"""Stage-dispatched orchestration: the provider route and the non-run route.

The canonical input packet is persisted write-once **before either route
branches**, so the bytes a run was built from exist whether or not a provider
was ever called. On the non-run route the published run root holds exactly two
files and no ``extraction_run`` at all.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.provider_adapter import (
    ProviderRequest,
    ProviderResponse,
)
from dynamic_ai_products.extraction.raw_artifacts import (
    canonical_json_bytes,
    sha256_bytes,
    write_artifact,
)
from dynamic_ai_products.extraction.run_extraction import (
    CLIENT_CONTRACT_REFERENCE,
    ENVELOPES_REFERENCE,
    EXTRACTION_RUN_REFERENCE,
    NON_RUN_REFERENCE,
    PACKET_REFERENCE,
    PREDICTION_MANIFEST_REFERENCE,
    PROMPT_REFERENCE,
    RAW_REFERENCE,
    run_extraction_stage,
)
from dynamic_ai_products.extraction.manifests import (
    STAGE_OUTPUT_SCHEMA_SHA256 as _STAGE_OUTPUT_SCHEMA_SHA256,
    validate_provider_client_contract,
)
from dynamic_ai_products.providers.client_contract import build_client_contract

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
CUTOFF = "2024-12-31"
COMPANY = "CIK0001404655"
COVERAGE = {"reference": "coverage/source_family_coverage.json", "sha256": "d" * 64}
SOURCE_MANIFEST = {"reference": "snapshots/manifest.json", "sha256": "e" * 64}
DATES = {"sec-1": "2024-02-14", "sec-late": "2025-06-01"}
RAW_OUTPUT = b'{"observations":[]}'


class _FakeProvider:
    """Injected offline provider. Performs no I/O of any kind."""

    def __init__(self) -> None:
        self.requests: list[ProviderRequest] = []
        self.permit_calls = 0
        self.contract_calls = 0
        self.seen_digest = None

    def client_contract(self) -> dict:
        self.contract_calls += 1
        return build_client_contract(vertex_project="my-research-project")

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        self.permit_calls += 1
        self.seen_digest = authorization_sha256


    def revoke_run_permission(self) -> None:
        self.revoked = getattr(self, 'revoked', 0) + 1
    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(
            raw_bytes=RAW_OUTPUT,
            model_provider="fake",
            model_name="fake-offline",
            model_parameters={"temperature": 0},
            prompt_model_metadata={
                "model_name": "fake-offline",
                "prompt_sha256": request.prompt_sha256,
                "raw_capture_representation": "post_content_encoding_entity_body",
            },
        )


class _ExplodingProvider:
    """Every member must stay unreached on a non-run route."""

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        raise AssertionError("the non-run route must not ask for permission")


    def revoke_run_permission(self) -> None:
        self.revoked = getattr(self, 'revoked', 0) + 1
    def client_contract(self) -> dict:
        raise AssertionError("the non-run route must not request a contract")

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise AssertionError("the provider must not be called on a non-run route")


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
        "code_commit": "59c716a1da4529f4b390e44eee6389f3a2f35954",
        "run_created_at": "2026-07-29T00:00:00Z",
        "extraction_run_id": "ext-0001",
        "prediction_run_id": "pred-0001",
        "schema_root": str(SCHEMAS),
        "provider": _FakeProvider(),
    }
    kwargs.update(overrides)
    return run_extraction_stage(**kwargs)


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- the provider route -------------------------------------------------------


# --- the non-run route --------------------------------------------------------


def _non_run(tmp_path: Path, **overrides):
    kwargs = {
        "passages": [_passage("p-1", "late", source_id="sec-late"), _passage("p-2", "  ")],
        "provider": _ExplodingProvider(),
    }
    kwargs.update(overrides)
    return _run(tmp_path, **kwargs)


def test_a_non_run_publishes_exactly_two_files(tmp_path: Path):
    outcome = _non_run(tmp_path)
    assert outcome.verdict == "no_run"
    assert _files(outcome.run_root) == {PACKET_REFERENCE, NON_RUN_REFERENCE}


def test_a_non_run_writes_no_extraction_run_and_no_prediction_artifacts(tmp_path: Path):
    outcome = _non_run(tmp_path)
    published = _files(outcome.run_root)
    for reference in (
        EXTRACTION_RUN_REFERENCE,
        RAW_REFERENCE,
        ENVELOPES_REFERENCE,
        PREDICTION_MANIFEST_REFERENCE,
        PROMPT_REFERENCE,
    ):
        assert reference not in published


def test_the_packet_is_persisted_before_either_route_branches(tmp_path: Path):
    outcome = _non_run(tmp_path)
    persisted = (outcome.run_root / PACKET_REFERENCE).read_bytes()
    assert sha256_bytes(persisted) == outcome.packet_sha256
    assert json.loads(persisted)["passages"] == []


def test_the_non_run_record_pins_the_packet_bytes(tmp_path: Path):
    outcome = _non_run(tmp_path)
    record = json.loads((outcome.run_root / NON_RUN_REFERENCE).read_text())
    assert record["input_packet_reference"] == PACKET_REFERENCE
    assert record["input_packet_sha256"] == outcome.packet_sha256
    assert record["reason_code"] == "zero_admissible_passages"
    assert record["provider_called"] is False
    assert record["filter_ledger"]["input_passage_count"] == 2


def test_the_non_run_record_conforms_to_its_released_schema(tmp_path: Path):
    schema = json.loads((SCHEMAS / "extraction_non_run_record.schema.json").read_text())
    outcome = _non_run(tmp_path)
    Draft202012Validator(schema).validate(
        json.loads((outcome.run_root / NON_RUN_REFERENCE).read_text())
    )


def test_no_provider_is_needed_on_the_non_run_route(tmp_path: Path):
    outcome = _non_run(tmp_path, provider=None)
    assert outcome.verdict == "no_run"


def test_the_non_run_route_never_asks_the_provider_anything(tmp_path: Path):
    """No provider will be called, so requiring one would be theatre."""
    outcome = _non_run(tmp_path, provider=_ExplodingProvider())
    assert outcome.verdict == "no_run"
    assert len(_files(outcome.run_root)) == 2


# --- refusals ------------------------------------------------------------------


@pytest.mark.parametrize(
    "pin",
    [None, {}, {"reference": "x.json", "sha256": "f" * 64}, "anything", 7],
)
def test_a_caller_supplied_contract_pin_is_refused_with_zero_artifacts(
    tmp_path: Path, pin
):
    """The channel is closed, but the reason code stays reachable."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider_client_contract=pin)
    assert excinfo.value.reason_code == "contract_pin_forbidden"
    assert not (tmp_path / "run").exists()


def test_a_contract_pin_is_refused_on_the_non_run_route_too(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        _non_run(tmp_path, provider_client_contract=None)
    assert excinfo.value.reason_code == "contract_pin_forbidden"
    assert not (tmp_path / "run").exists()


def test_nothing_is_published_when_the_packet_itself_is_refused(tmp_path: Path):
    with pytest.raises(ExtractionError):
        _run(tmp_path, company_id="HUBS")
    assert not (tmp_path / "run").exists()


@pytest.mark.parametrize("field", ["code_commit", "run_created_at"])
def test_run_identity_must_be_injected(tmp_path: Path, field):
    with pytest.raises(ExtractionError) as excinfo:
        _non_run(tmp_path, **{field: "  "})
    assert excinfo.value.reason_code == "run_identity_invalid"


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


# --- Stage 06 and Stage 07 stay blocked until E-S (ADR-036, E-R) ---------------


@pytest.mark.parametrize("stage", ["capability_extraction", "task_extraction"])
def test_a_non_product_stage_without_parent_pins_stops_in_the_packet_preflight(
    tmp_path: Path, stage
):
    """Product-shaped inputs at a non-product stage: the **packet** refuses.

    This is a packet-preflight test, not an E-R test. Both stages require pinned
    snapshot and decision-set identities, so a product-shaped invocation cannot
    build a packet at all and stops at ``parent_context_missing`` -- before the
    permit handshake and before the renderer is ever consulted.

    The companion test below supplies fully valid parent context and proves the
    separate E-R route: the packet and governance preflight both succeed, the
    permit is activated, and the **renderer** then refuses.
    """

    class _Recorder:
        def __init__(self) -> None:
            self.activated = False
            self.revoked = 0
            self.completes = 0
            self.factory_entries = 0

        def assert_run_permitted(self, **kwargs) -> None:
            self.activated = True

        def revoke_run_permission(self) -> None:
            self.activated = False
            self.revoked += 1

        def client_contract(self) -> dict:
            return build_client_contract(vertex_project="my-research-project")

        def complete(self, request):
            self.completes += 1
            self.factory_entries += 1
            raise AssertionError("the provider must never be reached")

    provider = _Recorder()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, stage=stage, provider=provider)

    assert excinfo.value.reason_code == "parent_context_missing"
    # Zero artifacts: the run root was never created.
    assert not (tmp_path / "run").exists()
    # The provider was never called and the factory was never entered.
    assert provider.completes == 0
    assert provider.factory_entries == 0
    # No permit is left live. It was never activated at all: the packet build at
    # [B] precedes assert_run_permitted at [F], so there is nothing to revoke --
    # a stronger guarantee than "revoked on the way out".
    assert provider.activated is False
    assert provider.revoked == 0

# --- E-R blocks a FULLY VALID Stage 06 / Stage 07 invocation -------------------


def _write_parent_artifact(root: Path, reference: str, payload) -> dict:
    """Persist real bytes and return a real pin. No model_construct anywhere."""
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
            members("product_parent", products)
            + members("capability_parent", capabilities),
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


class _HandshakeRecorder:
    """Records how far a fully valid non-product invocation actually gets."""

    def __init__(self) -> None:
        self.permits = 0
        self.activated = False
        self.revoked = 0
        self.contracts = 0
        self.completes = 0
        self.factory_entries = 0

    def assert_run_permitted(self, **kwargs) -> None:
        self.permits += 1
        self.activated = True

    def revoke_run_permission(self) -> None:
        self.activated = False
        self.revoked += 1

    def client_contract(self) -> dict:
        self.contracts += 1
        # The same project the governance fixture pins, so the authorization's
        # client-contract digest matches and the run proceeds to the renderer.
        return build_client_contract(vertex_project="my-research-project")

    def complete(self, request):
        self.completes += 1
        self.factory_entries += 1
        raise AssertionError("the provider must never be reached")
