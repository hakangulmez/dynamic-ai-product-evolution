# SPEC-022 — Evaluation Case and Review Data Model

## Status

Draft

## Objective

Define stable, versioned structures for evaluation cases, expected entities, deterministic findings, human reviews, and prompt-release decisions.

## Inputs

- source and passage registries;
- stage output schemas;
- gold annotations;
- model predictions;
- failure taxonomy;
- review decisions.

## Outputs

- evaluation-case records;
- structured findings;
- append-only review records;
- prompt-release records.

## Evaluation case fields

Required:

- `case_id`
- `stage`
- `split`
- `company_id`
- `observation_date`
- `input_source_ids`
- `input_passage_ids`
- `expected_entities`
- `forbidden_entities`
- `expected_status`
- `failure_tags`
- `notes`
- `created_by`
- `created_at`
- `guideline_version`

## Entity identity

Expected entities use stable gold IDs and may define accepted aliases. Textual labels alone are not stable identifiers.

## Review immutability

Human review records are append-only and contain original and revised values. Original predictions and original gold records remain unchanged.

## Validation

- unique case IDs;
- known split and stage values;
- valid dates;
- source and passage resolution;
- compatible schema versions;
- valid failure tags;
- no unresolved required fields.

## Acceptance criteria

- every case validates;
- cases can be loaded without stage-specific custom parsing;
- review history is reconstructable;
- original records remain recoverable.
