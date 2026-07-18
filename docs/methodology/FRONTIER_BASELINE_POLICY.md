# Frontier Baseline Policy

## Objective

Create a dated registry of frontier general-purpose AI capabilities used for replicability assessments.

## Registry granularity

A baseline is defined by date and access regime, not only model name.

Record:

- public release date;
- API or product availability date;
- relevant geographic or pricing restrictions;
- modalities;
- context length;
- tool or function calling;
- browsing/retrieval;
- code execution;
- image/audio/video generation;
- reliability and benchmark evidence;
- primary sources.

## Capability claims

Use primary model documentation, technical reports, system cards, and dated product announcements. Benchmarks support capabilities but do not automatically prove customer-task quality.

## Temporal assignment

For each task observation, assign the latest eligible baseline available by the observation cutoff. If access was limited, record the access assumption.

## Evaluation packet

The measurement model receives a concise, frozen baseline summary. It must not use current knowledge of later models.

## Updates

A new model release creates a new registry entry; it does not overwrite earlier capability profiles.
