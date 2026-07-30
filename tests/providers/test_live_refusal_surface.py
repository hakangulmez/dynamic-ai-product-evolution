"""The default-deny surface — a code path, not a claim (ADR-034, ADR-035).

A connector built without an authorization digest refuses at both public entry
points, exactly as E-P shipped it. ``assert_run_permitted`` matters most: the
orchestrator calls it before opening a run root, so a refused run leaves zero
artifacts rather than a directory to clean up.

E-L's authorized path is covered in ``test_live_activation.py``; everything here
is the unauthorized default.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.provider_adapter import (
    ExtractionProvider,
    ProviderRequest,
    require_provider,
)
from dynamic_ai_products.providers.errors import TERMINAL_REASON_CODES, ProviderError
from dynamic_ai_products.providers.vertex_gemini import VertexGeminiProvider

PROJECT = "my-research-project"


def _provider() -> VertexGeminiProvider:
    return VertexGeminiProvider(vertex_project=PROJECT)


def _request() -> ProviderRequest:
    return ProviderRequest(
        stage="product_extraction",
        rendered_contents="prompt",
        rendered_contents_sha256="cf07194ee232eb531e15f690000d19846dea69cf05504782658afcfacb9228a2",
        prompt_sha256="a" * 64,
        input_packet_sha256="b" * 64,
    )


def test_the_connector_satisfies_the_v2_protocol():
    provider = _provider()
    assert isinstance(provider, ExtractionProvider)
    assert require_provider(provider) is provider
    for member in ("assert_run_permitted", "client_contract", "complete"):
        assert callable(getattr(provider, member))


def test_assert_run_permitted_refuses_without_an_authorization():
    with pytest.raises(ProviderError) as excinfo:
        _provider().assert_run_permitted()
    assert excinfo.value.reason_code == "live_call_not_authorized"
    # Zero attempts: nothing began, so nothing is countable.
    assert excinfo.value.attempt_count == 0
    assert not excinfo.value.is_terminal


def test_complete_refuses_without_an_authorization():
    with pytest.raises(ProviderError) as excinfo:
        _provider().complete(_request())
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_a_digest_alone_does_not_activate_an_unconfigured_connector():
    """The runner's key is useless without the connector's own."""
    with pytest.raises(ProviderError) as excinfo:
        _provider().assert_run_permitted(
            authorization_sha256="a" * 64,
            endpoint_allowlist=("https://x.example.com/v1",),
            enablement_endpoint_allowlist=("https://x.example.com/v1",),
        )
    assert excinfo.value.reason_code == "live_call_not_authorized"


@pytest.mark.parametrize("payload", [None, 7, "text", {"a": 1}, _request()])
def test_complete_refuses_before_inspecting_its_argument(payload):
    with pytest.raises(ProviderError) as excinfo:
        _provider().complete(payload)
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_neither_entry_point_imports_the_vendor_sdk():
    """A delta, not an absolute: the optional compatibility test may already
    have imported the SDK in this process. What must hold is that *these calls*
    import nothing — the refusal happens before any SDK reference is touched.
    """
    before = {name for name in sys.modules if name.startswith("google")}
    provider = _provider()
    for call in (provider.assert_run_permitted, lambda: provider.complete(_request())):
        with pytest.raises(ProviderError):
            call()
    after = {name for name in sys.modules if name.startswith("google")}
    assert after == before


def test_the_provider_package_itself_pulls_in_no_google_module():
    """Importing the connector must not drag the SDK in as a side effect."""
    import subprocess  # noqa: PLC0415 - a clean interpreter is the point
    import sys as _sys

    script = (
        "import sys;"
        "import dynamic_ai_products.providers.vertex_gemini as m;"
        "print(sorted(n for n in sys.modules if n.startswith('google')))"
    )
    result = subprocess.run(
        [_sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        check=True,
    )
    assert result.stdout.strip() == "[]"


def test_the_pre_run_refusal_is_never_a_terminal_reason():
    """It can never reach the provider-error record enum."""
    assert "live_call_not_authorized" not in TERMINAL_REASON_CODES


def test_client_contract_is_still_available_while_calls_are_refused():
    """E-L flips the call path; the declared contract does not depend on it."""
    contract = _provider().client_contract()
    assert contract["model_name"] == "gemini-2.5-flash"
    assert contract["fallback_policy"] == "none"


def test_an_undeclared_reason_code_cannot_be_constructed():
    with pytest.raises(ValueError):
        ProviderError("something_invented")


@pytest.mark.parametrize("attempts", [-1, "2", 1.5, None])
def test_attempt_count_must_be_a_non_negative_integer(attempts):
    with pytest.raises(ValueError):
        ProviderError("provider_timeout", attempt_count=attempts)


def test_error_messages_carry_no_interpolated_upstream_text():
    """Every message is a fixed sentence chosen by reason code."""
    first = str(ProviderError("vertex_unavailable"))
    second = str(ProviderError("vertex_unavailable", attempt_count=3))
    assert first == second
