"""Slice 8: deterministic validator findings.

The pure ``evaluate_validator_findings`` dispatcher is exercised with in-memory
models; findings persistence and loading run under ``tmp_path`` using an
initialized Slice 5 run directory. Slice 8 assigns no execution status, gate
verdict or metric; severity and repairability come only from the bundle.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import validators as val_mod
from dynamic_ai_products.evaluation.cases import InvalidEvaluationRootError
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.models import ValidatorFinding
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import (
    RunArtifactNotAFileError,
    initialize_evaluation_run,
    load_evaluation_run_manifest,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.evaluation.validators import (
    DuplicateValidatorFindingError,
    LoadedValidatorFindings,
    PersistedValidatorFindings,
    SnapshotRunBindingError,
    VALIDATOR_RULE_ORDER,
    ValidationArtifactSnapshot,
    ValidatorArtifactMissingError,
    ValidatorArtifactNotAFileError,
    ValidatorBundle,
    ValidatorBundleBindingError,
    ValidatorDecodeError,
    ValidatorFindingRunBindingError,
    ValidatorFindingsExistError,
    ValidatorJsonError,
    ValidatorModelValidationError,
    ValidatorRuleConfig,
    ValidatorTopLevelTypeError,
    ValidatorWriteError,
    evaluate_validator_findings,
    load_validator_findings,
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


# --- Bundle helpers -------------------------------------------------------


def bundle(*, severities=None, repairable=None, params=None, version="vb-1"):
    sev = severities or {}
    rep = repairable or {}
    prm = params or {}
    rules = tuple(
        ValidatorRuleConfig(
            rule_id=rid,
            severity=sev.get(rid, "error"),
            rule_params_hash=prm.get(rid, HEX),
            repairable=rep.get(rid, False),
        )
        for rid in VALIDATOR_RULE_ORDER
    )
    return ValidatorBundle(bundle_version=version, rules=rules)


def init_run(eval_root, run_id="run1", *, bundle_version="vb-1", bundle_hash=None):
    if bundle_hash is None:
        bundle_hash = validator_bundle_hash(bundle(version=bundle_version))
    return initialize_evaluation_run(
        eval_root=eval_root, eval_run_id=run_id, prediction_run_id="P",
        prediction_run_manifest_hash="a" * 64, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version=bundle_version, validator_bundle_hash=bundle_hash,
        scoring_config=SCORING, code_commit="c", config_snapshot_source_root=FX / "configs",
    )


@pytest.fixture
def run_manifest(tmp_path):
    init_run(tmp_path)
    return load_evaluation_run_manifest("run1", eval_root=tmp_path).manifest


# --- Observation factories: passing baseline + failing overrides ----------


def _passing_observations():
    return {
        "output_json_schema_validity": {
            "rule_id": "output_json_schema_validity", "observation_id": "o1",
            "parse_succeeded": True, "schema_valid": True, "schema_reference": "s.json",
            "validation_errors": (),
        },
        "required_field_presence": {
            "rule_id": "required_field_presence", "observation_id": "o2",
            "required_fields": ("a", "b"), "present_fields": ("a", "b", "c"),
        },
        "source_id_resolution": {
            "rule_id": "source_id_resolution", "observation_id": "o3",
            "referenced_source_ids": ("s1",), "available_source_ids": ("s1", "s2"),
        },
        "passage_id_resolution": {
            "rule_id": "passage_id_resolution", "observation_id": "o4",
            "referenced_passage_ids": ("p1",), "available_passage_ids": ("p1",),
        },
        "evidence_quote_containment": {
            "rule_id": "evidence_quote_containment", "observation_id": "o5",
            "quote": "alpha", "passage_text": "the alpha beta", "passage_id": "p1",
        },
        "publication_date_cutoff": {
            "rule_id": "publication_date_cutoff", "observation_id": "o6",
            "publication_date": "2020-01-01", "observation_cutoff_date": "2020-06-01",
            "source_id": "s1",
        },
        "product_capability_task_parent_resolution": {
            "rule_id": "product_capability_task_parent_resolution", "observation_id": "o7",
            "child_id": "c1", "parent_id": "pp", "available_parent_ids": ("pp", "qq"),
        },
        "unique_ids_within_scope": {
            "rule_id": "unique_ids_within_scope", "observation_id": "o8",
            "scope_id": "sc", "record_ids": ("a", "b", "c"),
        },
        "prohibited_legacy_fields_absent": {
            "rule_id": "prohibited_legacy_fields_absent", "observation_id": "o9",
            "present_field_names": ("x", "y"), "prohibited_field_names": ("legacy",),
        },
        "active_record_non_roadmap_evidence": {
            "rule_id": "active_record_non_roadmap_evidence", "observation_id": "o10",
            "active": True,
            "evidence": (
                {"evidence_id": "e1", "is_future_roadmap": True},
                {"evidence_id": "e2", "is_future_roadmap": False},
            ),
        },
        "customer_task_outcome_and_evidence": {
            "rule_id": "customer_task_outcome_and_evidence", "observation_id": "o11",
            "is_customer_facing_task": True, "customer_outcome": "did the thing",
            "evidence_ids": ("e1",),
        },
        "raw_output_and_repair_preservation": {
            "rule_id": "raw_output_and_repair_preservation", "observation_id": "o12",
            "raw_output_reference": "raw.json", "repair_applied": True,
            "repair_record_references": ("repair-1",),
        },
    }


# One failing override per rule, keyed by rule_id.
_FAILING = {
    "output_json_schema_validity": {"parse_succeeded": True, "schema_valid": False},
    "required_field_presence": {"required_fields": ("a", "z"), "present_fields": ("a",)},
    "source_id_resolution": {"referenced_source_ids": ("missing",), "available_source_ids": ()},
    "passage_id_resolution": {"referenced_passage_ids": ("missing",), "available_passage_ids": ()},
    "evidence_quote_containment": {"quote": "zzz", "passage_text": "abc", "passage_id": "p1"},
    "publication_date_cutoff": {
        "publication_date": "2021-01-01", "observation_cutoff_date": "2020-06-01",
    },
    "product_capability_task_parent_resolution": {
        "parent_id": "absent", "available_parent_ids": ("pp",),
    },
    "unique_ids_within_scope": {"record_ids": ("a", "a", "b")},
    "prohibited_legacy_fields_absent": {
        "present_field_names": ("legacy", "x"), "prohibited_field_names": ("legacy",),
    },
    "active_record_non_roadmap_evidence": {
        "active": True, "evidence": ({"evidence_id": "e1", "is_future_roadmap": True},),
    },
    "customer_task_outcome_and_evidence": {
        "is_customer_facing_task": True, "customer_outcome": None, "evidence_ids": (),
    },
    "raw_output_and_repair_preservation": {
        "raw_output_reference": None, "repair_applied": True, "repair_record_references": (),
    },
}


def snapshot(*, failing=(), run_id="run1", artifact_id="art-1", case_id="SYNTH-CASE-0001",
             created_at=CREATED_AT, observations=None, entity_ids=None):
    if observations is None:
        base = _passing_observations()
        for rid in failing:
            base[rid] = {**base[rid], **_FAILING[rid]}
        if entity_ids:
            for rid, eid in entity_ids.items():
                base[rid] = {**base[rid], "entity_id": eid}
        observations = tuple(base[rid] for rid in VALIDATOR_RULE_ORDER)
    return ValidationArtifactSnapshot.model_validate(
        {
            "eval_run_id": run_id, "artifact_id": artifact_id, "artifact_sha256": "b" * 64,
            "created_at": created_at, "case_id": case_id, "observations": list(observations),
        }
    )


# --- Bundle contract ------------------------------------------------------


def test_bundle_exact_rule_set_and_order():
    b = bundle()
    assert tuple(r.rule_id for r in b.rules) == VALIDATOR_RULE_ORDER
    assert len(b.rules) == 12


def test_bundle_rejects_missing_rule():
    rules = tuple(
        ValidatorRuleConfig(rule_id=r, severity="error", rule_params_hash=HEX, repairable=False)
        for r in VALIDATOR_RULE_ORDER[:-1]
    )
    with pytest.raises(ValueError):
        ValidatorBundle(bundle_version="vb-1", rules=rules)


def test_bundle_rejects_duplicate_rule():
    rules = tuple(
        ValidatorRuleConfig(rule_id=r, severity="error", rule_params_hash=HEX, repairable=False)
        for r in VALIDATOR_RULE_ORDER[:-1]
    ) + (
        ValidatorRuleConfig(
            rule_id=VALIDATOR_RULE_ORDER[0], severity="error", rule_params_hash=HEX,
            repairable=False,
        ),
    )
    with pytest.raises(ValueError):
        ValidatorBundle(bundle_version="vb-1", rules=rules)


def test_bundle_rejects_wrong_order():
    reordered = (VALIDATOR_RULE_ORDER[1], VALIDATOR_RULE_ORDER[0]) + VALIDATOR_RULE_ORDER[2:]
    rules = tuple(
        ValidatorRuleConfig(rule_id=r, severity="error", rule_params_hash=HEX, repairable=False)
        for r in reordered
    )
    with pytest.raises(ValueError):
        ValidatorBundle(bundle_version="vb-1", rules=rules)


def test_bundle_hash_is_deterministic_and_sensitive():
    b1 = bundle()
    b2 = bundle()
    assert validator_bundle_hash(b1) == validator_bundle_hash(b2)
    changed = bundle(severities={"source_id_resolution": "critical"})
    assert validator_bundle_hash(changed) != validator_bundle_hash(b1)


def test_rule_params_hash_must_be_hex():
    with pytest.raises(ValueError):
        ValidatorRuleConfig(
            rule_id="source_id_resolution", severity="error",
            rule_params_hash="NOTHEX", repairable=False,
        )


# --- Handler pass/fail paths ----------------------------------------------


@pytest.mark.parametrize("rule_id", list(VALIDATOR_RULE_ORDER))
def test_each_handler_passes_when_clean(run_manifest, rule_id):
    result = evaluate_validator_findings(snapshot(), bundle=bundle(), run_manifest=run_manifest)
    assert result.findings == ()


@pytest.mark.parametrize("rule_id", list(VALIDATOR_RULE_ORDER))
def test_each_handler_fails_when_violated(run_manifest, rule_id):
    result = evaluate_validator_findings(
        snapshot(failing=(rule_id,)), bundle=bundle(), run_manifest=run_manifest
    )
    assert len(result.findings) == 1
    assert result.findings[0].validator == rule_id


def test_non_active_record_passes_roadmap_rule(run_manifest):
    obs = _passing_observations()
    obs["active_record_non_roadmap_evidence"] = {
        "rule_id": "active_record_non_roadmap_evidence", "observation_id": "o10",
        "active": False, "evidence": ({"evidence_id": "e1", "is_future_roadmap": True},),
    }
    result = evaluate_validator_findings(
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER)),
        bundle=bundle(), run_manifest=run_manifest,
    )
    assert result.findings == ()


def test_non_customer_task_passes_outcome_rule(run_manifest):
    obs = _passing_observations()
    obs["customer_task_outcome_and_evidence"] = {
        "rule_id": "customer_task_outcome_and_evidence", "observation_id": "o11",
        "is_customer_facing_task": False, "customer_outcome": None, "evidence_ids": (),
    }
    result = evaluate_validator_findings(
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER)),
        bundle=bundle(), run_manifest=run_manifest,
    )
    assert result.findings == ()


def test_no_repair_applied_needs_no_repair_record(run_manifest):
    obs = _passing_observations()
    obs["raw_output_and_repair_preservation"] = {
        "rule_id": "raw_output_and_repair_preservation", "observation_id": "o12",
        "raw_output_reference": "raw.json", "repair_applied": False,
        "repair_record_references": (),
    }
    result = evaluate_validator_findings(
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER)),
        bundle=bundle(), run_manifest=run_manifest,
    )
    assert result.findings == ()


# --- Blank-value semantics (locked): blanks must not pass by accident ------


def _single_failing(run_manifest, rule_id, override):
    obs = _passing_observations()
    obs[rule_id] = {**obs[rule_id], **override}
    result = evaluate_validator_findings(
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER)),
        bundle=bundle(), run_manifest=run_manifest,
    )
    return result


@pytest.mark.parametrize("quote", ["", "   ", "\t"])
def test_blank_quote_does_not_pass_by_substring_accident(run_manifest, quote):
    result = _single_failing(
        run_manifest, "evidence_quote_containment",
        {"quote": quote, "passage_text": "the alpha beta", "passage_id": "p1"},
    )
    assert len(result.findings) == 1
    assert result.findings[0].validator == "evidence_quote_containment"


def test_nonblank_quote_substring_still_passes(run_manifest):
    result = _single_failing(
        run_manifest, "evidence_quote_containment",
        {"quote": "alpha", "passage_text": "the alpha beta", "passage_id": "p1"},
    )
    assert result.findings == ()


@pytest.mark.parametrize("evidence_ids", [("",), ("   ",), ("", "  ")])
def test_blank_evidence_id_is_not_supporting_evidence(run_manifest, evidence_ids):
    result = _single_failing(
        run_manifest, "customer_task_outcome_and_evidence",
        {"is_customer_facing_task": True, "customer_outcome": "did x",
         "evidence_ids": evidence_ids},
    )
    assert len(result.findings) == 1
    assert result.findings[0].validator == "customer_task_outcome_and_evidence"


@pytest.mark.parametrize("repair_refs", [("",), ("   ",)])
def test_blank_repair_record_reference_does_not_satisfy(run_manifest, repair_refs):
    result = _single_failing(
        run_manifest, "raw_output_and_repair_preservation",
        {"raw_output_reference": "raw.json", "repair_applied": True,
         "repair_record_references": repair_refs},
    )
    assert len(result.findings) == 1
    assert result.findings[0].validator == "raw_output_and_repair_preservation"


def test_nonblank_evidence_and_repair_still_pass(run_manifest):
    result = evaluate_validator_findings(snapshot(), bundle=bundle(), run_manifest=run_manifest)
    assert result.findings == ()


# --- Severity stamping ----------------------------------------------------


@pytest.mark.parametrize("severity", ["critical", "error", "warning", "info"])
def test_all_four_severities_stamped_from_bundle(run_manifest, severity):
    b = bundle(severities={"source_id_resolution": severity},
               repairable={"source_id_resolution": True})
    init_bundle_hash = validator_bundle_hash(b)
    # Rebind the run manifest to this bundle's hash.
    result = evaluate_validator_findings(
        snapshot(failing=("source_id_resolution",)),
        bundle=b,
        run_manifest=run_manifest.model_copy(update={"validator_bundle_hash": init_bundle_hash}),
    )
    assert result.findings[0].severity == severity
    assert result.findings[0].repairable is True


# --- Bundle / snapshot binding --------------------------------------------


def test_bundle_version_mismatch(run_manifest):
    b = bundle(version="vb-OTHER")
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate_validator_findings(snapshot(), bundle=b, run_manifest=run_manifest)
    assert exc.value.binding_kind == "bundle_version_mismatch"


def test_bundle_hash_mismatch(run_manifest):
    # Same version, different severity -> different computed hash than the manifest pins.
    b = bundle(severities={"passage_id_resolution": "critical"})
    with pytest.raises(ValidatorBundleBindingError) as exc:
        evaluate_validator_findings(snapshot(), bundle=b, run_manifest=run_manifest)
    assert exc.value.binding_kind == "bundle_hash_mismatch"


def test_snapshot_run_mismatch(run_manifest):
    with pytest.raises(SnapshotRunBindingError):
        evaluate_validator_findings(
            snapshot(run_id="other-run"), bundle=bundle(), run_manifest=run_manifest
        )


# --- Snapshot invariants --------------------------------------------------


def test_snapshot_requires_all_twelve_rules():
    obs = _passing_observations()
    del obs["source_id_resolution"]
    with pytest.raises(ValueError):
        ValidationArtifactSnapshot.model_validate({
            "eval_run_id": "run1", "artifact_id": "a", "artifact_sha256": "b" * 64,
            "created_at": CREATED_AT, "case_id": None,
            "observations": [obs[r] for r in obs],
        })


def test_snapshot_rejects_duplicate_observation_id():
    obs = _passing_observations()
    obs["required_field_presence"] = {**obs["required_field_presence"], "observation_id": "o1"}
    with pytest.raises(ValueError):
        ValidationArtifactSnapshot.model_validate({
            "eval_run_id": "run1", "artifact_id": "a", "artifact_sha256": "b" * 64,
            "created_at": CREATED_AT, "case_id": None,
            "observations": [obs[r] for r in VALIDATOR_RULE_ORDER],
        })


def test_snapshot_rejects_non_rfc3339_created_at():
    with pytest.raises(ValueError):
        snapshot(created_at="2026-07-20")


def test_snapshot_rejects_bad_artifact_hash():
    with pytest.raises(ValueError):
        ValidationArtifactSnapshot.model_validate({
            "eval_run_id": "run1", "artifact_id": "a", "artifact_sha256": "NOTHEX",
            "created_at": CREATED_AT, "case_id": None,
            "observations": [_passing_observations()[r] for r in VALIDATOR_RULE_ORDER],
        })


def test_observation_no_verdict_field_accepted():
    """A generic `passed`/`valid`/`outcome` flag is rejected by extra=forbid."""
    obs = _passing_observations()
    obs["source_id_resolution"] = {**obs["source_id_resolution"], "passed": True}
    with pytest.raises(ValueError):
        ValidationArtifactSnapshot.model_validate({
            "eval_run_id": "run1", "artifact_id": "a", "artifact_sha256": "b" * 64,
            "created_at": CREATED_AT, "case_id": None,
            "observations": [obs[r] for r in VALIDATOR_RULE_ORDER],
        })


# --- Ordering + determinism -----------------------------------------------


def test_finding_order_is_canonical_rule_then_observation_id(run_manifest):
    # Fail three rules; supply observations out of canonical order in the tuple.
    failing = ("unique_ids_within_scope", "source_id_resolution", "passage_id_resolution")
    result = evaluate_validator_findings(
        snapshot(failing=failing), bundle=bundle(), run_manifest=run_manifest
    )
    order = [f.validator for f in result.findings]
    assert order == ["source_id_resolution", "passage_id_resolution", "unique_ids_within_scope"]


def test_findings_deterministic_and_distinct(run_manifest):
    s = snapshot(failing=("source_id_resolution", "passage_id_resolution"))
    r1 = evaluate_validator_findings(s, bundle=bundle(), run_manifest=run_manifest)
    r2 = evaluate_validator_findings(s, bundle=bundle(), run_manifest=run_manifest)
    assert r1.findings == r2.findings
    assert r1.findings[0] is not r2.findings[0]
    assert val_mod._canonical_finding_line(r1.findings[0]) == val_mod._canonical_finding_line(
        r2.findings[0]
    )


def test_finding_id_is_deterministic_hex(run_manifest):
    result = evaluate_validator_findings(
        snapshot(failing=("source_id_resolution",)), bundle=bundle(),
        run_manifest=run_manifest,
    )
    fid = result.findings[0].finding_id
    assert len(fid) == 64 and all(c in "0123456789abcdef" for c in fid)


def test_created_at_copied_from_snapshot(run_manifest):
    result = evaluate_validator_findings(
        snapshot(failing=("source_id_resolution",), created_at="2025-05-05T12:34:56+00:00"),
        bundle=bundle(), run_manifest=run_manifest,
    )
    assert result.findings[0].created_at == "2025-05-05T12:34:56+00:00"


def test_entity_id_stamped_when_present(run_manifest):
    result = evaluate_validator_findings(
        snapshot(failing=("source_id_resolution",),
                 entity_ids={"source_id_resolution": "ENT-1"}),
        bundle=bundle(), run_manifest=run_manifest,
    )
    assert result.findings[0].entity_id == "ENT-1"


def test_no_raw_text_leakage_in_quote_finding(run_manifest):
    result = evaluate_validator_findings(
        snapshot(failing=("evidence_quote_containment",)),
        bundle=bundle(), run_manifest=run_manifest,
    )
    f = result.findings[0]
    blob = " ".join([f.observed_value, f.expected_invariant, f.message, f.evidence])
    # The failing fixture uses quote "zzz" in passage "abc"; neither may appear.
    assert "zzz" not in blob
    assert "abc" not in blob


def test_no_customer_outcome_text_leakage(run_manifest):
    obs = _passing_observations()
    obs["customer_task_outcome_and_evidence"] = {
        "rule_id": "customer_task_outcome_and_evidence", "observation_id": "o11",
        "is_customer_facing_task": True, "customer_outcome": "SECRET_OUTCOME", "evidence_ids": (),
    }
    result = evaluate_validator_findings(
        snapshot(observations=tuple(obs[r] for r in VALIDATOR_RULE_ORDER)),
        bundle=bundle(), run_manifest=run_manifest,
    )
    f = result.findings[0]
    blob = " ".join([f.observed_value, f.expected_invariant, f.message, f.evidence])
    assert "SECRET_OUTCOME" not in blob


# --- Purity ---------------------------------------------------------------


def test_evaluate_touches_no_filesystem(run_manifest, monkeypatch):
    calls = []

    def spy(name, orig):
        def wrapper(*a, **k):
            calls.append(name)
            return orig(*a, **k)
        return wrapper

    monkeypatch.setattr(Path, "read_bytes", spy("read_bytes", Path.read_bytes))
    monkeypatch.setattr(Path, "read_text", spy("read_text", Path.read_text))
    monkeypatch.setattr(Path, "write_bytes", spy("write_bytes", Path.write_bytes))
    monkeypatch.setattr(Path, "mkdir", spy("mkdir", Path.mkdir))
    monkeypatch.setattr(os, "open", spy("os.open", os.open))
    evaluate_validator_findings(
        snapshot(failing=("source_id_resolution",)), bundle=bundle(),
        run_manifest=run_manifest,
    )
    assert calls == []


def test_result_has_no_status_or_verdict(run_manifest):
    result = evaluate_validator_findings(
        snapshot(failing=("source_id_resolution",)), bundle=bundle(),
        run_manifest=run_manifest,
    )
    fields = set(type(result).model_fields)
    assert "execution_status" not in fields
    assert "gate_verdict" not in fields
    assert fields == {
        "eval_run_id", "artifact_id", "artifact_sha256",
        "validator_bundle_version", "validator_bundle_hash", "findings",
    }


# --- Persistence ----------------------------------------------------------


def evaluated(tmp_path):
    run = load_evaluation_run_manifest("run1", eval_root=tmp_path).manifest
    return evaluate_validator_findings(
        snapshot(failing=("source_id_resolution", "unique_ids_within_scope")),
        bundle=bundle(), run_manifest=run,
    )


def test_persist_and_load_roundtrip(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    persisted = persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")
    assert isinstance(persisted, PersistedValidatorFindings)
    assert persisted.artifact_reference == "run1/findings/validator_findings.jsonl"
    dest = tmp_path / "run1" / "findings" / "validator_findings.jsonl"
    assert sha256_bytes(dest.read_bytes()) == persisted.sha256
    loaded = load_validator_findings("run1", eval_root=tmp_path)
    assert isinstance(loaded, LoadedValidatorFindings)
    assert loaded.sha256 == persisted.sha256
    assert [f.model_dump() for f in loaded.findings] == [f.model_dump() for f in ev.findings]


def test_persist_empty_findings(tmp_path):
    init_run(tmp_path)
    persisted = persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")
    dest = tmp_path / "run1" / "findings" / "validator_findings.jsonl"
    assert dest.read_bytes() == b""
    assert persisted.sha256 == sha256_bytes(b"")
    assert load_validator_findings("run1", eval_root=tmp_path).findings == ()


def test_persist_is_write_once(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_existing_file_collision(tmp_path):
    init_run(tmp_path)
    (tmp_path / "run1" / "findings").write_bytes(b"occupied")
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")
    assert (tmp_path / "run1" / "findings").read_bytes() == b"occupied"


def test_persist_rejects_existing_directory(tmp_path):
    init_run(tmp_path)
    (tmp_path / "run1" / "findings").mkdir()
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_symlink(tmp_path):
    init_run(tmp_path)
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / "run1" / "findings").symlink_to(target)
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_dangling_symlink(tmp_path):
    init_run(tmp_path)
    (tmp_path / "run1" / "findings").symlink_to(tmp_path / "nope")
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings((), eval_root=tmp_path, eval_run_id="run1")


def test_write_failure_after_dir_create_preserves_directory(tmp_path, monkeypatch):
    init_run(tmp_path)
    ev = evaluated(tmp_path)

    def boom(*a, **k):
        raise OSError("synthetic write failure")

    monkeypatch.setattr(val_mod.os, "open", boom)
    with pytest.raises(ValidatorWriteError):
        persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")
    monkeypatch.undo()
    d = tmp_path / "run1" / "findings"
    assert d.is_dir()
    assert list(d.iterdir()) == []
    with pytest.raises(ValidatorFindingsExistError):
        persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_run_binding(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    tampered = ev.findings[0].model_copy(update={"run_id": "other"})
    with pytest.raises(ValidatorFindingRunBindingError):
        persist_validator_findings((tampered,), eval_root=tmp_path, eval_run_id="run1")


def test_persist_rejects_duplicate_finding_id(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    dup = (ev.findings[0], ev.findings[0])
    with pytest.raises(DuplicateValidatorFindingError):
        persist_validator_findings(dup, eval_root=tmp_path, eval_run_id="run1")


# --- Loader strictness ----------------------------------------------------


def write_findings_dir(tmp_path, data: bytes):
    d = tmp_path / "run1" / "findings"
    d.mkdir(parents=True, exist_ok=False)
    (d / "validator_findings.jsonl").write_bytes(data)


def finding_line(tmp_path):
    ev = evaluated(tmp_path)
    return val_mod._canonical_finding_line(ev.findings[0]) + b"\n"


def test_load_missing(tmp_path):
    init_run(tmp_path)
    with pytest.raises(ValidatorArtifactMissingError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_non_utf8(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b"\xff\xfe")
    with pytest.raises(ValidatorDecodeError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_bom(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b"\xef\xbb\xbf" + finding_line(tmp_path))
    with pytest.raises(ValidatorJsonError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_blank_line(tmp_path):
    init_run(tmp_path)
    line = finding_line(tmp_path)
    write_findings_dir(tmp_path, line + b"\n" + line)
    with pytest.raises(ValidatorJsonError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_trailing_data(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    write_findings_dir(tmp_path, val_mod._canonical_finding_line(ev.findings[0]) + b" x\n")
    with pytest.raises(ValidatorJsonError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_duplicate_keys(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b'{"a":1,"a":2}\n')
    with pytest.raises(ValidatorJsonError) as exc:
        load_validator_findings("run1", eval_root=tmp_path)
    assert exc.value.duplicate_key == "a"


@pytest.mark.parametrize("constant", [b"NaN", b"Infinity", b"-Infinity"])
def test_load_rejects_non_finite(tmp_path, constant):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b'{"x":' + constant + b"}\n")
    with pytest.raises(ValidatorJsonError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_non_object(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b"[1,2]\n")
    with pytest.raises(ValidatorTopLevelTypeError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_model_invalid(tmp_path):
    init_run(tmp_path)
    write_findings_dir(tmp_path, b'{"unexpected":true}\n')
    with pytest.raises(ValidatorModelValidationError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_run_binding(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    tampered = ev.findings[0].model_copy(update={"run_id": "other"})
    write_findings_dir(
        tmp_path, val_mod._canonical_finding_line(tampered) + b"\n"
    )
    with pytest.raises(ValidatorFindingRunBindingError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_artifact(tmp_path):
    init_run(tmp_path)
    d = tmp_path / "run1" / "findings"
    d.mkdir(parents=True, exist_ok=False)
    target = tmp_path / "outside.jsonl"
    target.write_bytes(b"")
    (d / "validator_findings.jsonl").symlink_to(target)
    with pytest.raises(ValidatorArtifactNotAFileError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_load_rejects_symlinked_run_dir(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    init_run(real, "run1")
    (tmp_path / "run1").symlink_to(real / "run1")
    with pytest.raises(RunArtifactNotAFileError):
        load_validator_findings("run1", eval_root=tmp_path)


def test_repeated_loads_equal_but_distinct(tmp_path):
    init_run(tmp_path)
    ev = evaluated(tmp_path)
    persist_validator_findings(ev.findings, eval_root=tmp_path, eval_run_id="run1")
    a = load_validator_findings("run1", eval_root=tmp_path)
    b = load_validator_findings("run1", eval_root=tmp_path)
    assert a is not b
    assert a.findings[0] is not b.findings[0]
    assert [f.model_dump() for f in a.findings] == [f.model_dump() for f in b.findings]


def test_invalid_eval_root_rejected():
    with pytest.raises(InvalidEvaluationRootError):
        load_validator_findings("run1", eval_root="")


# --- Exports and import hygiene -------------------------------------------

PUBLIC_FUNCTIONS = (
    "evaluate_validator_findings", "persist_validator_findings", "load_validator_findings",
    "validator_bundle_hash",
)
PUBLIC_MODELS = (
    "ValidatorRuleConfig", "ValidatorBundle", "ValidationArtifactSnapshot",
    "EvaluatedValidatorFindings", "PersistedValidatorFindings", "LoadedValidatorFindings",
    "EvidenceClassification",
)
PUBLIC_ALIASES = ("ValidatorRuleId", "VALIDATOR_RULE_ORDER", "ValidatorObservation")
PUBLIC_EXCEPTIONS = (
    "ValidatorError", "ValidatorBundleBindingError",
    "SnapshotRunBindingError", "ValidatorFindingsExistError",
    "ValidatorArtifactMissingError", "ValidatorArtifactNotAFileError", "ValidatorArtifactReadError",
    "ValidatorDecodeError", "ValidatorJsonError", "ValidatorTopLevelTypeError",
    "ValidatorModelValidationError", "DuplicateValidatorFindingError",
    "ValidatorFindingRunBindingError", "ValidatorWriteError", "ValidatorDestinationHashMismatchError",
)


def test_public_symbols_exported():
    for name in PUBLIC_FUNCTIONS + PUBLIC_MODELS + PUBLIC_ALIASES + PUBLIC_EXCEPTIONS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(val_mod, name)


def test_observation_models_exported():
    for name in (
        "OutputJsonSchemaValidityObservation", "RequiredFieldPresenceObservation",
        "SourceIdResolutionObservation", "PassageIdResolutionObservation",
        "EvidenceQuoteContainmentObservation", "PublicationDateCutoffObservation",
        "ProductCapabilityTaskParentResolutionObservation", "UniqueIdsWithinScopeObservation",
        "ProhibitedLegacyFieldsAbsentObservation", "ActiveRecordNonRoadmapEvidenceObservation",
        "CustomerTaskOutcomeAndEvidenceObservation", "RawOutputAndRepairPreservationObservation",
    ):
        assert name in evaluation_pkg.__all__


def test_exception_hierarchy():
    for name in PUBLIC_EXCEPTIONS:
        cls = getattr(val_mod, name)
        if name == "ValidatorError":
            assert cls.__bases__ == (Exception,)
        else:
            assert issubclass(cls, val_mod.ValidatorError)


def test_private_helpers_not_exported():
    for name in ("_canonical_finding_line", "_parse_findings_jsonl", "_dispatch_rule",
                 "_finding_identity_bytes", "_DuplicateKeyControl"):
        assert name not in evaluation_pkg.__all__
        assert not hasattr(evaluation_pkg, name)


def test_no_path_escape_error_class():
    """Path escape is governed by the reused run-id validator, not a new class."""
    assert not hasattr(val_mod, "ValidatorPathEscapeError")


def test_finding_contract_hash_unchanged():
    assert model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0") == (
        "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292"
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
        "import dynamic_ai_products.evaluation.validators\n"
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open=orb,ort,omk,oop\nhashlib.sha256=osha\n"
        "bad=[p for p in reads if p.endswith('.json') or p.endswith('.jsonl') or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad and not writes and not sha, (bad, writes, len(sha))\nprint('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
