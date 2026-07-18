# Decision Log

## ADR-001 — Clean-room repository

**Decision:** Build the longitudinal project in a new repository without importing legacy artifacts.

**Rationale:** The research question and data structure changed materially. Isolation prevents old scores and taxonomies from steering extraction.

## ADR-002 — Separate extraction from measurement

**Decision:** Product, capability, and task extraction will not score replicability, adoption, or defensibility.

**Rationale:** Measurement assumptions should not determine what observations are preserved.

## ADR-003 — Official, dated sources only for the canonical corpus

**Decision:** Use SEC and official company sources under a fixed hierarchy, with historical snapshots.

**Rationale:** This balances richer product evidence with reproducibility and temporal validity.

## ADR-004 — AI wording is not evidence of depth

**Decision:** AI language identifies candidate passages but does not produce a measurement value without concrete actions and deployment evidence.

## ADR-005 — Task-year is the central measurement level

**Decision:** Aggregate only after task-level validation.

## ADR-006 — No immediate commitment to a single score

**Decision:** Preserve separate measurement families and defer any composite score until pilot construct validation.

## ADR-007 — Multi-axis firm-universe classification

**Decision:** Construct the universe from the historical SEC annual-filer frame and classify firms separately by customer-value archetype, software centrality, complementary dependencies, and firm structure/materiality. Derive Tier A/B/C samples through versioned deterministic rules.

**Rationale:** A binary software label conflates functional software with marketplaces, content catalogues, physical services, hardware systems, and human-managed services. Separate axes preserve economic mechanisms and permit transparent sensitivity samples.

## ADR-008 — Ex-ante baseline cohort and negative audit

**Decision:** Baseline membership uses only pre-cutoff evidence; later outcomes cannot affect inclusion. Post-baseline entrants form a separate cohort, exited incumbents are retained, and a stratified sample of first-pass negatives must be audited before universe freeze.

**Rationale:** These rules reduce post-treatment selection, survivorship bias, and unobserved false-negative screening.

## Open decisions

- Exact baseline cutoff, first-release form scope, and final Tier A/Tier B thresholds after the universe sentinel.
- Filing-date versus fiscal-year observation convention.
- Required source packet by firm-year.
- Frontier-registry granularity.
- Gold-set size and expert-review protocol.
- Whether third-party sources receive a bounded validation-only role.
