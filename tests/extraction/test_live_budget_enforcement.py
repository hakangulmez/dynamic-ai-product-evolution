"""Budget enforcement, and the honest line between runner and meter (ADR-035).

Three limits are genuinely enforced pre-call by the runner: records, requests,
and declared output tokens. ``budget_max_wall_clock_seconds`` is only a
compatibility floor against the retry policy's theoretical ceiling.
``budget_max_input_tokens`` and ``budget_max_estimated_cost_micros`` are
verifiable only through the injected meter, and with no meter the run is refused
rather than run unmetered.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.manifests import (
    STAGE_OUTPUT_SCHEMA_SHA256 as _STAGE_OUTPUT_SCHEMA_SHA256,
    PROVIDER_MAX_ATTEMPTS_PIN,
    PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS,
    resolve_attempt_cap,
    validate_provider_client_contract,
)
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.run_extraction import (
    CLIENT_CONTRACT_REFERENCE,
    CONTENTS_REFERENCE,
    run_extraction_stage,
)
from dynamic_ai_products.providers.client_contract import build_client_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"
COVERAGE = {"reference": "coverage/source_family_coverage.json", "sha256": "d" * 64}
SOURCE_MANIFEST = {"reference": "snapshots/manifest.json", "sha256": "e" * 64}
DATES = {"sec-1": "2024-02-14"}
PROJECT = "my-research-project"


class _Provider:
    def __init__(self):
        self.calls = 0

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        pass


    def revoke_run_permission(self) -> None:
        self.revoked = getattr(self, 'revoked', 0) + 1
    def client_contract(self) -> dict:
        return build_client_contract(vertex_project=PROJECT)

    def complete(self, request):
        self.calls += 1
        raise _Refusal("vertex_unavailable", 1)


class _Refusal(Exception):
    def __init__(self, reason_code, attempt_count):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.attempt_count = attempt_count


def _passage(text="the product ships an assistant"):
    return {
        "passage_id": "p-1",
        "source_id": "sec-1",
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


def _run(tmp_path: Path, *, chain_overrides=None, **overrides):
    governance_root = tmp_path / "governance-root"
    pin = write_governance_chain(governance_root, **(chain_overrides or {}))
    kwargs = {
        "run_root": tmp_path / "run",
        "repo_root": REPO_ROOT,
        "stage": "product_extraction",
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [_passage()],
        "document_publication_dates": dict(DATES),
        "coverage_artifact": dict(COVERAGE),
        "source_snapshot_manifest": dict(SOURCE_MANIFEST),
        "code_commit": "be627003f3246b371c2b3ac13e813ef0bb112582",
        "run_created_at": "2026-07-29T00:00:00Z",
        "extraction_run_id": "ext-0001",
        "prediction_run_id": "pred-0001",
        "schema_root": str(SCHEMAS),
        "provider": _Provider(),
        "governance_artifact_root": governance_root,
        "company_identity_root": tmp_path / "identity",
        "company_identity_pin": write_company_identity(tmp_path / "identity"),
        "live_call_authorization_pin": pin,
        "budget_meter": FakeMeter(),
    }
    kwargs.update(overrides)
    return run_extraction_stage(**kwargs)


def _refused(tmp_path: Path, expected: str, **kwargs):
    provider = _Provider()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider, **kwargs)
    assert excinfo.value.reason_code == expected
    assert not (tmp_path / "run").exists()
    assert provider.calls == 0
    return excinfo.value


def _authorization(**overrides):
    base = {
        "budget_max_records": 1,
        "budget_max_requests": 3,
        "budget_max_input_tokens": 100000,
        "budget_max_output_tokens": 8192,
        "budget_max_estimated_cost_micros": 500000,
        "budget_max_wall_clock_seconds": 903,
        "circuit_breaker_max_consecutive_failures": 1,
    }
    base.update(overrides)
    return base


# --- the meter seam -----------------------------------------------------------


def test_no_meter_refuses_with_zero_artifacts_and_no_provider_call(tmp_path: Path):
    _refused(tmp_path, "budget_meter_unavailable", budget_meter=None)


@pytest.mark.parametrize("meter", [object(), 7, "meter", {}, lambda: None])
def test_a_non_conforming_meter_is_refused(tmp_path: Path, meter):
    _refused(tmp_path, "budget_meter_protocol_invalid", budget_meter=meter)


def test_a_conforming_fake_meter_lets_the_run_proceed(tmp_path: Path):
    """The 8-artifact success path is only testable through an injected fake."""
    provider = _Provider()
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=provider)
    assert provider.calls == 1


@pytest.mark.parametrize(
    "reason",
    [
        "budget_input_tokens_exceeded",
        "budget_estimated_cost_exceeded",
        "budget_wall_clock_exceeded",
    ],
)
def test_every_meter_refusal_leaves_zero_artifacts(tmp_path: Path, reason):
    _refused(tmp_path, reason, budget_meter=FakeMeter(refuse=reason))


def test_an_undeclared_meter_reason_collapses_rather_than_widening(tmp_path: Path):
    _refused(tmp_path, "budget_insufficient", budget_meter=FakeMeter(refuse="invented"))


# --- meter identity -----------------------------------------------------------


def test_a_meter_whose_identity_differs_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "budget_meter_identity_mismatch",
        budget_meter=FakeMeter(identity="some-other-meter"),
    )


def test_a_meter_whose_version_differs_is_refused(tmp_path: Path):
    _refused(
        tmp_path, "budget_meter_identity_mismatch", budget_meter=FakeMeter(version="9.9.9")
    )


def test_the_e_b_gate_needs_the_authorization_to_pin_a_real_meter(tmp_path: Path):
    """Identity equality is enforced. It is not, and is not claimed to be, a
    structural bar against an in-process implementation imitating the values."""
    _refused(
        tmp_path,
        "budget_meter_identity_mismatch",
        chain_overrides={"authorization": {"budget_meter_identity": "e-m-real-meter"}},
    )


# --- what the meter actually sees ---------------------------------------------


def test_the_meter_sees_the_exact_request_the_provider_receives(tmp_path: Path):
    class _Capturing(_Provider):
        def complete(self, request):
            self.calls += 1
            self.seen_request = request
            raise _Refusal("vertex_unavailable", 1)

    provider = _Capturing()
    meter = FakeMeter()
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=provider, budget_meter=meter)
    # The same object, not an equal copy.
    assert meter.seen_request is provider.seen_request
    # rendered_contents is the sole provider-input authority (ADR-036, E-R), so
    # metering it is metering exactly what is sent.
    assert (
        meter.seen_request.rendered_contents
        == provider.seen_request.rendered_contents
    )
    assert (
        meter.seen_request.rendered_contents_sha256
        == provider.seen_request.rendered_contents_sha256
    )


def test_the_meter_sees_the_declared_max_output_tokens(tmp_path: Path):
    meter = FakeMeter()
    with pytest.raises(ExtractionError):
        _run(tmp_path, budget_meter=meter)
    assert meter.seen_max_output_tokens == 8192


def test_the_meter_runs_before_the_run_root_exists(tmp_path: Path):
    meter = FakeMeter(run_root=tmp_path / "run")
    with pytest.raises(ExtractionError):
        _run(tmp_path, budget_meter=meter)
    assert meter.root_existed_at_call is False


def test_the_metered_packet_digest_is_the_persisted_one(tmp_path: Path):
    from dynamic_ai_products.extraction.run_extraction import PACKET_REFERENCE

    meter = FakeMeter()
    with pytest.raises(ExtractionError):
        _run(tmp_path, budget_meter=meter)
    persisted = (tmp_path / "run" / PACKET_REFERENCE).read_bytes()
    assert meter.seen_request.input_packet_sha256 == sha256_bytes(persisted)


def test_the_metered_prompt_digest_is_the_persisted_one(tmp_path: Path):
    from dynamic_ai_products.extraction.run_extraction import PROMPT_REFERENCE

    meter = FakeMeter()
    with pytest.raises(ExtractionError):
        _run(tmp_path, budget_meter=meter)
    persisted = (tmp_path / "run" / PROMPT_REFERENCE).read_bytes()
    assert meter.seen_request.prompt_sha256 == sha256_bytes(persisted)


def test_the_metered_contents_digest_is_the_persisted_one(tmp_path: Path):
    """The meter measures the document that is actually sent (ADR-036, E-R).

    The prompt digest above is the frozen template; this is the rendered
    document. Metering the template would measure something the provider never
    receives, so the two are asserted separately and must differ.
    """
    meter = FakeMeter()
    with pytest.raises(ExtractionError):
        _run(tmp_path, budget_meter=meter)
    persisted = (tmp_path / "run" / CONTENTS_REFERENCE).read_bytes()
    assert meter.seen_request.rendered_contents_sha256 == sha256_bytes(persisted)
    assert meter.seen_request.rendered_contents.encode("utf-8") == persisted
    assert meter.seen_request.rendered_contents_sha256 != meter.seen_request.prompt_sha256


# --- the arithmetic limits ----------------------------------------------------


def test_the_cap_is_the_lesser_of_the_policy_and_the_budget():
    assert resolve_attempt_cap(authorization=_authorization(budget_max_requests=1)) == 1
    assert resolve_attempt_cap(
        authorization=_authorization(budget_max_requests=2, budget_max_wall_clock_seconds=601)
    ) == 2
    assert resolve_attempt_cap(authorization=_authorization(budget_max_requests=3)) == 3
    # A budget larger than the policy cannot buy extra attempts.
    assert resolve_attempt_cap(
        authorization=_authorization(budget_max_requests=99)
    ) == PROVIDER_MAX_ATTEMPTS_PIN


@pytest.mark.parametrize(
    "field",
    [
        "budget_max_records",
        "budget_max_requests",
        "budget_max_input_tokens",
        "budget_max_output_tokens",
        "budget_max_estimated_cost_micros",
        "budget_max_wall_clock_seconds",
        "circuit_breaker_max_consecutive_failures",
    ],
)
@pytest.mark.parametrize("value", [0, -1, "3", None, 1.5, True])
def test_a_non_positive_budget_field_is_refused(field, value):
    with pytest.raises(ExtractionError) as excinfo:
        resolve_attempt_cap(authorization=_authorization(**{field: value}))
    assert excinfo.value.reason_code == "budget_insufficient"


def test_an_output_token_budget_below_the_declared_value_is_refused():
    """The run would exceed its budget by construction."""
    with pytest.raises(ExtractionError) as excinfo:
        resolve_attempt_cap(authorization=_authorization(budget_max_output_tokens=4096))
    assert excinfo.value.reason_code == "budget_insufficient"


@pytest.mark.parametrize("requests,floor", [(1, 300), (2, 601), (3, 903)])
def test_the_wall_clock_floor_tracks_the_cap(requests, floor):
    """A compatibility floor against the theoretical ceiling, not elapsed
    enforcement -- that belongs to the meter."""
    assert resolve_attempt_cap(
        authorization=_authorization(
            budget_max_requests=requests, budget_max_wall_clock_seconds=floor
        )
    ) == requests
    with pytest.raises(ExtractionError) as excinfo:
        resolve_attempt_cap(
            authorization=_authorization(
                budget_max_requests=requests, budget_max_wall_clock_seconds=floor - 1
            )
        )
    assert excinfo.value.reason_code == "budget_insufficient"


def test_the_three_attempt_ceiling_is_the_documented_worst_case():
    assert PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS == 903


def test_a_wall_clock_budget_below_the_ceiling_is_refused_through_the_runner(tmp_path: Path):
    _refused(
        tmp_path,
        "budget_insufficient",
        chain_overrides={"authorization": {"budget_max_wall_clock_seconds": 10}},
    )


def test_the_breaker_is_validated_configuration_only(tmp_path: Path):
    """Single-call runs start no second call, so the breaker has no further
    runtime effect here; multi-call enforcement is outside E-B."""
    provider = _Provider()
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=provider)
    assert provider.calls == 1


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
