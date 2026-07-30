"""The declared provider-client contract document (ADR-034, E-P).

This builder is **pure and in-memory**: no network, no filesystem, no clock, no
environment read, and no SDK access. It returns a plain mapping; serialization
and write-once persistence belong to the extraction orchestrator, because the
only permitted ``providers -> extraction`` edge covers ``provider_adapter``
alone and a second canonical serializer would drift (ADR-027).

The document carries **no secret material**: no credential, key, token, header,
or account identifier. Identity is Application Default Credentials, resolved by
the SDK itself in a later increment; it never passes through this package.
"""

from __future__ import annotations

import re
from typing import Any

from .retry_policy import (
    API_VERSION,
    FALLBACK_POLICY,
    RATE_LIMIT_POLICY_VERSION,
    RETRY_DELAYS_SECONDS,
    RETRY_JITTER,
    RETRY_MAX_ATTEMPTS,
    RETRY_OWNER,
    RETRY_POLICY_VERSION,
    RETRY_TRIGGER_STATUS_CODES,
    RETRY_TRIGGER_TRANSPORT_TIMEOUT,
    SDK_RETRY_ATTEMPTS,
    TIMEOUT_DURATION,
    TIMEOUT_SDK_PARAMETER,
    TIMEOUT_UNIT,
)

__all__ = [
    "AUTH_METHOD",
    "CLIENT_CONTRACT_ID",
    "CLIENT_MODULE",
    "CLIENT_VERSION",
    "MODEL_NAME",
    "MODEL_PARAMETERS",
    "MODEL_PROVIDER",
    "PROVIDER_PROTOCOL_VERSION_PIN",
    "SDK_NAME",
    "SDK_VERSION",
    "VERTEX_LOCATION",
    "build_client_contract",
]

CLIENT_CONTRACT_ID = "extraction_provider_client_contract@0.1.0"
CLIENT_MODULE = "dynamic_ai_products.providers.vertex_gemini"
CLIENT_VERSION = "0.1.0"

# Closed static pin of the protocol constant. This package may import only the
# Protocol and the two payload types from provider_adapter, so the version
# string is pinned here and a drift test re-derives it.
PROVIDER_PROTOCOL_VERSION_PIN = "extraction_provider_protocol_v6"

SDK_NAME = "google-genai"
SDK_VERSION = "2.13.0"

MODEL_PROVIDER = "google_vertex_ai"
MODEL_NAME = "gemini-2.5-flash"
VERTEX_LOCATION = "us-central1"
AUTH_METHOD = "application_default_credentials"

MODEL_PARAMETERS: dict[str, Any] = {
    "temperature": 0,
    "top_p": 1,
    "candidate_count": 1,
    "max_output_tokens": 8192,
    "response_mime_type": "application/json",
}

_PROJECT_RE = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")
_ALLOWED_LOCATIONS = ("us-central1",)


def build_client_contract(
    *, vertex_project: str, vertex_location: str = VERTEX_LOCATION
) -> dict[str, Any]:
    """Build the declared client contract. Pure; performs no I/O."""
    from .errors import ProviderError

    if not isinstance(vertex_project, str) or not _PROJECT_RE.fullmatch(vertex_project):
        raise ProviderError("vertex_project_invalid")
    if vertex_location not in _ALLOWED_LOCATIONS:
        raise ProviderError("vertex_location_invalid")
    return {
        "contract": CLIENT_CONTRACT_ID,
        "schema_version": "0.1.0",
        "client_module": CLIENT_MODULE,
        "client_version": CLIENT_VERSION,
        "provider_protocol_version": PROVIDER_PROTOCOL_VERSION_PIN,
        "sdk_name": SDK_NAME,
        "sdk_version": SDK_VERSION,
        "model_provider": MODEL_PROVIDER,
        "model_name": MODEL_NAME,
        "model_parameters": dict(MODEL_PARAMETERS),
        "vertex_project": vertex_project,
        "vertex_location": vertex_location,
        "auth_method": AUTH_METHOD,
        "api_version": API_VERSION,
        "timeout_sdk_parameter": TIMEOUT_SDK_PARAMETER,
        "timeout_duration": TIMEOUT_DURATION,
        "timeout_unit": TIMEOUT_UNIT,
        "sdk_retry_disabled": True,
        "sdk_retry_attempts": SDK_RETRY_ATTEMPTS,
        "retry_owner": RETRY_OWNER,
        "retry_max_attempts": RETRY_MAX_ATTEMPTS,
        "retry_trigger_status_codes": list(RETRY_TRIGGER_STATUS_CODES),
        "retry_trigger_transport_timeout": RETRY_TRIGGER_TRANSPORT_TIMEOUT,
        "retry_delays_seconds": list(RETRY_DELAYS_SECONDS),
        "retry_jitter": RETRY_JITTER,
        "retry_policy_version": RETRY_POLICY_VERSION,
        "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
        "fallback_policy": FALLBACK_POLICY,
    }
