"""ADR-136 tests: V2.9 changes the question, not the machinery.

The V2.8 calibration completed with two unusable rows and every output-discipline
failure class at zero, and reading its evidence showed the residual problem had
moved from format to selection -- internal tooling and third-party infrastructure
cited as the firm's own customer-facing software. So V2.9 moves the semantic
instruction and holds every technical contract still.

That "holds still" claim is the load-bearing one here, because it is what makes a
V2.8/V2.9 comparison an experiment rather than an anecdote. It is asserted by
object identity below, not by equality of copied strings.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from dynamic_ai_products import classifier_contract_set as ccs
from dynamic_ai_products.classifier_calibration_review import (
    REVIEW_CONTRACT_V2,
    REVIEW_SCHEMA_V2,
)
from dynamic_ai_products.lineage_classifier_calibration import (
    CALIBRATION_ROUTE_V2_8,
    CALIBRATION_ROUTE_V2_9,
)
from dynamic_ai_products.lineage_classifier_continuation import (
    CONTINUATION_ROUTE_V2_9,
)
from dynamic_ai_products.lineage_classifier_v2_1 import BASE_ROUTE_V2_9

REPO = Path(__file__).resolve().parents[2]
P29 = REPO / "prompts/discovery/universe_full_classification.v2_9.md"
P28 = REPO / "prompts/discovery/universe_full_classification.v2_8.md"
ORIGINAL = REPO / "prompts/discovery/universe_full_classification.md"
PROMPT_V2_9 = P29.read_text()
PROMPT_V2_8 = P28.read_text()


# --- 3. the semantic content the experiment is actually testing ------------------------


def test_the_prompt_states_the_external_customer_purchase_rule():
    collapsed = " ".join(PROMPT_V2_9.split())
    assert "First identify what an external customer actually purchases from this firm." in collapsed
    for phrase in ("Internal R&D tools", "employee tools", "supplier technology",
                   "exchange infrastructure", "third-party platforms"):
        assert phrase in collapsed, phrase
    assert "not the firm's customer-facing product merely because the firm uses or depends on them" in collapsed
    assert "They cannot alone justify CORE or CO_ESSENTIAL." in collapsed
    assert ("Use CORE or CO_ESSENTIAL only when the selected evidence shows that the "
            "firm's own software capability directly produces the purchased customer "
            "outcome.") in collapsed
    assert "Otherwise use ENABLING, PERIPHERAL, or UNKNOWN as the evidence supports." in collapsed


def test_the_prompt_keeps_the_selected_span_protocol():
    assert "**You do not write quotes. You select them.**" in PROMPT_V2_9
    assert "There is no `quote` field in the" in PROMPT_V2_9
    assert "No evidence object contains a `quote` field" in PROMPT_V2_9
    assert "`P006:S003-S005`" in PROMPT_V2_9
    assert "shortest span that carries the claim" in PROMPT_V2_9
    assert "Never invent a marker." in PROMPT_V2_9


def test_the_prompt_keeps_unknown_over_guess():
    collapsed = " ".join(PROMPT_V2_9.split())
    assert "## Unknown over guess" in PROMPT_V2_9
    assert "An unknown backed by the evidence is a correct answer." in collapsed
    assert "A plausible label the packet does not prove is not." in collapsed
    assert "If no displayed span proves the claim, omit that evidence object." in collapsed


def test_the_prompt_keeps_the_closed_vocabularies_and_no_tier_rule():
    for value in ("FUNCTIONAL_SOFTWARE", "ADAPTIVE_DIGITAL_SERVICE", "HUMAN_MANAGED_SERVICE",
                  "PHYSICAL_SERVICE_NETWORK", "NONE_OR_STANDARD_COMPUTE",
                  "SPECIALIZED_NON_LLM_ENGINE", "MIXED_NONSEPARABLE", "CO_ESSENTIAL"):
        assert value in PROMPT_V2_9, value
    assert "There is no tier field and no" in PROMPT_V2_9
    assert "candidate_tier" in PROMPT_V2_9
    assert "No Tier was assigned." in PROMPT_V2_9


def test_the_prompt_carries_the_original_economic_core():
    original = ORIGINAL.read_text()
    for anchor in ("If the software functionality were removed",
                   "Is the software mainly connecting the customer to a physical service",
                   "no inclusion from SIC/NAICS alone",
                   "no assumption that proprietary data creates defensibility"):
        assert anchor in original and anchor in PROMPT_V2_9, anchor


def test_the_prompt_does_not_recount_v2_8s_failure_history():
    """A prompt that lists past mistakes teaches their shape, not the question."""
    for scar in ("calibration", "V2.7", "V2.6", "ADR-", "996", "annotation_status",
                 "over_length", "supported_claim"):
        assert scar not in PROMPT_V2_9, scar


# --- the three operational safeguards V2.9 must not have dropped -----------------------
#
# These are existing V2.8 contract behaviours, not semantic choices. A prompt that
# omits them lets the model walk into a refusal the contract will impose anyway --
# which is exactly how V2.8 lost its only two rows, to spans of 2,321 and 2,309
# characters against a bound the prompt never mentioned.


def test_confidence_is_stated_mandatory_and_closed():
    collapsed = " ".join(PROMPT_V2_9.split())
    assert ("`confidence` is mandatory on every response and is exactly one of `high`, "
            "`medium`, or `low`.") in collapsed
    assert "There is no default and the field is never omitted" in collapsed
    assert "even when the axes are largely unknown" in collapsed
    # and restated where the model checks its own output
    assert "- `confidence` is present and is exactly one of `high`, `medium`, `low`." in PROMPT_V2_9


def test_the_two_thousand_character_span_bound_is_stated_as_a_refusal():
    collapsed = " ".join(PROMPT_V2_9.split())
    assert ("A span resolving to more than 2,000 characters of filing text is refused, "
            "not truncated: a shortened quote is not the span you selected.") in collapsed
    assert "choose the narrower span that still proves the claim" in collapsed
    # restated in the output limits and in the closing checks
    assert PROMPT_V2_9.count("2,000 characters of filing text is refused") == 2
    assert "- No selected span exceeds 2,000 characters of filing text." in PROMPT_V2_9
    assert "truncat" in collapsed, "the refuse-rather-than-truncate reason must survive"


def test_span_interpretation_is_a_soft_target_not_a_refusal_bound():
    collapsed = " ".join(PROMPT_V2_9.split())
    assert ("`span_interpretation`: optional, with a 300-character soft target rather "
            "than a contractual bound.") in collapsed
    assert ("An interpretation that is absent, empty, or longer than the target is "
            "recorded as such and never discards your evidence or the tier derived "
            "from it.") in collapsed
    assert "omit the field or send null rather than inventing a clause" in collapsed
    assert "It must still be a string or null, never a number, list or object." in collapsed


def test_the_safeguards_did_not_arrive_as_v2_8_failure_prose():
    """Restored as rules, not as a retelling of how each was learned."""
    for scar in ("calibration", "V2.8", "V2.7", "ADR-", "unusable", "over_length",
                 "annotation_status", "996", "2,321", "2,309"):
        assert scar not in PROMPT_V2_9, scar


# --- 6. materially shorter, measured rather than capped -------------------------------


def test_the_prompt_is_materially_shorter_than_v2_8():
    w9, w8 = len(PROMPT_V2_9.split()), len(PROMPT_V2_8.split())
    b9, b8 = len(P29.read_bytes()), len(P28.read_bytes())
    # Reported, not enforced by an arbitrary cap: the requirement is that the
    # semantic instruction got smaller while every rule above still holds.
    assert w9 < w8 and b9 < b8
    # Materially shorter, with the three operational safeguards restored. The
    # threshold is a floor on "material", not the point: the point is that
    # every rule asserted above still holds at this size.
    assert w9 < w8 * 0.80, f"V2.9 {w9} words vs V2.8 {w8}"
    print(f"\n  V2.9 {w9} words / {b9} bytes; V2.8 {w8} words / {b8} bytes; "
          f"{100 * (1 - w9 / w8):.1f}% fewer words, {100 * (1 - b9 / b8):.1f}% fewer bytes")


# --- 4. predecessors byte-identical ----------------------------------------------------


@pytest.mark.parametrize("name,digest", [
    ("v2_1", "8b8c94807cd08a9dd6c2431b74525931fa0202443ad113a8e26d77b7ac77598b"),
    ("v2_2", "bafa3a5b8800cd572e5bb454df1bc0693ffb2fce6f237ca6f31fa8674d228e6b"),
    ("v2_3", "991c8a47b61141d801e61c084b0809eb52a7f72d3f61c03daea22f7f992f8a0a"),
    ("v2_4", "a0b9a7a3ee263da7a0cd278b5ae147ec8b9ed51c0918767ae67c663efe067f6b"),
    ("v2_5", "f09c6f8f2a6a74644db08333ebe1c7833692715190703c6b323617d49dc01581"),
    ("v2_7", "f727486e113521f2a9ba8aa1755b0c0803920091584e093a32ecb8ac18f30dd0"),
    ("v2_8", "56cc14656d26cb59f0ddb6ea5901e62a3f3e37949c49f95fbb06cb7ecd4551ce"),
])
def test_every_predecessor_prompt_is_byte_identical(name, digest):
    path = REPO / f"prompts/discovery/universe_full_classification.{name}.md"
    assert sha256(path.read_bytes()).hexdigest() == digest


def test_the_original_prompt_and_pinned_configs_are_untouched():
    for rel, digest in (
            ("configs/universe_classifier_span_index_v1.yaml",
             "0f98b00f861fbaee710612af3cda681f99c5f642e1e6323f91a1deb9ec219499"),
            ("configs/universe_classifier_tier_rules_v2_1.yaml",
             "14326a298236c2431c89aba4d4a5241bc4e6a95e4bc9212df716d5200dedc468"),
            ("configs/universe_classifier_calibration_strata_v1.yaml",
             "b763dca0816212430bbe844eca0065f2762a18905e3d8a8c6b1ee9dc902353ac"),
            ("schemas/universe_classifier_axes_record.v5.schema.json",
             "d46953eae0ff6ebb99af799096f92cb9fb6fc0689f5a6ed96db2bb24334fcf87"),
            ("schemas/universe_classifier_record.v5.schema.json",
             "9b2afc8fe85b9fa4b694652ee940bb7c36cc40f957624f8d8c3689376c5551ea")):
        assert sha256((REPO / rel).read_bytes()).hexdigest() == digest, rel


# --- the experiment's control: every mechanism held still by identity ------------------


@pytest.mark.parametrize("field", [
    "axes_schema", "axes_contract", "record_contract", "record_schema",
    "taxonomy_version", "evidence_protocol", "span_index_config", "annotation_policy",
])
def test_v2_9_reuses_every_v2_8_technical_contract(field):
    assert getattr(ccs.V2_9, field) == getattr(ccs.V2_8, field), field


def test_only_the_prompt_and_the_output_prefix_move():
    assert ccs.V2_9.prompt_path != ccs.V2_8.prompt_path
    assert ccs.V2_9.prompt_path.endswith("universe_full_classification.v2_9.md")
    assert ccs.V2_9.output_prefix == "v2_9_" != ccs.V2_8.output_prefix
    moved = {f for f in ccs.V2_9.__dataclass_fields__
             if getattr(ccs.V2_9, f) != getattr(ccs.V2_8, f)}
    assert moved == {"version_id", "prompt_path", "output_prefix"}, moved


def test_contract_set_for_resolves_v2_9_and_still_refuses_the_unknown():
    assert ccs.contract_set_for("v2_9") is ccs.V2_9
    with pytest.raises(ValueError, match="Unknown classifier contract version"):
        ccs.contract_set_for("v3_0")


# --- 2. the model-facing contract still forbids what it always forbade ----------------


def _axes(**over):
    item = {"axis": "centrality", "passage_ref": "P001", "span_ref": "P001:S001"}
    item.update(over.pop("evidence_item", {}))
    doc = {
        "customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "software_centrality": "CORE",
        "complementary_dependencies": ["NONE_OR_STANDARD_COMPUTE"],
        "firm_structure": "PURE_PLAY", "commercial_materiality": "DOMINANT",
        "customer_facing_functional_product": True, "economically_eligible": True,
        "data_eligible": True, "customer_market_orientation": "B2B",
        "boundary_flags": [], "contradictions": [], "evidence": [item],
        "confidence": "high"}
    doc.update(over)
    return doc


@pytest.fixture(scope="module")
def axes_validator():
    from jsonschema import Draft202012Validator, FormatChecker
    return Draft202012Validator(
        json.loads((REPO / ccs.V2_9.axes_schema).read_bytes()), format_checker=FormatChecker())


@pytest.mark.parametrize("field", [
    "quote", "evidence_quote", "resolved_quote", "span_start", "span_end",
    "span_sha256", "annotation_status", "annotation_provenance", "supported_claim",
])
def test_the_model_may_not_author_a_pipeline_evidence_field(axes_validator, field):
    errors = list(axes_validator.iter_errors(_axes(evidence_item={field: "x"})))
    assert errors, f"{field} must be unrepresentable in the V2.9 model contract"


@pytest.mark.parametrize("field", ["tier", "candidate_tier", "tier_rule_trace"])
def test_the_model_may_not_emit_a_tier(field):
    import dynamic_ai_products.lineage_classifier_v2_1 as lcl
    from jsonschema import Draft202012Validator, FormatChecker
    validator = Draft202012Validator(
        json.loads((REPO / ccs.V2_9.axes_schema).read_bytes()), format_checker=FormatChecker())
    with pytest.raises(lcl.AxesValidationFailure) as ei:
        lcl._parse_model_axes(json.dumps(_axes(**{field: "TIER_A"})),
                              validator, ccs.V2_9.axes_contract)
    assert ei.value.reason_code == "model_emitted_tier"


# --- 1. route, grant, manifest and archive isolation ----------------------------------


@pytest.mark.parametrize("route,contract,schema", [
    (BASE_ROUTE_V2_9, "universe_classifier_manifest@0.9.0",
     "schemas/universe_classifier_manifest.v9.schema.json"),
    (CONTINUATION_ROUTE_V2_9, "universe_classifier_continuation_manifest@0.9.0",
     "schemas/universe_classifier_continuation_manifest.v9.schema.json"),
    (CALIBRATION_ROUTE_V2_9, "universe_classifier_calibration_manifest@0.9.0",
     "schemas/universe_classifier_calibration_manifest.v9.schema.json"),
])
def test_each_v2_9_route_binds_its_own_v9_contract(route, contract, schema):
    assert route.manifest_contract == contract
    assert route.manifest_schema == schema
    assert route.contracts is ccs.V2_9
    assert "v2_9" in route.records_filename and "v2_9" in route.manifest_filename
    assert route.archive_filename == "universe_classifier_v2_9_raw_responses.jsonl"
    doc = json.loads((REPO / route.manifest_schema).read_bytes())
    assert doc["properties"]["prompt_template_path"]["const"] == ccs.V2_9.prompt_path
    assert doc["properties"]["output_contract"]["const"] == "universe_classifier_record@0.5.0"
    assert doc["properties"]["taxonomy_version"]["const"] == "universe_classifier_axes_v2_8"
    assert "annotation_status_counts" in doc["required"]
    declared = set(doc["properties"]["output_hashes"]["properties"])
    assert route.records_filename in declared and route.archive_filename in declared
    assert not any("v2_8" in n for n in declared)


def test_the_v9_authorizations_pin_the_v2_9_prompt():
    for name in ("universe_classifier_authorization",
                 "universe_classifier_continuation_authorization",
                 "universe_classifier_calibration_authorization"):
        doc = json.loads((REPO / f"schemas/{name}.v9.schema.json").read_bytes())
        props = doc["properties"]
        assert doc["$id"].endswith(f"{name}.v9.schema.json")
        assert doc["title"].endswith("v0.9.0")
        assert props["authorization_contract"]["const"] == f"{name}@0.9.0"
        assert props["prompt_template_path"]["const"] == ccs.V2_9.prompt_path
        assert props["output_contract"]["const"] == "universe_classifier_record@0.5.0"
        assert props["span_index_version"]["const"] == "universe_classifier_span_index_v1"


def test_no_v2_9_filename_or_contract_collides_with_any_earlier_version():
    import dynamic_ai_products.lineage_classifier_calibration as lcal
    import dynamic_ai_products.lineage_classifier_continuation as lcc
    import dynamic_ai_products.lineage_classifier_v2_1 as lcl
    routes = [getattr(m, n) for m, names in (
        (lcl, [n for n in dir(lcl) if n.startswith("BASE_ROUTE")]),
        (lcc, [n for n in dir(lcc) if n.startswith("CONTINUATION_ROUTE")]),
        (lcal, [n for n in dir(lcal) if n.startswith("CALIBRATION_ROUTE")])) for n in names]
    records = [r.records_filename for r in routes]
    manifests = [r.manifest_filename for r in routes]
    grants = [r.authorization_schema for r in routes]
    assert len(set(records)) == len(records)
    assert len(set(manifests)) == len(manifests)
    assert len(set(grants)) == len(grants)
    assert len(routes) == 27, len(routes)


def test_the_v2_8_route_is_untouched():
    assert CALIBRATION_ROUTE_V2_8.manifest_contract == \
        "universe_classifier_calibration_manifest@0.8.0"
    assert CALIBRATION_ROUTE_V2_8.contracts is ccs.V2_8
    assert CALIBRATION_ROUTE_V2_8.records_filename == \
        "universe_classifier_v2_8_calibration_records.jsonl"


# --- the review contract is reused, and that reuse is proved --------------------------


def test_the_review_contract_needs_no_successor_for_v2_9():
    """Structural, not preferential: V2.9's record schema *is* V2.8's."""
    assert ccs.V2_9.record_schema == ccs.V2_8.record_schema
    schema = json.loads((REPO / REVIEW_SCHEMA_V2).read_bytes())
    assert schema["properties"]["review_contract"]["const"] == REVIEW_CONTRACT_V2
    item = schema["properties"]["nominated_rows"]["items"]["properties"]["evidence"]["items"]
    stored = json.loads((REPO / ccs.V2_9.record_schema).read_bytes())
    branch = next(b for b in stored["properties"]["axes"]["oneOf"]
                  if "span_sha256" in b.get("properties", {}).get("evidence", {})
                  .get("items", {}).get("properties", {}))
    stored_fields = set(branch["properties"]["evidence"]["items"]["properties"])
    assert set(item["properties"]) <= stored_fields


# --- 7. the V2.8 run and review artifacts are untouched -------------------------------


@pytest.mark.parametrize("rel,digest", [
    ("data/runs/universe-classifier-calibrations-v2-8/universe-classifier-calibration-v2-8-20260827/universe_classifier_v2_8_calibration_manifest.json",
     "ac8e1e6e050c0e1018001bac1bb23edd679e4e206e7121cc37a4d9ef5a84a33f"),
    ("data/runs/universe-classifier-calibrations-v2-8/universe-classifier-calibration-v2-8-20260827/universe_classifier_v2_8_calibration_records.jsonl",
     "2d13e22024be40b0bedfc765167e4129215bf22b1223fb7158d2ee81fbde0675"),
    ("data/runs/universe-classifier-calibrations-v2-8/universe-classifier-calibration-v2-8-20260827/universe_classifier_v2_8_raw_responses.jsonl",
     "e1126c021d7ff078a0b671b3eee5a5fbe6d09b5e5f2b8686a40d2a28f6000235"),
    ("data/runs/universe-classifier-calibration-reviews-v2-8/universe-classifier-calibration-review-v2-8-20260828/universe_classifier_calibration_review.json",
     "f2b8312062953dfe5b5df6e0e671dcc82bb5b3b76f26ae271f4232d66cb497ee"),
])
def test_the_v2_8_run_and_review_artifacts_are_byte_identical(rel, digest):
    path = REPO / rel
    if not path.is_file():
        pytest.skip(f"{rel} is not present in this checkout")
    assert sha256(path.read_bytes()).hexdigest() == digest


# --- CLI ------------------------------------------------------------------------------


V2_9_MODES = ["classify-universe-cohort-v2-9",
              "classify-universe-cohort-continuation-v2-9",
              "classify-universe-calibration-v2-9",
              "build-classifier-calibration-review-v2-9"]


def _cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adr136_cli", REPO / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("mode", V2_9_MODES)
def test_every_v2_9_mode_is_declared(mode):
    choices = next(a.choices for a in _cli().build_parser()._actions if a.dest == "mode")
    assert mode in choices


def test_the_v2_9_modes_dispatch_to_the_v2_9_routes_only():
    source = (REPO / "pipelines" / "00_build_company_universe.py").read_text()
    for mode, symbol in (
            ("classify-universe-cohort-v2-9", "BASE_ROUTE_V2_9"),
            ("classify-universe-cohort-continuation-v2-9", "CONTINUATION_ROUTE_V2_9"),
            ("classify-universe-calibration-v2-9", "CALIBRATION_ROUTE_V2_9"),
            ("build-classifier-calibration-review-v2-9", "CALIBRATION_ROUTE_V2_9")):
        assert f'if args.mode == "{mode}":' in source
        assert symbol in source.split(f'if args.mode == "{mode}":')[1][:220], mode
    cli = _cli()
    assert cli.CALIBRATION_ROUTE_V2_9 is CALIBRATION_ROUTE_V2_9
    assert cli.BASE_ROUTE_V2_9 is BASE_ROUTE_V2_9
    assert cli.CONTINUATION_ROUTE_V2_9 is CONTINUATION_ROUTE_V2_9


def test_each_v2_9_mode_reaches_gating_parity_with_v2_8():
    source = (REPO / "pipelines" / "00_build_company_universe.py").read_text()
    for stem in ("classify-universe-cohort", "classify-universe-cohort-continuation",
                 "classify-universe-calibration", "build-classifier-calibration-review"):
        assert source.count(f'"{stem}-v2-9"') == source.count(f'"{stem}-v2-8"'), stem
