# Data Flow

```text
company_registry
  ↓
source_candidates
  ↓
retrieval_manifest + raw bytes
  ↓
normalized_document + source_passages
  ↓
product_candidates
  ↓ consolidation
product_observations
  ↓
capability_observations
  ↓
task_candidates
  ↓ consolidation and role review
task_observations
  ↓
longitudinal_match_candidates
  ↓ adjudication
task_transitions
  ↓
frontier_baseline assignment
  ↓
task_measurements
  ↓
product / family / firm-year aggregates
```

## Error records

Every arrow emits failures to a stage-specific error table with:

- input identifier;
- exception class;
- retry status;
- human-action requirement;
- resolution record.

## No destructive updates

Entity corrections create superseding records with `replaces_id` and a reason.
