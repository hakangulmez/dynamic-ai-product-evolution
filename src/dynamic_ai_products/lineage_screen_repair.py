"""Re-ask the rows a completed screen could not verify (ADR-123).

The first complete full-cohort screen validated 6,467 rows and left 574 as
``model_evidence_unverified``: 570 whose evidence quote did not resolve
verbatim inside the passage it cited, three whose ``screen_status`` was outside
the closed vocabulary, and one whose JSON did not parse. Replaying the
committed resolver and the unchanged strict validator over the archived bytes
reproduces all 574 exactly, so the population is a property of the evidence on
disk rather than of the run that produced it.

**Every unverified row is re-asked. No earlier output is edited.** Of the 570
quote failures, 119 cite a passage that does not contain the quote while some
other passage in the same packet contains it verbatim. Rewriting the citation
would close those rows without a model call, and this module deliberately does
not do that: substituting a passage manufactures an attribution no model ever
made, and repairing model output after the fact is exactly what this project
forbids. Those 119 are recorded as measured evidence of a prompt defect and
re-asked like the rest.

**The selection is derived, never authored.** A
``universe_screen_repair_selection@0.1.0`` artifact is built relationally from
one completed continuation-v5 run: its rows are exactly the source records
whose ``record_kind`` is ``model_evidence_unverified``, ascending by source row
ordinal, under the closed rule ``unverified_rows_ascending_ordinal@1``. No CIK,
accession or row count is ever written by hand, and **no status-based filter of
any kind is applied**. The claimed status inside a rejected payload is a
model assertion that failed validation; letting it decide which rows get a
second chance would make selection depend on the outcome being measured. The
consuming runner re-derives the selection from the source bytes at preflight
and refuses any difference, so a doctored selection cannot survive even with a
matching digest chain.

**A repair is a fresh observation, not a correction.** The prompt receives the
packet and nothing else. The earlier status, the earlier quote, the earlier
``passage_ref``, the failure reason and the very fact that this row is being
re-asked are all withheld from the model. Anything else would leak a rejected
output into the observation meant to replace it.

**A narrow prompt successor, bound explicitly.** The repair route runs under
``universe_high_recall_screen_repair.v1.md``, which differs from the committed
V5 screen prompt in exactly two places: a five-step ordering that requires the
model to find the span first and read the reference off the body it copied
from, and a sentence making omission the outcome when no contiguous span
exists. Screening criteria, the status vocabulary, the closed archetype list,
the JSON field structure and the strict validator are byte-identical. The
authorization pins the repair prompt's digest and the manifest records the V5
prompt's digest beside it, so a repair run cannot execute under the screen
prompt and a screen run cannot execute under this one.

**Nothing authoritative moves.** Every prompt, runner, validator, connector,
retry policy and promotion loader is byte-identical and SHA-pinned by the test
suite. This module reuses the adapter, the cohort budget, the V5 diagnostic
renderer and resolver, and the unchanged ``_validate_row_output``; what it adds
is a selection authority, a run kind, and repair-named outputs that the
authoritative, promotion, diagnostic, diagnostic-repair and continuation
loaders all refuse structurally.

**Structurally non-promotable, and deliberately so.** A repair run measures
whether a strengthened evidence-binding prompt recovers rows that failed
verbatim validation. It is not a screen release: ``promotable`` is false in
both the grant and the manifest, its outputs carry repair-only filenames, and
no reconciled release is produced here. Joining a base run to a repair run is a
separate decision with its own loader, taken after this measurement is read.

**One tolerance, and no others.** A row that fails validation again is recorded
as ``model_evidence_unverified`` and counted, up to the grant's
``max_repair_unverified``; above it the run stops fail-closed. Provider
failures are **not** tolerated on this route: ADR-121's provider-unresolved and
ADR-122's truncated-output outcomes belong to the cohort runners, where losing
a run costs thousands of rows. A repair run is small enough that a provider
stop is cheaper to re-authorize than to absorb, and silently importing those
tolerances would widen a threshold this ADR did not measure.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.extraction.provider_adapter import client_contract_digest
from dynamic_ai_products.providers.client_contract_v2 import (
    CLIENT_CONTRACT_V2_ID,
    build_client_contract_v2,
    build_operation_endpoints,
)
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.retry_policy import (
    RATE_LIMIT_POLICY_VERSION,
    RETRY_POLICY_VERSION,
)
from dynamic_ai_products.providers.screen_count_retry_policy import (
    SCREEN_COUNT_MAX_ATTEMPTS_V2,
    SCREEN_COUNT_RETRY_POLICY_VERSION,
    SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2,
    screen_count_attempt_cap,
    screen_external_request_cap_v2,
)
from dynamic_ai_products.providers.screen_retry_policy import (
    SCREEN_GENERATE_MAX_ATTEMPTS,
    SCREEN_GENERATE_RETRY_POLICY_VERSION,
    screen_generate_attempt_cap,
)
from dynamic_ai_products.providers.vertex_gemini_screen_v6 import (
    SCREEN_CONNECTOR_V6_ID,
    VertexGeminiScreenV6,
)
from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

from .lineage_screen_continuation_v5 import (
    CONTINUATION_V5_MANIFEST_FILENAME,
    CONTINUATION_V5_RECORDS_FILENAME,
    require_continuation_v5_run,
)
from .lineage_screen_diagnostic import (
    render_diagnostic_prompt_with_citation_refs,
    resolve_diagnostic_citation_refs,
)
from .lineage_screen_live import (
    CAPTURE_LEDGER_FILENAME,
    CAPTURES_DIRNAME,
    ENABLEMENT_SCHEMA_RELATIVE_PATH,
    ENVELOPE_TEXT_EXTRACTION_RULE,
    VertexLineageScreenProvider,
    _hydrate_pinned,
    _parse_moment,
)
from .lineage_screen_live_v3 import ScreenCohortBudgetV3
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    FAILURE_RECEIPT_FILENAME,
    RAW_RESPONSES_FILENAME,
    SCREEN_STATUSES,
    ScreenInputError,
    ScreenProviderTerminalError,
    ScreenRunResult,
    _canonical_line,
    _decode_utf8,
    _load_schema,
    _RowValidationFailure,
    _RUN_ID_RE,
    _sha256,
    _validate,
    _validate_row_output,
    load_packet_run,
)

__all__ = [
    "REPAIR_MANIFEST_FILENAME",
    "REPAIR_RECORDS_FILENAME",
    "REPAIR_SELECTION_FILENAME",
    "build_repair_selection",
    "load_repair_selection",
    "require_repair_run",
    "run_lineage_screen_repair",
]

# --- Filenames, contracts and the closed derivation rule -------------------------

#: Repair-only names. The authoritative loader looks for
#: ``universe_screen_manifest.json``, the continuation-v5 loader for
#: ``universe_screen_continuation_v5_manifest.json`` and the diagnostic-repair
#: loader for its own; a repair run carries none of them, so every one of them
#: refuses this directory with no change on its side.
REPAIR_RECORDS_FILENAME = "universe_screen_repair_records.jsonl"
REPAIR_MANIFEST_FILENAME = "universe_screen_repair_manifest.json"
REPAIR_SELECTION_FILENAME = "universe_screen_repair_selection.json"

SELECTION_CONTRACT = "universe_screen_repair_selection@0.1.0"
AUTHORIZATION_CONTRACT = "universe_screen_repair_authorization@0.1.0"
MANIFEST_CONTRACT = "universe_screen_repair_manifest@0.1.0"
RECORD_CONTRACT = "universe_screen_record@0.6.0"
RUN_KIND = "unverified_repair"
SELECTION_KIND = "unverified_repair"
SCREEN_STAGE = "universe_high_recall_screen"
RECORD_ORDER = "selection_row_order"

#: The one closed rule the rows are derived under. Population: every
#: ``model_evidence_unverified`` record. Order: ascending source row ordinal.
#: Count: whatever the source contains, derived and never authored.
DERIVATION_RULE = "unverified_rows_ascending_ordinal@1"
SOURCE_RECORD_KIND = "model_evidence_unverified"

#: The row kind this route re-asks, and the closed set of reasons it may carry.
SOURCE_FAILURE_REASONS = (
    "quote_resolution_failure",
    "adapter_rejection",
    "invalid_model_json",
    "temporal_violation",
)

#: The narrow prompt successor this route runs under, and the authoritative
#: screen prompt it must never run under. Both are recorded in the manifest.
REPAIR_PROMPT_PATH = "prompts/discovery/universe_high_recall_screen_repair.v1.md"
SCREEN_PROMPT_PATH = "prompts/discovery/universe_high_recall_screen.v5.md"

SELECTION_SCHEMA = "schemas/universe_screen_repair_selection.schema.json"
AUTHORIZATION_SCHEMA = "schemas/universe_screen_repair_authorization.schema.json"
MANIFEST_SCHEMA = "schemas/universe_screen_repair_manifest.schema.json"
RECORD_SCHEMA = "schemas/universe_screen_record.v6.schema.json"
SOURCE_MANIFEST_SCHEMA = (
    "schemas/universe_screen_continuation_manifest.v5.schema.json"
)

#: The closed hard-stop vocabulary this route writes into a failure receipt.
RECEIPT_CONTRACT = "universe_screen_failure_receipt@0.1.0"
RECEIPT_REASON_CODES = ("provider_error", "repair_unverified_budget_exhausted")

_DETAIL_LIMIT = 400


def _detail(text: str) -> str:
    return text if len(text) <= _DETAIL_LIMIT else text[:_DETAIL_LIMIT - 1] + "…"


# --- Stage 1: relational derivation from one completed screen ----------------------


def _derive_repair_rows(repo_root: Path, source_manifest_path: str | Path) -> dict:
    """Derive the repair population from one completed continuation-v5 run.

    Everything is read from the source's own bytes: its manifest is validated
    against the committed contract, every output file re-hashes to
    ``output_hashes``, the five-population partition is re-proved, and only then
    are the unverified rows taken in source order. A receipt-bearing, foreign,
    tampered or non-partitioning source is refused before anything is derived.
    """
    source_manifest_path = Path(source_manifest_path)
    if not source_manifest_path.is_file():
        raise ScreenInputError(
            f"Source screen manifest not found: {source_manifest_path}"
        )
    if source_manifest_path.name != CONTINUATION_V5_MANIFEST_FILENAME:
        raise ScreenInputError(
            f"Source manifest must be {CONTINUATION_V5_MANIFEST_FILENAME}; "
            f"{source_manifest_path.name} is a different run kind and this "
            "route derives from a completed continuation-v5 screen only."
        )
    source_dir = source_manifest_path.parent
    # Refuses a receipt-bearing directory and re-hashes every declared output.
    require_continuation_v5_run(source_dir)

    manifest_raw = source_manifest_path.read_bytes()
    manifest = json.loads(_decode_utf8(manifest_raw, source_manifest_path.name))
    _validate(manifest, _load_schema(repo_root, SOURCE_MANIFEST_SCHEMA),
              "Source continuation v5 manifest")
    # A continuation manifest carries no promotable flag; authority comes from
    # require_continuation_v5_run above plus a full-cohort selection here.
    if manifest["selection"].get("sampling_algorithm") != "full_cohort@1":
        raise ScreenInputError(
            "The source was screened under sampling algorithm "
            f"{manifest['selection'].get('sampling_algorithm')!r}; a repair "
            "population is derived from a full-cohort screen only."
        )
    if not all(manifest["reconciliation"].values()):
        raise ScreenInputError(
            "The source manifest carries a false reconciliation identity; its "
            "own accounting does not close and no population may be derived."
        )

    records_path = source_dir / CONTINUATION_V5_RECORDS_FILENAME
    records_raw = records_path.read_bytes()
    archive_path = source_dir / RAW_RESPONSES_FILENAME
    archive_raw = archive_path.read_bytes()
    rows = [json.loads(line) for line
            in _decode_utf8(records_raw, CONTINUATION_V5_RECORDS_FILENAME).splitlines()
            if line.strip()]
    counts = manifest["counts"]
    if len(rows) != counts["planned_rows"]:
        raise ScreenInputError(
            f"The source holds {len(rows)} records but declares "
            f"{counts['planned_rows']} planned rows; its partition is not "
            "trustworthy and no population may be derived from it."
        )
    populations = ("screened_packets", "model_evidence_unverified",
                   "insufficient_evidence", "provider_unresolved",
                   "model_output_truncated")
    if sum(counts[name] for name in populations) != counts["planned_rows"]:
        raise ScreenInputError(
            "The source's five populations do not sum to its planned rows."
        )

    archive = {}
    for line in _decode_utf8(archive_raw, RAW_RESPONSES_FILENAME).splitlines():
        if line.strip():
            entry = json.loads(line)
            archive[entry["raw_response_id"]] = entry

    selected: list[dict] = []
    for ordinal, row in enumerate(rows, start=1):
        if row["record_kind"] != SOURCE_RECORD_KIND:
            continue
        reason = row["failure_reason_code"]
        if reason not in SOURCE_FAILURE_REASONS:
            raise ScreenInputError(
                f"Source row {ordinal} carries unverified reason {reason!r}, "
                "which is outside the closed set this route re-asks."
            )
        if row["screen_status"] is not None or row["screen_output"] is not None:
            raise ScreenInputError(
                f"Source row {ordinal} is unverified yet carries a status or "
                "output; the source partition is not trustworthy."
            )
        entry = archive.get(row["raw_response_id"])
        if entry is None:
            raise ScreenInputError(
                f"Source row {ordinal} names raw response "
                f"{row['raw_response_id']!r}, which its archive does not hold."
            )
        if _sha256(entry["raw_response"].encode("utf-8")) != row["raw_response_sha256"]:
            raise ScreenInputError(
                f"Source raw response {row['raw_response_id']} no longer "
                "matches its recorded digest; the archive has drifted."
            )
        selected.append({
            "selection_ordinal": len(selected) + 1,
            "source_row_ordinal": ordinal,
            "cik": row["cik"],
            "accession": row["accession"],
            "packet_sha256": row["packet_sha256"],
            "source_failure_reason_code": reason,
            "source_raw_response_id": row["raw_response_id"],
            "source_raw_response_sha256": row["raw_response_sha256"],
        })
    if len(selected) != counts["model_evidence_unverified"]:
        raise ScreenInputError(
            f"Derived {len(selected)} unverified rows but the source manifest "
            f"declares {counts['model_evidence_unverified']}; the derivation "
            "and the source disagree."
        )
    if not selected:
        raise ScreenInputError(
            "The source screen left no unverified row; there is nothing to "
            "repair and no selection is written."
        )
    ordinals = [row["source_row_ordinal"] for row in selected]
    if ordinals != sorted(ordinals) or len(set(ordinals)) != len(ordinals):
        raise ScreenInputError(
            "The derived rows are not strictly ascending by source ordinal."
        )
    by_reason: dict[str, int] = {}
    for row in selected:
        key = row["source_failure_reason_code"]
        by_reason[key] = by_reason.get(key, 0) + 1
    return {
        "source_run_id": manifest["run_id"],
        "source_manifest_path": str(source_manifest_path),
        "source_manifest_sha256": _sha256(manifest_raw),
        "source_records_jsonl_sha256": _sha256(records_raw),
        "source_raw_responses_jsonl_sha256": _sha256(archive_raw),
        "packet_manifest_path": manifest["packet_manifest_path"],
        "packet_manifest_sha256": manifest["packet_manifest_sha256"],
        "rows": selected,
        "counts": {
            "selected_rows": len(selected),
            "source_cohort_rows": counts["cohort_rows"],
            "source_planned_rows": counts["planned_rows"],
            "by_source_failure_reason": by_reason,
        },
    }


def build_repair_selection(
    *,
    repo_root: str | Path,
    source_manifest_path: str | Path,
    output_path: str | Path,
    selection_id: str,
    clock: Callable[[], datetime],
) -> dict:
    """Derive and write one repair selection, write-once. No model call."""
    root = Path(repo_root)
    derived = _derive_repair_rows(root, source_manifest_path)
    selection = {
        "selection_contract": SELECTION_CONTRACT,
        "selection_id": selection_id,
        "selection_kind": SELECTION_KIND,
        "derivation_rule": DERIVATION_RULE,
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "Every unverified row is re-asked; no earlier model output is "
            "edited, re-attributed or repaired in place.",
            "No status-based filter is applied: the claimed status inside a "
            "rejected payload failed validation and may not select rows.",
            "A repair run is a measurement. Its outputs are structurally "
            "non-promotable and no SCREEN release may be built from them.",
        ],
        **derived,
    }
    _validate(selection, _load_schema(root, SELECTION_SCHEMA),
              "Universe screen repair selection")
    payload = (json.dumps(selection, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        write_bytes_once(Path(output_path), payload, what="repair selection")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return selection


def load_repair_selection(
    repo_root: str | Path, selection_path: str | Path
) -> tuple[dict, str]:
    """Load and validate a repair selection, returning it with its digest."""
    raw = Path(selection_path).read_bytes()
    selection = json.loads(_decode_utf8(raw, Path(selection_path).name))
    _validate(selection, _load_schema(Path(repo_root), SELECTION_SCHEMA),
              "Universe screen repair selection")
    if selection["selection_contract"] != SELECTION_CONTRACT:
        raise ScreenInputError(
            f"Selection declares {selection['selection_contract']!r}; this "
            f"route consumes {SELECTION_CONTRACT!r} only."
        )
    return selection, _sha256(raw)


def require_repair_run(run_dir: str | Path) -> Path:
    """Refuse any repair run that is not completed and self-consistent."""
    directory = Path(run_dir)
    if (directory / FAILURE_RECEIPT_FILENAME).exists():
        raise ScreenInputError(
            f"Repair run {directory} holds a failure receipt; it is "
            "non-authoritative and may not be consumed."
        )
    manifest_path = directory / REPAIR_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Repair run {directory} has no repair manifest."
        )
    manifest = json.loads(_decode_utf8(manifest_path.read_bytes(),
                                       REPAIR_MANIFEST_FILENAME))
    if manifest.get("manifest_contract") != MANIFEST_CONTRACT:
        raise ScreenInputError(
            f"Repair run {directory} declares "
            f"{manifest.get('manifest_contract')!r}; this loader consumes "
            f"{MANIFEST_CONTRACT!r} only."
        )
    if manifest.get("promotable", True):
        raise ScreenInputError(
            "A repair manifest may never be promotable; this one claims to be."
        )
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file() or _sha256(target.read_bytes()) != recorded:
            raise ScreenInputError(
                f"Repair output {filename} is missing or no longer hashes to "
                "its manifest entry."
            )
    return manifest_path


# --- Stage 2: the repair run --------------------------------------------------------


@dataclass
class _RepairPreflight:
    authorization: dict
    enablement: dict
    contract_digest: str
    endpoints: dict
    prompt_text: str
    prompt_sha256: str
    screen_prompt_sha256: str
    inputs: Any
    selection: dict
    selection_sha256: str
    packets: list[dict]
    rows: list[dict]
    model_route: dict


def _repair_preflight(
    *,
    root: Path,
    packet_manifest_path: str | Path,
    selection_artifact_path: str | Path,
    source_manifest_path: str | Path,
    governance_root: Path,
    authorization_reference: str,
    authorization_sha256: str,
    clock: Callable[[], datetime],
) -> _RepairPreflight:
    """Everything provable, proven, before any output or network exists."""
    authorization, _ = _hydrate_pinned(
        governance_root, authorization_reference, authorization_sha256,
        "screen repair authorization",
    )
    _validate(authorization, _load_schema(root, AUTHORIZATION_SCHEMA),
              "Screen repair authorization")
    if authorization["authorization_contract"] != AUTHORIZATION_CONTRACT:
        raise ScreenInputError(
            f"The grant declares {authorization['authorization_contract']!r}; "
            f"this route consumes {AUTHORIZATION_CONTRACT!r} only."
        )
    if authorization["run_kind"] != RUN_KIND:
        raise ScreenInputError(
            f"The grant authorizes {authorization['run_kind']!r}; this route "
            f"runs {RUN_KIND!r} only."
        )
    enablement, _ = _hydrate_pinned(
        governance_root,
        authorization["screen_adapter_enablement_reference"],
        authorization["screen_adapter_enablement_sha256"],
        "screen adapter enablement",
    )
    _validate(enablement, _load_schema(root, ENABLEMENT_SCHEMA_RELATIVE_PATH),
              "Screen adapter enablement")
    now = clock()
    for label, artifact in (("authorization", authorization),
                            ("enablement", enablement)):
        if not (
            _parse_moment(artifact["effective_at"], f"{label} effective_at")
            <= now
            < _parse_moment(artifact["expires_at"], f"{label} expires_at")
        ):
            raise ScreenInputError(
                f"The {label} is outside its effective window; nothing runs."
            )
    contract = build_client_contract_v2(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"],
    )
    digest = client_contract_digest(contract)
    model_route = {"provider": contract["model_provider"],
                   "model_label": contract["model_name"]}
    if (
        authorization["provider_client_contract_reference"] != CLIENT_CONTRACT_V2_ID
        or authorization["provider_client_contract_sha256"] != digest
        or enablement["provider_client_contract_reference"] != CLIENT_CONTRACT_V2_ID
        or enablement["provider_client_contract_sha256"] != digest
    ):
        raise ScreenInputError(
            "Authorization or enablement binds a different provider client contract."
        )
    if (
        authorization["model_route"] != model_route
        or authorization["retry_policy_version"] != RETRY_POLICY_VERSION
        or authorization["rate_limit_policy_version"] != RATE_LIMIT_POLICY_VERSION
        or authorization["screen_generate_retry_policy_version"]
        != SCREEN_GENERATE_RETRY_POLICY_VERSION
        or authorization["screen_count_retry_policy_version"]
        != SCREEN_COUNT_RETRY_POLICY_VERSION
        or authorization["screen_stage"] != SCREEN_STAGE
        or authorization["output_contract"] != RECORD_CONTRACT
        or authorization["count_attempts_per_row"] != SCREEN_COUNT_MAX_ATTEMPTS_V2
        or authorization["generate_attempts_per_row"] != SCREEN_GENERATE_MAX_ATTEMPTS
        or authorization["external_requests_per_row"]
        != SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2
    ):
        raise ScreenInputError(
            "Authorization route, policy versions or per-row ceilings do not "
            "match the committed ones."
        )
    if authorization["promotable"] is not False:
        raise ScreenInputError(
            "A repair grant may never be promotable; this one claims to be."
        )
    endpoints = build_operation_endpoints(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"],
    )
    if set(authorization["endpoint_allowlist"]) != set(endpoints.values()) or set(
        enablement["endpoint_allowlist"]
    ) != set(endpoints.values()):
        raise ScreenInputError(
            "Authorization/enablement endpoint allowlists are not exactly the "
            "derived operation endpoints."
        )
    # The repair prompt, and proof the screen prompt is not the one running.
    if authorization["prompt_template_path"] != REPAIR_PROMPT_PATH:
        raise ScreenInputError(
            f"The grant binds prompt {authorization['prompt_template_path']!r}; "
            f"this route runs {REPAIR_PROMPT_PATH!r} only."
        )
    prompt_raw = (root / REPAIR_PROMPT_PATH).read_bytes()
    prompt_sha = _sha256(prompt_raw)
    if prompt_sha != authorization["prompt_template_sha256"]:
        raise ScreenInputError(
            "Authorization does not bind the committed repair prompt bytes."
        )
    screen_prompt_sha = _sha256((root / SCREEN_PROMPT_PATH).read_bytes())
    if screen_prompt_sha == prompt_sha:
        raise ScreenInputError(
            "The repair prompt and the screen prompt hash identically; the "
            "repair route would be indistinguishable from the screen."
        )
    inputs = load_packet_run(root, packet_manifest_path)
    if inputs.manifest_sha256 != authorization["packet_manifest_sha256"]:
        raise ScreenInputError("Authorization binds a different packet cohort.")

    selection, selection_sha = load_repair_selection(root, selection_artifact_path)
    if selection_sha != authorization["selection_artifact_sha256"]:
        raise ScreenInputError(
            "Authorization binds a different repair selection artifact."
        )
    if selection["selection_kind"] != authorization["selection_kind"]:
        raise ScreenInputError("Selection kind and authorization disagree.")
    if selection["source_run_id"] != authorization["source_run_id"]:
        raise ScreenInputError(
            f"The selection was derived from {selection['source_run_id']!r} but "
            f"the grant names {authorization['source_run_id']!r}."
        )
    # Re-derive from the source bytes: a doctored selection cannot survive a
    # matching digest chain, because the rows themselves are recomputed here.
    rederived = _derive_repair_rows(root, source_manifest_path)
    # source_manifest_path is deliberately absent: the same run may be named
    # by a different but equivalent path, and the digests below are the proof.
    for field_name in ("source_run_id", "source_manifest_sha256",
                       "source_records_jsonl_sha256",
                       "source_raw_responses_jsonl_sha256",
                       "packet_manifest_sha256", "rows", "counts"):
        if rederived[field_name] != selection[field_name]:
            raise ScreenInputError(
                f"The selection's {field_name} does not match the value "
                "re-derived from the source run's own bytes."
            )
    rows = selection["rows"]
    if authorization["logical_row_cap"] != len(rows):
        raise ScreenInputError(
            f"The grant authorizes {authorization['logical_row_cap']} rows but "
            f"the selection derives {len(rows)}."
        )
    if authorization["count_attempt_cap"] != screen_count_attempt_cap(len(rows)):
        raise ScreenInputError(
            f"count_attempt_cap must be exactly {screen_count_attempt_cap(len(rows))}."
        )
    if authorization["provider_attempt_cap"] != screen_generate_attempt_cap(len(rows)):
        raise ScreenInputError(
            f"provider_attempt_cap must be exactly "
            f"{screen_generate_attempt_cap(len(rows))}."
        )
    if authorization["budget_max_external_requests"] != screen_external_request_cap_v2(
        len(rows)
    ):
        raise ScreenInputError(
            f"budget_max_external_requests must be exactly "
            f"{screen_external_request_cap_v2(len(rows))}."
        )
    if not 1 <= authorization["max_repair_unverified"] <= len(rows):
        raise ScreenInputError(
            "max_repair_unverified must lie between 1 and the selected row "
            "count; an unbounded repair measures nothing."
        )
    packets = {(p["cik"], p["accession"]): p for p in inputs.packets}
    ordered: list[dict] = []
    for row in rows:
        key = (row["cik"], row["accession"])
        packet = packets.get(key)
        if packet is None:
            raise ScreenInputError(
                f"Selected row {key} is absent from the packet cohort."
            )
        if packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError(
                f"Selected row {key} no longer matches its recorded packet "
                "digest; the cohort has moved beneath the selection."
            )
        ordered.append(packet)
    return _RepairPreflight(
        authorization=authorization, enablement=enablement, contract_digest=digest,
        endpoints=endpoints,
        prompt_text=_decode_utf8(prompt_raw, "repair prompt"),
        prompt_sha256=prompt_sha, screen_prompt_sha256=screen_prompt_sha,
        inputs=inputs, selection=selection, selection_sha256=selection_sha,
        packets=ordered, rows=rows, model_route=model_route,
    )


def run_lineage_screen_repair(
    *,
    repo_root: str | Path,
    packet_manifest_path: str | Path,
    selection_artifact_path: str | Path,
    source_manifest_path: str | Path,
    governance_root: str | Path,
    authorization_reference: str,
    authorization_sha256: str,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
    client_factory: Any = None,
    sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    """Re-ask every selected unverified row under the repair prompt."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError("Invalid run id.")
    pre = _repair_preflight(
        root=root, packet_manifest_path=packet_manifest_path,
        selection_artifact_path=selection_artifact_path,
        source_manifest_path=source_manifest_path,
        governance_root=Path(governance_root),
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256, clock=clock,
    )
    if dry_run:
        for packet in pre.packets:
            render_diagnostic_prompt_with_citation_refs(pre.prompt_text, packet)
        return ScreenRunResult(
            run_id, None, True, "dry_run", len(pre.packets), 0,
            request_accounting={
                "logical_row_cap": len(pre.packets),
                "count_attempt_cap": pre.authorization["count_attempt_cap"],
                "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
                "external_request_cap": pre.authorization["budget_max_external_requests"],
            },
        )
    connector = VertexGeminiScreenV6(
        vertex_project=pre.authorization["vertex_project"],
        vertex_location=pre.authorization["vertex_location"],
        expected_authorization_sha256=authorization_sha256,
        max_provider_requests=SCREEN_GENERATE_MAX_ATTEMPTS,
        endpoint_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
        client_factory=client_factory, sleep=sleep,
    )
    try:
        connector.assert_run_permitted(
            authorization_sha256=authorization_sha256,
            endpoint_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
            enablement_endpoint_allowlist=tuple(pre.enablement["endpoint_allowlist"]),
        )
    except ProviderError as exc:
        raise ScreenInputError(
            f"Connector handshake refused: {exc.reason_code}."
        ) from exc
    finally:
        connector.revoke_run_permission()

    run_dir = create_run_directory(output_dir, run_id)
    result = ScreenRunResult(run_id, run_dir, False, "failed", len(pre.packets), 0)
    budget = ScreenCohortBudgetV3(
        authorization=pre.authorization, authorization_sha256=authorization_sha256,
        run_id=run_id, clock=clock,
    )
    ledger: list[dict] = []
    adapter = VertexLineageScreenProvider(
        connector=connector, authorization_sha256=authorization_sha256,
        authorization_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
        enablement_allowlist=tuple(pre.enablement["endpoint_allowlist"]),
        run_dir=run_dir, budget=budget,
        packet_sha_by_key={(p["cik"], p["accession"]): p["packet_sha256"]
                           for p in pre.packets},
        prompt_template_sha256=pre.prompt_sha256, ledger=ledger,
    )
    archive_path = run_dir / RAW_RESPONSES_FILENAME
    archive = os.fdopen(
        os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), "wb")
    records: list[dict] = []
    still_unverified: dict[str, int] = {}
    recovered_by_reason: dict[str, int] = {}
    called_rows = count_attempts_made = generate_attempts_made = 0
    rows_count_retried = rows_generate_retried = 0

    def fail(reason: str, detail: str, packet: dict) -> ScreenRunResult:
        archive.flush()
        os.fsync(archive.fileno())
        archive.close()
        generates = sum(e["operation_label"] == "generate_content" for e in ledger)
        receipt = {
            "receipt_contract": RECEIPT_CONTRACT,
            "run_id": run_id,
            "run_kind": RUN_KIND,
            "reason_code": reason,
            "detail": _detail(detail),
            "stopping_cik": packet["cik"],
            "stopping_accession": packet["accession"],
            "stopping_row_index": len(records) + 1,
            "records_completed_before_failure": len(records),
            "model_called_rows_attempted": called_rows,
            "external_requests_made": len(ledger),
            "count_attempts_made": len(ledger) - generates,
            "provider_attempts_made": generates,
            "still_unverified_rows": sum(still_unverified.values()),
            "max_repair_unverified": pre.authorization["max_repair_unverified"],
            "authorization_sha256": authorization_sha256,
            "selection_artifact_sha256": pre.selection_sha256,
            "source_run_id": pre.selection["source_run_id"],
            "run_timestamp": clock().isoformat(),
            "retention_note": (
                "Non-authoritative repair run: no records JSONL, no capture "
                "ledger and no manifest exist here. The source screen it was "
                "derived from is untouched and remains the authority. This "
                "directory is immutable; a further attempt requires a new run "
                "id and a new authorization."
            ),
        }
        try:
            write_bytes_once(
                run_dir / FAILURE_RECEIPT_FILENAME,
                (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                what="repair failure receipt")
        except WriteOnceError as exc:
            raise ScreenInputError(str(exc)) from exc
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        result.receipt = receipt
        return result

    for packet, row in zip(pre.packets, pre.rows):
        # The packet only. No earlier status, quote, passage_ref, failure
        # reason or retry identity reaches the model: a repair is a fresh
        # observation, not a correction of one it can see.
        rendered, refs = render_diagnostic_prompt_with_citation_refs(
            pre.prompt_text, packet)
        called_rows += 1
        before = len(ledger)
        try:
            raw = adapter.screen(rendered, cik=packet["cik"],
                                 accession=packet["accession"])
        except ScreenProviderTerminalError as exc:
            spent = ledger[before:]
            count_attempts_made += sum(
                e["operation_label"] == "count_tokens" for e in spent)
            generate_attempts_made += sum(
                e["operation_label"] == "generate_content" for e in spent)
            # A repair run is small: a provider stop is cheaper to re-authorize
            # than to absorb, so no provider tolerance is imported here.
            return fail("provider_error", str(exc), packet)
        spent = ledger[before:]
        row_counts = sum(e["operation_label"] == "count_tokens" for e in spent)
        row_generates = sum(e["operation_label"] == "generate_content" for e in spent)
        count_attempts_made += row_counts
        generate_attempts_made += row_generates
        if row_counts > 1:
            rows_count_retried += 1
        if row_generates > 1:
            rows_generate_retried += 1
        if count_attempts_made > pre.authorization["count_attempt_cap"]:
            return fail("provider_error", "countTokens attempt cap exceeded.", packet)
        if generate_attempts_made > pre.authorization["provider_attempt_cap"]:
            return fail("provider_error", "Provider attempt cap exceeded.", packet)
        raw_sha = _sha256(raw.encode("utf-8"))
        response_id = f"{run_id}-{packet['cik']}-{packet['accession']}"
        archive.write((_canonical_line({
            "raw_response_id": response_id, "cik": packet["cik"],
            "accession": packet["accession"], "raw_response": raw,
            "raw_response_sha256": raw_sha,
        }) + "\n").encode("utf-8"))
        archive.flush()
        os.fsync(archive.fileno())
        base = {
            "record_contract": RECORD_CONTRACT, "cik": packet["cik"],
            "company_id": packet["company_id"], "accession": packet["accession"],
            "form": packet["form"],
            "baseline_filing_date": packet["baseline_filing_date"],
            "source_id": packet["source_id"],
            "packet_sha256": packet["packet_sha256"],
            "prompt_sha256": _sha256(rendered.encode("utf-8")),
            "model_route": dict(adapter.model_route),
            "raw_response_id": response_id, "raw_response_sha256": raw_sha,
            "provider_attempt_telemetry": None,
            "truncation_evidence": None,
            "row_provenance": {
                "origin": "model_called", "source_run_id": None,
                "source_raw_response_id": None,
                "source_raw_responses_sha256": None, "source_receipt_sha256": None,
            },
            "repair_provenance": {
                "source_run_id": pre.selection["source_run_id"],
                "source_record_kind": SOURCE_RECORD_KIND,
                "source_failure_reason_code": row["source_failure_reason_code"],
                "source_raw_response_id": row["source_raw_response_id"],
                "source_raw_response_sha256": row["source_raw_response_sha256"],
                "source_row_ordinal": row["source_row_ordinal"],
            },
        }
        try:
            output = _validate_row_output(
                resolve_diagnostic_citation_refs(raw, refs, packet), packet)
        except _RowValidationFailure as exc:
            still_unverified[exc.reason_code] = still_unverified.get(
                exc.reason_code, 0) + 1
            base.update(record_kind="model_evidence_unverified", screen_status=None,
                        screen_output=None, failure_reason_code=exc.reason_code,
                        failure_detail=_detail(exc.detail))
            if sum(still_unverified.values()) > pre.authorization[
                "max_repair_unverified"
            ]:
                records.append(base)
                return fail(
                    "repair_unverified_budget_exhausted",
                    "The authorized repair-unverified tolerance was exceeded.",
                    packet)
        else:
            reason = row["source_failure_reason_code"]
            recovered_by_reason[reason] = recovered_by_reason.get(reason, 0) + 1
            base.update(record_kind="screened_packet",
                        screen_status=output.screen_status,
                        screen_output=output.model_dump(mode="json"),
                        failure_reason_code=None, failure_detail=None)
        records.append(base)
    archive.flush()
    os.fsync(archive.fileno())
    archive.close()

    validator = Draft202012Validator(_load_schema(root, RECORD_SCHEMA),
                                     format_checker=FormatChecker())
    for record in records:
        errors = sorted(validator.iter_errors(record), key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Built repair record violates {RECORD_CONTRACT} at "
                f"{errors[0].json_path}: {errors[0].message}"
            )
    ledger_bytes = "".join(_canonical_line(e) + "\n" for e in ledger).encode("utf-8")
    records_bytes = "".join(_canonical_line(r) + "\n" for r in records).encode("utf-8")
    try:
        write_bytes_once(run_dir / CAPTURE_LEDGER_FILENAME, ledger_bytes,
                         what="repair capture ledger")
        write_bytes_once(run_dir / REPAIR_RECORDS_FILENAME, records_bytes,
                         what="repair records")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    archive_raw = archive_path.read_bytes()
    archive_entries = [json.loads(line) for line
                       in _decode_utf8(archive_raw, RAW_RESPONSES_FILENAME).splitlines()
                       if line.strip()]
    repaired = [r for r in records if r["record_kind"] == "screened_packet"]
    unresolved = [r for r in records if r["record_kind"] == SOURCE_RECORD_KIND]
    persisted = [e for e in ledger if e["capture_disposition"] == "raw_persisted"]
    capture_ok = all(
        (run_dir / e["raw_reference"]).is_file()
        and _sha256((run_dir / e["raw_reference"]).read_bytes()) == e["raw_sha256"]
        for e in persisted)
    disk_refs = ({str(p.relative_to(run_dir))
                  for p in (run_dir / CAPTURES_DIRNAME).rglob("*") if p.is_file()}
                 if (run_dir / CAPTURES_DIRNAME).exists() else set())
    source = pre.selection
    counts = {
        "selected_rows": len(pre.rows),
        "repaired_rows": len(repaired),
        "still_unverified_rows": len(unresolved),
        "max_repair_unverified": pre.authorization["max_repair_unverified"],
        "by_screen_status": {s: sum(r["screen_status"] == s for r in repaired)
                             for s in SCREEN_STATUSES},
        "still_unverified_by_reason": dict(still_unverified),
        "recovered_by_source_reason": dict(recovered_by_reason),
    }
    request_accounting = {
        "logical_row_cap": pre.authorization["logical_row_cap"],
        "count_attempt_cap": pre.authorization["count_attempt_cap"],
        "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
        "external_request_cap": pre.authorization["budget_max_external_requests"],
        "count_attempts_made": count_attempts_made,
        "provider_attempts_made": generate_attempts_made,
        "external_requests_made": len(ledger),
        "rows_count_retried": rows_count_retried,
        "rows_generate_retried": rows_generate_retried,
        "tokens_in_measured": budget.tokens_in_measured,
        "tokens_out_reported": budget.tokens_out_reported,
        "rows_usage_verified": budget.rows_usage_verified,
        "cost_micros_settled": budget.cost_micros_settled,
        "budget_max_input_tokens": pre.authorization["budget_max_input_tokens"],
        "budget_max_output_tokens": pre.authorization["budget_max_output_tokens"],
        "budget_max_estimated_cost_micros":
            pre.authorization["budget_max_estimated_cost_micros"],
        "budget_max_wall_clock_seconds":
            pre.authorization["budget_max_wall_clock_seconds"],
    }
    source_dir = Path(source_manifest_path).parent
    reconciliation = {
        "every selected row was re-asked exactly once": (
            len(records) == len(pre.rows) == called_rows),
        "records follow the selection order": (
            [(r["cik"], r["accession"]) for r in records]
            == [(row["cik"], row["accession"]) for row in pre.rows]),
        "repaired and still-unverified rows partition the selection": (
            len(repaired) + len(unresolved) == len(pre.rows)),
        "every row names the unverified observation it re-asks": all(
            r["repair_provenance"]["source_record_kind"] == SOURCE_RECORD_KIND
            and r["repair_provenance"]["source_run_id"] == source["source_run_id"]
            for r in records),
        "every row's source ordinal is the selection's": (
            [r["repair_provenance"]["source_row_ordinal"] for r in records]
            == [row["source_row_ordinal"] for row in pre.rows]),
        "no repaired row carries a failure reason": all(
            r["failure_reason_code"] is None and r["screen_status"] is not None
            for r in repaired),
        "no still-unverified row carries a status or output": all(
            r["screen_status"] is None and r["screen_output"] is None
            for r in unresolved),
        "still-unverified rows stayed within the authorized tolerance": (
            len(unresolved) <= pre.authorization["max_repair_unverified"]),
        "the unverified breakdown sums to the unverified population": (
            sum(still_unverified.values()) == len(unresolved)),
        "the recovery breakdown sums to the repaired population": (
            sum(recovered_by_reason.values()) == len(repaired)),
        "repaired rows are absent from every unverified count": (
            sum(counts["by_screen_status"].values()) == len(repaired)),
        "every row was model-called; none was reused": all(
            r["row_provenance"]["origin"] == "model_called" for r in records),
        "the archive holds one line per re-asked row": (
            len(archive_entries) == len(records)),
        "every record resolves in the archive and re-hashes": all(
            any(e["raw_response_id"] == r["raw_response_id"]
                and _sha256(e["raw_response"].encode("utf-8"))
                == r["raw_response_sha256"] for e in archive_entries)
            for r in records),
        "capture files rehash to their ledger lines": capture_ok,
        "no orphan capture file exists": disk_refs == {
            e["raw_reference"] for e in persisted},
        "count and generate sends partition external requests": (
            count_attempts_made + generate_attempts_made == len(ledger)),
        "no row exceeded its send ceilings": (
            count_attempts_made <= pre.authorization["count_attempt_cap"]
            and generate_attempts_made <= pre.authorization["provider_attempt_cap"]
            and len(ledger) <= pre.authorization["budget_max_external_requests"]),
        "the repair prompt ran, not the screen prompt": (
            pre.prompt_sha256 != pre.screen_prompt_sha256
            and pre.prompt_sha256 == pre.authorization["prompt_template_sha256"]),
        "the source screen is byte-unchanged": (
            _sha256((source_dir / CONTINUATION_V5_MANIFEST_FILENAME).read_bytes())
            == source["source_manifest_sha256"]
            and _sha256((source_dir / CONTINUATION_V5_RECORDS_FILENAME).read_bytes())
            == source["source_records_jsonl_sha256"]
            and _sha256((source_dir / RAW_RESPONSES_FILENAME).read_bytes())
            == source["source_raw_responses_jsonl_sha256"]),
    }
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            "Repair reconciliation failed; no manifest is written. Failed "
            f"identities: {failed}."
        )
    manifest = {
        "manifest_contract": MANIFEST_CONTRACT,
        "run_id": run_id,
        "run_kind": RUN_KIND,
        "run_timestamp": clock().isoformat(),
        "promotable": False,
        "authorization_id": pre.authorization["authorization_id"],
        "authorization_sha256": authorization_sha256,
        "selection": {
            "selection_kind": SELECTION_KIND,
            "selection_artifact_sha256": pre.selection_sha256,
            "derivation_rule": DERIVATION_RULE,
            "selected_rows": len(pre.rows),
            "rederived_at_preflight": True,
        },
        "source": {
            "source_run_id": source["source_run_id"],
            "source_manifest_sha256": source["source_manifest_sha256"],
            "source_records_jsonl_sha256": source["source_records_jsonl_sha256"],
            "source_raw_responses_jsonl_sha256":
                source["source_raw_responses_jsonl_sha256"],
            "source_unmodified": True,
            "earlier_output_withheld_from_prompt": True,
        },
        "prompt_template_path": REPAIR_PROMPT_PATH,
        "prompt_template_sha256": pre.prompt_sha256,
        "screen_prompt_not_used": {"path": SCREEN_PROMPT_PATH,
                                   "sha256": pre.screen_prompt_sha256},
        "packet_manifest_path": str(packet_manifest_path),
        "packet_manifest_sha256": pre.inputs.manifest_sha256,
        "packet_run_id": pre.inputs.manifest["run_id"],
        "provider": dict(pre.model_route),
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": pre.contract_digest,
        "screen_adapter_enablement_sha256":
            pre.authorization["screen_adapter_enablement_sha256"],
        "endpoint_allowlist": sorted(pre.endpoints.values()),
        "envelope_text_extraction_rule": ENVELOPE_TEXT_EXTRACTION_RULE,
        "output_contract": RECORD_CONTRACT,
        "output_hashes": {
            REPAIR_RECORDS_FILENAME: _sha256(records_bytes),
            RAW_RESPONSES_FILENAME: _sha256(archive_raw),
            CAPTURE_LEDGER_FILENAME: _sha256(ledger_bytes),
        },
        "record_order": RECORD_ORDER,
        "counts": counts,
        "request_accounting": request_accounting,
        "reconciliation": reconciliation,
        "schema_versions": {
            "universe_screen_record": "0.6.0",
            "universe_screen_repair_selection": "0.1.0",
            "universe_screen_repair_authorization": "0.1.0",
            "universe_screen_repair_manifest": "0.1.0",
            "screen_connector": SCREEN_CONNECTOR_V6_ID,
        },
        "limitations": [
            "A repair run is a measurement, not a release. It is structurally "
            "non-promotable and no SCREEN release may be built from it.",
            "Rows are re-asked, never edited: no earlier quote, reference or "
            "status was corrected, re-attributed or carried into the prompt.",
            "A row that failed validation again is still unverified. This run "
            "narrows the unverified population; it does not close it.",
            "Provider failures are not tolerated on this route, so a stopped "
            "repair run measures nothing and must be re-authorized.",
            "Reconciling this run with its source screen is a separate "
            "decision with its own loader and is not performed here.",
        ],
    }
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA),
              "Universe screen repair manifest")
    try:
        write_bytes_once(
            run_dir / REPAIR_MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="repair manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    result.status = "completed"
    result.counts = counts
    result.request_accounting = request_accounting
    result.reconciliation = reconciliation
    result.manifest_path = run_dir / REPAIR_MANIFEST_FILENAME
    return result
