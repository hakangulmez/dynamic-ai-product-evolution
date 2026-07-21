"""Slice 11: immutable comparison and assertion-transition artifacts.

Pure assessors are exercised with hand-built loaded wrappers (no filesystem);
persistence/loading run under ``tmp_path`` — the comparator validates only the
explicit ``eval_root``, never a source run directory. Comparisons never mutate
a source artifact and never change a Slice 10 verdict.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import comparator as comp
from dynamic_ai_products.evaluation.assertions import LoadedAssertionOutcomes
from dynamic_ai_products.evaluation.comparator import (
    AssertionComparisonMetadata,
    AssertionComparisonMetadataEntry,
    AssertionTransition,
    ComparisonArtifact,
    ComparisonArtifactMissingError,
    ComparisonArtifactNotAFileError,
    ComparisonBindingError,
    ComparisonBindingMismatchError,
    ComparisonDecodeError,
    ComparisonExistsError,
    ComparisonIssue,
    ComparisonJsonError,
    ComparisonMetadataError,
    ComparisonModelValidationError,
    ComparisonRunReference,
    ComparisonTopLevelTypeError,
    ComparisonValidityError,
    ComparisonWriteError,
    LoadedComparison,
    PersistedComparison,
    assess_comparison,
    build_errored_comparison,
    build_invalid_comparison,
    load_comparison,
    persist_comparison,
)
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes, model_contract_hash
from dynamic_ai_products.evaluation.gates import LoadedEvaluationResult
from dynamic_ai_products.evaluation.models import (
    AssertionOutcome,
    EvaluationRunManifest,
    EvaluationResultV2,
)
from dynamic_ai_products.evaluation.runs import LoadedEvaluationRunManifest
from dynamic_ai_products.evaluation.scoring_config import LoadedScoringGateConfig, load_scoring_gate_config
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
SC = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
PROT = "synth-protected-temporal"
PROT2 = "synth-protected-evidence"
CID = "SYNTH-CASE-0001"

RM_STAMP = {"contract_id": "evaluation_run_manifest", "contract_version": "0.1.0",
            "contract_hash": model_contract_hash(EvaluationRunManifest, "evaluation_run_manifest", "0.1.0")}
AO_STAMP = {"contract_id": "assertion_outcome", "contract_version": "0.1.0",
            "contract_hash": model_contract_hash(AssertionOutcome, "assertion_outcome", "0.1.0")}
META_STAMP = {"contract_id": "assertion_comparison_metadata", "contract_version": "0.1.0",
              "contract_hash": model_contract_hash(AssertionComparisonMetadata,
                                                   "assertion_comparison_metadata", "0.1.0")}
H1, H2, H3, H4, H5, H6 = ("1" * 64, "2" * 64, "3" * 64, "4" * 64, "5" * 64, "6" * 64)


# --- Builders (no filesystem) ---------------------------------------------


def manifest(run_id, **ov):
    base = {
        "contract": RM_STAMP, "eval_run_id": run_id, "prediction_run_id": "P",
        "prediction_run_manifest_hash": H1, "case_set_version": "cs-v1", "case_set_hash": H2,
        "registry_snapshot_hash": H3, "validator_bundle_version": "vb", "validator_bundle_hash": H4,
        "scoring_gate_config_version": "cfg-v1", "scoring_gate_config_hash": H5,
        "code_commit": "commit-1", "pydantic_runtime_version": "2.9",
    }
    base.update(ov)
    return EvaluationRunManifest.model_validate(base)


def loaded_manifest(run_id, *, sha=H6, **ov):
    return LoadedEvaluationRunManifest(
        manifest=manifest(run_id, **ov), sha256=sha,
        artifact_reference=f"{run_id}/evaluation_run_manifest.json")


def loaded_result(m, *, status="completed", verdict="pass", sha=None, dataset=None,
                  metric_sha=("a" * 64), stage="task_extraction", metrics=None, exclude_unset=True):
    dataset = m.case_set_version if dataset is None else dataset
    if metrics is None:
        metrics = {"provenance": {
            "case_set_version": m.case_set_version, "case_set_hash": m.case_set_hash,
            "scoring_gate_config_version": m.scoring_gate_config_version,
            "scoring_gate_config_hash": m.scoring_gate_config_hash,
            "metric_report_sha256": metric_sha},
            "gate_outcomes": [], "critical_finding_ids": []}
    payload = {"eval_run_id": m.eval_run_id, "stage": stage, "dataset_version": dataset,
               "metrics": metrics, "execution_status": status}
    if verdict is not None:
        payload["gate_verdict"] = verdict
    res = EvaluationResultV2.model_validate(payload)
    return LoadedEvaluationResult(eval_run_id=m.eval_run_id,
                                  artifact_reference="results/evaluation_result.json",
                                  sha256=sha or ("b" * 64), result=res)


def loaded_scoring(m, *, sha=None):
    cfg = SC.config.model_copy(update={"config_version": m.scoring_gate_config_version})
    return LoadedScoringGateConfig(config=cfg, version=m.scoring_gate_config_version,
                                   sha256=sha or m.scoring_gate_config_hash, artifact_reference="x")


def outcome(run_id, case_id, assertion_id, value, *, semver="1.0.0", chash=None):
    payload = {"contract": AO_STAMP, "eval_run_id": run_id, "case_id": case_id,
               "assertion_id": assertion_id, "outcome": value}
    if semver is not None:
        payload["assertion_semantic_version"] = semver
    if chash is not None:
        payload["assertion_contract_hash"] = chash
    return AssertionOutcome.model_validate(payload)


def loaded_outcomes(run_id, *outcomes, sha=None):
    return LoadedAssertionOutcomes(eval_run_id=run_id,
                                   artifact_reference=f"{run_id}/assertions/assertion_outcomes.jsonl",
                                   sha256=sha or ("c" * 64), outcomes=tuple(outcomes))


def meta_entry(case_id, assertion_id, *, semver="1.0.0", chash=None, protected=()):
    return AssertionComparisonMetadataEntry(
        case_id=case_id, assertion_id=assertion_id, assertion_semantic_version=semver,
        assertion_contract_hash=chash, protected_regression_classes=tuple(sorted(protected)))


def metadata(run_id, *entries, mapping="0.1.0", taxonomy="0.1.0"):
    ordered = tuple(sorted(entries, key=lambda e: (e.case_id, e.assertion_id)))
    return AssertionComparisonMetadata(contract=META_STAMP, eval_run_id=run_id,
                                       mapping_version=mapping, failure_taxonomy_version=taxonomy,
                                       entries=ordered)


def assess(*, cid="cmp-1", role="previous_candidate", commit="cc-1", b_manifest=None,
           c_manifest=None, b_result=None, c_result=None, b_outcomes, c_outcomes,
           b_scoring=None, c_scoring=None, b_metadata, c_metadata):
    bm = b_manifest or loaded_manifest("run-base")
    cm = c_manifest or loaded_manifest("run-cand")
    return assess_comparison(
        comparison_id=cid, baseline_role=role, comparison_code_commit=commit,
        baseline_manifest=bm, candidate_manifest=cm,
        baseline_result=b_result or loaded_result(bm.manifest),
        candidate_result=c_result or loaded_result(cm.manifest),
        baseline_outcomes=b_outcomes, candidate_outcomes=c_outcomes,
        baseline_scoring_config=b_scoring or loaded_scoring(bm.manifest),
        candidate_scoring_config=c_scoring or loaded_scoring(cm.manifest),
        baseline_metadata=b_metadata, candidate_metadata=c_metadata)


def one_assertion(b_value, c_value, *, protected=(), b_semver="1.0.0", c_semver="1.0.0",
                  b_chash=None, c_chash=None, b_protected=None, c_protected=None,
                  b_manifest=None, c_manifest=None, **kw):
    bp = protected if b_protected is None else b_protected
    cp = protected if c_protected is None else c_protected
    return assess(
        b_manifest=b_manifest, c_manifest=c_manifest,
        b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", b_value,
                                                        semver=b_semver, chash=b_chash)),
        c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", c_value,
                                                       semver=c_semver, chash=c_chash)),
        b_metadata=metadata("run-base", meta_entry(CID, "A1", semver=b_semver, chash=b_chash,
                                                   protected=bp)),
        c_metadata=metadata("run-cand", meta_entry(CID, "A1", semver=c_semver, chash=c_chash,
                                                   protected=cp)),
        **kw)


def t0(art):
    return art.transitions[0]


# --- Vocabularies & simple models -----------------------------------------


def test_vocabularies_exact():
    import typing
    assert set(typing.get_args(comp.BaselineRole)) == {
        "current_frozen_prompt", "accepted_release", "previous_candidate",
        "model_upgrade_baseline", "validator_bridge_baseline", "reproducibility_baseline"}
    assert set(typing.get_args(comp.ComparableTransitionClass)) == {
        "unchanged", "regression", "improvement", "coverage_or_certainty_degradation"}
    assert set(typing.get_args(comp.NoncomparabilityClass)) == {
        "changed_assertion_contract", "changed_gold", "changed_input_packet",
        "changed_validator_contract", "added_assertion", "removed_assertion", "noncomparable_contract"}
    assert set(typing.get_args(comp.CaseLedgerClass)) == {
        "newly_failing", "newly_passing", "degraded_but_still_passing", "degraded_and_still_failing",
        "improved_but_still_failing", "unchanged_passing", "unchanged_failing", "indeterminate",
        "noncomparable", "added_case", "removed_case", "additional_protected_regression"}


def test_models_strict_frozen_extra_forbid():
    e = meta_entry(CID, "A1")
    with pytest.raises(Exception):
        e.case_id = "x"  # frozen
    with pytest.raises(Exception):
        AssertionComparisonMetadataEntry(case_id="c", assertion_id="a",
                                         protected_regression_classes=(), extra="no")  # extra forbid


def test_metadata_entry_identity_presence_required():
    with pytest.raises(Exception):
        AssertionComparisonMetadataEntry(case_id="c", assertion_id="a", semver=None,
                                         protected_regression_classes=())
    with pytest.raises(Exception):
        AssertionComparisonMetadataEntry(case_id="c", assertion_id="a",
                                         assertion_semantic_version=None,
                                         assertion_contract_hash=None,
                                         protected_regression_classes=())


def test_metadata_entry_protected_sorted_unique():
    with pytest.raises(Exception):  # unsorted
        AssertionComparisonMetadataEntry(case_id="c", assertion_id="a",
                                         assertion_semantic_version="1",
                                         protected_regression_classes=("b", "a"))
    with pytest.raises(Exception):  # duplicate
        AssertionComparisonMetadataEntry(case_id="c", assertion_id="a",
                                         assertion_semantic_version="1",
                                         protected_regression_classes=("x", "x"))


def test_metadata_entries_sorted_unique():
    with pytest.raises(Exception):
        metadata("run", meta_entry("b", "a"), meta_entry("a", "a")).model_validate({
            "contract": META_STAMP, "eval_run_id": "run", "mapping_version": "0.1.0",
            "failure_taxonomy_version": "0.1.0",
            "entries": [meta_entry("b", "a").model_dump(), meta_entry("a", "a").model_dump()]})
    with pytest.raises(Exception):
        AssertionComparisonMetadata.model_validate({
            "contract": META_STAMP, "eval_run_id": "run", "mapping_version": "0.1.0",
            "failure_taxonomy_version": "0.1.0",
            "entries": [meta_entry("a", "a").model_dump(), meta_entry("a", "a").model_dump()]})


def test_run_reference_partial_and_hash_validation():
    ref = ComparisonRunReference(eval_run_id="run-x")
    assert not ref.is_complete
    with pytest.raises(Exception):
        ComparisonRunReference(eval_run_id="run-x", run_manifest_sha256="not-hex")
    with pytest.raises(Exception):  # completed status needs verdict
        ComparisonRunReference(eval_run_id="run-x", execution_status="completed")
    with pytest.raises(Exception):  # invalid status forbids verdict
        ComparisonRunReference(eval_run_id="run-x", execution_status="invalid", gate_verdict="fail")
    with pytest.raises(Exception):  # verdict needs status
        ComparisonRunReference(eval_run_id="run-x", gate_verdict="pass")


def test_transition_exclusivity_enforced():
    art = one_assertion("satisfied", "satisfied")
    tr = t0(art)
    with pytest.raises(Exception):  # both classes set
        AssertionTransition.model_validate(tr.model_dump() | {
            "transition_class": "unchanged", "noncomparability_class": "changed_gold"})
    with pytest.raises(Exception):  # neither set
        AssertionTransition.model_validate(tr.model_dump() | {
            "transition_class": None, "noncomparability_class": None})


def test_persisted_reference_binding():
    art = one_assertion("satisfied", "satisfied")
    with pytest.raises(Exception):
        PersistedComparison(comparison_id="cmp-1", artifact_reference="wrong.json",
                            sha256="a" * 64, artifact=art)


# --- Completed status & verdict -------------------------------------------


def test_completed_regression_protected_fails():
    art = one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    assert art.manifest.execution_status == "completed" and art.manifest.gate_verdict == "fail"
    assert t0(art).transition_class == "regression" and t0(art).is_protected_regression
    assert art.case_ledger[0].case_class == "newly_failing"
    assert art.case_ledger[0].protected_regression_count == 1


def test_unprotected_regression_can_pass():
    # both cases fail -> failing->failing regression, unprotected; another case pass->pass
    art = assess(
        b_outcomes=loaded_outcomes("run-base", outcome("run-base", "C1", "A1", "unsatisfied"),
                                   outcome("run-base", "C1", "A2", "satisfied")),
        c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", "C1", "A1", "unsatisfied"),
                                   outcome("run-cand", "C1", "A2", "unsatisfied")),
        b_metadata=metadata("run-base", meta_entry("C1", "A1"), meta_entry("C1", "A2")),
        c_metadata=metadata("run-cand", meta_entry("C1", "A1"), meta_entry("C1", "A2")))
    classes = {t.transition_class for t in art.transitions}
    assert "regression" in classes
    assert not any(t.is_protected_regression for t in art.transitions)
    assert art.manifest.gate_verdict == "pass"  # unprotected regression alone => pass


def test_all_pass_unchanged_is_pass():
    art = one_assertion("satisfied", "satisfied")
    assert art.manifest.gate_verdict == "pass"
    assert t0(art).transition_class == "unchanged"
    assert art.case_ledger[0].case_class == "unchanged_passing"


def test_degradation_yields_indeterminate():
    art = one_assertion("satisfied", "indeterminate")
    assert t0(art).transition_class == "coverage_or_certainty_degradation"
    assert art.manifest.gate_verdict == "indeterminate"


def test_fail_outranks_indeterminate():
    art = assess(
        b_outcomes=loaded_outcomes("run-base", outcome("run-base", "C1", "A1", "satisfied"),
                                   outcome("run-base", "C2", "A1", "satisfied")),
        c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", "C1", "A1", "unsatisfied"),
                                   outcome("run-cand", "C2", "A1", "indeterminate")),
        b_metadata=metadata("run-base", meta_entry("C1", "A1", protected=(PROT,)),
                            meta_entry("C2", "A1")),
        c_metadata=metadata("run-cand", meta_entry("C1", "A1", protected=(PROT,)),
                            meta_entry("C2", "A1")))
    assert art.manifest.gate_verdict == "fail"  # protected regression + degradation -> fail


def test_source_verdict_neutral():
    for sv in ("pass", "fail", "indeterminate"):
        bm, cm = loaded_manifest("run-base"), loaded_manifest("run-cand")
        art = assess(
            b_result=loaded_result(bm.manifest, verdict=sv),
            c_result=loaded_result(cm.manifest, verdict=sv),
            b_manifest=bm, c_manifest=cm,
            b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
            c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
            b_metadata=metadata("run-base", meta_entry(CID, "A1")),
            c_metadata=metadata("run-cand", meta_entry(CID, "A1")))
        assert art.manifest.gate_verdict == "pass"  # source verdict does not force comparison verdict


# --- Source binding -------------------------------------------------------


def test_same_run_id_rejected():
    with pytest.raises(ComparisonValidityError):
        assess(b_manifest=loaded_manifest("same"), c_manifest=loaded_manifest("same"),
               b_outcomes=loaded_outcomes("same", outcome("same", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("same", outcome("same", CID, "A1", "satisfied")),
               b_metadata=metadata("same", meta_entry(CID, "A1")),
               c_metadata=metadata("same", meta_entry(CID, "A1")))


def test_non_completed_source_raises_validity():
    bm = loaded_manifest("run-base")
    with pytest.raises(ComparisonValidityError):
        assess(b_manifest=bm, b_result=loaded_result(bm.manifest, status="invalid", verdict=None),
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_result_wrapper_run_id_mismatch():
    bm = loaded_manifest("run-base")
    bad = loaded_result(bm.manifest).model_copy(update={"eval_run_id": "other"})
    with pytest.raises(ComparisonBindingError):
        assess(b_manifest=bm, b_result=bad,
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_result_dataset_version_mismatch():
    bm = loaded_manifest("run-base")
    with pytest.raises(ComparisonBindingError):
        assess(b_manifest=bm, b_result=loaded_result(bm.manifest, dataset="wrong"),
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_result_projection_wrong_keys():
    bm = loaded_manifest("run-base")
    bad = loaded_result(bm.manifest, metrics={"foo": 1})
    with pytest.raises(ComparisonBindingError):
        assess(b_manifest=bm, b_result=bad,
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_result_provenance_mismatch():
    bm = loaded_manifest("run-base")
    metrics = {"provenance": {"case_set_version": "WRONG", "case_set_hash": bm.manifest.case_set_hash,
                              "scoring_gate_config_version": bm.manifest.scoring_gate_config_version,
                              "scoring_gate_config_hash": bm.manifest.scoring_gate_config_hash,
                              "metric_report_sha256": "a" * 64},
               "gate_outcomes": [], "critical_finding_ids": []}
    with pytest.raises(ComparisonBindingError):
        assess(b_manifest=bm, b_result=loaded_result(bm.manifest, metrics=metrics),
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_result_missing_metric_report_sha():
    bm = loaded_manifest("run-base")
    metrics = {"provenance": {"case_set_version": bm.manifest.case_set_version,
                              "case_set_hash": bm.manifest.case_set_hash,
                              "scoring_gate_config_version": bm.manifest.scoring_gate_config_version,
                              "scoring_gate_config_hash": bm.manifest.scoring_gate_config_hash,
                              "metric_report_sha256": None},
               "gate_outcomes": [], "critical_finding_ids": []}
    with pytest.raises(ComparisonBindingError):
        assess(b_manifest=bm, b_result=loaded_result(bm.manifest, metrics=metrics),
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_outcomes_wrapper_run_id_mismatch():
    with pytest.raises(ComparisonBindingError):
        assess(b_outcomes=loaded_outcomes("other", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_outcome_run_id_mismatch():
    with pytest.raises(ComparisonBindingError):
        assess(b_outcomes=loaded_outcomes("run-base", outcome("other", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_duplicate_outcome_identity():
    with pytest.raises(ComparisonBindingError):
        assess(b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied"),
                                          outcome("run-base", CID, "A1", "unsatisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_scoring_config_hash_mismatch():
    bm = loaded_manifest("run-base")
    with pytest.raises(ComparisonBindingError):
        assess(b_manifest=bm, b_scoring=loaded_scoring(bm.manifest, sha="f" * 64),
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_two_independent_scoring_configs_used():
    # Each side's scoring config binds to its own manifest; a candidate config that
    # binds the baseline manifest but not the candidate manifest must be rejected.
    bm, cm = loaded_manifest("run-base"), loaded_manifest("run-cand",
                                                           scoring_gate_config_version="cfg-v2",
                                                           scoring_gate_config_hash="a" * 64)
    with pytest.raises(ComparisonBindingError):
        assess(b_manifest=bm, c_manifest=cm, c_scoring=loaded_scoring(bm.manifest),
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


# --- Metadata binding -----------------------------------------------------


def test_metadata_missing_entry():
    with pytest.raises(ComparisonMetadataError):
        assess(b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied"),
                                          outcome("run-base", CID, "A2", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),  # missing A2
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_metadata_extra_entry():
    with pytest.raises(ComparisonMetadataError):
        assess(b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1"), meta_entry(CID, "A2")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_metadata_semver_mismatch_own_outcome():
    with pytest.raises(ComparisonMetadataError):
        assess(b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied",
                                                              semver="1.0.0")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1", semver="2.0.0")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


def test_metadata_contract_hash_mismatch_own_outcome():
    with pytest.raises(ComparisonMetadataError):
        assess(b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied",
                                                              semver=None, chash="a" * 64)),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied",
                                                              semver=None, chash="a" * 64)),
               b_metadata=metadata("run-base", meta_entry(CID, "A1", semver=None, chash="b" * 64)),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1", semver=None, chash="a" * 64)))


def test_metadata_undeclared_protected_class():
    with pytest.raises(ComparisonMetadataError):
        one_assertion("satisfied", "satisfied", protected=("undeclared-class",))


def test_metadata_run_id_mismatch():
    with pytest.raises(ComparisonMetadataError):
        assess(b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("other-run", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))


# --- Matching & noncomparability precedence -------------------------------


def test_added_assertion():
    art = assess(
        b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
        c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied"),
                                   outcome("run-cand", CID, "A2", "unsatisfied")),
        b_metadata=metadata("run-base", meta_entry(CID, "A1")),
        c_metadata=metadata("run-cand", meta_entry(CID, "A1"), meta_entry(CID, "A2")))
    added = [t for t in art.transitions if t.assertion_id == "A2"][0]
    assert added.noncomparability_class == "added_assertion" and added.baseline_outcome is None
    assert added.new_failure_without_comparable_baseline is True


def test_removed_assertion():
    art = assess(
        b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied"),
                                   outcome("run-base", CID, "A2", "satisfied")),
        c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
        b_metadata=metadata("run-base", meta_entry(CID, "A1"), meta_entry(CID, "A2")),
        c_metadata=metadata("run-cand", meta_entry(CID, "A1")))
    rem = [t for t in art.transitions if t.assertion_id == "A2"][0]
    assert rem.noncomparability_class == "removed_assertion" and rem.candidate_outcome is None
    assert rem.new_failure_without_comparable_baseline is False


def test_changed_gold_outranks_contract():
    art = one_assertion("satisfied", "unsatisfied", protected=(PROT,), b_semver="1.0.0",
                        c_semver="2.0.0", c_manifest=loaded_manifest("run-cand",
                                                                     case_set_version="cs-v2"))
    assert t0(art).noncomparability_class == "changed_gold"  # outranks changed_assertion_contract


def test_changed_input_packet():
    art = one_assertion("satisfied", "unsatisfied",
                        c_manifest=loaded_manifest("run-cand", prediction_run_manifest_hash="a" * 64))
    assert t0(art).noncomparability_class == "changed_input_packet"


def test_changed_validator_contract():
    art = one_assertion("satisfied", "unsatisfied",
                        c_manifest=loaded_manifest("run-cand", validator_bundle_version="vb2"))
    assert t0(art).noncomparability_class == "changed_validator_contract"


def test_changed_assertion_contract_semver():
    art = one_assertion("satisfied", "unsatisfied", b_semver="1.0.0", c_semver="2.0.0")
    assert t0(art).noncomparability_class == "changed_assertion_contract"


def test_changed_assertion_contract_protected_membership():
    art = one_assertion("satisfied", "unsatisfied", b_protected=(PROT,), c_protected=(PROT2,))
    assert t0(art).noncomparability_class == "changed_assertion_contract"
    assert t0(art).baseline_protected_regression_classes == (PROT,)
    assert t0(art).candidate_protected_regression_classes == (PROT2,)


def test_disjoint_axes_noncomparable():
    # baseline version-only, candidate hash-only -> disjoint axes
    art = one_assertion("satisfied", "unsatisfied", b_semver="1.0.0", b_chash=None,
                        c_semver=None, c_chash="a" * 64)
    assert t0(art).noncomparability_class == "noncomparable_contract"


def test_extra_axis_noncomparable():
    # baseline has both axes, candidate has only semver (equal) -> extra axis on baseline
    art = one_assertion("satisfied", "unsatisfied", b_semver="1.0.0", b_chash="a" * 64,
                        c_semver="1.0.0", c_chash=None)
    assert t0(art).noncomparability_class == "noncomparable_contract"


def test_registry_mismatch_noncomparable():
    art = one_assertion("satisfied", "unsatisfied",
                        c_manifest=loaded_manifest("run-cand", registry_snapshot_hash="a" * 64))
    assert t0(art).noncomparability_class == "noncomparable_contract"


def test_stage_mismatch_noncomparable():
    bm, cm = loaded_manifest("run-base"), loaded_manifest("run-cand")
    art = assess(
        b_manifest=bm, c_manifest=cm,
        b_result=loaded_result(bm.manifest, stage="task_extraction"),
        c_result=loaded_result(cm.manifest, stage="capability_extraction"),
        b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
        c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "unsatisfied")),
        b_metadata=metadata("run-base", meta_entry(CID, "A1")),
        c_metadata=metadata("run-cand", meta_entry(CID, "A1")))
    assert t0(art).noncomparability_class == "noncomparable_contract"


# --- Exhaustive outcome matrix --------------------------------------------

_VALUES = ("satisfied", "unsatisfied", "indeterminate", "not_applicable", "not_evaluated")


@pytest.mark.parametrize("b,c", [(b, c) for b in _VALUES for c in _VALUES])
def test_outcome_matrix(b, c):
    art = one_assertion(b, c)
    tr = t0(art)
    assert tr.noncomparability_class is None
    cls = tr.transition_class
    rank = {"indeterminate": 3, "not_applicable": 2, "not_evaluated": 1}
    if b == c:
        assert cls == "unchanged"
    elif b == "satisfied":
        assert cls == ("regression" if c == "unsatisfied" else "coverage_or_certainty_degradation")
    elif c == "satisfied":
        assert cls == "improvement"
    elif b == "unsatisfied":
        assert cls == "improvement"  # determinate failure gone
    elif c == "unsatisfied":
        assert cls == "coverage_or_certainty_degradation"
        assert tr.new_failure_without_comparable_baseline is True
    else:
        assert cls == ("improvement" if rank[c] > rank[b] else "coverage_or_certainty_degradation")


def test_new_failure_flag_only_on_undetermined_to_unsat():
    assert one_assertion("indeterminate", "unsatisfied").transitions[0]\
        .new_failure_without_comparable_baseline
    assert not one_assertion("satisfied", "unsatisfied").transitions[0]\
        .new_failure_without_comparable_baseline


# --- Protected regression classification ----------------------------------


def test_protected_requires_equal_nonempty_tuples():
    # equal empty -> not protected
    assert not one_assertion("satisfied", "unsatisfied", protected=()).transitions[0]\
        .is_protected_regression
    # equal nonempty -> protected
    assert one_assertion("satisfied", "unsatisfied", protected=(PROT,)).transitions[0]\
        .is_protected_regression


# --- Case ledger classes --------------------------------------------------


def _case_class(b_vals, c_vals, *, protected=None):
    protected = protected or {}
    b_outs = [outcome("run-base", "K1", f"A{i}", v) for i, v in enumerate(b_vals)]
    c_outs = [outcome("run-cand", "K1", f"A{i}", v) for i, v in enumerate(c_vals)]
    b_entries = [meta_entry("K1", f"A{i}", protected=protected.get(i, ())) for i in range(len(b_vals))]
    c_entries = [meta_entry("K1", f"A{i}", protected=protected.get(i, ())) for i in range(len(c_vals))]
    art = assess(
        b_outcomes=loaded_outcomes("run-base", *b_outs),
        c_outcomes=loaded_outcomes("run-cand", *c_outs),
        b_metadata=metadata("run-base", *b_entries),
        c_metadata=metadata("run-cand", *c_entries))
    return art.case_ledger[0].case_class


def test_case_added_and_removed():
    art = assess(
        b_outcomes=loaded_outcomes("run-base", outcome("run-base", "OLD", "A1", "satisfied")),
        c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", "NEW", "A1", "satisfied")),
        b_metadata=metadata("run-base", meta_entry("OLD", "A1")),
        c_metadata=metadata("run-cand", meta_entry("NEW", "A1")))
    classes = {c.case_id: c.case_class for c in art.case_ledger}
    assert classes["NEW"] == "added_case" and classes["OLD"] == "removed_case"


def test_case_classes_matrix():
    assert _case_class(["satisfied"], ["unsatisfied"]) == "newly_failing"
    assert _case_class(["unsatisfied"], ["satisfied"]) == "newly_passing"
    assert _case_class(["satisfied", "satisfied"], ["satisfied", "indeterminate"]) \
        == "degraded_but_still_passing"
    assert _case_class(["unsatisfied", "satisfied"], ["unsatisfied", "unsatisfied"]) \
        == "degraded_and_still_failing"
    assert _case_class(["unsatisfied", "unsatisfied"], ["unsatisfied", "satisfied"]) \
        == "improved_but_still_failing"
    assert _case_class(["satisfied"], ["satisfied"]) == "unchanged_passing"
    assert _case_class(["unsatisfied"], ["unsatisfied"]) == "unchanged_failing"
    # already-failing case (A0 stays failing) that gains a protected regression on A1
    assert _case_class(["unsatisfied", "satisfied"], ["unsatisfied", "unsatisfied"],
                       protected={1: (PROT,)}) == "additional_protected_regression"
    assert _case_class(["not_applicable"], ["not_applicable"]) == "noncomparable"
    assert _case_class(["indeterminate"], ["indeterminate"]) == "indeterminate"


# --- Hashing --------------------------------------------------------------


def test_output_hash_independent_of_comparison_id():
    a = one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    b = assess(cid="totally-different-id",
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "unsatisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1", protected=(PROT,))),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1", protected=(PROT,))))
    assert a.manifest.output_hash == b.manifest.output_hash


def test_output_hash_changes_with_code_commit():
    a = one_assertion("satisfied", "satisfied")
    b = assess(commit="different-commit",
               b_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
               c_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "satisfied")),
               b_metadata=metadata("run-base", meta_entry(CID, "A1")),
               c_metadata=metadata("run-cand", meta_entry(CID, "A1")))
    assert a.manifest.output_hash != b.manifest.output_hash


def test_output_hash_changes_with_swapped_order():
    a = one_assertion("satisfied", "unsatisfied")
    b = assess(  # baseline/candidate swapped
        b_manifest=loaded_manifest("run-cand"), c_manifest=loaded_manifest("run-base"),
        b_outcomes=loaded_outcomes("run-cand", outcome("run-cand", CID, "A1", "unsatisfied")),
        c_outcomes=loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied")),
        b_metadata=metadata("run-cand", meta_entry(CID, "A1")),
        c_metadata=metadata("run-base", meta_entry(CID, "A1")))
    assert a.manifest.output_hash != b.manifest.output_hash


def test_deterministic_equal_distinct():
    a = one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    b = one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    assert a is not b and a.model_dump() == b.model_dump()


def test_no_source_mutation():
    b_out = loaded_outcomes("run-base", outcome("run-base", CID, "A1", "satisfied"))
    before = b_out.model_dump()
    one_assertion("satisfied", "unsatisfied")
    assert b_out.model_dump() == before


# --- Invalid / errored ----------------------------------------------------


def _refs():
    return (ComparisonRunReference(eval_run_id="run-base", execution_status="invalid"),
            ComparisonRunReference(eval_run_id="run-cand"))


def test_invalid_comparison_partial_refs():
    b, c = _refs()
    art = build_invalid_comparison(comparison_id="cmp-i", baseline_role="accepted_release",
                                   comparison_code_commit="cc", baseline_reference=b,
                                   candidate_reference=c,
                                   issues=(ComparisonIssue(issue_code="source_not_completed",
                                                           message="baseline invalid"),))
    assert art.manifest.execution_status == "invalid" and art.manifest.gate_verdict is None
    assert art.transitions == () and art.case_ledger == ()


def test_errored_only_runtime_failure():
    b, c = _refs()
    art = build_errored_comparison(comparison_id="cmp-e", baseline_role="accepted_release",
                                   comparison_code_commit="cc", baseline_reference=b,
                                   candidate_reference=c,
                                   issues=(ComparisonIssue(issue_code="runtime_failure", message="x"),))
    assert art.manifest.execution_status == "errored"
    with pytest.raises(ComparisonValidityError) as exc:
        build_errored_comparison(comparison_id="cmp-e2", baseline_role="accepted_release",
                                 comparison_code_commit="cc", baseline_reference=b,
                                 candidate_reference=c,
                                 issues=(ComparisonIssue(issue_code="metadata_invalid", message="x"),))
    assert type(exc.value) is ComparisonValidityError


def test_invalid_rejects_runtime_failure_code():
    b, c = _refs()
    with pytest.raises(ComparisonValidityError):
        build_invalid_comparison(comparison_id="cmp-i", baseline_role="accepted_release",
                                 comparison_code_commit="cc", baseline_reference=b,
                                 candidate_reference=c,
                                 issues=(ComparisonIssue(issue_code="runtime_failure", message="x"),))


def test_invalid_issues_sorted_and_deduped():
    b, c = _refs()
    issues = (ComparisonIssue(issue_code="metadata_invalid", message="z"),
              ComparisonIssue(issue_code="duplicate_identity", message="a"))
    art = build_invalid_comparison(comparison_id="cmp-i", baseline_role="accepted_release",
                                   comparison_code_commit="cc", baseline_reference=b,
                                   candidate_reference=c, issues=issues)
    assert [i.issue_code for i in art.manifest.errors] == ["duplicate_identity", "metadata_invalid"]
    with pytest.raises(ComparisonValidityError):
        build_invalid_comparison(comparison_id="cmp-i", baseline_role="accepted_release",
                                 comparison_code_commit="cc", baseline_reference=b,
                                 candidate_reference=c,
                                 issues=(ComparisonIssue(issue_code="metadata_invalid", message="m"),
                                         ComparisonIssue(issue_code="metadata_invalid", message="m")))


def test_terminal_same_run_id_rejected():
    same = ComparisonRunReference(eval_run_id="run-x")
    with pytest.raises(ComparisonValidityError):
        build_invalid_comparison(comparison_id="cmp-i", baseline_role="accepted_release",
                                 comparison_code_commit="cc", baseline_reference=same,
                                 candidate_reference=ComparisonRunReference(eval_run_id="run-x"),
                                 issues=(ComparisonIssue(issue_code="metadata_invalid", message="m"),))


def test_issue_reference_rejects_bad_paths():
    for bad in ("/etc/x", "..\\x", "a/../b", "a//b", "C:\\x", "a\nb"):
        with pytest.raises(Exception):
            ComparisonIssue(issue_code="metadata_invalid", message="m", artifact_reference=bad)


# --- Persistence & loading ------------------------------------------------


def test_persist_and_load_roundtrip(tmp_path):
    art = one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    p = persist_comparison(art, eval_root=tmp_path)
    assert isinstance(p, PersistedComparison)
    assert p.artifact_reference == "comparisons/cmp-1/comparison_manifest.json"
    d = tmp_path / "comparisons" / "cmp-1"
    assert sorted(x.name for x in d.iterdir()) == [
        "assertion_transitions.jsonl", "case_ledger.jsonl", "comparison_manifest.json"]
    assert sha256_bytes((d / "comparison_manifest.json").read_bytes()) == p.sha256
    lo = load_comparison("cmp-1", eval_root=tmp_path)
    assert isinstance(lo, LoadedComparison)
    assert lo.artifact.model_dump() == art.model_dump()


def test_persist_invalid_manifest_only(tmp_path):
    b, c = _refs()
    art = build_invalid_comparison(comparison_id="cmp-i", baseline_role="accepted_release",
                                   comparison_code_commit="cc", baseline_reference=b,
                                   candidate_reference=c,
                                   issues=(ComparisonIssue(issue_code="source_not_completed",
                                                           message="x"),))
    persist_comparison(art, eval_root=tmp_path)
    d = tmp_path / "comparisons" / "cmp-i"
    assert sorted(x.name for x in d.iterdir()) == ["comparison_manifest.json"]
    lo = load_comparison("cmp-i", eval_root=tmp_path)
    assert lo.artifact.manifest.execution_status == "invalid"


def test_persist_canonical_one_newline(tmp_path):
    art = one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    persist_comparison(art, eval_root=tmp_path)
    raw = (tmp_path / "comparisons" / "cmp-1" / "comparison_manifest.json").read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    expected = canonical_contract_bytes(art.manifest.model_dump(mode="json", exclude_unset=True)) + b"\n"
    assert raw == expected
    jsonl = (tmp_path / "comparisons" / "cmp-1" / "assertion_transitions.jsonl").read_bytes()
    assert jsonl.endswith(b"\n")


def test_persist_write_once(tmp_path):
    art = one_assertion("satisfied", "satisfied")
    persist_comparison(art, eval_root=tmp_path)
    with pytest.raises(ComparisonExistsError):
        persist_comparison(art, eval_root=tmp_path)


def test_persist_rejects_dir_collision(tmp_path):
    (tmp_path / "comparisons").mkdir()
    (tmp_path / "comparisons" / "cmp-1").mkdir()
    with pytest.raises(ComparisonExistsError):
        persist_comparison(one_assertion("satisfied", "satisfied"), eval_root=tmp_path)


def test_persist_rejects_parent_symlink(tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    (tmp_path / "comparisons").symlink_to(other)
    with pytest.raises(ComparisonExistsError):
        persist_comparison(one_assertion("satisfied", "satisfied"), eval_root=tmp_path)


def test_persist_rejects_comparison_dir_symlink(tmp_path):
    (tmp_path / "comparisons").mkdir()
    target = tmp_path / "target"
    target.mkdir()
    (tmp_path / "comparisons" / "cmp-1").symlink_to(target)
    with pytest.raises(ComparisonExistsError):
        persist_comparison(one_assertion("satisfied", "satisfied"), eval_root=tmp_path)


def test_persist_write_failure_preserves_dir(tmp_path, monkeypatch):
    art = one_assertion("satisfied", "satisfied")

    def boom(*a, **k):
        raise OSError("synthetic-write-failure")

    monkeypatch.setattr(comp.os, "open", boom)
    with pytest.raises(ComparisonWriteError):
        persist_comparison(art, eval_root=tmp_path)
    monkeypatch.undo()
    assert (tmp_path / "comparisons" / "cmp-1").is_dir()


def test_persist_rejects_readback_hash_mismatch(tmp_path, monkeypatch):
    art = one_assertion("satisfied", "satisfied")
    real = Path.read_bytes

    def corrupt(self, *a, **k):
        data = real(self, *a, **k)
        return data + b"x" if self.name == "comparison_manifest.json" else data

    monkeypatch.setattr(Path, "read_bytes", corrupt)
    with pytest.raises(comp.ComparisonDestinationHashMismatchError):
        persist_comparison(art, eval_root=tmp_path)


def _tamper_manifest(art, **updates):
    return art.manifest.model_copy(update=updates)


def test_persist_rejects_ledger_hash_tamper_before_dir(tmp_path):
    art = one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    tampered = ComparisonArtifact.model_construct(
        manifest=_tamper_manifest(art, transition_ledger_sha256="0" * 64),
        transitions=art.transitions, case_ledger=art.case_ledger)
    with pytest.raises(ComparisonBindingMismatchError):
        persist_comparison(tampered, eval_root=tmp_path)
    assert not (tmp_path / "comparisons").exists()


def test_persist_rejects_output_hash_tamper_before_dir(tmp_path):
    art = one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    tampered = ComparisonArtifact.model_construct(
        manifest=_tamper_manifest(art, output_hash="0" * 64),
        transitions=art.transitions, case_ledger=art.case_ledger)
    with pytest.raises(ComparisonBindingMismatchError):
        persist_comparison(tampered, eval_root=tmp_path)
    assert not (tmp_path / "comparisons").exists()


def test_load_missing(tmp_path):
    with pytest.raises(ComparisonArtifactMissingError):
        load_comparison("cmp-x", eval_root=tmp_path)


def test_load_read_failure(tmp_path, monkeypatch):
    persist_comparison(one_assertion("satisfied", "satisfied"), eval_root=tmp_path)
    real = Path.read_bytes

    def boom(self, *a, **k):
        if self.name == "comparison_manifest.json":
            raise OSError("synthetic-read-failure-detail")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(comp.ComparisonArtifactReadError) as exc:
        load_comparison("cmp-1", eval_root=tmp_path)
    assert type(exc.value) is comp.ComparisonArtifactReadError
    assert "synthetic-read-failure-detail" not in str(exc.value)
    assert str(tmp_path) not in str(exc.value)


def _write_dir(tmp_path, cid, manifest_bytes, *, transitions=None, case=None):
    d = tmp_path / "comparisons" / cid
    d.mkdir(parents=True, exist_ok=False)
    (d / "comparison_manifest.json").write_bytes(manifest_bytes)
    if transitions is not None:
        (d / "assertion_transitions.jsonl").write_bytes(transitions)
    if case is not None:
        (d / "case_ledger.jsonl").write_bytes(case)
    return d


def _completed_bytes(tmp_path, cid="cmp-1"):
    art = one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    persist_comparison(art, eval_root=tmp_path)
    d = tmp_path / "comparisons" / cid
    m = (d / "comparison_manifest.json").read_bytes()
    t = (d / "assertion_transitions.jsonl").read_bytes()
    c = (d / "case_ledger.jsonl").read_bytes()
    import shutil
    shutil.rmtree(d)
    return m, t, c


def test_load_rejects_non_utf8(tmp_path):
    _write_dir(tmp_path, "cmp-1", b"\xff\xfe")
    with pytest.raises(ComparisonDecodeError):
        load_comparison("cmp-1", eval_root=tmp_path)


def test_load_rejects_bom(tmp_path):
    m, t, c = _completed_bytes(tmp_path)
    _write_dir(tmp_path, "cmp-1", "\ufeff".encode("utf-8") + m, transitions=t, case=c)
    with pytest.raises(ComparisonJsonError):
        load_comparison("cmp-1", eval_root=tmp_path)


def test_load_rejects_trailing_json(tmp_path):
    m, t, c = _completed_bytes(tmp_path)
    _write_dir(tmp_path, "cmp-1", m.rstrip(b"\n") + b" x", transitions=t, case=c)
    with pytest.raises(ComparisonJsonError):
        load_comparison("cmp-1", eval_root=tmp_path)


def test_load_rejects_duplicate_keys(tmp_path):
    _write_dir(tmp_path, "cmp-1", b'{"a":1,"a":2}')
    with pytest.raises(ComparisonJsonError) as exc:
        load_comparison("cmp-1", eval_root=tmp_path)
    assert exc.value.duplicate_key == "a"


def test_load_rejects_nonfinite(tmp_path):
    _write_dir(tmp_path, "cmp-1", b'{"metrics":{"x":NaN}}')
    with pytest.raises(ComparisonJsonError):
        load_comparison("cmp-1", eval_root=tmp_path)


def test_load_rejects_non_object(tmp_path):
    _write_dir(tmp_path, "cmp-1", b"[1,2]")
    with pytest.raises(ComparisonTopLevelTypeError):
        load_comparison("cmp-1", eval_root=tmp_path)


def test_load_rejects_model_invalid(tmp_path):
    _write_dir(tmp_path, "cmp-1", b'{"unexpected":true}')
    with pytest.raises(ComparisonModelValidationError):
        load_comparison("cmp-1", eval_root=tmp_path)


def test_load_rejects_ledger_count_mismatch(tmp_path):
    m, t, c = _completed_bytes(tmp_path)
    # duplicate the transition line -> count/hash disagree with manifest
    _write_dir(tmp_path, "cmp-1", m, transitions=t + t, case=c)
    with pytest.raises(ComparisonBindingMismatchError):
        load_comparison("cmp-1", eval_root=tmp_path)


def test_load_rejects_unexpected_ledger_on_invalid(tmp_path):
    b, c = _refs()
    art = build_invalid_comparison(comparison_id="cmp-i", baseline_role="accepted_release",
                                   comparison_code_commit="cc", baseline_reference=b,
                                   candidate_reference=c,
                                   issues=(ComparisonIssue(issue_code="source_not_completed",
                                                           message="x"),))
    persist_comparison(art, eval_root=tmp_path)
    (tmp_path / "comparisons" / "cmp-i" / "assertion_transitions.jsonl").write_bytes(b"{}\n")
    with pytest.raises(ComparisonBindingMismatchError):
        load_comparison("cmp-i", eval_root=tmp_path)


def test_load_rejects_symlinked_comparison_dir(tmp_path):
    art = one_assertion("satisfied", "satisfied")
    persist_comparison(art, eval_root=tmp_path)
    real = tmp_path / "comparisons" / "cmp-1"
    link = tmp_path / "comparisons" / "cmp-link"
    link.symlink_to(real)
    with pytest.raises(ComparisonArtifactNotAFileError):
        load_comparison("cmp-link", eval_root=tmp_path)


def test_load_rejects_symlinked_manifest(tmp_path):
    art = one_assertion("satisfied", "satisfied")
    persist_comparison(art, eval_root=tmp_path)
    d = tmp_path / "comparisons" / "cmp-1"
    real = d / "comparison_manifest.json"
    real.rename(d / "real.json")
    real.symlink_to(d / "real.json")
    with pytest.raises(ComparisonArtifactNotAFileError):
        load_comparison("cmp-1", eval_root=tmp_path)


def test_repeated_loads_equal_distinct(tmp_path):
    persist_comparison(one_assertion("satisfied", "unsatisfied", protected=(PROT,)), eval_root=tmp_path)
    a = load_comparison("cmp-1", eval_root=tmp_path)
    b = load_comparison("cmp-1", eval_root=tmp_path)
    assert a is not b and a.artifact is not b.artifact
    assert a.artifact.model_dump() == b.artifact.model_dump()


def test_invalid_eval_root_rejected():
    with pytest.raises(ComparisonValidityError):
        load_comparison("cmp-1", eval_root="")


# --- Boundaries, exports, hygiene -----------------------------------------


def test_pure_constructors_no_filesystem(monkeypatch):
    calls = []

    def spy(name, orig):
        def w(*a, **k):
            calls.append(name)
            return orig(*a, **k)
        return w

    monkeypatch.setattr(Path, "read_bytes", spy("rb", Path.read_bytes))
    monkeypatch.setattr(Path, "write_bytes", spy("wb", Path.write_bytes))
    monkeypatch.setattr(Path, "mkdir", spy("mk", Path.mkdir))
    monkeypatch.setattr(os, "open", spy("op", os.open))
    one_assertion("satisfied", "unsatisfied", protected=(PROT,))
    b, c = _refs()
    build_invalid_comparison(comparison_id="cmp-i", baseline_role="accepted_release",
                             comparison_code_commit="cc", baseline_reference=b, candidate_reference=c,
                             issues=(ComparisonIssue(issue_code="metadata_invalid", message="m"),))
    build_errored_comparison(comparison_id="cmp-e", baseline_role="accepted_release",
                             comparison_code_commit="cc", baseline_reference=b, candidate_reference=c,
                             issues=(ComparisonIssue(issue_code="runtime_failure", message="m"),))
    assert calls == []


def test_protected_slice_1_10_hashes_unchanged():
    from dynamic_ai_products.evaluation import models as mod
    from dynamic_ai_products.evaluation.envelopes import PredictionArtifactManifest
    from dynamic_ai_products.evaluation.metrics import MetricReport
    exp = {
        ("EvaluationRunManifest", "evaluation_run_manifest"): "7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee",
        ("ValidatorFinding", "validator_finding"): "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292",
        ("FindingDisposition", "finding_disposition"): "1c08efdbd36682acf535cc688ae5c73e902e1659f30814b6a5bee46b2c9d873e",
        ("PredictionEnvelope", "prediction_envelope"): "5ac06fb78220c3f7369863cda32ee914a1d33ff01020fc01e57d9bd0ccbb18a3",
        ("AssertionOutcome", "assertion_outcome"): "4af3a9eb7c99e3e3ba088784b3395f4b6920fa1f8061f7bb1118af6bd2720bd6",
    }
    for (name, cid), h in exp.items():
        assert model_contract_hash(getattr(mod, name), cid, "0.1.0") == h
    assert model_contract_hash(PredictionArtifactManifest, "prediction_artifact_manifest", "0.1.0") \
        == "4b164aea18fc99f9518854aca0fb98587eb71d81c972a477d48cb815ddc0dbe4"
    assert model_contract_hash(MetricReport, "metric_report", "0.1.0") \
        == "d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39"


PUBLIC_NAMES = (
    "BaselineRole", "CaseLedgerClass", "ComparableTransitionClass", "NoncomparabilityClass",
    "AssertionComparisonMetadata", "AssertionComparisonMetadataEntry", "AssertionTransition",
    "CaseLedgerEntry", "ComparisonArtifact", "ComparisonIssue", "ComparisonManifest",
    "ComparisonRunReference", "LoadedComparison", "PersistedComparison",
    "assess_comparison", "build_errored_comparison", "build_invalid_comparison",
    "load_comparison", "persist_comparison",
    "ComparisonError", "ComparisonValidityError", "ComparisonBindingError",
    "ComparisonMetadataError", "ComparisonBindingMismatchError", "ComparisonExistsError",
    "ComparisonArtifactMissingError", "ComparisonArtifactNotAFileError",
    "ComparisonArtifactReadError", "ComparisonDecodeError", "ComparisonJsonError",
    "ComparisonTopLevelTypeError", "ComparisonModelValidationError", "ComparisonWriteError",
    "ComparisonDestinationHashMismatchError",
)


def test_all_34_public_names_exported():
    assert len(PUBLIC_NAMES) == 34
    for name in PUBLIC_NAMES:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(comp, name)


def test_exception_hierarchy():
    concrete = [n for n in PUBLIC_NAMES if n.startswith("Comparison") and n.endswith("Error")
                and n != "ComparisonError"]
    assert comp.ComparisonError.__bases__ == (Exception,)
    for name in concrete:
        assert issubclass(getattr(comp, name), comp.ComparisonError)


def test_no_direct_base_error_raise():
    import ast
    tree = ast.parse((ROOT / "src" / "dynamic_ai_products" / "evaluation" / "comparator.py").read_text())
    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Raise) and node.exc is not None:
            target = node.exc.func if isinstance(node.exc, ast.Call) else node.exc
            if isinstance(target, ast.Name) and target.id == "ComparisonError":
                offenders.append(node.lineno)
    assert offenders == []


def test_private_not_exported():
    for name in ("CaseStatus", "_ContractStamped", "_build_transitions", "_derive_verdict",
                 "_logical_output_hash", "_COMPARISON_CONTRACT_VERSION"):
        assert name not in evaluation_pkg.__all__


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
        "import dynamic_ai_products.evaluation.comparator\n"
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open=orb,ort,omk,oop\nhashlib.sha256=osha\n"
        "bad=[p for p in reads if p.endswith('.json') or p.endswith('.jsonl') or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad and not writes and not sha, (bad, writes, len(sha))\nprint('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
