# Legacy Isolation Policy

## Objective

Prevent prior project assumptions, labels, outputs, and task lists from contaminating the new clean-room dataset.

## Prohibited inputs

The new pipeline must not read or import:

- prior task JSON or CSV outputs;
- prior firm-level rankings or scores;
- prior prompt files;
- prior taxonomies or category labels;
- prior case-study narratives;
- prior financial results during extraction or measurement design.

## Permitted historical knowledge

General methodological lessons may be documented without importing operational artifacts. Examples:

- extraction and measurement should be separated;
- evidence must be passage-level;
- task granularity needs explicit evaluation;
- aggregation can distort firm-level rankings;
- AI wording is not adoption evidence.

## Automated controls

The repository includes contamination tests that scan code, prompts, and schemas for:

- forbidden legacy paths;
- known old prompt-version markers;
- unexpected legacy score-field names;
- direct imports from sibling legacy repositories.

A small allowlist may permit legacy terms in this policy or in a later historical appendix only.

## Human controls

- Do not open prior firm scores before completing blinded new extraction for pilot firms.
- Gold labels must be created from source packets, not prior outputs.
- Reviewers should not be shown financial outcomes during construct labeling.
- Any later crosswalk must be performed after the new measurement version is frozen.
