"""Pure request/config mapping (ADR-034, E-P).

These run with no SDK installed and no network: the mapping is a deterministic
function of the locked constants and the stage request.
"""

from __future__ import annotations

import hashlib
import pytest

from dynamic_ai_products.extraction.provider_adapter import ProviderRequest
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.retry_policy import (
    API_VERSION,
    SDK_RETRY_ATTEMPTS,
    TIMEOUT_DURATION,
)
from dynamic_ai_products.providers.vertex_gemini import (
    build_http_options_kwargs,
    build_request_config,
)


CONTENTS = "prompt body with HUBSPOT INC and p-1"
CONTENTS_SHA256 = hashlib.sha256(CONTENTS.encode("utf-8")).hexdigest()


def _request(stage: str = "product_extraction") -> ProviderRequest:
    return ProviderRequest(
        stage=stage,
        rendered_contents=CONTENTS,
        rendered_contents_sha256=CONTENTS_SHA256,
        prompt_sha256="a" * 64,
        input_packet_sha256="b" * 64,
    )


def test_http_options_carry_the_locked_timeout_and_api_version():
    options = build_http_options_kwargs()
    assert options["api_version"] == "v1" == API_VERSION
    assert options["timeout"] == 300000 == TIMEOUT_DURATION


def test_sdk_retry_is_disabled_explicitly_never_left_unset():
    """The SDK defaults to five attempts; an unset field would enable a second layer."""
    options = build_http_options_kwargs()
    assert "retry_options" in options
    assert options["retry_options"] == {"attempts": 1}
    assert SDK_RETRY_ATTEMPTS == 1


def test_request_config_maps_the_locked_model_and_parameters():
    config = build_request_config(_request())
    assert config["model"] == "gemini-2.5-flash"
    assert config["config"] == {
        "temperature": 0,
        "top_p": 1,
        "candidate_count": 1,
        "max_output_tokens": 8192,
        "response_mime_type": "application/json",
    }


def test_request_config_carries_the_binding_digests_and_stage():
    config = build_request_config(_request("task_extraction"))
    assert config["prompt_sha256"] == "a" * 64
    assert config["input_packet_sha256"] == "b" * 64
    assert config["stage"] == "task_extraction"


def test_mapping_is_deterministic():
    assert build_request_config(_request()) == build_request_config(_request())


def test_mapping_returns_copies_not_the_shared_constants():
    first = build_request_config(_request())
    first["config"]["temperature"] = 1
    assert build_request_config(_request())["config"]["temperature"] == 0


@pytest.mark.parametrize("payload", [None, 7, "text", {"stage": "product_extraction"}])
def test_a_non_request_payload_is_refused(payload):
    with pytest.raises(ProviderError) as excinfo:
        build_request_config(payload)
    assert excinfo.value.reason_code == "provider_response_unusable"


def test_mapping_touches_no_filesystem_clock_or_environment(monkeypatch):
    import os
    from pathlib import Path

    def explode(*args, **kwargs):
        raise AssertionError("the mapping must be pure")

    monkeypatch.setattr(Path, "read_bytes", explode)
    monkeypatch.setattr(Path, "exists", explode)
    monkeypatch.setattr(os, "environ", {})
    build_request_config(_request())
    build_http_options_kwargs()
