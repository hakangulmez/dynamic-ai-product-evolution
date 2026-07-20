"""Slice 2: evaluation-case loading and validation tests.

Tracked fixtures cover the Slice 2 stop point (template and fixtures load;
prohibited-field fixtures rejected); all failure variants are generated
under ``tmp_path``. No collection loading, ordering, or duplicate-case-ID
behavior is tested here (deferred to later slices).
"""

import inspect
import json
import shutil
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import jsonschema
import pydantic
import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import cases as cases_module
from dynamic_ai_products.evaluation.cases import (
    CaseArtifactNotAFileError,
    CaseArtifactNotFoundError,
    CaseDecodeError,
    CaseJsonError,
    CaseLoadError,
    CaseModelValidationError,
    CasePathEscapeError,
    CaseReadError,
    CaseSchemaValidationError,
    CaseTopLevelTypeError,
    InvalidEvaluationRootError,
    ProhibitedLegacyFieldError,
    load_case,
)
from dynamic_ai_products.evaluation.models import EvaluationCase
from dynamic_ai_products.evaluation.schemas import (
    SchemaFileMissingError,
    SchemaHashMismatchError,
    load_schema as real_load_schema,
)

ROOT = Path(__file__).resolve().parents[2]
EVALS_DIR = ROOT / "evals"
FIXTURE_ROOT = ROOT / "evals" / "fixtures" / "evaluation_harness" / "cases"

LEGACY_FIELD_SAMPLES = {
    "split": "dev",
    "company_id": "SYNTH-COMPANY-0001",
    "observation_date": "2025-12-31",
    "expected_status": "valid",
    "expected_entities": ["SYNTH.LEGACY.EXPECTED"],
    "forbidden_entities": ["SYNTH.LEGACY.FORBIDDEN"],
}


def base_payload(**overrides):
    payload = {
        "case_id": "SYNTH-TMP-0001",
        "stage": "task_extraction",
        "stage_context": {},
        "input_source_ids": ["synth-source-tmp"],
        "input_passage_ids": ["synth-passage-tmp"],
        "assertions": [
            {
                "assertion_id": "SYNTH-TMP-0001-A1",
                "kind": "expected_entity",
                "semantic_version": "0.1.0",
                "target_references": ["SYNTH.TMP.TASK"],
                "scoring_gate_config_references": ["synth-scoring-gate-tmp"],
            }
        ],
        "failure_tags": [],
        "notes": "Synthetic tmp-path case.",
        "created_by": "synthetic-researcher",
        "created_at": "2026-07-19T00:00:00Z",
        "guideline_version": "draft-v0.1",
    }
    payload.update(overrides)
    return payload


def write_case(tmp_path: Path, content, name: str = "case.json") -> Path:
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_text(json.dumps(content), encoding="utf-8")
    return path


def load_tmp(tmp_path: Path, content, name: str = "case.json") -> EvaluationCase:
    write_case(tmp_path, content, name)
    return load_case(name, eval_root=tmp_path)


# --- Successful loading -------------------------------------------------


def test_loads_valid_minimal_fixture() -> None:
    case = load_case("valid_minimal_case.json", eval_root=FIXTURE_ROOT)
    assert case.case_id == "SYNTH-CASE-MIN-0001"
    assert case.assertions[0].semantic_version == "0.1.0"


def test_loads_valid_full_fixture() -> None:
    case = load_case("valid_full_case.json", eval_root=FIXTURE_ROOT)
    assert case.case_id == "SYNTH-CASE-FULL-0002"
    assert case.stage_context["observation_window"]["start"] == "2025-01-01"
    assert len(case.assertions) == 2


def test_loads_repository_template() -> None:
    case = load_case("templates/eval_case.template.json", eval_root=EVALS_DIR)
    assert isinstance(case, EvaluationCase)


def test_returns_evaluation_case_type(tmp_path: Path) -> None:
    assert isinstance(load_tmp(tmp_path, base_payload()), EvaluationCase)


def test_top_level_model_is_frozen(tmp_path: Path) -> None:
    case = load_tmp(tmp_path, base_payload())
    with pytest.raises(pydantic.ValidationError):
        case.case_id = "MUTATED"  # type: ignore[misc]


def test_repeated_loads_equal_but_distinct() -> None:
    first = load_case("valid_minimal_case.json", eval_root=FIXTURE_ROOT)
    second = load_case("valid_minimal_case.json", eval_root=FIXTURE_ROOT)
    assert first == second
    assert first is not second


def test_tuple_representation(tmp_path: Path) -> None:
    case = load_tmp(tmp_path, base_payload())
    assert isinstance(case.assertions, tuple)
    assert isinstance(case.input_source_ids, tuple)
    assert isinstance(case.input_passage_ids, tuple)
    assert isinstance(case.failure_tags, tuple)
    assert isinstance(case.assertions[0].target_references, tuple)


def test_exact_string_preservation(tmp_path: Path) -> None:
    notes = "  synthetic   internally   spaced  note  "
    case = load_tmp(tmp_path, base_payload(notes=notes))
    assert case.notes == notes


def test_valid_rfc3339_offset_datetime_accepted(tmp_path: Path) -> None:
    case = load_tmp(tmp_path, base_payload(created_at="2026-07-19T08:30:00+00:00"))
    assert case.created_at == "2026-07-19T08:30:00+00:00"


def test_semantic_version_only_assertion() -> None:
    case = load_case("valid_minimal_case.json", eval_root=FIXTURE_ROOT)
    assertion = case.assertions[0]
    assert assertion.semantic_version == "0.1.0"
    assert assertion.contract_hash is None


def test_contract_hash_only_assertion() -> None:
    case = load_case("valid_full_case.json", eval_root=FIXTURE_ROOT)
    assertion = case.assertions[1]
    assert assertion.contract_hash == "synthetic-opaque-assertion-contract-identity-0002"
    assert assertion.semantic_version is None


def test_source_bytes_unchanged_after_load() -> None:
    path = FIXTURE_ROOT / "valid_minimal_case.json"
    before = path.read_bytes()
    load_case("valid_minimal_case.json", eval_root=FIXTURE_ROOT)
    assert path.read_bytes() == before


# --- Root and path safety ------------------------------------------------


def test_omitted_eval_root_is_typeerror() -> None:
    with pytest.raises(TypeError):
        load_case("case.json")  # type: ignore[call-arg]


def test_none_eval_root_rejected() -> None:
    with pytest.raises(InvalidEvaluationRootError) as excinfo:
        load_case("case.json", eval_root=None)  # type: ignore[arg-type]
    assert excinfo.value.observed_type == "NoneType"


def test_empty_string_root_rejected() -> None:
    with pytest.raises(InvalidEvaluationRootError) as excinfo:
        load_case("case.json", eval_root="")
    assert excinfo.value.supplied_root == ""


def test_explicit_dot_root_is_legal(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_case(tmp_path, base_payload())
    monkeypatch.chdir(tmp_path)
    case = load_case("case.json", eval_root=".")
    assert isinstance(case, EvaluationCase)


def test_nonexistent_root_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidEvaluationRootError):
        load_case("case.json", eval_root=tmp_path / "missing-root")


def test_root_that_is_a_file_rejected(tmp_path: Path) -> None:
    file_root = write_case(tmp_path, base_payload(), name="not-a-dir.json")
    with pytest.raises(InvalidEvaluationRootError):
        load_case("case.json", eval_root=file_root)


def test_relative_contained_path(tmp_path: Path) -> None:
    sub = tmp_path / "nested"
    sub.mkdir()
    write_case(sub, base_payload())
    assert isinstance(load_case("nested/case.json", eval_root=tmp_path), EvaluationCase)


def test_absolute_contained_path(tmp_path: Path) -> None:
    path = write_case(tmp_path, base_payload())
    assert isinstance(load_case(str(path), eval_root=tmp_path), EvaluationCase)


def test_absolute_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    escaped = write_case(outside, base_payload())
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(CasePathEscapeError):
        load_case(str(escaped), eval_root=root)


def test_dotdot_traversal_escape_rejected(tmp_path: Path) -> None:
    write_case(tmp_path, base_payload(), name="outside.json")
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(CasePathEscapeError) as excinfo:
        load_case("../outside.json", eval_root=root)
    assert excinfo.value.artifact_reference == "../outside.json"


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret"
    outside.mkdir()
    target = write_case(outside, base_payload())
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.json").symlink_to(target)
    with pytest.raises(CasePathEscapeError):
        load_case("link.json", eval_root=root)


def test_root_symlink_resolves_to_real_directory(tmp_path: Path) -> None:
    real_root = tmp_path / "real-root"
    real_root.mkdir()
    write_case(real_root, base_payload())
    link_root = tmp_path / "root-link"
    link_root.symlink_to(real_root, target_is_directory=True)
    assert isinstance(load_case("case.json", eval_root=link_root), EvaluationCase)


def test_prefix_confusion_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "evals"
    root.mkdir()
    sibling = tmp_path / "evals-escape"
    sibling.mkdir()
    escaped = write_case(sibling, base_payload())
    with pytest.raises(CasePathEscapeError):
        load_case(str(escaped), eval_root=root)


def test_missing_artifact_rejected(tmp_path: Path) -> None:
    with pytest.raises(CaseArtifactNotFoundError) as excinfo:
        load_case("sub/missing.json", eval_root=tmp_path)
    assert excinfo.value.artifact_reference == "sub/missing.json"


def test_directory_artifact_rejected(tmp_path: Path) -> None:
    (tmp_path / "a-directory").mkdir()
    with pytest.raises(CaseArtifactNotAFileError) as excinfo:
        load_case("a-directory", eval_root=tmp_path)
    assert excinfo.value.artifact_reference == "a-directory"


def test_escape_error_hides_resolved_external_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret"
    outside.mkdir()
    target = write_case(outside, base_payload())
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.json").symlink_to(target)
    with pytest.raises(CasePathEscapeError) as excinfo:
        load_case("link.json", eval_root=root)
    exc = excinfo.value
    assert "outside-secret" not in str(exc)
    assert exc.artifact_reference == "link.json"


# --- Reading, decoding, and strict JSON ----------------------------------


def test_read_oserror_translated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_case(tmp_path, base_payload())

    def boom(self):
        raise OSError("synthetic read failure")

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(CaseReadError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert isinstance(excinfo.value.__cause__, OSError)


def test_invalid_utf8_rejected(tmp_path: Path) -> None:
    write_case(tmp_path, b'\xff\xfe{"case_id": "x"}')
    with pytest.raises(CaseDecodeError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert isinstance(excinfo.value.__cause__, UnicodeDecodeError)


def test_malformed_json_rejected(tmp_path: Path) -> None:
    write_case(tmp_path, "{not valid json")
    with pytest.raises(CaseJsonError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert isinstance(excinfo.value.__cause__, json.JSONDecodeError)


def test_trailing_content_rejected(tmp_path: Path) -> None:
    write_case(tmp_path, json.dumps(base_payload()) + " trailing")
    with pytest.raises(CaseJsonError):
        load_case("case.json", eval_root=tmp_path)


def test_utf8_bom_rejected(tmp_path: Path) -> None:
    write_case(tmp_path, b"\xef\xbb\xbf" + json.dumps(base_payload()).encode("utf-8"))
    with pytest.raises(CaseJsonError):
        load_case("case.json", eval_root=tmp_path)


@pytest.mark.parametrize(
    ("text", "observed_type"),
    [("[1, 2]", "list"), ('"synthetic"', "str"), ("null", "NoneType")],
)
def test_non_object_top_level_rejected(tmp_path: Path, text: str, observed_type: str) -> None:
    write_case(tmp_path, text)
    with pytest.raises(CaseTopLevelTypeError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.observed_type == observed_type


def test_duplicate_top_level_key_rejected(tmp_path: Path) -> None:
    write_case(tmp_path, '{"case_id": "a", "case_id": "b"}')
    with pytest.raises(CaseJsonError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "case_id"


def test_duplicate_nested_key_rejected(tmp_path: Path) -> None:
    write_case(tmp_path, '{"stage_context": {"k": 1, "k": 2}}')
    with pytest.raises(CaseJsonError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "k"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_constants_rejected(tmp_path: Path, constant: str) -> None:
    write_case(tmp_path, '{"stage_context": {"x": ' + constant + "}}")
    with pytest.raises(CaseJsonError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.constant_name == constant


@pytest.mark.parametrize(
    ("literal", "constant_name"), [("1e999", "Infinity"), ("-1e999", "-Infinity")]
)
def test_numeric_overflow_to_infinity_rejected(
    tmp_path: Path, literal: str, constant_name: str
) -> None:
    write_case(tmp_path, '{"stage_context": {"x": ' + literal + "}}")
    with pytest.raises(CaseJsonError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.constant_name == constant_name


def test_finite_numbers_remain_valid(tmp_path: Path) -> None:
    context = {"count": 3, "ratio": 0.5, "negative": -2.25}
    case = load_tmp(tmp_path, base_payload(stage_context=context))
    assert case.stage_context == context


def test_string_nan_remains_a_string(tmp_path: Path) -> None:
    case = load_tmp(tmp_path, base_payload(stage_context={"note": "NaN"}))
    assert case.stage_context["note"] == "NaN"


# --- Static-schema and legacy-field failures -----------------------------


def test_nonlegacy_unknown_property_is_schema_failure(tmp_path: Path) -> None:
    write_case(tmp_path, base_payload(zzz_unknown_property="x"))
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.validator_keyword == "additionalProperties"


def test_missing_required_property_rejected(tmp_path: Path) -> None:
    payload = base_payload()
    del payload["notes"]
    write_case(tmp_path, payload)
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.validator_keyword == "required"


def test_assertion_without_identity_rejected(tmp_path: Path) -> None:
    payload = base_payload()
    del payload["assertions"][0]["semantic_version"]
    write_case(tmp_path, payload)
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.json_pointer == "/assertions/0"
    assert excinfo.value.validator_keyword == "anyOf"


def test_explicit_null_assertion_identity_rejected(tmp_path: Path) -> None:
    payload = base_payload()
    payload["assertions"][0]["semantic_version"] = None
    write_case(tmp_path, payload)
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.json_pointer == "/assertions/0/semantic_version"


def test_invalid_assertion_kind_rejected(tmp_path: Path) -> None:
    payload = base_payload()
    payload["assertions"][0]["kind"] = "synthetic_bogus_kind"
    write_case(tmp_path, payload)
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.json_pointer == "/assertions/0/kind"
    assert excinfo.value.validator_keyword == "enum"


def test_empty_target_references_rejected(tmp_path: Path) -> None:
    payload = base_payload()
    payload["assertions"][0]["target_references"] = []
    write_case(tmp_path, payload)
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.json_pointer == "/assertions/0/target_references"
    assert excinfo.value.validator_keyword == "minItems"


def test_empty_scoring_gate_config_references_rejected(tmp_path: Path) -> None:
    payload = base_payload()
    payload["assertions"][0]["scoring_gate_config_references"] = []
    write_case(tmp_path, payload)
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.json_pointer == "/assertions/0/scoring_gate_config_references"


def test_empty_assertions_rejected(tmp_path: Path) -> None:
    write_case(tmp_path, base_payload(assertions=[]))
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.json_pointer == "/assertions"
    assert excinfo.value.validator_keyword == "minItems"


def test_invalid_created_at_rejected_and_value_not_leaked(tmp_path: Path) -> None:
    write_case(tmp_path, base_payload(created_at="SYNTHETIC-BAD-DATE"))
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    exc = excinfo.value
    assert exc.json_pointer == "/created_at"
    assert exc.validator_keyword == "format"
    assert "SYNTHETIC-BAD-DATE" not in str(exc)
    for attr in (exc.artifact_reference, exc.json_pointer, exc.validator_keyword, exc.schema_path):
        assert "SYNTHETIC-BAD-DATE" not in attr


def test_membership_like_field_is_schema_failure_not_legacy(tmp_path: Path) -> None:
    write_case(tmp_path, base_payload(partition="dev"))
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.validator_keyword == "additionalProperties"


@pytest.mark.parametrize("field", sorted(LEGACY_FIELD_SAMPLES))
def test_each_prohibited_legacy_field_rejected(tmp_path: Path, field: str) -> None:
    write_case(tmp_path, base_payload(**{field: LEGACY_FIELD_SAMPLES[field]}))
    with pytest.raises(ProhibitedLegacyFieldError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.field_names == (field,)


def test_tracked_legacy_fixture_reports_all_six_sorted() -> None:
    with pytest.raises(ProhibitedLegacyFieldError) as excinfo:
        load_case("prohibited_legacy_fields_case.json", eval_root=FIXTURE_ROOT)
    assert excinfo.value.field_names == (
        "company_id",
        "expected_entities",
        "expected_status",
        "forbidden_entities",
        "observation_date",
        "split",
    )


def test_multiple_legacy_fields_sorted_tuple(tmp_path: Path) -> None:
    write_case(
        tmp_path,
        base_payload(split="dev", company_id="SYNTH-COMPANY-0001", expected_status="valid"),
    )
    with pytest.raises(ProhibitedLegacyFieldError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.field_names == ("company_id", "expected_status", "split")


def test_deterministic_schema_error_selection(tmp_path: Path) -> None:
    payload = base_payload(zzz_unknown_property="x")
    del payload["notes"]
    payload["assertions"][0]["kind"] = "synthetic_bogus_kind"
    write_case(tmp_path, payload)
    selected = []
    for _ in range(2):
        with pytest.raises(CaseSchemaValidationError) as excinfo:
            load_case("case.json", eval_root=tmp_path)
        selected.append(
            (excinfo.value.json_pointer, excinfo.value.validator_keyword)
        )
    assert selected[0] == selected[1] == ("", "additionalProperties")


def test_schema_error_chains_original_jsonschema_error(tmp_path: Path) -> None:
    write_case(tmp_path, base_payload(zzz_unknown_property="x"))
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert isinstance(excinfo.value.__cause__, jsonschema.exceptions.ValidationError)


def test_json_pointer_escapes_special_tokens() -> None:
    assert cases_module._json_pointer(["a/b", "c~d", 3]) == "/a~1b/c~0d/3"
    assert cases_module._json_pointer([]) == ""


# --- Pydantic (model) failures -------------------------------------------


def test_model_validation_failure_edge_whitespace_identity(tmp_path: Path) -> None:
    payload = base_payload()
    payload["assertions"][0]["semantic_version"] = " 0.1.0 "
    write_case(tmp_path, payload)
    with pytest.raises(CaseModelValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    exc = excinfo.value
    assert isinstance(exc.__cause__, pydantic.ValidationError)
    # Two real pydantic errors, reported as deterministically sorted pairs:
    # the failing item, plus the variadic tuple counting valid items only.
    assert exc.field_locations == ("assertions", "assertions/0")
    assert exc.error_types == ("too_short", "value_error")


def test_model_error_message_and_attributes_are_safe(tmp_path: Path) -> None:
    payload = base_payload()
    payload["assertions"][0]["semantic_version"] = " 0.1.0 "
    write_case(tmp_path, payload)
    with pytest.raises(CaseModelValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    exc = excinfo.value
    assert " 0.1.0 " not in str(exc)
    for attr in (exc.artifact_reference, *exc.field_locations, *exc.error_types):
        assert " 0.1.0 " not in attr
    assert json.dumps(payload) not in str(exc)


# --- Registry and schema integration -------------------------------------


def _tmp_schema_repo(tmp_path: Path) -> Path:
    """Minimal repo copy carrying ONLY the case schema (no Phase 0 manifest)."""
    (tmp_path / "schemas").mkdir(parents=True)
    shutil.copy(
        ROOT / "schemas" / "evaluation_case.schema.json",
        tmp_path / "schemas" / "evaluation_case.schema.json",
    )
    return tmp_path


def _route_registry_to(monkeypatch: pytest.MonkeyPatch, repo: Path) -> None:
    def routed(contract_id, contract_version, *, purpose="read"):
        return real_load_schema(
            contract_id, contract_version, purpose=purpose, repo_root=repo
        )

    monkeypatch.setattr(cases_module, "load_schema", routed)


def test_registry_called_with_exact_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = []
    real = cases_module.load_schema

    def spy(contract_id, contract_version, *, purpose="read"):
        calls.append((contract_id, contract_version, purpose))
        return real(contract_id, contract_version, purpose=purpose)

    monkeypatch.setattr(cases_module, "load_schema", spy)
    load_tmp(tmp_path, base_payload())
    assert calls == [("evaluation_case", "0.1.0", "read")]


def test_missing_schema_file_propagates_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _tmp_schema_repo(tmp_path / "repo")
    (repo / "schemas" / "evaluation_case.schema.json").unlink()
    _route_registry_to(monkeypatch, repo)
    write_case(tmp_path, base_payload())
    with pytest.raises(SchemaFileMissingError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert not isinstance(excinfo.value, CaseLoadError)


def test_schema_hash_mismatch_propagates_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _tmp_schema_repo(tmp_path / "repo")
    target = repo / "schemas" / "evaluation_case.schema.json"
    tampered = json.loads(target.read_text(encoding="utf-8"))
    tampered["properties"]["injected"] = {"type": "string"}
    target.write_text(json.dumps(tampered), encoding="utf-8")
    _route_registry_to(monkeypatch, repo)
    write_case(tmp_path, base_payload())
    with pytest.raises(SchemaHashMismatchError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert not isinstance(excinfo.value, CaseLoadError)


def test_phase0_schema_version_manifest_not_consulted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _tmp_schema_repo(tmp_path / "repo")
    assert not (repo / "schemas" / "schema_version_manifest.json").exists()
    _route_registry_to(monkeypatch, repo)
    write_case(tmp_path, base_payload())
    assert isinstance(load_case("case.json", eval_root=tmp_path), EvaluationCase)


def test_missing_datetime_checker_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cases_module, "FormatChecker", lambda: SimpleNamespace(checkers={})
    )
    write_case(tmp_path, base_payload())
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert excinfo.value.validator_keyword == "format"
    assert "failing closed" in str(excinfo.value)


def test_schema_error_does_not_contain_complete_document(tmp_path: Path) -> None:
    payload = base_payload(zzz_unknown_property="SYNTH-MARKER-VALUE")
    write_case(tmp_path, payload)
    with pytest.raises(CaseSchemaValidationError) as excinfo:
        load_case("case.json", eval_root=tmp_path)
    assert json.dumps(payload) not in str(excinfo.value)
    assert "SYNTH-MARKER-VALUE" not in str(excinfo.value)


# --- Public exports and import behavior ----------------------------------

PUBLIC_SLICE_2_EXCEPTIONS = (
    "CaseLoadError",
    "InvalidEvaluationRootError",
    "CasePathEscapeError",
    "CaseArtifactNotFoundError",
    "CaseArtifactNotAFileError",
    "CaseReadError",
    "CaseDecodeError",
    "CaseJsonError",
    "CaseTopLevelTypeError",
    "ProhibitedLegacyFieldError",
    "CaseSchemaValidationError",
    "CaseModelValidationError",
)


def test_load_case_exported() -> None:
    assert "load_case" in evaluation_pkg.__all__
    assert evaluation_pkg.load_case is load_case


def test_public_exceptions_exported() -> None:
    for name in PUBLIC_SLICE_2_EXCEPTIONS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(cases_module, name)


def test_package_all_parity_exact() -> None:
    public = {
        name
        for name in dir(evaluation_pkg)
        if not name.startswith("_")
        and not inspect.ismodule(getattr(evaluation_pkg, name))
    }
    assert set(evaluation_pkg.__all__) == public


def test_private_helpers_and_control_exceptions_not_exported() -> None:
    private = (
        "_json_pointer",
        "_DuplicateKeyControl",
        "_NonFiniteControl",
        "_reject_duplicate_keys",
        "_validate_eval_root",
        "_resolve_contained_case_path",
    )
    for name in private:
        assert name not in evaluation_pkg.__all__
        assert not hasattr(evaluation_pkg, name)


def test_package_import_no_filesystem_read_or_contract_hash() -> None:
    # Third-party lazy machinery (pydantic plugin discovery on first model
    # creation, jsonschema lazy validator import) is warmed BEFORE the spies
    # so only our package's own behavior is measured; the read filter then
    # proves no schema/case JSON is read and no contract hash is computed.
    code = (
        "import sys\n"
        "sys.path.insert(0, 'src')\n"
        "import hashlib\n"
        "from jsonschema import Draft202012Validator, FormatChecker\n"
        "import pydantic\n"
        "import dynamic_ai_products\n"
        "import dynamic_ai_products.universe.models\n"
        "import dynamic_ai_products.universe.io_utils\n"
        "from pathlib import Path\n"
        "reads = []\n"
        "orig_rb, orig_rt = Path.read_bytes, Path.read_text\n"
        "Path.read_bytes = lambda self, *a, **k: "
        "(reads.append(str(self)), orig_rb(self, *a, **k))[1]\n"
        "Path.read_text = lambda self, *a, **k: "
        "(reads.append(str(self)), orig_rt(self, *a, **k))[1]\n"
        "sha_calls = []\n"
        "orig_sha = hashlib.sha256\n"
        "hashlib.sha256 = lambda *a, **k: (sha_calls.append(1), orig_sha(*a, **k))[1]\n"
        "import dynamic_ai_products.evaluation\n"
        "Path.read_bytes, Path.read_text = orig_rb, orig_rt\n"
        "hashlib.sha256 = orig_sha\n"
        "bad = [p for p in reads if p.endswith('.json') "
        "or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad, bad\n"
        "assert not sha_calls, 'sha256 called during package import'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
