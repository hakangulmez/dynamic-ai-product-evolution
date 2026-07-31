"""Documentation collection receipt v0.3.0: schema, loader and builder (ADR-039, E-C-D2).

**Why a successor rather than an edit.** ``@0.1.0`` and ``@0.2.0`` are both
committed and each is already instantiated by a live receipt. Their frozen route
URLs are ``const``-pinned inside their committed schema files -- 10 occurrences in
v0.1, 52 in v0.2 -- and each loader deep-compares its committed file against a
constructor that reads the route declaration. Re-freezing a route in place would
therefore make **both** committed schemas stop matching their own loaders, and
both live receipts would become unverifiable. So neither is touched: 0.3.0 is a
third contract that reads its routes from :mod:`documentation_routes`.

**What 0.3.0 changes, and what it does not.** Only the route identity and its
source move, plus the contract version. Every truthful-observation rule from
0.2.0 is preserved unchanged: the 20-field entry, the seven failure phases, the
20-reason phase map, the location/disposition binding under two unanchored
predicates, the three-constant ``request_chain`` pin, and every fail-closed
builder and loader guard. A drift test proves the two schemas are identical once
route strings and contract identity are substituted, so a future change to one
cannot silently diverge from the other.

**Still exactly one hop.** A second redirect may be observed and recorded as a
terminal observation; it is never followed.

**Recording is not authorizing.** ``request_chain`` is schema-pinned per frozen
entry to exactly three constant values, so an observed ``Location`` is
*structurally* incapable of entering it. That guarantee is checkable from the
schema alone, without trusting the collector.

**What an observed location is.** Exactly the adapter-exposed Python string
returned by the pinned ``httpx`` ``Headers.get("location")`` surface, before any
policy parsing, normalization, resolution, percent-decoding, truncation or
authorization comparison. It is **not** wire bytes: measured on httpx 0.28.1,
that surface decodes with ``iso-8859-1`` and joins duplicate field lines with
``", "``, so C0 controls and U+0080-U+00FF can appear and duplicate header-line
boundaries are not recoverable. The transcription policy below is sized to that
measured surface.

**Frozen identities are imported, not redeclared.** The route identities and
shared patterns come from the frozen 0.1.0 module, so this module holds no URL
literal at all and a third declaration that could drift never exists.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any

from .documentation_receipt import (
    ATTEMPT_ID_PATTERN,
    COMPLETION_STATUSES,
    ENTRY_RECORDABLE_REASONS,
    ENTRY_STATUSES,
    SCHEMA_DIALECT,
    SHA256_PATTERN,
    TERMINAL_SEQUENCES,
    UTC_INSTANT_PATTERN,
)
from .documentation_routes import FROZEN_ROUTE_IDENTITIES
from .errors import CollectionError
from .publication import canonical_json_bytes

__all__ = [
    "ENTRY_PROPERTIES_V3",
    "ENTRY_REQUIRED_V3",
    "FAILURE_PHASES",
    "LOCATION_DISPOSITIONS",
    "LOCATION_MAX_LENGTH",
    "NON_PRINTABLE_ASCII_PATTERN",
    "PRINTABLE_ASCII_REQUIRED_PATTERN",
    "RECEIPT_CONTRACT_V3",
    "RECEIPT_PROPERTIES_V3",
    "RECEIPT_REQUIRED_V3",
    "RECEIPT_SCHEMA_ID_V3",
    "REASON_PHASES",
    "RESPONSE_DISPOSITIONS",
    "SCHEMA_VERSION_V3",
    "build_documentation_receipt_v3",
    "classify_observed_location",
    "expected_receipt_schema_v3",
    "receipt_bytes_v3",
    "transcribable_location",
    "validate_receipt_schema_v3_bytes",
]

RECEIPT_CONTRACT_V3 = "documentation_collection_receipt@0.3.0"
RECEIPT_SCHEMA_ID_V3 = "documentation_collection_receipt.v3.schema.json"
SCHEMA_VERSION_V3 = "0.3.0"

# The seven phases an entry can be in when it refuses. Ordered by progress, so
# the position of a phase in this tuple states how far the entry actually got.
FAILURE_PHASES: tuple[str, ...] = (
    "entry_preflight",
    "redirect_request",
    "redirect_evaluation",
    "terminal_preflight",
    "terminal_request",
    "terminal_evaluation",
    "persistence",
)

# ``no_response`` and ``absent`` are deliberately distinct: collapsing "never
# asked" into "asked, got nothing" would reintroduce exactly the class of
# untruth this contract exists to remove.
LOCATION_DISPOSITIONS: tuple[str, ...] = (
    "no_response",
    "absent",
    "recorded",
    "rejected_oversize",
    "rejected_uncharacterizable",
)
# The subset available once a response was actually received.
RESPONSE_DISPOSITIONS: tuple[str, ...] = tuple(
    d for d in LOCATION_DISPOSITIONS if d != "no_response"
)

LOCATION_MAX_LENGTH = 2048
_PRINTABLE_MIN = 0x20
_PRINTABLE_MAX = 0x7E
_ASCII_SPACE = " "

# Two independent, **unanchored** predicates rather than one anchored pattern.
#
# JSON Schema ``pattern`` is a search, not a full match, and in the installed
# engine ``$`` also matches immediately before a final newline. An anchored
# ``^[\x20-\x7e]*[\x21-\x7e][\x20-\x7e]*$`` therefore accepted ``"x\n"`` under
# ``re.search`` -- measured -- while ``transcribable_location`` and the builder
# rejected it: a schema that was strictly weaker than the code it was supposed to
# mirror. Splitting the rule removes the anchor entirely:
#
#   * REQUIRED   proves at least one U+0021-U+007E character exists;
#   * FORBIDDEN, under ``not``, proves no character outside U+0020-U+007E exists.
#
# Neither depends on anchoring, so no end-of-string subtlety can weaken them, and
# both stay portable JSON Schema (no Python-only ``\Z``).
PRINTABLE_ASCII_REQUIRED_PATTERN = r"[\x21-\x7e]"
NON_PRINTABLE_ASCII_PATTERN = r"[^\x20-\x7e]"

REDIRECT_STATUSES_V3: tuple[int, ...] = (301, 308)
TERMINAL_STATUS_V3 = 200
_STATUS_MIN = 100
_STATUS_MAX = 599

# Every entry-recordable reason mapped to the phases in which it can truthfully
# be recorded. Exhaustive over ENTRY_RECORDABLE_REASONS; a drift test binds the
# two together so a new code cannot be added without a phase.
#
# A reason spans several phases when it is reachable from more than one point:
# the transport-level refusals are raised inside the adapter (no AdapterResponse
# escapes, so the phase is the *_request one) and also, for the identity check,
# by the policy with a response in hand (phase *_evaluation).
REASON_PHASES: dict[str, tuple[str, ...]] = {
    "retrieval_clock_failed": ("entry_preflight",),
    "retrieval_clock_invalid": ("entry_preflight",),
    # The adapter performs its own keylog check at the top of ``send_once``,
    # after the policy's precheck for that phase has already passed. A keylog
    # appearing in between is refused there, with the send already initiated and
    # no response received -- which is exactly what the ``*_request`` phases
    # mean, and is the same shape ``transport_failed`` already has. Omitting
    # those two phases made a reachable path unpublishable: the builder refused
    # the entry and the attempt was left with no terminal receipt at all.
    "tls_keylog_environment_present": (
        "entry_preflight",
        "redirect_request",
        "terminal_preflight",
        "terminal_request",
    ),
    "transport_timeout": ("redirect_request", "terminal_request"),
    "transport_failed": ("redirect_request", "terminal_request"),
    "response_request_identity_mismatch": (
        "redirect_request",
        "redirect_evaluation",
        "terminal_request",
        "terminal_evaluation",
    ),
    "direct_terminal_not_permitted": ("redirect_evaluation",),
    "redirect_status_invalid": ("redirect_evaluation",),
    "redirect_location_missing": ("redirect_evaluation",),
    "redirect_location_not_absolute": ("redirect_evaluation",),
    "redirect_location_mismatch": ("redirect_evaluation",),
    "entity_too_large": ("terminal_request",),
    "redirect_chain_too_long": ("terminal_evaluation",),
    "terminal_status_invalid": ("terminal_evaluation",),
    "content_type_invalid": ("terminal_evaluation",),
    "entity_empty": ("terminal_evaluation",),
    "attempt_byte_ceiling_exceeded": ("terminal_evaluation",),
    "content_object_corrupt": ("persistence",),
    "destination_exists": ("persistence",),
    "write_error": ("persistence",),
}

RECEIPT_REQUIRED_V3: frozenset[str] = frozenset(
    {
        "contract", "schema_version", "attempt_id", "code_commit", "run_created_at",
        "adapter_contract_sha256", "policy_contract_sha256", "receipt_schema_sha256",
        "retrieval_timestamp_mode", "entries", "completion_status",
    }
)
RECEIPT_PROPERTIES_V3: frozenset[str] = RECEIPT_REQUIRED_V3

# Twenty fields: the thirteen applicable v0.1 fields (``http_status`` removed),
# ``redirect_chain`` renamed to ``request_chain``, and seven observation fields.
ENTRY_REQUIRED_V3: frozenset[str] = frozenset(
    {
        "evidence_kind", "requested_url", "final_url", "entry_status",
        "request_chain", "content_type", "content_encoding", "byte_count",
        "content_sha256", "raw_reference", "object_disposition",
        "retrieval_timestamp", "failure_reason", "failure_phase",
        "redirect_observed_status", "redirect_observed_location",
        "redirect_observed_location_disposition", "terminal_observed_status",
        "terminal_observed_location", "terminal_observed_location_disposition",
    }
)
ENTRY_PROPERTIES_V3: frozenset[str] = ENTRY_REQUIRED_V3

# Payload fields that only a persisted object can justify.
_OBJECT_FIELDS: tuple[str, ...] = ("raw_reference", "object_disposition")
# Payload fields established once the terminal entity was accepted.
_ENTITY_FIELDS: tuple[str, ...] = (
    "content_type", "content_encoding", "byte_count", "content_sha256",
)
_REDIRECT_OBSERVED: tuple[str, ...] = (
    "redirect_observed_status", "redirect_observed_location",
)
_TERMINAL_OBSERVED: tuple[str, ...] = (
    "terminal_observed_status", "terminal_observed_location",
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


# --- the transcription policy -------------------------------------------------


def _printable_ascii(value: str) -> bool:
    return all(_PRINTABLE_MIN <= ord(ch) <= _PRINTABLE_MAX for ch in value)


def _ascii_space_only(value: str) -> bool:
    """True for a non-empty run of U+0020 alone.

    Deliberately not ``str.strip()``: bare ``strip`` removes ``\\t``, ``\\n``,
    ``\\r``, ``\\x0b``, ``\\x0c`` and every Unicode whitespace codepoint, which
    would classify a control- or NBSP-bearing value as ``absent`` when the locked
    order requires ``rejected_uncharacterizable``. Only U+0020 counts here.
    """
    return bool(value) and all(ch == _ASCII_SPACE for ch in value)


def transcribable_location(value: Any) -> bool:
    """Exactly the values ``classify_observed_location`` may mark ``recorded``.

    Shared by the classifier, the builder and the committed schema's predicates,
    so the three cannot disagree about what ``recorded`` is allowed to mean.
    """
    return (
        isinstance(value, str)
        and value != ""
        and len(value) <= LOCATION_MAX_LENGTH
        and _printable_ascii(value)
        and not _ascii_space_only(value)
    )


def classify_observed_location(value: Any, *, response_received: bool) -> tuple[str | None, str]:
    """Decide whether an adapter-exposed ``Location`` string can be transcribed.

    Returns ``(recorded_value_or_None, disposition)``. The value is **never**
    truncated, split, normalized, resolved or decoded: a shortened URL is a
    fabricated artifact, so an untranscribable value is refused outright and the
    disposition says why.

    Ordering is deliberate -- length before charset -- so an over-long value is
    reported as oversize rather than as whatever its first stray byte suggests.
    Classification is independent of authorization: a value may be ``recorded``
    and still refused by the route grammar, and vice versa.

    The two outputs are **bound**: a non-null value implies ``recorded``, and
    every other disposition implies null. Nothing may be half-recorded.
    """
    if not response_received:
        return None, "no_response"
    if value is None or value == "":
        return None, "absent"
    if not isinstance(value, str):
        # The adapter declares ``str | None``; anything else is uncharacterizable
        # rather than coerced into the receipt.
        return None, "rejected_uncharacterizable"
    if len(value) > LOCATION_MAX_LENGTH:
        return None, "rejected_oversize"
    if not _printable_ascii(value):
        # Charset is decided **before** the space-only rule. Checking emptiness
        # with a bare ``strip()`` first classified TAB, LF, CR, NBSP and U+2003
        # as ``absent``, hiding forbidden characters behind a benign disposition.
        return None, "rejected_uncharacterizable"
    if _ascii_space_only(value):
        # Every character is now known to be printable ASCII, so this is a run of
        # U+0020 alone: a field that arrived carrying no target. Reported absent,
        # because recording it would claim an observation that names nothing.
        return None, "absent"
    return value, "recorded"


# --- the single source of truth ----------------------------------------------


def _nulls(*names: str) -> dict[str, Any]:
    return {name: {"const": None} for name in names}


def _redirect_accepted(final_url: str) -> dict[str, Any]:
    """The redirect facts implied by having got past the frozen-pair check."""
    return {
        "redirect_observed_status": {"enum": list(REDIRECT_STATUSES_V3)},
        "redirect_observed_location": {"const": final_url},
        "redirect_observed_location_disposition": {"const": "recorded"},
    }


def _phase_rules(requested: str, final: str) -> dict[str, dict[str, Any]]:
    """Per-phase payload shape. Each phase states exactly what had been established."""
    no_terminal = {
        **_nulls(*_TERMINAL_OBSERVED),
        "terminal_observed_location_disposition": {"const": "no_response"},
    }
    no_redirect = {
        **_nulls(*_REDIRECT_OBSERVED),
        "redirect_observed_location_disposition": {"const": "no_response"},
    }
    dated = {"retrieval_timestamp": {"type": "string", "pattern": UTC_INSTANT_PATTERN}}
    empty_entity = _nulls(*_ENTITY_FIELDS)
    return {
        # No send was issued. The clock may or may not have been read, so the
        # timestamp stays nullable here and only here.
        "entry_preflight": {
            "request_chain": {"const": []},
            **no_redirect,
            **no_terminal,
            **empty_entity,
        },
        # Send one was initiated; no usable response came back.
        "redirect_request": {
            "request_chain": {"const": [requested]},
            **dated,
            **no_redirect,
            **no_terminal,
            **empty_entity,
        },
        # Send one answered and the response was evaluated and refused.
        "redirect_evaluation": {
            "request_chain": {"const": [requested]},
            **dated,
            "redirect_observed_status": {
                "type": "integer", "minimum": _STATUS_MIN, "maximum": _STATUS_MAX,
            },
            "redirect_observed_location_disposition": {
                "enum": list(RESPONSE_DISPOSITIONS)
            },
            **no_terminal,
            **empty_entity,
        },
        # The redirect was accepted; send two had not yet been issued.
        "terminal_preflight": {
            "request_chain": {"const": [requested]},
            **dated,
            **_redirect_accepted(final),
            **no_terminal,
            **empty_entity,
        },
        # Send two was initiated; no usable response came back.
        "terminal_request": {
            "request_chain": {"const": [requested, final]},
            **dated,
            **_redirect_accepted(final),
            **no_terminal,
            **empty_entity,
        },
        # Send two answered and the response was evaluated and refused.
        "terminal_evaluation": {
            "request_chain": {"const": [requested, final]},
            **dated,
            **_redirect_accepted(final),
            "terminal_observed_status": {
                "type": "integer", "minimum": _STATUS_MIN, "maximum": _STATUS_MAX,
            },
            "terminal_observed_location_disposition": {
                "enum": list(RESPONSE_DISPOSITIONS)
            },
            **empty_entity,
        },
        # The entity was accepted and storage refused it. The entity facts are
        # real and are recorded; no object exists, so its fields stay null.
        "persistence": {
            "request_chain": {"const": [requested, final]},
            **dated,
            **_redirect_accepted(final),
            "terminal_observed_status": {"const": TERMINAL_STATUS_V3},
            "terminal_observed_location_disposition": {
                "enum": list(RESPONSE_DISPOSITIONS)
            },
            "content_type": {"type": "string", "minLength": 1},
            "content_encoding": {"type": "string", "minLength": 1},
            "byte_count": {"type": "integer", "minimum": 1},
            "content_sha256": {"type": "string", "pattern": SHA256_PATTERN},
        },
    }


def _entry_schema_v3(entry: dict[str, str]) -> dict[str, Any]:
    """One positionally frozen entry with its status- and phase-conditioned rules."""
    requested, final = entry["requested_url"], entry["final_url"]

    succeeded = {
        "properties": {
            "request_chain": {"const": [requested, final]},
            "content_type": {"type": "string", "minLength": 1},
            "content_encoding": {"type": "string", "minLength": 1},
            "byte_count": {"type": "integer", "minimum": 1},
            "content_sha256": {"type": "string", "pattern": SHA256_PATTERN},
            "raw_reference": {"type": "string", "minLength": 1},
            "object_disposition": {"enum": ["created", "reused"]},
            "retrieval_timestamp": {"type": "string", "pattern": UTC_INSTANT_PATTERN},
            "failure_reason": {"const": None},
            "failure_phase": {"const": None},
            **_redirect_accepted(final),
            "terminal_observed_status": {"const": TERMINAL_STATUS_V3},
            # A 200 may legally carry a Location, so this stays nullable rather
            # than pinned to absent. Truth outranks convenience.
            "terminal_observed_location_disposition": {
                "enum": list(RESPONSE_DISPOSITIONS)
            },
        }
    }
    not_attempted = {
        "properties": {
            "request_chain": {"const": []},
            **_nulls(
                *_ENTITY_FIELDS, *_OBJECT_FIELDS, "retrieval_timestamp",
                *_REDIRECT_OBSERVED, *_TERMINAL_OBSERVED,
            ),
            "failure_reason": {"const": None},
            "failure_phase": {"const": None},
            "redirect_observed_location_disposition": {"const": "no_response"},
            "terminal_observed_location_disposition": {"const": "no_response"},
        }
    }
    failed = {
        "properties": {
            "failure_reason": {"type": "string", "enum": list(ENTRY_RECORDABLE_REASONS)},
            "failure_phase": {"type": "string", "enum": list(FAILURE_PHASES)},
            # No entry that failed ever produced a stored object.
            **_nulls(*_OBJECT_FIELDS),
        }
    }

    branches = [
        {
            "if": {
                "properties": {"entry_status": {"const": status}},
                "required": ["entry_status"],
            },
            "then": rules,
        }
        for status, rules in (
            ("succeeded", succeeded),
            ("not_attempted", not_attempted),
            ("failed", failed),
        )
    ]
    branches.extend(
        {
            "if": {
                "properties": {"failure_phase": {"const": phase}},
                "required": ["failure_phase"],
            },
            "then": {"properties": rules},
        }
        for phase, rules in _phase_rules(requested, final).items()
    )
    # Each observed location is bound to its own disposition in both directions,
    # under every status and phase. Without this the schema accepted a null
    # location claiming ``recorded``, a non-null location claiming ``absent``,
    # and a non-printable value claiming ``recorded`` -- three ways to describe
    # an observation that did not happen.
    branches.extend(
        {
            "if": {
                "properties": {f"{pair}_observed_location_disposition": {"const": "recorded"}},
                "required": [f"{pair}_observed_location_disposition"],
            },
            "then": {
                "properties": {
                    f"{pair}_observed_location": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": LOCATION_MAX_LENGTH,
                        # Unanchored and independent: one proves a non-space
                        # printable exists, the other that nothing outside
                        # printable ASCII does. See the constants above for why
                        # a single anchored pattern was not sufficient.
                        "pattern": PRINTABLE_ASCII_REQUIRED_PATTERN,
                        "not": {"pattern": NON_PRINTABLE_ASCII_PATTERN},
                    }
                }
            },
            "else": {"properties": {f"{pair}_observed_location": {"const": None}}},
        }
        for pair in ("redirect", "terminal")
    )

    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(ENTRY_REQUIRED_V3),
        "properties": {
            "evidence_kind": {"const": entry["evidence_kind"]},
            "requested_url": {"const": requested},
            "final_url": {"const": final},
            "entry_status": {"type": "string", "enum": list(ENTRY_STATUSES)},
            # The structural non-authorization guarantee: exactly three constant
            # values, all built from this entry's own frozen pair. An observed
            # Location cannot enter this field under any status or phase.
            "request_chain": {
                "oneOf": [
                    {"const": []},
                    {"const": [requested]},
                    {"const": [requested, final]},
                ]
            },
            "content_type": {"type": ["string", "null"], "minLength": 1},
            "content_encoding": {"type": ["string", "null"], "minLength": 1},
            "byte_count": {"type": ["integer", "null"], "minimum": 1},
            "content_sha256": {"type": ["string", "null"], "pattern": SHA256_PATTERN},
            "raw_reference": {"type": ["string", "null"], "minLength": 1},
            "object_disposition": {"enum": ["created", "reused", None]},
            "retrieval_timestamp": {
                "type": ["string", "null"], "pattern": UTC_INSTANT_PATTERN,
            },
            "failure_reason": {"enum": list(ENTRY_RECORDABLE_REASONS) + [None]},
            "failure_phase": {"enum": list(FAILURE_PHASES) + [None]},
            "redirect_observed_status": {
                "type": ["integer", "null"], "minimum": _STATUS_MIN, "maximum": _STATUS_MAX,
            },
            "redirect_observed_location": {
                "type": ["string", "null"], "minLength": 1, "maxLength": LOCATION_MAX_LENGTH,
            },
            "redirect_observed_location_disposition": {
                "type": "string", "enum": list(LOCATION_DISPOSITIONS),
            },
            "terminal_observed_status": {
                "type": ["integer", "null"], "minimum": _STATUS_MIN, "maximum": _STATUS_MAX,
            },
            "terminal_observed_location": {
                "type": ["string", "null"], "minLength": 1, "maxLength": LOCATION_MAX_LENGTH,
            },
            "terminal_observed_location_disposition": {
                "type": "string", "enum": list(LOCATION_DISPOSITIONS),
            },
        },
        "allOf": branches,
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


def expected_receipt_schema_v3() -> dict[str, Any]:
    """The complete locked 0.3.0 schema. The committed file is generated from this."""
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": RECEIPT_SCHEMA_ID_V3,
        "title": RECEIPT_CONTRACT_V3,
        "comment": (
            "ADR-039 (E-C-D2). Successor to documentation_collection_receipt@0.2.0, "
            "which is never modified because a live receipt already instantiates it "
            "and its frozen routes are const-pinned inside its committed schema. Only "
            "the E1 route identity and its source change: the E1 final is the Location "
            "observed by attempt docattempt-c4082dd835f2f5228669487f50ca2308, carried "
            "as a hypothesis under one separately governed test, not as validated "
            "content. E2 and E3 are copied unchanged; no route is inferred by pattern. "
            "Every 0.2.0 observation rule is preserved: a failed entry records what was "
            "actually established before the refusal -- failure_phase, the request-start "
            "timestamp, the observed HTTP status, and the adapter-exposed Location "
            "string -- instead of being blanked. request_chain lists only URLs this "
            "collector initiated, pinned per entry to three constants so an observed "
            "Location can never enter it and is never followed merely because it was "
            "observed. An observed location is the exact adapter-exposed Python string "
            "returned by httpx.Headers.get('location'): it is not wire bytes and does "
            "not preserve duplicate header-line boundaries, which that surface joins. "
            "It is either recorded unchanged or refused with a disposition that says "
            "why -- never truncated, and never present without a recorded "
            "disposition. The receipt owns "
            "retrieval_status only; whether the bytes carry the required official "
            "claim belongs to documentation_evidence_validation@0.1.0."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": sorted(RECEIPT_REQUIRED_V3),
        "properties": {
            "contract": {"const": RECEIPT_CONTRACT_V3},
            "schema_version": {"const": SCHEMA_VERSION_V3},
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
                "prefixItems": [_entry_schema_v3(e) for e in FROZEN_ROUTE_IDENTITIES],
                "items": False,
            },
            "completion_status": {"type": "string", "enum": list(COMPLETION_STATUSES)},
        },
        "oneOf": [_sequence_branch(c, s) for c, s in TERMINAL_SEQUENCES],
    }


class _DuplicateMemberError(ValueError):
    """A JSON object repeated a member name; the parser would hide one value."""


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` that refuses repeated names at any nesting level."""
    seen: set[str] = set()
    for name, _ in pairs:
        if name in seen:
            raise _DuplicateMemberError(name)
        seen.add(name)
    return dict(pairs)


def _json_exact_equal(left: Any, right: Any) -> bool:
    """Recursive, JSON-type-exact comparison.

    Ordinary ``==`` is not type-exact for JSON: ``True == 1`` and ``False == 0``
    in Python, so ``minLength: true`` compares equal to ``minLength: 1`` and
    ``additionalProperties: 0`` to ``false``; ``3 == 3.0`` erases the
    integer/number distinction. Type identity is checked before value equality,
    with ``bool`` separated from ``int`` by ``type(...) is not type(...)``.
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


def validate_receipt_schema_v3_bytes(schema_bytes: Any) -> str:
    """Prove the bytes are the locked 0.3.0 schema, semantically, and return the digest.

    Same closure as the 0.1.0 loader: a recursive JSON-type-exact comparison
    against :func:`expected_receipt_schema_v3`, duplicate member names refused at
    any depth, and ``receipt_schema_contract_mismatch`` reserved for a shape that
    actually *names* another contract with a non-blank string const. Formatting
    is outside the comparison; the digest is always of the exact bytes supplied.
    """
    if not isinstance(schema_bytes, (bytes, bytearray)) or not schema_bytes:
        _refuse("receipt schema bytes are required")
    try:
        schema = json.loads(
            bytes(schema_bytes).decode("utf-8"),
            object_pairs_hook=_reject_duplicate_members,
        )
    except _DuplicateMemberError:
        _refuse("the receipt schema repeats a member name")
    except (UnicodeDecodeError, ValueError):
        _refuse("receipt schema bytes are not valid UTF-8 JSON")
    if not isinstance(schema, dict):
        _refuse("the receipt schema must be a JSON object")

    properties = schema.get("properties")
    if isinstance(properties, dict):
        contract = properties.get("contract")
        if isinstance(contract, dict):
            declared = contract.get("const")
            if (
                isinstance(declared, str)
                and not isinstance(declared, bool)
                and declared.strip()
                and declared != RECEIPT_CONTRACT_V3
            ):
                _refuse(
                    "properties.contract.const identifies a different contract",
                    "receipt_schema_contract_mismatch",
                )

    required = schema.get("required")
    if isinstance(required, list) and all(isinstance(name, str) for name in required):
        if len(required) != len(set(required)):
            _refuse("the receipt schema required list carries duplicates")

    if not _json_exact_equal(schema, expected_receipt_schema_v3()):
        _refuse("the receipt schema does not match the locked definition")
    return sha256(bytes(schema_bytes)).hexdigest()


# --- the builder --------------------------------------------------------------


def _is_status(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and _STATUS_MIN <= value <= _STATUS_MAX
    )


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _entry_violations_v3(entry: Any, frozen: dict[str, str]) -> str | None:
    """Refuse anything the committed schema would refuse, and the reason/phase pairing.

    The schema pins phase to payload; the builder additionally pins reason to
    phase, so a truthful-looking record that names an impossible combination --
    ``write_error`` at ``entry_preflight``, say -- cannot be published either.
    """
    if not isinstance(entry, dict) or frozenset(entry) != ENTRY_PROPERTIES_V3:
        return "an entry does not carry exactly the locked property set"
    for field, expected in frozen.items():
        if entry.get(field) != expected:
            return f"an entry does not carry its frozen {field}"
    status = entry.get("entry_status")
    if status not in ENTRY_STATUSES:
        return "unknown entry status"

    requested, final = frozen["requested_url"], frozen["final_url"]
    chain = entry.get("request_chain")
    if chain not in ([], [requested], [requested, final]):
        return "request_chain is not one of this entry's three permitted values"

    for field in (
        "redirect_observed_location_disposition",
        "terminal_observed_location_disposition",
    ):
        if entry.get(field) not in LOCATION_DISPOSITIONS:
            return f"{field} is not a declared disposition"
    # The location/disposition binding, enforced identically to the schema: a
    # value may be present only when its disposition says it was recorded, and a
    # recorded disposition must name a value the classifier could have produced.
    for pair in ("redirect", "terminal"):
        value = entry.get(f"{pair}_observed_location")
        disposition = entry.get(f"{pair}_observed_location_disposition")
        if disposition == "recorded":
            if not transcribable_location(value):
                return f"{pair}_observed_location is recorded but is not transcribable"
        elif value is not None:
            return f"{pair}_observed_location must be null unless it was recorded"
    for field in ("redirect_observed_status", "terminal_observed_status"):
        value = entry.get(field)
        if value is not None and not _is_status(value):
            return f"{field} is neither null nor a real HTTP status"

    if status == "succeeded":
        return _succeeded_violations(entry, requested, final)
    if status == "not_attempted":
        return _blank_violations(entry, status)
    return _failed_violations(entry)


def _succeeded_violations(entry: dict[str, Any], requested: str, final: str) -> str | None:
    if entry.get("request_chain") != [requested, final]:
        return "a succeeded entry must record its own full request chain"
    for field in ("content_type", "content_encoding", "raw_reference"):
        if not _nonblank(entry.get(field)):
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
    if entry.get("failure_reason") is not None or entry.get("failure_phase") is not None:
        return "a succeeded entry carries no failure reason or phase"
    if entry.get("redirect_observed_status") not in REDIRECT_STATUSES_V3:
        return "a succeeded entry must record the accepted redirect status"
    if entry.get("redirect_observed_location") != final:
        return "a succeeded entry must record the accepted Location"
    if entry.get("redirect_observed_location_disposition") != "recorded":
        return "a succeeded entry must record the accepted Location as recorded"
    if entry.get("terminal_observed_status") != TERMINAL_STATUS_V3:
        return "a succeeded entry must record terminal status 200"
    if entry.get("terminal_observed_location_disposition") not in RESPONSE_DISPOSITIONS:
        return "a succeeded entry saw a terminal response"
    return None


def _blank_violations(entry: dict[str, Any], status: str) -> str | None:
    if entry.get("request_chain") != []:
        return f"a {status} entry initiated no request"
    for field in (*_ENTITY_FIELDS, *_OBJECT_FIELDS, "retrieval_timestamp",
                  *_REDIRECT_OBSERVED, *_TERMINAL_OBSERVED):
        if entry.get(field) is not None:
            return f"a {status} entry must leave {field} null"
    if entry.get("failure_reason") is not None or entry.get("failure_phase") is not None:
        return f"a {status} entry carries no failure reason or phase"
    for field in (
        "redirect_observed_location_disposition",
        "terminal_observed_location_disposition",
    ):
        if entry.get(field) != "no_response":
            return f"a {status} entry received no response"
    return None


def _failed_violations(entry: dict[str, Any]) -> str | None:
    reason = entry.get("failure_reason")
    phase = entry.get("failure_phase")
    if reason not in ENTRY_RECORDABLE_REASONS:
        return "a failed entry needs an entry-recordable failure reason"
    if phase not in FAILURE_PHASES:
        return "a failed entry needs a declared failure phase"
    if phase not in REASON_PHASES[reason]:
        return "a failed entry names a reason that cannot arise in that phase"
    for field in _OBJECT_FIELDS:
        if entry.get(field) is not None:
            return f"a failed entry stored no object, so {field} must be null"

    index = FAILURE_PHASES.index(phase)
    requested_only = FAILURE_PHASES.index("terminal_request")
    chain = entry.get("request_chain")
    if phase == "entry_preflight":
        expected_chain: list[str] = []
    elif index < requested_only:
        expected_chain = [entry["requested_url"]]
    else:
        expected_chain = [entry["requested_url"], entry["final_url"]]
    if chain != expected_chain:
        return "a failed entry does not record the request chain its phase implies"

    if phase == "entry_preflight":
        if entry.get("retrieval_timestamp") is not None and not _is_utc_instant(
            entry.get("retrieval_timestamp")
        ):
            return "a preflight failure carries either null or a real UTC instant"
    elif not _is_utc_instant(entry.get("retrieval_timestamp")):
        return "a failure after the clock was read must record its instant"

    saw_redirect_response = index >= FAILURE_PHASES.index("redirect_evaluation")
    if saw_redirect_response:
        if not _is_status(entry.get("redirect_observed_status")):
            return "a failure after send one answered must record its status"
        if entry.get("redirect_observed_location_disposition") == "no_response":
            return "a failure after send one answered saw a response"
    else:
        for field in _REDIRECT_OBSERVED:
            if entry.get(field) is not None:
                return f"a failure before send one answered must leave {field} null"
        if entry.get("redirect_observed_location_disposition") != "no_response":
            return "a failure before send one answered received no response"

    if index >= FAILURE_PHASES.index("terminal_preflight"):
        if entry.get("redirect_observed_status") not in REDIRECT_STATUSES_V3:
            return "a failure past the redirect must record the accepted status"
        if entry.get("redirect_observed_location") != entry["final_url"]:
            return "a failure past the redirect must record the accepted Location"

    saw_terminal_response = index >= FAILURE_PHASES.index("terminal_evaluation")
    if saw_terminal_response:
        if not _is_status(entry.get("terminal_observed_status")):
            return "a failure after send two answered must record its status"
        if entry.get("terminal_observed_location_disposition") == "no_response":
            return "a failure after send two answered saw a response"
    else:
        for field in _TERMINAL_OBSERVED:
            if entry.get(field) is not None:
                return f"a failure before send two answered must leave {field} null"
        if entry.get("terminal_observed_location_disposition") != "no_response":
            return "a failure before send two answered received no response"

    if phase == "persistence":
        if entry.get("terminal_observed_status") != TERMINAL_STATUS_V3:
            return "a persistence failure accepted a 200 entity"
        for field in ("content_type", "content_encoding"):
            if not _nonblank(entry.get(field)):
                return f"a persistence failure needs a non-blank {field}"
        count = entry.get("byte_count")
        if not isinstance(count, int) or isinstance(count, bool) or count < 1:
            return "a persistence failure needs a positive byte_count"
        digest = entry.get("content_sha256")
        if not isinstance(digest, str) or not re.fullmatch(SHA256_PATTERN, digest):
            return "a persistence failure needs a lowercase 64-hex content_sha256"
    else:
        for field in _ENTITY_FIELDS:
            if entry.get(field) is not None:
                return f"a {phase} failure accepted no entity, so {field} must be null"
    return None


def build_documentation_receipt_v3(
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
    """Assemble the 0.3.0 receipt, refusing anything the committed schema would reject.

    The collector must never be able to publish bytes its own schema rejects, so
    the builder enforces the same invariants rather than trusting its caller, and
    additionally enforces the reason/phase pairing the schema leaves open. Pure;
    performs no I/O.
    """
    if not isinstance(attempt_id, str) or not re.fullmatch(ATTEMPT_ID_PATTERN, attempt_id):
        _refuse("attempt_id does not match the locked pattern")
    if not _nonblank(code_commit):
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

    if not isinstance(entries, list) or len(entries) != len(FROZEN_ROUTE_IDENTITIES):
        _refuse("the receipt must carry exactly three positional entries")
    for entry, frozen in zip(entries, FROZEN_ROUTE_IDENTITIES):
        violation = _entry_violations_v3(entry, frozen)
        if violation is not None:
            _refuse(violation)

    sequence = tuple(entry["entry_status"] for entry in entries)
    if (completion_status, sequence) not in TERMINAL_SEQUENCES:
        _refuse("the status sequence describes a run that cannot have happened")

    return {
        "contract": RECEIPT_CONTRACT_V3,
        "schema_version": SCHEMA_VERSION_V3,
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


def receipt_bytes_v3(receipt: dict[str, Any]) -> bytes:
    """Canonical serialization, matching the repository's convention."""
    return canonical_json_bytes(receipt)
