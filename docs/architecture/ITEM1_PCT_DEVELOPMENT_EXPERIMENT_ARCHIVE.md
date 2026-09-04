# Item 1 PCT Development Experiment Archive

## Purpose

This is an archive index, not a relocation of source files. Historical smoke
artifacts pin their prompt and script paths plus SHA-256 digests. Moving or
rewriting those files would make the archived experiments harder to verify.
The files therefore remain at their original repository paths and are marked
here as retained development history rather than as the active pipeline.

The active V8 development chain is defined only in
`docs/methodology/ITEM1_PCT_DEVELOPMENT_SMOKE_PIPELINE.md`.

## Retained experiment families

| Family | Retained material | Why it is archived |
| --- | --- | --- |
| Combined snapshots | `pct_item1_combined_snapshot_v1` through `v5` prompts, schemas, runners, and tests | Compared one-call product/capability/task output shapes before separating stages. |
| Economic PCT variants | `pct_item1_economic_pct_v1` through `v3` prompts, schemas, runners, and tests | Explored task-family and task granularity inside one economic-PCT call. |
| Early capability and task variants | `pct_item1_capability_extraction_v1`, `pct_item1_tasks_flat_v1` through `v4`, and hierarchy variants | Superseded by product-local capability links and the V5 selected-evidence task stage. |
| Consolidation prototypes | economic-product and task-consolidation prompts, schemas, runners, and three-stage smoke | Retained for a future explicit consolidation decision; not part of the active V8 chain. |

## Interpretation rule

Archive status does not mean an experiment was erroneous or deleted. It means
it does not define the currently proposed pipeline and must not silently become
an input to a future run. Any successor may reuse an archived idea only through
an explicit new design decision, versioned prompt/schema, focused tests, and a
new immutable run manifest.
