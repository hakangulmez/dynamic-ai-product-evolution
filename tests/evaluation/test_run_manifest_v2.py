"""Slice 12B: evaluation-run manifest v0.2 (ADR-025).

Proves the v0.2 model, its governed pins and timestamp contract, the v0.2
initializer/loader round-trip, strict version routing (v0.1 historical reader
and v0.2 reader never fall back to one another), and that the historical v0.1
identity `7f8909d8...` is preserved unchanged. Tests exercise the public
boundaries, not private helpers.
"""

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import runs as runs_module
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.models import (
    EvaluationRunManifest,
    EvaluationRunManifestV2,
)
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import (
    InitializedEvaluationRun,
    LoadedEvaluationRunManifest,
    RunManifestConsistencyError,
    RunManifestModelValidationError,
    RunManifestUnsupportedVersionError,
    initialize_evaluation_run,
    initialize_evaluation_run_v2,
    load_evaluation_run_manifest,
    load_evaluation_run_manifest_v2,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.evaluation.stage_profiles import (
    StageProfileBindingError,
    load_stage_profile_registry,
    resolve_metric_applicability,
    stage_profile_registry_hash,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "evals" / "fixtures" / "evaluation_harness" / "configs"
CS = ROOT / "evals" / "fixtures" / "evaluation_harness" / "case_sets"
SPR_REL = "evals/fixtures/evaluation_harness/stage_profiles/stage_profile_registry.json"

SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=CFG)
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=CFG)
CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=CS)
SPR = load_stage_profile_registry(SPR_REL, eval_root=ROOT)

V1_HASH = "7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee"
V2_HASH = "6918e96c0f9d2066e89eaf6a699c00b36e1e52e5b5c74ec0e926533eacaf84d6"
H = "a" * 64
EXTRACTION_STAGE = "capability_extraction"
UNIVERSE_STAGE = "universe_screen"

_SEMANTIC_PINS = {
    "semantic_adapter_registry_version": "0.1.0",
    "semantic_adapter_registry_hash": H,
    "selected_semantic_adapter_entry_hash": H,
    "source_passage_snapshot_version": "0.1.0",
    "source_passage_snapshot_hash": H,
    "gold_assertion_set_version": "0.1.0",
    "gold_assertion_set_hash": H,
    "axis_taxonomy_version": "0.1.0",
    "axis_taxonomy_hash": H,
    "validator_rule_parameters_version": "0.1.0",
    "validator_rule_parameters_hash": H,
}


def v2_init(tmp_path, run_id="v2-run-0001", *, stage=EXTRACTION_STAGE, source_root=CFG, **over):
    kwargs = {
        "eval_root": tmp_path,
        "eval_run_id": run_id,
        "prediction_run_id": "synth-pred-run-1",
        "prediction_run_manifest_hash": H,
        "case_set": CASE_SET,
        "registry": REGISTRY,
        "validator_bundle_version": "synth-bundle-v1",
        "validator_bundle_hash": "b" * 64,
        "scoring_config": SCORING,
        "code_commit": "synth-commit-deadbeef",
        "config_snapshot_source_root": source_root,
        "evaluation_created_at": "2026-07-23T12:00:00Z",
        "evaluation_stage": stage,
        "stage_profile_registry": SPR,
        **_SEMANTIC_PINS,
    }
    if stage == UNIVERSE_STAGE:
        kwargs["stage_metric_evidence_set_version"] = "0.1.0"
        kwargs["stage_metric_evidence_set_hash"] = H
    kwargs.update(over)
    return initialize_evaluation_run_v2(**kwargs)


def v1_init(tmp_path, run_id="v1-run-0001", *, source_root=CFG, **over):
    kwargs = {
        "eval_root": tmp_path,
        "eval_run_id": run_id,
        "prediction_run_id": "synth-pred-run-1",
        "prediction_run_manifest_hash": H,
        "case_set": CASE_SET,
        "registry": REGISTRY,
        "validator_bundle_version": "synth-bundle-v1",
        "validator_bundle_hash": "b" * 64,
        "scoring_config": SCORING,
        "code_commit": "synth-commit-deadbeef",
        "config_snapshot_source_root": source_root,
    }
    kwargs.update(over)
    return initialize_evaluation_run(**kwargs)


def v2_doc(*, evidence=False, **over):
    doc = {
        "contract": {
            "contract_id": "evaluation_run_manifest",
            "contract_version": "0.2.0",
            "contract_hash": V2_HASH,
        },
        "eval_run_id": "r",
        "prediction_run_id": "p",
        "prediction_run_manifest_hash": H,
        "case_set_version": "v",
        "case_set_hash": H,
        "registry_snapshot_hash": H,
        "validator_bundle_version": "vb",
        "validator_bundle_hash": H,
        "scoring_gate_config_version": "sc",
        "scoring_gate_config_hash": H,
        "code_commit": "commit",
        "pydantic_runtime_version": "2.13.4",
        "evaluation_created_at": "2026-07-23T12:00:00Z",
        "stage_profile_registry_version": "0.1.0",
        "stage_profile_registry_hash": H,
        "selected_stage_profile_entry_hash": H,
        **_SEMANTIC_PINS,
    }
    if evidence:
        doc["stage_metric_evidence_set_version"] = "0.1.0"
        doc["stage_metric_evidence_set_hash"] = H
    doc.update(over)
    return doc


def _write_manifest(tmp_path, content, run_id):
    run_dir = tmp_path / run_id
    run_dir.mkdir(exist_ok=True)
    path = run_dir / "evaluation_run_manifest.json"
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_text(json.dumps(content), encoding="utf-8")


# --- Historical v0.1 preservation -----------------------------------------


def test_v1_generated_hash_and_governed_constant_agree():
    assert model_contract_hash(EvaluationRunManifest, "evaluation_run_manifest", "0.1.0") == V1_HASH
    assert runs_module._EVALUATION_RUN_MANIFEST_V1_CONTRACT_HASH == V1_HASH


def test_v1_initializer_still_produces_v1(tmp_path):
    r = v1_init(tmp_path)
    assert isinstance(r.manifest, EvaluationRunManifest)
    assert r.manifest.contract.contract_version == "0.1.0"
    assert r.manifest.contract.contract_hash == V1_HASH


def test_v1_loader_accepts_v1_only_and_rejects_v2(tmp_path):
    v1_init(tmp_path, run_id="v1")
    loaded = load_evaluation_run_manifest("v1", eval_root=tmp_path)
    assert isinstance(loaded.manifest, EvaluationRunManifest)
    v2_init(tmp_path, run_id="v2")
    with pytest.raises(RunManifestUnsupportedVersionError) as ei:
        load_evaluation_run_manifest("v2", eval_root=tmp_path)
    assert ei.value.observed_version == "0.2.0" and ei.value.expected_version == "0.1.0"


def test_v1_canonical_bytes_and_newline_stable(tmp_path):
    v1_init(tmp_path, run_id="v1")
    raw = (tmp_path / "v1" / "evaluation_run_manifest.json").read_bytes()
    assert not raw.endswith(b"\n") and not raw.startswith(b"\xef\xbb\xbf")
    parsed = json.loads(raw)
    assert raw.decode() == json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert "evaluation_created_at" not in parsed


def _valid_v1_dict():
    return {
        "contract": {
            "contract_id": "evaluation_run_manifest",
            "contract_version": "0.1.0",
            "contract_hash": V1_HASH,
        },
        "eval_run_id": "r", "prediction_run_id": "p", "prediction_run_manifest_hash": H,
        "case_set_version": "v", "case_set_hash": H, "registry_snapshot_hash": H,
        "validator_bundle_version": "vb", "validator_bundle_hash": H,
        "scoring_gate_config_version": "sc", "scoring_gate_config_hash": H,
        "code_commit": "commit", "pydantic_runtime_version": "2.13.4",
    }


V2_ONLY_FIELDS = (
    "evaluation_created_at",
    "stage_profile_registry_version",
    "stage_profile_registry_hash",
    "selected_stage_profile_entry_hash",
    "semantic_adapter_registry_version",
    "semantic_adapter_registry_hash",
    "selected_semantic_adapter_entry_hash",
    "source_passage_snapshot_version",
    "source_passage_snapshot_hash",
    "gold_assertion_set_version",
    "gold_assertion_set_hash",
    "axis_taxonomy_version",
    "axis_taxonomy_hash",
    "validator_rule_parameters_version",
    "validator_rule_parameters_hash",
    "stage_metric_evidence_set_version",
    "stage_metric_evidence_set_hash",
)


def test_v1_rejects_every_v2_only_field(tmp_path):
    # Every v0.2-only property is rejected by the frozen extra-forbid v0.1 model.
    assert len(V2_ONLY_FIELDS) == 17
    for field in V2_ONLY_FIELDS:
        d = _valid_v1_dict()
        d[field] = "x"
        with pytest.raises(PydanticValidationError):
            EvaluationRunManifest.model_validate(d)


def test_v1_document_not_rewritten_by_load(tmp_path):
    v1_init(tmp_path, run_id="v1")
    path = tmp_path / "v1" / "evaluation_run_manifest.json"
    before = path.read_bytes()
    load_evaluation_run_manifest("v1", eval_root=tmp_path)
    assert path.read_bytes() == before


def test_wrappers_preserve_concrete_v1_class(tmp_path):
    r = v1_init(tmp_path, run_id="v1")
    assert type(r.manifest) is EvaluationRunManifest
    assert type(load_evaluation_run_manifest("v1", eval_root=tmp_path).manifest) is EvaluationRunManifest


# --- V0.2 model -----------------------------------------------------------


def test_v2_strict_frozen_extra_forbid():
    m = EvaluationRunManifestV2.model_validate(v2_doc())
    with pytest.raises(PydanticValidationError):
        m.eval_run_id = "x"
    with pytest.raises(PydanticValidationError):
        EvaluationRunManifestV2.model_validate({**v2_doc(), "zzz": 1})


def test_v2_contract_identity_and_locked_hash():
    m = EvaluationRunManifestV2.model_validate(v2_doc())
    assert m.contract.contract_id == "evaluation_run_manifest"
    assert m.contract.contract_version == "0.2.0"
    assert m.contract.contract_hash == V2_HASH
    assert model_contract_hash(EvaluationRunManifestV2, "evaluation_run_manifest", "0.2.0") == V2_HASH


def test_v2_all_required_pins_present():
    doc = v2_doc()
    required = [
        "eval_run_id", "prediction_run_id", "prediction_run_manifest_hash",
        "case_set_version", "case_set_hash", "registry_snapshot_hash",
        "validator_bundle_version", "validator_bundle_hash",
        "scoring_gate_config_version", "scoring_gate_config_hash",
        "code_commit", "pydantic_runtime_version", "evaluation_created_at",
        "stage_profile_registry_version", "stage_profile_registry_hash",
        "selected_stage_profile_entry_hash", "semantic_adapter_registry_version",
        "semantic_adapter_registry_hash", "selected_semantic_adapter_entry_hash",
        "source_passage_snapshot_version", "source_passage_snapshot_hash",
        "gold_assertion_set_version", "gold_assertion_set_hash",
        "axis_taxonomy_version", "axis_taxonomy_hash",
        "validator_rule_parameters_version", "validator_rule_parameters_hash",
    ]
    for field in required:
        d = copy.deepcopy(doc)
        del d[field]
        with pytest.raises(PydanticValidationError):
            EvaluationRunManifestV2.model_validate(d)


def test_v2_wrong_stamp_and_extra_pin_rejected():
    with pytest.raises(PydanticValidationError):
        EvaluationRunManifestV2.model_validate(v2_doc(contract={
            "contract_id": "evaluation_run_manifest", "contract_version": "0.2.0",
            "contract_hash": "0" * 64}))
    with pytest.raises(PydanticValidationError):
        EvaluationRunManifestV2.model_validate({**v2_doc(), "unexpected_pin": H})


def test_v2_registry_snapshot_hash_not_overloaded():
    # target-registry pin is a distinct field, separate from the semantic pins.
    m = EvaluationRunManifestV2.model_validate(v2_doc(registry_snapshot_hash="d" * 64))
    assert m.registry_snapshot_hash == "d" * 64
    assert m.stage_profile_registry_hash == H and m.source_passage_snapshot_hash == H


@pytest.mark.parametrize("field", [
    "prediction_run_manifest_hash", "case_set_hash", "registry_snapshot_hash",
    "validator_bundle_hash", "scoring_gate_config_hash", "stage_profile_registry_hash",
    "selected_stage_profile_entry_hash", "semantic_adapter_registry_hash",
    "selected_semantic_adapter_entry_hash", "source_passage_snapshot_hash",
    "gold_assertion_set_hash", "axis_taxonomy_hash", "validator_rule_parameters_hash",
])
def test_v2_hash_fields_lowercase_64_hex(field):
    for bad in ("A" * 64, "a" * 63, "a" * 65, "g" * 64, ""):
        with pytest.raises(PydanticValidationError):
            EvaluationRunManifestV2.model_validate(v2_doc(**{field: bad}))


@pytest.mark.parametrize("field", [
    "eval_run_id", "prediction_run_id", "case_set_version", "validator_bundle_version",
    "scoring_gate_config_version", "code_commit", "pydantic_runtime_version",
    "stage_profile_registry_version", "semantic_adapter_registry_version",
    "source_passage_snapshot_version", "gold_assertion_set_version",
    "axis_taxonomy_version", "validator_rule_parameters_version",
])
def test_v2_identity_strings_reject_blank_and_edge_whitespace(field):
    for bad in ("", "   ", " x", "x ", "\tx"):
        with pytest.raises(PydanticValidationError):
            EvaluationRunManifestV2.model_validate(v2_doc(**{field: bad}))
    # an internal space is legal and unnormalized
    m = EvaluationRunManifestV2.model_validate(v2_doc(**{field: "a b"}))
    assert getattr(m, field) == "a b"


def test_v2_stage_evidence_paired_presence():
    EvaluationRunManifestV2.model_validate(v2_doc())  # both absent OK
    EvaluationRunManifestV2.model_validate(v2_doc(evidence=True))  # both present OK
    for one_sided in (
        {"stage_metric_evidence_set_version": "0.1.0"},
        {"stage_metric_evidence_set_hash": H},
    ):
        with pytest.raises(PydanticValidationError):
            EvaluationRunManifestV2.model_validate({**v2_doc(), **one_sided})


def test_v2_stage_evidence_explicit_null_rejected():
    for null_pins in (
        {"stage_metric_evidence_set_version": None, "stage_metric_evidence_set_hash": None},
        {"stage_metric_evidence_set_version": None},
        {"stage_metric_evidence_set_hash": None},
    ):
        with pytest.raises(PydanticValidationError):
            EvaluationRunManifestV2.model_validate({**v2_doc(), **null_pins})


def test_v2_stage_evidence_omission_in_fields_set_and_dump():
    m = EvaluationRunManifestV2.model_validate(v2_doc())
    assert "stage_metric_evidence_set_version" not in m.model_fields_set
    assert "stage_metric_evidence_set_hash" not in m.model_fields_set
    dumped = m.model_dump(mode="json", exclude_unset=True)
    assert "stage_metric_evidence_set_version" not in dumped
    assert "stage_metric_evidence_set_hash" not in dumped
    present = EvaluationRunManifestV2.model_validate(v2_doc(evidence=True))
    d = present.model_dump(mode="json", exclude_unset=True)
    assert d["stage_metric_evidence_set_version"] == "0.1.0" and d["stage_metric_evidence_set_hash"] == H


def test_v2_stage_evidence_present_hash_must_be_hex():
    with pytest.raises(PydanticValidationError):
        EvaluationRunManifestV2.model_validate(
            {**v2_doc(), "stage_metric_evidence_set_version": "0.1.0",
             "stage_metric_evidence_set_hash": "NOThex"})
    with pytest.raises(PydanticValidationError):
        EvaluationRunManifestV2.model_validate(
            {**v2_doc(), "stage_metric_evidence_set_version": " ",
             "stage_metric_evidence_set_hash": H})


# --- Timestamp ------------------------------------------------------------


@pytest.mark.parametrize("stamp", [
    "2026-07-23T12:00:00Z",
    "2026-07-23T12:00:00z",
    "2026-07-23T12:00:00+00:00",
    "2026-07-23T12:00:00-05:00",
    "2026-07-23T12:00:00+02:30",
    "2026-07-23T12:00:00.123456+00:00",
    "2026-07-23t12:00:00Z",
])
def test_v2_timestamp_accepts_and_round_trips_exactly(stamp):
    m = EvaluationRunManifestV2.model_validate(v2_doc(evaluation_created_at=stamp))
    assert m.evaluation_created_at == stamp  # exact accepted representation, unnormalized
    assert m.model_dump(mode="json", exclude_unset=True)["evaluation_created_at"] == stamp


@pytest.mark.parametrize("stamp", [
    "2026-07-23T12:00:00",       # naive (no offset)
    "2026-07-23",                # date only
    "2026-07-23 12:00:00+00:00",  # space separator
    "2026-13-01T00:00:00Z",      # bad month
    "not-a-timestamp",
    "",
    "   ",
    " 2026-07-23T12:00:00Z",     # leading whitespace
    "2026-07-23T12:00:00Z ",     # trailing whitespace
])
def test_v2_timestamp_rejects_invalid(stamp):
    with pytest.raises(PydanticValidationError):
        EvaluationRunManifestV2.model_validate(v2_doc(evaluation_created_at=stamp))


@pytest.mark.parametrize("stamp", [
    "20260723T120000+00:00",         # basic ISO (no separators)
    "2026-W30-4T12:00:00+00:00",     # ISO week date
    "2026-07-23T12:00+00:00",        # reduced precision (no seconds)
    "2026-07-23T12:00:00+00:00:30",  # offset carrying seconds
    "2026-200T12:00:00Z",            # ISO ordinal date
    "2026-07-23T12:00:00.5+00:00:00.5",  # fractional offset
])
def test_v2_timestamp_rejects_non_extended_rfc3339(stamp):
    with pytest.raises(PydanticValidationError):
        EvaluationRunManifestV2.model_validate(v2_doc(evaluation_created_at=stamp))


def test_v2_timestamp_non_string_rejected():
    for bad in (123, 20260723, ["2026-07-23T12:00:00Z"]):
        with pytest.raises(PydanticValidationError):
            EvaluationRunManifestV2.model_validate(v2_doc(evaluation_created_at=bad))


def test_v2_timestamp_z_not_normalized_to_offset():
    m = EvaluationRunManifestV2.model_validate(v2_doc(evaluation_created_at="2026-07-23T12:00:00Z"))
    assert m.evaluation_created_at == "2026-07-23T12:00:00Z"
    assert "+00:00" not in m.evaluation_created_at


# --- Initialization and loading -------------------------------------------


def test_v2_extraction_stage_omits_evidence(tmp_path):
    r = v2_init(tmp_path, stage=EXTRACTION_STAGE)
    assert isinstance(r.manifest, EvaluationRunManifestV2)
    assert "stage_metric_evidence_set_version" not in r.manifest.model_fields_set
    parsed = json.loads((tmp_path / "v2-run-0001" / "evaluation_run_manifest.json").read_text())
    assert "stage_metric_evidence_set_version" not in parsed
    assert "stage_metric_evidence_set_hash" not in parsed


def test_v2_universe_stage_requires_evidence(tmp_path):
    v2_init(tmp_path, stage=UNIVERSE_STAGE)
    parsed = json.loads((tmp_path / "v2-run-0001" / "evaluation_run_manifest.json").read_text())
    assert parsed["stage_metric_evidence_set_version"] == "0.1.0"
    assert parsed["stage_metric_evidence_set_hash"] == H


def test_v2_universe_without_evidence_rejected_before_directory(tmp_path):
    with pytest.raises(RunManifestModelValidationError):
        v2_init(tmp_path, run_id="bad", stage=UNIVERSE_STAGE,
                stage_metric_evidence_set_version=None, stage_metric_evidence_set_hash=None)
    assert not (tmp_path / "bad").exists()


def test_v2_extraction_with_evidence_rejected_before_directory(tmp_path):
    with pytest.raises(RunManifestModelValidationError):
        v2_init(tmp_path, run_id="bad", stage=EXTRACTION_STAGE,
                stage_metric_evidence_set_version="0.1.0", stage_metric_evidence_set_hash=H)
    assert not (tmp_path / "bad").exists()


def test_v2_unknown_stage_fails_closed_before_directory(tmp_path):
    with pytest.raises(StageProfileBindingError) as ei:
        v2_init(tmp_path, run_id="bad", stage="does_not_exist")
    assert ei.value.reason_code == "unknown_evaluation_stage"
    assert not (tmp_path / "bad").exists()


def test_v2_unsupported_stage_fails_closed_before_directory(tmp_path):
    with pytest.raises(StageProfileBindingError) as ei:
        v2_init(tmp_path, run_id="bad", stage="product_extraction")
    assert ei.value.reason_code == "unsupported_evaluation_stage"
    assert not (tmp_path / "bad").exists()


def test_v2_tampered_registry_fails_before_filesystem_mutation(tmp_path):
    # Build a validator-bypassed loaded wrapper (model_construct) around a
    # validator-bypassed (model_copy) nested registry whose registry_version no
    # longer equals the governed contract version, then drive it through the
    # real production initializer. Slice 12A's governed resolution boundary must
    # fail closed before any run directory is created.
    tampered_registry = SPR.registry.model_copy(update={"registry_version": "9.9.9"})
    bad_loaded = SPR.__class__.model_construct(
        registry=tampered_registry,
        version="9.9.9",
        sha256=SPR.sha256,
        artifact_reference=SPR.artifact_reference,
    )
    with pytest.raises(StageProfileBindingError) as ei:
        v2_init(tmp_path, run_id="bad", stage_profile_registry=bad_loaded)
    assert ei.value.reason_code == "inconsistent_profile_binding"
    assert not (tmp_path / "bad").exists()


def test_v2_stage_profile_pins_match_slice_12a_public_apis(tmp_path):
    r = v2_init(tmp_path, stage=EXTRACTION_STAGE)
    m = r.manifest
    assert m.stage_profile_registry_version == SPR.registry.registry_version
    assert m.stage_profile_registry_hash == stage_profile_registry_hash(SPR.registry)
    entry = resolve_metric_applicability(SPR.registry, EXTRACTION_STAGE)
    assert m.selected_stage_profile_entry_hash == entry.entry_hash


def test_v2_config_snapshot_bytes_exact(tmp_path):
    v2_init(tmp_path)
    written = (tmp_path / "v2-run-0001" / "snapshots" / "scoring_gate_config.json").read_bytes()
    assert written == (CFG / "valid_scoring_gate_config.json").read_bytes()


def test_v2_manifest_canonical_with_exactly_one_terminal_lf(tmp_path):
    r = v2_init(tmp_path)
    raw = (tmp_path / "v2-run-0001" / "evaluation_run_manifest.json").read_bytes()
    assert raw.endswith(b"\n")
    assert not raw.endswith(b"\n\n")
    assert not raw.startswith(b"\xef\xbb\xbf")
    parsed = json.loads(raw[:-1])
    assert raw[:-1].decode() == json.dumps(
        parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    # both the initialization and loader hashes bind the complete raw bytes
    # including the terminal LF.
    assert r.manifest_sha256 == sha256_bytes(raw)
    loaded = load_evaluation_run_manifest_v2("v2-run-0001", eval_root=tmp_path)
    assert loaded.sha256 == sha256_bytes(raw)


def test_v2_created_at_round_trips_through_persistence(tmp_path):
    r = v2_init(tmp_path, evaluation_created_at="2026-07-23T09:15:30-04:00")
    assert r.manifest.evaluation_created_at == "2026-07-23T09:15:30-04:00"
    reloaded = load_evaluation_run_manifest_v2("v2-run-0001", eval_root=tmp_path)
    assert reloaded.manifest.evaluation_created_at == "2026-07-23T09:15:30-04:00"


def test_v2_repeated_loads_deterministic(tmp_path):
    v2_init(tmp_path)
    a = load_evaluation_run_manifest_v2("v2-run-0001", eval_root=tmp_path)
    b = load_evaluation_run_manifest_v2("v2-run-0001", eval_root=tmp_path)
    assert a == b and a is not b


def test_v2_loaded_wrapper_binds_raw_sha_and_concrete_model(tmp_path):
    r = v2_init(tmp_path)
    loaded = load_evaluation_run_manifest_v2("v2-run-0001", eval_root=tmp_path)
    assert isinstance(loaded, LoadedEvaluationRunManifest)
    assert type(loaded.manifest) is EvaluationRunManifestV2
    assert loaded.sha256 == r.manifest_sha256
    assert loaded.artifact_reference == "v2-run-0001/evaluation_run_manifest.json"


def test_v2_returned_init_wrapper_holds_v2(tmp_path):
    r = v2_init(tmp_path)
    assert isinstance(r, InitializedEvaluationRun)
    assert type(r.manifest) is EvaluationRunManifestV2


def test_v2_loader_rejects_v1(tmp_path):
    v1_init(tmp_path, run_id="v1")
    with pytest.raises(RunManifestUnsupportedVersionError) as ei:
        load_evaluation_run_manifest_v2("v1", eval_root=tmp_path)
    assert ei.value.observed_version == "0.1.0" and ei.value.expected_version == "0.2.0"


def test_v2_loader_run_id_mismatch(tmp_path):
    d = v2_doc(eval_run_id="different")
    _write_manifest(tmp_path, d, "v2-run-0001")
    with pytest.raises(RunManifestConsistencyError) as ei:
        load_evaluation_run_manifest_v2("v2-run-0001", eval_root=tmp_path)
    assert ei.value.consistency_kind == "manifest_run_id_mismatch"


def test_v2_loader_wrong_id_and_hash_rejected(tmp_path):
    bad_id = v2_doc(eval_run_id="v2r", contract={
        "contract_id": "wrong", "contract_version": "0.2.0", "contract_hash": V2_HASH})
    _write_manifest(tmp_path, bad_id, "v2r")
    with pytest.raises(RunManifestModelValidationError):
        load_evaluation_run_manifest_v2("v2r", eval_root=tmp_path)
    bad_hash = v2_doc(eval_run_id="v2r2", contract={
        "contract_id": "evaluation_run_manifest", "contract_version": "0.2.0",
        "contract_hash": "0" * 64})
    _write_manifest(tmp_path, bad_hash, "v2r2")
    with pytest.raises(RunManifestModelValidationError):
        load_evaluation_run_manifest_v2("v2r2", eval_root=tmp_path)


def test_v2_loader_duplicate_key(tmp_path):
    _write_manifest(tmp_path, '{"eval_run_id": "a", "eval_run_id": "b"}', "v2-run-0001")
    with pytest.raises(runs_module.RunJsonError) as ei:
        load_evaluation_run_manifest_v2("v2-run-0001", eval_root=tmp_path)
    assert ei.value.duplicate_key == "eval_run_id"


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_v2_loader_non_finite(tmp_path, literal):
    _write_manifest(tmp_path, '{"x": ' + literal + "}", "v2-run-0001")
    with pytest.raises(runs_module.RunJsonError):
        load_evaluation_run_manifest_v2("v2-run-0001", eval_root=tmp_path)


def test_v2_loader_malformed_and_top_level(tmp_path):
    _write_manifest(tmp_path, "{not json", "r1")
    with pytest.raises(runs_module.RunJsonError):
        load_evaluation_run_manifest_v2("r1", eval_root=tmp_path)
    _write_manifest(tmp_path, "[1,2]", "r2")
    with pytest.raises(runs_module.RunTopLevelTypeError):
        load_evaluation_run_manifest_v2("r2", eval_root=tmp_path)


def test_v2_loader_missing_nonfile_symlink(tmp_path):
    with pytest.raises(runs_module.RunArtifactNotFoundError):
        load_evaluation_run_manifest_v2("nope", eval_root=tmp_path)
    (tmp_path / "d" / "evaluation_run_manifest.json").mkdir(parents=True)
    with pytest.raises(runs_module.RunArtifactNotAFileError):
        load_evaluation_run_manifest_v2("d", eval_root=tmp_path)
    real = tmp_path / "real"
    real.mkdir()
    _write_manifest(real, v2_doc(eval_run_id="real"), ".")
    (real / "evaluation_run_manifest.json").write_text(json.dumps(v2_doc(eval_run_id="lnk")))
    (tmp_path / "lnk").symlink_to(real, target_is_directory=True)
    with pytest.raises(runs_module.RunArtifactNotAFileError):
        load_evaluation_run_manifest_v2("lnk", eval_root=tmp_path)


def test_v2_source_missing_and_hash_mismatch_no_directory(tmp_path):
    empty = tmp_path / "src2"
    empty.mkdir()
    with pytest.raises(runs_module.SnapshotSourceMissingError):
        v2_init(tmp_path, run_id="bad2", source_root=empty)
    assert not (tmp_path / "bad2").exists()
    tampered = tmp_path / "src3"
    tampered.mkdir()
    (tampered / SCORING.artifact_reference).write_text("tampered")
    with pytest.raises(runs_module.SnapshotHashMismatchError):
        v2_init(tmp_path, run_id="bad3", source_root=tampered)
    assert not (tmp_path / "bad3").exists()


def test_v2_destination_collision(tmp_path):
    v2_init(tmp_path, run_id="dup")
    with pytest.raises(runs_module.RunDirectoryExistsError):
        v2_init(tmp_path, run_id="dup")


def test_v2_serialization_failure_no_directory(tmp_path, monkeypatch):
    def boom(self, **kwargs):
        raise ValueError("synthetic serialization failure")

    monkeypatch.setattr(EvaluationRunManifestV2, "model_dump", boom)
    with pytest.raises(runs_module.RunManifestSerializationError):
        v2_init(tmp_path, run_id="bad")
    assert not (tmp_path / "bad").exists()


def test_v2_write_and_readback_mismatch(tmp_path, monkeypatch):
    real_open = runs_module.os.open

    def boom(path, flags, mode=0o777):
        if str(path).endswith("evaluation_run_manifest.json"):
            raise OSError("synthetic write failure")
        return real_open(path, flags, mode)

    monkeypatch.setattr(runs_module.os, "open", boom)
    with pytest.raises(runs_module.RunWriteError):
        v2_init(tmp_path, run_id="w")
    assert not (tmp_path / "w" / "evaluation_run_manifest.json").exists()
    monkeypatch.undo()
    real_read = Path.read_bytes

    def tamper(self):
        if self.name == "evaluation_run_manifest.json":
            return b"tampered"
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", tamper)
    with pytest.raises(runs_module.RunDestinationHashMismatchError) as ei:
        v2_init(tmp_path, run_id="w2")
    assert ei.value.consistency_kind == "manifest_destination_hash_mismatch"


def test_v2_type_validation(tmp_path):
    with pytest.raises(TypeError):
        v2_init(tmp_path, stage_profile_registry=object())


# --- Surface and hygiene --------------------------------------------------

THREE_NEW = ("EvaluationRunManifestV2", "initialize_evaluation_run_v2", "load_evaluation_run_manifest_v2")


def test_three_new_exports_present_and_surface_clean():
    # The three Slice 12B exports are present and package __all__ stays sorted
    # and unique. The global export count is a current review result, not a
    # frozen literal every later slice must rewrite, so it is not pinned here.
    for name in THREE_NEW:
        assert name in evaluation_pkg.__all__
        assert hasattr(evaluation_pkg, name)
    al = list(evaluation_pkg.__all__)
    assert al == sorted(al) and len(al) == len(set(al))
    # no public v2 wrapper class leaked into the package surface
    assert "InitializedEvaluationRunV2" not in al and "LoadedEvaluationRunManifestV2" not in al
    assert not hasattr(evaluation_pkg, "InitializedEvaluationRunV2")
    assert not hasattr(evaluation_pkg, "LoadedEvaluationRunManifestV2")
    # the governed private v0.1 hash constant is not exported
    assert "_EVALUATION_RUN_MANIFEST_V1_CONTRACT_HASH" not in al
    assert not hasattr(evaluation_pkg, "_EVALUATION_RUN_MANIFEST_V1_CONTRACT_HASH")
    assert "RunManifestUnsupportedVersionError" not in al


def test_no_existing_export_removed():
    for name in ("EvaluationRunManifest", "InitializedEvaluationRun", "LoadedEvaluationRunManifest",
                 "initialize_evaluation_run", "load_evaluation_run_manifest"):
        assert name in evaluation_pkg.__all__


def test_manifest_declared_total_matches_entry_count_and_lists_new_path():
    # Durable invariant: the declared manifest total equals the number of listed
    # path entries (parity), rather than a frozen literal that goes stale as
    # later slices add entries. The Slice 12B test path appears exactly once.
    text = (ROOT / "REPO_MANIFEST.md").read_text(encoding="utf-8")
    match = re.search(r"Total tracked/scaffold files listed: \*\*(\d+)\*\*", text)
    assert match is not None
    declared_total = int(match.group(1))
    entries = re.findall(r"^- `([^`]+)`$", text, flags=re.MULTILINE)
    assert declared_total == len(entries)
    assert entries.count("tests/evaluation/test_run_manifest_v2.py") == 1


def test_no_static_schema_added_and_schema_manifest_unchanged():
    # Evaluation-v2 meaning preserved: run manifest v0.2 still adds no static
    # schema file. Only the global schema-version-manifest baseline is
    # rebaselined (latest: ADR-078, 0.24.0 -> 0.25.0, registering
    # edgar_index_acquisition_manifest_v2, the sec_live successor manifest
    # for the post-W0 live binding; before it ADR-076, 0.23.0 -> 0.24.0,
    # registering edgar_index_acquisition_manifest for the fixture-replay
    # index acquisition; before it ADR-075, 0.22.0 -> 0.23.0, registering
    # filer_frame_manifest for the FRAME builder; before it ADR-071,
    # 0.20.0 -> 0.21.0, the decision-set successor carrying the task kind and
    # the Snapshot B pin; before it ADR-057 added the first decision-set
    # successor).
    assert not (ROOT / "schemas" / "evaluation_run_manifest.v2.schema.json").exists()
    got = sha256_bytes((ROOT / "schemas" / "schema_version_manifest.json").read_bytes())
    assert got == "b7058f2340f827f41a7684b2849cb7f821cefb24660be43ba82403d493a27bed"


def test_protected_identities_unchanged():
    from dynamic_ai_products.evaluation import comparator as cm
    from dynamic_ai_products.evaluation.stage_profiles import StageProfileRegistry
    assert model_contract_hash(EvaluationRunManifest, "evaluation_run_manifest", "0.1.0") == V1_HASH
    assert model_contract_hash(cm.ComparisonManifest, "comparison_manifest", "0.2.0") \
        == "6a1253b72664bff73e872d1230fb3d52772a438f55915406010e105b4f5d29a5"
    assert model_contract_hash(StageProfileRegistry, "evaluation_stage_profile_registry", "0.1.0") \
        == "cbd567cb0367cabe5f680957a8da29d9018ccd50512c91e0f9c393de2c7ee4dd"
    assert stage_profile_registry_hash(SPR.registry) \
        == "242cf65210b1a176f15c2162342f5ddb84f5018ed5a4cb91423d5aef2a18a777"


def test_import_no_io_no_hash_no_clock():
    code = "\n".join([
        "import sys, os, hashlib, importlib, time",
        "sys.path.insert(0, 'src')",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.models, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation",
        "for m in ('dynamic_ai_products.evaluation.models','dynamic_ai_products.evaluation.runs'):",
        "    sys.modules.pop(m, None)",
        "from pathlib import Path",
        "reads=[]; writes=[]; sha=[]; clock=[]",
        "orb,ort,omk,oop,osha=Path.read_bytes,Path.read_text,Path.mkdir,os.open,hashlib.sha256",
        "ot1,ot2=time.time,time.monotonic",
        "Path.read_bytes=lambda self,*a,**k:(reads.append(str(self)),orb(self,*a,**k))[1]",
        "Path.read_text=lambda self,*a,**k:(reads.append(str(self)),ort(self,*a,**k))[1]",
        "Path.mkdir=lambda self,*a,**k:(writes.append(str(self)),omk(self,*a,**k))[1]",
        "os.open=lambda *a,**k:(writes.append('o'),oop(*a,**k))[1]",
        "hashlib.sha256=lambda *a,**k:(sha.append(1),osha(*a,**k))[1]",
        "time.time=lambda *a,**k:(clock.append(1),ot1())[1]",
        "time.monotonic=lambda *a,**k:(clock.append(1),ot2())[1]",
        "importlib.import_module('dynamic_ai_products.evaluation.models')",
        "importlib.import_module('dynamic_ai_products.evaluation.runs')",
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open,hashlib.sha256=orb,ort,omk,oop,osha",
        "time.time,time.monotonic=ot1,ot2",
        "assert reads==[], ('READS',reads)",
        "assert writes==[], ('WRITES',writes)",
        "assert sha==[], ('SHA',len(sha))",
        "assert clock==[], ('CLOCK',len(clock))",
        "print('OK')",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr
