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
    assert PROVIDER_PROTOCOL_VERSION == "extraction_provider_protocol_v6"


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
            prompt_text="prompt",
            prompt_sha256="c" * 64,
            input_packet_sha256="d" * 64,
            payload={"passages": []},
        )
    )
    assert isinstance(response, ProviderResponse)
    assert isinstance(response.raw_bytes, bytes)
    assert response.prompt_model_metadata == {"prompt_sha256": "c" * 64}
