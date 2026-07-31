"""The generic single-send transport adapter (ADR-037, E-C-D).

Every test here is offline: `httpx.MockTransport` or a stub stands in for the
network, and nothing is written outside ``tmp_path``. What is pinned is that the
adapter performs exactly one send with a fresh client, never follows a redirect,
never consumes a redirect body, refuses oversized bodies before accepting them,
and leaks no upstream text.
"""

from __future__ import annotations

import ast
from pathlib import Path

import httpx
import pytest

from dynamic_ai_products.collection.errors import CollectionError
from dynamic_ai_products.collection.http_adapter import (
    ADAPTER_CONTRACT,
    CHUNK_BYTES,
    MAX_ENTITY_BYTES_PER_RESPONSE,
    PHASE_TIMEOUT_SECONDS,
    USER_AGENT,
    AdapterResponse,
    adapter_contract_bytes,
    require_no_tls_keylog,
    send_once,
)

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "src" / "dynamic_ai_products" / "collection" / "http_adapter.py"
URL = "https://docs.example.test/page"


def _patched(monkeypatch, handler, *, record=None):
    """Route the adapter's own client construction through MockTransport."""
    real = httpx.Client

    def factory(**kwargs):
        if record is not None:
            record.append(kwargs)
        kwargs["transport"] = httpx.MockTransport(handler)
        return real(**kwargs)

    monkeypatch.setattr(httpx, "Client", factory)


# --- the declared contract ----------------------------------------------------


def test_the_contract_declares_four_phase_timeouts_and_no_total_deadline():
    """httpx.Timeout(30.0) is four phase deadlines, not one wall clock."""
    for field in (
        "connect_timeout_seconds",
        "read_timeout_seconds",
        "write_timeout_seconds",
        "pool_timeout_seconds",
    ):
        assert ADAPTER_CONTRACT[field] == PHASE_TIMEOUT_SECONDS
    assert ADAPTER_CONTRACT["total_wall_clock_deadline"] is None


def test_the_contract_pins_the_locked_transport_values():
    assert ADAPTER_CONTRACT["total_attempts"] == 1
    assert ADAPTER_CONTRACT["retry_policy"] == "none"
    assert ADAPTER_CONTRACT["automatic_redirects_disabled"] is True
    assert ADAPTER_CONTRACT["trust_env"] is False
    assert ADAPTER_CONTRACT["tls_verify"] is True
    assert ADAPTER_CONTRACT["client_lifecycle"] == "one_client_per_send"
    assert ADAPTER_CONTRACT["chunk_bytes"] == CHUNK_BYTES == 64 * 1024
    assert MAX_ENTITY_BYTES_PER_RESPONSE == 8 * 1024 * 1024


def test_the_contract_bytes_are_deterministic():
    assert adapter_contract_bytes() == adapter_contract_bytes()


# --- client construction ------------------------------------------------------


def test_the_client_is_constructed_with_the_locked_flags(monkeypatch):
    seen: list[dict] = []
    _patched(monkeypatch, lambda r: httpx.Response(200, content=b"x"), record=seen)
    send_once(url=URL, iterate_body=False)
    assert len(seen) == 1, "exactly one client per send"
    kwargs = seen[0]
    assert kwargs["follow_redirects"] is False
    assert kwargs["trust_env"] is False
    assert kwargs["verify"] is True
    timeout = kwargs["timeout"]
    assert timeout.connect == timeout.read == timeout.write == timeout.pool == 30.0
    assert kwargs["headers"]["User-Agent"] == USER_AGENT
    assert "Authorization" not in kwargs["headers"]


def test_a_fresh_client_per_send_carries_no_cookie(monkeypatch):
    """Measured: a reused client would send Cookie on the second request."""
    seen_headers: list[dict] = []

    def handler(request):
        seen_headers.append({k.lower(): v for k, v in request.headers.items()})
        if len(seen_headers) == 1:
            return httpx.Response(200, headers={"Set-Cookie": "sid=abc"}, content=b"a")
        return httpx.Response(200, content=b"b")

    _patched(monkeypatch, handler)
    send_once(url=URL, iterate_body=False)
    send_once(url=URL, iterate_body=False)
    assert "cookie" not in seen_headers[1]
    assert all("authorization" not in h for h in seen_headers)


# --- SSLKEYLOGFILE ------------------------------------------------------------


def test_a_configured_keylog_destination_refuses_before_any_client(
    monkeypatch, tmp_path: Path
):
    keylog = tmp_path / "keylog.txt"
    monkeypatch.setenv("SSLKEYLOGFILE", str(keylog))
    constructed: list[dict] = []
    _patched(monkeypatch, lambda r: httpx.Response(200, content=b"x"), record=constructed)
    with pytest.raises(CollectionError) as excinfo:
        send_once(url=URL, iterate_body=False)
    assert excinfo.value.reason_code == "tls_keylog_environment_present"
    assert constructed == [], "no client may be constructed"
    assert not keylog.exists(), "no keylog file may be created"
    # The value is never echoed.
    assert str(keylog) not in str(excinfo.value)


def test_the_keylog_guard_reads_presence_only(monkeypatch):
    monkeypatch.setenv("SSLKEYLOGFILE", "")
    with pytest.raises(CollectionError) as excinfo:
        require_no_tls_keylog()
    assert excinfo.value.reason_code == "tls_keylog_environment_present"


# --- redirect bodies are never consumed ---------------------------------------


def test_a_redirect_body_is_never_iterated(monkeypatch):
    """A hostile multi-megabyte redirect payload must not be downloaded."""
    huge = b"x" * (2 * 1024 * 1024)

    def handler(request):
        return httpx.Response(
            301, headers={"Location": "https://docs.example.test/final"}, content=huge
        )

    _patched(monkeypatch, handler)
    response = send_once(url=URL, iterate_body=False)
    assert response.status == 301
    assert response.location == "https://docs.example.test/final"
    assert response.entity_bytes is None
    assert response.decompressed_byte_count == 0


# --- bounded streaming --------------------------------------------------------


def test_a_terminal_body_is_returned_with_its_decompressed_count(monkeypatch):
    body = b"<html>ok</html>"
    _patched(
        monkeypatch,
        lambda r: httpx.Response(200, headers={"Content-Type": "text/html"}, content=body),
    )
    response = send_once(url=URL, iterate_body=True)
    assert response.entity_bytes == body
    assert response.decompressed_byte_count == len(body)
    assert response.status == 200


@pytest.mark.parametrize(
    "declared",
    [None, 1, 10_000_000],
    ids=["absent-content-length", "lying-under-limit", "over-limit"],
)
def test_an_oversized_body_is_refused_regardless_of_content_length(
    monkeypatch, declared
):
    """Content-Length is advisory: the cap is enforced on accepted bytes."""
    body = b"y" * 5000

    def handler(request):
        headers = {"Content-Type": "text/html"}
        if declared is not None:
            headers["Content-Length"] = str(declared)
        return httpx.Response(200, headers=headers, content=body)

    _patched(monkeypatch, handler)
    with pytest.raises(CollectionError) as excinfo:
        send_once(url=URL, iterate_body=True, max_entity_bytes=1000)
    assert excinfo.value.reason_code == "entity_too_large"


def test_a_body_exactly_at_the_cap_is_accepted(monkeypatch):
    body = b"z" * 1000
    _patched(monkeypatch, lambda r: httpx.Response(200, content=body))
    response = send_once(url=URL, iterate_body=True, max_entity_bytes=1000)
    assert response.decompressed_byte_count == 1000


def test_no_eager_whole_body_path_exists_in_the_source():
    """Static proof that .content / .read() never appear."""
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"))
    offenders = [
        f"{node.attr}:{node.lineno}"
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in {"content", "read"}
    ]
    assert not offenders, offenders
    assert "iter_bytes" in SOURCE.read_text(encoding="utf-8")


# --- request identity ---------------------------------------------------------


def test_a_mismatched_request_identity_refuses_before_status_is_trusted(monkeypatch):
    """The transport must not be able to answer a different URL."""
    real = httpx.Client

    class _Lying:
        def __init__(self, inner):
            self._inner = inner

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def stream(self, method, url):
            return self._inner.stream(method, "https://docs.example.test/other")

        def __getattr__(self, name):
            return getattr(self._inner, name)

    def factory(**kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda r: httpx.Response(200, content=b"x")
        )
        return _Lying(real(**kwargs))

    monkeypatch.setattr(httpx, "Client", factory)
    with pytest.raises(CollectionError) as excinfo:
        send_once(url=URL, iterate_body=False)
    assert excinfo.value.reason_code == "response_request_identity_mismatch"


# --- sanitized failures -------------------------------------------------------


def test_a_transport_timeout_is_sanitized(monkeypatch):
    def handler(request):
        raise httpx.ConnectTimeout("upstream secret detail")

    _patched(monkeypatch, handler)
    with pytest.raises(CollectionError) as excinfo:
        send_once(url=URL, iterate_body=False)
    assert excinfo.value.reason_code == "transport_timeout"
    assert "upstream secret detail" not in str(excinfo.value)


def test_any_other_transport_failure_is_sanitized(monkeypatch):
    def handler(request):
        raise RuntimeError("upstream secret detail")

    _patched(monkeypatch, handler)
    with pytest.raises(CollectionError) as excinfo:
        send_once(url=URL, iterate_body=False)
    assert excinfo.value.reason_code == "transport_failed"
    assert "upstream secret detail" not in str(excinfo.value)


def test_the_adapter_response_is_frozen():
    import dataclasses

    response = AdapterResponse(200, None, {}, URL, b"x", 1)
    with pytest.raises(dataclasses.FrozenInstanceError):
        response.status = 500  # type: ignore[misc]
