# CR-0001 — Bootstrap qualification for `product_discovery_recall`

## Status

In review

## Scope note — this is not a prompt edit

This change request modifies **no prompt bytes**. `prompts/extraction/product_discovery_recall.md`
is unchanged and stays unchanged; its digest is
`260c3cf4318d5f7d50465cae4342c2ff4e340d1faaca60218bcde0e9694dee6e` (1450 bytes).

It exists because `evals/CHANGE_CONTROL_PROTOCOL.md` and SPEC-024 require a tracked, reviewable
document behind any qualification-registry entry, and because a `prompt_qualification_record`
carries no free-text property. The prose that a reviewer needs lives here and is pinned into that
record by reference and SHA-256, rather than being embedded in a governance artifact where it would
become an unbounded channel into an authorization chain.

## Stage

`product_extraction`, first pass only: `product_discovery_recall`. Stage context is `SPEC-008`
(`31d2a8d49bae58ec3f9d1820867c07edf473e9565f7f38f840f26382ed555a83`). The **governing policy** for
the qualification record itself is `SPEC-024`, not SPEC-008; SPEC-008 is cited here as stage context
and must not be recorded as the qualification-governing spec.

## Observed gap

`adapter_enablement_record@0.1.0` has always required `prompt_qualification_reference` and
`prompt_qualification_sha256`, and SPEC-027 places the SPEC-024 reference there rather than on the
live-call authorization. Nothing loaded the artifact those fields name. The governance walk checked
only their shape — a non-blank string and sixty-four hex characters — so every existing fixture
satisfied it with a digest of `3` repeated sixty-four times naming a file that does not exist.

Consequently the prompt's own digest chain (`load_prompt` → `provider_request_digest`) and the
governance chain were two disconnected hash trees. Editing the frozen prompt broke neither, so
requalification could not be forced by the run path.

## General failure class

A required governance pin that is shape-checked but never resolved. The class is not specific to
prompts: any `*_reference` / `*_sha256` pair that no loader opens asserts nothing, while reading in
review as though it does.

## Failing case IDs

None. No evaluation case exists for this class, and no evaluation partition has been executed. The
defect is in the run path's governance binding, not in prompt output, so it is demonstrated by
offline binding tests rather than by an evaluation case.

## Expected behaviour

A provider-backed two-operation run refuses, before any filesystem effect or network activity,
unless the enablement-pinned prompt qualification record resolves, hash-verifies, and agrees with:
the resolved prompt's exact bytes, id and registry version; this run's stage and released
stage-output schema digest; the execution contract the adapter qualification accepted and the client
contract about to execute; the routing contract the enablement declares; the code commit; and a
decision instant that does not postdate the run.

## Proposed bounded change

Introduce `prompt_qualification_record@0.1.0` and bind it in the v2 route only. No released contract
is modified: the enablement schema already carries the pin, and `live_call_authorization@0.2.0`
deliberately gains no prompt property, because SPEC-027 places the reference on enablement and the
authorization property set is closed.

## Qualification basis — pre-evaluation, and stated as such

No completed evaluation run exists in this repository. `evals/cases/*` and `evals/expected/` contain
no cases, and no `evaluation_run_manifest` artifact has ever been produced.

`evals/CHANGE_CONTROL_PROTOCOL.md` states that a review decision presupposes a completed, valid
evaluation. A pre-evaluation record therefore may not carry a review decision at all — not even a
neutral one — and may not claim acceptance or release qualification.

The record for this CR is issued on basis `bootstrap_pre_evaluation`, with status
`bootstrap_authorized_live_dev`, scope `qualified_for_development`, and lifecycle state `candidate`.
It carries no `review_decision` and no `supporting_evaluation_references`, and it declares in closed
vocabulary that it is not an evaluation verdict, not an acceptance decision, not a release
qualification, and not a complete-universe finding.

That basis can authorize only the `live_dev` rollout state. Pilot and release are unreachable
through it.

## Known limitations

- `single_pass_recall_only_not_consolidated` — the run executes pass 1 of 2. The output is a
  recall-oriented candidate set, not a consolidated product universe.
- `sec_only_partial_corpus` — SEC filing text only; official documentation, IR materials and
  archived product pages are out of corpus for this observation.
- `single_firm_single_observation_year` — one firm, one observation cutoff.
- `no_completed_evaluation_run` — no evaluation has been executed against this prompt.
- `no_baseline_comparison` — no baseline exists, so no candidate-versus-accepted comparison is
  possible.

## Risks and trade-offs

Binding the prompt digest into the authorization chain means any future edit to the frozen prompt
breaks every run that pins this record. That is the intended cost: it converts requalification from
a documented expectation into a run-path refusal.

The record is issued before any evaluation, which is a real weakness. It is bounded by the basis
vocabulary rather than hidden: a `bootstrap_pre_evaluation` record cannot be mistaken for an
evaluated one, cannot claim a review decision, and cannot authorize anything beyond `live_dev`.

## Acceptance criteria

- the offline binding tests pass, including the refusal routes;
- a refusal occurs before the run root is created, leaving zero artifacts;
- the run permit is revoked on every new refusal route;
- no released contract, schema, or property set is modified;
- the frozen prompt's bytes are unchanged.

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
here, and the qualification record issued against this CR carries no `review_decision` property.

A decision becomes recordable when an evaluated successor record is issued on basis
`evaluated_comparison`, which additionally requires the evaluation-artifact root that no runtime
injects or hash-verifies yet.

## Approval

Recorded in the `prompt_qualification_record` issued against this change request: `reviewer`,
`decided_at`, `code_commit`, and the prompt artifact digest above. This document is pinned by that
record by reference and SHA-256; it is not itself an approval.
