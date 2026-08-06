"""Publication, permit lifecycle, and terminal chains on the v2 route.

Migrated from ``test_live_run_publication.py``, ``test_provider_error_publication.py``
and ``test_run_extraction.py`` by ADR-045 (G2b), which retired the v1 provider
route. Three v1 invariants could not survive unchanged and are asserted in their
v2 form, each with the reason stated at the test:

* the success route publishes eleven artifacts rather than nine, because the
  two-operation route additionally persists the count attempt, the generate
  attempt and the execution outcome;
* a terminal provider failure republishes as the classified terminal reason
  rather than the raw provider code, and always carries an execution outcome;
* the caller-supplied client-contract pin channel does not exist on v2 at all,
  so the v1 ``contract_pin_forbidden`` refusal has no counterpart and the
  *absence of the parameter* is what is asserted.

Nothing here touches a network, an SDK, or ADC. The one place a real connector is
constructed, it is constructed without a client factory and refuses at the
handshake, so no factory, credential or socket is ever reached.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.contents_renderer import render_provider_contents
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.execution_outcome import (
    COUNT_RAW_REFERENCE,
    EXECUTION_OUTCOME_REFERENCE,
    RAW_PREDICTION_REFERENCE,
    generate_attempt_reference,
)
from dynamic_ai_products.extraction.routing_contract import (
    ROUTING_CONTRACT_ID,
    derive_routing_contract,
)
from dynamic_ai_products.extraction.manifests import (
    STAGE_OUTPUT_SCHEMA_SHA256,
    STAGE_OUTPUT_CONTRACT_ID,
    wall_clock_floor_for_cap,
)
from dynamic_ai_products.extraction.prompt_qualification import (
    DECLARED_NON_CLAIMS,
    GOVERNING_SPEC_REFERENCE,
)
from dynamic_ai_products.extraction.prompts import load_prompt
from dynamic_ai_products.extraction.provider_adapter import (
    BudgetAdmission,
    ProviderResponse,
)
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.run_extraction import (
    AUTHORIZATION_REFERENCE,
    CLIENT_CONTRACT_REFERENCE,
    CONTENTS_REFERENCE,
    ENVELOPES_REFERENCE,
    EXTRACTION_RUN_REFERENCE,
    PACKET_REFERENCE,
    PREDICTION_MANIFEST_REFERENCE,
    PROMPT_REFERENCE,
    PROVIDER_ERROR_REFERENCE,
    run_extraction_stage_v2,
)
from dynamic_ai_products.providers.client_contract_v2 import (
    build_client_contract_v2,
    build_operation_endpoints,
)
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.vertex_gemini_v2 import VertexGeminiProviderV2

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"
PROJECT = "my-research-project"
CODE_COMMIT = "be627003f3246b371c2b3ac13e813ef0bb112582"
RUN_CREATED_AT = "2026-07-29T00:00:00Z"
STAGE = "product_extraction"
STAGE_SHA = STAGE_OUTPUT_SCHEMA_SHA256[STAGE]
ROUTING_SHA = derive_routing_contract(
    client_contract=build_client_contract_v2(vertex_project=PROJECT)
)["routing_contract_sha256"]
METER_IDENTITY = "dynamic_ai_products.extraction.budget_session"
METER_VERSION = "0.1.0"
SOURCE_MANIFEST = {"reference": "snapshots/m.json", "sha256": "e" * 64}
COVERAGE = {"reference": "coverage/c.json", "sha256": "d" * 64}
SENTINEL = "ya29.LEAKED-LOOKING-VALUE"
CHANGE_REQUEST_REFERENCE = (
    "evals/change_requests/CR-0004-product-discovery-schema-v4-bootstrap-qualification.md"
)

GOV_AUTH = "governance/live_call_authorization.json"
GOV_ENABLEMENT = "governance/adapter_enablement_record.json"
GOV_QUALIFICATION = "governance/adapter_qualification_record.json"
GOV_PROMPT_QUALIFICATION = "governance/prompt_qualification_record.json"

COUNT_BODY = b'{"totalTokens": 1000}'
PREDICTION_BODY = (
    b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}],'
    b'"usageMetadata":{"promptTokenCount":1000,"candidatesTokenCount":12}}'
)
ERROR_SCHEMA = json.loads(
    (SCHEMAS / "extraction_provider_error_record.schema.json").read_text(encoding="utf-8")
)


def _contract():
    return build_client_contract_v2(vertex_project=PROJECT)


def _contract_digest():
    return sha256_bytes(canonical_json_bytes(_contract()))


def _endpoints():
    endpoints = build_operation_endpoints(vertex_project=PROJECT)
    return (endpoints["count_tokens"], endpoints["generate_content"])


def _repo_digest(reference: str) -> str:
    return sha256_bytes((REPO_ROOT / reference).read_bytes())


class _Refusal(Exception):
    def __init__(self, reason_code, attempt_count=1):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.attempt_count = attempt_count


class _Provider:
    """Two-operation fake with observable permit and filesystem state."""

    def __init__(self, *, generate_failure=None, count_failure=None, run_root=None) -> None:
        self.count_sends = 0
        self.generate_sends = 0
        self.permits = 0
        self.revoked = 0
        self.contracts = 0
        self.seen_digest = None
        self.seen_allowlist = None
        self.seen_enablement_allowlist = None
        self.requests: list = []
        self.files_at_generate = None
        self.root_at_permit = None
        self.root_at_contract = None
        self._generate_failure = generate_failure
        self._count_failure = count_failure
        self._run_root = run_root

    def assert_run_permitted(
        self,
        *,
        authorization_sha256=None,
        endpoint_allowlist=None,
        enablement_endpoint_allowlist=None,
    ) -> None:
        self.permits += 1
        self.seen_digest = authorization_sha256
        self.seen_allowlist = endpoint_allowlist
        self.seen_enablement_allowlist = enablement_endpoint_allowlist
        if self._run_root is not None:
            self.root_at_permit = self._run_root.exists()

    def revoke_run_permission(self) -> None:
        self.revoked += 1

    def client_contract(self) -> dict:
        self.contracts += 1
        if self._run_root is not None:
            self.root_at_contract = self._run_root.exists()
        return _contract()

    def count_tokens(self, request, *, sink):
        self.count_sends += 1
        self.requests.append(request)
        if self._count_failure is not None:
            raise self._count_failure
        record = sink(
            operation_label="count_tokens",
            attempt_ordinal=1,
            raw_bytes=COUNT_BODY,
            send_outcome="response_2xx",
            sdk_call_outcome="returned",
            provider_reason_code=None,
        )
        return record, 1000

    def complete_v8(self, request, *, admission, sink):
        admission.spend()
        if self._run_root is not None:
            self.files_at_generate = _files(self._run_root)
        self.generate_sends += 1
        if self._generate_failure is not None:
            raise self._generate_failure
        record = sink(
            operation_label="generate_content",
            attempt_ordinal=1,
            raw_bytes=PREDICTION_BODY,
            send_outcome="response_2xx",
            sdk_call_outcome="returned",
            provider_reason_code=None,
        )
        response = ProviderResponse(
            raw_bytes=b"",
            model_provider="google_vertex_ai",
            model_name="gemini-2.5-flash",
            model_parameters=dict(_contract()["model_parameters"]),
            prompt_model_metadata={
                "model_name": "gemini-2.5-flash",
                "prompt_sha256": request.prompt_sha256,
                "api_version": "v1",
                "raw_capture_representation": "post_content_encoding_entity_body",
            },
        )
        return response, (record,)


class _Session:
    def __init__(self, cap: int = 3) -> None:
        self.cap = cap
        self.calls: list[dict] = []

    def meter_identity(self):
        return {"meter_identity": METER_IDENTITY, "meter_version": METER_VERSION}

    def admit(
        self, *, measured_input_tokens, reserved_cost_microdollars, provider_request_digest
    ):
        self.calls.append({"measured": measured_input_tokens})
        return BudgetAdmission(
            measured_input_tokens=measured_input_tokens,
            reserved_cost_microdollars=reserved_cost_microdollars,
            generate_attempt_cap=self.cap,
            provider_request_digest=provider_request_digest,
            session_nonce="nonce",
        )


def _files(root: Path) -> set[str]:
    if not root.exists():
        return set()
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


def _passage(text="the product ships an assistant"):
    return {
        "passage_id": "p-1",
        "source_id": "sec-1",
        "text": text,
        "start_offset": 0,
        "end_offset": len(text),
    }


def _write_identity(root: Path) -> dict[str, str]:
    root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "company_id": COMPANY,
            "cik": COMPANY[3:].lstrip("0"),
            "legal_name": "HUBSPOT INC",
            "observation_cutoff_date": CUTOFF,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    (root / "pilot_universe_packet.json").write_bytes(payload)
    return {"reference": "pilot_universe_packet.json", "sha256": hashlib.sha256(payload).hexdigest()}


# ADR-059. The capability entry deliberately names the **retired** prompt: the
# case above uses it to prove that a chain minted for a superseded prompt cannot
# execute the one the registry now resolves.
_STAGE_PROMPT = {
    "product_extraction": "product_discovery_schema_v4",
    "capability_extraction": "capability_extraction",
    "task_extraction": "task_discovery_recall",
}


def _prompt_qualification(stage: str = STAGE) -> dict:
    """Stage-appropriate, because the ADR-044 gate binds the resolved prompt.

    A product-stage record cannot qualify a capability run: the gate compares the
    record's ``prompt_id`` and ``stage`` against what the route actually
    resolved, and refuses before the renderer is ever reached.
    """
    prompt = load_prompt(REPO_ROOT, _STAGE_PROMPT[stage])
    return {
        "contract": "prompt_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "promptqual-g2b-pub",
        "qualification_basis": "bootstrap_pre_evaluation",
        "qualification_scope": "qualified_for_development",
        "qualification_status": "bootstrap_authorized_live_dev",
        "prompt_lifecycle_state": "candidate",
        "supersedes_qualification_id": None,
        "prompt_id": _STAGE_PROMPT[stage],
        "prompt_registry_version": prompt["prompt_registry_version"],
        "prompt_reference": prompt["reference"],
        "prompt_artifact_sha256": prompt["prompt_hash"],
        "stage": stage,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[stage],
        "stage_output_contract_sha256": STAGE_OUTPUT_SCHEMA_SHA256[stage],
        "execution_contract_id": "extraction_provider_client_contract@0.3.0",
        "execution_contract_sha256": _contract_digest(),
        "routing_contract_id": ROUTING_CONTRACT_ID,
        "routing_contract_sha256": ROUTING_SHA,
        "governing_spec_reference": GOVERNING_SPEC_REFERENCE,
        "governing_spec_sha256": _repo_digest(GOVERNING_SPEC_REFERENCE),
        "change_request_reference": CHANGE_REQUEST_REFERENCE,
        "change_request_sha256": _repo_digest(CHANGE_REQUEST_REFERENCE),
        "declared_non_claims": list(DECLARED_NON_CLAIMS),
        "known_limitation_codes": ["single_pass_recall_only_not_consolidated"],
        "reviewer": "methodology-owner",
        "decided_at": "2026-07-28T00:00:00Z",
        "code_commit": CODE_COMMIT,
    }


def write_governance_chain(root: Path, *, stage: str = STAGE, **overrides):
    known = {"qualification", "enablement", "authorization"}
    unknown = sorted(set(overrides) - known)
    if unknown:
        raise AssertionError(f"unknown governance overrides: {unknown}")
    (root / "governance").mkdir(parents=True, exist_ok=True)
    allowlist = list(_endpoints())

    qualification = {
        "contract": "adapter_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "qual-g2b-pub",
        "adapter_identity": "dynamic_ai_products.providers.vertex_gemini_v2",
        "adapter_version": "0.2.0",
        "adapter_family": "model_execution",
        "execution_contract_id": "extraction_provider_client_contract@0.3.0",
        "execution_contract_sha256": _contract_digest(),
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[STAGE],
        "stage_output_contract_sha256": STAGE_SHA,
        "qualification_scope": "live_dev",
        "qualification_status": "qualified",
        "qualified_at": "2026-07-01T00:00:00Z",
    }
    qualification.update(overrides.pop("qualification", {}))
    qual_bytes = canonical_json_bytes(qualification)
    (root / GOV_QUALIFICATION).write_bytes(qual_bytes)

    pq_bytes = canonical_json_bytes(_prompt_qualification(stage))
    (root / GOV_PROMPT_QUALIFICATION).write_bytes(pq_bytes)

    enablement = {
        "contract": "adapter_enablement_record@0.1.0",
        "schema_version": "0.1.0",
        "enablement_id": "enab-g2b-pub",
        "adapter_qualification_record_reference": GOV_QUALIFICATION,
        "adapter_qualification_record_sha256": sha256_bytes(qual_bytes),
        "prompt_qualification_reference": GOV_PROMPT_QUALIFICATION,
        "prompt_qualification_sha256": sha256_bytes(pq_bytes),
        "stage": STAGE,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[STAGE],
        "stage_output_contract_sha256": STAGE_SHA,
        "routing_contract_id": ROUTING_CONTRACT_ID,
        "routing_contract_sha256": ROUTING_SHA,
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "endpoint_allowlist": list(allowlist),
        "enablement_status": "enabled_live_dev",
        "approver": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
    }
    enablement.update(overrides.pop("enablement", {}))
    enab_bytes = canonical_json_bytes(enablement)
    (root / GOV_ENABLEMENT).write_bytes(enab_bytes)

    authorization = {
        "contract": "live_call_authorization@0.2.0",
        "schema_version": "0.2.0",
        "authorization_id": "auth-g2b-pub",
        "authorized_by": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "adapter_enablement_record_reference": GOV_ENABLEMENT,
        "adapter_enablement_record_sha256": sha256_bytes(enab_bytes),
        "provider_client_contract_reference": CLIENT_CONTRACT_REFERENCE,
        "provider_client_contract_sha256": _contract_digest(),
        "budget_meter_identity": METER_IDENTITY,
        "budget_meter_version": METER_VERSION,
        "stage": STAGE,
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "corpus_scope": "sec_only_partial",
        "budget_max_records": 1,
        "budget_max_external_requests": 4,
        "budget_max_input_tokens": 100000,
        "budget_max_output_tokens": 8192,
        "budget_max_estimated_cost_micros": 500000,
        "budget_max_wall_clock_seconds": wall_clock_floor_for_cap(3),
        "budget_policy_version": "budget_policy_v1",
        "retry_policy_version": "extraction_provider_retry_policy_v1",
        "rate_limit_policy_version": "extraction_provider_rate_limit_policy_v1",
        "endpoint_allowlist": list(allowlist),
        "circuit_breaker_max_consecutive_failures": 1,
        "provider_called": True,
        "harness_run": False,
    }
    authorization.update(overrides.pop("authorization", {}))
    auth_bytes = canonical_json_bytes(authorization)
    (root / GOV_AUTH).write_bytes(auth_bytes)
    return {"reference": GOV_AUTH, "sha256": sha256_bytes(auth_bytes)}


def _evidence_binding():
    schema = json.loads(
        (SCHEMAS / "extraction_execution_outcome.schema.json").read_text(encoding="utf-8")
    )["properties"]["evidence_binding"]["properties"]
    return {name: schema[name]["const"] for name in schema}


_UNSET = object()


def _run(tmp_path: Path, **overrides):
    governance = overrides.pop("governance_artifact_root", _UNSET)
    pin = overrides.pop("live_call_authorization_pin", _UNSET)
    if governance is _UNSET or pin is _UNSET:
        default_root = tmp_path / "governance-root"
        default_pin = write_governance_chain(default_root)
        if governance is _UNSET:
            governance = default_root
        if pin is _UNSET:
            pin = default_pin
    kwargs = {
        "run_root": tmp_path / "run",
        "repo_root": REPO_ROOT,
        "stage": STAGE,
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [_passage()],
        "document_publication_dates": {"sec-1": "2024-02-14"},
        "coverage_artifact": dict(COVERAGE),
        "source_snapshot_manifest": dict(SOURCE_MANIFEST),
        "code_commit": CODE_COMMIT,
        "run_created_at": RUN_CREATED_AT,
        "extraction_run_id": "ext-g2b-1",
        "prediction_run_id": "pred-g2b-1",
        "evidence_binding": _evidence_binding(),
        "schema_root": str(SCHEMAS),
        "provider": _Provider(),
        "governance_artifact_root": governance,
        "company_identity_root": tmp_path / "identity",
        "company_identity_pin": _write_identity(tmp_path / "identity"),
        "live_call_authorization_pin": pin,
    }
    kwargs.update(overrides)
    return run_extraction_stage_v2(**kwargs)


def _refused(tmp_path: Path, expected: str, **kwargs):
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, **kwargs)
    assert excinfo.value.reason_code == expected
    return excinfo.value


def _count_mkdir(monkeypatch, run_root: Path) -> list[int]:
    counter = [0]
    original = Path.mkdir
    prefix = str(run_root)

    def counting(self, *args, **kwargs):
        if str(self) == prefix or str(self).startswith(prefix + "/"):
            counter[0] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", counting)
    return counter


def _terminal_root(tmp_path: Path) -> Path:
    """Drive the run to a terminal generation failure and return its run root."""
    _refused(
        tmp_path,
        "provider_call_failed",
        provider=_Provider(generate_failure=_Refusal("vertex_unavailable", 3)),
    )
    return tmp_path / "run"


# --- the success route publishes a complete, self-consistent chain -------------


def test_v2_every_reported_digest_matches_the_persisted_bytes(tmp_path: Path):
    outcome = _run(tmp_path)
    assert outcome.artifacts
    for reference, digest in outcome.artifacts.items():
        assert sha256_bytes((outcome.run_root / reference).read_bytes()) == digest


def test_v2_a_successful_run_publishes_eleven_artifacts(tmp_path: Path):
    """Nine on v1; eleven here, and the two extra are the point of the route.

    The count attempt body and the execution outcome are what make a
    two-operation run auditable, so they are named rather than counted only.
    """
    outcome = _run(tmp_path)
    assert outcome.verdict == "two_operation_run_complete"
    assert _files(outcome.run_root) == {
        PACKET_REFERENCE,
        CONTENTS_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        AUTHORIZATION_REFERENCE,
        EXTRACTION_RUN_REFERENCE,
        RAW_PREDICTION_REFERENCE,
        ENVELOPES_REFERENCE,
        PREDICTION_MANIFEST_REFERENCE,
        COUNT_RAW_REFERENCE,
        EXECUTION_OUTCOME_REFERENCE,
    }


def test_v2_the_persisted_authorization_conforms_to_its_successor_schema(tmp_path: Path):
    """The v2 route persists a ``@0.2.0`` authorization, so that is the schema."""
    outcome = _run(tmp_path)
    schema = json.loads((SCHEMAS / "live_call_authorization_v2.schema.json").read_text())
    payload = json.loads((outcome.run_root / AUTHORIZATION_REFERENCE).read_text())
    Draft202012Validator(schema).validate(payload)
    assert payload["contract"] == "live_call_authorization@0.2.0"


def test_v2_the_run_records_the_stage_output_schema_digest(tmp_path: Path):
    outcome = _run(tmp_path)
    record = json.loads((outcome.run_root / EXTRACTION_RUN_REFERENCE).read_text())
    assert record["schema_hash"] == sha256_bytes(
        (SCHEMAS / "product_observation.schema.json").read_bytes()
    )
    assert record["source_manifest_hash"] == SOURCE_MANIFEST["sha256"]
    assert record["spec_version"] == "SPEC-008"


def test_v2_the_provider_sees_the_packet_digest_and_the_prompt_digest(tmp_path: Path):
    provider = _Provider()
    outcome = _run(tmp_path, provider=provider)
    assert len(provider.requests) == 1
    request = provider.requests[0]
    assert request.stage == STAGE
    assert request.input_packet_sha256 == outcome.packet_sha256
    prompt_bytes = (outcome.run_root / PROMPT_REFERENCE).read_bytes()
    assert request.prompt_sha256 == sha256_bytes(prompt_bytes)
    contents_bytes = (outcome.run_root / CONTENTS_REFERENCE).read_bytes()
    assert request.rendered_contents.encode("utf-8") == contents_bytes
    assert request.rendered_contents_sha256 == sha256_bytes(contents_bytes)
    assert request.rendered_contents_sha256 != request.prompt_sha256
    assert not hasattr(request, "prompt_text")
    assert not hasattr(request, "payload")


def test_v2_five_artifacts_already_exist_when_generation_is_called(tmp_path: Path):
    """The prepared inputs are durable before anything is generated.

    The count attempt body is there too, which is what the v1 route could not
    have: the budget decided on a measured number, and its evidence survives.
    """
    provider = _Provider(run_root=tmp_path / "run")
    _run(tmp_path, provider=provider)
    assert provider.files_at_generate == {
        PACKET_REFERENCE,
        CONTENTS_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        AUTHORIZATION_REFERENCE,
        COUNT_RAW_REFERENCE,
    }


def test_v2_the_run_root_does_not_exist_during_the_pre_run_gate(tmp_path: Path):
    provider = _Provider(run_root=tmp_path / "run")
    _run(tmp_path, provider=provider)
    assert provider.root_at_permit is False
    assert provider.root_at_contract is False


# --- refusals before anything is created ---------------------------------------


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"provider": None}, "provider_required"),
        ({"provider": object()}, "provider_protocol_invalid"),
        ({"governance_artifact_root": None}, "governance_root_required"),
        ({"live_call_authorization_pin": None}, "governance_root_required"),
    ],
)
def test_v2_every_pre_authorization_refusal_creates_nothing(
    tmp_path: Path, monkeypatch, overrides, expected
):
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    _refused(tmp_path, expected, **overrides)
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_v2_there_is_no_caller_supplied_client_contract_pin_channel():
    """v1 refused this channel; v2 never opened it.

    The stronger form of ``contract_pin_forbidden`` is that the parameter does
    not exist, so no refusal is needed and none can be forgotten.
    """
    import inspect

    parameters = inspect.signature(run_extraction_stage_v2).parameters
    assert "provider_client_contract" not in parameters
    with pytest.raises(TypeError):
        run_extraction_stage_v2(provider_client_contract={"reference": "x"})


def test_v2_a_schema_pin_mismatch_precedes_every_send(tmp_path: Path, monkeypatch):
    drifted = tmp_path / "drifted-schemas"
    drifted.mkdir()
    (drifted / "product_observation.schema.json").write_bytes(b"{}\n")
    provider = _Provider()
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    _refused(tmp_path, "schema_pin_mismatch", schema_root=str(drifted), provider=provider)
    assert (provider.count_sends, provider.generate_sends) == (0, 0)
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_v2_an_invalid_client_contract_creates_nothing(tmp_path: Path, monkeypatch):
    class _BadContract(_Provider):
        def client_contract(self):
            return {"contract": "wrong@0.1.0"}

    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    _refused(tmp_path, "client_contract_invalid", provider=_BadContract())
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_v2_a_secret_bearing_contract_creates_nothing(tmp_path: Path, monkeypatch):
    """Refused, and nothing leaks -- but by a different guard than on v1.

    v1 ran ``validate_provider_client_contract`` on the declared contract, whose
    first act is the credential scan, so a secret-bearing contract was refused as
    ``credential_material_in_artifact``. v2 cannot run that validator: it enforces
    the v1 property set exactly and a ``@0.2.0`` contract legitimately carries
    fourteen more fields. So on v2 the *digest* guard fires first -- the tampered
    contract no longer matches what the authorization pinned.

    The protective outcome is asserted rather than the vanished reason code:
    nothing is created and the sentinel never reaches the boundary.
    """

    class _SecretContract(_Provider):
        def client_contract(self):
            contract = _contract()
            contract["client_version"] = SENTINEL
            return contract

    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    error = _refused(
        tmp_path, "authorization_client_contract_mismatch", provider=_SecretContract()
    )
    assert SENTINEL not in str(error)
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_v2_the_client_contract_seam_carries_no_credential_scan(tmp_path: Path):
    """A recorded G2b gap, locked so that closing it must update ADR-045.

    The digest guard above only fires because the contract was *altered* after
    the authorization pinned it. It says nothing about a contract that carried
    credential material from the start and was pinned that way: v1 would still
    have refused that through the scan, and v2 has no scan on this seam at all.

    This is asserted as measured behaviour, not endorsed. If a later increment
    adds the scan to ``_client_contract_of_v2``, this test fails and the decision
    record has to be revisited -- which is the intent.
    """
    from dynamic_ai_products.extraction import run_extraction

    secret_contract = _contract()
    secret_contract["client_version"] = SENTINEL
    digest = sha256_bytes(canonical_json_bytes(secret_contract))

    class _SecretContract(_Provider):
        def client_contract(self):
            return dict(secret_contract)

    governance_root = tmp_path / "governance-secret"
    pin = write_governance_chain(
        governance_root, authorization={"provider_client_contract_sha256": digest}
    )
    # It is not refused for carrying the sentinel; it proceeds until the adapter
    # qualification disagrees about which contract was qualified.
    error = _refused(
        tmp_path,
        "governance_record_not_effective",
        provider=_SecretContract(),
        governance_artifact_root=governance_root,
        live_call_authorization_pin=pin,
    )
    assert error.reason_code != "credential_material_in_artifact"
    assert "_scan_for_credential_material" not in run_extraction._client_contract_of_v2.__doc__


def test_v2_a_prompt_failure_creates_nothing(tmp_path: Path, monkeypatch):
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    _refused(tmp_path, "prompt_invalid", repo_root=tmp_path / "no-prompts")
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


@pytest.mark.parametrize("preexisting", ["directory", "symlink"])
def test_v2_an_existing_run_root_is_never_overwritten_and_leaves_no_permit(
    tmp_path: Path, preexisting
):
    """``_require_absent_run_root`` sits after the handshake, so the permit
    granted for this run must be released on the way out."""
    if preexisting == "directory":
        (tmp_path / "run").mkdir()
    else:
        target = tmp_path / "elsewhere"
        target.mkdir()
        (tmp_path / "run").symlink_to(target)
    provider = _Provider()
    _refused(tmp_path, "run_root_exists", provider=provider)
    assert (provider.count_sends, provider.generate_sends) == (0, 0)
    assert provider.permits == 1
    assert provider.revoked == 1


# --- the permit lifecycle -------------------------------------------------------


def test_v2_the_runner_hands_the_provider_the_verified_digest(tmp_path: Path):
    provider = _Provider()
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(governance_root)
    _run(
        tmp_path,
        provider=provider,
        governance_artifact_root=governance_root,
        live_call_authorization_pin=pin,
    )
    assert provider.seen_digest == pin["sha256"]


def test_v2_the_runner_hands_the_provider_both_authorized_allowlists(tmp_path: Path):
    provider = _Provider()
    _run(tmp_path, provider=provider)
    assert tuple(provider.seen_allowlist) == _endpoints()
    assert tuple(provider.seen_enablement_allowlist) == _endpoints()


@pytest.mark.parametrize(
    "connector_allowlist",
    [
        _endpoints() + ("https://us-central1-aiplatform.googleapis.com/v1",),
        ("https://europe-west4-aiplatform.googleapis.com/v1/projects",),
        (),
    ],
)
def test_v2_a_connector_configured_for_another_allowlist_is_refused(
    tmp_path: Path, monkeypatch, connector_allowlist
):
    """Correct digest and cap, wrong endpoint set. No factory is ever entered."""
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(governance_root)
    provider = VertexGeminiProviderV2(
        vertex_project=PROJECT,
        expected_authorization_sha256=pin["sha256"],
        max_provider_requests=3,
        endpoint_allowlist=connector_allowlist,
    )
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    _refused(
        tmp_path,
        "live_call_not_authorized",
        provider=provider,
        governance_artifact_root=governance_root,
        live_call_authorization_pin=pin,
    )
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_v2_an_equivalent_normalized_allowlist_activates_through_the_runner(tmp_path: Path):
    """Semantic equality: a differently written but identical set still activates.

    The v2 grammar is narrower than v1's. It collapses the implicit ``:443`` and
    lowercases the host, but -- unlike the released normalizer -- it *refuses* a
    trailing dot and a ``.`` path segment rather than tidying them away, so the
    v1 spelling of this case would now be rejected on its own merits. The
    equivalences actually admitted are the two asserted here.
    """
    governance_root = tmp_path / "governance-override"
    count, generate = _endpoints()
    pin = write_governance_chain(
        governance_root,
        authorization={
            "endpoint_allowlist": [
                count.replace("googleapis.com", "googleapis.com:443"),
                generate.replace("aiplatform", "AIPLATFORM"),
            ]
        },
    )
    provider = VertexGeminiProviderV2(
        vertex_project=PROJECT,
        expected_authorization_sha256=pin["sha256"],
        max_provider_requests=3,
        endpoint_allowlist=_endpoints(),
    )
    # The handshake is accepted; the call itself then refuses because no client
    # factory is injected and no test may reach a real SDK.
    with pytest.raises(ExtractionError) as excinfo:
        _run(
            tmp_path,
            provider=provider,
            governance_artifact_root=governance_root,
            live_call_authorization_pin=pin,
        )
    assert excinfo.value.reason_code != "live_call_not_authorized"
    # The run root exists, so the handshake really was accepted.
    assert (tmp_path / "run").is_dir()


def test_v2_the_vertex_connector_refuses_before_anything_is_created(
    tmp_path: Path, monkeypatch
):
    """Default-deny: no expected digest was supplied, so it refuses."""
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    _refused(
        tmp_path,
        "live_call_not_authorized",
        provider=VertexGeminiProviderV2(vertex_project=PROJECT),
    )
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


@pytest.mark.parametrize(
    "entries",
    [
        [],
        ["not-a-url"],
        ["http://us-central1-aiplatform.googleapis.com/v1/projects"],
        list(_endpoints()) + [_endpoints()[0]],
    ],
)
def test_v2_a_malformed_or_duplicate_authorization_allowlist_creates_nothing(
    tmp_path: Path, monkeypatch, entries
):
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(
        governance_root, authorization={"endpoint_allowlist": entries}
    )
    provider = VertexGeminiProviderV2(
        vertex_project=PROJECT,
        expected_authorization_sha256=pin["sha256"],
        max_provider_requests=3,
        endpoint_allowlist=_endpoints(),
    )
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    _refused(
        tmp_path,
        "live_call_not_authorized",
        provider=provider,
        governance_artifact_root=governance_root,
        live_call_authorization_pin=pin,
    )
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


@pytest.mark.parametrize(
    "chain,expected",
    [
        ({"authorization": {"provider_client_contract_sha256": "0" * 64}},
         "authorization_client_contract_mismatch"),
        ({"qualification": {"execution_contract_sha256": "9" * 64}},
         "governance_record_not_effective"),
    ],
)
def test_v2_a_post_handshake_refusal_leaves_no_permit(tmp_path: Path, chain, expected):
    """These refusals sit after the handshake, so the permit must be released."""
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(governance_root, **chain)
    provider = _Provider()
    _refused(
        tmp_path,
        expected,
        provider=provider,
        governance_artifact_root=governance_root,
        live_call_authorization_pin=pin,
    )
    assert provider.permits == 1
    assert provider.revoked == 1
    assert (provider.count_sends, provider.generate_sends) == (0, 0)


def test_v2_a_prompt_failure_after_the_handshake_leaves_no_permit(tmp_path: Path):
    provider = _Provider()
    _refused(tmp_path, "prompt_invalid", provider=provider, repo_root=tmp_path / "no-prompts")
    assert provider.permits == 1
    assert provider.revoked == 1


def test_v2_a_successful_run_finishes_with_no_reusable_permit(tmp_path: Path):
    provider = _Provider()
    outcome = _run(tmp_path, provider=provider)
    assert outcome.verdict == "two_operation_run_complete"
    assert provider.revoked == 1


def test_v2_a_terminal_provider_failure_finishes_with_no_reusable_permit(tmp_path: Path):
    provider = _Provider(generate_failure=_Refusal("vertex_unavailable", 3))
    _refused(tmp_path, "provider_call_failed", provider=provider)
    assert provider.revoked == 1


def test_v2_a_revocation_failure_never_masks_the_original_refusal(tmp_path: Path):
    class _BadRevoke(_Provider):
        def revoke_run_permission(self) -> None:
            raise RuntimeError("revocation exploded with secret-looking text")

    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_BadRevoke(), repo_root=tmp_path / "no-prompts")
    assert excinfo.value.reason_code == "prompt_invalid"
    assert "revocation exploded" not in str(excinfo.value)


def test_v2_a_revocation_failure_on_the_success_path_is_not_a_success(tmp_path: Path):
    """Nothing else was failing, so the revocation failure *is* the failure."""

    class _SucceedThenFailRevoke(_Provider):
        def revoke_run_permission(self) -> None:
            raise RuntimeError("revocation exploded with secret-looking text")

    provider = _SucceedThenFailRevoke()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider)
    assert excinfo.value.reason_code == "provider_refused"
    assert "revocation exploded" not in str(excinfo.value)
    assert (provider.count_sends, provider.generate_sends) == (1, 1)


# --- write-path integrity -------------------------------------------------------


@pytest.mark.parametrize("failing_reference", [PROMPT_REFERENCE, CLIENT_CONTRACT_REFERENCE])
def test_v2_an_artifact_write_failure_leaves_no_permit(
    tmp_path: Path, monkeypatch, failing_reference
):
    from dynamic_ai_products.extraction import run_extraction

    attempted: list[str] = []
    real_write = run_extraction.write_artifact

    def failing_write(root, reference, payload):
        attempted.append(reference)
        if reference == failing_reference:
            raise ExtractionError("simulated write failure", reason_code="write_error")
        return real_write(root, reference, payload)

    monkeypatch.setattr(run_extraction, "write_artifact", failing_write)
    provider = _Provider()
    error = _refused(tmp_path, "write_error", provider=provider)
    assert error.reason_code != "run_root_exists"
    assert attempted[0] == PACKET_REFERENCE
    assert failing_reference in attempted
    assert (tmp_path / "run").is_dir()
    assert (provider.count_sends, provider.generate_sends) == (0, 0)
    assert provider.revoked == 1


@pytest.mark.parametrize("corrupted_reference", [PACKET_REFERENCE, CLIENT_CONTRACT_REFERENCE])
def test_v2_a_returned_digest_mismatch_fails_closed(
    tmp_path: Path, monkeypatch, corrupted_reference
):
    """A writer that reports a digest other than the pinned one stops the run."""
    from dynamic_ai_products.extraction import run_extraction

    attempted: list[str] = []
    real_write = run_extraction.write_artifact

    def lying_write(root, reference, payload):
        attempted.append(reference)
        observed = real_write(root, reference, payload)
        return "0" * 64 if reference == corrupted_reference else observed

    monkeypatch.setattr(run_extraction, "write_artifact", lying_write)
    provider = _Provider()
    error = _refused(tmp_path, "write_error", provider=provider)
    assert corrupted_reference in attempted
    assert "0" * 64 not in str(error)
    assert (provider.count_sends, provider.generate_sends) == (0, 0)
    assert provider.revoked == 1


def test_v2_the_digest_guard_is_reached_only_after_the_write_happened(
    tmp_path: Path, monkeypatch
):
    """Ordering proof: the artifact exists on disk before the guard refuses.

    Under a stripped ``assert`` the file would not exist at all, so this
    distinguishes a real unconditional write from a comparison-only check.
    """
    from dynamic_ai_products.extraction import run_extraction

    real_write = run_extraction.write_artifact
    seen_on_disk: dict[str, bool] = {}

    def lying_write(root, reference, payload):
        observed = real_write(root, reference, payload)
        if reference == PACKET_REFERENCE:
            seen_on_disk[reference] = (Path(root) / reference).is_file()
            return "0" * 64
        return observed

    monkeypatch.setattr(run_extraction, "write_artifact", lying_write)
    _refused(tmp_path, "write_error")
    assert seen_on_disk[PACKET_REFERENCE] is True


# --- the terminal provider-error chain ------------------------------------------


def test_v2_a_terminal_generation_failure_publishes_exactly_nine_artifacts(tmp_path: Path):
    """v1 published exactly seven on this route; v2 publishes exactly nine.

    The two additions are the countTokens attempt body and the execution
    outcome. The set is asserted exactly, not by membership, so a silently added
    or dropped artifact fails here.
    """
    provider = _Provider(generate_failure=_Refusal("vertex_unavailable", 3))
    _refused(tmp_path, "provider_call_failed", provider=provider)
    assert _files(tmp_path / "run") == {
        PACKET_REFERENCE,
        CONTENTS_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        AUTHORIZATION_REFERENCE,
        EXTRACTION_RUN_REFERENCE,
        PROVIDER_ERROR_REFERENCE,
        COUNT_RAW_REFERENCE,
        EXECUTION_OUTCOME_REFERENCE,
    }


def test_v2_an_attempt_count_above_the_cap_stops_the_run_rather_than_being_clamped(
    tmp_path: Path,
):
    """The provider claimed more attempts than the budget authorized.

    v1 recorded this as a budget violation and clamped the count to the cap. v2
    does not clamp: the execution outcome is validated against its committed
    contract before it is written, and a claim of 99 attempts under a cap of 3
    cannot produce a valid record. The run therefore stops with
    ``execution_outcome_invalid`` -- a strictly stronger outcome than a clamp,
    because nothing plausible-but-wrong is published.
    """
    provider = _Provider(generate_failure=_Refusal("vertex_unavailable", 99))
    _refused(tmp_path, "execution_outcome_invalid", provider=provider)
    # No execution outcome is published, because none could be validated.
    assert EXECUTION_OUTCOME_REFERENCE not in _files(tmp_path / "run")
    assert provider.revoked == 1


def test_v2_the_extraction_run_is_errored_and_counts_the_attempts(tmp_path: Path):
    _refused(
        tmp_path,
        "provider_call_failed",
        provider=_Provider(generate_failure=_Refusal("vertex_unavailable", 3)),
    )
    record = json.loads((tmp_path / "run" / EXTRACTION_RUN_REFERENCE).read_text())
    assert record["status"] == "errored"
    assert record["error_count"] == 3
    assert record["fallbacks"] == []
    # The released contract is not widened to hold a reason.
    assert "error_reason" not in record
    assert len(record) == 15


def test_v2_attempt_count_equals_the_run_error_count(tmp_path: Path):
    _refused(
        tmp_path,
        "provider_call_failed",
        provider=_Provider(generate_failure=ProviderError("adc_expired", attempt_count=2)),
    )
    root = tmp_path / "run"
    run_record = json.loads((root / EXTRACTION_RUN_REFERENCE).read_text())
    error_record = json.loads((root / PROVIDER_ERROR_REFERENCE).read_text())
    assert error_record["attempt_count"] == run_record["error_count"] == 2
    assert error_record["reason_code"] == "adc_expired"


def test_v2_the_error_record_conforms_to_its_released_schema(tmp_path: Path):
    root = _terminal_root(tmp_path)
    record = json.loads((root / PROVIDER_ERROR_REFERENCE).read_text())
    Draft202012Validator(ERROR_SCHEMA).validate(record)
    assert record["provider_called"] is True
    assert record["harness_run"] is False


def test_v2_the_error_record_pins_all_four_artifacts_by_reread_digest(tmp_path: Path):
    root = _terminal_root(tmp_path)
    record = json.loads((root / PROVIDER_ERROR_REFERENCE).read_text())
    for prefix, reference in (
        ("input_packet", PACKET_REFERENCE),
        ("resolved_prompt", PROMPT_REFERENCE),
        ("provider_client_contract", CLIENT_CONTRACT_REFERENCE),
        ("extraction_run", EXTRACTION_RUN_REFERENCE),
    ):
        assert record[f"{prefix}_reference"] == reference
        assert record[f"{prefix}_sha256"] == sha256_bytes((root / reference).read_bytes())


def test_v2_the_terminal_error_record_pins_what_reconstruction_needs(tmp_path: Path):
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
    for reference in (
        PACKET_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        EXTRACTION_RUN_REFERENCE,
    ):
        assert reference in pins
    for reference, digest in pins.items():
        assert sha256_bytes((root / reference).read_bytes()) == digest
    assert record["code_commit"]
    assert record["provider_called"] is True


def test_v2_the_terminal_extraction_run_pins_the_resolved_prompt_hash(tmp_path: Path):
    root = _terminal_root(tmp_path)
    run_record = json.loads((root / EXTRACTION_RUN_REFERENCE).read_text(encoding="utf-8"))
    assert run_record["prompt_hash"] == sha256_bytes((root / PROMPT_REFERENCE).read_bytes())


def test_v2_an_unclassifiable_failure_does_not_widen_the_released_enum(tmp_path: Path):
    class _Leaky(_Provider):
        def complete_v8(self, request, *, admission, sink):
            admission.spend()
            self.generate_sends += 1
            raise RuntimeError("ya29.SECRET-LOOKING internal failure")

    error = _refused(tmp_path, "provider_call_failed", provider=_Leaky())
    assert "ya29." not in str(error)
    record = json.loads((tmp_path / "run" / PROVIDER_ERROR_REFERENCE).read_text())
    Draft202012Validator(ERROR_SCHEMA).validate(record)
    assert record["reason_code"] == "provider_response_unusable"


def test_v2_a_count_side_failure_never_generates(tmp_path: Path):
    provider = _Provider(count_failure=_Refusal("vertex_unavailable", 1))
    _refused(tmp_path, "provider_call_failed", provider=provider)
    assert provider.generate_sends == 0
    record = json.loads((tmp_path / "run" / EXECUTION_OUTCOME_REFERENCE).read_text())
    assert record["route_family"] == "count_provider_error"


# --- the terminal chain reconstructs without a manifest root --------------------


def test_v2_the_terminal_route_persists_the_rendered_contents_at_all(tmp_path: Path):
    root = _terminal_root(tmp_path)
    assert (root / CONTENTS_REFERENCE).is_file()
    assert (root / CONTENTS_REFERENCE).read_bytes()


def test_v2_the_terminal_rendered_contents_reconstruct_deterministically(tmp_path: Path):
    """No prediction manifest exists on this route, so binding is by re-derivation."""
    root = _terminal_root(tmp_path)
    packet = json.loads((root / PACKET_REFERENCE).read_text(encoding="utf-8"))
    prompt_text = (root / PROMPT_REFERENCE).read_text(encoding="utf-8")
    persisted = (root / CONTENTS_REFERENCE).read_bytes()
    reconstructed = render_provider_contents(
        stage=packet["stage"], prompt_text=prompt_text, packet=packet
    )
    assert reconstructed.encode("utf-8") == persisted
    assert sha256_bytes(reconstructed.encode("utf-8")) == sha256_bytes(persisted)


def test_v2_a_tampered_terminal_packet_breaks_the_reconciliation(tmp_path: Path):
    """The reconciliation has teeth: a changed packet no longer reproduces."""
    root = _terminal_root(tmp_path)
    packet = json.loads((root / PACKET_REFERENCE).read_text(encoding="utf-8"))
    prompt_text = (root / PROMPT_REFERENCE).read_text(encoding="utf-8")
    persisted = (root / CONTENTS_REFERENCE).read_bytes()
    packet["legal_name"] = "SOMEONE ELSE INC"
    tampered = render_provider_contents(
        stage=packet["stage"], prompt_text=prompt_text, packet=packet
    )
    assert tampered.encode("utf-8") != persisted


def test_v2_the_execution_outcome_is_the_classifier_root_on_every_route(tmp_path: Path):
    """Every post-mkdir terminal route publishes one, success or failure."""
    outcome = _run(tmp_path)
    assert EXECUTION_OUTCOME_REFERENCE in _files(outcome.run_root)

    other = tmp_path / "second"
    other.mkdir()
    _refused(
        other,
        "provider_call_failed",
        provider=_Provider(generate_failure=_Refusal("vertex_unavailable", 3)),
    )
    assert EXECUTION_OUTCOME_REFERENCE in _files(other / "run")


def test_v2_the_generate_attempt_body_is_persisted_under_its_own_reference(tmp_path: Path):
    outcome = _run(tmp_path)
    reference = generate_attempt_reference(1)
    assert (outcome.run_root / RAW_PREDICTION_REFERENCE).is_file()
    assert isinstance(reference, str) and reference


# --- Stage 06 and Stage 07 stay blocked until E-S (ADR-036, E-R) ----------------


def _write_parent_artifact(root: Path, reference: str, payload) -> dict:
    """Persist real bytes and return a real pin. No model_construct anywhere."""
    from dynamic_ai_products.extraction.raw_artifacts import write_artifact

    digest = write_artifact(root, reference, json.dumps(payload).encode("utf-8"))
    return {"reference": reference, "sha256": digest}


def _valid_parent_chain(root: Path) -> dict:
    """A complete, mutually consistent A/B chain persisted under one root.

    Built from real payloads through the ordinary ``write_artifact`` path, so the
    packet builder's normal hydration, hash verification and reconciliation all
    run for real. Nothing here is a malformed stand-in.
    """
    products = [
        _write_parent_artifact(
            root,
            f"observations/product/p{i}.json",
            {"product_observation_id": f"prod-{i}", "product_name": f"P{i}"},
        )
        for i in range(2)
    ]
    capabilities = [
        _write_parent_artifact(
            root,
            "observations/capability/c0.json",
            {"capability_observation_id": "cap-0", "capability": "C0"},
        )
    ]

    def members(role, pins):
        return sorted(
            ({"role": role, **pin} for pin in pins),
            key=lambda m: (m["role"], m["reference"]),
        )

    def decision_set(kind, pins, **extra):
        payload = {
            "contract": "extraction_validation_decision_set@0.1.0",
            "observation_kind": kind,
            "raw_artifact_sha256": "9" * 64,
            "candidate_collection_sha256": "8" * 64,
            "decisions": [
                {
                    "candidate_id": pin["sha256"][:32],
                    "decision": "accept",
                    "reason": "",
                    "accepted_artifact_reference": pin["reference"],
                    "accepted_artifact_sha256": pin["sha256"],
                }
                for pin in pins
            ],
        }
        payload.update(extra)
        return payload

    def publish_snapshot(reference, version, member_rows):
        payload = {
            "contract": "parent_observation_snapshot@0.1.0",
            "snapshot_version": version,
            "case_id": "case-1",
            "company_id": COMPANY,
            "observation_cutoff": CUTOFF,
            "members": member_rows,
        }
        pin = _write_parent_artifact(root, reference, payload)
        pin["snapshot_version"] = version
        return pin

    product_decisions = _write_parent_artifact(
        root, "decisions/product.json", decision_set("product", products)
    )
    snapshot_a = publish_snapshot(
        "snapshots/a.json", "a-1", members("product_parent", products)
    )
    capability_decisions = _write_parent_artifact(
        root,
        "decisions/capability.json",
        decision_set(
            "capability",
            capabilities,
            snapshot_a_reference=snapshot_a["reference"],
            snapshot_a_sha256=snapshot_a["sha256"],
        ),
    )
    snapshot_b = publish_snapshot(
        "snapshots/b.json",
        "b-1",
        sorted(
            members("product_parent", products) + members("capability_parent", capabilities),
            key=lambda m: (m["role"], m["reference"]),
        ),
    )
    return {
        "artifact_root": root,
        "snapshot_a_pin": snapshot_a,
        "snapshot_b_pin": snapshot_b,
        "product_decision_set_pin": product_decisions,
        "capability_decision_set_pin": capability_decisions,
    }


@pytest.mark.parametrize("stage", ["capability_extraction", "task_extraction"])
def test_v2_a_fully_valid_non_product_stage_still_refuses_before_the_provider(
    tmp_path: Path, stage
):
    """The E-R gate itself, reached end to end through the v2 runner.

    Every preflight succeeds: the parent chain is real and hash-verified, the
    governance chain and stage-output pins match the selected stage, the passage
    set is nonempty, and the company-identity pin is valid. The permit handshake
    therefore happens -- and the renderer is what refuses, because
    ``MATERIALIZATION_SUPPORTED_STAGES`` holds only the product stage until E-S.

    Which gate refuses has moved twice; *that* both stages refuse has not, and
    every assertion below the reason code is unchanged: the permit was reached,
    zero artifacts exist, neither send happened, and the permit was revoked.

    - ``task_extraction`` is still stopped by the renderer: it needs Snapshot B,
      which does not exist, so its stage is not materializable
      (``contents_placeholder_unbound``).
    - ``capability_extraction`` is now materializable (ADR-058) and has a
      schema-bound prompt (ADR-059), so neither renderer gate fires. It is
      stopped earlier instead, by P1-P4: ``_STAGE_PROMPT`` below deliberately
      still names the **retired** capability prompt, so this chain qualifies one
      prompt while the route resolves another
      (``prompt_qualification_mismatch``). That a governance chain minted for a
      retired prompt cannot execute its successor is the protection ADR-053
      built, exercised here end to end.
    """
    expected_code = (
        "prompt_qualification_mismatch"
        if stage == "capability_extraction"
        else "contents_placeholder_unbound"
    )
    chain = _valid_parent_chain(tmp_path / "parents")
    governance_root = tmp_path / "governance-stage"
    stage_sha = STAGE_OUTPUT_SCHEMA_SHA256[stage]
    stage_contract = STAGE_OUTPUT_CONTRACT_ID[stage]
    pin = write_governance_chain(
        governance_root,
        stage=stage,
        qualification={
            "stage_output_contract_id": stage_contract,
            "stage_output_contract_sha256": stage_sha,
        },
        enablement={
            "stage": stage,
            "stage_output_contract_id": stage_contract,
            "stage_output_contract_sha256": stage_sha,
        },
        authorization={"stage": stage},
    )
    provider = _Provider()
    parent_kwargs = {
        "artifact_root": chain["artifact_root"],
        "snapshot_a_pin": chain["snapshot_a_pin"],
        "product_decision_set_pin": chain["product_decision_set_pin"],
    }
    if stage == "task_extraction":
        parent_kwargs["snapshot_b_pin"] = chain["snapshot_b_pin"]
        parent_kwargs["capability_decision_set_pin"] = chain["capability_decision_set_pin"]

    with pytest.raises(ExtractionError) as excinfo:
        _run(
            tmp_path,
            stage=stage,
            provider=provider,
            governance_artifact_root=governance_root,
            live_call_authorization_pin=pin,
            **parent_kwargs,
        )
    assert excinfo.value.reason_code == expected_code
    # The handshake was reached, so packet and governance preflight both passed.
    assert provider.permits == 1
    assert provider.contracts >= 1
    # Zero artifacts, and no send of either kind.
    assert not (tmp_path / "run").exists()
    assert (provider.count_sends, provider.generate_sends) == (0, 0)
    assert provider.revoked == 1


@pytest.mark.parametrize("stage", ["capability_extraction", "task_extraction"])
def test_v2_a_non_product_stage_without_parent_pins_stops_in_the_packet_preflight(
    tmp_path: Path, stage
):
    """The packet refuses first, before the handshake, so no permit is granted."""
    provider = _Provider()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, stage=stage, provider=provider)
    assert excinfo.value.reason_code == "parent_context_missing"
    assert not (tmp_path / "run").exists()
    assert provider.permits == 0
    assert provider.revoked == 0
