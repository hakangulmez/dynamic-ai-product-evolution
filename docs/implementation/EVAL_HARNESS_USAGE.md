# Evaluation Harness Usage

How to run the Phase 1 evaluation harness: the single-case evaluation runner
(Slice 13, ADR-027/ADR-029) and the released contract binding (Slice 14).

Read together with:

- `evals/EVAL_HARNESS.md` — governance and methodology (partitions, suites,
  gates, change control)
- `docs/implementation/EVAL_HARNESS_BUILD_PLAN.md` — slice history and scope
- `specs/SPEC-020-evaluation-harness.md`, `specs/SPEC-022-evaluation-data-model.md`,
  `specs/SPEC-023-deterministic-validation.md`, `specs/SPEC-024-run-versioning-and-comparison.md`

## Operating boundaries

The runner makes **no provider calls** — no model API, network, Git, or clock
access — and operates **only on explicitly prepared local plan/artifact
inputs**: every input is a file the caller has already placed under one of the
plan's three source roots and pinned by SHA-256. The committed test suite
demonstrates the runner over synthetic fixture material; that is its current
test demonstration, not a permanent runtime restriction. Real company-data
extraction, live pilots, and provider-backed prediction runs are separately
approved workflows that prepare their inputs through the same plan contract.

Every timestamp a run persists comes from the plan's `evaluation_created_at`;
the runner never reads a clock. All run artifacts are write-once, persisted,
reloaded, and hash-verified; nothing is repaired or overwritten.

## The run plan

A run is described by an `EvaluationRunPlan` JSON document:

- `eval_run_id` — single safe path component; the run directory name.
- `evaluation_stage` — `capability_extraction` or `task_extraction`.
- `prediction_run_id`, `prediction_record_id` — must equal the prediction
  manifest's run ID and the single envelope's record ID.
- `company_id` — verified against the adjudication decision set and the
  parent-observation snapshot context.
- `code_commit`, `evaluation_created_at` (RFC3339 with explicit offset).
- `governed_artifact_root`, `prediction_source_root`,
  `adjudication_source_root` — the three local input roots.
- `artifact_references` — exactly the sixteen governed roles, strictly
  ascending by `artifact_role`, each entry carrying its root, a safe relative
  reference, and the SHA-256 of the raw persisted bytes:
  `axis_taxonomy`, `case`, `case_set_manifest`, `gold_assertion_set`,
  `observation_target_resolution_decision_set` (adjudication root),
  `output_schema`, `parent_observation_snapshot`, `prediction_run_manifest`
  (prediction root), `raw_prediction_artifact` (prediction root),
  `scoring_gate_config`, `semantic_adapter_registry`,
  `source_passage_snapshot_manifest`, `stage_profile_registry`,
  `target_registry`, `validator_bundle_artifact`, `validator_rule_parameters`
  (all others governed root).

The `prediction_run_manifest` entry's SHA-256 is the sole
`prediction_run_manifest_hash` authority; the `output_schema` entry must equal
the selected Rule-1 `validator_rule_parameters@0.2.0` payload's
`output_schema_reference` and `output_schema_sha256` for the chosen stage.

## Invocation

```
PYTHONPATH=src python -m dynamic_ai_products.evaluation.runner run \
  --plan <plan.json> --eval-root <eval_root>
```

`--dry-run` executes only the pre-manifest boundary — strict plan validation,
all sixteen raw-byte pin/root/order/reference checks, public input loading,
prediction-manifest hash verification, the output-schema/Rule-1 binding, and
single-case cardinality — and writes nothing: no run directory, no
initialization, no persister call. The Python API is
`run_single_case_evaluation(plan, eval_root=...)`.

Single-case cardinality is required: exactly one case-set membership, exactly
one prediction envelope, and exactly one case matching the envelope on
`(input_packet_hash, stage)`. There is no first-case selection, filtering, or
batch behavior.

## Exit codes (operational runner behavior)

Exit codes are operational; they are distinct from the persisted
`execution_status` and `gate_verdict` inside `EvaluationResultV2`.

| Code | Meaning |
|---|---|
| 0 | completed; gate verdict `pass` |
| 1 | completed; gate verdict `fail` or `indeterminate` |
| 2 | `invalid` terminal result persisted |
| 3 | `errored` terminal result persisted |
| 4 | pre-manifest operational failure; nothing written; no summary |
| 5 | report persistence failed after the terminal result became immutable |

Pre-manifest failures (exit 4) create no run directory and fabricate no
result. After the run manifest exists, every failure persists a terminal
invalid/errored `EvaluationResultV2` plus both reports; once validator
findings exist, the v0.2 output manifest is built from every successfully
persisted optional artifact before the terminal result. Fake empty findings
are never written; existing report files are never deleted, repaired,
overwritten, or retried.

## Run-directory artifact layout

```
<eval_root>/<eval_run_id>/
  evaluation_run_manifest.json            evaluation_run_manifest@0.2.0
  snapshots/scoring_gate_config.json      exact-byte config snapshot
  predictions/normalized_envelopes.jsonl  canonical envelopes
  snapshots/parsed_prediction_content.json
  snapshots/observation_target_binding.json
  snapshots/validation_artifact_snapshot_set.json
  findings/validator_findings.jsonl
  assertions/assertion_outcomes.jsonl
  metric_inputs/metric_input_snapshot.json
  metrics/metric_report.v2.json           metric_report@0.2.0
  output_manifest/evaluation_output_manifest.json   v0.2, stage derived
  results/evaluation_result.json          EvaluationResultV2
  reports/machine_evaluation_report.json  canonical machine report
  reports/human_evaluation_report.md      deterministic Markdown
```

The output manifest's evaluation stage is reverse-resolved from the run
manifest and the stage-profile registry; it is never caller-supplied. Report
hashes never enter any governed artifact.

## Stage-dispatched binding contract (ADR-029)

`capability_extraction` runs persist `observation_target_binding@0.1.0`
unchanged. `task_extraction` runs persist the explicit successor
`observation_target_binding@0.2.0`, whose **required**
`parent_observation_snapshot_version` / `parent_observation_snapshot_sha256`
pins durably record the exact committed parent snapshot task-stage Rule 7
consumed. A context-matching foreign snapshot that is not the snapshot bound
to the run fails the unchanged P2 equality checks.

## Released contract set (Slice 14)

`dynamic_ai_products.evaluation.RELEASED_EVALUATION_CONTRACTS` is the reviewed
release binding of every governed contract identity: nine static-schema
bindings (contract ID, version, `schemas/` path, reviewed file-byte SHA-256)
and thirty-four generated-model identities (contract ID, version, reviewed
model-contract hash). It is a release-review surface, not a runtime
authority; the regression suite enforces two-way agreement with the runtime
anchor tables. `schemas/schema_version_manifest.json` is untouched, Phase 0
readers and writers are unchanged, and `universe_run_manifest.v2.schema.json`
remains compatibility-read-only for the evaluation package — its global
activation is a separately approved future change set.
