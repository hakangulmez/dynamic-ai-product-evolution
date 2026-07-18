# Obsidian and Streamlit Local Setup

## Purpose

The project uses two complementary interfaces:

```text
Obsidian
  → methodology navigation, concepts, decisions, research notes

Streamlit Research Console
  → structured status, evaluation reports, evidence review, adjudication
```

Obsidian is not the canonical structured-data store. Streamlit is not the place where methodology is rewritten. VS Code, Git, repository files, and the evaluation harness remain the canonical implementation environment.

## Recommended local layout

```text
~/Research/dynamic-ai-product-evolution/
  ├── RESEARCH_HOME.md
  ├── docs/
  ├── specs/
  ├── prompts/
  ├── evals/
  ├── apps/research_console/
  └── .venv/
```

## One-time Python and Streamlit setup

From Terminal, inside the repository:

```bash
./scripts/setup_local.sh
```

The script:

1. creates `.venv` if needed;
2. activates the virtual environment;
3. upgrades `pip`;
4. installs the project with development, notebook, and UI dependencies.

Manual equivalent:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev,notebook,ui]'
```

## Launch Streamlit

```bash
source .venv/bin/activate
make ui
```

Equivalent direct command:

```bash
streamlit run apps/research_console/app.py
```

The browser should open a local page. The current app is intentionally read-only and only confirms that:

- the repository can be found;
- the stage registry can be loaded;
- the local Streamlit environment works;
- canonical project documents are discoverable.

It does not yet run model APIs, modify data, or store review decisions.

## Launch the master notebook

```bash
source .venv/bin/activate
make notebook
```

Open and run:

```text
notebooks/00_MASTER_PIPELINE.ipynb
```

The notebook remains the canonical literate end-to-end workflow. Streamlit is the interactive review layer, not a substitute for the notebook.

## Install and open Obsidian on macOS

1. Install the Obsidian desktop application.
2. Open Obsidian.
3. Choose **Open folder as vault**.
4. Select the repository root: `dynamic-ai-product-evolution/`.
5. Open `RESEARCH_HOME.md`.
6. Pin the note or bookmark it as the main research map.

Opening the repository root avoids duplicated Markdown files. `docs/`, `specs/`, `prompts/`, and `evals/` remain a single source of truth shared by Obsidian, VS Code, Git, and Claude Code.

## Recommended Obsidian settings

Start with built-in features only. Community plugins are not required.

Recommended:

- enable backlinks;
- enable outgoing links;
- enable graph view only when useful;
- use Live Preview or Reading View according to preference;
- exclude noisy generated directories from search where possible:
  - `.venv/`
  - `data/raw/`
  - `data/snapshots/`
  - `data/runs/`
  - `artifacts/`
  - `evals/reports/`

Avoid editing generated JSON, Parquet, SQLite, or run artifacts through Obsidian.

## What belongs in each interface

| Activity | Primary interface |
|---|---|
| Read methodology and specs | Obsidian |
| Record a conceptual decision | Markdown decision log / Obsidian |
| Edit code or prompts | VS Code |
| Ask Claude Code to implement a bounded spec | VS Code terminal |
| Run the end-to-end workflow | Master notebook |
| Inspect eval metrics and failures | Streamlit |
| Approve or correct structured records | Streamlit after Phase 2 |
| Analyze final tables | Notebook / analysis scripts |

## Safe staged rollout

### UI Stage 0 — available now

- setup/status console;
- stage registry view;
- canonical documentation links;
- no data mutations.

### UI Stage 1 — after eval harness

- eval overview;
- hard-gate status;
- deterministic validation findings;
- run comparison.

### UI Stage 2 — after append-only review storage

- evidence/prediction/gold side-by-side review;
- reason-coded adjudication;
- regression-case promotion;
- production review queue.

### UI Stage 3 — after extraction pilot

- product–capability–task explorer;
- source explorer;
- longitudinal task timeline;
- measurement lab.

## Troubleshooting

### `streamlit: command not found`

Activate the environment:

```bash
source .venv/bin/activate
```

Then retry:

```bash
make ui
```

### Python version is too old

The repository requires Python 3.11 or newer. Confirm with:

```bash
python3 --version
```

### The Streamlit page opens but shows missing registry

Confirm that the app was launched from the repository and that this file exists:

```text
configs/pipeline_stages.yaml
```

### Obsidian shows too much noise

Use Obsidian's excluded-files setting for generated and data directories. Do not create a second copied vault; preserve the repository as the single source of truth.
