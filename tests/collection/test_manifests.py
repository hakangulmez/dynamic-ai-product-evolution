"""Run identity (fourteen keys), pins, and manifest field contracts."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402
from dynamic_ai_products.collection.manifests import (  # noqa: E402
    PARENT_INGESTION_MANIFEST_SHA256,
    PILOT_INPUT_PINS,
    build_collection_identity,
    build_official_web_collection_manifest,
    build_web_collection_receipt,
    build_web_discovery_manifest,
)
from dynamic_ai_products.collection.publication import (  # noqa: E402
    RUN_ID_IDENTITY_KEYS,
    RUN_ID_PATTERN,
    derive_collection_run_id,
)
from collection_test_helpers import CODE_COMMIT, COMPANY_ID, CUTOFF, RUN_CREATED_AT  # noqa: E402

PLAN_SHA = "d" * 64


def _identity(**overrides):
    identity = build_collection_identity(
        code_commit=CODE_COMMIT,
        run_created_at=RUN_CREATED_AT,
        request_plan_sha256=PLAN_SHA,
    )
    identity.update(overrides)
    return identity


def test_identity_has_exactly_fourteen_keys() -> None:
    identity = _identity()
    assert len(RUN_ID_IDENTITY_KEYS) == 14
    assert set(identity) == set(RUN_ID_IDENTITY_KEYS)


def test_run_id_format_and_determinism() -> None:
    run_id = derive_collection_run_id(_identity())
    assert RUN_ID_PATTERN.fullmatch(run_id)
    assert run_id == derive_collection_run_id(_identity())


@pytest.mark.parametrize("key", RUN_ID_IDENTITY_KEYS)
def test_changing_any_identity_key_changes_the_run_id(key: str) -> None:
    baseline = derive_collection_run_id(_identity())
    mutated = _identity()
    if key == "contract":
        # The contract is fixed; a different contract must be refused outright.
        mutated[key] = "official_web_collection_manifest@0.2.0"
        with pytest.raises(CollectionError) as excinfo:
            derive_collection_run_id(mutated)
        assert excinfo.value.reason_code == "run_identity_invalid"
        return
    mutated[key] = mutated[key] + "x"
    assert derive_collection_run_id(mutated) != baseline


def test_missing_identity_key_is_refused() -> None:
    identity = _identity()
    identity.pop("request_plan_sha256")
    with pytest.raises(CollectionError) as excinfo:
        derive_collection_run_id(identity)
    assert excinfo.value.reason_code == "run_identity_invalid"


def test_extra_identity_key_is_refused() -> None:
    identity = _identity()
    identity["smuggled"] = "value"
    with pytest.raises(CollectionError) as excinfo:
        derive_collection_run_id(identity)
    assert excinfo.value.reason_code == "run_identity_invalid"


@pytest.mark.parametrize("key", ["code_commit", "run_created_at"])
def test_blank_injected_identity_is_refused(key: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        build_collection_identity(
            code_commit="  " if key == "code_commit" else CODE_COMMIT,
            run_created_at="  " if key == "run_created_at" else RUN_CREATED_AT,
            request_plan_sha256=PLAN_SHA,
        )
    assert excinfo.value.reason_code == "run_identity_invalid"


def test_identity_carries_the_parent_and_five_pilot_pins() -> None:
    identity = _identity()
    assert identity["parent_ingestion_manifest_sha256"] == PARENT_INGESTION_MANIFEST_SHA256
    for key, value in PILOT_INPUT_PINS.items():
        assert identity[key] == value
    assert len(PILOT_INPUT_PINS) == 5


def test_missing_pilot_pin_is_refused() -> None:
    with pytest.raises(CollectionError) as excinfo:
        build_collection_identity(
            code_commit=CODE_COMMIT,
            run_created_at=RUN_CREATED_AT,
            request_plan_sha256=PLAN_SHA,
            pilot_input_pins={"packet_sha256": "a" * 64},
        )
    assert excinfo.value.reason_code == "run_identity_invalid"


# --- Manifest field contracts -------------------------------------------------


def test_discovery_manifest_conforms_and_asserts_no_model() -> None:
    manifest = build_web_discovery_manifest(
        code_commit=CODE_COMMIT,
        run_created_at=RUN_CREATED_AT,
        company_id=COMPANY_ID,
        observation_cutoff_date=CUTOFF,
        candidate_count=3,
        request_plan_sha256=PLAN_SHA,
    )
    schema = json.loads(
        Path("schemas/web_discovery_manifest.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)
    assert manifest["prompt_hash"] is None
    assert manifest["model_route"] is None
    assert manifest["discovery_mode"] == "request_plan_only"


def test_receipt_separates_the_three_request_classes() -> None:
    receipt = build_web_collection_receipt(
        code_commit=CODE_COMMIT,
        run_created_at=RUN_CREATED_AT,
        company_id=COMPANY_ID,
        request_plan_sha256=PLAN_SHA,
        initial_requests=[
            {
                "requested_url": "https://ir.hubspot.com/x",
                "final_url": "https://ir.hubspot.com/x",
                "redirect_hops": [{"url": "https://ir.hubspot.com/x", "status_code": 301}],
                "http_status": 200,
                "retry_count": 0,
                "retrieval_timestamp": "2026-07-28T12:00:00+00:00",
            }
        ],
        robots_requests=[
            {
                "requested_url": "https://ir.hubspot.com/robots.txt",
                "final_url": "https://ir.hubspot.com/robots.txt",
                "http_status": 200,
                "retrieval_timestamp": "2026-07-28T12:00:00+00:00",
                "robots_decision": "allowed",
            }
        ],
    )
    schema = json.loads(
        Path("schemas/web_collection_receipt.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(receipt)
    assert receipt["request_plan_sha256"] == PLAN_SHA
    assert len(receipt["initial_requests"]) == 1
    assert len(receipt["robots_requests"]) == 1
    assert receipt["prompt_hash"] is None and receipt["model_route"] is None


def test_collection_manifest_conforms_and_pins_everything() -> None:
    identity = _identity()
    run_id = derive_collection_run_id(identity)
    bindings = {
        name: f"{index}" * 64
        for index, name in enumerate(
            [
                "official_web_candidates",
                "web_discovery_manifest",
                "web_snapshot_manifest",
                "web_collection_receipt",
                "web_collection_request_plan",
                "source_family_coverage_v2",
            ]
        )
    }
    manifest = build_official_web_collection_manifest(
        run_id=run_id,
        identity=identity,
        company_id=COMPANY_ID,
        observation_cutoff_date=CUTOFF,
        artifact_bindings=bindings,
        verdict="official_packet_ready",
    )
    schema = json.loads(
        Path("schemas/official_web_collection_manifest.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(manifest)
    assert len(manifest["artifact_bindings"]) == 6
    assert "official_web_collection_manifest" not in manifest["artifact_bindings"]
    assert manifest["request_plan_sha256"] == PLAN_SHA
    assert manifest["parent_ingestion_manifest_sha256"] == PARENT_INGESTION_MANIFEST_SHA256
    assert set(manifest["pilot_input_pins"]) == set(PILOT_INPUT_PINS)


def test_unknown_verdict_is_refused() -> None:
    with pytest.raises(CollectionError) as excinfo:
        build_official_web_collection_manifest(
            run_id=derive_collection_run_id(_identity()),
            identity=_identity(),
            company_id=COMPANY_ID,
            observation_cutoff_date=CUTOFF,
            artifact_bindings={},
            verdict="probably_fine",
        )
    assert excinfo.value.reason_code == "verdict_invalid"
