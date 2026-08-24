"""ADR-126 tests: the prompt asks for axes, and the renderer leaks nothing.

The prompt is a governed artifact: its bytes are pinned by every authorization,
so a change to it is a change to the run's identity. These tests pin the
properties the rest of the pipeline depends on — that the model is never asked
for a tier, that the admission context is presented as contestable rather than
authoritative, and that the declared output limits are the same limits the axes
schema enforces.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

from dynamic_ai_products import lineage_classifier_v2_1 as lcl

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import (  # noqa: E402
    ROOT,
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
)

PROMPT_PATH = ROOT / lcl.PROMPT_PATH
PROMPT = PROMPT_PATH.read_text(encoding="utf-8")
AXES_SCHEMA = json.loads(
    (ROOT / lcl.AXES_SCHEMA).read_text(encoding="utf-8"))


def _required_json_block() -> dict:
    block = re.search(r"## Required JSON\n\n```json\n(.*?)\n```", PROMPT, re.S)
    assert block, "the prompt no longer carries one fenced Required JSON block"
    return block.group(1)


def _admission(origin, status, evidence):
    return {"cohort_id": "cohort-fixture", "admission_origin": origin,
            "admitted_status": status, "non_authoritative": True,
            "context_evidence": evidence, "model_screen": None,
            "human_review": None}


# --- what the prompt asks for ------------------------------------------------------


def test_every_placeholder_the_renderer_substitutes_appears_exactly_once():
    for token in lcl._PLACEHOLDERS:
        assert PROMPT.count(token) == 1, token


def test_the_required_json_names_no_tier_field():
    body = _required_json_block()
    parsed_keys = re.findall(r'^\s{2}"([a-z_]+)"', body, re.M)
    assert parsed_keys, "the Required JSON block has no top-level keys"
    assert not [k for k in parsed_keys if "tier" in k]
    assert sorted(parsed_keys) == sorted(AXES_SCHEMA["required"]), (
        "the prompt's Required JSON and the axes contract have diverged")


def test_the_axes_contract_itself_carries_no_tier_field():
    assert not [k for k in AXES_SCHEMA["properties"] if "tier" in k]


def test_the_prompt_forbids_assigning_a_tier():
    assert "Do not assign a Tier A/B/C label" in PROMPT
    assert "No Tier was assigned." in PROMPT


def test_the_admission_context_is_presented_as_contestable():
    assert "It is not authority for any classification result." in PROMPT
    assert "non_authoritative: true" in PROMPT
    for phrase in ("defer to the reviewer", "trust the earlier",
                   "confirm the admission"):
        assert phrase not in PROMPT


def test_the_prompt_forbids_inference_from_ai_wording():
    assert "AI wording" in PROMPT
    assert "current company knowledge" in PROMPT


def test_market_orientation_is_declared_descriptive():
    assert "Market orientation is descriptive only." in PROMPT


def test_the_declared_output_limits_match_the_axes_contract():
    limits = PROMPT.split("## Output size limits", 1)[1]
    properties = AXES_SCHEMA["properties"]
    for field, declared in (("customer_value_archetypes", 4),
                            ("complementary_dependencies", 5),
                            ("evidence", 6),
                            ("boundary_flags", 4),
                            ("contradictions", 4)):
        assert properties[field]["maxItems"] == declared, field
        assert str(declared) in limits
    quote = properties["evidence"]["items"]["properties"]["quote"]
    claim = properties["evidence"]["items"]["properties"]["supported_claim"]
    assert quote["maxLength"] == 300 and "300" in limits
    assert claim["maxLength"] == 200 and "200" in limits


def test_the_prompt_fences_are_balanced():
    assert PROMPT.count("```") % 2 == 0


def test_the_prompt_is_a_successor_and_not_an_edit():
    predecessor = ROOT / "prompts/discovery/universe_full_classification.md"
    assert predecessor.is_file()
    assert predecessor.read_bytes() != PROMPT_PATH.read_bytes()


# --- what the renderer produces ----------------------------------------------------


def test_the_renderer_substitutes_every_placeholder(cohort):
    packet = cohort.packets[0]
    rendered, refs = lcl.render_classifier_prompt(
        PROMPT, packet, _admission("model_screen", "LIKELY_ELIGIBLE", []))
    assert "{{" not in rendered and "}}" not in rendered
    assert refs and set(refs) == {f"P{i + 1:03d}"
                                  for i in range(len(packet["passages"]))}


def test_the_renderer_supplies_the_complete_packet(cohort):
    packet = cohort.packets[0]
    rendered, refs = lcl.render_classifier_prompt(
        PROMPT, packet, _admission("human_review", "BOUNDARY_OR_UNCERTAIN", []))
    for ref, passage in zip(sorted(refs), packet["passages"]):
        assert f"[passage_ref={ref} section={passage['section']}]" in rendered
        assert passage["text"] in rendered


def _substituted(rendered: str) -> str:
    """Only the region the renderer wrote, never the static instructions."""
    return rendered.split("BASELINE_CUTOFF:", 1)[1].split("```", 1)[0]


def test_the_renderer_leaks_no_identifier_the_model_must_not_see(cohort):
    packet = cohort.packets[0]
    rendered, _ = lcl.render_classifier_prompt(
        PROMPT, packet, _admission("model_screen", "LIKELY_ELIGIBLE", []))
    written = _substituted(rendered)
    assert packet["packet_sha256"] not in written
    for passage in packet["passages"]:
        assert passage["passage_id"] not in written
    for leak in ("passage_id", "raw_response", "overlay_id", "reviewer",
                 "sha256", lcl.PROMPT_PATH):
        assert leak not in written


def test_the_two_origins_render_different_context(cohort):
    packet = cohort.packets[0]
    quote = packet["passages"][0]["text"][:40]
    evidence = [{"passage_ref": "P001", "quote": quote}]
    screened, _ = lcl.render_classifier_prompt(
        PROMPT, packet, _admission("model_screen", "LIKELY_ELIGIBLE", evidence))
    reviewed, _ = lcl.render_classifier_prompt(
        PROMPT, packet,
        _admission("human_review", "BOUNDARY_OR_UNCERTAIN", evidence))
    assert "origin: model_screen" in screened
    assert "Earlier screen context:" in screened
    assert "origin: human_review" in reviewed
    assert "Earlier human-review context:" in reviewed
    assert "admitted_status: BOUNDARY_OR_UNCERTAIN" in reviewed
    assert f'- P001: "{quote}"' in screened


def test_an_admission_without_evidence_says_so(cohort):
    rendered, _ = lcl.render_classifier_prompt(
        PROMPT, cohort.packets[0],
        _admission("model_screen", "LIKELY_ELIGIBLE", []))
    assert "(no displayed evidence was recorded for this admission)" in rendered


def test_a_template_missing_a_placeholder_is_refused(cohort):
    from dynamic_ai_products.universe.lineage_screen import ScreenInputError
    broken = PROMPT.replace(lcl._PLACEHOLDERS[-1], "")
    with pytest.raises(ScreenInputError, match="missing placeholder"):
        lcl.render_classifier_prompt(
            broken, cohort.packets[0],
            _admission("model_screen", "LIKELY_ELIGIBLE", []))
