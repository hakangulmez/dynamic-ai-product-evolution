# SPEC-025 — Local Research Review Console

## Status

Draft

## Objective

Provide a local Streamlit application for reviewing evaluation failures and production extraction records without editing canonical files manually.

## Phase 1 pages

1. Eval overview.
2. Failure review.
3. Run comparison.
4. Production review queue.

## Inputs

- evaluation reports;
- run manifests;
- prediction and expected records;
- source passages;
- existing review database.

## Outputs

Append-only SQLite review records and exportable review summaries.

## Required decisions

- approve prediction;
- approve gold;
- both acceptable;
- edit expected;
- ambiguous source;
- ontology question;
- insufficient evidence;
- promote to regression.

## Non-negotiable rules

- never mutate raw sources;
- never overwrite predictions;
- never overwrite gold cases;
- require reviewer, timestamp, reason code, and case/run linkage;
- keep financial outcomes hidden during extraction and measurement review;
- run locally without authentication in the first version.

## Acceptance criteria

- one-command local launch;
- review persistence tests;
- side-by-side source, prediction, and expected view;
- filters for company, date, prompt version, failure tag, and split;
- run comparison displays fixed and regressed cases;
- non-developer usage documentation.
