"""Stage 00 company-universe entrypoint (local fixtures only).

Governing documents:
- specs/SPEC-001-company-universe.md
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md
- docs/architecture/COMPANY_UNIVERSE_PIPELINE.md
- docs/THESIS_EXECUTION_PLAN.md
- prompts/implementation/phase_0_company_universe.md

Sixty-five mutually exclusive modes, selected by ``--mode`` (default
``sentinel`` so every pre-existing invocation is unchanged):

- ``sentinel`` runs the fixture-driven sentinel described in
  `docs/implementation/COMPANY_UNIVERSE_SENTINEL_V0.md`. It performs no
  network access and accepts only the deterministic mock provider.
- ``frame`` runs the FRAME builder (SPEC-001 Stage A; W1) over either a local
  fixture bundle (``--index-dir``) or an acquisition manifest
  (``--acquisition-manifest``), verifying every acquired raw-file hash before
  parsing. No network access.
- ``acquire-index`` acquires a declared master.idx request plan through the
  fixture-replay transport (default) or, post-W0, the committed ``sec_live``
  transport (``--transport sec-live``), which performs real SEC requests
  under the recorded user-agent, spacing, retry, and timeout contract and
  writes the v0.2 successor manifest.
- ``dera-validate`` validates a completed FRAME run against local DERA FSDS
  SUB files (ADR-081). Independent validation only: DERA never feeds the
  frame. No network access.
- ``acquire-dera`` acquires declared DERA FSDS release ZIP archives
  (ADR-082) through the fixture-replay transport (default) or the committed
  ``sec_live`` transport, preserves raw ZIPs with receipts, extracts exactly
  one ``sub.txt`` member per archive, and writes a bundle that
  ``dera-validate`` consumes unchanged.
- ``acquire-docs`` acquires the baseline annual-report documents of planned
  baseline candidates (ADR-089) through the fixture-replay transport
  (default) or the committed bounded-streaming ``sec_live`` document
  transport, which enforces the plan's ``max_document_bytes`` while
  downloading. ``sec_filename`` is validated provenance; every URL is
  derived in the SEC filing-directory form. Documents only: no packet, no
  screen, no classification.
- ``probe-filing-index`` probes SEC filing-index pages to prove that they
  are a deterministic, type-bearing metadata source for a later two-hop
  packet route (ADR-090). Metadata only: it acquires no primary document,
  builds no packet, and authorizes nothing downstream.
- ``acquire-primary-docs`` acquires primary annual-report documents in two
  bounded hops — filing index, then the type-selected primary HTML — and
  emits the governed ``baseline_primary_document_bundle@0.1.0`` that
  ``build-baseline-packets`` consumes unchanged (ADR-092). Documents only.
- ``build-baseline-packets`` builds Stage 00C baseline evidence packets from
  a local, hash-verified primary-document bundle (ADR-091). Fixture-first and
  offline: it performs no network access, decides no exclusion, and records
  cover-page evidence and the economic subsections as explicitly missing.
- ``determine-asset-backed-issuer-lineage`` determines the asset-backed
  issuer flag for every carrier row of one completed lineage, reading only
  the ADR-101 aggregate it is given (ADR-105/106).
- ``screen-universe-lineage`` runs the production high-recall screen over
  exactly one named v0.5 baseline-packet run (ADR-108): every valid packet
  row is screened under the evidence-minimal prompt, every packet-failure
  row is preserved as a visible insufficient-evidence record with no model
  call, and the run is fail-closed with a governed failure receipt. Only
  the deterministic mock provider exists in this increment.
- ``screen-universe-lineage-live`` is the ADR-108 mode's explicit live
  successor (ADR-109): it screens exactly the rows of one governed selection
  artifact under the default-deny Vertex connector, bound by a screen live
  authorization whose digest, enablement, client contract, endpoints,
  prompt-template hash, packet-manifest hash and caps are all verified
  before a run directory, an SDK import, credential resolution or any
  network send exists. This increment ships offline only: no test builds a
  real SDK client.
- ``screen-universe-lineage-diagnostic`` is the canary-only diagnostic
  successor (ADR-112). It screens exactly one ``canary_100`` selection under
  a *separate* diagnostic authorization contract, applies the identical
  strict row validator, and records a rejected_output row instead of
  aborting when a model output fails validation — so one run measures the
  distribution of failures rather than the first one. It hard-stops exactly
  as the authoritative route does on governance, provider, envelope,
  capture, cap and budget failures, and on its declared rejected-row
  circuit breaker. Its outputs are structurally non-promotable.
- ``select-screen-repair-rows`` derives one governed seven-row
  ``universe_screen_diagnostic_repair_selection`` artifact (ADR-115) from a
  completed source diagnostic run: exactly its quote-resolution rejections,
  in ascending source ordinal order, relationally re-proven against the
  hash-bound source records. Deterministic; no model call, no network.
- ``screen-universe-lineage-diagnostic-repair`` re-screens exactly those
  seven derived rows under the committed v5 diagnostic prompt (ADR-115),
  through a third, repair-specific authorization contract with caps pinned
  to 7 logical / 21 attempts / 28 external requests. Diagnostic measurement
  only: its outputs are structurally non-promotable and every other loader
  refuses them.
- ``screen-universe-lineage-live-v3`` is the long-backoff authoritative
  successor (ADR-117). It is the V5 evidence-safe route with exactly one
  transport dimension changed: each logical packet may spend five
  ``generateContent`` attempts with fixed 15s/30s/60s/120s waits instead of
  three at 1s/2s, and ``countTokens`` remains a single un-retried send. The
  retry triggers are the committed transient conditions unchanged, 429 among
  them; no validation, capture, governance, budget or evidence failure is
  ever retried. Its own authorization and manifest contracts pin the policy
  and the arithmetic — logical x 5 attempts, logical x 6 external requests —
  so a three-attempt grant cannot run here and this grant cannot run on the
  three-attempt routes.
- ``screen-universe-lineage-continuation`` continues exactly one explicitly
  named failed full-cohort run into a fresh authoritative cohort (ADR-118).
  It revalidates the parent's completed prefix from the parent's hash-bound
  raw archive — re-rendering each prompt and re-running the unchanged strict
  validator, so a reused row is held to the same rules as a fresh one — makes
  no provider call for any reused row, and model-calls only the remaining
  suffix. Its connector adds a bounded three-attempt ``countTokens`` retry at
  15s/30s, the failure mode that killed the parent, while inheriting the V3
  five-attempt generate policy unchanged. The parent stays receipt-bearing,
  immutable and permanently non-authoritative; only the new manifest may be
  consumed. There is no discovery: the source run and its receipt digest are
  named on the command line.
- ``screen-universe-lineage-continuation-v2`` continues a run that stopped
  because ``generateContent`` returned an empty body (ADR-119). Its connector
  treats that one anomaly as retryable through the unchanged ADR-117 schedule,
  and its source loader admits an empty-body-stopped continuation only after
  proving the shape from the source's own captures: a real countTokens body for
  the stopping row and no persisted generate body at all. It writes its manifest
  under its own filename, so the earlier authoritative loaders refuse the
  directory until a promotion decision is taken deliberately.
- ``screen-universe-lineage-continuation-v3`` continues a run that stopped
  because ``countTokens`` returned an empty body (ADR-120). It is ADR-119's
  route with the counterpart anomaly closed: the measurement call now retries
  an empty body through the unchanged three-attempt count schedule, and the
  generation is never invoked on such an attempt. Its source loader admits an
  empty-count stop only after proving it from the source's own counters and
  captures — one count attempt for the stopping row, zero generate attempts,
  no stopping-row capture at all, and no empty generate body anywhere.
- ``screen-universe-lineage-continuation-v4`` adds a bounded, visible
  ``PROVIDER_UNRESOLVED`` row outcome (ADR-121). When a provider or transport
  condition has already exhausted the retry path this same grant authorized,
  the row is recorded with its closed reason and attempt telemetry and the run
  continues, rather than one unresolvable row discarding a whole cohort. The
  tolerance is 25 rows and the twenty-sixth stops the run fail-closed. Content,
  evidence, capture, governance and budget failures remain run-fatal and can
  never become provider-unresolved.
- ``build-human-review-overlay`` ingests a reviewer-supplied decision ledger
  covering every unresolved row of one SCREEN release. Evidence is cited as a
  displayed ``P001``-style reference and a contiguous verbatim quote; the
  loader re-derives the canonical passage id from the hash-bound packet and
  resolves the quote there. The release is never edited.
- ``build-classifier-candidate-cohort`` derives, from one release and its
  complete overlay, the rows a classifier may be handed: eligible or boundary,
  from either the screen or a reviewer, with the admission origin on every row.
  No model is called and no judgement is formed.
- ``build-screen-release`` reconciles one completed full-cohort screen and
  one completed repair run into an immutable SCREEN release. It is a
  derivation: no model, provider, prompt or authorization is involved, both
  sources are pinned by digest and left byte-unchanged, and a repair output
  supersedes a base row only where that repair validated.
- ``select-screen-unverified-repair-rows`` derives, from one completed
  continuation-v5 screen, the rows whose evidence never verified. The
  population is every ``model_evidence_unverified`` record, ascending by source
  row ordinal, under the closed rule ``unverified_rows_ascending_ordinal@1``
  and with no status-based filter; the artifact is written write-once and no
  model is called.
- ``classify-universe-cohort-v2-7``, ``classify-universe-cohort-continuation-v2-7``
  and ``classify-universe-calibration-v2-7`` are the ADR-134 successors, and they
  change only what the model is told about its own output. The V2.6 calibration
  completed but spent all five of its unusable allowance on contract violations:
  four ``boundary_flags`` entries written as explanatory sentences that ran past
  160 characters, and one response that omitted ``confidence`` entirely. No bound
  moves in response. The rows that did classify wrote flags of at most 133
  characters, so the ceiling was never the constraint; the failure was a genre
  error, reasoning placed in a label field. The V2.7 prompt therefore says what a
  flag is, and states that ``confidence`` is mandatory in both the contractual
  limits and the closing checklist -- it was the only required axis named in
  neither. The span protocol, the span index, the 0.4.0 axes and record
  contracts, the taxonomy, the tier rules and the null-compatible
  ``tokens_out_reported`` accounting are V2.5's and V2.6's own, unchanged.
- ``classify-universe-cohort-v2-6``, ``classify-universe-cohort-continuation-v2-6``
  and ``classify-universe-calibration-v2-6`` are the ADR-133 successors, and the
  narrowest one yet: nothing the model sees changes. The V2.5 calibration sent
  all forty rows and then refused its own manifest, because one row hit a Vertex
  quota 429, retried successfully, and ``ScreenBudget`` set
  ``tokens_out_reported`` to null -- correctly, since after a retry there is no
  verified total -- while ``request_accounting`` admitted integers only. V2.6
  widens that single property to integer-or-null and marks it required; every
  other accounting property stays integer-only under an unchanged
  ``additionalProperties``. The prompt, the span index, the 0.4.0 axes and
  record contracts, the taxonomy and the tier rules are V2.5's own files reused
  by reference. Budget enforcement cannot weaken: nothing reads
  ``tokens_out_reported``, and the ceilings run off ``tokens_out_accounted``,
  which charges the declared per-call maximum for exactly the unverified rows.
  New authorization and manifest contracts and new filenames exist so a V2.5
  grant cannot drive a V2.6 route and no loader can read one as the other. The
  V2.1 to V2.5 modes stay available and unchanged.
- ``classify-universe-cohort-v2-5``, ``classify-universe-cohort-continuation-v2-5``
  and ``classify-universe-calibration-v2-5`` are the ADR-132 successors, and the
  first to change what the model produces rather than how much. The free-text
  ``quote`` is gone. The model selects a ``span_ref`` naming a sentence or a
  contiguous run of sentences that a pinned deterministic index derived from the
  hash-bound packet, and the pipeline retrieves the exact text. Three live
  calibrations produced ten diagnosed quote failures across five classes -- one
  dropped invisible U+200B, four small visible copy errors, two splices across
  thousands of characters, one correctly copied quote attributed to the wrong
  passage, and one quote roughly 45% composed. Four of those five are
  unreachable when the model never types source characters; the fifth,
  selecting the wrong span, survives on purpose, because it yields authentic
  packet text a human reviewer can adjudicate rather than fabricated evidence.
  The stored row separates the model's selection from the pipeline's
  resolution by name, and carries the span's offsets and digest so it stays
  verifiable without re-running the segmenter. The economic axes, the tier
  rules, the 12-object evidence ceiling and the 300-character
  ``supported_claim`` bound are unchanged. Unlike the V2.3-to-V2.4 widening the
  rejection is bidirectional and structural: a V2.4 response carries ``quote``
  and fails the 0.4.0 axes contract, a V2.5 response carries ``span_ref`` and
  fails 0.3.0's. The V2.1 to V2.4 modes stay available and unchanged.
- ``classify-universe-cohort-v2-4``, ``classify-universe-cohort-continuation-v2-4``
  and ``classify-universe-calibration-v2-4`` are the ADR-130 successors: one
  bound moves and the instruction moves with it. The V2.3 calibration stopped
  after three rows, and every one of the three carried exactly one schema error
  -- a ``supported_claim`` of 233, 204 and 204 characters against a
  200-character cap -- while their quote lengths (972, 829, 994) and evidence
  counts (12, 12, 8) sat inside the 0.2.0 ceilings and all 32 evidence objects
  carried legal axis labels. So ``supported_claim`` rises to 300 and nothing
  else about the axes moves: ``evidence`` stays at 12, ``quote`` at 1200, and
  the tier rules are untouched. Two of the three rows also wrote a quote that
  did not resolve verbatim -- one splicing two real spans with an ellipsis, one
  prepending a subject the passage does not carry -- which no bound can fix, so
  the V2.4 prompt forbids ellipsis, splice, insertion, deletion and re-casing
  by name, requires ``supported_claim`` to be a conclusion clause rather than
  explanatory prose, and requires a per-axis evidence count. Because the axes
  contract changes, the record contract that inlines it changes too and
  ``taxonomy_version`` becomes ``universe_classifier_axes_v2_4``. Note that
  0.3.0 is a *widening* of 0.2.0, so a V2.3 output would satisfy the V2.4 axes
  schema: what separates the versions is the route's output filenames and the
  ``prompt_template_path`` and ``output_contract`` consts, which reject in both
  directions. The V2.1, V2.2 and V2.3 modes stay available and unchanged.
- ``classify-universe-cohort-v2-3``, ``classify-universe-cohort-continuation-v2-3`` and
  ``classify-universe-calibration-v2-3`` are the ADR-129 successors: a
  prompt-discipline increment, not another ceiling increase. The V2.2
  calibration stopped with three of four rows rejected, and none of the three
  was something a wider bound would fix -- the model over-cited (15, 15 and 13
  evidence objects against a cap of 12), wrote quotes instead of copying them
  so they no longer occurred in the passage cited, and put output JSON field
  names such as ``software_centrality`` into ``evidence.axis``. V2.3 therefore
  keeps the 0.2.0 axes and record contracts, the taxonomy version, the tier
  rules and the 12/1200 ceilings byte-unchanged, and changes only the prompt:
  quoting is stated as a copy operation with an ordered locate-copy-verify
  sequence, evidence is declared a sparse support set of at most two objects
  per axis, and the six legal ``evidence.axis`` labels are listed literally
  with output field names forbidden there. They carry their own authorization
  and manifest contracts solely because the prompt path is a const, plus their
  own output filenames so no loader can read a V2.3 run as a V2.2 one. The
  V2.1 and V2.2 modes stay available and unchanged.
- ``classify-universe-cohort-v2-2``, ``classify-universe-cohort-continuation-v2-2`` and
  ``classify-universe-calibration-v2-2`` are the ADR-128 successors of the three
  classifier modes above. The first calibration stopped after three rows: all
  three responses were valid JSON with valid axes and were refused on output
  size alone -- ``evidence`` capped at 6 against a six-value axis vocabulary,
  and ``quote`` capped at 300 characters against legitimate contiguous Item 1
  spans reaching 972. V2.2 raises those two ceilings to 12 and 1200, restates
  every bound in the prompt's final self-check, and requires the shortest
  *sufficient* span rather than the shortest span. The economic axes and the
  tier rules are byte-unchanged; ``taxonomy_version`` moves only to name the
  axes-contract identity. Each successor carries its own prompt, axes and
  record contracts, its own authorization and manifest contracts and its own
  output filenames, so a V2.1 loader refuses a V2.2 run and vice versa. The
  V2.1 modes stay available and unchanged, because a V2.1 run's evidence must
  remain interpretable under the contract it ran under.
- ``select-classifier-calibration-rows`` derives the ADR-127 calibration
  selection: a closed, seeded, stratified sample of the immutable classifier
  candidate cohort, drawn under a digest-pinned strata config that carries the
  quotas and the seed. Nine strata partition the cohort exactly; the
  reviewer-admitted rows are their own stratum, because no screen output and so
  no archetype signal exists for them, and they are deliberately over-weighted.
  The strata come from SCREEN_v1 candidate archetypes and are sample design
  only: never truth about a firm, never a tier input. Deterministic and
  offline: no model call, and the selection size is derived from the config
  rather than written down.
- ``select-classifier-pilot-rows`` materializes the ADR-137 ten-firm pilot
  selection: the committed ``PILOT_ROWS`` list, resolved against the candidate
  cohort and the 40-row calibration selection those ten are a chosen subset of.
  It accepts no row argument, so changing which firms the pilot covers means
  editing a committed constant. It pins the cohort manifest and the source
  selection by digest, cross-binds the two, validates the pilot selection
  contract and writes once. Deterministic and offline: no model call.
- ``classify-software-universe-pilot-v1`` runs the governed live firm-level
  pilot over exactly those ten filings (ADR-137). It is not a V2.x route and no
  V2.x loader can read it: its own authorization and manifest contracts, its own
  output filenames, its own run root. It derives no tier, holds no tier rules
  and states no bounded-outcome tolerance -- an unusable model response costs one
  row, recorded as ``review_uncertain`` with a reason, while a genuine provider
  failure stops the run and writes a receipt rather than being stored as a
  judgement. Its dry run resolves all ten inputs and reports the derived caps
  without constructing a provider client or writing anything.
- ``classify-software-universe-pilot-v2`` runs the same four-axis Item 1 pilot
  against the ADR-139 selection drawn directly from the annual-coverage cohort.
  It has its own authorization, manifest and filenames, so it cannot consume a
 - ``classify-software-universe-pilot-v3`` asks the narrower two-axis Item 1
 - ``classify-software-universe-pilot-v4`` asks whether the firm sells a separately identifiable digital product before assessing its centrality.
   universe-gate question over that same annual-coverage selection.
  V1 selection or be read by a V1 loader. It still derives no tier and writes
  no membership decision.
- ``build-annual-coverage-cohort`` derives the ADR-138 annual filing-year
  coverage restriction over the immutable candidate cohort. Model-free and
  deterministic: it reads the cohort and both hash-bound FRAME annual-filer
  inventories, and keeps a firm when it filed an annual report in every calendar
  filing year from 2022 through 2025. A 2021 filing is recorded and never
  required, and no filing after 2025 bears on eligibility. It writes two immutable
  artifacts -- the kept firms and, separately, every dropped firm with the years it
  filed and the required years it did not -- so nothing is discarded. The result is
  an analysis-eligibility cohort, not a software universe and not a classifier
  result: it runs AFTER the historical high-recall screen, carries every firm's
  screen verdict and review provenance through unchanged, and its manifest states
  that the rule selects a survivor / continuing-reporter sample.
- ``classify-universe-calibration`` runs the governed live classifier over exactly
  that selection (ADR-127). It binds the identical prompt bytes, tier-rule
  bytes, cohort, overlay, release and packet chain the full run will use, so
  what it observes is what the full run would do. It is structurally
  unconfusable with the full run: its own manifest contract and filenames, its
  own run root, ``promotable`` and ``covers_full_cohort`` both false, and a row
  count the preflight proves is strictly below the cohort's. Its three
  bounded-outcome tolerances are stated for this sample alone.
- ``build-classifier-calibration-review-v2-2`` through
  ``build-classifier-calibration-review-v2-6`` are the same gate over a
  V2.2 through V2.6 calibration run. The review contract is version-neutral -- it
  binds the source manifest and prompt digests rather than naming a prompt --
  so one builder reads all six, and only the manifest and records filenames
  it opens differ. A calibration loader accepts exactly its own version's
  completed run and refuses the others, so a review can never be built
  from a run of a different version than the mode names.
- ``build-classifier-calibration-review`` derives the qualitative gate from one
  completed calibration run: it nominates *every* selected row for human
  reading with its tier, the rule that fired, its evidence quotes and any
  contradiction of the admission it entered on. It records no accuracy or
  pass/fail figure, and its contract has no field for one -- there is no gold
  set and the sample cannot estimate a rate. The gate is passed by a recorded
  human decision or not at all. Deterministic and offline.
- ``classify-universe-cohort`` runs the governed live Company-Universe
  Classifier V2.1 over one immutable classifier candidate cohort (ADR-126).
  Each row is judged against its complete baseline Item 1 packet; the
  admission that put the firm in the cohort — a validated model screen or a
  hash-bound human-review decision — is rendered as explicitly
  non-authoritative context the model may contradict. The model returns axes
  only: a versioned deterministic engine derives the tier and stores its full
  rule trace, so a prompt revision can never move tier membership.
  Provider-unresolved, truncated and unusable outputs are bounded by
  authorization parameters with no default. Nothing runs until the cohort,
  overlay, release, packet, prompt, tier-rule, route, contract, endpoint and
  cap bindings are all proven, ahead of any run directory or SDK import.
- ``classify-universe-cohort-continuation`` is that route's immutable-prefix
  successor (ADR-126). It reuses one explicitly named failed classifier run's
  archived responses — revalidating and re-tiering every one of them rather
  than copying an outcome — and model-calls only the rows that remain. It
  refuses a source whose archive is not a contiguous prefix of the cohort,
  which includes any source that carried a provider-unresolved or truncated
  row before it stopped.
- ``screen-universe-unverified-repair`` re-asks exactly those rows under the
  narrow evidence-binding prompt successor. Each row is screened afresh from
  its packet: no earlier status, quote, reference or failure reason reaches the
  model. The run is structurally non-promotable and produces no release.
- ``screen-universe-lineage-continuation-v5`` adds a bounded, visible
  ``MODEL_OUTPUT_TRUNCATED`` row outcome (ADR-122). A generation that returns
  one candidate with ``finishReason: MAX_TOKENS`` produced a well-formed
  envelope the model never finished, so no screen JSON exists to judge. Such a
  row is recorded with the closed reason ``max_tokens`` and the digest of its
  captured envelope, is never re-sent, and never reaches the classifier. Its
  source's stopping row is re-derived from that run's own capture rather than
  re-called, so live sending resumes at the row after it. The tolerance is 25
  and the twenty-sixth stops the run fail-closed.
- ``select-screen-rows`` builds one governed ``universe_screen_selection``
  artifact (ADR-109): a seeded, stratified, packet-native canary_100
  enumeration of exactly one hundred rows, or the explicitly different
  full_cohort mode that enumerates nothing because the packet manifest is
  the row authority. Deterministic; no model call, no network.
- ``determine-shell-company`` reads exactly one cover-page fact,
  ``dei:EntityShellCompany``, from a local hash-verified primary-document
  bundle and emits one governed determination per carrier row (ADR-094). It
  sets no other issuer flag, fetches nothing, and excludes only on a true
  determination.
- ``baseline-carrier`` derives the Stage 00B firm-level baseline carrier
  (W2-A, ADR-088) from a completed FRAME run: hash-verified read-only frame
  consumption, per-stratum CIK grouping, baseline-filing selection against
  the W0-frozen cutoff in ``configs/project.yaml``. No exclusions, no DERA,
  no network access.

Examples:
    python pipelines/00_build_company_universe.py \
        --config configs/universe_sample_rules.yaml \
        --input evals/fixtures/universe_sentinel \
        --output-dir data/runs/universe-sentinel \
        --run-id sentinel-demo --seed 42 --provider mock

    python pipelines/00_build_company_universe.py --mode frame \
        --config configs/project.yaml \
        --index-dir evals/fixtures/edgar_full_index \
        --filing-window-start 2022-08-01 --filing-window-end 2023-02-28 \
        --output-dir data/runs/frame-fixture --run-id frame-demo

    python pipelines/00_build_company_universe.py --mode acquire-index \
        --request-plan evals/fixtures/edgar_index_request_plan/request_plan.json \
        --replay-dir evals/fixtures/edgar_full_index \
        --output-dir data/runs/index-acquisition --run-id acquire-demo
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

#: The three W3 queue stages. Each is separately gated: planning writes no
#: request, execution authorizes only the shard indices it is given, and
#: aggregation is its own command.
QUEUE_MODES = frozenset({
    "plan-acquisition-queue",
    "execute-acquisition-queue",
    "aggregate-acquisition-queue",
    # ADR-101. A fourth stage, not a widening of the third: the v0.1
    # aggregate keeps its single-run contract, and this one covers a lineage
    # assembled from explicitly enumerated execution runs.
    "aggregate-acquisition-lineage",
})
sys.path.insert(0, str(REPO_ROOT / "src"))

from dynamic_ai_products.universe.frame import (  # noqa: E402
    FrameInputError,
    FrameReconciliationError,
    run_frame_builder,
)
from dynamic_ai_products.sec_index_transport import (  # noqa: E402
    SEC_LIVE_TRANSPORT_IDENTITY,
    make_sec_live_transport,
)
from dynamic_ai_products.universe.frame_acquisition import (  # noqa: E402
    AcquisitionPlanError,
    make_fixture_replay_transport,
    run_index_acquisition,
)
from dynamic_ai_products.universe.dera_acquisition import (  # noqa: E402
    DeraPlanError,
    make_dera_fixture_replay_transport,
    run_dera_acquisition,
)
from dynamic_ai_products.universe.baseline_carrier import (  # noqa: E402
    CarrierInputError,
    CarrierReconciliationError,
    run_baseline_carrier,
)
from dynamic_ai_products.universe.document_acquisition import (  # noqa: E402
    DocumentPlanError,
    load_document_request_plan,
    make_document_fixture_replay_transport,
    run_document_acquisition,
)
from dynamic_ai_products.sec_document_transport import (  # noqa: E402
    SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    make_sec_live_document_transport,
)
from dynamic_ai_products.ingestion.baseline_packet import (  # noqa: E402
    PacketBundleError,
    run_baseline_packet_build,
)
from dynamic_ai_products.ingestion.lineage_packet import (  # noqa: E402
    run_lineage_packet_build,
    run_lineage_packet_build_v2,
)
from dynamic_ai_products.ingestion.asset_backed_determination import (  # noqa: E402
    AssetBackedDeterminationError,
    run_asset_backed_determination,
)
from dynamic_ai_products.ingestion.shell_company_determination import (  # noqa: E402
    ShellDeterminationError,
    run_lineage_shell_company_determination,
    run_shell_company_determination,
)
from dynamic_ai_products.universe.acquisition_queue import (
    AcquisitionQueueError,
    run_lineage_aggregator,
    run_queue_aggregator,
    run_queue_executor,
    run_queue_planner,
)
from dynamic_ai_products.universe.primary_document_acquisition import (  # noqa: E402
    PrimaryDocumentPlanError,
    load_request_plan as load_primary_document_plan,
    make_primary_document_fixture_replay_transport,
    run_primary_document_acquisition,
)
from dynamic_ai_products.universe.filing_index_probe import (  # noqa: E402
    ProbePlanError,
    load_probe_plan,
    make_filing_index_fixture_replay_transport,
    run_filing_index_probe,
)
from dynamic_ai_products.universe.frame_dera_validation import (  # noqa: E402
    DeraInputError,
    run_dera_validation,
)
from dynamic_ai_products.universe.freeze import FreezeBlockedError  # noqa: E402
from dynamic_ai_products.universe.lineage_screen import (  # noqa: E402
    MockLineageScreenProvider,
    ScreenInputError,
    _sha256,
    run_lineage_screen,
)
from dynamic_ai_products.lineage_screen_diagnostic import (  # noqa: E402
    run_lineage_screen_diagnostic,
)
from dynamic_ai_products.lineage_screen_diagnostic_repair import (  # noqa: E402
    build_repair_selection,
    run_lineage_screen_diagnostic_repair,
)
from dynamic_ai_products.lineage_screen_live import (  # noqa: E402
    build_screen_selection,
    run_lineage_screen_live,
)
from dynamic_ai_products.lineage_screen_live_v2 import (  # noqa: E402
    run_lineage_screen_live_v2,
)
from dynamic_ai_products.lineage_screen_live_v3 import (  # noqa: E402
    run_lineage_screen_live_v3,
)
from dynamic_ai_products.lineage_screen_continuation import (  # noqa: E402
    run_lineage_screen_continuation,
)
from dynamic_ai_products.lineage_screen_continuation_v2 import (  # noqa: E402
    run_lineage_screen_continuation_v2,
)
from dynamic_ai_products.lineage_screen_continuation_v3 import (  # noqa: E402
    run_lineage_screen_continuation_v3,
)
from dynamic_ai_products.lineage_screen_continuation_v4 import (  # noqa: E402
    run_lineage_screen_continuation_v4,
)
from dynamic_ai_products.classifier_candidate_cohort import (  # noqa: E402
    build_classifier_candidate_cohort,
)
from dynamic_ai_products.classifier_tier_engine import (  # noqa: E402
    TierRulesError,
)
from dynamic_ai_products.classifier_calibration_selection import (  # noqa: E402
    CALIBRATION_SELECTION_FILENAME,
    StrataRulesError,
    build_calibration_selection,
)
from dynamic_ai_products.classifier_calibration_review import (  # noqa: E402
    REVIEW_FILENAME,
    build_calibration_review,
)
from dynamic_ai_products.classifier_annual_coverage_cohort import (  # noqa: E402
    build_annual_coverage_cohort,
)
from dynamic_ai_products.classifier_pilot_selection import (  # noqa: E402
    PILOT_SELECTION_FILENAME,
    build_pilot_selection_artifact,
)
from dynamic_ai_products.classifier_pilot_selection_v2 import (  # noqa: E402
    PILOT_SELECTION_V2_FILENAME,
    build_pilot_selection_v2_artifact,
)
from dynamic_ai_products.lineage_classifier_pilot_v1 import (  # noqa: E402
    run_lineage_classifier_pilot_v1,
)
from dynamic_ai_products.lineage_classifier_pilot_v2 import (  # noqa: E402
    run_lineage_classifier_pilot_v2,
)
from dynamic_ai_products.lineage_classifier_pilot_v3 import (  # noqa: E402
    run_lineage_classifier_pilot_v3,
)
from dynamic_ai_products.lineage_classifier_pilot_v4 import (  # noqa: E402
    run_lineage_classifier_pilot_v4,
)
from dynamic_ai_products.lineage_classifier_pilot_v5 import (  # noqa: E402
    run_lineage_classifier_pilot_v5,
)
from dynamic_ai_products.lineage_classifier_pilot_v6 import (  # noqa: E402
    run_lineage_classifier_pilot_v6,
)
from dynamic_ai_products.lineage_classifier_calibration import (  # noqa: E402
    CALIBRATION_ROUTE,
    CALIBRATION_ROUTE_V2_2,
    CALIBRATION_ROUTE_V2_3,
    CALIBRATION_ROUTE_V2_4,
    CALIBRATION_ROUTE_V2_5,
    CALIBRATION_ROUTE_V2_6,
    CALIBRATION_ROUTE_V2_7,
    CALIBRATION_ROUTE_V2_8,
    CALIBRATION_ROUTE_V2_9,
    run_lineage_classifier_calibration,
)
from dynamic_ai_products.lineage_classifier_v2_1 import (  # noqa: E402
    BASE_ROUTE,
    BASE_ROUTE_V2_2,
    BASE_ROUTE_V2_3,
    BASE_ROUTE_V2_4,
    BASE_ROUTE_V2_5,
    BASE_ROUTE_V2_6,
    BASE_ROUTE_V2_7,
    BASE_ROUTE_V2_8,
    BASE_ROUTE_V2_9,
    run_lineage_classifier,
)
from dynamic_ai_products.lineage_classifier_continuation import (  # noqa: E402
    CONTINUATION_ROUTE,
    CONTINUATION_ROUTE_V2_2,
    CONTINUATION_ROUTE_V2_3,
    CONTINUATION_ROUTE_V2_4,
    CONTINUATION_ROUTE_V2_5,
    CONTINUATION_ROUTE_V2_6,
    CONTINUATION_ROUTE_V2_7,
    CONTINUATION_ROUTE_V2_8,
    CONTINUATION_ROUTE_V2_9,
    run_lineage_classifier_continuation,
)
from dynamic_ai_products.human_review_overlay import (  # noqa: E402
    build_human_review_overlay,
)
from dynamic_ai_products.lineage_screen_release import (  # noqa: E402
    build_screen_release,
)
from dynamic_ai_products.lineage_screen_repair import (  # noqa: E402
    REPAIR_SELECTION_FILENAME,
    build_repair_selection as build_unverified_repair_selection,
    run_lineage_screen_repair,
)
from dynamic_ai_products.lineage_screen_continuation_v5 import (  # noqa: E402
    run_lineage_screen_continuation_v5,
)
from dynamic_ai_products.universe.runner import (  # noqa: E402
    FixtureError,
    run_universe_sentinel,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="00_build_company_universe",
        description=(
            "Run Stage 00 over local fixtures: the company-universe sentinel "
            "(default), the EDGAR full-index FRAME builder, or the "
            "fixture-replay index acquisition."
        ),
    )
    parser.add_argument(
        "--mode", default="sentinel",
        choices=["sentinel", "frame", "acquire-index", "dera-validate",
                 "acquire-dera", "baseline-carrier", "acquire-docs",
                 "probe-filing-index", "build-baseline-packets",
                 "acquire-primary-docs", "determine-shell-company",
                 "determine-shell-company-lineage",
                 "determine-asset-backed-issuer-lineage",
                 "build-baseline-packets-lineage",
                 "build-baseline-packets-lineage-v2",
                 "screen-universe-lineage",
                 "screen-universe-lineage-live",
                 "screen-universe-lineage-live-v2",
                 "screen-universe-lineage-live-v3",
                 "screen-universe-lineage-continuation",
                 "screen-universe-lineage-continuation-v2",
                 "screen-universe-lineage-continuation-v3",
                 "screen-universe-lineage-continuation-v4",
                 "screen-universe-lineage-continuation-v5",
                 "screen-universe-lineage-diagnostic",
                 "screen-universe-lineage-diagnostic-repair",
                 "select-screen-repair-rows",
                 "select-screen-rows",
                 "select-screen-unverified-repair-rows",
                 "screen-universe-unverified-repair",
                 "build-screen-release",
                 "build-human-review-overlay",
                 "build-classifier-candidate-cohort",
                 "classify-universe-cohort",
                 "classify-universe-cohort-continuation",
                 "classify-universe-cohort-v2-2",
                 "classify-universe-cohort-continuation-v2-2",
                 "classify-universe-calibration-v2-2",
                 "classify-universe-cohort-v2-3",
                 "classify-universe-cohort-continuation-v2-3",
                 "classify-universe-calibration-v2-3",
                 "classify-universe-cohort-v2-4",
                 "classify-universe-cohort-continuation-v2-4",
                 "classify-universe-calibration-v2-4",
                 "classify-universe-cohort-v2-5",
                 "classify-universe-cohort-continuation-v2-5",
                 "classify-universe-calibration-v2-5",
                 "classify-universe-cohort-v2-6",
                 "classify-universe-cohort-continuation-v2-6",
                 "classify-universe-calibration-v2-6",
                 "classify-universe-cohort-v2-7",
                 "classify-universe-cohort-continuation-v2-7",
                 "classify-universe-calibration-v2-7",
                 "classify-universe-cohort-v2-8",
                 "classify-universe-cohort-continuation-v2-8",
                 "classify-universe-calibration-v2-8",
                 "classify-universe-cohort-v2-9",
                 "classify-universe-cohort-continuation-v2-9",
                 "classify-universe-calibration-v2-9",
                 "select-classifier-calibration-rows",
                 "classify-universe-calibration",
                 "select-classifier-pilot-rows",
                 "select-classifier-pilot-rows-v2",
                 "classify-software-universe-pilot-v1",
                 "classify-software-universe-pilot-v2",
                 "classify-software-universe-pilot-v3",
                 "classify-software-universe-pilot-v4",
                 "classify-software-universe-pilot-v5",
                 "classify-software-universe-pilot-v6",
                 "build-annual-coverage-cohort",
                 "build-classifier-calibration-review",
                 "build-classifier-calibration-review-v2-2",
                 "build-classifier-calibration-review-v2-3",
                 "build-classifier-calibration-review-v2-4",
                 "build-classifier-calibration-review-v2-5",
                 "build-classifier-calibration-review-v2-6",
                 "build-classifier-calibration-review-v2-7",
                 "build-classifier-calibration-review-v2-8",
                 "build-classifier-calibration-review-v2-9",
                 "plan-acquisition-queue", "execute-acquisition-queue",
                 "aggregate-acquisition-queue",
                 "aggregate-acquisition-lineage"],
        help="Stage 00 sub-pipeline to run (default: sentinel).",
    )
    parser.add_argument(
        "--config", default=None,
        help=(
            "Sentinel mode: the versioned sample-rule config "
            "(configs/universe_sample_rules.yaml). Frame mode: the project "
            "config carrying the universe form scopes (configs/project.yaml). "
            "Baseline-carrier mode: the project config carrying the "
            "W0-frozen universe.baseline_cutoff (configs/project.yaml). "
            "Not accepted in acquire-index mode."
        ),
    )
    parser.add_argument(
        "--input", default=None,
        help="Sentinel mode only: local fixture bundle directory "
             "(see evals/fixtures/universe_sentinel).",
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Directory under which the immutable run directory <output-dir>/<run-id> is created.",
    )
    parser.add_argument("--run-id", required=True, help="Unique run identifier; never reused.")
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Sentinel mode only: seed for the reproducible stratified "
             "negative-audit sample (default 42).",
    )
    parser.add_argument(
        "--provider", default=None, choices=["mock"],
        help="Sentinel and screen-universe-lineage modes: only the "
             "deterministic 'mock' fixture-replay provider exists in this "
             "phase.",
    )
    parser.add_argument(
        "--pilot-selection", default=None,
        help=(
            "classify-software-universe-pilot-v1 mode: the immutable ten-row "
            "pilot selection artifact "
            "(universe_classifier_pilot_selection.json) the grant pins by "
            "digest. Refused by every other mode."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate inputs and compute results without writing any output files.",
    )
    parser.add_argument(
        "--index-dir", default=None,
        help="Frame mode: directory of master.idx fixture files plus "
             "fixture_manifest.json (see evals/fixtures/edgar_full_index). "
             "Mutually exclusive with --acquisition-manifest.",
    )
    parser.add_argument(
        "--filing-window-start", default=None, metavar="YYYY-MM-DD",
        help="Frame mode only: earliest admitted filing date. No default.",
    )
    parser.add_argument(
        "--filing-window-end", default=None, metavar="YYYY-MM-DD",
        help="Frame mode only: latest admitted filing date. No default.",
    )
    parser.add_argument(
        "--acquisition-manifest", default=None,
        help="Frame mode: path to an edgar_index_acquisition_manifest.json; "
             "raw-file hashes are verified before parsing and the frame "
             "version is the code-owned label. Mutually exclusive with "
             "--index-dir.",
    )
    parser.add_argument(
        "--request-plan", default=None,
        help="Acquire-index, acquire-dera, and acquire-docs modes: path to "
             "the declared request plan — master.idx requests "
             "(evals/fixtures/edgar_index_request_plan), DERA FSDS release "
             "archives, or baseline filing documents "
             "(configs/baseline_doc_canary_request_plan.json).",
    )
    parser.add_argument(
        "--replay-dir", default=None,
        help="Acquire-index, acquire-dera, and acquire-docs modes with the "
             "fixture transport: directory whose local files the "
             "fixture-replay transport serves.",
    )
    parser.add_argument(
        "--transport", default=None, choices=["fixture", "sec-live"],
        help="Acquire-index, acquire-dera, and acquire-docs modes: transport "
             "binding (default: fixture). 'sec-live' performs real SEC "
             "requests under the committed sec_live contract and writes the "
             "v0.2 manifest; acquire-docs uses the bounded streaming "
             "document transport, which enforces the plan's "
             "max_document_bytes while downloading.",
    )
    parser.add_argument(
        "--bundle-dir", default=None,
        help="Build-baseline-packets mode only: directory holding "
             "bundle_manifest.json and the local primary documents it "
             "describes (see evals/fixtures/baseline_packets).",
    )
    parser.add_argument(
        "--frame-manifest", default=None,
        help="Dera-validate and baseline-carrier modes: path to a completed "
             "FRAME run's filer_frame_manifest.json.",
    )
    parser.add_argument(
        "--frame-manifest-sha256", default=None,
        help="Build-annual-coverage-cohort mode only: the digest the FRAME "
             "manifest must hash to. Refused by every other mode.",
    )
    parser.add_argument(
        "--dera-dir", default=None,
        help="Dera-validate mode only: directory of local DERA FSDS SUB "
             "files plus fixture_manifest.json (see evals/fixtures/dera_fsds).",
    )
    parser.add_argument(
        "--queue-definition", default=None,
        help="Queue modes: the committed, immutable acquisition queue "
             "definition. Naming it is what makes shard membership "
             "reproducible; possessing it authorizes no request.",
    )
    parser.add_argument(
        "--plan-dir", default=None,
        help="Execute-acquisition-queue mode only: the planner run directory "
             "holding the persisted shard-plan artefacts. The executor runs "
             "persisted plans, never ephemeral or hand-supplied ones.",
    )
    parser.add_argument(
        "--shard-indices", default=None,
        help="Execute-acquisition-queue mode only: an explicit, comma-"
             "separated allowlist such as '0,3,7'. Required. There is no "
             "value that expands to the whole queue.",
    )
    parser.add_argument(
        "--expected-request-count", type=int, default=None,
        help="Execute-acquisition-queue mode only: the exact number of "
             "requests the named shards will make. Must equal the computed "
             "total, so the scale being authorized is stated, not discovered.",
    )
    parser.add_argument(
        "--on-shard-failure", default=None, choices=["stop", "continue"],
        help="Execute-acquisition-queue mode only: the stop policy, declared "
             "by the operator and never defaulted.",
    )
    parser.add_argument(
        "--shard-output-dir", default=None,
        help="Queue modes: the root holding per-shard run directories.",
    )
    parser.add_argument(
        "--execution-run-id", default=None,
        help="Aggregate-acquisition-queue mode only: the execution run id "
             "whose shard directories are being aggregated.",
    )
    parser.add_argument(
        "--aggregate-manifest", default=None,
        help="Determine-shell-company-lineage mode only: the path of one "
             "ADR-101 acquisition_queue_aggregate_manifest@0.2.0. It is the "
             "sole authority root and the only data location this mode "
             "accepts: every shard directory read comes from inside it.",
    )
    parser.add_argument(
        "--shell-determination-manifest", default=None,
        help="Build-baseline-packets-lineage mode only: the path of one "
             "ADR-102 shell_company_determination_manifest@0.3.0. Its "
             "determinations decide which rows are excluded (shell true) and "
             "which are retained (false and unknown alike).",
    )
    parser.add_argument(
        "--asset-backed-determination-manifest", default=None,
        help="Build-baseline-packets-lineage-v2 mode only: the path of one "
             "ADR-105 asset_backed_issuer_determination manifest. Its "
             "determinations join the shell determination in deciding which "
             "rows are excluded (either true excludes; false and unknown "
             "are retained).",
    )
    parser.add_argument(
        "--item-one-locator", default=None,
        help="Build-baseline-packets-lineage mode only, required: the HTML "
             "Item 1 locator, selected from the closed mapping "
             "item_one_span_v2 | item_one_span_v3. Exact match; an unmapped "
             "value is refused before any output directory exists. The "
             "plain-text route is selector-independent.",
    )
    parser.add_argument(
        "--packet-manifest", default=None,
        help="Screen-universe-lineage mode only: the path of one v0.5 "
             "baseline_packet_manifest.json. It is the sole input authority "
             "and the only data location this mode accepts: its JSONLs are "
             "re-hashed against its own output_hashes before anything runs.",
    )
    parser.add_argument(
        "--screen-fixture", default=None,
        help="Screen-universe-lineage mode only: the mock provider's fixture "
             "file of precomputed raw responses keyed by 'cik:accession'. "
             "The only provider of this increment is the deterministic mock.",
    )
    parser.add_argument(
        "--logical-request-cap", type=int, default=None,
        help="Screen-universe-lineage mode only: the exact number of logical "
             "model requests, one per valid packet row. Must equal the "
             "packet run's packet count, so the scale being authorized is "
             "stated, not discovered.",
    )
    parser.add_argument(
        "--provider-attempt-cap", type=int, default=None,
        help="Screen-universe-lineage mode only: the separately declared "
             "provider attempt ceiling, logical cap times (1 + the bounded "
             "transient retry count). Retries never create another logical "
             "record.",
    )
    parser.add_argument(
        "--selection-artifact", default=None,
        help="Screen-universe-lineage-live mode only: the path of one "
             "universe_screen_selection artifact. The live screen runs "
             "exactly its rows (canary_100) or the full cohort it names "
             "(full_cohort); no other row source exists.",
    )
    parser.add_argument(
        "--governance-root", default=None,
        help="Screen-universe-lineage-live mode only: the explicit directory "
             "holding the screen live authorization and its enablement. "
             "There is no ambient, cwd, or environment fallback.",
    )
    parser.add_argument(
        "--screen-authorization", default=None,
        help="Screen-universe-lineage-live mode only: the authorization's "
             "path relative to --governance-root.",
    )
    parser.add_argument(
        "--screen-authorization-sha256", default=None,
        help="Screen-universe-lineage-live mode only: the expected SHA-256 "
             "of the authorization bytes — the operator states the digest "
             "half of the handshake explicitly.",
    )
    parser.add_argument(
        "--source-run-dir", default=None,
        help="Screen-universe-lineage-continuation mode only: the explicitly "
             "named failed run whose completed prefix is reused. Never "
             "discovered, never globbed, and never mutated.",
    )
    parser.add_argument(
        "--source-receipt-sha256", default=None,
        help="Screen-universe-lineage-continuation mode only: the expected "
             "SHA-256 of that run's failure receipt — the operator states "
             "which failure is being continued.",
    )
    parser.add_argument(
        "--release-manifest", default=None,
        help="Overlay and cohort modes only: the SCREEN release's "
             "universe_screen_release_manifest.json.",
    )
    parser.add_argument(
        "--release-manifest-sha256", default=None,
        help="Overlay and cohort modes only: the pinned digest of that "
             "release manifest.",
    )
    parser.add_argument(
        "--decision-ledger", default=None,
        help="Build-human-review-overlay mode only: the reviewer-supplied "
             "decision ledger covering every unresolved release row.",
    )
    parser.add_argument(
        "--cohort-manifest-sha256", default=None,
        help="Expected sha256 of the classifier candidate cohort manifest. "
             "Calibration selection mode only: a classifier run takes this "
             "digest from its authorization.",
    )
    parser.add_argument(
        "--calibration-selection", default=None,
        help="Path to a calibration selection artifact. Used by the calibration "
             "run and review modes only; its digest is pinned by the "
             "authorization or passed with --calibration-selection-sha256.",
    )
    parser.add_argument(
        "--calibration-selection-sha256", default=None,
        help="Expected sha256 of the calibration selection. Review mode only: "
             "a calibration run takes the digest from its authorization.",
    )
    parser.add_argument(
        "--calibration-run-dir", default=None,
        help="Path to a completed calibration run directory. Review mode only.",
    )
    parser.add_argument(
        "--cohort-manifest", default=None,
        help="Path to a completed classifier candidate cohort manifest. Used "
             "by the two classifier modes only; its digest is pinned by the "
             "authorization, never by this flag.",
    )
    parser.add_argument(
        "--annual-coverage-cohort-manifest", default=None,
        help=(
            "Select-classifier-pilot-rows-v2 mode only: the completed "
            "annual-coverage cohort manifest that supplies the eligible "
            "population for the named ten-filing pilot."
        ),
    )
    parser.add_argument(
        "--annual-coverage-cohort-manifest-sha256", default=None,
        help=(
            "Select-classifier-pilot-rows-v2 mode only: the pinned SHA-256 "
            "of that annual-coverage cohort manifest."
        ),
    )
    parser.add_argument(
        "--overlay-manifest", default=None,
        help="Build-classifier-candidate-cohort mode only: the human-review "
             "overlay's universe_human_review_overlay_manifest.json.",
    )
    parser.add_argument(
        "--overlay-manifest-sha256", default=None,
        help="Build-classifier-candidate-cohort mode only: the pinned digest "
             "of that overlay manifest.",
    )
    parser.add_argument(
        "--base-screen-manifest", default=None,
        help="Build-screen-release mode only: the completed base screen's "
             "universe_screen_continuation_v5_manifest.json.",
    )
    parser.add_argument(
        "--base-screen-manifest-sha256", default=None,
        help="Build-screen-release mode only: the pinned digest of that "
             "manifest. A mismatch refuses the reconciliation.",
    )
    parser.add_argument(
        "--repair-manifest", default=None,
        help="Build-screen-release mode only: the completed repair run's "
             "universe_screen_repair_manifest.json.",
    )
    parser.add_argument(
        "--repair-manifest-sha256", default=None,
        help="Build-screen-release mode only: the pinned digest of that "
             "manifest. A mismatch refuses the reconciliation.",
    )
    parser.add_argument(
        "--source-screen-manifest", default=None,
        help="Unverified-repair modes only: the completed source screen's "
             "universe_screen_continuation_v5_manifest.json. Its hash-bound "
             "records are the sole population the repair rows are derived "
             "from, and the runner re-derives them from those bytes.",
    )
    parser.add_argument(
        "--source-diagnostic-manifest", default=None,
        help="Select-screen-repair-rows mode only: the completed source "
             "diagnostic run's universe_screen_diagnostic_manifest.json. Its "
             "hash-bound records are the sole population the seven repair "
             "rows are derived from.",
    )
    parser.add_argument(
        "--selection-seed", type=int, default=None,
        help="Select-screen-rows mode only: the integer seed of the "
             "deterministic canary_100 sampler. Refused for full_cohort, "
             "which samples nothing.",
    )
    parser.add_argument(
        "--selection-kind", default=None, choices=["canary_100", "full_cohort"],
        help="Select-screen-rows mode only: canary_100 enumerates exactly "
             "one hundred packet-native stratified rows; full_cohort "
             "enumerates nothing because the packet manifest is the row "
             "authority.",
    )
    parser.add_argument(
        "--execution-run-ids", default=None,
        help="Aggregate-acquisition-lineage mode only: an explicit, comma-"
             "separated, ordered enumeration of the execution run ids the "
             "lineage is assembled from, such as 'r1,r2,r3'. Required. There "
             "is no value that expands to every run under an output root, and "
             "a run outside this enumeration is invisible to the aggregate.",
    )
    return parser


def _present(pairs: tuple[tuple[str, object], ...]) -> list[str]:
    return [name for name, value in pairs if value is not None]


def _missing(pairs: tuple[tuple[str, object], ...]) -> list[str]:
    return [name for name, value in pairs if value is None]


def _reject_cross_mode_flags(args: argparse.Namespace) -> str | None:
    """Return an error message when a flag from another mode is present."""
    sentinel_flags = (
        ("--input", args.input),
        ("--provider", args.provider),
        ("--seed", args.seed),
    )
    frame_flags = (
        ("--index-dir", args.index_dir),
        ("--filing-window-start", args.filing_window_start),
        ("--filing-window-end", args.filing_window_end),
        ("--acquisition-manifest", args.acquisition_manifest),
    )
    acquire_flags = (
        ("--request-plan", args.request_plan),
        ("--replay-dir", args.replay_dir),
        ("--transport", args.transport),
    )
    dera_flags = (
        ("--frame-manifest", args.frame_manifest),
        ("--dera-dir", args.dera_dir),
    )
    packet_flags = (("--bundle-dir", args.bundle_dir),)
    queue_flags = (
        ("--queue-definition", args.queue_definition),
        ("--plan-dir", args.plan_dir),
        ("--shard-indices", args.shard_indices),
        ("--expected-request-count", args.expected_request_count),
        ("--on-shard-failure", args.on_shard_failure),
        ("--shard-output-dir", args.shard_output_dir),
        ("--execution-run-id", args.execution_run_id),
        ("--execution-run-ids", args.execution_run_ids),
    )

    # One guard for every non-queue mode, rather than threading queue_flags
    # through each existing branch.
    if args.mode not in QUEUE_MODES:
        offending = _present(queue_flags)
        if offending:
            return f"{args.mode} mode does not accept: {', '.join(offending)}"

    # Total gating for the two lineage-input flags (ADR-103): every mode that
    # does not consume one refuses it, so no mode silently ignores either.
    # --aggregate-manifest is consumed by the three lineage consumers: shell
    # determination, asset-backed determination and the packet build;
    # --shell-determination-manifest by the packet-lineage mode alone.
    if args.mode not in ("determine-shell-company-lineage",
                         "determine-asset-backed-issuer-lineage",
                         "build-baseline-packets-lineage",
                         "build-baseline-packets-lineage-v2"):
        offending = _present(
            (("--aggregate-manifest", args.aggregate_manifest),)
        )
        if offending:
            return f"{args.mode} mode does not accept: {', '.join(offending)}"
    if args.mode not in ("build-baseline-packets-lineage",
                         "build-baseline-packets-lineage-v2"):
        offending = _present(
            (("--shell-determination-manifest",
              args.shell_determination_manifest),)
        )
        if offending:
            return f"{args.mode} mode does not accept: {', '.join(offending)}"
        offending = _present(
            (("--item-one-locator", args.item_one_locator),)
        )
        if offending:
            return f"{args.mode} mode does not accept: {', '.join(offending)}"
    if args.mode != "build-baseline-packets-lineage-v2":
        offending = _present(
            (("--asset-backed-determination-manifest",
              args.asset_backed_determination_manifest),)
        )
        if offending:
            return f"{args.mode} mode does not accept: {', '.join(offending)}"

    # Total gating for the screen flags (ADR-108/109), collected into one
    # refusal so a caller sees every offending flag at once. --packet-manifest
    # is consumed by the three packet-consuming screen modes; --screen-fixture
    # by the mock screen alone; the two caps by both screen modes; the four
    # live-governance flags by the live screen alone; the two selection flags
    # by the selection builder alone. Every other mode refuses them all.
    screen_offenders: list[str] = []
    if args.mode not in ("screen-universe-lineage",
                         "screen-universe-lineage-live",
                         "screen-universe-lineage-live-v2",
                         "screen-universe-lineage-live-v3",
                         "screen-universe-lineage-continuation",
                         "screen-universe-lineage-continuation-v2",
                         "screen-universe-lineage-continuation-v3",
                         "screen-universe-lineage-continuation-v4",
                         "screen-universe-lineage-continuation-v5",
                         "screen-universe-unverified-repair",
                         "screen-universe-lineage-diagnostic",
                         "screen-universe-lineage-diagnostic-repair",
                         "select-screen-repair-rows",
                         "select-screen-rows",
                         "classify-universe-cohort",
                         "classify-universe-cohort-continuation",
                         "classify-universe-calibration",
                         "classify-universe-cohort-v2-2", "classify-universe-cohort-continuation-v2-2", "classify-universe-calibration-v2-2",
                         "classify-universe-cohort-v2-3", "classify-universe-cohort-continuation-v2-3", "classify-universe-calibration-v2-3",
                         "classify-universe-cohort-v2-4", "classify-universe-cohort-continuation-v2-4", "classify-universe-calibration-v2-4",
                         "classify-universe-cohort-v2-5", "classify-universe-cohort-continuation-v2-5", "classify-universe-calibration-v2-5",
                         "classify-universe-cohort-v2-6", "classify-universe-cohort-continuation-v2-6", "classify-universe-calibration-v2-6",
                         "classify-universe-cohort-v2-7", "classify-universe-cohort-continuation-v2-7", "classify-universe-calibration-v2-7",
                         "classify-universe-cohort-v2-8", "classify-universe-cohort-continuation-v2-8", "classify-universe-calibration-v2-8",
                         "classify-universe-cohort-v2-9", "classify-universe-cohort-continuation-v2-9", "classify-universe-calibration-v2-9",
                         "classify-software-universe-pilot-v1",
                         "classify-software-universe-pilot-v2",
                         "classify-software-universe-pilot-v3",
                 "classify-software-universe-pilot-v4",
                 "classify-software-universe-pilot-v5",
                 "classify-software-universe-pilot-v6",
                         "select-classifier-pilot-rows-v2"):
        screen_offenders += _present(
            (("--packet-manifest", args.packet_manifest),)
        )
    if args.mode != "screen-universe-lineage":
        screen_offenders += _present(
            (("--screen-fixture", args.screen_fixture),)
        )
    if args.mode not in ("screen-universe-lineage",
                         "screen-universe-lineage-live",
                         "screen-universe-lineage-live-v2",
                         "screen-universe-lineage-live-v3",
                         "screen-universe-lineage-diagnostic",
                         "screen-universe-lineage-diagnostic-repair"):
        screen_offenders += _present((
            ("--logical-request-cap", args.logical_request_cap),
            ("--provider-attempt-cap", args.provider_attempt_cap),
        ))
    if args.mode not in ("screen-universe-lineage-live",
                         "screen-universe-lineage-live-v2",
                         "screen-universe-lineage-live-v3",
                         "screen-universe-lineage-continuation",
                         "screen-universe-lineage-continuation-v2",
                         "screen-universe-lineage-continuation-v3",
                         "screen-universe-lineage-continuation-v4",
                         "screen-universe-lineage-continuation-v5",
                         "screen-universe-unverified-repair",
                         "screen-universe-lineage-diagnostic",
                         "screen-universe-lineage-diagnostic-repair"):
        # The classifier modes take a cohort, not a selection artifact, so
        # they are deliberately absent here and admitted below for the three
        # governance flags alone.
        screen_offenders += _present((
            ("--selection-artifact", args.selection_artifact),
        ))
    if args.mode not in ("screen-universe-lineage-live",
                         "screen-universe-lineage-live-v2",
                         "screen-universe-lineage-live-v3",
                         "screen-universe-lineage-continuation",
                         "screen-universe-lineage-continuation-v2",
                         "screen-universe-lineage-continuation-v3",
                         "screen-universe-lineage-continuation-v4",
                         "screen-universe-lineage-continuation-v5",
                         "screen-universe-unverified-repair",
                         "screen-universe-lineage-diagnostic",
                         "screen-universe-lineage-diagnostic-repair",
                         "classify-universe-cohort",
                         "classify-universe-cohort-continuation",
                         "classify-universe-calibration",
                         "classify-universe-cohort-v2-2", "classify-universe-cohort-continuation-v2-2", "classify-universe-calibration-v2-2",
                         "classify-universe-cohort-v2-3", "classify-universe-cohort-continuation-v2-3", "classify-universe-calibration-v2-3",
                         "classify-universe-cohort-v2-4", "classify-universe-cohort-continuation-v2-4", "classify-universe-calibration-v2-4",
                         "classify-universe-cohort-v2-5", "classify-universe-cohort-continuation-v2-5", "classify-universe-calibration-v2-5",
                         "classify-universe-cohort-v2-6", "classify-universe-cohort-continuation-v2-6", "classify-universe-calibration-v2-6",
                         "classify-universe-cohort-v2-7", "classify-universe-cohort-continuation-v2-7", "classify-universe-calibration-v2-7",
                         "classify-universe-cohort-v2-8", "classify-universe-cohort-continuation-v2-8", "classify-universe-calibration-v2-8",
                         "classify-universe-cohort-v2-9", "classify-universe-cohort-continuation-v2-9", "classify-universe-calibration-v2-9",
                         "classify-software-universe-pilot-v1",
                         "classify-software-universe-pilot-v2",
                         "classify-software-universe-pilot-v3",
                         "classify-software-universe-pilot-v4",
                         "classify-software-universe-pilot-v5",
                         "classify-software-universe-pilot-v6"):
        screen_offenders += _present((
            ("--governance-root", args.governance_root),
            ("--screen-authorization", args.screen_authorization),
            ("--screen-authorization-sha256",
             args.screen_authorization_sha256),
        ))
    if args.mode != "select-screen-repair-rows":
        screen_offenders += _present((
            ("--source-diagnostic-manifest",
             args.source_diagnostic_manifest),
        ))
    if args.mode not in ("build-human-review-overlay",
                         "build-classifier-candidate-cohort",
                         "classify-universe-cohort",
                         "classify-universe-cohort-continuation",
                         "select-classifier-calibration-rows",
                         "classify-universe-calibration",
                         "classify-universe-cohort-v2-2", "classify-universe-cohort-continuation-v2-2", "classify-universe-calibration-v2-2",
                         "classify-universe-cohort-v2-3", "classify-universe-cohort-continuation-v2-3", "classify-universe-calibration-v2-3",
                         "classify-universe-cohort-v2-4", "classify-universe-cohort-continuation-v2-4", "classify-universe-calibration-v2-4",
                         "classify-universe-cohort-v2-5", "classify-universe-cohort-continuation-v2-5", "classify-universe-calibration-v2-5",
                         "classify-universe-cohort-v2-6", "classify-universe-cohort-continuation-v2-6", "classify-universe-calibration-v2-6",
                         "classify-universe-cohort-v2-7", "classify-universe-cohort-continuation-v2-7", "classify-universe-calibration-v2-7",
                         "classify-universe-cohort-v2-8", "classify-universe-cohort-continuation-v2-8", "classify-universe-calibration-v2-8",
                         "classify-universe-cohort-v2-9", "classify-universe-cohort-continuation-v2-9", "classify-universe-calibration-v2-9"):
        screen_offenders += _present((
            ("--release-manifest", args.release_manifest),
        ))
    # The digest flags belong to the two deterministic builders. A classifier
    # run takes its digests from the authorization, so passing one here would
    # create a second, unbound source of truth.
    if args.mode not in ("build-human-review-overlay",
                         "build-classifier-candidate-cohort", "select-classifier-calibration-rows"):
        screen_offenders += _present((
            ("--release-manifest-sha256", args.release_manifest_sha256),
        ))
    if args.mode != "build-human-review-overlay":
        screen_offenders += _present((
            ("--decision-ledger", args.decision_ledger),
        ))
    if args.mode not in ("build-classifier-candidate-cohort",
                         "classify-universe-cohort",
                         "classify-universe-cohort-continuation",
                         "select-classifier-calibration-rows",
                         "classify-universe-calibration",
                         "classify-universe-cohort-v2-2", "classify-universe-cohort-continuation-v2-2", "classify-universe-calibration-v2-2",
                         "classify-universe-cohort-v2-3", "classify-universe-cohort-continuation-v2-3", "classify-universe-calibration-v2-3",
                         "classify-universe-cohort-v2-4", "classify-universe-cohort-continuation-v2-4", "classify-universe-calibration-v2-4",
                         "classify-universe-cohort-v2-5", "classify-universe-cohort-continuation-v2-5", "classify-universe-calibration-v2-5",
                         "classify-universe-cohort-v2-6", "classify-universe-cohort-continuation-v2-6", "classify-universe-calibration-v2-6",
                         "classify-universe-cohort-v2-7", "classify-universe-cohort-continuation-v2-7", "classify-universe-calibration-v2-7",
                         "classify-universe-cohort-v2-8", "classify-universe-cohort-continuation-v2-8", "classify-universe-calibration-v2-8",
                         "classify-universe-cohort-v2-9", "classify-universe-cohort-continuation-v2-9", "classify-universe-calibration-v2-9"):
        screen_offenders += _present((
            ("--overlay-manifest", args.overlay_manifest),
        ))
    if args.mode not in ("build-classifier-candidate-cohort", "select-classifier-calibration-rows"):
        screen_offenders += _present((
            ("--overlay-manifest-sha256", args.overlay_manifest_sha256),
        ))
    if args.mode not in ("classify-universe-cohort",
                         "classify-universe-cohort-continuation",
                         "select-classifier-calibration-rows",
                         "classify-universe-calibration",
                         "classify-universe-cohort-v2-2", "classify-universe-cohort-continuation-v2-2", "classify-universe-calibration-v2-2",
                         "classify-universe-cohort-v2-3", "classify-universe-cohort-continuation-v2-3", "classify-universe-calibration-v2-3",
                         "classify-universe-cohort-v2-4", "classify-universe-cohort-continuation-v2-4", "classify-universe-calibration-v2-4",
                         "classify-universe-cohort-v2-5", "classify-universe-cohort-continuation-v2-5", "classify-universe-calibration-v2-5",
                         "classify-universe-cohort-v2-6", "classify-universe-cohort-continuation-v2-6", "classify-universe-calibration-v2-6",
                         "classify-universe-cohort-v2-7", "classify-universe-cohort-continuation-v2-7", "classify-universe-calibration-v2-7",
                         "classify-universe-cohort-v2-8", "classify-universe-cohort-continuation-v2-8", "classify-universe-calibration-v2-8",
                         "classify-universe-cohort-v2-9", "classify-universe-cohort-continuation-v2-9", "classify-universe-calibration-v2-9",
                         "select-classifier-pilot-rows",
                         "select-classifier-pilot-rows-v2",
                         "classify-software-universe-pilot-v1",
                         "classify-software-universe-pilot-v2",
                         "classify-software-universe-pilot-v3",
                 "classify-software-universe-pilot-v4",
                 "classify-software-universe-pilot-v5",
                 "classify-software-universe-pilot-v6",
                         "build-annual-coverage-cohort"):
        screen_offenders += _present((
            ("--cohort-manifest", args.cohort_manifest),
        ))
    if args.mode not in ("classify-universe-calibration",
                         "classify-universe-calibration-v2-2",
                         "classify-universe-calibration-v2-3",
                         "classify-universe-calibration-v2-4",
                         "classify-universe-calibration-v2-5",
                         "classify-universe-calibration-v2-6",
                         "classify-universe-calibration-v2-7",
                         "classify-universe-calibration-v2-8",
                         "classify-universe-calibration-v2-9",
                         "build-classifier-calibration-review", "build-classifier-calibration-review-v2-2", "build-classifier-calibration-review-v2-3", "build-classifier-calibration-review-v2-4", "build-classifier-calibration-review-v2-5", "build-classifier-calibration-review-v2-6", "build-classifier-calibration-review-v2-7", "build-classifier-calibration-review-v2-8", "build-classifier-calibration-review-v2-9",
                         "select-classifier-pilot-rows"):
        screen_offenders += _present((
            ("--calibration-selection", args.calibration_selection),
        ))
    _REVIEW_MODES = ("build-classifier-calibration-review", "build-classifier-calibration-review-v2-2", "build-classifier-calibration-review-v2-3", "build-classifier-calibration-review-v2-4", "build-classifier-calibration-review-v2-5", "build-classifier-calibration-review-v2-6", "build-classifier-calibration-review-v2-7", "build-classifier-calibration-review-v2-8", "build-classifier-calibration-review-v2-9")
    # The two flags were one gate while only the review modes used either. The
    # pilot selection builder pins its source 40-row artifact by digest and
    # consumes no calibration run, so they are gated apart now.
    if args.mode not in _REVIEW_MODES + ("select-classifier-pilot-rows",):
        screen_offenders += _present((
            ("--calibration-selection-sha256", args.calibration_selection_sha256),
        ))
    if args.mode not in _REVIEW_MODES:
        screen_offenders += _present((
            ("--calibration-run-dir", args.calibration_run_dir),
        ))
    if args.mode not in ("select-classifier-calibration-rows",
                         "select-classifier-pilot-rows",
                         "select-classifier-pilot-rows-v2",
                         "build-annual-coverage-cohort"):
        screen_offenders += _present((
            ("--cohort-manifest-sha256", args.cohort_manifest_sha256),
        ))
    # The FRAME digest belongs to the coverage builder alone. --frame-manifest
    # itself is shared with the DERA and baseline-carrier modes, which pin it a
    # different way, so only the digest flag is gated here.
    if args.mode != "build-annual-coverage-cohort":
        screen_offenders += _present((
            ("--frame-manifest-sha256", args.frame_manifest_sha256),
        ))
    # The pilot selection artifact belongs to the live pilot run alone. Every
    # other mode, the builder that writes it included, refuses it.
    if args.mode not in ("classify-software-universe-pilot-v1",
                         "classify-software-universe-pilot-v2",
                         "classify-software-universe-pilot-v3",
                         "classify-software-universe-pilot-v4",
                         "classify-software-universe-pilot-v5",
                         "classify-software-universe-pilot-v6"):
        screen_offenders += _present((
            ("--pilot-selection", args.pilot_selection),
        ))
    if args.mode not in ("select-classifier-pilot-rows-v2",
                         "classify-software-universe-pilot-v2",
                         "classify-software-universe-pilot-v3",
                         "classify-software-universe-pilot-v4",
                         "classify-software-universe-pilot-v5",
                         "classify-software-universe-pilot-v6"):
        screen_offenders += _present((
            ("--annual-coverage-cohort-manifest",
             args.annual_coverage_cohort_manifest),
            ("--annual-coverage-cohort-manifest-sha256",
             args.annual_coverage_cohort_manifest_sha256),
        ))
    if args.mode != "build-screen-release":
        screen_offenders += _present((
            ("--base-screen-manifest", args.base_screen_manifest),
            ("--base-screen-manifest-sha256", args.base_screen_manifest_sha256),
            ("--repair-manifest", args.repair_manifest),
            ("--repair-manifest-sha256", args.repair_manifest_sha256),
        ))
    if args.mode not in ("screen-universe-lineage-continuation",
                         "screen-universe-unverified-repair",
                         "select-screen-unverified-repair-rows",
                         "screen-universe-lineage-continuation-v2",
                         "screen-universe-lineage-continuation-v3",
                         "screen-universe-lineage-continuation-v4",
                         "screen-universe-lineage-continuation-v5",
                         "classify-universe-cohort-continuation",
                         "classify-universe-cohort-continuation-v2-2", "classify-universe-cohort-continuation-v2-3",
                         "classify-universe-cohort-continuation-v2-4",
                         "classify-universe-cohort-continuation-v2-5",
                         "classify-universe-cohort-continuation-v2-6",
                         "classify-universe-cohort-continuation-v2-7",
                         "classify-universe-cohort-continuation-v2-8",
                         "classify-universe-cohort-continuation-v2-9"):
        screen_offenders += _present((
            ("--source-run-dir", args.source_run_dir),
            ("--source-receipt-sha256", args.source_receipt_sha256),
        ))
    if args.mode != "select-screen-rows":
        screen_offenders += _present((
            ("--selection-seed", args.selection_seed),
            ("--selection-kind", args.selection_kind),
        ))
    if screen_offenders:
        return f"{args.mode} mode does not accept: {', '.join(screen_offenders)}"

    if args.mode in QUEUE_MODES:
        offending = _present(
            sentinel_flags + frame_flags + dera_flags + packet_flags
            + (("--config", args.config),)
        )
        if args.mode != "execute-acquisition-queue":
            offending += _present(acquire_flags)
        if offending:
            return f"{args.mode} mode does not accept: {', '.join(offending)}"
        if args.queue_definition is None:
            return f"{args.mode} mode requires: --queue-definition"

    if args.mode == "plan-acquisition-queue":
        offending = _present((
            ("--plan-dir", args.plan_dir),
            ("--shard-indices", args.shard_indices),
            ("--expected-request-count", args.expected_request_count),
            ("--on-shard-failure", args.on_shard_failure),
            ("--shard-output-dir", args.shard_output_dir),
            ("--execution-run-id", args.execution_run_id),
        ))
        if offending:
            return (
                "plan-acquisition-queue mode does not accept: "
                f"{', '.join(offending)}"
            )
        return None

    if args.mode == "execute-acquisition-queue":
        offending = _present((
            ("--replay-dir", args.replay_dir) if args.transport == "sec-live"
            else ("--unused", None),
            ("--execution-run-id", args.execution_run_id),
        ))
        if offending:
            return (
                "execute-acquisition-queue mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--plan-dir", args.plan_dir),
            ("--shard-indices", args.shard_indices),
            ("--expected-request-count", args.expected_request_count),
            ("--on-shard-failure", args.on_shard_failure),
        ))
        if missing:
            return (
                "execute-acquisition-queue mode requires: "
                f"{', '.join(missing)}"
            )
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "execute-acquisition-queue mode with the fixture transport "
                "requires: --replay-dir"
            )
        if args.request_plan is not None:
            return (
                "execute-acquisition-queue mode does not accept: "
                "--request-plan; shard plans come from --plan-dir, and the "
                "executor never runs a hand-supplied plan"
            )
        return None

    if args.mode == "aggregate-acquisition-queue":
        offending = _present((
            ("--plan-dir", args.plan_dir),
            ("--shard-indices", args.shard_indices),
            ("--expected-request-count", args.expected_request_count),
            ("--on-shard-failure", args.on_shard_failure),
            # The generations never mix: the v0.1 path aggregates exactly one
            # named run, so the plural enumeration is not a shorthand it
            # accepts (ADR-101).
            ("--execution-run-ids", args.execution_run_ids),
        ))
        if offending:
            return (
                "aggregate-acquisition-queue mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--shard-output-dir", args.shard_output_dir),
            ("--execution-run-id", args.execution_run_id),
        ))
        if missing:
            return (
                "aggregate-acquisition-queue mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "aggregate-acquisition-lineage":
        offending = _present((
            ("--plan-dir", args.plan_dir),
            ("--shard-indices", args.shard_indices),
            ("--expected-request-count", args.expected_request_count),
            ("--on-shard-failure", args.on_shard_failure),
            # Refused in this direction too: a lineage is enumerated, and a
            # single run id supplied here would look like an authorization it
            # is not.
            ("--execution-run-id", args.execution_run_id),
        ))
        if offending:
            return (
                "aggregate-acquisition-lineage mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--shard-output-dir", args.shard_output_dir),
            ("--execution-run-ids", args.execution_run_ids),
        ))
        if missing:
            return (
                "aggregate-acquisition-lineage mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "build-annual-coverage-cohort":
        # Its own block rather than a seat in the classifier loop below: that
        # loop rejects every DERA flag wholesale, and this is the one non-DERA
        # mode that legitimately consumes --frame-manifest.
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags + queue_flags
            + (("--dera-dir", args.dera_dir),)
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
        )
        if offending:
            return (f"build-annual-coverage-cohort mode does not accept: "
                    f"{', '.join(offending)}")
        missing = _missing((
            ("--cohort-manifest", args.cohort_manifest),
            ("--cohort-manifest-sha256", args.cohort_manifest_sha256),
            ("--frame-manifest", args.frame_manifest),
            ("--frame-manifest-sha256", args.frame_manifest_sha256),
            ("--output-dir", args.output_dir),
            ("--run-id", args.run_id),
        ))
        if missing:
            return (f"build-annual-coverage-cohort mode requires: "
                    f"{', '.join(missing)}")
        return None

    if args.mode == "dera-validate":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags
            + (("--config", args.config),)
        )
        if offending:
            return f"dera-validate mode does not accept: {', '.join(offending)}"
        missing = _missing(dera_flags)
        if missing:
            return f"dera-validate mode requires: {', '.join(missing)}"
        return None

    if args.mode == "acquire-docs":
        offending = _present(
            sentinel_flags + frame_flags + dera_flags
            + (("--config", args.config),)
        )
        if offending:
            return f"acquire-docs mode does not accept: {', '.join(offending)}"
        if args.request_plan is None:
            return "acquire-docs mode requires: --request-plan"
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "acquire-docs mode with the fixture transport requires: "
                "--replay-dir"
            )
        if transport_choice == "sec-live" and args.replay_dir is not None:
            return (
                "acquire-docs mode with the sec-live transport does not "
                "accept: --replay-dir"
            )
        return None

    if args.mode == "determine-shell-company":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags + dera_flags
            + (("--config", args.config),)
            # The generations never mix: the single-bundle path reads exactly
            # one named bundle, so an aggregate root is not a shorthand it
            # accepts (ADR-102).
            + (("--aggregate-manifest", args.aggregate_manifest),)
        )
        if offending:
            return (
                "determine-shell-company mode does not accept: "
                f"{', '.join(offending)}"
            )
        if args.bundle_dir is None:
            return "determine-shell-company mode requires: --bundle-dir"
        return None

    if args.mode == "determine-shell-company-lineage":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags + dera_flags
            + (("--config", args.config),)
            # Refused in this direction too, and with it every other data
            # location: the aggregate is the sole authority root, so a bundle
            # directory or shard-output root supplied here would name evidence
            # the manifest does not authorize.
            + (("--bundle-dir", args.bundle_dir),)
            + (("--shard-output-dir", args.shard_output_dir),)
            + (("--queue-definition", args.queue_definition),)
            + (("--replay-dir", args.replay_dir),)
        )
        if offending:
            return (
                "determine-shell-company-lineage mode does not accept: "
                f"{', '.join(offending)}"
            )
        if args.aggregate_manifest is None:
            return (
                "determine-shell-company-lineage mode requires: "
                "--aggregate-manifest"
            )
        return None

    if args.mode == "determine-asset-backed-issuer-lineage":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags + dera_flags
            + (("--config", args.config),)
            # The aggregate is the sole evidence location: any other data
            # flag supplied here would name evidence the manifest does not
            # authorize.
            + (("--bundle-dir", args.bundle_dir),)
            + (("--shard-output-dir", args.shard_output_dir),)
            + (("--queue-definition", args.queue_definition),)
            + (("--replay-dir", args.replay_dir),)
        )
        if offending:
            return (
                "determine-asset-backed-issuer-lineage mode does not accept: "
                f"{', '.join(offending)}"
            )
        if args.aggregate_manifest is None:
            return (
                "determine-asset-backed-issuer-lineage mode requires: "
                "--aggregate-manifest"
            )
        return None

    if args.mode == "build-baseline-packets-lineage":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags + dera_flags
            # The two manifests are the only data locations this mode takes:
            # a bundle directory or replay directory supplied here would name
            # evidence the aggregate does not authorize.
            + (("--bundle-dir", args.bundle_dir),)
            + (("--replay-dir", args.replay_dir),)
        )
        if offending:
            return (
                "build-baseline-packets-lineage mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--aggregate-manifest", args.aggregate_manifest),
            ("--shell-determination-manifest",
             args.shell_determination_manifest),
            ("--item-one-locator", args.item_one_locator),
            ("--config", args.config),
        ))
        if missing:
            return (
                "build-baseline-packets-lineage mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "build-baseline-packets-lineage-v2":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags + dera_flags
            # The three manifests are the only data locations this mode
            # takes: a bundle or replay directory supplied here would name
            # evidence the aggregate does not authorize.
            + (("--bundle-dir", args.bundle_dir),)
            + (("--replay-dir", args.replay_dir),)
        )
        if offending:
            return (
                "build-baseline-packets-lineage-v2 mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--aggregate-manifest", args.aggregate_manifest),
            ("--shell-determination-manifest",
             args.shell_determination_manifest),
            ("--asset-backed-determination-manifest",
             args.asset_backed_determination_manifest),
            ("--item-one-locator", args.item_one_locator),
            ("--config", args.config),
        ))
        if missing:
            return (
                "build-baseline-packets-lineage-v2 mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "screen-universe-lineage":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            # The packet manifest is the sole data location this mode takes:
            # a bundle directory, fixture input, sample-rule config or seed
            # supplied here would name evidence or behavior it does not
            # authorize. --provider is consumed, not refused: the mock is
            # the only provider of this increment.
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
        )
        if offending:
            return (
                "screen-universe-lineage mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--provider", args.provider),
            ("--screen-fixture", args.screen_fixture),
            ("--logical-request-cap", args.logical_request_cap),
            ("--provider-attempt-cap", args.provider_attempt_cap),
        ))
        if missing:
            return (
                "screen-universe-lineage mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "screen-universe-lineage-live":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            # The governed route takes no fixture, no provider choice and no
            # other data location: the packet manifest, the selection
            # artifact and the governance root are its only inputs, and the
            # mock provider is the other mode's whole point.
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                "screen-universe-lineage-live mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--selection-artifact", args.selection_artifact),
            ("--governance-root", args.governance_root),
            ("--screen-authorization", args.screen_authorization),
            ("--screen-authorization-sha256",
             args.screen_authorization_sha256),
            ("--logical-request-cap", args.logical_request_cap),
            ("--provider-attempt-cap", args.provider_attempt_cap),
        ))
        if missing:
            return (
                "screen-universe-lineage-live mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "screen-universe-lineage-live-v2":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                "screen-universe-lineage-live-v2 mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--selection-artifact", args.selection_artifact),
            ("--governance-root", args.governance_root),
            ("--screen-authorization", args.screen_authorization),
            ("--screen-authorization-sha256", args.screen_authorization_sha256),
            ("--logical-request-cap", args.logical_request_cap),
            ("--provider-attempt-cap", args.provider_attempt_cap),
        ))
        if missing:
            return (
                "screen-universe-lineage-live-v2 mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "screen-universe-lineage-live-v3":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                "screen-universe-lineage-live-v3 mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--selection-artifact", args.selection_artifact),
            ("--governance-root", args.governance_root),
            ("--screen-authorization", args.screen_authorization),
            ("--screen-authorization-sha256", args.screen_authorization_sha256),
            ("--logical-request-cap", args.logical_request_cap),
            ("--provider-attempt-cap", args.provider_attempt_cap),
        ))
        if missing:
            return (
                "screen-universe-lineage-live-v3 mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode in ("screen-universe-lineage-continuation",
                     "screen-universe-lineage-continuation-v2",
                     "screen-universe-lineage-continuation-v3",
                     "screen-universe-lineage-continuation-v4",
                     "screen-universe-lineage-continuation-v5"):
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return f"{args.mode} mode does not accept: {', '.join(offending)}"
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--selection-artifact", args.selection_artifact),
            ("--governance-root", args.governance_root),
            ("--screen-authorization", args.screen_authorization),
            ("--screen-authorization-sha256", args.screen_authorization_sha256),
            ("--source-run-dir", args.source_run_dir),
            ("--source-receipt-sha256", args.source_receipt_sha256),
        ))
        if missing:
            return f"{args.mode} mode requires: {', '.join(missing)}"
        return None

    if args.mode == "screen-universe-lineage-diagnostic-repair":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                "screen-universe-lineage-diagnostic-repair mode does not "
                f"accept: {', '.join(offending)}"
            )
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--selection-artifact", args.selection_artifact),
            ("--governance-root", args.governance_root),
            ("--screen-authorization", args.screen_authorization),
            ("--screen-authorization-sha256",
             args.screen_authorization_sha256),
            ("--logical-request-cap", args.logical_request_cap),
            ("--provider-attempt-cap", args.provider_attempt_cap),
        ))
        if missing:
            return (
                "screen-universe-lineage-diagnostic-repair mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    for derivation, required in (
        ("build-human-review-overlay",
         (("--release-manifest", "release_manifest"),
          ("--release-manifest-sha256", "release_manifest_sha256"),
          ("--decision-ledger", "decision_ledger"),
          ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-candidate-cohort",
         (("--release-manifest", "release_manifest"),
          ("--release-manifest-sha256", "release_manifest_sha256"),
          ("--overlay-manifest", "overlay_manifest"),
          ("--overlay-manifest-sha256", "overlay_manifest_sha256"),
          ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
    ):
        if args.mode != derivation:
            continue
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
            # a derivation reaches no provider, so it takes no grant
            + (("--governance-root", args.governance_root),)
            + (("--screen-authorization", args.screen_authorization),)
            + (("--screen-authorization-sha256",
                args.screen_authorization_sha256),)
            + (("--packet-manifest", args.packet_manifest),)
            + (("--selection-artifact", args.selection_artifact),)
        )
        if offending:
            return f"{derivation} mode does not accept: {', '.join(offending)}"
        missing = _missing(tuple((flag, getattr(args, attribute))
                                 for flag, attribute in required))
        if missing:
            return f"{derivation} mode requires: {', '.join(missing)}"
        return None

    if args.mode == "build-screen-release":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
            # a reconciliation reaches no provider, so it takes no grant
            + (("--governance-root", args.governance_root),)
            + (("--screen-authorization", args.screen_authorization),)
            + (("--screen-authorization-sha256",
                args.screen_authorization_sha256),)
            + (("--packet-manifest", args.packet_manifest),)
            + (("--selection-artifact", args.selection_artifact),)
        )
        if offending:
            return (
                "build-screen-release mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--base-screen-manifest", args.base_screen_manifest),
            ("--base-screen-manifest-sha256", args.base_screen_manifest_sha256),
            ("--repair-manifest", args.repair_manifest),
            ("--repair-manifest-sha256", args.repair_manifest_sha256),
            ("--output-dir", args.output_dir),
            ("--run-id", args.run_id),
        ))
        if missing:
            return f"build-screen-release mode requires: {', '.join(missing)}"
        return None

    if args.mode == "select-screen-unverified-repair-rows":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                "select-screen-unverified-repair-rows mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--source-screen-manifest", args.source_screen_manifest),
            ("--output-dir", args.output_dir),
            ("--run-id", args.run_id),
        ))
        if missing:
            return (
                "select-screen-unverified-repair-rows mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "screen-universe-unverified-repair":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                "screen-universe-unverified-repair mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--selection-artifact", args.selection_artifact),
            ("--source-screen-manifest", args.source_screen_manifest),
            ("--governance-root", args.governance_root),
            ("--screen-authorization", args.screen_authorization),
            ("--screen-authorization-sha256", args.screen_authorization_sha256),
        ))
        if missing:
            return (
                "screen-universe-unverified-repair mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    for calibration_mode, required_flags in (
        ("select-classifier-pilot-rows", (("--cohort-manifest", "cohort_manifest"),
                   ("--cohort-manifest-sha256", "cohort_manifest_sha256"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("select-classifier-pilot-rows-v2", (("--annual-coverage-cohort-manifest",
                    "annual_coverage_cohort_manifest"),
                   ("--annual-coverage-cohort-manifest-sha256",
                    "annual_coverage_cohort_manifest_sha256"),
                   ("--cohort-manifest", "cohort_manifest"),
                   ("--cohort-manifest-sha256", "cohort_manifest_sha256"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-software-universe-pilot-v1", (("--cohort-manifest", "cohort_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--pilot-selection", "pilot_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-software-universe-pilot-v2", (("--cohort-manifest", "cohort_manifest"),
                   ("--annual-coverage-cohort-manifest",
                    "annual_coverage_cohort_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--pilot-selection", "pilot_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-software-universe-pilot-v3", (("--cohort-manifest", "cohort_manifest"),
                   ("--annual-coverage-cohort-manifest",
                    "annual_coverage_cohort_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--pilot-selection", "pilot_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-software-universe-pilot-v4", (("--cohort-manifest", "cohort_manifest"),
                   ("--annual-coverage-cohort-manifest",
                    "annual_coverage_cohort_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--pilot-selection", "pilot_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-software-universe-pilot-v5", (("--cohort-manifest", "cohort_manifest"),
                   ("--annual-coverage-cohort-manifest",
                    "annual_coverage_cohort_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--pilot-selection", "pilot_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-software-universe-pilot-v6", (("--cohort-manifest", "cohort_manifest"),
                   ("--annual-coverage-cohort-manifest",
                    "annual_coverage_cohort_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--pilot-selection", "pilot_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("select-classifier-calibration-rows", (("--cohort-manifest", "cohort_manifest"),
                   ("--cohort-manifest-sha256", "cohort_manifest_sha256"),
                   ("--release-manifest", "release_manifest"),
                   ("--release-manifest-sha256", "release_manifest_sha256"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--overlay-manifest-sha256", "overlay_manifest_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-universe-calibration-v2-6", (("--cohort-manifest", "cohort_manifest"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--release-manifest", "release_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-universe-calibration-v2-7", (("--cohort-manifest", "cohort_manifest"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--release-manifest", "release_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-universe-calibration-v2-8", (("--cohort-manifest", "cohort_manifest"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--release-manifest", "release_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-universe-calibration-v2-9", (("--cohort-manifest", "cohort_manifest"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--release-manifest", "release_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-universe-calibration-v2-5", (("--cohort-manifest", "cohort_manifest"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--release-manifest", "release_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-universe-calibration-v2-4", (("--cohort-manifest", "cohort_manifest"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--release-manifest", "release_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-universe-calibration-v2-3", (("--cohort-manifest", "cohort_manifest"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--release-manifest", "release_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-universe-calibration-v2-2", (("--cohort-manifest", "cohort_manifest"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--release-manifest", "release_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("classify-universe-calibration", (("--cohort-manifest", "cohort_manifest"),
                   ("--overlay-manifest", "overlay_manifest"),
                   ("--release-manifest", "release_manifest"),
                   ("--packet-manifest", "packet_manifest"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--governance-root", "governance_root"),
                   ("--screen-authorization", "screen_authorization"),
                   ("--screen-authorization-sha256",
                    "screen_authorization_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-calibration-review-v2-2", (("--calibration-run-dir", "calibration_run_dir"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-calibration-review-v2-6", (("--calibration-run-dir", "calibration_run_dir"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-calibration-review-v2-7", (("--calibration-run-dir", "calibration_run_dir"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-calibration-review-v2-8", (("--calibration-run-dir", "calibration_run_dir"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-calibration-review-v2-9", (("--calibration-run-dir", "calibration_run_dir"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-calibration-review-v2-5", (("--calibration-run-dir", "calibration_run_dir"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-calibration-review-v2-4", (("--calibration-run-dir", "calibration_run_dir"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-calibration-review-v2-3", (("--calibration-run-dir", "calibration_run_dir"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
        ("build-classifier-calibration-review", (("--calibration-run-dir", "calibration_run_dir"),
                   ("--calibration-selection", "calibration_selection"),
                   ("--calibration-selection-sha256",
                    "calibration_selection_sha256"),
                   ("--output-dir", "output_dir"), ("--run-id", "run_id"))),
    ):
        if args.mode != calibration_mode:
            continue
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                f"{calibration_mode} mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing(tuple(
            (flag, getattr(args, attr)) for flag, attr in required_flags))
        if missing:
            return f"{calibration_mode} mode requires: {', '.join(missing)}"
        return None

    for classifier_mode, extra_required in (
        ("classify-universe-cohort", ()),
        ("classify-universe-cohort-v2-2", ()),
        ("classify-universe-cohort-v2-3", ()),
        ("classify-universe-cohort-continuation", (("--source-run-dir", "source_run_dir"),
                    ("--source-receipt-sha256", "source_receipt_sha256"))),
        ("classify-universe-cohort-continuation-v2-2", (("--source-run-dir", "source_run_dir"),
                    ("--source-receipt-sha256", "source_receipt_sha256"))),
        ("classify-universe-cohort-continuation-v2-3", (("--source-run-dir", "source_run_dir"),
                    ("--source-receipt-sha256", "source_receipt_sha256"))),
        ("classify-universe-cohort-v2-4", ()),
        ("classify-universe-cohort-continuation-v2-4", (("--source-run-dir", "source_run_dir"),
                    ("--source-receipt-sha256", "source_receipt_sha256"))),
        ("classify-universe-cohort-v2-5", ()),
        ("classify-universe-cohort-continuation-v2-5", (("--source-run-dir", "source_run_dir"),
                    ("--source-receipt-sha256", "source_receipt_sha256"))),
        ("classify-universe-cohort-v2-6", ()),
        ("classify-universe-cohort-v2-7", ()),
        ("classify-universe-cohort-v2-8", ()),
        ("classify-universe-cohort-v2-9", ()),
        ("classify-universe-cohort-continuation-v2-6", (("--source-run-dir", "source_run_dir"),
                    ("--source-receipt-sha256", "source_receipt_sha256"))),
        ("classify-universe-cohort-continuation-v2-7", (("--source-run-dir", "source_run_dir"),
                    ("--source-receipt-sha256", "source_receipt_sha256"))),
        ("classify-universe-cohort-continuation-v2-8", (("--source-run-dir", "source_run_dir"),
                    ("--source-receipt-sha256", "source_receipt_sha256"))),
        ("classify-universe-cohort-continuation-v2-9", (("--source-run-dir", "source_run_dir"),
                    ("--source-receipt-sha256", "source_receipt_sha256"))),
    ):
        if args.mode != classifier_mode:
            continue
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                f"{classifier_mode} mode does not accept: "
                f"{', '.join(offending)}"
            )
        required = [
            ("--cohort-manifest", args.cohort_manifest),
            ("--overlay-manifest", args.overlay_manifest),
            ("--release-manifest", args.release_manifest),
            ("--packet-manifest", args.packet_manifest),
            ("--governance-root", args.governance_root),
            ("--screen-authorization", args.screen_authorization),
            ("--screen-authorization-sha256", args.screen_authorization_sha256),
        ]
        required += [(flag, getattr(args, attr)) for flag, attr in extra_required]
        missing = _missing(tuple(required))
        if missing:
            return f"{classifier_mode} mode requires: {', '.join(missing)}"
        return None

    if args.mode == "select-screen-repair-rows":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                "select-screen-repair-rows mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--source-diagnostic-manifest",
             args.source_diagnostic_manifest),
        ))
        if missing:
            return (
                "select-screen-repair-rows mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "screen-universe-lineage-diagnostic":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            # Same rule as the live route: the packet manifest, the selection
            # artifact and the governance root are its only inputs, and the
            # mock provider belongs to the fixture mode alone.
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                "screen-universe-lineage-diagnostic mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--selection-artifact", args.selection_artifact),
            ("--governance-root", args.governance_root),
            ("--screen-authorization", args.screen_authorization),
            ("--screen-authorization-sha256",
             args.screen_authorization_sha256),
            ("--logical-request-cap", args.logical_request_cap),
            ("--provider-attempt-cap", args.provider_attempt_cap),
        ))
        if missing:
            return (
                "screen-universe-lineage-diagnostic mode requires: "
                f"{', '.join(missing)}"
            )
        return None

    if args.mode == "select-screen-rows":
        offending = _present(
            frame_flags + acquire_flags + dera_flags
            + (("--bundle-dir", args.bundle_dir),)
            + (("--config", args.config),)
            + (("--input", args.input),)
            + (("--seed", args.seed),)
            + (("--provider", args.provider),)
        )
        if offending:
            return (
                "select-screen-rows mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing((
            ("--packet-manifest", args.packet_manifest),
            ("--selection-kind", args.selection_kind),
        ))
        if missing:
            return f"select-screen-rows mode requires: {', '.join(missing)}"
        if args.selection_kind == "canary_100" and args.selection_seed is None:
            return (
                "select-screen-rows mode with canary_100 requires: "
                "--selection-seed"
            )
        if args.selection_kind == "full_cohort" and args.selection_seed is not None:
            return (
                "select-screen-rows mode with full_cohort does not accept: "
                "--selection-seed; a full-cohort selection samples nothing"
            )
        return None

    if args.mode == "build-baseline-packets":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags + dera_flags
        )
        if offending:
            return (
                "build-baseline-packets mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing(
            packet_flags + (("--config", args.config),)
        )
        if missing:
            return f"build-baseline-packets mode requires: {', '.join(missing)}"
        return None

    if args.mode == "acquire-primary-docs":
        offending = _present(
            sentinel_flags + frame_flags + dera_flags + packet_flags
            + (("--config", args.config),)
        )
        if offending:
            return (
                "acquire-primary-docs mode does not accept: "
                f"{', '.join(offending)}"
            )
        if args.request_plan is None:
            return "acquire-primary-docs mode requires: --request-plan"
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "acquire-primary-docs mode with the fixture transport "
                "requires: --replay-dir"
            )
        if transport_choice == "sec-live" and args.replay_dir is not None:
            return (
                "acquire-primary-docs mode with the sec-live transport does "
                "not accept: --replay-dir"
            )
        return None

    if args.mode == "probe-filing-index":
        offending = _present(
            sentinel_flags + frame_flags + dera_flags + packet_flags
            + (("--config", args.config),)
        )
        if offending:
            return (
                f"probe-filing-index mode does not accept: {', '.join(offending)}"
            )
        if args.request_plan is None:
            return "probe-filing-index mode requires: --request-plan"
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "probe-filing-index mode with the fixture transport requires: "
                "--replay-dir"
            )
        if transport_choice == "sec-live" and args.replay_dir is not None:
            return (
                "probe-filing-index mode with the sec-live transport does not "
                "accept: --replay-dir"
            )
        return None

    if args.mode == "baseline-carrier":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags
            + (("--dera-dir", args.dera_dir),)
        )
        if offending:
            return (
                f"baseline-carrier mode does not accept: {', '.join(offending)}"
            )
        missing = _missing(
            (
                ("--frame-manifest", args.frame_manifest),
                ("--config", args.config),
            )
        )
        if missing:
            return f"baseline-carrier mode requires: {', '.join(missing)}"
        return None

    if args.mode == "acquire-dera":
        offending = _present(
            sentinel_flags + frame_flags + dera_flags
            + (("--config", args.config),)
        )
        if offending:
            return f"acquire-dera mode does not accept: {', '.join(offending)}"
        if args.request_plan is None:
            return "acquire-dera mode requires: --request-plan"
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "acquire-dera mode with the fixture transport requires: "
                "--replay-dir"
            )
        if transport_choice == "sec-live" and args.replay_dir is not None:
            return (
                "acquire-dera mode with the sec-live transport does not "
                "accept: --replay-dir"
            )
        return None

    if args.mode == "frame":
        offending = _present(sentinel_flags + acquire_flags + dera_flags)
        if offending:
            return f"frame mode does not accept: {', '.join(offending)}"
        missing = _missing(
            (
                ("--config", args.config),
                ("--filing-window-start", args.filing_window_start),
                ("--filing-window-end", args.filing_window_end),
            )
        )
        if missing:
            return f"frame mode requires: {', '.join(missing)}"
        if (args.index_dir is None) == (args.acquisition_manifest is None):
            return (
                "frame mode requires exactly one of: --index-dir, "
                "--acquisition-manifest"
            )
        return None

    if args.mode == "acquire-index":
        offending = _present(
            sentinel_flags + frame_flags + dera_flags
            + (("--config", args.config),)
        )
        if offending:
            return f"acquire-index mode does not accept: {', '.join(offending)}"
        if args.request_plan is None:
            return "acquire-index mode requires: --request-plan"
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "acquire-index mode with the fixture transport requires: "
                "--replay-dir"
            )
        if transport_choice == "sec-live" and args.replay_dir is not None:
            return (
                "acquire-index mode with the sec-live transport does not "
                "accept: --replay-dir"
            )
        return None

    offending = _present(frame_flags + acquire_flags + dera_flags)
    if offending:
        return f"sentinel mode does not accept: {', '.join(offending)}"
    missing = _missing((("--config", args.config), ("--input", args.input)))
    if missing:
        return f"sentinel mode requires: {', '.join(missing)}"
    return None


def _main_sentinel(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    input_dir = Path(args.input)
    if not config_path.is_file():
        print(f"ERROR: sample-rule config not found: {config_path}", file=sys.stderr)
        return 2
    if not input_dir.is_dir():
        print(f"ERROR: fixture input directory not found: {input_dir}", file=sys.stderr)
        return 2
    try:
        result = run_universe_sentinel(
            repo_root=REPO_ROOT,
            rules_path=config_path,
            input_dir=input_dir,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            seed=42 if args.seed is None else args.seed,
            provider=args.provider or "mock",
            dry_run=args.dry_run,
        )
    except FixtureError as exc:
        print(f"ERROR: invalid fixture bundle or provider: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except FreezeBlockedError as exc:  # defensive: runner reports, never raises this
        print(f"ERROR: freeze blocked: {exc}", file=sys.stderr)
        return 1

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "counts": result.counts,
        "hard_gate_failures": result.hard_gate_failures,
        "freeze_status": result.freeze_status,
        "freeze_blockers": result.freeze_blockers,
        "universe_version": result.universe_version,
    }
    print(json.dumps(payload, indent=2))
    if result.hard_gate_failures:
        print("ERROR: hard gates failed; see hard_gate_failures above.", file=sys.stderr)
        return 1
    return 0


def _main_frame(args: argparse.Namespace) -> int:
    try:
        window_start = date.fromisoformat(args.filing_window_start)
        window_end = date.fromisoformat(args.filing_window_end)
    except ValueError as exc:
        print(f"ERROR: invalid filing-window date: {exc}", file=sys.stderr)
        return 2
    try:
        result = run_frame_builder(
            repo_root=REPO_ROOT,
            project_config_path=Path(args.config),
            index_dir=Path(args.index_dir) if args.index_dir else None,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            filing_window_start=window_start,
            filing_window_end=window_end,
            dry_run=args.dry_run,
            acquisition_manifest_path=(
                Path(args.acquisition_manifest)
                if args.acquisition_manifest
                else None
            ),
        )
    except FrameInputError as exc:
        print(f"ERROR: invalid frame input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except FrameReconciliationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "frame_version": result.frame_version,
        "counts": result.counts,
        "out_of_scope_form_counts": result.out_of_scope_form_counts,
        "reconciliation": result.reconciliation,
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_acquire(args: argparse.Namespace) -> int:
    request_plan = Path(args.request_plan)
    if not request_plan.is_file():
        print(f"ERROR: request plan not found: {request_plan}", file=sys.stderr)
        return 2
    transport_choice = args.transport or "fixture"
    if transport_choice == "sec-live":
        transport = make_sec_live_transport()
        transport_identity = SEC_LIVE_TRANSPORT_IDENTITY
    else:
        replay_dir = Path(args.replay_dir)
        if not replay_dir.is_dir():
            print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
            return 2
        transport = make_fixture_replay_transport(replay_dir)
        transport_identity = None  # fixture-replay identity, v0.1 manifest
    try:
        result = run_index_acquisition(
            repo_root=REPO_ROOT,
            request_plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            transport=transport,
            dry_run=args.dry_run,
            transport_identity=transport_identity,
        )
    except AcquisitionPlanError as exc:
        print(f"ERROR: invalid request plan: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "transport_kind": (
            transport_identity.kind if transport_identity else "fixture_replay"
        ),
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "request_plan_sha256": result.request_plan_sha256,
        "planned_entries": len(result.entries),
        "files_acquired": len(result.receipts),
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "failure_reason_code": (
            result.failure.reason_code if result.failure else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path
            else None
        ),
    }
    print(json.dumps(payload, indent=2))
    if result.failure is not None:
        print(
            "ERROR: acquisition failed; see the failure receipt. No "
            "acquisition manifest was written.",
            file=sys.stderr,
        )
        return 1
    return 0


def _main_acquire_dera(args: argparse.Namespace) -> int:
    request_plan = Path(args.request_plan)
    if not request_plan.is_file():
        print(f"ERROR: request plan not found: {request_plan}", file=sys.stderr)
        return 2
    transport_choice = args.transport or "fixture"
    if transport_choice == "sec-live":
        transport = make_sec_live_transport()
        transport_identity = SEC_LIVE_TRANSPORT_IDENTITY
    else:
        replay_dir = Path(args.replay_dir)
        if not replay_dir.is_dir():
            print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
            return 2
        transport = make_dera_fixture_replay_transport(replay_dir)
        transport_identity = None  # fixture-replay identity, v0.1 manifest
    try:
        result = run_dera_acquisition(
            repo_root=REPO_ROOT,
            request_plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            transport=transport,
            dry_run=args.dry_run,
            transport_identity=transport_identity,
        )
    except DeraPlanError as exc:
        print(f"ERROR: invalid DERA request plan: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "transport_kind": (
            transport_identity.kind if transport_identity else "fixture_replay"
        ),
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "request_plan_sha256": result.request_plan_sha256,
        "planned_releases": len(result.entries),
        "archives_acquired": len(result.receipts),
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
        "bundle_manifest_path": (
            str(result.bundle_manifest_path)
            if result.bundle_manifest_path
            else None
        ),
        "failure_reason_code": (
            result.failure.reason_code if result.failure else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path
            else None
        ),
    }
    print(json.dumps(payload, indent=2))
    if result.failure is not None:
        print(
            "ERROR: DERA acquisition failed; see the failure receipt. No "
            "acquisition manifest was written.",
            file=sys.stderr,
        )
        return 1
    return 0


def _main_dera_validate(args: argparse.Namespace) -> int:
    frame_manifest = Path(args.frame_manifest)
    dera_dir = Path(args.dera_dir)
    if not frame_manifest.is_file():
        print(f"ERROR: frame manifest not found: {frame_manifest}", file=sys.stderr)
        return 2
    if not dera_dir.is_dir():
        print(f"ERROR: DERA input directory not found: {dera_dir}", file=sys.stderr)
        return 2
    try:
        result = run_dera_validation(
            repo_root=REPO_ROOT,
            frame_manifest_path=frame_manifest,
            dera_dir=dera_dir,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            dry_run=args.dry_run,
        )
    except DeraInputError as exc:
        print(f"ERROR: invalid DERA validation input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "gate_status": result.gate_status,
        "failed_conditions": result.failed_conditions,
        "counts": result.counts,
        "noncoverage_by_form": result.noncoverage_by_form,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    if result.gate_status == "fail":
        print(
            "ERROR: DERA validation gate failed; see failed_conditions above.",
            file=sys.stderr,
        )
        return 1
    return 0


def _main_acquire_primary_docs(args: argparse.Namespace) -> int:
    request_plan = Path(args.request_plan)
    if not request_plan.is_file():
        print(f"ERROR: request plan not found: {request_plan}", file=sys.stderr)
        return 2
    # Both ceilings are plan-owned, so the plan is read before the transports
    # are built; the runner then refuses any transport bound differently.
    try:
        _, plan_fields, _ = load_primary_document_plan(request_plan)
    except PrimaryDocumentPlanError as exc:
        print(f"ERROR: invalid primary document request plan: {exc}", file=sys.stderr)
        return 2
    metadata_ceiling = plan_fields["max_metadata_bytes"]
    document_ceiling = plan_fields["max_document_bytes"]
    transport_choice = args.transport or "fixture"
    if transport_choice == "sec-live":
        metadata_transport = make_sec_live_document_transport(
            max_bytes=metadata_ceiling
        )
        primary_transport = make_sec_live_document_transport(
            max_bytes=document_ceiling
        )
        transport_identity = SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY
    else:
        replay_dir = Path(args.replay_dir)
        if not replay_dir.is_dir():
            print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
            return 2
        metadata_transport = make_filing_index_fixture_replay_transport(
            replay_dir, max_bytes=metadata_ceiling
        )
        primary_transport = make_primary_document_fixture_replay_transport(
            replay_dir, max_bytes=document_ceiling
        )
        transport_identity = None  # fixture-replay identity, v0.1 manifest
    try:
        result = run_primary_document_acquisition(
            repo_root=REPO_ROOT,
            request_plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            metadata_transport=metadata_transport,
            primary_transport=primary_transport,
            metadata_transport_max_bytes=metadata_ceiling,
            primary_transport_max_bytes=document_ceiling,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
            transport_identity=transport_identity,
        )
    except PrimaryDocumentPlanError as exc:
        print(f"ERROR: invalid primary document acquisition input: {exc}",
              file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "transport_kind": (
            transport_identity.kind if transport_identity else "fixture_replay"
        ),
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "plan_sha256": result.plan_sha256,
        "counts": result.counts,
        "bundle_manifest_path": (
            str(result.bundle_manifest_path)
            if result.bundle_manifest_path else None
        ),
        "acquisition_manifest_path": (
            str(result.acquisition_manifest_path)
            if result.acquisition_manifest_path else None
        ),
        "failure_reason_code": (
            result.failure.reason_code if result.failure else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    if result.failure is not None:
        print(
            "ERROR: primary document acquisition failed; see the failure "
            "receipt. No bundle manifest and no acquisition manifest were "
            "written, so this run is not an authoritative bundle.",
            file=sys.stderr,
        )
        return 1
    return 0


def _parse_shard_indices(raw: str) -> list[int]:
    """Enumerated integers only: no ranges, no globs, no 'all'."""
    if not raw.strip():
        raise AcquisitionQueueError(
            "--shard-indices must enumerate at least one index."
        )
    parts = [p.strip() for p in raw.split(",")]
    if any(not p for p in parts):
        raise AcquisitionQueueError(
            f"--shard-indices {raw!r} has an empty segment; enumerate indices "
            "exactly, with no trailing or repeated commas."
        )
    indices = []
    for part in parts:
        if not part.isdigit():
            raise AcquisitionQueueError(
                f"--shard-indices accepts enumerated non-negative integers "
                f"only; {part!r} is not one. Ranges and 'all' are refused."
            )
        indices.append(int(part))
    return indices


def _parse_execution_run_ids(raw: str) -> list[str]:
    """Enumerated run ids only: no ranges, no globs, no 'all'.

    Parsed at the entrypoint so a malformed enumeration is refused before the
    aggregator is reached, and therefore before any run directory could be
    created. The aggregator re-checks what it is handed.
    """
    if not raw.strip():
        raise AcquisitionQueueError(
            "--execution-run-ids must enumerate at least one execution run."
        )
    parts = [p.strip() for p in raw.split(",")]
    if any(not p for p in parts):
        raise AcquisitionQueueError(
            f"--execution-run-ids {raw!r} has an empty segment; enumerate the "
            "runs exactly, with no trailing or repeated commas."
        )
    duplicates = sorted({p for p in parts if parts.count(p) > 1})
    if duplicates:
        raise AcquisitionQueueError(
            f"--execution-run-ids {raw!r} repeats {duplicates}; each "
            "execution run is named once."
        )
    return parts


def _primary_transports(args: argparse.Namespace, definition: dict):
    """Build the two hop transports from the queue definition's ceilings.

    Returns (metadata_transport, primary_transport, identity) or None after
    printing the error. Ceilings are definition-owned exactly as they are
    plan-owned for a direct acquisition; the runner still refuses any
    transport bound differently.
    """
    metadata_ceiling = definition["max_metadata_bytes"]
    document_ceiling = definition["max_document_bytes"]
    if (args.transport or "fixture") == "sec-live":
        return (
            make_sec_live_document_transport(max_bytes=metadata_ceiling),
            make_sec_live_document_transport(max_bytes=document_ceiling),
            SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
        )
    replay_dir = Path(args.replay_dir)
    if not replay_dir.is_dir():
        print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
        return None
    return (
        make_filing_index_fixture_replay_transport(
            replay_dir, max_bytes=metadata_ceiling
        ),
        make_primary_document_fixture_replay_transport(
            replay_dir, max_bytes=document_ceiling
        ),
        None,  # fixture-replay identity
    )


def _main_plan_acquisition_queue(args: argparse.Namespace) -> int:
    try:
        result = run_queue_planner(
            repo_root=REPO_ROOT,
            definition_path=Path(args.queue_definition),
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except AcquisitionQueueError as exc:
        print(f"ERROR: invalid queue definition or carrier: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id,
        "dry_run": args.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "queue_definition_sha256": result.definition_sha256,
        "counts": result.counts,
        "shard_plan_sha256": {
            s.shard_index: s.plan_sha256 for s in result.shards
        } if len(result.shards) <= 8 else "omitted: more than 8 shards",
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }, indent=2))
    return 0


def _main_execute_acquisition_queue(args: argparse.Namespace) -> int:
    try:
        indices = _parse_shard_indices(args.shard_indices)
    except AcquisitionQueueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    plan_path = Path(args.plan_dir)
    if not plan_path.is_dir():
        print(f"ERROR: plan directory not found: {plan_path}", file=sys.stderr)
        return 2
    definition_path = Path(args.queue_definition)
    if not definition_path.is_file():
        print(f"ERROR: queue definition not found: {definition_path}",
              file=sys.stderr)
        return 2
    definition = json.loads(definition_path.read_text(encoding="utf-8"))
    transports = _primary_transports(args, definition)
    if transports is None:
        return 2
    metadata_transport, primary_transport, identity = transports
    try:
        result = run_queue_executor(
            repo_root=REPO_ROOT,
            definition_path=Path(args.queue_definition),
            plan_dir=plan_path,
            shard_indices=indices,
            expected_request_count=args.expected_request_count,
            on_shard_failure=args.on_shard_failure,
            output_dir=Path(args.shard_output_dir or args.output_dir),
            run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc),
            metadata_transport=metadata_transport,
            primary_transport=primary_transport,
            metadata_transport_max_bytes=definition["max_metadata_bytes"],
            primary_transport_max_bytes=definition["max_document_bytes"],
            transport_identity=identity,
        )
    except (AcquisitionQueueError, PrimaryDocumentPlanError) as exc:
        print(f"ERROR: queue execution refused: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "authorized_shard_indices": sorted(indices),
        "on_shard_failure": args.on_shard_failure,
        "stopped_at_shard_index": result.stopped_at_shard_index,
        "counts": result.counts,
        "shards": [
            {"shard_index": e.shard_index, "outcome": e.outcome,
             "retained_bytes_total": e.retained_bytes_total,
             "failure_reason_code": e.failure_reason_code,
             "receipt_present": e.receipt_present}
            for e in result.executions
        ],
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }, indent=2))
    return 0


def _main_aggregate_acquisition_queue(args: argparse.Namespace) -> int:
    try:
        aggregate = run_queue_aggregator(
            repo_root=REPO_ROOT,
            definition_path=Path(args.queue_definition),
            shard_output_dir=Path(args.shard_output_dir),
            execution_run_id=args.execution_run_id,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except AcquisitionQueueError as exc:
        print(f"ERROR: aggregation refused: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    manifest = aggregate.manifest
    print(json.dumps({
        "run_id": manifest["run_id"],
        "run_dir": str(aggregate.run_dir) if aggregate.run_dir else None,
        "coverage_complete": manifest["coverage_complete"],
        "coverage_statement": manifest["coverage_statement"],
        "counts": manifest["counts"],
        "shards_not_authoritative": manifest["shards_not_authoritative"],
    }, indent=2))
    return 0


def _main_aggregate_acquisition_lineage(args: argparse.Namespace) -> int:
    try:
        execution_run_ids = _parse_execution_run_ids(args.execution_run_ids)
        aggregate = run_lineage_aggregator(
            repo_root=REPO_ROOT,
            definition_path=Path(args.queue_definition),
            shard_output_dir=Path(args.shard_output_dir),
            execution_run_ids=execution_run_ids,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except AcquisitionQueueError as exc:
        print(f"ERROR: lineage aggregation refused: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    manifest = aggregate.manifest
    print(json.dumps({
        "run_id": manifest["run_id"],
        "run_dir": str(aggregate.run_dir) if aggregate.run_dir else None,
        "execution_run_ids": manifest["execution_run_ids"],
        "coverage_complete": manifest["coverage_complete"],
        "coverage_statement": manifest["coverage_statement"],
        "counts": manifest["counts"],
        "shards_not_authoritative": manifest["shards_not_authoritative"],
        "superseded_directories": manifest["superseded_directories"],
    }, indent=2))
    return 0


def _main_determine_shell_company(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle_dir)
    if not bundle_dir.is_dir():
        print(f"ERROR: bundle directory not found: {bundle_dir}", file=sys.stderr)
        return 2
    try:
        result = run_shell_company_determination(
            repo_root=REPO_ROOT,
            bundle_dir=bundle_dir,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            # The ingestion package never reads the clock; the entrypoint owns
            # identity and injects it.
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except (ShellDeterminationError, PacketBundleError) as exc:
        print(f"ERROR: invalid shell determination input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "bundle_manifest_sha256": result.bundle_manifest_sha256,
        "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_determine_shell_company_lineage(args: argparse.Namespace) -> int:
    # One path in, and it is a file: this mode has no directory argument at
    # all, so there is nothing here that could widen what the run may open.
    aggregate_manifest = Path(args.aggregate_manifest)
    if not aggregate_manifest.is_file():
        print(f"ERROR: aggregate manifest not found: {aggregate_manifest}",
              file=sys.stderr)
        return 2
    try:
        result = run_lineage_shell_company_determination(
            repo_root=REPO_ROOT,
            aggregate_manifest_path=aggregate_manifest,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except (ShellDeterminationError, PacketBundleError) as exc:
        print(f"ERROR: invalid lineage determination input: {exc}",
              file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "aggregate_manifest_sha256": result.bundle_manifest_sha256,
        "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_determine_asset_backed_issuer_lineage(
        args: argparse.Namespace) -> int:
    # One path in, and it is a file: this mode has no directory argument at
    # all, so there is nothing here that could widen what the run may open.
    aggregate_manifest = Path(args.aggregate_manifest)
    if not aggregate_manifest.is_file():
        print(f"ERROR: aggregate manifest not found: {aggregate_manifest}",
              file=sys.stderr)
        return 2
    try:
        result = run_asset_backed_determination(
            repo_root=REPO_ROOT,
            aggregate_manifest_path=aggregate_manifest,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except (AssetBackedDeterminationError, PacketBundleError) as exc:
        print(f"ERROR: invalid asset-backed determination input: {exc}",
              file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "aggregate_manifest_sha256": result.aggregate_manifest_sha256,
        "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_build_baseline_packets_lineage(args: argparse.Namespace) -> int:
    # Two files in, nothing else: this mode has no directory argument at all,
    # so there is nothing here that could widen what the run may open.
    aggregate_manifest = Path(args.aggregate_manifest)
    determination_manifest = Path(args.shell_determination_manifest)
    for label, path in (("aggregate manifest", aggregate_manifest),
                        ("determination manifest", determination_manifest)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = run_lineage_packet_build(
            repo_root=REPO_ROOT,
            aggregate_manifest_path=aggregate_manifest,
            determination_manifest_path=determination_manifest,
            project_config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            # Passed exactly as typed: the library's closed-mapping lookup is
            # the authority, with no normalization of any kind.
            item_one_locator=args.item_one_locator,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except PacketBundleError as exc:
        print(f"ERROR: invalid lineage packet input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "aggregate_manifest_sha256": result.aggregate_manifest_sha256,
        "determination_manifest_sha256": result.determination_manifest_sha256,
        "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_build_baseline_packets_lineage_v2(
        args: argparse.Namespace) -> int:
    # Three files in, nothing else: this mode has no directory argument at
    # all, so there is nothing here that could widen what the run may open.
    aggregate_manifest = Path(args.aggregate_manifest)
    shell_manifest = Path(args.shell_determination_manifest)
    abs_manifest = Path(args.asset_backed_determination_manifest)
    for label, path in (("aggregate manifest", aggregate_manifest),
                        ("shell determination manifest", shell_manifest),
                        ("asset-backed determination manifest",
                         abs_manifest)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = run_lineage_packet_build_v2(
            repo_root=REPO_ROOT,
            aggregate_manifest_path=aggregate_manifest,
            shell_determination_manifest_path=shell_manifest,
            asset_backed_determination_manifest_path=abs_manifest,
            project_config_path=Path(args.config),
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            item_one_locator=args.item_one_locator,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except PacketBundleError as exc:
        print(f"ERROR: invalid lineage packet input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "aggregate_manifest_sha256": result.aggregate_manifest_sha256,
        "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_screen_universe_lineage(args: argparse.Namespace) -> int:
    # One file of authority, one fixture of scripted outputs, nothing else:
    # this mode has no directory argument at all.
    packet_manifest = Path(args.packet_manifest)
    fixture_path = Path(args.screen_fixture)
    if not packet_manifest.is_file():
        print(f"ERROR: packet manifest not found: {packet_manifest}",
              file=sys.stderr)
        return 2
    if not fixture_path.is_file():
        print(f"ERROR: screen fixture not found: {fixture_path}",
              file=sys.stderr)
        return 2
    try:
        provider = MockLineageScreenProvider(
            json.loads(fixture_path.read_text(encoding="utf-8"))
        )
        result = run_lineage_screen(
            repo_root=REPO_ROOT,
            packet_manifest_path=packet_manifest,
            provider=provider,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            logical_request_cap=args.logical_request_cap,
            provider_attempt_cap=args.provider_attempt_cap,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid screen input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "planned_insufficient": result.planned_insufficient,
        "counts": result.counts,
        "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path else None
        ),
        "receipt": result.receipt,
    }
    print(json.dumps(payload, indent=2))
    if result.status == "failed":
        print("ERROR: screen run stopped with a failure receipt; the run "
              "directory is non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_screen_universe_lineage_live(args: argparse.Namespace) -> int:
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}",
              file=sys.stderr)
        return 2
    try:
        result = run_lineage_screen_live(
            repo_root=REPO_ROOT,
            packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            logical_request_cap=args.logical_request_cap,
            provider_attempt_cap=args.provider_attempt_cap,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid live screen input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "planned_insufficient": result.planned_insufficient,
        "counts": result.counts,
        "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path else None
        ),
        "receipt": result.receipt,
    }
    print(json.dumps(payload, indent=2))
    if result.status == "failed":
        print("ERROR: live screen run stopped with a failure receipt; the "
              "run directory is non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_screen_universe_lineage_live_v2(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-116 evidence-safe authoritative successor."""
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}", file=sys.stderr)
        return 2
    try:
        result = run_lineage_screen_live_v2(
            repo_root=REPO_ROOT, packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            logical_request_cap=args.logical_request_cap,
            provider_attempt_cap=args.provider_attempt_cap,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid live v2 screen input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id, "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "planned_insufficient": result.planned_insufficient,
        "counts": result.counts,
        "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "failure_receipt_path": str(result.failure_receipt_path) if result.failure_receipt_path else None,
        "receipt": result.receipt,
    }, indent=2))
    if result.status == "failed":
        print("ERROR: live v2 screen stopped with a failure receipt; the run is non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_screen_universe_lineage_live_v3(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-117 long-backoff authoritative successor."""
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}",
              file=sys.stderr)
        return 2
    try:
        result = run_lineage_screen_live_v3(
            repo_root=REPO_ROOT, packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            logical_request_cap=args.logical_request_cap,
            provider_attempt_cap=args.provider_attempt_cap,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid live v3 screen input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id, "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "planned_insufficient": result.planned_insufficient,
        "counts": result.counts,
        "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path else None),
        "receipt": result.receipt,
    }, indent=2))
    if result.status == "failed":
        print("ERROR: live v3 screen stopped with a failure receipt; the run "
              "is non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_screen_universe_lineage_continuation(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-118 governed continuation route."""
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    source_run_dir = Path(args.source_run_dir)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    for label, path in (("governance root", governance_root),
                        ("source run directory", source_run_dir)):
        if not path.is_dir():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = run_lineage_screen_continuation(
            repo_root=REPO_ROOT, packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            source_run_dir=source_run_dir,
            source_receipt_sha256=args.source_receipt_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid continuation input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id, "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "planned_insufficient": result.planned_insufficient,
        "counts": result.counts,
        "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path else None),
        "receipt": result.receipt,
    }, indent=2))
    if result.status == "failed":
        print("ERROR: continuation stopped with a failure receipt; the run is "
              "non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_screen_universe_lineage_continuation_v2(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-119 empty-body-tolerant continuation."""
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    source_run_dir = Path(args.source_run_dir)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    for label, path in (("governance root", governance_root),
                        ("source run directory", source_run_dir)):
        if not path.is_dir():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = run_lineage_screen_continuation_v2(
            repo_root=REPO_ROOT, packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            source_run_dir=source_run_dir,
            source_receipt_sha256=args.source_receipt_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid continuation v2 input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id, "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "planned_insufficient": result.planned_insufficient,
        "counts": result.counts, "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (str(result.manifest_path) if result.manifest_path else None),
        "failure_receipt_path": (str(result.failure_receipt_path)
                                 if result.failure_receipt_path else None),
        "receipt": result.receipt,
    }, indent=2))
    if result.status == "failed":
        print("ERROR: continuation v2 stopped with a failure receipt; the run is "
              "non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_screen_universe_lineage_continuation_v3(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-120 empty-count-tolerant continuation."""
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    source_run_dir = Path(args.source_run_dir)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    for label, path in (("governance root", governance_root),
                        ("source run directory", source_run_dir)):
        if not path.is_dir():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = run_lineage_screen_continuation_v3(
            repo_root=REPO_ROOT, packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            source_run_dir=source_run_dir,
            source_receipt_sha256=args.source_receipt_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid continuation v3 input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id, "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "planned_insufficient": result.planned_insufficient,
        "counts": result.counts, "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (str(result.manifest_path) if result.manifest_path else None),
        "failure_receipt_path": (str(result.failure_receipt_path)
                                 if result.failure_receipt_path else None),
        "receipt": result.receipt,
    }, indent=2))
    if result.status == "failed":
        print("ERROR: continuation v3 stopped with a failure receipt; the run is "
              "non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_screen_universe_lineage_continuation_v4(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-121 provider-unresolved-tolerant continuation."""
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    source_run_dir = Path(args.source_run_dir)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    for label, path in (("governance root", governance_root),
                        ("source run directory", source_run_dir)):
        if not path.is_dir():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = run_lineage_screen_continuation_v4(
            repo_root=REPO_ROOT, packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            source_run_dir=source_run_dir,
            source_receipt_sha256=args.source_receipt_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid continuation v4 input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id, "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "planned_insufficient": result.planned_insufficient,
        "counts": result.counts, "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (str(result.manifest_path) if result.manifest_path else None),
        "failure_receipt_path": (str(result.failure_receipt_path)
                                 if result.failure_receipt_path else None),
        "receipt": result.receipt,
    }, indent=2))
    if result.status == "failed":
        print("ERROR: continuation v4 stopped with a failure receipt; the run is "
              "non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_screen_universe_lineage_continuation_v5(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-122 truncated-output-tolerant continuation."""
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    source_run_dir = Path(args.source_run_dir)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    for label, path in (("governance root", governance_root),
                        ("source run directory", source_run_dir)):
        if not path.is_dir():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = run_lineage_screen_continuation_v5(
            repo_root=REPO_ROOT, packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            source_run_dir=source_run_dir,
            source_receipt_sha256=args.source_receipt_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid continuation v5 input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id, "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "planned_insufficient": result.planned_insufficient,
        "counts": result.counts, "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (str(result.manifest_path) if result.manifest_path else None),
        "failure_receipt_path": (str(result.failure_receipt_path)
                                 if result.failure_receipt_path else None),
        "receipt": result.receipt,
    }, indent=2))
    if result.status == "failed":
        print("ERROR: continuation v5 stopped with a failure receipt; the run is "
              "non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_build_human_review_overlay(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-125 overlay. Ingests decisions; calls no model."""
    release = Path(args.release_manifest)
    ledger = Path(args.decision_ledger)
    for label, path in (("release manifest", release),
                        ("decision ledger", ledger)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = build_human_review_overlay(
            repo_root=REPO_ROOT, release_manifest_path=release,
            release_manifest_sha256=args.release_manifest_sha256,
            ledger_path=ledger, output_dir=Path(args.output_dir),
            overlay_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run)
    except ScreenInputError as exc:
        print(f"ERROR: invalid human-review input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "overlay_id": result.overlay_id, "dry_run": result.dry_run,
        "status": result.status,
        "overlay_dir": str(result.overlay_dir) if result.overlay_dir else None,
        "coverage": result.coverage, "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (str(result.manifest_path) if result.manifest_path
                          else None),
    }, indent=2))
    return 0


def _main_build_classifier_candidate_cohort(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-125 cohort. Derives admission; calls no model."""
    release = Path(args.release_manifest)
    overlay = Path(args.overlay_manifest)
    for label, path in (("release manifest", release),
                        ("overlay manifest", overlay)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = build_classifier_candidate_cohort(
            repo_root=REPO_ROOT, release_manifest_path=release,
            release_manifest_sha256=args.release_manifest_sha256,
            overlay_manifest_path=overlay,
            overlay_manifest_sha256=args.overlay_manifest_sha256,
            output_dir=Path(args.output_dir), cohort_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run)
    except ScreenInputError as exc:
        print(f"ERROR: invalid cohort input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "cohort_id": result.cohort_id, "dry_run": result.dry_run,
        "status": result.status,
        "cohort_dir": str(result.cohort_dir) if result.cohort_dir else None,
        "counts": result.counts, "exclusions": result.exclusions,
        "reconciliation": result.reconciliation,
        "manifest_path": (str(result.manifest_path) if result.manifest_path
                          else None),
    }, indent=2))
    return 0


def _main_build_screen_release(args: argparse.Namespace) -> int:
    """CLI boundary for ADR-124. Derives a release; calls no model."""
    base = Path(args.base_screen_manifest)
    repair = Path(args.repair_manifest)
    for label, path in (("base screen manifest", base),
                        ("repair manifest", repair)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = build_screen_release(
            repo_root=REPO_ROOT, base_manifest_path=base,
            base_manifest_sha256=args.base_screen_manifest_sha256,
            repair_manifest_path=repair,
            repair_manifest_sha256=args.repair_manifest_sha256,
            output_dir=Path(args.output_dir), release_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run)
    except ScreenInputError as exc:
        print(f"ERROR: invalid release input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "release_id": result.release_id, "dry_run": result.dry_run,
        "status": result.status,
        "release_dir": str(result.release_dir) if result.release_dir else None,
        "counts": result.counts, "rates": result.rates,
        "reconciliation": result.reconciliation,
        "manifest_path": (str(result.manifest_path) if result.manifest_path
                          else None),
    }, indent=2))
    return 0


def _main_select_screen_unverified_repair_rows(args: argparse.Namespace) -> int:
    """CLI boundary for ADR-123 Stage 1. Derives rows; calls no model."""
    source_manifest = Path(args.source_screen_manifest)
    if not source_manifest.is_file():
        print(f"ERROR: source screen manifest not found: {source_manifest}",
              file=sys.stderr)
        return 2
    output_path = Path(args.output_dir) / args.run_id / REPAIR_SELECTION_FILENAME
    try:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        selection = build_unverified_repair_selection(
            repo_root=REPO_ROOT, source_manifest_path=source_manifest,
            output_path=output_path, selection_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc))
    except ScreenInputError as exc:
        print(f"ERROR: invalid repair selection input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "selection_id": selection["selection_id"],
        "selection_kind": selection["selection_kind"],
        "derivation_rule": selection["derivation_rule"],
        "source_run_id": selection["source_run_id"],
        "selection_artifact": str(output_path),
        "counts": selection["counts"],
    }, indent=2))
    return 0


def _main_select_classifier_calibration_rows(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-127 calibration selection. No model call."""
    cohort = Path(args.cohort_manifest)
    release = Path(args.release_manifest)
    overlay = Path(args.overlay_manifest)
    for label, path in (("cohort manifest", cohort), ("release manifest", release),
                        ("overlay manifest", overlay)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    output_path = Path(args.output_dir) / args.run_id / CALIBRATION_SELECTION_FILENAME
    # The directory is the write-once reservation of a selection id, so only an
    # invocation that will actually write may claim it. A dry run computes the
    # same selection and leaves the id free for the real run.
    if not args.dry_run:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            print(f"ERROR: {output_path.parent} already exists; a selection is "
                  "written once.", file=sys.stderr)
            return 2
    try:
        selection = build_calibration_selection(
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            cohort_manifest_sha256=args.cohort_manifest_sha256,
            release_manifest_path=release,
            release_manifest_sha256=args.release_manifest_sha256,
            overlay_manifest_path=overlay,
            overlay_manifest_sha256=args.overlay_manifest_sha256,
            output_path=output_path, selection_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run)
    except (ScreenInputError, StrataRulesError) as exc:
        print(f"ERROR: invalid calibration selection input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "selection_id": selection["selection_id"], "dry_run": args.dry_run,
        "output_path": None if args.dry_run else str(output_path),
        "counts": selection["counts"], "sampling": selection["sampling"],
    }, indent=2))
    return 0


def _main_build_annual_coverage_cohort(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-138 annual filing-year restriction. No model call."""
    cohort = Path(args.cohort_manifest)
    frame = Path(args.frame_manifest)
    for label, path in (("candidate cohort manifest", cohort),
                        ("FRAME manifest", frame)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    cohort_dir = Path(args.output_dir) / args.run_id
    # The directory is the write-once reservation of a coverage cohort id, so only
    # an invocation that will actually write may claim it. A dry run derives the
    # identical partition and leaves the id free.
    if not args.dry_run:
        try:
            cohort_dir.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            print(f"ERROR: {cohort_dir} already exists; a coverage cohort is "
                  "written once.", file=sys.stderr)
            return 2
    try:
        result = build_annual_coverage_cohort(
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            cohort_manifest_sha256=args.cohort_manifest_sha256,
            frame_manifest_path=frame,
            frame_manifest_sha256=args.frame_manifest_sha256,
            output_dir=Path(args.output_dir), coverage_cohort_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run)
    except ScreenInputError as exc:
        print(f"ERROR: invalid annual coverage input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "coverage_cohort_id": result.manifest["coverage_cohort_id"],
        "dry_run": args.dry_run,
        "cohort_dir": str(result.cohort_dir) if result.cohort_dir else None,
        "counts": result.manifest["counts"],
        "coverage_rule": result.manifest["coverage_rule"],
        "artifact_role": result.manifest["artifact_role"],
        "no_model_call": result.manifest["no_model_call"],
    }, indent=2))
    return 0


def _main_select_classifier_pilot_rows(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-137 ten-firm pilot selection. No model call."""
    cohort = Path(args.cohort_manifest)
    source = Path(args.calibration_selection)
    for label, path in (("cohort manifest", cohort),
                        ("source calibration selection", source)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    output_path = Path(args.output_dir) / args.run_id / PILOT_SELECTION_FILENAME
    # As with the calibration selection, the directory is the write-once
    # reservation of a selection id, so only an invocation that will actually
    # write may claim it. A dry run derives the same ten rows and leaves the id
    # free for the run that will keep them.
    if not args.dry_run:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            print(f"ERROR: {output_path.parent} already exists; a selection is "
                  "written once.", file=sys.stderr)
            return 2
    try:
        selection = build_pilot_selection_artifact(
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            cohort_manifest_sha256=args.cohort_manifest_sha256,
            source_selection_path=source,
            source_selection_sha256=args.calibration_selection_sha256,
            output_path=output_path, selection_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run)
    except (ScreenInputError, ValueError) as exc:
        print(f"ERROR: invalid pilot selection input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "selection_id": selection["selection_id"], "dry_run": args.dry_run,
        "output_path": None if args.dry_run else str(output_path),
        "counts": selection["counts"], "sampling": selection["sampling"],
    }, indent=2))
    return 0


def _main_select_classifier_pilot_rows_v2(args: argparse.Namespace) -> int:
    """Build the annual-coverage-backed ADR-139 pilot selection. No model call."""
    coverage = Path(args.annual_coverage_cohort_manifest)
    cohort = Path(args.cohort_manifest)
    packet = Path(args.packet_manifest)
    for label, path in (("annual coverage cohort manifest", coverage),
                        ("candidate cohort manifest", cohort),
                        ("packet manifest", packet)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    output_path = Path(args.output_dir) / args.run_id / PILOT_SELECTION_V2_FILENAME
    if not args.dry_run:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            print(f"ERROR: {output_path.parent} already exists; a selection is "
                  "written once.", file=sys.stderr)
            return 2
    try:
        selection = build_pilot_selection_v2_artifact(
            repo_root=REPO_ROOT,
            coverage_manifest_path=coverage,
            coverage_manifest_sha256=args.annual_coverage_cohort_manifest_sha256,
            candidate_cohort_manifest_path=cohort,
            candidate_cohort_manifest_sha256=args.cohort_manifest_sha256,
            packet_manifest_path=packet,
            packet_manifest_sha256=_sha256(packet.read_bytes()),
            output_path=output_path,
            selection_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except (ScreenInputError, ValueError) as exc:
        print(f"ERROR: invalid pilot V2 selection input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "selection_id": selection["selection_id"], "dry_run": args.dry_run,
        "output_path": None if args.dry_run else str(output_path),
        "coverage_cohort_id": selection["coverage_cohort_id"],
        "counts": selection["counts"], "sampling": selection["sampling"],
    }, indent=2))
    return 0


def _main_classify_software_universe_pilot_v1(args: argparse.Namespace) -> int:
    """CLI boundary for the ADR-137 governed live firm-level pilot run.

    Deliberately not routed through ``_classifier_paths``: that helper resolves
    the overlay and release a V2.x run needs to render the earlier verdict, and
    the pilot must never load them. Its inputs are the cohort, the packet cohort
    and its own ten-row selection.
    """
    cohort = Path(args.cohort_manifest)
    packet = Path(args.packet_manifest)
    selection = Path(args.pilot_selection)
    for label, path in (("cohort manifest", cohort), ("packet manifest", packet),
                        ("pilot selection", selection)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    governance_root = Path(args.governance_root)
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}",
              file=sys.stderr)
        return 2
    try:
        result = run_lineage_classifier_pilot_v1(
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            packet_manifest_path=packet, selection_path=selection,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid pilot input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _report_classifier_run(result, what="pilot run")


def _main_classify_software_universe_pilot_v2(args: argparse.Namespace) -> int:
    """CLI boundary for the annual-coverage-backed governed pilot run."""
    cohort = Path(args.cohort_manifest)
    coverage = Path(args.annual_coverage_cohort_manifest)
    packet = Path(args.packet_manifest)
    selection = Path(args.pilot_selection)
    for label, path in (("cohort manifest", cohort),
                        ("annual coverage cohort manifest", coverage),
                        ("packet manifest", packet), ("pilot selection", selection)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    governance_root = Path(args.governance_root)
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}", file=sys.stderr)
        return 2
    try:
        result = run_lineage_classifier_pilot_v2(
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            coverage_manifest_path=coverage, packet_manifest_path=packet,
            selection_path=selection, governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid V2 pilot input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _report_classifier_run(result, what="pilot V2 run")


def _main_classify_software_universe_pilot_v3(args: argparse.Namespace) -> int:
    """CLI boundary for the narrow two-axis annual-coverage pilot gate."""
    cohort = Path(args.cohort_manifest)
    coverage = Path(args.annual_coverage_cohort_manifest)
    packet = Path(args.packet_manifest)
    selection = Path(args.pilot_selection)
    for label, path in (("cohort manifest", cohort),
                        ("annual coverage cohort manifest", coverage),
                        ("packet manifest", packet), ("pilot selection", selection)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    governance_root = Path(args.governance_root)
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}", file=sys.stderr)
        return 2
    try:
        result = run_lineage_classifier_pilot_v3(
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            coverage_manifest_path=coverage, packet_manifest_path=packet,
            selection_path=selection, governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid V3 pilot input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _report_classifier_run(result, what="pilot V3 run")

def _main_classify_software_universe_pilot_v4(args: argparse.Namespace) -> int:
    """CLI boundary for the product-first annual-coverage pilot gate."""
    cohort = Path(args.cohort_manifest)
    coverage = Path(args.annual_coverage_cohort_manifest)
    packet = Path(args.packet_manifest)
    selection = Path(args.pilot_selection)
    for label, path in (("cohort manifest", cohort),
                        ("annual coverage cohort manifest", coverage),
                        ("packet manifest", packet), ("pilot selection", selection)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    governance_root = Path(args.governance_root)
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}", file=sys.stderr)
        return 2
    try:
        result = run_lineage_classifier_pilot_v4(
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            coverage_manifest_path=coverage, packet_manifest_path=packet,
            selection_path=selection, governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid V4 pilot input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _report_classifier_run(result, what="pilot V4 run")

def _main_classify_software_universe_pilot_v5(args: argparse.Namespace) -> int:
    """CLI boundary for the product-first annual-coverage pilot gate."""
    cohort = Path(args.cohort_manifest)
    coverage = Path(args.annual_coverage_cohort_manifest)
    packet = Path(args.packet_manifest)
    selection = Path(args.pilot_selection)
    for label, path in (("cohort manifest", cohort),
                        ("annual coverage cohort manifest", coverage),
                        ("packet manifest", packet), ("pilot selection", selection)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    governance_root = Path(args.governance_root)
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}", file=sys.stderr)
        return 2
    try:
        result = run_lineage_classifier_pilot_v5(
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            coverage_manifest_path=coverage, packet_manifest_path=packet,
            selection_path=selection, governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid V5 pilot input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _report_classifier_run(result, what="pilot V5 run")


def _main_classify_software_universe_pilot_v6(args: argparse.Namespace) -> int:
    """CLI boundary for the stricter group-level CORE pilot gate."""
    cohort = Path(args.cohort_manifest)
    coverage = Path(args.annual_coverage_cohort_manifest)
    packet = Path(args.packet_manifest)
    selection = Path(args.pilot_selection)
    for label, path in (("cohort manifest", cohort),
                        ("annual coverage cohort manifest", coverage),
                        ("packet manifest", packet), ("pilot selection", selection)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    governance_root = Path(args.governance_root)
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}", file=sys.stderr)
        return 2
    try:
        result = run_lineage_classifier_pilot_v6(
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            coverage_manifest_path=coverage, packet_manifest_path=packet,
            selection_path=selection, governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid V6 pilot input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _report_classifier_run(result, what="pilot V6 run")


def _main_classify_universe_calibration(args: argparse.Namespace, *,
                                        route=None) -> int:
    """CLI boundary for the ADR-127 governed live calibration run."""
    resolved = _classifier_paths(args)
    if resolved is None:
        return 2
    cohort, overlay, release, packet, governance_root = resolved
    selection = Path(args.calibration_selection)
    if not selection.is_file():
        print(f"ERROR: calibration selection not found: {selection}",
              file=sys.stderr)
        return 2
    try:
        result = run_lineage_classifier_calibration(
            route=route or CALIBRATION_ROUTE,
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            overlay_manifest_path=overlay, release_manifest_path=release,
            packet_manifest_path=packet, selection_path=selection,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid calibration input: {exc}", file=sys.stderr)
        return 2
    except TierRulesError as exc:
        print(f"ERROR: unusable tier rules: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _report_classifier_run(result, what="calibration run")


def _main_build_classifier_calibration_review(
        args: argparse.Namespace, *, calibration_route=None) -> int:
    """CLI boundary for the ADR-127 qualitative review gate. No model call."""
    run_dir = Path(args.calibration_run_dir)
    selection = Path(args.calibration_selection)
    if not run_dir.is_dir():
        print(f"ERROR: calibration run directory not found: {run_dir}",
              file=sys.stderr)
        return 2
    if not selection.is_file():
        print(f"ERROR: calibration selection not found: {selection}",
              file=sys.stderr)
        return 2
    output_path = Path(args.output_dir) / args.run_id / REVIEW_FILENAME
    # As with the selection, the directory is the write-once reservation of a
    # review id. A dry run derives the same review and leaves the id free.
    if not args.dry_run:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            print(f"ERROR: {output_path.parent} already exists; a review is "
                  "written once.", file=sys.stderr)
            return 2
    try:
        review = build_calibration_review(
            calibration_route=calibration_route or CALIBRATION_ROUTE,
            repo_root=REPO_ROOT, calibration_run_dir=run_dir,
            selection_path=selection,
            selection_sha256=args.calibration_selection_sha256,
            output_path=output_path, review_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run)
    except ScreenInputError as exc:
        print(f"ERROR: invalid calibration review input: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "review_id": review["review_id"], "dry_run": args.dry_run,
        "output_path": None if args.dry_run else str(output_path),
        "gate_state": review["gate_state"], "reviewer_id": review["reviewer_id"],
        "review_protocol_version": review["review_protocol_version"],
        "counts": review["counts"],
    }, indent=2))
    return 0


def _classifier_paths(args: argparse.Namespace):
    """Resolve and existence-check the four pinned classifier inputs."""
    paths = {
        "cohort manifest": Path(args.cohort_manifest),
        "overlay manifest": Path(args.overlay_manifest),
        "release manifest": Path(args.release_manifest),
        "packet manifest": Path(args.packet_manifest),
    }
    for label, path in paths.items():
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return None
    governance_root = Path(args.governance_root)
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}",
              file=sys.stderr)
        return None
    return list(paths.values()) + [governance_root]


def _report_classifier_run(result, *, what: str) -> int:
    print(json.dumps({
        "run_id": result.run_id, "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "counts": result.counts, "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (str(result.manifest_path) if result.manifest_path
                          else None),
        "failure_receipt_path": (str(result.failure_receipt_path)
                                 if result.failure_receipt_path else None),
        "receipt": result.receipt,
    }, indent=2))
    if result.status == "failed":
        print(f"ERROR: {what} stopped with a failure receipt; the run is "
              "non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_classify_universe_cohort(args: argparse.Namespace, *,
                                   route=None) -> int:
    """CLI boundary for the ADR-126 governed live classifier."""
    resolved = _classifier_paths(args)
    if resolved is None:
        return 2
    cohort, overlay, release, packet, governance_root = resolved
    try:
        result = run_lineage_classifier(
            route=route or BASE_ROUTE,
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            overlay_manifest_path=overlay, release_manifest_path=release,
            packet_manifest_path=packet, governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid classifier input: {exc}", file=sys.stderr)
        return 2
    except TierRulesError as exc:
        print(f"ERROR: unusable tier rules: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _report_classifier_run(result, what="classifier run")


def _main_classify_universe_cohort_continuation(args: argparse.Namespace, *,
                                                route=None) -> int:
    """CLI boundary for the ADR-126 immutable-prefix continuation."""
    resolved = _classifier_paths(args)
    if resolved is None:
        return 2
    cohort, overlay, release, packet, governance_root = resolved
    source_run_dir = Path(args.source_run_dir)
    if not source_run_dir.is_dir():
        print(f"ERROR: source run directory not found: {source_run_dir}",
              file=sys.stderr)
        return 2
    try:
        result = run_lineage_classifier_continuation(
            route=route or CONTINUATION_ROUTE,
            repo_root=REPO_ROOT, cohort_manifest_path=cohort,
            overlay_manifest_path=overlay, release_manifest_path=release,
            packet_manifest_path=packet, governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            source_run_dir=source_run_dir,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid classifier continuation input: {exc}",
              file=sys.stderr)
        return 2
    except TierRulesError as exc:
        print(f"ERROR: unusable tier rules: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    return _report_classifier_run(result, what="classifier continuation run")


def _main_screen_universe_unverified_repair(args: argparse.Namespace) -> int:
    """CLI boundary for ADR-123 Stage 2. Re-asks; never edits."""
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    source_manifest = Path(args.source_screen_manifest)
    governance_root = Path(args.governance_root)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact),
                        ("source screen manifest", source_manifest)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}",
              file=sys.stderr)
        return 2
    try:
        result = run_lineage_screen_repair(
            repo_root=REPO_ROOT, packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            source_manifest_path=source_manifest,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir), run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc), dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid repair input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({
        "run_id": result.run_id, "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "counts": result.counts, "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (str(result.manifest_path) if result.manifest_path
                          else None),
        "failure_receipt_path": (str(result.failure_receipt_path)
                                 if result.failure_receipt_path else None),
        "receipt": result.receipt,
    }, indent=2))
    if result.status == "failed":
        print("ERROR: repair run stopped with a failure receipt; the run is "
              "non-authoritative.", file=sys.stderr)
        return 1
    return 0


def _main_screen_universe_lineage_diagnostic_repair(
        args: argparse.Namespace) -> int:
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    for label, path in (("packet manifest", packet_manifest),
                        ("repair selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}",
              file=sys.stderr)
        return 2
    try:
        result = run_lineage_screen_diagnostic_repair(
            repo_root=REPO_ROOT,
            packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            logical_request_cap=args.logical_request_cap,
            provider_attempt_cap=args.provider_attempt_cap,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid repair screen input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "validated": result.validated,
        "rejected": result.rejected,
        "rejections_by_reason": result.rejections_by_reason,
        "counts": result.counts,
        "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path else None
        ),
        "receipt": result.receipt,
    }
    print(json.dumps(payload, indent=2))
    if result.status == "failed":
        print("ERROR: repair run stopped with a failure receipt; the run "
              "directory is incomplete and non-authoritative.", file=sys.stderr)
        return 1
    # Rejected rows are the measurement, not a run failure.
    return 0


def _main_select_screen_repair_rows(args: argparse.Namespace) -> int:
    packet_manifest = Path(args.packet_manifest)
    source_manifest = Path(args.source_diagnostic_manifest)
    for label, path in (("packet manifest", packet_manifest),
                        ("source diagnostic manifest", source_manifest)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    try:
        result = build_repair_selection(
            repo_root=REPO_ROOT,
            source_diagnostic_manifest_path=source_manifest,
            packet_manifest_path=packet_manifest,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid repair selection input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "counts": result.counts,
        "selection_artifact": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_screen_universe_lineage_diagnostic(args: argparse.Namespace) -> int:
    packet_manifest = Path(args.packet_manifest)
    selection_artifact = Path(args.selection_artifact)
    governance_root = Path(args.governance_root)
    for label, path in (("packet manifest", packet_manifest),
                        ("selection artifact", selection_artifact)):
        if not path.is_file():
            print(f"ERROR: {label} not found: {path}", file=sys.stderr)
            return 2
    if not governance_root.is_dir():
        print(f"ERROR: governance root not found: {governance_root}",
              file=sys.stderr)
        return 2
    try:
        result = run_lineage_screen_diagnostic(
            repo_root=REPO_ROOT,
            packet_manifest_path=packet_manifest,
            selection_artifact_path=selection_artifact,
            governance_root=governance_root,
            authorization_reference=args.screen_authorization,
            authorization_sha256=args.screen_authorization_sha256,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            logical_request_cap=args.logical_request_cap,
            provider_attempt_cap=args.provider_attempt_cap,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid diagnostic screen input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "planned_screened": result.planned_screened,
        "validated": result.validated,
        "rejected": result.rejected,
        "rejections_by_reason": result.rejections_by_reason,
        "counts": result.counts,
        "request_accounting": result.request_accounting,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path else None
        ),
        "receipt": result.receipt,
    }
    print(json.dumps(payload, indent=2))
    if result.status == "failed":
        print("ERROR: diagnostic run stopped with a failure receipt; the run "
              "directory is incomplete and non-authoritative.", file=sys.stderr)
        return 1
    # Rejected rows are the measurement, not a run failure.
    return 0


def _main_select_screen_rows(args: argparse.Namespace) -> int:
    packet_manifest = Path(args.packet_manifest)
    if not packet_manifest.is_file():
        print(f"ERROR: packet manifest not found: {packet_manifest}",
              file=sys.stderr)
        return 2
    try:
        result = build_screen_selection(
            repo_root=REPO_ROOT,
            packet_manifest_path=packet_manifest,
            selection_kind=args.selection_kind,
            seed=args.selection_seed,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except ScreenInputError as exc:
        print(f"ERROR: invalid selection input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "status": result.status,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "counts": result.counts,
        "selection_artifact": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_build_baseline_packets(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle_dir)
    config_path = Path(args.config)
    if not bundle_dir.is_dir():
        print(f"ERROR: bundle directory not found: {bundle_dir}", file=sys.stderr)
        return 2
    if not config_path.is_file():
        print(f"ERROR: project config not found: {config_path}", file=sys.stderr)
        return 2
    try:
        result = run_baseline_packet_build(
            repo_root=REPO_ROOT,
            bundle_dir=bundle_dir,
            project_config_path=config_path,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            # The ingestion package never reads the clock; the entrypoint owns
            # identity and injects it.
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except PacketBundleError as exc:
        print(f"ERROR: invalid baseline packet input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "bundle_manifest_sha256": result.bundle_manifest_sha256,
        "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_probe_filing_index(args: argparse.Namespace) -> int:
    request_plan = Path(args.request_plan)
    if not request_plan.is_file():
        print(f"ERROR: probe plan not found: {request_plan}", file=sys.stderr)
        return 2
    # The ceiling is plan-owned, so the plan is read before the transport is
    # built; the runner then refuses any transport bound to a different value.
    try:
        _, plan_fields, _ = load_probe_plan(request_plan)
    except ProbePlanError as exc:
        print(f"ERROR: invalid filing index probe plan: {exc}", file=sys.stderr)
        return 2
    max_metadata_bytes = plan_fields["max_metadata_bytes"]
    transport_choice = args.transport or "fixture"
    if transport_choice == "sec-live":
        transport = make_sec_live_document_transport(max_bytes=max_metadata_bytes)
        transport_identity = SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY
    else:
        replay_dir = Path(args.replay_dir)
        if not replay_dir.is_dir():
            print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
            return 2
        transport = make_filing_index_fixture_replay_transport(
            replay_dir, max_bytes=max_metadata_bytes
        )
        transport_identity = None  # fixture-replay identity, v0.1 manifest
    try:
        result = run_filing_index_probe(
            repo_root=REPO_ROOT,
            plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            transport=transport,
            transport_max_bytes=max_metadata_bytes,
            dry_run=args.dry_run,
            transport_identity=transport_identity,
        )
    except ProbePlanError as exc:
        print(f"ERROR: invalid filing index probe input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "transport_kind": (
            transport_identity.kind if transport_identity else "fixture_replay"
        ),
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "plan_sha256": result.plan_sha256,
        "max_metadata_bytes": max_metadata_bytes,
        "planned_probes": len(result.entries),
        "probes_resolved": len(result.observations),
        "ground_truth_matches": sum(
            1 for o in result.observations if o.ground_truth_match
        ),
        "selected_documents": [o.selected_document for o in result.observations],
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
        "failure_reason_code": (
            result.failure.reason_code if result.failure else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path
            else None
        ),
    }
    print(json.dumps(payload, indent=2))
    if result.failure is not None:
        print(
            "ERROR: filing index probe failed; see the failure receipt. No "
            "probe manifest was written.",
            file=sys.stderr,
        )
        return 1
    return 0


def _main_acquire_docs(args: argparse.Namespace) -> int:
    request_plan = Path(args.request_plan)
    if not request_plan.is_file():
        print(f"ERROR: request plan not found: {request_plan}", file=sys.stderr)
        return 2
    # The ceiling is plan-owned, so the plan is read before the transport is
    # built; the runner then refuses any transport bound to a different value.
    try:
        _, plan_fields, _ = load_document_request_plan(request_plan)
    except DocumentPlanError as exc:
        print(f"ERROR: invalid baseline document request plan: {exc}", file=sys.stderr)
        return 2
    max_document_bytes = plan_fields["max_document_bytes"]
    transport_choice = args.transport or "fixture"
    if transport_choice == "sec-live":
        transport = make_sec_live_document_transport(
            max_bytes=max_document_bytes
        )
        transport_identity = SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY
    else:
        replay_dir = Path(args.replay_dir)
        if not replay_dir.is_dir():
            print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
            return 2
        transport = make_document_fixture_replay_transport(
            replay_dir, max_bytes=max_document_bytes
        )
        transport_identity = None  # fixture-replay identity, v0.1 manifest
    try:
        result = run_document_acquisition(
            repo_root=REPO_ROOT,
            request_plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            transport=transport,
            transport_max_bytes=max_document_bytes,
            dry_run=args.dry_run,
            transport_identity=transport_identity,
        )
    except DocumentPlanError as exc:
        print(f"ERROR: invalid baseline document request plan: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "transport_kind": (
            transport_identity.kind if transport_identity else "fixture_replay"
        ),
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "request_plan_sha256": result.request_plan_sha256,
        "planned_documents": len(result.entries),
        "documents_acquired": len(result.receipts),
        "mapped_carrier_rows": sum(
            len(entry.carrier_rows) for entry in result.entries
        ),
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
        "failure_reason_code": (
            result.failure.reason_code if result.failure else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path
            else None
        ),
    }
    print(json.dumps(payload, indent=2))
    if result.failure is not None:
        print(
            "ERROR: baseline document acquisition failed; see the failure "
            "receipt. No acquisition manifest was written.",
            file=sys.stderr,
        )
        return 1
    return 0


def _main_baseline_carrier(args: argparse.Namespace) -> int:
    frame_manifest = Path(args.frame_manifest)
    config_path = Path(args.config)
    if not frame_manifest.is_file():
        print(f"ERROR: frame manifest not found: {frame_manifest}", file=sys.stderr)
        return 2
    if not config_path.is_file():
        print(f"ERROR: project config not found: {config_path}", file=sys.stderr)
        return 2
    try:
        result = run_baseline_carrier(
            repo_root=REPO_ROOT,
            project_config_path=config_path,
            frame_manifest_path=frame_manifest,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            dry_run=args.dry_run,
        )
    except CarrierInputError as exc:
        print(f"ERROR: invalid baseline-carrier input: {exc}", file=sys.stderr)
        return 2
    except CarrierReconciliationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    error = _reject_cross_mode_flags(args)
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if args.mode == "frame":
        return _main_frame(args)
    if args.mode == "acquire-index":
        return _main_acquire(args)
    if args.mode == "acquire-dera":
        return _main_acquire_dera(args)
    if args.mode == "dera-validate":
        return _main_dera_validate(args)
    if args.mode == "baseline-carrier":
        return _main_baseline_carrier(args)
    if args.mode == "acquire-docs":
        return _main_acquire_docs(args)
    if args.mode == "build-baseline-packets":
        return _main_build_baseline_packets(args)
    if args.mode == "acquire-primary-docs":
        return _main_acquire_primary_docs(args)
    if args.mode == "determine-shell-company":
        return _main_determine_shell_company(args)
    if args.mode == "determine-shell-company-lineage":
        return _main_determine_shell_company_lineage(args)
    if args.mode == "determine-asset-backed-issuer-lineage":
        return _main_determine_asset_backed_issuer_lineage(args)
    if args.mode == "build-baseline-packets-lineage":
        return _main_build_baseline_packets_lineage(args)
    if args.mode == "build-baseline-packets-lineage-v2":
        return _main_build_baseline_packets_lineage_v2(args)
    if args.mode == "screen-universe-lineage":
        return _main_screen_universe_lineage(args)
    if args.mode == "screen-universe-lineage-live":
        return _main_screen_universe_lineage_live(args)
    if args.mode == "screen-universe-lineage-live-v2":
        return _main_screen_universe_lineage_live_v2(args)
    if args.mode == "screen-universe-lineage-live-v3":
        return _main_screen_universe_lineage_live_v3(args)
    if args.mode == "screen-universe-lineage-continuation":
        return _main_screen_universe_lineage_continuation(args)
    if args.mode == "screen-universe-lineage-continuation-v2":
        return _main_screen_universe_lineage_continuation_v2(args)
    if args.mode == "screen-universe-lineage-continuation-v3":
        return _main_screen_universe_lineage_continuation_v3(args)
    if args.mode == "screen-universe-lineage-continuation-v4":
        return _main_screen_universe_lineage_continuation_v4(args)
    if args.mode == "screen-universe-lineage-continuation-v5":
        return _main_screen_universe_lineage_continuation_v5(args)
    if args.mode == "screen-universe-lineage-diagnostic":
        return _main_screen_universe_lineage_diagnostic(args)
    if args.mode == "screen-universe-lineage-diagnostic-repair":
        return _main_screen_universe_lineage_diagnostic_repair(args)
    if args.mode == "build-human-review-overlay":
        return _main_build_human_review_overlay(args)
    if args.mode == "build-classifier-candidate-cohort":
        return _main_build_classifier_candidate_cohort(args)
    if args.mode == "build-annual-coverage-cohort":
        return _main_build_annual_coverage_cohort(args)
    if args.mode == "select-classifier-pilot-rows":
        return _main_select_classifier_pilot_rows(args)
    if args.mode == "select-classifier-pilot-rows-v2":
        return _main_select_classifier_pilot_rows_v2(args)
    if args.mode == "classify-software-universe-pilot-v1":
        return _main_classify_software_universe_pilot_v1(args)
    if args.mode == "classify-software-universe-pilot-v2":
        return _main_classify_software_universe_pilot_v2(args)
    if args.mode == "classify-software-universe-pilot-v3":
        return _main_classify_software_universe_pilot_v3(args)
    if args.mode == "classify-software-universe-pilot-v4":
        return _main_classify_software_universe_pilot_v4(args)
    if args.mode == "classify-software-universe-pilot-v5":
        return _main_classify_software_universe_pilot_v5(args)
    if args.mode == "classify-software-universe-pilot-v6":
        return _main_classify_software_universe_pilot_v6(args)
    if args.mode == "select-classifier-calibration-rows":
        return _main_select_classifier_calibration_rows(args)
    if args.mode == "classify-universe-calibration":
        return _main_classify_universe_calibration(args)
    if args.mode == "build-classifier-calibration-review-v2-2":
        return _main_build_classifier_calibration_review(
            args, calibration_route=CALIBRATION_ROUTE_V2_2)
    if args.mode == "build-classifier-calibration-review-v2-3":
        return _main_build_classifier_calibration_review(
            args, calibration_route=CALIBRATION_ROUTE_V2_3)
    if args.mode == "build-classifier-calibration-review-v2-4":
        return _main_build_classifier_calibration_review(
            args, calibration_route=CALIBRATION_ROUTE_V2_4)
    if args.mode == "build-classifier-calibration-review-v2-5":
        return _main_build_classifier_calibration_review(
            args, calibration_route=CALIBRATION_ROUTE_V2_5)
    if args.mode == "build-classifier-calibration-review-v2-9":
        return _main_build_classifier_calibration_review(
            args, calibration_route=CALIBRATION_ROUTE_V2_9)
    if args.mode == "build-classifier-calibration-review-v2-8":
        return _main_build_classifier_calibration_review(
            args, calibration_route=CALIBRATION_ROUTE_V2_8)
    if args.mode == "build-classifier-calibration-review-v2-7":
        return _main_build_classifier_calibration_review(
            args, calibration_route=CALIBRATION_ROUTE_V2_7)
    if args.mode == "build-classifier-calibration-review-v2-6":
        return _main_build_classifier_calibration_review(
            args, calibration_route=CALIBRATION_ROUTE_V2_6)
    if args.mode == "build-classifier-calibration-review":
        return _main_build_classifier_calibration_review(args)
    if args.mode == "classify-universe-cohort-v2-9":
        return _main_classify_universe_cohort(args, route=BASE_ROUTE_V2_9)
    if args.mode == "classify-universe-cohort-v2-8":
        return _main_classify_universe_cohort(args, route=BASE_ROUTE_V2_8)
    if args.mode == "classify-universe-cohort-v2-7":
        return _main_classify_universe_cohort(args, route=BASE_ROUTE_V2_7)
    if args.mode == "classify-universe-cohort-v2-6":
        return _main_classify_universe_cohort(args, route=BASE_ROUTE_V2_6)
    if args.mode == "classify-universe-cohort-continuation-v2-9":
        return _main_classify_universe_cohort_continuation(
            args, route=CONTINUATION_ROUTE_V2_9)
    if args.mode == "classify-universe-cohort-continuation-v2-8":
        return _main_classify_universe_cohort_continuation(
            args, route=CONTINUATION_ROUTE_V2_8)
    if args.mode == "classify-universe-cohort-continuation-v2-7":
        return _main_classify_universe_cohort_continuation(
            args, route=CONTINUATION_ROUTE_V2_7)
    if args.mode == "classify-universe-cohort-continuation-v2-6":
        return _main_classify_universe_cohort_continuation(
            args, route=CONTINUATION_ROUTE_V2_6)
    if args.mode == "classify-universe-calibration-v2-9":
        return _main_classify_universe_calibration(
            args, route=CALIBRATION_ROUTE_V2_9)
    if args.mode == "classify-universe-calibration-v2-8":
        return _main_classify_universe_calibration(
            args, route=CALIBRATION_ROUTE_V2_8)
    if args.mode == "classify-universe-calibration-v2-7":
        return _main_classify_universe_calibration(
            args, route=CALIBRATION_ROUTE_V2_7)
    if args.mode == "classify-universe-calibration-v2-6":
        return _main_classify_universe_calibration(
            args, route=CALIBRATION_ROUTE_V2_6)
    if args.mode == "classify-universe-cohort-v2-5":
        return _main_classify_universe_cohort(args, route=BASE_ROUTE_V2_5)
    if args.mode == "classify-universe-cohort-continuation-v2-5":
        return _main_classify_universe_cohort_continuation(
            args, route=CONTINUATION_ROUTE_V2_5)
    if args.mode == "classify-universe-calibration-v2-5":
        return _main_classify_universe_calibration(
            args, route=CALIBRATION_ROUTE_V2_5)
    if args.mode == "classify-universe-cohort-v2-4":
        return _main_classify_universe_cohort(args, route=BASE_ROUTE_V2_4)
    if args.mode == "classify-universe-cohort-continuation-v2-4":
        return _main_classify_universe_cohort_continuation(
            args, route=CONTINUATION_ROUTE_V2_4)
    if args.mode == "classify-universe-calibration-v2-4":
        return _main_classify_universe_calibration(
            args, route=CALIBRATION_ROUTE_V2_4)
    if args.mode == "classify-universe-cohort-v2-3":
        return _main_classify_universe_cohort(args, route=BASE_ROUTE_V2_3)
    if args.mode == "classify-universe-cohort-continuation-v2-3":
        return _main_classify_universe_cohort_continuation(
            args, route=CONTINUATION_ROUTE_V2_3)
    if args.mode == "classify-universe-calibration-v2-3":
        return _main_classify_universe_calibration(
            args, route=CALIBRATION_ROUTE_V2_3)
    if args.mode == "classify-universe-cohort-v2-2":
        return _main_classify_universe_cohort(args, route=BASE_ROUTE_V2_2)
    if args.mode == "classify-universe-cohort-continuation-v2-2":
        return _main_classify_universe_cohort_continuation(
            args, route=CONTINUATION_ROUTE_V2_2)
    if args.mode == "classify-universe-calibration-v2-2":
        return _main_classify_universe_calibration(
            args, route=CALIBRATION_ROUTE_V2_2)
    if args.mode == "classify-universe-cohort":
        return _main_classify_universe_cohort(args)
    if args.mode == "classify-universe-cohort-continuation":
        return _main_classify_universe_cohort_continuation(args)
    if args.mode == "build-screen-release":
        return _main_build_screen_release(args)
    if args.mode == "select-screen-unverified-repair-rows":
        return _main_select_screen_unverified_repair_rows(args)
    if args.mode == "screen-universe-unverified-repair":
        return _main_screen_universe_unverified_repair(args)
    if args.mode == "select-screen-repair-rows":
        return _main_select_screen_repair_rows(args)
    if args.mode == "select-screen-rows":
        return _main_select_screen_rows(args)
    if args.mode == "plan-acquisition-queue":
        return _main_plan_acquisition_queue(args)
    if args.mode == "execute-acquisition-queue":
        return _main_execute_acquisition_queue(args)
    if args.mode == "aggregate-acquisition-queue":
        return _main_aggregate_acquisition_queue(args)
    if args.mode == "aggregate-acquisition-lineage":
        return _main_aggregate_acquisition_lineage(args)
    if args.mode == "probe-filing-index":
        return _main_probe_filing_index(args)
    return _main_sentinel(args)


if __name__ == "__main__":
    raise SystemExit(main())
