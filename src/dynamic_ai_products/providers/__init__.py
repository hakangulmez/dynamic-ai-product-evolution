"""Model-execution provider connectors (ADR-034, Increment E-P).

**E-P ships no live-call capability.** This package imports no vendor SDK: the
count of ``google.*`` imports under ``src/`` is zero, and both public entry
points of the Vertex connector refuse unconditionally with
``live_call_not_authorized``. E-L introduces the authorization artifact, the
SDK factory, and the authorized execution path; none of them exist here.

Boundaries enforced here and covered by tests:

- the single permitted outbound edge is
  ``extraction.provider_adapter``, and only its ``ExtractionProvider``,
  ``ProviderRequest``, and ``ProviderResponse`` surface;
- ``extraction`` never imports this package, and neither do ``evaluation``,
  ``universe``, ``ingestion``, or ``collection``;
- no environment variable is read: the Vertex project and location are
  caller-injected and Application Default Credentials are resolved by the SDK
  itself in a later increment, so credential material never passes through
  this code;
- :class:`~.errors.ProviderError` has no free-text channel, so an upstream
  message, body, header, or token cannot reach an artifact.
"""

from __future__ import annotations

from .errors import PROVIDER_REASON_CODES, ProviderError, TERMINAL_REASON_CODES

__all__ = ["PROVIDER_REASON_CODES", "ProviderError", "TERMINAL_REASON_CODES"]
