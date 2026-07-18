import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def test_taxonomy_matches_classification_schema() -> None:
    taxonomy = yaml.safe_load((ROOT / "configs/universe_taxonomy.yaml").read_text())
    schema = json.loads((ROOT / "schemas/company_universe_classification.schema.json").read_text())
    props = schema["properties"]

    assert set(taxonomy["customer_value_archetypes"]) == set(
        props["customer_value_archetypes"]["items"]["enum"]
    )
    assert set(taxonomy["software_centrality"]) == set(
        props["software_centrality"]["enum"]
    )
    assert set(taxonomy["complementary_dependencies"]) == set(
        props["complementary_dependencies"]["items"]["enum"]
    )
    assert set(taxonomy["firm_structure"]) == set(props["firm_structure"]["enum"])
    assert set(taxonomy["commercial_materiality"]) == set(
        props["commercial_materiality"]["enum"]
    )
    assert set(taxonomy["candidate_tiers"]) == set(props["candidate_tier"]["enum"])


def test_sample_rules_reference_known_taxonomy_values() -> None:
    taxonomy = yaml.safe_load((ROOT / "configs/universe_taxonomy.yaml").read_text())
    rules = yaml.safe_load((ROOT / "configs/universe_sample_rules.yaml").read_text())

    assert set(rules["tier_a_core"]["allowed_archetypes"]) <= set(
        taxonomy["customer_value_archetypes"]
    )
    assert set(rules["tier_a_core"]["allowed_software_centrality"]) <= set(
        taxonomy["software_centrality"]
    )
    assert set(rules["tier_a_core"]["allowed_firm_structure"]) <= set(
        taxonomy["firm_structure"]
    )
    assert set(rules["tier_a_core"]["allowed_materiality"]) <= set(
        taxonomy["commercial_materiality"]
    )
    assert set(rules["tier_b_extension"]["candidate_archetypes"]) <= set(
        taxonomy["customer_value_archetypes"]
    )
    assert set(rules["tier_c_boundary"]["default_archetypes"]) <= set(
        taxonomy["customer_value_archetypes"]
    )


def test_stage_00_declares_universe_release_outputs() -> None:
    registry = yaml.safe_load((ROOT / "configs/pipeline_stages.yaml").read_text())
    stage = next(s for s in registry["stages"] if str(s["id"]).zfill(2) == "00")
    outputs = set(stage["outputs"])
    assert "data/processed/company_universe_classifications.parquet" in outputs
    assert "data/processed/firm_year_eligibility.parquet" in outputs
    assert "data/processed/firm_lineage.parquet" in outputs
    assert "data/manifests/company_universe_manifest.json" in outputs


def test_project_blocks_full_edgar_run_by_default() -> None:
    project = yaml.safe_load((ROOT / "configs/project.yaml").read_text())
    assert project["universe"]["baseline_cutoff"] is None
    assert project["universe"]["full_edgar_run_enabled"] is False
