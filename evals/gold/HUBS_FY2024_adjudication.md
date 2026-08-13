# HubSpot FY2024 — adjudication record

## What this is

The methodology owner's decisions on the points where three readings of one
source packet disagreed. Under `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`
the human researcher owns "creating and adjudicating gold examples", so these
decisions — not the readings — are what a gold assertion set is derived from.

`specs/SPEC-022-evaluation-data-model.md` requires a gold provenance record to
reference a disagreement/adjudication record. **No schema for one exists.** This
file is written in the shape that record needs and is the first instance; a
machine-readable contract for it is an open item.

| field | value |
|---|---|
| source packet | `data/runs/srcsnap-hubspot-20241231-sec-v4`, 16 passages |
| `source_id` | `CIK0001404655/sec_10k/2025-02-12/36257e638feb2059` |
| observation cutoff | 2025-02-12 (filing date) |
| analytical period | FY2024 (fiscal year ended 2024-12-31) |
| `guideline_version` | `8d134ad00f92a92972dee37dbf0f284fbef846657d4bc2f9ad3fdf4bed6b716f` |
| adjudicator | Hakan Zeki Gülmez (methodology owner) |
| adjudicated | 2026-08-13 |
| corpus arm | `item1_only` — the first arm of the ablation the ninety-day roadmap calls "Item 1 only versus enriched official corpus" |

## Inputs adjudicated

Three readings of the same packet, all recorded in `evals/gold/draft/`:

| reading | products | capabilities | tasks |
|---|---|---|---|
| pipeline, C4 consolidation + `capability_discovery_schema_v3` + `task_discovery_schema_v1` | 7 | 66 | 64 |
| executor session (context-contaminated) | 11 | 58 | 32 |
| Opus, clean brief | 14 | 69 | 22 |

Neither model reading is gold and the two are not independent of each other;
`evals/gold/draft/README.md` records why.

---

## Decision 1 — `HubSpot customer platform` is a family, not a product

**Evidence, P4:** "We provide a customer platform that helps businesses connect
and grow better."

| reading | position |
|---|---|
| pipeline C4 | `family` |
| executor | `family` |
| Opus | both `F1` family **and** `PR1` product |
| product decision set, 2026-08-05 | rejected — "an overarching platform description that already encompasses…" |

**Decided: `family`.** The ontology's exclusion list rules out "'AI' or
'platform' without an offering", and Opus's placement made an entity its own
parent, which the hierarchy does not permit.

## Decision 2 — `Breeze` is a family; its three derivatives are capabilities

**Evidence, P7:** "Breeze. Breeze is our AI that powers the customer platform,
including our Smart CRM, engagement Hubs, and the connected ecosystem." and
"Breeze includes Breeze Copilot, an AI-powered companion to boost productivity
and make work easier; Breeze Agents to help teams automate work, end-to-end,
from strategy to execution; and Breeze Intelligence, a data enrichment solution
to provide a complete and unified view of the customer…"

| reading | `Breeze` | derivatives |
|---|---|---|
| pipeline C4 | `family` | `capability` ×3 |
| executor | `family` | `product` ×3 |
| Opus | `product` | `product` ×3 |
| product decision set, 2026-08-05 | rejected as a family | accepted as products |

**Decided: `Breeze` = `family`, the three = `capability`.**

The adjudicator's reasoning, recorded in their words: Breeze is not a separately
purchasable product but a complementary AI layer inside the Hubs. Two things in
the packet carry that. The verb attached to Breeze is "powers" — the ontology
excludes internal technology and platform labels without an offering. And
"Breeze includes X, Y and Z" is the grouping construction the family level
exists for.

Decision 5 below closes the remaining question. A capability's canonical form is
a verb phrase; Breeze has no function phrase of its own in this packet, while
each of the three does. So Breeze cannot be a capability under the rule adopted
here, and the three can.

**Measured consequence, recorded because it cuts both ways.** In the chain that
treated the three as products, each returned exactly one capability restating
its own definition and one task doing the same, at 6,134 microdollars, and
`Breeze Copilot` returned no capability at all because the packet describes no
function for it. In the chain that treated them as capabilities, all three
functions survived and attached to `Smart CRM`.

**Unresolved, and this decision makes it visible rather than removing it.** The
packet says three times that Breeze spans everything — "features across all our
engagement hubs and the Smart CRM". `capability_observation.product_observation_id`
is a single required string, so the three attach to one product and the six Hubs
carry none. That is CR-0010's second blocker and it stays open.

## Decision 3 — `Payments` is a capability of `Commerce Hub`

**Evidence, P7:** "It includes an end-to-end payment solution, Payments, which
enables customers to accept electronic funds transfers (e.g. credit card
payments) from their customers in less time and with fewer tools."

| reading | position |
|---|---|
| pipeline C4 | `capability` |
| executor | `product`, flagged ambiguous |
| Opus | `product` |
| product decision set, 2026-08-05 | `product` |
| `docs/DECISION_LOG.md` | open decision, unresolved |

**Decided: `capability` of `Commerce Hub`.** The sentence places it inside
Commerce Hub. The strongest argument on the other side — that `Payments` alone
carries a dedicated risk-factor paragraph — rests on Item 1A, which is not in
this packet, so under the evidence rule it cannot support a gold record in the
`item1_only` arm. It may become admissible in the enriched arm.

This resolves the open decision recorded at `docs/DECISION_LOG.md` for the
`item1_only` arm and for no other.

## Decision 4 — `Professional services` is not a product

**Evidence, P16:** "We complement our product offerings with customer success,
support, and occasionally, professional services."

| reading | position |
|---|---|
| pipeline C4 | no candidate emitted |
| executor | not a product |
| Opus | `product`, family unknown |
| product decision set, 2026-08-05 | rejected — "A human-delivered training/consulting service, not a software function" |

**Decided: not a product.** The sentence draws the distinction itself: these
things *complement* the product offerings. The ontology does not state this, and
Decision 4a below closes that gap.

### Decision 4a — ontology addition

A human-delivered service — training, consulting, implementation, support — is
not a product unless the source establishes standalone commercial revenue for
it. To be written into `docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`
under a decision-log entry, per rule 8.

## Decision 5 — a capability's canonical form is a verb phrase

Item 1 writes `call tracking`; the registered prompt writes `track calls`. The
three readings recorded 58, 66 and 69 capabilities on the same packet, so the
rule governs the recorded **form**, not the count — the prompt verbalises each
noun one for one.

**Decided: verb phrase.** The ontology's five examples are all verb phrases
("generate images from text", "summarize a support case") while its definition
sentence does not require one; the rule lives in
`capability_discovery_schema_v3` and in no governing document. It is written
into the ontology, and `target_registry` identities take the verb form.

This closes the fourth Open-decisions entry added in `b587cc7`.

## Decision 6 — an acquired, unshipped function is recorded as `announced`

**Evidence, P15:** "The Company acquired Cacheflow, a leading B2B subscription
billing management and CPQ solution, to build these features directly into
Commerce Hub."

**Decided: recorded, `availability_status = announced`.**
`docs/TEMPORAL_POLICY.md` holds that "an acquired product is not treated as
integrated merely because the acquisition closed", and `announced` is the
roadmap value in the availability vocabulary. The firm stated the intention
publicly; nothing states the function shipped.

The FY2025 filing describes the same function as in customer hands — "AI-powered
configure-price-quote ("CPQ") capabilities". The pair is the transition
`SPEC-013` exists to classify, and recording the first end is what makes it
observable. The vocabulary is **not** widened; a ninth availability value was
considered and rejected as too costly for one case.

## Decision 7 — `ai_action_observed` is populated only for a concrete AI-performed action

The field is required by two schemas and requested by
`task_discovery_schema_v1`, and defined in no document under `docs/` or
`specs/`. The thesis's central measure rests on it.

**Decided.** The field is populated when the evidence sentence carries a
concrete verb and object **and** the actor performing it is the AI.

```text
"automate incident triage"                            populated
"generate summaries for IT incidents"                 populated
"an AI-powered companion to boost productivity"       not populated — adjective
"Breeze is our AI that powers the customer platform"  not populated — no action
"we apply AI in talent management"                    not populated — internal use
```

To be written into the ontology alongside Decision 5. This is the distinction
that produced the measured gap between two firms' AI density, and leaving it
unwritten would put it beyond annotator agreement.

---

## Resulting HubSpot FY2024 structure

```text
family        HubSpot customer platform · Breeze
product       Smart CRM · Marketing Hub · Sales Hub · Service Hub ·
              Operations Hub · Content Hub · Commerce Hub          (7)
capability    Payments · Breeze Copilot · Breeze Agents ·
              Breeze Intelligence + the per-product functions
not a product Professional services · Clearbit · Cacheflow
```

`Clearbit` and `Cacheflow` are acquisitions, recorded under Decision 6 rather
than as products.

## Known limitations

- **The independence requirement is not met.** Two of the three readings are
  Claude, one of them context-contaminated, and the adjudicator is a single
  person. `docs/methodology/VALIDATION_STRATEGY.md` asks for two independent
  annotators; this record has none, and a later revision should say whether that
  is remedied or accepted.
- **Scope is one firm, one period, one corpus arm.** Nothing here generalises to
  another firm, and the `item1_only` label is load-bearing: Decisions 3 and 6 in
  particular could change under the enriched arm.
- **No evaluation has been run against these decisions.** They are the input to a
  gold assertion set that does not yet exist.
- **Two decisions change a governing document.** Decisions 4a, 5 and 7 write into
  the ontology and require a decision-log entry and version increment under rule
  8. That edit is not made by this file.
- **One blocker is made visible, not resolved.** Decision 2 leaves Breeze's three
  capabilities attached to one product while the packet says they span seven.
