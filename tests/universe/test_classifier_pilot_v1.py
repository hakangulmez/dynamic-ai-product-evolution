"""Firm-level software-universe pilot: isolation, resolution, and the review path.

The pilot's value depends on three things being true rather than merely intended,
so each is asserted directly: the model cannot see the earlier verdict, it cannot
author evidence text or a tier, and one unresolvable reference degrades one row
instead of ending the run.

Isolation from the V2.x ladder is asserted the same way -- by contract identifiers
and filenames, not by naming convention -- because a pilot that could be loaded by
a V2.x route, or vice versa, would not be a separate experiment.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_contract_set as ccs
from dynamic_ai_products import classifier_pilot_v1 as pilot
from dynamic_ai_products.human_review_overlay import passage_refs

REPO = Path(__file__).resolve().parents[2]
PROMPT = (REPO / pilot.PILOT_PROMPT_PATH).read_text()
AXES = Draft202012Validator(
    json.loads((REPO / pilot.PILOT_AXES_SCHEMA).read_bytes()), format_checker=FormatChecker())
RECORD = Draft202012Validator(
    json.loads((REPO / pilot.PILOT_RECORD_SCHEMA).read_bytes()), format_checker=FormatChecker())
SELECTION = Draft202012Validator(
    json.loads((REPO / pilot.PILOT_SELECTION_SCHEMA).read_bytes()), format_checker=FormatChecker())


def _packet(n_blocks=4):
    """A packet shaped like a real one: heading-derived blocks with byte offsets."""
    texts = [">Item 1. Business.",
             "We license our platform to enterprise customers on a subscription basis.",
             "Our internal research tooling supports product development.",
             "Revenue is derived principally from software subscriptions."][:n_blocks]
    passages, cursor = [], 0
    for i, t in enumerate(texts):
        passages.append({"passage_id": sha256(f"blk{i}".encode()).hexdigest()[:32],
                         "text": t, "byte_start": cursor, "byte_end": cursor + len(t),
                         "section": "item_1", "source_id": "src-1",
                         "text_hash": sha256(t.encode()).hexdigest(),
                         "normalizer_version": "v1"})
        cursor += len(t) + 2
    return {"cik": "0000000001", "accession": "0000000001-22-000001",
            "company_id": "CIK0000000001", "source_id": "src-1",
            "baseline_cutoff": "2022-01-01", "packet_sha256": "a" * 64,
            "passages": passages}


def _axes(**over):
    doc = {"customer_facing_functional_product": "YES",
           "software_centrality": "CORE",
           "firm_structure": "SOFTWARE_DOMINANT",
           "commercial_materiality": "DOMINANT",
           "confidence": "high",
           "evidence": [{"axis": "software_centrality", "passage_ref": "P002"}]}
    doc.update(over)
    return doc


# --- the prompt is the supplied text, and says what it must ---------------------------


def test_the_prompt_asks_the_firm_level_question_only():
    assert PROMPT.startswith("# Software Universe Classifier — Firm-Level Pilot")
    assert "Your task is to make a firm-level judgement. Do not build a product" in PROMPT
    assert "Do not list products, capabilities, tasks, customers, revenue shares" in PROMPT
    collapsed = " ".join(PROMPT.split())
    assert "Assess the firm as a whole. A mention of technology alone is not enough." in collapsed


def test_the_core_question_is_asked_in_two_independent_steps():
    """Existence first, centrality second, and the two are decided separately.

    The combined formulation asked one question whose answer conflated the two:
    a firm with an obvious customer-facing offering that is commercially
    peripheral, and a firm with no such offering at all, both failed it, and
    nothing in the wording distinguished them.
    """
    collapsed = " ".join(PROMPT.split())
    assert ("Using only Item 1, first decide whether the firm offers a commercially "
            "meaningful customer-facing digital or software offering.") in collapsed
    assert ("Then independently decide how central that offering is to the "
            "firm’s overall commercial value.") in collapsed
    # order matters: existence is asked before centrality
    assert collapsed.index("first decide whether the firm offers") < \
        collapsed.index("Then independently decide how central")


def test_the_old_combined_question_is_gone():
    """The single question the split replaced must not survive anywhere."""
    collapsed = " ".join(PROMPT.split())
    assert ("decide whether a customer-facing digital or software offering is "
            "economically central to the firm’s business") not in collapsed
    assert "is economically central to the firm" not in collapsed


def test_the_prompt_withholds_the_earlier_result():
    collapsed = " ".join(PROMPT.split())
    assert ("You receive only the firm’s baseline Item 1 text. You do not receive any "
            "prior high-recall result, human-review decision, prior classification, "
            "or Tier.") in collapsed


def test_the_prompt_names_evidence_blocks_not_paragraphs():
    """The correction that matters: P-refs address existing blocks, not new segments."""
    assert "Existing evidence blocks are marked" in PROMPT
    assert "paragraph" not in PROMPT.lower()
    assert "The full Item 1 is displayed in natural order." in PROMPT


def test_the_prompt_forbids_writing_evidence_text_or_a_tier():
    collapsed = " ".join(PROMPT.split())
    assert "Select zero to three evidence-block references. Select references only." in collapsed
    assert "Do not copy, paraphrase, summarize, or write evidence text." in collapsed
    assert ("Do not write quotes, explanations, product lists, a Tier, candidate Tier, "
            "rule trace, offsets, hashes") in collapsed


def test_the_prompt_keeps_unknown_over_guess():
    assert "use UNKNOWN rather than guessing" in " ".join(PROMPT.split())


@pytest.mark.parametrize("exclusion", [
    "internal, R&D, employee, or back-office software",
    "technology used by a supplier, exchange, partner, franchise network",
    "embedded software in a physical product",
    "a human-delivered service merely assisted by software",
    "future plans, pilots, acquisitions, or investments",
])
def test_the_prompt_lists_the_non_qualifying_technology_categories(exclusion):
    assert exclusion in " ".join(PROMPT.split()), exclusion


# --- the model-facing contract --------------------------------------------------------


def test_the_model_contract_is_four_axes_confidence_and_addresses():
    schema = AXES.schema
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted([
        "customer_facing_functional_product", "software_centrality", "firm_structure",
        "commercial_materiality", "confidence", "evidence"])
    item = schema["properties"]["evidence"]["items"]
    assert item["required"] == ["axis", "passage_ref"]
    assert item["additionalProperties"] is False
    assert schema["properties"]["evidence"]["minItems"] == 0
    assert schema["properties"]["evidence"]["maxItems"] == 3


@pytest.mark.parametrize("field", [
    "evidence_text", "text_start", "text_end", "text_sha256", "provenance",
    "quote", "span_ref",
])
def test_the_model_may_not_author_a_pipeline_field(field):
    doc = _axes()
    doc["evidence"][0][field] = "x"
    assert list(AXES.iter_errors(doc)), f"{field} must be unrepresentable"


@pytest.mark.parametrize("field", ["tier", "candidate_tier", "tier_rule_trace",
                                   "products", "capabilities", "tasks", "quote"])
def test_a_forbidden_top_level_field_yields_review_not_a_run_failure(field):
    packet = _packet()
    doc = _axes(**{field: "anything"})
    with pytest.raises(pilot.PilotAxesFailure) as ei:
        pilot.validate_pilot_axes_output(json.dumps(doc), packet, AXES)
    assert ei.value.reason_code == "model_emitted_forbidden_field"


def test_more_than_three_evidence_references_is_refused():
    doc = _axes(evidence=[{"axis": "software_centrality", "passage_ref": f"P00{i}"}
                          for i in range(1, 5)])
    assert list(AXES.iter_errors(doc))


def test_axis_vocabulary_is_closed():
    assert list(AXES.iter_errors(_axes(software_centrality="VERY_CORE")))
    assert list(AXES.iter_errors(_axes(customer_facing_functional_product=True)))
    assert list(AXES.iter_errors(_axes(confidence="certain")))


# --- deterministic evidence-block resolution ------------------------------------------


def test_resolution_reuses_the_existing_passage_reference_map():
    """No new segmenter: the pilot addresses the same blocks everything else does."""
    packet = _packet()
    refs = passage_refs(packet)
    assert sorted(refs) == ["P001", "P002", "P003", "P004"]
    for ref in refs:
        block = pilot.resolve_evidence_block(ref, packet)
        passage = next(p for p in packet["passages"] if p["passage_id"] == refs[ref])
        assert block.text == passage["text"]
        assert block.passage_id == refs[ref]
        assert block.byte_start == passage["byte_start"]
        assert block.byte_end == passage["byte_end"]
        assert block.sha256 == sha256(passage["text"].encode()).hexdigest()


def test_resolution_is_deterministic_across_repeated_calls():
    packet = _packet()
    a = pilot.resolve_evidence_block("P003", packet)
    b = pilot.resolve_evidence_block("P003", packet)
    assert a == b


def test_the_pipeline_supplies_text_offsets_and_digest_the_model_never_sent():
    packet = _packet()
    out = pilot.validate_pilot_axes_output(json.dumps(_axes()), packet, AXES)
    item = out["evidence"][0]
    assert sorted(item) == ["axis", "byte_end", "byte_start", "evidence_text",
                            "passage_id", "passage_ref", "provenance", "text_sha256"]
    assert item["provenance"] == "pipeline_derived"
    assert item["evidence_text"] == packet["passages"][1]["text"]
    assert item["text_sha256"] == sha256(item["evidence_text"].encode()).hexdigest()


# --- an unresolvable reference degrades one row, never the run ------------------------


@pytest.mark.parametrize("bad_ref", ["P099", "P005"])
def test_an_unresolvable_reference_raises_the_review_reason(bad_ref):
    packet = _packet()
    with pytest.raises(pilot.PilotAxesFailure) as ei:
        pilot.validate_pilot_axes_output(
            json.dumps(_axes(evidence=[{"axis": "software_centrality",
                                        "passage_ref": bad_ref}])), packet, AXES)
    assert ei.value.reason_code == "evidence_reference_unresolvable"


def test_an_unresolvable_reference_becomes_a_review_row_not_a_failure():
    packet = _packet()
    row = {"cik": "0000000001", "accession": "0000000001-22-000001",
           "company_id": "CIK0000000001", "source_id": "src-1",
           "admission_provenance": {"release_origin": "model_screen"}}
    rec = pilot.build_pilot_record(
        row=row, packet=packet, prompt_sha256="b" * 64,
        model_route={"provider": "p", "model_label": "m"},
        raw=json.dumps(_axes(evidence=[{"axis": "software_centrality",
                                        "passage_ref": "P099"}])),
        validator=AXES)
    RECORD.validate(rec)
    assert rec["record_kind"] == "review_uncertain"
    assert rec["review_reason_code"] == "evidence_reference_unresolvable"
    assert rec["axes"] is None
    assert "tier" not in rec
    assert "P099" in rec["review_detail"]


@pytest.mark.parametrize("raw,reason", [
    ("{not json", "invalid_model_json"),
    ('["a"]', "invalid_model_json"),
    ('{"software_centrality": "CORE"}', "pilot_axes_contract_violation"),
])
def test_every_bad_response_shape_becomes_a_review_row(raw, reason):
    packet = _packet()
    row = {"cik": "0000000001", "accession": "0000000001-22-000001",
           "company_id": "CIK0000000001", "source_id": "src-1",
           "admission_provenance": {}}
    rec = pilot.build_pilot_record(
        row=row, packet=packet, prompt_sha256="b" * 64,
        model_route={"provider": "p", "model_label": "m"}, raw=raw,
        validator=AXES)
    RECORD.validate(rec)
    assert rec["record_kind"] == "review_uncertain"
    assert rec["review_reason_code"] == reason
    assert rec["review_reason_code"] in pilot.REVIEW_REASONS


def test_the_review_reason_vocabulary_is_closed_and_all_non_fatal():
    assert pilot.REVIEW_REASONS == (
        "invalid_model_json", "pilot_axes_contract_violation",
        "model_emitted_forbidden_field", "evidence_reference_unresolvable")


# --- no tier anywhere in the pilot -----------------------------------------------------


def test_a_classified_row_carries_axes_and_no_tier():
    packet = _packet()
    rec = pilot.build_pilot_record(
        row={"cik": "0000000001", "accession": "0000000001-22-000001",
             "company_id": "CIK0000000001", "source_id": "src-1",
             "admission_provenance": {}},
        packet=packet, prompt_sha256="b" * 64,
        model_route={"provider": "p", "model_label": "m"},
        raw=json.dumps(_axes()), validator=AXES)
    RECORD.validate(rec)
    assert rec["record_kind"] == "classified"
    assert "tier" not in rec and "tier_rule_trace" not in rec
    assert sorted(rec["axes"]) == ["commercial_materiality", "confidence",
                                   "customer_facing_functional_product", "evidence",
                                   "firm_structure", "software_centrality"]


def test_the_record_contract_has_no_tier_field_at_all():
    props = RECORD.schema["properties"]
    for gone in ("tier", "tier_rule_trace", "candidate_tier"):
        assert gone not in props, gone
    stored = next(b for b in RECORD.schema["properties"]["axes"]["oneOf"]
                  if b.get("type") == "object")
    for gone in ("tier", "tier_rule_trace"):
        assert gone not in stored["properties"], gone


def test_the_pilot_module_imports_no_tier_engine():
    source = (REPO / "src/dynamic_ai_products/classifier_pilot_v1.py").read_text()
    for gone in ("derive_tier", "ClassifierTierRules", "TierDerivation",
                 "classifier_tier_engine", "normalize_axes_for_tier"):
        assert gone not in source, gone


def test_build_pilot_record_takes_no_tier_rules():
    import inspect
    params = list(inspect.signature(pilot.build_pilot_record).parameters)
    assert "tier_rules" not in params
    assert params == ["row", "packet", "prompt_sha256", "model_route", "raw", "validator"]


# --- the two dropped eligibility axes are gone everywhere ------------------------------


@pytest.mark.parametrize("gone", ["data_eligible", "economically_eligible"])
def test_the_dropped_axes_appear_nowhere_in_the_pilot(gone):
    assert gone not in PROMPT
    assert gone not in json.dumps(AXES.schema)
    assert gone not in json.dumps(RECORD.schema)
    assert gone not in (REPO / "src/dynamic_ai_products/classifier_pilot_v1.py").read_text()


@pytest.mark.parametrize("gone", ["data_eligible", "economically_eligible"])
def test_a_response_carrying_a_dropped_axis_is_refused(gone):
    assert list(AXES.iter_errors(_axes(**{gone: "YES"})))


# --- zero to three references, and the empty-evidence rule ----------------------------


def test_zero_evidence_is_valid_only_when_every_substantive_axis_is_unknown():
    all_unknown = _axes(customer_facing_functional_product="UNKNOWN",
                        software_centrality="UNKNOWN", firm_structure="UNKNOWN",
                        commercial_materiality="UNKNOWN", confidence="low",
                        evidence=[])
    assert not list(AXES.iter_errors(all_unknown))


@pytest.mark.parametrize("axis,value", [
    ("customer_facing_functional_product", "YES"),
    ("software_centrality", "CORE"),
    ("firm_structure", "PURE_PLAY"),
    ("commercial_materiality", "DOMINANT"),
])
def test_a_stated_conclusion_with_no_reference_is_refused(axis, value):
    doc = _axes(customer_facing_functional_product="UNKNOWN",
                software_centrality="UNKNOWN", firm_structure="UNKNOWN",
                commercial_materiality="UNKNOWN", evidence=[])
    doc[axis] = value
    assert list(AXES.iter_errors(doc)), f"{axis}={value} with no evidence must be refused"


def test_one_two_and_three_references_are_all_accepted():
    for n in (1, 2, 3):
        doc = _axes(evidence=[{"axis": "software_centrality", "passage_ref": f"P00{i+1}"}
                              for i in range(n)])
        assert not list(AXES.iter_errors(doc)), n


def test_an_all_unknown_row_with_no_evidence_stores_as_classified():
    packet = _packet()
    rec = pilot.build_pilot_record(
        row={"cik": "0000000001", "accession": "0000000001-22-000001",
             "company_id": "CIK0000000001", "source_id": "src-1",
             "admission_provenance": {}},
        packet=packet, prompt_sha256="b" * 64,
        model_route={"provider": "p", "model_label": "m"},
        raw=json.dumps(_axes(customer_facing_functional_product="UNKNOWN",
                             software_centrality="UNKNOWN", firm_structure="UNKNOWN",
                             commercial_materiality="UNKNOWN", confidence="low",
                             evidence=[])),
        validator=AXES)
    RECORD.validate(rec)
    assert rec["record_kind"] == "classified"
    assert rec["axes"]["evidence"] == []


# --- a denied product cannot have central software -------------------------------------
#
# The prompt says "Do not return CORE or CO_ESSENTIAL when
# customer_facing_functional_product is NO." Prose alone leaves the pair
# representable, so both contracts refuse it structurally instead.


def _stored_row(**axes_over):
    axes = _axes(**axes_over)
    axes["evidence"] = [{**e, "passage_id": "pid", "evidence_text": "t",
                         "byte_start": 0, "byte_end": 1, "text_sha256": "0" * 64,
                         "provenance": "pipeline_derived"} for e in axes["evidence"]]
    return {"record_contract": "universe_classifier_pilot_record@0.1.0",
            "record_kind": "classified", "cik": "0000000001",
            "accession": "0000000001-22-000001", "company_id": "c", "source_id": "s",
            "packet_sha256": "a" * 64, "prompt_sha256": "b" * 64, "model_route": {},
            "admission_provenance": {}, "review_reason_code": None,
            "review_detail": None, "axes": axes}


@pytest.mark.parametrize("centrality", ["CORE", "CO_ESSENTIAL"])
def test_no_product_with_central_software_is_refused_by_the_model_contract(centrality):
    doc = _axes(customer_facing_functional_product="NO", software_centrality=centrality)
    assert list(AXES.iter_errors(doc)), f"NO + {centrality} must be refused"


@pytest.mark.parametrize("centrality", ["CORE", "CO_ESSENTIAL"])
def test_no_product_with_central_software_is_refused_by_the_stored_contract(centrality):
    row = _stored_row(customer_facing_functional_product="NO",
                      software_centrality=centrality)
    assert list(RECORD.iter_errors(row)), f"stored NO + {centrality} must be refused"


@pytest.mark.parametrize("centrality", ["ENABLING", "PERIPHERAL"])
def test_no_product_with_non_central_software_stays_valid_in_both_contracts(centrality):
    doc = _axes(customer_facing_functional_product="NO", software_centrality=centrality)
    assert not list(AXES.iter_errors(doc)), f"NO + {centrality} must remain valid"
    assert not list(RECORD.iter_errors(_stored_row(
        customer_facing_functional_product="NO", software_centrality=centrality)))


@pytest.mark.parametrize("centrality", ["CORE", "CO_ESSENTIAL", "ENABLING",
                                        "PERIPHERAL", "UNKNOWN"])
def test_an_unknown_product_constrains_centrality_in_neither_contract(centrality):
    """UNKNOWN leaves the question open; constraining it would force a guess."""
    doc = _axes(customer_facing_functional_product="UNKNOWN",
                software_centrality=centrality)
    assert not list(AXES.iter_errors(doc)), f"UNKNOWN + {centrality} must stay valid"
    assert not list(RECORD.iter_errors(_stored_row(
        customer_facing_functional_product="UNKNOWN", software_centrality=centrality)))


@pytest.mark.parametrize("centrality", ["CORE", "CO_ESSENTIAL", "ENABLING",
                                        "PERIPHERAL", "UNKNOWN"])
def test_a_yes_product_constrains_centrality_in_neither_contract(centrality):
    doc = _axes(customer_facing_functional_product="YES", software_centrality=centrality)
    assert not list(AXES.iter_errors(doc))
    assert not list(RECORD.iter_errors(_stored_row(
        customer_facing_functional_product="YES", software_centrality=centrality)))


def test_a_no_plus_core_response_becomes_a_review_row_not_a_run_failure():
    """The contract refuses it; the pilot still records the row and continues."""
    packet = _packet()
    rec = pilot.build_pilot_record(
        row={"cik": "0000000001", "accession": "0000000001-22-000001",
             "company_id": "CIK0000000001", "source_id": "src-1",
             "admission_provenance": {}},
        packet=packet, prompt_sha256="b" * 64,
        model_route={"provider": "p", "model_label": "m"},
        raw=json.dumps(_axes(customer_facing_functional_product="NO",
                             software_centrality="CORE")),
        validator=AXES)
    RECORD.validate(rec)
    assert rec["record_kind"] == "review_uncertain"
    assert rec["review_reason_code"] == "pilot_axes_contract_violation"


def test_both_contracts_carry_both_conditionals():
    """The centrality rule was added beside the empty-evidence rule, not over it."""
    stored = next(b for b in RECORD.schema["properties"]["axes"]["oneOf"]
                  if b.get("type") == "object")
    for name, conditionals in (("model", AXES.schema["allOf"]),
                               ("stored", stored["allOf"])):
        assert len(conditionals) == 2, name
        blob = json.dumps(conditionals)
        assert "empty evidence array" in blob, name
        assert "CORE" in blob and "CO_ESSENTIAL" in blob, name
    # and the empty-evidence rule still behaves
    all_unknown = _axes(customer_facing_functional_product="UNKNOWN",
                        software_centrality="UNKNOWN", firm_structure="UNKNOWN",
                        commercial_materiality="UNKNOWN", confidence="low", evidence=[])
    assert not list(AXES.iter_errors(all_unknown))
    assert list(AXES.iter_errors({**all_unknown, "software_centrality": "ENABLING"}))


# --- stored identity and raw-source offsets -------------------------------------------


def test_every_resolved_block_stores_its_packet_passage_id():
    packet = _packet()
    out = pilot.validate_pilot_axes_output(json.dumps(_axes()), packet, AXES)
    item = out["evidence"][0]
    refs = passage_refs(packet)
    assert item["passage_id"] == refs[item["passage_ref"]]
    assert item["passage_id"] in {p["passage_id"] for p in packet["passages"]}


def test_offsets_are_the_packets_raw_source_boundaries():
    packet = _packet()
    out = pilot.validate_pilot_axes_output(json.dumps(_axes()), packet, AXES)
    item = out["evidence"][0]
    passage = next(p for p in packet["passages"] if p["passage_id"] == item["passage_id"])
    assert item["byte_start"] == passage["byte_start"]
    assert item["byte_end"] == passage["byte_end"]
    schema_text = json.dumps(RECORD.schema)
    assert "RAW SEC" in schema_text
    assert "not in any normalized or re-rendered Item 1 text" in schema_text


# --- the model never sees the earlier verdict -----------------------------------------


def test_the_rendered_prompt_contains_item_1_and_no_admission_context():
    packet = _packet()
    rendered = pilot.render_pilot_prompt(PROMPT, packet)
    for block in packet["passages"]:
        assert block["text"] in rendered
    for ref in ("[P001]", "[P002]", "[P003]", "[P004]"):
        assert ref in rendered
    for leaked in ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN", "admission",
                   "human_review", "model_screen", "screen_output", "TIER_",
                   "overlay", "reviewer"):
        assert leaked not in rendered, leaked


def test_the_renderer_cannot_receive_admission_context_at_all():
    """Structural, not incidental: there is no parameter through which it could."""
    import inspect
    params = list(inspect.signature(pilot.render_pilot_prompt).parameters)
    assert params == ["template", "packet"]


def test_blocks_render_in_natural_order():
    packet = _packet()
    rendered = pilot.render_pilot_prompt(PROMPT, packet)
    positions = [rendered.index(f"[P00{i}]") for i in range(1, 5)]
    assert positions == sorted(positions)


# --- isolation from the whole V2.x ladder ---------------------------------------------


def test_no_pilot_contract_id_collides_with_any_v2_x_contract():
    v2x = set()
    for cs in ccs.CONTRACT_SETS.values():
        v2x |= {cs.axes_contract, cs.record_contract, cs.axes_schema,
                cs.record_schema, cs.prompt_path, cs.taxonomy_version}
    mine = {pilot.PILOT_AXES_CONTRACT, pilot.PILOT_RECORD_CONTRACT,
            pilot.PILOT_SELECTION_CONTRACT, pilot.PILOT_AXES_SCHEMA,
            pilot.PILOT_RECORD_SCHEMA, pilot.PILOT_SELECTION_SCHEMA,
            pilot.PILOT_PROMPT_PATH}
    assert not (v2x & mine), v2x & mine


def test_the_pilot_is_not_registered_as_a_v2_x_contract_version():
    assert "pilot" not in ccs.CONTRACT_SETS
    assert all("pilot" not in v for v in ccs.CONTRACT_SETS)
    with pytest.raises(ValueError, match="Unknown classifier contract version"):
        ccs.contract_set_for("pilot_v1")


def test_a_v2_x_axes_response_is_refused_by_the_pilot_contract():
    v2x_shaped = {
        "customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "software_centrality": "CORE", "complementary_dependencies": ["CUSTOMER_DATA"],
        "firm_structure": "PURE_PLAY", "commercial_materiality": "DOMINANT",
        "customer_facing_functional_product": True, "economically_eligible": True,
        "data_eligible": True, "customer_market_orientation": "B2B",
        "boundary_flags": [], "contradictions": [], "confidence": "high",
        "evidence": [{"axis": "centrality", "passage_ref": "P001",
                      "span_ref": "P001:S001"}]}
    assert list(AXES.iter_errors(v2x_shaped))


def test_a_pilot_response_is_refused_by_the_v2_x_axes_contract():
    v2_8 = Draft202012Validator(
        json.loads((REPO / ccs.V2_8.axes_schema).read_bytes()), format_checker=FormatChecker())
    assert list(v2_8.iter_errors(_axes()))


def test_the_pilot_prompt_is_distinct_from_every_v2_x_prompt():
    mine = sha256((REPO / pilot.PILOT_PROMPT_PATH).read_bytes()).hexdigest()
    for cs in ccs.CONTRACT_SETS.values():
        assert sha256((REPO / cs.prompt_path).read_bytes()).hexdigest() != mine


# --- the ten-firm selection -----------------------------------------------------------


@pytest.fixture(scope="module")
def cohort_rows():
    p = (REPO / "data/runs/universe-classifier-candidate-cohorts/"
         "universe-classifier-candidate-cohort-v1-20260824/"
         "universe_classifier_candidate_records.jsonl")
    if not p.is_file():
        pytest.skip("candidate cohort not present in this checkout")
    return [json.loads(line) for line in p.read_text().splitlines() if line.strip()]


@pytest.fixture(scope="module")
def source_selection():
    p = (REPO / "data/runs/universe-classifier-calibration-selections/"
         "universe-classifier-calibration-selection-v1-20260824/"
         "universe_classifier_calibration_selection.json")
    if not p.is_file():
        pytest.skip("40-row selection not present in this checkout")
    return json.loads(p.read_bytes()), sha256(p.read_bytes()).hexdigest(), str(
        p.relative_to(REPO))


def _built(cohort_rows, source_selection):
    sel, digest, rel = source_selection
    return pilot.build_pilot_selection(
        cohort_rows=cohort_rows, source_selection=sel, source_selection_path=rel,
        source_selection_sha256=digest,
        cohort_manifest_sha256="1" * 64, packet_manifest_sha256="2" * 64,
        selection_id="pilot-selection-fixture", run_timestamp="2026-01-01T00:00:00+00:00")


def test_the_selection_is_ten_rows_and_valid(cohort_rows, source_selection):
    built = _built(cohort_rows, source_selection)
    SELECTION.validate(built)
    assert len(built["rows"]) == 10
    assert len({(r["cik"], r["accession"]) for r in built["rows"]}) == 10
    assert built["no_model_call"] is True


def test_every_pilot_row_comes_from_the_40_row_selection(cohort_rows, source_selection):
    built = _built(cohort_rows, source_selection)
    sel, _, _ = source_selection
    source_keys = {(r["cik"], r["accession"]) for r in sel["rows"]}
    assert {(r["cik"], r["accession"]) for r in built["rows"]} <= source_keys


def test_the_selection_covers_the_four_required_admission_dimensions(
        cohort_rows, source_selection):
    """Checked by admission path, not by the analytic stratum label."""
    rows = _built(cohort_rows, source_selection)["rows"]
    ms_likely = [r for r in rows if r["admission_origin"] == "model_screen"
                 and r["screen_status"] == "LIKELY_ELIGIBLE"]
    ms_boundary = [r for r in rows if r["admission_origin"] == "model_screen"
                   and r["screen_status"] == "BOUNDARY_OR_UNCERTAIN"]
    overlay = [r for r in rows if r["admission_origin"] == "human_review"]
    obvious = [r for r in rows if r["pilot_stratum"] == "P1_obvious_software"]
    ambiguous = [r for r in rows if r["pilot_stratum"] == "P5_economically_ambiguous"]
    assert ms_likely and ms_boundary and overlay and obvious and ambiguous
    assert len(ms_likely) == 3 and len(ms_boundary) == 5 and len(overlay) == 2


def test_the_selection_carries_provenance_the_prompt_never_renders(
        cohort_rows, source_selection):
    built = _built(cohort_rows, source_selection)
    for r in built["rows"]:
        assert r["admission_origin"] in ("model_screen", "human_review")
        assert r["screen_status"] in ("LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN")
        assert isinstance(r["admission_provenance"], dict)
    # and the renderer has no way to reach any of it
    import inspect
    assert list(inspect.signature(pilot.render_pilot_prompt).parameters) == \
        ["template", "packet"]


def test_the_selection_states_what_ten_rows_cannot_support(cohort_rows, source_selection):
    text = " ".join(_built(cohort_rows, source_selection)["limitations"])
    assert "cannot estimate a rate" in text
    assert "not promotable" in text
    assert "derives no tier" in text
    assert "not an independent sample" in text


def test_the_stratum_vocabulary_has_no_unreachable_value(cohort_rows, source_selection):
    items = SELECTION.schema["properties"]["rows"]["items"]
    declared = set(items["properties"]["pilot_stratum"]["enum"])
    used = {r["pilot_stratum"] for r in _built(cohort_rows, source_selection)["rows"]}
    assert declared == used, declared ^ used


def test_the_selection_refuses_a_cik_outside_the_source_selection(source_selection):
    sel, digest, rel = source_selection
    with pytest.raises(ValueError, match="is not in the candidate cohort"):
        pilot.build_pilot_selection(
            cohort_rows=[], source_selection=sel, source_selection_path=rel,
            source_selection_sha256=digest, cohort_manifest_sha256="1" * 64,
            packet_manifest_sha256="2" * 64, selection_id="x",
            run_timestamp="2026-01-01T00:00:00+00:00")


def test_every_row_is_named_by_cik_and_accession(cohort_rows, source_selection):
    """A CIK alone would merge two filings by the same issuer."""
    from dynamic_ai_products.classifier_pilot_v1 import PILOT_ROWS
    assert all(len(t) == 3 for t in PILOT_ROWS)
    built = _built(cohort_rows, source_selection)
    named = {(cik, acc) for cik, acc, _ in PILOT_ROWS}
    assert {(r["cik"], r["accession"]) for r in built["rows"]} == named
    assert len(named) == 10


def test_the_limitations_describe_a_stress_set_and_claim_no_comparison(
        cohort_rows, source_selection):
    """The pilot must not imply a comparison it is not making."""
    built = _built(cohort_rows, source_selection)
    text = " ".join(built["limitations"])
    assert "mixed stress set" in text
    assert "obvious software" in text and "clear negative control" in text
    assert "not a comparison against any earlier classifier" in text
    for claim in ("paired", "V2.8", "V2.9", "v2_8", "v2_9"):
        assert claim not in text, claim


def test_no_comparison_field_survives_anywhere_in_the_pilot(
        cohort_rows, source_selection):
    """Removed from the artifact, the contracts, and the module alike."""
    built = _built(cohort_rows, source_selection)
    for row in built["rows"]:
        assert "paired_with_v2_8" not in row and "paired_with_v2_9" not in row
    blob = json.dumps(built) + json.dumps(SELECTION.schema)
    blob += (REPO / "src/dynamic_ai_products/classifier_pilot_v1.py").read_text()
    for gone in ("paired_with_v2_8", "paired_with_v2_9",
                 "PILOT_ROWS_WITH_V2_9_OUTPUT"):
        assert gone not in blob, gone
    import dynamic_ai_products.classifier_pilot_v1 as mod
    assert not hasattr(mod, "PILOT_ROWS_WITH_V2_9_OUTPUT")


def test_the_stored_contract_mirrors_the_empty_evidence_rule():
    """A stored row must not assert a conclusion it cites nothing for."""
    stored = next(b for b in RECORD.schema["properties"]["axes"]["oneOf"]
                  if b.get("type") == "object")
    assert stored.get("allOf"), "the stored axes object must carry the conditional"
    base = {"record_contract": "universe_classifier_pilot_record@0.1.0",
            "record_kind": "classified", "cik": "0000000001",
            "accession": "0000000001-22-000001", "company_id": "c",
            "source_id": "s", "packet_sha256": "a" * 64, "prompt_sha256": "b" * 64,
            "model_route": {}, "admission_provenance": {},
            "review_reason_code": None, "review_detail": None}
    all_unknown = {"customer_facing_functional_product": "UNKNOWN",
                   "software_centrality": "UNKNOWN", "firm_structure": "UNKNOWN",
                   "commercial_materiality": "UNKNOWN", "confidence": "low",
                   "evidence": []}
    assert not list(RECORD.iter_errors({**base, "axes": all_unknown}))
    for axis, value in (("customer_facing_functional_product", "YES"),
                        ("software_centrality", "CORE"),
                        ("firm_structure", "PURE_PLAY"),
                        ("commercial_materiality", "DOMINANT")):
        bad = {**all_unknown, axis: value}
        assert list(RECORD.iter_errors({**base, "axes": bad})), f"{axis}={value}"


# --- end-to-end fixture pilot ---------------------------------------------------------


def test_a_fixture_pilot_runs_all_ten_shapes_without_a_run_failure():
    """Ten synthetic rows, three of them broken. The run yields ten records."""
    packet = _packet()
    responses = [json.dumps(_axes()) for _ in range(7)]
    responses.append(json.dumps(_axes(evidence=[{"axis": "firm_structure",
                                                 "passage_ref": "P077"}])))
    responses.append("{broken")
    responses.append(json.dumps(_axes(tier="TIER_A")))
    records = []
    for i, raw in enumerate(responses):
        records.append(pilot.build_pilot_record(
            row={"cik": f"{i:010d}", "accession": f"{i:010d}-22-000001",
                 "company_id": f"CIK{i:010d}", "source_id": "src-1",
                 "admission_provenance": {"release_origin": "model_screen"}},
            packet=packet, prompt_sha256="b" * 64,
            model_route={"provider": "p", "model_label": "m"},
            raw=raw, validator=AXES))
    assert len(records) == 10
    for r in records:
        RECORD.validate(r)
    kinds = [r["record_kind"] for r in records]
    assert kinds.count("classified") == 7
    assert kinds.count("review_uncertain") == 3
    reasons = {r["review_reason_code"] for r in records if r["review_reason_code"]}
    assert reasons == {"evidence_reference_unresolvable", "invalid_model_json",
                       "model_emitted_forbidden_field"}
    assert all("tier" not in r for r in records)
    assert all(r["axes"] is not None for r in records if r["record_kind"] == "classified")
    assert all(r["axes"] is None for r in records if r["record_kind"] == "review_uncertain")
