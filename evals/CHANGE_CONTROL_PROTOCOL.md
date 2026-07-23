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

## Semantic-substrate change classification (ADR-024, ADR-025)

Changes to the Phase-1 semantic substrate are versioned contract changes under
change control; a changed contract never inherits prior qualification or
enablement. The following are contract changes requiring a version increment,
a decision-log reference, and re-evaluation of every affected run:

- stage-profile registry entries, metric-family applicability, or supported
  stages;
- semantic-adapter registry entries, adapter output contracts, or selected
  adapter identity;
- gold assertion sets and axis-taxonomy definitions (a changed gold or taxonomy
  hash is a `changed_gold` comparability signal);
- validator-rule parameters and the validator-bundle artifact (a changed
  parameter-set or bundle hash is a `changed_validator_contract` signal); the
  complete per-rule parameter hash must equal `ValidatorRuleConfig.rule_params_hash`;
- the semantic producers (parsed prediction content, semantic assertion
  evaluators, validation-artifact snapshot set, metric-input snapshot);
- the evaluation-run-manifest version (v0.1 remains read-only; v0.1↔v0.2 is
  `noncomparable_contract`) and the evaluation-output manifest;
- metric applicability and the `metric_report@0.2.0` applicability ledger.

Pairwise run-comparison classification is distinct from change control. A
changed selected stage-profile entry identity/hash (which alters metric-family
applicability and/or required stage evidence) and a changed selected
semantic-adapter entry identity/hash are `noncomparable_contract`; a changed
gold, axis-taxonomy, or applicable stage-evidence hash is `changed_gold`; and a
changed validator-bundle or validator-rule-parameters hash is
`changed_validator_contract`. A changed stage-profile registry version/hash whose
selected entry identity/hash is identical, a changed semantic-adapter registry
version/hash whose selected adapter entry identity/hash is identical, and a
source-document/source-passage snapshot change that leaves every consumed
per-case input-packet hash identical are provenance-only for pairwise comparison.
Provenance-only describes only that pairwise-comparison classification and is not
a change-control exemption: every registry, adapter, gold, taxonomy, parameter,
bundle, and snapshot edit still requires a normal governed version/hash update
and review, and no new `NoncomparabilityClass` value is introduced. Committed
contract hashes preserved by this governance (`evaluation_run_manifest@0.1.0`,
`metric_report@0.1.0`, `validator_finding@0.1.0`, `comparison_manifest@0.2.0`)
must not change; any deviation is a defect requiring a new decision-log entry
rather than a silent rewrite (ADR-024, ADR-025).
