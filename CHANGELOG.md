# Changelog

## 0.6.0 — Phase 0 company-universe sentinel

- Implemented the Stage 00 local sentinel under `src/dynamic_ai_products/universe/`: filer-frame models with CIK/accession normalization, deterministic issuer exclusions with reason codes, temporally validated baseline evidence packets, a mock-provider high-recall screen and multi-axis classification boundary, config-driven Tier A/B/C derivation with rule traces and config hashes, an append-only boundary-adjudication layer, seeded stratified negative-audit sampling, and hard-gated freeze manifests.
- Rewrote `pipelines/00_build_company_universe.py` as a fixture-driven CLI (`--config/--input/--output-dir/--run-id/--seed/--provider mock/--dry-run`) with immutable run directories and non-zero exit codes on validation failure. No network access and no real model calls.
- Added the synthetic `evals/fixtures/universe_sentinel/` bundle (24 firms covering all twelve adversarial boundary families plus issuer, lineage, entrant, insufficient-evidence, and temporal-leakage cases) with gold `expected_tiers.json`.
- Added 58 tests across identifiers, issuer filters, packets, screening/classification validation, tier rules, review/audit, and end-to-end runner/CLI behavior; stage 00 registry status is now `sentinel`.
- Documented commands, fixture format, remaining stubs, and pre-network hard gates in `docs/implementation/COMPANY_UNIVERSE_SENTINEL_V0.md`.
- Review round: adopted ADR-009 (MIXED_NONSEPARABLE firms route to Tier C or manual review, never Tier B; sample rules 0.2.0) and ADR-010 (screen-derived exclusions are provisional with explicit provenance until the negative audit completes; audit completion is a freeze hard gate). Added exclusion-provenance fields, negative-audit result records, count-reconciliation identities, run-id path-traversal validation, and a fixture-bundle source hash in the run manifest. Aligned the package version with the changelog and extended `REPO_MANIFEST.md` with all Phase 0 files.

## 0.5.0 — Local Obsidian and Streamlit setup

- Added an Obsidian-friendly `RESEARCH_HOME.md` that maps methodology, implementation, evaluation, and operations documents.
- Added a read-only pre-harness Streamlit setup/status console.
- Added one-command local setup and console-launch scripts.
- Added a `ui` optional dependency, Makefile targets, and local Streamlit configuration.
- Added comprehensive non-developer setup and staged UI rollout documentation.
- Preserved the Phase 1 eval-harness gate: structured review and adjudication features remain unimplemented.

## 0.4.0 — Comprehensive current literature review

- Added `docs/literature/COMPREHENSIVE_LITERATURE_REVIEW.md`, a 12,000+ word synthesis aligned to the dynamic product–capability–task thesis.
- Added an explicit legacy-framework audit removing the static `rho/delta`, fixed-DiD, Item-1-only, and legacy score assumptions from the current design.
- Added literature on task-based technological change, general-purpose technologies, dynamic capabilities, complementary assets, firm AI adoption, product innovation, agent benchmarks, official-web/10-K text measurement, and LLM evaluation bias.
- Mapped the literature to Frontier Task Replicability, AI Transformation Depth, Deployment Scale, Task-Specific Defensibility, Task Economic Importance, and longitudinal task transitions.
- Added literature maintenance rules, publication-status labels, a priority reading list, and a literature-to-repository crosswalk.
- Updated the repository reading order, methodology blueprint, bootstrap, handoff context, and manifest.

## 0.3.0 — Master pipeline notebook

- Added `notebooks/00_MASTER_PIPELINE.ipynb` as the canonical literate workflow and safe orchestration layer.
- Added the canonical stage registry and notebook execution configuration.
- Added reusable workflow discovery, validation, dry-run, execution, logging, and summary helpers.
- Added master-notebook architecture documentation and `SPEC-026`.
- Added registry and notebook integrity tests.
- Added notebook optional dependencies and Makefile commands.

## 0.1.0 — Initial clean-room design

- Added project charter, source and temporal policies, ontology, extraction methodology, longitudinal matching design, provisional measurement design, and validation strategy.
- Added 21 implementation specifications.
- Added evidence-grounded extraction, matching, measurement, adjudication, and evaluation prompt templates.
- Added source and analysis skills.
- Added JSON schemas and minimal Python scaffolding.
- Added contamination checks and a 90-day roadmap.

No production data or frozen measurement scores are included.

## 0.1.1 — Comprehensive methodology and data blueprint

- Added `docs/THESIS_METHODOLOGY_AND_DATA.md`, a thesis-level description of the research design, source corpus, ontology, extraction pipeline, longitudinal matching, dated frontier baselines, measurement constructs, data tables, validation, aggregation, outcome analysis, limitations, and reproducibility policy.
- Added the document to the repository reading order and new-chat bootstrap instructions.

## 0.2.0 — Structured evaluation and local research workflow

- Added a binding prompt-development and evaluation protocol that prohibits informal production prompt changes without cases, change requests, regression comparison, and release decisions.
- Added evaluation data, deterministic validation, immutable run comparison, and local review-console specifications (`SPEC-022` through `SPEC-025`).
- Added implementation prompts for Phase 1 of the eval harness and Phase 2 of the Streamlit review console.
- Added non-developer local workflow and Claude Code safety documentation.
- Added local Research Console architecture, append-only review rules, and an Obsidian/Streamlit/VS Code division of roles.
- Added eval-case and change-request templates, split directories, and new operational skills.
- Updated the 90-day roadmap so evaluation infrastructure precedes prompt tuning and scaled extraction.