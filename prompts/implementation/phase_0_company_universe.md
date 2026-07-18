# Claude Code Implementation Task — Phase 0 Company Universe

Read `CLAUDE.md` first. Then read:

- `docs/methodology/SOFTWARE_FIRM_UNIVERSE.md`
- `docs/architecture/COMPANY_UNIVERSE_PIPELINE.md`
- `specs/SPEC-001-company-universe.md`
- `configs/universe_taxonomy.yaml`
- `configs/universe_sample_rules.yaml`
- `evals/rubrics/UNIVERSE_CLASSIFICATION_RUBRIC.md`
- `schemas/company_universe_classification.schema.json`
- `schemas/firm_year_eligibility.schema.json`
- `schemas/firm_lineage.schema.json`
- `schemas/universe_run_manifest.schema.json`

## Goal

Implement only the local, testable sentinel infrastructure for Stage 00. Do not run a full EDGAR universe job, do not call paid LLM APIs, and do not perform product/task extraction.

## Constraints

1. Work only inside this repository.
2. Do not import legacy code, prompts, labels, or outputs.
3. Do not make external network calls in this phase.
4. Preserve all inputs and outputs immutably.
5. Every exclusion and tier assignment must have a structured reason or rule trace.
6. No current-web evidence may enter baseline packets.
7. Use simple Python, JSON/JSONL, Parquet where available, and pytest.
8. Do not hide unresolved cases; emit `UNKNOWN` or review records.
9. Do not implement a polished UI.
10. Stop after the sentinel infrastructure and tests are complete.

## Deliverables

### A. Typed data models and schema validation

Implement models for:

- historical annual filer;
- deterministic issuer-filter decision;
- baseline evidence packet;
- high-recall screen output;
- company-universe classification;
- rule trace;
- firm-year eligibility;
- firm lineage;
- universe run manifest.

### B. Deterministic tier rules

Load `configs/universe_sample_rules.yaml` and derive Tier A/B/C, excluded, or uncertain without an LLM. Return the exact rules evaluated and the reason for the result.

### C. Local sentinel fixture runner

Build a runner that loads synthetic/local fixtures only and can execute:

- deterministic issuer filters;
- evidence-packet validation;
- precomputed screen/classifier outputs;
- sample-rule derivation;
- boundary routing;
- negative-audit sampling;
- manifest creation.

### D. Evaluation fixtures

Create structured fixtures covering at least the twelve cases in `evals/adversarial/UNIVERSE_BOUNDARY_CASES.md`, plus:

- fund;
- shell/pre-combination SPAC;
- acquired/delisted baseline incumbent;
- ticker/name change;
- post-baseline entrant;
- duplicate share class;
- insufficient evidence;
- mixed firm with and without segment separability.

### E. Tests

Test:

- schemas and enums;
- temporal cutoff validation;
- deterministic exclusions;
- Tier A/B/C rules;
- unknown preservation;
- CIK deduplication;
- lineage behavior;
- exited-firm retention;
- negative-audit reproducibility from a seed;
- immutable manifest behavior;
- no post-cutoff evidence.

### F. Documentation

Create `docs/implementation/COMPANY_UNIVERSE_SENTINEL_V0.md` describing exact commands, file structure, fixture format, output interpretation, current limitations, and the later network-enabled SEC ingestion phase.

## Before coding

- inspect the repository;
- identify conflicts among schemas, taxonomy, sample rules, and pipeline registry;
- write a concise implementation plan;
- resolve only implementation inconsistencies, not open research decisions.

## After coding

- run all tests;
- show commands and results;
- show the new file tree;
- state what is still a stub;
- stop before downloading SEC data or invoking models.
