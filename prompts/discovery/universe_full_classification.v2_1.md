# Company-Universe Full Multi-Axis Classification — v2.1

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

Every displayed Item 1 passage has a short reference such as `P001`.

- Return only that `passage_ref`, exactly as displayed.
- `quote` is a contiguous verbatim substring from that one passage body.
- Do not return a source id, passage id, hidden hash, URL, or filing id.
- Do not combine two sentences or passages in a quote.
- Prefer the shortest direct span. Use more than one evidence object only when
  the claims are genuinely different; never repeat the same
  `(passage_ref, quote, supported_claim)` object.
- If the packet does not support a claim, leave the relevant value unknown or
  null and add a concise boundary flag. Do not infer from a website, internal
  IT use, AI wording, a ticker, SIC/NAICS, or current company knowledge.
- A quote displayed in the admission context may be useful orientation, but
  reuse it only after checking it against the complete supplied Item 1 packet.

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
- `evidence`: at most 6 objects; at least 1 whenever any axis is not unknown.
- `quote`: at most 300 characters, contiguous, from one passage body.
- `supported_claim`: at most 200 characters.
- `boundary_flags`: at most 4 entries, each at most 160 characters.
- `contradictions`: at most 4 entries, each at most 200 characters.

Prefer the shortest span that carries the claim. Do not restate the packet, do
not explain your reasoning outside these fields, and do not emit prose before
or after the JSON object.

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
      "quote": "",
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
