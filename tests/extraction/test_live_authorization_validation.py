"""The three-ring SPEC-027 chain, scope equality, and the governance root.

Every refusal here happens in the pre-run gate, so the run root is never
created. Nothing in this module touches a network, an SDK, or ADC.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.manifests import (
    STAGE_OUTPUT_SCHEMA_SHA256 as _STAGE_OUTPUT_SCHEMA_SHA256,
    AUTHORIZATION_PROPERTIES,
    ENABLEMENT_STATUS_FOR_ROLLOUT,
    GOVERNANCE_SCHEMA_VERSION,
    STAGE_OUTPUT_CONTRACT_ID,
    ENABLEMENT_CONTRACT,
    ENABLEMENT_PROPERTIES,
    LIVE_AUTHORIZATION_CONTRACT,
    PROVIDER_DECLARED_MAX_OUTPUT_TOKENS_PIN,
    PROVIDER_MAX_ATTEMPTS_PIN,
    PROVIDER_RETRY_DELAYS_PIN,
    PROVIDER_TIMEOUT_SECONDS_PIN,
    PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS,
    QUALIFICATION_CONTRACT,
    QUALIFICATION_PROPERTIES,
    validate_provider_client_contract,
)
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.run_extraction import (
    CLIENT_CONTRACT_REFERENCE,
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
    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        self.seen_digest = authorization_sha256


    def revoke_run_permission(self) -> None:
        self.revoked = getattr(self, 'revoked', 0) + 1
    def client_contract(self) -> dict:
        return build_client_contract(vertex_project=PROJECT)

    def complete(self, request):
        raise AssertionError("no provider call should be reached in this module")


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
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, **kwargs)
    assert excinfo.value.reason_code == expected
    assert not (tmp_path / "run").exists()
    return excinfo.value


# --- the governance root is explicit -----------------------------------------


def test_there_is_no_cwd_or_environment_fallback():
    """The root is a parameter, not a discovered path.

    The check is on executable identifiers, not on source text: the refusal
    message legitimately says "there is no ambient, cwd, or environment
    fallback", and a substring scan would flag the very sentence that documents
    the guarantee.
    """
    import ast
    import inspect

    from dynamic_ai_products.extraction import run_extraction

    tree = ast.parse(inspect.getsource(run_extraction))
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    assert not (names & {"cwd", "getcwd", "environ", "getenv", "expandvars"})


# --- the three rings ----------------------------------------------------------


# --- scope equality -----------------------------------------------------------


def test_a_corpus_scope_mismatch_is_refused_at_the_validator():
    """The released enum admits only one scope, so a mismatch is unrepresentable
    in a schema-valid artifact; the validator is exercised directly instead."""
    from dynamic_ai_products.extraction.manifests import validate_authorization_scope

    with pytest.raises(ExtractionError) as excinfo:
        validate_authorization_scope(
            authorization={
                "stage": "product_extraction",
                "company_id": COMPANY,
                "observation_cutoff_date": CUTOFF,
                "corpus_scope": "full_universe",
                "effective_at": "2026-01-01T00:00:00Z",
                "expires_at": "2027-01-01T00:00:00Z",
            },
            stage="product_extraction",
            company_id=COMPANY,
            observation_cutoff_date=CUTOFF,
            corpus_scope="sec_only_partial",
            run_created_at="2026-07-29T00:00:00Z",
        )
    assert excinfo.value.reason_code == "authorization_scope_mismatch"


# --- client-contract byte identity -------------------------------------------


def test_the_pinned_contract_is_the_one_this_run_produces():
    contract = validate_provider_client_contract(
        build_client_contract(vertex_project=PROJECT)
    )
    assert CLIENT_CONTRACT_REFERENCE == "inputs/provider_client_contract.json"
    assert sha256_bytes(canonical_json_bytes(contract)) == _client_contract_digest()


# --- schema conformance and the closed pins ----------------------------------


@pytest.mark.parametrize(
    "stem,contract,properties",
    [
        ("adapter_qualification_record", QUALIFICATION_CONTRACT, QUALIFICATION_PROPERTIES),
        ("adapter_enablement_record", ENABLEMENT_CONTRACT, ENABLEMENT_PROPERTIES),
        ("live_call_authorization", LIVE_AUTHORIZATION_CONTRACT, AUTHORIZATION_PROPERTIES),
    ],
)
def test_each_schema_matches_its_code_property_set(stem, contract, properties):
    schema = json.loads((SCHEMAS / f"{stem}.schema.json").read_text())
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(properties)
    assert schema["properties"]["contract"]["const"] == contract


def test_the_persisted_chain_conforms_to_its_released_schemas(tmp_path: Path):
    governance_root = tmp_path / "governance-root"
    write_governance_chain(governance_root)
    for stem, reference in (
        ("adapter_qualification_record", GOV_QUALIFICATION_REFERENCE),
        ("adapter_enablement_record", GOV_ENABLEMENT_REFERENCE),
        ("live_call_authorization", GOV_AUTH_REFERENCE),
    ):
        schema = json.loads((SCHEMAS / f"{stem}.schema.json").read_text())
        payload = json.loads((governance_root / reference).read_text())
        Draft202012Validator(schema).validate(payload)


def test_the_closed_policy_pins_do_not_drift_from_providers():
    """extraction may not import providers, so the values are pinned and checked."""
    from dynamic_ai_products.providers import retry_policy as rp

    assert PROVIDER_MAX_ATTEMPTS_PIN == rp.RETRY_MAX_ATTEMPTS
    assert PROVIDER_TIMEOUT_SECONDS_PIN == rp.TIMEOUT_DURATION // 1000
    assert PROVIDER_RETRY_DELAYS_PIN == rp.RETRY_DELAYS_SECONDS
    assert PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS == (
        PROVIDER_MAX_ATTEMPTS_PIN * PROVIDER_TIMEOUT_SECONDS_PIN
        + sum(PROVIDER_RETRY_DELAYS_PIN)
    )
    from dynamic_ai_products.providers.client_contract import MODEL_PARAMETERS

    assert PROVIDER_DECLARED_MAX_OUTPUT_TOKENS_PIN == MODEL_PARAMETERS["max_output_tokens"]


def test_the_v2_contract_identity_pins_do_not_drift_from_the_provider_builder():
    """ADR-048. The schema-version pin is derived, never re-typed.

    Comparing ``CLIENT_CONTRACT_V2_SCHEMA_VERSION`` with a literal ``"0.2.0"``
    would be a second independent source and would stay green if the builder
    started emitting ``"0.3.0"`` -- precisely the drift this test exists to
    catch. There is no ``SCHEMA_VERSION`` constant on the providers side either:
    measured, the value lives only as a literal inside the builder's returned
    mapping. So the only drift-catching route is the builder's own output.

    The builder is pure: project/location grammar validation and string
    composition. No network, no filesystem, no clock, no credential. The
    synthetic project is the one this module already uses.
    """
    from dynamic_ai_products.extraction.manifests import (
        CLIENT_CONTRACT_V2_CONTRACT,
        CLIENT_CONTRACT_V2_SCHEMA_VERSION,
    )
    from dynamic_ai_products.providers.client_contract_v2 import (
        CLIENT_CONTRACT_V2_ID,
        build_client_contract_v2,
    )

    contract = build_client_contract_v2(vertex_project=PROJECT)
    assert CLIENT_CONTRACT_V2_SCHEMA_VERSION == contract["schema_version"]
    # Emitted identity and declared constant, both. If the builder ever stopped
    # using its own constant, the two would diverge and this would show it.
    assert CLIENT_CONTRACT_V2_CONTRACT == contract["contract"]
    assert CLIENT_CONTRACT_V2_CONTRACT == CLIENT_CONTRACT_V2_ID


def test_the_policy_version_pins_do_not_drift_from_providers():
    """ADR-048. Both policy versions, re-derived from their authoritative home.

    The rate-limit assertion carries a second job: ``collection.transport``
    declares a field of the same name with a *different* value for HTTP source
    retrieval. The inequality below states which namespace a model-execution run
    means, so the two can never be silently swapped.
    """
    from dynamic_ai_products.collection.transport import (
        RATE_LIMIT_POLICY_VERSION as COLLECTION_RATE_LIMIT_POLICY_VERSION,
    )
    from dynamic_ai_products.extraction.manifests import (
        PROVIDER_RATE_LIMIT_POLICY_VERSION_PIN,
        PROVIDER_RETRY_POLICY_VERSION_PIN,
    )
    from dynamic_ai_products.providers import retry_policy as rp

    assert PROVIDER_RETRY_POLICY_VERSION_PIN == rp.RETRY_POLICY_VERSION
    assert PROVIDER_RATE_LIMIT_POLICY_VERSION_PIN == rp.RATE_LIMIT_POLICY_VERSION
    assert PROVIDER_RATE_LIMIT_POLICY_VERSION_PIN != COLLECTION_RATE_LIMIT_POLICY_VERSION


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


# --- the validity window is chronological, not lexicographic ------------------
#
# Text comparison is wrong rather than merely imprecise: 2026-07-01T00:00:00Z and
# 2026-07-01T02:00:00+02:00 are the same instant but are not equal as strings,
# and an offset-bearing timestamp can sort on either side of a Z one regardless
# of chronology.


def _window_authorization(**overrides):
    base = {
        "stage": "product_extraction",
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "corpus_scope": "sec_only_partial",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def _check_window(authorization, run_created_at):
    from dynamic_ai_products.extraction.manifests import validate_authorization_scope

    validate_authorization_scope(
        authorization=authorization,
        stage="product_extraction",
        company_id=COMPANY,
        observation_cutoff_date=CUTOFF,
        corpus_scope="sec_only_partial",
        run_created_at=run_created_at,
    )


def _window_refused(authorization, run_created_at):
    with pytest.raises(ExtractionError) as excinfo:
        _check_window(authorization, run_created_at)
    assert excinfo.value.reason_code == "authorization_scope_mismatch"


@pytest.mark.parametrize(
    "effective,expires,instant",
    [
        # The same instant written three ways; all are in window.
        ("2026-07-01T00:00:00Z", "2027-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        ("2026-07-01T02:00:00+02:00", "2027-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        ("2026-07-01T00:00:00Z", "2027-07-01T00:00:00Z", "2026-07-01T02:00:00+02:00"),
        ("2026-06-30T22:00:00-02:00", "2027-07-01T00:00:00Z", "2026-07-01T00:00:00Z"),
        # An instant that sorts BEFORE effective_at as text but is after it in time.
        ("2026-07-02T00:00:00Z", "2027-07-01T00:00:00Z", "2026-07-02T03:00:00+02:00"),
    ],
)
def test_an_equivalent_instant_with_a_different_offset_is_accepted(
    effective, expires, instant
):
    _check_window(_window_authorization(effective_at=effective, expires_at=expires), instant)


@pytest.mark.parametrize(
    "instant",
    [
        "2026-06-30T23:59:59Z",
        "2027-07-01T00:00:01Z",
        "2030-01-01T00:00:00Z",
        "2020-01-01T00:00:00Z",
        # In window lexicographically against "2026-07-01..." but earlier in time.
        "2026-07-01T00:30:00+02:00",
    ],
)
def test_an_out_of_window_instant_is_refused(instant):
    _window_refused(_window_authorization(), instant)


def test_the_window_boundaries_are_inclusive():
    _check_window(_window_authorization(), "2026-07-01T00:00:00Z")
    _check_window(_window_authorization(), "2027-07-01T00:00:00Z")


@pytest.mark.parametrize(
    "value", ["2026-07-01T00:00:00", "2026-07-01 00:00:00", "2026-07-01"]
)
def test_a_timezone_naive_timestamp_is_refused(value):
    """Assuming UTC would silently move a boundary by an unknown amount."""
    _window_refused(_window_authorization(effective_at=value), "2026-07-29T00:00:00Z")
    _window_refused(_window_authorization(expires_at=value), "2026-07-29T00:00:00Z")
    _window_refused(_window_authorization(), value)


@pytest.mark.parametrize(
    "value", ["not-a-date", "", "  ", "2026-13-45T00:00:00Z", "26-07-01T00:00:00Z", None, 7]
)
def test_a_malformed_timestamp_is_refused(value):
    _window_refused(_window_authorization(effective_at=value), "2026-07-29T00:00:00Z")
    _window_refused(_window_authorization(expires_at=value), "2026-07-29T00:00:00Z")


@pytest.mark.parametrize("value", ["not-a-date", "", None, 7])
def test_a_malformed_run_instant_is_refused(value):
    _window_refused(_window_authorization(), value)


def test_an_inverted_window_is_refused_even_for_an_instant_between_them():
    """effective_at later than expires_at is never a usable authorization."""
    inverted = _window_authorization(
        effective_at="2027-01-01T00:00:00Z", expires_at="2026-01-01T00:00:00Z"
    )
    _window_refused(inverted, "2026-07-01T00:00:00Z")
    _window_refused(inverted, "2027-06-01T00:00:00Z")


def test_an_inverted_window_expressed_across_offsets_is_still_refused():
    _window_refused(
        _window_authorization(
            effective_at="2026-07-01T12:00:00+00:00",
            expires_at="2026-07-01T09:00:00-02:00",
        ),
        "2026-07-01T12:00:00Z",
    )


def test_a_zero_length_window_admits_only_that_instant():
    exact = _window_authorization(
        effective_at="2026-07-01T00:00:00Z", expires_at="2026-07-01T00:00:00Z"
    )
    _check_window(exact, "2026-07-01T02:00:00+02:00")
    _window_refused(exact, "2026-07-01T00:00:01Z")


def test_the_comparison_is_not_lexicographic():
    """A pair that text comparison gets wrong in both directions."""
    # As text "2026-07-01T00:00:00Z" > "2026-07-01T00:00:00+05:00", but the
    # offset-bearing instant is five hours EARLIER, so it is out of window.
    _window_refused(
        _window_authorization(effective_at="2026-07-01T00:00:00Z"),
        "2026-07-01T00:00:00+05:00",
    )
    # And the mirror: text says out, chronology says in.
    _check_window(
        _window_authorization(effective_at="2026-07-01T06:00:00Z"),
        "2026-07-01T09:00:00+02:00",
    )


# --- governing semantics of the upstream records (ADR-035, v4.5) ---------------
#
# A hash-valid chain proves the records are the ones that were pinned. It says
# nothing about whether they are in force. Every released const/enum is
# re-enforced by the loader because no schema file executes on this path.


def _ineffective(tmp_path: Path, **chain):
    return _refused(
        tmp_path, "governance_record_not_effective", chain_overrides=chain
    )


# (1) schema_version -- a structural violation, so it keeps the chain code.


def test_the_governance_schema_version_is_pinned_at_zero_one_zero():
    assert GOVERNANCE_SCHEMA_VERSION == "0.1.0"


# (2) qualification status and adapter family.


# (3) the closed rollout -> enablement-status mapping.


def test_the_rollout_mapping_is_closed():
    assert ENABLEMENT_STATUS_FOR_ROLLOUT == {
        "live_dev": "enabled_live_dev",
        "controlled_pilot": "enabled_pilot",
        "release_or_research_production": "enabled_release",
    }
    assert "full_scale" not in ENABLEMENT_STATUS_FOR_ROLLOUT
    assert "mock_only" not in ENABLEMENT_STATUS_FOR_ROLLOUT


# (4) the enablement window, and containment of the authorization window.


# (5) environment and rollout equality.


# (6) qualification execution contract == the actual client contract.


def test_the_qualified_digest_is_this_run_s_client_contract():
    from dynamic_ai_products.extraction.manifests import (
        validate_qualification_execution_contract,
    )

    contract = validate_provider_client_contract(
        build_client_contract(vertex_project=PROJECT)
    )
    validate_qualification_execution_contract(
        qualification={
            "execution_contract_id": contract["contract"],
            "execution_contract_sha256": _client_contract_digest(),
        },
        client_contract=contract,
        client_contract_sha256=_client_contract_digest(),
    )


# (7) stage and stage-output contract agreement.


def test_the_enforced_stage_output_sha_is_the_released_pin():
    assert _STAGE_OUTPUT_SCHEMA_SHA256["product_extraction"] == STAGE_OUTPUT_SHA


# --- every new refusal is pre-provider and zero-artifact ----------------------


# --- the stage-output contract identity is bound to the stage (v4.6) -----------
#
# Mutual agreement plus a correct released digest was not enough: two records
# could name the same arbitrary identity and the identity would assert nothing
# about which stage had been qualified.


def test_the_stage_output_identity_map_is_closed():
    """ADR-069 moves ``task_extraction`` to the @0.2.0 successor: the
    candidate-collection layer has validated task candidates against
    ``task_observation_v2.schema.json`` since ADR-068, and this identity must
    name the schema the stage actually validates against."""
    assert STAGE_OUTPUT_CONTRACT_ID == {
        "product_extraction": "product_observation@0.1.0",
        "capability_extraction": "capability_observation@0.1.0",
        "task_extraction": "task_observation@0.2.0",
    }


@pytest.mark.parametrize(
    "stage,expected_id",
    [
        ("product_extraction", "product_observation@0.1.0"),
        ("capability_extraction", "capability_observation@0.1.0"),
        ("task_extraction", "task_observation@0.2.0"),
    ],
)
def test_every_stage_requires_its_own_output_contract_identity(stage, expected_id):
    """All three mappings, exercised through the validator directly."""
    from dynamic_ai_products.extraction.manifests import (
        STAGE_OUTPUT_SCHEMA_SHA256,
        validate_governance_semantics,
    )

    sha = STAGE_OUTPUT_SCHEMA_SHA256[stage]
    base_enablement = {
        "rollout_state": "live_dev",
        "enablement_status": "enabled_live_dev",
        "deployment_environment_id": "dev-local",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
        "stage": stage,
        "stage_output_contract_id": expected_id,
        "stage_output_contract_sha256": sha,
    }
    base_qualification = {
        "adapter_family": "model_execution",
        "qualification_status": "qualified",
        "stage_output_contract_id": expected_id,
        "stage_output_contract_sha256": sha,
    }
    base_authorization = {
        "rollout_state": "live_dev",
        "deployment_environment_id": "dev-local",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
    }
    validate_governance_semantics(
        authorization=base_authorization,
        enablement=base_enablement,
        qualification=base_qualification,
        stage=stage,
        run_created_at="2026-07-29T00:00:00Z",
        stage_output_schema_sha256=sha,
    )
    # Another stage's identity is refused even with that stage's own digest.
    other = next(v for k, v in STAGE_OUTPUT_CONTRACT_ID.items() if k != stage)
    with pytest.raises(ExtractionError) as excinfo:
        validate_governance_semantics(
            authorization=base_authorization,
            enablement={**base_enablement, "stage_output_contract_id": other},
            qualification={**base_qualification, "stage_output_contract_id": other},
            stage=stage,
            run_created_at="2026-07-29T00:00:00Z",
            stage_output_schema_sha256=sha,
        )
    assert excinfo.value.reason_code == "governance_record_not_effective"
