# Master Notebook Architecture

## Decision

The repository has one canonical notebook, `notebooks/00_MASTER_PIPELINE.ipynb`, that
explains and orchestrates the full research pipeline from company-universe construction
to final analysis.

This is a **literate control plane**, not a monolithic implementation notebook.

## Why this is useful

A single, carefully structured notebook gives a non-developer researcher a stable place
to answer five questions:

1. What stage of the project are we currently in?
2. Which script implements each stage?
3. Which spec, prompt, schema, source policy, and eval gate govern it?
4. What inputs and outputs should exist before and after the stage?
5. Which exact command was run, with what result and run manifest?

It reduces the temptation to make untracked changes directly inside output files or to
run isolated scripts without understanding their dependencies.

## Separation of responsibilities

| Layer | Responsibility |
|---|---|
| Master notebook | Explanation, stage selection, safe orchestration, preflight, summaries |
| `configs/pipeline_stages.yaml` | Canonical stage registry and readiness status |
| `src/dynamic_ai_products/` | Reusable implementation logic |
| `pipelines/` | Thin numbered command-line entry points |
| `tests/` and `evals/` | Deterministic checks, gold comparisons, regression gates |
| Streamlit Research Console | Human review, adjudication, and run comparison |
| `data/runs/` | Immutable run records, logs, manifests, and reports |

## Non-negotiable rule

Production business logic must not live only in a notebook cell. A cell may import and
call a function, display a result, or construct a command. It must not become the only
place where extraction, matching, scoring, or aggregation behavior exists.

## Execution modes

The notebook reads `configs/master_notebook.yaml`.

- `status`: validate and display; do not execute stages.
- `selected`: run only explicitly listed stages.
- `sentinel`: intended for a small validated pilot once stage implementations exist.
- `full`: reserved for a frozen pipeline and additionally constrained by
  `configs/project.yaml: full_run_enabled`.

The current repository defaults to `status`.

## Stage readiness

Every stage has one status:

- `stub`: design placeholder; execution blocked.
- `sentinel`: implemented for a limited pilot and under active evaluation.
- `ready`: implementation and required eval thresholds pass.
- `frozen`: version accepted for the declared production run.

The notebook must never silently convert one status into another.

## Run records

When execution is enabled, the notebook creates an immutable directory under
`data/runs/<timestamp>_master-notebook/`. It records:

- repository commit;
- project and registry versions;
- selected stages;
- commands;
- return codes;
- stdout and stderr logs;
- stage-level block reasons;
- final summary.

Original stage outputs are never overwritten by notebook review cells.

## Relationship to eval-first development

The notebook is deliberately downstream of the eval harness. It should display eval
reports and block unsafe stages, not replace the harness with subjective inspection.
The intended loop remains:

```text
failure → eval case → change request → implementation/prompt change
→ full comparison → release decision → stage status update
```
