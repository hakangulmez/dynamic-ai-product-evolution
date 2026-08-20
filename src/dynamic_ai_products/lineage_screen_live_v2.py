"""Authoritative V5 high-recall screen successor (ADR-116).

The original live route remains all-or-nothing.  This successor retains the
same provider, capture, hash and strict evidence validation rules, but makes
the already-measured model-content validation failures visible as
``model_evidence_unverified`` records.  They are never a negative screen
result.  Packet-build failures remain ``insufficient_evidence`` and are never
model-called.  Governance, provider, envelope, capture, cap and budget faults
remain fail-closed for the entire run.
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
from dynamic_ai_products.provenance import write_bytes_once

from .lineage_screen_diagnostic import (
    REJECTION_DETAIL_MAX,
    REJECTION_REASON_CODES,
    render_diagnostic_prompt_with_citation_refs,
    resolve_diagnostic_citation_refs,
)
from .lineage_screen_live import (
    CAPTURE_LEDGER_FILENAME,
    CAPTURES_DIRNAME,
    ENABLEMENT_SCHEMA_RELATIVE_PATH,
    ENVELOPE_TEXT_EXTRACTION_RULE,
    EXTERNAL_REQUESTS_PER_ROW,
    GENERATE_ATTEMPT_CAP_PER_ROW,
    ScreenCohortBudget,
    VertexLineageScreenProvider,
    _hydrate_pinned,
    _parse_moment,
    load_screen_selection,
)
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

__all__ = ["run_lineage_screen_live_v2", "firm_rollup_v2"]

AUTHORIZATION_SCHEMA = "schemas/universe_screen_live_authorization.v2.schema.json"
RECORD_SCHEMA = "schemas/universe_screen_record.v2.schema.json"
MANIFEST_SCHEMA = "schemas/universe_screen_manifest.v6.schema.json"
PROMPT_PATH = "prompts/discovery/universe_high_recall_screen.v5.md"
AUTHORIZATION_CONTRACT = "universe_screen_live_authorization@0.2.0"
RECORD_CONTRACT = "universe_screen_record@0.2.0"
MANIFEST_CONTRACT = "universe_screen_manifest@0.6.0"
RECORD_ORDER = "selected_packets_then_packet_failures@2"
ROLLUP_RULE = (
    "eligible_over_boundary_over_model_evidence_unverified_over_ineligible_over_insufficient@1"
)


def _detail(value: str) -> str:
    value = " ".join(str(value).split())
    return (
        value if len(value) <= REJECTION_DETAIL_MAX else value[: REJECTION_DETAIL_MAX - 3] + "..."
    )


def firm_rollup_v2(records: list[dict]) -> dict[str, str]:
    """Fail-safe raw-CIK roll-up; an unverified model row blocks negative use."""
    precedence = (
        "LIKELY_ELIGIBLE",
        "BOUNDARY_OR_UNCERTAIN",
        "MODEL_EVIDENCE_UNVERIFIED",
        "LIKELY_INELIGIBLE",
    )
    seen: dict[str, set[str]] = {}
    for row in records:
        states = seen.setdefault(row["cik"], set())
        if row["record_kind"] == "screened_packet":
            states.add(row["screen_status"])
        elif row["record_kind"] == "model_evidence_unverified":
            states.add("MODEL_EVIDENCE_UNVERIFIED")
    return {
        cik: next((s for s in precedence if s in states), "INSUFFICIENT_EVIDENCE")
        for cik, states in seen.items()
    }


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
    include_failures: bool


def _preflight(
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
) -> _Preflight:
    authorization, _ = _hydrate_pinned(
        governance_root,
        authorization_reference,
        authorization_sha256,
        "screen live v2 authorization",
    )
    _validate(
        authorization, _load_schema(root, AUTHORIZATION_SCHEMA), "Screen live v2 authorization"
    )
    enablement, _ = _hydrate_pinned(
        governance_root,
        authorization["screen_adapter_enablement_reference"],
        authorization["screen_adapter_enablement_sha256"],
        "screen adapter enablement",
    )
    _validate(
        enablement, _load_schema(root, ENABLEMENT_SCHEMA_RELATIVE_PATH), "Screen adapter enablement"
    )
    now = clock()
    for label, artifact in (("authorization", authorization), ("enablement", enablement)):
        if not (
            _parse_moment(artifact["effective_at"], f"{label} effective_at")
            <= now
            < _parse_moment(artifact["expires_at"], f"{label} expires_at")
        ):
            raise ScreenInputError(f"The {label} is outside its effective window; nothing runs.")
    contract = build_client_contract_v2(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"],
    )
    digest = client_contract_digest(contract)
    expected_route = {"provider": contract["model_provider"], "model_label": contract["model_name"]}
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
        authorization["model_route"] != expected_route
        or authorization["retry_policy_version"] != RETRY_POLICY_VERSION
        or authorization["rate_limit_policy_version"] != RATE_LIMIT_POLICY_VERSION
    ):
        raise ScreenInputError(
            "Authorization route or policy binding differs from committed provider policy."
        )
    endpoints = build_operation_endpoints(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"],
    )
    if set(authorization["endpoint_allowlist"]) != set(endpoints.values()) or set(
        enablement["endpoint_allowlist"]
    ) != set(endpoints.values()):
        raise ScreenInputError(
            "Authorization/enablement endpoint allowlists are not exactly the derived operation endpoints."
        )
    prompt_raw = (root / PROMPT_PATH).read_bytes()
    prompt_sha = _sha256(prompt_raw)
    if prompt_sha != authorization["prompt_template_sha256"]:
        raise ScreenInputError("Authorization does not bind the committed V5 screen prompt bytes.")
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
            "Selection and authorization do not bind the loaded packet cohort identically."
        )
    by_key = {(p["cik"], p["accession"]): p for p in inputs.packets}
    if selection["selection_kind"] == "canary_100":
        keys = [(r["cik"], r["accession"]) for r in selection["rows"]]
        if len(keys) != len(set(keys)):
            raise ScreenInputError("Selection contains duplicate rows.")
        for row, key in zip(selection["rows"], keys):
            if key not in by_key or by_key[key]["packet_sha256"] != row["packet_sha256"]:
                raise ScreenInputError("Selection row is absent or packet-hash drifted.")
        packets, include_failures = (
            [p for p in inputs.packets if (p["cik"], p["accession"]) in set(keys)],
            False,
        )
    else:
        packets, include_failures = list(inputs.packets), True
    if (
        logical_request_cap != len(packets)
        or authorization["logical_request_cap"] != logical_request_cap
    ):
        raise ScreenInputError("logical_request_cap must equal selected valid packet rows.")
    if (
        provider_attempt_cap != logical_request_cap * GENERATE_ATTEMPT_CAP_PER_ROW
        or authorization["provider_attempt_cap"] != provider_attempt_cap
    ):
        raise ScreenInputError("provider_attempt_cap must equal logical cap times three.")
    if (
        authorization["budget_max_external_requests"]
        != logical_request_cap * EXTERNAL_REQUESTS_PER_ROW
    ):
        raise ScreenInputError("external request cap does not match selected-row arithmetic.")
    if authorization["max_model_evidence_unverified"] > logical_request_cap:
        raise ScreenInputError("model-evidence circuit breaker cannot exceed selected packet rows.")
    return _Preflight(
        authorization,
        enablement,
        digest,
        endpoints,
        _decode_utf8(prompt_raw, "V5 screen prompt"),
        prompt_sha,
        inputs,
        selection,
        selection_sha,
        packets,
        include_failures,
    )


def run_lineage_screen_live_v2(
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
) -> ScreenRunResult:
    """Run the V5 evidence-safe authoritative screen under a V2 grant."""
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
        logical_request_cap=logical_request_cap,
        provider_attempt_cap=provider_attempt_cap,
        clock=clock,
    )
    if dry_run:
        for packet in pre.packets:
            render_diagnostic_prompt_with_citation_refs(pre.prompt_text, packet)
        return ScreenRunResult(
            run_id,
            None,
            True,
            "dry_run",
            len(pre.packets),
            len(pre.inputs.failures) if pre.include_failures else 0,
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
            enablement_endpoint_allowlist=tuple(pre.enablement["endpoint_allowlist"]),
        )
    except ProviderError as exc:
        raise ScreenInputError(f"Connector handshake refused: {exc.reason_code}.") from exc
    finally:
        connector.revoke_run_permission()
    run_dir = create_run_directory(output_dir, run_id)
    result = ScreenRunResult(
        run_id,
        run_dir,
        False,
        "failed",
        len(pre.packets),
        len(pre.inputs.failures) if pre.include_failures else 0,
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
        packet_sha_by_key={(p["cik"], p["accession"]): p["packet_sha256"] for p in pre.packets},
        prompt_template_sha256=pre.prompt_sha256,
        ledger=ledger,
    )
    archive_path = run_dir / RAW_RESPONSES_FILENAME
    archive = os.fdopen(os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), "wb")
    records: list[dict] = []
    raw_count = 0
    logical_made = 0
    attempts_made = 0
    rejected: dict[str, int] = {code: 0 for code in REJECTION_REASON_CODES}

    def fail(
        reason: str,
        detail: str,
        packet: dict,
        *,
        stopping_row_index: int | None = None,
        records_completed_before_failure: int | None = None,
    ) -> ScreenRunResult:
        archive.flush()
        os.fsync(archive.fileno())
        archive.close()
        receipt = {
            "receipt_contract": "universe_screen_failure_receipt@0.1.0",
            "run_id": run_id,
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
            "raw_responses_captured": raw_count,
            "external_requests_made": len(ledger),
            "logical_requests_attempted": logical_made,
            "provider_attempts_made": sum(
                e["operation_label"] == "generate_content" for e in ledger
            ),
            "authorization_sha256": authorization_sha256,
            "run_timestamp": clock().isoformat(),
            "retention_note": "Non-authoritative failed V2 live run; no records JSONL, capture ledger or manifest exists.",
        }
        write_bytes_once(
            run_dir / FAILURE_RECEIPT_FILENAME,
            (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode(),
            what="V2 live failure receipt",
        )
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        result.receipt = receipt
        return result

    for packet in pre.packets:
        rendered, refs = render_diagnostic_prompt_with_citation_refs(pre.prompt_text, packet)
        logical_made += 1
        try:
            raw = adapter.screen(rendered, cik=packet["cik"], accession=packet["accession"])
        except ScreenProviderTerminalError as exc:
            return fail("provider_error", str(exc), packet)
        report = adapter.row_reports[-1]
        attempts_made += report["attempts"]
        if attempts_made > provider_attempt_cap:
            return fail("provider_error", "Provider attempt cap exceeded.", packet)
        raw_sha = _sha256(raw.encode())
        response_id = f"{run_id}-{packet['cik']}-{packet['accession']}"
        archive.write(
            (
                _canonical_line(
                    {
                        "raw_response_id": response_id,
                        "cik": packet["cik"],
                        "accession": packet["accession"],
                        "raw_response": raw,
                        "raw_response_sha256": raw_sha,
                    }
                )
                + "\n"
            ).encode()
        )
        archive.flush()
        os.fsync(archive.fileno())
        raw_count += 1
        base = {
            "record_contract": RECORD_CONTRACT,
            "cik": packet["cik"],
            "company_id": packet["company_id"],
            "accession": packet["accession"],
            "form": packet["form"],
            "baseline_filing_date": packet["baseline_filing_date"],
            "source_id": packet["source_id"],
            "packet_sha256": packet["packet_sha256"],
            "prompt_sha256": _sha256(rendered.encode()),
            "model_route": dict(adapter.model_route),
            "raw_response_id": response_id,
            "raw_response_sha256": raw_sha,
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
            if sum(rejected.values()) > pre.authorization["max_model_evidence_unverified"]:
                records.append(base)
                return fail(
                    "model_evidence_budget_exhausted",
                    "Declared model-evidence breaker exceeded.",
                    packet,
                    stopping_row_index=logical_made,
                    records_completed_before_failure=logical_made - 1,
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
    if pre.include_failures:
        for failure in pre.inputs.failures:
            records.append(
                {
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
                }
            )
    validator = Draft202012Validator(
        _load_schema(root, RECORD_SCHEMA), format_checker=FormatChecker()
    )
    for row in records:
        errors = sorted(validator.iter_errors(row), key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(f"Built V2 screen record violates schema: {errors[0].message}")
    archive_raw = archive_path.read_bytes()
    archive_entries = [
        json.loads(line)
        for line in _decode_utf8(archive_raw, RAW_RESPONSES_FILENAME).splitlines()
        if line
    ]
    persisted = [e for e in ledger if e["capture_disposition"] == "raw_persisted"]
    capture_ok = all(
        (run_dir / e["raw_reference"]).is_file()
        and _sha256((run_dir / e["raw_reference"]).read_bytes()) == e["raw_sha256"]
        for e in persisted
    )
    disk_refs = {
        str(p.relative_to(run_dir)) for p in (run_dir / CAPTURES_DIRNAME).rglob("*") if p.is_file()
    }
    model_rows = [r for r in records if r["record_kind"] == "model_evidence_unverified"]
    screened = [r for r in records if r["record_kind"] == "screened_packet"]
    insufficient = [r for r in records if r["record_kind"] == "insufficient_evidence"]
    rollup = firm_rollup_v2(records)
    rollup_counts = {
        s: sum(v == s for v in rollup.values())
        for s in (*SCREEN_STATUSES, "MODEL_EVIDENCE_UNVERIFIED", "INSUFFICIENT_EVIDENCE")
    }
    counts = {
        "planned_rows": len(pre.packets)
        + (len(pre.inputs.failures) if pre.include_failures else 0),
        "screened_packets": len(screened),
        "model_evidence_unverified": len(model_rows),
        "insufficient_evidence": len(insufficient),
        "rejections_by_reason": rejected,
        "by_screen_status": {
            s: sum(r["screen_status"] == s for r in screened) for s in SCREEN_STATUSES
        },
        "firm_rollup": rollup_counts,
    }
    reconciliation = {
        "records partition retained rows": len(records) == counts["planned_rows"],
        "selected packets partition accepted and model-evidence-unverified": len(screened)
        + len(model_rows)
        == len(pre.packets),
        "packet failures remain insufficient evidence": len(insufficient)
        == (len(pre.inputs.failures) if pre.include_failures else 0),
        "every model result binds archived raw response": len(archive_entries)
        == logical_made
        == len(pre.packets),
        "model evidence failures are nonnegative": all(
            r["screen_status"] is None and r["screen_output"] is None for r in model_rows
        ),
        "breaker was not exceeded": len(model_rows)
        <= pre.authorization["max_model_evidence_unverified"],
        "capture files rehash": capture_ok,
        "no orphan captures": disk_refs == {e["raw_reference"] for e in persisted},
        "model unverified blocks firm-negative": all(
            rollup[r["cik"]] != "LIKELY_INELIGIBLE" for r in model_rows
        ),
    }
    if not all(reconciliation.values()):
        raise ScreenInputError(
            f"V2 live reconciliation failed: {[k for k, v in reconciliation.items() if not v]}"
        )
    records_bytes = ("\n".join(_canonical_line(r) for r in records) + "\n").encode()
    ledger_bytes = ("\n".join(_canonical_line(r) for r in ledger) + "\n").encode()
    write_bytes_once(run_dir / RECORDS_FILENAME, records_bytes, what="V2 screen records")
    write_bytes_once(run_dir / CAPTURE_LEDGER_FILENAME, ledger_bytes, what="V2 capture ledger")
    manifest = {
        "manifest_contract": MANIFEST_CONTRACT,
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
        "screen_adapter_enablement_sha256": pre.authorization["screen_adapter_enablement_sha256"],
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
        "provider": {"name": adapter.name, "model_route": dict(adapter.model_route)},
        "screen_record_order": RECORD_ORDER,
        "firm_rollup_rule": ROLLUP_RULE,
        "baseline_cutoff": pre.inputs.baseline_cutoff,
        "counts": counts,
        "request_accounting": {
            "logical_request_cap": logical_request_cap,
            "provider_attempt_cap": provider_attempt_cap,
            "external_request_cap": pre.authorization["budget_max_external_requests"],
            "logical_requests_made": logical_made,
            "provider_attempts_made": attempts_made,
            "external_requests_made": len(ledger),
            "tokens_in_measured": budget.tokens_in_measured,
            "tokens_out_reported": budget.tokens_out_reported,
            "cost_micros_settled": budget.cost_micros_settled,
        },
        "reconciliation": reconciliation,
        "output_hashes": {
            RECORDS_FILENAME: _sha256(records_bytes),
            RAW_RESPONSES_FILENAME: _sha256(archive_raw),
            CAPTURE_LEDGER_FILENAME: _sha256(ledger_bytes),
        },
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "universe_screen_record_v2": "0.2.0",
            "universe_screen_manifest_v6": "0.6.0",
            "universe_screen_live_authorization_v2": "0.2.0",
            "universe_screen_selection": "0.1.0",
            "universe_screen_adapter_enablement": "0.1.0",
            "baseline_packet_manifest_v5": "0.5.0",
            "universe_baseline_packet_v2": "0.2.0",
        },
        "limitations": [
            "MODEL_EVIDENCE_UNVERIFIED is a visible review state, not a screen result or exclusion.",
            "INSUFFICIENT_EVIDENCE means no valid packet existed and no model call was made.",
        ],
    }
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA), "V2 live screen manifest")
    write_bytes_once(
        run_dir / SCREEN_MANIFEST_FILENAME,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
        what="V2 live screen manifest",
    )
    result.status = "completed"
    result.counts = counts
    result.reconciliation = reconciliation
    result.manifest_path = run_dir / SCREEN_MANIFEST_FILENAME
    return result
