"""The v0.5 receipt contract: schema, loader and builder (ADR-041, E-C-D4).

Contract-level only: nothing here drives the collector, constructs a client or
touches ``data/``. What it proves is that ``documentation_collection_receipt@0.5.0``
can describe a two-hop relative-path route and a one-hop route truthfully, and
refuses every shape describing a run that cannot have happened.
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection import documentation_receipt_v5 as v5  # noqa: E402
from dynamic_ai_products.collection.documentation_routes_v5 import (  # noqa: E402
    FROZEN_ROUTE_IDENTITIES_V5 as ROUTES,
)
from dynamic_ai_products.collection.documentation_routes_v5 import (  # noqa: E402
    RELATIVE_RESOLUTION_BASE,
    ROUTE_CONTRACT_V5,
    ROUTE_KINDS_V5,
    ROUTE_SET_VERSION_V5,
    SENDS_BY_ROUTE_KIND,
)
from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products" / "collection"
V5_BYTES = (ROOT / "schemas" / "documentation_collection_receipt.v5.schema.json").read_bytes()
V4_BYTES = (ROOT / "schemas" / "documentation_collection_receipt.v4.schema.json").read_bytes()

VALIDATOR = Draft202012Validator(v5.expected_receipt_schema_v5())
COMMITTED_VALIDATOR = Draft202012Validator(json.loads(V5_BYTES.decode("utf-8")))

COMMIT = "fbdc13eadb9912872c23fa21149a68c65f59a00c"
STAMP = "2026-08-01T09:00:00Z"
DIGEST = "a" * 64


def _blank(index: int, status: str) -> dict:
    frozen = ROUTES[index]
    entry = {
        "evidence_kind": frozen["evidence_kind"],
        "route_kind": frozen["route_kind"],
        "requested_url": frozen["requested_url"],
        "intermediate_url": frozen["intermediate_url"],
        "second_hop_location": frozen["second_hop_location"],
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
        "send3_request_url": None,
    }
    for ordinal in ("send1", "send2", "send3"):
        entry[f"{ordinal}_observed_status"] = None
        entry[f"{ordinal}_observed_location"] = None
        entry[f"{ordinal}_observed_location_disposition"] = "no_response"
    return entry


def _succeeded(index: int) -> dict:
    frozen = ROUTES[index]
    entry = _blank(index, "succeeded")
    entry.update({
        "content_type": "text/html; charset=utf-8",
        "content_encoding": "identity",
        "byte_count": 40,
        "content_sha256": DIGEST,
        "raw_reference": f"{frozen['evidence_kind']}/sha256-{DIGEST}/document.html",
        "object_disposition": "created",
        "retrieval_timestamp": STAMP,
    })
    if frozen["route_kind"] == "redirect_once":
        entry["request_chain"] = [frozen["requested_url"], frozen["final_url"]]
        entry["send1_observed_status"] = 301
        entry["send1_observed_location"] = frozen["final_url"]
        entry["send1_observed_location_disposition"] = "recorded"
        entry["send2_observed_status"] = 200
        entry["send2_observed_location_disposition"] = "absent"
    else:
        entry["request_chain"] = [
            frozen["requested_url"], frozen["intermediate_url"], frozen["final_url"]
        ]
        entry["send1_observed_status"] = 301
        entry["send1_observed_location"] = frozen["intermediate_url"]
        entry["send1_observed_location_disposition"] = "recorded"
        entry["send2_observed_status"] = 301
        entry["send2_observed_location"] = frozen["second_hop_location"]
        entry["send2_observed_location_disposition"] = "recorded"
        entry["send3_request_url"] = frozen["final_url"]
        entry["send3_observed_status"] = 200
        entry["send3_observed_location_disposition"] = "absent"
    return entry


def _build(entries: list[dict], completion: str) -> dict:
    return v5.build_documentation_receipt_v5(
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
    assert v5.validate_receipt_schema_v5_bytes(V5_BYTES) == sha256(V5_BYTES).hexdigest()
    Draft202012Validator.check_schema(v5.expected_receipt_schema_v5())


@pytest.mark.parametrize(
    "path,value",
    [("additionalProperties", 0), ("properties.entries.minItems", 3.0),
     ("properties.code_commit.minLength", True)],
    ids=["addprops-zero", "minitems-float", "minlength-true"],
)
def test_the_loader_is_json_type_exact(path, value):
    schema = json.loads(V5_BYTES.decode("utf-8"))
    node = schema
    parts = path.split(".")
    for key in parts[:-1]:
        node = node[key]
    node[parts[-1]] = value
    with pytest.raises(CollectionError):
        v5.validate_receipt_schema_v5_bytes(json.dumps(schema).encode("utf-8"))


def test_the_loader_refuses_a_duplicated_member_name():
    text = V5_BYTES.decode("utf-8").replace(
        '"type": "object"', '"type": "object", "type": "object"', 1
    )
    with pytest.raises(CollectionError) as excinfo:
        v5.validate_receipt_schema_v5_bytes(text.encode("utf-8"))
    assert excinfo.value.reason_code == "receipt_schema_invalid"


def test_all_four_earlier_contracts_are_untouched_and_mutually_rejected():
    from dynamic_ai_products.collection.documentation_receipt import (
        validate_receipt_schema_bytes as v1,
    )
    from dynamic_ai_products.collection.documentation_receipt_v2 import (
        validate_receipt_schema_v2_bytes as v2,
    )
    from dynamic_ai_products.collection.documentation_receipt_v3 import (
        validate_receipt_schema_v3_bytes as v3,
    )
    from dynamic_ai_products.collection.documentation_receipt_v4 import (
        validate_receipt_schema_v4_bytes as v4,
    )

    files = {
        v1: "documentation_collection_receipt.schema.json",
        v2: "documentation_collection_receipt.v2.schema.json",
        v3: "documentation_collection_receipt.v3.schema.json",
        v4: "documentation_collection_receipt.v4.schema.json",
    }
    for loader, name in files.items():
        raw = (ROOT / "schemas" / name).read_bytes()
        assert loader(raw) == sha256(raw).hexdigest()
        with pytest.raises(CollectionError) as excinfo:
            loader(V5_BYTES)
        assert excinfo.value.reason_code == "receipt_schema_contract_mismatch"
    with pytest.raises(CollectionError) as excinfo:
        v5.validate_receipt_schema_v5_bytes(V4_BYTES)
    assert excinfo.value.reason_code == "receipt_schema_contract_mismatch"


# --- route kinds --------------------------------------------------------------


def test_the_route_kinds_are_declared_and_direct_is_absent():
    assert set(ROUTE_KINDS_V5) == {"redirect_once", "redirect_twice_relative_path"}
    assert "direct" not in ROUTE_KINDS_V5
    assert [e["route_kind"] for e in ROUTES] == [
        "redirect_twice_relative_path", "redirect_twice_relative_path", "redirect_once",
    ]
    assert ROUTE_SET_VERSION_V5 == "0.5.0"
    assert ROUTE_CONTRACT_V5 == "documentation_frozen_routes@0.5.0"
    assert SENDS_BY_ROUTE_KIND == {"redirect_once": 2, "redirect_twice_relative_path": 3}


def test_no_v5_route_declares_a_bare_fetch():
    """Every route performs at least one recognized hop."""
    for entry in ROUTES:
        assert entry["requested_url"] != entry["final_url"]


def test_every_two_hop_route_resolves_to_its_frozen_final():
    for entry in ROUTES:
        if entry["route_kind"] != "redirect_twice_relative_path":
            assert entry["intermediate_url"] is None
            assert entry["second_hop_location"] is None
            continue
        raw = entry["second_hop_location"]
        assert v5.absolute_path_reference_violation(raw) is None
        assert RELATIVE_RESOLUTION_BASE + raw == entry["final_url"]
        assert v5.resolve_absolute_path_reference(raw) == entry["final_url"]
        assert len({entry["requested_url"], entry["intermediate_url"], entry["final_url"]}) == 3


def test_the_resolution_base_is_a_declared_constant():
    """Never parsed out of a response: a server cannot choose where a join lands."""
    source = (SRC / "documentation_receipt_v5.py").read_text(encoding="utf-8")
    assert "RELATIVE_RESOLUTION_BASE + value" in source
    assert RELATIVE_RESOLUTION_BASE == "https://docs.cloud.google.com"


# --- the absolute-path grammar ------------------------------------------------


@pytest.mark.parametrize("good", ["/a", "/a/b", "/gemini-enterprise-agent-platform/models/thinking"])
def test_the_grammar_accepts_a_bare_absolute_path(good):
    assert v5.absolute_path_reference_violation(good) is None


@pytest.mark.parametrize(
    "bad,why",
    [
        ("", "empty"),
        ("a/b", "no_leading_slash"),
        ("https://h/x", "no_leading_slash"),
        ("//host/x", "protocol_relative"),
        ("/a?q=1", "query_present"),
        ("/a#f", "fragment_present"),
        ("/u@h", "userinfo_present"),
        ("/a\\b", "backslash_present"),
        ("/a/../b", "dot_dot_segment"),
        ("/..", "dot_dot_segment"),
        ("/a:b", "colon_present"),
        ("/a\n", "non_printable"),
        ("/a\t", "non_printable"),
    ],
)
def test_the_grammar_refuses_everything_else(bad, why):
    assert v5.absolute_path_reference_violation(bad) == why


def test_the_grammar_refuses_non_strings():
    for value in (None, 7, b"/a", ["/a"]):
        assert v5.absolute_path_reference_violation(value) == "empty"


# --- send-three shape ---------------------------------------------------------


def test_a_two_hop_entry_permits_four_request_chains():
    for index in (0, 1):
        prefix = json.loads(V5_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][index]
        chains = [b["const"] for b in prefix["properties"]["request_chain"]["oneOf"]]
        assert chains == [
            [],
            [ROUTES[index]["requested_url"]],
            [ROUTES[index]["requested_url"], ROUTES[index]["intermediate_url"]],
            [ROUTES[index]["requested_url"], ROUTES[index]["intermediate_url"],
             ROUTES[index]["final_url"]],
        ]


def test_a_one_hop_entry_permits_three_request_chains():
    prefix = json.loads(V5_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][2]
    chains = [b["const"] for b in prefix["properties"]["request_chain"]["oneOf"]]
    assert chains == [[], [ROUTES[2]["requested_url"]],
                      [ROUTES[2]["requested_url"], ROUTES[2]["final_url"]]]


def test_every_permitted_chain_is_a_frozen_constant():
    """An observed location is structurally incapable of entering a chain."""
    schema = json.loads(V5_BYTES.decode("utf-8"))
    for index, prefix in enumerate(schema["properties"]["entries"]["prefixItems"]):
        frozen = {ROUTES[index]["requested_url"], ROUTES[index]["final_url"]}
        if ROUTES[index]["intermediate_url"]:
            frozen.add(ROUTES[index]["intermediate_url"])
        for branch in prefix["properties"]["request_chain"]["oneOf"]:
            assert set(branch["const"]) <= frozen


def test_send3_request_url_is_pinned_to_frozen_constants():
    schema = json.loads(V5_BYTES.decode("utf-8"))
    for index, prefix in enumerate(schema["properties"]["entries"]["prefixItems"]):
        allowed = prefix["properties"]["send3_request_url"]["enum"]
        if ROUTES[index]["route_kind"] == "redirect_once":
            assert allowed == [None]
        else:
            assert allowed == [ROUTES[index]["final_url"], None]


@pytest.mark.parametrize("phase", ["send3_preflight", "send3_request", "send3_evaluation"])
def test_a_one_hop_entry_cannot_name_a_send_three_phase(phase):
    prefix = json.loads(V5_BYTES.decode("utf-8"))["properties"]["entries"]["prefixItems"][2]
    assert phase not in prefix["properties"]["failure_phase"]["enum"]


def test_phase_counts_are_pinned():
    assert len(v5.FAILURE_PHASES_V5) == 10
    assert len(v5.REDIRECT_ONCE_PHASES_V5) == 7
    assert len(v5.REDIRECT_TWICE_PHASES_V5) == 10


# --- the reason vocabulary ----------------------------------------------------


def test_the_second_hop_reasons_exist_and_are_two_hop_only():
    second = {
        "second_redirect_status_invalid", "second_location_missing",
        "second_location_not_relative_path", "second_location_mismatch",
        "resolved_final_mismatch",
    }
    assert second <= set(v5.ENTRY_RECORDABLE_REASONS_V5)
    assert second <= set(v5.ROUTE_KIND_REASONS_V5["redirect_twice_relative_path"])
    assert not (second & set(v5.ROUTE_KIND_REASONS_V5["redirect_once"]))


def test_the_v4_direct_reason_is_gone():
    assert "direct_redirect_not_permitted" not in v5.FAILURE_REASONS_V5


def test_the_vocabulary_counts_are_pinned():
    assert len(v5.FAILURE_REASONS_V5) == 32
    assert len(v5.ENTRY_RECORDABLE_REASONS_V5) == 25
    assert len(v5.ENTRY_REQUIRED_V5) == 27
    assert len(v5.ROUTE_KIND_REASONS_V5["redirect_once"]) == 20
    assert len(v5.ROUTE_KIND_REASONS_V5["redirect_twice_relative_path"]) == 25


def test_every_entry_recordable_reason_maps_to_a_declared_phase():
    assert set(v5.REASON_PHASES_V5) == set(v5.ENTRY_RECORDABLE_REASONS_V5)
    for reason, phases in v5.REASON_PHASES_V5.items():
        assert phases, reason
        for phase in phases:
            assert phase in v5.FAILURE_PHASES_V5, (reason, phase)


def test_every_reason_a_kind_permits_is_reachable_in_that_kind():
    for kind, reasons in v5.ROUTE_KIND_REASONS_V5.items():
        allowed = set(v5.ROUTE_KIND_PHASES_V5[kind])
        for reason in reasons:
            assert allowed & set(v5.REASON_PHASES_V5[reason]), (kind, reason)


# --- the location / disposition binding ---------------------------------------


_BINDING_VIOLATIONS = [
    ({"location": None, "disposition": "recorded"}, "null-claiming-recorded"),
    ({"location": "https://a.test/x", "disposition": "absent"}, "value-claiming-absent"),
    ({"location": "https://a.test/x", "disposition": "no_response"}, "value-claiming-none"),
    ({"location": "x\n", "disposition": "recorded"}, "trailing-lf-recorded"),
    ({"location": "   ", "disposition": "recorded"}, "blank-recorded"),
    ({"location": "x" * 2049, "disposition": "recorded"}, "oversize-recorded"),
]


@pytest.mark.parametrize("ordinal", ["send1", "send2", "send3"])
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


def test_classify_and_transcribable_agree_exactly():
    for sample in ["https://a.test/x", "", " ", "x" * 2049, "\u00e9", "\x01", None, 7, "x\n"]:
        value, disposition = v5.classify_observed_location(sample, response_received=True)
        assert (disposition == "recorded") == v5.transcribable_location(sample), sample
        assert (value is not None) == (disposition == "recorded"), sample


# --- truthful sequencing ------------------------------------------------------


def test_a_truthful_completed_receipt_is_accepted():
    receipt = _build([_succeeded(0), _succeeded(1), _succeeded(2)], "completed")
    assert not list(COMMITTED_VALIDATOR.iter_errors(receipt))
    assert receipt["contract"] == "documentation_collection_receipt@0.5.0"
    assert receipt["schema_version"] == "0.5.0"


@pytest.mark.parametrize(
    "statuses",
    [("succeeded", "succeeded", "succeeded"), ("failed", "succeeded", "not_attempted"),
     ("failed", "failed", "not_attempted"), ("not_attempted", "not_attempted", "not_attempted")],
    ids=["all-ok-but-stopped", "success-after-failure", "two-failures", "none-attempted"],
)
def test_an_impossible_sequence_is_refused(statuses):
    entries = []
    for index, status in enumerate(statuses):
        if status == "succeeded":
            entries.append(_succeeded(index))
        elif status == "failed":
            entry = _blank(index, "failed")
            entry["failure_phase"] = "entry_preflight"
            entry["failure_reason"] = "retrieval_clock_invalid"
            entries.append(entry)
        else:
            entries.append(_blank(index, "not_attempted"))
    with pytest.raises(CollectionError):
        _build(entries, "stopped")


def test_a_failed_entry_may_not_carry_object_fields():
    entry = _blank(0, "failed")
    entry["failure_phase"] = "entry_preflight"
    entry["failure_reason"] = "retrieval_clock_invalid"
    entry["raw_reference"] = "x/sha256-y/document.html"
    with pytest.raises(CollectionError):
        _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")


def test_a_reason_outside_its_phase_is_refused():
    entry = _blank(0, "failed")
    entry["failure_phase"] = "entry_preflight"
    entry["failure_reason"] = "second_location_mismatch"
    with pytest.raises(CollectionError):
        _build([entry, _blank(1, "not_attempted"), _blank(2, "not_attempted")], "stopped")


def test_a_one_hop_entry_cannot_carry_a_second_hop_reason():
    entry = _blank(2, "failed")
    entry["failure_phase"] = "send2_evaluation"
    entry["failure_reason"] = "second_location_mismatch"
    with pytest.raises(CollectionError):
        _build([_succeeded(0), _succeeded(1), entry], "stopped")


def test_the_receipt_is_deterministic_and_canonical():
    receipt = _build([_succeeded(0), _succeeded(1), _succeeded(2)], "completed")
    assert v5.receipt_bytes_v5(receipt) == v5.receipt_bytes_v5(receipt)
    assert v5.receipt_bytes_v5(receipt).endswith(b"\n")


# --- structural ---------------------------------------------------------------


def test_the_v5_contract_declares_no_route_of_its_own():
    source = (SRC / "documentation_receipt_v5.py").read_text(encoding="utf-8")
    assert '"https://' not in source
    assert "documentation_routes_v5" in source


def test_the_v4_routes_are_untouched_and_v5_differs_at_every_entry():
    from dynamic_ai_products.collection.documentation_routes_v4 import (
        FROZEN_ROUTE_IDENTITIES_V4 as V4,
    )

    assert V4 is not ROUTES
    assert [e["route_kind"] for e in V4] == ["redirect_once", "redirect_once", "direct"]
    for entry in V4:
        assert "intermediate_url" not in entry
    # v0.5 corrects every route: two become two-hop, E3 regains a hop.
    for old, new in zip(V4, ROUTES):
        assert old["route_kind"] != new["route_kind"] or old["final_url"] != new["final_url"]
