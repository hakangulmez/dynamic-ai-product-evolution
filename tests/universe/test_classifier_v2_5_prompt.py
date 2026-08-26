"""ADR-132 tests: the V2.5 contracts, and the failure shapes they make unreachable.

Every quote defect the V2.4 calibrations produced is expressed here as an
attempted response and asserted to be refused — not by a length bound or a
resolution check, but as an unknown property, because the 0.4.0 axes contract
has no ``quote`` field at all. That is the difference between this successor and
the three before it: the shapes are not caught, they are unrepresentable.
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_contract_set as ccs
from dynamic_ai_products import classifier_span_index as csi
from dynamic_ai_products import lineage_classifier_v2_1 as lcl

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import (  # noqa: E402
    ROOT,
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
)

PROMPT = (ROOT / ccs.V2_5.prompt_path).read_text(encoding="utf-8")
V2_4_PROMPT = (ROOT / ccs.V2_4.prompt_path).read_text(encoding="utf-8")
FLAT = " ".join(PROMPT.split())
AXES = json.loads((ROOT / ccs.V2_5.axes_schema).read_text(encoding="utf-8"))
AXES_V2_4 = json.loads((ROOT / ccs.V2_4.axes_schema).read_text(encoding="utf-8"))
RECORD = json.loads((ROOT / ccs.V2_5.record_schema).read_text(encoding="utf-8"))
LEGAL_AXES = ["customer_value", "centrality", "dependency", "structure",
              "materiality", "eligibility"]


def _check() -> str:
    return " ".join(PROMPT.split("## Silent final check", 1)[1].split())


def _validator(schema):
    return Draft202012Validator(schema, format_checker=FormatChecker())


@pytest.fixture(scope="module")
def rules():
    return csi.load_span_index_rules(ROOT)


@pytest.fixture(scope="module")
def packet(cohort):
    return cohort.packets[0]


@pytest.fixture(scope="module")
def index(packet, rules):
    return csi.build_span_index(packet, rules)


def _axes(index, *, items=1, span_ref=None, claim_len=100):
    ref = sorted(index.passages)[0]
    return {
        "customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "software_centrality": "CORE",
        "complementary_dependencies": ["NONE_OR_STANDARD_COMPUTE"],
        "firm_structure": "PURE_PLAY", "commercial_materiality": "DOMINANT",
        "customer_facing_functional_product": True,
        "economically_eligible": True, "data_eligible": True,
        "customer_market_orientation": "B2B",
        "boundary_flags": [], "contradictions": [],
        "evidence": [{"axis": LEGAL_AXES[i % len(LEGAL_AXES)],
                      "passage_ref": ref,
                      "span_ref": span_ref or f"{ref}:S001",
                      "supported_claim": "C" * claim_len} for i in range(items)],
        "confidence": "high"}


# --- successor identity ---------------------------------------------------------------


def test_the_v2_5_prompt_is_a_successor_not_an_edit():
    assert PROMPT != V2_4_PROMPT
    assert "— v2.5" in PROMPT.splitlines()[0]


@pytest.mark.parametrize("contract_set,digest", [
    (ccs.V2_1, "8b8c94807cd08a9dd6c2431b74525931fa0202443ad113a8e26d77b7ac77598b"),
    (ccs.V2_2, "bafa3a5b8800cd572e5bb454df1bc0693ffb2fce6f237ca6f31fa8674d228e6b"),
    (ccs.V2_3, "991c8a47b61141d801e61c084b0809eb52a7f72d3f61c03daea22f7f992f8a0a"),
    (ccs.V2_4, "a0b9a7a3ee263da7a0cd278b5ae147ec8b9ed51c0918767ae67c663efe067f6b"),
])
def test_the_earlier_prompts_are_byte_frozen(contract_set, digest):
    assert sha256((ROOT / contract_set.prompt_path).read_bytes()).hexdigest() == digest


def test_the_v2_5_contract_set_declares_the_new_protocol():
    assert ccs.V2_5.evidence_protocol == "selected_span"
    assert ccs.V2_5.axes_contract == "universe_classifier_axes_record@0.4.0"
    assert ccs.V2_5.record_contract == "universe_classifier_record@0.4.0"
    assert ccs.V2_5.taxonomy_version == "universe_classifier_axes_v2_5"
    for earlier in (ccs.V2_1, ccs.V2_2, ccs.V2_3, ccs.V2_4):
        assert earlier.evidence_protocol == "model_quote"
        assert earlier.span_index_config is None
        assert ccs.V2_5.axes_schema != earlier.axes_schema
        assert ccs.V2_5.record_schema != earlier.record_schema


# --- the contract removed the quote ---------------------------------------------------


def test_the_axes_contract_has_no_quote_field():
    item = AXES["properties"]["evidence"]["items"]
    assert "quote" not in item["properties"]
    assert item["required"] == ["axis", "passage_ref", "span_ref", "supported_claim"]
    assert item["additionalProperties"] is False
    assert item["properties"]["span_ref"]["pattern"] == csi.SPAN_REF_PATTERN


def test_the_unchanged_bounds_are_unchanged():
    assert AXES["properties"]["evidence"]["maxItems"] == 12
    item = AXES["properties"]["evidence"]["items"]
    assert item["properties"]["supported_claim"]["maxLength"] == 300
    assert item["properties"]["axis"]["enum"] == LEGAL_AXES
    for name, spec in AXES_V2_4["properties"].items():
        if name == "evidence":
            continue
        assert AXES["properties"][name] == spec, name
    assert AXES["required"] == AXES_V2_4["required"]


def test_the_stored_record_separates_model_authored_from_derived():
    stored = RECORD["properties"]["axes"]["oneOf"][1]["properties"]["evidence"]["items"]
    assert stored["required"] == [
        "axis", "passage_ref", "span_ref", "supported_claim",
        "resolved_quote", "span_start", "span_end", "span_sha256"]
    for derived in ("resolved_quote", "span_start", "span_end", "span_sha256"):
        assert "PIPELINE-DERIVED" in stored["properties"][derived]["description"]
    assert stored["properties"]["resolved_quote"]["maxLength"] == 2000
    assert RECORD["properties"]["record_contract"]["const"] == \
        "universe_classifier_record@0.4.0"
    assert "span_index_version" in RECORD["required"]


def test_a_model_can_never_write_a_derived_field(index):
    """The axes contract the model is validated against forbids all four."""
    validator = _validator(AXES)
    for derived, value in (("resolved_quote", "x"), ("span_start", 0),
                           ("span_end", 1), ("span_sha256", "0" * 64)):
        payload = _axes(index)
        payload["evidence"][0][derived] = value
        errors = list(validator.iter_errors(payload))
        assert errors, derived
        assert any("additionalProperties" in str(e.validator) or
                   "Additional properties" in e.message for e in errors), derived


# --- every real V2.4 quote-failure shape is now unrepresentable -----------------------


@pytest.mark.parametrize("label,quote", [
    ("row1 duplicated word", "…K-12 districts and schools in more more than 100 countries."),
    ("row2 re-cased TESSCO", "Tessco Technologies Incorporated (which we sometimes refer"),
    ("row2 dropped U+200B", "Tessco.com ® is our e-commerce site and the digital gateway"),
    ("row3 three-span splice", "Our powerful image analysis system processes these images"),
    ("row5 leading word swap", "For the year ended September 30, 2021 sales and shipments"),
    ("row6 two-span splice", "Our machine learning technology may be embedded within"),
    ("row8 composed quote", "A part of our omni-channel growth strategy, we are focused"),
])
def test_each_diagnosed_quote_shape_is_refused_as_an_unknown_property(
        index, label, quote):
    """Not caught by a bound or a resolution check — unrepresentable."""
    payload = _axes(index)
    payload["evidence"][0]["quote"] = quote
    errors = list(_validator(AXES).iter_errors(payload))
    assert errors, label
    assert any("Additional properties" in e.message or "quote" in e.message
               for e in errors), label


def test_a_v2_4_response_fails_the_v2_5_contract_and_the_reverse(index):
    ref = sorted(index.passages)[0]
    v2_4_shape = _axes(index)
    del v2_4_shape["evidence"][0]["span_ref"]
    v2_4_shape["evidence"][0]["quote"] = index.passages[ref].units[0]
    assert list(_validator(AXES).iter_errors(v2_4_shape))
    v2_5_shape = _axes(index)
    assert list(_validator(AXES_V2_4).iter_errors(v2_5_shape))


# --- the runtime validator -------------------------------------------------------------


def test_a_well_formed_selection_is_accepted_and_resolved(packet, index):
    payload = _axes(index)
    axes = lcl.validate_span_axes_output(
        json.dumps(payload), packet, _validator(AXES), ccs.V2_5.axes_contract, index)
    item = axes["evidence"][0]
    ref = sorted(index.passages)[0]
    assert item["resolved_quote"] == index.passages[ref].units[0]
    assert item["span_sha256"] == sha256(
        item["resolved_quote"].encode("utf-8")).hexdigest()
    assert 0 <= item["span_start"] < item["span_end"] <= len(
        index.passages[ref].normalized)
    assert index.passages[ref].normalized[
        item["span_start"]:item["span_end"]] == item["resolved_quote"]


def test_a_real_but_unconvincing_span_is_still_accepted(packet, index):
    """Relevance is the reviewer's question, not the pipeline's.

    A span that parses, is displayed and resolves in range is stored even when
    the claim it is attached to plainly does not follow from it. Refusing it
    here would be the pipeline scoring evidence.
    """
    ref = next(r for r, s in index.passages.items() if len(s.units) >= 2)
    payload = _axes(index, span_ref=f"{ref}:S002")
    payload["evidence"][0]["passage_ref"] = ref
    payload["evidence"][0]["supported_claim"] = "Unrelated conclusion about pricing."
    axes = lcl.validate_span_axes_output(
        json.dumps(payload), packet, _validator(AXES), ccs.V2_5.axes_contract, index)
    assert axes["evidence"][0]["resolved_quote"] == index.passages[ref].units[1]
    assert axes["evidence"][0]["supported_claim"] == \
        "Unrelated conclusion about pricing."


@pytest.mark.parametrize("span_ref,reason", [
    ("P999:S001", "span_reference_unresolvable"),
    ("P001:S999", "span_reference_unresolvable"),
    ("P001:S003-S001", "span_reference_unresolvable"),
    ("P001:S000", "span_reference_unresolvable"),
    ("not-a-span", "span_reference_unresolvable"),
])
def test_a_bad_span_ref_is_a_bounded_failure(packet, index, span_ref, reason):
    payload = _axes(index, span_ref=span_ref)
    payload["evidence"][0]["passage_ref"] = span_ref.split(":")[0][:4] \
        if ":" in span_ref else "P001"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_span_axes_output(json.dumps(payload), packet, _validator(AXES),
                                      ccs.V2_5.axes_contract, index)
    assert exc.value.reason_code in (reason, "axes_contract_violation")


def test_the_unchanged_substance_refusals_still_fire(packet, index):
    validator = _validator(AXES)
    tiered = _axes(index)
    tiered["tier"] = "TIER_A"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_span_axes_output(json.dumps(tiered), packet, validator,
                                      ccs.V2_5.axes_contract, index)
    assert exc.value.reason_code == "model_emitted_tier"

    unsupported = _axes(index)
    unsupported["evidence"] = []
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_span_axes_output(json.dumps(unsupported), packet, validator,
                                      ccs.V2_5.axes_contract, index)
    assert exc.value.reason_code == "unsupported_conclusion"

    bad_axis = _axes(index)
    bad_axis["evidence"][0]["axis"] = "software_centrality"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_span_axes_output(json.dumps(bad_axis), packet, validator,
                                      ccs.V2_5.axes_contract, index)
    assert exc.value.reason_code == "axes_contract_violation"

    over_evidence = _axes(index, items=13)
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_span_axes_output(json.dumps(over_evidence), packet, validator,
                                      ccs.V2_5.axes_contract, index)
    assert exc.value.reason_code == "axes_contract_violation"

    over_claim = _axes(index, claim_len=301)
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_span_axes_output(json.dumps(over_claim), packet, validator,
                                      ccs.V2_5.axes_contract, index)
    assert exc.value.reason_code == "axes_contract_violation"


# --- every accepted V2.4 quote shape has a containing V2.5 span ------------------------


def test_every_fixture_quote_shape_has_a_containing_span(cohort, rules):
    """The property the ADR-132 measurement rests on, on fixture packets.

    A model that could quote a substring can select the span containing it, so
    the protocol change costs no evidence — only precision, which the review
    gate is asked about separately.
    """
    checked = 0
    for packet in cohort.packets:
        index = csi.build_span_index(packet, rules)
        for spans in index.passages.values():
            if not spans.units:
                continue
            for unit in spans.units[:3]:
                inner = unit[5:60] if len(unit) > 65 else unit
                start = spans.normalized.find(inner)
                assert start >= 0
                end = start + len(inner)
                lo = max(k for k, (s, _e) in enumerate(spans.offsets) if s <= start)
                hi = lo
                while hi < len(spans.units) - 1 and spans.offsets[hi][1] < end:
                    hi += 1
                span = spans.normalized[spans.offsets[lo][0]:spans.offsets[hi][1]]
                assert inner in span
                checked += 1
    assert checked


# --- the renderer -----------------------------------------------------------------------


def test_the_renderer_adds_markers_without_touching_earlier_versions(packet, index,
                                                                     cohort):
    admission = {"admission_origin": "human_review",
                 "admitted_status": "LIKELY_ELIGIBLE", "context_evidence": []}
    without, _ = lcl.render_classifier_prompt(V2_4_PROMPT, packet, admission)
    with_spans, _ = lcl.render_classifier_prompt(PROMPT, packet, admission,
                                                 span_index=index)
    assert "[S001]" not in without
    assert "[S001]" in with_spans


def test_every_renderer_placeholder_survives():
    for token in lcl._PLACEHOLDERS:
        assert PROMPT.count(token) == 1, token


def test_the_required_json_matches_the_axes_contract():
    import re as _re
    block = _re.search(r"## Required JSON\n\n```json\n(.*?)\n```", PROMPT, _re.S)
    keys = _re.findall(r'^\s{2}"([a-z_]+)"', block.group(1), _re.M)
    assert sorted(keys) == sorted(AXES["required"])
    assert '"span_ref": "P001:S001"' in block.group(0)
    assert '"quote"' not in block.group(0)


# --- the prompt says selection, not copying --------------------------------------------


@pytest.mark.parametrize("token", [
    "**You do not write quotes. You select them.**",
    "There is no `quote` field in the output, and any response containing one is refused.",
    "the pipeline retrieves that exact text from the filing itself",
    "The run must be contiguous and inside a single passage.",
    "Write the range in reading order",
    "Never invent a marker. Every ordinal you write must be one you saw.",
    "Select the narrowest span that carries the claim",
])
def test_the_prompt_states_the_selection_protocol(token):
    assert token in FLAT, token


@pytest.mark.parametrize("token", [
    "No evidence object contains a `quote` field.",
    "Every `span_ref` names markers that appear in the displayed packet",
    "Every `passage_ref` names the same passage as its `span_ref`.",
    "Every selected span is the narrowest one that carries its claim",
])
def test_the_final_check_restates_the_selection_rules(token):
    assert token in _check(), token


def test_the_prompt_keeps_the_earlier_guarantees():
    assert "Do not assign a Tier A/B/C label" in PROMPT
    assert "It is not authority for any classification result." in PROMPT
    assert "Market orientation is descriptive only." in PROMPT
    assert "At most two objects for any one axis" in FLAT
    assert "`supported_claim`: at most 300 characters." in PROMPT


def test_the_v2_4_prompt_lacks_the_v2_5_protocol():
    flat_v2_4 = " ".join(V2_4_PROMPT.split())
    for token in ("**You do not write quotes. You select them.**", "span_ref",
                  "[S001]"):
        assert token not in flat_v2_4, token


# --- ADR-133: V2.5 is frozen, and V2.6 reuses it rather than editing it -----------


def test_the_v2_5_prompt_is_byte_unchanged_by_adr_133():
    assert sha256((ROOT / ccs.V2_5.prompt_path).read_bytes()).hexdigest() == \
        "f09c6f8f2a6a74644db08333ebe1c7833692715190703c6b323617d49dc01581"


def test_v2_6_reuses_every_v2_5_contract_by_reference():
    """Identity, not equality: V2.6 points at V2.5's own files."""
    assert ccs.V2_6.prompt_path == ccs.V2_5.prompt_path
    assert ccs.V2_6.axes_schema == ccs.V2_5.axes_schema
    assert ccs.V2_6.record_schema == ccs.V2_5.record_schema
    assert ccs.V2_6.axes_contract == ccs.V2_5.axes_contract
    assert ccs.V2_6.record_contract == ccs.V2_5.record_contract
    assert ccs.V2_6.taxonomy_version == ccs.V2_5.taxonomy_version
    assert ccs.V2_6.evidence_protocol == ccs.V2_5.evidence_protocol
    assert ccs.V2_6.span_index_config == ccs.V2_5.span_index_config
    assert ccs.V2_6.output_prefix == "v2_6_" != ccs.V2_5.output_prefix


def test_the_v2_5_manifests_still_refuse_a_null_token_report():
    """What ADR-133 fixed forward, pinned as still broken backward."""
    accounting = json.loads(
        (ROOT / "schemas/universe_classifier_calibration_manifest.v5.schema.json")
        .read_text(encoding="utf-8"))["properties"]["request_accounting"]
    assert accounting["additionalProperties"] == {"type": "integer"}
    assert "properties" not in accounting
