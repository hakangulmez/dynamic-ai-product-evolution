"""Materialize the ten-firm pilot selection, write-once (ADR-137).

:func:`~dynamic_ai_products.classifier_pilot_v1.build_pilot_selection` is pure and
performs no I/O. This module is the only thing that gives it inputs and writes its
output, and it exists separately for that reason: the builder can be reasoned about
and tested without a filesystem, and every question about *which* cohort and *which*
40-row selection the ten came from is answered here, by digest, before the builder
is called.

**Nothing is chosen at the call site.** The ten filings are
``classifier_pilot_v1.PILOT_ROWS`` and this module accepts no row argument of any
kind. A caller can decide where to write and under which selection id, and nothing
else; changing which firms the pilot covers means editing a committed constant.

**The source chain is pinned twice.** The cohort manifest must hash to the digest
named for it, and the 40-row calibration selection must hash to the digest named
for it and declare its own contract. The two are then cross-bound: a selection
drawn from a different cohort than the one presented is refused, so the ten cannot
silently be lifted out of one cohort and described as a subset of another.

**The packet digest is inherited, never re-asserted.** It is read from the pinned
calibration selection rather than accepted as an argument, because that artifact
already carries the packet cohort the rows were drawn against. Taking it as a
parameter would create a second source of truth for the same fact.

Writing is once. A dry run derives the identical selection and writes nothing, so
a selection id stays free for the invocation that will actually claim it.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from .classifier_calibration_selection import require_calibration_selection
from .classifier_candidate_cohort import (
    COHORT_MANIFEST_FILENAME,
    COHORT_RECORDS_FILENAME,
    require_classifier_candidate_cohort,
)
from .classifier_pilot_v1 import (
    PILOT_ROWS,
    PILOT_SELECTION_CONTRACT,
    PILOT_SELECTION_SCHEMA,
    build_pilot_selection,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.lineage_screen import (
    ScreenInputError,
    _decode_utf8,
    _load_schema,
    _sha256,
    _validate,
)

__all__ = [
    "PILOT_ROW_CAP",
    "PILOT_SELECTION_FILENAME",
    "build_pilot_selection_artifact",
    "require_pilot_selection",
]

PILOT_SELECTION_FILENAME = "universe_classifier_pilot_selection.json"

#: The pilot's row count, derived from the committed row list rather than
#: written down. A literal here would keep agreeing with itself while the list
#: changed underneath it; the grant and the runner both bind this value, so the
#: derivation is the one place the number is decided.
PILOT_ROW_CAP: int = len(PILOT_ROWS)


def build_pilot_selection_artifact(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    cohort_manifest_sha256: str, source_selection_path: str | Path,
    source_selection_sha256: str, output_path: str | Path, selection_id: str,
    clock: Callable[[], datetime], dry_run: bool = False,
) -> dict:
    """Derive and write the ten-row pilot selection. No model call, no network."""
    root = Path(repo_root)
    cohort_path = Path(cohort_manifest_path)
    if cohort_path.name != COHORT_MANIFEST_FILENAME:
        raise ScreenInputError(
            f"The cohort manifest must be {COHORT_MANIFEST_FILENAME}; "
            f"{cohort_path.name} is a different artifact.")
    if not cohort_path.is_file():
        raise ScreenInputError(f"Cohort manifest not found: {cohort_path}")
    cohort_raw = cohort_path.read_bytes()
    if _sha256(cohort_raw) != cohort_manifest_sha256:
        raise ScreenInputError(
            f"The cohort manifest hashes to {_sha256(cohort_raw)}, but "
            f"{cohort_manifest_sha256} was pinned; this is not the artifact "
            "that was named.")
    cohort = json.loads(_decode_utf8(cohort_raw, COHORT_MANIFEST_FILENAME))
    require_classifier_candidate_cohort(cohort_path.parent)

    records_raw = (cohort_path.parent / COHORT_RECORDS_FILENAME).read_bytes()
    if _sha256(records_raw) != cohort["output_hashes"][COHORT_RECORDS_FILENAME]:
        raise ScreenInputError(
            f"{COHORT_RECORDS_FILENAME} no longer hashes to the digest its "
            "manifest records; nothing may be read from it.")
    cohort_rows = [json.loads(line) for line
                   in _decode_utf8(records_raw, COHORT_RECORDS_FILENAME).splitlines()
                   if line.strip()]
    if len(cohort_rows) != cohort["counts"]["cohort_rows"]:
        raise ScreenInputError(
            "The cohort's record count disagrees with its manifest.")

    source_path = Path(source_selection_path)
    source = require_calibration_selection(
        source_path, expected_sha256=source_selection_sha256)
    if source["cohort_manifest_sha256"] != cohort_manifest_sha256:
        raise ScreenInputError(
            "The 40-row calibration selection was drawn from a different cohort "
            "than the one presented; the ten could not be described as a subset "
            "of it.")
    if source["cohort_id"] != cohort["cohort_id"]:
        raise ScreenInputError(
            "The calibration selection names a different cohort id than the "
            "cohort manifest does.")

    selection = build_pilot_selection(
        cohort_rows=cohort_rows, source_selection=source,
        source_selection_path=str(source_path),
        source_selection_sha256=source_selection_sha256,
        cohort_manifest_sha256=cohort_manifest_sha256,
        packet_manifest_sha256=source["packet_manifest_sha256"],
        selection_id=selection_id, run_timestamp=clock().isoformat())
    if selection["selection_contract"] != PILOT_SELECTION_CONTRACT:
        raise ScreenInputError(
            "The builder produced a foreign selection contract.")
    if len(selection["rows"]) != PILOT_ROW_CAP:
        raise ScreenInputError(
            f"The pilot selection holds {len(selection['rows'])} row(s); this "
            f"experiment is exactly {PILOT_ROW_CAP}.")
    _validate(selection, _load_schema(root, PILOT_SELECTION_SCHEMA),
              "Pilot selection")
    if dry_run:
        return selection
    payload = (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_bytes_once(target, payload, what="pilot selection")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return selection


def require_pilot_selection(path: str | Path, *, expected_sha256: str) -> dict:
    """Load one pilot selection by digest, refusing anything else.

    The filename gate matters as much as the digest: a calibration selection and
    a pilot selection are both ``*_selection.json`` artifacts over the same
    cohort, and this loader must refuse the wrong one before its contents are
    read rather than after.
    """
    target = Path(path)
    if target.name != PILOT_SELECTION_FILENAME:
        raise ScreenInputError(
            f"A pilot selection must be {PILOT_SELECTION_FILENAME}; "
            f"{target.name} is a different artifact.")
    if not target.is_file():
        raise ScreenInputError(f"Pilot selection not found: {target}")
    raw = target.read_bytes()
    if _sha256(raw) != expected_sha256:
        raise ScreenInputError(
            f"The pilot selection hashes to {_sha256(raw)}, but "
            f"{expected_sha256} was pinned; nothing runs.")
    selection = json.loads(_decode_utf8(raw, PILOT_SELECTION_FILENAME))
    if selection.get("selection_contract") != PILOT_SELECTION_CONTRACT:
        raise ScreenInputError(
            f"The artifact declares {selection.get('selection_contract')!r}; "
            f"this route consumes {PILOT_SELECTION_CONTRACT!r} only.")
    if len(selection.get("rows") or []) != PILOT_ROW_CAP:
        raise ScreenInputError(
            f"The pilot selection holds {len(selection.get('rows') or [])} "
            f"row(s); this route runs exactly {PILOT_ROW_CAP}.")
    return selection
