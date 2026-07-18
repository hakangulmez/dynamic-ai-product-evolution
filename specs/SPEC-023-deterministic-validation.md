# SPEC-023 — Deterministic Validation Layer

## Status

Draft

## Objective

Implement non-model checks that must run before semantic evaluation or human review.

## Required validators

1. Output JSON/schema validity.
2. Required-field presence.
3. Source ID resolution.
4. Passage ID resolution.
5. Evidence quote occurs in cited passage.
6. Publication date is not later than observation cutoff.
7. Product–capability–task parent links resolve.
8. IDs are unique within the declared scope.
9. Prohibited legacy fields are absent.
10. Active records are not supported only by future-roadmap evidence.
11. Customer-facing tasks have a customer outcome and evidence.
12. Raw model output and any repair record are preserved.

## Finding structure

Each validator returns:

```yaml
finding_id:
validator:
severity:
status:
run_id:
case_id:
entity_id:
message:
evidence:
repairable:
```

Validators must not silently fix data.

## Severity

- `critical`: blocks release;
- `error`: invalidates the entity or case;
- `warning`: requires review;
- `info`: diagnostic only.

## Acceptance criteria

- critical findings produce a failing exit status;
- findings are machine-readable;
- all validators have unit tests;
- the runner reports failures without dropping records.
