# CR-0011 — Recording a firm-presented named AI system and its reach

## Status

Proposed — **gap qualified, six probes measured, no design selected.**

Nothing in this document is authorised for implementation. **Five of the six
probes are eliminated by their own measurements; one survives, defective.** This
document exists so that the surviving design can be argued about from
measurements rather than from expectations, and so that none of the six is run
again.

Every prompt executed is reproduced here in full, not as a diff, because a diff
against a frozen baseline does not show what the model was actually handed.

**The finding these probes converge on, stated once here.** An AI mechanism is
not a level in the commercial taxonomy. It is an **orthogonal role** — a
firm-presented named AI system — plus a **many-to-many relation** from that
system to governed product observations. Commercial entity level
(`family`/`product`/`capability`) and task-level transformation depth remain
separate constructs, and one entity can hold all three at once: Breeze is a
`family` commercially, a mechanism architecturally, and reaches seven products.
Probes 1 to 3 fail because they try to make these mutually exclusive.

**Two corrections of record.** A first version of this document said four probes
were eliminated and two survived; the probe sections themselves eliminate five.
It also reproduced Probe 3's prompt from a scratchpad file that differed from
the executed render in one line — the line naming the level count, which is the
experimental variable. The executed render is now what appears below. Neither
error changed a measurement; both made the record untrustworthy, which is the
only thing this document is for.

## Scope note — this proposes no edit to any frozen artefact

- `product_discovery_schema_v4`
  (`9fea11ceb77b83c05f11e98adc3dc3a54cf6a97a9c9cf2753d1eb691b3f74407`) and
  `product_consolidation_precision`
  (`a1578970bdbd5f034687e61ab98bd71ab89604b984a0023d5eed97f7c36a60fb`) are
  byte-unchanged. Two probes below are successors of the first and one is a
  successor of Design C4, which is itself unregistered.
- `capability_discovery_schema_v3` and `task_discovery_schema_v1` were not
  exercised by any probe here.
- `PROMPT_REGISTRY_VERSION` stays at `extraction_prompt_registry_v9`. No probe
  entered the registry and none has a position in `EXTRACTION_PROMPTS`.
- All six prompts exist only under a session scratchpad. No output from any of
  them entered a decision set, snapshot, product universe, gold record or
  target registry.
- The `srcsnap-*-sec-v4` packets consumed are byte-unchanged and were read, not
  written.

## Stage

`product_extraction`, at both its discovery and consolidation positions, plus a
probe stage that exists in no registry and is proposed as one of the two
surviving options.

---

## Observed gap

The pipeline is handed this sentence:

> "Breeze. Breeze is our AI that powers the customer platform, including our
> Smart CRM, engagement Hubs, and the connected ecosystem."
> — `P7`, HubSpot FY2024, `CIK0001404655/sec_10k/2025-02-12/36257e638feb2059`

It states two facts. HubSpot names Breeze and presents it as its AI. That AI
reaches the Smart CRM, the Hubs and the ecosystem.

The wording matters. The probes below were written around "the firm's own AI",
and *own* is a legal claim a business description cannot establish — a firm may
name and present a system it licenses. What the source supports is presentation,
not ownership. The probe prompts are reproduced as executed, with their original
wording; the correction applies to any successor.

The registered chain records neither. Discovery emits `Breeze` with
`entity_type: product`. Design C4 consolidation assigns `family`. Both are
answers to *what kind of thing is this*, and that is not the question the
sentence answers. The reach clause is discarded outright: the schema has no
field that can hold "this one thing is inside those seven things", and
`capability_observation.product_observation_id` is a single required string, so
even the derived capabilities attach to exactly one product.

`SPEC-017` states its own objective as measuring "availability, breadth, and
commercialization without conflation." Breadth is the component with no
carrier, and the sentence above is where its evidence lives.

The adjudication record already names this as open:

> "The packet says three times that Breeze spans everything — 'features across
> all our engagement hubs and the Smart CRM'. `capability_observation.product_observation_id`
> is a single required string, so the three attach to one product and the six
> Hubs carry none. That is CR-0010's second blocker and it stays open."
> — `evals/gold/HUBS_FY2024_adjudication.md`, Decision 2

`CR-0010` records the blocker. This document records what was measured against
it.

## General failure class

**A relation stated by the source has no carrier in the schema, so an extraction
stage that reads it correctly must discard it.**

The class is not about AI and not about HubSpot. It is the shape shared by every
statement of the form *X is inside Y*, where the pipeline records X and records
Y and has nowhere to put *inside*. `capability_observation.product_observation_id`
is the same defect at a different position: one required string where the source
supports many. `CR-0010`'s `exclude`-carries-no-link finding is a third instance.

Framing it as an AI question is what produced Probes 1 to 3, and all three
failed. The instructive part of this CR is that the failure was structural in
each case, not lexical.

## Failing case IDs

**None. No evaluation case exists for this behaviour, and that is the finding,
not an omission of this document.**

```text
evals/cases/dev/          empty for this stage
gold assertion set        does not exist for the reach relation
scoring_gate_config       does not exist
```

Under `SPEC-020` — "blocking gates are computed only on verified gold;
provisional-gold results are diagnostics" — every number in this document is a
diagnostic. Nothing here passed or failed a gate, because there is no gate.

The four firm-periods exercised are named here so they can be excluded from any
future blind set under ADR-015:

```text
CIK0001404655/sec_10k/2025-02-12    HUBS FY2024   ever-exposed
CIK0001373715/sec_10k/2026-01-29    NOW  FY2025   ever-exposed
CIK0000796343/sec_10k/2026-01-15    ADBE FY2025   ever-exposed
CIK0001561550/sec_10k/2026-02-18    DDOG FY2025   ever-exposed
```

## Why a variable and not a taxonomy repair

The methodology owner's framing, in their words:

> "breeze bir AI tool diye tanımlayıp hangi ürünlerde ne kadar deep kullanılıyor
> gibi bir tasarım daha iyi olmaz mıydı"

> "hem main product olmasından ayırırız hem de AI adoptionu yaratan sistemi
> detect ederiz, ileride breeze bizim için önemli bir variable olucak"

This asks for something the level vocabulary cannot express. A level says what a
candidate is. The request is for a relation between two candidates — *this AI is
inside that product* — and for that relation to be counted. Probes 1 to 3 test
whether the level vocabulary can carry it anyway. Probes 4 to 6 stop trying and
ask the relation directly.

## Instrument, identical across all six probes

```text
model                  gemini-2.5-flash  (Vertex AI, via the registered client)
temperature            0
top_p                  1
candidate_count        1
thinking_budget        0
response_mime_type     application/json
max_output_tokens      30,000            (raised from the registered 16,384)
input cap              50,000 tokens, enforced before each call
```

Source packets, all `sec_html_item_span_v4` normalisation, Item 1 only:

```text
HUBS   CIK0001404655/sec_10k/2025-02-12   cutoff 2025-02-12   FY2024
NOW    CIK0001373715/sec_10k/2026-01-29   cutoff 2026-01-29   FY2025
ADBE   CIK0000796343/sec_10k/2026-01-15   cutoff 2026-01-15   FY2025
DDOG   CIK0001561550/sec_10k/2026-02-18   cutoff 2026-02-18   FY2025
```

**The panel is not period-aligned.** HubSpot is a year behind the other three,
because the HubSpot FY2024 packet is the one the adjudication record covers.
Nothing below compares one firm's number to another's as a like-for-like
observation, and no cross-firm claim in this document depends on the periods
matching.

`DDOG` is the negative control throughout. Its filing names one AI offering and
makes no reach claim about it. A probe that finds a sprawling AI mechanism at
Datadog is over-firing.

## The six probes

```text
    probe   stage            what changed                          calls    cost µ$
    ─────   ─────            ────────────                          ─────    ───────
 1  pd5     discovery        entity_type values given definitions     10    260,975
 2  cp      discovery        new entity_type value `complementary`     5    110,509
 3  al      consolidation    new level `ai_layer`                      4    101,267
 4  cov     new probe        reach only, mechanism given by hand       3     18,569
 5  aim     new probe        mechanism and reach, both asked          4     31,825
 6  aim2    new probe        aim + a component de-duplication rule     4     26,795
                                                                    ───    ───────
                                                                     30    549,940
```

---

# Probe 1 — `pd5`: giving the `entity_type` values definitions

## Hypothesis

The registered discovery prompt lists five `entity_type` values and defines
none. If the model is told what each value means, it may find a place for an AI
layer without a new value being added.

## Change against the registered baseline

```diff
--- prompts/extraction/product_discovery_schema_v4.md
+++ pd_v5proto.md
@@ -72,7 +72,20 @@
 - `entity_type`: one of `product`, `product_family`, `bundle`, `plan`,
-  `candidate`.
+  `candidate`. This names what kind of thing the candidate is, not how
+  confident you are that it exists.
+  - `product` -- the offering defined above: something a customer can buy,
+    subscribe to, license, deploy, or use.
+  - `product_family` -- a stable commercial grouping the firm uses to
+    organize related products. It may correspond to a segment, cloud,
+    suite, or solution family. The grouping label itself is not sold, and
+    it is not automatically a product.
+  - `bundle` -- a packaged combination of offerings that are already named
+    separately in the evidence.
+  - `plan` -- a tier, edition, or plan of another offering rather than a
+    separate offering.
+  - `candidate` -- the evidence names the thing but does not establish
+    which of the above it is.
```

## Prompt executed, in full

`````markdown
# Product Discovery -- High Recall -- Schema v4

## Governing spec

`SPEC-008`

## System instruction

You are performing the high-recall discovery pass for a dated product
universe. Extract plausible customer-facing commercial offerings from the
supplied, temporally valid official source passages.

Do not score AI adoption, replicability, defensibility, quality, or business
success.

A product is an identifiable offering a customer can buy, subscribe to,
license, deploy, or use. Preserve uncertain candidates for later
consolidation.

Do not treat the following as products unless the evidence establishes a
distinct offering:

- strategy themes;
- generic "AI," "cloud," "platform," or "innovation" labels;
- internal technology;
- a bundle that only repackages listed products;
- a customer segment;
- a benefit statement.

## Input template

```text
COMPANY: {{company_name}}
OBSERVATION_CUTOFF: {{cutoff}}
SOURCE PASSAGES:
{{passages_with_ids}}
```

Each passage begins with a header of the form:

```text
[ref: P001] [passage_id: ...] [source_id: ...] [publication_date: ...]
```

Cite passages by their `ref` label only. Do not copy `passage_id` or
`source_id` into your output; they appear in the header for human readers and
are resolved downstream.

## Required output

Return a JSON array. Each element is one candidate object with exactly these
fields -- no other field, no wrapper object, no markdown fencing, no
commentary.

Required on every candidate:

- `product_observation_id`: a locally unique string for this candidate
  within this run only (e.g. `"cand-001"`, `"cand-002"`, ...). Do not
  attempt global uniqueness; that is derived downstream.
- `company_id`: copy `COMPANY` exactly as supplied.
- `observation_cutoff`: copy `OBSERVATION_CUTOFF` exactly as supplied.
- `product_name`
- `availability_status`: exactly one status **label** from the table below,
  for example `"S5"`. Never the status word itself.
- `confidence`: one of `high`, `medium`, `low`, `unknown`.
- `evidence`: array, at least one entry, each entry exactly
  `{"ref": ..., "quote": ...}`.

Include only when the evidence supports it, otherwise omit (never invent a
value):

- `product_family`
- `normalized_name`
- `entity_type`: one of `product`, `product_family`, `bundle`, `plan`,
  `candidate`. This names what kind of thing the candidate is, not how
  confident you are that it exists.
  - `product` -- the offering defined above: something a customer can buy,
    subscribe to, license, deploy, or use.
  - `product_family` -- a stable commercial grouping the firm uses to
    organize related products. It may correspond to a segment, cloud,
    suite, or solution family. The grouping label itself is not sold, and
    it is not automatically a product.
  - `bundle` -- a packaged combination of offerings that are already named
    separately in the evidence.
  - `plan` -- a tier, edition, or plan of another offering rather than a
    separate offering.
  - `candidate` -- the evidence names the thing but does not establish
    which of the above it is.
- `target_customers`: array of strings.
- `ambiguity`: a short note when packaging or scope is uncertain.

### `evidence` -- how to cite

Each evidence entry has exactly two fields and no others:

- `ref`: the label of one passage shown above, copied exactly as it appears
  in that passage's header -- the letter `P` followed by at least three
  digits, for example `"P001"` or `"P042"`.
- `quote`: text quoted verbatim from that same passage.

Binding rules:

- Use only `ref` labels that appear in the SOURCE PASSAGES above. Do not
  invent a label, do not guess a number, and do not cite a passage you were
  not shown.
- The `quote` must come from the passage that `ref` names, not from a
  neighbouring one.
- Never emit `source_id` or `passage_id`. An entry carrying either is
  rejected.

### `availability_status` -- closed vocabulary

Do not write a status word. Emit the short **label** for the status you mean:

```text
  S1  =  announced
  S2  =  broadly_deployed_or_default
  S3  =  deprecated
  S4  =  discontinued
  S5  =  general_availability
  S6  =  private_beta
  S7  =  public_beta
  S8  =  unknown
```

The eight statuses these labels stand for are the closed vocabulary below. Read
them to decide which one applies; emit only the label. A status word written out
in full is rejected, and there is no ninth status -- never `planned`.

```
active_status_values           : broadly_deployed_or_default, general_availability,
                                  private_beta, public_beta
roadmap_status_values          : announced
non_active_known_status_values : deprecated, discontinued
unknown_status_values          : unknown
```

`active_status_values` means the evidence supports the offering being
available now, in general availability or a named beta -- not that it is
automatically accepted, not that the product universe is complete, and not
that a customer task has moved to it. If the evidence does not establish
which of the seven other tokens applies, use the label for `unknown`. Do not
guess.

## Silent final check

- Every candidate is customer-facing.
- Every candidate has at least one evidence entry.
- Every `ref` is a label that appears in the SOURCE PASSAGES above.
- No evidence entry carries `source_id` or `passage_id`.
- No source is after the cutoff.
- `availability_status` is a label from the table (`S1`-`S8`), not a word.
- Uncertain packaging remains flagged via `ambiguity`, not resolved.
`````

## Result

Ten firms. Candidate counts against the registered v4 baseline on the four
firms where a baseline exists:

```text
           v4 baseline    pd5
HUBS               15      15
NOW                71      38      −33
ADBE               62      63      +1
DDOG               45      45
```

The other six firms ran without a baseline to compare against: `OKTA` 42,
`SNOW` 43, `TEAM` 32, `INTU` 42, `PANW` 40, `CRWD` 44.

**On the target case the change did nothing.** `Breeze`, `Breeze Copilot`,
`Breeze Agents` and `Breeze Intelligence` were all emitted as
`entity_type: product`, exactly as under the registered prompt. Definitions
moved no AI candidate anywhere.

**The ServiceNow drop is not what it looks like, and an earlier reading of it
recorded in conversation was wrong.** Decomposing the 71 baseline candidates:

```text
  31   `Now Assist for X` / `AI agents for X`      one pair per service domain
  40   everything else
```

and the same decomposition of what `pd5` kept:

```text
  per-domain AI rows kept    0 / 31
  all other candidates kept  35 / 40
  lost besides the AI rows   Creator and Other products
                             Security Operations products
                             Platform Privacy and Security products
                             Operational Technology Management products
                             Automation Engine
```

The model replaced all 31 per-domain rows with three: `Now Assist`,
`ServiceNow AI Platform`, `RaptorDB`. That is de-duplication, not recall loss.
It is also, unprompted, the exact operation Probe 6 later has to be told to
perform.

## Verdict — eliminated, with one finding carried forward

Eliminated: zero effect on the target case, and five genuine umbrella products
lost as collateral. Carried forward: a definition-bearing discovery prompt
collapses per-domain AI instances on its own, and **discards which domains they
covered while doing it**. Collapsing without recording the coverage destroys
precisely the variable this CR is about.

---

# Probe 2 — `cp`: a `complementary` value at discovery

## Hypothesis

The methodology owner's original description of Breeze was "tamamen HubSpot
platformunu tamamlayan tamamlayıcı (complementary) bir yapay zeka katmanı." If
the vocabulary carries a `complementary` value defined by non-separability,
Breeze should take it.

## Change against the registered baseline

```diff
--- prompts/extraction/product_discovery_schema_v4.md
+++ pd_comp_proto.md
@@ -72,7 +72,11 @@
 - `entity_type`: one of `product`, `product_family`, `bundle`, `plan`,
-  `candidate`.
+  `complementary`, `candidate`. Use `complementary` for an offering the
+  passages describe only alongside the firm's other offerings and never
+  describe as obtainable on its own. If any passage says it is sold,
+  subscribed to, offered free, or otherwise available by itself, it is a
+  `product`.
```

## Prompt executed, in full

`````markdown
# Product Discovery -- High Recall -- Schema v4

## Governing spec

`SPEC-008`

## System instruction

You are performing the high-recall discovery pass for a dated product
universe. Extract plausible customer-facing commercial offerings from the
supplied, temporally valid official source passages.

Do not score AI adoption, replicability, defensibility, quality, or business
success.

A product is an identifiable offering a customer can buy, subscribe to,
license, deploy, or use. Preserve uncertain candidates for later
consolidation.

Do not treat the following as products unless the evidence establishes a
distinct offering:

- strategy themes;
- generic "AI," "cloud," "platform," or "innovation" labels;
- internal technology;
- a bundle that only repackages listed products;
- a customer segment;
- a benefit statement.

## Input template

```text
COMPANY: {{company_name}}
OBSERVATION_CUTOFF: {{cutoff}}
SOURCE PASSAGES:
{{passages_with_ids}}
```

Each passage begins with a header of the form:

```text
[ref: P001] [passage_id: ...] [source_id: ...] [publication_date: ...]
```

Cite passages by their `ref` label only. Do not copy `passage_id` or
`source_id` into your output; they appear in the header for human readers and
are resolved downstream.

## Required output

Return a JSON array. Each element is one candidate object with exactly these
fields -- no other field, no wrapper object, no markdown fencing, no
commentary.

Required on every candidate:

- `product_observation_id`: a locally unique string for this candidate
  within this run only (e.g. `"cand-001"`, `"cand-002"`, ...). Do not
  attempt global uniqueness; that is derived downstream.
- `company_id`: copy `COMPANY` exactly as supplied.
- `observation_cutoff`: copy `OBSERVATION_CUTOFF` exactly as supplied.
- `product_name`
- `availability_status`: exactly one status **label** from the table below,
  for example `"S5"`. Never the status word itself.
- `confidence`: one of `high`, `medium`, `low`, `unknown`.
- `evidence`: array, at least one entry, each entry exactly
  `{"ref": ..., "quote": ...}`.

Include only when the evidence supports it, otherwise omit (never invent a
value):

- `product_family`
- `normalized_name`
- `entity_type`: one of `product`, `product_family`, `bundle`, `plan`,
  `complementary`, `candidate`. Use `complementary` for an offering the
  passages describe only alongside the firm's other offerings and never
  describe as obtainable on its own. If any passage says it is sold,
  subscribed to, offered free, or otherwise available by itself, it is a
  `product`.
- `target_customers`: array of strings.
- `ambiguity`: a short note when packaging or scope is uncertain.

### `evidence` -- how to cite

Each evidence entry has exactly two fields and no others:

- `ref`: the label of one passage shown above, copied exactly as it appears
  in that passage's header -- the letter `P` followed by at least three
  digits, for example `"P001"` or `"P042"`.
- `quote`: text quoted verbatim from that same passage.

Binding rules:

- Use only `ref` labels that appear in the SOURCE PASSAGES above. Do not
  invent a label, do not guess a number, and do not cite a passage you were
  not shown.
- The `quote` must come from the passage that `ref` names, not from a
  neighbouring one.
- Never emit `source_id` or `passage_id`. An entry carrying either is
  rejected.

### `availability_status` -- closed vocabulary

Do not write a status word. Emit the short **label** for the status you mean:

```text
  S1  =  announced
  S2  =  broadly_deployed_or_default
  S3  =  deprecated
  S4  =  discontinued
  S5  =  general_availability
  S6  =  private_beta
  S7  =  public_beta
  S8  =  unknown
```

The eight statuses these labels stand for are the closed vocabulary below. Read
them to decide which one applies; emit only the label. A status word written out
in full is rejected, and there is no ninth status -- never `planned`.

```
active_status_values           : broadly_deployed_or_default, general_availability,
                                  private_beta, public_beta
roadmap_status_values          : announced
non_active_known_status_values : deprecated, discontinued
unknown_status_values          : unknown
```

`active_status_values` means the evidence supports the offering being
available now, in general availability or a named beta -- not that it is
automatically accepted, not that the product universe is complete, and not
that a customer task has moved to it. If the evidence does not establish
which of the seven other tokens applies, use the label for `unknown`. Do not
guess.

## Silent final check

- Every candidate is customer-facing.
- Every candidate has at least one evidence entry.
- Every `ref` is a label that appears in the SOURCE PASSAGES above.
- No evidence entry carries `source_id` or `passage_id`.
- No source is after the cutoff.
- `availability_status` is a label from the table (`S1`-`S8`), not a word.
- Uncertain packaging remains flagged via `ambiguity`, not resolved.
`````

## Result

Five firms. Counts:

```text
           v4 baseline     cp
HUBS               15      15
NOW                71      39      −32
ADBE               62      65      +3
DDOG               45      45
MDB                 —      20
```

The ServiceNow decomposition is cleaner than Probe 1's:

```text
  per-domain AI rows kept    0 / 31
  all other candidates kept  39 / 40      (only `Automation Engine` lost)
```

**Where the new value actually went, in every firm:**

```text
HUBS   2   Clearbit · Cacheflow                                    acquisitions
NOW    5   Customer Support · Professional Services ·
           ServiceNow Impact · ServiceNow University ·
           RiseUp with ServiceNow                                  services / training
ADBE   4   Consulting Services · Customer Success Account
           Management · Technical Support · Digital Learning
           Solutions                                               services / training
MDB    3   Analytics Integrations · Voyage AI's embedding and
           reranking models · MongoDB University                   mixed
DDOG   0   —
```

**Fourteen assignments across five firms, and not one of them is an AI layer.**
`Breeze` was emitted as `entity_type: product`, and so were its three
derivatives. The value was taken up readily and consistently — by human-delivered
services, training programmes, and acquisitions.

## Verdict — eliminated

The value works; it names a real and coherent population, and that population is
the one Adjudication Decision 4a is about. It is simply not the population this
CR needs. Zero targeting accuracy on the intended case across five firms.

If `complementary` is ever revisited it should be revisited as a *services*
question under Decision 4a, not as an AI question. The methodology owner has
held this item open explicitly ("bu adımı boşverelim şimdilik ben sonra
hatırlatıcam"), and this measurement is the reason it should return under a
different heading.

---

# Probe 3 — `al`: an `ai_layer` level at consolidation

## Hypothesis

Discovery is a high-recall stage that should not be adjudicating. Consolidation
already assigns one level per candidate with evidence. Adding a seventh level
puts the judgement where the judgements are.

## Change against Design C4

C4 is the eighth consolidation prototype and is itself unregistered; the
registered `product_consolidation_precision` is a five-line stub that predates
it. The diff below is against C4, since that is the actual base.

```diff
--- c4 (unregistered)
+++ rel_prompt_ailayer.md
@@ system instruction, level list
 - `capability` -- a function that sits inside a product rather than being sold
   on its own.
+- `ai_layer` -- an offering the passages describe as the firm's own AI,
+  delivering AI function across the firm's other offerings rather than being
+  one of them.
@@ required output
-- `level`: exactly one of `family`, `product`, `capability`, `variant`,
-  `not_offered`, `unresolved`.
+- `level`: exactly one of `family`, `product`, `capability`, `ai_layer`,
+  `variant`, `not_offered`, `unresolved`.
@@ silent final check
-- Every `level` is one of the six words.
+- Every `level` is one of the seven words.
```

## Prompt executed, in full

`````markdown
# Product Consolidation -- High Precision -- Schema v1

## Governing spec

`SPEC-008`

## System instruction

You are consolidating high-recall product candidates into a precise dated
product universe. Use only the candidates and the source passages supplied
below. Add nothing from outside them.

For each candidate you must assign exactly one level, describing what the
candidate **is** -- not how it relates to another candidate:

- `family` -- a grouping label the firm uses for its offerings; the label
  itself is not sold.
- `product` -- an offering a customer can buy, subscribe to, license, deploy,
  or use.
- `capability` -- a function that sits inside a product rather than being sold
  on its own.
- `ai_layer` -- an offering the passages describe as the firm's own AI,
  delivering AI function across the firm's other offerings rather than being
  one of them.
- `variant` -- a delivery variant, edition, or price tier of another candidate
  rather than a distinct offering.
- `not_offered` -- not a customer-facing offering at all: strategy, internal
  technology, an acquired company, an unsupported roadmap item, or a
  **support, implementation, training, onboarding, customization, or
  managed-services wrapper** unless the passages show it sold on its own
  terms.
- `unresolved` -- the evidence does not settle which level applies.

Ask what the candidate is on its own terms. The parent follows from the level;
it is not the judgement.

A bundle becomes a distinct product only when it creates a customer-facing
cross-product workflow or commercial experience that the constituent products
do not represent on their own. A label that merely groups other products is a
family, not a bundle.

`unresolved` is a real answer, not a failure. Use it when the evidence supports
more than one action and does not choose between them. Do not guess an action
to avoid leaving a case open.

Do not use future measurement concepts. Do not score adoption, replicability,
defensibility, quality or business success. AI terms receive no special status.

## Input template

```text
COMPANY: {{company_name}}
OBSERVATION_CUTOFF: {{cutoff}}

PRODUCT CANDIDATES:
{{product_candidates}}

SOURCE PASSAGES:
{{passages_with_ids}}
```

Each candidate begins with a header of the form:

```text
[ref: D1] [entity_type: ...] [availability_status: ...]
```

followed by its product name on the next line.

Each passage begins with a header of the form:

```text
[ref: P1] [passage_id: ...] [source_id: ...] [publication_date: ...]
```

Cite candidates and passages by their `ref` labels only. Do not copy
`passage_id`, `source_id`, `product_observation_id` or `normalized_name` into
your output; they appear in the headers for human readers and are resolved
downstream.

## Required output

Return a JSON array with **exactly one element per candidate shown above**, in
any order -- no other field, no wrapper object, no markdown fencing, no
commentary. Every candidate gets exactly one decision; a candidate you do not
mention is an error, and a candidate mentioned twice is an error.

Required on every element:

- `ref`: the candidate's label, copied exactly -- the letter `D` followed by
  its position number, written with no fixed width and no leading zeros:
  `"D1"`, `"D12"`.
- `level`: exactly one of `family`, `product`, `capability`, `ai_layer`,
  `variant`, `not_offered`, `unresolved`.
- `reason`: one or two sentences saying why, in your own words.
- `evidence`: array, at least one entry, each entry exactly
  `{"ref": ..., "quote": ...}`.

Required only for the level named, and forbidden on every other level:

- `unresolved` -> `open_question`: one sentence naming what the evidence does
  not settle.

Do not emit `parent_ref`, `family_ref`, `canonical_ref` or any other link
field. This stage assigns a level and nothing else; the parent relationship is
carried elsewhere and is not your decision here.

Emit no other field. Do **not** emit `product_name`, `product_observation_id`,
`availability_status`, `entity_type`, `company_id`, `observation_cutoff` or any
identifier: the retained observation is assembled downstream from the candidate
you referenced, carried through unchanged. An element carrying any of them is
rejected.

### `evidence` -- how to cite

Each evidence entry has exactly two fields and no others:

- `ref`: the label of one passage shown above, copied exactly -- the letter `P`
  followed by that passage's position number, written with no fixed width and
  no leading zeros: `"P1"`, `"P16"`.
- `quote`: text quoted verbatim from that same passage. Quote **1 to 3
  sentences** -- the run that supports your decision, not the whole passage.

Binding rules:

- Use only `ref` labels that appear in the SOURCE PASSAGES block. Do not invent
  a label, do not guess a number, and do not cite a passage you were not shown.
- The `quote` must come from the passage that `ref` names.
- Copy the words exactly as they appear, without joining text across a gap. If
  the words you need are separated by other text, quote the shorter run that is
  contiguous, or cite a different passage.
- An exclusion needs evidence too. Quote the text that shows the candidate is
  strategy, a capability, internal technology, or an unsupported roadmap item.
- Never emit `source_id` or `passage_id`. An entry carrying either is rejected.

## Silent final check

- Exactly one element per candidate, no candidate missing, none repeated.
- Every `level` is one of the seven words.
- Every `ref` is a `D` label shown above.
- No element carries `parent_ref`, `family_ref`, `canonical_ref` or any other
  link field.
- Every evidence `ref` is a `P` label shown above.
- Every `quote` is 1 to 3 sentences, contiguous, and copied exactly.
- No element carries a name, a status, an identifier, `source_id` or
  `passage_id`.
- A case the evidence does not settle is `unresolved`, not a guess.
`````

## Result

Four firms. Candidate counts are unchanged by construction — consolidation
returns one element per candidate — so the measurement is *which* levels moved.

```text
HUBS    ai_layer: Breeze                                     1 level changed
        Breeze                              family → ai_layer

DDOG    ai_layer: none                                       7 levels changed
        Data Streams Monitoring            product → capability
        Data Jobs Monitoring (DJM)         product → capability
        App Builder                        product → capability
        Data Observability                  family → product
        Cloud Security                      family → product
        Threat Management                   family → product
        CI Visibility                       family → product

NOW     ai_layer: Now Assist · RaptorDB ·                    4 levels changed
                  ServiceNow AI Platform
        Now Assist                      capability → ai_layer
        RaptorDB                           product → ai_layer
        ServiceNow AI Platform             product → ai_layer
        ServiceNow Impact              not_offered → product

ADBE    ai_layer: Adobe Agent Orchestrator                   2 levels changed
        Adobe Agent Orchestrator        capability → ai_layer
        Adobe Acrobat Sign                 product → unresolved
```

**What worked.** Breeze moved cleanly and is the only `ai_layer` at HubSpot.
Datadog, the control, received no `ai_layer` at all.

**What failed.** Three separate defects, each independently sufficient to
disqualify the design as it stands.

1. **`RaptorDB` is a false positive.** It is ServiceNow's database, not its AI.
   The level's own words — "the firm's own AI" — did not exclude it.

2. **Fourteen collateral level changes across four firms, thirteen of them
   nowhere near AI.** Datadog alone moved seven, converting three families to
   products and three products to capabilities, on a filing where the new level
   was never used. This is the seventh independent measurement of the same
   effect first recorded as D1: *a vocabulary change at either extraction stage
   redistributes decisions well beyond its target.* `Adobe Acrobat Sign` falling
   from `product` to `unresolved` is the same effect on a case with no AI
   content whatsoever.

3. **A level cannot express reach.** Even where `ai_layer` is assigned
   correctly, the output says Breeze is an AI layer and says nothing about
   what it is a layer *over*. The prompt forbids `parent_ref` and every other
   link field, by design. The variable is still not recorded.

Naming was deliberately held constant in this probe. The methodology owner had
raised `ai_mechanism` as the better word, and the decision taken at the time was
to keep `ai_layer` for comparability and test the naming question separately
rather than change it mid-run. Probes 5 and 6 use `mechanism` and do not use the
level vocabulary at all, so the naming question is now moot for the surviving
designs.

## Verdict — eliminated on defect 3, independently of the other two

Defects 1 and 2 might be fixable by wording. Defect 3 is structural: the level
field answers *what is this*, and reach is *what is this inside*. No amount of
level-vocabulary work produces a coverage number.

---

# Probe 4 — `cov`: reach only, with the mechanism supplied by hand

## Hypothesis

Split the problem. If the mechanism is named for the model, does it read the
reach correctly? This isolates whether the failure is in finding the AI or in
reading its span.

## Prompt executed, in full

The mechanism was hard-coded per firm. `D10 (Breeze)` is shown; the ServiceNow
and Adobe renders named their own candidate in the same slot.

`````markdown
# AI Mechanism Coverage — probe

## Task

One candidate below has been identified as the firm's own AI: it is named
`D10 (Breeze)`. Your only job is to say **which of the other candidates the passages
place that AI inside**, and how the passages say it.

Do not re-judge whether `D10 (Breeze)` is a product. Do not judge any other
candidate's level. Add nothing from outside the passages shown.

## Input

```text
COMPANY: {{company_name}}
OBSERVATION_CUTOFF: {{cutoff}}

PRODUCT CANDIDATES:
{{product_candidates}}

SOURCE PASSAGES:
{{passages_with_ids}}
```

## Required output

Return one JSON object -- no array, no wrapper, no markdown fencing, no
commentary -- with exactly these fields:

- `mechanism`: the `D` label of the named AI candidate, copied exactly.
- `covered_refs`: array of `D` labels of the candidates the passages place the
  AI inside, on, or across. Empty array if the passages name none.
- `claim_type`: exactly one of
  - `enumerated` -- the passages name the covered offerings individually.
  - `categorical` -- the passages cover them by a group word ("all our
    engagement hubs", "across our solutions") without naming each.
  - `mixed` -- both forms appear.
  - `unstated` -- the passages do not say what the AI reaches.
- `evidence`: array, at least one entry, each entry exactly
  `{{"ref": ..., "quote": ...}}`.

### `evidence` -- how to cite

- `ref`: the label of one passage shown above, copied exactly.
- `quote`: 1 to 3 contiguous sentences copied verbatim from that passage.
- Quote the sentence that states the coverage. If no passage states it,
  `claim_type` is `unstated` and the quote is the sentence that names the AI.
- Never emit `source_id` or `passage_id`.

## Silent final check

- `mechanism` is a `D` label shown above.
- Every entry in `covered_refs` is a `D` label shown above, and `mechanism`
  is not among them.
- `claim_type` is one of the four words.
- Every evidence `ref` is a `P` label shown above and every quote is copied
  exactly.
- A coverage you cannot point at in a passage is not listed. `unstated` is a
  first-class answer, not a failure.
`````

## Result

```text
HUBS   Breeze                     covered 8    correct
NOW    ServiceNow AI Platform     covered 5    ─
ADBE   Adobe Experience Platform  covered 1 / 62
```

HubSpot answered correctly and immediately: given the mechanism, the model reads
the reach out of the filing without difficulty.

**Adobe returned 1 of 62 because the probe named the wrong entity.** The
mechanism was hand-picked from the C4 output and `Adobe Experience Platform` is
not Adobe's AI — Firefly is. The measurement is not evidence about Adobe; it is
evidence about the design.

## Verdict — eliminated, and it eliminates itself

Hand-supplying the mechanism moves the hardest judgement out of the instrument
and into the operator, where it is unauditable and — as this run demonstrates on
its own second data point — wrong. A design that requires the analyst to already
know each firm's AI cannot be run over a universe.

What it did establish, cheaply, at 18,569 microdollars: **the reach question is
answerable from Item 1 alone.** That result is what justified Probes 5 and 6.

---

# Probe 5 — `aim`: ask both questions

## Hypothesis

Ask the model to find the mechanism and state its reach, in two questions, with
no level vocabulary and no product judgement. Report the form of the reach claim
so a categorical claim is distinguishable from an enumerated one.

## Prompt executed, in full

`````markdown
# AI mechanism and its reach — probe

## Task

Answer two questions about the candidates and passages below, and nothing else.
Do not assign a level to any candidate. Do not judge whether anything is a
product. Add nothing from outside the passages shown.

**Question 1.** Which candidates, if any, do the passages present as the firm's
**own AI** -- an AI the firm names and owns, described as delivering AI
function to the firm's offerings? A firm may name none, one, or several. A
candidate that merely has AI features is not itself an AI mechanism; the
passages must present the candidate as the AI.

**Question 2.** For each mechanism from Question 1, which of the other
candidates do the passages place that AI inside, on, or across?

If a passage states the reach by a group word -- "all our engagement hubs",
"across our solutions" -- and another passage names that group's members, list
the named members. If no passage names them, list none and say the claim was
categorical.

## Input

```text
COMPANY: {{company_name}}
OBSERVATION_CUTOFF: {{cutoff}}

PRODUCT CANDIDATES:
{{product_candidates}}

SOURCE PASSAGES:
{{passages_with_ids}}
```

## Required output

Return a JSON array -- no wrapper object, no markdown fencing, no commentary --
with one element per mechanism found. An empty array is a valid and expected
answer for a firm that names no AI of its own.

Each element has exactly these fields:

- `mechanism_ref`: the `D` label of the AI candidate, copied exactly.
- `covered_refs`: array of `D` labels the passages place the AI inside, on or
  across. Empty array if the passages name none. `mechanism_ref` must not
  appear in it.
- `claim_type`: exactly one of
  - `enumerated` -- the passages name the covered offerings individually.
  - `categorical` -- a group word only, with no passage naming the members.
  - `mixed` -- both forms appear.
  - `unstated` -- the passages do not say what the AI reaches.
- `evidence`: array, at least one entry, each entry exactly
  `{{"ref": ..., "quote": ...}}`. Include the sentence that names the AI and,
  when the reach is stated, the sentence that states it.

### `evidence` -- how to cite

- `ref`: the label of one passage shown above, copied exactly.
- `quote`: 1 to 3 contiguous sentences copied verbatim from that passage.
- Never emit `source_id` or `passage_id`.

## Silent final check

- Every `mechanism_ref` and every entry in `covered_refs` is a `D` label shown
  above.
- No mechanism covers itself.
- `claim_type` is one of the four words.
- Every evidence `ref` is a `P` label shown above and every quote is copied
  exactly.
- A reach you cannot point at in a passage is not listed.
- An empty array is a real answer. Do not invent a mechanism to fill it.
`````

## Result

```text
        mechanisms found
HUBS     4
DDOG     1        Bits AI SRE, reach 0        control held
NOW     18
ADBE     6
```

Firefly was found at Adobe without being named — the failure Probe 4 could not
avoid is gone. The Commerce Hub misattribution seen in earlier runs did not
recur.

The usable reading, before correction:

```text
firm         mechanism        reach   products   ratio
HubSpot      Breeze              8        7      7/7 = 100%
ServiceNow   Now Assist         19       28     19/28 =  68%
Adobe        Firefly            10       47      ~6/47 = 13%
Datadog      Bits AI SRE         0       33      0/33 =   0%
```

**The defect is over-detection.** HubSpot's four mechanisms are `Breeze` and its
three derivatives, which are parts of Breeze, not four AIs. ServiceNow's
eighteen are `Now Assist` plus its per-domain instances. The model counted the
same AI once per name it appears under.

## Verdict — eliminated in favour of its own successor

The two-question shape is right. The counting rule is missing.

---

# Probe 6 — `aim2`: the same two questions plus a component rule

## Change against Probe 5

Four sentences added to Question 1, and nothing else:

```diff
 candidate that merely has AI features is not itself an AI mechanism; the
 passages must present the candidate as the AI.
 
+A mechanism's own parts are not separate mechanisms. If the passages say one
+candidate includes, contains, or is part of another, or name it as that other's
+application to a particular offering, report only the containing one. Listing
+both double-counts the same AI.
+
 **Question 2.** For each mechanism from Question 1, which of the other
```

## Prompt executed, in full

`````markdown
# AI mechanism and its reach — probe

## Task

Answer two questions about the candidates and passages below, and nothing else.
Do not assign a level to any candidate. Do not judge whether anything is a
product. Add nothing from outside the passages shown.

**Question 1.** Which candidates, if any, do the passages present as the firm's
**own AI** -- an AI the firm names and owns, described as delivering AI
function to the firm's offerings? A firm may name none, one, or several. A
candidate that merely has AI features is not itself an AI mechanism; the
passages must present the candidate as the AI.

A mechanism's own parts are not separate mechanisms. If the passages say one
candidate includes, contains, or is part of another, or name it as that other's
application to a particular offering, report only the containing one. Listing
both double-counts the same AI.

**Question 2.** For each mechanism from Question 1, which of the other
candidates do the passages place that AI inside, on, or across?

If a passage states the reach by a group word -- "all our engagement hubs",
"across our solutions" -- and another passage names that group's members, list
the named members. If no passage names them, list none and say the claim was
categorical.

## Input

```text
COMPANY: {{company_name}}
OBSERVATION_CUTOFF: {{cutoff}}

PRODUCT CANDIDATES:
{{product_candidates}}

SOURCE PASSAGES:
{{passages_with_ids}}
```

## Required output

Return a JSON array -- no wrapper object, no markdown fencing, no commentary --
with one element per mechanism found. An empty array is a valid and expected
answer for a firm that names no AI of its own.

Each element has exactly these fields:

- `mechanism_ref`: the `D` label of the AI candidate, copied exactly.
- `covered_refs`: array of `D` labels the passages place the AI inside, on or
  across. Empty array if the passages name none. `mechanism_ref` must not
  appear in it.
- `claim_type`: exactly one of
  - `enumerated` -- the passages name the covered offerings individually.
  - `categorical` -- a group word only, with no passage naming the members.
  - `mixed` -- both forms appear.
  - `unstated` -- the passages do not say what the AI reaches.
- `evidence`: array, at least one entry, each entry exactly
  `{{"ref": ..., "quote": ...}}`. Include the sentence that names the AI and,
  when the reach is stated, the sentence that states it.

### `evidence` -- how to cite

- `ref`: the label of one passage shown above, copied exactly.
- `quote`: 1 to 3 contiguous sentences copied verbatim from that passage.
- Never emit `source_id` or `passage_id`.

## Silent final check

- Every `mechanism_ref` and every entry in `covered_refs` is a `D` label shown
  above.
- No mechanism covers itself.
- `claim_type` is one of the four words.
- Every evidence `ref` is a `P` label shown above and every quote is copied
  exactly.
- A reach you cannot point at in a passage is not listed.
- An empty array is a real answer. Do not invent a mechanism to fill it.
`````

## Result against expectations registered before the run

```text
              before   after   expected   outcome
HubSpot          4  →    1        1       met exactly
ServiceNow      18  →    3        2       MISSED, in the safe direction
Datadog          1  →    1        1       reach-negative control held;
                                          see the note below — this is not
                                          the mechanism-negative control
Adobe            6  →    7       4-6      MISSED — the count rose
```

**Two of four are misses.** ServiceNow's is in the direction that does not
threaten the design — the extra mechanism is `ServiceNow AI Platform`, a real
named system with no stated reach, and the pre-registered risk was that the new
rule would *over*-cut and drop `AI Control Tower`. It did not. But the
expectation was 2 and the result was 3, and recording that as "met" would make
the pre-registration decorative.

**Datadog is the wrong kind of control, and this document previously conflated
two things.** Two distinct negative controls are needed:

```text
mechanism-negative firm      names no AI system at all
                             → a probe that returns one is over-firing
                             → WE HAVE NO SUCH FIRM

reach-negative mechanism     names an AI system, states no reach
                             → a probe that invents coverage is over-firing
                             → this is Datadog: Bits AI SRE, reach 0
```

Datadog holds the second and says nothing about the first. The acceptance
criterion below is written for the first and is not satisfied by any firm
exercised here.

Per firm:

```text
HUBS   Breeze                                  enumerated   reach  7 / 15
       → Smart CRM · Marketing · Sales · Service · Operations · Content · Commerce

DDOG   Bits AI SRE                             unstated     reach  0 / 45

NOW    Now Assist                              mixed        reach 20 / 71
       ServiceNow AI Platform                  unstated     reach  0 / 71
       AI Control Tower                        enumerated   reach  1 / 71

ADBE   Adobe Firefly                           mixed        reach 28 / 62
       Acrobat AI Assistant                    enumerated   reach  4 / 62
       Adobe Experience Platform AI Assistant  enumerated   reach  1 / 62
       Adobe Agent Orchestrator                enumerated   reach  1 / 62
       Adobe Brand Concierge                   unstated     reach  0 / 62
       Adobe Mix Modeler                       unstated     reach  0 / 62
       Adobe LLM Optimizer                     unstated     reach  0 / 62
```

`AI Control Tower` surviving at ServiceNow with a reach of exactly 1 is the
evidence that the new rule cuts components and not siblings. That case was
registered in advance as the over-cutting test and it passed.

Adobe's seven are plausibly seven: Firefly, the two Assistants, Agent
Orchestrator and three unstated offerings are genuinely different AIs for
different product lines, not parts of one. The count rising is not by itself the
defect.

## The defect: categorical expansion

Firefly's reach went from 10 to 28. Inspecting the 28:

```text
DEFENSIBLE   Photoshop · Illustrator · Premiere Pro · Lightroom · After Effects
             Adobe Express · Creative Cloud subscriptions
             Adobe Firefly web app · Adobe Firefly App

NOT          Adobe PostScript          a page-description language
             Adobe PDF standards       a standard, not an offering
             web conferencing · document and forms platform ·
             web App development · eLearning solutions ·
             technical document publishing        generic list items
             Experience Platform · Real-Time CDP · Customer Journey
             Analytics · AEM Sites · Commerce · Journey Optimizer ·
             Marketo Engage · Workfront · AEM Assets · Advertising ·
             GenStudio for Performance Marketing
```

The mechanism is legible in the two firms side by side:

```text
HubSpot   "across all our engagement hubs"    another passage NAMES the six
          → expansion is correct, 7 offerings

Adobe     "infused across Adobe's solutions"  NO passage names the members
          → the model expanded to nearly everything, 28 offerings
```

The prompt instructs, in Question 2: *"If no passage names them, list none and
say the claim was categorical."* The model expanded anyway and labelled the
result `mixed`. **The rule was written and not followed.** This is the same
pattern as D1 in a different guise: an instruction that runs against the model's
own tendency does not hold merely by being present.

## A second defect the deterministic layer would not catch

One of Firefly's eight evidence entries is:

> `P7`: "Mr. Wadhwani also advises early stage and growth companies and is on
> the board of directors of Gem Software, Inc., an AI recruiting software
> company, and on the board of trustees of StoryCorps…"

This is a director's biography, cited as evidence for a product's AI coverage.
It passes quote containment — the sentence really is in `P7` — and fails
relevance. `SPEC-023` deterministic validation checks containment. **Containment
is not sufficient**, and this is the first recorded instance in this project of
a citation that is verbatim, correctly attributed, and evidentially worthless.

## Verdict — surviving, defective, not authorised

Three firms of four met their pre-registered expectation, including the negative
control. The fourth failed in a diagnosed and specific way.

---

# What the six probes together establish

**1. The relation appears extractable from Item 1 and produces distinguishable
diagnostic shapes. Measurement validity is not established.** Four firms, four
patterns, from the source the corpus already holds — but no gold, one firm
failed, and no result here was scored against anything:

```text
HubSpot      one AI, every product           enumerated by the firm
ServiceNow   one AI, most products           partly enumerated
Adobe        several AIs, per product line   categorical, unverifiable as stated
Datadog      one AI, no reach claimed        unstated
```

That these four shapes are distinguishable at all is the substantive result of
this CR. It is a claim about extractability, not about validity: three of the
four were read by inspection, the fourth is a measured failure, and none was
compared to an adjudicated record.

**2. The level vocabulary cannot carry it.** Probes 1 to 3 tried three different
places to put an AI category into an existing vocabulary. All three failed, and
Probe 3 failed structurally rather than by wording: a level says what a thing is
and reach is a relation between two things.

**3. Asking the relation directly works.** Probes 4 to 6 asked, and got answers
that survive inspection in three firms of four.

**4. D1 is now measured seven times.** Every vocabulary change at either
extraction stage redistributes decisions beyond its target. Probe 3's fourteen
collateral changes, seven of them at the control firm, are the cleanest instance
recorded so far. Probes 5 and 6 change no vocabulary and produce no collateral
movement, which is a further argument for a separate probe over a vocabulary
edit.

**5. Reach and de-duplication must be recorded together.** Probe 1 showed the
model will collapse per-domain AI instances unprompted, and will discard the
domain list when it does. Probe 6 showed the same collapse can be requested
while the domains are retained. Collapsing without recording is worse than not
collapsing.

**6. Quote containment does not establish evidentiary relevance.** Recorded
above; it bears on `SPEC-023` and on the gold protocol independently of this CR.

# Risks and trade-offs of the surviving shape

Probe 6 is the only design not eliminated. Its risks, stated before anyone
argues for it:

- **A new stage is a new failure surface.** Probes 5 and 6 avoid D1 collateral
  movement by not touching the existing vocabulary, but they add a stage whose
  output nothing downstream validates. The collateral movement is traded for an
  unvalidated surface, not removed.
- **Over-detection is the standing bias.** Probe 5 found 18 mechanisms where 2
  exist. One rule fixed it in three firms. The direction of the error is
  consistent across every run: the model finds more AI than the filing states,
  never less. Any threshold set from this instrument inherits that bias.
- **Categorical claims will be systematically over-counted unless the fix
  holds.** Adobe's 28 is the measured size of the problem: 62 candidates, 47 of
  them products, and a claim that could defensibly cover about 9.
- **The reach count is a count of candidates, not of products.** `28 / 62` mixes
  families, products, variants and capabilities on the denominator. Any ratio
  built from it needs the consolidation levels applied first, and Probe 6 does
  not see them.
- **`unstated` and `zero reach` are the same output.** Datadog's `0 / 45` and
  Adobe Brand Concierge's `0 / 62` are both honest, and they mean different
  things: one firm makes no claim, the other names an AI with no stated span.
  `claim_type` separates them today only because the model set it correctly, and
  Adobe is the proof it does not always.
- **Item 1 is a strategy document, not a product catalogue.** A firm that
  restructured its Item 1 changes its measured reach without changing its
  products. HubSpot did exactly this at FY2024, collapsing seven product
  sections into one. A reach series read from Item 1 alone will show that as a
  transition.

# Known limitations

- **The panel is not period-aligned.** HubSpot is FY2024, the other three FY2025.
  No claim here compares two firms as like-for-like observations.
- **Four firms, one of them the control, is not a sample.** Nothing here
  generalises to a sector, and no threshold should be set from these numbers.
- **There is no gold for any of it.** No probe output was scored against an
  adjudicated record, because none exists for the reach question. The HubSpot
  reach of 7 agrees with the adjudication record's structure, which is
  agreement with one reading, not verification.
- **ADR-015 applies to every case touched here.** All four firm-periods have had
  their predictions inspected during tuning and can never serve as blind frozen
  cases for this question.
- **Categorical expansion is unresolved.** It is the single defect blocking
  Probe 6, it is diagnosed but not fixed, and no seventh probe was run.
- **Probe 6's `claim_type` was wrong on the case that matters.** Adobe's
  categorical claim was labelled `mixed`. A design that relies on `claim_type` to
  flag unverifiable reach must first make that label trustworthy.
- **549,940 microdollars were spent to eliminate four designs and qualify one
  defect.** No gold existed to score any of it against, which is why five of the
  six probes could only be read by inspection. This is the cost of running the
  development sequence out of order, and it is recorded here rather than
  argued away.

# Open questions for the methodology owner

1. **Where does the mechanism observation live?** A separate probe stage with its
   own schema, or a field on an existing observation? Probes 5 and 6 assume the
   former and nothing in the repository provides for either.

   One constraint is already known and is not a design preference. The target
   registry keeps aliases and canonical ids in **one shared namespace**
   (`src/dynamic_ai_products/evaluation/references.py`, `alias_owner`), so a
   second entry `HUBS.AI_MECHANISM.BREEZE` carrying the alias `"Breeze"` is
   rejected as `conflicting_reference_definition` — `HUBS.FAMILY.BREEZE` already
   owns that alias. An orthogonal role therefore needs either a separate
   mechanism registry with its own contract, or an explicit crosswalk. It cannot
   be a second row in `hubs_target_registry_v1.json`.
2. **Is a categorical claim a measurement or a missing value?** "Infused across
   Adobe's solutions" with no enumeration is a real statement by the firm. Under
   Rule 7 the honest record is `unknown` with the claim preserved. Under
   `SPEC-017`'s breadth component, discarding it loses a real difference between
   a firm that claims universal reach and one that claims none. These two
   readings disagree and the disagreement is not resolvable from the evidence.
3. **Does the reach relation need adjudicated gold before any further prompt
   work?** The development protocol says yes, and steps 3 and 6 of it were
   skipped once already.
4. **Should `complementary` return under Decision 4a?** Probe 2's fourteen
   assignments are a services taxonomy, and Decision 4a is an unwritten services
   rule. They may be the same problem.

# If a design is ever selected, it must satisfy

- Adjudicated gold for the reach relation on at least two firm-periods, produced
  before any further prompt iteration, from firms not among the four above.
- **Both** negative controls hold, on separate firms: a mechanism-negative firm
  that names no AI system returns none, and a reach-negative mechanism returns
  an empty coverage list. Only the second was exercised here.
- A categorical reach claim with no enumerating passage produces an empty
  coverage list and a `claim_type` that says so — verified on Adobe, which is
  the case that currently fails. `unstated` and `categorical` are each recorded
  as themselves: neither is a reach of zero, and neither is an exact count.
- The reach denominator contains **only governed retained product
  observations**. Adobe's `28 / 62` is not a ratio — its denominator mixes
  families, variants, capabilities and unresolved candidates.
- The mechanism is recorded as a **firm-presented named AI system**, not as the
  firm's own AI. Ownership is a legal claim that a business description does not
  establish; what the source supports is that the firm names the system and
  presents it as delivering AI function.
- Every coverage entry cites a passage that states the coverage, checked for
  relevance and not only for containment.
- Collateral movement measured, not assumed: the rest of the chain's output on
  the same packets compared before and after.
- A decision-log entry and a schema version increment, per Rule 8, before
  anything is registered.

# Decision

`revise`.

No candidate is put forward for acceptance. Four designs are eliminated by
measurement and recorded so they are not retried. One survives with a named,
reproducible defect and no gold to score it against.

The next step this document supports is **not** a seventh probe. It is the gold
that steps 3 and 6 of the development sequence call for and that was skipped.
Running a seventh probe before that gold exists would repeat the error this CR
cost 549,940 microdollars to demonstrate.

# Approval

```text
researcher      —  unsigned
date            —
prompt version  none; PROMPT_REGISTRY_VERSION unchanged at
                extraction_prompt_registry_v9
code commit     no code change accompanies this document
```

This CR proposes no edit and therefore requires no approval to exist. It
requires the methodology owner's answers to the four open questions before any
design derived from it may be built.

# Provenance

```text
prompts        pd_v5proto.md · pd_comp_proto.md · rel_prompt_ailayer.md
               cov/aim/aim2 renders          session scratchpad, unregistered
drivers        pd5_drive.py · cp_drive.py · al_drive.py ·
               cov_drive.py · aim_drive.py · aim2_drive.py
raw outputs    {tag}_raw_{TICKER}.json       30 files
rendered input {tag}_render_{TICKER}.md      prompt as sent, input included
baseline       c4_render_*.md · c4_raw_*.json   executor scratchpad
```

**These runs are not independently auditable, and this document must not be read
as if they were.** Scratchpad contents are session-local and not preserved by the
repository. The six prompts are reproduced above and are therefore re-readable;
the thirty model outputs and the rendered inputs they were produced from are
not. Every count, list and quotation attributed to a model output in this
document rests on a reading that cannot now be re-performed by anyone else.

That is a defect in how the probes were run, not a property of the work they
describe. Any successor must write raw outputs and rendered inputs to a run
directory before the first result is read.
