"""The terminal execution outcome and its verification predicates (ADR-043, E-M).

``extraction_execution_outcome@0.1.0`` is the single owner of everything a
two-operation run knows about itself that no released contract can hold. Three
released contracts were measured and none of them can be widened:

- ``extraction_run@0.1.0`` is closed and rejected every measurement field tried
  against it;
- ``extraction_provider_error_record@0.1.0`` is closed, has no operation label,
  attempt ordinal, raw reference or filesystem reason, and its ``reason_code``
  enum accepts no persistence code;
- ``prediction_artifact_manifest@0.1.0`` takes an unbounded ``source_artifacts``
  tuple, which is why two new roles can be bound without touching it.

This module is also where the classifier's rules live. It is **diagnostic only**:
a positive label says a tree is internally consistent, never that it may be
admitted. The one admissible shape is a ``completed`` family whose manifest and
every required pin verify.

**Pin direction.** A record may pin only what was written before it. The outcome
is written after the raw prediction and ``extraction_run`` and before the
envelopes and the manifest, so it can pin the first two and can never pin the last
two — there are no fields for them. On routes that publish no manifest the outcome
is itself the root, because the root is always the last write of its route.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from typing import Any

from .errors import ExtractionError

__all__ = [
    "COUNT_RAW_REFERENCE",
    "EXECUTION_OUTCOME_CONTRACT",
    "EXECUTION_OUTCOME_REFERENCE",
    "EVIDENCE_BINDING_CONTRACT",
    "OUTCOME_ROUTE_FAMILIES",
    "RAW_PREDICTION_REFERENCE",
    "build_execution_outcome",
    "classify_run_root",
    "generate_attempt_reference",
    "require_attempt_pin_equality",
    "require_authorization_chain",
    "require_generate_attempt_order",
    "require_terminal_ownership",
    "schema_gate",
    "validate_execution_outcome",
]

EXECUTION_OUTCOME_CONTRACT = "extraction_execution_outcome@0.1.0"

# Canonical run-root references. Frozen names, one directory level, snake_case,
# matching the layout the released orchestrator already uses.
COUNT_RAW_REFERENCE = "attempts/count_tokens_1.json"
RAW_PREDICTION_REFERENCE = "predictions/raw_prediction.json"
EXECUTION_OUTCOME_REFERENCE = "manifests/extraction_execution_outcome.json"

# The evidence binding is a **pre-existing external anchor**: the E-M-S registry
# record is written long before any E-M run and lives outside the run root, so
# its reference is registry-relative rather than run-root-relative.
#
# Its three values are pinned by ``const`` in
# ``schemas/extraction_execution_outcome.schema.json`` and nowhere else. They are
# deliberately not repeated here: this package must hold no ``data/`` path at
# all, and a second copy of a pin is a second thing that can drift. The binding
# reaches this builder as an argument and is validated against the contract.
EVIDENCE_BINDING_CONTRACT = "documentation_evidence_validation@0.1.0"

OUTCOME_ROUTE_FAMILIES: tuple[str, ...] = (
    "completed",
    "post_generation_invalid",
    "pre_generation_invalid",
    "count_provider_error",
    "generation_provider_error",
    "generation_persistence_failed",
)

# The verified CountTokens qualifiers travel together. Recording the zero price
# without the quota would drop a load-bearing part of the same passage.
_COUNT_RATE_LIMIT = "3000 requests per minute (maximum quota)"
_COUNT_QUOTA_CLAIM_LIMIT = "this evidence does not support a claim that no quota applies"

_SHA256_HEX = 64


def generate_attempt_reference(attempt_ordinal: int) -> str:
    """The canonical path of one non-terminal generation attempt body."""
    if isinstance(attempt_ordinal, bool) or not isinstance(attempt_ordinal, int):
        raise ExtractionError("an attempt ordinal must be an integer", reason_code="pin_invalid")
    if not 1 <= attempt_ordinal <= 3:
        raise ExtractionError("an attempt ordinal is 1..3", reason_code="pin_invalid")
    return f"attempts/generate_content_{attempt_ordinal}.json"


def _refuse(message: str, reason_code: str) -> None:
    raise ExtractionError(message, reason_code=reason_code)


def _require_pin(pin: Any, *, label: str) -> dict[str, str]:
    if not isinstance(pin, dict) or sorted(pin) != ["reference", "sha256"]:
        _refuse(f"{label} must carry exactly a reference and a sha256", "pin_invalid")
    reference = pin["reference"]
    digest = pin["sha256"]
    if not isinstance(reference, str) or not reference:
        _refuse(f"{label} lacks a reference", "pin_invalid")
    if (
        not isinstance(digest, str)
        or len(digest) != _SHA256_HEX
        or not all(character in "0123456789abcdef" for character in digest)
    ):
        _refuse(f"{label} lacks a valid sha256", "pin_invalid")
    return {"reference": reference, "sha256": digest}


def _require_evidence_binding(binding: Any) -> dict[str, str]:
    """The external anchor, shaped and identified. The values are the schema's.

    Checking the contract id here and the exact reference and digest in the
    schema keeps one pin rather than two: a builder-side copy of the digest
    would be a second authority that could fall out of step with the contract.
    """
    if not isinstance(binding, dict) or sorted(binding) != [
        "contract",
        "registry_reference",
        "sha256",
    ]:
        _refuse("the evidence binding must carry a contract, reference and digest", "pin_invalid")
    if binding.get("contract") != EVIDENCE_BINDING_CONTRACT:
        _refuse("the evidence binding names a different contract", "model_binding_mismatch")
    reference = binding.get("registry_reference")
    if not isinstance(reference, str) or not reference:
        _refuse("the evidence binding lacks a registry reference", "pin_invalid")
    digest = binding.get("sha256")
    if (
        not isinstance(digest, str)
        or len(digest) != _SHA256_HEX
        or not all(character in "0123456789abcdef" for character in digest)
    ):
        _refuse("the evidence binding lacks a valid sha256", "pin_invalid")
    return dict(binding)


def build_execution_outcome(
    *,
    route_family: str,
    terminal_reason: str,
    loop_termination_cause: str,
    external_request_count: int,
    error_count: int,
    count_operation: dict[str, Any],
    generate_attempts: list[dict[str, Any]],
    run_root_pins: dict[str, dict[str, str]],
    evidence_binding: dict[str, str],
    measurement_status: str | None = None,
    count_raw_pin: dict[str, str] | None = None,
    raw_prediction_pin: dict[str, str] | None = None,
    provider_error_record_pin: dict[str, str] | None = None,
    reserved_cost_microdollars: int | None = None,
    actual_cost_microdollars: int | None = None,
    measured_input_tokens: int | None = None,
    sdk_witness_total_tokens: int | None = None,
    thinking_budget: int | None = None,
) -> dict[str, Any]:
    """Assemble the record. The conditional shape is the schema's job; this
    builder refuses only what a schema cannot see."""
    if route_family not in OUTCOME_ROUTE_FAMILIES:
        _refuse(f"unknown route family: {route_family!r}", "route_family_invalid")
    required = (
        "packet_pin",
        "contents_pin",
        "prompt_pin",
        "client_contract_pin",
        "authorization_pin",
        "extraction_run_pin",
    )
    if not isinstance(run_root_pins, dict) or sorted(run_root_pins) != sorted(required):
        _refuse("the six run-root pins are all mandatory", "pin_invalid")
    record: dict[str, Any] = {
        "contract": EXECUTION_OUTCOME_CONTRACT,
        "schema_version": "0.1.0",
        "route_family": route_family,
        "terminal_reason": terminal_reason,
        "loop_termination_cause": loop_termination_cause,
        "external_request_count": int(external_request_count),
        "error_count": int(error_count),
        "count_operation": dict(count_operation),
        "generate_attempts": [dict(attempt) for attempt in generate_attempts],
        "evidence_binding": _require_evidence_binding(evidence_binding),
        "count_operation_monetary_cost_microdollars": 0,
        "count_operation_rate_limit": _COUNT_RATE_LIMIT,
        "count_operation_quota_claim_limit": _COUNT_QUOTA_CLAIM_LIMIT,
    }
    for name in required:
        record[name] = _require_pin(run_root_pins[name], label=name)
    optional_pins = (
        ("count_raw_pin", count_raw_pin),
        ("raw_prediction_pin", raw_prediction_pin),
        ("provider_error_record_pin", provider_error_record_pin),
    )
    for name, pin in optional_pins:
        if pin is not None:
            record[name] = _require_pin(pin, label=name)
    optional_scalars = (
        ("measurement_status", measurement_status),
        ("reserved_cost_microdollars", reserved_cost_microdollars),
        ("actual_cost_microdollars", actual_cost_microdollars),
        ("measured_input_tokens", measured_input_tokens),
        ("sdk_witness_total_tokens", sdk_witness_total_tokens),
        ("thinking_budget", thinking_budget),
    )
    for name, value in optional_scalars:
        if value is not None:
            record[name] = value
    return record


# --- predicates a JSON Schema cannot express ---------------------------------


def require_attempt_pin_equality(record: dict[str, Any]) -> None:
    """P1/P2: a named pin must equal the per-attempt pin it stands for.

    Deliberate redundancy. JSON Schema 2020-12 has no ``$data``, so cross-field
    equality is unreachable there; carrying the value twice makes a disagreement
    a detectable internal contradiction instead of an invisible one.
    """
    count = record.get("count_operation") or {}
    if "count_raw_pin" in record:
        pin = record["count_raw_pin"]
        if (pin.get("reference"), pin.get("sha256")) != (
            count.get("raw_reference"),
            count.get("raw_sha256"),
        ):
            _refuse(
                "count_raw_pin disagrees with the count attempt it stands for",
                "pin_equality_violation",
            )
    attempts = record.get("generate_attempts") or []
    if "raw_prediction_pin" in record:
        if not attempts:
            _refuse("a raw prediction pin needs a generation attempt", "pin_equality_violation")
        terminal = max(attempts, key=lambda attempt: attempt.get("attempt_ordinal", 0))
        pin = record["raw_prediction_pin"]
        if (pin.get("reference"), pin.get("sha256")) != (
            terminal.get("raw_reference"),
            terminal.get("raw_sha256"),
        ):
            _refuse(
                "raw_prediction_pin disagrees with the terminal generation attempt",
                "pin_equality_violation",
            )


def require_generate_attempt_order(record: dict[str, Any]) -> None:
    """P3/P4: ordinals are exactly ``1..n``, in order, and all are generations."""
    attempts = record.get("generate_attempts") or []
    ordinals = [attempt.get("attempt_ordinal") for attempt in attempts]
    if ordinals != list(range(1, len(ordinals) + 1)):
        _refuse(
            "generation ordinals must be 1..n, in order and without repetition",
            "attempt_order_violation",
        )
    if any(attempt.get("operation_label") != "generate_content" for attempt in attempts):
        _refuse("a non-generation attempt appeared in the list", "attempt_order_violation")


def require_terminal_ownership(record: dict[str, Any]) -> None:
    """P5: only the terminal attempt may own the raw-prediction path.

    A non-terminal attempt writes to its own ordinal path. Two attempts sharing
    the raw-prediction reference would mean one body silently stood in for
    another, which is the failure the single-use capture slots exist to prevent.
    """
    attempts = record.get("generate_attempts") or []
    if not attempts:
        return
    terminal_ordinal = max(attempt.get("attempt_ordinal", 0) for attempt in attempts)
    users = [
        attempt
        for attempt in attempts
        if attempt.get("raw_reference") == RAW_PREDICTION_REFERENCE
    ]
    if len(users) > 1:
        _refuse(
            "more than one generation attempt claims the raw prediction path",
            "terminal_ownership_violation",
        )
    for attempt in attempts:
        if attempt.get("capture_disposition") != "raw_persisted":
            continue
        ordinal = attempt.get("attempt_ordinal")
        if ordinal == terminal_ordinal:
            continue
        if attempt.get("raw_reference") != generate_attempt_reference(ordinal):
            _refuse(
                "a non-terminal attempt is not at its own canonical path",
                "terminal_ownership_violation",
            )
    if record.get("route_family") in ("completed", "post_generation_invalid"):
        terminal = [
            attempt
            for attempt in attempts
            if attempt.get("attempt_ordinal") == terminal_ordinal
        ][0]
        if terminal.get("capture_disposition") != "raw_persisted":
            _refuse("the terminal attempt did not persist", "terminal_ownership_violation")
        if terminal.get("raw_reference") != RAW_PREDICTION_REFERENCE:
            _refuse(
                "the terminal attempt is not at the raw prediction path",
                "terminal_ownership_violation",
            )


def schema_gate(raw_bytes: Any, *, schema: dict[str, Any], contract_id: str, version: str):
    """P6 pre-gate: parse, identify, validate — **then** compare digests.

    Nothing downstream runs unless this returns ``ok``. A contract mismatch is
    ``corrupt`` and not ``incomplete``: the pin is present and the file is
    present, so nothing is missing — something is wrong. Such a document can even
    hash-match its own pin, which is precisely why the digest comparison alone
    cannot catch it.
    """
    from jsonschema import Draft202012Validator

    if not isinstance(raw_bytes, (bytes, bytearray)):
        return "corrupt", "json_parse_failed", None
    try:
        document = json.loads(bytes(raw_bytes).decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        return "corrupt", "json_parse_failed", None
    if not isinstance(document, dict):
        return "corrupt", "not_an_object", None
    if document.get("contract") != contract_id:
        return "corrupt", "contract_id_mismatch", None
    if document.get("schema_version") != version:
        return "corrupt", "contract_version_mismatch", None
    if list(Draft202012Validator(schema).iter_errors(document)):
        return "corrupt", "schema_validation_failed", None
    return "ok", None, document


def require_authorization_chain(
    *,
    record: dict[str, Any],
    authorization_bytes: bytes,
    client_contract_bytes: bytes,
    evidence_record: dict[str, Any],
    expected_evidence_binding: dict[str, str],
) -> None:
    """P6.a-P6.f over real bytes, after each artifact has passed its own gate.

    Without this the budget and measurement claims are rootless: they would rest
    on numbers whose pricing, thinking and quota evidence was never tied to the
    model the run actually used.
    """
    client_pin = record.get("client_contract_pin") or {}
    authorization_pin = record.get("authorization_pin") or {}
    if sha256(authorization_bytes).hexdigest() != authorization_pin.get("sha256"):
        _refuse("the authorization bytes do not match their pin", "hash_mismatch")
    if sha256(client_contract_bytes).hexdigest() != client_pin.get("sha256"):
        _refuse("the client contract bytes do not match their pin", "hash_mismatch")
    authorization = json.loads(authorization_bytes.decode("utf-8"))
    contract = json.loads(client_contract_bytes.decode("utf-8"))
    if authorization.get("provider_client_contract_reference") != client_pin.get("reference"):
        _refuse("the authorization names a different client contract", "hash_mismatch")
    if authorization.get("provider_client_contract_sha256") != client_pin.get("sha256"):
        _refuse("the authorization pins a different client contract", "hash_mismatch")
    pricing = (evidence_record or {}).get("pricing_units") or {}
    if contract.get("model_name") != pricing.get("model"):
        _refuse(
            "the priced model and the executed model are not the same",
            "model_binding_mismatch",
        )
    if record.get("evidence_binding") != _require_evidence_binding(expected_evidence_binding):
        _refuse("the evidence binding is not the pinned anchor", "model_binding_mismatch")


def classify_run_root(
    *, outcome: dict[str, Any] | None, manifest_present: bool, envelopes_present: bool
) -> tuple[str, str | None]:
    """Diagnostic classification. It never grants admission.

    Only ``authoritative_completed`` is harness-admissible, and even that is a
    statement about internal consistency rather than a permission.
    """
    if outcome is None:
        return "non_authoritative_incomplete", "outcome_absent"
    family = outcome.get("route_family")
    if family not in OUTCOME_ROUTE_FAMILIES:
        return "corrupt", "route_family_shape_violation"
    if family == "completed":
        if not manifest_present or not envelopes_present:
            # extraction_run says completed while the manifest is missing: a
            # publication failure, not the deliberate stop that G3 records.
            return "non_authoritative_incomplete", "parent_artifact_absent"
        return "authoritative_completed", None
    if manifest_present or envelopes_present:
        return "corrupt", "unexpected_artifact_present"
    if family == "post_generation_invalid":
        return "authoritative_intentional_invalid", None
    return "authoritative_terminal_failure", None


def validate_execution_outcome(record: dict[str, Any], *, schema_root: str = "schemas") -> None:
    """Validate a record against the committed contract before it is written.

    Loaded from the committed file rather than from a copy in this module: the
    conditional route-family shape is the contract, and a second in-code copy of
    it would be a second thing to keep in step. A record that fails here is never
    persisted, so a run root can hold no outcome that its own schema rejects.
    """
    from jsonschema import Draft202012Validator

    path = Path(schema_root) / "extraction_execution_outcome.schema.json"
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ExtractionError(
            "the execution-outcome schema could not be read",
            reason_code="schema_unavailable",
        ) from exc
    errors = sorted(Draft202012Validator(schema).iter_errors(record), key=lambda e: list(e.path))
    if errors:
        raise ExtractionError(
            "the execution outcome does not satisfy its own contract",
            reason_code="execution_outcome_invalid",
            detail=str(list(errors[0].path)),
        )
    require_attempt_pin_equality(record)
    require_generate_attempt_order(record)
    require_terminal_ownership(record)
