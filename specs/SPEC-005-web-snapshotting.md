# SPEC-005 — Web Snapshotting

## Status

Draft

## Objective

Create immutable, dated captures of official web sources.

## Inputs

Official-web candidates.

## Outputs

Raw HTML/PDF snapshots and hashes.

## Governing documents

- `CLAUDE.md`
- `docs/SOURCE_POLICY.md`
- `docs/TEMPORAL_POLICY.md`
- relevant methodology document

## Core rules

- retrieval timestamp
- archive timestamp
- redirect chain
- robots/access failures

## Deterministic validations

- Input IDs and schema versions are present.
- Output validates against the declared JSON schema.
- Source and passage references resolve.
- Observation dates satisfy the temporal policy.
- Original model output and any repair record are preserved.

## Failure modes

- Missing source coverage.
- Invalid or ambiguous dates.
- Unsupported entity or measurement claim.
- Model output that violates schema or evidence requirements.
- Duplicate or conflicting records.

Failures must be emitted to a versioned error table rather than silently skipped.

## Evaluation

Use dedicated gold, adversarial, and regression fixtures. Report precision/recall where a gold set exists, evidence validity, unknown rate, and error taxonomy.

## Acceptance criteria

- Byte hash and metadata for every success
- Historical validity flag for every snapshot

## Run manifest

Every run records code commit, spec version, schema hash, prompt hash, model route, source-manifest hash, timestamps, retry count, and exclusions.

## Open questions

To be resolved during the sentinel pilot and documented in `docs/DECISION_LOG.md`.
