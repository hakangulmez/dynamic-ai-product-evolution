# Dynamic AI Product Evolution

A clean-room research repository for constructing a longitudinal, evidence-grounded dataset of how software firms' customer-facing products, capabilities, and tasks evolved during the frontier-LLM transition.

The repository is intentionally separate from all prior exposure-scoring work. It does **not** inherit earlier prompts, taxonomies, scores, or outputs. The initial goal is to build a reproducible `firm × observation date × product × capability × task` universe from dated official sources. Measurement and scoring are downstream layers and remain versioned, testable, and replaceable.

## Research objective

The project studies three related but distinct phenomena:

1. **Frontier task replicability:** Could the frontier model available at the observation date satisfy the customer's underlying task without the focal firm's product?
2. **AI transformation depth and scale:** How deeply and broadly did the firm integrate AI into customer-facing product workflows?
3. **Task-specific defensibility:** Did the transformed product retain or create meaningful differentiation, execution capability, workflow state, data advantage, or switching friction?

The central empirical object is not an AI word count and not a single firm-level score. It is a dated product–capability–task graph with source provenance and longitudinal transitions.

## Start here

Read in this order:

1. [`NEW_CHAT_BOOTSTRAP.md`](NEW_CHAT_BOOTSTRAP.md)
2. [`CLAUDE.md`](CLAUDE.md)
3. [`notebooks/00_MASTER_PIPELINE.ipynb`](notebooks/00_MASTER_PIPELINE.ipynb)
4. [`docs/THESIS_METHODOLOGY_AND_DATA.md`](docs/THESIS_METHODOLOGY_AND_DATA.md)
5. [`docs/literature/COMPREHENSIVE_LITERATURE_REVIEW.md`](docs/literature/COMPREHENSIVE_LITERATURE_REVIEW.md)
5. [`docs/PROJECT_CHARTER.md`](docs/PROJECT_CHARTER.md)
6. [`docs/CONCEPTUAL_FRAMEWORK.md`](docs/CONCEPTUAL_FRAMEWORK.md)
7. [`docs/SOURCE_POLICY.md`](docs/SOURCE_POLICY.md)
8. [`docs/TEMPORAL_POLICY.md`](docs/TEMPORAL_POLICY.md)
9. [`docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`](docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md)
10. [`docs/methodology/EXTRACTION_METHODOLOGY.md`](docs/methodology/EXTRACTION_METHODOLOGY.md)
11. [`docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`](docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md)
12. [`evals/EVAL_HARNESS.md`](evals/EVAL_HARNESS.md)
13. [`docs/implementation/NON_DEVELOPER_LOCAL_WORKFLOW.md`](docs/implementation/NON_DEVELOPER_LOCAL_WORKFLOW.md)
14. The relevant implementation spec under [`specs/`](specs/)

For the next implementation step, use:

- [`prompts/implementation/phase_1_eval_harness.md`](prompts/implementation/phase_1_eval_harness.md)
- then [`prompts/implementation/phase_2_review_console.md`](prompts/implementation/phase_2_review_console.md)


## Local research interfaces

The repository supports three complementary local interfaces:

- **Obsidian:** open the repository root as a vault and start from [`RESEARCH_HOME.md`](RESEARCH_HOME.md).
- **Streamlit:** run the local read-only setup console with `make ui` after `make setup`.
- **Jupyter:** use [`notebooks/00_MASTER_PIPELINE.ipynb`](notebooks/00_MASTER_PIPELINE.ipynb) as the canonical end-to-end workflow.

Setup instructions are in [`docs/implementation/OBSIDIAN_AND_STREAMLIT_SETUP.md`](docs/implementation/OBSIDIAN_AND_STREAMLIT_SETUP.md).

## Master workflow notebook

[`notebooks/00_MASTER_PIPELINE.ipynb`](notebooks/00_MASTER_PIPELINE.ipynb) is the
canonical end-to-end workflow view. It explains every pipeline stage, links the relevant
script and spec, runs registry/preflight checks, safely launches selected stages, and
records run summaries. It defaults to non-executing status mode because the numbered
pipeline scripts are still design stubs.

Production logic stays in `src/` and `pipelines/`; the notebook is the orchestration and
explanation layer.

## High-level pipeline

```text
Company universe
  → dated source discovery
  → immutable snapshots
  → normalization and passage indexing
  → product discovery and consolidation
  → capability extraction
  → customer-facing task discovery and consolidation
  → task-role classification
  → longitudinal entity resolution and transition matching
  → dated frontier-baseline assignment
  → task-level measurement
  → aggregation, descriptive analysis, and later outcome analysis
```

## Core design rules

- Extraction and measurement are separate.
- AI wording alone never proves adoption, depth, scale, or advantage.
- Every factual observation must cite a dated official source passage.
- Missing evidence becomes `unknown`, not an inferred score.
- Historical observations use only information available on or before the cutoff date.
- Product pages and documentation may enrich Item 1, but the source universe and temporal rules are fixed in advance.
- Full-universe runs are prohibited until sentinel evaluations pass.

## Repository status

This repository is a **design-complete scaffold**, not a finished production pipeline. It contains:

- governance and methodology documents;
- 26 implementation specifications;
- JSON schemas;
- source-collection playbooks;
- extraction, matching, measurement, adjudication, and evaluation prompts;
- operational skills;
- a structured prompt-development protocol, evaluation-harness design, change-control templates, and implementation prompts;
- minimal Python scaffolding, contamination checks, a local-console architecture, and a non-developer implementation workflow;
- a 90-day build roadmap.

No production dataset is included.

## Immediate implementation priority

1. Build Phase 1 of the deterministic evaluation harness.
2. Build the minimal local Streamlit review console.
3. Begin corpus and extraction pilots only after the harness is usable.

Prompt changes must follow the case → change request → full comparison → release decision workflow.
