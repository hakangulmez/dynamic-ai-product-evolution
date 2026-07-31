"""The v0.3-only frozen documentation routes (ADR-039, E-C-D2).

**Why routes needed their own home.** Under ADR-037 and ADR-038 the frozen pairs
were declared inside ``documentation_receipt`` and mirrored in
``documentation_policy``. That was workable while the routes never changed. It
stopped being workable the moment one had to: the URLs are ``const``-pinned
inside both committed schema files (10 occurrences in v0.1, 52 in v0.2), and both
loaders deep-compare their committed file against a constructor that reads the
declaration. Editing the declaration in place would make **both** committed
schemas stop matching their own loaders, which would render both live receipts
unverifiable -- including ``docattempt-f88b54ac…``, whose preservation has been a
standing constraint. So the historical declaration stays exactly where it is,
describing the routes v0.1 and v0.2 were built against, and v0.3 reads its routes
from here instead.

**E1 is a hypothesis under test, not a validated target.** Its ``final_url`` is
the value the governed v0.2 receipt ``docattempt-c4082dd835f2f5228669487f50ca2308``
recorded as the observed ``Location`` when the previously frozen E1 final was
refused with ``redirect_location_mismatch``. That observation makes the value
*known*; it does not make it correct. Nothing here has been retrieved from it, no
content has been validated against it, and freezing it authorizes exactly one
separately governed attempt -- see ADR-039.

**E2 and E3 are copied byte-identically.** Their finals sit on the same apexes and
may be wrong in the same way, but a single observation about E1 is not evidence
about them. Transforming them by host/path pattern would be inference, which the
operating constitution forbids. They stay as they are until an attempt observes
otherwise.

**Exactly one hop, still.** Every pair's two URLs differ, so the route grammar
continues to require exactly one recognized redirect hop -- not "at most one". A
second redirect may be *observed* and recorded as a terminal observation; it is
never followed.
"""

from __future__ import annotations

__all__ = [
    "FROZEN_ROUTE_IDENTITIES",
    "ROUTE_CONTRACT",
    "ROUTE_SET_VERSION",
]

ROUTE_SET_VERSION = "0.3.0"
ROUTE_CONTRACT = "documentation_frozen_routes@0.3.0"

# Ordered and positional: entry i of every v0.3 receipt is pair i here.
FROZEN_ROUTE_IDENTITIES: tuple[dict[str, str], ...] = (
    {
        # E1: re-frozen by ADR-039. The final is the observed Location from
        # docattempt-c4082dd835f2f5228669487f50ca2308, carried here as a
        # hypothesis under one governed test. It is NOT validated content.
        "evidence_kind": "gemini_thinking",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/docs/thinking",
        "final_url": (
            "https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking"
        ),
    },
    {
        # E2: unchanged from ADR-037. No inference applied.
        "evidence_kind": "count_tokens",
        "requested_url": (
            "https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/"
            "get-token-count"
        ),
        "final_url": (
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/"
            "models/capabilities/get-token-count"
        ),
    },
    {
        # E3: unchanged from ADR-037. No inference applied.
        "evidence_kind": "pricing_standard",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/pricing",
        "final_url": (
            "https://cloud.google.com/gemini-enterprise-agent-platform/"
            "generative-ai/pricing"
        ),
    },
)
