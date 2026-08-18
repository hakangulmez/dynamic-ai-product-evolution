"""Tests for the ``pct_candidate_extraction_dev30_v1`` development-draft
prompt.

Text-only checks against the committed prompt file. No prompt is run, no
model is called, no gold label is created, and no holdout row is inspected
-- this module reads one markdown file and the already-committed cohort
manifest (ticker list only, not filing text) and asserts things about their
content.

Substring checks run against a whitespace-normalized copy of the prompt
text (`_NORMALIZED`) so that a mid-sentence line wrap in the markdown source
cannot make an otherwise-present phrase look absent.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "prompts" / "extraction" / "pct_candidate_extraction_dev30_v1.md"

PROMPT_TEXT = PROMPT_PATH.read_text(encoding="utf-8")
_NORMALIZED = re.sub(r"\s+", " ", PROMPT_TEXT)

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)

MANIFEST = json.loads(
    (ROOT / "evals" / "registries" / "pct_dev30_v0_manifest.json").read_text(encoding="utf-8")
)
ALL_DEV30_TICKERS = sorted(row["ticker"] for row in MANIFEST["rows"])
assert len(ALL_DEV30_TICKERS) == 30  # 24 visible + 6 holdout, checked without opening any row's text

# Real full company names for the 30 Dev30 tickers. Checked case-insensitively
# as plain substrings; ticker symbols are checked separately as case-sensitive
# whole words (see test_no_real_dev30_ticker_appears_as_a_standalone_token),
# since several tickers (e.g. NOW, NET) collide with ordinary English words
# and only a case-sensitive, word-boundary check on the literal ticker avoids
# false positives against normal prose.
REAL_DEV30_COMPANY_NAMES = [
    "Asana", "Spotify", "HubSpot", "Salesforce", "Workday", "Intuit", "ServiceNow",
    "Boomi", "AppFolio", "Cloudflare", "Datadog", "CrowdStrike", "Zscaler", "MongoDB",
    "DigitalOcean", "PagerDuty", "Verisk", "MSCI", "CoStar", "FactSet", "Duolingo",
    "Chegg", "Roku", "Yelp", "Axon", "Samsara", "Marqeta", "Clarivate", "Palantir",
    "UiPath",
]

# Field-name-shaped tokens for every forbidden output category (SPEC item 13).
# Checked only against the fenced JSON example blocks -- the actual output
# contract shown to the model -- not against the surrounding prose, which is
# expected to name these categories precisely because it prohibits them.
FORBIDDEN_OUTPUT_TOKENS = (
    "confidence", "uncertainty", "task_role", "screening", "classification",
    "replicability", "defensibility", "deployment_scale", "ai_adoption",
    "financial",
)


def _core_word_count(text: str) -> int:
    """Whitespace-split word count with fenced code blocks removed -- the
    illustrative JSON is reference material, not prompt prose."""
    return len(_FENCE_RE.sub(" ", text).split())


def _code_block_text(text: str) -> str:
    return " ".join(m.group(0) for m in _FENCE_RE.finditer(text))


def test_prompt_file_exists_at_the_exact_path():
    assert PROMPT_PATH.is_file()
    assert PROMPT_PATH == ROOT / "prompts" / "extraction" / "pct_candidate_extraction_dev30_v1.md"


def test_prompt_declares_the_exact_contract_and_schema_version_literals():
    assert "pct_dev30_v0_model_output@0.2.0" in PROMPT_TEXT
    assert '"schema_version": "0.2.0"' in PROMPT_TEXT
    assert PROMPT_TEXT.count("pct_dev30_v0_model_output@0.2.0") >= 2  # header + JSON example
    assert "# pct_candidate_extraction_dev30_v1" in PROMPT_TEXT


def test_prompt_never_names_the_v01_or_other_contract_versions():
    assert "pct_dev30_v0_model_output@0.1.0" not in PROMPT_TEXT
    assert "pct_dev30_v0_persisted_candidates" not in PROMPT_TEXT  # a Stage-2, adapter-only contract


def test_prompt_is_marked_development_draft_not_authorized_for_a_model_call():
    assert "development draft" in PROMPT_TEXT.lower()
    assert "not authorized" in PROMPT_TEXT.lower() or "not authorized for any model call" in PROMPT_TEXT.lower()
    assert "ADR-100" in PROMPT_TEXT


def test_no_offset_or_char_position_fields_are_requested():
    assert "char_start" not in PROMPT_TEXT
    assert "char_end" not in PROMPT_TEXT
    assert "do not report a character offset" in PROMPT_TEXT.lower()


def test_model_echoes_legacy_source_id_and_never_invents_one():
    assert "Copy `legacy_source_id`" in PROMPT_TEXT
    assert "Never invent, guess, reformat" in _NORMALIZED
    assert "do not select, fetch, or infer" in PROMPT_TEXT.lower()


def test_strict_json_only_output_is_directed():
    assert "Exactly one JSON object and nothing else" in PROMPT_TEXT
    assert "no code fence" in _NORMALIZED.lower()
    assert "no markdown formatting" in _NORMALIZED.lower()


def test_extraction_is_not_limited_to_ai_labelled_content():
    assert "not only ones described with AI-related" in _NORMALIZED
    assert "ordinary, non-AI offerings are just as in scope" in _NORMALIZED


def test_local_id_scheme_and_ordering_are_specified():
    for token in ("`P1`", "`P2`", "`C1`", "`C2`", "`T1`", "`T2`"):
        assert token in PROMPT_TEXT
    assert "every product\nfirst, then every capability, then every task" in PROMPT_TEXT or (
        "every product first, then every capability, then every task" in _NORMALIZED
    )


def test_ontology_definitions_are_present():
    for term in (
        "**Product**", "**Capability**", "**Task**", "`customer_need`",
        "`product_family`", "verb + object + intended outcome",
    ):
        assert term in PROMPT_TEXT


def test_capability_definition_excludes_marketing_strategy_ui_and_internal_tech():
    for phrase in (
        "generic marketing language", "company strategy",
        "a single interface click", "internal technology",
    ):
        assert phrase in _NORMALIZED


def test_task_definition_requires_one_product_link_and_zero_or_more_capability_links():
    assert "links to exactly one product and to zero or more capabilities" in _NORMALIZED


def test_granularity_rule_forbids_splitting_synonyms_channels_formats_and_ui_steps():
    for phrase in ("synonyms", "delivery\nchannels", "delivery channels", "file formats", "individual UI steps"):
        if phrase in PROMPT_TEXT or phrase in _NORMALIZED:
            continue
        raise AssertionError(phrase)
    assert "materially different" in _NORMALIZED


def test_evidence_quote_rule_requires_exact_contiguous_verbatim_text_with_context():
    assert "exact, contiguous, verbatim" in _NORMALIZED
    assert "not a paraphrase" in _NORMALIZED
    assert "enough surrounding context" in _NORMALIZED


def test_availability_uses_exactly_the_eight_contract_tokens():
    tokens = (
        "announced", "private_beta", "public_beta", "general_availability",
        "broadly_deployed_or_default", "deprecated", "discontinued", "unknown",
    )
    for token in tokens:
        assert f"`{token}`" in PROMPT_TEXT
    assert "Never default to `general_availability` from present-tense wording alone" in PROMPT_TEXT
    assert "Roadmap or beta language is still a full candidate" in PROMPT_TEXT


def test_excluded_mentions_rule_is_optional_non_exhaustive_and_closed_enum():
    assert "is optional and does not need to cover every passage" in _NORMALIZED
    for reason in (
        "internal_use", "vague_ai_marketing", "not_customer_facing", "insufficient_specificity",
    ):
        assert f"`{reason}`" in PROMPT_TEXT


def test_zero_candidate_reason_rule_is_present_and_closed():
    assert "no_product_capability_or_task_evidence" in PROMPT_TEXT
    assert "all_mentions_excluded" in PROMPT_TEXT
    assert "`zero_candidate_reason`\nis `null`" in PROMPT_TEXT or "is `null`." in PROMPT_TEXT


def test_forbidden_output_categories_are_all_named_in_the_prohibition_section():
    assert "## What you never output" in PROMPT_TEXT
    section = _NORMALIZED.split("## What you never output", 1)[1]
    section = section.split("## Zero candidates", 1)[0]
    for phrase in (
        "score", "confidence", "uncertainty", "task role",
        "screening or classification decision", "replicability judgment",
        "defensibility judgment", "deployment-scale estimate", "AI-adoption metric",
        "financial figure or claim", "comparison to any period after",
    ):
        assert phrase in section, phrase


def test_forbidden_output_tokens_absent_from_the_actual_json_output_contract():
    """The prohibition prose is allowed (expected) to name these categories;
    the JSON shape shown to the model as its actual output target must not
    contain a field for any of them."""
    code_text = _code_block_text(PROMPT_TEXT)
    for token in FORBIDDEN_OUTPUT_TOKENS:
        assert token not in code_text, token


def test_word_count_guard_is_within_1000_to_1500_core_words():
    count = _core_word_count(PROMPT_TEXT)
    assert 1000 <= count <= 1500, count


def test_no_real_dev30_ticker_appears_as_a_standalone_token():
    for ticker in ALL_DEV30_TICKERS:
        pattern = re.compile(r"\b" + re.escape(ticker) + r"\b")
        assert not pattern.search(PROMPT_TEXT), ticker


def test_no_real_dev30_company_name_appears():
    lowered = PROMPT_TEXT.lower()
    for name in REAL_DEV30_COMPANY_NAMES:
        assert name.lower() not in lowered, name


def test_example_company_is_fictional_and_distinct_from_the_cohort():
    assert "Northwind" in PROMPT_TEXT
    assert "Northwind" not in REAL_DEV30_COMPANY_NAMES


def test_no_firm_specific_or_historical_exception_language():
    for phrase in ("Breeze", "professional services", "historically", "in the prior release"):
        assert phrase not in PROMPT_TEXT
