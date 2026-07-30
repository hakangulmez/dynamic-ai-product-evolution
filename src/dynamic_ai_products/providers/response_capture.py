"""Byte-identical response capture over the SDK's public transport hook (ADR-035).

The SDK discards the raw bytes: ``_api_client.py:1465-1467`` builds its
``HttpResponse`` from ``[response.text]`` on the non-streaming path, and the
public ``types.HttpResponse.body`` is a ``str``. Since ``httpx.Response.text``
is *derived from* ``self.content``, capturing ``content`` yields exactly the
bytes the SDK then decodes — no encode, no re-serialization, no private API.

``HttpOptions.httpx_client`` is the public hook and the SDK uses the supplied
client verbatim (``_api_client.py:817-818``); it also declines to close a client
it did not create (``:2258``), so the lifecycle is ours.

**Archival unit.** ``content`` is the HTTP entity body *after* transfer
``Content-Encoding`` is undone — httpx decompresses gzip/br transparently. That
is the JSON payload itself and the correct thing to archive; it is not the
compressed wire bytes, and this module does not claim otherwise.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

import httpx

from .errors import ProviderError

__all__ = [
    "CapturingHttpxClient",
    "assert_endpoint_allowed",
    "normalize_endpoint",
]

_DEFAULT_HTTPS_PORT = 443


def _normalized_path(raw_path: str) -> str:
    """Percent-decode, then resolve ``.``/``..`` before comparison.

    Comparing the raw path would let ``/v1/a/../../evil`` or ``/v1%2Fa`` slip a
    different endpoint past a prefix test.
    """
    decoded = unquote(raw_path or "/")
    parts: list[str] = []
    for segment in decoded.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            if parts:
                parts.pop()
            continue
        parts.append(segment)
    return "/" + "/".join(parts)


def normalize_endpoint(url: str) -> tuple[str, str]:
    """Return ``(origin, path)`` in canonical form, or refuse.

    Only ``https`` is accepted, the host is lower-cased with any trailing dot
    removed, an explicit ``:443`` collapses to the implicit port, and a URL
    carrying userinfo is refused outright — a ``user:pass@`` segment can make a
    hostile host look like an allowed one.
    """
    if not isinstance(url, str) or not url.strip():
        raise ProviderError("provider_response_unusable")
    split = urlsplit(url)
    if split.scheme.lower() != "https":
        raise ProviderError("provider_response_unusable")
    if split.username is not None or split.password is not None or "@" in (split.netloc or ""):
        raise ProviderError("provider_response_unusable")
    host = (split.hostname or "").lower().rstrip(".")
    if not host:
        raise ProviderError("provider_response_unusable")
    try:
        port = split.port
    except ValueError as exc:
        raise ProviderError("provider_response_unusable") from exc
    if port not in (None, _DEFAULT_HTTPS_PORT):
        raise ProviderError("provider_response_unusable")
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise ProviderError("provider_response_unusable") from exc
    return f"https://{host}", _normalized_path(split.path)


def assert_endpoint_allowed(url: str, allowlist: tuple[str, ...]) -> None:
    """Refuse anything outside the allowlist. Called **before** any send.

    Matching is on origin plus path, at a segment boundary: an allowlist entry
    ``/v1/projects`` never admits ``/v1/projectsX``. Query and fragment take no
    part in the decision.
    """
    if not allowlist:
        raise ProviderError("provider_response_unusable")
    origin, path = normalize_endpoint(url)
    for entry in allowlist:
        allowed_origin, allowed_path = normalize_endpoint(entry)
        if origin != allowed_origin:
            continue
        if path == allowed_path or path.startswith(allowed_path.rstrip("/") + "/"):
            return
    raise ProviderError("provider_response_unusable")


class CapturingHttpxClient(httpx.Client):
    """An ``httpx.Client`` that captures the entity body and refuses surprises.

    Three refusals, all fail-closed before or instead of a request:

    - ``stream=True`` — a streamed response cannot be read as bytes without
      consuming it, so byte-identical archival is impossible;
    - an endpoint outside the allowlist — refused **before** ``super().send``,
      so no socket is opened;
    - any 3xx — ``follow_redirects`` is ``False`` (the SDK's own client
      defaults it to ``True`` at ``_api_client.py:565``), and a redirect is
      terminal rather than a hop to a new endpoint.
    """

    def __init__(self, *, endpoint_allowlist: tuple[str, ...], **kwargs: Any) -> None:
        # Explicit, and deliberately the opposite of the SDK's own default.
        kwargs["follow_redirects"] = False
        super().__init__(**kwargs)
        self._endpoint_allowlist = tuple(endpoint_allowlist)
        self._captured: bytes | None = None
        self._send_calls = 0

    @property
    def endpoint_allowlist(self) -> tuple[str, ...]:
        return self._endpoint_allowlist

    @property
    def send_calls(self) -> int:
        return self._send_calls

    def captured_bytes(self) -> bytes:
        """The captured entity body, or refuse if nothing usable was captured."""
        if not isinstance(self._captured, bytes) or not self._captured:
            raise ProviderError("provider_response_unusable")
        return self._captured

    def send(self, request: httpx.Request, *, stream: bool = False, **kwargs: Any):
        if stream:
            raise ProviderError("provider_response_unusable")
        # Before any I/O: an off-allowlist request never leaves this process.
        assert_endpoint_allowed(str(request.url), self._endpoint_allowlist)
        self._send_calls += 1
        response = super().send(request, stream=False, **kwargs)
        if 300 <= response.status_code < 400:
            raise ProviderError("provider_response_unusable")
        # content is the authority; text is derived from it.
        self._captured = response.content
        return response
