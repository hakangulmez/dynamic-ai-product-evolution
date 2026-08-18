"""PCT_Dev30_v0 combined-candidate adapter (Round 2 contract).

Turns one raw Stage-1 model-output artifact (``pct_dev30_v0_model_output@0.1.0``,
local-ID-scoped, never touched by hand) into a persisted Stage-2 artifact
(``pct_dev30_v0_persisted_candidates@0.1.0``) whose ``candidate_id`` values are
deterministic, non-transferable across raw outputs, and reproducible from the
persisted record alone.

Nothing here trusts the model, and nothing here trusts the caller for
provenance either. The caller supplies only ``ticker``, ``span_text``, the
raw Stage-1 bytes, and ``model_output_reference``. Every authoritative fact
-- ``legacy_source_id``, the Item 1 span text's expected hash -- is read from
one fixed, hash-pinned path: the committed
``evals/registries/pct_dev30_v0_item1_locator_ledger.json``, resolved from
the repository root, never a caller-supplied path. There is no public
parameter through which a caller can point this module at a different
ledger. A model output that echoes the wrong ``legacy_source_id``, a
``span_text`` whose hash disagrees with the ledger, or a canonical ledger
file that no longer matches its reviewed hash pin, is refused before any
candidate_id is computed.

This module performs read-only I/O limited to the two schema files under
``schemas/`` and the one canonical ledger path above, all three hash-pinned.
It calls no model, makes no network request, and never constructs or accepts
a Stage 00C ``source_id`` (``sec-primary:<cik>:<accession>:<selected_document>``)
-- Dev30 identity is exclusively the ``legacy-item1:dev30-v0:<hash>``
namespace.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

__all__ = [
    "STAGE1_CONTRACT",
    "STAGE2_CONTRACT",
    "SCHEMA_VERSION",
    "LOCATOR_LEDGER_RELATIVE_PATH",
    "EXCLUDED_MENTION_REASONS",
    "ZERO_CANDIDATE_REASONS",
    "REASON_NOT_VALID_JSON",
    "REASON_SCHEMA_INVALID",
    "REASON_SCHEMA_FILE_TAMPERED",
    "REASON_LEDGER_FILE_TAMPERED",
    "REASON_LEDGER_ROW_NOT_FOUND",
    "REASON_SPAN_TEXT_HASH_MISMATCH",
    "REASON_LEGACY_SOURCE_ID_MISMATCH",
    "REASON_DANGLING_LOCAL_REFERENCE",
    "REASON_DUPLICATE_LOCAL_ID",
    "REASON_INVALID_LOCATOR_BOUNDS",
    "REASON_EVIDENCE_QUOTE_CONTAINMENT_FAILED",
    "CombinedCandidateAdapterError",
    "build_persisted_candidates",
]

STAGE1_CONTRACT = "pct_dev30_v0_model_output@0.1.0"
STAGE2_CONTRACT = "pct_dev30_v0_persisted_candidates@0.1.0"
SCHEMA_VERSION = "0.1.0"

#: Fixed for the whole PCT_Dev30_v0 line; never caller-supplied.
LOCATOR_LEDGER_RELATIVE_PATH = "evals/registries/pct_dev30_v0_item1_locator_ledger.json"

EXCLUDED_MENTION_REASONS = frozenset(
    {
        "internal_use",
        "vague_ai_marketing",
        "not_customer_facing",
        "insufficient_specificity",
    }
)
ZERO_CANDIDATE_REASONS = frozenset(
    {
        "no_product_capability_or_task_evidence",
        "all_mentions_excluded",
    }
)

REASON_NOT_VALID_JSON = "not_valid_json"
REASON_SCHEMA_INVALID = "schema_invalid"
REASON_SCHEMA_FILE_TAMPERED = "schema_file_tampered"
REASON_LEDGER_FILE_TAMPERED = "ledger_file_tampered"
REASON_LEDGER_ROW_NOT_FOUND = "ledger_row_not_found"
REASON_SPAN_TEXT_HASH_MISMATCH = "span_text_hash_mismatch"
REASON_LEGACY_SOURCE_ID_MISMATCH = "legacy_source_id_mismatch"
REASON_DANGLING_LOCAL_REFERENCE = "dangling_local_reference"
REASON_DUPLICATE_LOCAL_ID = "duplicate_local_id"
REASON_INVALID_LOCATOR_BOUNDS = "invalid_locator_bounds"
REASON_EVIDENCE_QUOTE_CONTAINMENT_FAILED = "evidence_quote_containment_failed"

_REASONS = frozenset(
    {
        REASON_NOT_VALID_JSON,
        REASON_SCHEMA_INVALID,
        REASON_SCHEMA_FILE_TAMPERED,
        REASON_LEDGER_FILE_TAMPERED,
        REASON_LEDGER_ROW_NOT_FOUND,
        REASON_SPAN_TEXT_HASH_MISMATCH,
        REASON_LEGACY_SOURCE_ID_MISMATCH,
        REASON_DANGLING_LOCAL_REFERENCE,
        REASON_DUPLICATE_LOCAL_ID,
        REASON_INVALID_LOCATOR_BOUNDS,
        REASON_EVIDENCE_QUOTE_CONTAINMENT_FAILED,
    }
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_DIR = _REPO_ROOT / "schemas"
_STAGE1_SCHEMA_PATH = _SCHEMA_DIR / "pct_dev30_v0_model_output.schema.json"
_STAGE2_SCHEMA_PATH = _SCHEMA_DIR / "pct_dev30_v0_persisted_candidates.schema.json"

#: Reviewed source literals, matching the committed schema files at the time
#: this module was written. A tampered or drifted schema file refuses rather
#: than silently validating against different rules than were reviewed.
_STAGE1_SCHEMA_SHA256 = "6e895cb805091103f78888b0d904a21994e5ecc6b0aef88dd60d67b5c15c9bc4"
_STAGE2_SCHEMA_SHA256 = "e9706e9bb99461f126fde1126f7eb15be5b7492a16e98e5e9627127e90b96333"

#: The one canonical Dev30 v0 locator ledger. Module-private and never
#: exposed as a public function parameter -- a caller chooses a ticker, not
#: a ledger. Tests may monkeypatch these two names together to point at a
#: synthetic fixture; production code always resolves and verifies this
#: exact path and hash.
_LEDGER_PATH = _REPO_ROOT / LOCATOR_LEDGER_RELATIVE_PATH
_CANONICAL_LEDGER_SHA256 = "69d25d1820a22625b1b13a4eebb704232740ca1937249816f4378e7e4a56b762"


class CombinedCandidateAdapterError(Exception):
    """Refused to build the persisted artifact. ``reason`` is one of the
    module-level ``REASON_*`` constants -- never a silently repaired
    fallback."""

    def __init__(self, reason: str, message: str):
        if reason not in _REASONS:
            raise ValueError(f"not a recognized adapter refusal reason: {reason!r}")
        self.reason = reason
        super().__init__(message)


def _load_pinned_schema(path: Path, expected_sha256: str) -> dict:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise CombinedCandidateAdapterError(
            REASON_SCHEMA_FILE_TAMPERED,
            f"{path.name} sha256 mismatch: expected {expected_sha256}, got {actual}",
        )
    return json.loads(raw.decode("utf-8"))


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _validate_against_schema(instance: dict, schema: dict, *, label: str) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(instance), key=lambda e: list(e.path))
    if errors:
        detail = "; ".join(f"{list(e.path)}: {e.message}" for e in errors[:5])
        raise CombinedCandidateAdapterError(
            REASON_SCHEMA_INVALID, f"{label} failed schema validation: {detail}"
        )


def _load_verified_ledger_row(ticker: str) -> dict:
    """Read the one canonical, hash-pinned Dev30 locator ledger and return
    the row for ``ticker``. Refuses on tamper/drift before ever looking at
    ``ticker`` -- the pin is checked first, unconditionally. Callers use the
    ``_CANONICAL_LEDGER_SHA256`` constant directly as the verified digest;
    this function does not hand back a recomputed hash for that purpose."""
    ledger_bytes = _LEDGER_PATH.read_bytes()
    actual_sha256 = hashlib.sha256(ledger_bytes).hexdigest()
    if actual_sha256 != _CANONICAL_LEDGER_SHA256:
        raise CombinedCandidateAdapterError(
            REASON_LEDGER_FILE_TAMPERED,
            f"{_LEDGER_PATH} sha256 mismatch: expected {_CANONICAL_LEDGER_SHA256}, "
            f"got {actual_sha256}",
        )
    ledger = json.loads(ledger_bytes.decode("utf-8"))
    for row in ledger["rows"]:
        if row["ticker"] == ticker:
            return row
    raise CombinedCandidateAdapterError(
        REASON_LEDGER_ROW_NOT_FOUND,
        f"no ledger row for ticker {ticker!r} in {_LEDGER_PATH}",
    )


def _parse_stage1(raw_stage1_bytes: bytes) -> dict:
    try:
        text = raw_stage1_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise CombinedCandidateAdapterError(
            REASON_NOT_VALID_JSON, f"raw Stage-1 bytes did not decode as strict UTF-8: {exc}"
        ) from exc
    try:
        stage1 = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CombinedCandidateAdapterError(
            REASON_NOT_VALID_JSON, f"raw Stage-1 bytes are not valid JSON: {exc}"
        ) from exc
    if not isinstance(stage1, dict):
        raise CombinedCandidateAdapterError(
            REASON_NOT_VALID_JSON,
            f"top-level Stage-1 JSON value is a {type(stage1).__name__}, not an object",
        )
    return stage1


def _validate_local_references(candidates: list[dict]) -> None:
    """Existence-only. Kind-correctness of every reference is already closed
    by the schema: a capability/task's ``kind`` is fixed by its own oneOf
    branch, and that branch's ``local_id`` pattern is the only way a given
    local_id string can validate at all -- so a schema-valid document can
    never contain a "P1" local_id on anything but a product row. A
    referential wrong-kind condition is therefore unreachable once schema
    validation (which always runs first) has passed, and is not re-checked
    here."""
    seen: set[str] = set()
    for row in candidates:
        local_id = row["local_id"]
        if local_id in seen:
            raise CombinedCandidateAdapterError(
                REASON_DUPLICATE_LOCAL_ID, f"local_id {local_id!r} appears more than once"
            )
        seen.add(local_id)

    def _check(reference: str, *, owner: str) -> None:
        if reference not in seen:
            raise CombinedCandidateAdapterError(
                REASON_DANGLING_LOCAL_REFERENCE,
                f"{owner} references local_id {reference!r}, which does not exist",
            )

    for row in candidates:
        if row["kind"] in ("capability", "task"):
            _check(row["product_local_id"], owner=row["local_id"])
        if row["kind"] == "task":
            for cap_ref in row["capability_local_ids"]:
                _check(cap_ref, owner=row["local_id"])


def _check_containment(evidence_quote: str, locator: dict, span_text: str, *, owner: str) -> None:
    start, end = locator["char_start"], locator["char_end"]
    if not (0 <= start < end <= len(span_text)):
        raise CombinedCandidateAdapterError(
            REASON_INVALID_LOCATOR_BOUNDS,
            f"{owner}: char_start={start}, char_end={end} out of bounds for a "
            f"span of length {len(span_text)}",
        )
    if span_text[start:end] != evidence_quote:
        raise CombinedCandidateAdapterError(
            REASON_EVIDENCE_QUOTE_CONTAINMENT_FAILED,
            f"{owner}: evidence_quote does not match span_text[{start}:{end}]",
        )


def build_persisted_candidates(
    *,
    ticker: str,
    span_text: str,
    raw_stage1_bytes: bytes,
    model_output_reference: str,
) -> dict[str, Any]:
    """Build and validate the Stage-2 persisted artifact from one raw Stage-1
    model output, refusing on any of the eleven ``REASON_*`` conditions.

    There is no ``locator_ledger_path`` parameter: the ledger this function
    checks against is always the one canonical, hash-pinned
    ``evals/registries/pct_dev30_v0_item1_locator_ledger.json``. A caller
    cannot select a different ledger through this API.

    ``span_text`` is the caller's claimed Item 1 span for this ticker; it is
    checked against the ledger's own ``source_text_hash`` before being
    trusted for any evidence-quote containment check, so an arbitrary or
    stale caller string cannot be used to rubber-stamp a candidate's quote.
    """
    stage1_schema = _load_pinned_schema(_STAGE1_SCHEMA_PATH, _STAGE1_SCHEMA_SHA256)
    stage2_schema = _load_pinned_schema(_STAGE2_SCHEMA_PATH, _STAGE2_SCHEMA_SHA256)

    ledger_row = _load_verified_ledger_row(ticker)
    expected_legacy_source_id = ledger_row["legacy_source_id"]
    expected_span_hash = ledger_row["source_text_hash"]

    actual_span_hash = hashlib.sha256(span_text.encode("utf-8")).hexdigest()
    if actual_span_hash != expected_span_hash:
        raise CombinedCandidateAdapterError(
            REASON_SPAN_TEXT_HASH_MISMATCH,
            f"span_text sha256 {actual_span_hash} does not match the ledger's "
            f"source_text_hash {expected_span_hash} for ticker {ticker!r}",
        )

    stage1 = _parse_stage1(raw_stage1_bytes)
    _validate_against_schema(stage1, stage1_schema, label="Stage-1 model output")

    if stage1["legacy_source_id"] != expected_legacy_source_id:
        raise CombinedCandidateAdapterError(
            REASON_LEGACY_SOURCE_ID_MISMATCH,
            f"Stage-1 legacy_source_id {stage1['legacy_source_id']!r} does not "
            f"match the ledger's {expected_legacy_source_id!r} for ticker {ticker!r}",
        )

    model_output_sha256 = hashlib.sha256(raw_stage1_bytes).hexdigest()

    candidates = stage1["candidates"]
    excluded_mentions = stage1["excluded_mentions"]

    _validate_local_references(candidates)

    for ordinal, row in enumerate(candidates):
        _check_containment(
            row["evidence_quote"], row["evidence_locator"], span_text,
            owner=f"candidates[{ordinal}] ({row['local_id']})",
        )
    for index, mention in enumerate(excluded_mentions):
        _check_containment(
            mention["evidence_quote"], mention["evidence_locator"], span_text,
            owner=f"excluded_mentions[{index}]",
        )

    persisted_candidate_id: dict[str, str] = {}
    persisted_rows: dict[str, dict] = {}

    for kind in ("product", "capability", "task"):
        for ordinal, row in enumerate(candidates):
            if row["kind"] != kind:
                continue
            fields = {k: v for k, v in row.items() if k not in ("local_id", "kind")}
            fields["evidence_locator"] = {
                "legacy_source_id": expected_legacy_source_id,
                "char_start": row["evidence_locator"]["char_start"],
                "char_end": row["evidence_locator"]["char_end"],
            }
            if kind in ("capability", "task"):
                fields["product_candidate_id"] = persisted_candidate_id[
                    row["product_local_id"]
                ]
                del fields["product_local_id"]
            if kind == "task":
                fields["capability_candidate_ids"] = [
                    persisted_candidate_id[cap_ref]
                    for cap_ref in row["capability_local_ids"]
                ]
                del fields["capability_local_ids"]

            candidate_id = hashlib.sha256(
                model_output_sha256.encode("utf-8")
                + b"\x00"
                + str(ordinal).encode("utf-8")
                + b"\x00"
                + kind.encode("utf-8")
                + b"\x00"
                + _canonical_json_bytes(fields)
            ).hexdigest()[:32]

            persisted_candidate_id[row["local_id"]] = candidate_id
            persisted_rows[row["local_id"]] = {
                "candidate_id": candidate_id,
                "local_id": row["local_id"],
                "ordinal": ordinal,
                "kind": kind,
                **fields,
            }

    persisted_excluded_mentions = [
        {
            "reason": mention["reason"],
            "evidence_quote": mention["evidence_quote"],
            "evidence_locator": {
                "legacy_source_id": expected_legacy_source_id,
                "char_start": mention["evidence_locator"]["char_start"],
                "char_end": mention["evidence_locator"]["char_end"],
            },
        }
        for mention in excluded_mentions
    ]

    stage2 = {
        "contract": STAGE2_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "ticker": ticker,
        "legacy_source_id": expected_legacy_source_id,
        "model_output_reference": model_output_reference,
        "model_output_sha256": model_output_sha256,
        "locator_ledger_relative_path": LOCATOR_LEDGER_RELATIVE_PATH,
        "locator_ledger_sha256": _CANONICAL_LEDGER_SHA256,
        "candidates": [persisted_rows[row["local_id"]] for row in candidates],
        "excluded_mentions": persisted_excluded_mentions,
        "zero_candidate_reason": stage1["zero_candidate_reason"],
    }

    _validate_against_schema(stage2, stage2_schema, label="Stage-2 persisted output")
    return stage2
