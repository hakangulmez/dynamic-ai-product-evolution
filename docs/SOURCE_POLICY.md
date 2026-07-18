# Source Policy

## Purpose

Define a standardized, reproducible, and auditable source universe for each firm-date observation.

## Canonical source hierarchy

### Tier 1 — SEC sources

- 10-K / 20-F / annual report
- 10-Q / 6-K when relevant
- 8-K and filed exhibits
- earnings-release exhibits
- investor-presentation exhibits
- registration filings when required for newly public firms

### Tier 2 — Official investor-relations sources

- earnings releases and presentations
- investor-day presentations
- prepared remarks
- official financial supplements

### Tier 3 — Official product sources

- product and solution pages
- pricing pages
- official product comparison pages
- official release notes

### Tier 4 — Official technical sources

- developer documentation
- API documentation
- architecture guides
- administration and implementation documentation
- security, governance, or model cards published by the firm

### Tier 5 — Official newsroom and blog

Used for dated launches, general availability, partnerships, and feature descriptions when higher-tier sources are silent.

### Tier 6 — Archived official pages

Used only when a valid historical snapshot is available and provenance is recorded.

## Excluded from the canonical extraction corpus

Unless a later accepted spec creates a narrow validation role:

- Wikipedia;
- press coverage;
- analyst reports;
- review sites;
- social-media posts;
- unsourced search snippets;
- current pages used to reconstruct past states without an archive date.

## Source-role separation

Different sources answer different questions.

| Source | Primary role |
|---|---|
| Annual filing Item 1 | yearly product/task universe and strategy |
| 10-Q / 8-K | intra-year launches, acquisitions, availability |
| Product page | customer-facing capability and product packaging |
| Developer docs | execution, tools, APIs, workflow integration |
| Release notes | first-seen date and general availability |
| Pricing page | commercialization and plan inclusion |
| MD&A / earnings | scale, customer metrics, financial context |
| Risk factors | stated dependencies and disruption risks |

## Evidence hierarchy within an observation

When sources conflict:

1. Prefer specific dated operational evidence over general narrative.
2. Prefer generally available product documentation over roadmap language.
3. Preserve conflicting evidence and mark ambiguity rather than silently choosing.
4. Do not let a later source rewrite the historical state.

## Discovery completeness

Source discovery is considered complete only when the manifest records:

- searched source categories;
- successful and failed retrievals;
- exclusion reasons;
- snapshot dates;
- content hashes;
- deduplication decisions.


## Baseline universe eligibility

The baseline company-universe decision uses dated SEC annual-filing and issuer evidence. Official product pages, developer documentation, newsroom materials, and later filings enrich downstream product observations but do not determine pre-cutoff incumbent membership. Any exception requires an accepted spec and a temporally valid archived official source.
