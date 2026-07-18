# Non-Developer Local Workflow

## Purpose

This guide explains how to work on the repository locally with VS Code and Claude Code without needing to become a software developer. The researcher remains responsible for scientific definitions and review decisions; Claude Code performs implementation work in small, testable phases.

## Your role

You should focus on:

- whether a product, capability, or task is conceptually correct;
- whether evidence supports a claim;
- whether a task is too broad, too narrow, duplicated, or internal;
- whether a task is core, supporting, or peripheral;
- whether two yearly observations represent the same task or a transformation;
- whether a measurement follows the written rubric;
- whether a prompt change fixes a general failure class.

You do not need to manually write application code, SQL, JSON parsers, or Streamlit pages.

## Claude Code’s role

Claude Code should:

- inspect the relevant specification;
- propose a bounded implementation plan;
- create code and tests;
- run the tests;
- show changed files;
- stop at the end of the requested phase;
- avoid changing methodology unless explicitly asked.

## Initial setup

### 1. Keep the repository isolated

Place the repository in a dedicated folder. Do not put personal documents, credentials, other research projects, or old project outputs inside it.

Recommended structure:

```text
~/Research/
  dynamic-ai-product-evolution/
```

Do not place these inside the repository:

- personal `.env` files;
- SSH keys;
- cloud credential folders;
- browser profiles;
- old task outputs;
- old prompt libraries;
- unrelated company documents.

### 2. Open only this repository in VS Code

From Terminal:

```bash
cd ~/Research/dynamic-ai-product-evolution
code .
```

Start Claude Code from the same directory so that the repository is the natural working boundary.

### 3. Use Git as the safety net

Before a major task:

```bash
git status
git add -A
git commit -m "Checkpoint before eval harness implementation"
```

After Claude finishes:

```bash
git status
git diff --stat
git diff
```

Do not accept a large change without first reading the summary, test results, and changed-file list.

## Permission modes

The safest practical default is to allow normal repository edits while retaining confirmation for riskier commands.

Do not begin with unrestricted permissions until the repository is isolated and committed.

Recommended sequence:

1. Start Claude Code normally or with an edit-accepting mode.
2. Give a precise implementation prompt.
3. Use unrestricted permission mode only for a bounded, local, mechanical task if repeated confirmations become impractical.
4. Return to the normal mode after the task.

An example deny-policy file is stored at:

```text
.claude/settings.example.json
```

It is deliberately an example and is not automatically active. Review it before copying it to an active Claude settings location.

## Daily workflow

### Step 1 — Choose one phase

Examples:

- deterministic eval validators;
- eval report generation;
- local review console;
- source discovery for one pilot firm;
- product extraction fixtures.

Do not ask Claude to “finish the whole repository.”

### Step 2 — Name the governing documents

Every implementation prompt should tell Claude which files to read first, for example:

```text
Read CLAUDE.md, SPEC-020, the validation strategy, and the prompt-evaluation protocol.
```

### Step 3 — State prohibitions

Typical constraints:

- no external network calls;
- no paid model calls;
- no prompt changes;
- no schema changes;
- no deletion;
- no legacy imports;
- do not proceed to the next phase automatically.

### Step 4 — Require a plan before coding

Claude should first report:

- the files it inspected;
- conflicts or ambiguities;
- proposed deliverables;
- tests it will add.

### Step 5 — Let Claude implement

The implementation prompt should have an explicit endpoint. For example:

> Implement Phase 1, run tests, document usage, summarize remaining work, and stop.

### Step 6 — Review the result

Check:

- Were all tests run?
- Did any methodology or prompt file change unexpectedly?
- Were files deleted?
- Did the implementation remain inside the repository?
- Are outputs versioned rather than overwritten?
- Does the documentation explain how you can use the feature?

### Step 7 — Commit accepted work

```bash
git add -A
git commit -m "Implement evaluation harness phase 1"
```

If the implementation is wrong, revert the specific changes or return to the checkpoint rather than asking for endless untracked repairs.

## The new prompt-development routine

The old routine was:

```text
Read several outputs
  → change prompt wording
  → rerun selected firms
  → repeat
```

The new routine is:

```text
Identify a failure
  → create an eval case
  → define expected behavior
  → confirm current prompt fails
  → write a change request
  → make one general change
  → run all eval splits
  → inspect fixes and regressions
  → accept or reject
```

Your main interface will eventually show the source evidence, model prediction, and expected output side by side.

## How to report a failure without writing code

Use plain language and include:

1. the company and observation date;
2. the source passage;
3. what the model extracted;
4. why it is wrong;
5. what the correct interpretation should be;
6. the general error class.

Example:

```text
The passage says that AI is central to the company’s strategy but does not describe a customer action.
The model created a capability named “AI-powered platform.”
This should be rejected as marketing wording.
General failure class: marketing language treated as a concrete capability.
```

Claude can convert this into a structured eval case and change request, but you must approve the conceptual expectation.

## What not to do

- Do not ask for a ticker-specific rule.
- Do not modify a prompt because a firm’s final score is not economically intuitive.
- Do not show financial outcomes while creating extraction gold labels.
- Do not accept a prompt because one familiar company improved.
- Do not overwrite a previous run.
- Do not combine extraction, matching, and scoring into one model call.
- Do not run hundreds of firms before the sentinel suite passes.

## Practical command list

### Check repository state

```bash
git status
```

### View recent commits

```bash
git log --oneline -10
```

### Run all tests

```bash
python -m pytest
```

### Run one test area

```bash
python -m pytest tests/schema
python -m pytest tests/temporal
python -m pytest tests/contamination
```

### Launch the future review console

```bash
make research-console
```

The command will be added during UI implementation.

## Recommended implementation order

1. Evaluation case data model.
2. Deterministic validators.
3. Eval runner and reports.
4. Development/adversarial/regression fixtures.
5. Run comparison.
6. Minimal Streamlit review console.
7. Source and extraction pipeline pilot.
8. Longitudinal matching.
9. Measurement pilot.

## When to use unrestricted permissions

Unrestricted permissions may be reasonable for a bounded task when:

- the repository is isolated;
- a clean Git checkpoint exists;
- secrets are not present;
- the task explicitly forbids network calls and deletion;
- the requested phase is narrow;
- tests and stop conditions are specified.

It should not be used for vague requests such as:

> Improve the entire project and install anything you need.

## Recovery if something goes wrong

First inspect:

```bash
git status
git diff
```

If only a few files are wrong, ask Claude to fix those files with tests.

If the whole phase is unusable and no desired work must be preserved, return to the last checkpoint using standard Git recovery. Do not use destructive Git commands unless you understand exactly which uncommitted work will be lost.

## Completion standard

A phase is complete only when:

- the requested deliverables exist;
- tests pass;
- usage is documented for a non-developer;
- no unexpected methodology changes occurred;
- outputs are versioned and auditable;
- the next phase is listed but not started automatically.
