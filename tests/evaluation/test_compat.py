"""Slice 12: compatibility readers and bridge re-evaluation coordination.

Historical documents and a fake trusted in-process executor are built in-test
(no repository fixtures). Readers are pure/read-only; the coordinator is pure
and the executor may be impure. The trust boundary is honest: a self-consistent
malicious executor output is outside the supported authenticity model — tests
document that boundary rather than claim independent authentication.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import comparator as comparator_mod
from dynamic_ai_products.evaluation import compat as compat_mod
from dynamic_ai_products.evaluation.case_sets import case_set_snapshot_hash
from dynamic_ai_products.evaluation.comparator import (
    ComparisonInputPacketEntry,
    ComparisonInputPacketSnapshot,
    ComparisonManifest,
    assess_comparison,
    build_comparison_input_packet_snapshot,
)
from dynamic_ai_products.evaluation.compat import (
    BridgeAssertionContractEntry,
    BridgeAssertionContractSnapshot,
    BridgeComparisonArguments,
    BridgeMetadataError,
    BridgePartialFailureError,
    BridgeReevaluationResult,
    BridgeRequest,
    BridgeRequestError,
    BridgeSharedContract,
    BridgeSideBindingError,
    BridgeSideComparatorInputs,
    BridgeSideComparisonBundle,
    BridgeSideExecutionError,
    BridgeSideExecutionResult,
    BridgeSideRequest,
    CompatDecodeError,
    CompatError,
    CompatJsonError,
    CompatSchemaHashMismatchError,
    CompatSchemaMissingError,
    CompatSchemaNotAFileError,
    CompatSchemaReadError,
    CompatSchemaRootError,
    CompatSchemaValidationError,
    CompatTopLevelTypeError,
    CompatUnsupportedVersionError,
    HistoricalEvaluationResultV1,
    LoadedHistoricalEvaluationResult,
    LoadedUniverseRunManifest,
    UniverseRunManifestDocument,
    build_bridge_assertion_contract_snapshot,
    build_bridge_comparison_arguments,
    derive_bridge_side_metadata,
    materialize_bridge_comparison_inputs,
    read_evaluation_result_v1,
    read_universe_run_manifest,
    reevaluate_bridge_pair,
)
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes, model_contract_hash
from dynamic_ai_products.evaluation.gates import LoadedEvaluationResult
from dynamic_ai_products.evaluation.models import (
    AssertionOutcome,
    CaseSetManifest,
    EvaluationResultV2,
    EvaluationRunManifest,
)
from dynamic_ai_products.evaluation.references import (
    CaseResolution,
    ResolvedAssertionReferences,
    ResolvedScoringReference,
)
from dynamic_ai_products.evaluation.runs import LoadedEvaluationRunManifest, runtime_contract_provenance
from dynamic_ai_products.evaluation.scoring_config import LoadedScoringGateConfig, load_scoring_gate_config
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_ROOT = ROOT
FX = ROOT / "evals" / "fixtures" / "evaluation_harness" / "configs"
SC = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX)
PROT = "synth-protected-temporal"
CID = "SYNTH-CASE-0001"
PYV = runtime_contract_provenance()["pydantic_version"]
RM_STAMP = {"contract_id": "evaluation_run_manifest", "contract_version": "0.1.0",
            "contract_hash": model_contract_hash(EvaluationRunManifest, "evaluation_run_manifest", "0.1.0")}
AO_STAMP = {"contract_id": "assertion_outcome", "contract_version": "0.1.0",
            "contract_hash": model_contract_hash(AssertionOutcome, "assertion_outcome", "0.1.0")}
GATE_REF = next(g.reference_id for g in SC.config.gates if PROT in g.protected_regression_class_references)


def H(c: str) -> str:
    return c * 64


# --- Governed shared case set + input-packet snapshot (ADR-023) -----------
# One governed new case set; both bridge sides re-evaluate over it, so a single
# shared snapshot (built via the committed public builder) binds both sides.
CSM_STAMP = {"contract_id": "case_set_manifest", "contract_version": "0.1.0",
             "contract_hash": model_contract_hash(CaseSetManifest, "case_set_manifest", "0.1.0")}
SHARED_CSM = CaseSetManifest.model_validate({
    "contract": CSM_STAMP, "case_set_version": "cs", "lifecycle": "frozen",
    "registry_snapshot_version": "rv", "registry_snapshot_hash": H("c"),
    "entries": [{"case_id": CID, "partition": "frozen_test", "suites": ["regression"],
                 "input_packet_hash": H("7")}]})
CS_HASH = case_set_snapshot_hash(SHARED_CSM)
_SNAP_RM = LoadedEvaluationRunManifest(
    manifest=EvaluationRunManifest.model_validate({
        "contract": RM_STAMP, "eval_run_id": "snap-src", "prediction_run_id": "p",
        "prediction_run_manifest_hash": H("1"), "case_set_version": "cs", "case_set_hash": CS_HASH,
        "registry_snapshot_hash": H("c"), "validator_bundle_version": "vb",
        "validator_bundle_hash": H("d"), "scoring_gate_config_version": SC.version,
        "scoring_gate_config_hash": SC.sha256, "code_commit": "cc", "pydantic_runtime_version": PYV}),
    sha256=H("6"), artifact_reference="snap/m.json")
SHARED_SNAPSHOT = build_comparison_input_packet_snapshot(
    run_manifest=_SNAP_RM, case_set_manifest=SHARED_CSM)


# --- Historical document builders -----------------------------------------


def eval_v1(**ov):
    doc = {"eval_run_id": "r1", "stage": "task_extraction", "dataset_version": "v1",
           "metrics": {"a": 1}, "decision": "conditional_pass"}
    doc.update(ov)
    return doc


def universe_doc(**ov):
    doc = {"run_id": "u1", "universe_version": "1", "baseline_cutoff": "2020",
           "form_scope": ["10-K"], "candidate_frame_hash": "h", "taxonomy_version": "t",
           "sample_rules_version": "s", "schema_versions": {"company": "0.1.0"},
           "run_timestamp": "2026", "counts": {"n": 5}, "hard_gate_status": "pass",
           "output_hashes": {"o": "x"}}
    doc.update(ov)
    return doc


# --- Bridge builders -------------------------------------------------------


def shared(**ov):
    base = {"stage": "task_extraction", "case_set_version": "cs", "case_set_hash": CS_HASH,
            "registry_snapshot_hash": H("c"), "validator_bundle_version": "vb",
            "validator_bundle_hash": H("d"), "scoring_gate_config_version": SC.version,
            "scoring_gate_config_hash": SC.sha256, "code_commit": "cc",
            "pydantic_runtime_version": PYV}
    base.update(ov)
    return BridgeSharedContract(**base)


def resolution(*, protected=(PROT,), semver="1.0.0", chash=None):
    refs = () if not protected else (ResolvedScoringReference(
        requested_reference_id=GATE_REF, canonical_reference_id=GATE_REF, definition_kind="gate"),)
    return CaseResolution(
        case_id=CID, target_registry_version="rv", target_registry_sha256=H("e"),
        scoring_config_version=SC.version, scoring_config_sha256=SC.sha256,
        assertions=(ResolvedAssertionReferences(
            assertion_id="A1", assertion_semantic_version=semver, assertion_contract_hash=chash,
            target_references=(), scoring_references=refs),))


def snapshot(*, resolutions=None):
    return build_bridge_assertion_contract_snapshot(
        resolutions=resolutions if resolutions is not None else (resolution(),), scoring_config=SC)


def request(*, snap=None, sc=None, ips=None):
    return BridgeRequest(
        baseline_role="validator_bridge_baseline", shared_contract=sc or shared(),
        assertion_contract_snapshot=snap or snapshot(),
        input_packet_snapshot=ips if ips is not None else SHARED_SNAPSHOT,
        baseline=BridgeSideRequest(side="baseline", source_prediction_run_id="pb",
                                   source_prediction_run_manifest_hash=H("1"),
                                   target_bridge_eval_run_id="bridge-base"),
        candidate=BridgeSideRequest(side="candidate", source_prediction_run_id="pc",
                                    source_prediction_run_manifest_hash=H("2"),
                                    target_bridge_eval_run_id="bridge-cand"))


def loaded_manifest(run_id, src_pred, src_hash, **ov):
    fields = {"contract": RM_STAMP, "eval_run_id": run_id, "prediction_run_id": src_pred,
              "prediction_run_manifest_hash": src_hash, "case_set_version": "cs",
              "case_set_hash": CS_HASH, "registry_snapshot_hash": H("c"),
              "validator_bundle_version": "vb", "validator_bundle_hash": H("d"),
              "scoring_gate_config_version": SC.version, "scoring_gate_config_hash": SC.sha256,
              "code_commit": "cc", "pydantic_runtime_version": PYV}
    fields.update(ov)
    rm = EvaluationRunManifest.model_validate(fields)
    sha = sha256_bytes(canonical_contract_bytes(rm.model_dump(mode="json", exclude_unset=True)))
    return LoadedEvaluationRunManifest(manifest=rm, sha256=sha, artifact_reference=f"{run_id}/m.json")


def loaded_result(run_id, verdict="pass", **provov):
    prov = {"case_set_version": "cs", "case_set_hash": CS_HASH,
            "scoring_gate_config_version": SC.version, "scoring_gate_config_hash": SC.sha256,
            "metric_report_sha256": H("f")}
    prov.update(provov)
    r = EvaluationResultV2.model_validate({
        "eval_run_id": run_id, "stage": "task_extraction", "dataset_version": "cs",
        "metrics": {"provenance": prov, "gate_outcomes": [], "critical_finding_ids": []},
        "execution_status": "completed", "gate_verdict": verdict})
    sha = sha256_bytes(canonical_contract_bytes(r.model_dump(mode="json", exclude_unset=True)) + b"\n")
    return LoadedEvaluationResult(eval_run_id=run_id, artifact_reference="results/evaluation_result.json",
                                  sha256=sha, result=r)


def loaded_outcomes(run_id, outcome_value="satisfied", semver="1.0.0", chash=None):
    payload = {"contract": AO_STAMP, "eval_run_id": run_id, "case_id": CID, "assertion_id": "A1",
               "outcome": outcome_value}
    if semver is not None:
        payload["assertion_semantic_version"] = semver
    if chash is not None:
        payload["assertion_contract_hash"] = chash
    ao = AssertionOutcome.model_validate(payload)
    from dynamic_ai_products.evaluation.assertions import LoadedAssertionOutcomes
    sha = sha256_bytes(canonical_contract_bytes(ao.model_dump(mode="json", exclude_unset=True)) + b"\n")
    return LoadedAssertionOutcomes(eval_run_id=run_id, artifact_reference=f"{run_id}/a.jsonl",
                                   sha256=sha, outcomes=(ao,))


def loaded_scoring():
    return LoadedScoringGateConfig(config=SC.config, version=SC.version, sha256=SC.sha256,
                                   artifact_reference="x")


def side_result(side, run_id, src_pred, src_hash, verdict="pass", outcome_value="satisfied"):
    return BridgeSideExecutionResult(
        side=side, run_manifest=loaded_manifest(run_id, src_pred, src_hash),
        result=loaded_result(run_id, verdict), outcomes=loaded_outcomes(run_id, outcome_value),
        scoring_config=loaded_scoring())


def good_executor(*, side_request, shared_contract):
    if side_request.side == "baseline":
        return side_result("baseline", "bridge-base", "pb", H("1"), "pass", "satisfied")
    return side_result("candidate", "bridge-cand", "pc", H("2"), "fail", "unsatisfied")


def valid_pair():
    return reevaluate_bridge_pair(request(), executor=good_executor)


# --- Reader: routes & schema loading --------------------------------------


def test_reader_evaluation_result_v1_route():
    lo = read_evaluation_result_v1(eval_v1(), contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    assert isinstance(lo, LoadedHistoricalEvaluationResult)
    assert lo.contract_version == "0.1.0" and lo.document.decision == "conditional_pass"
    assert lo.schema_sha256 == "2fae7b2305c041ed9062d272929bb67589aaf4f5ea0d7503fe4b56b87a480453"


def test_reader_universe_v1_and_v2_routes():
    u1 = read_universe_run_manifest(universe_doc(), contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    u2 = read_universe_run_manifest(universe_doc(), contract_version="0.2.0", schema_root=SCHEMA_ROOT)
    assert isinstance(u1, LoadedUniverseRunManifest)
    assert isinstance(u1.document, UniverseRunManifestDocument)
    assert u1.contract_version == "0.1.0" and u2.contract_version == "0.2.0"
    assert u1.source_sha256 == u2.source_sha256  # identical document bytes
    assert u1.schema_sha256 != u2.schema_sha256  # different pinned schema files


def test_reader_unsupported_version():
    with pytest.raises(CompatUnsupportedVersionError):
        read_evaluation_result_v1(eval_v1(), contract_version="9.9.9", schema_root=SCHEMA_ROOT)
    with pytest.raises(CompatUnsupportedVersionError):
        read_universe_run_manifest(universe_doc(), contract_version="3.0.0", schema_root=SCHEMA_ROOT)


def test_reader_no_evaluation_result_v2_route():
    with pytest.raises(CompatUnsupportedVersionError):
        read_evaluation_result_v1(eval_v1(), contract_version="0.2.0", schema_root=SCHEMA_ROOT)


def test_reader_schema_root_invalid(tmp_path):
    with pytest.raises(CompatSchemaRootError):
        read_evaluation_result_v1(eval_v1(), contract_version="0.1.0", schema_root=tmp_path / "nope")
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(CompatSchemaRootError):
        read_evaluation_result_v1(eval_v1(), contract_version="0.1.0", schema_root=f)


def test_reader_schema_root_symlink(tmp_path):
    target = tmp_path / "real"
    target.mkdir()
    link = tmp_path / "link"
    link.symlink_to(target)
    with pytest.raises(CompatSchemaRootError):
        read_evaluation_result_v1(eval_v1(), contract_version="0.1.0", schema_root=link)


def test_reader_schema_missing(tmp_path):
    (tmp_path / "schemas").mkdir()
    with pytest.raises(CompatSchemaMissingError):
        read_evaluation_result_v1(eval_v1(), contract_version="0.1.0", schema_root=tmp_path)


def test_reader_schema_symlink(tmp_path):
    (tmp_path / "schemas").mkdir()
    real = ROOT / "schemas" / "evaluation_result.schema.json"
    (tmp_path / "schemas" / "evaluation_result.schema.json").symlink_to(real)
    with pytest.raises(CompatSchemaNotAFileError):
        read_evaluation_result_v1(eval_v1(), contract_version="0.1.0", schema_root=tmp_path)


def test_reader_schema_hash_tamper(tmp_path):
    (tmp_path / "schemas").mkdir()
    raw = (ROOT / "schemas" / "evaluation_result.schema.json").read_bytes()
    (tmp_path / "schemas" / "evaluation_result.schema.json").write_bytes(raw + b"\n")
    with pytest.raises(CompatSchemaHashMismatchError):
        read_evaluation_result_v1(eval_v1(), contract_version="0.1.0", schema_root=tmp_path)


# --- Reader: strict payload parsing ---------------------------------------


def test_reader_bytes_str_mapping_source_sha():
    import json as _json
    doc = eval_v1()
    b = read_evaluation_result_v1(_json.dumps(doc).encode("utf-8"), contract_version="0.1.0",
                                  schema_root=SCHEMA_ROOT)
    s = read_evaluation_result_v1(_json.dumps(doc), contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    m = read_evaluation_result_v1(doc, contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    assert b.source_sha256 == s.source_sha256  # same UTF-8 bytes
    # Mapping SHA is over canonical bytes; equals bytes SHA only if input was canonical.
    assert m.source_sha256 == sha256_bytes(canonical_contract_bytes(doc))


def test_reader_mapping_order_independent_and_not_mutated():
    d1 = {"eval_run_id": "r1", "stage": "s", "dataset_version": "v", "metrics": {"a": 1}, "decision": "pass"}
    d2 = {"decision": "pass", "metrics": {"a": 1}, "dataset_version": "v", "stage": "s", "eval_run_id": "r1"}
    a = read_evaluation_result_v1(d1, contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    b = read_evaluation_result_v1(d2, contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    assert a.source_sha256 == b.source_sha256
    before = dict(d1)
    read_evaluation_result_v1(d1, contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    assert d1 == before  # not mutated


def test_reader_utf8_bom_json_errors():
    with pytest.raises(CompatDecodeError):
        read_evaluation_result_v1(b"\xff\xfe", contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    with pytest.raises(CompatJsonError):
        read_evaluation_result_v1(("\ufeff" + "{}").encode("utf-8"), contract_version="0.1.0",
                                  schema_root=SCHEMA_ROOT)
    with pytest.raises(CompatJsonError):
        read_evaluation_result_v1(b'{"a":1} trailing', contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    with pytest.raises(CompatJsonError):
        read_evaluation_result_v1(b'{"a":1,"a":2}', contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    with pytest.raises(CompatJsonError):
        read_evaluation_result_v1(b'{"a":NaN}', contract_version="0.1.0", schema_root=SCHEMA_ROOT)


def test_reader_nested_nonfinite_mapping():
    with pytest.raises(CompatJsonError):
        read_evaluation_result_v1({"eval_run_id": "r", "stage": "s", "dataset_version": "v",
                                   "metrics": {"a": float("inf")}, "decision": "pass"},
                                  contract_version="0.1.0", schema_root=SCHEMA_ROOT)


def test_reader_wrong_top_level_type():
    with pytest.raises(CompatTopLevelTypeError):
        read_evaluation_result_v1(b"[1,2]", contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    with pytest.raises(CompatTopLevelTypeError):
        read_evaluation_result_v1(123, contract_version="0.1.0", schema_root=SCHEMA_ROOT)


def test_reader_schema_validation_error():
    with pytest.raises(CompatSchemaValidationError):
        read_evaluation_result_v1({"eval_run_id": "r"}, contract_version="0.1.0",
                                  schema_root=SCHEMA_ROOT)  # missing required fields


# --- Reader: schema-exact & nullability -----------------------------------


def test_conditional_pass_preserved():
    lo = read_evaluation_result_v1(eval_v1(decision="conditional_pass"), contract_version="0.1.0",
                                   schema_root=SCHEMA_ROOT)
    assert lo.document.decision == "conditional_pass"
    assert lo.to_mapping()["decision"] == "conditional_pass"


def test_no_v1_to_v2_conversion_api():
    assert not hasattr(HistoricalEvaluationResultV1, "to_v2")
    assert not any("v2" in n.lower() for n in dir(LoadedHistoricalEvaluationResult) if not n.startswith("_"))


def test_metrics_must_be_object_errors_must_be_array():
    with pytest.raises(PydanticValidationError):
        HistoricalEvaluationResultV1(eval_run_id="r", stage="s", dataset_version="v",
                                     metrics=[1, 2], decision="pass")
    with pytest.raises(PydanticValidationError):
        HistoricalEvaluationResultV1(eval_run_id="r", stage="s", dataset_version="v",
                                     metrics={"a": 1}, decision="pass", errors={"a": 1})


def test_result_explicit_null_semantics():
    # errors / created_at forbid explicit null; reviewer_notes allows it
    with pytest.raises(CompatSchemaValidationError):
        read_evaluation_result_v1(eval_v1(errors=None), contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    with pytest.raises(CompatSchemaValidationError):
        read_evaluation_result_v1(eval_v1(created_at=None), contract_version="0.1.0",
                                  schema_root=SCHEMA_ROOT)
    ok = read_evaluation_result_v1(eval_v1(reviewer_notes=None), contract_version="0.1.0",
                                   schema_root=SCHEMA_ROOT)
    assert ok.document.reviewer_notes is None


def test_universe_optional_null_semantics():
    ok = read_universe_run_manifest(universe_doc(source_manifest_hash=None), contract_version="0.1.0",
                                    schema_root=SCHEMA_ROOT)
    assert ok.document.source_manifest_hash is None
    for field in ("model_routes", "eval_report_ids", "manual_review_complete", "limitations"):
        with pytest.raises(CompatSchemaValidationError):
            read_universe_run_manifest(universe_doc(**{field: None}), contract_version="0.1.0",
                                       schema_root=SCHEMA_ROOT)


def test_universe_counts_strict_integers():
    for bad in ({"n": True}, {"n": -1}, {"n": 1.5}):
        with pytest.raises(CompatSchemaValidationError):
            read_universe_run_manifest(universe_doc(counts=bad), contract_version="0.1.0",
                                       schema_root=SCHEMA_ROOT)


def test_universe_eval_report_ids_variants():
    absent = read_universe_run_manifest(universe_doc(), contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    assert "eval_report_ids" not in absent.to_mapping()
    empty = read_universe_run_manifest(universe_doc(eval_report_ids=[]), contract_version="0.2.0",
                                       schema_root=SCHEMA_ROOT)
    assert empty.to_mapping()["eval_report_ids"] == []
    full = read_universe_run_manifest(universe_doc(eval_report_ids=["e1", "e2"]), contract_version="0.1.0",
                                      schema_root=SCHEMA_ROOT)
    assert full.to_mapping()["eval_report_ids"] == ["e1", "e2"]


def test_no_reverse_link_or_writer_api():
    for name in dir(compat_mod):
        assert "reverse" not in name.lower()
    assert not hasattr(LoadedUniverseRunManifest, "write")
    assert not hasattr(LoadedUniverseRunManifest, "persist")


# --- Deep immutability & to_mapping isolation -----------------------------


def test_historical_data_deeply_immutable():
    lo = read_evaluation_result_v1(eval_v1(metrics={"a": {"nested": [1, 2]}}), contract_version="0.1.0",
                                   schema_root=SCHEMA_ROOT)
    with pytest.raises(TypeError):
        lo.document.metrics["a"]["nested"] = [9]
    assert isinstance(lo.document.metrics["a"]["nested"], tuple)


def test_source_mapping_mutation_after_read_does_not_affect_wrapper():
    src = {"eval_run_id": "r", "stage": "s", "dataset_version": "v",
           "metrics": {"a": {"nested": [1, 2]}}, "decision": "pass"}
    lo = read_evaluation_result_v1(src, contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    src["metrics"]["a"]["nested"].append(999)
    assert lo.to_mapping()["metrics"]["a"]["nested"] == [1, 2]


def test_to_mapping_mutation_isolation():
    lo = read_universe_run_manifest(universe_doc(), contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    m = lo.to_mapping()
    m["schema_versions"]["company"] = "HACK"
    assert lo.to_mapping()["schema_versions"]["company"] == "0.1.0"


# --- Snapshot builder ------------------------------------------------------


def test_snapshot_derivation_and_protected_class():
    snap = snapshot()
    assert isinstance(snap, BridgeAssertionContractSnapshot)
    assert isinstance(snap.entries[0], BridgeAssertionContractEntry)
    assert snap.entries[0].identity == (CID, "A1")
    assert snap.entries[0].protected_regression_classes == (PROT,)
    assert snap.scoring_config_version == SC.version and snap.scoring_config_sha256 == SC.sha256
    assert snap.mapping_version == "0.1.0" and snap.failure_taxonomy_version == "0.1.0"


def test_snapshot_diagnostic_reference_skipped():
    diag_ref = SC.config.diagnostics[0].reference_id
    res = CaseResolution(
        case_id=CID, target_registry_version="rv", target_registry_sha256=H("e"),
        scoring_config_version=SC.version, scoring_config_sha256=SC.sha256,
        assertions=(ResolvedAssertionReferences(
            assertion_id="A1", assertion_semantic_version="1.0.0", assertion_contract_hash=None,
            target_references=(), scoring_references=(ResolvedScoringReference(
                requested_reference_id=diag_ref, canonical_reference_id=diag_ref,
                definition_kind="diagnostic"),)),))
    snap = build_bridge_assertion_contract_snapshot(resolutions=(res,), scoring_config=SC)
    assert snap.entries[0].protected_regression_classes == ()


def test_snapshot_unresolved_gate_rejected():
    res = CaseResolution(
        case_id=CID, target_registry_version="rv", target_registry_sha256=H("e"),
        scoring_config_version=SC.version, scoring_config_sha256=SC.sha256,
        assertions=(ResolvedAssertionReferences(
            assertion_id="A1", assertion_semantic_version="1.0.0", assertion_contract_hash=None,
            target_references=(), scoring_references=(ResolvedScoringReference(
                requested_reference_id="ghost", canonical_reference_id="ghost",
                definition_kind="gate"),)),))
    with pytest.raises(BridgeMetadataError):
        build_bridge_assertion_contract_snapshot(resolutions=(res,), scoring_config=SC)


def test_snapshot_duplicate_identity_rejected():
    res = resolution()
    with pytest.raises(BridgeMetadataError):
        build_bridge_assertion_contract_snapshot(resolutions=(res, res), scoring_config=SC)


def test_snapshot_entries_sorted():
    r1 = CaseResolution(case_id="B", target_registry_version="rv", target_registry_sha256=H("e"),
                        scoring_config_version=SC.version, scoring_config_sha256=SC.sha256,
                        assertions=(ResolvedAssertionReferences(assertion_id="A1",
                            assertion_semantic_version="1.0.0", assertion_contract_hash=None,
                            target_references=(), scoring_references=()),))
    r2 = CaseResolution(case_id="A", target_registry_version="rv", target_registry_sha256=H("e"),
                        scoring_config_version=SC.version, scoring_config_sha256=SC.sha256,
                        assertions=(ResolvedAssertionReferences(assertion_id="A1",
                            assertion_semantic_version="1.0.0", assertion_contract_hash=None,
                            target_references=(), scoring_references=()),))
    snap = build_bridge_assertion_contract_snapshot(resolutions=(r1, r2), scoring_config=SC)
    assert [e.case_id for e in snap.entries] == ["A", "B"]


# --- Request ---------------------------------------------------------------


def test_request_fixed_role_and_direction():
    req = request()
    assert req.baseline_role == "validator_bridge_baseline"
    with pytest.raises(PydanticValidationError):
        BridgeRequest(baseline_role="model_upgrade_baseline", shared_contract=shared(),
                      assertion_contract_snapshot=snapshot(), input_packet_snapshot=SHARED_SNAPSHOT,
                      baseline=req.baseline, candidate=req.candidate)


def test_request_distinct_ids_and_snapshot_binding():
    with pytest.raises(PydanticValidationError):  # same source prediction id
        BridgeRequest(baseline_role="validator_bridge_baseline", shared_contract=shared(),
                      assertion_contract_snapshot=snapshot(), input_packet_snapshot=SHARED_SNAPSHOT,
                      baseline=BridgeSideRequest(side="baseline", source_prediction_run_id="p",
                          source_prediction_run_manifest_hash=H("1"), target_bridge_eval_run_id="b"),
                      candidate=BridgeSideRequest(side="candidate", source_prediction_run_id="p",
                          source_prediction_run_manifest_hash=H("2"), target_bridge_eval_run_id="c"))
    with pytest.raises(PydanticValidationError):  # snapshot scoring mismatch vs shared contract
        request(sc=shared(scoring_gate_config_hash=H("9")))


def test_request_snapshot_must_bind_shared_contract():
    # input_packet_snapshot must bind the shared contract's case-set/registry axes
    other_csm = CaseSetManifest.model_validate({
        "contract": CSM_STAMP, "case_set_version": "cs", "lifecycle": "frozen",
        "registry_snapshot_version": "rv", "registry_snapshot_hash": H("9"),
        "entries": [{"case_id": CID, "partition": "frozen_test", "suites": ["regression"],
                     "input_packet_hash": H("7")}]})
    other_rm = _SNAP_RM.model_copy(update={"manifest": _SNAP_RM.manifest.model_copy(update={
        "case_set_hash": case_set_snapshot_hash(other_csm), "registry_snapshot_hash": H("9")})})
    mismatched = build_comparison_input_packet_snapshot(
        run_manifest=other_rm, case_set_manifest=other_csm)
    with pytest.raises(PydanticValidationError):  # registry/case-set-hash mismatch vs shared contract
        request(ips=mismatched)


def test_request_deeply_immutable():
    req = request()
    with pytest.raises(PydanticValidationError):
        req.baseline = req.candidate


# --- Side binding & self-consistency --------------------------------------


def test_side_binding_target_id_mismatch():
    bad = side_result("baseline", "WRONG", "pb", H("1"))
    with pytest.raises(BridgeSideBindingError):
        compat_mod._bind_side(bad, request=request())


def test_side_binding_source_prediction_mismatch():
    bad = side_result("baseline", "bridge-base", "OTHER", H("1"))
    with pytest.raises(BridgeSideBindingError):
        compat_mod._bind_side(bad, request=request())


def test_side_binding_shared_contract_mismatch():
    bad = side_result("baseline", "bridge-base", "pb", H("1"))
    bad = bad.model_copy(update={"run_manifest": bad.run_manifest.model_copy(
        update={"manifest": bad.run_manifest.manifest.model_copy(update={"code_commit": "OTHER"})})})
    with pytest.raises(BridgeSideBindingError):
        compat_mod._bind_side(bad, request=request())


def test_side_binding_non_completed_result():
    bm = loaded_manifest("bridge-base", "pb", H("1"))
    r = EvaluationResultV2.model_validate({"eval_run_id": "bridge-base", "stage": "task_extraction",
        "dataset_version": "cs", "metrics": {"foo": 1}, "execution_status": "invalid"})
    # an invalid result has no gate_verdict; also metrics projection wrong -> binding error
    lr = LoadedEvaluationResult(eval_run_id="bridge-base", artifact_reference="results/evaluation_result.json",
                                sha256=sha256_bytes(canonical_contract_bytes(
                                    r.model_dump(mode="json", exclude_unset=True)) + b"\n"), result=r)
    bad = BridgeSideExecutionResult(side="baseline", run_manifest=bm, result=lr,
                                    outcomes=loaded_outcomes("bridge-base"), scoring_config=loaded_scoring())
    with pytest.raises(BridgeSideBindingError):
        compat_mod._bind_side(bad, request=request())


def test_side_binding_result_artifact_sha_tamper():
    good = side_result("baseline", "bridge-base", "pb", H("1"))
    bad = good.model_copy(update={"result": good.result.model_copy(update={"sha256": H("0")})})
    with pytest.raises(BridgeSideBindingError):  # sha256 no longer self-consistent
        compat_mod._bind_side(bad, request=request())


def test_side_binding_outcomes_jsonl_sha_tamper():
    good = side_result("baseline", "bridge-base", "pb", H("1"))
    bad = good.model_copy(update={"outcomes": good.outcomes.model_copy(update={"sha256": H("0")})})
    with pytest.raises(BridgeSideBindingError):
        compat_mod._bind_side(bad, request=request())


def test_self_consistent_forgery_is_accepted_within_trust_envelope():
    # This layer verifies structural self-consistency only. The injected in-process
    # executor envelope is trusted; the side-binding boundary does NOT independently
    # authenticate the gate verdict (no independent authority exists at this layer).
    # Acceptance of a self-consistent forgery is the documented Option A trust
    # boundary, not a security bypass.
    honest = side_result("baseline", "bridge-base", "pb", H("1"), verdict="fail")
    forged_result = honest.result.result.model_copy(update={"gate_verdict": "pass"})  # flip verdict
    forged_sha = sha256_bytes(
        canonical_contract_bytes(forged_result.model_dump(mode="json", exclude_unset=True)) + b"\n")
    forged_lr = honest.result.model_copy(update={"result": forged_result, "sha256": forged_sha})
    forged = honest.model_copy(update={"result": forged_lr})
    assert forged.result.result.gate_verdict != honest.result.result.gate_verdict
    assert compat_mod._result_artifact_sha(forged.result) == forged.result.sha256  # self-consistent
    # binding accepts the self-consistent forgery (returns None; no raise)
    assert compat_mod._bind_side(forged, request=request()) is None


# --- Metadata trust boundary ----------------------------------------------


def test_metadata_protected_class_from_snapshot_only():
    snap = snapshot()
    meta = derive_bridge_side_metadata(target_eval_run_id="bridge-base", snapshot=snap,
                                       scoring_config=loaded_scoring(),
                                       outcomes=loaded_outcomes("bridge-base"))
    assert meta.entries[0].protected_regression_classes == (PROT,)
    assert meta.eval_run_id == "bridge-base"


def test_metadata_unknown_outcome_identity_rejected():
    snap = snapshot()
    other = loaded_outcomes("bridge-base")
    other = other.model_copy(update={"outcomes": (other.outcomes[0].model_copy(
        update={"assertion_id": "UNKNOWN"}),)})
    with pytest.raises(BridgeMetadataError):
        derive_bridge_side_metadata(target_eval_run_id="bridge-base", snapshot=snap,
                                    scoring_config=loaded_scoring(), outcomes=other)


def test_metadata_version_mismatch_rejected():
    snap = snapshot()  # snapshot semver 1.0.0
    with pytest.raises(BridgeMetadataError):
        derive_bridge_side_metadata(target_eval_run_id="bridge-base", snapshot=snap,
                                    scoring_config=loaded_scoring(),
                                    outcomes=loaded_outcomes("bridge-base", semver="2.0.0"))


def test_metadata_scoring_snapshot_mismatch_rejected():
    snap = snapshot()
    bad_config = LoadedScoringGateConfig(config=SC.config, version="other-v", sha256=SC.sha256,
                                         artifact_reference="x")
    with pytest.raises(BridgeMetadataError):
        derive_bridge_side_metadata(target_eval_run_id="bridge-base", snapshot=snap,
                                    scoring_config=bad_config, outcomes=loaded_outcomes("bridge-base"))


def test_metadata_snapshot_superset_allowed():
    # snapshot has A1 and A2; outcomes only A1 -> exact outcome coverage, A2 unused
    r = CaseResolution(case_id=CID, target_registry_version="rv", target_registry_sha256=H("e"),
                       scoring_config_version=SC.version, scoring_config_sha256=SC.sha256,
                       assertions=(
        ResolvedAssertionReferences(assertion_id="A1", assertion_semantic_version="1.0.0",
            assertion_contract_hash=None, target_references=(), scoring_references=()),
        ResolvedAssertionReferences(assertion_id="A2", assertion_semantic_version="1.0.0",
            assertion_contract_hash=None, target_references=(), scoring_references=()),))
    snap = build_bridge_assertion_contract_snapshot(resolutions=(r,), scoring_config=SC)
    meta = derive_bridge_side_metadata(target_eval_run_id="bridge-base", snapshot=snap,
                                       scoring_config=loaded_scoring(),
                                       outcomes=loaded_outcomes("bridge-base"))
    assert {e.identity for e in meta.entries} == {(CID, "A1")}


def test_raw_result_has_no_metadata_or_snapshot_field():
    fields = set(BridgeSideExecutionResult.model_fields)
    assert fields == {"side", "run_manifest", "result", "outcomes", "scoring_config"}


# --- Coordinator behavior --------------------------------------------------


def test_coordinator_rejects_non_request():
    with pytest.raises(BridgeRequestError):
        reevaluate_bridge_pair({"not": "a request"}, executor=good_executor)


def test_coordinator_success_and_order():
    calls = []

    def spy(*, side_request, shared_contract):
        calls.append(side_request.side)
        return good_executor(side_request=side_request, shared_contract=shared_contract)

    result = reevaluate_bridge_pair(request(), executor=spy)
    assert isinstance(result, BridgeReevaluationResult)
    assert isinstance(result.baseline, BridgeSideComparisonBundle)
    assert calls == ["baseline", "candidate"]
    assert result.baseline_role == "validator_bridge_baseline"
    assert result.baseline.side == "baseline" and result.candidate.side == "candidate"


def test_coordinator_baseline_failure_skips_candidate():
    calls = []

    def exec_(*, side_request, shared_contract):
        calls.append(side_request.side)
        if side_request.side == "baseline":
            raise BridgeSideExecutionError(failed_side="baseline")
        return good_executor(side_request=side_request, shared_contract=shared_contract)

    with pytest.raises(BridgeSideExecutionError) as exc:
        reevaluate_bridge_pair(request(), executor=exec_)
    assert type(exc.value) is BridgeSideExecutionError
    assert exc.value.failed_side == "baseline"
    assert calls == ["baseline"]  # candidate never called
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_coordinator_baseline_wrong_side():
    def exec_(*, side_request, shared_contract):
        raise BridgeSideExecutionError(failed_side="candidate")  # wrong side for baseline
    with pytest.raises(BridgeSideBindingError):
        reevaluate_bridge_pair(request(), executor=exec_)


def test_coordinator_candidate_execution_partial():
    def exec_(*, side_request, shared_contract):
        if side_request.side == "baseline":
            return good_executor(side_request=side_request, shared_contract=shared_contract)
        raise BridgeSideExecutionError(failed_side="candidate")
    with pytest.raises(BridgePartialFailureError) as exc:
        reevaluate_bridge_pair(request(), executor=exec_)
    assert exc.value.failure_kind == "execution_failure"
    assert exc.value.completed_baseline.side == "baseline"
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_coordinator_candidate_wrong_side_partial_binding():
    def exec_(*, side_request, shared_contract):
        if side_request.side == "baseline":
            return good_executor(side_request=side_request, shared_contract=shared_contract)
        raise BridgeSideExecutionError(failed_side="baseline")
    with pytest.raises(BridgePartialFailureError) as exc:
        reevaluate_bridge_pair(request(), executor=exec_)
    assert exc.value.failure_kind == "binding_failure"
    assert exc.value.completed_baseline.side == "baseline"
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_coordinator_candidate_binding_partial():
    def exec_(*, side_request, shared_contract):
        if side_request.side == "baseline":
            return good_executor(side_request=side_request, shared_contract=shared_contract)
        return side_result("candidate", "WRONG-ID", "pc", H("2"))  # target mismatch
    with pytest.raises(BridgePartialFailureError) as exc:
        reevaluate_bridge_pair(request(), executor=exec_)
    assert exc.value.failure_kind == "binding_failure"
    assert exc.value.completed_baseline.side == "baseline"
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def test_coordinator_candidate_metadata_partial():
    snap = snapshot()

    def exec_(*, side_request, shared_contract):
        if side_request.side == "baseline":
            return good_executor(side_request=side_request, shared_contract=shared_contract)
        # candidate outcome identity not in snapshot -> metadata failure
        return side_result("candidate", "bridge-cand", "pc", H("2"), "fail", "unsatisfied").model_copy(
            update={"outcomes": _relabel(loaded_outcomes("bridge-cand", "unsatisfied"), "ZZZ")})
    with pytest.raises(BridgePartialFailureError) as exc:
        reevaluate_bridge_pair(request(snap=snap), executor=exec_)
    assert exc.value.failure_kind == "metadata_failure"
    assert exc.value.completed_baseline.side == "baseline"
    assert exc.value.__cause__ is None and exc.value.__context__ is None


def _relabel(outcomes, new_assertion_id):
    o = outcomes.outcomes[0].model_copy(update={"assertion_id": new_assertion_id})
    new_sha = sha256_bytes(canonical_contract_bytes(o.model_dump(mode="json", exclude_unset=True)) + b"\n")
    return outcomes.model_copy(update={"outcomes": (o,), "sha256": new_sha})


def test_coordinator_unexpected_exception_propagates():
    def exec_(*, side_request, shared_contract):
        raise RuntimeError("boom")
    with pytest.raises(RuntimeError):
        reevaluate_bridge_pair(request(), executor=exec_)


def test_coordinator_no_io(monkeypatch):
    calls = []

    def spy(name, orig):
        def w(*a, **k):
            calls.append(name)
            return orig(*a, **k)
        return w

    monkeypatch.setattr(Path, "read_bytes", spy("rb", Path.read_bytes))
    monkeypatch.setattr(Path, "mkdir", spy("mk", Path.mkdir))
    monkeypatch.setattr(os, "open", spy("op", os.open))
    valid_pair()
    assert calls == []


# --- Exception safety ------------------------------------------------------


def test_execution_error_interface():
    e = BridgeSideExecutionError(failed_side="baseline")
    assert e.failed_side == "baseline"
    assert "baseline" not in str(e) or "execution" in str(e)  # fixed sanitized message
    with pytest.raises(AttributeError):
        e.failed_side = "candidate"


def test_partial_failure_readonly_and_sanitized():
    def exec_(*, side_request, shared_contract):
        if side_request.side == "baseline":
            return good_executor(side_request=side_request, shared_contract=shared_contract)
        raise BridgeSideExecutionError(failed_side="candidate")
    with pytest.raises(BridgePartialFailureError) as exc:
        reevaluate_bridge_pair(request(), executor=exec_)
    e = exc.value
    with pytest.raises(AttributeError):
        e.failure_kind = "x"
    with pytest.raises(AttributeError):
        e.completed_baseline = None
    assert e.__cause__ is None and e.__context__ is None
    assert "boom" not in str(e)


# --- Canonical bundle & fingerprints --------------------------------------


def test_committed_wrappers_transitively_mutable():
    lr = loaded_result("r1")
    lr.result.metrics["INJECTED"] = 1  # committed wrapper is transitively mutable
    assert "INJECTED" in lr.result.metrics


def test_bundle_isolated_from_post_capture_mutation():
    raw = side_result("baseline", "bridge-base", "pb", H("1"))
    bundle = compat_mod._build_bundle(raw, request=request())
    raw.result.result.metrics["INJECTED"] = 1  # mutate the raw wrapper after capture
    mat = materialize_bridge_comparison_inputs(bundle)
    assert "INJECTED" not in mat.result.result.metrics


def test_bundle_fingerprint_tamper_detected():
    result = valid_pair()
    tampered = result.baseline.model_copy(update={"result_fingerprint": H("0")})
    # the frozen bundle's strict re-validation is the governed integrity check;
    # a model_copy bypass surfaces as an un-chained PydanticValidationError.
    with pytest.raises(PydanticValidationError) as ei:
        materialize_bridge_comparison_inputs(tampered)
    assert ei.value.__cause__ is None and ei.value.__context__ is None


def test_bundle_payload_tamper_detected():
    result = valid_pair()
    tampered = result.baseline.model_copy(update={"result_payload": b'{"eval_run_id":"HACK"}'})
    with pytest.raises(PydanticValidationError) as ei:
        materialize_bridge_comparison_inputs(tampered)
    assert ei.value.__cause__ is None and ei.value.__context__ is None


def test_artifact_hash_distinct_from_fingerprint():
    result = valid_pair()
    b = result.baseline
    # the manifest artifact SHA (inner .sha256) is carried inside the payload, and differs
    # from the bundle fingerprint (which hashes the whole wrapper canonical dump).
    mat = materialize_bridge_comparison_inputs(b)
    assert mat.run_manifest.sha256 != b.manifest_fingerprint


# --- Materialization & handoff --------------------------------------------


def test_materialize_equal_but_distinct():
    result = valid_pair()
    a = materialize_bridge_comparison_inputs(result.baseline)
    b = materialize_bridge_comparison_inputs(result.baseline)
    assert isinstance(a, BridgeSideComparatorInputs)
    assert a.model_dump() == b.model_dump() and a is not b and a.result is not b.result


def test_materialize_mutation_isolation():
    result = valid_pair()
    a = materialize_bridge_comparison_inputs(result.baseline)
    a.result.result.metrics["MUT"] = 1
    b = materialize_bridge_comparison_inputs(result.baseline)
    assert "MUT" not in b.result.result.metrics


def test_handoff_arguments_and_assess():
    # Full ADR-023 chain: governed CaseSetManifest -> build_comparison_input_packet_snapshot
    # -> BridgeRequest.input_packet_snapshot -> BridgeReevaluationResult.request
    # -> build_bridge_comparison_arguments -> to_assess_kwargs -> assess_comparison.
    result = valid_pair()
    assert result.request.input_packet_snapshot.model_dump() == SHARED_SNAPSHOT.model_dump()
    args = build_bridge_comparison_arguments(result, comparison_id="cmp-1", comparison_code_commit="cc")
    assert isinstance(args, BridgeComparisonArguments)
    kw = args.to_assess_kwargs()
    assert set(kw) == {
        "comparison_id", "baseline_role", "comparison_code_commit", "baseline_manifest",
        "candidate_manifest", "baseline_result", "candidate_result", "baseline_outcomes",
        "candidate_outcomes", "baseline_scoring_config", "candidate_scoring_config",
        "baseline_metadata", "candidate_metadata",
        "baseline_input_packets", "candidate_input_packets"}
    assert len(kw) == 15
    assert kw["baseline_role"] == "validator_bridge_baseline"
    assert hasattr(kw["baseline_manifest"], "manifest")  # model instances, not dicts
    # both input-packet snapshots are the single governed request snapshot
    assert kw["baseline_input_packets"].model_dump() == SHARED_SNAPSHOT.model_dump()
    assert kw["candidate_input_packets"].model_dump() == SHARED_SNAPSHOT.model_dump()
    artifact = assess_comparison(**kw)
    assert artifact.manifest.execution_status == "completed"
    # baseline satisfied -> candidate unsatisfied on a protected assertion => regression, fail
    assert artifact.transitions[0].transition_class == "regression"
    assert artifact.transitions[0].noncomparability_class is None
    assert artifact.manifest.gate_verdict == "fail"


def test_handoff_kwargs_fresh_each_call():
    args = build_bridge_comparison_arguments(valid_pair(), comparison_id="c", comparison_code_commit="cc")
    k1 = args.to_assess_kwargs()
    k1["baseline_manifest"] = "HACK"
    k2 = args.to_assess_kwargs()
    assert k2["baseline_manifest"] != "HACK" and hasattr(k2["baseline_manifest"], "manifest")


def test_handoff_no_persistence(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(os, "open", lambda *a, **k: calls.append("o"))
    monkeypatch.setattr(Path, "mkdir", lambda self, *a, **k: calls.append("m"))
    # the handoff is pure and must not raise; no broad swallowing
    build_bridge_comparison_arguments(valid_pair(), comparison_id="c", comparison_code_commit="cc")
    assert calls == []


def _snap_with(*, entries, case_set_version="cs", case_set_hash=CS_HASH, registry=H("c")):
    ents = tuple(entries)
    return ComparisonInputPacketSnapshot(
        case_set_version=case_set_version, case_set_hash=case_set_hash,
        registry_snapshot_hash=registry, entries=ents,
        input_packet_set_hash=comparator_mod._input_packet_set_hash(ents))


def test_handoff_snapshot_comparability_semantics():
    # The bridge feeds ONE shared input-packet snapshot to both sides, so the
    # handoff is always comparable. These direct assess_comparison calls document
    # the noncomparability classes that a *divergent* snapshot would surface --
    # exactly what the shared-snapshot design deliberately prevents (ADR-023).
    base_kw = build_bridge_comparison_arguments(
        valid_pair(), comparison_id="c", comparison_code_commit="cc").to_assess_kwargs()

    # (a) shared snapshot on both sides -> comparable regression, no noncomparability.
    a = assess_comparison(**base_kw)
    assert a.transitions[0].noncomparability_class is None
    assert a.transitions[0].transition_class == "regression"

    # (b) same case set / registry, different per-case input packet -> changed_input_packet.
    kw = dict(base_kw)
    kw["candidate_input_packets"] = _snap_with(
        entries=(ComparisonInputPacketEntry(case_id=CID, input_packet_hash=H("8")),))
    b = assess_comparison(**kw)
    assert b.transitions[0].transition_class is None
    assert b.transitions[0].noncomparability_class == "changed_input_packet"

    # (c) different gold registry snapshot -> changed_gold (candidate manifest re-binds).
    kw = dict(base_kw)
    cm = kw["candidate_manifest"]
    new_m = cm.manifest.model_copy(update={"registry_snapshot_hash": H("9")})
    new_sha = sha256_bytes(canonical_contract_bytes(new_m.model_dump(mode="json", exclude_unset=True)))
    kw["candidate_manifest"] = cm.model_copy(update={"manifest": new_m, "sha256": new_sha})
    kw["candidate_input_packets"] = _snap_with(
        entries=(ComparisonInputPacketEntry(case_id=CID, input_packet_hash=H("7")),), registry=H("9"))
    c = assess_comparison(**kw)
    assert c.transitions[0].noncomparability_class == "changed_gold"

    # (d) a matched outcome case dropped from one snapshot is a hard binding error,
    # not a classification -- both snapshots must cover every matched case.
    kw = dict(base_kw)
    kw["candidate_input_packets"] = _snap_with(
        entries=(ComparisonInputPacketEntry(case_id="OTHER", input_packet_hash=H("7")),))
    with pytest.raises(comparator_mod.ComparisonBindingError):
        assess_comparison(**kw)


def test_input_packet_membership_superset_is_changed_gold():
    # ADR-023 valid membership-difference classification -- distinct from the
    # dropped-consumed-case binding guard in the test above. The matched assertion
    # case is present on BOTH sides and the candidate packet snapshot is a superset
    # holding one extra case. A genuine membership change classifies changed_gold /
    # indeterminate through the real committed comparator, with no registry change
    # and no matched-packet-content change.
    second_case = "SYNTH-CASE-0002"
    assert second_case != CID
    new_case_set_hash = H("a")  # a valid, distinct lowercase 64-hex case_set_hash
    base_kwargs = build_bridge_comparison_arguments(
        valid_pair(), comparison_id="membership-superset", comparison_code_commit="cc",
    ).to_assess_kwargs()

    # Candidate run manifest: adopt the new case_set_hash; recompute the manifest
    # SHA over canonical inner-manifest JSON bytes with NO trailing newline.
    cand_manifest = base_kwargs["candidate_manifest"]
    new_inner_manifest = cand_manifest.manifest.model_copy(update={"case_set_hash": new_case_set_hash})
    new_manifest_sha = sha256_bytes(
        canonical_contract_bytes(new_inner_manifest.model_dump(mode="json", exclude_unset=True)))
    cand_manifest = cand_manifest.model_copy(
        update={"manifest": new_inner_manifest, "sha256": new_manifest_sha})

    # Candidate result: provenance case_set_hash adopts the new value; recompute the
    # result SHA over canonical result JSON bytes PLUS exactly one trailing newline.
    cand_result = base_kwargs["candidate_result"]
    old_metrics = cand_result.result.metrics
    new_provenance = dict(old_metrics["provenance"])
    new_provenance["case_set_hash"] = new_case_set_hash
    new_metrics = dict(old_metrics)
    new_metrics["provenance"] = new_provenance
    new_inner_result = cand_result.result.model_copy(update={"metrics": new_metrics})
    new_result_sha = sha256_bytes(
        canonical_contract_bytes(new_inner_result.model_dump(mode="json", exclude_unset=True)) + b"\n")
    cand_result = cand_result.model_copy(update={"result": new_inner_result, "sha256": new_result_sha})

    # Candidate input-packet snapshot: superset {CID, second_case}, sorted unique,
    # lowercase 64-hex packet hashes. The aggregate is computed INDEPENDENTLY here
    # (not via the production _input_packet_set_hash helper). The matched case keeps
    # its baseline packet hash, so the ONLY membership difference is the added case.
    entries = tuple(sorted(
        (ComparisonInputPacketEntry(case_id=CID, input_packet_hash=H("7")),
         ComparisonInputPacketEntry(case_id=second_case, input_packet_hash=H("8"))),
        key=lambda e: e.case_id))
    payload = [{"case_id": e.case_id, "input_packet_hash": e.input_packet_hash} for e in entries]
    packet_set_hash = sha256_bytes(canonical_contract_bytes(payload))
    cand_packets = ComparisonInputPacketSnapshot(
        case_set_version="cs", case_set_hash=new_case_set_hash, registry_snapshot_hash=H("c"),
        entries=entries, input_packet_set_hash=packet_set_hash)

    baseline_packets = base_kwargs["baseline_input_packets"]
    # Prove membership change -- NOT a registry change and NOT a matched-packet change.
    assert baseline_packets.registry_snapshot_hash == cand_packets.registry_snapshot_hash
    assert CID in baseline_packets.by_case and CID in cand_packets.by_case
    assert baseline_packets.by_case[CID] == cand_packets.by_case[CID]
    assert second_case in cand_packets.by_case and second_case not in baseline_packets.by_case
    assert set(cand_packets.by_case) - set(baseline_packets.by_case) == {second_case}
    assert cand_packets.case_set_hash != baseline_packets.case_set_hash
    # Prediction-run-manifest hashes are untouched (not used to manufacture the result).
    assert cand_manifest.manifest.prediction_run_manifest_hash \
        == base_kwargs["candidate_manifest"].manifest.prediction_run_manifest_hash
    # Outcomes/metadata still cover only the matched case; the superset case has no outcome.
    assert {(o.case_id, o.assertion_id) for o in base_kwargs["candidate_outcomes"].outcomes} == {(CID, "A1")}
    assert {e.identity for e in base_kwargs["candidate_metadata"].entries} == {(CID, "A1")}

    kwargs = dict(base_kwargs)
    kwargs["candidate_manifest"] = cand_manifest
    kwargs["candidate_result"] = cand_result
    kwargs["candidate_input_packets"] = cand_packets
    artifact = assess_comparison(**kwargs)  # consumes the matched assertion; no ComparisonBindingError

    assert artifact.manifest.execution_status == "completed"
    assert artifact.manifest.gate_verdict == "indeterminate"
    transition = next(t for t in artifact.transitions if t.case_id == CID and t.assertion_id == "A1")
    assert transition.transition_class is None
    assert transition.noncomparability_class == "changed_gold"


def test_schema_read_error_is_typed_and_sanitized(monkeypatch):
    # An OSError while reading the pinned schema surfaces as CompatSchemaReadError
    # with a sanitized message (relative path only, no absolute path, no OS text)
    # and the original OSError preserved as __cause__.
    real_read_bytes = Path.read_bytes

    def boom(self, *a, **k):
        if self.name.endswith(".schema.json"):
            raise OSError(13, "Permission denied: /private/secret/abs.json")
        return real_read_bytes(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(CompatSchemaReadError) as ei:
        read_evaluation_result_v1(eval_v1(), contract_version="0.1.0", schema_root=SCHEMA_ROOT)
    msg = str(ei.value)
    assert "schemas/evaluation_result.schema.json" in msg
    assert "Permission denied" not in msg
    assert "/private/secret/abs.json" not in msg
    assert str(SCHEMA_ROOT) not in msg
    assert isinstance(ei.value.__cause__, OSError)


# --- Boundaries, exports, hygiene -----------------------------------------


def test_all_38_exports():
    names = [
        "BridgeAssertionContractEntry", "BridgeAssertionContractSnapshot", "BridgeComparisonArguments",
        "BridgeReevaluationResult", "BridgeRequest", "BridgeSharedContract",
        "BridgeSideComparatorInputs", "BridgeSideComparisonBundle", "BridgeSideExecutionResult",
        "BridgeSideExecutor", "BridgeSideRequest", "HistoricalEvaluationResultV1",
        "LoadedHistoricalEvaluationResult", "LoadedUniverseRunManifest", "UniverseRunManifestDocument",
        "build_bridge_assertion_contract_snapshot", "build_bridge_comparison_arguments",
        "derive_bridge_side_metadata", "materialize_bridge_comparison_inputs",
        "read_evaluation_result_v1", "read_universe_run_manifest", "reevaluate_bridge_pair",
        "BridgeMetadataError", "BridgePartialFailureError", "BridgeRequestError",
        "BridgeSideBindingError", "BridgeSideExecutionError", "CompatDecodeError", "CompatError",
        "CompatJsonError", "CompatSchemaHashMismatchError",
        "CompatSchemaMissingError", "CompatSchemaNotAFileError", "CompatSchemaReadError",
        "CompatSchemaRootError", "CompatSchemaValidationError", "CompatTopLevelTypeError",
        "CompatUnsupportedVersionError"]
    assert len(names) == 38
    for name in names:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(compat_mod, name)


_CONCRETE_ERRORS = (
    "CompatUnsupportedVersionError", "CompatSchemaRootError", "CompatSchemaMissingError",
    "CompatSchemaNotAFileError", "CompatSchemaReadError", "CompatSchemaHashMismatchError",
    "CompatDecodeError", "CompatJsonError", "CompatTopLevelTypeError", "CompatSchemaValidationError",
    "BridgeRequestError", "BridgeSideBindingError", "BridgeMetadataError",
    "BridgeSideExecutionError", "BridgePartialFailureError",
)


def test_exception_hierarchy():
    assert CompatError.__bases__ == (Exception,)
    for name in _CONCRETE_ERRORS:
        assert issubclass(getattr(compat_mod, name), CompatError)


def test_no_direct_base_error_raise():
    import ast
    tree = ast.parse((ROOT / "src" / "dynamic_ai_products" / "evaluation" / "compat.py").read_text())
    offenders = [n.lineno for n in ast.walk(tree)
                 if isinstance(n, ast.Raise) and n.exc is not None
                 and isinstance(n.exc.func if isinstance(n.exc, ast.Call) else n.exc, ast.Name)
                 and (n.exc.func if isinstance(n.exc, ast.Call) else n.exc).id == "CompatError"]
    assert offenders == []


def test_private_not_exported():
    for name in ("_FrozenMap", "_freeze_json", "_HISTORICAL_ROUTES", "_bind_side", "_build_bundle",
                 "_BRIDGE_ROLE", "_CompatStrictModel"):
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
        "import dynamic_ai_products.evaluation.compat\n"
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open=orb,ort,omk,oop\nhashlib.sha256=osha\n"
        "bad=[p for p in reads if p.endswith('.json') or p.endswith('.jsonl') or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad and not writes and not sha, (bad, writes, len(sha))\nprint('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr


def test_protected_slice_1_11_hashes_unchanged():
    from dynamic_ai_products.evaluation import models as mod
    from dynamic_ai_products.evaluation.comparator import AssertionComparisonMetadata
    from dynamic_ai_products.evaluation.envelopes import PredictionArtifactManifest
    from dynamic_ai_products.evaluation.metrics import MetricReport
    exp = {
        ("EvaluationRunManifest", "evaluation_run_manifest"): "7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee",
        ("ValidatorFinding", "validator_finding"): "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292",
        ("AssertionOutcome", "assertion_outcome"): "4af3a9eb7c99e3e3ba088784b3395f4b6920fa1f8061f7bb1118af6bd2720bd6",
    }
    for (name, cid), h in exp.items():
        assert model_contract_hash(getattr(mod, name), cid, "0.1.0") == h
    assert model_contract_hash(MetricReport, "metric_report", "0.1.0") \
        == "d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39"
    assert model_contract_hash(PredictionArtifactManifest, "prediction_artifact_manifest", "0.1.0") \
        == "4b164aea18fc99f9518854aca0fb98587eb71d81c972a477d48cb815ddc0dbe4"
    assert model_contract_hash(AssertionComparisonMetadata, "assertion_comparison_metadata", "0.1.0") \
        == "6d1734afc9df3ae3d9fac1d4a5706a75e944a3b4afbbe785644afa251c67e3c4"
    # ComparisonManifest is now the current v0.2 model.
    assert model_contract_hash(ComparisonManifest, "comparison_manifest", "0.2.0") \
        == "6a1253b72664bff73e872d1230fb3d52772a438f55915406010e105b4f5d29a5"
    # The historical comparison_manifest@0.1.0 identity is preserved as a governed
    # constant (the renamed V1 shape model's generated hash is NOT this value).
    assert comparator_mod._COMPARISON_MANIFEST_V1_CONTRACT_HASH \
        == "ef1508e4e2ed06c1cbcaafaf3d30bb9cc6c88e72d1df0bf001c7315e5afb94f4"
    assert model_contract_hash(comparator_mod.ComparisonManifestV1, "comparison_manifest", "0.1.0") \
        != "ef1508e4e2ed06c1cbcaafaf3d30bb9cc6c88e72d1df0bf001c7315e5afb94f4"
