# CR-0005 — Bootstrap qualification for `capability_discovery_schema_v1`

## Status

In review

## Scope note — this introduces a prompt, and edits none

This change request adds one new frozen prompt,
`prompts/extraction/capability_discovery_schema_v1.md`, whose digest is
`def87e3e973d3790a95f17cfbc749ffdf16d7fb024451b964fdd8212ffcc8bee` (5776 bytes).

It modifies **no existing prompt bytes**. `capability_extraction.md` is unchanged
(`f10b85384b9798e6d6cfc497c07d9717d0b26ababa77929de08f62d0879d81b4`, 984 bytes) and stays
registered at position two. Every product prompt is likewise untouched, so `ext-smoke-0002`
through `ext-smoke-0006` remain verifiable. CR-0001 through CR-0004 are untouched.

## Stage

`capability_extraction`, first pass only: `capability_discovery_schema_v1`. Stage context is
`SPEC-009` (`38e73fbe2b20de603bcf27ca222bd96f22c1da34c3f1ece8264ba3c446739815`). The **governing
policy** for the qualification record itself is `SPEC-024`, not SPEC-009.

## Observed gap

The existing capability prompt has never been executed and, measured against the released schema,
could not have produced a conforming record.

`capability_observation@0.1.0` is `additionalProperties: false` and requires six fields:
`capability_observation_id`, `product_observation_id`, `capability`, `availability_status`,
`evidence`, `confidence`. Measured on `prompts/extraction/capability_extraction.md`:

- **zero placeholders** — no company, no cutoff, no passages and no parent products reach the
  model at all;
- **three of the six required fields are never named** — `capability_observation_id`,
  `product_observation_id` and `availability_status` do not appear in the prompt;
- **no output format** — no JSON array, no field list, no fencing rule;
- **no closed status vocabulary** and **no evidence format**;
- it instructs the model to "Return JSON conforming to `capability_observation.schema.json`",
  a file the model cannot see.

This is the same defect class the product prompt carried (CR-0003, CR-0004), one step worse: the
product prompt asked for a field the schema refuses, while this one does not ask for most of the
fields at all.

## General failure class

A prompt whose declared output contract is not the released schema the run validates against. Here
compounded by a prompt that was authored before the stage had any parent context to render, and
never revisited once ADR-058 supplied it.

## Failing case IDs

None. No evaluation case exists for this class and the capability stage has never been executed.
The defect is demonstrated offline: the prompt names three of six required fields, and a document
in the shape it implies cannot validate against the released schema.

## Expected behaviour

The successor states the output contract explicitly and asks the model for exactly what it can
judge, never for a value the pipeline can derive:

- **the parent by short label.** `parent_ref` carries `A01`…`A0N` from the
  `{{validated_products}}` block that ADR-058 renders. `product_observation_id` is 44 characters of
  colon-joined slug and is resolved downstream, never transcribed.
- **evidence by short label.** `{"ref": "P0NN", "quote": ...}`, exactly as ADR-055 established;
  `source_id` and `passage_id` are forbidden in the output.
- **status by short label.** `S1`…`S8` from the table ADR-056 established, generated from
  `CANONICAL_AVAILABILITY_STATUS_VALUES`. The prompt states explicitly that the status describes
  *the capability*, judged from its own evidence, not the availability of its parent.
- **no identifier of any kind.** `capability_observation_id`, `product_observation_id` and
  `normalized_capability` are derived downstream; a candidate carrying any of them is rejected.

`input_types` and `output_types` are requested as **optional** fields, on the evidence-supported-or-
omitted rule. SPEC-009's prose calls them required; the released schema does not list them as such,
and the schema is the contract. Making them mandatory would push the model to invent them.

`schemas/capability_observation.schema.json` is **not** modified.

## Proposed bounded change

Add the successor prompt, move it to position one of the `capability_extraction` sequence, and move
the prompt registry from `extraction_prompt_registry_v4` to `v5`. The known-version set introduced
by ADR-053 absorbs it with no governance-validator change.

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

- `single_pass_recall_only_not_consolidated` — the run executes pass 1 of 2. The output is a
  recall-oriented candidate set, not a consolidated capability inventory.
- `sec_only_partial_corpus` — SEC filing text only.
- `single_firm_single_observation_year` — one firm, one observation cutoff.
- `no_completed_evaluation_run` — this prompt has never been executed against a model. Nothing here
  establishes that it elicits conforming output; what is established is that the shape it asks for
  can conform, which the predecessor's could not.
- `no_baseline_comparison` — the predecessor was never executed to any result, so there is nothing
  to compare against.

**The parent set is one firm's eleven accepted products.** Capability recall is bounded by
Snapshot A: a capability of a product a human rejected cannot be found, by construction. That is
intended — the snapshot is the authorised universe — but it means capability coverage inherits every
limitation of the product decision set.

**The prompt-to-vocabulary binding is checked offline only**, as recorded for CR-0002 through
CR-0004.

## Risks and trade-offs

Attribution is the new failure surface. A capability wrongly attributed to a neighbouring product
would be structurally valid — a real `A0N`, a real passage, a conforming record — and only review
would catch it. The prompt therefore states the rule three times (one capability, one parent; omit
rather than guess; flag uncertainty in `ambiguity`), and the conformance gate that checks the parent
is genuinely a Snapshot A member is deferred to a separate increment rather than assumed here.

Requesting `input_types`/`output_types` as optional accepts that they will often be absent. The
alternative — requiring them — was rejected because a model asked for a field it cannot support from
evidence will supply one anyway.

## Acceptance criteria

- the prompt uses all four bound placeholders, including `validated_products`, which the ADR-058
  gate requires;
- the four labelled partition lists are present and the B4 offline binding holds against the
  vocabulary artifact;
- the status label table matches `status_label_table()` exactly;
- the prompt asks for no identifier field;
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
