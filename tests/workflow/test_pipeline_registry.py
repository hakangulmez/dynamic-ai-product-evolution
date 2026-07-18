from pathlib import Path

from dynamic_ai_products.workflow import load_stage_registry, validate_stage_registry


def test_pipeline_registry_is_complete_and_ordered() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = load_stage_registry(root)
    assert validate_stage_registry(root, registry) == []
    ids = [stage["id"] for stage in registry["stages"]]
    assert ids == [f"{index:02d}" for index in range(15)]


def test_stub_is_safe_default() -> None:
    root = Path(__file__).resolve().parents[2]
    registry = load_stage_registry(root)
    assert all(stage["status"] == "stub" for stage in registry["stages"])
