"""Regression tests for the managed-service product-gate successor."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from dynamic_ai_products.lineage_classifier_pilot_v6 import PILOT_V6_ROUTE, run_lineage_classifier_pilot_v6
from dynamic_ai_products.lineage_classifier_pilot_v7 import PILOT_V7_ROUTE, run_lineage_classifier_pilot_v7

ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v6_prompt_adds_a_general_managed_service_exclusion() -> None:
    prompt = (ROOT / "prompts/discovery/software_universe_classifier_pilot.v6.md").read_text()
    compact = " ".join(prompt.split())
    assert "A managed service, consulting engagement, implementation, integration, outsourcing, or staff-led operation is not a digital product merely because it uses or manages software, cloud infrastructure, data, or AI." in compact
    for name in ("Kyndryl", "AMD", "U-Haul", "MongoDB", "Cloudflare"):
        assert name not in prompt


def test_v5_prompt_remains_byte_identical() -> None:
    assert _sha(ROOT / "prompts/discovery/software_universe_classifier_pilot.v5.md") == "fdcd443442b0951ca0b8adba44282baa11dd3e3c8e0324fd0d5cc80d410bd8fc"


def test_v7_isolated_route_changes_only_identity_and_prompt() -> None:
    changed = {name for name in PILOT_V6_ROUTE.__dataclass_fields__ if getattr(PILOT_V6_ROUTE, name) != getattr(PILOT_V7_ROUTE, name)}
    assert changed == {"run_kind", "records_filename", "manifest_filename", "raw_responses_filename", "manifest_contract", "manifest_schema", "authorization_contract", "authorization_schema", "run_root_name", "prompt_path", "load_selection"}
    assert inspect.getsource(PILOT_V6_ROUTE.load_selection) == inspect.getsource(PILOT_V7_ROUTE.load_selection)
    assert tuple(inspect.signature(run_lineage_classifier_pilot_v7).parameters) == tuple(inspect.signature(run_lineage_classifier_pilot_v6).parameters)


def test_v7_schemas_pin_own_contracts_and_prompt() -> None:
    auth = json.loads((ROOT / PILOT_V7_ROUTE.authorization_schema).read_text())
    manifest = json.loads((ROOT / PILOT_V7_ROUTE.manifest_schema).read_text())
    Draft202012Validator.check_schema(auth)
    Draft202012Validator.check_schema(manifest)
    assert auth["properties"]["prompt_template_path"]["const"] == PILOT_V7_ROUTE.prompt_path
    assert manifest["properties"]["prompt_template_path"]["const"] == PILOT_V7_ROUTE.prompt_path
    assert auth["properties"]["authorization_contract"]["const"] == PILOT_V7_ROUTE.authorization_contract
    assert manifest["properties"]["manifest_contract"]["const"] == PILOT_V7_ROUTE.manifest_contract
