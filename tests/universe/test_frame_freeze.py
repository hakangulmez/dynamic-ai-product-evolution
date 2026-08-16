"""FRAME_v1 freeze-record guard tests (ADR-087) — fully offline.

The freeze record designates the released frame artifact by pinning its run
identity, manifest hash, output hashes, final counts, and the gate-passing
validation evidence. Every assertion here runs against the committed record;
nothing requires ``data/runs`` (one read-only verification test skips when
the local run artifacts are absent), no network exists, and no model is
called.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dynamic_ai_products.universe.frame import FRAME_VERSION_ON_ACQUIRED_BUILD
from dynamic_ai_products.universe.io_utils import read_json, sha256_file

ROOT = Path(__file__).resolve().parents[2]
FREEZE_PATH = ROOT / "configs" / "frame_v1_freeze.json"
PROJECT_CONFIG = ROOT / "configs" / "project.yaml"
FREEZE = read_json(FREEZE_PATH)

EMPTY_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


def test_freeze_record_declares_contract_and_version():
    assert FREEZE["freeze_contract"] == "frame_v1_freeze@0.1.0"
    assert FREEZE["frozen_version"] == "FRAME_v1"
    assert FREEZE["adr_reference"] == "ADR-087"


def test_freeze_pins_frame_artifact_identity_and_hashes():
    artifact = FREEZE["frame_artifact"]
    assert artifact["run_id"] == "frame-live-full-v11-2020q1-2026q2-20260815"
    assert artifact["manifest_path"] == (
        "data/runs/frame-full/frame-live-full-v11-2020q1-2026q2-20260815/"
        "filer_frame_manifest.json"
    )
    assert artifact["manifest_sha256"] == (
        "5203660fe4c6093041383284ad36614a5ac4d7116a1e1259138e14ebde164cee"
    )
    assert artifact["code_revision"] == (
        "215557d0d0bfecc008c110665845c2c42724f843"
    )
    assert artifact["project_config_hash"] == (
        "efc1b4a4ce05e9d9be125073f72958198e998938a8d9ae10fe8754aa1a4fbc3e"
    )
    assert artifact["output_sha256"] == {
        "historical_annual_filers.jsonl":
            "0c11153c59570fa4056a37bdbe81c5033fe1ea12a7d4197fb82003329086fa57",
        "fpi_extension_filers.jsonl":
            "545aa3a1d3a67bc68887a33861721daf35fb049062ba39de02eff5fca699d4b0",
        "amendment_links.jsonl":
            "3a97d3eddd4dced3a27f24537778da8cf65fe88beb8d0bd67866f11a526391e1",
        "frame_parse_failures.jsonl": EMPTY_SHA256,
        "frame_duplicates.jsonl": EMPTY_SHA256,
        "frame_integrity_failures.jsonl":
            "591a5403419f89e47dd4e85e8ba46094f8cd93e64b44879cc0e62ba16d316cc2",
    }


def test_freeze_pins_final_frame_counts():
    counts = FREEZE["frame_artifact"]["counts"]
    assert counts == {
        "index_files": 26,
        "data_lines": 7694062,
        "parsed_rows": 7694062,
        "parse_failures": 0,
        "integrity_failure_rows": 510,
        "duplicate_rows": 0,
        "admitted_rows": 7693552,
        "domestic_annual_records": 48793,
        "fpi_extension_records": 7478,
        "amendment_links": 6795,
        "amendment_links_with_candidate": 6692,
        "amendment_links_unmatched": 103,
        "out_of_scope_form_rows": 7630486,
        "out_of_window_rows": 0,
    }
    # The validation denominator is exactly the two frame strata combined.
    assert (
        counts["domestic_annual_records"] + counts["fpi_extension_records"]
        == FREEZE["validation_evidence"]["annual_frame_records"]
    )
    assert (
        counts["amendment_links_with_candidate"]
        + counts["amendment_links_unmatched"]
        == counts["amendment_links"]
    )


def test_freeze_cites_gate_passing_validation():
    evidence = FREEZE["validation_evidence"]
    assert evidence["run_id"] == (
        "frame-dera-validation-full-v11-2020q1-2026q1-adr086-20260816"
    )
    assert evidence["manifest_sha256"] == (
        "6154fe43f6a2577f2f3bdee2736c0b45299947568ed46f0b80c9d4965899af48"
    )
    assert evidence["gate_status"] == "pass"
    assert evidence["failed_conditions"] == []
    assert evidence["annual_dera_only_unexplained"] == 0
    assert evidence["amendment_dera_only_unexplained"] == 0
    assert evidence["annual_identity_mismatch"] == 0
    assert evidence["annual_identity_adjudicated"] == 2
    assert evidence["annual_dera_only_adjudicated"] == 3
    assert evidence["adjudications_file_sha256"] == (
        "6140782601f374f68ecad7e8ca9e234cec6ab76a9f37aadcd139ef166b8af199"
    )
    assert evidence["adjudication_records"] == 5
    assert evidence["adjudications_applied"] == 5
    assert evidence["reconciliation_identities_all_true"] is True
    assert evidence["dera_observed_through"] == "2026-03-31"
    assert evidence["annual_right_boundary_unobserved"] == 1169


def test_freeze_cites_the_committed_adjudication_file_exactly():
    # The freeze pins the adjudication evidence by content hash; the committed
    # file must still be that content.
    adjudications = ROOT / "configs" / "dera_validation_adjudications.json"
    assert sha256_file(adjudications) == (
        FREEZE["validation_evidence"]["adjudications_file_sha256"]
    )
    assert len(read_json(adjudications)["records"]) == (
        FREEZE["validation_evidence"]["adjudication_records"]
    )


def test_freeze_window_and_forms_match_w0_project_config():
    artifact = FREEZE["frame_artifact"]
    universe = yaml.safe_load(PROJECT_CONFIG.read_text(encoding="utf-8"))[
        "universe"
    ]
    assert artifact["filing_window_start"] == str(
        universe["filing_window_start"]
    )
    assert artifact["filing_window_end"] == str(universe["filing_window_end"])
    assert artifact["domestic_forms"] == universe["domestic_form_scope"]
    assert artifact["extension_forms"] == (
        universe["foreign_private_issuer_extension_forms"]
    )


def test_freeze_build_label_matches_code_owned_constant():
    # The released name maps onto the draft build label; the code constant
    # keeps labelling future builds as drafts until a successor freeze.
    assert (
        FREEZE["frame_artifact"]["frame_version_on_build"]
        == FRAME_VERSION_ON_ACQUIRED_BUILD
        == "FRAME_v1.1-draft"
    )
    assert FREEZE["frozen_version"] != FRAME_VERSION_ON_ACQUIRED_BUILD


_FRAME_MANIFEST = ROOT / FREEZE["frame_artifact"]["manifest_path"]
_VALIDATION_MANIFEST = ROOT / FREEZE["validation_evidence"]["manifest_path"]


@pytest.mark.skipif(
    not (_FRAME_MANIFEST.exists() and _VALIDATION_MANIFEST.exists()),
    reason="local data/runs artifacts absent; freeze hashes not recomputable",
)
def test_local_run_artifacts_match_freeze_record_when_present():
    # Read-only: recompute both manifest hashes from the immutable run
    # directories and compare against the pinned values.
    assert sha256_file(_FRAME_MANIFEST) == (
        FREEZE["frame_artifact"]["manifest_sha256"]
    )
    assert sha256_file(_VALIDATION_MANIFEST) == (
        FREEZE["validation_evidence"]["manifest_sha256"]
    )
