"""Publication policy for refusals and terminal provider failures (ADR-034).

Three exact artifact counts, asserted separately:

- **0** — every pre-run refusal. The run root is never created, so there is
  nothing to roll back; the guarantee is "never created", not "cleaned up".
- **2** — the zero-admissible-passage non-run route.
- **5** — a terminal provider failure: packet, prompt, client contract, an
  errored ``extraction_run``, and the provider-error record.

The whole terminal path is exercised offline: the fake permits the run, so the
orchestrator opens the root and writes three artifacts, and then the fake fails
in ``complete()``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.provider_adapter import ProviderRequest
from dynamic_ai_products.extraction.raw_artifacts import sha256_bytes
from dynamic_ai_products.extraction.run_extraction import (
    CLIENT_CONTRACT_REFERENCE,
    ENVELOPES_REFERENCE,
    EXTRACTION_RUN_REFERENCE,
    NON_RUN_REFERENCE,
    PACKET_REFERENCE,
    PREDICTION_MANIFEST_REFERENCE,
    PROMPT_REFERENCE,
    PROVIDER_ERROR_REFERENCE,
    RAW_REFERENCE,
    run_extraction_stage,
)
from dynamic_ai_products.providers.client_contract import build_client_contract
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.vertex_gemini import VertexGeminiProvider

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
ERROR_SCHEMA = json.loads(
    (SCHEMAS / "extraction_provider_error_record.schema.json").read_text()
)
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"
COVERAGE = {"reference": "coverage/source_family_coverage.json", "sha256": "d" * 64}
SOURCE_MANIFEST = {"reference": "snapshots/manifest.json", "sha256": "e" * 64}
DATES = {"sec-1": "2024-02-14", "sec-late": "2025-06-01"}
SENTINEL = "ya29.SENTINEL-TOKEN"
PROJECT = "my-research-project"


class _Recorder:
    """A fake that permits the run and observes what exists when it is called."""

    def __init__(self, *, fail: ProviderError | None = None, run_root: Path | None = None):
        self._fail = fail
        self._run_root = run_root
        self.root_at_permit: bool | None = None
        self.root_at_contract: bool | None = None
        self.files_at_complete: set[str] | None = None

    def assert_run_permitted(self) -> None:
        if self._run_root is not None:
            self.root_at_permit = self._run_root.exists()

    def client_contract(self) -> dict:
        if self._run_root is not None:
            self.root_at_contract = self._run_root.exists()
        return build_client_contract(vertex_project=PROJECT)

    def complete(self, request: ProviderRequest):
        if self._run_root is not None and self._run_root.exists():
            self.files_at_complete = {
                str(p.relative_to(self._run_root))
                for p in self._run_root.rglob("*")
                if p.is_file()
            }
        raise self._fail or ProviderError("vertex_unavailable", attempt_count=3)


class _Leaky:
    """Raises a bare exception whose text is full of credential material."""

    def assert_run_permitted(self) -> None:
        return None

    def client_contract(self) -> dict:
        return build_client_contract(vertex_project=PROJECT)

    def complete(self, request: ProviderRequest):
        raise RuntimeError(f"Authorization: Bearer {SENTINEL} body={SENTINEL}")


def _passage(passage_id: str, text: str, source_id: str = "sec-1"):
    return {
        "passage_id": passage_id,
        "source_id": source_id,
        "text": text,
        "start_offset": 0,
        "end_offset": len(text),
    }


def _run(tmp_path: Path, **overrides):
    kwargs = {
        "run_root": tmp_path / "run",
        "repo_root": REPO_ROOT,
        "stage": "product_extraction",
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [_passage("p-1", "the product ships an assistant")],
        "document_publication_dates": dict(DATES),
        "coverage_artifact": dict(COVERAGE),
        "source_snapshot_manifest": dict(SOURCE_MANIFEST),
        "code_commit": "d9c954aaa7dd344987aadffce76387f06c9fa52f",
        "run_created_at": "2026-07-29T00:00:00Z",
        "extraction_run_id": "ext-0001",
        "prediction_run_id": "pred-0001",
        "schema_root": str(SCHEMAS),
        "provider": _Recorder(),
    }
    kwargs.update(overrides)
    return run_extraction_stage(**kwargs)


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _count_mkdir(monkeypatch) -> list[int]:
    counter = [0]
    original = Path.mkdir

    def counting(self, *args, **kwargs):
        counter[0] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", counting)
    return counter


# --- 0 artifacts: every pre-run refusal ---------------------------------------


def test_the_vertex_provider_refuses_before_anything_is_created(tmp_path: Path, monkeypatch):
    counter = _count_mkdir(monkeypatch)
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=VertexGeminiProvider(vertex_project=PROJECT))
    assert excinfo.value.reason_code == "live_call_not_authorized"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


@pytest.mark.parametrize("pin", [None, {}, {"reference": "x", "sha256": "f" * 64}])
def test_a_caller_pin_creates_nothing(tmp_path: Path, monkeypatch, pin):
    counter = _count_mkdir(monkeypatch)
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider_client_contract=pin)
    assert excinfo.value.reason_code == "contract_pin_forbidden"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_an_invalid_client_contract_creates_nothing(tmp_path: Path, monkeypatch):
    class _BadContract(_Recorder):
        def client_contract(self):
            return {"contract": "wrong@0.1.0"}

    counter = _count_mkdir(monkeypatch)
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_BadContract())
    assert excinfo.value.reason_code == "client_contract_invalid"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_a_secret_bearing_contract_creates_nothing(tmp_path: Path, monkeypatch):
    class _SecretContract(_Recorder):
        def client_contract(self):
            contract = build_client_contract(vertex_project=PROJECT)
            contract["client_version"] = SENTINEL
            return contract

    counter = _count_mkdir(monkeypatch)
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_SecretContract())
    assert excinfo.value.reason_code == "credential_material_in_artifact"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_a_prompt_failure_creates_nothing(tmp_path: Path, monkeypatch):
    counter = _count_mkdir(monkeypatch)
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, repo_root=tmp_path / "no-prompts")
    assert excinfo.value.reason_code == "prompt_invalid"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_a_schema_pin_mismatch_creates_nothing_and_precedes_the_call(
    tmp_path: Path, monkeypatch
):
    """Before this ordering, the pin was verified after the call had been paid for."""
    drifted = tmp_path / "drifted-schemas"
    drifted.mkdir()
    (drifted / "product_observation.schema.json").write_bytes(b"{}\n")
    provider = _Recorder(run_root=tmp_path / "run")
    counter = _count_mkdir(monkeypatch)
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, schema_root=str(drifted), provider=provider)
    assert excinfo.value.reason_code == "schema_pin_mismatch"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0
    assert provider.files_at_complete is None  # complete() was never reached


def test_a_missing_provider_creates_nothing(tmp_path: Path, monkeypatch):
    counter = _count_mkdir(monkeypatch)
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=None)
    assert excinfo.value.reason_code == "provider_required"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


# --- ordering invariants -------------------------------------------------------


def test_the_run_root_does_not_exist_during_the_pre_run_gate(tmp_path: Path):
    provider = _Recorder(run_root=tmp_path / "run")
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=provider)
    assert provider.root_at_permit is False
    assert provider.root_at_contract is False


def test_three_artifacts_already_exist_when_complete_is_called(tmp_path: Path):
    provider = _Recorder(run_root=tmp_path / "run")
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=provider)
    assert provider.files_at_complete == {
        PACKET_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
    }


# --- 5 artifacts: terminal provider failure -----------------------------------


def test_a_terminal_failure_publishes_exactly_five_artifacts(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path)
    assert excinfo.value.reason_code == "vertex_unavailable"
    root = tmp_path / "run"
    assert _files(root) == {
        PACKET_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        EXTRACTION_RUN_REFERENCE,
        PROVIDER_ERROR_REFERENCE,
    }


def test_no_prediction_evidence_is_produced_on_a_terminal_failure(tmp_path: Path):
    with pytest.raises(ExtractionError):
        _run(tmp_path)
    published = _files(tmp_path / "run")
    for absent in (RAW_REFERENCE, ENVELOPES_REFERENCE, PREDICTION_MANIFEST_REFERENCE):
        assert absent not in published


def test_the_extraction_run_is_errored_and_counts_the_attempts(tmp_path: Path):
    with pytest.raises(ExtractionError):
        _run(tmp_path)
    record = json.loads((tmp_path / "run" / EXTRACTION_RUN_REFERENCE).read_text())
    assert record["status"] == "errored"
    assert record["error_count"] == 3
    assert record["fallbacks"] == []
    # The released contract is not widened to hold a reason.
    assert "error_reason" not in record
    assert len(record) == 15


def test_the_error_record_pins_all_four_artifacts_by_reread_digest(tmp_path: Path):
    with pytest.raises(ExtractionError):
        _run(tmp_path)
    root = tmp_path / "run"
    record = json.loads((root / PROVIDER_ERROR_REFERENCE).read_text())
    pairs = [
        ("input_packet", PACKET_REFERENCE),
        ("resolved_prompt", PROMPT_REFERENCE),
        ("provider_client_contract", CLIENT_CONTRACT_REFERENCE),
        ("extraction_run", EXTRACTION_RUN_REFERENCE),
    ]
    for prefix, reference in pairs:
        assert record[f"{prefix}_reference"] == reference
        assert record[f"{prefix}_sha256"] == sha256_bytes((root / reference).read_bytes())


def test_the_error_record_conforms_to_its_released_schema(tmp_path: Path):
    with pytest.raises(ExtractionError):
        _run(tmp_path)
    record = json.loads((tmp_path / "run" / PROVIDER_ERROR_REFERENCE).read_text())
    Draft202012Validator(ERROR_SCHEMA).validate(record)
    assert record["provider_called"] is True
    assert record["harness_run"] is False


def test_attempt_count_equals_the_run_error_count(tmp_path: Path):
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=_Recorder(fail=ProviderError("adc_expired", attempt_count=2)))
    root = tmp_path / "run"
    run_record = json.loads((root / EXTRACTION_RUN_REFERENCE).read_text())
    error_record = json.loads((root / PROVIDER_ERROR_REFERENCE).read_text())
    assert error_record["attempt_count"] == run_record["error_count"] == 2
    assert error_record["reason_code"] == "adc_expired"


def test_an_unclassifiable_failure_does_not_widen_the_released_enum(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_Leaky())
    assert excinfo.value.reason_code == "provider_response_unusable"
    record = json.loads((tmp_path / "run" / PROVIDER_ERROR_REFERENCE).read_text())
    Draft202012Validator(ERROR_SCHEMA).validate(record)


def test_no_upstream_text_reaches_any_artifact_or_message(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_Leaky())
    assert SENTINEL not in str(excinfo.value)
    assert "Bearer" not in str(excinfo.value)
    root = tmp_path / "run"
    for reference in _files(root):
        payload = (root / reference).read_bytes()
        assert SENTINEL.encode() not in payload
        assert b"Bearer" not in payload


def test_the_pre_run_refusal_never_writes_a_provider_error_record(tmp_path: Path):
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=VertexGeminiProvider(vertex_project=PROJECT))
    assert not (tmp_path / "run").exists()
    # Assert against the enum itself: the schema comment names the code on purpose.
    assert "live_call_not_authorized" not in ERROR_SCHEMA["properties"]["reason_code"]["enum"]


# --- 2 artifacts: the non-run route -------------------------------------------


def test_the_non_run_route_still_publishes_exactly_two_artifacts(tmp_path: Path):
    outcome = _run(
        tmp_path,
        passages=[_passage("p-1", "late", source_id="sec-late")],
        provider=None,
    )
    assert outcome.verdict == "no_run"
    assert _files(outcome.run_root) == {PACKET_REFERENCE, NON_RUN_REFERENCE}
