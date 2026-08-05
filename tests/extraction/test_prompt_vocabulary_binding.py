"""The successor prompt, the registry move, and the offline binding (ADR-053, G6-P).

Nothing here calls a provider, resolves credentials, or touches a run root. The
binding check is a pure function over prompt text and a vocabulary mapping, and
the schema conformance cases are hand-written documents validated offline
against the released ``product_observation`` schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.availability_vocabulary import (
    AVAILABILITY_PARTITION_FIELDS,
    build_availability_vocabulary,
    parse_prompt_status_vocabulary,
    validate_prompt_vocabulary_binding,
)
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.prompts import (
    EXTRACTION_PROMPTS,
    PROMPT_REGISTRY_VERSION,
    VOCABULARY_BOUND_PROMPT_IDS,
    load_prompt,
    single_pass_prompt_plan,
)

ROOT = Path(__file__).resolve().parents[2]
SUCCESSOR_ID = "product_discovery_schema_v4"
PREDECESSOR_ID = "product_discovery_schema_v3"
OLDER_ID = "product_discovery_schema_v2"
RECALL_ID = "product_discovery_recall"
STAGE = "product_extraction"

LOCKED_ACTIVE = [
    "broadly_deployed_or_default",
    "general_availability",
    "private_beta",
    "public_beta",
]
LOCKED_ROADMAP = ["announced"]
LOCKED_NON_ACTIVE_KNOWN = ["deprecated", "discontinued"]


@pytest.fixture(scope="module")
def prompt_text() -> str:
    return load_prompt(ROOT, SUCCESSOR_ID)["text"]


@pytest.fixture(scope="module")
def vocabulary() -> dict:
    """The artifact, built in memory. No run root is read or created."""
    return build_availability_vocabulary(
        vocabulary_version="product-candidate-availability-v1",
        active_status_values=LOCKED_ACTIVE,
        roadmap_status_values=LOCKED_ROADMAP,
        non_active_known_status_values=LOCKED_NON_ACTIVE_KNOWN,
        decided_by="test fixture",
        decided_at="2026-08-04T00:00:00+00:00",
        repo_root=ROOT,
    )


# --- the registry move ------------------------------------------------------


def test_the_registry_version_tracks_the_sequence():
    # ADR-055 moved it again when the label-citing successor took position one.
    assert PROMPT_REGISTRY_VERSION == "extraction_prompt_registry_v5"


def test_the_successor_is_first_and_every_predecessor_is_retained():
    """Nothing is ever unregistered: each archived run must stay verifiable."""
    assert EXTRACTION_PROMPTS[STAGE] == (
        SUCCESSOR_ID,
        PREDECESSOR_ID,
        OLDER_ID,
        RECALL_ID,
        "product_consolidation_precision",
    )


def test_a_single_pass_now_executes_the_successor():
    plan = single_pass_prompt_plan(STAGE)
    assert plan == {
        "prompt_id": SUCCESSOR_ID,
        "prompt_pass_index": 1,
        "prompt_sequence_length": 5,
        "prompt_sequence_complete": False,
    }


@pytest.mark.parametrize("prompt_id", [PREDECESSOR_ID, OLDER_ID, RECALL_ID])
def test_the_predecessor_prompt_bytes_are_untouched(prompt_id):
    """``ext-smoke-0002`` resolved these bytes; the chain stays verifiable.

    The digest is asserted against the committed file rather than a literal, so
    this test states the invariant -- unchanged -- without minting a second
    place the value has to be kept in step.
    """
    import subprocess

    committed = subprocess.check_output(
        ["git", "show", f"HEAD:prompts/extraction/{prompt_id}.md"],
        cwd=ROOT,
    )
    on_disk = (ROOT / "prompts" / "extraction" / f"{prompt_id}.md").read_bytes()
    assert on_disk == committed


def test_the_vocabulary_bound_set_names_every_prompt_carrying_the_block():
    """Every schema-bound prompt carries the literal vocabulary; the recall ones do not.

    ADR-059 adds the capability successor: ``availability_status`` is an
    unconstrained string in the capability schema too, so C5 governs it there
    and the prompt must carry the same four labelled lists.
    """
    assert VOCABULARY_BOUND_PROMPT_IDS == frozenset(
        {SUCCESSOR_ID, PREDECESSOR_ID, OLDER_ID, "capability_discovery_schema_v1"}
    )
    assert isinstance(VOCABULARY_BOUND_PROMPT_IDS, frozenset)
    assert RECALL_ID not in VOCABULARY_BOUND_PROMPT_IDS


def test_every_registered_prompt_resolves_to_a_file():
    for stage, ids in EXTRACTION_PROMPTS.items():
        for prompt_id in ids:
            record = load_prompt(ROOT, prompt_id)
            assert record["prompt_id"] == prompt_id
            assert record["byte_count"] > 0, (stage, prompt_id)


# --- parsing the canonical block --------------------------------------------


def test_the_four_lists_parse_exactly(prompt_text):
    assert parse_prompt_status_vocabulary(prompt_text) == {
        "active_status_values": LOCKED_ACTIVE,
        "non_active_known_status_values": LOCKED_NON_ACTIVE_KNOWN,
        "roadmap_status_values": LOCKED_ROADMAP,
        "unknown_status_values": ["unknown"],
    }


def test_the_parser_reads_a_continued_line(prompt_text):
    """``active_status_values`` spans two lines in the authored prompt.

    That is a property of the committed text, not of the test's own fixture, so
    it is asserted against the file: a future edit that joined the line would
    make this test vacuous without anyone noticing.
    """
    # ADR-056 put a label table above the four-list block, so the block is
    # located by the label it must contain rather than by counting fences.
    block = prompt_text.split("### `availability_status`", 1)[1]
    fenced = next(
        chunk for chunk in block.split("```")
        if any(line.startswith("active_status_values") for line in chunk.splitlines())
    )
    active_line = next(
        line for line in fenced.splitlines() if line.startswith("active_status_values")
    )
    assert "private_beta" not in active_line
    assert parse_prompt_status_vocabulary(prompt_text)["active_status_values"] == (
        LOCKED_ACTIVE
    )


def test_the_labels_also_appear_in_prose_and_the_parser_ignores_them(prompt_text):
    """Scoping to the fenced block is load-bearing, not tidiness.

    The prompt explains what ``active_status_values`` means in a sentence
    outside the block. A document-wide scan would read that sentence as data.
    """
    prose = prompt_text.split("```", 4)[-1]
    assert "`active_status_values` means" in prose
    assert parse_prompt_status_vocabulary(prompt_text)["active_status_values"] == (
        LOCKED_ACTIVE
    )


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "no fenced block at all",
        "```\nactive_status_values : private_beta\n```",
        "```\nactive_status_values : a\nroadmap_status_values : b\n```",
    ],
    ids=["empty", "blank", "no_block", "one_label", "two_labels"],
)
def test_a_block_missing_any_label_is_refused(text):
    with pytest.raises(ExtractionError) as excinfo:
        parse_prompt_status_vocabulary(text)
    assert excinfo.value.reason_code == "prompt_vocabulary_block_invalid"


def test_two_candidate_blocks_are_refused(prompt_text):
    doubled = prompt_text + "\n\n" + prompt_text
    with pytest.raises(ExtractionError) as excinfo:
        parse_prompt_status_vocabulary(doubled)
    assert excinfo.value.reason_code == "prompt_vocabulary_block_invalid"


def _block(active="private_beta", roadmap="announced",
           non_active="deprecated", unknown="unknown", order=None) -> str:
    lines = {
        "active_status_values": active,
        "roadmap_status_values": roadmap,
        "non_active_known_status_values": non_active,
        "unknown_status_values": unknown,
    }
    order = order or [
        "active_status_values",
        "roadmap_status_values",
        "non_active_known_status_values",
        "unknown_status_values",
    ]
    body = "\n".join(f"{label} : {lines[label]}" for label in order)
    return f"```\n{body}\n```"


def test_a_reordered_block_is_refused():
    reordered = _block(order=[
        "roadmap_status_values",
        "active_status_values",
        "non_active_known_status_values",
        "unknown_status_values",
    ])
    with pytest.raises(ExtractionError) as excinfo:
        parse_prompt_status_vocabulary(reordered)
    assert excinfo.value.reason_code == "prompt_vocabulary_block_invalid"


def test_a_repeated_label_is_refused():
    text = _block() .replace("```\n", "```\nactive_status_values : public_beta\n", 1)
    with pytest.raises(ExtractionError) as excinfo:
        parse_prompt_status_vocabulary(text)
    assert excinfo.value.reason_code == "prompt_vocabulary_block_invalid"


@pytest.mark.parametrize(
    "active",
    ["Private_Beta", "private beta", "private-beta", ",", "  "],
    ids=["uppercase", "space", "hyphen", "only_comma", "blank"],
)
def test_a_malformed_token_in_the_block_is_refused(active):
    with pytest.raises(ExtractionError) as excinfo:
        parse_prompt_status_vocabulary(_block(active=active))
    assert excinfo.value.reason_code == "prompt_vocabulary_block_invalid"


# --- B4a through B4e --------------------------------------------------------


def test_the_committed_prompt_binds_to_the_vocabulary(prompt_text, vocabulary):
    parsed = validate_prompt_vocabulary_binding(
        prompt_text=prompt_text, vocabulary=vocabulary
    )
    for label in AVAILABILITY_PARTITION_FIELDS:
        assert parsed[label] == vocabulary[label]
    assert sorted(t for v in parsed.values() for t in v) == (
        vocabulary["admitted_status_values"]
    )


@pytest.mark.parametrize(
    "label, check",
    [
        ("active_status_values", "B4a"),
        ("roadmap_status_values", "B4b"),
        ("non_active_known_status_values", "B4c"),
        ("unknown_status_values", "B4d"),
    ],
)
def test_each_list_is_bound_separately(prompt_text, vocabulary, label, check):
    """Four separate equalities, and the error says which one broke."""
    drifted = dict(vocabulary)
    drifted[label] = ["announced"] if label != "roadmap_status_values" else ["unknown"]
    with pytest.raises(ExtractionError) as excinfo:
        validate_prompt_vocabulary_binding(
            prompt_text=prompt_text, vocabulary=drifted
        )
    assert excinfo.value.reason_code == "prompt_vocabulary_binding_mismatch"
    assert check in str(excinfo.value)


def test_a_label_swap_is_caught_although_the_union_is_unchanged(
    prompt_text, vocabulary
):
    """The defect ordered equality exists for.

    Swapping the ``active`` and ``roadmap`` contents leaves every set, and the
    union, exactly as it was. Only a position-by-position comparison refuses it.
    """
    swapped = dict(vocabulary)
    swapped["active_status_values"] = list(vocabulary["roadmap_status_values"])
    swapped["roadmap_status_values"] = list(vocabulary["active_status_values"])

    before = sorted(
        t for label in AVAILABILITY_PARTITION_FIELDS for t in vocabulary[label]
    )
    after = sorted(
        t for label in AVAILABILITY_PARTITION_FIELDS for t in swapped[label]
    )
    assert before == after, "the swap must leave the union untouched"

    with pytest.raises(ExtractionError) as excinfo:
        validate_prompt_vocabulary_binding(
            prompt_text=prompt_text, vocabulary=swapped
        )
    assert excinfo.value.reason_code == "prompt_vocabulary_binding_mismatch"


def test_ordering_within_a_list_is_binding_not_just_membership(
    prompt_text, vocabulary
):
    reordered = dict(vocabulary)
    reordered["active_status_values"] = list(reversed(LOCKED_ACTIVE))
    assert set(reordered["active_status_values"]) == set(LOCKED_ACTIVE)
    with pytest.raises(ExtractionError) as excinfo:
        validate_prompt_vocabulary_binding(
            prompt_text=prompt_text, vocabulary=reordered
        )
    assert excinfo.value.reason_code == "prompt_vocabulary_binding_mismatch"
    assert "B4a" in str(excinfo.value)


def test_b4e_catches_an_admitted_field_that_disagrees_with_its_own_partition(
    prompt_text, vocabulary
):
    """B4e is not implied by B4a-d.

    Every list still matches; only the artifact's own ``admitted`` field is
    wrong. The loader would refuse such a document, but this function is also
    used on documents the loader has not seen.
    """
    inconsistent = dict(vocabulary)
    inconsistent["admitted_status_values"] = [
        v for v in vocabulary["admitted_status_values"] if v != "unknown"
    ]
    with pytest.raises(ExtractionError) as excinfo:
        validate_prompt_vocabulary_binding(
            prompt_text=prompt_text, vocabulary=inconsistent
        )
    assert excinfo.value.reason_code == "prompt_vocabulary_binding_mismatch"
    assert "B4e" in str(excinfo.value)


def test_the_recall_prompt_carries_no_block_and_cannot_bind(vocabulary):
    text = load_prompt(ROOT, RECALL_ID)["text"]
    with pytest.raises(ExtractionError) as excinfo:
        validate_prompt_vocabulary_binding(prompt_text=text, vocabulary=vocabulary)
    assert excinfo.value.reason_code == "prompt_vocabulary_block_invalid"


def test_the_binding_check_opens_no_file(prompt_text, vocabulary, monkeypatch):
    """Pure by demonstration, not by assertion in a docstring."""
    def _refuse(*args, **kwargs):  # pragma: no cover - must never run
        raise AssertionError("the binding check must not touch the filesystem")

    monkeypatch.setattr(Path, "read_bytes", _refuse)
    monkeypatch.setattr(Path, "read_text", _refuse)
    monkeypatch.setattr(Path, "open", _refuse)
    validate_prompt_vocabulary_binding(
        prompt_text=prompt_text, vocabulary=vocabulary
    )


# --- offline schema conformance of the prompt's declared output shape --------


PRODUCT_OBSERVATION_SCHEMA = json.loads(
    (ROOT / "schemas" / "product_observation.schema.json").read_text(encoding="utf-8")
)


def _candidate(**over) -> dict:
    payload = {
        "product_observation_id": "cand-001",
        "company_id": "HubSpot, Inc.",
        "observation_cutoff": "2025-02-12",
        "product_name": "Marketing Hub",
        "availability_status": "general_availability",
        "confidence": "high",
        "evidence": [
            {
                "source_id": "src-0001",
                "passage_id": "psg-0007",
                "quote": "Marketing Hub is generally available to all customers.",
            }
        ],
    }
    payload.update(over)
    return {k: v for k, v in payload.items() if v is not ...}


# Three documents in exactly the shape the successor prompt asks for: a minimal
# required-only candidate, one carrying the optional fields, and one recording
# an unknown status rather than guessing.
EXAMPLE_OUTPUT = [
    _candidate(),
    _candidate(
        product_observation_id="cand-002",
        product_name="Sales Hub Enterprise",
        product_family="Sales Hub",
        normalized_name="sales hub enterprise",
        entity_type="plan",
        target_customers=["enterprise sales teams"],
        availability_status="public_beta",
        confidence="medium",
        ambiguity="Packaging relative to Sales Hub Professional is not stated.",
        evidence=[
            {
                "source_id": "src-0002",
                "passage_id": "psg-0011",
                "quote": "Sales Hub Enterprise entered public beta.",
            }
        ],
    ),
    _candidate(
        product_observation_id="cand-003",
        product_name="Operations Hub",
        availability_status="unknown",
        confidence="unknown",
        evidence=[
            {
                "source_id": "src-0003",
                "passage_id": "psg-0019",
                "quote": "Operations Hub is referenced in the product list.",
            }
        ],
    ),
]


@pytest.mark.parametrize("index", range(len(EXAMPLE_OUTPUT)))
def test_each_example_candidate_validates_against_the_released_schema(index):
    Draft202012Validator(PRODUCT_OBSERVATION_SCHEMA).validate(EXAMPLE_OUTPUT[index])


def test_the_examples_cover_required_only_optional_and_unknown():
    required = set(PRODUCT_OBSERVATION_SCHEMA["required"])
    assert set(EXAMPLE_OUTPUT[0]) == required
    assert set(EXAMPLE_OUTPUT[1]) > required
    assert EXAMPLE_OUTPUT[2]["availability_status"] == "unknown"


def test_the_examples_only_use_tokens_the_prompt_declares(prompt_text):
    declared = {
        token
        for tokens in parse_prompt_status_vocabulary(prompt_text).values()
        for token in tokens
    }
    for candidate in EXAMPLE_OUTPUT:
        assert candidate["availability_status"] in declared


def test_candidate_status_is_rejected_by_the_released_schema():
    """The predecessor prompt's second defect, refused mechanically.

    ``product_observation.schema.json`` is ``additionalProperties: false`` and
    declares no ``candidate_status``, so a document carrying that field cannot
    validate. The successor prompt never asks for it.
    """
    assert PRODUCT_OBSERVATION_SCHEMA["additionalProperties"] is False
    assert "candidate_status" not in PRODUCT_OBSERVATION_SCHEMA["properties"]
    polluted = _candidate(candidate_status="active")
    assert not Draft202012Validator(PRODUCT_OBSERVATION_SCHEMA).is_valid(polluted)


def test_the_successor_prompt_never_asks_for_candidate_status(prompt_text):
    assert "candidate_status" not in prompt_text


def test_the_successor_prompt_names_every_required_schema_field(prompt_text):
    for field in PRODUCT_OBSERVATION_SCHEMA["required"]:
        assert f"`{field}`" in prompt_text, field


def test_every_optional_field_the_prompt_names_exists_in_the_schema(prompt_text):
    """The prompt may not invent a field the released schema would refuse."""
    named = {
        "product_family",
        "normalized_name",
        "entity_type",
        "target_customers",
        "ambiguity",
    }
    for field in named:
        assert f"`{field}`" in prompt_text, field
        assert field in PRODUCT_OBSERVATION_SCHEMA["properties"], field


# --- ADR-059 (E-S2): the schema-bound capability prompt ---------------------


CAPABILITY_ID = "capability_discovery_schema_v1"
RETIRED_CAPABILITY_ID = "capability_extraction"
CAPABILITY_OBSERVATION_SCHEMA = json.loads(
    (ROOT / "schemas" / "capability_observation.schema.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def capability_prompt_text() -> str:
    return load_prompt(ROOT, CAPABILITY_ID)["text"]


def test_the_capability_successor_is_first_and_the_retired_one_is_retained():
    assert EXTRACTION_PROMPTS["capability_extraction"] == (
        CAPABILITY_ID,
        RETIRED_CAPABILITY_ID,
    )
    plan = single_pass_prompt_plan("capability_extraction")
    assert plan["prompt_id"] == CAPABILITY_ID
    assert plan["prompt_sequence_complete"] is False


def test_the_retired_capability_prompt_bytes_are_untouched():
    import subprocess

    committed = subprocess.check_output(
        ["git", "show", f"HEAD:prompts/extraction/{RETIRED_CAPABILITY_ID}.md"], cwd=ROOT
    )
    on_disk = (
        ROOT / "prompts" / "extraction" / f"{RETIRED_CAPABILITY_ID}.md"
    ).read_bytes()
    assert on_disk == committed


def test_the_capability_prompt_binds_to_the_same_vocabulary(
    capability_prompt_text, vocabulary
):
    """One vocabulary artifact governs both stages.

    ``availability_status`` is an unconstrained string in the capability schema
    too, so C5 has the same job there and the prompt carries the same four
    labelled lists.
    """
    parsed = validate_prompt_vocabulary_binding(
        prompt_text=capability_prompt_text, vocabulary=vocabulary
    )
    for label in AVAILABILITY_PARTITION_FIELDS:
        assert parsed[label] == vocabulary[label]


def test_the_capability_prompt_uses_every_bound_placeholder(capability_prompt_text):
    """Including ``validated_products``, which the ADR-058 gate requires."""
    import re

    from dynamic_ai_products.extraction.contents_renderer import (
        STAGE_PLACEHOLDER_BINDINGS,
        STAGE_REQUIRED_PLACEHOLDERS,
    )

    used = set(re.findall(r"\{\{([a-z_]+)\}\}", capability_prompt_text))
    assert used == set(STAGE_PLACEHOLDER_BINDINGS["capability_extraction"])
    assert set(STAGE_REQUIRED_PLACEHOLDERS["capability_extraction"]) <= used


def test_the_capability_prompt_asks_for_labels_and_no_identifier(capability_prompt_text):
    """Three label mechanisms, zero transcription -- ADR-054/055/056 carried over."""
    text = capability_prompt_text
    assert "`parent_ref`" in text and '"A01"' in text
    assert '{"ref": ..., "quote": ...}' in text
    assert "Never emit `source_id` or `passage_id`" in text
    assert "Do **not** emit an identifier of any kind" in text


def test_the_capability_prompt_renders_the_generated_status_table(capability_prompt_text):
    from dynamic_ai_products.extraction.availability_vocabulary import (
        status_label_table,
    )

    for label, token in status_label_table():
        assert f"{label}  =  {token}" in capability_prompt_text


def test_the_capability_prompt_names_every_field_the_model_must_supply(
    capability_prompt_text,
):
    for field in ("parent_ref", "capability", "availability_status", "confidence",
                  "evidence"):
        assert f"`{field}`" in capability_prompt_text
    # Optional, on the evidence-supported-or-omitted rule. SPEC-009's prose calls
    # input/output types required; the released schema does not list them, and
    # the schema is the contract.
    for field in ("input_types", "output_types", "ambiguity"):
        assert f"`{field}`" in capability_prompt_text
        assert field in CAPABILITY_OBSERVATION_SCHEMA["properties"], field
        assert field not in CAPABILITY_OBSERVATION_SCHEMA["required"], field


def test_the_derived_fields_are_named_only_as_derived(capability_prompt_text):
    """The three the pipeline owns are mentioned to forbid them, not request them."""
    forbidden_block = capability_prompt_text.split(
        "Do **not** emit an identifier of any kind", 1
    )[1]
    for derived in ("capability_observation_id", "product_observation_id",
                    "normalized_capability"):
        assert derived in forbidden_block, derived


def test_the_retired_capability_prompt_could_not_have_conformed():
    """The defect CR-0005 records, asserted rather than described."""
    text = (
        ROOT / "prompts" / "extraction" / f"{RETIRED_CAPABILITY_ID}.md"
    ).read_text(encoding="utf-8")
    missing = [
        field
        for field in CAPABILITY_OBSERVATION_SCHEMA["required"]
        if field not in text
    ]
    assert set(missing) == {
        "capability_observation_id",
        "product_observation_id",
        "availability_status",
    }
    assert "{{" not in text
