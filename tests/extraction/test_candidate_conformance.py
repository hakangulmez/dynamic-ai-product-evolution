"""Derived identity, the parse gates, and the C1-C6 conformance gate (ADR-054, G6-M).

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
        label = passage_ref_label(ordinal)
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
    assert passage_ref_label(ordinal) == expected


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
    ["P004", "P999", "P000", "p001", "P1", "P01", "001", "", "PABC", None, 1],
    ids=["out_of_range", "far_out", "zero", "lowercase", "one_digit", "two_digits",
         "no_prefix", "empty", "letters", "null", "int"],
)
def test_an_unresolvable_label_has_its_own_reason_code(label):
    """Not folded into the unknown-pair code.

    "Invented an identifier" and "named a position it was not shown" are
    different faults, and an operator needs to know which one happened.
    """
    with pytest.raises(ExtractionError) as excinfo:
        resolve_evidence_refs(
            observation(evidence=[{"ref": label, "quote": "q"}]), packet=UNSORTED
        )
    assert excinfo.value.reason_code == "candidate_conformance_evidence_ref_unresolvable"


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
