"""ADR-129 tests: the instruction changed, the contract did not.

The V2.2 calibration stopped with three of four rows rejected, and a wider
ceiling would have rescued exactly one of them. The other two wrote quotes
instead of copying them, and one of those also put output JSON field names into
``evidence.axis``. Those are instruction failures, so these tests pin what the
V2.3 prompt now says and — just as importantly — that it says it while leaving
the 0.2.0 axes and record contracts, the taxonomy version and the 12/1200
ceilings exactly where V2.2 left them.
"""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from dynamic_ai_products import classifier_contract_set as ccs

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import ROOT  # noqa: E402

PROMPT = (ROOT / ccs.V2_3.prompt_path).read_text(encoding="utf-8")
V2_2_PROMPT = (ROOT / ccs.V2_2.prompt_path).read_text(encoding="utf-8")
#: Reflowed to single spaces so assertions test wording, not line wrapping.
FLAT = " ".join(PROMPT.split())
AXES = json.loads((ROOT / ccs.V2_3.axes_schema).read_text(encoding="utf-8"))

LEGAL_AXES = ["customer_value", "centrality", "dependency", "structure",
              "materiality", "eligibility"]
FORBIDDEN_AXIS_NAMES = ["software_centrality", "firm_structure",
                        "commercial_materiality", "complementary_dependencies",
                        "customer_value_archetypes", "customer_market_orientation"]


def _check() -> str:
    return " ".join(PROMPT.split("## Silent final check", 1)[1].split())


# --- successor identity ------------------------------------------------------------


def test_the_v2_3_prompt_is_a_successor_not_an_edit():
    assert PROMPT != V2_2_PROMPT
    assert "— v2.3" in PROMPT.splitlines()[0]
    assert sha256((ROOT / ccs.V2_2.prompt_path).read_bytes()).hexdigest() == \
        "bafa3a5b8800cd572e5bb454df1bc0693ffb2fce6f237ca6f31fa8674d228e6b"


def test_v2_3_changes_no_schema_limit():
    """The whole point: this successor is not another ceiling increase."""
    v2_2 = json.loads((ROOT / ccs.V2_2.axes_schema).read_text(encoding="utf-8"))
    assert ccs.V2_3.axes_schema == ccs.V2_2.axes_schema
    assert ccs.V2_3.record_schema == ccs.V2_2.record_schema
    assert ccs.V2_3.axes_contract == ccs.V2_2.axes_contract
    assert ccs.V2_3.record_contract == ccs.V2_2.record_contract
    assert ccs.V2_3.taxonomy_version == ccs.V2_2.taxonomy_version
    assert AXES == v2_2
    assert AXES["properties"]["evidence"]["maxItems"] == 12
    assert AXES["properties"]["evidence"]["items"]["properties"]["quote"][
        "maxLength"] == 1200


def test_the_declared_limits_still_match_the_unchanged_contract():
    limits = PROMPT.split("## Output size limits", 1)[1]
    assert "at most 12 objects" in limits
    assert "at most 1200 characters" in limits


# --- quoting is a copy operation ---------------------------------------------------


def test_the_prompt_states_quoting_as_a_copy_operation():
    assert "A quote is a copy operation, not a writing task." in FLAT
    assert "transcribing characters that are already in it" in FLAT


def test_the_ordered_copy_sequence_is_present_and_in_order():
    steps = [
        "Decide the one narrow claim this object will support.",
        "Locate a contiguous span, inside a single passage body, that proves that claim on its own.",
        "Select that span — its start and end characters.",
        "Copy it character for character into `quote`.",
        "Only then copy the `P`-reference from that same passage's header into `passage_ref`.",
        "Verify the copied quote occurs, exactly as copied, in that cited passage.",
    ]
    positions = []
    for step in steps:
        assert step in FLAT, step
        positions.append(FLAT.index(step))
    assert positions == sorted(positions), "the copy sequence is out of order"
    assert "If step 6 fails, you have written rather than copied." in FLAT


@pytest.mark.parametrize("prohibition", [
    "Never normalize, summarize, paraphrase, re-punctuate, expand an abbreviation, fix a typo, or tidy whitespace inside a quote.",
    "Never compose a quote from two sentences, two passages, or two separated spans, and never join spans with an ellipsis.",
    "Never truncate a span into something the claim no longer follows from.",
    "Never move a quote to a different `P`-reference.",
])
def test_each_transformation_is_forbidden(prohibition):
    assert prohibition in FLAT


def test_an_uncopyable_span_means_omission_not_approximation():
    assert "If no exact span can be copied, omit that evidence object." in FLAT
    assert "Set only the affected conclusion to unknown or null and add a concise boundary flag." in FLAT
    assert "An omitted object is correct; an approximated quote is not." in FLAT


# --- evidence is sparse ------------------------------------------------------------


def test_evidence_is_declared_a_sparse_support_set():
    assert "Evidence is a sparse support set" in PROMPT
    assert "Evidence is not a checklist and not a summary of the filing." in FLAT
    assert "Normally **one evidence object per axis you actually concluded on**." in FLAT
    assert "**At most two objects for any one axis**" in FLAT
    assert "only when a second, genuinely distinct claim is indispensable to that axis" in FLAT
    assert "An axis you left unknown or null needs no evidence object at all." in FLAT


def test_the_sparse_rule_is_arithmetically_consistent_with_the_cap():
    """Six axes at two objects each is exactly the unchanged 12-item ceiling."""
    axis_enum = AXES["properties"]["evidence"]["items"]["properties"]["axis"]["enum"]
    assert len(axis_enum) == 6
    assert len(axis_enum) * 2 == AXES["properties"]["evidence"]["maxItems"] == 12


# --- the legal axis labels ---------------------------------------------------------


def test_the_six_legal_axis_values_are_listed_literally():
    section = PROMPT.split("### The only legal `evidence.axis` values", 1)[1]
    flat = " ".join(section.split())
    for label in LEGAL_AXES:
        assert f"`{label}`" in flat, label
    assert AXES["properties"]["evidence"]["items"]["properties"]["axis"]["enum"] \
        == LEGAL_AXES


@pytest.mark.parametrize("field_name", FORBIDDEN_AXIS_NAMES)
def test_each_output_field_name_is_forbidden_as_an_axis(field_name):
    section = " ".join(
        PROMPT.split("### The only legal `evidence.axis` values", 1)[1].split())
    assert f"`{field_name}`" in section, field_name
    assert "Never put an output JSON field name in `evidence.axis`" in section


def test_the_prompt_explains_why_the_two_vocabularies_differ():
    section = " ".join(
        PROMPT.split("### The only legal `evidence.axis` values", 1)[1].split())
    assert "These are **axis labels, not output field names**." in section
    assert "The field names name where a *conclusion* goes; these six labels name which conclusion a piece of evidence supports." in section


# --- the final self-check ----------------------------------------------------------


@pytest.mark.parametrize("token", [
    "Every quote was copied, not written",
    "occurs character for character inside the passage its `passage_ref` cites",
    "each `passage_ref` was copied from the passage the span came from",
    "No quote was normalized, summarized, composed from two spans, truncated past its claim, or moved to another `P`-reference.",
    "Evidence is sparse: normally one object per concluded axis, never more than two for any one axis",
    "no object was added as a checklist entry",
    "no output JSON field name appears there",
    "Any claim without an exact copyable span was dropped",
    "`evidence` at most 12",
    "at most 1200 characters",
])
def test_the_final_check_restates_the_discipline(token):
    assert token in _check(), token


def test_the_final_check_lists_the_six_axis_labels():
    check = _check()
    for label in LEGAL_AXES:
        assert f"`{label}`" in check, label


def test_the_final_check_keeps_the_earlier_guarantees():
    check = _check()
    assert "No Tier was assigned." in check
    assert "The admission context did not substitute for the full Item 1 record." in check


# --- structure ---------------------------------------------------------------------


def test_every_renderer_placeholder_survives():
    from dynamic_ai_products import lineage_classifier_v2_1 as lcl
    for token in lcl._PLACEHOLDERS:
        assert PROMPT.count(token) == 1, token


def test_the_required_json_still_matches_the_axes_contract():
    block = re.search(r"## Required JSON\n\n```json\n(.*?)\n```", PROMPT, re.S)
    keys = re.findall(r'^\s{2}"([a-z_]+)"', block.group(1), re.M)
    assert sorted(keys) == sorted(AXES["required"])
    assert not [k for k in keys if "tier" in k]


def test_the_prompt_fences_are_balanced():
    assert PROMPT.count("```") % 2 == 0


def test_the_prompt_keeps_the_v2_2_guarantees():
    assert "Do not assign a Tier A/B/C label" in PROMPT
    assert "AI wording" in PROMPT
    assert "It is not authority for any classification result." in PROMPT
    assert "Market orientation is descriptive only." in PROMPT
