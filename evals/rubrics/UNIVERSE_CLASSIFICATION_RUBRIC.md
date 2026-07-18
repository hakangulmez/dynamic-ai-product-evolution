# Universe Classification Evaluation Rubric

## Scope

Evaluate Stage 00 screening, multi-axis classification, deterministic tier derivation, boundary adjudication, and negative-sample audit.

## Gold dimensions

Each gold case records:

- operating-company status;
- baseline evidence sufficiency;
- customer-value archetype(s);
- software centrality;
- necessary complementary dependencies;
- firm structure;
- commercial materiality;
- economic eligibility;
- data eligibility;
- expected tier or acceptable tier set;
- mandatory boundary flags;
- prohibited claims;
- evidence passages.

## Screen metrics

- recall of potentially Tier A or Tier B firms;
- false-negative rate by archetype;
- uncertain routing rate;
- unsupported positive-screen rate;
- evidence validity and temporal validity.

High-recall screening is not judged primarily by final precision. Boundary cases should be retained rather than confidently excluded.

## Full-classifier metrics

- exact and partial agreement for multi-label archetypes;
- centrality accuracy;
- dependency precision/recall;
- firm-structure accuracy;
- materiality accuracy;
- economic/data eligibility agreement;
- candidate-tier agreement;
- evidence support rate;
- unknown calibration;
- contradiction detection.

## Boundary-case error tags

- `DIGITAL_INTERFACE_FALSE_POSITIVE`
- `INTERNAL_SOFTWARE_FALSE_POSITIVE`
- `MARKETPLACE_AS_FUNCTIONAL_SOFTWARE`
- `CONTENT_CATALOG_AS_ANALYTICS`
- `HUMAN_SERVICE_AS_SOFTWARE`
- `HARDWARE_DEPENDENCY_IGNORED`
- `DATA_INPUT_VS_CONTENT_CONFUSION`
- `TRANSACTION_RAIL_IGNORED`
- `MIXED_FIRM_MATERIALITY_ERROR`
- `CURRENT_KNOWLEDGE_LEAKAGE`
- `SIC_SHORTCUT`
- `UNKNOWN_FORCED`
- `EVIDENCE_UNSUPPORTED`
- `DUPLICATE_ISSUER`
- `SURVIVORSHIP_SELECTION`

## Hard gates

The run fails on any:

- post-cutoff evidence;
- fabricated quote;
- evidence-free inclusion;
- fund, shell, or non-operating Tier A record;
- duplicate CIK in the frozen identity table;
- unknown coerced into include/exclude;
- silent loss of an exited baseline firm;
- missing deterministic rule trace;
- missing universe manifest.

## Negative audit

The likely-ineligible population is sampled with a recorded random seed and explicit strata. Report:

- sample size by stratum;
- eligible or boundary firms discovered;
- estimated false-negative rate and uncertainty;
- failure classes;
- whether screen changes are required before freeze.

## Release decision

A release report must state:

- fixed and newly introduced errors versus the prior version;
- per-archetype metrics;
- boundary reviewer agreement;
- negative-audit results;
- hard-gate status;
- unresolved limitations;
- accept, reject, or remain-sentinel decision.
