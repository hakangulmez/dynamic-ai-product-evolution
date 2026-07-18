# Local Research Console

This directory contains the local Streamlit research interface described in:

- `docs/architecture/RESEARCH_CONSOLE_ARCHITECTURE.md`
- `specs/SPEC-025-local-review-console.md`
- `prompts/implementation/phase_2_review_console.md`

## Current state

`app.py` is a deliberately read-only **pre-harness setup shell**. It confirms that the UI dependency is installed, loads the canonical pipeline stage registry, and links to project documentation.

It does not:

- call a paid model API;
- modify source or extraction data;
- write review records;
- implement evaluation adjudication;
- pretend that Phase 1 of the eval harness already exists.

## Run locally

```bash
./scripts/setup_local.sh
source .venv/bin/activate
make ui
```

## Full Phase 2 implementation gate

The complete review console must begin only after Phase 1 of the evaluation harness passes its tests. The initial full console will contain:

1. Eval overview.
2. Failure review.
3. Run comparison.
4. Production review queue.

Original run files and gold cases must remain immutable. Human decisions will be stored as append-only SQLite records.
