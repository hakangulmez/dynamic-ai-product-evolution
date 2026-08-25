"""ADR-128 tests: the V2.2 prompt, and the real failure shapes it must admit.

The first calibration stopped after three rows. Every one of those responses
was valid JSON with valid axes, refused only on output size. The shapes those
three produced are reproduced here as synthetic fixtures — item counts and
quote lengths, not the archived bytes, which may not be reused under the
successor contract — and each must now pass while the new ceilings still bite.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_contract_set as ccs
from dynamic_ai_products import lineage_classifier_v2_1 as lcl

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import (  # noqa: E402
    ROOT,
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
)

PROMPT = (ROOT / ccs.V2_2.prompt_path).read_text(encoding="utf-8")
#: The prompt reflowed to one space, so assertions test wording, not wrapping.
FLAT = " ".join(PROMPT.split())
V2_1_PROMPT = (ROOT / ccs.V2_1.prompt_path).read_text(encoding="utf-8")
AXES_V2_2 = json.loads((ROOT / ccs.V2_2.axes_schema).read_text(encoding="utf-8"))
AXES_V2_1 = json.loads((ROOT / ccs.V2_1.axes_schema).read_text(encoding="utf-8"))

#: The three shapes the failed run actually produced: (evidence items, longest
#: quote). Reconstructed structurally from the diagnosis, not copied.
OBSERVED_SHAPES = [(10, 972), (8, 638), (6, 375)]


def _validator(schema):
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _axes(packet, *, items, quote_len):
    """A well-formed axes payload of a given size shape.

    Every quote is a genuine contiguous span of the packet's own first passage,
    so only the size bounds can reject it.
    """
    body = packet["passages"][0]["text"]
    assert len(body) >= quote_len, "fixture packet is too short for this shape"
    quote = body[:quote_len]
    axes = ["customer_value", "centrality", "dependency", "structure",
            "materiality", "eligibility"]
    return json.dumps({
        "customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "software_centrality": "CORE",
        "complementary_dependencies": ["NONE_OR_STANDARD_COMPUTE"],
        "firm_structure": "PURE_PLAY", "commercial_materiality": "DOMINANT",
        "customer_facing_functional_product": True,
        "economically_eligible": True, "data_eligible": True,
        "customer_market_orientation": "B2B",
        "boundary_flags": [], "contradictions": [],
        "evidence": [{"axis": axes[i % len(axes)], "passage_ref": "P001",
                      "quote": quote,
                      "supported_claim": "The cited passage supports this axis."}
                     for i in range(items)],
        "confidence": "high"})


@pytest.fixture(scope="module")
def packet(cohort):
    """A real packet widened with one long passage.

    Committed fixture packets render ~150-character passages, too short to
    carry the 972-character span the failed run actually cited. The passage is
    lengthened here so the size bounds are the only thing under test.
    """
    source = cohort.packets[0]
    body = source["passages"][0]["text"]
    long_text = (body + " ") * (2000 // max(len(body), 1) + 2)
    return dict(source, passages=[
        dict(source["passages"][0], passage_id="synthetic-long-passage",
             text=long_text)])


# --- the prompt --------------------------------------------------------------------


def test_the_v2_2_prompt_is_a_successor_not_an_edit():
    assert (ROOT / ccs.V2_1.prompt_path).is_file()
    assert PROMPT != V2_1_PROMPT
    assert "— v2.2" in PROMPT.splitlines()[0]


def test_every_placeholder_survives_the_successor():
    for token in lcl._PLACEHOLDERS:
        assert PROMPT.count(token) == 1, token


def test_the_declared_limits_match_the_v2_2_axes_contract():
    limits = PROMPT.split("## Output size limits", 1)[1]
    props = AXES_V2_2["properties"]
    assert props["evidence"]["maxItems"] == 12
    assert "at most 12 objects" in limits
    quote = props["evidence"]["items"]["properties"]["quote"]
    assert quote["maxLength"] == 1200
    assert "at most 1200 characters" in limits
    for field, declared in (("customer_value_archetypes", 4),
                            ("complementary_dependencies", 5),
                            ("boundary_flags", 4), ("contradictions", 4)):
        assert props[field]["maxItems"] == declared, field


def test_the_final_self_check_restates_every_bound():
    """The size section sits tens of thousands of characters earlier."""
    check = " ".join(
        PROMPT.split("## Silent final check", 1)[1].split())
    for token in ("`customer_value_archetypes` at most 4",
                  "`complementary_dependencies` at most 5",
                  "`evidence` at most 12",
                  "at most 1200 characters",
                  "`supported_claim` at most 200",
                  "`boundary_flags` at most 4, each at most 160",
                  "`contradictions` at most 4, each at most 200"):
        assert token in check, token
    assert "No Tier was assigned." in check


def test_the_final_check_forbids_truncating_a_span_to_fit():
    check = " ".join(PROMPT.split("## Silent final check", 1)[1].split())
    assert "no span was cut short to fit a limit" in check


def test_the_quoting_rule_requires_shortest_sufficient_not_shortest():
    assert "shortest **sufficient** contiguous span" in FLAT
    assert "Never shorten a span past the text the claim depends on." in FLAT
    assert "quote it in full up to the limit" in FLAT
    assert "Prefer the shortest direct span." not in FLAT
    assert "Prefer the shortest direct span." in " ".join(V2_1_PROMPT.split())


def test_the_required_json_still_matches_the_axes_contract():
    block = re.search(r"## Required JSON\n\n```json\n(.*?)\n```", PROMPT, re.S)
    keys = re.findall(r'^\s{2}"([a-z_]+)"', block.group(1), re.M)
    assert sorted(keys) == sorted(AXES_V2_2["required"])
    assert not [k for k in keys if "tier" in k]


def test_the_prompt_still_forbids_a_tier_and_ai_wording_inference():
    assert "Do not assign a Tier A/B/C label" in PROMPT
    assert "AI wording" in PROMPT
    assert "It is not authority for any classification result." in PROMPT


def test_the_prompt_fences_are_balanced():
    assert PROMPT.count("```") % 2 == 0


# --- the three real failure shapes -------------------------------------------------


@pytest.mark.parametrize("items,quote_len", OBSERVED_SHAPES)
def test_the_observed_shapes_were_refused_under_v2_1(packet, items, quote_len):
    """Proof the fixtures reproduce the failure, not merely resemble it."""
    payload = _axes(packet, items=items, quote_len=quote_len)
    with pytest.raises(lcl.AxesValidationFailure) as excinfo:
        lcl.validate_axes_output(payload, packet, _validator(AXES_V2_1),
                                 ccs.V2_1.axes_contract)
    assert excinfo.value.reason_code == "axes_contract_violation"


@pytest.mark.parametrize("items,quote_len", OBSERVED_SHAPES)
def test_the_observed_shapes_are_accepted_under_v2_2(packet, items, quote_len):
    axes = lcl.validate_axes_output(
        _axes(packet, items=items, quote_len=quote_len), packet,
        _validator(AXES_V2_2), ccs.V2_2.axes_contract)
    assert len(axes["evidence"]) == items
    assert len(axes["evidence"][0]["quote"]) == quote_len


@pytest.mark.parametrize("items,quote_len,field", [
    (13, 100, "$.evidence"),
    (1, 1201, "$.evidence[0].quote"),
])
def test_the_new_ceilings_still_bite(packet, items, quote_len, field):
    with pytest.raises(lcl.AxesValidationFailure) as excinfo:
        lcl.validate_axes_output(
            _axes(packet, items=items, quote_len=quote_len), packet,
            _validator(AXES_V2_2), ccs.V2_2.axes_contract)
    assert excinfo.value.reason_code == "axes_contract_violation"
    assert field in excinfo.value.detail
    assert ccs.V2_2.axes_contract in excinfo.value.detail


def test_the_boundary_is_exact(packet):
    """12 items and a 1200-character quote pass; one more of either does not."""
    lcl.validate_axes_output(_axes(packet, items=12, quote_len=1200), packet,
                             _validator(AXES_V2_2), ccs.V2_2.axes_contract)
    for items, quote_len in ((13, 1200), (12, 1201)):
        with pytest.raises(lcl.AxesValidationFailure):
            lcl.validate_axes_output(
                _axes(packet, items=items, quote_len=quote_len), packet,
                _validator(AXES_V2_2), ccs.V2_2.axes_contract)


def test_v2_2_still_refuses_what_v2_1_refused_for_substance(packet):
    """Widening a size bound must not widen anything else."""
    validator = _validator(AXES_V2_2)
    payload = json.loads(_axes(packet, items=2, quote_len=100))
    payload["evidence"][0]["quote"] = "text that appears in no passage"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(payload), packet, validator,
                                 ccs.V2_2.axes_contract)
    assert exc.value.reason_code == "quote_resolution_failure"

    tiered = json.loads(_axes(packet, items=2, quote_len=100))
    tiered["tier"] = "TIER_A"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(tiered), packet, validator,
                                 ccs.V2_2.axes_contract)
    assert exc.value.reason_code == "model_emitted_tier"

    bad = json.loads(_axes(packet, items=2, quote_len=100))
    bad["software_centrality"] = "MOSTLY_CORE"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(bad), packet, validator,
                                 ccs.V2_2.axes_contract)
    assert exc.value.reason_code == "axes_contract_violation"


# --- ADR-129: V2.2 is frozen, and V2.3 did not reach back into it ------------------


def test_the_v2_2_prompt_is_byte_unchanged_by_adr_129():
    from hashlib import sha256
    assert sha256((ROOT / ccs.V2_2.prompt_path).read_bytes()).hexdigest() == \
        "bafa3a5b8800cd572e5bb454df1bc0693ffb2fce6f237ca6f31fa8674d228e6b"


def test_the_v2_2_axes_and_record_contracts_are_byte_unchanged():
    axes = json.loads((ROOT / ccs.V2_2.axes_schema).read_text(encoding="utf-8"))
    assert axes["properties"]["evidence"]["maxItems"] == 12
    assert axes["properties"]["evidence"]["items"]["properties"]["quote"][
        "maxLength"] == 1200
    record = json.loads((ROOT / ccs.V2_2.record_schema).read_text(encoding="utf-8"))
    assert record["properties"]["record_contract"]["const"] == \
        "universe_classifier_record@0.2.0"


def test_v2_3_reuses_these_very_contracts():
    """V2.3 is a prompt successor; it points at V2.2's own schema files."""
    assert ccs.V2_3.axes_schema == ccs.V2_2.axes_schema
    assert ccs.V2_3.record_schema == ccs.V2_2.record_schema
    assert ccs.V2_3.prompt_path != ccs.V2_2.prompt_path


def test_the_v2_2_prompt_lacks_the_v2_3_discipline():
    """Proof the discipline is genuinely new rather than already present."""
    flat = " ".join(PROMPT.split())
    for token in ("A quote is a copy operation, not a writing task.",
                  "Evidence is a sparse support set",
                  "The only legal `evidence.axis` values",
                  "Never put an output JSON field name in `evidence.axis`"):
        assert token not in flat, token
