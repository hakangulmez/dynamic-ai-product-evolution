# Extraction Methodology

## Objective

Produce a faithful, evidence-grounded representation of what customers could buy or use at each observation date, without evaluating AI exposure or business success.

## Multi-pass design

### Pass 0 — Source packet validation

Confirm temporal validity, source types, and coverage. No extraction occurs if the packet violates cutoff rules.

### Pass 1 — Product discovery, high recall

Extract all plausible customer offerings with evidence, including uncertain candidates.

### Pass 2 — Product consolidation, high precision

Remove packaging-only entities, duplicates, delivery variants, and unsupported roadmap items. Resolve product-family boundaries.

### Pass 3 — Capability extraction

For each validated product, extract concrete functions and evidence. Ignore generic benefit language.

### Pass 4 — Task discovery, high recall

Translate capabilities into customer jobs. Preserve distinct customer outcomes.

### Pass 5 — Task consolidation, high precision

Merge semantic duplicates, split over-broad combined jobs, remove internal work and marketing abstractions, and verify evidence.

### Pass 6 — Task-role classification

Assign core, major supporting, or peripheral based on product descriptions and commercial positioning.

### Pass 7 — Human or independent-model audit

Review ambiguity, granularity, and evidence coverage before longitudinal matching.

## Source use

All supplied official documents may contribute, but the output must state which source supports each claim. A product page can add a concrete feature absent from Item 1; a filing can establish portfolio importance and continuity.

## AI language

The extraction prompt may use AI terms to locate passages but must extract the actual function:

```text
“AI-powered productivity” → insufficient
“summarizes documents and answers questions with citations” → capability and task evidence
```

## Aspirations

Future plans are stored as announced status only when they describe a concrete product or capability. They do not enter the active-task universe until availability evidence exists.

## Output discipline

- Structured JSON only in production.
- Every entity has stable candidate IDs.
- Evidence quotes are short and verbatim.
- Unknown fields remain null or `unknown`.
- Reasoning is concise and audit-oriented, not chain-of-thought.
