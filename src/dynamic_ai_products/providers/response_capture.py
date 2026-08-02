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

ADR-043 (E-M) adds two-operation capture. A single ``_captured`` slot was
adequate while one run meant one send; it is not adequate once a run walks
``countTokens`` and then up to three ``generateContent`` attempts. Two changes
follow, both opt-in through ``operation_endpoints``:

- captures are keyed by ``(operation_label, attempt_ordinal)`` and are
  **single-use**: a second write to a filled key is refused rather than allowed
  to overwrite, so a retryable attempt's body can never be silently replaced by
  the one that came after it;
- before each send the active operation context's **one** declared endpoint is
  compared for equality with the actual request URL. Allowlist membership cannot
  catch a crossed operation, because both operations are on the allowlist.

One change is unconditional. A ``101`` reaches this boundary — measured in
``httpcore/_sync/http11.py``, whose receive loop breaks on an
``InformationalResponse`` with status 101 — and the released guard refused only
``3xx``, so a protocol switch fell through to ``response.content``. It is now
refused alongside redirects, before the body is touched.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator
from urllib.parse import unquote, urlsplit

import httpx

from .endpoint_grammar_v2 import assert_operation_url
from .errors import ProviderError

__all__ = [
    "CapturingHttpxClient",
    "assert_endpoint_allowed",
    "normalize_endpoint",
]

_DEFAULT_HTTPS_PORT = 443
_PROTOCOL_SWITCH_STATUS = 101


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

    Four refusals, all fail-closed before or instead of reading a body:

    - ``stream=True`` — a streamed response cannot be read as bytes without
      consuming it, so byte-identical archival is impossible;
    - an endpoint outside the allowlist, and in v2 mode any URL that is not the
      active operation's own endpoint — refused **before** ``super().send``, so
      no socket is opened and the send counter does not move;
    - any 3xx — ``follow_redirects`` is ``False`` (the SDK's own client defaults
      it to ``True`` at ``_api_client.py:565``), and a redirect is terminal
      rather than a hop to a new endpoint;
    - a ``101`` protocol switch, which reaches this boundary and carries no
      entity body worth archiving.
    """

    def __init__(
        self,
        *,
        endpoint_allowlist: tuple[str, ...],
        operation_endpoints: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        # Explicit, and deliberately the opposite of the SDK's own default.
        kwargs["follow_redirects"] = False
        super().__init__(**kwargs)
        self._endpoint_allowlist = tuple(endpoint_allowlist)
        self._operation_endpoints = (
            dict(operation_endpoints) if operation_endpoints is not None else None
        )
        self._captured: bytes | None = None
        self._send_calls = 0
        self._active_operation: str | None = None
        self._ordinals: dict[str, int] = {}
        self._slots: dict[tuple[str, int], bytes] = {}
        self._filled: set[tuple[str, int]] = set()
        self._outcomes: dict[tuple[str, int], str] = {}

    @property
    def endpoint_allowlist(self) -> tuple[str, ...]:
        return self._endpoint_allowlist

    @property
    def send_calls(self) -> int:
        return self._send_calls

    @property
    def operation_endpoints(self) -> dict[str, str] | None:
        return None if self._operation_endpoints is None else dict(self._operation_endpoints)

    def captured_bytes(self) -> bytes:
        """The captured entity body, or refuse if nothing usable was captured."""
        if not isinstance(self._captured, bytes) or not self._captured:
            raise ProviderError("provider_response_unusable")
        return self._captured

    # --- v2: operation-scoped, single-use capture -----------------------------

    @contextmanager
    def operation(self, operation_label: str) -> Iterator[None]:
        """Open the operation context whose endpoint every send must match.

        The label is a **fixed code path constant**, never a caller argument and
        never inferred from a URL: inferring it would turn every URL the matcher
        accepts into its own label generator.
        """
        if self._operation_endpoints is None:
            raise ProviderError("provider_response_unusable")
        if operation_label not in self._operation_endpoints:
            raise ProviderError("provider_response_unusable")
        if self._active_operation is not None:
            raise ProviderError("provider_response_unusable")
        self._active_operation = operation_label
        try:
            yield
        finally:
            self._active_operation = None

    def next_ordinal(self, operation_label: str) -> int:
        """The ordinal the next send of this operation will use.

        Derived from the client's own counter rather than supplied by the caller:
        the retry loop lives inside ``tenacity``, and injecting a number from
        outside would let the recorded ordinal drift from the sends actually made.
        """
        return self._ordinals.get(operation_label, 0) + 1

    def drain(self, operation_label: str, attempt_ordinal: int) -> bytes | None:
        """Take the body captured for one attempt, or ``None`` if there was none.

        Draining is destructive by design: a body is handed to the runner's sink
        exactly once, so nothing can be persisted twice under two references.
        """
        return self._slots.pop((operation_label, attempt_ordinal), None)

    def send_outcome(self, operation_label: str, attempt_ordinal: int) -> str:
        """What happened at the send boundary for one attempt.

        This layer is the only one that sees the raw status, so it is the only
        one that can name the outcome. The connector reads it rather than
        re-deriving it from an exception, which by then has been sanitized.
        """
        return self._outcomes.get(
            (operation_label, attempt_ordinal), "no_response_transport_failure"
        )

    @staticmethod
    def _classify(status_code: int) -> str:
        if status_code < 200:
            # Measured in httpcore/_sync/http11.py: the receive loop breaks only
            # on h11.Response or on an InformationalResponse with status 101, so
            # 101 is the one informational status that reaches this boundary.
            return "response_protocol_switch"
        if status_code < 300:
            return "response_2xx"
        if status_code < 400:
            return "response_redirect_refused"
        if status_code < 500:
            return "response_4xx"
        return "response_5xx"

    def send(self, request: httpx.Request, *, stream: bool = False, **kwargs: Any):
        if stream:
            raise ProviderError("provider_response_unusable")
        active = self._active_operation
        versioned = self._operation_endpoints is not None
        ordinal = 0
        if versioned:
            if active is None:
                raise ProviderError("provider_response_unusable")
            ordinal = self._ordinals.get(active, 0) + 1
            if (active, ordinal) in self._filled:
                # Single-use: a filled slot is never overwritten.
                raise ProviderError("provider_response_unusable")
            self._ordinals[active] = ordinal
            try:
                assert_operation_url(
                    str(request.url),
                    operation_label=active,
                    expected=self._operation_endpoints[active],
                )
            except ProviderError:
                # The request never left the process, so the send counter does
                # not move, but the attempt is still an observed fact.
                self._outcomes[(active, ordinal)] = "not_sent_context_url_mismatch"
                raise
        # Before any I/O: an off-allowlist request never leaves this process.
        assert_endpoint_allowed(str(request.url), self._endpoint_allowlist)
        self._send_calls += 1
        try:
            response = super().send(request, stream=False, **kwargs)
        except BaseException:
            if versioned and active is not None:
                self._outcomes[(active, ordinal)] = "no_response_transport_failure"
            raise
        if versioned and active is not None:
            self._outcomes[(active, ordinal)] = self._classify(response.status_code)
        if response.status_code == _PROTOCOL_SWITCH_STATUS:
            raise ProviderError("provider_response_unusable")
        if 300 <= response.status_code < 400:
            raise ProviderError("provider_response_unusable")
        # content is the authority; text is derived from it.
        self._captured = response.content
        if versioned and active is not None:
            key = (active, ordinal)
            self._filled.add(key)
            self._slots[key] = response.content
        return response
