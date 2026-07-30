"""The deterministic provider-contents renderer (ADR-036, E-R).

Before E-R the connector sent the frozen template and the packet payload was
never transmitted, so a live call would have handed the model literal
``{{company_name}}``, ``{{cutoff}}`` and ``{{passages_with_ids}}`` markers. These
tests pin that the markers are resolved, that resolution is byte-deterministic,
and that anything unresolvable fails closed instead of being sent.
"""

from __future__ import annotations

import hashlib

import pytest

from dynamic_ai_products.extraction.contents_renderer import (
    PLACEHOLDER_PATTERN,
    RENDERER_VERSION,
    STAGE_PLACEHOLDER_BINDINGS,
    render_provider_contents,
)
from dynamic_ai_products.extraction.errors import ExtractionError

PROMPT = "Firm {{company_name}} as of {{cutoff}}.\n\n{{passages_with_ids}}\n"


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


def test_only_the_product_stage_binds_placeholders_in_e_r():
    """E-S is what unblocks the other two; that is recorded, not implied."""
    assert set(STAGE_PLACEHOLDER_BINDINGS) == {
        "product_extraction",
        "capability_extraction",
        "task_extraction",
    }
    assert set(STAGE_PLACEHOLDER_BINDINGS["product_extraction"]) == {
        "company_name",
        "cutoff",
        "passages_with_ids",
    }
    assert STAGE_PLACEHOLDER_BINDINGS["capability_extraction"] == {}
    assert STAGE_PLACEHOLDER_BINDINGS["task_extraction"] == {}


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
    """Placeholder-free is not the same as materializable.

    The capability prompt happens to carry no markers, but it still needs the
    validated products E-S supplies. Rendering it verbatim would send an
    instruction naming no products at all, so E-C stays blocked here.
    """
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="capability_extraction",
            prompt_text="No markers here.\n",
            packet=_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unbound"


# --- fail closed --------------------------------------------------------------


def test_an_unbound_placeholder_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction",
            prompt_text="{{company_name}} and {{mystery_field}}",
            packet=_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unbound"


@pytest.mark.parametrize("stage", ["capability_extraction", "task_extraction"])
def test_both_non_product_stages_fail_closed_until_e_s(stage):
    """E-C and E-D stay blocked; only product_extraction materializes in E-R."""
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage=stage,
            prompt_text="{{product}} {{capabilities}} {{company}} {{cutoff}}",
            packet=_packet(),
        )
    assert excinfo.value.reason_code == "contents_placeholder_unbound"


def test_only_the_product_stage_is_materialization_supported():
    from dynamic_ai_products.extraction.contents_renderer import (
        MATERIALIZATION_SUPPORTED_STAGES,
    )

    assert MATERIALIZATION_SUPPORTED_STAGES == ("product_extraction",)


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
