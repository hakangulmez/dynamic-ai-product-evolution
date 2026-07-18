# Universe Boundary Adjudication

## Governing spec

`SPEC-001`

## Purpose

Resolve a disputed company-universe classification without overwriting the original screen, classifier output, deterministic rule trace, or source packet.

## Inputs

- baseline evidence packet;
- original high-recall screen;
- full classifier output;
- deterministic Tier A/B/C rule trace;
- reviewer disagreement or failure tag;
- relevant taxonomy definitions.

## Adjudication questions

1. What is the customer's core purchased outcome?
2. Which mechanism actually produces that outcome?
3. Is software core, co-essential, enabling, peripheral, or unknown?
4. Are complementary assets inputs to a software task, or are they the true underlying product?
5. Is the eligible activity dominant/material at firm level?
6. Can the product-level classification be linked cleanly to firm- or segment-level outcomes?
7. Is ambiguity caused by missing evidence, mixed business structure, or a genuine ontology boundary?

## Required output

```json
{
  "decision": "CONFIRM_CLASSIFIER | OVERRIDE_CLASSIFIER | CONFIRM_RULE_TIER | OVERRIDE_RULE_TIER | REMAIN_UNCERTAIN | ONTOLOGY_CHANGE_REQUIRED",
  "reviewed_axes": {},
  "final_candidate_tier": "TIER_A_CORE | TIER_B_EXTENSION | TIER_C_BOUNDARY | EXCLUDED | UNCERTAIN",
  "reason_codes": [],
  "evidence": [],
  "ontology_question": null,
  "review_comment": "",
  "confidence": "high | medium | low"
}
```

Write a concise audit rationale. Do not provide hidden chain-of-thought. If the case requires a new general rule, return `ONTOLOGY_CHANGE_REQUIRED`; do not improvise a company-specific exception.
