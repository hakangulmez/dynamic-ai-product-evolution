"""ADR-126 tests: the tier is derived, and market orientation never touches it.

The engine is the only thing in the pipeline permitted to name a tier, so these
tests care about two things above all: that a rule config which could quietly
mis-tier a firm is refused when it loads rather than obeyed at evaluation time,
and that ``customer_market_orientation`` cannot reach the decision by any path.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from dynamic_ai_products import classifier_tier_engine as cte

ROOT = Path(__file__).resolve().parents[2]

AXES_FIELDS = ("customer_value_archetypes", "software_centrality",
               "complementary_dependencies", "firm_structure",
               "commercial_materiality", "customer_facing_functional_product",
               "economically_eligible", "data_eligible",
               "customer_market_orientation")


def _axes(**overrides):
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
        "boundary_flags": [], "contradictions": [], "evidence": [],
        "confidence": "high",
    }
    axes.update(overrides)
    return axes


@pytest.fixture(scope="module")
def rules():
    return cte.load_tier_rules(ROOT)


def _write(tmp_path: Path, config: dict) -> Path:
    root = tmp_path / "repo"
    (root / "configs").mkdir(parents=True, exist_ok=True)
    (root / cte.TIER_RULES_RELATIVE_PATH).write_text(
        yaml.safe_dump(config, sort_keys=False), encoding="utf-8")
    return root


def _valid_config():
    return {"tier_rules_version": "fixture_rules_v1",
            "rules": [{"rule_id": "core", "tier": "TIER_A",
                       "when": {"software_centrality": ["CORE"]}},
                      {"rule_id": "rest", "tier": "UNCERTAIN", "when": {}}]}


# --- the committed config ----------------------------------------------------------


def test_the_committed_config_loads_and_pins_its_own_digest(rules):
    from hashlib import sha256
    raw = (ROOT / cte.TIER_RULES_RELATIVE_PATH).read_bytes()
    assert rules.version == "universe_classifier_tier_rules_v2_1"
    assert rules.sha256 == sha256(raw).hexdigest()
    assert len({r["rule_id"] for r in rules.rules}) == len(rules.rules)


def test_the_committed_config_never_names_market_orientation():
    raw = (ROOT / cte.TIER_RULES_RELATIVE_PATH).read_text(encoding="utf-8")
    config = yaml.safe_load(raw)
    for rule in config["rules"]:
        for key in ("when", "when_any"):
            assert cte.FORBIDDEN_CONDITION not in (rule.get(key) or {})


def test_the_sentinel_rule_config_is_a_different_file():
    assert cte.TIER_RULES_RELATIVE_PATH != "configs/universe_sample_rules.yaml"
    assert (ROOT / "configs/universe_sample_rules.yaml").is_file()


# --- derivation --------------------------------------------------------------------


@pytest.mark.parametrize("overrides,tier,rule_id", [
    ({}, "TIER_A", "tier_a_core_software_dominant_firm"),
    ({"software_centrality": "CO_ESSENTIAL", "firm_structure": "MIXED_NONSEPARABLE",
      "commercial_materiality": "MATERIAL"},
     "TIER_B", "tier_b_core_or_co_essential_mixed_firm"),
    ({"software_centrality": "ENABLING", "firm_structure": "MIXED_SEPARABLE",
      "commercial_materiality": "MATERIAL"},
     "TIER_C", "tier_c_enabling_software"),
    ({"software_centrality": "PERIPHERAL", "firm_structure": "SOFTWARE_PERIPHERAL",
      "commercial_materiality": "MINOR"},
     "EXCLUDED", "excluded_peripheral_software"),
    ({"customer_facing_functional_product": False},
     "EXCLUDED", "excluded_no_customer_facing_product"),
    ({"customer_facing_functional_product": None},
     "UNCERTAIN", "uncertain_unknown_product_or_centrality"),
    ({"software_centrality": "UNKNOWN"},
     "UNCERTAIN", "uncertain_unknown_product_or_centrality"),
    ({"firm_structure": "UNKNOWN"},
     "UNCERTAIN", "uncertain_unknown_product_or_centrality"),
    ({"software_centrality": "CORE", "firm_structure": "SOFTWARE_PERIPHERAL",
      "commercial_materiality": "UNKNOWN"},
     "UNCERTAIN", "uncertain_unresolved_combination"),
])
def test_the_axes_decide_the_tier(rules, overrides, tier, rule_id):
    derivation = cte.derive_tier(_axes(**overrides), rules)
    assert derivation.tier == tier
    fired = [e for e in derivation.trace["entries"] if e["result"] == "fired"]
    assert [e["rule_id"] for e in fired] == [rule_id]


def test_an_excluded_firm_never_reaches_a_tier_rule(rules):
    derivation = cte.derive_tier(
        _axes(customer_facing_functional_product=False,
              software_centrality="CORE", firm_structure="PURE_PLAY"), rules)
    assert derivation.tier == "EXCLUDED"
    assert len(derivation.trace["entries"]) == 1


@pytest.mark.parametrize("orientation", ["B2B", "B2C", "MIXED", "UNKNOWN"])
@pytest.mark.parametrize("shape", [
    {}, {"software_centrality": "ENABLING"},
    {"software_centrality": "PERIPHERAL"},
    {"customer_facing_functional_product": None},
])
def test_market_orientation_changes_no_tier(rules, orientation, shape):
    baseline = cte.derive_tier(_axes(**shape), rules)
    permuted = cte.derive_tier(
        _axes(**shape, customer_market_orientation=orientation), rules)
    assert permuted.tier == baseline.tier
    assert permuted.trace["entries"] == baseline.trace["entries"]


def test_the_trace_replays_the_derivation(rules):
    axes = _axes(software_centrality="CO_ESSENTIAL",
                 firm_structure="MIXED_SEPARABLE",
                 commercial_materiality="MINOR")
    derivation = cte.derive_tier(axes, rules)
    assert derivation.trace["tier_rules_version"] == rules.version
    assert derivation.trace["tier_rules_sha256"] == rules.sha256
    considered = [e["rule_id"] for e in derivation.trace["entries"]]
    assert considered == [r["rule_id"] for r in rules.rules][:len(considered)]
    assert cte.derive_tier(axes, rules).tier == derivation.tier


def test_the_trace_records_the_rules_that_did_not_fire(rules):
    derivation = cte.derive_tier(_axes(software_centrality="ENABLING",
                                       firm_structure="MIXED_SEPARABLE"), rules)
    results = {e["result"] for e in derivation.trace["entries"]}
    assert results == {"not_matched", "fired"}


# --- refusals ----------------------------------------------------------------------


def test_a_rule_conditioning_on_market_orientation_is_refused(tmp_path):
    config = _valid_config()
    config["rules"][0]["when"][cte.FORBIDDEN_CONDITION] = ["B2B"]
    with pytest.raises(cte.TierRulesError, match="descriptive metadata"):
        cte.load_tier_rules(_write(tmp_path, config))


def test_a_rule_conditioning_on_an_unknown_axis_is_refused(tmp_path):
    config = _valid_config()
    config["rules"][0]["when"]["revenue_growth"] = [True]
    with pytest.raises(cte.TierRulesError, match="unknown axis"):
        cte.load_tier_rules(_write(tmp_path, config))


def test_a_tier_outside_the_closed_set_is_refused(tmp_path):
    config = _valid_config()
    config["rules"][0]["tier"] = "TIER_S"
    with pytest.raises(cte.TierRulesError, match="closed set"):
        cte.load_tier_rules(_write(tmp_path, config))


def test_a_duplicate_rule_id_is_refused(tmp_path):
    config = _valid_config()
    config["rules"].insert(1, dict(config["rules"][0]))
    with pytest.raises(cte.TierRulesError, match="appears twice"):
        cte.load_tier_rules(_write(tmp_path, config))


def test_a_non_exhaustive_config_is_refused(tmp_path):
    config = _valid_config()
    config["rules"][-1]["when"] = {"software_centrality": ["ENABLING"]}
    with pytest.raises(cte.TierRulesError, match="unconditional"):
        cte.load_tier_rules(_write(tmp_path, config))


def test_a_config_without_a_version_is_refused(tmp_path):
    config = _valid_config()
    del config["tier_rules_version"]
    with pytest.raises(cte.TierRulesError, match="no version"):
        cte.load_tier_rules(_write(tmp_path, config))


def test_a_config_without_rules_is_refused(tmp_path):
    with pytest.raises(cte.TierRulesError, match="no rules"):
        cte.load_tier_rules(_write(tmp_path, {"tier_rules_version": "v",
                                              "rules": []}))


def test_a_missing_config_is_refused(tmp_path):
    with pytest.raises(cte.TierRulesError, match="not found"):
        cte.load_tier_rules(tmp_path / "nowhere")


def test_the_engine_imports_no_provider_sdk():
    """Asserted against the module's own source, not against global state.

    Reading ``sys.modules`` would make this test a report on whatever some
    earlier suite happened to import, which is a different question.
    """
    source = (ROOT / "src/dynamic_ai_products/classifier_tier_engine.py").read_text(
        encoding="utf-8")
    for forbidden in ("google", "genai", "vertex", "requests", "httpx"):
        assert forbidden not in source, forbidden
