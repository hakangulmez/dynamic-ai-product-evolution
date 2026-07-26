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

## Stage-specific validator parameters and coverage (ADR-024)

Validator rule policy is a versioned `validator_rule_parameters@0.1.0` artifact with exactly one `ValidatorRuleParameterEntry` per rule in `VALIDATOR_RULE_ORDER`. Each entry owns `rule_id`, canonically ordered unique `dependency_rule_ids` and `blocking_reason_codes`, exactly four canonically ordered `stage_parameters` for `capability_extraction`, `task_extraction`, `universe_screen`, and `universe_classification` as a discriminated applicable/inapplicable union (an applicable stage carries exactly one correctly typed rule-specific payload; an inapplicable stage carries exactly one governed reason code and no payload), and a `complete_rule_parameter_hash` that binds the rule ID, dependencies, blocking reasons, and all four complete stage entries while excluding its own field. That complete per-rule hash equals `ValidatorRuleConfig.rule_params_hash`, and an aggregate parameter-set hash binds the twelve entries in canonical order; the `validator_bundle_artifact@0.1.0` is generated as a reconciled pair from these hashes. An applicable Rule 1 static-schema payload binds `output_schema_id`, a repository-relative `output_schema_reference`, and `output_schema_sha256` (the committed anchors are `schemas/capability_observation.schema.json` `4ade397f3383ff756a1aa2ba5f98bdb99f76c002d5cf049d7e8dcd7abf493733`, `schemas/task_observation.schema.json` `b135ab828a3b710f1c63f6a8bf473caa6e29c3a63a5330cb203b470f772e3b03`, and `schemas/company_universe_classification.schema.json` `1d47a80ee670f927e55d6af50550b1584aab022389471739a055a9e550552a22`); `universe_screen` has no committed static output schema and binds the versioned adapter output contract `universe_screen_output@0.1.0` (ID, version, and canonical generated hash) in both Rule 1 and Rule 2.

Each of the twelve rules is produced from named typed inputs; no dummy or blanket-passing observation is permitted. A validation-artifact snapshot carries one `ValidatorRuleCoverage` record per rule in canonical order with the states `fully_evaluated`, `partially_evaluated`, `inapplicable`, and `blocked_by_dependency` plus candidate, evaluated-observation, blocked-candidate, and governed reason counts. Validator metric denominators use the evaluated-observation count only; candidate and blocked counts are diagnostic. For Rules 5 and 6, an unresolved cited passage or source is a completed-run prediction defect that blocks that candidate and makes the evidence-provenance assertion `unsatisfied`, but does not by itself invalidate evaluation input; a resolved canonical source lacking its governed publication date invalidates the source snapshot and run. Rule 12 has exactly one candidate and is always fully evaluated after valid parsed content loads (no inapplicable or dependency-blocked state) and directly verifies raw-output preservation and repair reference/hash provenance; unloadable, hash-mismatched, malformed, or contract-invalid parsed content invalidates the run before validation-snapshot production. The committed `ValidatorFinding@0.1.0` contract (`96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292`) is unchanged.

## Validator parameter successor `@0.2.0` (ADR-028)

`validator_rule_parameters@0.2.0` is an additive successor to the `@0.1.0` artifact described above. It exists because three governed facts cannot be expressed under v0.1 without mutating an accepted contract, which schema governance forbids. The v0.1 model, its generated model-contract hash `f9c20ba936e1c0541c721ac6c3c34bec183b4b360dfa177516c57b0bd0945822`, and every committed v0.1 parameter and bundle artifact remain valid and unchanged; the two versions are separate contracts, and neither loader accepts the other's declared `contract.contract_version`.

The successor differs from v0.1 in exactly three governed ways.

1. **Rule 11 is inapplicable at both extraction stages.** Neither extraction output schema carries `is_customer_facing_task` or `customer_outcome` (`schemas/task_observation.schema.json` declares neither, and `availability_status` is an unconstrained string), so `customer_task_outcome_and_evidence` is not derivable from a conforming extraction record. Under v0.2 it is inapplicable at `capability_extraction` and `task_extraction` with the already-governed reason code `stage_emits_no_customer_facing_task`; combined with the existing universe-stage cells, Rule 11 is inapplicable at all four stages. No inapplicable-reason vocabulary is added.

2. **Rule 10 carries the governed availability-status vocabularies.** Because `availability_status` is an unconstrained string in both extraction schemas, the active/roadmap classification cannot be schema-derived and is governed in the parameter artifact instead. The applicable Rule-10 payload adds `active_status_values` and `roadmap_status_values`, each non-empty, ascending, duplicate-free, and mutually disjoint. A record status outside the union of the two sets is a parameter-governance defect and fails closed; it is never silently treated as inactive. Wording heuristics play no part in this classification.

3. **Rule 10 additionally depends on `source_id_resolution`.** Rule 10's per-evidence temporal classification requires resolved source documents, so its dependency tuple is `(required_field_presence, source_id_resolution)` and its blocking tuple is the positionally aligned `(blocked_required_field_missing, blocked_source_unresolved)`. Both codes already exist in the governed blocking vocabulary, which is not widened. A prediction citing a source absent from the case-resolved document set is therefore a citation defect that Rule 3 reports while Rule 10 truthfully states `blocked_by_dependency` with `blocked_source_unresolved` — not an input-assembly abort. When `required_field_presence` is also blocked, that dependency takes precedence, matching canonical dependency order.

Rule 2's stage-specific required-field vocabulary stays inside the existing applicable stage payload's `required_fields`, whose values are already bound by `complete_rule_parameter_hash`; no top-level extraction-required-fields field is introduced. The coverage vocabulary is unchanged: `fully_evaluated`, `partially_evaluated`, `inapplicable`, and `blocked_by_dependency` remain the only states, and no state with zero candidates other than `inapplicable` exists.

Because the Rule-10 and Rule-11 entries change, their `complete_rule_parameter_hash` values and therefore the aggregate parameter-set hash change under v0.2. A v0.2 parameter artifact consequently requires its own reconciled `validator_bundle_artifact` counterpart; it cannot be loaded against a v0.1 bundle. Both hash helpers accept either governed model type, and the canonical dump algorithm is version-independent, so every v0.1 hash result is byte-identical to what it was before the successor existed.

## Revision history

- 2026-07-19 — Revised per ADR-018, ADR-019: finding provenance fields and immutability, versioned severity, finding lifecycle and resolution rules, reproducibility and gate-computation acceptance criteria.
- 2026-07-23 — Revised per ADR-024: stage-specific validator parameters, static-schema and adapter-contract hash binding, validator coverage records and evaluated-observation denominators, all twelve-rule production, and Rule 5/6/12 behavior.
- 2026-07-27 — Revised per ADR-028: `validator_rule_parameters@0.2.0` additive successor — Rule 11 extraction-stage inapplicability, governed Rule-10 availability-status vocabularies, and Rule 10's truthful `source_id_resolution` dependency, with v0.1 contract and artifacts preserved.
