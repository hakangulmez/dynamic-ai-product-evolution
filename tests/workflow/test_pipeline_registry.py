from pathlib import Path

from dynamic_ai_products.workflow import load_stage_registry, validate_stage_registry


def test_pipeline_registry_is_complete_and_ordered() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = load_stage_registry(root)
    assert validate_stage_registry(root, registry) == []
    ids = [stage["id"] for stage in registry["stages"]]
    assert ids == [f"{index:02d}" for index in range(15)]


def test_unimplemented_stages_stay_stub() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = load_stage_registry(root)
    statuses = {stage["id"]: stage["status"] for stage in registry["stages"]}
    # Stage 00 has a local fixture sentinel; every other stage remains a stub.
    assert statuses["00"] == "sentinel"
    assert all(status == "stub" for stage_id, status in statuses.items() if stage_id != "00")
