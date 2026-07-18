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

The pilot must compare two possible conventions before freezing one:

1. **Filing-date observation:** each annual observation is anchored to the annual filing date.
2. **Fiscal-year-end observation:** the source packet is bounded by the filing date but assigned to the fiscal year.

The convention must remain consistent within the released dataset.

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
