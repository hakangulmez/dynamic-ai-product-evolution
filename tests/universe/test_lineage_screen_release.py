"""ADR-124 tests: a release is a derivation, not a second opinion.

Everything is offline. The refusal cases use small synthetic runs — a handful
of rows is enough to prove a rule — and one read-only integration test runs
against the real completed screen and repair runs when they are present. No
test builds a client, resolves a credential, opens a socket, or writes under
``data/runs``.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import lineage_screen_continuation_v5 as lc5
from dynamic_ai_products import lineage_screen_diagnostic as ld
from dynamic_ai_products import lineage_screen_diagnostic_repair as ldr
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products import lineage_screen_release as lrel
from dynamic_ai_products import lineage_screen_repair as lr
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_screen_live import ROOT  # noqa: E402

CLOCK = lambda: datetime(2026, 8, 23, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731

RECORD_SCHEMA = json.loads(
    (ROOT / lrel.RECORD_SCHEMA).read_text(encoding="utf-8"))
MANIFEST_SCHEMA = json.loads(
    (ROOT / lrel.MANIFEST_SCHEMA).read_text(encoding="utf-8"))

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
    assert not added, f"the release path imported google: {sorted(added)}"


# --- small synthetic sources -------------------------------------------------------


def _sha(payload: bytes) -> str:
    return sha256(payload).hexdigest()


def _row(kind, cik, *, status=None, reason=None, response="resp", origin=None):
    raw = f"{{\"screen_status\": \"{status or 'NONE'}\", \"cik\": \"{cik}\"}}"
    return {
        "record_contract": "universe_screen_record@0.5.0",
        "record_kind": kind, "cik": cik, "company_id": f"CIK{cik}",
        "accession": f"{cik}-22-000001", "form": "10-K",
        "baseline_filing_date": "2022-09-15", "source_id": f"src-{cik}",
        "packet_sha256": _sha(cik.encode()), "prompt_sha256": _sha(b"p"),
        "model_route": {"provider": "google_vertex_ai",
                        "model_label": "gemini-2.5-flash"},
        "screen_status": status,
        "screen_output": {"screen_status": status} if status else None,
        "raw_response_id": f"{response}-{cik}", "raw_response_sha256": _sha(raw.encode()),
        "failure_reason_code": reason, "failure_detail": "detail" if reason else None,
        "provider_attempt_telemetry": None, "truncation_evidence": None,
        "row_provenance": {"origin": origin or "model_called", "source_run_id": None,
                           "source_raw_response_id": None,
                           "source_raw_responses_sha256": None,
                           "source_receipt_sha256": None},
    }


def _truncated_row(cik):
    row = _row("model_output_truncated", cik, reason="max_tokens")
    row["raw_response_id"] = None
    row["raw_response_sha256"] = None
    row["truncation_evidence"] = {
        "reason_code": "max_tokens", "finish_reason": "MAX_TOKENS",
        "capture_reference": "provider_captures/x/generate-attempt-01.bin",
        "capture_sha256": _sha(b"cap"), "count_attempts": 1,
        "generate_attempts": 1, "candidate_token_count": 16384}
    return row


def _insufficient_row(cik):
    row = _row("insufficient_evidence", cik, reason="packet_build_failure",
               origin="packet_build_failure")
    row.update(baseline_filing_date=None, packet_sha256=None, prompt_sha256=None,
               model_route=None, raw_response_id=None, raw_response_sha256=None)
    return row


def _write_base(tmp_path, rows, *, run_id="synthetic-base"):
    d = tmp_path / "base" / run_id
    d.mkdir(parents=True, exist_ok=True)
    records = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                      for r in rows).encode()
    archive = b""
    (d / lc5.CONTINUATION_V5_RECORDS_FILENAME).write_bytes(records)
    (d / ls.RAW_RESPONSES_FILENAME).write_bytes(archive)
    (d / ll.CAPTURE_LEDGER_FILENAME).write_bytes(b"")
    kinds = {k: sum(r["record_kind"] == k for r in rows) for k in (
        "screened_packet", "model_evidence_unverified", "insufficient_evidence",
        "model_output_truncated", "provider_unresolved")}
    manifest = {
        "manifest_contract": "universe_screen_continuation_manifest@0.12.0",
        "run_id": run_id,
        "counts": {
            "planned_rows": len(rows),
            "cohort_rows": len(rows) - kinds["insufficient_evidence"],
            "screened_packets": kinds["screened_packet"],
            "model_evidence_unverified": kinds["model_evidence_unverified"],
            "insufficient_evidence": kinds["insufficient_evidence"],
            "model_output_truncated": kinds["model_output_truncated"],
            "provider_unresolved": kinds["provider_unresolved"],
        },
        "output_hashes": {
            lc5.CONTINUATION_V5_RECORDS_FILENAME: _sha(records),
            ls.RAW_RESPONSES_FILENAME: _sha(archive),
            ll.CAPTURE_LEDGER_FILENAME: _sha(b""),
        },
    }
    path = d / lc5.CONTINUATION_V5_MANIFEST_FILENAME
    path.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return SimpleNamespace(dir=d, path=path, manifest=manifest, rows=rows,
                           sha256=_sha(path.read_bytes()),
                           records_sha256=_sha(records), archive_sha256=_sha(archive))


def _write_repair(tmp_path, base, rows, *, run_id="synthetic-repair",
                  source_overrides=None):
    d = tmp_path / "repair" / run_id
    d.mkdir(parents=True, exist_ok=True)
    for row in rows:
        row["record_contract"] = "universe_screen_record@0.6.0"
    records = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                      for r in rows).encode()
    (d / lr.REPAIR_RECORDS_FILENAME).write_bytes(records)
    (d / ls.RAW_RESPONSES_FILENAME).write_bytes(b"")
    (d / ll.CAPTURE_LEDGER_FILENAME).write_bytes(b"")
    source = {
        "source_run_id": base.manifest["run_id"],
        "source_manifest_sha256": base.sha256,
        "source_records_jsonl_sha256": base.records_sha256,
        "source_raw_responses_jsonl_sha256": base.archive_sha256,
        "source_unmodified": True, "earlier_output_withheld_from_prompt": True,
    }
    source.update(source_overrides or {})
    manifest = {
        "manifest_contract": "universe_screen_repair_manifest@0.1.0",
        "run_id": run_id, "promotable": False,
        "source": source,
        "selection": {"selection_artifact_sha256": _sha(b"sel")},
        "counts": {
            "selected_rows": len(rows),
            "repaired_rows": sum(r["record_kind"] == "screened_packet" for r in rows),
            "still_unverified_rows": sum(
                r["record_kind"] == "model_evidence_unverified" for r in rows),
        },
        "output_hashes": {
            lr.REPAIR_RECORDS_FILENAME: _sha(records),
            ls.RAW_RESPONSES_FILENAME: _sha(b""),
            ll.CAPTURE_LEDGER_FILENAME: _sha(b""),
        },
    }
    path = d / lr.REPAIR_MANIFEST_FILENAME
    path.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return SimpleNamespace(dir=d, path=path, manifest=manifest, rows=rows,
                           sha256=_sha(path.read_bytes()))


@pytest.fixture
def sources(tmp_path):
    """Two valid rows, two unverified (one recovers, one does not), plus the
    two carried-through kinds."""
    base_rows = [
        _row("screened_packet", "0000000001", status="LIKELY_ELIGIBLE"),
        _row("model_evidence_unverified", "0000000002",
             reason="quote_resolution_failure"),
        _row("screened_packet", "0000000003", status="LIKELY_INELIGIBLE"),
        _row("model_evidence_unverified", "0000000004", reason="adapter_rejection"),
        _truncated_row("0000000005"),
        _insufficient_row("0000000006"),
    ]
    base = _write_base(tmp_path, base_rows)
    repair_rows = [
        _row("screened_packet", "0000000002", status="BOUNDARY_OR_UNCERTAIN",
             response="repair"),
        _row("model_evidence_unverified", "0000000004",
             reason="quote_resolution_failure", response="repair"),
    ]
    repair = _write_repair(tmp_path, base, repair_rows)
    return SimpleNamespace(base=base, repair=repair)


def _build(sources, tmp_path, *, release_id="release-fixture", dry_run=False):
    return lrel.build_screen_release(
        repo_root=ROOT, base_manifest_path=sources.base.path,
        base_manifest_sha256=sources.base.sha256,
        repair_manifest_path=sources.repair.path,
        repair_manifest_sha256=sources.repair.sha256,
        output_dir=tmp_path / "releases", release_id=release_id,
        clock=CLOCK, dry_run=dry_run)


def _records(result):
    return [json.loads(x) for x in
            (result.release_dir / lrel.RELEASE_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


# --- the happy path ----------------------------------------------------------------


def test_the_release_reconciles_every_planned_row(sources, tmp_path):
    result = _build(sources, tmp_path)
    assert result.status == "completed"
    records = _records(result)
    assert len(records) == len(sources.base.rows)
    validator = Draft202012Validator(RECORD_SCHEMA, format_checker=FormatChecker())
    for row in records:
        validator.validate(row)
    origins = [r["release_origin"] for r in records]
    assert origins == ["base_valid", "repaired", "base_valid",
                       "unresolved_after_repair", "model_output_truncated",
                       "insufficient_evidence"]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(MANIFEST_SCHEMA, format_checker=FormatChecker()).validate(
        manifest)
    c = manifest["counts"]
    assert (c["base_valid"], c["repaired"], c["unresolved_after_repair"],
            c["insufficient_evidence"], c["model_output_truncated"]) == \
        (2, 1, 1, 1, 1)
    assert c["valid_screened_rows"] == 3
    assert sum(c["by_screen_status"].values()) == 3
    assert c["max_unresolved_after_repair"] == 211
    assert all(manifest["reconciliation"].values())
    assert len(manifest["reconciliation"]) >= 18
    _assert_no_google()


def test_a_repaired_row_keeps_both_provenance_chains(sources, tmp_path):
    result = _build(sources, tmp_path)
    row = next(r for r in _records(result) if r["release_origin"] == "repaired")
    base, repair = row["release_provenance"]["base"], row["release_provenance"]["repair"]
    assert base["run_id"] == sources.base.manifest["run_id"]
    assert base["raw_response_id"] == "resp-0000000002"
    assert base["failure_reason_code"] == "quote_resolution_failure"
    assert repair["run_id"] == sources.repair.manifest["run_id"]
    assert repair["raw_response_id"] == "repair-0000000002"
    assert row["screen_status"] == "BOUNDARY_OR_UNCERTAIN"
    assert row["failure_reason_code"] is None


def test_an_unresolved_row_keeps_both_failure_reasons_and_no_status(sources,
                                                                    tmp_path):
    result = _build(sources, tmp_path)
    row = next(r for r in _records(result)
               if r["release_origin"] == "unresolved_after_repair")
    assert row["record_kind"] == "model_evidence_unverified"
    assert row["screen_status"] is None and row["screen_output"] is None
    assert row["release_provenance"]["base"]["failure_reason_code"] == \
        "adapter_rejection"
    assert row["release_provenance"]["repair"]["failure_reason_code"] == \
        "quote_resolution_failure"
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["unresolved_by_base_reason"] == {"adapter_rejection": 1}
    assert manifest["counts"]["unresolved_by_repair_reason"] == \
        {"quote_resolution_failure": 1}
    # and it is in no status count
    assert sum(manifest["counts"]["by_screen_status"].values()) == \
        manifest["counts"]["valid_screened_rows"]


def test_carried_rows_keep_their_meaning(sources, tmp_path):
    result = _build(sources, tmp_path)
    records = {r["release_origin"]: r for r in _records(result)}
    trunc = records["model_output_truncated"]
    assert trunc["truncation_evidence"]["finish_reason"] == "MAX_TOKENS"
    assert trunc["screen_status"] is None
    assert trunc["release_provenance"] == {"base": None, "repair": None}
    insufficient = records["insufficient_evidence"]
    assert insufficient["record_kind"] == "insufficient_evidence"
    assert insufficient["failure_reason_code"] == "packet_build_failure"


def test_a_base_valid_row_is_never_superseded(sources, tmp_path):
    result = _build(sources, tmp_path)
    for row in _records(result):
        if row["release_origin"] == "base_valid":
            assert row["release_provenance"]["repair"] is None


# --- refusals ----------------------------------------------------------------------


def test_a_wrong_base_digest_is_refused(sources, tmp_path):
    with pytest.raises(ls.ScreenInputError, match="was pinned"):
        lrel.build_screen_release(
            repo_root=ROOT, base_manifest_path=sources.base.path,
            base_manifest_sha256="0" * 64,
            repair_manifest_path=sources.repair.path,
            repair_manifest_sha256=sources.repair.sha256,
            output_dir=tmp_path / "r", release_id="x", clock=CLOCK)


def test_a_wrong_repair_digest_is_refused(sources, tmp_path):
    with pytest.raises(ls.ScreenInputError, match="was pinned"):
        lrel.build_screen_release(
            repo_root=ROOT, base_manifest_path=sources.base.path,
            base_manifest_sha256=sources.base.sha256,
            repair_manifest_path=sources.repair.path,
            repair_manifest_sha256="0" * 64,
            output_dir=tmp_path / "r", release_id="x", clock=CLOCK)


def test_a_drifted_source_output_is_refused(sources, tmp_path):
    path = sources.base.dir / lc5.CONTINUATION_V5_RECORDS_FILENAME
    path.write_bytes(path.read_bytes() + b"\n")
    # the committed continuation loader catches it first, by its own wording
    with pytest.raises(ls.ScreenInputError, match="not consumable"):
        _build(sources, tmp_path)


def test_a_receipt_bearing_source_is_refused(sources, tmp_path):
    (sources.base.dir / ls.FAILURE_RECEIPT_FILENAME).write_text("{}")
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        _build(sources, tmp_path)


def test_a_repair_derived_from_another_base_is_refused(sources, tmp_path):
    repair = _write_repair(tmp_path, sources.base, sources.repair.rows,
                           run_id="foreign-repair",
                           source_overrides={"source_run_id": "some-other-run"})
    sources.repair = repair
    with pytest.raises(ls.ScreenInputError, match="may not be reconciled"):
        _build(sources, tmp_path)


def test_a_repair_recording_other_base_bytes_is_refused(sources, tmp_path):
    repair = _write_repair(tmp_path, sources.base, sources.repair.rows,
                           run_id="drifted-repair",
                           source_overrides={"source_records_jsonl_sha256": "1" * 64})
    sources.repair = repair
    with pytest.raises(ls.ScreenInputError, match="different base"):
        _build(sources, tmp_path)


def test_incomplete_repair_coverage_is_refused(sources, tmp_path):
    repair = _write_repair(tmp_path, sources.base, sources.repair.rows[:1],
                           run_id="short-repair")
    sources.repair = repair
    with pytest.raises(ls.ScreenInputError, match="coverage is not exact"):
        _build(sources, tmp_path)


def test_duplicated_repair_coverage_is_refused(sources, tmp_path):
    rows = sources.repair.rows + [dict(sources.repair.rows[0])]
    repair = _write_repair(tmp_path, sources.base, rows, run_id="dup-repair")
    sources.repair = repair
    with pytest.raises(ls.ScreenInputError, match="two records"):
        _build(sources, tmp_path)


@pytest.mark.parametrize("target,kind", [
    ("0000000001", "screened_packet"),
    ("0000000005", "model_output_truncated"),
    ("0000000006", "insufficient_evidence"),
])
def test_a_repair_targeting_a_non_replaceable_row_is_refused(sources, tmp_path,
                                                             target, kind):
    """Only an unverified base row may be superseded."""
    rows = sources.repair.rows + [
        _row("screened_packet", target, status="LIKELY_ELIGIBLE", response="repair")]
    repair = _write_repair(tmp_path, sources.base, rows, run_id="overreach-repair")
    sources.repair = repair
    with pytest.raises(ls.ScreenInputError, match="coverage is not exact"):
        _build(sources, tmp_path)


def test_a_residual_above_the_pinned_tolerance_is_refused(sources, tmp_path,
                                                          monkeypatch):
    monkeypatch.setattr(lrel, "MAX_UNRESOLVED_AFTER_REPAIR", 0)
    with pytest.raises(ls.ScreenInputError, match="remain unresolved after repair"):
        _build(sources, tmp_path)


def test_the_sources_are_never_modified(sources, tmp_path):
    def snapshot(directory):
        return {str(p.relative_to(directory)): _sha(p.read_bytes())
                for p in sorted(directory.rglob("*")) if p.is_file()}
    before = (snapshot(sources.base.dir), snapshot(sources.repair.dir))
    result = _build(sources, tmp_path)
    assert result.status == "completed"
    assert (snapshot(sources.base.dir), snapshot(sources.repair.dir)) == before
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sources"]["sources_unmodified"] is True
    assert manifest["sources"]["no_model_call"] is True


def test_dry_run_and_write_once(sources, tmp_path):
    dry = _build(sources, tmp_path, dry_run=True)
    assert dry.status == "dry_run" and dry.release_dir is None
    assert not (tmp_path / "releases").exists()
    assert dry.counts["valid_screened_rows"] == 3
    first = _build(sources, tmp_path)
    assert first.status == "completed"
    with pytest.raises(FileExistsError):
        _build(sources, tmp_path)


# --- loaders -----------------------------------------------------------------------


def test_every_run_loader_refuses_the_release(sources, tmp_path):
    result = _build(sources, tmp_path)
    for loader in (ls.require_authoritative_screen_run,
                   ll.require_promotable_screen_run,
                   ld.require_diagnostic_run,
                   ldr.require_diagnostic_repair_run,
                   lc5.require_continuation_v5_run,
                   lr.require_repair_run):
        with pytest.raises(ls.ScreenInputError):
            loader(result.release_dir)
    assert lrel.require_screen_release(result.release_dir).name == \
        lrel.RELEASE_MANIFEST_FILENAME


def test_the_release_loader_refuses_every_run(sources, tmp_path):
    for directory in (sources.base.dir, sources.repair.dir):
        with pytest.raises(ls.ScreenInputError):
            lrel.require_screen_release(directory)
    receipted = tmp_path / "receipted"
    receipted.mkdir()
    (receipted / ls.FAILURE_RECEIPT_FILENAME).write_text("{}")
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        lrel.require_screen_release(receipted)


def test_the_release_loader_refuses_a_drifted_output(sources, tmp_path):
    result = _build(sources, tmp_path)
    path = result.release_dir / lrel.RELEASE_RECORDS_FILENAME
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError, match="no longer hashes"):
        lrel.require_screen_release(result.release_dir)


def test_promotable_loader_is_unchanged_and_refuses_both_sources(sources):
    """ADR-124 adds a loader; it does not widen the promotion gate."""
    for directory in (sources.base.dir, sources.repair.dir):
        with pytest.raises(ls.ScreenInputError):
            ll.require_promotable_screen_run(directory)


# --- CLI -------------------------------------------------------------------------


def _cli_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adr124_cli", ROOT / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _release_argv(tmp_path):
    return [
        "--mode", "build-screen-release",
        "--base-screen-manifest", str(tmp_path / "base.json"),
        "--base-screen-manifest-sha256", "0" * 64,
        "--repair-manifest", str(tmp_path / "repair.json"),
        "--repair-manifest-sha256", "1" * 64,
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "release-cli-fixture",
    ]


def test_the_release_mode_accepts_its_flags(tmp_path):
    cli = _cli_module()
    args = cli.build_parser().parse_args(_release_argv(tmp_path))
    assert cli._reject_cross_mode_flags(args) is None
    _assert_no_google()


@pytest.mark.parametrize("flag,value", [
    ("--governance-root", "gov"),
    ("--screen-authorization", "auth.json"),
    ("--screen-authorization-sha256", "0" * 64),
    ("--packet-manifest", "packets.json"),
    ("--selection-artifact", "selection.json"),
])
def test_the_release_mode_rejects_governance_and_provider_flags(tmp_path, flag,
                                                                value):
    """A reconciliation reaches no provider, so it takes no grant."""
    cli = _cli_module()
    args = cli.build_parser().parse_args(_release_argv(tmp_path) + [flag, value])
    verdict = cli._reject_cross_mode_flags(args)
    assert verdict is not None and flag in verdict


def test_the_release_flags_belong_to_no_other_mode(tmp_path):
    cli = _cli_module()
    args = cli.build_parser().parse_args([
        "--mode", "screen-universe-unverified-repair",
        "--packet-manifest", "p.json", "--selection-artifact", "s.json",
        "--source-screen-manifest", "src.json", "--governance-root", "gov",
        "--screen-authorization", "a.json",
        "--screen-authorization-sha256", "0" * 64,
        "--output-dir", "out", "--run-id", "x",
        "--base-screen-manifest", "b.json",
    ])
    verdict = cli._reject_cross_mode_flags(args)
    assert verdict is not None and "--base-screen-manifest" in verdict


def test_the_release_cli_dry_run_writes_nothing(sources, tmp_path):
    cli = _cli_module()
    out = tmp_path / "cli-out"
    assert cli.main([
        "--mode", "build-screen-release",
        "--base-screen-manifest", str(sources.base.path),
        "--base-screen-manifest-sha256", sources.base.sha256,
        "--repair-manifest", str(sources.repair.path),
        "--repair-manifest-sha256", sources.repair.sha256,
        "--output-dir", str(out), "--run-id", "release-cli-dry", "--dry-run",
    ]) == 0
    assert not out.exists(), "a dry run creates no release directory"
    _assert_no_google()


# --- the real runs, read-only ------------------------------------------------------


def test_the_real_runs_reconcile_when_present(tmp_path):
    """The completed V5b screen and its repair run, read only, skipped if absent."""
    base = (ROOT / "data/runs/universe-screens"
            / "universe-high-recall-continuation-v5b-20260822"
            / lc5.CONTINUATION_V5_MANIFEST_FILENAME)
    repair = (ROOT / "data/runs/universe-screens"
              / "universe-high-recall-unverified-repair-v1-20260823"
              / lr.REPAIR_MANIFEST_FILENAME)
    if not (base.is_file() and repair.is_file()):
        pytest.skip("the completed screen and repair runs are not in this checkout")
    result = lrel.build_screen_release(
        repo_root=ROOT, base_manifest_path=base,
        base_manifest_sha256=_sha(base.read_bytes()),
        repair_manifest_path=repair,
        repair_manifest_sha256=_sha(repair.read_bytes()),
        output_dir=tmp_path / "releases", release_id="real-dry-run",
        clock=CLOCK, dry_run=True)
    assert result.status == "dry_run" and result.release_dir is None
    c = result.counts
    assert c["planned_rows"] == 7572 and c["cohort_rows"] == 7042
    assert (c["base_valid"], c["repaired"], c["unresolved_after_repair"],
            c["insufficient_evidence"], c["model_output_truncated"]) == \
        (6467, 363, 211, 530, 1)
    assert c["valid_screened_rows"] == 6830
    assert c["by_screen_status"] == {"LIKELY_ELIGIBLE": 3075,
                                     "LIKELY_INELIGIBLE": 2876,
                                     "BOUNDARY_OR_UNCERTAIN": 879}
    assert c["max_unresolved_after_repair"] == 211
    assert round(result.rates["pre_repair_unverified_rate"], 4) == 0.0815
    assert round(result.rates["residual_unverified_rate"], 4) == 0.03
    assert not (tmp_path / "releases").exists()
    _assert_no_google()


def test_predecessors_are_byte_identical():
    """ADR-124 adds beside; it moves nothing that already shipped."""
    pins = {
        "prompts/discovery/universe_high_recall_screen.v5.md":
            "fee42d939f9eab590fdcbf055e7b2039e8a33a410dfc12257a47291d7a77d558",
        "prompts/discovery/universe_high_recall_screen_repair.v1.md":
            "2df0342526e4d7fc179424a653bfda4f5878d130ee0c99ebe5d3970f60aa6037",
        "src/dynamic_ai_products/lineage_screen_live.py":
            "795dddb081629ddba184f52070011f1c42a61a669698f3643694a7cceb73c2c2",
        "src/dynamic_ai_products/lineage_screen_repair.py":
            "b0934cde513ab2ddd125c12dce80157807bc32fbdb021305846e30d6f54bce66",
    }
    for path, expected in pins.items():
        actual = sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual == expected, f"{path} moved: {actual}"


def test_the_registry_registers_the_release_contracts():
    registry = json.loads(
        (ROOT / "schemas/schema_version_manifest.json").read_text(encoding="utf-8"))
    assert registry["manifest_version"] == "0.77.0"
    assert len(registry["schemas"]) == 215
    assert registry["schemas"]["universe_screen_release_record"] == "0.1.0"
    assert registry["schemas"]["universe_screen_release_manifest"] == "0.1.0"
