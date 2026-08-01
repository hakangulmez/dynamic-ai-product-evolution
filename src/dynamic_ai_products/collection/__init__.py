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

- ``http_adapter`` is the **only** module here that may import ``httpx``, and the
  three named documentation policies -- ``documentation_policy`` (v0.3),
  ``documentation_policy_v4`` and ``documentation_policy_v5`` -- are the **only**
  production modules that may import ``http_adapter``. Neither adapter nor seam is exported below: no public
  name exposes a raw ``send(url)`` capability, so the governed entry points are
  the only route to the network. Direct adapter use elsewhere is
  ``noncanonical_experiment`` and is barred from governed artifacts;
- the official-web transport policy is untouched.
  ``collection.transport.follow_redirects`` keeps its five-hop, apex-bound
  semantics, which ADR-032 hard-binds to the HubSpot run. The documentation
  policies implement their own rule over the same generic adapter rather than
  loosening a hard-bound guarantee for an unrelated purpose.

ADR-040 (E-C-D3) added ``@0.4.0`` alongside ``@0.3.0`` rather than replacing it,
declaring route kinds per entry. ADR-041 (E-C-D4) adds ``@0.5.0`` the same way,
correcting route grammar only: ``redirect_twice_relative_path`` walks two
recognized hops, the second an absolute-path reference joined to a fixed declared
base, before the terminal document; ``redirect_once`` keeps the two-send shape.
v0.5 declares no ``direct`` kind. All three entry points are exported and each
keeps publishing the receipt contract it was built for.
"""

from __future__ import annotations

from .documentation_policy import (
    DocumentationCollectionResult,
    collect_documentation_evidence,
)
from .documentation_policy_v4 import collect_documentation_evidence_v4
from .documentation_policy_v5 import collect_documentation_evidence_v5
from .errors import CollectionError, translate_write_once_error

__all__ = [
    "CollectionError",
    "DocumentationCollectionResult",
    "collect_documentation_evidence",
    "collect_documentation_evidence_v4",
    "collect_documentation_evidence_v5",
    "translate_write_once_error",
]
