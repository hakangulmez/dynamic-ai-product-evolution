"""The budget seam on the v2 route: identity, ceilings, and what it is shown.

Migrated from ``test_live_budget_enforcement.py`` by ADR-045 (G2b). Two things
genuinely changed shape and are asserted in their v2 form rather than pretended
to be unchanged:

**Where the budget decides.** v1 metered an *estimate* before anything existed,
so every budget refusal left zero artifacts. v2 must measure first, so the count
call, the run root and the five prepared inputs already exist by the time the
budget can decide. A budget refusal is therefore a published
``pre_generation_invalid`` terminal chain, not an empty directory. The invariant
that survives is the one that mattered: **no generation happens.**

**What the budget is shown.** v1 handed the meter the ``ProviderRequest`` object.
v2 hands the session a measured token count, a computed reserve, and the
``provider_request_digest`` -- the six-value identity of the request. The
digest-based form is the stronger one, and it is checked against the artifacts
the run actually persisted.

The meter-identity check still runs before the run root exists, so that refusal
does still leave zero artifacts, and that is asserted separately.

Nothing here touches a network, an SDK, or ADC.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.count_reconciliation import reserve_cost_microdollars
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.execution_outcome import (
    COUNT_RAW_REFERENCE,
    EXECUTION_OUTCOME_REFERENCE,
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
    PROVIDER_PROTOCOL_VERSION_V8,
    BudgetAdmission,
    ProviderRequest,
    ProviderResponse,
    provider_request_digest,
)
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.run_extraction import (
    CLIENT_CONTRACT_REFERENCE,
    CONTENTS_REFERENCE,
    PACKET_REFERENCE,
    PROMPT_REFERENCE,
    run_extraction_stage_v2,
)
from dynamic_ai_products.providers.client_contract_v2 import (
    build_client_contract_v2,
    build_operation_endpoints,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"
PROJECT = "my-research-project"
CODE_COMMIT = "be627003f3246b371c2b3ac13e813ef0bb112582"
RUN_CREATED_AT = "2026-07-29T00:00:00Z"
STAGE = "product_extraction"
STAGE_SHA = STAGE_OUTPUT_SCHEMA_SHA256[STAGE]
ROUTING_SHA = "4" * 64
METER_IDENTITY = "g2b-budget-meter"
METER_VERSION = "0.1.0"
MAX_OUTPUT_TOKENS = 8192
MEASURED_TOKENS = 1000
CHANGE_REQUEST_REFERENCE = (
    "evals/change_requests/CR-0001-product-discovery-recall-bootstrap-qualification.md"
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


def _contract():
    return build_client_contract_v2(vertex_project=PROJECT)


def _contract_digest():
    return sha256_bytes(canonical_json_bytes(_contract()))


def _repo_digest(reference: str) -> str:
    return sha256_bytes((REPO_ROOT / reference).read_bytes())


class _Provider:
    def __init__(self) -> None:
        self.count_sends = 0
        self.generate_sends = 0
        self.revoked = 0
        self.seen_request = None

    def assert_run_permitted(self, **_kwargs) -> None:
        pass

    def revoke_run_permission(self) -> None:
        self.revoked += 1

    def client_contract(self) -> dict:
        return _contract()

    def count_tokens(self, request, *, sink):
        self.count_sends += 1
        self.seen_request = request
        record = sink(
            operation_label="count_tokens",
            attempt_ordinal=1,
            raw_bytes=COUNT_BODY,
            send_outcome="response_2xx",
            sdk_call_outcome="returned",
            provider_reason_code=None,
        )
        return record, MEASURED_TOKENS

    def complete_v8(self, request, *, admission, sink):
        admission.spend()
        self.generate_sends += 1
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


class FakeSession:
    """Records exactly what the runner shows it, and can refuse on demand."""

    def __init__(
        self,
        *,
        cap: int = 3,
        identity: str = METER_IDENTITY,
        version: str = METER_VERSION,
        refuse: str | None = None,
        run_root: Path | None = None,
        cap_override: int | None = None,
        reserve_override: int | None = None,
        digest_override: str | None = None,
    ) -> None:
        self.cap = cap
        self._identity = identity
        self._version = version
        self._refuse = refuse
        self._run_root = run_root
        self._cap_override = cap_override
        self._reserve_override = reserve_override
        self._digest_override = digest_override
        self.calls: list[dict] = []
        self.seen_measured: int | None = None
        self.seen_reserve: int | None = None
        self.seen_digest: str | None = None
        self.root_existed_at_call: bool | None = None

    def meter_identity(self):
        return {"meter_identity": self._identity, "meter_version": self._version}

    def admit(
        self, *, measured_input_tokens, reserved_cost_microdollars, provider_request_digest
    ):
        if self._run_root is not None:
            self.root_existed_at_call = self._run_root.exists()
        self.seen_measured = measured_input_tokens
        self.seen_reserve = reserved_cost_microdollars
        self.seen_digest = provider_request_digest
        self.calls.append(
            {
                "measured_input_tokens": measured_input_tokens,
                "reserved_cost_microdollars": reserved_cost_microdollars,
                "provider_request_digest": provider_request_digest,
            }
        )
        if self._refuse is not None:
            raise ExtractionError("refused by the meter", reason_code=self._refuse)
        return BudgetAdmission(
            measured_input_tokens=measured_input_tokens,
            reserved_cost_microdollars=(
                reserved_cost_microdollars
                if self._reserve_override is None
                else self._reserve_override
            ),
            generate_attempt_cap=self.cap if self._cap_override is None else self._cap_override,
            provider_request_digest=(
                provider_request_digest
                if self._digest_override is None
                else self._digest_override
            ),
            session_nonce="nonce",
        )


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


def _prompt_qualification() -> dict:
    prompt = load_prompt(REPO_ROOT, "product_discovery_recall")
    return {
        "contract": "prompt_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "promptqual-g2b-budget",
        "qualification_basis": "bootstrap_pre_evaluation",
        "qualification_scope": "qualified_for_development",
        "qualification_status": "bootstrap_authorized_live_dev",
        "prompt_lifecycle_state": "candidate",
        "supersedes_qualification_id": None,
        "prompt_id": "product_discovery_recall",
        "prompt_registry_version": prompt["prompt_registry_version"],
        "prompt_reference": prompt["reference"],
        "prompt_artifact_sha256": prompt["prompt_hash"],
        "stage": STAGE,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[STAGE],
        "stage_output_contract_sha256": STAGE_SHA,
        "execution_contract_id": "extraction_provider_client_contract@0.2.0",
        "execution_contract_sha256": _contract_digest(),
        "routing_contract_id": "vertex_gemini_route@0.2.0",
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


def _write_chain(root: Path, **authorization_overrides):
    (root / "governance").mkdir(parents=True, exist_ok=True)
    endpoints = build_operation_endpoints(vertex_project=PROJECT)
    allowlist = [endpoints["count_tokens"], endpoints["generate_content"]]

    qualification = {
        "contract": "adapter_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "qual-g2b-budget",
        "adapter_identity": "dynamic_ai_products.providers.vertex_gemini_v2",
        "adapter_version": "0.2.0",
        "adapter_family": "model_execution",
        "execution_contract_id": "extraction_provider_client_contract@0.2.0",
        "execution_contract_sha256": _contract_digest(),
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[STAGE],
        "stage_output_contract_sha256": STAGE_SHA,
        "qualification_scope": "live_dev",
        "qualification_status": "qualified",
        "qualified_at": "2026-07-01T00:00:00Z",
    }
    qual_bytes = canonical_json_bytes(qualification)
    (root / GOV_QUALIFICATION).write_bytes(qual_bytes)

    pq_bytes = canonical_json_bytes(_prompt_qualification())
    (root / GOV_PROMPT_QUALIFICATION).write_bytes(pq_bytes)

    enablement = {
        "contract": "adapter_enablement_record@0.1.0",
        "schema_version": "0.1.0",
        "enablement_id": "enab-g2b-budget",
        "adapter_qualification_record_reference": GOV_QUALIFICATION,
        "adapter_qualification_record_sha256": sha256_bytes(qual_bytes),
        "prompt_qualification_reference": GOV_PROMPT_QUALIFICATION,
        "prompt_qualification_sha256": sha256_bytes(pq_bytes),
        "stage": STAGE,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[STAGE],
        "stage_output_contract_sha256": STAGE_SHA,
        "routing_contract_id": "vertex_gemini_route@0.2.0",
        "routing_contract_sha256": ROUTING_SHA,
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "endpoint_allowlist": list(allowlist),
        "enablement_status": "enabled_live_dev",
        "approver": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
    }
    enab_bytes = canonical_json_bytes(enablement)
    (root / GOV_ENABLEMENT).write_bytes(enab_bytes)

    authorization = {
        "contract": "live_call_authorization@0.2.0",
        "schema_version": "0.2.0",
        "authorization_id": "auth-g2b-budget",
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
        "budget_max_output_tokens": MAX_OUTPUT_TOKENS,
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
    authorization.update(authorization_overrides)
    auth_bytes = canonical_json_bytes(authorization)
    (root / GOV_AUTH).write_bytes(auth_bytes)
    return {"reference": GOV_AUTH, "sha256": sha256_bytes(auth_bytes)}


def _evidence_binding():
    schema = json.loads(
        (SCHEMAS / "extraction_execution_outcome.schema.json").read_text(encoding="utf-8")
    )["properties"]["evidence_binding"]["properties"]
    return {name: schema[name]["const"] for name in schema}


def _run(tmp_path: Path, *, authorization_overrides=None, **overrides):
    governance = tmp_path / "governance-root"
    pin = _write_chain(governance, **(authorization_overrides or {}))
    kwargs = {
        "run_root": tmp_path / "run",
        "repo_root": REPO_ROOT,
        "stage": STAGE,
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [_passage()],
        "document_publication_dates": {"sec-1": "2024-02-14"},
        "coverage_artifact": {"reference": "coverage/c.json", "sha256": "d" * 64},
        "source_snapshot_manifest": {"reference": "snapshots/m.json", "sha256": "e" * 64},
        "code_commit": CODE_COMMIT,
        "run_created_at": RUN_CREATED_AT,
        "extraction_run_id": "ext-g2b-1",
        "prediction_run_id": "pred-g2b-1",
        "evidence_binding": _evidence_binding(),
        "schema_root": str(SCHEMAS),
        "provider": _Provider(),
        "budget_session": FakeSession(),
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


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- the meter identity is checked before anything exists ----------------------


def test_v2_a_meter_whose_identity_differs_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "budget_meter_identity_mismatch",
        budget_session=FakeSession(identity="some-other-meter"),
    )
    assert not (tmp_path / "run").exists()


def test_v2_a_meter_whose_version_differs_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "budget_meter_identity_mismatch",
        budget_session=FakeSession(version="9.9.9"),
    )
    assert not (tmp_path / "run").exists()


def test_v2_the_e_b_gate_needs_the_authorization_to_pin_a_real_meter(tmp_path: Path):
    """Identity equality is enforced. It is not, and is not claimed to be, a
    structural bar against an in-process implementation imitating the values."""
    _refused(
        tmp_path,
        "budget_meter_identity_mismatch",
        authorization_overrides={"budget_meter_identity": "e-m-real-meter"},
    )
    assert not (tmp_path / "run").exists()


def test_v2_a_meter_identity_refusal_precedes_the_run_root_and_every_send(tmp_path: Path):
    provider = _Provider()
    _refused(
        tmp_path,
        "budget_meter_identity_mismatch",
        provider=provider,
        budget_session=FakeSession(identity="wrong"),
    )
    assert (provider.count_sends, provider.generate_sends) == (0, 0)
    assert not (tmp_path / "run").exists()


def test_v2_an_absent_budget_session_is_refused(tmp_path: Path):
    provider = _Provider()
    _refused(tmp_path, "budget_meter_unavailable", provider=provider, budget_session=None)
    assert (provider.count_sends, provider.generate_sends) == (0, 0)
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("session", [object(), 7, "session", {}, lambda: None])
def test_v2_a_non_conforming_session_cannot_report_an_identity(tmp_path: Path, session):
    """v1 refused a non-conforming meter through an explicit protocol gate.

    v2 has no separate protocol gate on this seam: the runner asks the session for
    its identity, and an object that cannot answer fails there instead. The
    observable guarantee is the same one -- nothing is created and nothing is
    sent -- so it is asserted rather than the vanished reason code.
    """
    provider = _Provider()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider, budget_session=session)
    assert excinfo.value.reason_code in {
        "budget_meter_identity_mismatch",
        "budget_meter_protocol_invalid",
        "budget_meter_unavailable",
    }
    assert (provider.count_sends, provider.generate_sends) == (0, 0)
    assert not (tmp_path / "run").exists()


# --- ceilings the runner enforces itself ---------------------------------------


def test_v2_a_wall_clock_budget_below_the_ceiling_is_refused_through_the_runner(
    tmp_path: Path,
):
    provider = _Provider()
    _refused(
        tmp_path,
        "budget_insufficient",
        provider=provider,
        authorization_overrides={"budget_max_wall_clock_seconds": 10},
    )
    assert (provider.count_sends, provider.generate_sends) == (0, 0)
    assert not (tmp_path / "run").exists()


def test_v2_an_input_token_ceiling_refusal_never_generates(tmp_path: Path):
    """The runner enforces the ceiling itself, not only through the meter."""
    provider = _Provider()
    session = FakeSession()
    _refused(
        tmp_path,
        "budget_termination",
        provider=provider,
        budget_session=session,
        authorization_overrides={"budget_max_input_tokens": MEASURED_TOKENS - 1},
    )
    assert provider.generate_sends == 0
    assert session.calls == [], "the meter is never consulted once the ceiling is breached"


def test_v2_an_estimated_cost_ceiling_refusal_never_generates(tmp_path: Path):
    reserve = reserve_cost_microdollars(
        measured_input_tokens=MEASURED_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        generate_attempt_cap=3,
    )
    provider = _Provider()
    session = FakeSession()
    _refused(
        tmp_path,
        "budget_termination",
        provider=provider,
        budget_session=session,
        authorization_overrides={"budget_max_estimated_cost_micros": reserve - 1},
    )
    assert provider.generate_sends == 0
    assert session.calls == []


def test_v2_one_microdollar_more_admits_the_same_run(tmp_path: Path):
    """The refusal is the arithmetic, not an unrelated failure."""
    reserve = reserve_cost_microdollars(
        measured_input_tokens=MEASURED_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        generate_attempt_cap=3,
    )
    outcome = _run(
        tmp_path, authorization_overrides={"budget_max_estimated_cost_micros": reserve}
    )
    assert outcome.verdict == "two_operation_run_complete"


# --- a meter refusal publishes rather than vanishing ---------------------------


@pytest.mark.parametrize(
    "reason",
    [
        "budget_input_tokens_exceeded",
        "budget_estimated_cost_exceeded",
        "budget_wall_clock_exceeded",
    ],
)
def test_v2_every_meter_refusal_stops_before_generation_and_publishes(
    tmp_path: Path, reason
):
    """The v1 form of this asserted zero artifacts, which v2 cannot honour.

    v2 must send countTokens before the budget can decide on a measured number,
    so the run root and the prepared inputs already exist. What still holds -- and
    is what the assertion was protecting -- is that nothing is generated and the
    refusal is recorded rather than lost.
    """
    provider = _Provider()
    error = _refused(
        tmp_path, "budget_termination", provider=provider, budget_session=FakeSession(refuse=reason)
    )
    assert error.detail == "pre_generation_invalid"
    assert provider.generate_sends == 0
    files = _files(tmp_path / "run")
    assert EXECUTION_OUTCOME_REFERENCE in files
    assert COUNT_RAW_REFERENCE in files
    record = json.loads((tmp_path / "run" / EXECUTION_OUTCOME_REFERENCE).read_text())
    assert record["route_family"] == "pre_generation_invalid"
    assert record["generate_attempts"] == []


def test_v2_an_undeclared_meter_reason_collapses_rather_than_widening(tmp_path: Path):
    provider = _Provider()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider, budget_session=FakeSession(refuse="invented"))
    # "invented" is not a declared meter reason, so it is not treated as one: it
    # collapses onto the closed provider vocabulary instead of widening either
    # enum. The published record carries a declared terminal reason, never the
    # invented string.
    assert excinfo.value.reason_code != "invented"
    assert provider.generate_sends == 0
    record = json.loads((tmp_path / "run" / EXECUTION_OUTCOME_REFERENCE).read_text())
    assert "invented" not in json.dumps(record)
    assert record["terminal_reason"] == excinfo.value.reason_code


def test_v2_an_admission_claiming_a_larger_cap_is_refused(tmp_path: Path):
    provider = _Provider()
    _refused(
        tmp_path,
        "budget_termination",
        provider=provider,
        budget_session=FakeSession(cap_override=99),
    )
    assert provider.generate_sends == 0


def test_v2_an_admission_reserving_a_different_amount_is_refused(tmp_path: Path):
    provider = _Provider()
    _refused(
        tmp_path,
        "budget_termination",
        provider=provider,
        budget_session=FakeSession(reserve_override=1),
    )
    assert provider.generate_sends == 0


# --- what the budget is shown --------------------------------------------------


def test_v2_the_session_runs_before_the_run_root_holds_a_prediction(tmp_path: Path):
    """v1 asserted the meter ran before the run root existed at all.

    v2 cannot: the count response is already persisted. The surviving guarantee
    is that no prediction exists when the budget decides.
    """
    session = FakeSession(run_root=tmp_path / "run")
    _run(tmp_path, budget_session=session)
    assert session.root_existed_at_call is True
    assert session.calls, "the session was consulted"


def test_v2_the_metered_digest_binds_the_persisted_packet_prompt_and_contents(
    tmp_path: Path,
):
    """v1 handed the meter the request object; v2 hands it the request identity.

    The digest is recomputed here from the artifacts the run persisted, so the
    number the budget decided on is provably the request that was sent.
    """
    session = FakeSession()
    provider = _Provider()
    _run(tmp_path, provider=provider, budget_session=session)

    root = tmp_path / "run"
    packet_sha = sha256_bytes((root / PACKET_REFERENCE).read_bytes())
    prompt_sha = sha256_bytes((root / PROMPT_REFERENCE).read_bytes())
    contents = (root / CONTENTS_REFERENCE).read_bytes()
    contract_sha = sha256_bytes((root / CLIENT_CONTRACT_REFERENCE).read_bytes())

    rebuilt = ProviderRequest(
        stage=STAGE,
        rendered_contents=contents.decode("utf-8"),
        rendered_contents_sha256=sha256_bytes(contents),
        prompt_sha256=prompt_sha,
        input_packet_sha256=packet_sha,
    )
    expected = provider_request_digest(
        rebuilt,
        provider_client_contract_sha256=contract_sha,
        protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
    )
    assert session.seen_digest == expected
    # The rendered document is the sole provider-input authority (ADR-036), and
    # it is not the frozen template: metering the template would measure
    # something the provider never receives.
    assert provider.seen_request.rendered_contents_sha256 == sha256_bytes(contents)
    assert provider.seen_request.rendered_contents_sha256 != prompt_sha


@pytest.mark.parametrize(
    "reference,component",
    [
        (PACKET_REFERENCE, "input_packet_sha256"),
        (PROMPT_REFERENCE, "prompt_sha256"),
        (CONTENTS_REFERENCE, "rendered_contents_sha256"),
    ],
)
def test_v2_each_metered_digest_component_is_the_persisted_one(
    tmp_path: Path, reference, component
):
    """The three v1 tests, kept separate rather than folded into the digest one.

    v1 asserted each of packet, prompt and rendered contents individually against
    what the meter was shown. v2 shows the meter a single digest over all three,
    so each component is checked by rebuilding the digest with that one component
    replaced: if the run had metered anything other than the persisted bytes, the
    rebuilt digest would not match.
    """
    session = FakeSession()
    provider = _Provider()
    _run(tmp_path, provider=provider, budget_session=session)

    root = tmp_path / "run"
    persisted = sha256_bytes((root / reference).read_bytes())
    sent = provider.seen_request
    assert getattr(sent, component) == persisted

    # ``ProviderRequest`` validates its own contents digest, so the contents case
    # is perturbed through the document itself rather than through the field.
    other_contents = sent.rendered_contents + "\ntampered"
    corrupted = ProviderRequest(
        stage=STAGE,
        rendered_contents=(
            other_contents if component == "rendered_contents_sha256" else sent.rendered_contents
        ),
        rendered_contents_sha256=(
            sha256_bytes(other_contents.encode("utf-8"))
            if component == "rendered_contents_sha256"
            else sent.rendered_contents_sha256
        ),
        prompt_sha256=("0" * 64 if component == "prompt_sha256" else sent.prompt_sha256),
        input_packet_sha256=(
            "0" * 64 if component == "input_packet_sha256" else sent.input_packet_sha256
        ),
    )
    contract_sha = sha256_bytes((root / CLIENT_CONTRACT_REFERENCE).read_bytes())
    assert session.seen_digest != provider_request_digest(
        corrupted,
        provider_client_contract_sha256=contract_sha,
        protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
    )


def test_v2_the_metered_contents_digest_is_not_the_prompt_digest(tmp_path: Path):
    """The rendered document is what is sent; the frozen template is not."""
    provider = _Provider()
    _run(tmp_path, provider=provider)
    root = tmp_path / "run"
    contents = (root / CONTENTS_REFERENCE).read_bytes()
    prompt = (root / PROMPT_REFERENCE).read_bytes()
    assert provider.seen_request.rendered_contents.encode("utf-8") == contents
    assert sha256_bytes(contents) != sha256_bytes(prompt)
    assert provider.seen_request.rendered_contents_sha256 != provider.seen_request.prompt_sha256


def test_v2_the_metered_count_is_the_measured_one_not_an_estimate(tmp_path: Path):
    session = FakeSession()
    _run(tmp_path, budget_session=session)
    assert session.seen_measured == MEASURED_TOKENS


def test_v2_the_metered_reserve_uses_the_declared_max_output_tokens(tmp_path: Path):
    """v1 showed the meter ``max_output_tokens``; v2 shows the reserve built from it."""
    session = FakeSession()
    _run(tmp_path, budget_session=session)
    assert session.seen_reserve == reserve_cost_microdollars(
        measured_input_tokens=MEASURED_TOKENS,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        generate_attempt_cap=3,
    )
    assert _contract()["model_parameters"]["max_output_tokens"] == MAX_OUTPUT_TOKENS


def test_v2_the_breaker_is_validated_configuration_only(tmp_path: Path):
    """A completed run starts no second generation, so the breaker has no further
    runtime effect here; multi-call enforcement is outside E-B."""
    provider = _Provider()
    outcome = _run(tmp_path, provider=provider)
    assert outcome.verdict == "two_operation_run_complete"
    assert (provider.count_sends, provider.generate_sends) == (1, 1)


def test_v2_a_conforming_fake_session_lets_the_run_proceed(tmp_path: Path):
    provider = _Provider()
    session = FakeSession()
    outcome = _run(tmp_path, provider=provider, budget_session=session)
    assert outcome.verdict == "two_operation_run_complete"
    assert len(session.calls) == 1
    assert provider.revoked == 1
