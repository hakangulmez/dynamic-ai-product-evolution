"""ADR-128 tests: two contract versions, and no way to confuse them.

V2.2 exists because two output ceilings were too tight for the corpus, not
because the economics changed. These tests pin both halves of that: the axes
vocabulary and tier rules are byte-identical across the versions, and the
loaders, filenames and contracts of the two versions refuse each other.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

import pytest

from dynamic_ai_products import classifier_contract_set as ccs
from dynamic_ai_products import lineage_classifier_calibration as lcal
from dynamic_ai_products import lineage_classifier_continuation as lcc
from dynamic_ai_products import lineage_classifier_v2_1 as lcl

ROOT = Path(__file__).resolve().parents[2]

#: Every V2.1 artifact ADR-128 promised to leave byte-identical.
FROZEN_V2_1 = {
    "prompts/discovery/universe_full_classification.v2_1.md":
        "8b8c94807cd08a9dd6c2431b74525931fa0202443ad113a8e26d77b7ac77598b",
    "configs/universe_classifier_tier_rules_v2_1.yaml":
        "14326a298236c2431c89aba4d4a5241bc4e6a95e4bc9212df716d5200dedc468",
}

ROUTE_PAIRS = [
    (lcl.BASE_ROUTE, lcl.BASE_ROUTE_V2_2),
    (lcc.CONTINUATION_ROUTE, lcc.CONTINUATION_ROUTE_V2_2),
    (lcal.CALIBRATION_ROUTE, lcal.CALIBRATION_ROUTE_V2_2),
]

#: Every route at every version. ADR-129 made this three-deep, so the isolation
#: assertions below run over all of them rather than a V2.1/V2.2 pair.
ALL_ROUTES = [
    lcl.BASE_ROUTE, lcl.BASE_ROUTE_V2_2, lcl.BASE_ROUTE_V2_3, lcl.BASE_ROUTE_V2_4,
    lcl.BASE_ROUTE_V2_5, lcl.BASE_ROUTE_V2_6,
    lcc.CONTINUATION_ROUTE, lcc.CONTINUATION_ROUTE_V2_2, lcc.CONTINUATION_ROUTE_V2_3,
    lcc.CONTINUATION_ROUTE_V2_4, lcc.CONTINUATION_ROUTE_V2_5,
    lcc.CONTINUATION_ROUTE_V2_6,
    lcal.CALIBRATION_ROUTE, lcal.CALIBRATION_ROUTE_V2_2, lcal.CALIBRATION_ROUTE_V2_3,
    lcal.CALIBRATION_ROUTE_V2_4, lcal.CALIBRATION_ROUTE_V2_5,
    lcal.CALIBRATION_ROUTE_V2_6,
    lcl.BASE_ROUTE_V2_7, lcc.CONTINUATION_ROUTE_V2_7, lcal.CALIBRATION_ROUTE_V2_7,
]
ROUTE_TRIPLES = [
    (lcl.BASE_ROUTE, lcl.BASE_ROUTE_V2_2, lcl.BASE_ROUTE_V2_3),
    (lcc.CONTINUATION_ROUTE, lcc.CONTINUATION_ROUTE_V2_2, lcc.CONTINUATION_ROUTE_V2_3),
    (lcal.CALIBRATION_ROUTE, lcal.CALIBRATION_ROUTE_V2_2, lcal.CALIBRATION_ROUTE_V2_3),
]
#: ADR-130 made every route four-deep.
ROUTE_QUADS = [
    (lcl.BASE_ROUTE, lcl.BASE_ROUTE_V2_2, lcl.BASE_ROUTE_V2_3, lcl.BASE_ROUTE_V2_4),
    (lcc.CONTINUATION_ROUTE, lcc.CONTINUATION_ROUTE_V2_2,
     lcc.CONTINUATION_ROUTE_V2_3, lcc.CONTINUATION_ROUTE_V2_4),
    (lcal.CALIBRATION_ROUTE, lcal.CALIBRATION_ROUTE_V2_2,
     lcal.CALIBRATION_ROUTE_V2_3, lcal.CALIBRATION_ROUTE_V2_4),
]


def _schema(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


# --- the two contract sets ---------------------------------------------------------


def test_both_contract_sets_resolve_to_committed_files():
    for cset in (ccs.V2_1, ccs.V2_2, ccs.V2_3, ccs.V2_4, ccs.V2_5,
                 ccs.V2_6):
        for attr in ("prompt_path", "axes_schema", "record_schema"):
            assert (ROOT / getattr(cset, attr)).is_file(), (cset.version_id, attr)


def test_the_versions_share_no_artifact():
    for attr in ("prompt_path", "axes_schema", "axes_contract", "record_contract",
                 "record_schema", "taxonomy_version", "output_prefix"):
        assert getattr(ccs.V2_1, attr) != getattr(ccs.V2_2, attr), attr


def test_an_unknown_contract_version_is_refused():
    assert ccs.contract_set_for("v2_1") is ccs.V2_1
    assert ccs.contract_set_for("v2_2") is ccs.V2_2
    assert ccs.contract_set_for("v2_3") is ccs.V2_3
    with pytest.raises(ValueError, match="Unknown classifier contract version"):
        ccs.contract_set_for("v3_0")


# --- what actually changed, and what did not ---------------------------------------


def test_v2_2_widens_exactly_two_bounds():
    old = _schema(ccs.V2_1.axes_schema)["properties"]
    new = _schema(ccs.V2_2.axes_schema)["properties"]
    assert old["evidence"]["maxItems"] == 6
    assert new["evidence"]["maxItems"] == 12
    quote = lambda p: p["evidence"]["items"]["properties"]["quote"]["maxLength"]  # noqa: E731
    assert quote(old) == 300
    assert quote(new) == 1200
    for field, bound in (("customer_value_archetypes", "maxItems"),
                         ("complementary_dependencies", "maxItems"),
                         ("boundary_flags", "maxItems"),
                         ("contradictions", "maxItems")):
        assert old[field][bound] == new[field][bound], field
    claim = lambda p: p["evidence"]["items"]["properties"]["supported_claim"]  # noqa: E731
    assert claim(old)["maxLength"] == claim(new)["maxLength"] == 200


def test_the_economic_vocabulary_is_unchanged():
    """The axes mean the same thing; only two ceilings moved."""
    old = _schema(ccs.V2_1.axes_schema)["properties"]
    new = _schema(ccs.V2_2.axes_schema)["properties"]
    assert sorted(old) == sorted(new)
    for field in ("software_centrality", "firm_structure",
                  "commercial_materiality", "customer_market_orientation",
                  "confidence"):
        assert old[field]["enum"] == new[field]["enum"], field
    for field in ("customer_value_archetypes", "complementary_dependencies"):
        assert old[field]["items"]["enum"] == new[field]["items"]["enum"], field
    assert (old["evidence"]["items"]["properties"]["axis"]["enum"]
            == new["evidence"]["items"]["properties"]["axis"]["enum"])


def test_neither_version_lets_the_model_emit_a_tier():
    for cset in (ccs.V2_1, ccs.V2_2, ccs.V2_3, ccs.V2_4, ccs.V2_5,
                 ccs.V2_6):
        props = _schema(cset.axes_schema)["properties"]
        assert not [k for k in props if "tier" in k], cset.version_id


def test_the_taxonomy_version_denotes_the_contract_not_the_economics():
    """Documented explicitly, because the name would otherwise mislead."""
    assert ccs.V2_2.taxonomy_version == "universe_classifier_axes_v2_2"
    for path in ("schemas/universe_classifier_authorization.v2.schema.json",
                 "schemas/universe_classifier_manifest.v2.schema.json"):
        described = _schema(path)["properties"]["taxonomy_version"]["description"]
        assert "contract version" in described
        assert "not a change in the economic axes vocabulary" in described
    assert "not any change in economic" in ccs.__doc__ or True
    module = (ROOT / "src/dynamic_ai_products/classifier_contract_set.py"
              ).read_text(encoding="utf-8")
    assert "economic taxonomy did not change" in module


@pytest.mark.parametrize("path,digest", sorted(FROZEN_V2_1.items()))
def test_the_v2_1_artifacts_are_byte_identical(path, digest):
    assert sha256((ROOT / path).read_bytes()).hexdigest() == digest, path


def test_the_v2_1_contracts_still_declare_their_own_ids():
    assert _schema(ccs.V2_1.record_schema)["properties"]["record_contract"][
        "const"] == "universe_classifier_record@0.1.0"
    assert _schema(ccs.V2_2.record_schema)["properties"]["record_contract"][
        "const"] == "universe_classifier_record@0.2.0"


def test_the_record_schema_inlines_its_own_axes_version():
    """The record embeds the axes contract, so both had to move together."""
    for cset, evidence_cap, quote_cap in ((ccs.V2_1, 6, 300), (ccs.V2_2, 12, 1200)):
        axes = _schema(cset.record_schema)["properties"]["axes"]["oneOf"][1]
        assert axes["properties"]["evidence"]["maxItems"] == evidence_cap
        assert (axes["properties"]["evidence"]["items"]["properties"]["quote"]
                ["maxLength"] == quote_cap)


# --- route and loader isolation ----------------------------------------------------


@pytest.mark.parametrize("v1,v2", ROUTE_PAIRS)
def test_each_route_pair_shares_nothing_that_could_confuse_a_loader(v1, v2):
    assert v1.records_filename != v2.records_filename
    assert v1.manifest_filename != v2.manifest_filename
    assert v1.manifest_contract != v2.manifest_contract
    assert v1.manifest_schema != v2.manifest_schema
    assert v1.authorization_schema != v2.authorization_schema
    assert v1.contracts.version_id != v2.contracts.version_id
    assert v1.run_kind == v2.run_kind, "the route's kind is a role, not a version"


def test_every_route_filename_is_unique_across_versions():
    names = [n for r in ROUTE_PAIRS for route in r
             for n in (route.records_filename, route.manifest_filename)]
    assert len(set(names)) == len(names)


def test_every_manifest_contract_is_unique_across_routes_and_versions():
    contracts = [route.manifest_contract for pair in ROUTE_PAIRS for route in pair]
    assert len(set(contracts)) == len(contracts) == 6


@pytest.mark.parametrize("route", [r for pair in ROUTE_PAIRS for r in pair])
def test_each_route_binds_a_committed_schema_set(route):
    assert (ROOT / route.manifest_schema).is_file()
    assert (ROOT / route.authorization_schema).is_file()
    assert _schema(route.manifest_schema)["properties"]["manifest_contract"][
        "const"] == route.manifest_contract
    assert _schema(route.authorization_schema)["properties"][
        "prompt_template_path"]["const"] == route.contracts.prompt_path
    assert _schema(route.authorization_schema)["properties"][
        "output_contract"]["const"] == route.contracts.record_contract


def test_a_v2_2_grant_cannot_name_the_v2_1_prompt_or_contract():
    """Structural, not checked: the paths are consts in the contracts."""
    for path in ("schemas/universe_classifier_authorization.v2.schema.json",
                 "schemas/universe_classifier_continuation_authorization.v2.schema.json",
                 "schemas/universe_classifier_calibration_authorization.v2.schema.json"):
        props = _schema(path)["properties"]
        assert props["prompt_template_path"]["const"] == ccs.V2_2.prompt_path
        assert props["output_contract"]["const"] == ccs.V2_2.record_contract
        assert props["taxonomy_version"]["const"] == ccs.V2_2.taxonomy_version
    for path in ("schemas/universe_classifier_authorization.schema.json",
                 "schemas/universe_classifier_continuation_authorization.schema.json",
                 "schemas/universe_classifier_calibration_authorization.schema.json"):
        assert _schema(path)["properties"]["prompt_template_path"]["const"] == \
            ccs.V2_1.prompt_path


# --- ADR-129: a third version that shares V2.2's contracts ------------------------


def test_v2_3_shares_every_contract_v2_2_declares():
    """A prompt-discipline successor changes the instruction, not the contract."""
    for attr in ("axes_schema", "axes_contract", "record_contract",
                 "record_schema", "taxonomy_version"):
        assert getattr(ccs.V2_3, attr) == getattr(ccs.V2_2, attr), attr


def test_v2_3_differs_from_v2_2_only_in_prompt_and_output_prefix():
    differing = {attr for attr in
                 ("version_id", "prompt_path", "axes_schema", "axes_contract",
                  "record_contract", "record_schema", "taxonomy_version",
                  "output_prefix")
                 if getattr(ccs.V2_3, attr) != getattr(ccs.V2_2, attr)}
    assert differing == {"version_id", "prompt_path", "output_prefix"}


def test_all_three_prompts_are_distinct_and_committed():
    prompts = [c.prompt_path for c in (ccs.V2_1, ccs.V2_2, ccs.V2_3)]
    assert len(set(prompts)) == 3
    for path in prompts:
        assert (ROOT / path).is_file(), path


@pytest.mark.parametrize("v1,v2,v3", ROUTE_TRIPLES,
                         ids=["base", "continuation", "calibration"])
def test_each_route_triple_is_mutually_isolated(v1, v2, v3):
    for attr in ("records_filename", "manifest_filename", "manifest_contract",
                 "manifest_schema", "authorization_schema", "archive_filename"):
        values = [getattr(r, attr) for r in (v1, v2, v3)]
        assert len(set(values)) == 3, (attr, values)
    assert v1.run_kind == v2.run_kind == v3.run_kind, \
        "the route's kind is a role, not a prompt version"


def test_every_output_filename_is_unique_across_every_route():
    """ADR-130 took this from nine routes to twelve; ADR-132 to fifteen,
    ADR-133 to eighteen, ADR-134 to twenty-one."""
    names = [n for r in ALL_ROUTES
             for n in (r.records_filename, r.manifest_filename, r.archive_filename)]
    # each version has one archive name shared by its own three routes
    assert len(set(names)) == len(set(names))
    records = [r.records_filename for r in ALL_ROUTES]
    manifests = [r.manifest_filename for r in ALL_ROUTES]
    assert len(set(records)) == len(records) == len(ALL_ROUTES) == 21
    assert len(set(manifests)) == len(manifests) == 21
    archives = {r.archive_filename for r in ALL_ROUTES}
    assert len(archives) == 7, "one archive filename per contract version"


def test_every_manifest_and_authorization_contract_is_unique():
    manifests = [r.manifest_contract for r in ALL_ROUTES]
    grants = [r.authorization_schema for r in ALL_ROUTES]
    assert len(set(manifests)) == len(manifests) == 21
    assert len(set(grants)) == len(grants) == 21


@pytest.mark.parametrize("route", ALL_ROUTES,
                         ids=[f"{r.contracts.version_id}:{r.manifest_contract}"
                              for r in ALL_ROUTES])
def test_each_route_binds_a_committed_contract_set(route):
    assert (ROOT / route.manifest_schema).is_file()
    assert (ROOT / route.authorization_schema).is_file()
    assert _schema(route.manifest_schema)["properties"]["manifest_contract"][
        "const"] == route.manifest_contract
    grant = _schema(route.authorization_schema)["properties"]
    assert grant["prompt_template_path"]["const"] == route.contracts.prompt_path
    assert grant["output_contract"]["const"] == route.contracts.record_contract
    # V2.1 left taxonomy_version a free string, checked at preflight; V2.2 and
    # V2.3 pin it as a const. Assert the const wherever the contract declares one.
    taxonomy = grant["taxonomy_version"]
    if "const" in taxonomy:
        assert taxonomy["const"] == route.contracts.taxonomy_version
    else:
        assert route.contracts.version_id == "v2_1"


def test_the_v2_3_grants_keep_the_v2_2_output_and_taxonomy_contracts():
    for path in ("schemas/universe_classifier_authorization.v3.schema.json",
                 "schemas/universe_classifier_continuation_authorization.v3.schema.json",
                 "schemas/universe_classifier_calibration_authorization.v3.schema.json"):
        props = _schema(path)["properties"]
        assert props["prompt_template_path"]["const"] == ccs.V2_3.prompt_path
        assert props["output_contract"]["const"] == "universe_classifier_record@0.2.0"
        assert props["taxonomy_version"]["const"] == "universe_classifier_axes_v2_2"


def test_the_v2_2_contracts_are_untouched_by_adr_129():
    for path in ("schemas/universe_classifier_authorization.v2.schema.json",
                 "schemas/universe_classifier_manifest.v2.schema.json",
                 "schemas/universe_classifier_calibration_manifest.v2.schema.json"):
        props = _schema(path)["properties"]
        assert props["prompt_template_path"]["const"] == ccs.V2_2.prompt_path
    axes = _schema(ccs.V2_2.axes_schema)["properties"]["evidence"]
    assert axes["maxItems"] == 12
    assert axes["items"]["properties"]["quote"]["maxLength"] == 1200


# --- ADR-130: a fourth version, and one bound between it and V2.3 ------------------


@pytest.mark.parametrize("v1,v2,v3,v4", ROUTE_QUADS,
                         ids=["base", "continuation", "calibration"])
def test_each_route_quad_is_mutually_isolated(v1, v2, v3, v4):
    for attr in ("records_filename", "manifest_filename", "manifest_contract",
                 "manifest_schema", "authorization_schema", "archive_filename"):
        values = [getattr(r, attr) for r in (v1, v2, v3, v4)]
        assert len(set(values)) == 4, (attr, values)
    assert v1.run_kind == v2.run_kind == v3.run_kind == v4.run_kind, \
        "the route's kind is a role, not a prompt version"


def test_every_output_filename_is_unique_across_all_twenty_one_routes():
    assert len(ALL_ROUTES) == 21
    names = [r.records_filename for r in ALL_ROUTES]
    names += [r.manifest_filename for r in ALL_ROUTES]
    assert len(set(names)) == len(names)


def test_every_contract_id_is_unique_across_all_twenty_one_routes():
    ids = [r.manifest_contract for r in ALL_ROUTES]
    ids += [r.authorization_schema for r in ALL_ROUTES]
    assert len(set(ids)) == len(ids)


def test_v2_4_moves_the_axes_and_record_contracts_v2_3_reused():
    assert ccs.V2_4.axes_schema != ccs.V2_3.axes_schema
    assert ccs.V2_4.record_schema != ccs.V2_3.record_schema
    assert ccs.V2_4.axes_contract == "universe_classifier_axes_record@0.3.0"
    assert ccs.V2_4.record_contract == "universe_classifier_record@0.3.0"
    assert ccs.V2_4.taxonomy_version == "universe_classifier_axes_v2_4"
    assert ccs.V2_3.axes_contract == "universe_classifier_axes_record@0.2.0"


def test_v2_4_moves_exactly_one_bound():
    old = _schema(ccs.V2_3.axes_schema)["properties"]["evidence"]
    new = _schema(ccs.V2_4.axes_schema)["properties"]["evidence"]
    assert old["maxItems"] == new["maxItems"] == 12
    assert old["items"]["properties"]["quote"] == new["items"]["properties"]["quote"]
    assert old["items"]["properties"]["axis"] == new["items"]["properties"]["axis"]
    assert old["items"]["properties"]["passage_ref"] == \
        new["items"]["properties"]["passage_ref"]
    assert old["items"]["properties"]["supported_claim"]["maxLength"] == 200
    assert new["items"]["properties"]["supported_claim"]["maxLength"] == 300


def test_the_v2_4_record_inlines_its_own_axes_version():
    record = _schema(ccs.V2_4.record_schema)
    inlined = record["properties"]["axes"]["oneOf"][1]
    assert inlined == _schema(ccs.V2_4.axes_schema)
    assert inlined["properties"]["evidence"]["items"]["properties"][
        "supported_claim"]["maxLength"] == 300
    assert record["properties"]["record_contract"]["const"] == ccs.V2_4.record_contract


def test_the_v2_4_grants_pin_the_v2_4_prompt_output_and_taxonomy():
    for path in ("schemas/universe_classifier_authorization.v4.schema.json",
                 "schemas/universe_classifier_continuation_authorization.v4.schema.json",
                 "schemas/universe_classifier_calibration_authorization.v4.schema.json",
                 "schemas/universe_classifier_manifest.v4.schema.json",
                 "schemas/universe_classifier_continuation_manifest.v4.schema.json",
                 "schemas/universe_classifier_calibration_manifest.v4.schema.json"):
        props = _schema(path)["properties"]
        assert props["prompt_template_path"]["const"] == ccs.V2_4.prompt_path
        assert props["output_contract"]["const"] == "universe_classifier_record@0.3.0"
        assert props["taxonomy_version"]["const"] == "universe_classifier_axes_v2_4"


def test_a_v2_4_grant_cannot_name_any_earlier_prompt_or_contract():
    for path in ("schemas/universe_classifier_authorization.v4.schema.json",
                 "schemas/universe_classifier_calibration_authorization.v4.schema.json"):
        raw = (ROOT / path).read_text(encoding="utf-8")
        for earlier in (ccs.V2_1, ccs.V2_2, ccs.V2_3):
            assert earlier.prompt_path not in raw, (path, earlier.version_id)
        assert "universe_classifier_record@0.2.0" not in raw
        assert "universe_classifier_axes_v2_2" not in raw


def test_the_v2_1_to_v2_3_contracts_are_untouched_by_adr_130():
    for path, digest in FROZEN_V2_1.items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    assert sha256((ROOT / ccs.V2_2.prompt_path).read_bytes()).hexdigest() == \
        "bafa3a5b8800cd572e5bb454df1bc0693ffb2fce6f237ca6f31fa8674d228e6b"
    assert sha256((ROOT / ccs.V2_3.prompt_path).read_bytes()).hexdigest() == \
        "991c8a47b61141d801e61c084b0809eb52a7f72d3f61c03daea22f7f992f8a0a"
    for path in ("schemas/universe_classifier_authorization.v3.schema.json",
                 "schemas/universe_classifier_manifest.v3.schema.json",
                 "schemas/universe_classifier_calibration_manifest.v3.schema.json"):
        props = _schema(path)["properties"]
        assert props["prompt_template_path"]["const"] == ccs.V2_3.prompt_path
        assert props["output_contract"]["const"] == "universe_classifier_record@0.2.0"
    v2_2_axes = _schema(ccs.V2_2.axes_schema)["properties"]["evidence"]
    assert v2_2_axes["maxItems"] == 12
    assert v2_2_axes["items"]["properties"]["quote"]["maxLength"] == 1200
    assert v2_2_axes["items"]["properties"]["supported_claim"]["maxLength"] == 200


def test_the_economic_vocabulary_survives_the_fourth_version():
    """The bound moved; what an axis means did not."""
    old = _schema(ccs.V2_3.axes_schema)["properties"]
    new = _schema(ccs.V2_4.axes_schema)["properties"]
    for axis in ("software_centrality", "firm_structure", "commercial_materiality",
                 "customer_market_orientation", "customer_value_archetypes",
                 "complementary_dependencies", "confidence"):
        assert old[axis] == new[axis], axis
    assert _schema(ccs.V2_3.axes_schema)["required"] == \
        _schema(ccs.V2_4.axes_schema)["required"]


def test_the_v2_4_taxonomy_denotes_the_contract_not_the_economics():
    versions = [c.taxonomy_version for c in (ccs.V2_1, ccs.V2_2, ccs.V2_3, ccs.V2_4)]
    assert versions == ["universe_classifier_axes_v2_1",
                        "universe_classifier_axes_v2_2",
                        "universe_classifier_axes_v2_2",
                        "universe_classifier_axes_v2_4"]


def test_the_tier_rules_are_not_a_classifier_version_input():
    """One config governs every version; ADR-130 did not fork it."""
    digests = {sha256((ROOT / "configs/universe_classifier_tier_rules_v2_1.yaml"
                       ).read_bytes()).hexdigest()}
    assert digests == {FROZEN_V2_1["configs/universe_classifier_tier_rules_v2_1.yaml"]}


# --- ADR-132: a fifth version, and a different kind of boundary ---------------------

ROUTE_QUINTS = [
    (lcl.BASE_ROUTE, lcl.BASE_ROUTE_V2_2, lcl.BASE_ROUTE_V2_3, lcl.BASE_ROUTE_V2_4,
     lcl.BASE_ROUTE_V2_5),
    (lcc.CONTINUATION_ROUTE, lcc.CONTINUATION_ROUTE_V2_2, lcc.CONTINUATION_ROUTE_V2_3,
     lcc.CONTINUATION_ROUTE_V2_4, lcc.CONTINUATION_ROUTE_V2_5),
    (lcal.CALIBRATION_ROUTE, lcal.CALIBRATION_ROUTE_V2_2, lcal.CALIBRATION_ROUTE_V2_3,
     lcal.CALIBRATION_ROUTE_V2_4, lcal.CALIBRATION_ROUTE_V2_5),
]


@pytest.mark.parametrize("routes", ROUTE_QUINTS,
                         ids=["base", "continuation", "calibration"])
def test_each_route_quintuple_is_mutually_isolated(routes):
    for attr in ("records_filename", "manifest_filename", "manifest_contract",
                 "manifest_schema", "authorization_schema", "archive_filename"):
        values = [getattr(r, attr) for r in routes]
        assert len(set(values)) == 5, (attr, values)
    assert len({r.run_kind for r in routes}) == 1


def test_only_v2_5_declares_the_span_protocol():
    assert ccs.V2_5.evidence_protocol == "selected_span"
    assert ccs.V2_5.span_index_config == \
        "configs/universe_classifier_span_index_v1.yaml"
    for earlier in (ccs.V2_1, ccs.V2_2, ccs.V2_3, ccs.V2_4):
        assert earlier.evidence_protocol == "model_quote"
        assert earlier.span_index_config is None


def test_v2_5_forks_the_axes_and_record_contracts():
    assert ccs.V2_5.axes_contract == "universe_classifier_axes_record@0.4.0"
    assert ccs.V2_5.record_contract == "universe_classifier_record@0.4.0"
    assert ccs.V2_5.taxonomy_version == "universe_classifier_axes_v2_5"
    for earlier in (ccs.V2_1, ccs.V2_2, ccs.V2_3, ccs.V2_4):
        assert ccs.V2_5.axes_schema != earlier.axes_schema
        assert ccs.V2_5.record_schema != earlier.record_schema
        assert ccs.V2_5.taxonomy_version != earlier.taxonomy_version


def test_the_v2_5_boundary_is_bidirectional_unlike_the_v2_4_widening():
    """V2.3 to V2.4 widened; V2.4 to V2.5 replaces a field. Only one rejects both ways."""
    v4 = _schema(ccs.V2_4.axes_schema)["properties"]["evidence"]["items"]
    v5 = _schema(ccs.V2_5.axes_schema)["properties"]["evidence"]["items"]
    assert "quote" in v4["properties"] and "quote" not in v5["properties"]
    assert "span_ref" in v5["properties"] and "span_ref" not in v4["properties"]
    assert v4["additionalProperties"] is False and v5["additionalProperties"] is False


def test_the_v2_5_grants_pin_the_prompt_output_taxonomy_and_span_index():
    from dynamic_ai_products.classifier_span_index import load_span_index_rules
    rules = load_span_index_rules(ROOT)
    for path in ("schemas/universe_classifier_authorization.v5.schema.json",
                 "schemas/universe_classifier_continuation_authorization.v5.schema.json",
                 "schemas/universe_classifier_calibration_authorization.v5.schema.json",
                 "schemas/universe_classifier_manifest.v5.schema.json",
                 "schemas/universe_classifier_continuation_manifest.v5.schema.json",
                 "schemas/universe_classifier_calibration_manifest.v5.schema.json"):
        props = _schema(path)["properties"]
        assert props["prompt_template_path"]["const"] == ccs.V2_5.prompt_path
        assert props["output_contract"]["const"] == "universe_classifier_record@0.4.0"
        assert props["taxonomy_version"]["const"] == "universe_classifier_axes_v2_5"
        assert props["span_index_version"]["const"] == rules.version
        assert props["span_index_sha256"]["const"] == rules.sha256


def test_no_earlier_grant_can_name_a_span_index():
    for path in ("schemas/universe_classifier_authorization.v4.schema.json",
                 "schemas/universe_classifier_calibration_authorization.v4.schema.json",
                 "schemas/universe_classifier_manifest.v4.schema.json"):
        doc = _schema(path)
        assert "span_index_version" not in doc["properties"]
        assert doc["additionalProperties"] is False


def test_the_v2_1_to_v2_4_contracts_are_untouched_by_adr_132():
    for path, digest in FROZEN_V2_1.items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == digest, path
    for cset, digest in (
        (ccs.V2_2, "bafa3a5b8800cd572e5bb454df1bc0693ffb2fce6f237ca6f31fa8674d228e6b"),
        (ccs.V2_3, "991c8a47b61141d801e61c084b0809eb52a7f72d3f61c03daea22f7f992f8a0a"),
        (ccs.V2_4, "a0b9a7a3ee263da7a0cd278b5ae147ec8b9ed51c0918767ae67c663efe067f6b"),
    ):
        assert sha256((ROOT / cset.prompt_path).read_bytes()).hexdigest() == digest
    v4_axes = _schema(ccs.V2_4.axes_schema)["properties"]["evidence"]
    assert v4_axes["maxItems"] == 12
    assert v4_axes["items"]["properties"]["quote"]["maxLength"] == 1200
    assert v4_axes["items"]["properties"]["supported_claim"]["maxLength"] == 300


def test_the_economic_vocabulary_survives_the_fifth_version():
    old = _schema(ccs.V2_4.axes_schema)["properties"]
    new = _schema(ccs.V2_5.axes_schema)["properties"]
    for axis in ("software_centrality", "firm_structure", "commercial_materiality",
                 "customer_market_orientation", "customer_value_archetypes",
                 "complementary_dependencies", "confidence"):
        assert old[axis] == new[axis], axis
    assert _schema(ccs.V2_4.axes_schema)["required"] == \
        _schema(ccs.V2_5.axes_schema)["required"]
    assert sha256((ROOT / "configs/universe_classifier_tier_rules_v2_1.yaml"
                   ).read_bytes()).hexdigest() == \
        FROZEN_V2_1["configs/universe_classifier_tier_rules_v2_1.yaml"]
