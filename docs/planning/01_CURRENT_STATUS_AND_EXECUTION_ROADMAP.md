# Current Status and Execution Roadmap

## Thesis objective

The thesis constructs a dated, evidence-grounded panel of how software firms'
customer-facing products, capabilities, and tasks evolve during the frontier-LLM
transition. Its eventual analytical unit is:

```text
economic firm × fiscal year × product × capability × customer-facing task
```

The raw evidence layer remains deliberately finer:

```text
CIK × accession × carrier row
```

The project is not an AI-keyword-count exercise and does not assign a permanent
AI label to a firm. It first builds admissible dated evidence, then product-task
observations, then links and measurements, and only finally studies outcomes.

## Completed governed evidence

| Component | Current result | Authority |
|---|---:|---|
| SEC primary acquisition lineage | 86 shards; 8,718 carrier rows | named acquisition aggregate manifest |
| Shell-company determination | 795 `true`; false/unknown retained | ADR-102 lineage artifact |
| Asset-backed determination | 351 `true`; 8,367 `unknown`; zero shell overlap | ADR-105/106 lineage artifact |
| Union exclusion | 1,146 excluded; 7,572 retained | ADR-107 v0.5 packet manifest |
| Canonical Item 1 corpus | 7,042 packets + 530 governed failures | v5 manifest `516b7020…` |
| Locator recovery | 82 bounded combined-heading recoveries; prior qualifying spans unchanged | ADR-104 acceptance replay |
| High-recall infrastructure | mock runner, governed Vertex route, output budget, prompt successors, and diagnostic runner implemented | ADR-108–112 |

The canonical packet build uses `item_one_span_v3`. It does not make a
software-eligibility judgment: it supplies the frozen Item 1 evidence surface
for that later judgment.

## What the high-recall work has established

Three all-or-nothing authoritative canaries were informative, but by design did
not yield a screen release:

1. The first stopped on an undeclared archetype label, leading to the closed
   archetype vocabulary prompt successor (ADR-110).
2. The second stopped when the model merged the two header identifiers in a
   citation, leading to explicit identifier/quote instructions (ADR-111).
3. The third completed 27 clean rows and stopped on row 28. The rejected quotes
   were not fabricated: they existed verbatim in different passages of the
   same Item 1 packet. The failure was passage attribution, which the strict
   `(source_id, passage_id, quote)` validator correctly refused.

ADR-112 adds a separate, structurally non-promotable diagnostic canary. It uses
the same strict row validator but records the four model-output failures
(`invalid_model_json`, `adapter_rejection`, `quote_resolution_failure`, and
`temporal_violation`) as diagnostic rows. Governance, binding, capture,
provider, envelope, cap, budget, and circuit-breaker failures remain hard stops.
Its purpose is to measure the 100-row distribution without weakening the
authoritative SCREEN path.

## Required execution order

1. Maintain the plan pack and Stage 00 reproducibility notebook.
2. Materialize fresh diagnostic governance binding the v3 prompt, canonical v5
   packet manifest, and existing 100-row selection.
3. Run one diagnostic canary under its separate authorization; inspect the
   validated/rejected distribution and cost evidence.
4. Decide whether the prompt/evidence representation needs another measured
   successor. Do not use diagnostic rows as SCREEN output.
5. Run a new authoritative canary only after its acceptance criteria are met.
6. Perform the full 7,042-packet high-recall screen only after a separately
   authorized successful canary and human negative/boundary audits.
7. Freeze `SCREEN_v1`, implement the full classifier successor, derive tiers
   deterministically, and freeze `UNIVERSE_v1`.
8. Only then decide PCT sample/census and Dev30 instrument validation.

## Later gates

| Gate | Deliverable | Status |
|---|---|---|
| B | high-recall screen, classifier, deterministic tiers, `UNIVERSE_v1` | in progress |
| C | PCT Dev30 validation and production design | deferred until `UNIVERSE_v1` |
| D | multi-date source panel | proposal |
| E | product/capability/task extraction | proposal |
| F | longitudinal matching and transition labels | proposal |
| G | frontier/AI-transition measurement and aggregation | proposal |
| H | outcome panel and econometric analysis | proposal |

## Operating principles

- Preserve predecessors byte-for-byte; add governed successors rather than
  changing historical meaning under an existing name.
- Treat failed runs as immutable evidence, never as inputs to a release.
- Bind every live model run to exact packet, prompt, selection, route,
  endpoint, authorization, cap, and capture evidence.
- Unknown and insufficient evidence are visible outcomes, not negative labels.
- Do not refactor working provenance paths while the high-recall instrument is
  under calibration. Maintenance refactors follow a release, not precede it.
