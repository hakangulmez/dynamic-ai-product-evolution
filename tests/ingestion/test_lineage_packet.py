"""ADR-103 lineage packet-build tests — fully offline, tmp_path-synthesized.

Every lineage here is synthesized under a temporary root that symlinks the
real ``schemas/`` directory, so the real validators run while nothing is
written inside the repository. Determinations are produced by the **real**
ADR-102 lineage runner over the synthesized lineage, so the binding the
packet builder verifies is genuine, never hand-forged — except where a test
forges one field deliberately to prove the refusal.

No hash literal from any production run appears here: every binding is
relational between the two synthesized inputs.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.ingestion.baseline_packet import (
    FAILURES_FILENAME,
    PACKET_MANIFEST_FILENAME,
    PACKETS_FILENAME,
    PacketBundleError,
    run_baseline_packet_build,
)
from dynamic_ai_products.ingestion.lineage_packet import (
    PACKET_RECORD_ORDER,
    run_lineage_packet_build,
)
from dynamic_ai_products.ingestion.shell_company_determination import (
    DETERMINATIONS_FILENAME,
    run_lineage_shell_company_determination,
)
from dynamic_ai_products.universe.io_utils import read_json

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
CONFIG = ROOT / "configs" / "project.yaml"
PACKET_FIXTURES = ROOT / "evals" / "fixtures" / "baseline_packets"
SHELL_FIXTURES = ROOT / "evals" / "fixtures" / "shell_company"
TEXT_FIXTURES = ROOT / "evals" / "fixtures" / "plain_text_primary"

PACKET_MANIFEST_V3_SCHEMA = (
    ROOT / "schemas" / "baseline_packet_manifest.v3.schema.json"
)
PACKET_MANIFEST_V4_SCHEMA = (
    ROOT / "schemas" / "baseline_packet_manifest.v4.schema.json"
)
PACKET_MANIFEST_V2_SCHEMA = (
    ROOT / "schemas" / "baseline_packet_manifest.v2.schema.json"
)
PACKET_MANIFEST_V1_SCHEMA = (
    ROOT / "schemas" / "baseline_packet_manifest.schema.json"
)
ACQ_MANIFEST_FILENAME = "primary_document_acquisition_manifest.json"
BUNDLE_MANIFEST_FILENAME = "bundle_manifest.json"

FIXED_CLOCK = lambda: datetime(2026, 8, 18, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731

#: One provenance triple and one route record for every synthesized shard, so
#: agreement holds by construction and a disagreement test edits one copy.
PROVENANCE = {
    "carrier_run_id": "synthetic-fixture-carrier",
    "carrier_manifest_sha256": "0" * 64,
    "freeze_record_sha256": "0" * 64,
}
ROUTE_VALIDATION = {
    "probe_run_id": "synthetic-fixture-probe",
    "probe_manifest_sha256": "0" * 64,
    "covered_accessions": 3,
    "note": "URL-route grammar only; never selection evidence.",
}


def _synth_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / "schemas").symlink_to(ROOT / "schemas")
    return root


def _fixture_doc(source_dir: Path, filename: str, *, cik: str | None = None,
                 accession: str | None = None) -> tuple[Path, dict]:
    """One bundle document row from a committed fixture, upgraded to v0.2."""
    manifest = read_json(source_dir / BUNDLE_MANIFEST_FILENAME)
    entry = next(
        dict(d) for d in manifest["documents"] if d["local_filename"] == filename
    )
    if manifest["bundle_contract"].endswith("@0.1.0"):
        entry.update(representation="html", admission=None,
                     document_blocks=None, declared_type=None,
                     declared_filename=None)
    if cik is not None:
        entry["cik"] = cik
    if accession is not None:
        entry["accession"] = accession
    return source_dir / filename, entry


def _write_shard(root: Path, name: str,
                 documents: list[tuple[Path, dict]]) -> Path:
    run_dir = root / "shards" / name
    run_dir.mkdir(parents=True)
    manifest = {
        "bundle_contract": "baseline_primary_document_bundle@0.2.0",
        "description": "Synthesized ADR-103 fixture shard.",
        "provenance": dict(PROVENANCE),
        "route_validation": dict(ROUTE_VALIDATION),
        "documents": [entry for _, entry in documents],
    }
    (run_dir / BUNDLE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for source, entry in documents:
        target = run_dir / entry["local_filename"]
        if not target.exists():
            shutil.copyfile(source, target)
    (run_dir / ACQ_MANIFEST_FILENAME).write_text(
        json.dumps({"stub_for": name}, indent=2) + "\n", encoding="utf-8")
    return run_dir


def _shard_record(root: Path, index: int, run_dir: Path, rows: int) -> dict:
    return {
        "shard_index": index,
        "run_id": run_dir.name,
        "run_dir": str(run_dir.relative_to(root)),
        "shard_plan_sha256": f"{index:064d}",
        "acquisition_manifest_sha256": sha256(
            (run_dir / ACQ_MANIFEST_FILENAME).read_bytes()).hexdigest(),
        "bundle_manifest_sha256": sha256(
            (run_dir / BUNDLE_MANIFEST_FILENAME).read_bytes()).hexdigest(),
        "accessions": rows,
        "carrier_rows": rows,
        "bundle_entries": rows,
        "total_requests": 2 * rows,
        "retained_bytes_total": 1,
    }


def _aggregate_payload(records: list[dict], *, run_ids: list[str]) -> dict:
    rows = sum(r["carrier_rows"] for r in records)
    return {
        "aggregate_manifest_contract":
            "acquisition_queue_aggregate_manifest@0.2.0",
        "run_id": "synthetic-aggregate",
        "queue_id": "synthetic-queue",
        "queue_definition_sha256": "a" * 64,
        "execution_run_ids": list(run_ids),
        "coverage_complete": True,
        "coverage_statement":
            f"{len(records)} of {len(records)} shard(s) are authoritative.",
        "shards_authoritative": records,
        "shards_not_authoritative": [],
        "superseded_directories": [],
        "counts": {
            "shards_in_queue": len(records),
            "shards_authoritative": len(records),
            "shards_not_authoritative": 0,
            "accessions_covered": rows,
            "carrier_rows_covered": rows,
            "bundle_entries": rows,
            "total_requests": 2 * rows,
            "retained_bytes_total": len(records),
            "superseded_directories": 0,
            "retained_bytes_superseded": 0,
        },
        "run_timestamp": "2026-08-18T09:00:00+00:00",
        "limitations": ["Synthetic fixture aggregate."],
    }


def _write_aggregate(root: Path, shards: list[Path], *,
                     run_ids=("ra", "rb"), name="aggregate.json") -> Path:
    records = [
        _shard_record(root, index, run_dir,
                      len(read_json(run_dir / BUNDLE_MANIFEST_FILENAME)
                          ["documents"]))
        for index, run_dir in enumerate(shards)
    ]
    path = root / name
    path.write_text(json.dumps(
        _aggregate_payload(records, run_ids=list(run_ids)), indent=2) + "\n",
        encoding="utf-8")
    return path


def _determine(root: Path, aggregate_path: Path, run_id: str = "det") -> Path:
    """The real ADR-102 runner: a genuine v0.3 manifest plus JSONL."""
    result = run_lineage_shell_company_determination(
        repo_root=root, aggregate_manifest_path=aggregate_path,
        output_dir=root / "determinations", run_id=run_id, clock=FIXED_CLOCK)
    return result.manifest_path


def _lineage(tmp_path: Path):
    """Two shards mixing packet-capable, shell-true and plain-text rows.

    Shard 0: an Item-1-bearing iXBRL 10-K (no shell fact -> unknown,
    packetizes), a document without Item 1 (unknown, per-row failure), and a
    shell-true filing (excluded before any packet work).
    Shard 1: an Item-1-bearing 10-KT (unknown, packetizes), a governed
    plain-text 10-K (unknown, packetizes via the text route), and a
    shell-false filing without Item 1 (retained, per-row failure).
    """
    root = _synth_root(tmp_path)
    shard0 = _write_shard(root, "ra-shard-0000", [
        _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm"),
        _fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"),
        _fixture_doc(SHELL_FIXTURES, "shell_true_ballotbox.html"),
    ])
    shard1 = _write_shard(root, "rb-shard-0001", [
        _fixture_doc(PACKET_FIXTURES, "primary_10kt.htm"),
        _fixture_doc(TEXT_FIXTURES, "text-10k-item1a.txt"),
        _fixture_doc(SHELL_FIXTURES, "shell_false_booleanfalse.html"),
    ])
    aggregate = _write_aggregate(root, [shard0, shard1])
    determination = _determine(root, aggregate)
    return root, aggregate, determination, [shard0, shard1]


def _build(root: Path, aggregate: Path, determination: Path, tmp_path: Path,
           run_id: str = "lpk", dry_run: bool = False,
           locator: str = "item_one_span_v2"):
    return run_lineage_packet_build(
        repo_root=root, aggregate_manifest_path=aggregate,
        determination_manifest_path=determination,
        project_config_path=CONFIG, output_dir=tmp_path / "packets",
        run_id=run_id, item_one_locator=locator, clock=FIXED_CLOCK,
        dry_run=dry_run)


def _rewrite(path: Path, mutate) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    mutate(payload)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def _no_output(tmp_path: Path, run_id: str = "lpk") -> bool:
    return not (tmp_path / "packets" / run_id).exists()


# --- the cohort ---------------------------------------------------------------


def test_lineage_build_covers_every_retained_row(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    result = _build(root, aggregate, determination, tmp_path)
    counts = result.counts
    assert counts["planned_rows"] == 6
    assert counts["shell_true"] == 1
    assert counts["firms_excluded"] == 1
    assert counts["retained_rows"] == 5
    assert counts["packets_built"] == 3
    assert counts["packet_failures"] == 2
    assert counts["failures_by_reason"] == {"missing_item_one": 2}
    assert counts["shell_unknown"] >= 1, "unknown rows must be exercised"
    assert all(result.reconciliation.values())
    manifest = read_json(result.manifest_path)
    assert not list(Draft202012Validator(read_json(PACKET_MANIFEST_V4_SCHEMA))
                    .iter_errors(manifest))
    assert manifest["packet_record_order"] == PACKET_RECORD_ORDER
    assert manifest["item_one_locator"] == "item_one_span_v2"
    assert manifest["aggregate_manifest_sha256"] == sha256(
        aggregate.read_bytes()).hexdigest()
    assert [s["shard_index"] for s in manifest["shards_consumed"]] == [0, 1]


def test_shell_true_rows_appear_in_neither_output(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    result = _build(root, aggregate, determination, tmp_path)
    excluded = {"0009300002"}
    packet_ciks = {p.cik for p in result.packets}
    failure_ciks = {f.cik for f in result.failures}
    assert excluded.isdisjoint(packet_ciks | failure_ciks)
    blob = (result.run_dir / PACKETS_FILENAME).read_text() + (
        result.run_dir / FAILURES_FILENAME).read_text()
    assert "0009300002" not in blob


def test_unknown_rows_are_retained_not_excluded(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    determinations = [
        json.loads(line) for line in
        (determination.parent / DETERMINATIONS_FILENAME).read_text().splitlines()
    ]
    unknown = {r["cik"] for r in determinations
               if r["shell_company"] == "unknown"}
    assert unknown, "the fixture must carry unknown outcomes"
    result = _build(root, aggregate, determination, tmp_path)
    reached = {p.cik for p in result.packets} | {f.cik for f in result.failures}
    assert unknown <= reached


def test_item_one_failures_are_recorded_never_dropped(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    result = _build(root, aggregate, determination, tmp_path)
    reasons = {f.cik: f.reason_code for f in result.failures}
    assert reasons["0009100006"] == "missing_item_one"
    assert reasons["0009300004"] == "missing_item_one"
    lines = (result.run_dir / FAILURES_FILENAME).read_text().splitlines()
    assert len(lines) == 2


def test_plain_text_rows_packetize_through_the_governed_route(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    result = _build(root, aggregate, determination, tmp_path)
    text = next(p for p in result.packets if p.cik == "0009300101")
    dumped = text.model_dump(mode="json")
    assert dumped["representation"] == "plain_text"
    assert dumped["text_structure"]["admission"] == "single_sgml_document"
    assert dumped["packet_contract"] == "universe_baseline_packet@0.2.0"


def test_lineage_packets_match_the_single_bundle_path_byte_for_byte(tmp_path):
    """Same rows, same records: build_packet is reused unchanged."""
    root, aggregate, determination, shards = _lineage(tmp_path)
    lineage = _build(root, aggregate, determination, tmp_path)
    by_row = {(p.cik, p.accession): p.model_dump(mode="json")
              for p in lineage.packets}
    seen = 0
    for shard in shards:
        single = run_baseline_packet_build(
            repo_root=root, bundle_dir=shard,
            project_config_path=CONFIG,
            output_dir=tmp_path / "single" / shard.name, run_id="s",
            clock=FIXED_CLOCK, dry_run=True)
        for packet in single.packets:
            key = (packet.cik, packet.accession)
            if key in by_row:  # shell-true rows exist only on the single path
                assert packet.model_dump(mode="json") == by_row[key]
                seen += 1
    assert seen == len(lineage.packets)


def test_shared_accession_rows_stay_separate_and_filter_per_row(tmp_path):
    """Same accession, same bytes, two CIKs: one excluded, one retained."""
    root = _synth_root(tmp_path)
    shared = "0009300002-22-000002"
    shard = _write_shard(root, "ra-shard-0000", [
        _fixture_doc(SHELL_FIXTURES, "shell_true_ballotbox.html",
                     accession=shared),
        _fixture_doc(SHELL_FIXTURES, "shell_true_ballotbox.html",
                     cik="0009300099", accession=shared),
        _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm"),
    ])
    aggregate = _write_aggregate(root, [shard], run_ids=("ra",))
    determination = _determine(root, aggregate)
    result = _build(root, aggregate, determination, tmp_path)
    # The document's context CIK is 0009300002 -> shell true, excluded. The
    # sibling row citing the same bytes has no assignable fact -> unknown,
    # retained, and it fails Item 1 rather than vanishing.
    assert result.counts["shell_true"] == 1
    assert result.counts["retained_rows"] == 2
    packet_ciks = {p.cik for p in result.packets}
    failure_ciks = {f.cik for f in result.failures}
    # The shared accession yields no packet at all: its excluded row is
    # omitted and its retained sibling has no Item 1, so it lands in the
    # failures JSONL rather than vanishing.
    assert not any(p.accession == shared for p in result.packets)
    assert "0009300099" in failure_ciks
    # The shell-true sibling is absent from both outputs, not merely from one.
    assert "0009300002" not in packet_ciks
    assert "0009300002" not in failure_ciks


# --- determinism ----------------------------------------------------------------


def test_permuted_run_ids_and_shuffled_shards_move_no_packet_byte(tmp_path):
    root, aggregate, determination, shards = _lineage(tmp_path)
    first = _build(root, aggregate, determination, tmp_path, run_id="one")
    first_packets = (first.run_dir / PACKETS_FILENAME).read_bytes()
    first_failures = (first.run_dir / FAILURES_FILENAME).read_bytes()
    first_manifest = read_json(first.manifest_path)

    permuted = root / "aggregate-permuted.json"
    shutil.copyfile(root / "aggregate.json", permuted)
    _rewrite(permuted, lambda p: p.update(
        execution_run_ids=list(reversed(p["execution_run_ids"])),
        shards_authoritative=list(reversed(p["shards_authoritative"]))))
    determination_two = _determine(root, permuted, run_id="det-two")
    second = _build(root, permuted, determination_two, tmp_path, run_id="two")
    second_manifest = read_json(second.manifest_path)

    assert (second.run_dir / PACKETS_FILENAME).read_bytes() == first_packets
    assert (second.run_dir / FAILURES_FILENAME).read_bytes() == first_failures
    assert (second_manifest["output_hashes"]
            == first_manifest["output_hashes"])
    assert second_manifest["execution_run_ids"] == ["rb", "ra"]
    assert (second_manifest["aggregate_manifest_sha256"]
            != first_manifest["aggregate_manifest_sha256"])
    assert (second_manifest["shards_consumed"]
            == first_manifest["shards_consumed"])


# --- authority boundary ---------------------------------------------------------


def test_a_shard_the_aggregate_does_not_name_is_never_opened(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    before = _build(root, aggregate, determination, tmp_path, run_id="before")
    intruder = _write_shard(root, "rz-shard-0002", [
        _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm"),
    ])
    os.chmod(intruder, 0o000)
    try:
        after = _build(root, aggregate, determination, tmp_path,
                       run_id="after")
        assert (after.run_dir / PACKETS_FILENAME).read_bytes() == (
            before.run_dir / PACKETS_FILENAME).read_bytes()
        assert after.counts == before.counts
        assert "rz-shard-0002" not in json.dumps(read_json(after.manifest_path))
    finally:
        os.chmod(intruder, 0o755)


# --- binding refusals: the whole run writes nothing ------------------------------


def test_a_tampered_determination_jsonl_is_refused(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    jsonl = determination.parent / DETERMINATIONS_FILENAME
    lines = jsonl.read_text().splitlines()
    record = json.loads(lines[0])
    record["shell_company"] = "false"
    lines[0] = json.dumps(record, sort_keys=True)
    jsonl.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(PacketBundleError, match="hashes to"):
        _build(root, aggregate, determination, tmp_path)
    assert _no_output(tmp_path)


def test_a_determination_bound_to_a_different_aggregate_is_refused(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    # A second, distinct aggregate over the same shards (different run id).
    other = root / "aggregate-other.json"
    shutil.copyfile(root / "aggregate.json", other)
    _rewrite(other, lambda p: p.update(run_id="a-different-aggregate"))
    with pytest.raises(PacketBundleError, match="do not belong together"):
        _build(root, other, determination, tmp_path)
    assert _no_output(tmp_path)


def test_a_swapped_shard_tuple_association_is_refused(tmp_path):
    """Set comparisons would pass this; the per-index mapping refuses it."""
    root, aggregate, determination, _ = _lineage(tmp_path)
    payload = json.loads(determination.read_text(encoding="utf-8"))
    a, b = payload["shards_consumed"]
    swapped_fields = ("run_dir", "bundle_manifest_sha256",
                      "acquisition_manifest_sha256", "rows")
    for name in swapped_fields:
        a[name], b[name] = b[name], a[name]
    determination.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
    with pytest.raises(PacketBundleError,
                       match="disagrees with the aggregate's authoritative"):
        _build(root, aggregate, determination, tmp_path)
    assert _no_output(tmp_path)


def test_a_forged_omission_and_extra_row_are_refused(tmp_path):
    """Forging the JSONL and repairing its recorded hash still fails on
    reconciliation, so the hash check is not the only guard."""
    root, aggregate, determination, _ = _lineage(tmp_path)
    jsonl = determination.parent / DETERMINATIONS_FILENAME
    lines = jsonl.read_text().splitlines()
    removed = lines.pop(0)
    forged = "\n".join(lines) + "\n"
    jsonl.write_text(forged, encoding="utf-8")
    payload = json.loads(determination.read_text(encoding="utf-8"))
    payload["output_hashes"][DETERMINATIONS_FILENAME] = sha256(
        forged.encode("utf-8")).hexdigest()
    determination.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
    with pytest.raises(PacketBundleError,
                       match="no determination record"):
        _build(root, aggregate, determination, tmp_path)
    assert _no_output(tmp_path)

    # Now the extra: restore the row and append a stranger, hash repaired.
    lines.append(removed)
    stranger = json.loads(removed)
    stranger["cik"], stranger["accession"] = "0009999999", "0009999999-22-000001"
    lines.append(json.dumps(stranger, sort_keys=True))
    forged = "\n".join(lines) + "\n"
    jsonl.write_text(forged, encoding="utf-8")
    payload["output_hashes"][DETERMINATIONS_FILENAME] = sha256(
        forged.encode("utf-8")).hexdigest()
    determination.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
    with pytest.raises(PacketBundleError, match="unmatched"):
        _build(root, aggregate, determination, tmp_path)
    assert _no_output(tmp_path)


def test_non_utf8_determination_jsonl_is_refused_with_a_repaired_hash(
        tmp_path):
    """Bytes that hash correctly but do not decode are refused in their own
    right, so the controlled refusal is not merely the hash-mismatch path."""
    root, aggregate, determination, _ = _lineage(tmp_path)
    jsonl = determination.parent / DETERMINATIONS_FILENAME
    forged = jsonl.read_bytes() + b"\xff\xfe{not utf8}\xff\n"
    jsonl.write_bytes(forged)
    payload = json.loads(determination.read_text(encoding="utf-8"))
    payload["output_hashes"][DETERMINATIONS_FILENAME] = sha256(
        forged).hexdigest()
    determination.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
    with pytest.raises(PacketBundleError, match="not valid UTF-8"):
        _build(root, aggregate, determination, tmp_path)
    assert _no_output(tmp_path)


def test_a_record_violating_the_v2_contract_is_refused(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    jsonl = determination.parent / DETERMINATIONS_FILENAME
    lines = jsonl.read_text().splitlines()
    record = json.loads(lines[0])
    record["shell_company"] = "maybe"
    lines[0] = json.dumps(record, sort_keys=True)
    forged = "\n".join(lines) + "\n"
    jsonl.write_text(forged, encoding="utf-8")
    payload = json.loads(determination.read_text(encoding="utf-8"))
    payload["output_hashes"][DETERMINATIONS_FILENAME] = sha256(
        forged.encode("utf-8")).hexdigest()
    determination.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
    with pytest.raises(PacketBundleError, match="violates the v0.2 record"):
        _build(root, aggregate, determination, tmp_path)
    assert _no_output(tmp_path)


def test_partial_coverage_and_tampered_bundles_are_refused(tmp_path):
    root, aggregate, determination, shards = _lineage(tmp_path)
    partial = root / "aggregate-partial.json"
    shutil.copyfile(root / "aggregate.json", partial)
    _rewrite(partial, lambda p: p.update(coverage_complete=False))
    with pytest.raises(PacketBundleError, match="coverage is partial"):
        _build(root, partial, determination, tmp_path)
    assert _no_output(tmp_path)

    manifest = read_json(shards[0] / BUNDLE_MANIFEST_FILENAME)
    manifest["description"] = "edited after aggregation"
    (shards[0] / BUNDLE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(PacketBundleError, match="hashes to"):
        _build(root, aggregate, determination, tmp_path)
    assert _no_output(tmp_path)


def test_a_v1_bundle_shard_is_refused_in_a_lineage(tmp_path):
    root, aggregate, determination, shards = _lineage(tmp_path)
    # The html-only shard: a v0.1 bundle over html rows is schema-valid, so
    # the lineage-level contract requirement is what refuses, not the loader.
    manifest = read_json(shards[0] / BUNDLE_MANIFEST_FILENAME)
    manifest["bundle_contract"] = "baseline_primary_document_bundle@0.1.0"
    for document in manifest["documents"]:
        for key in ("representation", "admission", "document_blocks",
                    "declared_type", "declared_filename"):
            document.pop(key, None)
    (shards[0] / BUNDLE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    # Re-point the aggregate at the edited bytes so the contract, not the
    # hash, is what refuses.
    new_sha = sha256(
        (shards[0] / BUNDLE_MANIFEST_FILENAME).read_bytes()).hexdigest()

    def repoint(payload):
        for record in payload.get("shards_authoritative",
                                  payload.get("shards_consumed", [])):
            if record["shard_index"] == 0:
                record["bundle_manifest_sha256"] = new_sha

    _rewrite(root / "aggregate.json", repoint)
    with pytest.raises(PacketBundleError, match="lineage cohort is built only"):
        _build(root, root / "aggregate.json", determination, tmp_path)
    assert _no_output(tmp_path)


def test_route_validation_disagreement_is_refused(tmp_path):
    root, aggregate, determination, shards = _lineage(tmp_path)
    manifest = read_json(shards[1] / BUNDLE_MANIFEST_FILENAME)
    manifest["route_validation"] = {**manifest["route_validation"],
                                    "probe_run_id": "a-different-probe"}
    (shards[1] / BUNDLE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    new_sha = sha256(
        (shards[1] / BUNDLE_MANIFEST_FILENAME).read_bytes()).hexdigest()

    def repoint(payload):
        for record in payload["shards_authoritative"]:
            if record["shard_index"] == 1:
                record["bundle_manifest_sha256"] = new_sha

    _rewrite(root / "aggregate.json", repoint)
    with pytest.raises(PacketBundleError, match="route validation"):
        _build(root, root / "aggregate.json", determination, tmp_path)
    assert _no_output(tmp_path)


def test_missing_inputs_are_refused(tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    ghost = root / "missing.json"
    with pytest.raises(PacketBundleError, match="not found"):
        _build(root, aggregate, ghost, tmp_path)
    with pytest.raises(PacketBundleError, match="not found"):
        _build(root, ghost, determination, tmp_path)
    assert _no_output(tmp_path)


def test_the_lineage_packet_run_is_write_once_and_dry_run_writes_nothing(
        tmp_path):
    root, aggregate, determination, _ = _lineage(tmp_path)
    dry = _build(root, aggregate, determination, tmp_path, run_id="dry",
                 dry_run=True)
    assert dry.run_dir is None and _no_output(tmp_path, "dry")
    _build(root, aggregate, determination, tmp_path)
    with pytest.raises(FileExistsError):
        _build(root, aggregate, determination, tmp_path)


# --- generation separation --------------------------------------------------------


def test_the_packet_manifest_generations_reject_each_other(tmp_path):
    root, aggregate, determination, shards = _lineage(tmp_path)
    lineage = read_json(_build(root, aggregate, determination,
                               tmp_path).manifest_path)
    single = run_baseline_packet_build(
        repo_root=root, bundle_dir=shards[0], project_config_path=CONFIG,
        output_dir=tmp_path / "single", run_id="s", clock=FIXED_CLOCK)
    v2 = read_json(single.manifest_path)
    v1_schema = Draft202012Validator(read_json(PACKET_MANIFEST_V1_SCHEMA))
    v2_schema = Draft202012Validator(read_json(PACKET_MANIFEST_V2_SCHEMA))
    v3_schema = Draft202012Validator(read_json(PACKET_MANIFEST_V3_SCHEMA))
    v4_schema = Draft202012Validator(read_json(PACKET_MANIFEST_V4_SCHEMA))
    assert not list(v2_schema.iter_errors(v2))
    assert not list(v4_schema.iter_errors(lineage))
    # v0.4 <-> v0.3 mutual rejection: the successor field is required in one
    # generation and refused by the other's additionalProperties: false.
    assert list(v3_schema.iter_errors(lineage)), "a v0.4 manifest is not v0.3"
    v3_shaped = dict(lineage)
    del v3_shaped["item_one_locator"]
    v3_shaped["schema_versions"] = {
        **{k: v for k, v in lineage["schema_versions"].items()
           if k != "baseline_packet_manifest_v4"},
        "baseline_packet_manifest_v3": "0.3.0",
    }
    assert not list(v3_schema.iter_errors(v3_shaped)),         "the delta is exactly the successor fields"
    assert list(v4_schema.iter_errors(v3_shaped)), "a v0.3 manifest is not v0.4"
    assert list(v2_schema.iter_errors(lineage))
    assert list(v1_schema.iter_errors(lineage))
    assert list(v4_schema.iter_errors(v2)), "a v0.2 manifest is not a v0.4 one"
    assert "bundle_manifest_sha256" not in lineage
    assert lineage["counts"]["firms_excluded"] >= 1
    assert v2["counts"]["firms_excluded"] == 0


# --- ADR-103 CLI -------------------------------------------------------------------


def _cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, check=False)


def test_cli_single_bundle_packet_mode_still_runs_unchanged(tmp_path):
    completed = _cli("--mode", "build-baseline-packets",
                     "--bundle-dir", str(PACKET_FIXTURES),
                     "--config", str(CONFIG),
                     "--output-dir", str(tmp_path / "out"),
                     "--run-id", "still-works")
    assert completed.returncode == 0, completed.stderr
    written = read_json(tmp_path / "out" / "still-works"
                        / PACKET_MANIFEST_FILENAME)
    assert written["counts"]["firms_excluded"] == 0
    assert "bundle_manifest_sha256" in written


def test_cli_lineage_packet_mode_requires_both_manifests(tmp_path):
    completed = _cli("--mode", "build-baseline-packets-lineage",
                     "--config", str(CONFIG),
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "--aggregate-manifest" in completed.stderr
    assert "--shell-determination-manifest" in completed.stderr
    assert "--item-one-locator" in completed.stderr
    assert not (tmp_path / "o").exists()


def test_cli_lineage_packet_mode_anchors_at_the_repository_root(tmp_path):
    """A synthetic lineage outside the repo is unreachable by construction."""
    root, aggregate, determination, _ = _lineage(tmp_path)
    completed = _cli("--mode", "build-baseline-packets-lineage",
                     "--aggregate-manifest", str(aggregate),
                     "--shell-determination-manifest", str(determination),
                     "--item-one-locator", "item_one_span_v2",
                     "--config", str(CONFIG),
                     "--output-dir", str(tmp_path / "cli"), "--run-id", "r")
    assert completed.returncode == 2
    assert "run directory not found" in completed.stderr
    assert str(ROOT / "shards" / "ra-shard-0000") in completed.stderr
    assert not (tmp_path / "cli").exists()


@pytest.mark.parametrize("flag, value", [
    ("--bundle-dir", "x"), ("--replay-dir", "x"),
    ("--shard-output-dir", "x"), ("--queue-definition", "x"),
])
def test_cli_lineage_packet_mode_accepts_no_other_data_location(
        tmp_path, flag, value):
    completed = _cli("--mode", "build-baseline-packets-lineage",
                     "--aggregate-manifest", "a.json",
                     "--shell-determination-manifest", "d.json",
                     "--config", str(CONFIG), flag, value,
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert flag in completed.stderr
    assert not (tmp_path / "o").exists()


#: Every mode that consumes neither lineage-input flag. No mode may silently
#: ignore either; the sweep in the entrypoint refuses both everywhere else.
_OTHER_MODES = [
    "sentinel", "frame", "acquire-index", "dera-validate", "acquire-dera",
    "baseline-carrier", "acquire-docs", "probe-filing-index",
    "build-baseline-packets", "acquire-primary-docs",
    "determine-shell-company", "plan-acquisition-queue",
    "execute-acquisition-queue", "aggregate-acquisition-queue",
    "aggregate-acquisition-lineage",
]


@pytest.mark.parametrize(
    "mode", _OTHER_MODES + ["determine-asset-backed-issuer-lineage"])
def test_every_other_mode_refuses_the_determination_flag(tmp_path, mode):
    completed = _cli("--mode", mode,
                     "--shell-determination-manifest", "d.json",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "--shell-determination-manifest" in completed.stderr
    assert "does not accept" in completed.stderr


# determine-asset-backed-issuer-lineage is deliberately absent here: it is
# the third aggregate consumer (ADR-106) and accepts the flag; its own test
# module pins that acceptance.
@pytest.mark.parametrize("mode", _OTHER_MODES)
def test_every_other_mode_refuses_the_aggregate_flag(tmp_path, mode):
    completed = _cli("--mode", mode, "--aggregate-manifest", "a.json",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "--aggregate-manifest" in completed.stderr
    assert "does not accept" in completed.stderr


def test_the_shell_lineage_mode_refuses_the_determination_flag(tmp_path):
    completed = _cli("--mode", "determine-shell-company-lineage",
                     "--aggregate-manifest", "a.json",
                     "--shell-determination-manifest", "d.json",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "--shell-determination-manifest" in completed.stderr
    assert "does not accept" in completed.stderr


# --- ADR-104: the closed locator selector -------------------------------------
#
# --item-one-locator is a functional selector over ITEM_ONE_LOCATORS, never
# free provenance text. These pin the dispatch, the refusal, the canonical
# manifest field, and the text route's independence from the selection.

from dynamic_ai_products.ingestion.lineage_packet import (  # noqa: E402
    ITEM_ONE_LOCATORS,
)

COMBINED_DOC = (
    b"<html><p>Items 1 and 2. Business and Properties</p>"
    b"<p>We drill, gather and process; our properties are described together "
    b"with our business, exactly as the combined heading announces. This "
    b"narrative continues long enough to normalize into a passage.</p>"
    b"<p>Item 1A. Risk Factors</p><p>Risks follow here.</p></html>"
)


def _combined_row(root: Path) -> tuple[Path, dict]:
    """A synthetic combined-heading bundle row alongside the fixtures."""
    source = root / "combined_10k.htm"
    source.write_bytes(COMBINED_DOC)
    _, template = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    entry = {**template,
             "cik": "0009900001", "accession": "0009900001-22-000001",
             "local_filename": "combined_10k.htm",
             "selected_document": "combined_10k.htm",
             "source_sha256": sha256(COMBINED_DOC).hexdigest(),
             "source_byte_length": len(COMBINED_DOC)}
    return source, entry


def _selector_lineage(tmp_path: Path):
    """One shard mixing a v3-recoverable row, ordinary rows, and a text row."""
    root = _synth_root(tmp_path)
    shard = _write_shard(root, "ra-shard-0000", [
        _combined_row(root),
        _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm"),
        _fixture_doc(TEXT_FIXTURES, "text-10k-item1a.txt"),
    ])
    aggregate = _write_aggregate(root, [shard], run_ids=("ra",))
    determination = _determine(root, aggregate)
    return root, aggregate, determination


def test_selector_dispatch_reaches_distinct_locators(tmp_path):
    root, aggregate, determination = _selector_lineage(tmp_path)
    v2_run = _build(root, aggregate, determination, tmp_path, run_id="v2",
                    locator="item_one_span_v2")
    v3_run = _build(root, aggregate, determination, tmp_path, run_id="v3",
                    locator="item_one_span_v3")
    # Under v2 the combined row is a recorded failure; under v3 it packetizes.
    v2_fail = {f.cik: f.reason_code for f in v2_run.failures}
    assert v2_fail.get("0009900001") == "missing_item_one"
    v3_packets = {p.cik: p for p in v3_run.packets}
    assert "0009900001" in v3_packets
    assert v3_packets["0009900001"].end_boundary_kind == "item_1a_risk_factors"
    # Every other row's record is byte-identical between the two runs.
    v2_others = {p.cik: p.model_dump(mode="json") for p in v2_run.packets}
    for cik, packet in v3_packets.items():
        if cik != "0009900001":
            assert packet.model_dump(mode="json") == v2_others[cik]


@pytest.mark.parametrize("selector", [
    "item_one_span_v9", "", " item_one_span_v2", "item_one_span_v2 ",
    "find_item_one_span_v3", "ITEM_ONE_SPAN_V3",
])
def test_an_unmapped_selector_is_refused_with_no_output(tmp_path, selector):
    """Exact match only: no whitespace normalization, no aliasing."""
    root, aggregate, determination = _selector_lineage(tmp_path)
    with pytest.raises(PacketBundleError, match="item_one_locator"):
        _build(root, aggregate, determination, tmp_path, locator=selector)
    assert not (tmp_path / "packets").exists()


def test_the_manifest_records_the_canonical_mapping_key(tmp_path):
    root, aggregate, determination = _selector_lineage(tmp_path)
    for run_id, selector in (("mv2", "item_one_span_v2"),
                             ("mv3", "item_one_span_v3")):
        result = _build(root, aggregate, determination, tmp_path,
                        run_id=run_id, locator=selector)
        manifest = read_json(result.manifest_path)
        assert manifest["item_one_locator"] == selector
        assert manifest["item_one_locator"] in ITEM_ONE_LOCATORS
        assert not list(Draft202012Validator(
            read_json(PACKET_MANIFEST_V4_SCHEMA)).iter_errors(manifest))


def test_plain_text_routing_is_selector_independent(tmp_path):
    root, aggregate, determination = _selector_lineage(tmp_path)
    v2_run = _build(root, aggregate, determination, tmp_path, run_id="tv2",
                    locator="item_one_span_v2")
    v3_run = _build(root, aggregate, determination, tmp_path, run_id="tv3",
                    locator="item_one_span_v3")
    v2_text = next(p for p in v2_run.packets if p.cik == "0009300101")
    v3_text = next(p for p in v3_run.packets if p.cik == "0009300101")
    assert v2_text.model_dump(mode="json") == v3_text.model_dump(mode="json")
    assert v2_text.packet_sha256 == v3_text.packet_sha256


def test_cli_refuses_an_unmapped_selector_before_output(tmp_path):
    completed = _cli("--mode", "build-baseline-packets-lineage",
                     "--aggregate-manifest", "a.json",
                     "--shell-determination-manifest", "d.json",
                     "--item-one-locator", "item_one_span_v9",
                     "--config", str(CONFIG),
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize(
    "mode", _OTHER_MODES + ["determine-asset-backed-issuer-lineage"])
def test_every_other_mode_refuses_the_locator_flag(tmp_path, mode):
    completed = _cli("--mode", mode, "--item-one-locator", "item_one_span_v2",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "--item-one-locator" in completed.stderr
    assert "does not accept" in completed.stderr


def test_the_adr104_method_block_hash_matches_phase0():
    """G8: the committed appendix must reproduce the Phase-0 method block
    byte-for-byte; a drifted appendix invalidates the recorded evidence."""
    text = (ROOT / "docs" / "DECISION_LOG.md").read_text(encoding="utf-8")
    begin = "<!-- ADR104-METHOD-BLOCK-BEGIN -->\n"
    end = "<!-- ADR104-METHOD-BLOCK-END -->"
    assert begin in text and end in text
    block = text.split(begin, 1)[1].split(end, 1)[0]
    assert sha256(block.encode("utf-8")).hexdigest() == \
        "b0ef02d3017a300071da304f324d54deae66f36023e6deb47d0aceaeb7ecd742"


# --- ADR-104: Arm B acceptance replay (opt-in; reads data/runs read-only) -----
#
# A full replay of the measured acceptance gates against the pinned ADR-103
# artifacts. It re-runs the production v3 locator over all 730 failures and
# all 7,190 prior HTML successes, so it takes tens of minutes and only runs
# when ADR104_ARMB_REPLAY=1 and the pinned artifacts are present.

_REPLAY_RUN = (ROOT / "data" / "runs" / "baseline-packets"
               / "baseline-packets-domestic-text-lineage-v3-20260818")


@pytest.mark.skipif(
    os.environ.get("ADR104_ARMB_REPLAY") != "1"
    or not _REPLAY_RUN.is_dir(),
    reason="opt-in replay of the Arm B acceptance gates (ADR104_ARMB_REPLAY=1)",
)
def test_armb_acceptance_replay_matches_the_measured_result():
    from collections import Counter

    from dynamic_ai_products.ingestion.errors import IngestionError
    from dynamic_ai_products.ingestion.normalize import (
        find_item_one_span_v2,
        _ITEMS_ONE_AND_TWO_TEXT_RE, _ITEM_ONE_TEXT_RE, _text_offset_map,
    )

    v3 = ITEM_ONE_LOCATORS["item_one_span_v3"]
    fail_raw = (_REPLAY_RUN / "baseline_packet_failures.jsonl").read_bytes()
    assert sha256(fail_raw).hexdigest() == \
        "34e5fc88f0e68062e281484e5ca73b31c336f226dcb82736224ab366486c2ac8"
    failures = [json.loads(l) for l in fail_raw.decode().splitlines()]
    manifest = read_json(_REPLAY_RUN / "baseline_packet_manifest.json")
    row_to_entry = {}
    for shard_record in manifest["shards_consumed"]:
        run_dir = ROOT / shard_record["run_dir"]
        bm = (run_dir / BUNDLE_MANIFEST_FILENAME).read_bytes()
        assert sha256(bm).hexdigest() == shard_record["bundle_manifest_sha256"]
        for entry in json.loads(bm)["documents"]:
            row_to_entry[(entry["cik"], entry["accession"])] = (run_dir, entry)

    # frozen S2 bucket, adr104_bucket_method@1 (missing_item_one branch)
    import re as _re
    tag = _re.compile(rb"<[^>]*>"); ent = _re.compile(rb"&[#a-zA-Z0-9]{1,8};")
    token = _re.compile(rb"(?i)\bItems?\s{0,20}1\b")
    s2ctx = _re.compile(r"items? 1\.? ?(?:and|&) ?2\b")
    s2_bucket = set()
    for f in failures:
        if f["reason_code"] != "missing_item_one":
            continue
        run_dir, entry = row_to_entry[(f["cik"], f["accession"])]
        if entry.get("representation", "html") != "html":
            continue
        raw = (run_dir / entry["local_filename"]).read_bytes()
        stream = ent.sub(b" ", tag.sub(b" ", raw))
        n = max(1, len(stream))
        body = [m for m in token.finditer(stream) if m.start() / n >= 0.15]
        if not body:
            continue
        ctx = _re.sub(rb"\s+", b" ",
                      stream[body[-1].start():body[-1].start() + 90]) \
            .decode("utf-8", "replace").lower()
        if s2ctx.match(ctx):
            s2_bucket.add((f["cik"], f["accession"]))
    assert len(s2_bucket) == 59, "frozen S2 bucket must hold"

    # G4 + G2 + G3 over the 730
    recovered = []
    g2_bad = []
    g3_bad = []
    for f in failures:
        key = (f["cik"], f["accession"])
        run_dir, entry = row_to_entry[key]
        if entry.get("representation", "html") != "html":
            continue
        raw = (run_dir / entry["local_filename"]).read_bytes()
        if f["reason_code"] in ("ambiguous_end_boundary", "no_end_boundary"):
            try:
                find_item_one_span_v2(raw); v2r = ("SUCCESS", "")
            except IngestionError as exc:
                v2r = (exc.reason_code, str(exc))
            try:
                v3(raw); v3r = ("SUCCESS", "")
            except IngestionError as exc:
                v3r = (exc.reason_code, str(exc))
            if v2r != v3r or v3r[0] != f["reason_code"]:
                g2_bad.append(key)
            continue
        try:
            start, end, kind = v3(raw)
        except IngestionError:
            continue
        span = end - start
        recovered.append((key, kind, span, len(raw)))
        text, offsets = _text_offset_map(raw)
        comb = {offsets[m.start()]
                for m in _ITEMS_ONE_AND_TWO_TEXT_RE.finditer(text)}
        plain = {offsets[m.start()]
                 for m in _ITEM_ONE_TEXT_RE.finditer(text)}
        # attribution: v2 failed on these bytes, so no plain start was
        # usable; the recovery is S2-attributed iff a combined match exists.
        if not comb:
            g3_bad.append(key)
        del plain
    s2_recovered = sum(1 for key, *_ in recovered if key in s2_bucket)
    kinds = Counter(kind for _, kind, _, _ in recovered)
    spans = sorted(span for _, _, span, _ in recovered)
    flagged = [1 for _, _, span, doc in recovered
               if span < 4096 or span / doc < 0.005]

    # G1 over the prior successes
    mismatches = 0
    html_checked = 0
    with open(_REPLAY_RUN / "universe_baseline_packets.jsonl") as fh:
        for line in fh:
            p = json.loads(line)
            if p.get("representation", "html") != "html":
                continue
            run_dir, entry = row_to_entry[(p["cik"], p["accession"])]
            raw = (run_dir / entry["local_filename"]).read_bytes()
            got = v3(raw)
            html_checked += 1
            if got != (p["item_one_start"], p["item_one_end"],
                       p["end_boundary_kind"]):
                mismatches += 1

    print(f"\nARM B REPLAY: recovered={len(recovered)} "
          f"s2_bucket={s2_recovered}/59 kinds={dict(kinds)} "
          f"min_span={spans[0] if spans else None} flagged={len(flagged)} "
          f"G1={html_checked} checked/{mismatches} mismatches "
          f"G2_bad={len(g2_bad)} G3_bad={len(g3_bad)}")
    assert s2_recovered == 51, "G4: measured 51/59 must reproduce"
    assert len(recovered) == 82, "measured 82 total recoveries must reproduce"
    # 81 spans end at Item 1A and one at Item 1B — both tiers the rule
    # authorizes. (An earlier summary said "all end at 1A"; the scratch arm
    # never printed the in-bucket kind split, and this is the measured truth.)
    assert kinds == {"item_1a_risk_factors": 81,
                     "item_1b_unresolved_staff_comments": 1}
    assert spans[0] == 57451, "measured minimum span must reproduce"
    assert not flagged
    assert html_checked == 7190 and mismatches == 0, "G1"
    assert not g2_bad, "G2"
    assert not g3_bad, "G3"
