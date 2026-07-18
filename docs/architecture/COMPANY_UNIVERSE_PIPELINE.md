# Company-Universe Pipeline Architecture

## Purpose

This document translates the universe methodology into an implementation architecture. The canonical business definition is in `docs/methodology/SOFTWARE_FIRM_UNIVERSE.md`; this file governs data flow and component boundaries.

## Architectural rule

No LLM receives “all of EDGAR” and returns a company list. Candidate generation, issuer cleaning, evidence packet construction, model screening, deterministic tier assignment, human review, and release freezing are separate stages with immutable intermediate outputs.

## Stage 00 sub-pipeline

```text
00A historical annual-filer frame
  ↓
00B deterministic issuer cleaning
  ↓
00C baseline evidence-packet construction
  ↓
00D high-recall screen
  ↓
00E full multi-axis classifier
  ↓
00F deterministic Tier A/B/C rules
  ↓
00G append-only boundary adjudication
  ↓
00H stratified negative audit
  ↓
00I UNIVERSE_vX.Y freeze
```

## Components

### `registry/filer_frame`

Responsibilities:

- ingest dated annual filing metadata;
- normalize CIK and accession identifiers;
- retain annual forms and amendment relations;
- preserve current/former names and dated listing attributes where available;
- create entry/exit candidates;
- never classify business type.

### `universe/issuer_filters`

Responsibilities:

- deterministic fund, trust, shell, blank-check, asset-backed, and duplicate handling;
- structured reason codes;
- reversible flags rather than destructive deletion;
- unit tests for every exclusion family.

### `universe/evidence_packets`

Responsibilities:

- select temporally eligible Item 1 and cover-page passages;
- include product/service, customer, segment/materiality, and technology-delivery evidence;
- retain passage IDs and offsets;
- report missing sections;
- prohibit current official-web evidence for baseline eligibility.

### `universe/screening`

Responsibilities:

- run the high-recall prompt on every cleaned candidate packet;
- preserve raw model output;
- emit likely eligible, likely ineligible, or uncertain;
- route positives and uncertain cases to full classification.

### `universe/classification`

Responsibilities:

- apply the multi-axis taxonomy;
- output economic observations with direct evidence;
- preserve multiple archetypes;
- record contradictions and confidence;
- avoid directly hard-coding the final sample.

### `universe/rules`

Responsibilities:

- derive tiers from `configs/universe_sample_rules.yaml`;
- produce machine-readable rule traces;
- allow sensitivity samples without rerunning the LLM;
- version every rule set.

### `universe/review`

Responsibilities:

- create boundary queues;
- store append-only review decisions;
- preserve model and rule outputs;
- require reason codes;
- prevent manual edits from overwriting source evidence.

### `universe/audit`

Responsibilities:

- draw reproducible stratified samples of negatives;
- calculate false-negative estimates;
- evaluate gold, adversarial, and boundary cases;
- block release when hard gates fail.

### `universe/freeze`

Responsibilities:

- generate the immutable universe manifest;
- export identity, classification, firm-year eligibility, and lineage tables;
- compute content hashes;
- prevent downstream use of non-frozen working tables.

## Canonical inputs

```text
configs/project.yaml
configs/universe_taxonomy.yaml
configs/universe_sample_rules.yaml
schemas/company.schema.json
schemas/company_universe_classification.schema.json
schemas/firm_year_eligibility.schema.json
schemas/firm_lineage.schema.json
schemas/universe_run_manifest.schema.json
prompts/discovery/universe_high_recall_screen.md
prompts/discovery/universe_full_classification.md
prompts/adjudication/universe_boundary_adjudication.md
```

## Canonical outputs

```text
data/registry/historical_annual_filers.parquet
data/registry/issuer_filter_decisions.parquet
data/interim/universe_evidence_packets.jsonl
data/interim/universe_screen_predictions.jsonl
data/interim/universe_classifications_raw.jsonl
data/processed/company_universe_classifications.parquet
data/processed/firm_year_eligibility.parquet
data/processed/firm_lineage.parquet
data/registry/companies.parquet
data/manifests/company_universe_manifest.json
```

## Run immutability

Every run writes to a unique directory and records:

- code revision or repository state hash;
- SEC candidate-frame hash;
- cutoff date and form scope;
- packet-builder version;
- prompt, model, schema, taxonomy, and rule hashes;
- deterministic-filter counts;
- screen and classification counts;
- review decisions and negative-audit sampling seed;
- eval report IDs;
- final export hashes.

A rerun never overwrites a prior release.

## Failure handling

- Missing Item 1 becomes a packet failure, not automatic exclusion.
- Unresolved issuer status becomes `unknown` and manual review.
- Invalid model JSON is stored raw and marked failed; it is not silently repaired.
- Evidence after the cutoff blocks the classification record.
- A contradictory packet routes to adjudication.
- A mixed firm with unclear materiality remains uncertain.

## Integration with downstream stages

Stage 01 SEC source discovery receives only a versioned universe export. It may discover additional firm-year sources but cannot alter baseline universe membership.

Product extraction may use Tier A, Tier B, or a named sensitivity sample. Every downstream run records the universe release and sample-rule version.
