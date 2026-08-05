"""The SPEC-027 chain, scope equality, and the governance root, on the v2 route.

Migrated from ``test_live_authorization_validation.py`` by ADR-045 (G2b), which
retired the v1 provider route. The governance semantics themselves did not move:
``validate_governance_chain``, ``validate_governance_semantics`` and
``validate_authorization_scope`` are the same functions on both routes, and
``validate_governance_chain_v2`` reaches the released walk through a v1-shaped
stand-in. What changed is the entry point, the authorization contract
(``@0.2.0``), the client contract (``@0.2.0``), the provider protocol (v8), and
the fourth governance ring the enablement now really pins.

Every refusal here happens before the run root is created. Nothing in this module
touches a network, an SDK, or ADC.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.routing_contract import (
    ROUTING_CONTRACT_ID,
    derive_routing_contract,
)
from dynamic_ai_products.extraction.manifests import (
    STAGE_OUTPUT_SCHEMA_SHA256,
    AUTHORIZATION_V2_PROPERTIES,
    LIVE_AUTHORIZATION_V2_CONTRACT,
    STAGE_OUTPUT_CONTRACT_ID,
    wall_clock_floor_for_cap,
)
from dynamic_ai_products.extraction.prompt_qualification import (
    DECLARED_NON_CLAIMS,
    GOVERNING_SPEC_REFERENCE,
)
from dynamic_ai_products.extraction.prompts import load_prompt
from dynamic_ai_products.extraction.provider_adapter import ProviderResponse
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.run_extraction import (
    CONTENTS_REFERENCE,
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
COVERAGE = {"reference": "coverage/source_family_coverage.json", "sha256": "d" * 64}
SOURCE_MANIFEST = {"reference": "snapshots/manifest.json", "sha256": "e" * 64}
DATES = {"sec-1": "2024-02-14"}
PROJECT = "my-research-project"
CODE_COMMIT = "be627003f3246b371c2b3ac13e813ef0bb112582"
RUN_CREATED_AT = "2026-07-29T00:00:00Z"
STAGE = "product_extraction"
STAGE_SHA = STAGE_OUTPUT_SCHEMA_SHA256[STAGE]
ROUTING_SHA = derive_routing_contract(
    client_contract=build_client_contract_v2(vertex_project=PROJECT)
)["routing_contract_sha256"]
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


def _contract():
    return build_client_contract_v2(vertex_project=PROJECT)


def _contract_digest():
    return sha256_bytes(canonical_json_bytes(_contract()))


def _repo_digest(reference: str) -> str:
    return sha256_bytes((REPO_ROOT / reference).read_bytes())


class _Provider:
    """Two-operation fake. No client, no ADC, no socket, no vendor import."""

    def __init__(self) -> None:
        self.count_sends = 0
        self.generate_sends = 0
        self.permits = 0
        self.revoked = 0
        self.contracts = 0
        self.seen_digest = None
        self.seen_allowlist = None
        self.seen_enablement_allowlist = None

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

    def revoke_run_permission(self) -> None:
        self.revoked += 1

    def client_contract(self) -> dict:
        self.contracts += 1
        return _contract()

    def count_tokens(self, request, *, sink):
        self.count_sends += 1
        record = sink(
            operation_label="count_tokens",
            attempt_ordinal=1,
            raw_bytes=COUNT_BODY,
            send_outcome="response_2xx",
            sdk_call_outcome="returned",
            provider_reason_code=None,
        )
        return record, json.loads(COUNT_BODY.decode("utf-8"))["totalTokens"]

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


class _Session:
    """Admits on the measured count, under the identity the authorization pins."""

    def __init__(self, cap: int = 3) -> None:
        self.cap = cap
        self.calls: list[dict] = []

    def meter_identity(self):
        return {"meter_identity": "dynamic_ai_products.extraction.budget_session", "meter_version": "0.1.0"}

    def admit(
        self, *, measured_input_tokens, reserved_cost_microdollars, provider_request_digest
    ):
        from dynamic_ai_products.extraction.provider_adapter import BudgetAdmission

        self.calls.append(
            {
                "measured_input_tokens": measured_input_tokens,
                "reserved_cost_microdollars": reserved_cost_microdollars,
                "provider_request_digest": provider_request_digest,
            }
        )
        return BudgetAdmission(
            measured_input_tokens=measured_input_tokens,
            reserved_cost_microdollars=reserved_cost_microdollars,
            generate_attempt_cap=self.cap,
            provider_request_digest=provider_request_digest,
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


def write_company_identity(root: Path, **overrides) -> dict[str, str]:
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


def _prompt_qualification(**overrides) -> dict:
    prompt = load_prompt(REPO_ROOT, "product_discovery_schema_v4")
    record = {
        "contract": "prompt_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "promptqual-g2b",
        "qualification_basis": "bootstrap_pre_evaluation",
        "qualification_scope": "qualified_for_development",
        "qualification_status": "bootstrap_authorized_live_dev",
        "prompt_lifecycle_state": "candidate",
        "supersedes_qualification_id": None,
        "prompt_id": "product_discovery_schema_v4",
        "prompt_registry_version": prompt["prompt_registry_version"],
        "prompt_reference": prompt["reference"],
        "prompt_artifact_sha256": prompt["prompt_hash"],
        "stage": STAGE,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[STAGE],
        "stage_output_contract_sha256": STAGE_SHA,
        "execution_contract_id": "extraction_provider_client_contract@0.2.0",
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
    record.update(overrides)
    return record


def write_governance_chain(root: Path, **overrides):
    """Persist the four-ring chain and return the authorization pin.

    Unknown override keys raise: silently ignoring one would let a test think it
    had weakened a record when it had not, and pass for the wrong reason.
    """
    known = {"qualification", "enablement", "authorization", "prompt_qualification"}
    unknown = sorted(set(overrides) - known)
    if unknown:
        raise AssertionError(f"unknown governance overrides: {unknown}")
    (root / "governance").mkdir(parents=True, exist_ok=True)
    endpoints = build_operation_endpoints(vertex_project=PROJECT)
    allowlist = [endpoints["count_tokens"], endpoints["generate_content"]]

    qualification = {
        "contract": "adapter_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "qual-0001",
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
    qualification.update(overrides.pop("qualification", {}))
    qual_bytes = canonical_json_bytes(qualification)
    (root / GOV_QUALIFICATION).write_bytes(qual_bytes)

    prompt_qualification = _prompt_qualification(**overrides.pop("prompt_qualification", {}))
    pq_bytes = canonical_json_bytes(prompt_qualification)
    (root / GOV_PROMPT_QUALIFICATION).write_bytes(pq_bytes)

    enablement = {
        "contract": "adapter_enablement_record@0.1.0",
        "schema_version": "0.1.0",
        "enablement_id": "enab-0001",
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
        "contract": LIVE_AUTHORIZATION_V2_CONTRACT,
        "schema_version": "0.2.0",
        "authorization_id": "auth-0001",
        "authorized_by": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "adapter_enablement_record_reference": GOV_ENABLEMENT,
        "adapter_enablement_record_sha256": sha256_bytes(enab_bytes),
        "provider_client_contract_reference": "inputs/provider_client_contract.json",
        "provider_client_contract_sha256": _contract_digest(),
        "budget_meter_identity": "dynamic_ai_products.extraction.budget_session",
        "budget_meter_version": "0.1.0",
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


def _run(tmp_path: Path, *, chain_overrides=None, **overrides):
    governance_root = tmp_path / "governance-root"
    pin = write_governance_chain(governance_root, **(chain_overrides or {}))
    kwargs = {
        "run_root": tmp_path / "run",
        "repo_root": REPO_ROOT,
        "stage": STAGE,
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [_passage()],
        "document_publication_dates": dict(DATES),
        "coverage_artifact": dict(COVERAGE),
        "source_snapshot_manifest": dict(SOURCE_MANIFEST),
        "code_commit": CODE_COMMIT,
        "run_created_at": RUN_CREATED_AT,
        "extraction_run_id": "ext-0001",
        "prediction_run_id": "pred-0001",
        "evidence_binding": _evidence_binding(),
        "schema_root": str(SCHEMAS),
        "provider": _Provider(),
        "governance_artifact_root": governance_root,
        "company_identity_root": tmp_path / "identity",
        "company_identity_pin": write_company_identity(tmp_path / "identity"),
        "live_call_authorization_pin": pin,
    }
    kwargs.update(overrides)
    return run_extraction_stage_v2(**kwargs)


def _evidence_binding():
    schema = json.loads(
        (SCHEMAS / "extraction_execution_outcome.schema.json").read_text(encoding="utf-8")
    )["properties"]["evidence_binding"]["properties"]
    return {name: schema[name]["const"] for name in schema}


def _refused(tmp_path: Path, expected: str, **kwargs):
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, **kwargs)
    assert excinfo.value.reason_code == expected
    assert not (tmp_path / "run").exists()
    return excinfo.value


def _ineffective(tmp_path: Path, **chain):
    return _refused(tmp_path, "governance_record_not_effective", chain_overrides=chain)


def _completed(tmp_path: Path, **kwargs):
    """A valid chain runs to completion, which is what "the chain passed" means.

    On v1 this invariant was expressed as "the provider stand-in was reached and
    its refusal surfaced". The v2 route measures before it generates, so the
    honest v2 form is a completed two-operation run: every governance check has
    passed and both operations happened.
    """
    outcome = _run(tmp_path, **kwargs)
    assert outcome.verdict == "two_operation_run_complete"
    return outcome


# --- the governance root is explicit -----------------------------------------


def test_v2_a_pin_without_a_governance_root_is_refused(tmp_path: Path):
    _refused(tmp_path, "governance_root_required", governance_artifact_root=None)


def test_v2_a_governance_root_without_a_pin_is_refused(tmp_path: Path):
    _refused(tmp_path, "governance_root_required", live_call_authorization_pin=None)


@pytest.mark.parametrize(
    "reference",
    ["../escape.json", "/etc/passwd", "C:/x.json", "a\\b.json", "", "  "],
)
def test_v2_an_unsafe_authorization_reference_is_refused(tmp_path: Path, reference):
    _refused(
        tmp_path,
        "authorization_chain_broken",
        live_call_authorization_pin={"reference": reference, "sha256": "0" * 64},
    )


def test_v2_a_drifted_authorization_digest_is_refused(tmp_path: Path):
    governance_root = tmp_path / "governance-root"
    pin = write_governance_chain(governance_root)
    _refused(
        tmp_path,
        "authorization_chain_broken",
        governance_artifact_root=governance_root,
        live_call_authorization_pin={**pin, "sha256": "0" * 64},
    )


def test_v2_a_complete_chain_reaches_the_provider(tmp_path: Path):
    """A valid chain gets all the way to both calls.

    The run root now holds the full completed chain, which only the post-gate
    path writes, and the rendered document is among the artifacts: E-R persists
    what was sent.
    """
    outcome = _completed(tmp_path)
    published = {
        str(f.relative_to(tmp_path / "run"))
        for f in (tmp_path / "run").rglob("*")
        if f.is_file()
    }
    assert CONTENTS_REFERENCE in published
    # Eleven, not the v1 route's seven: the two-operation route additionally
    # persists the countTokens attempt body, the generate attempt body, and the
    # execution outcome that classifies the run.
    assert len(published) == 11
    assert "attempts/count_tokens_1.json" in published
    assert "manifests/extraction_execution_outcome.json" in published
    assert outcome.run_root == tmp_path / "run"


# --- the chain is walked ring by ring -----------------------------------------


def test_v2_a_broken_enablement_pin_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "authorization_chain_broken",
        chain_overrides={"authorization": {"adapter_enablement_record_sha256": "0" * 64}},
    )


def test_v2_a_broken_qualification_pin_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "authorization_chain_broken",
        chain_overrides={"enablement": {"adapter_qualification_record_sha256": "0" * 64}},
    )


def test_v2_a_missing_spec_024_prompt_qualification_is_refused(tmp_path: Path):
    """SPEC-027 places that reference on the enablement record.

    On v1 this pin was shape-checked and never opened. Here the blank reference
    fails inside the hydration that ADR-044 added, which is the same refusal code
    reached for a stronger reason.
    """
    _refused(
        tmp_path,
        "authorization_chain_broken",
        chain_overrides={"enablement": {"prompt_qualification_reference": "  "}},
    )


@pytest.mark.parametrize(
    "override",
    [
        {"contract": "something_else@0.1.0"},
        {"provider_called": False},
        {"harness_run": True},
    ],
)
def test_v2_a_malformed_authorization_is_refused(tmp_path: Path, override):
    _refused(
        tmp_path, "authorization_chain_broken", chain_overrides={"authorization": override}
    )


def test_v2_an_undeclared_authorization_property_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "authorization_chain_broken",
        chain_overrides={"authorization": {"surprise": "x"}},
    )


@pytest.mark.parametrize(
    "key", ["token", "api_key", "credentials", "authorization", "access_token"]
)
def test_v2_a_credential_shaped_property_is_refused(tmp_path: Path, key):
    _refused(
        tmp_path,
        "credential_material_in_artifact",
        chain_overrides={"authorization": {key: "value"}},
    )


def test_v2_a_credential_shaped_value_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "credential_material_in_artifact",
        chain_overrides={"authorization": {"authorized_by": "ya29.LEAKED"}},
    )


@pytest.mark.parametrize("record", ["authorization", "enablement", "qualification"])
@pytest.mark.parametrize("value", ["0.3.0", "9.9.9", "", None, 1])
def test_v2_a_wrong_schema_version_is_refused(tmp_path: Path, record, value):
    """Each ring declares its own version: 0.2.0 for the authorization, 0.1.0 above."""
    _refused(
        tmp_path,
        "authorization_chain_broken",
        chain_overrides={record: {"schema_version": value}},
    )


def test_v2_the_authorization_ring_must_declare_its_own_successor_version(tmp_path: Path):
    """0.1.0 is the released predecessor and may not satisfy a v2 run."""
    _refused(
        tmp_path,
        "authorization_chain_broken",
        chain_overrides={"authorization": {"schema_version": "0.1.0"}},
    )


# --- scope equality ------------------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"stage": "task_extraction"},
        {"company_id": "CIK0000000001"},
        {"observation_cutoff_date": "2023-12-31"},
    ],
)
def test_v2_a_scope_mismatch_is_refused(tmp_path: Path, override):
    _refused(
        tmp_path, "authorization_scope_mismatch", chain_overrides={"authorization": override}
    )


def test_v2_a_run_before_the_window_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "authorization_scope_mismatch",
        chain_overrides={"authorization": {"effective_at": "2027-01-01T00:00:00Z"}},
    )


def test_v2_a_run_after_the_window_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "authorization_scope_mismatch",
        chain_overrides={"authorization": {"expires_at": "2026-01-01T00:00:00Z"}},
    )


def test_v2_the_validity_window_is_checked_against_the_injected_instant(tmp_path: Path):
    """This package reads no clock; the run's own declared instant is used.

    An instant outside both windows trips the **enablement** window first, which
    is the stronger refusal: an authorization cannot be in force while the
    enablement it rests on is not.
    """
    _refused(
        tmp_path,
        "governance_record_not_effective",
        run_created_at="2030-01-01T00:00:00Z",
    )


def test_v2_an_authorization_only_window_violation_still_reports_scope(tmp_path: Path):
    """Inside the enablement window but outside the authorization's own."""
    _refused(
        tmp_path,
        "authorization_scope_mismatch",
        chain_overrides={"authorization": {"expires_at": "2026-07-02T00:00:00Z"}},
        run_created_at=RUN_CREATED_AT,
    )


# --- the client contract the authorization pins --------------------------------


def test_v2_a_foreign_client_contract_pin_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "authorization_client_contract_mismatch",
        chain_overrides={"authorization": {"provider_client_contract_sha256": "0" * 64}},
    )


def test_v2_a_foreign_client_contract_reference_is_refused(tmp_path: Path):
    _refused(
        tmp_path,
        "authorization_client_contract_mismatch",
        chain_overrides={
            "authorization": {"provider_client_contract_reference": "inputs/other.json"}
        },
    )


# --- the records must be in force ----------------------------------------------


@pytest.mark.parametrize("status", ["superseded", "revoked", "", None, "QUALIFIED"])
def test_v2_a_qualification_not_in_force_is_refused(tmp_path: Path, status):
    """superseded and revoked are valid schema values, so only this refuses them."""
    _ineffective(tmp_path, qualification={"qualification_status": status})


@pytest.mark.parametrize("family", ["source", "source_retrieval", "", None])
def test_v2_a_non_model_execution_adapter_family_is_refused(tmp_path: Path, family):
    """The two adapter families have separate readiness and safety gates."""
    _ineffective(tmp_path, qualification={"adapter_family": family})


@pytest.mark.parametrize(
    "rollout,status",
    [
        ("live_dev", "enabled_live_dev"),
        ("controlled_pilot", "enabled_pilot"),
        ("release_or_research_production", "enabled_release"),
    ],
)
def test_v2_each_mapped_rollout_state_activates(tmp_path: Path, rollout, status):
    """Governance semantics accept all three, and the run completes.

    ADR-044 narrows this further downstream: a bootstrap prompt qualification
    admits only ``live_dev``. That refusal is a *prompt-qualification* rule and is
    covered in its own module; here only the SPEC-027 mapping is under test, so
    the two non-``live_dev`` states carry an evaluated-basis-free chain by using a
    prompt qualification whose own gate is not reached.
    """
    if rollout == "live_dev":
        _completed(
            tmp_path,
            chain_overrides={
                "enablement": {"rollout_state": rollout, "enablement_status": status},
                "authorization": {"rollout_state": rollout},
            },
        )
        return
    # Past validate_governance_semantics, refused later by the ADR-044 gate.
    _refused(
        tmp_path,
        "prompt_qualification_invalid",
        chain_overrides={
            "enablement": {"rollout_state": rollout, "enablement_status": status},
            "authorization": {"rollout_state": rollout},
        },
    )


@pytest.mark.parametrize("rollout", ["full_scale", "mock_only", "", None, "invented"])
def test_v2_an_unmapped_rollout_state_is_refused(tmp_path: Path, rollout):
    """mock_only performs no network; full_scale is premature scale."""
    _ineffective(
        tmp_path,
        enablement={"rollout_state": rollout},
        authorization={"rollout_state": rollout},
    )


@pytest.mark.parametrize(
    "status", ["disabled", "suspended", "expired", "revoked", "enabled_release", "", None]
)
def test_v2_an_enablement_status_that_does_not_match_the_rollout_is_refused(
    tmp_path: Path, status
):
    _ineffective(tmp_path, enablement={"enablement_status": status})


def test_v2_a_run_outside_the_enablement_window_is_refused(tmp_path: Path):
    _ineffective(tmp_path, enablement={"expires_at": "2026-07-02T00:00:00Z"})


@pytest.mark.parametrize("value", ["2026-07-01T00:00:00", "not-a-date", "", None])
def test_v2_a_naive_or_malformed_enablement_window_is_refused(tmp_path: Path, value):
    _ineffective(tmp_path, enablement={"effective_at": value})
    _ineffective(tmp_path, enablement={"expires_at": value})


def test_v2_an_inverted_enablement_window_is_refused(tmp_path: Path):
    _ineffective(
        tmp_path,
        enablement={
            "effective_at": "2027-07-01T00:00:00Z",
            "expires_at": "2026-07-01T00:00:00Z",
        },
    )


def test_v2_an_authorization_starting_before_its_enablement_is_refused(tmp_path: Path):
    """An authorization may not outlive, or predate, the enablement it rests on."""
    _ineffective(tmp_path, authorization={"effective_at": "2026-01-01T00:00:00Z"})


def test_v2_an_authorization_outliving_its_enablement_is_refused(tmp_path: Path):
    _ineffective(tmp_path, authorization={"expires_at": "2028-01-01T00:00:00Z"})


def test_v2_containment_is_checked_independently_of_the_run_instant(tmp_path: Path):
    """The run instant sits inside both windows; containment still fails."""
    _ineffective(
        tmp_path,
        authorization={
            "effective_at": "2026-06-01T00:00:00Z",
            "expires_at": "2028-01-01T00:00:00Z",
        },
    )


def test_v2_containment_is_chronological_across_offsets(tmp_path: Path):
    """An equal boundary written with a different offset is contained."""
    _completed(
        tmp_path,
        chain_overrides={"authorization": {"effective_at": "2026-07-01T02:00:00+02:00"}},
    )


def test_v2_a_deployment_environment_mismatch_is_refused(tmp_path: Path):
    _ineffective(tmp_path, authorization={"deployment_environment_id": "prod-eu"})


def test_v2_a_rollout_state_mismatch_is_refused(tmp_path: Path):
    _ineffective(tmp_path, authorization={"rollout_state": "controlled_pilot"})


# --- the stage-output contract identity ----------------------------------------


def test_v2_a_qualification_under_a_different_contract_digest_is_refused(tmp_path: Path):
    """The adapter was never qualified for what it is about to execute."""
    _ineffective(tmp_path, qualification={"execution_contract_sha256": "9" * 64})


def test_v2_a_qualification_naming_a_different_contract_identity_is_refused(tmp_path: Path):
    _ineffective(tmp_path, qualification={"execution_contract_id": "something_else@0.1.0"})


def test_v2_an_enablement_for_a_different_stage_is_refused(tmp_path: Path):
    _ineffective(tmp_path, enablement={"stage": "task_extraction"})


def test_v2_a_stage_output_contract_disagreement_is_refused(tmp_path: Path):
    _ineffective(tmp_path, enablement={"stage_output_contract_sha256": "8" * 64})
    _ineffective(tmp_path, qualification={"stage_output_contract_id": "other@0.1.0"})


def test_v2_a_stage_output_sha_that_is_not_the_released_schema_is_refused(tmp_path: Path):
    """Both records agree, but on the wrong schema."""
    wrong = "7" * 64
    _ineffective(
        tmp_path,
        enablement={"stage_output_contract_sha256": wrong},
        qualification={"stage_output_contract_sha256": wrong},
    )


@pytest.mark.parametrize("false_id", ["invented@0.1.0", "product_observation", "", None])
def test_v2_a_shared_false_identity_with_the_correct_released_sha_is_refused(
    tmp_path: Path, false_id
):
    """The exact defect: both records agree, the digest is right, the ID lies."""
    _ineffective(
        tmp_path,
        qualification={"stage_output_contract_id": false_id},
        enablement={"stage_output_contract_id": false_id},
    )


def test_v2_only_the_qualification_carrying_a_false_identity_is_refused(tmp_path: Path):
    """The mutual-equality check catches this one; both rules are needed."""
    _ineffective(tmp_path, qualification={"stage_output_contract_id": "invented@0.1.0"})


def test_v2_no_semantic_refusal_creates_a_run_root(tmp_path: Path):
    counter = [0]
    original = Path.mkdir
    prefix = str(tmp_path / "run")

    def counting(self, *args, **kwargs):
        if str(self) == prefix or str(self).startswith(prefix + "/"):
            counter[0] += 1
        return original(self, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Path, "mkdir", counting)
        _ineffective(tmp_path, qualification={"qualification_status": "revoked"})
    assert counter[0] == 0
    assert not (tmp_path / "run").exists()


# --- the property set stays closed ---------------------------------------------


def test_v2_the_authorization_property_set_carries_no_prompt_field():
    """ADR-044: the binding is transitive through the enablement, never here."""
    assert not any("prompt" in name for name in AUTHORIZATION_V2_PROPERTIES)
    assert "budget_max_external_requests" in AUTHORIZATION_V2_PROPERTIES
    assert "budget_max_requests" not in AUTHORIZATION_V2_PROPERTIES


# --- ADR-048 (G3-3): route, policy and the narrow gate, on the real route -----


class _ContractProvider(_Provider):
    """Serves a contract the test chose, and counts every seam it is asked for."""

    def __init__(self, contract: dict) -> None:
        super().__init__()
        self._served = contract

    def client_contract(self) -> dict:
        self.contracts += 1
        return dict(self._served)


def _run_with_contract(tmp_path: Path, served: dict, *, repin: bool, **chain):
    """Drive the public v2 route with a chosen contract.

    ``repin=True`` points the authorization and the adapter qualification at the
    served contract's own digest. That is what isolates a refusal: with the pins
    matching, the digest comparisons cannot fire, so the only thing left that can
    refuse is the gate under test. With ``repin=False`` the digest comparisons
    *could* fire, which is what makes the ordering test meaningful.
    """
    provider = _ContractProvider(served)
    overrides = dict(chain)
    if repin:
        digest = sha256_bytes(canonical_json_bytes(served))
        overrides.setdefault("authorization", {})
        overrides.setdefault("qualification", {})
        overrides["authorization"] = {
            **overrides["authorization"],
            "provider_client_contract_sha256": digest,
        }
        overrides["qualification"] = {
            **overrides["qualification"],
            "execution_contract_sha256": digest,
        }
    with pytest.raises(ExtractionError) as caught:
        _run(tmp_path, provider=provider, chain_overrides=overrides)
    return caught.value, provider


def _assert_refused_with_nothing_spent(tmp_path: Path, provider, error, expected: str):
    """The whole matrix for a band-B refusal, in one place.

    What is asserted is only what the runner itself does. The seam method
    ``client_contract()`` **was** called -- it is how the contract got here -- and
    nothing is claimed about whether an arbitrary injected provider's version of
    that method is side-effect free. That is the canonical connector's property,
    not a runtime guarantee.
    """
    assert error.reason_code == expected
    assert provider.contracts == 1
    assert provider.permits == 1
    assert provider.revoked == 1
    assert provider.count_sends == 0
    assert provider.generate_sends == 0
    assert not (tmp_path / "run").exists()


_GATE_TEXT_FIELDS = (
    "api_version",
    "endpoint_match_mode",
    "endpoint_query_policy",
    "protocol_switch_policy",
    "rate_limit_policy_version",
    "retry_policy_version",
)


@pytest.mark.parametrize("field", _GATE_TEXT_FIELDS)
@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda c, f: c.pop(f), id="missing"),
        pytest.param(lambda c, f: c.__setitem__(f, 7), id="wrong-type"),
        pytest.param(lambda c, f: c.__setitem__(f, ""), id="empty"),
    ],
)
def test_v2_a_malformed_execution_field_is_refused_with_nothing_spent(
    tmp_path: Path, field, mutate
):
    served = _contract()
    mutate(served, field)
    error, provider = _run_with_contract(tmp_path, served, repin=True)
    _assert_refused_with_nothing_spent(
        tmp_path, provider, error, "client_contract_invalid"
    )


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda c: c.pop("operation_endpoints"), id="missing"),
        pytest.param(
            lambda c: c.__setitem__("operation_endpoints", ["a", "b"]), id="not-a-mapping"
        ),
        pytest.param(
            lambda c: c["operation_endpoints"].__setitem__("embed_content", "https://x/y"),
            id="extra-key",
        ),
        pytest.param(
            lambda c: c["operation_endpoints"].pop("count_tokens"), id="missing-key"
        ),
        pytest.param(
            lambda c: c["operation_endpoints"].__setitem__("count_tokens", 7),
            id="non-string-url",
        ),
        pytest.param(
            lambda c: c["operation_endpoints"].__setitem__("generate_content", ""),
            id="empty-url",
        ),
    ],
)
def test_v2_malformed_operation_endpoints_are_refused_with_nothing_spent(
    tmp_path: Path, mutate
):
    served = _contract()
    mutate(served)
    error, provider = _run_with_contract(tmp_path, served, repin=True)
    _assert_refused_with_nothing_spent(
        tmp_path, provider, error, "client_contract_invalid"
    )


def test_v2_the_shape_gate_is_reported_before_any_digest_comparison(tmp_path: Path):
    """Ordering, proved by making both defects true at once.

    The served contract is malformed **and** its digest is not the one the
    authorization pins. Both refusals are available; the shape gate runs first,
    so the reason code names the shape defect rather than the digest mismatch.
    Without the reordering this test would report
    ``authorization_client_contract_mismatch``.
    """
    served = _contract()
    served.pop("endpoint_match_mode")
    error, provider = _run_with_contract(tmp_path, served, repin=False)
    assert error.reason_code == "client_contract_invalid"
    assert error.reason_code != "authorization_client_contract_mismatch"
    _assert_refused_with_nothing_spent(
        tmp_path, provider, error, "client_contract_invalid"
    )


@pytest.mark.parametrize(
    ("side", "field", "value", "expected"),
    [
        pytest.param(
            "contract",
            "retry_policy_version",
            "retry_policy_v9",
            "retry_policy_version_mismatch",
            id="connector-retry-drift",
        ),
        pytest.param(
            "contract",
            "rate_limit_policy_version",
            "rate_limit_policy_v1",
            "rate_limit_policy_version_mismatch",
            id="connector-collection-namespace",
        ),
        pytest.param(
            "authorization",
            "retry_policy_version",
            "retry_policy_v2",
            "retry_policy_version_mismatch",
            id="authorization-retry-drift",
        ),
        pytest.param(
            "authorization",
            "rate_limit_policy_version",
            "rate_limit_policy_v1",
            "rate_limit_policy_version_mismatch",
            id="authorization-collection-namespace",
        ),
    ],
)
def test_v2_a_policy_version_this_build_does_not_implement_is_refused(
    tmp_path: Path, side, field, value, expected
):
    served = _contract()
    chain = {}
    if side == "contract":
        served[field] = value
    else:
        chain["authorization"] = {field: value}
    error, provider = _run_with_contract(tmp_path, served, repin=True, **chain)
    _assert_refused_with_nothing_spent(tmp_path, provider, error, expected)


def test_v2_two_artifacts_agreeing_on_a_wrong_policy_version_are_still_refused(
    tmp_path: Path,
):
    """The pin is what makes the agreement worthless."""
    served = _contract()
    served["retry_policy_version"] = "agreed_but_wrong_v1"
    error, provider = _run_with_contract(
        tmp_path,
        served,
        repin=True,
        authorization={"retry_policy_version": "agreed_but_wrong_v1"},
    )
    _assert_refused_with_nothing_spent(
        tmp_path, provider, error, "retry_policy_version_mismatch"
    )


def test_v2_policy_versions_are_reported_before_the_route(tmp_path: Path):
    """A drifted policy version would also change the routing digest.

    Both refusals are true at once here. Policy runs first, so the run reports
    the policy version rather than blaming the route for carrying it.
    """
    served = _contract()
    served["retry_policy_version"] = "retry_policy_v9"
    error, provider = _run_with_contract(tmp_path, served, repin=True)
    assert error.reason_code == "retry_policy_version_mismatch"
    assert error.reason_code != "routing_contract_mismatch"
    _assert_refused_with_nothing_spent(
        tmp_path, provider, error, "retry_policy_version_mismatch"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param(
            "routing_contract_id", "vertex_gemini_route@0.1.0", id="foreign-route-identity"
        ),
        pytest.param("routing_contract_sha256", "4" * 64, id="placeholder-digest"),
        pytest.param(
            "routing_contract_sha256",
            "b" * 64,
            id="digest-of-some-other-route",
        ),
    ],
)
def test_v2_an_enablement_pinning_a_different_route_is_refused(
    tmp_path: Path, field, value
):
    """``"4" * 64`` is here on purpose.

    Before ADR-048 that exact value satisfied the whole suite, because nothing
    produced the digest and the only check compared two caller-supplied records
    with each other. It is now a refusal on the real route.
    """
    error, provider = _run_with_contract(
        tmp_path, _contract(), repin=True, enablement={field: value}
    )
    _assert_refused_with_nothing_spent(
        tmp_path, provider, error, "routing_contract_mismatch"
    )


def test_v2_a_conforming_route_still_reaches_the_provider(tmp_path: Path):
    """The positive control: none of the three new gates blocks a good run."""
    provider = _Provider()
    outcome = _run(tmp_path, provider=provider)
    assert provider.contracts == 1
    assert provider.count_sends == 1
    assert provider.generate_sends == 1
    assert outcome.artifacts
