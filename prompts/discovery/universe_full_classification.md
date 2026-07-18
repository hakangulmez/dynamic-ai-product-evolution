# Company-Universe Full Multi-Axis Classification

## Governing spec

`SPEC-001`

## Required reading

- `docs/methodology/SOFTWARE_FIRM_UNIVERSE.md`
- `configs/universe_taxonomy.yaml`
- `configs/universe_sample_rules.yaml`

## Role

Classify one baseline firm from a temporally valid SEC evidence packet. Produce economic observations on separate axes. Do not collapse the analysis into a generic software/non-software label.

Do not extract the full product-task universe and do not score frontier replicability, AI transformation, deployment, defensibility, or business performance.

## Required distinctions

1. What customer outcome is being purchased?
2. Does software produce the outcome, share essential production with another asset, merely enable access/coordination, or remain peripheral?
3. Which complementary assets are necessary?
4. Is the eligible digital activity dominant, material and separable, material but nonseparable, or peripheral at the firm level?
5. Is there enough baseline evidence for later production extraction?

## Counterfactual checks

Before assigning `CORE`, ask:

> If the software functionality were removed while the non-software assets remained, could the customer still obtain substantially the same core outcome from this firm?

Before assigning `ENABLING`, ask:

> Is the software mainly connecting the customer to a physical service, catalogue, network participant, transaction, or human-delivered output?

Before assigning `DATA_ANALYTICS_PRODUCT`, ask:

> Does the software transform/search/analyze data to perform a customer decision task, or is the customer mainly purchasing passive access to content?

## Input template

```text
BASELINE_CUTOFF: {{baseline_cutoff}}
COMPANY_METADATA:
{{company_metadata}}

BASELINE_EVIDENCE_PACKET:
{{passages_with_source_and_passage_ids}}

HIGH_RECALL_SCREEN:
{{screen_output}}
```

## Required output

Return JSON conforming to `company_universe_classification.schema.json`.

Every archetype, centrality, dependency, structure, materiality, and eligibility claim must link to direct evidence. Multiple customer-value archetypes are allowed. Use `UNKNOWN` and boundary flags when the packet does not support a stable judgment.

The field `candidate_tier` is advisory only. Final tier membership is derived by deterministic rules.

## Prohibited shortcuts

- no inclusion from SIC/NAICS alone;
- no inclusion from AI or software wording alone;
- no use of current or post-cutoff evidence;
- no assumption that proprietary data creates defensibility;
- no assumption that a digital interface means software produces the final outcome;
- no assumption that a material software segment makes total-firm outcomes clean;
- no forced resolution of mixed or ambiguous evidence.

## Silent final check

- Customer-value archetype and software centrality are logically consistent.
- Materiality is supported separately from product existence.
- Dependencies describe necessary production inputs, not general company assets.
- Economic eligibility and data eligibility are separate.
- The evidence packet, not prior company knowledge, drives the output.
