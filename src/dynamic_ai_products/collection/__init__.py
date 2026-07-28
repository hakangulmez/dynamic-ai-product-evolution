"""Pilot 0 Stage 02-03 official-source collection boundary (ADR-032).

The separately governed operator/transport boundary that ADR-030 and ADR-031
deferred out of ``dynamic_ai_products.ingestion``. Increment C-A is code and
governance only: no live request, no artifact under ``data/``.

Boundaries enforced here and covered by tests:

- the dependency runs one way, ``collection`` -> ``provenance``; this package
  never imports ``ingestion``, and ``ingestion`` never imports this package;
- request authority comes only from a hash-pinned request plan; redirect hops
  are response-derived continuations, never independent candidate requests;
- no clock and no VCS read: ``run_created_at`` and ``code_commit`` are
  caller-injected;
- no prompt, no provider client, no evaluation-harness entry point;
- the neutral ``WriteOnceError`` never escapes: it is translated into
  :class:`CollectionError`.
"""

from __future__ import annotations

from .errors import CollectionError, translate_write_once_error

__all__ = ["CollectionError", "translate_write_once_error"]
