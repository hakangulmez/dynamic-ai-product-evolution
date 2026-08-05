"""Prompt identity is the digest of exact bytes (ADR-033, protocol amendment).

``prompt_hash`` is SHA-256 over the resolved prompt artifact's exact bytes: no
normalization, no whitespace folding, no template expansion. Committed prompt
files are read only; they are never modified to acquire an identity.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.prompts import (
    EXTRACTION_PROMPTS,
    PROMPT_REGISTRY_VERSION,
    load_prompt,
    prompt_hash_of_bytes,
    prompts_for_stage,
    resolve_prompt_path,
)

ROOT = Path(__file__).resolve().parents[2]


def test_registry_version_is_declared():
    # ADR-053 (G6-P): v1 -> v2 when the schema-bound successor took position one
    # in the product_extraction sequence.
    assert PROMPT_REGISTRY_VERSION == "extraction_prompt_registry_v4"


def test_every_stage_declares_at_least_one_prompt():
    assert set(EXTRACTION_PROMPTS) == {
        "product_extraction",
        "capability_extraction",
        "task_extraction",
    }
    for stage, ids in EXTRACTION_PROMPTS.items():
        assert ids, stage
        assert len(set(ids)) == len(ids), stage


def test_every_registered_prompt_file_exists_in_the_repository():
    for ids in EXTRACTION_PROMPTS.values():
        for prompt_id in ids:
            assert resolve_prompt_path(ROOT, prompt_id).is_file(), prompt_id


def test_prompts_for_stage_returns_the_registered_order():
    # ADR-053 (G6-P). The predecessor keeps its registration at position two:
    # ext-smoke-0002 resolved it, and removing it would make that chain
    # unverifiable. What changed is which prompt a single pass executes.
    assert prompts_for_stage("product_extraction") == (
        "product_discovery_schema_v4",
        "product_discovery_schema_v3",
        "product_discovery_schema_v2",
        "product_discovery_recall",
        "product_consolidation_precision",
    )


def test_unknown_stage_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        prompts_for_stage("marketing_extraction")
    assert excinfo.value.reason_code == "stage_invalid"


def test_unknown_prompt_id_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        resolve_prompt_path(ROOT, "not_a_prompt")
    assert excinfo.value.reason_code == "prompt_unknown"


@pytest.mark.parametrize(
    "payload",
    [b"a", b" a ", b"a\n", b"a\r\n", b"a  b", b"\xef\xbb\xbfa"],
)
def test_hashing_is_over_exact_bytes_with_no_normalization(payload):
    assert prompt_hash_of_bytes(payload) == sha256(payload).hexdigest()


def test_whitespace_variants_produce_different_identities():
    """Folding whitespace would make two distinct prompts share one identity."""
    digests = {
        prompt_hash_of_bytes(payload) for payload in (b"x", b"x\n", b"x ", b" x")
    }
    assert len(digests) == 4


def test_non_bytes_input_is_refused():
    with pytest.raises(ExtractionError) as excinfo:
        prompt_hash_of_bytes("a string")
    assert excinfo.value.reason_code == "prompt_invalid"


def test_loading_a_committed_prompt_reports_its_byte_digest(tmp_path: Path):
    prompt_id = "capability_extraction"
    record = load_prompt(ROOT, prompt_id)
    raw = resolve_prompt_path(ROOT, prompt_id).read_bytes()
    assert record["prompt_hash"] == sha256(raw).hexdigest()
    assert record["byte_count"] == len(raw)
    assert record["reference"] == f"prompts/extraction/{prompt_id}.md"
    assert record["text"].encode("utf-8") == raw


def test_loading_never_modifies_the_prompt_file():
    prompt_path = resolve_prompt_path(ROOT, "capability_extraction")
    before = prompt_path.read_bytes()
    load_prompt(ROOT, "capability_extraction")
    assert prompt_path.read_bytes() == before


def test_a_missing_prompt_is_refused(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        load_prompt(tmp_path, "capability_extraction")
    assert excinfo.value.reason_code == "prompt_invalid"


def test_an_empty_prompt_is_refused(tmp_path: Path):
    target = tmp_path / "prompts" / "extraction"
    target.mkdir(parents=True)
    (target / "capability_extraction.md").write_bytes(b"   \n\n")
    with pytest.raises(ExtractionError) as excinfo:
        load_prompt(tmp_path, "capability_extraction")
    assert excinfo.value.reason_code == "prompt_invalid"


# --- the single-pass decision (ADR-036, E-R) ----------------------------------


def test_the_single_pass_plan_is_explicit_not_incidental():
    """Indexing ``[0]`` is a decision; this records it as one."""
    from dynamic_ai_products.extraction.prompts import single_pass_prompt_plan

    plan = single_pass_prompt_plan("product_extraction")
    assert plan == {
        "prompt_id": "product_discovery_schema_v4",
        "prompt_pass_index": 1,
        "prompt_sequence_length": 5,
        "prompt_sequence_complete": False,
    }


def test_the_product_stage_is_never_reported_as_a_complete_universe():
    """A recall pass without its consolidation pass is a candidate set."""
    from dynamic_ai_products.extraction.prompts import single_pass_prompt_plan

    assert single_pass_prompt_plan("product_extraction")["prompt_sequence_complete"] is False
    assert single_pass_prompt_plan("task_extraction")["prompt_sequence_complete"] is False
    # The capability stage registers one prompt, so a single pass completes it.
    assert single_pass_prompt_plan("capability_extraction")["prompt_sequence_complete"] is True


def test_the_plan_selects_the_first_registered_prompt_for_every_stage():
    from dynamic_ai_products.extraction.prompts import (
        prompts_for_stage,
        single_pass_prompt_plan,
    )

    for stage in ("product_extraction", "capability_extraction", "task_extraction"):
        plan = single_pass_prompt_plan(stage)
        sequence = prompts_for_stage(stage)
        assert plan["prompt_id"] == sequence[0]
        assert plan["prompt_sequence_length"] == len(sequence)


def test_an_unknown_stage_has_no_plan():
    import pytest as _pytest

    from dynamic_ai_products.extraction.errors import ExtractionError
    from dynamic_ai_products.extraction.prompts import single_pass_prompt_plan

    with _pytest.raises(ExtractionError) as excinfo:
        single_pass_prompt_plan("mystery_stage")
    assert excinfo.value.reason_code == "stage_invalid"
