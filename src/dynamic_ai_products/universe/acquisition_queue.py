"""W3 batch primary-document acquisition queue (fixture-first).

Governing documents:
- docs/DECISION_LOG.md ADR-092 (two-hop primary-document acquisition),
  ADR-093 (declared lengths), ADR-095 (this design)
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md

Three separately governed stages sit **around** the committed acquisition
runner, which is reused unchanged: a **planner** that derives immutable shard
plans from a frozen carrier, an **executor** that runs an operator-named
allowlist of shards, and an **aggregator** that reports coverage over
completed shards only. Each stage writes its own governed manifest.

**Shard plans are artefacts, not arguments.** The planner writes every shard
plan write-once under its own run directory and hashes each one into a plan
manifest. The executor regenerates the requested plan in memory, compares it
to the persisted artefact **byte for byte and by sha256**, and then executes
the persisted file. It never executes an ephemeral or hand-supplied plan, so
a plan cannot be edited between planning and execution without refusal.

**Determinism.** Shard membership is a pure function of (carrier bytes,
selection filters, shard size, index): accessions are sorted lexicographically
and sliced. There is no clock, no randomness and no cursor. Complete carrier
groups cannot straddle a shard boundary, because shards partition accessions
and each accession carries its whole row group.

**Candidacy is not authority.** A run directory holding both a bundle
manifest and an acquisition manifest is a **candidate** for admission, nothing
more. Executor and aggregator alike admit it only after its content binds to
the regenerated shard plan: schema, plan hash, counts, budget and the bundle
output hash. A pair that fails binding raises ``ShardIntegrityError`` and is
never recorded as authoritative. A handled failure also writes a receipt; an
interrupted or crashed shard may write nothing at all. Receipt presence is
therefore diagnostic only, and both failure shapes stay non-authoritative.

**Authorization.** One executor invocation authorizes exactly the shard
indices enumerated on its command line, at the request count the operator
declared. There is no flag that expands to the whole queue. Aggregation is a
separate command behind its own gate, and the executor never writes an
aggregate.

This module performs no network access and no model call: it derives plans
from local carrier bytes and delegates every request to the injected
transports the acquisition runner already owns.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from jsonschema import Draft202012Validator

from ..provenance import write_bytes_once
from .freeze import create_run_directory
from .identifiers import IdentifierError, normalize_cik
from .io_utils import read_json, sha256_bytes
from .primary_document_acquisition import (
    ACQUISITION_MANIFEST_FILENAME,
    ADMITTED_FORMS,
    ADMITTED_STRATA,
    BUNDLE_MANIFEST_FILENAME,
    FAILURE_RECEIPT_FILENAME,
    PLAN_CONTRACT_V2,
    PrimaryAcquisitionResult,
    PrimaryDocumentPlanError,
    run_primary_document_acquisition,
)

QUEUE_DEFINITION_CONTRACT = "acquisition_queue_definition@0.1.0"
PLAN_MANIFEST_CONTRACT = "acquisition_queue_plan_manifest@0.1.0"
EXECUTION_MANIFEST_CONTRACT = "acquisition_queue_execution_manifest@0.1.0"
AGGREGATE_MANIFEST_CONTRACT = "acquisition_queue_aggregate_manifest@0.1.0"

PLAN_MANIFEST_FILENAME = "acquisition_queue_plan_manifest.json"
EXECUTION_MANIFEST_FILENAME = "acquisition_queue_execution_manifest.json"
AGGREGATE_MANIFEST_FILENAME = "acquisition_queue_aggregate_manifest.json"

PLAN_MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/acquisition_queue_plan_manifest.schema.json"
)
EXECUTION_MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/acquisition_queue_execution_manifest.schema.json"
)
AGGREGATE_MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/acquisition_queue_aggregate_manifest.schema.json"
)
#: The queue always emits plan v0.2, so a shard's acquisition manifest is
#: always a budgeted successor: v0.5 for sec_live, v0.4 for fixture replay.
ACQUISITION_V4_SCHEMA_RELATIVE_PATH = Path(
    "schemas/primary_document_acquisition_manifest.v4.schema.json"
)
ACQUISITION_V5_SCHEMA_RELATIVE_PATH = Path(
    "schemas/primary_document_acquisition_manifest.v5.schema.json"
)
TRANSPORT_KIND_SEC_LIVE = "sec_live"

#: Declared stop policies. Neither is a default: the operator names one.
ON_FAILURE_STOP = "stop"
ON_FAILURE_CONTINUE = "continue"
STOP_POLICIES = (ON_FAILURE_STOP, ON_FAILURE_CONTINUE)

SHARD_OUTCOME_AUTHORITATIVE = "authoritative"
SHARD_OUTCOME_FAILED = "failed"
SHARD_OUTCOME_NOT_ATTEMPTED = "not_attempted"

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_QUEUE_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class AcquisitionQueueError(ValueError):
    """The queue definition, a persisted plan, or an invocation is unusable."""


def shard_plan_filename(shard_index: int) -> str:
    """Zero-padded so lexicographic and numeric order agree."""
    return f"shard-{shard_index:04d}.plan.json"


def shard_run_id(run_id: str, shard_index: int) -> str:
    return f"{run_id}-shard-{shard_index:04d}"


def canonical_plan_bytes(payload: dict) -> bytes:
    """The one serialization both planner and executor use.

    Byte-for-byte comparison is only meaningful if regeneration is
    deterministic, so key order and spacing are fixed here rather than left to
    the caller.
    """
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


@dataclass
class QueueSelection:
    stratum: str
    forms: tuple[str, ...]
    restricted_accessions: Optional[tuple[str, ...]]


@dataclass
class QueueDefinition:
    queue_id: str
    description: str
    carrier_relative_path: str
    carrier_run_id: str
    carrier_manifest_sha256: str
    freeze_record_sha256: str
    selection: QueueSelection
    shard_size: int
    per_accession_allowance_bytes: int
    max_metadata_bytes: int
    max_document_bytes: int
    base_url: str
    route_validation: dict
    deferred_cohorts: tuple[dict, ...]
    definition_sha256: str


@dataclass
class ShardPlan:
    shard_index: int
    accessions: tuple[str, ...]
    carrier_rows: int
    planned_requests: int
    max_retained_bytes: int
    payload: dict

    @property
    def plan_sha256(self) -> str:
        return sha256_bytes(canonical_plan_bytes(self.payload))


@dataclass
class QueuePlanResult:
    run_id: str
    run_dir: Optional[Path]
    definition_sha256: str
    shards: list[ShardPlan] = field(default_factory=list)
    manifest_path: Optional[Path] = None
    counts: dict = field(default_factory=dict)


@dataclass
class ShardExecution:
    shard_index: int
    shard_run_id: str
    outcome: str
    run_dir: Optional[str] = None
    plan_sha256: Optional[str] = None
    acquisition_manifest_sha256: Optional[str] = None
    bundle_manifest_sha256: Optional[str] = None
    retained_bytes_total: Optional[int] = None
    failure_reason_code: Optional[str] = None
    receipt_present: bool = False


@dataclass
class QueueAggregateResult:
    manifest: dict
    run_dir: Optional[Path]
    manifest_path: Optional[Path]


@dataclass
class QueueExecutionResult:
    run_id: str
    run_dir: Optional[Path]
    executions: list[ShardExecution] = field(default_factory=list)
    manifest_path: Optional[Path] = None
    stopped_at_shard_index: Optional[int] = None
    counts: dict = field(default_factory=dict)


# --- queue definition --------------------------------------------------------


def validate_queue_definition(payload: object, definition_sha256: str) -> QueueDefinition:
    """Validate a queue definition; nothing here is defaulted."""
    if not isinstance(payload, dict):
        raise AcquisitionQueueError("Queue definition must be a JSON object.")
    if payload.get("queue_contract") != QUEUE_DEFINITION_CONTRACT:
        raise AcquisitionQueueError(
            f"Queue definition must declare {QUEUE_DEFINITION_CONTRACT!r}."
        )
    for key in ("queue_id", "description", "carrier", "selection", "shard_size",
                "per_accession_allowance_bytes", "max_metadata_bytes",
                "max_document_bytes", "base_url", "route_validation",
                "deferred_cohorts"):
        if key not in payload:
            raise AcquisitionQueueError(f"Queue definition is missing {key!r}.")

    queue_id = payload["queue_id"]
    if not isinstance(queue_id, str) or not _QUEUE_ID_RE.match(queue_id):
        raise AcquisitionQueueError(
            "queue_id must be lowercase letters, digits and hyphens; it names "
            "run directories."
        )

    carrier = payload["carrier"]
    if not isinstance(carrier, dict):
        raise AcquisitionQueueError("Queue definition carrier must be an object.")
    for key in ("relative_path", "carrier_run_id", "carrier_manifest_sha256",
                "freeze_record_sha256"):
        if key not in carrier:
            raise AcquisitionQueueError(f"Queue definition carrier is missing {key!r}.")
    for key in ("carrier_manifest_sha256", "freeze_record_sha256"):
        value = carrier[key]
        if not isinstance(value, str) or not _SHA256_RE.match(value):
            raise AcquisitionQueueError(
                f"carrier.{key} must be a canonical lowercase 64-hex digest."
            )
    relative = carrier["relative_path"]
    if not isinstance(relative, str) or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise AcquisitionQueueError(
            "carrier.relative_path must be a repository-relative path with no "
            "parent-directory segment."
        )

    selection = payload["selection"]
    if not isinstance(selection, dict):
        raise AcquisitionQueueError("Queue definition selection must be an object.")
    stratum = selection.get("stratum")
    if stratum not in ADMITTED_STRATA:
        raise AcquisitionQueueError(
            f"selection.stratum {stratum!r} must be {ADMITTED_STRATA[0]!r}; the "
            "FPI extension is preserved by the carrier and handled elsewhere."
        )
    forms = selection.get("forms")
    if (
        not isinstance(forms, list) or not forms
        or any(f not in ADMITTED_FORMS for f in forms)
        or len(set(forms)) != len(forms)
    ):
        raise AcquisitionQueueError(
            f"selection.forms must be a non-empty duplicate-free subset of "
            f"{list(ADMITTED_FORMS)!r}."
        )
    restricted = selection.get("restricted_accessions")
    if restricted is not None:
        if (
            not isinstance(restricted, list) or not restricted
            or any(not isinstance(a, str) for a in restricted)
            or len(set(restricted)) != len(restricted)
        ):
            raise AcquisitionQueueError(
                "selection.restricted_accessions, when present, must be a "
                "non-empty duplicate-free array of accession strings."
            )

    for key in ("shard_size", "per_accession_allowance_bytes",
                "max_metadata_bytes", "max_document_bytes"):
        value = payload[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise AcquisitionQueueError(
                f"{key} must be an explicit positive integer; it is never "
                "defaulted in code."
            )

    route = payload["route_validation"]
    if not isinstance(route, dict):
        raise AcquisitionQueueError("route_validation must be an object.")
    for key in ("probe_run_id", "probe_manifest_sha256", "covered_accessions",
                "note"):
        if key not in route:
            raise AcquisitionQueueError(f"route_validation is missing {key!r}.")

    deferred = payload["deferred_cohorts"]
    if not isinstance(deferred, list):
        raise AcquisitionQueueError(
            "deferred_cohorts must be an array; a deferred cohort is recorded "
            "explicitly so the deferral stays auditable, never dropped."
        )

    return QueueDefinition(
        queue_id=queue_id,
        description=str(payload["description"]),
        carrier_relative_path=relative,
        carrier_run_id=str(carrier["carrier_run_id"]),
        carrier_manifest_sha256=carrier["carrier_manifest_sha256"],
        freeze_record_sha256=carrier["freeze_record_sha256"],
        selection=QueueSelection(
            stratum=stratum,
            forms=tuple(forms),
            restricted_accessions=tuple(restricted) if restricted else None,
        ),
        shard_size=payload["shard_size"],
        per_accession_allowance_bytes=payload["per_accession_allowance_bytes"],
        max_metadata_bytes=payload["max_metadata_bytes"],
        max_document_bytes=payload["max_document_bytes"],
        base_url=str(payload["base_url"]),
        route_validation=dict(route),
        deferred_cohorts=tuple(deferred),
        definition_sha256=definition_sha256,
    )


def load_queue_definition(path: str | Path) -> QueueDefinition:
    definition_path = Path(path)
    if not definition_path.is_file():
        raise AcquisitionQueueError(f"Queue definition not found: {definition_path}")
    raw = definition_path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcquisitionQueueError(
            f"Queue definition is not valid JSON: {exc}"
        ) from exc
    return validate_queue_definition(payload, sha256_bytes(raw))


# --- deterministic sharding --------------------------------------------------


def select_carrier_accessions(
    definition: QueueDefinition, carrier_path: Path
) -> dict[str, list[dict]]:
    """Group in-scope carrier rows by accession, complete groups only.

    Read-only. A restricted definition must name accessions the carrier
    actually carries: a missing one is refused rather than silently skipped,
    so a canary cohort cannot shrink without saying so.
    """
    if not carrier_path.is_file():
        raise AcquisitionQueueError(f"Carrier not found: {carrier_path}")
    groups: dict[str, list[dict]] = {}
    for line in carrier_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("baseline_status") != "baseline_candidate":
            continue
        if row.get("stratum") != definition.selection.stratum:
            continue
        if row.get("baseline_form") not in definition.selection.forms:
            continue
        accession = row.get("baseline_accession")
        if not accession:
            continue
        groups.setdefault(accession, []).append(row)

    restricted = definition.selection.restricted_accessions
    if restricted is not None:
        missing = [a for a in restricted if a not in groups]
        if missing:
            raise AcquisitionQueueError(
                "Restricted queue definition names accessions absent from the "
                f"selected carrier rows: {missing}."
            )
        groups = {a: groups[a] for a in restricted}

    for accession, rows in groups.items():
        forms = {r["baseline_form"] for r in rows}
        dates = {r["baseline_filing_date"] for r in rows}
        if len(forms) != 1 or len(dates) != 1:
            raise AcquisitionQueueError(
                f"Accession {accession} carries inconsistent form/date across "
                f"its carrier rows: forms={sorted(forms)} dates={sorted(dates)}."
            )
    return groups


def build_shard_plans(
    definition: QueueDefinition, groups: dict[str, list[dict]]
) -> list[ShardPlan]:
    """Slice sorted accessions into shards and emit one plan v0.2 each."""
    accessions = sorted(groups)
    size = definition.shard_size
    shards: list[ShardPlan] = []
    for index in range(0, (len(accessions) + size - 1) // size):
        window = accessions[index * size:(index + 1) * size]
        documents = []
        rows_total = 0
        for accession in window:
            rows = sorted(groups[accession], key=lambda r: r["cik"])
            rows_total += len(rows)
            try:
                ciks = [normalize_cik(r["cik"]) for r in rows]
            except IdentifierError as exc:
                raise AcquisitionQueueError(f"{accession}: {exc}") from exc
            documents.append({
                "accession": accession,
                "form": rows[0]["baseline_form"],
                "directory_cik": min(ciks),
                "carrier_rows": [
                    {
                        "stratum": r["stratum"],
                        "cik": normalize_cik(r["cik"]),
                        "baseline_filing_date": r["baseline_filing_date"],
                    }
                    for r in rows
                ],
            })
        budget = len(window) * definition.per_accession_allowance_bytes
        payload = {
            "plan_contract": PLAN_CONTRACT_V2,
            "description": (
                f"Shard {index} of queue {definition.queue_id!r}: "
                f"{len(window)} accession(s) serving {rows_total} carrier "
                f"row(s), {2 * len(window)} request(s). Generated from the "
                "named immutable queue definition; possessing this plan "
                "authorizes no request."
            ),
            "base_url": definition.base_url,
            "max_metadata_bytes": definition.max_metadata_bytes,
            "max_document_bytes": definition.max_document_bytes,
            "max_retained_bytes": budget,
            "queue_id": definition.queue_id,
            "queue_definition_sha256": definition.definition_sha256,
            "shard_index": index,
            "provenance": {
                "carrier_run_id": definition.carrier_run_id,
                "carrier_manifest_sha256": definition.carrier_manifest_sha256,
                "freeze_record_sha256": definition.freeze_record_sha256,
            },
            "route_validation": dict(definition.route_validation),
            "documents": documents,
        }
        shards.append(ShardPlan(
            shard_index=index,
            accessions=tuple(window),
            carrier_rows=rows_total,
            planned_requests=2 * len(window),
            max_retained_bytes=budget,
            payload=payload,
        ))
    return shards


# --- stage 1: the planner ----------------------------------------------------


def run_queue_planner(
    *,
    repo_root: str | Path,
    definition_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> QueuePlanResult:
    """Derive shard plans and persist each one write-once."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise AcquisitionQueueError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    definition = load_queue_definition(definition_path)
    groups = select_carrier_accessions(
        definition, root / definition.carrier_relative_path
    )
    shards = build_shard_plans(definition, groups)
    if not shards:
        raise AcquisitionQueueError(
            "Queue definition selects no accession; there is nothing to plan."
        )

    result = QueuePlanResult(
        run_id=run_id, run_dir=None,
        definition_sha256=definition.definition_sha256, shards=shards,
    )
    counts = {
        "carrier_rows": sum(s.carrier_rows for s in shards),
        "unique_accessions": sum(len(s.accessions) for s in shards),
        "shards": len(shards),
        "shard_size": definition.shard_size,
        "planned_requests": sum(s.planned_requests for s in shards),
        "declared_retained_byte_budget": sum(s.max_retained_bytes for s in shards),
    }
    result.counts = counts
    if dry_run:
        return result

    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir
    plan_hashes: dict[str, str] = {}
    for shard in shards:
        name = shard_plan_filename(shard.shard_index)
        plan_hashes[name] = write_bytes_once(
            run_dir / name, canonical_plan_bytes(shard.payload),
            what=f"shard plan {name}",
        )

    manifest = {
        "plan_manifest_contract": PLAN_MANIFEST_CONTRACT,
        "run_id": run_id,
        "queue_id": definition.queue_id,
        "queue_definition_sha256": definition.definition_sha256,
        "carrier_provenance": {
            "carrier_run_id": definition.carrier_run_id,
            "carrier_manifest_sha256": definition.carrier_manifest_sha256,
            "freeze_record_sha256": definition.freeze_record_sha256,
        },
        "selection": {
            "stratum": definition.selection.stratum,
            "forms": list(definition.selection.forms),
            "restricted": definition.selection.restricted_accessions is not None,
            "restricted_accessions": (
                list(definition.selection.restricted_accessions)
                if definition.selection.restricted_accessions else []
            ),
        },
        "shards": [
            {
                "shard_index": s.shard_index,
                "plan_filename": shard_plan_filename(s.shard_index),
                "shard_plan_sha256": s.plan_sha256,
                "accessions": len(s.accessions),
                "carrier_rows": s.carrier_rows,
                "planned_requests": s.planned_requests,
                "max_retained_bytes": s.max_retained_bytes,
            }
            for s in shards
        ],
        "counts": counts,
        "deferred_cohorts": [dict(c) for c in definition.deferred_cohorts],
        "output_hashes": plan_hashes,
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "Plans only: this run makes no request, downloads nothing and "
            "authorizes nothing. Execution is a separate command with an "
            "operator-named shard allowlist.",
            "Shard membership is a pure function of the carrier bytes, the "
            "selection filters, the shard size and the index; complete carrier "
            "groups never straddle a shard boundary.",
            "The declared retained-byte budget is a bound, not a prediction. A "
            "shard that legitimately exceeds it fails closed and must be "
            "re-planned under a new plan hash.",
        ],
    }
    _validate(root, PLAN_MANIFEST_SCHEMA_RELATIVE_PATH, manifest, "plan manifest")
    write_bytes_once(
        run_dir / PLAN_MANIFEST_FILENAME,
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        what="queue plan manifest",
    )
    result.manifest_path = run_dir / PLAN_MANIFEST_FILENAME
    return result


# --- shard authority ---------------------------------------------------------


def manifest_pair_present(run_dir: Path) -> tuple[bool, bool]:
    """Return (both_manifest_filenames_present, receipt_present).

    This proves **presence only**, and deliberately says nothing about
    authority. Two files with the right names make a shard a *candidate*; it
    becomes authoritative only once ``_bind_shard_manifest`` binds its content
    to the regenerated shard plan. A receipt marks a handled failure and an
    interrupted shard may have none, so the receipt is diagnostic and is never
    consulted for either presence or authority.
    """
    pair_present = (
        (run_dir / BUNDLE_MANIFEST_FILENAME).is_file()
        and (run_dir / ACQUISITION_MANIFEST_FILENAME).is_file()
    )
    return pair_present, (run_dir / FAILURE_RECEIPT_FILENAME).is_file()


def find_shard_run_dirs(output_dir: Path, run_id_prefix: str) -> dict[int, Path]:
    """Map shard index to run directory for one execution run prefix."""
    found: dict[int, Path] = {}
    if not output_dir.is_dir():
        return found
    pattern = re.compile(rf"^{re.escape(run_id_prefix)}-shard-(\d{{4}})$")
    for child in sorted(output_dir.iterdir()):
        if not child.is_dir():
            continue
        match = pattern.match(child.name)
        if match:
            found[int(match.group(1))] = child
    return found


# --- stage 2: the executor ---------------------------------------------------


def run_queue_executor(
    *,
    repo_root: str | Path,
    definition_path: str | Path,
    plan_dir: str | Path,
    shard_indices: list[int],
    expected_request_count: int,
    on_shard_failure: str,
    output_dir: str | Path,
    run_id: str,
    acquire: Callable[..., PrimaryAcquisitionResult] | None = None,
    clock: Callable[[], datetime],
    **acquire_kwargs,
) -> QueueExecutionResult:
    """Execute exactly the named shards, from their persisted plan artefacts."""
    root = Path(repo_root)
    runner = acquire or run_primary_document_acquisition
    if not _RUN_ID_RE.match(run_id):
        raise AcquisitionQueueError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    if on_shard_failure not in STOP_POLICIES:
        raise AcquisitionQueueError(
            f"on_shard_failure must be one of {list(STOP_POLICIES)!r}; the stop "
            "policy is operator-declared and never defaulted."
        )
    if not shard_indices:
        raise AcquisitionQueueError(
            "An explicit shard-index allowlist is required. There is no flag "
            "that expands to the whole queue."
        )
    if len(set(shard_indices)) != len(shard_indices):
        raise AcquisitionQueueError(
            f"Duplicate shard indices in the allowlist: {shard_indices}."
        )

    definition = load_queue_definition(definition_path)
    groups = select_carrier_accessions(
        definition, root / definition.carrier_relative_path
    )
    shards = {s.shard_index: s for s in build_shard_plans(definition, groups)}
    unknown = [i for i in shard_indices if i not in shards]
    if unknown:
        raise AcquisitionQueueError(
            f"Shard indices {unknown} are outside this queue, which has "
            f"{len(shards)} shard(s) (0..{len(shards) - 1})."
        )

    requested = sum(shards[i].planned_requests for i in shard_indices)
    if expected_request_count != requested:
        raise AcquisitionQueueError(
            f"expected_request_count {expected_request_count} does not equal "
            f"the {requested} request(s) these {len(shard_indices)} shard(s) "
            "would make; the scale being authorized must be stated exactly."
        )

    plan_root = Path(plan_dir)
    out_root = Path(output_dir)
    # Preflight. Every requested shard is verified against the planner's own
    # manifest **before** a run directory exists or a transport is called, so a
    # missing, corrupt, mismatched or unenumerated plan artefact leaves nothing
    # behind. A directory holding a byte-identical plan but no valid planner
    # manifest is not a plan directory.
    plan_manifest = _load_plan_manifest(root, plan_root, definition)
    for index in sorted(shard_indices):
        _verify_persisted_plan(plan_root, shards[index], definition, plan_manifest)
    # Refuse an index that already has an authoritative run under this output
    # root: resume means naming the non-authoritative indices, never redoing
    # completed work.
    for index in sorted(shard_indices):
        for existing in _existing_shard_dirs(out_root, index):
            if not manifest_pair_present(existing)[0]:
                continue
            # A manifest pair only makes it a candidate. Binding decides
            # whether it is completed work worth protecting; a pair that fails
            # binding is corrupt evidence, not a finished shard, and must not
            # be described as one.
            _bind_shard_manifest(root, existing, shards[index])
            raise AcquisitionQueueError(
                f"Shard {index} already has a bound authoritative run at "
                f"{existing}; resume by naming only shard indices that are "
                "not authoritative."
            )

    result = QueueExecutionResult(run_id=run_id, run_dir=None)
    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir

    stopped = False
    for index in sorted(shard_indices):
        if stopped:
            result.executions.append(ShardExecution(
                shard_index=index, shard_run_id=shard_run_id(run_id, index),
                outcome=SHARD_OUTCOME_NOT_ATTEMPTED,
            ))
            continue
        shard = shards[index]
        persisted = plan_root / shard_plan_filename(index)
        child_id = shard_run_id(run_id, index)
        acquisition = runner(
            repo_root=root,
            request_plan_path=persisted,
            output_dir=out_root,
            run_id=child_id,
            clock=clock,
            **acquire_kwargs,
        )
        child_dir = Path(acquisition.run_dir) if acquisition.run_dir else None
        pair_present, receipt = (
            manifest_pair_present(child_dir) if child_dir else (False, False)
        )
        # A completed-looking child is only a candidate. It is bound here,
        # with the same check the aggregator applies, before any outcome is
        # recorded — so no execution manifest can label an unbound shard
        # authoritative.
        manifest = (
            _bind_shard_manifest(root, child_dir, shard) if pair_present else None
        )
        execution = ShardExecution(
            shard_index=index, shard_run_id=child_id,
            outcome=(SHARD_OUTCOME_AUTHORITATIVE if manifest is not None
                     else SHARD_OUTCOME_FAILED),
            run_dir=str(child_dir) if child_dir else None,
            plan_sha256=shard.plan_sha256,
            receipt_present=receipt,
        )
        if manifest is not None:
            execution.acquisition_manifest_sha256 = sha256_bytes(
                (child_dir / ACQUISITION_MANIFEST_FILENAME).read_bytes()
            )
            execution.bundle_manifest_sha256 = sha256_bytes(
                (child_dir / BUNDLE_MANIFEST_FILENAME).read_bytes()
            )
            execution.retained_bytes_total = manifest.get("retained_bytes_total")
        else:
            execution.failure_reason_code = (
                read_json(child_dir / FAILURE_RECEIPT_FILENAME).get("reason_code")
                if receipt else None
            )
            if on_shard_failure == ON_FAILURE_STOP:
                stopped = True
                result.stopped_at_shard_index = index
        result.executions.append(execution)

    counts = {
        "shards_requested": len(shard_indices),
        "shards_authoritative": sum(
            1 for e in result.executions if e.outcome == SHARD_OUTCOME_AUTHORITATIVE
        ),
        "shards_failed": sum(
            1 for e in result.executions if e.outcome == SHARD_OUTCOME_FAILED
        ),
        "shards_not_attempted": sum(
            1 for e in result.executions if e.outcome == SHARD_OUTCOME_NOT_ATTEMPTED
        ),
        "expected_request_count": expected_request_count,
        "requests_authorized": requested,
    }
    result.counts = counts
    manifest = {
        "execution_manifest_contract": EXECUTION_MANIFEST_CONTRACT,
        "run_id": run_id,
        "queue_id": definition.queue_id,
        "queue_definition_sha256": definition.definition_sha256,
        "plan_dir": str(plan_root),
        "authorized_shard_indices": sorted(shard_indices),
        "on_shard_failure": on_shard_failure,
        "stopped_at_shard_index": result.stopped_at_shard_index,
        "shards": [
            {
                "shard_index": e.shard_index,
                "shard_run_id": e.shard_run_id,
                "outcome": e.outcome,
                "run_dir": e.run_dir,
                "shard_plan_sha256": e.plan_sha256,
                "acquisition_manifest_sha256": e.acquisition_manifest_sha256,
                "bundle_manifest_sha256": e.bundle_manifest_sha256,
                "retained_bytes_total": e.retained_bytes_total,
                "failure_reason_code": e.failure_reason_code,
                "receipt_present": e.receipt_present,
            }
            for e in result.executions
        ],
        "counts": counts,
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "This manifest authorizes exactly the shard indices it lists, at "
            "the request count the operator declared. It confers nothing on "
            "any other index, on aggregation, on determination or on packets.",
            "A shard is authoritative only when its run directory holds both a "
            "bundle manifest and an acquisition manifest. A handled failure "
            "also writes a receipt; an interrupted shard may write none, and "
            "both are equally ineligible for aggregation.",
            "No aggregate is written here: aggregation is a separate command "
            "behind its own gate.",
        ],
    }
    _validate(root, EXECUTION_MANIFEST_SCHEMA_RELATIVE_PATH, manifest,
              "execution manifest")
    write_bytes_once(
        run_dir / EXECUTION_MANIFEST_FILENAME,
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        what="queue execution manifest",
    )
    result.manifest_path = run_dir / EXECUTION_MANIFEST_FILENAME
    return result


def _existing_shard_dirs(output_dir: Path, shard_index: int) -> list[Path]:
    if not output_dir.is_dir():
        return []
    suffix = f"-shard-{shard_index:04d}"
    return [c for c in sorted(output_dir.iterdir())
            if c.is_dir() and c.name.endswith(suffix)]


def _load_plan_manifest(
    root: Path, plan_dir: Path, definition: QueueDefinition
) -> dict:
    """The planner's own manifest is what makes a directory a plan directory."""
    path = plan_dir / PLAN_MANIFEST_FILENAME
    if not path.is_file():
        raise AcquisitionQueueError(
            f"No {PLAN_MANIFEST_FILENAME} in {plan_dir}. A directory holding "
            "shard plans but no planner manifest is not a plan directory, and "
            "its plans carry no authority."
        )
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcquisitionQueueError(
            f"Plan manifest {path} is not valid JSON: {exc}"
        ) from exc
    _validate(root, PLAN_MANIFEST_SCHEMA_RELATIVE_PATH, manifest, "plan manifest")
    if manifest["queue_definition_sha256"] != definition.definition_sha256:
        raise AcquisitionQueueError(
            f"Plan manifest {path} was written for queue definition "
            f"{manifest['queue_definition_sha256']!r}, not the named "
            f"{definition.definition_sha256!r}."
        )
    return manifest


def _verify_persisted_plan(
    plan_dir: Path, shard: ShardPlan, definition: QueueDefinition,
    plan_manifest: dict,
) -> None:
    """The executor runs artefacts, never arguments.

    Five bindings must hold together: the planner manifest enumerates this
    shard, names this exact filename, hashes that file, the bytes on disk hash
    to that recorded value, and the recorded plan hash equals the plan
    regenerated from the named definition.
    """
    filename = shard_plan_filename(shard.shard_index)
    entries = [
        e for e in plan_manifest["shards"]
        if e["shard_index"] == shard.shard_index
    ]
    if not entries:
        raise AcquisitionQueueError(
            f"Plan manifest does not enumerate shard {shard.shard_index}; the "
            "executor runs only shards the planner recorded."
        )
    entry = entries[0]
    if entry["plan_filename"] != filename:
        raise AcquisitionQueueError(
            f"Plan manifest records filename {entry['plan_filename']!r} for "
            f"shard {shard.shard_index}, expected {filename!r}."
        )
    recorded_hash = plan_manifest["output_hashes"].get(filename)
    if recorded_hash is None:
        raise AcquisitionQueueError(
            f"Plan manifest output_hashes does not record {filename!r}; an "
            "unhashed plan file carries no authority."
        )
    if entry["shard_plan_sha256"] != shard.plan_sha256:
        raise AcquisitionQueueError(
            f"Plan manifest records shard_plan_sha256 "
            f"{entry['shard_plan_sha256']!r} for shard {shard.shard_index}, "
            f"but the plan regenerated from the named definition hashes to "
            f"{shard.plan_sha256!r}."
        )
    persisted = plan_dir / filename
    if not persisted.is_file():
        raise AcquisitionQueueError(
            f"Shard {shard.shard_index} plan artefact not found: {persisted}. "
            "The executor runs persisted plans only."
        )
    on_disk = persisted.read_bytes()
    if sha256_bytes(on_disk) != recorded_hash:
        raise AcquisitionQueueError(
            f"Persisted plan {persisted} hashes to {sha256_bytes(on_disk)}, "
            f"but its planner manifest records {recorded_hash}. The artefact "
            "was changed after planning."
        )
    regenerated = canonical_plan_bytes(shard.payload)
    if on_disk != regenerated:
        raise AcquisitionQueueError(
            f"Persisted plan {persisted} does not match the plan regenerated "
            "from the named queue definition, byte for byte. A plan may not be "
            "edited between planning and execution."
        )
    if sha256_bytes(on_disk) != shard.plan_sha256:
        raise AcquisitionQueueError(
            f"Persisted plan {persisted} has sha256 {sha256_bytes(on_disk)}, "
            f"expected {shard.plan_sha256}."
        )
    try:
        payload = json.loads(on_disk.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AcquisitionQueueError(f"Persisted plan is not valid JSON: {exc}") from exc
    if payload.get("queue_definition_sha256") != definition.definition_sha256:
        raise AcquisitionQueueError(
            f"Persisted plan {persisted} was generated from queue definition "
            f"{payload.get('queue_definition_sha256')!r}, not the named "
            f"{definition.definition_sha256!r}."
        )
    if payload.get("shard_index") != shard.shard_index:
        raise AcquisitionQueueError(
            f"Persisted plan {persisted} declares shard_index "
            f"{payload.get('shard_index')!r}, expected {shard.shard_index}."
        )


# --- stage 3: the aggregator -------------------------------------------------


def run_queue_aggregator(
    *,
    repo_root: str | Path,
    definition_path: str | Path,
    shard_output_dir: str | Path,
    execution_run_id: str,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> QueueAggregateResult:
    """Report coverage over completed shards only."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise AcquisitionQueueError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    definition = load_queue_definition(definition_path)
    groups = select_carrier_accessions(
        definition, root / definition.carrier_relative_path
    )
    shards = build_shard_plans(definition, groups)
    found = find_shard_run_dirs(Path(shard_output_dir), execution_run_id)

    authoritative: list[dict] = []
    excluded: list[dict] = []
    for shard in shards:
        run_dir = found.get(shard.shard_index)
        if run_dir is None:
            excluded.append({
                "shard_index": shard.shard_index, "run_dir": None,
                "receipt_present": False, "reason": "no_run_directory",
                "failure_reason_code": None,
            })
            continue
        pair_present, receipt = manifest_pair_present(run_dir)
        if not pair_present:
            excluded.append({
                "shard_index": shard.shard_index, "run_dir": str(run_dir),
                "receipt_present": receipt,
                "reason": ("handled_failure" if receipt
                           else "interrupted_or_incomplete"),
                "failure_reason_code": (
                    read_json(run_dir / FAILURE_RECEIPT_FILENAME).get("reason_code")
                    if receipt else None
                ),
            })
            continue
        manifest = _bind_shard_manifest(root, run_dir, shard)
        authoritative.append({
            "shard_index": shard.shard_index,
            "run_id": run_dir.name,
            "run_dir": str(run_dir),
            "shard_plan_sha256": shard.plan_sha256,
            "acquisition_manifest_sha256": sha256_bytes(
                (run_dir / ACQUISITION_MANIFEST_FILENAME).read_bytes()
            ),
            "bundle_manifest_sha256": sha256_bytes(
                (run_dir / BUNDLE_MANIFEST_FILENAME).read_bytes()
            ),
            "accessions": len(shard.accessions),
            "carrier_rows": shard.carrier_rows,
            "bundle_entries": manifest["counts"]["bundle_entries"],
            "total_requests": manifest["counts"]["total_requests"],
            "retained_bytes_total": manifest.get("retained_bytes_total"),
        })

    counts = {
        "shards_in_queue": len(shards),
        "shards_authoritative": len(authoritative),
        "shards_not_authoritative": len(excluded),
        "accessions_covered": sum(s["accessions"] for s in authoritative),
        "carrier_rows_covered": sum(s["carrier_rows"] for s in authoritative),
        "bundle_entries": sum(s["bundle_entries"] for s in authoritative),
        "total_requests": sum(s["total_requests"] for s in authoritative),
        "retained_bytes_total": sum(
            s["retained_bytes_total"] or 0 for s in authoritative
        ),
    }
    complete = len(authoritative) == len(shards)
    manifest = {
        "aggregate_manifest_contract": AGGREGATE_MANIFEST_CONTRACT,
        "run_id": run_id,
        "queue_id": definition.queue_id,
        "queue_definition_sha256": definition.definition_sha256,
        "execution_run_id": execution_run_id,
        "coverage_complete": complete,
        "coverage_statement": (
            f"{len(authoritative)} of {len(shards)} shard(s) are authoritative."
            + ("" if complete else " Coverage is PARTIAL.")
        ),
        "shards_authoritative": authoritative,
        "shards_not_authoritative": excluded,
        "counts": counts,
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "Only shards holding both a bundle manifest and an acquisition "
            "manifest are admitted. A missing receipt is never read as "
            "success, and a present receipt is never the only failure marker.",
            "Coverage below the queue's shard count is reported as partial and "
            "never implies completeness.",
            "This aggregate hashes shard manifests; no shard manifest hashes "
            "it. The provenance graph stays directed and acyclic.",
        ],
    }
    _validate(root, AGGREGATE_MANIFEST_SCHEMA_RELATIVE_PATH, manifest,
              "aggregate manifest")
    if dry_run:
        return QueueAggregateResult(manifest=manifest, run_dir=None,
                                    manifest_path=None)
    run_dir = create_run_directory(output_dir, run_id)
    write_bytes_once(
        run_dir / AGGREGATE_MANIFEST_FILENAME,
        (json.dumps(manifest, indent=2) + "\n").encode("utf-8"),
        what="queue aggregate manifest",
    )
    # The run directory is returned alongside the manifest, never injected
    # into it: the validated payload carries only governed fields.
    return QueueAggregateResult(
        manifest=manifest, run_dir=run_dir,
        manifest_path=run_dir / AGGREGATE_MANIFEST_FILENAME,
    )


class ShardIntegrityError(AcquisitionQueueError):
    """A shard looks complete but its evidence does not bind.

    Distinct from an ordinary incomplete shard: two files with the right names
    are not authority, and a queue must not be reported merely "partial" when
    what it actually found was corrupt or mismatched evidence.
    """


def _bind_shard_manifest(root: Path, run_dir: Path, shard: ShardPlan) -> dict:
    """Admit a shard only when its manifest binds to *this* shard's plan.

    Fails closed on any mismatch. Filename presence is what makes a shard a
    candidate; content binding is what makes it authoritative.
    """
    path = run_dir / ACQUISITION_MANIFEST_FILENAME
    bundle_path = run_dir / BUNDLE_MANIFEST_FILENAME
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: {path} is not valid JSON: {exc}"
        ) from exc
    if not isinstance(manifest, dict):
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: {path} is not a JSON object."
        )
    try:
        json.loads(bundle_path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: {bundle_path} is not valid JSON: {exc}"
        ) from exc

    if manifest.get("plan_contract") != PLAN_CONTRACT_V2:
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: acquisition manifest declares "
            f"{manifest.get('plan_contract')!r}; every queue shard is planned "
            f"under {PLAN_CONTRACT_V2}."
        )
    schema = (
        ACQUISITION_V5_SCHEMA_RELATIVE_PATH
        if manifest.get("transport_kind") == TRANSPORT_KIND_SEC_LIVE
        else ACQUISITION_V4_SCHEMA_RELATIVE_PATH
    )
    errors = sorted(
        Draft202012Validator(read_json(root / schema)).iter_errors(manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: acquisition manifest violates "
            f"{schema.name}: {details}"
        )
    if manifest["plan_sha256"] != shard.plan_sha256:
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: acquisition manifest records "
            f"plan_sha256 {manifest['plan_sha256']!r}, but this shard's plan "
            f"regenerates to {shard.plan_sha256!r}. The run in this directory "
            "acquired a different plan."
        )
    counts = manifest["counts"]
    expected = {
        "planned_accessions": len(shard.accessions),
        "accessions_acquired": len(shard.accessions),
        "bundle_entries": shard.carrier_rows,
        "total_requests": shard.planned_requests,
    }
    mismatched = {
        key: (counts.get(key), value)
        for key, value in expected.items() if counts.get(key) != value
    }
    if mismatched:
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: acquisition counts do not match the "
            f"shard plan (recorded, expected): {mismatched}."
        )
    retained = manifest["retained_bytes_total"]
    if retained > shard.max_retained_bytes:
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: retained_bytes_total {retained} "
            f"exceeds the shard budget {shard.max_retained_bytes}."
        )
    recorded = manifest["output_hashes"].get(BUNDLE_MANIFEST_FILENAME)
    if recorded is None:
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: acquisition manifest output_hashes "
            f"does not record {BUNDLE_MANIFEST_FILENAME}."
        )
    actual = sha256_bytes(bundle_path.read_bytes())
    if recorded != actual:
        raise ShardIntegrityError(
            f"Shard {shard.shard_index}: bundle manifest on disk hashes to "
            f"{actual}, but the acquisition manifest records {recorded}."
        )
    return manifest


def _validate(root: Path, relative: Path, payload: dict, what: str) -> None:
    errors = sorted(
        Draft202012Validator(read_json(root / relative)).iter_errors(payload),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise AcquisitionQueueError(
            f"Queue {what} violates the canonical schema: {details}"
        )
