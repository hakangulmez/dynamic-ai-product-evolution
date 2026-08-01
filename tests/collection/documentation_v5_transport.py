"""The one v0.5 transport double: ordinal-only response selection (ADR-041).

**Why ordinal-only, again and more so.** v0.5 walks up to three sends per entry,
and E1's and E2's first two sends differ only in host. A double that branched on
``url ==`` would have to encode the whole chain shape to answer correctly, and a
wrong branch would silently return the hop response where the document was due.

Responses are selected by **call ordinal alone**. ``url`` and ``iterate_body`` are
*assertions*, never selectors: the fake knows which call number it is on, checks
that the collector asked for what the script says, and fails immediately
otherwise. That is a property of this helper, not something production code can
enforce -- a test double is test code and the collector never sees it -- but it
makes a URL-equality inference impossible to write against it.

Failures raise inside the transport seam, so the collector cannot continue past a
violation and no receipt is published from a mis-scripted run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from dynamic_ai_products.collection.errors import CollectionError
from dynamic_ai_products.collection.http_adapter import AdapterResponse

__all__ = [
    "BODY",
    "HTML",
    "ExpectedCall",
    "OrdinalTransport",
    "TransportScriptError",
    "hop",
    "terminal",
]

BODY = b"<html><body>official claim</body></html>"
HTML = {"content-type": "text/html; charset=utf-8"}


class TransportScriptError(AssertionError):
    """The collector deviated from the scripted call sequence."""


@dataclass(frozen=True)
class ExpectedCall:
    """One scripted send: what the collector must ask for, and what it gets back."""

    ordinal: int
    url: str
    iterate_body: bool
    outcome: Any


def hop(ordinal: int, url: str, location: str | None, *, status: int = 301) -> ExpectedCall:
    """A redirect send: headers only, body never consumed."""
    return ExpectedCall(
        ordinal=ordinal,
        url=url,
        iterate_body=False,
        outcome=AdapterResponse(status, location, {}, url, None, 0),
    )


def terminal(
    ordinal: int,
    url: str,
    *,
    status: int = 200,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    location: str | None = None,
) -> ExpectedCall:
    """A body-consuming send: the terminal document request."""
    payload = BODY if body is None else body
    return ExpectedCall(
        ordinal=ordinal,
        url=url,
        iterate_body=True,
        outcome=AdapterResponse(
            status, location, HTML if headers is None else headers, url, payload, len(payload)
        ),
    )


@dataclass
class OrdinalTransport:
    """A ``_send_once`` stand-in whose response depends only on the call ordinal.

    ``calls`` is the event queue: ``(ordinal, url, iterate_body)`` for every send
    the collector actually issued, in order.
    """

    script: Sequence[ExpectedCall]
    calls: list[tuple[int, str, bool]] = field(default_factory=list)
    _ordinal: int = 0

    def __call__(self, *, url: str, iterate_body: bool, **_: Any) -> AdapterResponse:
        self._ordinal += 1
        ordinal = self._ordinal
        if ordinal > len(self.script):
            raise TransportScriptError(
                f"unexpected send {ordinal}: the script declares only {len(self.script)}"
            )
        # Positional selection happens BEFORE any comparison, so nothing about the
        # response depends on what the URL was.
        expected = self.script[ordinal - 1]
        assert expected.ordinal == ordinal, "script ordinals must be 1..n in order"
        self.calls.append((ordinal, url, iterate_body))
        if url != expected.url:
            raise TransportScriptError(f"send {ordinal} requested an unexpected url")
        if iterate_body != expected.iterate_body:
            raise TransportScriptError(
                f"send {ordinal} used iterate_body={iterate_body}, "
                f"expected {expected.iterate_body}"
            )
        if isinstance(expected.outcome, CollectionError):
            raise expected.outcome
        return expected.outcome

    @property
    def ordinals(self) -> list[int]:
        return [ordinal for ordinal, _, _ in self.calls]

    @property
    def urls(self) -> list[str]:
        return [url for _, url, _ in self.calls]

    def count_for(self, url: str) -> int:
        """How many sends were issued for a given URL."""
        return sum(1 for _, observed, _ in self.calls if observed == url)

    def assert_exhausted(self) -> None:
        """Every scripted send happened, and no extra send did."""
        if len(self.calls) != len(self.script):
            raise TransportScriptError(
                f"{len(self.calls)} sends issued, {len(self.script)} scripted"
            )
