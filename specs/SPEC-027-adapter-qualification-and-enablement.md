# SPEC-027 — Adapter Qualification, Enablement, and Run Authorization

## Status

Draft

## Objective

Govern how external adapters — source-retrieval and model-execution — move from implemented code to audited external runs under default-deny authorization, without premature scale (ADR-022).

## Scope and Phase 1 boundary

Phase 1 delivers contracts, records, interfaces, and stubs only: the enablement and authorization data models, readiness-gate contracts, mock-runner integration, budget configuration structure, and default-deny enforcement. No live adapter implementation, no live provider enablement, and no external network calls are in Phase 1 scope. Completing the evaluation harness never auto-enables live calls.

## State chain

```text
adapter_available → adapter_qualified → adapter_enabled → run_authorized → executed → audited
```

- `adapter_available`: code exists in the repository and is testable;
- `adapter_qualified`: passed the required gates under a specific execution contract;
- `adapter_enabled`: permitted for a specific environment and rollout scope via a versioned enablement record;
- `run_authorized`: a specific external-call run authorized with predeclared budget and scope;
- `executed`: the run performed through the canonical runner;
- `audited`: run artifacts and provenance verified and recorded.

No state grants a later state automatically.

## Adapter qualification record

Adapter qualification is distinct from prompt qualification. SPEC-027 defines its own immutable `adapter_qualification_record`, binding at least:

- adapter identity/version;
- adapter family (source or model-execution);
- execution contract identity/hash;
- routing contract identity/hash, where applicable;
- stage/output contract identity/hash;
- qualification scope;
- supporting evaluation/readiness evidence references;
- qualification status and timestamps;
- supersession references.

Source adapters do not require a prompt qualification record. For model-execution adapters: adapter enablement references the SPEC-027 `adapter_qualification_record`; and when the authorized model route executes a prompt-bearing stage, it also references the applicable SPEC-024 prompt/execution/routing/stage-contract qualification record. SPEC-024 continues to own prompt qualification; SPEC-027 owns adapter qualification, enablement, and authorization.

## Enablement record

An enablement record binds at least:

- adapter identity and version;
- execution contract identity/hash;
- routing contract identity/hash;
- stage ID/version and stage/output contract identity/hash;
- `adapter_qualification_record` reference; for model-execution adapters on prompt-bearing stages, additionally the applicable SPEC-024 prompt qualification reference, consumed and never redefined here;
- `deployment_environment_id`;
- deployment-environment policy/version reference;
- rollout scope and permitted partitions/suites;
- allowed endpoints (allowlist);
- budget policy version and rate-limit/retry policy version;
- enablement status, approver, effective timestamp, and expiry or review date;
- supersedes/superseded-by references.

Execution-affecting contract changes never inherit enablement.

## Adapter families

Source adapters (for example SEC EDGAR and official web/archive retrieval) and model-execution adapters (for example LLM providers and declared routing bundles) have separate readiness and safety gates.

- Source-adapter risks: wrong or incomplete acquisition, temporal leakage, rate-limit violations, provenance loss, non-idempotent retrieval, unfrozen snapshots.
- Model-adapter risks: cost, nondeterminism, provider/model drift, route contamination, manifest gaps, raw-output loss, prompt/runtime contract ambiguity.

## Common readiness requirements

Before any live adapter is enabled, all of the following must hold as measurable, versioned conditions:

- the required evaluation-harness components are operational and tested;
- the immutable run-manifest model is in place;
- stage definition and input/output schema contracts are declared, versioned, and compatible with the target qualification scope: declared and versioned for `live_dev`; pilot-qualified for `controlled_pilot`; accepted/frozen release contracts with the required frozen gates for `release_or_research_production` and `full_scale`. One qualification scope never inherits authorization from another;
- the deterministic validator bundle and failure taxonomy for the stage exist;
- minimum verified gold and development coverage for the stage is met, with values defined in configuration;
- a mock/fixture end-to-end dry run succeeds;
- the raw/input/output artifact lifecycle and resume/idempotency behavior are tested;
- secrets are managed outside the repository;
- cost and rate-limit policies are defined;
- a kill switch / circuit breaker is available;
- enablement and run authorization are default-deny.

Stage-specific readiness profiles extend these requirements; one stage's readiness never enables another stage.

## Rollout sequence

```text
mock_only → live_dev → controlled_pilot → release_or_research_production → full_scale
```

- `mock_only` (default): no network; fixture/mock providers; deterministic integration testing.
- `live_dev`: development partition or explicitly designated non-frozen development cases only; low record/call/token budgets defined in configuration; single stage; manual run authorization; outputs never auto-promoted to the production corpus.
- `controlled_pilot`: predeclared pilot cohort defined in a separate design document; cohort size is never hardcoded in schemas or policy; per-run budgets and stop conditions; mandatory post-run review.
- `release_or_research_production`: required qualification scope complete; required frozen release gates passed; monitoring, drift, and rollback policies active.
- `full_scale`: no-premature-scale gates passed; pilot findings closed; capacity, storage, review workload, and recovery plans verified.

Each transition is an append-only enablement event; prior records are never mutated. Frozen partitions are never used in `live_dev`; frozen use follows the predeclared purposes in ADR-015.

## Canonical runner requirements

All live calls run through the canonical runner with:

- an approved runner and versioned run configuration;
- explicit per-run authorization;
- manifest creation and input-packet resolution before the call;
- budget enforcement and artifact archival.

Ad-hoc SDK calls are prohibited in the normal workflow. An exploratory diagnostic call must be explicitly marked `noncanonical_experiment`, requires separate approval, and never enters production or evaluation records.

## Provenance: raw before parse

Before each call, record: the resolved input packet, input/source snapshot hashes, prompt artifact and hash, execution contract and hash, intended provider/model/route, request configuration, and run authorization ID.

During and after each call, record: provider request ID, actual provider/model/route, timestamps, retry attempts, provider status, latency, token/usage metadata, estimated and actual cost, the raw response archived immutably before parsing, response metadata, and any error artifact.

Parsed predictions are new artifacts with `derived_from` links; raw artifacts are never overwritten.

## Idempotent execution fingerprints

The canonical request fingerprint is: stage + input-packet hash + prompt hash + execution-contract hash + request-configuration hash. A previously completed canonical request defaults to cache/reuse or requires explicit rerun approval. Resume never re-calls completed records, prevents duplicate prediction artifacts, and records every retry and resume event in the manifest.

## Routing and fallback

Undeclared fallback is contamination: use of a model or endpoint outside the authorized contract produces a `route_contamination` finding and may invalidate the run. Declared routing bundles require a versioned routing policy, separately qualified primary and fallback contracts, per-record actual-route and route-reason records, and route-level metric and cost slices.

## Budget, rate-limit, and safety configuration

Every authorized run carries a versioned configuration defining at least: maximum records, requests, input/output tokens, estimated cost, and wall-clock duration; concurrency limit; rate-limit policy; retry limit; circuit-breaker conditions; maximum consecutive failures; and a stop-on-critical-validator-failure policy. Numeric values live in versioned configuration, never in this specification or in schemas.

On limit exhaustion the runner initiates no new calls and closes the run. Evaluation execution status remains exactly `completed`, `invalid`, or `errored` (ADR-019); values such as `budget_exhausted`, `circuit_breaker_triggered`, `provider_error`, and `manually_stopped` are typed `termination_reason` or `error_reason` values attached to an `invalid` or `errored` run as appropriate — never execution statuses. Partial artifacts and the exact stop point are preserved.

## Vocabulary separation

Deployment environment (identified by `deployment_environment_id` under a versioned deployment-environment policy; values are not enumerated in this specification), rollout state (`mock_only` … `full_scale`), enablement status (`disabled` … `revoked`), and evaluation execution status (`completed`, `invalid`, `errored`) are four distinct vocabularies. No value from one vocabulary may be interpreted as a value from another.

## Secret management

Credentials are provided only through environment or secret managers; never committed to the repository; never logged. Request/response artifacts follow a redaction policy. Enabled providers and endpoints are allowlisted. Live network calls require an explicit `--live` (or equivalent) authorization; default behavior is mock/dry-run.

## Suspension, revocation, and requalification

Enablement statuses include at least: `disabled`, `enabled_live_dev`, `enabled_pilot`, `enabled_release`, `suspended`, `expired`, `revoked`.

Automatic or manual suspension triggers include: provider/model drift, qualification contract changes, critical validator regressions, cost anomalies, route contamination, credential or security events, provider terms or endpoint changes, and repeated runtime failures.

Prior enablement records are never deleted; new events derive the current operational state. Requalification follows the predeclared change-classification policy (ADR-021).

## Audit records

Every executed run produces an audit trail linking the enablement record, run authorization, manifests, provenance records, budget outcomes, route records, and any findings. Every live enablement requires an append-only operational change-control record, and paid external calls require explicit methodology-owner approval.

## Acceptance criteria

- default-deny is enforced for enablement and run authorization;
- the state chain is fully reconstructable from append-only records;
- no live call can bypass the canonical runner in the normal workflow;
- raw responses are archived before parsing;
- identical canonical requests are not silently re-executed;
- Phase 1 delivers data models, readiness contracts, mock-runner integration, budget configuration, and default-deny enforcement only.

## Revision history

- 2026-07-19 — Created per ADR-022: adapter qualification, enablement, and run-authorization contract; Phase 1 limited to contracts, records, interfaces, and stubs.
