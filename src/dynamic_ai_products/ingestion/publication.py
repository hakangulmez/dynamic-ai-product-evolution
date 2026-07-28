"""Run identity, output-template materialization, and atomic publication.

Publication model ``staging_root_atomic_rename`` (ADR-031): every artifact is
built and verified inside a fresh run-scoped staging root on the same
filesystem as the destination, the staging directory is fsynced, and the whole
run is published by a single ``os.rename``. The run root either exists
complete or does not exist; it is never partially populated.

A staging root is non-authoritative by name (``.staging-`` prefix) and is
never removed automatically — abandoning it is an explicit operator action,
not silent repair.
"""

from __future__ import annotations

import json
import os
import re
from hashlib import sha256
from pathlib import Path

from ..provenance import WriteOnceError, write_bytes_once
from .errors import IngestionError, translate_write_once_error

__all__ = [
    "PUBLICATION_MODEL",
    "RUN_ID_PATTERN",
    "RUN_ROOT_TEMPLATES",
    "STAGING_PREFIX",
    "canonical_json_bytes",
    "derive_run_id",
    "materialize_template",
    "publish_run_root",
    "staging_root_for",
    "stage_artifact",
]

PUBLICATION_MODEL = "staging_root_atomic_rename"
RUN_ID_PATTERN = re.compile(r"^ing-[0-9a-f]{32}$")
STAGING_PREFIX = ".staging-"
RUN_ID_PLACEHOLDER = "run_id"

_PLACEHOLDER_RE = re.compile(r"\{([^{}]*)\}")

# The literal output templates bound by the contract lock. These are the exact
# strings carried in configs/pipeline_stages.yaml.
RUN_ROOT_TEMPLATES: dict[str, str] = {
    "sec_source_candidates": "data/runs/{run_id}/registry/sec_source_candidates.parquet",
    "sec_discovery_manifest": "data/runs/{run_id}/manifests/sec_discovery_manifest.json",
    "source_family_coverage": "data/runs/{run_id}/manifests/source_family_coverage.json",
    "snapshot_manifest": "data/runs/{run_id}/manifests/snapshot_manifest.jsonl",
    "normalized_documents": "data/runs/{run_id}/normalized/documents.parquet",
    "normalized_passages": "data/runs/{run_id}/normalized/passages.parquet",
    "ingestion_preflight_manifest": (
        "data/runs/{run_id}/manifests/ingestion_preflight_manifest.json"
    ),
}


def canonical_json_bytes(payload: object) -> bytes:
    """Deterministic JSON bytes: sorted keys, compact separators, trailing newline."""
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


def derive_run_id(
    *,
    code_commit: str,
    run_created_at: str,
    company_id: str,
    observation_cutoff_date: str,
    collection_receipt_sha256: str,
    packet_sha256: str,
    normalizer_version: str,
) -> str:
    """Derive the deterministic run identity from injected inputs only.

    No clock is read and no VCS is consulted: ``code_commit`` and
    ``run_created_at`` are caller-supplied. Identical inputs yield an identical
    run id, so a duplicate run is refused by the destination-exists check
    rather than silently creating a second root.
    """
    for name, value in (
        ("code_commit", code_commit),
        ("run_created_at", run_created_at),
        ("company_id", company_id),
        ("observation_cutoff_date", observation_cutoff_date),
        ("collection_receipt_sha256", collection_receipt_sha256),
        ("packet_sha256", packet_sha256),
        ("normalizer_version", normalizer_version),
    ):
        if not isinstance(value, str) or not value.strip():
            raise IngestionError(
                f"run identity requires a non-blank {name}",
                reason_code="run_identity_invalid",
            )
    payload = {
        "contract": "ingestion_preflight_manifest@0.1.0",
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "code_commit": code_commit,
        "run_created_at": run_created_at,
        "collection_receipt_sha256": collection_receipt_sha256,
        "packet_sha256": packet_sha256,
        "normalizer_version": normalizer_version,
    }
    digest = sha256(canonical_json_bytes(payload)).hexdigest()
    return f"ing-{digest[:32]}"


def _require_valid_run_id(run_id: str) -> str:
    if not isinstance(run_id, str) or not RUN_ID_PATTERN.fullmatch(run_id):
        raise IngestionError(
            "run_id must match ^ing-[0-9a-f]{32}$",
            reason_code="run_id_invalid",
        )
    return run_id


def template_placeholders(template: str) -> list[str]:
    """Return the placeholder names in a template, in order of appearance."""
    return _PLACEHOLDER_RE.findall(template)


def materialize_template(template: str, run_id: str) -> str:
    """Resolve an output template. The only sanctioned substitution site.

    Refuses any template whose placeholder set is not exactly ``{run_id}``,
    and refuses any residual brace in the result. There is no implicit
    substitution, no environment lookup, and no default value anywhere.
    """
    if not isinstance(template, str) or not template:
        raise IngestionError(
            "output template must be a non-empty string",
            reason_code="template_invalid",
        )
    _require_valid_run_id(run_id)

    placeholders = template_placeholders(template)
    if placeholders != [RUN_ID_PLACEHOLDER]:
        raise IngestionError(
            f"output template must contain exactly one {{run_id}} placeholder: {template}",
            reason_code="template_invalid",
        )
    if template.count("{") != 1 or template.count("}") != 1:
        raise IngestionError(
            f"output template has unbalanced or extra braces: {template}",
            reason_code="template_invalid",
        )
    if "{run_id}" not in template.split("/"):
        raise IngestionError(
            f"{{run_id}} must be a complete path segment: {template}",
            reason_code="template_invalid",
        )

    resolved = template.replace("{run_id}", run_id)
    if "{" in resolved or "}" in resolved:
        raise IngestionError(
            f"materialized path retains a brace: {resolved}",
            reason_code="template_invalid",
        )
    return resolved


def staging_root_for(runs_root: str | Path, run_id: str) -> Path:
    """Path of the non-authoritative staging root for a run."""
    _require_valid_run_id(run_id)
    return Path(runs_root) / f"{STAGING_PREFIX}{run_id}"


def run_root_for(runs_root: str | Path, run_id: str) -> Path:
    _require_valid_run_id(run_id)
    return Path(runs_root) / run_id


def open_staging_root(runs_root: str | Path, run_id: str) -> Path:
    """Create a fresh staging root. Refuses to reuse an existing one."""
    staging = staging_root_for(runs_root, run_id)
    try:
        staging.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise IngestionError(
            f"staging root already exists and is never reused: {staging}",
            reason_code="staging_root_exists",
        ) from exc
    except OSError as exc:
        raise IngestionError(
            f"failed to create staging root: {staging}",
            reason_code="write_error",
        ) from exc
    return staging


def stage_artifact(staging_root: str | Path, relative_path: str, data: bytes) -> str:
    """Write one artifact inside the staging root and return its SHA-256."""
    destination = Path(staging_root) / relative_path
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise IngestionError(
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
    """Publish a staging root as an immutable run root with one atomic rename.

    Fsyncs the staging tree, renames it onto the final run root, then fsyncs
    the parent so the rename is durable. Publication is atomic: the run root is
    never partially populated. A crash between the rename and the parent fsync
    may leave the run root absent after reboot, but never half-built.
    """
    staging = staging_root_for(runs_root, run_id)
    final = run_root_for(runs_root, run_id)

    if not staging.is_dir():
        raise IngestionError(
            f"no staging root to publish: {staging}",
            reason_code="staging_root_missing",
        )
    if final.is_symlink() or final.exists():
        raise IngestionError(
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
        raise IngestionError(
            f"failed to publish run root: {final}",
            reason_code="publication_failed",
            detail=(
                "staging root is preserved for inspection and is never "
                "removed automatically"
            ),
        ) from exc
    return final
