"""Fixture-replay EDGAR full-index acquisition tests.

Governed by SPEC-001 Stage A and SPEC-003 provenance rules. Everything here
runs over local fixture bytes through the injected fixture-replay transport;
no network, no live SEC transport, no model call (W0 gate).
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.universe.frame import (
    FRAME_VERSION_ON_ACQUIRED_BUILD,
    FrameInputError,
    run_frame_builder,
)
from dynamic_ai_products.universe.frame_acquisition import (
    ACQUISITION_MANIFEST_FILENAME,
    FAILURE_RECEIPT_FILENAME,
    AcquisitionPlanError,
    IndexTransportResponse,
    make_fixture_replay_transport,
    run_index_acquisition,
    transport_contract_hash,
    validate_request_plan,
)
from dynamic_ai_products.universe.io_utils import read_json, sha256_file

ROOT = Path(__file__).resolve().parents[2]
REPLAY_DIR = ROOT / "evals" / "fixtures" / "edgar_full_index"
PLAN_PATH = ROOT / "evals" / "fixtures" / "edgar_index_request_plan" / "request_plan.json"
PROJECT_CONFIG = ROOT / "configs" / "project.yaml"
ACQUISITION_SCHEMA_PATH = ROOT / "schemas" / "edgar_index_acquisition_manifest.schema.json"
FRAME_MODULE_PATH = ROOT / "src" / "dynamic_ai_products" / "universe" / "frame.py"
ACQUISITION_MODULE_PATH = (
    ROOT / "src" / "dynamic_ai_products" / "universe" / "frame_acquisition.py"
)
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED_FRAME = read_json(REPLAY_DIR / "expected_frame.json")

FIXED_CLOCK = lambda: datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _plan_payload(entries: list[dict]) -> dict:
    return {
        "plan_contract": "edgar_index_request_plan@0.1.0",
        "description": "test plan",
        "entries": entries,
    }


def _acquire(output_dir: Path, run_id: str, *, transport=None, clock=FIXED_CLOCK):
    return run_index_acquisition(
        repo_root=ROOT,
        request_plan_path=PLAN_PATH,
        output_dir=output_dir,
        run_id=run_id,
        transport=transport or make_fixture_replay_transport(REPLAY_DIR),
        clock=clock,
    )


@pytest.fixture(scope="module")
def acquisition_run(tmp_path_factory: pytest.TempPathFactory):
    return _acquire(tmp_path_factory.mktemp("acq"), "pytest-acquire")


# --- request-plan trust boundary ---------------------------------------------


def test_non_sec_host_is_rejected() -> None:
    with pytest.raises(AcquisitionPlanError, match="canonical"):
        validate_request_plan(_plan_payload([
            {"quarter": "2022-QTR3",
             "url": "https://example.com/Archives/edgar/full-index/2022/QTR3/master.idx"},
        ]))


def test_http_scheme_is_rejected() -> None:
    with pytest.raises(AcquisitionPlanError, match="canonical"):
        validate_request_plan(_plan_payload([
            {"quarter": "2022-QTR3",
             "url": "http://www.sec.gov/Archives/edgar/full-index/2022/QTR3/master.idx"},
        ]))


def test_quarter_and_url_must_agree() -> None:
    with pytest.raises(AcquisitionPlanError, match="canonical"):
        validate_request_plan(_plan_payload([
            {"quarter": "2022-QTR3",
             "url": "https://www.sec.gov/Archives/edgar/full-index/2022/QTR4/master.idx"},
        ]))


def test_duplicate_quarter_is_rejected() -> None:
    entry = {"quarter": "2022-QTR3",
             "url": "https://www.sec.gov/Archives/edgar/full-index/2022/QTR3/master.idx"}
    with pytest.raises(AcquisitionPlanError, match="Duplicate quarter"):
        validate_request_plan(_plan_payload([entry, dict(entry)]))


def test_plan_supplied_filename_is_rejected() -> None:
    # Local paths are derived in code; a plan carrying one (or any unknown
    # key) is refused, so traversal text can never reach the filesystem.
    with pytest.raises(AcquisitionPlanError, match="exactly the keys"):
        validate_request_plan(_plan_payload([
            {"quarter": "2022-QTR3",
             "url": "https://www.sec.gov/Archives/edgar/full-index/2022/QTR3/master.idx",
             "filename": "../../evil.idx"},
        ]))


def test_malformed_quarter_and_out_of_range_year_are_rejected() -> None:
    with pytest.raises(AcquisitionPlanError, match="YYYY-QTRn"):
        validate_request_plan(_plan_payload([
            {"quarter": "2022-Q3", "url": "https://www.sec.gov/x"},
        ]))
    with pytest.raises(AcquisitionPlanError, match="outside"):
        validate_request_plan(_plan_payload([
            {"quarter": "1901-QTR1",
             "url": "https://www.sec.gov/Archives/edgar/full-index/1901/QTR1/master.idx"},
        ]))


def test_derived_filenames_are_safe_and_sorted() -> None:
    entries = validate_request_plan(read_json(PLAN_PATH))
    names = [e.filename for e in entries]
    assert names == sorted(names)
    for name in names:
        assert "/" not in name and ".." not in name
        assert name.startswith("master-") and name.endswith(".idx")


# --- successful acquisition ---------------------------------------------------


def test_acquired_bytes_are_byte_identical_to_replay_source(acquisition_run) -> None:
    for receipt in acquisition_run.receipts:
        acquired = (acquisition_run.run_dir / receipt.filename).read_bytes()
        assert acquired == (REPLAY_DIR / receipt.filename).read_bytes()
        assert receipt.sha256 == sha256_file(REPLAY_DIR / receipt.filename)
        assert receipt.byte_count == len(acquired)


def test_manifest_is_schema_valid_and_truthful_about_transport(acquisition_run) -> None:
    manifest = read_json(acquisition_run.manifest_path)
    Draft202012Validator(read_json(ACQUISITION_SCHEMA_PATH)).validate(manifest)
    assert manifest["transport_kind"] == "fixture_replay"
    assert manifest["transport_contract_hash"] == transport_contract_hash()
    assert manifest["request_plan_sha256"] == sha256_file(PLAN_PATH)
    # No live-client identity may be claimed by a fixture-replay run.
    text = acquisition_run.manifest_path.read_text(encoding="utf-8")
    assert "user_agent" not in text
    assert "collection.transport" not in text


def test_success_leaves_no_failure_receipt(acquisition_run) -> None:
    assert acquisition_run.failure is None
    assert not (acquisition_run.run_dir / FAILURE_RECEIPT_FILENAME).exists()


def test_manifest_bytes_are_deterministic_under_injected_clock(
    acquisition_run, tmp_path: Path
) -> None:
    second = _acquire(tmp_path, "pytest-acquire")
    assert (
        second.manifest_path.read_bytes()
        == acquisition_run.manifest_path.read_bytes()
    )
    for receipt in second.receipts:
        assert (second.run_dir / receipt.filename).read_bytes() == (
            acquisition_run.run_dir / receipt.filename
        ).read_bytes()


def test_run_directory_is_never_reused(acquisition_run) -> None:
    with pytest.raises(FileExistsError):
        _acquire(acquisition_run.run_dir.parent, acquisition_run.run_id)


# --- failure semantics --------------------------------------------------------


def _failing_transport(kind: str):
    real = make_fixture_replay_transport(REPLAY_DIR)

    def transport(url: str) -> IndexTransportResponse:
        if url.endswith("2022/QTR4/master.idx"):
            if kind == "redirect":
                return IndexTransportResponse(
                    status_code=301, final_url=url,
                    content=b"", location="https://www.sec.gov/elsewhere",
                )
            if kind == "mismatch":
                return IndexTransportResponse(
                    status_code=200,
                    final_url="https://www.sec.gov/other", content=b"x",
                )
            raise RuntimeError("boom")
        return real(url)

    return transport


@pytest.mark.parametrize(
    ("kind", "reason"),
    [
        ("redirect", "redirect_refused"),
        ("mismatch", "terminal_url_mismatch"),
        ("exception", "transport_exception"),
    ],
)
def test_failures_write_receipt_and_no_manifest(
    tmp_path: Path, kind: str, reason: str
) -> None:
    result = _acquire(tmp_path, f"fail-{kind}", transport=_failing_transport(kind))
    assert result.manifest_path is None
    assert not (result.run_dir / ACQUISITION_MANIFEST_FILENAME).exists()
    receipt = read_json(result.failure_receipt_path)
    assert receipt["reason_code"] == reason
    assert receipt["attempted_entry"]["quarter"] == "2022-QTR4"
    assert receipt["transport_kind"] == "fixture_replay"
    # The QTR3 file was acquired before the failure and stays recorded.
    assert receipt["files_acquired_before_failure"] == ["master-2022-QTR3.idx"]


def test_missing_replay_file_is_unexpected_http_status(tmp_path: Path) -> None:
    partial = tmp_path / "partial-replay"
    partial.mkdir()
    (partial / "master-2022-QTR3.idx").write_bytes(
        (REPLAY_DIR / "master-2022-QTR3.idx").read_bytes()
    )
    result = _acquire(
        tmp_path / "out", "fail-missing",
        transport=make_fixture_replay_transport(partial),
    )
    assert result.failure.reason_code == "unexpected_http_status"
    assert result.manifest_path is None


# --- frame consumption of the acquisition manifest ---------------------------


def test_frame_build_from_acquisition_matches_committed_gold(
    acquisition_run, tmp_path: Path
) -> None:
    result = run_frame_builder(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        acquisition_manifest_path=acquisition_run.manifest_path,
        output_dir=tmp_path,
        run_id="frame-from-acq",
        filing_window_start=date(2022, 8, 1),
        filing_window_end=date(2023, 2, 28),
    )
    assert result.counts == EXPECTED_FRAME["counts"]
    assert result.frame_version == FRAME_VERSION_ON_ACQUIRED_BUILD
    manifest = read_json(result.manifest_path)
    assert any("fixture_replay" in line for line in manifest["limitations"])
    assert any("hash" in line for line in manifest["limitations"])


def test_tampered_acquired_file_is_refused_before_parsing(
    tmp_path: Path,
) -> None:
    acq = _acquire(tmp_path / "acq", "tamper")
    target = acq.run_dir / "master-2022-QTR3.idx"
    data = bytearray(target.read_bytes())
    data[-1] ^= 0xFF
    target.chmod(0o644)
    target.write_bytes(bytes(data))
    with pytest.raises(FrameInputError, match="hash mismatch"):
        run_frame_builder(
            repo_root=ROOT,
            project_config_path=PROJECT_CONFIG,
            acquisition_manifest_path=acq.manifest_path,
            output_dir=tmp_path / "frame",
            run_id="frame-tampered",
            filing_window_start=date(2022, 8, 1),
            filing_window_end=date(2023, 2, 28),
        )


def _mutated_manifest(acquisition_run, tmp_path: Path, mutate) -> Path:
    """Copy the real manifest, apply one mutation, write it to a bare dir.

    The bundle directory deliberately contains no ``.idx`` files: refusal must
    happen at manifest validation, before any raw file is read or hashed.
    """
    manifest = read_json(acquisition_run.manifest_path)
    mutate(manifest)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    path = bundle / ACQUISITION_MANIFEST_FILENAME
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


def _frame_from(manifest_path: Path, tmp_path: Path, run_id: str):
    return run_frame_builder(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        acquisition_manifest_path=manifest_path,
        output_dir=tmp_path / "frame-out",
        run_id=run_id,
        filing_window_start=date(2022, 8, 1),
        filing_window_end=date(2023, 2, 28),
    )


def test_frame_refuses_manifest_with_extra_property(
    acquisition_run, tmp_path: Path
) -> None:
    def mutate(manifest: dict) -> None:
        manifest["extra_property"] = True

    path = _mutated_manifest(acquisition_run, tmp_path, mutate)
    with pytest.raises(FrameInputError, match="canonical schema"):
        _frame_from(path, tmp_path, "refuse-extra")


def test_frame_refuses_manifest_missing_governed_field(
    acquisition_run, tmp_path: Path
) -> None:
    def mutate(manifest: dict) -> None:
        del manifest["request_plan_sha256"]

    path = _mutated_manifest(acquisition_run, tmp_path, mutate)
    with pytest.raises(FrameInputError, match="canonical schema"):
        _frame_from(path, tmp_path, "refuse-missing")


def test_frame_refuses_unadmitted_transport_kind(
    acquisition_run, tmp_path: Path
) -> None:
    def mutate(manifest: dict) -> None:
        manifest["transport_kind"] = "live"

    path = _mutated_manifest(acquisition_run, tmp_path, mutate)
    # Two layers refuse this: the schema enum and, beside it, the explicit
    # fixture_replay-only consumption check that survives a widened schema.
    # Either message names the admitted value.
    with pytest.raises(FrameInputError, match="fixture_replay"):
        _frame_from(path, tmp_path, "refuse-live")


def test_frame_refuses_duplicate_receipt_filenames(
    acquisition_run, tmp_path: Path
) -> None:
    def mutate(manifest: dict) -> None:
        duplicate = dict(manifest["files"][0])
        duplicate["sha256"] = "0" * 64
        manifest["files"].append(duplicate)
        manifest["counts"]["planned_entries"] += 1
        manifest["counts"]["files_acquired"] += 1

    path = _mutated_manifest(acquisition_run, tmp_path, mutate)
    with pytest.raises(FrameInputError, match="Duplicate receipt filename"):
        _frame_from(path, tmp_path, "refuse-duplicate")


def test_frame_requires_exactly_one_inventory_source(tmp_path: Path) -> None:
    common = {
        "repo_root": ROOT,
        "project_config_path": PROJECT_CONFIG,
        "output_dir": tmp_path,
        "run_id": "inventory-both",
        "filing_window_start": date(2022, 8, 1),
        "filing_window_end": date(2023, 2, 28),
    }
    with pytest.raises(FrameInputError, match="Exactly one"):
        run_frame_builder(
            index_dir=REPLAY_DIR,
            acquisition_manifest_path=tmp_path / "x.json",
            **common,
        )
    with pytest.raises(FrameInputError, match="Exactly one"):
        run_frame_builder(**common)


# --- naming guard -------------------------------------------------------------


def test_acquisition_carries_no_analytical_period_or_live_client_naming() -> None:
    text = ACQUISITION_MODULE_PATH.read_text(encoding="utf-8")
    assert "analytical_period" not in text
    assert "CLIENT_CONTRACT" not in text  # live client identity is not claimed
    schema_text = ACQUISITION_SCHEMA_PATH.read_text(encoding="utf-8")
    assert "analytical_period" not in schema_text


# --- CLI ----------------------------------------------------------------------


def _cli(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *extra], capture_output=True, text=True, cwd=ROOT
    )


def _acquire_args(output_dir: Path, run_id: str) -> list[str]:
    return [
        "--mode", "acquire-index",
        "--request-plan", str(PLAN_PATH),
        "--replay-dir", str(REPLAY_DIR),
        "--output-dir", str(output_dir),
        "--run-id", run_id,
    ]


def test_cli_acquire_then_frame_from_manifest(tmp_path: Path) -> None:
    completed = _cli(*_acquire_args(tmp_path / "acq", "cli-acquire"))
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["files_acquired"] == 3 and payload["failure_reason_code"] is None

    frame = _cli(
        "--mode", "frame",
        "--config", str(PROJECT_CONFIG),
        "--acquisition-manifest", payload["manifest_path"],
        "--filing-window-start", "2022-08-01",
        "--filing-window-end", "2023-02-28",
        "--output-dir", str(tmp_path / "frame"),
        "--run-id", "cli-frame-from-acq",
    )
    assert frame.returncode == 0, frame.stderr
    frame_payload = json.loads(frame.stdout)
    assert frame_payload["frame_version"] == FRAME_VERSION_ON_ACQUIRED_BUILD
    assert frame_payload["counts"] == EXPECTED_FRAME["counts"]


def test_cli_acquire_dry_run_writes_nothing(tmp_path: Path) -> None:
    output_dir = tmp_path / "dry"
    completed = _cli(*_acquire_args(output_dir, "cli-acquire-dry"), "--dry-run")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["dry_run"] is True and payload["run_dir"] is None
    assert not output_dir.exists()


def test_cli_acquire_failure_exits_one_with_receipt(tmp_path: Path) -> None:
    partial = tmp_path / "partial"
    partial.mkdir()
    (partial / "master-2022-QTR3.idx").write_bytes(
        (REPLAY_DIR / "master-2022-QTR3.idx").read_bytes()
    )
    completed = _cli(
        "--mode", "acquire-index",
        "--request-plan", str(PLAN_PATH),
        "--replay-dir", str(partial),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-acquire-fail",
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["failure_reason_code"] == "unexpected_http_status"
    assert payload["manifest_path"] is None
    assert Path(payload["failure_receipt_path"]).exists()


def test_cli_acquire_mode_rejects_other_mode_flags(tmp_path: Path) -> None:
    completed = _cli(
        *_acquire_args(tmp_path / "out", "cli-cross"),
        "--config", str(PROJECT_CONFIG),
    )
    assert completed.returncode == 2
    assert "--config" in completed.stderr


def test_cli_frame_rejects_both_inventory_sources(tmp_path: Path) -> None:
    completed = _cli(
        "--mode", "frame",
        "--config", str(PROJECT_CONFIG),
        "--index-dir", str(REPLAY_DIR),
        "--acquisition-manifest", str(tmp_path / "m.json"),
        "--filing-window-start", "2022-08-01",
        "--filing-window-end", "2023-02-28",
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-both",
    )
    assert completed.returncode == 2
    assert "exactly one of" in completed.stderr


def test_cli_sentinel_rejects_acquire_flags(tmp_path: Path) -> None:
    completed = _cli(
        "--config", str(ROOT / "configs" / "universe_sample_rules.yaml"),
        "--input", str(ROOT / "evals" / "fixtures" / "universe_sentinel"),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-sentinel-cross",
        "--request-plan", str(PLAN_PATH),
    )
    assert completed.returncode == 2
    assert "--request-plan" in completed.stderr
