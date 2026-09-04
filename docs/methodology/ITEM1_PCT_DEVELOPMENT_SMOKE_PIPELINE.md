# Item 1 PCT Development Smoke Pipeline

## Status and scope

This document identifies the current development candidate for Item 1 PCT
extraction. It is a bounded five-firm smoke pipeline, not a production route,
a full-universe run, or a scoring decision. Its output is an Item 1-visible
product--capability--task map: it does not claim to be complete product history.

The pipeline uses only the verified Item 1 packet from the filing observation.
All model-selected `P001`-style references are resolved and validated by the
pipeline; the model does not author quotations, offsets, or hashes.

## Active chain

The active chain has three model stages, in this order.

1. **Product structure discovery**
   - Prompt: `prompts/extraction/pct_item1_product_structure_v1.md`
   - Contract: `schemas/pct_item1_product_structure_output.v1.schema.json`
   - Runner: `src/dynamic_ai_products/pct_product_structure_smoke.py`
   - Output: high-recall local product-family and product candidates. This is
     working material, not an economic-product finding.

2. **Economic products and capabilities**
   - Prompt: `prompts/extraction/pct_item1_economic_product_capability_v3.md`
   - Contract: `schemas/pct_item1_economic_product_capability_output.v1.schema.json`
   - Validator: `src/dynamic_ai_products/pct_economic_product_capability.py`
   - Runner: `src/dynamic_ai_products/pct_two_stage_smoke.py`
   - Input: the complete Item 1 packet plus the fixed discovery map.
   - Output: commercially distinct economic products and product-local
     capabilities, while accounting for every discovery product candidate.

3. **Customer tasks**
   - Prompt: `prompts/extraction/pct_item1_tasks_flat_v5.md`
   - Contract: `schemas/pct_item1_tasks_flat_output.v2.schema.json`
   - Validator: `src/dynamic_ai_products/pct_task_smoke.py`
   - Runner: `src/dynamic_ai_products/pct_two_stage_smoke.py`
   - Input: the fixed stage-2 product/capability map and only the Item 1
     passages selected by that map. It cannot revise the preceding map.
   - Output: product-local customer tasks linked to one or more product-local
     capabilities.

The active tests are:

- `tests/dev30/test_pct_product_structure.py`
- `tests/dev30/test_pct_economic_product_capability.py`
- `tests/dev30/test_pct_task_smoke.py`
- `tests/dev30/test_pct_two_stage_smoke.py`

## Reproducing the recorded smoke chain

The verified predecessor discovery run is:

`data/runs/pct-item1-product-structure-smokes/pct-item1-product-structure-smoke-v4-normalized-parents-20260903/`

It has five extracted rows and its records file SHA-256 is
`6e38f3a36738b414c66486406579eec2d0e081ad279ae28fcff2c2e4e81c911a`.

The current two-stage result is:

`data/runs/pct-item1-two-stage-smokes/pct-item1-two-stage-smoke-v8-selected-evidence-tasks-20260904/`

It records five extracted stage-2 maps, uses the V3 product/capability prompt
and V5 task prompt, and pins their prompt hashes in its manifest. The two-stage
runner can be reproduced with the following form; a fresh run must receive a
new run ID and never overwrite the archived result.

```bash
PYTHONPATH=src python -m dynamic_ai_products.pct_two_stage_smoke \
  --run-id NEW_RUN_ID \
  --discovery-run-dir data/runs/pct-item1-product-structure-smokes/pct-item1-product-structure-smoke-v4-normalized-parents-20260903 \
  --vertex-project VERTEX_PROJECT_ID \
  --product-capability-prompt prompts/extraction/pct_item1_economic_product_capability_v3.md \
  --task-prompt prompts/extraction/pct_item1_tasks_flat_v5.md \
  --live
```

## Current boundary

V8 is the current development checkpoint because all five rows validate and
the task stage is constrained to upstream-selected evidence. It is not yet a
full-run approval. The Adobe smoke result shows two cross-product repeated
tasks. A repeated task is valid when separately supported products enable the
same customer job; however, products with the same Item 1 evidence and the
same undifferentiated capability still need an economic-product consolidation
decision before a full-universe design is frozen.
