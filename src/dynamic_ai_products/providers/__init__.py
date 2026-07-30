"""Model-execution provider connectors (ADR-034 E-P, ADR-035 E-L).

**Default-deny, with an authorized path behind a two-key handshake.** With no
authorization the Vertex connector behaves exactly as E-P shipped it: both
public entry points refuse with ``live_call_not_authorized``. The authorized
path opens only when the connector's configured digest matches the digest the
runner verified from the SPEC-027 governance chain.

**The vendor SDK is reached from exactly one module.** E-P shipped zero
``google.*`` imports under ``src/``; E-L raises that to one —
:mod:`~dynamic_ai_products.providers.sdk_factory` — and the boundary guard is an
exact allowlist naming that file rather than a count. The import is lazy, inside
the factory body, so importing this package pulls in nothing, and the factory is
unreachable until the handshake passes.

Boundaries enforced here and covered by tests:

- the single permitted outbound edge is
  ``extraction.provider_adapter``, and only its ``ExtractionProvider``,
  ``ProviderRequest``, and ``ProviderResponse`` surface;
- ``httpx`` is imported by exactly one module, the capture client, which refuses
  streaming, disables redirect following, and checks the endpoint allowlist
  before any request leaves the process;
- ``extraction`` never imports this package, and neither do ``evaluation``,
  ``universe``, ``ingestion``, or ``collection``;
- no environment variable is read: the Vertex project and location are
  caller-injected and Application Default Credentials are resolved by the SDK
  itself, so credential material never passes through this code and this package
  never verifies, reads, or provisions a credential;
- :class:`~.errors.ProviderError` has no free-text channel, so an upstream
  message, body, header, or token cannot reach an artifact.
"""

from __future__ import annotations

from .errors import PROVIDER_REASON_CODES, ProviderError, TERMINAL_REASON_CODES

__all__ = ["PROVIDER_REASON_CODES", "ProviderError", "TERMINAL_REASON_CODES"]
