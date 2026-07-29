"""Environment-specific regression for the installed SDK (ADR-034, E-P0).

This is the **only** optional file in the provider suite. Behavioural coverage
lives elsewhere and runs with no SDK installed, so nothing disappears when this
is skipped — it re-checks that the E-P0 finding still holds, it does not
reproduce it.

Nothing here builds a client, resolves Application Default Credentials, or
makes a network call. Only import and signature/field introspection.
"""

from __future__ import annotations

import inspect

import pytest

from dynamic_ai_products.providers.client_contract import SDK_VERSION
from dynamic_ai_products.providers.retry_policy import (
    API_VERSION,
    SDK_RETRY_ATTEMPTS,
    TIMEOUT_DURATION,
    TIMEOUT_SDK_PARAMETER,
    TIMEOUT_UNIT,
)

genai = pytest.importorskip("google.genai", reason="the 'provider' extra is not installed")
genai_types = pytest.importorskip("google.genai.types")


def test_the_installed_version_matches_the_exact_pin():
    from importlib.metadata import version

    assert version("google-genai") == SDK_VERSION == "2.13.0"


def test_the_client_accepts_the_locked_constructor_keywords():
    """Signature introspection only: no client is constructed."""
    parameters = inspect.signature(genai.Client.__init__).parameters
    for name in ("vertexai", "project", "location", "http_options"):
        assert name in parameters, name
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_http_options_exposes_the_pinned_timeout_parameter():
    field_name = TIMEOUT_SDK_PARAMETER.rsplit(".", 1)[1]
    assert field_name == "timeout"
    assert field_name in genai_types.HttpOptions.model_fields


def test_the_timeout_unit_is_still_milliseconds():
    """E-P0 drift guard. If the SDK ever changes the unit, fail loudly."""
    field = genai_types.HttpOptions.model_fields["timeout"]
    assert TIMEOUT_UNIT == "milliseconds"
    assert "millisecond" in (field.description or "").lower()

    # Behavioural corroboration: the SDK divides by 1000 before httpx.
    from google.genai import _api_client

    source = inspect.getsource(_api_client.get_timeout_in_seconds)
    assert "/ 1000" in source
    assert _api_client.get_timeout_in_seconds(TIMEOUT_DURATION) == TIMEOUT_DURATION / 1000.0


def test_http_options_accepts_the_locked_api_version_and_retry_fields():
    fields = genai_types.HttpOptions.model_fields
    assert "api_version" in fields
    assert "retry_options" in fields
    assert API_VERSION == "v1"


def test_disabling_sdk_retry_means_attempts_one():
    """The SDK's own wording: 0 or 1 attempts means no retries."""
    description = genai_types.HttpRetryOptions.model_fields["attempts"].description or ""
    assert "no retries" in description.lower()
    assert SDK_RETRY_ATTEMPTS == 1


def test_the_locked_http_options_are_constructible_without_a_client():
    """Validates the field types only; no transport and no credential."""
    options = genai_types.HttpOptions(
        api_version=API_VERSION,
        timeout=TIMEOUT_DURATION,
        retry_options=genai_types.HttpRetryOptions(attempts=SDK_RETRY_ATTEMPTS),
    )
    assert options.timeout == 300000
    assert options.api_version == "v1"
    assert options.retry_options.attempts == 1
