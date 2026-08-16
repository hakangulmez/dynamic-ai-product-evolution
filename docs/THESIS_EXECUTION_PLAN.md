# Thesis Execution Plan

## Status

Accepted direction, partially executed. W0 is decided (ADR-077) and the frame
work is complete and frozen: `FRAME_v1` is released by ADR-087 against run
`frame-live-full-v11-2020q1-2026q2-20260815`. Decisions ADR-077 through
ADR-089 have been accepted, and at least five material runs have executed —
live EDGAR index acquisition, the FRAME build, DERA FSDS acquisition, the
gate-passing FRAME-versus-DERA validation, and the firm-level baseline
carrier — recorded in eleven immutable run directories in total, the
remainder being canaries, one superseded draft-grain canary, one dead
acquisition, and two gate-failing validation runs, all preserved rather than
deleted. The analytical path beyond the frame is unstarted: no screening, no
classification, no tier derivation, no universe freeze, no sample draw and no
PCT extraction has run, and no model call has been made on this path. That
statement is about the analytical path only — it does not describe the
post-frame denominator work already named above, which has executed (the
firm-level baseline carrier) or exists as tested capability awaiting its own
authorization (bounded baseline-document acquisition, canary unexecuted).

This is the canonical record of the thesis-first path. It supersedes no
methodology document: `docs/methodology/SOFTWARE_FIRM_UNIVERSE.md` and
`specs/SPEC-001-company-universe.md` remain governing, and this plan states
which of their stages run, in what order, and under what gates.

## Objective

Produce a defensible, source-grounded product–capability–task panel and proceed
to scoring. The deliverable is a dataset, not a platform.

## Artefact chain

```text
FRAME_v1                     dated annual-filer frame, no filtering
   ↓
UNIVERSE_v1                  full-frame screen, classification, tier derivation,
                             deterministic boundary queue, bounded negative
                             audit, freeze
   ↓
EXTERNAL_SET_COMPARISON_v1   dated CIK crosswalks against external firm lists
   ↓
SAMPLE_v1                    frozen extraction panel drawn from the governed
                             universe
   ↓
PCT_v1                       product–capability–task extraction, SAMPLE_v1 only
```

Each artefact carries its own manifest and version line. They are not
interchangeable, and three distinctions are load-bearing:

- **FRAME_v1 is not a sample.** It is the denominator. Nothing is excluded from
  it; non-operating issuers are flagged with reason codes, never dropped.
- **UNIVERSE_v1 is not an extraction target.** Screening and classification run
  over the whole frame because they are cheap. PCT extraction does not.
- **SAMPLE_v1 is not a population estimate.** It is a frozen stratified thesis
  panel. The sampling design is recorded; no population reweighting estimator is
  claimed or implemented.

## Measurement principle

**Every operational count, cost, and sample size in this plan is measured at a
gate, not carried as a fixed input.** Figures that appear anywhere in planning
notes — frame size, download volume, positive-and-boundary rate, classification
cost, final panel size — are provisional until the artefact that produces them
exists and is manifested.

Concretely:

| quantity | measured by | status |
|---|---|---|
| frame size, filer counts | `FRAME_v1` | measured: 48,793 domestic annual + 7,478 FPI extension = 56,271 filer-accession records (ADR-087) |
| DERA-versus-full-index coverage delta | `FRAME_v1` validation artefact | measured: gate pass, zero unexplained residuals, five committed adjudications applied (ADR-086) |
| firms surviving deterministic issuer filters | Stage 00B run | unverified — the firm-level carrier exists (12,160 firms; 9,916 baseline candidates) but applies no exclusions and leaves every issuer status unknown pending cover-page evidence, so this quantity is unmeasured; that is pre-00B carrier work (ADR-088) |
| download volume and wall-clock | canary, then Stage 00C | unverified — the request plan and the bounded document transport exist (ADR-089); the 12-document canary is unexecuted |
| positive-and-boundary rate | Stage 00D, at the budget gate | unverified |
| classification cost | Stage 00E projection at that gate | unverified |
| false-omission rate | bounded negative audit | unverified |
| final panel size | `SAMPLE_v1` draw, after `UNIVERSE_v1` is frozen | unset; see the cap below |

A gate that would consume an unmeasured number stops instead.

**The 200-firm figure is a resource and time ceiling on PCT extraction, not a
pre-committed final firm count.** It bounds what the extraction budget and the
schedule can carry; it does not assert that the panel will reach it, approach it,
or stop short of it. The final `SAMPLE_v1` size is determined **after
`UNIVERSE_v1` is frozen**, from the governed Tier A pool and the identification
requirement fixed in W0. If W0 establishes that identification needs more firms
than the ceiling carries, the plan stops for a scope or specification decision
rather than expanding automatically.

## Source scope

| in | out of this release |
|---|---|
| domestic `10-K` / `10-KT` | `20-F` / `40-F` — recorded in the frame, not sampled |
| SEC Item 1 / business disclosure | `10-Q` / `8-K` / `6-K` event coverage |
| official product pages, developer documentation, release notes, pricing — **10–15 firm enrichment subset only** | exhaustive official-web collection |

`PCT_v1` is explicitly an SEC-Item-1-disclosed dataset. The enrichment subset
measures recall; a low recall result is reported as a limitation and a
sensitivity result and **does not expand the primary corpus**.

## Gate sequence

```text
W0   design            DECIDED (ADR-077). Baseline cutoff 2022-11-29, frozen
                       ex ante in configs/project.yaml. FRAME filing-date
                       admission window 2020-01-01 through 2026-06-30 (2020
                       QTR1 to 2026 QTR2); this freezes filing-date admission
                       only — the fiscal-period carrier and PCT observation
                       coverage are a separate successor decision, and no
                       FY2020/FY2021 baseline PCT evidence is excluded by it.
                       FY2022 is retained as a transition observation, and
                       final pre/transition/post classification uses actual
                       reporting-period start and end dates, never firm
                       fiscal-year labels. No binary treated/control group is
                       frozen: all eligible firms remain in the universe;
                       baseline frontier task replicability is a future
                       continuous ex-ante exposure measure; post-shock AI
                       transformation, mechanism reach, and deployment are
                       observed responses, not treatment criteria. The exact
                       FTR rubric, weights, outcome, and estimator/FE
                       specification remain pilot-gated; if the
                       pilot-determined firm requirement exceeds the
                       extraction ceiling, the plan stops for a scope
                       decision. As decided here, filing collection was
                       unblocked from this gate while model calls and the
                       full frame run were gated. That frame gating has since
                       been lifted by reviewed increments: the full FRAME run
                       executed and FRAME_v1 is frozen under ADR-087 (see W1).
                       Model calls remain gated and unexecuted on this thesis
                       path.

W1   frame             FRAME_v1 COMPLETE AND FROZEN (ADR-087); one separate
                       legacy item in this gate is outstanding, stated at the
                       end of this entry. FRAME_v1 is released
                       against run
                       frame-live-full-v11-2020q1-2026q2-20260815, manifest
                       SHA-256 5203660fe4c6093041383284ad36614a5ac4d7116a1e
                       1259138e14ebde164cee, carrying 56,271 filer-accession
                       records with zero parse failures; the freeze record is
                       configs/frame_v1_freeze.json. Built from the EDGAR
                       full index; DERA FSDS was an independent validation
                       source only, never the frame source, and its
                       validation gate passes with zero unexplained residuals
                       (ADR-086). The frame window is carried as explicit
                       filing_window_start / filing_window_end filing-date
                       bounds; fiscal analytical-period assignment is a later
                       PCT/schema concern and is not carried by FRAME_v1.
                       SEPARATELY OUTSTANDING, and outside the scope of the
                       FRAME_v1 freeze: the admission audit of the existing
                       legacy sec-v4 snapshots has not been performed and no
                       audit artefact exists. The freeze covers the frame
                       artefact and its validation evidence only; it makes no
                       claim about those snapshots, and this audit is neither
                       completed by it nor dropped from the plan.

W2   first metric      one interpretable, source-derived HubSpot MetricReport.
                       C4 consolidation design evaluated against a pre-registered
                       gate; it is not registered merely because it exists.

W3   infrastructure    batch download queue, scale packet builder, live provider
                       route — implemented and tested before any full-frame work.
                       56-firm sentinel roster and gold.

W4   sentinel          development iteration under an ex ante stop rule, then a
                       single evaluation on frozen set 1. Prompts freeze here.

W5a  canary            50–100 firms, structural validation only. Tier assignments
                       are not read and no taxonomy or prompt is tuned from them.

W5b  full frame        screen, budget gate, classification, tier derivation.

W7   universe freeze   deterministic boundary queue, bounded negative audit,
                       classification-uncertainty sensitivity table,
                       UNIVERSE_v1 freeze, SAMPLE_v1 draw.

W8   extraction        PCT over SAMPLE_v1. External-set comparison runs in
                       parallel and does not block the universe freeze.

W9   release lock      PCT_v1 freeze, thesis_release_manifest.json, offline
                       reproduction notebook.
```

## Rules fixed ex ante

Written before the results they judge. Changing one requires a change request.

1. **C4 production gate.** Zero of three gold non-targets classified as retained
   products; at least twelve of thirteen targets at the correct commercial level;
   no wrong level for a retained product; a second-firm replication. Otherwise C4
   remains provisional and is not registered.
2. **Frozen gate.** No fund, shell or non-operating entity in Tier A; no Tier C
   archetype classified Tier A; tier agreement at least 13 of 16; evidence
   validity at least 0.98; no post-cutoff evidence.
3. **Development stop rule.** At most two new prompt versions, five working days,
   or a fixed model-spend ceiling on the development set — whichever comes first.
   Exceeding it routes to a methodology or scope decision, not to further
   iteration.
4. **Frozen-set matching.** Frozen set 1 and reserve frozen set 2 are matched on
   layer composition, so a failure on set 2 cannot be an artefact of a different
   population.
5. **High-impact boundary subset.** Rule-derived Tier A carrying a boundary flag,
   or `CO_ESSENTIAL` centrality, or multiple material archetypes; capped, ordered
   deterministically. Everything else stays `UNCERTAIN` and is excluded from
   Tier A sampling.
6. **Negative-audit consequence.** Three or more audited negatives sharing one
   (archetype, centrality) pair and judged eligible is a systematic omitted
   economic class: `UNIVERSE_v1` becomes provisional, a versioned screen or
   taxonomy correction is written, and the affected batch is re-run. Isolated
   misses enter the false-omission rate without a re-run.
7. **Screen-to-classification budget gate.** If the positive-and-boundary rate or
   the projected classification cost is materially above plan, classification does
   not start; the rate is reported and reviewed first.

## Sentinel partitions

```text
56 firms
  development     24    prompt iteration, under rule 3
  frozen set 1    16    evaluated once, after the candidate prompt is locked
  frozen set 2    16    untouched reserve; used only if set 1 fails, once
```

Each frozen set is pre-stratified across the twelve gold strata of
`docs/methodology/SOFTWARE_FIRM_UNIVERSE.md` §9.1 and across the high-risk
boundary types of §6.7. Frozen results may not tune the prompt version they
evaluated. A failed frozen evaluation opens a new version and a new cycle.

The frozen partitions are a **regression gate, not a precision estimator**: at
sixteen cases across twelve strata they cannot support stratified precision
estimates. Precision and recall estimation comes from the bounded negative audit
and full-frame results.

## Boundary handling

The universe boundary-adjudication prompt is **not used** in v1. Boundary cases
route to the existing deterministic queue in
`src/dynamic_ai_products/universe/review.py`, which has no model dependency. The
pre-declared high-impact subset is adjudicated manually; everything else remains
`UNCERTAIN` and is excluded from Tier A sampling.

That exclusion biases the panel toward firms that were straightforward to
classify. It is not treated as harmless: `UNIVERSE_v1` carries a
classification-uncertainty sensitivity table reporting confirmed Tier A, reviewed
high-impact boundaries, and remaining uncertain firms with their SIC, industry,
size and screen-status composition.

## External lists

External firm lists are **benchmark datasets, not ground truth**. For each list
the as-of date, its own inclusion rule, and its access route are recorded;
crosswalk is by CIK; the report gives overlap and composition differences against
our Tier A/B/C/excluded/uncertain categories. A list that cannot be accessed
under licence is recorded as an unavailable benchmark and is not approximately
reconstructed. External-list availability never blocks the `UNIVERSE_v1` freeze.

## Controls preserved

Temporal validity; source hashes; prompt, schema and model versions; evidence
resolution; quote containment plus a narrow relevance rule; explicit missingness;
run manifests; append-only corrections; frozen gold partitions.

## Frozen for this release

New slices, general-purpose framework work, prompt experimentation, and
one-ADR-per-minor-fix governance. An ADR is written for a scope decision, a
schema version increment, or a freeze — not for a bug fix.

## Deferred beyond PCT_v1

AI-mechanism and reach modelling is deferred, not abandoned. The preserved design
is an orthogonal `mechanism_observation` table plus many-to-many
mechanism-to-governed-product coverage edges, with categorical claims preserved
without product expansion, `unstated` distinct from zero reach, and a denominator
containing only governed retained products. One implementation constraint is
already known: the target registry keeps aliases and canonical ids in one shared
namespace, so a mechanism entry cannot reuse a product alias. See
`evals/change_requests/CR-0011-ai-mechanism-and-reach.md`.

Also deferred: foreign private issuers, event-filing coverage, exhaustive
official-web collection, population reweighting estimators, and per-filing header
retrieval for as-filed SIC where DERA has no coverage.

## Operator and publication surfaces

`notebooks/00_MASTER_PIPELINE.ipynb` remains the canonical operator notebook
under `specs/SPEC-026-master-notebook-orchestration.md`. It is not renamed and no
parallel orchestration notebook is created.

**Current state, stated so the plan is not read as a description of what exists.**
The notebook is a scaffold and status surface: it loads the stage registry, runs
preflight checks, and reports project safety state. It does not yet orchestrate a
production run, because the stages it would drive are mostly unimplemented —
`pipelines/01`–`14` all raise `NotImplementedError`. `pipelines/00_build_company_universe.py`
is the exception and is no longer fixture-only: it carries seven modes
(`sentinel`, `frame`, `acquire-index`, `dera-validate`, `acquire-dera`,
`baseline-carrier`, `acquire-docs`), has performed real SEC network
acquisition under the committed `sec_live` transport contract, and accepts
seventeen flags — the original `--config`, `--run-id`, `--dry-run`,
`--output-dir`, `--provider`, `--seed` and `--input`, plus `--mode`,
`--index-dir`, `--filing-window-start`, `--filing-window-end`,
`--acquisition-manifest`, `--request-plan`, `--replay-dir`, `--transport`,
`--frame-manifest` and `--dera-dir`. It writes a run manifest and exits
non-zero on a failed hard gate; `--resume` does not exist on any stage.

**Required implementation condition, not a current capability.** As each critical
stage is implemented it must support an explicit config, a run id, dry-run where
feasible, resume and idempotency, manifest output, and a non-zero exit on a failed
gate. Once those CLIs exist, the notebook calls them and displays a
manifest-derived stage ledger. Until then it shows status, and the ledger has
nothing to read.

`notebooks/01_reproduce_published_results.ipynb` is the publication-facing
notebook. It starts from `thesis_release_manifest.json` — a thin release lock
recording each release artefact's manifest path, hash, and the git revision — and
reproduces tables, figures, coverage reports and external-set comparisons from
frozen artefacts with no network access, no API keys and no model calls. Neither
notebook may contain business logic, prompt text, taxonomy rules, or tier
derivation.

## Governing documents

- `CLAUDE.md`
- `docs/methodology/SOFTWARE_FIRM_UNIVERSE.md`
- `specs/SPEC-001-company-universe.md`
- `specs/SPEC-026-master-notebook-orchestration.md`
- `docs/SOURCE_POLICY.md`, `docs/TEMPORAL_POLICY.md`
- `evals/EVAL_HARNESS.md`
