# Claude Code Implementation Prompt — Phase 2 Local Review Console

Use this only after Phase 1 of the evaluation harness is implemented and all tests pass.

---

Read `CLAUDE.md` and then:

- `docs/implementation/EVAL_HARNESS_V0.md`
- `docs/architecture/RESEARCH_CONSOLE_ARCHITECTURE.md`
- `docs/implementation/NON_DEVELOPER_LOCAL_WORKFLOW.md`
- `specs/SPEC-025-local-review-console.md`
- `evals/CHANGE_CONTROL_PROTOCOL.md`

Implement Phase 2: a minimal local Streamlit review console.

## Constraints

1. Do not modify extraction prompts, scoring rubrics, ontology definitions, or gold records.
2. Do not mutate original prediction files.
3. Do not make external network calls.
4. Do not add authentication or cloud deployment.
5. Use Streamlit standard components only.
6. Store human reviews in SQLite as append-only records.
7. Add tests for persistence and review logic.
8. Stop after the minimal four-page console works.

## Required pages

### 1. Eval overview

Show:

- selected run;
- prompt, model, schema, spec, and code versions;
- cases by split;
- hard-gate status;
- precision/recall metrics;
- evidence validity;
- duplicate rate;
- temporal leakage;
- failures by tag.

### 2. Failure review

Show source evidence, prediction, and expected output side by side.

Support decisions:

- prediction correct;
- gold correct;
- both acceptable;
- both wrong;
- ambiguous source;
- ontology decision required;
- insufficient evidence;
- add to regression set.

Require a reason code and allow a comment.

### 3. Run comparison

Show:

- fixed cases;
- new regressions;
- unchanged failures;
- metric deltas;
- hard-gate differences;
- filters by company, year, split, and failure tag.

### 4. Production review queue

Show records flagged for:

- low confidence;
- unsupported evidence;
- possible duplication;
- wrong granularity;
- unresolved parent link;
- temporal uncertainty;
- extraction-pass disagreement.

## Persistence

Create append-only tables with:

- review ID;
- case ID;
- run ID;
- entity ID;
- reviewer;
- timestamp;
- decision;
- reason code;
- comment;
- original value;
- reviewed value.

Never overwrite the original model output or gold fixture.

## Usability

- Add a one-command local launcher, preferably `make research-console`.
- Document setup for a non-developer.
- Display clear empty-state and error messages.
- Keep the visual design simple and readable.

## Completion

After implementation:

1. Run all tests.
2. Run a local smoke test.
3. Show exact commands.
4. List changed files.
5. Document usage.
6. Summarize limitations.
7. Stop. Do not implement later corpus or measurement pages.
