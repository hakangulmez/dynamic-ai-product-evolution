"""Provider-run provenance and the non-run record (ADR-033).

``extraction_run@0.1.0`` is adopted **unchanged**: it is strict with fifteen
properties and carries no provider-client-contract field. The client contract
is bound instead as a byte-referenced entry in the prediction manifest's
``source_artifacts``.

A pre-provider non-run writes **no** ``extraction_run``: that contract requires
``prompt_hash`` and ``source_manifest_hash`` and denotes a provider run, so
emitting one with a stopped status would assert a run that never began.

``extraction_run@0.1.0`` also carries ``status`` and ``error_count`` but **no**
``error_reason``, so an errored run alone would lose the terminal cause. The
contract is not widened; the reason is bound in the companion
``extraction_provider_error_record@0.1.0`` instead (ADR-034), the same shape of
decision that bound the provider-client contract to the prediction manifest
rather than adding a field here.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from .errors import ExtractionError
from .raw_artifacts import canonical_json_bytes

__all__ = [
    "ACCEPTED_PACKET_CONTRACTS",
    "AUTHORIZATION_PROPERTIES",
    "AUTHORIZATION_V2_PROPERTIES",
    "BUDGET_POLICY_VERSION",
    "CANONICAL_BUDGET_METER_IDENTITY",
    "CANONICAL_BUDGET_METER_VERSION",
    "CLIENT_CONTRACT_CONTRACT",
    "CLIENT_CONTRACT_PROPERTIES",
    "CLIENT_CONTRACT_V2_CONTRACT",
    "CLIENT_CONTRACT_V2_SCHEMA_VERSION",
    "ENABLEMENT_CONTRACT",
    "ENABLEMENT_PROPERTIES",
    "ENABLEMENT_STATUS_FOR_ROLLOUT",
    "EXTRACTION_RUN_PROPERTIES",
    "GOVERNANCE_SCHEMA_VERSION",
    "LIVE_AUTHORIZATION_CONTRACT",
    "LIVE_AUTHORIZATION_V2_CONTRACT",
    "NON_RUN_CONTRACT",
    "NON_RUN_REASONS",
    "PACKET_CONTRACT_REQUIRING_IDENTITY",
    "PROVIDER_COUNT_TIMEOUT_SECONDS_PIN",
    "PROVIDER_DECLARED_MAX_OUTPUT_TOKENS_PIN",
    "PROVIDER_ERROR_CONTRACT",
    "PROVIDER_ERROR_REASONS",
    "PROVIDER_MAX_ATTEMPTS_PIN",
    "PROVIDER_RATE_LIMIT_POLICY_VERSION_PIN",
    "PROVIDER_RETRY_DELAYS_PIN",
    "PROVIDER_RETRY_POLICY_VERSION_PIN",
    "PROVIDER_TIMEOUT_SECONDS_PIN",
    "PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS",
    "PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS_V2",
    "QUALIFICATION_CONTRACT",
    "QUALIFICATION_PROPERTIES",
    "STAGE_OUTPUT_CONTRACT_ID",
    "STAGE_OUTPUT_SCHEMA",
    "STAGE_OUTPUT_SCHEMA_SHA256",
    "build_extraction_run",
    "build_non_run_record",
    "build_provider_error_record",
    "record_bytes",
    "resolve_attempt_cap",
    "resolve_attempt_cap_v2",
    "resolve_stage_schema_hash",
    "validate_authorization_client_contract",
    "validate_authorization_scope",
    "validate_budget_meter_identity",
    "validate_governance_chain",
    "validate_governance_chain_v2",
    "validate_governance_semantics",
    "validate_provider_client_contract",
    "validate_provider_policy_versions",
    "validate_qualification_execution_contract",
    "validate_v2_contract_execution_fields",
    "wall_clock_floor_for_cap",
]

NON_RUN_CONTRACT = "extraction_non_run_record@0.1.0"
CLIENT_CONTRACT_CONTRACT = "extraction_provider_client_contract@0.1.0"
# ADR-048 (G3-3). The v2 identity lived in ``run_extraction`` until now, which
# was tolerable while only the runner needed it. It is not tolerable once
# ``routing_contract`` needs the same identity for a call that never goes
# through the runner: two module-level strings would be two sources of truth for
# one contract. One owner here, imported by both, and an AST invariant keeps the
# literal from being spelled a second time anywhere under ``extraction``.
CLIENT_CONTRACT_V2_CONTRACT = "extraction_provider_client_contract@0.3.0"
CLIENT_CONTRACT_V2_SCHEMA_VERSION = "0.3.0"
PROVIDER_ERROR_CONTRACT = "extraction_provider_error_record@0.1.0"
QUALIFICATION_CONTRACT = "adapter_qualification_record@0.1.0"
ENABLEMENT_CONTRACT = "adapter_enablement_record@0.1.0"
LIVE_AUTHORIZATION_CONTRACT = "live_call_authorization@0.1.0"
# ADR-036 (E-R). The packet contracts a run may present. ``@0.1.0`` remains
# valid for the non-run route, which renders nothing and therefore needs no legal
# name; the authorized route requires ``@0.2.0`` because the renderer cannot bind
# ``{{company_name}}`` without it. A packet naming anything else is refused
# rather than assumed to be one of these.
ACCEPTED_PACKET_CONTRACTS: tuple[str, ...] = (
    "extraction_input_packet@0.1.0",
    "extraction_input_packet@0.2.0",
)
PACKET_CONTRACT_REQUIRING_IDENTITY = "extraction_input_packet@0.2.0"

GOVERNANCE_SCHEMA_VERSION = "0.1.0"

# Closed rollout -> enablement-status mapping. ``full_scale`` is deliberately
# absent: SPEC-027 declares no "enabled" status for it, and admitting it would
# be premature scale (CLAUDE.md rule 10). ``mock_only`` means "no network" by
# definition and can never authorize a live call.
# Closed stage -> output-contract identity map. Without it, two records could
# agree on an arbitrary identity while carrying the correct released digest, and
# the identity would assert nothing about which stage was qualified.
STAGE_OUTPUT_CONTRACT_ID: dict[str, str] = {
    "product_extraction": "product_observation@0.1.0",
    "capability_extraction": "capability_observation@0.1.0",
    "task_extraction": "task_observation@0.1.0",
}

ENABLEMENT_STATUS_FOR_ROLLOUT: dict[str, str] = {
    "live_dev": "enabled_live_dev",
    "controlled_pilot": "enabled_pilot",
    "release_or_research_production": "enabled_release",
}

# Closed static pins of the E-P execution policy. ``extraction`` may not import
# ``providers``, so the values are pinned here and a drift test re-derives each
# one from providers.retry_policy.
#
# ADR-048 (G3-3) adds the two policy-version pins to the same family. They are
# not decoration: before this increment ``retry_policy_version`` and
# ``rate_limit_policy_version`` were declared by the authorization, declared
# again by the client contract, and **never compared to anything** -- measured
# across the whole repository. The pin is what makes the comparison mean
# something: two artifacts that echo one wrong value at each other agree
# perfectly, and only a third, code-owned side can say they are both wrong.
#
# The rate-limit name is shared with a different layer. ``collection.transport``
# declares its own ``rate_limit_policy_version = "rate_limit_policy_v1"`` for
# HTTP source retrieval; the provider policy below is a different value in a
# different namespace. Pinning it here states which one a model-execution run
# means, so an authorization carrying the collection spelling is refused instead
# of silently accepted.
PROVIDER_RETRY_POLICY_VERSION_PIN = "extraction_provider_retry_policy_v1"
PROVIDER_RATE_LIMIT_POLICY_VERSION_PIN = "extraction_provider_rate_limit_policy_v1"
PROVIDER_MAX_ATTEMPTS_PIN = 3
PROVIDER_TIMEOUT_SECONDS_PIN = 300
PROVIDER_RETRY_DELAYS_PIN: tuple[int, ...] = (1, 2)
PROVIDER_DECLARED_MAX_OUTPUT_TOKENS_PIN = 8192
# 3 attempts x 300s + (1 + 2)s of backoff. A theoretical ceiling only: real
# elapsed enforcement belongs to the injected budget meter.
PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS = 903

QUALIFICATION_PROPERTIES: frozenset[str] = frozenset(
    {
        "contract",
        "schema_version",
        "qualification_id",
        "adapter_identity",
        "adapter_version",
        "adapter_family",
        "execution_contract_id",
        "execution_contract_sha256",
        "stage_output_contract_id",
        "stage_output_contract_sha256",
        "qualification_scope",
        "qualification_status",
        "qualified_at",
    }
)

ENABLEMENT_PROPERTIES: frozenset[str] = frozenset(
    {
        "contract",
        "schema_version",
        "enablement_id",
        "adapter_qualification_record_reference",
        "adapter_qualification_record_sha256",
        "prompt_qualification_reference",
        "prompt_qualification_sha256",
        "stage",
        "stage_output_contract_id",
        "stage_output_contract_sha256",
        "routing_contract_id",
        "routing_contract_sha256",
        "deployment_environment_id",
        "rollout_state",
        "endpoint_allowlist",
        "enablement_status",
        "approver",
        "effective_at",
        "expires_at",
    }
)

AUTHORIZATION_PROPERTIES: frozenset[str] = frozenset(
    {
        "contract",
        "schema_version",
        "authorization_id",
        "authorized_by",
        "effective_at",
        "expires_at",
        "deployment_environment_id",
        "rollout_state",
        "adapter_enablement_record_reference",
        "adapter_enablement_record_sha256",
        "provider_client_contract_reference",
        "provider_client_contract_sha256",
        "budget_meter_identity",
        "budget_meter_version",
        "stage",
        "company_id",
        "observation_cutoff_date",
        "corpus_scope",
        "budget_max_records",
        "budget_max_requests",
        "budget_max_input_tokens",
        "budget_max_output_tokens",
        "budget_max_estimated_cost_micros",
        "budget_max_wall_clock_seconds",
        "budget_policy_version",
        "retry_policy_version",
        "rate_limit_policy_version",
        "endpoint_allowlist",
        "circuit_breaker_max_consecutive_failures",
        "provider_called",
        "harness_run",
    }
)

# Closed enum, identical to the released schema. ``live_call_not_authorized`` is
# deliberately absent: it is refused before any provider attempt begins, so no
# artifact — and therefore no record — exists on that path.
PROVIDER_ERROR_REASONS: tuple[str, ...] = (
    "provider_timeout",
    "vertex_quota_exhausted",
    "vertex_unavailable",
    "vertex_permission_denied",
    "vertex_model_not_found",
    "vertex_project_invalid",
    "vertex_location_invalid",
    "adc_not_configured",
    "adc_refresh_failed",
    "adc_expired",
    "provider_response_unusable",
)

# The released client-contract property set. Nothing outside it may be emitted.
CLIENT_CONTRACT_PROPERTIES: frozenset[str] = frozenset(
    {
        "contract",
        "schema_version",
        "client_module",
        "client_version",
        "provider_protocol_version",
        "sdk_name",
        "sdk_version",
        "model_provider",
        "model_name",
        "model_parameters",
        "vertex_project",
        "vertex_location",
        "auth_method",
        "api_version",
        "timeout_sdk_parameter",
        "timeout_duration",
        "timeout_unit",
        "sdk_retry_disabled",
        "sdk_retry_attempts",
        "retry_owner",
        "retry_max_attempts",
        "retry_trigger_status_codes",
        "retry_trigger_transport_timeout",
        "retry_delays_seconds",
        "retry_jitter",
        "retry_policy_version",
        "rate_limit_policy_version",
        "fallback_policy",
    }
)

# Key names that must never appear in a published contract, and value
# signatures that must never appear inside one. Detection **raises**; a silent
# rewrite would be repair-in-place (CLAUDE.md rule 9).
#
# The split matters: a bare ``token`` substring would reject the legitimate
# ``max_output_tokens`` budget, conflating a token *count* with a token
# *value*. Exact names cover a field that simply is a credential; compound
# fragments cover the ways one is usually spelled.
_CREDENTIAL_KEY_NAMES: frozenset[str] = frozenset(
    {
        "token",
        "key",
        "secret",
        "password",
        "credential",
        "credentials",
        "authorization",
        "bearer",
    }
)
_CREDENTIAL_KEY_FRAGMENTS: tuple[str, ...] = (
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
    "id_token",
    "auth_token",
    "bearer_token",
    "private_key",
    "secret_key",
    "client_secret",
    "password",
    "credential",
)
_CREDENTIAL_VALUE_SIGNATURES: tuple[str, ...] = (
    "-----BEGIN",
    "ya29.",
    "AIza",
)

NON_RUN_REASONS: tuple[str, ...] = (
    "zero_admissible_passages",
    "all_passages_temporally_invalid",
    "input_packet_empty_after_filters",
    "corpus_binding_unverified",
    "source_snapshot_unavailable",
)

# The released contract's exact property set. Nothing outside it may be emitted.
EXTRACTION_RUN_PROPERTIES: frozenset[str] = frozenset(
    {
        "run_id",
        "stage",
        "started_at",
        "completed_at",
        "status",
        "code_commit",
        "spec_version",
        "schema_hash",
        "prompt_hash",
        "source_manifest_hash",
        "model_provider",
        "model_name",
        "model_parameters",
        "fallbacks",
        "error_count",
    }
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# The authoritative output contract per stage: the released observation schema
# each stage's extracted records must validate against. schema_hash is the
# SHA-256 over that file's exact bytes, verified against the closed pin before
# extraction_run is built. Measured read-only from the committed files.
STAGE_OUTPUT_SCHEMA = {
    "product_extraction": "product_observation.schema.json",
    "capability_extraction": "capability_observation.schema.json",
    "task_extraction": "task_observation.schema.json",
}
STAGE_OUTPUT_SCHEMA_SHA256 = {
    "product_extraction": "2d2adcb0b24313c58ed27c51708e4e680e0d4c5abe099ae02788217c45cf1eae",
    "capability_extraction": "4ade397f3383ff756a1aa2ba5f98bdb99f76c002d5cf049d7e8dcd7abf493733",
    "task_extraction": "b135ab828a3b710f1c63f6a8bf473caa6e29c3a63a5330cb203b470f772e3b03",
}


def resolve_stage_schema_hash(stage: str, schema_root: str = "schemas") -> str:
    """Read the stage's released schema and verify it against the closed pin."""
    from pathlib import Path as _Path

    from .raw_artifacts import sha256_bytes

    if stage not in STAGE_OUTPUT_SCHEMA:
        raise ExtractionError(
            f"unknown extraction stage: {stage!r}", reason_code="packet_stage_invalid"
        )
    target = _Path(schema_root) / STAGE_OUTPUT_SCHEMA[stage]
    try:
        observed = sha256_bytes(target.read_bytes())
    except OSError as exc:
        raise ExtractionError(
            f"released output schema is unreadable: {target}",
            reason_code="schema_pin_mismatch",
        ) from exc
    expected = STAGE_OUTPUT_SCHEMA_SHA256[stage]
    if observed != expected:
        raise ExtractionError(
            f"released output schema does not match its pin: {target}",
            reason_code="schema_pin_mismatch",
            detail=f"expected {expected}, observed {observed}",
        )
    return observed


SPEC_VERSION_FOR_STAGE = {
    "product_extraction": "SPEC-008",
    "capability_extraction": "SPEC-009",
    "task_extraction": "SPEC-010",
}


def _require_injected(code_commit: str, run_created_at: str) -> None:
    for name, value in (("code_commit", code_commit), ("run_created_at", run_created_at)):
        if not isinstance(value, str) or not value.strip():
            raise ExtractionError(
                f"{name} must be injected by the caller; this package reads no clock "
                "and no VCS",
                reason_code="run_identity_invalid",
            )


def build_extraction_run(
    *,
    run_id: str,
    stage: str,
    started_at: str,
    completed_at: str,
    status: str,
    code_commit: str,
    schema_hash: str,
    prompt_hash: str,
    source_manifest_hash: str,
    model_provider: str | None = None,
    model_name: str | None = None,
    model_parameters: dict[str, Any] | None = None,
    fallbacks: list[Any] | None = None,
    error_count: int = 0,
) -> dict[str, Any]:
    """Build an ``extraction_run@0.1.0`` record without widening the contract."""
    _require_injected(code_commit, started_at)
    if stage not in SPEC_VERSION_FOR_STAGE:
        raise ExtractionError(
            f"unknown extraction stage: {stage!r}", reason_code="packet_stage_invalid"
        )
    for label, value in (
        ("schema_hash", schema_hash),
        ("prompt_hash", prompt_hash),
        ("source_manifest_hash", source_manifest_hash),
    ):
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ExtractionError(
                f"{label} must be 64 lowercase hex characters", reason_code="pin_invalid"
            )
    record = {
        "run_id": run_id,
        "stage": stage,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": status,
        "code_commit": code_commit,
        "spec_version": SPEC_VERSION_FOR_STAGE[stage],
        "schema_hash": schema_hash,
        "prompt_hash": prompt_hash,
        "source_manifest_hash": source_manifest_hash,
        "model_provider": model_provider,
        "model_name": model_name,
        "model_parameters": dict(model_parameters or {}),
        "fallbacks": list(fallbacks or []),
        "error_count": int(error_count),
    }
    extra = sorted(set(record) - EXTRACTION_RUN_PROPERTIES)
    if extra:
        raise ExtractionError(
            f"extraction_run@0.1.0 may not be widened: {extra}",
            reason_code="contract_widened",
        )
    return record


def build_non_run_record(
    *,
    extraction_run_id: str,
    stage: str,
    company_id: str,
    observation_cutoff_date: str,
    code_commit: str,
    run_created_at: str,
    input_packet_reference: str,
    input_packet_sha256: str,
    coverage_artifact_reference: str,
    coverage_artifact_sha256: str,
    reason_code: str,
    filter_ledger: dict[str, Any],
) -> dict[str, Any]:
    """The sole newly published output on a pre-provider non-run route."""
    _require_injected(code_commit, run_created_at)
    if reason_code not in NON_RUN_REASONS:
        raise ExtractionError(
            f"undeclared non-run reason: {reason_code!r}",
            reason_code="non_run_reason_unknown",
        )
    for label, value in (
        ("input_packet_sha256", input_packet_sha256),
        ("coverage_artifact_sha256", coverage_artifact_sha256),
    ):
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ExtractionError(
                f"{label} must be 64 lowercase hex characters", reason_code="pin_invalid"
            )
    return {
        "contract": NON_RUN_CONTRACT,
        "schema_version": "0.1.0",
        "extraction_run_id": extraction_run_id,
        "stage": stage,
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "code_commit": code_commit,
        "run_created_at": run_created_at,
        "input_packet_reference": input_packet_reference,
        "input_packet_sha256": input_packet_sha256,
        "coverage_artifact_reference": coverage_artifact_reference,
        "coverage_artifact_sha256": coverage_artifact_sha256,
        "reason_code": reason_code,
        "filter_ledger": dict(filter_ledger),
        "provider_called": False,
        "harness_run": False,
    }


def _scan_for_credential_material(node: Any, path: str = "") -> None:
    """Refuse any credential-shaped key or value, at any depth."""
    if isinstance(node, dict):
        for key, value in node.items():
            lowered = str(key).lower()
            hit = lowered in _CREDENTIAL_KEY_NAMES or any(
                fragment in lowered for fragment in _CREDENTIAL_KEY_FRAGMENTS
            )
            if hit:
                raise ExtractionError(
                    f"provider client contract carries a credential-shaped "
                    f"property at {path}{key!r}",
                    reason_code="credential_material_in_artifact",
                )
            _scan_for_credential_material(value, f"{path}{key}.")
    elif isinstance(node, (list, tuple)):
        for index, value in enumerate(node):
            _scan_for_credential_material(value, f"{path}{index}.")
    elif isinstance(node, str):
        for signature in _CREDENTIAL_VALUE_SIGNATURES:
            if signature in node:
                raise ExtractionError(
                    f"provider client contract carries credential material at "
                    f"{path.rstrip('.')!r}",
                    reason_code="credential_material_in_artifact",
                )


def validate_provider_client_contract(contract: Any) -> dict[str, Any]:
    """Strictly validate a connector-supplied client contract.

    Runs entirely in memory, before any run root exists, so a rejected contract
    leaves nothing on disk. The returned mapping is what the orchestrator
    serializes and writes write-once; the connector never asserts a digest.
    """
    if not isinstance(contract, dict):
        raise ExtractionError(
            "provider client contract must be a mapping",
            reason_code="client_contract_invalid",
        )
    # Credential material is scanned FIRST. A leaked credential is almost always
    # an undeclared property too, so running the property-set check first would
    # make this code unreachable for exactly the case it exists to catch. It is
    # refused, never redacted (CLAUDE.md rule 9).
    _scan_for_credential_material(contract)
    if contract.get("contract") != CLIENT_CONTRACT_CONTRACT:
        raise ExtractionError(
            f"provider client contract must declare {CLIENT_CONTRACT_CONTRACT}",
            reason_code="client_contract_invalid",
        )
    observed = set(contract)
    missing = sorted(CLIENT_CONTRACT_PROPERTIES - observed)
    if missing:
        raise ExtractionError(
            f"provider client contract is missing properties: {missing}",
            reason_code="client_contract_invalid",
        )
    extra = sorted(observed - CLIENT_CONTRACT_PROPERTIES)
    if extra:
        raise ExtractionError(
            f"provider client contract carries undeclared properties: {extra}",
            reason_code="client_contract_invalid",
        )
    if contract.get("fallback_policy") != "none":
        raise ExtractionError(
            "a declared fallback requires its own qualified contract",
            reason_code="client_contract_invalid",
        )
    if contract.get("sdk_retry_disabled") is not True or contract.get(
        "sdk_retry_attempts"
    ) != 1:
        raise ExtractionError(
            "the SDK retry layer must be disabled explicitly",
            reason_code="client_contract_invalid",
        )
    return dict(contract)


def build_provider_error_record(
    *,
    extraction_run_id: str,
    stage: str,
    company_id: str,
    code_commit: str,
    input_packet_reference: str,
    input_packet_sha256: str,
    resolved_prompt_reference: str,
    resolved_prompt_sha256: str,
    provider_client_contract_reference: str,
    provider_client_contract_sha256: str,
    extraction_run_reference: str,
    extraction_run_sha256: str,
    reason_code: str,
    attempt_count: int,
) -> dict[str, Any]:
    """Bind the terminal cause of a run whose provider attempts all failed.

    Every field is a closed value or a hash-bound identity. There is no
    free-text property, so an upstream message, body, header, or token cannot
    reach the record.
    """
    if stage not in SPEC_VERSION_FOR_STAGE:
        raise ExtractionError(
            f"unknown extraction stage: {stage!r}", reason_code="packet_stage_invalid"
        )
    if reason_code not in PROVIDER_ERROR_REASONS:
        raise ExtractionError(
            f"undeclared terminal provider reason: {reason_code!r}",
            reason_code="provider_error_reason_unknown",
        )
    if not isinstance(attempt_count, int) or attempt_count < 1:
        raise ExtractionError(
            "attempt_count must be a positive integer; the record exists only "
            "because at least one provider attempt began",
            reason_code="provider_error_attempt_count_invalid",
        )
    pins = {
        "input_packet_sha256": input_packet_sha256,
        "resolved_prompt_sha256": resolved_prompt_sha256,
        "provider_client_contract_sha256": provider_client_contract_sha256,
        "extraction_run_sha256": extraction_run_sha256,
    }
    for label, value in pins.items():
        if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
            raise ExtractionError(
                f"{label} must be 64 lowercase hex characters", reason_code="pin_invalid"
            )
    references = {
        "input_packet_reference": input_packet_reference,
        "resolved_prompt_reference": resolved_prompt_reference,
        "provider_client_contract_reference": provider_client_contract_reference,
        "extraction_run_reference": extraction_run_reference,
    }
    for label, value in references.items():
        if not isinstance(value, str) or not value.strip():
            raise ExtractionError(
                f"{label} must be a non-blank reference", reason_code="pin_invalid"
            )
    return {
        "contract": PROVIDER_ERROR_CONTRACT,
        "schema_version": "0.1.0",
        "extraction_run_id": extraction_run_id,
        "stage": stage,
        "company_id": company_id,
        "code_commit": code_commit,
        **references,
        **pins,
        "reason_code": reason_code,
        "attempt_count": int(attempt_count),
        "provider_called": True,
        "harness_run": False,
    }


# --- SPEC-027 governance chain (ADR-035) --------------------------------------


def _require_exact_properties(
    payload: Any, expected: frozenset[str], *, what: str, code: str
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ExtractionError(f"{what} must be a mapping", reason_code=code)
    # Credential material is scanned FIRST, for the same reason as the client
    # contract: a leaked credential is almost always an undeclared property too.
    _scan_for_credential_material(payload)
    observed = set(payload)
    missing = sorted(expected - observed)
    if missing:
        raise ExtractionError(
            f"{what} is missing properties: {missing}", reason_code=code
        )
    extra = sorted(observed - expected)
    if extra:
        raise ExtractionError(
            f"{what} carries undeclared properties: {extra}", reason_code=code
        )
    return dict(payload)


def _require_pin_pair(payload: dict[str, Any], prefix: str, *, code: str) -> tuple[str, str]:
    reference = payload.get(f"{prefix}_reference")
    digest = payload.get(f"{prefix}_sha256")
    if not isinstance(reference, str) or not reference.strip():
        raise ExtractionError(
            f"{prefix}_reference must be a non-blank reference", reason_code=code
        )
    if not isinstance(digest, str) or not _SHA256_RE.fullmatch(digest):
        raise ExtractionError(
            f"{prefix}_sha256 must be 64 lowercase hex characters", reason_code=code
        )
    return reference, digest


def validate_governance_chain(
    *,
    authorization: Any,
    enablement: Any,
    qualification: Any,
    authorization_pin: dict[str, str],
    enablement_pin: dict[str, str],
    qualification_pin: dict[str, str],
) -> dict[str, Any]:
    """Walk the three-ring chain upward, refusing any broken link.

    Each record pins exactly one ring above it; the chain is never transitive.
    The caller has already re-read and hash-verified each artifact through the
    shared hydrator, so this function verifies that the pins each record
    *declares* are the artifacts that were actually loaded.
    """
    code = "authorization_chain_broken"
    authorization = _require_exact_properties(
        authorization, AUTHORIZATION_PROPERTIES, what="live call authorization", code=code
    )
    enablement = _require_exact_properties(
        enablement, ENABLEMENT_PROPERTIES, what="adapter enablement record", code=code
    )
    qualification = _require_exact_properties(
        qualification,
        QUALIFICATION_PROPERTIES,
        what="adapter qualification record",
        code=code,
    )
    for payload, expected_contract in (
        (authorization, LIVE_AUTHORIZATION_CONTRACT),
        (enablement, ENABLEMENT_CONTRACT),
        (qualification, QUALIFICATION_CONTRACT),
    ):
        if payload.get("contract") != expected_contract:
            raise ExtractionError(
                f"governance record must declare {expected_contract}", reason_code=code
            )
        # The released schemas declare this as a const, but no schema file
        # executes on this path (ADR-032), so the loader enforces it. Without
        # this a record could carry any schema_version and still satisfy the
        # property-set check.
        if payload.get("schema_version") != GOVERNANCE_SCHEMA_VERSION:
            raise ExtractionError(
                f"governance record must declare schema_version "
                f"{GOVERNANCE_SCHEMA_VERSION}",
                reason_code=code,
            )

    declared_enablement = _require_pin_pair(
        authorization, "adapter_enablement_record", code=code
    )
    if declared_enablement != (
        enablement_pin.get("reference"),
        enablement_pin.get("sha256"),
    ):
        raise ExtractionError(
            "the authorization pins a different enablement record", reason_code=code
        )
    declared_qualification = _require_pin_pair(
        enablement, "adapter_qualification_record", code=code
    )
    if declared_qualification != (
        qualification_pin.get("reference"),
        qualification_pin.get("sha256"),
    ):
        raise ExtractionError(
            "the enablement record pins a different qualification record",
            reason_code=code,
        )
    # SPEC-024: a prompt-bearing stage must carry its prompt qualification, and
    # SPEC-027 places that reference on the enablement record, not here.
    _require_pin_pair(enablement, "prompt_qualification", code=code)
    if authorization.get("provider_called") is not True:
        raise ExtractionError(
            "a live-call authorization must declare provider_called", reason_code=code
        )
    if authorization.get("harness_run") is not False:
        raise ExtractionError(
            "a live-call authorization must not declare a harness run",
            reason_code=code,
        )
    _require_sha256_field(authorization_pin.get("sha256"), code)
    return authorization


def _require_sha256_field(value: Any, code: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ExtractionError(
            "the authorization pin sha256 must be 64 lowercase hex characters",
            reason_code=code,
        )
    return value


def _require_aware_instant(value: Any, *, field: str, code: str) -> datetime:
    """Parse a timezone-aware ISO-8601 instant and normalize it to UTC.

    Lexicographic comparison of these strings is wrong, not merely imprecise:
    ``2026-07-01T00:00:00Z`` and ``2026-07-01T02:00:00+02:00`` are the same
    instant but do not compare equal as text, and an offset-bearing timestamp can
    sort on either side of a ``Z`` one regardless of chronology. A naive
    timestamp is refused rather than assumed to be UTC — guessing a zone would
    silently move a window boundary by hours.

    Parsing only; this package reads no clock.
    """
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(
            f"{field} must be a non-blank ISO-8601 instant", reason_code=code
        )
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ExtractionError(
            f"{field} is not a valid ISO-8601 instant: {value!r}", reason_code=code
        ) from exc
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        raise ExtractionError(
            f"{field} must carry an explicit UTC offset; a naive instant would "
            "move the window boundary by an unknown amount",
            reason_code=code,
        )
    return parsed.astimezone(timezone.utc)


def validate_authorization_scope(
    *,
    authorization: dict[str, Any],
    stage: str,
    company_id: str,
    observation_cutoff_date: str,
    corpus_scope: str,
    run_created_at: str,
) -> None:
    """Every scope field must match the run exactly, and the window must hold.

    ``run_created_at`` is caller-injected; this package reads no clock, so the
    validity window is checked against the run's own declared instant. All three
    timestamps are parsed as timezone-aware ISO-8601 and compared
    chronologically in UTC, never as text.
    """
    code = "authorization_scope_mismatch"
    for field, expected in (
        ("stage", stage),
        ("company_id", company_id),
        ("observation_cutoff_date", observation_cutoff_date),
        ("corpus_scope", corpus_scope),
    ):
        if authorization.get(field) != expected:
            raise ExtractionError(
                f"authorization {field} does not match this run", reason_code=code
            )
    effective = _require_aware_instant(
        authorization.get("effective_at"), field="effective_at", code=code
    )
    expires = _require_aware_instant(
        authorization.get("expires_at"), field="expires_at", code=code
    )
    instant = _require_aware_instant(
        run_created_at, field="run_created_at", code=code
    )
    if effective > expires:
        raise ExtractionError(
            "the authorization validity window is inverted: effective_at is "
            "later than expires_at",
            reason_code=code,
        )
    if not (effective <= instant <= expires):
        raise ExtractionError(
            "the run instant lies outside the authorization validity window",
            reason_code=code,
        )


def validate_authorization_client_contract(
    *,
    authorization: dict[str, Any],
    client_contract_reference: str,
    client_contract_sha256: str,
) -> None:
    """The authorized client contract must be byte-identical to this run's.

    This is how SPEC-027's "execution-affecting contract changes never inherit
    enablement" becomes code: change the contract and the authorization dies.
    """
    code = "authorization_client_contract_mismatch"
    reference, digest = _require_pin_pair(
        authorization, "provider_client_contract", code=code
    )
    if reference != client_contract_reference or digest != client_contract_sha256:
        raise ExtractionError(
            "the authorization pins a different provider client contract",
            reason_code=code,
        )


def validate_budget_meter_identity(
    *,
    authorization: dict[str, Any],
    meter_identity: Any,
    expected_budget_policy_version: str,
) -> None:
    """The meter must be the one the authorization names, on the policy it names.

    Two different comparisons, deliberately kept apart (ADR-047).

    The **identity** pair travels through the meter mapping, which reports
    exactly ``meter_identity`` and ``meter_version``. The **policy version** does
    not: it is not a property of a meter instance, and adding it to the mapping
    loop would make this function look for a ``policy_version`` key that no
    session reports, failing every route including the canonical one. It arrives
    as its own required parameter instead, and the caller supplies the code-owned
    constant -- never a value re-derived from the session mapping or from the
    authorization being checked, which would be a tautology.

    ``expected_budget_policy_version`` has no default on purpose: a caller that
    forgets it gets a ``TypeError`` rather than a silently skipped check.

    This enforces the expected operational identity. It does **not**
    structurally prevent an in-process implementation from imitating those
    values; a deliberate imitation is a ``noncanonical_experiment`` under
    SPEC-027 and may never enter an evaluation or production record.
    """
    code = "budget_meter_identity_mismatch"
    if not isinstance(meter_identity, dict):
        raise ExtractionError(
            "the budget meter must report a mapping identity", reason_code=code
        )
    for field in ("budget_meter_identity", "budget_meter_version"):
        expected = authorization.get(field)
        observed = meter_identity.get(field.removeprefix("budget_"))
        if not isinstance(expected, str) or not expected.strip():
            raise ExtractionError(
                f"authorization {field} must be a non-blank string", reason_code=code
            )
        if observed != expected:
            raise ExtractionError(
                f"the injected meter {field} does not match the authorization",
                reason_code=code,
            )
    policy_code = "budget_policy_version_mismatch"
    declared_policy = authorization.get("budget_policy_version")
    if not isinstance(declared_policy, str) or not declared_policy.strip():
        raise ExtractionError(
            "authorization budget_policy_version must be a non-blank string",
            reason_code=policy_code,
        )
    if declared_policy != expected_budget_policy_version:
        raise ExtractionError(
            "the authorization declares a budget policy version this build does "
            "not implement",
            reason_code=policy_code,
        )


def resolve_attempt_cap(*, authorization: dict[str, Any]) -> int:
    """Enforce the arithmetic budget limits and return the attempt cap.

    Three limits are genuinely enforced here: records, requests, and declared
    output tokens. The wall-clock field is a **compatibility floor** only -- it
    proves the budget could accommodate the policy's theoretical ceiling, and
    real elapsed enforcement belongs to the injected meter.
    """
    code = "budget_insufficient"

    def _positive(field: str) -> int:
        value = authorization.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ExtractionError(
                f"{field} must be a positive integer", reason_code=code
            )
        return value

    records = _positive("budget_max_records")
    requests = _positive("budget_max_requests")
    output_tokens = _positive("budget_max_output_tokens")
    wall_clock = _positive("budget_max_wall_clock_seconds")
    breaker = _positive("circuit_breaker_max_consecutive_failures")
    # The meter is the only thing that can check these two; refuse a malformed
    # value here so a missing limit cannot masquerade as an unlimited one.
    _positive("budget_max_input_tokens")
    _positive("budget_max_estimated_cost_micros")

    if records < 1:
        raise ExtractionError("a run needs at least one record", reason_code=code)
    if output_tokens < PROVIDER_DECLARED_MAX_OUTPUT_TOKENS_PIN:
        raise ExtractionError(
            "budget_max_output_tokens is below the declared max_output_tokens; "
            "the run would exceed its budget by construction",
            reason_code=code,
        )
    cap = min(PROVIDER_MAX_ATTEMPTS_PIN, requests)
    floor = cap * PROVIDER_TIMEOUT_SECONDS_PIN + sum(PROVIDER_RETRY_DELAYS_PIN[: cap - 1])
    if wall_clock < floor:
        raise ExtractionError(
            f"budget_max_wall_clock_seconds is below the {cap}-attempt ceiling "
            f"of {floor}s; this is a compatibility floor, not elapsed enforcement",
            reason_code=code,
        )
    # Single-call runs start no second call, so the breaker is validated
    # configuration here and has no further runtime effect.
    if breaker < 1:
        raise ExtractionError(
            "circuit_breaker_max_consecutive_failures must be at least 1",
            reason_code=code,
        )
    return cap


def validate_governance_semantics(
    *,
    authorization: dict[str, Any],
    enablement: dict[str, Any],
    qualification: dict[str, Any],
    stage: str,
    run_created_at: str,
    stage_output_schema_sha256: str,
) -> None:
    """Enforce the governing meaning of the upstream records, not just their hashes.

    A hash-valid chain proves the records are the ones that were pinned. It says
    nothing about whether they are *in force*: without these checks a run can be
    authorized through a revoked qualification, a suspended or expired
    enablement, a different deployment environment, or a rollout state that was
    never meant to reach the network. Every released ``const``/``enum`` in the
    three schemas is re-enforced here, because no schema file executes on this
    path (ADR-032).
    """
    code = "governance_record_not_effective"

    # (2) The adapter must be qualified, and qualified as a model executor: the
    # two adapter families have separate readiness and safety gates.
    if qualification.get("adapter_family") != "model_execution":
        raise ExtractionError(
            "the qualification record is not for a model-execution adapter",
            reason_code=code,
        )
    if qualification.get("qualification_status") != "qualified":
        raise ExtractionError(
            "the adapter qualification is not in force: "
            f"{qualification.get('qualification_status')!r}",
            reason_code=code,
        )

    # (3) The enablement status must be the one this rollout state requires.
    rollout = enablement.get("rollout_state")
    expected_status = ENABLEMENT_STATUS_FOR_ROLLOUT.get(str(rollout))
    if expected_status is None:
        raise ExtractionError(
            f"rollout state {rollout!r} has no enabled status in E-L; "
            "mock_only performs no network and full_scale is premature scale",
            reason_code=code,
        )
    if enablement.get("enablement_status") != expected_status:
        raise ExtractionError(
            f"enablement status {enablement.get('enablement_status')!r} does not "
            f"match rollout state {rollout!r}",
            reason_code=code,
        )

    # (5) One environment, one rollout state, across both records.
    for field in ("deployment_environment_id", "rollout_state"):
        if enablement.get(field) != authorization.get(field):
            raise ExtractionError(
                f"enablement and authorization disagree on {field}", reason_code=code
            )

    # (4) The enablement window must hold at the run instant AND must fully
    # contain the authorization window. Containment matters independently: an
    # authorization must not outlive the enablement it rests on, and checking
    # only the run instant would leave that possible.
    enablement_effective = _require_aware_instant(
        enablement.get("effective_at"), field="enablement effective_at", code=code
    )
    enablement_expires = _require_aware_instant(
        enablement.get("expires_at"), field="enablement expires_at", code=code
    )
    instant = _require_aware_instant(run_created_at, field="run_created_at", code=code)
    if enablement_effective > enablement_expires:
        raise ExtractionError(
            "the enablement validity window is inverted", reason_code=code
        )
    if not (enablement_effective <= instant <= enablement_expires):
        raise ExtractionError(
            "the run instant lies outside the enablement validity window",
            reason_code=code,
        )
    authorization_effective = _require_aware_instant(
        authorization.get("effective_at"), field="effective_at", code=code
    )
    authorization_expires = _require_aware_instant(
        authorization.get("expires_at"), field="expires_at", code=code
    )
    if (
        authorization_effective < enablement_effective
        or authorization_expires > enablement_expires
    ):
        raise ExtractionError(
            "the authorization window is not fully contained by the enablement "
            "window; an authorization may not outlive its enablement",
            reason_code=code,
        )

    # (7) One stage, one stage-output contract, agreed by both records and equal
    # to the released schema this run actually validates against.
    if enablement.get("stage") != stage:
        raise ExtractionError(
            "the enablement record was issued for a different stage", reason_code=code
        )
    for field in ("stage_output_contract_id", "stage_output_contract_sha256"):
        if qualification.get(field) != enablement.get(field):
            raise ExtractionError(
                f"qualification and enablement disagree on {field}", reason_code=code
            )
    # Mutual agreement is not enough: both records could name the same arbitrary
    # identity while carrying the correct digest, and the identity would then
    # assert nothing about which stage was qualified.
    expected_contract_id = STAGE_OUTPUT_CONTRACT_ID.get(stage)
    if expected_contract_id is None:
        raise ExtractionError(
            f"no stage-output contract identity is declared for stage {stage!r}",
            reason_code=code,
        )
    for record, label in ((qualification, "qualification"), (enablement, "enablement")):
        if record.get("stage_output_contract_id") != expected_contract_id:
            raise ExtractionError(
                f"the {label} stage-output contract identity is not "
                f"{expected_contract_id} for stage {stage!r}",
                reason_code=code,
            )
    if enablement.get("stage_output_contract_sha256") != stage_output_schema_sha256:
        raise ExtractionError(
            "the enablement stage-output contract is not the released schema this "
            "run validates against",
            reason_code=code,
        )


def validate_qualification_execution_contract(
    *,
    qualification: dict[str, Any],
    client_contract: dict[str, Any],
    client_contract_sha256: str,
) -> None:
    """The adapter must be qualified for the contract it is about to execute.

    SPEC-027 qualifies an adapter *under a specific execution contract*. If the
    qualification names a different contract identity or digest, the adapter was
    never qualified for this run's actual configuration, and
    "execution-affecting contract changes never inherit enablement" would be a
    slogan rather than a rule.

    Called after the client contract is validated, because only then is its
    digest known. Still before ``mkdir``, the meter, the factory, and the
    network, so a refusal leaves zero artifacts.
    """
    code = "governance_record_not_effective"
    if qualification.get("execution_contract_id") != client_contract.get("contract"):
        raise ExtractionError(
            "the qualification names a different execution contract identity",
            reason_code=code,
        )
    if qualification.get("execution_contract_sha256") != client_contract_sha256:
        raise ExtractionError(
            "the adapter was qualified under a different execution contract digest",
            reason_code=code,
        )


# --- ADR-048 (G3-3): the narrow v2 identity gate and the policy pins ----------

_CLIENT_CONTRACT_INVALID = "client_contract_invalid"

# Exactly the non-empty string fields the routing projection and the policy
# validator read. Not "the v2 contract" -- see the docstring below.
_V2_EXECUTION_TEXT_FIELDS: tuple[str, ...] = (
    "api_version",
    "endpoint_match_mode",
    "endpoint_query_policy",
    "protocol_switch_policy",
    "rate_limit_policy_version",
    "retry_policy_version",
)
_V2_OPERATION_LABELS: frozenset[str] = frozenset({"count_tokens", "generate_content"})


def validate_v2_contract_execution_fields(contract: Any) -> dict[str, Any]:
    """Refuse anything the two downstream v2 readers cannot safely read.

    **This is not a v2 schema execution.** ``extraction_provider_client_contract_v2``
    declares forty-two properties under ``additionalProperties: false``; this
    gate looks at nine. The other thirty-three are protected exactly as before,
    by ``provider_client_contract_sha256`` -- the authorization pins the digest
    of the whole contract, so a changed field anywhere in it breaks that pin.
    What this gate adds is narrower and specific: the fields
    :func:`~dynamic_ai_products.extraction.routing_contract.derive_routing_contract`
    and :func:`validate_provider_policy_versions` are about to read.

    The identity pair is checked here and not only in the runner because
    ``derive_routing_contract`` will be called by G4 materialization with no
    runner in the picture at all. A v1 contract has no ``operation_endpoints``,
    no ``endpoint_match_mode`` and no ``protocol_switch_policy``; handed to the
    projection unchecked it would either raise ``KeyError`` or -- worse -- some
    future partial mapping would hash cleanly into a digest that describes a
    route nobody can execute. So the producer refuses a non-v2 surface itself
    rather than trusting a caller to have checked.

    Endpoint **grammar** is deliberately absent. Scheme, host, port, path, the
    operation suffixes and the shared model base belong to
    ``providers.endpoint_grammar_v2``, which ``extraction`` may not import;
    writing a second normalizer here would create the second grammar owner that
    module exists to prevent. Only the mapping shape is checked, and the digest
    downstream binds the endpoint strings as bytes.
    """
    if not isinstance(contract, dict):
        raise ExtractionError(
            "a v2 client contract must be a mapping", reason_code=_CLIENT_CONTRACT_INVALID
        )
    if contract.get("contract") != CLIENT_CONTRACT_V2_CONTRACT:
        raise ExtractionError(
            f"the two-operation surface requires {CLIENT_CONTRACT_V2_CONTRACT}",
            reason_code=_CLIENT_CONTRACT_INVALID,
        )
    if contract.get("schema_version") != CLIENT_CONTRACT_V2_SCHEMA_VERSION:
        raise ExtractionError(
            f"a v2 client contract must declare schema_version "
            f"{CLIENT_CONTRACT_V2_SCHEMA_VERSION}",
            reason_code=_CLIENT_CONTRACT_INVALID,
        )
    for field in _V2_EXECUTION_TEXT_FIELDS:
        value = contract.get(field)
        if not isinstance(value, str) or not value:
            raise ExtractionError(
                f"a v2 client contract must declare a non-empty {field}",
                reason_code=_CLIENT_CONTRACT_INVALID,
            )
    endpoints = contract.get("operation_endpoints")
    # Equality, not superset: a third operation would be a destination this route
    # never authorized, and a missing one would leave half the route undeclared.
    if not isinstance(endpoints, dict) or set(endpoints) != _V2_OPERATION_LABELS:
        raise ExtractionError(
            "operation_endpoints must name exactly count_tokens and generate_content",
            reason_code=_CLIENT_CONTRACT_INVALID,
        )
    for label in sorted(_V2_OPERATION_LABELS):
        url = endpoints[label]
        if not isinstance(url, str) or not url:
            raise ExtractionError(
                f"the {label} endpoint must be a non-empty string",
                reason_code=_CLIENT_CONTRACT_INVALID,
            )
    return dict(contract)


def validate_provider_policy_versions(
    *, authorization: dict[str, Any], client_contract: dict[str, Any]
) -> None:
    """Bind both policy versions to the code, on both sides, separately.

    Four comparisons rather than one. Comparing the authorization with the
    contract would accept two artifacts that echo one wrong value at each other;
    each side is therefore compared with the pin instead, and their agreement
    follows rather than being assumed.

    Order is part of the contract, not an implementation detail: retry is
    resolved before rate limit, so a run whose two policy versions have *both*
    drifted always reports ``retry_policy_version_mismatch``. A caller reading
    the reason code learns something stable rather than something that depends
    on dict ordering.

    Called after the shape gate, so every field read here is already known to be
    a non-empty string, and before ``mkdir``, so a refusal leaves zero artifacts.
    """
    for field, pin, code in (
        (
            "retry_policy_version",
            PROVIDER_RETRY_POLICY_VERSION_PIN,
            "retry_policy_version_mismatch",
        ),
        (
            "rate_limit_policy_version",
            PROVIDER_RATE_LIMIT_POLICY_VERSION_PIN,
            "rate_limit_policy_version_mismatch",
        ),
    ):
        if client_contract.get(field) != pin:
            raise ExtractionError(
                f"the executing client contract declares a {field} this build does "
                f"not implement",
                reason_code=code,
            )
        if authorization.get(field) != pin:
            raise ExtractionError(
                f"the authorization declares a {field} this build does not implement",
                reason_code=code,
            )


def record_bytes(record: dict[str, Any]) -> bytes:
    return canonical_json_bytes(record)


# --- ADR-043 (E-M): two-operation budget arithmetic --------------------------

LIVE_AUTHORIZATION_V2_CONTRACT = "live_call_authorization@0.2.0"

# countTokens carries its own declared timeout. The value equals the generation
# timeout by binding rather than by coincidence; it was never measured for
# countTokens and is a policy declaration.
PROVIDER_COUNT_TIMEOUT_SECONDS_PIN = PROVIDER_TIMEOUT_SECONDS_PIN

# One count send plus three generate attempts and their backoff. A compatibility
# floor, not a physical elapsed-time guarantee: DNS, TLS, credential refresh and
# connection-pool waiting are outside this arithmetic.
PROVIDER_WORST_CASE_WALL_CLOCK_SECONDS_V2 = (
    PROVIDER_COUNT_TIMEOUT_SECONDS_PIN
    + PROVIDER_MAX_ATTEMPTS_PIN * PROVIDER_TIMEOUT_SECONDS_PIN
    + sum(PROVIDER_RETRY_DELAYS_PIN)
)


# --- ADR-047 (G3-2): the code-owned budget identity ---------------------------
#
# Three constants with one home. The authorization declares what it expects; the
# canonical session reports what this build actually is. Before ADR-047 the
# session would have echoed the authorization's own values back at it and the
# comparison would have been a tautology, so the identity a session reports is
# now owned here and never read from the artifact it is checked against.
#
# ``BUDGET_POLICY_VERSION`` is deliberately **not** a third meter-identity field.
# ``meter_identity`` carries exactly two, and the policy version travels through
# its own validator parameter -- folding it into the mapping would make the
# validator look for a ``policy_version`` key that no session reports.
CANONICAL_BUDGET_METER_IDENTITY = "dynamic_ai_products.extraction.budget_session"
CANONICAL_BUDGET_METER_VERSION = "0.1.0"
BUDGET_POLICY_VERSION = "budget_policy_v1"


def wall_clock_floor_for_cap(cap: int) -> int:
    """The compatibility floor implied by an effective generate cap.

    Derived rather than restated, so a change to the timeout pins cannot leave a
    hard-coded tier behind. The v2 authorization schema states the same three
    numbers as tiered minima; a mismatch between the two is a refusal, which is
    the point of computing it twice.
    """
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        raise ExtractionError(
            "an effective generate cap is at least one", reason_code="budget_insufficient"
        )
    return (
        PROVIDER_COUNT_TIMEOUT_SECONDS_PIN
        + cap * PROVIDER_TIMEOUT_SECONDS_PIN
        + sum(PROVIDER_RETRY_DELAYS_PIN[: cap - 1])
    )


def resolve_attempt_cap_v2(*, authorization: dict[str, Any]) -> int:
    """Enforce the two-operation budget and return the effective generate cap.

    One rule, stated once. ``budget_max_external_requests`` below two cannot pay
    for one count send plus one generate attempt, so the run is refused before
    the run root exists. Above that the cap is **derived** --
    ``min(3, budget_max_external_requests - 1)`` -- and never declared: an
    independent field would be a second source of truth that could drift from the
    formula the connector actually applies.
    """
    code = "budget_insufficient"

    def _positive(field: str) -> int:
        value = authorization.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 1:
            raise ExtractionError(f"{field} must be a positive integer", reason_code=code)
        return value

    external_requests = authorization.get("budget_max_external_requests")
    if (
        not isinstance(external_requests, int)
        or isinstance(external_requests, bool)
        or external_requests < 2
    ):
        raise ExtractionError(
            "budget_max_external_requests must be at least two: one countTokens "
            "send plus one generateContent attempt",
            reason_code=code,
        )
    _positive("budget_max_records")
    output_tokens = _positive("budget_max_output_tokens")
    wall_clock = _positive("budget_max_wall_clock_seconds")
    _positive("circuit_breaker_max_consecutive_failures")
    # The meter is the only thing that can check these two; refuse a malformed
    # value here so a missing limit cannot masquerade as an unlimited one.
    _positive("budget_max_input_tokens")
    _positive("budget_max_estimated_cost_micros")

    if output_tokens < PROVIDER_DECLARED_MAX_OUTPUT_TOKENS_PIN:
        raise ExtractionError(
            "budget_max_output_tokens is below the declared max_output_tokens; "
            "the run would exceed its budget by construction",
            reason_code=code,
        )
    cap = min(PROVIDER_MAX_ATTEMPTS_PIN, external_requests - 1)
    floor = wall_clock_floor_for_cap(cap)
    if wall_clock < floor:
        raise ExtractionError(
            f"budget_max_wall_clock_seconds is below the {cap}-attempt ceiling of "
            f"{floor}s; this is a compatibility floor, not elapsed enforcement",
            reason_code=code,
        )
    return cap


AUTHORIZATION_V2_PROPERTIES: frozenset[str] = (
    AUTHORIZATION_PROPERTIES - {"budget_max_requests"}
) | {"budget_max_external_requests"}


def validate_governance_chain_v2(
    *,
    authorization: Any,
    enablement: Any,
    qualification: Any,
    authorization_pin: dict[str, str],
    enablement_pin: dict[str, str],
    qualification_pin: dict[str, str],
) -> dict[str, Any]:
    """The same three-ring walk, against the ``@0.2.0`` authorization shape.

    A separate function rather than a flag on the v1 one. The released
    ``live_call_authorization@0.1.0`` must keep being validated as exactly what
    it is; a shared validator that accepted either property set would have let a
    v1 authorization satisfy a v2 run and vice versa, which is precisely the
    substitution the two-operation budget cannot survive.

    Only the authorization ring differs. The enablement and qualification records
    are unchanged contracts and are checked by the released validator.
    """
    code = "authorization_chain_broken"
    authorization = _require_exact_properties(
        authorization,
        AUTHORIZATION_V2_PROPERTIES,
        what="live call authorization v2",
        code=code,
    )
    if authorization.get("contract") != LIVE_AUTHORIZATION_V2_CONTRACT:
        raise ExtractionError(
            f"governance record must declare {LIVE_AUTHORIZATION_V2_CONTRACT}",
            reason_code=code,
        )
    if authorization.get("schema_version") != "0.2.0":
        raise ExtractionError(
            "a v2 authorization must declare schema_version 0.2.0", reason_code=code
        )
    # Re-use the released walk for the two rings it still owns, by handing it a
    # v1-shaped stand-in of the ring it no longer owns. The stand-in is never
    # returned: only the pins and the two upper records are being checked here.
    stand_in = dict(authorization)
    stand_in["budget_max_requests"] = stand_in.pop("budget_max_external_requests")
    stand_in["contract"] = LIVE_AUTHORIZATION_CONTRACT
    stand_in["schema_version"] = GOVERNANCE_SCHEMA_VERSION
    validate_governance_chain(
        authorization=stand_in,
        enablement=enablement,
        qualification=qualification,
        authorization_pin=authorization_pin,
        enablement_pin=enablement_pin,
        qualification_pin=qualification_pin,
    )
    return authorization
