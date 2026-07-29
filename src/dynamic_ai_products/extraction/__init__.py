"""Pilot 0 Stage 05-07 extraction boundary (ADR-033, Increment E-A).

The provider run is separate from the evaluation harness: extraction emits
hash-bound artifacts and the harness consumes them by digest alone. **E-A is
offline** — the package carries no network capability at all, and
``provider_adapter`` is a typed protocol satisfied in tests by an injected
fake. The concrete connector, model label, parameters, and credentials belong
to the separately locked E-P increment.

Boundaries enforced here and covered by tests:

- the only permitted evaluation import is ``evaluation.source_snapshot``;
  ``evaluation`` never imports this package, and neither do ``ingestion``,
  ``collection``, or ``universe``;
- no network import beyond ``urllib.parse``, no URL literal, no SDK, no
  credential or environment-secret read, no transport construction;
- no clock and no VCS read: ``code_commit`` and ``run_created_at`` are
  caller-injected;
- snapshots and validation decision sets are hydrated from pinned
  reference/SHA identities, never accepted as caller-supplied documents;
- every released evaluation-shaped artifact carries a closed static contract
  pin, and caller-supplied contract metadata fails closed;
- the neutral ``WriteOnceError`` never escapes: it becomes
  :class:`ExtractionError`.
"""

from __future__ import annotations

from .errors import ExtractionError, translate_write_once_error

__all__ = ["ExtractionError", "translate_write_once_error"]
