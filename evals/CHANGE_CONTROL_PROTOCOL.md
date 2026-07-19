# Evaluation and Prompt Change Control

## Binding rule

No behavior-changing production prompt edit is accepted without:

1. a documented general failure class;
2. at least one evaluation case;
3. an expected result approved by the methodology owner;
4. a candidate-versus-accepted comparison;
5. a regression review;
6. an acceptance or rejection record.

## Change-request location

```text
evals/change_requests/CR-XXXX-short-title.md
```

Use `evals/templates/change_request.template.md`.

## Required workflow

```text
Failure observed
  → case added to the dev partition and tagged with the relevant suites
  → old version rerun and failure confirmed
  → change request opened
  → bounded prompt/spec change
  → all relevant eval partitions and suites rerun
  → report and diff generated
  → human decision recorded
  → qualification registry updated if approved
```

## Protected conditions

A candidate is rejected automatically if it introduces:

- temporal leakage;
- invalid evidence references;
- unsupported active products or tasks;
- legacy contamination;
- silent output overwrite;
- schema incompatibility;
- wrong or unsupported confident values where the evidence requires unknown.

These behavioral invariants are lexicographic: no metric improvement can
compensate for them (ADR-019).

## Evaluation validity precondition

A review decision presupposes a completed, valid evaluation. Evaluations
with execution status `invalid` or `errored` produce no verdict about the
candidate; the only path forward is to repair the evaluation and produce a
new immutable evaluation run (ADR-019).

## Review decisions

- `accept_candidate`
- `accept_with_documented_nonblocking_tradeoff`
- `revise`
- `reject`

A documented non-blocking trade-off requires a rationale and an explicit
record of the affected diagnostic metrics and slices. Protected
regressions, critical findings, blocking gate failures, and indeterminate
verdicts are not eligible for trade-off acceptance (ADR-019).

A methodological issue discovered during review is not encoded as a
candidate review decision; it is routed to the separate change-control and
decision-log (ADR) process.

## Release exceptions

A release exception is a separate governance record (failed gate and
finding IDs, scope, rationale, methodology-owner approval, expiry, and a
decision-log reference). The evaluation verdict remains `fail`; the prompt
lifecycle never auto-advances, and reports keep the failure visible
(ADR-019).
