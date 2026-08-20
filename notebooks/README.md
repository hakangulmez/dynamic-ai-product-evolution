# Notebooks

## Primary entry point

Open [`00_MASTER_PIPELINE.ipynb`](00_MASTER_PIPELINE.ipynb) first. It is the project's
**literate orchestration layer**: one place to understand the complete workflow,
inspect stage readiness, run preflight checks, launch selected pipeline stages, and
review outputs and gates.

The notebook does **not** contain production extraction or measurement logic. That
logic belongs in `src/` and the numbered scripts under `pipelines/`. Keeping logic out
of the notebook prevents hidden state, copy-pasted code, and irreproducible manual
changes.

## Reproducibility walkthrough

[`01_STAGE00_UNIVERSE_AND_SCREEN_REPRODUCIBILITY.ipynb`](01_STAGE00_UNIVERSE_AND_SCREEN_REPRODUCIBILITY.ipynb)
is a separate, read-only walkthrough of the completed Stage 00 corpus and the
high-recall-screen readiness chain. It re-hashes and reconciles the canonical
v5 packet corpus and canary selection, and summarizes receipt-bearing canaries.
It never invokes a model, SEC endpoint, or pipeline run; a printed command is a
template, not an execution cell.

## Safe default behavior

The notebook opens in `status` mode. In this mode it:

1. locates the repository;
2. loads project and stage configuration;
3. validates that every stage points to a real spec and script;
4. displays the end-to-end workflow and current stage status;
5. prepares commands without executing pipeline stages.

All pipeline stages are currently marked `stub`. The notebook will refuse to execute
stub stages unless a developer explicitly overrides the safety gate. Change a stage to
`sentinel`, `ready`, or `frozen` in `configs/pipeline_stages.yaml` only after its governing
spec and eval gates are satisfied.

## Recommended use

- Use the notebook to **understand and operate** the system.
- Use the Streamlit Research Console to **review and adjudicate** extraction results.
- Use `src/`, `pipelines/`, `tests/`, and `evals/` to **implement and validate** logic.
- Commit before and after meaningful workflow runs.

## Starting locally

From the repository root:

```bash
python -m pip install -e '.[dev,notebook]'
jupyter lab notebooks/00_MASTER_PIPELINE.ipynb
```

VS Code can open and run the notebook directly after selecting the project's Python
interpreter.
