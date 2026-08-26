"""ADR-127 tests: the sample is drawn by rule, never by hand.

The fixture cohort is deliberately larger than the committed quotas ask for, so
every stratum is a real pool that the draw genuinely samples from rather than
exhausts. Nothing here is offline-by-accident: the selection builder makes no
model call at all, and a test asserts the module contains no provider surface.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_calibration_selection as ccs
from dynamic_ai_products import classifier_candidate_cohort as ccc
from dynamic_ai_products import human_review_overlay as hro
from dynamic_ai_products import lineage_screen_release as lrel
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import CLOCK, ROOT, _entry, _ledger, _quote, _sha  # noqa: E402
from test_lineage_screen_live import PACKET_FIXTURES, _fixture_doc  # noqa: E402
from test_lineage_screen_live_v3 import _v5_run  # noqa: E402

SELECTION_SCHEMA = json.loads(
    (ROOT / ccs.SELECTION_SCHEMA).read_text(encoding="utf-8"))

#: One archetype recipe per model-screen stratum, chosen so the committed
#: priority order sends each recipe to exactly the stratum it names.
RECIPES = {
    "S2_contradiction_or_boundary": ("doubt", ["FUNCTIONAL_SOFTWARE"]),
    "S3_physical_or_human_delivered_service": ("clean", ["HUMAN_MANAGED_SERVICE"]),
    "S4_hardware_software_system": ("clean", ["HARDWARE_SOFTWARE_SYSTEM"]),
    "S5_marketplace_transaction": ("clean", ["MARKETPLACE_COORDINATION"]),
    "S6_mixed_firm": ("clean", ["FUNCTIONAL_SOFTWARE", "ECOMMERCE_RETAIL"]),
    "S7_data_analytics_product": ("clean", ["DATA_ANALYTICS_PRODUCT"]),
    "S8_clear_core_software": ("clean", ["FUNCTIONAL_SOFTWARE"]),
    "S9_residual_non_software": ("clean", ["ECOMMERCE_RETAIL"]),
}
STATUSES = ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN")
#: Rows per (stratum, status). Four, so each pool strictly exceeds its quota and
#: the reviewer stratum stays a minority of the cohort, as it is in production.
PER_CELL = 4
#: Reviewer-admitted rows per decision, above S1's four-per-status target.
PER_DECISION = 6

_GOOGLE_BASELINE: set[str] | None = None


def _google_modules() -> set[str]:
    return {n for n in sys.modules if n == "google" or n.startswith("google.")}


@pytest.fixture(autouse=True)
def _google_module_baseline():
    global _GOOGLE_BASELINE
    if _GOOGLE_BASELINE is None:
        _GOOGLE_BASELINE = _google_modules()
    yield


def _assert_no_google() -> None:
    added = _google_modules() - (_GOOGLE_BASELINE or set())
    assert not added, f"the selection path imported google: {sorted(added)}"


# --- a cohort large enough for the committed quotas --------------------------------


def _plan():
    """(stratum, status, kind, archetypes) for every fixture row, in order."""
    plan = []
    for rule_id, (kind, archetypes) in RECIPES.items():
        for status in STATUSES:
            for _ in range(PER_CELL):
                plan.append((rule_id, status, kind, archetypes))
    for decision in ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN"):
        for _ in range(PER_DECISION):
            plan.append(("S1_human_review_no_screen_signal", decision,
                         "unresolved", []))
    return plan


@pytest.fixture(scope="module")
def packet_cohort(tmp_path_factory):
    source, template = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    docs = []
    for index in range(len(_plan())):
        cik = f"{8300000000 + index:010d}"
        docs.append((source, dict(template, cik=cik, accession=f"{cik}-22-000001")))
    built = _v5_run(tmp_path_factory.mktemp("adr127-packets"), [docs])
    assert len(built.packets) == len(_plan())
    return built


def _release_row(packet, status, kind, archetypes):
    raw = json.dumps({"screen_status": status}, sort_keys=True)
    unresolved = kind == "unresolved"
    origin = "unresolved_after_repair" if unresolved else "base_valid"
    evidence = [{"passage_id": packet["passages"][0]["passage_id"],
                 "quote": _quote(packet), "source_id": packet["source_id"],
                 "supported_claim": "The cited passage supports the screen."}]
    screen_output = None if unresolved else {
        "screen_status": status,
        "plausible_customer_facing_digital_product": True,
        "candidate_customer_value_archetypes": list(archetypes),
        "positive_evidence": evidence,
        "negative_or_boundary_evidence": evidence if kind == "doubt" else [],
        "missing_evidence": [], "confidence": "high"}
    return {
        "record_contract": lrel.RECORD_CONTRACT, "release_origin": origin,
        "record_kind": "model_evidence_unverified" if unresolved
        else "screened_packet",
        "cik": packet["cik"], "company_id": packet["company_id"],
        "accession": packet["accession"], "form": packet["form"],
        "baseline_filing_date": packet["baseline_filing_date"],
        "source_id": packet["source_id"], "packet_sha256": packet["packet_sha256"],
        "prompt_sha256": _sha(b"p"),
        "model_route": {"provider": "google_vertex_ai",
                        "model_label": "gemini-2.5-flash"},
        "screen_status": None if unresolved else status,
        "screen_output": screen_output,
        "failure_reason_code": "quote_resolution_failure" if unresolved else None,
        "failure_detail": "detail" if unresolved else None,
        "truncation_evidence": None,
        "release_provenance": {
            "base": {"run_id": "synthetic-base-run",
                     "raw_response_id": f"base-{packet['cik']}",
                     "raw_response_sha256": _sha(raw.encode()),
                     "failure_reason_code": "quote_resolution_failure"
                     if unresolved else None,
                     "source_row_ordinal": 1},
            "repair": {"run_id": "synthetic-repair-run",
                       "raw_response_id": f"repair-{packet['cik']}",
                       "raw_response_sha256": _sha((raw + "r").encode()),
                       "failure_reason_code": "quote_resolution_failure",
                       "source_row_ordinal": None} if unresolved else None},
    }


@pytest.fixture
def release(packet_cohort, tmp_path):
    plan = _plan()
    rows = [_release_row(p, status, kind, archetypes)
            for p, (_rule, status, kind, archetypes) in zip(packet_cohort.packets, plan)]
    d = tmp_path / "release" / "synthetic-release"
    d.mkdir(parents=True, exist_ok=True)
    records = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                      for r in rows).encode()
    (d / lrel.RELEASE_RECORDS_FILENAME).write_bytes(records)
    base_dir = tmp_path / "base" / "synthetic-base-run"
    base_dir.mkdir(parents=True, exist_ok=True)
    from dynamic_ai_products import lineage_screen_continuation_v5 as lc5
    base_path = base_dir / lc5.CONTINUATION_V5_MANIFEST_FILENAME
    base_path.write_bytes((json.dumps({
        "manifest_contract": "universe_screen_continuation_manifest@0.12.0",
        "run_id": "synthetic-base-run",
        "packet_manifest_path": str(packet_cohort.manifest_path),
        "packet_manifest_sha256": _sha(Path(packet_cohort.manifest_path).read_bytes()),
        "packets_jsonl_sha256": ls.load_packet_run(
            ROOT, packet_cohort.manifest_path).packets_jsonl_sha256,
    }, indent=2, sort_keys=True) + "\n").encode())
    validated = [r for r in rows if r["screen_status"]]
    manifest = {
        "manifest_contract": lrel.MANIFEST_CONTRACT,
        "release_id": "synthetic-release", "release_kind": "screen_release_v1",
        "counts": {
            "planned_rows": len(rows), "cohort_rows": len(rows),
            "base_valid": len(validated), "repaired": 0,
            "unresolved_after_repair": len(rows) - len(validated),
            "insufficient_evidence": 0, "model_output_truncated": 0,
            "valid_screened_rows": len(validated),
            "max_unresolved_after_repair": 211,
            "by_screen_status": {
                s: sum(r["screen_status"] == s for r in rows)
                for s in ("LIKELY_ELIGIBLE", "LIKELY_INELIGIBLE",
                          "BOUNDARY_OR_UNCERTAIN")}},
        "sources": {"base": {"run_id": "synthetic-base-run",
                             "manifest_path": str(base_path),
                             "manifest_sha256": _sha(base_path.read_bytes())}},
        "output_hashes": {lrel.RELEASE_RECORDS_FILENAME: _sha(records)},
    }
    path = d / lrel.RELEASE_MANIFEST_FILENAME
    path.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return SimpleNamespace(dir=d, path=path, rows=rows, plan=plan,
                           sha256=_sha(path.read_bytes()),
                           packets={(p["cik"], p["accession"]): p
                                    for p in packet_cohort.packets})


@pytest.fixture
def cohort(release, packet_cohort, tmp_path):
    unresolved = [(r, release.packets[(r["cik"], r["accession"])])
                  for r in release.rows
                  if r["release_origin"] == "unresolved_after_repair"]
    decisions = [status for _rule, status, kind, _a in release.plan
                 if kind == "unresolved"]
    entries = [_entry(release, packet, decision)
               for (_row, packet), decision in zip(unresolved, decisions)]
    overlay = hro.build_human_review_overlay(
        repo_root=ROOT, release_manifest_path=release.path,
        release_manifest_sha256=release.sha256,
        ledger_path=_ledger(tmp_path, entries), output_dir=tmp_path / "overlays",
        overlay_id="overlay-fixture", clock=CLOCK)
    built = ccc.build_classifier_candidate_cohort(
        repo_root=ROOT, release_manifest_path=release.path,
        release_manifest_sha256=release.sha256,
        overlay_manifest_path=overlay.manifest_path,
        overlay_manifest_sha256=_sha(overlay.manifest_path.read_bytes()),
        output_dir=tmp_path / "cohorts", cohort_id="cohort-fixture", clock=CLOCK)
    rows = [json.loads(x) for x in
            (built.cohort_dir / ccc.COHORT_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]
    return SimpleNamespace(
        path=built.manifest_path, sha256=_sha(built.manifest_path.read_bytes()),
        rows=rows, release=release, overlay=overlay,
        overlay_path=overlay.manifest_path,
        overlay_sha256=_sha(overlay.manifest_path.read_bytes()),
        packets=packet_cohort,
        packet_manifest_path=packet_cohort.manifest_path,
        packet_manifest_sha256=packet_cohort.manifest_sha256)


def _build(cohort, tmp_path, *, selection_id="calibration-selection-fixture",
           dry_run=False, name="selection"):
    return ccs.build_calibration_selection(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        cohort_manifest_sha256=cohort.sha256,
        release_manifest_path=cohort.release.path,
        release_manifest_sha256=cohort.release.sha256,
        overlay_manifest_path=cohort.overlay_path,
        overlay_manifest_sha256=cohort.overlay_sha256,
        output_path=tmp_path / name / ccs.CALIBRATION_SELECTION_FILENAME,
        selection_id=selection_id, clock=CLOCK, dry_run=dry_run)


def _expected_total(rules, cohort):
    """What the config asks for, capped by what each stratum can supply."""
    pools: dict[str, dict[str, int]] = {}
    screen = {(r["cik"], r["accession"]): r.get("screen_output")
              for r in cohort.release.rows}
    for row in cohort.rows:
        rule_id = ccs.assign_stratum(row, screen[(row["cik"], row["accession"])], rules)
        pools.setdefault(rule_id, {}).setdefault(row["screen_status"], 0)
        pools[rule_id][row["screen_status"]] += 1
    total = 0
    for stratum in rules.strata:
        targets = stratum["quota"]["status_targets"]
        available = pools.get(stratum["rule_id"], {})
        taken = {s: min(targets[s], available.get(s, 0)) for s in targets}
        shortfall = sum(targets.values()) - sum(taken.values())
        spare = sum(available.get(s, 0) - taken[s] for s in targets)
        total += sum(taken.values()) + min(shortfall, spare)
    return total


# --- the committed config ----------------------------------------------------------


def test_the_committed_config_loads_and_pins_itself():
    from hashlib import sha256
    rules = ccs.load_strata_rules(ROOT)
    raw = (ROOT / ccs.STRATA_RULES_RELATIVE_PATH).read_bytes()
    assert rules.sha256 == sha256(raw).hexdigest()
    assert rules.version == "universe_classifier_calibration_strata_v1"
    assert rules.seed == 20260824
    assert rules.algorithm == ccs.SAMPLING_ALGORITHM
    assert len({s["rule_id"] for s in rules.strata}) == len(rules.strata)


def test_the_committed_quotas_are_the_approved_ones():
    rules = ccs.load_strata_rules(ROOT)
    quotas = {s["rule_id"]: s["quota"] for s in rules.strata}
    human = quotas["S1_human_review_no_screen_signal"]
    assert human["status_targets"] == {"LIKELY_ELIGIBLE": 4,
                                       "BOUNDARY_OR_UNCERTAIN": 4}
    for rule_id, quota in quotas.items():
        if rule_id == "S1_human_review_no_screen_signal":
            continue
        assert quota["status_targets"] == {"LIKELY_ELIGIBLE": 2,
                                           "BOUNDARY_OR_UNCERTAIN": 2}
    assert quotas["S3_physical_or_human_delivered_service"]


def test_the_folded_stratum_keeps_its_approved_name():
    rules = ccs.load_strata_rules(ROOT)
    ids = [s["rule_id"] for s in rules.strata]
    assert "S3_physical_or_human_delivered_service" in ids
    assert not [i for i in ids if i.startswith("S3_physical_service_interface")]


def test_the_partition_is_total_and_ordered(cohort):
    """Every cohort row lands in exactly one stratum, and the order decides."""
    rules = ccs.load_strata_rules(ROOT)
    screen = {(r["cik"], r["accession"]): r.get("screen_output")
              for r in cohort.release.rows}
    assigned = [ccs.assign_stratum(r, screen[(r["cik"], r["accession"])], rules)
                for r in cohort.rows]
    assert len(assigned) == len(cohort.rows)
    assert set(assigned) <= {s["rule_id"] for s in rules.strata}
    expected = {rule for rule, _s, _k, _a in cohort.release.plan}
    assert set(assigned) == expected


def test_a_reviewer_admitted_row_never_enters_an_economic_stratum(cohort):
    rules = ccs.load_strata_rules(ROOT)
    for row in cohort.rows:
        if row["admission_origin"] == "human_review":
            assert ccs.assign_stratum(row, None, rules) == \
                "S1_human_review_no_screen_signal"


def test_a_contradicted_row_outranks_its_archetypes(cohort):
    """Doubt is decided before any economic stratum can claim the row."""
    rules = ccs.load_strata_rules(ROOT)
    row = next(r for r in cohort.rows if r["admission_origin"] == "model_screen")
    doubtful = {"screen_status": "LIKELY_ELIGIBLE",
                "plausible_customer_facing_digital_product": True,
                "candidate_customer_value_archetypes": ["HARDWARE_SOFTWARE_SYSTEM"],
                "negative_or_boundary_evidence": [{"quote": "x"}],
                "confidence": "high"}
    assert ccs.assign_stratum(row, doubtful, rules) == "S2_contradiction_or_boundary"
    clean = dict(doubtful, negative_or_boundary_evidence=[])
    assert ccs.assign_stratum(row, clean, rules) == "S4_hardware_software_system"


# --- the draw ----------------------------------------------------------------------


def test_the_selection_derives_its_size_from_the_config(cohort, tmp_path):
    rules = ccs.load_strata_rules(ROOT)
    selection = _build(cohort, tmp_path)
    validator = Draft202012Validator(SELECTION_SCHEMA, format_checker=FormatChecker())
    validator.validate(selection)
    assert selection["counts"]["selected_rows"] == _expected_total(rules, cohort)
    assert selection["counts"]["selected_rows"] == len(selection["rows"])
    assert selection["counts"]["selected_rows"] < selection["counts"]["cohort_rows"]
    _assert_no_google()


def test_each_stratum_contributes_exactly_its_quota(cohort, tmp_path):
    rules = ccs.load_strata_rules(ROOT)
    selection = _build(cohort, tmp_path)
    quotas = {s["rule_id"]: s["quota"]["rows"] for s in rules.strata}
    for stratum in selection["sampling"]["strata"]:
        assert stratum["selected"] == min(quotas[stratum["rule_id"]],
                                          stratum["pool"])
        assert stratum["selected"] == selection["counts"]["by_stratum"][
            stratum["rule_id"]]
        assert stratum["pool"] >= stratum["selected"], "the pool was exhausted"


def test_the_status_split_is_the_configured_one(cohort, tmp_path):
    rules = ccs.load_strata_rules(ROOT)
    selection = _build(cohort, tmp_path)
    targets = {s["rule_id"]: s["quota"]["status_targets"] for s in rules.strata}
    for stratum in selection["sampling"]["strata"]:
        assert stratum["status_selected"] == targets[stratum["rule_id"]]
        assert stratum["reallocated"] == 0, "no fixture stratum is short"


def test_the_reviewer_rows_are_over_represented(cohort, tmp_path):
    selection = _build(cohort, tmp_path)
    selected = selection["counts"]["by_admission_origin"]["human_review"]
    cohort_share = sum(r["admission_origin"] == "human_review"
                       for r in cohort.rows) / len(cohort.rows)
    assert selected / selection["counts"]["selected_rows"] > cohort_share
    assert selection["counts"]["by_stratum"][
        "S1_human_review_no_screen_signal"] == selected


def test_the_draw_is_reproducible(cohort, tmp_path):
    first = _build(cohort, tmp_path, name="a")
    second = _build(cohort, tmp_path, name="b")
    assert [(r["cik"], r["accession"]) for r in first["rows"]] == \
        [(r["cik"], r["accession"]) for r in second["rows"]]
    assert first["sampling"]["seed"] == 20260824


def test_the_seed_changes_the_sample(cohort, tmp_path, monkeypatch):
    """Proof the draw is actually seeded rather than an ordering artefact."""
    baseline = _build(cohort, tmp_path, name="baseline")
    real = ccs.load_strata_rules
    monkeypatch.setattr(ccs, "load_strata_rules", lambda root: SimpleNamespace(
        **{**real(root).__dict__, "seed": 999}))
    other = _build(cohort, tmp_path, name="other")
    assert [(r["cik"], r["accession"]) for r in other["rows"]] != \
        [(r["cik"], r["accession"]) for r in baseline["rows"]]
    assert len(other["rows"]) == len(baseline["rows"])


def test_every_selected_row_is_a_cohort_row(cohort, tmp_path):
    selection = _build(cohort, tmp_path)
    known = {(r["cik"], r["accession"]): r for r in cohort.rows}
    for row in selection["rows"]:
        source = known[(row["cik"], row["accession"])]
        assert row["screen_status"] == source["screen_status"]
        assert row["admission_origin"] == source["admission_origin"]
        assert row["packet_sha256"] == source["packet_sha256"]
    assert len({(r["cik"], r["accession"]) for r in selection["rows"]}) == \
        len(selection["rows"])


def test_the_selection_binds_its_whole_source_chain(cohort, tmp_path):
    selection = _build(cohort, tmp_path)
    assert selection["cohort_manifest_sha256"] == cohort.sha256
    assert selection["release_manifest_sha256"] == cohort.release.sha256
    assert selection["overlay_manifest_sha256"] == cohort.overlay_sha256
    assert selection["packet_manifest_sha256"] == cohort.packet_manifest_sha256
    assert selection["strata_rules_sha256"] == ccs.load_strata_rules(ROOT).sha256
    assert selection["no_model_call"] is True


def test_the_archetype_limitation_is_stated(cohort, tmp_path):
    selection = _build(cohort, tmp_path)
    joined = " ".join(selection["limitations"]).lower()
    assert "sample design" in joined
    assert "not truth about a firm" in joined
    assert "no input to the deterministic tier engine" in joined
    assert "no screen output" in joined


def test_a_selection_is_written_once(cohort, tmp_path):
    _build(cohort, tmp_path, name="once")
    with pytest.raises(ls.ScreenInputError):
        _build(cohort, tmp_path, name="once")


def test_a_dry_run_writes_nothing(cohort, tmp_path):
    selection = _build(cohort, tmp_path, dry_run=True, name="dry")
    assert not (tmp_path / "dry").exists()
    assert selection["counts"]["selected_rows"] >= 1


def test_a_wrong_cohort_digest_is_refused(cohort, tmp_path):
    with pytest.raises(ls.ScreenInputError, match="was pinned"):
        ccs.build_calibration_selection(
            repo_root=ROOT, cohort_manifest_path=cohort.path,
            cohort_manifest_sha256="0" * 64,
            release_manifest_path=cohort.release.path,
            release_manifest_sha256=cohort.release.sha256,
            overlay_manifest_path=cohort.overlay_path,
            overlay_manifest_sha256=cohort.overlay_sha256,
            output_path=tmp_path / "x" / ccs.CALIBRATION_SELECTION_FILENAME,
            selection_id="x", clock=CLOCK)


def test_a_drifted_cohort_records_file_is_refused(cohort, tmp_path):
    records = cohort.path.parent / ccc.COHORT_RECORDS_FILENAME
    records.write_bytes(records.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError, match="no longer hashes"):
        _build(cohort, tmp_path, name="drifted")


def test_the_loader_refuses_a_foreign_or_undigested_artifact(cohort, tmp_path):
    _build(cohort, tmp_path, name="load")
    path = tmp_path / "load" / ccs.CALIBRATION_SELECTION_FILENAME
    digest = _sha(path.read_bytes())
    assert ccs.require_calibration_selection(path, expected_sha256=digest)
    with pytest.raises(ls.ScreenInputError, match="was pinned"):
        ccs.require_calibration_selection(path, expected_sha256="0" * 64)
    other = tmp_path / "load" / "not_a_selection.json"
    other.write_bytes(path.read_bytes())
    with pytest.raises(ls.ScreenInputError, match="different artifact"):
        ccs.require_calibration_selection(other, expected_sha256=digest)


# --- config refusals ---------------------------------------------------------------


def _write_config(tmp_path, mutate):
    config = yaml.safe_load(
        (ROOT / ccs.STRATA_RULES_RELATIVE_PATH).read_text(encoding="utf-8"))
    mutate(config)
    root = tmp_path / "repo"
    (root / "configs").mkdir(parents=True, exist_ok=True)
    (root / ccs.STRATA_RULES_RELATIVE_PATH).write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root


@pytest.mark.parametrize("mutate,match", [
    (lambda c: c.pop("strata_rules_version"), "no version"),
    (lambda c: c.__setitem__("seed", "20260824"), "integer seed"),
    (lambda c: c.__setitem__("sampling_algorithm", "coin_flip@1"), "implements"),
    (lambda c: c["strata"][0]["match"].__setitem__("tier", ["TIER_A"]),
     "unknown key"),
    (lambda c: c["strata"][2]["match"].__setitem__("archetype_any", ["NOT_A_TERM"]),
     "outside the declared vocabulary"),
    (lambda c: c["strata"][1]["match"].__setitem__("screen_doubt_any", ["vibes"]),
     "unknown doubt signal"),
    (lambda c: c["strata"][0]["quota"]["status_targets"].__setitem__(
        "LIKELY_ELIGIBLE", 99), "self-contradictory"),
    (lambda c: c["strata"].insert(1, dict(c["strata"][0])), "appears twice"),
    (lambda c: c["strata"][-1].__setitem__("match", {"archetype_any": ["OTHER"]}),
     "unconditional"),
    (lambda c: c["software_archetypes"].append("ECOMMERCE_RETAIL"),
     "both software and non-software"),
    (lambda c: c.__setitem__("strata", []), "no strata"),
])
def test_an_unusable_config_is_refused(tmp_path, mutate, match):
    with pytest.raises(ccs.StrataRulesError, match=match):
        ccs.load_strata_rules(_write_config(tmp_path, mutate))


def test_a_missing_config_is_refused(tmp_path):
    with pytest.raises(ccs.StrataRulesError, match="not found"):
        ccs.load_strata_rules(tmp_path / "nowhere")


def test_the_builder_carries_no_provider_surface():
    source = (ROOT / "src/dynamic_ai_products/classifier_calibration_selection.py"
              ).read_text(encoding="utf-8")
    for forbidden in ("genai", "vertex", "httpx", "requests", "generate_content"):
        assert forbidden not in source, forbidden


def test_no_population_literal_appears_in_the_builder():
    """The size is derived. A literal would describe one cohort forever.

    Read as tokens, not as text: a number inside a comment or a docstring is
    prose, and only a numeric literal in code could actually fix a population.
    """
    import io
    import tokenize
    path = ROOT / "src/dynamic_ai_products/classifier_calibration_selection.py"
    numbers = [tok.string for tok in
               tokenize.generate_tokens(io.StringIO(
                   path.read_text(encoding="utf-8")).readline)
               if tok.type == tokenize.NUMBER]
    for literal in numbers:
        assert int(literal) < 10, f"population literal {literal} in the builder"


# --- the CLI boundary --------------------------------------------------------------


def _cli_module():
    """Import the pipeline CLI once, by path, without executing main()."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adr127_cli", ROOT / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SELECT_ARGV = ["--mode", "select-classifier-calibration-rows",
               "--cohort-manifest", "c.json", "--cohort-manifest-sha256", "0" * 64,
               "--release-manifest", "r.json", "--release-manifest-sha256", "0" * 64,
               "--overlay-manifest", "o.json", "--overlay-manifest-sha256", "0" * 64,
               "--output-dir", "out", "--run-id", "cli-gating-fixture"]
RUN_ARGV = ["--mode", "classify-universe-calibration",
            "--cohort-manifest", "c.json", "--overlay-manifest", "o.json",
            "--release-manifest", "r.json", "--packet-manifest", "p.json",
            "--calibration-selection", "s.json", "--governance-root", "gov",
            "--screen-authorization", "a.json",
            "--screen-authorization-sha256", "0" * 64,
            "--output-dir", "out", "--run-id", "cli-gating-fixture"]
REVIEW_ARGV = ["--mode", "build-classifier-calibration-review",
               "--calibration-run-dir", "run", "--calibration-selection", "s.json",
               "--calibration-selection-sha256", "0" * 64,
               "--output-dir", "out", "--run-id", "cli-gating-fixture"]


@pytest.mark.parametrize("argv", [SELECT_ARGV, RUN_ARGV, REVIEW_ARGV])
def test_each_calibration_mode_accepts_the_flags_it_requires(argv):
    """ADR-123's lesson: a mode unreachable through its own flags is a defect."""
    cli = _cli_module()
    args = cli.build_parser().parse_args(argv)
    assert cli._reject_cross_mode_flags(args) is None
    _assert_no_google()


@pytest.mark.parametrize("argv,flag", [
    (SELECT_ARGV, "--cohort-manifest"), (SELECT_ARGV, "--cohort-manifest-sha256"),
    (SELECT_ARGV, "--release-manifest-sha256"),
    (SELECT_ARGV, "--overlay-manifest-sha256"),
    (RUN_ARGV, "--calibration-selection"), (RUN_ARGV, "--packet-manifest"),
    (RUN_ARGV, "--screen-authorization-sha256"),
    (REVIEW_ARGV, "--calibration-run-dir"),
    (REVIEW_ARGV, "--calibration-selection-sha256"),
])
def test_each_calibration_mode_still_requires_every_flag(argv, flag):
    cli = _cli_module()
    trimmed = list(argv)
    index = trimmed.index(flag)
    del trimmed[index:index + 2]
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(trimmed))
    assert verdict and "requires" in verdict and flag in verdict


@pytest.mark.parametrize("argv,flag,value", [
    (RUN_ARGV, "--cohort-manifest-sha256", "0" * 64),
    (RUN_ARGV, "--calibration-run-dir", "run"),
    (RUN_ARGV, "--selection-artifact", "sel.json"),
    (SELECT_ARGV, "--calibration-selection", "s.json"),
    (SELECT_ARGV, "--governance-root", "gov"),
    (REVIEW_ARGV, "--cohort-manifest", "c.json"),
])
def test_a_calibration_mode_refuses_a_flag_that_is_not_its_own(argv, flag, value):
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(
        cli.build_parser().parse_args(list(argv) + [flag, value]))
    assert verdict and flag in verdict


def test_no_other_mode_accepts_the_calibration_flags():
    cli = _cli_module()
    for flag in ("--calibration-selection", "--calibration-run-dir",
                 "--calibration-selection-sha256", "--cohort-manifest-sha256"):
        argv = ["--mode", "build-screen-release", flag, "x",
                "--output-dir", "out", "--run-id", "cli-gating-fixture"]
        verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(argv))
        assert verdict and flag in verdict


def test_the_cli_declares_all_three_modes():
    cli = _cli_module()
    choices = next(a.choices for a in cli.build_parser()._actions
                   if a.dest == "mode")
    for mode in ("select-classifier-calibration-rows",
                 "classify-universe-calibration",
                 "build-classifier-calibration-review"):
        assert mode in choices
    assert "Fifty-eight mutually exclusive modes" in cli.__doc__


# --- dry-run semantics at the CLI boundary -----------------------------------------


def _select_argv(cohort, out_dir, *, run_id, dry_run):
    argv = ["--mode", "select-classifier-calibration-rows",
            "--cohort-manifest", str(cohort.path),
            "--cohort-manifest-sha256", cohort.sha256,
            "--release-manifest", str(cohort.release.path),
            "--release-manifest-sha256", cohort.release.sha256,
            "--overlay-manifest", str(cohort.overlay_path),
            "--overlay-manifest-sha256", cohort.overlay_sha256,
            "--output-dir", str(out_dir), "--run-id", run_id]
    return argv + (["--dry-run"] if dry_run else [])


def _invoke(cli, cohort, out_dir, *, run_id, dry_run):
    args = cli.build_parser().parse_args(
        _select_argv(cohort, out_dir, run_id=run_id, dry_run=dry_run))
    assert cli._reject_cross_mode_flags(args) is None
    return cli._main_select_classifier_calibration_rows(args)


def test_a_dry_run_reserves_no_selection_id(cohort, tmp_path, capsys):
    """A dry run computes the sample and leaves the id free for the real run.

    The run directory is the write-once reservation, so creating it before
    knowing whether anything will be written would burn an id on an invocation
    that produces no artifact.
    """
    cli = _cli_module()
    out = tmp_path / "cli-dry"
    assert _invoke(cli, cohort, out, run_id="dry-selection", dry_run=True) == 0
    assert not (out / "dry-selection").exists(), "a dry run reserved the run id"
    assert not out.exists(), "a dry run created the output parent"
    reported = json.loads(capsys.readouterr().out)
    assert reported["dry_run"] is True
    assert reported["output_path"] is None
    assert reported["counts"]["selected_rows"] >= 1
    assert reported["sampling"]["seed"] == 20260824
    assert len(reported["sampling"]["strata"]) >= 1
    _assert_no_google()


def test_a_dry_run_leaves_the_id_free_for_the_real_run(cohort, tmp_path, capsys):
    cli = _cli_module()
    out = tmp_path / "cli-then-real"
    assert _invoke(cli, cohort, out, run_id="shared-id", dry_run=True) == 0
    dry = json.loads(capsys.readouterr().out)
    assert _invoke(cli, cohort, out, run_id="shared-id", dry_run=False) == 0
    real = json.loads(capsys.readouterr().out)
    assert (out / "shared-id" / ccs.CALIBRATION_SELECTION_FILENAME).is_file()
    assert real["counts"] == dry["counts"]
    assert real["output_path"] == str(
        out / "shared-id" / ccs.CALIBRATION_SELECTION_FILENAME)


def test_a_real_run_creates_exactly_its_write_once_target(cohort, tmp_path,
                                                          capsys):
    cli = _cli_module()
    out = tmp_path / "cli-real"
    assert _invoke(cli, cohort, out, run_id="real-selection", dry_run=False) == 0
    target = out / "real-selection"
    assert target.is_dir()
    assert [p.name for p in target.iterdir()] == [
        ccs.CALIBRATION_SELECTION_FILENAME]
    assert [p.name for p in out.iterdir()] == ["real-selection"]
    reported = json.loads(capsys.readouterr().out)
    assert reported["dry_run"] is False
    assert reported["output_path"] == str(
        target / ccs.CALIBRATION_SELECTION_FILENAME)
    written = target / ccs.CALIBRATION_SELECTION_FILENAME
    assert json.loads(written.read_text(encoding="utf-8"))["selection_id"] == \
        "real-selection"


def test_a_second_real_run_with_the_same_id_is_refused(cohort, tmp_path, capsys):
    """Write-once is unchanged: the reservation still refuses a second run."""
    cli = _cli_module()
    out = tmp_path / "cli-twice"
    assert _invoke(cli, cohort, out, run_id="same-id", dry_run=False) == 0
    capsys.readouterr()
    written = out / "same-id" / ccs.CALIBRATION_SELECTION_FILENAME
    before = _sha(written.read_bytes())
    assert _invoke(cli, cohort, out, run_id="same-id", dry_run=False) == 2
    captured = capsys.readouterr()
    assert "written once" in captured.err
    assert _sha(written.read_bytes()) == before, "the artifact was overwritten"


def test_a_dry_run_after_a_real_run_still_reports(cohort, tmp_path, capsys):
    """A dry run reads nothing it must not, and never trips the reservation."""
    cli = _cli_module()
    out = tmp_path / "cli-after"
    assert _invoke(cli, cohort, out, run_id="taken", dry_run=False) == 0
    capsys.readouterr()
    assert _invoke(cli, cohort, out, run_id="taken", dry_run=True) == 0
    reported = json.loads(capsys.readouterr().out)
    assert reported["dry_run"] is True and reported["output_path"] is None


# --- ADR-128: the three V2.2 modes must be reachable through their own flags -------

SHA_PLACEHOLDER = "0" * 64

V2_2_COHORT_ARGV = [
    "--mode", "classify-universe-cohort-v2-2",
    "--cohort-manifest", "c.json", "--overlay-manifest", "o.json",
    "--release-manifest", "r.json", "--packet-manifest", "p.json",
    "--governance-root", "gov", "--screen-authorization", "a.json",
    "--screen-authorization-sha256", SHA_PLACEHOLDER,
    "--output-dir", "out", "--run-id", "cli-gating-fixture",
]
V2_2_CONTINUATION_ARGV = V2_2_COHORT_ARGV[:2] + [
    "--source-run-dir", "src", "--source-receipt-sha256", SHA_PLACEHOLDER,
] + V2_2_COHORT_ARGV[2:]
V2_2_CONTINUATION_ARGV[1] = "classify-universe-cohort-continuation-v2-2"
V2_2_CALIBRATION_ARGV = ["--mode", "classify-universe-calibration-v2-2",
                         "--calibration-selection", "s.json"] + V2_2_COHORT_ARGV[2:]

V2_2_MODES = [
    ("classify-universe-cohort-v2-2", V2_2_COHORT_ARGV),
    ("classify-universe-cohort-continuation-v2-2", V2_2_CONTINUATION_ARGV),
    ("classify-universe-calibration-v2-2", V2_2_CALIBRATION_ARGV),
]


@pytest.mark.parametrize("mode,argv", V2_2_MODES, ids=[m for m, _ in V2_2_MODES])
def test_each_v2_2_mode_accepts_its_complete_required_argv(mode, argv):
    """ADR-123's lesson, missed again in ADR-128 and pinned here.

    A mode whose own required-flag table demands a flag the shared allow-list
    refuses is unreachable: every invocation dies at the argument gate before
    preflight. The V2.1 modes had this coverage; the V2.2 successors did not,
    and exactly one of them shipped unreachable.
    """
    cli = _cli_module()
    args = cli.build_parser().parse_args(argv)
    assert args.mode == mode
    assert cli._reject_cross_mode_flags(args) is None
    _assert_no_google()


def test_the_v2_2_calibration_mode_accepts_its_selection_flag():
    """The exact defect: --calibration-selection beside every other required flag."""
    cli = _cli_module()
    args = cli.build_parser().parse_args(V2_2_CALIBRATION_ARGV)
    assert args.calibration_selection == "s.json"
    for attr in ("cohort_manifest", "overlay_manifest", "release_manifest",
                 "packet_manifest", "governance_root", "screen_authorization",
                 "screen_authorization_sha256", "output_dir", "run_id"):
        assert getattr(args, attr), attr
    verdict = cli._reject_cross_mode_flags(args)
    assert verdict is None, verdict


#: Every flag in the V2.2 calibration mode's required-flag table, in table
#: order. Two of them -- --output-dir and --run-id -- are enforced by argparse
#: itself rather than by _reject_cross_mode_flags, so omitting one exits at
#: parse time and the cross-mode gate never runs. Both layers are refusals;
#: the test asserts whichever one actually applies, so the list can mirror the
#: table exactly and the test's name stays true.
V2_2_CALIBRATION_REQUIRED_FLAGS = [
    "--cohort-manifest", "--overlay-manifest", "--release-manifest",
    "--packet-manifest", "--calibration-selection", "--governance-root",
    "--screen-authorization", "--screen-authorization-sha256",
    "--output-dir", "--run-id",
]


@pytest.mark.parametrize("flag", V2_2_CALIBRATION_REQUIRED_FLAGS)
def test_the_v2_2_calibration_mode_still_requires_every_flag(flag, capsys):
    """Accepting a flag must not make it optional."""
    cli = _cli_module()
    parser = cli.build_parser()
    enforced_by_argparse = {option for action in parser._actions if action.required
                            for option in action.option_strings}
    trimmed = list(V2_2_CALIBRATION_ARGV)
    index = trimmed.index(flag)
    del trimmed[index:index + 2]
    if flag in enforced_by_argparse:
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(trimmed)
        assert excinfo.value.code == 2
        assert flag in capsys.readouterr().err
    else:
        verdict = cli._reject_cross_mode_flags(parser.parse_args(trimmed))
        assert verdict and "requires" in verdict and flag in verdict


def test_the_required_flag_list_covers_the_modes_whole_table():
    """The list above mirrors the CLI's own table; drift would hide a flag."""
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    start = source.index('("classify-universe-calibration-v2-2", ((')
    table = source[start:source.index('("classify-universe-calibration",', start)]
    declared = re.findall(r'\("(--[a-z0-9-]+)"', table)
    assert declared == V2_2_CALIBRATION_REQUIRED_FLAGS
    assert len(set(declared)) == len(declared) == 10


@pytest.mark.parametrize("mode,argv", [
    ("classify-universe-cohort-v2-2", V2_2_COHORT_ARGV),
    ("classify-universe-cohort-continuation-v2-2", V2_2_CONTINUATION_ARGV),
], ids=["cohort-v2-2", "continuation-v2-2"])
def test_a_v2_2_run_mode_still_rejects_the_selection_flag(mode, argv):
    """Only the calibration route takes a selection; widening one allow-list
    must not have widened the others."""
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(
        list(argv) + ["--calibration-selection", "s.json"]))
    assert verdict and "--calibration-selection" in verdict


def test_the_v2_1_calibration_mode_is_unaffected():
    cli = _cli_module()
    assert cli._reject_cross_mode_flags(
        cli.build_parser().parse_args(RUN_ARGV)) is None
    trimmed = list(RUN_ARGV)
    index = trimmed.index("--calibration-selection")
    del trimmed[index:index + 2]
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(trimmed))
    assert verdict and "--calibration-selection" in verdict


def test_no_unrelated_mode_gained_the_selection_flag():
    cli = _cli_module()
    for mode in ("build-screen-release", "build-classifier-candidate-cohort",
                 "select-classifier-calibration-rows",
                 "screen-universe-lineage-live"):
        argv = ["--mode", mode, "--calibration-selection", "s.json",
                "--output-dir", "out", "--run-id", "cli-gating-fixture"]
        verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(argv))
        assert verdict and "--calibration-selection" in verdict, mode


# --- ADR-129: the three V2.3 modes must be reachable through their own flags -------

V2_3_COHORT_ARGV = [
    "--mode", "classify-universe-cohort-v2-3",
    "--cohort-manifest", "c.json", "--overlay-manifest", "o.json",
    "--release-manifest", "r.json", "--packet-manifest", "p.json",
    "--governance-root", "gov", "--screen-authorization", "a.json",
    "--screen-authorization-sha256", SHA_PLACEHOLDER,
    "--output-dir", "out", "--run-id", "cli-gating-fixture",
]
V2_3_CONTINUATION_ARGV = (
    ["--mode", "classify-universe-cohort-continuation-v2-3",
     "--source-run-dir", "src", "--source-receipt-sha256", SHA_PLACEHOLDER]
    + V2_3_COHORT_ARGV[2:])
V2_3_CALIBRATION_ARGV = (
    ["--mode", "classify-universe-calibration-v2-3",
     "--calibration-selection", "s.json"] + V2_3_COHORT_ARGV[2:])

V2_3_MODES = [
    ("classify-universe-cohort-v2-3", V2_3_COHORT_ARGV),
    ("classify-universe-cohort-continuation-v2-3", V2_3_CONTINUATION_ARGV),
    ("classify-universe-calibration-v2-3", V2_3_CALIBRATION_ARGV),
]

#: Every flag in the V2.3 calibration mode's required-flag table, in table order.
V2_3_CALIBRATION_REQUIRED_FLAGS = [
    "--cohort-manifest", "--overlay-manifest", "--release-manifest",
    "--packet-manifest", "--calibration-selection", "--governance-root",
    "--screen-authorization", "--screen-authorization-sha256",
    "--output-dir", "--run-id",
]


@pytest.mark.parametrize("mode,argv", V2_3_MODES, ids=[m for m, _ in V2_3_MODES])
def test_each_v2_3_mode_accepts_its_complete_required_argv(mode, argv):
    cli = _cli_module()
    args = cli.build_parser().parse_args(argv)
    assert args.mode == mode
    assert cli._reject_cross_mode_flags(args) is None
    _assert_no_google()


def test_the_v2_3_calibration_mode_accepts_its_selection_flag():
    cli = _cli_module()
    args = cli.build_parser().parse_args(V2_3_CALIBRATION_ARGV)
    assert args.calibration_selection == "s.json"
    assert cli._reject_cross_mode_flags(args) is None


@pytest.mark.parametrize("flag", V2_3_CALIBRATION_REQUIRED_FLAGS)
def test_the_v2_3_calibration_mode_still_requires_every_flag(flag, capsys):
    cli = _cli_module()
    parser = cli.build_parser()
    enforced_by_argparse = {option for action in parser._actions if action.required
                            for option in action.option_strings}
    trimmed = list(V2_3_CALIBRATION_ARGV)
    index = trimmed.index(flag)
    del trimmed[index:index + 2]
    if flag in enforced_by_argparse:
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(trimmed)
        assert excinfo.value.code == 2
        assert flag in capsys.readouterr().err
    else:
        verdict = cli._reject_cross_mode_flags(parser.parse_args(trimmed))
        assert verdict and "requires" in verdict and flag in verdict


def test_the_v2_3_required_flag_list_covers_the_modes_whole_table():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    start = source.index('("classify-universe-calibration-v2-3", ((')
    table = source[start:source.index('("classify-universe-calibration-v2-2",', start)]
    declared = re.findall(r'\("(--[a-z0-9-]+)"', table)
    assert declared == V2_3_CALIBRATION_REQUIRED_FLAGS
    assert len(set(declared)) == len(declared) == 10


@pytest.mark.parametrize("mode,argv", [
    ("classify-universe-cohort-v2-3", V2_3_COHORT_ARGV),
    ("classify-universe-cohort-continuation-v2-3", V2_3_CONTINUATION_ARGV),
], ids=["cohort-v2-3", "continuation-v2-3"])
def test_a_v2_3_run_mode_still_rejects_the_selection_flag(mode, argv):
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(
        list(argv) + ["--calibration-selection", "s.json"]))
    assert verdict and "--calibration-selection" in verdict


def test_all_three_versions_of_each_mode_are_declared():
    cli = _cli_module()
    choices = next(a.choices for a in cli.build_parser()._actions
                   if a.dest == "mode")
    for stem in ("classify-universe-cohort",
                 "classify-universe-cohort-continuation",
                 "classify-universe-calibration"):
        for suffix in ("", "-v2-2", "-v2-3"):
            assert f"{stem}{suffix}" in choices, f"{stem}{suffix}"


# --- ADR-130: the four V2.4 modes must be reachable through their own flags --------

V2_4_COHORT_ARGV = [
    "--mode", "classify-universe-cohort-v2-4",
    "--cohort-manifest", "c.json", "--overlay-manifest", "o.json",
    "--release-manifest", "r.json", "--packet-manifest", "p.json",
    "--governance-root", "gov", "--screen-authorization", "a.json",
    "--screen-authorization-sha256", SHA_PLACEHOLDER,
    "--output-dir", "out", "--run-id", "cli-gating-fixture",
]
V2_4_CONTINUATION_ARGV = (
    ["--mode", "classify-universe-cohort-continuation-v2-4",
     "--source-run-dir", "src", "--source-receipt-sha256", SHA_PLACEHOLDER]
    + V2_4_COHORT_ARGV[2:])
V2_4_CALIBRATION_ARGV = (
    ["--mode", "classify-universe-calibration-v2-4",
     "--calibration-selection", "s.json"] + V2_4_COHORT_ARGV[2:])
V2_4_REVIEW_ARGV = [
    "--mode", "build-classifier-calibration-review-v2-4",
    "--calibration-run-dir", "run", "--calibration-selection", "s.json",
    "--calibration-selection-sha256", SHA_PLACEHOLDER,
    "--output-dir", "out", "--run-id", "cli-gating-fixture",
]

V2_4_MODES = [
    ("classify-universe-cohort-v2-4", V2_4_COHORT_ARGV),
    ("classify-universe-cohort-continuation-v2-4", V2_4_CONTINUATION_ARGV),
    ("classify-universe-calibration-v2-4", V2_4_CALIBRATION_ARGV),
    ("build-classifier-calibration-review-v2-4", V2_4_REVIEW_ARGV),
]

V2_4_CALIBRATION_REQUIRED_FLAGS = [
    "--cohort-manifest", "--overlay-manifest", "--release-manifest",
    "--packet-manifest", "--calibration-selection", "--governance-root",
    "--screen-authorization", "--screen-authorization-sha256",
    "--output-dir", "--run-id",
]
V2_4_REVIEW_REQUIRED_FLAGS = [
    "--calibration-run-dir", "--calibration-selection",
    "--calibration-selection-sha256", "--output-dir", "--run-id",
]


@pytest.mark.parametrize("mode,argv", V2_4_MODES, ids=[m for m, _ in V2_4_MODES])
def test_each_v2_4_mode_accepts_its_complete_required_argv(mode, argv):
    cli = _cli_module()
    args = cli.build_parser().parse_args(argv)
    assert args.mode == mode
    assert cli._reject_cross_mode_flags(args) is None
    _assert_no_google()


def test_the_v2_4_calibration_mode_accepts_its_selection_flag():
    cli = _cli_module()
    args = cli.build_parser().parse_args(V2_4_CALIBRATION_ARGV)
    assert args.calibration_selection == "s.json"
    assert cli._reject_cross_mode_flags(args) is None


@pytest.mark.parametrize("flag", V2_4_CALIBRATION_REQUIRED_FLAGS)
def test_the_v2_4_calibration_mode_requires_every_flag(flag, capsys):
    _assert_mode_requires_flag(V2_4_CALIBRATION_ARGV, flag, capsys)


@pytest.mark.parametrize("flag", V2_4_REVIEW_REQUIRED_FLAGS)
def test_the_v2_4_review_mode_requires_every_flag(flag, capsys):
    _assert_mode_requires_flag(V2_4_REVIEW_ARGV, flag, capsys)


def _assert_mode_requires_flag(argv, flag, capsys):
    """Assert at whichever layer actually enforces the flag.

    ``--output-dir`` and ``--run-id`` are argparse-required, so removing one
    raises ``SystemExit(2)`` rather than reaching the cross-mode verdict. The
    test names the enforcing layer per flag instead of assuming one of them.
    """
    cli = _cli_module()
    parser = cli.build_parser()
    enforced_by_argparse = {option for action in parser._actions if action.required
                            for option in action.option_strings}
    trimmed = list(argv)
    index = trimmed.index(flag)
    del trimmed[index:index + 2]
    if flag in enforced_by_argparse:
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(trimmed)
        assert excinfo.value.code == 2
        assert flag in capsys.readouterr().err
    else:
        verdict = cli._reject_cross_mode_flags(parser.parse_args(trimmed))
        assert verdict and "requires" in verdict and flag in verdict


def test_the_v2_4_required_flag_list_covers_the_modes_whole_table():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    start = source.index('("classify-universe-calibration-v2-4", ((')
    table = source[start:source.index('("classify-universe-calibration-v2-3",', start)]
    declared = re.findall(r'\("(--[a-z0-9-]+)"', table)
    assert declared == V2_4_CALIBRATION_REQUIRED_FLAGS
    assert len(set(declared)) == len(declared) == 10


def test_the_v2_4_review_flag_list_covers_the_modes_whole_table():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    start = source.index('("build-classifier-calibration-review-v2-4", ((')
    table = source[start:source.index(
        '("build-classifier-calibration-review-v2-3",', start)]
    declared = re.findall(r'\("(--[a-z0-9-]+)"', table)
    assert declared == V2_4_REVIEW_REQUIRED_FLAGS
    assert len(set(declared)) == len(declared) == 5


@pytest.mark.parametrize("mode,argv", [
    ("classify-universe-cohort-v2-4", V2_4_COHORT_ARGV),
    ("classify-universe-cohort-continuation-v2-4", V2_4_CONTINUATION_ARGV),
], ids=["cohort-v2-4", "continuation-v2-4"])
def test_a_v2_4_run_mode_still_rejects_the_selection_flag(mode, argv):
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(
        list(argv) + ["--calibration-selection", "s.json"]))
    assert verdict and "--calibration-selection" in verdict


def test_the_v2_4_cohort_mode_still_rejects_continuation_flags():
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(
        list(V2_4_COHORT_ARGV) + ["--source-run-dir", "src"]))
    assert verdict and "--source-run-dir" in verdict


def test_the_v2_4_review_mode_rejects_the_run_modes_flags():
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(
        list(V2_4_REVIEW_ARGV) + ["--governance-root", "gov"]))
    assert verdict and "--governance-root" in verdict


def test_all_four_versions_of_each_mode_are_declared():
    """ADR-130's four-version assertion, kept and rebaselined by ADR-132."""
    cli = _cli_module()
    choices = next(a.choices for a in cli.build_parser()._actions
                   if a.dest == "mode")
    for stem in ("classify-universe-cohort",
                 "classify-universe-cohort-continuation",
                 "classify-universe-calibration"):
        for suffix in ("", "-v2-2", "-v2-3", "-v2-4"):
            assert f"{stem}{suffix}" in choices, f"{stem}{suffix}"
    for suffix in ("", "-v2-2", "-v2-3", "-v2-4"):
        assert f"build-classifier-calibration-review{suffix}" in choices, suffix
    assert len(choices) == 58


# --- ADR-132: the four V2.5 modes must be reachable through their own flags --------

V2_5_COHORT_ARGV = [
    "--mode", "classify-universe-cohort-v2-5",
    "--cohort-manifest", "c.json", "--overlay-manifest", "o.json",
    "--release-manifest", "r.json", "--packet-manifest", "p.json",
    "--governance-root", "gov", "--screen-authorization", "a.json",
    "--screen-authorization-sha256", SHA_PLACEHOLDER,
    "--output-dir", "out", "--run-id", "cli-gating-fixture",
]
V2_5_CONTINUATION_ARGV = (
    ["--mode", "classify-universe-cohort-continuation-v2-5",
     "--source-run-dir", "src", "--source-receipt-sha256", SHA_PLACEHOLDER]
    + V2_5_COHORT_ARGV[2:])
V2_5_CALIBRATION_ARGV = (
    ["--mode", "classify-universe-calibration-v2-5",
     "--calibration-selection", "s.json"] + V2_5_COHORT_ARGV[2:])
V2_5_REVIEW_ARGV = [
    "--mode", "build-classifier-calibration-review-v2-5",
    "--calibration-run-dir", "run", "--calibration-selection", "s.json",
    "--calibration-selection-sha256", SHA_PLACEHOLDER,
    "--output-dir", "out", "--run-id", "cli-gating-fixture",
]
V2_5_MODES = [
    ("classify-universe-cohort-v2-5", V2_5_COHORT_ARGV),
    ("classify-universe-cohort-continuation-v2-5", V2_5_CONTINUATION_ARGV),
    ("classify-universe-calibration-v2-5", V2_5_CALIBRATION_ARGV),
    ("build-classifier-calibration-review-v2-5", V2_5_REVIEW_ARGV),
]
V2_5_CALIBRATION_REQUIRED_FLAGS = list(V2_4_CALIBRATION_REQUIRED_FLAGS)
V2_5_REVIEW_REQUIRED_FLAGS = list(V2_4_REVIEW_REQUIRED_FLAGS)


@pytest.mark.parametrize("mode,argv", V2_5_MODES, ids=[m for m, _ in V2_5_MODES])
def test_each_v2_5_mode_accepts_its_complete_required_argv(mode, argv):
    cli = _cli_module()
    args = cli.build_parser().parse_args(argv)
    assert args.mode == mode
    assert cli._reject_cross_mode_flags(args) is None
    _assert_no_google()


@pytest.mark.parametrize("flag", V2_5_CALIBRATION_REQUIRED_FLAGS)
def test_the_v2_5_calibration_mode_requires_every_flag(flag, capsys):
    _assert_mode_requires_flag(V2_5_CALIBRATION_ARGV, flag, capsys)


@pytest.mark.parametrize("flag", V2_5_REVIEW_REQUIRED_FLAGS)
def test_the_v2_5_review_mode_requires_every_flag(flag, capsys):
    _assert_mode_requires_flag(V2_5_REVIEW_ARGV, flag, capsys)


def test_the_v2_5_required_flag_tables_match_the_pipeline():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    start = source.index('("classify-universe-calibration-v2-5", ((')
    table = source[start:source.index('("classify-universe-calibration-v2-4",', start)]
    assert re.findall(r'\("(--[a-z0-9-]+)"', table) == V2_5_CALIBRATION_REQUIRED_FLAGS
    start = source.index('("build-classifier-calibration-review-v2-5", ((')
    table = source[start:source.index(
        '("build-classifier-calibration-review-v2-4",', start)]
    assert re.findall(r'\("(--[a-z0-9-]+)"', table) == V2_5_REVIEW_REQUIRED_FLAGS


@pytest.mark.parametrize("mode,argv", [
    ("classify-universe-cohort-v2-5", V2_5_COHORT_ARGV),
    ("classify-universe-cohort-continuation-v2-5", V2_5_CONTINUATION_ARGV),
], ids=["cohort-v2-5", "continuation-v2-5"])
def test_a_v2_5_run_mode_still_rejects_the_selection_flag(mode, argv):
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(
        list(argv) + ["--calibration-selection", "s.json"]))
    assert verdict and "--calibration-selection" in verdict


def test_the_v2_5_cohort_mode_still_rejects_continuation_flags():
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(
        list(V2_5_COHORT_ARGV) + ["--source-run-dir", "src"]))
    assert verdict and "--source-run-dir" in verdict


def test_the_v2_5_review_mode_rejects_the_run_modes_flags():
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(
        list(V2_5_REVIEW_ARGV) + ["--governance-root", "gov"]))
    assert verdict and "--governance-root" in verdict


def test_all_five_versions_of_each_mode_are_declared():
    cli = _cli_module()
    choices = next(a.choices for a in cli.build_parser()._actions if a.dest == "mode")
    for stem in ("classify-universe-cohort",
                 "classify-universe-cohort-continuation",
                 "classify-universe-calibration"):
        for suffix in ("", "-v2-2", "-v2-3", "-v2-4", "-v2-5"):
            assert f"{stem}{suffix}" in choices, f"{stem}{suffix}"
    for suffix in ("", "-v2-2", "-v2-3", "-v2-4", "-v2-5"):
        assert f"build-classifier-calibration-review{suffix}" in choices, suffix
    assert len(choices) == 58
