# CR-0003 — Bootstrap qualification for `product_discovery_schema_v3`

## Status

In review

## Scope note — this introduces a prompt, and edits none

This change request adds one new frozen prompt,
`prompts/extraction/product_discovery_schema_v3.md`, whose digest is
`b03329d224c5dfa899947f987ee32f026a06f4cbaee33048e324912b67bf4680` (4234 bytes).

It modifies **no existing prompt bytes**. `product_discovery_schema_v2.md` is unchanged
(`1730142fe84fda484867a2ec414ec9932c70724d9a14e03d7c802a81396105ba`, 3195 bytes) and
`product_discovery_recall.md` is unchanged
(`260c3cf4318d5f7d50465cae4342c2ff4e340d1faaca60218bcde0e9694dee6e`, 1450 bytes). Both stay
registered so that `ext-smoke-0002`, `ext-smoke-0003` and `ext-smoke-0004` remain verifiable.
CR-0001 and CR-0002 are untouched.

## Stage

`product_extraction`, first pass only: `product_discovery_schema_v3`. Stage context is `SPEC-008`
(`31d2a8d49bae58ec3f9d1820867c07edf473e9565f7f38f840f26382ed555a83`). The **governing policy** for
the qualification record itself is `SPEC-024`, not SPEC-008.

## Observed gap

A model asked to transcribe a long opaque identifier does not do it reliably, and this was measured
rather than assumed.

Two independent live calls under `product_discovery_schema_v2` (`ext-smoke-0003` and
`ext-smoke-0004`) produced nineteen schema-valid candidates each. In both, the same candidate cited
the same corrupted `passage_id`: the true value `04917fd59df6da2499d38ea749a2c819` came back as
`04917fd59df6da249982a2c819` — first eighteen characters correct, last six correct, the eight
middle characters `d38ea749` collapsed to `82`. The other three citations on that same candidate
were correct.

The rendered document was read back from `inputs/rendered_provider_contents.md` and shown the
model the correct value, so this is not a renderer defect. It is a reproducible transcription
failure on a 32-character hex string, and `source_id` is 49 characters of the same material.

Under the C6 conformance gate a citation that resolves to nothing refuses the whole
materialization, correctly. So one unreliable copy operation blocked every candidate in the run,
including the eighteen whose evidence was sound.

## General failure class

Asking a model for a value that can be derived instead. The class already has two precedents in
this repository: `candidate_id` has never been requested, and ADR-054 moved `company_id`,
`normalized_name` and `product_observation_id` from requested to derived for exactly this reason.
Long opaque identifiers are the same problem in a different place.

## Failing case IDs

None. No evaluation case exists for this class and no evaluation partition has been executed. The
defect is demonstrated by two archived live runs and by offline resolution tests.

## Expected behaviour

Each rendered passage carries a short positional label in its header
(`[ref: P001] [passage_id: ...] [source_id: ...] [publication_date: ...]`). The prompt asks for
`evidence` entries of exactly `{"ref": ..., "quote": ...}` and forbids emitting `source_id` or
`passage_id` at all. Downstream, each `ref` is resolved to the real identity pair before schema
validation, so a conforming observation still carries `{source_id, passage_id, quote}`.

`schemas/product_observation.schema.json` is **not** modified.

## Proposed bounded change

Add the successor prompt, move it to position one of the `product_extraction` sequence, and move
the prompt registry from `extraction_prompt_registry_v2` to `extraction_prompt_registry_v3`. The
registry-version set introduced by ADR-053 already recognises historical versions, so no governance
validator changes.

Introduce one shared ordering function used by both the renderer and the resolver, so a label
cannot mean one passage when it is shown and another when it is read back.

`prompt_qualification_record@0.1.0` keeps its identity, version and property set. Its `prompt_id`
`enum` mirrors the prompt registry and gains the successor id; that edit is additive and every
previously admissible id remains admissible.

## Qualification basis — pre-evaluation, and stated as such

No completed evaluation run exists in this repository. This record is issued on basis
`bootstrap_pre_evaluation`, with status `bootstrap_authorized_live_dev`, scope
`qualified_for_development`, and lifecycle state `candidate`. It carries no `review_decision` and no
`supporting_evaluation_references`, and it declares in closed vocabulary that it is not an
evaluation verdict, not an acceptance decision, not a release qualification, and not a
complete-universe finding.

That basis can authorize only the `live_dev` rollout state.

## Known limitations

- `single_pass_recall_only_not_consolidated` — the run executes pass 1 of 4. The output is a
  recall-oriented candidate set, not a consolidated product universe.
- `sec_only_partial_corpus` — SEC filing text only.
- `single_firm_single_observation_year` — one firm, one observation cutoff.
- `no_completed_evaluation_run` — no evaluation has been executed against this prompt. Whether a
  short label is copied more reliably than a long hex string is **untested against a model**; the
  two archived failures establish that the long form is unreliable, not that the short form is
  reliable.
- `no_baseline_comparison` — no baseline exists, so no candidate-versus-accepted comparison is
  possible.

**The prompt-to-vocabulary binding is checked offline only**, exactly as recorded for CR-0002: B4
is a pure function and a test, E4 is deferred with the authorization successor, and the governance
chain issued against this change request does not re-check the binding at call time.

**A label names a position, not a passage.** If the packet changes, the same label means a
different passage. That is safe only because a label is resolved against the packet the run was
built from, in the same process, through the same ordering function that rendered it — a label is
never carried across runs and never stored as an identity. The resolved artifact stores the real
pair, not the label.

## Risks and trade-offs

The failure mode this replaces was loud: a bad identifier resolved to nothing and C6 refused. The
failure mode it could introduce is quiet: a label that resolves to the *wrong* passage would look
valid. That risk is closed structurally rather than by review — `canonical_passage_order` is the
only place the order is decided, and both the renderer and the resolver call it. Measured on the
pilot packet, the packet's own list order differs from the canonical order at 121 of 124 positions,
so an implementation that indexed the packet list would have mis-attributed almost every quote.

Out-of-range or malformed labels are refused with their own reason code
(`candidate_conformance_evidence_ref_unresolvable`) rather than folded into the existing
unknown-pair code, because "invented an identifier" and "named a position it was not shown" are
different faults.

## Acceptance criteria

- the renderer emits one `[ref: ...]` header per passage, in canonical order, with `passage_id` and
  `source_id` retained for human readers;
- the resolver and the renderer derive their order from the same function;
- a resolved observation validates against the unchanged `product_observation` schema;
- a malformed or out-of-range label is refused with its own reason code and writes nothing;
- the predecessor prompts' bytes are unchanged;
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
