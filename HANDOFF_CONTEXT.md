# Handoff Context

## Why this repository exists

Earlier work built a static pre-shock product-task exposure dataset and a multi-part scoring framework. That work revealed a more important empirical problem: software firms respond endogenously to frontier-model progress. Some products are directly bypassed even after firms add AI features; other firms integrate AI into data, permissions, workflow state, tools, and execution, creating deeper product transformation.

The new project therefore starts from a clean slate and asks how customer-facing products and tasks evolve over time.

## Illustrative observations motivating the redesign

- A consumer learning product can add conversational AI, proprietary content grounding, and frontier models while its underlying customer job remains easy to obtain directly from a general-purpose model at low switching cost.
- A creative-software firm can progress from predictive features to first-party generative models, custom brand models, API-scale content production, cross-product workflows, and agentic orchestration.
- An enterprise-workflow firm can move from recordkeeping and recommendations to workflow-integrated execution, permissions-aware agents, and multi-step orchestration.

These observations motivate separate measures of:

- what frontier models can do at each date;
- how deeply AI changes a product task;
- how broadly the change is deployed;
- whether the result is differentiated or commoditized.

## Clean-room commitment

Prior project artifacts may be retained outside this repository for historical provenance, but they are not inputs to extraction, prompt development, measurement, or model evaluation here. Any later comparison must be explicitly labeled as an external comparison after the new framework is frozen.

## First pilot recommendation

Use a deliberately heterogeneous set rather than only famous AI adopters. A balanced pilot should include:

- one consumer direct-substitution case;
- one creative-production case;
- one enterprise-workflow case;
- one infrastructure/security case;
- one proprietary-data case;
- one low-change control case.

Do not pre-label firms as winners or losers in the gold data. The pilot is for ontology, source coverage, and transition reliability.

## Current implementation priority

The project now treats prompt development as an evaluated software-and-methodology release process. The next step is not additional prompt wording and not a full extraction run.

Priority sequence:

1. implement the evaluation-case model and deterministic validators;
2. implement immutable eval reports and prompt-version comparisons;
3. create the minimal local Streamlit review console;
4. begin the six-firm source and extraction pilot under the harness;
5. add every corrected failure to the permanent regression set.

Use `prompts/implementation/phase_1_eval_harness.md` first. The researcher should act as ontology owner and gold-set adjudicator rather than manually modifying JSON or code.

## Canonical workflow notebook

Open `notebooks/00_MASTER_PIPELINE.ipynb` after reading `CLAUDE.md`. It is the single
end-to-end map of the repository and the safe stage orchestration surface. It currently
runs in status mode because stage scripts are intentional stubs.

## Canonical literature

- `docs/literature/COMPREHENSIVE_LITERATURE_REVIEW.md`
