"""The E-M phase order, the capture sink, and the budget arithmetic end to end.

Everything runs offline with an injected fake connector: no client is built, no
credential is read, no socket is opened, and nothing is written outside
``tmp_path``.

The load-bearing test is :func:`test_a_persistence_failure_permits_no_further_send`.
An earlier design had the connector finish every retry and hand the runner a
bundle of captures afterwards, which makes that rule unenforceable — by the time
the failure is visible, the later sends have already happened. Here the sink is
called after each attempt and before the next, so the send counter is the proof.
"""

from __future__ import annotations

import inspect
import json
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.count_reconciliation import (
    reserve_cost_microdollars,
    usage_cost_microdollars,
)
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.execution_outcome import (
    COUNT_RAW_REFERENCE,
    RAW_PREDICTION_REFERENCE,
    generate_attempt_reference,
)
from dynamic_ai_products.extraction.routing_contract import (
    ROUTING_CONTRACT_ID,
    derive_routing_contract,
)
from dynamic_ai_products.extraction.manifests import (
    PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS_V2,
    resolve_attempt_cap_v2,
    wall_clock_floor_for_cap,
)
from dynamic_ai_products.extraction.prediction_manifest import (
    REQUIRED_SOURCE_ARTIFACT_ROLES,
    REQUIRED_SOURCE_ARTIFACT_ROLES_V2,
)
from dynamic_ai_products.extraction.provider_adapter import (
    PROVIDER_PROTOCOL_VERSION_V8,
    BudgetAdmission,
    CaptureSinkError,
    ProviderRequest,
    client_contract_digest,
    provider_request_digest,
    require_provider,
    require_provider_v8,
)
from dynamic_ai_products.extraction.manifests import STAGE_OUTPUT_SCHEMA_SHA256
from dynamic_ai_products.extraction.prompt_qualification import (
    DECLARED_NON_CLAIMS,
    GOVERNING_SPEC_REFERENCE,
)
from dynamic_ai_products.extraction.prompts import load_prompt
from dynamic_ai_products.extraction.provider_adapter import ProviderResponse
from dynamic_ai_products.extraction.run_extraction import (
    AUTHORIZATION_REFERENCE,
    CLIENT_CONTRACT_REFERENCE,
    CONTENTS_REFERENCE,
    ENVELOPES_REFERENCE,
    EXECUTION_OUTCOME_REFERENCE,
    EXTRACTION_RUN_REFERENCE,
    PACKET_REFERENCE,
    PREDICTION_MANIFEST_REFERENCE,
    PROMPT_REFERENCE,
    PROVIDER_ERROR_REFERENCE,
    build_capture_sink,
    run_extraction_stage,
    run_extraction_stage_v2,
    _run_two_operation_measurement,
)
from dynamic_ai_products.extraction.raw_artifacts import (
    canonical_json_bytes,
    sha256_bytes,
    write_artifact,
)
from dynamic_ai_products.providers.client_contract_v2 import (
    build_client_contract_v2,
    build_operation_endpoints,
)
from jsonschema import Draft202012Validator

CONTENTS = "rendered document"
MAX_OUTPUT_TOKENS = 8192
# The helper takes the digest as an argument; the production entry point derives
# it. Nothing here may treat the contents digest as the identity.
HELPER_DIGEST = "f" * 64


def request() -> ProviderRequest:
    return ProviderRequest(
        stage="product_extraction",
        rendered_contents=CONTENTS,
        rendered_contents_sha256=sha256_bytes(CONTENTS.encode("utf-8")),
        prompt_sha256="a" * 64,
        input_packet_sha256="b" * 64,
    )


def authorization(external_requests=4, wall_clock=None):
    return {
        "budget_max_external_requests": external_requests,
        "budget_max_wall_clock_seconds": (
            wall_clock
            if wall_clock is not None
            else wall_clock_floor_for_cap(min(3, external_requests - 1))
        ),
        "budget_max_records": 1,
        "budget_max_output_tokens": MAX_OUTPUT_TOKENS,
        "budget_max_input_tokens": 1_000_000,
        "budget_max_estimated_cost_micros": 10_000_000,
        "circuit_breaker_max_consecutive_failures": 1,
    }


class FakeSession:
    """A budget session that admits on the measured count it is given.

    Both keyword-only values are required and both are recorded. The reserve
    arrives from the runner rather than being re-derived here: two copies of the
    pricing rule could disagree, and the meter is the copy nobody would notice
    drifting. The admission returned carries the supplied reserve **exactly** --
    the runner compares the two and refuses a mismatch, so a meter that quietly
    reserved a different amount could not spend it.
    """

    def __init__(
        self,
        cap: int,
        *,
        reserve_override: int | None = None,
        digest_override: str | None = None,
        nonce: str | None = None,
    ) -> None:
        self.cap = cap
        self.admitted: list[int] = []
        self.reserves: list[int] = []
        self.digests: list[str] = []
        self.calls: list[dict[str, object]] = []
        self._reserve_override = reserve_override
        self._digest_override = digest_override
        self._nonce = nonce or "c" * 64

    def meter_identity(self):
        return {"meter_identity": "fake", "meter_version": "1"}

    @property
    def session_nonce(self) -> str:
        """ADR-047: a real 64-hex nonce, and the one it stamps on admissions.

        The private seam applies the same shape gate and the same
        admission-versus-session comparison as the canonical route, so a fake
        that returned a placeholder here would be refused rather than tolerated.
        """
        return self._nonce

    def admit(
        self,
        *,
        measured_input_tokens: int,
        reserved_cost_microdollars: int,
        provider_request_digest: str,
    ) -> BudgetAdmission:
        self.admitted.append(measured_input_tokens)
        self.reserves.append(reserved_cost_microdollars)
        self.digests.append(provider_request_digest)
        self.calls.append(
            {
                "measured_input_tokens": measured_input_tokens,
                "reserved_cost_microdollars": reserved_cost_microdollars,
                "provider_request_digest": provider_request_digest,
            }
        )
        return BudgetAdmission(
            measured_input_tokens=measured_input_tokens,
            reserved_cost_microdollars=(
                reserved_cost_microdollars
                if self._reserve_override is None
                else self._reserve_override
            ),
            generate_attempt_cap=self.cap,
            provider_request_digest=(
                provider_request_digest
                if self._digest_override is None
                else self._digest_override
            ),
            session_nonce=self._nonce,
        )


class FakeProvider:
    """Calls the sink exactly once per attempt, before the next one starts."""

    def __init__(self, *, count_body, generate_bodies, witness=None) -> None:
        self.count_body = count_body
        self.generate_bodies = list(generate_bodies)
        self.witness = witness
        self.sends = 0
        self.order: list[str] = []

    def count_tokens(self, request, *, sink):
        self.sends += 1
        self.order.append("count_send")
        record = sink(
            operation_label="count_tokens",
            attempt_ordinal=1,
            raw_bytes=self.count_body,
            send_outcome="response_2xx",
            sdk_call_outcome="returned",
            provider_reason_code=None,
        )
        self.order.append("count_sink")
        witness = self.witness
        if witness is None and self.count_body:
            try:
                witness = json.loads(self.count_body.decode("utf-8")).get("totalTokens")
            except ValueError:
                # The SDK would have produced no usable witness either. The
                # runner's own parser is what refuses, and it refuses first.
                witness = None
        return record, witness

    def complete_v8(self, request, *, admission, sink):
        admission.spend()
        records = []
        for ordinal, body in enumerate(self.generate_bodies, start=1):
            self.sends += 1
            self.order.append(f"generate_send_{ordinal}")
            terminal = ordinal == len(self.generate_bodies)
            records.append(
                sink(
                    operation_label="generate_content",
                    attempt_ordinal=ordinal,
                    raw_bytes=body,
                    send_outcome="response_2xx",
                    sdk_call_outcome="returned" if terminal else "raised",
                    provider_reason_code=None if terminal else "vertex_unavailable",
                )
            )
            self.order.append(f"generate_sink_{ordinal}")
        return object(), tuple(records)


# --- the phase order ---------------------------------------------------------


def test_the_measurement_walks_count_then_derive_then_admit_then_generate(tmp_path):
    provider = FakeProvider(count_body=b'{"totalTokens": 1000}', generate_bodies=[b"prediction"])
    session = FakeSession(cap=3)
    result = _run_two_operation_measurement(
        root=tmp_path,
        provider=provider,
        session=session,
        request=request(),
        authorization=authorization(),
        max_output_tokens=MAX_OUTPUT_TOKENS,
        request_digest=HELPER_DIGEST,
    )
    assert result["measured_input_tokens"] == 1000
    assert session.admitted == [1000]
    # The count body was on disk before the budget saw its number.
    assert (tmp_path / COUNT_RAW_REFERENCE).read_bytes() == b'{"totalTokens": 1000}'
    assert provider.order[:2] == ["count_send", "count_sink"]
    assert "generate_send_1" in provider.order
    assert provider.order.index("count_sink") < provider.order.index("generate_send_1")


def test_the_reserve_is_the_cap_times_the_per_attempt_ceiling(tmp_path):
    provider = FakeProvider(count_body=b'{"totalTokens": 100000}', generate_bodies=[b"p"])
    result = _run_two_operation_measurement(
        root=tmp_path,
        provider=provider,
        session=FakeSession(cap=3),
        request=request(),
        authorization=authorization(),
        max_output_tokens=MAX_OUTPUT_TOKENS,
        request_digest=HELPER_DIGEST,
    )
    per_attempt = usage_cost_microdollars(input_tokens=100_000, output_tokens=MAX_OUTPUT_TOKENS)
    assert result["reserved_cost_microdollars"] == 3 * per_attempt


def test_a_witness_disagreement_stops_before_the_generation_call(tmp_path):
    provider = FakeProvider(
        count_body=b'{"totalTokens": 10}', generate_bodies=[b"never"], witness=11
    )
    with pytest.raises(ExtractionError) as caught:
        _run_two_operation_measurement(
            root=tmp_path,
            provider=provider,
            session=FakeSession(cap=3),
            request=request(),
            authorization=authorization(),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            request_digest=HELPER_DIGEST,
        )
    assert caught.value.reason_code == "count_reconciliation_mismatch"
    assert provider.sends == 1
    # The evidence for the refusal survives it.
    assert (tmp_path / COUNT_RAW_REFERENCE).exists()


def test_an_unparsable_count_body_stops_before_the_generation_call(tmp_path):
    provider = FakeProvider(count_body=b"{not json", generate_bodies=[b"never"])
    with pytest.raises(ExtractionError) as caught:
        _run_two_operation_measurement(
            root=tmp_path,
            provider=provider,
            session=FakeSession(cap=3),
            request=request(),
            authorization=authorization(),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            request_digest=HELPER_DIGEST,
        )
    assert caught.value.reason_code == "count_parse_failed"
    assert provider.sends == 1


# --- the sink ----------------------------------------------------------------


def test_the_sink_writes_each_attempt_to_its_own_canonical_path(tmp_path):
    sink = build_capture_sink(tmp_path)
    first = sink(
        operation_label="generate_content",
        attempt_ordinal=1,
        raw_bytes=b"transient",
        send_outcome="response_5xx",
        sdk_call_outcome="raised",
        provider_reason_code="vertex_unavailable",
    )
    second = sink(
        operation_label="generate_content",
        attempt_ordinal=2,
        raw_bytes=b"final",
        send_outcome="response_2xx",
        sdk_call_outcome="returned",
        provider_reason_code=None,
    )
    assert first.raw_reference == generate_attempt_reference(1)
    assert second.raw_reference == RAW_PREDICTION_REFERENCE
    assert (tmp_path / first.raw_reference).read_bytes() == b"transient"
    assert (tmp_path / second.raw_reference).read_bytes() == b"final"


def test_the_sink_never_writes_a_zero_length_body(tmp_path):
    """A zero-byte artifact would carry sha256 of nothing — a valid-looking
    digest for content that never existed."""
    sink = build_capture_sink(tmp_path)
    record = sink(
        operation_label="count_tokens",
        attempt_ordinal=1,
        raw_bytes=b"",
        send_outcome="response_2xx",
        sdk_call_outcome="returned",
        provider_reason_code="provider_response_unusable",
    )
    assert record.capture_disposition == "empty_entity_body_not_persisted"
    assert record.raw_reference is None and record.raw_sha256 is None
    assert not (tmp_path / COUNT_RAW_REFERENCE).exists()


def test_the_sink_reports_no_body_captured_without_inventing_one(tmp_path):
    sink = build_capture_sink(tmp_path)
    record = sink(
        operation_label="generate_content",
        attempt_ordinal=1,
        raw_bytes=None,
        send_outcome="no_response_transport_failure",
        sdk_call_outcome="raised",
        provider_reason_code="provider_timeout",
    )
    assert record.capture_disposition == "no_body_captured"
    assert record.raw_reference is None
    assert list(tmp_path.rglob("*.json")) == []


def test_a_persistence_failure_raises_the_sentinel_and_not_a_provider_error(tmp_path):
    sink = build_capture_sink(tmp_path)
    sink(
        operation_label="count_tokens",
        attempt_ordinal=1,
        raw_bytes=b"first",
        send_outcome="response_2xx",
        sdk_call_outcome="returned",
        provider_reason_code=None,
    )
    with pytest.raises(CaptureSinkError) as caught:
        # Write-once: the second write to the same reference is refused.
        sink(
            operation_label="count_tokens",
            attempt_ordinal=1,
            raw_bytes=b"second",
            send_outcome="response_2xx",
            sdk_call_outcome="returned",
            provider_reason_code=None,
        )
    assert caught.value.persistence_reason_code == "destination_exists"
    assert (tmp_path / COUNT_RAW_REFERENCE).read_bytes() == b"first"


def test_a_persistence_failure_carries_the_provider_reason_without_replacing_it(tmp_path):
    """Both can be true at once, and neither masks the other."""
    sink = build_capture_sink(tmp_path)
    sink(
        operation_label="generate_content",
        attempt_ordinal=1,
        raw_bytes=b"first",
        send_outcome="response_5xx",
        sdk_call_outcome="raised",
        provider_reason_code="vertex_unavailable",
    )
    with pytest.raises(CaptureSinkError) as caught:
        sink(
            operation_label="generate_content",
            attempt_ordinal=1,
            raw_bytes=b"again",
            send_outcome="response_5xx",
            sdk_call_outcome="raised",
            provider_reason_code="vertex_unavailable",
        )
    assert caught.value.provider_reason_code == "vertex_unavailable"
    assert caught.value.persistence_reason_code == "destination_exists"


def test_a_persistence_failure_permits_no_further_send(tmp_path):
    """The rule the whole ordering exists for."""

    class FailingSinkProvider(FakeProvider):
        def complete_v8(self, request, *, admission, sink):
            admission.spend()
            for ordinal in (1, 2):
                self.sends += 1
                sink(
                    operation_label="generate_content",
                    attempt_ordinal=1,  # collides on the second call
                    raw_bytes=b"body",
                    send_outcome="response_5xx",
                    sdk_call_outcome="raised",
                    provider_reason_code="vertex_unavailable",
                )
            raise AssertionError("unreachable")  # pragma: no cover

    provider = FailingSinkProvider(count_body=b'{"totalTokens": 5}', generate_bodies=[])
    with pytest.raises(CaptureSinkError):
        _run_two_operation_measurement(
            root=tmp_path,
            provider=provider,
            session=FakeSession(cap=3),
            request=request(),
            authorization=authorization(),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            request_digest=HELPER_DIGEST,
        )
    # One count send plus exactly two generate sends: the loop stopped at the
    # failure instead of continuing to the third attempt its cap allowed.
    assert provider.sends == 3


# --- budget arithmetic -------------------------------------------------------


@pytest.mark.parametrize(
    "external_requests, cap, floor",
    [(2, 1, 600), (3, 2, 901), (4, 3, 1203), (9, 3, 1203)],
)
def test_the_wall_clock_floor_is_tiered_by_the_effective_cap(external_requests, cap, floor):
    assert resolve_attempt_cap_v2(authorization=authorization(external_requests)) == cap
    assert wall_clock_floor_for_cap(cap) == floor
    too_low = authorization(external_requests, wall_clock=floor - 1)
    with pytest.raises(ExtractionError) as caught:
        resolve_attempt_cap_v2(authorization=too_low)
    assert caught.value.reason_code == "budget_insufficient"


def test_a_single_flat_floor_would_not_have_been_enough():
    """600 satisfies a one-attempt run and nothing else."""
    for external_requests in (3, 4):
        with pytest.raises(ExtractionError):
            resolve_attempt_cap_v2(authorization=authorization(external_requests, wall_clock=600))


def test_fewer_than_two_external_requests_buys_nothing():
    for external_requests in (1, 0, -1):
        with pytest.raises(ExtractionError):
            resolve_attempt_cap_v2(authorization=authorization(external_requests, wall_clock=1203))


def test_the_worst_case_ceiling_is_derived_and_not_restated():
    assert PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS_V2 == wall_clock_floor_for_cap(3) == 1203


# --- manifest roles ----------------------------------------------------------


def test_the_v1_role_set_is_untouched_and_v2_adds_exactly_two():
    assert len(REQUIRED_SOURCE_ARTIFACT_ROLES) == 8
    assert len(REQUIRED_SOURCE_ARTIFACT_ROLES_V2) == 10
    assert set(REQUIRED_SOURCE_ARTIFACT_ROLES_V2) - set(REQUIRED_SOURCE_ARTIFACT_ROLES) == {
        "count_tokens_raw_response",
        "extraction_execution_outcome",
    }


def test_generation_attempt_bodies_are_not_manifest_roles():
    """A role is a 1:1 pin; a run holds zero to three of those bodies. They are
    pinned by the outcome's per-attempt entries, and the outcome is a role."""
    assert not any("generate_content" in role for role in REQUIRED_SOURCE_ARTIFACT_ROLES_V2)


def test_nothing_is_written_outside_the_run_root(tmp_path):
    provider = FakeProvider(count_body=b'{"totalTokens": 7}', generate_bodies=[b"p"])
    _run_two_operation_measurement(
        root=tmp_path,
        provider=provider,
        session=FakeSession(cap=1),
        request=request(),
        authorization=authorization(2),
        max_output_tokens=MAX_OUTPUT_TOKENS,
        request_digest=HELPER_DIGEST,
    )
    written = sorted(str(path.relative_to(tmp_path)) for path in tmp_path.rglob("*") if path.is_file())
    assert written == sorted([COUNT_RAW_REFERENCE, RAW_PREDICTION_REFERENCE])
    assert all(not Path(name).is_absolute() for name in written)


# --- the public E-M production entry point -----------------------------------
#
# Everything below drives ``run_extraction_stage_v2`` -- the entry point a real
# run uses -- rather than the measurement helper. A helper that works while no
# production route calls it proves nothing about the route.

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"
PROJECT = "my-research-project"
GOV_AUTH = "governance/live_call_authorization.json"
GOV_ENABLEMENT = "governance/adapter_enablement_record.json"
GOV_QUALIFICATION = "governance/adapter_qualification_record.json"
# ADR-044. The fourth governance artifact. Its digests are derived from the real
# repository -- the frozen prompt, SPEC-024, and the tracked change request --
# rather than from placeholder hex, because the whole point of the binding is
# that a run refuses when those bytes are not the ones that were qualified.
GOV_PROMPT_QUALIFICATION = "governance/prompt_qualification_record.json"
CHANGE_REQUEST_REFERENCE = (
    "evals/change_requests/CR-0004-product-discovery-schema-v4-bootstrap-qualification.md"
)
CODE_COMMIT = "be627003f3246b371c2b3ac13e813ef0bb112582"
RUN_CREATED_AT = "2026-07-29T00:00:00Z"
METER_IDENTITY = "dynamic_ai_products.extraction.budget_session"
METER_VERSION = "0.1.0"
COUNT_BODY = b'{"totalTokens": 1000}'
PREDICTION_BODY = (
    b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}],'
    b'"usageMetadata":{"promptTokenCount":1000,"candidatesTokenCount":12}}'
)


def _v2_endpoints():
    return build_operation_endpoints(vertex_project=PROJECT)


def _v2_contract():
    return build_client_contract_v2(vertex_project=PROJECT)


def _v2_contract_digest():
    return sha256_bytes(canonical_json_bytes(_v2_contract()))


class ProviderV2:
    """Injected fake connector: no client, no ADC, no socket, no vendor import."""

    def __init__(self, *, count_body=COUNT_BODY, generate_bodies=(PREDICTION_BODY,),
                 witness=None, count_failure=None, generate_failure=None):
        self.count_body = count_body
        self.generate_bodies = list(generate_bodies)
        self.witness = witness
        self.count_failure = count_failure
        self.generate_failure = generate_failure
        self.count_sends = 0
        self.generate_sends = 0
        self.seen_reserve = None

    def assert_run_permitted(self, *, authorization_sha256=None, endpoint_allowlist=None,
                             enablement_endpoint_allowlist=None):
        self.seen_allowlist = endpoint_allowlist

    def revoke_run_permission(self):
        self.revoked = getattr(self, "revoked", 0) + 1

    def client_contract(self):
        return _v2_contract()

    def count_tokens(self, request, *, sink):
        self.count_sends += 1
        if self.count_failure is not None:
            raise self.count_failure
        record = sink(
            operation_label="count_tokens",
            attempt_ordinal=1,
            raw_bytes=self.count_body,
            send_outcome="response_2xx",
            sdk_call_outcome="returned",
            provider_reason_code=None,
        )
        witness = self.witness
        if witness is None and self.count_body:
            try:
                witness = json.loads(self.count_body.decode("utf-8")).get("totalTokens")
            except ValueError:
                witness = None
        return record, witness

    def complete_v8(self, request, *, admission, sink):
        admission.spend()
        self.seen_reserve = admission.reserved_cost_microdollars
        if self.generate_failure is not None:
            self.generate_sends += 1
            raise self.generate_failure
        records = []
        for ordinal, body in enumerate(self.generate_bodies, start=1):
            self.generate_sends += 1
            terminal = ordinal == len(self.generate_bodies)
            records.append(
                sink(
                    operation_label="generate_content",
                    attempt_ordinal=ordinal,
                    raw_bytes=body,
                    send_outcome="response_2xx",
                    sdk_call_outcome="returned" if terminal else "raised",
                    provider_reason_code=None if terminal else "vertex_unavailable",
                )
            )
        response = ProviderResponse(
            raw_bytes=b"",
            model_provider="google_vertex_ai",
            model_name="gemini-2.5-flash",
            model_parameters=dict(_v2_contract()["model_parameters"]),
            prompt_model_metadata={
                "model_name": "gemini-2.5-flash",
                "prompt_sha256": request.prompt_sha256,
                "api_version": "v1",
                "raw_capture_representation": "post_content_encoding_entity_body",
            },
        )
        return response, tuple(records)


class SinkFailingProvider(ProviderV2):
    """Attempt 1 persists; attempt 2's destination already exists, so it cannot.

    The collision is arranged the way a real one would arise -- the target path
    is occupied -- rather than by calling the sink twice with one ordinal, which
    would produce two attempts wearing the same number.
    """

    def __init__(self, *, provider_reason=None, run_root=None, **kwargs):
        super().__init__(**kwargs)
        self._provider_reason = provider_reason
        self._run_root = run_root

    def complete_v8(self, request, *, admission, sink):
        admission.spend()
        # Attempt 1: a retryable provider failure whose body is captured and
        # written to its own ordinal path.
        self.generate_sends += 1
        sink(
            operation_label="generate_content",
            attempt_ordinal=1,
            raw_bytes=b"transient",
            send_outcome="response_5xx",
            sdk_call_outcome="raised",
            provider_reason_code="vertex_unavailable",
        )
        # Occupy attempt 2's destination before it is written. Which path that
        # is depends on whether the call returns: a returning attempt is the
        # terminal one and owns the raw-prediction path, a raising one goes to
        # its own ordinal path.
        occupied = self._run_root / (
            generate_attempt_reference(2)
            if self._provider_reason
            else RAW_PREDICTION_REFERENCE
        )
        occupied.parent.mkdir(parents=True, exist_ok=True)
        occupied.write_bytes(b"already here")
        self.generate_sends += 1
        sink(
            operation_label="generate_content",
            attempt_ordinal=2,
            raw_bytes=b"second",
            send_outcome="response_5xx" if self._provider_reason else "response_2xx",
            sdk_call_outcome="raised" if self._provider_reason else "returned",
            provider_reason_code=self._provider_reason,
        )
        raise AssertionError("unreachable")  # pragma: no cover


class SessionV2(FakeSession):
    """The same admission seam, under the identity the authorization pins."""

    def meter_identity(self):
        return {"meter_identity": METER_IDENTITY, "meter_version": METER_VERSION}


class _Refusal(Exception):
    def __init__(self, reason_code, attempt_count=1):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.attempt_count = attempt_count


def _passage():
    text = "the product ships an assistant"
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
    return {"reference": "pilot_universe_packet.json", "sha256": sha256_bytes(payload)}


def _repo_digest(reference: str) -> str:
    return sha256_bytes((REPO_ROOT / reference).read_bytes())


def _prompt_qualification_record(stage_sha: str, routing_sha: str, **overrides):
    prompt = load_prompt(REPO_ROOT, "product_discovery_schema_v4")
    record = {
        "contract": "prompt_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "promptqual-em",
        "qualification_basis": "bootstrap_pre_evaluation",
        "qualification_scope": "qualified_for_development",
        "qualification_status": "bootstrap_authorized_live_dev",
        "prompt_lifecycle_state": "candidate",
        "supersedes_qualification_id": None,
        "prompt_id": "product_discovery_schema_v4",
        "prompt_registry_version": prompt["prompt_registry_version"],
        "prompt_reference": prompt["reference"],
        "prompt_artifact_sha256": prompt["prompt_hash"],
        "stage": "product_extraction",
        "stage_output_contract_id": "product_observation@0.1.0",
        "stage_output_contract_sha256": stage_sha,
        "execution_contract_id": "extraction_provider_client_contract@0.2.0",
        "execution_contract_sha256": _v2_contract_digest(),
        "routing_contract_id": ROUTING_CONTRACT_ID,
        "routing_contract_sha256": routing_sha,
        "governing_spec_reference": GOVERNING_SPEC_REFERENCE,
        "governing_spec_sha256": _repo_digest(GOVERNING_SPEC_REFERENCE),
        "change_request_reference": CHANGE_REQUEST_REFERENCE,
        "change_request_sha256": _repo_digest(CHANGE_REQUEST_REFERENCE),
        "declared_non_claims": list(DECLARED_NON_CLAIMS),
        "known_limitation_codes": [
            "single_pass_recall_only_not_consolidated",
            "sec_only_partial_corpus",
            "no_completed_evaluation_run",
        ],
        "reviewer": "methodology-owner",
        "decided_at": "2026-07-28T00:00:00Z",
        "code_commit": CODE_COMMIT,
    }
    record.update(overrides)
    return record


def _write_governance_v2(
    root: Path, prompt_qualification_overrides=None, **authorization_overrides
) -> dict[str, str]:
    (root / "governance").mkdir(parents=True, exist_ok=True)
    stage_sha = STAGE_OUTPUT_SCHEMA_SHA256["product_extraction"]
    qualification = {
        "contract": "adapter_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "qual-em",
        "adapter_identity": "dynamic_ai_products.providers.vertex_gemini_v2",
        "adapter_version": "0.2.0",
        "adapter_family": "model_execution",
        "execution_contract_id": "extraction_provider_client_contract@0.2.0",
        "execution_contract_sha256": _v2_contract_digest(),
        "stage_output_contract_id": "product_observation@0.1.0",
        "stage_output_contract_sha256": stage_sha,
        "qualification_scope": "live_dev",
        "qualification_status": "qualified",
        "qualified_at": "2026-07-01T00:00:00Z",
    }
    qual_bytes = canonical_json_bytes(qualification)
    (root / GOV_QUALIFICATION).write_bytes(qual_bytes)

    routing_sha = derive_routing_contract(client_contract=_v2_contract())[
        "routing_contract_sha256"
    ]
    prompt_qualification = _prompt_qualification_record(
        stage_sha, routing_sha, **(prompt_qualification_overrides or {})
    )
    pq_bytes = canonical_json_bytes(prompt_qualification)
    (root / GOV_PROMPT_QUALIFICATION).write_bytes(pq_bytes)

    endpoints = _v2_endpoints()
    allowlist = [endpoints["count_tokens"], endpoints["generate_content"]]
    enablement = {
        "contract": "adapter_enablement_record@0.1.0",
        "schema_version": "0.1.0",
        "enablement_id": "enab-em",
        "adapter_qualification_record_reference": GOV_QUALIFICATION,
        "adapter_qualification_record_sha256": sha256_bytes(qual_bytes),
        "prompt_qualification_reference": GOV_PROMPT_QUALIFICATION,
        "prompt_qualification_sha256": sha256_bytes(pq_bytes),
        "stage": "product_extraction",
        "stage_output_contract_id": "product_observation@0.1.0",
        "stage_output_contract_sha256": stage_sha,
        "routing_contract_id": ROUTING_CONTRACT_ID,
        "routing_contract_sha256": routing_sha,
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

    auth = {
        "contract": "live_call_authorization@0.2.0",
        "schema_version": "0.2.0",
        "authorization_id": "auth-em",
        "authorized_by": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "adapter_enablement_record_reference": GOV_ENABLEMENT,
        "adapter_enablement_record_sha256": sha256_bytes(enab_bytes),
        "provider_client_contract_reference": "inputs/provider_client_contract.json",
        "provider_client_contract_sha256": _v2_contract_digest(),
        "budget_meter_identity": METER_IDENTITY,
        "budget_meter_version": METER_VERSION,
        "stage": "product_extraction",
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "corpus_scope": "sec_only_partial",
        "budget_max_records": 1,
        "budget_max_external_requests": 4,
        "budget_max_input_tokens": 100000,
        "budget_max_output_tokens": 8192,
        "budget_max_estimated_cost_micros": 500000,
        "budget_max_wall_clock_seconds": 1203,
        "budget_policy_version": "budget_policy_v1",
        "retry_policy_version": "extraction_provider_retry_policy_v1",
        "rate_limit_policy_version": "extraction_provider_rate_limit_policy_v1",
        "endpoint_allowlist": list(allowlist),
        "circuit_breaker_max_consecutive_failures": 1,
        "provider_called": True,
        "harness_run": False,
    }
    auth.update(authorization_overrides)
    auth_bytes = canonical_json_bytes(auth)
    (root / GOV_AUTH).write_bytes(auth_bytes)
    return {"reference": GOV_AUTH, "sha256": sha256_bytes(auth_bytes)}


def _evidence_binding():
    schema = json.loads(
        (SCHEMAS / "extraction_execution_outcome.schema.json").read_text(encoding="utf-8")
    )["properties"]["evidence_binding"]["properties"]
    return {name: schema[name]["const"] for name in schema}


def _run_v2(
    tmp_path: Path,
    *,
    provider=None,
    authorization_overrides=None,
    prompt_qualification_overrides=None,
):
    """ADR-047: no ``session`` argument. The canonical route builds its own, so a
    test that wants to observe or misbehave a session drives the private
    measurement helper instead -- see the admission-boundary section below."""
    governance = tmp_path / "governance-root"
    pin = _write_governance_v2(
        governance,
        prompt_qualification_overrides=prompt_qualification_overrides,
        **(authorization_overrides or {}),
    )
    return run_extraction_stage_v2(
        run_root=tmp_path / "run",
        repo_root=REPO_ROOT,
        stage="product_extraction",
        company_id=COMPANY,
        observation_cutoff_date=CUTOFF,
        passages=[_passage()],
        document_publication_dates={"sec-1": "2024-02-14"},
        coverage_artifact={"reference": "coverage/c.json", "sha256": "d" * 64},
        source_snapshot_manifest={"reference": "snapshots/m.json", "sha256": "e" * 64},
        code_commit="be627003f3246b371c2b3ac13e813ef0bb112582",
        run_created_at="2026-07-29T00:00:00Z",
        extraction_run_id="ext-em-1",
        prediction_run_id="pred-em-1",
        evidence_binding=_evidence_binding(),
        schema_root=str(SCHEMAS),
        provider=provider if provider is not None else ProviderV2(),
        governance_artifact_root=governance,
        live_call_authorization_pin=pin,
        company_identity_root=tmp_path / "identity",
        company_identity_pin=_write_identity(tmp_path / "identity"),
    )


def _files(root: Path) -> set[str]:
    return {str(path.relative_to(root)) for path in root.rglob("*") if path.is_file()}


def _outcome(root: Path) -> dict:
    return json.loads((root / EXECUTION_OUTCOME_REFERENCE).read_text(encoding="utf-8"))


def _outcome_is_valid(record: dict) -> bool:
    schema = json.loads(
        (SCHEMAS / "extraction_execution_outcome.schema.json").read_text(encoding="utf-8")
    )
    return list(Draft202012Validator(schema).iter_errors(record)) == []


# --- the completed route ------------------------------------------------------


def test_the_production_entry_point_publishes_the_full_two_operation_chain(tmp_path):
    outcome = _run_v2(tmp_path)
    assert outcome.verdict == "two_operation_run_complete"
    assert _files(outcome.run_root) == {
        PACKET_REFERENCE,
        CONTENTS_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        AUTHORIZATION_REFERENCE,
        COUNT_RAW_REFERENCE,
        RAW_PREDICTION_REFERENCE,
        EXTRACTION_RUN_REFERENCE,
        EXECUTION_OUTCOME_REFERENCE,
        ENVELOPES_REFERENCE,
        PREDICTION_MANIFEST_REFERENCE,
    }
    assert set(outcome.artifacts) == _files(outcome.run_root)
    for reference, digest in outcome.artifacts.items():
        assert sha256_bytes((outcome.run_root / reference).read_bytes()) == digest


def test_the_published_outcome_satisfies_its_own_committed_contract(tmp_path):
    outcome = _run_v2(tmp_path)
    record = _outcome(outcome.run_root)
    assert _outcome_is_valid(record)
    assert record["route_family"] == "completed"
    assert record["measurement_status"] == "verified"
    assert record["measured_input_tokens"] == 1000
    assert record["external_request_count"] == 2


def test_the_outcome_is_write_once(tmp_path):
    outcome = _run_v2(tmp_path)
    with pytest.raises(ExtractionError) as caught:
        write_artifact(outcome.run_root, EXECUTION_OUTCOME_REFERENCE, b"{}")
    assert caught.value.reason_code == "destination_exists"


def test_the_manifest_pins_the_count_response_and_the_outcome_as_roles(tmp_path):
    outcome = _run_v2(tmp_path)
    manifest = json.loads(
        (outcome.run_root / PREDICTION_MANIFEST_REFERENCE).read_text(encoding="utf-8")
    )
    pinned = {entry["reference"]: entry["sha256"] for entry in manifest["source_artifacts"]}
    assert len(pinned) == 10
    assert pinned[COUNT_RAW_REFERENCE] == outcome.artifacts[COUNT_RAW_REFERENCE]
    assert pinned[EXECUTION_OUTCOME_REFERENCE] == outcome.artifacts[EXECUTION_OUTCOME_REFERENCE]


def test_the_count_bytes_are_persisted_and_verified_before_anything_derives_from_them(
    tmp_path,
):
    """The ordering claim, observed rather than asserted.

    The sink writes the count body; the runner then re-reads it and compares the
    digest before parsing. A provider that watches the filesystem at each step
    sees the file already present and already correct when generation starts.
    """
    observed = {}

    class Watcher(ProviderV2):
        def complete_v8(self, request, *, admission, sink):
            root = tmp_path / "run"
            path = root / COUNT_RAW_REFERENCE
            observed["exists_at_generate"] = path.exists()
            observed["digest_at_generate"] = sha256_bytes(path.read_bytes())
            observed["admitted_input"] = admission.measured_input_tokens
            return super().complete_v8(request, admission=admission, sink=sink)

    outcome = _run_v2(tmp_path, provider=Watcher())
    assert observed["exists_at_generate"] is True
    assert observed["digest_at_generate"] == outcome.artifacts[COUNT_RAW_REFERENCE]
    assert observed["admitted_input"] == 1000
    assert _outcome(outcome.run_root)["count_operation"]["raw_sha256"] == (
        outcome.artifacts[COUNT_RAW_REFERENCE]
    )


# --- terminal routes: every one publishes an outcome, none generates ----------


def _expect_stop(tmp_path, *, raw_prediction_absent=True, **kwargs):
    """Every terminal route publishes a valid outcome and certifies nothing.

    ``raw_prediction_absent`` is relaxed only where a test itself put a file at
    that path to arrange the failure; the certification checks below hold
    regardless.
    """
    with pytest.raises(ExtractionError) as caught:
        _run_v2(tmp_path, **kwargs)
    root = tmp_path / "run"
    record = _outcome(root)
    assert _outcome_is_valid(record), "a published outcome must satisfy its own contract"
    files = _files(root)
    if raw_prediction_absent:
        assert RAW_PREDICTION_REFERENCE not in files
    # Nothing is certified on any of these routes.
    assert ENVELOPES_REFERENCE not in files
    assert PREDICTION_MANIFEST_REFERENCE not in files
    return caught.value, record, files


def test_a_count_provider_failure_publishes_a_terminal_chain_and_never_generates(tmp_path):
    provider = ProviderV2(count_failure=_Refusal("vertex_unavailable"))
    error, record, files = _expect_stop(tmp_path, provider=provider)
    assert provider.generate_sends == 0
    assert record["route_family"] == "count_provider_error"
    assert record["terminal_reason"] == "provider_call_failed"
    assert PROVIDER_ERROR_REFERENCE in files
    assert COUNT_RAW_REFERENCE not in files
    assert error.reason_code == "provider_call_failed"


def test_a_count_parse_failure_publishes_an_invalid_outcome_and_never_generates(tmp_path):
    provider = ProviderV2(count_body=b"{not json}")
    _error, record, files = _expect_stop(tmp_path, provider=provider)
    assert provider.generate_sends == 0
    assert record["route_family"] == "pre_generation_invalid"
    assert record["terminal_reason"] == "count_parse_failed"
    # The evidence for the refusal survives it.
    assert COUNT_RAW_REFERENCE in files
    assert PROVIDER_ERROR_REFERENCE not in files


def test_a_reconciliation_mismatch_publishes_an_invalid_outcome_and_never_generates(tmp_path):
    provider = ProviderV2(witness=999)
    _error, record, files = _expect_stop(tmp_path, provider=provider)
    assert provider.generate_sends == 0
    assert record["terminal_reason"] == "count_reconciliation_mismatch"
    assert COUNT_RAW_REFERENCE in files


def test_an_estimated_cost_refusal_stops_before_generatecontent(tmp_path):
    """The reserve for the authorized cap exceeds the authorized spend."""
    provider = ProviderV2()
    _error, record, files = _expect_stop(
        tmp_path,
        provider=provider,
        # cap 3 x (ceil(1000 x 3/10) + ceil(8192 x 5/2)) = 62 340
        authorization_overrides={"budget_max_estimated_cost_micros": 62_339},
    )
    assert provider.generate_sends == 0
    assert record["route_family"] == "pre_generation_invalid"
    assert record["terminal_reason"] == "budget_termination"
    assert COUNT_RAW_REFERENCE in files


def test_one_microdollar_more_of_budget_admits_the_same_run(tmp_path):
    """The refusal is the arithmetic, not an unrelated failure."""
    outcome = _run_v2(
        tmp_path, authorization_overrides={"budget_max_estimated_cost_micros": 62_340}
    )
    assert outcome.verdict == "two_operation_run_complete"


def test_an_input_token_refusal_stops_before_generatecontent(tmp_path):
    provider = ProviderV2()
    _error, record, files = _expect_stop(
        tmp_path, provider=provider, authorization_overrides={"budget_max_input_tokens": 999}
    )
    assert provider.generate_sends == 0
    assert record["terminal_reason"] == "budget_termination"


def test_a_count_persistence_failure_publishes_an_invalid_outcome_and_never_generates(
    tmp_path,
):
    class DoubleWriter(ProviderV2):
        def count_tokens(self, request, *, sink):
            self.count_sends += 1
            sink(
                operation_label="count_tokens",
                attempt_ordinal=1,
                raw_bytes=self.count_body,
                send_outcome="response_2xx",
                sdk_call_outcome="returned",
                provider_reason_code=None,
            )
            # Write-once: the same reference cannot be claimed twice.
            return sink(
                operation_label="count_tokens",
                attempt_ordinal=1,
                raw_bytes=self.count_body,
                send_outcome="response_2xx",
                sdk_call_outcome="returned",
                provider_reason_code=None,
            ), 1000

    provider = DoubleWriter()
    _error, record, _files_ = _expect_stop(tmp_path, provider=provider)
    assert provider.generate_sends == 0
    assert record["route_family"] == "pre_generation_invalid"
    assert record["terminal_reason"] == "persistence_failure"


def test_a_generation_failure_publishes_a_provider_error_and_an_outcome(tmp_path):
    provider = ProviderV2(generate_failure=_Refusal("vertex_quota_exhausted", attempt_count=2))
    _error, record, files = _expect_stop(tmp_path, provider=provider)
    assert provider.generate_sends == 1
    assert record["route_family"] == "generation_provider_error"
    assert PROVIDER_ERROR_REFERENCE in files
    assert COUNT_RAW_REFERENCE in files
    assert record["error_count"] == 2


def test_a_post_generation_reconciliation_refusal_keeps_the_bytes_and_certifies_nothing(
    tmp_path,
):
    body = (
        b'{"candidates":[],"usageMetadata":{"promptTokenCount":1000,'
        b'"thoughtsTokenCount":7}}'
    )
    provider = ProviderV2(generate_bodies=(body,))
    with pytest.raises(ExtractionError) as caught:
        _run_v2(tmp_path, provider=provider)
    assert caught.value.reason_code == "reconciliation_invalid"
    root = tmp_path / "run"
    record = _outcome(root)
    assert _outcome_is_valid(record)
    assert record["route_family"] == "post_generation_invalid"
    assert record["measurement_status"] == "invalid"
    files = _files(root)
    # The bytes stay; the certification does not.
    assert RAW_PREDICTION_REFERENCE in files
    assert ENVELOPES_REFERENCE not in files
    assert PREDICTION_MANIFEST_REFERENCE not in files


def test_a_v1_shaped_authorization_cannot_drive_the_two_operation_route(tmp_path):
    """The budgets are not interchangeable: one counts retries, the other requests."""
    governance = tmp_path / "governance-root"
    _write_governance_v2(governance)
    payload = json.loads((governance / GOV_AUTH).read_text(encoding="utf-8"))
    payload["budget_max_requests"] = payload.pop("budget_max_external_requests")
    payload["contract"] = "live_call_authorization@0.1.0"
    payload["schema_version"] = "0.1.0"
    rewritten = canonical_json_bytes(payload)
    (governance / GOV_AUTH).write_bytes(rewritten)
    with pytest.raises(ExtractionError):
        run_extraction_stage_v2(
            run_root=tmp_path / "run",
            repo_root=REPO_ROOT,
            stage="product_extraction",
            company_id=COMPANY,
            observation_cutoff_date=CUTOFF,
            passages=[_passage()],
            document_publication_dates={"sec-1": "2024-02-14"},
            coverage_artifact={"reference": "coverage/c.json", "sha256": "d" * 64},
            source_snapshot_manifest={"reference": "snapshots/m.json", "sha256": "e" * 64},
            code_commit="be627003f3246b371c2b3ac13e813ef0bb112582",
            run_created_at="2026-07-29T00:00:00Z",
            extraction_run_id="ext-em-1",
            prediction_run_id="pred-em-1",
            evidence_binding=_evidence_binding(),
            schema_root=str(SCHEMAS),
            provider=ProviderV2(),
            governance_artifact_root=governance,
            live_call_authorization_pin={
                "reference": GOV_AUTH,
                "sha256": sha256_bytes(rewritten),
            },
            company_identity_root=tmp_path / "identity",
            company_identity_pin=_write_identity(tmp_path / "identity"),
        )
    assert not (tmp_path / "run").exists(), "a governance refusal costs zero artifacts"


def test_a_pre_mkdir_budget_refusal_leaves_no_run_root(tmp_path):
    with pytest.raises(ExtractionError):
        _run_v2(tmp_path, authorization_overrides={"budget_max_wall_clock_seconds": 1202})
    assert not (tmp_path / "run").exists()


# --- the admission boundary carries both values, exactly ----------------------


def _measure(tmp_path, *, session, provider=None, authorization_overrides=None):
    """Drive the private measurement helper with a caller-supplied session.

    ADR-047 closed the public seam, so this is the only place a session can be
    observed or misbehaved. The helper publishes nothing -- it returns facts and
    raises -- so these tests assert the raised reason code, never a route family.
    """
    root = tmp_path / "measure"
    root.mkdir()
    auth = authorization(4)
    auth.update(authorization_overrides or {})
    return _run_two_operation_measurement(
        root=root,
        provider=provider if provider is not None else FakeProvider(
            count_body=COUNT_BODY, generate_bodies=(PREDICTION_BODY,)
        ),
        session=session,
        request=request(),
        authorization=auth,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        request_digest=HELPER_DIGEST,
    )


def test_the_admission_boundary_receives_both_required_values(tmp_path):
    session = FakeSession(cap=3)
    _measure(tmp_path, session=session)
    expected = reserve_cost_microdollars(
        measured_input_tokens=1000, max_output_tokens=8192, generate_attempt_cap=3
    )
    assert len(session.calls) == 1
    call = session.calls[0]
    assert call["measured_input_tokens"] == 1000
    assert call["reserved_cost_microdollars"] == expected
    assert call["provider_request_digest"] == HELPER_DIGEST
    assert len(call["provider_request_digest"]) == 64


def test_the_reserve_reaches_the_admission_boundary(tmp_path):
    session = FakeSession(cap=3)
    provider = FakeProvider(count_body=COUNT_BODY, generate_bodies=(PREDICTION_BODY,))
    _measure(tmp_path, session=session, provider=provider)
    expected = reserve_cost_microdollars(
        measured_input_tokens=1000, max_output_tokens=8192, generate_attempt_cap=3
    )
    assert session.reserves == [expected]


def test_a_ceiling_refusal_never_consults_the_meter(tmp_path):
    """The runner enforces before it admits, so the session is never called."""
    session = FakeSession(cap=3)
    with pytest.raises(ExtractionError) as caught:
        _measure(
            tmp_path,
            session=session,
            authorization_overrides={"budget_max_estimated_cost_micros": 62_339},
        )
    assert caught.value.reason_code == "budget_estimated_cost_exceeded"
    assert session.admitted == []


def test_an_admission_that_reserves_a_different_amount_cannot_be_spent(tmp_path):
    """The runner compares what it computed with what the admission carries."""
    provider = FakeProvider(count_body=COUNT_BODY, generate_bodies=(PREDICTION_BODY,))
    with pytest.raises(ExtractionError) as caught:
        _measure(tmp_path, session=FakeSession(cap=3, reserve_override=1), provider=provider)
    assert caught.value.reason_code == "budget_estimated_cost_exceeded"
    assert provider.sends == 1, "only the count send happened"


def test_the_runner_derives_the_full_identity_and_hands_it_to_the_meter(tmp_path):
    """The canonical route's digest is rebuilt from what it actually persisted."""
    outcome = _run_v2(tmp_path)
    contract_sha = outcome.artifacts[CLIENT_CONTRACT_REFERENCE]
    persisted_contract = json.loads(
        (outcome.run_root / CLIENT_CONTRACT_REFERENCE).read_text(encoding="utf-8")
    )
    assert client_contract_digest(persisted_contract) == contract_sha
    expected = provider_request_digest(
        ProviderRequest(
            stage="product_extraction",
            rendered_contents=(outcome.run_root / CONTENTS_REFERENCE).read_text(
                encoding="utf-8"
            ),
            rendered_contents_sha256=outcome.artifacts[CONTENTS_REFERENCE],
            prompt_sha256=json.loads(
                (outcome.run_root / EXTRACTION_RUN_REFERENCE).read_text(encoding="utf-8")
            )["prompt_hash"],
            input_packet_sha256=outcome.artifacts[PACKET_REFERENCE],
        ),
        provider_client_contract_sha256=contract_sha,
        protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
    )
    assert len(expected) == 64


def test_an_admission_carrying_another_requests_identity_is_refused(tmp_path):
    """The runner checks the returned admission against what it derived."""
    provider = FakeProvider(count_body=COUNT_BODY, generate_bodies=(PREDICTION_BODY,))
    with pytest.raises(ExtractionError) as caught:
        _measure(tmp_path, session=FakeSession(cap=3, digest_override="a" * 64), provider=provider)
    assert caught.value.reason_code == "budget_admission_invalid"
    assert provider.sends == 1, "only the count send happened"


def _assert_count_verified_and_no_generation(root: Path, record: dict, provider) -> None:
    """The count evidence is on disk and correct; generation never started."""
    persisted = (root / COUNT_RAW_REFERENCE).read_bytes()
    assert sha256_bytes(persisted) == record["count_operation"]["raw_sha256"]
    assert record["count_operation"]["capture_disposition"] == "raw_persisted"
    assert record["measured_input_tokens"] == 1000
    assert provider.generate_sends == 0
    files = _files(root)
    assert RAW_PREDICTION_REFERENCE not in files
    assert ENVELOPES_REFERENCE not in files
    assert PREDICTION_MANIFEST_REFERENCE not in files


def test_the_cost_ceiling_refuses_after_verified_count_bytes(tmp_path):
    """The count evidence survives the refusal, and the meter is never reached.

    ADR-047 closed the public session seam, so "the meter is never reached" is
    proved on the private measurement helper with an observable session, while
    the published evidence is proved on the canonical route. Both halves of the
    original assertion survive; neither is dropped.
    """
    provider = ProviderV2()
    _error, record, _files_ = _expect_stop(
        tmp_path,
        provider=provider,
        authorization_overrides={"budget_max_estimated_cost_micros": 62_339},
    )
    _assert_count_verified_and_no_generation(tmp_path / "run", record, provider)

    observed = FakeSession(cap=3)
    with pytest.raises(ExtractionError):
        _measure(
            tmp_path,
            session=observed,
            authorization_overrides={"budget_max_estimated_cost_micros": 62_339},
        )
    assert observed.calls == [], "the meter is never reached once the ceiling is breached"


def test_the_input_token_ceiling_refuses_after_verified_count_bytes(tmp_path):
    provider = ProviderV2()
    _error, record, _files_ = _expect_stop(
        tmp_path, provider=provider, authorization_overrides={"budget_max_input_tokens": 999}
    )
    _assert_count_verified_and_no_generation(tmp_path / "run", record, provider)

    observed = FakeSession(cap=3)
    with pytest.raises(ExtractionError):
        _measure(
            tmp_path, session=observed, authorization_overrides={"budget_max_input_tokens": 999}
        )
    assert observed.calls == []


def test_a_generation_persistence_failure_is_our_failure_not_the_providers(tmp_path):
    provider = SinkFailingProvider(run_root=tmp_path / "run")
    # The test itself occupies the raw-prediction path to arrange the collision,
    # so its presence here is the cause of the failure, not a product of it.
    _error, record, files = _expect_stop(
        tmp_path, provider=provider, raw_prediction_absent=False
    )
    assert record["route_family"] == "generation_persistence_failed"
    assert record["terminal_reason"] == "persistence_failure"
    # Our failure, so no provider-error record is published.
    assert PROVIDER_ERROR_REFERENCE not in files
    # The loop stopped at the failure instead of continuing to the third attempt
    # its cap allowed.
    assert provider.generate_sends == 2
    # Attempt 1 failed on the provider's side and was persisted; attempt 2 could
    # not be persisted. Both are recorded, with their own dispositions.
    dispositions = [a["capture_disposition"] for a in record["generate_attempts"]]
    assert dispositions == ["raw_persisted", "body_captured_persistence_failed"]
    assert record["generate_attempts"][1]["persistence_reason_code"] == "destination_exists"
    assert record["error_count"] == 1


def test_a_provider_failure_and_a_persistence_failure_are_both_recorded(tmp_path):
    """Both can be true of one attempt, and neither replaces the other."""
    provider = SinkFailingProvider(
        provider_reason="vertex_unavailable", run_root=tmp_path / "run"
    )
    _error, record, files = _expect_stop(tmp_path, provider=provider)
    assert record["route_family"] == "generation_provider_error"
    assert record["terminal_reason"] == "persistence_failure"
    assert PROVIDER_ERROR_REFERENCE in files
    published = json.loads(
        ((tmp_path / "run") / PROVIDER_ERROR_REFERENCE).read_text(encoding="utf-8")
    )
    # The released record keeps the provider's own reason; the persistence
    # reason has no field there and stays in the outcome.
    assert published["reason_code"] == "vertex_unavailable"
    assert "persistence_reason_code" not in published
    assert provider.generate_sends == 2
    terminal = record["generate_attempts"][-1]
    assert terminal["provider_reason_code"] == "vertex_unavailable"
    assert terminal["persistence_reason_code"] == "destination_exists"


def test_the_v1_entry_point_gained_no_e_m_parameter():
    """E-M is a successor route, not a widening of the released one.

    ADR-047 additionally closed v2's own session seam, so ``budget_session`` is
    now absent from **both** signatures -- v1 because it never had one, v2
    because the runner builds its session itself.
    """
    parameters = set(inspect.signature(run_extraction_stage).parameters)
    for added in ("evidence_binding", "budget_session"):
        assert added not in parameters
    assert "budget_meter" in parameters
    v2_parameters = set(inspect.signature(run_extraction_stage_v2).parameters)
    assert "budget_meter" not in v2_parameters
    assert "budget_session" not in v2_parameters
    assert "evidence_binding" in v2_parameters


def test_the_v1_published_shape_holds_no_e_m_artifact():
    """Nothing the released route publishes moved, and nothing was added to it."""
    assert REQUIRED_SOURCE_ARTIFACT_ROLES == (
        "raw_prediction",
        "extraction_input_packet",
        "rendered_provider_contents",
        "coverage_artifact",
        "resolved_prompt",
        "provider_client_contract",
        "live_call_authorization",
        "extraction_run",
    )
    v1_references = {
        PACKET_REFERENCE,
        CONTENTS_REFERENCE,
        PROMPT_REFERENCE,
        CLIENT_CONTRACT_REFERENCE,
        AUTHORIZATION_REFERENCE,
        RAW_PREDICTION_REFERENCE,
        EXTRACTION_RUN_REFERENCE,
        ENVELOPES_REFERENCE,
        PREDICTION_MANIFEST_REFERENCE,
    }
    assert COUNT_RAW_REFERENCE not in v1_references
    assert EXECUTION_OUTCOME_REFERENCE not in v1_references


def test_the_two_provider_gates_do_not_admit_each_other(tmp_path):
    """A single widened protocol would have let a one-operation connector drive
    a route that must measure before it generates."""

    class OnlyV1:
        def assert_run_permitted(self, **_kwargs):
            return None

        def revoke_run_permission(self):
            return None

        def client_contract(self):
            return {}

        def complete(self, request):
            return None

    with pytest.raises(ExtractionError) as caught:
        require_provider_v8(OnlyV1())
    assert caught.value.reason_code == "provider_protocol_invalid"
    with pytest.raises(ExtractionError) as caught:
        require_provider(ProviderV2())
    assert caught.value.reason_code == "provider_protocol_invalid"
