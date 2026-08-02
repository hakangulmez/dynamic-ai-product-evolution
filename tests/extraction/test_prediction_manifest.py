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
    REQUIRED_SOURCE_ARTIFACT_ROLES_V2,
    build_prediction_artifact_manifest_v2,
    build_prediction_artifact_manifest,
    manifest_bytes,
)

SOURCE_ARTIFACTS = {
    "raw_prediction": {"reference": "predictions/raw_prediction.json", "sha256": "1" * 64},
    "extraction_input_packet": {
        "reference": "inputs/extraction_input_packet.json",
        "sha256": "2" * 64,
    },
    "rendered_provider_contents": {
        "reference": "inputs/rendered_provider_contents.md",
        "sha256": "a" * 64,
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


def test_eight_roles_are_required():
    """E-R adds the rendered provider contents as the eighth role (ADR-036).

    The released model's ``source_artifacts`` is an unbounded tuple, so this
    does not widen ``prediction_artifact_manifest@0.1.0``.
    """
    assert REQUIRED_SOURCE_ARTIFACT_ROLES == (
        "raw_prediction",
        "extraction_input_packet",
        "rendered_provider_contents",
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
    assert "inputs/rendered_provider_contents.md" in references
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
    assert len(entries) == 8


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


# --- ADR-043 (E-M): the ten-role successor -----------------------------------


def test_the_v1_role_tuple_is_untouched_by_the_e_m_increment():
    """Changing it would have altered every manifest the released route emits."""
    assert len(REQUIRED_SOURCE_ARTIFACT_ROLES) == 8
    assert REQUIRED_SOURCE_ARTIFACT_ROLES[0] == "raw_prediction"
    assert "count_tokens_raw_response" not in REQUIRED_SOURCE_ARTIFACT_ROLES
    assert "extraction_execution_outcome" not in REQUIRED_SOURCE_ARTIFACT_ROLES


def test_the_v2_role_tuple_extends_it_by_exactly_two():
    assert REQUIRED_SOURCE_ARTIFACT_ROLES_V2[:8] == REQUIRED_SOURCE_ARTIFACT_ROLES
    assert REQUIRED_SOURCE_ARTIFACT_ROLES_V2[8:] == (
        "count_tokens_raw_response",
        "extraction_execution_outcome",
    )
    assert len(REQUIRED_SOURCE_ARTIFACT_ROLES_V2) == 10


def test_the_v2_builder_pins_all_ten_roles():
    manifest = build_prediction_artifact_manifest_v2(
        prediction_run_id="run-1",
        envelopes_reference="predictions/prediction_envelopes.jsonl",
        envelopes_sha256="a" * 64,
        record_count=1,
        source_artifacts={
            role: {"reference": f"x/{role}", "sha256": "b" * 64}
            for role in REQUIRED_SOURCE_ARTIFACT_ROLES_V2
        },
    )
    assert len(manifest["source_artifacts"]) == 10
    assert manifest["contract"] == dict(PREDICTION_MANIFEST_CONTRACT)


def test_the_two_builders_do_not_accept_each_other_s_role_sets():
    """A shared, configurable role set would let one route's requirement quietly
    become the other's."""
    v1_only = {
        role: {"reference": role, "sha256": "b" * 64}
        for role in REQUIRED_SOURCE_ARTIFACT_ROLES
    }
    with pytest.raises(ExtractionError) as caught:
        build_prediction_artifact_manifest_v2(
            prediction_run_id="r",
            envelopes_reference="e",
            envelopes_sha256="a" * 64,
            record_count=1,
            source_artifacts=v1_only,
        )
    assert caught.value.reason_code == "source_artifact_missing"

    v2_all = {
        role: {"reference": role, "sha256": "b" * 64}
        for role in REQUIRED_SOURCE_ARTIFACT_ROLES_V2
    }
    with pytest.raises(ExtractionError) as caught:
        build_prediction_artifact_manifest(
            prediction_run_id="r",
            envelopes_reference="e",
            envelopes_sha256="a" * 64,
            record_count=1,
            source_artifacts=v2_all,
        )
    assert caught.value.reason_code == "source_artifact_unknown"


def test_generation_attempt_bodies_are_deliberately_not_roles():
    """A role is a 1:1 pin and a run holds zero to three attempt bodies. They are
    pinned by the execution outcome's per-attempt entries instead, and the outcome
    is itself a role -- so they stay reachable by hash, transitively."""
    assert not any("attempt" in role for role in REQUIRED_SOURCE_ARTIFACT_ROLES_V2)
