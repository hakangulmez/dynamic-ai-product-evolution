"""DERA FSDS release-archive acquisition (fixture-first; canary-gated live).

Governing documents:
- docs/THESIS_EXECUTION_PLAN.md (W1: DERA FSDS is validation-only)
- docs/DECISION_LOG.md ADR-081 (validation construct), ADR-082 (this design)

Acquires declared DERA Financial Statement Data Set release ZIP archives
through an injected transport callable, preserves the raw ZIP bytes
write-once with hash receipts, extracts exactly one ``sub.txt`` member per
archive reproducibly, and writes a consumer bundle that the committed
``dera-validate`` mode reads unchanged. DERA remains an independent FRAME
validation source only — never a denominator, eligibility filter, or
universe input; this runner writes only into its own run directory.

This module contains no network code. The live transport is the committed
``sec_live`` policy wrapper, built outside the universe package and injected
in with its identity as data; the fixture-replay transport defined here
serves local ZIP bytes.

Request-plan trust boundary (``dera_fsds_request_plan@0.1.0``): the plan
declares one ``url_template`` — enforced in code to be ``https://``, host
``www.sec.gov``, with exactly one ``{release}`` placeholder — and release
labels matching ``YYYYq[1-4]``. The template path is a *candidate* the
separately authorized canary verifies empirically; it is never assumed
correct, and no other URL can ever be requested. Local filenames are derived
in code, never read from the plan. ``observed_through`` and its
``observed_through_basis`` evidence field are plan-authored, copied through
verbatim to the acquisition manifest and the consumer bundle, and never
inferred by this runner.

Extraction safety: exactly one member named ``sub.txt`` is extracted. A
corrupt archive, a missing or duplicate ``sub.txt``, any member with an
absolute path, a path separator escape, or ``..``, and an uncompressed
``sub.txt`` above the code-owned 512 MB ceiling are refused before
extraction, each with a write-once failure receipt; no acquisition manifest
or bundle exists after any failure. Manifest presence is the sole mark of an
authoritative acquisition. Failures while acquiring or extracting a planned
release are receipted; a failure while persisting the final manifests
propagates and leaves no manifest — non-authoritative under the same rule.
"""

from __future__ import annotations

import io
import json
import re
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Literal, Optional

from jsonschema import Draft202012Validator
from pydantic import Field

from ..provenance import WriteOnceError, write_bytes_once
from .frame_acquisition import (
    FIXTURE_REPLAY_TRANSPORT_IDENTITY,
    IndexTransportResponse,
    TRANSPORT_KIND_SEC_LIVE,
    TransportIdentity,
)
from .freeze import create_run_directory
from .io_utils import read_json, sha256_bytes
from .models import StrictModel

DERA_PLAN_CONTRACT = "dera_fsds_request_plan@0.1.0"
SUB_MEMBER_NAME = "sub.txt"
# Code-owned ceiling on the uncompressed sub.txt member; recorded in every
# acquisition manifest. Real sub.txt files are tens of megabytes; an archive
# claiming (or delivering) more than this is refused before extraction.
MAX_SUB_UNCOMPRESSED_BYTES = 512 * 1024 * 1024

DERA_ACQUISITION_MANIFEST_FILENAME = "dera_fsds_acquisition_manifest.json"
DERA_FAILURE_RECEIPT_FILENAME = "dera_acquisition_failure_receipt.json"
CONSUMER_BUNDLE_MANIFEST_FILENAME = "fixture_manifest.json"  # consumer contract
DERA_ACQUISITION_SCHEMA_RELATIVE_PATH = Path(
    "schemas/dera_fsds_acquisition_manifest.schema.json"
)
DERA_ACQUISITION_V2_SCHEMA_RELATIVE_PATH = Path(
    "schemas/dera_fsds_acquisition_manifest.v2.schema.json"
)

_RELEASE_RE = re.compile(r"^(\d{4})q([1-4])$")
_RELEASE_TOKEN_RE = re.compile(r"\d{4}q[1-4]")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_REDIRECT_STATUSES = frozenset({301, 302, 303, 307, 308})
_MIN_RELEASE_YEAR = 2009  # first FSDS release family
_MAX_RELEASE_YEAR = 2100


class DeraPlanError(ValueError):
    """The DERA request plan is malformed or outside the enforced grammar."""


class PlannedDeraRelease(StrictModel):
    """One validated release entry with code-derived names."""

    release: str
    year: int
    quarter: int
    url: str
    zip_filename: str
    sub_filename: str


class DeraArchiveReceipt(StrictModel):
    """Write-once provenance for one acquired archive and its extraction."""

    release: str
    url: str
    zip_filename: str
    zip_sha256: str
    zip_byte_count: int
    status_code: int
    retrieved_at: datetime
    member_name: str
    member_sha256: str
    sub_filename: str
    sub_sha256: str
    sub_byte_count: int


class DeraAcquisitionFailureReceipt(StrictModel):
    """Non-authoritative record of a failed DERA acquisition run."""

    run_id: str
    request_plan_sha256: str
    transport_kind: Literal["fixture_replay", "sec_live"]
    transport_contract_hash: str
    reason_code: Literal[
        "redirect_refused",
        "terminal_url_mismatch",
        "unexpected_http_status",
        "transport_exception",
        "write_once_refused",
        "corrupt_zip",
        "missing_sub_member",
        "duplicate_sub_member",
        "unsafe_member_path",
        "member_over_ceiling",
    ]
    detail: str
    attempted_release: PlannedDeraRelease
    releases_acquired_before_failure: list[str] = Field(default_factory=list)
    failed_at: datetime


@dataclass
class DeraAcquisitionResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    request_plan_sha256: str
    entries: list[PlannedDeraRelease]
    receipts: list[DeraArchiveReceipt]
    manifest_path: Path | None = None
    bundle_manifest_path: Path | None = None
    failure: Optional[DeraAcquisitionFailureReceipt] = None
    failure_receipt_path: Path | None = None


def validate_dera_request_plan(payload: object) -> tuple[list[PlannedDeraRelease], dict]:
    """Validate the plan; derive URLs and local filenames in code.

    Returns the sorted entries plus the validated top-level fields
    (url_template, observed_through, observed_through_basis, description).
    """
    if not isinstance(payload, dict):
        raise DeraPlanError("DERA request plan must be a JSON object.")
    expected = {
        "plan_contract", "description", "url_template",
        "observed_through", "observed_through_basis", "releases",
    }
    if set(payload) != expected:
        raise DeraPlanError(
            f"DERA request plan must have exactly the keys {sorted(expected)}; "
            f"got {sorted(payload)}."
        )
    if payload["plan_contract"] != DERA_PLAN_CONTRACT:
        raise DeraPlanError(
            f"Unknown plan contract {payload['plan_contract']!r}; expected "
            f"{DERA_PLAN_CONTRACT!r}."
        )
    template = str(payload["url_template"])
    if not template.startswith("https://www.sec.gov/"):
        raise DeraPlanError(
            "url_template must be https:// on host www.sec.gov; got "
            f"{template!r}."
        )
    if (
        template.count("{release}") != 1
        or template.count("{") != 1
        or template.count("}") != 1
    ):
        raise DeraPlanError(
            "url_template must contain exactly one {release} placeholder."
        )
    try:
        # Defensive probe: any residual format-string pathology surfaces
        # here as a plan error, never as a raw ValueError mid-run.
        template.format(release="0000q1")
    except (ValueError, KeyError, IndexError) as exc:
        raise DeraPlanError(
            "url_template must contain exactly one {release} placeholder; "
            f"format probe failed: {exc}"
        ) from exc
    if any(ch.isspace() for ch in template):
        raise DeraPlanError("url_template must not contain whitespace.")
    try:
        observed_through = date.fromisoformat(str(payload["observed_through"]))
    except ValueError as exc:
        raise DeraPlanError(f"observed_through is not a date: {exc}") from exc
    basis = str(payload["observed_through_basis"]).strip()
    if not basis:
        raise DeraPlanError(
            "observed_through_basis must be a non-empty evidence statement."
        )
    raw_releases = payload["releases"]
    if not isinstance(raw_releases, list) or not raw_releases:
        raise DeraPlanError("releases must be a non-empty list.")
    entries: list[PlannedDeraRelease] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_releases):
        release = str(raw)
        match = _RELEASE_RE.match(release)
        if not match:
            raise DeraPlanError(
                f"Release {index}: {release!r} does not match YYYYq[1-4]."
            )
        year, quarter = int(match.group(1)), int(match.group(2))
        if not _MIN_RELEASE_YEAR <= year <= _MAX_RELEASE_YEAR:
            raise DeraPlanError(
                f"Release {index}: year {year} outside "
                f"[{_MIN_RELEASE_YEAR}, {_MAX_RELEASE_YEAR}]."
            )
        if release in seen:
            raise DeraPlanError(f"Duplicate release in plan: {release}.")
        seen.add(release)
        zip_filename = f"dera-{release}.zip"
        sub_filename = f"dera-{release}-sub.tsv"
        for name in (zip_filename, sub_filename):
            if "/" in name or "\\" in name or ".." in name:
                raise DeraPlanError(  # unreachable by construction; defensive
                    f"Derived filename {name!r} is unsafe."
                )
        entries.append(
            PlannedDeraRelease(
                release=release, year=year, quarter=quarter,
                url=template.format(release=release),
                zip_filename=zip_filename, sub_filename=sub_filename,
            )
        )
    fields = {
        "url_template": template,
        "observed_through": str(observed_through),
        "observed_through_basis": basis,
        "description": str(payload["description"]),
    }
    return sorted(entries, key=lambda e: (e.year, e.quarter)), fields


def load_dera_request_plan(
    path: str | Path,
) -> tuple[list[PlannedDeraRelease], dict, str]:
    plan_path = Path(path)
    if not plan_path.is_file():
        raise DeraPlanError(f"DERA request plan not found: {plan_path}")
    raw = plan_path.read_bytes()
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeraPlanError(f"DERA request plan is not valid JSON: {exc}") from exc
    entries, fields = validate_dera_request_plan(payload)
    return entries, fields, sha256_bytes(raw)


def make_dera_fixture_replay_transport(
    replay_dir: str | Path,
) -> Callable[[str], IndexTransportResponse]:
    """Deterministic replay transport serving local ZIP bytes for plan URLs.

    The release token is recovered from the URL; a URL without exactly one
    ``YYYYq[1-4]`` token, or a missing replay file, yields a 404 response,
    which the runner records as a failed acquisition.
    """
    directory = Path(replay_dir)

    def transport(url: str) -> IndexTransportResponse:
        tokens = _RELEASE_TOKEN_RE.findall(url)
        if len(tokens) != 1:
            return IndexTransportResponse(status_code=404, final_url=url, content=b"")
        path = directory / f"dera-{tokens[0]}.zip"
        if not path.is_file():
            return IndexTransportResponse(status_code=404, final_url=url, content=b"")
        return IndexTransportResponse(
            status_code=200, final_url=url, content=path.read_bytes()
        )

    return transport


def _extract_sub_member(content: bytes) -> tuple[bytes, str] | tuple[None, str]:
    """Return (extracted bytes, "") or (None, refusal reason detail).

    The reason code is encoded as ``code:detail`` in the second element when
    extraction is refused.
    """
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        return None, f"corrupt_zip:{exc}"
    with archive:
        names = archive.namelist()
        for name in names:
            if name.startswith("/") or "\\" in name or ".." in name:
                return None, f"unsafe_member_path:{name!r}"
        matches = [info for info in archive.infolist()
                   if info.filename == SUB_MEMBER_NAME]
        if not matches:
            return None, f"missing_sub_member:members={names!r}"
        if len(matches) > 1:
            return None, f"duplicate_sub_member:{len(matches)} entries"
        info = matches[0]
        if info.file_size > MAX_SUB_UNCOMPRESSED_BYTES:
            return None, (
                f"member_over_ceiling:declared {info.file_size} bytes exceeds "
                f"the {MAX_SUB_UNCOMPRESSED_BYTES}-byte ceiling"
            )
        with archive.open(info) as handle:
            # Read at most ceiling+1 bytes so a lying header cannot force an
            # unbounded read; anything beyond the ceiling is refused.
            data = handle.read(MAX_SUB_UNCOMPRESSED_BYTES + 1)
        if len(data) > MAX_SUB_UNCOMPRESSED_BYTES:
            return None, (
                f"member_over_ceiling:extracted beyond the "
                f"{MAX_SUB_UNCOMPRESSED_BYTES}-byte ceiling"
            )
    return data, ""


def run_dera_acquisition(
    *,
    repo_root: str | Path,
    request_plan_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    transport: Callable[[str], IndexTransportResponse],
    clock: Callable[[], datetime] | None = None,
    dry_run: bool = False,
    transport_identity: TransportIdentity | None = None,
) -> DeraAcquisitionResult:
    """Acquire and extract every planned release, or fail closed."""
    root = Path(repo_root)
    now = clock or (lambda: datetime.now(timezone.utc))
    identity = transport_identity or FIXTURE_REPLAY_TRANSPORT_IDENTITY
    if not _RUN_ID_RE.match(run_id):
        raise DeraPlanError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    entries, fields, plan_sha256 = load_dera_request_plan(request_plan_path)
    result = DeraAcquisitionResult(
        run_id=run_id, run_dir=None, dry_run=dry_run,
        request_plan_sha256=plan_sha256, entries=entries, receipts=[],
    )
    if dry_run:
        return result

    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir

    def fail(entry: PlannedDeraRelease, reason: str, detail: str) -> DeraAcquisitionResult:
        receipt = DeraAcquisitionFailureReceipt(
            run_id=run_id,
            request_plan_sha256=plan_sha256,
            transport_kind=identity.kind,  # type: ignore[arg-type]
            transport_contract_hash=identity.contract_hash(),
            reason_code=reason,  # type: ignore[arg-type]
            detail=detail,
            attempted_release=entry,
            releases_acquired_before_failure=[r.release for r in result.receipts],
            failed_at=now(),
        )
        payload = (
            json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True)
            + "\n"
        ).encode("utf-8")
        target = run_dir / DERA_FAILURE_RECEIPT_FILENAME
        write_bytes_once(target, payload, what="DERA acquisition failure receipt")
        result.failure = receipt
        result.failure_receipt_path = target
        return result

    output_hashes: dict[str, str] = {}
    for entry in entries:
        try:
            response = transport(entry.url)
        except Exception as exc:  # noqa: BLE001 - recorded, never swallowed
            return fail(entry, "transport_exception", f"{type(exc).__name__}: {exc}")
        if response.status_code in _REDIRECT_STATUSES:
            return fail(
                entry, "redirect_refused",
                f"redirect status {response.status_code} for {entry.url}; "
                "redirects are disabled for archive acquisition.",
            )
        if response.status_code != 200:
            return fail(
                entry, "unexpected_http_status",
                f"status {response.status_code} for {entry.url}.",
            )
        if not response.final_url or response.final_url != entry.url:
            return fail(
                entry, "terminal_url_mismatch",
                f"requested {entry.url}, response reports "
                f"{response.final_url!r}.",
            )
        try:
            zip_sha = write_bytes_once(
                run_dir / entry.zip_filename, response.content,
                what=f"raw DERA archive {entry.zip_filename}",
            )
        except WriteOnceError as exc:
            return fail(entry, "write_once_refused", str(exc))
        output_hashes[entry.zip_filename] = zip_sha

        extracted, refusal = _extract_sub_member(response.content)
        if extracted is None:
            code, _, detail = refusal.partition(":")
            return fail(entry, code, detail)
        member_sha = sha256_bytes(extracted)
        try:
            sub_sha = write_bytes_once(
                run_dir / entry.sub_filename, extracted,
                what=f"extracted SUB file {entry.sub_filename}",
            )
        except WriteOnceError as exc:
            return fail(entry, "write_once_refused", str(exc))
        output_hashes[entry.sub_filename] = sub_sha
        result.receipts.append(
            DeraArchiveReceipt(
                release=entry.release,
                url=entry.url,
                zip_filename=entry.zip_filename,
                zip_sha256=zip_sha,
                zip_byte_count=len(response.content),
                status_code=response.status_code,
                retrieved_at=now(),
                member_name=SUB_MEMBER_NAME,
                member_sha256=member_sha,
                sub_filename=entry.sub_filename,
                sub_sha256=sub_sha,
                sub_byte_count=len(extracted),
            )
        )

    # --- consumer bundle (the shape dera-validate already reads) ----------
    bundle = {
        "description": (
            "Real DERA FSDS bundle produced by acquisition run "
            f"{run_id} under {DERA_PLAN_CONTRACT}. "
            + fields["description"]
        ),
        "observed_through": fields["observed_through"],
        "observed_through_basis": fields["observed_through_basis"],
        "loaded_releases": [entry.release for entry in entries],
        "sub_files": [entry.sub_filename for entry in entries],
        "source": "dera_fsds_acquisition",
        "acquisition_run_id": run_id,
        "request_plan_sha256": plan_sha256,
    }
    bundle_payload = (
        json.dumps(bundle, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    bundle_path = run_dir / CONSUMER_BUNDLE_MANIFEST_FILENAME
    write_bytes_once(bundle_path, bundle_payload, what="DERA consumer bundle manifest")
    output_hashes[CONSUMER_BUNDLE_MANIFEST_FILENAME] = sha256_bytes(bundle_payload)
    result.bundle_manifest_path = bundle_path

    manifest = build_dera_acquisition_manifest(
        repo_root=root,
        run_id=run_id,
        request_plan_sha256=plan_sha256,
        fields=fields,
        receipts=result.receipts,
        output_hashes=output_hashes,
        run_timestamp=now(),
        transport_identity=identity,
    )
    manifest_payload = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    manifest_path = run_dir / DERA_ACQUISITION_MANIFEST_FILENAME
    write_bytes_once(manifest_path, manifest_payload, what="DERA acquisition manifest")
    result.manifest_path = manifest_path
    return result


def build_dera_acquisition_manifest(
    *,
    repo_root: str | Path,
    run_id: str,
    request_plan_sha256: str,
    fields: dict,
    receipts: list[DeraArchiveReceipt],
    output_hashes: dict[str, str],
    run_timestamp: datetime,
    transport_identity: TransportIdentity,
) -> dict:
    """Assemble and schema-validate the acquisition manifest (v0.1 or v0.2)."""
    root = Path(repo_root)
    schema_versions = read_json(root / "schemas" / "schema_version_manifest.json")[
        "schemas"
    ]
    live = transport_identity.kind == TRANSPORT_KIND_SEC_LIVE
    manifest: dict = {
        "run_id": run_id,
        "request_plan_sha256": request_plan_sha256,
        "url_template": fields["url_template"],
        "observed_through": fields["observed_through"],
        "observed_through_basis": fields["observed_through_basis"],
        "transport_kind": transport_identity.kind,
        "transport_contract_hash": transport_identity.contract_hash(),
        "max_sub_uncompressed_bytes": MAX_SUB_UNCOMPRESSED_BYTES,
        "archives": [receipt.model_dump(mode="json") for receipt in receipts],
        "counts": {
            "planned_releases": len(receipts),
            "archives_acquired": len(receipts),
            "members_extracted": len(receipts),
        },
        "output_hashes": output_hashes,
        "run_timestamp": run_timestamp.isoformat(),
        "limitations": [
            "DERA FSDS is an independent FRAME validation source only; this "
            "acquisition never feeds the frame, eligibility, or the universe.",
            "observed_through and its basis are plan-authored evidence, "
            "copied verbatim; the runner never infers coverage.",
            "This manifest does not authorize validation of any FRAME run "
            "by itself; the dera-validate gate governs that separately "
            "(ADR-081).",
        ],
    }
    if live:
        manifest["transport_contract"] = dict(transport_identity.contract)
        manifest["schema_versions"] = {
            "dera_fsds_acquisition_manifest_v2": schema_versions[
                "dera_fsds_acquisition_manifest_v2"
            ]
        }
        schema_path = DERA_ACQUISITION_V2_SCHEMA_RELATIVE_PATH
    else:
        manifest["schema_versions"] = {
            "dera_fsds_acquisition_manifest": schema_versions[
                "dera_fsds_acquisition_manifest"
            ]
        }
        manifest["limitations"].insert(
            0,
            "Fixture-replay acquisition: bytes were served from local "
            "fixture archives; no network request was made.",
        )
        schema_path = DERA_ACQUISITION_SCHEMA_RELATIVE_PATH
    schema = read_json(root / schema_path)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(manifest), key=lambda e: e.json_path)
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"DERA acquisition manifest violates the canonical schema: {details}"
        )
    return manifest
