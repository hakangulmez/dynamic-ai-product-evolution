"""Provider-run provenance and the non-run record (ADR-033).

``extraction_run@0.1.0`` is adopted unchanged: strict, fifteen properties, no
provider-client-contract field. A pre-provider non-run writes no
``extraction_run`` at all, because that contract requires ``prompt_hash`` and
``source_manifest_hash`` and denotes a run that, on that route, never began.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.manifests import (
    AUTHORIZATION_PROPERTIES,
    ENABLEMENT_CONTRACT,
    ENABLEMENT_PROPERTIES,
    EXTRACTION_RUN_PROPERTIES,
    LIVE_AUTHORIZATION_CONTRACT,
    PROVIDER_ERROR_CONTRACT,
    PROVIDER_ERROR_REASONS,
    QUALIFICATION_CONTRACT,
    QUALIFICATION_PROPERTIES,
    build_provider_error_record,
    NON_RUN_CONTRACT,
    NON_RUN_REASONS,
    STAGE_OUTPUT_SCHEMA,
    STAGE_OUTPUT_SCHEMA_SHA256,
    build_extraction_run,
    build_non_run_record,
    record_bytes,
    resolve_stage_schema_hash,
)
from dynamic_ai_products.extraction.raw_artifacts import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"
LEDGER = {
    "input_passage_count": 4,
    "blank_drop_count": 1,
    "temporal_drop_count": 3,
    "surviving_count": 0,
    "blank_drops": [],
    "temporal_drops": [],
}


def _run(**overrides):
    kwargs = {
        "run_id": "ext-0001",
        "stage": "product_extraction",
        "started_at": "2026-07-29T00:00:00Z",
        "completed_at": "2026-07-29T00:01:00Z",
        "status": "completed",
        "code_commit": "59c716a1da4529f4b390e44eee6389f3a2f35954",
        "schema_hash": STAGE_OUTPUT_SCHEMA_SHA256["product_extraction"],
        "prompt_hash": "a" * 64,
        "source_manifest_hash": "b" * 64,
    }
    kwargs.update(overrides)
    return build_extraction_run(**kwargs)


def _non_run(**overrides):
    kwargs = {
        "extraction_run_id": "ext-0001",
        "stage": "product_extraction",
        "company_id": "CIK0001404655",
        "observation_cutoff_date": "2024-12-31",
        "code_commit": "59c716a1da4529f4b390e44eee6389f3a2f35954",
        "run_created_at": "2026-07-29T00:00:00Z",
        "input_packet_reference": "inputs/extraction_input_packet.json",
        "input_packet_sha256": "c" * 64,
        "coverage_artifact_reference": "coverage/source_family_coverage.json",
        "coverage_artifact_sha256": "d" * 64,
        "reason_code": "zero_admissible_passages",
        "filter_ledger": LEDGER,
    }
    kwargs.update(overrides)
    return build_non_run_record(**kwargs)


# --- extraction_run@0.1.0 is adopted unchanged -------------------------------


def test_the_released_property_set_is_exactly_fifteen():
    assert len(EXTRACTION_RUN_PROPERTIES) == 15
    assert "provider_client_contract" not in EXTRACTION_RUN_PROPERTIES
    assert "provider_client_contract_sha256" not in EXTRACTION_RUN_PROPERTIES


def test_a_built_run_emits_exactly_the_released_properties():
    assert set(_run()) == set(EXTRACTION_RUN_PROPERTIES)


def test_a_built_run_conforms_to_the_released_extraction_run_schema():
    schema = json.loads((SCHEMAS / "extraction_run.schema.json").read_text())
    Draft202012Validator(schema).validate(_run())


def test_spec_version_is_derived_from_the_stage_not_supplied():
    assert _run(stage="product_extraction")["spec_version"] == "SPEC-008"
    assert _run(stage="capability_extraction",
                schema_hash=STAGE_OUTPUT_SCHEMA_SHA256["capability_extraction"],
                )["spec_version"] == "SPEC-009"
    assert _run(stage="task_extraction",
                schema_hash=STAGE_OUTPUT_SCHEMA_SHA256["task_extraction"],
                )["spec_version"] == "SPEC-010"


def test_an_unknown_stage_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        _run(stage="marketing_extraction")
    assert excinfo.value.reason_code == "packet_stage_invalid"


@pytest.mark.parametrize(
    "field", ["schema_hash", "prompt_hash", "source_manifest_hash"]
)
def test_every_digest_field_must_be_lowercase_hex(field):
    with pytest.raises(ExtractionError) as excinfo:
        _run(**{field: "NOT" + "0" * 61})
    assert excinfo.value.reason_code == "pin_invalid"


@pytest.mark.parametrize("field", ["code_commit", "started_at"])
def test_run_identity_must_be_injected_never_discovered(field):
    """This package reads no clock and no VCS."""
    with pytest.raises(ExtractionError) as excinfo:
        _run(**{field: "  "})
    assert excinfo.value.reason_code == "run_identity_invalid"


# --- the stage output schema pin ---------------------------------------------


def test_every_stage_declares_its_released_output_schema():
    assert set(STAGE_OUTPUT_SCHEMA) == set(STAGE_OUTPUT_SCHEMA_SHA256)
    assert set(STAGE_OUTPUT_SCHEMA) == {
        "product_extraction",
        "capability_extraction",
        "task_extraction",
    }


@pytest.mark.parametrize("stage", sorted(STAGE_OUTPUT_SCHEMA))
def test_schema_hash_is_the_released_schema_file_digest(stage):
    """Not a digest of the run's own inputs: the stage output contract."""
    observed = resolve_stage_schema_hash(stage, str(SCHEMAS))
    target = SCHEMAS / STAGE_OUTPUT_SCHEMA[stage]
    assert observed == sha256_bytes(target.read_bytes())
    assert observed == STAGE_OUTPUT_SCHEMA_SHA256[stage]


def test_a_drifted_output_schema_fails_closed(tmp_path: Path):
    (tmp_path / "product_observation.schema.json").write_bytes(b"{}\n")
    with pytest.raises(ExtractionError) as excinfo:
        resolve_stage_schema_hash("product_extraction", str(tmp_path))
    assert excinfo.value.reason_code == "schema_pin_mismatch"


def test_an_unreadable_output_schema_fails_closed(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        resolve_stage_schema_hash("product_extraction", str(tmp_path))
    assert excinfo.value.reason_code == "schema_pin_mismatch"


def test_resolving_an_unknown_stage_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        resolve_stage_schema_hash("marketing_extraction", str(SCHEMAS))
    assert excinfo.value.reason_code == "packet_stage_invalid"


# --- extraction_non_run_record@0.1.0 -----------------------------------------


def test_the_non_run_record_declares_its_contract_and_never_a_provider_call():
    record = _non_run()
    assert record["contract"] == NON_RUN_CONTRACT
    assert record["provider_called"] is False
    assert record["harness_run"] is False


def test_the_non_run_record_pins_the_packet_bytes_not_only_the_ledger():
    record = _non_run()
    assert record["input_packet_reference"] == "inputs/extraction_input_packet.json"
    assert record["input_packet_sha256"] == "c" * 64
    assert record["filter_ledger"]["temporal_drop_count"] == 3


def test_the_non_run_record_carries_no_prompt_or_source_manifest_hash():
    """Those fields denote a provider run; this route never began one."""
    record = _non_run()
    assert "prompt_hash" not in record
    assert "source_manifest_hash" not in record
    assert "model_provider" not in record


@pytest.mark.parametrize("reason", NON_RUN_REASONS)
def test_every_declared_non_run_reason_is_accepted(reason):
    assert _non_run(reason_code=reason)["reason_code"] == reason


def test_an_undeclared_non_run_reason_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        _non_run(reason_code="provider_returned_nothing_useful")
    assert excinfo.value.reason_code == "non_run_reason_unknown"


@pytest.mark.parametrize(
    "field", ["input_packet_sha256", "coverage_artifact_sha256"]
)
def test_non_run_pins_must_be_well_formed(field):
    with pytest.raises(ExtractionError) as excinfo:
        _non_run(**{field: "short"})
    assert excinfo.value.reason_code == "pin_invalid"


@pytest.mark.parametrize("field", ["code_commit", "run_created_at"])
def test_non_run_identity_must_be_injected(field):
    with pytest.raises(ExtractionError) as excinfo:
        _non_run(**{field: ""})
    assert excinfo.value.reason_code == "run_identity_invalid"


def test_the_non_run_record_conforms_to_its_released_schema():
    schema = json.loads(
        (SCHEMAS / "extraction_non_run_record.schema.json").read_text()
    )
    Draft202012Validator(schema).validate(_non_run())


def test_serialization_is_deterministic():
    assert record_bytes(_non_run()) == record_bytes(_non_run())
    assert record_bytes(_run()).endswith(b"\n")


# --- extraction_provider_error_record@0.1.0 -----------------------------------


PROVIDER_ERROR_SCHEMA = json.loads(
    (SCHEMAS / "extraction_provider_error_record.schema.json").read_text()
)


def _error_record(**overrides):
    kwargs = {
        "extraction_run_id": "ext-0001",
        "stage": "product_extraction",
        "company_id": "CIK0001404655",
        "code_commit": "d9c954aaa7dd344987aadffce76387f06c9fa52f",
        "input_packet_reference": "inputs/extraction_input_packet.json",
        "input_packet_sha256": "1" * 64,
        "resolved_prompt_reference": "inputs/resolved_prompt.md",
        "resolved_prompt_sha256": "2" * 64,
        "provider_client_contract_reference": "inputs/provider_client_contract.json",
        "provider_client_contract_sha256": "3" * 64,
        "extraction_run_reference": "manifests/extraction_run.json",
        "extraction_run_sha256": "4" * 64,
        "reason_code": "vertex_unavailable",
        "attempt_count": 3,
    }
    kwargs.update(overrides)
    return build_provider_error_record(**kwargs)


def test_the_error_record_declares_its_contract_and_const_flags():
    record = _error_record()
    assert record["contract"] == PROVIDER_ERROR_CONTRACT
    assert record["provider_called"] is True
    assert record["harness_run"] is False


def test_the_error_record_conforms_to_its_released_schema():
    Draft202012Validator(PROVIDER_ERROR_SCHEMA).validate(_error_record())


def test_the_record_carries_no_free_text_property():
    """Structural: an upstream message has no channel into the artifact."""
    assert set(_error_record()) == set(PROVIDER_ERROR_SCHEMA["required"])
    assert PROVIDER_ERROR_SCHEMA["additionalProperties"] is False


def test_the_enum_matches_the_released_schema_exactly():
    assert list(PROVIDER_ERROR_REASONS) == PROVIDER_ERROR_SCHEMA["properties"]["reason_code"]["enum"]
    assert "live_call_not_authorized" not in PROVIDER_ERROR_REASONS


@pytest.mark.parametrize("reason", PROVIDER_ERROR_REASONS)
def test_every_declared_terminal_reason_is_accepted(reason):
    assert _error_record(reason_code=reason)["reason_code"] == reason


@pytest.mark.parametrize("reason", ["live_call_not_authorized", "invented", "", None])
def test_an_undeclared_reason_is_refused(reason):
    with pytest.raises(ExtractionError) as excinfo:
        _error_record(reason_code=reason)
    assert excinfo.value.reason_code == "provider_error_reason_unknown"


@pytest.mark.parametrize("attempts", [0, -1, "3", 1.5, None])
def test_a_non_positive_attempt_count_is_refused(attempts):
    with pytest.raises(ExtractionError) as excinfo:
        _error_record(attempt_count=attempts)
    assert excinfo.value.reason_code == "provider_error_attempt_count_invalid"


@pytest.mark.parametrize(
    "field",
    [
        "input_packet_sha256",
        "resolved_prompt_sha256",
        "provider_client_contract_sha256",
        "extraction_run_sha256",
    ],
)
def test_every_pin_must_be_a_well_formed_digest(field):
    with pytest.raises(ExtractionError) as excinfo:
        _error_record(**{field: "nope"})
    assert excinfo.value.reason_code == "pin_invalid"


@pytest.mark.parametrize(
    "field",
    [
        "input_packet_reference",
        "resolved_prompt_reference",
        "provider_client_contract_reference",
        "extraction_run_reference",
    ],
)
def test_every_reference_must_be_non_blank(field):
    with pytest.raises(ExtractionError) as excinfo:
        _error_record(**{field: "  "})
    assert excinfo.value.reason_code == "pin_invalid"


def test_an_unknown_stage_is_refused_for_the_error_record():
    with pytest.raises(ExtractionError) as excinfo:
        _error_record(stage="marketing_extraction")
    assert excinfo.value.reason_code == "packet_stage_invalid"


def test_extraction_run_is_not_widened_to_carry_a_reason():
    """The companion record exists precisely so this stays true."""
    assert "error_reason" not in EXTRACTION_RUN_PROPERTIES
    assert len(EXTRACTION_RUN_PROPERTIES) == 15


def test_the_module_export_list_is_sorted_unique_and_resolvable():
    """The shared boundary guard checks uniqueness and resolvability; this
    module additionally holds its export list in alphabetical order."""
    from dynamic_ai_products.extraction import manifests

    exported = manifests.__all__
    assert exported == sorted(exported)
    assert len(set(exported)) == len(exported)
    for name in exported:
        assert hasattr(manifests, name), name


# --- the seven-role manifest and live_call_authorization (ADR-035) ------------


def test_the_error_record_does_not_pin_the_authorization():
    """The six-artifact route writes the authorization but the error record's
    released field set is unchanged: it pins exactly four artifacts.

    The authorization is reachable from the run root and, on a successful run,
    from the prediction manifest as the seventh role. Adding a fifth pin here
    would widen a released contract for provenance that already exists.
    """
    record = _error_record()
    assert len(record) == 18
    assert not any(key.startswith("live_call_authorization") for key in record)
    assert not any("authorization" in key for key in record)


def test_the_authorization_and_rendered_contents_are_manifest_roles():
    """Bound in the prediction manifest, not in extraction_run or this record.

    ADR-036 (E-R) adds ``rendered_provider_contents`` as the eighth role, so the
    authorization keeps its position relative to the end of the tuple rather
    than an absolute index that a later insertion would silently shift.
    """
    from dynamic_ai_products.extraction.prediction_manifest import (
        REQUIRED_SOURCE_ARTIFACT_ROLES,
    )

    assert len(REQUIRED_SOURCE_ARTIFACT_ROLES) == 8
    assert REQUIRED_SOURCE_ARTIFACT_ROLES[-2] == "live_call_authorization"
    assert REQUIRED_SOURCE_ARTIFACT_ROLES[-1] == "extraction_run"
    assert "rendered_provider_contents" in REQUIRED_SOURCE_ARTIFACT_ROLES
    # extraction_run@0.1.0 is still strict and unwidened.
    assert len(EXTRACTION_RUN_PROPERTIES) == 15
    assert "live_call_authorization" not in EXTRACTION_RUN_PROPERTIES


@pytest.mark.parametrize(
    "stem,contract,properties,count",
    [
        (
            "adapter_qualification_record",
            QUALIFICATION_CONTRACT,
            QUALIFICATION_PROPERTIES,
            13,
        ),
        ("adapter_enablement_record", ENABLEMENT_CONTRACT, ENABLEMENT_PROPERTIES, 19),
        (
            "live_call_authorization",
            LIVE_AUTHORIZATION_CONTRACT,
            AUTHORIZATION_PROPERTIES,
            31,
        ),
    ],
)
def test_each_governance_property_set_matches_its_released_schema(
    stem, contract, properties, count
):
    schema = json.loads((SCHEMAS / f"{stem}.schema.json").read_text())
    assert len(properties) == count
    assert set(schema["required"]) == set(properties)
    assert set(schema["properties"]) == set(properties)
    assert schema["additionalProperties"] is False
    assert schema["properties"]["contract"]["const"] == contract


def test_the_governance_contract_identities_are_versioned_zero_one_zero():
    for contract in (
        QUALIFICATION_CONTRACT,
        ENABLEMENT_CONTRACT,
        LIVE_AUTHORIZATION_CONTRACT,
    ):
        assert contract.endswith("@0.1.0")


def test_the_authorization_carries_the_budget_meter_identity_pin():
    """E-B's gate rests on this pin, so it is required, not optional."""
    assert "budget_meter_identity" in AUTHORIZATION_PROPERTIES
    assert "budget_meter_version" in AUTHORIZATION_PROPERTIES


def test_the_enablement_record_carries_the_spec_024_reference():
    """SPEC-027 places the prompt qualification on enablement, not authorization."""
    assert "prompt_qualification_reference" in ENABLEMENT_PROPERTIES
    assert "prompt_qualification_sha256" in ENABLEMENT_PROPERTIES
    assert "prompt_qualification_reference" not in AUTHORIZATION_PROPERTIES


def test_no_governance_property_set_admits_a_free_text_field():
    """An upstream message must have no channel into an authorization chain."""
    for properties in (
        QUALIFICATION_PROPERTIES,
        ENABLEMENT_PROPERTIES,
        AUTHORIZATION_PROPERTIES,
    ):
        for forbidden in ("message", "detail", "note", "comment", "error"):
            assert not any(forbidden in name for name in properties), forbidden
