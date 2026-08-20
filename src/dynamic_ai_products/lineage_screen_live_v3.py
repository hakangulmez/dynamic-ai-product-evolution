"""Authoritative V5 screen successor with the long 429 backoff (ADR-117).

The ADR-116 route keeps its three-attempt transport and its bytes. This
successor changes exactly one dimension of it — how many times, and how far
apart, one logical packet's ``generateContent`` may be re-sent when the
provider declares a transient condition — and inherits every other rule by
import rather than by restatement:

* the row semantics are ADR-116's, unchanged: a model-content failure the
  strict validator can name becomes one ``model_evidence_unverified`` record
  under the same ``universe_screen_record@0.2.0`` contract, packet-build
  failures stay ``insufficient_evidence``, and the fail-safe firm roll-up is
  the same function object;
* the prompt is the same committed V5 template, the same renderer and the same
  resolver, and the strict validator is untouched;
* governance, envelope, capture, cap and budget faults remain run-fatal and
  receipt-bearing. Nothing about the longer wait chain makes any of them
  survivable.

**What the retry change buys.** A 429 is the provider declaring a quota or a
rate limit, and the committed 1s/2s chain re-sends inside the same window, so
a rate-limited cohort loses whole packets to three refusals that were never
going to succeed. Five attempts at 15s, 30s, 60s and 120s cross a per-minute
window before the last try. The cost is bounded and stated rather than
estimated: at most four waits totalling 225 seconds for one packet, and the
authorization must pay for five attempts per row up front.

**Why the arithmetic changes with it.** One logical packet may now spend five
generate attempts and one countTokens send, so a run of ``n`` selected packets
authorizes ``n × 5`` provider attempts and ``n × 6`` external requests. The
full cohort of 7,042 packets is therefore 7,042 logical requests, 35,210
generate attempts and 42,252 external requests. Nothing here pins that cohort
size: the ceilings are re-derived from the selection at preflight and checked
against the authorization, which must state the same numbers.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.extraction.count_reconciliation import (
    reserve_cost_microdollars,
)
from dynamic_ai_products.extraction.provider_adapter import (
    BudgetAdmission,
    client_contract_digest,
)
from dynamic_ai_products.providers.client_contract_v2 import (
    CLIENT_CONTRACT_V2_ID,
    MODEL_PARAMETERS_V2,
    build_client_contract_v2,
    build_operation_endpoints,
)
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.retry_policy import (
    RATE_LIMIT_POLICY_VERSION,
    RETRY_POLICY_VERSION,
)
from dynamic_ai_products.providers.screen_retry_policy import (
    SCREEN_COUNT_MAX_ATTEMPTS,
    SCREEN_EXTERNAL_REQUESTS_PER_ROW,
    SCREEN_GENERATE_MAX_ATTEMPTS,
    SCREEN_GENERATE_RETRY_DELAYS_SECONDS,
    SCREEN_GENERATE_RETRY_POLICY_VERSION,
    SCREEN_RETRY_JITTER,
    SCREEN_RETRY_OWNER,
    screen_external_request_cap,
    screen_generate_attempt_cap,
)
from dynamic_ai_products.providers.vertex_gemini_screen_v3 import (
    SCREEN_CONNECTOR_ID,
    VertexGeminiScreenV3,
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
    ScreenCohortBudget,
    VertexLineageScreenProvider,
    _hydrate_pinned,
    _parse_moment,
    load_screen_selection,
)
from .lineage_screen_live_v2 import (
    PROMPT_PATH,
    RECORD_CONTRACT,
    RECORD_ORDER,
    RECORD_SCHEMA,
    ROLLUP_RULE,
    _detail,
    firm_rollup_v2,
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

__all__ = ["ScreenCohortBudgetV3", "run_lineage_screen_live_v3"]

AUTHORIZATION_SCHEMA = "schemas/universe_screen_live_authorization.v3.schema.json"
MANIFEST_SCHEMA = "schemas/universe_screen_manifest.v7.schema.json"
AUTHORIZATION_CONTRACT = "universe_screen_live_authorization@0.3.0"
MANIFEST_CONTRACT = "universe_screen_manifest@0.7.0"


class ScreenCohortBudgetV3(ScreenCohortBudget):
    """The ADR-116 cohort budget, paying for five generate attempts per row.

    Only :meth:`admit` differs, and only in the attempt count it prices: the
    reserve must cover what the connector is actually permitted to spend, and
    the minted admission must carry the same ceiling the connector will check.
    Wall-clock, input-token, output-headroom and settlement rules are the
    predecessor's, inherited unchanged.
    """

    def admit(
        self, *, measured_input_tokens: int, request_digest: str
    ) -> BudgetAdmission:
        self._require_wall_clock()
        if self.tokens_in_measured + measured_input_tokens > self._max_input_tokens:
            raise ScreenProviderTerminalError(
                "The cohort input-token budget is exhausted; the run stops "
                "before the send it cannot pay for."
            )
        reserve = reserve_cost_microdollars(
            measured_input_tokens=measured_input_tokens,
            max_output_tokens=MODEL_PARAMETERS_V2["max_output_tokens"],
            generate_attempt_cap=SCREEN_GENERATE_MAX_ATTEMPTS,
        )
        if self.cost_micros_settled + reserve > self._max_cost_micros:
            raise ScreenProviderTerminalError(
                "The cohort cost budget cannot cover this row's five-attempt "
                "reserve; the run stops before the send it cannot pay for."
            )
        return BudgetAdmission(
            measured_input_tokens=measured_input_tokens,
            reserved_cost_microdollars=reserve,
            generate_attempt_cap=SCREEN_GENERATE_MAX_ATTEMPTS,
            provider_request_digest=request_digest,
            session_nonce=self._session_nonce,
        )


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
    """The ADR-109 validation order, all of it before any output or SDK.

    Ordering is the whole guarantee: a wrong cap, a wrong policy or a wrong
    binding is refused here, so no run directory, no SDK import, no credential
    resolution and no send ever exists for a run that was not authorized in
    exactly this shape.
    """
    authorization, _ = _hydrate_pinned(
        governance_root,
        authorization_reference,
        authorization_sha256,
        "screen live v3 authorization",
    )
    _validate(
        authorization,
        _load_schema(root, AUTHORIZATION_SCHEMA),
        "Screen live v3 authorization",
    )
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
    expected_route = {
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
        authorization["model_route"] != expected_route
        or authorization["retry_policy_version"] != RETRY_POLICY_VERSION
        or authorization["rate_limit_policy_version"] != RATE_LIMIT_POLICY_VERSION
    ):
        raise ScreenInputError(
            "Authorization route or policy binding differs from committed provider policy."
        )
    # The screen's own generate policy, bound rather than assumed. Belt and
    # braces beyond the schema consts: a grant minted for the committed
    # three-attempt chain names a different policy version and runs nothing.
    if (
        authorization["screen_generate_retry_policy_version"]
        != SCREEN_GENERATE_RETRY_POLICY_VERSION
        or authorization["generate_attempt_cap_per_row"] != SCREEN_GENERATE_MAX_ATTEMPTS
        or authorization["external_requests_per_row"] != SCREEN_EXTERNAL_REQUESTS_PER_ROW
    ):
        raise ScreenInputError(
            "The authorization does not name this route's screen generate "
            f"policy ({SCREEN_GENERATE_RETRY_POLICY_VERSION}: "
            f"{SCREEN_GENERATE_MAX_ATTEMPTS} attempts per row, "
            f"{SCREEN_EXTERNAL_REQUESTS_PER_ROW} external sends per row); it "
            "was minted for a different retry policy."
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
        packets = [p for p in inputs.packets if (p["cik"], p["accession"]) in set(keys)]
        include_failures = False
    else:
        packets, include_failures = list(inputs.packets), True
    if (
        logical_request_cap != len(packets)
        or authorization["logical_request_cap"] != logical_request_cap
    ):
        raise ScreenInputError(
            "logical_request_cap must equal selected valid packet rows."
        )
    expected_attempts = screen_generate_attempt_cap(logical_request_cap)
    if (
        provider_attempt_cap != expected_attempts
        or authorization["provider_attempt_cap"] != expected_attempts
    ):
        raise ScreenInputError(
            f"provider_attempt_cap must be exactly {expected_attempts} "
            f"(logical x {SCREEN_GENERATE_MAX_ATTEMPTS} generate attempts)."
        )
    expected_external = screen_external_request_cap(logical_request_cap)
    if authorization["budget_max_external_requests"] != expected_external:
        raise ScreenInputError(
            f"budget_max_external_requests must be exactly {expected_external} "
            f"(logical x {SCREEN_EXTERNAL_REQUESTS_PER_ROW}: one countTokens "
            "send plus the five-attempt generate ceiling per row)."
        )
    if authorization["max_model_evidence_unverified"] > logical_request_cap:
        raise ScreenInputError(
            "model-evidence circuit breaker cannot exceed selected packet rows."
        )
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


def run_lineage_screen_live_v3(
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
    sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    """Screen the selected rows under the long-backoff grant. Fail closed.

    ``client_factory`` and ``sleep`` exist so the authorized path is testable
    offline: every caller in this repository injects a fake transport and a
    wait recorder, so no test builds an SDK client, resolves ADC, opens a
    socket, or waits a real 225 seconds. Both default to ``None``, which is
    what a separately authorized live run uses.
    """
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
    planned_insufficient = len(pre.inputs.failures) if pre.include_failures else 0
    if dry_run:
        for packet in pre.packets:
            render_diagnostic_prompt_with_citation_refs(pre.prompt_text, packet)
        return ScreenRunResult(
            run_id,
            None,
            True,
            "dry_run",
            len(pre.packets),
            planned_insufficient,
            request_accounting={
                "logical_request_cap": logical_request_cap,
                "provider_attempt_cap": provider_attempt_cap,
                "external_request_cap": pre.authorization[
                    "budget_max_external_requests"
                ],
                "generate_attempt_cap_per_row": SCREEN_GENERATE_MAX_ATTEMPTS,
                "external_requests_per_row": SCREEN_EXTERNAL_REQUESTS_PER_ROW,
            },
        )
    # Connector construction is pure; the handshake smoke proves the three-list
    # equality once, before any output exists, and is revoked immediately.
    connector = VertexGeminiScreenV3(
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
    # Only now may an output directory exist.
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
        packet_sha_by_key={
            (p["cik"], p["accession"]): p["packet_sha256"] for p in pre.packets
        },
        prompt_template_sha256=pre.prompt_sha256,
        ledger=ledger,
    )
    archive_path = run_dir / RAW_RESPONSES_FILENAME
    archive = os.fdopen(
        os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), "wb"
    )
    records: list[dict] = []
    raw_count = 0
    logical_made = 0
    attempts_made = 0
    rows_retried = 0
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
        generate_captures = sum(
            entry["operation_label"] == "generate_content" for entry in ledger
        )
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
            # Ledger-derived, so the stopping row's real send attempts are
            # counted even though no row report exists for it.
            "provider_attempts_made": generate_captures,
            "logical_request_cap": logical_request_cap,
            "provider_attempt_cap": provider_attempt_cap,
            "generate_attempt_cap_per_row": SCREEN_GENERATE_MAX_ATTEMPTS,
            "authorization_sha256": authorization_sha256,
            "run_timestamp": clock().isoformat(),
            "retention_note": (
                "Non-authoritative failed V3 live run: no records JSONL, no "
                "capture ledger and no manifest exist here. This directory is "
                "immutable and may not be consumed by a SCREEN release or a "
                "classifier loader; a retry requires a new run id and a new "
                "authorization."
            ),
        }
        try:
            write_bytes_once(
                run_dir / FAILURE_RECEIPT_FILENAME,
                (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                what="V3 live failure receipt",
            )
        except WriteOnceError as exc:
            raise ScreenInputError(str(exc)) from exc
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        result.receipt = receipt
        return result

    for packet in pre.packets:
        rendered, refs = render_diagnostic_prompt_with_citation_refs(
            pre.prompt_text, packet
        )
        logical_made += 1
        try:
            raw = adapter.screen(
                rendered, cik=packet["cik"], accession=packet["accession"]
            )
        except ScreenProviderTerminalError as exc:
            return fail("provider_error", str(exc), packet)
        report = adapter.row_reports[-1]
        attempts_made += report["attempts"]
        if report["attempts"] > 1:
            rows_retried += 1
        if attempts_made > provider_attempt_cap:
            return fail(
                "provider_error",
                f"Provider attempt cap {provider_attempt_cap} exceeded; the run "
                "stops rather than exceeding its authorized scale.",
                packet,
            )
        raw_sha = _sha256(raw.encode("utf-8"))
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
            ).encode("utf-8")
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
            "prompt_sha256": _sha256(rendered.encode("utf-8")),
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
            if sum(rejected.values()) > pre.authorization[
                "max_model_evidence_unverified"
            ]:
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
            raise ScreenInputError(
                f"Built V3 screen record violates schema: {errors[0].message}"
            )
    archive_raw = archive_path.read_bytes()
    archive_entries = [
        json.loads(line)
        for line in _decode_utf8(archive_raw, RAW_RESPONSES_FILENAME).splitlines()
        if line.strip()
    ]
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
    }
    count_captures = sum(
        entry["operation_label"] == "count_tokens" for entry in ledger
    )
    generate_captures = len(ledger) - count_captures
    model_rows = [r for r in records if r["record_kind"] == "model_evidence_unverified"]
    screened = [r for r in records if r["record_kind"] == "screened_packet"]
    insufficient = [r for r in records if r["record_kind"] == "insufficient_evidence"]
    rollup = firm_rollup_v2(records)
    rollup_counts = {
        s: sum(v == s for v in rollup.values())
        for s in (*SCREEN_STATUSES, "MODEL_EVIDENCE_UNVERIFIED", "INSUFFICIENT_EVIDENCE")
    }
    counts = {
        "planned_rows": len(pre.packets) + planned_insufficient,
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
        "selected packets partition accepted and model-evidence-unverified": (
            len(screened) + len(model_rows) == len(pre.packets)
        ),
        "packet failures remain insufficient evidence": (
            len(insufficient) == planned_insufficient
        ),
        "every model result binds archived raw response": (
            len(archive_entries) == logical_made == len(pre.packets)
        ),
        "model evidence failures carry no status and no output": all(
            r["screen_status"] is None and r["screen_output"] is None
            for r in model_rows
        ),
        "breaker was not exceeded": (
            len(model_rows) <= pre.authorization["max_model_evidence_unverified"]
        ),
        "capture files rehash to their ledger lines": capture_ok,
        "no orphan capture file exists": (
            disk_refs == {e["raw_reference"] for e in persisted}
        ),
        "model unverified blocks firm-negative": all(
            rollup[r["cik"]] != "LIKELY_INELIGIBLE" for r in model_rows
        ),
        "every row made exactly one count send": (
            count_captures == logical_made == len(pre.packets) * SCREEN_COUNT_MAX_ATTEMPTS
        ),
        "count and generate captures partition external requests": (
            count_captures + generate_captures == len(ledger)
            == budget.external_requests_made
        ),
        "generate captures equal provider attempts": (
            generate_captures == attempts_made
            == sum(report["attempts"] for report in adapter.row_reports)
        ),
        "no row exceeded the five-attempt generate ceiling": all(
            report["attempts"] <= SCREEN_GENERATE_MAX_ATTEMPTS
            for report in adapter.row_reports
        ),
        "provider attempts never exceeded the declared cap": (
            attempts_made <= provider_attempt_cap
        ),
        "external requests stay within the authorized cap": (
            len(ledger) <= pre.authorization["budget_max_external_requests"]
        ),
        "the prompt template hash equals the authorization's": (
            pre.prompt_sha256 == pre.authorization["prompt_template_sha256"]
        ),
    }
    if not all(reconciliation.values()):
        raise ScreenInputError(
            "V3 live reconciliation failed; no records JSONL, no capture ledger "
            "and no manifest are written. Failed identities: "
            f"{sorted(k for k, v in reconciliation.items() if not v)}."
        )
    records_bytes = ("\n".join(_canonical_line(r) for r in records) + "\n").encode(
        "utf-8"
    )
    ledger_bytes = ("\n".join(_canonical_line(r) for r in ledger) + "\n").encode(
        "utf-8"
    )
    try:
        write_bytes_once(
            run_dir / RECORDS_FILENAME, records_bytes, what="V3 screen records"
        )
        write_bytes_once(
            run_dir / CAPTURE_LEDGER_FILENAME, ledger_bytes, what="V3 capture ledger"
        )
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    request_accounting = {
        "logical_request_cap": logical_request_cap,
        "provider_attempt_cap": provider_attempt_cap,
        "external_request_cap": pre.authorization["budget_max_external_requests"],
        "generate_attempt_cap_per_row": SCREEN_GENERATE_MAX_ATTEMPTS,
        "external_requests_per_row": SCREEN_EXTERNAL_REQUESTS_PER_ROW,
        "logical_requests_made": logical_made,
        "provider_attempts_made": attempts_made,
        "external_requests_made": len(ledger),
        "count_captures": count_captures,
        "generate_captures": generate_captures,
        "rows_retried": rows_retried,
        "tokens_in_measured": budget.tokens_in_measured,
        "tokens_out_reported": budget.tokens_out_reported,
        "rows_usage_verified": budget.rows_usage_verified,
        "cost_micros_settled": budget.cost_micros_settled,
        "budget_max_input_tokens": pre.authorization["budget_max_input_tokens"],
        "budget_max_output_tokens": pre.authorization["budget_max_output_tokens"],
        "budget_max_estimated_cost_micros": pre.authorization[
            "budget_max_estimated_cost_micros"
        ],
        "budget_max_wall_clock_seconds": pre.authorization[
            "budget_max_wall_clock_seconds"
        ],
    }
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
        "screen_adapter_enablement_sha256": pre.authorization[
            "screen_adapter_enablement_sha256"
        ],
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
        "provider": {
            "name": adapter.name,
            "connector": SCREEN_CONNECTOR_ID,
            "model_route": dict(adapter.model_route),
        },
        "generate_retry_policy": {
            "policy_version": SCREEN_GENERATE_RETRY_POLICY_VERSION,
            "retry_owner": SCREEN_RETRY_OWNER,
            "generate_max_attempts": SCREEN_GENERATE_MAX_ATTEMPTS,
            "generate_retry_delays_seconds": list(SCREEN_GENERATE_RETRY_DELAYS_SECONDS),
            "jitter": SCREEN_RETRY_JITTER,
            "count_max_attempts": SCREEN_COUNT_MAX_ATTEMPTS,
            "external_requests_per_row": SCREEN_EXTERNAL_REQUESTS_PER_ROW,
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
            "universe_screen_record_v2": "0.2.0",
            "universe_screen_manifest_v7": "0.7.0",
            "universe_screen_live_authorization_v3": "0.3.0",
            "universe_screen_selection": "0.1.0",
            "universe_screen_adapter_enablement": "0.1.0",
            "baseline_packet_manifest_v5": "0.5.0",
            "universe_baseline_packet_v2": "0.2.0",
        },
        "limitations": [
            "MODEL_EVIDENCE_UNVERIFIED is a visible review state, not a screen "
            "result or exclusion.",
            "INSUFFICIENT_EVIDENCE means no valid packet existed and no model "
            "call was made.",
            "The long backoff changes transport only: five generate attempts at "
            "15s/30s/60s/120s, one countTokens send, and the same declared "
            "transient conditions. No validation, capture, governance, budget or "
            "evidence failure is retried.",
            "Every binding is relational between the supplied inputs; no "
            "production cohort size is pinned in code or schema.",
        ],
    }
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA), "V3 live screen manifest")
    try:
        write_bytes_once(
            run_dir / SCREEN_MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="V3 live screen manifest",
        )
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    result.status = "completed"
    result.counts = counts
    result.reconciliation = reconciliation
    result.request_accounting = request_accounting
    result.manifest_path = run_dir / SCREEN_MANIFEST_FILENAME
    return result
