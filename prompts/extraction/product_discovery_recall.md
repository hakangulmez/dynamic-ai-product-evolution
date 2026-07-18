# Product Discovery — High Recall

## Governing spec

`SPEC-008`

## System instruction

You are performing the high-recall discovery pass for a dated product universe. Extract plausible customer-facing commercial offerings from the supplied, temporally valid official source passages.

Do not score AI adoption, replicability, defensibility, quality, or business success.

A product is an identifiable offering a customer can buy, subscribe to, license, deploy, or use. Preserve uncertain candidates for later consolidation.

Do not treat the following as products unless the evidence establishes a distinct offering:

- strategy themes;
- generic “AI,” “cloud,” “platform,” or “innovation” labels;
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

## Required output

For each candidate provide candidate name, normalized name, possible product family, status, target customer, evidence passages, direct quote, ambiguity, and confidence.

Return JSON conforming to `product_observation.schema.json`, with `candidate_status = discovery_candidate`.

## Silent final check

- Every candidate is customer-facing.
- Every candidate has evidence.
- No source is after the cutoff.
- Uncertain packaging remains flagged rather than resolved.
