"""Stage 00B-S deterministic shell-company determination (fixture-first).

Governing documents:
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md (Stage 00B deterministic issuer
  exclusions)
- docs/DECISION_LOG.md ADR-091 (baseline packet contracts), ADR-092 (two-hop
  primary-document acquisition), ADR-094 (this design)

Reads exactly one cover-page fact — ``dei:EntityShellCompany`` — from primary
annual-report documents that are already local and hash-verified, and emits
one governed determination per carrier row. It consumes the committed
``baseline_primary_document_bundle@0.1.0`` unchanged: no new acquisition
format, no fetch, no network. This module lives in ``ingestion`` because it
parses document bytes, and inherits that package's AST-enforced no-network and
no-URL-literal guards.

**Exactly one fact.** ``shell_company`` is the only output. The four other
Stage 00B flags are neither read, set, inferred, nor represented here, and
``issuer_filters`` is not imported: its five-flag contract is untouched. A
liquidating trust that declares shell=false says nothing about
``non_operating_trust``, and this module makes no such claim.

**What each outcome means.** ``true`` is a deterministic hard-exclusion
determination carrying dated evidence. ``false`` means the firm is
**retained** and asserts nothing about software, product, or general
eligibility. ``unknown`` is likewise retained. Nothing is ever excluded on
absent or ambiguous evidence.

**Boolean evaluation is a transform-application contract.** The declared
transform alone does not decide the value: one measured filing yields both
outcomes under ``ixt-sec:boolballotbox`` — ``dei:DocumentAnnualReport`` with
U+2612 is true while ``dei:EntityShellCompany`` with U+2610 is false in the
same document. Decoded content is therefore evaluated *under* its transform.
``ixt-sec:boolballotbox`` is the **only** content-dependent transform. The
four fixed and boolean transforms are content-**independent**: the XBRL
Transformation Registry defines their output, so ``ixt:booleanfalse`` and
``ixt:fixed-false`` yield false and ``ixt:booleantrue`` and ``ixt:fixed-true``
yield true, each regardless of what the element renders. A checkbox glyph is
never consulted for them, in either direction — a ``fixed-true`` element
rendering U+2610 is still true, exactly as a ``fixed-false`` element rendering
U+2612 is still false. ``ixt:booleantrue`` and ``ixt:fixed-true`` were added
in v0.2 after three real filings declared them; the registry, not the
observation, is the authority for what they mean. Any other transform stays
unsupported and yields ``unknown``.

**Context resolution.** Every fact is resolved through its ``contextRef``. The
context identifier scheme must be exactly the SEC CIK scheme, and an
unmembered context binds only when its identifier equals the carrier row's
CIK. A context carrying a ``dei:LegalEntityAxis`` member is **unassignable**
unless the filing itself maps that member to the row CIK — measured evidence:
a real combined filing carries three shell facts whose contexts all bear the
*parent's* CIK and distinguish registrants only by filer-defined ``sr:``
member tokens, which carry no CIK. A member token is never mapped by name
resemblance.

**Fail-closed multiplicity.** Missing, malformed, unsupported, conflicting,
unassignable, or more than one assignable fact all yield ``unknown``. In v0.1
even *agreeing* duplicate assignable facts yield ``unknown`` rather than being
silently collapsed: agreement is not evidence that the duplication was
intended.

Byte ranges are half-open ``[fact_byte_start, fact_byte_end)`` and
``fact_element_sha256`` covers exactly ``raw[start:end]`` — the complete raw
``ix:nonNumeric`` element, unnormalized and undecoded.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from html import unescape
from pathlib import Path
from typing import Callable, Optional

from jsonschema import Draft202012Validator

from ..provenance import write_bytes_once
from ..universe.freeze import create_run_directory
from ..universe.identifiers import (
    SEC_CIK_IDENTIFIER_SCHEME,
    company_id_for_cik,
)
from ..universe.io_utils import read_json
from .baseline_packet import PacketBundleError, load_bundle
from .lineage_authority import (
    LineageAuthorityError,
    load_lineage_bundles as _load_lineage_bundles,
)

DETERMINATION_CONTRACT = "shell_company_determination@0.2.0"
DETERMINATIONS_FILENAME = "shell_company_determinations.jsonl"
MANIFEST_FILENAME = "shell_company_determination_manifest.json"
#: v0.1 schemas, retained unchanged. They remain the only validators for
#: artefacts written under ``shell_company_determination@0.1.0``; this module
#: no longer writes that contract and never validates against them.
DETERMINATION_V1_SCHEMA_RELATIVE_PATH = Path(
    "schemas/shell_company_determination.schema.json"
)
MANIFEST_V1_SCHEMA_RELATIVE_PATH = Path(
    "schemas/shell_company_determination_manifest.schema.json"
)
#: v0.2 successors, which this module writes and validates against. A v0.1
#: artefact is rejected here, and a v0.2 artefact is rejected by v0.1: the
#: ``determination_contract`` const differs, and the successor requires
#: exactly the five supported transforms.
DETERMINATION_SCHEMA_RELATIVE_PATH = Path(
    "schemas/shell_company_determination.v2.schema.json"
)
MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/shell_company_determination_manifest.v2.schema.json"
)
#: v0.3, the lineage-cohort run manifest (ADR-102). The record contract does
#: not move: a row determined through either path yields an identical v0.2
#: record, and only the manifest describing the *run* is versioned, because
#: v0.2's single ``bundle_manifest_sha256`` cannot describe a cohort spread
#: over many bundles. v0.1 and v0.2 stay byte-unchanged and neither validates
#: a v0.3 manifest.
MANIFEST_V3_SCHEMA_RELATIVE_PATH = Path(
    "schemas/shell_company_determination_manifest.v3.schema.json"
)
LINEAGE_MANIFEST_FILENAME = MANIFEST_FILENAME
#: The order determination records are written in, recorded in the manifest so
#: a reader need not infer it. Both keys come from artefacts -- the aggregate's
#: shard index and the bundle manifest's own entry order -- never from an
#: argument, so the output is independent of how the runs were enumerated.
RECORD_ORDER = "shard_index_then_bundle_entry_order"

#: The one fact this module reads. No other cover-page fact is consulted.
SHELL_FACT_NAME = "dei:EntityShellCompany"
#: Only this identifier scheme may bind a context to a CIK. Imported rather
#: than written here: this package may not name a URL.
SEC_CIK_SCHEME = SEC_CIK_IDENTIFIER_SCHEME
LEGAL_ENTITY_AXIS = "dei:LegalEntityAxis"

BALLOT_BOX_EMPTY = "☐"      # ☐  unchecked
BALLOT_BOX_X = "☒"          # ☒  crossed
TRANSFORM_BALLOTBOX = "ixt-sec:boolballotbox"
TRANSFORM_BOOLEAN_FALSE = "ixt:booleanfalse"
TRANSFORM_FIXED_FALSE = "ixt:fixed-false"
TRANSFORM_BOOLEAN_TRUE = "ixt:booleantrue"
TRANSFORM_FIXED_TRUE = "ixt:fixed-true"
#: The five transforms this module resolves. The four fixed and boolean
#: transforms take their meaning from the XBRL Transformation Registry, not
#: from what any filing renders; ixt-sec:boolballotbox is the only one whose
#: decoded content is read. Anything else yields unknown.
SUPPORTED_TRANSFORMS = (
    TRANSFORM_BALLOTBOX,
    TRANSFORM_BOOLEAN_FALSE,
    TRANSFORM_FIXED_FALSE,
    TRANSFORM_BOOLEAN_TRUE,
    TRANSFORM_FIXED_TRUE,
)

SHELL_TRUE = "true"
SHELL_FALSE = "false"
SHELL_UNKNOWN = "unknown"

BASIS_BALLOTBOX_EMPTY = "boolballotbox_empty_box"
BASIS_BALLOTBOX_X = "boolballotbox_crossed_box"
BASIS_FIXED_FALSE = "fixed_false_transform"
BASIS_BOOLEAN_FALSE = "boolean_false_transform"
BASIS_FIXED_TRUE = "fixed_true_transform"
BASIS_BOOLEAN_TRUE = "boolean_true_transform"
BASIS_NO_FACT = "no_shell_fact_in_document"
BASIS_NO_ASSIGNABLE = "no_fact_assignable_to_this_cik"
BASIS_MULTIPLE_ASSIGNABLE = "multiple_assignable_facts"
BASIS_UNSUPPORTED_TRANSFORM = "unsupported_transform"
BASIS_ABSENT_TRANSFORM = "absent_transform"
BASIS_UNRESOLVED_CONTENT = "unresolved_ballotbox_content"

_FACT_RE = re.compile(
    rb"<ix:nonNumeric\b[^>]*?>.*?</ix:nonNumeric>", re.S | re.I
)
_ATTR_RE = {
    "name": re.compile(rb'\bname="([^"]*)"', re.I),
    "contextRef": re.compile(rb'\bcontextRef="([^"]*)"', re.I),
    "format": re.compile(rb'\bformat="([^"]*)"', re.I),
}
_TAG_STRIP_RE = re.compile(rb"<[^>]*>")
_CONTEXT_RE = re.compile(
    rb'<xbrli:context\b[^>]*\bid="([^"]*)"[^>]*>(.*?)</xbrli:context>',
    re.S | re.I,
)
_IDENTIFIER_RE = re.compile(
    rb'<xbrli:identifier\b[^>]*\bscheme="([^"]*)"[^>]*>([^<]*)<', re.I
)
_MEMBER_RE = re.compile(
    rb'<xbrldi:explicitMember\b[^>]*\bdimension="([^"]*)"[^>]*>([^<]*)<', re.I
)
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class ShellDeterminationError(ValueError):
    """The bundle or a determination input is unusable; the run refuses."""


@dataclass
class ShellFact:
    """One raw ``dei:EntityShellCompany`` element, addressed to its bytes."""

    byte_start: int
    byte_end: int          # half-open: bytes are raw[byte_start:byte_end]
    element_sha256: str
    context_ref: Optional[str]
    transform: Optional[str]
    decoded_content: str


@dataclass
class XbrlContext:
    """One ``xbrli:context`` with **every** explicit member it declares.

    All members are retained, not just the first: a context may declare a
    member on some other axis before its ``dei:LegalEntityAxis`` member, and
    reading only the first would treat such a context as unmembered and let it
    bind — which is exactly the assignment ADR-094 forbids.
    """

    context_id: str
    identifier_scheme: Optional[str]
    identifier_value: Optional[str]
    members: list[tuple[str, str]]

    @property
    def legal_entity_members(self) -> list[str]:
        """Member values on ``dei:LegalEntityAxis``, in document order."""
        return [
            value
            for dimension, value in self.members
            if dimension.lower() == LEGAL_ENTITY_AXIS.lower()
        ]

    @property
    def is_membered(self) -> bool:
        """True if *any* member sits on the legal-entity axis, at any position."""
        return bool(self.legal_entity_members)


@dataclass
class ShellRunResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    bundle_manifest_sha256: str
    determinations: list[dict] = field(default_factory=list)
    manifest_path: Path | None = None
    counts: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)


def extract_shell_facts(raw: bytes) -> list[ShellFact]:
    """Every ``dei:EntityShellCompany`` element, in document order.

    Offsets are half-open and ``element_sha256`` covers exactly
    ``raw[byte_start:byte_end]``: the complete raw element, unnormalized.
    """
    facts: list[ShellFact] = []
    for match in _FACT_RE.finditer(raw):
        block = match.group(0)
        name = _ATTR_RE["name"].search(block)
        if name is None or name.group(1).decode("utf-8", "replace") != SHELL_FACT_NAME:
            continue
        context_ref = _ATTR_RE["contextRef"].search(block)
        transform = _ATTR_RE["format"].search(block)
        inner = _TAG_STRIP_RE.sub(b"", block).decode("utf-8", "replace")
        facts.append(
            ShellFact(
                byte_start=match.start(),
                byte_end=match.end(),
                element_sha256=sha256(raw[match.start():match.end()]).hexdigest(),
                context_ref=(
                    context_ref.group(1).decode("utf-8", "replace")
                    if context_ref else None
                ),
                transform=(
                    transform.group(1).decode("utf-8", "replace")
                    if transform else None
                ),
                decoded_content=unescape(inner).strip(),
            )
        )
    return facts


def extract_contexts(raw: bytes) -> dict[str, XbrlContext]:
    """Every ``xbrli:context`` by id, with its identifier and **all** members."""
    contexts: dict[str, XbrlContext] = {}
    for match in _CONTEXT_RE.finditer(raw):
        context_id = match.group(1).decode("utf-8", "replace")
        body = match.group(2)
        identifier = _IDENTIFIER_RE.search(body)
        contexts[context_id] = XbrlContext(
            context_id=context_id,
            identifier_scheme=(
                identifier.group(1).decode("utf-8", "replace")
                if identifier else None
            ),
            identifier_value=(
                identifier.group(2).decode("utf-8", "replace").strip()
                if identifier else None
            ),
            members=[
                (
                    match.group(1).decode("utf-8", "replace"),
                    match.group(2).decode("utf-8", "replace").strip(),
                )
                for match in _MEMBER_RE.finditer(body)
            ],
        )
    return contexts


#: Transforms whose output the XBRL Transformation Registry fixes, mapped to
#: that output and the basis naming it. Rendered content is never consulted
#: for these; ``ixt-sec:boolballotbox`` is the only content-dependent case.
CONTENT_INDEPENDENT_TRANSFORMS = {
    TRANSFORM_BOOLEAN_FALSE: (SHELL_FALSE, BASIS_BOOLEAN_FALSE),
    TRANSFORM_FIXED_FALSE: (SHELL_FALSE, BASIS_FIXED_FALSE),
    TRANSFORM_BOOLEAN_TRUE: (SHELL_TRUE, BASIS_BOOLEAN_TRUE),
    TRANSFORM_FIXED_TRUE: (SHELL_TRUE, BASIS_FIXED_TRUE),
}


def evaluate_fact(fact: ShellFact) -> tuple[str, str]:
    """Apply the declared transform to the decoded content.

    Returns ``(shell_company, basis)``. Only ``ixt-sec:boolballotbox`` reads
    the decoded content. The four fixed and boolean transforms return the
    output the XBRL Transformation Registry defines for them, whatever the
    element renders — this function must never infer either direction from a
    checkbox glyph for those four.
    """
    if fact.transform is None:
        return SHELL_UNKNOWN, BASIS_ABSENT_TRANSFORM
    if fact.transform not in SUPPORTED_TRANSFORMS:
        return SHELL_UNKNOWN, BASIS_UNSUPPORTED_TRANSFORM
    fixed = CONTENT_INDEPENDENT_TRANSFORMS.get(fact.transform)
    if fixed is not None:
        # Returned before decoded_content is read at all, so a contradicting
        # glyph cannot reach a branch in either direction.
        return fixed
    content = fact.decoded_content
    if content == BALLOT_BOX_EMPTY:
        return SHELL_FALSE, BASIS_BALLOTBOX_EMPTY
    if content == BALLOT_BOX_X:
        return SHELL_TRUE, BASIS_BALLOTBOX_X
    return SHELL_UNKNOWN, BASIS_UNRESOLVED_CONTENT


def assignable_facts(
    facts: list[ShellFact], contexts: dict[str, XbrlContext], cik: str
) -> tuple[list[ShellFact], list[str]]:
    """Facts whose context binds to ``cik``, plus why the others did not."""
    assignable: list[ShellFact] = []
    notes: list[str] = []
    for fact in facts:
        if fact.context_ref is None:
            notes.append("fact carries no contextRef")
            continue
        context = contexts.get(fact.context_ref)
        if context is None:
            notes.append(f"contextRef {fact.context_ref!r} resolves to no context")
            continue
        if context.identifier_scheme != SEC_CIK_SCHEME:
            notes.append(
                f"context {context.context_id!r} identifier scheme "
                f"{context.identifier_scheme!r} is not the SEC CIK scheme"
            )
            continue
        if context.is_membered:
            # Filer-defined member tokens carry no CIK, and nothing in the
            # filing maps them. Never resolved by name resemblance.
            notes.append(
                f"context {context.context_id!r} carries LegalEntityAxis "
                f"member(s) {context.legal_entity_members!r}, which the filing "
                "does not map to a CIK"
            )
            continue
        if (context.identifier_value or "").lstrip("0") != cik.lstrip("0"):
            notes.append(
                f"context {context.context_id!r} identifies CIK "
                f"{context.identifier_value!r}, not this row"
            )
            continue
        assignable.append(fact)
    return assignable, notes


def determine_for_row(entry: dict, raw: bytes) -> dict:
    """One governed determination for one carrier row."""
    cik = entry["cik"]
    facts = extract_shell_facts(raw)
    contexts = extract_contexts(raw)
    assignable, notes = assignable_facts(facts, contexts, cik)

    fact: Optional[ShellFact] = None
    if not facts:
        shell, basis, detail = SHELL_UNKNOWN, BASIS_NO_FACT, (
            "the document declares no dei:EntityShellCompany fact"
        )
    elif len(assignable) > 1:
        values = {evaluate_fact(f)[0] for f in assignable}
        shell, basis = SHELL_UNKNOWN, BASIS_MULTIPLE_ASSIGNABLE
        detail = (
            f"{len(assignable)} facts bind to this CIK with values "
            f"{sorted(values)}; duplicates are never collapsed in v0.1, "
            "whether or not they agree"
        )
    elif not assignable:
        shell, basis = SHELL_UNKNOWN, BASIS_NO_ASSIGNABLE
        detail = "; ".join(notes) or "no fact could be assigned to this CIK"
    else:
        fact = assignable[0]
        shell, basis = evaluate_fact(fact)
        detail = (
            f"transform {fact.transform!r} applied to decoded content "
            f"{fact.decoded_content!r}"
        )

    return {
        "determination_contract": DETERMINATION_CONTRACT,
        "cik": cik,
        "company_id": company_id_for_cik(cik),
        "accession": entry["accession"],
        "form": entry["form"],
        "baseline_filing_date": entry["baseline_filing_date"],
        "source_sha256": entry["source_sha256"],
        "shell_company": shell,
        "basis": basis,
        "detail": detail,
        "facts_in_document": len(facts),
        "assignable_facts": len(assignable),
        "transform_observed": fact.transform if fact else None,
        "decoded_content_observed": fact.decoded_content if fact else None,
        "context_ref_observed": fact.context_ref if fact else None,
        "fact_byte_start": fact.byte_start if fact else None,
        "fact_byte_end": fact.byte_end if fact else None,
        "fact_element_sha256": fact.element_sha256 if fact else None,
    }


def run_shell_company_determination(
    *,
    repo_root: str | Path,
    bundle_dir: str | Path,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> ShellRunResult:
    """Determine shell status for every row of a local, hash-verified bundle."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ShellDeterminationError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    manifest, entries, bundle_sha = load_bundle(root, Path(bundle_dir))

    determinations = [
        determine_for_row(entry, entry["path"].read_bytes()) for entry in entries
    ]
    provenance = dict(manifest["provenance"])
    for record in determinations:
        record["bundle_manifest_sha256"] = bundle_sha
        record["carrier_provenance"] = {
            "carrier_run_id": provenance["carrier_run_id"],
            "carrier_manifest_sha256": provenance["carrier_manifest_sha256"],
            "freeze_record_sha256": provenance["freeze_record_sha256"],
        }

    by_outcome: dict[str, int] = {}
    by_basis: dict[str, int] = {}
    for record in determinations:
        by_outcome[record["shell_company"]] = (
            by_outcome.get(record["shell_company"], 0) + 1
        )
        by_basis[record["basis"]] = by_basis.get(record["basis"], 0) + 1
    counts = {
        "rows_considered": len(entries),
        "determinations": len(determinations),
        "shell_true": by_outcome.get(SHELL_TRUE, 0),
        "shell_false": by_outcome.get(SHELL_FALSE, 0),
        "shell_unknown": by_outcome.get(SHELL_UNKNOWN, 0),
        "firms_excluded": by_outcome.get(SHELL_TRUE, 0),
        "by_basis": by_basis,
    }
    reconciliation = {
        "one determination per bundle row": (
            counts["rows_considered"] == counts["determinations"]
        ),
        "outcomes partition the determinations": (
            counts["shell_true"] + counts["shell_false"] + counts["shell_unknown"]
            == counts["determinations"]
        ),
        "exclusions are exactly the true determinations": (
            counts["firms_excluded"] == counts["shell_true"]
        ),
        "every true or false determination cites one raw fact": all(
            (
                record["fact_element_sha256"] is not None
                and record["fact_byte_start"] is not None
                and record["fact_byte_end"] > record["fact_byte_start"]
            )
            for record in determinations
            if record["shell_company"] in (SHELL_TRUE, SHELL_FALSE)
        ),
        "no unknown determination excludes a firm": all(
            record["shell_company"] != SHELL_TRUE
            for record in determinations
            if record["basis"].startswith(("no_", "multiple_", "unsupported_",
                                           "absent_", "unresolved_"))
        ),
    }
    failed = sorted(name for name, ok in reconciliation.items() if not ok)
    if failed:
        raise ShellDeterminationError(
            f"Shell determination reconciliation failed: {'; '.join(failed)}. "
            "Nothing was written."
        )

    result = ShellRunResult(
        run_id=run_id, run_dir=None, dry_run=dry_run,
        bundle_manifest_sha256=bundle_sha, determinations=determinations,
        counts=counts, reconciliation=reconciliation,
    )
    if dry_run:
        return result

    schema = read_json(root / DETERMINATION_SCHEMA_RELATIVE_PATH)
    validator = Draft202012Validator(schema)
    for record in determinations:
        errors = sorted(validator.iter_errors(record), key=lambda e: e.json_path)
        if errors:
            details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
            raise ValueError(
                f"Determination violates the canonical schema: {details}"
            )

    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir
    payload = (
        "\n".join(json.dumps(r, sort_keys=True) for r in determinations)
        + ("\n" if determinations else "")
    ).encode("utf-8")
    write_bytes_once(
        run_dir / DETERMINATIONS_FILENAME, payload,
        what="shell company determinations",
    )

    schema_versions = read_json(
        root / "schemas" / "schema_version_manifest.json"
    )["schemas"]
    run_manifest = {
        "run_id": run_id,
        "determination_contract": DETERMINATION_CONTRACT,
        "bundle_manifest_sha256": bundle_sha,
        "carrier_provenance": determinations[0]["carrier_provenance"]
        if determinations else {},
        "supported_transforms": list(SUPPORTED_TRANSFORMS),
        "counts": counts,
        "reconciliation": reconciliation,
        "output_hashes": {DETERMINATIONS_FILENAME: sha256(payload).hexdigest()},
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "shell_company_determination_v2": schema_versions[
                "shell_company_determination_v2"
            ],
            "shell_company_determination_manifest_v2": schema_versions[
                "shell_company_determination_manifest_v2"
            ],
        },
        "limitations": [
            "Exactly one fact is determined: shell_company. The four other "
            "Stage 00B flags are neither read, set nor inferred, and the "
            "five-flag issuer_filters contract is untouched.",
            "true is a deterministic hard exclusion with dated evidence; "
            "false means retained and asserts nothing about software, product "
            "or general eligibility; unknown is retained.",
            "Five transforms are resolved: ixt-sec:boolballotbox, whose "
            "decoded content is read, and ixt:booleanfalse, ixt:fixed-false, "
            "ixt:booleantrue and ixt:fixed-true, whose outputs the XBRL "
            "Transformation Registry fixes regardless of rendered content. No "
            "checkbox glyph is consulted for those four in either direction. "
            "Any other transform, and an absent one, yield unknown.",
            "A context carrying a dei:LegalEntityAxis member is unassignable "
            "unless the filing maps that member to the row CIK; a "
            "filer-defined member token is never resolved by name "
            "resemblance.",
            "Missing, malformed, unsupported, conflicting, unassignable or "
            "multiple assignable facts all yield unknown; agreeing duplicates "
            "are not collapsed.",
            "Fixture-first: determinations are read from locally supplied, "
            "hash-verified primary documents. This module performs no network "
            "access and no model call.",
        ],
    }
    manifest_schema = read_json(root / MANIFEST_SCHEMA_RELATIVE_PATH)
    errors = sorted(
        Draft202012Validator(manifest_schema).iter_errors(run_manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"Shell determination manifest violates the canonical schema: {details}"
        )
    manifest_payload = (
        json.dumps(run_manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_bytes_once(
        run_dir / MANIFEST_FILENAME, manifest_payload,
        what="shell company determination manifest",
    )
    result.manifest_path = run_dir / MANIFEST_FILENAME
    return result


# --- ADR-102: the lineage cohort ---------------------------------------------
#
# The single-bundle path above is unchanged and still takes one bundle
# directory. A completed cohort, however, lives in many bundles across many
# execution runs, and the only artefact naming them authoritatively is the
# ADR-101 aggregate. Copying primaries into one directory would make a second,
# unhashed copy of immutable evidence; merging bundle manifests would fabricate
# an artefact no acquisition run wrote. The aggregate is read as the authority
# root instead.
#
# **It is the only data-location input there is.** This consumer takes no
# shard-output root, no bundle directory, no replay directory, no glob and no
# search path, so there is nothing to scan *with*. Every directory it opens is
# exactly a ``shards_authoritative[].run_dir`` value from the validated
# manifest, resolved against the repository root and never joined with an
# operator-supplied prefix. ``superseded_directories`` and
# ``shards_not_authoritative`` are counted and never resolved: a nearby shard
# directory that the aggregate does not name is unreachable, because no code
# path here constructs its name.


def load_lineage_bundles(
    repo_root: str | Path, aggregate_manifest_path: str | Path
) -> tuple[dict, list[dict], str, dict]:
    """Validate one ADR-101 aggregate and open exactly the shards it names.

    The validation itself lives in :mod:`.lineage_authority` (ADR-103), where
    the Item 1 packet consumer shares it instead of duplicating it or
    importing it from here in a cycle. This wrapper preserves ADR-102's public
    seam exactly: same signature, same return shape, and the same
    :class:`ShellDeterminationError` carrying the identical message.
    """
    try:
        return _load_lineage_bundles(repo_root, aggregate_manifest_path)
    except LineageAuthorityError as exc:
        raise ShellDeterminationError(str(exc)) from exc


def run_lineage_shell_company_determination(
    *,
    repo_root: str | Path,
    aggregate_manifest_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> ShellRunResult:
    """Determine shell status for every carrier row of one lineage cohort."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ShellDeterminationError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    aggregate, shards, aggregate_sha, provenance = load_lineage_bundles(
        root, aggregate_manifest_path
    )

    determinations: list[dict] = []
    for shard in shards:
        for entry in shard["entries"]:
            record = determine_for_row(entry, entry["path"].read_bytes())
            record["bundle_manifest_sha256"] = shard["bundle_manifest_sha256"]
            record["carrier_provenance"] = dict(provenance)
            determinations.append(record)

    by_outcome: dict[str, int] = {}
    by_basis: dict[str, int] = {}
    for record in determinations:
        by_outcome[record["shell_company"]] = (
            by_outcome.get(record["shell_company"], 0) + 1
        )
        by_basis[record["basis"]] = by_basis.get(record["basis"], 0) + 1
    rows = sum(shard["rows"] for shard in shards)
    counts = {
        "rows_considered": rows,
        "determinations": len(determinations),
        "shell_true": by_outcome.get(SHELL_TRUE, 0),
        "shell_false": by_outcome.get(SHELL_FALSE, 0),
        "shell_unknown": by_outcome.get(SHELL_UNKNOWN, 0),
        "firms_excluded": by_outcome.get(SHELL_TRUE, 0),
        "by_basis": by_basis,
        "shards_consumed": len(shards),
        "superseded_directories_ignored": len(
            aggregate["superseded_directories"]
        ),
        "shards_not_authoritative_ignored": len(
            aggregate["shards_not_authoritative"]
        ),
    }
    reconciliation = {
        "one determination per carrier row": (
            counts["rows_considered"] == counts["determinations"]
        ),
        "outcomes partition the determinations": (
            counts["shell_true"] + counts["shell_false"] + counts["shell_unknown"]
            == counts["determinations"]
        ),
        "exclusions are exactly the true determinations": (
            counts["firms_excluded"] == counts["shell_true"]
        ),
        "every consumed shard is an authoritative aggregate record": (
            counts["shards_consumed"] == len(aggregate["shards_authoritative"])
        ),
        "rows equal the aggregate's carrier rows": (
            rows == aggregate["counts"]["carrier_rows_covered"]
        ),
        "every true or false determination cites one raw fact": all(
            (
                record["fact_element_sha256"] is not None
                and record["fact_byte_start"] is not None
                and record["fact_byte_end"] > record["fact_byte_start"]
            )
            for record in determinations
            if record["shell_company"] in (SHELL_TRUE, SHELL_FALSE)
        ),
        "no unknown determination excludes a firm": all(
            record["shell_company"] != SHELL_TRUE
            for record in determinations
            if record["basis"].startswith(("no_", "multiple_", "unsupported_",
                                           "absent_", "unresolved_"))
        ),
    }
    failed = sorted(name for name, ok in reconciliation.items() if not ok)
    if failed:
        raise ShellDeterminationError(
            f"Lineage shell determination reconciliation failed: "
            f"{'; '.join(failed)}. Nothing was written."
        )

    result = ShellRunResult(
        run_id=run_id, run_dir=None, dry_run=dry_run,
        bundle_manifest_sha256=aggregate_sha, determinations=determinations,
        counts=counts, reconciliation=reconciliation,
    )
    if dry_run:
        return result

    validator = Draft202012Validator(
        read_json(root / DETERMINATION_SCHEMA_RELATIVE_PATH)
    )
    for record in determinations:
        errors = sorted(validator.iter_errors(record), key=lambda e: e.json_path)
        if errors:
            details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
            raise ValueError(
                f"Determination violates the canonical schema: {details}"
            )

    run_dir = create_run_directory(output_dir, run_id)
    result.run_dir = run_dir
    payload = (
        "\n".join(json.dumps(r, sort_keys=True) for r in determinations)
        + ("\n" if determinations else "")
    ).encode("utf-8")
    write_bytes_once(
        run_dir / DETERMINATIONS_FILENAME, payload,
        what="lineage shell company determinations",
    )

    schema_versions = read_json(
        root / "schemas" / "schema_version_manifest.json"
    )["schemas"]
    run_manifest = {
        "run_id": run_id,
        "determination_contract": DETERMINATION_CONTRACT,
        "aggregate_manifest_path": str(aggregate_manifest_path),
        "aggregate_manifest_sha256": aggregate_sha,
        "aggregate_run_id": aggregate["run_id"],
        "queue_id": aggregate["queue_id"],
        "queue_definition_sha256": aggregate["queue_definition_sha256"],
        "execution_run_ids": list(aggregate["execution_run_ids"]),
        "shards_consumed": [
            {
                "shard_index": shard["shard_index"],
                "run_dir": shard["run_dir"],
                "bundle_manifest_sha256": shard["bundle_manifest_sha256"],
                "acquisition_manifest_sha256": shard[
                    "acquisition_manifest_sha256"
                ],
                "rows": shard["rows"],
            }
            for shard in shards
        ],
        "determination_record_order": RECORD_ORDER,
        "carrier_provenance": dict(provenance),
        "supported_transforms": list(SUPPORTED_TRANSFORMS),
        "counts": counts,
        "reconciliation": reconciliation,
        "output_hashes": {DETERMINATIONS_FILENAME: sha256(payload).hexdigest()},
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "shell_company_determination_v2": schema_versions[
                "shell_company_determination_v2"
            ],
            "shell_company_determination_manifest_v3": schema_versions[
                "shell_company_determination_manifest_v3"
            ],
            "acquisition_queue_aggregate_manifest_v2": schema_versions[
                "acquisition_queue_aggregate_manifest_v2"
            ],
        },
        "limitations": [
            "Exactly one fact is determined: shell_company. The four other "
            "Stage 00B flags are neither read, set nor inferred, and the "
            "five-flag issuer_filters contract is untouched.",
            "true is a deterministic hard exclusion with dated evidence; "
            "false means retained and asserts nothing about software, product "
            "or general eligibility; unknown is retained.",
            "The named aggregate is the sole authority root. This run took no "
            "shard-output root, bundle directory, replay directory, glob or "
            "search path, and every directory it opened was exactly a "
            "shards_authoritative run_dir from that manifest. Superseded and "
            "non-authoritative directories were counted, never resolved or "
            "opened, and a shard directory the aggregate does not name was "
            "unreachable.",
            "Each referenced bundle and acquisition manifest was re-hashed "
            "against the aggregate before any primary was read, and every "
            "primary's byte length and SHA-256 were verified by the unchanged "
            "bundle loader. The shard plans were not regenerated here: hash "
            "equality means the bytes read are the bytes the aggregate bound.",
            "Records are written in shard_index ascending order, then in each "
            "bundle manifest's own entry order. Both keys come from artefacts, "
            "so the output does not depend on the order the execution run ids "
            "were enumerated.",
            "Determination records keep the unchanged v0.2 record contract: a "
            "row determined here and through the single-bundle path yields an "
            "identical record.",
            "Fixture-first: determinations are read from locally supplied, "
            "hash-verified primary documents. This module performs no network "
            "access and no model call.",
        ],
    }
    errors = sorted(
        Draft202012Validator(
            read_json(root / MANIFEST_V3_SCHEMA_RELATIVE_PATH)
        ).iter_errors(run_manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"Lineage determination manifest violates the canonical schema: "
            f"{details}"
        )
    manifest_payload = (
        json.dumps(run_manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_bytes_once(
        run_dir / LINEAGE_MANIFEST_FILENAME, manifest_payload,
        what="lineage shell company determination manifest",
    )
    result.manifest_path = run_dir / LINEAGE_MANIFEST_FILENAME
    return result
