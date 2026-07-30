"""The single harness-visible prediction root (ADR-033).

``prediction_artifact_manifest@0.1.0`` pins six source artifacts, so all
provider provenance — including the provider-client contract that
``extraction_run@0.1.0`` has no field for — is reachable by hash from one root.
"""

from __future__ import annotations

import pytest

from dynamic_ai_products.evaluation.envelopes import PredictionArtifactManifest
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.prediction_manifest import (
    PREDICTION_MANIFEST_CONTRACT,
    REQUIRED_SOURCE_ARTIFACT_ROLES,
    build_prediction_artifact_manifest,
    manifest_bytes,
)

SOURCE_ARTIFACTS = {
    "raw_prediction": {"reference": "predictions/raw_prediction.json", "sha256": "1" * 64},
    "extraction_input_packet": {
        "reference": "inputs/extraction_input_packet.json",
        "sha256": "2" * 64,
    },
    "coverage_artifact": {
        "reference": "coverage/source_family_coverage.json",
        "sha256": "3" * 64,
    },
    "resolved_prompt": {"reference": "inputs/resolved_prompt.md", "sha256": "4" * 64},
    "provider_client_contract": {
        "reference": "inputs/provider_client_contract.json",
        "sha256": "5" * 64,
    },
    "live_call_authorization": {
        "reference": "inputs/live_call_authorization.json",
        "sha256": "6" * 64,
    },
    "extraction_run": {"reference": "manifests/extraction_run.json", "sha256": "7" * 64},
}


def _manifest(**overrides):
    kwargs = {
        "prediction_run_id": "pred-0001",
        "envelopes_reference": "predictions/prediction_envelopes.jsonl",
        "envelopes_sha256": "8" * 64,
        "record_count": 1,
        "source_artifacts": {k: dict(v) for k, v in SOURCE_ARTIFACTS.items()},
    }
    kwargs.update(overrides)
    return build_prediction_artifact_manifest(**kwargs)


def test_seven_roles_are_required():
    """E-L adds the live-call authorization as the seventh role (ADR-035).

    The released model's ``source_artifacts`` is an unbounded tuple, so this
    does not widen ``prediction_artifact_manifest@0.1.0``.
    """
    assert REQUIRED_SOURCE_ARTIFACT_ROLES == (
        "raw_prediction",
        "extraction_input_packet",
        "coverage_artifact",
        "resolved_prompt",
        "provider_client_contract",
        "live_call_authorization",
        "extraction_run",
    )


def test_the_provider_client_contract_is_bound_here_not_in_extraction_run():
    """extraction_run@0.1.0 is strict and released; it gains no new field."""
    manifest = _manifest()
    references = {entry["reference"] for entry in manifest["source_artifacts"]}
    assert "inputs/provider_client_contract.json" in references
    assert "inputs/live_call_authorization.json" in references
    assert "manifests/extraction_run.json" in references


def test_a_built_manifest_validates_against_the_released_model():
    PredictionArtifactManifest.model_validate(_manifest())


def test_the_contract_stamp_comes_only_from_the_closed_pin():
    manifest = _manifest()
    assert manifest["contract"] == PREDICTION_MANIFEST_CONTRACT
    assert manifest["contract"] is not PREDICTION_MANIFEST_CONTRACT


def test_source_artifacts_are_emitted_in_canonical_order():
    entries = _manifest()["source_artifacts"]
    assert entries == sorted(entries, key=lambda e: (e["reference"], e["sha256"]))
    assert len(entries) == 7


@pytest.mark.parametrize("role", REQUIRED_SOURCE_ARTIFACT_ROLES)
def test_a_missing_role_fails_closed(role):
    artifacts = {k: dict(v) for k, v in SOURCE_ARTIFACTS.items()}
    artifacts.pop(role)
    with pytest.raises(ExtractionError) as excinfo:
        _manifest(source_artifacts=artifacts)
    assert excinfo.value.reason_code == "source_artifact_missing"


def test_an_undeclared_role_fails_closed():
    artifacts = {k: dict(v) for k, v in SOURCE_ARTIFACTS.items()}
    artifacts["mystery_artifact"] = {"reference": "x.json", "sha256": "9" * 64}
    with pytest.raises(ExtractionError) as excinfo:
        _manifest(source_artifacts=artifacts)
    assert excinfo.value.reason_code == "source_artifact_unknown"


def test_a_role_without_a_reference_fails_closed():
    artifacts = {k: dict(v) for k, v in SOURCE_ARTIFACTS.items()}
    artifacts["resolved_prompt"] = {"reference": "", "sha256": "4" * 64}
    with pytest.raises(ExtractionError) as excinfo:
        _manifest(source_artifacts=artifacts)
    assert excinfo.value.reason_code == "source_artifact_missing"


def test_a_role_without_a_valid_digest_fails_closed():
    artifacts = {k: dict(v) for k, v in SOURCE_ARTIFACTS.items()}
    artifacts["coverage_artifact"] = {"reference": "c.json", "sha256": "nope"}
    with pytest.raises(ExtractionError) as excinfo:
        _manifest(source_artifacts=artifacts)
    assert excinfo.value.reason_code == "pin_invalid"


def test_a_malformed_envelopes_digest_fails_closed():
    with pytest.raises(ExtractionError) as excinfo:
        _manifest(envelopes_sha256="ABCDEF")
    assert excinfo.value.reason_code == "pin_invalid"


def test_no_caller_channel_can_mint_a_contract_stamp():
    with pytest.raises(ExtractionError) as excinfo:
        _manifest(contract_metadata={"contract_hash": "f" * 64})
    assert excinfo.value.reason_code == "contract_metadata_forbidden"


def test_a_contract_key_smuggled_through_source_artifacts_is_refused():
    artifacts = {k: dict(v) for k, v in SOURCE_ARTIFACTS.items()}
    artifacts["contract"] = {"contract_hash": "f" * 64}
    with pytest.raises(ExtractionError) as excinfo:
        _manifest(source_artifacts=artifacts)
    assert excinfo.value.reason_code == "contract_metadata_forbidden"


def test_a_contract_key_smuggled_inside_one_role_is_refused():
    artifacts = {k: dict(v) for k, v in SOURCE_ARTIFACTS.items()}
    artifacts["raw_prediction"]["contract"] = {"contract_hash": "f" * 64}
    with pytest.raises(ExtractionError) as excinfo:
        _manifest(source_artifacts=artifacts)
    assert excinfo.value.reason_code == "contract_metadata_forbidden"


def test_serialization_is_deterministic():
    assert manifest_bytes(_manifest()) == manifest_bytes(_manifest())
