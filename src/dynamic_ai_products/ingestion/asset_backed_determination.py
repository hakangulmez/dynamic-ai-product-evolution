"""ADR-105 deterministic asset-backed-issuer determination (fixture-first).

Governing documents:
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md (Stage 00B deterministic issuer
  exclusions)
- docs/DECISION_LOG.md ADR-094 (shell determination, the sibling pattern),
  ADR-101 (lineage aggregate authority), ADR-105 (this design)

Reads exactly one question from primary annual-report documents that are
already local and hash-verified: **is this filing an asset-backed issuer's
Form 10-K filed under General Instruction J with Regulation AB disclosure?**
It emits one governed determination per carrier row, ``true`` or ``unknown``,
and never ``false``: absence of the signature is absence of evidence, not
evidence of an operating company.

**Two positive conditions, both required in the same filing.** ``true``
demands:

1. an **explicit, non-negated Item 1 / Part I omission construction tied
   structurally to General Instruction J** — one contiguous construction of
   the form ``omitted / not included / not applicable`` immediately followed
   by ``pursuant to / in accordance with / in reliance (up)on / under
   General Instruction J``, with an ``Item 1`` or ``Part I`` reference in
   the 150 bytes before the construction and no negator (``no``, ``not``,
   ``none``, ``never``, ``nor``, ``without``) in the 40 bytes before it.
   Two nearby words in an arbitrary window never qualify, and ``pursuant
   to`` alone is not an omission; and
2. a **structural Regulation AB disclosure signature** — at least one
   **block-opening** ``Item 1112 / 1114 / 1115 / 1117 / 1119 / 1122 / 1123``
   heading, under the same ``_starts_a_block`` guard the Item 1 locator
   uses (line-start for plain text). An inline prose citation of a
   Regulation AB item is not a heading and supplies nothing.

Either half alone stays ``unknown``. So does an operating company that
merely discusses securitization or asset-backed securities, a trust by name,
and a filing with a short Item 1: **no word count, span length, or
source-size ratio is ever consulted**. The determination is made from the
two named signatures or not at all.

**Every true result carries its evidence**: the source document's SHA-256,
the exact quote for each condition, half-open raw-byte offsets computed
through the same tag-and-entity offset map the Item 1 locator uses, the rule
id, and the reason code ``ASSET_BACKED_ISSUER`` — the same string
``issuer_filters`` has always reserved for this exclusion, reused verbatim so
downstream readers need no mapping. The five-flag ``issuer_filters`` contract
itself is untouched: this module neither imports its evaluation logic nor
sets any generic flag, because a flag without the evidence above would be
exactly the routing-around this design forbids.

**The aggregate is the sole authority for what is opened** (ADR-101/102/103
semantics, shared through :mod:`.lineage_authority`): no shard-output root,
no glob, no alternate shard root, and every bundle and primary is re-hashed
before any byte is read.

This module performs no network access and no model call, names no URL, and
never reads the clock.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator

from ..provenance import write_bytes_once
from ..universe.freeze import create_run_directory
from ..universe.identifiers import company_id_for_cik
from ..universe.io_utils import read_json
from .lineage_authority import LineageAuthorityError, load_lineage_bundles
from .normalize import _starts_a_block, _starts_a_text_line, _text_offset_map

DETERMINATION_CONTRACT = "asset_backed_issuer_determination@0.1.0"
DETERMINATIONS_FILENAME = "asset_backed_issuer_determinations.jsonl"
MANIFEST_FILENAME = "asset_backed_issuer_determination_manifest.json"
DETERMINATION_SCHEMA_RELATIVE_PATH = Path(
    "schemas/asset_backed_issuer_determination.schema.json"
)
MANIFEST_SCHEMA_RELATIVE_PATH = Path(
    "schemas/asset_backed_issuer_determination_manifest.schema.json"
)

#: The reason code issuer_filters has always reserved for this exclusion,
#: reproduced byte-for-byte (universe/issuer_filters.py). Recorded only on a
#: ``true`` determination, whose evidence fields justify it.
REASON_CODE = "ASSET_BACKED_ISSUER"
#: The two-condition rule this module applies, named so a record can cite it.
RULE_ID = "instruction_j_omission_and_reg_ab_items@1"

DET_TRUE = "true"
DET_UNKNOWN = "unknown"

BASIS_BOTH_CONDITIONS = "instruction_j_omission_and_reg_ab_items"
BASIS_J_ONLY = "general_instruction_j_only"
BASIS_REG_AB_ONLY = "regulation_ab_items_only"
BASIS_NO_EVIDENCE = "no_asset_backed_evidence"

#: Regulation AB's asset-backed-issuer item series. Membership is exact:
#: Item 1111 or Item 1124 would not match.
REG_AB_ITEM_NUMBERS = ("1112", "1114", "1115", "1117", "1119", "1122", "1123")

#: The omission construction, matched as one contiguous expression: an
#: omission verb, a bounded joiner, and the instruction reference. This is a
#: structural tie, not word proximity — "pursuant to" alone is a citation,
#: not an omission, and never qualifies by itself.
_J_OMISSION_CONSTRUCTION_RE = re.compile(
    rb"(?i)\b(?:omitted|not\s{1,20}included|not\s{1,20}applicable)\b"
    rb"[\s\.,;]{0,20}"
    rb"(?:pursuant\s{1,20}to|in\s{1,20}accordance\s{1,20}with|"
    rb"in\s{1,20}reliance\s{1,20}(?:up)?on|under)\s{1,20}"
    rb"General\s{1,20}Instruction\s{1,20}J\b"
)
#: A construction preceded by a negator is a statement that nothing was
#: omitted, and refuses.
_NEGATION_RE = re.compile(rb"(?i)\b(?:no|not|none|never|nor|without)\b")
_NEGATION_WINDOW = 40
#: The omission must be about Item 1 / Part I: the reference must appear
#: immediately before the construction.
_ITEM_ONE_TIE_RE = re.compile(rb"(?i)\bItems?\s{0,20}1\b|\bPart\s{1,20}I\b")
_ITEM_TIE_WINDOW = 150

_REG_AB_ITEM_RE = re.compile(
    (r"(?i)\bItem\s{1,20}(" + "|".join(REG_AB_ITEM_NUMBERS) + r")\b").encode()
)

_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

RECORD_ORDER = "shard_index_then_bundle_entry_order"


class AssetBackedDeterminationError(ValueError):
    """The aggregate, a shard, or a determination input is unusable; refuse."""


@dataclass
class AssetBackedRunResult:
    run_id: str
    run_dir: Path | None
    dry_run: bool
    aggregate_manifest_sha256: str
    determinations: list[dict] = field(default_factory=list)
    manifest_path: Path | None = None
    counts: dict = field(default_factory=dict)
    reconciliation: dict = field(default_factory=dict)


def _quote(stream: bytes, start: int, end: int) -> str:
    """Whitespace-collapsed text of the matched stream region."""
    return " ".join(
        stream[start:end].decode("utf-8", errors="replace").split()
    )


def _raw_span(offsets: list[int], start: int, end: int) -> tuple[int, int]:
    """Half-open raw-byte offsets covering stream positions [start, end)."""
    return offsets[start], offsets[end - 1] + 1


def determine_for_row(entry: dict, raw: bytes) -> dict:
    """Determine asset-backed-issuer status for one carrier row.

    Both representations run the same two probes: for html the probes read
    the tag-and-entity-collapsed stream with raw-offset mapping; for
    plain text the raw bytes are their own stream.
    """
    if entry.get("representation", "html") == "html":
        stream, offsets = _text_offset_map(raw)

        def opens_block(stream_position: int) -> bool:
            return _starts_a_block(raw, offsets[stream_position])
    else:
        stream, offsets = raw, list(range(len(raw)))

        def opens_block(stream_position: int) -> bool:
            return _starts_a_text_line(raw, stream_position)

    # Condition 1: a non-negated Item 1 / Part I omission construction tied
    # structurally to General Instruction J.
    instruction = None
    for match in _J_OMISSION_CONSTRUCTION_RE.finditer(stream):
        negation_window = stream[max(0, match.start() - _NEGATION_WINDOW):
                                 match.start()]
        if _NEGATION_RE.search(negation_window):
            continue
        tie_window = stream[max(0, match.start() - _ITEM_TIE_WINDOW):
                            match.start()]
        if not _ITEM_ONE_TIE_RE.search(tie_window):
            continue
        instruction = match
        break

    # Condition 2: block-opening Regulation AB item headings only. An inline
    # prose citation fails the same guard the Item 1 locator applies.
    reg_ab_matches = [
        m for m in _REG_AB_ITEM_RE.finditer(stream)
        if opens_block(m.start())
    ]
    reg_ab_items = sorted({m.group(1).decode("ascii") for m in reg_ab_matches})

    record = {
        "determination_contract": DETERMINATION_CONTRACT,
        "cik": entry["cik"],
        "company_id": company_id_for_cik(entry["cik"]),
        "accession": entry["accession"],
        "form": entry["form"],
        "baseline_filing_date": entry["baseline_filing_date"],
        "source_sha256": entry["source_sha256"],
        "asset_backed_issuer": DET_UNKNOWN,
        "basis": BASIS_NO_EVIDENCE,
        "reason_code": None,
        "rule_id": RULE_ID,
        "instruction_j_quote": None,
        "instruction_j_byte_start": None,
        "instruction_j_byte_end": None,
        "reg_ab_items": None,
        "reg_ab_quote": None,
        "reg_ab_byte_start": None,
        "reg_ab_byte_end": None,
    }
    if instruction is not None and reg_ab_items:
        j_start, j_end = _raw_span(offsets, instruction.start(),
                                   instruction.end())
        first = reg_ab_matches[0]
        ab_start, ab_end = _raw_span(offsets, first.start(), first.end())
        record.update({
            "asset_backed_issuer": DET_TRUE,
            "basis": BASIS_BOTH_CONDITIONS,
            "reason_code": REASON_CODE,
            "instruction_j_quote": _quote(stream, instruction.start(),
                                          instruction.end()),
            "instruction_j_byte_start": j_start,
            "instruction_j_byte_end": j_end,
            "reg_ab_items": reg_ab_items,
            "reg_ab_quote": _quote(stream, first.start(), first.end()),
            "reg_ab_byte_start": ab_start,
            "reg_ab_byte_end": ab_end,
        })
    elif instruction is not None:
        record["basis"] = BASIS_J_ONLY
    elif reg_ab_items:
        record["basis"] = BASIS_REG_AB_ONLY
    return record


def run_asset_backed_determination(
    *,
    repo_root: str | Path,
    aggregate_manifest_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> AssetBackedRunResult:
    """Determine asset-backed status for every carrier row of one lineage."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise AssetBackedDeterminationError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    try:
        aggregate, shards, aggregate_sha, provenance = load_lineage_bundles(
            root, aggregate_manifest_path
        )
    except LineageAuthorityError as exc:
        raise AssetBackedDeterminationError(str(exc)) from exc

    determinations: list[dict] = []
    for shard in shards:
        for entry in shard["entries"]:
            record = determine_for_row(entry, entry["path"].read_bytes())
            record["bundle_manifest_sha256"] = shard["bundle_manifest_sha256"]
            record["carrier_provenance"] = dict(provenance)
            determinations.append(record)

    by_outcome = {DET_TRUE: 0, DET_UNKNOWN: 0}
    by_basis: dict[str, int] = {}
    for record in determinations:
        by_outcome[record["asset_backed_issuer"]] += 1
        by_basis[record["basis"]] = by_basis.get(record["basis"], 0) + 1
    counts = {
        "rows_considered": len(determinations),
        "determinations": len(determinations),
        "asset_backed_true": by_outcome[DET_TRUE],
        "asset_backed_unknown": by_outcome[DET_UNKNOWN],
        "by_basis": by_basis,
        "shards_consumed": len(shards),
    }
    reconciliation = {
        "one determination per carrier row": (
            counts["rows_considered"]
            == sum(shard["rows"] for shard in shards)
        ),
        "outcomes partition the determinations": (
            counts["asset_backed_true"] + counts["asset_backed_unknown"]
            == counts["determinations"]
        ),
        "false is never emitted": all(
            record["asset_backed_issuer"] in (DET_TRUE, DET_UNKNOWN)
            for record in determinations
        ),
        "every true determination cites both conditions": all(
            record["instruction_j_quote"] is not None
            and record["reg_ab_items"]
            and record["reason_code"] == REASON_CODE
            and record["instruction_j_byte_end"]
            > record["instruction_j_byte_start"]
            and record["reg_ab_byte_end"] > record["reg_ab_byte_start"]
            for record in determinations
            if record["asset_backed_issuer"] == DET_TRUE
        ),
        "no unknown determination carries the exclusion code": all(
            record["reason_code"] is None
            for record in determinations
            if record["asset_backed_issuer"] == DET_UNKNOWN
        ),
    }
    failed = sorted(name for name, ok in reconciliation.items() if not ok)
    if failed:
        raise AssetBackedDeterminationError(
            f"Asset-backed determination reconciliation failed: "
            f"{'; '.join(failed)}. Nothing was written."
        )

    result = AssetBackedRunResult(
        run_id=run_id, run_dir=None, dry_run=dry_run,
        aggregate_manifest_sha256=aggregate_sha,
        determinations=determinations, counts=counts,
        reconciliation=reconciliation,
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
    write_bytes_once(run_dir / DETERMINATIONS_FILENAME, payload,
                     what="asset-backed issuer determinations")

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
        "rule": {
            "rule_id": RULE_ID,
            "reason_code": REASON_CODE,
            "reg_ab_item_numbers": list(REG_AB_ITEM_NUMBERS),
            "negation_window_bytes": _NEGATION_WINDOW,
            "item_tie_window_bytes": _ITEM_TIE_WINDOW,
        },
        "carrier_provenance": dict(provenance),
        "counts": counts,
        "reconciliation": reconciliation,
        "output_hashes": {DETERMINATIONS_FILENAME: sha256(payload).hexdigest()},
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "asset_backed_issuer_determination": schema_versions[
                "asset_backed_issuer_determination"
            ],
            "asset_backed_issuer_determination_manifest": schema_versions[
                "asset_backed_issuer_determination_manifest"
            ],
            "acquisition_queue_aggregate_manifest_v2": schema_versions[
                "acquisition_queue_aggregate_manifest_v2"
            ],
        },
        "limitations": [
            "Exactly one question is determined: asset_backed_issuer. The "
            "other Stage 00B flags are neither read, set nor inferred, and "
            "the five-flag issuer_filters contract is untouched; the "
            "ASSET_BACKED_ISSUER reason code is reused verbatim so no "
            "mapping is needed, and it is recorded only beside the evidence "
            "that justifies it.",
            "true requires both positive conditions in the same filing: a "
            "non-negated Item 1 / Part I omission construction tied "
            "structurally to General Instruction J, and at least one "
            "block-opening Regulation AB item heading (1112/1114/1115/1117/"
            "1119/1122/1123). Either half alone, an inline prose citation of "
            "a Regulation AB item, a bare 'pursuant to General Instruction "
            "J', securitization prose in an operating company's filing, a "
            "trust-styled name, and a short Item 1 all stay unknown; no "
            "word count or span ratio is ever consulted.",
            "false is never emitted: absence of the signature is absence of "
            "evidence, and unknown rows are retained by every downstream "
            "consumer until a governed rule says otherwise.",
            "The named aggregate is the sole authority root: no shard-output "
            "root, no glob, no alternate shard root, and every bundle and "
            "primary document was re-hashed before any byte was read.",
            "Records are written in shard_index ascending order, then in "
            "each bundle manifest's own entry order.",
            "Fixture-first: determinations are read from locally supplied, "
            "hash-verified primary documents. This module performs no "
            "network access and no model call.",
        ],
    }
    errors = sorted(
        Draft202012Validator(
            read_json(root / MANIFEST_SCHEMA_RELATIVE_PATH)
        ).iter_errors(run_manifest),
        key=lambda e: e.json_path,
    )
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ValueError(
            f"Asset-backed determination manifest violates the canonical "
            f"schema: {details}"
        )
    manifest_payload = (
        json.dumps(run_manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    write_bytes_once(run_dir / MANIFEST_FILENAME, manifest_payload,
                     what="asset-backed issuer determination manifest")
    result.manifest_path = run_dir / MANIFEST_FILENAME
    return result
