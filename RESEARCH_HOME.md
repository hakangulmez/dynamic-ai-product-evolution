---
title: Dynamic AI Product Evolution — Research Home
tags:
  - thesis
  - research-home
  - methodology
---

# Dynamic AI Product Evolution — Research Home

This note is the recommended Obsidian landing page for the repository.

## Current project state

- The repository is a clean-room methodological and architectural scaffold.
- The company-universe methodology is designed but Stage 00 is not yet production-ready.
- The evaluation harness must be implemented before production prompt tuning.
- The local Streamlit app is currently a read-only setup/status shell.

## Canonical workflow

1. [[docs/methodology/SOFTWARE_FIRM_UNIVERSE|Software-firm universe]]
2. [[docs/architecture/COMPANY_UNIVERSE_PIPELINE|Company-universe pipeline]]
3. [[docs/SOURCE_POLICY|Source policy]]
4. [[docs/TEMPORAL_POLICY|Temporal policy]]
5. [[docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY|Product–capability–task ontology]]
6. [[docs/methodology/EXTRACTION_METHODOLOGY|Extraction methodology]]
7. [[docs/methodology/LONGITUDINAL_TASK_MATCHING|Longitudinal matching]]
8. [[docs/methodology/MEASUREMENT_DESIGN|Measurement design]]
9. [[evals/EVAL_HARNESS|Evaluation harness]]
10. [[notebooks/README|Master notebook guide]]

## Thesis-level documents

- [[docs/THESIS_METHODOLOGY_AND_DATA|Thesis methodology and data blueprint]]
- [[docs/literature/COMPREHENSIVE_LITERATURE_REVIEW|Comprehensive literature review]]
- [[docs/PROJECT_CHARTER|Project charter]]
- [[docs/RESEARCH_QUESTIONS|Research questions]]
- [[docs/CONCEPTUAL_FRAMEWORK|Conceptual framework]]

## Implementation and operations

- [[CLAUDE|Claude working constitution]]
- [[docs/implementation/NON_DEVELOPER_LOCAL_WORKFLOW|Non-developer local workflow]]
- [[docs/implementation/OBSIDIAN_AND_STREAMLIT_SETUP|Obsidian and Streamlit setup]]
- [[docs/operations/CLAUDE_CODE_LOCAL_SAFETY|Claude Code local safety]]
- [[docs/architecture/RESEARCH_CONSOLE_ARCHITECTURE|Research Console architecture]]
- [[prompts/implementation/phase_0_company_universe|Phase 0 company-universe implementation prompt]]
- [[prompts/implementation/phase_1_eval_harness|Phase 1 eval-harness implementation prompt]]
- [[prompts/implementation/phase_2_review_console|Phase 2 review-console implementation prompt]]

## Decision and change control

- [[docs/DECISION_LOG|Decision log]]
- [[evals/CHANGE_CONTROL_PROTOCOL|Evaluation change-control protocol]]
- [[docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL|Prompt development protocol]]
- [[CHANGELOG|Repository changelog]]

## Daily working order

```text
Open Obsidian
→ read the relevant methodology/spec
→ open VS Code and Claude Code
→ implement one bounded phase
→ run tests and evals
→ inspect Streamlit reports
→ record decisions
→ commit accepted changes
```
