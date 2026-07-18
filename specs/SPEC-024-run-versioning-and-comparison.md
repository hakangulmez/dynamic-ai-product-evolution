# SPEC-024 — Run Versioning and Prompt Comparison

## Status

Draft

## Objective

Ensure every extraction or evaluation run is immutable, reproducible, and comparable with an accepted baseline.

## Run directory

```text
data/runs/<run_id>/
```

Required artifacts:

- run manifest;
- input manifest;
- source packet manifest;
- raw output;
- parsed output;
- repair records;
- deterministic findings;
- evaluation report;
- diff against accepted version.

## Run identity

The run ID must be unique and include a timestamp or generated identifier. Existing directories cannot be overwritten.

## Comparison outputs

- fixed cases;
- new regressions;
- unchanged failures;
- entity additions and removals;
- metric deltas;
- hard-gate changes;
- results by split, failure tag, company, year, and source type.

## Promotion states

- draft;
- candidate;
- accepted;
- frozen;
- deprecated;
- rejected.

## Acceptance criteria

A release decision must link the run, report, change request, prompt hash, schema hash, spec version, and code commit.
