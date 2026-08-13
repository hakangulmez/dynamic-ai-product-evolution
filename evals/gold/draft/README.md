# Draft readings — not gold

Everything in this directory is a **model-authored reading of a source packet**.
None of it is a gold record, and none of it may be used as ground truth.

Gold is created by the methodology owner. `docs/methodology/PROMPT_DEVELOPMENT_AND_EVALUATION_PROTOCOL.md`
assigns "creating and adjudicating gold examples" to the human researcher, and
lists "treating an LLM judge as ground truth" among prohibited practices. These
files exist to be adjudicated, not to be scored against.

Adjudicated gold, when it exists, is written to `evals/gold/`, not here. The
gold protocol in `evals/EVAL_HARNESS.md` requires that original annotations be
preserved after adjudication, so nothing here is deleted once gold is produced.

## The independence requirement is not met

`docs/methodology/VALIDATION_STRATEGY.md` asks for two independent annotators.
That condition is **not satisfied** by the readings held here, for two separate
reasons:

1. **Both readers are Claude.** Two readings from one model family share
   training and failure modes. They are not two observations; they are one
   instrument run twice.
2. **One reader was exposed.** `HUBS_NOW_reading_executor.md` was produced
   inside a session that had already inspected eight consolidation prototypes,
   C4's product list, and the pipeline's own capability and task output for the
   same firm. `HUBS_FY2024_reading_opus.md` and `HUBS_FY2025_reading_opus.md`
   were produced under a written instruction with an explicit forbidden-reading
   list, archived here as `_reading_instruction_opus.md`.

A third reading by a human is what would make an adjudication meaningful. Until
then, agreement between these files is weak evidence and disagreement is the
useful signal.

## Files

| file | reader | source packet | archival header |
|---|---|---|---|
| `HUBS_FY2024_reading_opus.md` | Opus, Claude Code CLI | `srcsnap-hubspot-20241231-sec-v4` | complete, written at reading time |
| `HUBS_FY2025_reading_opus.md` | Opus, Claude Code CLI | `srcsnap-hubspot-20251231-sec-v4` | complete, written at reading time |
| `HUBS_NOW_reading_executor.md` | executor session | `srcsnap-hubspot-20241231-sec-v4` and `srcsnap-servicenow-20251231-sec-v4` | **partial, added retroactively** |
| `_reading_instruction_opus.md` | — | — | the instruction the Opus readings were made under |

## Known order effect

`HUBS_FY2025_reading_opus.md` was produced before `HUBS_FY2024_reading_opus.md`.
The FY2025 filing is dated 2026-02-11, after the FY2024 source-admission cutoff
of 2025-02-12, so the later reading was made by a reader who had already seen a
document that Rule 3 excludes from it. The reader reported this itself and the
FY2024 file carries the note. No FY2025 content was carried across, but the
exposure cannot be undone and is recorded rather than argued away.

## What the readings disagree about

The three readings and the pipeline's own C4 output diverge on a small number of
decisions, and those decisions are what an adjudication would settle:

- `HubSpot customer platform` — product, family, or neither
- `Breeze` — product, family, or capability, and what its derivatives are
- `Payments` — a product or a capability of `Commerce Hub`
  (also recorded as an open decision in `docs/DECISION_LOG.md`)
- `Professional services` — a product or not
- whether a verb-less feature name (`smart content`, `file manager`,
  `team emails`) is a capability at all; this single rule moves the capability
  count by roughly a factor of two and the task-per-capability ratio from 0.29
  to 0.55
- whether an acquired-but-not-yet-shipped function (`Cacheflow` CPQ in FY2024)
  belongs in the period at all

None of these is resolved here.
