# G3 live smoke runbook

**Status:** template and procedure only. See ADR-050.

This document carries **no operator values**. There is no project identifier, no
budget ceiling, no validity window, no identity, no attempt-root name, no backup
location, no access detail, no deletion event and no ADC output anywhere in it —
and none is ever added. Real values are the operator's transient local inputs;
their first durable write is the four governance records in the chosen governance
root, and nowhere else.

## 0. What this document does not authorize

Reading or following this runbook authorizes nothing on its own. Each of the
following is a separate, explicit operator authorization:

- **R8** — real governance materialization.
- **G5-pre-B layer 2** — the ADC reachability check that mints a token and
  contacts the provider's identity service.
- **G5** — the live smoke run itself.

Creating the governance container or an attempt root is likewise an explicit R7
step, never a side effect of any tool.

## 1. Two roots, never one

| | `governance_artifact_root` | `run_root` |
|---|---|---|
| what it holds | the four write-once governance records | one run's own outputs |
| state required at the G5 call | **exists and is populated** | **does not exist at all** |
| refusal if wrong | `governance_root_required` (when absent from the call) | `run_root_exists` |
| who creates it | the operator, at R7 | the runner, at F1 |

The two requirements are opposites, so one path can never satisfy both. Handing
the populated governance root to a run as its output root is refused before any
extraction artifact is written, and the four governance records are untouched.

### Governance root convention (ADR-050, D1 = B)

```
container    : artifacts/governance/
attempt root : artifacts/governance/gov-<company_id>-<stage>-<nnnn>/
retry        : increment <nnnn>; a previous attempt root is never reused
```

Inside an attempt root the layout is fixed by code and cannot be configured:

```
<attempt_root>/governance/adapter_qualification_record.json
<attempt_root>/governance/prompt_qualification_record.json
<attempt_root>/governance/adapter_enablement_record.json
<attempt_root>/governance/live_call_authorization.json
```

**This convention is not runtime-enforced.** The materializer accepts any
existing, real, non-symlink, completely empty directory; it has no opinion about
where that directory is. Placement is enforced by step R7 below and by nothing
else.

## 2. Operator input template

Fill these locally. Do **not** write them into this document, into any decision
record, or into any other tracked file.

| field | owner | constraint |
|---|---|---|
| `vertex_project` | operator | `<…>` — lowercase, 6–30 chars, `[a-z][a-z0-9-]*[a-z0-9]` |
| `budget_max_records` | operator | `<…>` — positive integer |
| `budget_max_external_requests` | operator | `<…>` — at least 2 |
| `budget_max_input_tokens` | operator | `<…>` — positive integer |
| `budget_max_output_tokens` | operator | `<…>` — at least the declared max output tokens |
| `budget_max_estimated_cost_micros` | operator | `<…>` — positive integer |
| `budget_max_wall_clock_seconds` | operator | `<…>` — at least the floor for the effective cap |
| `circuit_breaker_max_consecutive_failures` | operator | `<…>` — positive integer |
| `deployment_environment_id` | operator | `<…>` — identical in authorization and enablement |
| `rollout_state` | operator | one of `live_dev`, `controlled_pilot`, `release_or_research_production` |
| `authorization_effective_at` / `authorization_expires_at` | operator | `<…>` — explicit UTC offset |
| `enablement_effective_at` / `enablement_expires_at` | operator | `<…>` — explicit UTC offset |
| `qualified_at`, `decided_at` | operator | `<…>` — `decided_at <= run_created_at` |
| `run_created_at` | operator | `<…>` — declared instant; see §7 |
| `authorization_id`, `enablement_id`, `qualification_id`, `prompt_qualification_id` | operator | `<…>` — non-blank |
| `authorized_by`, `approver`, `reviewer` | operator | `<…>` — non-blank |
| `adapter_identity`, `adapter_version` | operator | `<…>` — confirm against the connector actually used |

### Derived, not chosen

These are **not** operator decisions. They are copied from the selected smoke
scope and verified, never picked:

| field | source |
|---|---|
| `stage` | the selected smoke scope |
| `company_id` | the selected input packet |
| `observation_cutoff_date` | the source-admission cutoff (ADR-046) |
| `corpus_scope` | the packet; the run reads it from there |
| `vertex_location` | the single permitted location constant |

A mismatch between any of these and the authorization is refused at G5 with
`authorization_scope_mismatch`.

## 3. R0 — this document exists and is approved

No values collected yet. Nothing on disk.

## 4. R1 — baseline

Clean worktree, pinned HEAD, expected `data/` file count. Any drift stops here.

## 5. R2 — informational HEAD read

Read `git rev-parse HEAD` and note it as `C_early`. **This value is not
binding.** It is recorded for awareness only, is written nowhere, and takes part
in no comparison. `C_early != C₀` later is a note, not a refusal.

## 6. R3–R5 — inputs and arithmetic

- **R3** — collect §2 as transient local inputs. Verify the derived fields of
  §2 rather than choosing them.
- **R4** — check the budget arithmetic on paper: the effective generate cap is
  derived from the external-request ceiling, the wall-clock ceiling must reach
  the floor implied by that cap, and the output ceiling must reach the declared
  maximum. Failing any of these is `budget_insufficient` at R8 anyway; catching
  it here costs nothing.
- **R5** — check the window: all four instants carry an explicit UTC offset,
  the authorization window is fully contained by the enablement window, and the
  decision does not postdate the declared run instant. Textual comparison of
  timestamps is forbidden; two spellings of one instant are not equal as text.

## 7. R7 — prepare the attempt root

Nine checks. **Rules 1 through 6 exist only here** — the materializer does not
perform any of them.

| # | check | how |
|---|---|---|
| 1 | canonical container | resolve `<repo_root>/artifacts/governance`; create it explicitly if absent, otherwise verify it exists |
| 2 | **direct child** | the normalized/resolved attempt root's parent equals the normalized container. A string prefix test is **not** acceptable: a `..` segment satisfies a prefix test while resolving elsewhere |
| 3 | **no symlink between** | check `artifacts`, `governance` and the attempt-root name individually. A symlinked container leaves the attempt root itself non-symlinked, so the materializer's own check does not see it |
| 4 | single segment | the attempt-root name contains no separator, no `..`, no `.` |
| 5 | grammar | the name matches `gov-<company_id>-<stage>-<nnnn>` with `<nnnn>` four digits |
| 6 | new | `<nnnn>` is unused in the container |
| 7 | real directory | not a file, FIFO or device |
| 8 | not a symlink | the root itself |
| 9 | completely empty | no entry other than `.` and `..`, hidden files included |

**Rules 7, 8 and 9 are repeated by the materializer** as defence in depth.

**Declared scope limit.** Rule 3 inspects components **below the repository
root** only. Platform symlinks above it are not rejected and must not be: on
macOS `/tmp` is itself a symlink, and refusing every symlinked ancestor would
reject ordinary paths. What is verified is the canonical placement beneath the
repository root, not the symlink-freedom of an entire absolute path.

## 8. R7b — the binding `C₀`

**After** R3, R4, R5 and R7 are all complete, and **immediately before** the R8
call, read `git rev-parse HEAD` again as `C₀`. This is the value passed to the
materializer and written into the prompt-qualification record.

Reading it here rather than at R2 means drift that happens while inputs are
being collected is caught while the attempt root is still empty — no record has
been written, and the fix is simply to re-read `C₀` and continue.

## 9. R8 — materialization

Separate authorization required. Produces exactly four write-once records and an
**in-memory** authorization pin. The pin is not a fifth artifact and is written
nowhere.

## 10. G5-pre-A — freshness, over a pin-verified chain

**A₁ — hydrate the chain.** Do not read the prompt-qualification JSON from a
path. Starting from the returned authorization pin and the injected governance
root, walk:

```
authorization pin → live_call_authorization
                  → adapter_enablement_record   (pinned by the authorization)
                  → prompt_qualification_record (pinned by the enablement)
```

Each step goes through the shared containment and SHA-256 discipline: relative
reference required; absolute, drive-qualified, upward-traversing, symlinked and
root-escaping references refused; bytes re-read and the digest compared. Read
`C_rec` from the verified prompt-qualification record.

The authorization does **not** pin the prompt qualification directly — the
enablement does, as a sibling of the adapter qualification — so the walk is the
only correct route.

**A₂ — compare.** Read `git rev-parse HEAD` as `C₁`. Refuse on **any** violation
of the triple equality:

```
C₀ != C_rec   OR   C₁ != C_rec   OR   C₀ != C₁
```

Each tells the operator something different: the first that materialization
recorded a value other than the one fixed at R7b; the second that HEAD moved
after the records were written; the third that HEAD moved between R7b and G5.

**The runtime does not enforce this.** It compares the record's `code_commit`
with the value the caller supplies, and cannot tell whether either is the real
HEAD. The triple equality is a runbook obligation.

### Fail-closed result of A₁ or A₂

- No ADC preflight of either layer.
- No client construction, no provider call, no network call.
- The four governance records are not modified, deleted or overwritten.
- The same attempt root is **not** reused — it is populated, so it is refused.
- The fix is a **new attempt root** followed by **R7b → R8 again**. There is no
  partial repair: `code_commit` sits inside the prompt qualification, whose
  digest the enablement pins, whose digest the authorization pins.

## 11. G5-pre-B — ADC reachability

Runs only after A₁ and A₂ pass.

- **Layer 1** — verify that application default credentials are configured, by
  exit code only. This mints no token and contacts nothing.
- **Layer 2** — verify reachability, by exit code only, with both streams
  discarded. **This requires its own operator authorization**: it contacts the
  identity service and mints a token.

Binding constraints for layer 2: the output is never assigned to a variable,
never echoed, never written to a file, and never recorded in this or any other
tracked document. Only the exit status is reported.

## 12. G5 — the smoke run

Separate authorization required. `governance_artifact_root` is the attempt root
from R8; `run_root` is a separate path that does not exist.

## 13. Fail-closed matrix

| situation | governance root after | run root | extraction artifacts written | provider call |
|---|---|---|---|---|
| R7 container/grammar violation (rules 1–6) | not created or not used | none | 0 | none |
| R7 physical violation (rules 7–9) | unchanged | none | 0 | none |
| drift before R7b (`C_early != C₀`) | still empty | none | 0 | none |
| **R8 success** | **four records** | **none** | **0** | **none** |
| R8 partial write failure | 1, 2 or 3 records | none | 0 | none |
| R8 post-write validation failure | four records, **no pin returned** | none | 0 | none |
| R8 attempt-root violation | unchanged | none | 0 | none |
| **G5-pre-A₁ chain hydration failure** | **unchanged** | **none** | **0** | **none** |
| **G5-pre-A₂ freshness violation** | **unchanged** | **none** | **0** | **none** |
| G5-pre-B layer 1 failure | unchanged | none | 0 | none |
| G5 governance root not supplied | unchanged | none | 0 | none |
| **G5 run root equals the governance root** | **unchanged** | already exists | **0** | **none** |
| G5 refusal before the permit handshake | unchanged | none | 0 | none |
| G5 refusal after the handshake, before the run root | unchanged | none | 0 | the client-contract seam only; no send |
| G5 count-side provider error | unchanged | exists | eight | one count send |
| G5 completed | unchanged | exists | eleven | one count send, one generation |

The governance root is never written by a run. The runner only reads it.

## 14. Deletion event schema and policy

**This document is not a ledger.** It describes the shape of a deletion event
and the policy governing one. No real deletion event, date, attempt-root name or
reason is ever appended here.

A deletion event records these fields:

- date of the deletion
- attempt-root name
- reason class
- approving user

Policy (ADR-050, D2 = R2):

- Deletion requires **explicit user approval**. There is no unattended deletion.
- Successful attempt roots are retained for the duration of the thesis work.
- **Failed and partial attempt roots are retained as evidence** and are not
  deleted. They are already unusable for a retry, because they are not empty.
- Every deletion is recorded as an event with the fields above.

## 15. Retention policy

- **Access owner** — a single operator; the container is narrowly permissioned.
  Whether any synchronization or backup tooling covers that path is confirmed in
  writing at R0.
- **Backup and recovery** — an operator-managed encrypted backup. Recovery means
  restoring the bytes, never regenerating them: `code_commit` alone reproduces
  nothing, because the budget ceilings, windows, identities, people and the
  client contract are operator decisions that no commit encodes. The audit trail
  **is** the four write-once records.
- **Retention period** — successful roots for the duration of the thesis work;
  failed and partial roots likewise, as evidence.
- **Deletion authority** — see §14.

**Ledger boundary.** The exact backup location, the access list and the real
deletion events are held in a protected operator ledger outside this repository.
This document contains none of them, and the ledger's own location does not
appear here either.

## 16. Why these records are not tracked in git

The project identifier is not confined to opaque digests. It appears as
**plaintext inside the endpoint allowlist** of both the live-call authorization
and the adapter enablement record, in full URL form. The contract and routing
digests are one-way; an allowlist entry is not. That is why the four records live
outside version control, and why the retention policy above exists in its place.
