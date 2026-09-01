"""V3 batch route is the V9 prompt successor for the fixed batch plan."""

from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from dynamic_ai_products.lineage_classifier_product_gate_batch_v2 import (
    PRODUCT_GATE_BATCH_V2_ROUTE,
)
from dynamic_ai_products.lineage_classifier_product_gate_batch_v3 import (
    PRODUCT_GATE_BATCH_V3_ROUTE,
)

ROOT = Path(__file__).resolve().parents[2]


def test_v3_batch_reuses_the_fixed_plan_and_changes_only_successor_identity() -> None:
    changed = {
        name
        for name in PRODUCT_GATE_BATCH_V2_ROUTE.__dataclass_fields__
        if getattr(PRODUCT_GATE_BATCH_V2_ROUTE, name)
        != getattr(PRODUCT_GATE_BATCH_V3_ROUTE, name)
    }
    assert changed == {
        "run_kind", "records_filename", "manifest_filename",
        "raw_responses_filename", "manifest_contract", "manifest_schema",
        "authorization_contract", "authorization_schema", "run_root_name",
        "prompt_path", "load_selection",
    }
    assert PRODUCT_GATE_BATCH_V3_ROUTE.selection_kind == "classifier_product_gate_batch_plan_v1"
    assert PRODUCT_GATE_BATCH_V3_ROUTE.prompt_path.endswith("software_universe_classifier_pilot.v9.md")
    assert PRODUCT_GATE_BATCH_V3_ROUTE.load_selection.__name__ == "_load_batch_plan"


def test_v3_batch_schemas_own_v9_contracts_and_output_names() -> None:
    auth = json.loads((ROOT / PRODUCT_GATE_BATCH_V3_ROUTE.authorization_schema).read_text())
    manifest = json.loads((ROOT / PRODUCT_GATE_BATCH_V3_ROUTE.manifest_schema).read_text())
    Draft202012Validator.check_schema(auth)
    Draft202012Validator.check_schema(manifest)
    assert auth["properties"]["prompt_template_path"]["const"] == PRODUCT_GATE_BATCH_V3_ROUTE.prompt_path
    assert manifest["properties"]["prompt_template_path"]["const"] == PRODUCT_GATE_BATCH_V3_ROUTE.prompt_path
    assert auth["properties"]["authorization_contract"]["const"] == PRODUCT_GATE_BATCH_V3_ROUTE.authorization_contract
    assert manifest["properties"]["manifest_contract"]["const"] == PRODUCT_GATE_BATCH_V3_ROUTE.manifest_contract
    assert set(manifest["properties"]["output_hashes"]["required"]) == {
        PRODUCT_GATE_BATCH_V3_ROUTE.records_filename,
        PRODUCT_GATE_BATCH_V3_ROUTE.raw_responses_filename,
        "universe_screen_capture_ledger.jsonl",
    }
