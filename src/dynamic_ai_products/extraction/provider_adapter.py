"""Provider protocol and injection point (ADR-033, E-A).

**E-A carries no network capability whatsoever.** This module declares the
typed surface a provider must satisfy and nothing else: no vendor SDK, no
credential handling, no environment-secret read, no transport construction,
and no call. The concrete connector, model label, parameters, credentials,
and client-contract identity belong to the separately locked E-P increment.

Offline tests satisfy this protocol with an injected fake.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

from .errors import ExtractionError

__all__ = [
    "PROVIDER_PROTOCOL_VERSION",
    "ProviderRequest",
    "ProviderResponse",
    "ExtractionProvider",
    "require_provider",
]

PROVIDER_PROTOCOL_VERSION = "extraction_provider_protocol_v1"


@dataclass(frozen=True)
class ProviderRequest:
    """One extraction request as seen by a provider."""

    stage: str
    prompt_text: str
    prompt_sha256: str
    input_packet_sha256: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class ProviderResponse:
    """A provider's literal output plus the metadata the run manifest records."""

    raw_bytes: bytes
    model_provider: str
    model_name: str
    model_parameters: dict[str, Any]
    prompt_model_metadata: dict[str, Any]


@runtime_checkable
class ExtractionProvider(Protocol):
    """The only provider surface extraction knows about."""

    def complete(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover
        ...


def require_provider(provider: object) -> ExtractionProvider:
    """Fail closed unless an injected object satisfies the protocol."""
    if provider is None:
        raise ExtractionError(
            "an extraction provider must be injected; this package constructs none",
            reason_code="provider_required",
        )
    if not isinstance(provider, ExtractionProvider):
        raise ExtractionError(
            "injected provider does not satisfy the extraction provider protocol",
            reason_code="provider_protocol_invalid",
        )
    return provider
