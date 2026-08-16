"""Live SEC transport binding tests — mocked/injected transport only.

Every test injects a fake send, sleeper, and monotonic clock; no test opens a
socket, performs a real sleep, or reaches sec.gov. The real send
(`sec_index_transport._httpx_send`) is deliberately never called here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.sec_index_transport import (
    SEC_LIVE_TRANSPORT_CONTRACT,
    SEC_LIVE_TRANSPORT_IDENTITY,
    live_transport_contract_hash,
    make_sec_live_transport,
    request_headers,
)
from dynamic_ai_products.universe.frame import (
    FRAME_VERSION_ON_ACQUIRED_BUILD,
    FrameInputError,
    run_frame_builder,
)
from dynamic_ai_products.universe.frame_acquisition import (
    ACQUISITION_MANIFEST_FILENAME,
    AcquisitionPlanError,
    IndexTransportResponse,
    TransportIdentity,
    load_request_plan,
    run_index_acquisition,
)
from dynamic_ai_products.universe.io_utils import read_json, sha256_file

ROOT = Path(__file__).resolve().parents[2]
REPLAY_DIR = ROOT / "evals" / "fixtures" / "edgar_full_index"
PLAN_PATH = ROOT / "evals" / "fixtures" / "edgar_index_request_plan" / "request_plan.json"
CANARY_PLAN_PATH = ROOT / "configs" / "edgar_index_canary_request_plan.json"
FULL_PLAN_PATH = ROOT / "configs" / "edgar_index_full_request_plan.json"
PROJECT_CONFIG = ROOT / "configs" / "project.yaml"
V2_SCHEMA_PATH = ROOT / "schemas" / "edgar_index_acquisition_manifest.v2.schema.json"
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED_FRAME = read_json(REPLAY_DIR / "expected_frame.json")

FIXED_CLOCK = lambda: datetime(2026, 2, 2, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _fake_send_from_fixtures(url: str) -> IndexTransportResponse:
    from dynamic_ai_products.universe.frame_acquisition import (
        make_fixture_replay_transport,
    )

    return make_fixture_replay_transport(REPLAY_DIR)(url)


class _Clock:
    """Deterministic monotonic clock; advances a fixed step per reading."""

    def __init__(self, step: float = 0.1) -> None:
        self.now = 0.0
        self.step = step

    def __call__(self) -> float:
        self.now += self.step
        return self.now


# --- transport policy: spacing, retry, backoff, redirects ---------------------


def test_spacing_is_enforced_between_sends() -> None:
    sleeps: list[float] = []
    transport = make_sec_live_transport(
        send=_fake_send_from_fixtures, sleeper=sleeps.append, monotonic=_Clock(0.1)
    )
    url = "https://www.sec.gov/Archives/edgar/full-index/2022/QTR3/master.idx"
    transport(url)
    transport(url)
    # One fake-clock step (0.1s) elapses between the first send's timestamp
    # and the second send's spacing check; the policy tops the gap up to the
    # contract's 1.0s spacing.
    assert len(sleeps) == 1
    assert sleeps[0] == pytest.approx(
        SEC_LIVE_TRANSPORT_CONTRACT["min_request_spacing_seconds"] - 0.1
    )


def test_retryable_status_is_retried_with_backoff_then_succeeds() -> None:
    calls: list[str] = []

    def send(url: str) -> IndexTransportResponse:
        calls.append(url)
        if len(calls) < 3:
            return IndexTransportResponse(status_code=503, final_url=url, content=b"")
        return _fake_send_from_fixtures(url)

    sleeps: list[float] = []
    transport = make_sec_live_transport(
        send=send, sleeper=sleeps.append, monotonic=_Clock()
    )
    url = "https://www.sec.gov/Archives/edgar/full-index/2022/QTR3/master.idx"
    response = transport(url)
    assert response.status_code == 200 and len(calls) == 3
    backoff = SEC_LIVE_TRANSPORT_CONTRACT["retry_backoff_seconds"]
    assert [s for s in sleeps if s in backoff] == backoff  # 5.0 then 15.0


def test_retry_exhaustion_returns_last_response_for_runner_to_classify() -> None:
    def send(url: str) -> IndexTransportResponse:
        return IndexTransportResponse(status_code=503, final_url=url, content=b"")

    transport = make_sec_live_transport(
        send=send, sleeper=lambda _: None, monotonic=_Clock()
    )
    response = transport(
        "https://www.sec.gov/Archives/edgar/full-index/2022/QTR3/master.idx"
    )
    assert response.status_code == 503  # runner records unexpected_http_status


def test_transport_exception_is_retried_then_propagates() -> None:
    attempts: list[int] = []

    def send(url: str) -> IndexTransportResponse:
        attempts.append(1)
        raise ConnectionError("boom")

    transport = make_sec_live_transport(
        send=send, sleeper=lambda _: None, monotonic=_Clock()
    )
    with pytest.raises(ConnectionError):
        transport("https://www.sec.gov/Archives/edgar/full-index/2022/QTR3/master.idx")
    assert len(attempts) == 1 + SEC_LIVE_TRANSPORT_CONTRACT["max_retries_per_url"]


def test_redirects_are_returned_unfollowed() -> None:
    def send(url: str) -> IndexTransportResponse:
        return IndexTransportResponse(
            status_code=301, final_url=url, content=b"",
            location="https://www.sec.gov/elsewhere",
        )

    transport = make_sec_live_transport(
        send=send, sleeper=lambda _: None, monotonic=_Clock()
    )
    response = transport(
        "https://www.sec.gov/Archives/edgar/full-index/2022/QTR3/master.idx"
    )
    assert response.status_code == 301  # runner refuses: redirect_refused
    assert SEC_LIVE_TRANSPORT_CONTRACT["follows_redirects"] is False


def test_user_agent_names_a_contact_and_headers_are_committed() -> None:
    headers = request_headers()
    assert "@" in headers["User-Agent"]
    assert headers["User-Agent"] == SEC_LIVE_TRANSPORT_CONTRACT["user_agent"]
    assert SEC_LIVE_TRANSPORT_CONTRACT["request_timeout_seconds"] > 0
    assert SEC_LIVE_TRANSPORT_CONTRACT["min_request_spacing_seconds"] >= 1.0


# --- the canonical one-quarter canary plan ------------------------------------


def test_canary_request_plan_is_valid_and_single_quarter() -> None:
    entries, plan_sha256 = load_request_plan(CANARY_PLAN_PATH)
    assert len(entries) == 1  # a sec-live canary run makes exactly one request
    entry = entries[0]
    assert entry.quarter == "2020-QTR1"  # earliest frozen-window quarter (ADR-077)
    assert entry.url == (
        "https://www.sec.gov/Archives/edgar/full-index/2020/QTR1/master.idx"
    )
    assert entry.filename == "master-2020-QTR1.idx"
    assert len(plan_sha256) == 64
    # The three-quarter fixture plan is untouched and stays three quarters.
    fixture_entries, _ = load_request_plan(PLAN_PATH)
    assert len(fixture_entries) == 3


def test_full_range_request_plan_covers_the_frozen_window_contiguously() -> None:
    # Offline only: load_request_plan validates grammar and derives filenames
    # in code; no transport exists in this test.
    entries, plan_sha256 = load_request_plan(FULL_PLAN_PATH)
    assert len(plan_sha256) == 64
    assert len(entries) == 26

    expected_quarters = [
        f"{year}-QTR{qtr}" for year in range(2020, 2026) for qtr in (1, 2, 3, 4)
    ] + ["2026-QTR1", "2026-QTR2"]
    quarters = [entry.quarter for entry in entries]
    assert quarters == expected_quarters  # contiguous, chronological
    assert len(set(quarters)) == 26  # no duplicates

    assert entries[0].quarter == "2020-QTR1"
    assert entries[-1].quarter == "2026-QTR2"
    for entry in entries:
        assert entry.url == (
            "https://www.sec.gov/Archives/edgar/full-index/"
            f"{entry.year}/QTR{entry.qtr}/master.idx"
        )
        assert entry.filename == f"master-{entry.quarter}.idx"

    # The one-quarter canary plan and the synthetic fixture plan are
    # distinct, unchanged inputs.
    canary_entries, _ = load_request_plan(CANARY_PLAN_PATH)
    assert len(canary_entries) == 1
    fixture_entries, _ = load_request_plan(PLAN_PATH)
    assert len(fixture_entries) == 3


# --- transport identity -------------------------------------------------------


def test_identity_hash_is_stable_and_kind_is_validated() -> None:
    assert SEC_LIVE_TRANSPORT_IDENTITY.contract_hash() == live_transport_contract_hash()
    with pytest.raises(AcquisitionPlanError, match="Unknown transport kind"):
        TransportIdentity(kind="carrier_pigeon", contract={"transport_kind": "carrier_pigeon"})
    with pytest.raises(AcquisitionPlanError, match="does not match"):
        TransportIdentity(kind="sec_live", contract={"transport_kind": "fixture_replay"})


# --- runner writes the v0.2 successor manifest for sec_live -------------------


@pytest.fixture(scope="module")
def live_identity_run(tmp_path_factory: pytest.TempPathFactory):
    return run_index_acquisition(
        repo_root=ROOT,
        request_plan_path=PLAN_PATH,
        output_dir=tmp_path_factory.mktemp("live-acq"),
        run_id="pytest-sec-live",
        transport=make_sec_live_transport(
            send=_fake_send_from_fixtures, sleeper=lambda _: None, monotonic=_Clock()
        ),
        clock=FIXED_CLOCK,
        transport_identity=SEC_LIVE_TRANSPORT_IDENTITY,
    )


def test_sec_live_run_writes_schema_valid_v2_manifest(live_identity_run) -> None:
    manifest = read_json(live_identity_run.manifest_path)
    Draft202012Validator(read_json(V2_SCHEMA_PATH)).validate(manifest)
    assert manifest["transport_kind"] == "sec_live"
    assert manifest["transport_contract"] == SEC_LIVE_TRANSPORT_CONTRACT
    assert manifest["transport_contract_hash"] == live_transport_contract_hash()
    assert manifest["schema_versions"] == {
        "edgar_index_acquisition_manifest_v2": "0.2.0"
    }
    assert any("does not authorize frame consumption" in l for l in manifest["limitations"])


def test_sec_live_failure_receipt_records_live_identity(tmp_path: Path) -> None:
    def send(url: str) -> IndexTransportResponse:
        return IndexTransportResponse(status_code=404, final_url=url, content=b"")

    result = run_index_acquisition(
        repo_root=ROOT,
        request_plan_path=PLAN_PATH,
        output_dir=tmp_path,
        run_id="pytest-sec-live-fail",
        transport=make_sec_live_transport(
            send=send, sleeper=lambda _: None, monotonic=_Clock()
        ),
        clock=FIXED_CLOCK,
        transport_identity=SEC_LIVE_TRANSPORT_IDENTITY,
    )
    receipt = read_json(result.failure_receipt_path)
    assert receipt["transport_kind"] == "sec_live"
    assert receipt["transport_contract_hash"] == live_transport_contract_hash()
    assert result.manifest_path is None
    assert not (result.run_dir / ACQUISITION_MANIFEST_FILENAME).exists()


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


def test_frame_consumes_a_valid_v2_live_manifest(
    live_identity_run, tmp_path: Path
) -> None:
    # ADR-079: the separately reviewed sec_live consumption path. The fixture
    # bytes served through the sec_live wrapper are the committed synthetic
    # quarters, so the build must reproduce the committed gold exactly.
    result = _frame_from(live_identity_run.manifest_path, tmp_path, "frame-from-live")
    assert result.counts == EXPECTED_FRAME["counts"]
    assert result.frame_version == FRAME_VERSION_ON_ACQUIRED_BUILD
    limitations = read_json(result.manifest_path)["limitations"]
    parent_sha = sha256_file(live_identity_run.manifest_path)
    assert any(f"sha256={parent_sha}" in line for line in limitations)
    assert any("sec_live" in line for line in limitations)
    assert any(live_transport_contract_hash() in line for line in limitations)


def _mutated_v2_manifest(live_identity_run, tmp_path: Path, mutate) -> Path:
    """Copy the v0.2 manifest, mutate it, write it into a bare directory.

    No ``.idx`` files are placed beside it: every refusal under test must
    happen at manifest validation, before any raw file is read or hashed.
    """
    manifest = read_json(live_identity_run.manifest_path)
    mutate(manifest)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    path = bundle / ACQUISITION_MANIFEST_FILENAME
    path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return path


@pytest.mark.parametrize(
    "mutate",
    [
        lambda m: m.__setitem__("extra_property", True),
        lambda m: m.__delitem__("transport_contract"),
    ],
    ids=["extra-property", "missing-transport-contract"],
)
def test_frame_refuses_malformed_v2_manifest(
    live_identity_run, tmp_path: Path, mutate
) -> None:
    path = _mutated_v2_manifest(live_identity_run, tmp_path, mutate)
    with pytest.raises(FrameInputError, match="canonical schema"):
        _frame_from(path, tmp_path, "refuse-malformed-v2")


def test_frame_refuses_tampered_transport_contract_hash(
    live_identity_run, tmp_path: Path
) -> None:
    def mutate(manifest: dict) -> None:
        manifest["transport_contract_hash"] = "0" * 64  # schema-valid, wrong

    path = _mutated_v2_manifest(live_identity_run, tmp_path, mutate)
    with pytest.raises(FrameInputError, match="does not match its recorded hash"):
        _frame_from(path, tmp_path, "refuse-tampered-contract")


def test_frame_refuses_tampered_raw_file_before_parsing(
    live_identity_run, tmp_path: Path
) -> None:
    import shutil

    bundle = tmp_path / "bundle"
    shutil.copytree(live_identity_run.run_dir, bundle)
    target = bundle / "master-2022-QTR3.idx"
    data = bytearray(target.read_bytes())
    data[-1] ^= 0xFF
    target.write_bytes(bytes(data))
    with pytest.raises(FrameInputError, match="hash mismatch"):
        _frame_from(bundle / ACQUISITION_MANIFEST_FILENAME, tmp_path, "refuse-raw-tamper")


def test_frame_refuses_unknown_transport_kind_v2_shape(
    live_identity_run, tmp_path: Path
) -> None:
    def mutate(manifest: dict) -> None:
        manifest["transport_kind"] = "carrier_pigeon"

    path = _mutated_v2_manifest(live_identity_run, tmp_path, mutate)
    with pytest.raises(FrameInputError, match="no reviewed frame-consumption path"):
        _frame_from(path, tmp_path, "refuse-unknown-kind")


def test_cli_frame_mode_consumes_v2_manifest(
    live_identity_run, tmp_path: Path
) -> None:
    completed = _cli(
        "--mode", "frame",
        "--config", str(PROJECT_CONFIG),
        "--acquisition-manifest", str(live_identity_run.manifest_path),
        "--filing-window-start", "2022-08-01",
        "--filing-window-end", "2023-02-28",
        "--output-dir", str(tmp_path / "frame"),
        "--run-id", "cli-frame-from-v2",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["frame_version"] == FRAME_VERSION_ON_ACQUIRED_BUILD
    assert payload["counts"] == EXPECTED_FRAME["counts"]


# --- fixture-replay behaviour preserved --------------------------------------


def test_fixture_route_still_writes_v01_manifest_without_live_naming(
    tmp_path: Path,
) -> None:
    from dynamic_ai_products.universe.frame_acquisition import (
        make_fixture_replay_transport,
    )

    result = run_index_acquisition(
        repo_root=ROOT,
        request_plan_path=PLAN_PATH,
        output_dir=tmp_path,
        run_id="pytest-fixture-unchanged",
        transport=make_fixture_replay_transport(REPLAY_DIR),
        clock=FIXED_CLOCK,
    )
    manifest = read_json(result.manifest_path)
    assert manifest["transport_kind"] == "fixture_replay"
    assert "transport_contract" not in manifest  # v0.1 shape, not widened
    text = result.manifest_path.read_text(encoding="utf-8")
    assert "sec_live" not in text and "user_agent" not in text


# --- CLI ----------------------------------------------------------------------


def _cli(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *extra], capture_output=True, text=True, cwd=ROOT
    )


def test_cli_sec_live_dry_run_validates_plan_without_any_send(tmp_path: Path) -> None:
    # Dry run returns before the run directory is created and before any
    # transport call, so this is safe to run against the real CLI wiring.
    completed = _cli(
        "--mode", "acquire-index",
        "--transport", "sec-live",
        "--request-plan", str(PLAN_PATH),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-sec-live-dry",
        "--dry-run",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["transport_kind"] == "sec_live"
    assert payload["dry_run"] is True and payload["run_dir"] is None
    assert not (tmp_path / "out").exists()


def test_cli_sec_live_rejects_replay_dir(tmp_path: Path) -> None:
    completed = _cli(
        "--mode", "acquire-index",
        "--transport", "sec-live",
        "--request-plan", str(PLAN_PATH),
        "--replay-dir", str(REPLAY_DIR),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-sec-live-replay",
    )
    assert completed.returncode == 2
    assert "--replay-dir" in completed.stderr


def test_cli_fixture_transport_still_requires_replay_dir(tmp_path: Path) -> None:
    completed = _cli(
        "--mode", "acquire-index",
        "--request-plan", str(PLAN_PATH),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-fixture-missing-replay",
    )
    assert completed.returncode == 2
    assert "--replay-dir" in completed.stderr


def test_cli_other_modes_reject_transport_flag(tmp_path: Path) -> None:
    completed = _cli(
        "--mode", "frame",
        "--config", str(PROJECT_CONFIG),
        "--index-dir", str(REPLAY_DIR),
        "--filing-window-start", "2022-08-01",
        "--filing-window-end", "2023-02-28",
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-frame-transport",
        "--transport", "fixture",
    )
    assert completed.returncode == 2
    assert "--transport" in completed.stderr


# --- ADR-089 no-regression: the index contract is untouched -------------------


def test_index_transport_contract_and_identity_are_unchanged_by_adr_089() -> None:
    """The document transport is a separate identity, not a widening.

    ADR-089 added a streaming send to this module for filing documents. The
    index/DERA contract, identity, and canonical hash must be byte-identical
    to what every existing live manifest recorded, so no prior acquisition's
    provenance changes.
    """
    assert SEC_LIVE_TRANSPORT_CONTRACT == {
        "transport_kind": "sec_live",
        "transport_version": "0.1.0",
        "user_agent": (
            "dynamic-ai-product-evolution research hakanzekigulmez@gmail.com"
        ),
        "min_request_spacing_seconds": 1.0,
        "request_timeout_seconds": 30.0,
        "max_retries_per_url": 2,
        "retry_backoff_seconds": [5.0, 15.0],
        "retry_statuses": [429, 500, 502, 503, 504],
        "follows_redirects": False,
    }
    assert "streaming" not in SEC_LIVE_TRANSPORT_CONTRACT
    assert SEC_LIVE_TRANSPORT_IDENTITY.contract_hash() == (
        live_transport_contract_hash()
    )


def test_document_transport_identity_differs_from_the_index_identity() -> None:
    from dynamic_ai_products.sec_document_transport import (
        SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    )

    assert (
        SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY.contract_hash()
        != SEC_LIVE_TRANSPORT_IDENTITY.contract_hash()
    )
    # Same kind, so both write v0.2-shaped manifests; the recorded hash is
    # what distinguishes a streamed document run from an index run.
    assert SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY.kind == (
        SEC_LIVE_TRANSPORT_IDENTITY.kind
    )


def test_whole_response_send_is_still_the_index_default() -> None:
    """``make_sec_live_transport`` keeps its non-streaming behaviour."""
    calls: list[str] = []

    def fake_send(url: str) -> IndexTransportResponse:
        calls.append(url)
        return IndexTransportResponse(
            status_code=200, final_url=url, content=b"payload"
        )

    transport = make_sec_live_transport(
        send=fake_send, sleeper=lambda s: None, monotonic=lambda: 0.0
    )
    response = transport("https://www.sec.gov/Archives/edgar/full-index/x.idx")
    assert response.content == b"payload"
    assert calls == ["https://www.sec.gov/Archives/edgar/full-index/x.idx"]
