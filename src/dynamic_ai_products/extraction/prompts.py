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
)

# ADR-053 (G6-P). ``v1`` -> ``v2``: the product_extraction sequence gained a
# schema-bound successor at position one. The version is a property of the
# registry, not of any single prompt, so it moves for every stage at once --
# which is the point: a record that declares v1 was minted against a different
# ordering than the one this build resolves.
#
# ADR-055. ``v2`` -> ``v3``: a second successor takes position one, citing
# passages by short positional label instead of transcribed identifiers.
PROMPT_REGISTRY_VERSION = "extraction_prompt_registry_v3"

# Stage -> ordered prompt ids. Labels live here, never inside a frozen prompt.
EXTRACTION_PROMPTS: dict[str, tuple[str, ...]] = {
    "product_extraction": (
        # Position one is what ``single_pass_prompt_plan`` executes. This
        # successor states the output schema explicitly, carries the closed
        # availability vocabulary as literal text, and cites passages by short
        # positional label (ADR-055).
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
    "capability_extraction": ("capability_extraction",),
    "task_extraction": ("task_discovery_recall", "task_consolidation_precision"),
}

# Code-owned and closed. A prompt in this set carries the availability
# vocabulary as literal text and therefore must not execute without the binding
# having been checked; a prompt outside it carries no such text. One source,
# used in both directions, so the two rules cannot drift apart.
VOCABULARY_BOUND_PROMPT_IDS = frozenset(
    {"product_discovery_schema_v2", "product_discovery_schema_v3"}
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
