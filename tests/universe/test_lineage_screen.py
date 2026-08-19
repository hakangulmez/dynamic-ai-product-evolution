"""ADR-108 production high-recall screen tests — fully offline, mock-only.

Every packet cohort here is a **real** v0.5 packet run: a lineage is
synthesized under a temporary root that symlinks the committed ``schemas/``
directory, the real ADR-102 shell and ADR-105 asset-backed determinations run
over it, and the real ADR-107 two-determination builder emits the manifest
the screen consumes — so the bindings the screen verifies are genuine, never
hand-forged, except where a test forges one field deliberately to prove the
refusal. The lineage-synthesis helpers mirror
``tests/ingestion/test_lineage_packet.py``; they are duplicated rather than
imported because cross-test-module imports couple unrelated suites.

No model API, no network access, no credential, and no production-run hash
literal appears anywhere in this module. The only pinned hashes are the two
predecessor pins at the bottom, which freeze committed repository files so a
silent edit of the screen's evidence contract is loud.
"""

from __future__ import annotations

import itertools
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.ingestion.asset_backed_determination import (
    run_asset_backed_determination,
)
from dynamic_ai_products.ingestion.baseline_packet import (
    FAILURES_FILENAME,
    PACKET_MANIFEST_FILENAME,
    PACKETS_FILENAME,
)
from dynamic_ai_products.ingestion.lineage_packet import (
    run_lineage_packet_build_v2,
)
from dynamic_ai_products.ingestion.shell_company_determination import (
    run_lineage_shell_company_determination,
)
from dynamic_ai_products.universe import lineage_screen as ls
from dynamic_ai_products.universe.io_utils import read_json

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
CONFIG = ROOT / "configs" / "project.yaml"
PACKET_FIXTURES = ROOT / "evals" / "fixtures" / "baseline_packets"
SHELL_FIXTURES = ROOT / "evals" / "fixtures" / "shell_company"
TEXT_FIXTURES = ROOT / "evals" / "fixtures" / "plain_text_primary"

RECORD_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_record.schema.json")
    .read_text(encoding="utf-8"))
MANIFEST_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_manifest.schema.json")
    .read_text(encoding="utf-8"))

ACQ_MANIFEST_FILENAME = "primary_document_acquisition_manifest.json"
BUNDLE_MANIFEST_FILENAME = "bundle_manifest.json"

FIXED_CLOCK = lambda: datetime(2026, 8, 19, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731

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


# --- Lineage synthesis (mirrors tests/ingestion/test_lineage_packet.py) --------


def _synth_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / "schemas").symlink_to(ROOT / "schemas")
    return root


def _fixture_doc(source_dir: Path, filename: str, *, cik: str | None = None,
                 accession: str | None = None) -> tuple[Path, dict]:
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
        "description": "Synthesized ADR-108 fixture shard.",
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


def _write_aggregate(root: Path, shards: list[Path], *,
                     run_ids=("ra", "rb")) -> Path:
    records = [
        _shard_record(root, index, run_dir,
                      len(read_json(run_dir / BUNDLE_MANIFEST_FILENAME)
                          ["documents"]))
        for index, run_dir in enumerate(shards)
    ]
    rows = sum(r["carrier_rows"] for r in records)
    payload = {
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
        "run_timestamp": "2026-08-19T09:00:00+00:00",
        "limitations": ["Synthetic fixture aggregate."],
    }
    path = root / "aggregate.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _v5_run(tmp: Path, shard_docs: list[list[tuple[Path, dict]]] | None = None):
    """A real v0.5 packet run over a synthesized lineage."""
    root = _synth_root(tmp)
    if shard_docs is None:
        shard_docs = [
            [
                _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm"),
                _fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"),
                _fixture_doc(SHELL_FIXTURES, "shell_true_ballotbox.html"),
            ],
            [
                _fixture_doc(PACKET_FIXTURES, "primary_10kt.htm"),
                _fixture_doc(TEXT_FIXTURES, "text-10k-item1a.txt"),
                _fixture_doc(SHELL_FIXTURES, "shell_false_booleanfalse.html"),
            ],
        ]
    run_ids = [f"r{chr(ord('a') + i)}" for i in range(len(shard_docs))]
    shards = [
        _write_shard(root, f"{run_ids[i]}-shard-{i:04d}", docs)
        for i, docs in enumerate(shard_docs)
    ]
    aggregate = _write_aggregate(root, shards, run_ids=run_ids)
    shell_det = run_lineage_shell_company_determination(
        repo_root=root, aggregate_manifest_path=aggregate,
        output_dir=root / "determinations", run_id="shell-det",
        clock=FIXED_CLOCK).manifest_path
    abs_det = run_asset_backed_determination(
        repo_root=root, aggregate_manifest_path=aggregate,
        output_dir=root / "abs-determinations", run_id="abs-det",
        clock=FIXED_CLOCK).manifest_path
    result = run_lineage_packet_build_v2(
        repo_root=root, aggregate_manifest_path=aggregate,
        shell_determination_manifest_path=shell_det,
        asset_backed_determination_manifest_path=abs_det,
        project_config_path=CONFIG, output_dir=tmp / "packets",
        run_id="v5-fixture", item_one_locator="item_one_span_v2",
        clock=FIXED_CLOCK)
    manifest_path = result.manifest_path
    run_dir = manifest_path.parent
    packets = [json.loads(line) for line in
               (run_dir / PACKETS_FILENAME).read_text(encoding="utf-8")
               .splitlines() if line.strip()]
    failures = [json.loads(line) for line in
                (run_dir / FAILURES_FILENAME).read_text(encoding="utf-8")
                .splitlines() if line.strip()]
    return SimpleNamespace(manifest_path=manifest_path, run_dir=run_dir,
                           packets=packets, failures=failures)


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    """One shared, never-mutated v0.5 cohort: 3 packets + 2 failures."""
    built = _v5_run(tmp_path_factory.mktemp("screen-base"))
    assert len(built.packets) == 3 and len(built.failures) == 2
    return built


# --- Screen invocation helpers ---------------------------------------------------


def _raw_output(packet: dict, status: str = "BOUNDARY_OR_UNCERTAIN", *,
                quote: str | None = None, **overrides) -> str:
    passage = packet["passages"][0]
    evidence = []
    if status == "LIKELY_ELIGIBLE" or quote is not None:
        evidence = [{
            "source_id": packet["source_id"],
            "passage_id": passage["passage_id"],
            "quote": quote if quote is not None else passage["text"][:50],
            "supported_claim": "The filing describes an external offering.",
        }]
    payload = {
        "screen_status": status,
        "plausible_customer_facing_digital_product": (
            True if status == "LIKELY_ELIGIBLE" else None),
        "candidate_customer_value_archetypes": [],
        "positive_evidence": evidence,
        "negative_or_boundary_evidence": [],
        "missing_evidence": [],
        "confidence": "medium",
    }
    payload.update(overrides)
    return json.dumps(payload)


def _key(packet: dict) -> str:
    return f"{packet['cik']}:{packet['accession']}"


def _fixture_for(packets: list[dict],
                 statuses: dict[str, str] | None = None) -> dict:
    statuses = statuses or {}
    return {
        _key(p): {"raw": _raw_output(
            p, statuses.get(p["cik"], "BOUNDARY_OR_UNCERTAIN"))}
        for p in packets
    }


def _screen(cohort, out_dir: Path, provider, run_id: str = "scr", *,
            dry_run: bool = False, logical: int | None = None,
            attempts: int | None = None):
    logical = len(cohort.packets) if logical is None else logical
    attempts = (logical * (1 + ls.MAX_TRANSIENT_RETRIES)
                if attempts is None else attempts)
    return ls.run_lineage_screen(
        repo_root=ROOT, packet_manifest_path=cohort.manifest_path,
        provider=provider, output_dir=out_dir, run_id=run_id,
        logical_request_cap=logical, provider_attempt_cap=attempts,
        clock=FIXED_CLOCK, dry_run=dry_run)


def _completed(cohort, tmp_path: Path, statuses=None, run_id="scr"):
    provider = ls.MockLineageScreenProvider(
        _fixture_for(cohort.packets, statuses))
    result = _screen(cohort, tmp_path / "screen", provider, run_id=run_id)
    assert result.status == "completed", result.receipt
    return result, provider


def _records(result) -> list[dict]:
    return [json.loads(line) for line in
            (result.run_dir / ls.RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if line.strip()]


def _tampered(base, tmp_path: Path, *, mutate_packets=None,
              mutate_failures=None, repair: bool = False,
              raw_packets: bytes | None = None) -> SimpleNamespace:
    """Copy the base run and tamper one file, optionally repairing the hash."""
    run_dir = tmp_path / "v5-tampered"
    shutil.copytree(base.run_dir, run_dir)
    for filename, mutate in ((PACKETS_FILENAME, mutate_packets),
                             (FAILURES_FILENAME, mutate_failures)):
        target = run_dir / filename
        if filename == PACKETS_FILENAME and raw_packets is not None:
            target.write_bytes(raw_packets)
        elif mutate is not None:
            rows = [json.loads(line) for line in
                    target.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
            rows = mutate(rows)
            target.write_text(
                "".join(json.dumps(r, sort_keys=True, ensure_ascii=False,
                                   separators=(",", ":")) + "\n"
                        for r in rows),
                encoding="utf-8")
        else:
            continue
        if repair:
            manifest_path = run_dir / PACKET_MANIFEST_FILENAME
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["output_hashes"][filename] = sha256(
                target.read_bytes()).hexdigest()
            manifest_path.write_text(
                json.dumps(manifest, indent=2, sort_keys=True) + "\n",
                encoding="utf-8")
    return SimpleNamespace(manifest_path=run_dir / PACKET_MANIFEST_FILENAME,
                           run_dir=run_dir, packets=base.packets,
                           failures=base.failures)


# --- The cohort -------------------------------------------------------------------


def test_screen_covers_every_retained_row(base, tmp_path):
    result, provider = _completed(base, tmp_path)
    records = _records(result)
    assert len(records) == 5
    kinds = [r["record_kind"] for r in records]
    assert kinds.count("screened_packet") == 3
    assert kinds.count("insufficient_evidence") == 2
    assert provider.calls == 3  # one logical call per valid packet, no more
    assert result.counts["planned_rows"] == 5
    assert result.counts["screened_packets"] == 3
    assert result.counts["insufficient_evidence"] == 2
    assert len(result.reconciliation) >= 10
    assert all(result.reconciliation.values())
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    errors = list(Draft202012Validator(
        MANIFEST_SCHEMA, format_checker=FormatChecker()).iter_errors(manifest))
    assert errors == []
    for record in records:
        assert list(Draft202012Validator(
            RECORD_SCHEMA, format_checker=FormatChecker()
        ).iter_errors(record)) == []


def test_record_order_is_packets_then_failures(base, tmp_path):
    result, _ = _completed(base, tmp_path)
    records = _records(result)
    expected = ([(p["cik"], p["accession"]) for p in base.packets]
                + [(f["cik"], f["accession"]) for f in base.failures])
    assert [(r["cik"], r["accession"]) for r in records] == expected


def test_screened_records_carry_the_packet_bindings(base, tmp_path):
    statuses = {base.packets[0]["cik"]: "LIKELY_ELIGIBLE"}
    result, _ = _completed(base, tmp_path, statuses=statuses)
    by_key = {(r["cik"], r["accession"]): r for r in _records(result)}
    for packet in base.packets:
        record = by_key[(packet["cik"], packet["accession"])]
        assert record["baseline_filing_date"] == packet["baseline_filing_date"]
        assert record["baseline_filing_date"] is not None
        assert record["packet_sha256"] == packet["packet_sha256"]
        assert record["form"] == packet["form"]
        assert record["source_id"] == packet["source_id"]
        assert record["model_route"] == {"provider": "mock",
                                         "model_label": "fixture-replay"}
        assert len(record["prompt_sha256"]) == 64
        assert record["screen_status"] in ls.SCREEN_STATUSES
        assert (record["screen_status"]
                == record["screen_output"]["screen_status"])
    eligible = by_key[(base.packets[0]["cik"], base.packets[0]["accession"])]
    assert eligible["screen_status"] == "LIKELY_ELIGIBLE"
    assert eligible["screen_output"]["positive_evidence"]


def test_insufficient_records_preserve_the_failure_verbatim(base, tmp_path):
    result, _ = _completed(base, tmp_path)
    insufficient = [r for r in _records(result)
                    if r["record_kind"] == "insufficient_evidence"]
    by_key = {(f["cik"], f["accession"]): f for f in base.failures}
    assert len(insufficient) == 2
    for record in insufficient:
        original = by_key[(record["cik"], record["accession"])]
        assert record["failure_reason_code"] == original["reason_code"]
        assert record["failure_detail"] == original["detail"]
        assert record["company_id"] == original["company_id"]
        assert record["source_id"] == original["source_id"]
        # The failures JSONL is the only authority and it carries no filing
        # date: null by contract, never derived from a carrier.
        assert record["baseline_filing_date"] is None
        assert record["screen_status"] is None
        for null_field in ("packet_sha256", "prompt_sha256", "model_route",
                           "raw_response_id", "raw_response_sha256",
                           "screen_output"):
            assert record[null_field] is None


# --- Input authority: hash, schema, UTF-8, partition ------------------------------


def test_tampered_packets_jsonl_is_refused(base, tmp_path):
    raw = (base.run_dir / PACKETS_FILENAME).read_bytes()
    cohort = _tampered(base, tmp_path,
                       raw_packets=raw.replace(b'"10-K"', b'"10-Q"', 1))
    provider = ls.MockLineageScreenProvider(_fixture_for(base.packets))
    with pytest.raises(ls.ScreenInputError, match="hashes to"):
        _screen(cohort, tmp_path / "screen", provider)
    assert not (tmp_path / "screen").exists()


def test_repaired_hash_cannot_admit_a_contract_violation(base, tmp_path):
    def corrupt(rows):
        rows[0]["end_boundary_kind"] = "item_3_financial_statements"
        return rows

    cohort = _tampered(base, tmp_path, mutate_packets=corrupt, repair=True)
    provider = ls.MockLineageScreenProvider(_fixture_for(base.packets))
    with pytest.raises(ls.ScreenInputError,
                       match="universe_baseline_packet@0.2.0"):
        _screen(cohort, tmp_path / "screen", provider)
    assert not (tmp_path / "screen").exists()


def test_repaired_hash_cannot_move_the_partition(base, tmp_path):
    cohort = _tampered(base, tmp_path, mutate_failures=lambda rows: rows[:-1],
                       repair=True)
    provider = ls.MockLineageScreenProvider(_fixture_for(base.packets))
    with pytest.raises(ls.ScreenInputError, match="counts"):
        _screen(cohort, tmp_path / "screen", provider)
    assert not (tmp_path / "screen").exists()


def test_non_utf8_packets_jsonl_refused_even_with_repaired_hash(base, tmp_path):
    run_dir = tmp_path / "v5-tampered"
    shutil.copytree(base.run_dir, run_dir)
    target = run_dir / PACKETS_FILENAME
    target.write_bytes(target.read_bytes() + b'{"cik": "\xff\xfe"}\n')
    manifest_path = run_dir / PACKET_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_hashes"][PACKETS_FILENAME] = sha256(
        target.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    cohort = SimpleNamespace(manifest_path=manifest_path,
                             packets=base.packets, failures=base.failures)
    provider = ls.MockLineageScreenProvider(_fixture_for(base.packets))
    with pytest.raises(ls.ScreenInputError, match="UTF-8"):
        _screen(cohort, tmp_path / "screen", provider)
    assert not (tmp_path / "screen").exists()


def test_missing_inputs_are_refused(base, tmp_path):
    provider = ls.MockLineageScreenProvider({})
    ghost = SimpleNamespace(manifest_path=tmp_path / "nope.json",
                            packets=base.packets, failures=base.failures)
    with pytest.raises(ls.ScreenInputError, match="not found"):
        _screen(ghost, tmp_path / "screen", provider, logical=3)
    run_dir = tmp_path / "v5-missing"
    shutil.copytree(base.run_dir, run_dir)
    (run_dir / FAILURES_FILENAME).unlink()
    cohort = SimpleNamespace(manifest_path=run_dir / PACKET_MANIFEST_FILENAME,
                             packets=base.packets, failures=base.failures)
    with pytest.raises(ls.ScreenInputError, match="missing"):
        _screen(cohort, tmp_path / "screen", provider)
    assert not (tmp_path / "screen").exists()


def test_shared_accession_rows_stay_separate_by_cik(tmp_path):
    """Same accession, same bytes, two CIKs: two records, two firms."""
    source, entry = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    sibling = dict(entry, cik="0000000123")
    cohort = _v5_run(tmp_path, shard_docs=[[(source, entry),
                                            (source, sibling)]])
    assert len(cohort.packets) == 2 and len(cohort.failures) == 0
    accessions = {p["accession"] for p in cohort.packets}
    assert len(accessions) == 1  # genuinely shared
    result, _ = _completed(cohort, tmp_path)
    records = _records(result)
    assert len(records) == 2
    assert len({r["cik"] for r in records}) == 2
    assert result.counts["firms_total"] == 2
    assert result.reconciliation[
        "shared accessions stay separate rows per cik"]


# --- The closed vocabulary and the null conditionals -------------------------------


def test_insufficient_evidence_cannot_be_a_fourth_screen_status(base, tmp_path):
    result, _ = _completed(base, tmp_path)
    records = _records(result)
    screened = next(r for r in records
                    if r["record_kind"] == "screened_packet")
    insufficient = next(r for r in records
                        if r["record_kind"] == "insufficient_evidence")
    validator = Draft202012Validator(RECORD_SCHEMA,
                                     format_checker=FormatChecker())
    forged = dict(screened, screen_status="INSUFFICIENT_EVIDENCE")
    assert list(validator.iter_errors(forged))
    forged = dict(insufficient, screen_status="INSUFFICIENT_EVIDENCE")
    assert list(validator.iter_errors(forged))
    # The roll-up state exists only at firm level, and only non-negatively.
    assert "INSUFFICIENT_EVIDENCE" not in ls.SCREEN_STATUSES


def test_null_date_conditionals_bind_both_kinds(base, tmp_path):
    result, _ = _completed(base, tmp_path)
    records = _records(result)
    screened = next(r for r in records
                    if r["record_kind"] == "screened_packet")
    insufficient = next(r for r in records
                        if r["record_kind"] == "insufficient_evidence")
    validator = Draft202012Validator(RECORD_SCHEMA,
                                     format_checker=FormatChecker())
    assert list(validator.iter_errors(
        dict(screened, baseline_filing_date=None)))
    assert list(validator.iter_errors(
        dict(insufficient, baseline_filing_date="2022-01-01")))
    # And the null carries no model call with it: a date-less screened row
    # or a dated failure row is refused, never repaired.
    assert list(validator.iter_errors(
        dict(insufficient, raw_response_id="ghost")))


# --- Raw-response archive -----------------------------------------------------------


def test_raw_archive_precedes_parsing_and_pins_counters(base, tmp_path):
    outputs = _fixture_for(base.packets)
    outputs[_key(base.packets[1])] = {"raw": "this is { not json"}
    provider = ls.MockLineageScreenProvider(outputs)
    result = _screen(base, tmp_path / "screen", provider)
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "invalid_model_json"
    # Invalid JSON is archived before parsing: raw_responses_captured == k,
    # records_completed_before_failure == k - 1, at k == 2.
    assert receipt["stopping_row_index"] == 2
    assert receipt["raw_responses_captured"] == 2
    assert receipt["records_completed_before_failure"] == 1
    archive_lines = (result.run_dir / ls.RAW_RESPONSES_FILENAME).read_text(
        encoding="utf-8").splitlines()
    assert len(archive_lines) == 2
    last = json.loads(archive_lines[1])
    assert last["raw_response"] == "this is { not json"  # verbatim
    assert last["raw_response_sha256"] == sha256(
        "this is { not json".encode("utf-8")).hexdigest()
    assert not (result.run_dir / ls.RECORDS_FILENAME).exists()
    assert not (result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()


def test_raw_bindings_rederive_from_the_archive(base, tmp_path):
    result, _ = _completed(base, tmp_path)
    archive = {entry["raw_response_id"]: entry for entry in (
        json.loads(line) for line in
        (result.run_dir / ls.RAW_RESPONSES_FILENAME)
        .read_text(encoding="utf-8").splitlines() if line.strip())}
    screened = [r for r in _records(result)
                if r["record_kind"] == "screened_packet"]
    assert len(archive) == len(screened) == 3
    for record in screened:
        entry = archive[record["raw_response_id"]]
        assert entry["cik"] == record["cik"]
        assert entry["accession"] == record["accession"]
        rederived = sha256(entry["raw_response"].encode("utf-8")).hexdigest()
        assert rederived == entry["raw_response_sha256"]
        assert rederived == record["raw_response_sha256"]


def test_output_hashes_cover_both_jsonls(base, tmp_path):
    result, _ = _completed(base, tmp_path)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    hashes = manifest["output_hashes"]
    assert set(hashes) == {ls.RECORDS_FILENAME, ls.RAW_RESPONSES_FILENAME}
    for filename, recorded in hashes.items():
        observed = sha256((result.run_dir / filename).read_bytes()).hexdigest()
        assert observed == recorded


def test_a_tampered_output_is_not_consumable(base, tmp_path):
    result, _ = _completed(base, tmp_path)
    assert ls.require_authoritative_screen_run(result.run_dir)
    archive = result.run_dir / ls.RAW_RESPONSES_FILENAME
    raw = archive.read_bytes()
    archive.write_bytes(raw[:-2] + b"X\n")
    with pytest.raises(ls.ScreenInputError, match="hashes to"):
        ls.require_authoritative_screen_run(result.run_dir)
    archive.write_bytes(raw)  # restore for hygiene within tmp_path
    assert ls.require_authoritative_screen_run(result.run_dir)


# --- Fail-closed receipts: all five reasons, exact counters -------------------------


def test_provider_terminal_error_receipt(base, tmp_path):
    outputs = _fixture_for(base.packets)
    outputs[_key(base.packets[1])] = {"terminal": "scripted terminal failure"}
    provider = ls.MockLineageScreenProvider(outputs)
    result = _screen(base, tmp_path / "screen", provider)
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "provider_error"
    # No raw response exists for the stopping row: captured == k - 1.
    assert receipt["stopping_row_index"] == 2
    assert receipt["raw_responses_captured"] == 1
    assert receipt["records_completed_before_failure"] == 1
    assert receipt["stopping_cik"] == base.packets[1]["cik"]
    assert not (result.run_dir / ls.RECORDS_FILENAME).exists()
    assert not (result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()
    saved = json.loads((result.run_dir / ls.FAILURE_RECEIPT_FILENAME)
                       .read_text(encoding="utf-8"))
    assert saved["reason_code"] == "provider_error"
    assert saved["reason_code"] in ls.RECEIPT_REASON_CODES


def test_adapter_rejection_receipt_at_the_first_row(base, tmp_path):
    outputs = _fixture_for(base.packets)
    broken = json.loads(outputs[_key(base.packets[0])]["raw"])
    del broken["confidence"]
    outputs[_key(base.packets[0])] = {"raw": json.dumps(broken)}
    provider = ls.MockLineageScreenProvider(outputs)
    result = _screen(base, tmp_path / "screen", provider)
    receipt = result.receipt
    assert receipt["reason_code"] == "adapter_rejection"
    assert receipt["stopping_row_index"] == 1
    assert receipt["raw_responses_captured"] == 1  # archived before parsing
    assert receipt["records_completed_before_failure"] == 0


def test_quote_resolution_failure_receipt(base, tmp_path):
    outputs = _fixture_for(base.packets)
    packet = base.packets[0]
    outputs[_key(packet)] = {"raw": _raw_output(
        packet, "LIKELY_ELIGIBLE", quote="words that appear in no passage")}
    provider = ls.MockLineageScreenProvider(outputs)
    result = _screen(base, tmp_path / "screen", provider)
    assert result.receipt["reason_code"] == "quote_resolution_failure"
    assert result.receipt["raw_responses_captured"] == 1
    assert result.receipt["records_completed_before_failure"] == 0

    # An unknown passage id fails the same closed way.
    forged = json.loads(_raw_output(packet, "LIKELY_ELIGIBLE"))
    forged["positive_evidence"][0]["passage_id"] = "ghost-passage"
    outputs[_key(packet)] = {"raw": json.dumps(forged)}
    provider = ls.MockLineageScreenProvider(outputs)
    result = _screen(base, tmp_path / "screen-2", provider, run_id="scr2")
    assert result.receipt["reason_code"] == "quote_resolution_failure"


def test_temporal_violation_receipt(base, tmp_path):
    def leak(rows):
        rows[0]["baseline_filing_date"] = "2031-01-01"
        return rows

    cohort = _tampered(base, tmp_path, mutate_packets=leak, repair=True)
    tampered_packets = [json.loads(line) for line in
                        (cohort.run_dir / PACKETS_FILENAME)
                        .read_text(encoding="utf-8").splitlines()
                        if line.strip()]
    provider = ls.MockLineageScreenProvider(_fixture_for(tampered_packets))
    result = _screen(cohort, tmp_path / "screen", provider)
    receipt = result.receipt
    assert receipt["reason_code"] == "temporal_violation"
    assert receipt["stopping_row_index"] == 1
    assert receipt["raw_responses_captured"] == 1  # archived before the check
    assert receipt["records_completed_before_failure"] == 0


def test_likely_eligible_requires_positive_evidence(base, tmp_path):
    outputs = _fixture_for(base.packets)
    packet = base.packets[0]
    outputs[_key(packet)] = {"raw": _raw_output(
        packet, "LIKELY_ELIGIBLE", positive_evidence=[])}
    provider = ls.MockLineageScreenProvider(outputs)
    result = _screen(base, tmp_path / "screen", provider)
    assert result.status == "failed"
    assert result.receipt["reason_code"] == "adapter_rejection"
    assert "positive evidence" in result.receipt["detail"]


def test_failed_runs_are_write_once_and_not_consumable(base, tmp_path):
    outputs = _fixture_for(base.packets)
    outputs[_key(base.packets[0])] = {"terminal": "scripted"}
    provider = ls.MockLineageScreenProvider(outputs)
    result = _screen(base, tmp_path / "screen", provider, run_id="failed-run")
    assert result.status == "failed"
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        ls.require_authoritative_screen_run(result.run_dir)
    # Run-id reuse is refused for failed directories too.
    with pytest.raises(FileExistsError):
        _screen(base, tmp_path / "screen",
                ls.MockLineageScreenProvider(_fixture_for(base.packets)),
                run_id="failed-run")
    # A manifest-less directory is refused even without a receipt.
    bare = tmp_path / "bare-run"
    bare.mkdir()
    with pytest.raises(ls.ScreenInputError, match="no manifest"):
        ls.require_authoritative_screen_run(bare)


# --- Request accounting --------------------------------------------------------------


def test_transient_retry_arithmetic(base, tmp_path):
    outputs = _fixture_for(base.packets)
    outputs[_key(base.packets[0])]["transient_failures"] = 2
    provider = ls.MockLineageScreenProvider(outputs)
    result = _screen(base, tmp_path / "screen", provider)
    assert result.status == "completed"
    accounting = result.request_accounting
    # Three logical requests; the first row cost 1 + 2 attempts.
    assert accounting["logical_requests_made"] == 3
    assert accounting["provider_attempts_made"] == 5
    assert accounting["rows_retried"] == 1
    assert accounting["logical_request_cap"] == 3
    assert accounting["provider_attempt_cap"] == 9
    # A retry never creates another logical record or archive line.
    archive_lines = (result.run_dir / ls.RAW_RESPONSES_FILENAME).read_text(
        encoding="utf-8").splitlines()
    assert len(archive_lines) == 3


def test_transient_exhaustion_is_a_terminal_receipt(base, tmp_path):
    outputs = _fixture_for(base.packets)
    outputs[_key(base.packets[0])]["transient_failures"] = (
        ls.MAX_TRANSIENT_RETRIES + 1)
    provider = ls.MockLineageScreenProvider(outputs)
    result = _screen(base, tmp_path / "screen", provider)
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "provider_error"
    assert receipt["provider_attempts_made"] == 1 + ls.MAX_TRANSIENT_RETRIES
    assert receipt["raw_responses_captured"] == 0
    assert receipt["records_completed_before_failure"] == 0


def test_caps_are_stated_not_discovered(base, tmp_path):
    provider = ls.MockLineageScreenProvider(_fixture_for(base.packets))
    with pytest.raises(ls.ScreenInputError, match="logical_request_cap"):
        _screen(base, tmp_path / "screen", provider, logical=100)
    with pytest.raises(ls.ScreenInputError, match="provider_attempt_cap"):
        _screen(base, tmp_path / "screen", provider, attempts=1)
    assert not (tmp_path / "screen").exists()
    assert provider.calls == 0
    # The per-attempt charge refuses at the declared ceiling.
    assert ls._charge_attempt(0, 1) == 1
    with pytest.raises(ls._AttemptCapBreach):
        ls._charge_attempt(1, 1)


def test_dry_run_validates_calls_nothing_writes_nothing(base, tmp_path):
    provider = ls.MockLineageScreenProvider(_fixture_for(base.packets))
    result = _screen(base, tmp_path / "screen", provider, dry_run=True)
    assert result.status == "dry_run"
    assert result.run_dir is None
    assert result.planned_screened == 3
    assert result.planned_insufficient == 2
    assert provider.calls == 0
    assert not (tmp_path / "screen").exists()


def test_determinism_and_write_once(base, tmp_path):
    provider_one = ls.MockLineageScreenProvider(_fixture_for(base.packets))
    one = _screen(base, tmp_path / "one", provider_one, run_id="same-id")
    provider_two = ls.MockLineageScreenProvider(_fixture_for(base.packets))
    two = _screen(base, tmp_path / "two", provider_two, run_id="same-id")
    assert ((one.run_dir / ls.RECORDS_FILENAME).read_bytes()
            == (two.run_dir / ls.RECORDS_FILENAME).read_bytes())
    assert ((one.run_dir / ls.RAW_RESPONSES_FILENAME).read_bytes()
            == (two.run_dir / ls.RAW_RESPONSES_FILENAME).read_bytes())
    assert (one.manifest_path.read_bytes() == two.manifest_path.read_bytes())
    with pytest.raises(FileExistsError):
        _screen(base, tmp_path / "one",
                ls.MockLineageScreenProvider(_fixture_for(base.packets)),
                run_id="same-id")


# --- Firm roll-up ----------------------------------------------------------------------


def _synthetic_record(cik: str, kind: str, status: str | None,
                      accession: str = "0000000001-22-000001") -> dict:
    return {"cik": cik, "record_kind": kind, "screen_status": status,
            "accession": accession}


def test_firm_rollup_orders_eligible_over_boundary_over_ineligible():
    records = [
        _synthetic_record("0000000001", "screened_packet", "LIKELY_INELIGIBLE"),
        _synthetic_record("0000000001", "screened_packet", "LIKELY_ELIGIBLE"),
        _synthetic_record("0000000002", "screened_packet", "LIKELY_INELIGIBLE"),
        _synthetic_record("0000000002", "screened_packet",
                          "BOUNDARY_OR_UNCERTAIN"),
        _synthetic_record("0000000003", "screened_packet", "LIKELY_INELIGIBLE"),
        _synthetic_record("0000000004", "insufficient_evidence", None),
    ]
    states = ls.firm_rollup(records)
    assert states == {
        "0000000001": "LIKELY_ELIGIBLE",
        "0000000002": "BOUNDARY_OR_UNCERTAIN",
        "0000000003": "LIKELY_INELIGIBLE",
        "0000000004": "INSUFFICIENT_EVIDENCE",
    }


def test_no_negative_firm_with_any_nonnegative_packet():
    """Property sweep: every status multiset up to three packets per firm."""
    order = ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN", "LIKELY_INELIGIBLE")
    for size in (1, 2, 3):
        for combo in itertools.combinations_with_replacement(order, size):
            for with_insufficient in (False, True):
                records = [
                    _synthetic_record("0000000009", "screened_packet", status)
                    for status in combo
                ]
                if with_insufficient:
                    records.append(_synthetic_record(
                        "0000000009", "insufficient_evidence", None))
                state = ls.firm_rollup(records)["0000000009"]
                expected = next(s for s in order if s in combo)
                assert state == expected
                if any(s in combo for s in
                       ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN")):
                    assert state != "LIKELY_INELIGIBLE"
    # A firm with no screened packet at all is never negative either.
    only_insufficient = [
        _synthetic_record("0000000010", "insufficient_evidence", None)]
    assert ls.firm_rollup(only_insufficient)["0000000010"] == (
        "INSUFFICIENT_EVIDENCE")


def test_rollup_in_the_run_manifest_is_visible_and_nonnegative(base, tmp_path):
    statuses = {p["cik"]: "LIKELY_INELIGIBLE" for p in base.packets}
    result, provider = _completed(base, tmp_path, statuses=statuses)
    rollup = result.counts["firm_rollup"]
    # The two failure rows are two distinct CIKs with no valid packet: they
    # stay visible as INSUFFICIENT_EVIDENCE at roll-up, never negative, and
    # were never model-called.
    assert rollup["INSUFFICIENT_EVIDENCE"] == 2
    assert rollup["LIKELY_INELIGIBLE"] == 3
    assert provider.calls == 3
    assert sum(rollup.values()) == result.counts["firms_total"] == 5


# --- CLI --------------------------------------------------------------------------------


def _cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, check=False)


def _cli_fixture(base, tmp_path: Path, outputs: dict | None = None) -> Path:
    path = tmp_path / "screen_fixture.json"
    path.write_text(json.dumps(outputs or _fixture_for(base.packets)),
                    encoding="utf-8")
    return path


def test_cli_screen_mode_end_to_end(base, tmp_path):
    fixture = _cli_fixture(base, tmp_path)
    completed = _cli("--mode", "screen-universe-lineage",
                     "--packet-manifest", str(base.manifest_path),
                     "--provider", "mock",
                     "--screen-fixture", str(fixture),
                     "--logical-request-cap", "3",
                     "--provider-attempt-cap", "9",
                     "--output-dir", str(tmp_path / "out"),
                     "--run-id", "cli-screen")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "completed"
    assert payload["counts"]["screened_packets"] == 3
    assert payload["counts"]["insufficient_evidence"] == 2
    manifest = read_json(tmp_path / "out" / "cli-screen"
                         / ls.SCREEN_MANIFEST_FILENAME)
    assert manifest["firm_rollup_rule"] == ls.FIRM_ROLLUP_RULE


def test_cli_dry_run_writes_nothing(base, tmp_path):
    fixture = _cli_fixture(base, tmp_path)
    completed = _cli("--mode", "screen-universe-lineage",
                     "--packet-manifest", str(base.manifest_path),
                     "--provider", "mock",
                     "--screen-fixture", str(fixture),
                     "--logical-request-cap", "3",
                     "--provider-attempt-cap", "9",
                     "--output-dir", str(tmp_path / "out"),
                     "--run-id", "cli-dry", "--dry-run")
    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "out").exists()


def test_cli_failed_run_exits_nonzero_with_receipt(base, tmp_path):
    outputs = _fixture_for(base.packets)
    outputs[_key(base.packets[0])] = {"terminal": "scripted"}
    fixture = _cli_fixture(base, tmp_path, outputs)
    completed = _cli("--mode", "screen-universe-lineage",
                     "--packet-manifest", str(base.manifest_path),
                     "--provider", "mock",
                     "--screen-fixture", str(fixture),
                     "--logical-request-cap", "3",
                     "--provider-attempt-cap", "9",
                     "--output-dir", str(tmp_path / "out"),
                     "--run-id", "cli-fail")
    assert completed.returncode == 1
    assert "non-authoritative" in completed.stderr
    run_dir = tmp_path / "out" / "cli-fail"
    assert (run_dir / ls.FAILURE_RECEIPT_FILENAME).exists()
    assert not (run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()


def test_cli_requires_all_screen_flags(tmp_path):
    completed = _cli("--mode", "screen-universe-lineage",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    for flag in ("--packet-manifest", "--provider", "--screen-fixture",
                 "--logical-request-cap", "--provider-attempt-cap"):
        assert flag in completed.stderr
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize("flag,value", [
    ("--bundle-dir", "b"),
    ("--config", "c.yaml"),
    ("--input", "i"),
    ("--seed", "42"),
    ("--aggregate-manifest", "a.json"),
    ("--shell-determination-manifest", "d.json"),
    ("--item-one-locator", "item_one_span_v3"),
    ("--replay-dir", "r"),
])
def test_cli_screen_mode_accepts_no_other_data_location(tmp_path, flag, value):
    completed = _cli("--mode", "screen-universe-lineage", flag, value,
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert flag in completed.stderr
    assert "does not accept" in completed.stderr
    assert not (tmp_path / "o").exists()


_OTHER_MODES = [
    "sentinel", "frame", "acquire-index", "dera-validate", "acquire-dera",
    "baseline-carrier", "acquire-docs", "probe-filing-index",
    "build-baseline-packets", "acquire-primary-docs",
    "determine-shell-company", "determine-shell-company-lineage",
    "determine-asset-backed-issuer-lineage",
    "build-baseline-packets-lineage", "build-baseline-packets-lineage-v2",
    "plan-acquisition-queue", "execute-acquisition-queue",
    "aggregate-acquisition-queue", "aggregate-acquisition-lineage",
]


@pytest.mark.parametrize("mode", _OTHER_MODES)
def test_every_other_mode_refuses_the_screen_flags(tmp_path, mode):
    completed = _cli("--mode", mode,
                     "--packet-manifest", "p.json",
                     "--screen-fixture", "f.json",
                     "--logical-request-cap", "1",
                     "--provider-attempt-cap", "3",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr
    for flag in ("--packet-manifest", "--screen-fixture",
                 "--logical-request-cap", "--provider-attempt-cap"):
        assert flag in completed.stderr
    assert not (tmp_path / "o").exists()


# --- Boundary and predecessor pins ---------------------------------------------------


def test_filename_constants_match_the_ingestion_originals():
    """The one-way import boundary forbids importing these; equality is the
    relational binding that makes a rename on either side loud."""
    from dynamic_ai_products.ingestion import baseline_packet as bp

    assert ls.PACKET_MANIFEST_FILENAME == bp.PACKET_MANIFEST_FILENAME
    assert ls.PACKETS_FILENAME == bp.PACKETS_FILENAME
    assert ls.PACKET_FAILURES_FILENAME == bp.FAILURES_FILENAME


def test_prompt_is_evidence_minimal(base):
    template = (ROOT / ls.PROMPT_TEMPLATE_RELATIVE_PATH).read_text(
        encoding="utf-8")
    packet = base.packets[0]
    rendered = ls.render_lineage_screen_prompt(template, packet)
    assert "{{" not in rendered
    start = rendered.index("COMPANY_METADATA:\n") + len("COMPANY_METADATA:\n")
    end = rendered.index("\n\nBASELINE_SEC_PASSAGES:")
    metadata = rendered[start:end]
    # Exactly four evidence-minimal lines: no name, ticker, exchange or SIC.
    assert metadata == (
        f"cik: {packet['cik']}\n"
        f"accession: {packet['accession']}\n"
        f"form: {packet['form']}\n"
        f"filing_date: {packet['baseline_filing_date']}"
    )
    for passage in packet["passages"]:
        assert passage["text"] in rendered


def test_predecessor_files_are_byte_identical():
    """ADR-108 pins its two behavioral predecessors: the canonical screen
    prompt template (whose placeholders the production renderer fills
    evidence-minimally) and the sentinel screening module it deliberately
    does not modify. A change to either must arrive with its own decision,
    not ride along silently."""
    template = (ROOT / "prompts" / "discovery"
                / "universe_high_recall_screen.md").read_bytes()
    assert sha256(template).hexdigest() == (
        "4ac95a4c4e6ffdfbc55de7aec98fe4d50b89c29fab79e75a10c07cc35d102194")
    sentinel = (ROOT / "src" / "dynamic_ai_products" / "universe"
                / "screening.py").read_bytes()
    assert sha256(sentinel).hexdigest() == (
        "0de87e71be2277e4479b0587433a73bb7d725b8b1b8926e96e56ebca38db7a7a")


def test_registry_registers_the_two_screen_schemas():
    registry = json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json")
        .read_text(encoding="utf-8"))
    assert registry["manifest_version"] == "0.47.0"
    assert len(registry["schemas"]) == 103
    assert registry["schemas"]["universe_screen_record"] == "0.1.0"
    assert registry["schemas"]["universe_screen_manifest"] == "0.1.0"
