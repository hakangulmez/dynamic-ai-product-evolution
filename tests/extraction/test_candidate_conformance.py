"""Derived identity, the parse gates, and the C1-C8 conformance gate (ADR-054, G6-M).

Offline throughout: no provider, no network, no run root is created by anything
here except the temporary ones these tests own.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.availability_vocabulary import (
    build_availability_vocabulary,
)
from dynamic_ai_products.extraction.candidates import (
    CANDIDATE_COLLECTION_REFERENCE,
    assert_candidate_conformance,
    build_candidate_collection,
    derive_identity_fields,
    materialize_candidate_collection,
    parse_model_observations,
    resolve_capability_refs,
    slugify_product_name,
)
from dynamic_ai_products.extraction.errors import ExtractionError

ROOT = Path(__file__).resolve().parents[2]
COMPANY = "CIK0001404655"
CUTOFF = "2025-02-12"
SRC, PSG = "src-0001", "psg-0001"


@pytest.fixture(scope="module")
def vocabulary() -> dict:
    return build_availability_vocabulary(
        vocabulary_version="product-candidate-availability-v1",
        active_status_values=[
            "broadly_deployed_or_default",
            "general_availability",
            "private_beta",
            "public_beta",
        ],
        roadmap_status_values=["announced"],
        non_active_known_status_values=["deprecated", "discontinued"],
        decided_by="test fixture",
        decided_at="2026-08-05T00:00:00+00:00",
        repo_root=ROOT,
    )


def packet(**over) -> dict:
    payload = {
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [{"source_id": SRC, "passage_id": PSG, "text": "x"}],
    }
    payload.update(over)
    return payload


def observation(**over) -> dict:
    payload = {
        "product_observation_id": "ignored-by-derivation",
        "company_id": "ignored",
        "observation_cutoff": "1999-01-01",
        "product_name": "Marketing Hub",
        "availability_status": "general_availability",
        "confidence": "high",
        "evidence": [{"source_id": SRC, "passage_id": PSG, "quote": "x"}],
    }
    payload.update(over)
    return {k: v for k, v in payload.items() if v is not ...}


def derived(obs: dict) -> dict:
    return derive_identity_fields(obs, company_id=COMPANY, observation_cutoff=CUTOFF)


def refuse(observations, vocab, **over) -> ExtractionError:
    with pytest.raises(ExtractionError) as excinfo:
        assert_candidate_conformance(
            [derived(o) if isinstance(o, dict) else o for o in observations],
            packet=packet(**over),
            vocabulary=vocab,
            schema_root=ROOT / "schemas",
        )
    return excinfo.value


# --- slugify ----------------------------------------------------------------


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Marketing Hub", "marketing-hub"),
        ("Breeze Copilot", "breeze-copilot"),
        ("  Smart   CRM  ", "smart-crm"),
        ("Sales Hub (Enterprise)", "sales-hub-enterprise"),
        ("HubSpot 2.0", "hubspot-2-0"),
        ("A/B Testing", "a-b-testing"),
        ("---", ""),
        ("", ""),
        ("!!!", ""),
        (None, ""),
        (12, ""),
    ],
)
def test_slugify_is_total_and_deterministic(name, expected):
    assert slugify_product_name(name) == expected
    assert slugify_product_name(name) == slugify_product_name(name)


def test_slugify_never_raises_so_the_grammar_has_one_owner():
    """A name it cannot slug yields "", and C3 judges that.

    Raising here would put the grammar in two places: this function and C3.
    """
    assert slugify_product_name("###") == ""


# --- derivation -------------------------------------------------------------


def test_derivation_overwrites_all_three_identity_fields():
    out = derived(observation())
    assert out["company_id"] == COMPANY
    assert out["observation_cutoff"] == CUTOFF
    assert out["normalized_name"] == "marketing-hub"
    assert out["product_observation_id"] == f"{COMPANY}:{CUTOFF}:marketing-hub"


def test_derivation_ignores_whatever_the_model_emitted():
    """The model's ids are discarded, so the prompt need not change."""
    out = derived(observation(
        product_observation_id="cand-001",
        company_id="HUBSPOT INC",
        observation_cutoff="not-a-date",
        normalized_name="Smart CRM",
    ))
    assert out["product_observation_id"] != "cand-001"
    assert out["company_id"] == COMPANY
    assert out["normalized_name"] == "marketing-hub"


def test_derivation_does_not_mutate_its_input():
    original = observation()
    snapshot = json.dumps(original, sort_keys=True)
    derived(original)
    assert json.dumps(original, sort_keys=True) == snapshot


def test_derivation_passes_non_objects_through_untouched():
    for item in ("a string", 12, None, ["nested"]):
        assert derive_identity_fields(
            item, company_id=COMPANY, observation_cutoff=CUTOFF
        ) is item


def test_derivation_supplies_a_schema_required_field_before_validation():
    """Ordering, asserted rather than assumed.

    ``product_observation_id`` is schema-required. If derivation ran after the
    schema check, an observation that omitted it would be recorded as
    ``schema_invalid`` for a field the pipeline always supplies.
    """
    without = observation(product_observation_id=...)
    assert "product_observation_id" not in without
    assert derived(without)["product_observation_id"].endswith(":marketing-hub")


# --- parse gates ------------------------------------------------------------


def envelope(text: str, *, finish="STOP", parts=None, candidates=None) -> dict:
    part_list = [{"text": text}] if parts is None else parts
    cands = (
        [{"finishReason": finish, "content": {"parts": part_list}}]
        if candidates is None
        else candidates
    )
    return {"candidates": cands}


def test_a_well_formed_envelope_parses():
    assert parse_model_observations(envelope('[{"a": 1}]')) == [{"a": 1}]


@pytest.mark.parametrize(
    "bad, code",
    [
        ("not a mapping", "candidate_parse_envelope_unusable"),
        ({"candidates": []}, "candidate_parse_envelope_unusable"),
        ({"candidates": [{}, {}]}, "candidate_parse_envelope_unusable"),
    ],
)
def test_an_unusable_envelope_is_refused(bad, code):
    with pytest.raises(ExtractionError) as excinfo:
        parse_model_observations(bad)
    assert excinfo.value.reason_code == code


@pytest.mark.parametrize("finish", ["MAX_TOKENS", "SAFETY", "OTHER", None])
def test_a_truncated_response_is_not_an_empty_result(finish):
    """A run that did not finish says nothing about candidates.

    Recording it as "zero candidates" would assert an absence nobody observed.
    """
    with pytest.raises(ExtractionError) as excinfo:
        parse_model_observations(envelope("[]", finish=finish))
    assert excinfo.value.reason_code == "candidate_parse_envelope_unusable"


@pytest.mark.parametrize("parts", [[], [{"text": "a"}, {"text": "b"}], [{}], [{"text": "  "}]])
def test_a_missing_or_split_text_part_is_refused(parts):
    with pytest.raises(ExtractionError) as excinfo:
        parse_model_observations(envelope("", parts=parts))
    assert excinfo.value.reason_code == "candidate_parse_envelope_unusable"


def test_unparseable_json_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        parse_model_observations(envelope("{not json"))
    assert excinfo.value.reason_code == "candidate_parse_json_invalid"


@pytest.mark.parametrize("body", ['{"a": 1}', '"a string"', "12", "null"])
def test_a_top_level_non_list_is_refused(body):
    with pytest.raises(ExtractionError) as excinfo:
        parse_model_observations(envelope(body))
    assert excinfo.value.reason_code == "candidate_parse_not_a_list"


# --- C1 through C6 ----------------------------------------------------------


def test_a_conforming_list_passes_every_gate(vocabulary):
    assert_candidate_conformance(
        [derived(observation())],
        packet=packet(),
        vocabulary=vocabulary,
        schema_root=ROOT / "schemas",
    )


def test_c1_and_c4_hold_by_construction_after_derivation(vocabulary):
    """Derivation makes C1/C2/C4 tautological, and they stay anyway.

    They are cheap, and they are what would catch a derivation bug -- the only
    remaining way those fields can be wrong.
    """
    out = derived(observation())
    assert out["company_id"] == packet()["company_id"]
    assert out["product_observation_id"] == (
        f"{out['company_id']}:{out['observation_cutoff']}:{out['normalized_name']}"
    )


@pytest.mark.parametrize(
    "field, value, code",
    [
        ("company_id", "OTHER-CO", "candidate_conformance_company_mismatch"),
        ("observation_cutoff", "2024-01-01", "candidate_conformance_cutoff_mismatch"),
        ("normalized_name", "Not A Slug", "candidate_conformance_normalized_name_invalid"),
        ("normalized_name", "", "candidate_conformance_normalized_name_invalid"),
        ("product_observation_id", "wrong", "candidate_conformance_observation_id_mismatch"),
    ],
)
def test_a_tampered_derived_field_is_caught(vocabulary, field, value, code):
    """Each gate has its own reason code, so the operator learns which broke."""
    tampered = derived(observation())
    tampered[field] = value
    with pytest.raises(ExtractionError) as excinfo:
        assert_candidate_conformance(
            [tampered], packet=packet(), vocabulary=vocabulary,
            schema_root=ROOT / "schemas",
        )
    assert excinfo.value.reason_code == code


def test_c3_refuses_a_product_name_that_cannot_be_slugged(vocabulary):
    error = refuse([observation(product_name="???")], vocabulary)
    assert error.reason_code == "candidate_conformance_normalized_name_invalid"


def test_two_products_that_slug_alike_are_refused_as_a_collision(vocabulary):
    """Distinct names, one identity -- the dataset cannot carry both.

    ID-1 makes ``product_observation_id`` a function of the slug, so a collision
    is not a cosmetic clash: two different products would share one longitudinal
    identity.
    """
    error = refuse(
        [observation(product_name="Sales Hub"), observation(product_name="sales hub!")],
        vocabulary,
    )
    assert error.reason_code == "candidate_conformance_observation_id_collision"
    assert "sales-hub" in str(error)


def test_the_same_product_name_twice_is_also_a_collision(vocabulary):
    error = refuse([observation(), observation()], vocabulary)
    assert error.reason_code == "candidate_conformance_observation_id_collision"


@pytest.mark.parametrize("status", ["planned", "ga", "GENERAL_AVAILABILITY", ""])
def test_c5_admits_only_the_governed_vocabulary(vocabulary, status):
    """A string outside the governed set is a conformance failure.

    Every value here is schema-valid -- ``availability_status`` is an
    unconstrained string -- so C5 is the only layer that can refuse them. That
    is exactly why the vocabulary artifact exists.
    """
    error = refuse([observation(availability_status=status)], vocabulary)
    assert error.reason_code == "candidate_conformance_status_not_governed"


def test_a_null_status_is_a_schema_failure_and_not_a_conformance_failure(vocabulary):
    """The boundary between the two layers, asserted rather than assumed.

    ``None`` is not a string, so the observation never passes the pre-schema
    check and C5 never sees it. It belongs in ``rejected[]`` as
    ``schema_invalid`` -- turning it into an atomic conformance refusal would
    take an ordinary bad record and stop the whole materialization.
    """
    assert_candidate_conformance(
        [derived(observation(availability_status=None))],
        packet=packet(), vocabulary=vocabulary, schema_root=ROOT / "schemas",
    )
    collection = build_candidate_collection(
        observation_kind="product",
        raw_artifact_reference="data/runs/x/raw.json",
        raw_artifact_sha256="a" * 64,
        observations=[derived(observation(availability_status=None))],
        schema_root=ROOT / "schemas",
    )
    assert [e["reason"] for e in collection["rejected"]] == ["schema_invalid"]


@pytest.mark.parametrize(
    "status",
    ["announced", "broadly_deployed_or_default", "deprecated", "discontinued",
     "general_availability", "private_beta", "public_beta", "unknown"],
)
def test_c5_asks_only_about_admission_not_about_activity(vocabulary, status):
    """All eight are admitted, ``unknown`` included.

    C5 is not the active/roadmap classification. An ``unknown`` candidate enters
    the collection and its disposition is a human decision made later.
    """
    assert_candidate_conformance(
        [derived(observation(availability_status=status))],
        packet=packet(), vocabulary=vocabulary, schema_root=ROOT / "schemas",
    )


def test_c6_refuses_evidence_the_packet_does_not_contain(vocabulary):
    error = refuse(
        [observation(evidence=[{"source_id": SRC, "passage_id": "psg-9999", "quote": "x"}])],
        vocabulary,
    )
    assert error.reason_code == "candidate_conformance_evidence_pair_unknown"


def test_c6_checks_the_pair_not_either_half(vocabulary):
    """A real source with someone else's passage is still unresolvable."""
    error = refuse(
        [observation(evidence=[{"source_id": "other", "passage_id": PSG, "quote": "x"}])],
        vocabulary,
    )
    assert error.reason_code == "candidate_conformance_evidence_pair_unknown"


# --- C8: the quote must be in the passage it cites --------------------------
#
# The shape below is the real ext-smoke-0006 Sales Hub failure, reduced: two
# passages that are *not* adjacent in the source, a quote assembled from the end
# of one and the start of the other, cited under the first one's id alone.

SPLICE_A = "psg-a-0001"
SPLICE_B = "psg-b-0001"
TEXT_A = "Sales Hub is software for sales representatives. Features include: email"
TEXT_B = "templates and tracking, conversations and meeting scheduling."
_C8_CODE = "candidate_conformance_evidence_quote_uncontained"


def splice_packet(**over) -> dict:
    # Ordered by (source_id, passage_id), so A is P001 and B is P002 -- the
    # materialization test below cites P001 and means passage A.
    return packet(
        passages=[
            {"source_id": SRC, "passage_id": SPLICE_A, "text": TEXT_A,
             "publication_date": "2024-01-01"},
            {"source_id": SRC, "passage_id": SPLICE_B, "text": TEXT_B,
             "publication_date": "2024-01-01"},
        ],
        **over,
    )


def refuse_spliced(evidence, vocab) -> ExtractionError:
    with pytest.raises(ExtractionError) as excinfo:
        assert_candidate_conformance(
            [derived(observation(evidence=evidence))],
            packet=splice_packet(),
            vocabulary=vocab,
            schema_root=ROOT / "schemas",
        )
    return excinfo.value


def test_c8_refuses_a_quote_spliced_from_two_passages(vocabulary):
    """The measured Sales Hub failure, and the reason this gate exists.

    Every earlier gate admits it: the pair resolves, so C6 is satisfied, and
    nothing before C8 ever read the words.
    """
    error = refuse_spliced(
        [{"source_id": SRC, "passage_id": SPLICE_A, "quote": f"{TEXT_A} {TEXT_B}"}],
        vocabulary,
    )
    assert error.reason_code == _C8_CODE


def test_the_spliced_citation_is_not_a_c6_failure(vocabulary):
    """C6 and C8 are different faults and must not answer for each other.

    The cited ``passage_id`` is genuinely a passage of this run -- the identifier
    is real and the content is not. Reporting this as C6 would send an operator
    looking for an invented identifier that does not exist.
    """
    error = refuse_spliced(
        [{"source_id": SRC, "passage_id": SPLICE_A, "quote": f"{TEXT_A} {TEXT_B}"}],
        vocabulary,
    )
    assert error.reason_code != "candidate_conformance_evidence_pair_unknown"
    assert (SRC, SPLICE_A) in {
        (p["source_id"], p["passage_id"]) for p in splice_packet()["passages"]
    }


@pytest.mark.parametrize("quote", ["", "   ", "\n\t "])
def test_c8_refuses_a_blank_quote(vocabulary, quote):
    """A blank quote must fail rather than pass by substring accident."""
    error = refuse_spliced(
        [{"source_id": SRC, "passage_id": SPLICE_A, "quote": quote}], vocabulary
    )
    assert error.reason_code == _C8_CODE


def test_c8_refuses_a_quote_from_the_passage_next_door(vocabulary):
    """Verbatim somewhere in the corpus is not verbatim in the cited passage."""
    error = refuse_spliced(
        [{"source_id": SRC, "passage_id": SPLICE_A, "quote": TEXT_B}], vocabulary
    )
    assert error.reason_code == _C8_CODE


def test_c8_admits_a_quote_that_really_occurs_in_the_cited_passage(vocabulary):
    """The contrast case: a substring of the right passage still passes."""
    assert_candidate_conformance(
        [derived(observation(evidence=[
            {"source_id": SRC, "passage_id": SPLICE_A, "quote": "software for sales"},
            {"source_id": SRC, "passage_id": SPLICE_B, "quote": TEXT_B},
        ]))],
        packet=splice_packet(),
        vocabulary=vocabulary,
        schema_root=ROOT / "schemas",
    )


def test_c8_names_the_citation_without_quoting_it(vocabulary):
    """A refusal reports what failed, never the contents that failed it."""
    error = refuse_spliced(
        [{"source_id": SRC, "passage_id": SPLICE_A, "quote": f"{TEXT_A} {TEXT_B}"}],
        vocabulary,
    )
    message = str(error)
    assert SRC in message and SPLICE_A in message
    assert TEXT_A not in message and TEXT_B not in message


def test_c8_refuses_the_whole_collection_not_the_one_entry(tmp_path, vocabulary):
    """Same atomicity as C6: one bad quote, nothing written at all."""
    vroot, vpin = _vocab_root(tmp_path, vocabulary)
    croot = tmp_path / "cand"
    croot.mkdir()
    with pytest.raises(ExtractionError) as excinfo:
        materialize_candidate_collection(
            raw_prediction=envelope(json.dumps([
                observation(
                    product_name="Marketing Hub",
                    availability_status="S5",
                    evidence=[{"ref": "P001", "quote": "software for sales"}],
                ),
                observation(
                    product_name="Sales Hub",
                    availability_status="S5",
                    evidence=[{"ref": "P001", "quote": f"{TEXT_A} {TEXT_B}"}],
                ),
            ])),
            packet=splice_packet(),
            raw_artifact_reference="data/runs/x/predictions/raw_prediction.json",
            raw_artifact_sha256="b" * 64,
            collection_root=croot,
            vocabulary_root=vroot,
            vocabulary_pin=vpin,
            repo_root=ROOT,
            schema_root=ROOT / "schemas",
        )
    assert excinfo.value.reason_code == _C8_CODE
    assert list(croot.rglob("*")) == []


# --- the boundary with the released rejected[] contract ---------------------


def test_non_objects_and_schema_failures_never_reach_the_conformance_gate(vocabulary):
    """They belong to ``rejected[]``, whose enum this gate must not widen."""
    assert_candidate_conformance(
        ["not an object", 12, None, {"missing": "required fields"},
         derived(observation())],
        packet=packet(), vocabulary=vocabulary, schema_root=ROOT / "schemas",
    )


def test_those_items_are_still_recorded_by_the_builder():
    collection = build_candidate_collection(
        observation_kind="product",
        raw_artifact_reference="data/runs/x/raw.json",
        raw_artifact_sha256="a" * 64,
        observations=["not an object", {"missing": "fields"}, derived(observation())],
        schema_root=ROOT / "schemas",
    )
    reasons = [entry["reason"] for entry in collection["rejected"]]
    assert reasons == ["not_an_object", "schema_invalid"]
    assert collection["accepted_candidate_count"] == 1
    assert collection["rejected_candidate_count"] == 2


# --- materialization --------------------------------------------------------


def _vocab_root(tmp_path: Path, vocabulary: dict) -> tuple[Path, dict]:
    from dynamic_ai_products.extraction.availability_vocabulary import (
        materialize_availability_vocabulary,
    )
    root = tmp_path / "vocab"
    root.mkdir()
    pin = materialize_availability_vocabulary(
        vocabulary, attempt_root=root, repo_root=ROOT
    )
    return root, pin


def test_a_conforming_run_materializes_exactly_one_collection(tmp_path, vocabulary):
    """End to end the model now emits a status *label*, resolved before C5."""
    vroot, vpin = _vocab_root(tmp_path, vocabulary)
    croot = tmp_path / "cand"
    croot.mkdir()
    pin = materialize_candidate_collection(
        raw_prediction=envelope(json.dumps([observation(availability_status="S5")])),
        packet=packet(),
        raw_artifact_reference="data/runs/x/predictions/raw_prediction.json",
        raw_artifact_sha256="b" * 64,
        collection_root=croot,
        vocabulary_root=vroot,
        vocabulary_pin=vpin,
        repo_root=ROOT,
        schema_root=ROOT / "schemas",
    )
    written = sorted(p.relative_to(croot).as_posix() for p in croot.rglob("*") if p.is_file())
    assert written == [CANDIDATE_COLLECTION_REFERENCE]
    body = json.loads((croot / CANDIDATE_COLLECTION_REFERENCE).read_bytes())
    assert pin["sha256"] == hashlib.sha256(
        (croot / CANDIDATE_COLLECTION_REFERENCE).read_bytes()
    ).hexdigest()
    assert body["accepted_candidate_count"] == 1
    assert body["entries"][0]["observation"]["product_observation_id"] == (
        f"{COMPANY}:{CUTOFF}:marketing-hub"
    )
    # The label is resolved on the way in; the artifact stores the real token.
    assert body["entries"][0]["observation"]["availability_status"] == (
        "general_availability"
    )


def test_a_conformance_violation_writes_nothing_at_all(tmp_path, vocabulary):
    """Atomic at the collection level: no partial artifact, ever."""
    vroot, vpin = _vocab_root(tmp_path, vocabulary)
    croot = tmp_path / "cand"
    croot.mkdir()
    with pytest.raises(ExtractionError) as excinfo:
        materialize_candidate_collection(
            raw_prediction=envelope(json.dumps([
                observation(availability_status="S5"),
                observation(product_name="Other", availability_status="S9"),
            ])),
            packet=packet(),
            raw_artifact_reference="data/runs/x/predictions/raw_prediction.json",
            raw_artifact_sha256="b" * 64,
            collection_root=croot,
            vocabulary_root=vroot,
            vocabulary_pin=vpin,
            repo_root=ROOT,
            schema_root=ROOT / "schemas",
        )
    assert excinfo.value.reason_code == (
        "candidate_conformance_status_label_unresolvable"
    )
    assert list(croot.rglob("*")) == []


def test_a_second_materialization_is_refused(tmp_path, vocabulary):
    vroot, vpin = _vocab_root(tmp_path, vocabulary)
    croot = tmp_path / "cand"
    croot.mkdir()
    kwargs = dict(
        raw_prediction=envelope(json.dumps([observation(availability_status="S5")])),
        packet=packet(),
        raw_artifact_reference="data/runs/x/predictions/raw_prediction.json",
        raw_artifact_sha256="b" * 64,
        collection_root=croot,
        vocabulary_root=vroot,
        vocabulary_pin=vpin,
        repo_root=ROOT,
        schema_root=ROOT / "schemas",
    )
    materialize_candidate_collection(**kwargs)
    with pytest.raises(ExtractionError):
        materialize_candidate_collection(**kwargs)


def test_a_tampered_vocabulary_pin_refuses_before_anything_is_written(
    tmp_path, vocabulary
):
    """C5's set comes from the artifact, never from a constant in the module."""
    vroot, vpin = _vocab_root(tmp_path, vocabulary)
    croot = tmp_path / "cand"
    croot.mkdir()
    with pytest.raises(ExtractionError) as excinfo:
        materialize_candidate_collection(
            raw_prediction=envelope(json.dumps([observation()])),
            packet=packet(),
            raw_artifact_reference="data/runs/x/predictions/raw_prediction.json",
            raw_artifact_sha256="b" * 64,
            collection_root=croot,
            vocabulary_root=vroot,
            vocabulary_pin={**vpin, "sha256": "0" * 64},
            repo_root=ROOT,
            schema_root=ROOT / "schemas",
        )
    assert excinfo.value.reason_code == "vocabulary_pin_unresolved"
    assert list(croot.rglob("*")) == []


# --- the wiring -------------------------------------------------------------


def test_the_runner_accepts_the_collection_parameters_and_they_are_optional():
    import inspect

    from dynamic_ai_products.extraction.run_extraction import run_extraction_stage_v2

    parameters = inspect.signature(run_extraction_stage_v2).parameters
    for name in ("candidate_collection_root", "vocabulary_root", "vocabulary_pin"):
        assert name in parameters, name
        assert parameters[name].default is None, name


def test_the_collection_never_lands_inside_the_run_root():
    """The eleven-member run root is an invariant, not an accident."""
    from dynamic_ai_products.extraction import run_extraction as mod

    source = Path(mod.__file__).read_text(encoding="utf-8")
    assert "collection_root=candidate_collection_root" in source
    assert "collection_root=root" not in source
    assert "collection_root=outcome.run_root" not in source


# --- ADR-055: positional labels replace transcribed identifiers -------------


from dynamic_ai_products.extraction.candidates import resolve_evidence_refs  # noqa: E402
from dynamic_ai_products.extraction.contents_renderer import (  # noqa: E402
    canonical_passage_order,
    passage_ref_label,
    render_provider_contents,
)


def _packet_of(pairs) -> dict:
    return {
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "legal_name": "TEST CO",
        "passages": [
            {
                "source_id": source_id,
                "passage_id": passage_id,
                "text": f"body of {passage_id}",
                "publication_date": "2024-01-01",
            }
            for source_id, passage_id in pairs
        ],
    }


UNSORTED = _packet_of([("s-b", "p-9"), ("s-a", "p-2"), ("s-a", "p-1")])


def test_the_canonical_order_is_not_the_packets_own_order():
    """The defect the shared sorter exists to prevent.

    Measured on the pilot packet: 121 of 124 positions differ between the
    packet's list order and the render order. A resolver that indexed the list
    would attach almost every quote to the wrong passage, and every position it
    named would still be a real one -- so nothing downstream would notice.
    """
    own = [(p["source_id"], p["passage_id"]) for p in UNSORTED["passages"]]
    canonical = [(p["source_id"], p["passage_id"]) for p in canonical_passage_order(UNSORTED)]
    assert own != canonical
    assert canonical == sorted(own)


def test_the_renderer_and_the_resolver_read_the_same_order():
    """One function decides, both callers obey -- asserted, not assumed."""
    rendered = render_provider_contents(
        stage="product_extraction",
        prompt_text="{{company_name}} {{cutoff}}\n{{passages_with_ids}}",
        packet=UNSORTED,
    )
    ordered = canonical_passage_order(UNSORTED)
    for ordinal, passage in enumerate(ordered, start=1):
        label = passage_ref_label(ordinal, stage="product_extraction")
        assert f"[ref: {label}] [passage_id: {passage['passage_id']}]" in rendered


def test_the_renderer_keeps_the_identifiers_for_human_readers():
    """The model no longer copies them; an auditor still needs them."""
    rendered = render_provider_contents(
        stage="product_extraction",
        prompt_text="{{company_name}} {{cutoff}}\n{{passages_with_ids}}",
        packet=UNSORTED,
    )
    assert rendered.count("[ref: ") == 3
    assert rendered.count("[passage_id: ") == 3
    assert rendered.count("[source_id: ") == 3


@pytest.mark.parametrize("ordinal, expected", [(1, "P001"), (42, "P042"), (1000, "P1000")])
def test_labels_are_one_based_and_widen_past_three_digits(ordinal, expected):
    """The product stage's padding is unchanged; ADR-064 moved only capability."""
    assert passage_ref_label(ordinal, stage="product_extraction") == expected


@pytest.mark.parametrize("ordinal, expected", [(1, "P1"), (42, "P42"), (1000, "P1000")])
def test_the_capability_stage_labels_without_padding(ordinal, expected):
    assert passage_ref_label(ordinal, stage="capability_extraction") == expected


@pytest.mark.parametrize("stage", ["", "mystery", None, 7])
def test_a_stage_with_no_declared_label_style_is_refused(stage):
    """No default. A default is what would give a new stage a padding
    convention its own prompt never described."""
    with pytest.raises(ExtractionError) as excinfo:
        passage_ref_label(1, stage=stage)
    assert excinfo.value.reason_code == "passage_ref_label_style_undeclared"


def test_the_label_style_map_is_closed_over_the_materializable_stages():
    """ADR-068 adds the task stage; the map is still closed, not defaulted."""
    from dynamic_ai_products.extraction.contents_renderer import STAGE_PASSAGE_REF_STYLE

    assert set(STAGE_PASSAGE_REF_STYLE) == {
        "product_extraction",
        "capability_extraction",
        "task_extraction",
        # ADR-073 (CR-0009): consolidation is a stage, not a second pass.
        "product_consolidation",
    }
    # ADR-064's measurement carried forward rather than repeated: only the
    # product stage pads, because only its prompt describes a padded label.
    assert STAGE_PASSAGE_REF_STYLE["product_extraction"] == "P{:03d}"
    assert STAGE_PASSAGE_REF_STYLE["capability_extraction"] == "P{:d}"
    assert STAGE_PASSAGE_REF_STYLE["task_extraction"] == "P{:d}"
    assert STAGE_PASSAGE_REF_STYLE["product_consolidation"] == "P{:d}"


def test_a_ref_resolves_to_the_pair_at_that_canonical_position():
    ordered = canonical_passage_order(UNSORTED)
    out = resolve_evidence_refs(
        observation(evidence=[{"ref": "P002", "quote": "q"}]), packet=UNSORTED
    )
    assert out["evidence"] == [
        {
            "quote": "q",
            "source_id": ordered[1]["source_id"],
            "passage_id": ordered[1]["passage_id"],
        }
    ]


def test_the_resolved_observation_validates_against_the_unchanged_schema():
    """The schema is untouched; resolution just runs first."""
    from jsonschema import Draft202012Validator

    schema = json.loads((ROOT / "schemas" / "product_observation.schema.json").read_text())
    resolved = derive_identity_fields(
        resolve_evidence_refs(
            observation(evidence=[{"ref": "P001", "quote": "q"}]), packet=UNSORTED
        ),
        company_id=COMPANY,
        observation_cutoff=CUTOFF,
    )
    Draft202012Validator(schema).validate(resolved)
    assert set(resolved["evidence"][0]) == {"source_id", "passage_id", "quote"}


@pytest.mark.parametrize(
    "label",
    ["P004", "P999", "P000", "P0", "p001", "001", "", "PABC", None, 1],
    ids=["out_of_range", "far_out", "zero_padded", "zero", "lowercase",
         "no_prefix", "empty", "letters", "null", "int"],
)
def test_an_unresolvable_label_has_its_own_reason_code(label):
    """Not folded into the unknown-pair code.

    "Invented an identifier" and "named a position it was not shown" are
    different faults, and an operator needs to know which one happened.

    ADR-064 widened the grammar to any run of digits, so ``P1`` and ``P01`` left
    this list -- they now resolve. What stays refused is unchanged: a position
    outside the packet, a zero ordinal however it is spelled, a wrong case, a
    missing prefix, and anything that is not a digit string at all.
    """
    with pytest.raises(ExtractionError) as excinfo:
        resolve_evidence_refs(
            observation(evidence=[{"ref": label, "quote": "q"}]), packet=UNSORTED
        )
    assert excinfo.value.reason_code == "candidate_conformance_evidence_ref_unresolvable"


# --- ADR-064: padding is presentation, not identity -------------------------


@pytest.mark.parametrize("label", ["P001", "P01", "P1", "P0001"])
def test_any_padding_of_one_ordinal_resolves_to_one_passage(label):
    """The fix for the measured P25 failure, stated as an equivalence.

    Two live capability runs cited ``P25`` for a passage rendered as ``P025``
    and were refused. The grammar now reads the digits as a number, so every
    spelling of an ordinal names the same passage and none of them is a guess:
    ``int`` does the work, not a repair heuristic.
    """
    ordered = canonical_passage_order(UNSORTED)
    resolved = resolve_evidence_refs(
        observation(evidence=[{"ref": label, "quote": "q"}]), packet=UNSORTED
    )
    assert resolved["evidence"][0]["passage_id"] == ordered[0]["passage_id"]
    assert resolved["evidence"][0]["source_id"] == ordered[0]["source_id"]


def test_the_unpadded_label_is_not_a_repair_of_the_padded_one():
    """Both spellings go down one path; neither is rewritten into the other."""
    padded = resolve_evidence_refs(
        observation(evidence=[{"ref": "P002", "quote": "q"}]), packet=UNSORTED
    )
    plain = resolve_evidence_refs(
        observation(evidence=[{"ref": "P2", "quote": "q"}]), packet=UNSORTED
    )
    assert padded["evidence"] == plain["evidence"]


def test_resolution_leaves_untouched_what_it_does_not_own():
    """Non-objects and ref-free evidence fall through to the released contract."""
    for item in ("a string", 12, None):
        assert resolve_evidence_refs(item, packet=UNSORTED) is item
    already = observation(evidence=[{"source_id": "s-a", "passage_id": "p-1", "quote": "q"}])
    assert resolve_evidence_refs(already, packet=UNSORTED) is already
    assert resolve_evidence_refs({"evidence": "not a list"}, packet=UNSORTED) == (
        {"evidence": "not a list"}
    )


def test_resolution_does_not_mutate_its_input():
    original = observation(evidence=[{"ref": "P001", "quote": "q"}])
    snapshot = json.dumps(original, sort_keys=True)
    resolve_evidence_refs(original, packet=UNSORTED)
    assert json.dumps(original, sort_keys=True) == snapshot


def test_the_successor_prompt_asks_for_labels_and_forbids_identifiers():
    text = (ROOT / "prompts" / "extraction" / "product_discovery_schema_v3.md").read_text()
    assert '{"ref": ..., "quote": ...}' in text
    assert "Never emit `source_id` or `passage_id`" in text
    assert "[ref: P001]" in text


# --- ADR-056: the status is named by label, not transcribed -----------------


from dynamic_ai_products.extraction.availability_vocabulary import (  # noqa: E402
    CANONICAL_AVAILABILITY_STATUS_VALUES,
    resolve_status_label,
    status_label,
    status_label_table,
)
from dynamic_ai_products.extraction.candidates import resolve_status_labels  # noqa: E402


def test_the_label_table_is_derived_from_the_canonical_tuple():
    """One ordering, not two. The table is a view of the constant."""
    table = status_label_table()
    assert [token for _, token in table] == list(CANONICAL_AVAILABILITY_STATUS_VALUES)
    assert [label for label, _ in table] == [f"S{i}" for i in range(1, 9)]
    assert len(table) == 8


@pytest.mark.parametrize("ordinal, token", list(enumerate(CANONICAL_AVAILABILITY_STATUS_VALUES, 1)))
def test_every_label_resolves_to_its_canonical_status(ordinal, token):
    assert resolve_status_label(status_label(ordinal)) == token


@pytest.mark.parametrize(
    "label",
    ["S0", "S9", "S99", "s1", "S", "1", "", "SX", "general_availability",
     "broadly_deployed_or_default", "broadly_deployed_or_or_default", None, 5],
    ids=["zero", "nine", "far", "lowercase", "bare_letter", "bare_digit", "empty",
         "letters", "spelled_token", "spelled_long_token", "the_measured_corruption",
         "null", "int"],
)
def test_anything_that_is_not_a_label_is_refused(label):
    """Strict both ways.

    A spelled-out token is refused even when it is spelled correctly: accepting
    both conventions would restore the transcription this change removes, and
    the doubled-syllable value measured on ``ext-smoke-0005`` is refused with
    the same code rather than being reported as an ungoverned status.
    """
    with pytest.raises(ExtractionError) as excinfo:
        resolve_status_label(label)
    assert excinfo.value.reason_code == (
        "candidate_conformance_status_label_unresolvable"
    )


def test_the_measured_corruption_is_refused_before_c5_sees_it():
    """``broadly_deployed_or_or_default`` blocked a whole run once."""
    with pytest.raises(ExtractionError) as excinfo:
        resolve_status_labels(observation(availability_status="broadly_deployed_or_or_default"))
    assert excinfo.value.reason_code == (
        "candidate_conformance_status_label_unresolvable"
    )


def test_resolution_replaces_the_label_and_leaves_the_rest_alone():
    out = resolve_status_labels(observation(availability_status="S2"))
    assert out["availability_status"] == "broadly_deployed_or_default"
    assert out["product_name"] == "Marketing Hub"


def test_status_resolution_does_not_mutate_its_input():
    original = observation(availability_status="S5")
    snapshot = json.dumps(original, sort_keys=True)
    resolve_status_labels(original)
    assert json.dumps(original, sort_keys=True) == snapshot


def test_status_resolution_leaves_untouched_what_it_does_not_own():
    for item in ("a string", 12, None):
        assert resolve_status_labels(item) is item
    without = {"product_name": "x"}
    assert resolve_status_labels(without) is without


def test_the_v4_prompt_renders_exactly_the_generated_table():
    """The instruction and the code cannot disagree about what S2 means."""
    text = (ROOT / "prompts" / "extraction" / "product_discovery_schema_v4.md").read_text()
    for label, token in status_label_table():
        assert f"{label}  =  {token}" in text
    assert "Do not write a status word" in text
    assert "not a word" in text


def test_the_v4_prompt_keeps_the_four_lists_so_the_binding_still_holds():
    """B4 compares the prompt's real tokens against the artifact.

    Replacing those lists with labels would delete the only check that proves
    the prompt's copy of the vocabulary has not drifted.
    """
    from dynamic_ai_products.extraction.availability_vocabulary import (
        parse_prompt_status_vocabulary,
    )

    text = (ROOT / "prompts" / "extraction" / "product_discovery_schema_v4.md").read_text()
    parsed = parse_prompt_status_vocabulary(text)
    assert parsed["active_status_values"] == [
        "broadly_deployed_or_default",
        "general_availability",
        "private_beta",
        "public_beta",
    ]
    assert parsed["unknown_status_values"] == ["unknown"]


# --- ADR-060 (E-S3): the capability branch ----------------------------------


from dynamic_ai_products.extraction.candidates import resolve_parent_refs  # noqa: E402

PARENT_A = f"{COMPANY}:{CUTOFF}:alpha"
PARENT_B = f"{COMPANY}:{CUTOFF}:beta"


def capability_packet(**over) -> dict:
    payload = packet(**over)
    # ``resolve_evidence_refs`` goes through ``canonical_passage_order``, which
    # requires a dated passage -- the same rule the renderer enforces.
    payload.setdefault("legal_name", "TEST CO")
    payload["passages"] = [
        {"source_id": SRC, "passage_id": PSG, "text": "x",
         "publication_date": "2024-01-01"}
    ]
    payload["parent_context"] = {
        "snapshot": {"reference": "snapshots/a.json", "sha256": "b" * 64,
                     "snapshot_version": "v1"},
        "product_parents": [
            {"observation_id": PARENT_A, "reference": "observations/product/1.json",
             "sha256": "a" * 64, "payload": {"product_name": "Alpha"}},
            {"observation_id": PARENT_B, "reference": "observations/product/2.json",
             "sha256": "c" * 64, "payload": {"product_name": "Beta"}},
        ],
    }
    return payload


def capability(**over) -> dict:
    payload = {
        "parent_ref": "A01",
        "capability": "summarize support tickets",
        "availability_status": "S5",
        "confidence": "high",
        "evidence": [{"ref": "P001", "quote": "x"}],
    }
    payload.update(over)
    return {k: v for k, v in payload.items() if v is not ...}


def cap_chain(obs, pkt=None):
    pkt = pkt if pkt is not None else capability_packet()
    return derive_identity_fields(
        resolve_status_labels(
            resolve_evidence_refs(resolve_parent_refs(obs, packet=pkt), packet=pkt)
        ),
        company_id=pkt["company_id"],
        observation_cutoff=pkt["observation_cutoff_date"],
        observation_kind="capability",
    )


def cap_refuse(observations, vocab, pkt=None) -> ExtractionError:
    pkt = pkt if pkt is not None else capability_packet()
    with pytest.raises(ExtractionError) as excinfo:
        assert_candidate_conformance(
            observations, packet=pkt, vocabulary=vocab,
            schema_root=ROOT / "schemas", observation_kind="capability",
        )
    return excinfo.value


# --- parent resolution ------------------------------------------------------


def test_a_parent_ref_resolves_to_the_product_at_that_position():
    """The third label family, resolved from the same ordered parent context."""
    out = resolve_parent_refs(capability(), packet=capability_packet())
    assert out["product_observation_id"] == PARENT_A
    assert "parent_ref" not in out


def test_the_label_is_removed_so_the_released_schema_accepts_the_result():
    """``capability_observation@0.1.0`` is additionalProperties: false."""
    from jsonschema import Draft202012Validator

    schema = json.loads(
        (ROOT / "schemas" / "capability_observation.schema.json").read_text()
    )
    resolved = cap_chain(capability())
    Draft202012Validator(schema).validate(resolved)
    assert "parent_ref" not in resolved


@pytest.mark.parametrize(
    "label",
    ["A03", "A99", "A00", "a01", "A1", "A", "01", "", "AXX", None, 1],
    ids=["out_of_range", "far_out", "zero", "lowercase", "one_digit", "bare",
         "no_prefix", "empty", "letters", "null", "int"],
)
def test_an_unresolvable_parent_label_has_its_own_reason_code(label):
    """Separate from the evidence code, and from C7.

    Three distinct faults: a label that names no position, a citation of a
    passage that does not exist, and a parent that exists but was never
    admitted. An operator needs to know which.
    """
    with pytest.raises(ExtractionError) as excinfo:
        resolve_parent_refs(capability(parent_ref=label), packet=capability_packet())
    assert excinfo.value.reason_code == (
        "candidate_conformance_parent_ref_unresolvable"
    )


def test_parent_resolution_leaves_untouched_what_it_does_not_own():
    for item in ("a string", 12, None):
        assert resolve_parent_refs(item, packet=capability_packet()) is item
    already = {"product_observation_id": PARENT_A}
    assert resolve_parent_refs(already, packet=capability_packet()) is already


def test_parent_resolution_does_not_mutate_its_input():
    original = capability()
    snapshot = json.dumps(original, sort_keys=True)
    resolve_parent_refs(original, packet=capability_packet())
    assert json.dumps(original, sort_keys=True) == snapshot


def test_a_packet_without_verified_parent_context_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        resolve_parent_refs(capability(), packet=packet())
    assert excinfo.value.reason_code == (
        "candidate_conformance_parent_ref_unresolvable"
    )


# --- capability identity ----------------------------------------------------


def test_the_capability_identity_is_derived_from_its_parent():
    out = cap_chain(capability())
    assert out["normalized_capability"] == "summarize-support-tickets"
    assert out["capability_observation_id"] == f"{PARENT_A}:summarize-support-tickets"


def test_the_parent_id_is_a_component_of_the_child_id():
    """Which is why parent resolution must run before derivation."""
    out = cap_chain(capability())
    assert out["capability_observation_id"].startswith(out["product_observation_id"] + ":")


def test_the_model_cannot_supply_any_capability_identity():
    out = cap_chain(capability(
        capability_observation_id="cap-001",
        normalized_capability="Whatever The Model Said",
    ))
    assert out["capability_observation_id"] != "cap-001"
    assert out["normalized_capability"] == "summarize-support-tickets"


def test_the_product_branch_is_unchanged_by_the_parameter():
    """Backward compatibility, asserted rather than assumed."""
    explicit = derive_identity_fields(
        observation(), company_id=COMPANY, observation_cutoff=CUTOFF,
        observation_kind="product",
    )
    assert explicit == derived(observation())


@pytest.mark.parametrize("kind", ["", "products", "Capability", None, 7])
def test_an_unknown_observation_kind_is_refused(kind):
    with pytest.raises(ExtractionError) as excinfo:
        derive_identity_fields(observation(), observation_kind=kind)
    assert excinfo.value.reason_code == "observation_kind_invalid"


# --- C7 and the capability gate ---------------------------------------------


def test_a_conforming_capability_passes_every_gate(vocabulary):
    assert_candidate_conformance(
        [cap_chain(capability())], packet=capability_packet(),
        vocabulary=vocabulary, schema_root=ROOT / "schemas",
        observation_kind="capability",
    )


def test_c7_refuses_a_parent_that_is_not_a_validated_product(vocabulary):
    """The gate with no product-side counterpart.

    A capability attributed to a product the human rejected would be
    structurally valid -- real-looking id, real passage, conforming record --
    and only this gate catches it.
    """
    tampered = cap_chain(capability())
    tampered["product_observation_id"] = f"{COMPANY}:{CUTOFF}:rejected-product"
    tampered["capability_observation_id"] = (
        f"{tampered['product_observation_id']}:{tampered['normalized_capability']}"
    )
    error = cap_refuse([tampered], vocabulary)
    assert error.reason_code == "candidate_conformance_parent_not_in_snapshot"
    assert "rejected-product" in str(error)


def test_c7_subsumes_c1_and_c2_for_capability(vocabulary):
    """A capability record carries neither company_id nor observation_cutoff.

    Measured: neither is a property of ``capability_observation@0.1.0``. Both
    reach the record through the parent, whose id *is*
    ``{company_id}:{cutoff}:{slug}`` -- so C7 proves them, and proves something
    C1 and C2 could not: that a human admitted this parent.
    """
    schema = json.loads(
        (ROOT / "schemas" / "capability_observation.schema.json").read_text()
    )
    assert "company_id" not in schema["properties"]
    assert "observation_cutoff" not in schema["properties"]
    out = cap_chain(capability())
    assert out["product_observation_id"].startswith(f"{COMPANY}:{CUTOFF}:")


def test_collision_is_scoped_per_parent_without_a_second_mechanism(vocabulary):
    """Two products may legitimately offer the same capability."""
    same_parent = [
        cap_chain(capability()),
        cap_chain(capability(capability="Summarize Support Tickets!")),
    ]
    assert cap_refuse(same_parent, vocabulary).reason_code == (
        "candidate_conformance_observation_id_collision"
    )

    different_parents = [cap_chain(capability()), cap_chain(capability(parent_ref="A02"))]
    assert_candidate_conformance(
        different_parents, packet=capability_packet(), vocabulary=vocabulary,
        schema_root=ROOT / "schemas", observation_kind="capability",
    )


def test_c3_refuses_a_capability_that_cannot_be_slugged(vocabulary):
    error = cap_refuse([cap_chain(capability(capability="???"))], vocabulary)
    assert error.reason_code == "candidate_conformance_normalized_name_invalid"
    assert "normalized_capability" in str(error)


@pytest.mark.parametrize("status", ["planned", "ga", ""])
def test_c5_governs_the_capability_status_too(vocabulary, status):
    tampered = cap_chain(capability())
    tampered["availability_status"] = status
    assert cap_refuse([tampered], vocabulary).reason_code == (
        "candidate_conformance_status_not_governed"
    )


def test_c6_still_refuses_evidence_outside_the_packet(vocabulary):
    tampered = cap_chain(capability())
    tampered["evidence"] = [
        {"source_id": SRC, "passage_id": "psg-9999", "quote": "x"}
    ]
    assert cap_refuse([tampered], vocabulary).reason_code == (
        "candidate_conformance_evidence_pair_unknown"
    )


@pytest.mark.parametrize("kind", ["", "mystery", "tasks", None, 7])
def test_the_gate_refuses_an_unknown_kind(vocabulary, kind):
    """ADR-068 made "task" a real kind, so the probe names ones that are not."""
    with pytest.raises(ExtractionError) as excinfo:
        assert_candidate_conformance(
            [], packet=capability_packet(), vocabulary=vocabulary,
            schema_root=ROOT / "schemas", observation_kind=kind,
        )
    assert excinfo.value.reason_code == "observation_kind_invalid"


def test_the_materializer_defaults_to_product_so_nothing_existing_changes():
    import inspect

    parameters = inspect.signature(materialize_candidate_collection).parameters
    assert parameters["observation_kind"].default == "product"


# --- ADR-061: the runner resolves the kind, never defaults to it ------------


from dynamic_ai_products.extraction.candidates import (  # noqa: E402
    OBSERVATION_KINDS,
    STAGE_OBSERVATION_KIND,
    observation_kind_for_stage,
)


def test_the_stage_map_now_includes_task_because_it_has_a_qualified_prompt():
    """ADR-068 added the *kind*; ADR-069 makes the *stage* runnable.

    ``task`` became a real observation kind and the renderer could materialize
    the task stage offline, but the entry that lets a run resolve a kind from
    the stage stayed missing on purpose: ``task_discovery_recall`` states no
    output contract, so it had no change request and no prompt qualification.
    Adding this entry before that existed would have made a live task run
    reachable through a prompt that cannot produce a conforming record -- the
    exact defect CR-0005 was written for on the capability side.
    ``task_discovery_schema_v1`` (CR-0008) closes that gap, so the entry is
    added now.
    """
    assert STAGE_OBSERVATION_KIND == {
        "product_extraction": "product",
        "capability_extraction": "capability",
        "task_extraction": "task",
    }
    assert set(STAGE_OBSERVATION_KIND.values()) == set(OBSERVATION_KINDS)


@pytest.mark.parametrize(
    "stage, kind", [("product_extraction", "product"),
                    ("capability_extraction", "capability"),
                    ("task_extraction", "task")]
)
def test_each_declared_stage_resolves_to_its_kind(stage, kind):
    assert observation_kind_for_stage(stage) == kind


@pytest.mark.parametrize("stage", ["", "product", "mystery_stage"])
def test_an_undeclared_stage_fails_closed_with_its_own_code(stage):
    """Not a default, and not a borrowed reason code.

    Defaulting is what created the defect this map closes: the runner asked for
    no kind, got ``product``, and a capability run would have collected against
    the product schema.
    """
    with pytest.raises(ExtractionError) as excinfo:
        observation_kind_for_stage(stage)
    assert excinfo.value.reason_code == "stage_observation_kind_undeclared"
    assert stage in str(excinfo.value) or stage == ""


def test_the_runner_resolves_the_kind_from_the_stage():
    """The call site, not just the helper.

    Parameterizing the function without threading it through its one caller is
    exactly the gap this closes, so the caller is asserted directly.
    """
    from pathlib import Path as _Path

    from dynamic_ai_products.extraction import run_extraction as mod

    source = _Path(mod.__file__).read_text(encoding="utf-8")
    assert "observation_kind=observation_kind_for_stage(stage)" in source
    assert "observation_kind=\"product\"" not in source


def test_a_capability_collection_would_have_been_silently_empty(tmp_path, vocabulary):
    """The defect, reproduced against the released schemas.

    Collected as ``product``, eleven conforming capability observations become
    eleven ``schema_invalid`` rejects and the collection reports
    ``accepted=0`` -- structurally valid, and wrong. Nothing downstream refuses
    it, because C1-C7 gate only what survives the pre-schema check.
    """
    capabilities = [cap_chain(capability()), cap_chain(capability(parent_ref="A02"))]

    wrong = build_candidate_collection(
        observation_kind="product",
        raw_artifact_reference="data/runs/x/raw.json",
        raw_artifact_sha256="a" * 64,
        observations=capabilities,
        schema_root=ROOT / "schemas",
    )
    assert wrong["accepted_candidate_count"] == 0
    assert [entry["reason"] for entry in wrong["rejected"]] == ["schema_invalid"] * 2

    right = build_candidate_collection(
        observation_kind="capability",
        raw_artifact_reference="data/runs/x/raw.json",
        raw_artifact_sha256="a" * 64,
        observations=capabilities,
        schema_root=ROOT / "schemas",
    )
    assert right["accepted_candidate_count"] == 2
    assert right["rejected"] == []


# --- ADR-068 (E-T1): the task kind, C9 and C10 ------------------------------

TASK_PRODUCT = f"{COMPANY}:{CUTOFF}:payments"
OTHER_PRODUCT = f"{COMPANY}:{CUTOFF}:sales-hub"
TASK_CAPABILITY = f"{TASK_PRODUCT}:accept-electronic-funds-transfers"
OTHER_CAPABILITY = f"{OTHER_PRODUCT}:score-leads"


def task_packet(**over) -> dict:
    payload = packet(**over)
    payload["parent_context"] = {
        "snapshot": {"reference": "snapshots/b.json", "sha256": "c" * 64,
                     "snapshot_version": "b-v1"},
        "product_parents": [
            {"observation_id": TASK_PRODUCT, "reference": "observations/product/a.json",
             "sha256": "a" * 64, "payload": {"product_observation_id": TASK_PRODUCT,
                                             "product_name": "Payments"}},
            {"observation_id": OTHER_PRODUCT, "reference": "observations/product/b.json",
             "sha256": "b" * 64, "payload": {"product_observation_id": OTHER_PRODUCT,
                                             "product_name": "Sales Hub"}},
        ],
        "capability_parents": [
            {"observation_id": TASK_CAPABILITY,
             "reference": "observations/capability/a.json", "sha256": "d" * 64,
             "payload": {"capability_observation_id": TASK_CAPABILITY,
                         "product_observation_id": TASK_PRODUCT,
                         "capability": "accept electronic funds transfers",
                         "evidence": [{"source_id": SRC, "passage_id": PSG,
                                       "quote": "x"}]}},
            {"observation_id": OTHER_CAPABILITY,
             "reference": "observations/capability/b.json", "sha256": "e" * 64,
             "payload": {"capability_observation_id": OTHER_CAPABILITY,
                         "product_observation_id": OTHER_PRODUCT,
                         "capability": "score leads",
                         "evidence": [{"source_id": SRC, "passage_id": PSG,
                                       "quote": "x"}]}},
        ],
    }
    return payload


def task(**over) -> dict:
    payload = {
        "task_observation_id": "ignored-by-derivation",
        "company_id": COMPANY,
        "observation_cutoff": CUTOFF,
        "product_observation_id": TASK_PRODUCT,
        "capability_observation_ids": [TASK_CAPABILITY],
        "task": "Accept a customer card payment to get paid faster",
        "customer_need": "collect money from a buyer without extra tooling",
        "availability_status": "general_availability",
        "confidence": "high",
        "evidence": [{"source_id": SRC, "passage_id": PSG, "quote": "x"}],
    }
    payload.update(over)
    return {k: v for k, v in payload.items() if v is not ...}


def derived_task(obs: dict) -> dict:
    return derive_identity_fields(
        obs, company_id=COMPANY, observation_cutoff=CUTOFF, observation_kind="task"
    )


def admit_task(observations, vocab, **over):
    assert_candidate_conformance(
        [derived_task(o) if isinstance(o, dict) else o for o in observations],
        packet=task_packet(**over), vocabulary=vocab,
        schema_root=ROOT / "schemas", observation_kind="task",
    )


def refuse_task(observations, vocab, **over) -> ExtractionError:
    with pytest.raises(ExtractionError) as excinfo:
        admit_task(observations, vocab, **over)
    return excinfo.value


def test_a_task_identity_is_keyed_on_its_product_not_its_capabilities():
    """ADR-068. ``capability_observation_ids`` is an array; an id derived from it
    would depend on how many were cited and in what order."""
    out = derived_task(task())
    assert out["normalized_task"] == "accept-a-customer-card-payment-to-get-paid-faster"
    assert out["task_observation_id"] == (
        f"{TASK_PRODUCT}:accept-a-customer-card-payment-to-get-paid-faster"
    )
    # Reordering or adding a cited capability cannot move the identity.
    both = derived_task(task(capability_observation_ids=[OTHER_CAPABILITY, TASK_CAPABILITY]))
    assert both["task_observation_id"] == out["task_observation_id"]


def test_the_collision_scope_falls_out_of_the_task_formula():
    """Two products may host the same task; only a within-product clash collides."""
    assert derived_task(task(product_observation_id=OTHER_PRODUCT))[
        "task_observation_id"
    ] != derived_task(task())["task_observation_id"]


def test_a_conforming_task_is_admitted(vocabulary):
    admit_task([task()], vocabulary)


def test_c9_refuses_a_capability_no_human_validated(vocabulary):
    error = refuse_task(
        [task(capability_observation_ids=[f"{TASK_PRODUCT}:invented-capability"])],
        vocabulary,
    )
    assert error.reason_code == "candidate_conformance_capability_not_in_snapshot"


def test_c9_refuses_a_task_that_cites_no_capability(vocabulary):
    """A task is performed *through* a capability; zero of them is not a task.

    An empty list is schema-valid -- ``capability_observation_ids`` declares no
    ``minItems`` -- so it reaches C9 rather than being recorded as
    ``schema_invalid``. That is the layering ADR-054 fixed: the released
    ``rejected[]`` enum is not widened to carry conformance failures.
    """
    error = refuse_task([task(capability_observation_ids=[])], vocabulary)
    assert error.reason_code == "candidate_conformance_capability_not_in_snapshot"


@pytest.mark.parametrize("cited", [None, "not-a-list", 7])
def test_a_non_list_capability_field_never_reaches_c9(vocabulary, cited):
    """It is a schema failure, and the pre-schema check owns saying so."""
    admit_task([task(capability_observation_ids=cited)], vocabulary)


def test_c10_refuses_a_capability_belonging_to_another_product(vocabulary):
    """Structurally unreachable today, and asserted anyway.

    Task discovery renders one product at a time, so the model never sees a
    second product's ``C0N``. This is the cheap insurance for the day that
    changes -- the assumption ADR-053, ADR-058, ADR-061, ADR-062 and ADR-064
    each watched go false.
    """
    error = refuse_task(
        [task(capability_observation_ids=[TASK_CAPABILITY, OTHER_CAPABILITY])],
        vocabulary,
    )
    assert error.reason_code == "candidate_conformance_capability_parent_mismatch"


def test_c9_and_c10_are_distinct_reason_codes():
    """"Nobody validated it" and "it belongs to another product" are different
    faults, and an operator needs to know which one happened."""
    from dynamic_ai_products.extraction import candidates

    assert candidates._C9 != candidates._C10
    assert candidates._C9 != candidates._C7


def test_c7_still_applies_to_the_tasks_own_product(vocabulary):
    error = refuse_task([task(product_observation_id=f"{COMPANY}:{CUTOFF}:invented")], vocabulary)
    assert error.reason_code == "candidate_conformance_parent_not_in_snapshot"


@pytest.mark.parametrize(
    "field, value, code",
    [("company_id", "OTHER-CO", "candidate_conformance_company_mismatch"),
     ("observation_cutoff", "2024-01-01", "candidate_conformance_cutoff_mismatch"),
     ("normalized_task", "Not A Slug", "candidate_conformance_normalized_name_invalid"),
     ("task_observation_id", "wrong", "candidate_conformance_observation_id_mismatch")],
)
def test_a_tampered_derived_task_field_is_caught(vocabulary, field, value, code):
    """C1-C4 apply to a task, unlike to a capability.

    ``task_observation`` requires ``company_id`` and ``observation_cutoff``; the
    capability schema has neither, which is why C7 replaces C1/C2 there. They
    are asserted the way the product ones are -- by tampering *after* derivation,
    because derivation supplies these fields and whatever the model emitted in
    them is discarded. So C1 and C2 catch a corrupted pipeline, not a bad model.
    """
    tampered = derived_task(task())
    tampered[field] = value
    with pytest.raises(ExtractionError) as excinfo:
        assert_candidate_conformance(
            [tampered], packet=task_packet(), vocabulary=vocabulary,
            schema_root=ROOT / "schemas", observation_kind="task",
        )
    assert excinfo.value.reason_code == code


def test_what_the_model_emits_in_the_derived_task_fields_is_discarded(vocabulary):
    """The other half of the same rule, stated as its own case."""
    admit_task([task(company_id="HUBSPOT INC", observation_cutoff="not-a-date",
                     task_observation_id="cand-001")], vocabulary)


def test_c5_governs_a_task_status_too(vocabulary):
    error = refuse_task([task(availability_status="planned")], vocabulary)
    assert error.reason_code == "candidate_conformance_status_not_governed"


def test_c8_governs_a_task_quote_too(vocabulary):
    error = refuse_task(
        [task(evidence=[{"source_id": SRC, "passage_id": PSG, "quote": "not in it"}])],
        vocabulary,
    )
    assert error.reason_code == "candidate_conformance_evidence_quote_uncontained"


def test_the_task_gate_reads_the_v2_schema_that_carries_normalized_task():
    from dynamic_ai_products.extraction import candidates

    assert candidates._SCHEMA_FOR_KIND["task"] == "task_observation_v2.schema.json"
    released = json.loads((ROOT / "schemas/task_observation.schema.json").read_text())
    successor = json.loads((ROOT / "schemas/task_observation_v2.schema.json").read_text())
    assert "normalized_task" not in released["properties"]
    assert "normalized_task" in successor["required"]
    # The successor adds one property and changes nothing else.
    assert set(successor["properties"]) - set(released["properties"]) == {"normalized_task"}
    assert set(released["properties"]) - set(successor["properties"]) == set()


def test_the_collection_contract_admits_a_task_collection():
    """ADR-069. ADR-068 added ``"task"`` to ``OBSERVATION_KINDS`` but left the
    collection's own released schema closed to ``["product", "capability"]`` in
    both places it appears -- found by the first end-to-end task
    materialization, not by inspection."""
    schema = json.loads(
        (ROOT / "schemas/extraction_candidate_collection.schema.json").read_text()
    )
    assert schema["properties"]["observation_kind"]["enum"] == [
        "product", "capability", "task",
    ]
    assert schema["properties"]["entries"]["items"]["properties"][
        "observation_kind"
    ]["enum"] == ["product", "capability", "task"]


# --- ADR-069 (E-T1 governance wiring): resolve_capability_refs, the fourth
# label family, and the focal product injection ------------------------------


def cap_observation(**over) -> dict:
    """A raw, pre-resolution task candidate, in the shape the model emits."""
    payload = {
        "task": "accept a customer card payment to get paid faster",
        "customer_need": "collect money from a buyer without extra tooling",
        "capability_refs": ["C1"],
        "availability_status": "general_availability",
        "confidence": "high",
        "evidence": [{"source_id": SRC, "passage_id": PSG, "quote": "x"}],
    }
    payload.update(over)
    return {k: v for k, v in payload.items() if v is not ...}


def two_cap_task_packet() -> dict:
    """A task packet whose focal product carries two capabilities.

    ``task_packet()`` gives every product exactly one, which cannot
    distinguish "resolved the second position" from "resolved the only
    position". This fixture exists only to test multi-entry resolution.
    """
    payload = task_packet()
    payload["parent_context"]["capability_parents"].append(
        {
            "observation_id": f"{TASK_PRODUCT}:issue-a-refund",
            "reference": "observations/capability/c.json",
            "sha256": "f" * 64,
            "payload": {
                "capability_observation_id": f"{TASK_PRODUCT}:issue-a-refund",
                "product_observation_id": TASK_PRODUCT,
                "capability": "issue a refund",
                "evidence": [{"source_id": SRC, "passage_id": PSG, "quote": "x"}],
            },
        }
    )
    return payload


def test_resolve_capability_refs_resolves_to_the_focal_products_capability():
    resolved = resolve_capability_refs(
        cap_observation(capability_refs=["C1"]),
        packet=task_packet(),
        focal_product_observation_id=TASK_PRODUCT,
    )
    assert resolved["capability_observation_ids"] == [TASK_CAPABILITY]
    assert "capability_refs" not in resolved


def test_resolve_capability_refs_is_scoped_to_the_focal_product_not_packet_position():
    """The same packet, a different focal product, resolves ``C1`` differently.

    ``TASK_CAPABILITY`` sits first in ``capability_parents`` and
    ``OTHER_CAPABILITY`` second, but each is the *only* capability of its own
    product -- so ``C1`` names ``OTHER_CAPABILITY`` when the focal product is
    ``OTHER_PRODUCT``. A resolver that read packet position instead of
    ``focal_capability_order`` would get this wrong.
    """
    resolved = resolve_capability_refs(
        cap_observation(capability_refs=["C1"]),
        packet=task_packet(),
        focal_product_observation_id=OTHER_PRODUCT,
    )
    assert resolved["capability_observation_ids"] == [OTHER_CAPABILITY]


def test_resolve_capability_refs_resolves_every_entry_in_order():
    packet_ = two_cap_task_packet()
    resolved = resolve_capability_refs(
        cap_observation(capability_refs=["C2", "C1"]),
        packet=packet_,
        focal_product_observation_id=TASK_PRODUCT,
    )
    assert resolved["capability_observation_ids"] == [
        f"{TASK_PRODUCT}:issue-a-refund",
        TASK_CAPABILITY,
    ]


@pytest.mark.parametrize("label", ["C2", "C99", "C0", "c1", "1", "", "CX", None, 1])
def test_an_unresolvable_capability_ref_has_its_own_reason_code(label):
    """Out of range or malformed, distinct from every other resolver's code.

    ``TASK_PRODUCT`` has exactly one capability in ``task_packet()``, so ``C2``
    is out of range there without needing a second fixture.
    """
    with pytest.raises(ExtractionError) as excinfo:
        resolve_capability_refs(
            cap_observation(capability_refs=[label]),
            packet=task_packet(),
            focal_product_observation_id=TASK_PRODUCT,
        )
    assert excinfo.value.reason_code == "candidate_conformance_capability_ref_unresolvable"


@pytest.mark.parametrize("refs", [None, "C1", 7])
def test_a_non_list_capability_refs_is_refused_before_any_label_is_read(refs):
    with pytest.raises(ExtractionError) as excinfo:
        resolve_capability_refs(
            cap_observation(capability_refs=refs),
            packet=task_packet(),
            focal_product_observation_id=TASK_PRODUCT,
        )
    assert excinfo.value.reason_code == "candidate_conformance_capability_ref_unresolvable"


@pytest.mark.parametrize("label", ["C01", "C1", "C0001"])
def test_any_padding_of_one_capability_ordinal_resolves_to_one_capability(label):
    """The same equivalence ADR-064 established for ``P0N``, pre-applied to
    ``C0N`` rather than discovered on a live call (ADR-069)."""
    resolved = resolve_capability_refs(
        cap_observation(capability_refs=[label]),
        packet=task_packet(),
        focal_product_observation_id=TASK_PRODUCT,
    )
    assert resolved["capability_observation_ids"] == [TASK_CAPABILITY]


def test_resolve_capability_refs_requires_a_focal_product():
    with pytest.raises(ExtractionError) as excinfo:
        resolve_capability_refs(
            cap_observation(), packet=task_packet(), focal_product_observation_id=None
        )
    assert excinfo.value.reason_code == "focal_product_required"


def test_resolve_capability_refs_leaves_untouched_what_it_does_not_own():
    for item in ("a string", 12, None):
        assert resolve_capability_refs(
            item, packet=task_packet(), focal_product_observation_id=TASK_PRODUCT
        ) is item
    already = cap_observation(capability_observation_ids=[TASK_CAPABILITY])
    del already["capability_refs"]
    assert resolve_capability_refs(
        already, packet=task_packet(), focal_product_observation_id=TASK_PRODUCT
    ) is already


def test_resolve_capability_refs_does_not_mutate_its_input():
    original = cap_observation(capability_refs=["C1"])
    snapshot = json.dumps(original, sort_keys=True)
    resolve_capability_refs(
        original, packet=task_packet(), focal_product_observation_id=TASK_PRODUCT
    )
    assert json.dumps(original, sort_keys=True) == snapshot


# --- the focal product injection: a value supplied, never a label resolved --


def test_the_focal_product_is_injected_regardless_of_what_the_model_wrote():
    from dynamic_ai_products.extraction.candidates import _inject_focal_product

    out = _inject_focal_product(
        {"product_observation_id": "whatever-the-model-guessed"},
        observation_kind="task",
        focal_product_observation_id=TASK_PRODUCT,
    )
    assert out["product_observation_id"] == TASK_PRODUCT


def test_the_focal_product_is_supplied_even_when_the_model_named_none():
    from dynamic_ai_products.extraction.candidates import _inject_focal_product

    out = _inject_focal_product(
        {"task": "x"}, observation_kind="task", focal_product_observation_id=TASK_PRODUCT
    )
    assert out["product_observation_id"] == TASK_PRODUCT


@pytest.mark.parametrize("kind", ["product", "capability"])
def test_the_injection_is_task_only(kind):
    from dynamic_ai_products.extraction.candidates import _inject_focal_product

    untouched = {"product_observation_id": "already-there"}
    out = _inject_focal_product(
        untouched, observation_kind=kind, focal_product_observation_id=TASK_PRODUCT
    )
    assert out is untouched


def test_the_injection_requires_a_focal_product_for_the_task_kind():
    from dynamic_ai_products.extraction.candidates import _inject_focal_product

    with pytest.raises(ExtractionError) as excinfo:
        _inject_focal_product(
            {"task": "x"}, observation_kind="task", focal_product_observation_id=None
        )
    assert excinfo.value.reason_code == "focal_product_required"


# --- materialize_candidate_collection, end to end, for the task kind --------


def _task_prediction(**over) -> dict:
    return envelope(json.dumps([cap_observation(**over)]))


def test_materialization_refuses_a_task_run_with_no_focal_product(tmp_path, vocabulary):
    """Checked before parsing, the same order the renderer already enforces."""
    vroot, vpin = _vocab_root(tmp_path, vocabulary)
    croot = tmp_path / "cand"
    croot.mkdir()
    with pytest.raises(ExtractionError) as excinfo:
        materialize_candidate_collection(
            raw_prediction=_task_prediction(),
            packet=task_packet(),
            raw_artifact_reference="data/runs/x/predictions/raw_prediction.json",
            raw_artifact_sha256="b" * 64,
            collection_root=croot,
            vocabulary_root=vroot,
            vocabulary_pin=vpin,
            repo_root=ROOT,
            schema_root=ROOT / "schemas",
            observation_kind="task",
        )
    assert excinfo.value.reason_code == "focal_product_required"
    assert list(croot.rglob("*")) == []


def test_a_conforming_task_run_materializes_end_to_end(tmp_path, vocabulary):
    """The full chain: capability_refs and the focal product resolve, then the
    derived task identity validates against the released successor schema."""
    vroot, vpin = _vocab_root(tmp_path, vocabulary)
    croot = tmp_path / "cand"
    croot.mkdir()
    pin = materialize_candidate_collection(
        raw_prediction=_task_prediction(availability_status="S5"),
        packet=task_packet(),
        raw_artifact_reference="data/runs/x/predictions/raw_prediction.json",
        raw_artifact_sha256="b" * 64,
        collection_root=croot,
        vocabulary_root=vroot,
        vocabulary_pin=vpin,
        repo_root=ROOT,
        schema_root=ROOT / "schemas",
        observation_kind="task",
        focal_product_observation_id=TASK_PRODUCT,
    )
    body = json.loads((croot / CANDIDATE_COLLECTION_REFERENCE).read_bytes())
    assert pin["sha256"] == hashlib.sha256(
        (croot / CANDIDATE_COLLECTION_REFERENCE).read_bytes()
    ).hexdigest()
    assert body["accepted_candidate_count"] == 1
    entry = body["entries"][0]["observation"]
    assert entry["product_observation_id"] == TASK_PRODUCT
    assert entry["capability_observation_ids"] == [TASK_CAPABILITY]
    assert entry["availability_status"] == "general_availability"
    assert "capability_refs" not in entry
    assert entry["task_observation_id"] == (
        f"{TASK_PRODUCT}:accept-a-customer-card-payment-to-get-paid-faster"
    )


# --- adversarial review fixes ----------------------------------------------
#
# Three findings, all reproduced against the code before they were fixed. The
# first two were silent: a corrupted packet and a doubled citation both produced
# an observation that looked like an ordinary bad model answer.


def _capability_parent(observation_id, product=TASK_PRODUCT, **over):
    parent = {
        "observation_id": observation_id,
        "reference": "observations/capability/x.json",
        "sha256": "f" * 64,
        "payload": {
            "capability_observation_id": observation_id,
            "product_observation_id": product,
            "capability": "some capability",
            "evidence": [{"source_id": SRC, "passage_id": PSG, "quote": "x"}],
        },
    }
    parent.update(over)
    return parent


def _packet_with_capability_parents(parents):
    payload = task_packet()
    payload["parent_context"]["capability_parents"] = parents
    return payload


def _drop(mapping, key):
    return {k: v for k, v in mapping.items() if k != key}


def _with_observation_id(value):
    parent = _capability_parent(TASK_CAPABILITY)
    parent["observation_id"] = value
    return parent


BROKEN_PARENTS = {
    "missing_observation_id": _drop(_capability_parent(TASK_CAPABILITY), "observation_id"),
    "null_observation_id": _with_observation_id(None),
    "blank_observation_id": _with_observation_id("   "),
    "non_string_observation_id": _with_observation_id(7),
}


@pytest.mark.parametrize("case", sorted(BROKEN_PARENTS))
def test_a_capability_parent_without_an_identity_stops_the_resolver(case):
    """Finding 1, first half -- and the one that fires first.

    Measured before the fix: this resolved to ``[None]``, which then failed the
    released schema and was recorded as an ordinary ``schema_invalid``
    candidate. A corrupted packet was being reported as a bad model answer.

    The refusal comes from ``focal_capability_order`` -- the single source both
    the renderer and this resolver read -- so ``C0N`` cannot name a position
    whose identity is missing at either end.
    """
    with pytest.raises(ExtractionError) as excinfo:
        resolve_capability_refs(
            {"capability_refs": ["C01"]},
            packet=_packet_with_capability_parents([BROKEN_PARENTS[case]]),
            focal_product_observation_id=TASK_PRODUCT,
        )
    assert excinfo.value.reason_code == "contents_context_invalid"


@pytest.mark.parametrize("case", sorted(BROKEN_PARENTS))
def test_a_capability_parent_without_an_identity_stops_c9s_universe(case):
    """Finding 1, second half -- defence in depth, not a duplicate.

    ``_capability_observation_ids`` reads *all* capability parents, not only the
    focal product's, and it is the universe C9 and C10 judge against. Before the
    fix ``str(None)`` made the literal ``"None"`` a valid key, so C9 would have
    admitted a task citing nothing at all.
    """
    from dynamic_ai_products.extraction.candidates import _capability_observation_ids

    with pytest.raises(ExtractionError) as excinfo:
        _capability_observation_ids(
            _packet_with_capability_parents([BROKEN_PARENTS[case]])
        )
    assert excinfo.value.reason_code == (
        "candidate_conformance_capability_context_malformed"
    )


def test_a_capability_parent_without_an_owner_stops_c10s_universe():
    """C10 compares against ``product_observation_id``; a missing one coerced to
    the string ``"None"`` and would have been compared as if it were real."""
    from dynamic_ai_products.extraction.candidates import _capability_observation_ids

    parent = _capability_parent(TASK_CAPABILITY)
    parent["payload"] = _drop(parent["payload"], "product_observation_id")
    with pytest.raises(ExtractionError) as excinfo:
        _capability_observation_ids(_packet_with_capability_parents([parent]))
    assert excinfo.value.reason_code == (
        "candidate_conformance_capability_context_malformed"
    )


def test_a_malformed_context_is_not_reported_as_c9():
    """Finding 1's reason-code decision, asserted.

    "The model cited a capability nobody validated" is a statement about the
    answer; "this run's capability context is corrupt" is a statement about the
    question. An operator chasing the first would never find the second, so the
    codes are kept apart -- ADR-055's rule applied one level up.
    """
    from dynamic_ai_products.extraction import candidates

    assert candidates._CAPABILITY_CONTEXT_MALFORMED != candidates._C9
    assert candidates._CAPABILITY_CONTEXT_MALFORMED != candidates._C10
    assert candidates._CAPABILITY_CONTEXT_MALFORMED != candidates._C11


@pytest.mark.parametrize(
    "refs", [["C01", "C01"], ["C1", "C01"], ["C01", "C1"], ["C1", "C1", "C01"]]
)
def test_c11_refuses_the_same_capability_cited_twice(vocabulary, refs):
    """Finding 2. The check is on the resolved ids, not the labels.

    ``C1`` and ``C01`` are different strings for one position, so a check on the
    raw labels would let the second spelling through. Refused rather than
    deduplicated: collapsing the list silently would be a repair nobody logged,
    and a downstream reader counting ``len(capability_observation_ids)`` would
    otherwise be told a task rests on two capabilities when it rests on one.
    """
    resolved = resolve_capability_refs(
        {"capability_refs": refs},
        packet=task_packet(),
        focal_product_observation_id=TASK_PRODUCT,
    )
    error = refuse_task([task(**_drop(resolved, "capability_refs"))], vocabulary)
    assert error.reason_code == "candidate_conformance_capability_cited_twice"


def test_a_single_capability_reference_is_still_admitted(vocabulary):
    """The contrast case: one label, one capability, still fine."""
    resolved = resolve_capability_refs(
        {"capability_refs": ["C01"]},
        packet=task_packet(),
        focal_product_observation_id=TASK_PRODUCT,
    )
    assert resolved["capability_observation_ids"] == [TASK_CAPABILITY]
    admit_task([task(capability_observation_ids=[TASK_CAPABILITY])], vocabulary)


def test_c11_is_not_folded_into_c9(vocabulary):
    """Two citations of one real capability is a different fault from citing an
    unvalidated one, and each keeps its own code."""
    duplicated = refuse_task(
        [task(capability_observation_ids=[TASK_CAPABILITY, TASK_CAPABILITY])], vocabulary
    )
    invented = refuse_task(
        [task(capability_observation_ids=[f"{TASK_PRODUCT}:invented"])], vocabulary
    )
    assert duplicated.reason_code == "candidate_conformance_capability_cited_twice"
    assert invented.reason_code == "candidate_conformance_capability_not_in_snapshot"


def test_the_prompt_names_each_derived_field_with_its_own_source():
    """Finding 3. The imperative was right; the reason sentence was not.

    It said the first three of four derived fields come "from this call's
    product and your capability_refs", which mixes them: ``task_observation_id``
    never derives from ``capability_refs``, and ``capability_observation_ids``
    never derives from the product.
    """
    text = (ROOT / "prompts/extraction/task_discovery_schema_v1.md").read_text()
    assert "`product_observation_id` from this call's product" in text
    assert "`capability_observation_ids`\nfrom your `capability_refs`" in text
    assert "`normalized_task` from your `task`" in text
    assert "`task_observation_id` from this call's product together with your `task`" in text
    assert "the first three from this" not in text


def test_the_change_request_pins_the_prompt_it_actually_describes():
    """A digest a document states about a file it names has to be that file's.

    Asserted against the bytes rather than a literal, so this states the
    invariant without minting a second place the value must be kept in step.
    """
    from hashlib import sha256

    prompt = ROOT / "prompts/extraction/task_discovery_schema_v1.md"
    change_request = (
        ROOT / "evals/change_requests"
        / "CR-0008-task-discovery-schema-v1-bootstrap-qualification.md"
    ).read_text()
    payload = prompt.read_bytes()
    assert sha256(payload).hexdigest() in change_request
    assert f"({len(payload)} bytes)" in change_request
