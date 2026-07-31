"""The v0.4-only frozen documentation routes (ADR-040, E-C-D3).

**Why a fourth route module.** ``documentation_routes.py`` is const-pinned into
the committed v0.3 schema, and ``validate_receipt_schema_v3_bytes`` deep-compares
that file against a constructor which reads it. Editing it would make the v0.3
schema stop matching its own loader. Routes therefore succeed rather than mutate,
exactly as receipts and schemas do.

**Route kinds are explicit.** v0.1-v0.3 assumed every route was one redirect hop,
which was expressible only because every pair's two URLs differed. E3 is now a
**direct** route whose requested and final URLs are identical, so the kind is
declared per entry rather than inferred from URL inequality:

* ``redirect_once`` -- exactly one recognized hop; two sends; the second send's
  URL must equal the frozen ``final_url``;
* ``direct`` -- one send only; an initial 200 is the sole success path; any 3xx
  is **recorded and refused without being followed**.

**Provenance is not uniform across these three routes, and must not be read as
if it were.**

* **E1** carries the target that governed receipt
  ``docattempt-c4082dd835f2f5228669487f50ca2308`` actually recorded as the
  observed ``Location``. That is a collector observation.
* **E2** and **E3** carry **human-supplied route hypotheses dated 2026-07-30**.
  They are not collector provenance and not raw-byte evidence: ADR-037 rejected
  ``WebFetch`` output as authoritative on measurement, because it returns
  model-summarised markdown with no digest and produced navigation shells for two
  of three pages during E-M0. Freezing them makes them *testable*, not *true*.

E2's target follows the same host swap E1's governed observation confirmed. That
is corroborating context, not evidence, and nothing here treats it as evidence.

**The superseded E3 final was never validated.** No attempt ever requested
``.../gemini-enterprise-agent-platform/generative-ai/pricing``; every run stopped
earlier. It is dropped rather than demoted to a second hop, which would be
treating an untested guess as a route.
"""

from __future__ import annotations

__all__ = [
    "FROZEN_ROUTE_IDENTITIES_V4",
    "ROUTE_CONTRACT_V4",
    "ROUTE_KINDS",
    "ROUTE_SET_VERSION_V4",
]

ROUTE_SET_VERSION_V4 = "0.4.0"
ROUTE_CONTRACT_V4 = "documentation_frozen_routes@0.4.0"

# The two declared route kinds. A pair is one or the other; nothing is inferred.
ROUTE_KINDS: tuple[str, ...] = ("direct", "redirect_once")

# Ordered and positional: entry i of every v0.4 receipt is pair i here.
FROZEN_ROUTE_IDENTITIES_V4: tuple[dict[str, str], ...] = (
    {
        # E1: unchanged from v0.3. Its final is the Location recorded by
        # docattempt-c4082dd835f2f5228669487f50ca2308 -- a governed observation.
        "evidence_kind": "gemini_thinking",
        "route_kind": "redirect_once",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/docs/thinking",
        "final_url": (
            "https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking"
        ),
    },
    {
        # E2: human-supplied hypothesis dated 2026-07-30. Not collector
        # provenance. Same host swap as E1, which corroborates but does not prove.
        "evidence_kind": "count_tokens",
        "route_kind": "redirect_once",
        "requested_url": (
            "https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/"
            "get-token-count"
        ),
        "final_url": (
            "https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/"
            "get-token-count"
        ),
    },
    {
        # E3: human-supplied hypothesis dated 2026-07-30, declared **direct**.
        # requested_url == final_url by contract; an initial 200 is the only
        # success path and no redirect is ever followed from here.
        "evidence_kind": "pricing_standard",
        "route_kind": "direct",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/pricing",
        "final_url": "https://cloud.google.com/vertex-ai/generative-ai/pricing",
    },
)
