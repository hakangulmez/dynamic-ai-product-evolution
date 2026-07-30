"""Publication policy for refusals and terminal provider failures (ADR-034, ADR-036).

Three exact artifact counts, asserted separately:

- **0** — every pre-run refusal. The run root is never created, so there is
  nothing to roll back; the guarantee is "never created", not "cleaned up".
- **2** — the zero-admissible-passage non-run route.
- **7** — a terminal provider failure. **Five input artifacts already exist when
  ``complete()`` is entered** — packet, the rendered provider contents, prompt,
  client contract, and the live-call authorization — and the terminal route then
  adds an errored ``extraction_run`` plus the provider-error record.

The whole terminal path is exercised offline: the fake permits the run, so the
orchestrator opens the root and writes those five inputs, and then the fake fails
in ``complete()``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.provider_adapter import ProviderRequest
from dynamic_ai_products.extraction.manifests import (
    STAGE_OUTPUT_SCHEMA_SHA256 as _STAGE_OUTPUT_SCHEMA_SHA256,
    validate_provider_client_contract,
)
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.run_extraction import (
    AUTHORIZATION_REFERENCE,
    CLIENT_CONTRACT_REFERENCE,
    CONTENTS_REFERENCE,
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
        self.seen_digest: str | None = None
        self.root_at_permit: bool | None = None
        self.root_at_contract: bool | None = None
        self.files_at_complete: set[str] | None = None

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        self.seen_digest = authorization_sha256
        if self._run_root is not None:
            self.root_at_permit = self._run_root.exists()


    def revoke_run_permission(self) -> None:
        self.revoked = getattr(self, 'revoked', 0) + 1
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

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        return None


    def revoke_run_permission(self) -> None:
        self.revoked = getattr(self, 'revoked', 0) + 1
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


def write_company_identity(root: Path, **overrides) -> dict[str, str]:
    """Persist an admission artifact and return its pin (ADR-036, E-R).

    Mirrors the approved Pilot Universe Packet's identity fields. The legal name
    is only ever *read* from here; no test may pass one to the builder.
    """
    admission = {
        "company_id": COMPANY,
        "cik": COMPANY[3:].lstrip("0") or "0",
        "legal_name": "HUBSPOT INC",
        "observation_cutoff_date": CUTOFF,
    }
    unknown = sorted(set(overrides) - set(admission))
    assert not unknown, f"unknown admission override(s): {unknown}"
    admission.update(overrides)
    root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(admission, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (root / "pilot_universe_packet.json").write_bytes(payload)
    return {
        "reference": "pilot_universe_packet.json",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _run(tmp_path: Path, **overrides):
    governance_root = tmp_path / "governance-root"
    kwargs = {
        "run_root": tmp_path / "run",
        "governance_artifact_root": governance_root,
        "company_identity_root": tmp_path / "identity",
        "company_identity_pin": write_company_identity(tmp_path / "identity"),
        "live_call_authorization_pin": write_governance_chain(governance_root),
        "budget_meter": FakeMeter(),
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


def _count_mkdir(monkeypatch, run_root: Path) -> list[int]:
    """Count only mkdirs at or under the run root.

    The invariant is "the run root is never created", not "no directory
    anywhere is created" — the governance fixture legitimately creates its own
    root, and counting that would measure the wrong thing.
    """
    counter = [0]
    original = Path.mkdir
    prefix = str(run_root)

    def counting(self, *args, **kwargs):
        if str(self) == prefix or str(self).startswith(prefix + "/"):
            counter[0] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", counting)
    return counter


# --- 0 artifacts: every pre-run refusal ---------------------------------------


def test_the_vertex_provider_refuses_before_anything_is_created(tmp_path: Path, monkeypatch):
    """Default-deny: no expected digest was supplied, so it refuses."""
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=VertexGeminiProvider(vertex_project=PROJECT))
    assert excinfo.value.reason_code == "live_call_not_authorized"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


@pytest.mark.parametrize("pin", [None, {}, {"reference": "x", "sha256": "f" * 64}])
def test_a_caller_pin_creates_nothing(tmp_path: Path, monkeypatch, pin):
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider_client_contract=pin)
    assert excinfo.value.reason_code == "contract_pin_forbidden"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_an_invalid_client_contract_creates_nothing(tmp_path: Path, monkeypatch):
    class _BadContract(_Recorder):
        def client_contract(self):
            return {"contract": "wrong@0.1.0"}

    counter = _count_mkdir(monkeypatch, tmp_path / "run")
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

    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_SecretContract())
    assert excinfo.value.reason_code == "credential_material_in_artifact"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_a_prompt_failure_creates_nothing(tmp_path: Path, monkeypatch):
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
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
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, schema_root=str(drifted), provider=provider)
    assert excinfo.value.reason_code == "schema_pin_mismatch"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0
    assert provider.files_at_complete is None  # complete() was never reached


def test_a_missing_provider_creates_nothing(tmp_path: Path, monkeypatch):
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
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


def test_five_artifacts_already_exist_when_complete_is_called(tmp_path: Path):
    provider = _Recorder(run_root=tmp_path / "run")
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=provider)
    assert provider.files_at_complete == {
        PACKET_REFERENCE,
        CONTENTS_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        AUTHORIZATION_REFERENCE,
    }


# --- 7 artifacts: terminal provider failure -----------------------------------


def test_a_terminal_failure_publishes_exactly_seven_artifacts(tmp_path: Path):
    """Seven: E-L's six plus E-R's rendered provider contents."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path)
    assert excinfo.value.reason_code == "vertex_unavailable"
    root = tmp_path / "run"
    assert _files(root) == {
        PACKET_REFERENCE,
        CONTENTS_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        AUTHORIZATION_REFERENCE,
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


# --- governance chain fixture (ADR-035) --------------------------------------
#
# Built locally in each test module rather than in a shared helper file: the E-L
# increment is scope-locked to a fixed path set, and a new helper module is not
# in it. The duplication is deliberate and small.

GOV_AUTH_REFERENCE = "governance/live_call_authorization.json"
GOV_ENABLEMENT_REFERENCE = "governance/adapter_enablement_record.json"
GOV_QUALIFICATION_REFERENCE = "governance/adapter_qualification_record.json"
STAGE_OUTPUT_SHA = _STAGE_OUTPUT_SCHEMA_SHA256["product_extraction"]
METER_IDENTITY = "e-m-reference-meter"
METER_VERSION = "0.1.0"
ENDPOINT_ALLOWLIST = ["https://us-central1-aiplatform.googleapis.com/v1/projects"]


class FakeMeter:
    """Conforming offline meter. It counts nothing; it only records and refuses.

    E-M supplies the real tokenizer, pricing table, and monotonic clock behind
    this same seam. This stand-in exists so the authorized path is testable
    without either, and it is never used in E-B.
    """

    def __init__(self, *, refuse: str | None = None, identity=METER_IDENTITY,
                 version=METER_VERSION, run_root=None):
        self._refuse = refuse
        self._identity = identity
        self._version = version
        self._run_root = run_root
        self.seen_request = None
        self.seen_max_output_tokens = None
        self.root_existed_at_call = None

    def meter_identity(self):
        return {"meter_identity": self._identity, "meter_version": self._version}

    def assert_within_budget(self, *, request, max_output_tokens, budget):
        self.seen_request = request
        self.seen_max_output_tokens = max_output_tokens
        if self._run_root is not None:
            self.root_existed_at_call = self._run_root.exists()
        if self._refuse:
            raise _MeterRefusal(self._refuse)


class _MeterRefusal(Exception):
    def __init__(self, reason_code):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _client_contract_digest(project="my-research-project"):
    contract = validate_provider_client_contract(
        build_client_contract(vertex_project=project)
    )
    return sha256_bytes(canonical_json_bytes(contract))


def write_governance_chain(root: Path, **overrides):
    """Persist the three-ring chain and return the authorization pin.

    Unknown override keys raise: silently ignoring one would let a test think it
    had weakened a record when it had not, and pass for the wrong reason.
    """
    unknown = sorted(set(overrides) - {"qualification", "enablement", "authorization"})
    if unknown:
        raise AssertionError(f"unknown governance overrides: {unknown}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "governance").mkdir(parents=True, exist_ok=True)

    qualification = {
        "contract": "adapter_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "qual-0001",
        "adapter_identity": "dynamic_ai_products.providers.vertex_gemini",
        "adapter_version": "0.1.0",
        "adapter_family": "model_execution",
        # Qualified under the contract this run actually executes, and against
        # the released stage-output schema the run validates against.
        "execution_contract_id": "extraction_provider_client_contract@0.1.0",
        "execution_contract_sha256": _client_contract_digest(),
        "stage_output_contract_id": "product_observation@0.1.0",
        "stage_output_contract_sha256": STAGE_OUTPUT_SHA,
        "qualification_scope": "live_dev",
        "qualification_status": "qualified",
        "qualified_at": "2026-07-01T00:00:00Z",
    }
    qualification.update(overrides.pop("qualification", {}))
    qual_bytes = canonical_json_bytes(qualification)
    (root / GOV_QUALIFICATION_REFERENCE).write_bytes(qual_bytes)

    enablement = {
        "contract": "adapter_enablement_record@0.1.0",
        "schema_version": "0.1.0",
        "enablement_id": "enab-0001",
        "adapter_qualification_record_reference": GOV_QUALIFICATION_REFERENCE,
        "adapter_qualification_record_sha256": sha256_bytes(qual_bytes),
        "prompt_qualification_reference": "governance/prompt_qualification.json",
        "prompt_qualification_sha256": "3" * 64,
        "stage": "product_extraction",
        "stage_output_contract_id": "product_observation@0.1.0",
        "stage_output_contract_sha256": STAGE_OUTPUT_SHA,
        "routing_contract_id": "vertex_gemini_route@0.1.0",
        "routing_contract_sha256": "4" * 64,
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "endpoint_allowlist": list(ENDPOINT_ALLOWLIST),
        "enablement_status": "enabled_live_dev",
        "approver": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
    }
    enablement.update(overrides.pop("enablement", {}))
    enab_bytes = canonical_json_bytes(enablement)
    (root / GOV_ENABLEMENT_REFERENCE).write_bytes(enab_bytes)

    authorization = {
        "contract": "live_call_authorization@0.1.0",
        "schema_version": "0.1.0",
        "authorization_id": "auth-0001",
        "authorized_by": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "adapter_enablement_record_reference": GOV_ENABLEMENT_REFERENCE,
        "adapter_enablement_record_sha256": sha256_bytes(enab_bytes),
        "provider_client_contract_reference": CLIENT_CONTRACT_REFERENCE,
        "provider_client_contract_sha256": _client_contract_digest(),
        "budget_meter_identity": METER_IDENTITY,
        "budget_meter_version": METER_VERSION,
        "stage": "product_extraction",
        "company_id": "CIK0001404655",
        "observation_cutoff_date": "2024-12-31",
        "corpus_scope": "sec_only_partial",
        "budget_max_records": 1,
        "budget_max_requests": 3,
        "budget_max_input_tokens": 100000,
        "budget_max_output_tokens": 8192,
        "budget_max_estimated_cost_micros": 500000,
        "budget_max_wall_clock_seconds": 903,
        "budget_policy_version": "budget_policy_v1",
        "retry_policy_version": "extraction_provider_retry_policy_v1",
        "rate_limit_policy_version": "extraction_provider_rate_limit_policy_v1",
        "endpoint_allowlist": list(ENDPOINT_ALLOWLIST),
        "circuit_breaker_max_consecutive_failures": 1,
        "provider_called": True,
        "harness_run": False,
    }
    authorization.update(overrides.pop("authorization", {}))
    auth_bytes = canonical_json_bytes(authorization)
    (root / GOV_AUTH_REFERENCE).write_bytes(auth_bytes)
    return {"reference": GOV_AUTH_REFERENCE, "sha256": sha256_bytes(auth_bytes)}


# --- terminal reconciliation of the rendered contents (ADR-036, E-R) -----------


def _terminal_root(tmp_path: Path) -> Path:
    """Drive a terminal provider failure and return the run root."""
    with pytest.raises(ExtractionError):
        _run(tmp_path)
    return tmp_path / "run"


def test_the_terminal_rendered_contents_reconstruct_deterministically(tmp_path: Path):
    """No prediction manifest exists on this route, so binding is by re-derivation.

    The packet and the resolved prompt are both persisted; re-rendering them with
    the recorded renderer must reproduce the persisted document byte-for-byte.
    That is what makes the terminal chain checkable without a manifest root.
    """
    from dynamic_ai_products.extraction.contents_renderer import (
        render_provider_contents,
    )

    root = _terminal_root(tmp_path)
    packet = json.loads((root / PACKET_REFERENCE).read_text(encoding="utf-8"))
    prompt_text = (root / PROMPT_REFERENCE).read_text(encoding="utf-8")
    persisted = (root / CONTENTS_REFERENCE).read_bytes()

    reconstructed = render_provider_contents(
        stage=packet["stage"], prompt_text=prompt_text, packet=packet
    )
    assert reconstructed.encode("utf-8") == persisted
    assert sha256_bytes(reconstructed.encode("utf-8")) == sha256_bytes(persisted)


def test_the_terminal_route_persists_the_rendered_contents_at_all(tmp_path: Path):
    root = _terminal_root(tmp_path)
    assert (root / CONTENTS_REFERENCE).is_file()
    assert (root / CONTENTS_REFERENCE).read_bytes()


def test_the_terminal_error_record_pins_what_reconstruction_needs(tmp_path: Path):
    """packet, prompt, client contract, extraction run and code commit."""
    root = _terminal_root(tmp_path)
    record = json.loads((root / PROVIDER_ERROR_REFERENCE).read_text(encoding="utf-8"))

    pins = {
        record["input_packet_reference"]: record["input_packet_sha256"],
        record["resolved_prompt_reference"]: record["resolved_prompt_sha256"],
        record["provider_client_contract_reference"]: record[
            "provider_client_contract_sha256"
        ],
        record["extraction_run_reference"]: record["extraction_run_sha256"],
    }
    assert PACKET_REFERENCE in pins
    assert PROMPT_REFERENCE in pins
    assert CLIENT_CONTRACT_REFERENCE in pins
    assert EXTRACTION_RUN_REFERENCE in pins
    # Every pin resolves to bytes on disk with the recorded digest.
    for reference, digest in pins.items():
        assert sha256_bytes((root / reference).read_bytes()) == digest
    # The code commit is recorded, so the renderer version is reconstructible.
    assert record["code_commit"]
    assert record["provider_called"] is True


def test_the_terminal_extraction_run_pins_the_resolved_prompt_hash(tmp_path: Path):
    """What this actually proves: the run's prompt_hash equals the persisted prompt.

    That is one input the deterministic re-render needs. It is **not** a
    renderer-version field: ``extraction_provider_error_record@0.1.0`` and
    ``extraction_run@0.1.0`` are released and carry none, and neither is widened
    to preserve a more flattering test name. The renderer version travels in the
    envelope's open ``prompt_model_metadata`` on the success route only.
    """
    root = _terminal_root(tmp_path)
    run_record = json.loads((root / EXTRACTION_RUN_REFERENCE).read_text(encoding="utf-8"))
    prompt_bytes = (root / PROMPT_REFERENCE).read_bytes()
    assert run_record["prompt_hash"] == sha256_bytes(prompt_bytes)


def test_a_tampered_terminal_packet_breaks_the_reconciliation(tmp_path: Path):
    """The reconciliation has teeth: a changed packet no longer reproduces."""
    from dynamic_ai_products.extraction.contents_renderer import (
        render_provider_contents,
    )

    root = _terminal_root(tmp_path)
    packet = json.loads((root / PACKET_REFERENCE).read_text(encoding="utf-8"))
    prompt_text = (root / PROMPT_REFERENCE).read_text(encoding="utf-8")
    persisted = (root / CONTENTS_REFERENCE).read_bytes()

    packet["legal_name"] = "SOMEONE ELSE INC"
    tampered = render_provider_contents(
        stage=packet["stage"], prompt_text=prompt_text, packet=packet
    )
    assert tampered.encode("utf-8") != persisted
