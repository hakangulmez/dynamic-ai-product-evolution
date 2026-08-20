"""Seven-row diagnostic repair measurement (ADR-115).

The completed v4 diagnostic canary validated 93 of 100 rows and recorded
seven ``quote_resolution_failure`` rows. ADR-114 shipped the v5 diagnostic
prompt in response — source identity removed from the model-facing contract,
quote discipline stated as a copy operation — but v5 has never faced the
seven filings that actually failed. This module measures exactly that: it
re-screens **only** those seven rows under the committed v5 prompt, so the
next live spend is seven logical requests, not another hundred.

**The seven rows are derived, never authored.** A
``universe_screen_diagnostic_repair_selection@0.1.0`` artifact is built
relationally from one completed source diagnostic run: its rows are exactly
the source records whose ``record_kind`` is ``rejected_output`` with
``rejection_reason_code == quote_resolution_failure``, ascending by source
row ordinal, under the closed rule
``rejected_quote_resolution_rows_ascending_ordinal@1``. No CIK or accession
is ever hard-coded: the builder validates the source manifest and records
against their schemas, re-hashes every source output file, re-proves the
source partition, and refuses a receipt-bearing, tampered, foreign,
incomplete, duplicated or wrong-count source outright. The consuming runner
then **re-derives the selection from the source bytes at preflight** and
refuses any difference, so a doctored selection cannot survive even with a
matching digest chain.

**A third authorization contract, on purpose.** The authoritative live
authorization and the 100-row diagnostic authorization each pin their own
contract const; ``universe_screen_diagnostic_repair_authorization@0.1.0``
pins a third (``run_kind: diagnostic_repair_7``), so none of the three
runners can consume another's grant. The repair arithmetic is schema-pinned:
exactly 7 logical requests, 21 provider attempts, 28 external sends, with a
bounded rejected-row breaker in [1, 7).

**Nothing authoritative moves.** ``lineage_screen_live.py``, the 100-row
diagnostic runner, the shared strict ``_validate_row_output``, every prompt
and every predecessor schema are byte-identical and SHA-pinned by the test
suite. This module reuses the adapter, the cohort budget, the v5 diagnostic
renderer/resolver and the diagnostic record contract; what it adds is a
selection authority, a run-kind, and repair-named outputs
(``universe_screen_diagnostic_repair_records.jsonl`` /
``universe_screen_diagnostic_repair_manifest.json``) that the authoritative,
promotion and standard diagnostic loaders all refuse structurally.
Raw-before-parse, per-line fsync, complete capture accounting and the
fail-closed receipt semantics are unchanged from ADR-112.

This increment ships offline: every test injects a fake client factory; no
real SDK client is built, no credential is resolved, no socket is opened.
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
from dynamic_ai_products.providers.vertex_gemini_v2 import VertexGeminiProviderV2
from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

# Reused unchanged from the 100-row diagnostic route: the v5 renderer and
# resolver, the record contract, the bounded-detail rule and the consumer
# gate for source runs. Importing is not modifying; the diagnostic module
# stays byte-identical and is SHA-pinned by the repair test suite.
from .lineage_screen_diagnostic import (
    DIAGNOSTIC_MANIFEST_FILENAME,
    DIAGNOSTIC_PROMPT_TEMPLATE_RELATIVE_PATH,
    DIAGNOSTIC_RECORDS_FILENAME,
    DiagnosticRunResult,
    RECORD_CONTRACT,
    RECORD_SCHEMA_RELATIVE_PATH,
    REJECTION_REASON_CODES,
    _bounded_detail,
    render_diagnostic_prompt_with_citation_refs,
    require_diagnostic_run,
    resolve_diagnostic_citation_refs,
)

# Reused unchanged from the authoritative live route: adapter, budget,
# governance hydration and envelope extraction.
from .lineage_screen_live import (
    CAPTURE_LEDGER_FILENAME,
    CAPTURES_DIRNAME,
    ENABLEMENT_SCHEMA_RELATIVE_PATH,
    ENVELOPE_TEXT_EXTRACTION_RULE,
    EXTERNAL_REQUESTS_PER_ROW,
    GENERATE_ATTEMPT_CAP_PER_ROW,
    ScreenCohortBudget,
    VertexLineageScreenProvider,
    _extract_envelope_text,
    _hydrate_pinned,
    _parse_moment,
)
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    FAILURE_RECEIPT_FILENAME,
    RAW_RESPONSES_FILENAME,
    SCREEN_MANIFEST_FILENAME,
    SCREEN_STATUSES,
    ScreenInputError,
    ScreenProviderTerminalError,
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
    "REPAIR_ROWS",
    "build_repair_selection",
    "load_repair_selection",
    "require_diagnostic_repair_run",
    "run_lineage_screen_diagnostic_repair",
]

# --- Filenames, contracts and the closed derivation rule -------------------------

#: Repair-specific names. The authoritative loader looks for
#: ``universe_screen_manifest.json`` and the diagnostic loader for
#: ``universe_screen_diagnostic_manifest.json``; a repair run carries neither,
#: so both refuse the directory with no code change on their side.
REPAIR_RECORDS_FILENAME = "universe_screen_diagnostic_repair_records.jsonl"
REPAIR_MANIFEST_FILENAME = "universe_screen_diagnostic_repair_manifest.json"
REPAIR_SELECTION_FILENAME = "universe_screen_diagnostic_repair_selection.json"

REPAIR_SELECTION_CONTRACT = "universe_screen_diagnostic_repair_selection@0.1.0"
REPAIR_AUTHORIZATION_CONTRACT = (
    "universe_screen_diagnostic_repair_authorization@0.1.0"
)
REPAIR_MANIFEST_CONTRACT = "universe_screen_diagnostic_repair_manifest@0.1.0"
REPAIR_RUN_KIND = "diagnostic_repair_7"
REPAIR_SELECTION_KIND = "repair_7"
SCREEN_STAGE = "universe_high_recall_screen"
RECORD_ORDER = "selection_row_order"

#: The one closed rule the seven rows are derived under. Population:
#: ``rejected_output`` with ``quote_resolution_failure``. Order: ascending
#: source row ordinal. Count: exactly seven, or the derivation refuses.
DERIVATION_RULE = "rejected_quote_resolution_rows_ascending_ordinal@1"
REPAIR_ROWS = 7
REPAIR_REASON = "quote_resolution_failure"

REPAIR_SELECTION_SCHEMA_RELATIVE_PATH = (
    "schemas/universe_screen_diagnostic_repair_selection.schema.json"
)
REPAIR_AUTHORIZATION_SCHEMA_RELATIVE_PATH = (
    "schemas/universe_screen_diagnostic_repair_authorization.schema.json"
)
REPAIR_MANIFEST_SCHEMA_RELATIVE_PATH = (
    "schemas/universe_screen_diagnostic_repair_manifest.schema.json"
)

#: Same closed hard-stop vocabulary as the 100-row diagnostic route.
RECEIPT_REASON_CODES = (
    "provider_error",
    "rejected_row_budget_exhausted",
)


# --- Source-run derivation ---------------------------------------------------------


def _derive_repair_rows(repo_root: Path, source_manifest_path: Path) -> dict:
    """Derive the eligible rows from one completed source diagnostic run.

    Fail-closed and purely relational: the source run is admitted through
    :func:`require_diagnostic_run` (which refuses receipts, foreign or
    authoritative manifests, and any output-hash mismatch), its manifest and
    every record are re-validated against their committed schemas, the row
    partition is re-proven, and only then is the closed derivation rule
    applied. Anything other than exactly seven eligible rows refuses.
    """
    source_manifest_path = Path(source_manifest_path)
    if not source_manifest_path.is_file():
        raise ScreenInputError(
            f"Source diagnostic manifest not found: {source_manifest_path}"
        )
    source_dir = source_manifest_path.parent
    if source_manifest_path.name != DIAGNOSTIC_MANIFEST_FILENAME:
        raise ScreenInputError(
            f"The source must be a {DIAGNOSTIC_MANIFEST_FILENAME}; a repair "
            "selection is derived from a completed diagnostic run and from "
            "nothing else."
        )
    # Receipts, foreign contracts, authoritative manifests and output-hash
    # drift are all refused here, before a single record is read.
    require_diagnostic_run(source_dir)

    manifest_raw = source_manifest_path.read_bytes()
    manifest = json.loads(_decode_utf8(manifest_raw, "Source diagnostic manifest"))
    _validate(
        manifest,
        _load_schema(repo_root, "schemas/universe_screen_diagnostic_manifest.schema.json"),
        "Source diagnostic manifest",
    )

    records_path = source_dir / DIAGNOSTIC_RECORDS_FILENAME
    records_raw = records_path.read_bytes()
    records_sha = _sha256(records_raw)
    if records_sha != manifest["output_hashes"][DIAGNOSTIC_RECORDS_FILENAME]:
        raise ScreenInputError(
            "The source records JSONL does not hash to its manifest entry; "
            "nothing is derived from unproven rows."
        )
    record_validator = Draft202012Validator(
        _load_schema(repo_root, RECORD_SCHEMA_RELATIVE_PATH),
        format_checker=FormatChecker(),
    )
    rows: list[dict] = []
    for line_number, line in enumerate(
        _decode_utf8(records_raw, DIAGNOSTIC_RECORDS_FILENAME).splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ScreenInputError(
                f"Source record line {line_number} is not valid JSON: {exc}."
            ) from exc
        errors = sorted(record_validator.iter_errors(record),
                        key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Source record line {line_number} violates {RECORD_CONTRACT} "
                f"at {errors[0].json_path}: {errors[0].message}"
            )
        rows.append(record)

    # The partition is re-proven from the rows, never trusted from counts.
    counts = manifest["counts"]
    validated = [r for r in rows if r["record_kind"] == "validated_screen"]
    rejected = [r for r in rows if r["record_kind"] == "rejected_output"]
    if len(rows) != counts["rows_selected"] or (
        len(validated) != counts["validated"]
        or len(rejected) != counts["rejected"]
    ):
        raise ScreenInputError(
            "The source run's rows do not partition as its manifest counts "
            "declare; an incomplete source derives nothing."
        )
    if [r["row_ordinal"] for r in rows] != list(range(1, len(rows) + 1)):
        raise ScreenInputError(
            "The source run's row ordinals are not dense and one-based."
        )
    if len({(r["cik"], r["accession"]) for r in rows}) != len(rows):
        raise ScreenInputError(
            "The source run carries duplicate (cik, accession) rows."
        )

    eligible = [r for r in rejected
                if r["rejection_reason_code"] == REPAIR_REASON]
    eligible.sort(key=lambda r: r["row_ordinal"])
    if len(eligible) != REPAIR_ROWS:
        raise ScreenInputError(
            f"The source run holds {len(eligible)} "
            f"{REPAIR_REASON} rejections; a {REPAIR_SELECTION_KIND} "
            f"selection derives exactly {REPAIR_ROWS}, and any other count "
            "is a different population needing its own contract."
        )
    declared = counts["rejections_by_reason"].get(REPAIR_REASON)
    if declared != REPAIR_ROWS:
        raise ScreenInputError(
            f"The source manifest declares {declared} {REPAIR_REASON} "
            f"rejections but its rows derive {REPAIR_ROWS}; refusing the "
            "disagreement."
        )
    return {
        "manifest": manifest,
        "manifest_sha256": _sha256(manifest_raw),
        "records_sha256": records_sha,
        "rows_total": len(rows),
        "rejected_total": len(rejected),
        "eligible": eligible,
    }


def build_repair_selection(
    *,
    repo_root: str | Path,
    source_diagnostic_manifest_path: str | Path,
    packet_manifest_path: str | Path,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> DiagnosticRunResult:
    """Derive and persist the seven-row repair selection. No model call."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    source = _derive_repair_rows(root, Path(source_diagnostic_manifest_path))

    # The packet cohort must be the same one the source run screened, and
    # every derived row must still resolve in it with an unchanged packet.
    inputs = load_packet_run(root, packet_manifest_path)
    if inputs.manifest_sha256 != source["manifest"]["packet_manifest_sha256"]:
        raise ScreenInputError(
            "The supplied packet manifest is not the cohort the source "
            "diagnostic run screened; the repair rows would be unmoored."
        )
    packets_by_key = {(p["cik"], p["accession"]): p for p in inputs.packets}
    selection_rows: list[dict] = []
    for record in source["eligible"]:
        key = (record["cik"], record["accession"])
        packet = packets_by_key.get(key)
        if packet is None:
            raise ScreenInputError(
                f"Source rejection cik={key[0]} accession={key[1]} has no "
                "packet in the supplied cohort; refusing a missing packet."
            )
        if packet["packet_sha256"] != record["packet_sha256"]:
            raise ScreenInputError(
                f"Packet for cik={key[0]} hashes to "
                f"{packet['packet_sha256']}, but the source record pinned "
                f"{record['packet_sha256']}; refusing a drifted packet."
            )
        selection_rows.append({
            "source_row_ordinal": record["row_ordinal"],
            "cik": record["cik"],
            "accession": record["accession"],
            "packet_sha256": record["packet_sha256"],
            "source_record_kind": "rejected_output",
            "source_rejection_reason_code": REPAIR_REASON,
        })

    payload = {
        "selection_contract": REPAIR_SELECTION_CONTRACT,
        "selection_id": run_id,
        "selection_kind": REPAIR_SELECTION_KIND,
        "derivation_rule": DERIVATION_RULE,
        "source_diagnostic_manifest_path": str(source_diagnostic_manifest_path),
        "source_diagnostic_manifest_sha256": source["manifest_sha256"],
        "source_records_jsonl_sha256": source["records_sha256"],
        "source_run_id": source["manifest"]["run_id"],
        "packet_manifest_path": str(packet_manifest_path),
        "packet_manifest_sha256": inputs.manifest_sha256,
        "rows": selection_rows,
        "counts": {
            "source_rows_total": source["rows_total"],
            "source_rejected_total": source["rejected_total"],
            "source_rejected_quote_resolution": REPAIR_ROWS,
            "rows_selected": REPAIR_ROWS,
        },
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "Derived, never authored: the seven rows are exactly the source "
            "run's quote_resolution_failure rejections in ascending source "
            "ordinal order, re-derived again by the consuming runner.",
            "A repair selection authorizes nothing by itself and its rows "
            "are a diagnostic population, never a screen sample.",
        ],
    }
    _validate(
        payload,
        _load_schema(root, REPAIR_SELECTION_SCHEMA_RELATIVE_PATH),
        "Repair selection artifact",
    )

    result = DiagnosticRunResult(
        run_id=run_id, run_dir=None, dry_run=dry_run, status="dry_run",
        planned_screened=REPAIR_ROWS, planned_insufficient=0,
        counts=dict(payload["counts"]),
    )
    if dry_run:
        return result
    run_dir = create_run_directory(output_dir, run_id)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        write_bytes_once(run_dir / REPAIR_SELECTION_FILENAME, raw,
                         what=f"repair selection {run_dir / REPAIR_SELECTION_FILENAME}")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    result.run_dir = run_dir
    result.dry_run = False
    result.status = "completed"
    result.manifest_path = run_dir / REPAIR_SELECTION_FILENAME
    return result


def load_repair_selection(
    repo_root: str | Path, selection_path: str | Path
) -> tuple[dict, str]:
    """Load and schema-validate one repair selection; return it with its sha."""
    target = Path(selection_path)
    if not target.is_file():
        raise ScreenInputError(f"Repair selection artifact not found: {target}.")
    raw = target.read_bytes()
    try:
        payload = json.loads(_decode_utf8(raw, "Repair selection artifact"))
    except json.JSONDecodeError as exc:
        raise ScreenInputError(
            f"Repair selection artifact {target} is not valid JSON: {exc}."
        ) from exc
    _validate(
        payload,
        _load_schema(Path(repo_root), REPAIR_SELECTION_SCHEMA_RELATIVE_PATH),
        f"Repair selection artifact {target}",
    )
    return payload, _sha256(raw)


# --- Consumer gate -----------------------------------------------------------------


def require_diagnostic_repair_run(run_dir: str | Path) -> Path:
    """Accept only a completed repair run, and refuse everything else."""
    directory = Path(run_dir)
    if (directory / FAILURE_RECEIPT_FILENAME).exists():
        raise ScreenInputError(
            f"Repair run {directory} holds a failure receipt; it is "
            "incomplete and may not be consumed."
        )
    for foreign, what in ((SCREEN_MANIFEST_FILENAME, "authoritative screen"),
                          (DIAGNOSTIC_MANIFEST_FILENAME, "diagnostic canary")):
        if (directory / foreign).exists():
            raise ScreenInputError(
                f"Run {directory} carries a {what} manifest; it is not a "
                "repair run and must be read through its own loader."
            )
    manifest_path = directory / REPAIR_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Repair run {directory} has no repair manifest; only a "
            "manifest-bearing run is complete."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_contract") != REPAIR_MANIFEST_CONTRACT:
        raise ScreenInputError(
            f"Repair run {directory} declares contract "
            f"{manifest.get('manifest_contract')!r}, not "
            f"{REPAIR_MANIFEST_CONTRACT}."
        )
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file():
            raise ScreenInputError(
                f"Repair run output {filename} is missing beside its manifest."
            )
        observed = _sha256(target.read_bytes())
        if observed != recorded:
            raise ScreenInputError(
                f"Repair run output {filename} hashes to {observed}, but the "
                f"manifest records {recorded}; the run is not consumable."
            )
    return manifest_path


# --- Preflight ---------------------------------------------------------------------


@dataclass
class _RepairPreflight:
    authorization: dict
    enablement: dict
    contract_digest: str
    endpoints: dict
    prompt_template_text: str
    prompt_template_sha256: str
    inputs: Any
    selection: dict
    selection_sha256: str
    selected_packets: list[dict]
    max_rejected_rows: int
    source_rederivation_holds: bool


def _repair_preflight(
    *,
    root: Path,
    packet_manifest_path: str | Path,
    selection_artifact_path: str | Path,
    governance_root: Path,
    authorization_reference: str,
    authorization_sha256: str,
    logical_request_cap: int,
    provider_attempt_cap: int,
    clock: Callable[[], datetime],
) -> _RepairPreflight:
    """The ADR-109 validation order, against the repair authorization.

    Every step runs before any output directory, SDK import, credential
    resolution or network send. Beyond the diagnostic preflight, the repair
    preflight **re-derives the selection from the bound source run's bytes**
    and refuses any difference, so the derivation-rule proof is executed
    twice: once when the selection was minted and again for every run.
    """
    # (2) The repair authorization, by pin.
    authorization, _ = _hydrate_pinned(
        governance_root, authorization_reference, authorization_sha256,
        "screen diagnostic repair authorization",
    )
    _validate(
        authorization,
        _load_schema(root, REPAIR_AUTHORIZATION_SCHEMA_RELATIVE_PATH),
        "Screen diagnostic repair authorization",
    )
    if authorization["run_kind"] != REPAIR_RUN_KIND:
        raise ScreenInputError(
            f"The authorization declares run_kind "
            f"{authorization['run_kind']!r}; this runner performs "
            f"{REPAIR_RUN_KIND!r} runs only."
        )
    if authorization["output_contract"] != RECORD_CONTRACT:
        raise ScreenInputError(
            "The authorization names a different output contract than "
            f"{RECORD_CONTRACT}."
        )
    if authorization["selection_kind"] != REPAIR_SELECTION_KIND:
        raise ScreenInputError(
            f"A repair run screens a {REPAIR_SELECTION_KIND} selection only."
        )
    if authorization["diagnostic_only"] is not True or (
        authorization["promotable"] is not False
    ):
        raise ScreenInputError(
            "A repair authorization must declare diagnostic_only true and "
            "promotable false."
        )

    # (3) The enablement, via the authorization's own pin; temporal windows.
    enablement, _ = _hydrate_pinned(
        governance_root,
        authorization["screen_adapter_enablement_reference"],
        authorization["screen_adapter_enablement_sha256"],
        "screen adapter enablement",
    )
    _validate(
        enablement,
        _load_schema(root, ENABLEMENT_SCHEMA_RELATIVE_PATH),
        "Screen adapter enablement",
    )
    now = clock()
    for what, artifact in (("authorization", authorization),
                           ("enablement", enablement)):
        effective = _parse_moment(artifact["effective_at"], f"{what} effective_at")
        expires = _parse_moment(artifact["expires_at"], f"{what} expires_at")
        if not (effective <= now < expires):
            raise ScreenInputError(
                f"The {what} window [{artifact['effective_at']} .. "
                f"{artifact['expires_at']}) does not cover {now.isoformat()}; "
                "nothing runs under an expired or not-yet-effective grant."
            )
    if enablement["screen_stage"] != SCREEN_STAGE or (
        authorization["screen_stage"] != SCREEN_STAGE
    ):
        raise ScreenInputError(
            f"Both artifacts must declare screen_stage {SCREEN_STAGE!r}."
        )

    # (4) The client contract, recomputed from code for the authorized project.
    contract = build_client_contract_v2(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"],
    )
    contract_digest = client_contract_digest(contract)
    for what, artifact in (("authorization", authorization),
                           ("enablement", enablement)):
        if artifact["provider_client_contract_sha256"] != contract_digest:
            raise ScreenInputError(
                f"The {what} pins client-contract digest "
                f"{artifact['provider_client_contract_sha256']}, but the "
                f"connector's own declared contract digests to "
                f"{contract_digest}."
            )
        if artifact["provider_client_contract_reference"] != CLIENT_CONTRACT_V2_ID:
            raise ScreenInputError(
                f"The {what} names client contract "
                f"{artifact['provider_client_contract_reference']!r}; this "
                f"connector speaks {CLIENT_CONTRACT_V2_ID!r}."
            )
    expected_route = {
        "provider": contract["model_provider"],
        "model_label": contract["model_name"],
    }
    if authorization["model_route"] != expected_route:
        raise ScreenInputError(
            f"The authorization's model route {authorization['model_route']} "
            f"is not the connector's route {expected_route}."
        )
    if authorization["retry_policy_version"] != RETRY_POLICY_VERSION or (
        authorization["rate_limit_policy_version"] != RATE_LIMIT_POLICY_VERSION
    ):
        raise ScreenInputError(
            "The authorization names retry/rate-limit policy versions other "
            "than the committed ones; it was minted for a different policy."
        )

    # (5) Endpoint equality across authorization, enablement and derivation.
    endpoints = build_operation_endpoints(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"],
    )
    expected_endpoints = set(endpoints.values())
    for what, artifact in (("authorization", authorization),
                           ("enablement", enablement)):
        if set(artifact["endpoint_allowlist"]) != expected_endpoints:
            raise ScreenInputError(
                f"The {what} endpoint allowlist is not exactly the two "
                "operation endpoints derived from the client contract."
            )

    # (6) The prompt binding: the committed v5 diagnostic bytes.
    template_path = root / DIAGNOSTIC_PROMPT_TEMPLATE_RELATIVE_PATH
    if not template_path.is_file():
        raise ScreenInputError(
            f"Diagnostic screen prompt template not found: {template_path}"
        )
    template_raw = template_path.read_bytes()
    template_sha = _sha256(template_raw)
    if template_sha != authorization["prompt_template_sha256"]:
        raise ScreenInputError(
            f"The committed diagnostic prompt template "
            f"({DIAGNOSTIC_PROMPT_TEMPLATE_RELATIVE_PATH}) hashes to "
            f"{template_sha}, but the authorization binds "
            f"{authorization['prompt_template_sha256']}. A stale or "
            "mismatched prompt authorization runs nothing."
        )

    # (7) The cohort, the selection, the source re-derivation, and the caps.
    inputs = load_packet_run(root, packet_manifest_path)
    if inputs.manifest_sha256 != authorization["packet_manifest_sha256"]:
        raise ScreenInputError(
            f"The packet manifest hashes to {inputs.manifest_sha256}, but the "
            f"authorization binds {authorization['packet_manifest_sha256']}; "
            "this is not the cohort that was authorized."
        )
    selection, selection_sha = load_repair_selection(root, selection_artifact_path)
    if selection_sha != authorization["selection_artifact_sha256"]:
        raise ScreenInputError(
            "The repair selection artifact is not the one the authorization "
            "binds."
        )
    if selection["packet_manifest_sha256"] != inputs.manifest_sha256:
        raise ScreenInputError(
            "The repair selection binds a different packet manifest than the "
            "one loaded; nothing is screened."
        )

    # The derivation-rule proof, executed again: the selection's rows must be
    # exactly what the bound source run's bytes derive today.
    source_path = Path(selection["source_diagnostic_manifest_path"])
    source = _derive_repair_rows(root, source_path)
    if source["manifest_sha256"] != selection["source_diagnostic_manifest_sha256"]:
        raise ScreenInputError(
            "The source diagnostic manifest no longer hashes to the value "
            "the repair selection pinned; the source has drifted."
        )
    if source["records_sha256"] != selection["source_records_jsonl_sha256"]:
        raise ScreenInputError(
            "The source records JSONL no longer hashes to the value the "
            "repair selection pinned; the source has drifted."
        )
    rederived = [{
        "source_row_ordinal": r["row_ordinal"],
        "cik": r["cik"],
        "accession": r["accession"],
        "packet_sha256": r["packet_sha256"],
        "source_record_kind": "rejected_output",
        "source_rejection_reason_code": REPAIR_REASON,
    } for r in source["eligible"]]
    if rederived != selection["rows"]:
        raise ScreenInputError(
            "Re-deriving the repair selection from the source run's bytes "
            "does not reproduce the selection's rows; a doctored selection "
            "is refused even with a matching digest chain."
        )

    packets_by_key = {(p["cik"], p["accession"]): p for p in inputs.packets}
    selected: list[dict] = []
    for row in selection["rows"]:
        key = (row["cik"], row["accession"])
        packet = packets_by_key.get(key)
        if packet is None:
            raise ScreenInputError(
                f"The repair selection names cik={key[0]} "
                f"accession={key[1]}, which is not a valid packet row of "
                "this cohort."
            )
        if packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError(
                f"The repair selection pins packet sha {row['packet_sha256']} "
                f"for cik={key[0]}, but the cohort's packet hashes to "
                f"{packet['packet_sha256']}; refusing a drifted row."
            )
        selected.append(packet)

    if logical_request_cap != REPAIR_ROWS or len(selected) != REPAIR_ROWS:
        raise ScreenInputError(
            f"logical_request_cap must be exactly {REPAIR_ROWS}: one logical "
            "request per repaired row."
        )
    if authorization["logical_request_cap"] != logical_request_cap:
        raise ScreenInputError(
            "The operator-stated logical cap and the authorization disagree."
        )
    expected_attempt_cap = REPAIR_ROWS * GENERATE_ATTEMPT_CAP_PER_ROW
    if provider_attempt_cap != expected_attempt_cap or (
        authorization["provider_attempt_cap"] != expected_attempt_cap
    ):
        raise ScreenInputError(
            f"provider_attempt_cap must be exactly {expected_attempt_cap} "
            f"({REPAIR_ROWS} x {GENERATE_ATTEMPT_CAP_PER_ROW} generate "
            "attempts)."
        )
    expected_external = REPAIR_ROWS * EXTERNAL_REQUESTS_PER_ROW
    if authorization["budget_max_external_requests"] != expected_external:
        raise ScreenInputError(
            f"budget_max_external_requests must be exactly {expected_external}."
        )
    max_rejected = authorization["max_rejected_rows"]
    if not isinstance(max_rejected, int) or isinstance(max_rejected, bool) or (
        not 1 <= max_rejected < REPAIR_ROWS
    ):
        raise ScreenInputError(
            f"max_rejected_rows must be an integer in [1, {REPAIR_ROWS - 1}] "
            "for a seven-row measurement; a breaker that can never trip is "
            "not a breaker."
        )

    return _RepairPreflight(
        authorization=authorization,
        enablement=enablement,
        contract_digest=contract_digest,
        endpoints=endpoints,
        prompt_template_text=_decode_utf8(template_raw, "Screen prompt template"),
        prompt_template_sha256=template_sha,
        inputs=inputs,
        selection=selection,
        selection_sha256=selection_sha,
        selected_packets=selected,
        max_rejected_rows=max_rejected,
        source_rederivation_holds=True,
    )


# --- The repair runner --------------------------------------------------------------


def run_lineage_screen_diagnostic_repair(
    *,
    repo_root: str | Path,
    packet_manifest_path: str | Path,
    selection_artifact_path: str | Path,
    governance_root: str | Path,
    authorization_reference: str,
    authorization_sha256: str,
    output_dir: str | Path,
    run_id: str,
    logical_request_cap: int,
    provider_attempt_cap: int,
    clock: Callable[[], datetime],
    dry_run: bool = False,
    client_factory: Any = None,
) -> DiagnosticRunResult:
    """Re-screen the seven derived rows under v5. Diagnostic only, never a screen."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    pre = _repair_preflight(
        root=root,
        packet_manifest_path=packet_manifest_path,
        selection_artifact_path=selection_artifact_path,
        governance_root=Path(governance_root),
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256,
        logical_request_cap=logical_request_cap,
        provider_attempt_cap=provider_attempt_cap,
        clock=clock,
    )
    record_schema = _load_schema(root, RECORD_SCHEMA_RELATIVE_PATH)
    manifest_schema = _load_schema(root, REPAIR_MANIFEST_SCHEMA_RELATIVE_PATH)

    if dry_run:
        for packet in pre.selected_packets:
            render_diagnostic_prompt_with_citation_refs(
                pre.prompt_template_text, packet
            )
        return DiagnosticRunResult(
            run_id=run_id, run_dir=None, dry_run=True, status="dry_run",
            planned_screened=REPAIR_ROWS, planned_insufficient=0,
            request_accounting={
                "logical_request_cap": logical_request_cap,
                "provider_attempt_cap": provider_attempt_cap,
                "external_request_cap":
                    pre.authorization["budget_max_external_requests"],
                "max_rejected_rows": pre.max_rejected_rows,
            },
        )

    connector = VertexGeminiProviderV2(
        vertex_project=pre.authorization["vertex_project"],
        vertex_location=pre.authorization["vertex_location"],
        expected_authorization_sha256=authorization_sha256,
        max_provider_requests=GENERATE_ATTEMPT_CAP_PER_ROW,
        endpoint_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
        client_factory=client_factory,
    )
    try:
        connector.assert_run_permitted(
            authorization_sha256=authorization_sha256,
            endpoint_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
            enablement_endpoint_allowlist=tuple(
                pre.enablement["endpoint_allowlist"]
            ),
        )
    except ProviderError as exc:
        raise ScreenInputError(
            f"The connector refused the handshake ({exc.reason_code}); "
            "nothing runs and nothing exists."
        ) from exc
    finally:
        connector.revoke_run_permission()

    run_dir = create_run_directory(output_dir, run_id)
    result = DiagnosticRunResult(
        run_id=run_id, run_dir=run_dir, dry_run=False, status="failed",
        planned_screened=REPAIR_ROWS, planned_insufficient=0,
    )
    budget = ScreenCohortBudget(
        authorization=pre.authorization,
        authorization_sha256=authorization_sha256,
        run_id=run_id,
        clock=clock,
    )
    ledger: list[dict] = []
    adapter = VertexLineageScreenProvider(
        connector=connector,
        authorization_sha256=authorization_sha256,
        authorization_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
        enablement_allowlist=tuple(pre.enablement["endpoint_allowlist"]),
        run_dir=run_dir,
        budget=budget,
        packet_sha_by_key={
            (p["cik"], p["accession"]): p["packet_sha256"]
            for p in pre.selected_packets
        },
        prompt_template_sha256=pre.prompt_template_sha256,
        ledger=ledger,
    )

    archive_path = run_dir / RAW_RESPONSES_FILENAME
    descriptor = os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    archive = os.fdopen(descriptor, "wb")

    logical_requests_made = 0
    provider_attempts_made = 0
    rows_retried = 0
    raw_responses_captured = 0
    records: list[dict] = []
    rejections = {code: 0 for code in REJECTION_REASON_CODES}

    def _counts_now() -> tuple[int, int]:
        validated = sum(1 for r in records
                        if r["record_kind"] == "validated_screen")
        return validated, len(records) - validated

    def _fail(reason_code: str, detail: str, packet: dict, *,
              stopping_row_index: int | None = None,
              records_completed_before_failure: int | None = None,
              ) -> DiagnosticRunResult:
        """Write the governed receipt and stop; counters as in ADR-112."""
        archive.flush()
        os.fsync(archive.fileno())
        archive.close()
        count_captures = sum(
            1 for entry in ledger if entry["operation_label"] == "count_tokens"
        )
        generate_captures = len(ledger) - count_captures
        validated, rejected = _counts_now()
        receipt = {
            "receipt_contract": "universe_screen_failure_receipt@0.1.0",
            "run_kind": REPAIR_RUN_KIND,
            "run_id": run_id,
            "reason_code": reason_code,
            "detail": _bounded_detail(detail),
            "stopping_cik": packet["cik"],
            "stopping_accession": packet["accession"],
            "stopping_row_index": (
                len(records) + 1 if stopping_row_index is None
                else stopping_row_index
            ),
            "records_completed_before_failure": (
                len(records) if records_completed_before_failure is None
                else records_completed_before_failure
            ),
            "validated_rows": validated,
            "rejected_rows": rejected,
            "max_rejected_rows": pre.max_rejected_rows,
            "raw_responses_captured": raw_responses_captured,
            "capture_files_written": sum(
                1 for entry in ledger
                if entry["capture_disposition"] == "raw_persisted"
            ),
            "count_captures": count_captures,
            "generate_captures": generate_captures,
            "external_requests_made": len(ledger),
            "logical_request_cap": logical_request_cap,
            "provider_attempt_cap": provider_attempt_cap,
            "logical_requests_attempted": logical_requests_made,
            "provider_attempts_made": generate_captures,
            "authorization_sha256": authorization_sha256,
            "run_timestamp": clock().isoformat(),
            "retention_note": (
                "Non-authoritative failed diagnostic repair run: no records "
                "JSONL, no capture ledger and no repair manifest exist here — "
                "only the raw responses and wire captures taken before the "
                "stop. This directory is immutable, was never promotable, "
                "and may not be consumed by any loader; a retry requires a "
                "new run id and new authorization."
            ),
        }
        if reason_code not in RECEIPT_REASON_CODES:
            raise ScreenInputError(
                f"Internal error: receipt reason {reason_code!r} is outside "
                f"the closed repair vocabulary {RECEIPT_REASON_CODES}."
            )
        payload = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        )
        try:
            write_bytes_once(
                run_dir / FAILURE_RECEIPT_FILENAME, payload,
                what=f"failure receipt {run_dir / FAILURE_RECEIPT_FILENAME}",
            )
        except WriteOnceError as exc:
            raise ScreenInputError(str(exc)) from exc
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        result.receipt = receipt
        result.validated, result.rejected = validated, rejected
        result.rejections_by_reason = dict(rejections)
        return result

    for ordinal, packet in enumerate(pre.selected_packets, start=1):
        rendered, citation_refs = render_diagnostic_prompt_with_citation_refs(
            pre.prompt_template_text, packet
        )
        prompt_sha256 = _sha256(rendered.encode("utf-8"))
        logical_requests_made += 1
        cost_before = budget.cost_micros_settled
        try:
            raw_response = adapter.screen(
                rendered, cik=packet["cik"], accession=packet["accession"]
            )
        except ScreenProviderTerminalError as exc:
            return _fail("provider_error", str(exc), packet)
        report = adapter.row_reports[-1]
        provider_attempts_made += report["attempts"]
        if report["attempts"] > 1:
            rows_retried += 1
        if provider_attempts_made > provider_attempt_cap:
            return _fail(
                "provider_error",
                f"Provider attempt cap {provider_attempt_cap} exceeded.",
                packet,
            )

        raw_bytes = raw_response.encode("utf-8")
        raw_sha256 = _sha256(raw_bytes)
        raw_response_id = f"{run_id}-{packet['cik']}-{packet['accession']}"
        archive.write((_canonical_line({
            "raw_response_id": raw_response_id,
            "cik": packet["cik"],
            "accession": packet["accession"],
            "raw_response": raw_response,
            "raw_response_sha256": raw_sha256,
        }) + "\n").encode("utf-8"))
        archive.flush()
        os.fsync(archive.fileno())
        raw_responses_captured += 1

        row = {
            "record_contract": RECORD_CONTRACT,
            "row_ordinal": ordinal,
            "cik": packet["cik"],
            "company_id": packet["company_id"],
            "accession": packet["accession"],
            "form": packet["form"],
            "baseline_filing_date": packet["baseline_filing_date"],
            "source_id": packet["source_id"],
            "packet_sha256": packet["packet_sha256"],
            "prompt_sha256": prompt_sha256,
            "model_route": dict(adapter.model_route),
            "raw_response_id": raw_response_id,
            "raw_response_sha256": raw_sha256,
            "attempts": report["attempts"],
            "measured_input_tokens": report["measured_input_tokens"],
            "usage_output_tokens": report["usage_output_tokens"],
            "usage_verified": bool(report["usage_verified"]),
            "cost_micros": 0,
        }
        try:
            # The identical strict validator, behind the identical resolver.
            output = _validate_row_output(
                resolve_diagnostic_citation_refs(
                    raw_response, citation_refs, packet
                ),
                packet,
            )
        except _RowValidationFailure as exc:
            rejections[exc.reason_code] = rejections.get(exc.reason_code, 0) + 1
            row.update(record_kind="rejected_output", screen_output=None,
                       rejection_reason_code=exc.reason_code,
                       rejection_detail=_bounded_detail(exc.detail))
        else:
            row.update(record_kind="validated_screen",
                       screen_output=output.model_dump(mode="json"),
                       rejection_reason_code=None, rejection_detail=None)
        row["cost_micros"] = budget.cost_micros_settled - cost_before
        records.append(row)

        _, rejected_now = _counts_now()
        if rejected_now > pre.max_rejected_rows:
            return _fail(
                "rejected_row_budget_exhausted",
                f"The declared circuit breaker of {pre.max_rejected_rows} "
                f"rejected rows was exceeded at row {ordinal}; the run stops "
                "with the measurement so far retained.",
                packet,
                stopping_row_index=ordinal,
                records_completed_before_failure=ordinal - 1,
            )

    archive.flush()
    os.fsync(archive.fileno())
    archive.close()

    record_validator = Draft202012Validator(
        record_schema, format_checker=FormatChecker()
    )
    for record in records:
        errors = sorted(record_validator.iter_errors(record),
                        key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Built repair record for cik={record['cik']} violates "
                f"{RECORD_CONTRACT} at {errors[0].json_path}: "
                f"{errors[0].message}"
            )

    archive_raw = archive_path.read_bytes()
    archive_entries = [
        json.loads(line)
        for line in _decode_utf8(archive_raw, RAW_RESPONSES_FILENAME).splitlines()
        if line.strip()
    ]
    entries_by_id = {entry["raw_response_id"]: entry for entry in archive_entries}
    raw_bindings_hold = len(entries_by_id) == len(archive_entries) and all(
        (entry := entries_by_id.get(record["raw_response_id"])) is not None
        and _sha256(entry["raw_response"].encode("utf-8"))
        == entry["raw_response_sha256"] == record["raw_response_sha256"]
        for record in records
    )
    persisted_refs = {
        entry["raw_reference"] for entry in ledger
        if entry["capture_disposition"] == "raw_persisted"
    }
    capture_files_verified = all(
        (run_dir / entry["raw_reference"]).is_file()
        and _sha256((run_dir / entry["raw_reference"]).read_bytes())
        == entry["raw_sha256"]
        for entry in ledger
        if entry["capture_disposition"] == "raw_persisted"
    )
    on_disk = {
        str(path.relative_to(run_dir))
        for path in (run_dir / CAPTURES_DIRNAME).rglob("*")
        if path.is_file()
    }
    no_orphan_captures = on_disk == persisted_refs

    archive_matches_envelopes = True
    for report in adapter.row_reports:
        envelope_raw = (run_dir / report["terminal_raw_reference"]).read_bytes()
        if _sha256(envelope_raw) != report["terminal_raw_sha256"]:
            archive_matches_envelopes = False
            break
        text, _ = _extract_envelope_text(envelope_raw)
        entry = entries_by_id.get(
            f"{run_id}-{report['cik']}-{report['accession']}"
        )
        if entry is None or entry["raw_response"] != text:
            archive_matches_envelopes = False
            break

    count_captures = sum(
        1 for entry in ledger if entry["operation_label"] == "count_tokens"
    )
    generate_captures = len(ledger) - count_captures
    validated_records = [r for r in records
                         if r["record_kind"] == "validated_screen"]
    rejected_records = [r for r in records
                        if r["record_kind"] == "rejected_output"]
    status_counts = {status: 0 for status in SCREEN_STATUSES}
    for record in validated_records:
        status_counts[record["screen_output"]["screen_status"]] += 1

    counts = {
        "rows_selected": REPAIR_ROWS,
        "validated": len(validated_records),
        "rejected": len(rejected_records),
        "max_rejected_rows": pre.max_rejected_rows,
        "by_screen_status": status_counts,
        "rejections_by_reason": dict(rejections),
        "firms_total": len({r["cik"] for r in records}),
    }
    request_accounting = {
        "logical_request_cap": logical_request_cap,
        "provider_attempt_cap": provider_attempt_cap,
        "external_request_cap":
            pre.authorization["budget_max_external_requests"],
        "generate_attempt_cap_per_row": GENERATE_ATTEMPT_CAP_PER_ROW,
        "logical_requests_made": logical_requests_made,
        "provider_attempts_made": provider_attempts_made,
        "external_requests_made": len(ledger),
        "count_captures": count_captures,
        "generate_captures": generate_captures,
        "rows_retried": rows_retried,
        "tokens_in_measured": budget.tokens_in_measured,
        "tokens_out_reported": budget.tokens_out_reported,
        "rows_usage_verified": budget.rows_usage_verified,
        "cost_micros_settled": budget.cost_micros_settled,
        "cost_micros_rejected_rows": sum(
            r["cost_micros"] for r in rejected_records
        ),
        "budget_max_input_tokens": pre.authorization["budget_max_input_tokens"],
        "budget_max_output_tokens": pre.authorization["budget_max_output_tokens"],
        "budget_max_estimated_cost_micros":
            pre.authorization["budget_max_estimated_cost_micros"],
        "budget_max_wall_clock_seconds":
            pre.authorization["budget_max_wall_clock_seconds"],
    }

    reconciliation = {
        "validated and rejected partition the seven rows": (
            len(validated_records) + len(rejected_records) == len(records)
            == REPAIR_ROWS
        ),
        "every selected row was screened exactly once": (
            len(records) == logical_requests_made == logical_request_cap
        ),
        "records follow the selection row order": (
            [(r["cik"], r["accession"]) for r in records]
            == [(p["cik"], p["accession"]) for p in pre.selected_packets]
        ),
        "row ordinals are dense and one-based": (
            [r["row_ordinal"] for r in records]
            == list(range(1, len(records) + 1))
        ),
        "the selection re-derives from the bound source run": (
            pre.source_rederivation_holds
        ),
        "rejections by reason sum to the rejected count": (
            sum(rejections.values()) == len(rejected_records)
        ),
        "every rejection reason is in the closed validator vocabulary": all(
            r["rejection_reason_code"] in REJECTION_REASON_CODES
            for r in rejected_records
        ),
        "the circuit breaker was never exceeded": (
            len(rejected_records) <= pre.max_rejected_rows
        ),
        "no rejected row carries an accepted screen result": all(
            r["screen_output"] is None for r in rejected_records
        ),
        "every validated row carries a closed screen status": all(
            r["screen_output"]["screen_status"] in SCREEN_STATUSES
            for r in validated_records
        ),
        "every row binds its raw response, rejected rows included": (
            raw_bindings_hold
            and len(archive_entries) == len(records)
        ),
        "generate captures equal provider attempts": (
            generate_captures == provider_attempts_made
            == sum(report["attempts"] for report in adapter.row_reports)
        ),
        "count and generate captures partition external requests": (
            count_captures + generate_captures == len(ledger)
            == budget.external_requests_made
        ),
        "every row made exactly one count send": (
            count_captures == logical_requests_made
        ),
        "external requests stay within the authorized cap": (
            len(ledger) <= pre.authorization["budget_max_external_requests"]
        ),
        "provider attempts never exceeded the declared cap": (
            provider_attempts_made <= provider_attempt_cap
        ),
        "every capture file re-hashes to its ledger line": capture_files_verified,
        "no orphan capture file exists": no_orphan_captures,
        "every archived response equals its terminal envelope text": (
            archive_matches_envelopes
        ),
        "the prompt template hash equals the authorization's": (
            pre.prompt_template_sha256
            == pre.authorization["prompt_template_sha256"]
        ),
        "per-row cost sums to the settled cohort cost": (
            sum(r["cost_micros"] for r in records) == budget.cost_micros_settled
        ),
    }
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            "Repair reconciliation failed; no records JSONL, no capture "
            f"ledger and no manifest are written. Failed identities: {failed}."
        )

    records_payload = (
        "\n".join(_canonical_line(record) for record in records) + "\n"
    ).encode("utf-8")
    ledger_payload = (
        "\n".join(_canonical_line(entry) for entry in ledger) + "\n"
    ).encode("utf-8")
    try:
        write_bytes_once(run_dir / REPAIR_RECORDS_FILENAME, records_payload,
                         what=f"repair records {run_dir / REPAIR_RECORDS_FILENAME}")
        write_bytes_once(run_dir / CAPTURE_LEDGER_FILENAME, ledger_payload,
                         what=f"capture ledger {run_dir / CAPTURE_LEDGER_FILENAME}")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    manifest = {
        "manifest_contract": REPAIR_MANIFEST_CONTRACT,
        "run_kind": REPAIR_RUN_KIND,
        "diagnostic_only": True,
        "promotable": False,
        "output_contract": RECORD_CONTRACT,
        "run_id": run_id,
        "packet_manifest_path": str(packet_manifest_path),
        "packet_manifest_sha256": pre.inputs.manifest_sha256,
        "packet_run_id": pre.inputs.manifest["run_id"],
        "packets_jsonl_sha256": pre.inputs.packets_jsonl_sha256,
        "packet_failures_jsonl_sha256": pre.inputs.failures_jsonl_sha256,
        "prompt_template_path": DIAGNOSTIC_PROMPT_TEMPLATE_RELATIVE_PATH,
        "prompt_template_sha256": pre.prompt_template_sha256,
        "authorization_id": pre.authorization["authorization_id"],
        "authorization_sha256": authorization_sha256,
        "screen_adapter_enablement_sha256":
            pre.authorization["screen_adapter_enablement_sha256"],
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": pre.contract_digest,
        "endpoint_allowlist": sorted(pre.endpoints.values()),
        "envelope_text_extraction_rule": ENVELOPE_TEXT_EXTRACTION_RULE,
        "selection": {
            "selection_artifact_path": str(selection_artifact_path),
            "selection_artifact_sha256": pre.selection_sha256,
            "selection_kind": REPAIR_SELECTION_KIND,
            "derivation_rule": DERIVATION_RULE,
            "rows_selected": REPAIR_ROWS,
            "source_diagnostic_manifest_path":
                pre.selection["source_diagnostic_manifest_path"],
            "source_diagnostic_manifest_sha256":
                pre.selection["source_diagnostic_manifest_sha256"],
            "source_records_jsonl_sha256":
                pre.selection["source_records_jsonl_sha256"],
            "source_run_id": pre.selection["source_run_id"],
        },
        "provider": {
            "name": adapter.name,
            "model_route": dict(adapter.model_route),
        },
        "record_order": RECORD_ORDER,
        "baseline_cutoff": pre.inputs.baseline_cutoff,
        "counts": counts,
        "request_accounting": request_accounting,
        "reconciliation": reconciliation,
        "output_hashes": {
            REPAIR_RECORDS_FILENAME: _sha256(records_payload),
            RAW_RESPONSES_FILENAME: _sha256(archive_raw),
            CAPTURE_LEDGER_FILENAME: _sha256(ledger_payload),
        },
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "universe_screen_diagnostic_record": "0.1.0",
            "universe_screen_diagnostic_repair_manifest": "0.1.0",
            "universe_screen_diagnostic_repair_selection": "0.1.0",
            "universe_screen_diagnostic_repair_authorization": "0.1.0",
            "universe_screen_adapter_enablement": "0.1.0",
            "baseline_packet_manifest_v5": "0.5.0",
            "universe_baseline_packet_v2": "0.2.0",
        },
        "limitations": [
            "A seven-row diagnostic measurement, never an authoritative "
            "screen: its population is exactly the source diagnostic run's "
            "seven quote_resolution_failure rejections, so its validation "
            "rate says nothing about the full cohort.",
            "No row of this run may enter a SCREEN release, a classifier "
            "call list, or any later stage; the authoritative, promotion "
            "and standard diagnostic loaders refuse this directory "
            "structurally.",
            "A rejected row carries no accepted screen result; its full "
            "invalid payload is retained only in the hash-bound raw-response "
            "archive.",
            "The row validator is the authoritative one, imported unchanged "
            "behind the unchanged v5 resolver.",
            "Every binding is relational between the supplied inputs; no "
            "production hash is pinned in code or schema.",
        ],
    }
    _validate(manifest, manifest_schema, "Diagnostic repair run manifest")
    manifest_payload = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        write_bytes_once(run_dir / REPAIR_MANIFEST_FILENAME, manifest_payload,
                         what=f"repair manifest {run_dir / REPAIR_MANIFEST_FILENAME}")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    result.status = "completed"
    result.counts = counts
    result.reconciliation = reconciliation
    result.request_accounting = request_accounting
    result.manifest_path = run_dir / REPAIR_MANIFEST_FILENAME
    result.validated = len(validated_records)
    result.rejected = len(rejected_records)
    result.rejections_by_reason = dict(rejections)
    return result
