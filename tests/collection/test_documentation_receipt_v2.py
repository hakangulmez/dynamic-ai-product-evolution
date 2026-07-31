"""The documentation_collection_receipt@0.2.0 contract (ADR-038, E-C-D1).

Offline and pure: this file exercises the schema constructor, the loader and the
builder. Nothing here performs I/O outside ``tmp_path`` and nothing reaches a
network.

The committed file is *generated* from :func:`expected_receipt_schema_v2`, so the
first test below is the one that keeps them from drifting.
"""

from __future__ import annotations

import copy
import json
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.collection import documentation_receipt_v2 as v2
from dynamic_ai_products.collection.documentation_receipt import (
    ENTRY_RECORDABLE_REASONS,
    FROZEN_ENTRY_IDENTITIES,
    TERMINAL_SEQUENCES,
)
from dynamic_ai_products.collection.documentation_receipt import (
    expected_receipt_schema as expected_v1,
)
from dynamic_ai_products.collection.documentation_receipt import (
    validate_receipt_schema_bytes as validate_v1,
)
from dynamic_ai_products.collection.errors import CollectionError

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products" / "collection"
V2_PATH = ROOT / "schemas" / "documentation_collection_receipt.v2.schema.json"
V1_PATH = ROOT / "schemas" / "documentation_collection_receipt.schema.json"
V2_BYTES = V2_PATH.read_bytes()
V1_BYTES = V1_PATH.read_bytes()

STAMP = "2026-07-31T09:00:00Z"
COMMIT = "4d285669820ad610643be29d4ff790e94d61c90d"
ATTEMPT = "docattempt-" + "0" * 32
DIGEST = "a" * 64
BODY_DIGEST = sha256(b"<html></html>").hexdigest()

VALIDATOR = Draft202012Validator(v2.expected_receipt_schema_v2())
# Built from the committed **bytes**, not the constructor. The final-newline hole
# was invisible to ``re.fullmatch`` and only appeared when the real validator ran
# ``pattern`` as a search against the file that actually ships.
COMMITTED_VALIDATOR = Draft202012Validator(json.loads(V2_BYTES.decode("utf-8")))


def _serialize(schema: dict) -> bytes:
    return (json.dumps(schema, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _succeeded(index: int) -> dict:
    frozen = FROZEN_ENTRY_IDENTITIES[index]
    return {
        "evidence_kind": frozen["evidence_kind"],
        "requested_url": frozen["requested_url"],
        "final_url": frozen["final_url"],
        "entry_status": "succeeded",
        "request_chain": [frozen["requested_url"], frozen["final_url"]],
        "content_type": "text/html; charset=utf-8",
        "content_encoding": "identity",
        "byte_count": 13,
        "content_sha256": BODY_DIGEST,
        "raw_reference": f"{frozen['evidence_kind']}/sha256-{BODY_DIGEST}/document.html",
        "object_disposition": "created",
        "retrieval_timestamp": STAMP,
        "failure_reason": None,
        "failure_phase": None,
        "redirect_observed_status": 301,
        "redirect_observed_location": frozen["final_url"],
        "redirect_observed_location_disposition": "recorded",
        "terminal_observed_status": 200,
        "terminal_observed_location": None,
        "terminal_observed_location_disposition": "absent",
    }


def _blank(index: int, status: str) -> dict:
    frozen = FROZEN_ENTRY_IDENTITIES[index]
    return {
        "evidence_kind": frozen["evidence_kind"],
        "requested_url": frozen["requested_url"],
        "final_url": frozen["final_url"],
        "entry_status": status,
        "request_chain": [],
        "content_type": None,
        "content_encoding": None,
        "byte_count": None,
        "content_sha256": None,
        "raw_reference": None,
        "object_disposition": None,
        "retrieval_timestamp": None,
        "failure_reason": None,
        "failure_phase": None,
        "redirect_observed_status": None,
        "redirect_observed_location": None,
        "redirect_observed_location_disposition": "no_response",
        "terminal_observed_status": None,
        "terminal_observed_location": None,
        "terminal_observed_location_disposition": "no_response",
    }


def _failed(index: int, phase: str, reason: str) -> dict:
    """A minimally truthful failed entry for `phase`, matching the locked shape."""
    frozen = FROZEN_ENTRY_IDENTITIES[index]
    entry = _blank(index, "failed")
    entry["failure_reason"] = reason
    entry["failure_phase"] = phase
    order = list(v2.FAILURE_PHASES)
    position = order.index(phase)
    if position >= order.index("terminal_request"):
        entry["request_chain"] = [frozen["requested_url"], frozen["final_url"]]
    elif phase != "entry_preflight":
        entry["request_chain"] = [frozen["requested_url"]]
    if phase != "entry_preflight":
        entry["retrieval_timestamp"] = STAMP
    if position >= order.index("redirect_evaluation"):
        entry["redirect_observed_status"] = 301
        entry["redirect_observed_location"] = frozen["final_url"]
        entry["redirect_observed_location_disposition"] = "recorded"
    if position >= order.index("terminal_evaluation"):
        entry["terminal_observed_status"] = 200 if phase == "persistence" else 404
        entry["terminal_observed_location_disposition"] = "absent"
    if phase == "persistence":
        entry["content_type"] = "text/html"
        entry["content_encoding"] = "identity"
        entry["byte_count"] = 13
        entry["content_sha256"] = BODY_DIGEST
    return entry


def _build(entries: list[dict], completion: str) -> dict:
    return v2.build_documentation_receipt_v2(
        attempt_id=ATTEMPT,
        code_commit=COMMIT,
        run_created_at=STAMP,
        adapter_contract_sha256=DIGEST,
        policy_contract_sha256=DIGEST,
        receipt_schema_sha256=DIGEST,
        retrieval_timestamp_mode="caller_injected_request_start_utc_v1",
        entries=entries,
        completion_status=completion,
    )


# --- the committed file is generated from the constructor ---------------------


def test_the_committed_schema_is_exactly_the_constructor_output():
    assert V2_BYTES == _serialize(v2.expected_receipt_schema_v2())
    assert v2.validate_receipt_schema_v2_bytes(V2_BYTES) == sha256(V2_BYTES).hexdigest()


def test_the_schema_is_a_legal_2020_12_schema():
    Draft202012Validator.check_schema(v2.expected_receipt_schema_v2())


def test_the_contract_identity_is_the_successor():
    schema = v2.expected_receipt_schema_v2()
    assert schema["properties"]["contract"]["const"] == "documentation_collection_receipt@0.2.0"
    assert schema["properties"]["schema_version"]["const"] == "0.2.0"
    assert schema["$id"] == "documentation_collection_receipt.v2.schema.json"


# --- v1 and v2 reject each other ---------------------------------------------


def test_the_two_loaders_reject_each_other_s_file():
    with pytest.raises(CollectionError) as v2_on_v1:
        v2.validate_receipt_schema_v2_bytes(V1_BYTES)
    with pytest.raises(CollectionError) as v1_on_v2:
        validate_v1(V2_BYTES)
    assert v2_on_v1.value.reason_code == "receipt_schema_contract_mismatch"
    assert v1_on_v2.value.reason_code == "receipt_schema_contract_mismatch"


def test_v0_1_0_is_untouched_by_this_increment():
    """The live receipt must stay verifiable against the contract that made it."""
    assert validate_v1(V1_BYTES) == sha256(V1_BYTES).hexdigest()
    assert expected_v1()["properties"]["contract"]["const"].endswith("@0.1.0")
    assert "redirect_chain" in expected_v1()["properties"]["entries"]["prefixItems"][0][
        "properties"
    ]


# --- the loader closes the same gaps the v1 loader closes ---------------------


@pytest.mark.parametrize(
    "mutate,expected",
    [
        (lambda s: s["properties"]["entries"].__setitem__("minItems", 2), "receipt_schema_invalid"),
        (lambda s: s.__setitem__("additionalProperties", 0), "receipt_schema_invalid"),
        (
            lambda s: s["properties"]["attempt_id"].__setitem__("pattern", ".*"),
            "receipt_schema_invalid",
        ),
        (lambda s: s.__setitem__("oneOf", []), "receipt_schema_invalid"),
        (
            lambda s: s["properties"]["contract"].__setitem__("const", "other@0.1.0"),
            "receipt_schema_contract_mismatch",
        ),
    ],
    ids=["min-items", "additional-zero", "pattern-any", "empty-oneof", "foreign-contract"],
)
def test_a_weakened_schema_is_refused(mutate, expected):
    schema = copy.deepcopy(v2.expected_receipt_schema_v2())
    mutate(schema)
    with pytest.raises(CollectionError) as excinfo:
        v2.validate_receipt_schema_v2_bytes(_serialize(schema))
    assert excinfo.value.reason_code == expected


@pytest.mark.parametrize(
    "value,label",
    [(True, "bool-for-int"), (3.0, "float-for-int")],
)
def test_json_type_exactness_is_enforced(value, label):
    """True == 1 and 3 == 3.0 in Python; the comparator must not be fooled."""
    schema = copy.deepcopy(v2.expected_receipt_schema_v2())
    schema["properties"]["entries"]["minItems"] = value
    with pytest.raises(CollectionError) as excinfo:
        v2.validate_receipt_schema_v2_bytes(_serialize(schema))
    assert excinfo.value.reason_code == "receipt_schema_invalid", label


def test_a_duplicate_member_name_is_refused_at_any_depth():
    text = V2_BYTES.decode("utf-8")
    doubled = text.replace('"type": "object",', '"type": "object",\n  "type": "object",', 1)
    with pytest.raises(CollectionError) as excinfo:
        v2.validate_receipt_schema_v2_bytes(doubled.encode("utf-8"))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize("payload", [b"", b"not json", b"{}", None, "str", bytearray()])
def test_unusable_schema_bytes_are_refused(payload):
    with pytest.raises(CollectionError):
        v2.validate_receipt_schema_v2_bytes(payload)


def test_formatting_is_outside_the_comparison():
    compact = json.dumps(v2.expected_receipt_schema_v2(), separators=(",", ":")).encode()
    assert v2.validate_receipt_schema_v2_bytes(compact) == sha256(compact).hexdigest()


# --- the 20-field entry shape -------------------------------------------------


def test_the_entry_carries_exactly_twenty_locked_fields():
    assert len(v2.ENTRY_REQUIRED_V2) == 20
    assert "http_status" not in v2.ENTRY_REQUIRED_V2, "removed by 0.2.0"
    assert "redirect_chain" not in v2.ENTRY_REQUIRED_V2, "renamed to request_chain"
    assert "request_chain" in v2.ENTRY_REQUIRED_V2
    for field in (
        "failure_phase",
        "redirect_observed_status",
        "redirect_observed_location",
        "redirect_observed_location_disposition",
        "terminal_observed_status",
        "terminal_observed_location",
        "terminal_observed_location_disposition",
    ):
        assert field in v2.ENTRY_REQUIRED_V2, field
    entry_schema = v2.expected_receipt_schema_v2()["properties"]["entries"]["prefixItems"][0]
    assert entry_schema["additionalProperties"] is False
    assert set(entry_schema["properties"]) == set(v2.ENTRY_REQUIRED_V2)
    assert sorted(entry_schema["required"]) == sorted(v2.ENTRY_REQUIRED_V2)


# --- the structural non-authorization guarantee -------------------------------


def test_request_chain_is_pinned_to_three_constants_per_entry():
    """Provable from the schema alone: no observed value can enter the chain."""
    for index, frozen in enumerate(FROZEN_ENTRY_IDENTITIES):
        prefix = v2.expected_receipt_schema_v2()["properties"]["entries"]["prefixItems"][index]
        branches = prefix["properties"]["request_chain"]["oneOf"]
        assert [b["const"] for b in branches] == [
            [],
            [frozen["requested_url"]],
            [frozen["requested_url"], frozen["final_url"]],
        ]


def test_a_decoy_url_in_the_request_chain_is_refused_by_the_schema():
    decoy = "https://evil.test/decoy"
    receipt = _build([_succeeded(0), _succeeded(1), _succeeded(2)], "completed")
    receipt["entries"][0]["request_chain"] = [
        FROZEN_ENTRY_IDENTITIES[0]["requested_url"],
        decoy,
    ]
    assert list(VALIDATOR.iter_errors(receipt)), "the schema must reject a decoy chain"


def test_the_builder_refuses_a_decoy_request_chain():
    entries = [_succeeded(0), _succeeded(1), _succeeded(2)]
    entries[0]["request_chain"] = ["https://evil.test/decoy"]
    with pytest.raises(CollectionError):
        _build(entries, "completed")


# --- the phase / reason matrix ------------------------------------------------


def test_seven_phases_are_declared_in_progress_order():
    assert v2.FAILURE_PHASES == (
        "entry_preflight",
        "redirect_request",
        "redirect_evaluation",
        "terminal_preflight",
        "terminal_request",
        "terminal_evaluation",
        "persistence",
    )


def test_every_entry_recordable_reason_maps_to_declared_phases():
    assert set(v2.REASON_PHASES) == set(ENTRY_RECORDABLE_REASONS)
    assert len(v2.REASON_PHASES) == 20
    for reason, phases in v2.REASON_PHASES.items():
        assert phases, reason
        for phase in phases:
            assert phase in v2.FAILURE_PHASES, (reason, phase)


@pytest.mark.parametrize("reason", sorted(ENTRY_RECORDABLE_REASONS))
def test_each_reason_builds_and_validates_in_each_of_its_phases(reason):
    for phase in v2.REASON_PHASES[reason]:
        entries = [_failed(0, phase, reason), _blank(1, "not_attempted"), _blank(2, "not_attempted")]
        receipt = _build(entries, "stopped")
        assert not list(VALIDATOR.iter_errors(receipt)), (reason, phase)


@pytest.mark.parametrize(
    "reason,phase",
    [
        ("write_error", "entry_preflight"),
        ("retrieval_clock_invalid", "persistence"),
        ("redirect_location_mismatch", "terminal_evaluation"),
        ("entity_empty", "redirect_request"),
    ],
)
def test_an_impossible_reason_phase_pairing_is_refused(reason, phase):
    entries = [_failed(0, phase, reason), _blank(1, "not_attempted"), _blank(2, "not_attempted")]
    with pytest.raises(CollectionError):
        _build(entries, "stopped")


# --- per-phase payload rules --------------------------------------------------


def test_a_preflight_failure_records_no_observation():
    entry = _failed(0, "entry_preflight", "retrieval_clock_invalid")
    assert entry["request_chain"] == []
    assert entry["redirect_observed_location_disposition"] == "no_response"
    assert entry["terminal_observed_location_disposition"] == "no_response"
    receipt = _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")
    assert not list(VALIDATOR.iter_errors(receipt))


def test_a_preflight_failure_may_carry_a_timestamp_when_the_clock_succeeded():
    entry = _failed(0, "entry_preflight", "tls_keylog_environment_present")
    entry["retrieval_timestamp"] = STAMP
    receipt = _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")
    assert not list(VALIDATOR.iter_errors(receipt))


@pytest.mark.parametrize(
    "phase,field",
    [
        ("redirect_request", "redirect_observed_status"),
        ("redirect_evaluation", "terminal_observed_status"),
        ("terminal_request", "terminal_observed_status"),
    ],
)
def test_a_phase_cannot_claim_an_observation_it_never_had(phase, field):
    reason = v2.REASON_PHASES and next(
        r for r, ps in v2.REASON_PHASES.items() if phase in ps
    )
    entry = _failed(0, phase, reason)
    entry[field] = 500
    with pytest.raises(CollectionError):
        _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")


def test_a_persistence_failure_records_the_accepted_entity_but_no_object():
    entry = _failed(0, "persistence", "write_error")
    assert entry["byte_count"] == 13
    assert entry["content_sha256"] == BODY_DIGEST
    assert entry["raw_reference"] is None
    assert entry["object_disposition"] is None
    receipt = _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")
    assert not list(VALIDATOR.iter_errors(receipt))


def test_a_failed_entry_can_never_claim_a_stored_object():
    entry = _failed(0, "persistence", "write_error")
    entry["raw_reference"] = "gemini_thinking/sha256-x/document.html"
    with pytest.raises(CollectionError):
        _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")


# --- terminal sequences -------------------------------------------------------


@pytest.mark.parametrize("completion,statuses", TERMINAL_SEQUENCES)
def test_the_four_truthful_sequences_build_and_validate(completion, statuses):
    entries = []
    for index, status in enumerate(statuses):
        if status == "succeeded":
            entries.append(_succeeded(index))
        elif status == "failed":
            entries.append(_failed(index, "redirect_evaluation", "redirect_location_mismatch"))
        else:
            entries.append(_blank(index, "not_attempted"))
    receipt = _build(entries, completion)
    assert not list(VALIDATOR.iter_errors(receipt))


@pytest.mark.parametrize(
    "statuses,completion",
    [
        (("not_attempted", "failed", "succeeded"), "stopped"),
        (("failed", "succeeded", "succeeded"), "stopped"),
        (("succeeded", "succeeded", "succeeded"), "stopped"),
        (("failed", "failed", "not_attempted"), "stopped"),
    ],
)
def test_an_impossible_sequence_is_refused(statuses, completion):
    entries = []
    for index, status in enumerate(statuses):
        if status == "succeeded":
            entries.append(_succeeded(index))
        elif status == "failed":
            entries.append(_failed(index, "redirect_evaluation", "redirect_location_mismatch"))
        else:
            entries.append(_blank(index, "not_attempted"))
    with pytest.raises(CollectionError):
        _build(entries, completion)


# --- the transcription policy -------------------------------------------------


@pytest.mark.parametrize(
    "value,received,expected_value,expected_disposition",
    [
        (None, False, None, "no_response"),
        ("https://a.test/x", False, None, "no_response"),
        (None, True, None, "absent"),
        ("", True, None, "absent"),
        ("https://a.test/x", True, "https://a.test/x", "recorded"),
        ("/relative", True, "/relative", "recorded"),
        ("https://a.test/" + "x" * 2048, True, None, "rejected_oversize"),
        ("https://a.test/\r\nSet-Cookie: x", True, None, "rejected_uncharacterizable"),
        ("https://a.test/\x00", True, None, "rejected_uncharacterizable"),
        ("https://a.test/\x01", True, None, "rejected_uncharacterizable"),
        ("https://a.test/\t", True, None, "rejected_uncharacterizable"),
        ("https://a.test/é", True, None, "rejected_uncharacterizable"),
        (7, True, None, "rejected_uncharacterizable"),
    ],
)
def test_the_location_transcription_table(value, received, expected_value, expected_disposition):
    got, disposition = v2.classify_observed_location(value, response_received=received)
    assert (got, disposition) == (expected_value, expected_disposition)


def test_an_untranscribable_location_is_never_truncated():
    """A shortened URL is a fabricated artifact; refusing is the truthful move."""
    long_value = "https://a.test/" + "x" * 4096
    got, disposition = v2.classify_observed_location(long_value, response_received=True)
    assert got is None and disposition == "rejected_oversize"
    assert got != long_value[: v2.LOCATION_MAX_LENGTH]


def test_a_location_at_exactly_the_limit_is_recorded():
    value = "h" * v2.LOCATION_MAX_LENGTH
    got, disposition = v2.classify_observed_location(value, response_received=True)
    assert got == value and disposition == "recorded"
    assert len(got) == 2048


def test_the_measured_httpx_join_of_duplicate_field_lines_is_transcribable():
    """Measured on httpx 0.28.1: Headers.get joins duplicates with ", ".

    The joined string is the observation. It is printable ASCII, so it is
    recorded, and it can never equal a frozen final URL, so the route grammar
    refuses it -- recorded truthfully, never followed.
    """
    joined = "https://a.test/x, https://b.test/y"
    got, disposition = v2.classify_observed_location(joined, response_received=True)
    assert got == joined and disposition == "recorded"
    assert joined not in {
        e[field] for e in FROZEN_ENTRY_IDENTITIES for field in ("requested_url", "final_url")
    }


@pytest.mark.parametrize("blank", [" ", "   ", "\x20\x20"], ids=["one", "three", "two"])
def test_an_ascii_space_only_location_is_absent(blank):
    """It arrived, and it names no target; recording it would claim nothing."""
    assert v2.classify_observed_location(blank, response_received=True) == (None, "absent")


@pytest.mark.parametrize(
    "value",
    ["\t", "\n", "\r", " ", " ", " \t ", "\v", "\f", "​", "   "],
    ids=["tab", "lf", "cr", "nbsp", "em-space", "space-tab-space",
         "vtab", "ff", "zwsp", "space-nbsp-space"],
)
def test_non_ascii_or_control_whitespace_is_uncharacterizable_not_absent(value):
    """Charset is decided before the space-only rule.

    A bare ``strip()`` treats TAB, LF, CR, NBSP, U+2003 and every other Unicode
    whitespace codepoint as blank, so checking emptiness first classified all of
    them ``absent`` -- a benign disposition hiding forbidden characters. The
    locked order puts the printable-ASCII check first, so only a run of U+0020
    can reach the space-only rule.
    """
    got, disposition = v2.classify_observed_location(value, response_received=True)
    assert disposition == "rejected_uncharacterizable", value
    assert got is None
    assert disposition != "absent" and disposition != "recorded"


@pytest.mark.parametrize(
    "value",
    [" ", "   ", "\t", "\n", "\r", " ", " ", " \t "],
)
def test_no_whitespace_value_is_ever_recorded_or_truncated(value):
    got, disposition = v2.classify_observed_location(value, response_received=True)
    assert disposition != "recorded"
    assert got is None, "never a truncated or trimmed remnant"
    assert not v2.transcribable_location(value)


def test_the_locked_disposition_order_is_length_then_charset_then_space():
    """Each rule is reachable, and none shadows the one after it."""
    over = "x" * (v2.LOCATION_MAX_LENGTH + 1)
    # Length wins over charset: an over-long value carrying a control character
    # is still reported oversize, preserving the previously locked ordering.
    assert v2.classify_observed_location(over + "\n", response_received=True) == (
        None, "rejected_oversize",
    )
    # Charset wins over space-only.
    assert v2.classify_observed_location(" \t ", response_received=True) == (
        None, "rejected_uncharacterizable",
    )
    # Space-only is reached only once charset has passed.
    assert v2.classify_observed_location("  ", response_received=True) == (None, "absent")


def test_classify_and_transcribable_agree_exactly():
    """One definition of `recorded`, shared by classifier, builder and schema."""
    samples = [
        "https://a.test/x", "", " ", "  x  ", "x" * 2048, "x" * 2049,
        "é", "\x01", "\t", None, 7, "a b", "https://a.test/x, https://b.test/y",
    ]
    for sample in samples:
        value, disposition = v2.classify_observed_location(sample, response_received=True)
        assert (disposition == "recorded") == v2.transcribable_location(sample), sample
        # The binding itself: a value exists exactly when it was recorded.
        assert (value is not None) == (disposition == "recorded"), sample


# --- the location / disposition binding ---------------------------------------
#
# Before ADR-038's correction the schema and builder both accepted a null
# location claiming ``recorded``, a non-null location claiming ``absent``, and a
# non-printable value claiming ``recorded`` -- three ways to describe an
# observation that did not happen.


_BINDING_VIOLATIONS = [
    ({"location": None, "disposition": "recorded"}, "null-claiming-recorded"),
    ({"location": "https://a.test/x", "disposition": "absent"}, "value-claiming-absent"),
    ({"location": "https://a.test/x", "disposition": "no_response"}, "value-claiming-no-response"),
    (
        {"location": "https://a.test/x", "disposition": "rejected_oversize"},
        "value-claiming-oversize",
    ),
    (
        {"location": "https://a.test/x", "disposition": "rejected_uncharacterizable"},
        "value-claiming-uncharacterizable",
    ),
    ({"location": "https://a.test/é", "disposition": "recorded"}, "latin1-recorded"),
    ({"location": "https://a.test/\x01", "disposition": "recorded"}, "control-recorded"),
    ({"location": "   ", "disposition": "recorded"}, "blank-recorded"),
    ({"location": "x" * 2049, "disposition": "recorded"}, "oversize-recorded"),
]


@pytest.mark.parametrize("pair", ["redirect", "terminal"])
@pytest.mark.parametrize("violation,label", _BINDING_VIOLATIONS)
def test_the_schema_refuses_an_unbound_location_on_a_succeeded_entry(
    pair, violation, label
):
    receipt = _build([_succeeded(0), _succeeded(1), _succeeded(2)], "completed")
    entry = receipt["entries"][0]
    entry[f"{pair}_observed_location"] = violation["location"]
    entry[f"{pair}_observed_location_disposition"] = violation["disposition"]
    assert list(VALIDATOR.iter_errors(receipt)), (pair, label)


@pytest.mark.parametrize("pair", ["redirect", "terminal"])
@pytest.mark.parametrize("violation,label", _BINDING_VIOLATIONS)
def test_the_builder_refuses_an_unbound_location_on_a_succeeded_entry(
    pair, violation, label
):
    entries = [_succeeded(0), _succeeded(1), _succeeded(2)]
    entries[0][f"{pair}_observed_location"] = violation["location"]
    entries[0][f"{pair}_observed_location_disposition"] = violation["disposition"]
    with pytest.raises(CollectionError):
        _build(entries, "completed")


@pytest.mark.parametrize("pair", ["redirect", "terminal"])
@pytest.mark.parametrize("violation,label", _BINDING_VIOLATIONS)
def test_the_schema_and_builder_refuse_an_unbound_location_on_a_failed_entry(
    pair, violation, label
):
    entry = _failed(0, "terminal_evaluation", "terminal_status_invalid")
    entry[f"{pair}_observed_location"] = violation["location"]
    entry[f"{pair}_observed_location_disposition"] = violation["disposition"]
    entries = [entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")]
    with pytest.raises(CollectionError):
        _build(entries, "stopped")


@pytest.mark.parametrize("pair", ["redirect", "terminal"])
def test_a_bound_recorded_location_is_accepted(pair):
    """The binding refuses the untruthful shapes without refusing the true one."""
    entry = _failed(0, "terminal_evaluation", "terminal_status_invalid")
    entry[f"{pair}_observed_location"] = "https://a.test/x, https://b.test/y"
    entry[f"{pair}_observed_location_disposition"] = "recorded"
    if pair == "redirect":
        # A recorded redirect location past the hop must still be the frozen one.
        entry["redirect_observed_location"] = FROZEN_ENTRY_IDENTITIES[0]["final_url"]
    receipt = _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")
    assert not list(VALIDATOR.iter_errors(receipt))


def test_the_committed_schema_carries_the_binding_branches():
    prefix = json.loads(V2_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][0]
    bound = [
        branch for branch in prefix["allOf"]
        if any(key.endswith("_observed_location_disposition") for key in branch["if"]["properties"])
    ]
    assert len(bound) == 2, "one binding branch per observation pair"
    for branch in bound:
        field = next(iter(branch["else"]["properties"]))
        recorded = branch["then"]["properties"][field]
        # Two independent unanchored predicates, not one anchored pattern.
        assert recorded["pattern"] == v2.PRINTABLE_ASCII_REQUIRED_PATTERN
        assert recorded["not"] == {"pattern": v2.NON_PRINTABLE_ASCII_PATTERN}
        assert recorded["minLength"] == 1
        assert recorded["maxLength"] == v2.LOCATION_MAX_LENGTH
        assert branch["else"]["properties"][field] == {"const": None}


def test_the_committed_schema_uses_no_anchored_location_pattern():
    """``$`` also matches before a final newline under a search, so it is gone."""
    for pattern in (v2.PRINTABLE_ASCII_REQUIRED_PATTERN, v2.NON_PRINTABLE_ASCII_PATTERN):
        assert not pattern.startswith("^"), pattern
        assert not pattern.endswith("$"), pattern
    # The only "^" present is character-class negation, not a start anchor.
    assert v2.NON_PRINTABLE_ASCII_PATTERN.startswith("[^")
    assert "^" not in v2.PRINTABLE_ASCII_REQUIRED_PATTERN
    # Portable JSON Schema: no Python-only anchors may reach the committed file.
    text = V2_BYTES.decode("utf-8")
    assert r"\\Z" not in text and r"\\A" not in text


def test_the_two_predicates_are_individually_search_safe():
    """Neither predicate relies on anchoring, which is the whole point.

    ``REQUIRED`` alone still matches ``"x\\n"`` under a search -- that is exactly
    why it cannot be the only rule -- and ``FORBIDDEN`` under ``not`` is what
    rejects it. Together they hold without any end-of-string assumption.
    """
    import re

    assert re.search(v2.PRINTABLE_ASCII_REQUIRED_PATTERN, "x\n")
    assert re.search(v2.NON_PRINTABLE_ASCII_PATTERN, "x\n")
    assert re.search(v2.PRINTABLE_ASCII_REQUIRED_PATTERN, "x")
    assert not re.search(v2.NON_PRINTABLE_ASCII_PATTERN, "x")
    # A space-only value fails the positive predicate without needing an anchor.
    assert not re.search(v2.PRINTABLE_ASCII_REQUIRED_PATTERN, "   ")


# The values that exposed the hole. ``"x\n"`` passed the anchored pattern under
# ``re.search`` while ``transcribable_location`` rejected it, so the committed
# schema was strictly weaker than the builder it mirrored. These run through
# Draft202012Validator against the committed **bytes**, because ``re.fullmatch``
# is exactly what hid the defect.
_TRAILING_CONTROL_VALUES = [
    ("x\n", "trailing-lf"),
    ("x\r", "trailing-cr"),
    ("x\r\n", "trailing-crlf"),
    ("\nx", "leading-lf"),
    ("x\t", "trailing-tab"),
    ("x ", "trailing-nbsp"),
    ("x\v", "trailing-vtab"),
    ("x\f", "trailing-ff"),
    ("x ", "line-separator"),
]


@pytest.mark.parametrize("pair", ["redirect", "terminal"])
@pytest.mark.parametrize("value,label", _TRAILING_CONTROL_VALUES)
def test_the_committed_schema_rejects_a_control_bearing_recorded_location(
    pair, value, label
):
    receipt = _build([_succeeded(0), _succeeded(1), _succeeded(2)], "completed")
    entry = receipt["entries"][0]
    entry[f"{pair}_observed_location"] = value
    entry[f"{pair}_observed_location_disposition"] = "recorded"
    assert list(COMMITTED_VALIDATOR.iter_errors(receipt)), (pair, label)


@pytest.mark.parametrize("pair", ["redirect", "terminal"])
@pytest.mark.parametrize("value,label", _TRAILING_CONTROL_VALUES)
def test_the_builder_rejects_a_control_bearing_recorded_location(pair, value, label):
    entries = [_succeeded(0), _succeeded(1), _succeeded(2)]
    entries[0][f"{pair}_observed_location"] = value
    entries[0][f"{pair}_observed_location_disposition"] = "recorded"
    with pytest.raises(CollectionError):
        _build(entries, "completed")


@pytest.mark.parametrize("pair", ["redirect", "terminal"])
@pytest.mark.parametrize("value,label", _TRAILING_CONTROL_VALUES)
def test_a_control_bearing_recorded_location_is_refused_on_a_failed_entry(
    pair, value, label
):
    entry = _failed(0, "terminal_evaluation", "terminal_status_invalid")
    entry[f"{pair}_observed_location"] = value
    entry[f"{pair}_observed_location_disposition"] = "recorded"
    entries = [entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")]
    with pytest.raises(CollectionError):
        _build(entries, "stopped")


@pytest.mark.parametrize("value,label", _TRAILING_CONTROL_VALUES)
def test_the_committed_schema_and_the_builder_never_diverge(value, label):
    """The property the anchored pattern broke: one rule, two enforcers."""
    prefix = json.loads(V2_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][0]
    branch = next(
        b for b in prefix["allOf"]
        if "redirect_observed_location_disposition" in b["if"]["properties"]
    )
    schema_says = Draft202012Validator(
        branch["then"]["properties"]["redirect_observed_location"]
    ).is_valid(value)
    assert schema_says is v2.transcribable_location(value), label
    assert schema_says is False, label


def test_the_dispositions_are_the_five_declared_values():
    assert v2.LOCATION_DISPOSITIONS == (
        "no_response", "absent", "recorded", "rejected_oversize",
        "rejected_uncharacterizable",
    )
    assert "no_response" not in v2.RESPONSE_DISPOSITIONS
    assert len(v2.RESPONSE_DISPOSITIONS) == 4


# --- builder top-level guards -------------------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"attempt_id": "nope"},
        {"code_commit": "  "},
        {"run_created_at": "2026-02-30T09:00:00Z"},
        {"run_created_at": "2026-07-31T24:00:00Z"},
        {"adapter_contract_sha256": "A" * 64},
        {"retrieval_timestamp_mode": "other"},
        {"completion_status": "partial"},
        {"entries": []},
    ],
)
def test_the_builder_refuses_a_malformed_header(override):
    kwargs = {
        "attempt_id": ATTEMPT,
        "code_commit": COMMIT,
        "run_created_at": STAMP,
        "adapter_contract_sha256": DIGEST,
        "policy_contract_sha256": DIGEST,
        "receipt_schema_sha256": DIGEST,
        "retrieval_timestamp_mode": "caller_injected_request_start_utc_v1",
        "entries": [_succeeded(0), _succeeded(1), _succeeded(2)],
        "completion_status": "completed",
    }
    kwargs.update(override)
    with pytest.raises(CollectionError):
        v2.build_documentation_receipt_v2(**kwargs)


def test_every_builder_output_validates_against_the_committed_schema():
    receipt = _build([_succeeded(0), _succeeded(1), _succeeded(2)], "completed")
    committed = Draft202012Validator(json.loads(V2_BYTES.decode("utf-8")))
    assert not list(committed.iter_errors(receipt))
    assert v2.receipt_bytes_v2(receipt).endswith(b"\n")


# --- module hygiene -----------------------------------------------------------


def test_the_v2_module_declares_no_url_literal():
    """Frozen identities are imported from 0.1.0, so no third declaration exists."""
    source = (SRC / "documentation_receipt_v2.py").read_text(encoding="utf-8")
    assert '"https://' not in source
    assert '"http://' not in source
    assert "'https://" not in source


def test_the_v2_module_reads_no_clock_and_runs_no_process():
    source = (SRC / "documentation_receipt_v2.py").read_text(encoding="utf-8")
    for marker in ("datetime.now", "time.time", "utcnow", "subprocess", "urlopen"):
        assert marker not in source, marker
