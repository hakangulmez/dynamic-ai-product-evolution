# System Architecture

## Components

1. **Registry:** firm identifiers, observation dates, fiscal calendars.
2. **Discovery:** SEC and official-web URL enumeration.
3. **Ingestion:** retrieval, retry, rate limiting, hashing, immutable storage.
4. **Normalization:** text extraction, boilerplate removal, passage segmentation.
5. **Extraction:** products, capabilities, tasks, roles.
6. **Matching:** entity resolution and longitudinal transitions.
7. **Frontier registry:** dated capability baselines.
8. **Measurement:** replicability, transformation depth, scale, defensibility.
9. **Evaluation:** deterministic and expert gold comparisons.
10. **Analysis:** aggregation, descriptive trajectories, later outcomes.
11. **Provenance:** source, prompt, model, schema, and run manifests.

## Architectural boundaries

- Discovery does not interpret products.
- Extraction does not read financial outcomes.
- Matching does not alter source observations.
- Measurement does not rewrite tasks.
- Aggregation does not repair task-level errors.

## Idempotence

Every pipeline stage should be restartable and content-addressed. Re-running unchanged inputs should produce identical deterministic outputs or a versioned model-run record.

## Storage keys

Recommended object keys:

```text
raw/{company_id}/{source_type}/{publication_date}/{content_hash}.{ext}
normalized/{source_id}/{normalizer_version}.jsonl
processed/{dataset_version}/{entity_type}.parquet
manifests/{run_type}/{run_id}.json
```
