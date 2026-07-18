# CLAUDE.md — Project Operating Constitution

## Mission

Build a longitudinal, evidence-grounded product–capability–task dataset for software firms across the frontier-LLM transition. The dataset must support multiple future measurement frameworks without embedding one score into extraction.

## Non-negotiable rules

1. **Clean room.** Never import code, prompts, schemas, labels, scores, task lists, or outputs from legacy repositories.
2. **No AI-wording inference.** A phrase such as “AI-powered,” “AI-first,” “copilot,” or “agent” is only a candidate signal. It earns no depth, scale, or defensibility value without a concrete customer-facing action and dated evidence.
3. **Temporal integrity.** Never use information published after an observation cutoff to support that observation.
4. **Immutable raw sources.** Never overwrite raw documents or snapshots. Corrections create new versions and manifests.
5. **Evidence requirement.** Every extracted factual claim must reference `source_id`, `passage_id`, publication date, and a short evidence quote.
6. **Separate layers.** Source collection, extraction, matching, measurement, aggregation, and outcome analysis are separate stages with separate schemas.
7. **Unknown over guess.** If evidence is insufficient, output `unknown`, `uncertain`, or a missing field. Do not fill gaps by plausibility.
8. **Schema governance.** Do not change schemas, rubrics, or accepted specs without a decision-log entry and version increment.
9. **No silent repair.** All repairs are explicit, logged, and reversible.
10. **No premature scale.** Do not run the full universe until the sentinel evaluation suite passes its acceptance thresholds.
11. **No outcome leakage.** Financial performance, stock returns, or later narratives must not influence extraction or measurement labels.
12. **No benefit-by-definition.** Deep AI transformation is not automatically advantageous. Adoption, replicability, and defensibility remain separate.

## Unit of analysis

Primary observation:

```text
firm × observation date × product × capability × customer-facing task
```

Longitudinal relation:

```text
predecessor task observation → transition → successor task observation
```

## Source priority

1. SEC filing text and exhibits
2. Official investor-relations materials
3. Official product documentation
4. Official developer/API documentation
5. Official release notes and newsroom
6. Archived official product pages

Third-party sources are excluded from the canonical extraction corpus unless a future accepted spec adds a clearly bounded validation role.

## Temporal rule

A source may support observation `t` only if:

```text
publication_date <= observation_cutoff_date
```

A live product page cannot establish a historical capability unless an archived snapshot with a valid date is available.

## Required workflow for any implementation task

1. Identify and read the governing spec.
2. State the exact input and output contract.
3. Implement the smallest testable unit.
4. Add schema, temporal, provenance, and contamination tests.
5. Run the relevant eval fixture.
6. Write a run manifest.
7. Update the decision log only if a design decision changed.

## Model-use policy

- Use high-capability models for ontology design, difficult matching, adjudication, and scientific review.
- Use cheaper structured-output models for validated repetitive extraction.
- Record model provider, model label/version, prompt hash, schema hash, spec version, source-manifest hash, run time, parameters, tools, and fallback behavior.
- Chat UI runs are exploratory unless their exact source packet, prompt, model label, and output are archived.

## Forbidden behavior

- Creating a new production taxonomy during a batch run.
- Treating marketing strategy as a deployed product capability.
- Treating a roadmap item as generally available.
- Creating one task per sentence.
- Treating delivery channels as distinct tasks without distinct customer outcomes.
- Treating every named feature as a product.
- Aggregating to firm level before task-level validation.
- Using current web content to revise historical observations.
- Optimizing wording locally when scientific content is already correct.

## Required reading map

- Research purpose: `docs/PROJECT_CHARTER.md`
- Concepts: `docs/CONCEPTUAL_FRAMEWORK.md`
- Sources: `docs/SOURCE_POLICY.md`
- Time: `docs/TEMPORAL_POLICY.md`
- Ontology: `docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`
- Extraction: `docs/methodology/EXTRACTION_METHODOLOGY.md`
- Matching: `docs/methodology/LONGITUDINAL_TASK_MATCHING.md`
- Measurement: `docs/methodology/MEASUREMENT_DESIGN.md`
- Evaluation: `evals/EVAL_HARNESS.md`
- Implementation: relevant `specs/SPEC-XXX-*.md`

## Agent skills

### Installed workflow skills

Project-local skills are stored under `.claude/skills/` and pinned by
`skills-lock.json`. Third-party skill instructions never override this
repository's canonical methodology, specifications, decision log, safety
rules, or explicit user instructions.

### Domain documentation

- Glossary: `CONTEXT.md`
- Methodology: `docs/methodology/`
- Binding specifications: `specs/`
- Decisions and ADRs: `docs/DECISION_LOG.md`
- Agent-specific domain rules: `docs/agents/domain.md`

Do not create a parallel `docs/adr/` tree. Do not write a new term or ADR
without explicit approval.

### Issue tracker

GitHub Issues may be used only when explicitly requested. Existing
specifications and implementation prompts must not be automatically converted
into issues. See `docs/agents/issue-tracker.md`.

### Skill execution boundaries

- Grilling and documentation work do not imply implementation permission.
- A planning/grilling request must not modify source code or begin the next phase.
- Commit, push, issue creation, label changes, and external write actions require
  explicit user approval.
- Repository-local instructions override generic third-party skill defaults.
