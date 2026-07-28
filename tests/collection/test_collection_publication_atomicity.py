"""Atomic publication and pre-network duplicate refusal."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402
from dynamic_ai_products.collection.manifests import build_collection_identity  # noqa: E402
from dynamic_ai_products.collection.publication import (  # noqa: E402
    PUBLICATION_MODEL,
    RUN_ROOT_TEMPLATES,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    derive_collection_run_id,
    materialize_template,
    open_staging_root,
    publish_run_root,
    refuse_duplicate_run,
    run_root_for,
    stage_artifact,
    staging_root_for,
)
from dynamic_ai_products.collection.transport import require_planned_request  # noqa: E402
from dynamic_ai_products.collection.request_plan import validate_request_plan  # noqa: E402
from collection_test_helpers import (  # noqa: E402
    CODE_COMMIT,
    RUN_CREATED_AT,
    FakeTransport,
    plan_payload,
)

RUN_ID = "owc-" + "0" * 32
PLAN_SHA = "d" * 64


def _identity(**overrides):
    identity = build_collection_identity(
        code_commit=CODE_COMMIT,
        run_created_at=RUN_CREATED_AT,
        request_plan_sha256=PLAN_SHA,
    )
    identity.update(overrides)
    return identity


# --- Templates ----------------------------------------------------------------


def test_seven_templates_are_owned_here() -> None:
    assert len(RUN_ROOT_TEMPLATES) == 7
    assert len(set(RUN_ROOT_TEMPLATES.values())) == 7
    for template in RUN_ROOT_TEMPLATES.values():
        segments = template.split("/")
        assert segments[:3] == ["data", "runs", "{collection_run_id}"]
        assert segments.count("{collection_run_id}") == 1


def test_materializes_every_template() -> None:
    for template in RUN_ROOT_TEMPLATES.values():
        resolved = materialize_template(template, RUN_ID)
        assert resolved.startswith(f"data/runs/{RUN_ID}/")
        assert "{" not in resolved and "}" not in resolved


@pytest.mark.parametrize(
    "template",
    [
        "data/runs/{collection_run_id}/{other}/x.json",
        "data/runs/{collection_run_id}-suffix/x.json",
        "data/runs/{collection_run_id/x.json",
        "data/runs/plain/x.json",
        "data/runs/{collection_run_id}/{collection_run_id}/x.json",
        "",
    ],
)
def test_malformed_template_is_refused(template: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        materialize_template(template, RUN_ID)
    assert excinfo.value.reason_code == "template_invalid"


@pytest.mark.parametrize("run_id", ["owc-XYZ", "owc-" + "0" * 31, "ing-" + "0" * 32, ""])
def test_malformed_run_id_is_refused(run_id: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        materialize_template(RUN_ROOT_TEMPLATES["web_snapshot_manifest"], run_id)
    assert excinfo.value.reason_code == "run_id_invalid"


# --- Pre-network duplicate refusal -------------------------------------------


def _relative(key: str, run_id: str) -> str:
    return materialize_template(RUN_ROOT_TEMPLATES[key], run_id).split(
        f"{run_id}/", 1
    )[1]


def test_duplicate_run_root_refused_before_any_request(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    run_root_for(runs_root, RUN_ID).mkdir()
    transport = FakeTransport()
    plan = validate_request_plan(plan_payload())

    with pytest.raises(CollectionError) as excinfo:
        refuse_duplicate_run(runs_root, RUN_ID)
        # Unreachable: a real run would only now start requesting.
        require_planned_request(sorted(plan["entries"])[0]["source_url"], plan)
        transport("https://ir.hubspot.com/x")
    assert excinfo.value.reason_code == "run_root_exists"
    assert transport.calls == [], "a duplicate run must issue zero requests"


def test_duplicate_staging_root_refused_before_any_request(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    staging_root_for(runs_root, RUN_ID).mkdir()
    transport = FakeTransport()
    with pytest.raises(CollectionError) as excinfo:
        refuse_duplicate_run(runs_root, RUN_ID)
        transport("https://ir.hubspot.com/x")
    assert excinfo.value.reason_code == "staging_root_exists"
    assert transport.calls == []


def test_clean_root_passes_the_duplicate_gate(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    refuse_duplicate_run(runs_root, RUN_ID)  # no exception


def test_run_id_is_derivable_before_staging_or_transport(tmp_path: Path) -> None:
    """Identity depends only on injected/pin-verified values, never on I/O."""
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    transport = FakeTransport()
    run_id = derive_collection_run_id(_identity())
    assert run_id.startswith("owc-")
    assert transport.calls == []
    assert not list(runs_root.iterdir())


# --- Staging and atomic publication ------------------------------------------


def _stage_all(runs_root: Path, run_id: str) -> dict[str, str]:
    staging = open_staging_root(runs_root, run_id)
    bindings = {}
    for key in RUN_ROOT_TEMPLATES:
        data = (
            canonical_jsonl_bytes([{"k": key}])
            if key.endswith("candidates") or key == "web_snapshot_manifest"
            else canonical_json_bytes({"k": key})
        )
        bindings[key] = stage_artifact(staging, _relative(key, run_id), data)
    return bindings


def test_happy_path_publishes_seven_artifacts(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _stage_all(runs_root, RUN_ID)
    root = publish_run_root(runs_root, RUN_ID)
    assert root.is_dir()
    assert len([p for p in root.rglob("*") if p.is_file()]) == 7
    assert not staging_root_for(runs_root, RUN_ID).exists()


def test_failure_during_staging_publishes_nothing(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    staging = open_staging_root(runs_root, RUN_ID)
    stage_artifact(staging, _relative("web_discovery_manifest", RUN_ID), b"{}\n")
    with pytest.raises(CollectionError):
        stage_artifact(staging, _relative("web_discovery_manifest", RUN_ID), b"{}\n")
    assert not run_root_for(runs_root, RUN_ID).exists()
    assert staging.exists(), "the staging root is preserved for inspection"


def test_failure_at_rename_publishes_nothing(tmp_path: Path, monkeypatch) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _stage_all(runs_root, RUN_ID)

    def boom(src, dst):
        raise OSError("injected rename failure")

    monkeypatch.setattr(os, "rename", boom)
    with pytest.raises(CollectionError) as excinfo:
        publish_run_root(runs_root, RUN_ID)
    monkeypatch.undo()
    assert excinfo.value.reason_code == "publication_failed"
    assert not run_root_for(runs_root, RUN_ID).exists()
    assert staging_root_for(runs_root, RUN_ID).exists()


def test_publication_refuses_a_pre_existing_run_root(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    _stage_all(runs_root, RUN_ID)
    final = run_root_for(runs_root, RUN_ID)
    final.mkdir()
    (final / "occupied.txt").write_text("prior run")
    with pytest.raises(CollectionError) as excinfo:
        publish_run_root(runs_root, RUN_ID)
    assert excinfo.value.reason_code == "run_root_exists"


def test_missing_staging_root_is_refused(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    with pytest.raises(CollectionError) as excinfo:
        publish_run_root(runs_root, RUN_ID)
    assert excinfo.value.reason_code == "staging_root_missing"


def test_staging_root_is_never_reused(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    open_staging_root(runs_root, RUN_ID)
    with pytest.raises(CollectionError) as excinfo:
        open_staging_root(runs_root, RUN_ID)
    assert excinfo.value.reason_code == "staging_root_exists"


def test_publication_model_is_declared() -> None:
    assert PUBLICATION_MODEL == "staging_root_atomic_rename"


def test_staging_and_destination_share_a_filesystem(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    assert staging_root_for(runs_root, RUN_ID).parent == run_root_for(
        runs_root, RUN_ID
    ).parent
    assert os.stat(runs_root).st_dev == os.stat(tmp_path).st_dev
