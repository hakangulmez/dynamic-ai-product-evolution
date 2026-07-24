"""Slice 8: append-only finding dispositions and derived coverage state.

Dispositions are appended beside immutable validator findings under an
initialized Slice 5 run directory. No disposition alters, filters or
re-severities a finding, and none produces a status, verdict or gate effect;
only the two derivable coverage states (open, dispositioned) are exposed.
"""

import subprocess
import sys
from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import dispositions as disp_mod
from dynamic_ai_products.evaluation import validators as val_mod
from dynamic_ai_products.evaluation.cases import InvalidEvaluationRootError
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.dispositions import (
    AppendedFindingDispositions,
    DerivedDispositionState,
    DispositionArtifactMissingError,
    DispositionArtifactNotAFileError,
    DispositionConcurrentModificationError,
    DispositionDecodeError,
    DispositionError,
    DispositionJsonError,
    DispositionModelValidationError,
    DispositionPreviousHashMismatchError,
    DispositionTopLevelTypeError,
    DispositionWriteError,
    DuplicateDispositionIdError,
    EMPTY_DISPOSITION_LOG_SHA256,
    EmptyDispositionAppendError,
    InvalidExpectedPreviousHashError,
    LoadedFindingDispositions,
    ProhibitedCriticalRiskAcceptanceError,
    UnknownFindingReferenceError,
    append_finding_dispositions,
    derive_disposition_states,
    load_finding_dispositions,
)
from dynamic_ai_products.evaluation.models import EvaluationRunManifestV2, FindingDisposition
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import (
    RunArtifactNotAFileError,
    initialize_evaluation_run,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.evaluation.validator_parameters import (
    complete_rule_parameter_hash,
    load_validator_rule_parameters,
    validator_rule_parameters_aggregate_hash,
)
from dynamic_ai_products.evaluation.validators import (
    VALIDATOR_RULE_ORDER,
    ValidationArtifactSnapshot,
    ValidatorBundle,
    ValidatorRuleConfig,
    evaluate_validator_findings,
    persist_validator_findings,
    validator_bundle_hash,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"

SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FX / "case_sets")

HEX = "a" * 64
CREATED_AT = "2026-07-20T00:00:00Z"
PSHA = "d" * 64
V2_HASH = "6918e96c0f9d2066e89eaf6a699c00b36e1e52e5b5c74ec0e926533eacaf84d6"
PARAMS = load_validator_rule_parameters(
    "validator_parameters/validator_rule_parameters.json", eval_root=FX
)
AGG = validator_rule_parameters_aggregate_hash(PARAMS.model)
ENTRIES = {e.rule_id: e for e in PARAMS.model.entries}
DISP_META = {
    "contract_id": "finding_disposition", "contract_version": "0.1.0",
    "contract_hash": model_contract_hash(FindingDisposition, "finding_disposition", "0.1.0"),
}


def _v2_manifest(run_id, bundle):
    doc = {
        "contract": {"contract_id": "evaluation_run_manifest", "contract_version": "0.2.0",
                     "contract_hash": V2_HASH},
        "eval_run_id": run_id, "prediction_run_id": "p", "prediction_run_manifest_hash": HEX,
        "case_set_version": "v", "case_set_hash": HEX, "registry_snapshot_hash": HEX,
        "validator_bundle_version": bundle.bundle_version,
        "validator_bundle_hash": validator_bundle_hash(bundle),
        "scoring_gate_config_version": "sc", "scoring_gate_config_hash": HEX,
        "code_commit": "commit", "pydantic_runtime_version": "2.13.4",
        "evaluation_created_at": "2026-07-23T12:00:00Z",
        "stage_profile_registry_version": "0.1.0", "stage_profile_registry_hash": HEX,
        "selected_stage_profile_entry_hash": HEX,
        "semantic_adapter_registry_version": "0.1.0", "semantic_adapter_registry_hash": HEX,
        "selected_semantic_adapter_entry_hash": HEX,
        "source_passage_snapshot_version": "0.1.0", "source_passage_snapshot_hash": HEX,
        "gold_assertion_set_version": "0.1.0", "gold_assertion_set_hash": HEX,
        "axis_taxonomy_version": "0.1.0", "axis_taxonomy_hash": HEX,
        "validator_rule_parameters_version": PARAMS.version,
        "validator_rule_parameters_hash": AGG,
    }
    return EvaluationRunManifestV2.model_validate(doc)


def _full_coverage():
    return [
        {"rule_id": rid, "coverage_state": "fully_evaluated", "candidate_count": 1,
         "evaluated_observation_count": 1, "blocked_candidate_count": 0, "reason_counts": []}
        for rid in VALIDATOR_RULE_ORDER
    ]

ALL_DISPOSITION_TYPES = (
    "confirmed_defect", "suspected_validator_false_positive",
    "confirmed_validator_false_positive", "source_snapshot_defect",
    "prediction_artifact_defect", "gold_or_case_defect", "policy_or_rule_mismatch",
    "accepted_nonblocking_risk", "duplicate_finding", "needs_investigation",
)


def _bundle(*, critical_first=False):
    rules = []
    for i, rid in enumerate(VALIDATOR_RULE_ORDER):
        sev = "critical" if (critical_first and i == 0) else "error"
        rules.append(
            ValidatorRuleConfig(
                rule_id=rid, severity=sev,
                rule_params_hash=complete_rule_parameter_hash(ENTRIES[rid]), repairable=False,
            )
        )
    return ValidatorBundle(bundle_version="vb-1", rules=tuple(rules))


def _passing_observations():
    return {
        "output_json_schema_validity": {
            "rule_id": "output_json_schema_validity", "observation_id": "o1",
            "parse_succeeded": True, "schema_valid": True, "schema_reference": "s.json",
            "validation_errors": (),
        },
        "required_field_presence": {
            "rule_id": "required_field_presence", "observation_id": "o2",
            "required_fields": ("a",), "present_fields": ("a",),
        },
        "source_id_resolution": {
            "rule_id": "source_id_resolution", "observation_id": "o3",
            "referenced_source_ids": ("s1",), "available_source_ids": ("s1",),
        },
        "passage_id_resolution": {
            "rule_id": "passage_id_resolution", "observation_id": "o4",
            "referenced_passage_ids": ("p1",), "available_passage_ids": ("p1",),
        },
        "evidence_quote_containment": {
            "rule_id": "evidence_quote_containment", "observation_id": "o5",
            "quote": "x", "passage_text": "axb", "passage_id": "p1",
        },
        "publication_date_cutoff": {
            "rule_id": "publication_date_cutoff", "observation_id": "o6",
            "publication_date": "2020-01-01", "observation_cutoff_date": "2020-06-01",
            "source_id": "s1",
        },
        "product_capability_task_parent_resolution": {
            "rule_id": "product_capability_task_parent_resolution", "observation_id": "o7",
            "child_id": "c1", "parent_id": "pp", "available_parent_ids": ("pp",),
        },
        "unique_ids_within_scope": {
            "rule_id": "unique_ids_within_scope", "observation_id": "o8",
            "scope_id": "sc", "record_ids": ("a", "b"),
        },
        "prohibited_legacy_fields_absent": {
            "rule_id": "prohibited_legacy_fields_absent", "observation_id": "o9",
            "present_field_names": ("x",), "prohibited_field_names": ("legacy",),
        },
        "active_record_non_roadmap_evidence": {
            "rule_id": "active_record_non_roadmap_evidence", "observation_id": "o10",
            "active": True, "evidence": ({"evidence_id": "e1", "is_future_roadmap": False},),
        },
        "customer_task_outcome_and_evidence": {
            "rule_id": "customer_task_outcome_and_evidence", "observation_id": "o11",
            "is_customer_facing_task": True, "customer_outcome": "did x", "evidence_ids": ("e1",),
        },
        "raw_output_and_repair_preservation": {
            "rule_id": "raw_output_and_repair_preservation", "observation_id": "o12",
            "raw_output_reference": "raw.json", "raw_artifact_sha256": "c" * 64,
            "raw_output_preserved": True, "repair_applied": False,
            "repair_record_references": (), "repair_record_hashes": (),
            "parsed_content_sha256": PSHA,
        },
    }


def _snapshot(*, failing, run_id="run1"):
    base = _passing_observations()
    fail_overrides = {
        "source_id_resolution": {"referenced_source_ids": ("missing",), "available_source_ids": ()},
        "unique_ids_within_scope": {"record_ids": ("a", "a")},
        "output_json_schema_validity": {"parse_succeeded": False, "schema_valid": False},
    }
    for rid in failing:
        base[rid] = {**base[rid], **fail_overrides[rid]}
    return ValidationArtifactSnapshot.model_validate({
        "eval_run_id": run_id, "artifact_id": "art-1", "stage": "capability_extraction",
        "artifact_sha256": "b" * 64, "parsed_prediction_content_sha256": PSHA,
        "created_at": CREATED_AT, "case_id": "SYNTH-CASE-0001",
        "observations": [base[r] for r in VALIDATOR_RULE_ORDER],
        "coverage": _full_coverage(),
    })


def init_run(eval_root, run_id="run1", *, critical_first=False):
    b = _bundle(critical_first=critical_first)
    initialize_evaluation_run(
        eval_root=eval_root, eval_run_id=run_id, prediction_run_id="P",
        prediction_run_manifest_hash="a" * 64, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb-1", validator_bundle_hash=validator_bundle_hash(b),
        scoring_config=SCORING, code_commit="c", config_snapshot_source_root=FX / "configs",
    )
    return b


def seed_findings(eval_root, run_id="run1", *, failing=("source_id_resolution",), critical_first=False):
    """Initialize a run, evaluate, and persist findings; return the findings.

    The on-disk run directory remains the committed v0.1 initialization (findings
    persistence and disposition tests bind to that run-directory layout); the
    coverage-aware evaluation uses an in-memory ``EvaluationRunManifestV2`` whose
    bundle and parameter pins match the reconciled bundle and loaded parameters.
    """
    b = init_run(eval_root, run_id, critical_first=critical_first)
    manifest = _v2_manifest(run_id, b)
    ev = evaluate_validator_findings(
        _snapshot(failing=failing, run_id=run_id), bundle=b, run_manifest=manifest,
        rule_parameters=PARAMS,
    )
    persist_validator_findings(ev.findings, eval_root=eval_root, eval_run_id=run_id)
    return ev.findings


def disp(did, finding_id, disposition="confirmed_defect"):
    return FindingDisposition.model_validate({
        "contract": DISP_META, "disposition_id": did, "finding_id": finding_id,
        "disposition": disposition, "reviewer": "r", "timestamp": CREATED_AT,
        "rationale": "because", "linked_evidence": (), "proposed_resolution_path": "path",
    })


# --- First and later appends ----------------------------------------------


def test_first_append_then_later_append(tmp_path):
    findings = seed_findings(tmp_path)
    fid = findings[0].finding_id
    r1 = append_finding_dispositions(
        (disp("d1", fid),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    assert isinstance(r1, AppendedFindingDispositions)
    assert r1.artifact_reference == "run1/dispositions/finding_dispositions.jsonl"
    assert r1.previous_sha256 == EMPTY_DISPOSITION_LOG_SHA256
    assert r1.appended_count == 1
    r2 = append_finding_dispositions(
        (disp("d2", fid, "needs_investigation"),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=r1.sha256,
    )
    assert r2.previous_sha256 == r1.sha256
    loaded = load_finding_dispositions("run1", eval_root=tmp_path)
    assert isinstance(loaded, LoadedFindingDispositions)
    assert [d.disposition_id for d in loaded.dispositions] == ["d1", "d2"]
    assert loaded.sha256 == r2.sha256


def test_first_append_expects_empty_hash_constant():
    assert EMPTY_DISPOSITION_LOG_SHA256 == sha256_bytes(b"")


@pytest.mark.parametrize("disposition_type", list(ALL_DISPOSITION_TYPES))
def test_all_ten_disposition_types_accepted(tmp_path, disposition_type):
    # Seed a non-critical finding so accepted_nonblocking_risk is allowed too.
    findings = seed_findings(tmp_path)
    fid = findings[0].finding_id
    assert findings[0].severity != "critical"
    r = append_finding_dispositions(
        (disp("d1", fid, disposition_type),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    assert r.appended_count == 1
    loaded = load_finding_dispositions("run1", eval_root=tmp_path)
    assert loaded.dispositions[0].disposition == disposition_type


# --- Append guards --------------------------------------------------------


def test_empty_append_rejected(tmp_path):
    seed_findings(tmp_path)
    with pytest.raises(EmptyDispositionAppendError):
        append_finding_dispositions(
            (), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )


@pytest.mark.parametrize("bad", ["", "abc", "A" * 64, "g" * 64, "a" * 63])
def test_invalid_expected_previous_hash_rejected(tmp_path, bad):
    findings = seed_findings(tmp_path)
    with pytest.raises(InvalidExpectedPreviousHashError):
        append_finding_dispositions(
            (disp("d1", findings[0].finding_id),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=bad,
        )


def test_previous_hash_mismatch_rejected(tmp_path):
    findings = seed_findings(tmp_path)
    with pytest.raises(DispositionPreviousHashMismatchError):
        append_finding_dispositions(
            (disp("d1", findings[0].finding_id),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256="b" * 64,
        )


def test_second_append_with_stale_hash_rejected(tmp_path):
    findings = seed_findings(tmp_path)
    fid = findings[0].finding_id
    append_finding_dispositions(
        (disp("d1", fid),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    # Reusing the empty hash after the first append must fail.
    with pytest.raises(DispositionPreviousHashMismatchError):
        append_finding_dispositions(
            (disp("d2", fid),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )


def test_existing_bytes_preserved_as_exact_prefix(tmp_path):
    findings = seed_findings(tmp_path)
    fid = findings[0].finding_id
    dest = tmp_path / "run1" / "dispositions" / "finding_dispositions.jsonl"
    r1 = append_finding_dispositions(
        (disp("d1", fid),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    first_bytes = dest.read_bytes()
    append_finding_dispositions(
        (disp("d2", fid),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=r1.sha256,
    )
    final_bytes = dest.read_bytes()
    assert final_bytes.startswith(first_bytes)


def test_duplicate_disposition_id_within_batch(tmp_path):
    findings = seed_findings(tmp_path)
    fid = findings[0].finding_id
    with pytest.raises(DuplicateDispositionIdError):
        append_finding_dispositions(
            (disp("d1", fid), disp("d1", fid, "needs_investigation")),
            eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )


def test_duplicate_disposition_id_against_existing(tmp_path):
    findings = seed_findings(tmp_path)
    fid = findings[0].finding_id
    r1 = append_finding_dispositions(
        (disp("d1", fid),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    with pytest.raises(DuplicateDispositionIdError):
        append_finding_dispositions(
            (disp("d1", fid, "needs_investigation"),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=r1.sha256,
        )


def test_unknown_finding_reference_rejected(tmp_path):
    seed_findings(tmp_path)
    with pytest.raises(UnknownFindingReferenceError):
        append_finding_dispositions(
            (disp("d1", "f" * 64),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )


def test_critical_accepted_nonblocking_risk_rejected(tmp_path):
    findings = seed_findings(tmp_path, failing=("output_json_schema_validity",), critical_first=True)
    critical = [f for f in findings if f.severity == "critical"]
    assert critical
    with pytest.raises(ProhibitedCriticalRiskAcceptanceError) as exc:
        append_finding_dispositions(
            (disp("d1", critical[0].finding_id, "accepted_nonblocking_risk"),),
            eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )
    assert exc.value.severity == "critical"


def test_noncritical_accepted_nonblocking_risk_stored_without_gate_effect(tmp_path):
    findings = seed_findings(tmp_path)  # severity "error"
    fid = findings[0].finding_id
    append_finding_dispositions(
        (disp("d1", fid, "accepted_nonblocking_risk"),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    # The finding bytes are unchanged: dispositions never rewrite findings.
    fdest = tmp_path / "run1" / "findings" / "validator_findings.jsonl"
    reloaded = val_mod.load_validator_findings("run1", eval_root=tmp_path)
    assert reloaded.findings[0].severity == "error"
    assert reloaded.findings[0].finding_id == fid
    # No status/verdict artifact was produced by the disposition append.
    assert not (tmp_path / "run1" / "evaluation_result.json").exists()
    assert fdest.is_file()


def test_findings_unchanged_byte_for_byte_after_appends(tmp_path):
    findings = seed_findings(tmp_path)
    fid = findings[0].finding_id
    fdest = tmp_path / "run1" / "findings" / "validator_findings.jsonl"
    before = fdest.read_bytes()
    r1 = append_finding_dispositions(
        (disp("d1", fid),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    append_finding_dispositions(
        (disp("d2", fid, "needs_investigation"),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=r1.sha256,
    )
    assert fdest.read_bytes() == before


# --- Path / collision behavior --------------------------------------------


def test_append_requires_existing_findings(tmp_path):
    init_run(tmp_path)  # no findings persisted
    with pytest.raises(val_mod.ValidatorArtifactMissingError):
        append_finding_dispositions(
            (disp("d1", "a" * 64),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )


def test_append_rejects_symlinked_dispositions_dir(tmp_path):
    findings = seed_findings(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "run1" / "dispositions").symlink_to(outside)
    with pytest.raises(DispositionArtifactNotAFileError):
        append_finding_dispositions(
            (disp("d1", findings[0].finding_id),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )


def test_append_rejects_dangling_symlink(tmp_path):
    findings = seed_findings(tmp_path)
    (tmp_path / "run1" / "dispositions").symlink_to(tmp_path / "nope")
    with pytest.raises(DispositionArtifactNotAFileError):
        append_finding_dispositions(
            (disp("d1", findings[0].finding_id),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )


def test_append_rejects_file_where_directory_expected(tmp_path):
    findings = seed_findings(tmp_path)
    (tmp_path / "run1" / "dispositions").write_bytes(b"occupied")
    with pytest.raises(DispositionArtifactNotAFileError):
        append_finding_dispositions(
            (disp("d1", findings[0].finding_id),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )


def test_forced_append_failure_preserves_directory(tmp_path, monkeypatch):
    findings = seed_findings(tmp_path)
    fid = findings[0].finding_id
    real_open = disp_mod.os.open

    def boom(path, flags, *a, **k):
        if str(path).endswith("finding_dispositions.jsonl"):
            raise OSError("synthetic append failure")
        return real_open(path, flags, *a, **k)

    monkeypatch.setattr(disp_mod.os, "open", boom)
    with pytest.raises(DispositionWriteError):
        append_finding_dispositions(
            (disp("d1", fid),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
        )
    monkeypatch.undo()
    d = tmp_path / "run1" / "dispositions"
    assert d.is_dir()
    assert not (d / "finding_dispositions.jsonl").exists()


def test_post_write_concurrent_modification_detected(tmp_path, monkeypatch):
    findings = seed_findings(tmp_path)
    fid = findings[0].finding_id
    # Establish a non-empty prior state so the "no longer begins with the
    # verified previous bytes" branch is the one exercised.
    r1 = append_finding_dispositions(
        (disp("d1", fid),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    real_read = disp_mod.Path.read_bytes
    dest_name = "finding_dispositions.jsonl"
    dest_reads = {"count": 0}

    def tampering_read(self):
        if self.name == dest_name:
            dest_reads["count"] += 1
            # The first dest read is the pre-append classify; the second is
            # the post-write verification re-read. Replace the artifact
            # entirely just before that second read returns, so the final
            # bytes no longer start with the verified previous bytes.
            if dest_reads["count"] == 2:
                self.write_bytes(b"WHOLLY-REPLACED\n")
        return real_read(self)

    monkeypatch.setattr(disp_mod.Path, "read_bytes", tampering_read)
    with pytest.raises(DispositionConcurrentModificationError):
        append_finding_dispositions(
            (disp("d2", fid, "needs_investigation"),), eval_root=tmp_path, eval_run_id="run1",
            expected_previous_sha256=r1.sha256,
        )


# --- Loader strictness ----------------------------------------------------


def write_disp_dir(tmp_path, data: bytes):
    d = tmp_path / "run1" / "dispositions"
    d.mkdir(parents=True, exist_ok=False)
    (d / "finding_dispositions.jsonl").write_bytes(data)


def disp_line(fid):
    return disp_mod._canonical_disposition_line(disp("d1", fid)) + b"\n"


def test_load_missing(tmp_path):
    seed_findings(tmp_path)
    with pytest.raises(DispositionArtifactMissingError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_load_rejects_non_utf8(tmp_path):
    seed_findings(tmp_path)
    write_disp_dir(tmp_path, b"\xff\xfe")
    with pytest.raises(DispositionDecodeError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_load_rejects_bom(tmp_path):
    findings = seed_findings(tmp_path)
    write_disp_dir(tmp_path, b"\xef\xbb\xbf" + disp_line(findings[0].finding_id))
    with pytest.raises(DispositionJsonError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_load_rejects_blank_line(tmp_path):
    findings = seed_findings(tmp_path)
    line = disp_line(findings[0].finding_id)
    write_disp_dir(tmp_path, line + b"\n")
    with pytest.raises(DispositionJsonError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_load_rejects_duplicate_keys(tmp_path):
    seed_findings(tmp_path)
    write_disp_dir(tmp_path, b'{"a":1,"a":2}\n')
    with pytest.raises(DispositionJsonError) as exc:
        load_finding_dispositions("run1", eval_root=tmp_path)
    assert exc.value.duplicate_key == "a"


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_load_rejects_non_finite(tmp_path, constant):
    seed_findings(tmp_path)
    write_disp_dir(tmp_path, b'{"x":' + constant + b"}\n")
    with pytest.raises(DispositionJsonError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_load_rejects_non_object(tmp_path):
    seed_findings(tmp_path)
    write_disp_dir(tmp_path, b"[1,2]\n")
    with pytest.raises(DispositionTopLevelTypeError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_load_rejects_model_invalid(tmp_path):
    seed_findings(tmp_path)
    write_disp_dir(tmp_path, b'{"unexpected":true}\n')
    with pytest.raises(DispositionModelValidationError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_load_rejects_duplicate_disposition_id(tmp_path):
    findings = seed_findings(tmp_path)
    line = disp_line(findings[0].finding_id)
    write_disp_dir(tmp_path, line + line)
    with pytest.raises(DuplicateDispositionIdError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_dir(tmp_path):
    seed_findings(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "finding_dispositions.jsonl").write_bytes(b"")
    (tmp_path / "run1" / "dispositions").symlink_to(outside)
    with pytest.raises(DispositionArtifactNotAFileError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_run_dir(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    seed_findings(real, "run1")
    (tmp_path / "run1").symlink_to(real / "run1")
    with pytest.raises(RunArtifactNotAFileError):
        load_finding_dispositions("run1", eval_root=tmp_path)


def test_repeated_loads_equal_but_distinct(tmp_path):
    findings = seed_findings(tmp_path)
    append_finding_dispositions(
        (disp("d1", findings[0].finding_id),), eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    a = load_finding_dispositions("run1", eval_root=tmp_path)
    b = load_finding_dispositions("run1", eval_root=tmp_path)
    assert a is not b
    assert a.dispositions[0] is not b.dispositions[0]
    assert [d.model_dump() for d in a.dispositions] == [d.model_dump() for d in b.dispositions]


def test_invalid_eval_root_rejected():
    with pytest.raises(InvalidEvaluationRootError):
        load_finding_dispositions("run1", eval_root="")


# --- Derived state --------------------------------------------------------


def test_derive_states_open_and_dispositioned(tmp_path):
    findings = seed_findings(tmp_path, failing=("source_id_resolution", "unique_ids_within_scope"))
    assert len(findings) == 2
    fid0, fid1 = findings[0].finding_id, findings[1].finding_id
    append_finding_dispositions(
        (disp("d1", fid0), disp("d2", fid0, "needs_investigation")),
        eval_root=tmp_path, eval_run_id="run1",
        expected_previous_sha256=EMPTY_DISPOSITION_LOG_SHA256,
    )
    loaded = load_finding_dispositions("run1", eval_root=tmp_path)
    states = derive_disposition_states(findings, loaded.dispositions)
    assert all(isinstance(s, DerivedDispositionState) for s in states)
    by_id = {s.finding_id: s for s in states}
    assert by_id[fid0].state == "dispositioned"
    assert by_id[fid0].disposition_count == 2
    assert by_id[fid1].state == "open"
    assert by_id[fid1].disposition_count == 0


def test_derive_states_all_open_with_no_dispositions(tmp_path):
    findings = seed_findings(tmp_path)
    states = derive_disposition_states(findings, ())
    assert [s.state for s in states] == ["open"]


def test_derive_states_follows_findings_order(tmp_path):
    findings = seed_findings(tmp_path, failing=("source_id_resolution", "unique_ids_within_scope"))
    states = derive_disposition_states(findings, ())
    assert [s.finding_id for s in states] == [f.finding_id for f in findings]


# --- Exports and import hygiene -------------------------------------------

PUBLIC_FUNCTIONS = (
    "append_finding_dispositions", "load_finding_dispositions", "derive_disposition_states",
)
PUBLIC_MODELS = (
    "LoadedFindingDispositions", "AppendedFindingDispositions", "DerivedDispositionState",
)
PUBLIC_ALIASES = ("DispositionState", "EMPTY_DISPOSITION_LOG_SHA256")
PUBLIC_EXCEPTIONS = (
    "DispositionError", "EmptyDispositionAppendError", "InvalidExpectedPreviousHashError",
    "DispositionPreviousHashMismatchError", "DispositionArtifactMissingError",
    "DispositionArtifactNotAFileError", "DispositionArtifactReadError", "DispositionDecodeError",
    "DispositionJsonError", "DispositionTopLevelTypeError", "DispositionModelValidationError",
    "DuplicateDispositionIdError", "UnknownFindingReferenceError",
    "ProhibitedCriticalRiskAcceptanceError", "DispositionWriteError",
    "DispositionConcurrentModificationError", "DispositionDestinationHashMismatchError",
)


def test_public_symbols_exported():
    for name in PUBLIC_FUNCTIONS + PUBLIC_MODELS + PUBLIC_ALIASES + PUBLIC_EXCEPTIONS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(disp_mod, name)


def test_disposition_state_alias():
    import typing
    assert set(typing.get_args(disp_mod.DispositionState)) == {"open", "dispositioned"}


def test_exception_hierarchy():
    for name in PUBLIC_EXCEPTIONS:
        cls = getattr(disp_mod, name)
        if name == "DispositionError":
            assert cls.__bases__ == (Exception,)
        else:
            assert issubclass(cls, DispositionError)


def test_private_helpers_not_exported():
    for name in ("_canonical_disposition_line", "_parse_dispositions_jsonl", "_classify_existing",
                 "_DuplicateKeyControl", "_serialize_dispositions"):
        assert name not in evaluation_pkg.__all__
        assert not hasattr(evaluation_pkg, name)


def test_finding_disposition_contract_hash_unchanged():
    assert model_contract_hash(FindingDisposition, "finding_disposition", "0.1.0") == (
        "1c08efdbd36682acf535cc688ae5c73e902e1659f30814b6a5bee46b2c9d873e"
    )


def test_package_import_no_io_or_hash():
    code = (
        "import sys, os\nsys.path.insert(0, 'src')\nimport hashlib\n"
        "from jsonschema import Draft202012Validator, FormatChecker\nimport pydantic\n"
        "import dynamic_ai_products, dynamic_ai_products.universe.models, dynamic_ai_products.universe.io_utils\n"
        "from pathlib import Path\nreads=[]; writes=[]\n"
        "orb, ort, omk, oop = Path.read_bytes, Path.read_text, Path.mkdir, os.open\n"
        "Path.read_bytes = lambda self,*a,**k:(reads.append(str(self)),orb(self,*a,**k))[1]\n"
        "Path.read_text = lambda self,*a,**k:(reads.append(str(self)),ort(self,*a,**k))[1]\n"
        "Path.mkdir = lambda self,*a,**k:(writes.append('m'),omk(self,*a,**k))[1]\n"
        "os.open = lambda *a,**k:(writes.append('o'),oop(*a,**k))[1]\n"
        "sha=[]; osha=hashlib.sha256\nhashlib.sha256=lambda *a,**k:(sha.append(1),osha(*a,**k))[1]\n"
        "import dynamic_ai_products.evaluation.dispositions\n"
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open=orb,ort,omk,oop\nhashlib.sha256=osha\n"
        "bad=[p for p in reads if p.endswith('.json') or p.endswith('.jsonl') or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad and not writes and not sha, (bad, writes, len(sha))\nprint('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
