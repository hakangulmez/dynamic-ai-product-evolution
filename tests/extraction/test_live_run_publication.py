"""The four artifact counts, offline (ADR-035, ADR-036).

- **0** — every pre-authorization refusal; the run root is never created.
- **2** — the zero-admissible-passage non-run, which never consults governance,
  the meter, the provider, the prompt, or the schema pin.
- **7** — a terminal provider failure: five inputs (packet, rendered provider
  contents, prompt, client contract, authorization) plus an errored
  ``extraction_run`` and the provider-error record.
- **9** — an authorized successful run, adding the raw prediction, the envelopes,
  and the prediction manifest. Driven entirely by injected fakes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.evaluation.envelopes import PredictionArtifactManifest
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.manifests import (
    STAGE_OUTPUT_SCHEMA_SHA256 as _STAGE_OUTPUT_SCHEMA_SHA256,
    validate_provider_client_contract,
)
from dynamic_ai_products.extraction.provider_adapter import ProviderResponse
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
from dynamic_ai_products.providers.vertex_gemini import (
    RAW_CAPTURE_REPRESENTATION,
    VertexGeminiProvider,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"
COVERAGE = {"reference": "coverage/source_family_coverage.json", "sha256": "d" * 64}
SOURCE_MANIFEST = {"reference": "snapshots/manifest.json", "sha256": "e" * 64}
DATES = {"sec-1": "2024-02-14", "sec-late": "2025-06-01"}
PROJECT = "my-research-project"
CAPTURED = b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'


class _Provider:
    """Injected fake. It never builds a client, resolves ADC, or opens a socket."""

    def __init__(self, *, fail=None):
        self._fail = fail
        self.calls = 0
        self.seen_request = None
        self.seen_digest = None
        self.seen_allowlist = None
        self.seen_enablement_allowlist = None

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        self.seen_digest = authorization_sha256
        self.seen_allowlist = endpoint_allowlist
        self.seen_enablement_allowlist = enablement_endpoint_allowlist


    def revoke_run_permission(self) -> None:
        self.revoked = getattr(self, 'revoked', 0) + 1
    def client_contract(self) -> dict:
        return build_client_contract(vertex_project=PROJECT)

    def complete(self, request):
        self.calls += 1
        self.seen_request = request
        if self._fail is not None:
            raise self._fail
        return ProviderResponse(
            raw_bytes=CAPTURED,
            model_provider="google_vertex_ai",
            model_name="gemini-2.5-flash",
            model_parameters={"temperature": 0},
            prompt_model_metadata={
                "model_name": "gemini-2.5-flash",
                "prompt_sha256": request.prompt_sha256,
                "api_version": "v1",
                "raw_capture_representation": RAW_CAPTURE_REPRESENTATION,
            },
        )


class _Refusal(Exception):
    def __init__(self, reason_code, attempt_count):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.attempt_count = attempt_count


def _passage(passage_id="p-1", text="the product ships an assistant", source_id="sec-1"):
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
        "live_call_authorization_pin": write_governance_chain(governance_root),
        "budget_meter": FakeMeter(),
    }
    kwargs.update(overrides)
    return run_extraction_stage(**kwargs)


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- 9: the authorized successful run ----------------------------------------


def test_an_authorized_run_publishes_exactly_nine_artifacts(tmp_path: Path):
    outcome = _run(tmp_path)
    assert outcome.verdict == "provider_run_complete"
    assert _files(outcome.run_root) == {
        PACKET_REFERENCE,
        CONTENTS_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        AUTHORIZATION_REFERENCE,
        RAW_REFERENCE,
        EXTRACTION_RUN_REFERENCE,
        ENVELOPES_REFERENCE,
        PREDICTION_MANIFEST_REFERENCE,
    }
    assert set(outcome.artifacts) == _files(outcome.run_root)


def test_every_reported_digest_matches_the_persisted_bytes(tmp_path: Path):
    outcome = _run(tmp_path)
    for reference, digest in outcome.artifacts.items():
        assert sha256_bytes((outcome.run_root / reference).read_bytes()) == digest


def test_the_authorization_and_contents_are_bound_as_manifest_roles(tmp_path: Path):
    outcome = _run(tmp_path)
    manifest = json.loads((outcome.run_root / PREDICTION_MANIFEST_REFERENCE).read_text())
    PredictionArtifactManifest.model_validate(manifest)
    pinned = {e["reference"]: e["sha256"] for e in manifest["source_artifacts"]}
    assert len(pinned) == 8
    assert pinned[AUTHORIZATION_REFERENCE] == outcome.artifacts[AUTHORIZATION_REFERENCE]


def test_the_persisted_authorization_conforms_to_its_released_schema(tmp_path: Path):
    outcome = _run(tmp_path)
    schema = json.loads((SCHEMAS / "live_call_authorization.schema.json").read_text())
    payload = json.loads((outcome.run_root / AUTHORIZATION_REFERENCE).read_text())
    Draft202012Validator(schema).validate(payload)


def test_the_capture_representation_is_hash_bound_through_the_manifest(tmp_path: Path):
    """Reachable from the manifest by digest, not merely asserted in an ADR."""
    outcome = _run(tmp_path)
    manifest = json.loads((outcome.run_root / PREDICTION_MANIFEST_REFERENCE).read_text())
    envelopes_bytes = (outcome.run_root / ENVELOPES_REFERENCE).read_bytes()
    assert manifest["envelopes_sha256"] == sha256_bytes(envelopes_bytes)
    envelope = json.loads(envelopes_bytes.decode("utf-8").strip())
    assert (
        envelope["prompt_model_metadata"]["raw_capture_representation"]
        == "post_content_encoding_entity_body"
    )


def test_the_raw_prediction_holds_the_captured_bytes(tmp_path: Path):
    outcome = _run(tmp_path)
    assert (outcome.run_root / RAW_REFERENCE).read_bytes() == CAPTURED


def test_the_runner_hands_the_provider_the_verified_digest(tmp_path: Path):
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


def test_the_meter_and_the_provider_see_the_same_request_object(tmp_path: Path):
    provider = _Provider()
    meter = FakeMeter()
    _run(tmp_path, provider=provider, budget_meter=meter)
    assert meter.seen_request is provider.seen_request


# --- 7: terminal provider failure --------------------------------------------


def test_a_terminal_failure_publishes_exactly_seven_artifacts(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_Provider(fail=_Refusal("vertex_unavailable", 3)))
    assert excinfo.value.reason_code == "vertex_unavailable"
    assert _files(tmp_path / "run") == {
        PACKET_REFERENCE,
        CONTENTS_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        AUTHORIZATION_REFERENCE,
        EXTRACTION_RUN_REFERENCE,
        PROVIDER_ERROR_REFERENCE,
    }


def test_a_terminal_failure_produces_no_prediction_evidence(tmp_path: Path):
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=_Provider(fail=_Refusal("adc_expired", 1)))
    published = _files(tmp_path / "run")
    for absent in (RAW_REFERENCE, ENVELOPES_REFERENCE, PREDICTION_MANIFEST_REFERENCE):
        assert absent not in published


def test_an_attempt_count_above_the_cap_is_recorded_as_a_budget_violation(tmp_path: Path):
    """The provider claimed more attempts than the budget authorized."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_Provider(fail=_Refusal("vertex_unavailable", 99)))
    assert excinfo.value.reason_code == "provider_response_unusable"
    record = json.loads((tmp_path / "run" / EXTRACTION_RUN_REFERENCE).read_text())
    assert record["error_count"] == 3


# --- 2: the non-run route -----------------------------------------------------


def test_the_non_run_route_publishes_exactly_two_artifacts(tmp_path: Path):
    outcome = _run(
        tmp_path, passages=[_passage("p-1", "late", "sec-late")]
    )
    assert outcome.verdict == "no_run"
    assert _files(outcome.run_root) == {PACKET_REFERENCE, NON_RUN_REFERENCE}


def test_the_non_run_route_consults_no_governance_meter_or_provider(tmp_path: Path):
    """No provider will be called, so requiring any of them would be theatre."""

    class _Exploding:
        def assert_run_permitted(
            self, *, authorization_sha256=None, endpoint_allowlist=None,
            enablement_endpoint_allowlist=None,
        ):
            raise AssertionError("the non-run route must not ask for permission")


        def revoke_run_permission(self) -> None:
            self.revoked = getattr(self, 'revoked', 0) + 1
        def client_contract(self):
            raise AssertionError("the non-run route must not request a contract")

        def complete(self, request):
            raise AssertionError("the non-run route must not call a provider")

    outcome = _run(
        tmp_path,
        passages=[_passage("p-1", "late", "sec-late")],
        provider=_Exploding(),
        governance_artifact_root=None,
        live_call_authorization_pin=None,
        budget_meter=None,
    )
    assert outcome.verdict == "no_run"
    assert len(_files(outcome.run_root)) == 2


# --- 0: pre-authorization refusals -------------------------------------------


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


@pytest.mark.parametrize(
    "overrides,expected",
    [
        ({"provider": None}, "provider_required"),
        ({"provider": object()}, "provider_protocol_invalid"),
        ({"budget_meter": None}, "budget_meter_unavailable"),
        ({"budget_meter": object()}, "budget_meter_protocol_invalid"),
        ({"governance_artifact_root": None}, "governance_root_required"),
        ({"live_call_authorization_pin": None}, "governance_root_required"),
        ({"provider_client_contract": None}, "contract_pin_forbidden"),
        ({"provider_client_contract": {"reference": "x", "sha256": "f" * 64}},
         "contract_pin_forbidden"),
    ],
)
def test_every_pre_authorization_refusal_creates_nothing(
    tmp_path: Path, monkeypatch, overrides, expected
):
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, **overrides)
    assert excinfo.value.reason_code == expected
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_a_schema_pin_mismatch_precedes_the_provider_call(tmp_path: Path, monkeypatch):
    drifted = tmp_path / "drifted"
    drifted.mkdir()
    (drifted / "product_observation.schema.json").write_bytes(b"{}\n")
    provider = _Provider()
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, schema_root=str(drifted), provider=provider)
    assert excinfo.value.reason_code == "schema_pin_mismatch"
    assert provider.calls == 0
    assert counter[0] == 0


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


# --- the runner binds the authorization allowlist to the connector -------------


def test_the_runner_hands_the_provider_the_authorized_allowlist(tmp_path: Path):
    provider = _Provider()
    _run(tmp_path, provider=provider)
    assert provider.seen_allowlist == tuple(ENDPOINT_ALLOWLIST)


def test_a_connector_configured_for_a_broader_allowlist_is_refused(
    tmp_path: Path, monkeypatch
):
    """The defect this closes: correct digest and cap, wrong endpoint set."""
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(governance_root)
    broader = tuple(ENDPOINT_ALLOWLIST) + (
        "https://us-central1-aiplatform.googleapis.com/v1",
    )
    provider = VertexGeminiProvider(
        vertex_project=PROJECT,
        expected_authorization_sha256=pin["sha256"],
        max_provider_requests=3,
        endpoint_allowlist=broader,
    )
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    with pytest.raises(ExtractionError) as excinfo:
        _run(
            tmp_path,
            provider=provider,
            governance_artifact_root=governance_root,
            live_call_authorization_pin=pin,
        )
    assert excinfo.value.reason_code == "live_call_not_authorized"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_a_connector_configured_for_a_different_allowlist_is_refused(
    tmp_path: Path, monkeypatch
):
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(governance_root)
    provider = VertexGeminiProvider(
        vertex_project=PROJECT,
        expected_authorization_sha256=pin["sha256"],
        max_provider_requests=3,
        endpoint_allowlist=("https://europe-west4-aiplatform.googleapis.com/v1/projects",),
    )
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    with pytest.raises(ExtractionError) as excinfo:
        _run(
            tmp_path,
            provider=provider,
            governance_artifact_root=governance_root,
            live_call_authorization_pin=pin,
        )
    assert excinfo.value.reason_code == "live_call_not_authorized"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


def test_an_equivalent_normalized_allowlist_activates_through_the_runner(tmp_path: Path):
    """Semantic equality, so a differently written but identical set activates."""
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(
        governance_root,
        authorization={
            "endpoint_allowlist": [
                "https://US-CENTRAL1-AIPLATFORM.googleapis.com.:443/v1/./projects"
            ]
        },
    )
    provider = VertexGeminiProvider(
        vertex_project=PROJECT,
        expected_authorization_sha256=pin["sha256"],
        max_provider_requests=3,
        endpoint_allowlist=tuple(ENDPOINT_ALLOWLIST),
        client_factory=None,
    )
    # The handshake passes; the call itself then refuses because no factory is
    # injected and E-L must reach no real SDK in a test.
    with pytest.raises(ExtractionError):
        _run(
            tmp_path,
            provider=provider,
            governance_artifact_root=governance_root,
            live_call_authorization_pin=pin,
        )
    # Seven artifacts: the handshake was accepted and the terminal route ran.
    assert len(_files(tmp_path / "run")) == 7


@pytest.mark.parametrize(
    "entries",
    [
        [],
        ["not-a-url"],
        ["http://us-central1-aiplatform.googleapis.com/v1/projects"],
        [
            "https://us-central1-aiplatform.googleapis.com/v1/projects",
            "https://US-CENTRAL1-AIPLATFORM.googleapis.com:443/v1/projects",
        ],
    ],
)
def test_a_malformed_or_duplicate_authorization_allowlist_creates_nothing(
    tmp_path: Path, monkeypatch, entries
):
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(
        governance_root, authorization={"endpoint_allowlist": entries}
    )
    provider = VertexGeminiProvider(
        vertex_project=PROJECT,
        expected_authorization_sha256=pin["sha256"],
        max_provider_requests=3,
        endpoint_allowlist=tuple(ENDPOINT_ALLOWLIST),
    )
    counter = _count_mkdir(monkeypatch, tmp_path / "run")
    with pytest.raises(ExtractionError) as excinfo:
        _run(
            tmp_path,
            provider=provider,
            governance_artifact_root=governance_root,
            live_call_authorization_pin=pin,
        )
    assert excinfo.value.reason_code == "live_call_not_authorized"
    assert not (tmp_path / "run").exists()
    assert counter[0] == 0


# --- no post-handshake refusal leaves a spendable permit (v4.6) ----------------
#
# The permit outlives the client contract, the qualification's execution
# contract, the prompt, the meter, the budget, the run root, and the artifact
# writes. Any of those may refuse, so the orchestrator revokes on every exit.


class _PermitProbe:
    """A conforming provider that reports whether its permit is still live."""

    def __init__(self, *, contract_override=None):
        self._contract_override = contract_override
        self.activated = False
        self.revoked = 0
        self.factory_entries = 0

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        self.activated = True

    def revoke_run_permission(self) -> None:
        self.activated = False
        self.revoked += 1

    def client_contract(self) -> dict:
        if self._contract_override is not None:
            return self._contract_override
        return build_client_contract(vertex_project=PROJECT)

    def complete(self, request):
        # Stands in for the factory: reaching here means a permit was spendable.
        self.factory_entries += 1
        if not self.activated:
            raise _Refusal("live_call_not_authorized", 1)
        raise _Refusal("vertex_unavailable", 1)


def _post_handshake_refusal(tmp_path: Path, expected: str, **overrides):
    provider = overrides.pop("provider", None) or _PermitProbe()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider, **overrides)
    assert excinfo.value.reason_code == expected
    # The handshake succeeded, so the permit existed and must now be gone.
    assert provider.activated is False
    assert provider.revoked >= 1
    assert provider.factory_entries == 0
    return provider


def test_a_client_contract_mismatch_leaves_no_permit(tmp_path: Path):
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(
        governance_root,
        authorization={"provider_client_contract_sha256": "0" * 64},
    )
    _post_handshake_refusal(
        tmp_path,
        "authorization_client_contract_mismatch",
        governance_artifact_root=governance_root,
        live_call_authorization_pin=pin,
    )


def test_a_qualification_execution_contract_mismatch_leaves_no_permit(tmp_path: Path):
    """The reproduction from the review: this refusal is after the handshake."""
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(
        governance_root, qualification={"execution_contract_sha256": "9" * 64}
    )
    _post_handshake_refusal(
        tmp_path,
        "governance_record_not_effective",
        governance_artifact_root=governance_root,
        live_call_authorization_pin=pin,
    )


def test_a_prompt_failure_leaves_no_permit(tmp_path: Path):
    _post_handshake_refusal(
        tmp_path, "prompt_invalid", repo_root=tmp_path / "no-prompts"
    )


def test_a_meter_refusal_leaves_no_permit(tmp_path: Path):
    _post_handshake_refusal(
        tmp_path,
        "budget_input_tokens_exceeded",
        budget_meter=FakeMeter(refuse="budget_input_tokens_exceeded"),
    )


def test_a_budget_refusal_leaves_no_permit(tmp_path: Path):
    governance_root = tmp_path / "governance-override"
    pin = write_governance_chain(
        governance_root, authorization={"budget_max_output_tokens": 1}
    )
    provider = _PermitProbe()
    with pytest.raises(ExtractionError) as excinfo:
        _run(
            tmp_path,
            provider=provider,
            governance_artifact_root=governance_root,
            live_call_authorization_pin=pin,
        )
    # The budget arithmetic runs before the handshake, so no permit was granted.
    assert excinfo.value.reason_code == "budget_insufficient"
    assert provider.activated is False
    assert provider.factory_entries == 0


def test_a_meter_identity_mismatch_leaves_no_permit(tmp_path: Path):
    provider = _PermitProbe()
    with pytest.raises(ExtractionError) as excinfo:
        _run(
            tmp_path,
            provider=provider,
            budget_meter=FakeMeter(identity="some-other-meter"),
        )
    assert excinfo.value.reason_code == "budget_meter_identity_mismatch"
    assert provider.activated is False
    assert provider.factory_entries == 0


def test_an_existing_run_root_leaves_no_permit(tmp_path: Path):
    (tmp_path / "run").mkdir()
    _post_handshake_refusal(tmp_path, "run_root_exists")


def test_a_symlinked_run_root_leaves_no_permit(tmp_path: Path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / "run").symlink_to(target)
    _post_handshake_refusal(tmp_path, "run_root_exists")


@pytest.mark.parametrize(
    "failing_reference", [PROMPT_REFERENCE, CLIENT_CONTRACT_REFERENCE]
)
def test_an_artifact_write_failure_leaves_no_permit(
    tmp_path: Path, monkeypatch, failing_reference
):
    """A genuine write-path failure, after the clean run root has been created.

    The earlier version of this test pre-created ``run/inputs``, so
    ``_require_absent_run_root`` refused with ``run_root_exists`` before any
    artifact write was attempted — it never exercised the write path at all, and
    its monkeypatch argument went unused.
    """
    from dynamic_ai_products.extraction import run_extraction

    attempted: list[str] = []
    real_write = run_extraction.write_artifact

    def failing_write(root, reference, payload):
        attempted.append(reference)
        if reference == failing_reference:
            raise ExtractionError(
                "simulated write failure", reason_code="write_error"
            )
        return real_write(root, reference, payload)

    monkeypatch.setattr(run_extraction, "write_artifact", failing_write)

    provider = _PermitProbe()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider)

    # The intended write path was reached, not the run-root guard.
    assert excinfo.value.reason_code == "write_error"
    assert excinfo.value.reason_code != "run_root_exists"
    assert attempted[0] == PACKET_REFERENCE
    assert failing_reference in attempted
    # The run root was created cleanly and the packet write was attempted first.
    assert (tmp_path / "run").is_dir()
    # No permit survives, and the provider was never called.
    assert provider.activated is False
    assert provider.revoked >= 1
    assert provider.factory_entries == 0


def test_a_terminal_provider_failure_finishes_with_no_reusable_permit(tmp_path: Path):
    provider = _PermitProbe()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider)
    assert excinfo.value.reason_code == "vertex_unavailable"
    assert provider.factory_entries == 1
    assert provider.activated is False
    assert provider.revoked >= 1


def test_a_successful_run_finishes_with_no_reusable_permit(tmp_path: Path):
    provider = _Provider()
    outcome = _run(tmp_path, provider=provider)
    assert outcome.verdict == "provider_run_complete"
    assert getattr(provider, "revoked", 0) >= 1


def test_revocation_is_idempotent_and_needs_no_sdk():
    """Clearing a field is the whole operation, so it cannot fail."""
    import sys

    before = {name for name in sys.modules if name.startswith("google")}
    provider = VertexGeminiProvider(
        vertex_project=PROJECT,
        expected_authorization_sha256="a" * 64,
        max_provider_requests=3,
        endpoint_allowlist=tuple(ENDPOINT_ALLOWLIST),
    )
    provider.assert_run_permitted(
        authorization_sha256="a" * 64,
        endpoint_allowlist=tuple(ENDPOINT_ALLOWLIST),
        enablement_endpoint_allowlist=tuple(ENDPOINT_ALLOWLIST),
    )
    for _ in range(3):
        provider.revoke_run_permission()
    with pytest.raises(Exception) as excinfo:
        provider.complete(None)
    assert getattr(excinfo.value, "reason_code", None) == "live_call_not_authorized"
    assert {name for name in sys.modules if name.startswith("google")} == before


class _BadRevoke(_PermitProbe):
    """Non-conforming: revocation is required to be infallible, and this is not."""

    def revoke_run_permission(self) -> None:
        raise RuntimeError("revocation exploded with secret-looking text")


def test_a_revocation_failure_never_masks_the_original_refusal(tmp_path: Path):
    """prompt_invalid plus a failed revocation still reports prompt_invalid."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_BadRevoke(), repo_root=tmp_path / "no-prompts")
    assert excinfo.value.reason_code == "prompt_invalid"
    assert "revocation exploded" not in str(excinfo.value)


def test_a_revocation_failure_on_the_success_path_is_not_a_success(tmp_path: Path):
    """Nothing else was failing, so the revocation failure *is* the failure.

    Before the exception-state fix this was silently swallowed and the run
    returned a successful outcome while leaving a live permit behind.
    """

    class _SucceedThenFailRevoke(_Provider):
        def revoke_run_permission(self) -> None:
            raise RuntimeError("revocation exploded with secret-looking text")

    provider = _SucceedThenFailRevoke()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider)
    assert excinfo.value.reason_code == "provider_refused"
    assert "revocation exploded" not in str(excinfo.value)
    # The provider really did run: the failure is the revocation, not the call.
    assert provider.calls == 1


def test_a_standalone_revocation_failure_raises_provider_refused():
    """No original failure in flight, so the revocation failure surfaces."""
    from dynamic_ai_products.extraction.run_extraction import _revoke_run_permission

    with pytest.raises(ExtractionError) as excinfo:
        _revoke_run_permission(_BadRevoke())
    assert excinfo.value.reason_code == "provider_refused"
    assert "revocation exploded" not in str(excinfo.value)


def test_an_in_flight_failure_is_preserved_over_a_revocation_failure():
    """Direct proof of the branch the old sys.exc_info() check could never reach."""
    from dynamic_ai_products.extraction.run_extraction import _revoke_run_permission

    with pytest.raises(ExtractionError) as excinfo:
        try:
            raise ExtractionError("the real reason", reason_code="schema_pin_mismatch")
        finally:
            _revoke_run_permission(_BadRevoke())
    assert excinfo.value.reason_code == "schema_pin_mismatch"


# ---------------------------------------------------------------------------
# Returned-digest integrity on the authorized route (E-L v4.6.2).
#
# The packet and client-contract writes were once bound to their expected digests
# by ``assert``, which ``python -O`` strips: the packet ``assert`` contained the
# write call itself, so under ``-O`` no packet was persisted, and the contract
# ``assert`` was a fail-closed integrity check that simply disappeared. Both are
# now unconditional writes plus ordinary ``if`` comparisons, and both mismatches
# must fail closed *after* a successful handshake without spending the permit.
# ---------------------------------------------------------------------------


def test_the_authorized_route_really_persists_the_packet_it_pinned(tmp_path: Path):
    """The write executes and the bytes on disk match the pinned digest."""
    import hashlib
    import json

    provider = _Provider()
    outcome = _run(tmp_path, provider=provider)
    assert outcome.verdict == "provider_run_complete"
    packet_file = Path(outcome.run_root) / PACKET_REFERENCE
    assert packet_file.is_file()
    on_disk = hashlib.sha256(packet_file.read_bytes()).hexdigest()
    manifest = json.loads(
        (Path(outcome.run_root) / PREDICTION_MANIFEST_REFERENCE).read_text()
    )
    pinned = {
        entry["reference"]: entry["sha256"] for entry in manifest["source_artifacts"]
    }
    assert pinned[PACKET_REFERENCE] == on_disk


@pytest.mark.parametrize(
    "corrupted_reference", [PACKET_REFERENCE, CLIENT_CONTRACT_REFERENCE]
)
def test_a_returned_digest_mismatch_fails_closed(
    tmp_path: Path, monkeypatch, corrupted_reference
):
    """A writer that reports a digest other than the pinned one stops the run.

    Both cases are post-handshake, so the permit must not survive and the
    provider must never be reached.
    """
    from dynamic_ai_products.extraction import run_extraction

    attempted: list[str] = []
    real_write = run_extraction.write_artifact

    def lying_write(root, reference, payload):
        attempted.append(reference)
        observed = real_write(root, reference, payload)
        if reference == corrupted_reference:
            # A digest of the right shape but the wrong value.
            return "0" * 64
        return observed

    monkeypatch.setattr(run_extraction, "write_artifact", lying_write)

    provider = _PermitProbe()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider)

    assert excinfo.value.reason_code == "write_error"
    assert excinfo.value.reason_code != "run_root_exists"
    assert corrupted_reference in attempted
    # The mismatching digest is never reported back through the boundary.
    assert "0" * 64 not in str(excinfo.value)
    # Post-handshake: the permit is revoked and the provider is never reached.
    assert provider.activated is False
    assert provider.revoked >= 1
    assert provider.factory_entries == 0


def test_the_digest_guard_is_reached_only_after_the_write_happened(
    tmp_path: Path, monkeypatch
):
    """Ordering proof: the artifact exists on disk before the guard refuses.

    Under the stripped ``assert`` the file would not exist at all, so this
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

    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=_PermitProbe())
    assert excinfo.value.reason_code == "write_error"
    assert seen_on_disk[PACKET_REFERENCE] is True


def test_the_digest_guard_is_a_plain_function_not_an_assert():
    """Directly exercised, so ``-O`` cannot make it vacuous."""
    from dynamic_ai_products.extraction.run_extraction import _require_written_digest

    _require_written_digest("a" * 64, "a" * 64)  # equal: silent
    with pytest.raises(ExtractionError) as excinfo:
        _require_written_digest("a" * 64, "b" * 64)
    assert excinfo.value.reason_code == "write_error"
    assert "a" * 64 not in str(excinfo.value)
    assert "b" * 64 not in str(excinfo.value)
