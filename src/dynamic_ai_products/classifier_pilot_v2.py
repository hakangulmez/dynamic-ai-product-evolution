"""The narrow two-axis Item 1 software-universe gate (ADR-141).

This is an output-contract successor to the four-axis pilot, not a repair of the
immutable V1/V2 runs.  It holds one shared list of at most three Item 1 block
addresses, so the model cannot accidentally spend four evidence slots merely by
answering four separate axes.  The pipeline resolves the referenced blocks; the
model never writes their text.
"""

from __future__ import annotations

import json

from jsonschema import Draft202012Validator

from .classifier_pilot_v1 import (
    FORBIDDEN_MODEL_FIELDS,
    PILOT_SELECTION_CONTRACT,
    PILOT_SELECTION_SCHEMA,
    PilotAxesFailure,
    resolve_evidence_block,
)

__all__ = [
    "PILOT_V2_AXES", "PILOT_V2_AXES_CONTRACT", "PILOT_V2_AXES_SCHEMA",
    "PILOT_V2_PROMPT_PATH", "PILOT_V2_RECORD_CONTRACT", "PILOT_V2_RECORD_SCHEMA",
    "PILOT_V2_SELECTION_CONTRACT", "PILOT_V2_SELECTION_SCHEMA",
    "build_pilot_v2_record", "validate_pilot_v2_axes_output",
]

PILOT_V2_PROMPT_PATH = "prompts/discovery/software_universe_classifier_pilot.v2.md"
PILOT_V2_AXES_SCHEMA = "schemas/universe_classifier_pilot_axes_record.v2.schema.json"
PILOT_V2_AXES_CONTRACT = "universe_classifier_pilot_axes_record@0.2.0"
PILOT_V2_RECORD_SCHEMA = "schemas/universe_classifier_pilot_record.v2.schema.json"
PILOT_V2_RECORD_CONTRACT = "universe_classifier_pilot_record@0.2.0"
PILOT_V2_SELECTION_SCHEMA = PILOT_SELECTION_SCHEMA
PILOT_V2_SELECTION_CONTRACT = PILOT_SELECTION_CONTRACT
PILOT_V2_AXES = ("customer_facing_digital_product", "software_centrality")


def validate_pilot_v2_axes_output(raw: str, packet: dict,
                                  validator: Draft202012Validator) -> dict:
    """Validate the two judgements and resolve their shared block addresses."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PilotAxesFailure("invalid_model_json", f"Pilot output is not valid JSON: {exc}.") from exc
    if not isinstance(parsed, dict):
        raise PilotAxesFailure("invalid_model_json", "Pilot output is JSON but not an object.")
    for field in (*FORBIDDEN_MODEL_FIELDS, "evidence"):
        if field in parsed:
            raise PilotAxesFailure(
                "model_emitted_forbidden_field",
                f"Pilot output carries {field!r}; it returns only two judgements, confidence and Item 1 addresses.")
    errors = sorted(validator.iter_errors(parsed), key=lambda e: e.json_path)
    if errors:
        raise PilotAxesFailure(
            "pilot_axes_contract_violation",
            f"Pilot output violates {PILOT_V2_AXES_CONTRACT} at {errors[0].json_path}: {errors[0].message}")
    evidence = []
    for position, passage_ref in enumerate(parsed["passage_refs"], start=1):
        try:
            block = resolve_evidence_block(passage_ref, packet)
        except PilotAxesFailure as exc:
            raise PilotAxesFailure(exc.reason_code, f"Evidence {position}: {exc.detail}") from exc
        evidence.append({
            "passage_ref": passage_ref, "passage_id": block.passage_id,
            "evidence_text": block.text, "byte_start": block.byte_start,
            "byte_end": block.byte_end, "text_sha256": block.sha256,
            "provenance": "pipeline_derived",
        })
    return {**parsed, "evidence": evidence}


def build_pilot_v2_record(*, row: dict, packet: dict, prompt_sha256: str,
                          model_route: dict, raw: str,
                          validator: Draft202012Validator) -> dict:
    """Build a v0.2.0 stored gate row; a bad response is review-only."""
    base = {
        "record_contract": PILOT_V2_RECORD_CONTRACT,
        "cik": row["cik"], "accession": row["accession"],
        "company_id": row["company_id"], "source_id": row["source_id"],
        "packet_sha256": packet["packet_sha256"], "prompt_sha256": prompt_sha256,
        "model_route": dict(model_route),
        "admission_provenance": dict(row.get("admission_provenance") or {}),
    }
    try:
        axes = validate_pilot_v2_axes_output(raw, packet, validator)
    except PilotAxesFailure as exc:
        return {**base, "record_kind": "review_uncertain", "axes": None,
                "review_reason_code": exc.reason_code, "review_detail": exc.detail}
    return {**base, "record_kind": "classified", "axes": axes,
            "review_reason_code": None, "review_detail": None}
