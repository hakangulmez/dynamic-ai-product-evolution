# CR-0006 — Bootstrap qualification for `capability_discovery_schema_v2`

## Status

In review

## Scope note — this introduces a prompt, and edits none

This change request adds one new frozen prompt,
`prompts/extraction/capability_discovery_schema_v2.md`, whose digest is
`caf5b3a04bb1fb3c858fea46ada122fd84575735792aa0438a242fc0758dc0c3` (5854 bytes).

It modifies **no existing prompt bytes**. `capability_discovery_schema_v1.md` is unchanged
(`def87e3e973d3790a95f17cfbc749ffdf16d7fb024451b964fdd8212ffcc8bee`, 5776 bytes) and stays
registered at position two, because `ext-smoke-cap-0001` and `ext-smoke-cap-0002` resolved it and
both chains must stay verifiable. `capability_extraction.md` is unchanged and stays at position
three. Every product prompt is untouched — `product_discovery_schema_v4` in particular — so
`ext-smoke-0002` through `ext-smoke-0006` remain verifiable. CR-0001 through CR-0005 are untouched.

## Stage

`capability_extraction`, first pass only: `capability_discovery_schema_v2`. Stage context is
`SPEC-009` (`38e73fbe2b20de603bcf27ca222bd96f22c1da34c3f1ece8264ba3c446739815`). The **governing
policy** for the qualification record itself is `SPEC-024`, not SPEC-009.

## Observed gap

`capability_discovery_schema_v1` tells the model that a passage label is "the letter `P` followed
by at least three digits, for example `"P001"`", and the renderer emitted exactly that. Measured on
two live calls:

- `ext-smoke-cap-0001` (governance round `capability_extraction-0002`) — 81 observations, 81
  evidence citations, **80 correctly padded**, one written `P25` where the rendered label was
  `P025`. Refused with `candidate_conformance_evidence_ref_unresolvable`; no collection written.
- `ext-smoke-cap-0002` (governance round `capability_extraction-0003`) — the model output was
  **byte-identical** to the first run (same SHA-256 over the returned text), same single failure at
  the same observation and the same label.

So this is not a sampling accident that a retry clears. At `temperature=0` the failure is
reproducible, and two governance rounds and two paid calls produced the same refusal.

## General failure class

An output format that requires the model to preserve a presentation detail — here zero padding —
that carries no information. `025` and `25` denote the same position; the padding exists only to
make labels the same width. Asking a model to re-emit a number in a fixed width puts the
instruction in tension with what a model does naturally with a numeral it has read, and the
tension has to be resolved somewhere. It was being resolved by refusing the model's output.

## Failing case IDs

None in the evaluation harness. The evidence is the two live runs above; the collection was refused
both times, so no candidate artifact exists to reference.

## Expected behaviour

The successor is `capability_discovery_schema_v1` with **one section changed**: how a passage label
is described. The label is now the passage's position number with no fixed width and no leading
zeros — `"P1"`, `"P25"`, `"P100"` — and the header example in the input template shows `[ref: P1]`
to match. Nothing else moves: the parent-label rules, the status-label table, the closed
vocabulary, the required and optional field lists, the no-identifier rule and the silent final
check are byte-identical to v1.

The renderer changes with it. `STAGE_PASSAGE_REF_STYLE` (ADR-064) is a closed, fail-closed map from
stage to label style: `product_extraction` keeps `P{:03d}`, `capability_extraction` becomes
`P{:d}`, and a stage that declares no style is refused with `passage_ref_label_style_undeclared`.
The style is per stage rather than global precisely so that `product_discovery_schema_v4` — a
qualified prompt whose digest is pinned in six product qualification records — keeps being rendered
the way its own text describes.

`PASSAGE_REF_PATTERN` widens from `^P(\d{3,})$` to `^P(\d+)$`. Measured on the widening: every
label the old grammar accepted is still accepted and still resolves to the same ordinal, because
`int("025") == int("25") == 25`. No historical citation changes meaning, and the resolver performs
no repair — it reads digits as a number, which it already did.

`schemas/capability_observation.schema.json` is **not** modified. No schema file is modified.

## Proposed bounded change

Add the successor prompt, move it to position one of the `capability_extraction` sequence, and move
the prompt registry from `extraction_prompt_registry_v5` to `v6`. The known-version set introduced
by ADR-053 absorbs it with no governance-validator change.

`STAGE_CHANGE_REQUEST["capability_extraction"]` moves from CR-0005 to this document. That is the
maintenance step ADR-062 recorded as its own known limitation, performed here for the first time:
the map records *which change request is current*, so it must move whenever a stage's prompt is
superseded. `STAGE_CHANGE_REQUEST["product_extraction"]` is untouched.

`prompt_qualification_record@0.1.0` keeps its identity, version and property set; its `prompt_id`
and `prompt_registry_version` enums gain the new values additively.

## Qualification basis — pre-evaluation, and stated as such

No completed evaluation run exists in this repository. This record is issued on basis
`bootstrap_pre_evaluation`, with status `bootstrap_authorized_live_dev`, scope
`qualified_for_development`, and lifecycle state `candidate`. It carries no `review_decision` and no
`supporting_evaluation_references`, and it declares in closed vocabulary that it is not an
evaluation verdict, not an acceptance decision, not a release qualification, and not a
complete-universe finding.

That basis can authorize only the `live_dev` rollout state.

## Known limitations

- `single_pass_recall_only_not_consolidated` — the run executes pass 1 of 2.
- `sec_only_partial_corpus` — SEC filing text only.
- `single_firm_single_observation_year` — one firm, one observation cutoff.
- `no_completed_evaluation_run` — this prompt has never been executed against a model. What is
  established offline is that the label format it describes is the format the renderer now emits
  for this stage, and that the resolver accepts both spellings. Whether the model follows it is not
  established by anything here.
- `no_baseline_comparison` — the predecessor was executed twice and refused twice at the
  materialization gate, so there is no accepted candidate set to compare against.

**A second, independent defect is present in the same measured output and is not addressed here.**
Two of the eighty resolvable citations in `ext-smoke-cap-0002` quote text that does not occur in the
passage they cite: the quote is the whole of one passage with the trailing word of another
prepended, the same corpus seam that produced the `ext-smoke-0006` Sales Hub failure. C8 (ADR-063)
refuses exactly that, and will refuse it again. This change request does not claim to fix it and
does not weaken C8 to let it through.

**The prompt-to-vocabulary binding is checked offline only**, as recorded for CR-0002 through
CR-0005.

## Risks and trade-offs

The two stages now render the same passage under different labels. A reader comparing a product
rendering with a capability rendering of one packet sees `P001` and `P1` for the same passage. That
is accepted: the label is scoped to one rendered document and resolved against the canonical order
of that document's own packet, and the alternative — one global style — would require reopening a
qualified product prompt that has no defect.

The widened grammar accepts spellings the renderer never emits (`P0025` for position 25). That is
deliberate. The grammar's job is to read what a model wrote, not to police presentation, and every
accepted spelling resolves through `int` to exactly one position. What stays refused is unchanged:
a position outside the packet, a zero ordinal however it is spelled, a wrong case, a missing prefix,
and anything that is not a digit string.

The alternative approaches were considered and rejected. Hardening the prompt against the model's
own tendency was measured to have already failed — v1 states the rule explicitly and the model
broke it identically twice. Repairing `P25` to `P025` in the resolver would be a silent repair, and
the resolver would be interpreting rather than reading.

## Acceptance criteria

- the prompt uses all four bound placeholders, including `validated_products`;
- the four labelled partition lists are present and the B4 offline binding holds against the
  vocabulary artifact;
- the status label table matches `status_label_table()` exactly;
- the prompt asks for no identifier field;
- the predecessor prompt's bytes are unchanged, and `product_discovery_schema_v4`'s are unchanged;
- the label the prompt describes is the label its stage renders, asserted by test;
- both the padded and the unpadded spelling of one ordinal resolve to the same passage;
- no released contract, schema, or property set is modified;
- the full test suite passes.

## Evaluation results

None. See *Qualification basis* above.

## Fixed cases

None in the evaluation harness. The defect this addresses was observed on live runs, not on a
harness case.

## New regressions

None. The product stage's rendering, prompt, change request and qualification records are unchanged,
and the existing tests that pin the padded product label still pass unmodified in substance.

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
