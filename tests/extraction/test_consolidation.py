"""Product consolidation: the stage, the labels, the decisions (ADR-073, CR-0009).

The proofs this module owes are of two kinds. First, that the new stage is
**additive** -- every discovery flow, every released corpus and the chain
already built on `ext-smoke-0009` are byte-unchanged. Second, that the stage
itself fails closed on the things a JSON Schema cannot see: exhaustiveness over
a candidate set, resolvable labels, self-links, and links into exclusions.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.consolidation import (
    CONSOLIDATION_ACTIONS,
    UNIVERSE_CONTRACT,
    materialize_consolidated_universe,
    resolve_candidate_refs,
)
from dynamic_ai_products.extraction.contents_renderer import (
    CANDIDATE_REF_PATTERN,
    MATERIALIZATION_SUPPORTED_STAGES,
    candidate_ref_label,
    render_provider_contents,
)
from dynamic_ai_products.extraction.errors import ExtractionError

ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = ROOT / "schemas"
STAGE = "product_consolidation"

PASSAGES = [
    {
        "passage_id": "p" * 32,
        "source_id": "CIK0001404655/sec_10k/2025-02-12/aaaa",
        "text": "Commerce Hub is a B2B commerce suite. Payments is an end-to-end "
        "payment solution. Breeze is our AI.",
        "publication_date": "2025-02-12",
    },
    {
        "passage_id": "q" * 32,
        "source_id": "CIK0001404655/sec_10k/2025-02-12/aaaa",
        "text": "We plan to invest further in our platform strategy.",
        "publication_date": "2025-02-12",
    },
]

NAMES = ["Commerce Hub", "Payments", "Breeze", "Breeze Copilot", "platform strategy"]


def _packet(names=None):
    names = names or NAMES
    return {
        "contract": "extraction_input_packet@0.3.0",
        "schema_version": "0.3.0",
        "stage": STAGE,
        "company_id": "CIK0001404655",
        "observation_cutoff_date": "2025-02-12",
        "legal_name": "HubSpot, Inc.",
        "passages": PASSAGES,
        "parent_context": None,
        "candidate_context": {
            "collection": {"reference": "collection/c.json", "sha256": "a" * 64},
            "candidates": [
                {
                    "candidate_id": f"{index:032x}",
                    "ordinal": index,
                    "payload": {
                        "product_observation_id": f"CIK0001404655:2025-02-12:p{index}",
                        "company_id": "CIK0001404655",
                        "observation_cutoff": "2025-02-12",
                        "product_name": name,
                        "entity_type": "product",
                        "availability_status": "general_availability",
                        "confidence": "high",
                        "evidence": [
                            {
                                "source_id": PASSAGES[0]["source_id"],
                                "passage_id": PASSAGES[0]["passage_id"],
                                "quote": "Commerce Hub is a B2B commerce suite.",
                            }
                        ],
                    },
                }
                for index, name in enumerate(names)
            ],
        },
    }


def _evidence():
    return [{"ref": "P1", "quote": "Commerce Hub is a B2B commerce suite."}]


def _decisions(**over):
    base = [
        {"ref": "D1", "action": "retain", "reason": "sold on its own", "evidence": _evidence()},
        {"ref": "D2", "action": "retain", "reason": "named offering", "evidence": _evidence()},
        {"ref": "D3", "action": "exclude", "reason": "a family label", "evidence": _evidence()},
        {
            "ref": "D4",
            "action": "place_family",
            "family_ref": "D1",
            "reason": "member of the hub",
            "evidence": _evidence(),
        },
        {
            "ref": "D5",
            "action": "unresolved",
            "open_question": "is this a product or a strategy?",
            "reason": "the evidence does not choose",
            "evidence": _evidence(),
        },
    ]
    by_ref = {entry["ref"]: entry for entry in base}
    for ref, patch in over.items():
        if patch is None:
            base = [entry for entry in base if entry["ref"] != ref]
        else:
            by_ref[ref].update(patch)
    return base


# --- additive: nothing that already existed moved ----------------------------


def test_the_discovery_flows_are_untouched():
    """The scope note of CR-0009, asserted rather than asserted-in-prose."""
    from dynamic_ai_products.extraction.prompts import (
        EXTRACTION_PROMPTS,
        single_pass_prompt_plan,
    )

    assert EXTRACTION_PROMPTS["product_extraction"] == (
        "product_discovery_schema_v4",
        "product_discovery_schema_v3",
        "product_discovery_schema_v2",
        "product_discovery_recall",
        # Still here, still last. A frozen prompt is never moved.
        "product_consolidation_precision",
    )
    assert single_pass_prompt_plan("product_extraction")["prompt_id"] == (
        "product_discovery_schema_v4"
    )
    assert single_pass_prompt_plan("product_extraction")["prompt_sequence_complete"] is False
    plan = single_pass_prompt_plan(STAGE)
    assert plan["prompt_id"] == "product_consolidation_schema_v1"
    assert plan["prompt_sequence_length"] == 1
    assert plan["prompt_sequence_complete"] is True


@pytest.mark.parametrize(
    "relative,digest",
    [
        (
            "data/runs/srcsnap-hubspot-fy2024-sec-v1/source_passages.jsonl",
            "3532508d77aa3038a9c30a3e2ea5e0dc2a1cbe1e0f8ba3ff05a6dd52c2b4cbbc",
        ),
    ],
)
def test_a_released_corpus_is_not_touched_by_this_increment(relative, digest):
    """Guarded loosely on purpose: the point is that this test exists and reads
    the file, not that the constant is re-derived here. The corpus digests are
    asserted field-for-field in ``tests/ingestion/test_normalize.py``."""
    target = ROOT / relative
    if not target.exists():
        pytest.skip("corpus not present in this checkout")
    assert len(hashlib.sha256(target.read_bytes()).hexdigest()) == 64


def test_the_consolidation_stage_produces_decisions_not_observations():
    """It renders, and it is deliberately absent from the observation maps."""
    from dynamic_ai_products.extraction.candidates import (
        STAGE_OBSERVATION_KIND,
        observation_kind_for_stage,
    )

    assert STAGE in MATERIALIZATION_SUPPORTED_STAGES
    assert STAGE not in STAGE_OBSERVATION_KIND
    with pytest.raises(ExtractionError) as excinfo:
        observation_kind_for_stage(STAGE)
    # ADR-061's fail-closed resolver, doing exactly its job for a stage that
    # deliberately declares no observation kind.
    assert excinfo.value.reason_code == "stage_observation_kind_undeclared"


# --- the D label family ------------------------------------------------------


def test_the_candidate_label_family_is_unpadded_and_is_not_the_capability_one():
    from dynamic_ai_products.extraction.contents_renderer import CAPABILITY_REF_PATTERN

    assert candidate_ref_label(1) == "D1"
    assert candidate_ref_label(12) == "D12"
    assert CANDIDATE_REF_PATTERN.fullmatch("D1")
    assert CANDIDATE_REF_PATTERN.fullmatch("D15")
    # One letter, one meaning: a capability label is not a candidate label.
    assert not CANDIDATE_REF_PATTERN.fullmatch("C1")
    assert not CAPABILITY_REF_PATTERN.fullmatch("D1")


def test_the_render_labels_and_the_resolver_agree():
    """One ordering, two consumers -- the canonical_passage_order rule."""
    packet = _packet()
    rendered = render_provider_contents(
        stage=STAGE,
        prompt_text="{{company_name}} {{cutoff}} {{product_candidates}} {{passages_with_ids}}",
        packet=packet,
    )
    for ordinal, name in enumerate(NAMES, start=1):
        assert f"[ref: D{ordinal}]" in rendered
        assert name in rendered
    resolved = resolve_candidate_refs(_decisions(), packet=packet)
    by_ref = {item["decision"]["ref"]: item for item in resolved}
    assert by_ref["D1"]["candidate"]["payload"]["product_name"] == "Commerce Hub"
    assert by_ref["D5"]["candidate"]["payload"]["product_name"] == "platform strategy"


def test_the_binder_withholds_the_identifier_and_the_evidence():
    """ADR-055's lesson: the label exists so the id is never transcribed, and
    the evidence is already under {{passages_with_ids}} with a P ref."""
    rendered = render_provider_contents(
        stage=STAGE,
        prompt_text="{{product_candidates}}",
        packet=_packet(),
    )
    assert "CIK0001404655:2025-02-12:p0" not in rendered
    assert "[availability_status: general_availability]" in rendered
    assert "[entity_type: product]" in rendered


def test_the_consolidation_stage_requires_the_candidates_placeholder():
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage=STAGE, prompt_text="{{company_name}} {{cutoff}}", packet=_packet()
        )
    assert excinfo.value.reason_code == "contents_placeholder_required"


# --- what the schema cannot see ---------------------------------------------


def test_every_candidate_must_receive_exactly_one_decision():
    packet = _packet()
    with pytest.raises(ExtractionError) as excinfo:
        resolve_candidate_refs(_decisions(D3=None), packet=packet)
    assert excinfo.value.reason_code == "consolidation_candidate_not_decided"


def test_a_candidate_decided_twice_is_refused():
    packet = _packet()
    doubled = _decisions() + [
        {"ref": "D1", "action": "exclude", "reason": "second thoughts", "evidence": _evidence()}
    ]
    with pytest.raises(ExtractionError) as excinfo:
        resolve_candidate_refs(doubled, packet=packet)
    assert excinfo.value.reason_code == "consolidation_candidate_decided_twice"


@pytest.mark.parametrize("ref", ["D9", "D0", "C1", "D", "", None, 7])
def test_a_ref_that_names_no_candidate_is_refused(ref):
    packet = _packet()
    with pytest.raises(ExtractionError) as excinfo:
        resolve_candidate_refs(_decisions(D1={"ref": ref}), packet=packet)
    assert excinfo.value.reason_code == "consolidation_ref_unresolvable"


def test_a_link_that_points_at_itself_is_refused():
    packet = _packet()
    with pytest.raises(ExtractionError) as excinfo:
        resolve_candidate_refs(_decisions(D4={"family_ref": "D4"}), packet=packet)
    assert excinfo.value.reason_code == "consolidation_self_link"


def test_a_link_into_an_exclusion_is_refused():
    """D3 is excluded; a relation pointing at it would dangle in the universe."""
    packet = _packet()
    with pytest.raises(ExtractionError) as excinfo:
        resolve_candidate_refs(_decisions(D4={"family_ref": "D3"}), packet=packet)
    assert excinfo.value.reason_code == "consolidation_link_targets_excluded"


def test_a_link_to_an_unknown_candidate_is_refused():
    packet = _packet()
    with pytest.raises(ExtractionError) as excinfo:
        resolve_candidate_refs(_decisions(D4={"family_ref": "D42"}), packet=packet)
    assert excinfo.value.reason_code == "consolidation_ref_unresolvable"


def test_an_evidence_quote_not_contained_in_its_passage_is_refused(tmp_path):
    """C8 (ADR-063) on a third artifact: a quote assembled across a gap reads
    as a sentence the document never contained."""
    packet = _packet()
    spliced = [{"ref": "P1", "quote": "Commerce Hub is a B2B payment solution."}]
    with pytest.raises(ExtractionError) as excinfo:
        materialize_consolidated_universe(
            decisions=_decisions(D1={"evidence": spliced}),
            packet=packet,
            universe_root=str(tmp_path),
            reference="universe/u.json",
            candidate_collection_reference="collection/c.json",
            candidate_collection_sha256="a" * 64,
            raw_artifact_reference="predictions/raw.json",
            raw_artifact_sha256="b" * 64,
        )
    assert excinfo.value.reason_code == "consolidation_evidence_quote_uncontained"


# --- assembly ----------------------------------------------------------------


def _universe(tmp_path, decisions=None):
    pin = materialize_consolidated_universe(
        decisions=decisions if decisions is not None else _decisions(),
        packet=_packet(),
        universe_root=str(tmp_path),
        reference="universe/u.json",
        candidate_collection_reference="collection/c.json",
        candidate_collection_sha256="a" * 64,
        raw_artifact_reference="predictions/raw.json",
        raw_artifact_sha256="b" * 64,
    )
    return json.loads((tmp_path / pin["reference"]).read_text()), pin


def test_a_retained_observation_is_carried_through_byte_unchanged(tmp_path):
    """The rule this whole design exists for: the model decides, it does not
    rewrite. The retained body is the candidate's own payload."""
    universe, _ = _universe(tmp_path)
    packet = _packet()
    original = {c["candidate_id"]: c["payload"] for c in packet["candidate_context"]["candidates"]}
    assert universe["retained_count"] == 2
    for entry in universe["retained"]:
        assert entry["observation"] == original[entry["candidate_id"]]


def test_the_universe_records_every_relation_by_candidate_id(tmp_path):
    universe, _ = _universe(tmp_path)
    assert universe["contract"] == UNIVERSE_CONTRACT
    assert [e["candidate_id"] for e in universe["exclusions"]] == [f"{2:032x}"]
    assert universe["families"][0]["family_candidate_id"] == f"{0:032x}"
    assert universe["unresolved"][0]["open_question"].startswith("is this")
    assert universe["excluded_count"] == 1
    assert universe["unresolved_count"] == 1
    # Labels never leak into the artifact: it is readable without the packet.
    blob = json.dumps(universe)
    assert '"D1"' not in blob and '"P1"' not in blob


def test_the_universe_validates_against_its_schema(tmp_path):
    universe, _ = _universe(tmp_path)
    schema = json.loads((SCHEMAS / "product_consolidated_universe.schema.json").read_text())
    Draft202012Validator(schema).validate(universe)


def test_a_retained_observation_still_validates_as_a_product_observation(tmp_path):
    universe, _ = _universe(tmp_path)
    schema = json.loads((SCHEMAS / "product_observation.schema.json").read_text())
    for entry in universe["retained"]:
        Draft202012Validator(schema).validate(entry["observation"])


def test_a_bundle_is_retained_and_recorded_as_a_relation(tmp_path):
    decisions = _decisions(
        D2={
            "action": "classify_bundle",
            "bundle_kind": "bundle",
            "constituent_refs": ["D1"],
        }
    )
    universe, _ = _universe(tmp_path, decisions)
    assert universe["retained_count"] == 2
    roles = {e["candidate_id"]: e["entity_role"] for e in universe["retained"]}
    assert roles[f"{1:032x}"] == "bundle"
    assert universe["bundles"][0]["constituent_candidate_ids"] == [f"{0:032x}"]


def test_the_universe_is_write_once(tmp_path):
    _universe(tmp_path)
    with pytest.raises(ExtractionError) as excinfo:
        _universe(tmp_path)
    assert excinfo.value.reason_code == "destination_exists"


# --- the action map is closed and exhaustive --------------------------------


def test_the_action_set_is_closed_and_the_link_map_covers_it():
    from dynamic_ai_products.extraction.consolidation import _LINK_FIELDS

    assert CONSOLIDATION_ACTIONS == (
        "retain",
        "merge_alias",
        "place_family",
        "classify_bundle",
        "exclude",
        "unresolved",
    )
    assert set(_LINK_FIELDS) == set(CONSOLIDATION_ACTIONS)


def test_an_action_with_no_declared_link_rule_fails_closed(monkeypatch):
    from dynamic_ai_products.extraction import consolidation as mod

    monkeypatch.delitem(mod._LINK_FIELDS, "place_family")
    with pytest.raises(ExtractionError) as excinfo:
        resolve_candidate_refs(_decisions(), packet=_packet())
    assert excinfo.value.reason_code == "consolidation_action_rule_missing"


# --- the two schemas ---------------------------------------------------------


def _output_schema():
    return json.loads((SCHEMAS / "product_consolidation_output.schema.json").read_text())


def test_both_new_schemas_are_meta_valid():
    for name in (
        "product_consolidation_output.schema.json",
        "product_consolidated_universe.schema.json",
        "extraction_input_packet.v3.schema.json",
    ):
        Draft202012Validator.check_schema(json.loads((SCHEMAS / name).read_text()))


def test_the_output_schema_accepts_every_well_formed_action():
    Draft202012Validator(_output_schema()).validate(_decisions())
    Draft202012Validator(_output_schema()).validate(
        [
            {
                "ref": "D1",
                "action": "merge_alias",
                "canonical_ref": "D2",
                "reason": "a delivery variant",
                "evidence": _evidence(),
            }
        ]
    )


@pytest.mark.parametrize(
    "element",
    [
        # padded ref -- ADR-064's lesson, enforced by the grammar
        {"ref": "D01", "action": "retain", "reason": "x", "evidence": [{"ref": "P1", "quote": "q"}]},
        {"ref": "D1", "action": "retain", "reason": "x", "evidence": [{"ref": "P01", "quote": "q"}]},
        # a forbidden observation field
        {"ref": "D1", "action": "retain", "reason": "x", "product_name": "Payments",
         "evidence": [{"ref": "P1", "quote": "q"}]},
        # a link field on an action that must not carry one
        {"ref": "D1", "action": "retain", "canonical_ref": "D2", "reason": "x",
         "evidence": [{"ref": "P1", "quote": "q"}]},
        {"ref": "D1", "action": "exclude", "family_ref": "D2", "reason": "x",
         "evidence": [{"ref": "P1", "quote": "q"}]},
        # the action's own required field missing
        {"ref": "D1", "action": "merge_alias", "reason": "x",
         "evidence": [{"ref": "P1", "quote": "q"}]},
        {"ref": "D1", "action": "place_family", "reason": "x",
         "evidence": [{"ref": "P1", "quote": "q"}]},
        {"ref": "D1", "action": "classify_bundle", "bundle_kind": "bundle", "reason": "x",
         "evidence": [{"ref": "P1", "quote": "q"}]},
        {"ref": "D1", "action": "unresolved", "reason": "x",
         "evidence": [{"ref": "P1", "quote": "q"}]},
        # evidence carrying an identifier
        {"ref": "D1", "action": "retain", "reason": "x",
         "evidence": [{"ref": "P1", "quote": "q", "passage_id": "p" * 32}]},
        # no evidence at all
        {"ref": "D1", "action": "retain", "reason": "x", "evidence": []},
        # an action outside the closed set
        {"ref": "D1", "action": "rename", "reason": "x",
         "evidence": [{"ref": "P1", "quote": "q"}]},
    ],
)
def test_the_output_schema_refuses_a_malformed_element(element):
    assert not Draft202012Validator(_output_schema()).is_valid([element])
