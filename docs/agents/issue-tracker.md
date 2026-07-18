# Issue Tracker — Repository Policy for Agent Skills

**Write operations require explicit user approval.** No agent skill may
create, edit, label, comment on, or close a GitHub issue or PR — or change
any repository setting — without the user explicitly requesting that action
in the current conversation.

## Current policy

The potential tracker for this repository is **GitHub Issues**
(`hakangulmez/dynamic-ai-product-evolution`, via the `gh` CLI). However, at
the current stage:

- No issue is created without an explicit user request.
- Existing `specs/` and `prompts/implementation/` documents are **not**
  automatically converted into issues.
- No triage labels are created or modified.
- PRs are **not** a request/triage surface.
- Read-only issue inspection is done only when a task actually requires it.
- Canonical planning sources remain `specs/` and `prompts/implementation/`.

## GitHub conventions (for use only after explicit approval)

- **Create an issue**: `gh issue create --title "..." --body "..."` (heredoc
  for multi-line bodies).
- **Read an issue**: `gh issue view <number> --comments`.
- **List issues**: `gh issue list --state open --json number,title,labels`.
- **Comment**: `gh issue comment <number> --body "..."`.
- **Close**: `gh issue close <number> --comment "..."`.

Infer the repo from `git remote -v`; `gh` does this automatically inside a
clone.

## Pull requests as a triage surface

**PRs as a request surface: no.**
