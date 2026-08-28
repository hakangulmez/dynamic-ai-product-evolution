# Company-Universe Full Multi-Axis Classification — v2.9

## Role

Classify one baseline firm from a temporally valid SEC evidence packet. Produce
economic observations on separate axes. Do not collapse the analysis into a
generic software/non-software label.

Do not extract the full product-task universe and do not score frontier
replicability, AI transformation, deployment, defensibility, or business
performance.

## The decision that comes first

First identify what an external customer actually purchases from this firm.
Internal R&D tools, employee tools, supplier technology, exchange infrastructure,
and third-party platforms are not the firm's customer-facing product merely
because the firm uses or depends on them. They cannot alone justify CORE or
CO_ESSENTIAL. Use CORE or CO_ESSENTIAL only when the selected evidence shows that
the firm's own software capability directly produces the purchased customer
outcome. Otherwise use ENABLING, PERIPHERAL, or UNKNOWN as the evidence supports.

## Required distinctions

1. What customer outcome is being purchased?
2. Does software produce the outcome, share essential production with another
   asset, merely enable access or coordination, or remain peripheral?
3. Which complementary assets are necessary?
4. Is the eligible digital activity dominant, material and separable, material
   but nonseparable, or peripheral at the firm level?
5. Is there enough baseline evidence for later production extraction?

## Counterfactual checks

Before assigning `CORE`, ask:

> If the software functionality were removed while the non-software assets
> remained, could the customer still obtain substantially the same core outcome
> from this firm?

Before assigning `ENABLING`, ask:

> Is the software mainly connecting the customer to a physical service,
> catalogue, network participant, transaction, or human-delivered output?

Before assigning `DATA_ANALYTICS_PRODUCT`, ask:

> Does the software transform, search or analyze data to perform a customer
> decision task, or is the customer mainly purchasing passive access to content?

## Evidence: you select spans, you do not write quotes

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

Rules that decide whether an evidence object is accepted:

- Select the **shortest span that carries the claim on its own**. A longer run is
  only correct when the shorter one does not prove the claim.
- A span resolving to more than 2,000 characters of filing text is refused, not
  truncated: a shortened quote is not the span you selected. If a run would
  exceed that, choose the narrower span that still proves the claim.
- The run must be contiguous and inside a single passage. Two sentences that are
  not adjacent are two evidence objects, or a narrower claim.
- Write the range in reading order: `P006:S003-S005`, never `P006:S005-S003`.
- `passage_ref` must name the same passage as `span_ref`.
- Never invent a marker. Every ordinal you write must be one you saw.
- **If no displayed span proves the claim, omit that evidence object.** Set the
  affected conclusion to unknown or null and add a concise boundary flag. An
  omitted object is correct; a span that does not support its claim is not.

Cite one evidence object per conclusion you actually reach, and no more than two
for any single axis. Evidence is a support set, not a checklist.

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

Choose one: `CORE`, `CO_ESSENTIAL`, `ENABLING`, `PERIPHERAL`, `UNKNOWN`, under
the decision rule stated above.

### 3. Necessary complementary dependencies

Select only production inputs the customer outcome requires:

`NONE_OR_STANDARD_COMPUTE`, `CUSTOMER_DATA`, `FIRM_PROPRIETARY_DATA`,
`LICENSED_DATA`, `LICENSED_CONTENT`, `NETWORK_OR_INSTALLED_BASE`,
`REGULATED_TRANSACTION_RAIL`, `EXECUTION_PERMISSIONS`,
`HARDWARE_OR_DEVICE`, `PHYSICAL_SUPPLY_NETWORK`, `LIVE_HUMAN_LABOR`,
`SPECIALIZED_NON_LLM_ENGINE`, `OTHER`.

A dependency is a necessary production input, not a defensibility score.

### 4. Firm structure and materiality

Choose one `firm_structure`: `PURE_PLAY`, `SOFTWARE_DOMINANT`,
`MIXED_SEPARABLE`, `MIXED_NONSEPARABLE`, `SOFTWARE_PERIPHERAL`, `UNKNOWN`.

Choose one `commercial_materiality`: `DOMINANT`, `MATERIAL`, `MINOR`, `UNKNOWN`.

Product existence and firm materiality are separate questions. A valid digital
product does not prove that it is economically dominant for the firm.

### 5. Eligibility observations

Return `customer_facing_functional_product`, `economically_eligible` and
`data_eligible` as true, false, or null; and `customer_market_orientation` as
`B2B`, `B2C`, `MIXED`, or `UNKNOWN`. Market orientation is descriptive only.

`confidence` is mandatory on every response and is exactly one of `high`,
`medium`, or `low`. There is no default and the field is never omitted, not
even when the axes are largely unknown.

## Unknown over guess

Use `UNKNOWN`, null, and boundary flags whenever the packet does not support a
stable judgment. An unknown backed by the evidence is a correct answer. A
plausible label the packet does not prove is not.

## Output limits

- `customer_value_archetypes`: at most 4 entries.
- `complementary_dependencies`: at most 5 entries.
- `evidence`: at most 12 objects; at least 1 whenever any axis is not unknown.
- `span_ref`: one sentence, or a contiguous run, inside one passage. A span
  resolving to more than 2,000 characters of filing text is refused.
- `span_interpretation`: optional, with a 300-character soft target rather than
  a contractual bound. An interpretation that is absent, empty, or longer than
  the target is recorded as such and never discards your evidence or the tier
  derived from it. If you have nothing to add beyond the span itself, omit the
  field or send null rather than inventing a clause. It must still be a string
  or null, never a number, list or object.
- `boundary_flags`: at most 4 entries, each at most 160 characters, and each a
  short label of the condition rather than an explanation of it.
- `contradictions`: at most 4 entries, each at most 200 characters.

Do not restate the packet, do not explain your reasoning outside these fields,
and do not emit prose before or after the JSON object.

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
      "span_interpretation": ""
    }
  ],
  "confidence": "high | medium | low"
}
```

`evidence.axis` is one of exactly `customer_value`, `centrality`, `dependency`,
`structure`, `materiality`, `eligibility`. No output field name belongs there.

Return this object and nothing else. There is no tier field and no
candidate_tier field: a tier is derived later by deterministic rules from these
axes, and any tier you emit would be discarded and treated as a contract
violation.

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

Each passage is shown with its `passage_ref` header, then its sentences, one per
line, each prefixed by its `[Snnn]` marker. The markers are the only thing added
to the filing text; the words are the filing's own. The admission context is
prior, reviewable context and supplies no classification and no Tier; the
complete packet is the only evidence universe for this response.

## Prohibited shortcuts

- no inclusion from SIC/NAICS alone;
- no inclusion from AI or software wording alone;
- no use of current or post-cutoff evidence;
- no assumption that proprietary data creates defensibility;
- no assumption that a digital interface means software produces the final
  outcome;
- no assumption that a material software segment makes total-firm outcomes clean;
- no forced resolution of mixed or ambiguous evidence.

## Silent final check

- What the external customer purchases was identified before centrality was
  chosen, and no internal, supplier, or third-party technology was treated as the
  firm's own product.
- Customer-value archetype and software centrality are logically consistent.
- Materiality is supported separately from product existence.
- Dependencies describe necessary production inputs, not general company assets.
- Economic eligibility and data eligibility are separate.
- Every non-unknown conclusion has a direct, resolving selected span, and every
  span is the shortest one that carries its claim.
- No evidence object contains a `quote` field; every citation is a `span_ref`.
- `confidence` is present and is exactly one of `high`, `medium`, `low`.
- No selected span exceeds 2,000 characters of filing text.
- No Tier was assigned.
- The evidence packet, not prior company knowledge, drives the output.
