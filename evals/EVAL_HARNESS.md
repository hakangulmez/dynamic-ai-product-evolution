# Evaluation Harness

## Purpose

The harness is the scientific control system for source collection, extraction, matching, and measurement. It replaces informal prompt tweaking with versioned cases, hard gates, regression testing, and explicit release decisions.

Read together with:

- `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`
- `evals/CHANGE_CONTROL_PROTOCOL.md`
- `specs/SPEC-020-evaluation-harness.md`
- `specs/SPEC-022-evaluation-data-model.md`
- `specs/SPEC-023-deterministic-validation.md`
- `specs/SPEC-024-run-versioning-and-comparison.md`

## Evaluation partitions and suites

Case usage membership lives in the authoritative, versioned, append-only
case-set manifest, not in case files or directory paths (ADR-014). Case files
are split-agnostic; an immutable evaluation case does not own its split.

- Partition (exactly one per case per case-set version): `dev`, visible
  during prompt development; `frozen_test`, the protected generalization set.
- Suites (zero or more; suites may overlap): `adversarial`, deliberately
  misleading and difficult cases; `regression`, permanent cases for
  previously corrected failures.

Frozen case-set snapshots are immutable. Detailed case or gold exposure
contaminates blind frozen use; a contaminated case moves to `dev` in a later
case-set version (ADR-015). No silent approval and no silent frozen-set
mutation is permitted. The concrete manifest layout and evaluation artifact
root are deferred to implementation planning.

## Assertions

Assertions are the atomic scoring unit; every case contains one or more
assertions. The assertion kinds are `expected_entity`, `forbidden_entity`,
`field_value`, `evidence_provenance`, and `deterministic_validation`. Each
assertion carries stable identity through an assertion semantic version, an
assertion contract hash, or both; explicit, non-empty target references; and
explicit, non-empty `scoring_gate_config_references`. Protected classes,
severities, gate rules, and thresholds are referenced from the versioned
scoring/gate configuration, never hardcoded in case records. Assertion
outcomes are run artifacts, not immutable case-definition fields.

## Execution status and gate verdict

Evaluation execution status is `completed`, `invalid`, or `errored`. The gate
verdict — for completed runs only — is `pass`, `fail`, or `indeterminate`. A
completed run requires a gate verdict; an invalid or errored run has no gate
verdict and is never treated as a regression or as a passing run.
`conditional_pass` is not part of the Phase 1 verdict vocabulary, and the
historical combined `decision` field is not the Phase 1 v2 verdict contract.

Human review decisions (`accept_candidate`,
`accept_with_documented_nonblocking_tradeoff`, `revise`, `reject`) and prompt
lifecycle states (`draft`, `candidate`, `accepted`, `frozen`, `deprecated`)
are separate vocabularies. No gate result automatically accepts or freezes an
artifact; a blocking gate failure cannot be overridden into a passing
evaluation; release exceptions remain separate records while the evaluation
itself remains failed.

## Evaluation runs and artifacts

Evaluation cases are immutable inputs; evaluation runs are immutable
artifacts; production prediction runs and evaluation runs are separate
records. The authoritative linking direction is evaluation-run →
prediction-run; `eval_report_ids` remains optional compatibility data in
universe manifests, and no new reverse-link field is introduced. Evaluation
artifacts are never written into extraction-output directories, and no ad hoc
JSONL becomes the canonical evaluation store.

## Release gates

A stage may scale only after its relevant gate passes.

## E0 — Deterministic integrity

Hard checks:

- valid JSON and declared schema;
- required fields present;
- source and passage references resolve;
- evidence quotes occur in cited passages;
- publication date is not later than the observation cutoff;
- product–capability–task hierarchy resolves;
- IDs are unique;
- prohibited legacy fields are absent;
- active records are not supported only by future roadmap evidence;
- original outputs and repairs are preserved.

Critical E0 failures block release regardless of aggregate metrics.

## E1 — Source discovery

Metrics:

- official-domain precision;
- required-category recall;
- date-resolution rate;
- temporal-invalid rate;
- duplicate-source rate.

## E2 — Product extraction

Metrics:

- product precision and recall;
- suite and bundle error rate;
- alias-resolution accuracy;
- unsupported-roadmap false positives;
- evidence validity;
- duplicate product rate.

## E3 — Capability extraction

Metrics:

- concrete-action precision;
- capability recall;
- marketing-abstraction false positives;
- product/capability boundary agreement;
- task/capability confusion rate;
- availability accuracy.

## E4 — Task extraction

Metrics:

- economic-task precision and recall;
- duplicate rate;
- over-split and under-split rates;
- customer-need quality;
- evidence coverage;
- core/supporting/peripheral agreement;
- unsupported task rate.

## E5 — Longitudinal matching

Metrics:

- predecessor-link precision and recall;
- transition-label macro F1;
- false-new and false-discontinued rates;
- split/merge accuracy;
- rename robustness;
- unresolved rate.

## E6 — Measurement

Metrics:

- rubric agreement;
- frontier-baseline accuracy;
- temporal leakage;
- marketing-only false positives;
- anchor-task ordering;
- unknown calibration;
- component-to-final-label consistency;
- evidence-backed depth, scale, and defensibility.

## Gold protocol

- Two independent annotations for the formal gold set where feasible.
- Adjudication after independent completion.
- Source packet only.
- No financial outcomes or legacy scores.
- Guideline version and annotator confidence recorded.
- Original annotations preserved after adjudication.

## Required adversarial fixtures

- generic AI strategy statement with no concrete action;
- announced agent with no availability;
- “agent” that only drafts text;
- product rename with no task change;
- same mechanism but distinct economic tasks;
- distinct features forming one customer workflow;
- proprietary data that is not necessary for the underlying need;
- current page incorrectly used for an earlier year;
- internal R&D incorrectly extracted as a customer capability;
- broad mission statement incorrectly extracted as a task.

## Regression suite

Every accepted prompt or rubric change adds fixtures for the failure it addresses. A version may not improve one metric by materially degrading another without explicit acceptance.

## Prompt comparison

Candidate reports must show:

- fixed cases;
- new regressions;
- unchanged failures;
- metric deltas;
- hard-gate changes;
- results by partition, suite, company, year, source type, and failure tag;
- unknown-rate and evidence-coverage changes.

## Full-run gate

The full universe is blocked until:

- deterministic integrity tests pass;
- source temporal tests pass;
- product and task gold thresholds are met;
- evidence validity is at least 0.98;
- no critical contamination failure exists;
- matching reliability is accepted;
- measurement pilot completes blinded construct review;
- a prompt release record identifies the accepted version.
