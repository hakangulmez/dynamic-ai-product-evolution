"""ADR-101 lineage-aggregate authority validation, shared (ADR-103).

Governing documents:
- docs/DECISION_LOG.md ADR-101 (lineage aggregation over enumerated execution
  runs), ADR-102 (the shell-determination consumer), ADR-103 (this extraction
  and the packet consumer)

One aggregate manifest is the sole authority root for every lineage consumer:
the shell-company determination (ADR-102) and the Item 1 packet build
(ADR-103) both open **exactly** the ``shards_authoritative[].run_dir``
directories the validated manifest names, and nothing else. That validation
used to live inside ``shell_company_determination``; a second consumer would
have had to import it from there — a cycle, because that module already
imports this package's bundle loader — or duplicate it. It lives here instead,
imported by both, importing neither.

Everything about the validation is unchanged from ADR-102: the aggregate must
declare ``acquisition_queue_aggregate_manifest@0.2.0`` and validate against
its schema; coverage must be complete; a ``run_dir`` that is absolute,
traverses a parent, or resolves outside the repository root is refused before
any open; each referenced bundle and acquisition manifest is re-hashed against
the aggregate's own record before any primary document is read; the unchanged
bundle loader then verifies every document's byte length and SHA-256; carrier
provenance must agree across shards; and a ``(cik, accession)`` row belongs to
exactly one shard. ``superseded_directories`` and ``shards_not_authoritative``
are never resolved or opened.

Failures raise :class:`LineageAuthorityError`. Each consumer owns its public
error type and re-raises with the identical message, so ADR-102's exception
semantics do not move.

This module performs no network access and no model call, names no URL, and
never reads the clock.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from jsonschema import Draft202012Validator

from ..universe.acquisition_queue import (
    AGGREGATE_MANIFEST_CONTRACT_V2,
    AGGREGATE_V2_SCHEMA_RELATIVE_PATH,
)
from ..universe.io_utils import read_json
from ..universe.primary_document_acquisition import (
    ACQUISITION_MANIFEST_FILENAME,
    BUNDLE_MANIFEST_FILENAME,
)
from .baseline_packet import load_bundle


class LineageAuthorityError(ValueError):
    """The aggregate, a named shard, or its evidence is unusable; refuse."""


def resolved_run_dir(root: Path, raw: object, shard_index: int) -> Path:
    """Resolve a run_dir the aggregate names, refusing anything that escapes."""
    where = f"shards_authoritative[shard_index={shard_index}].run_dir"
    if not isinstance(raw, str) or not raw.strip():
        raise LineageAuthorityError(f"{where} is not a usable path: {raw!r}.")
    candidate = Path(raw)
    if candidate.is_absolute():
        raise LineageAuthorityError(
            f"{where} is absolute ({raw!r}); a shard directory is named "
            "relative to the repository root."
        )
    if ".." in candidate.parts:
        raise LineageAuthorityError(
            f"{where} traverses a parent directory ({raw!r})."
        )
    base = root.resolve()
    resolved = (base / candidate).resolve()
    if not resolved.is_relative_to(base):
        raise LineageAuthorityError(
            f"{where} resolves outside the repository root ({raw!r})."
        )
    return resolved


def load_lineage_bundles(
    repo_root: str | Path, aggregate_manifest_path: str | Path
) -> tuple[dict, list[dict], str, dict]:
    """Validate one ADR-101 aggregate and open exactly the shards it names.

    Fails closed before anything is written. Each referenced bundle and
    acquisition manifest is re-hashed against the aggregate's own record
    *before* a primary document is read: equality means the bytes on disk are
    byte-identical to the bytes the aggregate bound, which is why the shard
    plans are not regenerated here. The unchanged bundle loader then verifies
    every document's byte length and SHA-256.
    """
    root = Path(repo_root)
    path = Path(aggregate_manifest_path)
    if not path.is_file():
        raise LineageAuthorityError(f"Aggregate manifest not found: {path}")
    raw = path.read_bytes()
    try:
        aggregate = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LineageAuthorityError(
            f"Aggregate manifest is not valid JSON: {exc}"
        ) from exc
    if not isinstance(aggregate, dict):
        raise LineageAuthorityError(
            f"Aggregate manifest is not a JSON object: {path}"
        )
    declared = aggregate.get("aggregate_manifest_contract")
    if declared != AGGREGATE_MANIFEST_CONTRACT_V2:
        raise LineageAuthorityError(
            f"Aggregate manifest declares {declared!r}; the lineage cohort is "
            f"read only from {AGGREGATE_MANIFEST_CONTRACT_V2}."
        )
    schema = read_json(root / AGGREGATE_V2_SCHEMA_RELATIVE_PATH)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(aggregate),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise LineageAuthorityError(
            f"Aggregate manifest violates "
            f"{AGGREGATE_V2_SCHEMA_RELATIVE_PATH.name}: {details}"
        )
    if aggregate["coverage_complete"] is not True:
        raise LineageAuthorityError(
            "Aggregate coverage is partial "
            f"({aggregate['coverage_statement']}). A full-cohort determination "
            "is built only from complete coverage; a partial one would "
            "under-count exclusions without saying so."
        )
    records = aggregate["shards_authoritative"]
    if not records:
        raise LineageAuthorityError(
            "Aggregate names no authoritative shard; there is nothing to read."
        )
    indices = [record["shard_index"] for record in records]
    duplicates = sorted({i for i in indices if indices.count(i) > 1})
    if duplicates:
        raise LineageAuthorityError(
            f"Aggregate repeats shard index {duplicates}; one index names one "
            "authoritative directory."
        )
    directories = [record["run_dir"] for record in records]
    repeated = sorted({d for d in directories if directories.count(d) > 1})
    if repeated:
        raise LineageAuthorityError(
            f"Aggregate repeats run directory {repeated}."
        )

    shards: list[dict] = []
    rows_seen: dict[tuple[str, str], int] = {}
    provenance: dict | None = None
    # Sorted rather than taken in array order: the record order is computed
    # from the shard index itself, so it holds even for an aggregate whose
    # array arrived out of order, and cannot depend on how the runs were
    # enumerated.
    for record in sorted(records, key=lambda r: r["shard_index"]):
        index = record["shard_index"]
        run_dir = resolved_run_dir(root, record["run_dir"], index)
        if not run_dir.is_dir():
            raise LineageAuthorityError(
                f"Shard {index}: run directory not found: {run_dir}"
            )
        for filename, key in (
            (BUNDLE_MANIFEST_FILENAME, "bundle_manifest_sha256"),
            (ACQUISITION_MANIFEST_FILENAME, "acquisition_manifest_sha256"),
        ):
            target = run_dir / filename
            if not target.is_file():
                raise LineageAuthorityError(
                    f"Shard {index}: {filename} is missing from {run_dir}."
                )
            observed = sha256(target.read_bytes()).hexdigest()
            if observed != record[key]:
                raise LineageAuthorityError(
                    f"Shard {index}: {filename} hashes to {observed}, but the "
                    f"aggregate records {record[key]}. The evidence on disk is "
                    "not the evidence that was aggregated; nothing is read."
                )
        manifest, entries, bundle_sha = load_bundle(root, run_dir)
        if len(entries) != record["carrier_rows"]:
            raise LineageAuthorityError(
                f"Shard {index}: bundle holds {len(entries)} row(s) but the "
                f"aggregate records {record['carrier_rows']} carrier row(s)."
            )
        declared_provenance = {
            "carrier_run_id": manifest["provenance"]["carrier_run_id"],
            "carrier_manifest_sha256": manifest["provenance"][
                "carrier_manifest_sha256"
            ],
            "freeze_record_sha256": manifest["provenance"][
                "freeze_record_sha256"
            ],
        }
        if provenance is None:
            provenance = declared_provenance
        elif declared_provenance != provenance:
            raise LineageAuthorityError(
                f"Shard {index}: carrier provenance {declared_provenance} "
                f"disagrees with {provenance}. One cohort has one carrier; "
                "disagreement is refused, never reconciled."
            )
        for entry in entries:
            key = (entry["cik"], entry["accession"])
            if key in rows_seen:
                raise LineageAuthorityError(
                    f"Row {key} appears in shard {rows_seen[key]} and shard "
                    f"{index}; a carrier row belongs to exactly one shard."
                )
            rows_seen[key] = index
        shards.append({
            "shard_index": index,
            "run_dir": record["run_dir"],
            "bundle_manifest_sha256": bundle_sha,
            "acquisition_manifest_sha256": record["acquisition_manifest_sha256"],
            "rows": len(entries),
            "entries": entries,
            # Consumers beyond ADR-102 read these two without re-opening the
            # bundle manifest; both come from the already-validated manifest.
            "bundle_contract": manifest["bundle_contract"],
            "route_validation": dict(manifest["route_validation"]),
        })
    return aggregate, shards, sha256(raw).hexdigest(), provenance or {}
