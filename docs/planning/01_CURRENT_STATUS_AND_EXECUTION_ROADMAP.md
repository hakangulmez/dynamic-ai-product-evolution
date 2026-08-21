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
| High-recall instrument | V5 prompt, governed live route, evidence-safe records, long generate backoff, bounded countTokens retry, and a continuation route | ADR-108–118 |
| High-recall result | none yet: no authoritative screen manifest exists | absence of any `universe_screen_manifest.json` under `data/runs/universe-screens/` |

The canonical packet build uses `item_one_span_v3`. It does not make a
software-eligibility judgment: it supplies the frozen Item 1 evidence surface
for that later judgment.

## What the high-recall work has established

Eleven accepted decisions have built the instrument, each one answering a
defect the previous run measured rather than a defect that was anticipated.
Three early all-or-nothing canaries failed on an undeclared archetype label, on
two merged header identifiers in a citation, and on passage attribution, and
produced the closed-vocabulary and evidence-identity prompt successors
(ADR-110, ADR-111). A structurally non-promotable diagnostic canary was added
so a run could measure the distribution of model-output failures instead of
stopping at the first one (ADR-112), and short deterministic passage references
replaced opaque hashes in the model-facing prompt (ADR-113, ADR-114), with a
seven-row repair measurement to check the change (ADR-115). The authoritative
route then gained an evidence-safe record kind, so a model-content failure
becomes a visible `model_evidence_unverified` row rather than aborting a cohort
(ADR-116), and a long 429 backoff of five attempts at 15, 30, 60 and 120
seconds (ADR-117).

### The current high-recall state, precisely

The V5 prompt and the governed live screen successors exist and are committed.
A full-cohort V3 run then completed a **verified reusable prefix of 3,939 of
the 7,042 rows** before stopping at row 3,940 on an un-retried 300-second
`countTokens` timeout. That call was a single send by design at the time, so
the run behaved exactly as authorized; the cost was that 3,939 finished rows
had no artifact to live in.

The failed parent run remains immutable and non-authoritative. It holds a
failure receipt and a raw-response archive, no manifest, no records and no
capture ledger, and both the authoritative and promotion loaders refuse the
directory outright.

ADR-118 provides the governed continuation route. It revalidates that prefix
from the parent's hash-bound archive — re-rendering each prompt and re-running
the unchanged strict validator, so a reused row is held to the same standard as
a fresh one — and model-calls only the remaining suffix. It also bounds the
`countTokens` call at three attempts with 15 and 30 second waits, which is the
failure that stopped the parent.

Offline revalidation under ADR-118 confirms the prefix is intact: every
response re-hashes, the archive maps in order onto a contiguous prefix of the
selection, and 295 of the 3,939 rows revalidate as `model_evidence_unverified`
rather than as screened rows. No screen-status distribution is reported here,
because a status mix may only be read from a manifest that reconciled a whole
cohort, and no such manifest exists.

## Required execution order

1. Materialize fresh continuation governance: an enablement and a continuation
   authorization binding the named failed run by receipt and archive digest,
   the canonical v5 packet manifest, the full-cohort selection, the V5 prompt
   bytes, and a whole-cohort model-evidence breaker sized to measured reality.
2. Run only the governed continuation suffix. The 3,939 reused rows are
   revalidated offline and are never re-sent.
3. Verify the resulting full 7,042-row manifest and its reconciliation: the
   record partition, the reused and model-called populations, the byte-identical
   archive prefix, the output and capture hashes, and the request accounting.
4. Perform the high-recall release audits, including human review of negative
   and boundary rows.
5. Freeze `SCREEN_v1`.
6. Implement and run the classifier successor.
7. Derive deterministic tiers and freeze `UNIVERSE_v1`.
8. Only then decide the PCT sample or census and Dev30 instrument validation.

Steps 1 and 2 are separate approvals, as is every governance materialization
and every live run.

## Visible uncertainty

Two populations are recorded rather than silently removed, and neither is an
exclusion:

- **530 `INSUFFICIENT_EVIDENCE` rows** — retained carrier rows whose Item 1
  packet could not be built. No model call was made for any of them, and they
  carry a null filing date and null screen status by contract.
- **`model_evidence_unverified` rows** — rows whose packet was model-called and
  whose verbatim response is archive-bound, but where one closed validation
  condition failed. This is a review state, never a negative screen result and
  never a sample exclusion; a firm with such a row cannot be treated as
  firm-negative by the roll-up rule.

Both remain visible in the eventual release so that a later reader can see the
shape of what was not established, rather than inferring it from an absence.

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
