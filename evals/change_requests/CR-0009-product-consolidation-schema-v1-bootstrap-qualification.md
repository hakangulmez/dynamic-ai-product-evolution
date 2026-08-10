# CR-0009 — Bootstrap qualification for `product_consolidation_schema_v1`

## Status

Proposed.

## Scope note — this introduces a stage, and edits none

Nothing in the three discovery flows changes. Asserted by test rather than
claimed here:

- `product_discovery_schema_v4` and every other registered prompt file is
  byte-unchanged, including `product_consolidation_precision`, which stays at
  position five of the `product_extraction` sequence rather than being moved
  into the new stage. A frozen prompt is never moved and never deleted; moving
  it would rewrite the record of what that stage's sequence was.
- `EXTRACTION_PROMPTS["product_extraction"]` still has its five entries in the
  same order. `single_pass_prompt_plan` is byte-unchanged.
- `srcsnap-hubspot-fy2024-sec-v1`, `-v2` and `-v3` are byte-unchanged.
- `ext-smoke-0009`, `cand-ext-smoke-0009-0001`, the product decision set built
  from it and the Snapshot A derived from that are all byte-unchanged.

Every registry change is one line added to a closed map. No existing entry is
edited or reordered.

## Stage

`product_consolidation` — new.

## Observed gap

`SPEC-008` defines a consolidation pass and `product_consolidation_precision`
has been registered since the first prompt registry. It has never executed, and
measurement shows it could not:

1. **No code path reaches it.** All three consumers of `single_pass_prompt_plan`
   take `sequence[0]`, and none accepts a prompt selection.
   `single_pass_prompt_plan`'s own docstring records that executing position one
   is an explicit ADR-036 decision rather than incidental indexing.
2. **It has no input mechanism.** The prompt carries zero `{{...}}`
   placeholders, and `STAGE_PLACEHOLDER_BINDINGS["product_extraction"]` has no
   binder for candidates — the packet has no field to hold them.
3. **It states no output contract.** It asks for "retained product
   observations, alias links, family links, exclusions with reasons, and
   unresolved cases" and names no field, no type and no shape.

Point 3 is the same defect `prompts.py` already names for `task_discovery_recall`
— *"this prompt states no output contract at all"*, the CR-0005 defect — one
stage earlier. CR-0008 contrasts its own prompt against it explicitly
(*"Unlike the capability stage's CR-0005 predecessor, this prompt is not
placeholder-empty"*). This CR closes the same gap for the product stage.

## General failure class

A registered artifact that no code path can execute, whose defect is invisible
because nothing ever ran it. The registry entry made it look available.

## Expected behaviour

Consolidation is a **stage**, not a second pass:

- its input is the discovery stage's *output* — a hash-pinned candidate
  collection — not the corpus;
- its output is a **decision per candidate**, not an observation. The model
  never re-emits an observation body; a retained product is carried through
  byte-unchanged from the candidate it came from, and the consolidated universe
  is assembled deterministically downstream. That is ADR-054's rule for derived
  identity, applied one artifact on, and it exists because a model cannot
  reliably copy a long opaque string (ADR-055) and a re-emitted body is one it
  could have silently altered;
- candidates are cited by a short positional label `D0N`, unpadded per ADR-064.
  `C` is not available: it belongs to `focal_capability_order`, and one letter
  with two meanings is the failure `canonical_passage_order` exists to prevent;
- `unresolved` is a first-class action, because rule 7 says unknown over guess
  and a rule the output cannot express is a rule the model cannot follow.

## Proposed bounded change

- `prompts/extraction/product_consolidation_schema_v1.md` — new prompt with an
  explicit output contract.
- `schemas/product_consolidation_output.schema.json` — what the model returns.
- `schemas/product_consolidated_universe.schema.json` — what is persisted.
- `schemas/extraction_input_packet.v3.schema.json` — `@0.2.0` plus
  `candidate_context`. Required because the candidates the model was shown must
  sit inside the packet whose digest the run records; leaving them outside would
  make `input_packet_sha256` cover less than the model actually saw.
- `extraction/consolidation.py` — `resolve_candidate_refs` and
  `materialize_consolidated_universe`.
- `derive_candidate_context`, `candidate_ref_order`, `_bind_product_candidates`.
- One optional `candidate_collection_pin` parameter on the runner.
- Six reason codes, listed under Acceptance criteria.

## Qualification basis — pre-evaluation, and stated as such

`bootstrap_pre_evaluation`. No evaluation run has scored this prompt against a
baseline, because no consolidation output exists to score. The qualification
records that, rather than implying a comparison that has not happened.

## Known limitations

- `single_pass_recall_only_not_consolidated` now carries two readings: "this
  project does not consolidate" and "consolidation is a separate run". Left
  as-is — no record misuses it today, and adding a second code to an enum
  nothing is exercising would be a change without a caller.
- The rule that a bundle is a product only when it creates a cross-product
  workflow is a judgement the prompt states and nothing downstream can check.
- `product_observation.schema.json` carries `entity_type` and `product_family`,
  written by discovery. Consolidation records its own view as `entity_role` and
  `families[]` beside the observation rather than overwriting those fields, so
  which stage said what stays legible. Reconciling the two is out of scope.

## Risks and trade-offs

- A consolidation decision set — the human judgement over this artifact — does
  not exist. The consolidated universe is a model output with evidence, not an
  admitted finding, and nothing downstream may treat it as one until that stage
  is built.
- The packet gains a third contract. `@0.1.0` and `@0.2.0` are unchanged and a
  caller supplying no candidate pin gets exactly the packet it got before, but
  there are now three loaders to keep closed.

## Acceptance criteria

- New reason codes, each with its own test: `consolidation_candidate_not_decided`,
  `consolidation_candidate_decided_twice`, `consolidation_ref_unresolvable`,
  `consolidation_self_link`, `consolidation_link_targets_excluded`,
  `consolidation_evidence_quote_uncontained`.
- `product_consolidation` is in `MATERIALIZATION_SUPPORTED_STAGES` and is **not**
  in `STAGE_OBSERVATION_KIND`; `observation_kind_for_stage` refuses it.
- `single_pass_prompt_plan("product_consolidation")` returns
  `prompt_sequence_complete = True`; `product_extraction` still returns `False`.
- Both new schemas are meta-valid and their conditional branches are exercised
  per action, including refusal of a padded ref and of a forbidden observation
  field.
- Full suite green; `ruff` clean.

## Evaluation results

Not applicable — pre-evaluation bootstrap.

## Fixed cases

None claimed. This makes a registered stage executable; it does not assert that
its output is correct.

## New regressions

None expected. Every change is additive and the discovery flows are asserted
byte-unchanged.

## Decision

Pending.

## Approval

Pending.
