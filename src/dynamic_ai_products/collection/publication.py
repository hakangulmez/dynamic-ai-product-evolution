"""Collection run identity, output templates, and atomic publication (ADR-032).

The run identity is derived from exactly fourteen caller-injected or
pin-verified values. The package reads neither clock nor VCS. The identity is
derived — and a duplicate refused — BEFORE a staging root is opened and before
any network request is made, so a duplicate run issues zero requests.

Publication reuses ADR-031's ``staging_root_atomic_rename``: build and verify
everything in a run-scoped staging root on the same filesystem, fsync it, then
publish the whole run with a single ``os.rename``.
"""

from __future__ import annotations

import json
import os
import re
from hashlib import sha256
from pathlib import Path
from typing import Any

from ..provenance import WriteOnceError, write_bytes_once
from .errors import CollectionError, translate_write_once_error

__all__ = [
    "COLLECTION_MANIFEST_CONTRACT",
    "PUBLICATION_MODEL",
    "RUN_ID_IDENTITY_KEYS",
    "RUN_ID_PATTERN",
    "RUN_ROOT_TEMPLATES",
    "STAGING_PREFIX",
    "canonical_json_bytes",
    "canonical_jsonl_bytes",
    "derive_collection_run_id",
    "materialize_template",
    "open_staging_root",
    "publish_run_root",
    "refuse_duplicate_run",
    "run_root_for",
    "stage_artifact",
    "staging_root_for",
]

COLLECTION_MANIFEST_CONTRACT = "official_web_collection_manifest@0.1.0"
PUBLICATION_MODEL = "staging_root_atomic_rename"
RUN_ID_PATTERN = re.compile(r"^owc-[0-9a-f]{32}$")
STAGING_PREFIX = ".staging-"
RUN_ID_PLACEHOLDER = "collection_run_id"

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")

# Exactly these fourteen keys form the run identity payload.
RUN_ID_IDENTITY_KEYS: tuple[str, ...] = (
    "canonicalization_version",
    "code_commit",
    "collection_client_contract_hash",
    "collection_receipt_sha256",
    "contract",
    "filing_index_sha256",
    "packet_sha256",
    "parent_ingestion_manifest_sha256",
    "primary_document_sha256",
    "rate_limit_policy_version",
    "request_plan_sha256",
    "robots_policy_version",
    "run_created_at",
    "submissions_sha256",
)

RUN_ROOT_TEMPLATES: dict[str, str] = {
    "official_web_candidates": (
        "data/runs/{collection_run_id}/registry/official_web_candidates.jsonl"
    ),
    "web_discovery_manifest": (
        "data/runs/{collection_run_id}/manifests/web_discovery_manifest.json"
    ),
    "web_snapshot_manifest": (
        "data/runs/{collection_run_id}/manifests/web_snapshot_manifest.jsonl"
    ),
    "web_collection_receipt": (
        "data/runs/{collection_run_id}/manifests/web_collection_receipt.json"
    ),
    "web_collection_request_plan": (
        "data/runs/{collection_run_id}/manifests/web_collection_request_plan.json"
    ),
    "source_family_coverage_v2": (
        "data/runs/{collection_run_id}/manifests/source_family_coverage.v2.json"
    ),
    "official_web_collection_manifest": (
        "data/runs/{collection_run_id}/manifests/official_web_collection_manifest.json"
    ),
}


def canonical_json_bytes(payload: object) -> bytes:
    """Deterministic JSON bytes: sorted keys, compact separators, trailing newline.

    Byte-identical to the ingestion package's serializer by contract; the two
    are pinned together by a cross-package equality test rather than an import,
    because collection must not depend on ingestion.
    """
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        + "\n"
    ).encode("utf-8")


def canonical_jsonl_bytes(records: list[object]) -> bytes:
    lines = [
        json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        for record in records
    ]
    return ("\n".join(lines) + ("\n" if lines else "")).encode("utf-8")


def derive_collection_run_id(identity: dict[str, Any]) -> str:
    """Derive ``owc-<32 hex>`` from exactly the fourteen identity keys."""
    if not isinstance(identity, dict):
        raise CollectionError(
            "run identity must be a mapping", reason_code="run_identity_invalid"
        )
    missing = sorted(set(RUN_ID_IDENTITY_KEYS) - set(identity))
    extra = sorted(set(identity) - set(RUN_ID_IDENTITY_KEYS))
    if missing or extra:
        raise CollectionError(
            f"run identity keys are wrong; missing={missing} extra={extra}",
            reason_code="run_identity_invalid",
        )
    for key in RUN_ID_IDENTITY_KEYS:
        value = identity[key]
        if not isinstance(value, str) or not value.strip():
            raise CollectionError(
                f"run identity requires a non-blank {key}",
                reason_code="run_identity_invalid",
            )
    if identity["contract"] != COLLECTION_MANIFEST_CONTRACT:
        raise CollectionError(
            f"run identity contract must be {COLLECTION_MANIFEST_CONTRACT}",
            reason_code="run_identity_invalid",
        )
    digest = sha256(canonical_json_bytes(identity)).hexdigest()
    return f"owc-{digest[:32]}"


def _require_valid_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise CollectionError(
            "collection_run_id must match ^owc-[0-9a-f]{32}$",
            reason_code="run_id_invalid",
        )
    return run_id


def materialize_template(template: str, run_id: str) -> str:
    """Resolve an output template. The only sanctioned substitution site."""
    if not isinstance(template, str) or not template:
        raise CollectionError(
            "output template must be a non-empty string", reason_code="template_invalid"
        )
    _require_valid_run_id(run_id)
    placeholders = _PLACEHOLDER_RE.findall(template)
    if placeholders != [RUN_ID_PLACEHOLDER]:
        raise CollectionError(
            f"template must contain exactly one {{collection_run_id}}: {template}",
            reason_code="template_invalid",
        )
    if template.count("{") != 1 or template.count("}") != 1:
        raise CollectionError(
            f"template has unbalanced or extra braces: {template}",
            reason_code="template_invalid",
        )
    if "{collection_run_id}" not in template.split("/"):
        raise CollectionError(
            f"{{collection_run_id}} must be a complete path segment: {template}",
            reason_code="template_invalid",
        )
    resolved = template.replace("{collection_run_id}", run_id)
    if "{" in resolved or "}" in resolved:
        raise CollectionError(
            f"materialized path retains a brace: {resolved}",
            reason_code="template_invalid",
        )
    return resolved


def staging_root_for(runs_root: str | Path, run_id: str) -> Path:
    _require_valid_run_id(run_id)
    return Path(runs_root) / f"{STAGING_PREFIX}{run_id}"


def run_root_for(runs_root: str | Path, run_id: str) -> Path:
    _require_valid_run_id(run_id)
    return Path(runs_root) / run_id


def refuse_duplicate_run(runs_root: str | Path, run_id: str) -> None:
    """Refuse an existing staging or final run root BEFORE any network request."""
    staging = staging_root_for(runs_root, run_id)
    final = run_root_for(runs_root, run_id)
    if final.is_symlink() or final.exists():
        raise CollectionError(
            f"run root already exists; runs are never overwritten: {final}",
            reason_code="run_root_exists",
        )
    if staging.is_symlink() or staging.exists():
        raise CollectionError(
            f"staging root already exists and is never reused: {staging}",
            reason_code="staging_root_exists",
        )


def open_staging_root(runs_root: str | Path, run_id: str) -> Path:
    staging = staging_root_for(runs_root, run_id)
    try:
        staging.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise CollectionError(
            f"staging root already exists and is never reused: {staging}",
            reason_code="staging_root_exists",
        ) from exc
    except OSError as exc:
        raise CollectionError(
            f"failed to create staging root: {staging}", reason_code="write_error"
        ) from exc
    return staging


def stage_artifact(staging_root: str | Path, relative_path: str, data: bytes) -> str:
    destination = Path(staging_root) / relative_path
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise CollectionError(
            f"failed to create staging directory for {relative_path}",
            reason_code="write_error",
        ) from exc
    try:
        return write_bytes_once(destination, data, what=f"staged {relative_path}")
    except WriteOnceError as exc:
        raise translate_write_once_error(exc) from exc


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def publish_run_root(runs_root: str | Path, run_id: str) -> Path:
    """Publish a staging root as an immutable run root with one atomic rename."""
    staging = staging_root_for(runs_root, run_id)
    final = run_root_for(runs_root, run_id)
    if not staging.is_dir():
        raise CollectionError(
            f"no staging root to publish: {staging}", reason_code="staging_root_missing"
        )
    if final.is_symlink() or final.exists():
        raise CollectionError(
            f"run root already exists; runs are never overwritten: {final}",
            reason_code="run_root_exists",
        )
    try:
        for directory in sorted(
            {p.parent for p in staging.rglob("*") if p.is_file()} | {staging}
        ):
            _fsync_directory(directory)
        os.rename(staging, final)
        _fsync_directory(final.parent)
    except OSError as exc:
        raise CollectionError(
            f"failed to publish run root: {final}",
            reason_code="publication_failed",
            detail="staging root is preserved for inspection and never auto-removed",
        ) from exc
    return final
