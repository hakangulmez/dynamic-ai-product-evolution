"""Prompt resolution and identity (ADR-033, protocol amendment).

``prompt_hash`` is SHA-256 over the **exact bytes** of the resolved prompt
artifact. No normalization, no whitespace folding, and no template expansion
occurs before hashing. That digest is the prompt identity; a human-readable
label is optional and lives here, never as an in-file edit to a frozen prompt.

The files under ``prompts/extraction/`` are never modified to acquire
identity — only their digest is computed.
"""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from .errors import ExtractionError

__all__ = [
    "EXTRACTION_PROMPTS",
    "KNOWN_PROMPT_REGISTRY_VERSIONS",
    "PROMPT_REGISTRY_VERSION",
    "VOCABULARY_BOUND_PROMPT_IDS",
    "load_prompt",
    "single_pass_prompt_plan",
    "prompt_hash_of_bytes",
    "resolve_prompt_path",
]

# Every registry version this code has ever published, oldest first. A
# qualification record documents the version that was current when it was
# minted, so a governance validator has to recognise the historical ones as
# well as today's -- otherwise moving the registry would retroactively
# invalidate records that were correct when issued. The set lives here, with the
# registry it describes, so there is one owner and no second list to drift.
KNOWN_PROMPT_REGISTRY_VERSIONS: tuple[str, ...] = (
    "extraction_prompt_registry_v1",
    "extraction_prompt_registry_v2",
    "extraction_prompt_registry_v3",
    "extraction_prompt_registry_v4",
    "extraction_prompt_registry_v5",
    "extraction_prompt_registry_v6",
    "extraction_prompt_registry_v7",
)

# ADR-053 (G6-P). ``v1`` -> ``v2``: the product_extraction sequence gained a
# schema-bound successor at position one. The version is a property of the
# registry, not of any single prompt, so it moves for every stage at once --
# which is the point: a record that declares v1 was minted against a different
# ordering than the one this build resolves.
#
# ADR-055. ``v2`` -> ``v3``: a second successor takes position one, citing
# passages by short positional label instead of transcribed identifiers.
#
# ADR-056. ``v3`` -> ``v4``: the availability status is emitted as a short
# label instead of a transcribed token.
#
# ADR-059. ``v4`` -> ``v5``: the capability stage gains a schema-bound prompt at
# position one. The registry version moves for every stage at once, which is the
# point -- a record naming v4 was minted against a different sequence.
#
# ADR-064. ``v5`` -> ``v6``: a capability successor takes position one, citing
# passages by an unpadded position number. Measured twice on live calls: shown
# ``P025``, the model wrote ``P25``. The prompt changes with the renderer, so
# the label a capability prompt describes is the label its stage renders.
#
# ADR-065. ``v6`` -> ``v7``: a capability successor takes position one, bounding
# the evidence quote to one to three sentences. The passage container is about
# to grow; the quote should not grow with it.
PROMPT_REGISTRY_VERSION = "extraction_prompt_registry_v7"

# Stage -> ordered prompt ids. Labels live here, never inside a frozen prompt.
EXTRACTION_PROMPTS: dict[str, tuple[str, ...]] = {
    "product_extraction": (
        # Position one is what ``single_pass_prompt_plan`` executes. This
        # successor states the output schema explicitly, carries the closed
        # availability vocabulary as literal text, and cites passages by short
        # positional label (ADR-055) and names the availability status by short
        # label rather than transcribing it (ADR-056).
        "product_discovery_schema_v4",
        # Retained: ext-smoke-0005 resolved this prompt. It asked the model to
        # write the status token in full, which it doubled a syllable of once.
        "product_discovery_schema_v3",
        # Retained: ext-smoke-0003 and ext-smoke-0004 resolved this prompt and
        # both chains must stay verifiable. It asked the model to transcribe a
        # 32-character passage_id, which it did wrong the same way twice.
        "product_discovery_schema_v2",
        # Retained, not retired: ``ext-smoke-0002`` resolved this prompt and its
        # bytes must stay reachable for that chain to remain verifiable. It is no
        # longer the prompt a single pass executes.
        "product_discovery_recall",
        "product_consolidation_precision",
    ),
    "capability_extraction": (
        # ADR-065. Position one. Identical to v2 except that the evidence quote
        # is bounded to one to three sentences and must be contiguous.
        "capability_discovery_schema_v3",
        # Retained, not retired: ext-smoke-cap-0003 resolved this prompt. It
        # asked for a verbatim quote and said nothing about its length.
        "capability_discovery_schema_v2",
        # Retained, not retired: ext-smoke-cap-0001 and ext-smoke-cap-0002 both
        # resolved this prompt and their chains must stay verifiable. It asked
        # for at least three digits, and the model dropped the padding once in
        # eighty-one citations -- identically on both runs.
        "capability_discovery_schema_v1",
        # Retained, not retired. Its bytes stay reachable, but it was measured
        # to carry zero placeholders and to name three of six required schema
        # fields, so a single pass no longer executes it.
        "capability_extraction",
    ),
    "task_extraction": ("task_discovery_recall", "task_consolidation_precision"),
}

# Code-owned and closed. A prompt in this set carries the availability
# vocabulary as literal text and therefore must not execute without the binding
# having been checked; a prompt outside it carries no such text. One source,
# used in both directions, so the two rules cannot drift apart.
VOCABULARY_BOUND_PROMPT_IDS = frozenset(
    {
        "product_discovery_schema_v2",
        "product_discovery_schema_v3",
        "product_discovery_schema_v4",
        "capability_discovery_schema_v1",
        "capability_discovery_schema_v2",
        "capability_discovery_schema_v3",
    }
)

_PROMPT_DIR = "prompts/extraction"


def prompt_hash_of_bytes(payload: bytes) -> str:
    """SHA-256 over exact bytes. No normalization of any kind."""
    if not isinstance(payload, (bytes, bytearray)):
        raise ExtractionError(
            "prompt bytes are required", reason_code="prompt_invalid"
        )
    return sha256(bytes(payload)).hexdigest()


def resolve_prompt_path(repo_root: str | Path, prompt_id: str) -> Path:
    known = {pid for ids in EXTRACTION_PROMPTS.values() for pid in ids}
    if prompt_id not in known:
        raise ExtractionError(
            f"unknown extraction prompt id: {prompt_id!r}",
            reason_code="prompt_unknown",
        )
    return Path(repo_root) / _PROMPT_DIR / f"{prompt_id}.md"


def load_prompt(repo_root: str | Path, prompt_id: str) -> dict[str, Any]:
    """Read a prompt read-only and return its identity record."""
    prompt_path = resolve_prompt_path(repo_root, prompt_id)
    try:
        payload = prompt_path.read_bytes()
    except OSError as exc:
        raise ExtractionError(
            f"prompt is unreadable: {prompt_path}", reason_code="prompt_invalid"
        ) from exc
    if not payload.strip():
        raise ExtractionError(
            f"prompt is empty: {prompt_path}", reason_code="prompt_invalid"
        )
    return {
        "prompt_id": prompt_id,
        "prompt_registry_version": PROMPT_REGISTRY_VERSION,
        "reference": f"{_PROMPT_DIR}/{prompt_id}.md",
        "prompt_hash": prompt_hash_of_bytes(payload),
        "byte_count": len(payload),
        "text": payload.decode("utf-8"),
    }


def single_pass_prompt_plan(stage: str) -> dict[str, Any]:
    """The one prompt a single-pass run executes, and an honest record of that.

    ADR-036 (E-R) makes this an **explicit, tested decision** rather than the
    incidental consequence of indexing ``[0]``. ``product_extraction`` registers
    two prompts: a high-recall discovery pass and a precision consolidation pass
    that consumes the first pass's output. A single-pass run executes only the
    first, so its result is a recall-oriented candidate set and **not** a
    consolidated product universe. The returned record carries that fact into the
    run artifacts so no downstream reader can mistake one for the other.
    """
    sequence = prompts_for_stage(stage)
    return {
        "prompt_id": sequence[0],
        "prompt_pass_index": 1,
        "prompt_sequence_length": len(sequence),
        "prompt_sequence_complete": len(sequence) == 1,
    }


def prompts_for_stage(stage: str) -> tuple[str, ...]:
    if stage not in EXTRACTION_PROMPTS:
        raise ExtractionError(
            f"unknown extraction stage: {stage!r}", reason_code="stage_invalid"
        )
    return EXTRACTION_PROMPTS[stage]
