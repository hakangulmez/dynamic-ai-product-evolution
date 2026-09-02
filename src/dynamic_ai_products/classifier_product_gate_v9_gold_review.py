"""Build a blinded human-review case set from the complete V9 aggregate.

The V9 aggregate is a model output, not gold.  This module deliberately keeps
that distinction: it materializes Item 1 packets for human reading and writes a
separate audit map that proves the CORE-precision, CO_ESSENTIAL-recall, and
empty-source queues.  No human decision is fabricated here.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .classifier_product_gate_v9_aggregate import (
    CANDIDATES_FILENAME,
    CORE_FILENAME,
    require_product_gate_v9_aggregate,
)
from .lineage_classifier_product_gate_batch_v3 import (
    PRODUCT_GATE_BATCH_V3_ROUTE,
    require_product_gate_batch_run_v3,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    ScreenInputError,
    _canonical_line,
    _load_schema,
    _sha256,
    _validate,
    load_packet_run,
)

__all__ = [
    "AUDIT_MAP_FILENAME",
    "AUDIT_MAP_SCHEMA",
    "CASE_FILENAME",
    "CASE_SCHEMA",
    "GOLD_REVIEW_MANIFEST_CONTRACT",
    "MANIFEST_FILENAME",
    "MANIFEST_SCHEMA",
    "build_product_gate_v9_gold_review_cases",
    "require_product_gate_v9_gold_review_cases",
]

GOLD_REVIEW_MANIFEST_CONTRACT = (
    "universe_classifier_product_gate_v9_gold_review_manifest@0.1.0")
CASE_CONTRACT = "universe_classifier_product_gate_v9_gold_review_case@0.1.0"
AUDIT_CONTRACT = "universe_classifier_product_gate_v9_gold_review_audit_map@0.1.0"

MANIFEST_FILENAME = "universe_classifier_product_gate_v9_gold_review_manifest.json"
CASE_FILENAME = "universe_classifier_product_gate_v9_gold_review_cases.jsonl"
AUDIT_MAP_FILENAME = "universe_classifier_product_gate_v9_gold_review_audit_map.jsonl"
MANIFEST_SCHEMA = "schemas/universe_classifier_product_gate_v9_gold_review_manifest.v1.schema.json"
CASE_SCHEMA = "schemas/universe_classifier_product_gate_v9_gold_review_case.v1.schema.json"
AUDIT_MAP_SCHEMA = "schemas/universe_classifier_product_gate_v9_gold_review_audit_map.v1.schema.json"

_SOFTWARE_SIGNAL_PATTERNS = (
    r"\bsoftware[- ]as[- ]a[- ]service\b", r"\bsaas\b",
    r"\bsoftware platform\b", r"\benterprise software\b",
    r"\bcloud[- ]based software\b", r"\blicensed software\b",
)
_ITEM1_HEADING_ONLY = re.compile(
    r"^>?\s*item\s*1\.\s*business\.?\s*(?:\d+)?\s*(?:omitted\.)?$",
    re.IGNORECASE,
)


def _read_jsonl(path: Path, *, what: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise ScreenInputError(f"{what} is missing: {path}")
    try:
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
    except json.JSONDecodeError as exc:
        raise ScreenInputError(f"{what} is not valid JSONL: {path}") from exc


def _source_record_sha256(record: dict[str, Any]) -> str:
    return _sha256((_canonical_line(record) + "\n").encode("utf-8"))


def _source_is_insufficient(packet: dict[str, Any]) -> bool:
    """True only for a packet reduced to its Item 1 heading (or omission)."""
    text = " ".join(" ".join(passage["text"].split()) for passage in packet["passages"])
    return bool(_ITEM1_HEADING_ONLY.fullmatch(text))


def _software_signal_score(packet: dict[str, Any]) -> int:
    text = " ".join(passage["text"] for passage in packet["passages"]).lower()
    return sum(len(re.findall(pattern, text)) for pattern in _SOFTWARE_SIGNAL_PATTERNS)


def _case_id(record: dict[str, Any]) -> str:
    return f"v9-gold-{record['cik']}-{record['accession']}"


def _case(record: dict[str, Any], packet: dict[str, Any], *, availability: str) -> dict[str, Any]:
    passages = []
    for index, passage in enumerate(packet["passages"], start=1):
        passages.append({
            "passage_ref": f"P{index:03d}",
            "passage_id": passage["passage_id"],
            "byte_start": passage["byte_start"],
            "byte_end": passage["byte_end"],
            "text": passage["text"],
            "text_sha256": passage["text_hash"],
        })
    return {
        "case_contract": CASE_CONTRACT,
        "case_id": _case_id(record),
        "cik": record["cik"],
        "accession": record["accession"],
        "source_id": record["source_id"],
        "packet_sha256": packet["packet_sha256"],
        "source_availability": availability,
        "item1_passages": passages,
    }


def _audit(record: dict[str, Any], *, track: str, score: int) -> dict[str, Any]:
    axes = record["axes"]
    return {
        "audit_contract": AUDIT_CONTRACT,
        "case_id": _case_id(record),
        "selection_track": track,
        "source_record_sha256": _source_record_sha256(record),
        "model_product_label": axes["customer_facing_digital_product"],
        "model_centrality": axes["software_centrality"],
        "model_confidence": axes["confidence"],
        "software_signal_score": score,
    }


def build_gold_review_payloads(
    *, core_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]],
    all_records: list[dict[str, Any]], packets_by_key: dict[tuple[str, str], dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    """Build the three approved queues without assigning a human label."""
    records_by_key = {(record["cik"], record["accession"]): record for record in all_records}
    if len(records_by_key) != len(all_records):
        raise ScreenInputError("V9 source records contain duplicate filing identities.")

    def source_for(aggregate_row: dict[str, Any]) -> dict[str, Any]:
        key = (aggregate_row["cik"], aggregate_row["accession"])
        record = records_by_key.get(key)
        if record is None or _source_record_sha256(record) != aggregate_row["source_record_sha256"]:
            raise ScreenInputError("An aggregate row no longer binds its source record.")
        return record

    core = [source_for(row) for row in core_rows]
    coessential = [source_for(row) for row in candidate_rows
                   if row["axes"]["software_centrality"] == "CO_ESSENTIAL"]
    unknown = [record for record in all_records if record["record_kind"] == "classified"
               and record["axes"]["customer_facing_digital_product"] == "UNKNOWN"]

    def packet_for(record: dict[str, Any]) -> dict[str, Any]:
        packet = packets_by_key.get((record["cik"], record["accession"]))
        if packet is None or packet["packet_sha256"] != record["packet_sha256"]:
            raise ScreenInputError("A selected V9 record does not resolve to its hash-bound Item 1 packet.")
        return packet

    insufficient = [record for record in unknown if _source_is_insufficient(packet_for(record))]
    if len(insufficient) != len(unknown):
        raise ScreenInputError(
            "A V9 UNKNOWN record has substantive Item 1 text and cannot be silently classified as source-insufficient.")

    selections: list[tuple[dict[str, Any], str, str, int]] = []
    selections.extend((record, "source_insufficient_unknown", "source_insufficient", 0)
                      for record in sorted(insufficient, key=lambda r: (r["cik"], r["accession"])))
    selections.extend((record, "precision_model_core", "sufficient_item1", _software_signal_score(packet_for(record)))
                      for record in sorted(core, key=lambda r: (r["cik"], r["accession"])))
    selections.extend((record, "recall_model_coessential", "sufficient_item1", _software_signal_score(packet_for(record)))
                      for record in sorted(coessential, key=lambda r: (-_software_signal_score(packet_for(r)), r["cik"], r["accession"])))

    keys = [(record["cik"], record["accession"]) for record, *_rest in selections]
    if len(keys) != len(set(keys)):
        raise ScreenInputError("Gold-review selection tracks overlap; a filing may appear only once.")
    cases = [_case(record, packet_for(record), availability=availability)
             for record, _track, availability, _score in selections]
    # The reviewer-facing file must not disclose a model cohort through its
    # line order. The audit map keeps its transparent priority order instead.
    cases.sort(key=lambda case: _sha256(case["case_id"].encode("utf-8")))
    audit = [_audit(record, track=track, score=score)
             for record, track, _availability, score in selections]
    counts = {
        "review_cases": len(cases),
        "precision_model_core": len(core),
        "recall_model_coessential": len(coessential),
        "source_insufficient_unknown": len(insufficient),
    }
    if counts["review_cases"] != sum(counts[key] for key in counts if key != "review_cases"):
        raise ScreenInputError("Gold-review counts do not close.")
    return cases, audit, counts


def _load_complete_v9_sources(root: Path, aggregate_dir: Path, aggregate: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[tuple[str, str], dict[str, Any]], str]:
    packet_source: dict[str, str] | None = None
    all_records: list[dict[str, Any]] = []
    for run in aggregate["batch_runs"]:
        directory = Path(run["run_dir"])
        manifest_path = require_product_gate_batch_run_v3(directory)
        if _sha256(manifest_path.read_bytes()) != run["manifest_sha256"]:
            raise ScreenInputError("A V9 aggregate batch manifest no longer hashes to its aggregate binding.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        records_path = directory / PRODUCT_GATE_BATCH_V3_ROUTE.records_filename
        if _sha256(records_path.read_bytes()) != run["records_sha256"]:
            raise ScreenInputError("A V9 aggregate batch records file no longer hashes to its aggregate binding.")
        source = manifest["sources"]["packet"]
        if packet_source is None:
            packet_source = dict(source)
        elif source != packet_source:
            raise ScreenInputError("V9 batches do not bind one identical Item 1 packet source.")
        all_records.extend(_read_jsonl(records_path, what="V9 batch records"))
    if packet_source is None:
        raise ScreenInputError("The aggregate names no V9 batch sources.")
    packets = load_packet_run(root, Path(packet_source["packet_manifest_path"]))
    if (packets.manifest_sha256 != packet_source["packet_manifest_sha256"]
            or packets.packets_jsonl_sha256 != packet_source["packets_jsonl_sha256"]):
        raise ScreenInputError("The V9 packet source no longer hashes to its batch bindings.")
    return all_records, {(p["cik"], p["accession"]): p for p in packets.packets}, packets.manifest_sha256


def build_product_gate_v9_gold_review_cases(
    *, repo_root: str | Path, aggregate_dir: str | Path, output_dir: str | Path,
    case_set_id: str, clock: Callable[[], datetime], dry_run: bool = False,
) -> dict[str, Any]:
    """Materialize the approved V9 precision/recall human-review case set."""
    root = Path(repo_root)
    aggregate_directory = Path(aggregate_dir)
    aggregate_path = require_product_gate_v9_aggregate(aggregate_directory, repo_root=root)
    aggregate_raw = aggregate_path.read_bytes()
    aggregate = json.loads(aggregate_raw)
    core_rows = _read_jsonl(aggregate_directory / CORE_FILENAME, what="V9 CORE aggregate")
    candidate_rows = _read_jsonl(aggregate_directory / CANDIDATES_FILENAME, what="V9 candidate aggregate")
    all_records, packets_by_key, packet_manifest_sha256 = _load_complete_v9_sources(root, aggregate_directory, aggregate)
    cases, audit, counts = build_gold_review_payloads(
        core_rows=core_rows, candidate_rows=candidate_rows,
        all_records=all_records, packets_by_key=packets_by_key)
    case_schema = _load_schema(root, CASE_SCHEMA)
    audit_schema = _load_schema(root, AUDIT_MAP_SCHEMA)
    for case in cases:
        _validate(case, case_schema, "V9 gold-review case")
    for row in audit:
        _validate(row, audit_schema, "V9 gold-review audit map")
    payloads = {
        CASE_FILENAME: "".join(_canonical_line(case) + "\n" for case in cases).encode("utf-8"),
        AUDIT_MAP_FILENAME: "".join(_canonical_line(row) + "\n" for row in audit).encode("utf-8"),
    }
    manifest = {
        "case_set_contract": GOLD_REVIEW_MANIFEST_CONTRACT,
        "case_set_id": case_set_id,
        "run_timestamp": clock().isoformat(),
        "aggregate_manifest_path": str(aggregate_path),
        "aggregate_manifest_sha256": _sha256(aggregate_raw),
        "packet_manifest_sha256": packet_manifest_sha256,
        "output_hashes": {name: _sha256(raw) for name, raw in payloads.items()},
        "counts": counts,
        "reconciliation": {
            "every model CORE row enters the precision queue once": counts["precision_model_core"] == aggregate["counts"]["core_software_rows"],
            "every model CO_ESSENTIAL candidate enters the recall queue once": counts["recall_model_coessential"] == sum(1 for row in candidate_rows if row["axes"]["software_centrality"] == "CO_ESSENTIAL"),
            "every V9 product UNKNOWN row is separately source-insufficient": counts["source_insufficient_unknown"] == sum(1 for row in all_records if row["record_kind"] == "classified" and row["axes"]["customer_facing_digital_product"] == "UNKNOWN"),
            "cases and audit rows have identical identity sets": {case["case_id"] for case in cases} == {row["case_id"] for row in audit},
        },
        "human_label_vocabulary": ["STRICT_CORE", "NOT_STRICT_CORE", "INSUFFICIENT_ITEM1"],
        "no_model_call": True,
        "promotable": False,
        "limitations": [
            "This is a human-review case set, not a gold label set: it records no human decision and cannot score V9.",
            "The human-facing cases contain only packet-derived Item 1 text; model labels and selection tracks are isolated in the audit map.",
            "ENABLING and PERIPHERAL software candidates are outside this first recall-review wave and require a separately governed second wave.",
        ],
    }
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA), "V9 gold-review manifest")
    if dry_run:
        return manifest
    run_dir = create_run_directory(output_dir, case_set_id)
    try:
        for filename, raw in payloads.items():
            write_bytes_once(run_dir / filename, raw, what=f"V9 gold-review {filename}")
        write_bytes_once(run_dir / MANIFEST_FILENAME,
                         (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                         what="V9 gold-review manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return manifest


def require_product_gate_v9_gold_review_cases(run_dir: str | Path, *, repo_root: str | Path) -> Path:
    """Load exactly one self-consistent, decision-free V9 gold-review case set."""
    directory = Path(run_dir)
    manifest_path = directory / MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError("A V9 gold-review manifest is missing.")
    manifest_raw = manifest_path.read_bytes()
    manifest = json.loads(manifest_raw)
    if manifest.get("case_set_contract") != GOLD_REVIEW_MANIFEST_CONTRACT:
        raise ScreenInputError("The gold-review case set declares a different contract.")
    root = Path(repo_root)
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA), "V9 gold-review manifest")
    for filename, digest in manifest["output_hashes"].items():
        path = directory / filename
        if not path.is_file() or _sha256(path.read_bytes()) != digest:
            raise ScreenInputError("A V9 gold-review output is missing or no longer hashes to its manifest.")
    cases = _read_jsonl(directory / CASE_FILENAME, what="V9 gold-review cases")
    audit = _read_jsonl(directory / AUDIT_MAP_FILENAME, what="V9 gold-review audit map")
    for case in cases:
        _validate(case, _load_schema(root, CASE_SCHEMA), "V9 gold-review case")
    for row in audit:
        _validate(row, _load_schema(root, AUDIT_MAP_SCHEMA), "V9 gold-review audit map")
    if {case["case_id"] for case in cases} != {row["case_id"] for row in audit}:
        raise ScreenInputError("Gold-review cases and audit map do not share one identity set.")
    if len(cases) != manifest["counts"]["review_cases"]:
        raise ScreenInputError("Gold-review case count does not match its manifest.")
    return manifest_path
