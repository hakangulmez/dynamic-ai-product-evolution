"""The v0.5-only frozen documentation routes (ADR-041, E-C-D4).

**Why a fifth route module.** Each earlier route declaration is ``const``-pinned
inside its own committed schema, and each loader deep-compares that schema
against a constructor which reads the declaration. Editing one in place would
make its committed schema stop matching its own loader and its live receipt
unverifiable. Routes therefore succeed rather than mutate, as receipts, schemas
and policy sources now do.

**What v0.5 corrects: the chain is two hops, not one.** The governed v0.4 attempt
``docattempt-921cb253da290dc5dadadd5afc7244d6`` stopped at ``send2_evaluation``
with ``redirect_chain_too_long``. That is a *positive* observation: E1's send-one
hop was accepted -- the frozen intermediate was byte-exact -- and the intermediate
itself answered with a further redirect. The route is therefore two hops deep,
and the one-hop grammar could not express it.

**The second hop is a relative absolute-path reference.** It is not an absolute
URL, so it is accepted under a deliberately narrow grammar and resolved
mechanically against a **fixed** base declared here. Nothing is parsed out of the
observed value and reused as a base: the base is a constant, the raw path must be
byte-exact against the frozen declaration, and the join must reproduce the frozen
final URL byte-exactly or the entry refuses.

**Provenance is not uniform, and the receipt must not imply that it is.**

* **E1's second-hop Location** is a governed observation: the v0.4 stopped
  receipt recorded it. That receipt is raw evidence.
* **E2's and E3's chain information** is **human/agent-supplied design input,
  obtained with curl**. It is *not* governed raw evidence, and no receipt attests
  it. ADR-037 already rejected ``WebFetch`` as authoritative for redirect chains
  -- it summarises rather than reports, and reveals no hop structure. Curl output
  pasted into a design conversation is no better as provenance: it has no digest,
  no manifest and no attempt identity. Freezing these routes makes them
  **testable, not true**.

**v0.5 corrects route grammar only.** It collects no content evidence, and a
successful retrieval under it would still be retrieval status alone.

**No ``direct`` route kind exists here.** v0.4's direct semantics are not carried
forward: E3 is ``redirect_once``, whose two URLs differ, and every v0.5 route
performs at least one recognized hop.
"""

from __future__ import annotations

__all__ = [
    "FROZEN_ROUTE_IDENTITIES_V5",
    "RELATIVE_RESOLUTION_BASE",
    "ROUTE_CONTRACT_V5",
    "ROUTE_KINDS_V5",
    "ROUTE_SET_VERSION_V5",
    "SENDS_BY_ROUTE_KIND",
]

ROUTE_SET_VERSION_V5 = "0.5.0"
ROUTE_CONTRACT_V5 = "documentation_frozen_routes@0.5.0"

# The two declared kinds. ``direct`` is deliberately absent: every v0.5 route
# performs at least one recognized hop, so no entry may describe a bare fetch.
ROUTE_KINDS_V5: tuple[str, ...] = ("redirect_once", "redirect_twice_relative_path")

# Sends per kind. Two three-send routes and one two-send route give an attempt
# maximum of eight sends.
SENDS_BY_ROUTE_KIND: dict[str, int] = {
    "redirect_once": 2,
    "redirect_twice_relative_path": 3,
}

# The single fixed base a second-hop absolute-path reference is joined to. It is
# a declared constant, never derived from an observed value: parsing a base out
# of a response would let the server choose where the join lands.
RELATIVE_RESOLUTION_BASE = "https://docs.cloud.google.com"

# Ordered and positional: entry i of every v0.5 receipt is route i here.
FROZEN_ROUTE_IDENTITIES_V5: tuple[dict[str, str | None], ...] = (
    {
        # E1: the second-hop Location below is the value the governed v0.4
        # stopped receipt docattempt-921cb253da290dc5dadadd5afc7244d6 recorded.
        "evidence_kind": "gemini_thinking",
        "route_kind": "redirect_twice_relative_path",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/docs/thinking",
        "intermediate_url": (
            "https://docs.cloud.google.com/vertex-ai/generative-ai/docs/thinking"
        ),
        "second_hop_location": "/gemini-enterprise-agent-platform/models/thinking",
        "final_url": (
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/"
            "models/thinking"
        ),
    },
    {
        # E2: human/agent-supplied curl design input. Not governed raw evidence.
        "evidence_kind": "count_tokens",
        "route_kind": "redirect_twice_relative_path",
        "requested_url": (
            "https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/"
            "get-token-count"
        ),
        "intermediate_url": (
            "https://docs.cloud.google.com/vertex-ai/generative-ai/docs/multimodal/"
            "get-token-count"
        ),
        "second_hop_location": (
            "/gemini-enterprise-agent-platform/models/capabilities/get-token-count"
        ),
        "final_url": (
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/"
            "models/capabilities/get-token-count"
        ),
    },
    {
        # E3: human/agent-supplied curl design input. Not governed raw evidence.
        # One hop, to an absolute Location on the original apex.
        "evidence_kind": "pricing_standard",
        "route_kind": "redirect_once",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/pricing",
        "intermediate_url": None,
        "second_hop_location": None,
        "final_url": (
            "https://cloud.google.com/gemini-enterprise-agent-platform/"
            "generative-ai/pricing"
        ),
    },
)
