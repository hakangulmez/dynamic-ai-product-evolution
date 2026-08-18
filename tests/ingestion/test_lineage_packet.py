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
           run_id: str = "lpk", dry_run: bool = False):
    return run_lineage_packet_build(
        repo_root=root, aggregate_manifest_path=aggregate,
        determination_manifest_path=determination,
        project_config_path=CONFIG, output_dir=tmp_path / "packets",
        run_id=run_id, clock=FIXED_CLOCK, dry_run=dry_run)


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
    assert not list(Draft202012Validator(read_json(PACKET_MANIFEST_V3_SCHEMA))
                    .iter_errors(manifest))
    assert manifest["packet_record_order"] == PACKET_RECORD_ORDER
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


def test_the_three_packet_manifest_generations_reject_each_other(tmp_path):
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
    assert not list(v2_schema.iter_errors(v2))
    assert not list(v3_schema.iter_errors(lineage))
    assert list(v3_schema.iter_errors(v2)), "a v0.2 manifest is not a v0.3 one"
    assert list(v2_schema.iter_errors(lineage)), "and the converse"
    assert list(v1_schema.iter_errors(lineage))
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
    assert not (tmp_path / "o").exists()


def test_cli_lineage_packet_mode_anchors_at_the_repository_root(tmp_path):
    """A synthetic lineage outside the repo is unreachable by construction."""
    root, aggregate, determination, _ = _lineage(tmp_path)
    completed = _cli("--mode", "build-baseline-packets-lineage",
                     "--aggregate-manifest", str(aggregate),
                     "--shell-determination-manifest", str(determination),
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


@pytest.mark.parametrize("mode", _OTHER_MODES)
def test_every_other_mode_refuses_the_determination_flag(tmp_path, mode):
    completed = _cli("--mode", mode,
                     "--shell-determination-manifest", "d.json",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "--shell-determination-manifest" in completed.stderr
    assert "does not accept" in completed.stderr


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
