"""The deterministic provider-contents renderer (ADR-036, E-R).

Before E-R the connector sent the frozen template and the packet payload was
never transmitted, so a live call would have handed the model literal
``{{company_name}}``, ``{{cutoff}}`` and ``{{passages_with_ids}}`` markers. These
tests pin that the markers are resolved, that resolution is byte-deterministic,
and that anything unresolvable fails closed instead of being sent.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.contents_renderer import (
    PLACEHOLDER_PATTERN,
    RENDERER_VERSION,
    STAGE_PLACEHOLDER_BINDINGS,
    render_provider_contents,
)
from dynamic_ai_products.extraction.errors import ExtractionError

PROMPT = "Firm {{company_name}} as of {{cutoff}}.\n\n{{passages_with_ids}}\n"


def _parent(name, ordinal, **payload_over):
    payload = {"product_observation_id": f"CIK1:2024-12-31:{name}", "product_name": name}
    payload.update(payload_over)
    return {
        "observation_id": payload["product_observation_id"],
        "reference": f"observations/product/{ordinal:032x}.json",
        "sha256": "a" * 64,
        "payload": payload,
    }


def _capability_packet(parents=None, **overrides):
    """A packet as the capability branch of the builder produces one."""
    packet = _packet(**overrides)
    packet["parent_context"] = {
        "snapshot": {"reference": "snapshots/a.json", "sha256": "b" * 64,
                     "snapshot_version": "v1"},
        "product_parents": [_parent("Alpha", 1, product_family="Fam",
                                    entity_type="product"),
                            _parent("Beta", 2, entity_type="product")]
        if parents is None else parents,
    }
    return packet


def _packet(**overrides):
    packet = {
        "contract": "extraction_input_packet@0.2.0",
        "observation_cutoff_date": "2024-12-31",
        "legal_name": "HUBSPOT INC",
        "passages": [
            {
                "passage_id": "p-2",
                "source_id": "sec-b",
                "publication_date": "2023-05-05",
                "text": "second body",
            },
            {
                "passage_id": "p-1",
                "source_id": "sec-a",
                "publication_date": "2024-02-14",
                "text": "first body",
            },
        ],
    }
    packet.update(overrides)
    return packet


def _render(**overrides):
    return render_provider_contents(
        stage="product_extraction", prompt_text=PROMPT, packet=_packet(**overrides)
    )


# --- identity -----------------------------------------------------------------


def test_the_renderer_declares_a_version():
    assert RENDERER_VERSION == "extraction_contents_renderer_v1"


def test_the_stage_binding_map_is_closed_and_stage_scoped():
    """ADR-058 (E-S1) added the capability stage; ADR-068 (E-T1) the task one."""
    assert set(STAGE_PLACEHOLDER_BINDINGS) == {
        "product_extraction",
        "capability_extraction",
        "task_extraction",
        # ADR-073 (CR-0009): consolidation reads the discovery stage's output.
        "product_consolidation",
    }
    assert set(STAGE_PLACEHOLDER_BINDINGS["product_consolidation"]) == {
        "company_name",
        "cutoff",
        "passages_with_ids",
        "product_candidates",
    }
    assert set(STAGE_PLACEHOLDER_BINDINGS["product_extraction"]) == {
        "company_name",
        "cutoff",
        "passages_with_ids",
    }
    assert set(STAGE_PLACEHOLDER_BINDINGS["capability_extraction"]) == {
        "company_name",
        "cutoff",
        "passages_with_ids",
        "validated_products",
    }
    # The task stage's placeholder names are its own frozen prompt's, not the
    # other two stages' vocabulary: measured, ``task_discovery_recall`` says
    # ``{{company}}`` and carries no ``{{passages}}`` at all.
    assert set(STAGE_PLACEHOLDER_BINDINGS["task_extraction"]) == {
        "company",
        "cutoff",
        "product",
        "capabilities",
    }
    # Offered to the capability stage only: the product stage has no parents, and
    # a placeholder a stage cannot legitimately fill has no business in its map.
    assert "validated_products" not in STAGE_PLACEHOLDER_BINDINGS["product_extraction"]
    assert "passages_with_ids" not in STAGE_PLACEHOLDER_BINDINGS["task_extraction"]


# --- resolution ---------------------------------------------------------------


def test_every_placeholder_is_resolved():
    rendered = _render()
    assert not PLACEHOLDER_PATTERN.search(rendered)
    assert "{{" not in rendered
    assert "HUBSPOT INC" in rendered
    assert "2024-12-31" in rendered


def test_the_packet_passages_reach_the_rendered_document():
    rendered = _render()
    for token in ("p-1", "p-2", "sec-a", "sec-b", "first body", "second body"):
        assert token in rendered, token


def test_passages_are_emitted_in_canonical_order_not_input_order():
    """Ordering is by (source_id, passage_id), so arrival order cannot leak in."""
    rendered = _render()
    assert rendered.index("p-1") < rendered.index("p-2")

    reversed_packet = _packet()
    reversed_packet["passages"] = list(reversed(reversed_packet["passages"]))
    other = render_provider_contents(
        stage="product_extraction", prompt_text=PROMPT, packet=reversed_packet
    )
    assert other == rendered


def test_rendering_is_byte_deterministic():
    assert _render().encode("utf-8") == _render().encode("utf-8")


def test_a_changed_passage_necessarily_changes_the_rendered_bytes():
    before = hashlib.sha256(_render().encode("utf-8")).hexdigest()
    changed = _packet()
    changed["passages"][0]["text"] = "second body, amended"
    after = hashlib.sha256(
        render_provider_contents(
            stage="product_extraction", prompt_text=PROMPT, packet=changed
        ).encode("utf-8")
    ).hexdigest()
    assert before != after


def test_a_repeated_placeholder_resolves_to_one_value():
    rendered = render_provider_contents(
        stage="product_extraction",
        prompt_text="{{cutoff}} and again {{cutoff}}",
        packet=_packet(),
    )
    assert rendered == "2024-12-31 and again 2024-12-31"


def test_a_placeholder_free_capability_prompt_is_still_refused():
    """ADR-058 rebaselines *why* it is refused, not *that* it is.

    Before E-S1 the stage was not materializable at all, so this failed with
    ``contents_placeholder_unbound``. Making it materializable removed that
    accidental protection, and a run then reached the provider carrying an
    instruction naming no products -- the exact hazard the E-R docstring warned
    about. The guard is now deliberate: a capability record requires
    ``product_observation_id``, so a prompt that never asks for its parents
    cannot produce a conforming one, and the call is refused before it is made.
    """
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="capability_extraction",
            prompt_text="No markers here.\n",
            packet=_capability_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_required"


# --- fail closed --------------------------------------------------------------


def test_an_unbound_placeholder_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction",
            prompt_text="{{company_name}} and {{mystery_field}}",
            packet=_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unbound"


def test_the_task_stage_refuses_without_a_focal_product():
    """ADR-068. Materializable is not the same as renderable from any packet.

    A packet carries every validated product; task discovery is about one. The
    renderer will not pick, so a task render with no focal product is refused
    rather than silently choosing the first.
    """
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="task_extraction",
            prompt_text="{{product}} {{capabilities}} {{company}} {{cutoff}}",
            packet=_packet(),
        )
    assert excinfo.value.reason_code == "focal_product_required"


def test_an_unbound_placeholder_is_still_refused_on_the_capability_stage():
    """Materializable is not the same as permissive."""
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="capability_extraction",
            prompt_text="{{company_name}} and {{mystery_field}}",
            packet=_capability_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unbound"


def test_all_four_stages_are_materialization_supported():
    from dynamic_ai_products.extraction.contents_renderer import (
        MATERIALIZATION_SUPPORTED_STAGES,
    )

    assert MATERIALIZATION_SUPPORTED_STAGES == (
        "product_extraction",
        "capability_extraction",
        "task_extraction",
        # ADR-073 (CR-0009): consolidation is a stage, not a second pass.
        "product_consolidation",
    )


def test_a_value_that_introduces_a_marker_is_caught_on_the_rescan():
    """Substitution cannot smuggle a placeholder in through its own value."""
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction",
            prompt_text="{{company_name}}",
            packet=_packet(legal_name="ACME {{cutoff}} INC"),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unresolved"


def test_an_unknown_stage_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="mystery_stage", prompt_text=PROMPT, packet=_packet()
        )
    assert excinfo.value.reason_code == "contents_stage_unsupported"


def test_a_packet_without_a_legal_name_cannot_render_a_company_name():
    """A @0.1.0 packet has no name field; the CIK is not a substitute."""
    packet = _packet()
    del packet["legal_name"]
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction", prompt_text=PROMPT, packet=packet
        )
    assert excinfo.value.reason_code == "company_identity_pin_required"


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_legal_name_is_refused(blank):
    with pytest.raises(ExtractionError) as excinfo:
        _render(legal_name=blank)
    assert excinfo.value.reason_code == "contents_context_invalid"


@pytest.mark.parametrize("passages", [[], None, "not-a-list", [7], [{}]])
def test_unusable_passages_are_refused(passages):
    with pytest.raises(ExtractionError) as excinfo:
        _render(passages=passages)
    assert excinfo.value.reason_code == "contents_context_invalid"


def test_duplicate_passage_identities_are_refused():
    """A duplicate hides how many distinct passages were actually supplied."""
    with pytest.raises(ExtractionError) as excinfo:
        _render(
            passages=[
                {"passage_id": "p-1", "source_id": "sec-a", "text": "one"},
                {"passage_id": "p-1", "source_id": "sec-a", "text": "two"},
            ]
        )
    assert excinfo.value.reason_code == "contents_context_invalid"


@pytest.mark.parametrize("prompt_text", ["", "   ", None, 7])
def test_an_unusable_prompt_is_refused(prompt_text):
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction", prompt_text=prompt_text, packet=_packet()
        )
    assert excinfo.value.reason_code == "prompt_invalid"


def test_the_renderer_touches_no_clock_network_or_filesystem():
    """Static proof, so purity is not merely asserted in a docstring."""
    import ast
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "dynamic_ai_products"
        / "extraction"
        / "contents_renderer.py"
    )
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported <= {"__future__", "re", "typing", "errors"}
    assert not any(isinstance(node, ast.Assert) for node in ast.walk(tree))


# --- no residual marker survives, in any spelling -----------------------------


@pytest.mark.parametrize(
    "marker",
    [
        "{{UPPER}}",              # uppercase: invisible to the lowercase pattern
        "{{ company_name }}",     # whitespace-bearing
        "{{foo-bar}}",            # hyphenated
        "{{MiXeD_Case}}",
        "{{123}}",
        "{{",                     # unmatched opening
        "}}",                     # unmatched closing
        "{{unclosed",
        "text}} trailing",
    ],
)
def test_any_residual_literal_marker_is_refused(marker):
    """The lowercase pattern alone let all of these through to the provider."""
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction",
            prompt_text=f"Firm {{{{company_name}}}} note {marker}",
            packet=_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unresolved"


def test_a_recognized_but_undeclared_lowercase_placeholder_stays_unbound():
    """The two codes stay distinct: unbound is a binding gap, not a leftover."""
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction",
            prompt_text="{{company_name}} {{some_other_field}}",
            packet=_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unbound"


@pytest.mark.parametrize("hostile", ["{{UPPER}}", "{{ cutoff }}", "{{a-b}}", "}}", "{{"])
def test_a_marker_introduced_through_the_company_name_is_refused(hostile):
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction",
            prompt_text="{{company_name}}",
            packet=_packet(legal_name=f"ACME {hostile} INC"),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unresolved"


@pytest.mark.parametrize("hostile", ["{{UPPER}}", "{{ cutoff }}", "{{a-b}}", "}}", "{{"])
def test_a_marker_introduced_through_passage_text_is_refused(hostile):
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction",
            prompt_text="{{passages_with_ids}}",
            packet=_packet(
                passages=[
                    {
                        "passage_id": "p-1",
                        "source_id": "sec-a",
                        "publication_date": "2024-02-14",
                        "text": f"body {hostile} tail",
                    }
                ]
            ),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unresolved"


# --- the authoritative publication date ---------------------------------------


def test_every_passage_header_carries_the_publication_date():
    rendered = _render()
    assert "[publication_date: 2024-02-14]" in rendered
    assert "[publication_date: 2023-05-05]" in rendered
    assert rendered.count("[publication_date:") == 2


@pytest.mark.parametrize("bad", [None, "", "2024/02/14", "14-02-2024", "2024-2-4", 7])
def test_a_missing_or_malformed_publication_date_is_refused(bad):
    with pytest.raises(ExtractionError) as excinfo:
        _render(
            passages=[
                {
                    "passage_id": "p-1",
                    "source_id": "sec-a",
                    "publication_date": bad,
                    "text": "body",
                }
            ]
        )
    assert excinfo.value.reason_code == "contents_context_invalid"


# --- ADR-058 (E-S1): the validated-products binding -------------------------


from dynamic_ai_products.extraction.contents_renderer import (  # noqa: E402
    PARENT_REF_PATTERN,
    parent_ref_label,
)

PRODUCTS_PROMPT = "PRODUCTS:\n{{validated_products}}\n"


def _render_products(packet=None):
    return render_provider_contents(
        stage="capability_extraction",
        prompt_text=PRODUCTS_PROMPT,
        packet=packet if packet is not None else _capability_packet(),
    )


@pytest.mark.parametrize("ordinal, expected", [(1, "A01"), (11, "A11"), (100, "A100")])
def test_parent_labels_are_one_based_and_widen_past_two_digits(ordinal, expected):
    assert parent_ref_label(ordinal) == expected
    assert PARENT_REF_PATTERN.fullmatch(expected)


def test_each_validated_product_gets_a_label_in_packet_order():
    """No second sorter: the packet's order is ``derive_parent_context``'s."""
    rendered = _render_products()
    assert "[ref: A01]" in rendered and "[ref: A02]" in rendered
    assert rendered.index("Alpha") < rendered.index("Beta")


def test_the_block_carries_the_name_family_and_entity_type():
    rendered = _render_products()
    assert "[ref: A01] [product_family: Fam] [entity_type: product]\nAlpha" in rendered
    # Beta has no family; the bracket is omitted rather than emitted empty.
    assert "[ref: A02] [entity_type: product]\nBeta" in rendered


def test_the_block_omits_what_would_reopen_a_closed_defect():
    """The three deliberate exclusions, asserted rather than described.

    ``evidence`` would duplicate text the model already receives with ``P0NN``
    refs; ``product_observation_id`` is the 44-character string the label
    exists to avoid transcribing; the parent's ``availability_status`` would
    bias a judgement the capability must make from its own evidence.
    """
    parents = [
        _parent(
            "Alpha",
            1,
            availability_status="general_availability",
            evidence=[{"source_id": "s", "passage_id": "p", "quote": "a quote"}],
        )
    ]
    rendered = _render_products(_capability_packet(parents=parents))
    assert "a quote" not in rendered
    assert "general_availability" not in rendered
    assert "CIK1:2024-12-31:Alpha" not in rendered
    assert "Alpha" in rendered


def test_the_rendered_block_is_deterministic():
    assert _render_products() == _render_products()


@pytest.mark.parametrize(
    "context",
    [None, "not a mapping", {}, {"product_parents": []}, {"product_parents": "no"}],
    ids=["absent", "not_a_mapping", "empty_map", "empty_list", "not_a_list"],
)
def test_a_capability_packet_without_parent_context_is_refused(context):
    packet = _packet()
    if context is not None:
        packet["parent_context"] = context
    with pytest.raises(ExtractionError) as excinfo:
        _render_products(packet)
    assert excinfo.value.reason_code == "contents_context_invalid"


@pytest.mark.parametrize(
    "parent",
    ["not a mapping", {"payload": "not a mapping"}, {"payload": {}},
     {"payload": {"product_name": "  "}}, {"payload": {"product_name": 12}}],
    ids=["not_a_mapping", "payload_not_a_mapping", "no_name", "blank_name", "non_string"],
)
def test_a_parent_without_a_verified_payload_and_name_is_refused(parent):
    with pytest.raises(ExtractionError) as excinfo:
        _render_products(_capability_packet(parents=[parent]))
    assert excinfo.value.reason_code == "contents_context_invalid"


def test_the_product_stage_cannot_bind_validated_products():
    """The placeholder is stage-scoped, not global."""
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction",
            prompt_text=PRODUCTS_PROMPT,
            packet=_capability_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unbound"


def test_the_capability_stage_still_renders_passages_and_identity():
    """The new binding is additive; the three E-R bindings still work here."""
    rendered = render_provider_contents(
        stage="capability_extraction",
        prompt_text="{{company_name}} {{cutoff}}\n{{passages_with_ids}}\n{{validated_products}}",
        packet=_capability_packet(),
    )
    assert "HUBSPOT INC" in rendered and "2024-12-31" in rendered
    # ADR-064: the capability stage labels without padding; the parent label is
    # untouched, because no measured failure involved it.
    assert "[ref: P1]" in rendered and "[ref: A01]" in rendered
    assert "[ref: P001]" not in rendered


def test_the_two_stages_render_the_same_passage_under_different_labels():
    """The style is the only difference, and it follows the prompt, not the run.

    The product stage still shows ``P001`` because
    ``product_discovery_schema_v4`` -- qualified, digest-pinned, and untouched by
    ADR-064 -- tells the model the label has at least three digits.
    """
    packet = _capability_packet()
    capability = render_provider_contents(
        stage="capability_extraction",
        prompt_text="{{passages_with_ids}}\n{{validated_products}}",
        packet=packet,
    )
    product = render_provider_contents(
        stage="product_extraction",
        prompt_text="{{passages_with_ids}}",
        packet=packet,
    )
    assert "[ref: P1]" in capability and "[ref: P001]" not in capability
    assert "[ref: P001]" in product and "[ref: P1]" not in product


def test_the_required_placeholder_map_is_closed_and_narrow():
    """Two stages require something; the product stage still requires nothing.

    ADR-068 adds the task stage's pair for ADR-058's reason: ``task_observation``
    requires both a product and the capabilities the task is performed through,
    so a prompt naming neither could not produce a conforming record.
    """
    from dynamic_ai_products.extraction.contents_renderer import (
        STAGE_REQUIRED_PLACEHOLDERS,
    )

    assert STAGE_REQUIRED_PLACEHOLDERS == {
        "capability_extraction": ("validated_products",),
        "task_extraction": ("product", "capabilities"),
        # ADR-073. Same reason again: a consolidation decision names a
        # candidate, so a prompt that never shows the candidates cannot produce
        # a conforming decision.
        "product_consolidation": ("product_candidates",),
    }
    assert "product_extraction" not in STAGE_REQUIRED_PLACEHOLDERS


def test_a_capability_prompt_using_other_markers_but_not_its_parents_is_refused():
    """Using *some* placeholders is not the same as using the load-bearing one."""
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="capability_extraction",
            prompt_text="{{company_name}} {{cutoff}} {{passages_with_ids}}",
            packet=_capability_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_required"


def test_the_product_stage_is_not_subject_to_the_requirement():
    """A product prompt using only one marker still renders."""
    rendered = render_provider_contents(
        stage="product_extraction", prompt_text="{{cutoff}}", packet=_packet()
    )
    assert rendered == "2024-12-31"


# --- ADR-068 (E-T1): the task binding, over the real HubSpot chain ----------

REAL_CAP_ROOT = (
    Path(__file__).resolve().parents[2] / "data/runs/decisions-ext-smoke-cap-0005-0001"
)
REAL_PRODUCT_ROOT = (
    Path(__file__).resolve().parents[2] / "data/runs/decisions-ext-smoke-0006-0002"
)
REAL_SNAPSHOT = (
    Path(__file__).resolve().parents[2] / "data/runs/srcsnap-hubspot-fy2024-sec-v2"
)
TASK_PROMPT = (
    Path(__file__).resolve().parents[2] / "prompts/extraction/task_discovery_recall.md"
)

requires_real_chain = pytest.mark.skipif(
    not (REAL_CAP_ROOT / "snapshots/parent_observation_snapshot_b.json").exists(),
    reason="the persisted HubSpot capability chain is not present in this checkout",
)


PRODUCT_DECISIONS = "decisions/product_extraction_validation_decision_set.json"


def _real_task_packet(tmp_path=None):
    """A task packet over the persisted chain, from its own root.

    All four pins resolve inside ``decisions-ext-smoke-cap-0005-0001``: Snapshot
    A and the product decision set are byte-identical copies of the product
    root's originals, carried forward because ``build_extraction_input_packet``
    resolves every pin against one ``artifact_root``. The product set takes a
    distinct filename because the canonical one is already the capability set's.
    """
    import hashlib
    import json

    from dynamic_ai_products.extraction.input_packet import (
        build_extraction_input_packet,
    )

    root = REAL_CAP_ROOT
    product_decisions = PRODUCT_DECISIONS

    def sha(path):
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()

    def lines(name):
        return [
            json.loads(line)
            for line in (REAL_SNAPSHOT / name).read_text().splitlines()
            if line.strip()
        ]

    documents = lines("source_documents.jsonl")
    repo = Path(__file__).resolve().parents[2]
    coverage = "data/runs/ing-783d01075ef04858a22ba5743395bb9c/manifests/source_family_coverage.json"
    manifest = "data/runs/srcsnap-hubspot-fy2024-sec-v2/snapshots/source_passage_snapshot_manifest.json"
    return build_extraction_input_packet(
        stage="task_extraction",
        company_id="CIK0001404655",
        observation_cutoff_date="2025-02-12",
        passages=lines("source_passages.jsonl"),
        document_publication_dates={
            d["source_id"]: d["publication_date"] for d in documents
        },
        coverage_artifact={"reference": coverage, "sha256": sha(repo / coverage)},
        source_snapshot_manifest={"reference": manifest, "sha256": sha(repo / manifest)},
        artifact_root=root,
        snapshot_a_pin={
            "reference": "snapshots/parent_observation_snapshot_a.json",
            "sha256": sha(root / "snapshots/parent_observation_snapshot_a.json"),
            "snapshot_version": "product-snapshot-a-hubspot-0006-v1",
        },
        snapshot_b_pin={
            "reference": "snapshots/parent_observation_snapshot_b.json",
            "sha256": sha(root / "snapshots/parent_observation_snapshot_b.json"),
            "snapshot_version": "capability-snapshot-b-hubspot-cap-0005-v1",
        },
        product_decision_set_pin={
            "reference": product_decisions,
            "sha256": sha(root / product_decisions),
            "decision_set_version": "product-validation-hubspot-0006-v1",
        },
        capability_decision_set_pin={
            "reference": "decisions/extraction_validation_decision_set.json",
            "sha256": sha(root / "decisions/extraction_validation_decision_set.json"),
            "decision_set_version": "capability-validation-hubspot-cap-0005-v1",
        },
        company_identity_root=repo / "data/registry",
        company_identity_pin={
            "reference": "pilot_universe_packet_CIK0001404655.json",
            "sha256": sha(repo / "data/registry/pilot_universe_packet_CIK0001404655.json"),
        },
    )


PAYMENTS = "CIK0001404655:2025-02-12:payments"
SALES_HUB = "CIK0001404655:2025-02-12:sales-hub"


@requires_real_chain
def test_the_task_render_shows_one_product_and_only_its_capabilities(tmp_path):
    """The design decision, asserted on real data.

    Task discovery runs per product so the model cannot pile every task onto one
    section -- the failure measured on the capability stage, where 68 of 71
    citations landed in a single passage. It sees one product's capabilities and
    no other product's ``C0N``.
    """
    packet = _real_task_packet(tmp_path)
    rendered = render_provider_contents(
        stage="task_extraction",
        prompt_text=TASK_PROMPT.read_text(),
        packet=packet,
        focal_product_observation_id=PAYMENTS,
    )
    assert "PRODUCT: Payments" in rendered
    assert "[ref: C1]" in rendered and "[ref: C2]" in rendered
    assert "[ref: C3]" not in rendered  # Payments has exactly two capabilities
    for foreign in ("score leads", "manage sales pipeline", "create smart content"):
        assert foreign not in rendered, foreign


@requires_real_chain
def test_the_task_render_carries_no_opaque_identifier_for_the_model_to_copy(tmp_path):
    """ADR-055, ADR-060 and ADR-064's shared lesson, applied before it can bite.

    Measured here: ``capability_observation_id`` runs 46-111 characters on this
    data. The model is shown ``C1`` and ``P11`` instead, and the passage header
    still carries the real identifiers for a human auditor.
    """
    packet = _real_task_packet(tmp_path)
    rendered = render_provider_contents(
        stage="task_extraction",
        prompt_text=TASK_PROMPT.read_text(),
        packet=packet,
        focal_product_observation_id=PAYMENTS,
    )
    body = rendered.split("SOURCE PASSAGES:")[0]
    # No capability id and no product id in the part the model reasons from.
    assert PAYMENTS not in body
    for parent in packet["parent_context"]["capability_parents"]:
        assert parent["observation_id"] not in body
    # The header keeps them, for the human reading the archived document.
    assert "[passage_id: " in rendered and "[source_id: " in rendered


@requires_real_chain
def test_nine_of_the_eleven_products_render_and_two_refuse(tmp_path):
    """How many task runs this chain actually supports, measured not assumed.

    Snapshot B carries eleven products but only nine of them have a validated
    capability: Breeze Agents and Breeze Copilot were rejected at G6-D, on the
    ground that a single SEC overview sentence does not establish a concrete
    action. A task is performed *through* a capability, so a product with none
    yields no task and the renderer refuses rather than sending an instruction
    with an empty capability block.

    Nine renders, all distinct -- no two products produce the same document.
    """
    packet = _real_task_packet(tmp_path)
    rendered_by_product = {}
    refused = []
    for parent in packet["parent_context"]["product_parents"]:
        try:
            rendered_by_product[parent["payload"]["product_name"]] = (
                render_provider_contents(
                    stage="task_extraction",
                    prompt_text=TASK_PROMPT.read_text(),
                    packet=packet,
                    focal_product_observation_id=parent["observation_id"],
                )
            )
        except ExtractionError as exc:
            assert exc.reason_code == "contents_context_invalid"
            refused.append(parent["payload"]["product_name"])

    assert len(packet["parent_context"]["product_parents"]) == 11
    assert sorted(refused) == ["Breeze Agents", "Breeze Copilot"]
    assert len(rendered_by_product) == 9
    assert len(set(rendered_by_product.values())) == 9
    for name, rendered in rendered_by_product.items():
        assert f"PRODUCT: {name}" in rendered
        assert "[ref: C1]" in rendered


@requires_real_chain
def test_a_focal_product_outside_the_snapshot_is_refused(tmp_path):
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="task_extraction",
            prompt_text=TASK_PROMPT.read_text(),
            packet=_real_task_packet(tmp_path),
            focal_product_observation_id="CIK0001404655:2025-02-12:invented",
        )
    assert excinfo.value.reason_code == "contents_context_invalid"


@requires_real_chain
def test_the_task_render_is_byte_deterministic(tmp_path):
    packet = _real_task_packet(tmp_path)
    renders = [
        render_provider_contents(
            stage="task_extraction",
            prompt_text=TASK_PROMPT.read_text(),
            packet=packet,
            focal_product_observation_id=SALES_HUB,
        )
        for _ in range(2)
    ]
    assert renders[0].encode("utf-8") == renders[1].encode("utf-8")
