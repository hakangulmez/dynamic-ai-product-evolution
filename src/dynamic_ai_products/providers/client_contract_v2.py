"""The declared provider-client contract, v2 (ADR-043, E-M).

Successor of :mod:`~dynamic_ai_products.providers.client_contract`, which is left
byte-identical. ``extraction_provider_client_contract@0.1.0`` could not carry this
increment: its ``model_parameters`` object is closed, so ``thinking_config`` had
nowhere to live, and widening a released contract is forbidden.

Like its predecessor this builder is **pure and in-memory**: no network, no
filesystem, no clock, no environment read, no SDK access, and no credential. It
returns a plain mapping; serialization and write-once persistence belong to the
extraction orchestrator.

Three declarations here are easy to misread and are therefore stated once:

- ``generate_retry_max_attempts`` and ``external_request_max`` are **structural
  maxima of the connector**. A run's effective cap is derived from the
  authorization -- ``min(3, budget_max_external_requests - 1)`` -- and may only
  be narrower. The effective cap is never written into this contract, because it
  changes per run while the contract is hash-pinned by governance.
- ``count_timeout_duration`` is a **policy declaration, not a measurement**. The
  300s value was resolved for ``generateContent``; it was never measured for
  ``countTokens``. :func:`build_client_contract_v2` binds the two mechanically so
  they cannot drift apart silently.
- ``wire_thinking_budget_key`` records what the pinned SDK actually puts on the
  wire. Measured against ``google-genai==2.13.0``: the Vertex converter passes the
  thinking config through unchanged and ``convert_to_dict`` applies no aliases, so
  the terminal request body carries ``thinking_budget``, not ``thinkingBudget``.
"""

from __future__ import annotations

from typing import Any

from .client_contract import (
    AUTH_METHOD,
    MODEL_NAME,
    MODEL_PARAMETERS,
    MODEL_PROVIDER,
    SDK_NAME,
    SDK_VERSION,
    VERTEX_LOCATION,
    build_client_contract,
)
from .errors import ProviderError
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
    "CLIENT_CONTRACT_V2_ID",
    "CLIENT_MODULE_V2",
    "CLIENT_VERSION_V2",
    "COUNT_RETRY_MAX_ATTEMPTS",
    "EXTERNAL_REQUEST_MAX",
    "GENERATION_CONFIG_PROJECTION",
    "PROVIDER_PROTOCOL_VERSION_PIN_V2",
    "THINKING_CONFIG",
    "WIRE_THINKING_BUDGET_KEY",
    "build_client_contract_v2",
    "build_operation_endpoints",
    "resolve_effective_generate_cap",
]

CLIENT_CONTRACT_V2_ID = "extraction_provider_client_contract@0.2.0"
CLIENT_MODULE_V2 = "dynamic_ai_products.providers.vertex_gemini_v2"
CLIENT_VERSION_V2 = "0.2.0"

# Closed static pin of the protocol constant, mirroring the v1 builder. A drift
# test re-derives it from ``extraction.provider_adapter``.
PROVIDER_PROTOCOL_VERSION_PIN_V2 = "extraction_provider_protocol_v8"

# countTokens is exactly one send: an empty or malformed body is not a declared
# retry trigger, so retrying it would repeat a condition the policy never named.
COUNT_RETRY_MAX_ATTEMPTS = 1
# Structural maximum: one count send plus the generate attempt ceiling.
EXTERNAL_REQUEST_MAX = COUNT_RETRY_MAX_ATTEMPTS + RETRY_MAX_ATTEMPTS

# The verified evidence says a zero budget prevents thought content from being
# returned; it also says reasoning-style text may still be present in the output,
# and the price row bills "response and reasoning" alike. Nothing here claims
# reasoning tokens are unbilled.
THINKING_CONFIG: dict[str, int] = {"thinking_budget": 0}
WIRE_THINKING_BUDGET_KEY = "thinking_budget"

# One canonical fixed ordering. A permuted list serializes to different canonical
# bytes -- sort_keys orders mapping keys, never list elements -- so two
# semantically identical contracts would acquire divergent provenance digests and
# the authorization's pinned digest would stop matching.
GENERATION_CONFIG_PROJECTION: tuple[str, ...] = (
    "temperature",
    "top_p",
    "candidate_count",
    "max_output_tokens",
    "response_mime_type",
    "thinking_config",
)

_HOST_SUFFIX = "-aiplatform.googleapis.com"
_COUNT_OPERATION = "countTokens"
_GENERATE_OPERATION = "generateContent"


def build_operation_endpoints(
    *, vertex_project: str, vertex_location: str = VERTEX_LOCATION, model_name: str = MODEL_NAME
) -> dict[str, str]:
    """Derive the two exact operation URLs. Pure; performs no I/O.

    No endpoint literal appears in this module: the origin is composed from the
    validated location, so a real destination is never baked into the source.
    Both URLs share one model base by construction, which is what makes the
    per-operation context check meaningful -- the two can only differ in the
    operation suffix.
    """
    # The released v1 builder is the single owner of project and location
    # grammar. Reusing it -- and discarding the result -- keeps one set of rules
    # instead of a second copy that could drift; ``client_contract.py`` itself is
    # left byte-identical.
    build_client_contract(vertex_project=vertex_project, vertex_location=vertex_location)
    if (
        not isinstance(model_name, str)
        or not model_name
        or any(character in model_name for character in "/:?#@ ")
    ):
        raise ProviderError("vertex_model_not_found")
    origin = "https://" + vertex_location + _HOST_SUFFIX
    base = (
        f"{origin}/{API_VERSION}/projects/{vertex_project}"
        f"/locations/{vertex_location}/publishers/google/models/{model_name}"
    )
    return {
        "count_tokens": f"{base}:{_COUNT_OPERATION}",
        "generate_content": f"{base}:{_GENERATE_OPERATION}",
    }


def resolve_effective_generate_cap(budget_max_external_requests: object) -> int:
    """The single request-cap rule, stated once.

    ``budget_max_external_requests`` below two cannot pay for one count send plus
    one generate attempt, so it is refused. Above that the cap is derived, never
    declared: an independent ``budget_max_generate_attempts`` field would be a
    second source of truth that could drift from this formula.
    """
    value = budget_max_external_requests
    if isinstance(value, bool) or not isinstance(value, int) or value < 2:
        raise ProviderError("live_call_not_authorized")
    return min(RETRY_MAX_ATTEMPTS, value - 1)


def build_client_contract_v2(
    *,
    vertex_project: str,
    vertex_location: str = VERTEX_LOCATION,
    model_name: str = MODEL_NAME,
) -> dict[str, Any]:
    """Build the declared v2 client contract. Pure; performs no I/O."""
    endpoints = build_operation_endpoints(
        vertex_project=vertex_project,
        vertex_location=vertex_location,
        model_name=model_name,
    )
    return {
        "contract": CLIENT_CONTRACT_V2_ID,
        "schema_version": "0.2.0",
        "client_module": CLIENT_MODULE_V2,
        "client_version": CLIENT_VERSION_V2,
        "provider_protocol_version": PROVIDER_PROTOCOL_VERSION_PIN_V2,
        "sdk_name": SDK_NAME,
        "sdk_version": SDK_VERSION,
        "model_provider": MODEL_PROVIDER,
        "model_name": model_name,
        "model_parameters": dict(MODEL_PARAMETERS),
        "vertex_project": vertex_project,
        "vertex_location": vertex_location,
        "auth_method": AUTH_METHOD,
        "api_version": API_VERSION,
        "timeout_sdk_parameter": TIMEOUT_SDK_PARAMETER,
        "timeout_duration": TIMEOUT_DURATION,
        "timeout_unit": TIMEOUT_UNIT,
        # Bound to the generate timeout rather than restated, so a change to one
        # cannot leave the other behind. The value is a policy declaration.
        "count_timeout_duration": TIMEOUT_DURATION,
        "count_timeout_unit": TIMEOUT_UNIT,
        "sdk_retry_disabled": True,
        "sdk_retry_attempts": SDK_RETRY_ATTEMPTS,
        "retry_owner": RETRY_OWNER,
        "retry_max_attempts": RETRY_MAX_ATTEMPTS,
        "count_retry_max_attempts": COUNT_RETRY_MAX_ATTEMPTS,
        "generate_retry_max_attempts": RETRY_MAX_ATTEMPTS,
        "external_request_max": EXTERNAL_REQUEST_MAX,
        "retry_trigger_status_codes": list(RETRY_TRIGGER_STATUS_CODES),
        "retry_trigger_transport_timeout": RETRY_TRIGGER_TRANSPORT_TIMEOUT,
        "retry_delays_seconds": list(RETRY_DELAYS_SECONDS),
        "retry_jitter": RETRY_JITTER,
        "retry_policy_version": RETRY_POLICY_VERSION,
        "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
        "fallback_policy": FALLBACK_POLICY,
        "thinking_config": dict(THINKING_CONFIG),
        "thinking_level_used": False,
        "include_thoughts_used": False,
        "wire_thinking_budget_key": WIRE_THINKING_BUDGET_KEY,
        "generation_config_projection": list(GENERATION_CONFIG_PROJECTION),
        "operation_endpoints": endpoints,
        "endpoint_match_mode": "exact_equality",
        "endpoint_query_policy": "reject",
        "protocol_switch_policy": "reject",
    }
