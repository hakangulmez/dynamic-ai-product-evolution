"""Duck-typed error translation (ADR-034, E-P).

No vendor exception class is imported, so the taxonomy is exercised with plain
fakes and no SDK installed. Classification reads only structural attributes and
the class name — never the exception's text — so an upstream message, body, or
header cannot reach a reason code.
"""

from __future__ import annotations

import pytest

from dynamic_ai_products.extraction.provider_adapter import ProviderResponse
from dynamic_ai_products.providers.errors import TERMINAL_REASON_CODES, ProviderError
from dynamic_ai_products.providers.vertex_gemini import (
    adapt_response,
    translate_provider_exception,
)

SECRET = "ya29.SUPER-SECRET-ACCESS-TOKEN"


def _exc(name: str, **attributes):
    cls = type(name, (Exception,), {})
    instance = cls(f"upstream body {SECRET} Authorization: Bearer {SECRET}")
    for key, value in attributes.items():
        setattr(instance, key, value)
    return instance


class _Response:
    def __init__(self, status_code):
        self.status_code = status_code


@pytest.mark.parametrize(
    "name,expected",
    [
        ("DefaultCredentialsError", "adc_not_configured"),
        ("RefreshError", "adc_refresh_failed"),
        ("ReauthFailError", "adc_expired"),
    ],
)
def test_adc_failures_are_classified_by_class_name(name, expected):
    assert translate_provider_exception(_exc(name)).reason_code == expected


@pytest.mark.parametrize(
    "status,expected",
    [
        (403, "vertex_permission_denied"),
        (404, "vertex_model_not_found"),
        (408, "provider_timeout"),
        (429, "vertex_quota_exhausted"),
        (500, "vertex_unavailable"),
        (502, "vertex_unavailable"),
        (503, "vertex_unavailable"),
        (504, "vertex_unavailable"),
    ],
)
def test_status_codes_are_classified(status, expected):
    assert translate_provider_exception(_exc("ApiError", code=status)).reason_code == expected
    assert (
        translate_provider_exception(_exc("ApiError", status_code=status)).reason_code
        == expected
    )
    nested = _exc("ApiError")
    nested.response = _Response(status)
    assert translate_provider_exception(nested).reason_code == expected


def test_a_timeout_class_name_is_classified():
    assert translate_provider_exception(_exc("ReadTimeout")).reason_code == "provider_timeout"


@pytest.mark.parametrize("status", [400, 401, 409, 418, 451])
def test_an_unmapped_status_collapses_to_an_unusable_outcome(status):
    """The released enum is never widened to accommodate a new upstream code."""
    translated = translate_provider_exception(_exc("ApiError", code=status))
    assert translated.reason_code == "provider_response_unusable"


def test_an_unclassifiable_failure_collapses_to_an_unusable_outcome():
    assert (
        translate_provider_exception(_exc("Mystery")).reason_code
        == "provider_response_unusable"
    )


def test_an_already_translated_error_passes_through():
    original = ProviderError("vertex_unavailable", attempt_count=2)
    assert translate_provider_exception(original) is original


def test_every_translated_reason_is_terminal_and_carries_no_upstream_text():
    for name in ("DefaultCredentialsError", "RefreshError", "ReadTimeout", "Mystery"):
        translated = translate_provider_exception(_exc(name))
        assert translated.reason_code in TERMINAL_REASON_CODES
        assert SECRET not in str(translated)
        assert "Authorization" not in str(translated)
        assert "upstream body" not in str(translated)


def test_a_status_bearing_failure_also_carries_no_upstream_text():
    translated = translate_provider_exception(_exc("ApiError", code=429))
    assert SECRET not in str(translated)
    assert "Bearer" not in str(translated)


class _SdkResponse:
    def __init__(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)


def test_a_response_is_adapted_verbatim():
    adapted = adapt_response(_SdkResponse(raw_bytes=b'{"a":1}'), prompt_sha256="c" * 64)
    assert isinstance(adapted, ProviderResponse)
    assert adapted.raw_bytes == b'{"a":1}'
    assert adapted.model_provider == "google_vertex_ai"
    assert adapted.model_name == "gemini-2.5-flash"
    assert adapted.prompt_model_metadata["prompt_sha256"] == "c" * 64


def test_malformed_output_is_preserved_never_repaired():
    junk = b'  {"trailing": "junk"} \n not json '
    adapted = adapt_response(_SdkResponse(raw_bytes=junk), prompt_sha256="c" * 64)
    assert adapted.raw_bytes == junk


def test_a_text_only_response_is_refused_never_encoded_into_bytes():
    """E-P does not invent a raw artifact the provider never sent.

    Encoding a decoded ``text`` attribute would fabricate the very bytes that
    raw-before-parse exists to preserve. The real SDK response-byte capture
    surface is designed in E-L; here the answer is a refusal.
    """
    with pytest.raises(ProviderError) as excinfo:
        adapt_response(_SdkResponse(text='{"a":1}'), prompt_sha256="c" * 64)
    assert excinfo.value.reason_code == "provider_response_unusable"


def test_a_genuine_bytes_field_passes_through_byte_identical():
    payload = b'\x00\xff{"a": 1}\n  trailing '
    adapted = adapt_response(_SdkResponse(raw_bytes=payload), prompt_sha256="c" * 64)
    assert adapted.raw_bytes == payload
    assert isinstance(adapted.raw_bytes, bytes)


def test_a_bytearray_is_accepted_and_stored_as_bytes():
    adapted = adapt_response(_SdkResponse(raw_bytes=bytearray(b"\x01\x02")), prompt_sha256="c" * 64)
    assert adapted.raw_bytes == b"\x01\x02"
    assert type(adapted.raw_bytes) is bytes


@pytest.mark.parametrize(
    "response",
    [
        _SdkResponse(),
        _SdkResponse(raw_bytes=7),
        _SdkResponse(raw_bytes=None),
        _SdkResponse(raw_bytes='{"a":1}'),
        _SdkResponse(text="only text", candidates=[]),
        None,
    ],
)
def test_an_unusable_response_is_refused(response):
    with pytest.raises(ProviderError) as excinfo:
        adapt_response(response, prompt_sha256="c" * 64)
    assert excinfo.value.reason_code == "provider_response_unusable"


def test_no_encode_or_str_coercion_exists_in_the_adapter_source():
    """Structural guard: the refusal cannot be softened back into a conversion."""
    import inspect

    from dynamic_ai_products.providers import vertex_gemini

    source = inspect.getsource(vertex_gemini.adapt_response)
    for forbidden in (".encode(", "str(", "json.dumps", ".decode("):
        assert forbidden not in source, forbidden
