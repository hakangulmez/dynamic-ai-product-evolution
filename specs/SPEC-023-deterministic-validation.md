# SPEC-023 — Deterministic Validation Layer

## Status

Draft

## Objective

Implement non-model checks that must run before semantic evaluation or human review. Validators produce mechanical, reproducible facts; semantic judgment is reserved to human review (ADR-018).

## Required validators

1. Output JSON/schema validity.
2. Required-field presence.
3. Source ID resolution.
4. Passage ID resolution.
5. Evidence quote occurs in cited passage.
6. Publication date is not later than observation cutoff.
7. Product–capability–task parent links resolve.
8. IDs are unique within the declared scope.
9. Prohibited legacy fields are absent.
10. Active records are not supported only by future-roadmap evidence.
11. Customer-facing tasks have a customer outcome and evidence.
12. Raw model output and any repair record are preserved.

## Finding structure

Each validator returns:

```yaml
finding_id:
validator:                 # rule ID
validator_bundle_version:
validator_bundle_hash:
rule_params_hash:
severity:
run_id:
case_id:
entity_id:
artifact_id:               # prediction/artifact record under validation
observed_value:
expected_invariant:
message:
evidence:
repairable:
created_at:
```

A finding is immutable: the reproducible result of one validator bundle and one rule applied to one artifact. Validators must not silently fix data. Repairs are append-only records with supersedes/derived_from links and require a new evaluation run.

## Severity

- `critical`: blocks release;
- `error`: invalidates the entity or case;
- `warning`: requires review;
- `info`: diagnostic only.

Severity assignments are versioned configuration bound to the validator bundle and the scoring/gate configuration. Per-case human severity changes are prohibited; a wrong severity is corrected through a new bundle or configuration version and corpus-wide re-evaluation (ADR-018).

## Finding lifecycle and resolution

The finding record itself is immutable and carries no mutable lifecycle field. Dispositions, remediation actions, supersession links, and resolution events are separate append-only records (data model in SPEC-022). The displayed lifecycle state — `open`, `dispositioned`, `remediation_pending`, `resolved_by_rerun`, `superseded`, `unresolved` — is derived from those event records; an old finding is never edited to become resolved.

- Human dispositions never modify findings.
- Whether a defect persists is determined only by producing a new version of the faulty component — prediction, source snapshot, gold/case-set, validator bundle, or scoring/gate configuration — and a new immutable evaluation run.
- Gate arithmetic uses the raw blocking findings emitted by the current evaluation run; a disposition never removes a current finding from gate arithmetic and never changes the verdict.
- Critical findings are never waived per case; release exceptions are separate governance records under change control and never convert a finding or verdict to pass (ADR-018, ADR-019).

## Acceptance criteria

- a `completed` evaluation run containing any current critical blocking finding receives gate verdict `fail`;
- findings, dispositions, and resolution events never modify evaluation execution status;
- `invalid` and `errored` are execution outcomes and produce no candidate gate verdict;
- process exit codes, when implemented, are operational runner behavior and are not part of the evaluation execution-status or gate-verdict vocabularies;
- findings are machine-readable;
- identical validator bundle and artifact inputs reproduce identical findings;
- gate computation uses the raw blocking findings emitted by the current evaluation run; append-only dispositions, remediation events, supersession events, and displayed lifecycle state never filter or remove a current-run finding from gate arithmetic; only a new component version and a new immutable evaluation run can establish that the defect is no longer present (ADR-018, ADR-019);
- all validators have unit tests;
- the runner reports failures without dropping records.

## Revision history

- 2026-07-19 — Revised per ADR-018, ADR-019: finding provenance fields and immutability, versioned severity, finding lifecycle and resolution rules, reproducibility and gate-computation acceptance criteria.
