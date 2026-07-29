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
from typing import Any

from .errors import ExtractionError
from .raw_artifacts import canonical_json_bytes

__all__ = [
    "CLIENT_CONTRACT_CONTRACT",
    "CLIENT_CONTRACT_PROPERTIES",
    "EXTRACTION_RUN_PROPERTIES",
    "NON_RUN_CONTRACT",
    "NON_RUN_REASONS",
    "PROVIDER_ERROR_CONTRACT",
    "PROVIDER_ERROR_REASONS",
    "STAGE_OUTPUT_SCHEMA",
    "STAGE_OUTPUT_SCHEMA_SHA256",
    "build_extraction_run",
    "build_non_run_record",
    "build_provider_error_record",
    "record_bytes",
    "resolve_stage_schema_hash",
    "validate_provider_client_contract",
]

NON_RUN_CONTRACT = "extraction_non_run_record@0.1.0"
CLIENT_CONTRACT_CONTRACT = "extraction_provider_client_contract@0.1.0"
PROVIDER_ERROR_CONTRACT = "extraction_provider_error_record@0.1.0"

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


def record_bytes(record: dict[str, Any]) -> bytes:
    return canonical_json_bytes(record)
