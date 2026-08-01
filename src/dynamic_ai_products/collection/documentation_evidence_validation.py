"""Documentation evidence validation v0.1.0 (ADR-042, E-M-S validation).

**What this contract is for.** ADR-037 declared that a collection receipt owns
*retrieval status only* -- whether the bytes carry the required official claim was
deliberately left to a later, separate contract. This is that contract. The v0.5
attempt ``docattempt-ef3032c82e618c8ace8e33b26326d5c6`` completed and persisted
three raw documents; this module decides, offline and fail-closed, whether a
specific human-selected byte range of a specific persisted document actually
contains specific literal text.

**What it deliberately does not do.** No HTML parser, no renderer, no entity
decoding, no whitespace normalization, no model, no network, no clock. Those are
all ways of turning "the bytes say X" into "something like X was probably meant",
and every one of them would let a claim survive a change in the evidence. The
verification is therefore restricted to five mechanical facts:

1. the receipt is the pinned one (digest, contract id, schema digest);
2. the raw object is the pinned one (digest **and** byte count);
3. the selected byte range lies inside the object and hashes to its pin;
4. the range decodes under **strict** UTF-8;
5. each required literal occurs in the decoded range, and each forbidden literal
   does not -- exact substring containment, no transformation of either side.

**The selection is a human act, and is labelled as one.** Which byte range answers
a question is a judgement this module never makes and never re-derives. It records
the range, proves the range is what it claims to be, and proves the literals are in
it. The ``claim`` string attached to each finding is the human's reading, carried
verbatim as an attributed statement -- not something the code inferred.

**Qualifiers travel with claims.** Where the source qualifies a statement, the
qualifier is bound as a required literal too, so a future edit that drops it
breaks validation. Two are load-bearing here: ``CountTokens`` is free of charge
*and* carries a 3000 requests-per-minute maximum quota, so no "there is no quota"
claim may be built from it; and ``thinking_budget = 0`` suppresses returned
thought content *while reasoning-style text may still appear in the output*.
"""

from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..provenance import WriteOnceError, write_bytes_once
from .errors import CollectionError
from .publication import canonical_json_bytes

__all__ = [
    "ATTEMPT_BINDING",
    "EVIDENCE_VALIDATION_CONTRACT",
    "EVIDENCE_VALIDATION_SCHEMA_ID",
    "FROZEN_SELECTIONS",
    "PRICING_UNITS",
    "SCHEMA_VERSION",
    "SELECTION_PROVENANCE",
    "SUBJECT",
    "build_evidence_validation_record",
    "canonical_raw_reference",
    "expected_canonical_record",
    "expected_validation_schema",
    "publish_evidence_validation_record",
    "usage_cost_microdollars",
    "validate_selection",
    "validate_validation_schema_bytes",
    "validation_record_bytes",
]

EVIDENCE_VALIDATION_CONTRACT = "documentation_evidence_validation@0.1.0"
EVIDENCE_VALIDATION_SCHEMA_ID = "documentation_evidence_validation.schema.json"
SCHEMA_VERSION = "0.1.0"
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"
SHA256_PATTERN = "^[0-9a-f]{64}$"
ATTEMPT_ID_PATTERN = "^docattempt-[0-9a-f]{32}$"

SUBJECT = "vertex_ai_gemini_2_5_flash"
# The range is chosen by a person; this module proves what the range *is*, never
# why it was chosen.
SELECTION_PROVENANCE = "human_selected_byte_slice_v1"
DECODE_MODE = "utf_8_strict"
NORMALIZATION = "none"

# The hash-bound starting point. A validation record may only be built from this
# exact attempt: a different receipt is a different question.
ATTEMPT_BINDING: dict[str, str] = {
    "attempt_id": "docattempt-ef3032c82e618c8ace8e33b26326d5c6",
    "receipt_sha256": "eeb8287ecceddb35ad4eef5c36f14fa94ef04b2bff5f8b25bcba27d59a6841a3",
    "receipt_contract": "documentation_collection_receipt@0.5.0",
    "receipt_schema_sha256": (
        "307777c1e4df625b82a8186fb5260b2426c1425009d0f2da400a2e7b0655e5db"
    ),
}

# Canonical pricing units, expressed as exact integer ratios so no float ever
# touches a monetary quantity.
#
#   1 USD          = 1_000_000 microdollar
#   $0.30 / 1M tok =   300_000 / 1_000_000 = 3/10 microdollar per token
#   $2.50 / 1M tok = 2_500_000 / 1_000_000 = 5/2 microdollar per token
PRICING_UNITS: dict[str, Any] = {
    "model": "gemini-2.5-flash",
    "unit": "microdollar_per_token",
    "microdollar_per_usd": 1_000_000,
    "input_numerator": 3,
    "input_denominator": 10,
    "output_numerator": 5,
    "output_denominator": 2,
    "derivation": (
        "1 USD = 1000000 microdollar; $0.30 per 1000000 tokens = "
        "300000/1000000 = 3/10 microdollar per token; $2.50 per 1000000 tokens = "
        "2500000/1000000 = 5/2 microdollar per token"
    ),
    "cost_formula": "ceil(input_tokens * 3 / 10) + ceil(output_tokens * 5 / 2)",
    "prompt_length_tiers": 2,
    "tier_prices_equal": True,
}


def _ceil_div(numerator: int, denominator: int) -> int:
    """Integer ceiling division. No float ever touches a monetary quantity.

    ``ceil(a * n / d)`` looked equivalent but is not: ``a * n / d`` is a float
    division, so it loses precision above 2**53 and raises ``OverflowError`` for
    a token count too large to convert. ``(x + d - 1) // d`` is exact for every
    non-negative integer Python can represent.
    """
    return (numerator + denominator - 1) // denominator


def usage_cost_microdollars(*, input_tokens: int, output_tokens: int) -> int:
    """Exact integer cost in microdollars. No float arithmetic anywhere.

    Each side is rounded up independently, which is what the declared formula
    says; summing first and rounding once would be a different rule.
    """
    for value in (input_tokens, output_tokens):
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise CollectionError(
                "token counts must be non-negative integers",
                reason_code="validation_input_invalid",
            )
    return (
        _ceil_div(
            input_tokens * PRICING_UNITS["input_numerator"],
            PRICING_UNITS["input_denominator"],
        )
        + _ceil_div(
            output_tokens * PRICING_UNITS["output_numerator"],
            PRICING_UNITS["output_denominator"],
        )
    )


# --- the frozen selections ----------------------------------------------------
#
# Every literal below was measured present in the pinned slice before being
# frozen. Multi-line literals bind a value to its own table row, which a bare
# "$0.30 appears somewhere" check could not do.

FROZEN_SELECTIONS: tuple[dict[str, Any], ...] = (
    {
        "evidence_kind": "gemini_thinking",
        "raw_sha256": "e47448c0d68f0465035af00aac7f8969ffdcfebf7a491f444b3bd81c4503df7d",
        "raw_byte_count": 624675,
        "slice_start": 367041,
        "slice_stop": 369448,
        "slice_sha256": (
            "b6a6195df8dbfc21b329f029999981ca1c2f17fe19edeb18d558cf85b28c533c"
        ),
        "required_literals": (
            "For models earlier than Gemini 3",
            "thinking_budget",
            "not set, the model automatically controls how much it thinks",
            # Binds 1..24,576 to Gemini 2.5 Flash specifically, not to the table.
            "<td>Gemini 2.5 Flash</td>\n<td>1</td>\n<td>24,576</td>",
            "set the budget to 0 to prevent thought content from being",
            "no thought content is returned with the",
            # The qualifier: suppressed thought content is not suppressed reasoning text.
            "However, reasoning-style text might still be present in the model",
            "thinking_level",
            "parameter with a model earlier than Gemini 3, the",
            "model returns an error",
        ),
        "forbidden_literals": (),
        "claim": (
            "For Gemini 2.5 Flash (a model earlier than Gemini 3), thinking is "
            "controlled by thinking_budget: when unset the model controls it "
            "automatically, the settable range is 1 to 24,576 tokens, and setting it "
            "to 0 prevents thought content from being returned -- though the source "
            "qualifies that reasoning-style text may still appear in the output. "
            "Using thinking_level with a model earlier than Gemini 3 makes the model "
            "return an error."
        ),
    },
    {
        "evidence_kind": "count_tokens",
        "raw_sha256": "e7cb9e6b4142ea79f9f39c905fd8b2395c090826ec5d03e59a1e36da3c9fda4d",
        "raw_byte_count": 284918,
        "slice_start": 251498,
        "slice_stop": 251819,
        "slice_sha256": (
            "6491feec0ef68e1aa300882291f4a29929ae846150d850a5ba2c44938029f6d5"
        ),
        "required_literals": (
            "There is no charge or quota restriction for using the",
            "CountTokens",
            # The qualifier, bound so that "there is no quota at all" cannot be
            # built from this slice: the same passage states a 3000 RPM maximum.
            "maximum quota for the",
            "3000 requests per minute",
        ),
        "forbidden_literals": (),
        "claim": (
            "The CountTokens API carries no monetary charge. The same passage also "
            "states a maximum quota of 3000 requests per minute, so this evidence "
            "supports a zero-price claim and a 3000 RPM rate-limit claim together; "
            "it does not support a claim that no quota applies."
        ),
    },
    {
        "evidence_kind": "pricing_standard",
        "raw_sha256": "2c96306a245ba39051e0f5c5a2b1359fd55425f6b7e7f17a2c5b4f57ca0fd3fc",
        "raw_byte_count": 828714,
        "slice_start": 681132,
        "slice_stop": 681752,
        "slice_sha256": (
            "cf451af8ca6860efb6d03d71b77ff81c026e9c76506ebf32f742872cf4bcaa6e"
        ),
        "required_literals": (
            "Gemini 2.5<br>Flash",
            # Row-bound: the two prompt-length tier cells belong to this row.
            "<td>Input (text, image, video)</td>\n           <td>$0.30</td>\n"
            "           <td>$0.30</td>\n           ",
            "<td>Text output (response and reasoning)</td>\n           <td>$2.50</td>\n"
            "           <td>$2.50</td>\n           ",
        ),
        "forbidden_literals": (),
        "claim": (
            "For Gemini 2.5 Flash, text/image/video input is $0.30 per 1M tokens and "
            "text output (response and reasoning) is $2.50 per 1M tokens, with the "
            "same price in both prompt-length tiers."
        ),
    },
)

_KIND_ORDER: tuple[str, ...] = tuple(s["evidence_kind"] for s in FROZEN_SELECTIONS)

# Exactly the fields a selection must carry. Checked as a set before any lookup.
_SELECTION_FIELDS: frozenset[str] = frozenset(
    {
        "evidence_kind", "raw_sha256", "raw_byte_count",
        "slice_start", "slice_stop", "slice_sha256",
        "required_literals", "forbidden_literals", "claim",
    }
)

VALIDATION_REASON_CODES: frozenset[str] = frozenset(
    {
        "validation_input_invalid",
        "validation_record_not_canonical",
        "validation_schema_invalid",
        "validation_schema_contract_mismatch",
        "receipt_binding_mismatch",
        "receipt_entry_missing",
        "raw_object_missing",
        "raw_digest_mismatch",
        "raw_byte_count_mismatch",
        "slice_bounds_invalid",
        "slice_digest_mismatch",
        "slice_not_utf8",
        "required_literal_absent",
        "forbidden_literal_present",
        "record_publication_failed",
        "destination_exists",
    }
)


def _refuse(message: str, code: str) -> None:
    raise CollectionError(message, reason_code=code)


def _is_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(re.fullmatch(SHA256_PATTERN, value))


def _positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


# --- the pure verification engine ---------------------------------------------


def validate_selection(selection: dict[str, Any], raw_bytes: bytes) -> dict[str, Any]:
    """Verify one selection against one object's bytes. Pure; no I/O.

    Returns the finding record. Raises :class:`CollectionError` on any mismatch --
    there is no partial success and no "close enough".
    """
    if not isinstance(raw_bytes, (bytes, bytearray)):
        _refuse("raw bytes are required", "validation_input_invalid")
    raw_bytes = bytes(raw_bytes)

    # Every shape check happens before any field is indexed, so a malformed
    # selection can only ever produce a CollectionError -- never a KeyError,
    # TypeError or AttributeError escaping to the caller.
    if not isinstance(selection, dict):
        _refuse("a selection must be a mapping", "validation_input_invalid")
    missing = _SELECTION_FIELDS - frozenset(selection)
    if missing:
        _refuse("a selection is missing a required field", "validation_input_invalid")
    if not isinstance(selection["evidence_kind"], str) or not selection["evidence_kind"]:
        _refuse("evidence_kind must be a non-empty string", "validation_input_invalid")
    if not isinstance(selection["claim"], str) or not selection["claim"]:
        _refuse("claim must be a non-empty string", "validation_input_invalid")
    for field in ("raw_sha256", "slice_sha256"):
        if not _is_digest(selection[field]):
            _refuse(f"{field} is not a lowercase 64-hex digest", "validation_input_invalid")
    for field in ("raw_byte_count", "slice_start", "slice_stop"):
        if not _positive_int(selection[field]):
            _refuse(f"{field} must be a non-negative integer", "validation_input_invalid")
    for field in ("required_literals", "forbidden_literals"):
        value = selection[field]
        # ``str`` is a sequence of ``str``: a bare string would iterate character
        # by character and silently check the wrong thing.
        if isinstance(value, (str, bytes)) or not isinstance(value, (list, tuple)):
            _refuse(f"{field} must be a list or tuple", "validation_input_invalid")
    start, stop = selection["slice_start"], selection["slice_stop"]

    if len(raw_bytes) != selection["raw_byte_count"]:
        _refuse("the raw object byte count does not match", "raw_byte_count_mismatch")
    if sha256(raw_bytes).hexdigest() != selection["raw_sha256"]:
        _refuse("the raw object digest does not match", "raw_digest_mismatch")
    # Bounds are checked before slicing: Python would silently clamp an
    # out-of-range slice and hand back a shorter span than was declared.
    if not (start < stop <= len(raw_bytes)):
        _refuse("the selected range is not inside the object", "slice_bounds_invalid")

    segment = raw_bytes[start:stop]
    if sha256(segment).hexdigest() != selection["slice_sha256"]:
        _refuse("the selected range digest does not match", "slice_digest_mismatch")
    try:
        text = segment.decode("utf-8")
    except UnicodeDecodeError:
        _refuse("the selected range is not strict UTF-8", "slice_not_utf8")

    # Exact containment on both sides. Neither the haystack nor the needle is
    # normalized, unescaped or re-encoded, so an entity change or a whitespace
    # change in the source is a validation failure rather than an invisible pass.
    for literal in selection["required_literals"]:
        if not isinstance(literal, str) or not literal:
            _refuse("a required literal must be a non-empty string", "validation_input_invalid")
        if literal not in text:
            _refuse("a required literal is absent from the selected range",
                    "required_literal_absent")
    for literal in selection["forbidden_literals"]:
        if not isinstance(literal, str) or not literal:
            _refuse("a forbidden literal must be a non-empty string", "validation_input_invalid")
        if literal in text:
            _refuse("a forbidden literal occurs in the selected range",
                    "forbidden_literal_present")

    return {
        "evidence_kind": selection["evidence_kind"],
        "raw_sha256": selection["raw_sha256"],
        "raw_byte_count": selection["raw_byte_count"],
        "slice_start": start,
        "slice_stop": stop,
        "slice_byte_count": stop - start,
        "slice_sha256": selection["slice_sha256"],
        "required_literal_count": len(selection["required_literals"]),
        "forbidden_literal_count": len(selection["forbidden_literals"]),
        "required_literals": list(selection["required_literals"]),
        "forbidden_literals": list(selection["forbidden_literals"]),
        "claim": selection["claim"],
        "claim_attribution": "human_reading_of_the_verified_range",
    }


def _require_receipt_binding(receipt_bytes: bytes) -> dict[str, Any]:
    """The record may only be built from the one pinned receipt."""
    if not isinstance(receipt_bytes, (bytes, bytearray)) or not receipt_bytes:
        _refuse("receipt bytes are required", "validation_input_invalid")
    receipt_bytes = bytes(receipt_bytes)
    if sha256(receipt_bytes).hexdigest() != ATTEMPT_BINDING["receipt_sha256"]:
        _refuse("the receipt digest does not match the pinned attempt",
                "receipt_binding_mismatch")
    try:
        receipt = json.loads(receipt_bytes.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        _refuse("the receipt is not valid UTF-8 JSON", "validation_input_invalid")
    if not isinstance(receipt, dict):
        _refuse("the receipt must be a JSON object", "validation_input_invalid")
    for field, pin in (
        ("attempt_id", ATTEMPT_BINDING["attempt_id"]),
        ("contract", ATTEMPT_BINDING["receipt_contract"]),
        ("receipt_schema_sha256", ATTEMPT_BINDING["receipt_schema_sha256"]),
    ):
        if receipt.get(field) != pin:
            _refuse("the receipt does not carry the pinned attempt identity",
                    "receipt_binding_mismatch")
    if receipt.get("completion_status") != "completed":
        _refuse("only a completed attempt may be validated", "receipt_binding_mismatch")
    return receipt


def _require_raw_objects(raw_objects: Any) -> None:
    """Validate the container before any ``in`` test or subscript.

    Measured leaks this closes: ``None`` and ``int`` raised ``TypeError`` from the
    membership test, and a ``str`` whose text happens to contain an evidence kind
    passed the membership test and then raised ``TypeError`` on subscript. A
    ``list`` or ``tuple`` reported ``raw_object_missing``, which named the wrong
    failure -- the container was malformed, not the entry absent.
    """
    if not isinstance(raw_objects, dict):
        _refuse("raw_objects must be a mapping of evidence kind to bytes",
                "validation_input_invalid")
    for key, value in raw_objects.items():
        if not isinstance(key, str) or not key:
            _refuse("raw_objects keys must be non-empty strings",
                    "validation_input_invalid")
        if not isinstance(value, (bytes, bytearray)):
            _refuse("raw_objects values must be bytes", "validation_input_invalid")


def canonical_raw_reference(selection: dict[str, Any]) -> str:
    """Where the persisted object for a selection must live. Fully derived."""
    return f"{selection['evidence_kind']}/sha256-{selection['raw_sha256']}/document.html"


def build_evidence_validation_record(
    *, receipt_bytes: bytes, raw_objects: dict[str, bytes]
) -> dict[str, Any]:
    """Build the canonical validation record, or refuse. Pure; performs no I/O.

    The canonical path takes **no** selection or binding argument. Accepting one
    would let a caller hand in their own selections, get them wrapped in the
    locked contract identity, and publish the result as though the contract had
    vouched for them. Offline tests reach the parameterised engine through
    :func:`_build_record_noncanonical`, which is private and explicitly not the
    contract.

    ``raw_objects`` maps evidence kind to the persisted bytes. Each must be the
    object the receipt itself recorded for that kind, and each must satisfy its
    frozen selection.
    """
    return _build_record_noncanonical(
        receipt_bytes=receipt_bytes,
        raw_objects=raw_objects,
        selections=FROZEN_SELECTIONS,
        attempt_binding=ATTEMPT_BINDING,
    )


def _build_record_noncanonical(
    *,
    receipt_bytes: bytes,
    raw_objects: dict[str, bytes],
    selections: tuple[dict[str, Any], ...],
    attempt_binding: dict[str, str],
) -> dict[str, Any]:
    """The parameterised engine. Private, and never the published contract.

    A record produced with anything other than the frozen constants will fail
    :func:`_require_canonical_record` and therefore cannot be published.
    """
    _require_raw_objects(raw_objects)
    receipt = _require_receipt_binding(receipt_bytes)
    entries = receipt.get("entries")
    if not isinstance(entries, list):
        _refuse("the receipt carries no entries", "validation_input_invalid")
    by_kind = {
        e.get("evidence_kind"): e for e in entries if isinstance(e, dict)
    }

    findings: list[dict[str, Any]] = []
    for selection in selections:
        kind = selection["evidence_kind"]
        entry = by_kind.get(kind)
        if entry is None or entry.get("entry_status") != "succeeded":
            _refuse("the receipt has no succeeded entry for this evidence kind",
                    "receipt_entry_missing")
        # The object being validated must be the one this attempt persisted.
        if entry.get("content_sha256") != selection["raw_sha256"]:
            _refuse("the receipt records a different digest for this evidence kind",
                    "receipt_binding_mismatch")
        if entry.get("byte_count") != selection["raw_byte_count"]:
            _refuse("the receipt records a different byte count for this evidence kind",
                    "receipt_binding_mismatch")
        if kind not in raw_objects:
            _refuse("a raw object was not supplied for this evidence kind",
                    "raw_object_missing")
        finding = validate_selection(selection, raw_objects[kind])
        finding["raw_reference"] = entry.get("raw_reference")
        findings.append(finding)

    return {
        "contract": EVIDENCE_VALIDATION_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "subject": SUBJECT,
        "attempt_binding": dict(attempt_binding),
        "selection_provenance": SELECTION_PROVENANCE,
        "decode": DECODE_MODE,
        "normalization": NORMALIZATION,
        "findings": findings,
        "pricing_units": dict(PRICING_UNITS),
    }


def validation_record_bytes(record: dict[str, Any]) -> bytes:
    """Canonical serialization, matching the repository's convention."""
    return canonical_json_bytes(record)


def expected_canonical_record(raw_references: dict[str, str]) -> dict[str, Any]:
    """Every field a locked v0.1 record must carry, derived from frozen constants.

    ``raw_references`` is supplied only so the caller's own values can be
    compared; each is independently required to equal
    :func:`canonical_raw_reference` for its selection, so nothing here is taken
    on trust.
    """
    findings = []
    for selection in FROZEN_SELECTIONS:
        kind = selection["evidence_kind"]
        findings.append(
            {
                "evidence_kind": kind,
                "raw_reference": raw_references.get(kind),
                "raw_sha256": selection["raw_sha256"],
                "raw_byte_count": selection["raw_byte_count"],
                "slice_start": selection["slice_start"],
                "slice_stop": selection["slice_stop"],
                "slice_byte_count": selection["slice_stop"] - selection["slice_start"],
                "slice_sha256": selection["slice_sha256"],
                "required_literal_count": len(selection["required_literals"]),
                "forbidden_literal_count": len(selection["forbidden_literals"]),
                "required_literals": list(selection["required_literals"]),
                "forbidden_literals": list(selection["forbidden_literals"]),
                "claim": selection["claim"],
                "claim_attribution": "human_reading_of_the_verified_range",
            }
        )
    return {
        "contract": EVIDENCE_VALIDATION_CONTRACT,
        "schema_version": SCHEMA_VERSION,
        "subject": SUBJECT,
        "attempt_binding": dict(ATTEMPT_BINDING),
        "selection_provenance": SELECTION_PROVENANCE,
        "decode": DECODE_MODE,
        "normalization": NORMALIZATION,
        "findings": findings,
        "pricing_units": dict(PRICING_UNITS),
    }


def _require_canonical_record(record: Any) -> None:
    """Refuse anything that is not the locked v0.1 record, before any write.

    Write-once alone is not enough: it stops a *second* write, not a *first*
    write of the wrong thing. An altered binding, selector, literal, claim,
    price or raw reference is refused here, so no target file is ever created.
    """
    if not isinstance(record, dict):
        _refuse("a validation record must be a mapping", "validation_input_invalid")
    findings = record.get("findings")
    if not isinstance(findings, list) or len(findings) != len(FROZEN_SELECTIONS):
        _refuse("a validation record carries exactly three findings",
                "validation_record_not_canonical")
    references: dict[str, str] = {}
    for finding, selection in zip(findings, FROZEN_SELECTIONS):
        if not isinstance(finding, dict):
            _refuse("a finding must be a mapping", "validation_record_not_canonical")
        reference = finding.get("raw_reference")
        # Derived, not accepted: the reference must be the one the digest implies.
        if reference != canonical_raw_reference(selection):
            _refuse("a finding does not carry its derived raw reference",
                    "validation_record_not_canonical")
        references[selection["evidence_kind"]] = reference
    if not _json_exact_equal(record, expected_canonical_record(references)):
        _refuse("the validation record is not the locked v0.1 record",
                "validation_record_not_canonical")


def publish_evidence_validation_record(target: Path, record: dict[str, Any]) -> str:
    """Write the record once, and only if it is the locked v0.1 record."""
    _require_canonical_record(record)
    payload = validation_record_bytes(record)
    try:
        return write_bytes_once(target, payload, what="documentation evidence validation")
    except WriteOnceError as exc:
        code = (
            "destination_exists" if exc.category == "destination_exists"
            else "record_publication_failed"
        )
        raise CollectionError("the validation record could not be written",
                              reason_code=code) from None
    except OSError:
        raise CollectionError("the validation record could not be written",
                              reason_code="record_publication_failed") from None


# --- the committed schema -----------------------------------------------------


def _finding_schema(selection: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(
            {
                "evidence_kind", "raw_reference", "raw_sha256", "raw_byte_count",
                "slice_start", "slice_stop", "slice_byte_count", "slice_sha256",
                "required_literal_count", "forbidden_literal_count",
                "required_literals", "forbidden_literals", "claim", "claim_attribution",
            }
        ),
        "properties": {
            "evidence_kind": {"const": selection["evidence_kind"]},
            "raw_reference": {"type": "string", "minLength": 1},
            "raw_sha256": {"const": selection["raw_sha256"]},
            "raw_byte_count": {"const": selection["raw_byte_count"]},
            "slice_start": {"const": selection["slice_start"]},
            "slice_stop": {"const": selection["slice_stop"]},
            "slice_byte_count": {
                "const": selection["slice_stop"] - selection["slice_start"]
            },
            "slice_sha256": {"const": selection["slice_sha256"]},
            "required_literal_count": {"const": len(selection["required_literals"])},
            "forbidden_literal_count": {"const": len(selection["forbidden_literals"])},
            "required_literals": {"const": list(selection["required_literals"])},
            "forbidden_literals": {"const": list(selection["forbidden_literals"])},
            "claim": {"const": selection["claim"]},
            "claim_attribution": {"const": "human_reading_of_the_verified_range"},
        },
    }


def expected_validation_schema() -> dict[str, Any]:
    """The complete locked schema. The committed file is generated from this."""
    return {
        "$schema": SCHEMA_DIALECT,
        "$id": EVIDENCE_VALIDATION_SCHEMA_ID,
        "title": EVIDENCE_VALIDATION_CONTRACT,
        "comment": (
            "ADR-042. Offline, fail-closed validation of persisted documentation "
            "evidence. It answers only the question a collection receipt "
            "deliberately does not: whether a named byte range of a named persisted "
            "object contains named literal text. No HTML parser, renderer, entity "
            "decoder, whitespace normalizer, model or network is involved, so a "
            "claim cannot survive a change in the bytes it rests on. Every finding "
            "binds the pinned attempt receipt, the raw object digest and byte count, "
            "the byte range and its digest, strict UTF-8 decoding, and exact "
            "substring containment of each required literal plus absence of each "
            "forbidden literal. The byte range is a human selection, labelled as "
            "such, and the attached claim is an attributed human reading of the "
            "verified range rather than an inference the code performed. Source "
            "qualifiers are bound as required literals so that dropping one breaks "
            "validation: CountTokens is free of monetary charge and simultaneously "
            "carries a 3000 requests-per-minute maximum quota, and thinking_budget=0 "
            "suppresses returned thought content while reasoning-style text may "
            "still appear. Pricing is carried as exact integer ratios in "
            "microdollars per token, never as a float."
        ),
        "type": "object",
        "additionalProperties": False,
        "required": sorted(
            {
                "contract", "schema_version", "subject", "attempt_binding",
                "selection_provenance", "decode", "normalization", "findings",
                "pricing_units",
            }
        ),
        "properties": {
            "contract": {"const": EVIDENCE_VALIDATION_CONTRACT},
            "schema_version": {"const": SCHEMA_VERSION},
            "subject": {"const": SUBJECT},
            "attempt_binding": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(ATTEMPT_BINDING),
                "properties": {
                    "attempt_id": {
                        "const": ATTEMPT_BINDING["attempt_id"],
                        "pattern": ATTEMPT_ID_PATTERN,
                    },
                    "receipt_sha256": {"const": ATTEMPT_BINDING["receipt_sha256"]},
                    "receipt_contract": {"const": ATTEMPT_BINDING["receipt_contract"]},
                    "receipt_schema_sha256": {
                        "const": ATTEMPT_BINDING["receipt_schema_sha256"]
                    },
                },
            },
            "selection_provenance": {"const": SELECTION_PROVENANCE},
            "decode": {"const": DECODE_MODE},
            "normalization": {"const": NORMALIZATION},
            "findings": {
                "type": "array",
                "minItems": 3,
                "maxItems": 3,
                "prefixItems": [_finding_schema(s) for s in FROZEN_SELECTIONS],
                "items": False,
            },
            "pricing_units": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(PRICING_UNITS),
                "properties": {
                    key: {"const": value} for key, value in PRICING_UNITS.items()
                },
            },
        },
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


def validate_validation_schema_bytes(schema_bytes: Any) -> str:
    """Prove the bytes are the locked schema, semantically, and return the digest."""
    if not isinstance(schema_bytes, (bytes, bytearray)) or not schema_bytes:
        _refuse("validation schema bytes are required", "validation_schema_invalid")
    try:
        schema = json.loads(
            bytes(schema_bytes).decode("utf-8"),
            object_pairs_hook=_reject_duplicate_members,
        )
    except _DuplicateMemberError:
        _refuse("the validation schema repeats a member name", "validation_schema_invalid")
    except (UnicodeDecodeError, ValueError):
        _refuse("validation schema bytes are not valid UTF-8 JSON",
                "validation_schema_invalid")
    if not isinstance(schema, dict):
        _refuse("the validation schema must be a JSON object", "validation_schema_invalid")

    properties = schema.get("properties")
    if isinstance(properties, dict):
        contract = properties.get("contract")
        if isinstance(contract, dict):
            declared = contract.get("const")
            if (
                isinstance(declared, str)
                and not isinstance(declared, bool)
                and declared.strip()
                and declared != EVIDENCE_VALIDATION_CONTRACT
            ):
                _refuse("properties.contract.const identifies a different contract",
                        "validation_schema_contract_mismatch")

    if not _json_exact_equal(schema, expected_validation_schema()):
        _refuse("the validation schema does not match the locked definition",
                "validation_schema_invalid")
    return sha256(bytes(schema_bytes)).hexdigest()
