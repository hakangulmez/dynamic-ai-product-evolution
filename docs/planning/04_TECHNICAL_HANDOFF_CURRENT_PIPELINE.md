# Technical Handoff — Current Pipeline State

**Snapshot:** 21 August 2026, after ADR-118 was committed and pushed at
`687b90cf4d98ae8b4e9649375765aea7bf4db9b0`.

## Authority order

For any run claim, verify the named manifest and hashes first, then source,
schemas, tests, and ADRs at the current commit. This file is an orientation aid,
not an authority and not permission to run a command.

## Canonical Stage 00 evidence

| Artifact | Key fact |
|---|---|
| acquisition aggregate | 86 shards; 8,718 planned carrier rows |
| shell determination | 795 true; manifest hash starts `12f76902` |
| asset-backed determination | 351 true; manifest hash starts `a4b2f339` |
| packet corpus | v0.5 manifest hash `516b7020c657a7b656880444e0f98479c1aa46dca80bda9a1beafd846d7d88d8` |
| v5 packet counts | 1,146 union exclusions; 7,572 retained; 7,042 packets; 530 failures |
| live prompt | V5 prompt SHA `fee42d939f9eab590fdcbf055e7b2039e8a33a410dfc12257a47291d7a77d558` |
| failed parent archive | raw-response SHA `08679414440968d9cbb77227fe0d6584803b9841232a6473620d482ad9078c34` |

The full-cohort selection artifact lives under
`data/runs/universe-screen-selections/universe-screen-full-selection-v1-20260820/`.
Its digest is not restated here: a run binds it by SHA in its own
authorization, and that binding is the authority.

The v5 packet manifest is under
`data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819/`.
It binds its aggregate and both determination manifests, contains 86 consumed
shards, and records `item_one_span_v3`.

## High-recall contract state

- ADR-108/109: hash-bound packet authority loader, record and manifest
  contracts, raw archive, and the governed live Vertex route with selection,
  authorization, enablement, endpoint, capture and cap bindings.
- ADR-110/111/113/114: the prompt line ending at **V5**, which shows the model
  short deterministic passage references (`P001`) and asks it to copy a
  contiguous verbatim span, with no source identifier to reproduce.
- ADR-112/115: the diagnostic and seven-row repair routes, both structurally
  non-promotable and refused by the authoritative and promotion loaders.
- ADR-116: the authoritative route records a model-content failure as a
  `model_evidence_unverified` row instead of aborting the cohort. It is a
  review state, not a negative screen result.
- ADR-117: five `generateContent` attempts per row with fixed 15, 30, 60 and
  120 second waits, on the declared transient class including HTTP 429.
- ADR-118: a bounded `countTokens` retry — three attempts at 15 and 30
  seconds — and the governed continuation route described below.

The V5 prompt is what all three current routes render.

## The failed parent run

`data/runs/universe-screens/universe-high-recall-full-v4-20260821/` completed
3,939 of 7,042 rows and stopped at row 3,940 on a 300-second `countTokens`
timeout, which that route sends exactly once.

**This directory cannot be consumed directly.** It holds a failure receipt and
a raw-response archive, and no manifest, records JSONL or capture ledger.
`require_authoritative_screen_run` and `require_promotable_screen_run` both
refuse it, and that refusal is permanent rather than a state to be cleared.
Only a fresh completed continuation manifest can be authoritative.

What the directory does hold is usable evidence, but only through the
continuation route, which revalidates every reused response against its packet
with the unchanged strict validator rather than trusting that the parent once
accepted it.

## Safe next operation

Two separately authorized steps, in this order.

First, materialize a fresh continuation governance pair: an enablement and a
`universe_screen_continuation_authorization@0.1.0` grant binding the named
failed run by its receipt and archive digests, the parent grant it ran under,
the canonical v5 packet manifest, the full-cohort selection, the V5 prompt
bytes, the provider contract and endpoints, and a whole-cohort
model-evidence breaker. The send ceilings are derived from the remaining
suffix rather than stated, and the runner re-derives and refuses drift.

Second, run the explicit continuation CLI mode
(`--mode screen-universe-lineage-continuation`), which requires the source run
directory and its pinned receipt digest to be named on the command line. There
is no discovery, no globbing and no "latest failed run" behaviour.

No command line is given here, and neither step is performed by reading this
file. Afterward, verify the new manifest's schema, its output and capture
hashes, the record partition across reused and model-called rows, the
byte-identical archive prefix, the request accounting, and the reconciliation
block before treating anything as a release candidate.

## Handoff rules

- Never reuse a run identifier or a failed authorization for another run.
- Never consume a receipt-bearing directory as a screen release.
- Do not change prompts, validators, schemas, or provider code while a run is
  active.
- Keep implementation, staging, commit, push, governance materialization, and
  live execution as separate approvals.
- PCT Dev30 begins only after `UNIVERSE_v1` is frozen; no high-recall result is
  a PCT result.
