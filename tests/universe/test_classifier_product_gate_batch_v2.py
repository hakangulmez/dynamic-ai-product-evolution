"""V2 product-gate batch route keeps the plan but pins the V7 product gate."""

from __future__ import annotations

import inspect
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from dynamic_ai_products.lineage_classifier_product_gate_batch_v1 import PRODUCT_GATE_BATCH_ROUTE
from dynamic_ai_products.lineage_classifier_product_gate_batch_v2 import PRODUCT_GATE_BATCH_V2_ROUTE

ROOT = Path(__file__).resolve().parents[2]


def test_v2_batch_route_reuses_the_same_plan_and_only_changes_route_identity() -> None:
    changed = {name for name in PRODUCT_GATE_BATCH_ROUTE.__dataclass_fields__ if getattr(PRODUCT_GATE_BATCH_ROUTE, name) != getattr(PRODUCT_GATE_BATCH_V2_ROUTE, name)}
    assert changed == {"run_kind", "records_filename", "manifest_filename", "raw_responses_filename", "manifest_contract", "manifest_schema", "authorization_contract", "authorization_schema", "run_root_name", "prompt_path", "load_selection"}
    assert PRODUCT_GATE_BATCH_V2_ROUTE.selection_contract == PRODUCT_GATE_BATCH_ROUTE.selection_contract
    assert PRODUCT_GATE_BATCH_V2_ROUTE.selection_kind == "classifier_product_gate_batch_plan_v1"
    assert PRODUCT_GATE_BATCH_V2_ROUTE.prompt_path.endswith("software_universe_classifier_pilot.v6.md")
    assert inspect.getsource(PRODUCT_GATE_BATCH_V2_ROUTE.load_selection) == inspect.getsource(PRODUCT_GATE_BATCH_ROUTE.load_selection)


def test_v2_batch_schemas_pin_the_managed_service_prompt_and_own_contracts() -> None:
    auth = json.loads((ROOT / PRODUCT_GATE_BATCH_V2_ROUTE.authorization_schema).read_text())
    manifest = json.loads((ROOT / PRODUCT_GATE_BATCH_V2_ROUTE.manifest_schema).read_text())
    Draft202012Validator.check_schema(auth)
    Draft202012Validator.check_schema(manifest)
    assert auth["properties"]["prompt_template_path"]["const"] == PRODUCT_GATE_BATCH_V2_ROUTE.prompt_path
    assert manifest["properties"]["prompt_template_path"]["const"] == PRODUCT_GATE_BATCH_V2_ROUTE.prompt_path
    assert auth["properties"]["authorization_contract"]["const"] == PRODUCT_GATE_BATCH_V2_ROUTE.authorization_contract
    assert manifest["properties"]["manifest_contract"]["const"] == PRODUCT_GATE_BATCH_V2_ROUTE.manifest_contract
