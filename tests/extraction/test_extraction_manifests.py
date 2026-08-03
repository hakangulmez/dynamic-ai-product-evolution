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
    AUTHORIZATION_V2_PROPERTIES,
    BUDGET_POLICY_VERSION,
    CANONICAL_BUDGET_METER_IDENTITY,
    CANONICAL_BUDGET_METER_VERSION,
    ENABLEMENT_CONTRACT,
    ENABLEMENT_PROPERTIES,
    EXTRACTION_RUN_PROPERTIES,
    LIVE_AUTHORIZATION_CONTRACT,
    PROVIDER_ERROR_CONTRACT,
    PROVIDER_ERROR_REASONS,
    CLIENT_CONTRACT_V2_CONTRACT,
    PROVIDER_RATE_LIMIT_POLICY_VERSION_PIN,
    PROVIDER_RETRY_POLICY_VERSION_PIN,
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
    validate_budget_meter_identity,
    validate_provider_policy_versions,
    validate_v2_contract_execution_fields,
)
from dynamic_ai_products.extraction.prompt_qualification import (
    PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP,
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
    """SPEC-027 places the prompt qualification on enablement, not authorization.

    ADR-044 binds the artifact those two fields name, and the binding travels
    transitively: prompt qualification -> enablement -> authorization. Neither
    authorization property set gains a prompt field, and both are asserted, so a
    later "helpful" addition to the v2 set fails here rather than silently
    creating a second, unwalked path to the same reference.
    """
    assert "prompt_qualification_reference" in ENABLEMENT_PROPERTIES
    assert "prompt_qualification_sha256" in ENABLEMENT_PROPERTIES
    for properties in (AUTHORIZATION_PROPERTIES, AUTHORIZATION_V2_PROPERTIES):
        assert "prompt_qualification_reference" not in properties
        assert "prompt_qualification_sha256" not in properties
        assert not any("prompt" in name for name in properties)


def test_no_governance_property_set_admits_a_free_text_field():
    """An upstream message must have no channel into an authorization chain."""
    for properties in (
        QUALIFICATION_PROPERTIES,
        ENABLEMENT_PROPERTIES,
        AUTHORIZATION_PROPERTIES,
        AUTHORIZATION_V2_PROPERTIES,
        PROMPT_QUALIFICATION_PROPERTIES_BOOTSTRAP,
    ):
        for forbidden in ("message", "detail", "note", "comment", "error"):
            assert not any(forbidden in name for name in properties), forbidden


# --- ADR-047 (G3-2): the code-owned budget identity ---------------------------


def _canonical_authorization(**overrides) -> dict:
    payload = {
        "budget_meter_identity": CANONICAL_BUDGET_METER_IDENTITY,
        "budget_meter_version": CANONICAL_BUDGET_METER_VERSION,
        "budget_policy_version": BUDGET_POLICY_VERSION,
    }
    payload.update(overrides)
    return payload


def _canonical_mapping() -> dict:
    return {
        "meter_identity": CANONICAL_BUDGET_METER_IDENTITY,
        "meter_version": CANONICAL_BUDGET_METER_VERSION,
    }


def test_the_budget_identity_constants_have_one_home():
    assert CANONICAL_BUDGET_METER_IDENTITY == "dynamic_ai_products.extraction.budget_session"
    assert CANONICAL_BUDGET_METER_VERSION == "0.1.0"
    assert BUDGET_POLICY_VERSION == "budget_policy_v1"


def test_the_canonical_identity_and_policy_are_accepted_together():
    validate_budget_meter_identity(
        authorization=_canonical_authorization(),
        meter_identity=_canonical_mapping(),
        expected_budget_policy_version=BUDGET_POLICY_VERSION,
    )


@pytest.mark.parametrize(
    "override,expected",
    [
        ({"budget_meter_identity": "someone-elses-meter"}, "budget_meter_identity_mismatch"),
        ({"budget_meter_version": "9.9.9"}, "budget_meter_identity_mismatch"),
        ({"budget_policy_version": "budget_policy_v2"}, "budget_policy_version_mismatch"),
        ({"budget_policy_version": ""}, "budget_policy_version_mismatch"),
        ({"budget_policy_version": None}, "budget_policy_version_mismatch"),
    ],
)
def test_each_budget_mismatch_carries_its_own_reason(override, expected):
    """The policy version is not silently folded into the identity code."""
    with pytest.raises(ExtractionError) as caught:
        validate_budget_meter_identity(
            authorization=_canonical_authorization(**override),
            meter_identity=_canonical_mapping(),
            expected_budget_policy_version=BUDGET_POLICY_VERSION,
        )
    assert caught.value.reason_code == expected


def test_the_policy_version_is_not_read_from_the_meter_mapping():
    """The mapping carries exactly two keys and the loop must not want a third.

    Folding ``budget_policy_version`` into the ``removeprefix("budget_")`` loop
    would make it look for ``meter_identity["policy_version"]`` -- a key no
    session reports -- and every route including the canonical one would fail.
    """
    mapping = _canonical_mapping()
    assert set(mapping) == {"meter_identity", "meter_version"}
    validate_budget_meter_identity(
        authorization=_canonical_authorization(),
        meter_identity=mapping,
        expected_budget_policy_version=BUDGET_POLICY_VERSION,
    )


def test_the_expected_policy_version_parameter_has_no_default():
    """A caller that forgets it gets a TypeError, not a silently skipped check."""
    with pytest.raises(TypeError):
        validate_budget_meter_identity(
            authorization=_canonical_authorization(), meter_identity=_canonical_mapping()
        )


def test_the_validator_has_exactly_two_call_sites_each_with_three_keywords():
    """One v1 legacy call, one canonical F0 call, and none in between.

    The third assertion is the load-bearing one: it proves the F0 placement was a
    *move*, so no second code path can validate the identity after the permit
    handshake. Read with AST rather than grep, because a comment or docstring
    naming the function is not a call.
    """
    import ast

    from dynamic_ai_products.extraction import run_extraction

    tree = ast.parse(Path(run_extraction.__file__).read_text(encoding="utf-8"))
    scope: list[str] = []
    seen: list[tuple[str, tuple[str, ...]]] = []

    class Visitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node):
            scope.append(node.name)
            self.generic_visit(node)
            scope.pop()

        def visit_Call(self, node):
            if getattr(node.func, "id", None) == "validate_budget_meter_identity":
                seen.append((scope[-1], tuple(sorted(k.arg for k in node.keywords))))
            self.generic_visit(node)

    Visitor().visit(tree)
    expected = ("authorization", "expected_budget_policy_version", "meter_identity")
    assert len(seen) == 2
    assert all(keywords == expected for _fn, keywords in seen)
    assert {fn for fn, _ in seen} == {"_run_authorized_stage", "run_extraction_stage_v2"}
    assert "_run_two_operation_stage" not in {fn for fn, _ in seen}


# --- ADR-048 (G3-3): the narrow v2 gate and the policy pins -------------------


def _v2_contract() -> dict:
    """A real contract from the provider builder, not a hand-written stand-in.

    The builder is pure -- grammar validation and string composition, no network,
    no filesystem, no clock, no credential -- so a test may call it freely, and a
    hand-written mapping would drift from what actually executes.
    """
    from dynamic_ai_products.providers.client_contract_v2 import build_client_contract_v2

    return build_client_contract_v2(vertex_project="my-research-project")


def test_a_real_v2_contract_passes_the_narrow_gate_unchanged():
    contract = _v2_contract()
    assert validate_v2_contract_execution_fields(contract) == contract


def test_the_gate_returns_a_fresh_outer_mapping():
    """Shallow, and only shallow.

    ``dict(contract)`` gives a new outer mapping, so rebinding a top-level key on
    the result does not touch the caller's. It does **not** give an isolated
    contract: ``operation_endpoints`` is the same nested dict on both sides, and
    mutating it through the result is visible to the caller -- measured. Nothing
    here relies on deep isolation, so the assertion is limited to what is true.
    """
    contract = _v2_contract()
    checked = validate_v2_contract_execution_fields(contract)
    assert checked is not contract
    checked["api_version"] = "mutated"
    assert contract["api_version"] != "mutated"


_TEXT_FIELDS = (
    "api_version",
    "endpoint_match_mode",
    "endpoint_query_policy",
    "protocol_switch_policy",
    "rate_limit_policy_version",
    "retry_policy_version",
)


@pytest.mark.parametrize("field", _TEXT_FIELDS)
@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda c, f: c.pop(f), id="missing"),
        pytest.param(lambda c, f: c.__setitem__(f, 7), id="wrong-type"),
        pytest.param(lambda c, f: c.__setitem__(f, ""), id="empty"),
    ],
)
def test_the_gate_refuses_every_malformed_execution_string(field, mutate):
    """Eighteen cases: six fields the projection and the policy validator read."""
    contract = _v2_contract()
    mutate(contract, field)
    with pytest.raises(ExtractionError) as caught:
        validate_v2_contract_execution_fields(contract)
    assert caught.value.reason_code == "client_contract_invalid"


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="missing"),
        pytest.param(7, id="wrong-type"),
        pytest.param("", id="empty"),
        pytest.param("extraction_provider_client_contract@0.1.0", id="v1-identity"),
        pytest.param("some_other_contract@9.9.9", id="foreign-identity"),
    ],
)
def test_the_gate_refuses_every_contract_identity_that_is_not_the_v2_one(value):
    """A non-empty *wrong* identity is the case that matters for G4.

    ``derive_routing_contract`` will be called with no runner in the picture, so
    a v1 contract -- which has no ``operation_endpoints`` at all -- must be
    refused by the producer itself rather than by a caller that may not exist.
    """
    contract = _v2_contract()
    if value is None:
        contract.pop("contract")
    else:
        contract["contract"] = value
    with pytest.raises(ExtractionError) as caught:
        validate_v2_contract_execution_fields(contract)
    assert caught.value.reason_code == "client_contract_invalid"


@pytest.mark.parametrize(
    "value",
    [
        pytest.param(None, id="missing"),
        pytest.param(7, id="wrong-type"),
        pytest.param("", id="empty"),
        pytest.param("0.1.0", id="v1-schema-version"),
        pytest.param("9.9.9", id="foreign-schema-version"),
    ],
)
def test_the_gate_refuses_every_schema_version_that_is_not_the_v2_one(value):
    contract = _v2_contract()
    if value is None:
        contract.pop("schema_version")
    else:
        contract["schema_version"] = value
    with pytest.raises(ExtractionError) as caught:
        validate_v2_contract_execution_fields(contract)
    assert caught.value.reason_code == "client_contract_invalid"


@pytest.mark.parametrize(
    "mutate",
    [
        pytest.param(lambda c: c.pop("operation_endpoints"), id="missing"),
        pytest.param(
            lambda c: c.__setitem__("operation_endpoints", ["a", "b"]), id="not-a-mapping"
        ),
        pytest.param(
            lambda c: c["operation_endpoints"].__setitem__("embed_content", "https://x/y"),
            id="extra-key",
        ),
        pytest.param(
            lambda c: c["operation_endpoints"].pop("count_tokens"), id="missing-key"
        ),
        pytest.param(
            lambda c: c["operation_endpoints"].__setitem__("count_tokens", 7),
            id="non-string-url",
        ),
        pytest.param(
            lambda c: c["operation_endpoints"].__setitem__("generate_content", ""),
            id="empty-url",
        ),
    ],
)
def test_the_gate_requires_exactly_the_two_named_operation_endpoints(mutate):
    """Equality, not superset.

    A third operation would be a destination this route never authorized, and a
    missing one would leave half the route undeclared. Both are refusals.
    """
    contract = _v2_contract()
    mutate(contract)
    with pytest.raises(ExtractionError) as caught:
        validate_v2_contract_execution_fields(contract)
    assert caught.value.reason_code == "client_contract_invalid"


def test_the_gate_is_narrow_and_says_so_by_passing_a_contract_missing_other_fields():
    """The honest boundary of this gate, asserted rather than claimed.

    ``model_parameters`` and ``thinking_config`` are real v2 properties that this
    gate does **not** look at -- their protection is the contract digest the
    authorization pins, not this function. If this test ever starts failing, the
    gate has quietly become a schema executor and the docstring is a lie.
    """
    contract = _v2_contract()
    del contract["model_parameters"]
    del contract["thinking_config"]
    assert validate_v2_contract_execution_fields(contract)["contract"] == (
        CLIENT_CONTRACT_V2_CONTRACT
    )


def _authorization(**overrides) -> dict:
    base = {
        "retry_policy_version": PROVIDER_RETRY_POLICY_VERSION_PIN,
        "rate_limit_policy_version": PROVIDER_RATE_LIMIT_POLICY_VERSION_PIN,
    }
    base.update(overrides)
    return base


def test_matching_policy_versions_on_both_sides_are_accepted():
    validate_provider_policy_versions(
        authorization=_authorization(), client_contract=_v2_contract()
    )


@pytest.mark.parametrize(
    ("side", "field", "value", "expected"),
    [
        pytest.param(
            "authorization",
            "retry_policy_version",
            "retry_policy_v2",
            "retry_policy_version_mismatch",
            id="S2-authorization-retry-drift",
        ),
        pytest.param(
            "contract",
            "retry_policy_version",
            "retry_policy_v9",
            "retry_policy_version_mismatch",
            id="S3-connector-retry-drift",
        ),
        pytest.param(
            "authorization",
            "rate_limit_policy_version",
            "rate_limit_policy_v1",
            "rate_limit_policy_version_mismatch",
            id="S5-collection-namespace-spelling",
        ),
        pytest.param(
            "contract",
            "rate_limit_policy_version",
            "rate_limit_policy_v9",
            "rate_limit_policy_version_mismatch",
            id="S5b-connector-rate-drift",
        ),
    ],
)
def test_a_policy_version_that_this_build_does_not_implement_is_refused(
    side, field, value, expected
):
    authorization = _authorization()
    contract = _v2_contract()
    (authorization if side == "authorization" else contract)[field] = value
    with pytest.raises(ExtractionError) as caught:
        validate_provider_policy_versions(
            authorization=authorization, client_contract=contract
        )
    assert caught.value.reason_code == expected


def test_two_artifacts_that_agree_on_a_wrong_policy_version_are_still_refused():
    """S4 -- the case a single authorization/contract comparison would miss.

    Both sides carry the same value, so they agree perfectly. They are both
    wrong, and only a third, code-owned side can say so. This is why there are
    four comparisons against the pin rather than one between the two artifacts.
    """
    authorization = _authorization(retry_policy_version="agreed_but_wrong_v1")
    contract = _v2_contract()
    contract["retry_policy_version"] = "agreed_but_wrong_v1"
    with pytest.raises(ExtractionError) as caught:
        validate_provider_policy_versions(
            authorization=authorization, client_contract=contract
        )
    assert caught.value.reason_code == "retry_policy_version_mismatch"


def test_when_both_policy_versions_drift_the_retry_code_is_the_one_that_is_raised():
    """Order is part of the contract, not an implementation detail.

    A caller reading the reason code should learn something stable rather than
    something that depends on which comparison happened to run first.
    """
    authorization = _authorization(
        retry_policy_version="wrong_retry_v1", rate_limit_policy_version="wrong_rate_v1"
    )
    contract = _v2_contract()
    contract["retry_policy_version"] = "wrong_retry_v1"
    contract["rate_limit_policy_version"] = "wrong_rate_v1"
    with pytest.raises(ExtractionError) as caught:
        validate_provider_policy_versions(
            authorization=authorization, client_contract=contract
        )
    assert caught.value.reason_code == "retry_policy_version_mismatch"
    assert caught.value.reason_code != "rate_limit_policy_version_mismatch"


def test_when_only_the_rate_limit_drifts_the_rate_limit_code_is_raised():
    """The symmetric case, so the ordering test above cannot hide a "always
    retry" bug."""
    authorization = _authorization(rate_limit_policy_version="wrong_rate_v1")
    contract = _v2_contract()
    contract["rate_limit_policy_version"] = "wrong_rate_v1"
    with pytest.raises(ExtractionError) as caught:
        validate_provider_policy_versions(
            authorization=authorization, client_contract=contract
        )
    assert caught.value.reason_code == "rate_limit_policy_version_mismatch"


def test_the_v2_identity_literal_is_spelled_exactly_once_under_extraction():
    """One owner for the identity string, enforced rather than agreed.

    Scoped to the identity literal only. ``"0.2.0"`` is deliberately **not**
    counted: it already spells the authorization's and the input packet's own
    schema versions, so counting it would either fail or force edits to two
    unrelated modules. The schema version is protected by the drift test in
    ``test_live_authorization_validation`` instead.
    """
    package = Path(__file__).resolve().parents[2] / "src" / "dynamic_ai_products" / "extraction"
    literal = '"' + CLIENT_CONTRACT_V2_CONTRACT + '"'
    holders = {
        module.name: module.read_text(encoding="utf-8").count(literal)
        for module in package.rglob("*.py")
        if literal in module.read_text(encoding="utf-8")
    }
    assert holders == {"manifests.py": 1}
