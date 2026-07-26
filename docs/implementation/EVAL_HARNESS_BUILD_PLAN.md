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

Dependency chain (Slices 1–12 are linear): 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8 → 9 →
10 → 11 → 12, where Slice 4 (references/config) must be completed and
validity-checked before run pinning (5), assertion dispatch (7), and any metric,
gate, or comparison execution (9–11), and Slice 12 (compat/bridge) depends on
10–11. Prerequisite Slices 12A–12M (ADR-024, ADR-025) implement the
semantic-evaluation substrate — the producers that turn governed references and
raw predictions into `ResolvedAssertionEvaluation`, `ValidationArtifactSnapshot`,
and `MetricInputSnapshot` values — before Slice 13, and form a directed acyclic
graph rather than a single chain:

- 12 → 12A → 12B;
- 12B → {12C, 12D, 12E};
- 12D → 12F;
- 12F → 12G;
- {12D, 12E, 12G} → 12H;
- {12A, 12E, 12G, 12H} → 12I;
- 12I → 12J → 12K;
- {12B, 12I, 12J, 12K} → 12L;
- {12A, 12B, 12D, 12E, 12F, 12G, 12H, 12I, 12J, 12K, 12L} → 12M;
- {12C, 12M} → Xe2a → Xe-bind → P1 → {P2, P3} → 13 → 14.
- Slice 13B (multi-case / package-case runner) is outside Phase 1; its
  precondition is a separate design lock that explicitly changes the
  evaluation-cardinality contract in `assertions.py` (ADR-027).

Deterministic validation (validator-rule parameters, the validator-bundle
artifact, `ValidatorRuleCoverage`, and the validation-artifact snapshot set) is
produced before semantic assertion evaluation, which consumes it. Slice 13
(canonical runner) is a thin orchestrator that invokes these producers; it
defines no semantic evaluator.
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

## Prerequisite semantic-substrate slices (ADR-024, ADR-025)

Slices 12A–12M implement the semantic-evaluation substrate that the committed
Slices 1–12 deferred to the caller. They are ordinary reviewable slices inserted
before Slice 13; Slices 1–12 are not renumbered and Slice 14 remains the final
Phase-1 slice.

**Protection rule (authoritative for every prerequisite slice):** every path
tracked at the slice's baseline HEAD that is not listed in that slice's exact
`Modified paths` set remains byte-identical; new paths are limited to that
slice's exact `New paths` set. Stage/payload implementation models are
module-private and add no package exports. Cumulative totals from baseline
exports 420 / manifest 323 are locked: 12A 430/326; 12B 433/327; 12C 433/327;
12D 459/339; 12E 476/345; 12F 494/351; 12G 502/354; 12H 505/356; 12I 520/361;
12J 524/362; 12K 525/362; 12L 531/364; 12M 531/381. Prerequisite slices Xe2a,
Xe-bind, P1, P2, and P3 land between 12M and Slice 13 and each raise the
baseline, so Slice 13's totals are stated relatively: its three new tracked
paths add exactly 3 to whatever manifest count its own baseline HEAD carries. Preserved committed contract hashes:
`evaluation_run_manifest@0.1.0` `7f8909d8e7059952c933c8e30f43044178b3f8a21d4baaa77bfb5c786b38d6ee`,
`metric_report@0.1.0` `d9e3f6d7399af628b38754758a7cb580e57955ad695ee7d92fb56c67c4ceac39`,
`validator_finding@0.1.0` `96f63fee300d363a662f4f956bacccdca596acfb0f22bf7039aa1335b6d61292`,
`comparison_manifest@0.2.0` `6a1253b72664bff73e872d1230fb3d52772a438f55915406010e105b4f5d29a5`.

### Slice 12A — Stage-profile registry
- Objective: hash-bound `evaluation_stage_profile_registry@0.1.0` mapping each supported evaluation stage to its applicable metric families and required stage-evidence kind; loader + run snapshot.
- Governing: SPEC-020, ADR-024. Depends on Slice 12.
- New paths: `src/dynamic_ai_products/evaluation/stage_profiles.py`; `tests/evaluation/test_stage_profiles.py`; `evals/fixtures/evaluation_harness/stage_profiles/stage_profile_registry.json`.
- Modified paths: `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 430, manifest 326.
- Stop point: registry loads, hashes, and snapshots deterministically; unsupported/duplicate stage rejected.

### Slice 12B — Evaluation-run manifest v0.2
- Objective: `evaluation_run_manifest@0.2.0` pinning the semantic inputs (ADR-025); frozen v0.1 historical model + governed constant + historical reader.
- Governing: SPEC-024, ADR-025. Depends on 12A.
- New paths: `tests/evaluation/test_run_manifest_v2.py`.
- Modified paths: `src/dynamic_ai_products/evaluation/models.py`; `src/dynamic_ai_products/evaluation/runs.py`; `tests/evaluation/test_runs.py`; `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 433, manifest 327.
- Stop point: v0.1 hash `7f8909d8…` preserved; `evaluation_created_at` round-trips; v0.2 pins present.

### Slice 12C — Comparator v0.2 binding
- Objective: comparator reads the v0.2 semantic-input hashes and maps them to the existing noncomparability vocabulary with no new class — a changed selected stage-profile entry identity/hash or a changed selected semantic-adapter entry identity/hash is `noncomparable_contract`; a changed gold/taxonomy/applicable-stage-evidence hash is `changed_gold`; a changed validator-bundle or validator-rule-parameters hash is `changed_validator_contract`; a changed stage-profile registry version/hash or semantic-adapter registry version/hash whose selected entry identity/hash is identical, and a global source/passage snapshot difference with identical consumed per-case packets, are provenance-only for pairwise comparison (not a change-control exemption); v0.1↔v0.2 is `noncomparable_contract`.
- Governing: SPEC-024, ADR-025. Depends on 12B.
- New paths: none.
- Modified paths: `src/dynamic_ai_products/evaluation/comparator.py`; `tests/evaluation/test_comparator.py`. Exports 433, manifest 327.
- Stop point: registry-pin classification exercised (selected-entry change vs registry-version-only change); no new `NoncomparabilityClass` value; `comparison_manifest@0.2.0` model hash `6a1253b7…` unchanged; v0.1↔v0.2 noncomparable.

### Slice 12D — Source/passage access, parsed prediction content, semantic-adapter registry
- Objective: `source_passage_snapshot_manifest@0.1.0` (reusing Phase-0 source/passage schema meanings), `parsed_prediction_content@0.1.0` with collection-completeness and validator-provenance fields, `evaluation_semantic_adapter_registry@0.1.0` with selected-entry identity; per-stage adapters; per-case observation-cutoff extraction from governed `stage_context`.
- Governing: SPEC-022, SPEC-023, ADR-024, ADR-025. Depends on 12B.
- New paths: `src/dynamic_ai_products/evaluation/source_snapshot.py`; `src/dynamic_ai_products/evaluation/prediction_content.py`; `src/dynamic_ai_products/evaluation/semantic_adapters.py`; `tests/evaluation/test_source_snapshot.py`; `tests/evaluation/test_prediction_content.py`; `tests/evaluation/test_semantic_adapters.py`; `evals/fixtures/evaluation_harness/source_snapshots/source_documents.jsonl`; `evals/fixtures/evaluation_harness/source_snapshots/source_passages.jsonl`; `evals/fixtures/evaluation_harness/source_snapshots/source_passage_snapshot_manifest.json`; `evals/fixtures/evaluation_harness/parsed_content/capability_extraction_raw.json`; `evals/fixtures/evaluation_harness/parsed_content/task_extraction_cutoff_probe.json`; `evals/fixtures/evaluation_harness/semantic_adapters/semantic_adapter_registry.json`.
- Modified paths: `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 459, manifest 339.
- Stop point: collection-completeness invariants; cutoff pointer `/stage_context/observation_window/end` proven; symlink/path rejection; selected-adapter-entry pin.

### Slice 12E — Gold assertion set and axis taxonomy
- Objective: `gold_assertion_set@0.1.0` (assertion-owned, kind-discriminated payloads, SPEC-022 gold provenance, registry-alias precedence, no parallel channel) and `axis_taxonomy@0.1.0`.
- Governing: SPEC-022, ADR-024. Depends on 12B.
- New paths: `src/dynamic_ai_products/evaluation/gold.py`; `src/dynamic_ai_products/evaluation/taxonomy.py`; `tests/evaluation/test_gold.py`; `tests/evaluation/test_taxonomy.py`; `evals/fixtures/evaluation_harness/gold/gold_assertion_set.json`; `evals/fixtures/evaluation_harness/taxonomy/axis_taxonomy.json`.
- Modified paths: `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 476, manifest 345.
- Stop point: gold operator/value-shape rejection; alias precedence; `target_registry` byte-identical.

### Slice 12F — Validator-rule parameters, validator-bundle artifact, coverage successor
- Objective: `validator_rule_parameters@0.1.0` (one entry per rule, four canonical stage-parameter entries, typed private payloads, complete per-rule hash) and `validator_bundle_artifact@0.1.0` generated as a reconciled pair; reopen `validators.py` to add the `ValidatorRuleCoverage` mixed-coverage ledger and the Rule 12 raw-output/repair fields. Deterministic validation is produced here, before semantic assertion evaluation.
- Governing: SPEC-023, ADR-024. Depends on 12D.
- New paths: `src/dynamic_ai_products/evaluation/validator_parameters.py`; `src/dynamic_ai_products/evaluation/validator_bundle_artifact.py`; `tests/evaluation/test_validator_parameters.py`; `tests/evaluation/test_validator_bundle_artifact.py`; `evals/fixtures/evaluation_harness/validator_parameters/validator_rule_parameters.json`; `evals/fixtures/evaluation_harness/validator_bundle/validator_bundle_artifact.json`.
- Modified paths: `src/dynamic_ai_products/evaluation/validators.py`; `tests/evaluation/test_validators.py`; `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 494, manifest 351.
- Stop point: complete per-rule hash equals `ValidatorRuleConfig.rule_params_hash`; mixed coverage; no dummy observation; `validator_finding@0.1.0` `96f63fee…` preserved.

### Slice 12G — Validation-artifact snapshot set
- Objective: contract-stamped `validation_artifact_snapshot_set@0.1.0` wrapping the committed per-artifact `ValidationArtifactSnapshot` primitives (twelve-rule coverage, per-record `artifact_sha256` binding); persistence.
- Governing: SPEC-023, ADR-024. Depends on 12F.
- New paths: `src/dynamic_ai_products/evaluation/validation_snapshot.py`; `tests/evaluation/test_validation_snapshot.py`; `evals/fixtures/evaluation_harness/validation/validation_artifact_snapshot_set.json`.
- Modified paths: `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 502, manifest 354.
- Stop point: twelve-rule coverage per element; per-record parsed-content hash binding.

### Slice 12H — Semantic assertion evaluators
- Objective: `build_resolved_assertion_evaluations` producing `ResolvedAssertionEvaluation` per kind from parsed content, gold, and source/passage access; feeds the committed `assertions.py` dispatcher (unchanged). Persisted audit artifact is the committed `AssertionOutcome`; `ResolvedAssertionEvaluation` is transient. `deterministic_validation` assertions consume the validator findings and coverage produced by Slice 12F and the validation-artifact snapshot set produced by Slice 12G.
- Governing: SPEC-020, SPEC-022, SPEC-023, ADR-024. Depends on 12D, 12E, 12G.
- New paths: `src/dynamic_ai_products/evaluation/semantic_assertions.py`; `tests/evaluation/test_semantic_assertions.py`.
- Modified paths: `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 505, manifest 356.
- Stop point: outcome semantics per ADR-024 Phases B and C for all five kinds, reachable only after deterministic validator findings/coverage (12F) and the validation snapshot (12G) are available; `assertions.py` unchanged.

### Slice 12I — Stage metric evidence set and active metric-input snapshot
- Objective: `stage_metric_evidence_set@0.1.0` (discriminated Universe evidence kinds; extraction stages carry none) and the first persisted, contract-stamped `metric_input_snapshot@0.1.0` (the public `MetricInputSnapshot` becomes the stamped model; screen/audit/tier behind the optional stage-evidence binding; applicability bindings); `compute_metric_report` stage-dispatch.
- Governing: SPEC-020, ADR-024. Depends on 12A, 12E, 12G, 12H.
- New paths: `src/dynamic_ai_products/evaluation/stage_evidence.py`; `src/dynamic_ai_products/evaluation/metric_inputs.py`; `tests/evaluation/test_stage_evidence.py`; `tests/evaluation/test_metric_inputs.py`; `evals/fixtures/evaluation_harness/stage_evidence/universe_stage_metric_evidence_set.json`.
- Modified paths: `src/dynamic_ai_products/evaluation/metrics.py`; `tests/evaluation/test_metrics.py`; `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 520, manifest 361.
- Stop point: stage-evidence discrimination; single stamped `MetricInputSnapshot`; extraction stages create no stage-evidence artifact.

### Slice 12J — Metric report v0.2
- Objective: `metric_report@0.2.0` with the top-level metric-family applicability ledger; frozen v0.1 historical model + reader.
- Governing: SPEC-020, ADR-024. Depends on 12I.
- New paths: `tests/evaluation/test_metric_report_v2.py`.
- Modified paths: `src/dynamic_ai_products/evaluation/metrics.py`; `tests/evaluation/test_metrics.py`; `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 524, manifest 362.
- Stop point: v0.1 hash `d9e3f6d7…` preserved; inapplicable family carries a ledger entry and no `MetricDatum`.

### Slice 12K — Gate applicability
- Objective: `GateApplicabilityBindingError` in `gates.py`; a gate targeting an inapplicable metric family is a binding error before datum selection.
- Governing: SPEC-020, ADR-024. Depends on 12J.
- New paths: none.
- Modified paths: `src/dynamic_ai_products/evaluation/gates.py`; `tests/evaluation/test_gates.py`; `src/dynamic_ai_products/evaluation/__init__.py`. Exports 525, manifest 362.
- Stop point: inapplicable-family gate raises before selection; never pass/fail/zero/indeterminate.

### Slice 12L — Evaluation output manifest
- Objective: `evaluation_output_manifest@0.1.0` binding read-back persisted-byte hashes of every derived artifact; inapplicable hashes omitted (never explicit null).
- Governing: SPEC-022, SPEC-024, ADR-024, ADR-025. Depends on 12B, 12I, 12J, 12K.
- New paths: `src/dynamic_ai_products/evaluation/output_manifest.py`; `tests/evaluation/test_output_manifest.py`.
- Modified paths: `src/dynamic_ai_products/evaluation/__init__.py`; `REPO_MANIFEST.md`. Exports 531, manifest 364.
- Stop point: manifest binds only persisted read-back hashes; omission semantics honored.

### Slice 12M — Semantic-substrate integration proof (pre-runner)
- Objective: a pre-runner integration test that drives a dedicated coherent `capability_extraction` fixture bundle through public production APIs to construct, persist, reload, and hash-verify parsed content, resolved assertion evaluations/outcomes, validation snapshot set, validator findings + coverage, metric-input snapshot, metric report, and evaluation-output manifest. No prebuilt-internal-snapshot shortcut, no dummy/blanket observation, no inferred gold, no provider call, and no runner orchestration. Must not create or modify `runner.py`, `report.py`, or `test_runner.py`.
- Governing: SPEC-020, SPEC-022, SPEC-023, ADR-024, ADR-025. Depends on 12A, 12B, 12D, 12E, 12F, 12G, 12H, 12I, 12J, 12K, 12L.
- New paths: `tests/evaluation/test_semantic_substrate_integration.py`; `evals/fixtures/evaluation_harness/substrate_integration/capability_case.json`; `evals/fixtures/evaluation_harness/substrate_integration/case_set_manifest.json`; `evals/fixtures/evaluation_harness/substrate_integration/target_registry.json`; `evals/fixtures/evaluation_harness/substrate_integration/scoring_gate_config.json`; `evals/fixtures/evaluation_harness/substrate_integration/prediction_run_manifest.json`; `evals/fixtures/evaluation_harness/substrate_integration/prediction_envelopes.jsonl`; `evals/fixtures/evaluation_harness/substrate_integration/prediction_source.json`; `evals/fixtures/evaluation_harness/substrate_integration/source_documents.jsonl`; `evals/fixtures/evaluation_harness/substrate_integration/source_passages.jsonl`; `evals/fixtures/evaluation_harness/substrate_integration/source_passage_snapshot_manifest.json`; `evals/fixtures/evaluation_harness/substrate_integration/gold_assertion_set.json`; `evals/fixtures/evaluation_harness/substrate_integration/axis_taxonomy.json`; `evals/fixtures/evaluation_harness/substrate_integration/stage_profile_registry.json`; `evals/fixtures/evaluation_harness/substrate_integration/semantic_adapter_registry.json`; `evals/fixtures/evaluation_harness/substrate_integration/validator_rule_parameters.json`; `evals/fixtures/evaluation_harness/substrate_integration/validator_bundle_artifact.json`.
- Modified paths: `REPO_MANIFEST.md`. Exports 531, manifest 381.
- Reconciliation invariants: loaded target-registry SHA equals the run-manifest registry hash and the integration case-set's registry snapshot hash; case-set snapshot hash equals the run-manifest case-set hash; membership input-packet hash equals the prediction-envelope input-packet hash; parsed raw-artifact hash equals the prediction-source byte hash; source/passage aggregate hash equals the run-manifest source/passage hash; each complete per-rule parameter hash equals its bundle rule hash and the aggregate/bundle hashes equal their run-manifest pins; extraction-stage stage-evidence fields are absent; output-manifest hashes are read-back persisted byte hashes.
- Stop point: the full producer chain yields a real `MetricReport` and `EvaluationOutputManifest` over the coherent bundle through public APIs only; unrelated committed fixtures remain byte-identical.

### Slice P1 — Adjudication decision set and parsed-content preparation boundary

- Objective: own the adjudication layer the binding producer consumes.
  `evaluation/resolution_decisions.py` becomes the canonical owner of
  `EXTRACTION_EVALUATION_STAGES`, `ObservationTargetResolutionProvenance`, and
  `ObservationTargetResolutionDecision`, and adds
  `observation_target_resolution_decision_set@0.1.0` — a run-external,
  hash-bound artifact with strict model, fail-closed revalidation, canonical
  write-once persistence, and a loader. `prediction_content` gains the public
  preparation boundary `parsed_prediction_content_artifact_bytes` /
  `parsed_prediction_content_artifact_sha256`, sharing one private byte producer
  with the persister so an adjudicator can pin a decision set to one exact parse
  before any run directory exists. `observation_target_binding` imports and
  re-exports the moved names and accepts the loaded set as a channel mutually
  exclusive with its `resolution_entries` tuple.
- Governing: ADR-026, ADR-027.
- Existing files modified: `evaluation/prediction_content.py`,
  `evaluation/observation_target_binding.py`, `evaluation/__init__.py`,
  `tests/evaluation/test_prediction_content.py`,
  `tests/evaluation/test_observation_target_binding.py`, the two count
  assertions, `REPO_MANIFEST.md`, `docs/DECISION_LOG.md` (ADR-027), and this
  build plan.
- New files: `evaluation/resolution_decisions.py`,
  `tests/evaluation/test_resolution_decisions.py`.
- Preserved: `parsed_prediction_content@0.1.0`
  (`ffeae7ab54fa03948f4498a3ceb5a634b17444791fd91f94a57c086afedbda3e`),
  `observation_target_binding@0.1.0`
  (`f3ec0e0f2db9185333c667a6d7a52bf64a3b2a21b65bf1cbd90fa582ed67acd2`), the
  existing persist/load byte behaviour, and the tuple-based binding API.
- Stop point: helper SHA equals the persisted and re-read artifact SHA; the
  single-stage `exclude_unset` shortcut is proven to drift and is rejected;
  re-export identity and both import orders hold; no fixture added.

### Slice P2 — Deterministic validator observation/coverage producer

- Objective: a pure public producer for Rules 1–11 `ValidatorObservation`
  values and their `ValidatorRuleCoverage`, derived from parsed content,
  resolved sources, rule parameters, and (at an extraction stage) the binding.
  No persisted artifact of its own: the output is embedded in the persisted
  `ValidationArtifactSnapshotSet`, which `evaluation_output_manifest@0.2.0`
  already hash-binds. Rule 12 stays where it is.
- Governing: SPEC-023, ADR-024, ADR-027.
- Deferred/forbidden: a separate persisted observation-set artifact would
  require a new output-manifest version; adding fields to v0.2 is forbidden.

### Slice P3 — Deterministic axis-record producer

- Objective: a pure public producer for `AxisEvaluationRecord` values from
  parsed content, bound gold, the axis taxonomy, resolved sources, and (at an
  extraction stage) the binding, which is what makes an observation-shaped
  prediction comparable to canonical axis labels. Output is embedded in the
  persisted `MetricInputSnapshot`; no separate persisted artifact.
- Governing: SPEC-020, ADR-024, ADR-026, ADR-027.

### Slice 13 — Canonical runner / CLI orchestration

- Objective: `python -m dynamic_ai_products.evaluation.runner` (Typer,
  following `validation.py`): load the governed inputs → resolve
  references/config → normalize predictions → evaluate assertions →
  validators → metrics → gates → persist an immutable run under the required
  `--eval-root`; machine- and human-readable reports. **First scope is a
  single-case runner** (ADR-027): the case set must hold exactly one
  membership entry, the prediction manifest exactly one envelope, and the
  envelope must match exactly one case on `(input_packet_hash, stage)`.
  Multi-case / package-case orchestration is Slice 13B.
- Governing: SPEC-020, SPEC-024; ADR-024, ADR-025, ADR-026, ADR-027.
- Existing files modified: `evaluation/gates.py` (run-manifest v0.1|v0.2
  dispatch across the build/persist/load path, per ADR-027 — the projection,
  `EvaluationResultV2`, and `evaluation_result.v2.schema.json` are unchanged),
  `evaluation/__init__.py` (exports), `REPO_MANIFEST.md`, and the two
  export/manifest count assertions in `tests/evaluation/test_output_manifest.py`
  and `tests/evaluation/test_metric_report_v2.py`. No other shared file changes;
  `assertions.py` in particular is unchanged.
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
