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

**Evaluation Case**:
One evaluation invocation of a single pipeline stage over one immutable,
bounded input packet, together with its stage-specific typed context and
its assertions.

**Assertion**:
The atomic scoring unit inside an evaluation case: an expected or forbidden
entity, a required field value, an evidence or provenance requirement, or a
deterministic-validation expectation.

**Evaluation Run**:
An immutable execution of the evaluation harness over a case set and a
prediction set; the unit at which aggregate metrics and hard gates are
computed.

**Prediction Envelope**:
The canonical, stage-agnostic form into which production or fixture outputs
are adapted before scoring, preserving record identity, source references,
and run provenance.

**Case-Set Manifest**:
The versioned record that fixes case membership and pins the registry
snapshot and resolved input-packet hashes for a case set.

**Case-Set Snapshot**:
A released, hash-identified version of a case set. Frozen status is a
property of the snapshot, not of an individual gold record.

**Gold Origin**:
How a gold label was produced: constructed together with a synthetic
packet, annotated by a human from a real source packet, or imported from an
external reference with preserved provenance.

**Verification Status**:
Whether a gold label has passed a documented second verification
(`verified`) or not (`provisional`); the verification method is recorded
separately.

**Evaluation Partition**:
The mutually exclusive usage assignment of a case within a case-set
version: development or frozen test.

**Evaluation Suite**:
A non-exclusive role tag on a case, such as adversarial or regression; a
case may hold several suite memberships at once.

**Exposure Event**:
A typed, append-only record of any access to frozen-case information, from
aggregate metrics to gold detail, with its purpose and actor.

**Ever-Exposed**:
Permanent provenance marking that a case's prediction or gold detail was
seen during tuning or diagnosis; such a case can no longer serve as a blind
frozen case.

**Unsafe Exclusion**:
A screen-negative decision for a firm that is actually eligible or
boundary-relevant; the screen's primary scientific error.

**Pass-Through Burden**:
The downstream review load created by firms the high-recall screen declines
to exclude; an operational cost, not a false-positive rate.

**Tier-Consequential Error**:
A classification error that changes the deterministically derived tier
under a fixed tier-rule version.

**Validator Finding**:
The immutable, reproducible result of one validator rule from one validator
bundle applied to one artifact.

**Finding Disposition**:
An append-only human judgment attached to a validator finding; it never
alters the finding or the gate arithmetic.

**Evaluation Execution Status**:
Whether an evaluation run completed, was invalid, or errored; invalid and
errored runs carry no verdict about the candidate under evaluation.

**Gate Verdict**:
The outcome of a computed gate: pass, fail, or indeterminate when verified
support is insufficient.

**Comparison Artifact**:
An immutable, deterministic record derived from a baseline evaluation run,
a candidate evaluation run, and a versioned comparison contract.

**Qualification**:
A versioned record binding a specific prompt artifact, execution/routing
contract, and stage/output contract to an evaluation scope and qualification
status. Qualification does not transfer across execution-affecting contract
changes.

**Adapter Enablement**:
The versioned operational permission for an adapter in a given environment
and rollout scope, distinct from code availability, qualification, and
per-run authorization.
