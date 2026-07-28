"""Stage registry validation: generic Stage 01-04 graph and co_specs.

`configs/pipeline_stages.yaml` is the general future pipeline registry, not a
Pilot 0 execution profile. Pilot 0's run-root layout lives solely in
`dynamic_ai_products.ingestion.publication.RUN_ROOT_TEMPLATES` and is asserted
in the ingestion tests, where it is owned. These tests exist to keep the
generic registry generic.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dynamic_ai_products.workflow import (
    find_repo_root,
    load_stage_registry,
    stage_by_id,
    validate_stage_registry,
)

ROOT = find_repo_root(Path(__file__).resolve())

# The original generic declarations. Stage 01-04 outputs describe the future
# pipeline's flat data zones and must not encode Pilot 0 behavior.
GENERIC_OUTPUTS = {
    "01": [
        "data/registry/sec_source_candidates.parquet",
        "data/manifests/sec_discovery_manifest.json",
    ],
    "02": [
        "data/registry/official_web_candidates.parquet",
        "data/manifests/web_discovery_manifest.json",
    ],
    "03": [
        "data/snapshots/**",
        "data/manifests/snapshot_manifest.jsonl",
    ],
    "04": [
        "data/normalized/documents.parquet",
        "data/normalized/passages.parquet",
    ],
}

GENERIC_INPUTS = {
    "01": ["data/registry/companies.parquet", "docs/source_playbooks/SEC_EDGAR.md"],
    "02": ["data/registry/companies.parquet", "configs/source_types.yaml"],
    "03": [
        "data/registry/sec_source_candidates.parquet",
        "data/registry/official_web_candidates.parquet",
    ],
    "04": [
        "data/snapshots/**",
        "schemas/source_document.schema.json",
        "schemas/source_passage.schema.json",
    ],
}


def test_registry_is_valid() -> None:
    assert validate_stage_registry(ROOT) == []


def test_stage_01_to_04_outputs_are_generic() -> None:
    registry = load_stage_registry(ROOT)
    for stage_id, expected in GENERIC_OUTPUTS.items():
        assert stage_by_id(registry, stage_id)["outputs"] == expected


def test_stage_01_to_04_inputs_are_generic() -> None:
    registry = load_stage_registry(ROOT)
    for stage_id, expected in GENERIC_INPUTS.items():
        assert stage_by_id(registry, stage_id)["inputs"] == expected


def test_web_discovery_and_snapshot_outputs_are_retained() -> None:
    """Pilot 0 not exercising these must never delete them from the registry."""
    registry = load_stage_registry(ROOT)
    stage_02 = stage_by_id(registry, "02")["outputs"]
    assert "data/registry/official_web_candidates.parquet" in stage_02
    assert "data/manifests/web_discovery_manifest.json" in stage_02
    assert "data/snapshots/**" in stage_by_id(registry, "03")["outputs"]


def test_registry_carries_no_pilot_run_root_template() -> None:
    """The Pilot's run-root layout does not amend the general registry."""
    text = (ROOT / "configs" / "pipeline_stages.yaml").read_text(encoding="utf-8")
    assert "{run_id}" not in text
    assert "data/runs/" not in text
    assert "ingestion_preflight_manifest" not in text
    assert "source_family_coverage" not in text


def test_no_stage_declares_a_placeholder_output() -> None:
    registry = load_stage_registry(ROOT)
    for stage in registry["stages"]:
        for value in list(stage.get("outputs") or []) + list(stage.get("inputs") or []):
            assert "{" not in str(value) and "}" not in str(value)


def test_stage_01_to_04_statuses_remain_stub() -> None:
    registry = load_stage_registry(ROOT)
    for stage_id in GENERIC_OUTPUTS:
        assert stage_by_id(registry, stage_id)["status"] == "stub"


# --- co_specs: the retained general governance improvement --------------------


def test_stage_03_declares_sec_ingestion_co_spec() -> None:
    registry = load_stage_registry(ROOT)
    stage = stage_by_id(registry, "03")
    assert stage["co_specs"] == ["specs/SPEC-003-sec-ingestion.md"]
    assert (ROOT / stage["co_specs"][0]).exists()


def test_missing_co_spec_is_reported() -> None:
    registry = load_stage_registry(ROOT)
    stage_by_id(registry, "03")["co_specs"] = ["specs/SPEC-999-absent.md"]
    findings = validate_stage_registry(ROOT, registry)
    assert any(f["code"] == "missing_co_spec" for f in findings)
    assert all(f["severity"] == "error" for f in findings)


def test_absent_co_specs_key_is_accepted() -> None:
    registry = load_stage_registry(ROOT)
    for stage_id in ("01", "02", "04"):
        assert "co_specs" not in stage_by_id(registry, stage_id)
    assert validate_stage_registry(ROOT, registry) == []


def test_empty_or_null_co_specs_is_accepted() -> None:
    registry = load_stage_registry(ROOT)
    stage_by_id(registry, "03")["co_specs"] = []
    assert validate_stage_registry(ROOT, registry) == []
    registry = load_stage_registry(ROOT)
    stage_by_id(registry, "03")["co_specs"] = None
    assert validate_stage_registry(ROOT, registry) == []


def test_every_declared_co_spec_path_exists() -> None:
    registry = load_stage_registry(ROOT)
    for stage in registry["stages"]:
        for co_spec in stage.get("co_specs") or []:
            assert (ROOT / co_spec).exists(), co_spec


@pytest.mark.parametrize("key", ["script", "spec"])
def test_missing_required_path_is_still_reported(key: str) -> None:
    registry = load_stage_registry(ROOT)
    stage_by_id(registry, "01")[key] = "does/not/exist.md"
    findings = validate_stage_registry(ROOT, registry)
    assert any(f["code"] == f"missing_{key}" for f in findings)


def test_validator_never_stats_a_braced_path(monkeypatch) -> None:
    real_exists = Path.exists
    seen: list[str] = []

    def spy(self):  # noqa: ANN001
        seen.append(str(self))
        return real_exists(self)

    monkeypatch.setattr(Path, "exists", spy, raising=True)
    validate_stage_registry(ROOT)
    monkeypatch.undo()
    assert not [path for path in seen if "{" in path or "}" in path]
