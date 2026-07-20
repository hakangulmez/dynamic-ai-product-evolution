"""Slice 4: target/gold registry and case-reference resolution tests.

Option 1 semantics: an assertion's own ``semantic_version`` / ``contract_hash``
are preserved verbatim and never resolved against the target registry; only
``target_references`` drive target lookup. The tracked fixtures cover the
positive stop-point path; failure variants are generated under ``tmp_path``.
"""

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pydantic
import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation.cases import (
    InvalidEvaluationRootError,
    load_case,
)
from dynamic_ai_products.evaluation.models import EvaluationCase
from dynamic_ai_products.evaluation.references import (
    BlockingResolutionError,
    CaseResolution,
    LoadedTargetRegistry,
    ResolutionFinding,
    ResolvedAssertionReferences,
    ResolvedTargetReference,
    TargetRegistry,
    TargetRegistryArtifactNotAFileError,
    TargetRegistryDecodeError,
    TargetRegistryJsonError,
    TargetRegistryModelValidationError,
    TargetRegistryPathEscapeError,
    TargetRegistryTopLevelTypeError,
    load_target_registry,
    resolve_case_references,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "evals" / "fixtures" / "evaluation_harness" / "configs"
CASE_FIX = ROOT / "evals" / "fixtures" / "evaluation_harness" / "cases"

HASH_A = "1" * 64
HASH_B = "2" * 64


def contract(cid="synth-product-contract", ver="0.1.0", chash=HASH_A):
    return {"contract_id": cid, "contract_version": ver, "contract_hash": chash}


def entry(ref="SYNTH.T.ONE", kind="target", cid="synth-product-contract", ver="0.1.0",
          aliases=(), description=None):
    return {
        "reference_id": ref,
        "reference_kind": kind,
        "contract_id": cid,
        "contract_version": ver,
        "aliases": list(aliases),
        "description": description,
    }


def registry_payload(*, registry_version="synth-reg-v1", contracts=None, entries=None):
    return {
        "registry_version": registry_version,
        "contracts": contracts if contracts is not None else [contract()],
        "entries": entries if entries is not None else [entry()],
    }


def write(tmp_path: Path, content, name="registry.json") -> str:
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_text(json.dumps(content), encoding="utf-8")
    return name


def load_tmp(tmp_path: Path, content, **kw) -> LoadedTargetRegistry:
    name = write(tmp_path, content)
    return load_target_registry(name, eval_root=tmp_path, **kw)


def assertion(aid, *, semver="0.1.0", chash=None, targets=("SYNTH.T.ONE",),
              scorings=("synth-scoring-gate-ref-0001",)):
    payload = {
        "assertion_id": aid,
        "kind": "expected_entity",
        "target_references": list(targets),
        "scoring_gate_config_references": list(scorings),
    }
    if semver is not None:
        payload["semantic_version"] = semver
    if chash is not None:
        payload["contract_hash"] = chash
    return payload


def build_case(assertions, case_id="SYNTH-CASE-X"):
    return EvaluationCase.model_validate(
        {
            "case_id": case_id,
            "stage": "task_extraction",
            "stage_context": {},
            "input_source_ids": ["s"],
            "input_passage_ids": ["p"],
            "assertions": assertions,
            "failure_tags": [],
            "notes": "n",
            "created_by": "c",
            "created_at": "2026-07-19T00:00:00Z",
            "guideline_version": "g",
        }
    )


TRACKED_CONFIG = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FIX)


# --- Loader success and binding ------------------------------------------


def test_loads_tracked_fixture() -> None:
    loaded = load_target_registry("valid_target_registry.json", eval_root=FIX)
    assert isinstance(loaded, LoadedTargetRegistry)
    assert isinstance(loaded.registry, TargetRegistry)
    assert loaded.version == "synth-target-registry-v1"
    assert [e.reference_id for e in loaded.registry.entries][0] == "SYNTH.PRODUCT.CAPABILITY.TASK"


def test_frozen_model() -> None:
    loaded = load_target_registry("valid_target_registry.json", eval_root=FIX)
    with pytest.raises(pydantic.ValidationError):
        loaded.registry.registry_version = "mutated"  # type: ignore[misc]


def test_reloads_equal_but_distinct() -> None:
    a = load_target_registry("valid_target_registry.json", eval_root=FIX)
    b = load_target_registry("valid_target_registry.json", eval_root=FIX)
    assert a == b and a is not b


def test_raw_byte_hash(tmp_path: Path) -> None:
    name = write(tmp_path, registry_payload())
    loaded = load_target_registry(name, eval_root=tmp_path)
    assert loaded.sha256 == sha256_bytes((tmp_path / name).read_bytes())


def test_expected_matching_hash() -> None:
    observed = sha256_bytes((FIX / "valid_target_registry.json").read_bytes())
    loaded = load_target_registry(
        "valid_target_registry.json", eval_root=FIX, expected_sha256=observed
    )
    assert loaded.sha256 == observed


def test_absent_expected_hash_binding(tmp_path: Path) -> None:
    loaded = load_tmp(tmp_path, registry_payload())
    assert len(loaded.sha256) == 64


def test_explicit_dot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write(tmp_path, registry_payload())
    monkeypatch.chdir(tmp_path)
    assert isinstance(
        load_target_registry("registry.json", eval_root="."), LoadedTargetRegistry
    )


# --- Path and strict parsing ---------------------------------------------


def test_omitted_root_typeerror() -> None:
    with pytest.raises(TypeError):
        load_target_registry("r.json")  # type: ignore[call-arg]


def test_none_root() -> None:
    with pytest.raises(InvalidEvaluationRootError):
        load_target_registry("r.json", eval_root=None)  # type: ignore[arg-type]


def test_empty_root() -> None:
    with pytest.raises(InvalidEvaluationRootError):
        load_target_registry("r.json", eval_root="")


def test_nonexistent_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidEvaluationRootError):
        load_target_registry("r.json", eval_root=tmp_path / "missing")


def test_file_root(tmp_path: Path) -> None:
    write(tmp_path, registry_payload(), "not-a-dir.json")
    with pytest.raises(InvalidEvaluationRootError):
        load_target_registry("r.json", eval_root=tmp_path / "not-a-dir.json")


def test_absolute_contained(tmp_path: Path) -> None:
    write(tmp_path, registry_payload())
    assert isinstance(
        load_target_registry(str(tmp_path / "registry.json"), eval_root=tmp_path),
        LoadedTargetRegistry,
    )


def test_traversal_escape(tmp_path: Path) -> None:
    write(tmp_path, registry_payload(), "outside.json")
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(TargetRegistryPathEscapeError):
        load_target_registry("../outside.json", eval_root=root)


def test_symlink_escape_hides_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret"
    outside.mkdir()
    write(outside, registry_payload(), "r.json")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.json").symlink_to(outside / "r.json")
    with pytest.raises(TargetRegistryPathEscapeError) as excinfo:
        load_target_registry("link.json", eval_root=root)
    assert "outside-secret" not in str(excinfo.value)
    assert excinfo.value.artifact_reference == "link.json"


def test_root_symlink(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    write(real, registry_payload())
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    assert isinstance(
        load_target_registry("registry.json", eval_root=link), LoadedTargetRegistry
    )


def test_prefix_confusion(tmp_path: Path) -> None:
    root = tmp_path / "evals"
    root.mkdir()
    sibling = tmp_path / "evals-escape"
    sibling.mkdir()
    write(sibling, registry_payload(), "r.json")
    with pytest.raises(TargetRegistryPathEscapeError):
        load_target_registry(str(sibling / "r.json"), eval_root=root)


def test_missing_registry_is_blocking(tmp_path: Path) -> None:
    with pytest.raises(BlockingResolutionError) as excinfo:
        load_target_registry("missing.json", eval_root=tmp_path)
    assert excinfo.value.failure_kind == "registry_artifact_missing"
    assert excinfo.value.rule_id == "slice4.registry_artifact_missing"
    assert excinfo.value.artifact_reference == "missing.json"


def test_directory_instead_of_file(tmp_path: Path) -> None:
    (tmp_path / "a-dir").mkdir()
    with pytest.raises(TargetRegistryArtifactNotAFileError):
        load_target_registry("a-dir", eval_root=tmp_path)


def test_invalid_utf8(tmp_path: Path) -> None:
    write(tmp_path, b"\xff\xfe{}")
    with pytest.raises(TargetRegistryDecodeError):
        load_target_registry("registry.json", eval_root=tmp_path)


def test_bom(tmp_path: Path) -> None:
    write(tmp_path, b"\xef\xbb\xbf" + json.dumps(registry_payload()).encode())
    with pytest.raises(TargetRegistryJsonError):
        load_target_registry("registry.json", eval_root=tmp_path)


def test_malformed_json(tmp_path: Path) -> None:
    write(tmp_path, "{not json")
    with pytest.raises(TargetRegistryJsonError):
        load_target_registry("registry.json", eval_root=tmp_path)


def test_trailing_content(tmp_path: Path) -> None:
    write(tmp_path, json.dumps(registry_payload()) + " x")
    with pytest.raises(TargetRegistryJsonError):
        load_target_registry("registry.json", eval_root=tmp_path)


def test_duplicate_top_level_key(tmp_path: Path) -> None:
    write(tmp_path, '{"registry_version": "a", "registry_version": "b"}')
    with pytest.raises(TargetRegistryJsonError) as excinfo:
        load_target_registry("registry.json", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "registry_version"


def test_duplicate_nested_key(tmp_path: Path) -> None:
    write(tmp_path, '{"contracts": [{"contract_id": "a", "contract_id": "b"}]}')
    with pytest.raises(TargetRegistryJsonError) as excinfo:
        load_target_registry("registry.json", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "contract_id"


@pytest.mark.parametrize("text", ["[1]", '"x"', "null"])
def test_non_object_top_level(tmp_path: Path, text: str) -> None:
    write(tmp_path, text)
    with pytest.raises(TargetRegistryTopLevelTypeError):
        load_target_registry("registry.json", eval_root=tmp_path)


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_nonfinite(tmp_path: Path, constant: str) -> None:
    write(tmp_path, '{"x": ' + constant + "}")
    with pytest.raises(TargetRegistryJsonError) as excinfo:
        load_target_registry("registry.json", eval_root=tmp_path)
    assert excinfo.value.constant_name == constant


def test_overflow_infinity(tmp_path: Path) -> None:
    write(tmp_path, '{"x": -1e999}')
    with pytest.raises(TargetRegistryJsonError) as excinfo:
        load_target_registry("registry.json", eval_root=tmp_path)
    assert excinfo.value.constant_name == "-Infinity"


# --- Expected hashes ------------------------------------------------------


def test_expected_hash_mismatch(tmp_path: Path) -> None:
    name = write(tmp_path, registry_payload())
    with pytest.raises(BlockingResolutionError) as excinfo:
        load_target_registry(name, eval_root=tmp_path, expected_sha256="0" * 64)
    exc = excinfo.value
    assert exc.failure_kind == "snapshot_hash_mismatch"
    assert exc.expected_sha256 == "0" * 64 and len(exc.observed_sha256) == 64


def test_malformed_expected_hash(tmp_path: Path) -> None:
    name = write(tmp_path, registry_payload())
    with pytest.raises(BlockingResolutionError) as excinfo:
        load_target_registry(name, eval_root=tmp_path, expected_sha256="XYZ")
    assert excinfo.value.expected_sha256 is None
    assert "XYZ" not in str(excinfo.value)


# --- Target registry validation ------------------------------------------


def expect_blocking(tmp_path: Path, payload, kind):
    write(tmp_path, payload)
    with pytest.raises(BlockingResolutionError) as excinfo:
        load_target_registry("registry.json", eval_root=tmp_path)
    assert excinfo.value.failure_kind == kind
    return excinfo.value


def test_duplicate_canonical_id(tmp_path: Path) -> None:
    exc = expect_blocking(
        tmp_path,
        registry_payload(entries=[entry(ref="DUP"), entry(ref="DUP")]),
        "duplicate_reference_id",
    )
    assert exc.reference_id == "DUP"


def test_alias_duplicated_within_entry(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        registry_payload(entries=[entry(ref="A", aliases=["X", "X"])]),
        "conflicting_reference_definition",
    )


def test_alias_collision_across_entries(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        registry_payload(
            entries=[entry(ref="A", aliases=["SHARED"]), entry(ref="B", aliases=["SHARED"])]
        ),
        "conflicting_reference_definition",
    )


def test_alias_collides_with_canonical(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        registry_payload(entries=[entry(ref="A"), entry(ref="B", aliases=["A"])]),
        "conflicting_reference_definition",
    )


def test_alias_equals_own_canonical(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        registry_payload(entries=[entry(ref="A", aliases=["A"])]),
        "conflicting_reference_definition",
    )


def test_duplicate_contract_identity(tmp_path: Path) -> None:
    expect_blocking(
        tmp_path,
        registry_payload(contracts=[contract(), contract(chash=HASH_B)]),
        "conflicting_reference_definition",
    )


def test_unknown_entry_contract_version(tmp_path: Path) -> None:
    exc = expect_blocking(
        tmp_path,
        registry_payload(
            contracts=[contract()],
            entries=[entry(ref="A", ver="9.9.9")],
        ),
        "unknown_contract_version",
    )
    assert exc.reference_id == "A"


def test_malformed_contract_hash(tmp_path: Path) -> None:
    write(tmp_path, registry_payload(contracts=[contract(chash="short")]))
    with pytest.raises(TargetRegistryModelValidationError):
        load_target_registry("registry.json", eval_root=tmp_path)


def test_accepted_alias_resolves_to_canonical() -> None:
    registry = load_target_registry("valid_target_registry.json", eval_root=FIX)
    case = build_case([assertion("A1", targets=("SYNTH.ALIAS.TASK",))])
    res = resolve_case_references(case, registry=registry, scoring_config=TRACKED_CONFIG)
    t = res.assertions[0].target_references[0]
    assert t.requested_reference_id == "SYNTH.ALIAS.TASK"
    assert t.canonical_reference_id == "SYNTH.PRODUCT.CAPABILITY.TASK"


def test_registry_order_preserved() -> None:
    registry = load_target_registry("valid_target_registry.json", eval_root=FIX)
    assert [e.reference_id for e in registry.registry.entries] == [
        "SYNTH.PRODUCT.CAPABILITY.TASK",
        "SYNTH.PRODUCT.ALPHA",
        "SYNTH.PRODUCT.ALPHA.CAPABILITY",
        "SYNTH.PRODUCT.ROADMAP_ONLY",
    ]


# --- Assertion identity is preserved, not registry-resolved (Option 1) ----


def test_assertion_semantic_version_preserved() -> None:
    registry = load_target_registry("valid_target_registry.json", eval_root=FIX)
    case = load_case("valid_full_case.json", eval_root=CASE_FIX)
    res = resolve_case_references(case, registry=registry, scoring_config=TRACKED_CONFIG)
    assert res.assertions[0].assertion_semantic_version == "0.1.0"
    assert res.assertions[0].assertion_contract_hash is None


def test_assertion_contract_hash_preserved() -> None:
    registry = load_target_registry("valid_target_registry.json", eval_root=FIX)
    case = load_case("valid_full_case.json", eval_root=CASE_FIX)
    res = resolve_case_references(case, registry=registry, scoring_config=TRACKED_CONFIG)
    assert res.assertions[1].assertion_semantic_version is None
    assert (
        res.assertions[1].assertion_contract_hash
        == "synthetic-opaque-assertion-contract-identity-0002"
    )


def test_semantic_version_only_needs_no_registry_version_lookup(tmp_path: Path) -> None:
    # Registry contract version deliberately differs from assertion semantic_version.
    reg = load_tmp(
        tmp_path,
        registry_payload(
            contracts=[contract(ver="7.7.7")],
            entries=[entry(ref="SYNTH.T.ONE", ver="7.7.7")],
        ),
    )
    case = build_case([assertion("A1", semver="0.1.0", targets=("SYNTH.T.ONE",))])
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert res.assertions[0].assertion_semantic_version == "0.1.0"
    assert res.assertions[0].target_references[0].contract_version == "7.7.7"


def test_contract_hash_only_assertion_needs_no_hash_lookup(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    case = build_case(
        [assertion("A1", semver=None, chash="opaque-assertion-hash", targets=("SYNTH.T.ONE",))]
    )
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert res.assertions[0].assertion_contract_hash == "opaque-assertion-hash"


def test_opaque_assertion_hash_absent_from_registry_does_not_block(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    case = build_case(
        [assertion("A1", semver=None, chash="never-in-registry", targets=("SYNTH.T.ONE",))]
    )
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert res.assertions[0].target_references[0].canonical_reference_id == "SYNTH.T.ONE"


def test_same_semantic_version_different_registry_contracts(tmp_path: Path) -> None:
    reg = load_tmp(
        tmp_path,
        registry_payload(
            contracts=[
                contract(cid="synth-contract-a", chash=HASH_A),
                contract(cid="synth-contract-b", chash=HASH_B),
            ],
            entries=[
                entry(ref="T.A", cid="synth-contract-a"),
                entry(ref="T.B", cid="synth-contract-b"),
            ],
        ),
    )
    case = build_case(
        [
            assertion("A1", semver="0.1.0", targets=("T.A",)),
            assertion("A2", semver="0.1.0", targets=("T.B",)),
        ]
    )
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert res.assertions[0].target_references[0].contract_id == "synth-contract-a"
    assert res.assertions[1].target_references[0].contract_id == "synth-contract-b"


def test_one_assertion_targets_backed_by_different_contracts(tmp_path: Path) -> None:
    reg = load_tmp(
        tmp_path,
        registry_payload(
            contracts=[
                contract(cid="synth-contract-a", chash=HASH_A),
                contract(cid="synth-contract-b", chash=HASH_B),
            ],
            entries=[
                entry(ref="T.A", cid="synth-contract-a"),
                entry(ref="T.B", cid="synth-contract-b"),
            ],
        ),
    )
    case = build_case([assertion("A1", targets=("T.A", "T.B"))])
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    kinds = [t.contract_id for t in res.assertions[0].target_references]
    assert kinds == ["synth-contract-a", "synth-contract-b"]


# --- Case target resolution ----------------------------------------------


def test_all_tracked_targets_resolve() -> None:
    registry = load_target_registry("valid_target_registry.json", eval_root=FIX)
    for name in ("valid_minimal_case.json", "valid_full_case.json"):
        case = load_case(name, eval_root=CASE_FIX)
        res = resolve_case_references(case, registry=registry, scoring_config=TRACKED_CONFIG)
        assert isinstance(res, CaseResolution)


def test_missing_target_reference(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    case = build_case([assertion("A1", targets=("NOPE",))])
    with pytest.raises(BlockingResolutionError) as excinfo:
        resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    exc = excinfo.value
    assert exc.failure_kind == "unresolvable_target_reference"
    assert exc.case_id == "SYNTH-CASE-X"
    assert exc.assertion_id == "A1"
    assert exc.reference_id == "NOPE"


def test_assertion_and_target_order_preserved(tmp_path: Path) -> None:
    reg = load_tmp(
        tmp_path,
        registry_payload(entries=[entry(ref="T.1"), entry(ref="T.2"), entry(ref="T.3")]),
    )
    case = build_case(
        [
            assertion("A1", targets=("T.2", "T.1")),
            assertion("A2", targets=("T.3",)),
        ]
    )
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert [a.assertion_id for a in res.assertions] == ["A1", "A2"]
    assert [t.requested_reference_id for t in res.assertions[0].target_references] == [
        "T.2",
        "T.1",
    ]


def test_first_deterministic_target_failure(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload(entries=[entry(ref="T.1")]))
    case = build_case([assertion("A1", targets=("T.1", "MISS-A", "MISS-B"))])
    with pytest.raises(BlockingResolutionError) as excinfo:
        resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert excinfo.value.reference_id == "MISS-A"


# --- Case scoring-reference resolution ------------------------------------


def test_scoring_gate_resolution(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    case = build_case([assertion("A1", scorings=("synth-scoring-gate-ref-0001",))])
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert res.assertions[0].scoring_references[0].definition_kind == "gate"


def test_scoring_diagnostic_resolution(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    case = build_case([assertion("A1", scorings=("synth-scoring-gate-ref-0002",))])
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert res.assertions[0].scoring_references[0].definition_kind == "diagnostic"


def test_missing_scoring_reference(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    case = build_case([assertion("A1", scorings=("synth-missing-ref",))])
    with pytest.raises(BlockingResolutionError) as excinfo:
        resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert excinfo.value.failure_kind == "unresolvable_scoring_gate_config_reference"
    assert excinfo.value.reference_id == "synth-missing-ref"


def test_scoring_order_preserved(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    case = build_case(
        [
            assertion(
                "A1",
                scorings=("synth-scoring-gate-ref-0002", "synth-scoring-gate-ref-0001"),
            )
        ]
    )
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    assert [s.requested_reference_id for s in res.assertions[0].scoring_references] == [
        "synth-scoring-gate-ref-0002",
        "synth-scoring-gate-ref-0001",
    ]


# --- Blocking finding material for every failure kind ---------------------


def _trigger(kind: str, tmp_path: Path, reg: LoadedTargetRegistry):
    from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config as lc

    if kind == "registry_artifact_missing":
        return lambda: load_target_registry("missing.json", eval_root=tmp_path)
    if kind == "config_artifact_missing":
        return lambda: lc("missing.json", eval_root=tmp_path)
    if kind == "unknown_contract_version":
        write(tmp_path, registry_payload(entries=[entry(ref="A", ver="9.9.9")]), "u.json")
        return lambda: load_target_registry("u.json", eval_root=tmp_path)
    if kind == "snapshot_hash_mismatch":
        write(tmp_path, registry_payload(), "h.json")
        return lambda: load_target_registry(
            "h.json", eval_root=tmp_path, expected_sha256="0" * 64
        )
    if kind == "duplicate_reference_id":
        write(tmp_path, registry_payload(entries=[entry(ref="D"), entry(ref="D")]), "d.json")
        return lambda: load_target_registry("d.json", eval_root=tmp_path)
    if kind == "conflicting_reference_definition":
        write(tmp_path, registry_payload(entries=[entry(ref="A", aliases=["A"])]), "c.json")
        return lambda: load_target_registry("c.json", eval_root=tmp_path)
    if kind == "unresolvable_target_reference":
        return lambda: resolve_case_references(
            build_case([assertion("A1", targets=("NOPE",))]),
            registry=reg,
            scoring_config=TRACKED_CONFIG,
        )
    return lambda: resolve_case_references(
        build_case([assertion("A1", scorings=("MISS",))]),
        registry=reg,
        scoring_config=TRACKED_CONFIG,
    )


ALL_FAILURE_KINDS = (
    "registry_artifact_missing",
    "config_artifact_missing",
    "unknown_contract_version",
    "snapshot_hash_mismatch",
    "duplicate_reference_id",
    "conflicting_reference_definition",
    "unresolvable_target_reference",
    "unresolvable_scoring_gate_config_reference",
)


@pytest.mark.parametrize("kind", ALL_FAILURE_KINDS)
def test_failure_kind_has_stable_rule_id_and_finding(kind: str, tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    trigger = _trigger(kind, tmp_path, reg)
    with pytest.raises(BlockingResolutionError) as excinfo:
        trigger()
    exc = excinfo.value
    assert exc.failure_kind == kind
    assert exc.rule_id == f"slice4.{kind}"
    assert isinstance(exc.finding, ResolutionFinding)
    assert exc.finding.rule_id == f"slice4.{kind}"
    assert exc.finding.message


def test_finding_is_immutable() -> None:
    finding = ResolutionFinding(
        failure_kind="unresolvable_target_reference",
        rule_id="slice4.unresolvable_target_reference",
        message="m",
    )
    with pytest.raises(pydantic.ValidationError):
        finding.message = "x"  # type: ignore[misc]


def test_finding_has_no_severity_or_run_fields() -> None:
    fields = set(ResolutionFinding.model_fields)
    assert "severity" not in fields
    assert "run_id" not in fields
    assert "validator_bundle_version" not in fields


# --- Resolved-versus-unsatisfied distinction -----------------------------


def test_resolution_success_is_not_satisfaction(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    case = build_case([assertion("A1", targets=("SYNTH.T.ONE",))])
    res = resolve_case_references(case, registry=reg, scoring_config=TRACKED_CONFIG)
    # A resolved reference carries identities only — no outcome/metric/verdict.
    fields = set(ResolvedAssertionReferences.model_fields)
    assert "outcome" not in fields and "verdict" not in fields
    assert not hasattr(res, "execution_status")
    assert isinstance(res.assertions[0].target_references[0], ResolvedTargetReference)


# --- Type guards ----------------------------------------------------------


def test_resolve_requires_evaluation_case(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    with pytest.raises(TypeError):
        resolve_case_references({"case_id": "x"}, registry=reg, scoring_config=TRACKED_CONFIG)  # type: ignore[arg-type]


def test_resolve_requires_loaded_wrappers(tmp_path: Path) -> None:
    reg = load_tmp(tmp_path, registry_payload())
    case = build_case([assertion("A1")])
    with pytest.raises(TypeError):
        resolve_case_references(case, registry=reg, scoring_config=object())  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        resolve_case_references(case, registry=object(), scoring_config=TRACKED_CONFIG)  # type: ignore[arg-type]


# --- Compatibility and imports -------------------------------------------


def test_slice_2_and_3_loaders_unchanged() -> None:
    case = load_case("valid_minimal_case.json", eval_root=CASE_FIX)
    assert case.case_id == "SYNTH-CASE-MIN-0001"


PUBLIC_FUNCTIONS = (
    "load_target_registry",
    "load_scoring_gate_config",
    "resolve_case_references",
)
PUBLIC_MODELS = (
    "TargetRegistry",
    "LoadedTargetRegistry",
    "ScoringGateConfig",
    "LoadedScoringGateConfig",
    "CaseResolution",
    "ResolutionFinding",
    "BlockingResolutionError",
)


def test_public_symbols_exported() -> None:
    for name in PUBLIC_FUNCTIONS + PUBLIC_MODELS:
        assert name in evaluation_pkg.__all__
        assert hasattr(evaluation_pkg, name)


def test_package_all_parity_exact() -> None:
    public = {
        name
        for name in dir(evaluation_pkg)
        if not name.startswith("_")
        and not inspect.ismodule(getattr(evaluation_pkg, name))
    }
    assert set(evaluation_pkg.__all__) == public


def test_private_helpers_not_exported() -> None:
    for name in (
        "_blocking",
        "_resolve_contained",
        "_parse_json",
        "_DuplicateKeyControl",
        "_registry_lookups",
        "RULE_IDS",
    ):
        assert name not in evaluation_pkg.__all__


def test_package_import_no_io_or_hash() -> None:
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
        "sha = []\n"
        "orig_sha = hashlib.sha256\n"
        "hashlib.sha256 = lambda *a, **k: (sha.append(1), orig_sha(*a, **k))[1]\n"
        "import dynamic_ai_products.evaluation\n"
        "Path.read_bytes, Path.read_text = orig_rb, orig_rt\n"
        "hashlib.sha256 = orig_sha\n"
        "bad = [p for p in reads if p.endswith('.json') or p.endswith('.jsonl') "
        "or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad, bad\n"
        "assert not sha, 'sha256 called during import'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
