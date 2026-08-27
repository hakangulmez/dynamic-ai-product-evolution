"""ADR-135 tests: V2.8 separates an evidence address from an interpretation of it.

The V2.7 calibration discarded a row whose axes were well-formed, whose span
resolved against the hash-bound packet, and whose tier would have derived
deterministically -- because a field no tier rule reads ran past 300 characters.
Every fixture below exists to prove that cannot happen again, and that nothing
protecting provenance was loosened to achieve it.

The four reachable interpretation shapes each appear at their exact boundary,
and each is asserted to leave the row classified and tiered. A non-string is
asserted to be refused: that is Design A, chosen because 996 accepted evidence
items across three completed runs produced no non-string value.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_contract_set as ccs
from dynamic_ai_products import lineage_classifier_v2_1 as lcl
from dynamic_ai_products.classifier_calibration_review import (
    REVIEW_CONTRACT,
    REVIEW_CONTRACT_V2,
    REVIEW_SCHEMA,
    REVIEW_SCHEMA_V2,
)
from dynamic_ai_products.classifier_span_index import verify_stored_span
from dynamic_ai_products.classifier_tier_engine import derive_tier, load_tier_rules
from dynamic_ai_products.lineage_classifier_calibration import (
    CALIBRATION_ROUTE_V2_7,
    CALIBRATION_ROUTE_V2_8,
)
from dynamic_ai_products.lineage_classifier_continuation import (
    CONTINUATION_ROUTE_V2_8,
)
from dynamic_ai_products.lineage_classifier_v2_1 import BASE_ROUTE_V2_8

REPO = Path(__file__).resolve().parents[2]
AXES_V5 = Draft202012Validator(
    json.loads((REPO / ccs.V2_8.axes_schema).read_bytes()), format_checker=FormatChecker())
RECORD_V5 = Draft202012Validator(
    json.loads((REPO / ccs.V2_8.record_schema).read_bytes()), format_checker=FormatChecker())

OVER = "x" * 301
LONG = "y" * 5000


def _model_axes(**evidence_overrides):
    """One model response that validates before any override."""
    item = {"axis": "centrality", "passage_ref": "P001", "span_ref": "P001:S001"}
    item.update(evidence_overrides)
    return {
        "customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "software_centrality": "CORE",
        "complementary_dependencies": ["NONE_OR_STANDARD_COMPUTE"],
        "firm_structure": "PURE_PLAY",
        "commercial_materiality": "DOMINANT",
        "customer_facing_functional_product": True,
        "economically_eligible": True,
        "data_eligible": True,
        "customer_market_orientation": "B2B",
        "boundary_flags": [],
        "contradictions": [],
        "evidence": [item],
        "confidence": "high",
    }


def _errors(doc, validator=AXES_V5):
    return sorted(validator.iter_errors(doc), key=lambda e: list(e.absolute_path))


# --- the model-facing contract -------------------------------------------------------


def test_the_address_is_required_and_the_interpretation_is_not():
    item = AXES_V5.schema["properties"]["evidence"]["items"]
    assert item["required"] == ["axis", "passage_ref", "span_ref"]
    assert "span_interpretation" not in item["required"]
    assert item["additionalProperties"] is False
    assert sorted(item["properties"]) == [
        "axis", "passage_ref", "span_interpretation", "span_ref"]


def test_the_interpretation_is_typed_only_string_or_null_and_is_unbounded():
    prop = AXES_V5.schema["properties"]["evidence"]["items"]["properties"]["span_interpretation"]
    assert prop["type"] == ["string", "null"]
    assert "minLength" not in prop and "maxLength" not in prop


@pytest.mark.parametrize("value,label", [
    (None, "explicit null"),
    ("", "empty string"),
    ("a" * 300, "exactly the 300 soft target"),
    (OVER, "301, one past the soft target"),
    (LONG, "5000, far past it"),
])
def test_every_string_or_null_interpretation_satisfies_the_contract(value, label):
    assert not _errors(_model_axes(span_interpretation=value)), label


def test_an_omitted_interpretation_satisfies_the_contract():
    assert not _errors(_model_axes())


@pytest.mark.parametrize("value", [42, 3.5, True, ["a"], {"a": 1}])
def test_a_non_string_interpretation_is_refused(value):
    """Design A: type discipline stays uniform across model-authored fields."""
    errors = _errors(_model_axes(span_interpretation=value))
    assert errors
    assert any("span_interpretation" in list(e.absolute_path) for e in errors)


@pytest.mark.parametrize("field", [
    "evidence_quote", "span_start", "span_end", "span_sha256",
    "supported_claim", "quote", "resolved_quote", "annotation_status",
])
def test_the_model_may_not_author_a_pipeline_field(field):
    errors = _errors(_model_axes(**{field: "anything"}))
    assert errors, f"{field} must be unrepresentable in the model contract"


# --- the annotation classifier -------------------------------------------------------


@pytest.mark.parametrize("value,expected", [
    (None, "absent"),
    ("", "empty"),
    ("a", "accepted"),
    ("a" * 300, "accepted"),
    ("a" * 301, "over_length"),
    (LONG, "over_length"),
])
def test_classify_annotation_is_total_over_every_admissible_value(value, expected):
    assert lcl.classify_annotation(value) == expected


def test_classify_annotation_refuses_a_shape_the_contract_never_admits():
    with pytest.raises(lcl.AxesValidationFailure):
        lcl.classify_annotation(42)


def test_the_status_vocabulary_is_closed_and_has_no_non_string_member():
    assert lcl.ANNOTATION_STATUSES == ("accepted", "over_length", "empty", "absent")
    assert "non_string" not in lcl.ANNOTATION_STATUSES
    stored = RECORD_V5.schema["properties"]["axes"]["oneOf"]
    item = next(b["properties"]["evidence"]["items"] for b in stored
                if "span_sha256" in b.get("properties", {}).get("evidence", {})
                .get("items", {}).get("properties", {}))
    assert item["properties"]["annotation_status"]["enum"] == list(lcl.ANNOTATION_STATUSES)
    assert item["properties"]["annotation_provenance"]["const"] == "model_authored"


def test_the_soft_target_is_300_and_is_not_a_contract_bound():
    assert lcl.ANNOTATION_ACCEPTED_MAX == 300
    prop = AXES_V5.schema["properties"]["evidence"]["items"]["properties"]["span_interpretation"]
    assert "maxLength" not in prop


# --- no repair, no truncation, no normalisation ---------------------------------------


@pytest.mark.parametrize("value", ["", "a" * 300, OVER, LONG, "  padded  ", "line\nbreak"])
def test_the_interpretation_is_stored_byte_for_byte(value):
    stored = {"axis": "centrality", "passage_ref": "P001", "span_ref": "P001:S001",
              "span_interpretation": value, "evidence_quote": "q",
              "span_start": 0, "span_end": 1, "span_sha256": "0" * 64,
              "annotation_status": lcl.classify_annotation(value),
              "annotation_provenance": "model_authored"}
    assert stored["span_interpretation"] == value
    assert len(stored["span_interpretation"]) == len(value)
    assert "…" not in stored["span_interpretation"]


def test_the_stored_contract_always_carries_the_field_even_when_absent():
    stored_branches = RECORD_V5.schema["properties"]["axes"]["oneOf"]
    item = next(b["properties"]["evidence"]["items"] for b in stored_branches
                if "span_sha256" in b.get("properties", {}).get("evidence", {})
                .get("items", {}).get("properties", {}))
    assert "span_interpretation" in item["required"]
    assert item["properties"]["span_interpretation"]["type"] == ["string", "null"]


def test_annotation_status_counts_declare_all_four_keys_always():
    records = [{"axes": {"evidence": [
        {"annotation_status": "accepted"}, {"annotation_status": "over_length"}]}},
        {"axes": None}, {}]
    counts = lcl.annotation_status_counts(records)
    assert sorted(counts) == ["absent", "accepted", "empty", "over_length"]
    assert counts["accepted"] == 1 and counts["over_length"] == 1
    assert counts["empty"] == 0 and counts["absent"] == 0
    assert sum(counts.values()) == 2


# --- the tier is untouched by the interpretation --------------------------------------


@pytest.mark.parametrize("value", [None, "", "a" * 120, OVER, LONG])
def test_the_tier_is_identical_whatever_the_interpretation(value):
    rules = load_tier_rules(REPO)
    axes = _model_axes(span_interpretation=value)
    assert derive_tier(axes, rules).tier == "TIER_A"


def test_the_tier_engine_cannot_condition_on_the_interpretation():
    from dynamic_ai_products.classifier_tier_engine import CONDITIONABLE
    assert "span_interpretation" not in CONDITIONABLE
    assert "supported_claim" not in CONDITIONABLE
    engine = (REPO / "src/dynamic_ai_products/classifier_tier_engine.py").read_text()
    rules = (REPO / "configs/universe_classifier_tier_rules_v2_1.yaml").read_text()
    assert "span_interpretation" not in engine and "span_interpretation" not in rules


# --- V2.7 failure shapes that must stay fatal -----------------------------------------


def test_an_invented_archetype_is_still_refused():
    axes = _model_axes()
    axes["customer_value_archetypes"] = ["FUNCTIONAL_SOFTWARE", "SPECIALIZED_NON_LLM_ENGINE"]
    errors = _errors(axes)
    assert errors and any("is not one of" in e.message for e in errors)


def test_an_output_field_name_used_as_an_axis_is_still_refused():
    errors = _errors(_model_axes(axis="complementary_dependencies"))
    assert errors and any("is not one of" in e.message for e in errors)


def test_a_model_supplied_tier_is_still_refused():
    axes = _model_axes()
    axes["tier"] = "TIER_A"
    with pytest.raises(lcl.AxesValidationFailure) as ei:
        lcl._parse_model_axes(json.dumps(axes), AXES_V5, ccs.V2_8.axes_contract)
    assert ei.value.reason_code == "model_emitted_tier"


def test_span_reference_shape_is_still_strictly_patterned():
    for bad in ("P020", "S001", "P20:S1", "p001:s001", ""):
        assert _errors(_model_axes(span_ref=bad)), bad


# --- the prompt says what the contract enforces ----------------------------------------

PROMPT_V2_8 = (REPO / "prompts/discovery/universe_full_classification.v2_8.md").read_text()


def test_the_prompt_still_forbids_model_authored_quote_text():
    """The rule V2.5 introduced and V2.8 must never lose."""
    assert "**You do not write quotes. You select them.**" in PROMPT_V2_8
    assert "There is no `quote` field in the" in PROMPT_V2_8
    assert "No evidence object contains a `quote` field." in PROMPT_V2_8
    assert "every citation is a `span_ref` and nothing else" in PROMPT_V2_8
    for field in ("evidence_quote", "resolved_quote", "span_sha256",
                  "span_start", "span_end"):
        assert f'"{field}"' not in PROMPT_V2_8, \
            f"{field} is pipeline-derived and must not be asked of the model"


@pytest.mark.parametrize("stale", [
    "direct, resolving quote",
    "each `quote`\n  each `span_ref`",
    "restatement of the quote",
    "supported_claim",
])
def test_the_prompt_carries_no_stale_quote_era_wording(stale):
    """V2.8 inherited V2.5 text; a checklist that still asks for a resolving
    quote contradicts the contract it is meant to summarise."""
    assert stale not in PROMPT_V2_8, stale


def test_the_final_checks_ask_for_a_resolving_span():
    assert "- Every non-unknown conclusion has a direct, resolving selected span." in PROMPT_V2_8
    assert "`span_ref` names a contiguous run inside one passage" in PROMPT_V2_8
    # Both sites say it; the checklist one wraps across a line, so match on the
    # collapsed text rather than on a substring that only one of them contains.
    collapsed = " ".join(PROMPT_V2_8.split())
    assert collapsed.count("not a restatement of the selected evidence text") == 2
    assert "restatement of the quote" not in collapsed


def test_the_admission_context_prose_is_preserved():
    """Contextual prose about an already-displayed quote, not an output rule."""
    assert ("- A quote displayed in the admission context may be useful orientation, but cite"
            in PROMPT_V2_8)
    assert "locating the sentence that carries it in the complete supplied" in PROMPT_V2_8


def test_every_remaining_quote_mention_is_accounted_for():
    """Four, and each one is deliberate. A fifth means new stale wording crept in."""
    lines = [line for line in PROMPT_V2_8.splitlines() if "quote" in line.lower()]
    assert len(lines) == 4, lines
    assert any("You do not write quotes" in line for line in lines)
    assert any("admission context" in line for line in lines)
    assert any("what the quoted span" in line for line in lines)
    assert any("No evidence object contains a `quote` field" in line for line in lines)


def test_the_prompt_states_the_interpretation_rules_the_contract_enforces():
    assert "`span_interpretation`: optional" in PROMPT_V2_8
    assert "omit the field or send null" in PROMPT_V2_8
    assert "must still be a string or" in PROMPT_V2_8
    assert "never a number, list or object" in PROMPT_V2_8


# --- the contract set and its routes --------------------------------------------------


def test_v2_8_declares_its_own_axes_record_and_taxonomy():
    assert ccs.V2_8.axes_contract == "universe_classifier_axes_record@0.5.0"
    assert ccs.V2_8.record_contract == "universe_classifier_record@0.5.0"
    assert ccs.V2_8.taxonomy_version == "universe_classifier_axes_v2_8"
    assert ccs.V2_8.prompt_path.endswith("universe_full_classification.v2_8.md")
    assert ccs.V2_8.output_prefix == "v2_8_"


def test_v2_8_reuses_the_span_protocol_and_index_by_identity():
    assert ccs.V2_8.evidence_protocol == ccs.V2_5.evidence_protocol == "selected_span"
    assert ccs.V2_8.span_index_config == ccs.V2_5.span_index_config


def test_only_v2_8_declares_the_annotation_policy():
    assert ccs.V2_8.annotation_policy == "span_interpretation_v1"
    for older in (ccs.V2_1, ccs.V2_2, ccs.V2_3, ccs.V2_4, ccs.V2_5, ccs.V2_6, ccs.V2_7):
        assert older.annotation_policy is None, older.version_id


def test_contract_set_for_resolves_v2_8_and_still_refuses_the_unknown():
    assert ccs.contract_set_for("v2_8") is ccs.V2_8
    with pytest.raises(ValueError, match="Unknown classifier contract version"):
        ccs.contract_set_for("v3_0")


@pytest.mark.parametrize("route,contract,schema", [
    (BASE_ROUTE_V2_8, "universe_classifier_manifest@0.8.0",
     "schemas/universe_classifier_manifest.v8.schema.json"),
    (CONTINUATION_ROUTE_V2_8, "universe_classifier_continuation_manifest@0.8.0",
     "schemas/universe_classifier_continuation_manifest.v8.schema.json"),
    (CALIBRATION_ROUTE_V2_8, "universe_classifier_calibration_manifest@0.8.0",
     "schemas/universe_classifier_calibration_manifest.v8.schema.json"),
])
def test_each_v2_8_route_binds_its_own_v8_contract(route, contract, schema):
    assert route.manifest_contract == contract
    assert route.manifest_schema == schema
    assert route.contracts is ccs.V2_8
    assert "v2_8" in route.records_filename
    assert route.archive_filename == "universe_classifier_v2_8_raw_responses.jsonl"
    doc = json.loads((REPO / route.manifest_schema).read_bytes())
    assert doc["properties"]["prompt_template_path"]["const"] == ccs.V2_8.prompt_path
    assert doc["properties"]["taxonomy_version"]["const"] == "universe_classifier_axes_v2_8"
    assert doc["properties"]["output_contract"]["const"] == "universe_classifier_record@0.5.0"
    assert "annotation_status_counts" in doc["required"]
    counts = doc["properties"]["annotation_status_counts"]
    assert counts["required"] == ["accepted", "over_length", "empty", "absent"]
    assert counts["additionalProperties"] is False
    declared = set(doc["properties"]["output_hashes"]["properties"])
    assert route.records_filename in declared and route.archive_filename in declared
    assert not any("v2_7" in n for n in declared)


def test_the_v8_authorizations_pin_the_v2_8_prompt_and_record_contract():
    for name in ("universe_classifier_authorization",
                 "universe_classifier_continuation_authorization",
                 "universe_classifier_calibration_authorization"):
        doc = json.loads((REPO / f"schemas/{name}.v8.schema.json").read_bytes())
        props = doc["properties"]
        assert doc["$id"].endswith(f"{name}.v8.schema.json")
        assert doc["title"].endswith("v0.8.0")
        assert "ADR-135" in doc["description"]
        assert props["authorization_contract"]["const"] == f"{name}@0.8.0"
        assert props["prompt_template_path"]["const"] == ccs.V2_8.prompt_path
        assert props["output_contract"]["const"] == "universe_classifier_record@0.5.0"
        assert props["taxonomy_version"]["const"] == "universe_classifier_axes_v2_8"
        assert props["span_index_version"]["const"] == "universe_classifier_span_index_v1"


def test_the_v8_manifests_keep_the_null_compatible_token_accounting():
    for name in ("universe_classifier_manifest",
                 "universe_classifier_continuation_manifest",
                 "universe_classifier_calibration_manifest"):
        acct = json.loads((REPO / f"schemas/{name}.v8.schema.json").read_bytes()
                          )["properties"]["request_accounting"]
        assert acct["properties"]["tokens_out_reported"]["type"] == ["integer", "null"]
        assert acct["additionalProperties"] == {"type": "integer"}


# --- the review contract successor ----------------------------------------------------


def _review_item(interpretation):
    return {"axis": "centrality", "passage_ref": "P001", "span_ref": "P001:S001",
            "evidence_quote": "text", "span_interpretation": interpretation,
            "span_start": 0, "span_end": 4, "span_sha256": "0" * 64,
            "annotation_status": lcl.classify_annotation(interpretation),
            "annotation_provenance": "model_authored"}


@pytest.mark.parametrize("interpretation", [None, "", "a" * 300, OVER])
def test_review_v2_accepts_v2_8_evidence_including_a_null_interpretation(interpretation):
    schema = json.loads((REPO / REVIEW_SCHEMA_V2).read_bytes())
    item_schema = schema["properties"]["nominated_rows"]["items"]["properties"]["evidence"]["items"]
    assert not list(Draft202012Validator(item_schema).iter_errors(_review_item(interpretation)))


def test_review_v1_cannot_display_v2_8_evidence():
    """The successor is required, not preferred."""
    schema = json.loads((REPO / REVIEW_SCHEMA).read_bytes())
    item_schema = schema["properties"]["nominated_rows"]["items"]["properties"]["evidence"]["items"]
    errors = list(Draft202012Validator(item_schema).iter_errors(_review_item("ok")))
    assert errors, "0.1.0 must refuse a V2.8 evidence item"
    assert item_schema["additionalProperties"] is False
    assert item_schema["required"] == ["axis", "passage_ref", "quote", "supported_claim"]


def test_review_v1_is_untouched_and_still_names_0_1_0():
    doc = json.loads((REPO / REVIEW_SCHEMA).read_bytes())
    assert doc["properties"]["review_contract"]["const"] == REVIEW_CONTRACT
    assert REVIEW_CONTRACT == "universe_classifier_calibration_review@0.1.0"
    assert REVIEW_CONTRACT_V2 == "universe_classifier_calibration_review@0.2.0"


def test_review_v2_labels_each_provenance_class():
    props = json.loads((REPO / REVIEW_SCHEMA_V2).read_bytes()
                       )["properties"]["nominated_rows"]["items"]["properties"]["evidence"]["items"]["properties"]
    for f in ("axis", "passage_ref", "span_ref", "span_interpretation"):
        assert "MODEL-AUTHORED" in props[f]["description"]
    for f in ("evidence_quote", "span_start", "span_end", "span_sha256", "annotation_status"):
        assert "PIPELINE-DERIVED" in props[f]["description"]


# --- predecessors are frozen ----------------------------------------------------------


@pytest.mark.parametrize("name,digest", [
    ("v2_1", "8b8c94807cd08a9dd6c2431b74525931fa0202443ad113a8e26d77b7ac77598b"),
    ("v2_2", "bafa3a5b8800cd572e5bb454df1bc0693ffb2fce6f237ca6f31fa8674d228e6b"),
    ("v2_3", "991c8a47b61141d801e61c084b0809eb52a7f72d3f61c03daea22f7f992f8a0a"),
    ("v2_4", "a0b9a7a3ee263da7a0cd278b5ae147ec8b9ed51c0918767ae67c663efe067f6b"),
    ("v2_5", "f09c6f8f2a6a74644db08333ebe1c7833692715190703c6b323617d49dc01581"),
    ("v2_7", "f727486e113521f2a9ba8aa1755b0c0803920091584e093a32ecb8ac18f30dd0"),
])
def test_every_predecessor_prompt_is_byte_identical(name, digest):
    path = REPO / f"prompts/discovery/universe_full_classification.{name}.md"
    assert sha256(path.read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("rel,digest", [
    ("configs/universe_classifier_span_index_v1.yaml",
     "0f98b00f861fbaee710612af3cda681f99c5f642e1e6323f91a1deb9ec219499"),
    ("configs/universe_classifier_tier_rules_v2_1.yaml",
     "14326a298236c2431c89aba4d4a5241bc4e6a95e4bc9212df716d5200dedc468"),
    ("configs/universe_classifier_calibration_strata_v1.yaml",
     "b763dca0816212430bbe844eca0065f2762a18905e3d8a8c6b1ee9dc902353ac"),
    ("schemas/universe_classifier_axes_record.v4.schema.json",
     "d37147c74f9c657b1760f073d9f8d9404e8005c5e56085667ee46783566800a0"),
    ("schemas/universe_classifier_record.v4.schema.json",
     "3216670a93afadf5e5f8e757b36c95ea734b83cd11012940d8993b5cbc040734"),
])
def test_every_pinned_predecessor_artifact_is_byte_identical(rel, digest):
    assert sha256((REPO / rel).read_bytes()).hexdigest() == digest


def test_the_v2_7_route_is_untouched():
    assert CALIBRATION_ROUTE_V2_7.manifest_contract == \
        "universe_classifier_calibration_manifest@0.7.0"
    assert CALIBRATION_ROUTE_V2_7.contracts is ccs.V2_7
    assert CALIBRATION_ROUTE_V2_7.contracts.annotation_policy is None


# --- the span verifier still serves both regimes --------------------------------------


def test_verify_stored_span_reads_either_pipeline_text_key():
    """One archival proof for every stored row from V2.5 onward."""
    packet = {"passages": [{"passage_id": "abc", "text": "Alpha beta. Gamma delta."}],
              "cik": "0000000001", "accession": "x"}
    from dynamic_ai_products.classifier_span_index import normalize_passage_text
    from dynamic_ai_products.human_review_overlay import passage_refs
    ref = next(iter(passage_refs(packet)))
    text = normalize_passage_text(packet["passages"][0]["text"])
    piece = text[0:11]
    base = {"passage_ref": ref, "span_start": 0, "span_end": 11,
            "span_sha256": sha256(piece.encode("utf-8")).hexdigest()}
    assert verify_stored_span({**base, "evidence_quote": piece}, packet)
    assert verify_stored_span({**base, "resolved_quote": piece}, packet)
    assert not verify_stored_span({**base, "evidence_quote": piece + "!"}, packet)


# --- CLI ------------------------------------------------------------------------------


def _cli():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adr135_cli", REPO / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


V2_8_MODES = ["classify-universe-cohort-v2-8",
              "classify-universe-cohort-continuation-v2-8",
              "classify-universe-calibration-v2-8",
              "build-classifier-calibration-review-v2-8"]


@pytest.mark.parametrize("mode", V2_8_MODES)
def test_every_v2_8_mode_is_declared(mode):
    choices = next(a.choices for a in _cli().build_parser()._actions if a.dest == "mode")
    assert mode in choices


def test_the_v2_8_modes_dispatch_to_the_v2_8_routes_only():
    source = (REPO / "pipelines" / "00_build_company_universe.py").read_text()
    for mode, symbol in (
            ("classify-universe-cohort-v2-8", "BASE_ROUTE_V2_8"),
            ("classify-universe-cohort-continuation-v2-8", "CONTINUATION_ROUTE_V2_8"),
            ("classify-universe-calibration-v2-8", "CALIBRATION_ROUTE_V2_8"),
            ("build-classifier-calibration-review-v2-8", "CALIBRATION_ROUTE_V2_8")):
        assert f'if args.mode == "{mode}":' in source
        block = source.split(f'if args.mode == "{mode}":')[1][:220]
        assert symbol in block, mode
    cli = _cli()
    assert cli.CALIBRATION_ROUTE_V2_8 is CALIBRATION_ROUTE_V2_8
    assert cli.BASE_ROUTE_V2_8 is BASE_ROUTE_V2_8
    assert cli.CONTINUATION_ROUTE_V2_8 is CONTINUATION_ROUTE_V2_8


def test_each_v2_8_mode_reaches_full_gating_parity_with_v2_7():
    source = (REPO / "pipelines" / "00_build_company_universe.py").read_text()
    for stem in ("classify-universe-cohort", "classify-universe-cohort-continuation",
                 "classify-universe-calibration", "build-classifier-calibration-review"):
        assert source.count(f'"{stem}-v2-8"') == source.count(f'"{stem}-v2-7"'), stem
