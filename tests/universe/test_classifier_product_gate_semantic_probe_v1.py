"""Fixture-first coverage for the V10 23-filing semantic product-gate probe."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products import classifier_product_gate_semantic_probe_selection as selection_module
from dynamic_ai_products import lineage_classifier_product_gate_semantic_probe_v1 as probe
from dynamic_ai_products.universe.lineage_screen import ScreenInputError

sys.path.insert(0, str(Path(__file__).parent))

from test_classifier_calibration_selection import (  # noqa: E402
    CLOCK,
    ROOT,
    cohort as cohort,  # noqa: F401
    packet_cohort as packet_cohort,  # noqa: F401
    release as release,  # noqa: F401
)
from test_classifier_pilot_v1_run import _PilotFactory, _grant  # noqa: E402
from test_classifier_product_gate_batch_plan import _coverage_from_candidate_cohort  # noqa: E402


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _axes() -> str:
    return json.dumps({
        "customer_facing_digital_product": "NO",
        "software_centrality": "UNKNOWN",
        "confidence": "high",
        "passage_refs": ["P001"],
    })


@pytest.fixture
def semantic_selection(cohort, packet_cohort, tmp_path, monkeypatch):
    coverage, coverage_sha, rows = _coverage_from_candidate_cohort(
        tmp_path, cohort, count=23)
    chosen = tuple((row["cik"], row["accession"]) for row in rows)
    monkeypatch.setattr(selection_module, "SEMANTIC_PROBE_ROWS", chosen)
    target = tmp_path / selection_module.SEMANTIC_PROBE_SELECTION_FILENAME
    payload = selection_module.build_product_gate_semantic_probe_selection(
        repo_root=ROOT,
        cohort_manifest_path=cohort.path,
        cohort_manifest_sha256=cohort.sha256,
        coverage_manifest_path=coverage,
        coverage_manifest_sha256=coverage_sha,
        packet_manifest_path=packet_cohort.manifest_path,
        output_path=target,
        selection_id="semantic-probe-selection-fixture",
        clock=CLOCK,
    )
    return SimpleNamespace(
        path=target,
        sha256=_sha(target.read_bytes()),
        payload=payload,
        rows=rows,
        coverage=coverage,
        coverage_sha=coverage_sha,
    )


def _semantic_grant(cohort, selection, tmp_path):
    base = _grant(cohort, selection, tmp_path, name="semantic-probe-governance")
    authorization = {
        **base.authorization,
        "authorization_contract": probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.authorization_contract,
        "authorization_id": "semantic-probe-fixture",
        "run_kind": probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.run_kind,
        "output_contract": probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.record_contract,
        "output_axes_contract": probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.axes_contract,
        "prompt_template_path": probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.prompt_path,
        "prompt_template_sha256": _sha((ROOT / probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.prompt_path).read_bytes()),
        "selection_artifact_path": str(selection.path),
        "selection_artifact_sha256": selection.sha256,
        "selection_kind": selection_module.SEMANTIC_PROBE_SELECTION_KIND,
        "coverage_cohort_id": selection.payload["coverage_cohort_id"],
        "coverage_cohort_manifest_sha256": selection.coverage_sha,
        "coverage_cohort_records_sha256": selection.payload["coverage_cohort_records_sha256"],
    }
    raw = (json.dumps(authorization, indent=2, sort_keys=True) + "\n").encode()
    reference = "semantic_probe_authorization.json"
    (base.root / reference).write_bytes(raw)
    return SimpleNamespace(root=base.root, reference=reference, sha256=_sha(raw))


def test_v10_adds_one_general_purchase_object_test_and_keeps_v9_unchanged() -> None:
    v10 = (ROOT / probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.prompt_path).read_text()
    v9 = (ROOT / "prompts/discovery/software_universe_classifier_pilot.v9.md").read_text()
    compact = " ".join(v10.split())
    assert "Apply a strict purchase-object test before returning `YES`" in v10
    assert "what the external customer is contracting to obtain" in compact
    assert "do not by themselves establish a software product" in compact
    assert "purchase-object test" not in v9


def test_semantic_selection_is_exactly_23_rows_and_refuses_reordering(semantic_selection, monkeypatch):
    assert semantic_selection.payload["counts"] == {"selected_rows": 23}
    assert selection_module.require_product_gate_semantic_probe_selection(
        semantic_selection.path, expected_sha256=semantic_selection.sha256, repo_root=ROOT,
    ) == semantic_selection.payload
    monkeypatch.setattr(selection_module, "SEMANTIC_PROBE_ROWS", tuple(reversed(selection_module.SEMANTIC_PROBE_ROWS)))
    with pytest.raises(ScreenInputError, match="different filing set or order"):
        selection_module.require_product_gate_semantic_probe_selection(
            semantic_selection.path, expected_sha256=semantic_selection.sha256, repo_root=ROOT,
        )


def test_semantic_probe_contracts_pin_v10_and_exact_caps() -> None:
    for schema_path in (
        selection_module.SEMANTIC_PROBE_SELECTION_SCHEMA,
        probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.authorization_schema,
        probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.manifest_schema,
    ):
        Draft202012Validator.check_schema(json.loads((ROOT / schema_path).read_text()))
    auth = json.loads((ROOT / probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.authorization_schema).read_text())
    assert auth["properties"]["logical_row_cap"]["const"] == 23
    assert auth["properties"]["count_attempt_cap"]["const"] == 69
    assert auth["properties"]["prompt_template_path"]["const"] == probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.prompt_path


def test_semantic_probe_dry_run_builds_no_provider_or_output(
        cohort, packet_cohort, semantic_selection, tmp_path):
    grant = _semantic_grant(cohort, semantic_selection, tmp_path)
    result = probe.run_product_gate_semantic_probe_v1(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        coverage_manifest_path=semantic_selection.coverage,
        packet_manifest_path=packet_cohort.manifest_path,
        selection_path=semantic_selection.path, governance_root=grant.root,
        authorization_reference=grant.reference, authorization_sha256=grant.sha256,
        output_dir=tmp_path / "semantic-probe-output", run_id="semantic-probe-fixture",
        clock=CLOCK, dry_run=True,
        client_factory=lambda **_kwargs: pytest.fail("dry run constructed a provider"),
    )
    assert result.status == "dry_run" and result.run_dir is None
    assert result.request_accounting == {
        "selected_rows": 23, "model_called_rows": 23, "logical_row_cap": 23,
        "count_attempt_cap": 69, "provider_attempt_cap": 115,
        "external_request_cap": 184,
    }


def test_semantic_probe_fixture_run_preserves_23_rows_and_v10(
        cohort, packet_cohort, semantic_selection, tmp_path):
    grant = _semantic_grant(cohort, semantic_selection, tmp_path)
    events: list[tuple] = []
    factory = _PilotFactory(
        {row["cik"]: {"text": _axes()} for row in semantic_selection.rows}, events)
    result = probe.run_product_gate_semantic_probe_v1(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        coverage_manifest_path=semantic_selection.coverage,
        packet_manifest_path=packet_cohort.manifest_path,
        selection_path=semantic_selection.path, governance_root=grant.root,
        authorization_reference=grant.reference, authorization_sha256=grant.sha256,
        output_dir=tmp_path / "semantic-probe-output", run_id="semantic-probe-fixture-live",
        clock=CLOCK, client_factory=factory, sleep=lambda seconds: events.append(("sleep", seconds)),
    )
    assert result.status == "completed"
    manifest = json.loads((result.run_dir / probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.manifest_filename).read_text())
    assert manifest["counts"]["selected_rows"] == manifest["counts"]["classified"] == 23
    assert manifest["prompt_template_path"] == probe.PRODUCT_GATE_SEMANTIC_PROBE_V1_ROUTE.prompt_path
    assert all(manifest["reconciliation"].values())
