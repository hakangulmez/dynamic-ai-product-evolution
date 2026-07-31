"""Documentation collection receipt v0.4.0: schema, loader and builder (ADR-040, E-C-D3).

**Why a successor rather than an edit.** ``@0.1.0``, ``@0.2.0`` and ``@0.3.0`` are
all committed, two of them are instantiated by live receipts, and every one pins
its frozen routes as ``const`` inside its committed schema file. Each loader
deep-compares that file against a constructor which reads the route declaration,
so re-freezing a route in place would make the committed schema stop matching its
own loader and the live receipts unverifiable. Under the v0.4 standard every
governed layer -- receipt, schema, routes and now policy source -- succeeds rather
than mutates, so an archived receipt can be re-verified against the exact sources
that produced it.

**What 0.4.0 changes: route kinds become explicit.** v0.1-v0.3 could only express
"exactly one redirect hop", which happened to be expressible because every frozen
pair's two URLs differed. E3 is now a **direct** route whose requested and final
URLs are identical. Two consequences:

* ``route_kind`` is declared per entry (``direct`` | ``redirect_once``) and pinned
  as a ``const``. Nothing is inferred from URL inequality.
* Observation slots are named by **send ordinal**, not by role. Calling a direct
  route's only send "terminal" while its failure phases stayed named "redirect"
  would describe a hop that never happened -- exactly the misleading redirect-only
  vocabulary this contract exists to remove. ``redirect_observed_*`` and
  ``terminal_observed_*`` become ``send1_observed_*`` and ``send2_observed_*``,
  which are true under both kinds.

**A direct route issues one send.** An initial 200 is its only success path. A 3xx
is **recorded** -- status, and the adapter-exposed ``Location`` under the unchanged
transcription policy -- and refused with ``direct_redirect_not_permitted``. It is
never followed. The schema pins the three ``send2_*`` phases unreachable for a
direct entry, so a second send cannot be described even by a malformed builder.

**Everything else from 0.3.0 is preserved unchanged**: the seven-phase model (with
ordinal names), the location/disposition binding under two unanchored predicates,
``request_chain`` pinned to per-entry constants so an observed value can never
enter it, the four truthful terminal sequences, and every fail-closed builder and
loader guard.
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
    ENTRY_STATUSES,
    FAILURE_REASONS,
    SCHEMA_DIALECT,
    SHA256_PATTERN,
    TERMINAL_SEQUENCES,
    UTC_INSTANT_PATTERN,
)
from .documentation_routes_v4 import FROZEN_ROUTE_IDENTITIES_V4
from .errors import CollectionError
from .publication import canonical_json_bytes

__all__ = [
    "DIRECT_PHASES",
    "ENTRY_PROPERTIES_V4",
    "ENTRY_RECORDABLE_REASONS_V4",
    "ENTRY_REQUIRED_V4",
    "FAILURE_PHASES",
    "FAILURE_REASONS_V4",
    "LOCATION_DISPOSITIONS",
    "LOCATION_MAX_LENGTH",
    "NON_PRINTABLE_ASCII_PATTERN",
    "PRINTABLE_ASCII_REQUIRED_PATTERN",
    "RECEIPT_CONTRACT_V4",
    "RECEIPT_PROPERTIES_V4",
    "RECEIPT_REQUIRED_V4",
    "RECEIPT_SCHEMA_ID_V4",
    "REASON_PHASES",
    "REDIRECT_ONCE_PHASES",
    "RESPONSE_DISPOSITIONS",
    "ROUTE_KIND_PHASES",
    "ROUTE_KIND_REASONS",
    "SCHEMA_VERSION_V4",
    "build_documentation_receipt_v4",
    "classify_observed_location",
    "expected_receipt_schema_v4",
    "receipt_bytes_v4",
    "transcribable_location",
    "validate_receipt_schema_v4_bytes",
]

RECEIPT_CONTRACT_V4 = "documentation_collection_receipt@0.4.0"
RECEIPT_SCHEMA_ID_V4 = "documentation_collection_receipt.v4.schema.json"
SCHEMA_VERSION_V4 = "0.4.0"

# Seven phases, named by send ordinal so they stay true under both route kinds.
# Ordered by progress: a phase's position states how far the entry actually got.
FAILURE_PHASES: tuple[str, ...] = (
    "entry_preflight",
    "send1_request",
    "send1_evaluation",
    "send2_preflight",
    "send2_request",
    "send2_evaluation",
    "persistence",
)
# A direct route has one send, so the three send2_* phases are unreachable for it.
DIRECT_PHASES: tuple[str, ...] = (
    "entry_preflight",
    "send1_request",
    "send1_evaluation",
    "persistence",
)
REDIRECT_ONCE_PHASES: tuple[str, ...] = FAILURE_PHASES
ROUTE_KIND_PHASES: dict[str, tuple[str, ...]] = {
    "direct": DIRECT_PHASES,
    "redirect_once": REDIRECT_ONCE_PHASES,
}

# ``no_response`` and ``absent`` stay distinct: collapsing "never asked" into
# "asked, got nothing" would reintroduce the untruth ADR-038 removed.
LOCATION_DISPOSITIONS: tuple[str, ...] = (
    "no_response",
    "absent",
    "recorded",
    "rejected_oversize",
    "rejected_uncharacterizable",
)
RESPONSE_DISPOSITIONS: tuple[str, ...] = tuple(
    d for d in LOCATION_DISPOSITIONS if d != "no_response"
)

LOCATION_MAX_LENGTH = 2048
_PRINTABLE_MIN = 0x20
_PRINTABLE_MAX = 0x7E
_ASCII_SPACE = " "

# Two independent, unanchored predicates rather than one anchored pattern. JSON
# Schema ``pattern`` is a search, and in the installed engine ``$`` also matches
# immediately before a final newline, so an anchored rule accepted ``"x\n"`` while
# the builder rejected it. Neither predicate below depends on anchoring, and both
# stay portable JSON Schema (no Python-only ``\Z``).
PRINTABLE_ASCII_REQUIRED_PATTERN = r"[\x21-\x7e]"
NON_PRINTABLE_ASCII_PATTERN = r"[^\x20-\x7e]"

REDIRECT_STATUSES_V4: tuple[int, ...] = (301, 308)
TERMINAL_STATUS_V4 = 200
_STATUS_MIN = 100
_STATUS_MAX = 599

# 0.4.0 adds exactly one reason: a direct route that answered with a redirect.
FAILURE_REASONS_V4: tuple[str, ...] = tuple(
    sorted(set(FAILURE_REASONS) | {"direct_redirect_not_permitted"})
)

# Reasons that can only arise before the attempt root exists, or only while
# publishing the receipt itself. Neither can truthfully appear inside an entry of
# a receipt that was successfully published.
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
ENTRY_RECORDABLE_REASONS_V4: tuple[str, ...] = tuple(
    reason for reason in FAILURE_REASONS_V4 if reason not in _NON_ENTRY_REASONS
)

# Reasons that describe a hop, and therefore cannot arise on a direct route.
_REDIRECT_ONLY_REASONS: frozenset[str] = frozenset(
    {
        "direct_terminal_not_permitted",
        "redirect_status_invalid",
        "redirect_location_missing",
        "redirect_location_not_absolute",
        "redirect_location_mismatch",
        "redirect_chain_too_long",
    }
)
# ... and the converse: only a direct route can be answered by a forbidden 3xx.
_DIRECT_ONLY_REASONS: frozenset[str] = frozenset({"direct_redirect_not_permitted"})

ROUTE_KIND_REASONS: dict[str, tuple[str, ...]] = {
    "direct": tuple(
        r for r in ENTRY_RECORDABLE_REASONS_V4 if r not in _REDIRECT_ONLY_REASONS
    ),
    "redirect_once": tuple(
        r for r in ENTRY_RECORDABLE_REASONS_V4 if r not in _DIRECT_ONLY_REASONS
    ),
}

# Every entry-recordable reason mapped to the phases in which it can truthfully be
# recorded, as a union across route kinds. The admissible set for a given entry is
# the intersection of this map with that entry's ROUTE_KIND_PHASES, which the
# schema pins per positional entry and the builder enforces independently.
#
# A reason spans several phases when it is reachable from more than one point: the
# transport-level refusals are raised inside the adapter (no AdapterResponse
# escapes, so the phase is the *_request one) and also, for the identity check, by
# the policy with a response in hand (phase *_evaluation).
REASON_PHASES: dict[str, tuple[str, ...]] = {
    "retrieval_clock_failed": ("entry_preflight",),
    "retrieval_clock_invalid": ("entry_preflight",),
    # The adapter rechecks the keylog at the top of ``send_once``, after the
    # policy's precheck for that phase has passed. A keylog appearing in between
    # is refused there, with the send initiated and no response received.
    "tls_keylog_environment_present": (
        "entry_preflight",
        "send1_request",
        "send2_preflight",
        "send2_request",
    ),
    "transport_timeout": ("send1_request", "send2_request"),
    "transport_failed": ("send1_request", "send2_request"),
    "response_request_identity_mismatch": (
        "send1_request",
        "send1_evaluation",
        "send2_request",
        "send2_evaluation",
    ),
    # redirect_once only: a 200 at send 1 is not the authorized route.
    "direct_terminal_not_permitted": ("send1_evaluation",),
    # direct only: a 3xx at send 1 is recorded and refused, never followed.
    "direct_redirect_not_permitted": ("send1_evaluation",),
    "redirect_status_invalid": ("send1_evaluation",),
    "redirect_location_missing": ("send1_evaluation",),
    "redirect_location_not_absolute": ("send1_evaluation",),
    "redirect_location_mismatch": ("send1_evaluation",),
    # Raised inside the adapter while iterating the terminal body: send 1 for a
    # direct route, send 2 for a redirect_once route.
    "entity_too_large": ("send1_request", "send2_request"),
    "redirect_chain_too_long": ("send2_evaluation",),
    "terminal_status_invalid": ("send1_evaluation", "send2_evaluation"),
    "content_type_invalid": ("send1_evaluation", "send2_evaluation"),
    "entity_empty": ("send1_evaluation", "send2_evaluation"),
    "attempt_byte_ceiling_exceeded": ("send1_evaluation", "send2_evaluation"),
    "content_object_corrupt": ("persistence",),
    "destination_exists": ("persistence",),
    "write_error": ("persistence",),
}

RECEIPT_REQUIRED_V4: frozenset[str] = frozenset(
    {
        "contract", "schema_version", "attempt_id", "code_commit", "run_created_at",
        "adapter_contract_sha256", "policy_contract_sha256", "receipt_schema_sha256",
        "retrieval_timestamp_mode", "entries", "completion_status",
    }
)
RECEIPT_PROPERTIES_V4: frozenset[str] = RECEIPT_REQUIRED_V4

ENTRY_REQUIRED_V4: frozenset[str] = frozenset(
    {
        "evidence_kind", "route_kind", "requested_url", "final_url", "entry_status",
        "request_chain", "failure_reason", "failure_phase",
        "send1_observed_status", "send1_observed_location",
        "send1_observed_location_disposition",
        "send2_observed_status", "send2_observed_location",
        "send2_observed_location_disposition",
        "content_type", "content_encoding", "byte_count", "content_sha256",
        "raw_reference", "object_disposition", "retrieval_timestamp",
    }
)
ENTRY_PROPERTIES_V4: frozenset[str] = ENTRY_REQUIRED_V4

# Fields that must be null whenever no value was established.
_NULLABLE_ENTRY_FIELDS: tuple[str, ...] = (
    "content_type", "content_encoding", "byte_count", "content_sha256",
    "raw_reference", "object_disposition", "retrieval_timestamp",
    "send1_observed_status", "send1_observed_location",
    "send2_observed_status", "send2_observed_location",
)
_ENTITY_FIELDS: tuple[str, ...] = (
    "content_type", "content_encoding", "byte_count", "content_sha256",
)
_OBJECT_FIELDS: tuple[str, ...] = ("raw_reference", "object_disposition")


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

    The locked order is length before charset before the space-only rule.
    Classification is independent of authorization: a value may be ``recorded``
    and still refused by the route grammar, and vice versa. The two outputs are
    **bound** -- a non-null value implies ``recorded``, every other disposition
    implies null. Nothing may be half-recorded.
    """
    if not response_received:
        return None, "no_response"
    if value is None or value == "":
        return None, "absent"
    if not isinstance(value, str):
        return None, "rejected_uncharacterizable"
    if len(value) > LOCATION_MAX_LENGTH:
        return None, "rejected_oversize"
    if not _printable_ascii(value):
        # Charset is decided **before** the space-only rule. Checking emptiness
        # with a bare ``strip()`` first classified TAB, LF, CR, NBSP and U+2003
        # as ``absent``, hiding forbidden characters behind a benign disposition.
        return None, "rejected_uncharacterizable"
    if _ascii_space_only(value):
        return None, "absent"
    return value, "recorded"


# --- the single source of truth ----------------------------------------------


def _no_response_pair(ordinal: str) -> dict[str, Any]:
    return {
        f"{ordinal}_observed_status": {"const": None},
        f"{ordinal}_observed_location": {"const": None},
        f"{ordinal}_observed_location_disposition": {"const": "no_response"},
    }


def _observed_pair(ordinal: str) -> dict[str, Any]:
    return {
        f"{ordinal}_observed_status": {
            "type": "integer", "minimum": _STATUS_MIN, "maximum": _STATUS_MAX,
        },
        f"{ordinal}_observed_location_disposition": {
            "enum": list(RESPONSE_DISPOSITIONS)
        },
    }


def _accepted_hop(final: str) -> dict[str, Any]:
    """What send 1 must look like once a redirect_once hop has been accepted."""
    return {
        "send1_observed_status": {"enum": list(REDIRECT_STATUSES_V4)},
        "send1_observed_location": {"const": final},
        "send1_observed_location_disposition": {"const": "recorded"},
    }


def _nulled(fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: {"const": None} for field in fields}


def _phase_rules_v4(kind: str, requested: str, final: str) -> dict[str, dict[str, Any]]:
    """Per-phase payload rules. A phase states exactly how far the entry got."""
    dated = {"retrieval_timestamp": {"type": "string", "pattern": UTC_INSTANT_PATTERN}}
    undated = {"retrieval_timestamp": {"type": ["string", "null"], "pattern": UTC_INSTANT_PATTERN}}
    no_object = _nulled(_OBJECT_FIELDS)
    no_entity = _nulled(_ENTITY_FIELDS)
    # Reached only when the entity was accepted and storage refused it, so the
    # entity facts are real even though no object exists.
    accepted_entity = {
        "content_type": {"type": "string", "minLength": 1},
        "content_encoding": {"type": "string", "minLength": 1},
        "byte_count": {"type": "integer", "minimum": 1},
        "content_sha256": {"type": "string", "pattern": SHA256_PATTERN},
    }

    rules: dict[str, dict[str, Any]] = {
        "entry_preflight": {
            "request_chain": {"const": []},
            **undated, **no_entity, **no_object,
            **_no_response_pair("send1"), **_no_response_pair("send2"),
        },
        "send1_request": {
            "request_chain": {"const": [requested]},
            **dated, **no_entity, **no_object,
            **_no_response_pair("send1"), **_no_response_pair("send2"),
        },
        "send1_evaluation": {
            "request_chain": {"const": [requested]},
            **dated, **no_entity, **no_object,
            **_observed_pair("send1"), **_no_response_pair("send2"),
        },
    }
    if kind == "direct":
        # One send: persistence follows send 1 directly, and the accepted status
        # is the terminal 200 observed there.
        rules["persistence"] = {
            "request_chain": {"const": [requested]},
            **dated, **no_object, **accepted_entity,
            "send1_observed_status": {"const": TERMINAL_STATUS_V4},
            "send1_observed_location_disposition": {"enum": list(RESPONSE_DISPOSITIONS)},
            **_no_response_pair("send2"),
        }
        return rules

    rules["send2_preflight"] = {
        "request_chain": {"const": [requested]},
        **dated, **no_entity, **no_object,
        **_accepted_hop(final), **_no_response_pair("send2"),
    }
    rules["send2_request"] = {
        "request_chain": {"const": [requested, final]},
        **dated, **no_entity, **no_object,
        **_accepted_hop(final), **_no_response_pair("send2"),
    }
    rules["send2_evaluation"] = {
        "request_chain": {"const": [requested, final]},
        **dated, **no_entity, **no_object,
        **_accepted_hop(final), **_observed_pair("send2"),
    }
    rules["persistence"] = {
        "request_chain": {"const": [requested, final]},
        **dated, **no_object, **accepted_entity,
        **_accepted_hop(final),
        "send2_observed_status": {"const": TERMINAL_STATUS_V4},
        "send2_observed_location_disposition": {"enum": list(RESPONSE_DISPOSITIONS)},
    }
    return rules


def _chain_constants(kind: str, requested: str, final: str) -> list[dict[str, Any]]:
    """The only chains an entry may carry -- all frozen constants.

    An observed ``Location`` is therefore structurally incapable of entering the
    chain, provable from the schema alone without trusting the collector.
    """
    if kind == "direct":
        return [{"const": []}, {"const": [requested]}]
    return [{"const": []}, {"const": [requested]}, {"const": [requested, final]}]


def _entry_schema_v4(entry: dict[str, str]) -> dict[str, Any]:
    """One positionally frozen entry with its full per-status/phase payload rules."""
    kind = entry["route_kind"]
    requested, final = entry["requested_url"], entry["final_url"]
    phases = ROUTE_KIND_PHASES[kind]
    reasons = ROUTE_KIND_REASONS[kind]

    succeeded_common = {
        "content_type": {"type": "string", "minLength": 1},
        "content_encoding": {"type": "string", "minLength": 1},
        "byte_count": {"type": "integer", "minimum": 1},
        "content_sha256": {"type": "string", "pattern": SHA256_PATTERN},
        "raw_reference": {"type": "string", "minLength": 1},
        "object_disposition": {"enum": ["created", "reused"]},
        "retrieval_timestamp": {"type": "string", "pattern": UTC_INSTANT_PATTERN},
        "failure_reason": {"const": None},
        "failure_phase": {"const": None},
    }
    if kind == "direct":
        succeeded = {
            "properties": {
                **succeeded_common,
                "request_chain": {"const": [requested]},
                "send1_observed_status": {"const": TERMINAL_STATUS_V4},
                "send1_observed_location_disposition": {"enum": list(RESPONSE_DISPOSITIONS)},
                **_no_response_pair("send2"),
            }
        }
    else:
        succeeded = {
            "properties": {
                **succeeded_common,
                "request_chain": {"const": [requested, final]},
                **_accepted_hop(final),
                "send2_observed_status": {"const": TERMINAL_STATUS_V4},
                "send2_observed_location_disposition": {"enum": list(RESPONSE_DISPOSITIONS)},
            }
        }

    not_attempted = {
        "properties": {
            "request_chain": {"const": []},
            **_nulled(_NULLABLE_ENTRY_FIELDS),
            **_no_response_pair("send1"), **_no_response_pair("send2"),
            "failure_reason": {"const": None},
            "failure_phase": {"const": None},
        }
    }
    # Entity nullity is decided per phase, not here: a ``persistence`` failure
    # means the entity was accepted and storage refused it, so its entity facts
    # are real. Every earlier phase pins them null in ``_phase_rules_v4``.
    failed = {
        "properties": {
            **_nulled(_OBJECT_FIELDS),
            "failure_reason": {"enum": list(reasons)},
            "failure_phase": {"enum": list(phases)},
        }
    }

    branches: list[dict[str, Any]] = [
        {"if": {"properties": {"entry_status": {"const": "succeeded"}}}, "then": succeeded},
        {"if": {"properties": {"entry_status": {"const": "failed"}}}, "then": failed},
        {
            "if": {"properties": {"entry_status": {"const": "not_attempted"}}},
            "then": not_attempted,
        },
    ]
    branches.extend(
        {
            "if": {
                "properties": {"failure_phase": {"const": phase}},
                "required": ["failure_phase"],
            },
            "then": {"properties": rules},
        }
        for phase, rules in _phase_rules_v4(kind, requested, final).items()
    )
    # Each observed location is bound to its own disposition in both directions,
    # under every status and phase: ``recorded`` requires a transcribable string,
    # every other disposition requires null, and therefore a non-null location
    # implies ``recorded``.
    branches.extend(
        {
            "if": {
                "properties": {f"{ordinal}_observed_location_disposition": {"const": "recorded"}},
                "required": [f"{ordinal}_observed_location_disposition"],
            },
            "then": {
                "properties": {
                    f"{ordinal}_observed_location": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": LOCATION_MAX_LENGTH,
                        "pattern": PRINTABLE_ASCII_REQUIRED_PATTERN,
                        "not": {"pattern": NON_PRINTABLE_ASCII_PATTERN},
                    }
                }
            },
            "else": {"properties": {f"{ordinal}_observed_location": {"const": None}}},
        }
        for ordinal in ("send1", "send2")
    )

    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(ENTRY_REQUIRED_V4),
        "properties": {
            "evidence_kind": {"const": entry["evidence_kind"]},
            "route_kind": {"const": kind},
            "requested_url": {"const": requested},
            "final_url": {"const": final},
            "entry_status": {"type": "string", "enum": list(ENTRY_STATUSES)},
            "request_chain": {"oneOf": _chain_constants(kind, requested, final)},
            "failure_reason": {"enum": list(reasons) + [None]},
            "failure_phase": {"enum": list(phases) + [None]},
            "send1_observed_status": {
                "type": ["integer", "null"], "minimum": _STATUS_MIN, "maximum": _STATUS_MAX,
            },
            "send1_observed_location": {"type": ["string", "null"], "maxLength": LOCATION_MAX_LENGTH},
            "send1_observed_location_disposition": {"enum": list(LOCATION_DISPOSITIONS)},
            "send2_observed_status": {
                "type": ["integer", "null"], "minimum": _STATUS_MIN, "maximum": _STATUS_MAX,
            },
            "send2_observed_location": {"type": ["string", "null"], "maxLength": LOCATION_MAX_LENGTH},
            "send2_observed_location_disposition": {"enum": list(LOCATION_DISPOSITIONS)},
            "content_type": {"type": ["string", "null"], "minLength": 1},
            "content_encoding": {"type": ["string", "null"], "minLength": 1},
            "byte_count": {"type": ["integer", "null"], "minimum": 1},
            "content_sha256": {"type": ["string", "null"], "pattern": SHA256_PATTERN},
            "raw_reference": {"type": ["string", "null"], "minLength": 1},
            "object_disposition": {"enum": ["created", "reused", None]},
            "retrieval_timestamp": {
                "type": ["string", "null"], "pattern": UTC_INSTANT_PATTERN,
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


def expected_receipt_schema_v4() -> dict[str, Any]:
    """The complete locked 0.4.0 schema. The committed file is generated from this."""
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": RECEIPT_SCHEMA_ID_V4,
        "title": RECEIPT_CONTRACT_V4,
        "comment": (
            "ADR-040 (E-C-D3). Successor to documentation_collection_receipt@0.3.0, "
            "which is never modified because its frozen routes are const-pinned "
            "inside its committed schema. Route kinds are now explicit: E1 and E2 "
            "are redirect_once, E3 is direct with requested_url == final_url, one "
            "send, an initial 200 as its only success path, and any 3xx recorded "
            "then refused with direct_redirect_not_permitted rather than followed. "
            "Observation slots are named by send ordinal, not by role, so a direct "
            "route's only send is never described with redirect-only vocabulary; "
            "the three send2_* phases are unreachable for a direct entry. An "
            "observed location is the exact adapter-exposed Python string returned "
            "by httpx.Headers.get('location'): it is not wire bytes and does not "
            "preserve duplicate header-line boundaries, which that surface joins. "
            "It is either recorded unchanged or refused with a disposition that "
            "says why -- never truncated, and never present without a recorded "
            "disposition. request_chain lists only URLs this collector initiated, "
            "pinned per entry to frozen constants so an observed value can never "
            "enter it and is never followed merely because it was observed. E1's "
            "target is a governed collector observation; E2 and E3 are "
            "human-supplied route hypotheses dated 2026-07-30, testable but not "
            "validated. The receipt owns retrieval_status only; whether the bytes "
            "carry the required official claim belongs to "
            "documentation_evidence_validation@0.1.0."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": sorted(RECEIPT_REQUIRED_V4),
        "properties": {
            "contract": {"const": RECEIPT_CONTRACT_V4},
            "schema_version": {"const": SCHEMA_VERSION_V4},
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
                "prefixItems": [_entry_schema_v4(e) for e in FROZEN_ROUTE_IDENTITIES_V4],
                "items": False,
            },
            "completion_status": {"type": "string", "enum": list(COMPLETION_STATUSES)},
        },
        "oneOf": [_sequence_branch(c, s) for c, s in TERMINAL_SEQUENCES],
    }


class _DuplicateMemberError(ValueError):
    """A JSON object repeated a member name; the parser would hide one value."""


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """``object_pairs_hook`` refusing repeated names at any nesting level.

    ``json.loads`` silently keeps the last occurrence, so a schema carrying a
    duplicate is ambiguous about which definition governs -- even when the two
    values are identical, because another parser need not resolve it the same way.
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
    ``additionalProperties: 0`` compared equal to ``false``. ``3 == 3.0`` likewise
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


def validate_receipt_schema_v4_bytes(schema_bytes: Any) -> str:
    """Prove the bytes are the locked 0.4.0 schema, semantically, and return the digest.

    Same closure as the earlier loaders: a recursive JSON-type-exact comparison
    against :func:`expected_receipt_schema_v4`, so every type, const, enum,
    pattern, bound, nullability and conditional rule is verified. Duplicate member
    names are refused at any depth. Formatting is not part of the comparison, and
    the returned digest is always derived from the exact bytes supplied.
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
    properties = schema.get("properties")
    if isinstance(properties, dict):
        contract = properties.get("contract")
        if isinstance(contract, dict):
            declared = contract.get("const")
            if (
                isinstance(declared, str)
                and not isinstance(declared, bool)
                and declared.strip()
                and declared != RECEIPT_CONTRACT_V4
            ):
                _refuse(
                    "properties.contract.const identifies a different contract",
                    "receipt_schema_contract_mismatch",
                )

    required = schema.get("required")
    if isinstance(required, list) and all(isinstance(name, str) for name in required):
        if len(required) != len(set(required)):
            _refuse("the receipt schema required list carries duplicates")

    if not _json_exact_equal(schema, expected_receipt_schema_v4()):
        _refuse("the receipt schema does not match the locked definition")
    return sha256(bytes(schema_bytes)).hexdigest()


# --- the builder --------------------------------------------------------------


def _nonblank(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _status_ok(value: Any) -> bool:
    return (
        isinstance(value, int)
        and not isinstance(value, bool)
        and _STATUS_MIN <= value <= _STATUS_MAX
    )


def _binding_violation(entry: Any, ordinal: str) -> str | None:
    """A location may exist only when its disposition says it was recorded."""
    value = entry.get(f"{ordinal}_observed_location")
    disposition = entry.get(f"{ordinal}_observed_location_disposition")
    if disposition not in LOCATION_DISPOSITIONS:
        return f"{ordinal}_observed_location_disposition is not a declared value"
    if disposition == "recorded":
        if not transcribable_location(value):
            return f"{ordinal}_observed_location is recorded but is not transcribable"
    elif value is not None:
        return f"{ordinal}_observed_location must be null unless it was recorded"
    return None


def _no_send_violation(entry: Any, ordinal: str) -> str | None:
    """This send never happened: no status, no location, disposition no_response."""
    if entry.get(f"{ordinal}_observed_status") is not None:
        return f"{ordinal}_observed_status must be null when no send occurred"
    if entry.get(f"{ordinal}_observed_location") is not None:
        return f"{ordinal}_observed_location must be null when no send occurred"
    if entry.get(f"{ordinal}_observed_location_disposition") != "no_response":
        return f"{ordinal}_observed_location_disposition must be no_response"
    return None


def _entry_violations_v4(entry: Any, frozen: dict[str, str]) -> str | None:
    if not isinstance(entry, dict) or frozenset(entry) != ENTRY_PROPERTIES_V4:
        return "an entry does not carry exactly the locked property set"
    for field in ("evidence_kind", "route_kind", "requested_url", "final_url"):
        if entry.get(field) != frozen[field]:
            return f"an entry does not carry its frozen {field}"

    kind = frozen["route_kind"]
    requested, final = frozen["requested_url"], frozen["final_url"]
    # The route-kind truthfulness constraint, enforced here as well as in the
    # frozen declaration: a direct route's two URLs are the same one, and a
    # redirect_once route's two URLs genuinely differ.
    if kind == "direct" and requested != final:
        return "a direct route must declare requested_url == final_url"
    if kind == "redirect_once" and requested == final:
        return "a redirect_once route must declare two different URLs"

    status = entry.get("entry_status")
    if status not in ENTRY_STATUSES:
        return "unknown entry status"

    for ordinal in ("send1", "send2"):
        violation = _binding_violation(entry, ordinal)
        if violation is not None:
            return violation

    if status == "succeeded":
        if entry.get("failure_reason") is not None:
            return "a succeeded entry carries no failure reason"
        if entry.get("failure_phase") is not None:
            return "a succeeded entry carries no failure phase"
        for field in ("content_type", "content_encoding", "raw_reference"):
            if not _nonblank(entry.get(field)):
                return f"a succeeded entry needs a non-blank {field}"
        if not _positive_int(entry.get("byte_count")):
            return "a succeeded entry needs a positive byte_count"
        digest = entry.get("content_sha256")
        if not isinstance(digest, str) or not re.fullmatch(SHA256_PATTERN, digest):
            return "a succeeded entry needs a lowercase 64-hex content_sha256"
        if entry.get("object_disposition") not in {"created", "reused"}:
            return "a succeeded entry needs a created/reused disposition"
        if not _is_utc_instant(entry.get("retrieval_timestamp")):
            return "a succeeded entry needs a real UTC retrieval_timestamp"
        if kind == "direct":
            if entry.get("request_chain") != [requested]:
                return "a succeeded direct entry records exactly its own single send"
            if entry.get("send1_observed_status") != TERMINAL_STATUS_V4:
                return "a succeeded direct entry records status 200 on its only send"
            violation = _no_send_violation(entry, "send2")
            if violation is not None:
                return f"a succeeded direct entry issues no second send: {violation}"
        else:
            if entry.get("request_chain") != [requested, final]:
                return "a succeeded redirect_once entry records its own two sends"
            if entry.get("send1_observed_status") not in REDIRECT_STATUSES_V4:
                return "a succeeded redirect_once entry records an accepted hop status"
            if entry.get("send1_observed_location") != final:
                return "a succeeded redirect_once entry records the frozen hop target"
            if entry.get("send1_observed_location_disposition") != "recorded":
                return "a succeeded redirect_once entry records its hop location"
            if entry.get("send2_observed_status") != TERMINAL_STATUS_V4:
                return "a succeeded redirect_once entry records status 200 on send two"
        return None

    for field in _OBJECT_FIELDS:
        if entry.get(field) is not None:
            return f"a {status} entry must leave {field} null"

    if status == "not_attempted":
        for field in _ENTITY_FIELDS:
            if entry.get(field) is not None:
                return f"a not_attempted entry must leave {field} null"
        if entry.get("request_chain") != []:
            return "a not_attempted entry records no request chain"
        if entry.get("failure_reason") is not None:
            return "a not_attempted entry carries no failure reason"
        if entry.get("failure_phase") is not None:
            return "a not_attempted entry carries no failure phase"
        if entry.get("retrieval_timestamp") is not None:
            return "a not_attempted entry records no retrieval timestamp"
        for ordinal in ("send1", "send2"):
            violation = _no_send_violation(entry, ordinal)
            if violation is not None:
                return f"a not_attempted entry made no send: {violation}"
        return None

    # failed
    reason = entry.get("failure_reason")
    phase = entry.get("failure_phase")
    if phase == "persistence":
        # The entity was accepted and storage refused it, so these facts
        # are real. Every earlier phase refused before acceptance.
        for field in ("content_type", "content_encoding"):
            if not _nonblank(entry.get(field)):
                return f"a persistence failure records a non-blank {field}"
        if not _positive_int(entry.get("byte_count")):
            return "a persistence failure records a positive byte_count"
        digest = entry.get("content_sha256")
        if not isinstance(digest, str) or not re.fullmatch(SHA256_PATTERN, digest):
            return "a persistence failure records the accepted digest"
    else:
        for field in _ENTITY_FIELDS:
            if entry.get(field) is not None:
                return f"a pre-acceptance failure must leave {field} null"
    if reason not in ROUTE_KIND_REASONS[kind]:
        return "a failed entry needs a reason its route kind can produce"
    if phase not in ROUTE_KIND_PHASES[kind]:
        return "a failed entry needs a phase its route kind can reach"
    if phase not in REASON_PHASES[reason]:
        return "a failed entry names a phase its reason cannot arise in"
    if entry.get("request_chain") not in (
        [], [requested], ([requested, final] if kind == "redirect_once" else None),
    ):
        return "a failed entry records a chain that is not one of its own constants"
    if phase == "entry_preflight":
        if entry.get("request_chain") != []:
            return "an entry_preflight failure initiated no request"
        for ordinal in ("send1", "send2"):
            violation = _no_send_violation(entry, ordinal)
            if violation is not None:
                return f"an entry_preflight failure made no send: {violation}"
        return None
    if not _is_utc_instant(entry.get("retrieval_timestamp")):
        return "a failure after the clock read records its request-start instant"
    # The chain a phase may carry, by kind. ``persistence`` is reachable under
    # both kinds -- for a direct route it follows send one, which is why it is
    # named here rather than lumped in with the send-two phases.
    if phase in ("send1_request", "send1_evaluation"):
        if entry.get("request_chain") != [requested]:
            return "a send-one failure initiated exactly its own first request"
    elif phase == "persistence":
        expected = [requested] if kind == "direct" else [requested, final]
        if entry.get("request_chain") != expected:
            return "a persistence failure records the sends it actually issued"
    else:
        if kind == "direct":
            return "a direct route cannot reach a send-two phase"
        if phase == "send2_preflight":
            if entry.get("request_chain") != [requested]:
                return "a send2_preflight failure has not yet initiated send two"
        elif entry.get("request_chain") != [requested, final]:
            return "a send-two failure initiated both of its own requests"

    if phase == "send1_request":
        violation = _no_send_violation(entry, "send1")
        if violation is not None:
            return f"a send1_request failure received no response: {violation}"
    if phase == "send1_evaluation" and not _status_ok(entry.get("send1_observed_status")):
        return "a send1_evaluation failure records the status it evaluated"

    if kind == "direct":
        # One send, so the second observation stays empty under every phase, and
        # a persistence failure means the single send answered 200.
        violation = _no_send_violation(entry, "send2")
        if violation is not None:
            return f"a direct route issued no second send: {violation}"
        if phase == "persistence" and entry.get("send1_observed_status") != TERMINAL_STATUS_V4:
            return "a direct persistence failure accepted a 200 on its only send"
        return None

    if phase in ("send1_request", "send1_evaluation"):
        violation = _no_send_violation(entry, "send2")
        if violation is not None:
            return f"a send-one failure issued no second send: {violation}"
        return None
    if phase in ("send2_preflight", "send2_request"):
        violation = _no_send_violation(entry, "send2")
        if violation is not None:
            return f"a pre-response send-two failure received no response: {violation}"
    if phase == "send2_evaluation" and not _status_ok(entry.get("send2_observed_status")):
        return "a send2_evaluation failure records the status it evaluated"
    if phase == "persistence" and entry.get("send2_observed_status") != TERMINAL_STATUS_V4:
        return "a hop-route persistence failure accepted a 200 on send two"
    if entry.get("send1_observed_location") != final:
        return "a post-hop failure records the accepted hop target"
    return None


def build_documentation_receipt_v4(
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
    """Assemble the 0.4.0 receipt, refusing anything the committed schema rejects.

    The collector must never be able to publish bytes its own schema rejects, so
    the builder enforces the same invariants rather than trusting its caller.
    Pure; performs no I/O.
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

    if not isinstance(entries, list) or len(entries) != len(FROZEN_ROUTE_IDENTITIES_V4):
        _refuse("the receipt must carry exactly three positional entries")
    for entry, frozen in zip(entries, FROZEN_ROUTE_IDENTITIES_V4):
        violation = _entry_violations_v4(entry, frozen)
        if violation is not None:
            _refuse(violation)

    sequence = tuple(entry["entry_status"] for entry in entries)
    if (completion_status, sequence) not in TERMINAL_SEQUENCES:
        _refuse("the status sequence describes a run that cannot have happened")

    return {
        "contract": RECEIPT_CONTRACT_V4,
        "schema_version": SCHEMA_VERSION_V4,
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


def receipt_bytes_v4(receipt: dict[str, Any]) -> bytes:
    """Canonical serialization, matching the repository's convention."""
    return canonical_json_bytes(receipt)
