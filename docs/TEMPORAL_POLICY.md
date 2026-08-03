# Temporal Policy

## Core rule

A source may support an observation only when:

```text
source_publication_date <= observation_cutoff_date
```

## Required dates

Every source and observation must record:

- `document_publication_date`
- `retrieval_timestamp`
- `snapshot_timestamp`, when applicable
- `observation_cutoff_date`
- `frontier_baseline_date`

## Observation-date options

The pilot comparison is complete (ADR-046). Two conventions were on the table:

1. **Filing-date observation:** each annual observation is anchored to the annual filing date.
2. **Fiscal-year-end observation:** the source packet is bounded by the filing date but assigned to the fiscal year.

**Both bound the source packet by the filing date.** They differ in the label
assigned to the observation, not in which sources are admissible, so they are not
competing cutoffs. Two distinct ideas must therefore be named separately:

- **Source-admission (evidence-availability) cutoff.** This is what
  `observation_cutoff_date` means in the packet and authorization schemas: the
  right-hand side of the core rule above. It is the **filing/publication date**.
- **Analytical period assignment.** The fiscal year the observation belongs to,
  carried by `period_of_report`, `fiscal_year_end_date` and `observation_year`.
  It is never expressed through `observation_cutoff_date`.

For the first HubSpot observation the source-admission cutoff is `2025-02-12` and
the analytical period assignment is FY2024.

Using a fiscal-period-end date as a *source-admission* cutoff is rejected: an
annual report is filed after the period it reports on, so a period-end admission
cutoff makes every annual filing invalid evidence for its own observation. This
rejection concerns the admission boundary only and says nothing about fiscal-year
panel assignment.

Both rules must be applied consistently within the released dataset, and
consistently with each other: the source-admission cutoff rule that decides which
sources are admissible, and the analytical-period-assignment rule that decides
which period an observation belongs to. Neither may be varied per firm, per year,
or per source family, and satisfying one does not satisfy the other.

**Current limitation.** The analytical period assignment stops at the
admission/ingestion artifact. No schema carries an `observation_year` field, and
neither the extraction packet nor the live-call authorization carries any date
field other than `observation_cutoff_date`. No extraction output may be joined to
a fiscal-year panel until a successor adds a hash-bound carrier for that label
(ADR-046).

## Historical web content

A live product page retrieved in 2026 cannot support a 2023 observation unless:

- a dated official release establishes the feature by 2023; or
- an archived version of the page exists with a valid 2023 snapshot.

## Roadmap and beta states

Store availability explicitly:

- `announced`
- `private_beta`
- `public_beta`
- `general_availability`
- `default_or_broadly_deployed`
- `deprecated`
- `discontinued`

A roadmap statement does not become a deployed task.

## Frontier-model baseline

The frontier baseline is assigned as of the observation date. It must not include capabilities released later.

The registry records:

- model/system name;
- release and access dates;
- modalities;
- context window;
- tool use and code execution;
- browsing or retrieval;
- relevant quality evidence;
- source citations;
- access limitations.

## Acquisitions

An acquired product is not treated as integrated merely because the acquisition closed. Store:

- acquisition announcement date;
- close date;
- product continuity;
- integration evidence;
- first appearance in product packaging or workflows.

## Corrections

If a source date or cutoff was wrong, create a new versioned observation and a correction record. Never mutate historical raw data silently.
