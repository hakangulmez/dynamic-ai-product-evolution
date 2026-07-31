"""The v0.4 receipt contract: schema, loader and builder (ADR-040, E-C-D3).

Contract-level only: nothing here drives the collector, constructs a client or
touches ``data/``. What it proves is that ``documentation_collection_receipt@0.4.0``
can describe a direct route and a redirect_once route truthfully, and refuses
every shape that would describe a run which cannot have happened.
"""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection import documentation_receipt_v4 as v4  # noqa: E402
from dynamic_ai_products.collection.documentation_routes_v4 import (  # noqa: E402
    FROZEN_ROUTE_IDENTITIES_V4 as ROUTES,
)
from dynamic_ai_products.collection.documentation_routes_v4 import (  # noqa: E402
    ROUTE_CONTRACT_V4,
    ROUTE_KINDS,
    ROUTE_SET_VERSION_V4,
)
from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products" / "collection"
V4_PATH = ROOT / "schemas" / "documentation_collection_receipt.v4.schema.json"
V4_BYTES = V4_PATH.read_bytes()
V3_PATH = ROOT / "schemas" / "documentation_collection_receipt.v3.schema.json"
V3_BYTES = V3_PATH.read_bytes()

VALIDATOR = Draft202012Validator(v4.expected_receipt_schema_v4())
# Built from the committed **bytes**, because a divergence between the
# constructor and the shipped file is exactly what a loader test must catch.
COMMITTED_VALIDATOR = Draft202012Validator(json.loads(V4_BYTES.decode("utf-8")))

COMMIT = "c53233bba5e43702e8de93a623592351cc361d73"
STAMP = "2026-07-31T09:00:00Z"
DIGEST = "a" * 64


def _blank(index: int, status: str) -> dict:
    frozen = ROUTES[index]
    return {
        "evidence_kind": frozen["evidence_kind"],
        "route_kind": frozen["route_kind"],
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
        "send1_observed_status": None,
        "send1_observed_location": None,
        "send1_observed_location_disposition": "no_response",
        "send2_observed_status": None,
        "send2_observed_location": None,
        "send2_observed_location_disposition": "no_response",
    }


def _succeeded(index: int) -> dict:
    frozen = ROUTES[index]
    entry = _blank(index, "succeeded")
    entry.update(
        {
            "content_type": "text/html; charset=utf-8",
            "content_encoding": "identity",
            "byte_count": 40,
            "content_sha256": DIGEST,
            "raw_reference": f"{frozen['evidence_kind']}/sha256-{DIGEST}/document.html",
            "object_disposition": "created",
            "retrieval_timestamp": STAMP,
        }
    )
    if frozen["route_kind"] == "direct":
        entry["request_chain"] = [frozen["requested_url"]]
        entry["send1_observed_status"] = 200
        entry["send1_observed_location_disposition"] = "absent"
    else:
        entry["request_chain"] = [frozen["requested_url"], frozen["final_url"]]
        entry["send1_observed_status"] = 301
        entry["send1_observed_location"] = frozen["final_url"]
        entry["send1_observed_location_disposition"] = "recorded"
        entry["send2_observed_status"] = 200
        entry["send2_observed_location_disposition"] = "absent"
    return entry


def _failed(index: int, phase: str, reason: str) -> dict:
    """A minimally truthful failure record for the given phase."""
    frozen = ROUTES[index]
    entry = _blank(index, "failed")
    entry["failure_phase"] = phase
    entry["failure_reason"] = reason
    if phase == "entry_preflight":
        return entry
    entry["retrieval_timestamp"] = STAMP
    entry["request_chain"] = [frozen["requested_url"]]
    if phase in ("send1_evaluation",):
        entry["send1_observed_status"] = 500
        entry["send1_observed_location_disposition"] = "absent"
    if phase in ("send2_preflight", "send2_request", "send2_evaluation", "persistence"):
        entry["send1_observed_status"] = 301
        entry["send1_observed_location"] = frozen["final_url"]
        entry["send1_observed_location_disposition"] = "recorded"
    if phase in ("send2_request", "send2_evaluation", "persistence"):
        entry["request_chain"] = [frozen["requested_url"], frozen["final_url"]]
    if phase == "send2_evaluation":
        entry["send2_observed_status"] = 500
        entry["send2_observed_location_disposition"] = "absent"
    if phase == "persistence":
        if frozen["route_kind"] == "direct":
            entry["send1_observed_status"] = 200
            entry["send1_observed_location"] = None
            entry["send1_observed_location_disposition"] = "absent"
            entry["request_chain"] = [frozen["requested_url"]]
        else:
            entry["send2_observed_status"] = 200
            entry["send2_observed_location_disposition"] = "absent"
        entry.update(
            {
                "content_type": "text/html; charset=utf-8",
                "content_encoding": "identity",
                "byte_count": 40,
                "content_sha256": DIGEST,
            }
        )
    return entry


def _build(entries: list[dict], completion: str) -> dict:
    return v4.build_documentation_receipt_v4(
        attempt_id="docattempt-" + "0" * 32,
        code_commit=COMMIT,
        run_created_at=STAMP,
        adapter_contract_sha256="1" * 64,
        policy_contract_sha256="2" * 64,
        receipt_schema_sha256="3" * 64,
        retrieval_timestamp_mode="caller_injected_request_start_utc_v1",
        entries=entries,
        completion_status=completion,
    )


# --- the committed file matches its constructor -------------------------------


def test_the_committed_schema_matches_the_locked_definition():
    assert v4.validate_receipt_schema_v4_bytes(V4_BYTES) == sha256(V4_BYTES).hexdigest()
    Draft202012Validator.check_schema(v4.expected_receipt_schema_v4())


def test_the_loader_refuses_bytes_that_are_not_the_locked_schema():
    schema = json.loads(V4_BYTES.decode("utf-8"))
    schema["properties"]["entries"]["minItems"] = 2
    with pytest.raises(CollectionError) as excinfo:
        v4.validate_receipt_schema_v4_bytes(json.dumps(schema).encode("utf-8"))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


@pytest.mark.parametrize(
    "path,value",
    [
        ("additionalProperties", 0),
        ("properties.entries.minItems", 3.0),
        ("properties.entries.maxItems", 3.0),
        ("properties.code_commit.minLength", True),
    ],
    ids=["addprops-zero", "minitems-float", "maxitems-float", "minlength-true"],
)
def test_the_loader_is_json_type_exact(path, value):
    """True == 1 and 3 == 3.0 in Python; neither may weaken the schema."""
    schema = json.loads(V4_BYTES.decode("utf-8"))
    node = schema
    parts = path.split(".")
    for key in parts[:-1]:
        node = node[key]
    node[parts[-1]] = value
    with pytest.raises(CollectionError):
        v4.validate_receipt_schema_v4_bytes(json.dumps(schema).encode("utf-8"))


def test_the_loader_refuses_a_duplicated_member_name():
    text = V4_BYTES.decode("utf-8").replace(
        '"type": "object"', '"type": "object", "type": "object"', 1
    )
    with pytest.raises(CollectionError) as excinfo:
        v4.validate_receipt_schema_v4_bytes(text.encode("utf-8"))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


def test_the_three_earlier_contracts_are_untouched_and_mutually_rejected():
    """Each live receipt stays verifiable against the contract that made it."""
    from dynamic_ai_products.collection.documentation_receipt import (
        validate_receipt_schema_bytes as validate_v1,
    )
    from dynamic_ai_products.collection.documentation_receipt_v2 import (
        validate_receipt_schema_v2_bytes as validate_v2,
    )
    from dynamic_ai_products.collection.documentation_receipt_v3 import (
        validate_receipt_schema_v3_bytes as validate_v3,
    )

    v1_bytes = (ROOT / "schemas" / "documentation_collection_receipt.schema.json").read_bytes()
    v2_bytes = (ROOT / "schemas" / "documentation_collection_receipt.v2.schema.json").read_bytes()
    assert validate_v1(v1_bytes) == sha256(v1_bytes).hexdigest()
    assert validate_v2(v2_bytes) == sha256(v2_bytes).hexdigest()
    assert validate_v3(V3_BYTES) == sha256(V3_BYTES).hexdigest()
    for loader in (validate_v1, validate_v2, validate_v3):
        with pytest.raises(CollectionError) as excinfo:
            loader(V4_BYTES)
        assert excinfo.value.reason_code == "receipt_schema_contract_mismatch"
    with pytest.raises(CollectionError) as excinfo:
        v4.validate_receipt_schema_v4_bytes(V3_BYTES)
    assert excinfo.value.reason_code == "receipt_schema_contract_mismatch"


# --- route kinds are explicit and truthful ------------------------------------


def test_the_route_kinds_are_declared_per_entry():
    assert [e["route_kind"] for e in ROUTES] == ["redirect_once", "redirect_once", "direct"]
    assert set(ROUTE_KINDS) == {"direct", "redirect_once"}
    assert ROUTE_SET_VERSION_V4 == "0.4.0"
    assert ROUTE_CONTRACT_V4 == "documentation_frozen_routes@0.4.0"


def test_a_direct_route_declares_one_url_and_a_hop_route_declares_two():
    for entry in ROUTES:
        same = entry["requested_url"] == entry["final_url"]
        assert same is (entry["route_kind"] == "direct"), entry["evidence_kind"]


def test_the_e3_direct_route_is_the_expected_pricing_url():
    e3 = ROUTES[2]
    assert e3["evidence_kind"] == "pricing_standard"
    assert e3["route_kind"] == "direct"
    assert e3["requested_url"] == e3["final_url"]
    assert e3["requested_url"] == "https://cloud.google.com/vertex-ai/generative-ai/pricing"


def test_the_builder_refuses_a_kind_that_contradicts_its_urls():
    """The truthfulness constraint, enforced independently of the declaration."""
    lying = dict(ROUTES[2])
    lying["route_kind"] = "redirect_once"  # but the two URLs are the same one
    entry = _blank(2, "not_attempted")
    entry["route_kind"] = "redirect_once"
    violation = v4._entry_violations_v4(entry, lying)
    assert violation == "a redirect_once route must declare two different URLs"

    lying = dict(ROUTES[0])
    lying["route_kind"] = "direct"  # but the two URLs differ
    entry = _blank(0, "not_attempted")
    entry["route_kind"] = "direct"
    violation = v4._entry_violations_v4(entry, lying)
    assert violation == "a direct route must declare requested_url == final_url"


# --- the direct entry cannot describe a second send ---------------------------


def test_a_direct_entry_permits_only_two_request_chains():
    prefix = json.loads(V4_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][2]
    chains = [b["const"] for b in prefix["properties"]["request_chain"]["oneOf"]]
    assert chains == [[], [ROUTES[2]["requested_url"]]]


def test_a_hop_entry_permits_three_request_chains():
    for index in (0, 1):
        prefix = json.loads(V4_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][index]
        chains = [b["const"] for b in prefix["properties"]["request_chain"]["oneOf"]]
        assert chains == [
            [],
            [ROUTES[index]["requested_url"]],
            [ROUTES[index]["requested_url"], ROUTES[index]["final_url"]],
        ]


def test_every_permitted_chain_is_a_frozen_constant():
    """An observed location is structurally incapable of entering a chain."""
    schema = json.loads(V4_BYTES.decode("utf-8"))
    for index, prefix in enumerate(schema["properties"]["entries"]["prefixItems"]):
        frozen = {ROUTES[index]["requested_url"], ROUTES[index]["final_url"]}
        for branch in prefix["properties"]["request_chain"]["oneOf"]:
            assert set(branch["const"]) <= frozen


@pytest.mark.parametrize("phase", ["send2_preflight", "send2_request", "send2_evaluation"])
def test_a_direct_entry_cannot_name_a_send_two_phase(phase):
    prefix = json.loads(V4_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][2]
    assert phase not in prefix["properties"]["failure_phase"]["enum"]
    entry = _failed(2, "send1_evaluation", "terminal_status_invalid")
    entry["failure_phase"] = phase
    with pytest.raises(CollectionError):
        _build([_blank(0, "not_attempted"), _blank(1, "not_attempted"), entry], "stopped")


def test_a_direct_entry_reaches_exactly_four_phases():
    prefix = json.loads(V4_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][2]
    phases = [p for p in prefix["properties"]["failure_phase"]["enum"] if p is not None]
    assert phases == list(v4.DIRECT_PHASES)
    assert len(phases) == 4


def test_a_hop_entry_reaches_all_seven_phases():
    for index in (0, 1):
        prefix = json.loads(V4_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][index]
        phases = [p for p in prefix["properties"]["failure_phase"]["enum"] if p is not None]
        assert phases == list(v4.FAILURE_PHASES)
        assert len(phases) == 7


# --- the reason vocabulary is kind-scoped -------------------------------------


def test_the_new_reason_exists_and_is_direct_only():
    assert "direct_redirect_not_permitted" in v4.ENTRY_RECORDABLE_REASONS_V4
    assert "direct_redirect_not_permitted" in v4.ROUTE_KIND_REASONS["direct"]
    assert "direct_redirect_not_permitted" not in v4.ROUTE_KIND_REASONS["redirect_once"]


@pytest.mark.parametrize(
    "reason",
    [
        "direct_terminal_not_permitted",
        "redirect_status_invalid",
        "redirect_location_missing",
        "redirect_location_not_absolute",
        "redirect_location_mismatch",
        "redirect_chain_too_long",
    ],
)
def test_hop_only_reasons_are_absent_from_a_direct_route(reason):
    assert reason not in v4.ROUTE_KIND_REASONS["direct"]
    assert reason in v4.ROUTE_KIND_REASONS["redirect_once"]
    prefix = json.loads(V4_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][2]
    assert reason not in prefix["properties"]["failure_reason"]["enum"]


def test_the_vocabulary_counts_are_pinned():
    assert len(v4.FAILURE_REASONS_V4) == 28
    assert len(v4.ENTRY_RECORDABLE_REASONS_V4) == 21
    assert len(v4.ENTRY_REQUIRED_V4) == 21
    assert len(v4.ROUTE_KIND_REASONS["direct"]) == 15
    assert len(v4.ROUTE_KIND_REASONS["redirect_once"]) == 20


def test_every_entry_recordable_reason_maps_to_a_declared_phase():
    assert set(v4.REASON_PHASES) == set(v4.ENTRY_RECORDABLE_REASONS_V4)
    for reason, phases in v4.REASON_PHASES.items():
        assert phases, reason
        for phase in phases:
            assert phase in v4.FAILURE_PHASES, (reason, phase)


def test_every_reason_a_kind_permits_is_reachable_in_that_kind():
    """No reason may be permitted for a kind whose phases it can never occupy."""
    for kind, reasons in v4.ROUTE_KIND_REASONS.items():
        allowed = set(v4.ROUTE_KIND_PHASES[kind])
        for reason in reasons:
            assert allowed & set(v4.REASON_PHASES[reason]), (kind, reason)


# --- the location / disposition binding ---------------------------------------


_BINDING_VIOLATIONS = [
    ({"location": None, "disposition": "recorded"}, "null-claiming-recorded"),
    ({"location": "https://a.test/x", "disposition": "absent"}, "value-claiming-absent"),
    ({"location": "https://a.test/x", "disposition": "no_response"}, "value-claiming-none"),
    ({"location": "https://a.test/é", "disposition": "recorded"}, "latin1-recorded"),
    ({"location": "https://a.test/\x01", "disposition": "recorded"}, "control-recorded"),
    ({"location": "   ", "disposition": "recorded"}, "blank-recorded"),
    ({"location": "x" * 2049, "disposition": "recorded"}, "oversize-recorded"),
    ({"location": "x\n", "disposition": "recorded"}, "trailing-lf-recorded"),
]


@pytest.mark.parametrize("ordinal", ["send1", "send2"])
@pytest.mark.parametrize("violation,label", _BINDING_VIOLATIONS)
def test_the_schema_and_builder_refuse_an_unbound_location(ordinal, violation, label):
    entries = [_succeeded(0), _succeeded(1), _succeeded(2)]
    entries[0][f"{ordinal}_observed_location"] = violation["location"]
    entries[0][f"{ordinal}_observed_location_disposition"] = violation["disposition"]
    with pytest.raises(CollectionError):
        _build(entries, "completed")
    receipt = _build([_succeeded(0), _succeeded(1), _succeeded(2)], "completed")
    receipt["entries"][0][f"{ordinal}_observed_location"] = violation["location"]
    receipt["entries"][0][f"{ordinal}_observed_location_disposition"] = violation["disposition"]
    assert list(COMMITTED_VALIDATOR.iter_errors(receipt)), label


def test_the_committed_schema_uses_unanchored_location_predicates():
    """``$`` also matches before a final newline under a search, so it is gone."""
    for pattern in (v4.PRINTABLE_ASCII_REQUIRED_PATTERN, v4.NON_PRINTABLE_ASCII_PATTERN):
        assert not pattern.startswith("^")
        assert not pattern.endswith("$")
    text = V4_BYTES.decode("utf-8")
    assert r"\\Z" not in text and r"\\A" not in text


def test_classify_and_transcribable_agree_exactly():
    samples = [
        "https://a.test/x", "", " ", "  x  ", "x" * 2048, "x" * 2049,
        "é", "\x01", "\t", None, 7, "a b", "x\n",
    ]
    for sample in samples:
        value, disposition = v4.classify_observed_location(sample, response_received=True)
        assert (disposition == "recorded") == v4.transcribable_location(sample), sample
        assert (value is not None) == (disposition == "recorded"), sample


def test_the_locked_disposition_order_is_length_then_charset_then_space():
    over = "x" * (v4.LOCATION_MAX_LENGTH + 1)
    assert v4.classify_observed_location(over + "\n", response_received=True) == (
        None, "rejected_oversize",
    )
    assert v4.classify_observed_location(" \t ", response_received=True) == (
        None, "rejected_uncharacterizable",
    )
    assert v4.classify_observed_location("  ", response_received=True) == (None, "absent")
    assert v4.classify_observed_location(None, response_received=False) == (None, "no_response")


# --- the builder refuses runs that cannot have happened ------------------------


def test_a_truthful_completed_receipt_is_accepted():
    receipt = _build([_succeeded(0), _succeeded(1), _succeeded(2)], "completed")
    assert not list(COMMITTED_VALIDATOR.iter_errors(receipt))
    assert receipt["contract"] == "documentation_collection_receipt@0.4.0"
    assert receipt["schema_version"] == "0.4.0"


@pytest.mark.parametrize(
    "statuses,completion",
    [
        (("failed", "not_attempted", "not_attempted"), "stopped"),
        (("succeeded", "failed", "not_attempted"), "stopped"),
        (("succeeded", "succeeded", "failed"), "stopped"),
    ],
)
def test_every_truthful_stopped_sequence_is_accepted(statuses, completion):
    entries = []
    for index, status in enumerate(statuses):
        if status == "succeeded":
            entries.append(_succeeded(index))
        elif status == "failed":
            entries.append(_failed(index, "send1_evaluation", "terminal_status_invalid"))
        else:
            entries.append(_blank(index, "not_attempted"))
    receipt = _build(entries, completion)
    assert not list(COMMITTED_VALIDATOR.iter_errors(receipt))


@pytest.mark.parametrize(
    "statuses,completion",
    [
        (("succeeded", "succeeded", "succeeded"), "stopped"),
        (("failed", "succeeded", "not_attempted"), "stopped"),
        (("failed", "failed", "not_attempted"), "stopped"),
        (("not_attempted", "not_attempted", "not_attempted"), "stopped"),
    ],
    ids=["all-ok-but-stopped", "success-after-failure", "two-failures", "none-attempted"],
)
def test_an_impossible_sequence_is_refused(statuses, completion):
    entries = []
    for index, status in enumerate(statuses):
        if status == "succeeded":
            entries.append(_succeeded(index))
        elif status == "failed":
            entries.append(_failed(index, "send1_evaluation", "terminal_status_invalid"))
        else:
            entries.append(_blank(index, "not_attempted"))
    with pytest.raises(CollectionError):
        _build(entries, completion)


def test_a_failed_entry_may_not_carry_object_fields():
    entry = _failed(0, "send1_evaluation", "terminal_status_invalid")
    entry["raw_reference"] = "x/sha256-y/document.html"
    with pytest.raises(CollectionError):
        _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")


def test_a_reason_outside_its_phase_is_refused():
    entry = _failed(0, "persistence", "redirect_location_mismatch")
    with pytest.raises(CollectionError):
        _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")


def test_the_receipt_is_deterministic_and_canonical():
    receipt = _build([_succeeded(0), _succeeded(1), _succeeded(2)], "completed")
    assert v4.receipt_bytes_v4(receipt) == v4.receipt_bytes_v4(receipt)
    assert v4.receipt_bytes_v4(receipt).endswith(b"\n")


# --- structural -------------------------------------------------------------


def test_the_v4_contract_declares_no_route_of_its_own():
    source = (SRC / "documentation_receipt_v4.py").read_text(encoding="utf-8")
    assert '"https://' not in source
    assert "documentation_routes_v4" in source


def test_the_v4_routes_module_is_the_single_declaration():
    from dynamic_ai_products.collection import documentation_policy_v4 as dp4

    assert dp4.FROZEN_EVIDENCE_ENTRIES_V4 is ROUTES


def test_the_v3_routes_are_untouched_and_differ_at_e2_and_e3():
    from dynamic_ai_products.collection.documentation_routes import (
        FROZEN_ROUTE_IDENTITIES as V3_ROUTES,
    )

    assert V3_ROUTES[0]["final_url"] == ROUTES[0]["final_url"], "E1 unchanged"
    assert V3_ROUTES[1]["final_url"] != ROUTES[1]["final_url"], "E2 re-frozen"
    assert V3_ROUTES[2]["final_url"] != ROUTES[2]["final_url"], "E3 re-frozen as direct"
    for entry in V3_ROUTES:
        assert "route_kind" not in entry, "v0.3 declared no kinds"
        assert entry["requested_url"] != entry["final_url"]


def test_the_attempt_id_cannot_collide_with_either_live_attempt():
    from dynamic_ai_products.collection import documentation_policy_v4 as dp4

    live = {
        "docattempt-f88b54ac65e04d0766d749cb606bcee2",
        "docattempt-c4082dd835f2f5228669487f50ca2308",
    }
    identity = {
        "code_commit": COMMIT,
        "run_created_at": STAMP,
        "adapter_contract_sha256": "1" * 64,
        "policy_contract_sha256": sha256(
            v4.receipt_bytes_v4(dp4.POLICY_CONTRACT_V4)
        ).hexdigest(),
        "receipt_contract_id": v4.RECEIPT_CONTRACT_V4,
        "receipt_schema_sha256": sha256(V4_BYTES).hexdigest(),
        "ordered_pairs": [dict(e) for e in ROUTES],
    }
    derived = "docattempt-" + sha256(v4.receipt_bytes_v4(identity)).hexdigest()[:32]
    assert derived not in live
    assert re.fullmatch(v4.ATTEMPT_ID_PATTERN if hasattr(v4, "ATTEMPT_ID_PATTERN") else r"^docattempt-[0-9a-f]{32}$", derived)
