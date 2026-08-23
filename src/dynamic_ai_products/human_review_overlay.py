"""Ingest the human-review layer over one SCREEN_v1 release (ADR-125).

SCREEN_v1 named 211 rows `unresolved_after_repair`: rows whose evidence failed
verbatim validation twice, about which the screen knows nothing. This module
ingests a reviewer-supplied decision ledger for exactly those rows and writes it
as a separate, hash-bound overlay. It never edits the release, and the release
never learns of it — a human decision is a second observation layer, not a
correction applied to the first.

**Coverage is exact, and that is a bias control rather than tidiness.** Every
unresolved row must carry exactly one decision. A partial review would silently
select which holes get filled, and the selection would almost certainly
correlate with how legible a filing is — precisely the property the screen
already struggles with. A gap, a duplicate, a foreign row, or a decision aimed
at a row the release did not leave unresolved each refuse the whole ingestion.

**Evidence is cited the way a human reads it, and resolved the way a machine
must.** A reviewer supplies a displayed ``P001``-style reference and a
contiguous verbatim quote — never an opaque internal ``passage_id``, which is
not visible when reading Item 1 and would be transcription noise with no
reviewer-facing meaning. The loader re-derives the canonical passage id from the
hash-bound packet using the same ordinal convention the screen displayed, then
resolves the quote inside that passage's body. A quote that does not appear
verbatim in the cited passage refuses the ingestion, exactly as it would for a
model.

**The evidence chain reaches the immutable bytes.** The overlay binds the
release manifest, and through the release's own base run it binds that run's
packet manifest and packets JSONL. Human evidence is therefore tied to the Item
1 bytes the screen itself consumed, not to a rendering, a copy, or a reviewer's
recollection of them.

**A LIKELY_INELIGIBLE decision is kept, not discarded.** It enters no classifier
cohort, but dropping it would erase the record that a human looked and
concluded. The overlay is the audit trail for all 211 rows; admission is a
separate question answered downstream.

**No authorization governs this.** Nothing is spent: no provider, no prompt, no
token. The reviewers' decisions are themselves the authority, and the ledger is
the artifact of record. What replaces a grant is binding — pinned digests for
the release and the packet chain, and verbatim resolution of every quote.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

from .lineage_screen_release import (
    RELEASE_MANIFEST_FILENAME,
    RELEASE_RECORDS_FILENAME,
    require_screen_release,
)
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    ScreenInputError,
    _canonical_line,
    _decode_utf8,
    _load_schema,
    _RUN_ID_RE,
    _sha256,
    _validate,
    load_packet_run,
)

__all__ = [
    "OVERLAY_DECISIONS_FILENAME",
    "OVERLAY_MANIFEST_FILENAME",
    "HumanReviewOverlayResult",
    "build_human_review_overlay",
    "passage_refs",
    "require_human_review_overlay",
]

OVERLAY_DECISIONS_FILENAME = "universe_human_review_decisions.jsonl"
OVERLAY_MANIFEST_FILENAME = "universe_human_review_overlay_manifest.json"

DECISION_CONTRACT = "universe_human_review_decision@0.1.0"
MANIFEST_CONTRACT = "universe_human_review_overlay_manifest@0.1.0"
LEDGER_CONTRACT = "universe_human_review_decision_ledger@0.1.0"
RECORD_ORDER = "release_row_order"

DECISION_SCHEMA = "schemas/universe_human_review_decision.schema.json"
MANIFEST_SCHEMA = "schemas/universe_human_review_overlay_manifest.schema.json"

#: The release row kind a human decision may target, and no other.
REVIEWABLE_ORIGIN = "unresolved_after_repair"

#: The decision vocabulary, identical to the screen's so the two layers speak
#: the same language. Which of them a cohort admits is decided downstream.
DECISIONS = ("LIKELY_ELIGIBLE", "LIKELY_INELIGIBLE", "BOUNDARY_OR_UNCERTAIN")


@dataclass
class HumanReviewOverlayResult:
    overlay_id: str
    overlay_dir: Path | None
    dry_run: bool
    status: str  # "completed" | "dry_run"
    coverage: dict
    counts: dict
    reconciliation: dict
    manifest_path: Path | None = None


def passage_refs(packet: dict) -> dict[str, str]:
    """Map the displayed ``Pnnn`` references onto canonical passage ids.

    The convention is the screen's own: passages are referenced by their
    1-based position in the packet, zero-padded to three digits. A test pins
    this against the committed renderer, so the reviewer's reference and the
    model's reference can never drift apart silently.
    """
    return {f"P{ordinal:03d}": passage["passage_id"]
            for ordinal, passage in enumerate(packet["passages"], start=1)}


def _load_release(root: Path, manifest_path: Path, expected_sha256: str
                  ) -> tuple[dict, list[dict], str]:
    """Pin the release by digest, revalidate it, then read its rows."""
    if manifest_path.name != RELEASE_MANIFEST_FILENAME:
        raise ScreenInputError(
            f"The release manifest must be {RELEASE_MANIFEST_FILENAME}; "
            f"{manifest_path.name} is a different artifact."
        )
    if not manifest_path.is_file():
        raise ScreenInputError(f"Release manifest not found: {manifest_path}")
    raw = manifest_path.read_bytes()
    observed = _sha256(raw)
    if observed != expected_sha256:
        raise ScreenInputError(
            f"The release manifest hashes to {observed}, but {expected_sha256} "
            "was pinned; this is not the release these decisions reviewed."
        )
    require_screen_release(manifest_path.parent)
    manifest = json.loads(_decode_utf8(raw, RELEASE_MANIFEST_FILENAME))
    records = [
        json.loads(line) for line
        in _decode_utf8((manifest_path.parent / RELEASE_RECORDS_FILENAME).read_bytes(),
                        RELEASE_RECORDS_FILENAME).splitlines()
        if line.strip()
    ]
    return manifest, records, observed


def _bind_packet_source(root: Path, release_manifest: dict) -> dict:
    """Reach the immutable Item 1 bytes through the release's own base run.

    The release names its base run; that run's manifest names the packet
    manifest and the packets JSONL by digest. Both are re-hashed here, so a
    human quote is bound to the bytes the screen consumed rather than to a
    path that merely looks right.
    """
    base_manifest_path = Path(release_manifest["sources"]["base"]["manifest_path"])
    if not base_manifest_path.is_absolute():
        base_manifest_path = root / base_manifest_path
    if not base_manifest_path.is_file():
        raise ScreenInputError(
            f"The release names base manifest {base_manifest_path}, which is "
            "not present; the packet chain cannot be bound."
        )
    base_raw = base_manifest_path.read_bytes()
    if _sha256(base_raw) != release_manifest["sources"]["base"]["manifest_sha256"]:
        raise ScreenInputError(
            "The base run manifest no longer hashes to the digest the release "
            "recorded; the packet chain is not trustworthy."
        )
    base = json.loads(_decode_utf8(base_raw, base_manifest_path.name))
    packet_manifest_path = base["packet_manifest_path"]
    resolved = root / packet_manifest_path
    if not resolved.is_file():
        raise ScreenInputError(
            f"The base run names packet manifest {packet_manifest_path}, which "
            "is not present."
        )
    observed = _sha256(resolved.read_bytes())
    if observed != base["packet_manifest_sha256"]:
        raise ScreenInputError(
            f"The packet manifest hashes to {observed}, but the base run "
            f"recorded {base['packet_manifest_sha256']}; the Item 1 bytes have "
            "moved beneath the review."
        )
    inputs = load_packet_run(root, packet_manifest_path)
    if inputs.packets_jsonl_sha256 != base["packets_jsonl_sha256"]:
        raise ScreenInputError(
            "The packets JSONL no longer hashes to the digest the base run "
            "recorded; human evidence may not be resolved against it."
        )
    return {
        "base_run_id": base["run_id"],
        "packet_manifest_path": packet_manifest_path,
        "packet_manifest_sha256": observed,
        "packets_jsonl_sha256": inputs.packets_jsonl_sha256,
        "quotes_resolved_against_packet_bytes": True,
        "_packets": {(p["cik"], p["accession"]): p for p in inputs.packets},
    }


def _load_ledger(root: Path, ledger_path: Path) -> list[dict]:
    raw = Path(ledger_path).read_bytes()
    ledger = json.loads(_decode_utf8(raw, Path(ledger_path).name))
    if not isinstance(ledger, dict):
        raise ScreenInputError("The decision ledger must be a JSON object.")
    if ledger.get("ledger_contract") != LEDGER_CONTRACT:
        raise ScreenInputError(
            f"The ledger declares {ledger.get('ledger_contract')!r}; this route "
            f"ingests {LEDGER_CONTRACT!r} only."
        )
    decisions = ledger.get("decisions")
    if not isinstance(decisions, list) or not decisions:
        raise ScreenInputError("The decision ledger carries no decisions.")
    return decisions


def build_human_review_overlay(
    *,
    repo_root: str | Path,
    release_manifest_path: str | Path,
    release_manifest_sha256: str,
    ledger_path: str | Path,
    output_dir: str | Path,
    overlay_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> HumanReviewOverlayResult:
    """Validate one reviewer ledger against SCREEN_v1 and write the overlay."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(overlay_id):
        raise ScreenInputError("Invalid overlay id.")
    release_manifest_path = Path(release_manifest_path)
    release, release_rows, release_sha = _load_release(
        root, release_manifest_path, release_manifest_sha256)
    packet_source = _bind_packet_source(root, release)
    packets = packet_source.pop("_packets")
    decisions = _load_ledger(root, Path(ledger_path))

    unresolved = {(r["cik"], r["accession"]): r for r in release_rows
                  if r["release_origin"] == REVIEWABLE_ORIGIN}
    if not unresolved:
        raise ScreenInputError(
            "The release left no unresolved row; there is nothing to review."
        )
    reviewable = {(r["cik"], r["accession"]) for r in release_rows}

    validator = Draft202012Validator(_load_schema(root, DECISION_SCHEMA),
                                     format_checker=FormatChecker())
    seen: dict[tuple[str, str], dict] = {}
    records: list[dict] = []
    evidence_items = 0
    for index, supplied in enumerate(decisions, start=1):
        if not isinstance(supplied, dict):
            raise ScreenInputError(f"Ledger entry {index} is not an object.")
        record = dict(supplied)
        record.setdefault("decision_contract", DECISION_CONTRACT)
        record.setdefault("release_id", release["release_id"])
        record.setdefault("release_manifest_sha256", release_sha)
        errors = sorted(validator.iter_errors(record), key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Ledger entry {index} violates {DECISION_CONTRACT} at "
                f"{errors[0].json_path}: {errors[0].message}"
            )
        if record["release_id"] != release["release_id"]:
            raise ScreenInputError(
                f"Ledger entry {index} reviews release "
                f"{record['release_id']!r}, not {release['release_id']!r}."
            )
        if record["release_manifest_sha256"] != release_sha:
            raise ScreenInputError(
                f"Ledger entry {index} pins a different release manifest digest."
            )
        key = (record["cik"], record["accession"])
        if key in seen:
            raise ScreenInputError(
                f"Ledger entry {index} decides {key} a second time; a row is "
                "reviewed once."
            )
        if key not in reviewable:
            raise ScreenInputError(
                f"Ledger entry {index} decides {key}, which is not a row of "
                "this release."
            )
        row = unresolved.get(key)
        if row is None:
            raise ScreenInputError(
                f"Ledger entry {index} decides {key}, which the release did not "
                f"leave {REVIEWABLE_ORIGIN}; only an unresolved row is reviewed."
            )
        for field, actual in (
            ("base_failure_reason_code",
             row["release_provenance"]["base"]["failure_reason_code"]),
            ("repair_failure_reason_code",
             row["release_provenance"]["repair"]["failure_reason_code"]),
        ):
            if record[field] != actual:
                raise ScreenInputError(
                    f"Ledger entry {index} records {field} "
                    f"{record[field]!r}, but the release row carries "
                    f"{actual!r}."
                )
        packet = packets.get(key)
        if packet is None:
            raise ScreenInputError(
                f"Ledger entry {index} decides {key}, which is absent from the "
                "packet cohort; its evidence cannot be resolved."
            )
        if packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError(
                f"Ledger entry {index}: the packet for {key} no longer matches "
                "the digest the release recorded."
            )
        refs = passage_refs(packet)
        bodies = {p["passage_id"]: p["text"] for p in packet["passages"]}
        for position, item in enumerate(record["evidence"], start=1):
            passage_id = refs.get(item["passage_ref"])
            if passage_id is None:
                raise ScreenInputError(
                    f"Ledger entry {index} evidence {position} cites "
                    f"{item['passage_ref']}, which this packet does not display."
                )
            if item["quote"] not in bodies[passage_id]:
                raise ScreenInputError(
                    f"Ledger entry {index} evidence {position}: the quote does "
                    f"not appear verbatim in {item['passage_ref']}."
                )
            evidence_items += 1
        seen[key] = record
        records.append(record)

    missing = sorted(set(unresolved) - set(seen))
    if missing:
        raise ScreenInputError(
            f"{len(missing)} unresolved row(s) carry no decision; coverage must "
            f"be exact. First missing: {missing[0]}."
        )
    # Emitted in release order, so the overlay reads alongside the release.
    order = {key: position for position, key in enumerate(
        (r["cik"], r["accession"]) for r in release_rows)}
    records.sort(key=lambda r: order[(r["cik"], r["accession"])])

    by_decision = {value: sum(r["decision"] == value for r in records)
                   for value in DECISIONS}
    coverage = {
        "unresolved_rows_in_release": len(unresolved),
        "decisions_supplied": len(records),
        "coverage_is_exact": True,
    }
    counts = {
        "decisions": len(records),
        "by_decision": by_decision,
        "evidence_items": evidence_items,
        "reviewers": len({r["reviewer_id"] for r in records}),
        "review_protocol_versions": sorted(
            {r["review_protocol_version"] for r in records}),
    }
    if dry_run:
        return HumanReviewOverlayResult(overlay_id, None, True, "dry_run",
                                        coverage, counts, {})
    decisions_bytes = "".join(_canonical_line(r) + "\n"
                              for r in records).encode("utf-8")
    reconciliation = {
        "every unresolved release row carries exactly one decision": (
            set(seen) == set(unresolved) and len(records) == len(unresolved)),
        "no decision targets a row outside the release": all(
            (r["cik"], r["accession"]) in reviewable for r in records),
        "every decision targets an unresolved row": all(
            (r["cik"], r["accession"]) in unresolved for r in records),
        "no row is decided twice": (
            len({(r["cik"], r["accession"]) for r in records}) == len(records)),
        "every decision names the release it reviewed": all(
            r["release_id"] == release["release_id"]
            and r["release_manifest_sha256"] == release_sha for r in records),
        "every decision carries both prior failure reasons": all(
            r["base_failure_reason_code"] and r["repair_failure_reason_code"]
            for r in records),
        "every decision is evidence-backed": all(r["evidence"] for r in records),
        "every quote resolved verbatim in its cited packet passage": True,
        "every decision names a reviewer, protocol and timestamp": all(
            r["reviewer_id"] and r["review_protocol_version"]
            and r["decision_timestamp"] for r in records),
        "the decision breakdown sums to the decision population": (
            sum(by_decision.values()) == len(records)),
        "decisions are emitted in release row order": (
            [order[(r["cik"], r["accession"])] for r in records]
            == sorted(order[(r["cik"], r["accession"])] for r in records)),
        "the release is byte-unchanged": (
            _sha256(release_manifest_path.read_bytes()) == release_sha),
        "the packet bytes are byte-unchanged": (
            _sha256((root / packet_source["packet_manifest_path"]).read_bytes())
            == packet_source["packet_manifest_sha256"]),
    }
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            f"Overlay reconciliation failed; nothing is written. Failed "
            f"identities: {failed}."
        )
    overlay_dir = create_run_directory(output_dir, overlay_id)
    manifest = {
        "manifest_contract": MANIFEST_CONTRACT,
        "overlay_id": overlay_id,
        "run_timestamp": clock().isoformat(),
        "release": {
            "release_id": release["release_id"],
            "manifest_path": str(release_manifest_path),
            "manifest_sha256": release_sha,
            "records_jsonl_sha256":
                release["output_hashes"][RELEASE_RECORDS_FILENAME],
            "release_unmodified": True,
        },
        "packet_source": packet_source,
        "coverage": coverage,
        "counts": counts,
        "output_contract": DECISION_CONTRACT,
        "output_hashes": {OVERLAY_DECISIONS_FILENAME: _sha256(decisions_bytes)},
        "record_order": RECORD_ORDER,
        "reconciliation": reconciliation,
        "schema_versions": {
            "universe_human_review_decision": "0.1.0",
            "universe_human_review_overlay_manifest": "0.1.0",
            "reviewed_release": release["manifest_contract"],
        },
        "limitations": [
            "A human decision is a separate observation layer. It does not "
            "edit SCREEN_v1, and SCREEN_v1 does not learn of it.",
            "Coverage is exact by construction: a partial review would select "
            "which holes get filled, and that selection would not be neutral.",
            "A LIKELY_INELIGIBLE decision is retained here for audit and "
            "admitted to no downstream cohort.",
            "Human evidence is held to the same verbatim standard as model "
            "evidence, resolved against the base run's own packet bytes.",
            "This overlay records decisions. It makes no claim that a "
            "reviewed row is more accurate than a screened one.",
        ],
    }
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA),
              "Universe human review overlay manifest")
    try:
        write_bytes_once(overlay_dir / OVERLAY_DECISIONS_FILENAME, decisions_bytes,
                         what="human review decisions")
        write_bytes_once(
            overlay_dir / OVERLAY_MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="human review overlay manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return HumanReviewOverlayResult(
        overlay_id, overlay_dir, False, "completed", coverage, counts,
        reconciliation, overlay_dir / OVERLAY_MANIFEST_FILENAME)


def require_human_review_overlay(overlay_dir: str | Path) -> Path:
    """Refuse anything that is not a complete, self-consistent overlay."""
    directory = Path(overlay_dir)
    manifest_path = directory / OVERLAY_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Directory {directory} holds no human-review overlay manifest."
        )
    manifest = json.loads(_decode_utf8(manifest_path.read_bytes(),
                                       OVERLAY_MANIFEST_FILENAME))
    if manifest.get("manifest_contract") != MANIFEST_CONTRACT:
        raise ScreenInputError(
            f"Overlay {directory} declares {manifest.get('manifest_contract')!r}; "
            f"this loader consumes {MANIFEST_CONTRACT!r} only."
        )
    if not manifest["coverage"].get("coverage_is_exact"):
        raise ScreenInputError(
            "The overlay does not claim exact coverage; it may not be consumed."
        )
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file() or _sha256(target.read_bytes()) != recorded:
            raise ScreenInputError(
                f"Overlay output {filename} is missing or no longer hashes to "
                "its manifest entry."
            )
    return manifest_path
