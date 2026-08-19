"""Live successor of the lineage high-recall screen (ADR-109).

ADR-108's ``run_lineage_screen`` and its mock path are retained byte- and
behavior-identical; this module is the explicit successor that binds the
governed Vertex/Gemini stack to the same screen contract. Nothing here is
callable without a complete, hash-bound governance chain, and this increment
ships **offline only**: every test injects a fake client factory, no real SDK
client is ever built, no credential is resolved, and no network is reached.

**What a live authorization binds** (ADR-109, stated verbatim in the decision
log): the packet cohort (``packet_manifest_sha256``) + the selected rows or
full-cohort mode (``selection_artifact_sha256``, ``selection_kind``) + the
prompt bytes (``prompt_template_sha256``) + the provider client contract
(canonical digest) + the enablement (reference plus sha) + the endpoints
(allowlist equality across connector, authorization and enablement) + the
model route + the caps and budgets. A run under any different value is a
different authorization, refused before a run directory, an SDK import,
credential resolution, or any network send exists.

**Selection authority.** A live run screens exactly the rows of one named
``universe_screen_selection@0.1.0`` artifact: a ``canary_100`` selection
enumerates exactly one hundred ``(cik, accession, packet_sha256)`` rows drawn
under the packet-native seeded stratified sampler (representation ×
filing-date quartile × packet-byte-size quartile; no SIC and no external
carrier participates); a ``full_cohort`` selection enumerates nothing because
the packet manifest itself is the row authority. A canary run is structurally
non-promotable: :func:`require_promotable_screen_run` accepts only a
full-cohort v0.2 manifest.

**Retry ownership.** The connector's tenacity loop is the single retry owner
(1 + 2 retries per row, the committed E-P policy); this module never raises
the screen's transient error and never retries a row itself, so double retry
is structurally impossible. One logical request per selected packet; at most
3 generate attempts per row; 1 countTokens + ≤3 generate sends per row.

**Dual raw authority.** The screen raw archive keeps ADR-108's rule exactly:
it receives the final verbatim model output *text* before any parsing. The
wire *envelopes* — every countTokens and generateContent attempt body — are
persisted write-once under ``provider_captures/`` before the next send, and
the capture ledger is their complete file mapping: every referenced file is
re-hashed and an orphan walk runs before the manifest is written. Records +
archive are the row-level model-output authority; ledger + envelope files
are the attempt-level wire authority for external requests, tokens and cost.

**Cohort budget.** A narrow screen-specific wrapper —
:class:`ScreenCohortBudget` — owns cohort accounting (cumulative input
tokens, settled cost, external sends, wall clock) against the authorization's
budgets and mints the connector's one-shot admissions itself. Extraction's
per-record ``CanonicalBudgetSession`` is deliberately not the cohort
authority (ADR-109 resolution 1). Pricing is the committed exact-integer rule
in ``extraction.count_reconciliation``; no price appears in any schema or
authorization. Settlement is deterministic and conservative: a row whose
usage block verified on a single attempt settles at its measured usage cost;
any other row settles at the per-attempt ceiling times the attempts actually
made.

The 530 insufficient-evidence rows are never model-called in any mode: a
canary carries none of them, and a full-cohort run preserves them exactly as
ADR-108 does — null status, null date, no raw binding.
"""

from __future__ import annotations

import json
import os
import random
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.extraction.count_reconciliation import (
    parse_input_token_count,
    reconcile_count,
    reserve_cost_microdollars,
    usage_cost_microdollars,
)
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.provider_adapter import (
    PROVIDER_PROTOCOL_VERSION_V8,
    BudgetAdmission,
    CaptureRecord,
    CaptureSinkError,
    ProviderRequest,
    client_contract_digest,
    provider_request_digest,
)
from dynamic_ai_products.providers.client_contract_v2 import (
    CLIENT_CONTRACT_V2_ID,
    MODEL_PARAMETERS_V2,
    build_client_contract_v2,
    build_operation_endpoints,
)
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.retry_policy import (
    RATE_LIMIT_POLICY_VERSION,
    RETRY_MAX_ATTEMPTS,
    RETRY_POLICY_VERSION,
)
from dynamic_ai_products.providers.vertex_gemini_v2 import VertexGeminiProviderV2
from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    FAILURE_RECEIPT_FILENAME,
    FIRM_ROLLUP_RULE,
    PROMPT_TEMPLATE_RELATIVE_PATH,
    RAW_RESPONSES_FILENAME,
    RECORD_CONTRACT,
    RECORD_SCHEMA_RELATIVE_PATH,
    RECORDS_FILENAME,
    SCREEN_MANIFEST_FILENAME,
    SCREEN_RECORD_ORDER,
    SCREEN_STATUSES,
    ScreenInputError,
    ScreenProviderTerminalError,
    ScreenRunResult,
    _canonical_line,
    _decode_utf8,
    _load_schema,
    _RowValidationFailure,
    _RUN_ID_RE,
    _sha256,
    _validate,
    _validate_row_output,
    firm_rollup,
    load_packet_run,
    render_lineage_screen_prompt,
    require_authoritative_screen_run,
)

# --- Filenames, contracts and closed vocabularies -------------------------------

CAPTURES_DIRNAME = "provider_captures"
CAPTURE_LEDGER_FILENAME = "universe_screen_capture_ledger.jsonl"
SELECTION_FILENAME = "universe_screen_selection.json"

SELECTION_CONTRACT = "universe_screen_selection@0.1.0"
AUTHORIZATION_CONTRACT = "universe_screen_live_authorization@0.1.0"
ENABLEMENT_CONTRACT = "universe_screen_adapter_enablement@0.1.0"
SCREEN_MANIFEST_V2_CONTRACT = "universe_screen_manifest@0.2.0"
SCREEN_STAGE = "universe_high_recall_screen"

SELECTION_SCHEMA_RELATIVE_PATH = "schemas/universe_screen_selection.schema.json"
AUTHORIZATION_SCHEMA_RELATIVE_PATH = (
    "schemas/universe_screen_live_authorization.schema.json"
)
ENABLEMENT_SCHEMA_RELATIVE_PATH = (
    "schemas/universe_screen_adapter_enablement.schema.json"
)
MANIFEST_V2_SCHEMA_RELATIVE_PATH = "schemas/universe_screen_manifest.v2.schema.json"

#: The pinned deterministic envelope-to-text rule: exactly one candidate,
#: every part a string ``text`` field, concatenated in order. Anything else —
#: blocked, empty, malformed, multi-candidate, part-less — is terminal.
ENVELOPE_TEXT_EXTRACTION_RULE = "vertex_generate_content_candidates0_text_parts@1"

SAMPLING_ALGORITHM = "seeded_stratified_quartiles@1"
FULL_COHORT_ALGORITHM = "full_cohort@1"
CANARY_ROWS = 100

#: One logical request per row may spend at most this many generate attempts —
#: the committed E-P retry policy ceiling, restated relationally, never widened.
GENERATE_ATTEMPT_CAP_PER_ROW = RETRY_MAX_ATTEMPTS
#: Structural per-row external maximum: one count send plus the generate cap.
EXTERNAL_REQUESTS_PER_ROW = 1 + RETRY_MAX_ATTEMPTS

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


# --- Governance hydration --------------------------------------------------------


def _hydrate_pinned(
    governance_root: Path, reference: str, expected_sha256: str, what: str
) -> tuple[dict, bytes]:
    """Read one pinned governance artifact: containment, byte re-hash, UTF-8."""
    if not isinstance(reference, str) or not reference:
        raise ScreenInputError(f"The {what} reference must be a non-empty string.")
    if not isinstance(expected_sha256, str) or not _SHA256_RE.fullmatch(
        expected_sha256
    ):
        raise ScreenInputError(
            f"The {what} pin must carry a 64-hex sha256; refusing to read anything."
        )
    root = governance_root.resolve()
    target = (governance_root / reference).resolve()
    if root not in target.parents and target != root:
        raise ScreenInputError(
            f"The {what} reference escapes the governance root; refused."
        )
    if not target.is_file():
        raise ScreenInputError(f"The {what} was not found at {target}.")
    raw = target.read_bytes()
    observed = _sha256(raw)
    if observed != expected_sha256:
        raise ScreenInputError(
            f"The {what} hashes to {observed}, but its pin says "
            f"{expected_sha256}. The artifact on disk is not the artifact "
            "that was authorized; nothing runs."
        )
    try:
        payload = json.loads(_decode_utf8(raw, what))
    except json.JSONDecodeError as exc:
        raise ScreenInputError(f"The {what} is not valid JSON: {exc}.") from exc
    if not isinstance(payload, dict):
        raise ScreenInputError(f"The {what} must be a JSON object.")
    return payload, raw


def _parse_moment(value: str, what: str) -> datetime:
    try:
        return datetime.fromisoformat(value)
    except ValueError as exc:
        raise ScreenInputError(f"{what} is not an ISO timestamp: {value!r}.") from exc


# --- Selection: generation and loading --------------------------------------------


def _quartile(index: int, total: int) -> int:
    """Deterministic quartile of a zero-based rank: 0..3, no floats."""
    return min(3, index * 4 // total)


def _allocate_stratum_counts(sizes: dict[str, int], target: int) -> dict[str, int]:
    """Largest-remainder proportional allocation to exactly ``target`` rows.

    Pure and deterministic: quotas are exact integer arithmetic, remainders
    are ranked by fractional part with the stratum key as the tiebreak. A
    stratum can never be allocated more rows than it has, because a quota's
    ceiling only exceeds its floor when the quota is fractional, and a
    fractional quota is strictly below the stratum size.
    """
    total = sum(sizes.values())
    if target > total:
        raise ScreenInputError(
            f"Cannot select {target} rows from {total}; the cohort is smaller "
            "than the selection."
        )
    base: dict[str, int] = {}
    remainders: list[tuple[int, str]] = []
    allocated = 0
    for key in sorted(sizes):
        quota_times_total = sizes[key] * target
        floor = quota_times_total // total
        base[key] = floor
        allocated += floor
        remainders.append((quota_times_total - floor * total, key))
    remainders.sort(key=lambda item: (-item[0], item[1]))
    for _, key in remainders[: target - allocated]:
        base[key] += 1
    return base


def _stratum_key(packet: dict, date_rank: dict, size_rank: dict, total: int) -> str:
    row = (packet["cik"], packet["accession"])
    return (
        f"{packet['representation']}"
        f"|d{_quartile(date_rank[row], total)}"
        f"|s{_quartile(size_rank[row], total)}"
    )


def build_screen_selection(
    *,
    repo_root: str | Path,
    packet_manifest_path: str | Path,
    selection_kind: str,
    seed: int | None,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> ScreenRunResult:
    """Build one governed selection artifact. Deterministic; no model call."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    if selection_kind not in ("canary_100", "full_cohort"):
        raise ScreenInputError(
            f"Unknown selection kind {selection_kind!r}; the closed vocabulary "
            "is canary_100 | full_cohort."
        )
    if selection_kind == "canary_100" and not isinstance(seed, int):
        raise ScreenInputError("A canary selection requires an integer seed.")
    if selection_kind == "full_cohort" and seed is not None:
        raise ScreenInputError(
            "A full-cohort selection takes no seed: it samples nothing."
        )

    inputs = load_packet_run(root, packet_manifest_path)
    packets = inputs.packets

    rows: list[dict] = []
    strata: list[dict] = []
    if selection_kind == "canary_100":
        if len(packets) < CANARY_ROWS:
            raise ScreenInputError(
                f"The cohort holds {len(packets)} packets; a canary needs at "
                f"least {CANARY_ROWS}."
            )
        total = len(packets)
        by_date = sorted(
            packets, key=lambda p: (p["baseline_filing_date"], p["cik"], p["accession"])
        )
        by_size = sorted(
            packets, key=lambda p: (p["packet_byte_size"], p["cik"], p["accession"])
        )
        date_rank = {
            (p["cik"], p["accession"]): index for index, p in enumerate(by_date)
        }
        size_rank = {
            (p["cik"], p["accession"]): index for index, p in enumerate(by_size)
        }
        grouped: dict[str, list[dict]] = {}
        for packet in packets:
            key = _stratum_key(packet, date_rank, size_rank, total)
            grouped.setdefault(key, []).append(packet)
        allocation = _allocate_stratum_counts(
            {key: len(members) for key, members in grouped.items()}, CANARY_ROWS
        )
        for key in sorted(grouped):
            members = sorted(
                grouped[key], key=lambda p: (p["cik"], p["accession"])
            )
            take = allocation[key]
            rng = random.Random(f"{seed}:{key}")
            chosen = members if take == len(members) else rng.sample(members, take)
            rows.extend(
                {
                    "cik": p["cik"],
                    "accession": p["accession"],
                    "packet_sha256": p["packet_sha256"],
                }
                for p in chosen
            )
            strata.append({"key": key, "rows": len(members), "selected": take})
        rows.sort(key=lambda r: (r["cik"], r["accession"]))
    else:
        strata = []

    payload = {
        "selection_contract": SELECTION_CONTRACT,
        "selection_id": run_id,
        "selection_kind": selection_kind,
        "packet_manifest_path": str(packet_manifest_path),
        "packet_manifest_sha256": inputs.manifest_sha256,
        "sampling": {
            "algorithm": (
                SAMPLING_ALGORITHM
                if selection_kind == "canary_100"
                else FULL_COHORT_ALGORITHM
            ),
            "seed": seed,
            "strata": strata,
        },
        "rows": rows,
        "counts": {
            "packets_total": len(packets),
            "rows_selected": len(rows),
        },
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "Selection is deterministic and packet-native: representation, "
            "filing-date quartile and packet-byte-size quartile only. No SIC "
            "carrier and no external source authority participates "
            "(ADR-109 resolution 2).",
            "A full-cohort selection enumerates no rows: the packet manifest "
            "is the row authority, and an enumeration would be a second copy "
            "that could drift.",
        ],
    }
    _validate(
        payload,
        _load_schema(root, SELECTION_SCHEMA_RELATIVE_PATH),
        "Screen selection artifact",
    )

    result = ScreenRunResult(
        run_id=run_id, run_dir=None, dry_run=dry_run, status="dry_run",
        planned_screened=len(rows) if selection_kind == "canary_100" else len(packets),
        planned_insufficient=0,
        counts=dict(payload["counts"]),
    )
    if dry_run:
        return result
    run_dir = create_run_directory(output_dir, run_id)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        write_bytes_once(run_dir / SELECTION_FILENAME, raw,
                         what=f"screen selection {run_dir / SELECTION_FILENAME}")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    result.run_dir = run_dir
    result.dry_run = False
    result.status = "completed"
    result.manifest_path = run_dir / SELECTION_FILENAME
    return result


def load_screen_selection(
    repo_root: str | Path, selection_path: str | Path
) -> tuple[dict, str]:
    """Load and schema-validate one selection artifact; return it with its sha."""
    target = Path(selection_path)
    if not target.is_file():
        raise ScreenInputError(f"Selection artifact not found: {target}.")
    raw = target.read_bytes()
    try:
        payload = json.loads(_decode_utf8(raw, "Selection artifact"))
    except json.JSONDecodeError as exc:
        raise ScreenInputError(
            f"Selection artifact {target} is not valid JSON: {exc}."
        ) from exc
    _validate(
        payload,
        _load_schema(Path(repo_root), SELECTION_SCHEMA_RELATIVE_PATH),
        f"Selection artifact {target}",
    )
    return payload, _sha256(raw)


# --- Cohort budget: the narrow screen-specific wrapper ----------------------------


class ScreenCohortBudget:
    """Cohort accounting authority for one live screen run (ADR-109 res. 1).

    Owns the cumulative ceilings the authorization declares — input tokens,
    settled cost, external sends, wall clock — and mints the connector's
    one-shot :class:`BudgetAdmission` itself. Extraction's per-record session
    is deliberately not reused as this authority. Settlement is conservative
    and deterministic: usage cost when the usage block verified on a single
    attempt, else the per-attempt ceiling times the attempts actually made.
    """

    def __init__(
        self,
        *,
        authorization: dict,
        authorization_sha256: str,
        run_id: str,
        clock: Callable[[], datetime],
    ) -> None:
        self._max_input_tokens = authorization["budget_max_input_tokens"]
        self._max_output_tokens = authorization["budget_max_output_tokens"]
        self._max_cost_micros = authorization["budget_max_estimated_cost_micros"]
        self._max_wall_clock_seconds = authorization["budget_max_wall_clock_seconds"]
        self._max_external_requests = authorization["budget_max_external_requests"]
        self._clock = clock
        self._started_at = clock()
        self._session_nonce = _sha256(
            f"{authorization_sha256}:{run_id}:screen_cohort_budget@1".encode("utf-8")
        )
        self.tokens_in_measured = 0
        self.tokens_out_reported: int | None = 0
        self.rows_usage_verified = 0
        self.cost_micros_settled = 0
        self.external_requests_made = 0

    def _require_wall_clock(self) -> None:
        elapsed = (self._clock() - self._started_at).total_seconds()
        if elapsed > self._max_wall_clock_seconds:
            raise ScreenProviderTerminalError(
                f"The wall-clock budget of {self._max_wall_clock_seconds}s is "
                "exhausted; the run stops rather than running unbounded."
            )

    def admit(
        self, *, measured_input_tokens: int, request_digest: str
    ) -> BudgetAdmission:
        self._require_wall_clock()
        if self.tokens_in_measured + measured_input_tokens > self._max_input_tokens:
            raise ScreenProviderTerminalError(
                "The cohort input-token budget is exhausted; the run stops "
                "before the send it cannot pay for."
            )
        reserve = reserve_cost_microdollars(
            measured_input_tokens=measured_input_tokens,
            max_output_tokens=MODEL_PARAMETERS_V2["max_output_tokens"],
            generate_attempt_cap=GENERATE_ATTEMPT_CAP_PER_ROW,
        )
        if self.cost_micros_settled + reserve > self._max_cost_micros:
            raise ScreenProviderTerminalError(
                "The cohort cost budget cannot cover this row's reserve; the "
                "run stops before the send it cannot pay for."
            )
        return BudgetAdmission(
            measured_input_tokens=measured_input_tokens,
            reserved_cost_microdollars=reserve,
            generate_attempt_cap=GENERATE_ATTEMPT_CAP_PER_ROW,
            provider_request_digest=request_digest,
            session_nonce=self._session_nonce,
        )

    def settle(
        self,
        *,
        measured_input_tokens: int,
        attempts: int,
        usage_verified: bool,
        usage_output_tokens: int | None,
    ) -> None:
        self.tokens_in_measured += measured_input_tokens
        self.external_requests_made += 1 + attempts
        if usage_verified and attempts == 1 and usage_output_tokens is not None:
            self.rows_usage_verified += 1
            if self.tokens_out_reported is not None:
                self.tokens_out_reported += usage_output_tokens
            self.cost_micros_settled += usage_cost_microdollars(
                input_tokens=measured_input_tokens,
                output_tokens=usage_output_tokens,
            )
        else:
            self.tokens_out_reported = None
            self.cost_micros_settled += attempts * usage_cost_microdollars(
                input_tokens=measured_input_tokens,
                output_tokens=MODEL_PARAMETERS_V2["max_output_tokens"],
            )


# --- Envelope parsing: the pinned deterministic extraction ------------------------


def _extract_envelope_text(raw_bytes: bytes) -> tuple[str, dict]:
    """Extract the model text from one terminal generateContent envelope.

    ``vertex_generate_content_candidates0_text_parts@1``: exactly one
    candidate; parts a non-empty list; every part a string ``text``; parts
    concatenated in order. Blocked, empty, malformed, multi-candidate and
    part-less envelopes are terminal — the screen never repairs a response.
    Returns the text plus the usage facts settlement needs.
    """
    try:
        document = json.loads(raw_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScreenProviderTerminalError(
            f"The terminal envelope is not UTF-8 JSON: {exc}."
        ) from exc
    if not isinstance(document, dict):
        raise ScreenProviderTerminalError(
            "The terminal envelope is JSON but not an object."
        )
    feedback = document.get("promptFeedback")
    if isinstance(feedback, dict) and feedback.get("blockReason"):
        raise ScreenProviderTerminalError(
            f"The provider blocked the prompt: {feedback.get('blockReason')!r}."
        )
    candidates = document.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        raise ScreenProviderTerminalError(
            "The terminal envelope must carry exactly one candidate; "
            f"got {len(candidates) if isinstance(candidates, list) else 'none'}."
        )
    candidate = candidates[0]
    if not isinstance(candidate, dict):
        raise ScreenProviderTerminalError("The candidate is not an object.")
    finish = candidate.get("finishReason")
    if finish is not None and finish != "STOP":
        raise ScreenProviderTerminalError(
            f"The candidate finished abnormally: {finish!r}."
        )
    content = candidate.get("content")
    parts = content.get("parts") if isinstance(content, dict) else None
    if not isinstance(parts, list) or not parts:
        raise ScreenProviderTerminalError(
            "The candidate carries no content parts; nothing to extract."
        )
    pieces: list[str] = []
    for part in parts:
        if not isinstance(part, dict) or not isinstance(part.get("text"), str):
            raise ScreenProviderTerminalError(
                "A candidate part carries no string text; the extraction "
                "rule admits text parts only."
            )
        pieces.append(part["text"])
    text = "".join(pieces)
    if not text:
        raise ScreenProviderTerminalError("The extracted model text is empty.")
    return text, _usage_facts(document)


def _usage_facts(document: dict) -> dict:
    """Read the envelope's usage block. Facts only; never a refusal."""
    usage = document.get("usageMetadata")
    if not isinstance(usage, dict):
        return {"present": False, "prompt_tokens": None, "output_tokens": None,
                "thoughts_tokens": None}
    def _int_or_none(value: Any) -> int | None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        return value
    return {
        "present": True,
        "prompt_tokens": _int_or_none(usage.get("promptTokenCount")),
        "output_tokens": _int_or_none(usage.get("candidatesTokenCount")),
        "thoughts_tokens": _int_or_none(usage.get("thoughtsTokenCount")),
    }


def _usage_verified(usage: dict, measured_input_tokens: int) -> bool:
    """Verified iff the reported prompt count equals the admitted count and,
    under the zero thinking budget, the thoughts count is absent or zero."""
    return (
        usage["present"]
        and usage["prompt_tokens"] == measured_input_tokens
        and usage["output_tokens"] is not None
        and usage["thoughts_tokens"] in (None, 0)
    )


# --- The capture sink and the adapter ---------------------------------------------


class VertexLineageScreenProvider:
    """The governed live adapter behind the unchanged screen protocol.

    ``screen(rendered_prompt, *, cik, accession) -> str`` — per row it re-arms
    the connector's default-deny handshake, walks countTokens then
    generateContent under a one-shot cohort-budget admission, resolves the
    terminal capture by reference, re-hashes its bytes against both the
    capture record and the connector's response metadata, extracts the model
    text under the pinned rule, and returns that text verbatim. Every failure
    is terminal: this adapter never raises the screen's transient error, so
    the connector's tenacity loop stays the single retry owner.
    """

    def __init__(
        self,
        *,
        connector: VertexGeminiProviderV2,
        authorization_sha256: str,
        authorization_allowlist: tuple[str, ...],
        enablement_allowlist: tuple[str, ...],
        run_dir: Path,
        budget: ScreenCohortBudget,
        packet_sha_by_key: dict[tuple[str, str], str],
        prompt_template_sha256: str,
        ledger: list[dict],
    ) -> None:
        self._connector = connector
        self._authorization_sha256 = authorization_sha256
        self._authorization_allowlist = tuple(authorization_allowlist)
        self._enablement_allowlist = tuple(enablement_allowlist)
        self._run_dir = run_dir
        self._budget = budget
        self._packet_sha_by_key = dict(packet_sha_by_key)
        self._prompt_template_sha256 = prompt_template_sha256
        self._ledger = ledger
        self._contract = connector.client_contract()
        self._contract_digest = client_contract_digest(self._contract)
        self._row_ordinal = 0
        self.name = "vertex_gemini_v2"
        self.model_route = {
            "provider": self._contract["model_provider"],
            "model_label": self._contract["model_name"],
        }
        self.row_reports: list[dict] = []

    def _sink_for_row(self, row_prefix: str) -> Any:
        run_dir = self._run_dir
        ledger = self._ledger
        row_ordinal = self._row_ordinal

        def sink(
            *,
            operation_label: str,
            attempt_ordinal: int,
            raw_bytes: bytes | None,
            send_outcome: str,
            sdk_call_outcome: str,
            provider_reason_code: str | None,
        ) -> CaptureRecord:
            entry: dict[str, Any] = {
                "row_ordinal": row_ordinal,
                "operation_label": operation_label,
                "attempt_ordinal": attempt_ordinal,
                "send_outcome": send_outcome,
                "sdk_call_outcome": sdk_call_outcome,
                "provider_reason_code": provider_reason_code,
                "persistence_reason_code": None,
                "raw_reference": None,
                "raw_sha256": None,
                "byte_count": None,
            }
            if raw_bytes is None:
                entry["capture_disposition"] = "no_body_captured"
                ledger.append(entry)
                return CaptureRecord(
                    operation_label=operation_label,
                    attempt_ordinal=attempt_ordinal,
                    send_outcome=send_outcome,
                    sdk_call_outcome=sdk_call_outcome,
                    capture_disposition="no_body_captured",
                    provider_reason_code=provider_reason_code,
                )
            if not raw_bytes:
                entry["capture_disposition"] = "empty_entity_body_not_persisted"
                ledger.append(entry)
                return CaptureRecord(
                    operation_label=operation_label,
                    attempt_ordinal=attempt_ordinal,
                    send_outcome=send_outcome,
                    sdk_call_outcome=sdk_call_outcome,
                    capture_disposition="empty_entity_body_not_persisted",
                    provider_reason_code=provider_reason_code,
                )
            reference = (
                f"{CAPTURES_DIRNAME}/{row_prefix}/"
                f"{'count' if operation_label == 'count_tokens' else 'generate'}"
                f"-attempt-{attempt_ordinal:02d}.bin"
            )
            target = run_dir / reference
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                digest = write_bytes_once(
                    target, bytes(raw_bytes), what=f"capture {target}"
                )
            except WriteOnceError as exc:
                reason = (
                    "destination_exists"
                    if exc.category == "destination_exists"
                    else "write_error"
                )
                entry["capture_disposition"] = "body_captured_persistence_failed"
                entry["persistence_reason_code"] = reason
                ledger.append(entry)
                raise CaptureSinkError(
                    operation_label=operation_label,
                    attempt_ordinal=attempt_ordinal,
                    persistence_reason_code=reason,
                    provider_reason_code=provider_reason_code,
                ) from None
            entry["capture_disposition"] = "raw_persisted"
            entry["raw_reference"] = reference
            entry["raw_sha256"] = digest
            entry["byte_count"] = len(raw_bytes)
            ledger.append(entry)
            return CaptureRecord(
                operation_label=operation_label,
                attempt_ordinal=attempt_ordinal,
                send_outcome=send_outcome,
                sdk_call_outcome=sdk_call_outcome,
                capture_disposition="raw_persisted",
                raw_reference=reference,
                raw_sha256=digest,
                byte_count=len(raw_bytes),
                provider_reason_code=provider_reason_code,
            )

        return sink

    def _verified_capture_bytes(self, record: CaptureRecord, what: str) -> bytes:
        if record.capture_disposition != "raw_persisted" or not record.raw_reference:
            raise ScreenProviderTerminalError(f"The {what} was not persisted.")
        raw = (self._run_dir / record.raw_reference).read_bytes()
        if _sha256(raw) != record.raw_sha256:
            raise ScreenProviderTerminalError(
                f"The persisted {what} no longer matches its digest."
            )
        return raw

    def screen(self, rendered_prompt: str, *, cik: str, accession: str) -> str:
        self._row_ordinal += 1
        key = (cik, accession)
        packet_sha = self._packet_sha_by_key.get(key)
        if packet_sha is None:
            raise ScreenProviderTerminalError(
                f"No selected packet is known for cik={cik} "
                f"accession={accession}; the adapter screens selected rows only."
            )
        row_prefix = f"{self._row_ordinal:05d}-{cik}-{accession}"
        sink = self._sink_for_row(row_prefix)
        try:
            # Re-armed per row: the v8 permit model grants one count and one
            # generate permit per handshake. Stated openly in ADR-109 as the
            # one semantic extension of the reused stack.
            self._connector.assert_run_permitted(
                authorization_sha256=self._authorization_sha256,
                endpoint_allowlist=self._authorization_allowlist,
                enablement_endpoint_allowlist=self._enablement_allowlist,
            )
            request = ProviderRequest(
                stage=SCREEN_STAGE,
                rendered_contents=rendered_prompt,
                rendered_contents_sha256=_sha256(rendered_prompt.encode("utf-8")),
                prompt_sha256=self._prompt_template_sha256,
                input_packet_sha256=packet_sha,
            )
            count_record, witness = self._connector.count_tokens(request, sink=sink)
            count_raw = self._verified_capture_bytes(count_record, "count response")
            measured = reconcile_count(
                parsed=parse_input_token_count(count_raw), sdk_witness=witness
            )
            admission = self._budget.admit(
                measured_input_tokens=measured,
                request_digest=provider_request_digest(
                    request,
                    provider_client_contract_sha256=self._contract_digest,
                    protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
                ),
            )
            response, records = self._connector.complete_v8(
                request, admission=admission, sink=sink
            )
            attempts = len(records)
            terminal = records[-1]
            raw = self._verified_capture_bytes(terminal, "terminal envelope")
            metadata_sha = response.prompt_model_metadata.get("raw_prediction_sha256")
            if metadata_sha != terminal.raw_sha256:
                raise ScreenProviderTerminalError(
                    "The connector's response metadata and the terminal "
                    "capture disagree about the envelope digest."
                )
            text, usage = _extract_envelope_text(raw)
            self._budget.settle(
                measured_input_tokens=measured,
                attempts=attempts,
                usage_verified=_usage_verified(usage, measured),
                usage_output_tokens=usage["output_tokens"],
            )
            self.row_reports.append({
                "row_ordinal": self._row_ordinal,
                "cik": cik,
                "accession": accession,
                "attempts": attempts,
                "measured_input_tokens": measured,
                "usage_verified": _usage_verified(usage, measured),
                "usage_output_tokens": usage["output_tokens"],
                "terminal_raw_reference": terminal.raw_reference,
                "terminal_raw_sha256": terminal.raw_sha256,
            })
            return text
        except ScreenProviderTerminalError:
            raise
        except ProviderError as exc:
            raise ScreenProviderTerminalError(
                f"Governed provider failure ({exc.reason_code})."
            ) from exc
        except CaptureSinkError as exc:
            raise ScreenProviderTerminalError(
                "A captured response body could not be persisted "
                f"({exc.persistence_reason_code}); a persistence failure "
                "permits no further send."
            ) from exc
        except ExtractionError as exc:
            raise ScreenProviderTerminalError(
                f"Count reconciliation failed ({exc.reason_code})."
            ) from exc
        finally:
            self._connector.revoke_run_permission()


# --- Promotion gate ----------------------------------------------------------------


def require_promotable_screen_run(run_dir: str | Path) -> Path:
    """Refuse any screen run a SCREEN release may not be built from.

    Promotion requires an authoritative run whose manifest is the live v0.2
    generation with a full-cohort selection: a mock v0.1 run has no governed
    provider and a canary run screened a sample, so neither may become
    SCREEN_v1.
    """
    manifest_path = require_authoritative_screen_run(run_dir)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    selection = manifest.get("selection")
    if not isinstance(selection, dict):
        raise ScreenInputError(
            f"Screen run {run_dir} carries no selection block; only a live "
            "full-cohort run is promotable."
        )
    if selection.get("selection_kind") != "full_cohort":
        raise ScreenInputError(
            f"Screen run {run_dir} was screened under selection kind "
            f"{selection.get('selection_kind')!r}; a canary is a measurement "
            "run and is structurally non-promotable."
        )
    # The ledger is the complete capture-file mapping: every referenced file
    # must still re-hash to its line, and no unlisted file may exist.
    directory = Path(run_dir)
    ledger_lines = [
        json.loads(line)
        for line in (directory / CAPTURE_LEDGER_FILENAME)
        .read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    persisted = {
        entry["raw_reference"]: entry["raw_sha256"]
        for entry in ledger_lines
        if entry["capture_disposition"] == "raw_persisted"
    }
    for reference, recorded in persisted.items():
        target = directory / reference
        if not target.is_file() or _sha256(target.read_bytes()) != recorded:
            raise ScreenInputError(
                f"Capture file {reference} is missing or no longer hashes to "
                "its ledger line; the run is not consumable."
            )
    on_disk = {
        str(path.relative_to(directory))
        for path in (directory / CAPTURES_DIRNAME).rglob("*")
        if path.is_file()
    }
    if on_disk != set(persisted):
        raise ScreenInputError(
            "The capture directory and the ledger disagree about which "
            "files exist; the run is not consumable."
        )
    return manifest_path


# --- The live successor runner ------------------------------------------------------


@dataclass
class _Preflight:
    authorization: dict
    enablement: dict
    contract: dict
    contract_digest: str
    endpoints: dict
    prompt_template_text: str
    prompt_template_sha256: str
    inputs: Any
    selection: dict
    selection_sha256: str
    selected_packets: list[dict]
    include_insufficient: bool


def _preflight(
    *,
    root: Path,
    packet_manifest_path: str | Path,
    selection_artifact_path: str | Path,
    governance_root: Path,
    authorization_reference: str,
    authorization_sha256: str,
    logical_request_cap: int,
    provider_attempt_cap: int,
    clock: Callable[[], datetime],
) -> _Preflight:
    """The exact ADR-109 validation order, all before any output or SDK."""
    # (2) The authorization, by pin.
    authorization, _ = _hydrate_pinned(
        governance_root, authorization_reference, authorization_sha256,
        "screen live authorization",
    )
    _validate(
        authorization,
        _load_schema(root, AUTHORIZATION_SCHEMA_RELATIVE_PATH),
        "Screen live authorization",
    )
    # (3) The enablement, via the authorization's own pin; temporal windows.
    enablement, _ = _hydrate_pinned(
        governance_root,
        authorization["screen_adapter_enablement_reference"],
        authorization["screen_adapter_enablement_sha256"],
        "screen adapter enablement",
    )
    _validate(
        enablement,
        _load_schema(root, ENABLEMENT_SCHEMA_RELATIVE_PATH),
        "Screen adapter enablement",
    )
    now = clock()
    for what, artifact in (("authorization", authorization),
                           ("enablement", enablement)):
        effective = _parse_moment(artifact["effective_at"], f"{what} effective_at")
        expires = _parse_moment(artifact["expires_at"], f"{what} expires_at")
        if not (effective <= now < expires):
            raise ScreenInputError(
                f"The {what} window [{artifact['effective_at']} .. "
                f"{artifact['expires_at']}) does not cover {now.isoformat()}; "
                "nothing runs under an expired or not-yet-effective grant."
            )
    # (4) The client contract, recomputed from code for the authorized project.
    contract = build_client_contract_v2(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"],
    )
    contract_digest = client_contract_digest(contract)
    for what, artifact in (("authorization", authorization),
                           ("enablement", enablement)):
        if artifact["provider_client_contract_sha256"] != contract_digest:
            raise ScreenInputError(
                f"The {what} pins client-contract digest "
                f"{artifact['provider_client_contract_sha256']}, but the "
                f"connector's own declared contract digests to "
                f"{contract_digest}; the {what} was minted for a different "
                "contract."
            )
        if artifact["provider_client_contract_reference"] != CLIENT_CONTRACT_V2_ID:
            raise ScreenInputError(
                f"The {what} names client contract "
                f"{artifact['provider_client_contract_reference']!r}; this "
                f"connector speaks {CLIENT_CONTRACT_V2_ID!r}."
            )
    expected_route = {
        "provider": contract["model_provider"],
        "model_label": contract["model_name"],
    }
    if authorization["model_route"] != expected_route:
        raise ScreenInputError(
            f"The authorization's model route {authorization['model_route']} "
            f"is not the connector's route {expected_route}."
        )
    if authorization["retry_policy_version"] != RETRY_POLICY_VERSION or (
        authorization["rate_limit_policy_version"] != RATE_LIMIT_POLICY_VERSION
    ):
        raise ScreenInputError(
            "The authorization names retry/rate-limit policy versions other "
            "than the committed ones; it was minted for a different policy."
        )
    # (5) Endpoint equality across authorization, enablement and derivation.
    endpoints = build_operation_endpoints(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"],
    )
    expected_endpoints = set(endpoints.values())
    for what, artifact in (("authorization", authorization),
                           ("enablement", enablement)):
        if set(artifact["endpoint_allowlist"]) != expected_endpoints:
            raise ScreenInputError(
                f"The {what} endpoint allowlist is not exactly the two "
                "operation endpoints derived from the client contract."
            )
    # (6) The prompt binding: committed bytes against the authorization.
    template_path = root / PROMPT_TEMPLATE_RELATIVE_PATH
    if not template_path.is_file():
        raise ScreenInputError(f"Screen prompt template not found: {template_path}")
    template_raw = template_path.read_bytes()
    template_sha = _sha256(template_raw)
    if template_sha != authorization["prompt_template_sha256"]:
        raise ScreenInputError(
            f"The committed screen prompt template hashes to {template_sha}, "
            f"but the authorization binds "
            f"{authorization['prompt_template_sha256']}. A stale or "
            "mismatched prompt authorization runs nothing."
        )
    # (7) The cohort, the selection, and the stated caps.
    inputs = load_packet_run(root, packet_manifest_path)
    if inputs.manifest_sha256 != authorization["packet_manifest_sha256"]:
        raise ScreenInputError(
            f"The packet manifest hashes to {inputs.manifest_sha256}, but the "
            f"authorization binds {authorization['packet_manifest_sha256']}; "
            "this is not the cohort that was authorized."
        )
    selection, selection_sha = load_screen_selection(root, selection_artifact_path)
    if selection_sha != authorization["selection_artifact_sha256"]:
        raise ScreenInputError(
            "The selection artifact is not the one the authorization binds."
        )
    if selection["selection_kind"] != authorization["selection_kind"]:
        raise ScreenInputError(
            "The selection artifact and the authorization disagree about the "
            "selection kind."
        )
    if selection["packet_manifest_sha256"] != inputs.manifest_sha256:
        raise ScreenInputError(
            "The selection artifact binds a different packet manifest than "
            "the one loaded; nothing is screened."
        )
    packets_by_key = {
        (p["cik"], p["accession"]): p for p in inputs.packets
    }
    if selection["selection_kind"] == "canary_100":
        seen: set[tuple[str, str]] = set()
        for row in selection["rows"]:
            key = (row["cik"], row["accession"])
            if key in seen:
                raise ScreenInputError(
                    f"The selection lists cik={key[0]} accession={key[1]} "
                    "twice; a row is selected at most once."
                )
            seen.add(key)
            packet = packets_by_key.get(key)
            if packet is None:
                raise ScreenInputError(
                    f"The selection names cik={key[0]} accession={key[1]}, "
                    "which is not a valid packet row of this cohort."
                )
            if packet["packet_sha256"] != row["packet_sha256"]:
                raise ScreenInputError(
                    f"The selection pins packet sha {row['packet_sha256']} "
                    f"for cik={key[0]}, but the cohort's packet hashes to "
                    f"{packet['packet_sha256']}; refusing a drifted row."
                )
        selected = [p for p in inputs.packets
                    if (p["cik"], p["accession"]) in seen]
        include_insufficient = False
    else:
        selected = list(inputs.packets)
        include_insufficient = True
    if logical_request_cap != len(selected):
        raise ScreenInputError(
            f"logical_request_cap is {logical_request_cap}, but the selection "
            f"covers exactly {len(selected)} valid packet rows. One logical "
            "request per selected packet; state the scale you authorize."
        )
    if authorization["logical_request_cap"] != logical_request_cap:
        raise ScreenInputError(
            "The operator-stated logical cap and the authorization disagree."
        )
    expected_attempt_cap = logical_request_cap * GENERATE_ATTEMPT_CAP_PER_ROW
    if provider_attempt_cap != expected_attempt_cap or (
        authorization["provider_attempt_cap"] != expected_attempt_cap
    ):
        raise ScreenInputError(
            f"provider_attempt_cap must be exactly {expected_attempt_cap} "
            f"(logical x {GENERATE_ATTEMPT_CAP_PER_ROW} generate attempts)."
        )
    expected_external = logical_request_cap * EXTERNAL_REQUESTS_PER_ROW
    if authorization["budget_max_external_requests"] != expected_external:
        raise ScreenInputError(
            f"budget_max_external_requests must be exactly {expected_external} "
            f"(logical x {EXTERNAL_REQUESTS_PER_ROW}: one count send plus the "
            "generate ceiling per row)."
        )
    return _Preflight(
        authorization=authorization,
        enablement=enablement,
        contract=contract,
        contract_digest=contract_digest,
        endpoints=endpoints,
        prompt_template_text=_decode_utf8(template_raw, "Screen prompt template"),
        prompt_template_sha256=template_sha,
        inputs=inputs,
        selection=selection,
        selection_sha256=selection_sha,
        selected_packets=selected,
        include_insufficient=include_insufficient,
    )


def run_lineage_screen_live(
    *,
    repo_root: str | Path,
    packet_manifest_path: str | Path,
    selection_artifact_path: str | Path,
    governance_root: str | Path,
    authorization_reference: str,
    authorization_sha256: str,
    output_dir: str | Path,
    run_id: str,
    logical_request_cap: int,
    provider_attempt_cap: int,
    clock: Callable[[], datetime],
    dry_run: bool = False,
    client_factory: Any = None,
) -> ScreenRunResult:
    """Screen the selected rows of one authorized cohort. Fail closed.

    ``client_factory`` exists so the authorized path is testable offline; in
    this increment every caller injects a fake and no real SDK client, ADC
    resolution, or socket ever exists. The default (``None``) defers to the
    connector's lazy real factory, reachable only after the handshake, and is
    exercised only by a separately authorized live run.
    """
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    pre = _preflight(
        root=root,
        packet_manifest_path=packet_manifest_path,
        selection_artifact_path=selection_artifact_path,
        governance_root=Path(governance_root),
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256,
        logical_request_cap=logical_request_cap,
        provider_attempt_cap=provider_attempt_cap,
        clock=clock,
    )
    planned_insufficient = (
        len(pre.inputs.failures) if pre.include_insufficient else 0
    )
    record_schema = _load_schema(root, RECORD_SCHEMA_RELATIVE_PATH)
    manifest_schema = _load_schema(root, MANIFEST_V2_SCHEMA_RELATIVE_PATH)

    if dry_run:
        for packet in pre.selected_packets:
            render_lineage_screen_prompt(pre.prompt_template_text, packet)
        return ScreenRunResult(
            run_id=run_id, run_dir=None, dry_run=True, status="dry_run",
            planned_screened=len(pre.selected_packets),
            planned_insufficient=planned_insufficient,
            request_accounting={
                "logical_request_cap": logical_request_cap,
                "provider_attempt_cap": provider_attempt_cap,
                "external_request_cap":
                    pre.authorization["budget_max_external_requests"],
            },
        )

    # (8) Connector construction is pure; the handshake smoke proves the
    # three-list equality once, before any output exists, and is revoked.
    connector = VertexGeminiProviderV2(
        vertex_project=pre.authorization["vertex_project"],
        vertex_location=pre.authorization["vertex_location"],
        expected_authorization_sha256=authorization_sha256,
        max_provider_requests=GENERATE_ATTEMPT_CAP_PER_ROW,
        endpoint_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
        client_factory=client_factory,
    )
    try:
        connector.assert_run_permitted(
            authorization_sha256=authorization_sha256,
            endpoint_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
            enablement_endpoint_allowlist=tuple(
                pre.enablement["endpoint_allowlist"]
            ),
        )
    except ProviderError as exc:
        raise ScreenInputError(
            f"The connector refused the handshake ({exc.reason_code}); "
            "nothing runs and nothing exists."
        ) from exc
    finally:
        connector.revoke_run_permission()

    # (9) Only now may an output directory exist.
    run_dir = create_run_directory(output_dir, run_id)
    result = ScreenRunResult(
        run_id=run_id, run_dir=run_dir, dry_run=False, status="failed",
        planned_screened=len(pre.selected_packets),
        planned_insufficient=planned_insufficient,
    )
    budget = ScreenCohortBudget(
        authorization=pre.authorization,
        authorization_sha256=authorization_sha256,
        run_id=run_id,
        clock=clock,
    )
    ledger: list[dict] = []
    adapter = VertexLineageScreenProvider(
        connector=connector,
        authorization_sha256=authorization_sha256,
        authorization_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
        enablement_allowlist=tuple(pre.enablement["endpoint_allowlist"]),
        run_dir=run_dir,
        budget=budget,
        packet_sha_by_key={
            (p["cik"], p["accession"]): p["packet_sha256"]
            for p in pre.selected_packets
        },
        prompt_template_sha256=pre.prompt_template_sha256,
        ledger=ledger,
    )

    archive_path = run_dir / RAW_RESPONSES_FILENAME
    descriptor = os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    archive = os.fdopen(descriptor, "wb")

    logical_requests_made = 0
    provider_attempts_made = 0
    rows_retried = 0
    raw_responses_captured = 0
    records: list[dict] = []

    def _fail(reason_code: str, detail: str, packet: dict) -> ScreenRunResult:
        archive.flush()
        os.fsync(archive.fileno())
        archive.close()
        count_captures = sum(
            1 for entry in ledger if entry["operation_label"] == "count_tokens"
        )
        generate_captures = len(ledger) - count_captures
        receipt = {
            "receipt_contract": "universe_screen_failure_receipt@0.1.0",
            "run_id": run_id,
            "reason_code": reason_code,
            "detail": detail,
            "stopping_cik": packet["cik"],
            "stopping_accession": packet["accession"],
            "stopping_row_index": len(records) + 1,
            "records_completed_before_failure": len(records),
            "raw_responses_captured": raw_responses_captured,
            "capture_files_written": sum(
                1 for entry in ledger
                if entry["capture_disposition"] == "raw_persisted"
            ),
            "count_captures": count_captures,
            "generate_captures": generate_captures,
            "external_requests_made": len(ledger),
            "logical_request_cap": logical_request_cap,
            "provider_attempt_cap": provider_attempt_cap,
            "logical_requests_attempted": logical_requests_made,
            # Ledger-derived, so the stopping row's real send attempts are
            # counted even though no row report exists for it.
            "provider_attempts_made": generate_captures,
            "authorization_sha256": authorization_sha256,
            "run_timestamp": clock().isoformat(),
            "retention_note": (
                "Non-authoritative failed live run: no records JSONL, no "
                "capture ledger and no manifest exist here — only the raw "
                "responses and wire captures taken before the stop. This "
                "directory is immutable and may not be consumed by a SCREEN "
                "release or a classifier loader; a retry requires a new run "
                "id and new authorization."
            ),
        }
        payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        try:
            write_bytes_once(
                run_dir / FAILURE_RECEIPT_FILENAME, payload,
                what=f"failure receipt {run_dir / FAILURE_RECEIPT_FILENAME}",
            )
        except WriteOnceError as exc:
            raise ScreenInputError(str(exc)) from exc
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        result.receipt = receipt
        return result

    for packet in pre.selected_packets:
        rendered = render_lineage_screen_prompt(pre.prompt_template_text, packet)
        prompt_sha256 = _sha256(rendered.encode("utf-8"))
        logical_requests_made += 1
        try:
            raw_response = adapter.screen(
                rendered, cik=packet["cik"], accession=packet["accession"]
            )
        except ScreenProviderTerminalError as exc:
            return _fail("provider_error", str(exc), packet)
        report = adapter.row_reports[-1]
        provider_attempts_made += report["attempts"]
        if report["attempts"] > 1:
            rows_retried += 1
        if provider_attempts_made > provider_attempt_cap:
            return _fail(
                "provider_error",
                f"Provider attempt cap {provider_attempt_cap} exceeded; the "
                "run stops rather than exceeding its authorized scale.",
                packet,
            )

        raw_bytes = raw_response.encode("utf-8")
        raw_sha256 = _sha256(raw_bytes)
        raw_response_id = f"{run_id}-{packet['cik']}-{packet['accession']}"
        archive_entry = {
            "raw_response_id": raw_response_id,
            "cik": packet["cik"],
            "accession": packet["accession"],
            "raw_response": raw_response,
            "raw_response_sha256": raw_sha256,
        }
        archive.write((_canonical_line(archive_entry) + "\n").encode("utf-8"))
        archive.flush()
        os.fsync(archive.fileno())
        raw_responses_captured += 1

        try:
            output = _validate_row_output(raw_response, packet)
        except _RowValidationFailure as exc:
            return _fail(exc.reason_code, exc.detail, packet)

        records.append({
            "record_contract": RECORD_CONTRACT,
            "record_kind": "screened_packet",
            "cik": packet["cik"],
            "company_id": packet["company_id"],
            "accession": packet["accession"],
            "form": packet["form"],
            "baseline_filing_date": packet["baseline_filing_date"],
            "source_id": packet["source_id"],
            "packet_sha256": packet["packet_sha256"],
            "screen_status": output.screen_status,
            "prompt_sha256": prompt_sha256,
            "model_route": dict(adapter.model_route),
            "raw_response_id": raw_response_id,
            "raw_response_sha256": raw_sha256,
            "screen_output": output.model_dump(mode="json"),
            "failure_reason_code": None,
            "failure_detail": None,
        })

    archive.flush()
    os.fsync(archive.fileno())
    archive.close()

    if pre.include_insufficient:
        for failure in pre.inputs.failures:
            records.append({
                "record_contract": RECORD_CONTRACT,
                "record_kind": "insufficient_evidence",
                "cik": failure["cik"],
                "company_id": failure["company_id"],
                "accession": failure["accession"],
                "form": failure["form"],
                "baseline_filing_date": None,
                "source_id": failure["source_id"],
                "packet_sha256": None,
                "screen_status": None,
                "prompt_sha256": None,
                "model_route": None,
                "raw_response_id": None,
                "raw_response_sha256": None,
                "screen_output": None,
                "failure_reason_code": failure["reason_code"],
                "failure_detail": failure["detail"],
            })

    record_validator = Draft202012Validator(
        record_schema, format_checker=FormatChecker()
    )
    for record in records:
        errors = sorted(record_validator.iter_errors(record),
                        key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Built screen record for cik={record['cik']} violates "
                f"{RECORD_CONTRACT} at {errors[0].json_path}: "
                f"{errors[0].message}"
            )

    # Verification: everything re-derived from the bytes on disk.
    archive_raw = archive_path.read_bytes()
    archive_entries = [
        json.loads(line)
        for line in _decode_utf8(archive_raw, RAW_RESPONSES_FILENAME).splitlines()
        if line.strip()
    ]
    entries_by_id = {entry["raw_response_id"]: entry for entry in archive_entries}
    screened = [r for r in records if r["record_kind"] == "screened_packet"]
    insufficient = [r for r in records
                    if r["record_kind"] == "insufficient_evidence"]
    raw_bindings_hold = len(entries_by_id) == len(archive_entries) and all(
        (entry := entries_by_id.get(record["raw_response_id"])) is not None
        and _sha256(entry["raw_response"].encode("utf-8"))
        == entry["raw_response_sha256"] == record["raw_response_sha256"]
        for record in screened
    )

    # Every capture file re-hashes to its ledger line, and no orphan exists.
    persisted_refs = {
        entry["raw_reference"] for entry in ledger
        if entry["capture_disposition"] == "raw_persisted"
    }
    capture_files_verified = all(
        (run_dir / entry["raw_reference"]).is_file()
        and _sha256((run_dir / entry["raw_reference"]).read_bytes())
        == entry["raw_sha256"]
        for entry in ledger
        if entry["capture_disposition"] == "raw_persisted"
    )
    on_disk = {
        str(path.relative_to(run_dir))
        for path in (run_dir / CAPTURES_DIRNAME).rglob("*")
        if path.is_file()
    }
    no_orphan_captures = on_disk == persisted_refs

    # Every archived response equals the text extracted from its row's
    # terminal, hash-verified envelope.
    archive_matches_envelopes = True
    for report in adapter.row_reports:
        envelope_raw = (run_dir / report["terminal_raw_reference"]).read_bytes()
        if _sha256(envelope_raw) != report["terminal_raw_sha256"]:
            archive_matches_envelopes = False
            break
        text, _ = _extract_envelope_text(envelope_raw)
        entry = entries_by_id.get(
            f"{run_id}-{report['cik']}-{report['accession']}"
        )
        if entry is None or entry["raw_response"] != text:
            archive_matches_envelopes = False
            break

    count_captures = sum(
        1 for entry in ledger if entry["operation_label"] == "count_tokens"
    )
    generate_captures = len(ledger) - count_captures

    status_counts = {status: 0 for status in SCREEN_STATUSES}
    for record in screened:
        status_counts[record["screen_status"]] += 1
    rollup_states = firm_rollup(records)
    rollup_counts = {
        state: sum(1 for value in rollup_states.values() if value == state)
        for state in SCREEN_STATUSES + ("INSUFFICIENT_EVIDENCE",)
    }
    insufficient_firm_ciks = {
        cik for cik, state in rollup_states.items()
        if state == "INSUFFICIENT_EVIDENCE"
    }

    counts = {
        "planned_rows": len(pre.selected_packets) + planned_insufficient,
        "screened_packets": len(screened),
        "insufficient_evidence": len(insufficient),
        "by_screen_status": status_counts,
        "firms_total": len(rollup_states),
        "firm_rollup": rollup_counts,
    }
    request_accounting = {
        "logical_request_cap": logical_request_cap,
        "provider_attempt_cap": provider_attempt_cap,
        "external_request_cap":
            pre.authorization["budget_max_external_requests"],
        "generate_attempt_cap_per_row": GENERATE_ATTEMPT_CAP_PER_ROW,
        "logical_requests_made": logical_requests_made,
        "provider_attempts_made": provider_attempts_made,
        "external_requests_made": len(ledger),
        "count_captures": count_captures,
        "generate_captures": generate_captures,
        "rows_retried": rows_retried,
        "tokens_in_measured": budget.tokens_in_measured,
        "tokens_out_reported": budget.tokens_out_reported,
        "rows_usage_verified": budget.rows_usage_verified,
        "cost_micros_settled": budget.cost_micros_settled,
        "budget_max_input_tokens":
            pre.authorization["budget_max_input_tokens"],
        "budget_max_output_tokens":
            pre.authorization["budget_max_output_tokens"],
        "budget_max_estimated_cost_micros":
            pre.authorization["budget_max_estimated_cost_micros"],
        "budget_max_wall_clock_seconds":
            pre.authorization["budget_max_wall_clock_seconds"],
    }

    reconciliation = {
        "records partition the retained rows": (
            len(records) == len(screened) + len(insufficient)
            == counts["planned_rows"]
        ),
        "every selected packet row was screened exactly once": (
            len(screened) == len(pre.selected_packets) == logical_requests_made
        ),
        "selection covers exactly the screened rows": (
            {(r["cik"], r["accession"]) for r in screened}
            == {(p["cik"], p["accession"]) for p in pre.selected_packets}
        ),
        "every packet failure row is preserved as insufficient evidence": (
            len(insufficient) == planned_insufficient
        ),
        "every raw response resolves by id and re-hashes": raw_bindings_hold,
        "the archive holds one line per logical request": (
            len(archive_entries) == logical_requests_made
        ),
        "logical requests equal the declared cap": (
            logical_requests_made == logical_request_cap
        ),
        "generate captures equal provider attempts": (
            generate_captures == provider_attempts_made
            == sum(report["attempts"] for report in adapter.row_reports)
        ),
        "count and generate captures partition external requests": (
            count_captures + generate_captures == len(ledger)
            == budget.external_requests_made
        ),
        "external requests stay within the authorized cap": (
            len(ledger) <= pre.authorization["budget_max_external_requests"]
        ),
        "provider attempts never exceeded the declared cap": (
            provider_attempts_made <= provider_attempt_cap
        ),
        "every row made exactly one count send": (
            count_captures == logical_requests_made
        ),
        "every capture file re-hashes to its ledger line": (
            capture_files_verified
        ),
        "no orphan capture file exists": no_orphan_captures,
        "every archived response equals its terminal envelope text": (
            archive_matches_envelopes
        ),
        "the prompt template hash equals the authorization's": (
            pre.prompt_template_sha256
            == pre.authorization["prompt_template_sha256"]
        ),
        "every screen status is in the closed three-value vocabulary": all(
            record["screen_status"] in SCREEN_STATUSES for record in screened
        ),
        "record status always equals the validated output status": all(
            record["screen_status"] == record["screen_output"]["screen_status"]
            for record in screened
        ),
        "insufficient rows carry null status and null date and no model call": all(
            record["screen_status"] is None
            and record["baseline_filing_date"] is None
            and record["raw_response_id"] is None
            for record in insufficient
        ),
        "a canary run carries no insufficient rows": (
            pre.include_insufficient or len(insufficient) == 0
        ),
        "shared accessions stay separate rows per cik": (
            len({(record["cik"], record["accession"]) for record in records})
            == len(records)
        ),
        "insufficient-evidence firms have no screened packet": not (
            insufficient_firm_ciks & {record["cik"] for record in screened}
        ),
        "firm rollup covers every cik exactly once": (
            sum(rollup_counts.values()) == len(rollup_states)
            and {record["cik"] for record in records} == set(rollup_states)
        ),
    }
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            "Live screen reconciliation failed; no records JSONL, no capture "
            f"ledger and no manifest are written. Failed identities: {failed}."
        )

    records_payload = (
        "\n".join(_canonical_line(record) for record in records) + "\n"
    ).encode("utf-8")
    ledger_payload = (
        "\n".join(_canonical_line(entry) for entry in ledger) + "\n"
    ).encode("utf-8")
    try:
        write_bytes_once(run_dir / RECORDS_FILENAME, records_payload,
                         what=f"screen records {run_dir / RECORDS_FILENAME}")
        write_bytes_once(
            run_dir / CAPTURE_LEDGER_FILENAME, ledger_payload,
            what=f"capture ledger {run_dir / CAPTURE_LEDGER_FILENAME}",
        )
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    manifest = {
        "run_id": run_id,
        "packet_manifest_path": str(packet_manifest_path),
        "packet_manifest_sha256": pre.inputs.manifest_sha256,
        "packet_run_id": pre.inputs.manifest["run_id"],
        "packets_jsonl_sha256": pre.inputs.packets_jsonl_sha256,
        "packet_failures_jsonl_sha256": pre.inputs.failures_jsonl_sha256,
        "prompt_template_path": PROMPT_TEMPLATE_RELATIVE_PATH,
        "prompt_template_sha256": pre.prompt_template_sha256,
        "authorization_id": pre.authorization["authorization_id"],
        "authorization_sha256": authorization_sha256,
        "screen_adapter_enablement_sha256":
            pre.authorization["screen_adapter_enablement_sha256"],
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": pre.contract_digest,
        "envelope_text_extraction_rule": ENVELOPE_TEXT_EXTRACTION_RULE,
        "selection": {
            "selection_artifact_path": str(selection_artifact_path),
            "selection_artifact_sha256": pre.selection_sha256,
            "selection_kind": pre.selection["selection_kind"],
            "sampling_algorithm": pre.selection["sampling"]["algorithm"],
            "seed": pre.selection["sampling"]["seed"],
            "rows_selected": len(pre.selected_packets),
        },
        "provider": {
            "name": adapter.name,
            "model_route": dict(adapter.model_route),
        },
        "screen_record_order": SCREEN_RECORD_ORDER,
        "firm_rollup_rule": FIRM_ROLLUP_RULE,
        "baseline_cutoff": pre.inputs.baseline_cutoff,
        "counts": counts,
        "request_accounting": request_accounting,
        "reconciliation": reconciliation,
        "output_hashes": {
            RECORDS_FILENAME: _sha256(records_payload),
            RAW_RESPONSES_FILENAME: _sha256(archive_raw),
            CAPTURE_LEDGER_FILENAME: _sha256(ledger_payload),
        },
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "universe_screen_record": "0.1.0",
            "universe_screen_manifest_v2": "0.2.0",
            "universe_screen_selection": "0.1.0",
            "universe_screen_live_authorization": "0.1.0",
            "universe_screen_adapter_enablement": "0.1.0",
            "baseline_packet_manifest_v5": "0.5.0",
            "universe_baseline_packet_v2": "0.2.0",
        },
        "limitations": [
            "A screen status is a recall decision only: it is never final "
            "sample membership and never establishes software eligibility.",
            "A canary_100 run is a measurement run: it screens the selected "
            "hundred packets only, carries no insufficient-evidence rows, "
            "and is structurally non-promotable to a SCREEN release.",
            "The model saw CIK, accession, form, filing date, cutoff and "
            "Item 1 passages only — no company name, ticker, exchange or "
            "SIC code; selection strata are packet-native only.",
            "Records plus the raw archive are the row-level model-output "
            "authority; the capture ledger plus envelope files are the "
            "attempt-level wire authority for external requests, tokens "
            "and cost.",
            "Every binding is relational between the supplied inputs; no "
            "production hash is pinned in code or schema.",
        ],
    }
    _validate(manifest, manifest_schema, "Live screen run manifest")
    manifest_payload = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        write_bytes_once(run_dir / SCREEN_MANIFEST_FILENAME, manifest_payload,
                         what=f"screen manifest {run_dir / SCREEN_MANIFEST_FILENAME}")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    result.status = "completed"
    result.counts = counts
    result.reconciliation = reconciliation
    result.request_accounting = request_accounting
    result.manifest_path = run_dir / SCREEN_MANIFEST_FILENAME
    return result
