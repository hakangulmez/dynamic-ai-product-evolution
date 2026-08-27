"""ADR-134 tests: the V2.7 output-discipline successor.

The V2.6 calibration completed and still failed its promotion gate, because all
five of its unusable rows were contract violations the model could have avoided:
four ``boundary_flags`` entries written as explanatory sentences that ran past
160 characters, and one response that omitted ``confidence``. Each of those five
live shapes appears below as an attempted response and is asserted to be
refused, at its exact observed length.

Nothing here relaxes a bound. The rows that did classify in that run wrote flags
of at most 133 characters against a ceiling of 160, so the ceiling was never
what failed; a 160-character flag is asserted to be accepted, immediately beside
the 162-character one that is not. What V2.7 changes is the prompt: it says what
a flag is, and it names ``confidence`` in the two places every other bound is
already named.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_contract_set as ccs
from dynamic_ai_products.lineage_classifier_calibration import (
    CALIBRATION_ROUTE_V2_6,
    CALIBRATION_ROUTE_V2_7,
)
from dynamic_ai_products.lineage_classifier_continuation import (
    CONTINUATION_ROUTE_V2_7,
)
from dynamic_ai_products.lineage_classifier_v2_1 import BASE_ROUTE_V2_7

REPO = Path(__file__).resolve().parents[2]
PROMPT_PATH = REPO / "prompts/discovery/universe_full_classification.v2_7.md"
PROMPT = PROMPT_PATH.read_text()
V2_5_PROMPT = (REPO / "prompts/discovery/universe_full_classification.v2_5.md").read_text()

AXES = Draft202012Validator(
    __import__("json").loads(
        (REPO / "schemas/universe_classifier_axes_record.v4.schema.json").read_bytes()),
    format_checker=FormatChecker())


def _axes(**overrides):
    """A minimal axes response that validates, before any override."""
    axes = {
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
        "evidence": [{"axis": "centrality", "passage_ref": "P001",
                      "span_ref": "P001:S001", "supported_claim": "C" * 100}],
        "confidence": "high",
    }
    axes.update(overrides)
    return axes


def _errors(axes):
    return sorted(AXES.iter_errors(axes), key=lambda e: list(e.absolute_path))


# --- the five live V2.6 failures ------------------------------------------------------

#: The four overlong flags exactly as the 2026-08-27 calibration produced them,
#: kept at their observed lengths so a future bound change cannot pass this
#: suite by accident. The 162 case is the one that matters most: it clears the
#: ceiling by two characters.
LIVE_OVERLONG = [
    pytest.param(175, id="cik-0001563568-embedded-vehicle-software"),
    pytest.param(211, id="cik-0001493212-doctor-patient-portal"),
    pytest.param(162, id="cik-0001763329-rnd-not-commercial-software"),
    pytest.param(169, id="cik-0001754068-internal-algorithms"),
]


@pytest.mark.parametrize("length", LIVE_OVERLONG)
def test_the_four_live_overlong_boundary_flags_are_refused(length):
    errors = _errors(_axes(boundary_flags=["x" * length]))
    assert errors, f"a {length}-character flag must not validate"
    assert any(e.absolute_path and e.absolute_path[0] == "boundary_flags"
               for e in errors)
    assert any("too long" in e.message for e in errors)


def test_the_live_missing_confidence_row_is_refused():
    axes = _axes()
    del axes["confidence"]
    errors = _errors(axes)
    assert errors
    assert any("'confidence' is a required property" in e.message for e in errors)


def test_an_overlong_flag_in_a_later_position_is_still_refused():
    # Two of the live failures were at boundary_flags[2], not [0].
    axes = _axes(boundary_flags=["ok", "ok", "x" * 162])
    errors = _errors(axes)
    assert errors
    assert any(list(e.absolute_path) == ["boundary_flags", 2] for e in errors)


# --- and what stays accepted ----------------------------------------------------------


def test_a_flag_at_exactly_the_ceiling_is_accepted():
    assert not _errors(_axes(boundary_flags=["x" * 160]))


def test_the_bound_is_unchanged_at_160():
    schema = AXES.schema["properties"]["boundary_flags"]
    assert schema["items"]["maxLength"] == 160
    assert schema["maxItems"] == 4


@pytest.mark.parametrize("value", ["high", "medium", "low"])
def test_every_confidence_value_is_accepted(value):
    assert not _errors(_axes(confidence=value))


def test_confidence_remains_a_closed_enum():
    assert AXES.schema["properties"]["confidence"]["enum"] == ["high", "medium", "low"]
    assert _errors(_axes(confidence="very high"))


# --- the prompt carries both discipline clauses ---------------------------------------


def test_the_v2_7_prompt_states_the_boundary_flag_genre_rule():
    assert "short label naming the boundary condition, never an explanation" in PROMPT
    assert "it has become\n  reasoning" in PROMPT
    # stated in the closing checklist too, not only in the limits block
    assert "is a short label of the boundary condition, not\n  an explanatory sentence" in PROMPT


def test_the_v2_7_prompt_makes_confidence_mandatory_in_both_places():
    assert "`confidence`: mandatory." in PROMPT
    assert "There is no default\n  and the field is never omitted." in PROMPT
    assert "`confidence` is present and is exactly one of `high`, `medium`, `low`." in PROMPT
    limits = PROMPT.index("## Output size limits")
    checklist = PROMPT.index("- Every output bound holds:")
    assert PROMPT.index("`confidence`: mandatory.") > limits
    assert PROMPT.rindex("`confidence` is present") > checklist


def test_the_v2_7_prompt_relaxes_nothing():
    assert "each at most 160 characters" in PROMPT
    assert "at most 4, each at most 160" in PROMPT
    for bound in ("at most 300 characters", "at most 12 objects",
                  "2000 characters", "at most 200 characters"):
        assert bound in PROMPT
        assert PROMPT.count(bound) == V2_5_PROMPT.count(bound)


def test_v2_7_differs_from_v2_5_only_by_the_two_discipline_edits():
    import difflib
    delta = list(difflib.ndiff(V2_5_PROMPT.splitlines(), PROMPT.splitlines()))
    added = [line[2:] for line in delta if line.startswith("+ ")]
    removed = [line[2:] for line in delta if line.startswith("- ")]
    assert removed == ["- `boundary_flags`: at most 4 entries, each at most 160 characters."]
    joined = "\n".join(added)
    assert "boundary" in joined and "confidence" in joined
    for forbidden in ("span_ref", "quote", "taxonomy", "Tier"):
        assert forbidden not in joined, f"V2.7 must not touch {forbidden}"


# --- predecessor prompts are untouched ------------------------------------------------


@pytest.mark.parametrize("name,digest", [
    ("v2_1", "8b8c94807cd08a9dd6c2431b74525931fa0202443ad113a8e26d77b7ac77598b"),
    ("v2_2", "bafa3a5b8800cd572e5bb454df1bc0693ffb2fce6f237ca6f31fa8674d228e6b"),
    ("v2_3", "991c8a47b61141d801e61c084b0809eb52a7f72d3f61c03daea22f7f992f8a0a"),
    ("v2_4", "a0b9a7a3ee263da7a0cd278b5ae147ec8b9ed51c0918767ae67c663efe067f6b"),
    ("v2_5", "f09c6f8f2a6a74644db08333ebe1c7833692715190703c6b323617d49dc01581"),
])
def test_every_predecessor_prompt_is_byte_identical(name, digest):
    path = REPO / f"prompts/discovery/universe_full_classification.{name}.md"
    assert sha256(path.read_bytes()).hexdigest() == digest


def test_v2_6_has_no_prompt_of_its_own_and_still_points_at_v2_5():
    assert not (REPO / "prompts/discovery/universe_full_classification.v2_6.md").exists()
    assert ccs.V2_6.prompt_path == ccs.V2_5.prompt_path


# --- the contract set is a successor, not a widening ----------------------------------


def test_v2_7_reuses_every_span_contract_by_identity():
    for field in ("axes_schema", "axes_contract", "record_contract", "record_schema",
                  "taxonomy_version", "evidence_protocol", "span_index_config"):
        assert getattr(ccs.V2_7, field) == getattr(ccs.V2_5, field), field
    assert ccs.V2_7.evidence_protocol == "selected_span"
    assert ccs.V2_7.taxonomy_version == "universe_classifier_axes_v2_5"


def test_only_the_prompt_and_the_output_prefix_move():
    assert ccs.V2_7.prompt_path != ccs.V2_5.prompt_path
    assert ccs.V2_7.prompt_path.endswith("universe_full_classification.v2_7.md")
    assert ccs.V2_7.output_prefix == "v2_7_" != ccs.V2_6.output_prefix


def test_contract_set_for_resolves_v2_7_and_still_refuses_the_unknown():
    assert ccs.contract_set_for("v2_7") is ccs.V2_7
    with pytest.raises(ValueError, match="Unknown classifier contract version"):
        ccs.contract_set_for("v3_0")


@pytest.mark.parametrize("route,contract,schema", [
    (BASE_ROUTE_V2_7, "universe_classifier_manifest@0.7.0",
     "schemas/universe_classifier_manifest.v7.schema.json"),
    (CONTINUATION_ROUTE_V2_7, "universe_classifier_continuation_manifest@0.7.0",
     "schemas/universe_classifier_continuation_manifest.v7.schema.json"),
    (CALIBRATION_ROUTE_V2_7, "universe_classifier_calibration_manifest@0.7.0",
     "schemas/universe_classifier_calibration_manifest.v7.schema.json"),
])
def test_each_v2_7_route_binds_its_own_v7_contract(route, contract, schema):
    assert route.manifest_contract == contract
    assert route.manifest_schema == schema
    assert route.contracts is ccs.V2_7
    assert "v2_7" in route.records_filename and "v2_7" in route.manifest_filename


def test_the_v7_authorization_schemas_pin_the_v2_7_prompt():
    import json
    for name in ("universe_classifier_authorization",
                 "universe_classifier_continuation_authorization",
                 "universe_classifier_calibration_authorization"):
        s = json.loads((REPO / f"schemas/{name}.v7.schema.json").read_bytes())
        props = s["properties"]
        assert props["prompt_template_path"]["const"] == \
            "prompts/discovery/universe_full_classification.v2_7.md"
        assert props["taxonomy_version"]["const"] == "universe_classifier_axes_v2_5"
        assert props["span_index_version"]["const"] == "universe_classifier_span_index_v1"
        assert props["output_contract"]["const"] == "universe_classifier_record@0.4.0"


#: Each V7 schema and the exact title it must carry. Spelled out rather than
#: derived, so a wrong title cannot be produced by the same rule that checks it.
V7_TITLES = {
    "universe_classifier_authorization":
        "Universe classifier authorization v0.7.0",
    "universe_classifier_manifest":
        "Universe classifier manifest v0.7.0",
    "universe_classifier_continuation_authorization":
        "Universe classifier continuation authorization v0.7.0",
    "universe_classifier_continuation_manifest":
        "Universe classifier continuation manifest v0.7.0",
    "universe_classifier_calibration_authorization":
        "Universe classifier calibration authorization v0.7.0",
    "universe_classifier_calibration_manifest":
        "Universe classifier calibration manifest v0.7.0",
}


@pytest.mark.parametrize("name,title", sorted(V7_TITLES.items()))
def test_every_v7_schema_describes_itself_as_v2_7_and_adr_134(name, title):
    """A schema that still calls itself v0.6.0 is a lie a reviewer would read."""
    import json
    s = json.loads((REPO / f"schemas/{name}.v7.schema.json").read_bytes())
    assert s["$id"].endswith(f"{name}.v7.schema.json")
    assert ".v6.schema.json" not in s["$id"]
    assert s["title"] == title
    assert "v0.6.0" not in s["title"]
    assert s["description"].startswith("ADR-134.")
    assert "V2.6 calibration completed" in s["description"]
    # the description must not still be telling ADR-133's story as its own
    assert "Successor to the 0.6.0 contracts" in s["description"]
    assert "Successor to the 0.5.0 contracts" not in s["description"]
    key = next(k for k in s["properties"] if k.endswith("_contract")
               and k.startswith(("authorization", "manifest")))
    assert s["properties"][key]["const"] == f"{name}@0.7.0"


def test_v7_manifests_keep_the_v2_6_null_compatible_token_accounting():
    import json
    for name in ("universe_classifier_manifest",
                 "universe_classifier_continuation_manifest",
                 "universe_classifier_calibration_manifest"):
        s = json.loads((REPO / f"schemas/{name}.v7.schema.json").read_bytes())
        acct = s["properties"]["request_accounting"]
        assert acct["properties"]["tokens_out_reported"]["type"] == ["integer", "null"]
        assert "tokens_out_reported" in acct["required"]
        assert acct["additionalProperties"] == {"type": "integer"}


def test_v2_6_route_is_untouched():
    assert CALIBRATION_ROUTE_V2_6.manifest_contract == \
        "universe_classifier_calibration_manifest@0.6.0"
    assert CALIBRATION_ROUTE_V2_6.contracts is ccs.V2_6
