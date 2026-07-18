# SEC Document Reader Skill

## Purpose

Read and index relevant portions of SEC filings without losing provenance.

## Required reading

- `SPEC-003`
- `SPEC-006`
- `SEC_EDGAR.md`

## Procedure

1. Confirm accession and filing metadata.
2. Locate Item 1, MD&A, risks, and relevant exhibits.
3. Preserve headings and passage IDs.
4. Flag tables or exhibits requiring separate parsing.

## Output discipline

- Use the governing schema.
- Cite source and passage IDs.
- Preserve unknowns and ambiguity.
- Write concise audit rationales, not hidden chain-of-thought.
- Produce a run manifest.

## Stop conditions

- Source bytes or accession metadata are missing.
