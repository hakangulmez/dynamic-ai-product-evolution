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
    "PROMPT_REGISTRY_VERSION",
    "load_prompt",
    "prompt_hash_of_bytes",
    "resolve_prompt_path",
]

PROMPT_REGISTRY_VERSION = "extraction_prompt_registry_v1"

# Stage -> ordered prompt ids. Labels live here, never inside a frozen prompt.
EXTRACTION_PROMPTS: dict[str, tuple[str, ...]] = {
    "product_extraction": (
        "product_discovery_recall",
        "product_consolidation_precision",
    ),
    "capability_extraction": ("capability_extraction",),
    "task_extraction": ("task_discovery_recall", "task_consolidation_precision"),
}

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


def prompts_for_stage(stage: str) -> tuple[str, ...]:
    if stage not in EXTRACTION_PROMPTS:
        raise ExtractionError(
            f"unknown extraction stage: {stage!r}", reason_code="stage_invalid"
        )
    return EXTRACTION_PROMPTS[stage]
