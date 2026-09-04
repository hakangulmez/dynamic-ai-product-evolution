"""Text-only contract checks for the compact combined PCT snapshot draft.

The draft is not a schema, runner, qualification, or model call. These checks
only keep its narrow extraction boundary stable while later work decides
whether to create a governed execution route.
"""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "prompts" / "extraction" / "pct_item1_combined_snapshot_v1.md"
V2_PROMPT_PATH = ROOT / "prompts" / "extraction" / "pct_item1_combined_snapshot_v2.md"
V3_PROMPT_PATH = ROOT / "prompts" / "extraction" / "pct_item1_combined_snapshot_v3.md"
V4_PROMPT_PATH = ROOT / "prompts" / "extraction" / "pct_item1_combined_snapshot_v4.md"
V5_PROMPT_PATH = ROOT / "prompts" / "extraction" / "pct_item1_combined_snapshot_v5.md"
PROMPT_TEXT = PROMPT_PATH.read_text(encoding="utf-8")
NORMALIZED = re.sub(r"\s+", " ", PROMPT_TEXT)


def test_prompt_is_limited_to_the_archived_five_firm_smoke_route():
    assert "Status: development smoke draft" in PROMPT_TEXT
    assert "bounded, archived five-firm smoke route" in NORMALIZED
    assert "not qualified for a production run" in NORMALIZED


def test_prompt_asks_for_one_connected_product_capability_task_snapshot():
    assert "Read the whole Item 1 packet" in PROMPT_TEXT
    assert "**Products**" in PROMPT_TEXT
    assert "**Capabilities**" in PROMPT_TEXT
    assert "**Customer tasks**" in PROMPT_TEXT
    assert "verb + object + intended outcome" in PROMPT_TEXT


def test_product_family_is_optional_context_not_a_separate_model_entity():
    assert "`product_family` is optional context only" in PROMPT_TEXT
    assert "Do not create a standalone family record" in PROMPT_TEXT
    assert "Otherwise set it to `null`" in NORMALIZED


def test_evidence_is_address_only_and_model_never_writes_a_quote():
    assert "one to three `passage_refs`" in PROMPT_TEXT
    assert "do not write quotations, offsets, hashes, page numbers" in NORMALIZED
    assert "pipeline resolves and verifies evidence text separately" in NORMALIZED.lower()


def test_task_relationships_and_availability_are_explicit():
    assert "Every task belongs to exactly one product" in PROMPT_TEXT
    assert "zero or more of that product's capabilities" in NORMALIZED
    for token in (
        "announced", "private_beta", "public_beta", "general_availability",
        "broadly_deployed_or_default", "deprecated", "discontinued", "unknown",
    ):
        assert f"`{token}`" in PROMPT_TEXT


def test_prompt_excludes_later_scoring_and_does_not_name_any_real_firm():
    for token in (
        "scores", "tiers", "confidence", "revenue estimates", "materiality",
        "replicability", "defensibility", "AI-transition judgements",
    ):
        assert token in PROMPT_TEXT
    for firm in ("HubSpot", "Salesforce", "Netflix", "Arteris", "CEVA"):
        assert firm not in PROMPT_TEXT


def test_v2_adds_only_general_granularity_and_output_checks():
    text = V2_PROMPT_PATH.read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", text)
    assert "one consistent, non-overlapping commercial level" in normalized
    assert "Do not output both an umbrella offering" in normalized
    assert "Do not make a plan, edition, add-on, or delivery channel" in normalized
    assert "Merge tasks that have the same customer objective and deliverable" in normalized
    assert "no entry has more than three `passage_refs`" in normalized
    for firm in ("Adobe", "Salesforce", "Autodesk", "Cadence", "F5"):
        assert firm not in text


def test_v3_uses_product_family_only_as_optional_context():
    text = V3_PROMPT_PATH.read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", text)
    assert "Use `product_family` only as optional commercial context" in text
    assert "A family is not a separate product record" in text
    assert "explicitly names a suite, cloud, solution family" in normalized


def test_v3_replaces_detailed_tasks_with_durable_task_families():
    text = V3_PROMPT_PATH.read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", text)
    assert "**Task families**" in text
    assert "enduring customer outcomes or coherent workflows" in normalized
    assert "Merge interface steps, delivery channels, formats" in normalized
    assert "task families `TF1`, `TF2`" in normalized
    for firm in ("Adobe", "Salesforce", "Autodesk", "Cadence", "F5"):
        assert firm not in text


def test_v4_makes_product_families_explicit_without_turning_them_into_products():
    text = V4_PROMPT_PATH.read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", text)
    assert "**Product families**" in text
    assert "A family groups products; it is not itself a product" in normalized
    assert "`product_family_id`" in text
    assert "families `F1`, `F2`" in normalized


def test_v4_uses_tasks_not_task_families_and_keeps_the_boundary_compact():
    text = V4_PROMPT_PATH.read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", text)
    assert "**Customer tasks**" in text
    assert "A task states the customer job as `verb + object + intended outcome`" in normalized
    assert "Merge adjacent steps, channels, formats" in normalized
    assert "task families" not in text.lower()


def test_v5_combines_explicit_product_families_with_task_families():
    text = V5_PROMPT_PATH.read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", text)
    assert "**Product families**" in text
    assert "**Task families**" in text
    assert "A family groups products; it is not itself a product" in normalized
    assert "durable customer outcomes or coherent workflows" in normalized
    assert "task families `TF1`, `TF2`" in normalized
