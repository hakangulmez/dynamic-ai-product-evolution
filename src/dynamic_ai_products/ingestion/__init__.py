"""Pilot 0 Stage 01-04 ingestion and operator boundary (ADR-030, ADR-031).

This package is the separately governed ingestion/operator boundary that
ADR-030 deferred out of ``dynamic_ai_products.universe``. Increment A is
code and governance only: no live transport, no CLI entry point, no artifact
under ``data/``.

Boundaries enforced here and covered by tests:

- the dependency runs one way, ``ingestion`` -> ``universe``; ``universe``
  never imports this package;
- no network: no transport client, no URL literal, no socket;
- no model: no prompt, no provider client, no harness entry point;
- no clock and no VCS read: ``run_created_at`` and ``code_commit`` are
  caller-injected;
- the neutral ``WriteOnceError`` never escapes this package's public API; it
  is translated into :class:`IngestionError`.
"""

from __future__ import annotations

from .errors import IngestionError, translate_write_once_error

__all__ = ["IngestionError", "translate_write_once_error"]
