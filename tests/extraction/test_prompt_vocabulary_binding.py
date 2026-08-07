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
    # ADR-064 moved it once more, for the capability successor. ADR-065 moved
    # it to v7 for the quote bound. ADR-069 moves it to v8 for the task
    # successor.
    assert PROMPT_REGISTRY_VERSION == "extraction_prompt_registry_v8"


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
        {
            SUCCESSOR_ID,
            PREDECESSOR_ID,
            OLDER_ID,
            "capability_discovery_schema_v1",
            "capability_discovery_schema_v2",
            "capability_discovery_schema_v3",
            # ADR-069. ``availability_status`` is unconstrained in
            # ``task_observation_v2.schema.json`` too.
            "task_discovery_schema_v1",
        }
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


# ADR-064. The content assertions below follow position one, which is now the
# successor. v1 keeps its own test: its bytes must not move, because
# ext-smoke-cap-0001 and ext-smoke-cap-0002 resolved it.
CAPABILITY_ID = "capability_discovery_schema_v3"
PRIOR_CAPABILITY_ID = "capability_discovery_schema_v2"
OLDEST_CAPABILITY_ID = "capability_discovery_schema_v1"
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
        PRIOR_CAPABILITY_ID,
        OLDEST_CAPABILITY_ID,
        RETIRED_CAPABILITY_ID,
    )
    plan = single_pass_prompt_plan("capability_extraction")
    assert plan["prompt_id"] == CAPABILITY_ID
    assert plan["prompt_sequence_complete"] is False


@pytest.mark.parametrize(
    "prompt_id",
    [RETIRED_CAPABILITY_ID, OLDEST_CAPABILITY_ID, PRIOR_CAPABILITY_ID,
     "product_discovery_schema_v4"],
)
def test_a_superseded_prompts_bytes_are_untouched(prompt_id):
    """Superseding adds a file; it never edits one.

    ADR-064 adds the two that matter for this increment: v1, which
    ``ext-smoke-cap-0001`` and ``ext-smoke-cap-0002`` resolved, and the product
    successor, whose padded-label instruction this change deliberately leaves
    alone.
    """
    import subprocess

    committed = subprocess.check_output(
        ["git", "show", f"HEAD:prompts/extraction/{prompt_id}.md"], cwd=ROOT
    )
    on_disk = (ROOT / "prompts" / "extraction" / f"{prompt_id}.md").read_bytes()
    assert on_disk == committed


# --- ADR-064: the prompt and the renderer describe one label ----------------


def test_each_stage_prompt_describes_the_label_its_stage_renders():
    """The defect this closes was the two disagreeing.

    v1 told the model "at least three digits" and the renderer emitted ``P025``;
    the model wrote ``P25`` anyway, identically on two live runs. Asserting the
    agreement here means a future style change cannot move one without the
    other silently.
    """
    from dynamic_ai_products.extraction.contents_renderer import passage_ref_label

    capability = load_prompt(ROOT, CAPABILITY_ID)["text"]
    product = load_prompt(ROOT, SUCCESSOR_ID)["text"]

    assert passage_ref_label(25, stage="capability_extraction") == "P25"
    assert "P25" in capability
    assert "at least three digits" not in capability
    assert "no leading zeros" in capability

    assert passage_ref_label(1, stage="product_extraction") == "P001"
    assert "at least three" in product and "P001" in product


@pytest.mark.parametrize(
    "prior_id, successor_id, dropped",
    [
        (
            OLDEST_CAPABILITY_ID,
            PRIOR_CAPABILITY_ID,
            [
                "# Capability Discovery -- High Recall -- Schema v1",
                "[ref: P001] [passage_id: ...] [source_id: ...] [publication_date: ...]",
                "- `ref`: the label of one passage shown above, copied exactly -- the letter `P`",
                '  followed by at least three digits, for example `"P001"`.',
            ],
        ),
        (
            PRIOR_CAPABILITY_ID,
            CAPABILITY_ID,
            [
                "# Capability Discovery -- High Recall -- Schema v2",
                "- `quote`: text quoted verbatim from that same passage.",
            ],
        ),
    ],
    ids=["v1_to_v2_label_style", "v2_to_v3_quote_bound"],
)
def test_each_supersession_changes_exactly_one_thing(prior_id, successor_id, dropped):
    """Every capability successor is its predecessor plus one narrow edit.

    Asserted line by line so a supersession that quietly rewrote the status
    table, the parent rules or the schema contract would fail here rather than
    be found by reading two 160-line prompts side by side.
    """
    successor = load_prompt(ROOT, successor_id)["text"].splitlines()
    prior = load_prompt(ROOT, prior_id)["text"].splitlines()
    assert [line for line in prior if line not in successor] == dropped


def test_the_quote_bound_is_stated_in_the_successor():
    """ADR-065. The bound lives in the prompt and nowhere else, by decision.

    Nothing enforces one to three sentences -- not the schema, not C6, not C8 --
    so this test is the only place that says the instruction is present at all.
    """
    text = load_prompt(ROOT, CAPABILITY_ID)["text"]
    evidence = text.split("### `evidence`", 1)[1].split("### `parent_ref`", 1)[0]
    assert "1 to 3\n  sentences" in evidence
    assert "not the\n  entire passage" in evidence
    assert "without joining text across a gap" in evidence
    assert "- Every `quote` is 1 to 3 sentences, contiguous, and copied exactly." in text


def test_the_quote_bound_is_absent_from_every_predecessor():
    """The successor is what introduced it; the retained chains did not carry it."""
    for prompt_id in (PRIOR_CAPABILITY_ID, OLDEST_CAPABILITY_ID, SUCCESSOR_ID):
        assert "1 to 3" not in load_prompt(ROOT, prompt_id)["text"], prompt_id


def test_the_quote_bound_is_not_enforced_anywhere_in_code():
    """The honest half of ADR-065, asserted rather than assumed.

    Quote length is a quality preference, not an integrity property: C6 proves
    the cited pair is a passage of this run and C8 proves the words occur
    verbatim in it, and both hold identically at any length. If a length gate is
    ever added, this test is where the decision gets revisited.
    """
    for name in ("product_observation", "capability_observation"):
        schema = json.loads((ROOT / "schemas" / f"{name}.schema.json").read_text())
        quote = schema["properties"]["evidence"]["items"]["properties"]["quote"]
        assert quote == {"type": "string"}, name

    from dynamic_ai_products.extraction import candidates

    source = (ROOT / "src" / "dynamic_ai_products" / "extraction" / "candidates.py").read_text()
    assert "maxLength" not in source
    assert not [c for c in dir(candidates) if "quote_length" in c or "quote_max" in c]


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


# --- ADR-069 (E-T1 governance wiring, CR-0008): the schema-bound task prompt -


TASK_ID = "task_discovery_schema_v1"
RETIRED_TASK_ID = "task_discovery_recall"
CONSOLIDATION_TASK_ID = "task_consolidation_precision"
TASK_OBSERVATION_SCHEMA = json.loads(
    (ROOT / "schemas" / "task_observation_v2.schema.json").read_text(encoding="utf-8")
)


@pytest.fixture(scope="module")
def task_prompt_text() -> str:
    return load_prompt(ROOT, TASK_ID)["text"]


def test_the_task_successor_is_first_and_the_unresolved_prompts_are_retained():
    assert EXTRACTION_PROMPTS["task_extraction"] == (
        TASK_ID,
        RETIRED_TASK_ID,
        CONSOLIDATION_TASK_ID,
    )
    plan = single_pass_prompt_plan("task_extraction")
    assert plan == {
        "prompt_id": TASK_ID,
        "prompt_pass_index": 1,
        "prompt_sequence_length": 3,
        "prompt_sequence_complete": False,
    }


@pytest.mark.parametrize("prompt_id", [RETIRED_TASK_ID, CONSOLIDATION_TASK_ID])
def test_the_retained_task_prompts_bytes_are_untouched(prompt_id):
    """Superseding adds a file; it never edits one -- no chain has ever resolved
    either retained prompt, but a frozen prompt is never deleted."""
    import subprocess

    committed = subprocess.check_output(
        ["git", "show", f"HEAD:prompts/extraction/{prompt_id}.md"], cwd=ROOT
    )
    on_disk = (ROOT / "prompts" / "extraction" / f"{prompt_id}.md").read_bytes()
    assert on_disk == committed


def test_the_retired_task_prompt_could_not_have_conformed():
    """The CR-0008 measurement, asserted rather than described: only three of
    eleven required fields are named at all, and none of them is the
    identifier or attribution machinery a conforming record needs."""
    text = (ROOT / "prompts" / "extraction" / f"{RETIRED_TASK_ID}.md").read_text(
        encoding="utf-8"
    )
    missing = [
        field for field in TASK_OBSERVATION_SCHEMA["required"] if field not in text
    ]
    assert set(missing) == {
        "task_observation_id",
        "company_id",
        "observation_cutoff",
        "product_observation_id",
        "capability_observation_ids",
        "normalized_task",
        "customer_need",
        "availability_status",
    }


def test_the_task_prompt_binds_to_the_same_vocabulary(task_prompt_text, vocabulary):
    """The S1-S8 vocabulary, reused rather than a second one minted for tasks."""
    parsed = validate_prompt_vocabulary_binding(
        prompt_text=task_prompt_text, vocabulary=vocabulary
    )
    for label in AVAILABILITY_PARTITION_FIELDS:
        assert parsed[label] == vocabulary[label]


def test_the_task_prompt_uses_every_bound_placeholder_and_the_required_ones(
    task_prompt_text,
):
    import re

    from dynamic_ai_products.extraction.contents_renderer import (
        STAGE_PLACEHOLDER_BINDINGS,
        STAGE_REQUIRED_PLACEHOLDERS,
    )

    used = set(re.findall(r"\{\{([a-z_]+)\}\}", task_prompt_text))
    assert used == set(STAGE_PLACEHOLDER_BINDINGS["task_extraction"])
    assert set(STAGE_REQUIRED_PLACEHOLDERS["task_extraction"]) <= used


def test_the_task_prompt_asks_for_labels_and_no_identifier(task_prompt_text):
    text = task_prompt_text
    assert '"C1"' in text and '"C9"' in text and '"C13"' in text
    assert '{"ref": ..., "quote": ...}' in text
    assert "Never emit `source_id` or `passage_id`" in text
    assert "Do **not** emit an identifier of any kind" in text


def test_the_task_prompt_renders_the_generated_status_table(task_prompt_text):
    from dynamic_ai_products.extraction.availability_vocabulary import (
        status_label_table,
    )

    for label, token in status_label_table():
        assert f"{label}  =  {token}" in task_prompt_text


def test_the_task_prompt_names_every_field_the_model_must_supply(task_prompt_text):
    for field in ("task", "customer_need", "capability_refs",
                  "availability_status", "confidence", "evidence"):
        assert f"`{field}`" in task_prompt_text
    # Optional, on the evidence-supported-or-omitted rule already established
    # for the capability stage's input_types/output_types.
    for field in ("target_customer", "monetization_model", "task_components",
                  "ai_action_observed", "ambiguity"):
        assert f"`{field}`" in task_prompt_text, field
        assert field in TASK_OBSERVATION_SCHEMA["properties"], field
        assert field not in TASK_OBSERVATION_SCHEMA["required"], field


def test_the_derived_task_fields_are_named_only_as_derived(task_prompt_text):
    """The four the pipeline owns -- plus company_id/observation_cutoff, which
    this prompt never mentions at all, unlike the product stage's prompt."""
    forbidden_block = task_prompt_text.split(
        "Do **not** emit an identifier of any kind", 1
    )[1]
    for derived in ("task_observation_id", "product_observation_id",
                    "capability_observation_ids", "normalized_task"):
        assert derived in forbidden_block, derived
    assert "company_id" not in task_prompt_text
    assert "observation_cutoff" not in task_prompt_text


def test_the_task_prompt_never_asks_for_a_role_or_a_parent_label(task_prompt_text):
    """Two things a task prompt must not ask for, for two different reasons:
    ``task_role`` is a later consolidation-pass decision (the predecessor
    prompt's own instruction, carried forward), and a parent product label is
    unnecessary -- task discovery renders one product per call, so the
    pipeline already knows it and injects it directly (ADR-069)."""
    assert "task_role" in task_prompt_text  # named, to forbid it
    assert "`parent_ref`" not in task_prompt_text
    assert '"A0' not in task_prompt_text


def test_the_task_prompt_c0n_is_unpadded_from_its_first_version(task_prompt_text):
    """ADR-069: applying ADR-064's measurement before a live call can repeat it.

    Distinct from ADR-064's own capability-stage fix, which corrected an
    instruction that had already caused two live failures. Nothing here has
    ever run against a model; the point is that the instruction and the
    renderer already agree on day one.
    """
    from dynamic_ai_products.extraction.contents_renderer import (
        capability_ref_label,
    )

    assert capability_ref_label(13) == "C13"
    assert "no fixed width and no leading zeros" in task_prompt_text
    assert "at least two digits" not in task_prompt_text
    assert "at least three digits" not in task_prompt_text


def test_the_task_prompt_states_the_quote_bound(task_prompt_text):
    """ADR-065's rule, applied to this prompt's first version rather than
    added to a predecessor that shipped without it."""
    assert "1 to 3\n  sentences" in task_prompt_text
    assert "without joining text across a gap" in task_prompt_text
    assert "- Every `quote` is 1 to 3 sentences, contiguous, and copied exactly." in (
        task_prompt_text
    )


def test_the_task_prompt_governing_spec_is_spec_010(task_prompt_text):
    assert "`SPEC-010`" in task_prompt_text
