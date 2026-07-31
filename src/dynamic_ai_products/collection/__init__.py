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

ADR-037 (E-C-D) adds documentation-evidence acquisition and, with it, this
package's first outbound transport. Two boundaries keep that narrow:

- ``http_adapter`` is the **only** module here that may import ``httpx``, and
  ``documentation_policy`` is the **only** production module that may import
  ``http_adapter``. Neither is exported below: no public name exposes a raw
  ``send(url)`` capability, so the governed entry point is the only route to the
  network. Direct adapter use elsewhere is ``noncanonical_experiment`` and is
  barred from governed artifacts;
- the official-web transport policy is untouched.
  ``collection.transport.follow_redirects`` keeps its five-hop, apex-bound
  semantics, which ADR-032 hard-binds to the HubSpot run. The documentation
  policy needs exactly one hop across apexes against a frozen pair list, so it
  implements its own rule over the same generic adapter rather than loosening a
  hard-bound guarantee for an unrelated purpose.
"""

from __future__ import annotations

from .documentation_policy import (
    DocumentationCollectionResult,
    collect_documentation_evidence,
)
from .errors import CollectionError, translate_write_once_error

__all__ = [
    "CollectionError",
    "DocumentationCollectionResult",
    "collect_documentation_evidence",
    "translate_write_once_error",
]
