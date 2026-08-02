"""The injected provider surface (ADR-033, E-A).

E-A never constructs a provider. ``require_provider`` is the only door, and it
is closed until a caller passes an object that satisfies the protocol. The
concrete connector, model label, parameters, and credentials belong to E-P.
"""

from __future__ import annotations

import dataclasses

import pytest

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.provider_adapter import (
    PROVIDER_PROTOCOL_VERSION,
    ExtractionProvider,
    ProviderRequest,
    ProviderResponse,
    require_provider,
)


class _FakeProvider:
    """The offline stand-in. It performs no I/O of any kind."""

    def __init__(self) -> None:
        self.calls: list[ProviderRequest] = []
        self.permitted = 0
        self.seen_digest: str | None = None

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        self.permitted += 1
        self.seen_digest = authorization_sha256


    def revoke_run_permission(self) -> None:
        self.revoked = getattr(self, 'revoked', 0) + 1
    def client_contract(self) -> dict:
        return {"contract": "extraction_provider_client_contract@0.1.0"}

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.calls.append(request)
        return ProviderResponse(
            raw_bytes=b'{"observations": []}',
            model_provider="fake",
            model_name="fake-offline",
            model_parameters={"temperature": 0},
            prompt_model_metadata={"prompt_sha256": request.prompt_sha256},
        )


class _WrongShape:
    def generate(self, request):  # pragma: no cover - never invoked
        raise AssertionError("must not be called")


class _PartialShape:
    """Satisfies only part of v2: a pre-v2 provider must not slip through."""

    def complete(self, request):  # pragma: no cover - never invoked
        raise AssertionError("must not be called")


def test_protocol_version_is_declared():
    assert PROVIDER_PROTOCOL_VERSION == "extraction_provider_protocol_v7"


def test_the_protocol_declares_all_four_members():
    assert set(ExtractionProvider.__protocol_attrs__) == {
        "assert_run_permitted",
        "revoke_run_permission",
        "client_contract",
        "complete",
    }


def test_a_pre_v2_provider_is_refused():
    """A provider with only complete() no longer satisfies the surface."""
    with pytest.raises(ExtractionError) as excinfo:
        require_provider(_PartialShape())
    assert excinfo.value.reason_code == "provider_protocol_invalid"


def test_request_and_response_are_frozen_dataclasses():
    for cls in (ProviderRequest, ProviderResponse):
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen


def test_a_request_cannot_be_mutated_after_construction():
    request = ProviderRequest(
        stage="product_extraction",
        rendered_contents="p",
        rendered_contents_sha256="148de9c5a7a44d19e56cd9ae1a554bf67847afb0c58f6e12fa29ac7ddfca9940",
        prompt_sha256="a" * 64,
        input_packet_sha256="b" * 64,
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        request.stage = "task_extraction"


def test_missing_provider_fails_closed():
    with pytest.raises(ExtractionError) as excinfo:
        require_provider(None)
    assert excinfo.value.reason_code == "provider_required"


def test_a_wrongly_shaped_object_fails_closed():
    with pytest.raises(ExtractionError) as excinfo:
        require_provider(_WrongShape())
    assert excinfo.value.reason_code == "provider_protocol_invalid"


@pytest.mark.parametrize("candidate", [object(), 7, "provider", [], {}])
def test_arbitrary_objects_are_refused(candidate):
    with pytest.raises(ExtractionError):
        require_provider(candidate)


def test_an_injected_fake_satisfies_the_protocol_and_is_returned_unchanged():
    provider = _FakeProvider()
    assert isinstance(provider, ExtractionProvider)
    assert require_provider(provider) is provider


def test_a_fake_may_permit_a_run_so_the_terminal_path_stays_testable():
    provider = _FakeProvider()
    provider.assert_run_permitted(authorization_sha256="a" * 64)
    assert provider.permitted == 1
    assert provider.seen_digest == "a" * 64
    assert provider.client_contract()["contract"].startswith("extraction_provider")


def test_the_fake_round_trips_a_request_without_touching_the_network():
    provider = require_provider(_FakeProvider())
    response = provider.complete(
        ProviderRequest(
            stage="product_extraction",
            rendered_contents="prompt",
            rendered_contents_sha256="cf07194ee232eb531e15f690000d19846dea69cf05504782658afcfacb9228a2",
            prompt_sha256="c" * 64,
            input_packet_sha256="d" * 64,
        )
    )
    assert isinstance(response, ProviderResponse)
    assert isinstance(response.raw_bytes, bytes)
    assert response.prompt_model_metadata == {"prompt_sha256": "c" * 64}


# --- ADR-043 (E-M): protocol v8 declared alongside v7 -------------------------


def test_v8_is_declared_beside_v7_and_does_not_replace_its_value():
    """Rewriting the shared constant would have silently changed the digest of
    every released @0.1.0 client contract, and with it every governance artifact
    that pins one."""
    from dynamic_ai_products.extraction.provider_adapter import (
        PROVIDER_PROTOCOL_VERSION,
        PROVIDER_PROTOCOL_VERSION_V8,
    )

    assert PROVIDER_PROTOCOL_VERSION == "extraction_provider_protocol_v7"
    assert PROVIDER_PROTOCOL_VERSION_V8 == "extraction_provider_protocol_v8"


def test_a_budget_admission_is_frozen_and_single_use():
    from dataclasses import FrozenInstanceError

    from dynamic_ai_products.extraction.provider_adapter import BudgetAdmission

    admission = BudgetAdmission(
        measured_input_tokens=10,
        reserved_cost_microdollars=1,
        generate_attempt_cap=3,
        provider_request_digest="a" * 64,
        session_nonce="nonce",
    )
    with pytest.raises(FrozenInstanceError):
        admission.measured_input_tokens = 11
    assert admission.spent is False
    admission.spend()
    assert admission.spent is True
    with pytest.raises(ExtractionError) as caught:
        admission.spend()
    assert caught.value.reason_code == "budget_admission_invalid"


def test_the_sink_error_carries_both_reasons_and_no_bytes():
    """A persistence failure and a provider failure can both be true at once."""
    from dataclasses import fields

    from dynamic_ai_products.extraction.provider_adapter import CaptureRecord, CaptureSinkError

    error = CaptureSinkError(
        operation_label="generate_content",
        attempt_ordinal=2,
        persistence_reason_code="write_error",
        provider_reason_code="vertex_unavailable",
    )
    assert error.persistence_reason_code == "write_error"
    assert error.provider_reason_code == "vertex_unavailable"
    assert not any(isinstance(value, (bytes, bytearray)) for value in vars(error).values())
    # The return path carries digests, never bytes.
    annotations = {field.name: str(field.type) for field in fields(CaptureRecord)}
    assert not any("bytes" in text for text in annotations.values())
