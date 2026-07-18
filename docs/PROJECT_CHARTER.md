# Project Charter

## Working title

**Dynamic AI Product Evolution: A Longitudinal Product–Capability–Task Dataset for Software Firms**

## Problem statement

Static pre-shock exposure measures describe a firm's initial vulnerability but cannot observe endogenous product redesign. During the frontier-LLM transition, firms may:

- be directly bypassed by general-purpose models;
- add superficial AI features without durable differentiation;
- integrate AI into data, permissions, workflow state, tools, and execution;
- create new AI-native products or orchestration layers;
- pivot away from exposed product categories;
- discontinue, merge, or repackage tasks.

A longitudinal product-task dataset is required to distinguish these paths.

## Primary objective

Construct a reproducible, dated, source-grounded representation of customer-facing products, capabilities, and tasks for a defined universe of software firms, then measure how those tasks change as frontier-model capabilities advance.

## Scientific contribution

The project aims to contribute:

1. A longitudinal product–capability–task ontology.
2. A transparent source architecture combining SEC and dated official product materials.
3. A task-transition dataset distinguishing renaming, expansion, AI assistance, workflow integration, agentification, replacement, and discontinuation.
4. Separate measures of frontier replicability, AI transformation depth, deployment scale, and task-specific defensibility.
5. Descriptive and later econometric evidence on strategic product trajectories.

## Scope

Initial target period: approximately 2022–2026.

Initial target population: publicly listed software and software-enabled technology firms, with exact inclusion rules defined in `SPEC-001`.

Initial source universe:

- SEC filings and exhibits;
- official investor-relations materials;
- official product and developer documentation;
- official release notes and newsroom;
- archived official pages.

## Non-goals for the initial build

- Proving a causal financial effect before validating the data.
- Counting AI mentions as adoption.
- Producing one universal firm score at the extraction stage.
- Inferring technical architecture from marketing language alone.
- Using unrestricted third-party web content in the canonical corpus.
- Labeling firms as winners or losers in gold data.

## Success criteria for version 1

- Source discovery recall and temporal validity pass accepted thresholds on sentinel firms.
- Product, capability, and task extraction achieve acceptable precision/recall and evidence validity.
- Longitudinal matching is reliable enough to separate continuity from true task change.
- Measurement labels show construct validity on blinded anchors without being tuned to financial outcomes.
- Every released observation is reproducible from immutable source snapshots and manifests.

## Governance

Major design decisions require:

- an accepted spec;
- a decision-log entry;
- schema and prompt versioning;
- regression-eval updates;
- an explicit migration plan for existing data.
