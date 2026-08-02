"""The terminal outcome contract: conditional shape, pins, gate and classifier.

Three groups of tests. The first proves the released contracts really cannot
carry any of this, so the new record is a necessity rather than a preference. The
second exercises the conditional route-family shape and the predicates a JSON
Schema cannot express. The third covers the schema gate and the classifier.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.execution_outcome import (
    COUNT_RAW_REFERENCE,
    EVIDENCE_BINDING_CONTRACT,
    EXECUTION_OUTCOME_REFERENCE,
    RAW_PREDICTION_REFERENCE,
    build_execution_outcome,
    classify_run_root,
    generate_attempt_reference,
    require_attempt_pin_equality,
    require_generate_attempt_order,
    require_terminal_ownership,
    schema_gate,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / "schemas" / "extraction_execution_outcome.schema.json").read_bytes())
VALIDATOR = Draft202012Validator(SCHEMA)
BINDING = {
    "registry_reference": SCHEMA["properties"]["evidence_binding"]["properties"][
        "registry_reference"
    ]["const"],
    "sha256": SCHEMA["properties"]["evidence_binding"]["properties"]["sha256"]["const"],
    "contract": EVIDENCE_BINDING_CONTRACT,
}
H = lambda character: character * 64  # noqa: E731 - a digest stub, not logic
PINS = {
    name: {"reference": f"inputs/{name}", "sha256": H("1")}
    for name in (
        "packet_pin",
        "contents_pin",
        "prompt_pin",
        "client_contract_pin",
        "authorization_pin",
        "extraction_run_pin",
    )
}


def attempt(label, ordinal, disposition, **extra):
    record = {
        "operation_label": label,
        "attempt_ordinal": ordinal,
        "send_outcome": "response_2xx",
        "sdk_call_outcome": "returned",
        "capture_disposition": disposition,
    }
    record.update(extra)
    return record


def count_attempt(disposition="raw_persisted"):
    if disposition == "raw_persisted":
        return attempt(
            "count_tokens",
            1,
            disposition,
            raw_reference=COUNT_RAW_REFERENCE,
            raw_sha256=H("c"),
            byte_count=10,
        )
    if disposition == "body_captured_persistence_failed":
        return attempt("count_tokens", 1, disposition, persistence_reason_code="write_error")
    if disposition == "empty_entity_body_not_persisted":
        # The call returned; the body it returned was empty.
        return attempt(
            "count_tokens", 1, disposition, provider_reason_code="provider_response_unusable"
        )
    # Nothing was captured, so the call cannot have returned: a transport failure,
    # a redirect or a protocol switch all raise.
    return attempt(
        "count_tokens",
        1,
        disposition,
        send_outcome="no_response_transport_failure",
        sdk_call_outcome="raised",
        provider_reason_code="provider_timeout",
    )


def generate_attempt(ordinal=1, terminal=True, disposition="raw_persisted"):
    if disposition != "raw_persisted":
        return attempt("generate_content", ordinal, disposition, persistence_reason_code="write_error")
    reference = RAW_PREDICTION_REFERENCE if terminal else generate_attempt_reference(ordinal)
    return attempt(
        "generate_content",
        ordinal,
        disposition,
        raw_reference=reference,
        raw_sha256=H("d" if terminal else "e"),
        byte_count=20,
    )


def outcome(family="completed", **overrides):
    kwargs = {
        "route_family": family,
        "terminal_reason": "none",
        "loop_termination_cause": "terminal_response_returned",
        "external_request_count": 2,
        "error_count": 0,
        "count_operation": count_attempt(),
        "generate_attempts": [generate_attempt()],
        "run_root_pins": PINS,
        "evidence_binding": dict(BINDING),
        "measurement_status": "verified",
        "count_raw_pin": {"reference": COUNT_RAW_REFERENCE, "sha256": H("c")},
        "raw_prediction_pin": {"reference": RAW_PREDICTION_REFERENCE, "sha256": H("d")},
    }
    kwargs.update(overrides)
    return build_execution_outcome(**kwargs)


def valid(record) -> bool:
    return list(VALIDATOR.iter_errors(record)) == []


# --- why this contract has to exist ------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "measured_input_tokens",
        "actual_cost_microdollars",
        "count_tokens_raw_reference",
        "measurement_status",
        "thinking_budget",
    ],
)
def test_extraction_run_cannot_carry_any_of_this(field):
    released = json.loads((ROOT / "schemas" / "extraction_run.schema.json").read_bytes())
    assert released["additionalProperties"] is False
    assert field not in released["properties"]


@pytest.mark.parametrize(
    "field", ["operation_label", "attempt_ordinal", "raw_response_sha256", "persistence_reason_code"]
)
def test_the_provider_error_record_cannot_carry_any_of_this_either(field):
    released = json.loads(
        (ROOT / "schemas" / "extraction_provider_error_record.schema.json").read_bytes()
    )
    assert released["additionalProperties"] is False
    assert field not in released["properties"]
    assert "write_error" not in released["properties"]["reason_code"]["enum"]


def test_the_outcome_can_never_pin_what_is_written_after_it():
    """Pin direction, enforced by absence rather than by a rule."""
    assert "envelopes_pin" not in SCHEMA["properties"]
    assert "manifest_pin" not in SCHEMA["properties"]


# --- conditional route-family shape ------------------------------------------


def test_a_completed_outcome_validates_and_satisfies_every_predicate():
    record = outcome()
    assert valid(record)
    require_attempt_pin_equality(record)
    require_generate_attempt_order(record)
    require_terminal_ownership(record)


def test_completed_requires_both_raw_pins_and_a_measurement_verdict():
    for missing in ("raw_prediction_pin", "count_raw_pin", "measurement_status"):
        record = outcome()
        record.pop(missing)
        assert not valid(record)


def test_pre_generation_invalid_forbids_a_generation_it_never_made():
    """Without this the shape of a generation-phase persistence failure would
    have validated here too."""
    record = outcome(
        family="pre_generation_invalid",
        terminal_reason="count_parse_failed",
        loop_termination_cause="retry_not_permitted",
        measurement_status=None,
        raw_prediction_pin=None,
        generate_attempts=[],
        error_count=0,
        external_request_count=1,
    )
    assert valid(record)
    leaked = dict(record)
    leaked["generate_attempts"] = [generate_attempt()]
    assert not valid(leaked)


def test_count_and_generation_provider_errors_are_different_families():
    count_side = outcome(
        family="count_provider_error",
        terminal_reason="provider_call_failed",
        loop_termination_cause="retry_not_permitted",
        measurement_status=None,
        count_operation=count_attempt("no_body_captured"),
        count_raw_pin=None,
        raw_prediction_pin=None,
        generate_attempts=[],
        error_count=1,
        external_request_count=1,
        provider_error_record_pin={"reference": "manifests/e", "sha256": H("f")},
    )
    assert valid(count_side)
    # The same record relabelled as a generation failure no longer validates:
    # that family requires a persisted count and at least one generation attempt.
    relabelled = dict(count_side)
    relabelled["route_family"] = "generation_provider_error"
    assert not valid(relabelled)


def test_c4a_and_f4a_share_a_disposition_but_never_a_family():
    c4a = outcome(
        family="pre_generation_invalid",
        terminal_reason="persistence_failure",
        loop_termination_cause="persistence_failure",
        measurement_status=None,
        count_operation=count_attempt("body_captured_persistence_failed"),
        count_raw_pin=None,
        raw_prediction_pin=None,
        generate_attempts=[],
        error_count=0,
        external_request_count=1,
    )
    f4a = outcome(
        family="generation_persistence_failed",
        terminal_reason="persistence_failure",
        loop_termination_cause="persistence_failure",
        measurement_status=None,
        raw_prediction_pin=None,
        generate_attempts=[generate_attempt(disposition="body_captured_persistence_failed")],
        error_count=0,
        external_request_count=2,
    )
    assert valid(c4a) and valid(f4a)
    assert c4a["count_operation"]["capture_disposition"] == (
        f4a["generate_attempts"][0]["capture_disposition"]
    )
    swapped = dict(c4a)
    swapped["route_family"] = "generation_persistence_failed"
    assert not valid(swapped)


# --- exact iff rules on an attempt -------------------------------------------


@pytest.mark.parametrize(
    "disposition, extra, ok",
    [
        ("raw_persisted", {}, True),
        ("no_body_captured", {"persistence_reason_code": "destination_exists"}, False),
        ("empty_entity_body_not_persisted", {"persistence_reason_code": "write_error"}, False),
        ("body_captured_persistence_failed", {}, False),
    ],
)
def test_a_persistence_reason_belongs_to_exactly_one_disposition(disposition, extra, ok):
    if disposition == "raw_persisted":
        candidate = count_attempt()
        candidate.update(extra)
    else:
        candidate = attempt("count_tokens", 1, disposition, **extra)
        if disposition != "body_captured_persistence_failed":
            candidate["provider_reason_code"] = "provider_response_unusable"
    record = outcome(
        family="pre_generation_invalid",
        terminal_reason="persistence_failure",
        loop_termination_cause="persistence_failure",
        measurement_status=None,
        count_operation=candidate,
        count_raw_pin=(
            {"reference": COUNT_RAW_REFERENCE, "sha256": H("c")}
            if disposition == "raw_persisted"
            else None
        ),
        raw_prediction_pin=None,
        generate_attempts=[],
        external_request_count=1,
    )
    assert valid(record) is ok


def test_a_zero_length_body_is_never_given_a_raw_reference():
    """``sha256(b"")`` is a valid-looking digest for content that never existed."""
    empty = attempt(
        "count_tokens",
        1,
        "empty_entity_body_not_persisted",
        provider_reason_code="provider_response_unusable",
        raw_reference=COUNT_RAW_REFERENCE,
    )
    record = outcome(
        family="count_provider_error",
        terminal_reason="provider_call_failed",
        loop_termination_cause="retry_not_permitted",
        measurement_status=None,
        count_operation=empty,
        count_raw_pin=None,
        raw_prediction_pin=None,
        generate_attempts=[],
        error_count=1,
        external_request_count=1,
        provider_error_record_pin={"reference": "manifests/e", "sha256": H("f")},
    )
    assert not valid(record)


# --- predicates a schema cannot express --------------------------------------


def test_a_named_pin_must_equal_the_attempt_it_stands_for():
    record = outcome()
    record["count_raw_pin"] = {"reference": COUNT_RAW_REFERENCE, "sha256": H("9")}
    with pytest.raises(ExtractionError) as caught:
        require_attempt_pin_equality(record)
    assert caught.value.reason_code == "pin_equality_violation"


def test_generation_ordinals_are_one_to_n_in_order():
    record = outcome(
        generate_attempts=[generate_attempt(2, terminal=True), generate_attempt(1, terminal=False)]
    )
    with pytest.raises(ExtractionError) as caught:
        require_generate_attempt_order(record)
    assert caught.value.reason_code == "attempt_order_violation"


def test_only_the_terminal_attempt_owns_the_raw_prediction_path():
    shared = outcome(
        generate_attempts=[generate_attempt(1, terminal=True), generate_attempt(2, terminal=True)],
        raw_prediction_pin={"reference": RAW_PREDICTION_REFERENCE, "sha256": H("d")},
    )
    with pytest.raises(ExtractionError) as caught:
        require_terminal_ownership(shared)
    assert caught.value.reason_code == "terminal_ownership_violation"


def test_a_non_terminal_attempt_sits_at_its_own_ordinal_path():
    record = outcome(
        generate_attempts=[
            attempt(
                "generate_content",
                1,
                "raw_persisted",
                raw_reference="attempts/generate_content_9.json",
                raw_sha256=H("e"),
                byte_count=5,
            ),
            generate_attempt(2, terminal=True),
        ],
        raw_prediction_pin={"reference": RAW_PREDICTION_REFERENCE, "sha256": H("d")},
    )
    with pytest.raises(ExtractionError) as caught:
        require_terminal_ownership(record)
    assert caught.value.reason_code == "terminal_ownership_violation"


def test_the_evidence_binding_must_be_the_named_anchor():
    with pytest.raises(ExtractionError):
        outcome(evidence_binding={**BINDING, "contract": "other@0.1.0"})
    with pytest.raises(ExtractionError):
        outcome(evidence_binding={**BINDING, "sha256": "not-a-digest"})


# --- the schema gate ---------------------------------------------------------


def test_the_gate_admits_only_a_conforming_document():
    payload = json.dumps(outcome()).encode("utf-8")
    verdict, reason, document = schema_gate(
        payload, schema=SCHEMA, contract_id="extraction_execution_outcome@0.1.0", version="0.1.0"
    )
    assert (verdict, reason) == ("ok", None)
    assert document["route_family"] == "completed"


@pytest.mark.parametrize(
    "payload, expected_reason",
    [
        (b"{not json", "json_parse_failed"),
        (b"[1,2,3]", "not_an_object"),
        (b'{"contract":"other@0.1.0","schema_version":"0.1.0"}', "contract_id_mismatch"),
        (
            b'{"contract":"extraction_execution_outcome@0.1.0","schema_version":"9.9.9"}',
            "contract_version_mismatch",
        ),
        (
            b'{"contract":"extraction_execution_outcome@0.1.0","schema_version":"0.1.0"}',
            "schema_validation_failed",
        ),
    ],
)
def test_every_gate_failure_is_corrupt_and_not_incomplete(payload, expected_reason):
    """A pin that is present and a file that is present: nothing is *missing*.

    A mismatched document can even hash-match its own pin, which is exactly why a
    digest comparison alone cannot catch it and why the gate exists.
    """
    verdict, reason, document = schema_gate(
        payload, schema=SCHEMA, contract_id="extraction_execution_outcome@0.1.0", version="0.1.0"
    )
    assert verdict == "corrupt"
    assert reason == expected_reason
    assert document is None


# --- the classifier ----------------------------------------------------------


def test_only_a_complete_completed_tree_is_admissible():
    record = outcome()
    assert classify_run_root(outcome=record, manifest_present=True, envelopes_present=True) == (
        "authoritative_completed",
        None,
    )


def test_a_completed_tree_without_a_manifest_is_a_publication_failure():
    record = outcome()
    label, reason = classify_run_root(
        outcome=record, manifest_present=False, envelopes_present=False
    )
    assert label == "non_authoritative_incomplete"
    assert reason == "parent_artifact_absent"


def test_an_intentional_invalid_stop_is_not_the_same_as_that_failure():
    record = outcome(
        family="post_generation_invalid",
        terminal_reason="reconciliation_invalid",
        measurement_status="invalid",
    )
    assert classify_run_root(
        outcome=record, manifest_present=False, envelopes_present=False
    ) == ("authoritative_intentional_invalid", None)


def test_a_missing_outcome_yields_no_positive_label_at_all():
    assert classify_run_root(
        outcome=None, manifest_present=True, envelopes_present=True
    ) == ("non_authoritative_incomplete", "outcome_absent")


def test_a_failure_family_carrying_a_manifest_is_corrupt():
    record = outcome(
        family="pre_generation_invalid",
        terminal_reason="budget_termination",
        loop_termination_cause="retry_not_permitted",
        measurement_status=None,
        raw_prediction_pin=None,
        generate_attempts=[],
        external_request_count=1,
    )
    assert classify_run_root(
        outcome=record, manifest_present=True, envelopes_present=False
    ) == ("corrupt", "unexpected_artifact_present")


def test_the_canonical_references_are_frozen():
    assert COUNT_RAW_REFERENCE == "attempts/count_tokens_1.json"
    assert RAW_PREDICTION_REFERENCE == "predictions/raw_prediction.json"
    assert EXECUTION_OUTCOME_REFERENCE == "manifests/extraction_execution_outcome.json"
    assert generate_attempt_reference(2) == "attempts/generate_content_2.json"
    for refused in (0, 4, True, "1", None):
        with pytest.raises(ExtractionError):
            generate_attempt_reference(refused)
