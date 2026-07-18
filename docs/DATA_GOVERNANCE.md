# Data Governance

## Data zones

- `raw/`: immutable downloaded files and HTML.
- `snapshots/`: dated, hashed web captures.
- `normalized/`: cleaned text with passage IDs.
- `interim/`: model candidates and unresolved matches.
- `processed/`: validated released observations.
- `manifests/`: source, run, and schema provenance.

## Immutability

Raw and snapshot files are content-addressed. A changed source creates a new object; it does not overwrite the old one.

## Provenance chain

Every released task must be traceable through:

```text
task observation
  → capability observation
  → product observation
  → source passage
  → normalized document
  → raw snapshot
  → retrieval manifest
```

## Versioning

Version independently:

- source corpus;
- normalization pipeline;
- product/capability/task schemas;
- prompts;
- model route;
- gold data;
- measurement rubric;
- aggregation method.

## Reproducibility package

A release should include:

- source manifest with URLs and hashes;
- schema versions;
- prompt hashes;
- model-run manifests;
- deterministic validators;
- exclusion and repair logs;
- evaluation report;
- code commit.

## Sensitive information

The project uses public company materials. Do not collect personal data beyond names already contained in official public filings when not required for the research question.
