# CR-0004 — Bootstrap qualification for `product_discovery_schema_v4`

## Status

In review

## Scope note — this introduces a prompt, and edits none

This change request adds one new frozen prompt,
`prompts/extraction/product_discovery_schema_v4.md`, whose digest is
`9fea11ceb77b83c05f11e98adc3dc3a54cf6a97a9c9cf2753d1eb691b3f74407` (4743 bytes).

It modifies **no existing prompt bytes**. `product_discovery_schema_v3.md`,
`product_discovery_schema_v2.md` and `product_discovery_recall.md` are unchanged and stay
registered, so `ext-smoke-0002` through `ext-smoke-0005` all remain verifiable. CR-0001,
CR-0002 and CR-0003 are untouched.

## Stage

`product_extraction`, first pass only: `product_discovery_schema_v4`. Stage context is `SPEC-008`
(`31d2a8d49bae58ec3f9d1820867c07edf473e9565f7f38f840f26382ed555a83`). The **governing policy** for
the qualification record itself is `SPEC-024`, not SPEC-008.

## Observed gap

The same fault class as CR-0003, in a different field, measured on the run that CR-0003's prompt
produced.

`ext-smoke-0005` returned fifteen candidates. Fourteen wrote `availability_status` as
`broadly_deployed_or_default`. One wrote `broadly_deployed_or_or_default` — the syllable `or`
doubled, 30 characters instead of 27. Every other gate passed on that run: C6 resolved 28 of 28
citations, which is what the ADR-055 labels were for, so the only remaining transcription in the
output is the one that failed.

Under the atomic C5 gate a single ungoverned status refuses the whole materialization, so one
doubled syllable blocked fourteen correct candidates.

## General failure class

Asking a model to copy a long, internally repetitive string. This is the third instance and the
third fix of the same shape: `candidate_id` was never requested; ADR-054 derived `company_id`,
`normalized_name` and `product_observation_id`; ADR-055 replaced transcribed `passage_id` and
`source_id` with positional labels. The status token is the last field in the output that the
model was still required to reproduce character for character.

## Failing case IDs

None. No evaluation case exists for this class. The defect is demonstrated by an archived live run
and by offline resolution tests.

## Expected behaviour

The prompt renders a label table — `S1` through `S8`, one per status, in the canonical order of
`CANONICAL_AVAILABILITY_STATUS_VALUES` — and asks for `availability_status` as a label. Downstream,
`resolve_status_labels` turns the label back into the token before schema validation and before C5,
so a conforming observation still carries the real status word and
`schemas/product_observation.schema.json` is **not** modified.

The four labelled partition lists stay in the prompt with their real tokens. They are what the
model reads to decide *which* status applies, and they are what the B4 offline binding compares
against the vocabulary artifact. Replacing them with labels would delete that binding, which is
the check that proves the prompt's copy has not drifted.

## Proposed bounded change

Add the successor prompt, move it to position one, and move the registry from
`extraction_prompt_registry_v3` to `v4`. The label table is generated from the same code-owned
tuple the resolver reads, so the instruction and the code cannot disagree about what `S2` means.

A label outside `S1`-`S8`, or a value that is not a label at all — including a correctly spelled
status word — is refused with `candidate_conformance_status_label_unresolvable`, separate from the
C5 code. Strictness is deliberate: accepting both spellings would let one run mix two conventions
and would quietly restore the transcription this change removes.

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

- `single_pass_recall_only_not_consolidated` — the run executes pass 1 of 5.
- `sec_only_partial_corpus` — SEC filing text only.
- `single_firm_single_observation_year` — one firm, one observation cutoff.
- `no_completed_evaluation_run` — no evaluation has been executed against this prompt. That a short
  label is emitted more reliably than a token is **untested against a model**; three archived runs
  establish that long strings are copied unreliably, not that labels are copied reliably.
- `no_baseline_comparison` — no baseline exists.

**The prompt-to-vocabulary binding is checked offline only**, as recorded for CR-0002 and CR-0003.

**A label names a position in a code-owned tuple.** Unlike a passage reference it does not depend on
the packet, so it is stable across runs — but it is still not an identity: the persisted artifact
stores the resolved status word, never the label.

## Risks and trade-offs

Refusing a correctly spelled status word is a real cost: a run where the model ignored the label
instruction fails entirely rather than partially. That is the intended trade. A lenient resolver
would accept the token path, and the token path is the one measured to fail.

The label table adds a second representation of the vocabulary inside the prompt. It is generated
from `status_label_table()`, the same function the resolver uses, and a test asserts the rendered
table matches it — so the two cannot drift the way a hand-written copy could.

## Acceptance criteria

- the prompt renders the label table generated from the canonical tuple;
- the four partition lists are unchanged and B4 still binds them to the artifact;
- a label resolves to its token before schema validation and before C5;
- a malformed, out-of-range, or spelled-out status is refused with its own reason code and writes
  nothing;
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
