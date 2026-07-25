"""Slice 6: prediction normalization and canonical envelope tests.

The tracked manifest-bearing prediction fixture covers the positive stop point;
all negative, collision, partial-write and adversarial variants are generated
under ``tmp_path`` using the module's own serializers so hashes match by
default. No assertion/metric/gate/verdict behavior is exercised.
"""

import inspect
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pydantic
import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import envelopes as env_mod
from dynamic_ai_products.evaluation.case_sets import load_case_set_manifest
from dynamic_ai_products.evaluation.contracts import (
    canonical_contract_bytes,
    model_contract_hash,
)
from dynamic_ai_products.evaluation.envelopes import (
    EnvelopeArtifactMissingError,
    EnvelopeArtifactNotAFileError,
    EnvelopeDecodeError,
    EnvelopeDestinationHashMismatchError,
    EnvelopeDuplicateRecordIdError,
    EnvelopeError,
    EnvelopeHashMismatchError,
    EnvelopeJsonError,
    EnvelopeModelValidationError,
    EnvelopePathEscapeError,
    EnvelopeRecordCountMismatchError,
    EnvelopeReferenceBindingError,
    EnvelopeTopLevelTypeError,
    EnvelopeWriteError,
    ImportedPredictionSnapshot,
    InvalidSnapshotIdError,
    LoadedPredictionEnvelopes,
    NormalizedPredictionExistsError,
    NormalizedPredictionRun,
    PredictionArtifactManifest,
    PredictionRunBindingError,
    PredictionSnapshotExistsError,
    PredictionSourceArtifact,
    import_ad_hoc_prediction_file,
    load_prediction_envelopes,
    normalize_prediction_artifact,
)
from dynamic_ai_products.evaluation.models import PredictionEnvelope
from dynamic_ai_products.evaluation.references import load_target_registry
from dynamic_ai_products.evaluation.runs import (
    initialize_evaluation_run,
    initialize_evaluation_run_v2,
    load_evaluation_run_manifest_v2,
)
from dynamic_ai_products.evaluation.scoring_config import load_scoring_gate_config
from dynamic_ai_products.evaluation.stage_profiles import load_stage_profile_registry
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FX = ROOT / "evals" / "fixtures" / "evaluation_harness"
PRED_ROOT = FX / "predictions"
SUB = "valid_manifest_bearing_prediction"
MAN_REF = f"{SUB}/prediction_run_manifest.json"

SCORING = load_scoring_gate_config("valid_scoring_gate_config.json", eval_root=FX / "configs")
REGISTRY = load_target_registry("valid_target_registry.json", eval_root=FX / "configs")
CASE_SET = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FX / "case_sets")

ENV_HASH = model_contract_hash(PredictionEnvelope, "prediction_envelope", "0.1.0")
MAN_HASH = model_contract_hash(
    PredictionArtifactManifest, "prediction_artifact_manifest", "0.1.0"
)
FIXTURE_MANIFEST_SHA = sha256_bytes((PRED_ROOT / SUB / "prediction_run_manifest.json").read_bytes())


SP_REG = load_stage_profile_registry("stage_profiles/stage_profile_registry.json", eval_root=FX)
HEXV = "a" * 64


def init_run(eval_root, run_id="run1", *, prediction_run_id="SYNTH-PRED-RUN-0001",
             manifest_hash=FIXTURE_MANIFEST_SHA):
    return initialize_evaluation_run(
        eval_root=eval_root, eval_run_id=run_id, prediction_run_id=prediction_run_id,
        prediction_run_manifest_hash=manifest_hash, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64,
        scoring_config=SCORING, code_commit="c", config_snapshot_source_root=FX / "configs",
    )


def init_run_v2(eval_root, run_id="run1", *, prediction_run_id="SYNTH-PRED-RUN-0001",
                manifest_hash=FIXTURE_MANIFEST_SHA):
    """Initialize a genuine v0.2 run bound to the same fixture prediction manifest."""
    return initialize_evaluation_run_v2(
        eval_root=eval_root, eval_run_id=run_id, prediction_run_id=prediction_run_id,
        prediction_run_manifest_hash=manifest_hash, case_set=CASE_SET, registry=REGISTRY,
        validator_bundle_version="vb", validator_bundle_hash="b" * 64, scoring_config=SCORING,
        code_commit="c", config_snapshot_source_root=FX / "configs",
        evaluation_created_at="2026-07-25T00:00:00+00:00",
        evaluation_stage="capability_extraction", stage_profile_registry=SP_REG,
        semantic_adapter_registry_version="sa-v1", semantic_adapter_registry_hash=HEXV,
        selected_semantic_adapter_entry_hash=HEXV,
        source_passage_snapshot_version="sp-v1", source_passage_snapshot_hash=HEXV,
        gold_assertion_set_version="g-v1", gold_assertion_set_hash=HEXV,
        axis_taxonomy_version="ax-v1", axis_taxonomy_hash=HEXV,
        validator_rule_parameters_version="vp-v1", validator_rule_parameters_hash=HEXV,
    )


def envelope(rid, *, source_refs=("s.json",), man_ref="m.json", metadata=None):
    return {
        "contract": {"contract_id": "prediction_envelope", "contract_version": "0.1.0",
                     "contract_hash": ENV_HASH},
        "prediction_record_id": rid, "stage": "capability_extraction",
        "source_references": list(source_refs),
        "prompt_model_metadata": metadata if metadata is not None else {"m": "v"},
        "input_packet_hash": "1" * 64, "prediction_run_manifest_reference": man_ref,
    }


def build_artifact(tmp_path, *, sub="art", records=None, source_refs=("sources/s.json",),
                   source_bytes=b'{"c":1}\n', record_count=None, envelopes_sha=None,
                   prediction_run_id="SYNTH-PRED-RUN-0001", man_contract_hash=MAN_HASH,
                   env_man_ref=None, tamper_env_bytes=None):
    """Create a manifest-bearing artifact under tmp_path/src; return (src_root, man_ref, man_sha)."""
    src = tmp_path / "src"
    (src / sub / "sources").mkdir(parents=True, exist_ok=True)
    man_ref = f"{sub}/prediction_run_manifest.json"
    env_ref = f"{sub}/envelopes.jsonl"
    # write source
    (src / sub / source_refs[0]).parent.mkdir(parents=True, exist_ok=True)
    (src / sub / source_refs[0]).write_bytes(source_bytes)
    src_sha = sha256_bytes(source_bytes)
    full_src_ref = f"{sub}/{source_refs[0]}"
    # envelopes
    if records is None:
        records = [envelope("SYNTH-PRED-0001", source_refs=(full_src_ref,),
                            man_ref=env_man_ref or man_ref)]
    env_objs = tuple(PredictionEnvelope.model_validate(r) for r in records)
    env_bytes = tamper_env_bytes if tamper_env_bytes is not None else env_mod._serialize_envelopes_jsonl(env_objs)
    (src / env_ref).write_bytes(env_bytes)
    esha = envelopes_sha or sha256_bytes(env_bytes)
    # manifest
    man = {
        "contract": {"contract_id": "prediction_artifact_manifest", "contract_version": "0.1.0",
                     "contract_hash": man_contract_hash},
        "prediction_run_id": prediction_run_id, "envelopes_reference": env_ref,
        "envelopes_sha256": esha,
        "record_count": record_count if record_count is not None else len(env_objs),
        "source_artifacts": [{"reference": full_src_ref, "sha256": src_sha}],
    }
    man_bytes = canonical_contract_bytes(man)
    (src / man_ref).write_bytes(man_bytes)
    return src, man_ref, sha256_bytes(man_bytes)


# --- Existing PredictionEnvelope protection ------------------------------


def test_prediction_envelope_contract_unchanged() -> None:
    assert model_contract_hash(PredictionEnvelope, "prediction_envelope", "0.1.0") == (
        "5ac06fb78220c3f7369863cda32ee914a1d33ff01020fc01e57d9bd0ccbb18a3"
    )


def test_prediction_envelope_has_no_content_fields() -> None:
    fields = set(PredictionEnvelope.model_fields)
    for forbidden in ("prediction_payload", "output", "result", "answer", "confidence",
                      "unknown", "abstention", "eval_run_id", "case_id"):
        assert forbidden not in fields


# --- New manifest contract ------------------------------------------------


def test_manifest_contract_hash() -> None:
    assert MAN_HASH == "4b164aea18fc99f9518854aca0fb98587eb71d81c972a477d48cb815ddc0dbe4"


def test_manifest_model_strict_frozen() -> None:
    m = PredictionArtifactManifest.model_validate({
        "contract": {"contract_id": "prediction_artifact_manifest", "contract_version": "0.1.0",
                     "contract_hash": MAN_HASH},
        "prediction_run_id": "r", "envelopes_reference": "e.jsonl", "envelopes_sha256": "a" * 64,
        "record_count": 0, "source_artifacts": [],
    })
    with pytest.raises(pydantic.ValidationError):
        m.prediction_run_id = "x"  # type: ignore[misc]
    with pytest.raises(pydantic.ValidationError):
        PredictionArtifactManifest.model_validate({**m.model_dump(), "zzz": 1})


@pytest.mark.parametrize("bad", ["../x", "/abs", "a\\b", "", "  ", "a//b", "./x", "a/../b"])
def test_source_artifact_unsafe_reference_rejected(bad: str) -> None:
    with pytest.raises(pydantic.ValidationError):
        PredictionSourceArtifact.model_validate({"reference": bad, "sha256": "a" * 64})


def test_source_artifact_bad_hash() -> None:
    with pytest.raises(pydantic.ValidationError):
        PredictionSourceArtifact.model_validate({"reference": "s.json", "sha256": "short"})


# --- Valid manifest-bearing normalization --------------------------------


def test_valid_normalization_round_trip(tmp_path: Path) -> None:
    init_run(tmp_path)
    nr = normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                       eval_run_id="run1")
    assert isinstance(nr, NormalizedPredictionRun)
    assert [e.prediction_record_id for e in nr.envelopes] == ["SYNTH-PRED-0001", "SYNTH-PRED-0002"]
    assert nr.prediction_run_id == "SYNTH-PRED-RUN-0001"
    assert nr.artifact_reference == "run1/predictions/normalized_envelopes.jsonl"
    disk = (tmp_path / "run1/predictions/normalized_envelopes.jsonl").read_bytes()
    assert disk.endswith(b"\n") and nr.sha256 == sha256_bytes(disk)


def test_normalization_does_not_rewrite_slice5_manifest(tmp_path: Path) -> None:
    init_run(tmp_path)
    before = (tmp_path / "run1/evaluation_run_manifest.json").read_bytes()
    normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                  eval_run_id="run1")
    assert (tmp_path / "run1/evaluation_run_manifest.json").read_bytes() == before


def test_normalization_creates_no_later_slice_artifact(tmp_path: Path) -> None:
    init_run(tmp_path)
    normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                  eval_run_id="run1")
    names = {p.name for p in (tmp_path / "run1").rglob("*")}
    assert not names & {"results", "findings", "metrics", "gates", "comparisons",
                        "evaluation_result.json", "COMPLETED"}


def test_normalized_hash_independently_reproducible(tmp_path: Path) -> None:
    init_run(tmp_path)
    nr = normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                       eval_run_id="run1")
    rebuilt = env_mod._serialize_envelopes_jsonl(nr.envelopes)
    assert sha256_bytes(rebuilt) == nr.sha256


# --- Prediction-content boundary ------------------------------------------


def test_content_stays_in_source_only(tmp_path: Path) -> None:
    init_run(tmp_path)
    nr = normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                       eval_run_id="run1")
    for e in nr.envelopes:
        assert "synthetic_predicted_entities" not in e.prompt_model_metadata
        assert set(e.prompt_model_metadata) == {"synthetic_model_label", "synthetic_prompt_hash"}
        assert e.source_references == (f"{SUB}/sources/prediction_source.json",)
    source = json.loads((PRED_ROOT / SUB / "sources/prediction_source.json").read_text())
    assert "synthetic_predicted_entities" in source


# --- Ad hoc import --------------------------------------------------------


def test_ad_hoc_import_round_trip(tmp_path: Path) -> None:
    src = tmp_path / "adhoc"
    src.mkdir()
    (src / "raw.bin").write_bytes(b"\x00arbitrary-bytes\xff not json")
    snap_root = tmp_path / "snaps"
    snap_root.mkdir()
    imp = import_ad_hoc_prediction_file(
        "raw.bin", source_root=src, snapshot_root=snap_root, snapshot_id="snapA",
        prediction_run_id="SYNTH-AD-RUN-1", prediction_record_id="SYNTH-AD-0001",
        stage="task_extraction", prompt_model_metadata={"model": "synth"}, input_packet_hash="2" * 64,
    )
    assert isinstance(imp, ImportedPredictionSnapshot)
    layout = sorted(p.relative_to(snap_root).as_posix() for p in (snap_root / "snapA").rglob("*"))
    assert layout == [
        "snapA/envelopes.jsonl", "snapA/prediction_run_manifest.json",
        "snapA/sources", "snapA/sources/prediction_source.bin",
    ]
    assert (snap_root / "snapA/sources/prediction_source.bin").read_bytes() == b"\x00arbitrary-bytes\xff not json"
    assert imp.envelope.source_references == ("snapA/sources/prediction_source.bin",)
    assert imp.envelope.prompt_model_metadata == {"model": "synth"}
    # generated manifest hash usable to init Slice 5 and normalize the snapshot
    init_run(tmp_path, run_id="rr", prediction_run_id="SYNTH-AD-RUN-1",
             manifest_hash=imp.manifest_sha256)
    nr = normalize_prediction_artifact(imp.manifest_reference, source_root=snap_root,
                                       eval_root=tmp_path, eval_run_id="rr")
    assert len(nr.envelopes) == 1 and nr.envelopes[0].prediction_record_id == "SYNTH-AD-0001"


def test_ad_hoc_import_refuses_overwrite(tmp_path: Path) -> None:
    src = tmp_path / "a"
    src.mkdir()
    (src / "raw.bin").write_bytes(b"x")
    snap = tmp_path / "s"
    snap.mkdir()
    kw = dict(source_root=src, snapshot_root=snap, snapshot_id="snapA",
              prediction_run_id="r", prediction_record_id="p", stage="s",
              prompt_model_metadata={}, input_packet_hash="2" * 64)
    import_ad_hoc_prediction_file("raw.bin", **kw)
    with pytest.raises(PredictionSnapshotExistsError):
        import_ad_hoc_prediction_file("raw.bin", **kw)


@pytest.mark.parametrize("bad", ["", "  ", ".", "..", "a/b", "a\\b", "/abs", "x\x00y", 123])
def test_ad_hoc_invalid_snapshot_id(tmp_path: Path, bad) -> None:
    src = tmp_path / "a"
    src.mkdir()
    (src / "raw.bin").write_bytes(b"x")
    snap = tmp_path / "s"
    snap.mkdir()
    with pytest.raises(InvalidSnapshotIdError):
        import_ad_hoc_prediction_file("raw.bin", source_root=src, snapshot_root=snap,
            snapshot_id=bad, prediction_run_id="r", prediction_record_id="p", stage="s",
            prompt_model_metadata={}, input_packet_hash="2" * 64)


def test_ad_hoc_partial_directory_preserved(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    src = tmp_path / "a"
    src.mkdir()
    (src / "raw.bin").write_bytes(b"x")
    snap = tmp_path / "s"
    snap.mkdir()
    real = env_mod.os.open

    def boom(path, flags, mode=0o777):
        if str(path).endswith("prediction_run_manifest.json"):
            raise OSError("x")
        return real(path, flags, mode)

    monkeypatch.setattr(env_mod.os, "open", boom)
    with pytest.raises(EnvelopeWriteError):
        import_ad_hoc_prediction_file("raw.bin", source_root=src, snapshot_root=snap,
            snapshot_id="snapA", prediction_run_id="r", prediction_record_id="p", stage="s",
            prompt_model_metadata={}, input_packet_hash="2" * 64)
    assert (snap / "snapA/sources/prediction_source.bin").is_file()
    assert not (snap / "snapA/prediction_run_manifest.json").exists()


# --- Manifest binding -----------------------------------------------------


def test_binding_manifest_hash_mismatch(tmp_path: Path) -> None:
    init_run(tmp_path, manifest_hash="0" * 64)
    with pytest.raises(PredictionRunBindingError) as e:
        normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                      eval_run_id="run1")
    assert e.value.binding_kind == "prediction_manifest_hash_mismatch"
    assert not (tmp_path / "run1/predictions").exists()


def test_binding_prediction_run_id_mismatch(tmp_path: Path) -> None:
    src, man_ref, man_sha = build_artifact(tmp_path, prediction_run_id="OTHER-RUN")
    init_run(tmp_path, prediction_run_id="SYNTH-PRED-RUN-0001", manifest_hash=man_sha)
    with pytest.raises(PredictionRunBindingError) as e:
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id="run1")
    assert e.value.binding_kind == "prediction_run_id_mismatch"


def test_binding_envelope_manifest_reference_mismatch(tmp_path: Path) -> None:
    recs = [envelope("SYNTH-PRED-0001", source_refs=("art/sources/s.json",),
                     man_ref="wrong-reference.json")]
    src, man_ref, man_sha = build_artifact(tmp_path, records=recs)
    init_run(tmp_path, manifest_hash=man_sha)
    with pytest.raises(EnvelopeReferenceBindingError) as e:
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id="run1")
    assert e.value.binding_kind == "prediction_manifest_reference_mismatch"


def test_binding_undeclared_source_reference(tmp_path: Path) -> None:
    recs = [envelope("SYNTH-PRED-0001", source_refs=("art/sources/undeclared.json",),
                     man_ref="art/prediction_run_manifest.json")]
    src, man_ref, man_sha = build_artifact(tmp_path, records=recs)
    init_run(tmp_path, manifest_hash=man_sha)
    with pytest.raises(EnvelopeReferenceBindingError) as e:
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id="run1")
    assert e.value.binding_kind == "undeclared_source_reference"


def test_binding_source_hash_mismatch(tmp_path: Path) -> None:
    src, man_ref, man_sha = build_artifact(tmp_path)
    # tamper the source file after manifest was built
    (src / "art/sources/s.json").write_bytes(b'{"c":999}\n')
    init_run(tmp_path, manifest_hash=man_sha)
    # manifest raw hash no longer matches run pin because source unchanged in manifest,
    # so use the manifest's own recomputed hash for the run pin instead:
    man_sha2 = sha256_bytes((src / man_ref).read_bytes())
    with tempfile.TemporaryDirectory() as td:
        r2 = Path(td)
        init_run(r2, manifest_hash=man_sha2)
        with pytest.raises(EnvelopeHashMismatchError):
            normalize_prediction_artifact(man_ref, source_root=src, eval_root=r2, eval_run_id="run1")


def test_binding_descriptor_hash_mismatch(tmp_path: Path) -> None:
    src, man_ref, _ = build_artifact(tmp_path, envelopes_sha="0" * 64)
    man_sha = sha256_bytes((src / man_ref).read_bytes())
    init_run(tmp_path, manifest_hash=man_sha)
    with pytest.raises(EnvelopeHashMismatchError):
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id="run1")


def test_binding_record_count_mismatch(tmp_path: Path) -> None:
    src, man_ref, _ = build_artifact(tmp_path, record_count=5)
    man_sha = sha256_bytes((src / man_ref).read_bytes())
    init_run(tmp_path, manifest_hash=man_sha)
    with pytest.raises(EnvelopeRecordCountMismatchError) as e:
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id="run1")
    assert e.value.expected_count == 5 and e.value.observed_count == 1


def test_binding_duplicate_record_id(tmp_path: Path) -> None:
    recs = [envelope("DUP", source_refs=("art/sources/s.json",), man_ref="art/prediction_run_manifest.json"),
            envelope("DUP", source_refs=("art/sources/s.json",), man_ref="art/prediction_run_manifest.json")]
    src, man_ref, _ = build_artifact(tmp_path, records=recs, record_count=2)
    man_sha = sha256_bytes((src / man_ref).read_bytes())
    init_run(tmp_path, manifest_hash=man_sha)
    with pytest.raises(EnvelopeDuplicateRecordIdError) as e:
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id="run1")
    assert e.value.duplicate_record_id == "DUP"


def test_all_bindings_fail_before_directory_creation(tmp_path: Path) -> None:
    init_run(tmp_path, manifest_hash="0" * 64)
    with pytest.raises(PredictionRunBindingError):
        normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                      eval_run_id="run1")
    assert not (tmp_path / "run1/predictions").exists()


# --- Strict manifest JSON -------------------------------------------------


def _init_and_expect(tmp_path, man_ref, src, exc, run_id="run1"):
    man_sha = sha256_bytes((src / man_ref).read_bytes())
    init_run(tmp_path, run_id=run_id, manifest_hash=man_sha)
    with pytest.raises(exc):
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id=run_id)


def test_manifest_missing(tmp_path: Path) -> None:
    init_run(tmp_path)
    with pytest.raises(EnvelopeArtifactMissingError):
        normalize_prediction_artifact("nope/x.json", source_root=PRED_ROOT, eval_root=tmp_path,
                                      eval_run_id="run1")


def test_manifest_invalid_utf8(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "art").mkdir(parents=True)
    (src / "art/prediction_run_manifest.json").write_bytes(b"\xff\xfe{}")
    init_run(tmp_path)
    with pytest.raises(EnvelopeDecodeError):
        normalize_prediction_artifact("art/prediction_run_manifest.json", source_root=src,
                                      eval_root=tmp_path, eval_run_id="run1")


def test_manifest_bom(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "art").mkdir(parents=True)
    (src / "art/prediction_run_manifest.json").write_bytes(b"\xef\xbb\xbf{}")
    init_run(tmp_path)
    with pytest.raises(EnvelopeJsonError):
        normalize_prediction_artifact("art/prediction_run_manifest.json", source_root=src,
                                      eval_root=tmp_path, eval_run_id="run1")


def test_manifest_duplicate_key(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "art").mkdir(parents=True)
    (src / "art/prediction_run_manifest.json").write_bytes(b'{"prediction_run_id":"a","prediction_run_id":"b"}')
    init_run(tmp_path)
    with pytest.raises(EnvelopeJsonError) as e:
        normalize_prediction_artifact("art/prediction_run_manifest.json", source_root=src,
                                      eval_root=tmp_path, eval_run_id="run1")
    assert e.value.duplicate_key == "prediction_run_id"


def test_manifest_nonobject(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "art").mkdir(parents=True)
    (src / "art/prediction_run_manifest.json").write_bytes(b"[1]")
    init_run(tmp_path)
    with pytest.raises(EnvelopeTopLevelTypeError):
        normalize_prediction_artifact("art/prediction_run_manifest.json", source_root=src,
                                      eval_root=tmp_path, eval_run_id="run1")


def test_manifest_bad_contract_hash(tmp_path: Path) -> None:
    src, man_ref, _ = build_artifact(tmp_path, man_contract_hash="0" * 64)
    _init_and_expect(tmp_path, man_ref, src, EnvelopeModelValidationError)


def test_manifest_unknown_field(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "art").mkdir(parents=True)
    man = {"contract": {"contract_id": "prediction_artifact_manifest", "contract_version": "0.1.0",
                        "contract_hash": MAN_HASH}, "prediction_run_id": "r",
           "envelopes_reference": "e.jsonl", "envelopes_sha256": "a" * 64, "record_count": 0,
           "source_artifacts": [], "zzz": 1}
    (src / "art/prediction_run_manifest.json").write_bytes(canonical_contract_bytes(man))
    _init_and_expect(tmp_path, "art/prediction_run_manifest.json", src, EnvelopeModelValidationError)


# --- Strict JSONL ---------------------------------------------------------


def test_empty_descriptor_zero_records(tmp_path: Path) -> None:
    src = tmp_path / "src"
    (src / "art/sources").mkdir(parents=True)
    (src / "art/envelopes.jsonl").write_bytes(b"")
    man = {"contract": {"contract_id": "prediction_artifact_manifest", "contract_version": "0.1.0",
                        "contract_hash": MAN_HASH}, "prediction_run_id": "SYNTH-PRED-RUN-0001",
           "envelopes_reference": "art/envelopes.jsonl", "envelopes_sha256": sha256_bytes(b""),
           "record_count": 0, "source_artifacts": []}
    (src / "art/prediction_run_manifest.json").write_bytes(canonical_contract_bytes(man))
    man_sha = sha256_bytes((src / "art/prediction_run_manifest.json").read_bytes())
    init_run(tmp_path, manifest_hash=man_sha)
    nr = normalize_prediction_artifact("art/prediction_run_manifest.json", source_root=src,
                                       eval_root=tmp_path, eval_run_id="run1")
    assert nr.envelopes == ()
    assert (tmp_path / "run1/predictions/normalized_envelopes.jsonl").read_bytes() == b""


def test_descriptor_blank_line_rejected(tmp_path: Path) -> None:
    good = env_mod._serialize_envelopes_jsonl((PredictionEnvelope.model_validate(
        envelope("P1", source_refs=("art/sources/s.json",), man_ref="art/prediction_run_manifest.json")),))
    tampered = good + b"\n" + good
    src, man_ref, _ = build_artifact(tmp_path, tamper_env_bytes=tampered,
                                     envelopes_sha=sha256_bytes(tampered), record_count=2)
    _init_and_expect(tmp_path, man_ref, src, EnvelopeJsonError)


def test_descriptor_nonfinite(tmp_path: Path) -> None:
    tampered = b'{"x": NaN}\n'
    src, man_ref, _ = build_artifact(tmp_path, tamper_env_bytes=tampered,
                                     envelopes_sha=sha256_bytes(tampered), record_count=1)
    _init_and_expect(tmp_path, man_ref, src, EnvelopeJsonError)


def test_descriptor_line_number(tmp_path: Path) -> None:
    good = env_mod._canonical_envelope_line(PredictionEnvelope.model_validate(
        envelope("P1", source_refs=("art/sources/s.json",), man_ref="art/prediction_run_manifest.json")))
    tampered = good + b"\n" + b"{not json\n"
    src, man_ref, _ = build_artifact(tmp_path, tamper_env_bytes=tampered,
                                     envelopes_sha=sha256_bytes(tampered), record_count=2)
    man_sha = sha256_bytes((src / man_ref).read_bytes())
    init_run(tmp_path, manifest_hash=man_sha)
    with pytest.raises(EnvelopeJsonError) as e:
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id="run1")
    assert e.value.line_number == 2


# --- Path security --------------------------------------------------------


def test_manifest_traversal_escape(tmp_path: Path) -> None:
    src = tmp_path / "src"
    src.mkdir()
    (tmp_path / "outside.json").write_bytes(b"{}")
    init_run(tmp_path)
    with pytest.raises(EnvelopePathEscapeError):
        normalize_prediction_artifact("../outside.json", source_root=src, eval_root=tmp_path,
                                      eval_run_id="run1")


def test_source_symlink_escape(tmp_path: Path) -> None:
    src, man_ref, _ = build_artifact(tmp_path)
    (tmp_path / "ext.json").write_bytes(b"x")
    (src / "art/sources/s.json").unlink()
    (src / "art/sources/s.json").symlink_to(tmp_path / "ext.json")
    man_sha = sha256_bytes((src / man_ref).read_bytes())
    init_run(tmp_path, manifest_hash=man_sha)
    with pytest.raises((EnvelopePathEscapeError, EnvelopeArtifactNotAFileError)):
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id="run1")


def test_source_contained_dangling_symlink_not_a_file(tmp_path: Path) -> None:
    src, man_ref, _ = build_artifact(tmp_path)
    (src / "art/sources/s.json").unlink()
    (src / "art/sources/s.json").symlink_to(src / "art/sources/missing.json")
    man_sha = sha256_bytes((src / man_ref).read_bytes())
    init_run(tmp_path, manifest_hash=man_sha)
    with pytest.raises(EnvelopeArtifactNotAFileError):
        normalize_prediction_artifact(man_ref, source_root=src, eval_root=tmp_path, eval_run_id="run1")


# --- Persistence ----------------------------------------------------------


def test_predictions_directory_collision(tmp_path: Path) -> None:
    init_run(tmp_path)
    (tmp_path / "run1/predictions").mkdir()
    with pytest.raises(NormalizedPredictionExistsError):
        normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                      eval_run_id="run1")


def test_predictions_symlink_collision(tmp_path: Path) -> None:
    init_run(tmp_path)
    (tmp_path / "run1/predictions").symlink_to(tmp_path)
    with pytest.raises(NormalizedPredictionExistsError):
        normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                      eval_run_id="run1")


def test_no_second_normalization(tmp_path: Path) -> None:
    init_run(tmp_path)
    normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                  eval_run_id="run1")
    with pytest.raises(NormalizedPredictionExistsError):
        normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                      eval_run_id="run1")


def test_destination_hash_mismatch_preserves_partial(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    init_run(tmp_path)
    real = Path.read_bytes

    def tamper(self):
        if self.name == "normalized_envelopes.jsonl":
            return b"tampered"
        return real(self)

    monkeypatch.setattr(Path, "read_bytes", tamper)
    with pytest.raises(EnvelopeDestinationHashMismatchError):
        normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                      eval_run_id="run1")
    assert (tmp_path / "run1/predictions").is_dir()


# --- Normalized loader ----------------------------------------------------


def test_loader_success_and_distinct(tmp_path: Path) -> None:
    init_run(tmp_path)
    nr = normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                       eval_run_id="run1")
    a = load_prediction_envelopes("run1", eval_root=tmp_path)
    b = load_prediction_envelopes("run1", eval_root=tmp_path)
    assert isinstance(a, LoadedPredictionEnvelopes)
    assert a == b and a is not b and a.envelopes == nr.envelopes and a.sha256 == nr.sha256


def test_loader_missing(tmp_path: Path) -> None:
    init_run(tmp_path)
    with pytest.raises(EnvelopeArtifactMissingError):
        load_prediction_envelopes("run1", eval_root=tmp_path)


def test_loader_predictions_symlink_rejected(tmp_path: Path) -> None:
    init_run(tmp_path)
    (tmp_path / "run1/predictions").symlink_to(tmp_path)
    with pytest.raises(EnvelopeArtifactNotAFileError):
        load_prediction_envelopes("run1", eval_root=tmp_path)


def test_loader_requires_valid_run_manifest(tmp_path: Path) -> None:
    # No Slice 5 run at all -> run-manifest load fails (RunArtifactNotFoundError).
    from dynamic_ai_products.evaluation.runs import RunArtifactNotFoundError
    with pytest.raises(RunArtifactNotFoundError):
        load_prediction_envelopes("ghost", eval_root=tmp_path)


# --- Compatibility --------------------------------------------------------


def test_slice_2_5_unchanged(tmp_path: Path) -> None:
    from dynamic_ai_products.evaluation.cases import load_case
    case = load_case("valid_minimal_case.json", eval_root=FX / "cases")
    assert case.case_id == "SYNTH-CASE-MIN-0001"
    r = init_run(tmp_path)
    assert r.manifest.eval_run_id == "run1"


# --- Exports and import behavior ------------------------------------------

PUBLIC_FUNCTIONS = ("import_ad_hoc_prediction_file", "normalize_prediction_artifact",
                    "load_prediction_envelopes")
PUBLIC_MODELS = ("PredictionSourceArtifact", "PredictionArtifactManifest",
                 "ImportedPredictionSnapshot", "NormalizedPredictionRun",
                 "LoadedPredictionEnvelopes")
PUBLIC_EXCEPTIONS = ("EnvelopeError", "InvalidSnapshotIdError", "PredictionSnapshotExistsError",
    "NormalizedPredictionExistsError", "EnvelopePathEscapeError", "EnvelopeArtifactMissingError",
    "EnvelopeArtifactNotAFileError", "EnvelopeArtifactReadError", "EnvelopeDecodeError",
    "EnvelopeJsonError", "EnvelopeTopLevelTypeError", "EnvelopeModelValidationError",
    "EnvelopeDuplicateRecordIdError", "EnvelopeHashMismatchError", "EnvelopeReferenceBindingError",
    "PredictionRunBindingError", "EnvelopeRecordCountMismatchError", "EnvelopeWriteError",
    "EnvelopeDestinationHashMismatchError")


def test_public_symbols_exported() -> None:
    for name in PUBLIC_FUNCTIONS + PUBLIC_MODELS + PUBLIC_EXCEPTIONS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(env_mod, name)


def test_package_all_parity_exact() -> None:
    public = {n for n in dir(evaluation_pkg)
              if not n.startswith("_") and not inspect.ismodule(getattr(evaluation_pkg, n))}
    assert set(evaluation_pkg.__all__) == public


def test_private_helpers_not_exported() -> None:
    for name in ("_serialize_envelopes_jsonl", "_resolve_and_read", "_exclusive_write",
                 "_DuplicateKeyControl", "_parse_envelope_jsonl", "_load_prediction_artifact"):
        assert name not in evaluation_pkg.__all__
        assert not hasattr(evaluation_pkg, name)


def test_exception_hierarchy() -> None:
    for name in PUBLIC_EXCEPTIONS:
        cls = getattr(env_mod, name)
        if name == "EnvelopeError":
            assert cls.__bases__ == (Exception,)
        else:
            assert issubclass(cls, EnvelopeError)


def test_package_import_no_io_or_hash() -> None:
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
        "import dynamic_ai_products.evaluation\n"
        "Path.read_bytes,Path.read_text,Path.mkdir,os.open=orb,ort,omk,oop\nhashlib.sha256=osha\n"
        "bad=[p for p in reads if p.endswith('.json') or p.endswith('.jsonl') or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad and not writes and not sha, (bad, writes, len(sha))\nprint('OK')\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT)
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr


# --- Correction A: run-manifest version-agnostic envelope I/O -------------


def test_v1_normalize_and_reload_envelopes_unchanged(tmp_path: Path) -> None:
    # v0.1 behavior preserved: normalize, then reload through load_prediction_envelopes.
    init_run(tmp_path)
    nr = normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                       eval_run_id="run1")
    loaded = load_prediction_envelopes("run1", eval_root=tmp_path)
    assert loaded.eval_run_id == "run1"
    assert loaded.sha256 == nr.sha256
    assert [e.prediction_record_id for e in loaded.envelopes] == \
        [e.prediction_record_id for e in nr.envelopes] == ["SYNTH-PRED-0001", "SYNTH-PRED-0002"]


def test_v2_normalize_and_reload_envelopes(tmp_path: Path) -> None:
    # A genuine v0.2 run with a matching prediction manifest normalizes and reloads.
    init_run_v2(tmp_path)
    # Confirm the persisted run manifest is truly v0.2.
    rm = load_evaluation_run_manifest_v2("run1", eval_root=tmp_path).manifest
    assert rm.contract.contract_version == "0.2.0"
    nr = normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                       eval_run_id="run1")
    assert isinstance(nr, NormalizedPredictionRun)
    assert nr.prediction_run_id == "SYNTH-PRED-RUN-0001"
    assert nr.artifact_reference == "run1/predictions/normalized_envelopes.jsonl"
    assert [e.prediction_record_id for e in nr.envelopes] == ["SYNTH-PRED-0001", "SYNTH-PRED-0002"]
    disk = (tmp_path / "run1/predictions/normalized_envelopes.jsonl").read_bytes()
    assert disk.endswith(b"\n") and nr.sha256 == sha256_bytes(disk)
    loaded = load_prediction_envelopes("run1", eval_root=tmp_path)
    assert loaded.eval_run_id == "run1" and loaded.sha256 == nr.sha256
    assert [e.prediction_record_id for e in loaded.envelopes] == \
        [e.prediction_record_id for e in nr.envelopes]


def test_v2_normalization_binds_prediction_identity_and_bytes(tmp_path: Path) -> None:
    # Run/prediction identity and persisted-byte binding hold on a v0.2 run.
    init_run_v2(tmp_path)
    # Capture the genuine v0.2 run manifest bytes before any envelope I/O.
    before = (tmp_path / "run1" / "evaluation_run_manifest.json").read_bytes()
    nr = normalize_prediction_artifact(MAN_REF, source_root=PRED_ROOT, eval_root=tmp_path,
                                       eval_run_id="run1")
    assert nr.eval_run_id == "run1"
    rebuilt = env_mod._serialize_envelopes_jsonl(nr.envelopes)
    assert sha256_bytes(rebuilt) == nr.sha256
    # Normalization leaves the v0.2 run manifest byte-identical.
    assert (tmp_path / "run1" / "evaluation_run_manifest.json").read_bytes() == before
    # Reload also leaves the v0.2 run manifest byte-identical.
    load_prediction_envelopes("run1", eval_root=tmp_path)
    assert (tmp_path / "run1" / "evaluation_run_manifest.json").read_bytes() == before
