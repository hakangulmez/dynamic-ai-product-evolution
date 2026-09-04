"""Offline contract tests for the compact combined Item 1 PCT draft."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.pct_combined_snapshot import (
    CombinedSnapshotFailure,
    OUTPUT_SCHEMA,
    OUTPUT_SCHEMA_V2,
    OUTPUT_SCHEMA_V3,
    OUTPUT_SCHEMA_V4,
    validate_combined_snapshot_output,
    validate_combined_snapshot_output_v2,
    validate_combined_snapshot_output_v3,
    validate_combined_snapshot_output_v4,
)
from dynamic_ai_products.pct_combined_snapshot_smoke import (
    SMOKE_HTML_FILENAME,
    SMOKE_MANIFEST_FILENAME,
    SMOKE_RAW_RESPONSES_FILENAME,
    SMOKE_RECORDS_FILENAME,
    SMOKE_ROWS,
    build_vertex_generator,
    build_smoke_plan,
    run_smoke_plan,
)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((ROOT / OUTPUT_SCHEMA).read_text())
VALIDATOR = Draft202012Validator(SCHEMA)
VALIDATOR_V2 = Draft202012Validator(
    json.loads((ROOT / OUTPUT_SCHEMA_V2).read_text())
)
VALIDATOR_V3 = Draft202012Validator(
    json.loads((ROOT / OUTPUT_SCHEMA_V3).read_text())
)
VALIDATOR_V4 = Draft202012Validator(
    json.loads((ROOT / OUTPUT_SCHEMA_V4).read_text())
)
PACKET = {
    "passages": [
        {"passage_id": "first", "text": "First Item 1 block."},
        {"passage_id": "second", "text": "Second Item 1 block."},
    ]
}


def _output() -> dict:
    return {
        "products": [
            {"id": "P1", "name": "Example product", "product_family": None,
             "availability_status": "general_availability", "passage_refs": ["P001"]}
        ],
        "capabilities": [
            {"id": "C1", "product_id": "P1", "text": "automate reporting",
             "availability_status": "general_availability", "passage_refs": ["P001"]}
        ],
        "tasks": [
            {"id": "T1", "product_id": "P1", "capability_ids": ["C1"],
             "text": "generate reports to monitor operations",
             "customer_need": "monitor operations using current reports",
             "availability_status": "general_availability", "passage_refs": ["P002"]}
        ],
    }


def _validate(value: dict) -> dict:
    return validate_combined_snapshot_output(json.dumps(value), PACKET, VALIDATOR)


def _output_v2() -> dict:
    return {
        "products": [{
            "id": "P1", "name": "Example product", "product_family": "Example suite",
            "availability_status": "general_availability", "passage_refs": ["P001"],
        }],
        "capabilities": [{
            "id": "C1", "product_id": "P1", "text": "automate reporting",
            "passage_refs": ["P001"],
        }],
        "task_families": [{
            "id": "TF1", "product_id": "P1", "capability_ids": ["C1"],
            "text": "monitor operations using current reports",
            "customer_outcome": "make operating decisions from current reports",
            "passage_refs": ["P002"],
        }],
    }


def _validate_v2(value: dict) -> dict:
    return validate_combined_snapshot_output_v2(json.dumps(value), PACKET, VALIDATOR_V2)


def _output_v3() -> dict:
    return {
        "product_families": [{
            "id": "F1", "name": "Example suite", "passage_refs": ["P001"],
        }],
        "products": [{
            "id": "P1", "name": "Example product", "product_family_id": "F1",
            "availability_status": "general_availability", "passage_refs": ["P001"],
        }],
        "capabilities": [{
            "id": "C1", "product_id": "P1", "text": "automate reporting",
            "passage_refs": ["P001"],
        }],
        "tasks": [{
            "id": "T1", "product_id": "P1", "capability_ids": ["C1"],
            "text": "generate reports to monitor operations",
            "customer_need": "monitor operations using current reports",
            "passage_refs": ["P002"],
        }],
    }


def _validate_v3(value: dict) -> dict:
    return validate_combined_snapshot_output_v3(json.dumps(value), PACKET, VALIDATOR_V3)


def _output_v4() -> dict:
    value = _output_v3()
    del value["tasks"]
    value["task_families"] = [{
        "id": "TF1", "product_id": "P1", "capability_ids": ["C1"],
        "text": "monitor operations using current reports",
        "customer_outcome": "make operating decisions from current reports",
        "passage_refs": ["P002"],
    }]
    return value


def _validate_v4(value: dict) -> dict:
    return validate_combined_snapshot_output_v4(json.dumps(value), PACKET, VALIDATOR_V4)


def test_valid_snapshot_uses_current_zero_padded_packet_addresses() -> None:
    assert _validate(_output()) == _output()


@pytest.mark.parametrize("reference", ["P01", "P1", "P003", "p001"])
def test_p001_rendered_route_refuses_a_different_or_absent_address(reference: str) -> None:
    value = _output()
    value["products"][0]["passage_refs"] = [reference]
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate(value)
    assert error.value.reason_code in {
        "snapshot_contract_violation", "evidence_reference_unresolvable"
    }


def test_schema_forbids_pipeline_derived_evidence_and_later_scores() -> None:
    value = _output()
    value["products"][0]["evidence_text"] = "The model must not author this."
    with pytest.raises(CombinedSnapshotFailure, match="Additional properties"):
        _validate(value)


def test_cross_entry_product_and_capability_links_must_resolve() -> None:
    value = _output()
    value["tasks"][0]["product_id"] = "P9"
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate(value)
    assert error.value.reason_code == "dangling_product_reference"

    value = _output()
    value["tasks"][0]["capability_ids"] = ["C9"]
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate(value)
    assert error.value.reason_code == "dangling_capability_reference"


def test_empty_snapshot_is_a_valid_observation() -> None:
    assert _validate({"products": [], "capabilities": [], "tasks": []}) == {
        "products": [], "capabilities": [], "tasks": []
    }


def test_v2_snapshot_accepts_optional_product_family_and_task_families() -> None:
    assert _validate_v2(_output_v2()) == _output_v2()
    value = _output_v2()
    value["products"][0]["product_family"] = None
    assert _validate_v2(value)["products"][0]["product_family"] is None


def test_v2_contract_keeps_family_context_out_of_capabilities_and_tasks() -> None:
    value = _output_v2()
    value["capabilities"][0]["availability_status"] = "general_availability"
    with pytest.raises(CombinedSnapshotFailure, match="Additional properties"):
        _validate_v2(value)
    value = _output_v2()
    value["task_families"][0]["capability_ids"] = ["C9"]
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate_v2(value)
    assert error.value.reason_code == "dangling_capability_reference"


def test_v2_task_family_cannot_link_a_capability_from_another_product() -> None:
    value = _output_v2()
    value["products"].append({
        "id": "P2", "name": "Second product", "product_family": None,
        "availability_status": "unknown", "passage_refs": ["P001"],
    })
    value["capabilities"][0]["product_id"] = "P2"
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate_v2(value)
    assert error.value.reason_code == "cross_product_capability_reference"


def test_v3_snapshot_uses_explicit_product_family_identity() -> None:
    assert _validate_v3(_output_v3()) == _output_v3()
    value = _output_v3()
    value["products"][0]["product_family_id"] = None
    assert _validate_v3(value)["products"][0]["product_family_id"] is None


def test_v3_refuses_a_dangling_product_family_reference() -> None:
    value = _output_v3()
    value["products"][0]["product_family_id"] = "F9"
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate_v3(value)
    assert error.value.reason_code == "dangling_product_family_reference"


def test_v4_combines_explicit_product_families_with_durable_task_families() -> None:
    assert _validate_v4(_output_v4()) == _output_v4()
    value = _output_v4()
    value["task_families"][0]["capability_ids"] = ["C9"]
    with pytest.raises(CombinedSnapshotFailure) as error:
        _validate_v4(value)
    assert error.value.reason_code == "dangling_capability_reference"


def _smoke_packets() -> dict[tuple[str, str], dict]:
    return {
        (cik, accession): {
            "cik": cik,
            "accession": accession,
            "packet_sha256": "a" * 64,
            "baseline_cutoff": "2022-01-01",
            "passages": [{
                "passage_id": f"packet-{cik}", "source_id": f"sec:{cik}",
                "byte_start": 10, "byte_end": 42,
                "text": f"{issuer_name} product description.",
            }],
        }
        for issuer_name, cik, accession in SMOKE_ROWS
    }


def test_smoke_dry_run_renders_all_packets_without_model_or_writes(tmp_path: Path) -> None:
    plan = build_smoke_plan(prompt_text="Return JSON.", packets_by_key=_smoke_packets())
    called = False

    def generate(_prompt: str) -> str:
        nonlocal called
        called = True
        raise AssertionError("dry run must not call a model")

    result = run_smoke_plan(
        plan=plan, packets_by_key=_smoke_packets(), output_root=tmp_path,
        run_id="pct-item1-combined-snapshot-smoke-v1-fixture", prompt_sha256="b" * 64,
        schema_sha256="c" * 64, generate=generate,
        model={"provider": "fixture", "model_label": "fixture"},
        clock=lambda: datetime(2026, 9, 2, tzinfo=timezone.utc), dry_run=True,
    )
    assert result["status"] == "dry_run"
    assert result["selected_rows"] == 5
    assert called is False
    assert list(tmp_path.iterdir()) == []


def test_smoke_archives_raw_validated_and_human_readable_outputs(tmp_path: Path) -> None:
    packets = _smoke_packets()
    plan = build_smoke_plan(prompt_text="Return JSON.", packets_by_key=packets)
    valid = _output_v4()
    valid["task_families"][0]["passage_refs"] = ["P001"]
    payload = json.dumps(valid)
    result = run_smoke_plan(
        plan=plan, packets_by_key=packets, output_root=tmp_path,
        run_id="pct-item1-combined-snapshot-smoke-v1-fixture", prompt_sha256="b" * 64,
        schema_sha256="c" * 64, generate=lambda _prompt: payload,
        model={"provider": "fixture", "model_label": "fixture"},
        clock=lambda: datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    run_dir = result["run_dir"]
    assert result["manifest"]["counts"] == {"extracted": 5, "review_uncertain": 0}
    assert {path.name for path in run_dir.iterdir()} == {
        SMOKE_RAW_RESPONSES_FILENAME, SMOKE_RECORDS_FILENAME,
        SMOKE_MANIFEST_FILENAME, SMOKE_HTML_FILENAME,
    }
    record = result["records"][0]
    assert record["resolved_evidence"][0]["passage_ref"] == "P001"
    assert record["resolved_evidence"][0]["evidence_text"] == "Adobe product description."
    assert "Resolved evidence blocks" in (run_dir / SMOKE_HTML_FILENAME).read_text()


def test_smoke_retains_invalid_but_readable_model_output_for_review(tmp_path: Path) -> None:
    packets = _smoke_packets()
    plan = build_smoke_plan(prompt_text="Return JSON.", packets_by_key=packets)
    result = run_smoke_plan(
        plan=plan, packets_by_key=packets, output_root=tmp_path,
        run_id="pct-item1-combined-snapshot-smoke-v1-invalid", prompt_sha256="b" * 64,
        schema_sha256="c" * 64, generate=lambda _prompt: "{not json}",
        model={"provider": "fixture", "model_label": "fixture"},
        clock=lambda: datetime(2026, 9, 2, tzinfo=timezone.utc),
    )
    assert result["manifest"]["counts"] == {"extracted": 0, "review_uncertain": 5}
    assert {record["review_reason_code"] for record in result["records"]} == {
        "invalid_model_json"
    }


def test_vertex_generator_uses_the_fixed_json_generation_projection() -> None:
    calls: list[dict] = []


    class Response:
        text = '{"product_families": [], "products": [], "capabilities": [], "task_families": []}'

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return Response()

    class Client:
        models = Models()

    generator = build_vertex_generator(
        vertex_project="project-fixture", client_factory=lambda **_kwargs: Client()
    )
    assert generator("rendered Item 1") == Response.text
    assert calls == [{
        "model": "gemini-2.5-flash", "contents": "rendered Item 1",
        "config": {
            "temperature": 0, "top_p": 1, "candidate_count": 1,
            "max_output_tokens": 16384, "response_mime_type": "application/json",
            "thinking_config": {"thinking_budget": 0},
        },
    }]
