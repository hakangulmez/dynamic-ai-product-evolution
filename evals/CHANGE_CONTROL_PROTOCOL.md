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
  → case added to dev/adversarial/regression split
  → old version rerun and failure confirmed
  → change request opened
  → bounded prompt/spec change
  → all relevant eval splits rerun
  → report and diff generated
  → human decision recorded
  → accepted prompt registry updated if approved
```

## Protected conditions

A candidate is rejected automatically if it introduces:

- temporal leakage;
- invalid evidence references;
- unsupported active products or tasks;
- legacy contamination;
- silent output overwrite;
- schema incompatibility;
- confident values where the rubric requires unknown.

## Review decisions

- `accept_candidate`
- `reject_candidate`
- `revise_candidate`
- `accept_with_documented_tradeoff`
- `methodology_decision_required`

A documented trade-off requires a rationale and explicit protected metrics.
