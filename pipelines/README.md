# Pipelines

These numbered files are thin stage entry points. Each production implementation must
call reusable code from `src/dynamic_ai_products/`, check its governing spec, source
manifest hash, schema version, and required eval gates.

The initial files are placeholders and intentionally refuse production execution.
Their current readiness is declared in `configs/pipeline_stages.yaml`.

Use `notebooks/00_MASTER_PIPELINE.ipynb` as the canonical human-readable workflow and
safe orchestration interface. Do not move production logic into notebook cells.
