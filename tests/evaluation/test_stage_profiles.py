"""Slice 12A: governed, hash-bound evaluation-stage-profile registry."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError as PydanticValidationError

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import stage_profiles as sp_mod
from dynamic_ai_products.evaluation.stage_profiles import (
    StageProfileBindingError,
    StageProfileEntry,
    StageProfileError,
    StageProfileRegistry,
    load_stage_profile_registry,
    persist_stage_profile_registry_snapshot,
    resolve_metric_applicability,
    stage_profile_registry_hash,
)
from dynamic_ai_products.evaluation.contracts import canonical_contract_bytes, model_contract_hash
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_REL = "evals/fixtures/evaluation_harness/stage_profiles/stage_profile_registry.json"
FIXTURE_ABS = ROOT / FIXTURE_REL

_CONTRACT_ID = "evaluation_stage_profile_registry"
_CONTRACT_VERSION = "0.1.0"
MODEL_HASH = "cbd567cb0367cabe5f680957a8da29d9018ccd50512c91e0f9c393de2c7ee4dd"
CONTENT_HASH = "242cf65210b1a176f15c2162342f5ddb84f5018ed5a4cb91423d5aef2a18a777"
FIXTURE_SHA = "69a676df22c69ed7a117f28ab4b9f776f7dd9cefb74eec2abd0bc132ea7ca18f"
ENTRY_HASHES = {
    "capability_extraction": "e0b871784297c66a7e9a280c9705d530f3cce9d803540691bbde74a984a07ad2",
    "task_extraction": "c1ca660679f6591bdd240a885c979220bee8d998a9a7bb6ce700f9ac4ace0a6d",
    "universe_screen": "cee3b3259d2f4bd40ba3caab7b84aa77bea4519005519ff438e5814c289b09b8",
    "universe_classification": "ce3c1b17fe3eb15e805a82208502615e0de192aa1388012e18c760089f145671",
}

AXIS5 = [
    "axis_abstention", "axis_multi_label", "axis_nominal_single_label",
    "axis_ordinal_single_label", "axis_structured_set",
]


def load():
    return load_stage_profile_registry(FIXTURE_REL, eval_root=ROOT)


def base_doc() -> dict:
    return copy.deepcopy(json.loads(FIXTURE_ABS.read_bytes()))


def entry_dict(stage, status, families, kinds, reasons):
    return {
        "evaluation_stage": stage, "support_status": status,
        "applicable_metric_families": families, "required_stage_evidence_kinds": kinds,
        "applicability_reason_codes": reasons,
    }


# --- 1. strict/frozen/extra-forbid ----------------------------------------


def test_models_strict_frozen_extra_forbid():
    e = StageProfileEntry.model_validate(
        entry_dict("s", "unsupported", [], [], ["unsupported_evaluation_stage"]))
    with pytest.raises(PydanticValidationError):
        e.support_status = "working"  # frozen
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate(
            {**entry_dict("s", "unsupported", [], [], ["unsupported_evaluation_stage"]), "x": 1})
    reg = load().registry
    with pytest.raises(PydanticValidationError):
        reg.entries[0].__init__()  # noqa
    with pytest.raises(PydanticValidationError):
        StageProfileRegistry.model_validate({**base_doc(), "extra": 1})


# --- 2. correct contract id/version/generated hash ------------------------


def test_correct_contract_identity_and_hash():
    reg = load().registry
    assert reg.contract.contract_id == _CONTRACT_ID
    assert reg.contract.contract_version == _CONTRACT_VERSION
    assert reg.contract.contract_hash == MODEL_HASH
    assert model_contract_hash(StageProfileRegistry, _CONTRACT_ID, _CONTRACT_VERSION) == MODEL_HASH


# --- 3. wrong contract id/version/hash rejection --------------------------


def test_wrong_contract_stamp_rejected():
    for bad in ({"contract_id": "other"}, {"contract_version": "0.2.0"}, {"contract_hash": "a" * 64}):
        doc = base_doc()
        doc["contract"].update(bad)
        with pytest.raises(PydanticValidationError):
            StageProfileRegistry.model_validate(doc)


def test_wrong_stamp_via_loader_is_stage_profile_error(tmp_path):
    doc = base_doc()
    doc["contract"]["contract_hash"] = "b" * 64
    p = tmp_path / "r.json"
    p.write_bytes(json.dumps(doc).encode("utf-8"))
    with pytest.raises(StageProfileError) as ei:
        load_stage_profile_registry("r.json", eval_root=tmp_path)
    assert ei.value.reason_code == "model_validation"


# --- 4. exact inventory + status mapping ----------------------------------


def test_exact_seven_entry_inventory_and_status():
    reg = load().registry
    assert [e.evaluation_stage for e in reg.entries] == [
        "capability_extraction", "product_extraction", "task_extraction",
        "task_measurement", "task_transition", "universe_classification", "universe_screen"]
    status = {e.evaluation_stage: e.support_status for e in reg.entries}
    assert status == {
        "capability_extraction": "fixture_backed", "product_extraction": "unsupported",
        "task_extraction": "fixture_backed", "task_measurement": "unsupported",
        "task_transition": "unsupported", "universe_classification": "working",
        "universe_screen": "working"}


# --- 5. exact metric-family + evidence-kind mapping ------------------------


def test_exact_family_and_evidence_mapping():
    by = load().registry.by_stage
    ext_fam = tuple(sorted(["assertion_outcomes", *AXIS5, "validator_rules", "validator_summaries"]))
    for s in ("capability_extraction", "task_extraction"):
        assert by[s].applicable_metric_families == ext_fam
        assert by[s].required_stage_evidence_kinds == ()
    assert by["universe_screen"].applicable_metric_families == tuple(sorted(
        ["assertion_outcomes", "screen_operational", "unsafe_exclusion",
         "validator_rules", "validator_summaries"]))
    assert by["universe_screen"].required_stage_evidence_kinds == (
        "universe_screen_operational", "universe_unsafe_exclusion_audit")
    assert by["universe_classification"].applicable_metric_families == tuple(sorted(
        ["assertion_outcomes", *AXIS5, "tier_contract", "validator_rules", "validator_summaries"]))
    assert by["universe_classification"].required_stage_evidence_kinds == ("universe_classification_tier",)
    for s in ("product_extraction", "task_measurement", "task_transition"):
        assert by[s].applicable_metric_families == ()
        assert by[s].required_stage_evidence_kinds == ()
        assert by[s].applicability_reason_codes == ("unsupported_evaluation_stage",)


# --- 6. ordering + duplicate rejection at every governed collection --------


def fixture_entry(stage: str) -> dict:
    return {e["evaluation_stage"]: e for e in base_doc()["entries"]}[stage]


def test_ordering_and_duplicate_rejections():
    # A real, alignment-valid supported entry (6 inapplicable families → 6 aligned
    # reason codes) is the base; each mutation below must be rejected.
    good = fixture_entry("universe_screen")
    fams = list(good["applicable_metric_families"])
    StageProfileEntry.model_validate(good)
    # unsorted / duplicate families
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate({**good, "applicable_metric_families": list(reversed(fams))})
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate({**good, "applicable_metric_families": [fams[0], fams[0]]})
    # unsorted / duplicate evidence
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate({**good, "required_stage_evidence_kinds": ["universe_unsafe_exclusion_audit", "universe_screen_operational"]})
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate({**good, "required_stage_evidence_kinds": ["universe_screen_operational", "universe_screen_operational"]})
    # unsorted / duplicate / blank / whitespace reasons
    for bad in (["b_reason", "a_reason"], ["a_reason", "a_reason"], [""], [" x"], ["x "]):
        with pytest.raises(PydanticValidationError):
            StageProfileEntry.model_validate({**good, "applicability_reason_codes": bad})
    # registry: unsorted entries + duplicate stage
    doc = base_doc()
    doc["entries"] = list(reversed(doc["entries"]))
    with pytest.raises(PydanticValidationError):
        StageProfileRegistry.model_validate(doc)
    doc2 = base_doc()
    doc2["entries"].append(copy.deepcopy(doc2["entries"][0]))
    with pytest.raises(PydanticValidationError):
        StageProfileRegistry.model_validate(doc2)


def test_unsupported_and_supported_structural_rules():
    # unsupported with families rejected
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate(entry_dict("s", "unsupported", ["assertion_outcomes"], [], ["unsupported_evaluation_stage"]))
    # unsupported wrong reason rejected
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate(entry_dict("s", "unsupported", [], [], ["other"]))
    # supported empty families rejected
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate(entry_dict("s", "fixture_backed", [], [], ["r"]))
    # non-working stage may not require stage evidence
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate(entry_dict("s", "fixture_backed", ["assertion_outcomes"], ["universe_screen_operational"], ["r"]))
    # registry_version must equal governed contract version
    doc = base_doc()
    doc["registry_version"] = "9.9.9"
    with pytest.raises(PydanticValidationError):
        StageProfileRegistry.model_validate(doc)


# --- 7. unknown / unsupported typed binding failures -----------------------


def test_resolve_unknown_and_unsupported():
    reg = load().registry
    with pytest.raises(StageProfileBindingError) as u:
        resolve_metric_applicability(reg, "nonexistent_stage")
    assert u.value.reason_code == "unknown_evaluation_stage" and u.value.evaluation_stage == "nonexistent_stage"
    with pytest.raises(StageProfileBindingError) as x:
        resolve_metric_applicability(reg, "product_extraction")
    assert x.value.reason_code == "unsupported_evaluation_stage"
    # supported resolves to the governed entry incl. hash
    entry = resolve_metric_applicability(reg, "universe_screen")
    assert entry.evaluation_stage == "universe_screen"
    assert entry.entry_hash == ENTRY_HASHES["universe_screen"]


# --- 8. selected-entry hash vs whole-registry hash independence -------------


def test_selected_entry_hash_independence():
    reg = load().registry
    for s, h in ENTRY_HASHES.items():
        assert reg.by_stage[s].entry_hash == h
    assert stage_profile_registry_hash(reg) == CONTENT_HASH
    # identical content -> same entry hash
    reg2 = load().registry
    assert reg2.by_stage["capability_extraction"].entry_hash == reg.by_stage["capability_extraction"].entry_hash
    # change a selected-entry semantic field -> its entry hash changes. The new
    # reason codes stay alignment-valid (correct canonical family prefixes) so the
    # entry still validates; only their suffixes differ.
    doc = base_doc()
    doc["entries"][0]["applicability_reason_codes"] = [
        "screen_operational_changed_reason",
        "tier_contract_changed_reason",
        "unsafe_exclusion_changed_reason",
    ]
    changed = StageProfileRegistry.model_validate(doc)
    assert changed.by_stage["capability_extraction"].entry_hash != ENTRY_HASHES["capability_extraction"]
    # change an unrelated entry -> registry hash changes, capability entry hash unchanged
    doc2 = base_doc()
    doc2["entries"][6]["applicability_reason_codes"] = [  # universe_screen, still aligned
        "axis_abstention_changed_for_screen",
        "axis_multi_label_changed_for_screen",
        "axis_nominal_single_label_changed_for_screen",
        "axis_ordinal_single_label_changed_for_screen",
        "axis_structured_set_changed_for_screen",
        "tier_contract_changed_for_screen",
    ]
    reg3 = StageProfileRegistry.model_validate(doc2)
    assert stage_profile_registry_hash(reg3) != CONTENT_HASH
    assert reg3.by_stage["capability_extraction"].entry_hash == ENTRY_HASHES["capability_extraction"]


# --- 9. determinism -------------------------------------------------------


def test_deterministic_repeated():
    a, b = load(), load()
    assert a.sha256 == b.sha256 == FIXTURE_SHA
    assert stage_profile_registry_hash(a.registry) == stage_profile_registry_hash(b.registry) == CONTENT_HASH
    assert resolve_metric_applicability(a.registry, "universe_screen").entry_hash == \
        resolve_metric_applicability(b.registry, "universe_screen").entry_hash


# --- 10. relative and contained-absolute loading --------------------------


def test_relative_and_contained_absolute():
    rel = load_stage_profile_registry(FIXTURE_REL, eval_root=ROOT)
    ab = load_stage_profile_registry(FIXTURE_ABS, eval_root=ROOT)
    assert rel.sha256 == ab.sha256 == FIXTURE_SHA
    assert rel.artifact_reference == ab.artifact_reference == FIXTURE_REL


# --- 11. loader failure surface -------------------------------------------


def test_invalid_eval_root():
    for bad in (123, "", "/nonexistent/root/xyz"):
        with pytest.raises(StageProfileError) as ei:
            load_stage_profile_registry(FIXTURE_REL, eval_root=bad)
        assert ei.value.reason_code in ("invalid_eval_root",)


def test_eval_root_not_a_directory(tmp_path):
    f = tmp_path / "afile"
    f.write_text("x")
    with pytest.raises(StageProfileError) as ei:
        load_stage_profile_registry("r.json", eval_root=f)
    assert ei.value.reason_code == "invalid_eval_root"


def test_path_escape(tmp_path):
    with pytest.raises(StageProfileError) as ei:
        load_stage_profile_registry("../outside.json", eval_root=tmp_path)
    assert ei.value.reason_code == "path_escape"


def test_symlink_root_and_artifact(tmp_path):
    real = tmp_path / "real"
    real.mkdir()
    (real / "r.json").write_bytes(FIXTURE_ABS.read_bytes())
    link = tmp_path / "link"
    link.symlink_to(real)
    with pytest.raises(StageProfileError) as ei:
        load_stage_profile_registry("r.json", eval_root=link)
    assert ei.value.reason_code == "eval_root_symlink"
    art_link = real / "alias.json"
    art_link.symlink_to(real / "r.json")
    with pytest.raises(StageProfileError) as ej:
        load_stage_profile_registry("alias.json", eval_root=real)
    assert ej.value.reason_code == "artifact_symlink"


def test_missing_and_directory_and_decode_and_json(tmp_path):
    with pytest.raises(StageProfileError) as m:
        load_stage_profile_registry("nope.json", eval_root=tmp_path)
    assert m.value.reason_code == "artifact_missing"
    (tmp_path / "adir").mkdir()
    with pytest.raises(StageProfileError) as d:
        load_stage_profile_registry("adir", eval_root=tmp_path)
    assert d.value.reason_code == "artifact_not_a_file"
    (tmp_path / "bad.json").write_bytes(b"\xff\xfe")
    with pytest.raises(StageProfileError) as u:
        load_stage_profile_registry("bad.json", eval_root=tmp_path)
    assert u.value.reason_code == "decode_error"
    (tmp_path / "j.json").write_bytes(b"{not json")
    with pytest.raises(StageProfileError) as j:
        load_stage_profile_registry("j.json", eval_root=tmp_path)
    assert j.value.reason_code == "json_error"


def test_duplicate_key_nonfinite_toplevel_model(tmp_path):
    (tmp_path / "dup.json").write_bytes(b'{"a":1,"a":2}')
    with pytest.raises(StageProfileError) as d:
        load_stage_profile_registry("dup.json", eval_root=tmp_path)
    assert d.value.reason_code == "duplicate_key"
    (tmp_path / "nf.json").write_bytes(b'{"a":NaN}')
    with pytest.raises(StageProfileError) as n:
        load_stage_profile_registry("nf.json", eval_root=tmp_path)
    assert n.value.reason_code == "non_finite"
    (tmp_path / "arr.json").write_bytes(b"[1,2]")
    with pytest.raises(StageProfileError) as t:
        load_stage_profile_registry("arr.json", eval_root=tmp_path)
    assert t.value.reason_code == "top_level_type"
    (tmp_path / "m.json").write_bytes(b'{"registry_version":"0.1.0"}')
    with pytest.raises(StageProfileError) as mo:
        load_stage_profile_registry("m.json", eval_root=tmp_path)
    assert mo.value.reason_code == "model_validation"


# --- 12. expected_sha256 ---------------------------------------------------


def test_expected_sha256():
    ok = load_stage_profile_registry(FIXTURE_REL, eval_root=ROOT, expected_sha256=FIXTURE_SHA)
    assert ok.sha256 == FIXTURE_SHA
    with pytest.raises(StageProfileError) as bad:
        load_stage_profile_registry(FIXTURE_REL, eval_root=ROOT, expected_sha256="NOThex")
    assert bad.value.reason_code == "snapshot_hash_mismatch"
    with pytest.raises(StageProfileError) as mm:
        load_stage_profile_registry(FIXTURE_REL, eval_root=ROOT, expected_sha256="a" * 64)
    assert mm.value.reason_code == "snapshot_hash_mismatch"


# --- 13. snapshot persistence ---------------------------------------------


def test_snapshot_canonical_newline_exclusive_readback(tmp_path):
    reg = load().registry
    (tmp_path / "run1").mkdir()
    persisted = persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id="run1")
    dest = tmp_path / "run1" / "snapshots" / "stage_profile_registry.json"
    data = dest.read_bytes()
    expected_bytes = canonical_contract_bytes(reg.model_dump(mode="json", exclude_unset=True)) + b"\n"
    assert data == expected_bytes
    assert data.endswith(b"\n") and not data.endswith(b"\n\n")
    assert persisted.sha256 == sha256_bytes(expected_bytes)
    assert persisted.sha256 != stage_profile_registry_hash(reg)  # newline vs content hash
    assert stage_profile_registry_hash(reg) == CONTENT_HASH
    assert persisted.artifact_reference == "run1/snapshots/stage_profile_registry.json"
    # exclusive write: second call refuses
    with pytest.raises(StageProfileError) as c:
        persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id="run1")
    assert c.value.reason_code == "snapshot_exists"


def test_snapshot_requires_run_dir_and_rejects_symlinks(tmp_path):
    reg = load().registry
    with pytest.raises(StageProfileError) as m:
        persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id="missing")
    assert m.value.reason_code == "run_directory_missing"
    with pytest.raises(StageProfileError):
        persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id="../escape")
    real = tmp_path / "realrun"
    real.mkdir()
    (tmp_path / "linkrun").symlink_to(real)
    with pytest.raises(StageProfileError) as s:
        persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id="linkrun")
    assert s.value.reason_code == "run_directory_symlink"


# --- Correction 1: fail-closed revalidation of bypassed instances ----------


def _tamper_one_entry(reg, index, update):
    """A registry copy (validators bypassed) with one entry field overwritten."""
    entries = list(reg.entries)
    entries[index] = entries[index].model_copy(update=update)
    return reg.model_copy(update={"entries": tuple(entries)})


def test_entry_hash_fails_closed_on_bypassed_supported_empty_families():
    reg = load().registry
    bad = reg.by_stage["capability_extraction"].model_copy(
        update={"applicable_metric_families": ()})
    with pytest.raises(StageProfileBindingError) as ei:
        bad.entry_hash
    assert ei.value.reason_code == "inconsistent_profile_binding"


def test_registry_hash_and_resolver_fail_closed_supported_empty_families():
    reg = load().registry
    bad_reg = _tamper_one_entry(reg, 0, {"applicable_metric_families": ()})
    with pytest.raises(StageProfileBindingError) as h:
        stage_profile_registry_hash(bad_reg)
    assert h.value.reason_code == "inconsistent_profile_binding"
    with pytest.raises(StageProfileBindingError) as r:
        resolve_metric_applicability(bad_reg, "capability_extraction")
    assert r.value.reason_code == "inconsistent_profile_binding"


def test_fail_closed_duplicate_registry_entries():
    reg = load().registry
    dup = reg.model_copy(update={"entries": reg.entries + (reg.entries[0],)})
    for call in (
        lambda: stage_profile_registry_hash(dup),
        lambda: resolve_metric_applicability(dup, "capability_extraction"),
    ):
        with pytest.raises(StageProfileBindingError) as ei:
            call()
        assert ei.value.reason_code == "duplicate_profile_binding"


def test_fail_closed_unsorted_registry_entries():
    reg = load().registry
    rev = reg.model_copy(update={"entries": tuple(reversed(reg.entries))})
    with pytest.raises(StageProfileBindingError) as ei:
        stage_profile_registry_hash(rev)
    assert ei.value.reason_code == "inconsistent_profile_binding"


def test_fail_closed_invalid_registry_version():
    reg = load().registry
    bad = reg.model_copy(update={"registry_version": "9.9.9"})
    with pytest.raises(StageProfileBindingError) as ei:
        stage_profile_registry_hash(bad)
    assert ei.value.reason_code == "inconsistent_profile_binding"


def test_fail_closed_invalid_nested_contract_stamp():
    reg = load().registry
    bad = reg.model_copy(update={
        "contract": reg.contract.model_copy(update={"contract_hash": "a" * 64})})
    with pytest.raises(StageProfileBindingError) as ei:
        stage_profile_registry_hash(bad)
    assert ei.value.reason_code == "inconsistent_profile_binding"


def test_fail_closed_invalid_reason_code_coverage():
    reg = load().registry
    bad_entry = reg.by_stage["universe_screen"].model_copy(
        update={"applicability_reason_codes": ("wrong_only_reason",)})
    with pytest.raises(StageProfileBindingError) as ei:
        bad_entry.entry_hash
    assert ei.value.reason_code == "inconsistent_profile_binding"
    bad_reg = _tamper_one_entry(reg, 6, {"applicability_reason_codes": ("wrong_only_reason",)})
    with pytest.raises(StageProfileBindingError) as r:
        resolve_metric_applicability(bad_reg, "universe_screen")
    assert r.value.reason_code == "inconsistent_profile_binding"


def test_fail_closed_invalid_required_stage_evidence_structure():
    reg = load().registry
    # capability_extraction is fixture_backed (non-working): requiring evidence is invalid
    bad_entry = reg.by_stage["capability_extraction"].model_copy(
        update={"required_stage_evidence_kinds": ("universe_screen_operational",)})
    with pytest.raises(StageProfileBindingError) as ei:
        bad_entry.entry_hash
    assert ei.value.reason_code == "inconsistent_profile_binding"
    bad_reg = _tamper_one_entry(reg, 0, {"required_stage_evidence_kinds": ("universe_screen_operational",)})
    with pytest.raises(StageProfileBindingError) as h:
        stage_profile_registry_hash(bad_reg)
    assert h.value.reason_code == "inconsistent_profile_binding"


def test_persist_fails_closed_on_bypassed_registry_and_leaves_nothing(tmp_path):
    reg = load().registry
    (tmp_path / "run").mkdir()
    bad_reg = _tamper_one_entry(reg, 0, {"applicable_metric_families": ()})
    with pytest.raises(StageProfileBindingError) as ei:
        persist_stage_profile_registry_snapshot(bad_reg, eval_root=tmp_path, eval_run_id="run")
    assert ei.value.reason_code == "inconsistent_profile_binding"
    assert not (tmp_path / "run" / "snapshots").exists()
    assert list((tmp_path / "run").iterdir()) == []


def test_valid_registry_revalidation_is_hash_stable():
    # Revalidation must not perturb a well-formed registry's locked identities.
    reg = load().registry
    assert stage_profile_registry_hash(reg) == CONTENT_HASH
    for s, h in ENTRY_HASHES.items():
        assert reg.by_stage[s].entry_hash == h


# --- Correction 2: one deterministic reason per inapplicable family --------


def test_reason_code_alignment_negatives():
    screen = fixture_entry("universe_screen")
    full = list(screen["applicability_reason_codes"])  # 6 aligned, sorted
    assert len(full) == 6
    # missing one
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate({**screen, "applicability_reason_codes": full[:-1]})
    # extra one (kept sorted so only the count/alignment is wrong)
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate(
            {**screen, "applicability_reason_codes": sorted(full + ["zzz_extra_reason"])})
    # wrong-family: a reason keyed to an APPLICABLE family (validator_rules) in
    # place of the inapplicable tier_contract slot
    wrong = sorted(full[:5] + ["validator_rules_inapplicable_for_screen"])
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate({**screen, "applicability_reason_codes": wrong})
    # misaligned: two reasons for axis_abstention, none for tier_contract
    mis = [
        "axis_abstention_a_reason", "axis_abstention_b_reason",
        "axis_multi_label_reason", "axis_nominal_single_label_reason",
        "axis_ordinal_single_label_reason", "axis_structured_set_reason",
    ]
    assert mis == sorted(mis) and len(set(mis)) == 6
    with pytest.raises(PydanticValidationError):
        StageProfileEntry.model_validate({**screen, "applicability_reason_codes": mis})
    # positive control: suffix-only change (family prefixes preserved) stays valid
    ok = [f.split("_inapplicable_")[0] + "_ok" for f in full]
    StageProfileEntry.model_validate({**screen, "applicability_reason_codes": ok})


def test_unsupported_reason_coverage_is_fixed():
    for stage in ("product_extraction", "task_measurement", "task_transition"):
        e = fixture_entry(stage)
        assert e["applicable_metric_families"] == []
        assert e["required_stage_evidence_kinds"] == []
        assert e["applicability_reason_codes"] == ["unsupported_evaluation_stage"]
        StageProfileEntry.model_validate(e)


# --- Correction 4: complete fail-closed matrix -----------------------------


def test_loader_read_error(tmp_path, monkeypatch):
    p = tmp_path / "r.json"
    p.write_bytes(FIXTURE_ABS.read_bytes())
    real = Path.read_bytes

    def boom(self, *a, **k):
        if self.name == "r.json":
            raise OSError("simulated read failure")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(StageProfileError) as ei:
        load_stage_profile_registry("r.json", eval_root=tmp_path)
    assert ei.value.reason_code == "read_error"


def test_loader_nested_parent_symlink_path_escape(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "r.json").write_bytes(FIXTURE_ABS.read_bytes())
    (root / "sub").symlink_to(outside, target_is_directory=True)
    with pytest.raises(StageProfileError) as ei:
        load_stage_profile_registry("sub/r.json", eval_root=root)
    assert ei.value.reason_code == "path_escape"


def test_snapshots_path_is_regular_file(tmp_path):
    reg = load().registry
    (tmp_path / "run").mkdir()
    (tmp_path / "run" / "snapshots").write_text("not a directory")
    with pytest.raises(StageProfileError) as ei:
        persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id="run")
    assert ei.value.reason_code == "snapshots_directory_not_a_directory"


def test_snapshots_directory_is_symlink(tmp_path):
    reg = load().registry
    (tmp_path / "run").mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (tmp_path / "run" / "snapshots").symlink_to(other, target_is_directory=True)
    with pytest.raises(StageProfileError) as ei:
        persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id="run")
    assert ei.value.reason_code == "snapshots_directory_symlink"


def test_destination_snapshot_is_symlink(tmp_path):
    reg = load().registry
    snaps = tmp_path / "run" / "snapshots"
    snaps.mkdir(parents=True)
    (snaps / "stage_profile_registry.json").symlink_to(tmp_path / "elsewhere")
    with pytest.raises(StageProfileError) as ei:
        persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id="run")
    assert ei.value.reason_code == "snapshot_exists"


def test_readback_hash_mismatch(tmp_path, monkeypatch):
    reg = load().registry
    (tmp_path / "run").mkdir()
    real = Path.read_bytes

    def tampered(self, *a, **k):
        if self.name == "stage_profile_registry.json":
            return b"tampered-content"
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_bytes", tampered)
    with pytest.raises(StageProfileError) as ei:
        persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id="run")
    assert ei.value.reason_code == "destination_hash_mismatch"


def test_invalid_eval_run_ids(tmp_path):
    reg = load().registry
    for bad in (123, "", "   ", " x", "x ", ".", "..", "a/b", "a\\b", "a\x00b"):
        with pytest.raises(StageProfileError) as ei:
            persist_stage_profile_registry_snapshot(reg, eval_root=tmp_path, eval_run_id=bad)
        assert ei.value.reason_code == "invalid_eval_run_id"


def test_duplicate_key_message_is_sanitized(tmp_path):
    (tmp_path / "dup.json").write_bytes(b'{"leaked_secret_key":1,"leaked_secret_key":2}')
    with pytest.raises(StageProfileError) as ei:
        load_stage_profile_registry("dup.json", eval_root=tmp_path)
    assert ei.value.reason_code == "duplicate_key"
    assert "leaked_secret_key" not in str(ei.value)
    assert "leaked_secret_key" not in str(ei.value.__cause__ or "")


def test_nonfinite_message_is_sanitized(tmp_path):
    (tmp_path / "nf.json").write_bytes(b'{"x":Infinity}')
    with pytest.raises(StageProfileError) as ei:
        load_stage_profile_registry("nf.json", eval_root=tmp_path)
    assert ei.value.reason_code == "non_finite"
    assert "Infinity" not in str(ei.value)
    assert "Infinity" not in str(ei.value.__cause__ or "")


def test_error_messages_hide_host_paths_and_content(tmp_path):
    (tmp_path / "j.json").write_bytes(b'{"MEGA_SECRET_TOKEN": not valid json here')
    with pytest.raises(StageProfileError) as ei:
        load_stage_profile_registry("j.json", eval_root=tmp_path)
    msg = str(ei.value)
    assert str(tmp_path) not in msg and "MEGA_SECRET_TOKEN" not in msg
    doc = base_doc()
    doc["registry_version"] = "LEAKED_VERSION_9_9_9"
    (tmp_path / "m.json").write_bytes(json.dumps(doc).encode("utf-8"))
    with pytest.raises(StageProfileError) as ej:
        load_stage_profile_registry("m.json", eval_root=tmp_path)
    mmsg = str(ej.value)
    assert str(tmp_path) not in mmsg and "LEAKED_VERSION" not in mmsg


# --- 14. import performs no filesystem I/O and no hashing ------------------


def test_import_no_io_no_hash():
    # Preload every unavoidable third-party dependency (jsonschema pulls its own
    # metaschema; pydantic and the universe package initialize), then drop ONLY
    # the target module and re-execute its body with all siblings already cached.
    # The module body must perform ZERO application-level Path reads (asserted as
    # an empty collection, not filtered by suffix), no writes, and no SHA-256 —
    # so an import-time read of ANY file (json/jsonl/yaml/toml/txt/...) through
    # the monitored Path APIs would fail this test.
    code = "\n".join([
        "import sys, os, hashlib, importlib",
        "sys.path.insert(0, 'src')",
        "from jsonschema import Draft202012Validator, FormatChecker",
        "import pydantic",
        "import dynamic_ai_products, dynamic_ai_products.universe.models, dynamic_ai_products.universe.io_utils",
        "import dynamic_ai_products.evaluation  # loads package + all siblings incl. the target",
        "del sys.modules['dynamic_ai_products.evaluation.stage_profiles']",
        "from pathlib import Path",
        "reads=[]; writes=[]; sha=[]",
        "orb, ort, omk, oop, osha = Path.read_bytes, Path.read_text, Path.mkdir, os.open, hashlib.sha256",
        "Path.read_bytes = lambda self,*a,**k:(reads.append(str(self)),orb(self,*a,**k))[1]",
        "Path.read_text = lambda self,*a,**k:(reads.append(str(self)),ort(self,*a,**k))[1]",
        "Path.mkdir = lambda self,*a,**k:(writes.append(('mkdir',str(self))),omk(self,*a,**k))[1]",
        "os.open = lambda *a,**k:(writes.append(('open',)),oop(*a,**k))[1]",
        "hashlib.sha256 = lambda *a,**k:(sha.append(1),osha(*a,**k))[1]",
        "importlib.import_module('dynamic_ai_products.evaluation.stage_profiles')",
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open,hashlib.sha256 = orb,ort,omk,oop,osha",
        "assert reads == [], ('UNEXPECTED_READS', reads)",
        "assert writes == [], ('UNEXPECTED_WRITES', writes)",
        "assert sha == [], ('UNEXPECTED_SHA', len(sha))",
        "print('OK')",
    ])
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr


# --- 15/16. exact ten exports + package parity ----------------------------


TEN_EXPORTS = [
    "StageProfileRegistry", "StageProfileEntry", "MetricFamily",
    "LoadedStageProfileRegistry", "load_stage_profile_registry",
    "persist_stage_profile_registry_snapshot", "stage_profile_registry_hash",
    "resolve_metric_applicability", "StageProfileError", "StageProfileBindingError"]


def test_module_all_is_exactly_the_ten():
    # The module's public surface is defined by __all__ — not inferred from a
    # __module__ filter — and must be exactly the ten authorized names.
    assert len(TEN_EXPORTS) == 10 and len(set(TEN_EXPORTS)) == 10
    assert isinstance(sp_mod.__all__, list)
    assert set(sp_mod.__all__) == set(TEN_EXPORTS)
    assert len(sp_mod.__all__) == 10 and len(set(sp_mod.__all__)) == 10


def test_import_star_exposes_exactly_the_ten():
    ns: dict = {}
    exec("from dynamic_ai_products.evaluation.stage_profiles import *", ns)
    exposed = {k for k in ns if not k.startswith("__")}
    assert exposed == set(TEN_EXPORTS)


def test_no_eleventh_slice_12a_api():
    # No public (non-underscore) symbol owned by the module may sit outside
    # __all__, and __all__ may not list a non-owned or private name. Ownership is
    # checked via __module__ here only to catch an accidental leak — it is not
    # used to define the surface (that is __all__ / import-star above).
    owned_public = {
        n for n, v in vars(sp_mod).items()
        if not n.startswith("_")
        and getattr(v, "__module__", None) == sp_mod.__name__
    } | {"MetricFamily"}  # a Literal alias carries no __module__
    assert owned_public <= set(sp_mod.__all__)
    assert set(sp_mod.__all__) <= owned_public
    for name in sp_mod.__all__:
        assert not name.startswith("_")


def test_package_reexports_ten_and_all_sorted_unique():
    # The ten Slice 12A exports must remain present and correctly re-exported,
    # and package __all__ must stay sorted and unique. This test deliberately
    # does not pin the package's global export count: later slices legitimately
    # add exports, and a frozen historical total must not make this stale.
    for name in TEN_EXPORTS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(sp_mod, name)
    al = list(evaluation_pkg.__all__)
    assert al == sorted(al) and len(al) == len(set(al))


# --- 17/18/19. manifest, no static schema, protected identities ------------


def test_repo_manifest_lists_three_slice_12a_paths_once():
    # The three Slice 12A paths must each appear exactly once. This test does
    # not pin the manifest's global total (a frozen literal would go stale as
    # later slices add manifest entries); manifest-total parity is asserted by
    # the repository-hygiene suite and the current slice's own manifest test.
    text = (ROOT / "REPO_MANIFEST.md").read_text(encoding="utf-8")
    for p in (
        "src/dynamic_ai_products/evaluation/stage_profiles.py",
        "tests/evaluation/test_stage_profiles.py",
        FIXTURE_REL,
    ):
        assert text.count(f"`{p}`") == 1


def test_no_static_schema_added():
    assert not (ROOT / "schemas" / "evaluation_stage_profile_registry.schema.json").exists()
    assert not (ROOT / "schemas" / "stage_profile_registry.schema.json").exists()


def test_protected_contract_identities_unchanged():
    from dynamic_ai_products.evaluation import comparator as cm
    from dynamic_ai_products.evaluation.models import EvaluationRunManifest, ValidatorFinding
    assert model_contract_hash(EvaluationRunManifest, "evaluation_run_manifest", "0.1.0") \
        == "7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee"
    assert model_contract_hash(ValidatorFinding, "validator_finding", "0.1.0") \
        == "96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292"
    assert model_contract_hash(cm.ComparisonManifest, "comparison_manifest", "0.2.0") \
        == "6a1253b72664bff73e872d1230fb3d52772a438f55915406010e105b4f5d29a5"
