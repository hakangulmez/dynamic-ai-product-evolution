# SPEC-001 — Historical Company Universe

## Status

Draft

## Objective

Construct a dated, evidence-backed, versioned universe of public operating firms whose customer value is produced wholly or materially through software-led digital products, while preserving boundary classes and avoiding survivorship, post-treatment, and keyword-selection bias.

## Governing documents

- `CLAUDE.md`
- `docs/methodology/SOFTWARE_FIRM_UNIVERSE.md`
- `docs/architecture/COMPANY_UNIVERSE_PIPELINE.md`
- `docs/SOURCE_POLICY.md`
- `docs/TEMPORAL_POLICY.md`
- `docs/DATA_GOVERNANCE.md`
- `evals/rubrics/UNIVERSE_CLASSIFICATION_RUBRIC.md`

## Unit of construction

The initial candidate unit is `CIK × baseline annual filing`. Firm-year and lineage tables are produced separately. Ticker is a dated attribute and must not be used as the stable firm key.

## Inputs

- project baseline cutoff and form scope;
- SEC annual-filing history and dated issuer metadata;
- deterministic issuer-filter rules;
- baseline evidence passages;
- universe taxonomy and sample rules;
- high-recall and full-classification prompts;
- gold, adversarial, boundary, and negative-audit fixtures;
- append-only human adjudications.

## Outputs

- `data/registry/historical_annual_filers.parquet`;
- `data/registry/issuer_filter_decisions.parquet`;
- `data/interim/universe_evidence_packets.jsonl`;
- `data/interim/universe_screen_predictions.jsonl`;
- `data/interim/universe_classifications_raw.jsonl`;
- `data/processed/company_universe_classifications.parquet`;
- `data/processed/firm_year_eligibility.parquet`;
- `data/processed/firm_lineage.parquet`;
- `data/registry/companies.parquet`;
- `data/manifests/company_universe_manifest.json`.

## Required schemas

- `company.schema.json`;
- `company_universe_classification.schema.json`;
- `firm_year_eligibility.schema.json`;
- `firm_lineage.schema.json`;
- `universe_run_manifest.schema.json`.

## Construction stages

### A. Historical filer frame

Build the full eligible annual-filer frame as of the baseline cutoff. Preserve exited, acquired, failed, and delisted operating firms. Link amendments to original filings. Separate domestic annual filers from foreign-private-issuer extensions.

### B. Deterministic issuer filtering

Apply explicit, tested reason codes to funds, trusts, asset-backed issuers, shells, pre-combination blank-check companies, duplicate share classes, and non-operating records. Never delete silently.

### C. Baseline evidence packet

Build a compact, passage-addressable packet from temporally eligible SEC evidence. The packet must contain enough information to evaluate customer value, software centrality, complementary dependencies, firm structure, and commercial materiality.

### D. High-recall screening

Classify every cleaned packet as likely eligible, likely ineligible, or boundary/uncertain. Optimize for recall; do not treat this output as final membership.

### E. Multi-axis classification

Classify customer-value archetypes, software centrality, complementary dependencies, firm structure, materiality, data eligibility, boundary flags, and confidence. Every non-null claim requires evidence.

### F. Deterministic sample derivation

Derive Tier A, Tier B, Tier C, excluded, and uncertain from versioned rule configuration. Preserve a machine-readable rule trace.

### G. Adjudication and negative audit

Review all boundary cases required by policy. Draw a reproducible stratified sample from likely-ineligible records and estimate false-negative risk.

### H. Freeze

Release a universe only when hard gates pass. Record hashes, versions, counts, eval results, reviews, and limitations.

## Core rules

1. Baseline membership uses only evidence available on or before the baseline cutoff.
2. Current web pages cannot establish historical eligibility.
3. SIC, NAICS, GICS, keywords, or an AI mention are candidate signals, not final rules.
4. A customer-facing mobile app does not make a firm a software firm.
5. Software centrality and customer-value archetype are separate fields.
6. Complementary assets do not automatically imply defensibility.
7. Economic eligibility and data eligibility are separate.
8. Unknown is a valid result and must not be coerced.
9. Post-baseline entrants are stored separately from baseline incumbents.
10. Acquired, delisted, bankrupt, and failed incumbents remain in historical observations.
11. Mixed-firm product observations must not be linked to total-firm outcomes without a documented mapping.
12. Original model, rule, and human-review states are all preserved.

## Inclusion logic

Tier derivation is governed only by `configs/universe_sample_rules.yaml`. The prompt may propose a candidate tier for review, but that proposal is not authoritative.

## Deterministic validations

- unique CIK in the frozen company identity table;
- valid accession and filing dates;
- amendment linkage;
- valid enum values;
- evidence source and passage resolution;
- direct quote substring validity;
- evidence date at or before baseline cutoff;
- reason code for every deterministic exclusion;
- rule trace for every derived tier;
- no Tier A shell, fund, or non-operating issuer;
- no duplicate or silently dropped firm;
- no current-page evidence in baseline packets;
- no overwrite of prior runs or releases;
- complete manifest and content hashes.

## Evaluation

Report:

- high-recall screen recall;
- Tier A precision and recall;
- archetype, centrality, structure, and materiality agreement;
- evidence validity;
- temporal leakage;
- unknown rate;
- false inclusion of software-enabled non-software firms;
- negative-audit false-negative estimate;
- reviewer agreement;
- confusion matrices by economic archetype and source-coverage stratum.

## Hard release gates

- temporal leakage: zero;
- evidence-free inclusion: zero;
- fabricated evidence quote: zero;
- shell/fund/non-operating Tier A inclusion: zero;
- duplicate CIK: zero;
- unknown coercion: zero;
- missing release manifest: zero;
- unresolved high-severity boundary decisions: zero.

Numerical precision/recall thresholds are provisional until the sentinel gold set is completed. Any threshold change requires a change request and decision-log entry.

## Sentinel acceptance criteria

- all hard release gates pass;
- all intended archetype strata are represented;
- at least one difficult case from each boundary family is adjudicated;
- negative-audit sampling is reproducible;
- the sample rule can be changed without rerunning the model;
- all output tables validate against schemas;
- a complete dry run produces an immutable manifest;
- remaining uncertainty is documented rather than hidden.

## Failure modes

- historical filer frame built from current survivors only;
- post-baseline product evidence leaks into eligibility;
- software keywords drive false inclusion;
- marketplaces or content platforms are treated as core functional software without economic analysis;
- mixed firm is linked to total outcomes without separability;
- first-pass negatives are never audited;
- ticker changes create duplicate firms;
- insufficient evidence is coded as economic ineligibility;
- prompt output silently defines the sample.

Failures are written to versioned error and review tables.

## Run manifest

Every run records cutoff, forms, candidate-frame hash, code state, packet version, prompt/model versions, schemas, taxonomy, sample rules, sampling seed, eval IDs, review state, counts, and output hashes.

## Open questions

See Section 11 of `SOFTWARE_FIRM_UNIVERSE.md`. Open questions must be resolved through the sentinel and recorded in `docs/DECISION_LOG.md`.
