"""Slice 5: immutable evaluation-run identity and artifact persistence tests.

All run directories and failure variants are generated under ``tmp_path``; the
tracked Slice 4 scoring-config fixture is reused as the snapshot source. No
tracked Slice 5 fixture is added, and no execution status, verdict, prediction,
assertion, finding, metric or gate behavior is exercised here.
"""

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pydantic
import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import runs as runs_module
from dynamic_ai_products.evaluation.cases import InvalidEvaluationRootError
from dynamic_ai_products.evaluation.case_sets import (
    case_set_snapshot_hash,
    load_case_set_manifest,
)
from dynamic_ai_products.evaluation.contracts import (
    model_contract_hash,
    runtime_contract_provenance,
)
from dynamic_ai_products.evaluation.models import EvaluationRunManifest
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import (
    InitializedEvaluationRun,
    InvalidRunIdError,
    LoadedEvaluationRunManifest,
    RunArtifactNotAFileError,
    RunArtifactNotFoundError,
    RunDecodeError,
    RunDestinationHashMismatchError,
    RunDirectoryExistsError,
    RunJsonError,
    RunManifestConsistencyError,
    RunManifestModelValidationError,
    RunManifestSerializationError,
    RunPersistenceError,
    RunTopLevelTypeError,
    RunWriteError,
    SnapshotHashMismatchError,
    SnapshotReadError,
    SnapshotSourceMissingError,
    SnapshotSourceNotAFileError,
    SnapshotSourcePathEscapeError,
    initialize_evaluation_run,
    load_evaluation_run_manifest,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "evals" / "fixtures" / "evaluation_harness" / "configs"
CS = ROOT / "evals" / "fixtures" / "evaluation_harness" / "case_sets"

SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=CFG)
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=CFG)
CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=CS)
RUN_MANIFEST_CONTRACT_HASH = model_contract_hash(
    EvaluationRunManifest, "evaluation_run_manifest", "0.1.0"
)


def init(eval_root, run_id="synth-run-0001", *, source_root=CFG, **over):
    kwargs = {
        "eval_root": eval_root,
        "eval_run_id": run_id,
        "prediction_run_id": "synth-pred-run-1",
        "prediction_run_manifest_hash": "a" * 64,
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


# --- Successful initialization -------------------------------------------


def test_successful_initialization_layout(tmp_path: Path) -> None:
    r = init(tmp_path)
    run_dir = tmp_path / "synth-run-0001"
    assert run_dir.is_dir() and run_dir.name == "synth-run-0001"
    entries = sorted(p.relative_to(tmp_path).as_posix() for p in run_dir.rglob("*"))
    assert entries == [
        "synth-run-0001/evaluation_run_manifest.json",
        "synth-run-0001/snapshots",
        "synth-run-0001/snapshots/scoring_gate_config.json",
    ]
    assert isinstance(r, InitializedEvaluationRun)


def test_config_snapshot_bytes_preserved(tmp_path: Path) -> None:
    init(tmp_path)
    written = (tmp_path / "synth-run-0001/snapshots/scoring_gate_config.json").read_bytes()
    assert written == (CFG / "valid_scoring_gate_config.json").read_bytes()


def test_config_source_destination_hash_equal(tmp_path: Path) -> None:
    r = init(tmp_path)
    assert r.config_snapshot_sha256 == SCORING.sha256
    assert r.config_snapshot_sha256 == r.manifest.scoring_gate_config_hash


def test_manifest_hash_reproducible(tmp_path: Path) -> None:
    r = init(tmp_path)
    disk = (tmp_path / "synth-run-0001/evaluation_run_manifest.json").read_bytes()
    assert r.manifest_sha256 == sha256_bytes(disk)


def test_returned_wrapper_frozen(tmp_path: Path) -> None:
    r = init(tmp_path)
    with pytest.raises(pydantic.ValidationError):
        r.eval_run_id = "mutated"  # type: ignore[misc]


def test_all_manifest_pins_correct(tmp_path: Path) -> None:
    r = init(tmp_path)
    m = r.manifest
    assert m.eval_run_id == "synth-run-0001"
    assert m.prediction_run_id == "synth-pred-run-1"
    assert m.prediction_run_manifest_hash == "a" * 64
    assert m.validator_bundle_version == "synth-bundle-v1"
    assert m.validator_bundle_hash == "b" * 64
    assert m.code_commit == "synth-commit-deadbeef"


def test_case_set_hash_derived(tmp_path: Path) -> None:
    r = init(tmp_path)
    assert r.manifest.case_set_hash == case_set_snapshot_hash(CASE_SET)
    assert r.manifest.case_set_version == CASE_SET.case_set_version


def test_registry_hash_derived(tmp_path: Path) -> None:
    r = init(tmp_path)
    assert r.manifest.registry_snapshot_hash == REGISTRY.sha256


def test_scoring_version_hash_derived(tmp_path: Path) -> None:
    r = init(tmp_path)
    assert r.manifest.scoring_gate_config_version == SCORING.version
    assert r.manifest.scoring_gate_config_hash == SCORING.sha256


def test_runtime_version_derived_not_supplied(tmp_path: Path) -> None:
    r = init(tmp_path)
    assert r.manifest.pydantic_runtime_version == runtime_contract_provenance()["pydantic_version"]


def test_manifest_contract_metadata(tmp_path: Path) -> None:
    r = init(tmp_path)
    assert r.manifest.contract.contract_id == "evaluation_run_manifest"
    assert r.manifest.contract.contract_version == "0.1.0"
    assert r.manifest.contract.contract_hash == RUN_MANIFEST_CONTRACT_HASH


def test_manifest_reload(tmp_path: Path) -> None:
    r = init(tmp_path)
    loaded = load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)
    assert isinstance(loaded, LoadedEvaluationRunManifest)
    assert loaded.manifest == r.manifest
    assert loaded.sha256 == r.manifest_sha256
    assert loaded.artifact_reference == "synth-run-0001/evaluation_run_manifest.json"


def test_repeated_loads_equal_but_distinct(tmp_path: Path) -> None:
    init(tmp_path)
    a = load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)
    b = load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)
    assert a == b and a is not b


def test_no_later_slice_directories(tmp_path: Path) -> None:
    init(tmp_path)
    run_dir = tmp_path / "synth-run-0001"
    for forbidden in ("predictions", "results", "findings", "metrics", "gates", "comparisons", "logs", "raw"):
        assert not (run_dir / forbidden).exists()


def test_no_completion_or_status_marker(tmp_path: Path) -> None:
    init(tmp_path)
    names = {p.name for p in (tmp_path / "synth-run-0001").rglob("*")}
    assert not names & {"COMPLETED", "INVALID", "ERRORED", ".lock", "status.json"}


def test_explicit_dot_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    r = init(".")
    assert (tmp_path / "synth-run-0001").is_dir()
    assert r.eval_run_id == "synth-run-0001"


# --- Run-ID validation ----------------------------------------------------


@pytest.mark.parametrize(
    "bad",
    [123, None, "", "   ", " lead", "trail ", ".", "..", "a/b", "a\\b", "/abs", "x\x00y"],
)
def test_invalid_run_ids_rejected(tmp_path: Path, bad) -> None:
    with pytest.raises(InvalidRunIdError):
        init(tmp_path, run_id=bad)


@pytest.mark.parametrize("good", ["synth.run.1", "synth_run_1", "synth-run-1", "RUN0001"])
def test_valid_opaque_run_ids_accepted(tmp_path: Path, good: str) -> None:
    r = init(tmp_path, run_id=good)
    assert (tmp_path / good).is_dir() and r.eval_run_id == good


def test_run_directory_basename_equals_run_id(tmp_path: Path) -> None:
    init(tmp_path, run_id="synth.exact.name")
    assert (tmp_path / "synth.exact.name").is_dir()


# --- Root and path safety -------------------------------------------------


def test_omitted_eval_root_typeerror() -> None:
    with pytest.raises(TypeError):
        initialize_evaluation_run(  # type: ignore[call-arg]
            eval_run_id="x", prediction_run_id="p", prediction_run_manifest_hash="a" * 64,
            case_set=CASE_SET, registry=REGISTRY, validator_bundle_version="v",
            validator_bundle_hash="b" * 64, scoring_config=SCORING, code_commit="c",
            config_snapshot_source_root=CFG,
        )


def test_none_eval_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidEvaluationRootError):
        init(None)


def test_empty_eval_root() -> None:
    with pytest.raises(InvalidEvaluationRootError):
        init("")


def test_nonexistent_eval_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidEvaluationRootError):
        init(tmp_path / "missing")


def test_file_eval_root(tmp_path: Path) -> None:
    (tmp_path / "afile").write_text("x")
    with pytest.raises(InvalidEvaluationRootError):
        init(tmp_path / "afile")


def test_none_source_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidEvaluationRootError):
        init(tmp_path, source_root=None)


def test_nonexistent_source_root(tmp_path: Path) -> None:
    with pytest.raises(InvalidEvaluationRootError):
        init(tmp_path, source_root=tmp_path / "missing")


def test_eval_root_symlink_resolves(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)
    init(link)
    assert (real / "synth-run-0001").is_dir()


def test_snapshot_source_escaping_symlink_rejected(tmp_path: Path) -> None:
    # A symlink inside the source root that points outside it must be rejected
    # by resolved-path containment before any not-a-file check.
    src = tmp_path / "src"
    src.mkdir()
    outside = tmp_path / "outside-secret"
    outside.mkdir()
    (outside / "real.json").write_bytes((CFG / "valid_scoring_gate_config.json").read_bytes())
    (src / SCORING.artifact_reference).symlink_to(outside / "real.json")
    with pytest.raises(SnapshotSourcePathEscapeError) as excinfo:
        init(tmp_path, source_root=src)
    assert "outside-secret" not in str(excinfo.value)


def test_snapshot_source_missing(tmp_path: Path) -> None:
    empty = tmp_path / "empty_src"
    empty.mkdir()
    with pytest.raises(SnapshotSourceMissingError) as excinfo:
        init(tmp_path, source_root=empty)
    assert excinfo.value.source_artifact_reference == SCORING.artifact_reference


def test_snapshot_source_is_directory(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / SCORING.artifact_reference).mkdir()
    with pytest.raises(SnapshotSourceNotAFileError):
        init(tmp_path, source_root=src)


def test_snapshot_source_contained_symlink_rejected(tmp_path: Path) -> None:
    # A symlink that stays inside the source root is still not a regular file.
    src = tmp_path / "src"
    src.mkdir()
    (src / "real.json").write_bytes((CFG / "valid_scoring_gate_config.json").read_bytes())
    (src / SCORING.artifact_reference).symlink_to(src / "real.json")
    with pytest.raises(SnapshotSourceNotAFileError):
        init(tmp_path, source_root=src)


def test_snapshot_source_contained_dangling_symlink_rejected(tmp_path: Path) -> None:
    # A dangling final-component symlink whose target stays inside the source
    # root is classified as a non-file, not as a missing artifact: the symlink
    # itself is the (non-regular) source, and its target's absence must not
    # downgrade the classification.
    src = tmp_path / "src"
    src.mkdir()
    (src / SCORING.artifact_reference).symlink_to(src / "does-not-exist.json")
    with pytest.raises(SnapshotSourceNotAFileError) as excinfo:
        init(tmp_path, source_root=src)
    # A safe root-relative reference is fine; no absolute/external path leaks.
    assert str(tmp_path) not in str(excinfo.value)
    assert not (tmp_path / "synth-run-0001").exists()


def test_snapshot_source_read_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    real_read = Path.read_bytes

    def boom(self):
        if self.name == SCORING.artifact_reference:
            raise OSError("synthetic read failure")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", boom)
    with pytest.raises(SnapshotReadError):
        init(tmp_path)


def test_snapshot_source_hash_mismatch(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / SCORING.artifact_reference).write_text("tampered")
    with pytest.raises(SnapshotHashMismatchError) as excinfo:
        init(tmp_path, source_root=src)
    exc = excinfo.value
    assert exc.expected_sha256 == SCORING.sha256
    assert exc.observed_sha256 and exc.observed_sha256 != SCORING.sha256
    assert "tampered" not in str(exc)


def test_source_validated_before_run_directory(tmp_path: Path) -> None:
    empty = tmp_path / "empty_src"
    empty.mkdir()
    with pytest.raises(SnapshotSourceMissingError):
        init(tmp_path, source_root=empty)
    assert not (tmp_path / "synth-run-0001").exists()


# --- Refuse-to-overwrite --------------------------------------------------


def test_successful_run_id_cannot_be_reused(tmp_path: Path) -> None:
    init(tmp_path)
    with pytest.raises(RunDirectoryExistsError) as excinfo:
        init(tmp_path)
    assert excinfo.value.eval_run_id == "synth-run-0001"


def test_preexisting_directory_rejected(tmp_path: Path) -> None:
    (tmp_path / "synth-run-0001").mkdir()
    with pytest.raises(RunDirectoryExistsError):
        init(tmp_path)


def test_preexisting_file_rejected(tmp_path: Path) -> None:
    (tmp_path / "synth-run-0001").write_text("x")
    with pytest.raises(RunDirectoryExistsError):
        init(tmp_path)


def test_preexisting_symlink_rejected(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    target.mkdir()
    (tmp_path / "synth-run-0001").symlink_to(target, target_is_directory=True)
    with pytest.raises(RunDirectoryExistsError):
        init(tmp_path)


def test_no_silent_resume(tmp_path: Path) -> None:
    init(tmp_path)
    manifest_before = (tmp_path / "synth-run-0001/evaluation_run_manifest.json").read_bytes()
    with pytest.raises(RunDirectoryExistsError):
        init(tmp_path)
    after = (tmp_path / "synth-run-0001/evaluation_run_manifest.json").read_bytes()
    assert after == manifest_before


# --- Transaction behavior -------------------------------------------------


def test_manifest_validation_failure_no_directory(tmp_path: Path) -> None:
    with pytest.raises(RunManifestModelValidationError):
        init(tmp_path, prediction_run_manifest_hash="not-64-hex")
    assert not (tmp_path / "synth-run-0001").exists()


def test_serialization_failure_no_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(self, **kwargs):
        raise ValueError("synthetic serialization failure")

    monkeypatch.setattr(EvaluationRunManifest, "model_dump", boom)
    with pytest.raises(RunManifestSerializationError):
        init(tmp_path)
    assert not (tmp_path / "synth-run-0001").exists()


def test_source_failure_creates_no_directory(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (src / SCORING.artifact_reference).write_text("tampered")
    with pytest.raises(SnapshotHashMismatchError):
        init(tmp_path, source_root=src)
    assert not (tmp_path / "synth-run-0001").exists()


def test_snapshot_write_failure_preserves_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = runs_module.os.open

    def boom(path, flags, mode=0o777):
        if str(path).endswith("scoring_gate_config.json"):
            raise OSError("synthetic write failure")
        return real_open(path, flags, mode)

    monkeypatch.setattr(runs_module.os, "open", boom)
    with pytest.raises(RunWriteError):
        init(tmp_path)
    assert (tmp_path / "synth-run-0001").is_dir()
    assert not (tmp_path / "synth-run-0001/evaluation_run_manifest.json").exists()


def test_manifest_write_failure_preserves_directory_and_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_open = runs_module.os.open

    def boom(path, flags, mode=0o777):
        if str(path).endswith("evaluation_run_manifest.json"):
            raise OSError("synthetic write failure")
        return real_open(path, flags, mode)

    monkeypatch.setattr(runs_module.os, "open", boom)
    with pytest.raises(RunWriteError):
        init(tmp_path)
    assert (tmp_path / "synth-run-0001/snapshots/scoring_gate_config.json").is_file()
    assert not (tmp_path / "synth-run-0001/evaluation_run_manifest.json").exists()


def test_snapshot_destination_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_read = Path.read_bytes

    def tamper(self):
        if self.name == "scoring_gate_config.json" and "snapshots" in str(self):
            return b"tampered-destination"
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", tamper)
    with pytest.raises(RunDestinationHashMismatchError) as excinfo:
        init(tmp_path)
    assert excinfo.value.consistency_kind == "config_destination_hash_mismatch"


def test_manifest_destination_hash_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    real_read = Path.read_bytes

    def tamper(self):
        if self.name == "evaluation_run_manifest.json":
            return b"tampered-manifest"
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", tamper)
    with pytest.raises(RunDestinationHashMismatchError) as excinfo:
        init(tmp_path)
    assert excinfo.value.consistency_kind == "manifest_destination_hash_mismatch"


# --- Manifest serialization -----------------------------------------------


def test_manifest_canonical_serialization(tmp_path: Path) -> None:
    init(tmp_path)
    raw = (tmp_path / "synth-run-0001/evaluation_run_manifest.json").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert not raw.endswith(b"\n")
    text = raw.decode("utf-8")
    parsed = json.loads(text)
    assert text == json.dumps(parsed, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert "contract" in parsed


def test_manifest_has_no_status_or_verdict(tmp_path: Path) -> None:
    init(tmp_path)
    parsed = json.loads((tmp_path / "synth-run-0001/evaluation_run_manifest.json").read_text())
    for forbidden in ("execution_status", "gate_verdict", "lifecycle", "created_at", "timestamp"):
        assert forbidden not in parsed


def test_manifest_self_hash_not_embedded(tmp_path: Path) -> None:
    r = init(tmp_path)
    parsed = json.loads((tmp_path / "synth-run-0001/evaluation_run_manifest.json").read_text())
    assert r.manifest_sha256 not in json.dumps(parsed)


# --- Strict manifest loading ----------------------------------------------


def _write_manifest(tmp_path: Path, content, run_id="synth-run-0001") -> None:
    run_dir = tmp_path / run_id
    run_dir.mkdir(exist_ok=True)
    path = run_dir / "evaluation_run_manifest.json"
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_text(json.dumps(content), encoding="utf-8")


def _valid_manifest_dict():
    return {
        "contract": {
            "contract_id": "evaluation_run_manifest",
            "contract_version": "0.1.0",
            "contract_hash": RUN_MANIFEST_CONTRACT_HASH,
        },
        "eval_run_id": "synth-run-0001",
        "prediction_run_id": "p",
        "prediction_run_manifest_hash": "a" * 64,
        "case_set_version": "v",
        "case_set_hash": "c" * 64,
        "registry_snapshot_hash": "d" * 64,
        "validator_bundle_version": "vb",
        "validator_bundle_hash": "e" * 64,
        "scoring_gate_config_version": "sc",
        "scoring_gate_config_hash": "f" * 64,
        "code_commit": "commit",
        "pydantic_runtime_version": "2.13.4",
    }


def test_load_missing_manifest(tmp_path: Path) -> None:
    with pytest.raises(RunArtifactNotFoundError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_directory_instead_of_manifest(tmp_path: Path) -> None:
    (tmp_path / "synth-run-0001" / "evaluation_run_manifest.json").mkdir(parents=True)
    with pytest.raises(RunArtifactNotAFileError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_symlink_run_dir_rejected(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    _write_manifest(real, _valid_manifest_dict(), run_id=".")  # writes into real/
    (real / "evaluation_run_manifest.json").write_text(json.dumps(_valid_manifest_dict()))
    (tmp_path / "synth-run-0001").symlink_to(real, target_is_directory=True)
    with pytest.raises(RunArtifactNotAFileError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_invalid_utf8(tmp_path: Path) -> None:
    _write_manifest(tmp_path, b"\xff\xfe{}")
    with pytest.raises(RunDecodeError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_bom_rejected(tmp_path: Path) -> None:
    _write_manifest(tmp_path, b"\xef\xbb\xbf" + json.dumps(_valid_manifest_dict()).encode())
    with pytest.raises(RunJsonError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_malformed_json(tmp_path: Path) -> None:
    _write_manifest(tmp_path, "{not json")
    with pytest.raises(RunJsonError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_trailing_content(tmp_path: Path) -> None:
    _write_manifest(tmp_path, json.dumps(_valid_manifest_dict()) + " x")
    with pytest.raises(RunJsonError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_duplicate_top_level_key(tmp_path: Path) -> None:
    _write_manifest(tmp_path, '{"eval_run_id": "a", "eval_run_id": "b"}')
    with pytest.raises(RunJsonError) as excinfo:
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "eval_run_id"


def test_load_duplicate_nested_key(tmp_path: Path) -> None:
    _write_manifest(tmp_path, '{"contract": {"k": 1, "k": 2}}')
    with pytest.raises(RunJsonError) as excinfo:
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "k"


@pytest.mark.parametrize("text", ["[1]", '"x"', "null"])
def test_load_non_object_top_level(tmp_path: Path, text: str) -> None:
    _write_manifest(tmp_path, text)
    with pytest.raises(RunTopLevelTypeError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity", "1e999"])
def test_load_non_finite(tmp_path: Path, literal: str) -> None:
    _write_manifest(tmp_path, '{"x": ' + literal + "}")
    with pytest.raises(RunJsonError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_unknown_field(tmp_path: Path) -> None:
    d = _valid_manifest_dict()
    d["zzz"] = "x"
    _write_manifest(tmp_path, d)
    with pytest.raises(RunManifestModelValidationError) as excinfo:
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)
    assert "extra_forbidden" in excinfo.value.error_types


def test_load_missing_field(tmp_path: Path) -> None:
    d = _valid_manifest_dict()
    del d["code_commit"]
    _write_manifest(tmp_path, d)
    with pytest.raises(RunManifestModelValidationError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_bad_contract_hash(tmp_path: Path) -> None:
    d = _valid_manifest_dict()
    d["contract"]["contract_hash"] = "0" * 64
    _write_manifest(tmp_path, d)
    with pytest.raises(RunManifestModelValidationError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_bad_contract_id(tmp_path: Path) -> None:
    d = _valid_manifest_dict()
    d["contract"]["contract_id"] = "wrong"
    _write_manifest(tmp_path, d)
    with pytest.raises(RunManifestModelValidationError):
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)


def test_load_run_id_mismatch(tmp_path: Path) -> None:
    d = _valid_manifest_dict()
    d["eval_run_id"] = "different"
    _write_manifest(tmp_path, d)
    with pytest.raises(RunManifestConsistencyError) as excinfo:
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)
    assert excinfo.value.consistency_kind == "manifest_run_id_mismatch"


def test_load_error_no_value_leak(tmp_path: Path) -> None:
    d = _valid_manifest_dict()
    d["registry_snapshot_hash"] = "SYNTH-LEAK-MARKER"
    _write_manifest(tmp_path, d)
    with pytest.raises(RunManifestModelValidationError) as excinfo:
        load_evaluation_run_manifest("synth-run-0001", eval_root=tmp_path)
    assert "SYNTH-LEAK-MARKER" not in str(excinfo.value)


# --- Binding semantics ----------------------------------------------------


def test_registry_hash_binding_not_from_case_set(tmp_path: Path) -> None:
    r = init(tmp_path)
    assert r.manifest.registry_snapshot_hash == REGISTRY.sha256
    # The case-set manifest's own registry_snapshot_hash is a different field.
    assert CASE_SET.registry_snapshot_hash != REGISTRY.sha256


def test_prediction_and_validator_pins_preserved(tmp_path: Path) -> None:
    r = init(tmp_path, prediction_run_id="pr-42", validator_bundle_version="vb-9")
    assert r.manifest.prediction_run_id == "pr-42"
    assert r.manifest.validator_bundle_version == "vb-9"


# --- Compatibility --------------------------------------------------------


def test_slice_2_3_4_unchanged() -> None:
    from dynamic_ai_products.evaluation.cases import load_case
    case = load_case(
        "valid_minimal_case.json",
        eval_root=ROOT / "evals/fixtures/evaluation_harness/cases",
    )
    assert case.case_id == "SYNTH-CASE-MIN-0001"
    # Slice 3 hashing and Slice 4 loading remain callable and unchanged.
    assert len(case_set_snapshot_hash(CASE_SET)) == 64
    assert REGISTRY.version == "synth-target-registry-v1"


# --- Exports and import behavior ------------------------------------------

PUBLIC_FUNCTIONS = ("initialize_evaluation_run", "load_evaluation_run_manifest")
PUBLIC_MODELS = ("InitializedEvaluationRun", "LoadedEvaluationRunManifest")
PUBLIC_EXCEPTIONS = (
    "RunPersistenceError", "InvalidRunIdError", "RunDirectoryExistsError",
    "RunPathEscapeError", "RunDestinationCollisionError", "RunWriteError",
    "RunDestinationHashMismatchError", "SnapshotSourceMissingError",
    "SnapshotSourceNotAFileError", "SnapshotSourcePathEscapeError", "SnapshotReadError",
    "SnapshotHashMismatchError", "RunArtifactNotFoundError", "RunArtifactNotAFileError",
    "RunReadError", "RunDecodeError", "RunJsonError", "RunTopLevelTypeError",
    "RunManifestModelValidationError", "RunManifestConsistencyError",
    "RunManifestSerializationError",
)


def test_public_symbols_exported() -> None:
    for name in PUBLIC_FUNCTIONS + PUBLIC_MODELS + PUBLIC_EXCEPTIONS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(runs_module, name)


def test_package_all_parity_exact() -> None:
    public = {
        n for n in dir(evaluation_pkg)
        if not n.startswith("_") and not inspect.ismodule(getattr(evaluation_pkg, n))
    }
    assert set(evaluation_pkg.__all__) == public


def test_private_helpers_not_exported() -> None:
    for name in ("_exclusive_write", "_canonical_bytes", "_validate_run_id",
                 "_DuplicateKeyControl", "_resolve_contained", "_serialize_manifest"):
        assert name not in evaluation_pkg.__all__
        assert not hasattr(evaluation_pkg, name)


def test_exception_hierarchy() -> None:
    for name in PUBLIC_EXCEPTIONS:
        cls = getattr(runs_module, name)
        if name == "RunPersistenceError":
            assert cls.__bases__ == (Exception,)
        else:
            assert issubclass(cls, RunPersistenceError)


def test_package_import_no_io_or_hash() -> None:
    code = (
        "import sys\nsys.path.insert(0, 'src')\n"
        "import hashlib, os\n"
        "from jsonschema import Draft202012Validator, FormatChecker\n"
        "import pydantic\n"
        "import dynamic_ai_products, dynamic_ai_products.universe.models, dynamic_ai_products.universe.io_utils\n"
        "from pathlib import Path\n"
        "reads=[]\nmkdirs=[]\n"
        "orb, ort = Path.read_bytes, Path.read_text\n"
        "omk, oopen = Path.mkdir, os.open\n"
        "Path.read_bytes = lambda self,*a,**k:(reads.append(str(self)),orb(self,*a,**k))[1]\n"
        "Path.read_text = lambda self,*a,**k:(reads.append(str(self)),ort(self,*a,**k))[1]\n"
        "Path.mkdir = lambda self,*a,**k:(mkdirs.append(str(self)),omk(self,*a,**k))[1]\n"
        "os.open = lambda *a,**k:(mkdirs.append('open'),oopen(*a,**k))[1]\n"
        "sha=[]\nosha=hashlib.sha256\nhashlib.sha256=lambda *a,**k:(sha.append(1),osha(*a,**k))[1]\n"
        "import dynamic_ai_products.evaluation\n"
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open=orb,ort,omk,oopen\nhashlib.sha256=osha\n"
        "bad=[p for p in reads if p.endswith('.json') or p.endswith('.jsonl') or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad, bad\nassert not mkdirs, mkdirs\nassert not sha\nprint('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
