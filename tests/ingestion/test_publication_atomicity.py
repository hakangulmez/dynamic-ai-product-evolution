"""Publication transaction: staging root, atomic rename, failure injection."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.ingestion import preflight as pf  # noqa: E402
from dynamic_ai_products.ingestion.errors import IngestionError  # noqa: E402
from dynamic_ai_products.ingestion.publication import (  # noqa: E402
    PUBLICATION_MODEL,
    RUN_ID_PATTERN,
    RUN_ROOT_TEMPLATES,
    derive_run_id,
    materialize_template,
    open_staging_root,
    publish_run_root,
    run_root_for,
    stage_artifact,
    staging_root_for,
)
from ingestion_test_helpers import preflight_kwargs  # noqa: E402

RUN_ID = "ing-" + "0" * 32


# --- run_id derivation --------------------------------------------------------


def _derive(**overrides) -> str:
    kwargs = {
        "code_commit": "a" * 40,
        "run_created_at": "2026-07-28T00:00:00+00:00",
        "company_id": "CIK0001404655",
        "observation_cutoff_date": "2025-02-12",
        "collection_receipt_sha256": "c" * 64,
        "packet_sha256": "d" * 64,
        "normalizer_version": "sec_html_item_span_v1",
    }
    kwargs.update(overrides)
    return derive_run_id(**kwargs)


def test_run_id_format_and_determinism() -> None:
    run_id = _derive()
    assert RUN_ID_PATTERN.fullmatch(run_id)
    assert run_id == _derive()


def test_run_id_changes_with_commit_or_timestamp() -> None:
    assert _derive() != _derive(code_commit="b" * 40)
    assert _derive() != _derive(run_created_at="2026-07-29T00:00:00+00:00")


def test_run_id_requires_injected_values() -> None:
    with pytest.raises(IngestionError) as excinfo:
        _derive(code_commit="  ")
    assert excinfo.value.reason_code == "run_identity_invalid"


# --- template materialization -------------------------------------------------


LOCKED_TEMPLATES = {
    "sec_source_candidates": "data/runs/{run_id}/registry/sec_source_candidates.parquet",
    "sec_discovery_manifest": "data/runs/{run_id}/manifests/sec_discovery_manifest.json",
    "source_family_coverage": "data/runs/{run_id}/manifests/source_family_coverage.json",
    "snapshot_manifest": "data/runs/{run_id}/manifests/snapshot_manifest.jsonl",
    "normalized_documents": "data/runs/{run_id}/normalized/documents.parquet",
    "normalized_passages": "data/runs/{run_id}/normalized/passages.parquet",
    "ingestion_preflight_manifest": (
        "data/runs/{run_id}/manifests/ingestion_preflight_manifest.json"
    ),
}


def test_the_seven_locked_templates_are_owned_here() -> None:
    """RUN_ROOT_TEMPLATES is the Pilot 0 Increment-B execution contract.

    It lives in the ingestion package, never in the general stage registry.
    """
    assert RUN_ROOT_TEMPLATES == LOCKED_TEMPLATES
    assert len(RUN_ROOT_TEMPLATES) == 7
    assert len(set(RUN_ROOT_TEMPLATES.values())) == 7


def test_every_locked_template_has_one_run_id_segment() -> None:
    for template in RUN_ROOT_TEMPLATES.values():
        segments = template.split("/")
        assert segments[:3] == ["data", "runs", "{run_id}"]
        assert segments.count("{run_id}") == 1
        assert template.count("{") == template.count("}") == 1


def test_materializes_every_locked_template() -> None:
    for template in RUN_ROOT_TEMPLATES.values():
        resolved = materialize_template(template, RUN_ID)
        assert resolved.startswith(f"data/runs/{RUN_ID}/")
        assert "{" not in resolved and "}" not in resolved


@pytest.mark.parametrize(
    "template",
    [
        "data/runs/{run_id}/{other}/x.json",  # unknown placeholder
        "data/runs/{run_id}-suffix/x.json",  # partial segment
        "data/runs/prefix-{run_id}/x.json",  # partial segment
        "data/runs/{run_id/x.json",  # unbalanced brace
        "data/runs/{run_id}}/x.json",  # unbalanced brace
        "data/runs/no_placeholder/x.json",  # missing placeholder
        "data/runs/{run_id}/{run_id}/x.json",  # duplicated placeholder
        "",  # empty template
    ],
)
def test_malformed_template_is_refused(template: str) -> None:
    with pytest.raises(IngestionError) as excinfo:
        materialize_template(template, RUN_ID)
    assert excinfo.value.reason_code == "template_invalid"


def test_run_root_confinement_is_enforced_by_the_preflight_resolver() -> None:
    """materialize_template validates shape; _relative enforces the run root.

    A well-formed template outside data/runs/{run_id}/ materializes fine but
    can never be staged.
    """
    outside = "data/normalized/{run_id}/x.parquet"
    assert materialize_template(outside, RUN_ID) == f"data/normalized/{RUN_ID}/x.parquet"

    monkey = dict(pf.RUN_ROOT_TEMPLATES)
    try:
        pf.RUN_ROOT_TEMPLATES["_probe"] = outside
        with pytest.raises(IngestionError) as excinfo:
            pf._relative("_probe", RUN_ID)
        assert excinfo.value.reason_code == "template_invalid"
    finally:
        pf.RUN_ROOT_TEMPLATES.clear()
        pf.RUN_ROOT_TEMPLATES.update(monkey)


@pytest.mark.parametrize("run_id", ["ing-XYZ", "ing-" + "0" * 31, "../escape", ""])
def test_malformed_run_id_is_refused(run_id: str) -> None:
    with pytest.raises(IngestionError) as excinfo:
        materialize_template(RUN_ROOT_TEMPLATES["normalized_documents"], run_id)
    assert excinfo.value.reason_code == "run_id_invalid"


# --- staging and publication --------------------------------------------------


def test_happy_path_publishes_seven_artifacts(tmp_path: Path) -> None:
    result = pf.run_ingestion_preflight(**preflight_kwargs(tmp_path))
    assert result.verdict == "ready_for_extraction"
    assert result.run_root is not None and result.run_root.is_dir()
    files = sorted(p.relative_to(result.run_root).as_posix() for p in result.run_root.rglob("*") if p.is_file())
    assert files == sorted(
        materialize_template(t, result.run_id).split(f"{result.run_id}/", 1)[1]
        for t in RUN_ROOT_TEMPLATES.values()
    )
    assert len(files) == 7
    assert len(result.artifact_bindings) == 7
    assert result.manifest["publication_model"] == PUBLICATION_MODEL
    # The staging root is consumed by the rename.
    assert not staging_root_for(tmp_path / "runs", result.run_id).exists()


def _fail_at(monkeypatch, nth_call: int) -> None:
    """Make the nth stage_artifact call raise, leaving earlier ones written."""
    calls = {"n": 0}
    real = pf.stage_artifact

    def wrapped(staging_root, relative_path, data):
        calls["n"] += 1
        if calls["n"] == nth_call:
            raise IngestionError("injected staging failure", reason_code="write_error")
        return real(staging_root, relative_path, data)

    monkeypatch.setattr(pf, "stage_artifact", wrapped)


@pytest.mark.parametrize("nth", [1, 4, 7])
def test_failure_during_staging_publishes_nothing(
    tmp_path: Path, monkeypatch, nth: int
) -> None:
    kwargs = preflight_kwargs(tmp_path)
    _fail_at(monkeypatch, nth)
    with pytest.raises(IngestionError):
        pf.run_ingestion_preflight(**kwargs)
    monkeypatch.undo()

    runs_root = kwargs["runs_root"]
    published = [p for p in runs_root.iterdir() if not p.name.startswith(".staging-")]
    assert published == [], "no run root may exist after a staging failure"

    staging = [p for p in runs_root.iterdir() if p.name.startswith(".staging-")]
    assert len(staging) == 1, "the staging root is preserved for inspection"
    # No authoritative manifest is readable anywhere outside staging.
    assert not list(runs_root.glob("ing-*/manifests/ingestion_preflight_manifest.json"))


def test_failure_at_rename_publishes_nothing(tmp_path: Path, monkeypatch) -> None:
    kwargs = preflight_kwargs(tmp_path)

    def boom(src, dst):
        raise OSError("injected rename failure")

    monkeypatch.setattr(os, "rename", boom)
    with pytest.raises(IngestionError) as excinfo:
        pf.run_ingestion_preflight(**kwargs)
    monkeypatch.undo()
    assert excinfo.value.reason_code == "publication_failed"

    runs_root = kwargs["runs_root"]
    assert [p for p in runs_root.iterdir() if not p.name.startswith(".staging-")] == []
    assert len([p for p in runs_root.iterdir() if p.name.startswith(".staging-")]) == 1


def test_staging_root_is_never_reused(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    open_staging_root(runs_root, RUN_ID)
    with pytest.raises(IngestionError) as excinfo:
        open_staging_root(runs_root, RUN_ID)
    assert excinfo.value.reason_code == "staging_root_exists"


def test_publication_refuses_a_pre_existing_run_root(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    staging = open_staging_root(runs_root, RUN_ID)
    stage_artifact(staging, "manifests/x.json", b"{}\n")
    run_root_for(runs_root, RUN_ID).mkdir()
    (run_root_for(runs_root, RUN_ID) / "occupied.txt").write_text("prior run")
    with pytest.raises(IngestionError) as excinfo:
        publish_run_root(runs_root, RUN_ID)
    assert excinfo.value.reason_code == "run_root_exists"


def test_missing_staging_root_is_refused(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    with pytest.raises(IngestionError) as excinfo:
        publish_run_root(runs_root, RUN_ID)
    assert excinfo.value.reason_code == "staging_root_missing"


def test_rerun_with_new_identity_publishes_beside_failed_staging(
    tmp_path: Path, monkeypatch
) -> None:
    kwargs = preflight_kwargs(tmp_path)
    _fail_at(monkeypatch, 2)
    with pytest.raises(IngestionError):
        pf.run_ingestion_preflight(**kwargs)
    monkeypatch.undo()

    failed_staging = [
        p for p in kwargs["runs_root"].iterdir() if p.name.startswith(".staging-")
    ]
    assert len(failed_staging) == 1
    before = sorted(p.name for p in failed_staging[0].rglob("*"))

    retry = dict(kwargs, run_created_at="2026-07-28T01:00:00+00:00")
    result = pf.run_ingestion_preflight(**retry)
    assert result.run_root is not None and result.run_root.is_dir()
    # The failed staging root is untouched and never auto-deleted.
    assert failed_staging[0].exists()
    assert sorted(p.name for p in failed_staging[0].rglob("*")) == before


def test_published_run_root_is_not_modified_by_a_later_run(tmp_path: Path) -> None:
    kwargs = preflight_kwargs(tmp_path)
    first = pf.run_ingestion_preflight(**kwargs)
    snapshot = {
        p.relative_to(first.run_root).as_posix(): p.read_bytes()
        for p in first.run_root.rglob("*")
        if p.is_file()
    }
    second = pf.run_ingestion_preflight(
        **dict(kwargs, run_created_at="2026-07-28T02:00:00+00:00")
    )
    assert second.run_id != first.run_id
    after = {
        p.relative_to(first.run_root).as_posix(): p.read_bytes()
        for p in first.run_root.rglob("*")
        if p.is_file()
    }
    assert after == snapshot


def test_identical_inputs_refuse_a_duplicate_run(tmp_path: Path) -> None:
    kwargs = preflight_kwargs(tmp_path)
    pf.run_ingestion_preflight(**kwargs)
    with pytest.raises(IngestionError) as excinfo:
        pf.run_ingestion_preflight(**kwargs)
    assert excinfo.value.reason_code in {"staging_root_exists", "run_root_exists"}


def test_staging_and_destination_share_a_filesystem(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    runs_root.mkdir()
    staging = staging_root_for(runs_root, RUN_ID)
    final = run_root_for(runs_root, RUN_ID)
    assert staging.parent == final.parent
    assert os.stat(runs_root).st_dev == os.stat(tmp_path).st_dev
