"""Governed continuation of a failed full-cohort screen run (ADR-118).

A live V3 full-cohort run completed 3,939 of 7,042 rows and then died because
one ``countTokens`` call timed out. Nothing was wrong with the 3,939 completed
rows; the run simply had no way to keep them. This module is the successor that
can: it revalidates a hash-bound completed prefix from one **explicitly named**
failed run, model-calls only the remaining suffix, and emits one fresh
authoritative full-cohort output.

**Reuse is earned, never assumed.** The parent was never authoritative — it
holds a failure receipt, no manifest, no records and no capture ledger — and it
stays that way forever. Nothing about it is trusted here. Every reused row is
re-parsed, re-reference-resolved and re-validated by the same strict rules the
live route applies to a fresh response, using a prompt re-rendered from the
packet rather than any stored intermediate. A reused row that no longer
validates does not become a screened row; it becomes the same
``model_evidence_unverified`` record a fresh failure would.

**What is proven before a run directory, an SDK import or a send exists:**

* the source receipt matches its pinned digest and is the one enumerated,
  continuation-safe shape — a provider timeout with a contiguous completed
  prefix and no archived response for the stopping row;
* the source archive matches its pinned digest, line for line, hash for hash;
* the archive maps in selection order onto a contiguous prefix of the current
  selection, with no skipped, reordered, duplicated, foreign or suffix row;
* the parent ran under a grant whose packet, selection, prompt, route, client
  contract and endpoint bindings are identical to this run's;
* every reused response still validates.

**Honest telemetry.** A failed run leaves no capture ledger, so no per-attempt
token, cost or wire accounting exists for the prefix. The manifest records the
parent's receipt aggregates and pins ``per_attempt_telemetry_available`` false
rather than inventing numbers, and ``request_accounting`` describes this run's
own sends only.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
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
    SCREEN_COUNT_RETRY_DELAYS_SECONDS,
    SCREEN_COUNT_RETRY_POLICY_VERSION,
    SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2,
    screen_count_attempt_cap,
    screen_external_request_cap_v2,
)
from dynamic_ai_products.providers.screen_retry_policy import (
    SCREEN_GENERATE_MAX_ATTEMPTS,
    SCREEN_GENERATE_RETRY_DELAYS_SECONDS,
    SCREEN_GENERATE_RETRY_POLICY_VERSION,
    SCREEN_RETRY_JITTER,
    screen_generate_attempt_cap,
)
from dynamic_ai_products.providers.vertex_gemini_screen_v4 import (
    SCREEN_CONNECTOR_V4_ID,
    VertexGeminiScreenV4,
)
from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

from .lineage_screen_diagnostic import (
    REJECTION_REASON_CODES,
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
    load_screen_selection,
)
from .lineage_screen_live_v2 import (
    PROMPT_PATH,
    RECORD_ORDER,
    ROLLUP_RULE,
    _detail,
    firm_rollup_v2,
)
from .lineage_screen_live_v3 import ScreenCohortBudgetV3
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    FAILURE_RECEIPT_FILENAME,
    RAW_RESPONSES_FILENAME,
    RECORDS_FILENAME,
    SCREEN_MANIFEST_FILENAME,
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
    "SourcePrefix",
    "load_continuation_source",
    "revalidate_source_prefix",
    "run_lineage_screen_continuation",
]

AUTHORIZATION_SCHEMA = "schemas/universe_screen_continuation_authorization.schema.json"
MANIFEST_SCHEMA = "schemas/universe_screen_continuation_manifest.schema.json"
RECORD_SCHEMA = "schemas/universe_screen_record.v3.schema.json"
AUTHORIZATION_CONTRACT = "universe_screen_continuation_authorization@0.1.0"
RECORD_CONTRACT = "universe_screen_record@0.3.0"
MANIFEST_CONTRACT = "universe_screen_manifest@0.8.0"
RUN_KIND = "full_cohort_continuation"
RECEIPT_CONTRACT = "universe_screen_failure_receipt@0.1.0"

#: The one source failure shape this route accepts. Any other receipt — an
#: exhausted model-evidence breaker, a capture failure, a cap breach, a
#: reconciliation failure — is a different situation whose prefix has not been
#: shown to be reusable, and is refused rather than assumed safe.
ACCEPTED_SOURCE_REASON_CODE = "provider_error"
ACCEPTED_SOURCE_FAILURE_SIGNATURE = "provider_timeout"

#: A continuation source must be a V3-route receipt: only that generation
#: records the per-row generate ceiling, and only its one-count-per-row
#: invariant lets the count/generate split below be derived from aggregates.
_REQUIRED_RECEIPT_FIELDS = (
    "receipt_contract", "run_id", "reason_code", "detail", "stopping_cik",
    "stopping_accession", "stopping_row_index", "records_completed_before_failure",
    "raw_responses_captured", "external_requests_made", "provider_attempts_made",
    "logical_request_cap", "provider_attempt_cap", "generate_attempt_cap_per_row",
    "authorization_sha256",
)


@dataclass
class SourcePrefix:
    """One failed run's reusable evidence, all of it hash-bound."""

    run_dir: Path
    run_id: str
    receipt: dict
    receipt_sha256: str
    archive_bytes: bytes
    archive_sha256: str
    entries: list[dict] = field(default_factory=list)


def load_continuation_source(
    source_run_dir: str | Path, *, source_receipt_sha256: str
) -> SourcePrefix:
    """Load and structurally validate one explicitly named failed run.

    There is no discovery here by design: no run-root scan, no glob, no
    "latest failed run". The caller names a directory and pins its receipt by
    digest, and anything that does not match exactly is refused.
    """
    directory = Path(source_run_dir)
    if not directory.is_dir():
        raise ScreenInputError(
            f"Continuation source {directory} is not a directory; a source run "
            "is named explicitly and must exist."
        )
    # A completed run is not a continuation source: it needs no continuing, and
    # reusing part of it would fork an authoritative artifact.
    for filename, what in ((SCREEN_MANIFEST_FILENAME, "manifest"),
                           (RECORDS_FILENAME, "records JSONL"),
                           (CAPTURE_LEDGER_FILENAME, "capture ledger")):
        if (directory / filename).exists():
            raise ScreenInputError(
                f"Continuation source {directory} carries a {what}; a completed "
                "run is authoritative on its own and is never continued."
            )
    receipt_path = directory / FAILURE_RECEIPT_FILENAME
    if not receipt_path.is_file():
        raise ScreenInputError(
            f"Continuation source {directory} holds no failure receipt; only a "
            "receipt-bearing failed run may be continued."
        )
    receipt_bytes = receipt_path.read_bytes()
    observed = _sha256(receipt_bytes)
    if observed != source_receipt_sha256:
        raise ScreenInputError(
            f"The source receipt hashes to {observed}, but {source_receipt_sha256} "
            "was pinned; this is not the failed run that was authorized."
        )
    receipt = json.loads(receipt_bytes.decode("utf-8"))
    missing = [f for f in _REQUIRED_RECEIPT_FIELDS if f not in receipt]
    if missing:
        raise ScreenInputError(
            f"The source receipt is missing {missing}; it is not the V3-route "
            "receipt shape this continuation is designed and tested for."
        )
    if receipt["receipt_contract"] != RECEIPT_CONTRACT:
        raise ScreenInputError(
            f"The source receipt declares {receipt['receipt_contract']!r}; this "
            f"route continues {RECEIPT_CONTRACT!r} runs only."
        )
    if receipt["reason_code"] != ACCEPTED_SOURCE_REASON_CODE or (
        ACCEPTED_SOURCE_FAILURE_SIGNATURE not in str(receipt["detail"])
    ):
        raise ScreenInputError(
            f"The source stopped with reason {receipt['reason_code']!r} "
            f"({receipt['detail']!r}). This route continues exactly one shape — "
            f"a {ACCEPTED_SOURCE_REASON_CODE} carrying "
            f"{ACCEPTED_SOURCE_FAILURE_SIGNATURE!r} — because that is the shape "
            "whose completed prefix has been shown reusable. Any other failure "
            "needs its own design and its own tests."
        )
    archive_path = directory / RAW_RESPONSES_FILENAME
    if not archive_path.is_file():
        raise ScreenInputError(
            f"Continuation source {directory} holds no raw-response archive; "
            "there is no evidence to reuse."
        )
    archive_bytes = archive_path.read_bytes()
    entries = [
        json.loads(line)
        for line in _decode_utf8(archive_bytes, RAW_RESPONSES_FILENAME).splitlines()
        if line.strip()
    ]
    completed = receipt["records_completed_before_failure"]
    if len(entries) != completed or receipt["raw_responses_captured"] != completed:
        raise ScreenInputError(
            f"The source archive holds {len(entries)} responses but the receipt "
            f"declares {completed} completed rows and "
            f"{receipt['raw_responses_captured']} captured; a prefix that does "
            "not agree with its own receipt is not reusable."
        )
    if completed < 1:
        raise ScreenInputError(
            "The source completed no rows; there is no prefix to reuse."
        )
    if receipt["stopping_row_index"] != completed + 1:
        raise ScreenInputError(
            f"The source stopped at row {receipt['stopping_row_index']} with "
            f"{completed} completed; a continuation needs a contiguous prefix "
            "ending exactly where the run stopped."
        )
    # The stopping row must have left no archived response: it is re-sent whole.
    stopping = (receipt["stopping_cik"], receipt["stopping_accession"])
    if any((e["cik"], e["accession"]) == stopping for e in entries):
        raise ScreenInputError(
            f"The source archive contains the stopping row {stopping}; the "
            "prefix must end before it so the row can be re-sent cleanly."
        )
    # Under the V3 route countTokens is one un-retried send per attempted row,
    # so the count/generate split follows from the receipt's aggregates: the
    # stopping row measured its input once and never reached generation.
    generate_entries = receipt["provider_attempts_made"]
    count_entries = receipt["external_requests_made"] - generate_entries
    if count_entries != completed + 1:
        raise ScreenInputError(
            f"The source made {count_entries} countTokens sends for "
            f"{completed} completed rows; the countTokens-timeout shape spends "
            "exactly one measurement per attempted row."
        )
    if generate_entries < completed:
        raise ScreenInputError(
            f"The source made {generate_entries} generate attempts for "
            f"{completed} completed rows; every completed row generated at "
            "least once."
        )
    ids = {e["raw_response_id"] for e in entries}
    if len(ids) != len(entries):
        raise ScreenInputError(
            "The source archive carries duplicate raw_response_ids; a reused "
            "prefix must address each row exactly once."
        )
    for entry in entries:
        if _sha256(entry["raw_response"].encode("utf-8")) != entry["raw_response_sha256"]:
            raise ScreenInputError(
                f"Source response {entry['raw_response_id']} no longer matches "
                "its recorded digest; the archive has drifted."
            )
    return SourcePrefix(
        run_dir=directory,
        run_id=receipt["run_id"],
        receipt=receipt,
        receipt_sha256=observed,
        archive_bytes=archive_bytes,
        archive_sha256=_sha256(archive_bytes),
        entries=entries,
    )


def revalidate_source_prefix(
    prefix: SourcePrefix,
    *,
    packets: list[dict],
    prompt_text: str,
    model_route: dict,
) -> tuple[list[dict], dict[str, int]]:
    """Rebuild the prefix rows from evidence, refusing anything unearned.

    Each archived response is re-rendered against its own packet, so the
    ``P001``-style references resolve from a freshly derived map rather than a
    stored one, and then goes through the unchanged strict validator. The
    outcome is recomputed, never copied: a response that no longer validates
    becomes ``model_evidence_unverified`` here exactly as it would in a fresh
    run.
    """
    if len(prefix.entries) > len(packets):
        raise ScreenInputError(
            f"The source prefix holds {len(prefix.entries)} rows but the "
            f"selection covers {len(packets)}; the prefix is not a prefix."
        )
    records: list[dict] = []
    rejected = {code: 0 for code in REJECTION_REASON_CODES}
    for index, entry in enumerate(prefix.entries):
        packet = packets[index]
        if (entry["cik"], entry["accession"]) != (packet["cik"], packet["accession"]):
            raise ScreenInputError(
                f"Source row {index + 1} is cik={entry['cik']} "
                f"accession={entry['accession']}, but the selection's row "
                f"{index + 1} is cik={packet['cik']} "
                f"accession={packet['accession']}; a reusable prefix maps onto "
                "the selection in order, with nothing skipped, reordered, "
                "duplicated or foreign."
            )
        rendered, refs = render_diagnostic_prompt_with_citation_refs(
            prompt_text, packet
        )
        base = {
            "record_contract": RECORD_CONTRACT,
            "cik": packet["cik"],
            "company_id": packet["company_id"],
            "accession": packet["accession"],
            "form": packet["form"],
            "baseline_filing_date": packet["baseline_filing_date"],
            "source_id": packet["source_id"],
            "packet_sha256": packet["packet_sha256"],
            "prompt_sha256": _sha256(rendered.encode("utf-8")),
            "model_route": dict(model_route),
            "raw_response_id": entry["raw_response_id"],
            "raw_response_sha256": entry["raw_response_sha256"],
            "row_provenance": {
                "origin": "reused_source_prefix",
                "source_run_id": prefix.run_id,
                "source_raw_response_id": entry["raw_response_id"],
                "source_raw_responses_sha256": prefix.archive_sha256,
                "source_receipt_sha256": prefix.receipt_sha256,
            },
        }
        try:
            output = _validate_row_output(
                resolve_diagnostic_citation_refs(entry["raw_response"], refs, packet),
                packet,
            )
        except _RowValidationFailure as exc:
            rejected[exc.reason_code] += 1
            base.update(
                record_kind="model_evidence_unverified",
                screen_status=None,
                screen_output=None,
                failure_reason_code=exc.reason_code,
                failure_detail=_detail(exc.detail),
            )
        else:
            base.update(
                record_kind="screened_packet",
                screen_status=output.screen_status,
                screen_output=output.model_dump(mode="json"),
                failure_reason_code=None,
                failure_detail=None,
            )
        records.append(base)
    return records, rejected


@dataclass
class _Preflight:
    authorization: dict
    enablement: dict
    contract_digest: str
    endpoints: dict
    prompt_text: str
    prompt_sha256: str
    inputs: Any
    selection: dict
    selection_sha256: str
    packets: list[dict]
    prefix: SourcePrefix
    prefix_records: list[dict]
    prefix_rejected: dict[str, int]
    suffix: list[dict]
    model_route: dict


def _preflight(
    *,
    root: Path,
    packet_manifest_path: str | Path,
    selection_artifact_path: str | Path,
    governance_root: Path,
    authorization_reference: str,
    authorization_sha256: str,
    source_run_dir: str | Path,
    source_receipt_sha256: str,
    clock: Callable[[], datetime],
) -> _Preflight:
    """Everything provable, proven, before any output or network exists."""
    authorization, _ = _hydrate_pinned(
        governance_root, authorization_reference, authorization_sha256,
        "screen continuation authorization",
    )
    _validate(
        authorization, _load_schema(root, AUTHORIZATION_SCHEMA),
        "Screen continuation authorization",
    )
    enablement, _ = _hydrate_pinned(
        governance_root,
        authorization["screen_adapter_enablement_reference"],
        authorization["screen_adapter_enablement_sha256"],
        "screen adapter enablement",
    )
    _validate(
        enablement, _load_schema(root, ENABLEMENT_SCHEMA_RELATIVE_PATH),
        "Screen adapter enablement",
    )
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
    model_route = {
        "provider": contract["model_provider"],
        "model_label": contract["model_name"],
    }
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
    ):
        raise ScreenInputError(
            "Authorization route or policy binding differs from this route's "
            "committed provider and screen policies."
        )
    if (
        authorization["count_attempts_per_row"] != SCREEN_COUNT_MAX_ATTEMPTS_V2
        or authorization["generate_attempts_per_row"] != SCREEN_GENERATE_MAX_ATTEMPTS
        or authorization["external_requests_per_row"]
        != SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2
    ):
        raise ScreenInputError(
            "The authorization does not name this route's per-row send policy "
            f"({SCREEN_COUNT_MAX_ATTEMPTS_V2} count, "
            f"{SCREEN_GENERATE_MAX_ATTEMPTS} generate, "
            f"{SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2} external)."
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
    prompt_raw = (root / PROMPT_PATH).read_bytes()
    prompt_sha = _sha256(prompt_raw)
    if prompt_sha != authorization["prompt_template_sha256"]:
        raise ScreenInputError(
            "Authorization does not bind the committed V5 screen prompt bytes."
        )
    inputs = load_packet_run(root, packet_manifest_path)
    if inputs.manifest_sha256 != authorization["packet_manifest_sha256"]:
        raise ScreenInputError("Authorization binds a different packet cohort.")
    selection, selection_sha = load_screen_selection(root, selection_artifact_path)
    if (
        selection_sha != authorization["selection_artifact_sha256"]
        or selection["selection_kind"] != authorization["selection_kind"]
        or selection["packet_manifest_sha256"] != inputs.manifest_sha256
    ):
        raise ScreenInputError(
            "Selection and authorization do not bind the loaded packet cohort "
            "identically."
        )
    if selection["selection_kind"] != "full_cohort":
        raise ScreenInputError(
            "A continuation runs the full cohort; a sampled selection is a "
            "different measurement."
        )
    packets = list(inputs.packets)

    # --- the source, named and pinned -------------------------------------
    prefix = load_continuation_source(
        source_run_dir, source_receipt_sha256=source_receipt_sha256
    )
    if prefix.receipt_sha256 != authorization["source_receipt_sha256"]:
        raise ScreenInputError(
            "The source receipt is not the one the authorization binds."
        )
    if prefix.archive_sha256 != authorization["source_raw_responses_sha256"]:
        raise ScreenInputError(
            f"The source archive hashes to {prefix.archive_sha256}, but the "
            f"authorization binds {authorization['source_raw_responses_sha256']}."
        )
    if prefix.run_id != authorization["source_run_id"]:
        raise ScreenInputError(
            f"The source run is {prefix.run_id!r}, but the authorization names "
            f"{authorization['source_run_id']!r}."
        )
    if prefix.receipt["authorization_sha256"] != authorization[
        "source_authorization_sha256"
    ]:
        raise ScreenInputError(
            "The source receipt names a different parent authorization than "
            "the one this continuation binds."
        )
    # The parent's own grant, by pin: the prefix is reusable only if it was
    # produced under bindings identical to the ones in force now.
    parent, _ = _hydrate_pinned(
        governance_root,
        authorization["source_authorization_reference"],
        authorization["source_authorization_sha256"],
        "source screen authorization",
    )
    for field_name in ("packet_manifest_sha256", "prompt_template_sha256",
                       "selection_artifact_sha256", "selection_kind",
                       "provider_client_contract_reference",
                       "provider_client_contract_sha256", "vertex_project",
                       "vertex_location", "model_route", "retry_policy_version",
                       "rate_limit_policy_version",
                       "screen_generate_retry_policy_version"):
        if parent.get(field_name) != authorization.get(field_name):
            raise ScreenInputError(
                f"The parent grant and this continuation disagree about "
                f"{field_name}; the prefix was produced under different rules "
                "and may not be reused."
            )
    if sorted(parent.get("endpoint_allowlist", [])) != sorted(
        authorization["endpoint_allowlist"]
    ):
        raise ScreenInputError(
            "The parent grant and this continuation disagree about the "
            "endpoint allowlist; the prefix was produced under different rules."
        )

    # --- revalidate every reused row, before anything exists ---------------
    prefix_records, prefix_rejected = revalidate_source_prefix(
        prefix, packets=packets, prompt_text=_decode_utf8(prompt_raw, "V5 prompt"),
        model_route=model_route,
    )
    suffix = packets[len(prefix_records):]
    if not suffix:
        raise ScreenInputError(
            "The source prefix already covers the whole cohort; there is "
            "nothing to continue."
        )
    # The first row this run sends must be exactly the parent's stopping row.
    if (suffix[0]["cik"], suffix[0]["accession"]) != (
        prefix.receipt["stopping_cik"], prefix.receipt["stopping_accession"]
    ):
        raise ScreenInputError(
            "The first unreused row is not the parent's stopping row; the "
            "continuation would skip or repeat work."
        )

    # --- caps, all derived from the two populations ------------------------
    reused, called, cohort = len(prefix_records), len(suffix), len(packets)
    if (
        authorization["logical_row_cap"] != cohort
        or authorization["reused_prefix_row_cap"] != reused
        or authorization["model_called_row_cap"] != called
        or reused + called != cohort
    ):
        raise ScreenInputError(
            f"The authorization states {authorization['logical_row_cap']} "
            f"cohort / {authorization['reused_prefix_row_cap']} reused / "
            f"{authorization['model_called_row_cap']} called, but the inputs "
            f"derive {cohort} / {reused} / {called}."
        )
    if authorization["count_attempt_cap"] != screen_count_attempt_cap(called):
        raise ScreenInputError(
            f"count_attempt_cap must be exactly {screen_count_attempt_cap(called)} "
            f"(model-called rows x {SCREEN_COUNT_MAX_ATTEMPTS_V2})."
        )
    if authorization["provider_attempt_cap"] != screen_generate_attempt_cap(called):
        raise ScreenInputError(
            f"provider_attempt_cap must be exactly "
            f"{screen_generate_attempt_cap(called)} (model-called rows x "
            f"{SCREEN_GENERATE_MAX_ATTEMPTS})."
        )
    if authorization["budget_max_external_requests"] != screen_external_request_cap_v2(
        called
    ):
        raise ScreenInputError(
            f"budget_max_external_requests must be exactly "
            f"{screen_external_request_cap_v2(called)} (model-called rows x "
            f"{SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2})."
        )
    breaker = authorization["max_model_evidence_unverified"]
    if breaker > cohort:
        raise ScreenInputError(
            "The model-evidence breaker cannot exceed the cohort row count."
        )
    inherited = sum(prefix_rejected.values())
    if inherited > breaker:
        raise ScreenInputError(
            f"The reused prefix alone carries {inherited} unverified rows "
            f"against a breaker of {breaker}; this continuation cannot "
            "complete and does not start. A continuation inherits its parent's "
            "unverified rows and must be authorized to carry them."
        )
    return _Preflight(
        authorization, enablement, digest, endpoints,
        _decode_utf8(prompt_raw, "V5 prompt"), prompt_sha, inputs, selection,
        selection_sha, packets, prefix, prefix_records, prefix_rejected, suffix,
        model_route,
    )


def run_lineage_screen_continuation(
    *,
    repo_root: str | Path,
    packet_manifest_path: str | Path,
    selection_artifact_path: str | Path,
    governance_root: str | Path,
    authorization_reference: str,
    authorization_sha256: str,
    source_run_dir: str | Path,
    source_receipt_sha256: str,
    output_dir: str | Path,
    run_id: str,
    clock: Callable[[], datetime],
    dry_run: bool = False,
    client_factory: Any = None,
    sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    """Continue one named failed run into a fresh authoritative cohort."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError("Invalid run id.")
    pre = _preflight(
        root=root,
        packet_manifest_path=packet_manifest_path,
        selection_artifact_path=selection_artifact_path,
        governance_root=Path(governance_root),
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256,
        source_run_dir=source_run_dir,
        source_receipt_sha256=source_receipt_sha256,
        clock=clock,
    )
    planned_insufficient = len(pre.inputs.failures)
    if dry_run:
        for packet in pre.suffix:
            render_diagnostic_prompt_with_citation_refs(pre.prompt_text, packet)
        return ScreenRunResult(
            run_id, None, True, "dry_run", len(pre.packets), planned_insufficient,
            request_accounting={
                "cohort_rows": len(pre.packets),
                "reused_prefix_rows": len(pre.prefix_records),
                "model_called_rows": len(pre.suffix),
                "count_attempt_cap": pre.authorization["count_attempt_cap"],
                "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
                "external_request_cap":
                    pre.authorization["budget_max_external_requests"],
            },
        )
    connector = VertexGeminiScreenV4(
        vertex_project=pre.authorization["vertex_project"],
        vertex_location=pre.authorization["vertex_location"],
        expected_authorization_sha256=authorization_sha256,
        max_provider_requests=SCREEN_GENERATE_MAX_ATTEMPTS,
        endpoint_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
        client_factory=client_factory,
        sleep=sleep,
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
    result = ScreenRunResult(
        run_id, run_dir, False, "failed", len(pre.packets), planned_insufficient
    )
    budget = ScreenCohortBudgetV3(
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
        # Only the suffix is screenable: naming a reused row here would let a
        # row that is already recorded be sent again.
        packet_sha_by_key={
            (p["cik"], p["accession"]): p["packet_sha256"] for p in pre.suffix
        },
        prompt_template_sha256=pre.prompt_sha256,
        ledger=ledger,
    )
    # Capture directories are named by cohort ordinal, not suffix ordinal, so a
    # human reading the evidence sees row 3,940 as 03940.
    adapter._row_ordinal = len(pre.prefix_records)

    # The new archive opens with the parent's bytes, verbatim. Nothing is
    # relabelled: each reused line keeps the id it was written under, which is
    # what makes its provenance readable rather than asserted.
    archive_path = run_dir / RAW_RESPONSES_FILENAME
    archive = os.fdopen(
        os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), "wb"
    )
    archive.write(pre.prefix.archive_bytes)
    archive.flush()
    os.fsync(archive.fileno())

    records: list[dict] = list(pre.prefix_records)
    rejected = dict(pre.prefix_rejected)
    called_rows = 0
    count_attempts_made = 0
    generate_attempts_made = 0
    rows_count_retried = 0
    rows_generate_retried = 0

    def fail(reason: str, detail: str, packet: dict, *,
             stopping_row_index: int | None = None,
             records_completed_before_failure: int | None = None) -> ScreenRunResult:
        archive.flush()
        os.fsync(archive.fileno())
        archive.close()
        generate_entries = sum(
            e["operation_label"] == "generate_content" for e in ledger
        )
        receipt = {
            "receipt_contract": RECEIPT_CONTRACT,
            "run_id": run_id,
            "run_kind": RUN_KIND,
            "reason_code": reason,
            "detail": _detail(detail),
            "stopping_cik": packet["cik"],
            "stopping_accession": packet["accession"],
            "stopping_row_index": (
                len(records) + 1 if stopping_row_index is None else stopping_row_index
            ),
            "records_completed_before_failure": (
                len(records)
                if records_completed_before_failure is None
                else records_completed_before_failure
            ),
            "reused_prefix_rows": len(pre.prefix_records),
            "model_called_rows_attempted": called_rows,
            "external_requests_made": len(ledger),
            "count_attempts_made": len(ledger) - generate_entries,
            "provider_attempts_made": generate_entries,
            "count_attempt_cap": pre.authorization["count_attempt_cap"],
            "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
            "count_attempts_per_row": SCREEN_COUNT_MAX_ATTEMPTS_V2,
            "generate_attempt_cap_per_row": SCREEN_GENERATE_MAX_ATTEMPTS,
            "authorization_sha256": authorization_sha256,
            "source_run_id": pre.prefix.run_id,
            "source_receipt_sha256": pre.prefix.receipt_sha256,
            "run_timestamp": clock().isoformat(),
            "retention_note": (
                "Non-authoritative failed continuation run: no records JSONL, "
                "no capture ledger and no manifest exist here. The reused "
                "prefix bytes present in this directory's archive remain the "
                "parent run's evidence and confer no authority. This directory "
                "is immutable; a further attempt requires a new run id and a "
                "new authorization."
            ),
        }
        try:
            write_bytes_once(
                run_dir / FAILURE_RECEIPT_FILENAME,
                (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                what="continuation failure receipt",
            )
        except WriteOnceError as exc:
            raise ScreenInputError(str(exc)) from exc
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        result.receipt = receipt
        return result

    for packet in pre.suffix:
        rendered, refs = render_diagnostic_prompt_with_citation_refs(
            pre.prompt_text, packet
        )
        called_rows += 1
        before = len(ledger)
        try:
            raw = adapter.screen(
                rendered, cik=packet["cik"], accession=packet["accession"]
            )
        except ScreenProviderTerminalError as exc:
            spent = ledger[before:]
            count_attempts_made += sum(
                e["operation_label"] == "count_tokens" for e in spent
            )
            generate_attempts_made += sum(
                e["operation_label"] == "generate_content" for e in spent
            )
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
        archive.write(
            (_canonical_line({
                "raw_response_id": response_id,
                "cik": packet["cik"],
                "accession": packet["accession"],
                "raw_response": raw,
                "raw_response_sha256": raw_sha,
            }) + "\n").encode("utf-8")
        )
        archive.flush()
        os.fsync(archive.fileno())
        base = {
            "record_contract": RECORD_CONTRACT,
            "cik": packet["cik"],
            "company_id": packet["company_id"],
            "accession": packet["accession"],
            "form": packet["form"],
            "baseline_filing_date": packet["baseline_filing_date"],
            "source_id": packet["source_id"],
            "packet_sha256": packet["packet_sha256"],
            "prompt_sha256": _sha256(rendered.encode("utf-8")),
            "model_route": dict(adapter.model_route),
            "raw_response_id": response_id,
            "raw_response_sha256": raw_sha,
            "row_provenance": {
                "origin": "model_called",
                "source_run_id": None,
                "source_raw_response_id": None,
                "source_raw_responses_sha256": None,
                "source_receipt_sha256": None,
            },
        }
        try:
            output = _validate_row_output(
                resolve_diagnostic_citation_refs(raw, refs, packet), packet
            )
        except _RowValidationFailure as exc:
            rejected[exc.reason_code] += 1
            base.update(
                record_kind="model_evidence_unverified",
                screen_status=None,
                screen_output=None,
                failure_reason_code=exc.reason_code,
                failure_detail=_detail(exc.detail),
            )
            if sum(rejected.values()) > pre.authorization[
                "max_model_evidence_unverified"
            ]:
                records.append(base)
                return fail(
                    "model_evidence_budget_exhausted",
                    "Declared model-evidence breaker exceeded across the cohort.",
                    packet,
                    stopping_row_index=len(records),
                    records_completed_before_failure=len(records) - 1,
                )
        else:
            base.update(
                record_kind="screened_packet",
                screen_status=output.screen_status,
                screen_output=output.model_dump(mode="json"),
                failure_reason_code=None,
                failure_detail=None,
            )
        records.append(base)
    archive.flush()
    os.fsync(archive.fileno())
    archive.close()

    for failure in pre.inputs.failures:
        records.append({
            "record_contract": RECORD_CONTRACT,
            "record_kind": "insufficient_evidence",
            "cik": failure["cik"],
            "company_id": failure["company_id"],
            "accession": failure["accession"],
            "form": failure["form"],
            "baseline_filing_date": None,
            "source_id": failure["source_id"],
            "packet_sha256": None,
            "screen_status": None,
            "prompt_sha256": None,
            "model_route": None,
            "raw_response_id": None,
            "raw_response_sha256": None,
            "screen_output": None,
            "failure_reason_code": failure["reason_code"],
            "failure_detail": failure["detail"],
            "row_provenance": {
                "origin": "packet_build_failure",
                "source_run_id": None,
                "source_raw_response_id": None,
                "source_raw_responses_sha256": None,
                "source_receipt_sha256": None,
            },
        })

    validator = Draft202012Validator(
        _load_schema(root, RECORD_SCHEMA), format_checker=FormatChecker()
    )
    for row in records:
        errors = sorted(validator.iter_errors(row), key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Built continuation record violates {RECORD_CONTRACT} at "
                f"{errors[0].json_path}: {errors[0].message}"
            )

    archive_raw = archive_path.read_bytes()
    archive_entries = [
        json.loads(line)
        for line in _decode_utf8(archive_raw, RAW_RESPONSES_FILENAME).splitlines()
        if line.strip()
    ]
    entries_by_id = {e["raw_response_id"]: e for e in archive_entries}
    persisted = [e for e in ledger if e["capture_disposition"] == "raw_persisted"]
    capture_ok = all(
        (run_dir / e["raw_reference"]).is_file()
        and _sha256((run_dir / e["raw_reference"]).read_bytes()) == e["raw_sha256"]
        for e in persisted
    )
    disk_refs = {
        str(p.relative_to(run_dir))
        for p in (run_dir / CAPTURES_DIRNAME).rglob("*")
        if p.is_file()
    } if (run_dir / CAPTURES_DIRNAME).exists() else set()
    reused = [r for r in records
              if r["row_provenance"]["origin"] == "reused_source_prefix"]
    called = [r for r in records if r["row_provenance"]["origin"] == "model_called"]
    screened = [r for r in records if r["record_kind"] == "screened_packet"]
    unverified = [r for r in records
                  if r["record_kind"] == "model_evidence_unverified"]
    insufficient = [r for r in records
                    if r["record_kind"] == "insufficient_evidence"]
    rollup = firm_rollup_v2(records)
    rollup_counts = {
        s: sum(v == s for v in rollup.values())
        for s in (*SCREEN_STATUSES, "MODEL_EVIDENCE_UNVERIFIED", "INSUFFICIENT_EVIDENCE")
    }
    counts = {
        "planned_rows": len(pre.packets) + planned_insufficient,
        "cohort_rows": len(pre.packets),
        "reused_prefix_rows": len(reused),
        "model_called_rows": len(called),
        "screened_packets": len(screened),
        "model_evidence_unverified": len(unverified),
        "insufficient_evidence": len(insufficient),
        "reused_screened_packets": sum(
            1 for r in reused if r["record_kind"] == "screened_packet"),
        "reused_model_evidence_unverified": sum(
            1 for r in reused if r["record_kind"] == "model_evidence_unverified"),
        "rejections_by_reason": rejected,
        "by_screen_status": {
            s: sum(r["screen_status"] == s for r in screened) for s in SCREEN_STATUSES
        },
        "firm_rollup": rollup_counts,
        "max_model_evidence_unverified":
            pre.authorization["max_model_evidence_unverified"],
    }
    count_entries = sum(e["operation_label"] == "count_tokens" for e in ledger)
    generate_entries = len(ledger) - count_entries
    reconciliation = {
        "records partition the retained rows": (
            len(records) == counts["planned_rows"]
            == len(screened) + len(unverified) + len(insufficient)
        ),
        "the cohort closes at every selected packet row exactly once": (
            len(reused) + len(called) == len(pre.packets)
            and {(r["cik"], r["accession"]) for r in reused + called}
            == {(p["cik"], p["accession"]) for p in pre.packets}
        ),
        "reused and called rows partition the cohort": (
            len(reused) == len(pre.prefix_records)
            and len(called) == len(pre.suffix)
        ),
        "the reused prefix cost this run no send": (
            count_entries + generate_entries == len(ledger)
            and all(e["row_ordinal"] > len(pre.prefix_records) for e in ledger)
        ),
        "the first sent row is the parent's stopping row": (
            not called
            or (called[0]["cik"], called[0]["accession"])
            == (pre.prefix.receipt["stopping_cik"],
                pre.prefix.receipt["stopping_accession"])
        ),
        "the archive opens with the parent archive byte for byte": (
            archive_raw.startswith(pre.prefix.archive_bytes)
        ),
        "the archive holds one line per model-called row plus the prefix": (
            len(archive_entries) == len(pre.prefix_records) + len(called)
        ),
        "every model-bearing record resolves in the archive and re-hashes": all(
            (entry := entries_by_id.get(r["raw_response_id"])) is not None
            and _sha256(entry["raw_response"].encode("utf-8"))
            == entry["raw_response_sha256"] == r["raw_response_sha256"]
            for r in screened + unverified
        ),
        "every reused record keeps its source binding": all(
            r["row_provenance"]["source_run_id"] == pre.prefix.run_id
            and r["row_provenance"]["source_raw_responses_sha256"]
            == pre.prefix.archive_sha256
            and r["row_provenance"]["source_receipt_sha256"]
            == pre.prefix.receipt_sha256
            for r in reused
        ),
        "every screened row's quotes resolved verbatim": all(
            r["screen_output"] is not None and r["failure_reason_code"] is None
            for r in screened
        ),
        "every unverified row names its closed reason and claims no status": all(
            r["screen_status"] is None and r["screen_output"] is None
            and r["failure_reason_code"] in REJECTION_REASON_CODES
            for r in unverified
        ),
        "unverified rows are counted, never omitted or relabelled": (
            sum(rejected.values()) == len(unverified)
        ),
        "the whole-cohort breaker was not exceeded": (
            len(unverified) <= pre.authorization["max_model_evidence_unverified"]
        ),
        "capture files rehash to their ledger lines": capture_ok,
        "no orphan capture file exists": (
            disk_refs == {e["raw_reference"] for e in persisted}
        ),
        "count and generate sends partition external requests": (
            count_entries + generate_entries == len(ledger)
        ),
        "no row exceeded its send ceilings": (
            count_attempts_made <= pre.authorization["count_attempt_cap"]
            and generate_attempts_made <= pre.authorization["provider_attempt_cap"]
            and len(ledger) <= pre.authorization["budget_max_external_requests"]
        ),
        "model unverified blocks firm-negative": all(
            rollup[r["cik"]] != "LIKELY_INELIGIBLE" for r in unverified
        ),
        "the prompt template hash equals the authorization's": (
            pre.prompt_sha256 == pre.authorization["prompt_template_sha256"]
        ),
    }
    if not all(reconciliation.values()):
        raise ScreenInputError(
            "Continuation reconciliation failed; no records JSONL, no capture "
            "ledger and no manifest are written. Failed identities: "
            f"{sorted(k for k, v in reconciliation.items() if not v)}."
        )
    records_bytes = ("\n".join(_canonical_line(r) for r in records) + "\n").encode("utf-8")
    ledger_bytes = ("\n".join(_canonical_line(r) for r in ledger) + "\n").encode("utf-8")
    try:
        write_bytes_once(run_dir / RECORDS_FILENAME, records_bytes,
                         what="continuation screen records")
        write_bytes_once(run_dir / CAPTURE_LEDGER_FILENAME, ledger_bytes,
                         what="continuation capture ledger")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    request_accounting = {
        "model_called_row_cap": pre.authorization["model_called_row_cap"],
        "count_attempt_cap": pre.authorization["count_attempt_cap"],
        "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
        "external_request_cap": pre.authorization["budget_max_external_requests"],
        "count_attempts_per_row": SCREEN_COUNT_MAX_ATTEMPTS_V2,
        "generate_attempts_per_row": SCREEN_GENERATE_MAX_ATTEMPTS,
        "external_requests_per_row": SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2,
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
    manifest = {
        "manifest_contract": MANIFEST_CONTRACT,
        "run_kind": RUN_KIND,
        "run_id": run_id,
        "packet_manifest_path": str(packet_manifest_path),
        "packet_manifest_sha256": pre.inputs.manifest_sha256,
        "packet_run_id": pre.inputs.manifest["run_id"],
        "packets_jsonl_sha256": pre.inputs.packets_jsonl_sha256,
        "packet_failures_jsonl_sha256": pre.inputs.failures_jsonl_sha256,
        "prompt_template_path": PROMPT_PATH,
        "prompt_template_sha256": pre.prompt_sha256,
        "authorization_id": pre.authorization["authorization_id"],
        "authorization_sha256": authorization_sha256,
        "screen_adapter_enablement_sha256":
            pre.authorization["screen_adapter_enablement_sha256"],
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": pre.contract_digest,
        "envelope_text_extraction_rule": ENVELOPE_TEXT_EXTRACTION_RULE,
        "selection": {
            "selection_artifact_path": str(selection_artifact_path),
            "selection_artifact_sha256": pre.selection_sha256,
            "selection_kind": pre.selection["selection_kind"],
            "sampling_algorithm": pre.selection["sampling"]["algorithm"],
            "seed": pre.selection["sampling"]["seed"],
            "rows_selected": len(pre.packets),
        },
        "continuation": {
            "source_run_id": pre.prefix.run_id,
            "source_run_path": str(source_run_dir),
            "source_receipt_sha256": pre.prefix.receipt_sha256,
            "source_raw_responses_sha256": pre.prefix.archive_sha256,
            "source_authorization_sha256":
                pre.authorization["source_authorization_sha256"],
            "reused_prefix_rows": len(reused),
            "first_model_called_row_ordinal": len(reused) + 1,
            "source_archive_is_byte_identical_prefix": True,
        },
        "parent_telemetry": {
            "per_attempt_telemetry_available": False,
            "records_completed_before_failure":
                pre.prefix.receipt["records_completed_before_failure"],
            "raw_responses_captured": pre.prefix.receipt["raw_responses_captured"],
            "external_requests_made": pre.prefix.receipt["external_requests_made"],
            "provider_attempts_made": pre.prefix.receipt["provider_attempts_made"],
            "reason_code": pre.prefix.receipt["reason_code"],
            "stopping_row_index": pre.prefix.receipt["stopping_row_index"],
        },
        "provider": {
            "name": adapter.name,
            "connector": SCREEN_CONNECTOR_V4_ID,
            "model_route": dict(adapter.model_route),
        },
        "generate_retry_policy": {
            "policy_version": SCREEN_GENERATE_RETRY_POLICY_VERSION,
            "generate_max_attempts": SCREEN_GENERATE_MAX_ATTEMPTS,
            "generate_retry_delays_seconds": list(SCREEN_GENERATE_RETRY_DELAYS_SECONDS),
            "jitter": SCREEN_RETRY_JITTER,
        },
        "count_retry_policy": {
            "policy_version": SCREEN_COUNT_RETRY_POLICY_VERSION,
            "count_max_attempts": SCREEN_COUNT_MAX_ATTEMPTS_V2,
            "count_retry_delays_seconds": list(SCREEN_COUNT_RETRY_DELAYS_SECONDS),
            "jitter": SCREEN_RETRY_JITTER,
        },
        "screen_record_order": RECORD_ORDER,
        "firm_rollup_rule": ROLLUP_RULE,
        "baseline_cutoff": pre.inputs.baseline_cutoff,
        "counts": counts,
        "request_accounting": request_accounting,
        "reconciliation": reconciliation,
        "output_hashes": {
            RECORDS_FILENAME: _sha256(records_bytes),
            RAW_RESPONSES_FILENAME: _sha256(archive_raw),
            CAPTURE_LEDGER_FILENAME: _sha256(ledger_bytes),
        },
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "universe_screen_record_v3": "0.3.0",
            "universe_screen_continuation_manifest": "0.8.0",
            "universe_screen_continuation_authorization": "0.1.0",
            "universe_screen_selection": "0.1.0",
            "universe_screen_adapter_enablement": "0.1.0",
            "baseline_packet_manifest_v5": "0.5.0",
            "universe_baseline_packet_v2": "0.2.0",
        },
        "limitations": [
            "Reused rows were revalidated by the same strict rules as fresh "
            "rows, but their wire-level evidence lives in the parent run: no "
            "per-attempt token, cost or capture telemetry exists for them, and "
            "none is claimed here.",
            "The capture ledger beside this manifest covers model-called rows "
            "only; its row ordinals are cohort ordinals.",
            "MODEL_EVIDENCE_UNVERIFIED is a visible review state, not a screen "
            "result or exclusion, and reused unverified rows count against this "
            "run's breaker exactly as fresh ones do.",
            "The parent run remains receipt-bearing, immutable and permanently "
            "non-authoritative; only this manifest may be consumed.",
        ],
    }
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA), "Continuation manifest")
    try:
        write_bytes_once(
            run_dir / SCREEN_MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="continuation screen manifest",
        )
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    result.status = "completed"
    result.counts = counts
    result.reconciliation = reconciliation
    result.request_accounting = request_accounting
    result.manifest_path = run_dir / SCREEN_MANIFEST_FILENAME
    return result
