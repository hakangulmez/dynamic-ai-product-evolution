# Evaluation Cases

Case files stored here are immutable, partition- and suite-agnostic records:
an evaluation case does not own its split. Partition and suite membership is
owned by the authoritative, versioned, append-only case-set manifest
(ADR-014):

- partition (exactly one per case per case-set version): `dev`,
  `frozen_test`;
- suites (zero or more; suites may overlap): for example `adversarial`,
  `regression`.

The subdirectories here are authoring organization only and are not
authoritative for membership. Frozen case-set snapshots are immutable;
membership changes create a new case-set version. Detailed case or gold
exposure contaminates blind frozen use; a contaminated case moves to `dev` in
a later case-set version (ADR-015). No silent approval and no silent
frozen-set mutation is permitted. The concrete manifest layout is deferred to
implementation planning.

Use `evals/templates/eval_case.template.json`, follow `SPEC-022`, and
validate against `schemas/evaluation_case.schema.json`.
