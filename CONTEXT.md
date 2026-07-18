# Domain Context

Canonical glossary for the Dynamic AI Product Evolution project. This file is
the shared vocabulary only.

- `CONTEXT.md` is the shared glossary, nothing else.
- Methodology lives in `docs/methodology/`.
- Binding contracts live in `specs/`.
- Decisions live in `docs/DECISION_LOG.md`.
- On any conflict, the canonical source governs, not `CONTEXT.md`.

## Language

**Company Universe**:
The dated, evidence-backed set of eligible SEC annual filers constructed and
classified before any product, capability, or task extraction.

**Baseline Firm**:
A firm whose last eligible annual filing falls on or before the project
baseline cutoff; a member of the ex-ante incumbent cohort.

**Post-Baseline Entrant**:
A firm that first becomes an eligible public filer after the baseline cutoff.
Stored in a separate entrant cohort, outside the baseline tier denominator.

**Evidence Packet**:
A compact, passage-addressable set of baseline-dated SEC passages used to
classify one firm. A packet may never contain post-cutoff evidence.

**Customer-Facing Product**:
An externally offered product or service that customers purchase. Internal
software or AI use does not create a customer-facing product.

**Customer-Facing Task**:
A functional outcome that the customer uses the product to accomplish.

**Customer Value Archetype**:
The multi-label economic axis describing what the customer is fundamentally
purchasing, restricted to the canonical codes in the universe taxonomy.

**Software Centrality**:
The axis describing how software contributes to the customer outcome:
CORE, CO_ESSENTIAL, ENABLING, PERIPHERAL, or UNKNOWN.

**Complementary Dependency**:
An asset required to deliver the customer task, such as licensed data or a
physical supply network. A dependency is not, by itself, defensibility.

**Frontier Task Replicability**:
The extent to which a frontier general-purpose model can reproduce the
customer-facing task under a specified model-year contract.

**AI Transformation Depth**:
The extent to which AI changes the product's workflow architecture, rather
than merely adding a surface-level feature.

**Deterministic Issuer Exclusion**:
A definitive, evidenced exclusion produced by deterministic issuer rules
(fund, trust, asset-backed issuer, shell or pre-combination SPAC,
unsupported filing form, duplicate issuer record).

**Screen-Derived Exclusion**:
A provisional exclusion produced by the high-recall screen that remains
subject to the negative-audit gate.

**Negative Audit**:
A seeded, reproducible, stratified human review of first-pass negatives used
to estimate false-negative risk. Its completion is a universe-freeze gate.

**Boundary Adjudication**:
An append-only human review that resolves a disputed classification without
overwriting the raw screen, classifier output, or rule trace.

**Universe Freeze**:
The versioned release of the company universe, permitted only after all hard
gates pass and recorded in an immutable run manifest.
