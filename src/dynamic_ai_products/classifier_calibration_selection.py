"""Draw the calibration sample from the candidate cohort (ADR-127).

The full 4,045-row classifier run is expensive and, once made, is the thing
every later stage reads. Before authorizing it we run a small calibration over
a sample designed to surface the failures worth finding early: a prompt that
will not return valid axes, a tier rule that never resolves, a model deferring
to the admission context it was told to contest, quotes that do not resolve,
output hitting the token ceiling, and the real cost per row.

**Closed, deterministic, relational — never hand-picked.** Strata, quotas and
seed live in a digest-pinned config. The draw is a seeded per-(stratum, status)
sample over rows sorted canonically, so the same cohort and the same config
always yield the same rows, and changing the sample means editing a versioned
file rather than a call site.

**The archetype signal is sample design, not truth.** Strata are derived from
SCREEN_v1's candidate archetypes. That signal is a non-authoritative model
output the classifier is free to contradict; it says where a row was drawn
from and nothing about how it must classify, and it reaches the tier engine
nowhere. The dependency is recorded as a stated limitation rather than left for
a reader to infer.

**The 91 reviewer-admitted rows have no archetype signal at all.** They failed
screen validation twice, so no screen output exists for them. Placing them into
an economic stratum would mean inventing the signal, so they are a stratum of
their own, drawn by reviewer decision, and deliberately over-weighted: they are
2.2% of the cohort and a fifth of the calibration, because they are the
population nothing else has measured.

**No population literal.** The selection size is derived by summing what the
config asks for against what each stratum can supply. Writing the total down
would describe one cohort and would keep passing while describing another.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import yaml

from .classifier_candidate_cohort import (
    COHORT_MANIFEST_FILENAME,
    COHORT_RECORDS_FILENAME,
    require_classifier_candidate_cohort,
)
from .human_review_overlay import OVERLAY_MANIFEST_FILENAME
from .lineage_screen_release import (
    RELEASE_MANIFEST_FILENAME,
    RELEASE_RECORDS_FILENAME,
    require_screen_release,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.lineage_screen import (
    ScreenInputError,
    _decode_utf8,
    _load_schema,
    _sha256,
    _validate,
)

__all__ = [
    "CALIBRATION_SELECTION_FILENAME",
    "SELECTION_CONTRACT",
    "STRATA_RULES_RELATIVE_PATH",
    "CalibrationStrataRules",
    "build_calibration_selection",
    "load_strata_rules",
    "require_calibration_selection",
]

STRATA_RULES_RELATIVE_PATH = "configs/universe_classifier_calibration_strata_v1.yaml"
CALIBRATION_SELECTION_FILENAME = "universe_classifier_calibration_selection.json"
SELECTION_CONTRACT = "universe_classifier_calibration_selection@0.1.0"
SELECTION_KIND = "classifier_calibration_v1"
SELECTION_SCHEMA = "schemas/universe_classifier_calibration_selection.schema.json"
SAMPLING_ALGORITHM = "seeded_stratified_admission_archetype@1"

ADMITTED_STATUSES = ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN")

#: The predicate vocabulary a stratum may use. A config naming anything else is
#: refused when it loads rather than silently never matching.
MATCH_KEYS = frozenset({
    "admission_origin", "screen_doubt_any", "archetype_any",
    "mixed_software_and_non_software", "archetypes_subset_of_software",
})
DOUBT_KEYS = frozenset({
    "negative_or_boundary_evidence", "low_confidence", "not_plausible",
    "no_archetype",
})


class StrataRulesError(ValueError):
    """The strata config is unusable. Never repaired, never defaulted."""


@dataclass(frozen=True)
class CalibrationStrataRules:
    version: str
    sha256: str
    seed: int
    algorithm: str
    software: frozenset[str]
    non_software: frozenset[str]
    strata: tuple[dict[str, Any], ...]


def load_strata_rules(repo_root: str | Path) -> CalibrationStrataRules:
    """Load and validate the pinned strata config."""
    path = Path(repo_root) / STRATA_RULES_RELATIVE_PATH
    if not path.is_file():
        raise StrataRulesError(f"Calibration strata config not found: {path}")
    raw = path.read_bytes()
    config = yaml.safe_load(raw.decode("utf-8"))
    if not isinstance(config, dict):
        raise StrataRulesError("The strata config is not a mapping.")
    version = config.get("strata_rules_version")
    if not isinstance(version, str) or not version:
        raise StrataRulesError("The strata config declares no version.")
    seed = config.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool):
        raise StrataRulesError("The strata config declares no integer seed.")
    if config.get("sampling_algorithm") != SAMPLING_ALGORITHM:
        raise StrataRulesError(
            f"The strata config names sampling algorithm "
            f"{config.get('sampling_algorithm')!r}; this builder implements "
            f"{SAMPLING_ALGORITHM!r} only."
        )
    software = config.get("software_archetypes")
    non_software = config.get("non_software_archetypes")
    for label, terms in (("software_archetypes", software),
                         ("non_software_archetypes", non_software)):
        if not isinstance(terms, list) or not terms:
            raise StrataRulesError(f"The strata config declares no {label}.")
    overlap = set(software) & set(non_software)
    if overlap:
        raise StrataRulesError(
            f"Archetype terms {sorted(overlap)} are declared both software and "
            "non-software; the mixed-firm predicate would be incoherent."
        )
    strata = config.get("strata")
    if not isinstance(strata, list) or not strata:
        raise StrataRulesError("The strata config declares no strata.")
    seen: set[str] = set()
    for position, stratum in enumerate(strata, start=1):
        if not isinstance(stratum, dict):
            raise StrataRulesError(f"Stratum {position} is not a mapping.")
        rule_id = stratum.get("rule_id")
        if not isinstance(rule_id, str) or not rule_id:
            raise StrataRulesError(f"Stratum {position} declares no rule_id.")
        if rule_id in seen:
            raise StrataRulesError(f"Stratum id {rule_id!r} appears twice.")
        seen.add(rule_id)
        match = stratum.get("match") or {}
        if not isinstance(match, dict):
            raise StrataRulesError(f"Stratum {rule_id!r} has a non-mapping match.")
        for key in match:
            if key not in MATCH_KEYS:
                raise StrataRulesError(
                    f"Stratum {rule_id!r} matches on unknown key {key!r}."
                )
        for key in match.get("screen_doubt_any", []) or []:
            if key not in DOUBT_KEYS:
                raise StrataRulesError(
                    f"Stratum {rule_id!r} names unknown doubt signal {key!r}."
                )
        for term in match.get("archetype_any", []) or []:
            if term not in set(software) | set(non_software):
                raise StrataRulesError(
                    f"Stratum {rule_id!r} names archetype {term!r}, which is "
                    "outside the declared vocabulary."
                )
        quota = stratum.get("quota")
        if not isinstance(quota, dict):
            raise StrataRulesError(f"Stratum {rule_id!r} declares no quota.")
        rows, targets = quota.get("rows"), quota.get("status_targets")
        if not isinstance(rows, int) or isinstance(rows, bool) or rows < 1:
            raise StrataRulesError(f"Stratum {rule_id!r} has no positive row quota.")
        if not isinstance(targets, dict) or set(targets) != set(ADMITTED_STATUSES):
            raise StrataRulesError(
                f"Stratum {rule_id!r} must target exactly {list(ADMITTED_STATUSES)}."
            )
        if sum(targets.values()) != rows:
            raise StrataRulesError(
                f"Stratum {rule_id!r} targets {sum(targets.values())} row(s) by "
                f"status but asks for {rows}; the quota is self-contradictory."
            )
    last = strata[-1]
    if last.get("match"):
        raise StrataRulesError(
            "The final stratum must be unconditional, so every cohort row "
            "belongs to exactly one stratum and the partition is total."
        )
    return CalibrationStrataRules(
        version=version, sha256=_sha256(raw), seed=seed,
        algorithm=SAMPLING_ALGORITHM, software=frozenset(software),
        non_software=frozenset(non_software), strata=tuple(strata))


def _doubt_signals(screen_output: dict | None) -> set[str]:
    """Where the screen itself recorded doubt about its own reading."""
    if not screen_output:
        return set(DOUBT_KEYS)
    signals = set()
    if screen_output.get("negative_or_boundary_evidence"):
        signals.add("negative_or_boundary_evidence")
    if screen_output.get("confidence") == "low":
        signals.add("low_confidence")
    if screen_output.get("plausible_customer_facing_digital_product") is not True:
        signals.add("not_plausible")
    if not (screen_output.get("candidate_customer_value_archetypes") or []):
        signals.add("no_archetype")
    return signals


def assign_stratum(row: dict, screen_output: dict | None,
                   rules: CalibrationStrataRules) -> str:
    """The first stratum whose predicate holds. Total by construction."""
    archetypes = set(
        (screen_output or {}).get("candidate_customer_value_archetypes") or [])
    doubt = _doubt_signals(screen_output) if row["admission_origin"] == "model_screen" \
        else set()
    for stratum in rules.strata:
        match = stratum.get("match") or {}
        if not match:
            return stratum["rule_id"]
        origins = match.get("admission_origin")
        if origins is not None and row["admission_origin"] not in origins:
            continue
        if "screen_doubt_any" in match and not (doubt & set(match["screen_doubt_any"])):
            continue
        if "archetype_any" in match and not (archetypes & set(match["archetype_any"])):
            continue
        if match.get("mixed_software_and_non_software") and not (
                (archetypes & rules.software) and (archetypes & rules.non_software)):
            continue
        if match.get("archetypes_subset_of_software") and not (
                archetypes and archetypes <= rules.software):
            continue
        return stratum["rule_id"]
    raise StrataRulesError(
        "No stratum matched; load_strata_rules guarantees a total partition, so "
        "this config was not the one that was validated."
    )


def _draw(rule_id: str, pools: dict[str, list], targets: dict[str, int], seed: int
          ) -> tuple[dict[str, list], int]:
    """Seeded per-status draw with deterministic within-stratum reallocation.

    A status pool too thin to meet its target does not shrink the stratum: the
    shortfall moves to the other status, drawn from what that status has left,
    under its own seeded stream. Both the status order and the pool order are
    canonical, so the same inputs always give the same rows.
    """
    taken: dict[str, list] = {}
    shortfall = 0
    for status in ADMITTED_STATUSES:
        available = sorted(pools.get(status, []))
        want = min(targets[status], len(available))
        shortfall += targets[status] - want
        rng = random.Random(f"{seed}:{rule_id}:{status}")
        taken[status] = sorted(rng.sample(available, want)) if want else []
    reallocated = 0
    if shortfall:
        for status in ADMITTED_STATUSES:
            if not shortfall:
                break
            spare = sorted(set(pools.get(status, [])) - set(taken[status]))
            take = min(shortfall, len(spare))
            if not take:
                continue
            rng = random.Random(f"{seed}:{rule_id}:{status}:reallocate")
            taken[status] = sorted(taken[status] + sorted(rng.sample(spare, take)))
            shortfall -= take
            reallocated += take
    return taken, reallocated


def build_calibration_selection(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    cohort_manifest_sha256: str, release_manifest_path: str | Path,
    release_manifest_sha256: str, overlay_manifest_path: str | Path,
    overlay_manifest_sha256: str, output_path: str | Path, selection_id: str,
    clock: Callable[[], datetime], dry_run: bool = False,
) -> dict:
    """Derive and write one calibration selection, write-once. No model call."""
    root = Path(repo_root)
    rules = load_strata_rules(root)

    def pin(path, expected, filename, what):
        path = Path(path)
        if path.name != filename:
            raise ScreenInputError(
                f"The {what} manifest must be {filename}; {path.name} is a "
                "different artifact.")
        if not path.is_file():
            raise ScreenInputError(f"{what} manifest not found: {path}")
        raw = path.read_bytes()
        if _sha256(raw) != expected:
            raise ScreenInputError(
                f"The {what} manifest hashes to {_sha256(raw)}, but {expected} "
                "was pinned; this is not the artifact that was named.")
        return json.loads(_decode_utf8(raw, filename)), path

    cohort, cohort_path = pin(cohort_manifest_path, cohort_manifest_sha256,
                              COHORT_MANIFEST_FILENAME, "cohort")
    require_classifier_candidate_cohort(cohort_path.parent)
    release, release_path = pin(release_manifest_path, release_manifest_sha256,
                                RELEASE_MANIFEST_FILENAME, "release")
    require_screen_release(release_path.parent)
    overlay, _ = pin(overlay_manifest_path, overlay_manifest_sha256,
                     OVERLAY_MANIFEST_FILENAME, "overlay")
    if cohort["sources"]["release"]["manifest_sha256"] != release_manifest_sha256:
        raise ScreenInputError("The cohort was built from a different release.")
    if cohort["sources"]["overlay"]["manifest_sha256"] != overlay_manifest_sha256:
        raise ScreenInputError("The cohort was built from a different overlay.")

    def read(directory, filename, recorded):
        raw = (directory / filename).read_bytes()
        if _sha256(raw) != recorded:
            raise ScreenInputError(
                f"{filename} no longer hashes to the digest its manifest "
                "records; nothing may be read from it.")
        return raw

    cohort_raw = read(cohort_path.parent, COHORT_RECORDS_FILENAME,
                      cohort["output_hashes"][COHORT_RECORDS_FILENAME])
    rows = [json.loads(x) for x
            in _decode_utf8(cohort_raw, COHORT_RECORDS_FILENAME).splitlines()
            if x.strip()]
    if len(rows) != cohort["counts"]["cohort_rows"]:
        raise ScreenInputError("The cohort's record count disagrees with its manifest.")
    release_raw = read(release_path.parent, RELEASE_RECORDS_FILENAME,
                       release["output_hashes"][RELEASE_RECORDS_FILENAME])
    screen_by_key = {}
    for line in _decode_utf8(release_raw, RELEASE_RECORDS_FILENAME).splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        screen_by_key[(record["cik"], record["accession"])] = record.get("screen_output")

    by_row = {}
    pools: dict[str, dict[str, list]] = {s["rule_id"]: {} for s in rules.strata}
    for row in rows:
        key = (row["cik"], row["accession"])
        if key not in screen_by_key:
            raise ScreenInputError(f"Cohort row {key} is absent from the release.")
        rule_id = assign_stratum(row, screen_by_key[key], rules)
        by_row[key] = rule_id
        pools[rule_id].setdefault(row["screen_status"], []).append(key)
    if len(by_row) != len(rows):
        raise ScreenInputError("The cohort carries a duplicate row identity.")

    index = {(r["cik"], r["accession"]): r for r in rows}
    selected: list[dict] = []
    strata_report: list[dict] = []
    for stratum in rules.strata:
        rule_id = stratum["rule_id"]
        targets = dict(stratum["quota"]["status_targets"])
        taken, reallocated = _draw(rule_id, pools[rule_id], targets, rules.seed)
        pool_size = sum(len(v) for v in pools[rule_id].values())
        count = sum(len(v) for v in taken.values())
        if count > pool_size:
            raise ScreenInputError(
                f"Stratum {rule_id!r} drew more rows than it holds.")
        strata_report.append({
            "rule_id": rule_id, "pool": pool_size,
            "quota": stratum["quota"]["rows"], "status_targets": targets,
            "status_selected": {s: len(taken.get(s, [])) for s in ADMITTED_STATUSES},
            "selected": count, "reallocated": reallocated})
        for status in ADMITTED_STATUSES:
            for key in taken.get(status, []):
                row = index[key]
                selected.append({
                    "cik": row["cik"], "accession": row["accession"],
                    "company_id": row["company_id"], "form": row["form"],
                    "baseline_filing_date": row["baseline_filing_date"],
                    "source_id": row["source_id"],
                    "packet_sha256": row["packet_sha256"],
                    "admission_origin": row["admission_origin"],
                    "screen_status": row["screen_status"],
                    "stratum": rule_id, "stratum_rule_id": rule_id})
    if len({(r["cik"], r["accession"]) for r in selected}) != len(selected):
        raise ScreenInputError("The draw selected a row twice.")
    if len(selected) >= len(rows):
        raise ScreenInputError(
            "A calibration must be strictly smaller than the cohort it samples.")

    selection = {
        "selection_contract": SELECTION_CONTRACT, "selection_id": selection_id,
        "selection_kind": SELECTION_KIND, "cohort_id": cohort["cohort_id"],
        "cohort_manifest_path": str(cohort_path),
        "cohort_manifest_sha256": cohort_manifest_sha256,
        "cohort_records_jsonl_sha256": _sha256(cohort_raw),
        "release_manifest_sha256": release_manifest_sha256,
        "release_records_jsonl_sha256": _sha256(release_raw),
        "overlay_manifest_sha256": overlay_manifest_sha256,
        "packet_manifest_path": overlay["packet_source"]["packet_manifest_path"],
        "packet_manifest_sha256": overlay["packet_source"]["packet_manifest_sha256"],
        "strata_rules_path": STRATA_RULES_RELATIVE_PATH,
        "strata_rules_version": rules.version, "strata_rules_sha256": rules.sha256,
        "sampling": {"algorithm": rules.algorithm, "seed": rules.seed,
                     "strata": strata_report},
        "rows": selected,
        "counts": {
            "cohort_rows": len(rows), "selected_rows": len(selected),
            "by_admission_origin": {
                o: sum(r["admission_origin"] == o for r in selected)
                for o in ("model_screen", "human_review")},
            "by_screen_status": {
                s: sum(r["screen_status"] == s for r in selected)
                for s in ADMITTED_STATUSES},
            "by_stratum": {s["rule_id"]: s["selected"] for s in strata_report}},
        "no_model_call": True,
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "Strata were derived from SCREEN_v1 candidate archetypes. That "
            "signal is sample design only: it is a non-authoritative model "
            "output the classifier may contradict, it is not truth about a "
            "firm, and it is no input to the deterministic tier engine.",
            "The reviewer-admitted rows carry no screen output and therefore no "
            "archetype signal at all. They are sampled by reviewer decision, "
            "never placed into an economic stratum by inference.",
            "Reviewer-admitted rows are deliberately over-weighted relative to "
            "their cohort share, because that population is the one no earlier "
            "artifact has measured.",
            "This is a sample for calibration, not a universe. It settles no "
            "firm's membership and licenses no inference about the cohort's "
            "rates.",
        ],
    }
    _validate(selection, _load_schema(root, SELECTION_SCHEMA),
              "Calibration selection")
    if dry_run:
        return selection
    payload = (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_bytes_once(target, payload, what="calibration selection")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return selection


def require_calibration_selection(path: str | Path, *, expected_sha256: str) -> dict:
    """Load one selection by digest, refusing anything else."""
    target = Path(path)
    if target.name != CALIBRATION_SELECTION_FILENAME:
        raise ScreenInputError(
            f"A calibration selection must be {CALIBRATION_SELECTION_FILENAME}; "
            f"{target.name} is a different artifact.")
    if not target.is_file():
        raise ScreenInputError(f"Calibration selection not found: {target}")
    raw = target.read_bytes()
    if _sha256(raw) != expected_sha256:
        raise ScreenInputError(
            f"The calibration selection hashes to {_sha256(raw)}, but "
            f"{expected_sha256} was pinned; nothing runs.")
    selection = json.loads(_decode_utf8(raw, CALIBRATION_SELECTION_FILENAME))
    if selection.get("selection_contract") != SELECTION_CONTRACT:
        raise ScreenInputError(
            f"The artifact declares {selection.get('selection_contract')!r}; "
            f"this route consumes {SELECTION_CONTRACT!r} only.")
    return selection
