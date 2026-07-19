"""Slice 1A/1B model tests: foundations plus persisted-artifact contracts."""

import subprocess
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError as JsonSchemaValidationError
from pydantic import ValidationError, create_model

from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.models import (
    AssertionOutcome,
    AssertionSpec,
    CaseMembership,
    CaseSetManifest,
    ContractMetadata,
    EvaluationCase,
    EvaluationResultV2,
    EvaluationRunManifest,
    EvaluationStrictModel,
    FindingDisposition,
    MembershipEvent,
    PredictionEnvelope,
    ValidatorFinding,
)
from dynamic_ai_products.evaluation.schemas import load_schema

ROOT = Path(__file__).resolve().parents[2]
HEX = "a" * 64


class _Example(EvaluationStrictModel):
    name: str


# ---------------------------------------------------------------------------
# Slice 1A foundations
# ---------------------------------------------------------------------------


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _Example(name="ok", unexpected="boom")


def test_instances_are_frozen() -> None:
    instance = _Example(name="ok")
    with pytest.raises(ValidationError):
        instance.name = "changed"


def test_contract_metadata_round_trip() -> None:
    meta = ContractMetadata(
        contract_id="evaluation_case",
        contract_version="0.1.0",
        contract_hash="a" * 64,
    )
    assert meta.contract_id == "evaluation_case"
    assert meta.model_dump() == {
        "contract_id": "evaluation_case",
        "contract_version": "0.1.0",
        "contract_hash": "a" * 64,
    }


@pytest.mark.parametrize("field", ["contract_id", "contract_version", "contract_hash"])
def test_contract_metadata_rejects_empty_fields(field: str) -> None:
    payload = {
        "contract_id": "evaluation_case",
        "contract_version": "0.1.0",
        "contract_hash": "a" * 64,
    }
    payload[field] = ""
    with pytest.raises(ValidationError):
        ContractMetadata(**payload)


@pytest.mark.parametrize("field", ["contract_id", "contract_version"])
@pytest.mark.parametrize(
    "bad_value",
    [" ", "   ", "\t", " case", "case ", " 0.1.0", "0.1.0 "],
    ids=["space", "spaces", "tab", "leading", "trailing", "leading-version", "trailing-version"],
)
def test_identity_whitespace_is_rejected(field: str, bad_value: str) -> None:
    payload = {
        "contract_id": "evaluation_case",
        "contract_version": "0.1.0",
        "contract_hash": "a" * 64,
    }
    payload[field] = bad_value
    with pytest.raises(ValidationError):
        ContractMetadata(**payload)


@pytest.mark.parametrize(
    "bad_hash",
    ["", "a" * 63, "a" * 65, "g" * 64, "A" * 64, ("a" * 63) + "Z"],
    ids=["empty", "short", "long", "non-hex", "uppercase", "mixed-invalid"],
)
def test_malformed_contract_hash_is_rejected(bad_hash: str) -> None:
    with pytest.raises(ValidationError):
        ContractMetadata(
            contract_id="evaluation_case",
            contract_version="0.1.0",
            contract_hash=bad_hash,
        )


def test_valid_lowercase_sha256_hash_is_accepted() -> None:
    digest = "0123456789abcdef" * 4
    meta = ContractMetadata(
        contract_id="evaluation case",
        contract_version="0.1.0",
        contract_hash=digest,
    )
    assert meta.contract_hash == digest


def test_valid_identities_are_preserved_exactly() -> None:
    meta = ContractMetadata(
        contract_id="Evaluation Case",
        contract_version="0.1.0-Draft",
        contract_hash="b" * 64,
    )
    assert meta.contract_id == "Evaluation Case"
    assert meta.contract_version == "0.1.0-Draft"


# ---------------------------------------------------------------------------
# Slice 1B payload factories
# ---------------------------------------------------------------------------


def assertion_payload(**over: object) -> dict:
    payload: dict = {
        "assertion_id": "A-1",
        "kind": "expected_entity",
        "semantic_version": "v1",
        "target_references": ["EXAMPLE.PRODUCT.CAPABILITY.TASK"],
        "scoring_gate_config_references": ["scoring-gate-config-example"],
    }
    payload.update(over)
    return {k: v for k, v in payload.items() if v is not ...}


def case_payload(**over: object) -> dict:
    payload: dict = {
        "case_id": "CASE-1",
        "stage": "task_extraction",
        "stage_context": {},
        "input_source_ids": ["source-1"],
        "input_passage_ids": ["passage-1"],
        "assertions": [assertion_payload()],
        "failure_tags": [],
        "notes": "Example case.",
        "created_by": "researcher",
        "created_at": "2026-07-20T00:00:00Z",
        "guideline_version": "g-1",
    }
    payload.update(over)
    return {k: v for k, v in payload.items() if v is not ...}


def result_payload(**over: object) -> dict:
    payload: dict = {
        "eval_run_id": "run-1",
        "stage": "task_extraction",
        "dataset_version": "cs-1",
        "metrics": {},
        "execution_status": "completed",
        "gate_verdict": "pass",
    }
    payload.update(over)
    return {k: v for k, v in payload.items() if v is not ...}


def stamped(model_cls: type, contract_id: str, **body: object) -> dict:
    return {
        "contract": {
            "contract_id": contract_id,
            "contract_version": "0.1.0",
            "contract_hash": model_contract_hash(model_cls, contract_id, "0.1.0"),
        },
        **body,
    }


def membership_payload(case_id: str = "CASE-1") -> dict:
    return {
        "case_id": case_id,
        "partition": "dev",
        "suites": ["regression"],
        "input_packet_hash": HEX,
    }


GENERATED_FACTORIES: dict[type, object] = {
    CaseSetManifest: lambda: stamped(
        CaseSetManifest,
        "case_set_manifest",
        case_set_version="cs-1",
        lifecycle="draft",
        registry_snapshot_version="reg-1",
        registry_snapshot_hash=HEX,
        entries=[membership_payload()],
    ),
    MembershipEvent: lambda: stamped(
        MembershipEvent,
        "membership_event",
        previous_case_set_version="cs-1",
        new_case_set_version="cs-2",
        case_id="CASE-1",
        added_suites=["regression"],
        removed_suites=[],
        reason_code="promote_to_regression",
        actor="researcher",
        timestamp="2026-07-20T00:00:00Z",
    ),
    EvaluationRunManifest: lambda: stamped(
        EvaluationRunManifest,
        "evaluation_run_manifest",
        eval_run_id="run-1",
        prediction_run_id="pred-1",
        prediction_run_manifest_hash=HEX,
        case_set_version="cs-1",
        case_set_hash=HEX,
        registry_snapshot_hash=HEX,
        validator_bundle_version="vb-1",
        validator_bundle_hash=HEX,
        scoring_gate_config_version="sg-1",
        scoring_gate_config_hash=HEX,
        code_commit="f1d9ef8",
        pydantic_runtime_version="2.13.4",
    ),
    PredictionEnvelope: lambda: stamped(
        PredictionEnvelope,
        "prediction_envelope",
        prediction_record_id="rec-1",
        stage="task_extraction",
        source_references=["source-1"],
        prompt_model_metadata={"prompt_hash": "abc"},
        input_packet_hash=HEX,
        prediction_run_manifest_reference="pred-1-manifest",
    ),
    AssertionOutcome: lambda: stamped(
        AssertionOutcome,
        "assertion_outcome",
        eval_run_id="run-1",
        case_id="CASE-1",
        assertion_id="A-1",
        assertion_semantic_version="v1",
        outcome="satisfied",
    ),
    ValidatorFinding: lambda: stamped(
        ValidatorFinding,
        "validator_finding",
        finding_id="F-1",
        validator="evidence_quote_in_passage",
        validator_bundle_version="vb-1",
        validator_bundle_hash=HEX,
        rule_params_hash=HEX,
        severity="critical",
        run_id="run-1",
        case_id="CASE-1",
        entity_id="E-1",
        artifact_id="rec-1",
        observed_value="quote missing",
        expected_invariant="quote occurs in cited passage",
        message="evidence quote not found",
        evidence="passage-1",
        repairable=False,
        created_at="2026-07-20T00:00:00Z",
    ),
    FindingDisposition: lambda: stamped(
        FindingDisposition,
        "finding_disposition",
        disposition_id="D-1",
        finding_id="F-1",
        disposition="confirmed_defect",
        reviewer="researcher",
        timestamp="2026-07-20T00:00:00Z",
        rationale="confirmed against source",
        linked_evidence=["passage-1"],
        proposed_resolution_path="fix prediction and re-run",
    ),
}

CONTRACT_IDS: dict[type, str] = {
    CaseSetManifest: "case_set_manifest",
    MembershipEvent: "membership_event",
    EvaluationRunManifest: "evaluation_run_manifest",
    PredictionEnvelope: "prediction_envelope",
    AssertionOutcome: "assertion_outcome",
    ValidatorFinding: "validator_finding",
    FindingDisposition: "finding_disposition",
}

ALL_FACTORIES: dict[type, object] = {
    AssertionSpec: assertion_payload,
    EvaluationCase: case_payload,
    EvaluationResultV2: result_payload,
    CaseMembership: membership_payload,
    **GENERATED_FACTORIES,
}


# ---------------------------------------------------------------------------
# Every model: minimal validity, unknown fields, frozen, round trip
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_cls", list(ALL_FACTORIES), ids=lambda m: m.__name__)
def test_minimal_valid_instance(model_cls: type) -> None:
    instance = model_cls.model_validate(ALL_FACTORIES[model_cls]())
    assert instance is not None


@pytest.mark.parametrize("model_cls", list(ALL_FACTORIES), ids=lambda m: m.__name__)
def test_unknown_top_level_field_is_rejected(model_cls: type) -> None:
    payload = ALL_FACTORIES[model_cls]()
    payload["zzz_unknown_field"] = 1
    with pytest.raises(ValidationError):
        model_cls.model_validate(payload)


@pytest.mark.parametrize("model_cls", list(ALL_FACTORIES), ids=lambda m: m.__name__)
def test_frozen_top_level_mutation_is_rejected(model_cls: type) -> None:
    instance = model_cls.model_validate(ALL_FACTORIES[model_cls]())
    first_field = next(iter(model_cls.model_fields))
    with pytest.raises(ValidationError):
        setattr(instance, first_field, "changed")


@pytest.mark.parametrize("model_cls", list(ALL_FACTORIES), ids=lambda m: m.__name__)
def test_json_round_trip(model_cls: type) -> None:
    instance = model_cls.model_validate(ALL_FACTORIES[model_cls]())
    dumped = instance.model_dump(mode="json", exclude_unset=True)
    again = model_cls.model_validate(dumped)
    assert again.model_dump(mode="json", exclude_unset=True) == dumped


def test_tuple_fields_serialize_as_json_arrays() -> None:
    case = EvaluationCase.model_validate(case_payload())
    assert isinstance(case.input_source_ids, tuple)
    dumped = case.model_dump(mode="json", exclude_unset=True)
    assert isinstance(dumped["input_source_ids"], list)
    assert isinstance(dumped["assertions"], list)


@pytest.mark.parametrize(
    "field,factory",
    [
        ("stage_context", case_payload),
        ("metrics", result_payload),
    ],
)
def test_json_safe_fields_reject_arbitrary_python_objects(field: str, factory) -> None:
    payload = factory(**{field: {"bad": object()}})
    model_cls = EvaluationCase if factory is case_payload else EvaluationResultV2
    with pytest.raises(ValidationError):
        model_cls.model_validate(payload)


def test_prompt_model_metadata_rejects_arbitrary_python_objects() -> None:
    payload = GENERATED_FACTORIES[PredictionEnvelope]()
    payload["prompt_model_metadata"] = {"bad": object()}
    with pytest.raises(ValidationError):
        PredictionEnvelope.model_validate(payload)


def test_errors_items_reject_arbitrary_python_objects() -> None:
    with pytest.raises(ValidationError):
        EvaluationResultV2.model_validate(result_payload(errors=[object()]))


# ---------------------------------------------------------------------------
# Static-schema-backed models
# ---------------------------------------------------------------------------


def _static_validator(contract_id: str, version: str) -> Draft202012Validator:
    schema = load_schema(contract_id, version)
    return Draft202012Validator(dict(schema), format_checker=FormatChecker())


def test_case_serialization_validates_against_static_schema() -> None:
    case = EvaluationCase.model_validate(case_payload())
    _static_validator("evaluation_case", "0.1.0").validate(
        case.model_dump(mode="json", exclude_unset=True)
    )


@pytest.mark.parametrize(
    "payload",
    [
        result_payload(),
        result_payload(execution_status="invalid", gate_verdict=...),
        result_payload(execution_status="errored", gate_verdict=...),
    ],
    ids=["completed", "invalid-absent-verdict", "errored-absent-verdict"],
)
def test_result_serialization_validates_against_static_schema(payload: dict) -> None:
    result = EvaluationResultV2.model_validate(payload)
    _static_validator("evaluation_result", "0.2.0").validate(
        result.model_dump(mode="json", exclude_unset=True)
    )


def test_case_invalid_datetime_passes_model_but_fails_static_schema() -> None:
    case = EvaluationCase.model_validate(case_payload(created_at="not-a-date"))
    assert case.created_at == "not-a-date"
    with pytest.raises(JsonSchemaValidationError):
        _static_validator("evaluation_case", "0.1.0").validate(
            case.model_dump(mode="json", exclude_unset=True)
        )


def test_result_created_at_has_no_datetime_format_in_static_schema() -> None:
    result = EvaluationResultV2.model_validate(result_payload(created_at="not-a-date"))
    _static_validator("evaluation_result", "0.2.0").validate(
        result.model_dump(mode="json", exclude_unset=True)
    )


def test_valid_rfc3339_datetime_passes_static_schema() -> None:
    case = EvaluationCase.model_validate(case_payload(created_at="2026-07-20T00:00:00+00:00"))
    _static_validator("evaluation_case", "0.1.0").validate(
        case.model_dump(mode="json", exclude_unset=True)
    )


@pytest.mark.parametrize(
    "model_cls,factory", [(EvaluationCase, case_payload), (EvaluationResultV2, result_payload)]
)
def test_static_schema_models_reject_contract_field(model_cls: type, factory) -> None:
    payload = factory()
    payload["contract"] = {
        "contract_id": "x",
        "contract_version": "0.1.0",
        "contract_hash": HEX,
    }
    with pytest.raises(ValidationError):
        model_cls.model_validate(payload)


# ---------------------------------------------------------------------------
# Verdict presence matrix
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("verdict", ["pass", "fail", "indeterminate"])
def test_completed_with_each_verdict_is_valid(verdict: str) -> None:
    result = EvaluationResultV2.model_validate(result_payload(gate_verdict=verdict))
    assert result.gate_verdict == verdict


def test_completed_missing_verdict_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvaluationResultV2.model_validate(result_payload(gate_verdict=...))


def test_completed_null_verdict_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvaluationResultV2.model_validate(result_payload(gate_verdict=None))


@pytest.mark.parametrize("status", ["invalid", "errored"])
def test_noncompleted_absent_verdict_is_valid(status: str) -> None:
    result = EvaluationResultV2.model_validate(
        result_payload(execution_status=status, gate_verdict=...)
    )
    dumped = result.model_dump(mode="json", exclude_unset=True)
    assert "gate_verdict" not in dumped


@pytest.mark.parametrize("status", ["invalid", "errored"])
def test_noncompleted_null_verdict_is_rejected(status: str) -> None:
    with pytest.raises(ValidationError):
        EvaluationResultV2.model_validate(
            result_payload(execution_status=status, gate_verdict=None)
        )


@pytest.mark.parametrize("status", ["invalid", "errored"])
def test_noncompleted_supplied_verdict_is_rejected(status: str) -> None:
    with pytest.raises(ValidationError):
        EvaluationResultV2.model_validate(
            result_payload(execution_status=status, gate_verdict="fail")
        )


# ---------------------------------------------------------------------------
# Optional-but-non-null fields
# ---------------------------------------------------------------------------


def test_errors_absent_stays_absent() -> None:
    result = EvaluationResultV2.model_validate(result_payload())
    assert "errors" not in result.model_dump(mode="json", exclude_unset=True)


def test_errors_explicit_null_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EvaluationResultV2.model_validate(result_payload(errors=None))


def test_errors_empty_array_round_trips_as_tuple() -> None:
    result = EvaluationResultV2.model_validate(result_payload(errors=[]))
    assert result.errors == ()
    assert result.model_dump(mode="json", exclude_unset=True)["errors"] == []


def test_created_at_absent_ok_and_null_rejected() -> None:
    ok = EvaluationResultV2.model_validate(result_payload())
    assert "created_at" not in ok.model_dump(mode="json", exclude_unset=True)
    with pytest.raises(ValidationError):
        EvaluationResultV2.model_validate(result_payload(created_at=None))


def test_reviewer_notes_absence_differs_from_explicit_null() -> None:
    absent = EvaluationResultV2.model_validate(result_payload())
    assert "reviewer_notes" not in absent.model_dump(mode="json", exclude_unset=True)
    explicit = EvaluationResultV2.model_validate(result_payload(reviewer_notes=None))
    assert explicit.model_dump(mode="json", exclude_unset=True)["reviewer_notes"] is None


# ---------------------------------------------------------------------------
# Assertion identity presence semantics
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_cls,factory,fields",
    [
        (
            AssertionSpec,
            assertion_payload,
            ("semantic_version", "contract_hash"),
        ),
        (
            AssertionOutcome,
            lambda **over: GENERATED_FACTORIES[AssertionOutcome]() | over,
            ("assertion_semantic_version", "assertion_contract_hash"),
        ),
    ],
    ids=["AssertionSpec", "AssertionOutcome"],
)
class TestAssertionIdentity:
    def test_both_absent_rejected(self, model_cls, factory, fields) -> None:
        payload = factory()
        for field in fields:
            payload.pop(field, None)
        with pytest.raises(ValidationError):
            model_cls.model_validate(payload)

    @pytest.mark.parametrize("which", [0, 1])
    def test_explicit_null_rejected(self, model_cls, factory, fields, which) -> None:
        payload = factory()
        payload[fields[which]] = None
        with pytest.raises(ValidationError):
            model_cls.model_validate(payload)

    @pytest.mark.parametrize("bad", ["", " ", " v1", "v1 "])
    def test_blank_or_edge_whitespace_rejected(self, model_cls, factory, fields, bad) -> None:
        payload = factory()
        payload.pop(fields[0], None)
        payload[fields[1]] = bad
        with pytest.raises(ValidationError):
            model_cls.model_validate(payload)

    def test_hash_only_identity_accepted(self, model_cls, factory, fields) -> None:
        payload = factory()
        payload.pop(fields[0], None)
        payload[fields[1]] = "opaque-contract-hash-identity"
        instance = model_cls.model_validate(payload)
        assert getattr(instance, fields[1]) == "opaque-contract-hash-identity"


def test_assertion_contract_hash_is_opaque_not_hex64() -> None:
    payload = assertion_payload(semantic_version=..., contract_hash="not-a-sha256")
    assert AssertionSpec.model_validate(payload).contract_hash == "not-a-sha256"


# ---------------------------------------------------------------------------
# Generated-schema contract stamping
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_cls", list(GENERATED_FACTORIES), ids=lambda m: m.__name__)
def test_generated_model_correct_contract_accepted(model_cls: type) -> None:
    instance = model_cls.model_validate(GENERATED_FACTORIES[model_cls]())
    assert instance.contract.contract_id == CONTRACT_IDS[model_cls]
    assert instance.contract.contract_version == "0.1.0"


@pytest.mark.parametrize("model_cls", list(GENERATED_FACTORIES), ids=lambda m: m.__name__)
def test_generated_model_wrong_contract_id_rejected(model_cls: type) -> None:
    payload = GENERATED_FACTORIES[model_cls]()
    payload["contract"] = dict(payload["contract"], contract_id="wrong_contract")
    with pytest.raises(ValidationError):
        model_cls.model_validate(payload)


@pytest.mark.parametrize("model_cls", list(GENERATED_FACTORIES), ids=lambda m: m.__name__)
def test_generated_model_wrong_version_rejected(model_cls: type) -> None:
    payload = GENERATED_FACTORIES[model_cls]()
    payload["contract"] = dict(payload["contract"], contract_version="9.9.9")
    with pytest.raises(ValidationError):
        model_cls.model_validate(payload)


@pytest.mark.parametrize("model_cls", list(GENERATED_FACTORIES), ids=lambda m: m.__name__)
def test_generated_model_wrong_hash_rejected(model_cls: type) -> None:
    payload = GENERATED_FACTORIES[model_cls]()
    payload["contract"] = dict(payload["contract"], contract_hash="0" * 64)
    with pytest.raises(ValidationError):
        model_cls.model_validate(payload)


@pytest.mark.parametrize("model_cls", list(GENERATED_FACTORIES), ids=lambda m: m.__name__)
def test_generated_model_missing_contract_rejected(model_cls: type) -> None:
    payload = GENERATED_FACTORIES[model_cls]()
    payload.pop("contract")
    with pytest.raises(ValidationError):
        model_cls.model_validate(payload)


def test_generated_contract_hash_is_stable_and_model_specific() -> None:
    first = model_contract_hash(CaseSetManifest, "case_set_manifest", "0.1.0")
    second = model_contract_hash(CaseSetManifest, "case_set_manifest", "0.1.0")
    other = model_contract_hash(MembershipEvent, "membership_event", "0.1.0")
    assert first == second
    assert first != other


# ---------------------------------------------------------------------------
# Model-specific rules
# ---------------------------------------------------------------------------


def test_duplicate_case_membership_is_rejected() -> None:
    payload = GENERATED_FACTORIES[CaseSetManifest]()
    payload["entries"] = [membership_payload("CASE-1"), membership_payload("CASE-1")]
    with pytest.raises(ValidationError):
        CaseSetManifest.model_validate(payload)


def test_run_level_finding_without_case_or_entity_is_valid() -> None:
    payload = GENERATED_FACTORIES[ValidatorFinding]()
    payload.pop("case_id")
    payload.pop("entity_id")
    finding = ValidatorFinding.model_validate(payload)
    assert finding.case_id is None and finding.entity_id is None


_TIMESTAMP_FIELDS = [
    (MembershipEvent, "timestamp"),
    (ValidatorFinding, "created_at"),
    (FindingDisposition, "timestamp"),
]


@pytest.mark.parametrize("model_cls,field", _TIMESTAMP_FIELDS, ids=lambda x: getattr(x, "__name__", x))
@pytest.mark.parametrize(
    "bad_value",
    [
        "",
        " ",
        "   ",
        " 2026-07-20T00:00:00Z",
        "2026-07-20T00:00:00Z ",
        "\t2026-07-20T00:00:00Z",
        "2026-07-20T00:00:00Z\n",
    ],
    ids=["empty", "space", "spaces", "leading", "trailing", "leading-tab", "trailing-newline"],
)
def test_generated_timestamps_reject_blank_and_edge_whitespace(
    model_cls: type, field: str, bad_value: str
) -> None:
    payload = GENERATED_FACTORIES[model_cls]()
    payload[field] = bad_value
    with pytest.raises(ValidationError):
        model_cls.model_validate(payload)


@pytest.mark.parametrize("model_cls,field", _TIMESTAMP_FIELDS, ids=lambda x: getattr(x, "__name__", x))
def test_generated_timestamps_preserved_exactly(model_cls: type, field: str) -> None:
    payload = GENERATED_FACTORIES[model_cls]()
    payload[field] = "2026-07-20T00:00:00Z"
    assert getattr(model_cls.model_validate(payload), field) == "2026-07-20T00:00:00Z"


@pytest.mark.parametrize("model_cls,field", _TIMESTAMP_FIELDS, ids=lambda x: getattr(x, "__name__", x))
def test_generated_timestamps_allow_internal_space_unnormalized(
    model_cls: type, field: str
) -> None:
    payload = GENERATED_FACTORIES[model_cls]()
    payload[field] = "2026-07-20 00:00:00"
    assert getattr(model_cls.model_validate(payload), field) == "2026-07-20 00:00:00"


# ---------------------------------------------------------------------------
# Generated-contract structural tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("model_cls", list(GENERATED_FACTORIES), ids=lambda m: m.__name__)
def test_generated_artifact_nested_contract_shape(model_cls: type) -> None:
    instance = model_cls.model_validate(GENERATED_FACTORIES[model_cls]())
    dumped = instance.model_dump(mode="json", exclude_unset=True)
    assert isinstance(dumped["contract"], dict)
    assert set(dumped["contract"]) == {"contract_id", "contract_version", "contract_hash"}
    for meta_key in ("contract_id", "contract_version", "contract_hash"):
        assert meta_key not in dumped, f"{meta_key} must not be flattened to top level"


def test_runtime_values_do_not_change_the_contract_hash() -> None:
    base = GENERATED_FACTORIES[MembershipEvent]()
    other = dict(base, case_id="CASE-OTHER", reason_code="frozen_exposure", actor="reviewer-2")
    first = MembershipEvent.model_validate(base)
    second = MembershipEvent.model_validate(other)
    canonical = model_contract_hash(MembershipEvent, "membership_event", "0.1.0")
    assert first.contract.contract_hash == canonical
    assert second.contract.contract_hash == canonical
    assert first.case_id != second.case_id


def test_controlled_schema_change_alters_contract_hash() -> None:
    original = create_model("SyntheticContractModel", value=(str, ...))
    unchanged = model_contract_hash(original, "synthetic_contract", "0.0.1")
    assert unchanged == model_contract_hash(original, "synthetic_contract", "0.0.1")
    changed = create_model("SyntheticContractModel", value=(str, ...), extra_field=(int, 0))
    assert unchanged != model_contract_hash(changed, "synthetic_contract", "0.0.1")


def test_package_import_performs_no_filesystem_json_read() -> None:
    code = (
        "import builtins, sys\n"
        "sys.path.insert(0, 'src')\n"
        "opened = []\n"
        "orig = builtins.open\n"
        "builtins.open = lambda f, *a, **k: (opened.append(str(f)), orig(f, *a, **k))[1]\n"
        "import dynamic_ai_products.evaluation\n"
        "builtins.open = orig\n"
        "bad = [f for f in opened if str(f).endswith('.json')]\n"
        "assert not bad, bad\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
