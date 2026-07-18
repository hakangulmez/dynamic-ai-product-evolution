# Company Universe Sentinel V0 — Local Fixture Implementation

## Status

Implemented as a **local, fixture-driven sentinel** (Stage 00 registry status:
`sentinel`). No SEC EDGAR ingestion, no model API, and no network access exist
anywhere in this layer. Everything below runs offline and deterministically.

Governing documents: `specs/SPEC-001-company-universe.md`,
`docs/methodology/SOFTWARE_FIRM_UNIVERSE.md`,
`docs/architecture/COMPANY_UNIVERSE_PIPELINE.md`,
`prompts/implementation/phase_0_company_universe.md`.

## What is implemented

| Stage | Component | Module | State |
|---|---|---|---|
| 00A | Historical annual-filer frame contract | `dynamic_ai_products.universe.models` / `identifiers` | Implemented (fixture-fed) |
| 00B | Deterministic issuer exclusions | `universe.issuer_filters` | Implemented |
| 00C | Baseline evidence packets + temporal validator | `universe.packets` | Implemented |
| 00D | High-recall screen interface | `universe.screening` | Implemented; **mock provider only** |
| 00E | Multi-axis classification validation | `universe.classification` | Implemented; **mock provider only** |
| 00F | Deterministic tier derivation + rule trace | `universe.rules` | Implemented |
| 00G | Boundary queue + append-only adjudication | `universe.review` | Implemented |
| 00H | Seeded stratified negative audit | `universe.audit` | Implemented |
| 00I | Hard gates, run manifest, freeze control | `universe.freeze` | Implemented |
| — | Fixture runner / orchestration | `universe.runner` | Implemented |
| — | CLI entrypoint | `pipelines/00_build_company_universe.py` | Implemented |

## What is still a stub or absent

- **SEC EDGAR ingestion (network)** — absent by design. The filer frame is a
  fixture; the adapter boundary is `HistoricalAnnualFiler` +
  `runner._load_fixture_bundle`. A future network-enabled phase replaces the
  fixture loader with a dated EDGAR ingestion component behind the same models.
- **Real LLM providers** — absent. `--provider` accepts only `mock`, which
  replays precomputed fixture outputs through full validation. Real providers
  arrive only with the Phase 1 eval harness and model-route configs.
- **Parquet exports** — sentinel outputs are JSONL; the production exporters to
  the `data/processed/*.parquet` targets in SPEC-001 are not yet written.
- **Eval harness metrics** (recall/precision reporting, confusion matrices) —
  Phase 1 scope.
- **Streamlit review console integration** — Phase 2 scope.

## Commands

Run the full test suite:

```bash
source .venv/bin/activate
PYTHONPATH=src python -m pytest -q
```

Dry-run (validates fixtures, derives tiers, writes nothing):

```bash
python pipelines/00_build_company_universe.py \
  --config configs/universe_sample_rules.yaml \
  --input evals/fixtures/universe_sentinel \
  --output-dir /tmp/dape-phase0-dry-run \
  --run-id phase0-dry-run --seed 42 --provider mock --dry-run
```

Fixture execution (writes an immutable run directory):

```bash
python pipelines/00_build_company_universe.py \
  --config configs/universe_sample_rules.yaml \
  --input evals/fixtures/universe_sentinel \
  --output-dir /tmp/dape-phase0-fixture-run \
  --run-id phase0-fixture-run --seed 42 --provider mock
```

Exit codes: `0` success, `1` hard-gate failure, `2` invalid input/usage.
A reused `--run-id` under the same `--output-dir` is refused (immutability).

## Fixture bundle format

`evals/fixtures/universe_sentinel/` (all firms are synthetic):

- `fixture_manifest.json` — `baseline_cutoff`, `form_scope`,
  `universe_version_on_freeze`.
- `filer_frame.json` — raw filer records (CIKs and accessions are normalized on
  load; issuer cover-page status flags included).
- `evidence_packets.json` — passages per normalized CIK
  (`passage_id`, `source_id`, `section`, `publication_date`, `text`).
- `screen_outputs.json` / `classification_outputs.json` — precomputed mock
  outputs per CIK; validated against the pydantic models and the canonical
  JSON schema before use. Quotes must resolve to packet passages.
- `adjudications.json` — append-only human adjudication records.
- `negative_audit_results.json` — append-only audit records for the sampled
  screen-derived negatives; the freeze is blocked until every sampled
  negative has one (ADR-010).
- `lineage.json`, `firm_year_events.json` — lineage relations and firm-year
  overrides.
- `expected_tiers.json` — gold expectations consumed by the tests, never by
  the runner.

Covered case families: the twelve adversarial cases in
`evals/adversarial/UNIVERSE_BOUNDARY_CASES.md`, plus fund, shell/pre-combination
SPAC, duplicate share class, acquired/delisted incumbent, name change,
post-baseline entrant, insufficient evidence, temporal-leakage attempt, and
three software-enabled non-software negative controls.

## Output interpretation

Each run directory contains JSONL tables mirroring the SPEC-001 output list
(`historical_annual_filers`, `issuer_filter_decisions`,
`universe_evidence_packets`, `universe_screen_predictions`,
`universe_classifications_raw`, `tier_decisions`,
`company_universe_classifications` (derived tier + review state),
`review_queue`, `adjudications`, `negative_audit_sample`,
`firm_year_eligibility`, `firm_lineage`, `companies`), plus
`company_universe_manifest.json` (schema-validated, with content hashes) and
`run_summary.json`.

Raw model output and human adjudication are separate records; adjudication
never overwrites the raw classification or the rule trace.

Exclusions carry explicit provenance (ADR-010): `deterministic` issuer
exclusions are definitive when evidenced; `screen_derived` exclusions
(`LIKELY_INELIGIBLE`) are provisional, enter the negative-audit pool, and
count as confirmed only after their audit record exists;
`economic_classification` exclusions come from the full classifier. The
manifest counts report each provenance class separately
(`excluded_deterministic`, `excluded_screen_derived_provisional`,
`excluded_economic_classification`) plus `negative_audit_completed` /
`negative_audit_pending`.

Count vocabulary: `filer_records` = `unique_firms` + `duplicate_records`;
`unique_firms` = `baseline_firms` + `post_baseline_entrants`; the tier
denominator is `baseline_firms` only — entrants are a separate cohort
(SPEC-001 core rule 9). The run summary carries these identities under
`count_reconciliation` and the run fails if any identity breaks.

## Hard gates before the next phase

The freeze is refused while any of these hold (see `universe/freeze.py`):

- any temporal leakage or unresolvable evidence quote;
- any evidence-free tier inclusion;
- any issuer-excluded firm in Tier A;
- any duplicate CIK;
- any open boundary-review case / incomplete manual review;
- any sampled screen-derived negative without an audit record (ADR-010).

The sentinel fixture satisfies the audit gate only through its own
`negative_audit_results.json` gold records; a production release requires a
real audit pass.

Additional gates before enabling networked SEC ingestion (later phase):

1. Phase 1 eval harness passes its sentinel thresholds (SPEC-001 §Evaluation).
2. **Baseline cutoff is an open production blocker.** `configs/project.yaml`
   still has `universe.baseline_cutoff: null`. The fixture bundle carries its
   own explicit cutoff; the runner refuses any bundle without one and never
   substitutes a default date. A production adapter must require an explicit,
   decision-logged cutoff before it can run.
3. Model routes and prompt hashes recorded for real providers.
4. `configs/project.yaml` `universe.full_edgar_run_enabled` flipped only after
   the above, with a decision-log entry.

## Resolved methodological decisions

- **ADR-009:** `MIXED_NONSEPARABLE` firms are not Tier B candidates
  (`universe_sample_rules.yaml` 0.2.0); they derive Tier C or remain in
  manual review, because their firm-level outcomes cannot be cleanly mapped
  to the software activity. `MIXED_SEPARABLE` firms remain Tier B candidates
  with a documented segment-mapping requirement.
- **ADR-010:** screen-derived exclusions are provisional until the negative
  audit completes; audit completion is a freeze hard gate.
