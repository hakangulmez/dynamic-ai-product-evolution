"""Slice 12I: stage metric evidence set (``stage_metric_evidence_set@0.1.0``)."""

from pathlib import Path

import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import stage_evidence as se
from dynamic_ai_products.evaluation.contracts import model_contract_hash
from dynamic_ai_products.evaluation.stage_evidence import (
    LoadedStageMetricEvidenceSet,
    StageEvidenceBindingError,
    StageEvidenceError,
    StageMetricEvidenceSet,
    build_stage_metric_evidence_set,
    load_stage_metric_evidence_set,
    persist_stage_metric_evidence_set,
    stage_metric_evidence_set_hash,
)
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
FIXTURE = "stage_evidence/universe_stage_metric_evidence_set.json"

SCREEN = {"kind": "universe_screen_operational", "screen_operational_summary": {
    "total_screened": 10, "screen_negative": 4, "screen_nonnegative": 5,
    "unresolved": 1, "downstream_review_count": 3}}
UNSAFE = {"kind": "universe_unsafe_exclusion_audit", "unsafe_exclusion_audit": {
    "audit_snapshot_hash": "b" * 64, "seed": 1, "sampling_design_id": "d",
    "strata": [{"stratum_id": "s1", "screen_negative_population_count": 100, "audited_labels": [
        {"record_id": "a0", "verification_status": "verified",
         "actually_eligible_or_boundary_relevant": False}]}]}}
TIER = {"kind": "universe_classification_tier", "tier_contract_observations": [{
    "record_id": "t1", "verification_status": "verified", "tier_rule_version": "v",
    "expected_tier": "T", "observed_tier": "T", "expected_reason_codes": ["r"],
    "observed_reason_codes": ["r"], "expected_rule_trace_hash": "c" * 64,
    "observed_rule_trace_hash": "c" * 64, "repeatability_output_hashes": ["d" * 64, "d" * 64]}]}


def _screen_set():
    return build_stage_metric_evidence_set(
        evaluation_stage="universe_screen", set_version="se-v1", variants=(SCREEN, UNSAFE))


def _mkrun(tmp_path):
    (tmp_path / "run1").mkdir()
    return tmp_path


# --- Model + variants ------------------------------------------------------


def test_carries_stage_and_version():
    s = _screen_set()
    assert s.evaluation_stage == "universe_screen"
    assert s.set_version == "se-v1"
    assert s.present_kinds == ("universe_screen_operational", "universe_unsafe_exclusion_audit")


def test_each_discriminated_variant_round_trips():
    tier = build_stage_metric_evidence_set(
        evaluation_stage="universe_classification", set_version="v", variants=(TIER,))
    assert tier.present_kinds == ("universe_classification_tier",)
    assert tier.variants[0].tier_contract_observations[0].record_id == "t1"
    scr = build_stage_metric_evidence_set(
        evaluation_stage="universe_screen", set_version="v", variants=(SCREEN,))
    assert scr.variants[0].screen_operational_summary.total_screened == 10
    uns = build_stage_metric_evidence_set(
        evaluation_stage="universe_screen", set_version="v", variants=(UNSAFE,))
    assert uns.variants[0].unsafe_exclusion_audit.seed == 1


def test_non_canonical_variant_order_rejected():
    with pytest.raises(Exception):
        build_stage_metric_evidence_set(
            evaluation_stage="universe_screen", set_version="v", variants=(UNSAFE, SCREEN))


def test_duplicate_variant_kind_rejected():
    with pytest.raises(Exception):
        build_stage_metric_evidence_set(
            evaluation_stage="universe_screen", set_version="v", variants=(SCREEN, SCREEN))


def test_empty_set_rejected():
    with pytest.raises(Exception):
        build_stage_metric_evidence_set(
            evaluation_stage="universe_screen", set_version="v", variants=())


def test_blank_stage_rejected():
    with pytest.raises(Exception):
        build_stage_metric_evidence_set(
            evaluation_stage="  ", set_version="v", variants=(SCREEN,))


# --- Hashing: governed semantic vs raw persisted byte ---------------------


def test_semantic_hash_is_deterministic_and_64_hex():
    s = _screen_set()
    h = stage_metric_evidence_set_hash(s)
    assert h == stage_metric_evidence_set_hash(s)
    assert len(h) == 64 and all(c in "0123456789abcdef" for c in h)


def test_semantic_hash_differs_from_raw_byte_hash(tmp_path):
    root = _mkrun(tmp_path)
    loaded = persist_stage_metric_evidence_set(_screen_set(), eval_root=root, eval_run_id="run1")
    content = stage_metric_evidence_set_hash(loaded.model)
    # The governed content hash and the raw persisted-byte SHA-256 are distinct
    # identities (the persisted bytes include the terminal newline).
    assert content != loaded.sha256


def test_fail_closed_revalidation_of_tampered_instance():
    s = _screen_set()
    # A model_construct-bypassed instance with an unsorted variant tuple must be
    # rejected before it can yield a semantic-content hash.
    bad = s.model_construct(**{**s.__dict__, "variants": tuple(reversed(s.variants))})
    with pytest.raises(StageEvidenceError):
        stage_metric_evidence_set_hash(bad)


# --- Contract stamp --------------------------------------------------------


def test_contract_stamp_governed():
    s = _screen_set()
    assert s.contract.contract_id == "stage_metric_evidence_set"
    assert s.contract.contract_version == "0.1.0"
    assert s.contract.contract_hash == model_contract_hash(
        StageMetricEvidenceSet, "stage_metric_evidence_set", "0.1.0")


# --- Loader ----------------------------------------------------------------


def test_load_committed_fixture():
    loaded = load_stage_metric_evidence_set(FIXTURE, eval_root=FX)
    assert isinstance(loaded, LoadedStageMetricEvidenceSet)
    assert loaded.model.evaluation_stage == "universe_screen"
    assert loaded.version == "0.1.0"
    assert loaded.model.present_kinds == (
        "universe_screen_operational", "universe_unsafe_exclusion_audit")


def test_load_expected_hash_match_and_mismatch():
    raw = (FX / "stage_evidence/universe_stage_metric_evidence_set.json").read_bytes()
    good = sha256_bytes(raw)
    assert load_stage_metric_evidence_set(FIXTURE, eval_root=FX, expected_sha256=good).sha256 == good
    with pytest.raises(StageEvidenceError):
        load_stage_metric_evidence_set(FIXTURE, eval_root=FX, expected_sha256="0" * 64)


def test_load_rejects_symlink(tmp_path):
    root = _mkrun(tmp_path)
    target = root / "real.json"
    target.write_bytes((FX / "stage_evidence/universe_stage_metric_evidence_set.json").read_bytes())
    link = root / "link.json"
    link.symlink_to(target)
    with pytest.raises(StageEvidenceError) as e:
        load_stage_metric_evidence_set("link.json", eval_root=root)
    assert e.value.reason_code == "artifact_symlink"


def test_load_rejects_path_escape(tmp_path):
    root = _mkrun(tmp_path)
    with pytest.raises(StageEvidenceError) as e:
        load_stage_metric_evidence_set("../escape.json", eval_root=root)
    assert e.value.reason_code == "unsafe_reference"


def test_load_rejects_duplicate_keys(tmp_path):
    root = _mkrun(tmp_path)
    (root / "dup.json").write_text('{"set_version": "a", "set_version": "b"}')
    with pytest.raises(StageEvidenceError) as e:
        load_stage_metric_evidence_set("dup.json", eval_root=root)
    assert e.value.reason_code == "duplicate_key"


def test_load_rejects_non_finite(tmp_path):
    root = _mkrun(tmp_path)
    (root / "nf.json").write_text('{"x": NaN}')
    with pytest.raises(StageEvidenceError) as e:
        load_stage_metric_evidence_set("nf.json", eval_root=root)
    assert e.value.reason_code == "non_finite"


def test_load_rejects_non_object(tmp_path):
    root = _mkrun(tmp_path)
    (root / "arr.json").write_text("[1, 2]")
    with pytest.raises(StageEvidenceError) as e:
        load_stage_metric_evidence_set("arr.json", eval_root=root)
    assert e.value.reason_code == "top_level_type"


def test_load_rejects_model_invalid(tmp_path):
    root = _mkrun(tmp_path)
    (root / "bad.json").write_text('{"evaluation_stage": "x"}')
    with pytest.raises(StageEvidenceError) as e:
        load_stage_metric_evidence_set("bad.json", eval_root=root)
    assert e.value.reason_code == "model_validation"


# --- Persistence -----------------------------------------------------------


def test_persist_round_trip(tmp_path):
    root = _mkrun(tmp_path)
    persisted = persist_stage_metric_evidence_set(_screen_set(), eval_root=root, eval_run_id="run1")
    reloaded = load_stage_metric_evidence_set(persisted.artifact_reference, eval_root=root)
    assert reloaded.sha256 == persisted.sha256
    assert reloaded.model.present_kinds == persisted.model.present_kinds


def test_persist_is_write_once(tmp_path):
    root = _mkrun(tmp_path)
    persist_stage_metric_evidence_set(_screen_set(), eval_root=root, eval_run_id="run1")
    with pytest.raises(StageEvidenceError) as e:
        persist_stage_metric_evidence_set(_screen_set(), eval_root=root, eval_run_id="run1")
    assert e.value.reason_code == "artifact_exists"


def test_persist_rejects_missing_run_dir(tmp_path):
    with pytest.raises(StageEvidenceError) as e:
        persist_stage_metric_evidence_set(_screen_set(), eval_root=tmp_path, eval_run_id="absent")
    assert e.value.reason_code == "run_directory_missing"


def test_persist_rejects_invalid_run_id(tmp_path):
    with pytest.raises(StageEvidenceError) as e:
        persist_stage_metric_evidence_set(_screen_set(), eval_root=tmp_path, eval_run_id="a/b")
    assert e.value.reason_code == "invalid_eval_run_id"


# --- Public surface --------------------------------------------------------


def test_public_surface():
    assert set(se.__all__) == {
        "LoadedStageMetricEvidenceSet", "StageEvidenceBindingError", "StageEvidenceError",
        "StageMetricEvidenceKind", "StageMetricEvidenceSet", "load_stage_metric_evidence_set",
        "persist_stage_metric_evidence_set", "stage_metric_evidence_set_hash",
    }
    for name in se.__all__:
        assert name in evaluation_pkg.__all__
    # Discriminated variant wrappers remain private.
    for private in ("_ScreenOperationalEvidence", "_ClassificationTierEvidence",
                    "_UnsafeExclusionAuditEvidence"):
        assert private not in evaluation_pkg.__all__
    assert issubclass(StageEvidenceBindingError, Exception)
