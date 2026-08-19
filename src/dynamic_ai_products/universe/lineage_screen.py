"""Production high-recall screen over one lineage-bound v0.5 packet cohort.

ADR-108. This module is the production successor to the fixture sentinel's
screen stage: it consumes exactly one named ``baseline_packet_manifest@0.5.0``
run — never a directory scan, never a glob — and emits governed
``universe_screen_record@0.1.0`` rows at raw ``(cik, accession)`` grain
under a ``universe_screen_manifest@0.1.0`` run manifest.

**Authority.** The packet manifest is the sole input authority. Before any
output directory exists or any provider is called, its bytes are re-hashed,
both of its JSONLs are re-hashed against its own ``output_hashes`` entries
and UTF-8-guarded, every packet record is re-validated against
``universe_baseline_packet@0.2.0``, and the retained-row partition
(packets plus failures equals retained rows) is re-proven. Every binding is
relational between the supplied inputs; no production hash is pinned here.

**The two record kinds.** A valid packet row is screened by the model and
becomes a ``screened_packet`` record carrying the packet's own filing date,
one of the three closed statuses, the packet/prompt hashes, the model route
and the raw-response binding. A packet-build failure row is preserved as an
``insufficient_evidence`` record with ``screen_status`` null and
``baseline_filing_date`` null — the failures JSONL is its only authority and
it measurably carries no filing date, so none is derived from a carrier or
any other source. ``INSUFFICIENT_EVIDENCE`` is never a fourth model status:
it exists only at firm roll-up. Insufficient-evidence rows are never
model-called and never enter a later classifier call list.

**Evidence-minimal rendering.** The model sees CIK, accession, form, filing
date, the packet cutoff and the verbatim Item 1 passages with their
source/passage identifiers — never a company name, ticker, exchange, SIC
code or anything dated after the cutoff.

**Raw-response archive.** Every received raw response is appended to
``universe_screen_raw_responses.jsonl`` — verbatim, hashed over its exact
original bytes — *before* any parsing or validation, so a mid-run failure
retains every captured response. The run manifest's ``output_hashes`` covers
the archive and the records JSONL both, and each screened record binds its
own archive entry by id and SHA-256.

**Fail-closed.** On the first terminal provider error, invalid model JSON,
adapter rejection, quote-resolution failure, temporal violation or attempt-
cap breach, the run stops: no records JSONL and no manifest are written; the
directory retains the captured raw archive plus a governed failure receipt.
A run is authoritative iff its manifest exists and binds — a receipt-bearing
or manifest-less directory is refused by :func:`require_authoritative_screen_run`.
Run directories are write-once in success and failure alike; a retry needs a
new run id and new authorization.

Phase 0 of this stage ships only the deterministic mock provider below. No
model API, no network access and no credential exist in this module; the
live provider binding is a separate, separately-authorized increment that
reuses the governed ``providers`` stack.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Callable, Protocol

from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

from .freeze import create_run_directory
from .models import HighRecallScreenOutput

# --- Filenames and closed vocabularies -----------------------------------------

RECORDS_FILENAME = "universe_screen_records.jsonl"
RAW_RESPONSES_FILENAME = "universe_screen_raw_responses.jsonl"
SCREEN_MANIFEST_FILENAME = "universe_screen_manifest.json"
FAILURE_RECEIPT_FILENAME = "universe_screen_failure_receipt.json"

#: Local mirrors of the packet-run filenames. The one-way dependency rule
#: (universe never imports ingestion) forbids importing the originals from
#: ``ingestion.baseline_packet``; the test suite asserts equality between the
#: two constant sets, so a rename on either side is loud, never silent.
PACKET_MANIFEST_FILENAME = "baseline_packet_manifest.json"
PACKETS_FILENAME = "universe_baseline_packets.jsonl"
PACKET_FAILURES_FILENAME = "baseline_packet_failures.jsonl"

RECORD_CONTRACT = "universe_screen_record@0.1.0"
SCREEN_MANIFEST_CONTRACT = "universe_screen_manifest@0.1.0"
PACKET_MANIFEST_CONTRACT = "baseline_packet_manifest@0.5.0"
PACKET_RECORD_CONTRACT = "universe_baseline_packet@0.2.0"

SCREEN_STATUSES = (
    "LIKELY_ELIGIBLE",
    "LIKELY_INELIGIBLE",
    "BOUNDARY_OR_UNCERTAIN",
)

#: Firm roll-up rule identity. Any eligible or boundary packet prevents
#: firm-negative treatment; a CIK with no valid packet is INSUFFICIENT_EVIDENCE
#: at roll-up only — non-negative, visible, and never classifier-called.
FIRM_ROLLUP_RULE = "eligible_over_boundary_over_ineligible_failsafe@1"

SCREEN_RECORD_ORDER = (
    "packet_rows_in_packet_file_order_then_failure_rows_in_failure_file_order"
)

#: Closed receipt vocabulary. A receipt names why the run stopped; there is
#: deliberately no sixth value, and a reconciliation failure is an internal
#: invariant breach that raises instead of writing a receipt.
RECEIPT_REASON_CODES = (
    "provider_error",
    "invalid_model_json",
    "adapter_rejection",
    "quote_resolution_failure",
    "temporal_violation",
)

#: Bounded transient retry policy: at most this many retries per row, on
#: transient provider failures only. A retry never creates another logical
#: record; only the final received response enters the archive.
MAX_TRANSIENT_RETRIES = 2

PROMPT_TEMPLATE_RELATIVE_PATH = "prompts/discovery/universe_high_recall_screen.md"
RECORD_SCHEMA_RELATIVE_PATH = "schemas/universe_screen_record.schema.json"
MANIFEST_SCHEMA_RELATIVE_PATH = "schemas/universe_screen_manifest.schema.json"
PACKET_MANIFEST_SCHEMA_RELATIVE_PATH = "schemas/baseline_packet_manifest.v5.schema.json"
PACKET_RECORD_SCHEMA_RELATIVE_PATH = "schemas/universe_baseline_packet.v2.schema.json"

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: The failure JSONL's closed key set, exactly as the v0.5 builder writes it.
#: It measurably carries no ``baseline_filing_date``; that absence is why the
#: insufficient_evidence record kind pins the field to null.
PACKET_FAILURE_KEYS = frozenset(
    ("accession", "cik", "company_id", "detail", "form", "reason_code",
     "source_id")
)


class ScreenInputError(RuntimeError):
    """A screen input, binding, cap or invariant failed. Nothing is built."""


class ScreenProviderTransientError(RuntimeError):
    """A retryable provider failure. Consumed by the bounded retry loop."""


class ScreenProviderTerminalError(RuntimeError):
    """A non-retryable provider failure. The run stops with a receipt."""


class _AttemptCapBreach(RuntimeError):
    """Charging one more provider attempt would exceed the declared cap."""


class LineageScreenProvider(Protocol):
    name: str
    model_route: dict

    def screen(self, rendered_prompt: str, *, cik: str, accession: str) -> str: ...


class MockLineageScreenProvider:
    """Replays precomputed raw response strings keyed by ``cik:accession``.

    Each fixture entry is a dict with a verbatim ``raw`` string and,
    optionally, ``transient_failures`` (an int consumed before the raw is
    served) or ``terminal`` (a message; the row fails terminally). The mock
    is the only provider of this increment: it makes no network request and
    reads no credential.
    """

    name = "mock"
    model_route = {"provider": "mock", "model_label": "fixture-replay"}

    def __init__(self, outputs: dict):
        if not isinstance(outputs, dict):
            raise ScreenInputError(
                "Mock screen fixture must be a JSON object keyed by "
                "'cik:accession'."
            )
        self._outputs = {str(key): dict(value) for key, value in outputs.items()}
        self._transient_served: dict[str, int] = {}
        self.calls = 0

    def screen(self, rendered_prompt: str, *, cik: str, accession: str) -> str:
        self.calls += 1
        key = f"{cik}:{accession}"
        entry = self._outputs.get(key)
        if entry is None:
            raise ScreenProviderTerminalError(
                f"Mock screen fixture has no output for {key}."
            )
        pending = int(entry.get("transient_failures", 0))
        served = self._transient_served.get(key, 0)
        if served < pending:
            self._transient_served[key] = served + 1
            raise ScreenProviderTransientError(
                f"Scripted transient failure {served + 1}/{pending} for {key}."
            )
        if "terminal" in entry:
            raise ScreenProviderTerminalError(str(entry["terminal"]))
        raw = entry.get("raw")
        if not isinstance(raw, str):
            raise ScreenProviderTerminalError(
                f"Mock screen fixture entry for {key} has no 'raw' string."
            )
        return raw


# --- Input loading: the packet run is the sole authority ------------------------


@dataclass
class PacketRunInputs:
    manifest: dict
    manifest_sha256: str
    packets: list[dict]
    failures: list[dict]
    packets_jsonl_sha256: str
    failures_jsonl_sha256: str
    baseline_cutoff: str


def _sha256(payload: bytes) -> str:
    from hashlib import sha256

    return sha256(payload).hexdigest()


def _load_schema(repo_root: Path, relative_path: str) -> dict:
    path = repo_root / relative_path
    if not path.is_file():
        raise ScreenInputError(f"Committed schema not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def _decode_utf8(raw: bytes, what: str) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ScreenInputError(
            f"{what} is not strict UTF-8: {exc}. A repaired hash cannot admit "
            "undecodable bytes; nothing is built."
        ) from exc


def _validate(instance: dict, schema: dict, what: str) -> None:
    errors = sorted(
        Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(
            instance
        ),
        key=lambda e: e.json_path,
    )
    if errors:
        first = errors[0]
        raise ScreenInputError(
            f"{what} violates its contract at {first.json_path}: "
            f"{first.message}"
        )


def load_packet_run(
    repo_root: str | Path, packet_manifest_path: str | Path
) -> PacketRunInputs:
    """Load and verify exactly one named v0.5 packet run. Fail closed."""
    root = Path(repo_root)
    manifest_path = Path(packet_manifest_path)
    if not manifest_path.is_file():
        raise ScreenInputError(f"Packet manifest not found: {manifest_path}")

    manifest_raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(_decode_utf8(manifest_raw, "Packet manifest"))
    except json.JSONDecodeError as exc:
        raise ScreenInputError(
            f"Packet manifest {manifest_path} is not valid JSON: {exc}."
        ) from exc
    _validate(
        manifest,
        _load_schema(root, PACKET_MANIFEST_SCHEMA_RELATIVE_PATH),
        f"Packet manifest {manifest_path}",
    )

    run_dir = manifest_path.parent
    recorded = manifest["output_hashes"]
    payloads: dict[str, bytes] = {}
    for filename in (PACKETS_FILENAME, PACKET_FAILURES_FILENAME):
        if filename not in recorded:
            raise ScreenInputError(
                f"Packet manifest records no output hash for {filename}; the "
                "run it describes is not consumable."
            )
        target = run_dir / filename
        if not target.is_file():
            raise ScreenInputError(
                f"Packet run output {filename} is missing beside its "
                f"manifest in {run_dir}."
            )
        raw = target.read_bytes()
        observed = _sha256(raw)
        if observed != recorded[filename]:
            raise ScreenInputError(
                f"{filename} hashes to {observed}, but the packet manifest "
                f"records {recorded[filename]}. The rows on disk are not the "
                "rows that manifest describes; nothing is screened."
            )
        payloads[filename] = raw

    packet_schema = _load_schema(root, PACKET_RECORD_SCHEMA_RELATIVE_PATH)
    packet_validator = Draft202012Validator(
        packet_schema, format_checker=FormatChecker()
    )
    packets: list[dict] = []
    text = _decode_utf8(payloads[PACKETS_FILENAME], f"{PACKETS_FILENAME}")
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ScreenInputError(
                f"{PACKETS_FILENAME} line {line_number} is not valid JSON: "
                f"{exc}."
            ) from exc
        errors = sorted(packet_validator.iter_errors(record),
                        key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Packet record on line {line_number} violates "
                f"{PACKET_RECORD_CONTRACT} at {errors[0].json_path}: "
                f"{errors[0].message}"
            )
        packets.append(record)

    failures: list[dict] = []
    text = _decode_utf8(
        payloads[PACKET_FAILURES_FILENAME], f"{PACKET_FAILURES_FILENAME}"
    )
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ScreenInputError(
                f"{PACKET_FAILURES_FILENAME} line {line_number} is not valid "
                f"JSON: {exc}."
            ) from exc
        if not isinstance(record, dict) or set(record) != PACKET_FAILURE_KEYS:
            raise ScreenInputError(
                f"Packet failure record on line {line_number} does not carry "
                f"exactly the governed key set {sorted(PACKET_FAILURE_KEYS)}."
            )
        if not all(isinstance(record[key], str) and record[key]
                   for key in PACKET_FAILURE_KEYS):
            raise ScreenInputError(
                f"Packet failure record on line {line_number} carries an "
                "empty or non-string field."
            )
        failures.append(record)

    counts = manifest["counts"]
    if len(packets) != counts["packets_built"]:
        raise ScreenInputError(
            f"Packet JSONL holds {len(packets)} records, but the manifest "
            f"counts {counts['packets_built']} packets built."
        )
    if len(failures) != counts["packet_failures"]:
        raise ScreenInputError(
            f"Failures JSONL holds {len(failures)} records, but the manifest "
            f"counts {counts['packet_failures']} packet failures."
        )
    if len(packets) + len(failures) != counts["retained_rows"]:
        raise ScreenInputError(
            "Packets and failures do not partition the retained rows: "
            f"{len(packets)} + {len(failures)} != {counts['retained_rows']}."
        )

    seen_packets: set[tuple[str, str]] = set()
    for record in packets:
        key = (record["cik"], record["accession"])
        if key in seen_packets:
            raise ScreenInputError(
                f"Duplicate packet row for cik={key[0]} accession={key[1]}."
            )
        seen_packets.add(key)
        if record["baseline_cutoff"] != manifest["baseline_cutoff"]:
            raise ScreenInputError(
                f"Packet row cik={key[0]} carries cutoff "
                f"{record['baseline_cutoff']}, but the run manifest declares "
                f"{manifest['baseline_cutoff']}."
            )
    seen_failures: set[tuple[str, str]] = set()
    for record in failures:
        key = (record["cik"], record["accession"])
        if key in seen_failures:
            raise ScreenInputError(
                f"Duplicate failure row for cik={key[0]} accession={key[1]}."
            )
        seen_failures.add(key)
    overlap = seen_packets & seen_failures
    if overlap:
        raise ScreenInputError(
            f"Rows appear as both packet and failure: {sorted(overlap)[:3]}."
        )

    return PacketRunInputs(
        manifest=manifest,
        manifest_sha256=_sha256(manifest_raw),
        packets=packets,
        failures=failures,
        packets_jsonl_sha256=recorded[PACKETS_FILENAME],
        failures_jsonl_sha256=recorded[PACKET_FAILURES_FILENAME],
        baseline_cutoff=manifest["baseline_cutoff"],
    )


# --- Evidence-minimal prompt rendering -------------------------------------------


def render_lineage_screen_prompt(template_text: str, packet: dict) -> str:
    """Fill the canonical screen template with baseline-bounded evidence only.

    The metadata block deliberately carries no company name, ticker,
    exchange or SIC code: identity beyond CIK/accession is withheld from the
    model so the decision rests on the filing's own words. Deterministic
    stratification by SIC, if any, happens outside the model entirely.
    """
    metadata = (
        f"cik: {packet['cik']}\n"
        f"accession: {packet['accession']}\n"
        f"form: {packet['form']}\n"
        f"filing_date: {packet['baseline_filing_date']}"
    )
    passages = "\n\n".join(
        f"[source_id={p['source_id']} passage_id={p['passage_id']} "
        f"section={p['section']}]\n{p['text']}"
        for p in packet["passages"]
    )
    rendered = template_text
    replacements = {
        "{{baseline_cutoff}}": packet["baseline_cutoff"],
        "{{company_metadata}}": metadata,
        "{{passages_with_source_and_passage_ids}}": passages,
    }
    for placeholder, value in replacements.items():
        if placeholder not in rendered:
            raise ScreenInputError(
                f"Screen prompt template is missing placeholder {placeholder}."
            )
        rendered = rendered.replace(placeholder, value)
    return rendered


# --- Output validation: adapter, quotes, temporal --------------------------------


class _RowValidationFailure(Exception):
    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def _validate_row_output(raw_response: str, packet: dict) -> HighRecallScreenOutput:
    """Parse and validate one archived raw response against its packet.

    Raises :class:`_RowValidationFailure` with the receipt reason code. The
    raw response is already archived when this runs; the counters in the
    receipt reflect that ordering.
    """
    try:
        parsed = json.loads(raw_response)
    except json.JSONDecodeError as exc:
        raise _RowValidationFailure(
            "invalid_model_json", f"Model output is not valid JSON: {exc}."
        ) from exc
    if not isinstance(parsed, dict):
        raise _RowValidationFailure(
            "invalid_model_json",
            f"Model output is JSON but not an object: {type(parsed).__name__}.",
        )

    # Defense in depth: the packet contract already forbids post-cutoff
    # filing dates, but a violation here must stop the run, never pass into
    # a record. Checked after archiving, per the pinned counter semantics.
    filing = date.fromisoformat(packet["baseline_filing_date"])
    cutoff = date.fromisoformat(packet["baseline_cutoff"])
    if filing > cutoff:
        raise _RowValidationFailure(
            "temporal_violation",
            f"Packet filing date {filing} is after cutoff {cutoff}; no "
            "screen observation may rest on it.",
        )

    for identity in ("cik", "company_id"):
        expected = packet[identity]
        if identity in parsed and parsed[identity] != expected:
            raise _RowValidationFailure(
                "adapter_rejection",
                f"Model output claims {identity}={parsed[identity]!r}, but "
                f"the screened packet is {identity}={expected!r}.",
            )
    payload = {"cik": packet["cik"], "company_id": packet["company_id"], **parsed}
    try:
        output = HighRecallScreenOutput.model_validate(payload)
    except ValidationError as exc:
        raise _RowValidationFailure(
            "adapter_rejection", f"Model output violates the screen contract: {exc}"
        ) from exc

    passages_by_id = {p["passage_id"]: p for p in packet["passages"]}
    for item in output.positive_evidence + output.negative_or_boundary_evidence:
        if item.source_id != packet["source_id"]:
            raise _RowValidationFailure(
                "quote_resolution_failure",
                f"Evidence cites source_id {item.source_id!r}, which is not "
                "the screened packet's source.",
            )
        passage = passages_by_id.get(item.passage_id)
        if passage is None:
            raise _RowValidationFailure(
                "quote_resolution_failure",
                f"Evidence cites passage_id {item.passage_id!r}, which the "
                "screened packet does not contain.",
            )
        if item.quote not in passage["text"]:
            raise _RowValidationFailure(
                "quote_resolution_failure",
                f"Evidence quote does not resolve verbatim inside passage "
                f"{item.passage_id!r}.",
            )
    return output


# --- Firm roll-up ----------------------------------------------------------------


def firm_rollup(records: list[dict]) -> dict[str, str]:
    """Roll screen records up to one state per CIK under the pinned rule.

    ``eligible_over_boundary_over_ineligible_failsafe@1``: any eligible or
    boundary packet prevents firm-negative treatment; a CIK whose rows are
    all insufficient-evidence rolls up to INSUFFICIENT_EVIDENCE, which is
    non-negative and excluded from later classifier call lists. Firms are
    never merged: the key is the raw CIK.
    """
    order = ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN", "LIKELY_INELIGIBLE")
    statuses_by_cik: dict[str, set[str]] = {}
    for record in records:
        statuses = statuses_by_cik.setdefault(record["cik"], set())
        if record["record_kind"] == "screened_packet":
            statuses.add(record["screen_status"])
    states: dict[str, str] = {}
    for cik, statuses in statuses_by_cik.items():
        for status in order:
            if status in statuses:
                states[cik] = status
                break
        else:
            states[cik] = "INSUFFICIENT_EVIDENCE"
    return states


# --- Authority gate for downstream consumers -------------------------------------


def require_authoritative_screen_run(run_dir: str | Path) -> Path:
    """Refuse any screen run a SCREEN release or classifier may not consume.

    Authority is the manifest's presence plus its output bindings: a
    receipt-bearing directory, a manifest-less directory, or a directory
    whose output bytes no longer hash to the manifest's ``output_hashes``
    is refused. Returns the manifest path on success.
    """
    directory = Path(run_dir)
    receipt = directory / FAILURE_RECEIPT_FILENAME
    if receipt.exists():
        raise ScreenInputError(
            f"Screen run {directory} holds a failure receipt; it is "
            "non-authoritative and may not be consumed."
        )
    manifest_path = directory / SCREEN_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Screen run {directory} has no manifest; only a manifest-bearing "
            "run is authoritative."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file():
            raise ScreenInputError(
                f"Screen run output {filename} is missing beside its manifest."
            )
        observed = _sha256(target.read_bytes())
        if observed != recorded:
            raise ScreenInputError(
                f"Screen run output {filename} hashes to {observed}, but the "
                f"manifest records {recorded}; the run is not consumable."
            )
    return manifest_path


# --- The runner -------------------------------------------------------------------


@dataclass
class ScreenRunResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    status: str  # "completed" | "failed" | "dry_run"
    planned_screened: int
    planned_insufficient: int
    counts: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)
    request_accounting: dict = field(default_factory=dict)
    manifest_path: Path | None = None
    failure_receipt_path: Path | None = None
    receipt: dict | None = None


def _canonical_line(record: dict) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"))


def _charge_attempt(attempts_made: int, provider_attempt_cap: int) -> int:
    """Charge one provider attempt against the declared cap, or refuse."""
    if attempts_made + 1 > provider_attempt_cap:
        raise _AttemptCapBreach(
            f"Provider attempt cap {provider_attempt_cap} would be exceeded; "
            "the run stops rather than exceeding its authorized scale."
        )
    return attempts_made + 1


def run_lineage_screen(
    *,
    repo_root: str | Path,
    packet_manifest_path: str | Path,
    provider: LineageScreenProvider,
    output_dir: str | Path,
    run_id: str,
    logical_request_cap: int,
    provider_attempt_cap: int,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> ScreenRunResult:
    """Screen every retained row of one named v0.5 packet run. Fail closed."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )

    inputs = load_packet_run(root, packet_manifest_path)
    planned_screened = len(inputs.packets)
    planned_insufficient = len(inputs.failures)

    # The scale is stated, never discovered: the logical cap must equal the
    # screened-packet count exactly, and the attempt cap must equal the
    # logical cap under the bounded transient retry policy.
    if logical_request_cap != planned_screened:
        raise ScreenInputError(
            f"logical_request_cap is {logical_request_cap}, but the packet "
            f"run holds exactly {planned_screened} valid packet rows. One "
            "logical request per packet; state the scale you authorize."
        )
    expected_attempt_cap = logical_request_cap * (1 + MAX_TRANSIENT_RETRIES)
    if provider_attempt_cap != expected_attempt_cap:
        raise ScreenInputError(
            f"provider_attempt_cap is {provider_attempt_cap}, but the "
            f"bounded retry policy ({MAX_TRANSIENT_RETRIES} transient "
            f"retries per row) requires exactly {expected_attempt_cap}."
        )

    template_path = root / PROMPT_TEMPLATE_RELATIVE_PATH
    if not template_path.is_file():
        raise ScreenInputError(f"Screen prompt template not found: {template_path}")
    template_raw = template_path.read_bytes()
    template_text = _decode_utf8(template_raw, "Screen prompt template")
    prompt_template_sha256 = _sha256(template_raw)

    record_schema = _load_schema(root, RECORD_SCHEMA_RELATIVE_PATH)
    manifest_schema = _load_schema(root, MANIFEST_SCHEMA_RELATIVE_PATH)

    if dry_run:
        # Full validation and rendering, no provider call, no write anywhere.
        for packet in inputs.packets:
            render_lineage_screen_prompt(template_text, packet)
        return ScreenRunResult(
            run_id=run_id, run_dir=None, dry_run=True, status="dry_run",
            planned_screened=planned_screened,
            planned_insufficient=planned_insufficient,
            request_accounting={
                "logical_request_cap": logical_request_cap,
                "provider_attempt_cap": provider_attempt_cap,
                "max_transient_retries": MAX_TRANSIENT_RETRIES,
            },
        )

    run_dir = create_run_directory(output_dir, run_id)
    result = ScreenRunResult(
        run_id=run_id, run_dir=run_dir, dry_run=False, status="failed",
        planned_screened=planned_screened,
        planned_insufficient=planned_insufficient,
    )

    # The raw archive is the one append-during-run file: every received raw
    # response lands here before parsing, fsynced line by line, so a mid-run
    # failure retains every captured response. Created O_EXCL so the
    # write-once property holds for it too.
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
            "logical_request_cap": logical_request_cap,
            "provider_attempt_cap": provider_attempt_cap,
            "logical_requests_attempted": logical_requests_made,
            "provider_attempts_made": provider_attempts_made,
            "run_timestamp": clock().isoformat(),
            "retention_note": (
                "Non-authoritative failed run: no records JSONL and no "
                "manifest exist here, only the raw responses captured before "
                "the stop. This directory is immutable and may not be "
                "consumed by a SCREEN release or a classifier loader; a "
                "retry requires a new run id and new authorization."
            ),
        }
        if reason_code not in RECEIPT_REASON_CODES:
            raise ScreenInputError(
                f"Internal error: receipt reason {reason_code!r} is outside "
                f"the closed vocabulary {RECEIPT_REASON_CODES}."
            )
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
        result.request_accounting = {
            "logical_request_cap": logical_request_cap,
            "provider_attempt_cap": provider_attempt_cap,
            "max_transient_retries": MAX_TRANSIENT_RETRIES,
            "logical_requests_made": logical_requests_made,
            "provider_attempts_made": provider_attempts_made,
            "rows_retried": rows_retried,
            "tokens_in": None,
            "tokens_out": None,
        }
        return result

    for packet in inputs.packets:
        rendered = render_lineage_screen_prompt(template_text, packet)
        prompt_sha256 = _sha256(rendered.encode("utf-8"))
        logical_requests_made += 1

        raw_response: str | None = None
        row_attempts = 0
        while True:
            try:
                provider_attempts_made = _charge_attempt(
                    provider_attempts_made, provider_attempt_cap
                )
            except _AttemptCapBreach as exc:
                return _fail("provider_error", str(exc), packet)
            row_attempts += 1
            try:
                raw_response = provider.screen(
                    rendered, cik=packet["cik"], accession=packet["accession"]
                )
                break
            except ScreenProviderTransientError as exc:
                if row_attempts > MAX_TRANSIENT_RETRIES:
                    return _fail(
                        "provider_error",
                        f"Transient failures exhausted the {MAX_TRANSIENT_RETRIES}"
                        f"-retry bound for cik={packet['cik']}: {exc}",
                        packet,
                    )
                continue
            except ScreenProviderTerminalError as exc:
                return _fail(
                    "provider_error",
                    f"Terminal provider failure for cik={packet['cik']}: {exc}",
                    packet,
                )
        if row_attempts > 1:
            rows_retried += 1

        # Archive the verbatim response BEFORE any parsing or validation.
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
            "model_route": dict(provider.model_route),
            "raw_response_id": raw_response_id,
            "raw_response_sha256": raw_sha256,
            "screen_output": output.model_dump(mode="json"),
            "failure_reason_code": None,
            "failure_detail": None,
        })

    archive.flush()
    os.fsync(archive.fileno())
    archive.close()

    for failure in inputs.failures:
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

    # Re-read the archive from disk and re-derive every screened binding:
    # the file that will be hashed is the file that is verified.
    archive_raw = archive_path.read_bytes()
    archive_entries = [
        json.loads(line)
        for line in _decode_utf8(archive_raw, RAW_RESPONSES_FILENAME).splitlines()
        if line.strip()
    ]
    entries_by_id = {entry["raw_response_id"]: entry for entry in archive_entries}
    screened = [r for r in records if r["record_kind"] == "screened_packet"]
    insufficient = [r for r in records if r["record_kind"] == "insufficient_evidence"]
    raw_bindings_hold = len(entries_by_id) == len(archive_entries) and all(
        (entry := entries_by_id.get(record["raw_response_id"])) is not None
        and _sha256(entry["raw_response"].encode("utf-8"))
        == entry["raw_response_sha256"] == record["raw_response_sha256"]
        for record in screened
    )

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
        "planned_rows": planned_screened + planned_insufficient,
        "screened_packets": len(screened),
        "insufficient_evidence": len(insufficient),
        "by_screen_status": status_counts,
        "firms_total": len(rollup_states),
        "firm_rollup": rollup_counts,
    }
    request_accounting = {
        "logical_request_cap": logical_request_cap,
        "provider_attempt_cap": provider_attempt_cap,
        "max_transient_retries": MAX_TRANSIENT_RETRIES,
        "logical_requests_made": logical_requests_made,
        "provider_attempts_made": provider_attempts_made,
        "rows_retried": rows_retried,
        "tokens_in": getattr(provider, "tokens_in", None),
        "tokens_out": getattr(provider, "tokens_out", None),
    }

    reconciliation = {
        "records partition the retained rows": (
            len(records) == len(screened) + len(insufficient)
            == counts["planned_rows"]
        ),
        "every valid packet row was screened exactly once": (
            len(screened) == planned_screened == logical_requests_made
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
        "provider attempts never exceeded the declared cap": (
            provider_attempts_made <= provider_attempt_cap
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
            "Screen reconciliation failed; no records JSONL and no manifest "
            f"are written. Failed identities: {failed}. The run directory "
            "retains only the raw archive and is non-authoritative."
        )

    records_payload = (
        "\n".join(_canonical_line(record) for record in records) + "\n"
    ).encode("utf-8")
    try:
        write_bytes_once(run_dir / RECORDS_FILENAME, records_payload,
                         what=f"screen records {run_dir / RECORDS_FILENAME}")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    manifest = {
        "run_id": run_id,
        "packet_manifest_path": str(packet_manifest_path),
        "packet_manifest_sha256": inputs.manifest_sha256,
        "packet_run_id": inputs.manifest["run_id"],
        "packets_jsonl_sha256": inputs.packets_jsonl_sha256,
        "packet_failures_jsonl_sha256": inputs.failures_jsonl_sha256,
        "prompt_template_path": PROMPT_TEMPLATE_RELATIVE_PATH,
        "prompt_template_sha256": prompt_template_sha256,
        "provider": {
            "name": provider.name,
            "model_route": dict(provider.model_route),
        },
        "screen_record_order": SCREEN_RECORD_ORDER,
        "firm_rollup_rule": FIRM_ROLLUP_RULE,
        "baseline_cutoff": inputs.baseline_cutoff,
        "counts": counts,
        "request_accounting": request_accounting,
        "reconciliation": reconciliation,
        "output_hashes": {
            RECORDS_FILENAME: _sha256(records_payload),
            RAW_RESPONSES_FILENAME: _sha256(archive_raw),
        },
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "universe_screen_record": "0.1.0",
            "universe_screen_manifest": "0.1.0",
            "baseline_packet_manifest_v5": "0.5.0",
            "universe_baseline_packet_v2": "0.2.0",
        },
        "limitations": [
            "A screen status is a recall decision only: it is never final "
            "sample membership and never establishes software eligibility.",
            "INSUFFICIENT_EVIDENCE exists only at firm roll-up. The "
            "insufficient-evidence rows preserve packet-build failures "
            "verbatim; their filing dates are null because the failures "
            "JSONL, their only authority, carries none.",
            "The model saw CIK, accession, form, filing date, cutoff and "
            "Item 1 passages only — no company name, ticker, exchange or "
            "SIC code.",
            "Token accounting is null under the mock provider; the live "
            "successor records provider-reported totals.",
            "Every binding is relational between the supplied inputs; no "
            "production hash is pinned in code or schema.",
        ],
    }
    _validate(manifest, manifest_schema, "Screen run manifest")
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
