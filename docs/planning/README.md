# Dynamic AI Product Evolution — Project Plan Pack

## Purpose

This folder is the durable, versioned strategic plan for the thesis. It brings
the formerly external desktop plan into the repository while preserving a strict
authority hierarchy:

1. immutable run manifests, output hashes, schemas, and source evidence;
2. committed code, tests, and `docs/DECISION_LOG.md` at the checked-out revision;
3. this planning pack.

The pack must never be used to overwrite, repair, or reinterpret an artifact.
It explains what has been established, what is proposed, what remains open, and
what may safely happen next.

## Snapshot

This version is current through the acceptance and push of ADR-112 at commit
`ca7538bf07a4a853f740db204071701c3c020f6d` (20 August 2026). It is updated
only after an accepted decision or major governed gate, not after exploratory
commands or an unreviewed worktree edit.

## Reading order

1. [01_CURRENT_STATUS_AND_EXECUTION_ROADMAP.md](01_CURRENT_STATUS_AND_EXECUTION_ROADMAP.md) — completed evidence, the current high-recall gate, and the required order from here.
2. [02_LONGITUDINAL_PANEL_AND_MATCHING_PLAN.md](02_LONGITUDINAL_PANEL_AND_MATCHING_PLAN.md) — the proposed longitudinal identity and matching architecture.
3. [03_MEASUREMENT_OUTCOMES_AND_ECONOMETRICS_PLAN.md](03_MEASUREMENT_OUTCOMES_AND_ECONOMETRICS_PLAN.md) — proposed measurement constructs and empirical designs; not final commitments.
4. [04_TECHNICAL_HANDOFF_CURRENT_PIPELINE.md](04_TECHNICAL_HANDOFF_CURRENT_PIPELINE.md) — a compact handoff with current artifact bindings and operational constraints.

## Maintenance rules

- Keep raw issuer identity (`CIK × accession × carrier row`) separate from a
  later economic-firm layer.
- Mark a statement as one of: completed evidence, accepted implementation,
  open decision, or future proposal.
- Do not use financial outcomes to tune eligibility, prompts, extraction,
  matching, or measurement.
- Preserve uncertainty rather than forcing an entity link, task match, or
  software classification.
- A model response, an unmanifested scratch file, or a failed run directory is
  not a research output.

## Related repository documents

- [Thesis Execution Plan](../THESIS_EXECUTION_PLAN.md)
- [Thesis Methodology and Data Blueprint](../THESIS_METHODOLOGY_AND_DATA.md)
- [Decision Log](../DECISION_LOG.md)
- [Longitudinal Task Matching](../methodology/LONGITUDINAL_TASK_MATCHING.md)
- [Measurement Design](../methodology/MEASUREMENT_DESIGN.md)
- [Master Notebook Architecture](../architecture/MASTER_NOTEBOOK_ARCHITECTURE.md)
