# Claude Code Local Safety Policy

## Goal

Allow Claude Code to perform useful autonomous implementation while reducing the risk of accidental deletion, access to unrelated files, credential exposure, uncontrolled network actions, and unreviewed large changes.

## Core principle

Local execution is not automatically safe. A local agent can still read any file available to its process, run destructive shell commands, or expose credentials through network requests. Safety comes from isolation, version control, narrow tasks, deny rules, and review.

## Required local controls

### Repository isolation

Claude Code must be started from the repository root. The repository should not contain symlinks to:

- home directories;
- credential folders;
- old repositories;
- personal documents;
- cloud configuration;
- external data not approved for the project.

### Secrets

Do not store secrets in tracked files. Keep `.env` and credential files outside the agent’s readable project tree where possible.

The repository includes `.env.example` only as a template.

### Git checkpoint

Before any autonomous implementation:

```bash
git status
git add -A
git commit -m "Checkpoint before autonomous implementation"
```

The working tree should be clean unless the uncommitted files are intentionally part of the task.

### Task boundaries

Every autonomous prompt must state:

- allowed directories;
- files or layers that must not change;
- whether network access is prohibited;
- whether package installation is prohibited;
- whether deletion is prohibited;
- test requirements;
- the explicit stopping point.

## Recommended permission practice

Use the least permissive mode that is practical.

### Normal mode

Use for:

- exploratory repository reading;
- methodology changes;
- schema design;
- small code edits;
- tasks involving uncertain commands.

### Edit-accepting mode

Use for:

- bounded implementation within the repository;
- repetitive code creation;
- test writing;
- documentation updates.

### Permission-bypass mode

Use only when all of the following are true:

- the repository is isolated;
- a clean Git checkpoint exists;
- the task is narrow and explicit;
- network calls are forbidden unless necessary;
- destructive commands are forbidden;
- the stop condition is clear;
- the researcher will review the diff immediately afterward.

## Example deny policy

An illustrative file is included at:

```text
.claude/settings.example.json
```

It is not automatically active. Copy and adapt it only after reviewing the patterns against the installed Claude Code version.

The intended protections are:

- deny reading `.env`, secret folders, and paths above the repository;
- deny recursive deletion;
- deny force pushes and destructive Git cleaning;
- deny piping downloaded scripts to a shell;
- permit safe inspection, testing, and repository-local edits.

## Required autonomous-prompt footer

Use a footer like this in implementation prompts:

```text
Safety and stopping rules:
- Work only inside this repository.
- Do not read parent or sibling directories.
- Do not read .env, secrets, SSH, or cloud credential files.
- Do not make external network calls.
- Do not delete files.
- Do not modify methodology, prompts, or schemas unless explicitly listed.
- Run tests and report exact commands.
- Show changed files and remaining limitations.
- Stop at the end of this phase.
```

## Review after an autonomous run

Run:

```bash
git status
git diff --stat
git diff
```

Review especially:

- `.claude/` settings;
- dependency files;
- shell scripts;
- CI configurations;
- files outside the requested directories;
- deleted files;
- prompt and methodology changes;
- network-related code;
- changes to `.gitignore` or credential handling.

## Prohibited autonomous tasks

Do not use permission bypass for:

- open-ended “improve everything” requests;
- migration of old project files;
- broad web scraping before source rules are implemented;
- full-universe paid model runs;
- package publishing;
- force pushing;
- deleting datasets;
- modifying frozen prompts or gold sets without a change request;
- executing scripts copied from unknown web sources.

## Incident procedure

If unexpected behavior occurs:

1. Stop the agent.
2. Do not continue giving repair prompts blindly.
3. Run `git status` and `git diff`.
4. Identify created, modified, and deleted files.
5. Preserve logs if the event matters for reproducibility.
6. Revert only after confirming which changes should be retained.
7. Add a deny rule or process control before retrying.

## Scientific safety

Operational safety also includes scientific controls:

- no access to financial outcomes during gold annotation;
- no access to legacy scores during clean-room extraction;
- no use of future sources for historical observations;
- no modification of expected labels merely to match model output;
- no production prompt change without an eval case.
