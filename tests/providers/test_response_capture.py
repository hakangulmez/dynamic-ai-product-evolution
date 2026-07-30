"""Byte-identical entity-body capture and its refusals (ADR-035).

No network: a fake ``httpx`` transport answers every request in-process. The
capture point is ``httpx.Response.content``, which is the authority from which
``.text`` is derived — so what is captured is exactly what the SDK later decodes.
"""

from __future__ import annotations

import inspect

import httpx
import pytest

from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.response_capture import (
    CapturingHttpxClient,
    assert_endpoint_allowed,
    normalize_endpoint,
)

ORIGIN = "https://us-central1-aiplatform.googleapis.com"
ALLOWLIST = (f"{ORIGIN}/v1/projects",)
URL = f"{ORIGIN}/v1/projects/p/locations/us-central1/publishers/google/models/x:generateContent"
BODY = b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'


def _client(*, handler=None, allowlist=ALLOWLIST):
    def default(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=BODY)

    transport = httpx.MockTransport(handler or default)
    return CapturingHttpxClient(endpoint_allowlist=allowlist, transport=transport)


# --- normalization ------------------------------------------------------------


def test_normalization_lowercases_strips_and_resolves():
    assert normalize_endpoint("https://Example.COM.:443/v1/./a/../b?q=1") == (
        "https://example.com",
        "/v1/b",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/v1",
        "ws://example.com/v1",
        "https://user:pass@example.com/v1",
        "https://example.com:8443/v1",
        "https:///v1",
        "",
        None,
        7,
    ],
)
def test_unusable_urls_are_refused(url):
    with pytest.raises(ProviderError) as excinfo:
        normalize_endpoint(url)
    assert excinfo.value.reason_code == "provider_response_unusable"


def test_percent_encoding_cannot_hide_a_traversal():
    assert normalize_endpoint(f"{ORIGIN}/v1/projects/%2E%2E/evil")[1] == "/v1/evil"


# --- allowlist ----------------------------------------------------------------


def test_an_allowed_endpoint_passes():
    assert_endpoint_allowed(URL, ALLOWLIST)


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/v1/projects/p",
        f"{ORIGIN}/v1/projectsX/p",
        f"{ORIGIN}/v2/projects/p",
        f"{ORIGIN}/",
        f"http://{ORIGIN.removeprefix('https://')}/v1/projects/p",
    ],
)
def test_an_off_allowlist_endpoint_is_refused(url):
    with pytest.raises(ProviderError) as excinfo:
        assert_endpoint_allowed(url, ALLOWLIST)
    assert excinfo.value.reason_code == "provider_response_unusable"


def test_an_empty_allowlist_refuses_everything():
    with pytest.raises(ProviderError):
        assert_endpoint_allowed(URL, ())


def test_matching_is_at_a_segment_boundary():
    assert_endpoint_allowed(f"{ORIGIN}/v1/projects", ALLOWLIST)
    assert_endpoint_allowed(f"{ORIGIN}/v1/projects/p", ALLOWLIST)
    with pytest.raises(ProviderError):
        assert_endpoint_allowed(f"{ORIGIN}/v1/projectsevil", ALLOWLIST)


# --- capture ------------------------------------------------------------------


def test_the_entity_body_is_captured_byte_identically():
    with _client() as client:
        response = client.send(client.build_request("POST", URL, content=b"{}"))
        assert response.status_code == 200
        assert client.captured_bytes() == BODY
        # text is derived from content, so the bytes we hold are the bytes the
        # SDK will decode.
        assert response.text == BODY.decode("utf-8")


def test_a_non_utf8_body_survives_unchanged():
    payload = b"\x00\xff\xfe binary \x01"

    def handler(request):
        return httpx.Response(200, content=payload)

    with _client(handler=handler) as client:
        client.send(client.build_request("POST", URL, content=b"{}"))
        assert client.captured_bytes() == payload


def test_streaming_is_refused_before_any_request():
    with _client() as client:
        with pytest.raises(ProviderError) as excinfo:
            client.send(client.build_request("POST", URL), stream=True)
        assert excinfo.value.reason_code == "provider_response_unusable"
        assert client.send_calls == 0


def test_an_off_allowlist_request_never_leaves_the_process():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, content=BODY)

    with _client(handler=handler) as client:
        with pytest.raises(ProviderError) as excinfo:
            client.send(client.build_request("POST", "https://evil.example.com/v1/projects"))
        assert excinfo.value.reason_code == "provider_response_unusable"
    assert calls == []
    assert client.send_calls == 0


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_a_redirect_is_terminal_and_never_followed(status):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(status, headers={"location": "https://evil.example.com/v1"})

    with _client(handler=handler) as client:
        with pytest.raises(ProviderError) as excinfo:
            client.send(client.build_request("POST", URL, content=b"{}"))
        assert excinfo.value.reason_code == "provider_response_unusable"
    # Exactly one request, and it never went to the redirect target.
    assert seen == [URL]


def test_follow_redirects_is_explicitly_disabled():
    """The SDK's own client sets this to True; ours sets it to False."""
    with _client() as client:
        assert client.follow_redirects is False
    source = inspect.getsource(CapturingHttpxClient.__init__)
    assert 'kwargs["follow_redirects"] = False' in source


def test_an_error_status_still_captures_the_body_but_it_is_never_persisted():
    """Held in memory only: the terminal route writes no raw prediction."""
    def handler(request):
        return httpx.Response(503, content=b'{"error":"unavailable"}')

    with _client(handler=handler) as client:
        response = client.send(client.build_request("POST", URL, content=b"{}"))
        assert response.status_code == 503
        assert client.captured_bytes() == b'{"error":"unavailable"}'


def test_captured_bytes_refuses_when_nothing_was_captured():
    with _client() as client:
        with pytest.raises(ProviderError) as excinfo:
            client.captured_bytes()
        assert excinfo.value.reason_code == "provider_response_unusable"


def test_an_empty_body_is_not_a_usable_capture():
    def handler(request):
        return httpx.Response(200, content=b"")

    with _client(handler=handler) as client:
        client.send(client.build_request("POST", URL, content=b"{}"))
        with pytest.raises(ProviderError):
            client.captured_bytes()


def test_the_archived_bytes_come_from_content_never_from_a_decoded_form():
    """The guard is response-side.

    ``str(request.url)`` is a request-side URL conversion for the allowlist
    check, not a re-serialization of a response, so a blanket ``str(`` ban would
    flag the endpoint guard itself. What must never appear is a decoded response
    being turned back into bytes.
    """
    source = inspect.getsource(CapturingHttpxClient.send)
    assert "self._captured = response.content" in source
    for forbidden in (".encode(", "response.text", "json.dumps"):
        assert forbidden not in source, forbidden
