# Prompt Development and Evaluation Protocol

## Purpose

This document defines the only accepted process for changing extraction, matching, classification, measurement, or adjudication prompts in this repository.

The project must not return to an informal cycle of reading a few outputs, changing wording, rerunning selected firms, and deciding by intuition whether the prompt improved. That workflow creates four major scientific risks:

1. **Local overfitting:** a change fixes one visible company but harms other firms or sectors.
2. **Hidden regressions:** a new version appears better because only the corrected examples are inspected.
3. **Specification drift:** prompt wording gradually changes the construct without an explicit methodological decision.
4. **Irreproducibility:** outputs cannot be traced to a stable prompt, schema, source packet, model, and code version.

The accepted workflow is therefore:

```text
Observe a failure
  → classify the failure
  → create or update an evaluation case
  → define the expected behavior
  → verify that the current version fails
  → make one bounded change
  → rerun all relevant evaluations
  → compare with the previous accepted version
  → accept, reject, or revise the change
  → archive the decision and release artifacts
```

The central rule is:

> **No production prompt change without an evaluation case, an explicit expected behavior, and a regression comparison.**

## Scope

This protocol applies to:

- official-source discovery prompts;
- product discovery and product consolidation;
- capability extraction;
- customer-facing task discovery and consolidation;
- task-role classification;
- longitudinal entity resolution;
- task-transition classification;
- frontier replicability assessment;
- AI transformation depth;
- deployment scale;
- task-specific defensibility;
- human-adjudication assistance;
- model-based output criticism.

Pure formatting, spelling, or documentation changes that cannot affect model behavior may be exempted, but the exemption must be obvious and documented in the commit message.

## Separation of roles

### Methodology owner

The human researcher is responsible for:

- defining the construct;
- deciding whether an output is conceptually correct;
- creating and adjudicating gold examples;
- identifying unacceptable failure classes;
- approving rubric and ontology changes;
- deciding whether a trade-off is scientifically acceptable.

### Implementation agent

Claude Code or another coding agent is responsible for:

- implementing the harness;
- loading and validating cases;
- running prompts and parsers;
- computing metrics;
- generating diffs and reports;
- preserving immutable run artifacts;
- building the local review interface;
- adding tests for accepted behavior.

### Evaluation harness

The harness is the binding control layer. It must answer:

- What changed?
- Which cases were fixed?
- Which cases regressed?
- Did precision, recall, evidence validity, duplication, or temporal integrity change?
- Was the change tested on examples not used to design it?
- Can the output be reproduced from archived inputs and versions?

## Evaluation partitions and suites

Case usage membership lives in the versioned case-set manifest, not in case
files or directory paths (ADR-014). Each case holds exactly one evaluation
partition per case-set version (`dev` or `frozen_test`) and zero or more
evaluation suites (`adversarial`, `regression`, `smoke`, `boundary`,
`schema_validation`). Membership changes are versioned events with recorded
provenance; they never mutate an existing case-set snapshot.

### Development partition

The development partition is visible during prompt design. It should contain heterogeneous examples and known edge cases.

Recommended initial size:

- 8–12 firms;
- 20–40 firm-year source packets;
- 100–200 product, capability, or task observations across stages.

The development partition may include familiar cases such as Adobe, Chegg, and ServiceNow, but it must not consist only of famous AI adopters.

### Frozen test partition

The frozen test partition measures generalization. It should include firms, products, wording styles, and industries that were not central to prompt development.

Rules (ADR-015):

- Frozen case-set snapshots are immutable; membership changes exist only as append-only events plus new case-set versions.
- Frozen-test evaluation runs are restricted to predeclared purposes (release-candidate evaluation, baseline establishment, reproducibility check, approved regression diagnosis) and are always logged.
- Any access to frozen-case information is a typed, logged exposure event; case-level detail requires a recorded purpose.
- A case whose prediction or gold detail was inspected during tuning or diagnosis is marked ever-exposed, moves to the development partition in the next case-set version, and is replaced through a separate process; it can never again serve as a blind frozen case.

### Adversarial suite

The adversarial suite contains deliberately difficult or misleading passages. Required classes include:

- generic AI strategy language with no customer-facing action;
- roadmap statements presented as future intentions;
- a feature named “agent” that only drafts or summarizes;
- product renaming with no economic task change;
- suite names incorrectly treated as separately usable products;
- internal R&D incorrectly treated as a customer capability;
- proprietary data claims that do not establish task-specific defensibility;
- current product pages incorrectly used as historical evidence;
- multiple sentences describing the same task;
- one capability supporting several distinct customer outcomes;
- one economic task delivered through multiple channels;
- a broad value proposition that is not an executable task.

### Regression suite

Every accepted correction must become a permanent regression case. Adding a case to the regression suite is a versioned membership event; it does not change the case's partition and does not by itself verify the case (ADR-014). Gate-bearing regression cases must be verified (ADR-013).

Examples:

- “AI-powered personalized learning” was incorrectly extracted as a capability.
- An announced future agent was coded as generally available.
- A task was duplicated because two sources used different wording.
- A product rename was classified as a new product.
- A broad mission statement was extracted as a core task.
- A source quote did not occur in the cited passage.

The regression suite is the project’s accumulated memory of past errors. A failure that has been corrected once should not silently return.

## Evaluation case anatomy

Each case must include, at minimum:

```yaml
case_id:
stage:
stage_context:        # stage-specific typed context (e.g. company, dates)
input_source_ids:
input_passage_ids:
assertions:           # atomic scoring units; the sole scoring contract
failure_tags:
notes:
created_by:
created_at:
guideline_version:
```

Partition and suite membership is not a case field; it lives in the
versioned case-set manifest (ADR-014). Company and observation date are
stage-specific typed context, not universal required fields (ADR-011).

Assertions are the atomic scoring units and the sole scoring contract
(ADR-011): each assertion records a stable assertion ID; one of the kinds
`expected_entity`, `forbidden_entity`, `field_value`, `evidence_provenance`,
or `deterministic_validation`; an assertion semantic version, an assertion
contract hash, or both; explicit target references; and explicit
`scoring_gate_config_references` into the versioned scoring/gate
configuration. Assertion outcomes are run artifacts, not case-definition
fields. The machine-readable contract is
`schemas/evaluation_case.schema.json`.

Where appropriate, an entity referenced by an expected-entity or
forbidden-entity assertion includes:

- stable gold ID;
- accepted aliases;
- parent product or capability;
- availability status;
- evidence references;
- role or transition label;
- explicit fields that must remain unknown;
- forbidden interpretations.

Exact wording is not the primary target. The harness should compare stable entity identities and accepted aliases rather than requiring one sentence formulation.

## Failure taxonomy

All prompt failures must receive one or more standardized tags. Initial taxonomy:

### Source and time

- `wrong_source_type`
- `unofficial_source`
- `publication_date_unknown`
- `temporal_leakage`
- `live_page_used_historically`
- `evidence_quote_missing`
- `source_id_unresolved`
- `passage_id_unresolved`

### Product ontology

- `feature_as_product`
- `bundle_as_product`
- `suite_inflation`
- `product_omission`
- `product_duplicate`
- `rename_as_new_product`
- `roadmap_as_active_product`

### Capability ontology

- `marketing_as_capability`
- `task_as_capability`
- `internal_rd_as_capability`
- `capability_omission`
- `capability_duplicate`
- `unsupported_capability`

### Task ontology

- `mission_as_task`
- `task_too_broad`
- `task_too_narrow`
- `task_duplicate`
- `channel_as_task`
- `internal_task`
- `unsupported_task`
- `customer_need_missing`
- `wrong_parent_capability`
- `role_misclassification`

### Longitudinal matching

- `false_new`
- `false_discontinued`
- `rename_mismatch`
- `split_missed`
- `merge_missed`
- `transformation_misclassified`
- `predecessor_link_wrong`

### Measurement

- `ai_wording_contamination`
- `frontier_date_wrong`
- `unsupported_depth`
- `unsupported_scale`
- `defensibility_by_asset_presence`
- `unknown_should_not_be_scored`
- `benefit_assumed_from_adoption`
- `outcome_leakage`

### Parsing and system behavior

- `schema_invalid`
- `required_field_missing`
- `duplicate_id`
- `silent_repair`
- `run_artifact_overwritten`
- `legacy_contamination`

## Hard gates

The following are release blockers rather than soft quality metrics:

| Gate | Required condition |
|---|---:|
| JSON/schema validity | 100% |
| Referenced source IDs resolve | 100% |
| Referenced passage IDs resolve | 100% |
| Evidence quote is present in cited passage | 100% for accepted factual claims |
| Temporal leakage | 0 critical cases |
| Legacy-field contamination | 0 |
| Silent overwrite of run outputs | 0 |
| Active task supported only by future roadmap evidence | 0 |
| Unknown evidence converted into confident fact | 0 |

A run that fails a hard gate cannot be promoted even if aggregate precision or recall improves.

The unknown-to-confident gate targets wrong or unsupported confidence, not a lower unknown rate. A change that converts UNKNOWN into a confident label is classified as beneficial resolution only when the new label is verified correct; otherwise it is a false-confidence regression or unsupported confidence, and both are blocking (ADR-019).

## Provisional quality thresholds

These thresholds are initial engineering targets and must be revisited after the sentinel gold set is complete:

| Metric | Initial target |
|---|---:|
| Product precision | ≥ 0.95 |
| Product recall | ≥ 0.90 |
| Capability precision | ≥ 0.92 |
| Capability recall | ≥ 0.85 |
| Task precision | ≥ 0.90 |
| Task recall | ≥ 0.85 |
| Evidence validity | ≥ 0.98 |
| Duplicate task rate | ≤ 0.05 |
| Longitudinal transition agreement | ≥ 0.85 |
| Critical temporal errors | 0 |

No single aggregate score should hide a serious failure class. Reports must always include per-stage and per-tag results.

## Prompt change request

Every behavior-changing prompt edit must have a change request under:

```text
evals/change_requests/CR-XXXX-short-title.md
```

A change request contains:

1. observed failure;
2. why it violates the governing definition;
3. affected case IDs;
4. expected behavior;
5. proposed bounded change;
6. risks and likely trade-offs;
7. acceptance criteria;
8. results against the current accepted version;
9. final decision;
10. links to prompt, report, and commit.

The change request should describe a **general failure class**, not a company-specific desired score.

Bad justification:

> Chegg’s replicability is too low, so add a rule that educational Q&A should score high.

Good justification:

> Direct-response informational tasks are being treated as non-replicable whenever the focal firm claims proprietary content, even when the task can be completed without that corpus. Add a task-level counterfactual test and evaluate it across consumer education, writing assistance, and general research cases.

## One-change principle

Whenever possible, a prompt release should address one failure class at a time. Multiple unrelated changes make causal diagnosis impossible.

Allowed exceptions:

- coordinated changes required by a schema version;
- a taxonomy freeze affecting several prompts;
- an emergency fix for a hard-gate failure.

Exceptions must be stated in the change request.

## Required comparison outputs

Every candidate version must produce a comparison with the current accepted version:

```text
Fixed cases
New regressions
Unchanged failures
New failures without prior labels
Metric deltas
Hard-gate results
Results by company archetype
Results by source type
Results by year
Results by failure tag
Unknown-rate change
Evidence-coverage change
```

A version must not be accepted solely because the average score improved.

## Run immutability and versioning

Each run must be written to a new directory:

```text
data/runs/<run_id>/
  run_manifest.json
  input_manifest.json
  source_packet_manifest.json
  raw_model_output.jsonl
  parsed_output.jsonl
  repair_records.jsonl
  deterministic_findings.jsonl
```

Evaluation reports, assertion results, and candidate-versus-accepted diffs
are not extraction-run artifacts. They belong to independent, immutable
evaluation runs and comparison artifacts that reference the prediction run
by ID and hash (ADR-012, ADR-020). The canonical evaluation-run root path
is an open decision.

Required run-manifest fields:

```yaml
run_id:
stage:
code_commit:
spec_version:
schema_version:
schema_hash:
prompt_version:
prompt_hash:
model_provider:
model_label:
model_parameters:
source_manifest_hash:
input_manifest_hash:
started_at:
completed_at:
retry_count:
fallback_model:
```

No run directory may be overwritten. A repair creates a new record or a new run.

### Extraction prompt-hash binding

For Stage 05-07 extraction runs, prompt identity is fixed by digest, not by a
label:

- `prompt_hash` is **SHA-256 over the exact bytes of the resolved prompt
  artifact** used for that run. No normalization, no whitespace folding, and
  no template expansion occurs before hashing.
- **That digest is the prompt identity.** A human-readable version label is
  optional; when used it lives in the extraction prompt registry, **never as
  an in-file edit to a frozen prompt**, preserving the rule in
  `prompts/README.md` that a frozen prompt is superseded by a new version
  rather than edited in place.
- The files under `prompts/extraction/` are not modified in order to acquire
  identity. Only their digest is computed.

### Contract over prose for Stage 05-07 extraction runs

**For Stage 05-07 extraction runs only**, the generic required-field list above
is a planning and protocol superset. The released and binding contract for
those extraction runs is `schemas/extraction_run.schema.json` at version
`0.1.0`, which is strict (`additionalProperties: false`) and carries exactly
fifteen properties: `run_id`, `stage`, `started_at`, `completed_at`, `status`,
`code_commit`, `spec_version`, `schema_hash`, `prompt_hash`,
`source_manifest_hash`, `model_provider`, `model_name`, `model_parameters`,
`fallbacks`, and `error_count`.

It does **not** carry `prompt_version`, `schema_version`, `input_manifest_hash`,
`retry_count`, `fallback_model`, or `model_label`. Where this document and the
schema disagree **for a Stage 05-07 extraction run**, the schema governs. No
increment may widen, rename, or version `extraction_run@0.1.0` in order to
match this prose; doing so would mutate a released contract to satisfy a wish
list. See ADR-033.

This narrowing applies to Stage 05-07 extraction runs and to nothing else. The
generic required run-manifest field list above **remains normative for every
other run type governed by this protocol**, and is not weakened by the
existence of a narrower released contract for one stage block.

## Prompt release states

Prompts use the following lifecycle:

- `draft`: not yet evaluated;
- `candidate`: complete and under evaluation;
- `accepted`: approved for the specified stage and corpus version;
- `frozen`: used for a released dataset version;
- `deprecated`: retained for provenance but not used.

`reject` is a human review decision, not a lifecycle status. A rejected
candidate retains its immutable artifact and review event but does not
transition to any `rejected` lifecycle state (ADR-019).

Acceptance is a qualification bound to prompt artifact × execution/routing contract × stage/output contract; it does not transfer across execution-affecting contract changes, and requalification scope follows the predeclared change-classification policy (ADR-021).

The qualification registry must record at least:

- qualification ID;
- prompt path;
- prompt artifact version/hash;
- execution/routing contract identity/hash;
- stage/output contract identity/hash;
- compatible schema;
- governing spec;
- qualification scope;
- supporting eval/comparison references;
- qualification status;
- decision timestamp;
- supersedes/superseded-by references;
- known limitations.

## Human review protocol

When the model output and gold record disagree, the reviewer chooses one of:

- `prediction_correct`;
- `gold_correct`;
- `both_acceptable`;
- `both_wrong`;
- `ambiguous_source`;
- `ontology_decision_required`;
- `insufficient_evidence`.

Human edits are append-only. The original prediction and original gold record remain unchanged. Human dispositions never modify validator findings and never enter gate arithmetic; resolution requires a new component version and a new evaluation run (ADR-018). Every review records:

- reviewer;
- timestamp;
- decision;
- reason code;
- comment;
- prior and revised values;
- linked case and run IDs.

## Development sequence

Prompt development for a stage follows this order:

1. Freeze the stage definition and output schema.
2. Build deterministic validators.
3. Create a small gold set.
4. Run the initial prompt.
5. Classify failures.
6. Add regression cases.
7. Make bounded changes through change requests.
8. Run development, adversarial, regression, and frozen evaluations.
9. Conduct construct review on difficult cases.
10. Accept one version.
11. Freeze before the production run.

## Prohibited practices

- Changing a prompt because one company’s result “looks wrong” without defining the failure class.
- Inspecting only corrected examples after a change.
- Using financial outcomes to determine the desired extraction or measurement label.
- Adding exceptions that mention specific tickers in production prompts.
- Altering gold labels to make the model appear better without independent adjudication.
- Treating an LLM judge as ground truth.
- Combining data collection, extraction, scoring, and evaluation in a single opaque model call.
- Overwriting old model outputs.
- Promoting a prompt while a hard gate fails.

## Acceptance decision template

A prompt candidate is accepted only when the release record answers:

1. Which general failure class was targeted?
2. Which eval cases were added?
3. Did the old version fail those cases?
4. Which files changed?
5. Which cases were fixed?
6. Which regressions appeared?
7. Were hard gates passed?
8. Did frozen-test performance remain acceptable?
9. Did the construct definition change?
10. Who approved the release?

## Scientific interpretation

The evaluation harness does not prove that the ontology or measurement framework is objectively correct. It ensures that:

- definitions are applied consistently;
- changes are explicit;
- evidence and time constraints are respected;
- known errors do not repeatedly return;
- model behavior generalizes beyond a few visible examples;
- released data can be reproduced and audited.

That is the required foundation before scaling to hundreds of firms and thousands of task-year observations.

## Revision history

- 2026-07-19 — Revised per ADR-011..ADR-022: partition/suite membership model, logged frozen exposure, stage-typed case context, independent evaluation runs, unknown-to-confident refinement, contract-bound qualification and qualification registry, `rejected` removed from the prompt lifecycle.
