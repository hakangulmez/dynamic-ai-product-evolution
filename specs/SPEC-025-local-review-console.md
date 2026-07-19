# SPEC-025 — Local Research Review Console

## Status

Draft

## Objective

Provide a local Streamlit application for reviewing evaluation failures and production extraction records without editing canonical files manually.

## Phase boundary

Console implementation is a Phase 2+ explicit slice. Phase 1 may include only the underlying data models and interface stubs (review records, membership-change events, exposure events, dispositions). This specification remains the binding contract for the eventual implementation.

## Initial pages

1. Eval overview.
2. Failure review.
3. Run comparison.
4. Production review queue.

## Inputs

- evaluation reports;
- run manifests;
- case-set manifests;
- prediction and expected records;
- source passages;
- finding dispositions;
- exposure log;
- existing review database.

## Outputs

Append-only SQLite review records, membership-change events, exposure events, and exportable review summaries.

## Required decisions

- approve prediction;
- approve gold;
- both acceptable;
- edit expected — creates a new case or case-set version; originals remain unchanged;
- ambiguous source;
- ontology question;
- insufficient evidence;
- promote to regression — a versioned suite-membership event; it does not change the case's partition and does not verify the case (ADR-014).

## Review-decision boundary

- SPEC-024 and the change-control protocol define the semantics and allowed transitions of `accept_candidate`, `accept_with_documented_nonblocking_tradeoff`, `revise`, and `reject`.
- The console may provide an interface that records append-only human review-decision events.
- The console cannot redefine the decision vocabulary, alter gate arithmetic, override a blocking failure, or advance the prompt lifecycle automatically (ADR-018, ADR-019).

## Non-negotiable rules

- never mutate raw sources;
- never overwrite predictions;
- never overwrite gold cases;
- require reviewer, timestamp, reason code, and case/run linkage;
- frozen case-level views require a recorded purpose and produce typed exposure events; aggregate views are the default (ADR-015);
- raw validator results and disposition-enriched review views are presented separately; the review view never replaces the raw view (ADR-018);
- severity is not editable in the console (ADR-018);
- keep financial outcomes hidden during extraction and measurement review;
- local-only operation is permitted; local deployment never bypasses identity, purpose, or exposure controls;
- aggregate views remain the default;
- frozen case-level, source-packet, prediction, gold, or adjudication detail requires an authorized actor identity, a recorded purpose, and an append-only exposure event (ADR-015);
- the eventual implementation may use a lightweight local identity mechanism, but it cannot provide anonymous frozen-detail access.

## Acceptance criteria

- one-command local launch;
- review persistence tests;
- exposure-event and membership-change event persistence tests;
- side-by-side source, prediction, and expected view;
- filters for company, date, prompt version, failure tag, partition, and suite;
- run comparison displays fixed and regressed cases;
- non-developer usage documentation.

## Revision history

- 2026-07-19 — Revised per ADR-014, ADR-015, ADR-018, ADR-019 and the Phase 1 boundary: exposure-logged frozen access, append-only review-decision events and boundary, partition/suite filters, membership-event semantics, Phase 2+ implementation scoping.
