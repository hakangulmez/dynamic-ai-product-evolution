"""Slice 4: scoring/gate configuration loading and validation tests.

The tracked fixture covers the positive stop-point path; failure variants are
generated under ``tmp_path``. No metric, gate, threshold, or verdict is
evaluated here.
"""

import json
from pathlib import Path

import pydantic
import pytest

from dynamic_ai_products.evaluation.cases import InvalidEvaluationRootError
from dynamic_ai_products.evaluation.references import BlockingResolutionError
from dynamic_ai_products.evaluation.scoring_config import (
    LoadedScoringGateConfig,
    ScoringConfigArtifactNotAFileError,
    ScoringConfigDecodeError,
    ScoringConfigJsonError,
    ScoringConfigModelValidationError,
    ScoringConfigPathEscapeError,
    ScoringConfigTopLevelTypeError,
    ScoringGateConfig,
    load_scoring_gate_config,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "evals" / "fixtures" / "evaluation_harness" / "configs"


def gate(**over):
    payload = {
        "reference_id": "synth-gate-1",
        "metric_id": "synth-metric",
        "population_slice_id": "synth-slice",
        "verified_support_requirement": {"synth_min": 10},
        "ci_method_reference": "synth-ci",
        "blocking_severity": "synth-critical",
        "protected_regression_class_references": ["synth-class-a"],
        "slice_definitions": [{"synth_slice": "global"}],
        "threshold": {"synth_max": 0.1},
    }
    payload.update(over)
    return payload


def diagnostic(**over):
    payload = {
        "reference_id": "synth-diag-1",
        "metric_id": "synth-metric",
        "population_slice_id": "synth-slice",
        "slice_definitions": [{"synth_slice": "stratum"}],
    }
    payload.update(over)
    return payload


def config_payload(**over):
    payload = {
        "config_version": "synth-config-v1",
        "blocking_severities": ["synth-critical", "synth-error"],
        "protected_regression_classes": ["synth-class-a", "synth-class-b"],
        "gates": [gate()],
        "diagnostics": [diagnostic()],
    }
    payload.update(over)
    return payload


def write(tmp_path: Path, content, name="config.json") -> str:
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_text(json.dumps(content), encoding="utf-8")
    return name


def load_tmp(tmp_path: Path, content, **kw):
    name = write(tmp_path, content)
    return load_scoring_gate_config(name, eval_root=tmp_path, **kw)


# --- Loader success and binding ------------------------------------------


def test_loads_tracked_fixture() -> None:
    loaded = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FIX)
    assert isinstance(loaded, LoadedScoringGateConfig)
    assert isinstance(loaded.config, ScoringGateConfig)
    assert loaded.version == "synth-scoring-gate-config-v1"
    assert loaded.config.gates[0].reference_id == "synth-scoring-gate-ref-0001"
    assert loaded.config.diagnostics[0].reference_id == "synth-scoring-gate-ref-0002"


def test_frozen_model() -> None:
    loaded = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FIX)
    with pytest.raises(pydantic.ValidationError):
        loaded.config.config_version = "mutated"  # type: ignore[misc]


def test_reloads_equal_but_distinct() -> None:
    a = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FIX)
    b = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FIX)
    assert a == b and a is not b


def test_raw_byte_hash_matches_independent_sha(tmp_path: Path) -> None:
    name = write(tmp_path, config_payload())
    loaded = load_scoring_gate_config(name, eval_root=tmp_path)
    assert loaded.sha256 == sha256_bytes((tmp_path / name).read_bytes())


def test_expected_matching_hash_succeeds() -> None:
    observed = sha256_bytes((FIX / "valid_scoring_gate_config.json").read_bytes())
    loaded = load_scoring_gate_config(
        "valid_scoring_gate_config.json", eval_root=FIX, expected_sha256=observed
    )
    assert loaded.sha256 == observed


def test_absent_expected_hash_returns_binding(tmp_path: Path) -> None:
    loaded = load_tmp(tmp_path, config_payload())
    assert len(loaded.sha256) == 64


def test_explicit_dot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, config_payload())
    monkeypatch.chdir(tmp_path)
    assert isinstance(
        load_scoring_gate_config("config.json", eval_root="."), LoadedScoringGateConfig
    )


# --- Path and strict parsing ---------------------------------------------


def test_omitted_root_typeerror() -> None:
    with pytest.raises(TypeError):
        load_scoring_gate_config("config.json")  # type: ignore[call-arg]


def test_none_root_rejected() -> None:
    with pytest.raises(InvalidEvaluationRootError):
        load_scoring_gate_config("config.json", eval_root=None)  # type: ignore[arg-type]


def test_empty_root_rejected() -> None:
    with pytest.raises(InvalidEvaluationRootError):
        load_scoring_gate_config("config.json", eval_root="")


def test_nonexistent_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidEvaluationRootError):
        load_scoring_gate_config("config.json", eval_root=tmp_path / "missing")


def test_file_root_rejected(tmp_path: Path) -> None:
    write(tmp_path, config_payload(), "not-a-dir.json")
    with pytest.raises(InvalidEvaluationRootError):
        load_scoring_gate_config("config.json", eval_root=tmp_path / "not-a-dir.json")


def test_absolute_contained(tmp_path: Path) -> None:
    write(tmp_path, config_payload())
    assert isinstance(
        load_scoring_gate_config(str(tmp_path / "config.json"), eval_root=tmp_path),
        LoadedScoringGateConfig,
    )


def test_traversal_escape(tmp_path: Path) -> None:
    write(tmp_path, config_payload(), "outside.json")
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ScoringConfigPathEscapeError):
        load_scoring_gate_config("../outside.json", eval_root=root)


def test_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret"
    outside.mkdir()
    write(outside, config_payload(), "c.json")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.json").symlink_to(outside / "c.json")
    with pytest.raises(ScoringConfigPathEscapeError) as excinfo:
        load_scoring_gate_config("link.json", eval_root=root)
    assert "outside-secret" not in str(excinfo.value)


def test_root_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    write(real, config_payload())
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert isinstance(
        load_scoring_gate_config("config.json", eval_root=link), LoadedScoringGateConfig
    )


def test_prefix_confusion(tmp_path: Path) -> None:
    root = tmp_path / "evals"
    root.mkdir()
    sibling = tmp_path / "evals-escape"
    sibling.mkdir()
    write(sibling, config_payload(), "c.json")
    with pytest.raises(ScoringConfigPathEscapeError):
        load_scoring_gate_config(str(sibling / "c.json"), eval_root=root)


def test_missing_config_is_blocking(tmp_path: Path) -> None:
    with pytest.raises(BlockingResolutionError) as excinfo:
        load_scoring_gate_config("missing.json", eval_root=tmp_path)
    assert excinfo.value.failure_kind == "config_artifact_missing"
    assert excinfo.value.rule_id == "slice4.config_artifact_missing"
    assert excinfo.value.artifact_reference == "missing.json"


def test_directory_instead_of_file(tmp_path: Path) -> None:
    (tmp_path / "a-dir").mkdir()
    with pytest.raises(ScoringConfigArtifactNotAFileError):
        load_scoring_gate_config("a-dir", eval_root=tmp_path)


def test_invalid_utf8(tmp_path: Path) -> None:
    write(tmp_path, b"\xff\xfe{}")
    with pytest.raises(ScoringConfigDecodeError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


def test_bom_rejected(tmp_path: Path) -> None:
    write(tmp_path, b"\xef\xbb\xbf" + json.dumps(config_payload()).encode())
    with pytest.raises(ScoringConfigJsonError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


def test_malformed_json(tmp_path: Path) -> None:
    write(tmp_path, "{not json")
    with pytest.raises(ScoringConfigJsonError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


def test_trailing_content(tmp_path: Path) -> None:
    write(tmp_path, json.dumps(config_payload()) + " x")
    with pytest.raises(ScoringConfigJsonError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


def test_duplicate_top_level_key(tmp_path: Path) -> None:
    write(tmp_path, '{"config_version": "a", "config_version": "b"}')
    with pytest.raises(ScoringConfigJsonError) as excinfo:
        load_scoring_gate_config("config.json", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "config_version"


def test_duplicate_nested_key(tmp_path: Path) -> None:
    write(tmp_path, '{"gates": [{"threshold": {"k": 1, "k": 2}}]}')
    with pytest.raises(ScoringConfigJsonError) as excinfo:
        load_scoring_gate_config("config.json", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "k"


@pytest.mark.parametrize("text", ["[1]", '"x"', "null"])
def test_non_object_top_level(tmp_path: Path, text: str) -> None:
    write(tmp_path, text)
    with pytest.raises(ScoringConfigTopLevelTypeError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite_constant(tmp_path: Path, constant: str) -> None:
    write(tmp_path, '{"x": ' + constant + "}")
    with pytest.raises(ScoringConfigJsonError) as excinfo:
        load_scoring_gate_config("config.json", eval_root=tmp_path)
    assert excinfo.value.constant_name == constant


def test_overflow_infinity(tmp_path: Path) -> None:
    write(tmp_path, '{"x": 1e999}')
    with pytest.raises(ScoringConfigJsonError) as excinfo:
        load_scoring_gate_config("config.json", eval_root=tmp_path)
    assert excinfo.value.constant_name == "Infinity"


def test_finite_nested_values_preserved(tmp_path: Path) -> None:
    payload = config_payload(gates=[gate(threshold={"synth_max": 0.25, "n": 3})])
    loaded = load_tmp(tmp_path, payload)
    assert loaded.config.gates[0].threshold == {"synth_max": 0.25, "n": 3}


# --- Expected hashes ------------------------------------------------------


def test_expected_hash_mismatch(tmp_path: Path) -> None:
    name = write(tmp_path, config_payload())
    with pytest.raises(BlockingResolutionError) as excinfo:
        load_scoring_gate_config(name, eval_root=tmp_path, expected_sha256="0" * 64)
    exc = excinfo.value
    assert exc.failure_kind == "snapshot_hash_mismatch"
    assert exc.expected_sha256 == "0" * 64
    assert exc.observed_sha256 and len(exc.observed_sha256) == 64


def test_malformed_expected_hash(tmp_path: Path) -> None:
    name = write(tmp_path, config_payload())
    with pytest.raises(BlockingResolutionError) as excinfo:
        load_scoring_gate_config(name, eval_root=tmp_path, expected_sha256="not-a-hash")
    exc = excinfo.value
    assert exc.failure_kind == "snapshot_hash_mismatch"
    assert exc.expected_sha256 is None
    assert "not-a-hash" not in str(exc)


# --- Contract validation --------------------------------------------------


def test_missing_required_field(tmp_path: Path) -> None:
    payload = config_payload()
    del payload["config_version"]
    write(tmp_path, payload)
    with pytest.raises(ScoringConfigModelValidationError) as excinfo:
        load_scoring_gate_config("config.json", eval_root=tmp_path)
    assert "config_version" in excinfo.value.field_locations


def test_unknown_field(tmp_path: Path) -> None:
    write(tmp_path, config_payload(zzz="x"))
    with pytest.raises(ScoringConfigModelValidationError) as excinfo:
        load_scoring_gate_config("config.json", eval_root=tmp_path)
    assert "extra_forbidden" in excinfo.value.error_types


def test_blank_config_version(tmp_path: Path) -> None:
    write(tmp_path, config_payload(config_version="  "))
    with pytest.raises(ScoringConfigModelValidationError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


def test_empty_threshold_object_rejected(tmp_path: Path) -> None:
    write(tmp_path, config_payload(gates=[gate(threshold={})]))
    with pytest.raises(ScoringConfigModelValidationError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


def test_empty_support_object_rejected(tmp_path: Path) -> None:
    write(tmp_path, config_payload(gates=[gate(verified_support_requirement={})]))
    with pytest.raises(ScoringConfigModelValidationError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


def test_empty_slice_definition_rejected(tmp_path: Path) -> None:
    write(tmp_path, config_payload(gates=[gate(slice_definitions=[{}])]))
    with pytest.raises(ScoringConfigModelValidationError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


def test_diagnostic_cannot_carry_gate_only_field(tmp_path: Path) -> None:
    bad = diagnostic(threshold={"synth_max": 0.1})
    write(tmp_path, config_payload(diagnostics=[bad]))
    with pytest.raises(ScoringConfigModelValidationError) as excinfo:
        load_scoring_gate_config("config.json", eval_root=tmp_path)
    assert "extra_forbidden" in excinfo.value.error_types


def test_gate_missing_required_structural_field(tmp_path: Path) -> None:
    bad = gate()
    del bad["threshold"]
    write(tmp_path, config_payload(gates=[bad]))
    with pytest.raises(ScoringConfigModelValidationError):
        load_scoring_gate_config("config.json", eval_root=tmp_path)


def test_model_error_no_value_leak(tmp_path: Path) -> None:
    write(tmp_path, config_payload(config_version="  "))
    with pytest.raises(ScoringConfigModelValidationError) as excinfo:
        load_scoring_gate_config("config.json", eval_root=tmp_path)
    assert "  " not in " ".join(excinfo.value.field_locations)


# --- Configuration invariants (semantic) ---------------------------------


def expect_blocking(tmp_path: Path, payload, kind):
    write(tmp_path, payload)
    with pytest.raises(BlockingResolutionError) as excinfo:
        load_scoring_gate_config("config.json", eval_root=tmp_path)
    assert excinfo.value.failure_kind == kind
    return excinfo.value


def test_duplicate_gate_reference_id(tmp_path: Path) -> None:
    exc = expect_blocking(
        tmp_path,
        config_payload(gates=[gate(reference_id="g"), gate(reference_id="g")]),
        "duplicate_reference_id",
    )
    assert exc.reference_id == "g"


def test_duplicate_diagnostic_reference_id(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        config_payload(
            diagnostics=[diagnostic(reference_id="d"), diagnostic(reference_id="d")]
        ),
        "duplicate_reference_id",
    )


def test_gate_diagnostic_cross_conflict(tmp_path: Path) -> None:
    exc = expect_blocking(
        tmp_path,
        config_payload(
            gates=[gate(reference_id="shared")],
            diagnostics=[diagnostic(reference_id="shared")],
        ),
        "conflicting_reference_definition",
    )
    assert exc.reference_id == "shared"


def test_duplicate_severity(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        config_payload(blocking_severities=["synth-critical", "synth-critical"]),
        "conflicting_reference_definition",
    )


def test_duplicate_protected_class(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        config_payload(protected_regression_classes=["synth-class-a", "synth-class-a"]),
        "conflicting_reference_definition",
    )


def test_unknown_severity_reference(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        config_payload(gates=[gate(blocking_severity="synth-unknown")]),
        "conflicting_reference_definition",
    )


def test_unknown_protected_class_reference(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        config_payload(
            gates=[gate(protected_regression_class_references=["synth-unknown"])]
        ),
        "conflicting_reference_definition",
    )


def test_duplicate_protected_class_within_gate(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        config_payload(
            gates=[
                gate(protected_regression_class_references=["synth-class-a", "synth-class-a"])
            ]
        ),
        "conflicting_reference_definition",
    )


def test_repeated_metric_id_accepted(tmp_path: Path) -> None:
    payload = config_payload(
        gates=[gate(reference_id="g1", metric_id="m"), gate(reference_id="g2", metric_id="m")]
    )
    loaded = load_tmp(tmp_path, payload)
    assert [g.metric_id for g in loaded.config.gates] == ["m", "m"]


def test_opaque_threshold_preserved(tmp_path: Path) -> None:
    payload = config_payload(
        gates=[gate(threshold={"synth_nested": {"a": [1, 2, 3]}, "flag": True})]
    )
    loaded = load_tmp(tmp_path, payload)
    assert loaded.config.gates[0].threshold == {"synth_nested": {"a": [1, 2, 3]}, "flag": True}
