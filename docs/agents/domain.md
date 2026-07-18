# Domain Docs — Repository Rules for Agent Skills

How the installed agent skills (`grilling`, `domain-modeling`, `grill-with-docs`,
`tdd`, `diagnosing-bugs`, `handoff`) must consume and update this repository's
domain documentation. **These repository-specific rules override the generic
defaults inside the third-party skill files.**

## Canonical locations

- **Glossary:** `/CONTEXT.md` at the repository root (single context).
- **ADRs / decisions:** `docs/DECISION_LOG.md`, using the existing `ADR-NNN`
  heading format (`## ADR-009 — Title`, **Decision:** / **Rationale:** body).
- **Methodology:** `docs/methodology/` — canonical and binding.
- **Specifications:** `specs/` — canonical and binding.

## Overrides of skill defaults

- Do **not** create a `docs/adr/` tree. The `domain-modeling` skill's default
  `docs/adr/0001-slug.md` layout does not apply here; every ADR is an entry in
  `docs/DECISION_LOG.md`.
- New ADRs append the next `ADR-NNN` number. Existing ADRs are never
  overwritten, renumbered, or deleted.
- `CONTEXT.md` is a glossary only. It is not a PRD, spec, implementation plan,
  decision log, or scratch pad.
- Do **not** update `CONTEXT.md` or `docs/DECISION_LOG.md` inline the moment a
  term or decision crystallises. Propose the exact wording first and wait for
  explicit user approval before writing.

## What may enter the glossary

- Only canonical domain terms consistent with `docs/methodology/`, `specs/`,
  and `configs/` (taxonomy and sample rules).
- No new taxonomy codes, methodology concepts, Python class names, file paths,
  test plans, or open questions.
- Canonical taxonomy and configuration names are never silently renamed.

## What qualifies as an ADR candidate

All three must hold (easily reversible implementation preferences are not ADRs):

1. **Hard to reverse** — changing the decision later is costly.
2. **Surprising without context** — a future reader would ask "why?".
3. **A real trade-off** — genuine alternatives existed, including
   methodological trade-offs.

## Grilling-session conduct

- Ask exactly one question at a time and wait for the answer.
- If the answer exists in the repository (methodology, specs, decision log,
  code, tests), research it there before asking the user.
- Present a recommended answer with rationale alongside each question.
- A grilling or documentation session never implies implementation
  permission: no source-code changes and no next-phase work.
