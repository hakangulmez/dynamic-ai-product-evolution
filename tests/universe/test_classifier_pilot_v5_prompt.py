"""Regression tests for the stricter group-level CORE pilot successor."""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

from jsonschema import Draft202012Validator

from dynamic_ai_products.lineage_classifier_pilot_v5 import (
    PILOT_V5_ROUTE,
    run_lineage_classifier_pilot_v5,
)
from dynamic_ai_products.lineage_classifier_pilot_v6 import (
    PILOT_V6_ROUTE,
    run_lineage_classifier_pilot_v6,
)

ROOT = Path(__file__).resolve().parents[2]


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_v5_prompt_adds_one_general_group_level_core_rule() -> None:
    prompt = (ROOT / "prompts/discovery/software_universe_classifier_pilot.v5.md").read_text()
    assert "at the consolidated-firm\n  level" in prompt
    assert "firm has a software segment,\n  subsidiary, acquisition" in prompt
    assert "firm's principal commercial offering" in prompt
    assert "do not use `CORE`" in prompt
    for firm_name in ("ADP", "Ally", "Emerson", "Churchill", "Lumen"):
        assert firm_name not in prompt


def test_v5_keeps_the_product_gate_and_address_only_output() -> None:
    prompt = (ROOT / "prompts/discovery/software_universe_classifier_pilot.v5.md").read_text()
    compact = " ".join(prompt.split())
    for phrase in (
        "separately identifiable digital or software product",
        "online catalogue, customer account, online ordering or transaction",
        "Select addresses only.",
        "Do not write quotes, evidence text, explanations",
    ):
        assert phrase in compact


def test_v4_prompt_remains_byte_identical() -> None:
    assert _sha(ROOT / "prompts/discovery/software_universe_classifier_pilot.v4.md") == (
        "426b1d8199de2a6f69d1d46c484f7a06bdc6a053d6c6d0efd52ac9af7f05b7d0"
    )


def test_v6_route_changes_only_prompt_identity_and_route_contracts() -> None:
    assert PILOT_V6_ROUTE.run_kind == "classifier_pilot_v6"
    assert PILOT_V6_ROUTE.prompt_path.endswith("software_universe_classifier_pilot.v5.md")
    assert PILOT_V6_ROUTE.authorization_contract == "universe_classifier_pilot_authorization@0.6.0"
    assert PILOT_V6_ROUTE.manifest_contract == "universe_classifier_pilot_manifest@0.6.0"
    assert PILOT_V6_ROUTE.axes_contract == "universe_classifier_pilot_axes_record@0.3.0"
    assert PILOT_V6_ROUTE.record_contract == "universe_classifier_pilot_record@0.3.0"
    assert PILOT_V6_ROUTE.scope_exact_rows == 10


def test_v6_keeps_the_same_ten_filing_selection_and_execution_surface() -> None:
    """The live comparison changes prompt/route identity, not the test population."""
    changed = {
        name for name in PILOT_V5_ROUTE.__dataclass_fields__
        if getattr(PILOT_V5_ROUTE, name) != getattr(PILOT_V6_ROUTE, name)
    }
    assert changed == {
        "run_kind",
        "records_filename",
        "manifest_filename",
        "raw_responses_filename",
        "manifest_contract",
        "manifest_schema",
        "authorization_contract",
        "authorization_schema",
        "run_root_name",
        "prompt_path",
        "load_selection",
    }
    assert PILOT_V5_ROUTE.selection_contract == PILOT_V6_ROUTE.selection_contract
    assert PILOT_V5_ROUTE.selection_kind == PILOT_V6_ROUTE.selection_kind
    assert PILOT_V5_ROUTE.selection_source == PILOT_V6_ROUTE.selection_source
    assert inspect.getsource(PILOT_V5_ROUTE.load_selection) == inspect.getsource(
        PILOT_V6_ROUTE.load_selection
    )
    assert tuple(inspect.signature(run_lineage_classifier_pilot_v6).parameters) == tuple(
        inspect.signature(run_lineage_classifier_pilot_v5).parameters
    )


def test_v6_schemas_pin_the_new_prompt_and_own_contracts() -> None:
    auth = json.loads((ROOT / PILOT_V6_ROUTE.authorization_schema).read_text())
    manifest = json.loads((ROOT / PILOT_V6_ROUTE.manifest_schema).read_text())
    assert not list(Draft202012Validator.check_schema(auth) or [])
    assert not list(Draft202012Validator.check_schema(manifest) or [])
    assert auth["properties"]["prompt_template_path"]["const"] == PILOT_V6_ROUTE.prompt_path
    assert manifest["properties"]["prompt_template_path"]["const"] == PILOT_V6_ROUTE.prompt_path
    assert auth["properties"]["authorization_contract"]["const"] == PILOT_V6_ROUTE.authorization_contract
    assert manifest["properties"]["manifest_contract"]["const"] == PILOT_V6_ROUTE.manifest_contract
