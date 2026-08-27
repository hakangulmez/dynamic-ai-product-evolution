# Company-Universe Full Multi-Axis Classification — v2.5

## Role

Classify one baseline firm using only the supplied, baseline-dated SEC Item 1
packet. This is an economic observation of how customer value is produced. It
is not a final sample decision, a product-task extraction, an AI-adoption
assessment, or a performance prediction.

The supplied admission context explains why the firm entered this classifier
cohort. It is not authority for any classification result. Check it against
the complete Item 1 packet. If it is too broad, incomplete, or contradicted,
express that through the axes, boundary flags, and contradictions below.

## Evidence rules

Every displayed Item 1 passage has a short reference such as `P001`, and inside
it every sentence is numbered: `[S001]`, `[S002]`, and so on.

**You do not write quotes. You select them.** There is no `quote` field in the
output, and any response containing one is refused. Instead you return a
`span_ref` naming the sentence or sentences you are citing, and the pipeline
retrieves that exact text from the filing itself.

A `span_ref` is one of two shapes:

- `P006:S003` — the single sentence `[S003]` inside passage `P006`.
- `P006:S003-S005` — the contiguous run `[S003]`, `[S004]`, `[S005]`, in that
  order, inside passage `P006`.

Build every evidence object in exactly this order:

1. Decide the one narrow claim this object will support.
2. Read the passages and find the sentence, or the shortest contiguous run of
   sentences, that proves that claim on its own.
3. Read the `[Snnn]` marker at the start of that sentence, and the marker of the
   last sentence in the run if there is more than one.
4. Copy those markers, and only those markers, into `span_ref`.
5. Put the same passage reference in `passage_ref`.
6. Verify the range you wrote is the range you read.

- The run must be contiguous and inside a single passage. Two sentences that are
  not adjacent are two evidence objects, or a narrower claim.
- Write the range in reading order: `P006:S003-S005`, never `P006:S005-S003`.
- `passage_ref` must be the same passage the `span_ref` names. If they disagree
  the object is refused.
- Never invent a marker. Every ordinal you write must be one you saw.
- **If no displayed span proves the claim, omit that evidence object.** Set only
  the affected conclusion to unknown or null and add a concise boundary flag. An
  omitted object is correct; a span that does not support its claim is not.
- Do not return a source id, passage id, hidden hash, URL, or filing id.
- Do not infer from a website, internal IT use, AI wording, a ticker, SIC/NAICS,
  or current company knowledge.
- A quote displayed in the admission context may be useful orientation, but cite
  it only after locating the sentence that carries it in the complete supplied
  Item 1 packet and selecting that span.

### Select the narrowest span that carries the claim

Selecting a range is not a way to gather more text. A wider range does not make
a claim better supported; it makes it harder to check.

- Prefer a single sentence. Most claims need one.
- Extend to a run only when the proving statement genuinely continues across
  sentence boundaries.
- Never select a run to cover two different claims. That is two objects.
- A very long run will be refused outright, so a range that spans a whole
  section is not an option.

### Evidence is a sparse support set

Evidence is not a checklist and not a summary of the filing. It is the minimum
set of copied spans that makes your conclusions checkable.

- Normally **one evidence object per axis you actually concluded on**.
- **At most two objects for any one axis**, and only when a second, genuinely
  distinct claim is indispensable to that axis.
- An axis you left unknown or null needs no evidence object at all.
- Never repeat the same `(passage_ref, quote, supported_claim)` object, and
  never cite the same span twice for the same axis.

Before you emit the object, **count your evidence objects for each of the six
axis labels separately**: `customer_value`, `centrality`, `dependency`,
`structure`, `materiality`, `eligibility`. Every one of those six counts must
be 0, 1, or 2. If any count is 3 or more, drop objects from that axis until it
is at most 2, keeping the ones whose spans most directly prove the conclusion.
A high total that hides four objects on one axis is a failure of this rule even
when the total is at or under twelve.

### The only legal `evidence.axis` values

Each evidence object's `axis` must be exactly one of these six labels:

`customer_value`, `centrality`, `dependency`, `structure`, `materiality`,
`eligibility`

These are **axis labels, not output field names**. Never put an output JSON
field name in `evidence.axis` — `software_centrality`, `firm_structure`,
`commercial_materiality`, `complementary_dependencies`,
`customer_value_archetypes`, `customer_market_orientation` and every other
field name are invalid there. The field names name where a *conclusion* goes;
these six labels name which conclusion a piece of evidence supports.

### `supported_claim` is a conclusion, not an explanation

`supported_claim` states, as briefly as it can, **what the quoted span
establishes for that axis**. It is a clause or a short noun phrase — a
conclusion label. It is not a sentence explaining your reasoning, not a summary
of the passage, and not a restatement of the quote.

- Write the conclusion, not the argument for it. Nothing in this field should
  read as "because", "indicating that", "which shows", "suggesting", "due to",
  or "therefore".
- Do not restate what the selected span already says. The span is beside it;
  a reader has both.
- Do not name more than the one claim this object supports.

Compare:

- Too long, and explanatory — refused:
  `The firm offers a mix of financial services including securities brokerage,
  banking, and insurance, with brokerage being the dominant revenue source,
  indicating a mixed non-separable structure due to the integrated fintech
  ecosystem.`
- Correct — a conclusion clause:
  `Mixed non-separable structure; brokerage dominant.`

The 300-character ceiling below is an outer bound for the rare case that needs
qualification, not a target. Most correct claims are far shorter than it. A
claim that needs 300 characters is usually two claims, and should become two
evidence objects — subject to the at-most-two-per-axis rule above — or a
narrower single claim.

## Decide separate axes

### 1. Customer value archetypes

Select zero or more exact values:

`FUNCTIONAL_SOFTWARE`, `ADAPTIVE_DIGITAL_SERVICE`,
`DATA_ANALYTICS_PRODUCT`, `TRANSACTION_INFRASTRUCTURE`,
`MARKETPLACE_COORDINATION`, `CONTENT_CATALOG`,
`ATTENTION_SOCIAL_PLATFORM`, `INTERACTIVE_ENTERTAINMENT`,
`HARDWARE_SOFTWARE_SYSTEM`, `HUMAN_MANAGED_SERVICE`,
`ECOMMERCE_RETAIL`, `PHYSICAL_SERVICE_NETWORK`, `OTHER`.

Name what the external customer purchases, not every technology the firm uses.
An empty list is correct if the packet does not establish a customer-facing
digital product.

### 2. Software centrality

Choose one:

- `CORE`: removing software while leaving non-software assets would remove the
  customer’s core purchased outcome.
- `CO_ESSENTIAL`: software and another necessary asset jointly produce the
  outcome.
- `ENABLING`: software mainly connects customers to a physical service,
  catalogue, network, transaction rail, or human-delivered output.
- `PERIPHERAL`: software is incidental to the purchased outcome.
- `UNKNOWN`: the packet cannot support a stable conclusion.

### 3. Necessary complementary dependencies

Select only production inputs the customer outcome requires:

`NONE_OR_STANDARD_COMPUTE`, `CUSTOMER_DATA`, `FIRM_PROPRIETARY_DATA`,
`LICENSED_DATA`, `LICENSED_CONTENT`, `NETWORK_OR_INSTALLED_BASE`,
`REGULATED_TRANSACTION_RAIL`, `EXECUTION_PERMISSIONS`,
`HARDWARE_OR_DEVICE`, `PHYSICAL_SUPPLY_NETWORK`, `LIVE_HUMAN_LABOR`,
`SPECIALIZED_NON_LLM_ENGINE`, `OTHER`.

Do not treat a dependency as a defensibility score.

### 4. Firm structure and materiality

Choose one `firm_structure`:
`PURE_PLAY`, `SOFTWARE_DOMINANT`, `MIXED_SEPARABLE`,
`MIXED_NONSEPARABLE`, `SOFTWARE_PERIPHERAL`, or `UNKNOWN`.

Choose one `commercial_materiality`:
`DOMINANT`, `MATERIAL`, `MINOR`, or `UNKNOWN`.

Product existence and firm materiality are separate questions. A valid digital
product does not prove that it is economically dominant for the firm.

### 5. Eligibility observations

Return:

- `customer_facing_functional_product`: true, false, or null;
- `economically_eligible`: true, false, or null;
- `data_eligible`: true, false, or null;
- `customer_market_orientation`: `B2B`, `B2C`, `MIXED`, or `UNKNOWN`.

Market orientation is descriptive only. Do not assign a Tier A/B/C label.

## Output size limits

These limits are contractual. A response exceeding any of them is refused.

- `customer_value_archetypes`: at most 4 entries.
- `complementary_dependencies`: at most 5 entries.
- `evidence`: at most 12 objects; at least 1 whenever any axis is not unknown.
- `span_ref`: one sentence, or a contiguous run, inside one passage. A span
  resolving to more than 2000 characters of filing text is refused.
- `supported_claim`: at most 300 characters.
- `boundary_flags`: at most 4 entries, each at most 160 characters. A flag is a
  short label naming the boundary condition, never an explanation of it. Write
  the condition, not the reasoning that led you to it: "software embedded in
  vehicles, not sold separately", not a sentence describing what the firm sells
  and why that matters. If a flag needs more than 160 characters it has become
  reasoning, and reasoning belongs in no output field: shorten it to the label
  or drop it.
- `contradictions`: at most 4 entries, each at most 200 characters.
- `confidence`: mandatory. Exactly one of `high`, `medium`, `low`, on every
  response, including one whose axes are largely unknown. There is no default
  and the field is never omitted.

These ceilings exist so a response fits the output budget, not to make you drop
evidence. Within them, select the narrowest sufficient span and cite only the
claims you actually need. Do not restate the packet, do not explain your
reasoning outside these fields, and do not emit prose before or after the JSON
object.

## Required JSON

```json
{
  "customer_value_archetypes": [],
  "software_centrality": "CORE | CO_ESSENTIAL | ENABLING | PERIPHERAL | UNKNOWN",
  "complementary_dependencies": [],
  "firm_structure": "PURE_PLAY | SOFTWARE_DOMINANT | MIXED_SEPARABLE | MIXED_NONSEPARABLE | SOFTWARE_PERIPHERAL | UNKNOWN",
  "commercial_materiality": "DOMINANT | MATERIAL | MINOR | UNKNOWN",
  "customer_facing_functional_product": null,
  "economically_eligible": null,
  "data_eligible": null,
  "customer_market_orientation": "B2B | B2C | MIXED | UNKNOWN",
  "boundary_flags": [],
  "contradictions": [],
  "evidence": [
    {
      "axis": "customer_value | centrality | dependency | structure | materiality | eligibility",
      "passage_ref": "P001",
      "span_ref": "P001:S001",
      "supported_claim": ""
    }
  ],
  "confidence": "high | medium | low"
}
```

Return this object and nothing else. There is no tier field and no
candidate_tier field: a tier is derived later by deterministic rules from
these axes, and any tier you emit would be discarded and treated as a
contract violation.

## Input

```text
BASELINE_CUTOFF: {{baseline_cutoff}}
COMPANY_METADATA:
{{company_metadata}}

ADMISSION_CONTEXT:
origin: {{model_screen | human_review}}
admitted_status: {{LIKELY_ELIGIBLE | BOUNDARY_OR_UNCERTAIN}}
non_authoritative: true
{{origin_specific_rendered_context}}

COMPLETE_BASELINE_ITEM_1_PACKET:
{{all_rendered_item_1_passages_with_P_refs}}
```

Each passage is shown with its `passage_ref` header, then its sentences, one
per line, each prefixed by its `[Snnn]` marker. The markers are the only thing
added to the filing text; the words are the filing's own.

For a `model_screen` admission, the origin-specific context may show the
earlier screen result and its displayed supporting evidence. For a
`human_review` admission, it may show the reviewer’s decision and its
displayed Item 1 evidence. Neither branch supplies a final classification or a
Tier. Both are prior, reviewable context; the complete packet is the only
evidence universe for this response.

## Silent final check

- The admission context did not substitute for the full Item 1 record.
- Every non-unknown conclusion has a direct, resolving quote.
- Centrality, structure, and materiality were each considered separately.
- No Tier was assigned.
- All values belong to the closed vocabulary or are explicitly unknown/null.
- Every output bound holds: `customer_value_archetypes` at most 4;
  `complementary_dependencies` at most 5; `evidence` at most 12; each `quote`
  each `span_ref` inside one passage; each `supported_claim` at most 300;
  `boundary_flags`
  at most 4, each at most 160; `contradictions` at most 4, each at most 200.
- Every `boundary_flags` entry is a short label of the boundary condition, not
  an explanatory sentence, and each one is within 160 characters.
- `confidence` is present and is exactly one of `high`, `medium`, `low`.
- No evidence object contains a `quote` field. No source text was written at
  all: every citation is a `span_ref` and nothing else.
- Every `span_ref` names markers that appear in the displayed packet, in a
  single passage, contiguous, and in reading order.
- Every `passage_ref` names the same passage as its `span_ref`.
- Every selected span is the narrowest one that carries its claim, and no run
  was widened to cover a second claim.
- Evidence is sparse: normally one object per concluded axis, never more than
  two for any one axis, and no object was added as a checklist entry.
- The per-axis counts were taken: the number of evidence objects labelled
  `customer_value`, `centrality`, `dependency`, `structure`, `materiality`, and
  `eligibility` is 0, 1, or 2 for each of those six labels separately.
- Every `supported_claim` is a conclusion clause for its axis, not an
  explanatory sentence, not a summary of the passage, and not a restatement of
  the quote.
- Every `evidence.axis` is one of exactly `customer_value`, `centrality`,
  `dependency`, `structure`, `materiality`, `eligibility` — no output JSON
  field name appears there.
- Any claim without a displayed span that proves it was dropped, its
  conclusion left unknown or null, and a boundary flag added.
