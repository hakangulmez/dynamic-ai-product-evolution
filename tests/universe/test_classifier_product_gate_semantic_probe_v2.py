"""V11 isolation tests for the fixed two-test semantic probe."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products import lineage_classifier_product_gate_semantic_probe_v1 as v1
from dynamic_ai_products import lineage_classifier_product_gate_semantic_probe_v2 as v2
from dynamic_ai_products.universe.lineage_screen import ScreenInputError

sys.path.insert(0, str(Path(__file__).parent))

from test_classifier_product_gate_semantic_probe_v1 import (  # noqa: E402
    _axes,
    _semantic_grant,
    semantic_selection,
)
from test_classifier_calibration_selection import (  # noqa: E402, F401
    CLOCK,
    ROOT,
    cohort,
    packet_cohort,
    release,
)
from test_classifier_pilot_v1_run import _PilotFactory  # noqa: E402


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _v2_grant(cohort, selection, tmp_path):
    v1_grant = _semantic_grant(cohort, selection, tmp_path)
    payload = json.loads((v1_grant.root / v1_grant.reference).read_text())
    payload.update({
        "authorization_contract": v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.authorization_contract,
        "authorization_id": "semantic-probe-v2-fixture",
        "run_kind": v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.run_kind,
        "prompt_template_path": v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.prompt_path,
        "prompt_template_sha256": _sha((ROOT / v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.prompt_path).read_bytes()),
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    reference = "semantic_probe_v2_authorization.json"
    (v1_grant.root / reference).write_bytes(raw)
    return SimpleNamespace(root=v1_grant.root, reference=reference, sha256=_sha(raw))


def test_v11_requires_both_purchase_object_and_explicit_commercialization() -> None:
    text = (ROOT / v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.prompt_path).read_text()
    compact = " ".join(text.split())
    assert "Return `YES` only when both tests pass." in text
    assert "Purchase-object test" in text
    assert "Explicit-commercialization test" in text
    assert "directly establish" in compact
    assert "both required tests silently" in text


def test_v2_route_and_contracts_are_isolated_from_v1() -> None:
    assert v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.records_filename != v1.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.records_filename
    assert v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.manifest_filename != v1.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.manifest_filename
    assert v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.prompt_path != v1.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.prompt_path
    for schema_path in (v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.authorization_schema, v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.manifest_schema):
        Draft202012Validator.check_schema(json.loads((ROOT / schema_path).read_text()))
    auth = json.loads((ROOT / v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.authorization_schema).read_text())
    assert auth["properties"]["logical_row_cap"]["const"] == 23
    assert auth["properties"]["prompt_template_path"]["const"] == v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.prompt_path


def test_v2_dry_run_and_fixture_live_run(cohort, packet_cohort, semantic_selection, tmp_path):
    grant = _v2_grant(cohort, semantic_selection, tmp_path)
    common = dict(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        coverage_manifest_path=semantic_selection.coverage,
        packet_manifest_path=packet_cohort.manifest_path,
        selection_path=semantic_selection.path, governance_root=grant.root,
        authorization_reference=grant.reference, authorization_sha256=grant.sha256,
        output_dir=tmp_path / "semantic-probe-v2-output", clock=CLOCK,
    )
    dry = v2.run_product_gate_semantic_probe_v2(
        **common, run_id="semantic-probe-v2-dry", dry_run=True,
        client_factory=lambda **_kwargs: pytest.fail("dry run constructed a provider"),
    )
    assert dry.status == "dry_run" and dry.run_dir is None
    events: list[tuple] = []
    factory = _PilotFactory({row["cik"]: {"text": _axes()} for row in semantic_selection.rows}, events)
    live = v2.run_product_gate_semantic_probe_v2(
        **common, run_id="semantic-probe-v2-live", client_factory=factory,
        sleep=lambda seconds: events.append(("sleep", seconds)),
    )
    assert live.status == "completed"
    manifest = json.loads((live.run_dir / v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.manifest_filename).read_text())
    assert manifest["run_kind"] == v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.run_kind
    assert manifest["prompt_template_path"] == v2.PRODUCT_GATE_SEMANTIC_PROBE_V2_ROUTE.prompt_path
    assert all(manifest["reconciliation"].values())
    with pytest.raises(ScreenInputError, match="holds no"):
        v2.require_product_gate_semantic_probe_run_v2(live.run_dir.parent / "missing")
