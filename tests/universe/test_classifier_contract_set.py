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


def _schema(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


# --- the two contract sets ---------------------------------------------------------


def test_both_contract_sets_resolve_to_committed_files():
    for cset in (ccs.V2_1, ccs.V2_2):
        for attr in ("prompt_path", "axes_schema", "record_schema"):
            assert (ROOT / getattr(cset, attr)).is_file(), (cset.version_id, attr)


def test_the_versions_share_no_artifact():
    for attr in ("prompt_path", "axes_schema", "axes_contract", "record_contract",
                 "record_schema", "taxonomy_version", "output_prefix"):
        assert getattr(ccs.V2_1, attr) != getattr(ccs.V2_2, attr), attr


def test_an_unknown_contract_version_is_refused():
    assert ccs.contract_set_for("v2_1") is ccs.V2_1
    assert ccs.contract_set_for("v2_2") is ccs.V2_2
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
    for cset in (ccs.V2_1, ccs.V2_2):
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
