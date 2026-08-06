# CR-0007 — Bootstrap qualification for `capability_discovery_schema_v3`

## Status

In review

## Scope note — this introduces a prompt, and edits none

This change request adds one new frozen prompt,
`prompts/extraction/capability_discovery_schema_v3.md`, whose digest is
`4904da3472ebc15387440a822c3397e7678498a1ad32f1c625d3c916e3b4f0f2` (6520 bytes).

It modifies **no existing prompt bytes**. `capability_discovery_schema_v2.md` is unchanged
(`caf5b3a04bb1fb3c858fea46ada122fd84575735792aa0438a242fc0758dc0c3`, 5854 bytes) and stays
registered at position two, because `ext-smoke-cap-0003` resolved it. `capability_discovery_schema_v1.md`
and `capability_extraction.md` are unchanged and stay at positions three and four. Every product
prompt is untouched. CR-0001 through CR-0006 are untouched.

## Stage

`capability_extraction`, first pass only: `capability_discovery_schema_v3`. Stage context is
`SPEC-009` (`38e73fbe2b20de603bcf27ca222bd96f22c1da34c3f1ece8264ba3c446739815`). The **governing
policy** for the qualification record itself is `SPEC-024`, not SPEC-009.

## Observed gap

Neither this stage's prompt nor the released schema says anything about how much text an evidence
quote should carry. Measured on `capability_discovery_schema_v2`: the word "quote" appears three
times and never with a length, a sentence count, or a bound of any kind;
`capability_observation.schema.json` types `quote` as `{"type": "string"}` and nothing more.

So the quote's size is whatever the model happens to produce against whatever passage it happens
to be shown. Measured on real output:

- `ext-smoke-0006` (product stage, 124 small passages): 34 quotes, median 204 characters, longest
  590 — one of which was the spliced Sales Hub citation ADR-063 now refuses.
- `ext-smoke-cap-0003` (capability stage, same corpus): 84 quotes, median 96 characters, longest
  220. None over 300.

The capability stage is therefore **not** currently producing long quotes. This change is not a
repair of an observed defect; it is a bound stated before the thing that would make it bite.

## General failure class

An output field whose size is determined by the size of its input container rather than by what it
needs to say. A quote is evidence for one claim; a passage is an arbitrary chunk of a document. When
the two are similar in size the distinction is invisible, and a model shown a large passage has no
instruction telling it not to quote the whole thing.

## Failing case IDs

None. See *Observed gap*: this is a forward-looking bound, and the measurement says the current
capability output already sits inside it.

## Expected behaviour

The successor is `capability_discovery_schema_v2` with the `evidence` section extended. The
`quote` bullet now bounds the quote to **one to three sentences** — enough to support the claim,
not the whole passage — and two binding rules are added: quote the part that supports the claim
rather than the passage it sits in, and copy a contiguous run rather than joining text across a
gap. The silent final check gains a matching line. Nothing else moves.

The contiguity rule is deliberate and is **not** a substitute for C8 (ADR-063). C8 refuses a quote
that is not verbatim in its cited passage, and continues to do so regardless of what any prompt
says. The rule exists so a model that would otherwise reconstruct a sentence across a passage
boundary has been told not to; the gate is what makes it true.

No schema file is modified. `quote` stays `{"type": "string"}` — see *Risks and trade-offs*.

## Proposed bounded change

Add the successor prompt, move it to position one of the `capability_extraction` sequence, and move
the prompt registry from `extraction_prompt_registry_v6` to `v7`. The known-version set introduced
by ADR-053 absorbs it with no governance-validator change.

`STAGE_CHANGE_REQUEST["capability_extraction"]` moves from CR-0006 to this document — the ADR-062
maintenance step, performed for the second time. `STAGE_CHANGE_REQUEST["product_extraction"]` is
untouched.

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
- `no_completed_evaluation_run` — this prompt has never been executed against a model. Nothing here
  establishes that the model obeys the bound; what is established is that the bound is stated.
- `no_baseline_comparison` — the predecessor was executed once and its output was truncated at the
  model's output-token ceiling, so there is no accepted candidate set to compare against.

**The bound is not enforced anywhere.** A quote of thirty sentences that occurs verbatim in its
cited passage passes every gate this repository has. That is stated here rather than implied,
because the natural reading of "1 to 3 sentences" is that something checks it, and nothing does.

**The prompt-to-vocabulary binding is checked offline only**, as recorded for CR-0002 through
CR-0006.

## Risks and trade-offs

**Why this is not enforced in the schema, stated as a decision rather than an omission.** Adding
`maxLength` to `evidence.items.quote` was considered and rejected on three measured grounds.

First, it is a released-contract change: `capability_observation@0.1.0` and
`product_observation@0.1.0` are `additionalProperties: false` released contracts, and narrowing an
existing property is breaking, requiring a successor contract and a manifest bump — not an additive
enum widening.

Second, it would retroactively invalidate accepted data. Eleven human-validated product observations
are persisted under `decisions-ext-smoke-0006-0002`, and their quotes run to 590 characters. Any
bound below that would make records a human already accepted fail re-validation, which is the
opposite of what immutability means here.

Third, and decisively: quote length is not an integrity property. C6 proves the cited pair is a
passage of this run; C8 proves the quoted words occur verbatim in it. Both hold identically for a
20-character quote and a 2,000-character one. A length cap would buy no verifiability; it would only
express a preference about presentation, enforced by a gate whose refusals cannot be distinguished
from real corruption. Rule 7 — unknown over guess — points the other way here: a hard cap would make
the pipeline reject truthful evidence for being verbose.

The cost of leaving it soft is that the bound can be ignored without anything noticing. That is
accepted and recorded above as a known limitation.

## Acceptance criteria

- the prompt uses all four bound placeholders, including `validated_products`;
- the four labelled partition lists are present and the B4 offline binding holds against the
  vocabulary artifact;
- the status label table matches `status_label_table()` exactly;
- the prompt asks for no identifier field;
- the evidence section states the one-to-three-sentence bound and the contiguity rule, asserted by
  test;
- the predecessor prompts' bytes are unchanged;
- no released contract, schema, or property set is modified;
- the full test suite passes.

## Evaluation results

None. See *Qualification basis* above.

## Fixed cases

None.

## New regressions

None. The product stage's rendering, prompt, change request and qualification records are unchanged.

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
