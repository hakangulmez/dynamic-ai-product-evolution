# Local Research Console Architecture

## Objective

The project needs a local interface that makes source evidence, extraction outputs, evaluation failures, human corrections, longitudinal links, and later measurements inspectable without requiring the researcher to edit JSON files manually.

The interface is not a public product and not a replacement for the pipeline. It is a local research workbench designed for one primary researcher and occasional collaborators.

## Tool roles

The recommended environment has three distinct interfaces:

```text
VS Code + Claude Code
  → implementation, tests, pipelines, Git, structured files

Obsidian
  → methodology, concepts, decisions, company notes, research navigation

Streamlit Research Console
  → source review, extraction review, eval comparison, adjudication, run monitoring
```

Each tool has one primary role. The same data should not be copied into three independent systems.

## Why Obsidian is not the main annotation system

Obsidian is useful for:

- navigating Markdown methodology and specifications;
- linking concepts such as replicability, transformation depth, scale, and defensibility;
- maintaining decision logs and research notes;
- creating company case-study notes;
- visualizing conceptual links and project status.

Obsidian is not the canonical system for:

- approving thousands of structured records;
- validating JSON schemas;
- preserving immutable predictions;
- comparing prompt versions;
- writing append-only adjudication records;
- enforcing source and temporal constraints;
- running extraction pipelines.

The repository Markdown may be opened as an Obsidian vault or linked into a small vault, but canonical structured data remains in files and the operational database.

## Why Streamlit

Streamlit is suitable for the first local console because:

- the repository is Python-based;
- it supports multipage applications;
- tables and editable fields can be built quickly;
- no separate frontend framework is required;
- it can run entirely on localhost;
- it can read SQLite, Parquet, JSON, and evaluation reports;
- the user can operate it through a browser without writing code.

A later migration to a custom React or web framework is unnecessary unless the project becomes multi-user or requires complex annotation workflows.

## Data architecture

```text
Immutable raw sources
  → filesystem snapshots

Normalized documents and passages
  → Parquet or JSONL

Operational review state
  → SQLite

Analysis-ready tables
  → Parquet

Interactive analytical queries
  → DuckDB

Model and eval run artifacts
  → immutable versioned directories
```

### Canonical principles

1. The user interface never modifies raw source files.
2. The user interface never overwrites original model predictions.
3. Human decisions are stored as append-only review records.
4. A consolidated accepted view is derived from originals plus reviews.
5. Every displayed result links back to source, passage, run, prompt, and schema identifiers.

## Proposed application structure

```text
apps/research_console/
├── app.py
├── README.md
├── pages/
│   ├── 01_eval_overview.py
│   ├── 02_failure_review.py
│   ├── 03_run_comparison.py
│   ├── 04_production_review.py
│   ├── 05_source_explorer.py
│   ├── 06_product_task_universe.py
│   ├── 07_longitudinal_timeline.py
│   └── 08_measurement_lab.py
├── components/
│   ├── evidence_panel.py
│   ├── entity_diff.py
│   ├── task_editor.py
│   ├── source_viewer.py
│   ├── run_summary.py
│   └── review_controls.py
└── services/
    ├── database.py
    ├── eval_service.py
    ├── review_service.py
    ├── source_service.py
    └── run_service.py
```

Only the first four pages belong in the initial implementation.

## Phase 1 pages

### 1. Eval overview

Displays one selected evaluation run:

- prompt and schema versions;
- model and code commit;
- number of cases by split;
- hard-gate status;
- precision and recall by entity type;
- evidence validity;
- duplicate rate;
- temporal-leakage count;
- failures by tag;
- fixed and regressed cases relative to the accepted version.

The page must make critical failures visible even when average metrics are high.

### 2. Failure review

Displays three synchronized panels:

```text
Source evidence | Model prediction | Gold/expected record
```

Required actions:

- approve prediction;
- approve gold;
- mark both acceptable;
- edit expected record;
- mark ambiguous source;
- flag ontology decision;
- add case to regression set.

Each decision requires a reason code and permits an optional comment.

### 3. Run comparison

Compares two run IDs:

- fixed cases;
- new regressions;
- unchanged failures;
- newly introduced entities;
- removed entities;
- metric deltas;
- hard-gate differences;
- results by firm, year, source type, and failure tag.

The interface must not reduce comparison to one aggregate score.

### 4. Production review queue

Shows non-gold extraction records that require human review due to:

- low confidence;
- unresolved evidence;
- possible duplication;
- broad or narrow granularity;
- temporal uncertainty;
- unresolved parent product or capability;
- disagreement between extraction passes;
- invalid schema repair;
- model-to-model disagreement.

Review edits create new review records and do not mutate production outputs.

## Later pages

### Source explorer

Allows the researcher to filter by company, observation date, source type, publication date, and retrieval status. It shows raw and normalized text and all entities supported by a passage.

### Product–task universe

Displays:

```text
Company
  → Product family
  → Product
  → Capability
  → Customer-facing task
```

Each node shows first-seen date, last-seen date, availability, source evidence, review status, and longitudinal links.

### Longitudinal timeline

Shows products and tasks across observation dates and lets the researcher adjudicate:

- same;
- renamed;
- expanded;
- contracted;
- AI-assisted;
- workflow-integrated;
- agentified;
- split;
- merged;
- replaced;
- discontinued;
- new;
- uncertain.

### Measurement lab

Shows task-level measurement components separately:

- frontier task replicability;
- AI transformation depth;
- deployment breadth and scale;
- task-specific defensibility;
- task role and commercial importance;
- confidence and unresolved evidence.

No composite should be displayed as the only result.

## Operational database

SQLite is sufficient for the local single-user version. Proposed tables:

```text
review_sessions
review_decisions
review_field_changes
ontology_questions
regression_promotions
run_annotations
ui_preferences
```

Canonical extraction tables may be read from Parquet/JSONL rather than duplicated into SQLite.

### Append-only review model

A review record should include:

```yaml
review_id:
case_id:
run_id:
entity_id:
reviewer:
timestamp:
decision:
reason_code:
comment:
original_value:
reviewed_value:
source_ids:
passage_ids:
```

Editing a review creates a superseding record rather than deleting the old one.

## Interface principles

- Evidence first: source text is always visible near a claim.
- No hidden mutation: original prediction and gold record remain accessible.
- Low cognitive load: the researcher reviews one failure class or queue at a time.
- Stable filters: company, year, source type, prompt version, failure tag, split.
- Explicit uncertainty: unknown and ambiguous are first-class states.
- No score steering: financial outcomes are not shown during extraction or measurement adjudication.
- Local only: no authentication or deployment complexity in the initial version.

## Minimal local launch

The final implementation should support one command such as:

```bash
make research-console
```

or:

```bash
streamlit run apps/research_console/app.py
```

The browser should open at a localhost address. No cloud service is required.

## Development phases

### UI v0 — Evaluation console

Build only after Phase 1 of the eval harness works.

Includes:

- eval overview;
- failure review;
- run comparison;
- production review queue;
- SQLite review persistence.

### UI v1 — Corpus and extraction review

Add:

- source explorer;
- product/capability/task tree;
- batch review;
- evidence highlighting;
- task-role editor.

### UI v2 — Longitudinal review

Add:

- timeline;
- predecessor/successor links;
- split/merge editor;
- transition review.

### UI v3 — Measurement and thesis outputs

Add:

- task-level measurement lab;
- firm comparisons;
- audit packet export;
- descriptive figures and tables.

## Non-goals

The first interface will not include:

- public deployment;
- authentication;
- multi-user concurrency;
- custom React components;
- direct editing of raw sources;
- automatic acceptance of model output;
- paid-model calls from the browser;
- regression or financial-analysis dashboards before data freeze.

## Acceptance criteria for the first console

- It opens locally with one documented command.
- It can read a completed eval report.
- It shows source, prediction, and expected record side by side.
- It writes append-only reviews to SQLite.
- It compares two run versions.
- It never changes original run files.
- Database operations and persistence are tested.
- A non-developer can follow the setup guide without modifying code.
