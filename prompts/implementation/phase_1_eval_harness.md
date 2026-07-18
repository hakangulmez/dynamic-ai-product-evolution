# Claude Code Implementation Prompt — Phase 1 Evaluation Harness

Copy the prompt below into Claude Code from the repository root.

---

Read `CLAUDE.md` first.

Then read:

- `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`
- `docs/implementation/EVAL_HARNESS_BUILD_PLAN.md`
- `evals/EVAL_HARNESS.md`
- `evals/CHANGE_CONTROL_PROTOCOL.md`
- `specs/SPEC-020-evaluation-harness.md`
- `specs/SPEC-022-evaluation-data-model.md`
- `specs/SPEC-023-deterministic-validation.md`
- `specs/SPEC-024-run-versioning-and-comparison.md`
- `docs/methodology/VALIDATION_STRATEGY.md`
- `docs/methodology/EVIDENCE_AND_CONFIDENCE.md`
- `schemas/task_observation.schema.json`
- `schemas/evaluation_result.schema.json`

We are implementing Phase 1 of the evaluation harness before building the production interface.

## Constraints

1. Work only inside this repository.
2. Do not read or import anything from legacy repositories.
3. Do not modify extraction, matching, or measurement prompts.
4. Do not change methodological definitions or scoring rubrics.
5. Do not make external network calls.
6. Do not invoke paid LLM APIs.
7. Do not overwrite any existing run output.
8. Do not delete files.
9. Every new component must have tests.
10. Use simple Python, JSON/JSONL, SQLite only if needed, and pytest.
11. Prefer clarity over abstraction.
12. Stop after Phase 1; do not implement Streamlit yet.

## Deliverables

### A. Evaluation case schema and Python model

Implement a typed evaluation-case representation containing:

- case ID;
- stage;
- split: dev, frozen_test, adversarial, or regression;
- company ID;
- observation date;
- input source IDs;
- input passage IDs;
- expected entities;
- forbidden entities;
- expected status;
- failure tags;
- notes;
- created by;
- created at;
- guideline version.

Add JSON-schema validation and documented examples.

### B. Deterministic validators

Implement structured validators for:

- JSON/schema validity;
- required fields;
- source ID existence;
- passage ID existence;
- evidence quote substring validity;
- publication date not later than observation cutoff;
- valid product–capability–task hierarchy;
- duplicate IDs and records;
- prohibited legacy fields;
- unsupported customer-facing task records;
- active records supported only by roadmap evidence;
- preservation of original model output and explicit repair records.

Each validator must return structured findings rather than only true or false.

### C. Evaluation runner

Implement a CLI equivalent to:

```bash
python -m dynamic_ai_products.evaluation.runner \
  --cases evals/cases/dev \
  --predictions path/to/predictions.jsonl \
  --output evals/reports/<run_id>
```

The runner must:

- load and validate cases;
- load predictions;
- run deterministic validators;
- compare explicit expected entities with predictions;
- produce a machine-readable JSON report;
- produce a concise Markdown report;
- return a failing exit code for critical gates;
- refuse to overwrite an existing output directory.

### D. Metrics

Implement:

- schema-validity rate;
- evidence-validity rate;
- unsupported-claim rate;
- temporal-leakage count;
- duplicate rate;
- product precision and recall;
- capability precision and recall;
- task precision and recall.

Do not use an LLM judge. Use stable gold IDs and accepted aliases.

### E. Fixtures

Create at least twelve small fixtures covering:

- valid product extraction;
- AI marketing wording only;
- future roadmap capability;
- duplicated task;
- capability/task confusion;
- unsupported task;
- wrong-date evidence;
- valid multi-step workflow execution;
- renamed product;
- bundle versus product;
- internal R&D that is not customer-facing;
- valid customer-facing AI capability.

Fixtures must be readable and explain the expected behavior.

### F. Tests

Add unit and integration tests. Run the complete test suite and fix all failures.

### G. Documentation

Create `docs/implementation/EVAL_HARNESS_V0.md` explaining:

- implemented architecture;
- file structure;
- how to add a case;
- how to run the harness;
- how to interpret reports;
- current limitations;
- Phase 2 work.

## Required process

Before coding:

1. Inspect the repository.
2. Write a short implementation plan.
3. Identify conflicts between existing schemas or specs.
4. Resolve conflicts conservatively without modifying frozen methodology.

After implementation:

1. Run tests.
2. Show exact commands.
3. Show the resulting file tree.
4. List changed files.
5. Summarize limitations and remaining work.
6. Stop. Do not proceed to Phase 2.

## Safety and stopping rules

- Do not read parent or sibling directories.
- Do not read `.env`, secrets, SSH, or cloud credentials.
- Do not install dependencies unless an existing declared dependency is insufficient; ask before adding one.
- Do not run destructive shell commands.
- Stop after the requested phase.
