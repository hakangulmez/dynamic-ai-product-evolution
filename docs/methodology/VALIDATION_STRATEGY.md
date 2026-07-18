# Validation Strategy

## Validation layers

1. Source validity and temporal integrity.
2. Product precision/recall.
3. Capability concreteness.
4. Task economic validity and granularity.
5. Evidence grounding.
6. Longitudinal matching reliability.
7. Measurement construct validity.
8. Aggregation sensitivity.

## Sentinel set

Select heterogeneous firms before viewing model scores. Include direct-substitution, enterprise-workflow, creative-production, infrastructure, proprietary-data, human-service, and low-change cases.

## Gold creation

- two independent annotators;
- source packet only;
- no financial outcomes;
- adjudication log;
- versioned guidelines;
- agreement metrics by label type.

## Required ablations

- Item 1 only versus enriched official corpus;
- annual filing only versus intra-year sources;
- product pages with and without developer docs;
- strong model versus production model;
- one-pass versus discovery/consolidation pipeline;
- matching with and without deterministic candidate generation.

## Construct validation

Use ex ante anchor tasks rather than selecting examples from score rankings. Review whether the ordering follows the rubric and evidence, not intuition alone.

## External validity

Financial outcomes are not used to tune measurement. Outcome relationships are evaluated after freeze.
