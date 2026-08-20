"""Diagnostic canary successor of the live high-recall screen (ADR-112).

Three governed canaries stopped at rows 1, 4 and 28. Each stop was correct —
the authoritative runner is all-or-nothing by contract, and each defect it
caught was real — but the consequence is that a canary measures *the next
defect* rather than the distribution of defects. This module measures the
distribution instead, without touching the authoritative path.

**It is not a permissive variant of the authoritative runner.** Per row it
applies the *identical* strict validator, imported unchanged from the live
module; it is strictly less permissive in what it will call a result. What
differs is only the policy on a failed row: the authoritative runner aborts
the run, this one records the failure and continues, so one run reports what
100 rows actually do.

**Authority boundary — structural, not declarative.** A diagnostic run is
unusable as an authoritative input for four independent reasons:

* its outputs carry diagnostic filenames, so
  :func:`~dynamic_ai_products.lineage_screen.require_authoritative_screen_run`
  and :func:`~dynamic_ai_products.lineage_screen_live.require_promotable_screen_run`
  both refuse the directory for having no ``universe_screen_manifest.json``;
* its record and manifest contracts share no ``$id`` or field set with the
  authoritative ones, and every schema involved is closed, so they mutually
  reject;
* its manifest pins ``diagnostic_only``, ``promotable``, ``run_kind`` and
  ``selection_kind`` as consts no authoritative manifest can carry;
* it consumes a *separate* authorization contract, so an authorization
  minted for authoritative screening cannot silently authorize diagnostic
  collection, and vice versa.

**The continuation set is definitional, not a judgement.** A row is recorded
and the run continues for exactly the reason codes the shared row validator
can raise — ``invalid_model_json``, ``adapter_rejection``,
``quote_resolution_failure``, ``temporal_violation`` — and nothing else.
Every other failure reaches this runner as a different exception type and
hard-stops it with a governed receipt: governance, binding and hash
failures; provider terminal failures and retry exhaustion; envelope-level
failures (blocked, empty, multi-candidate, part-less, malformed), which are
transport-contract failures rather than model-output content; capture
persistence or integrity failures; cap, budget and wall-clock breaches; the
``max_rejected_rows`` circuit breaker; and any write-once or reconciliation
invariant. Raw-before-parse is unchanged: the verbatim response is archived
before validation, so a rejected row's evidence is retained in full and the
counters stay truthful.

**Rejected rows carry no result.** ``screen_output`` is null, there is no
screen-status field in the record contract at all, and the detail is bounded
and sanitized — which field or citation failed and how, never a copy of the
payload. The invalid payload lives exclusively in the hash-bound
raw-response archive, which every row binds by id and SHA-256.

This increment ships offline: every test injects a fake client factory, no
real SDK client is built, no credential is resolved, no socket is opened.
"""

from __future__ import annotations

import json
import os
import re
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
from dynamic_ai_products.providers.vertex_gemini_v2 import VertexGeminiProviderV2
from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

# Reused unchanged from the authoritative live route. Importing is not
# modifying: `lineage_screen_live` stays byte-identical and is pinned by SHA
# in the test suite.
from .lineage_screen_live import (
    CAPTURE_LEDGER_FILENAME,
    CAPTURES_DIRNAME,
    ENABLEMENT_SCHEMA_RELATIVE_PATH,
    ENVELOPE_TEXT_EXTRACTION_RULE,
    EXTERNAL_REQUESTS_PER_ROW,
    GENERATE_ATTEMPT_CAP_PER_ROW,
    LIVE_PROMPT_TEMPLATE_RELATIVE_PATH,
    ScreenCohortBudget,
    VertexLineageScreenProvider,
    _extract_envelope_text,
    _hydrate_pinned,
    _parse_moment,
    load_screen_selection,
)
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    FAILURE_RECEIPT_FILENAME,
    RAW_RESPONSES_FILENAME,
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
    render_lineage_screen_prompt,
)

__all__ = [
    "DIAGNOSTIC_MANIFEST_FILENAME",
    "DIAGNOSTIC_RECORDS_FILENAME",
    "REJECTION_REASON_CODES",
    "require_diagnostic_run",
    "run_lineage_screen_diagnostic",
]

# --- Filenames and closed vocabularies -------------------------------------------

#: Deliberately *not* the authoritative names. This is the primary structural
#: reason the authoritative and promotion loaders refuse a diagnostic run:
#: they look for ``universe_screen_manifest.json`` and find none.
DIAGNOSTIC_RECORDS_FILENAME = "universe_screen_diagnostic_records.jsonl"
DIAGNOSTIC_MANIFEST_FILENAME = "universe_screen_diagnostic_manifest.json"

RECORD_CONTRACT = "universe_screen_diagnostic_record@0.1.0"
MANIFEST_CONTRACT = "universe_screen_diagnostic_manifest@0.1.0"
AUTHORIZATION_CONTRACT = "universe_screen_diagnostic_authorization@0.1.0"
RUN_KIND = "diagnostic_canary"
SCREEN_STAGE = "universe_high_recall_screen"
RECORD_ORDER = "selection_row_order"

RECORD_SCHEMA_RELATIVE_PATH = "schemas/universe_screen_diagnostic_record.schema.json"
MANIFEST_SCHEMA_RELATIVE_PATH = (
    "schemas/universe_screen_diagnostic_manifest.schema.json"
)
AUTHORIZATION_SCHEMA_RELATIVE_PATH = (
    "schemas/universe_screen_diagnostic_authorization.schema.json"
)

#: Exactly the reason codes the shared strict row validator can raise. The
#: continuation set is this set, by construction rather than by choice.
REJECTION_REASON_CODES = (
    "invalid_model_json",
    "adapter_rejection",
    "quote_resolution_failure",
    "temporal_violation",
)

#: Rejection detail is bounded so a pathological response cannot inflate the
#: records file; the full payload stays in the raw archive.
REJECTION_DETAIL_MAX = 600

#: The closed vocabulary of diagnostic hard stops. Deliberately disjoint from
#: REJECTION_REASON_CODES: a value here ends the run and produces a receipt,
#: a value there produces a record and the run continues.
RECEIPT_REASON_CODES = (
    "provider_error",
    "rejected_row_budget_exhausted",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _bounded_detail(detail: str) -> str:
    """One line, sanitized, capped. Never a copy of the model payload."""
    flat = " ".join(str(detail).split())
    if len(flat) <= REJECTION_DETAIL_MAX:
        return flat
    return flat[: REJECTION_DETAIL_MAX - 3] + "..."


# --- Consumer gate ------------------------------------------------------------------


def require_diagnostic_run(run_dir: str | Path) -> Path:
    """Accept only a completed diagnostic run, and refuse everything else.

    This is the *only* loader that admits these directories. It refuses a
    receipt-bearing (hard-stopped) run, a manifest-less run, an authoritative
    run that wandered in, and any run whose output bytes no longer hash to
    the manifest's ``output_hashes``.
    """
    directory = Path(run_dir)
    if (directory / FAILURE_RECEIPT_FILENAME).exists():
        raise ScreenInputError(
            f"Diagnostic run {directory} holds a failure receipt; it is "
            "non-authoritative and incomplete, and may not be consumed."
        )
    if (directory / SCREEN_MANIFEST_FILENAME).exists():
        raise ScreenInputError(
            f"Run {directory} carries an authoritative screen manifest; it is "
            "not a diagnostic run and must be read through the authoritative "
            "loader."
        )
    manifest_path = directory / DIAGNOSTIC_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Diagnostic run {directory} has no diagnostic manifest; only a "
            "manifest-bearing run is complete."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_contract") != MANIFEST_CONTRACT:
        raise ScreenInputError(
            f"Diagnostic run {directory} declares contract "
            f"{manifest.get('manifest_contract')!r}, not {MANIFEST_CONTRACT}."
        )
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file():
            raise ScreenInputError(
                f"Diagnostic run output {filename} is missing beside its manifest."
            )
        observed = _sha256(target.read_bytes())
        if observed != recorded:
            raise ScreenInputError(
                f"Diagnostic run output {filename} hashes to {observed}, but "
                f"the manifest records {recorded}; the run is not consumable."
            )
    return manifest_path


# --- Preflight -----------------------------------------------------------------------


@dataclass
class _DiagnosticPreflight:
    authorization: dict
    enablement: dict
    contract_digest: str
    endpoints: dict
    prompt_template_path: str
    prompt_template_text: str
    prompt_template_sha256: str
    inputs: Any
    selection: dict
    selection_sha256: str
    selected_packets: list[dict]
    max_rejected_rows: int


def _diagnostic_preflight(
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
) -> _DiagnosticPreflight:
    """The ADR-109 validation order, against the diagnostic authorization.

    Every step runs before any output directory, SDK import, credential
    resolution or network send exists. The helpers are the live route's own;
    only the authorization contract differs, which is exactly what stops a
    live authorization from authorizing diagnostic collection.
    """
    # (2) The diagnostic authorization, by pin.
    authorization, _ = _hydrate_pinned(
        governance_root, authorization_reference, authorization_sha256,
        "screen diagnostic authorization",
    )
    _validate(
        authorization,
        _load_schema(root, AUTHORIZATION_SCHEMA_RELATIVE_PATH),
        "Screen diagnostic authorization",
    )
    # Belt and braces: the schema pins these as consts, and the runner
    # refuses anything else even if a schema were ever widened.
    if authorization["run_kind"] != RUN_KIND:
        raise ScreenInputError(
            f"The authorization declares run_kind {authorization['run_kind']!r}; "
            f"this runner performs {RUN_KIND!r} runs only."
        )
    if authorization["output_contract"] != RECORD_CONTRACT:
        raise ScreenInputError(
            "The authorization names a different output contract than "
            f"{RECORD_CONTRACT}."
        )
    if authorization["selection_kind"] != "canary_100":
        raise ScreenInputError(
            "A diagnostic run screens a canary_100 selection only; the full "
            "cohort is never diagnostic."
        )
    if authorization["diagnostic_only"] is not True or (
        authorization["promotable"] is not False
    ):
        raise ScreenInputError(
            "A diagnostic authorization must declare diagnostic_only true and "
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

    # (6) The prompt binding: committed bytes against the authorization.
    template_path = root / LIVE_PROMPT_TEMPLATE_RELATIVE_PATH
    if not template_path.is_file():
        raise ScreenInputError(
            f"Live screen prompt template not found: {template_path}"
        )
    template_raw = template_path.read_bytes()
    template_sha = _sha256(template_raw)
    if template_sha != authorization["prompt_template_sha256"]:
        raise ScreenInputError(
            f"The committed screen prompt template "
            f"({LIVE_PROMPT_TEMPLATE_RELATIVE_PATH}) hashes to "
            f"{template_sha}, but the authorization binds "
            f"{authorization['prompt_template_sha256']}. A stale or "
            "mismatched prompt authorization runs nothing."
        )

    # (7) The cohort, the selection, and the stated caps.
    inputs = load_packet_run(root, packet_manifest_path)
    if inputs.manifest_sha256 != authorization["packet_manifest_sha256"]:
        raise ScreenInputError(
            f"The packet manifest hashes to {inputs.manifest_sha256}, but the "
            f"authorization binds {authorization['packet_manifest_sha256']}; "
            "this is not the cohort that was authorized."
        )
    selection, selection_sha = load_screen_selection(root, selection_artifact_path)
    if selection_sha != authorization["selection_artifact_sha256"]:
        raise ScreenInputError(
            "The selection artifact is not the one the authorization binds."
        )
    if selection["selection_kind"] != "canary_100":
        raise ScreenInputError(
            "A diagnostic run screens a canary_100 selection only; the "
            "full-cohort selection kind is refused."
        )
    if selection["packet_manifest_sha256"] != inputs.manifest_sha256:
        raise ScreenInputError(
            "The selection artifact binds a different packet manifest than "
            "the one loaded; nothing is screened."
        )
    packets_by_key = {(p["cik"], p["accession"]): p for p in inputs.packets}
    seen: set[tuple[str, str]] = set()
    for row in selection["rows"]:
        key = (row["cik"], row["accession"])
        if key in seen:
            raise ScreenInputError(
                f"The selection lists cik={key[0]} accession={key[1]} twice."
            )
        seen.add(key)
        packet = packets_by_key.get(key)
        if packet is None:
            raise ScreenInputError(
                f"The selection names cik={key[0]} accession={key[1]}, which "
                "is not a valid packet row of this cohort."
            )
        if packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError(
                f"The selection pins packet sha {row['packet_sha256']} for "
                f"cik={key[0]}, but the cohort's packet hashes to "
                f"{packet['packet_sha256']}; refusing a drifted row."
            )
    # Selection row order is the diagnostic record order, so a rejection can
    # always be located by ordinal.
    selected = [packets_by_key[(r["cik"], r["accession"])]
                for r in selection["rows"]]

    if logical_request_cap != len(selected):
        raise ScreenInputError(
            f"logical_request_cap is {logical_request_cap}, but the selection "
            f"covers exactly {len(selected)} rows."
        )
    if authorization["logical_request_cap"] != logical_request_cap:
        raise ScreenInputError(
            "The operator-stated logical cap and the authorization disagree."
        )
    expected_attempt_cap = logical_request_cap * GENERATE_ATTEMPT_CAP_PER_ROW
    if provider_attempt_cap != expected_attempt_cap or (
        authorization["provider_attempt_cap"] != expected_attempt_cap
    ):
        raise ScreenInputError(
            f"provider_attempt_cap must be exactly {expected_attempt_cap} "
            f"(logical x {GENERATE_ATTEMPT_CAP_PER_ROW} generate attempts)."
        )
    expected_external = logical_request_cap * EXTERNAL_REQUESTS_PER_ROW
    if authorization["budget_max_external_requests"] != expected_external:
        raise ScreenInputError(
            f"budget_max_external_requests must be exactly {expected_external}."
        )
    max_rejected = authorization["max_rejected_rows"]
    if not isinstance(max_rejected, int) or isinstance(max_rejected, bool) or (
        max_rejected < 1
    ):
        raise ScreenInputError(
            "max_rejected_rows must be a positive integer circuit breaker."
        )
    if max_rejected > len(selected):
        raise ScreenInputError(
            f"max_rejected_rows {max_rejected} exceeds the {len(selected)} "
            "selected rows; a breaker that can never trip is not a breaker."
        )

    return _DiagnosticPreflight(
        authorization=authorization,
        enablement=enablement,
        contract_digest=contract_digest,
        endpoints=endpoints,
        prompt_template_path=LIVE_PROMPT_TEMPLATE_RELATIVE_PATH,
        prompt_template_text=_decode_utf8(template_raw, "Screen prompt template"),
        prompt_template_sha256=template_sha,
        inputs=inputs,
        selection=selection,
        selection_sha256=selection_sha,
        selected_packets=selected,
        max_rejected_rows=max_rejected,
    )


# --- The runner -------------------------------------------------------------------------


@dataclass
class DiagnosticRunResult(ScreenRunResult):
    """A screen run result carrying the diagnostic partition as well."""

    validated: int = 0
    rejected: int = 0
    rejections_by_reason: dict = field(default_factory=dict)


def run_lineage_screen_diagnostic(
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
    """Measure every selected row's outcome. Diagnostic only, never a screen."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError(
            f"Invalid run id {run_id!r}: only letters, digits, '.', '_', '-' "
            "are allowed (no path separators)."
        )
    pre = _diagnostic_preflight(
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
    manifest_schema = _load_schema(root, MANIFEST_SCHEMA_RELATIVE_PATH)

    if dry_run:
        for packet in pre.selected_packets:
            render_lineage_screen_prompt(pre.prompt_template_text, packet)
        return DiagnosticRunResult(
            run_id=run_id, run_dir=None, dry_run=True, status="dry_run",
            planned_screened=len(pre.selected_packets),
            planned_insufficient=0,
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
        planned_screened=len(pre.selected_packets), planned_insufficient=0,
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
        """Write the governed receipt and stop.

        The two positional counters default to the pre-record derivation,
        which is correct for every hard stop that happens *before* a row
        record exists: the failing row is the one after the last completed
        record. The circuit breaker is the one case where it is not — its
        triggering row has already been validated, appended, archived and
        counted as rejected — so that call passes both explicitly.
        """
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
            "run_kind": RUN_KIND,
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
                "Non-authoritative failed diagnostic run: no records JSONL, "
                "no capture ledger and no diagnostic manifest exist here — "
                "only the raw responses and wire captures taken before the "
                "stop. This directory is immutable, was never promotable, "
                "and may not be consumed by any loader; a retry requires a "
                "new run id and new authorization."
            ),
        }
        if reason_code not in RECEIPT_REASON_CODES:
            raise ScreenInputError(
                f"Internal error: receipt reason {reason_code!r} is outside "
                f"the closed diagnostic vocabulary {RECEIPT_REASON_CODES}."
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
        rendered = render_lineage_screen_prompt(pre.prompt_template_text, packet)
        prompt_sha256 = _sha256(rendered.encode("utf-8"))
        logical_requests_made += 1
        # Snapshotted BEFORE the send: the adapter settles this row's cost
        # inside screen(), so the delta afterwards is exactly this row's.
        cost_before = budget.cost_micros_settled
        try:
            raw_response = adapter.screen(
                rendered, cik=packet["cik"], accession=packet["accession"]
            )
        except ScreenProviderTerminalError as exc:
            # Provider, envelope, capture, budget and cap failures are all
            # hard stops: none of them is model-output content.
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
            # The identical strict validator the authoritative runner uses.
            output = _validate_row_output(raw_response, packet)
        except _RowValidationFailure as exc:
            rejections[exc.reason_code] = rejections.get(exc.reason_code, 0) + 1
            row.update(record_kind="rejected_output", screen_output=None,
                       rejection_reason_code=exc.reason_code,
                       rejection_detail=_bounded_detail(exc.detail))
        else:
            row.update(record_kind="validated_screen",
                       screen_output=output.model_dump(mode="json"),
                       rejection_reason_code=None, rejection_detail=None)
        # Settlement happened inside the adapter, so a rejected row's cost is
        # measured exactly like a validated one's.
        row["cost_micros"] = budget.cost_micros_settled - cost_before
        records.append(row)

        _, rejected_now = _counts_now()
        if rejected_now > pre.max_rejected_rows:
            # The triggering row is this one, and it is already measured,
            # archived and counted: rows 1..ordinal-1 completed before it.
            return _fail(
                "rejected_row_budget_exhausted",
                f"The declared circuit breaker of {pre.max_rejected_rows} "
                f"rejected rows was exceeded at row {ordinal}; the run stops "
                "with the distribution measured so far retained.",
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
                f"Built diagnostic record for cik={record['cik']} violates "
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
        "rows_selected": len(pre.selected_packets),
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
        "validated and rejected partition the selected rows": (
            len(validated_records) + len(rejected_records) == len(records)
            == len(pre.selected_packets)
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
        "shared accessions stay separate rows per cik": (
            len({(r["cik"], r["accession"]) for r in records}) == len(records)
        ),
        "per-row cost sums to the settled cohort cost": (
            sum(r["cost_micros"] for r in records) == budget.cost_micros_settled
        ),
    }
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            "Diagnostic reconciliation failed; no records JSONL, no capture "
            f"ledger and no manifest are written. Failed identities: {failed}."
        )

    records_payload = (
        "\n".join(_canonical_line(record) for record in records) + "\n"
    ).encode("utf-8")
    ledger_payload = (
        "\n".join(_canonical_line(entry) for entry in ledger) + "\n"
    ).encode("utf-8")
    try:
        write_bytes_once(run_dir / DIAGNOSTIC_RECORDS_FILENAME, records_payload,
                         what=f"diagnostic records {run_dir / DIAGNOSTIC_RECORDS_FILENAME}")
        write_bytes_once(run_dir / CAPTURE_LEDGER_FILENAME, ledger_payload,
                         what=f"capture ledger {run_dir / CAPTURE_LEDGER_FILENAME}")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    manifest = {
        "manifest_contract": MANIFEST_CONTRACT,
        "run_kind": RUN_KIND,
        "diagnostic_only": True,
        "promotable": False,
        "output_contract": RECORD_CONTRACT,
        "run_id": run_id,
        "packet_manifest_path": str(packet_manifest_path),
        "packet_manifest_sha256": pre.inputs.manifest_sha256,
        "packet_run_id": pre.inputs.manifest["run_id"],
        "packets_jsonl_sha256": pre.inputs.packets_jsonl_sha256,
        "packet_failures_jsonl_sha256": pre.inputs.failures_jsonl_sha256,
        "prompt_template_path": pre.prompt_template_path,
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
            "selection_kind": pre.selection["selection_kind"],
            "sampling_algorithm": pre.selection["sampling"]["algorithm"],
            "seed": pre.selection["sampling"]["seed"],
            "rows_selected": len(pre.selected_packets),
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
            DIAGNOSTIC_RECORDS_FILENAME: _sha256(records_payload),
            RAW_RESPONSES_FILENAME: _sha256(archive_raw),
            CAPTURE_LEDGER_FILENAME: _sha256(ledger_payload),
        },
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "universe_screen_diagnostic_record": "0.1.0",
            "universe_screen_diagnostic_manifest": "0.1.0",
            "universe_screen_diagnostic_authorization": "0.1.0",
            "universe_screen_selection": "0.1.0",
            "universe_screen_adapter_enablement": "0.1.0",
            "baseline_packet_manifest_v5": "0.5.0",
            "universe_baseline_packet_v2": "0.2.0",
        },
        "limitations": [
            "Diagnostic measurement only. No row of this run is a screen "
            "result: it may not enter a SCREEN release, a classifier call "
            "list, or any later stage, and the authoritative and promotion "
            "loaders refuse this directory structurally.",
            "A rejected_output row carries no accepted screen status or "
            "output. Its full invalid payload is retained only in the "
            "hash-bound raw-response archive, bound by id and SHA-256.",
            "Rejections are recorded for model-output failures only "
            "(invalid JSON, adapter rejection, quote resolution, temporal "
            "violation). Governance, provider, envelope, capture, cap and "
            "budget failures hard-stop the run exactly as they do on the "
            "authoritative path.",
            "The row validator is the authoritative one, imported unchanged: "
            "this run is not more permissive per row, only more informative "
            "per cohort.",
            "Every binding is relational between the supplied inputs; no "
            "production hash is pinned in code or schema.",
        ],
    }
    _validate(manifest, manifest_schema, "Diagnostic run manifest")
    manifest_payload = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    try:
        write_bytes_once(run_dir / DIAGNOSTIC_MANIFEST_FILENAME, manifest_payload,
                         what=f"diagnostic manifest {run_dir / DIAGNOSTIC_MANIFEST_FILENAME}")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    result.status = "completed"
    result.counts = counts
    result.reconciliation = reconciliation
    result.request_accounting = request_accounting
    result.manifest_path = run_dir / DIAGNOSTIC_MANIFEST_FILENAME
    result.validated = len(validated_records)
    result.rejected = len(rejected_records)
    result.rejections_by_reason = dict(rejections)
    return result
