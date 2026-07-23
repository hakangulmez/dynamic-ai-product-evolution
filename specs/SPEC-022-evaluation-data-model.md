# SPEC-022 — Evaluation Case and Review Data Model

## Status

Draft

## Objective

Define stable, versioned structures for evaluation cases and assertions, case-set manifests and snapshots, gold provenance, prediction envelopes, finding dispositions, human reviews, exposure events, and prompt-release records.

## Inputs

- source and passage registry snapshots;
- stage output schemas;
- gold annotations;
- prediction envelopes from manifest-bearing runs;
- failure taxonomy;
- review decisions.

## Outputs

- evaluation-case records;
- case-set manifests and membership-change events;
- gold provenance records;
- finding-disposition records;
- append-only review records;
- exposure-event records (data model only in Phase 1);
- prompt-release records.

Responsibility boundary: SPEC-023 owns the semantics and production of deterministic findings; SPEC-022 owns the persistence data model for findings, dispositions, and review records.

## Evaluation case fields

Required:

- `case_id`
- `stage`
- `stage_context` — stage-specific typed context; may include company, observation date, secondary dates, or frontier-model context; none is universally required (ADR-011)
- `input_source_ids`
- `input_passage_ids`
- `assertions`
- `failure_tags`
- `notes`
- `created_by`
- `created_at`
- `guideline_version`

Removed from the contract:

- `split`, `company_id`, `observation_date` — membership lives in the case-set manifest (ADR-014); company and dates are stage context (ADR-011);
- `expected_status` — expected behavior is expressed through assertions and failure tags; no replacement field or vocabulary is introduced;
- `expected_entities`, `forbidden_entities` — their content is represented by assertions of kind `expected_entity` and `forbidden_entity`; no parallel expected-output channels are maintained.

There are currently no persisted evaluation cases requiring migration. The evaluation-case template and the successor schema will be aligned with this contract in Batch B2; no template or schema is modified in this batch.

## Assertion model

Assertions are the sole scoring contract of an evaluation case: every expected or prohibited behavior is expressed as an assertion, and no parallel expected-output channels exist. An evaluation case contains assertions as its atomic scoring units (ADR-011). Each assertion records:

- a stable assertion ID;
- assertion kind: `expected_entity`, `forbidden_entity`, `field_value`, `evidence_provenance`, or `deterministic_validation`;
- an assertion semantic version or contract hash;
- target entity or field references;
- references to protected-class and severity definitions in the versioned scoring/gate configuration; values are never hardcoded in case records.

Assertion outcomes use the vocabulary `satisfied`, `unsatisfied`, `indeterminate`, `not_applicable`, `not_evaluated` (ADR-020).

## Case-set manifest and snapshot

Case usage membership lives in the versioned case-set manifest, not in case files or directory paths (ADR-014):

- exactly one evaluation partition per case per case-set version (`dev`, `frozen_test`);
- zero or more evaluation suites (`adversarial`, `regression`, `smoke`, `boundary`, `schema_validation`);
- registry snapshot version/hash and resolved input-packet hashes (ADR-012);
- case-set lifecycle `draft` or `frozen`; frozen snapshots are immutable and hash-identified (ADR-013).

Membership-change events record: previous and new case-set version, case ID, old and new partition where applicable, added and removed suites, reason code, change-request or adjudication reference, actor, and timestamp.

## Gold provenance

Gold labels record three orthogonal dimensions (ADR-013):

- `gold_origin`: `constructed`, `human_annotated`, `imported_reference`;
- `verification_status`: `provisional`, `verified`, with `verification_method` as separate metadata: `dual_independent_adjudication`, `solo_blinded_retest`, `expert_second_review`, `construction_review`;
- case-set lifecycle membership per the snapshot.

Each gold assertion carries: annotator/reviewer pseudonymous IDs, annotation timestamps, verification method, disagreement/adjudication record reference, source packet hash, case version, change reason, and a superseded-by reference where applicable. Retest intervals live in policy configuration, not in this specification or in schemas.

## Prediction envelope

Predictions are scored only in the canonical envelope (ADR-012). It preserves at least:

- prediction record ID;
- stage;
- source references;
- prompt/model metadata;
- input-packet hash;
- prediction-run manifest reference.

Ad-hoc files enter evaluation only through an explicit import that produces a manifest-bearing eval input snapshot.

## Finding dispositions

Human dispositions on deterministic findings are append-only records (ADR-018) with types: `confirmed_defect`, `suspected_validator_false_positive`, `confirmed_validator_false_positive`, `source_snapshot_defect`, `prediction_artifact_defect`, `gold_or_case_defect`, `policy_or_rule_mismatch`, `accepted_nonblocking_risk`, `duplicate_finding`, `needs_investigation`. Each carries reviewer, timestamp, rationale, linked evidence, proposed resolution path, and a linked replacement run or version where applicable. Dispositions never modify findings and never enter gate arithmetic.

## Exposure events

Exposure events record access to frozen-case information (ADR-015): exposure type (`aggregate_metrics_view`, `case_prediction_view`, `gold_detail_view`, `source_packet_view`, `adjudication_view`), scope, purpose code, actor, timestamp, candidate reference, and resulting disposition. Phase 1 defines the record model only; enforcement services and interfaces are Phase 2+.

## Entity identity

Expected-entity and forbidden-entity assertions use stable gold IDs and may define accepted aliases. Textual labels alone are not stable identifiers.

## Review immutability

Human review records are append-only and contain original and revised values. Original predictions, original gold records, and validator findings remain unchanged; resolution occurs only through new component versions and new evaluation runs (ADR-018). Membership-change and exposure events are append-only.

## Validation

- unique case IDs;
- known stage values and resolvable stage-context types;
- exactly one partition and valid suite values per case in each case-set version;
- valid dates;
- source and passage resolution against the pinned registry snapshot;
- compatible schema versions;
- valid failure tags;
- valid gold-origin, verification-status, and verification-method values;
- no unresolved required fields.

## Acceptance criteria

- every case validates;
- cases load without stage-specific custom parsing via typed stage context;
- membership is fully reconstructable from case-set manifests and membership-change events;
- gold provenance is complete for verified records;
- review, disposition, membership, and exposure history are reconstructable;
- original records remain recoverable.

## Semantic-substrate artifact families (ADR-024, ADR-025)

The Phase-1 semantic substrate adds strict, frozen, extra-forbid, versioned, deterministically persisted contracts, each identified by a model-contract hash and canonical persisted bytes unless a committed static schema already governs the source artifact: `evaluation_stage_profile_registry@0.1.0`, `source_passage_snapshot_manifest@0.1.0`, `parsed_prediction_content@0.1.0`, `evaluation_semantic_adapter_registry@0.1.0`, `gold_assertion_set@0.1.0`, `axis_taxonomy@0.1.0`, `validator_rule_parameters@0.1.0`, `validator_bundle_artifact@0.1.0`, `validation_artifact_snapshot_set@0.1.0`, `stage_metric_evidence_set@0.1.0`, `metric_input_snapshot@0.1.0`, `metric_report@0.2.0`, and `evaluation_output_manifest@0.1.0`. `evaluation_run_manifest` advances to `0.2.0` (ADR-025).

Gold is an assertion-owned artifact family (`gold_assertion_set`) keyed by case ID, assertion ID, assertion semantic version or contract hash, and resolved canonical target reference, with kind-discriminated typed payloads for field-value and evidence-provenance expectations and full gold provenance (origin, verification status/method, annotator/adjudication references, source-packet hash, case version, supersession). Expected-entity and forbidden-entity behavior derives from the assertion kind and the canonical target reference; no parallel `expected_entities`/`forbidden_entities` channel is reintroduced, and accepted aliases remain solely target-registry-owned with absolute precedence. The target registry keeps its committed identity and contract byte-identical.

Parsed prediction content is a derived output (not a case field and not a run input); it carries typed entity/field/evidence collections, per-collection completeness state (`complete`/`partial`/`unavailable`), and the raw-output/repair provenance that Rule 12 verifies, and its read-back hash is bound through the output manifest. Immutable identity/hash relationships across a coherent run (registry, case-set, membership input-packet, source/passage, gold, taxonomy, validator parameters/bundle, and stage evidence) are governed by ADR-025 and the evaluation-output manifest. Invalid or errored runs persist the run manifest and `EvaluationResultV2` without a gate verdict plus findings produced before invalidation; assertion material exists only as explicitly-marked partial artifacts, never as completed `not_evaluated` outcomes, and no completed assertion-outcomes artifact, metric report, or gate verdict is produced.

## Revision history

- 2026-07-19 — Revised per ADR-011, ADR-012, ADR-013, ADR-014, ADR-015, ADR-018, ADR-020: stage-typed case context, assertions as the sole scoring contract, case-set manifests and snapshots, gold provenance dimensions, prediction envelope, disposition and exposure record models; removed `split`, `company_id`, `observation_date`, `expected_status`, `expected_entities`, and `forbidden_entities` from the case contract.
- 2026-07-23 — Revised per ADR-024, ADR-025: semantic-substrate artifact families, assertion-owned gold and axis taxonomy, parsed-prediction-content derived-output contract, stage/taxonomy inputs, immutable identity/hash relationships, and partial/invalid-run artifact semantics.
