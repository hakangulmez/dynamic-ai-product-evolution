"""The declared provider-client contract (ADR-034, E-P).

Built purely in memory and validated strictly by the extraction orchestrator
before any run root exists, so a rejected contract leaves nothing on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.manifests import (
    CLIENT_CONTRACT_CONTRACT,
    CLIENT_CONTRACT_PROPERTIES,
    validate_provider_client_contract,
)
from dynamic_ai_products.extraction.provider_adapter import PROVIDER_PROTOCOL_VERSION
from dynamic_ai_products.providers.client_contract import (
    PROVIDER_PROTOCOL_VERSION_PIN,
    build_client_contract,
)
from dynamic_ai_products.providers.errors import ProviderError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "schemas" / "extraction_provider_client_contract.schema.json").read_text()
)
PROJECT = "my-research-project"


def _contract(**overrides):
    contract = build_client_contract(vertex_project=PROJECT)
    contract.update(overrides)
    return contract


def test_the_contract_validates_against_its_released_schema():
    Draft202012Validator(SCHEMA).validate(_contract())


def test_the_property_set_matches_the_released_schema_exactly():
    assert set(SCHEMA["required"]) == set(CLIENT_CONTRACT_PROPERTIES)
    assert set(_contract()) == set(CLIENT_CONTRACT_PROPERTIES)
    assert SCHEMA["additionalProperties"] is False


def test_the_protocol_version_pin_does_not_drift():
    """providers may not import the constant, so the pin is re-derived here."""
    assert PROVIDER_PROTOCOL_VERSION_PIN == PROVIDER_PROTOCOL_VERSION
    assert _contract()["provider_protocol_version"] == PROVIDER_PROTOCOL_VERSION


def test_the_locked_provider_model_and_sdk_values():
    contract = _contract()
    assert contract["contract"] == CLIENT_CONTRACT_CONTRACT
    assert contract["sdk_name"] == "google-genai"
    assert contract["sdk_version"] == "2.13.0"
    assert contract["model_provider"] == "google_vertex_ai"
    assert contract["model_name"] == "gemini-2.5-flash"
    assert contract["vertex_location"] == "us-central1"
    assert contract["auth_method"] == "application_default_credentials"
    assert contract["api_version"] == "v1"


def test_the_e_p0_resolved_timeout_values():
    contract = _contract()
    assert contract["timeout_sdk_parameter"] == "google.genai.types.HttpOptions.timeout"
    assert contract["timeout_duration"] == 300000
    assert contract["timeout_unit"] == "milliseconds"


def test_the_retry_values_declare_a_single_owner():
    contract = _contract()
    assert contract["sdk_retry_disabled"] is True
    assert contract["sdk_retry_attempts"] == 1
    assert contract["retry_owner"] == "tenacity"
    assert contract["retry_max_attempts"] == 3
    assert contract["retry_delays_seconds"] == [1, 2]
    assert contract["retry_jitter"] is False
    assert contract["retry_trigger_status_codes"] == [408, 429, 500, 502, 503, 504]
    assert contract["fallback_policy"] == "none"


def test_building_is_pure_and_deterministic(monkeypatch):
    import os

    def explode(*args, **kwargs):
        raise AssertionError("build_client_contract must be pure")

    monkeypatch.setattr(Path, "read_bytes", explode)
    monkeypatch.setattr(Path, "exists", explode)
    monkeypatch.setattr(os, "environ", {})
    assert build_client_contract(vertex_project=PROJECT) == _contract()


def test_the_builder_returns_copies_not_shared_state():
    first = build_client_contract(vertex_project=PROJECT)
    first["model_parameters"]["temperature"] = 1
    assert build_client_contract(vertex_project=PROJECT)["model_parameters"]["temperature"] == 0


@pytest.mark.parametrize("project", ["", "AB", "Bad-Caps", "x", "a" * 40, None, 7])
def test_a_malformed_project_is_refused(project):
    with pytest.raises(ProviderError) as excinfo:
        build_client_contract(vertex_project=project)
    assert excinfo.value.reason_code == "vertex_project_invalid"


@pytest.mark.parametrize("location", ["", "europe-west4", "US-CENTRAL1", None])
def test_a_location_outside_the_allowlist_is_refused(location):
    with pytest.raises(ProviderError) as excinfo:
        build_client_contract(vertex_project=PROJECT, vertex_location=location)
    assert excinfo.value.reason_code == "vertex_location_invalid"


# --- strict validation on the extraction side ---------------------------------


def test_a_well_formed_contract_is_accepted_and_copied():
    validated = validate_provider_client_contract(_contract())
    assert validated == _contract()


@pytest.mark.parametrize("contract", [None, "text", 7, [], ()])
def test_a_non_mapping_contract_is_refused(contract):
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(contract)
    assert excinfo.value.reason_code == "client_contract_invalid"


def test_a_wrong_contract_identity_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(_contract(contract="something_else@0.1.0"))
    assert excinfo.value.reason_code == "client_contract_invalid"


def test_a_missing_property_is_refused():
    contract = _contract()
    del contract["retry_policy_version"]
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(contract)
    assert excinfo.value.reason_code == "client_contract_invalid"


def test_an_undeclared_property_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(_contract(extra_field="x"))
    assert excinfo.value.reason_code == "client_contract_invalid"


def test_a_declared_fallback_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(_contract(fallback_policy="secondary_model"))
    assert excinfo.value.reason_code == "client_contract_invalid"


@pytest.mark.parametrize(
    "overrides",
    [
        {"sdk_retry_disabled": False},
        {"sdk_retry_attempts": 5},
        {"sdk_retry_attempts": None},
    ],
)
def test_an_enabled_sdk_retry_layer_is_refused(overrides):
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(_contract(**overrides))
    assert excinfo.value.reason_code == "client_contract_invalid"


# --- credential-material rejection --------------------------------------------


def test_a_token_budget_is_not_mistaken_for_a_token_value():
    """max_output_tokens is a count, not a credential. Regression guard."""
    validated = validate_provider_client_contract(_contract())
    assert validated["model_parameters"]["max_output_tokens"] == 8192


@pytest.mark.parametrize(
    "key",
    ["token", "api_key", "secret", "credentials", "authorization", "access_token",
     "private_key", "client_secret", "password", "bearer"],
)
def test_a_credential_shaped_property_is_refused(key):
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(_contract(**{key: "value"}))
    assert excinfo.value.reason_code == "credential_material_in_artifact"


def test_a_nested_credential_shaped_property_is_refused():
    contract = _contract()
    contract["model_parameters"] = {**contract["model_parameters"], "api_key": "x"}
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(contract)
    assert excinfo.value.reason_code == "credential_material_in_artifact"


@pytest.mark.parametrize(
    "value",
    ["ya29.SOME-ACCESS-TOKEN", "AIzaSyFAKEKEYVALUE", "-----BEGIN PRIVATE KEY-----"],
)
def test_credential_shaped_values_are_refused_anywhere(value):
    contract = _contract(vertex_location="us-central1")
    contract["client_module"] = value
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(contract)
    assert excinfo.value.reason_code == "credential_material_in_artifact"


def test_credential_material_is_refused_not_redacted():
    """A silent rewrite would be repair-in-place (CLAUDE.md rule 9)."""
    contract = _contract()
    contract["client_version"] = "ya29.LEAKED"
    with pytest.raises(ExtractionError):
        validate_provider_client_contract(contract)
    assert contract["client_version"] == "ya29.LEAKED"
