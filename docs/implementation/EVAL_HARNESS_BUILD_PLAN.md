# Evaluation Harness Build Plan

## Purpose

This document converts the evaluation methodology into a dependency-ordered
implementation sequence of small, reviewable slices. The objective of Phase 1
is the evaluation-harness core: a reliable, immutable, contract-driven
mechanism for deciding whether a candidate improved general performance
without violating evidence, temporal, schema, or contamination rules.

Governing contracts: `schemas/evaluation_case.schema.json`,
`schemas/evaluation_result.v2.schema.json`,
`schemas/universe_run_manifest.v2.schema.json`, SPEC-020, SPEC-022, SPEC-023,
SPEC-024, SPEC-025, SPEC-027, `evals/EVAL_HARNESS.md`,
`evals/CHANGE_CONTROL_PROTOCOL.md`, and ADR-011..ADR-022 in
`docs/DECISION_LOG.md`.

## Phase 1 boundary

Phase 1 implements the evaluation-harness core only:

- immutable evaluation-case loading and validation;
- external case-set partition/suite membership;
- versioned reference and scoring/gate-configuration resolution;
- immutable evaluation-run creation;
- canonical prediction/result envelopes where required by the evaluator;
- assertion-level evaluation;
- deterministic validation findings and append-only finding dispositions;
- execution status (`completed`, `invalid`, `errored`) and, for completed
  runs only, the gate verdict (`pass`, `fail`, `indeterminate`);
- axis-native metrics with coverage, abstention, and false-confidence
  reporting;
- immutable comparison artifacts and comparable assertion-transition
  analysis, including bridge re-evaluation for changed contracts;
- artifact persistence outside extraction-output directories;
- schema validation and compatibility tests;
- the CLI / canonical-runner entry points required for the harness;
- the final evaluation-contract finalization and regression-validation slice.

Explicitly deferred beyond Phase 1 (interface contracts or stubs only, where
already approved by SPEC-025 or SPEC-027):

- the full local review console;
- frozen-set access-control enforcement infrastructure;
- live SEC/source adapters and live model-provider integrations;
- secrets and production credential handling;
- controlled-pilot, release, and full-scale rollout execution;
- production monitoring services;
- webhook/event-triggered execution;
- global activation of `universe_run_manifest.v2.schema.json` (see the
  activation boundary below).

## Schema-activation boundary (selected design: evaluation-only activation)

Audited facts. The active mapping in `schemas/schema_version_manifest.json`
is consumed by exactly two readers: `universe/freeze.py:92`, which embeds the
entire mapping verbatim into every Phase 0 run manifest
(`"schema_versions": schema_versions` at `freeze.py:118`), and
`universe/runner.py:149`, which stamps mapping values into
`firm_year_eligibility`, `firm_lineage`, and `company` output records
(`runner.py:363,368,372`). Therefore adding any successor entry to the active
mapping changes the serialized bytes of every future Phase 0 run manifest.
Global activation through that manifest cannot be byte-stable and is not used
in Phase 1.

Selected design:

- The evaluation package owns an explicit, code-level **evaluation schema
  registry** (`evaluation/schemas.py`) that loads
  `evaluation_case.schema.json` and `evaluation_result.v2.schema.json` by
  explicit filename/version. These two contracts are active **for the
  evaluation package only**, from the slice that introduces them.
- `schemas/schema_version_manifest.json` remains byte-for-byte unchanged
  throughout Phase 1. Phase 0 writers, their embedded schema mapping, and
  all Phase 0 outputs remain byte-for-byte unchanged.
- `universe_run_manifest.v2.schema.json` remains a readable compatibility
  contract via explicit version routing (`evaluation/compat.py`); it is not
  made the default for Phase 0 writers during Phase 1. Its global activation
  is a separately approved future migration with its own change set and
  decision record.

Runtime selection-path coherence (why partial activation cannot occur):

1. Phase 0 paths (`freeze.py`, `runner.py`) read only the active manifest —
   unchanged.
2. Evaluation paths read only the evaluation schema registry — explicit
   filenames/versions, never the active manifest.
3. `validation.py` and `tests/schema/` glob all `schemas/*.schema.json` for
   meta-validation only; they perform no runtime selection.

No selection path consults both sources, so no commit can produce a mixed
activation state.

## Package grounding

The implementation extends the existing package family rather than creating a
parallel architecture. Reused foundations: `universe/io_utils.py`
(read/write/hash helpers), the immutable run-directory pattern in
`universe/freeze.py` (`create_run_directory`), the Typer CLI pattern in
`validation.py`, the pydantic `StrictModel` pattern in `universe/models.py`,
the versioned-config pattern in `configs/universe_sample_rules.yaml`
(explicit in-file version field), and the auto-globbing schema validation in
`tests/schema/` and `validation.py`.

New module family: `src/dynamic_ai_products/evaluation/` with tests under
`tests/evaluation/` and Phase 1 fixtures under a new
`evals/fixtures/evaluation_harness/` bundle. Fixture scenarios must cover at
least the previously accepted failure families: valid product extraction; AI
marketing wording only; future roadmap capability; duplicated task;
capability/task confusion; unsupported task; wrong-date evidence; valid
multi-step workflow execution; renamed product; bundle versus product;
internal R&D that is not customer-facing; valid customer-facing AI
capability.

## Repository-manifest rule (applies to every slice)

`tests/universe/test_repo_hygiene.py` enforces exact parity between
`REPO_MANIFEST.md` and the tracked/non-ignored file set. Therefore every
slice that adds, removes, or renames a tracked path must include, in the same
slice: the minimal `REPO_MANIFEST.md` entry changes in canonical ordering,
the mechanical header-count update, and parity/duplicate validation. Manifest
updates are never postponed to a later slice.

## Persisted-artifact contracts

Typed Pydantic models (`StrictModel`, extra forbidden) are the initial
canonical contracts for all Phase 1 evaluation artifacts that have no static
JSON Schema. Compatibility readers select by the recorded
`contract_version`; validation on both write and read is performed by the
owning model. Introducing additional static JSON Schema files is NOT part of
this plan; any such addition is a separate spec/version decision (SPEC-022
governance) with its own approval and REPO_MANIFEST effect.

Canonical model-contract hash algorithm (owned by
`evaluation/contracts.py`, tested by `tests/evaluation/test_contracts.py`):

1. construct a contract envelope containing at least the stable
   `contract_id`, the explicit `contract_version`, and the model's generated
   JSON Schema;
2. serialize the envelope as canonical UTF-8 JSON — recursively sorted
   object keys, compact separators, no platform-dependent whitespace —
   exactly `json.dumps(envelope, sort_keys=True, separators=(",", ":"),
   ensure_ascii=False).encode("utf-8")`;
3. compute SHA-256 over those exact UTF-8 bytes (digest via the existing
   `universe/io_utils.sha256_bytes`; the canonical-envelope serializer is a
   new, smallest helper in the evaluation package — Phase 0 hashing behavior
   is not altered);
4. persist both `contract_version` and `contract_hash` in artifact metadata
   and verify the declared hash on every read;
5. a changed generated-schema hash is a contract change requiring review,
   compatibility handling, and version governance — never a silent rewrite;
6. record the Pydantic/runtime dependency version in run provenance so
   unexpected schema-generation drift is diagnosable.

Prohibited as hash inputs: Python dict display order, pretty-printed JSON,
filesystem formatting, or an unversioned `model_json_schema()` result alone.
Required focused tests: identical contracts produce identical hashes; object
key order does not affect the hash; contract-version changes alter the hash;
schema changes alter the hash; artifact reads reject a declared-hash
mismatch.

| Artifact | Owning model (module) | Format | Contract | Static schema exists? | New static schema? |
|---|---|---|---|---|---|
| Evaluation case | `EvaluationCase` (`evaluation/models.py`) | JSON, one file per case | `schemas/evaluation_case.schema.json` 0.1.0 + model | Yes | No |
| Case-set manifest | `CaseSetManifest` (`evaluation/models.py`) | JSON | model `contract_version` + hash | No | No (deferred decision) |
| Membership events | `MembershipEvent` (`evaluation/models.py`) | JSONL, append-only | model `contract_version` | No | No (deferred decision) |
| Evaluation-run manifest | `EvaluationRunManifest` (`evaluation/models.py`) | JSON in run dir | model `contract_version` + pinned hashes | No | No (deferred decision) |
| Prediction envelope | `PredictionEnvelope` (`evaluation/models.py`) | JSONL | model `contract_version` | No | No (deferred decision) |
| Assertion outcome | `AssertionOutcome` (`evaluation/models.py`) | JSONL in run dir | model `contract_version` | No | No (deferred decision) |
| Validator finding | `ValidatorFinding` (`evaluation/models.py`) | JSONL, immutable | model `contract_version` + bundle hash | No | No (deferred decision) |
| Finding disposition | `FindingDisposition` (`evaluation/models.py`) | JSONL, append-only | model `contract_version` | No | No (deferred decision) |
| Metric report | `MetricReport` (`evaluation/models.py`) | JSON in run dir | model `contract_version` | No | No (deferred decision) |
| Evaluation result | `EvaluationResultV2` (`evaluation/models.py`) | JSON in run dir | `schemas/evaluation_result.v2.schema.json` 0.2.0 + model | Yes | No |
| Comparison artifact + transition records | `ComparisonArtifact`, `AssertionTransition` (`evaluation/models.py`) | JSON + JSONL in comparison dir | model `contract_version` + deterministic output hash | No | No (deferred decision) |
| Scoring/gate config snapshot | `ScoringGateConfig` (`evaluation/scoring_config.py`) | versioned YAML/JSON under `configs/` (pattern: `universe_sample_rules.yaml`) + hashed snapshot copy in run dir | in-file version field + SHA-256 | No | No (deferred decision) |

Immutability rules: run-scoped artifacts are write-once inside a
refuse-to-overwrite run directory; JSONL event artifacts are append-only;
nothing mutates a case, manifest snapshot, finding, or historical artifact.

Artifact validity semantics (which artifacts may exist per execution
status):

| Artifact | completed | invalid | errored |
|---|---|---|---|
| Evaluation-run manifest | yes | yes — persisted whenever creation progressed far enough to record the failure, with execution diagnostics | yes — same rule |
| Evaluation result (v2) | yes, with `gate_verdict` | yes, without `gate_verdict` | yes, without `gate_verdict` |
| Validator findings / dispositions | yes | yes (including the blocking resolution findings) | yes, as far as produced |
| Normalized envelopes, assertion outcomes | yes | only as explicitly marked partial artifacts | only as explicitly marked partial artifacts |
| Metric report | yes | **never** | **never** |
| Comparison artifact / transition records | yes (both runs completed) | **never** | **never** |
| Scoring/gate config snapshot, raw inputs / provider outputs already obtained | yes | yes — preserved for audit | yes — preserved for audit |

Invalid/errored artifacts carry execution diagnostics but no gate verdict;
metric and comparison artifacts must never imply a completed evaluation when
blocking input resolution failed; partial artifacts are explicitly marked
and never masquerade as completed immutable artifacts.

## Evaluation artifact root (parametric)

The evaluation artifact root is an explicit, required `eval_root` /
`--eval-root` parameter. No default is introduced during normal
implementation slices. If a default ever becomes necessary, the implementing
agent must stop and request a separately approved decision-log/spec change;
nothing in this plan or the implementation prompt authorizes that change.
Evaluation artifacts never live inside extraction-output directories; ad hoc
JSONL is never the canonical evaluation store; runs use immutable, run-scoped
directories following the `create_run_directory` pattern; where model
execution is involved, raw provider output is preserved before parsing.

## Case-set and frozen-evaluation boundaries

Phase 1 implements the data contracts and validation rules for: immutable,
split-agnostic case files; authoritative, versioned, append-only case-set
manifests owning membership; exclusive partition (`dev` | `frozen_test`) and
overlapping suites; membership changes only through a new case-set version;
immutable frozen snapshots; exposure contamination moving cases to `dev`
only in a later version; no silent approval and no silent frozen mutation.
Access-control enforcement infrastructure and the review console remain
deferred. No case counts, audit sample sizes, reviewer identities, retention
periods, or frozen thresholds are defined here; they live in versioned
policy/configuration.

## Evaluation semantics (binding for every slice)

- Assertions are the atomic scoring unit; a case has one or more assertions.
- Assertion kinds: `expected_entity`, `forbidden_entity`, `field_value`,
  `evidence_provenance`, `deterministic_validation`.
- Assertion identity uses a semantic version, a contract hash, or both;
  target references and `scoring_gate_config_references` are explicit and
  non-empty.
- Protected classes, severities, gate rules, and thresholds are obtained
  exclusively through the versioned scoring/gate configuration reader
  (Slice 4); they are never hardcoded in case files or Python constants.
- Assertion outcomes are run artifacts, not immutable case fields.
- `UNKNOWN` remains distinct from negative outcomes; abstention, coverage,
  and false confidence are reported; low-support metrics may be
  `indeterminate`.
- Invalid or errored runs have no gate verdict and are neither passing
  evaluations nor regressions.
- A blocking failure cannot be overridden into a pass; exceptions remain
  separate records and the failed evaluation remains failed; gate outcomes
  never automatically accept or freeze an artifact.

## Comparison and qualification boundaries

Comparison primitive (SPEC-024): assertion identity includes the applicable
version/hash inputs; a comparison records rich old/new outcomes and the
transition type; changed assertion contracts are non-comparable by default;
bridge re-evaluation may restore comparability; baseline selection is
predeclared. Per SPEC-024 "Comparison artifacts": a comparison is a separate
immutable artifact carrying its own execution status (`completed`,
`invalid`, `errored`) and verdict (`pass`, `fail`, `indeterminate`), with a
deterministic output hash; aggregate gate results remain separate from
assertion-transition data; invalid runs produce no regression claims.

Adapter/model qualification stays at the Phase 1 contract/stub boundary
(SPEC-024, SPEC-027): qualification binds prompt artifact ×
execution/routing contract × stage/output contract; mutable provider labels
are not immutable qualification identity; enablement binds exact qualified
artifacts; run authorization remains default-deny; source and model
readiness remain separate; no live network call is introduced in this phase.

## Dependency-ordered implementation slices

Dependency chain: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 → 10 → 11 → 12 → 13 →
14, where Slice 4 (references/config) must be completed and validity-checked
before run pinning (5), assertion dispatch (7), and any metric, gate, or
comparison execution (9–11), and Slice 12 (compat/bridge) depends on 10–11.
Metric reports and comparison artifacts exist only for `completed` runs;
blocking resolution failures short-circuit to `execution_status = invalid`.

Rules for every slice: focused tests green; full suite green
(`PYTHONPATH=src python -m pytest -q`); schema CLI green; REPO_MANIFEST
updated in-slice for any tracked-path change; complete diff and hash report;
stop/review point before the next slice; no test modified to conceal a
failure; Phase 0 outputs byte-for-byte unchanged; the active schema-version
manifest untouched.

### Slice 1 — Shared typed models and the evaluation schema registry

- Objective: typed models for all persisted-artifact contracts above; the
  canonical contract-hash helper; the evaluation-only schema registry. The
  registry (`evaluation/schemas.py`) binds evaluation contract IDs and
  versions to exact schema paths AND expected file hashes; selects
  `evaluation_case.schema.json` and `evaluation_result.v2.schema.json` only
  for evaluation-package readers/writers; allows explicit compatibility
  reading of `universe_run_manifest.v2.schema.json` without ever making it a
  Phase 0 writer default; never reads or mutates the active Phase 0
  schema-version mapping; and fails closed on an unknown contract
  ID/version or a hash mismatch.
- Governing: SPEC-022, SPEC-023; both static evaluation schemas.
- Existing files modified: none.
- New files: `src/dynamic_ai_products/evaluation/__init__.py`,
  `evaluation/models.py`, `evaluation/contracts.py`,
  `evaluation/schemas.py`;
  `tests/evaluation/__init__.py` (if package-style tests are used),
  `tests/evaluation/test_models.py`, `tests/evaluation/test_contracts.py`,
  `tests/evaluation/test_schema_registry.py`.
- REPO_MANIFEST: add each new tracked path; header count updated.
- Persisted artifacts: none yet (models only).
- Contract: static evaluation schemas + model `contract_version` mechanism.
- Deferred: everything downstream.
- Stop point: models round-trip schema examples; registry rejects unknown
  versions; active manifest untouched.

### Slice 2 — Evaluation-case parsing and validation

- Objective: load/validate immutable case files; reject prohibited legacy
  fields with structured errors.
- Governing: SPEC-022; ADR-011.
- Existing files modified: none.
- New files: `evaluation/cases.py`; `tests/evaluation/test_cases.py`;
  first fixture files under `evals/fixtures/evaluation_harness/cases/`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: none (read-side).
- Contract: `evaluation_case.schema.json` + `EvaluationCase`.
- Stop point: template and fixtures load; prohibited-field fixtures rejected.

### Slice 3 — Case-set manifest, partition, and suite membership

- Objective: `CaseSetManifest` + `MembershipEvent` handling with exclusive
  partition, overlapping suites, snapshot hashing, append-only events.
- Governing: SPEC-022, ADR-013, ADR-014, ADR-015 (data contracts only).
- Existing files modified: none.
- New files: `evaluation/case_sets.py`; `tests/evaluation/test_case_sets.py`;
  manifest fixtures under `evals/fixtures/evaluation_harness/case_sets/`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: case-set manifest (JSON), membership events (JSONL).
- Stop point: membership reconstructable; conflicts rejected; frozen
  snapshots hash-stable.

### Slice 4 — Reference and scoring/gate-configuration resolution

- Objective: versioned target/gold registry reader and versioned
  scoring/gate configuration reader; artifact identity and hash
  verification; structured findings for missing, duplicate, or conflicting
  references; immutable snapshot binding material (hashes) for runs.
- Blocking resolution failures (validity-blocking input failures):
  target/gold registry artifact missing; scoring/gate configuration artifact
  missing; referenced contract version unknown; expected snapshot hash
  mismatch; duplicate reference ID in the same registry; conflicting
  definitions for the same reference ID; assertion target reference
  unresolvable in the pinned target registry; scoring/gate configuration
  reference unresolvable in the pinned configuration snapshot.
- Required behavior on any blocking failure: emit an immutable deterministic
  finding for traceability; affected assertions may be recorded
  `not_evaluated`; the run receives `execution_status = invalid` with no
  `gate_verdict`; no metrics and no regression claims are produced as though
  the run completed; the failure is never converted into `indeterminate`,
  `fail`, or `pass`; dispositions or exceptions never make the invalid run
  valid.
- Distinct from failure: a reference that resolves successfully while the
  prediction does not satisfy the referenced expectation is a normal
  assertion outcome (for example `unsatisfied`), never an invalid input.
- Ownership: registry/config loaders return typed resolution results or
  structured resolution errors; the runner's validity layer converts any
  blocking resolution error into `execution_status = invalid`; assertion
  dispatch never silently treats an unresolved contract reference as an
  ordinary negative prediction.
- Protected classes, severities, rules, and thresholds are read from the
  versioned configuration only.
- Governing: SPEC-022 (`scoring_gate_config_references`), SPEC-023, ADR-017,
  ADR-019.
- Existing files modified: none.
- New files: `evaluation/references.py`, `evaluation/scoring_config.py`;
  `tests/evaluation/test_references.py`,
  `tests/evaluation/test_scoring_config.py`; example versioned config
  fixture under `evals/fixtures/evaluation_harness/configs/` (fixture only —
  a production config under `configs/` is created only when first needed,
  with its own REPO_MANIFEST entry; no threshold, protected-class, or
  severity values are defined by this plan).
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: scoring/gate config snapshot copy (hash-verified) in
  the run directory (written by Slice 5 machinery).
- Focused tests: one per listed blocking failure (each proving finding +
  `execution_status = invalid` + absent gate verdict + absent metrics), plus
  the resolved-reference-but-unsatisfied distinction.
- Stop point: resolution completed and validity-checked before metrics,
  gates, or comparisons can execute; no hardcoded policy anywhere.

### Slice 5 — Immutable run identity and artifact persistence

- Objective: evaluation-run identity and refuse-to-overwrite run directories
  under the caller-supplied `eval_root`; `EvaluationRunManifest` pinning
  prediction run ID + manifest hash, case-set version/hash, registry
  snapshot hash, validator bundle hash, scoring/gate config version/hash,
  code commit, and the Pydantic/runtime dependency version (contract-hash
  drift diagnosability).
- Governing: SPEC-024, ADR-012.
- Existing files modified: none (reuses `io_utils`,
  `freeze.create_run_directory` pattern by local implementation, not by
  changing `freeze.py`).
- New files: `evaluation/runs.py`; `tests/evaluation/test_runs.py`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: run manifest (JSON), config snapshot copy.
- Stop point: same-run-ID rerun fails loudly; all pins recorded by hash.

### Slice 6 — Prediction/result normalization (canonical envelopes)

- Objective: adapter layer producing `PredictionEnvelope` records from
  manifest-bearing prediction artifacts; explicit import producing a
  manifest-bearing eval input snapshot for ad hoc files.
- Governing: SPEC-022 (prediction envelope), ADR-012.
- Existing files modified: none.
- New files: `evaluation/envelopes.py`; `tests/evaluation/test_envelopes.py`;
  prediction fixtures under `evals/fixtures/evaluation_harness/predictions/`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: normalized envelopes (JSONL) inside the run dir.
- Stop point: raw stage output is never scored directly.

### Slice 7 — Assertion evaluation dispatch and identity checks

- Objective: dispatch by `kind` over resolved references; identity checks;
  `AssertionOutcome` artifacts with the vocabulary `satisfied`,
  `unsatisfied`, `indeterminate`, `not_applicable`, `not_evaluated`.
- Governing: SPEC-022, ADR-011, ADR-020.
- Existing files modified: none.
- New files: `evaluation/assertions.py`;
  `tests/evaluation/test_assertions.py`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: assertion outcomes (JSONL) in run dir.
- Stop point: all five kinds covered at the common-contract level; an
  unresolved contract reference yields a finding plus `not_evaluated` and is
  escalated to the runner's validity layer (`execution_status = invalid`) —
  never treated as an ordinary negative prediction; a resolved-but-
  unsatisfied expectation yields the normal `unsatisfied` outcome.

### Slice 8 — Deterministic validator findings and dispositions

- Objective: the SPEC-023 validator set emitting immutable
  `ValidatorFinding` records with full provenance; append-only
  `FindingDisposition` records; lifecycle state derived from events.
- Governing: SPEC-023, SPEC-022, ADR-018.
- Existing files modified: none.
- New files: `evaluation/validators.py`, `evaluation/dispositions.py`;
  `tests/evaluation/test_validators.py`,
  `tests/evaluation/test_dispositions.py`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: findings (JSONL, immutable), dispositions (JSONL,
  append-only).
- Stop point: identical bundle+artifact reproduce identical findings;
  dispositions never enter gate arithmetic.

### Slice 9 — Metric aggregation, coverage, and abstention reporting

- Objective: axis-native metric families plus coverage, selective-risk,
  unnecessary-abstention, false-confidence, and correct-abstention
  reporting; support metadata on every metric; low-support slices yield
  `indeterminate`.
- Governing: SPEC-020, ADR-013, ADR-016, ADR-017.
- Existing files modified: none.
- New files: `evaluation/metrics.py`; `tests/evaluation/test_metrics.py`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: `MetricReport` (JSON) in run dir.
- Contract: thresholds/protected classes consumed only from the Slice 4
  configuration reader.
- Stop point: no aggregate metric acts as a gate by itself.

### Slice 10 — Gate evaluation and status/verdict separation

- Objective: layered gate evaluation (validity → behavioral invariants →
  metric/regression gates) producing `execution_status` and, only for
  completed runs, `gate_verdict`; serialization validated against
  `evaluation_result.v2.schema.json` via the evaluation schema registry.
- Governing: SPEC-020, ADR-019.
- Existing files modified: none.
- New files: `evaluation/gates.py`; `tests/evaluation/test_gates.py`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: `EvaluationResultV2` (JSON) in run dir.
- Stop point: v2 conditional contract exercised on valid and invalid sides;
  `conditional_pass` nonexistent.

### Slice 11 — Immutable comparison and assertion-transition artifacts

- Objective: `ComparisonArtifact` with its own identity, manifest, execution
  status, and verdict per SPEC-024; `AssertionTransition` ledger with
  noncomparability classes; derived case-level ledger; predeclared baseline
  roles; deterministic output hash.
- Governing: SPEC-024, ADR-020.
- Existing files modified: none.
- New files: `evaluation/comparator.py`;
  `tests/evaluation/test_comparator.py`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: comparison manifest + transition ledger in a
  comparison-scoped immutable directory under `eval_root`.
- Stop point: identical inputs reproduce identical output hashes; invalid
  runs produce no regression claims.

### Slice 12 — Compatibility readers and bridge re-evaluation

- Objective: explicit-version readers for v1 `evaluation_result` and v1/v2
  `universe_run_manifest` documents (historical artifacts stay readable);
  bridge re-evaluation re-running both prediction sets under a new
  validator/scoring contract to restore comparability.
- Governing: SPEC-024, ADR-012, ADR-020.
- Existing files modified: none.
- New files: `evaluation/compat.py`; `tests/evaluation/test_compat.py`.
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: bridge evaluation runs (ordinary immutable eval runs).
- Stop point: `eval_report_ids` read as optional deprecated data; no
  reverse-link field anywhere; round-trip tests over v1- and v2-shaped
  documents pass.

### Slice 13 — Canonical runner / CLI orchestration

- Objective: `python -m dynamic_ai_products.evaluation.runner` (Typer,
  following `validation.py`): load case set → resolve references/config →
  normalize predictions → evaluate assertions → validators → metrics →
  gates → persist immutable run under required `--eval-root`; machine- and
  human-readable reports.
- Governing: SPEC-020, SPEC-024.
- Existing files modified: none expected; if a shared CLI registration point
  must change, that file is named in the pre-slice audit and approved first.
- New files: `evaluation/runner.py`, `evaluation/report.py`;
  `tests/evaluation/test_runner.py` (fixture end-to-end; no network, no paid
  APIs).
- REPO_MANIFEST: add new tracked paths.
- Persisted artifacts: full run-directory artifact set.
- Stop point: exit codes documented as operational runner behavior, distinct
  from execution status and gate verdict.

### Slice 14 — Evaluation package release binding and final compatibility validation

- Objective: bind the evaluation package's released contract set (contract
  IDs, versions, schema paths, expected hashes) as a reviewed code-level
  constant in `evaluation/schemas.py`; run the full regression matrix; write
  the harness usage documentation. This is neither global nor atomic schema
  activation — it is the evaluation package's own release binding.
- Explicitly NOT in this slice: any change to
  `schemas/schema_version_manifest.json` (stays byte-for-byte unchanged);
  any Phase 0 writer/reader change; any global activation of
  `universe_run_manifest.v2.schema.json` — that migration is a separately
  approved future change set with its own preconditions, rollback, and
  decision record.
- Existing files modified: `evaluation/schemas.py` (finalized registry) and
  the usage-documentation file. The usage-documentation pathname is selected
  during this slice only after a repository audit and explicit approval; if
  it is a new tracked file, its REPO_MANIFEST entry lands in the same slice.
- Validation: full pytest suite; schema CLI; manifest parity; v1 round-trip
  compatibility tests; sentinel runner suite proving Phase 0 outputs
  unchanged.
- Rollback: reverting this slice reverts only the registry finalization and
  documentation; no historical artifact, Phase 0 output, or active manifest
  is affected at any point.
- Stop point: Phase 1 complete; any global universe-manifest activation
  request goes back to explicit approval.

## Commit and review topology

- One implementation slice per commit (a slice may span more than one commit
  when a reviewable boundary requires it, never the reverse).
- Every slice is validated before its commit; staging is explicit and
  path-limited; branch and commit hashes are recorded at each checkpoint.
- Slice 14 (contract finalization) is isolated as the final Phase 1 slice.
- No history rewriting, no automatic merge to `main`, no force-push; commits
  and pushes only with explicit approval.

## Later phases (outline only, unchanged in intent)

- Pipeline integration: connect extraction stages to the harness via
  manifest-bearing prediction runs.
- Longitudinal and measurement evaluation: matching fixtures, transition
  metrics, frontier-baseline validation, unknown calibration,
  source-ablation comparisons.
- Global `universe_run_manifest.v2` activation migration (separately
  approved).
- Review console (SPEC-025) and adapter qualification/enablement execution
  (SPEC-027) follow their own specs after the harness core is accepted.

## Stop conditions

Each implementation slice must stop after: deliverables written; tests pass;
commands documented; changed files listed with hashes; limitations
summarized. The implementing agent must not automatically continue into the
next slice.
