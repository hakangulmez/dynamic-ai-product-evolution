"""ADR-103 full-cohort Item 1 packet build over a completed lineage.

Governing documents:
- docs/DECISION_LOG.md ADR-091 (baseline packet contracts), ADR-097
  (plain-text representation), ADR-101 (lineage aggregate), ADR-102
  (lineage shell determination), ADR-103 (this design)

The single-bundle builder in :mod:`.baseline_packet` is unchanged and still
takes one bundle directory. A completed cohort lives in many bundles across
many execution runs, screened by one shell determination; the only artefacts
naming both authoritatively are the ADR-101 aggregate and the ADR-102
determination manifest, and this module consumes exactly those two.

**The aggregate is the sole authority for what is opened.** Shard discovery
and verification are shared with ADR-102 through :mod:`.lineage_authority`:
no shard-output root, no bundle directory, no glob, no search path, and a
directory the aggregate does not name is unreachable. Superseded and
non-authoritative directories are never resolved.

**The two inputs bind relationally, never against a pinned literal.** The
aggregate's bytes are re-hashed at run time and the determination manifest's
recorded ``aggregate_manifest_sha256`` must equal that recomputation; the
determination JSONL is re-hashed and must equal that manifest's own
``output_hashes`` entry. Shard binding is an exact per-index tuple mapping —
``(shard_index, run_dir, bundle_manifest_sha256, acquisition_manifest_sha256,
rows)`` — identical between the aggregate's authoritative records and the
determination's consumed records, so a swapped index-to-directory association
is refused even though every column would pass a set comparison.

**Only shell_company == true excludes.** false and unknown rows are retained
and packetized by the unchanged :func:`.baseline_packet.build_packet`, so the
ADR-097 plain-text handling, passage normalization and admission-evidence
forwarding are reused rather than reimplemented, and every record stays under
``universe_baseline_packet@0.2.0`` with all five issuer flags null: the packet
still has no cover-page route, and the shell result is bound in the run
manifest, never written into record fields it did not evidence. A retained
document without a usable Item 1 is a per-row failure record — never an
exclusion, never a silent drop.

**Deterministic order.** Packets and failures are written in ``shard_index``
ascending order, then in each bundle manifest's own entry order, after
shell-true omission. Both keys come from artefacts, so the output is
independent of how the execution runs were enumerated.

This module performs no network access and no model call, names no URL, and
never reads the clock.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator

from ..provenance import write_bytes_once
from ..universe.freeze import create_run_directory
from ..universe.io_utils import read_json
from ..universe.models import PacketBuildFailure, UniverseBaselinePacket
from .baseline_packet import (
    BUNDLE_CONTRACT_V2,
    COVER_PAGE_SECTION,
    DEFERRED_SECTIONS,
    FAILURES_FILENAME,
    PACKET_CONTRACT_V2,
    PACKET_MANIFEST_FILENAME,
    PACKETS_FILENAME,
    PacketBundleError,
    build_packet,
)
from .lineage_authority import LineageAuthorityError, load_lineage_bundles
from .normalize import find_item_one_span_v2, find_item_one_span_v3
from .shell_company_determination import (
    DETERMINATION_CONTRACT,
    DETERMINATION_SCHEMA_RELATIVE_PATH,
    DETERMINATIONS_FILENAME,
    MANIFEST_V3_SCHEMA_RELATIVE_PATH as DETERMINATION_MANIFEST_V3_SCHEMA,
    SHELL_FALSE,
    SHELL_TRUE,
    SHELL_UNKNOWN,
)

PACKET_MANIFEST_V3_SCHEMA_RELATIVE_PATH = Path(
    "schemas/baseline_packet_manifest.v3.schema.json"
)
#: v0.4 (ADR-104): v0.3 plus the operator-declared HTML locator. The mode
#: emits v0.4 from ADR-104 on; the v0.3 schema stays byte-identical and keeps
#: validating the artifacts already written under it.
PACKET_MANIFEST_V4_SCHEMA_RELATIVE_PATH = Path(
    "schemas/baseline_packet_manifest.v4.schema.json"
)

#: The closed HTML-locator dispatch (ADR-104). ``--item-one-locator`` is a
#: functional selector over exactly this mapping, never free provenance text:
#: the callable used comes only from here, an unmapped value is refused
#: before any output directory exists, and the v0.4 manifest records the
#: canonical key re-derived from the selected entry. The text route is not
#: part of the selection.
ITEM_ONE_LOCATORS = {
    "item_one_span_v2": find_item_one_span_v2,
    "item_one_span_v3": find_item_one_span_v3,
}
#: The order packet and failure records are written in, recorded in the
#: manifest so a reader need not infer it. Both keys come from artefacts —
#: the aggregate's shard index and the bundle manifest's own entry order —
#: never from an argument.
PACKET_RECORD_ORDER = "shard_index_then_bundle_entry_order_after_shell_exclusion"

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: The exact per-shard binding tuple. Mapping equality by shard index — not
#: independent set comparisons per column — is what refuses a swapped
#: index-to-directory association.
_SHARD_TUPLE_FIELDS = (
    "run_dir",
    "bundle_manifest_sha256",
    "acquisition_manifest_sha256",
    "rows",
)


@dataclass
class LineagePacketRunResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    aggregate_manifest_sha256: str
    determination_manifest_sha256: str
    packets: list[UniverseBaselinePacket] = field(default_factory=list)
    failures: list[PacketBuildFailure] = field(default_factory=list)
    manifest_path: Path | None = None
    counts: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)


def _load_determination(
    root: Path, determination_manifest_path: Path
) -> tuple[dict, str, list[dict], str]:
    """Validate the ADR-102 manifest and its JSONL; return both, with hashes."""
    if not determination_manifest_path.is_file():
        raise PacketBundleError(
            f"Determination manifest not found: {determination_manifest_path}"
        )
    raw = determination_manifest_path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketBundleError(
            f"Determination manifest is not valid JSON: {exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise PacketBundleError(
            f"Determination manifest is not a JSON object: "
            f"{determination_manifest_path}"
        )
    schema = read_json(root / DETERMINATION_MANIFEST_V3_SCHEMA)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise PacketBundleError(
            f"Determination manifest violates "
            f"{DETERMINATION_MANIFEST_V3_SCHEMA.name}: {details}"
        )
    if manifest["determination_contract"] != DETERMINATION_CONTRACT:
        raise PacketBundleError(
            f"Determination manifest declares "
            f"{manifest['determination_contract']!r}; the cohort filter reads "
            f"only {DETERMINATION_CONTRACT} records."
        )

    jsonl_path = determination_manifest_path.parent / DETERMINATIONS_FILENAME
    if not jsonl_path.is_file():
        raise PacketBundleError(
            f"Determinations JSONL not found beside its manifest: {jsonl_path}"
        )
    jsonl_raw = jsonl_path.read_bytes()
    recorded = manifest["output_hashes"][DETERMINATIONS_FILENAME]
    observed = sha256(jsonl_raw).hexdigest()
    if observed != recorded:
        raise PacketBundleError(
            f"Determinations JSONL hashes to {observed}, but its manifest "
            f"records {recorded}. The records on disk are not the records "
            "that manifest describes; nothing is built."
        )
    validator = Draft202012Validator(
        read_json(root / DETERMINATION_SCHEMA_RELATIVE_PATH)
    )
    try:
        jsonl_text = jsonl_raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        # An input-integrity refusal in its own right: bytes that hash to the
        # recorded value but are not UTF-8 are still not the records the
        # manifest describes, and the refusal must not depend on the
        # hash-mismatch path having caught them first.
        raise PacketBundleError(
            f"Determinations JSONL {jsonl_path} is not valid UTF-8: {exc}. "
            "Nothing is built."
        ) from exc
    records: list[dict] = []
    for line_number, line in enumerate(jsonl_text.splitlines(), 1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise PacketBundleError(
                f"Determinations JSONL line {line_number} is not valid JSON: "
                f"{exc}"
            ) from exc
        errors = sorted(validator.iter_errors(record), key=lambda e: e.json_path)
        if errors:
            details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:3])
            raise PacketBundleError(
                f"Determinations JSONL line {line_number} violates the v0.2 "
                f"record contract: {details}"
            )
        records.append(record)
    return manifest, sha256(raw).hexdigest(), records, observed


def _shard_tuple_map(records: list[dict], *, rows_key: str) -> dict[int, tuple]:
    return {
        record["shard_index"]: tuple(
            record[key] if key != "rows" else record[rows_key]
            for key in _SHARD_TUPLE_FIELDS
        )
        for record in records
    }


def _require_tuple_equality(aggregate: dict, determination: dict) -> None:
    """The exact per-index shard binding, aggregate versus determination."""
    ours = _shard_tuple_map(
        aggregate["shards_authoritative"], rows_key="carrier_rows"
    )
    theirs = _shard_tuple_map(
        determination["shards_consumed"], rows_key="rows"
    )
    if set(ours) != set(theirs):
        missing = sorted(set(ours) - set(theirs))
        extra = sorted(set(theirs) - set(ours))
        raise PacketBundleError(
            "The determination's consumed shards do not name the aggregate's "
            f"authoritative shard indices exactly (missing {missing}, "
            f"unexpected {extra})."
        )
    for index in sorted(ours):
        if ours[index] != theirs[index]:
            differing = [
                name
                for name, a, b in zip(_SHARD_TUPLE_FIELDS, ours[index],
                                      theirs[index])
                if a != b
            ]
            raise PacketBundleError(
                f"Shard {index}: the determination's consumed-shard record "
                f"disagrees with the aggregate's authoritative record on "
                f"{differing}. The two artefacts do not describe the same "
                "lineage; nothing is built."
            )


def run_lineage_packet_build(
    *,
    repo_root: str | Path,
    aggregate_manifest_path: str | Path,
    determination_manifest_path: str | Path,
    project_config_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    item_one_locator: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> LineagePacketRunResult:
    """Build Item 1 packets for every retained row of one lineage cohort."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise PacketBundleError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    # The selector is exact-match against the closed mapping: no whitespace
    # normalization, no aliasing, no caller-supplied callable, and the
    # refusal precedes every read and every write.
    if item_one_locator not in ITEM_ONE_LOCATORS:
        raise PacketBundleError(
            f"Unknown item_one_locator {item_one_locator!r}; the HTML locator "
            f"is selected from exactly {sorted(ITEM_ONE_LOCATORS)}."
        )
    locate_html = ITEM_ONE_LOCATORS[item_one_locator]
    # Derived from the selected mapping entry, never copied from operator
    # text: the recorded identifier is the key under which the callable was
    # found.
    canonical_locator = next(
        key for key, value in ITEM_ONE_LOCATORS.items() if value is locate_html
    )

    # --- authority: the aggregate names everything that may be opened -------
    try:
        aggregate, shards, aggregate_sha, provenance = load_lineage_bundles(
            root, aggregate_manifest_path
        )
    except LineageAuthorityError as exc:
        raise PacketBundleError(str(exc)) from exc
    for shard in shards:
        if shard["bundle_contract"] != BUNDLE_CONTRACT_V2:
            raise PacketBundleError(
                f"Shard {shard['shard_index']}: bundle declares "
                f"{shard['bundle_contract']!r}; a lineage cohort is built only "
                f"from {BUNDLE_CONTRACT_V2} bundles."
            )
    route_validation = shards[0]["route_validation"]
    for shard in shards[1:]:
        if shard["route_validation"] != route_validation:
            raise PacketBundleError(
                f"Shard {shard['shard_index']}: route validation "
                f"{shard['route_validation']} disagrees with "
                f"{route_validation}. One cohort has one probe record; "
                "disagreement is refused, never reconciled."
            )

    # --- binding: the determination must describe exactly this aggregate ----
    determination, determination_sha, records, jsonl_sha = _load_determination(
        root, Path(determination_manifest_path)
    )
    if determination["aggregate_manifest_sha256"] != aggregate_sha:
        raise PacketBundleError(
            f"The determination manifest records aggregate "
            f"{determination['aggregate_manifest_sha256']}, but the supplied "
            f"aggregate's bytes hash to {aggregate_sha}. The two inputs do "
            "not belong together; nothing is built."
        )
    for name, ours in (("queue_id", aggregate["queue_id"]),
                       ("queue_definition_sha256",
                        aggregate["queue_definition_sha256"])):
        if determination[name] != ours:
            raise PacketBundleError(
                f"The determination manifest records {name} "
                f"{determination[name]!r}, but the aggregate declares "
                f"{ours!r}."
            )
    if determination["aggregate_run_id"] != aggregate["run_id"]:
        raise PacketBundleError(
            f"The determination manifest records aggregate run id "
            f"{determination['aggregate_run_id']!r}, but the aggregate "
            f"declares {aggregate['run_id']!r}."
        )
    if determination["carrier_provenance"] != provenance:
        raise PacketBundleError(
            "The determination manifest's carrier provenance disagrees with "
            "the consumed bundles'."
        )
    _require_tuple_equality(aggregate, determination)

    # --- reconciliation: every carrier row, exactly once, correctly bound ---
    bundle_hash_by_index = {
        shard["shard_index"]: shard["bundle_manifest_sha256"]
        for shard in shards
    }
    by_row: dict[tuple[str, str], dict] = {}
    for line_number, record in enumerate(records, 1):
        key = (record["cik"], record["accession"])
        if key in by_row:
            raise PacketBundleError(
                f"Determinations JSONL repeats row {key}; the cohort "
                "determines each carrier row exactly once."
            )
        by_row[key] = record
    rows_planned = 0
    for shard in shards:
        for entry in shard["entries"]:
            key = (entry["cik"], entry["accession"])
            rows_planned += 1
            record = by_row.get(key)
            if record is None:
                raise PacketBundleError(
                    f"Bundle row {key} (shard {shard['shard_index']}) has no "
                    "determination record; the cohort filter is incomplete."
                )
            if record["bundle_manifest_sha256"] != bundle_hash_by_index[
                shard["shard_index"]
            ]:
                raise PacketBundleError(
                    f"Determination for row {key} cites bundle "
                    f"{record['bundle_manifest_sha256']}, but the row lives "
                    f"in shard {shard['shard_index']} whose bundle hashes to "
                    f"{bundle_hash_by_index[shard['shard_index']]}."
                )
    if len(records) != rows_planned:
        extras = sorted(
            set(by_row)
            - {(e["cik"], e["accession"])
               for shard in shards for e in shard["entries"]}
        )
        raise PacketBundleError(
            f"Determinations JSONL holds {len(records)} record(s) but the "
            f"lineage plans {rows_planned} row(s); unmatched: {extras[:5]}."
        )
    outcome_counts = {SHELL_TRUE: 0, SHELL_FALSE: 0, SHELL_UNKNOWN: 0}
    for record in records:
        outcome_counts[record["shell_company"]] += 1
    for name, key in (("shell_true", SHELL_TRUE), ("shell_false", SHELL_FALSE),
                      ("shell_unknown", SHELL_UNKNOWN)):
        if determination["counts"][name] != outcome_counts[key]:
            raise PacketBundleError(
                f"Determination manifest counts {name}="
                f"{determination['counts'][name]}, but its own records tally "
                f"{outcome_counts[key]}."
            )

    # --- the cutoff is the W0-frozen value, exactly as the v0.2 path reads it
    config_path = Path(project_config_path)
    if not config_path.is_file():
        raise PacketBundleError(f"Project config not found: {config_path}")
    import yaml

    universe_config = (
        yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    ).get("universe") or {}
    raw_cutoff = universe_config.get("baseline_cutoff")
    if raw_cutoff is None:
        raise PacketBundleError(
            "Project config carries no universe.baseline_cutoff; the cutoff is "
            "the W0-frozen value, never a parameter."
        )
    cutoff = raw_cutoff if isinstance(raw_cutoff, date) else date.fromisoformat(
        str(raw_cutoff)
    )
    cutoff_source = {
        "path": "configs/project.yaml",
        "key": "universe.baseline_cutoff",
        "project_config_sha256": sha256(config_path.read_bytes()).hexdigest(),
    }

    # --- build: shard_index ascending, bundle entry order, shell-true omitted
    result = LineagePacketRunResult(
        run_id=run_id, run_dir=None, dry_run=dry_run,
        aggregate_manifest_sha256=aggregate_sha,
        determination_manifest_sha256=determination_sha,
    )
    per_shard: list[dict] = []
    for shard in shards:
        excluded = built = failed = 0
        for entry in shard["entries"]:
            record = by_row[(entry["cik"], entry["accession"])]
            if record["shell_company"] == SHELL_TRUE:
                excluded += 1
                continue
            outcome = build_packet(
                entry,
                baseline_cutoff=cutoff,
                baseline_cutoff_source=cutoff_source,
                route_validation=route_validation,
                packet_contract=PACKET_CONTRACT_V2,
                locate_html=locate_html,
            )
            if isinstance(outcome, UniverseBaselinePacket):
                result.packets.append(outcome)
                built += 1
            else:
                result.failures.append(outcome)
                failed += 1
        per_shard.append({
            "shard_index": shard["shard_index"],
            "run_dir": shard["run_dir"],
            "bundle_manifest_sha256": shard["bundle_manifest_sha256"],
            "acquisition_manifest_sha256": shard["acquisition_manifest_sha256"],
            "rows": shard["rows"],
            "rows_excluded_shell": excluded,
            "rows_retained": shard["rows"] - excluded,
            "packets_built": built,
            "packet_failures": failed,
        })

    boundary_counts: dict[str, int] = {}
    for packet in result.packets:
        boundary_counts[packet.end_boundary_kind] = (
            boundary_counts.get(packet.end_boundary_kind, 0) + 1
        )
    failure_counts: dict[str, int] = {}
    for failure in result.failures:
        failure_counts[failure.reason_code] = (
            failure_counts.get(failure.reason_code, 0) + 1
        )
    sizes = [p.packet_byte_size for p in result.packets]
    counts = {
        "planned_rows": rows_planned,
        "shell_true": outcome_counts[SHELL_TRUE],
        "shell_false": outcome_counts[SHELL_FALSE],
        "shell_unknown": outcome_counts[SHELL_UNKNOWN],
        "firms_excluded": outcome_counts[SHELL_TRUE],
        "retained_rows": rows_planned - outcome_counts[SHELL_TRUE],
        "packets_built": len(result.packets),
        "packet_failures": len(result.failures),
        "shards_consumed": len(shards),
        "packets_by_end_boundary": boundary_counts,
        "failures_by_reason": failure_counts,
        "passages_total": sum(len(p.passages) for p in result.packets),
        "packet_bytes_total": sum(sizes),
        "packet_bytes_max": max(sizes) if sizes else 0,
        "packet_bytes_mean": (sum(sizes) // len(sizes)) if sizes else 0,
    }
    reconciliation = {
        "one planned row per determination record": (
            counts["planned_rows"]
            == counts["shell_true"] + counts["shell_false"]
            + counts["shell_unknown"]
        ),
        "retained rows are the non-shell rows": (
            counts["retained_rows"]
            == counts["shell_false"] + counts["shell_unknown"]
        ),
        "packets and failures partition the retained rows": (
            counts["packets_built"] + counts["packet_failures"]
            == counts["retained_rows"]
        ),
        "exclusions are exactly the shell-true determinations": (
            counts["firms_excluded"] == counts["shell_true"]
        ),
        "per-shard rows partition into excluded and retained": all(
            shard["rows_excluded_shell"] + shard["rows_retained"]
            == shard["rows"]
            and shard["packets_built"] + shard["packet_failures"]
            == shard["rows_retained"]
            for shard in per_shard
        ),
        "every passage lies inside its Item 1 span": all(
            packet.item_one_start <= passage.byte_start
            and passage.byte_end <= packet.item_one_end
            for packet in result.packets
            for passage in packet.passages
        ),
        "every packet conserves its normalized bytes": all(
            packet.normalization_ledger["input_byte_count"]
            == packet.normalization_ledger["normalized_byte_count"]
            + packet.normalization_ledger["dropped_byte_count"]
            for packet in result.packets
        ),
        "cover page and the deferred sections are explicitly missing": all(
            COVER_PAGE_SECTION in packet.missing_sections
            and all(s in packet.missing_sections for s in DEFERRED_SECTIONS)
            for packet in result.packets
        ),
        "no issuer flag is asserted without cover-page evidence": all(
            packet.issuer_status_flags.model_dump() == {
                "investment_company": None,
                "asset_backed_issuer": None,
                "non_operating_trust": None,
                "shell_company": None,
                "blank_check_precombination": None,
            }
            for packet in result.packets
        ),
        "boundary counts sum to packets built": (
            sum(boundary_counts.values()) == counts["packets_built"]
        ),
    }
    result.counts, result.reconciliation = counts, reconciliation
    failed_checks = sorted(name for name, ok in reconciliation.items() if not ok)
    if failed_checks:
        raise PacketBundleError(
            f"Lineage packet reconciliation failed: {'; '.join(failed_checks)}. "
            "Nothing was written."
        )
    if dry_run:
        return result

    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir
    packets_payload = (
        "\n".join(
            json.dumps(p.model_dump(mode="json"), sort_keys=True)
            for p in result.packets
        )
        + ("\n" if result.packets else "")
    ).encode("utf-8")
    failures_payload = (
        "\n".join(
            json.dumps(f.model_dump(mode="json"), sort_keys=True)
            for f in result.failures
        )
        + ("\n" if result.failures else "")
    ).encode("utf-8")
    write_bytes_once(run_dir / PACKETS_FILENAME, packets_payload,
                     what="lineage baseline packets")
    write_bytes_once(run_dir / FAILURES_FILENAME, failures_payload,
                     what="lineage baseline packet failures")

    schema_versions = read_json(
        root / "schemas" / "schema_version_manifest.json"
    )["schemas"]
    run_manifest = {
        "run_id": run_id,
        "aggregate_manifest_path": str(aggregate_manifest_path),
        "aggregate_manifest_sha256": aggregate_sha,
        "aggregate_run_id": aggregate["run_id"],
        "queue_id": aggregate["queue_id"],
        "queue_definition_sha256": aggregate["queue_definition_sha256"],
        "execution_run_ids": list(aggregate["execution_run_ids"]),
        "determination_manifest_path": str(determination_manifest_path),
        "determination_manifest_sha256": determination_sha,
        "determination_run_id": determination["run_id"],
        "determinations_jsonl_sha256": jsonl_sha,
        "shards_consumed": per_shard,
        "packet_record_order": PACKET_RECORD_ORDER,
        "item_one_locator": canonical_locator,
        "bundle_contract": BUNDLE_CONTRACT_V2,
        "carrier_provenance": dict(provenance),
        "route_validation": dict(route_validation),
        "baseline_cutoff": str(cutoff),
        "baseline_cutoff_source": cutoff_source,
        "counts": counts,
        "reconciliation": reconciliation,
        "output_hashes": {
            PACKETS_FILENAME: sha256(packets_payload).hexdigest(),
            FAILURES_FILENAME: sha256(failures_payload).hexdigest(),
        },
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "universe_baseline_packet_v2": schema_versions[
                "universe_baseline_packet_v2"
            ],
            "baseline_packet_manifest_v4": schema_versions[
                "baseline_packet_manifest_v4"
            ],
            "shell_company_determination_manifest_v3": schema_versions[
                "shell_company_determination_manifest_v3"
            ],
            "acquisition_queue_aggregate_manifest_v2": schema_versions[
                "acquisition_queue_aggregate_manifest_v2"
            ],
        },
        "limitations": [
            "Only shell_company == true excludes, and it excludes "
            "deterministically with dated evidence bound in the ADR-102 "
            "manifest this run names. false and unknown rows are retained and "
            "packetized; retention asserts nothing about software, product or "
            "general eligibility.",
            "Packet records keep the unchanged universe_baseline_packet@0.2.0 "
            "contract. COVER_PAGE is explicitly missing and all five issuer "
            "flags are null on every record: the packet has no cover-page "
            "route, and the shell result lives here at run level, never in "
            "record fields it did not evidence.",
            "The named aggregate is the sole authority root. This run took no "
            "shard-output root, bundle directory, replay directory, glob or "
            "search path; every directory it opened was exactly a "
            "shards_authoritative run_dir from that manifest, and superseded "
            "or non-authoritative directories were never resolved.",
            "The two inputs bind relationally: the determination's recorded "
            "aggregate hash must equal the recomputed aggregate bytes, its "
            "JSONL must hash to its own output_hashes entry, and the "
            "per-shard tuple mapping must be identical index by index. No "
            "hash is pinned in code or schema.",
            "A retained document without a usable Item 1 is a per-row failure "
            "record in the failures JSONL, never an exclusion and never a "
            "silent drop.",
            "Packets and failures are written in shard_index ascending order, "
            "then in each bundle manifest's own entry order, after shell-true "
            "omission; the order is independent of execution-run-id "
            "enumeration.",
            "The HTML locator is an operator-declared, closed functional "
            "selector: the callable comes only from ITEM_ONE_LOCATORS, an "
            "unmapped value is refused before any output exists, and the "
            "identifier recorded here is re-derived from the selected "
            "mapping entry. The plain-text route is selector-independent.",
            "Fixture-first: packets are built only from locally supplied, "
            "hash-verified primary documents. This module performs no network "
            "access and no model call, and no screening, classification, tier "
            "derivation or PCT extraction is performed.",
        ],
    }
    schema = read_json(root / PACKET_MANIFEST_V4_SCHEMA_RELATIVE_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(run_manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"Lineage packet manifest violates the canonical schema: {details}"
        )
    payload = (json.dumps(run_manifest, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    write_bytes_once(run_dir / PACKET_MANIFEST_FILENAME, payload,
                     what="lineage baseline packet manifest")
    result.manifest_path = run_dir / PACKET_MANIFEST_FILENAME
    return result
