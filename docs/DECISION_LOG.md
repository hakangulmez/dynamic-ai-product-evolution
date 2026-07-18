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

## ADR-009 — Mixed nonseparable firms are not Tier B

**Decision:** `MIXED_SEPARABLE` firms may enter Tier B when the other Tier B conditions hold. `MIXED_NONSEPARABLE` firms may not enter Tier B; they route to the Tier C boundary stratum or remain unresolved in manual review. `universe_sample_rules.yaml` 0.2.0 removes `MIXED_NONSEPARABLE` from the Tier B candidate structures.

**Rationale:** A mixed nonseparable firm can have material product-level software activity, but its firm-level outcomes cannot be cleanly mapped to that activity. Keeping such firms in the extension sample would silently blend unattributable outcomes into mechanism comparisons. The classifier's advisory tier remains non-authoritative.

## ADR-010 — Screen-derived exclusions are provisional until the negative audit completes

**Decision:** Deterministic issuer exclusions (fund, trust, asset-backed, shell/pre-combination SPAC, unsupported form, duplicate record) are definitive when evidenced. A high-recall screen result of `LIKELY_INELIGIBLE` is stored as a provisional, screen-derived exclusion with explicit provenance, enters the stratified negative-audit pool, and cannot be presented as a confirmed exclusion in a frozen universe until its audit record exists. Negative-audit completion is a freeze hard gate.

**Rationale:** The screen is a recall-optimized model pass, not a membership decision. Without an audit gate, first-pass negatives would silently define the sample boundary — the exact failure mode SPEC-001 lists under "prompt output silently defines the sample."

## Open decisions

- Exact baseline cutoff, first-release form scope, and final Tier A/Tier B thresholds after the universe sentinel.
- Filing-date versus fiscal-year observation convention.
- Required source packet by firm-year.
- Frontier-registry granularity.
- Gold-set size and expert-review protocol.
- Whether third-party sources receive a bounded validation-only role.
