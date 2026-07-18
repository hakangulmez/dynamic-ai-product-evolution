# Failure Recovery

## Retrieval failures

- Retry with exponential backoff.
- Preserve HTTP status and response headers.
- Do not substitute an unofficial mirror automatically.
- Escalate archive retrieval separately.

## Parsing failures

- Store raw bytes and parser error.
- Try an alternate parser under a new normalizer version.
- Never OCR unless no text representation exists and the source is important.

## Model failures

- Invalid JSON: deterministic repair only for syntax, with original output preserved.
- Schema violation: reject and retry; do not coerce semantic values silently.
- Evidence mismatch: quarantine observation.
- Context truncation: split by product sections or source groups and record composition.

## Matching failures

Ambiguous matches remain unresolved. Do not force one-to-one continuity.

## Rollback

Every processed release points to immutable source and run manifests, allowing a prior dataset version to be reconstructed.
