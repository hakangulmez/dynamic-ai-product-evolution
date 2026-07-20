"""Slice 3: case-set manifest, membership-event, succession, and hash tests.

Tracked fixtures cover the Slice 3 stop point (membership reconstructable;
conflicts rejected; frozen snapshots hash-stable); failure variants are
generated under ``tmp_path``. No writer, exposure-authorization, policy,
or later-slice behavior is tested here.
"""

import inspect
import json
import subprocess
import sys
from pathlib import Path

import pydantic
import pytest

import dynamic_ai_products.evaluation as evaluation_pkg
from dynamic_ai_products.evaluation import case_sets as case_sets_module
from dynamic_ai_products.evaluation.case_sets import (
    CaseSetArtifactNotAFileError,
    CaseSetArtifactNotFoundError,
    CaseSetConsistencyError,
    CaseSetDecodeError,
    CaseSetJsonError,
    CaseSetLoadError,
    CaseSetModelValidationError,
    CaseSetPathEscapeError,
    CaseSetTopLevelTypeError,
    case_set_snapshot_hash,
    load_case_set_manifest,
    load_membership_events,
    verify_case_set_succession,
    verify_event_log_extension,
)
from dynamic_ai_products.evaluation.cases import InvalidEvaluationRootError, load_case
from dynamic_ai_products.evaluation.contracts import (
    canonical_contract_bytes,
    model_contract_hash,
)
from dynamic_ai_products.evaluation.models import CaseSetManifest, MembershipEvent
from dynamic_ai_products.universe.io_utils import sha256_bytes

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "evals" / "fixtures" / "evaluation_harness" / "case_sets"
CASE_FIX = ROOT / "evals" / "fixtures" / "evaluation_harness" / "cases"

MANIFEST_CONTRACT_HASH = model_contract_hash(
    CaseSetManifest, "case_set_manifest", "0.1.0"
)
EVENT_CONTRACT_HASH = model_contract_hash(MembershipEvent, "membership_event", "0.1.0")


def entry(case_id, partition="dev", suites=(), packet="1" * 64):
    return {
        "case_id": case_id,
        "partition": partition,
        "suites": list(suites),
        "input_packet_hash": packet,
    }


def manifest_payload(*, version="set-v1", lifecycle="draft", entries=None, **overrides):
    payload = {
        "contract": {
            "contract_id": "case_set_manifest",
            "contract_version": "0.1.0",
            "contract_hash": MANIFEST_CONTRACT_HASH,
        },
        "case_set_version": version,
        "lifecycle": lifecycle,
        "registry_snapshot_version": "synth-registry-v1",
        "registry_snapshot_hash": "a" * 64,
        "entries": (
            entries
            if entries is not None
            else [
                entry("CASE-A", "dev", ["adversarial"], "1" * 64),
                entry("CASE-B", "frozen_test", [], "2" * 64),
            ]
        ),
    }
    payload.update(overrides)
    return payload


def event_payload(**overrides):
    payload = {
        "contract": {
            "contract_id": "membership_event",
            "contract_version": "0.1.0",
            "contract_hash": EVENT_CONTRACT_HASH,
        },
        "previous_case_set_version": "set-v1",
        "new_case_set_version": "set-v2",
        "case_id": "CASE-A",
        "old_partition": "dev",
        "new_partition": "frozen_test",
        "added_suites": [],
        "removed_suites": [],
        "reason_code": "synthetic-reason",
        "actor": "synthetic-researcher",
        "timestamp": "synthetic-clock-1",
    }
    payload.update(overrides)
    return payload


def make_manifest(**kwargs) -> CaseSetManifest:
    return CaseSetManifest.model_validate(manifest_payload(**kwargs))


def make_event(**overrides) -> MembershipEvent:
    return MembershipEvent.model_validate(event_payload(**overrides))


def write(tmp_path: Path, content, name: str) -> str:
    path = tmp_path / name
    if isinstance(content, bytes):
        path.write_bytes(content)
    elif isinstance(content, str):
        path.write_text(content, encoding="utf-8")
    else:
        path.write_text(json.dumps(content), encoding="utf-8")
    return name


def write_events(tmp_path: Path, lines, name: str = "events.jsonl") -> str:
    text = "\n".join(
        json.dumps(line) if isinstance(line, dict) else line for line in lines
    )
    (tmp_path / name).write_text(text + "\n", encoding="utf-8")
    return name


def succession(base_entries, events, successor_entries):
    base = make_manifest(version="set-v1", entries=base_entries)
    successor = make_manifest(
        version="set-v2", lifecycle="frozen", entries=successor_entries
    )
    verify_case_set_succession(base, events, successor)


# --- Successful loading ---------------------------------------------------


def test_loads_base_manifest_fixture() -> None:
    manifest = load_case_set_manifest(
        "valid_base_case_set_manifest.json", eval_root=FIX
    )
    assert manifest.case_set_version == "synth-case-set-v1"
    assert manifest.lifecycle == "draft"
    assert [e.case_id for e in manifest.entries] == [
        "SYNTH-CASE-0001",
        "SYNTH-CASE-0002",
        "SYNTH-CASE-0003",
    ]


def test_loads_frozen_manifest_fixture() -> None:
    manifest = load_case_set_manifest(
        "valid_frozen_case_set_manifest.json", eval_root=FIX
    )
    assert manifest.lifecycle == "frozen"
    assert manifest.entries[0].suites == ("adversarial", "regression", "smoke")


def test_loads_membership_events_fixture_in_file_order() -> None:
    events = load_membership_events("valid_membership_events.jsonl", eval_root=FIX)
    assert [e.case_id for e in events] == [
        "SYNTH-CASE-0001",
        "SYNTH-CASE-0003",
        "SYNTH-CASE-0004",
        "SYNTH-CASE-0002",
    ]


def test_returned_types() -> None:
    manifest = load_case_set_manifest(
        "valid_base_case_set_manifest.json", eval_root=FIX
    )
    events = load_membership_events("valid_membership_events.jsonl", eval_root=FIX)
    assert isinstance(manifest, CaseSetManifest)
    assert isinstance(events, tuple)
    assert all(isinstance(e, MembershipEvent) for e in events)


def test_loaded_models_are_frozen() -> None:
    manifest = load_case_set_manifest(
        "valid_base_case_set_manifest.json", eval_root=FIX
    )
    with pytest.raises(pydantic.ValidationError):
        manifest.case_set_version = "mutated"  # type: ignore[misc]


def test_repeated_loads_equal_but_distinct() -> None:
    first = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FIX)
    second = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FIX)
    assert first == second and first is not second
    ev1 = load_membership_events("valid_membership_events.jsonl", eval_root=FIX)
    ev2 = load_membership_events("valid_membership_events.jsonl", eval_root=FIX)
    assert ev1 == ev2 and ev1 is not ev2


def test_tuple_representation() -> None:
    manifest = load_case_set_manifest(
        "valid_base_case_set_manifest.json", eval_root=FIX
    )
    assert isinstance(manifest.entries, tuple)
    assert isinstance(manifest.entries[0].suites, tuple)
    events = load_membership_events("valid_membership_events.jsonl", eval_root=FIX)
    assert isinstance(events[0].added_suites, tuple)


def test_identity_and_timestamp_preservation() -> None:
    events = load_membership_events("valid_membership_events.jsonl", eval_root=FIX)
    assert events[0].timestamp == "2026-07-19T10:01:00Z"
    assert events[0].change_reference == "synth-change-request-0001"
    assert events[1].change_reference is None


def test_omitted_eval_root_is_typeerror() -> None:
    with pytest.raises(TypeError):
        load_case_set_manifest("m.json")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        load_membership_events("e.jsonl")  # type: ignore[call-arg]


def test_explicit_dot_root_is_legal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(tmp_path, manifest_payload(), "manifest.json")
    monkeypatch.chdir(tmp_path)
    assert isinstance(
        load_case_set_manifest("manifest.json", eval_root="."), CaseSetManifest
    )


# --- Root and path safety -------------------------------------------------


def test_none_root_rejected() -> None:
    with pytest.raises(InvalidEvaluationRootError) as excinfo:
        load_case_set_manifest("m.json", eval_root=None)  # type: ignore[arg-type]
    assert excinfo.value.observed_type == "NoneType"


def test_empty_string_root_rejected() -> None:
    with pytest.raises(InvalidEvaluationRootError):
        load_membership_events("e.jsonl", eval_root="")


def test_nonexistent_root_rejected(tmp_path: Path) -> None:
    with pytest.raises(InvalidEvaluationRootError):
        load_case_set_manifest("m.json", eval_root=tmp_path / "missing")


def test_file_root_rejected(tmp_path: Path) -> None:
    name = write(tmp_path, manifest_payload(), "not-a-dir.json")
    with pytest.raises(InvalidEvaluationRootError):
        load_case_set_manifest("m.json", eval_root=tmp_path / name)


def test_absolute_contained_path(tmp_path: Path) -> None:
    write(tmp_path, manifest_payload(), "manifest.json")
    manifest = load_case_set_manifest(
        str(tmp_path / "manifest.json"), eval_root=tmp_path
    )
    assert isinstance(manifest, CaseSetManifest)


def test_absolute_escape_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    write(outside, manifest_payload(), "m.json")
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(CaseSetPathEscapeError):
        load_case_set_manifest(str(outside / "m.json"), eval_root=root)


def test_dotdot_escape_rejected(tmp_path: Path) -> None:
    write(tmp_path, manifest_payload(), "outside.json")
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(CaseSetPathEscapeError) as excinfo:
        load_case_set_manifest("../outside.json", eval_root=root)
    assert excinfo.value.artifact_reference == "../outside.json"


def test_symlink_escape_rejected_and_target_hidden(tmp_path: Path) -> None:
    outside = tmp_path / "outside-secret"
    outside.mkdir()
    write(outside, manifest_payload(), "m.json")
    root = tmp_path / "root"
    root.mkdir()
    (root / "link.json").symlink_to(outside / "m.json")
    with pytest.raises(CaseSetPathEscapeError) as excinfo:
        load_case_set_manifest("link.json", eval_root=root)
    assert "outside-secret" not in str(excinfo.value)
    assert excinfo.value.artifact_reference == "link.json"


def test_root_symlink_resolves(tmp_path: Path) -> None:
    real = tmp_path / "real-root"
    real.mkdir()
    write(real, manifest_payload(), "manifest.json")
    link = tmp_path / "root-link"
    link.symlink_to(real, target_is_directory=True)
    assert isinstance(
        load_case_set_manifest("manifest.json", eval_root=link), CaseSetManifest
    )


def test_prefix_confusion_escape_rejected(tmp_path: Path) -> None:
    root = tmp_path / "evals"
    root.mkdir()
    sibling = tmp_path / "evals-escape"
    sibling.mkdir()
    write(sibling, manifest_payload(), "m.json")
    with pytest.raises(CaseSetPathEscapeError):
        load_case_set_manifest(str(sibling / "m.json"), eval_root=root)


def test_missing_artifact_rejected(tmp_path: Path) -> None:
    with pytest.raises(CaseSetArtifactNotFoundError) as excinfo:
        load_case_set_manifest("sub/missing.json", eval_root=tmp_path)
    assert excinfo.value.artifact_reference == "sub/missing.json"


def test_directory_artifact_rejected(tmp_path: Path) -> None:
    (tmp_path / "a-dir").mkdir()
    with pytest.raises(CaseSetArtifactNotAFileError):
        load_case_set_manifest("a-dir", eval_root=tmp_path)


def test_events_loader_containment(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(CaseSetPathEscapeError):
        load_membership_events("../outside.jsonl", eval_root=root)
    with pytest.raises(CaseSetArtifactNotFoundError):
        load_membership_events("missing.jsonl", eval_root=root)


# --- Strict JSON and JSONL ------------------------------------------------


def test_invalid_utf8_manifest(tmp_path: Path) -> None:
    write(tmp_path, b'\xff\xfe{"a": 1}', "manifest.json")
    with pytest.raises(CaseSetDecodeError) as excinfo:
        load_case_set_manifest("manifest.json", eval_root=tmp_path)
    assert isinstance(excinfo.value.__cause__, UnicodeDecodeError)


def test_malformed_manifest_json(tmp_path: Path) -> None:
    write(tmp_path, "{not json", "manifest.json")
    with pytest.raises(CaseSetJsonError) as excinfo:
        load_case_set_manifest("manifest.json", eval_root=tmp_path)
    assert isinstance(excinfo.value.__cause__, json.JSONDecodeError)


def test_trailing_manifest_content(tmp_path: Path) -> None:
    write(tmp_path, json.dumps(manifest_payload()) + " extra", "manifest.json")
    with pytest.raises(CaseSetJsonError):
        load_case_set_manifest("manifest.json", eval_root=tmp_path)


def test_bom_manifest_rejected(tmp_path: Path) -> None:
    raw = b"\xef\xbb\xbf" + json.dumps(manifest_payload()).encode("utf-8")
    write(tmp_path, raw, "manifest.json")
    with pytest.raises(CaseSetJsonError):
        load_case_set_manifest("manifest.json", eval_root=tmp_path)


@pytest.mark.parametrize(
    ("text", "observed_type"),
    [("[1]", "list"), ('"x"', "str"), ("null", "NoneType")],
)
def test_non_object_manifest_rejected(
    tmp_path: Path, text: str, observed_type: str
) -> None:
    write(tmp_path, text, "manifest.json")
    with pytest.raises(CaseSetTopLevelTypeError) as excinfo:
        load_case_set_manifest("manifest.json", eval_root=tmp_path)
    assert excinfo.value.observed_type == observed_type


def test_duplicate_top_level_key_manifest(tmp_path: Path) -> None:
    write(tmp_path, '{"case_set_version": "a", "case_set_version": "b"}', "m.json")
    with pytest.raises(CaseSetJsonError) as excinfo:
        load_case_set_manifest("m.json", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "case_set_version"


def test_duplicate_nested_key_manifest(tmp_path: Path) -> None:
    write(tmp_path, '{"contract": {"k": 1, "k": 2}}', "m.json")
    with pytest.raises(CaseSetJsonError) as excinfo:
        load_case_set_manifest("m.json", eval_root=tmp_path)
    assert excinfo.value.duplicate_key == "k"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_non_finite_manifest_rejected(tmp_path: Path, constant: str) -> None:
    write(tmp_path, '{"x": ' + constant + "}", "m.json")
    with pytest.raises(CaseSetJsonError) as excinfo:
        load_case_set_manifest("m.json", eval_root=tmp_path)
    assert excinfo.value.constant_name == constant


def test_overflow_manifest_rejected(tmp_path: Path) -> None:
    write(tmp_path, '{"x": 1e999}', "m.json")
    with pytest.raises(CaseSetJsonError) as excinfo:
        load_case_set_manifest("m.json", eval_root=tmp_path)
    assert excinfo.value.constant_name == "Infinity"


def test_non_object_event_line_with_line_number(tmp_path: Path) -> None:
    name = write_events(tmp_path, [event_payload(), "[1, 2]"])
    with pytest.raises(CaseSetTopLevelTypeError) as excinfo:
        load_membership_events(name, eval_root=tmp_path)
    assert excinfo.value.line_number == 2
    assert excinfo.value.observed_type == "list"


def test_duplicate_key_on_later_event_line(tmp_path: Path) -> None:
    name = write_events(tmp_path, [event_payload(), '{"case_id": "a", "case_id": "b"}'])
    with pytest.raises(CaseSetJsonError) as excinfo:
        load_membership_events(name, eval_root=tmp_path)
    assert excinfo.value.line_number == 2
    assert excinfo.value.duplicate_key == "case_id"


def test_overflow_event_line(tmp_path: Path) -> None:
    name = write_events(tmp_path, ['{"x": -1e999}'])
    with pytest.raises(CaseSetJsonError) as excinfo:
        load_membership_events(name, eval_root=tmp_path)
    assert excinfo.value.constant_name == "-Infinity"
    assert excinfo.value.line_number == 1


def test_internal_blank_event_line_rejected(tmp_path: Path) -> None:
    text = json.dumps(event_payload()) + "\n\n" + json.dumps(event_payload()) + "\n"
    (tmp_path / "events.jsonl").write_text(text, encoding="utf-8")
    with pytest.raises(CaseSetJsonError) as excinfo:
        load_membership_events("events.jsonl", eval_root=tmp_path)
    assert excinfo.value.line_number == 2


def test_whitespace_only_event_line_rejected(tmp_path: Path) -> None:
    text = json.dumps(event_payload()) + "\n   \n"
    (tmp_path / "events.jsonl").write_text(text, encoding="utf-8")
    with pytest.raises(CaseSetJsonError) as excinfo:
        load_membership_events("events.jsonl", eval_root=tmp_path)
    assert excinfo.value.line_number == 2


def test_missing_final_newline_accepted(tmp_path: Path) -> None:
    (tmp_path / "events.jsonl").write_text(
        json.dumps(event_payload()), encoding="utf-8"
    )
    events = load_membership_events("events.jsonl", eval_root=tmp_path)
    assert len(events) == 1


def test_empty_events_file_returns_empty_tuple(tmp_path: Path) -> None:
    (tmp_path / "events.jsonl").write_bytes(b"")
    assert load_membership_events("events.jsonl", eval_root=tmp_path) == ()


def test_invalid_utf8_events_file(tmp_path: Path) -> None:
    (tmp_path / "events.jsonl").write_bytes(b"\xff\xfe")
    with pytest.raises(CaseSetDecodeError):
        load_membership_events("events.jsonl", eval_root=tmp_path)


def test_nan_string_reason_code_preserved(tmp_path: Path) -> None:
    name = write_events(tmp_path, [event_payload(reason_code="NaN")])
    events = load_membership_events(name, eval_root=tmp_path)
    assert events[0].reason_code == "NaN"


# --- Model and contract validation ---------------------------------------


def test_missing_required_field(tmp_path: Path) -> None:
    payload = manifest_payload()
    del payload["case_set_version"]
    write(tmp_path, payload, "m.json")
    with pytest.raises(CaseSetModelValidationError) as excinfo:
        load_case_set_manifest("m.json", eval_root=tmp_path)
    assert isinstance(excinfo.value.__cause__, pydantic.ValidationError)
    assert "case_set_version" in excinfo.value.field_locations


def test_unknown_field_rejected(tmp_path: Path) -> None:
    write(tmp_path, manifest_payload(zzz_unknown="x"), "m.json")
    with pytest.raises(CaseSetModelValidationError) as excinfo:
        load_case_set_manifest("m.json", eval_root=tmp_path)
    assert "extra_forbidden" in excinfo.value.error_types


def test_explicit_null_rejected(tmp_path: Path) -> None:
    write(tmp_path, manifest_payload(case_set_version=None), "m.json")
    with pytest.raises(CaseSetModelValidationError):
        load_case_set_manifest("m.json", eval_root=tmp_path)


def test_wrong_contract_id(tmp_path: Path) -> None:
    payload = manifest_payload()
    payload["contract"]["contract_id"] = "membership_event"
    write(tmp_path, payload, "m.json")
    with pytest.raises(CaseSetModelValidationError):
        load_case_set_manifest("m.json", eval_root=tmp_path)


def test_wrong_contract_version(tmp_path: Path) -> None:
    payload = manifest_payload()
    payload["contract"]["contract_version"] = "9.9.9"
    write(tmp_path, payload, "m.json")
    with pytest.raises(CaseSetModelValidationError):
        load_case_set_manifest("m.json", eval_root=tmp_path)


def test_wrong_contract_hash(tmp_path: Path) -> None:
    payload = manifest_payload()
    payload["contract"]["contract_hash"] = "0" * 64
    write(tmp_path, payload, "m.json")
    with pytest.raises(CaseSetModelValidationError):
        load_case_set_manifest("m.json", eval_root=tmp_path)


def test_malformed_hash_field(tmp_path: Path) -> None:
    write(tmp_path, manifest_payload(registry_snapshot_hash="xyz"), "m.json")
    with pytest.raises(CaseSetModelValidationError):
        load_case_set_manifest("m.json", eval_root=tmp_path)


def test_event_line_wrong_contract_hash(tmp_path: Path) -> None:
    payload = event_payload()
    payload["contract"]["contract_hash"] = "0" * 64
    name = write_events(tmp_path, [payload])
    with pytest.raises(CaseSetModelValidationError) as excinfo:
        load_membership_events(name, eval_root=tmp_path)
    assert excinfo.value.line_number == 1


def test_model_error_does_not_leak_values(tmp_path: Path) -> None:
    write(
        tmp_path, manifest_payload(registry_snapshot_hash="SYNTH-LEAK-MARKER"), "m.json"
    )
    with pytest.raises(CaseSetModelValidationError) as excinfo:
        load_case_set_manifest("m.json", eval_root=tmp_path)
    exc = excinfo.value
    assert "SYNTH-LEAK-MARKER" not in str(exc)
    for attr in (*exc.field_locations, *exc.error_types):
        assert "SYNTH-LEAK-MARKER" not in attr


@pytest.mark.parametrize("bad", ["", "   "])
def test_event_timestamp_blank_rejected(tmp_path: Path, bad: str) -> None:
    name = write_events(tmp_path, [event_payload(timestamp=bad)])
    with pytest.raises(CaseSetModelValidationError) as excinfo:
        load_membership_events(name, eval_root=tmp_path)
    assert excinfo.value.line_number == 1


def test_event_timestamp_not_normalized(tmp_path: Path) -> None:
    name = write_events(tmp_path, [event_payload(timestamp="synthetic-clock-42")])
    events = load_membership_events(name, eval_root=tmp_path)
    assert events[0].timestamp == "synthetic-clock-42"


# --- Membership invariants ------------------------------------------------


def test_duplicate_case_id_rejected(tmp_path: Path) -> None:
    entries = [entry("CASE-A"), entry("CASE-A", "frozen_test")]
    write(tmp_path, manifest_payload(entries=entries), "m.json")
    with pytest.raises(CaseSetModelValidationError):
        load_case_set_manifest("m.json", eval_root=tmp_path)


def test_duplicate_suites_in_membership_rejected(tmp_path: Path) -> None:
    entries = [entry("CASE-A", "dev", ["smoke", "smoke"])]
    write(tmp_path, manifest_payload(entries=entries), "m.json")
    with pytest.raises(CaseSetConsistencyError) as excinfo:
        load_case_set_manifest("m.json", eval_root=tmp_path)
    assert excinfo.value.conflict_kind == "duplicate_suite_membership"
    assert excinfo.value.case_id == "CASE-A"


def test_duplicate_added_suites_rejected(tmp_path: Path) -> None:
    name = write_events(tmp_path, [event_payload(added_suites=["smoke", "smoke"])])
    with pytest.raises(CaseSetConsistencyError) as excinfo:
        load_membership_events(name, eval_root=tmp_path)
    assert excinfo.value.conflict_kind == "duplicate_suite_membership"
    assert excinfo.value.event_index == 0


def test_duplicate_removed_suites_rejected(tmp_path: Path) -> None:
    name = write_events(
        tmp_path, [event_payload(removed_suites=["boundary", "boundary"])]
    )
    with pytest.raises(CaseSetConsistencyError) as excinfo:
        load_membership_events(name, eval_root=tmp_path)
    assert excinfo.value.conflict_kind == "duplicate_suite_membership"


def test_overlapping_suites_across_cases_accepted(tmp_path: Path) -> None:
    entries = [
        entry("CASE-A", "dev", ["regression", "smoke"]),
        entry("CASE-B", "frozen_test", ["regression"], "2" * 64),
    ]
    write(tmp_path, manifest_payload(entries=entries), "m.json")
    manifest = load_case_set_manifest("m.json", eval_root=tmp_path)
    assert manifest.entries[0].suites == ("regression", "smoke")


def test_invalid_partition_rejected(tmp_path: Path) -> None:
    entries = [entry("CASE-A", "calibration")]
    write(tmp_path, manifest_payload(entries=entries), "m.json")
    with pytest.raises(CaseSetModelValidationError):
        load_case_set_manifest("m.json", eval_root=tmp_path)


# --- Succession -----------------------------------------------------------


def expect_conflict(kind, base_entries, events, successor_entries):
    with pytest.raises(CaseSetConsistencyError) as excinfo:
        succession(base_entries, events, successor_entries)
    assert excinfo.value.conflict_kind == kind
    return excinfo.value


def test_valid_tracked_succession() -> None:
    base = load_case_set_manifest("valid_base_case_set_manifest.json", eval_root=FIX)
    events = load_membership_events("valid_membership_events.jsonl", eval_root=FIX)
    successor = load_case_set_manifest(
        "valid_frozen_case_set_manifest.json", eval_root=FIX
    )
    verify_case_set_succession(base, events, successor)


def test_valid_repeated_events_for_one_case() -> None:
    succession(
        [entry("CASE-A", "dev", ["adversarial"])],
        [
            make_event(new_partition="dev", added_suites=["smoke"]),
            make_event(old_partition="dev", new_partition="frozen_test"),
        ],
        [entry("CASE-A", "frozen_test", ["adversarial", "smoke"])],
    )


def test_valid_suite_only_event() -> None:
    succession(
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(new_partition="dev", added_suites=["regression"])],
        [entry("CASE-A", "dev", ["adversarial", "regression"])],
    )


def test_valid_partition_only_event() -> None:
    succession(
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event()],
        [entry("CASE-A", "frozen_test", ["adversarial"])],
    )


def test_valid_case_addition() -> None:
    succession(
        [entry("CASE-A", "dev", ["adversarial"])],
        [
            make_event(
                case_id="CASE-NEW",
                old_partition=None,
                new_partition="dev",
                added_suites=["boundary"],
            )
        ],
        [
            entry("CASE-A", "dev", ["adversarial"]),
            entry("CASE-NEW", "dev", ["boundary"], "9" * 64),
        ],
    )


def test_valid_case_removal() -> None:
    succession(
        [entry("CASE-A", "dev", ["adversarial"]), entry("CASE-B", "frozen_test", [], "2" * 64)],
        [
            make_event(
                case_id="CASE-B",
                old_partition="frozen_test",
                new_partition=None,
                removed_suites=[],
            )
        ],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_valid_net_zero_sequence() -> None:
    succession(
        [entry("CASE-A", "dev", ["adversarial"])],
        [
            make_event(new_partition="dev", added_suites=["smoke"]),
            make_event(new_partition="dev", removed_suites=["smoke"]),
        ],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_same_version_rejected() -> None:
    base = make_manifest(version="set-v1")
    successor = make_manifest(version="set-v1")
    with pytest.raises(CaseSetConsistencyError) as excinfo:
        verify_case_set_succession(base, [], successor)
    assert excinfo.value.conflict_kind == "same_version_change"


def test_event_previous_version_mismatch() -> None:
    exc = expect_conflict(
        "version_chain_mismatch",
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(previous_case_set_version="set-v0")],
        [entry("CASE-A", "frozen_test", ["adversarial"])],
    )
    assert exc.event_index == 0


def test_event_new_version_mismatch() -> None:
    expect_conflict(
        "version_chain_mismatch",
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(new_case_set_version="set-v9")],
        [entry("CASE-A", "frozen_test", ["adversarial"])],
    )


def test_unknown_case_with_old_partition() -> None:
    expect_conflict(
        "unknown_case_reference",
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(case_id="CASE-GHOST", old_partition="dev")],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_unknown_case_with_no_partitions() -> None:
    expect_conflict(
        "unknown_case_reference",
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(case_id="CASE-GHOST", old_partition=None, new_partition=None)],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_addition_with_removed_suites_rejected() -> None:
    expect_conflict(
        "contradictory_suite_change",
        [entry("CASE-A", "dev", ["adversarial"])],
        [
            make_event(
                case_id="CASE-NEW",
                old_partition=None,
                new_partition="dev",
                removed_suites=["smoke"],
            )
        ],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_stale_old_partition_on_update() -> None:
    expect_conflict(
        "stale_old_partition",
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(old_partition="frozen_test")],
        [entry("CASE-A", "frozen_test", ["adversarial"])],
    )


def test_stale_old_partition_on_removal() -> None:
    expect_conflict(
        "stale_old_partition",
        [entry("CASE-A", "dev", ["adversarial"])],
        [
            make_event(
                old_partition="frozen_test",
                new_partition=None,
                removed_suites=["adversarial"],
            )
        ],
        [],
    )


def test_add_and_remove_same_suite_rejected() -> None:
    expect_conflict(
        "contradictory_suite_change",
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(new_partition="dev", added_suites=["smoke"], removed_suites=["smoke"])],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_adding_existing_suite_rejected() -> None:
    expect_conflict(
        "contradictory_suite_change",
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(new_partition="dev", added_suites=["adversarial"])],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_removing_nonexistent_suite_rejected() -> None:
    expect_conflict(
        "contradictory_suite_change",
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(new_partition="dev", removed_suites=["smoke"])],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_removal_with_incomplete_suite_list_rejected() -> None:
    expect_conflict(
        "contradictory_suite_change",
        [entry("CASE-A", "dev", ["adversarial", "smoke"])],
        [make_event(old_partition="dev", new_partition=None, removed_suites=["smoke"])],
        [],
    )


def test_removal_with_added_suites_rejected() -> None:
    expect_conflict(
        "contradictory_suite_change",
        [entry("CASE-A", "dev", [])],
        [make_event(old_partition="dev", new_partition=None, added_suites=["smoke"])],
        [],
    )


def test_no_op_event_rejected() -> None:
    expect_conflict(
        "unexplained_event",
        [entry("CASE-A", "dev", ["adversarial"])],
        [make_event(new_partition="dev")],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_addition_missing_from_successor_rejected() -> None:
    exc = expect_conflict(
        "unexplained_event",
        [entry("CASE-A", "dev", ["adversarial"])],
        [
            make_event(
                case_id="CASE-NEW",
                old_partition=None,
                new_partition="dev",
                added_suites=["boundary"],
            )
        ],
        [entry("CASE-A", "dev", ["adversarial"])],
    )
    assert exc.case_id == "CASE-NEW"


def test_unexplained_successor_addition() -> None:
    expect_conflict(
        "unexplained_membership_change",
        [entry("CASE-A", "dev", ["adversarial"])],
        [],
        [
            entry("CASE-A", "dev", ["adversarial"]),
            entry("CASE-EXTRA", "dev", [], "8" * 64),
        ],
    )


def test_unexplained_successor_removal() -> None:
    expect_conflict(
        "unexplained_membership_change",
        [entry("CASE-A", "dev", ["adversarial"]), entry("CASE-B", "dev", [], "2" * 64)],
        [],
        [entry("CASE-A", "dev", ["adversarial"])],
    )


def test_unexplained_partition_change() -> None:
    expect_conflict(
        "unexplained_membership_change",
        [entry("CASE-A", "dev", ["adversarial"])],
        [],
        [entry("CASE-A", "frozen_test", ["adversarial"])],
    )


def test_unexplained_suite_change() -> None:
    expect_conflict(
        "unexplained_membership_change",
        [entry("CASE-A", "dev", ["adversarial"])],
        [],
        [entry("CASE-A", "dev", ["adversarial", "smoke"])],
    )


def test_existing_packet_hash_change_rejected() -> None:
    expect_conflict(
        "unexplained_membership_change",
        [entry("CASE-A", "dev", ["adversarial"], "1" * 64)],
        [],
        [entry("CASE-A", "dev", ["adversarial"], "5" * 64)],
    )


def test_successor_entry_order_change_rejected() -> None:
    expect_conflict(
        "unexplained_membership_change",
        [entry("CASE-A", "dev", []), entry("CASE-B", "dev", [], "2" * 64)],
        [],
        [entry("CASE-B", "dev", [], "2" * 64), entry("CASE-A", "dev", [])],
    )


def test_successor_suite_order_change_rejected() -> None:
    expect_conflict(
        "unexplained_membership_change",
        [entry("CASE-A", "dev", ["adversarial", "smoke"])],
        [],
        [entry("CASE-A", "dev", ["smoke", "adversarial"])],
    )


def test_re_addition_packet_hash_mutation_rejected() -> None:
    """Remove/re-add must not launder an unrepresentable packet-hash change."""
    exc = expect_conflict(
        "unexplained_membership_change",
        [entry("CASE-A", "dev", ["adversarial"], "1" * 64)],
        [
            make_event(
                old_partition="dev", new_partition=None, removed_suites=["adversarial"]
            ),
            make_event(old_partition=None, new_partition="dev", added_suites=["smoke"]),
        ],
        [entry("CASE-A", "dev", ["smoke"], "5" * 64)],
    )
    assert exc.case_id == "CASE-A"


def test_re_addition_with_preserved_identity_accepted() -> None:
    succession(
        [
            entry("CASE-A", "dev", ["adversarial"], "1" * 64),
            entry("CASE-B", "frozen_test", [], "2" * 64),
        ],
        [
            make_event(
                old_partition="dev", new_partition=None, removed_suites=["adversarial"]
            ),
            make_event(old_partition=None, new_partition="dev", added_suites=["smoke"]),
        ],
        [
            entry("CASE-B", "frozen_test", [], "2" * 64),
            entry("CASE-A", "dev", ["smoke"], "1" * 64),
        ],
    )


def test_intersection_mismatch_reported_in_base_entry_order() -> None:
    exc = expect_conflict(
        "unexplained_membership_change",
        [entry("CASE-A", "dev", [], "1" * 64), entry("CASE-B", "dev", [], "2" * 64)],
        [],
        [entry("CASE-A", "dev", [], "8" * 64), entry("CASE-B", "dev", [], "9" * 64)],
    )
    assert exc.case_id == "CASE-A"


def test_first_deterministic_conflict_reported() -> None:
    exc = expect_conflict(
        "version_chain_mismatch",
        [entry("CASE-A", "dev", ["adversarial"])],
        [
            make_event(previous_case_set_version="set-v0"),
            make_event(new_partition="dev"),
        ],
        [entry("CASE-A", "dev", ["adversarial"])],
    )
    assert exc.event_index == 0


# --- Snapshot hash --------------------------------------------------------


def test_snapshot_hash_is_64_lowercase_hex() -> None:
    digest = case_set_snapshot_hash(make_manifest())
    assert len(digest) == 64
    assert digest == digest.lower()
    int(digest, 16)


def test_snapshot_hash_repeated_calls_stable() -> None:
    manifest = make_manifest()
    assert case_set_snapshot_hash(manifest) == case_set_snapshot_hash(manifest)


def test_snapshot_hash_reload_stable() -> None:
    first = load_case_set_manifest("valid_frozen_case_set_manifest.json", eval_root=FIX)
    second = load_case_set_manifest(
        "valid_frozen_case_set_manifest.json", eval_root=FIX
    )
    assert case_set_snapshot_hash(first) == case_set_snapshot_hash(second)


def test_snapshot_hash_algorithm_includes_contract_metadata() -> None:
    manifest = make_manifest()
    payload = manifest.model_dump(mode="json", exclude_unset=True)
    assert "contract" in payload
    expected = sha256_bytes(canonical_contract_bytes(payload))
    assert case_set_snapshot_hash(manifest) == expected


def test_snapshot_hash_changes_with_content() -> None:
    assert case_set_snapshot_hash(make_manifest(version="set-v1")) != (
        case_set_snapshot_hash(make_manifest(version="set-v2"))
    )


def test_snapshot_hash_changes_with_entry_order() -> None:
    entries_a = [entry("CASE-A", "dev", []), entry("CASE-B", "dev", [], "2" * 64)]
    entries_b = [entry("CASE-B", "dev", [], "2" * 64), entry("CASE-A", "dev", [])]
    assert case_set_snapshot_hash(make_manifest(entries=entries_a)) != (
        case_set_snapshot_hash(make_manifest(entries=entries_b))
    )


def test_snapshot_hash_changes_with_suite_order() -> None:
    entries_a = [entry("CASE-A", "dev", ["adversarial", "smoke"])]
    entries_b = [entry("CASE-A", "dev", ["smoke", "adversarial"])]
    assert case_set_snapshot_hash(make_manifest(entries=entries_a)) != (
        case_set_snapshot_hash(make_manifest(entries=entries_b))
    )


def test_snapshot_hash_no_io_and_no_mutation(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = make_manifest()
    before = manifest.model_dump(mode="json", exclude_unset=True)

    def boom(self):
        raise AssertionError("filesystem read during snapshot hashing")

    monkeypatch.setattr(Path, "read_bytes", boom)
    monkeypatch.setattr(Path, "read_text", boom)
    case_set_snapshot_hash(manifest)
    assert manifest.model_dump(mode="json", exclude_unset=True) == before


def test_snapshot_hash_rejects_duplicate_suites() -> None:
    manifest = make_manifest(entries=[entry("CASE-A", "dev", ["smoke", "smoke"])])
    with pytest.raises(CaseSetConsistencyError) as excinfo:
        case_set_snapshot_hash(manifest)
    assert excinfo.value.conflict_kind == "duplicate_suite_membership"


def test_snapshot_hash_requires_manifest_type() -> None:
    with pytest.raises(TypeError):
        case_set_snapshot_hash({"case_set_version": "x"})  # type: ignore[arg-type]


# --- Append-only log extension -------------------------------------------


def test_extension_equality_accepted(tmp_path: Path) -> None:
    name = write_events(tmp_path, [event_payload()])
    verify_event_log_extension(name, name, eval_root=tmp_path)


def test_extension_from_empty_previous_accepted(tmp_path: Path) -> None:
    (tmp_path / "prev.jsonl").write_bytes(b"")
    write_events(tmp_path, [event_payload()], name="cur.jsonl")
    verify_event_log_extension("prev.jsonl", "cur.jsonl", eval_root=tmp_path)


def test_exact_byte_prefix_extension_accepted(tmp_path: Path) -> None:
    raw = (FIX / "valid_membership_events.jsonl").read_bytes()
    lines = raw.split(b"\n")
    previous = b"\n".join(lines[:2]) + b"\n"
    assert raw.startswith(previous)
    (tmp_path / "prev.jsonl").write_bytes(previous)
    (tmp_path / "cur.jsonl").write_bytes(raw)
    verify_event_log_extension("prev.jsonl", "cur.jsonl", eval_root=tmp_path)


def test_changed_historical_byte_rejected(tmp_path: Path) -> None:
    write_events(tmp_path, [event_payload()], name="prev.jsonl")
    write_events(
        tmp_path,
        [event_payload(reason_code="synthetic-rewritten"), event_payload()],
        name="cur.jsonl",
    )
    with pytest.raises(CaseSetConsistencyError) as excinfo:
        verify_event_log_extension("prev.jsonl", "cur.jsonl", eval_root=tmp_path)
    exc = excinfo.value
    assert exc.conflict_kind == "append_only_prefix_violation"
    assert exc.artifact_reference == "prev.jsonl"
    assert exc.related_artifact_reference == "cur.jsonl"
    assert '{"contract"' not in str(exc)


def test_truncated_current_rejected(tmp_path: Path) -> None:
    write_events(tmp_path, [event_payload(), event_payload()], name="prev.jsonl")
    write_events(tmp_path, [event_payload()], name="cur.jsonl")
    with pytest.raises(CaseSetConsistencyError) as excinfo:
        verify_event_log_extension("prev.jsonl", "cur.jsonl", eval_root=tmp_path)
    assert excinfo.value.conflict_kind == "append_only_prefix_violation"


def test_different_line_endings_rejected(tmp_path: Path) -> None:
    line = json.dumps(event_payload())
    (tmp_path / "prev.jsonl").write_bytes(line.encode() + b"\n")
    (tmp_path / "cur.jsonl").write_bytes(line.encode() + b"\r\n" + line.encode() + b"\n")
    with pytest.raises(CaseSetConsistencyError) as excinfo:
        verify_event_log_extension("prev.jsonl", "cur.jsonl", eval_root=tmp_path)
    assert excinfo.value.conflict_kind == "append_only_prefix_violation"


def test_invalid_previous_log_is_parse_error(tmp_path: Path) -> None:
    (tmp_path / "prev.jsonl").write_text("{not json\n", encoding="utf-8")
    write_events(tmp_path, [event_payload()], name="cur.jsonl")
    with pytest.raises(CaseSetJsonError):
        verify_event_log_extension("prev.jsonl", "cur.jsonl", eval_root=tmp_path)


def test_invalid_current_log_is_parse_error(tmp_path: Path) -> None:
    write_events(tmp_path, [event_payload()], name="prev.jsonl")
    (tmp_path / "cur.jsonl").write_text("{not json\n", encoding="utf-8")
    with pytest.raises(CaseSetJsonError):
        verify_event_log_extension("prev.jsonl", "cur.jsonl", eval_root=tmp_path)


# --- Slice 2 separation ---------------------------------------------------


def test_case_bodies_remain_split_agnostic() -> None:
    body = json.loads((CASE_FIX / "valid_minimal_case.json").read_text())
    membership_fields = {"split", "partition", "suites", "case_set_version", "lifecycle"}
    assert not membership_fields & set(body)


def test_manifest_loading_resolves_no_case_files() -> None:
    manifest = load_case_set_manifest(
        "valid_base_case_set_manifest.json", eval_root=FIX
    )
    for member in manifest.entries:
        assert not (FIX / f"{member.case_id}.json").exists()


def test_slice_2_loader_unchanged() -> None:
    case = load_case("valid_minimal_case.json", eval_root=CASE_FIX)
    assert case.case_id == "SYNTH-CASE-MIN-0001"


# --- Exports and import behavior -----------------------------------------

PUBLIC_SLICE_3_FUNCTIONS = (
    "load_case_set_manifest",
    "load_membership_events",
    "case_set_snapshot_hash",
    "verify_case_set_succession",
    "verify_event_log_extension",
)

PUBLIC_SLICE_3_EXCEPTIONS = (
    "CaseSetLoadError",
    "CaseSetArtifactNotFoundError",
    "CaseSetArtifactNotAFileError",
    "CaseSetPathEscapeError",
    "CaseSetReadError",
    "CaseSetDecodeError",
    "CaseSetJsonError",
    "CaseSetTopLevelTypeError",
    "CaseSetModelValidationError",
    "CaseSetConsistencyError",
)


def test_slice_3_functions_exported() -> None:
    for name in PUBLIC_SLICE_3_FUNCTIONS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(case_sets_module, name)


def test_slice_3_exceptions_exported() -> None:
    for name in PUBLIC_SLICE_3_EXCEPTIONS:
        assert name in evaluation_pkg.__all__
        assert getattr(evaluation_pkg, name) is getattr(case_sets_module, name)
    assert issubclass(CaseSetLoadError, Exception)
    assert not issubclass(CaseSetConsistencyError, CaseSetLoadError)


def test_package_all_parity_exact() -> None:
    public = {
        name
        for name in dir(evaluation_pkg)
        if not name.startswith("_")
        and not inspect.ismodule(getattr(evaluation_pkg, name))
    }
    assert set(evaluation_pkg.__all__) == public


def test_private_helpers_not_exported() -> None:
    private = (
        "_parse_membership_events",
        "_DuplicateKeyControl",
        "_NonFiniteControl",
        "_MembershipState",
        "_require_unique_membership_suites",
        "_resolve_contained_path",
    )
    for name in private:
        assert name not in evaluation_pkg.__all__
        assert not hasattr(evaluation_pkg, name)


def test_package_import_no_filesystem_read_or_hash() -> None:
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
        "sha_calls = []\n"
        "orig_sha = hashlib.sha256\n"
        "hashlib.sha256 = lambda *a, **k: (sha_calls.append(1), orig_sha(*a, **k))[1]\n"
        "import dynamic_ai_products.evaluation\n"
        "Path.read_bytes, Path.read_text = orig_rb, orig_rt\n"
        "hashlib.sha256 = orig_sha\n"
        "bad = [p for p in reads if p.endswith('.json') or p.endswith('.jsonl') "
        "or '/schemas/' in p or '/evals/' in p]\n"
        "assert not bad, bad\n"
        "assert not sha_calls, 'sha256 called during package import'\n"
        "print('OK')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT
    )
    assert result.returncode == 0 and "OK" in result.stdout, result.stderr
