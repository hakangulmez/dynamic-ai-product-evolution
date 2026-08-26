"""ADR-130 tests: one bound moved, and two defects a bound cannot reach.

The V2.3 calibration stopped after three rows and every one of them carried
exactly one schema error — a ``supported_claim`` of 233, 204 and 204 characters
against a 200-character cap. Everything V2.3 was written to fix had held: quote
lengths were 972, 829 and 994 inside a ceiling of 1200, evidence counts were 12,
12 and 8 inside a cap of 12, and all 32 evidence objects carried legal axis
labels. So ``supported_claim`` rises to 300 and nothing else about the axes
moves.

Two of the three rows would still fail, and these tests say so out loud. Row 2
spliced two real spans with an ellipsis; row 3 prepended a subject the passage
does not carry. Both are reproduced structurally here — shapes, not archived
bytes, which belong to the contract their run used — and both must still be
refused under V2.4, because a widening that rescued them would be a relaxation
of acceptance rather than a correction of a bound.
"""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
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

PROMPT = (ROOT / ccs.V2_4.prompt_path).read_text(encoding="utf-8")
V2_3_PROMPT = (ROOT / ccs.V2_3.prompt_path).read_text(encoding="utf-8")
#: Reflowed to single spaces so assertions test wording, not line wrapping.
FLAT = " ".join(PROMPT.split())
AXES = json.loads((ROOT / ccs.V2_4.axes_schema).read_text(encoding="utf-8"))
AXES_V2_3 = json.loads((ROOT / ccs.V2_3.axes_schema).read_text(encoding="utf-8"))
RECORD = json.loads((ROOT / ccs.V2_4.record_schema).read_text(encoding="utf-8"))

LEGAL_AXES = ["customer_value", "centrality", "dependency", "structure",
              "materiality", "eligibility"]

#: The three rows the V2.3 calibration actually produced, as measured by the
#: offline replay: (evidence objects, longest quote, longest supported_claim).
OBSERVED_SHAPES = [(12, 972, 233), (12, 829, 204), (8, 994, 204)]

#: Row 1's per-axis distribution. The schema does not constrain it; the prompt
#: does. Recorded so the difference between the two is explicit.
OBSERVED_ROW_1_PER_AXIS = {"customer_value": 3, "centrality": 1, "dependency": 4,
                           "structure": 1, "materiality": 1, "eligibility": 2}


def _check() -> str:
    return " ".join(PROMPT.split("## Silent final check", 1)[1].split())


def _validator(schema):
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture(scope="module")
def packet(cohort):
    """A real packet widened so a 994-character contiguous span exists in it."""
    source = cohort.packets[0]
    body = source["passages"][0]["text"]
    long_text = (body + " ") * (3000 // max(len(body), 1) + 2)
    return dict(source, passages=[
        dict(source["passages"][0], passage_id="synthetic-long-passage",
             text=long_text)])


def _axes(packet, *, items, quote_len, claim_len, axis_counts=None):
    """A well-formed payload of a given shape, every quote genuinely verbatim."""
    body = " ".join(packet["passages"][0]["text"].split())
    assert len(body) >= quote_len, "fixture packet is too short for this shape"
    quote = body[:quote_len]
    if axis_counts is None:
        labels = [LEGAL_AXES[i % len(LEGAL_AXES)] for i in range(items)]
    else:
        labels = [a for a, n in axis_counts.items() for _ in range(n)]
    assert len(labels) == items
    claims = ["C" * min(claim_len, 40)] * items
    claims[0] = "C" * claim_len
    return {
        "customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "software_centrality": "CORE",
        "complementary_dependencies": ["NONE_OR_STANDARD_COMPUTE"],
        "firm_structure": "PURE_PLAY", "commercial_materiality": "DOMINANT",
        "customer_facing_functional_product": True,
        "economically_eligible": True, "data_eligible": True,
        "customer_market_orientation": "B2B",
        "boundary_flags": [], "contradictions": [],
        "evidence": [{"axis": labels[i], "passage_ref": "P001", "quote": quote,
                      "supported_claim": claims[i]} for i in range(items)],
        "confidence": "high"}


# --- successor identity -------------------------------------------------------------


def test_the_v2_4_prompt_is_a_successor_not_an_edit():
    assert PROMPT != V2_3_PROMPT
    assert "— v2.4" in PROMPT.splitlines()[0]


@pytest.mark.parametrize("contract_set,digest", [
    (ccs.V2_1, "8b8c94807cd08a9dd6c2431b74525931fa0202443ad113a8e26d77b7ac77598b"),
    (ccs.V2_2, "bafa3a5b8800cd572e5bb454df1bc0693ffb2fce6f237ca6f31fa8674d228e6b"),
    (ccs.V2_3, "991c8a47b61141d801e61c084b0809eb52a7f72d3f61c03daea22f7f992f8a0a"),
])
def test_the_earlier_prompts_are_byte_frozen(contract_set, digest):
    assert sha256((ROOT / contract_set.prompt_path).read_bytes()).hexdigest() == digest


def test_the_v2_4_contract_set_names_its_own_everything():
    assert ccs.V2_4.version_id == "v2_4"
    assert ccs.V2_4.output_prefix == "v2_4_"
    assert ccs.V2_4.axes_contract == "universe_classifier_axes_record@0.3.0"
    assert ccs.V2_4.record_contract == "universe_classifier_record@0.3.0"
    assert ccs.V2_4.taxonomy_version == "universe_classifier_axes_v2_4"
    for earlier in (ccs.V2_1, ccs.V2_2, ccs.V2_3):
        assert ccs.V2_4.prompt_path != earlier.prompt_path
        assert ccs.V2_4.axes_schema != earlier.axes_schema
        assert ccs.V2_4.record_schema != earlier.record_schema
        assert ccs.V2_4.taxonomy_version != earlier.taxonomy_version


def test_contract_set_for_resolves_v2_4_and_still_refuses_the_unknown():
    assert ccs.contract_set_for("v2_4") is ccs.V2_4
    # ADR-132 made v2_5 real, so the unknown-id probe moves to the next one.
    assert ccs.contract_set_for("v2_5") is ccs.V2_5
    with pytest.raises(ValueError):
        ccs.contract_set_for("v2_6")


# --- exactly one bound moved --------------------------------------------------------


def test_supported_claim_is_the_only_bound_that_moved():
    claim = AXES["properties"]["evidence"]["items"]["properties"]["supported_claim"]
    assert claim["maxLength"] == 300
    assert claim["minLength"] == 1
    assert AXES_V2_3["properties"]["evidence"]["items"]["properties"][
        "supported_claim"]["maxLength"] == 200


def test_evidence_and_quote_ceilings_are_untouched():
    assert AXES["properties"]["evidence"]["maxItems"] == 12
    assert AXES["properties"]["evidence"]["items"]["properties"]["quote"][
        "maxLength"] == 1200
    assert AXES["properties"]["evidence"]["items"]["properties"]["quote"][
        "minLength"] == 1


def test_nothing_else_in_the_axes_contract_moved():
    """Key by key against 0.2.0, so a stray edit cannot hide in the diff."""
    for key in AXES_V2_3:
        if key in ("$id", "title", "description", "properties"):
            continue
        assert AXES[key] == AXES_V2_3[key], key
    assert sorted(AXES["properties"]) == sorted(AXES_V2_3["properties"])
    for name, spec in AXES_V2_3["properties"].items():
        if name == "evidence":
            continue
        assert AXES["properties"][name] == spec, name
    item = AXES["properties"]["evidence"]["items"]
    old_item = AXES_V2_3["properties"]["evidence"]["items"]
    assert item["required"] == old_item["required"]
    assert item["additionalProperties"] is False
    assert item["properties"]["axis"]["enum"] == LEGAL_AXES
    assert item["properties"]["passage_ref"] == old_item["properties"]["passage_ref"]


def test_the_record_inlines_the_v3_axes_document_byte_for_byte():
    inlined = RECORD["properties"]["axes"]["oneOf"][1]
    assert RECORD["properties"]["axes"]["oneOf"][0] == {"type": "null"}
    assert json.dumps(inlined, sort_keys=True) == json.dumps(AXES, sort_keys=True)
    assert RECORD["properties"]["record_contract"]["const"] == \
        "universe_classifier_record@0.3.0"


def test_the_v2_3_contracts_are_byte_frozen():
    assert AXES_V2_3["properties"]["evidence"]["maxItems"] == 12
    record_v2_3 = json.loads(
        (ROOT / ccs.V2_3.record_schema).read_text(encoding="utf-8"))
    assert record_v2_3["properties"]["record_contract"]["const"] == \
        "universe_classifier_record@0.2.0"
    assert ccs.V2_3.axes_schema == ccs.V2_2.axes_schema
    assert ccs.V2_3.record_schema == ccs.V2_2.record_schema


# --- the 300/301 boundary -----------------------------------------------------------


def test_a_three_hundred_character_claim_validates(packet):
    payload = _axes(packet, items=1, quote_len=200, claim_len=300)
    assert len(payload["evidence"][0]["supported_claim"]) == 300
    axes = lcl.validate_axes_output(json.dumps(payload), packet,
                                    _validator(AXES), ccs.V2_4.axes_contract)
    assert axes["evidence"][0]["supported_claim"] == "C" * 300


def test_a_three_hundred_and_one_character_claim_is_refused(packet):
    payload = _axes(packet, items=1, quote_len=200, claim_len=301)
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(payload), packet, _validator(AXES),
                                 ccs.V2_4.axes_contract)
    assert exc.value.reason_code == "axes_contract_violation"
    assert "supported_claim" in exc.value.detail


def test_an_empty_claim_is_still_refused(packet):
    payload = _axes(packet, items=1, quote_len=200, claim_len=300)
    payload["evidence"][0]["supported_claim"] = ""
    with pytest.raises(lcl.AxesValidationFailure):
        lcl.validate_axes_output(json.dumps(payload), packet, _validator(AXES),
                                 ccs.V2_4.axes_contract)


# --- the three observed V2.3 shapes -------------------------------------------------


@pytest.mark.parametrize("items,quote_len,claim_len", OBSERVED_SHAPES)
def test_each_observed_shape_was_refused_by_the_v2_3_contract(
        packet, items, quote_len, claim_len):
    payload = _axes(packet, items=items, quote_len=quote_len, claim_len=claim_len)
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(payload), packet,
                                 _validator(AXES_V2_3), ccs.V2_3.axes_contract)
    assert exc.value.reason_code == "axes_contract_violation"
    assert "supported_claim" in exc.value.detail


@pytest.mark.parametrize("items,quote_len,claim_len", OBSERVED_SHAPES)
def test_each_observed_shape_now_validates_on_size(packet, items, quote_len,
                                                   claim_len):
    """The bound was the only thing standing between these rows and a record."""
    payload = _axes(packet, items=items, quote_len=quote_len, claim_len=claim_len)
    axes = lcl.validate_axes_output(json.dumps(payload), packet, _validator(AXES),
                                    ccs.V2_4.axes_contract)
    assert len(axes["evidence"]) == items
    assert max(len(e["quote"]) for e in axes["evidence"]) == quote_len


def test_row_ones_per_axis_distribution_is_a_prompt_rule_not_a_contract_one(packet):
    """Four `dependency` objects: the schema admits it, the prompt forbids it."""
    payload = _axes(packet, items=12, quote_len=300, claim_len=233,
                    axis_counts=OBSERVED_ROW_1_PER_AXIS)
    counts: dict[str, int] = {}
    for item in payload["evidence"]:
        counts[item["axis"]] = counts.get(item["axis"], 0) + 1
    assert counts == OBSERVED_ROW_1_PER_AXIS
    assert max(counts.values()) > 2
    lcl.validate_axes_output(json.dumps(payload), packet, _validator(AXES),
                             ccs.V2_4.axes_contract)
    assert "At most two objects for any one axis" in FLAT


def test_row_twos_ellipsis_splice_is_still_refused(packet):
    """Two real spans joined by an ellipsis are not one real span."""
    body = " ".join(packet["passages"][0]["text"].split())
    payload = _axes(packet, items=1, quote_len=200, claim_len=204)
    payload["evidence"][0]["quote"] = f"{body[:152]}... {body[600:758]}"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(payload), packet, _validator(AXES),
                                 ccs.V2_4.axes_contract)
    assert exc.value.reason_code == "quote_resolution_failure"


def test_row_threes_prepended_and_re_cased_quote_is_still_refused(packet):
    """760 of 781 characters verbatim is not verbatim."""
    body = " ".join(packet["passages"][0]["text"].split())
    span = body[10:400]
    payload = _axes(packet, items=1, quote_len=200, claim_len=204)
    payload["evidence"][0]["quote"] = "Our " + span[0].lower() + span[1:]
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(payload), packet, _validator(AXES),
                                 ccs.V2_4.axes_contract)
    assert exc.value.reason_code == "quote_resolution_failure"


def test_the_widening_did_not_relax_any_other_refusal(packet):
    validator = _validator(AXES)
    over_evidence = _axes(packet, items=13, quote_len=200, claim_len=100)
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(over_evidence), packet, validator,
                                 ccs.V2_4.axes_contract)
    assert exc.value.reason_code == "axes_contract_violation"

    over_quote = _axes(packet, items=1, quote_len=1201, claim_len=100)
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(over_quote), packet, validator,
                                 ccs.V2_4.axes_contract)
    assert exc.value.reason_code == "axes_contract_violation"

    tiered = _axes(packet, items=1, quote_len=200, claim_len=100)
    tiered["tier"] = "TIER_A"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(tiered), packet, validator,
                                 ccs.V2_4.axes_contract)
    assert exc.value.reason_code == "model_emitted_tier"

    bad_axis = _axes(packet, items=1, quote_len=200, claim_len=100)
    bad_axis["evidence"][0]["axis"] = "software_centrality"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(bad_axis), packet, validator,
                                 ccs.V2_4.axes_contract)
    assert exc.value.reason_code == "axes_contract_violation"

    unsupported = _axes(packet, items=1, quote_len=200, claim_len=100)
    unsupported["evidence"] = []
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(unsupported), packet, validator,
                                 ccs.V2_4.axes_contract)
    assert exc.value.reason_code == "unsupported_conclusion"

    absent_ref = _axes(packet, items=1, quote_len=200, claim_len=100)
    absent_ref["evidence"][0]["passage_ref"] = "P999"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_axes_output(json.dumps(absent_ref), packet, validator,
                                 ccs.V2_4.axes_contract)
    assert exc.value.reason_code == "quote_resolution_failure"


def test_the_widening_is_one_directional(packet):
    """A V2.4 output is refused by V2.3; a V2.3 output satisfies V2.4."""
    wide = _axes(packet, items=1, quote_len=200, claim_len=250)
    with pytest.raises(lcl.AxesValidationFailure):
        lcl.validate_axes_output(json.dumps(wide), packet, _validator(AXES_V2_3),
                                 ccs.V2_3.axes_contract)
    narrow = _axes(packet, items=1, quote_len=200, claim_len=150)
    lcl.validate_axes_output(json.dumps(narrow), packet, _validator(AXES_V2_3),
                             ccs.V2_3.axes_contract)
    lcl.validate_axes_output(json.dumps(narrow), packet, _validator(AXES),
                             ccs.V2_4.axes_contract)


# --- the new prompt rules -----------------------------------------------------------


@pytest.mark.parametrize("token", [
    "A quote admits no character modification whatsoever",
    "**Ellipsis.**",
    "**Splice.**",
    "**Insertion.**",
    "**Deletion.**",
    "**Re-casing.**",
    "**Any other character change.**",
])
def test_the_quote_modification_ban_names_every_observed_shape(token):
    assert token in FLAT, token


@pytest.mark.parametrize("token", [
    "No `...`, no `…`, no `[...]`",
    "Two spans that are each real do not become one real span by being written next to each other.",
    "Do not prepend `Our`, `The Company`, `We`, or any other subject",
    "No change of an upper-case letter to lower case",
])
def test_the_ban_is_specific_rather_than_general(token):
    assert token in FLAT, token


@pytest.mark.parametrize("token", [
    "`supported_claim` is a conclusion, not an explanation",
    "It is a clause or a short noun phrase — a conclusion label.",
    "Write the conclusion, not the argument for it.",
    "Do not restate what the quote already says.",
])
def test_supported_claim_is_redefined_as_a_conclusion_clause(token):
    assert token in FLAT, token


def test_the_over_long_claim_is_shown_and_rewritten():
    """V2.3 stated the bound twice and never showed what obeying it looks like."""
    section = " ".join(
        PROMPT.split("### `supported_claim` is a conclusion", 1)[1].split())
    assert "indicating a mixed non-separable structure due to the integrated fintech ecosystem." in section
    assert "Mixed non-separable structure; brokerage dominant." in section
    assert "is an outer bound for the rare case that needs qualification, not a target" in section


@pytest.mark.parametrize("token", [
    "count your evidence objects for each of the six axis labels separately",
    "Every one of those six counts must be 0, 1, or 2.",
    "drop objects from that axis until it is at most 2",
    "A high total that hides four objects on one axis is a failure of this rule",
])
def test_the_per_axis_count_check_is_required(token):
    assert token in FLAT, token


def test_the_declared_limits_match_the_moved_contract():
    limits = PROMPT.split("## Output size limits", 1)[1].split("## Required JSON")[0]
    assert "`supported_claim`: at most 300 characters." in limits
    assert "at most 12 objects" in limits
    assert "at most 1200 characters" in limits
    # `contradictions` legitimately keeps its own 200-character entry, so the
    # stale-bound check has to name the field rather than the number.
    assert "`supported_claim`: at most 200 characters." not in limits
    assert "`contradictions`: at most 4 entries, each at most 200 characters." in limits


# --- the final self-check -----------------------------------------------------------


@pytest.mark.parametrize("token", [
    "each `supported_claim` at most 300",
    "No quote carries an ellipsis, a splice, an inserted word or leading subject, a deleted word or clause, a re-cased letter, or any other character modification",
    "every quote is the located span, unaltered",
    "The per-axis counts were taken",
    "is 0, 1, or 2 for each of those six labels separately",
    "Every `supported_claim` is a conclusion clause for its axis, not an explanatory sentence",
])
def test_the_final_check_restates_every_new_rule(token):
    assert token in _check(), token


@pytest.mark.parametrize("token", [
    "Every quote was copied, not written",
    "No quote was normalized, summarized, composed from two spans, truncated past its claim, or moved to another `P`-reference.",
    "Evidence is sparse: normally one object per concluded axis, never more than two for any one axis",
    "no output JSON field name appears there",
    "Any claim without an exact copyable span was dropped",
    "No Tier was assigned.",
    "The admission context did not substitute for the full Item 1 record.",
    "`evidence` at most 12",
    "at most 1200 characters",
])
def test_the_final_check_keeps_every_v2_3_guarantee(token):
    assert token in _check(), token


def test_the_final_check_lists_the_six_axis_labels():
    check = _check()
    for label in LEGAL_AXES:
        assert f"`{label}`" in check, label


# --- V2.3 discipline retained, V2.3 prompt untouched --------------------------------


@pytest.mark.parametrize("token", [
    "A quote is a copy operation, not a writing task.",
    "Decide the one narrow claim this object will support.",
    "Verify the copied quote occurs, exactly as copied, in that cited passage.",
    "Evidence is a sparse support set",
    "At most two objects for any one axis",
    "The only legal `evidence.axis` values",
    "Never put an output JSON field name in `evidence.axis`",
    "**If no exact span can be copied, omit that evidence object.**",
    "Do not assign a Tier A/B/C label",
    "It is not authority for any classification result.",
    "Market orientation is descriptive only.",
])
def test_every_v2_3_discipline_rule_survives(token):
    assert token in FLAT, token


def test_the_six_legal_axis_labels_are_still_listed_with_field_names_forbidden():
    section = " ".join(
        PROMPT.split("### The only legal `evidence.axis` values", 1)[1].split())
    for label in LEGAL_AXES:
        assert f"`{label}`" in section, label
    for field in ("software_centrality", "firm_structure", "commercial_materiality",
                  "complementary_dependencies", "customer_value_archetypes",
                  "customer_market_orientation"):
        assert f"`{field}`" in section, field


@pytest.mark.parametrize("token", [
    "A quote admits no character modification whatsoever",
    "`supported_claim` is a conclusion, not an explanation",
    "count your evidence objects for each of the six axis labels separately",
    "at most 300 characters",
])
def test_the_v2_3_prompt_lacks_the_v2_4_discipline(token):
    """Proof the discipline is genuinely new rather than already present."""
    assert token not in " ".join(V2_3_PROMPT.split()), token


# --- structure ----------------------------------------------------------------------


def test_every_renderer_placeholder_survives():
    for token in lcl._PLACEHOLDERS:
        assert PROMPT.count(token) == 1, token


def test_the_required_json_still_matches_the_axes_contract():
    block = re.search(r"## Required JSON\n\n```json\n(.*?)\n```", PROMPT, re.S)
    keys = re.findall(r'^\s{2}"([a-z_]+)"', block.group(1), re.M)
    assert sorted(keys) == sorted(AXES["required"])
    assert not [k for k in keys if "tier" in k]


def test_the_prompt_fences_are_balanced():
    assert PROMPT.count("```") % 2 == 0


def test_the_prompt_carries_no_stale_two_hundred_claim_bound():
    assert "each `supported_claim` at most 200" not in FLAT
    assert "`supported_claim`: at most 200 characters." not in FLAT


# --- ADR-132: V2.4 is frozen, and V2.5 did not reach back into it -----------------


def test_the_v2_4_prompt_is_byte_unchanged_by_adr_132():
    assert sha256((ROOT / ccs.V2_4.prompt_path).read_bytes()).hexdigest() == \
        "a0b9a7a3ee263da7a0cd278b5ae147ec8b9ed51c0918767ae67c663efe067f6b"


def test_the_v2_4_axes_and_record_contracts_are_byte_unchanged():
    evidence = AXES["properties"]["evidence"]
    assert evidence["maxItems"] == 12
    assert evidence["items"]["properties"]["quote"]["maxLength"] == 1200
    assert evidence["items"]["properties"]["supported_claim"]["maxLength"] == 300
    assert evidence["items"]["required"] == [
        "axis", "passage_ref", "quote", "supported_claim"]
    assert RECORD["properties"]["record_contract"]["const"] == \
        "universe_classifier_record@0.3.0"


def test_v2_5_forked_rather_than_edited_the_v2_4_contracts():
    assert ccs.V2_5.axes_schema != ccs.V2_4.axes_schema
    assert ccs.V2_5.record_schema != ccs.V2_4.record_schema
    assert ccs.V2_5.prompt_path != ccs.V2_4.prompt_path
    assert ccs.V2_4.evidence_protocol == "model_quote"
    assert ccs.V2_5.evidence_protocol == "selected_span"


def test_the_v2_4_prompt_still_asks_the_model_to_type_the_quote():
    """The regime ADR-132 replaced, pinned so the contrast stays legible."""
    assert "A quote is a copy operation, not a writing task." in FLAT
    assert "`quote`: at most 1200 characters" in FLAT
    assert "span_ref" not in FLAT
    assert "[S001]" not in FLAT
