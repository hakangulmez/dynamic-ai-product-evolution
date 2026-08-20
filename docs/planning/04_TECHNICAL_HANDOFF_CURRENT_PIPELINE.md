# Technical Handoff — Current Pipeline State

**Snapshot:** 20 August 2026, after ADR-112 was committed and pushed at
`ca7538bf07a4a853f740db204071701c3c020f6d`.

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
| selection | `canary_100`, SHA `26bd88052a4efd9c8b5580411c7fd9a2054d27314bae277799a0a7a0a4b0d570` |
| live prompt | v3 prompt SHA `1d371255d9b650bd5ff6ffd1d58d6a42b649436cfbcaf905bf3e53c5a7a58c78` |

The v5 packet manifest is under
`data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819/`.
It binds its aggregate and both determination manifests, contains 86 consumed
shards, and records `item_one_span_v3`.

## High-recall contract state

- ADR-108: hash-bound packet authority loader, mock route, record/manifest
  contracts, raw archive, all-or-nothing authoritative semantics.
- ADR-109: separate live provider composition route with selection,
  authorization, enablement, endpoint, capture, and cap bindings.
- ADR-110: prompt v2 enumerated the closed archetype vocabulary.
- ADR-111: prompt v3 requires exact separate source/passage identifiers and a
  contiguous verbatim quote from the cited passage.
- ADR-112: diagnostic-only canary successor; same validator, diagnostic rows
  for output failures, separate authorization, non-promotable outputs, and a
  25-rejection breaker.

The authoritative route is still all-or-nothing. The diagnostic route is not a
shortcut to SCREEN_v1 and its manifest/records are structurally refused by the
authoritative and promotion loaders.

## Safe next operation

Use a fresh diagnostic governance root containing the separate diagnostic
authorization. Bind the canonical v5 manifest, the selection SHA, prompt v3
SHA, provider contract/endpoints, and the declared 100/300/400 request caps
plus `max_rejected_rows: 25`. Run a fresh diagnostic identifier exactly once.

Afterward, verify its schema, output/capture hashes, row partition,
validated/rejected reason distribution, token/cost accounting, and receipt or
manifest path. Only then decide whether the prompt can advance to a new
authoritative canary.

## Handoff rules

- Never reuse a run identifier or a failed authorization for another run.
- Never consume a receipt-bearing directory as a screen release.
- Do not change prompts, validators, schemas, or provider code while a run is
  active.
- Keep implementation, staging, commit, push, governance materialization, and
  live execution as separate approvals.
- PCT Dev30 begins only after `UNIVERSE_v1` is frozen; no high-recall result is
  a PCT result.
