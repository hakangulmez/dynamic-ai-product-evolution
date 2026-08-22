"""ADR-123: the repair prompt strengthens evidence binding and nothing else.

The repair prompt exists because 570 of 574 unverified rows failed verbatim
quote resolution. It may therefore change how evidence is bound, and it may
change nothing else: a screening-criteria, vocabulary or archetype edit smuggled
in beside it would silently move what the screen measures, and the repair run's
recovery rate would no longer be attributable to the binding change.

These tests read both prompt files only. Nothing is rendered, no packet is
loaded and no model is called.
"""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_screen_live import ROOT  # noqa: E402

SCREEN_PATH = ROOT / "prompts/discovery/universe_high_recall_screen.v5.md"
REPAIR_PATH = ROOT / "prompts/discovery/universe_high_recall_screen_repair.v1.md"

#: The one section the repair prompt is permitted to change, plus the title.
CHANGED_SECTION = "Evidence identity and exact-copy binding"

#: Every other section must be byte-identical. Named explicitly rather than
#: derived, so deleting a section from the repair prompt fails this test.
PRESERVED_SECTIONS = (
    "Governing specification",
    "Role",
    "Temporal rule",
    "Do not infer eligibility from wording alone",
    "Customer-facing product test",
    "Candidate customer-value archetypes",
    "Input",
    "Required output",
    "Silent final check",
)


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sections(text: str) -> dict[str, str]:
    """Split a prompt into ``{heading: body}`` on its ``## `` headings."""
    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    out = {}
    for part in parts[1:]:
        heading, _, body = part.partition("\n")
        out[heading.strip()] = body
    return out


@pytest.fixture(scope="module")
def prompts():
    return _text(SCREEN_PATH), _text(REPAIR_PATH)


def test_the_screen_prompt_is_byte_identical():
    """The authoritative screen prompt is not touched by this ADR."""
    assert sha256(SCREEN_PATH.read_bytes()).hexdigest() == (
        "fee42d939f9eab590fdcbf055e7b2039e8a33a410dfc12257a47291d7a77d558")


def test_the_repair_prompt_is_a_distinct_committed_file(prompts):
    screen, repair = prompts
    assert REPAIR_PATH.is_file()
    assert screen != repair
    assert sha256(REPAIR_PATH.read_bytes()).hexdigest() != \
        sha256(SCREEN_PATH.read_bytes()).hexdigest()


def test_every_preserved_section_is_byte_identical(prompts):
    screen, repair = prompts
    a, b = _sections(screen), _sections(repair)
    assert set(a) == set(b), "the repair prompt adds or drops no section"
    for name in PRESERVED_SECTIONS:
        assert name in a, f"{name} is missing from the screen prompt"
        assert a[name] == b[name], f"section {name!r} drifted"


def test_only_the_evidence_binding_section_and_the_title_differ(prompts):
    screen, repair = prompts
    a, b = _sections(screen), _sections(repair)
    differing = sorted(name for name in a if a[name] != b[name])
    assert differing == [CHANGED_SECTION]
    # the title line is the only other permitted difference
    assert screen.splitlines()[0] != repair.splitlines()[0]
    assert repair.splitlines()[0].startswith("# High-recall software-universe screen")


def test_the_status_vocabulary_is_unchanged(prompts):
    screen, repair = prompts
    statuses = ("LIKELY_ELIGIBLE", "LIKELY_INELIGIBLE", "BOUNDARY_OR_UNCERTAIN")
    for status in statuses:
        assert screen.count(status) == repair.count(status), status
    # and no new status token appears
    tokens = set(re.findall(r"\b[A-Z][A-Z_]{4,}\b", repair))
    assert tokens == set(re.findall(r"\b[A-Z][A-Z_]{4,}\b", screen))


def test_the_closed_archetype_list_is_unchanged(prompts):
    screen, repair = prompts
    def archetypes(text: str) -> list[str]:
        section = _sections(text)["Candidate customer-value archetypes"]
        block = section.split("```text")[1].split("```")[0]
        return [line.strip() for line in block.splitlines() if line.strip()]
    listed = archetypes(screen)
    assert archetypes(repair) == listed, "order and membership both preserved"
    assert "HARDWARE_SOFTWARE_SYSTEM" in listed


def test_the_required_output_block_is_byte_identical(prompts):
    screen, repair = prompts
    def block(text: str) -> str:
        return _sections(text)["Required output"].split("```json")[1].split("```")[0]
    assert block(screen) == block(repair)
    fields = set(json.loads(block(screen).replace(
        '"LIKELY_ELIGIBLE | LIKELY_INELIGIBLE | BOUNDARY_OR_UNCERTAIN"', '"x"'
    ).replace('"high | medium | low"', '"x"')))
    assert fields == set(json.loads(block(repair).replace(
        '"LIKELY_ELIGIBLE | LIKELY_INELIGIBLE | BOUNDARY_OR_UNCERTAIN"', '"x"'
    ).replace('"high | medium | low"', '"x"')))


def test_the_repair_prompt_adds_only_binding_instructions(prompts):
    screen, repair = prompts
    added = [line for line in repair.splitlines() if line not in screen.splitlines()]
    # every added line lives in the evidence-binding section or is the title
    section = _sections(repair)[CHANGED_SECTION]
    for line in added:
        assert line in section or line.startswith("# High-recall"), line
    joined = "\n".join(added).lower()
    # it strengthens where the span comes from and how it is copied ...
    assert "contiguous" in joined
    assert "passage_ref" in joined
    # ... and says nothing about eligibility, status choice or archetypes
    for forbidden in ("eligible", "ineligible", "boundary", "archetype",
                      "confidence", "screen_status"):
        assert forbidden not in joined, f"{forbidden!r} appears in an added line"


def test_the_repair_prompt_never_mentions_a_previous_attempt(prompts):
    """The model must not learn that this row was screened before."""
    _, repair = prompts
    lowered = repair.lower()
    for forbidden in ("retry", "again", "previous", "earlier attempt",
                      "failed", "rejected", "repair", "your last",
                      "second attempt", "re-ask", "correct your"):
        assert forbidden not in lowered, f"{forbidden!r} leaks the retry identity"


def test_the_repair_prompt_keeps_the_same_placeholders(prompts):
    screen, repair = prompts
    pattern = re.compile(r"\{\{[a-z_]+\}\}")
    assert pattern.findall(screen) == pattern.findall(repair)
