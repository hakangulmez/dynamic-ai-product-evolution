"""DERA FSDS archive acquisition tests (ADR-082) — fully offline.

Every test uses the fixture-replay transport or an injected fake send; no
test opens a socket, reads ``data/runs``, or calls a model. Malicious ZIP
variants are constructed inside tests, never committed.
"""

from __future__ import annotations

import io
import json
import shutil
import subprocess
import sys
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.sec_index_transport import (
    SEC_LIVE_TRANSPORT_CONTRACT,
    SEC_LIVE_TRANSPORT_IDENTITY,
    live_transport_contract_hash,
)
from dynamic_ai_products.universe import dera_acquisition as da
from dynamic_ai_products.universe.dera_acquisition import (
    DERA_ACQUISITION_MANIFEST_FILENAME,
    DERA_FAILURE_RECEIPT_FILENAME,
    DeraPlanError,
    load_dera_request_plan,
    make_dera_fixture_replay_transport,
    run_dera_acquisition,
    validate_dera_request_plan,
)
from dynamic_ai_products.universe.frame import run_frame_builder
from dynamic_ai_products.universe.frame_acquisition import IndexTransportResponse
from dynamic_ai_products.universe.frame_dera_validation import run_dera_validation
from dynamic_ai_products.universe.io_utils import read_json, sha256_file

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE_FIXTURES = ROOT / "evals" / "fixtures" / "dera_fsds_archives"
PLAN_PATH = ARCHIVE_FIXTURES / "request_plan.json"
CANARY_PLAN_PATH = ROOT / "configs" / "dera_fsds_canary_request_plan.json"
DERA_TSV_FIXTURES = ROOT / "evals" / "fixtures" / "dera_fsds"
FRAME_FIXTURE_DIR = ROOT / "evals" / "fixtures" / "edgar_full_index"
PROJECT_CONFIG = ROOT / "configs" / "project.yaml"
V1_SCHEMA = ROOT / "schemas" / "dera_fsds_acquisition_manifest.schema.json"
V2_SCHEMA = ROOT / "schemas" / "dera_fsds_acquisition_manifest.v2.schema.json"
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED_VALIDATION = read_json(DERA_TSV_FIXTURES / "expected_validation.json")

FIXED_CLOCK = lambda: datetime(2026, 4, 4, 7, 0, 0, tzinfo=timezone.utc)  # noqa: E731

TEMPLATE = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{release}.zip"


def _plan_payload(**overrides) -> dict:
    payload = {
        "plan_contract": "dera_fsds_request_plan@0.1.0",
        "description": "test plan",
        "url_template": TEMPLATE,
        "observed_through": "2022-12-31",
        "observed_through_basis": "test basis",
        "releases": ["2022q4"],
    }
    payload.update(overrides)
    return payload


def _acquire(output_dir: Path, run_id: str, *, plan=PLAN_PATH, transport=None,
             identity=None, dry_run=False):
    return run_dera_acquisition(
        repo_root=ROOT,
        request_plan_path=plan,
        output_dir=output_dir,
        run_id=run_id,
        transport=transport or make_dera_fixture_replay_transport(ARCHIVE_FIXTURES),
        clock=FIXED_CLOCK,
        dry_run=dry_run,
        transport_identity=identity,
    )


@pytest.fixture(scope="module")
def acquisition_run(tmp_path_factory: pytest.TempPathFactory):
    return _acquire(tmp_path_factory.mktemp("dera-acq"), "pytest-dera-acquire")


def _zip_bytes(members: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, data in members.items():
            zf.writestr(zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0)), data)
    return buffer.getvalue()


def _replay_with_zip(tmp_path: Path, zip_bytes: bytes) -> tuple[Path, Path]:
    """A one-release plan plus a replay dir serving the given ZIP bytes."""
    replay = tmp_path / "replay"
    replay.mkdir()
    (replay / "dera-2022q4.zip").write_bytes(zip_bytes)
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_plan_payload()) + "\n", encoding="utf-8")
    return plan, replay


# --- request-plan grammar ------------------------------------------------------


def test_plan_requires_https_sec_gov_template() -> None:
    for template in (
        "http://www.sec.gov/files/{release}.zip",
        "https://example.com/files/{release}.zip",
    ):
        with pytest.raises(DeraPlanError, match="https:// on host www.sec.gov"):
            validate_dera_request_plan(_plan_payload(url_template=template))


def test_plan_requires_exactly_one_release_placeholder() -> None:
    for template in (
        "https://www.sec.gov/files/data.zip",
        "https://www.sec.gov/{release}/{release}.zip",
    ):
        with pytest.raises(DeraPlanError, match="exactly one"):
            validate_dera_request_plan(_plan_payload(url_template=template))


def test_malformed_format_string_templates_are_plan_errors_not_valueerror() -> None:
    # Regression: an unmatched or extra brace must surface as DeraPlanError
    # under the contract wording, never escape as a raw ValueError from
    # str.format() during entry derivation.
    for template in (
        "https://www.sec.gov/files/{release}.zip}",   # extra closing brace
        "https://www.sec.gov/files/}{release}.zip",   # stray leading brace
        "https://www.sec.gov/files/{release.zip",     # unterminated placeholder
    ):
        with pytest.raises(DeraPlanError, match="exactly one"):
            validate_dera_request_plan(_plan_payload(url_template=template))


def test_plan_release_grammar_and_duplicates() -> None:
    with pytest.raises(DeraPlanError, match="YYYYq"):
        validate_dera_request_plan(_plan_payload(releases=["2022-Q4"]))
    with pytest.raises(DeraPlanError, match="Duplicate release"):
        validate_dera_request_plan(_plan_payload(releases=["2022q4", "2022q4"]))
    with pytest.raises(DeraPlanError, match="outside"):
        validate_dera_request_plan(_plan_payload(releases=["1999q1"]))


def test_plan_requires_observed_through_and_basis() -> None:
    with pytest.raises(DeraPlanError, match="exactly the keys"):
        payload = _plan_payload()
        del payload["observed_through_basis"]
        validate_dera_request_plan(payload)
    with pytest.raises(DeraPlanError, match="non-empty evidence"):
        validate_dera_request_plan(_plan_payload(observed_through_basis="  "))


def test_committed_canary_plan_is_single_release_with_basis() -> None:
    entries, fields, plan_sha = load_dera_request_plan(CANARY_PLAN_PATH)
    assert len(entries) == 1
    assert entries[0].release == "2020q1"
    assert entries[0].zip_filename == "dera-2020q1.zip"
    assert fields["observed_through"] == "2020-03-31"
    assert "release-quarter-end" in fields["observed_through_basis"]
    assert len(plan_sha) == 64


# --- successful acquisition and extraction ------------------------------------


def test_raw_zips_and_extracted_subs_are_byte_faithful(acquisition_run) -> None:
    for receipt in acquisition_run.receipts:
        raw = (acquisition_run.run_dir / receipt.zip_filename).read_bytes()
        assert raw == (ARCHIVE_FIXTURES / receipt.zip_filename).read_bytes()
        extracted = (acquisition_run.run_dir / receipt.sub_filename).read_bytes()
        source_tsv = DERA_TSV_FIXTURES / f"sub_{receipt.release}.tsv"
        assert extracted == source_tsv.read_bytes()
        assert receipt.member_sha256 == receipt.sub_sha256
        assert receipt.member_name == "sub.txt"


def test_v01_manifest_is_schema_valid_with_ceiling_and_basis(acquisition_run) -> None:
    manifest = read_json(acquisition_run.manifest_path)
    Draft202012Validator(read_json(V1_SCHEMA)).validate(manifest)
    assert manifest["transport_kind"] == "fixture_replay"
    assert "transport_contract" not in manifest  # v0.1 shape, not widened
    assert manifest["max_sub_uncompressed_bytes"] == 512 * 1024 * 1024
    assert manifest["observed_through"] == "2022-12-31"
    assert "conservative" in manifest["observed_through_basis"]
    assert manifest["request_plan_sha256"] == sha256_file(PLAN_PATH)
    for name, digest in manifest["output_hashes"].items():
        assert sha256_file(acquisition_run.run_dir / name) == digest


def test_consumer_bundle_is_written_with_plan_authored_fields(acquisition_run) -> None:
    bundle = read_json(acquisition_run.bundle_manifest_path)
    # The exact keys the committed dera-validate consumer requires:
    for key in ("description", "observed_through", "loaded_releases", "sub_files"):
        assert key in bundle
    assert bundle["observed_through"] == "2022-12-31"  # verbatim from the plan
    assert bundle["observed_through_basis"].startswith("Deliberately conservative")
    assert bundle["loaded_releases"] == ["2022q4", "2023q1"]
    assert bundle["sub_files"] == ["dera-2022q4-sub.tsv", "dera-2023q1-sub.tsv"]
    assert bundle["request_plan_sha256"] == sha256_file(PLAN_PATH)


def test_acquired_bundle_validates_frame_reproducing_adr081_gold(
    acquisition_run, tmp_path: Path
) -> None:
    # End-to-end: fixture frame + acquired DERA bundle -> the committed gold,
    # proving consumer compatibility without touching frame_dera_validation.
    frame = run_frame_builder(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        index_dir=FRAME_FIXTURE_DIR,
        output_dir=tmp_path,
        run_id="dera-acq-frame",
        filing_window_start=date(2022, 8, 1),
        filing_window_end=date(2023, 2, 28),
    )
    result = run_dera_validation(
        repo_root=ROOT,
        frame_manifest_path=frame.run_dir / "filer_frame_manifest.json",
        dera_dir=acquisition_run.run_dir,
        output_dir=tmp_path / "val",
        run_id="dera-acq-validate",
    )
    assert result.gate_status == "pass"
    assert result.counts == EXPECTED_VALIDATION["counts"]


def test_observed_through_is_never_computed_by_the_runner(acquisition_run) -> None:
    # The loaded releases extend into 2023q1, yet observed_through stays the
    # plan-authored 2022-12-31: passthrough, never inference.
    manifest = read_json(acquisition_run.manifest_path)
    assert manifest["observed_through"] == "2022-12-31"
    assert "2023" not in manifest["observed_through"]


def test_manifest_bytes_deterministic_under_injected_clock(
    acquisition_run, tmp_path: Path
) -> None:
    second = _acquire(tmp_path, "pytest-dera-acquire")
    assert (
        second.manifest_path.read_bytes()
        == acquisition_run.manifest_path.read_bytes()
    )
    assert (
        second.bundle_manifest_path.read_bytes()
        == acquisition_run.bundle_manifest_path.read_bytes()
    )


def test_run_directory_never_reused_and_dry_run_sends_nothing(
    acquisition_run, tmp_path: Path
) -> None:
    with pytest.raises(FileExistsError):
        _acquire(acquisition_run.run_dir.parent, acquisition_run.run_id)

    def exploding_transport(url: str) -> IndexTransportResponse:
        raise AssertionError("dry run must never call the transport")

    out = tmp_path / "dry"
    result = _acquire(out, "dry", transport=exploding_transport, dry_run=True)
    assert result.manifest_path is None and not out.exists()


# --- v0.2 sec_live identity (mocked send only) ---------------------------------


def test_sec_live_identity_writes_schema_valid_v2_manifest(tmp_path: Path) -> None:
    fixture_replay = make_dera_fixture_replay_transport(ARCHIVE_FIXTURES)
    result = _acquire(
        tmp_path, "pytest-dera-live",
        transport=fixture_replay,  # mocked bytes; identity declares sec_live
        identity=SEC_LIVE_TRANSPORT_IDENTITY,
    )
    manifest = read_json(result.manifest_path)
    Draft202012Validator(read_json(V2_SCHEMA)).validate(manifest)
    assert manifest["transport_kind"] == "sec_live"
    assert manifest["transport_contract"] == SEC_LIVE_TRANSPORT_CONTRACT
    assert manifest["transport_contract_hash"] == live_transport_contract_hash()


# --- refusals: transport and unsafe archives -----------------------------------

SUB_BYTES = (DERA_TSV_FIXTURES / "sub_2022q4.tsv").read_bytes()


@pytest.mark.parametrize(
    ("members", "reason"),
    [
        ({"data/other.txt": b"x"}, "missing_sub_member"),
        ({"sub.txt": b"a", "../evil.txt": b"x"}, "unsafe_member_path"),
        ({"/abs.txt": b"x", "sub.txt": b"a"}, "unsafe_member_path"),
    ],
    ids=["missing-sub", "traversal-member", "absolute-member"],
)
def test_unsafe_or_incomplete_archives_are_refused(
    tmp_path: Path, members: dict, reason: str
) -> None:
    plan, replay = _replay_with_zip(tmp_path, _zip_bytes(members))
    result = _acquire(tmp_path / "out", f"refuse-{reason}", plan=plan,
                      transport=make_dera_fixture_replay_transport(replay))
    assert result.failure is not None
    assert result.failure.reason_code == reason
    assert result.manifest_path is None
    assert not (result.run_dir / DERA_ACQUISITION_MANIFEST_FILENAME).exists()
    # The raw ZIP was preserved before the refusal; nothing was extracted.
    assert (result.run_dir / "dera-2022q4.zip").exists()
    assert not list(result.run_dir.glob("*.tsv"))


@pytest.mark.filterwarnings("ignore:Duplicate name")
def test_duplicate_sub_member_is_refused(tmp_path: Path) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(zipfile.ZipInfo("sub.txt", date_time=(2020, 1, 1, 0, 0, 0)), b"a")
        zf.writestr(zipfile.ZipInfo("sub.txt", date_time=(2020, 1, 1, 0, 0, 0)), b"b")
    plan, replay = _replay_with_zip(tmp_path, buffer.getvalue())
    result = _acquire(tmp_path / "out", "refuse-dup", plan=plan,
                      transport=make_dera_fixture_replay_transport(replay))
    assert result.failure.reason_code == "duplicate_sub_member"


def test_corrupt_zip_is_refused_with_raw_bytes_preserved(tmp_path: Path) -> None:
    plan, replay = _replay_with_zip(tmp_path, b"this is not a zip archive")
    result = _acquire(tmp_path / "out", "refuse-corrupt", plan=plan,
                      transport=make_dera_fixture_replay_transport(replay))
    assert result.failure.reason_code == "corrupt_zip"
    assert (result.run_dir / "dera-2022q4.zip").read_bytes() == (
        b"this is not a zip archive"
    )
    receipt = read_json(result.failure_receipt_path)
    assert receipt["attempted_release"]["release"] == "2022q4"
    assert receipt["transport_kind"] == "fixture_replay"


def test_over_ceiling_member_is_refused_before_extraction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(da, "MAX_SUB_UNCOMPRESSED_BYTES", 8)
    plan, replay = _replay_with_zip(tmp_path, _zip_bytes({"sub.txt": SUB_BYTES}))
    result = _acquire(tmp_path / "out", "refuse-ceiling", plan=plan,
                      transport=make_dera_fixture_replay_transport(replay))
    assert result.failure.reason_code == "member_over_ceiling"
    assert "ceiling" in result.failure.detail
    assert not list(result.run_dir.glob("*.tsv"))


def test_http_failure_writes_receipt_and_no_manifest(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps(_plan_payload()) + "\n", encoding="utf-8")
    empty_replay = tmp_path / "replay"
    empty_replay.mkdir()
    result = _acquire(tmp_path / "out", "refuse-404", plan=plan,
                      transport=make_dera_fixture_replay_transport(empty_replay))
    assert result.failure.reason_code == "unexpected_http_status"
    assert result.manifest_path is None
    assert (result.run_dir / DERA_FAILURE_RECEIPT_FILENAME).exists()


# --- CLI ------------------------------------------------------------------------


def _cli(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *extra], capture_output=True, text=True, cwd=ROOT
    )


def test_cli_acquire_dera_happy_path_and_dry_run(tmp_path: Path) -> None:
    completed = _cli(
        "--mode", "acquire-dera",
        "--request-plan", str(PLAN_PATH),
        "--replay-dir", str(ARCHIVE_FIXTURES),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-dera-acq",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["archives_acquired"] == 2
    assert Path(payload["manifest_path"]).exists()
    assert Path(payload["bundle_manifest_path"]).exists()

    dry_dir = tmp_path / "dry"
    dry = _cli(
        "--mode", "acquire-dera",
        "--transport", "sec-live",
        "--request-plan", str(CANARY_PLAN_PATH),
        "--output-dir", str(dry_dir),
        "--run-id", "cli-dera-dry",
        "--dry-run",
    )
    assert dry.returncode == 0, dry.stderr
    assert not dry_dir.exists()  # plan validated, nothing sent or written


def test_cli_acquire_dera_failure_exits_one(tmp_path: Path) -> None:
    empty_replay = tmp_path / "replay"
    empty_replay.mkdir()
    completed = _cli(
        "--mode", "acquire-dera",
        "--request-plan", str(PLAN_PATH),
        "--replay-dir", str(empty_replay),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-dera-fail",
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["failure_reason_code"] == "unexpected_http_status"


def test_cli_mode_isolation(tmp_path: Path) -> None:
    completed = _cli(
        "--mode", "acquire-dera",
        "--request-plan", str(PLAN_PATH),
        "--replay-dir", str(ARCHIVE_FIXTURES),
        "--config", str(PROJECT_CONFIG),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-cross-a",
    )
    assert completed.returncode == 2 and "--config" in completed.stderr

    completed = _cli(
        "--mode", "acquire-dera",
        "--request-plan", str(PLAN_PATH),
        "--replay-dir", str(ARCHIVE_FIXTURES),
        "--frame-manifest", str(tmp_path / "m.json"),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-cross-b",
    )
    assert completed.returncode == 2 and "--frame-manifest" in completed.stderr

    completed = _cli(
        "--mode", "dera-validate",
        "--frame-manifest", str(tmp_path / "m.json"),
        "--dera-dir", str(ARCHIVE_FIXTURES),
        "--transport", "fixture",
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-cross-c",
    )
    assert completed.returncode == 2 and "--transport" in completed.stderr
