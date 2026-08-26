"""ADR-132 tests: the span index, and the two defects it caught in its own build.

The module is load-bearing in an unusual way: it decides what the model is
allowed to cite, and if its units do not rejoin to the source it would be
quietly misrepresenting the filing. So the properties asserted here are
behavioural — losslessness over the real calibration corpus, offset round-trip,
digest agreement — rather than the shape of the config.

Two real defects are pinned as regressions. The abbreviation lookbehinds were
first written before the terminator, where they suppress nothing; and the
boundary pattern first consumed trailing quotation characters, dropping them
from the units. Both were caught by guards in the module rather than by review,
and both have a test here that fails if the guard is removed.
"""

from __future__ import annotations

import json
import re
import sys
from hashlib import sha256
from pathlib import Path

import pytest
import yaml

from dynamic_ai_products import classifier_span_index as csi
from dynamic_ai_products.classifier_contract_set import V2_5

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import (  # noqa: E402
    ROOT,
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
)

CONFIG = ROOT / "configs/universe_classifier_span_index_v1.yaml"


@pytest.fixture(scope="module")
def rules():
    return csi.load_span_index_rules(ROOT)


def _packet(cohort, index=0):
    return cohort.packets[index]


# --- the pinned config ---------------------------------------------------------------


def test_the_config_is_the_one_the_contract_set_names(rules):
    assert V2_5.span_index_config == "configs/universe_classifier_span_index_v1.yaml"
    assert V2_5.evidence_protocol == "selected_span"
    assert rules.version == "universe_classifier_span_index_v1"
    assert rules.sha256 == sha256(CONFIG.read_bytes()).hexdigest()


def test_every_v2_5_contract_pins_this_exact_config(rules):
    for stem in ("universe_classifier_authorization",
                 "universe_classifier_continuation_authorization",
                 "universe_classifier_calibration_authorization",
                 "universe_classifier_manifest",
                 "universe_classifier_continuation_manifest",
                 "universe_classifier_calibration_manifest"):
        props = json.loads((ROOT / f"schemas/{stem}.v5.schema.json")
                           .read_text(encoding="utf-8"))["properties"]
        assert props["span_index_version"]["const"] == rules.version, stem
        assert props["span_index_sha256"]["const"] == rules.sha256, stem


def test_the_declared_bounds_match_the_record_contract(rules):
    """The config repeats the 2000 ceiling; the two must not drift."""
    record = json.loads((ROOT / V2_5.record_schema).read_text(encoding="utf-8"))
    stored = record["properties"]["axes"]["oneOf"][1]["properties"]["evidence"]["items"]
    assert stored["properties"]["resolved_quote"]["maxLength"] == \
        rules.max_resolved_characters == 2000


# --- the abbreviation regression -----------------------------------------------------


@pytest.mark.parametrize("abbreviation", [
    "No", "Inc", "Corp", "Ltd", "Co", "U.S", "Mr", "Ms", "Dr", "St"])
def test_each_declared_abbreviation_is_actually_suppressed(rules, abbreviation):
    """The first pattern written for ADR-132 suppressed none of these.

    Its lookbehinds were spelled ``(?<!\\bInc)`` and applied at the position
    after the terminator, where the preceding characters are ``nc.`` rather than
    ``Inc``. The module's loader probes every declared abbreviation for exactly
    this reason.
    """
    normalized, units = csi.segment_units(
        f"Alpha {abbreviation}. Beta gamma delta.", rules)
    assert len(units) == 1, units


def test_the_loader_refuses_a_pattern_that_ignores_its_own_abbreviations(tmp_path):
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config["sentence_boundary"]["pattern"] = r"(?<=[.!?])\s+"
    broken = tmp_path / "configs"
    broken.mkdir()
    (broken / "universe_classifier_span_index_v1.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(csi.SpanIndexError, match="declared abbreviation"):
        csi.load_span_index_rules(tmp_path)


# --- the losslessness regression ------------------------------------------------------


@pytest.mark.parametrize("text", [
    'He said "yes." Then he left.',
    "Alpha ends. ● Bullet one. ● Bullet two.",
    "Revenue rose 12.5 percent overall.",
    "Inc. stays. U.S. stays too. Next sentence begins.",
    "Trailing paren (like this.) And a new one.",
    "Question? Answer! Statement.",
])
def test_segmentation_is_lossless_on_punctuation_shapes(rules, text):
    """The first pattern consumed trailing quotes, dropping them from the units."""
    normalized, units = csi.segment_units(text, rules)
    assert " ".join(units) == normalized


def test_the_module_refuses_a_lossy_segmentation(rules, monkeypatch):
    lossy = csi.SpanIndexRules(
        version=rules.version, sha256=rules.sha256,
        pattern=r"[.!?]\s+", abbreviations=rules.abbreviations,
        ordinal_width=3, max_units_per_passage=rules.max_units_per_passage,
        max_resolved_characters=rules.max_resolved_characters)
    with pytest.raises(csi.SpanIndexError, match="not lossless"):
        csi.segment_units("Alpha ends here. Beta begins here.", lossy)


# --- structural cases -----------------------------------------------------------------


def test_an_empty_passage_contributes_no_units(rules):
    assert csi.segment_units("   \n\t ", rules) == ("", ())


def test_a_passage_with_no_boundary_is_one_unit(rules):
    normalized, units = csi.segment_units("One clause with no terminator", rules)
    assert units == ("One clause with no terminator",)
    assert " ".join(units) == normalized


def test_segmentation_is_deterministic(rules, cohort):
    packet = _packet(cohort)
    first = csi.build_span_index(packet, rules)
    second = csi.build_span_index(packet, rules)
    for ref, spans in first.passages.items():
        assert spans.units == second.passages[ref].units
        assert spans.offsets == second.passages[ref].offsets


def test_a_passage_needing_four_digit_ordinals_is_refused(rules, cohort):
    packet = dict(_packet(cohort))
    body = " ".join(f"Sentence number {n} ends here." for n in range(1, 1201))
    packet["passages"] = [dict(packet["passages"][0], text=body)]
    with pytest.raises(csi.SpanIndexError, match="three-digit ordinal"):
        csi.build_span_index(packet, rules)


def test_a_width_other_than_three_is_refused(tmp_path):
    config = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    config["ordinals"]["width"] = 4
    (tmp_path / "configs").mkdir()
    (tmp_path / "configs/universe_classifier_span_index_v1.yaml").write_text(
        yaml.safe_dump(config), encoding="utf-8")
    with pytest.raises(csi.SpanIndexError, match="three-digit ordinals"):
        csi.load_span_index_rules(tmp_path)


# --- offsets, digests and resolution ---------------------------------------------------


def test_offsets_round_trip_for_every_unit(rules, cohort):
    index = csi.build_span_index(_packet(cohort), rules)
    for spans in index.passages.values():
        assert " ".join(spans.units) == spans.normalized
        for (start, end), unit in zip(spans.offsets, spans.units):
            assert spans.normalized[start:end] == unit


def test_a_single_span_resolves_to_its_own_unit(rules, cohort):
    index = csi.build_span_index(_packet(cohort), rules)
    ref = sorted(index.passages)[0]
    spans = index.passages[ref]
    resolved = csi.resolve_span(f"{ref}:S001", ref, index)
    assert resolved.text == spans.units[0]
    assert resolved.start == 0 and resolved.end == len(spans.units[0])
    assert resolved.sha256 == sha256(resolved.text.encode("utf-8")).hexdigest()


def test_a_range_resolves_to_the_contiguous_run(rules, cohort):
    index = csi.build_span_index(_packet(cohort), rules)
    ref = next(r for r, s in index.passages.items() if len(s.units) >= 3)
    spans = index.passages[ref]
    resolved = csi.resolve_span(f"{ref}:S001-S003", ref, index)
    assert resolved.text == " ".join(spans.units[:3])
    assert spans.normalized[resolved.start:resolved.end] == resolved.text


def test_verify_stored_span_accepts_a_stored_item_and_rejects_a_tampered_one(
        rules, cohort):
    """The archival verifier takes a packet, never a span index."""
    packet = _packet(cohort)
    index = csi.build_span_index(packet, rules)
    ref = sorted(index.passages)[0]
    resolved = csi.resolve_span(f"{ref}:S001", ref, index)
    item = {"passage_ref": ref, "resolved_quote": resolved.text,
            "span_start": resolved.start, "span_end": resolved.end,
            "span_sha256": resolved.sha256}
    assert csi.verify_stored_span(item, packet)
    assert not csi.verify_stored_span(
        {**item, "resolved_quote": item["resolved_quote"] + "!"}, packet)
    assert not csi.verify_stored_span({**item, "span_sha256": "0" * 64}, packet)
    assert not csi.verify_stored_span({**item, "span_end": item["span_end"] + 5},
                                      packet)
    assert not csi.verify_stored_span({**item, "span_start": item["span_end"]}, packet)
    assert not csi.verify_stored_span({**item, "passage_ref": "P999"}, packet)
    assert not csi.verify_stored_span({**item, "span_start": -1}, packet)
    assert not csi.verify_stored_span({k: v for k, v in item.items()
                                       if k != "span_sha256"}, packet)


def test_verify_stored_span_needs_no_span_ref_and_no_rules(rules, cohort, monkeypatch):
    """The archival proof is offsets and digest, not the model's reference.

    A stored item is verified with ``span_ref`` absent entirely, and with the
    module's own segmenter and config loader rigged to raise. Both are what an
    earlier revision of this module quietly depended on.
    """
    packet = _packet(cohort)
    index = csi.build_span_index(packet, rules)
    ref = sorted(index.passages)[0]
    resolved = csi.resolve_span(f"{ref}:S001", ref, index)
    item = {"passage_ref": ref, "resolved_quote": resolved.text,
            "span_start": resolved.start, "span_end": resolved.end,
            "span_sha256": resolved.sha256}
    assert "span_ref" not in item

    def _explode(*args, **kwargs):
        raise AssertionError("the archival path must not reach the segmenter")

    monkeypatch.setattr(csi, "build_span_index", _explode)
    monkeypatch.setattr(csi, "segment_units", _explode)
    monkeypatch.setattr(csi, "load_span_index_rules", _explode)
    assert csi.verify_stored_span(item, packet)


# --- refusals -------------------------------------------------------------------------


@pytest.mark.parametrize("span_ref", [
    "P001", "P001:S1", "S001", "P001:S001-", "P1:S001", "P001:S001-S002-S003",
    "p001:s001", "", "P001:S001 ", None, 7,
])
def test_a_malformed_span_ref_is_refused(rules, cohort, span_ref):
    index = csi.build_span_index(_packet(cohort), rules)
    with pytest.raises(csi.SpanSelectionError) as exc:
        csi.resolve_span(span_ref, "P001", index)
    assert exc.value.reason_code == "span_reference_unresolvable"


def test_an_undisplayed_passage_is_refused(rules, cohort):
    index = csi.build_span_index(_packet(cohort), rules)
    with pytest.raises(csi.SpanSelectionError, match="does not display") as exc:
        csi.resolve_span("P999:S001", "P999", index)
    assert exc.value.reason_code == "span_reference_unresolvable"


def test_an_out_of_range_ordinal_is_refused(rules, cohort):
    index = csi.build_span_index(_packet(cohort), rules)
    ref = sorted(index.passages)[0]
    beyond = len(index.passages[ref].units) + 1
    with pytest.raises(csi.SpanSelectionError, match="unit S") as exc:
        csi.resolve_span(f"{ref}:S{beyond:03d}", ref, index)
    assert exc.value.reason_code == "span_reference_unresolvable"


def test_a_zero_ordinal_is_refused(rules, cohort):
    index = csi.build_span_index(_packet(cohort), rules)
    ref = sorted(index.passages)[0]
    with pytest.raises(csi.SpanSelectionError, match="numbered from 1"):
        csi.resolve_span(f"{ref}:S000", ref, index)


def test_an_inverted_range_is_refused(rules, cohort):
    index = csi.build_span_index(_packet(cohort), rules)
    ref = next(r for r, s in index.passages.items() if len(s.units) >= 3)
    with pytest.raises(csi.SpanSelectionError, match="runs backwards"):
        csi.resolve_span(f"{ref}:S003-S001", ref, index)


def test_a_passage_ref_disagreeing_with_the_span_prefix_is_refused(rules, cohort):
    """Two references that name different passages is its own defect.

    It is kept distinct from naming an undisplayed passage because a reader
    deserves to know which of the two the model got wrong.
    """
    packet = next((p for p in cohort.packets if len(p["passages"]) >= 2), None)
    if packet is None:
        # Every fixture packet shows one passage; synthesise a second from the
        # first so the disagreement is still exercised on real passage shapes.
        base = _packet(cohort)
        packet = dict(base, passages=[base["passages"][0],
                                      dict(base["passages"][0],
                                           passage_id="second-passage-fixture")])
    index = csi.build_span_index(packet, rules)
    refs = sorted(index.passages)
    assert len(refs) >= 2
    with pytest.raises(csi.SpanSelectionError, match="disagree") as exc:
        csi.resolve_span(f"{refs[0]}:S001", refs[1], index)
    assert exc.value.reason_code == "span_reference_unresolvable"


def test_a_span_over_the_stored_bound_is_refused_not_truncated(rules, cohort):
    """A real, contiguous span the contract will not store. Truthful, not silent."""
    packet = dict(_packet(cohort))
    body = " ".join(f"Sentence {n} carries a long clause of filler text here."
                    for n in range(1, 60))
    packet["passages"] = [dict(packet["passages"][0], text=body)]
    index = csi.build_span_index(packet, rules)
    ref = sorted(index.passages)[0]
    last = len(index.passages[ref].units)
    with pytest.raises(csi.SpanSelectionError) as exc:
        csi.resolve_span(f"{ref}:S001-S{last:03d}", ref, index)
    assert exc.value.reason_code == "span_exceeds_stored_bound"
    assert "truncated" in exc.value.detail


# --- the real 40-packet corpus ---------------------------------------------------------


def test_losslessness_holds_over_every_fixture_packet(rules, cohort):
    passages = units = 0
    for packet in cohort.packets:
        index = csi.build_span_index(packet, rules)
        for spans in index.passages.values():
            passages += 1
            units += len(spans.units)
            assert " ".join(spans.units) == spans.normalized, spans.passage_ref
    assert passages and units


def test_rendering_adds_markers_and_nothing_else(rules, cohort):
    """Strip the markers, rejoin, and the filing's own text comes back."""
    index = csi.build_span_index(_packet(cohort), rules)
    for spans in index.passages.values():
        rendered = csi.render_passage_units(spans)
        stripped = [re.sub(r"^\[S[0-9]{3}\] ", "", line)
                    for line in rendered.split("\n")]
        assert " ".join(stripped) == spans.normalized
        assert len(stripped) == len(spans.units)
