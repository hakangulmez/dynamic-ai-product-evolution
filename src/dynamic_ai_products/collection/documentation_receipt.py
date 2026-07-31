"""Documentation collection receipt: schema, loader and builder (ADR-037, E-C-D).

**One constructor is the single source of truth.** :func:`expected_receipt_schema`
builds the complete locked schema; the committed file is generated from it, and
:func:`validate_receipt_schema_bytes` deep-compares supplied bytes against it.
That closes the gap a hand-written checklist leaves: a checklist verifies the
properties someone remembered to list, so weakening ``http_status.maximum`` or
replacing ``retrieval_timestamp.pattern`` with ``".*"`` slipped through. A deep
comparison has no such blind spot. It is not a raw-file SHA constant either —
JSON is parsed first, so formatting may differ while semantics may not.

**The schema is validated from bytes, and its digest is derived, never claimed.**
A caller-asserted digest is refused: the pin is mandatory, the *claim* forbidden.

**Runtime-``jsonschema``-free.** That package sits in the ``dev`` extra while 11
modules under ``src/`` already import it; deepening that inconsistency was
rejected. Tests exercise the committed schema with a real validator; production
does not.

**Retrieval status only.** Whether the persisted bytes contain the required
official claim belongs to ``documentation_evidence_validation@0.1.0``, so
``evidence_body_unusable`` is never a collection failure reason.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from .errors import CollectionError
from .publication import canonical_json_bytes

__all__ = [
    "ATTEMPT_ID_PATTERN",
    "ENTRY_PROPERTIES",
    "ENTRY_RECORDABLE_REASONS",
    "ENTRY_REQUIRED",
    "ENTRY_STATUSES",
    "FAILURE_REASONS",
    "FROZEN_ENTRY_IDENTITIES",
    "RECEIPT_CONTRACT",
    "RECEIPT_PROPERTIES",
    "RECEIPT_REQUIRED",
    "RECEIPT_SCHEMA_ID",
    "SCHEMA_DIALECT",
    "SHA256_PATTERN",
    "TERMINAL_SEQUENCES",
    "UTC_INSTANT_PATTERN",
    "build_documentation_receipt",
    "expected_receipt_schema",
    "receipt_bytes",
    "validate_receipt_schema_bytes",
]

RECEIPT_CONTRACT = "documentation_collection_receipt@0.1.0"
RECEIPT_SCHEMA_ID = "documentation_collection_receipt.schema.json"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SHA256_PATTERN = "^[0-9a-f]{64}$"
ATTEMPT_ID_PATTERN = "^docattempt-[0-9a-f]{32}$"
UTC_INSTANT_PATTERN = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?(Z|\+00:00)$"

ENTRY_STATUSES: tuple[str, ...] = ("succeeded", "failed", "not_attempted")
COMPLETION_STATUSES: tuple[str, ...] = ("completed", "stopped")

# The full public vocabulary the collector may raise.
FAILURE_REASONS: tuple[str, ...] = (
    "attempt_byte_ceiling_exceeded", "attempt_identity_invalid", "attempt_root_exists",
    "attempt_root_unsafe", "content_object_corrupt", "content_type_invalid",
    "destination_exists", "direct_terminal_not_permitted", "entity_empty",
    "entity_too_large", "receipt_publication_failed", "receipt_schema_claim_forbidden",
    "receipt_schema_contract_mismatch", "receipt_schema_invalid",
    "redirect_chain_too_long", "redirect_location_mismatch",
    "redirect_location_missing", "redirect_location_not_absolute",
    "redirect_status_invalid", "response_request_identity_mismatch",
    "retrieval_clock_failed", "retrieval_clock_invalid", "terminal_status_invalid",
    "tls_keylog_environment_present", "transport_failed", "transport_timeout",
    "write_error",
)

# Reasons that can only arise before the attempt root exists, or only while
# publishing the receipt itself. Neither can truthfully appear inside an entry
# of a receipt that was successfully published.
_NON_ENTRY_REASONS: frozenset[str] = frozenset(
    {
        "receipt_schema_claim_forbidden",
        "receipt_schema_invalid",
        "receipt_schema_contract_mismatch",
        "attempt_identity_invalid",
        "attempt_root_exists",
        "attempt_root_unsafe",
        "receipt_publication_failed",
    }
)
ENTRY_RECORDABLE_REASONS: tuple[str, ...] = tuple(
    reason for reason in FAILURE_REASONS if reason not in _NON_ENTRY_REASONS
)

# Positional route identities, duplicated deliberately so the receipt contract
# stays checkable without importing the orchestrator it describes.
FROZEN_ENTRY_IDENTITIES: tuple[dict[str, str], ...] = (
    {
        "evidence_kind": "gemini_thinking",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/docs/thinking",
        "final_url": (
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/"
            "models/thinking"
        ),
    },
    {
        "evidence_kind": "count_tokens",
        "requested_url": (
            "https://cloud.google.com/vertex-ai/generative-ai/docs/multimodal/"
            "get-token-count"
        ),
        "final_url": (
            "https://docs.cloud.google.com/gemini-enterprise-agent-platform/"
            "models/capabilities/get-token-count"
        ),
    },
    {
        "evidence_kind": "pricing_standard",
        "requested_url": "https://cloud.google.com/vertex-ai/generative-ai/pricing",
        "final_url": (
            "https://cloud.google.com/gemini-enterprise-agent-platform/"
            "generative-ai/pricing"
        ),
    },
)

# The only four terminal sequences a truthful attempt can produce. Anything else
# -- a success after a failure, two failures, a stop with none -- describes a run
# that cannot have happened, because the collector stops at the first failure.
TERMINAL_SEQUENCES: tuple[tuple[str, tuple[str, str, str]], ...] = (
    ("completed", ("succeeded", "succeeded", "succeeded")),
    ("stopped", ("failed", "not_attempted", "not_attempted")),
    ("stopped", ("succeeded", "failed", "not_attempted")),
    ("stopped", ("succeeded", "succeeded", "failed")),
)

RECEIPT_REQUIRED: frozenset[str] = frozenset(
    {
        "contract", "schema_version", "attempt_id", "code_commit", "run_created_at",
        "adapter_contract_sha256", "policy_contract_sha256", "receipt_schema_sha256",
        "retrieval_timestamp_mode", "entries", "completion_status",
    }
)
RECEIPT_PROPERTIES: frozenset[str] = RECEIPT_REQUIRED

ENTRY_REQUIRED: frozenset[str] = frozenset(
    {
        "evidence_kind", "requested_url", "final_url", "entry_status",
        "redirect_chain", "http_status", "content_type", "content_encoding",
        "byte_count", "content_sha256", "raw_reference", "object_disposition",
        "retrieval_timestamp", "failure_reason",
    }
)
ENTRY_PROPERTIES: frozenset[str] = ENTRY_REQUIRED

_NULL_ENTRY_FIELDS: tuple[str, ...] = (
    "http_status", "content_type", "content_encoding", "byte_count",
    "content_sha256", "raw_reference", "object_disposition", "retrieval_timestamp",
)


def _refuse(message: str, code: str = "receipt_schema_invalid") -> None:
    raise CollectionError(message, reason_code=code)


def _is_utc_instant(value: Any) -> bool:
    """Lexical **and** semantic: a regex alone admits 2026-02-30 and 24:00:00."""
    if not isinstance(value, str) or not re.fullmatch(UTC_INSTANT_PATTERN, value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0)


# --- the single source of truth ----------------------------------------------


def _entry_schema(entry: dict[str, str]) -> dict[str, Any]:
    """One positionally frozen entry with its full per-status payload rules."""
    succeeded = {
        "properties": {
            # Exactly this entry's own route, so a chain borrowed from another
            # entry or an empty one cannot pass.
            "redirect_chain": {"const": [entry["requested_url"], entry["final_url"]]},
            "http_status": {"const": 200},
            "content_type": {"type": "string", "minLength": 1},
            "content_encoding": {"type": "string", "minLength": 1},
            "byte_count": {"type": "integer", "minimum": 1},
            "content_sha256": {"type": "string", "pattern": SHA256_PATTERN},
            "raw_reference": {"type": "string", "minLength": 1},
            "object_disposition": {"enum": ["created", "reused"]},
            "retrieval_timestamp": {"type": "string", "pattern": UTC_INSTANT_PATTERN},
            "failure_reason": {"const": None},
        }
    }
    emptied = {
        "properties": {
            "redirect_chain": {"const": []},
            **{field: {"const": None} for field in _NULL_ENTRY_FIELDS},
        }
    }
    failed = {
        "properties": {
            **emptied["properties"],
            "failure_reason": {"enum": list(ENTRY_RECORDABLE_REASONS)},
        }
    }
    not_attempted = {
        "properties": {
            **emptied["properties"],
            "failure_reason": {"const": None},
        }
    }
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(ENTRY_REQUIRED),
        "properties": {
            "evidence_kind": {"const": entry["evidence_kind"]},
            "requested_url": {"const": entry["requested_url"]},
            "final_url": {"const": entry["final_url"]},
            "entry_status": {"type": "string", "enum": list(ENTRY_STATUSES)},
            "redirect_chain": {
                "type": "array",
                "items": {"type": "string", "minLength": 1},
                "maxItems": 2,
            },
            "http_status": {"type": ["integer", "null"], "minimum": 100, "maximum": 599},
            "content_type": {"type": ["string", "null"], "minLength": 1},
            "content_encoding": {"type": ["string", "null"], "minLength": 1},
            "byte_count": {"type": ["integer", "null"], "minimum": 1},
            "content_sha256": {"type": ["string", "null"], "pattern": SHA256_PATTERN},
            "raw_reference": {"type": ["string", "null"], "minLength": 1},
            "object_disposition": {"enum": ["created", "reused", None]},
            "retrieval_timestamp": {
                "type": ["string", "null"],
                "pattern": UTC_INSTANT_PATTERN,
            },
            "failure_reason": {"enum": list(ENTRY_RECORDABLE_REASONS) + [None]},
        },
        "allOf": [
            {"if": {"properties": {"entry_status": {"const": "succeeded"}}}, "then": succeeded},
            {"if": {"properties": {"entry_status": {"const": "failed"}}}, "then": failed},
            {
                "if": {"properties": {"entry_status": {"const": "not_attempted"}}},
                "then": not_attempted,
            },
        ],
    }


def _sequence_branch(completion: str, statuses: tuple[str, str, str]) -> dict[str, Any]:
    return {
        "properties": {
            "completion_status": {"const": completion},
            "entries": {
                "prefixItems": [
                    {"properties": {"entry_status": {"const": status}}}
                    for status in statuses
                ]
            },
        }
    }


def expected_receipt_schema() -> dict[str, Any]:
    """The complete locked schema. The committed file is generated from this."""
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": RECEIPT_SCHEMA_ID,
        "title": RECEIPT_CONTRACT,
        "comment": (
            "ADR-037 (E-C-D). One attempt-level receipt for the ordered three-entry "
            "documentation acquisition. Entries are positionally frozen and each "
            "status pins its own payload shape, so a succeeded entry without a "
            "digest, a failed entry carrying one, or a sequence describing a run "
            "that cannot have happened are all refused. The receipt owns "
            "retrieval_status only; whether the bytes contain the required official "
            "claim belongs to documentation_evidence_validation@0.1.0. It lives "
            "outside any content digest directory so it stays writable when the "
            "first entry fails before any hash exists."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": sorted(RECEIPT_REQUIRED),
        "properties": {
            "contract": {"const": RECEIPT_CONTRACT},
            "schema_version": {"const": "0.1.0"},
            "attempt_id": {"type": "string", "pattern": ATTEMPT_ID_PATTERN},
            "code_commit": {"type": "string", "minLength": 1},
            "run_created_at": {"type": "string", "pattern": UTC_INSTANT_PATTERN},
            "adapter_contract_sha256": {"type": "string", "pattern": SHA256_PATTERN},
            "policy_contract_sha256": {"type": "string", "pattern": SHA256_PATTERN},
            "receipt_schema_sha256": {"type": "string", "pattern": SHA256_PATTERN},
            "retrieval_timestamp_mode": {
                "const": "caller_injected_request_start_utc_v1"
            },
            "entries": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "prefixItems": [_entry_schema(e) for e in FROZEN_ENTRY_IDENTITIES],
                "items": False,
            },
            "completion_status": {"type": "string", "enum": list(COMPLETION_STATUSES)},
        },
        # Exactly one of the four truthful terminal sequences.
        "oneOf": [_sequence_branch(c, s) for c, s in TERMINAL_SEQUENCES],
    }


class _DuplicateMemberError(ValueError):
    """A JSON object repeated a member name; the parser would hide one value."""


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` that refuses repeated names at any nesting level.

    ``json.loads`` silently keeps the last occurrence, so ``{"a": 1, "a": 1}``
    and ``{"a": 1, "a": 2}`` both parse to a single member. A schema carrying a
    duplicate is ambiguous about which definition governs -- even when the two
    values are identical, because a later reader or a different parser need not
    resolve it the same way.
    """
    seen: set[str] = set()
    for name, _ in pairs:
        if name in seen:
            raise _DuplicateMemberError(name)
        seen.add(name)
    return dict(pairs)


def _json_exact_equal(left: Any, right: Any) -> bool:
    """Recursive, JSON-type-exact comparison.

    Ordinary ``==`` is not type-exact for JSON: ``True == 1`` and ``False == 0``
    in Python, so ``minLength: true`` compared equal to ``minLength: 1`` and
    ``additionalProperties: 0`` compared equal to ``additionalProperties: false``
    -- four real weakenings that a plain ``!=`` accepted. ``3 == 3.0`` likewise
    erased the integer/number distinction. Type identity is therefore checked
    before value equality, with ``bool`` separated from ``int`` explicitly.
    """
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if set(left) != set(right):
            return False
        return all(_json_exact_equal(left[key], right[key]) for key in left)
    if isinstance(left, list):
        if len(left) != len(right):
            return False
        return all(_json_exact_equal(a, b) for a, b in zip(left, right))
    return left == right


def validate_receipt_schema_bytes(schema_bytes: Any) -> str:
    """Prove the bytes are the locked schema, semantically, and return the digest.

    Recursive JSON-type-exact comparison against
    :func:`expected_receipt_schema`, so every type, const, enum, pattern, bound,
    nullability and conditional rule is verified -- not a subset someone
    remembered to list, and not a comparison that Python's ``bool``/``int``
    equivalence can slip past. Duplicate member names are refused at any depth.

    Formatting is not part of the comparison: an equivalent schema written with
    different indentation or key order is accepted, and the returned digest is
    always derived from the exact bytes supplied.
    """
    if not isinstance(schema_bytes, (bytes, bytearray)) or not schema_bytes:
        _refuse("receipt schema bytes are required")
    try:
        schema = json.loads(
            bytes(schema_bytes).decode("utf-8"), object_pairs_hook=_reject_duplicate_members
        )
    except _DuplicateMemberError:
        _refuse("the receipt schema repeats a member name")
    except (UnicodeDecodeError, ValueError):
        _refuse("receipt schema bytes are not valid UTF-8 JSON")
    if not isinstance(schema, dict):
        _refuse("the receipt schema must be a JSON object")

    # A foreign contract is a different failure from a weakened one, so it keeps
    # its own code -- but only when the shape actually *names* another contract.
    # A missing ``const``, or one holding null, a bool, a number, a list, an
    # object or a blank string, identifies nothing; those are weakenings, not
    # foreign contracts, and fall through to the exact comparison below.
    properties = schema.get("properties")
    if isinstance(properties, dict):
        contract = properties.get("contract")
        if isinstance(contract, dict):
            declared = contract.get("const")
            if (
                isinstance(declared, str)
                and not isinstance(declared, bool)
                and declared.strip()
                and declared != RECEIPT_CONTRACT
            ):
                _refuse(
                    "properties.contract.const identifies a different contract",
                    "receipt_schema_contract_mismatch",
                )

    required = schema.get("required")
    if isinstance(required, list) and all(isinstance(name, str) for name in required):
        if len(required) != len(set(required)):
            _refuse("the receipt schema required list carries duplicates")

    if not _json_exact_equal(schema, expected_receipt_schema()):
        _refuse("the receipt schema does not match the locked definition")
    return sha256(bytes(schema_bytes)).hexdigest()


# --- the builder --------------------------------------------------------------


def _entry_violations(entry: Any, frozen: dict[str, str]) -> str | None:
    if not isinstance(entry, dict) or frozenset(entry) != ENTRY_PROPERTIES:
        return "an entry does not carry exactly the locked property set"
    for field, expected in frozen.items():
        if entry.get(field) != expected:
            return f"an entry does not carry its frozen {field}"
    status = entry.get("entry_status")
    if status not in ENTRY_STATUSES:
        return "unknown entry status"

    if status == "succeeded":
        if entry.get("redirect_chain") != [frozen["requested_url"], frozen["final_url"]]:
            return "a succeeded entry must record its own redirect chain"
        if entry.get("http_status") != 200:
            return "a succeeded entry must record status 200"
        for field in ("content_type", "content_encoding", "raw_reference"):
            value = entry.get(field)
            if not isinstance(value, str) or not value.strip():
                return f"a succeeded entry needs a non-blank {field}"
        count = entry.get("byte_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return "a succeeded entry needs a positive byte_count"
        digest = entry.get("content_sha256")
        if not isinstance(digest, str) or not re.fullmatch(SHA256_PATTERN, digest):
            return "a succeeded entry needs a lowercase 64-hex content_sha256"
        if entry.get("object_disposition") not in {"created", "reused"}:
            return "a succeeded entry needs a created/reused disposition"
        if not _is_utc_instant(entry.get("retrieval_timestamp")):
            return "a succeeded entry needs a real UTC retrieval_timestamp"
        if entry.get("failure_reason") is not None:
            return "a succeeded entry carries no failure reason"
        return None

    if entry.get("redirect_chain") != []:
        return f"a {status} entry records no redirect chain"
    for field in _NULL_ENTRY_FIELDS:
        if entry.get(field) is not None:
            return f"a {status} entry must leave {field} null"
    reason = entry.get("failure_reason")
    if status == "failed":
        if reason not in ENTRY_RECORDABLE_REASONS:
            return "a failed entry needs an entry-recordable failure reason"
    elif reason is not None:
        return "a not_attempted entry carries no failure reason"
    return None


def build_documentation_receipt(
    *,
    attempt_id: str,
    code_commit: str,
    run_created_at: str,
    adapter_contract_sha256: str,
    policy_contract_sha256: str,
    receipt_schema_sha256: str,
    retrieval_timestamp_mode: str,
    entries: list[dict[str, Any]],
    completion_status: str,
) -> dict[str, Any]:
    """Assemble the receipt, refusing anything the committed schema would reject.

    The collector must never be able to publish bytes its own schema rejects, so
    the builder enforces the same invariants rather than trusting its caller.
    Pure; performs no I/O.
    """
    if not isinstance(attempt_id, str) or not re.fullmatch(ATTEMPT_ID_PATTERN, attempt_id):
        _refuse("attempt_id does not match the locked pattern")
    if not isinstance(code_commit, str) or not code_commit.strip():
        _refuse("code_commit must be a non-blank string")
    if not _is_utc_instant(run_created_at):
        _refuse("run_created_at is not a real timezone-aware UTC instant")
    for label, digest in (
        ("adapter_contract_sha256", adapter_contract_sha256),
        ("policy_contract_sha256", policy_contract_sha256),
        ("receipt_schema_sha256", receipt_schema_sha256),
    ):
        if not isinstance(digest, str) or not re.fullmatch(SHA256_PATTERN, digest):
            _refuse(f"{label} is not a lowercase 64-hex digest")
    if retrieval_timestamp_mode != "caller_injected_request_start_utc_v1":
        _refuse("retrieval_timestamp_mode is not the locked value")
    if completion_status not in COMPLETION_STATUSES:
        _refuse("unknown completion status")

    if not isinstance(entries, list) or len(entries) != len(FROZEN_ENTRY_IDENTITIES):
        _refuse("the receipt must carry exactly three positional entries")
    for entry, frozen in zip(entries, FROZEN_ENTRY_IDENTITIES):
        violation = _entry_violations(entry, frozen)
        if violation is not None:
            _refuse(violation)

    sequence = tuple(entry["entry_status"] for entry in entries)
    if (completion_status, sequence) not in TERMINAL_SEQUENCES:
        _refuse("the status sequence describes a run that cannot have happened")

    return {
        "contract": RECEIPT_CONTRACT,
        "schema_version": "0.1.0",
        "attempt_id": attempt_id,
        "code_commit": code_commit,
        "run_created_at": run_created_at,
        "adapter_contract_sha256": adapter_contract_sha256,
        "policy_contract_sha256": policy_contract_sha256,
        "receipt_schema_sha256": receipt_schema_sha256,
        "retrieval_timestamp_mode": retrieval_timestamp_mode,
        "entries": list(entries),
        "completion_status": completion_status,
    }


def receipt_bytes(receipt: dict[str, Any]) -> bytes:
    """Canonical serialization, matching the repository's convention."""
    return canonical_json_bytes(receipt)
