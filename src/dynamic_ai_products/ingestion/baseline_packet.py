"""Stage 00C baseline evidence packets from local primary documents (W2-C-beta).

Governing documents:
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md (Stage 00C baseline packets)
- docs/DECISION_LOG.md ADR-088 (baseline carrier), ADR-089 (bounded document
  acquisition), ADR-090 (filing-index route probe), ADR-091 (this design)

Builds compact, provenance-preserving packets from primary annual-report
documents that are **already on disk and hash-verified**. This module lives in
``ingestion`` because it needs ``normalize``'s span and passage machinery,
while the packet contracts live in ``universe``: the dependency runs one way,
``ingestion`` -> ``universe``, and this module inherits ingestion's
AST-enforced no-network, no-URL-literal guards. It therefore *cannot* fetch a
document; acquisition, its request plan, and its canary are separate later
increments.

**What a v0.1 packet contains.** The full normalized Item 1 span, every
passage classified ``ITEM1_OVERVIEW``, plus explicit missingness for
everything else. ``COVER_PAGE`` is recorded missing and all five issuer flags
are ``unknown`` cohort-wide: the two-hop route never retrieves the SGML header
that carried SIC, state of incorporation and fiscal year end, and no
inline-XBRL cover-fact parser exists. Silence is not evidence, so a flag is
``true``/``false`` only from a directly observed source fact and otherwise
stays ``unknown``. ``PRODUCTS_SERVICES``, ``CUSTOMERS``,
``SEGMENTS_MATERIALITY`` and ``TECHNOLOGY_DELIVERY`` are recorded missing
rather than inferred: deterministic subsection tagging has not been measured,
and a later increment may add it.

**Evidence separation.** A packet cites two different things and never
conflates them. ``route_validation`` records that a filing-index probe proved
the URL route — for its own three accessions, not for this firm.
``selection_provenance`` records, per document, the filing-index response
hash, the selected document, and the primary URL that produced *these* bytes.

**Failure semantics.** Input-integrity problems refuse the whole run: a hash
mismatch, a bundle entry missing provenance, an out-of-scope form. Evidentiary
problems for one firm are recorded as a packet failure and never as an
exclusion — a missing Item 1, an ambiguous end boundary, no trustworthy end
boundary, or a filing dated after the baseline cutoff.

Scope is the domestic ``10-K``/``10-KT`` path. The FPI extension cohort
(``20-F``/``40-F``) is preserved by the frame and carrier and is neither
handled nor excluded here.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from hashlib import sha256
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator

from ..provenance import write_bytes_once
from ..universe.freeze import create_run_directory
from ..universe.identifiers import (
    IdentifierError,
    company_id_for_cik,
    normalize_accession,
    normalize_cik,
)
from ..universe.io_utils import read_json
from ..universe.models import (
    IssuerStatusFlags,
    PacketBuildFailure,
    SourcePassage,
    UniverseBaselinePacket,
)
from ..universe.taxonomy import PACKET_SECTIONS
from .errors import IngestionError
from .normalize import (
    build_passages_v4,
    find_item_one_span_text,
    find_item_one_span_v2,
)

BUNDLE_CONTRACT = "baseline_primary_document_bundle@0.1.0"
PACKET_CONTRACT = "universe_baseline_packet@0.1.0"
#: ADR-097 successors, emitted only for a v0.2 bundle. An all-HTML bundle
#: still produces exactly the v0.1 artefacts it produces today.
BUNDLE_CONTRACT_V2 = "baseline_primary_document_bundle@0.2.0"
PACKET_CONTRACT_V2 = "universe_baseline_packet@0.2.0"
REPRESENTATION_HTML = "html"
REPRESENTATION_PLAIN_TEXT = "plain_text"
ADMISSION_EVIDENCE_FIELDS = (
    "admission", "document_blocks", "declared_type", "declared_filename",
)
BUNDLE_MANIFEST_FILENAME = "bundle_manifest.json"
PACKET_MANIFEST_FILENAME = "baseline_packet_manifest.json"
PACKETS_FILENAME = "universe_baseline_packets.jsonl"
FAILURES_FILENAME = "baseline_packet_failures.jsonl"

BUNDLE_SCHEMA_RELATIVE_PATH = Path(
    "schemas/baseline_primary_document_bundle.schema.json"
)
PACKET_SCHEMA_RELATIVE_PATH = Path("schemas/universe_baseline_packet.schema.json")
BUNDLE_V2_SCHEMA_RELATIVE_PATH = Path(
    "schemas/baseline_primary_document_bundle.v2.schema.json"
)
PACKET_V2_SCHEMA_RELATIVE_PATH = Path(
    "schemas/universe_baseline_packet.v2.schema.json"
)
PACKET_MANIFEST_V2_SCHEMA_RELATIVE_PATH = Path(
    "schemas/baseline_packet_manifest.v2.schema.json"
)
PACKET_MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/baseline_packet_manifest.schema.json"
)

ADMITTED_FORMS = ("10-K", "10-KT")
ITEM_ONE_SECTION = "ITEM1_OVERVIEW"
COVER_PAGE_SECTION = "COVER_PAGE"
#: Recorded on every packet: no cover-page evidence is observable on this
#: route, so no issuer flag may be asserted either way.
ISSUER_STATUS_BASIS = "cover_page_evidence_not_yet_observed"
#: Deferred until a measured increment; never inferred from Item 1 prose.
DEFERRED_SECTIONS = (
    "PRODUCTS_SERVICES",
    "CUSTOMERS",
    "SEGMENTS_MATERIALITY",
    "TECHNOLOGY_DELIVERY",
)

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class PacketBundleError(ValueError):
    """The bundle, its manifest, or an entry is unusable. The run refuses."""


#: Path segments a bundle filename may never contain or equal. A bundle names
#: files *inside* its own directory; anything that could address another
#: location is refused before the filesystem is touched.
_UNSAFE_NAME_SEGMENTS = ("/", "\\", "\x00")
_UNSAFE_NAME_EXACT = (".", "..")


def require_safe_leaf_name(value: object, *, where: str, field: str) -> str:
    """Return ``value`` if it is a safe leaf filename, else refuse.

    Checked before any file is opened: a bundle entry may only name a file in
    the bundle directory itself, so an absolute path, any separator, a dot
    segment, or a traversal component is refused rather than resolved.
    """
    if not isinstance(value, str) or not value.strip():
        raise PacketBundleError(
            f"{where}: {field} must be a non-empty filename."
        )
    name = value
    if name != name.strip():
        raise PacketBundleError(
            f"{where}: {field} {name!r} carries leading or trailing whitespace."
        )
    if name in _UNSAFE_NAME_EXACT:
        raise PacketBundleError(f"{where}: {field} {name!r} is a dot segment.")
    for segment in _UNSAFE_NAME_SEGMENTS:
        if segment in name:
            raise PacketBundleError(
                f"{where}: {field} {name!r} contains {segment!r}; a bundle "
                "entry names a file inside the bundle directory only."
            )
    if name.startswith("~") or ":" in name:
        raise PacketBundleError(
            f"{where}: {field} {name!r} is not a plain leaf filename."
        )
    return name


def source_id_for(cik: str, accession: str, selected_document: str) -> str:
    """The stable identity of one primary document.

    Deliberately independent of the document's bytes: a re-download of
    identical content, or an unrelated edit elsewhere in the document, must
    not change passage identity. The raw hash travels separately on the
    packet as ``source_sha256``.
    """
    return f"sec-primary:{cik}:{accession}:{selected_document}"


#: Fields omitted from the serialization each self-referential value covers.
_HASH_OMITS = ("packet_sha256",)
_SIZE_OMITS = ("packet_sha256", "packet_byte_size")


def canonical_packet_bytes(payload: dict, *, omit=_HASH_OMITS) -> bytes:
    """Canonical serialization of a packet record.

    ``packet_sha256`` covers this serialization with the hash field itself
    omitted — it cannot cover its own value — and ``packet_byte_size``
    measures the serialization with *both* self-referential fields omitted,
    so neither definition is circular. Key order is fixed, so two equal
    packets always serialize, size and hash identically.
    """
    material = {k: v for k, v in payload.items() if k not in omit}
    return json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


@dataclass
class PacketRunResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    bundle_manifest_sha256: str
    planned: int
    packets: list[UniverseBaselinePacket] = field(default_factory=list)
    failures: list[PacketBuildFailure] = field(default_factory=list)
    manifest_path: Path | None = None
    counts: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)


def load_bundle(repo_root: Path, bundle_dir: Path) -> tuple[dict, list[dict], str]:
    """Schema-validate the bundle manifest and verify every document.

    Verification is fail-closed and repairs nothing: filenames must be safe
    leaf names (checked before the filesystem is touched), and every
    document's byte length *and* SHA-256 must equal what the bundle declares.
    A declared value is never replaced by an observed one.
    """
    if not bundle_dir.is_dir():
        raise PacketBundleError(f"Bundle directory not found: {bundle_dir}")
    manifest_path = bundle_dir / BUNDLE_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise PacketBundleError(
            f"Bundle is missing {BUNDLE_MANIFEST_FILENAME}: {bundle_dir}"
        )
    raw = manifest_path.read_bytes()
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketBundleError(f"Bundle manifest is not valid JSON: {exc}") from exc
    declared = manifest.get("bundle_contract")
    if declared not in (BUNDLE_CONTRACT, BUNDLE_CONTRACT_V2):
        raise PacketBundleError(
            f"Bundle must declare one of "
            f"{[BUNDLE_CONTRACT, BUNDLE_CONTRACT_V2]!r}."
        )
    schema_path = (
        BUNDLE_V2_SCHEMA_RELATIVE_PATH if declared == BUNDLE_CONTRACT_V2
        else BUNDLE_SCHEMA_RELATIVE_PATH
    )
    schema = read_json(repo_root / schema_path)
    errors = sorted(
        Draft202012Validator(schema).iter_errors(manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise PacketBundleError(
            f"Bundle manifest violates {schema_path.name}: {details}"
        )

    entries: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for index, entry in enumerate(manifest["documents"]):
        where = f"documents[{index}]"
        if entry["form"] not in ADMITTED_FORMS:
            raise PacketBundleError(
                f"{where}: form {entry['form']!r} is outside the domestic "
                f"annual forms {list(ADMITTED_FORMS)}. The FPI extension "
                "cohort is preserved by the frame and carrier, and is neither "
                "handled nor excluded here."
            )
        try:
            cik = normalize_cik(entry["cik"])
            accession = normalize_accession(entry["accession"])
        except IdentifierError as exc:
            raise PacketBundleError(f"{where}: {exc}") from exc
        key = (cik, accession)
        if key in seen:
            raise PacketBundleError(f"{where}: duplicate document {key}.")
        seen.add(key)

        # Name safety first: nothing outside the bundle directory may be
        # addressed, so this runs before any path is built or opened.
        local_filename = require_safe_leaf_name(
            entry["local_filename"], where=where, field="local_filename"
        )
        # Kept distinct from local_filename: the document SEC selected and the
        # file this bundle stores it as are separate facts, and equality is
        # never required.
        require_safe_leaf_name(
            entry["selected_document"], where=where, field="selected_document"
        )

        document_path = bundle_dir / local_filename
        if not document_path.is_file():
            raise PacketBundleError(f"{where}: document missing: {document_path}")
        raw_bytes = document_path.read_bytes()
        # Both declared facts are verified, and neither is ever repaired from
        # what was observed: a declared length that disagrees with the bytes is
        # a broken bundle even when the hash matches.
        if len(raw_bytes) != entry["source_byte_length"]:
            raise PacketBundleError(
                f"{where}: document byte-length mismatch for {local_filename}: "
                f"bundle {entry['source_byte_length']}, observed "
                f"{len(raw_bytes)}. Refusing to build."
            )
        observed = sha256(raw_bytes).hexdigest()
        if observed != entry["source_sha256"]:
            raise PacketBundleError(
                f"{where}: document hash mismatch for {local_filename}: "
                f"bundle {entry['source_sha256']}, observed {observed}. "
                "Refusing to build."
            )
        entries.append({**entry, "cik": cik, "accession": accession,
                        "local_filename": local_filename,
                        "path": document_path})
    return manifest, entries, sha256(raw).hexdigest()


def build_packet(
    entry: dict,
    *,
    baseline_cutoff: date,
    baseline_cutoff_source: dict,
    route_validation: dict,
    packet_contract: str = PACKET_CONTRACT,
    locate_html: Callable[[bytes], tuple[int, int, str]] = find_item_one_span_v2,
) -> UniverseBaselinePacket | PacketBuildFailure:
    """Build one packet, or return the recorded reason it could not be built."""
    cik, accession = entry["cik"], entry["accession"]
    source_id = source_id_for(cik, accession, entry["selected_document"])
    company_id = company_id_for_cik(cik)

    def failure(reason: str, detail: str) -> PacketBuildFailure:
        return PacketBuildFailure(
            cik=cik, company_id=company_id, accession=accession,
            form=entry["form"], source_id=source_id,
            reason_code=reason, detail=detail,
        )

    filing_date = date.fromisoformat(entry["baseline_filing_date"])
    if filing_date > baseline_cutoff:
        return failure(
            "temporal_mismatch",
            f"baseline filing date {filing_date} is after the baseline cutoff "
            f"{baseline_cutoff}; post-cutoff evidence may not support a "
            "baseline observation.",
        )

    raw = entry["path"].read_bytes()
    # ADR-097: the representation and its admission evidence are read from the
    # governed bundle, never re-derived here. This module deliberately does
    # not import the acquisition-side admission code: re-deciding admission
    # from the bytes would make the packet a second, drifting record of why a
    # text source was accepted.
    representation = entry.get("representation", REPRESENTATION_HTML)
    text_structure = (
        {field: entry.get(field) for field in ADMISSION_EVIDENCE_FIELDS}
        if representation == REPRESENTATION_PLAIN_TEXT else None
    )
    # The text route is locator-selector independent (ADR-104): only the
    # HTML locator is parameterized, and its default is the committed v2, so
    # the single-bundle path is unchanged.
    locate = (
        find_item_one_span_text
        if representation == REPRESENTATION_PLAIN_TEXT
        else locate_html
    )
    try:
        start, end, boundary_kind = locate(raw)
    except IngestionError as exc:
        mapping = {
            "item_span_not_found": "missing_item_one",
            "ambiguous_end_boundary": "ambiguous_end_boundary",
            "no_end_boundary": "no_end_boundary",
        }
        return failure(mapping.get(exc.reason_code, exc.reason_code), str(exc))

    raw_passages, ledger = build_passages_v4(
        raw, source_id=source_id, start_offset=start, end_offset=end
    )
    if not raw_passages:
        return failure(
            "empty_item_one_span",
            f"the located Item 1 span ({start}..{end}) normalized to no "
            "passages.",
        )
    passages = [
        SourcePassage(
            passage_id=item["passage_id"],
            source_id=item["source_id"],
            section=ITEM_ONE_SECTION,
            text=item["text"],
            text_hash=item["text_hash"],
            byte_start=item["start_offset"],
            byte_end=item["end_offset"],
            normalizer_version=item["normalizer_version"],
        )
        for item in raw_passages
    ]
    # Cover page is unobservable on this route, and the four economic
    # subsections are deferred rather than inferred: everything except Item 1
    # is explicitly missing.
    missing = sorted(set(PACKET_SECTIONS) - {ITEM_ONE_SECTION})
    payload = {
        "packet_contract": packet_contract,
        "cik": cik,
        "company_id": company_id,
        "stratum": entry["stratum"],
        "accession": accession,
        "form": entry["form"],
        "baseline_filing_date": str(filing_date),
        "baseline_cutoff": str(baseline_cutoff),
        "baseline_cutoff_source": baseline_cutoff_source,
        "source_id": source_id,
        "source_sha256": entry["source_sha256"],
        "source_byte_length": len(raw),
        "selection_provenance": {
            "filing_index_url": entry["filing_index_url"],
            "filing_index_response_sha256": entry["filing_index_response_sha256"],
            "selected_document": entry["selected_document"],
            "primary_url": entry["primary_url"],
        },
        "route_validation": dict(route_validation),
        "item_one_start": start,
        "item_one_end": end,
        "end_boundary_kind": boundary_kind,
        "passages": [p.model_dump(mode="json") for p in passages],
        "issuer_status_flags": IssuerStatusFlags().model_dump(mode="json"),
        "issuer_status_basis": ISSUER_STATUS_BASIS,
        "missing_sections": missing,
        "parse_status": "complete",
        "normalization_ledger": ledger,
        "packet_byte_size": 0,
        "packet_sha256": "",
    }
    if packet_contract == PACKET_CONTRACT_V2:
        # Only a v0.2 packet carries these. A v0.1 packet must stay
        # byte-identical to what it has always been, and packet_byte_size and
        # packet_sha256 cover the payload, so adding a field to every packet
        # would silently rewrite every historical hash.
        payload["representation"] = representation
        payload["text_structure"] = text_structure
    payload["packet_byte_size"] = len(
        canonical_packet_bytes(payload, omit=_SIZE_OMITS)
    )
    payload["packet_sha256"] = sha256(canonical_packet_bytes(payload)).hexdigest()
    return UniverseBaselinePacket.model_validate(payload)


def run_baseline_packet_build(
    *,
    repo_root: str | Path,
    bundle_dir: str | Path,
    project_config_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> PacketRunResult:
    """Build every packet the bundle plans, or refuse the run.

    ``clock`` is required and injected: this package never reads the clock
    itself (tests/ingestion/test_ingestion_boundaries.py), so the run
    timestamp is supplied by the caller that owns identity.
    """
    root = Path(repo_root)
    now = clock
    if not _RUN_ID_RE.match(run_id):
        raise PacketBundleError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    manifest, entries, bundle_sha = load_bundle(root, Path(bundle_dir))
    # The packet generation follows the bundle's, not any single document's:
    # a v0.2 bundle may carry html rows too, and they are v0.2 packets whose
    # text_structure is null.
    textual_bundle = manifest["bundle_contract"] == BUNDLE_CONTRACT_V2
    packet_contract = PACKET_CONTRACT_V2 if textual_bundle else PACKET_CONTRACT

    config_path = Path(project_config_path)
    if not config_path.is_file():
        raise PacketBundleError(f"Project config not found: {config_path}")
    import yaml

    universe_config = (
        yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    ).get("universe") or {}
    raw_cutoff = universe_config.get("baseline_cutoff")
    if raw_cutoff is None:
        raise PacketBundleError(
            "Project config carries no universe.baseline_cutoff; the cutoff is "
            "the W0-frozen value, never a parameter."
        )
    cutoff = raw_cutoff if isinstance(raw_cutoff, date) else date.fromisoformat(
        str(raw_cutoff)
    )
    cutoff_source = {
        "path": "configs/project.yaml",
        "key": "universe.baseline_cutoff",
        "project_config_sha256": sha256(config_path.read_bytes()).hexdigest(),
    }
    route_validation = dict(manifest["route_validation"])

    result = PacketRunResult(
        run_id=run_id, run_dir=None, dry_run=dry_run,
        bundle_manifest_sha256=bundle_sha, planned=len(entries),
    )
    for entry in entries:
        built = build_packet(
            entry,
            baseline_cutoff=cutoff,
            baseline_cutoff_source=cutoff_source,
            route_validation=route_validation,
            packet_contract=packet_contract,
        )
        if isinstance(built, UniverseBaselinePacket):
            result.packets.append(built)
        else:
            result.failures.append(built)

    boundary_counts: dict[str, int] = {}
    for packet in result.packets:
        boundary_counts[packet.end_boundary_kind] = (
            boundary_counts.get(packet.end_boundary_kind, 0) + 1
        )
    failure_counts: dict[str, int] = {}
    for failed in result.failures:
        failure_counts[failed.reason_code] = (
            failure_counts.get(failed.reason_code, 0) + 1
        )
    sizes = [p.packet_byte_size for p in result.packets]
    counts = {
        "planned_documents": len(entries),
        "packets_built": len(result.packets),
        "packet_failures": len(result.failures),
        "firms_excluded": 0,
        "packets_by_end_boundary": boundary_counts,
        "failures_by_reason": failure_counts,
        "passages_total": sum(len(p.passages) for p in result.packets),
        "packet_bytes_total": sum(sizes),
        "packet_bytes_max": max(sizes) if sizes else 0,
        "packet_bytes_mean": (sum(sizes) // len(sizes)) if sizes else 0,
    }
    reconciliation = {
        "planned = packets + failures": (
            counts["planned_documents"]
            == counts["packets_built"] + counts["packet_failures"]
        ),
        "no firm was excluded": counts["firms_excluded"] == 0,
        "every passage lies inside its Item 1 span": all(
            packet.item_one_start <= passage.byte_start
            and passage.byte_end <= packet.item_one_end
            for packet in result.packets
            for passage in packet.passages
        ),
        "every packet conserves its normalized bytes": all(
            packet.normalization_ledger["input_byte_count"]
            == packet.normalization_ledger["normalized_byte_count"]
            + packet.normalization_ledger["dropped_byte_count"]
            for packet in result.packets
        ),
        "cover page and the deferred sections are explicitly missing": all(
            COVER_PAGE_SECTION in packet.missing_sections
            and all(s in packet.missing_sections for s in DEFERRED_SECTIONS)
            for packet in result.packets
        ),
        "no issuer flag is asserted without cover-page evidence": all(
            packet.issuer_status_flags.model_dump() == {
                "investment_company": None,
                "asset_backed_issuer": None,
                "non_operating_trust": None,
                "shell_company": None,
                "blank_check_precombination": None,
            }
            for packet in result.packets
        ),
        "boundary counts sum to packets built": (
            sum(boundary_counts.values()) == counts["packets_built"]
        ),
    }
    result.counts, result.reconciliation = counts, reconciliation
    failed = sorted(name for name, ok in reconciliation.items() if not ok)
    if failed:
        raise PacketBundleError(
            f"Packet reconciliation failed: {'; '.join(failed)}. Nothing was "
            "written."
        )
    if dry_run:
        return result

    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir
    packets_payload = (
        "\n".join(
            json.dumps(p.model_dump(mode="json"), sort_keys=True)
            for p in result.packets
        )
        + ("\n" if result.packets else "")
    ).encode("utf-8")
    failures_payload = (
        "\n".join(
            json.dumps(f.model_dump(mode="json"), sort_keys=True)
            for f in result.failures
        )
        + ("\n" if result.failures else "")
    ).encode("utf-8")
    write_bytes_once(run_dir / PACKETS_FILENAME, packets_payload,
                     what="baseline packets")
    write_bytes_once(run_dir / FAILURES_FILENAME, failures_payload,
                     what="baseline packet failures")

    schema_versions = read_json(
        root / "schemas" / "schema_version_manifest.json"
    )["schemas"]
    run_manifest = {
        "run_id": run_id,
        "bundle_contract": manifest["bundle_contract"],
        "bundle_manifest_sha256": bundle_sha,
        "bundle_provenance": dict(manifest["provenance"]),
        "route_validation": route_validation,
        "baseline_cutoff": str(cutoff),
        "baseline_cutoff_source": cutoff_source,
        "counts": counts,
        "reconciliation": reconciliation,
        "output_hashes": {
            PACKETS_FILENAME: sha256(packets_payload).hexdigest(),
            FAILURES_FILENAME: sha256(failures_payload).hexdigest(),
        },
        "run_timestamp": now().isoformat(),
        "schema_versions": (
            {
                "universe_baseline_packet_v2": schema_versions[
                    "universe_baseline_packet_v2"
                ],
                "baseline_packet_manifest_v2": schema_versions[
                    "baseline_packet_manifest_v2"
                ],
            } if textual_bundle else {
                "universe_baseline_packet": schema_versions[
                    "universe_baseline_packet"
                ],
                "baseline_packet_manifest": schema_versions[
                    "baseline_packet_manifest"
                ],
                "baseline_primary_document_bundle": schema_versions[
                    "baseline_primary_document_bundle"
                ],
            }
        ),
        "limitations": [
            "Fixture-first: packets are built only from locally supplied, "
            "hash-verified primary documents. This module performs no network "
            "access; acquisition and its canary are separate increments.",
            "COVER_PAGE is explicitly missing and all five issuer flags are "
            "unknown cohort-wide: this route retrieves no SGML header and no "
            "inline-XBRL cover-fact parser exists. Silence is never evidence.",
            "PRODUCTS_SERVICES, CUSTOMERS, SEGMENTS_MATERIALITY and "
            "TECHNOLOGY_DELIVERY are recorded missing, never inferred; "
            "deterministic subsection tagging is a later measured increment.",
            "route_validation proves a URL route for the probe's own "
            "accessions; per-document selection evidence is "
            "selection_provenance, and the two are never interchangeable.",
            "Domestic 10-K/10-KT only. The FPI extension cohort is preserved "
            "by the frame and carrier, and is neither handled nor excluded.",
            "No issuer filtering, screening, classification, tier derivation "
            "or PCT extraction is performed, and no model is called.",
            "Packet sizes are recorded, not capped: the raw-document "
            "acquisition ceiling remains the only size bound.",
        ],
    }
    schema = read_json(root / (
        PACKET_MANIFEST_V2_SCHEMA_RELATIVE_PATH if textual_bundle
        else PACKET_MANIFEST_SCHEMA_RELATIVE_PATH
    ))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(run_manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"Baseline packet manifest violates the canonical schema: {details}"
        )
    payload = (json.dumps(run_manifest, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    write_bytes_once(run_dir / PACKET_MANIFEST_FILENAME, payload,
                     what="baseline packet manifest")
    result.manifest_path = run_dir / PACKET_MANIFEST_FILENAME
    return result


def packet_schema_path_for(packet: dict) -> Path:
    """Which packet generation validates this record."""
    return (
        PACKET_V2_SCHEMA_RELATIVE_PATH
        if packet.get("packet_contract") == PACKET_CONTRACT_V2
        else PACKET_SCHEMA_RELATIVE_PATH
    )


def validate_packet_against_schema(repo_root: str | Path, packet: dict) -> None:
    """Raise if a packet record violates its canonical schema."""
    schema = read_json(Path(repo_root) / packet_schema_path_for(packet))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(packet),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(f"Packet violates the canonical schema: {details}")


def recompute_packet_sha256(packet: dict) -> str:
    """Recompute a packet's self-excluding hash from its own record."""
    return sha256(canonical_packet_bytes(packet)).hexdigest()


def packet_sections_present(packet: dict) -> set[str]:
    return {p["section"] for p in packet["passages"]}
