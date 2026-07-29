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


def test_protocol_version_is_declared():
    assert PROVIDER_PROTOCOL_VERSION == "extraction_provider_protocol_v1"


def test_request_and_response_are_frozen_dataclasses():
    for cls in (ProviderRequest, ProviderResponse):
        assert dataclasses.is_dataclass(cls)
        assert cls.__dataclass_params__.frozen


def test_a_request_cannot_be_mutated_after_construction():
    request = ProviderRequest(
        stage="product_extraction",
        prompt_text="p",
        prompt_sha256="a" * 64,
        input_packet_sha256="b" * 64,
        payload={},
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


def test_the_fake_round_trips_a_request_without_touching_the_network():
    provider = require_provider(_FakeProvider())
    response = provider.complete(
        ProviderRequest(
            stage="product_extraction",
            prompt_text="prompt",
            prompt_sha256="c" * 64,
            input_packet_sha256="d" * 64,
            payload={"passages": []},
        )
    )
    assert isinstance(response, ProviderResponse)
    assert isinstance(response.raw_bytes, bytes)
    assert response.prompt_model_metadata == {"prompt_sha256": "c" * 64}
