# SPEC-026 — Master Notebook Orchestration

## Status

Accepted design; scaffold implemented.

## Objective

Provide one canonical, executable, human-readable notebook that documents and safely
orchestrates the complete research pipeline without duplicating production logic.

## Inputs

- `configs/project.yaml`
- `configs/master_notebook.yaml`
- `configs/pipeline_stages.yaml`
- governing specs, schemas, prompts, and stage scripts
- existing run and eval reports

## Outputs

- an interactive workflow view;
- preflight and registry validation results;
- dry-run or executed stage commands;
- immutable notebook run summaries under `data/runs/`;
- links to expected stage outputs and validation gates.

## Required behaviors

1. Default to non-executing `status` mode.
2. Identify every stage by a stable two-digit ID.
3. Show the script, governing spec, inputs, outputs, status, and acceptance gate.
4. Refuse stub execution unless explicitly overridden.
5. Respect the repository-level `full_run_enabled` gate.
6. Use shared functions from `src/`; do not implement extraction or scoring in cells.
7. Capture command outputs and block reasons as structured records.
8. Never overwrite an existing run directory.
9. Remain fully usable from VS Code or JupyterLab.
10. Include explanations suitable for a non-developer methodology owner.

## Non-goals

- replacing the Streamlit review console;
- editing gold labels or production records directly;
- embedding API keys;
- hiding pipeline logic in notebook state;
- automatically approving a failed eval gate.

## Acceptance tests

- the notebook is valid `nbformat` JSON;
- required section headings are present;
- every registry stage points to an existing script and spec;
- stage IDs are unique;
- status mode runs without paid APIs or external network access;
- stub-stage execution is blocked by default;
- tests validate registry and notebook integrity.
