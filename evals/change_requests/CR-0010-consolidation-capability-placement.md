# CR-0010 — Consolidation cannot say "not a product, and belongs to X"

## Status

Proposed — **defect qualified, one remedy measured and surviving, two eliminated.**
The measurement precondition set by the previous revision has been discharged.
Design C4 is recorded below with its measured results and its measured cost; it
is not authorised for implementation, because two blockers named in *Known
limitations* are unresolved and the registry surface is unclosed.

**Revision history of this document.** A first draft proposed one design as
settled and was withdrawn: its carrier claim was false, its scope item named one
registry surface where nine exist, and two acceptance criteria bound to model
output that had not been produced. A second revision recorded Designs A and B as
unselected candidates and named three things to measure. All three were measured.
**Both designs failed**, and the surviving design has a different shape than
either — it does not carry the parent at all. This revision folds that in.

**Number note.** `CR-0010` was previously assigned to a cross-source adjudication
proposal that was withdrawn and removed from disk, together with a `CR-0011` on
taxonomy adjudication. The number is reused deliberately; the withdrawn documents
are recorded in `evals/reports/2026-08-12-product-taxonomy-measurement-note.md`.

## Scope note — this proposes no edit to any frozen artefact

- `product_discovery_schema_v4`, `capability_discovery_schema_v3`,
  `task_discovery_schema_v1` and `product_consolidation_schema_v1` are
  byte-unchanged under this design, and were verified by hash before every run
  cited here. A frozen prompt is never edited; any change rides a successor.
- `srcsnap-hubspot-fy2024-sec-v1`, `-v2`, `-v3`, `ext-smoke-0009`,
  `cand-ext-smoke-0009-0001`, the product decision set built from it and the
  Snapshot A derived from that are byte-unchanged.
- `sec_html_item_span_v1` through `v4` are untouched. `v4` was exercised on 80
  firm-periods and one out-of-set firm without modification.
- The eight consolidation prototypes exist only under the executor scratchpad.
  None is registered, none is in the repository, and no output from any of them
  entered a decision set, snapshot or universe.

## Stage

`product_consolidation`.

## Observed gap

No action in `CONSOLIDATION_ACTIONS` can express *"this candidate is not a
product, and its parent is X."*

```python
_LINK_FIELDS = {
    "retain": (), "merge_alias": ("canonical_ref",),
    "place_family": ("family_ref",), "classify_bundle": ("constituent_refs",),
    "exclude": (), "unresolved": (),
}
```

`exclude` names `capability` among its four grounds but carries no link field.
`place_family` and `merge_alias` carry a parent and imply the child is itself a
product. A model that has judged a candidate a capability *and* identified its
parent must discard one of the two facts.

It discards producthood, consistently, and the symptom differs by firm:

- **HubSpot** — all four known capabilities take `place_family` with correct
  parents (`Payments` → `Commerce Hub`; three `Breeze` derivatives → `Breeze`).
  The tree is correct and every member is a family member, so `retained_count`
  is **1** for a firm with at least seven products.
- **ServiceNow** — all 31 `Now Assist for X` / `AI agents for X` candidates take
  `merge_alias`, with reasons stating *"indicating it is a feature or variant"*.
  Because `canonical_ref` means *the canonical form of this* and no field means
  *the product this belongs to*, 16 links point at the brand `Now Assist` and 15
  at `ServiceNow AI Platform`, none at the product the reason names.

The downstream consequence was measured, not inferred. All four mis-levelled
HubSpot entities entered `capability_extraction` as parents; each returned
exactly one capability restating its own definition, and one task doing the
same. The four task runs cost **6,134** microdollars in total
(`ext-smoke-task-0017`…`-0020`: 1,477 + 1,567 + 1,552 + 1,538, each the
`actual_cost_microdollars` recorded in that run's
`extraction_execution_outcome.json` under `extraction_execution_outcome@0.1.0`,
and each reproduced by `usage_cost_microdollars`, which rounds the two sides up
independently). The capability cost is not separable: `capability_extraction`
runs once per firm, with every product in a single packet.

## General failure class

A closed vocabulary whose members are individually correct but jointly
incomplete: every action is a defensible thing to say, and the set cannot say one
thing that is true. The model does not fail — it selects the least-wrong
available action, and the loss is silent because the output validates.

Same shape as ADR-069 and CR-0009 one stage on: the increment that adds a
judgement and the increment that lets the judgement be expressed are not the same
increment.

## Failing case IDs

None. No registered evaluation case exists for this stage and the harness has
never executed. The evidence is the exploratory runs recorded in
`evals/reports/2026-08-13-fifteen-firm-extraction-and-consolidation-note.md`
(C1–C7) and
`evals/reports/2026-08-13-longitudinal-panel-and-consolidation-design-search.md`
(D1–D8, V1–V4). Stated as a limitation, not offered as qualification.

## Expected behaviour

For a candidate the evidence shows is a capability of another candidate, the
stage records that it is **not a product**, and does so without discarding it
from the universe.

**Corrected from the previous revision.** That revision required the stage to
record *which candidate it belongs to*. That requirement is withdrawn, on
measured grounds: the parent is recoverable downstream and is more accurate when
rebuilt there than when carried (D6, V3 below). The stage's job is the level
judgement alone.

## The surviving design — C4

Six levels, one per candidate, **no link field of any kind**:

```text
family        a grouping label the firm uses for its offerings; the label
              itself is not sold
product       a separately purchasable offering
capability    a function of another offering, not sold on its own
variant       a tier or edition of another offering
not_offered   not offered by this firm in this period
unresolved    the evidence does not decide
```

The prompt forbids emitting `parent_ref` for any level. That prohibition is
definitional rather than conditional, and it held: **0 link leakage in 262
decisions across six firms** (D6).

### Measured results

Eight tracked cases, none of which should fall to `not_offered` — that level
removes a candidate from the universe entirely, reaching neither the capability
nor the task layer:

| candidate | v1 | C3 | **C4** |
|---|---|---|---|
| Security Operations products | not_offered | not_offered | **family** |
| Operational Technology Management products | not_offered | not_offered | **family** |
| Platform Privacy and Security products | not_offered | not_offered | **family** |
| Creator and Other products | not_offered | not_offered | **family** |
| Okta Platform | not_offered | not_offered | **family** |
| Auth0 Platform | not_offered | not_offered | **family** |
| customer platform | family | not_offered | **family** |
| Breeze | family | not_offered | **family** |

8/8 recovered. On HubSpot, all fifteen candidates match a single unadjudicated
reading made in the same session that designed C4 — the first time in eight
prototypes that any firm matched it fully:

```text
family        customer platform · Breeze
product       Smart CRM · Marketing / Sales / Service / Operations /
              Content / Commerce Hub                              (7)
capability    Payments · Breeze Copilot · Agents · Intelligence    (4)
not_offered   Clearbit · Cacheflow                                (2)
```

That reading is not a gold record and at least one of the fifteen is contested.
`docs/DECISION_LOG.md` records `Payments` as an open decision — standalone
product versus a named feature of Commerce Hub — and a second reading made the
same day places `Payments` and the three `Breeze` derivatives as products under
a `Breeze` family rather than as capabilities, an 11/15 match on the same
output. The disagreement is recorded, not resolved; it is one of the items a
gold adjudication would settle.

## Why the parent is not carried — the evidence for D6/V3

The ServiceNow capability run supplied **no links**: 28 product names and 101
passages, nothing else. Of 31 AI entities that consolidation had levelled
`capability`, **26 became capabilities and 22 attached to exactly the product
the filing names.** One sentence yields three correctly-parented capabilities:

```text
"Now Assist and AI agents for ITSM can help automate incident triage,
 generate summaries and provide intelligent resolution recommendations."
   → [IT Service Management] automate IT incident triage
   → [IT Service Management] generate summaries for IT incidents
   → [IT Service Management] provide intelligent resolution recommendations
```

Consolidation, asked to carry the parent, put 16 of these on a brand and 15 on a
platform. The capability stage, asked to read it from the sentence, got 22 of 31
right. **The stage that reads the passage attributes better than the stage that
guesses from a candidate list.** Removing the field did not lose a fact; it moved
the fact to where it is derived correctly.

The same holds functionally on HubSpot (V1). All four mis-levelled functions
survived relocation:

```text
Breeze Copilot's function       → Smart CRM     "boost productivity with an
                                                 AI-powered companion"
Breeze Agents' function         → Smart CRM     "automate work end-to-end"
Breeze Intelligence's function  → Smart CRM     "provide a complete and unified
                                                 view … through data enrichment"
Payments' function              → Commerce Hub  "accept electronic funds transfers"
                                                 + "create payment links"
```

Nothing was lost, `Payments` gained a second capability under the correct parent,
and the task count was unchanged at 64 from four fewer parents — task density
rising 5.8 → 9.1 per product. **The gain is structural, not numerical**, and this
discharges precondition 2 of the previous revision.

## The two eliminated designs

### Design B — `relation` field on `place_family` — ELIMINATED

Precondition 1 asked whether a structured field elicits the distinction that
prose showed. It does not: **it degrades it.** HubSpot's twelve `place_family`
reasons split 6 membership / 4 inclusion / 2 powering in prose — the correct
answer. The same model, given the field, returned 9 / 1 / 2. Structuring the
judgement changed the judgement, and in the wrong direction.

It did fix ServiceNow's 31 `merge_alias` cases, so it addressed a symptom. It
does not survive the firm it was designed on.

### Design A — `place_capability` action — ELIMINATED

Fixed HubSpot's three Breeze derivatives; broke `Breeze` itself, and moved
`Clearbit` and `Cacheflow` out of `exclude`. Produced 3 chain violations —
capabilities linked to candidates themselves placed as capabilities — against a
chain rule that had not been written. Its `place_family` count went 12 → 0 and
its `exclude` count 2 → 0: adding one action redistributed the whole vocabulary.

Precondition 3 asked each design to report the action distribution beside the v1
baseline. The question is dissolved rather than answered: C4 replaces the action
vocabulary with a level vocabulary, so there is no comparable distribution. The
finding that motivated the precondition survives and generalises — **there is no
bounded edit to this prompt** (D1). Four different kinds of change (a field, an
action, a relaxed rule, a restored level) each redistributed decisions outside
their target.

## Registry surface — nine places, not one

`product_consolidation` is absent from:

```text
manifests.py  SPEC_VERSION_FOR_STAGE                      (Python)
schemas/      extraction_input_packet.schema.json
              extraction_input_packet.v2.schema.json
              extraction_input_packet.v3.schema.json      <- written for this stage
              live_call_authorization.schema.json
              live_call_authorization_v2.schema.json
              adapter_enablement_record.schema.json
              extraction_non_run_record.schema.json
              extraction_provider_error_record.schema.json
```

Two are not latent. The artefacts of the one live consolidation run fail their
own schemas today:

```text
ext-smoke-cons-0001/inputs/extraction_input_packet.json
ext-smoke-cons-0001/inputs/live_call_authorization.json
  -> ['stage']: 'product_consolidation' is not one of [...]
```

`acc3449` closed five maps for this stage and its own message records the
pattern: *"a registered, tested stage could not mint a qualification record."*
Nine more surfaces of the same pattern remain, and closing them is prerequisite
to any design here.

## Out of scope, and why the scope boundary is uncomfortable

Two changes are excluded: making this stage's output reach the human decision,
and making Snapshot A read the consolidated universe.

**The 6,134 microdollars cited above is not stopped by this CR.** That cost arose
because the human decision did not see this stage's output, and this CR does not
change what the human sees. Cited as motivation, the number belongs to the
excluded work.

The argument for the ordering nonetheless: a judgement that cannot be expressed
cannot be carried, whatever the ordering. Move consolidation before the human
decision today and the human sees `place_family` on both `Marketing Hub` and
`Breeze Copilot` — the same ambiguity, one stage earlier. Expression precedes
plumbing. This is the first of at least three increments.

## Qualification basis — pre-evaluation, and stated as such

Bootstrap. No evaluation case, no threshold, no gate verdict. Every run cited is
exploratory and its packets were built outside the governed path, because
`pilot_packet.py` is pinned to one CIK and ADR-030 admits one firm. Nothing here
is a scored result.

## Known limitations

Two are blockers. The rest are recorded.

- **BLOCKER — `family` delivers nothing downstream, and the cost is now
  measured.** Capability and task observations flow only through `product`.
  Three ServiceNow passages whose subject C4 levelled `family` produced **zero**
  capabilities:

  ```text
  P23  Security Operations         "…natural language to interact with AI agents"
  P34  Platform Privacy & Security "auto-classifying data … recommending or
                                    initiating protective actions"
  P72  OT Management               "summarize incident history"
  ```

  Five AI entities and three concrete AI-action sentences fall outside the task
  universe as a direct consequence of four `family` decisions. C4 saves these
  candidates from `not_offered` but not from irrelevance, and neither C3 nor C4
  delivers them. The root cause is in the filing's grammar — ServiceNow writes
  *"IT Service Management … provides"* (singular) and *"Security Operations
  products help"* (plural) — and the firm's own site carries a page for Security
  Operations, so filing and site disagree, both being the firm's own statement.
  Eight prototypes indicate the answer is not in the level vocabulary.

- **BLOCKER — cross-cutting capabilities cannot be expressed.**
  `capability_observation.product_observation_id` is a single required string.
  HubSpot's filing states three times that Breeze spans all seven products
  (*"features across all our engagement hubs and the Smart CRM"*); all four AI
  capabilities attach to Smart CRM and the six Hubs carry none. This is a
  validity problem, not a counting one: the thesis measures AI-bearing tasks over
  all tasks, and a firm describing its AI layer once records one AI capability
  where a firm describing it per product records sixteen — same reality, an order
  of magnitude apart, and the difference is a writing choice. Not addressed by
  this CR; likely a separate CR against the capability schema.

- **`unresolved` is never selected** — 1,311 consolidation decisions across eight
  prototypes and six firms, zero (D7). `availability_status` is `S5` in 66/66 and
  150/150 capabilities and 64/64 tasks; `ambiguity` was populated 0/150 including
  four attributions the run could not resolve. Rule 7 is not obtainable by asking
  this model. Any design depending on the model declining to guess inherits this.

- **HubSpot's 15/15 is a calibration result.** It was the tuning firm in all
  eight rounds. The only blind measurement here broke the design's principal
  claim: `discovery.product_family` resolves 12/12 on HubSpot, 29/43 Adobe,
  23/56 ServiceNow, and is never populated on Datadog or Okta (D4).

- **One error survived every prototype.** `Automation Engine` is `not_offered` in
  all four C variants; ServiceNow's site carries `automation-engine.html`.

- **Purchasability evidence is present and unread** (C5). HubSpot's *"Each Hub
  can be used standalone… available in both free and paid tiers"* — the sentence
  that settles `retained_count = 1` — is cited by no decision in any run. A
  promotion rule on this signal is a separate CR.

- **Splicing is ~9.5× more common in this stage** than in discovery (C6);
  panel-wide the splicing class is 37/3,772 quotes (1.0%), doubled from the
  single-period 0.5%. Not touched.

- **The materializer's counters are asymmetric**: six collections, three
  counters. A level vocabulary changes the collection set entirely and the
  counter set must be settled in the same increment.

## Risks and trade-offs

- **A demotion is harder to reverse than an omission.** A candidate wrongly
  levelled `capability` leaves the product universe silently, and the human
  decision does not see it unless the excluded ordering change also lands.
- **`family` is a demotion with no downstream destination.** Until the first
  blocker is resolved, levelling something `family` is closer to `not_offered`
  than the level name suggests.
- **Removing the parent field trades an expressible fact for a re-derived one.**
  Measured at 22/31 exact on ServiceNow and 4/4 functionally on HubSpot; not
  measured anywhere else.
- **The design was selected on two firms and blind-tested on four.** The blind
  test measured level distribution and exclusion recovery, not correctness.

## Acceptance criteria — mechanism only

Model behaviour belongs in *Evaluation results*, not here.

1. `product_consolidation_schema_v1` and all three discovery prompts are
   byte-unchanged; asserted by test.
2. Every snapshot, extraction run, candidate collection, decision set and
   Snapshot A named in the scope note is byte-unchanged; asserted by test.
3. The successor output schema accepts an element carrying `level` from the
   six-member enum, and **rejects** an element carrying any `*_ref` link field.
4. The materializer routes each level into its own collection, and the counter
   set covers every collection.
5. `build_extraction_run(stage="product_consolidation", …)` completes and writes
   a run manifest, and the nine registry surfaces above accept the stage.
6. `ext-smoke-cons-0001`'s existing input artefacts validate against their
   schemas after the registry change.
7. Deterministic validation runs unchanged — quote containment, `D`/`P`
   resolution — plus: no output element carries a link field of any kind.
8. A v1 run over the same input reproduces its recorded decisions byte for byte.
9. The successor prompt is a new registered file; `product_consolidation_schema_v1`
   is not edited.

## Evaluation results

Not run against any evaluation case; the harness has never executed. The
exploratory results are in the two measurement notes named under *Failing case
IDs*, and the numbers reported above are drawn from them.

## Fixed cases

None yet.

## New regressions

None yet.

## Decision

Pending. Design C4 is the only surviving candidate and is not authorised: the two
blockers in *Known limitations* are unresolved, and no scored evaluation exists.

## Approval

Pending.
