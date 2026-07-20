"""Slice 7: assertion evaluation dispatch, identity checks, persistence.

The pure ``evaluate_case_assertions`` dispatcher is exercised with in-memory
models; persistence and loading round-trips run under ``tmp_path`` using an
initialized Slice 5 run directory. No metric, gate, verdict, execution-status,
or source-content behavior is exercised — Slice 7 copies the caller-supplied
four-value outcome for resolved assertions and emits ``not_evaluated`` with the
supplied finding for unresolved ones.

Bound-case memberships are taken from the authoritative ``CaseSetManifest``
entries: the manifest is the membership record, and a supplied membership must
equal its manifest entry as a complete object.
"""

import os
import subprocess
import sys
import typing
from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import assertions as asrt_mod
from dynamic_ai_products.evaluation import references as refs_mod
from dynamic_ai_products.evaluation.assertions import (
    AssertionArtifactMissingError,
    AssertionArtifactNotAFileError,
    AssertionBoundCaseError,
    AssertionCaseSetBindingError,
    AssertionDecodeError,
    AssertionDispatchBindingError,
    AssertionEnvelopeMatchError,
    AssertionEvaluationError,
    AssertionJsonError,
    AssertionModelValidationError,
    AssertionOutcomeExistsError,
    AssertionRunBindingError,
    AssertionTopLevelTypeError,
    AssertionWriteError,
    BoundEvaluationCase,
    DuplicateAssertionDispatchError,
    DuplicateAssertionIdError,
    DuplicateAssertionOutcomeError,
    EvaluatedCaseAssertions,
    LoadedAssertionOutcomes,
    MissingAssertionDispatchError,
    PersistedAssertionOutcomes,
    ResolvedAssertionDispatch,
    ResolvedAssertionEvaluation,
    UnexpectedAssertionDispatchError,
    UnresolvedAssertionDispatch,
    evaluate_case_assertions,
    load_assertion_outcomes,
    persist_assertion_outcomes,
)
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.cases import InvalidEvaluationRootError
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.models import (
    AssertionOutcome,
    AssertionSpec,
    EvaluationCase,
    PredictionEnvelope,
)
from dynamic_ai_products.evaluation.references import (
    ResolutionFinding,
    ResolvedAssertionReferences,
    load_target_registry,
)
from dynamic_ai_products.evaluation.runs import (
    RunArtifactNotAFileError,
    initialize_evaluation_run,
    load_evaluation_run_manifest,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"

SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FX / "case_sets")

# Authoritative membership record, keyed by case ID.
MEMBERSHIPS = {entry.case_id: entry for entry in CASE_SET.entries}
CID1, CID2, CID3 = "SYNTH-CASE-0001", "SYNTH-CASE-0002", "SYNTH-CASE-0003"

ENV_HASH = model_contract_hash(PredictionEnvelope, "prediction_envelope", "0.1.0")
OUT_HASH = model_contract_hash(AssertionOutcome, "assertion_outcome", "0.1.0")

STAGE = "task_extraction"
IPH1 = MEMBERSHIPS[CID1].input_packet_hash


# --- Factories ------------------------------------------------------------


def spec(aid, *, kind="expected_entity", sv="0.1.0", ch=None):
    data = {
        "assertion_id": aid,
        "kind": kind,
        "target_references": ["SYNTH.T"],
        "scoring_gate_config_references": ["synth-scoring-ref"],
    }
    if sv is not None:
        data["semantic_version"] = sv
    if ch is not None:
        data["contract_hash"] = ch
    return AssertionSpec.model_validate(data)


def case(cid, assertions, *, stage=STAGE):
    return EvaluationCase.model_validate(
        {
            "case_id": cid,
            "stage": stage,
            "stage_context": {},
            "input_source_ids": ["synth-source-0001"],
            "input_passage_ids": ["synth-passage-0001"],
            "assertions": [a.model_dump(exclude_unset=True) for a in assertions],
            "failure_tags": [],
            "notes": "synthetic",
            "created_by": "synthetic-researcher",
            "created_at": "2026-07-19T00:00:00Z",
            "guideline_version": "draft-v0.1",
        }
    )


def bound(c, m):
    return BoundEvaluationCase(case=c, membership=m)


def full_bound(case0001, *, membership0001=None):
    """Complete bound collection using the authoritative manifest memberships."""
    return (
        bound(case0001, membership0001 or MEMBERSHIPS[CID1]),
        bound(case(CID2, [spec(f"{CID2}-A1")]), MEMBERSHIPS[CID2]),
        bound(case(CID3, [spec(f"{CID3}-A1")]), MEMBERSHIPS[CID3]),
    )


def envelope(rid="SYNTH-PRED-0001", *, iph=IPH1, stage=STAGE):
    return PredictionEnvelope.model_validate(
        {
            "contract": {
                "contract_id": "prediction_envelope",
                "contract_version": "0.1.0",
                "contract_hash": ENV_HASH,
            },
            "prediction_record_id": rid,
            "stage": stage,
            "source_references": ["sources/s.json"],
            "prompt_model_metadata": {"m": "v"},
            "input_packet_hash": iph,
            "prediction_run_manifest_reference": "m.json",
        }
    )


def resolved(cid, aid, *, kind="expected_entity", sv="0.1.0", ch=None, outcome="satisfied",
             eval_aid=None):
    resref = ResolvedAssertionReferences(
        assertion_id=aid,
        assertion_semantic_version=sv,
        assertion_contract_hash=ch,
        target_references=(),
        scoring_references=(),
    )
    ev = ResolvedAssertionEvaluation(
        case_id=cid,
        assertion_id=eval_aid if eval_aid is not None else aid,
        assertion_semantic_version=sv,
        assertion_contract_hash=ch,
        kind=kind,
        outcome=outcome,
    )
    return ResolvedAssertionDispatch(status="resolved", resolution=resref, evaluation=ev)


def unresolved(cid, aid, *, failure_kind="registry_artifact_missing"):
    finding = ResolutionFinding(
        failure_kind=failure_kind, rule_id="R1", message="unresolved", case_id=cid, assertion_id=aid
    )
    return UnresolvedAssertionDispatch(status="unresolved", finding=finding)


def init_run(eval_root, run_id="run1", *, case_set=CASE_SET):
    return initialize_evaluation_run(
        eval_root=eval_root,
        eval_run_id=run_id,
        prediction_run_id="SYNTH-PRED-RUN-0001",
        prediction_run_manifest_hash="a" * 64,
        case_set=case_set,
        registry=REGISTRY,
        validator_bundle_version="vb",
        validator_bundle_hash="b" * 64,
        scoring_config=SCORING,
        code_commit="c",
        config_snapshot_source_root=FX / "configs",
    )


@pytest.fixture
def loaded_run(tmp_path):
    init_run(tmp_path)
    return load_evaluation_run_manifest("run1", eval_root=tmp_path)


# --- Pure evaluation: happy paths -----------------------------------------


def test_resolved_outcome_is_copied(loaded_run):
    c1 = case(CID1, [spec("A1")])
    result = evaluate_case_assertions(
        full_bound(c1),
        case_set=CASE_SET,
        run_manifest=loaded_run,
        envelope=envelope(),
        assertion_dispatches=(resolved(CID1, "A1", outcome="unsatisfied"),),
    )
    assert isinstance(result, EvaluatedCaseAssertions)
    assert result.eval_run_id == "run1"
    assert result.case_id == CID1
    assert result.prediction_record_id == "SYNTH-PRED-0001"
    assert len(result.outcomes) == 1
    o = result.outcomes[0]
    assert o.outcome == "unsatisfied"
    assert o.eval_run_id == "run1"
    assert o.case_id == CID1
    assert o.assertion_id == "A1"
    assert o.assertion_semantic_version == "0.1.0"
    assert o.assertion_contract_hash is None
    assert o.contract.contract_hash == OUT_HASH
    assert result.resolution_findings == ()


@pytest.mark.parametrize("value", ["satisfied", "unsatisfied", "indeterminate", "not_applicable"])
def test_all_four_resolved_values_pass_through(loaded_run, value):
    c1 = case(CID1, [spec("A1")])
    result = evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
        assertion_dispatches=(resolved(CID1, "A1", outcome=value),),
    )
    assert result.outcomes[0].outcome == value


def test_unresolved_yields_not_evaluated_and_returns_finding(loaded_run):
    c1 = case(CID1, [spec("A1")])
    result = evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
        assertion_dispatches=(unresolved(CID1, "A1"),),
    )
    assert result.outcomes[0].outcome == "not_evaluated"
    assert len(result.resolution_findings) == 1
    assert result.resolution_findings[0].assertion_id == "A1"


def test_all_five_kinds_covered(loaded_run):
    kinds = [
        "expected_entity", "forbidden_entity", "field_value",
        "evidence_provenance", "deterministic_validation",
    ]
    specs = [spec(f"A{i}", kind=k) for i, k in enumerate(kinds)]
    c1 = case(CID1, specs)
    dispatches = tuple(
        resolved(CID1, f"A{i}", kind=k, outcome="satisfied") for i, k in enumerate(kinds)
    )
    result = evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run,
        envelope=envelope(), assertion_dispatches=dispatches,
    )
    assert len(result.outcomes) == 5
    assert {o.outcome for o in result.outcomes} == {"satisfied"}


def test_mixed_resolved_and_unresolved(loaded_run):
    c1 = case(CID1, [spec("A1"), spec("A2")])
    result = evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
        assertion_dispatches=(
            resolved(CID1, "A1", outcome="satisfied"),
            unresolved(CID1, "A2"),
        ),
    )
    assert {o.assertion_id: o.outcome for o in result.outcomes} == {
        "A1": "satisfied", "A2": "not_evaluated"
    }
    assert len(result.resolution_findings) == 1


def test_outcome_order_follows_case_assertion_order(loaded_run):
    c1 = case(CID1, [spec("A3"), spec("A1"), spec("A2")])
    result = evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
        assertion_dispatches=(
            resolved(CID1, "A1"), resolved(CID1, "A2"), resolved(CID1, "A3"),
        ),
    )
    assert [o.assertion_id for o in result.outcomes] == ["A3", "A1", "A2"]


def test_resolved_identity_none_semantic_version_omitted(loaded_run):
    c1 = case(CID1, [spec("A1", sv=None, ch="e" * 64)])
    result = evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
        assertion_dispatches=(resolved(CID1, "A1", sv=None, ch="e" * 64),),
    )
    o = result.outcomes[0]
    assert o.assertion_contract_hash == "e" * 64
    assert "assertion_semantic_version" not in o.model_fields_set


# --- Pure evaluation: case-set binding ------------------------------------


def test_case_set_version_mismatch(loaded_run):
    bad = CASE_SET.model_copy(update={"case_set_version": "different"})
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionCaseSetBindingError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=bad, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "case_set_version_mismatch"


def test_case_set_hash_mismatch(loaded_run):
    tampered = CASE_SET.model_copy(update={"registry_snapshot_version": "tampered-v9"})
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionCaseSetBindingError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=tampered, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "case_set_hash_mismatch"


# --- Defect 1: authoritative membership binding ---------------------------


def test_membership_packet_hash_tamper_rejected(loaded_run):
    """Case ID unchanged, packet hash altered -> rejected against the manifest."""
    tampered = MEMBERSHIPS[CID1].model_copy(update={"input_packet_hash": "9" * 64})
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionBoundCaseError) as exc:
        evaluate_case_assertions(
            full_bound(c1, membership0001=tampered), case_set=CASE_SET,
            run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "bound_case_collection_mismatch"
    assert exc.value.case_id == CID1


def test_membership_partition_tamper_rejected(loaded_run):
    assert MEMBERSHIPS[CID1].partition == "dev"
    tampered = MEMBERSHIPS[CID1].model_copy(update={"partition": "frozen_test"})
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionBoundCaseError) as exc:
        evaluate_case_assertions(
            full_bound(c1, membership0001=tampered), case_set=CASE_SET,
            run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "bound_case_collection_mismatch"


def test_membership_suites_tamper_rejected(loaded_run):
    assert MEMBERSHIPS[CID1].suites == ("adversarial", "regression")
    tampered = MEMBERSHIPS[CID1].model_copy(update={"suites": ("adversarial",)})
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionBoundCaseError) as exc:
        evaluate_case_assertions(
            full_bound(c1, membership0001=tampered), case_set=CASE_SET,
            run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "bound_case_collection_mismatch"


def test_authoritative_membership_accepted(loaded_run):
    """The untampered manifest membership binds successfully."""
    c1 = case(CID1, [spec("A1")])
    result = evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
        assertion_dispatches=(resolved(CID1, "A1"),),
    )
    assert result.case_id == CID1


# --- Pure evaluation: bound-collection integrity --------------------------


def test_bound_case_id_membership_mismatch(loaded_run):
    c1 = case(CID1, [spec("A1")])
    bad = (
        bound(c1, MEMBERSHIPS[CID2]),  # membership case ID != case case ID
        bound(case(CID2, [spec("X")]), MEMBERSHIPS[CID2]),
        bound(case(CID3, [spec("Y")]), MEMBERSHIPS[CID3]),
    )
    with pytest.raises(AssertionBoundCaseError) as exc:
        evaluate_case_assertions(
            bad, case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "membership_case_id_mismatch"


def test_incomplete_bound_collection(loaded_run):
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionBoundCaseError) as exc:
        evaluate_case_assertions(
            (bound(c1, MEMBERSHIPS[CID1]),), case_set=CASE_SET, run_manifest=loaded_run,
            envelope=envelope(), assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "bound_case_collection_mismatch"


def test_duplicate_bound_case(loaded_run):
    c1 = case(CID1, [spec("A1")])
    dup = full_bound(c1) + (bound(c1, MEMBERSHIPS[CID1]),)
    with pytest.raises(AssertionBoundCaseError) as exc:
        evaluate_case_assertions(
            dup, case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "bound_case_collection_mismatch"


def test_duplicate_assertion_id_in_case(loaded_run):
    c1 = case(CID1, [spec("A1"), spec("A1")])
    with pytest.raises(DuplicateAssertionIdError):
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )


# --- Pure evaluation: envelope matching -----------------------------------


def test_no_package_case_match(loaded_run):
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionEnvelopeMatchError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run,
            envelope=envelope(iph="9" * 64), assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "no_package_case_match"
    assert exc.value.match_count == 0


def test_stage_mismatch_is_no_match(loaded_run):
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionEnvelopeMatchError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run,
            envelope=envelope(stage="other_stage"),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "no_package_case_match"


def test_ambiguous_package_case_match(tmp_path):
    """A case set that legitimately pins two cases to one packet hash is ambiguous."""
    colliding_entries = (
        MEMBERSHIPS[CID1],
        MEMBERSHIPS[CID2].model_copy(update={"input_packet_hash": IPH1}),
        MEMBERSHIPS[CID3],
    )
    colliding = CASE_SET.model_copy(update={"entries": colliding_entries})
    init_run(tmp_path, "run1", case_set=colliding)
    run = load_evaluation_run_manifest("run1", eval_root=tmp_path)
    c1 = case(CID1, [spec("A1")])
    bounds = (
        bound(c1, colliding_entries[0]),
        bound(case(CID2, [spec("B1")]), colliding_entries[1]),
        bound(case(CID3, [spec("Y")]), colliding_entries[2]),
    )
    with pytest.raises(AssertionEnvelopeMatchError) as exc:
        evaluate_case_assertions(
            bounds, case_set=colliding, run_manifest=run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )
    assert exc.value.binding_kind == "ambiguous_package_case_match"
    assert exc.value.match_count == 2


# --- Defect 2: dispatch identity binding kinds ----------------------------


def test_missing_dispatch(loaded_run):
    c1 = case(CID1, [spec("A1"), spec("A2")])
    with pytest.raises(MissingAssertionDispatchError):
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"),),
        )


def test_resolution_assertion_id_mismatch(loaded_run):
    """Resolver identity does not target any assertion of the matched case."""
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(UnexpectedAssertionDispatchError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "GHOST", eval_aid="GHOST"),),
        )
    assert exc.value.binding_kind == "resolution_assertion_id_mismatch"
    assert exc.value.assertion_id == "GHOST"


def test_evaluation_assertion_id_mismatch(loaded_run):
    """Resolver targets a real assertion; the evaluation targets a different one."""
    c1 = case(CID1, [spec("A1"), spec("A2")])
    with pytest.raises(AssertionDispatchBindingError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(
                resolved(CID1, "A1", eval_aid="A2"),
                resolved(CID1, "A2"),
            ),
        )
    assert exc.value.binding_kind == "evaluation_assertion_id_mismatch"
    assert exc.value.assertion_id == "A2"


def test_finding_assertion_id_mismatch(loaded_run):
    """Unresolved finding does not target any assertion of the matched case."""
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(UnexpectedAssertionDispatchError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(unresolved(CID1, "GHOST"),),
        )
    assert exc.value.binding_kind == "finding_assertion_id_mismatch"
    assert exc.value.assertion_id == "GHOST"


def test_duplicate_dispatch(loaded_run):
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(DuplicateAssertionDispatchError):
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1"), resolved(CID1, "A1")),
        )


def test_resolved_evaluation_case_id_mismatch(loaded_run):
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionDispatchBindingError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved("SYNTH-CASE-9999", "A1"),),
        )
    assert exc.value.binding_kind == "evaluation_case_id_mismatch"


def test_resolved_semantic_version_mismatch(loaded_run):
    c1 = case(CID1, [spec("A1", sv="0.1.0")])
    with pytest.raises(AssertionDispatchBindingError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1", sv="0.2.0"),),
        )
    assert exc.value.binding_kind == "evaluation_semantic_version_mismatch"


def test_resolved_contract_hash_mismatch(loaded_run):
    c1 = case(CID1, [spec("A1", sv="0.1.0", ch="a" * 64)])
    with pytest.raises(AssertionDispatchBindingError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1", sv="0.1.0", ch="f" * 64),),
        )
    assert exc.value.binding_kind == "evaluation_contract_hash_mismatch"


def test_resolved_kind_mismatch(loaded_run):
    c1 = case(CID1, [spec("A1", kind="expected_entity")])
    with pytest.raises(AssertionDispatchBindingError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(resolved(CID1, "A1", kind="forbidden_entity"),),
        )
    assert exc.value.binding_kind == "evaluation_kind_mismatch"


def test_unresolved_finding_case_id_mismatch(loaded_run):
    c1 = case(CID1, [spec("A1")])
    with pytest.raises(AssertionDispatchBindingError) as exc:
        evaluate_case_assertions(
            full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
            assertion_dispatches=(unresolved("SYNTH-CASE-9999", "A1"),),
        )
    assert exc.value.binding_kind == "finding_case_id_mismatch"


# --- BindingKind reachability audit ---------------------------------------


def test_binding_kind_has_exactly_15_values():
    values = typing.get_args(asrt_mod.BindingKind)
    assert len(values) == 15
    assert len(set(values)) == 15
    # The withdrawn resolver-case-ID literal must not return; it is constructed
    # here rather than written out so the retired name appears nowhere verbatim.
    withdrawn = "_".join(("resolution", "case", "id", "mismatch"))
    assert withdrawn not in values


def test_every_binding_kind_literal_is_emitted_in_source():
    """Each declared literal must be emitted by a real raise site."""
    source = Path(asrt_mod.__file__).read_text(encoding="utf-8")
    # Strip the literal declaration block so only raise sites remain.
    start = source.index("BindingKind = Literal[")
    end = source.index("]", start)
    body = source[:start] + source[end:]
    for value in typing.get_args(asrt_mod.BindingKind):
        assert f'binding_kind="{value}"' in body, f"unreachable binding kind: {value}"


def test_persistence_binding_kind_emitted(loaded_run, tmp_path):
    with pytest.raises(AssertionRunBindingError) as exc:
        persist_assertion_outcomes(
            (outcome_obj(eval_run_id="nope"),), eval_root=tmp_path, eval_run_id="run1"
        )
    assert exc.value.binding_kind == "outcome_run_id_mismatch"


# --- Persistence round-trip -----------------------------------------------


def outcomes_for(loaded_run):
    c1 = case(CID1, [spec("A1"), spec("A2")])
    return evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
        assertion_dispatches=(
            resolved(CID1, "A1", outcome="satisfied"), unresolved(CID1, "A2"),
        ),
    ).outcomes


def outcome_obj(eval_run_id="run1", case_id=CID1, assertion_id="A1", outcome="satisfied"):
    return AssertionOutcome.model_validate(
        {
            "contract": {
                "contract_id": "assertion_outcome",
                "contract_version": "0.1.0",
                "contract_hash": OUT_HASH,
            },
            "eval_run_id": eval_run_id,
            "case_id": case_id,
            "assertion_id": assertion_id,
            "assertion_semantic_version": "0.1.0",
            "outcome": outcome,
        }
    )


def test_persist_and_load_roundtrip(loaded_run, tmp_path):
    outs = outcomes_for(loaded_run)
    persisted = persist_assertion_outcomes(outs, eval_root=tmp_path, eval_run_id="run1")
    assert isinstance(persisted, PersistedAssertionOutcomes)
    assert persisted.artifact_reference == "run1/assertions/assertion_outcomes.jsonl"
    dest = tmp_path / "run1" / "assertions" / "assertion_outcomes.jsonl"
    assert dest.is_file()
    assert sha256_bytes(dest.read_bytes()) == persisted.sha256

    loaded = load_assertion_outcomes("run1", eval_root=tmp_path)
    assert isinstance(loaded, LoadedAssertionOutcomes)
    assert loaded.sha256 == persisted.sha256
    assert tuple(o.model_dump() for o in loaded.outcomes) == tuple(o.model_dump() for o in outs)


def test_persist_is_write_once(loaded_run, tmp_path):
    outs = outcomes_for(loaded_run)
    persist_assertion_outcomes(outs, eval_root=tmp_path, eval_run_id="run1")
    with pytest.raises(AssertionOutcomeExistsError):
        persist_assertion_outcomes(outs, eval_root=tmp_path, eval_run_id="run1")


def test_persist_empty_outcomes(loaded_run, tmp_path):
    persisted = persist_assertion_outcomes((), eval_root=tmp_path, eval_run_id="run1")
    dest = tmp_path / "run1" / "assertions" / "assertion_outcomes.jsonl"
    assert dest.read_bytes() == b""
    assert persisted.sha256 == sha256_bytes(b"")
    assert load_assertion_outcomes("run1", eval_root=tmp_path).outcomes == ()


def test_persist_rejects_run_id_mismatch(loaded_run, tmp_path):
    with pytest.raises(AssertionRunBindingError):
        persist_assertion_outcomes(
            (outcome_obj(eval_run_id="nope"),), eval_root=tmp_path, eval_run_id="run1"
        )


def test_persist_rejects_duplicate_identity(loaded_run, tmp_path):
    with pytest.raises(DuplicateAssertionOutcomeError):
        persist_assertion_outcomes(
            (outcome_obj(assertion_id="A1"), outcome_obj(assertion_id="A1")),
            eval_root=tmp_path, eval_run_id="run1",
        )


# --- Persistence collision rejection --------------------------------------


def test_persist_rejects_existing_regular_file_at_assertions(loaded_run, tmp_path):
    (tmp_path / "run1" / "assertions").write_bytes(b"occupied")
    with pytest.raises(AssertionOutcomeExistsError):
        persist_assertion_outcomes((), eval_root=tmp_path, eval_run_id="run1")
    assert (tmp_path / "run1" / "assertions").read_bytes() == b"occupied"


def test_persist_rejects_existing_directory(loaded_run, tmp_path):
    (tmp_path / "run1" / "assertions").mkdir()
    with pytest.raises(AssertionOutcomeExistsError):
        persist_assertion_outcomes((), eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_symlink(loaded_run, tmp_path):
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / "run1" / "assertions").symlink_to(target)
    with pytest.raises(AssertionOutcomeExistsError):
        persist_assertion_outcomes((), eval_root=tmp_path, eval_run_id="run1")
    assert not (target / "assertion_outcomes.jsonl").exists()


def test_persist_rejects_dangling_symlink(loaded_run, tmp_path):
    (tmp_path / "run1" / "assertions").symlink_to(tmp_path / "does-not-exist")
    with pytest.raises(AssertionOutcomeExistsError):
        persist_assertion_outcomes((), eval_root=tmp_path, eval_run_id="run1")
    assert not (tmp_path / "does-not-exist").exists()


def test_write_failure_after_directory_create_preserves_directory(
    loaded_run, tmp_path, monkeypatch
):
    """A post-mkdir write failure raises typed, leaves the dir, does not clean up."""
    def boom(*args, **kwargs):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(asrt_mod.os, "open", boom)
    with pytest.raises(AssertionWriteError):
        persist_assertion_outcomes(
            (outcome_obj(),), eval_root=tmp_path, eval_run_id="run1"
        )
    monkeypatch.undo()
    d = tmp_path / "run1" / "assertions"
    assert d.is_dir(), "the created assertions directory must be preserved"
    assert list(d.iterdir()) == [], "no partial, marker, or retry artifact may exist"
    # No append/retry: the refuse-to-overwrite guard now blocks a second attempt.
    with pytest.raises(AssertionOutcomeExistsError):
        persist_assertion_outcomes((outcome_obj(),), eval_root=tmp_path, eval_run_id="run1")


# --- Loader failure modes -------------------------------------------------


def write_outcomes_dir(tmp_path, data: bytes):
    d = tmp_path / "run1" / "assertions"
    d.mkdir(parents=True, exist_ok=False)
    (d / "assertion_outcomes.jsonl").write_bytes(data)


def test_load_missing_artifact(loaded_run, tmp_path):
    with pytest.raises(AssertionArtifactMissingError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_non_utf8(loaded_run, tmp_path):
    write_outcomes_dir(tmp_path, b"\xff\xfe not utf8")
    with pytest.raises(AssertionDecodeError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_utf8_bom(loaded_run, tmp_path):
    line = asrt_mod._canonical_outcome_line(outcome_obj()) + b"\n"
    write_outcomes_dir(tmp_path, b"\xef\xbb\xbf" + line)
    with pytest.raises(AssertionJsonError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_blank_line(loaded_run, tmp_path):
    line = asrt_mod._canonical_outcome_line(outcome_obj()) + b"\n"
    write_outcomes_dir(tmp_path, line + b"\n" + line)
    with pytest.raises(AssertionJsonError) as exc:
        load_assertion_outcomes("run1", eval_root=tmp_path)
    assert exc.value.line_number == 2


def test_load_rejects_trailing_non_json_data(loaded_run, tmp_path):
    line = asrt_mod._canonical_outcome_line(outcome_obj())
    write_outcomes_dir(tmp_path, line + b" trailing\n")
    with pytest.raises(AssertionJsonError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_bad_json(loaded_run, tmp_path):
    write_outcomes_dir(tmp_path, b"{not json}\n")
    with pytest.raises(AssertionJsonError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_non_object_line(loaded_run, tmp_path):
    write_outcomes_dir(tmp_path, b"[1,2,3]\n")
    with pytest.raises(AssertionTopLevelTypeError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_duplicate_keys(loaded_run, tmp_path):
    write_outcomes_dir(tmp_path, b'{"a":1,"a":2}\n')
    with pytest.raises(AssertionJsonError) as exc:
        load_assertion_outcomes("run1", eval_root=tmp_path)
    assert exc.value.duplicate_key == "a"


def test_load_rejects_nested_duplicate_keys(loaded_run, tmp_path):
    write_outcomes_dir(tmp_path, b'{"contract":{"nested":1,"nested":2}}\n')
    with pytest.raises(AssertionJsonError) as exc:
        load_assertion_outcomes("run1", eval_root=tmp_path)
    assert exc.value.duplicate_key == "nested"


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_load_rejects_non_finite_constants(loaded_run, tmp_path, constant):
    write_outcomes_dir(tmp_path, b'{"x":' + constant + b"}\n")
    with pytest.raises(AssertionJsonError) as exc:
        load_assertion_outcomes("run1", eval_root=tmp_path)
    assert exc.value.constant_name == constant.decode()


def test_load_rejects_model_invalid(loaded_run, tmp_path):
    write_outcomes_dir(tmp_path, b'{"unexpected":true}\n')
    with pytest.raises(AssertionModelValidationError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_run_id_mismatch(loaded_run, tmp_path):
    line = asrt_mod._canonical_outcome_line(outcome_obj(eval_run_id="other")) + b"\n"
    write_outcomes_dir(tmp_path, line)
    with pytest.raises(AssertionRunBindingError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_duplicate_identity(loaded_run, tmp_path):
    line = asrt_mod._canonical_outcome_line(outcome_obj()) + b"\n"
    write_outcomes_dir(tmp_path, line + line)
    with pytest.raises(DuplicateAssertionOutcomeError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_artifact(loaded_run, tmp_path):
    d = tmp_path / "run1" / "assertions"
    d.mkdir(parents=True, exist_ok=False)
    target = tmp_path / "outside.jsonl"
    target.write_bytes(b"")
    (d / "assertion_outcomes.jsonl").symlink_to(target)
    with pytest.raises(AssertionArtifactNotAFileError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_assertions_directory(loaded_run, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "assertion_outcomes.jsonl").write_bytes(b"")
    (tmp_path / "run1" / "assertions").symlink_to(outside)
    with pytest.raises(AssertionArtifactNotAFileError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_run_directory(tmp_path):
    """A symlinked run directory is refused by the Slice 5 manifest loader."""
    real = tmp_path / "real"
    real.mkdir()
    init_run(real, "run1")
    (tmp_path / "run1").symlink_to(real / "run1")
    with pytest.raises(RunArtifactNotAFileError):
        load_assertion_outcomes("run1", eval_root=tmp_path)


def test_repeated_loads_are_equal_but_distinct_objects(loaded_run, tmp_path):
    persist_assertion_outcomes(outcomes_for(loaded_run), eval_root=tmp_path, eval_run_id="run1")
    first = load_assertion_outcomes("run1", eval_root=tmp_path)
    second = load_assertion_outcomes("run1", eval_root=tmp_path)
    assert first is not second
    assert first.outcomes[0] is not second.outcomes[0]
    assert first.sha256 == second.sha256
    assert [o.model_dump() for o in first.outcomes] == [o.model_dump() for o in second.outcomes]


def test_invalid_eval_root_rejected():
    with pytest.raises(InvalidEvaluationRootError):
        load_assertion_outcomes("run1", eval_root="")


# --- Pure-function boundary -----------------------------------------------


def test_evaluate_case_assertions_touches_no_filesystem_and_no_resolver(
    loaded_run, monkeypatch
):
    """The dispatcher is pure: no I/O, no Slice 4 resolver, no source reads."""
    calls = []

    def spy(name, original):
        def wrapper(*args, **kwargs):
            calls.append(name)
            return original(*args, **kwargs)
        return wrapper

    monkeypatch.setattr(Path, "read_bytes", spy("read_bytes", Path.read_bytes))
    monkeypatch.setattr(Path, "read_text", spy("read_text", Path.read_text))
    monkeypatch.setattr(Path, "write_bytes", spy("write_bytes", Path.write_bytes))
    monkeypatch.setattr(Path, "mkdir", spy("mkdir", Path.mkdir))
    monkeypatch.setattr(Path, "open", spy("open", Path.open))
    monkeypatch.setattr(os, "open", spy("os.open", os.open))

    def forbidden_resolver(*args, **kwargs):
        raise AssertionError("evaluate_case_assertions must not call the Slice 4 resolver")

    monkeypatch.setattr(refs_mod, "resolve_case_references", forbidden_resolver)
    monkeypatch.setattr(asrt_mod, "resolve_case_references", forbidden_resolver, raising=False)

    env = envelope()
    c1 = case(CID1, [spec("A1"), spec("A2")])
    result = evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=env,
        assertion_dispatches=(resolved(CID1, "A1"), unresolved(CID1, "A2")),
    )

    assert calls == [], f"pure dispatcher performed filesystem calls: {calls}"
    # No prediction source content was read: only the envelope's own fields are used.
    assert env.source_references == ("sources/s.json",)
    # No execution status, gate verdict, or validator-finding artifact is produced.
    fields = set(type(result).model_fields)
    assert fields == {
        "eval_run_id", "case_id", "prediction_record_id", "outcomes", "resolution_findings"
    }
    assert not hasattr(result, "execution_status")
    assert not hasattr(result, "gate_verdict")
    for finding in result.resolution_findings:
        assert isinstance(finding, ResolutionFinding)
        assert not isinstance(finding, evaluation_pkg.ValidatorFinding)


def test_evaluate_case_assertions_writes_nothing_to_disk(loaded_run, tmp_path):
    before = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    c1 = case(CID1, [spec("A1")])
    evaluate_case_assertions(
        full_bound(c1), case_set=CASE_SET, run_manifest=loaded_run, envelope=envelope(),
        assertion_dispatches=(resolved(CID1, "A1"),),
    )
    after = sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob("*"))
    assert before == after


# --- Exceptions, exports, import hygiene -----------------------------------

PUBLIC_FUNCTIONS = (
    "evaluate_case_assertions", "persist_assertion_outcomes", "load_assertion_outcomes",
)
PUBLIC_MODELS = (
    "BoundEvaluationCase", "ResolvedAssertionEvaluation", "ResolvedAssertionDispatch",
    "UnresolvedAssertionDispatch", "AssertionDispatchInput", "EvaluatedCaseAssertions",
    "PersistedAssertionOutcomes", "LoadedAssertionOutcomes",
)
PUBLIC_EXCEPTIONS = (
    "AssertionEvaluationError", "AssertionCaseSetBindingError", "AssertionBoundCaseError",
    "AssertionEnvelopeMatchError", "DuplicateAssertionIdError", "AssertionDispatchBindingError",
    "DuplicateAssertionDispatchError", "MissingAssertionDispatchError",
    "UnexpectedAssertionDispatchError", "UnsupportedAssertionKindError",
    "AssertionOutcomeExistsError", "AssertionPathEscapeError", "AssertionArtifactMissingError",
    "AssertionArtifactNotAFileError", "AssertionArtifactReadError", "AssertionDecodeError",
    "AssertionJsonError", "AssertionTopLevelTypeError", "AssertionModelValidationError",
    "DuplicateAssertionOutcomeError", "AssertionRunBindingError", "AssertionWriteError",
    "AssertionDestinationHashMismatchError",
)
PUBLIC_ALIASES = ("ResolvedAssertionOutcome", "BindingKind")


def test_public_symbols_exported():
    for name in PUBLIC_FUNCTIONS + PUBLIC_MODELS + PUBLIC_EXCEPTIONS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(asrt_mod, name)


def test_public_aliases_exported():
    for name in PUBLIC_ALIASES:
        assert name in evaluation_pkg.__all__
        assert hasattr(evaluation_pkg, name)
        assert getattr(evaluation_pkg, name) is getattr(asrt_mod, name)


def test_exception_hierarchy():
    for name in PUBLIC_EXCEPTIONS:
        cls = getattr(asrt_mod, name)
        if name == "AssertionEvaluationError":
            assert cls.__bases__ == (Exception,)
        else:
            assert issubclass(cls, AssertionEvaluationError)


def test_reused_root_error_is_invalid_evaluation_root():
    assert asrt_mod.InvalidEvaluationRootError is InvalidEvaluationRootError


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
        "import dynamic_ai_products.evaluation.assertions\n"
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open=orb,ort,omk,oop\nhashlib.sha256=osha\n"
        "bad=[p for p in reads if p.endswith('.json') or p.endswith('.jsonl') or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad and not writes and not sha, (bad, writes, len(sha))\nprint('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
