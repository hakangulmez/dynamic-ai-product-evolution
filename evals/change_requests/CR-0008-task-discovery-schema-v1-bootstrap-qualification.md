# CR-0008 — Bootstrap qualification for `task_discovery_schema_v1`

## Status

In review

## Scope note — this introduces a prompt, and edits none

This change request adds one new frozen prompt,
`prompts/extraction/task_discovery_schema_v1.md`, whose digest is
`1f484896a4e51935d45e5c8c4c575e48da1ed191305c066cb55f69255ea445c0` (9524 bytes).

It modifies **no existing prompt bytes**. `task_discovery_recall.md` is unchanged
(`7147faeda5f77d3807eb59cdee6663bd5599e358ce30df235d22a4b495f350ec`, 1663 bytes) and stays
registered, at position two: no chain has ever resolved it, but a frozen prompt is never deleted.
`task_consolidation_precision.md` is unchanged
(`93346d8827f9d66aed52dfa43a3ba0bdb850a555d56e8cbddce88ac42b9d2846`, 1238 bytes) and stays at
position three; it is not executed by a single pass and this change does not touch that. Every
product and capability prompt is untouched. CR-0001 through CR-0007 are untouched.

## Stage

`task_extraction`, first pass only: `task_discovery_schema_v1`. Stage context is `SPEC-010`. The
**governing policy** for the qualification record itself is `SPEC-024`, not SPEC-010.

## Observed gap

The existing task prompt has never been executed and, measured against the released schema, could
not have produced a conforming record.

`task_observation_v2.schema.json` (`task_observation@0.2.0`, the successor ADR-068 already validates
task candidates against, for `normalized_task`) is `additionalProperties: false` and requires eleven
fields: `task_observation_id`, `company_id`, `observation_cutoff`, `product_observation_id`,
`capability_observation_ids`, `task`, `normalized_task`, `customer_need`, `availability_status`,
`evidence`, `confidence`. Measured on `prompts/extraction/task_discovery_recall.md`:

- **eight of eleven required fields are never named** — only `task`, `evidence` and `confidence`
  appear; `task_observation_id`, `company_id`, `observation_cutoff`, `product_observation_id`,
  `capability_observation_ids`, `normalized_task`, `customer_need` and `availability_status` do not;
- **no output format** — no JSON array, no field list, no fencing rule;
- **no closed status vocabulary** and **no evidence format**;
- it instructs the model to emit "product and capability IDs" directly — the exact
  opaque-identifier-transcription defect ADR-055, ADR-060 and ADR-064 already closed for the other
  two stages, reopened here because this prompt predates the `C0N`/`P0N` reference design entirely: a
  repository-wide grep for either label family returns zero hits inside it.

Unlike the capability stage's CR-0005 predecessor, this prompt is not placeholder-empty — it already
uses all four placeholders `task_discovery_recall` declares (`{{company}}`, `{{cutoff}}`,
`{{product}}`, `{{capabilities}}`), and the renderer already binds them (ADR-068, E-T1). The defect is
narrower and, on the required-field count, more severe: more of the schema's required output is
simply never named.

## General failure class

A prompt whose declared output contract is not the released schema the run validates against —
CR-0005's class, one stage on. Here compounded by a prompt authored before the reference-label design
existed for any stage, so it asks for exactly what that design exists to avoid: raw identifiers,
copied by hand.

## Failing case IDs

None. No evaluation case exists for this class and the task stage has never been executed. The defect
is demonstrated offline: the prompt names three of eleven required fields, and a document in the shape
it implies cannot validate against the released schema.

## Expected behaviour

The successor states the output contract explicitly and asks the model for exactly what it can judge,
never for a value the pipeline can derive or already knows:

- **the capability by short label, plural.** `capability_refs` carries one or more `C0N` labels from
  the `{{capabilities}}` block ADR-068 renders. `capability_observation_ids` is resolved downstream
  by `resolve_capability_refs`, never transcribed. Unlike the capability stage's `parent_ref`, no
  product label is requested at all: task discovery renders one product per call
  (`focal_product_observation_id`), so the pipeline already knows `product_observation_id` before the
  call is made and injects it directly.
- **evidence by short label.** `{"ref": "P0N", "quote": ...}`, the same mechanism ADR-055
  established, resolved through the same `canonical_passage_order` every stage shares. The quote is
  bounded to **one to three sentences**, ADR-065's rule for the capability stage, applied from this
  prompt's first version rather than added after a predecessor without the bound existed.
- **status by short label.** `S1`…`S8` from the same table the capability stage uses — one closed
  vocabulary, not a second one minted for tasks, matching the S1-S8 reuse this change request was
  reviewed against.
- **`C0N` unpadded from this prompt's first version, not after a measured failure.** ADR-064 found
  the capability stage's `P0N` padding defect on two independent live turns: shown `P025`, the model
  wrote `P25`. Every product's capability count passes through the single-digit range that failure
  lived in, so a padded `C0N` would carry that same risk on every one of the nine task-discovery
  calls this chain supports, not on an occasional one. `capability_ref_label` and
  `CAPABILITY_REF_PATTERN` move to the unpadded form in the same change (ADR-069), and this prompt is
  written to describe the label its stage has always rendered.
- **no identifier of any kind, and no role.** `task_observation_id`, `product_observation_id`,
  `capability_observation_ids` and `normalized_task` are derived downstream; `task_role` is decided by
  a later consolidation pass. A candidate carrying any of the five is rejected.

`target_customer`, `monetization_model`, `task_components` and `ai_action_observed` are requested as
**optional** fields, on the evidence-supported-or-omitted rule already established for the capability
stage's `input_types`/`output_types`. The released schema does not require them, and the schema is the
contract.

`schemas/task_observation_v2.schema.json` is **not** modified.

## Proposed bounded change

Add the successor prompt, move it to position one of the `task_extraction` sequence, and move the
prompt registry from `extraction_prompt_registry_v7` to `v8`. The known-version set introduced by
ADR-053 absorbs it with no governance-validator change.

`STAGE_OBSERVATION_KIND["task_extraction"]` and `STAGE_CHANGE_REQUEST["task_extraction"]` (this
document) are added for the first time — deliberately withheld until now, per ADR-061 and ADR-062, for
exactly the reason those two records exist: adding either before a qualified prompt existed would have
made a live task run reachable through `task_discovery_recall`, which cannot produce a conforming
record.

`STAGE_OUTPUT_CONTRACT_ID["task_extraction"]` and `STAGE_OUTPUT_SCHEMA["task_extraction"]` move to the
`@0.2.0` successor, matching what the candidate-collection layer has validated against since ADR-068.

`prompt_qualification_record@0.1.0` keeps its identity, version and property set; its `prompt_id` and
`prompt_registry_version` enums gain the new values additively.

## Qualification basis — pre-evaluation, and stated as such

No completed evaluation run exists in this repository. This record is issued on basis
`bootstrap_pre_evaluation`, with status `bootstrap_authorized_live_dev`, scope
`qualified_for_development`, and lifecycle state `candidate`. It carries no `review_decision` and no
`supporting_evaluation_references`, and it declares in closed vocabulary that it is not an evaluation
verdict, not an acceptance decision, not a release qualification, and not a complete-universe finding.

That basis can authorize only the `live_dev` rollout state.

## Known limitations

- `single_pass_recall_only_not_consolidated` — the run executes pass 1 of 2. `task_consolidation_
  precision` is registered and untouched by this change.
- `sec_only_partial_corpus` — SEC filing text only.
- `single_firm_single_observation_year` — one firm, one observation cutoff.
- `no_completed_evaluation_run` — this prompt has never been executed against a model. Nothing here
  establishes that it elicits conforming output; what is established is that the shape it asks for
  can conform, which the predecessor's could not.
- `no_baseline_comparison` — the predecessor was never executed to any result, so there is nothing to
  compare against.

**Task recall is bounded by Snapshot B, one product removed.** A task performed through a capability a
human rejected cannot be found, by construction — Snapshot A bounds capability recall the same way,
one level up, and this is the same limitation one stage on. Of the eleven products in the persisted
HubSpot chain, nine carry at least one accepted capability and support a task run; Breeze Agents and
Breeze Copilot do not (G6-D), so this prompt's coverage on that chain is nine products, not eleven,
until a richer capability source changes that.

**The evidence a task run will actually see is concentrated in one passage, measured rather than
assumed.** Of the 69 accepted capabilities in the persisted chain, all 70 of their evidence citations
resolve to only two distinct (`source_id`, `passage_id`) pairs, and 69 of the 70 land on the same one —
the "Our Customer Platform" section, which names every Hub and Breeze product in a single paragraph.
`{{capabilities}}` folds each capability's own evidence into its section (ADR-068), so a task run's
`SOURCE PASSAGES` block is, for nearly every product, this one ~6,000-character passage repeated. This
is not a defect this prompt introduces — it inherits the capability stage's own evidence base exactly
as coverage does — but it is why the one-to-three-sentence quote bound above is load-bearing here in a
way it was only precautionary for CR-0007: without it, a task's evidence is a large passage the model
has every incentive to quote in full.

**The prompt-to-vocabulary binding is checked offline only**, as recorded for CR-0002 through CR-0007.

## Risks and trade-offs

Attribution is the new failure surface, one level deeper than the capability stage's. A task wrongly
attributed to a capability it does not depend on would be structurally valid — a real `C0N`, a real
`P0N`, a conforming record — and only review would catch it within the focal product. Cross-product
attribution is structurally prevented rather than merely discouraged: task discovery renders one
product's capabilities per call, so the model is never shown a second product's `C0N` and cannot cite
one. C9 and C10 (ADR-068) close the corresponding gate offline: C9 refuses a capability no human
validated, and C10 — unreachable today, and asserted anyway — refuses a capability belonging to another
product, on the ADR-053/058/061/062/064 lesson that "impossible by construction" has gone false before.

Requesting `target_customer`/`monetization_model`/`task_components`/`ai_action_observed` as optional
accepts that they will often be absent. The alternative — requiring them — was rejected for the same
reason CR-0005 rejected it for `input_types`/`output_types`: a model asked for a field it cannot
support from evidence will supply one anyway.

## Acceptance criteria

- the prompt uses all four bound placeholders (`company`, `cutoff`, `product`, `capabilities`), the
  set `task_discovery_recall` already declared and the renderer already binds;
- the four labelled partition lists are present and the B4 offline binding holds against the
  vocabulary artifact;
- the status label table matches `status_label_table()` exactly;
- the prompt asks for no identifier field and no `task_role`;
- the evidence section states the one-to-three-sentence bound and the contiguity rule;
- `C0N` is described unpadded, with no "at least N digits" instruction;
- the predecessor prompts' bytes are unchanged;
- no released contract, schema, or property set is modified;
- the full test suite passes.

## Evaluation results

None. See *Qualification basis* above.

## Fixed cases

None.

## New regressions

None. The product and capability stages' rendering, prompts, change requests and qualification
records are unchanged.

## Decision

**Not applicable at this revision.** A review decision presupposes a completed, valid evaluation
(`evals/CHANGE_CONTROL_PROTOCOL.md`). None exists, so no value from `accept_candidate |
accept_with_documented_nonblocking_tradeoff | revise | reject` may be recorded here, and the
qualification record issued against this change request carries no `review_decision` property.

## Approval

Recorded in the `prompt_qualification_record` issued against this change request: `reviewer`,
`decided_at`, `code_commit`, and the prompt artifact digest above. This document is pinned by that
record by reference and SHA-256; it is not itself an approval.
