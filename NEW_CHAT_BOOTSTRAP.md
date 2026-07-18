# New Chat Bootstrap

Use this file to continue the project in a new chat without relying on the prior conversation.

## Copy-paste prompt for the new chat

> I am continuing a clean-room research project contained in the attached `dynamic-ai-product-evolution` repository. First read `CLAUDE.md`, `docs/THESIS_METHODOLOGY_AND_DATA.md`, `docs/literature/COMPREHENSIVE_LITERATURE_REVIEW.md`, `docs/PROJECT_CHARTER.md`, `docs/CONCEPTUAL_FRAMEWORK.md`, `docs/SOURCE_POLICY.md`, `docs/TEMPORAL_POLICY.md`, `docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md`, `docs/methodology/EXTRACTION_METHODOLOGY.md`, `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`, `evals/EVAL_HARNESS.md`, `docs/implementation/EVAL_HARNESS_BUILD_PLAN.md`, and `docs/implementation/NON_DEVELOPER_LOCAL_WORKFLOW.md`. Do not import or reconstruct any prior project's prompts, scores, taxonomies, or outputs. The current implementation priority is Phase 1 of the evaluation harness, not full-corpus extraction and not the Streamlit interface. Use `prompts/implementation/phase_1_eval_harness.md` as the governing task. Before changing code or schemas, identify the governing spec, propose a small testable plan, and stop at the end of the requested phase. Do not run a full-universe job.

## Current project state

- The research question has shifted from a static, single-filing exposure score to a longitudinal product–capability–task dataset.
- The intended observation window is approximately 2022–2026, subject to final universe and cutoff decisions.
- Official sources are allowed under a strict hierarchy: SEC filings and exhibits, official investor-relations materials, official product/developer documentation, official newsroom/release notes, and archived official pages.
- Product/task extraction is deliberately separated from frontier replicability, AI transformation depth, deployment scale, and task-specific defensibility.
- The measurement framework is provisional. Extraction schemas preserve the raw facts needed for multiple future measures.
- A small sentinel pilot must precede scaling.

## Recommended next action

Implement Phase 1 of the evaluation harness using `prompts/implementation/phase_1_eval_harness.md`. After it passes, implement the minimal local review console using `prompts/implementation/phase_2_review_console.md`. Corpus ingestion and extraction pilots follow under the same evaluation discipline.

## Do not do yet

- Do not copy old task lists.
- Do not use old firm scores as labels.
- Do not design regressions before validating the longitudinal data.
- Do not infer adoption from the presence of the words AI, generative AI, copilot, or agent.
- Do not scrape the live web without immutable snapshots and retrieval manifests.
- Do not change production prompts without a linked eval case and change request.
- Do not build a polished dashboard before the deterministic harness works.

## Canonical workflow notebook

Open `notebooks/00_MASTER_PIPELINE.ipynb` after reading `CLAUDE.md`. It is the single
end-to-end map of the repository and the safe stage orchestration surface. It currently
runs in status mode because stage scripts are intentional stubs.
