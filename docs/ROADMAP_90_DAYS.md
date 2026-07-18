# 90-Day Roadmap

## Weeks 1–2 — Governance and evaluation foundation

Deliverables:

- accepted project charter, source policy, temporal policy, and ontology;
- prompt-development and change-control protocol;
- evaluation-case schema;
- deterministic validators;
- development, adversarial, frozen, and regression split structure;
- immutable run-manifest and comparison design;
- local Claude Code safety workflow.

Exit criterion: a prompt change can be tested, compared, accepted, or rejected without manually editing previous outputs.

## Week 3 — Minimal evaluation harness

Implement:

- eval runner CLI;
- structured findings;
- product/capability/task precision and recall;
- evidence and temporal hard gates;
- Markdown and JSON reports;
- at least twelve hand-readable fixtures.

Exit criterion: Phase 1 tests pass and a candidate run can be compared with an accepted baseline.

## Week 4 — Local review console v0

Implement the four-page local Streamlit console:

- eval overview;
- failure review;
- run comparison;
- production review queue.

Use append-only SQLite reviews. No raw outputs or gold records may be overwritten.

Exit criterion: the researcher can inspect evidence, prediction, and expected output without editing JSON manually.

## Weeks 5–6 — Corpus pilot

Implement:

- SEC discovery and ingestion;
- official-web discovery;
- snapshotting and hashing;
- normalization and passage indexing;
- source coverage reporting.

Pilot: six heterogeneous firms across 2022–2026.

Exit criterion: required source categories are retrieved or explicitly marked unavailable; no temporal leakage appears in audit.

## Weeks 7–8 — Product and capability extraction

Implement high-recall discovery and high-precision consolidation under the eval harness.

Create blinded gold cases and permanent regression cases for observed failures.

Exit criterion: accepted product and capability precision/recall with low packaging and marketing-language inflation.

## Weeks 9–10 — Task extraction and longitudinal matching

Implement:

- task discovery and consolidation;
- customer-need representation;
- core/major-supporting/peripheral role classification;
- yearly entity resolution;
- transition matching;
- split and merge handling.

Exit criterion: task granularity, evidence validity, and transition reliability pass sentinel thresholds.

## Week 11 — Provisional measurement pilot

Build dated frontier registry and evaluate separate rubrics for:

- frontier task replicability;
- AI transformation depth;
- deployment scale;
- task-specific defensibility.

Do not create a single final composite. Deep adoption is not treated as beneficial by definition.

## Week 12 — Ablations, freeze decision, and next-stage plan

Run:

- Item 1 only versus enriched official corpus;
- model and prompt comparisons;
- temporal-leakage adversarial tests;
- source-type contribution analysis;
- anchor-firm construct review.

Freeze only the stages that pass their gates. Choose the production universe based on source cost, extraction quality, and review capacity.
