# Claude Code Implementation Prompt — Phase 1 Evaluation Harness

Copy the prompt below into Claude Code from the repository root.

---

Read `CLAUDE.md` first.

## Baseline

1. Record the approved implementation-start commit here at kickoff:
   `IMPLEMENTATION_BASELINE_COMMIT: <fill in the approved commit hash>`.
   Do not begin without an explicitly approved baseline.
2. Verify the working branch, that HEAD equals the recorded baseline commit,
   and that `git status --short --untracked-files=all` is clean.

## Required reading

- `docs/implementation/EVAL_HARNESS_BUILD_PLAN.md` (the binding slice plan)
- `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`
- `evals/EVAL_HARNESS.md`
- `evals/CHANGE_CONTROL_PROTOCOL.md`
- `specs/SPEC-020-evaluation-harness.md`
- `specs/SPEC-022-evaluation-data-model.md`
- `specs/SPEC-023-deterministic-validation.md`
- `specs/SPEC-024-run-versioning-and-comparison.md`
- `specs/SPEC-025-local-review-console.md` (deferred-scope boundary)
- `specs/SPEC-027-adapter-qualification-and-enablement.md` (deferred-scope
  boundary)
- `schemas/evaluation_case.schema.json`
- `schemas/evaluation_result.v2.schema.json`
- `schemas/universe_run_manifest.v2.schema.json`
- `schemas/schema_version_manifest.json` (active Phase 0 contracts — never
  modified during Phase 1)
- `evals/templates/eval_case.template.json`

Then audit the actual package layout (`src/dynamic_ai_products/`, `tests/`,
`evals/fixtures/`) before proposing any file. Extend the existing module
family; do not create a parallel architecture.

## Constraints

1. Work only inside this repository.
2. Do not read or import anything from legacy repositories.
3. Do not modify extraction, matching, or measurement prompts.
4. Do not change methodological definitions, specs, schemas, rubrics, or the
   Decision Log.
5. Do not make external network calls and do not invoke paid model APIs.
6. Do not overwrite any existing run output and do not delete files.
7. Preserve Phase 0 behavior exactly: the universe sentinel suite must stay
   green against untouched fixtures; no writer may emit a successor schema
   format through active Phase 0 paths; and
   `schemas/schema_version_manifest.json` remains byte-for-byte unchanged
   throughout Phase 1 (the build plan's evaluation-only activation boundary).
   Global activation of `universe_run_manifest.v2.schema.json` is a
   separately approved future migration — never part of this prompt.
8. The evaluation package loads `evaluation_case.schema.json` and
   `evaluation_result.v2.schema.json` only through its explicit schema
   registry (`evaluation/schemas.py`), by filename/version — never through
   the active schema-version manifest.
9. Do not modify tests, fixtures, or contracts to conceal a failure; report
   the failure instead.
10. Every new component must have tests. Use simple Python, JSON/JSONL,
    SQLite only if needed, and pytest. Prefer clarity over abstraction.
11. The evaluation artifact root is parametric (`--eval-root` / `eval_root`)
    and required; do not hardcode a default path; if a default ever appears
    necessary, STOP and request a separately approved decision-log/spec
    change — this prompt does not authorize any Decision Log or spec edit.
    Evaluation artifacts never live inside extraction-output directories; ad
    hoc JSONL is never the canonical store.
12. Repository-manifest rule: every slice that adds, removes, or renames a
    tracked path must include, in the same slice, the minimal
    `REPO_MANIFEST.md` entry changes in canonical ordering, the mechanical
    header-count update, and parity/duplicate validation
    (`tests/universe/test_repo_hygiene.py` must stay green). Never postpone
    manifest updates to a later slice.
13. Do not implement the review console, frozen-set access-control
    infrastructure, live source/model adapters, secrets handling, rollout
    execution, monitoring services, or webhook triggers; contracts/stubs only
    where SPEC-025/SPEC-027 already approve them.

## Working method

Implement the slices of `docs/implementation/EVAL_HARNESS_BUILD_PLAN.md` in
order (Slice 1 through Slice 14; reference and scoring/gate-configuration
resolution in Slice 4 must exist before run pinning, assertion dispatch,
metrics, or gates). For every slice:

1. restate the slice objective, governing contracts, and file plan before
   coding;
2. implement the smallest testable unit;
3. run the slice's focused tests, then the full suite:
   `PYTHONPATH=src python -m pytest -q`;
4. run `PYTHONPATH=src python -m dynamic_ai_products.validation`;
5. stage with explicit path-limited `git add` of exactly the slice's files;
6. report the complete diff, `git status --short --untracked-files=all`, and
   full SHA-256 hashes of every changed file;
7. stop for review. Do not continue to the next slice, and do not commit or
   push, without separate explicit approval.

## Binding evaluation semantics

- Evaluation cases are immutable and split-agnostic; assertions are the sole
  scoring contract (kinds: `expected_entity`, `forbidden_entity`,
  `field_value`, `evidence_provenance`, `deterministic_validation`).
- Assertion identity uses a semantic version, a contract hash, or both;
  target references and `scoring_gate_config_references` are explicit and
  non-empty; protected classes, severities, gate rules, and thresholds come
  from versioned scoring/gate configuration, never from case records or code
  constants.
- Case-set manifests own membership: exclusive partition
  (`dev` | `frozen_test`), overlapping suites, append-only versioned
  membership; frozen snapshots immutable; contaminated cases move to `dev`
  only in a later version.
- Execution status is `completed`, `invalid`, or `errored`; the gate verdict
  (`pass`, `fail`, `indeterminate`) exists only for completed runs; invalid
  or errored runs are neither passing evaluations nor regressions;
  `conditional_pass` does not exist; a blocking failure cannot be overridden
  into a pass; exceptions are separate records and the failed evaluation
  remains failed; gate outcomes never automatically accept or freeze an
  artifact. Process exit codes are runner behavior, not either vocabulary.
- Findings are immutable with full provenance; dispositions are append-only
  and never enter gate arithmetic; resolution requires a new component
  version and a new evaluation run.
- Reference-resolution failures are validity-blocking, not negative
  predictions: a missing/unknown-version/hash-mismatched/duplicate/
  conflicting/unresolvable target or scoring-gate-configuration reference
  emits an immutable finding, may mark affected assertions `not_evaluated`,
  and forces `execution_status = invalid` with no gate verdict, no metrics,
  and no regression claims; dispositions or exceptions never make the
  invalid run valid. A reference that resolves while the prediction fails
  the expectation is a normal `unsatisfied` outcome. Loaders return typed
  resolution results/errors; the runner's validity layer owns the
  invalid-run decision; assertion dispatch never converts an unresolved
  contract reference into an ordinary negative.
- Persisted-artifact contracts use the build plan's canonical contract-hash
  algorithm (`evaluation/contracts.py`: sorted-key compact UTF-8 JSON
  envelope of contract_id + contract_version + generated schema, SHA-256
  digest); artifacts store and verify `contract_version` + `contract_hash`;
  the runtime Pydantic version is recorded in run provenance. Metric and
  comparison artifacts exist only for completed runs; invalid/errored runs
  keep their manifests, diagnostics, findings, and preserved raw inputs,
  with partial artifacts explicitly marked.
- Comparisons are immutable artifacts with predeclared baselines; changed
  assertion contracts are non-comparable by default; bridge re-evaluation
  restores comparability; invalid runs produce no regression claims.
- `UNKNOWN` stays distinct from negative outcomes; report coverage,
  abstention, and false confidence; low-support metrics may be
  `indeterminate`.

## Evaluation package release binding (final slice)

Only after Slices 1–13 are complete, green, and approved: perform the build
plan's Slice 14 — "Evaluation package release binding and final
compatibility validation" — binding the evaluation package's released
contract set and usage documentation exactly as specified there. This slice never touches
`schemas/schema_version_manifest.json`, never changes Phase 0
writers/readers, never mutates historical artifacts, never removes old
schema support, never silently removes `eval_report_ids`, and never
introduces a reverse-link replacement. Global activation of
`universe_run_manifest.v2.schema.json` is out of scope and requires separate
approval. The usage-documentation pathname is selected in this slice only
after a repository audit and explicit approval, with its REPO_MANIFEST entry
in the same slice.

## After each slice (required report)

1. exact commands run and their results (focused tests, full suite, schema
   CLI);
2. resulting file tree of changed areas;
3. changed-file list with complete SHA-256 hashes;
4. limitations and remaining work;
5. explicit statement that Phase 0 behavior is unchanged;
6. stop.

## Safety and stopping rules

- Do not read parent or sibling directories.
- Do not read `.env`, secrets, SSH, or cloud credentials.
- Do not install dependencies unless an existing declared dependency is
  insufficient; ask before adding one.
- Do not run destructive shell commands.
- Never auto-commit or auto-push; commits and pushes require separate
  explicit approval with the exact file set and message.
- Stop after the approved slice.
