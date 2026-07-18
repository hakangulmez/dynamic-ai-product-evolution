# Task Role Classification

## Governing spec

`SPEC-011`

## System instruction

Classify each validated task's importance to the product's customer value proposition.

Labels:

- `core`: a central reason customers buy or use the product; removing it would materially change the product category or value proposition.
- `major_supporting`: materially enables, completes, or differentiates the core workflow.
- `peripheral`: convenience, administration, optional enhancement, or narrow edge feature.
- `unknown`: evidence insufficient.

Do not use task count, text length, novelty, AI wording, or technical complexity as importance evidence.

Return label, concise evidence-based rationale, source IDs, confidence, and any product-level ambiguity.
