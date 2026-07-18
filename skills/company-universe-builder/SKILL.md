# Company Universe Builder Skill

## Use when

Constructing, screening, classifying, adjudicating, auditing, or freezing the dated company universe.

## Do not use when

- extracting full products, capabilities, or tasks;
- measuring AI or frontier replicability;
- using current websites to decide historical membership;
- selecting firms based on later outcomes.

## Required reading

- `CLAUDE.md`
- `SPEC-001`
- `docs/methodology/SOFTWARE_FIRM_UNIVERSE.md`
- `docs/architecture/COMPANY_UNIVERSE_PIPELINE.md`
- `docs/TEMPORAL_POLICY.md`
- `configs/universe_taxonomy.yaml`
- `configs/universe_sample_rules.yaml`
- `evals/rubrics/UNIVERSE_CLASSIFICATION_RUBRIC.md`

## Procedure

1. Confirm the baseline cutoff, form scope, and universe version.
2. Build or load the historical annual-filer frame.
3. Apply deterministic issuer reason codes without destructive deletion.
4. Construct passage-addressable baseline SEC packets.
5. Run the high-recall screen on all cleaned candidates.
6. Run the full classifier on positive and uncertain candidates.
7. Validate every evidence claim and temporal rule.
8. Apply deterministic tier rules and retain the rule trace.
9. Route required boundary families to append-only review.
10. Draw and audit a reproducible stratified negative sample.
11. Run gold, adversarial, regression, and hard-gate checks.
12. Freeze only after acceptance criteria pass.
13. Write all output hashes and limitations to the manifest.

## Output discipline

- CIK is the stable company key.
- Do not silently remove failed or exited firms.
- Preserve economic eligibility separately from data eligibility.
- Preserve all raw model outputs and reviews.
- Use unknown instead of unsupported certainty.
- Never hard-code company-specific exceptions in production rules.

## Stop conditions

- baseline cutoff is not frozen for the run;
- source packet includes post-cutoff evidence;
- historical operating/listing status cannot be resolved;
- taxonomy, schemas, or sample rules are inconsistent;
- hard eval gates fail;
- negative audit has not been completed;
- manual boundary queue contains unresolved high-severity cases.
