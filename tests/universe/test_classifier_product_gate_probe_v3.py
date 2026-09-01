"""Fixture-first coverage for the five-filing software-product wording probe."""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_product_gate_probe_selection as selection_module
from dynamic_ai_products import lineage_classifier_product_gate_probe_v3 as probe
from dynamic_ai_products.universe.lineage_screen import ScreenInputError

sys.path.insert(0, str(Path(__file__).parent))

from test_classifier_calibration_selection import (  # noqa: E402
    CLOCK,
    ROOT,
    cohort as cohort,  # noqa: F401
    packet_cohort as packet_cohort,  # noqa: F401
    release as release,  # noqa: F401
)
from test_classifier_pilot_v1_run import (  # noqa: E402
    _PilotFactory,
    _grant,
)
from test_classifier_product_gate_batch_plan import _coverage_from_candidate_cohort  # noqa: E402


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _axes(*, product: str = "YES", centrality: str = "CORE") -> str:
    return json.dumps({
        "customer_facing_digital_product": product,
        "software_centrality": centrality,
        "confidence": "high",
        "passage_refs": ["P001"],
    })


@pytest.fixture
def probe_selection(cohort, packet_cohort, tmp_path, monkeypatch):
    coverage, coverage_sha, rows = _coverage_from_candidate_cohort(
        tmp_path, cohort, count=5)
    chosen = tuple((row["cik"], row["accession"]) for row in rows)
    monkeypatch.setattr(selection_module, "PROBE_ROWS", chosen)
    target = tmp_path / selection_module.PROBE_SELECTION_FILENAME
    payload = selection_module.build_product_gate_probe_selection(
        repo_root=ROOT,
        cohort_manifest_path=cohort.path,
        cohort_manifest_sha256=cohort.sha256,
        coverage_manifest_path=coverage,
        coverage_manifest_sha256=coverage_sha,
        packet_manifest_path=packet_cohort.manifest_path,
        output_path=target,
        selection_id="probe-selection-fixture",
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


def _probe_grant(cohort, selection, tmp_path):
    base = _grant(cohort, selection, tmp_path, name="probe-governance")
    authorization = {
        **base.authorization,
        "authorization_contract": probe.PRODUCT_GATE_PROBE_V3_ROUTE.authorization_contract,
        "authorization_id": "product-gate-probe-fixture",
        "run_kind": probe.PRODUCT_GATE_PROBE_V3_ROUTE.run_kind,
        "output_contract": probe.PRODUCT_GATE_PROBE_V3_ROUTE.record_contract,
        "output_axes_contract": probe.PRODUCT_GATE_PROBE_V3_ROUTE.axes_contract,
        "prompt_template_path": probe.PRODUCT_GATE_PROBE_V3_ROUTE.prompt_path,
        "prompt_template_sha256": _sha((ROOT / probe.PRODUCT_GATE_PROBE_V3_ROUTE.prompt_path).read_bytes()),
        "selection_artifact_path": str(selection.path),
        "selection_artifact_sha256": selection.sha256,
        "selection_kind": selection_module.PROBE_SELECTION_KIND,
        "coverage_cohort_id": selection.payload["coverage_cohort_id"],
        "coverage_cohort_manifest_sha256": selection.coverage_sha,
        "coverage_cohort_records_sha256": selection.payload["coverage_cohort_records_sha256"],
    }
    raw = (json.dumps(authorization, indent=2, sort_keys=True) + "\n").encode()
    reference = "probe_authorization.json"
    (base.root / reference).write_bytes(raw)
    return SimpleNamespace(root=base.root, reference=reference, sha256=_sha(raw), authorization=authorization)


def test_prompt_removes_financial_categories_and_closes_core_on_software_itself() -> None:
    text = (ROOT / probe.PRODUCT_GATE_PROBE_V3_ROUTE.prompt_path).read_text()
    compact = " ".join(text.split())
    assert "separately identifiable software product or software platform" in compact
    assert "obtains the software functionality itself" in compact
    assert "customers a separately identifiable digital or software product" not in compact
    assert "obtains the digital functionality itself" not in compact
    assert "A financial product, payment service, account, loan, card, brokerage," not in text
    assert "customers principally acquire the software product or software platform itself" in compact
    assert "merely because software delivers, enables, accompanies, or improves" in compact
    assert "digital or software product" not in compact
    assert "A financial product, payment service, account, loan, card, brokerage," in (
        ROOT / "prompts/discovery/software_universe_classifier_pilot.v8.md"
    ).read_text()


def test_selection_is_exactly_the_committed_five_rows(probe_selection) -> None:
    assert probe_selection.payload["counts"] == {"selected_rows": 5}
    assert selection_module.require_product_gate_probe_selection(
        probe_selection.path, expected_sha256=probe_selection.sha256, repo_root=ROOT
    ) == probe_selection.payload


def test_selection_refuses_a_different_row_order(probe_selection, monkeypatch) -> None:
    monkeypatch.setattr(selection_module, "PROBE_ROWS", tuple(reversed(selection_module.PROBE_ROWS)))
    with pytest.raises(ScreenInputError, match="different filing set or order"):
        selection_module.require_product_gate_probe_selection(
            probe_selection.path, expected_sha256=probe_selection.sha256, repo_root=ROOT)


def test_probe_contracts_are_well_formed_and_pin_only_the_new_prompt() -> None:
    for schema_path in (
        selection_module.PROBE_SELECTION_SCHEMA,
        probe.PRODUCT_GATE_PROBE_V3_ROUTE.authorization_schema,
        probe.PRODUCT_GATE_PROBE_V3_ROUTE.manifest_schema,
    ):
        schema = json.loads((ROOT / schema_path).read_text())
        Draft202012Validator.check_schema(schema)
    auth = json.loads((ROOT / probe.PRODUCT_GATE_PROBE_V3_ROUTE.authorization_schema).read_text())
    manifest = json.loads((ROOT / probe.PRODUCT_GATE_PROBE_V3_ROUTE.manifest_schema).read_text())
    assert auth["properties"]["logical_row_cap"]["const"] == 5
    assert auth["properties"]["prompt_template_path"]["const"] == probe.PRODUCT_GATE_PROBE_V3_ROUTE.prompt_path
    assert manifest["properties"]["prompt_template_path"]["const"] == probe.PRODUCT_GATE_PROBE_V3_ROUTE.prompt_path


def test_probe_dry_run_uses_no_provider_and_writes_nothing(
        cohort, packet_cohort, probe_selection, tmp_path):
    grant = _probe_grant(cohort, probe_selection, tmp_path)
    result = probe.run_product_gate_probe_v3(
        repo_root=ROOT,
        cohort_manifest_path=cohort.path,
        coverage_manifest_path=probe_selection.coverage,
        packet_manifest_path=packet_cohort.manifest_path,
        selection_path=probe_selection.path,
        governance_root=grant.root,
        authorization_reference=grant.reference,
        authorization_sha256=grant.sha256,
        output_dir=tmp_path / "probe-output",
        run_id="product-gate-probe-fixture",
        clock=CLOCK,
        dry_run=True,
        client_factory=lambda **_kwargs: pytest.fail("dry run constructed a provider"),
    )
    assert result.status == "dry_run" and result.run_dir is None
    assert result.request_accounting == {
        "selected_rows": 5, "model_called_rows": 5, "logical_row_cap": 5,
        "count_attempt_cap": 15, "provider_attempt_cap": 25,
        "external_request_cap": 40,
    }
    assert not (tmp_path / "probe-output").exists()


def test_probe_fixture_run_preserves_five_rows_and_records_the_new_prompt(
        cohort, packet_cohort, probe_selection, tmp_path):
    grant = _probe_grant(cohort, probe_selection, tmp_path)
    script = {
        row["cik"]: {"text": _axes(product="NO", centrality="UNKNOWN")}
        for row in probe_selection.rows
    }
    events: list[tuple] = []
    factory = _PilotFactory(script, events)
    result = probe.run_product_gate_probe_v3(
        repo_root=ROOT,
        cohort_manifest_path=cohort.path,
        coverage_manifest_path=probe_selection.coverage,
        packet_manifest_path=packet_cohort.manifest_path,
        selection_path=probe_selection.path,
        governance_root=grant.root,
        authorization_reference=grant.reference,
        authorization_sha256=grant.sha256,
        output_dir=tmp_path / "probe-output",
        run_id="product-gate-probe-fixture-live",
        clock=CLOCK,
        client_factory=factory,
        sleep=lambda seconds: events.append(("sleep", seconds)),
    )
    assert result.status == "completed"
    manifest = json.loads((result.run_dir / probe.PRODUCT_GATE_PROBE_V3_ROUTE.manifest_filename).read_text())
    assert manifest["counts"]["selected_rows"] == manifest["counts"]["classified"] == 5
    assert manifest["prompt_template_path"] == probe.PRODUCT_GATE_PROBE_V3_ROUTE.prompt_path
    assert all(manifest["reconciliation"].values())
