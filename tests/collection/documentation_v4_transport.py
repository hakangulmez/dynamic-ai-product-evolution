"""The one v0.4 transport double: ordinal-only response selection (ADR-040).

**Why this exists.** Every earlier documentation test double branched on
``url == pair["requested_url"]`` to decide whether it was answering the hop or
the terminal document. Under v0.4 that is ambiguous by construction: E3 is a
``direct`` route whose requested and final URLs are the *same URL*, so a
URL-equality branch cannot distinguish "first send" from "second send" and would
silently answer the wrong thing.

**The rule.** Responses are selected by **call ordinal alone**. ``url`` and
``iterate_body`` are *assertions*, never selectors: the fake already knows what
call number it is on, checks that the collector asked for what the script says it
should ask for, and fails immediately otherwise.

That is a property of this helper, not something production code can enforce --
a test double is test code, and the collector never sees it. What the design does
guarantee is that a v0.4 test written against this helper *cannot* infer a phase
from URL equality, because the helper offers no way to.

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
    "hop",
    "terminal",
]

BODY = b"<html><body>official claim</body></html>"
HTML = {"content-type": "text/html; charset=utf-8"}


class TransportScriptError(AssertionError):
    """The collector deviated from the scripted call sequence."""


@dataclass(frozen=True)
class ExpectedCall:
    """One scripted send: what the collector must ask for, and what it gets back.

    ``outcome`` is either an :class:`AdapterResponse` to return or a
    :class:`CollectionError` to raise, mirroring the two ways the real adapter can
    end a send.
    """

    ordinal: int
    url: str
    iterate_body: bool
    outcome: Any


def hop(ordinal: int, url: str, location: str | None, *, status: int = 301) -> ExpectedCall:
    """Send one of a ``redirect_once`` route: headers only, body never consumed."""
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
    """A body-consuming send: send two of a hop route, or a direct route's only send."""
    payload = BODY if body is None else body
    return ExpectedCall(
        ordinal=ordinal,
        url=url,
        iterate_body=True,
        outcome=AdapterResponse(
            status,
            location,
            HTML if headers is None else headers,
            url,
            payload,
            len(payload),
        ),
    )


@dataclass
class OrdinalTransport:
    """A ``_send_once`` stand-in whose response depends only on the call ordinal.

    ``calls`` is the event queue: ``(ordinal, url, iterate_body)`` for every send
    the collector actually issued, in order. Assertions read it directly rather
    than reconstructing intent from URLs.
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
        # Selection is positional and happens BEFORE any comparison, so nothing
        # about the response depends on what the URL was.
        expected = self.script[ordinal - 1]
        assert expected.ordinal == ordinal, "script ordinals must be 1..n in order"
        self.calls.append((ordinal, url, iterate_body))
        if url != expected.url:
            raise TransportScriptError(
                f"send {ordinal} requested an unexpected url"
            )
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
        """How many sends were issued for a given URL. Used to prove 'exactly one'."""
        return sum(1 for _, observed, _ in self.calls if observed == url)

    def assert_exhausted(self) -> None:
        """Every scripted send happened, and no extra send did."""
        if len(self.calls) != len(self.script):
            raise TransportScriptError(
                f"{len(self.calls)} sends issued, {len(self.script)} scripted"
            )
