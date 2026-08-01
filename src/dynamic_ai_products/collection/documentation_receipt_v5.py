"""Documentation collection receipt v0.5.0: schema, loader and builder (ADR-041, E-C-D4).

**Why a successor rather than an edit.** ``@0.1.0`` through ``@0.4.0`` are all
committed and three are instantiated by live receipts. Every one pins its frozen
routes as ``const`` inside its committed schema, and every loader deep-compares
that schema against a constructor which reads the route declaration. Re-freezing
in place would make a committed schema stop matching its own loader and its live
receipt unverifiable. The v0.4 standard therefore holds: receipt, schema, routes
**and policy source** all succeed rather than mutate.

**What 0.5.0 changes: a two-hop route grammar.** The governed v0.4 attempt
``docattempt-921cb253da290dc5dadadd5afc7244d6`` stopped at ``send2_evaluation``
with ``redirect_chain_too_long`` -- a positive observation that E1's accepted
intermediate itself redirects. v0.5 adds ``redirect_twice_relative_path``, whose
second hop is an **absolute-path reference**, not an absolute URL:

* send 1 and send 2 accept only 301/308;
* send 1's ``Location`` must be byte-exact against the frozen intermediate;
* send 2's ``Location`` must satisfy a deliberately narrow absolute-path grammar
  -- one leading ``/``, no ``//``, no scheme, host, userinfo, query or fragment,
  no ``..`` segment -- and be byte-exact against the frozen raw path;
* the raw path is joined to a **fixed declared base**, never one parsed out of a
  response, and the join must reproduce the frozen final URL byte-exactly;
* send 3 must answer 200.

``redirect_once`` keeps the two-send shape for E3.

**No ``direct`` kind.** v0.4's direct semantics are not carried forward: every
v0.5 route performs at least one recognized hop, so no entry can describe a bare
fetch.

**What is preserved from 0.4.0 unchanged.** Send-ordinal observation naming, the
location/disposition binding under two unanchored predicates, ``request_chain``
pinned to per-entry frozen constants so an observed value can never enter it, the
four truthful terminal sequences, and every fail-closed builder and loader guard.
The 0.4 entry is extended with send-three fields rather than mutated.
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
from .documentation_routes_v5 import (
    FROZEN_ROUTE_IDENTITIES_V5,
    RELATIVE_RESOLUTION_BASE,
)
from .errors import CollectionError
from .publication import canonical_json_bytes

__all__ = [
    "ENTRY_PROPERTIES_V5",
    "ENTRY_RECORDABLE_REASONS_V5",
    "ENTRY_REQUIRED_V5",
    "FAILURE_PHASES_V5",
    "FAILURE_REASONS_V5",
    "LOCATION_DISPOSITIONS",
    "LOCATION_MAX_LENGTH",
    "NON_PRINTABLE_ASCII_PATTERN",
    "PRINTABLE_ASCII_REQUIRED_PATTERN",
    "RECEIPT_CONTRACT_V5",
    "RECEIPT_PROPERTIES_V5",
    "RECEIPT_REQUIRED_V5",
    "RECEIPT_SCHEMA_ID_V5",
    "REASON_PHASES_V5",
    "REDIRECT_ONCE_PHASES_V5",
    "REDIRECT_TWICE_PHASES_V5",
    "RESPONSE_DISPOSITIONS",
    "ROUTE_KIND_PHASES_V5",
    "ROUTE_KIND_REASONS_V5",
    "SCHEMA_VERSION_V5",
    "absolute_path_reference_violation",
    "build_documentation_receipt_v5",
    "classify_observed_location",
    "expected_receipt_schema_v5",
    "receipt_bytes_v5",
    "resolve_absolute_path_reference",
    "transcribable_location",
    "validate_receipt_schema_v5_bytes",
]

RECEIPT_CONTRACT_V5 = "documentation_collection_receipt@0.5.0"
RECEIPT_SCHEMA_ID_V5 = "documentation_collection_receipt.v5.schema.json"
SCHEMA_VERSION_V5 = "0.5.0"

# Ten phases, named by send ordinal so they stay true under both route kinds.
FAILURE_PHASES_V5: tuple[str, ...] = (
    "entry_preflight",
    "send1_request",
    "send1_evaluation",
    "send2_preflight",
    "send2_request",
    "send2_evaluation",
    "send3_preflight",
    "send3_request",
    "send3_evaluation",
    "persistence",
)
# A two-send route can never reach a send-three phase.
REDIRECT_ONCE_PHASES_V5: tuple[str, ...] = (
    "entry_preflight",
    "send1_request",
    "send1_evaluation",
    "send2_preflight",
    "send2_request",
    "send2_evaluation",
    "persistence",
)
REDIRECT_TWICE_PHASES_V5: tuple[str, ...] = FAILURE_PHASES_V5
ROUTE_KIND_PHASES_V5: dict[str, tuple[str, ...]] = {
    "redirect_once": REDIRECT_ONCE_PHASES_V5,
    "redirect_twice_relative_path": REDIRECT_TWICE_PHASES_V5,
}

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

# Two independent, unanchored predicates rather than one anchored pattern: JSON
# Schema ``pattern`` is a search, and ``$`` also matches before a final newline.
PRINTABLE_ASCII_REQUIRED_PATTERN = r"[\x21-\x7e]"
NON_PRINTABLE_ASCII_PATTERN = r"[^\x20-\x7e]"

REDIRECT_STATUSES_V5: tuple[int, ...] = (301, 308)
TERMINAL_STATUS_V5 = 200
_STATUS_MIN = 100
_STATUS_MAX = 599

# 0.5.0 drops the v0.4 direct-only reason (there is no direct kind) and adds five
# describing the second hop's absolute-path grammar and its resolution.
_SECOND_HOP_REASONS: frozenset[str] = frozenset(
    {
        "second_redirect_status_invalid",
        "second_location_missing",
        "second_location_not_relative_path",
        "second_location_mismatch",
        "resolved_final_mismatch",
    }
)
FAILURE_REASONS_V5: tuple[str, ...] = tuple(
    sorted((set(FAILURE_REASONS) | _SECOND_HOP_REASONS) - {"direct_redirect_not_permitted"})
)

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
ENTRY_RECORDABLE_REASONS_V5: tuple[str, ...] = tuple(
    reason for reason in FAILURE_REASONS_V5 if reason not in _NON_ENTRY_REASONS
)

ROUTE_KIND_REASONS_V5: dict[str, tuple[str, ...]] = {
    # A two-send route never evaluates a second hop, so those five cannot arise.
    "redirect_once": tuple(
        r for r in ENTRY_RECORDABLE_REASONS_V5 if r not in _SECOND_HOP_REASONS
    ),
    "redirect_twice_relative_path": ENTRY_RECORDABLE_REASONS_V5,
}

REASON_PHASES_V5: dict[str, tuple[str, ...]] = {
    "retrieval_clock_failed": ("entry_preflight",),
    "retrieval_clock_invalid": ("entry_preflight",),
    "tls_keylog_environment_present": (
        "entry_preflight", "send1_request",
        "send2_preflight", "send2_request",
        "send3_preflight", "send3_request",
    ),
    "transport_timeout": ("send1_request", "send2_request", "send3_request"),
    "transport_failed": ("send1_request", "send2_request", "send3_request"),
    "response_request_identity_mismatch": (
        "send1_request", "send1_evaluation",
        "send2_request", "send2_evaluation",
        "send3_request", "send3_evaluation",
    ),
    # A 200 where a redirect was required.
    "direct_terminal_not_permitted": ("send1_evaluation", "send2_evaluation"),
    # First hop: absolute-URL grammar.
    "redirect_status_invalid": ("send1_evaluation",),
    "redirect_location_missing": ("send1_evaluation",),
    "redirect_location_not_absolute": ("send1_evaluation",),
    "redirect_location_mismatch": ("send1_evaluation",),
    # Second hop: absolute-path grammar and its mechanical resolution.
    "second_redirect_status_invalid": ("send2_evaluation",),
    "second_location_missing": ("send2_evaluation",),
    "second_location_not_relative_path": ("send2_evaluation",),
    "second_location_mismatch": ("send2_evaluation",),
    "resolved_final_mismatch": ("send2_evaluation",),
    "entity_too_large": ("send2_request", "send3_request"),
    "redirect_chain_too_long": ("send2_evaluation", "send3_evaluation"),
    "terminal_status_invalid": ("send2_evaluation", "send3_evaluation"),
    "content_type_invalid": ("send2_evaluation", "send3_evaluation"),
    "entity_empty": ("send2_evaluation", "send3_evaluation"),
    "attempt_byte_ceiling_exceeded": ("send2_evaluation", "send3_evaluation"),
    "content_object_corrupt": ("persistence",),
    "destination_exists": ("persistence",),
    "write_error": ("persistence",),
}

RECEIPT_REQUIRED_V5: frozenset[str] = frozenset(
    {
        "contract", "schema_version", "attempt_id", "code_commit", "run_created_at",
        "adapter_contract_sha256", "policy_contract_sha256", "receipt_schema_sha256",
        "retrieval_timestamp_mode", "entries", "completion_status",
    }
)
RECEIPT_PROPERTIES_V5: frozenset[str] = RECEIPT_REQUIRED_V5

# The 0.4 entry, extended with send-three fields. Nothing from 0.4 is renamed or
# removed; ``intermediate_url``, ``second_hop_location`` and the four send-three
# fields are added.
ENTRY_REQUIRED_V5: frozenset[str] = frozenset(
    {
        "evidence_kind", "route_kind",
        "requested_url", "intermediate_url", "second_hop_location", "final_url",
        "entry_status", "request_chain", "failure_reason", "failure_phase",
        "send1_observed_status", "send1_observed_location",
        "send1_observed_location_disposition",
        "send2_observed_status", "send2_observed_location",
        "send2_observed_location_disposition",
        "send3_request_url", "send3_observed_status", "send3_observed_location",
        "send3_observed_location_disposition",
        "content_type", "content_encoding", "byte_count", "content_sha256",
        "raw_reference", "object_disposition", "retrieval_timestamp",
    }
)
ENTRY_PROPERTIES_V5: frozenset[str] = ENTRY_REQUIRED_V5

_ENTITY_FIELDS: tuple[str, ...] = (
    "content_type", "content_encoding", "byte_count", "content_sha256",
)
_OBJECT_FIELDS: tuple[str, ...] = ("raw_reference", "object_disposition")
_SEND_ORDINALS: tuple[str, ...] = ("send1", "send2", "send3")


def _refuse(message: str, code: str = "receipt_schema_invalid") -> None:
    raise CollectionError(message, reason_code=code)


def _is_utc_instant(value: Any) -> bool:
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
    """True for a non-empty run of U+0020 alone; never ``str.strip()``."""
    return bool(value) and all(ch == _ASCII_SPACE for ch in value)


def transcribable_location(value: Any) -> bool:
    """Exactly the values ``classify_observed_location`` may mark ``recorded``."""
    return (
        isinstance(value, str)
        and value != ""
        and len(value) <= LOCATION_MAX_LENGTH
        and _printable_ascii(value)
        and not _ascii_space_only(value)
    )


def classify_observed_location(value: Any, *, response_received: bool) -> tuple[str | None, str]:
    """Decide whether an adapter-exposed ``Location`` string can be transcribed.

    Never truncated, split, normalized, resolved or decoded. Order is length,
    then charset, then the space-only rule. The two outputs are bound: a non-null
    value implies ``recorded``, every other disposition implies null.
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
        return None, "rejected_uncharacterizable"
    if _ascii_space_only(value):
        return None, "absent"
    return value, "recorded"


# --- the second-hop absolute-path grammar -------------------------------------


def absolute_path_reference_violation(value: Any) -> str | None:
    """Refuse anything that is not a bare absolute-path reference.

    Deliberately narrow, and deliberately *not* a URL parser: a permissive parse
    is exactly how a protocol-relative ``//host/x`` or an embedded userinfo gets
    treated as a path. Returns ``None`` when the value is acceptable, or a short
    reason for the refusal.
    """
    if not isinstance(value, str) or not value:
        return "empty"
    if not _printable_ascii(value):
        return "non_printable"
    if not value.startswith("/"):
        return "no_leading_slash"
    if value.startswith("//"):
        # Protocol-relative: the authority would come from the response.
        return "protocol_relative"
    if ":" in value:
        # Narrower than "no ``://``": a colon anywhere would let a first segment
        # be read as a scheme by a permissive resolver. No frozen path needs one.
        return "colon_present"
    if "?" in value:
        return "query_present"
    if "#" in value:
        return "fragment_present"
    if "@" in value:
        return "userinfo_present"
    if "\\" in value:
        return "backslash_present"
    if any(segment == ".." for segment in value.split("/")):
        return "dot_dot_segment"
    return None


def resolve_absolute_path_reference(value: str) -> str:
    """Join a validated absolute-path reference to the fixed declared base.

    Mechanical concatenation only. The base is a module constant, never parsed
    out of a response, so a server cannot choose where the join lands.
    """
    return RELATIVE_RESOLUTION_BASE + value


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
        f"{ordinal}_observed_location_disposition": {"enum": list(RESPONSE_DISPOSITIONS)},
    }


def _accepted_first_hop(intermediate: str) -> dict[str, Any]:
    return {
        "send1_observed_status": {"enum": list(REDIRECT_STATUSES_V5)},
        "send1_observed_location": {"const": intermediate},
        "send1_observed_location_disposition": {"const": "recorded"},
    }


def _accepted_second_hop(raw_path: str) -> dict[str, Any]:
    return {
        "send2_observed_status": {"enum": list(REDIRECT_STATUSES_V5)},
        "send2_observed_location": {"const": raw_path},
        "send2_observed_location_disposition": {"const": "recorded"},
    }


def _nulled(fields: tuple[str, ...]) -> dict[str, Any]:
    return {field: {"const": None} for field in fields}


def _chain_constants(entry: dict[str, Any]) -> list[dict[str, Any]]:
    """The only chains an entry may carry -- all frozen constants."""
    requested, final = entry["requested_url"], entry["final_url"]
    if entry["route_kind"] == "redirect_once":
        return [{"const": []}, {"const": [requested]}, {"const": [requested, final]}]
    intermediate = entry["intermediate_url"]
    return [
        {"const": []},
        {"const": [requested]},
        {"const": [requested, intermediate]},
        {"const": [requested, intermediate, final]},
    ]


def _phase_rules_v5(entry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Per-phase payload rules. A phase states exactly how far the entry got."""
    kind = entry["route_kind"]
    requested, final = entry["requested_url"], entry["final_url"]
    intermediate = entry["intermediate_url"]
    raw_path = entry["second_hop_location"]

    dated = {"retrieval_timestamp": {"type": "string", "pattern": UTC_INSTANT_PATTERN}}
    undated = {"retrieval_timestamp": {"type": ["string", "null"], "pattern": UTC_INSTANT_PATTERN}}
    no_object = _nulled(_OBJECT_FIELDS)
    no_entity = _nulled(_ENTITY_FIELDS)
    accepted_entity = {
        "content_type": {"type": "string", "minLength": 1},
        "content_encoding": {"type": "string", "minLength": 1},
        "byte_count": {"type": "integer", "minimum": 1},
        "content_sha256": {"type": "string", "pattern": SHA256_PATTERN},
    }
    no_send3_url = {"send3_request_url": {"const": None}}

    rules: dict[str, dict[str, Any]] = {
        "entry_preflight": {
            "request_chain": {"const": []},
            **undated, **no_entity, **no_object, **no_send3_url,
            **_no_response_pair("send1"), **_no_response_pair("send2"),
            **_no_response_pair("send3"),
        },
        "send1_request": {
            "request_chain": {"const": [requested]},
            **dated, **no_entity, **no_object, **no_send3_url,
            **_no_response_pair("send1"), **_no_response_pair("send2"),
            **_no_response_pair("send3"),
        },
        "send1_evaluation": {
            "request_chain": {"const": [requested]},
            **dated, **no_entity, **no_object, **no_send3_url,
            **_observed_pair("send1"), **_no_response_pair("send2"),
            **_no_response_pair("send3"),
        },
    }

    if kind == "redirect_once":
        # send 2 is the terminal document request.
        rules["send2_preflight"] = {
            "request_chain": {"const": [requested]},
            **dated, **no_entity, **no_object, **no_send3_url,
            "send1_observed_status": {"enum": list(REDIRECT_STATUSES_V5)},
            "send1_observed_location": {"const": final},
            "send1_observed_location_disposition": {"const": "recorded"},
            **_no_response_pair("send2"), **_no_response_pair("send3"),
        }
        rules["send2_request"] = {
            **rules["send2_preflight"],
            "request_chain": {"const": [requested, final]},
        }
        rules["send2_evaluation"] = {
            **rules["send2_request"],
            **_observed_pair("send2"),
        }
        rules["persistence"] = {
            "request_chain": {"const": [requested, final]},
            **dated, **no_object, **no_send3_url, **accepted_entity,
            "send1_observed_status": {"enum": list(REDIRECT_STATUSES_V5)},
            "send1_observed_location": {"const": final},
            "send1_observed_location_disposition": {"const": "recorded"},
            "send2_observed_status": {"const": TERMINAL_STATUS_V5},
            "send2_observed_location_disposition": {"enum": list(RESPONSE_DISPOSITIONS)},
            **_no_response_pair("send3"),
        }
        return rules

    first = _accepted_first_hop(intermediate)
    second = _accepted_second_hop(raw_path)
    rules["send2_preflight"] = {
        "request_chain": {"const": [requested]},
        **dated, **no_entity, **no_object, **no_send3_url,
        **first, **_no_response_pair("send2"), **_no_response_pair("send3"),
    }
    rules["send2_request"] = {
        **rules["send2_preflight"],
        "request_chain": {"const": [requested, intermediate]},
    }
    rules["send2_evaluation"] = {
        "request_chain": {"const": [requested, intermediate]},
        **dated, **no_entity, **no_object, **no_send3_url,
        **first, **_observed_pair("send2"), **_no_response_pair("send3"),
    }
    rules["send3_preflight"] = {
        "request_chain": {"const": [requested, intermediate]},
        **dated, **no_entity, **no_object,
        "send3_request_url": {"const": final},
        **first, **second, **_no_response_pair("send3"),
    }
    rules["send3_request"] = {
        **rules["send3_preflight"],
        "request_chain": {"const": [requested, intermediate, final]},
    }
    rules["send3_evaluation"] = {
        "request_chain": {"const": [requested, intermediate, final]},
        **dated, **no_entity, **no_object,
        "send3_request_url": {"const": final},
        **first, **second, **_observed_pair("send3"),
    }
    rules["persistence"] = {
        "request_chain": {"const": [requested, intermediate, final]},
        **dated, **no_object, **accepted_entity,
        "send3_request_url": {"const": final},
        **first, **second,
        "send3_observed_status": {"const": TERMINAL_STATUS_V5},
        "send3_observed_location_disposition": {"enum": list(RESPONSE_DISPOSITIONS)},
    }
    return rules


def _entry_schema_v5(entry: dict[str, Any]) -> dict[str, Any]:
    """One positionally frozen entry with its full per-status/phase payload rules."""
    kind = entry["route_kind"]
    requested, final = entry["requested_url"], entry["final_url"]
    intermediate = entry["intermediate_url"]
    raw_path = entry["second_hop_location"]
    phases = ROUTE_KIND_PHASES_V5[kind]
    reasons = ROUTE_KIND_REASONS_V5[kind]

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
    if kind == "redirect_once":
        succeeded = {
            "properties": {
                **succeeded_common,
                "request_chain": {"const": [requested, final]},
                "send1_observed_status": {"enum": list(REDIRECT_STATUSES_V5)},
                "send1_observed_location": {"const": final},
                "send1_observed_location_disposition": {"const": "recorded"},
                "send2_observed_status": {"const": TERMINAL_STATUS_V5},
                "send2_observed_location_disposition": {"enum": list(RESPONSE_DISPOSITIONS)},
                "send3_request_url": {"const": None},
                **_no_response_pair("send3"),
            }
        }
    else:
        succeeded = {
            "properties": {
                **succeeded_common,
                "request_chain": {"const": [requested, intermediate, final]},
                **_accepted_first_hop(intermediate),
                **_accepted_second_hop(raw_path),
                "send3_request_url": {"const": final},
                "send3_observed_status": {"const": TERMINAL_STATUS_V5},
                "send3_observed_location_disposition": {"enum": list(RESPONSE_DISPOSITIONS)},
            }
        }

    not_attempted = {
        "properties": {
            "request_chain": {"const": []},
            **_nulled(_ENTITY_FIELDS), **_nulled(_OBJECT_FIELDS),
            "retrieval_timestamp": {"const": None},
            "send3_request_url": {"const": None},
            **_no_response_pair("send1"), **_no_response_pair("send2"),
            **_no_response_pair("send3"),
            "failure_reason": {"const": None},
            "failure_phase": {"const": None},
        }
    }
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
        for phase, rules in _phase_rules_v5(entry).items()
    )
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
        for ordinal in _SEND_ORDINALS
    )

    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(ENTRY_REQUIRED_V5),
        "properties": {
            "evidence_kind": {"const": entry["evidence_kind"]},
            "route_kind": {"const": kind},
            "requested_url": {"const": requested},
            "intermediate_url": {"const": intermediate},
            "second_hop_location": {"const": raw_path},
            "final_url": {"const": final},
            "entry_status": {"type": "string", "enum": list(ENTRY_STATUSES)},
            "request_chain": {"oneOf": _chain_constants(entry)},
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
            # Const-pinned to the frozen final: the resolution result is recorded,
            # and an observed value can never occupy this field.
            "send3_request_url": {
                "enum": ([final, None] if kind == "redirect_twice_relative_path" else [None])
            },
            "send3_observed_status": {
                "type": ["integer", "null"], "minimum": _STATUS_MIN, "maximum": _STATUS_MAX,
            },
            "send3_observed_location": {"type": ["string", "null"], "maxLength": LOCATION_MAX_LENGTH},
            "send3_observed_location_disposition": {"enum": list(LOCATION_DISPOSITIONS)},
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


def expected_receipt_schema_v5() -> dict[str, Any]:
    """The complete locked 0.5.0 schema. The committed file is generated from this."""
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": RECEIPT_SCHEMA_ID_V5,
        "title": RECEIPT_CONTRACT_V5,
        "comment": (
            "ADR-041 (E-C-D4). Successor to documentation_collection_receipt@0.4.0, "
            "which is never modified because its frozen routes are const-pinned "
            "inside its committed schema and a live receipt instantiates it. v0.5 "
            "corrects route grammar only and collects no content evidence. Two "
            "kinds: redirect_twice_relative_path performs three sends, where send "
            "one's Location must be byte-exact against the frozen intermediate and "
            "send two's Location must be a bare absolute-path reference -- one "
            "leading slash, no protocol-relative prefix, scheme, host, userinfo, "
            "query, fragment, backslash or dot-dot segment -- byte-exact against "
            "the frozen raw path, whose mechanical join to a fixed declared base "
            "must reproduce the frozen final URL byte-exactly; redirect_once "
            "performs two. There is no direct kind: every route performs at least "
            "one recognized hop. E1's second-hop Location is a governed observation "
            "from attempt docattempt-921cb253da290dc5dadadd5afc7244d6; E2's and "
            "E3's chain information is human/agent-supplied curl design input, not "
            "governed raw evidence. request_chain and send3_request_url are pinned "
            "to frozen constants, so an observed value can never enter either and "
            "is never followed merely because it was observed. The receipt owns "
            "retrieval_status only; whether the bytes carry the required official "
            "claim belongs to documentation_evidence_validation@0.1.0."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": sorted(RECEIPT_REQUIRED_V5),
        "properties": {
            "contract": {"const": RECEIPT_CONTRACT_V5},
            "schema_version": {"const": SCHEMA_VERSION_V5},
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
                "prefixItems": [_entry_schema_v5(e) for e in FROZEN_ROUTE_IDENTITIES_V5],
                "items": False,
            },
            "completion_status": {"type": "string", "enum": list(COMPLETION_STATUSES)},
        },
        "oneOf": [_sequence_branch(c, s) for c, s in TERMINAL_SEQUENCES],
    }


class _DuplicateMemberError(ValueError):
    """A JSON object repeated a member name; the parser would hide one value."""


def _reject_duplicate_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    seen: set[str] = set()
    for name, _ in pairs:
        if name in seen:
            raise _DuplicateMemberError(name)
        seen.add(name)
    return dict(pairs)


def _json_exact_equal(left: Any, right: Any) -> bool:
    """Recursive, JSON-type-exact comparison: True == 1 and 3 == 3.0 in Python."""
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


def validate_receipt_schema_v5_bytes(schema_bytes: Any) -> str:
    """Prove the bytes are the locked 0.5.0 schema, semantically, and return the digest."""
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

    properties = schema.get("properties")
    if isinstance(properties, dict):
        contract = properties.get("contract")
        if isinstance(contract, dict):
            declared = contract.get("const")
            if (
                isinstance(declared, str)
                and not isinstance(declared, bool)
                and declared.strip()
                and declared != RECEIPT_CONTRACT_V5
            ):
                _refuse(
                    "properties.contract.const identifies a different contract",
                    "receipt_schema_contract_mismatch",
                )

    required = schema.get("required")
    if isinstance(required, list) and all(isinstance(name, str) for name in required):
        if len(required) != len(set(required)):
            _refuse("the receipt schema required list carries duplicates")

    if not _json_exact_equal(schema, expected_receipt_schema_v5()):
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
    if entry.get(f"{ordinal}_observed_status") is not None:
        return f"{ordinal}_observed_status must be null when no send occurred"
    if entry.get(f"{ordinal}_observed_location") is not None:
        return f"{ordinal}_observed_location must be null when no send occurred"
    if entry.get(f"{ordinal}_observed_location_disposition") != "no_response":
        return f"{ordinal}_observed_location_disposition must be no_response"
    return None


def _entry_violations_v5(entry: Any, frozen: dict[str, Any]) -> str | None:
    if not isinstance(entry, dict) or frozenset(entry) != ENTRY_PROPERTIES_V5:
        return "an entry does not carry exactly the locked property set"
    for field in (
        "evidence_kind", "route_kind", "requested_url",
        "intermediate_url", "second_hop_location", "final_url",
    ):
        if entry.get(field) != frozen[field]:
            return f"an entry does not carry its frozen {field}"

    kind = frozen["route_kind"]
    requested, final = frozen["requested_url"], frozen["final_url"]
    intermediate = frozen["intermediate_url"]
    raw_path = frozen["second_hop_location"]

    # Route-kind truthfulness, enforced independently of the declaration.
    if kind == "redirect_once":
        if intermediate is not None or raw_path is not None:
            return "a redirect_once route declares no intermediate hop"
        if requested == final:
            return "a redirect_once route must declare two different URLs"
    else:
        if not _nonblank(intermediate) or not _nonblank(raw_path):
            return "a two-hop route must declare an intermediate and a raw path"
        if absolute_path_reference_violation(raw_path) is not None:
            return "a two-hop route's frozen raw path is not an absolute-path reference"
        if resolve_absolute_path_reference(raw_path) != final:
            return "a two-hop route's raw path must resolve to its frozen final URL"
        if len({requested, intermediate, final}) != 3:
            return "a two-hop route declares three distinct URLs"

    status = entry.get("entry_status")
    if status not in ENTRY_STATUSES:
        return "unknown entry status"
    for ordinal in _SEND_ORDINALS:
        violation = _binding_violation(entry, ordinal)
        if violation is not None:
            return violation

    send3_url = entry.get("send3_request_url")
    if kind == "redirect_once":
        if send3_url is not None:
            return "a redirect_once route issues no third send"
    elif send3_url is not None and send3_url != final:
        return "send3_request_url must be the resolved frozen final URL"

    if status == "succeeded":
        if entry.get("failure_reason") is not None or entry.get("failure_phase") is not None:
            return "a succeeded entry carries no failure reason or phase"
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
        if kind == "redirect_once":
            if entry.get("request_chain") != [requested, final]:
                return "a succeeded redirect_once entry records its own two sends"
            if entry.get("send1_observed_status") not in REDIRECT_STATUSES_V5:
                return "a succeeded redirect_once entry records an accepted hop status"
            if entry.get("send1_observed_location") != final:
                return "a succeeded redirect_once entry records the frozen hop target"
            if entry.get("send2_observed_status") != TERMINAL_STATUS_V5:
                return "a succeeded redirect_once entry records status 200 on send two"
            violation = _no_send_violation(entry, "send3")
            if violation is not None:
                return f"a succeeded redirect_once entry issues no third send: {violation}"
        else:
            if entry.get("request_chain") != [requested, intermediate, final]:
                return "a succeeded two-hop entry records its own three sends"
            if entry.get("send1_observed_status") not in REDIRECT_STATUSES_V5:
                return "a succeeded two-hop entry records an accepted first-hop status"
            if entry.get("send1_observed_location") != intermediate:
                return "a succeeded two-hop entry records the frozen intermediate"
            if entry.get("send2_observed_status") not in REDIRECT_STATUSES_V5:
                return "a succeeded two-hop entry records an accepted second-hop status"
            if entry.get("send2_observed_location") != raw_path:
                return "a succeeded two-hop entry records the frozen raw path"
            if entry.get("send3_request_url") != final:
                return "a succeeded two-hop entry records the resolved final URL"
            if entry.get("send3_observed_status") != TERMINAL_STATUS_V5:
                return "a succeeded two-hop entry records status 200 on send three"
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
        if entry.get("failure_reason") is not None or entry.get("failure_phase") is not None:
            return "a not_attempted entry carries no failure reason or phase"
        if entry.get("retrieval_timestamp") is not None:
            return "a not_attempted entry records no retrieval timestamp"
        if entry.get("send3_request_url") is not None:
            return "a not_attempted entry resolved no third request"
        for ordinal in _SEND_ORDINALS:
            violation = _no_send_violation(entry, ordinal)
            if violation is not None:
                return f"a not_attempted entry made no send: {violation}"
        return None

    # failed
    reason = entry.get("failure_reason")
    phase = entry.get("failure_phase")
    if reason not in ROUTE_KIND_REASONS_V5[kind]:
        return "a failed entry needs a reason its route kind can produce"
    if phase not in ROUTE_KIND_PHASES_V5[kind]:
        return "a failed entry needs a phase its route kind can reach"
    if phase not in REASON_PHASES_V5[reason]:
        return "a failed entry names a phase its reason cannot arise in"

    if phase == "persistence":
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

    if phase == "entry_preflight":
        if entry.get("request_chain") != []:
            return "an entry_preflight failure initiated no request"
        for ordinal in _SEND_ORDINALS:
            violation = _no_send_violation(entry, ordinal)
            if violation is not None:
                return f"an entry_preflight failure made no send: {violation}"
        return None

    if not _is_utc_instant(entry.get("retrieval_timestamp")):
        return "a failure after the clock read records its request-start instant"

    expected_chain = _expected_chain_for_phase(kind, phase, requested, intermediate, final)
    if entry.get("request_chain") != expected_chain:
        return "a failed entry records a chain that is not the one its phase implies"

    if phase == "send1_request":
        for ordinal in _SEND_ORDINALS:
            violation = _no_send_violation(entry, ordinal)
            if violation is not None:
                return f"a send1_request failure received no response: {violation}"
        return None
    if phase == "send1_evaluation":
        if not _status_ok(entry.get("send1_observed_status")):
            return "a send1_evaluation failure records the status it evaluated"
        for ordinal in ("send2", "send3"):
            violation = _no_send_violation(entry, ordinal)
            if violation is not None:
                return f"a send1_evaluation failure issued no later send: {violation}"
        return None

    # Past send one, the first hop must have been accepted.
    accepted_first = final if kind == "redirect_once" else intermediate
    if entry.get("send1_observed_location") != accepted_first:
        return "a post-first-hop failure records the accepted first-hop target"
    if entry.get("send1_observed_status") not in REDIRECT_STATUSES_V5:
        return "a post-first-hop failure records an accepted first-hop status"

    if phase in ("send2_preflight", "send2_request"):
        for ordinal in ("send2", "send3"):
            violation = _no_send_violation(entry, ordinal)
            if violation is not None:
                return f"a pre-response send-two failure received no response: {violation}"
        return None
    if phase == "send2_evaluation":
        if not _status_ok(entry.get("send2_observed_status")):
            return "a send2_evaluation failure records the status it evaluated"
        violation = _no_send_violation(entry, "send3")
        if violation is not None:
            return f"a send2_evaluation failure issued no third send: {violation}"
        return None

    # send3_* and persistence: the second hop must have been accepted too.
    if entry.get("send2_observed_location") != raw_path:
        return "a post-second-hop failure records the accepted raw path"
    if entry.get("send2_observed_status") not in REDIRECT_STATUSES_V5:
        return "a post-second-hop failure records an accepted second-hop status"
    if entry.get("send3_request_url") != final:
        return "a post-second-hop failure records the resolved final URL"
    if phase in ("send3_preflight", "send3_request"):
        violation = _no_send_violation(entry, "send3")
        if violation is not None:
            return f"a pre-response send-three failure received no response: {violation}"
        return None
    if phase == "send3_evaluation" and not _status_ok(entry.get("send3_observed_status")):
        return "a send3_evaluation failure records the status it evaluated"
    if phase == "persistence":
        terminal = "send2" if kind == "redirect_once" else "send3"
        if entry.get(f"{terminal}_observed_status") != TERMINAL_STATUS_V5:
            return "a persistence failure accepted a 200 on its terminal send"
    return None


def _expected_chain_for_phase(
    kind: str, phase: str, requested: str, intermediate: str | None, final: str
) -> list[str]:
    """The one chain a phase implies. Every value is a frozen constant."""
    if phase in ("send1_request", "send1_evaluation", "send2_preflight"):
        return [requested]
    if kind == "redirect_once":
        return [requested, final]
    if phase in ("send2_request", "send2_evaluation", "send3_preflight"):
        return [requested, intermediate]  # type: ignore[list-item]
    return [requested, intermediate, final]  # type: ignore[list-item]


def build_documentation_receipt_v5(
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
    """Assemble the 0.5.0 receipt, refusing anything the committed schema rejects."""
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

    if not isinstance(entries, list) or len(entries) != len(FROZEN_ROUTE_IDENTITIES_V5):
        _refuse("the receipt must carry exactly three positional entries")
    for entry, frozen in zip(entries, FROZEN_ROUTE_IDENTITIES_V5):
        violation = _entry_violations_v5(entry, frozen)
        if violation is not None:
            _refuse(violation)

    sequence = tuple(entry["entry_status"] for entry in entries)
    if (completion_status, sequence) not in TERMINAL_SEQUENCES:
        _refuse("the status sequence describes a run that cannot have happened")

    return {
        "contract": RECEIPT_CONTRACT_V5,
        "schema_version": SCHEMA_VERSION_V5,
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


def receipt_bytes_v5(receipt: dict[str, Any]) -> bytes:
    """Canonical serialization, matching the repository's convention."""
    return canonical_json_bytes(receipt)
