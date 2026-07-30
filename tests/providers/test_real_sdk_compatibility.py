"""Environment-specific regression for the installed SDK (ADR-034, E-P0).

This is the **only** module-level-optional file in the provider suite.
Behavioural coverage lives elsewhere and runs with no SDK installed, so nothing
disappears when this is skipped — it re-checks that the surface E-P0 and E-L
measured still holds, it does not reproduce it.

E-L adds a second drift risk here. Its entire capture strategy rests on
``HttpOptions.httpx_client`` being a public field that the SDK honours verbatim.
If that field were removed, renamed, or retyped, capture would silently stop
being byte-identical, so it is guarded alongside the timeout unit.

Nothing here builds a client, resolves Application Default Credentials, or
makes a network call. Only import and signature/field introspection.
"""

from __future__ import annotations

import inspect
import typing

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
_api_client = pytest.importorskip("google.genai._api_client")


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


# --- E-L: the public transport hook capture depends on -----------------------


def test_the_public_httpx_client_hook_still_exists_and_is_typed():
    """Capture is only byte-identical because this hook is public and honoured."""
    import httpx

    field = genai_types.HttpOptions.model_fields["httpx_client"]
    assert field.annotation == typing.Optional[httpx.Client]
    assert field.default is None


def test_the_sdk_uses_a_supplied_client_verbatim():
    """It must not wrap or replace ours, or the captured bytes would not be the
    bytes the SDK decodes."""
    source = inspect.getsource(_api_client.BaseApiClient.__init__)
    assert "self._httpx_client = self._http_options.httpx_client" in source


def test_the_sdk_does_not_close_a_client_it_did_not_create():
    """Closing is therefore the factory's obligation, done in ``finally``."""
    source = inspect.getsource(_api_client.BaseApiClient)
    assert "if not self._http_options.httpx_client" in source


def test_the_non_streaming_path_still_discards_the_raw_bytes():
    """The reason capture exists: the SDK keeps only the decoded text.

    If a future version began exposing real bytes, this guard fails loudly and
    the capture client can be reconsidered rather than kept out of habit.
    """
    # The construction lives in _request_once; _request delegates to it.
    source = inspect.getsource(_api_client.BaseApiClient._request_once)
    assert "response.text" in source
    assert genai_types.HttpResponse.model_fields["body"].annotation == typing.Optional[str]


def test_the_sdk_default_follows_redirects_so_ours_must_say_otherwise():
    """Our capture client sets follow_redirects=False explicitly because the
    SDK's own client defaults it to True."""
    source = inspect.getsource(_api_client.SyncHttpxClient.__init__)
    assert "follow_redirects" in source and "True" in source


def test_the_sdk_accepts_a_plain_string_as_contents():
    """E-R sends one canonical UTF-8 document, so ``contents`` stays a ``str``.

    Measured against the installed SDK rather than assumed: if a future version
    stopped accepting a bare string for ``contents``, the renderer's
    single-representation design would need revisiting and this fails first.
    """
    genai_types = pytest.importorskip("google.genai.types")
    from google.genai import _transformers  # noqa: PLC0415 - drift probe only

    parts = _transformers.t_contents("Firm HUBSPOT INC as of 2024-12-31.")
    assert parts, "a plain string must still transform into contents"
    assert isinstance(parts, list)
    assert isinstance(parts[0], genai_types.Content)
