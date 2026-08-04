# CR-0002 — Bootstrap qualification for `product_discovery_schema_v2`

## Status

In review

## Scope note — this introduces a prompt, and edits none

This change request adds one new frozen prompt,
`prompts/extraction/product_discovery_schema_v2.md`, whose digest is
`1730142fe84fda484867a2ec414ec9932c70724d9a14e03d7c802a81396105ba` (3195 bytes).

It modifies **no existing prompt bytes**. `prompts/extraction/product_discovery_recall.md` is
unchanged and stays unchanged; its digest remains
`260c3cf4318d5f7d50465cae4342c2ff4e340d1faaca60218bcde0e9694dee6e` (1450 bytes). That prompt stays
registered, because `ext-smoke-0002` resolved it and removing it would make that chain
unverifiable. What changes is which prompt a single pass executes.

As with CR-0001, this document exists because `evals/CHANGE_CONTROL_PROTOCOL.md` and SPEC-024
require a tracked, reviewable document behind any qualification-registry entry, and because a
`prompt_qualification_record` carries no free-text property.

## Stage

`product_extraction`, first pass only: `product_discovery_schema_v2`. Stage context is `SPEC-008`
(`31d2a8d49bae58ec3f9d1820867c07edf473e9565f7f38f840f26382ed555a83`). The **governing policy** for
the qualification record itself is `SPEC-024`, not SPEC-008.

## Observed gap

Two defects in the predecessor prompt, both established offline rather than by inference.

**1. The declared output shape cannot validate.** `schemas/product_observation.schema.json` is
`additionalProperties: false` and declares no `candidate_status` property. The predecessor prompt
asks for that field, so a conforming model response cannot validate against the released stage
output schema. A live call under that prompt would have produced output that the run's own schema
check must reject.

**2. `availability_status` was unconstrained in both directions.** The schema types it as a bare
string, and the predecessor prompt named no closed vocabulary, so any word at all could arrive and
be structurally valid. Candidate admission had no vocabulary to check against.

## General failure class

A prompt whose declared output contract is not the released schema the run validates against. The
class is not specific to this stage: whenever the instruction and the schema are authored
separately, the two can disagree, and the disagreement surfaces only after a paid call.

## Failing case IDs

None. No evaluation case exists for this class and no evaluation partition has been executed. The
defect is demonstrated offline: a hand-written document in the predecessor prompt's declared shape
is refused by `Draft202012Validator` against the released schema, and the successor's declared shape
validates.

## Expected behaviour

A single pass over `product_extraction` resolves `product_discovery_schema_v2`, which asks for
exactly the released schema's required fields, names only optional fields that schema declares, asks
for no `candidate_status`, and constrains `availability_status` to the eight tokens of
`docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`.

The four labelled status lists the prompt carries as literal text must equal, list by list and in
order, the corresponding lists of the `product_candidate_availability_vocabulary@0.1.0` artifact
(ADR-052). The artifact is the authority; the prompt's copy is what the model is shown.

## Proposed bounded change

Add the successor prompt, move it to position one of the `product_extraction` sequence, and move
the prompt registry from `extraction_prompt_registry_v1` to `extraction_prompt_registry_v2`.

Correct one governance-validator rule that the registry move exposed: the prompt-qualification
validator required a record to declare `extraction_prompt_registry_v1` *and*, separately, to equal
the registry version the current build resolved. Those two demands cannot both hold once the
registry moves, so a released validator was silently freezing a registry it does not own. A record
documents the version current when it was minted; the corrected rule checks membership in the
closed, code-owned set of published versions.

`prompt_qualification_record@0.1.0` keeps its identity, its version, and its property set: no
property is added, removed or retyped, and every record that validated before still validates.

One schema-file edit is required and is stated rather than glossed. The record's `prompt_id` is a
closed `enum` that mirrors the prompt registry — the assertion guarding it is named *the prompt-id
vocabulary is the registry and not a second list* — so registering a prompt without extending the
enum would leave the schema unable to describe a record the runtime accepts. The successor id is
added to that enum. The change is additive: every previously admissible id remains admissible, the
contract identity and `schema_version` are unchanged, and the file's digest is pinned by nothing, so
no released artifact's hash chain moves.

## Qualification basis — pre-evaluation, and stated as such

No completed evaluation run exists in this repository. `evals/cases/*` and `evals/expected/` contain
no cases, and no `evaluation_run_manifest` artifact has ever been produced.

`evals/CHANGE_CONTROL_PROTOCOL.md` states that a review decision presupposes a completed, valid
evaluation. This record is therefore issued on basis `bootstrap_pre_evaluation`, with status
`bootstrap_authorized_live_dev`, scope `qualified_for_development`, and lifecycle state `candidate`.
It carries no `review_decision` and no `supporting_evaluation_references`, and it declares in closed
vocabulary that it is not an evaluation verdict, not an acceptance decision, not a release
qualification, and not a complete-universe finding.

That basis can authorize only the `live_dev` rollout state. Pilot and release are unreachable
through it.

## Known limitations

- `single_pass_recall_only_not_consolidated` — the run executes pass 1 of 3. The output is a
  recall-oriented candidate set, not a consolidated product universe.
- `sec_only_partial_corpus` — SEC filing text only; official documentation, IR materials and
  archived product pages are out of corpus for this observation.
- `single_firm_single_observation_year` — one firm, one observation cutoff.
- `no_completed_evaluation_run` — no evaluation has been executed against this prompt. In
  particular, whether the successor's stated output shape actually produces schema-valid model
  output is **untested against a model**; only the shape it asks for has been validated offline.
- `no_baseline_comparison` — no baseline exists, so no candidate-versus-accepted comparison is
  possible. The predecessor was never executed to a schema-valid result, so there is nothing to
  compare against.

**The prompt-to-vocabulary binding is checked offline only, and the governance chain issued against
this change request does not re-check it at call time.** B4 — that the four labelled status lists in
the prompt text equal, list by list and in order, the corresponding lists of the
`product_candidate_availability_vocabulary@0.1.0` artifact — is a pure function and a test. E4, the
same comparison performed again at the run's F0 gate before any provider send, belonged to the
authorization successor that this increment deliberately defers. There is therefore no code path in
the current chain that asks, at the moment of a live call, whether the prompt still agrees with the
vocabulary artifact.

The practical consequence, stated rather than implied: if the prompt text and the artifact drift
apart after this record is issued, the offline test fails but nothing in the governance chain
refuses the call. Until E4 exists, keeping them in agreement is a review obligation, exactly as
`code_commit` freshness and `run_created_at` are. This is not covered by a
`known_limitation_codes` entry, because that vocabulary is closed and is not widened to absorb it.

## Risks and trade-offs

Moving the successor to position one means `single_pass_prompt_plan` resolves it and the predecessor
is no longer reachable as the executed prompt. That is intended: the predecessor asks for a field
the released schema refuses. The predecessor's bytes and registration remain so that
`ext-smoke-0002` stays verifiable — verifiable, not replayable. No replay of that run is promised.

Widening the accepted registry versions from one literal to a closed set is a real loosening, and it
is bounded deliberately: the set is code-owned, contains only versions this code has actually
published, and a record naming anything else is refused. The three bindings that tie a record to the
prompt it qualifies — id, reference, and artifact digest — are unchanged and remain byte-exact.

The vocabulary the prompt carries is a copy of the artifact's. A copy can drift, and the offline
binding check exists for exactly that reason; it is not yet enforced on the live run path, which is
a deliberate limitation of this increment rather than an oversight.

## Acceptance criteria

- the offline binding tests pass, including every refusal route;
- the four labelled prompt lists equal the vocabulary artifact's, list by list and in order;
- a hand-written document in the successor's declared shape validates against the released
  `product_observation` schema, and one carrying `candidate_status` does not;
- the predecessor prompt's bytes are unchanged;
- no released contract, schema, or property set is modified;
- the full test suite passes.

## Evaluation results

None. See *Qualification basis* above.

## Fixed cases

None.

## New regressions

None.

## Decision

**Not applicable at this revision.** A review decision presupposes a completed, valid evaluation
(`evals/CHANGE_CONTROL_PROTOCOL.md`). None exists, so no value from
`accept_candidate | accept_with_documented_nonblocking_tradeoff | revise | reject` may be recorded
here, and the qualification record issued against this change request carries no `review_decision`
property.

## Approval

Recorded in the `prompt_qualification_record` issued against this change request: `reviewer`,
`decided_at`, `code_commit`, and the prompt artifact digest above. This document is pinned by that
record by reference and SHA-256; it is not itself an approval.
