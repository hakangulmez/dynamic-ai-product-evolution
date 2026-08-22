"""Continuation with a bounded, visible provider-unresolved outcome (ADR-121).

Four full-cohort attempts have now stopped four ways, and three of those
stops were a single row's provider transport failing after its authorized
retries were already spent. Each previous decision removed one such way of
losing finished work; none of them addressed the shape of the loss, which is
that one unresolvable row discards a whole cohort.

This successor changes that, narrowly. One change from ADR-120, and no others.

**A row whose provider path is exhausted becomes a visible outcome.** When a
provider or transport condition has already spent the retry budget this same
grant authorized, the row is recorded as ``PROVIDER_UNRESOLVED`` and the run
continues. It is not a skip and not a weaker evidence rule: the row keeps its
identity, its closed provider reason and its attempt telemetry, carries no
status, no evidence and no archived response — because none exists — and is
excluded from classifier call lists and from every valid-status count.

**The tolerance is bounded and authorized.** The grant must pin
``max_provider_unresolved`` at 25. The twenty-sixth such row stops the run
fail-closed with no manifest, so a systematically failing provider still ends
the run rather than quietly producing a cohort full of holes.

**Nothing else is tolerated.** Invalid JSON, adapter rejection, a quote or
evidence failure, a malformed or blocked response, a capture failure, a
governance or binding failure, a budget or cap breach: all remain run-fatal,
and none can become provider-unresolved. The classification is structural, not
textual — the adapter re-raises a ``ProviderError`` as the ``__cause__``, and
only a cause of that type, carrying a closed reason, with the failing
operation's attempts actually exhausted, qualifies.

**The source loader admits one more shape, narrowly.** A failed continuation
whose stop was an empty count body is reusable — but the admission is not "any
``provider_response_unusable``", and not "any missing capture directory". The
proofs are read from the source's own counters and captures: exactly one count
attempt for the stopping row, zero generate attempts for it, no stopping-row
capture of any kind, and zero empty generate bodies anywhere in the run. A
source that stopped for another reason, that persisted anything for its
stopping row, or whose counters do not close, is refused before a run
directory exists.

Everything else is inherited by import: the revalidation of every reused row
through the unchanged strict validator, the byte-identical archive
carry-forward, the honest separation of parent telemetry from this run's own,
and the rule that neither the source nor its own parent is ever authoritative.

**Structural isolation.** This manifest is written under its own filename, so
the v0.5-v0.8 loaders refuse the directory. Promoting an ADR-119 run to a
SCREEN release is a deliberate decision with its own loader and its own tests.
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
from dynamic_ai_products.providers.vertex_gemini_screen_v5 import EMPTY_GENERATE_BODY_REASON
from dynamic_ai_products.providers.vertex_gemini_screen_v6 import (
    EMPTY_COUNT_BODY_REASON,
    SCREEN_CONNECTOR_V6_ID,
    VertexGeminiScreenV6,
)
from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

from .lineage_screen_continuation import SourcePrefix, revalidate_source_prefix
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
    "CONTINUATION_V4_MANIFEST_FILENAME",
    "CONTINUATION_V4_RECORDS_FILENAME",
    "EMPTY_COUNT_TERMINAL_REASON",
    "load_continuation_source_v3",
    "require_continuation_v4_run",
    "run_lineage_screen_continuation_v4",
]

AUTHORIZATION_SCHEMA = "schemas/universe_screen_continuation_authorization.v4.schema.json"
MANIFEST_SCHEMA = "schemas/universe_screen_continuation_manifest.v4.schema.json"
RECORD_SCHEMA = "schemas/universe_screen_record.v4.schema.json"
AUTHORIZATION_CONTRACT = "universe_screen_continuation_authorization@0.4.0"
RECORD_CONTRACT = "universe_screen_record@0.4.0"
MANIFEST_CONTRACT = "universe_screen_continuation_manifest@0.11.0"
RUN_KIND = "full_cohort_continuation"
RECEIPT_CONTRACT = "universe_screen_failure_receipt@0.1.0"

#: The bounded tolerance, pinned by the authorization contract and restated
#: here so the runner refuses a grant that disagrees with it.
MAX_PROVIDER_UNRESOLVED = 25
SOURCE_KIND = "failed_continuation_empty_count_body"

#: Successor output names. The v0.5-v0.8 loaders look for
#: universe_screen_manifest.json and therefore refuse this directory outright.
CONTINUATION_V4_MANIFEST_FILENAME = "universe_screen_continuation_v4_manifest.json"
CONTINUATION_V4_RECORDS_FILENAME = "universe_screen_continuation_v4_records.jsonl"

#: The distinct terminal reason this route writes when every permitted attempt
#: for one row returned nothing. The closed ProviderError enum cannot carry it,
#: so it lives here, where this successor owns the contract.
EMPTY_COUNT_TERMINAL_REASON = "empty_count_body_exhausted"

#: The closed set of provider reasons that may become PROVIDER_UNRESOLVED.
#: Every one of them names a transport outcome, never a content judgement, and
#: each is reached only after the retry path this grant authorized is spent.
PROVIDER_UNRESOLVED_REASONS: tuple[str, ...] = (
    "vertex_quota_exhausted",
    "vertex_unavailable",
    "provider_timeout",
    "provider_response_unusable",
)

#: What the record and manifest report. The first four are the provider's own
#: reason codes; the last two are this lineage's empty-body exhaustions, which
#: the closed enum cannot name.
PROVIDER_UNRESOLVED_RECORD_REASONS: tuple[str, ...] = PROVIDER_UNRESOLVED_REASONS + (
    "empty_generate_body_exhausted",
    "empty_count_body_exhausted",
)

#: The ADR-119 terminal reason, carried forward: this route inherits that
#: behaviour and must be able to report it with the same words.
EMPTY_GENERATE_TERMINAL_REASON = "empty_generate_body_exhausted"

#: Receipt reason codes this route will continue from. The legacy value is what
#: the ADR-118 runner wrote before an empty body was survivable; the second is
#: what this route writes. Neither is sufficient on its own - the capture
#: evidence below must agree.
_ACCEPTED_SOURCE_REASONS = ("provider_error", EMPTY_COUNT_TERMINAL_REASON)
_LEGACY_EMPTY_BODY_SIGNATURE = "provider_response_unusable"

_REQUIRED_RECEIPT_FIELDS = (
    "receipt_contract", "run_id", "run_kind", "reason_code", "detail",
    "stopping_cik", "stopping_accession", "stopping_row_index",
    "records_completed_before_failure", "reused_prefix_rows",
    "model_called_rows_attempted", "external_requests_made",
    "count_attempts_made", "provider_attempts_made", "authorization_sha256",
    "source_run_id", "source_receipt_sha256",
)


def _capture_dir_for(run_dir: Path, receipt: dict) -> Path:
    """Where the stopping row's captures live, by the runner's own naming."""
    return (run_dir / CAPTURES_DIRNAME /
            f"{receipt['stopping_row_index']:05d}-{receipt['stopping_cik']}-"
            f"{receipt['stopping_accession']}")


def load_continuation_source_v3(
    source_run_dir: str | Path, *, source_receipt_sha256: str
) -> SourcePrefix:
    """Admit one failed continuation whose stop was an empty generate body.

    Seven proofs, each independent, and none of them a reason string on its
    own. The two that actually identify the shape are read from the source's
    captures: a real countTokens body for the stopping row, and no persisted
    generate body for it. That is what separates "the provider returned
    nothing" from every other way an outcome can be unusable.
    """
    directory = Path(source_run_dir)
    if not directory.is_dir():
        raise ScreenInputError(
            f"Continuation source {directory} is not a directory; a source run "
            "is named explicitly and must exist."
        )
    # (1) It must be a failed run, not a completed one.
    for filename, what in ((SCREEN_MANIFEST_FILENAME, "authoritative manifest"),
                           (CONTINUATION_V4_MANIFEST_FILENAME, "continuation manifest"),
                           (CONTINUATION_V4_RECORDS_FILENAME, "continuation records")):
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
            f"The source receipt hashes to {observed}, but "
            f"{source_receipt_sha256} was pinned; this is not the failed run "
            "that was authorized."
        )
    receipt = json.loads(receipt_bytes.decode("utf-8"))
    missing = [f for f in _REQUIRED_RECEIPT_FIELDS if f not in receipt]
    if missing:
        raise ScreenInputError(
            f"The source receipt is missing {missing}; it is not the "
            "continuation-route receipt shape this successor continues."
        )
    if receipt["receipt_contract"] != RECEIPT_CONTRACT:
        raise ScreenInputError(
            f"The source receipt declares {receipt['receipt_contract']!r}; this "
            f"route continues {RECEIPT_CONTRACT!r} runs only."
        )
    if receipt["run_kind"] != RUN_KIND:
        raise ScreenInputError(
            f"The source is a {receipt['run_kind']!r} run; this route continues "
            f"a {RUN_KIND!r} run whose prefix is already revalidated evidence."
        )
    # (2) The terminal reason must be one this route knows how to continue.
    reason = receipt["reason_code"]
    if reason not in _ACCEPTED_SOURCE_REASONS or (
        reason == "provider_error"
        and _LEGACY_EMPTY_BODY_SIGNATURE not in str(receipt["detail"])
    ):
        raise ScreenInputError(
            f"The source stopped with reason {reason!r} ({receipt['detail']!r}). "
            "This route continues an empty-generate-body stop only; any other "
            "failure needs its own design and its own tests."
        )
    archive_path = directory / RAW_RESPONSES_FILENAME
    if not archive_path.is_file():
        raise ScreenInputError(
            f"Continuation source {directory} holds no raw-response archive."
        )
    archive_bytes = archive_path.read_bytes()
    entries = [
        json.loads(line)
        for line in _decode_utf8(archive_bytes, RAW_RESPONSES_FILENAME).splitlines()
        if line.strip()
    ]
    completed = receipt["records_completed_before_failure"]
    # (3) Receipt row index equals archive line count plus one.
    if len(entries) != completed:
        raise ScreenInputError(
            f"The source archive holds {len(entries)} responses but the receipt "
            f"declares {completed} completed rows; a prefix that does not agree "
            "with its own receipt is not reusable."
        )
    if completed < 1:
        raise ScreenInputError("The source completed no rows; nothing to reuse.")
    if receipt["stopping_row_index"] != completed + 1:
        raise ScreenInputError(
            f"The source stopped at row {receipt['stopping_row_index']} with "
            f"{completed} completed; a continuation needs a contiguous prefix "
            "ending exactly where the run stopped."
        )
    stopping = (receipt["stopping_cik"], receipt["stopping_accession"])
    if any((e["cik"], e["accession"]) == stopping for e in entries):
        raise ScreenInputError(
            f"The source archive contains the stopping row {stopping}; the "
            "prefix must end before it so the row can be re-sent cleanly."
        )
    # (4) Unique ids, and every archived response re-hashes.
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
    # (5) No empty generate body anywhere: that is ADR-119's shape, not this
    # one, and a run that hit both is not the closed case tested here.
    if receipt.get("empty_generate_body_attempts", 0) != 0:
        raise ScreenInputError(
            f"The source recorded "
            f"{receipt.get('empty_generate_body_attempts')} empty generate "
            "bodies; this route continues an empty-count stop, and a run that "
            "met both anomalies is a different case needing its own tests."
        )
    # (6) The capture evidence that identifies an empty-count stop: the
    # stopping row persisted nothing at all, because its measurement returned
    # nothing and the generation was therefore never attempted.
    capture_dir = _capture_dir_for(directory, receipt)
    if capture_dir.exists():
        persisted = sorted(capture_dir.glob("*.bin"))
        raise ScreenInputError(
            f"The source's stopping row persisted {len(persisted)} capture "
            "file(s); an empty-count stop persists none, so this row failed "
            "for some other reason and is not continuable here."
        )
    # (7) Counter arithmetic closes exactly.
    suffix_done = completed - receipt["reused_prefix_rows"]
    if suffix_done < 0 or receipt["model_called_rows_attempted"] != suffix_done + 1:
        raise ScreenInputError(
            f"The source's own accounting does not close: "
            f"{receipt['reused_prefix_rows']} reused + {suffix_done} called "
            f"!= {receipt['model_called_rows_attempted']} attempted."
        )
    if receipt["external_requests_made"] != (
        receipt["count_attempts_made"] + receipt["provider_attempts_made"]
    ):
        raise ScreenInputError(
            "The source's external-request count is not its count plus "
            "generate attempts; its accounting is not trustworthy."
        )
    if receipt["count_attempts_made"] < receipt["model_called_rows_attempted"]:
        raise ScreenInputError(
            "The source made fewer countTokens sends than rows attempted; "
            "every attempted row measures its input at least once."
        )
    # (8) The arithmetic that names the failing operation. Every completed row
    # spent one generate; the stopping row spent none, and measured once.
    stopping_generates = receipt["provider_attempts_made"] - suffix_done
    stopping_counts = receipt["count_attempts_made"] - suffix_done
    if stopping_generates != 0:
        raise ScreenInputError(
            f"The source's stopping row spent {stopping_generates} generate "
            "attempt(s); an empty-count stop never reaches the generation, so "
            "this row failed elsewhere and is not continuable here."
        )
    expected_counts = (
        SCREEN_COUNT_MAX_ATTEMPTS_V2
        if reason == EMPTY_COUNT_TERMINAL_REASON else 1
    )
    if stopping_counts != expected_counts:
        raise ScreenInputError(
            f"The source's stopping row spent {stopping_counts} countTokens "
            f"attempt(s); this terminal shape spends exactly "
            f"{expected_counts}."
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


def require_continuation_v4_run(run_dir: str | Path) -> Path:
    """Refuse any ADR-119 run that is not a completed, self-consistent one."""
    directory = Path(run_dir)
    if (directory / FAILURE_RECEIPT_FILENAME).exists():
        raise ScreenInputError(
            f"Continuation run {directory} holds a failure receipt; it is "
            "non-authoritative and may not be consumed."
        )
    manifest_path = directory / CONTINUATION_V4_MANIFEST_FILENAME
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Continuation run {directory} has no {CONTINUATION_V4_MANIFEST_FILENAME}; "
            "only a manifest-bearing run is consumable."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("manifest_contract") != MANIFEST_CONTRACT:
        raise ScreenInputError(
            f"Continuation run {directory} declares "
            f"{manifest.get('manifest_contract')!r}; this loader reads "
            f"{MANIFEST_CONTRACT!r} only."
        )
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file():
            raise ScreenInputError(f"Continuation output {filename} is missing.")
        observed = _sha256(target.read_bytes())
        if observed != recorded:
            raise ScreenInputError(
                f"Continuation output {filename} hashes to {observed}, but the "
                f"manifest records {recorded}; the run is not consumable."
            )
    return manifest_path


def _classify_provider_unresolved(
    exc: ScreenProviderTerminalError, spent: list[dict]
) -> tuple[str, dict] | None:
    """Decide whether one failed row is provider-unresolved, structurally.

    Two independent things must hold, and neither is a message match.

    First, the cause must be a :class:`ProviderError`. The shared adapter
    re-raises a provider failure ``from`` the original, so a capture-sink
    failure, a count-reconciliation failure and an envelope failure each carry
    a different cause — or none — and are excluded by construction rather than
    by text.

    Second, the failing operation's attempts must actually be exhausted. A
    provider error that stopped on its first attempt was not retried and is
    not "unresolved after trying"; it is a hard stop. Returns the closed
    reason and the row's telemetry, or ``None`` when the row must stop the run.
    """
    cause = exc.__cause__
    if not isinstance(cause, ProviderError):
        return None
    if cause.reason_code not in PROVIDER_UNRESOLVED_REASONS:
        return None
    counts = [e for e in spent if e["operation_label"] == "count_tokens"]
    generates = [e for e in spent if e["operation_label"] == "generate_content"]
    empty_counts = sum(
        1 for e in counts
        if e.get("provider_reason_code") == EMPTY_COUNT_BODY_REASON)
    empty_generates = sum(
        1 for e in generates
        if e.get("provider_reason_code") == EMPTY_GENERATE_BODY_REASON)
    reason = cause.reason_code
    if generates:
        # The generation is where it failed: it must have spent its ceiling.
        if empty_generates and empty_generates == len(generates):
            reason = EMPTY_GENERATE_TERMINAL_REASON
        elif len(generates) < SCREEN_GENERATE_MAX_ATTEMPTS:
            return None
    else:
        # It never reached the generation, so the measurement must be spent.
        if empty_counts and empty_counts == len(counts):
            reason = EMPTY_COUNT_TERMINAL_REASON
        elif len(counts) < SCREEN_COUNT_MAX_ATTEMPTS_V2:
            return None
    telemetry = {
        "count_attempts": len(counts),
        "generate_attempts": len(generates),
        "capture_files_persisted": sum(
            1 for e in spent if e["capture_disposition"] == "raw_persisted"),
        "empty_count_bodies": empty_counts,
        "empty_generate_bodies": empty_generates,
        "provider_reason_code": reason,
    }
    return reason, telemetry


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
        "screen continuation v4 authorization",
    )
    _validate(authorization, _load_schema(root, AUTHORIZATION_SCHEMA),
              "Screen continuation v4 authorization")
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
    ):
        raise ScreenInputError(
            "Authorization route or policy binding differs from this route's "
            "committed provider and screen policies."
        )
    if (
        authorization["count_attempts_per_row"] != SCREEN_COUNT_MAX_ATTEMPTS_V2
        or authorization["generate_attempts_per_row"] != SCREEN_GENERATE_MAX_ATTEMPTS
        or authorization["external_requests_per_row"] != SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2
        or authorization["max_empty_generate_body_retries_per_row"]
        != SCREEN_GENERATE_MAX_ATTEMPTS
    ):
        raise ScreenInputError(
            "The authorization does not name this route's per-row send policy."
        )
    if authorization["source_kind"] != SOURCE_KIND:
        raise ScreenInputError(
            f"The authorization names source kind {authorization['source_kind']!r}; "
            f"this route continues {SOURCE_KIND!r} only."
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
        or selection["selection_kind"] != "full_cohort"
    ):
        raise ScreenInputError(
            "Selection and authorization do not bind the loaded packet cohort "
            "identically."
        )
    packets = list(inputs.packets)

    prefix = load_continuation_source_v3(
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
            "The source receipt names a different grant than this continuation "
            "binds."
        )
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
                f"The source grant and this continuation disagree about "
                f"{field_name}; the prefix was produced under different rules "
                "and may not be reused."
            )
    prefix_records, prefix_rejected = revalidate_source_prefix(
        prefix, packets=packets,
        prompt_text=_decode_utf8(prompt_raw, "V5 prompt"), model_route=model_route,
    )
    suffix = packets[len(prefix_records):]
    if not suffix:
        raise ScreenInputError(
            "The source prefix already covers the whole cohort; nothing to continue."
        )
    if (suffix[0]["cik"], suffix[0]["accession"]) != (
        prefix.receipt["stopping_cik"], prefix.receipt["stopping_accession"]
    ):
        raise ScreenInputError(
            "The first unreused row is not the source's stopping row; the "
            "continuation would skip or repeat work."
        )
    reused, called, cohort = len(prefix_records), len(suffix), len(packets)
    if (
        authorization["logical_row_cap"] != cohort
        or authorization["reused_prefix_row_cap"] != reused
        or authorization["model_called_row_cap"] != called
        or reused + called != cohort
    ):
        raise ScreenInputError(
            f"The authorization states {authorization['logical_row_cap']} cohort "
            f"/ {authorization['reused_prefix_row_cap']} reused / "
            f"{authorization['model_called_row_cap']} called, but the inputs "
            f"derive {cohort} / {reused} / {called}."
        )
    if authorization["count_attempt_cap"] != screen_count_attempt_cap(called):
        raise ScreenInputError(
            f"count_attempt_cap must be exactly {screen_count_attempt_cap(called)}."
        )
    if authorization["provider_attempt_cap"] != screen_generate_attempt_cap(called):
        raise ScreenInputError(
            f"provider_attempt_cap must be exactly "
            f"{screen_generate_attempt_cap(called)}."
        )
    if authorization["budget_max_external_requests"] != screen_external_request_cap_v2(called):
        raise ScreenInputError(
            f"budget_max_external_requests must be exactly "
            f"{screen_external_request_cap_v2(called)}."
        )
    if authorization["max_provider_unresolved"] != MAX_PROVIDER_UNRESOLVED:
        raise ScreenInputError(
            "The authorization does not pin this route's provider-unresolved "
            f"threshold of {MAX_PROVIDER_UNRESOLVED}."
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
            f"against a breaker of {breaker}; this continuation cannot complete "
            "and does not start."
        )
    return _Preflight(
        authorization, enablement, digest, endpoints,
        _decode_utf8(prompt_raw, "V5 prompt"), prompt_sha, inputs, selection,
        selection_sha, packets, prefix, prefix_records, prefix_rejected, suffix,
        model_route,
    )


def run_lineage_screen_continuation_v4(
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
    """Continue one empty-body-stopped run into a fresh complete cohort."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError("Invalid run id.")
    pre = _preflight(
        root=root, packet_manifest_path=packet_manifest_path,
        selection_artifact_path=selection_artifact_path,
        governance_root=Path(governance_root),
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256,
        source_run_dir=source_run_dir,
        source_receipt_sha256=source_receipt_sha256, clock=clock,
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
    result = ScreenRunResult(run_id, run_dir, False, "failed", len(pre.packets),
                             planned_insufficient)
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
                           for p in pre.suffix},
        prompt_template_sha256=pre.prompt_sha256, ledger=ledger,
    )
    adapter._row_ordinal = len(pre.prefix_records)

    archive_path = run_dir / RAW_RESPONSES_FILENAME
    archive = os.fdopen(
        os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), "wb")
    archive.write(pre.prefix.archive_bytes)
    archive.flush()
    os.fsync(archive.fileno())

    def base_identity(packet: dict, rendered: str) -> dict:
        """The fields every model-called row carries, whatever its outcome."""
        return {
            "record_contract": RECORD_CONTRACT, "cik": packet["cik"],
            "company_id": packet["company_id"], "accession": packet["accession"],
            "form": packet["form"],
            "baseline_filing_date": packet["baseline_filing_date"],
            "source_id": packet["source_id"],
            "packet_sha256": packet["packet_sha256"],
            "prompt_sha256": _sha256(rendered.encode("utf-8")),
            "model_route": dict(adapter.model_route),
            "raw_response_id": None, "raw_response_sha256": None,
            "provider_attempt_telemetry": None,
            "row_provenance": {
                "origin": "model_called", "source_run_id": None,
                "source_raw_response_id": None,
                "source_raw_responses_sha256": None, "source_receipt_sha256": None,
            },
        }

    # The v0.3 prefix records predate this contract's telemetry field.
    records: list[dict] = [
        {**row, "record_contract": RECORD_CONTRACT,
         "provider_attempt_telemetry": None}
        for row in pre.prefix_records
    ]
    provider_unresolved: list[dict] = []
    unresolved_by_reason: dict[str, int] = {}
    rejected = dict(pre.prefix_rejected)
    called_rows = count_attempts_made = generate_attempts_made = 0
    rows_count_retried = rows_generate_retried = 0
    empty_body_attempts = rows_with_empty_body = rows_recovered_after_empty = 0
    empty_count_attempts = rows_with_empty_count = rows_recovered_after_empty_count = 0

    def _empty_events(entries: list[dict]) -> int:
        return sum(1 for e in entries
                   if e.get("provider_reason_code") == EMPTY_GENERATE_BODY_REASON)

    def _empty_count_events(entries: list[dict]) -> int:
        return sum(1 for e in entries
                   if e.get("provider_reason_code") == EMPTY_COUNT_BODY_REASON)

    def fail(reason: str, detail: str, packet: dict, *,
             stopping_row_index: int | None = None,
             records_completed_before_failure: int | None = None) -> ScreenRunResult:
        archive.flush()
        os.fsync(archive.fileno())
        archive.close()
        generate_entries = sum(e["operation_label"] == "generate_content" for e in ledger)
        receipt = {
            "receipt_contract": RECEIPT_CONTRACT,
            "run_id": run_id,
            "run_kind": RUN_KIND,
            "reason_code": reason,
            "detail": _detail(detail),
            "stopping_cik": packet["cik"],
            "stopping_accession": packet["accession"],
            "stopping_row_index": (len(records) + 1 if stopping_row_index is None
                                   else stopping_row_index),
            "records_completed_before_failure": (
                len(records) if records_completed_before_failure is None
                else records_completed_before_failure),
            "reused_prefix_rows": len(pre.prefix_records),
            "model_called_rows_attempted": called_rows,
            "external_requests_made": len(ledger),
            "count_attempts_made": len(ledger) - generate_entries,
            "provider_attempts_made": generate_entries,
            "empty_generate_body_attempts": _empty_events(ledger),
            "empty_count_body_attempts": _empty_count_events(ledger),
            "provider_unresolved_rows": len(provider_unresolved),
            "max_provider_unresolved": MAX_PROVIDER_UNRESOLVED,
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
                "prefix bytes present in this directory's archive remain their "
                "source run's evidence and confer no authority. This directory "
                "is immutable; a further attempt requires a new run id and a "
                "new authorization."
            ),
        }
        try:
            write_bytes_once(
                run_dir / FAILURE_RECEIPT_FILENAME,
                (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                what="continuation v4 failure receipt")
        except WriteOnceError as exc:
            raise ScreenInputError(str(exc)) from exc
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        result.receipt = receipt
        return result

    for packet in pre.suffix:
        rendered, refs = render_diagnostic_prompt_with_citation_refs(
            pre.prompt_text, packet)
        called_rows += 1
        before = len(ledger)
        try:
            raw = adapter.screen(rendered, cik=packet["cik"],
                                 accession=packet["accession"])
        except ScreenProviderTerminalError as exc:
            spent = ledger[before:]
            count_attempts_made += sum(e["operation_label"] == "count_tokens" for e in spent)
            generate_attempts_made += sum(e["operation_label"] == "generate_content" for e in spent)
            empties = _empty_events(spent)
            empty_counts = _empty_count_events(spent)
            empty_body_attempts += empties
            empty_count_attempts += empty_counts
            if empty_counts:
                rows_with_empty_count += 1
            if empties:
                rows_with_empty_body += 1
            # An exhausted provider path is a recorded row; anything else is
            # still a stop. The classifier decides structurally.
            classified = _classify_provider_unresolved(exc, spent)
            if classified is not None:
                reason, telemetry = classified
                if len(provider_unresolved) + 1 > MAX_PROVIDER_UNRESOLVED:
                    # The 26th is a stop, not a tolerance: a provider failing
                    # this often is a systematic condition, not a stray row.
                    return fail(
                        "provider_unresolved_budget_exhausted",
                        f"A twenty-sixth row exhausted its provider retry path "
                        f"({reason}); the authorized tolerance is "
                        f"{MAX_PROVIDER_UNRESOLVED}.",
                        packet)
                unresolved_row = {
                    **base_identity(packet, rendered),
                    "record_kind": "provider_unresolved",
                    "screen_status": None,
                    "screen_output": None,
                    "raw_response_id": None,
                    "raw_response_sha256": None,
                    "failure_reason_code": reason,
                    "failure_detail": _detail(str(exc)),
                    "provider_attempt_telemetry": telemetry,
                }
                provider_unresolved.append(unresolved_row)
                records.append(unresolved_row)
                unresolved_by_reason[reason] = unresolved_by_reason.get(reason, 0) + 1
                continue
            return fail("provider_error", str(exc), packet)
        spent = ledger[before:]
        row_counts = sum(e["operation_label"] == "count_tokens" for e in spent)
        row_generates = sum(e["operation_label"] == "generate_content" for e in spent)
        row_empties = _empty_events(spent)
        row_empty_counts = _empty_count_events(spent)
        count_attempts_made += row_counts
        generate_attempts_made += row_generates
        empty_body_attempts += row_empties
        empty_count_attempts += row_empty_counts
        if row_counts > 1:
            rows_count_retried += 1
        if row_generates > 1:
            rows_generate_retried += 1
        if row_empties:
            rows_with_empty_body += 1
            rows_recovered_after_empty += 1
        if row_empty_counts:
            rows_with_empty_count += 1
            rows_recovered_after_empty_count += 1
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
            **base_identity(packet, rendered),
            "raw_response_id": response_id, "raw_response_sha256": raw_sha,
        }
        try:
            output = _validate_row_output(
                resolve_diagnostic_citation_refs(raw, refs, packet), packet)
        except _RowValidationFailure as exc:
            rejected[exc.reason_code] += 1
            base.update(record_kind="model_evidence_unverified", screen_status=None,
                        screen_output=None, failure_reason_code=exc.reason_code,
                        failure_detail=_detail(exc.detail))
            if sum(rejected.values()) > pre.authorization["max_model_evidence_unverified"]:
                records.append(base)
                return fail("model_evidence_budget_exhausted",
                            "Declared model-evidence breaker exceeded across the cohort.",
                            packet, stopping_row_index=len(records),
                            records_completed_before_failure=len(records) - 1)
        else:
            base.update(record_kind="screened_packet",
                        screen_status=output.screen_status,
                        screen_output=output.model_dump(mode="json"),
                        failure_reason_code=None, failure_detail=None)
        records.append(base)
    archive.flush()
    os.fsync(archive.fileno())
    archive.close()

    for failure in pre.inputs.failures:
        records.append({
            "record_contract": RECORD_CONTRACT, "record_kind": "insufficient_evidence",
            "cik": failure["cik"], "company_id": failure["company_id"],
            "accession": failure["accession"], "form": failure["form"],
            "baseline_filing_date": None, "source_id": failure["source_id"],
            "packet_sha256": None, "screen_status": None, "prompt_sha256": None,
            "model_route": None, "raw_response_id": None,
            "raw_response_sha256": None, "screen_output": None,
            "failure_reason_code": failure["reason_code"],
            "failure_detail": failure["detail"],
            "provider_attempt_telemetry": None,
            "row_provenance": {
                "origin": "packet_build_failure", "source_run_id": None,
                "source_raw_response_id": None,
                "source_raw_responses_sha256": None, "source_receipt_sha256": None,
            },
        })

    validator = Draft202012Validator(_load_schema(root, RECORD_SCHEMA),
                                     format_checker=FormatChecker())
    for row in records:
        errors = sorted(validator.iter_errors(row), key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Built continuation record violates {RECORD_CONTRACT} at "
                f"{errors[0].json_path}: {errors[0].message}")

    archive_raw = archive_path.read_bytes()
    archive_entries = [json.loads(line) for line in
                       _decode_utf8(archive_raw, RAW_RESPONSES_FILENAME).splitlines()
                       if line.strip()]
    entries_by_id = {e["raw_response_id"]: e for e in archive_entries}
    persisted = [e for e in ledger if e["capture_disposition"] == "raw_persisted"]
    capture_ok = all(
        (run_dir / e["raw_reference"]).is_file()
        and _sha256((run_dir / e["raw_reference"]).read_bytes()) == e["raw_sha256"]
        for e in persisted)
    disk_refs = ({str(p.relative_to(run_dir))
                  for p in (run_dir / CAPTURES_DIRNAME).rglob("*") if p.is_file()}
                 if (run_dir / CAPTURES_DIRNAME).exists() else set())
    reused = [r for r in records if r["row_provenance"]["origin"] == "reused_source_prefix"]
    called = [r for r in records if r["row_provenance"]["origin"] == "model_called"]
    screened = [r for r in records if r["record_kind"] == "screened_packet"]
    unverified = [r for r in records if r["record_kind"] == "model_evidence_unverified"]
    insufficient = [r for r in records if r["record_kind"] == "insufficient_evidence"]
    unresolved = [r for r in records if r["record_kind"] == "provider_unresolved"]
    rollup = firm_rollup_v2(records)
    rollup_counts = {s: sum(v == s for v in rollup.values())
                     for s in (*SCREEN_STATUSES, "MODEL_EVIDENCE_UNVERIFIED",
                               "INSUFFICIENT_EVIDENCE")}
    counts = {
        "planned_rows": len(pre.packets) + planned_insufficient,
        "cohort_rows": len(pre.packets),
        "reused_prefix_rows": len(reused), "model_called_rows": len(called),
        "screened_packets": len(screened),
        "model_evidence_unverified": len(unverified),
        "insufficient_evidence": len(insufficient),
        "provider_unresolved": len(unresolved),
        "provider_unresolved_by_reason": dict(sorted(unresolved_by_reason.items())),
        "max_provider_unresolved": MAX_PROVIDER_UNRESOLVED,
        "reused_screened_packets": sum(1 for r in reused if r["record_kind"] == "screened_packet"),
        "reused_model_evidence_unverified": sum(
            1 for r in reused if r["record_kind"] == "model_evidence_unverified"),
        "rejections_by_reason": rejected,
        "by_screen_status": {s: sum(r["screen_status"] == s for r in screened)
                             for s in SCREEN_STATUSES},
        "firm_rollup": rollup_counts,
        "max_model_evidence_unverified": pre.authorization["max_model_evidence_unverified"],
    }
    count_entries = sum(e["operation_label"] == "count_tokens" for e in ledger)
    generate_entries = len(ledger) - count_entries
    empty_events = _empty_events(ledger)
    reconciliation = {
        "records partition the retained rows across all four populations": (
            len(records) == counts["planned_rows"]
            == len(screened) + len(unverified) + len(insufficient)
            + len(unresolved)),
        "provider-unresolved rows stayed within the authorized tolerance": (
            len(unresolved) <= MAX_PROVIDER_UNRESOLVED
            == pre.authorization["max_provider_unresolved"]),
        "every provider-unresolved row names a closed provider reason": all(
            r["failure_reason_code"] in PROVIDER_UNRESOLVED_RECORD_REASONS
            for r in unresolved),
        "no provider-unresolved row carries a status, evidence or response": all(
            r["screen_status"] is None and r["screen_output"] is None
            and r["raw_response_id"] is None and r["raw_response_sha256"] is None
            for r in unresolved),
        "every provider-unresolved row carries its attempt telemetry": all(
            isinstance(r["provider_attempt_telemetry"], dict)
            and r["provider_attempt_telemetry"]["provider_reason_code"]
            == r["failure_reason_code"]
            for r in unresolved),
        "no other row kind claims provider telemetry": all(
            r["provider_attempt_telemetry"] is None for r in records
            if r["record_kind"] != "provider_unresolved"),
        "the unresolved breakdown sums to the unresolved population": (
            sum(unresolved_by_reason.values()) == len(unresolved)),
        "provider-unresolved rows are absent from every valid-status count": (
            sum(counts["by_screen_status"].values()) == len(screened)
            and not any(r["cik"] in {u["cik"] for u in unresolved}
                        and r["screen_status"] is not None for r in unresolved)),
        "the cohort closes at every selected packet row exactly once": (
            len(reused) + len(called) == len(pre.packets)
            and {(r["cik"], r["accession"]) for r in reused + called}
            == {(p["cik"], p["accession"]) for p in pre.packets}),
        "reused and called rows partition the cohort": (
            len(reused) == len(pre.prefix_records)
            and len(called) == len(pre.suffix)),
        "provider-unresolved rows are model-called rows that produced nothing": (
            all(r["row_provenance"]["origin"] == "model_called" for r in unresolved)
            and len(unresolved) <= len(called)),
        "the reused prefix cost this run no send": all(
            e["row_ordinal"] > len(pre.prefix_records) for e in ledger),
        "the first sent row is the source's stopping row": (
            not called or (called[0]["cik"], called[0]["accession"])
            == (pre.prefix.receipt["stopping_cik"],
                pre.prefix.receipt["stopping_accession"])),
        "the archive opens with the source archive byte for byte": (
            archive_raw.startswith(pre.prefix.archive_bytes)),
        "the archive holds one line per resolved model-called row": (
            len(archive_entries)
            == len(pre.prefix_records) + len(called) - len(unresolved)),
        "every model-bearing record resolves in the archive and re-hashes": all(
            (entry := entries_by_id.get(r["raw_response_id"])) is not None
            and _sha256(entry["raw_response"].encode("utf-8"))
            == entry["raw_response_sha256"] == r["raw_response_sha256"]
            for r in screened + unverified),
        "every reused record keeps its source binding": all(
            r["row_provenance"]["source_run_id"] == pre.prefix.run_id
            and r["row_provenance"]["source_raw_responses_sha256"] == pre.prefix.archive_sha256
            and r["row_provenance"]["source_receipt_sha256"] == pre.prefix.receipt_sha256
            for r in reused),
        "every screened row's quotes resolved verbatim": all(
            r["screen_output"] is not None and r["failure_reason_code"] is None
            for r in screened),
        "every unverified row names its closed reason and claims no status": all(
            r["screen_status"] is None and r["screen_output"] is None
            and r["failure_reason_code"] in REJECTION_REASON_CODES
            for r in unverified),
        "unverified rows are counted, never omitted or relabelled": (
            sum(rejected.values()) == len(unverified)),
        "the whole-cohort breaker was not exceeded": (
            len(unverified) <= pre.authorization["max_model_evidence_unverified"]),
        "capture files rehash to their ledger lines": capture_ok,
        "no orphan capture file exists": (
            disk_refs == {e["raw_reference"] for e in persisted}),
        "count and generate sends partition external requests": (
            count_entries + generate_entries == len(ledger)),
        "no row exceeded its send ceilings": (
            count_attempts_made <= pre.authorization["count_attempt_cap"]
            and generate_attempts_made <= pre.authorization["provider_attempt_cap"]
            and len(ledger) <= pre.authorization["budget_max_external_requests"]),
        "every empty-body attempt is an attempt with no response": all(
            e.get("raw_reference") is None and e.get("raw_sha256") is None
            for e in ledger
            if e.get("provider_reason_code")
            in (EMPTY_GENERATE_BODY_REASON, EMPTY_COUNT_BODY_REASON)),
        "empty count attempts are counted but never archived": (
            _empty_count_events(ledger) == empty_count_attempts),
        "the archive holds no line for any provider-unresolved row": not (
            {(r["cik"], r["accession"]) for r in unresolved}
            & {(e["cik"], e["accession"]) for e in archive_entries}),
        "empty-body attempts are counted but never archived": (
            empty_events == empty_body_attempts),
        "model unverified blocks firm-negative": all(
            rollup[r["cik"]] != "LIKELY_INELIGIBLE" for r in unverified),
        "the prompt template hash equals the authorization's": (
            pre.prompt_sha256 == pre.authorization["prompt_template_sha256"]),
    }
    if not all(reconciliation.values()):
        raise ScreenInputError(
            "Continuation v4 reconciliation failed; no records JSONL, no capture "
            "ledger and no manifest are written. Failed identities: "
            f"{sorted(k for k, v in reconciliation.items() if not v)}.")
    records_bytes = ("\n".join(_canonical_line(r) for r in records) + "\n").encode("utf-8")
    ledger_bytes = ("\n".join(_canonical_line(r) for r in ledger) + "\n").encode("utf-8")
    try:
        write_bytes_once(run_dir / CONTINUATION_V4_RECORDS_FILENAME, records_bytes,
                         what="continuation v4 records")
        write_bytes_once(run_dir / CAPTURE_LEDGER_FILENAME, ledger_bytes,
                         what="continuation v4 capture ledger")
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
        "budget_max_estimated_cost_micros": pre.authorization["budget_max_estimated_cost_micros"],
        "budget_max_wall_clock_seconds": pre.authorization["budget_max_wall_clock_seconds"],
    }
    manifest = {
        "manifest_contract": MANIFEST_CONTRACT, "run_kind": RUN_KIND, "run_id": run_id,
        "packet_manifest_path": str(packet_manifest_path),
        "packet_manifest_sha256": pre.inputs.manifest_sha256,
        "packet_run_id": pre.inputs.manifest["run_id"],
        "packets_jsonl_sha256": pre.inputs.packets_jsonl_sha256,
        "packet_failures_jsonl_sha256": pre.inputs.failures_jsonl_sha256,
        "prompt_template_path": PROMPT_PATH, "prompt_template_sha256": pre.prompt_sha256,
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
        "continuation": {
            "source_run_id": pre.prefix.run_id,
            "source_run_path": str(source_run_dir),
            "source_kind": SOURCE_KIND,
            "source_receipt_sha256": pre.prefix.receipt_sha256,
            "source_raw_responses_sha256": pre.prefix.archive_sha256,
            "source_authorization_sha256": pre.authorization["source_authorization_sha256"],
            "reused_prefix_rows": len(reused),
            "first_model_called_row_ordinal": len(reused) + 1,
            "source_archive_is_byte_identical_prefix": True,
        },
        "parent_telemetry": {
            "per_attempt_telemetry_available": False,
            "records_completed_before_failure": pre.prefix.receipt["records_completed_before_failure"],
            "raw_responses_captured": pre.prefix.receipt["records_completed_before_failure"],
            "external_requests_made": pre.prefix.receipt["external_requests_made"],
            "provider_attempts_made": pre.prefix.receipt["provider_attempts_made"],
            "reason_code": pre.prefix.receipt["reason_code"],
            "stopping_row_index": pre.prefix.receipt["stopping_row_index"],
        },
        "provider": {"name": adapter.name, "connector": SCREEN_CONNECTOR_V6_ID,
                     "model_route": dict(adapter.model_route)},
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
        "empty_generate_body_telemetry": {
            "empty_body_attempts": empty_body_attempts,
            "rows_with_empty_body": rows_with_empty_body,
            "rows_recovered_after_empty_body": rows_recovered_after_empty,
            "max_retries_per_row": SCREEN_GENERATE_MAX_ATTEMPTS,
        },
        "empty_count_body_telemetry": {
            "empty_body_attempts": empty_count_attempts,
            "rows_with_empty_body": rows_with_empty_count,
            "rows_recovered_after_empty_body": rows_recovered_after_empty_count,
            "max_retries_per_row": SCREEN_COUNT_MAX_ATTEMPTS_V2,
        },
        "inherited_source_limitations": [
            "This cohort's reused rows were first written by one or more runs "
            "that stopped without a manifest; each was revalidated here, and "
            "none of those runs is authoritative.",
            f"Immediate source: {pre.prefix.run_id} "
            f"(receipt {pre.prefix.receipt_sha256[:16]}...), which stopped on "
            f"{pre.prefix.receipt['reason_code']}.",
            "Per-attempt wire telemetry for reused rows lives in those source "
            "runs and is not restated here.",
        ],
        "provider_unresolved_policy": {
            "max_provider_unresolved": MAX_PROVIDER_UNRESOLVED,
            "closed_reasons": list(PROVIDER_UNRESOLVED_RECORD_REASONS),
        },
        "screen_record_order": RECORD_ORDER, "firm_rollup_rule": ROLLUP_RULE,
        "baseline_cutoff": pre.inputs.baseline_cutoff, "counts": counts,
        "request_accounting": request_accounting, "reconciliation": reconciliation,
        "output_hashes": {
            CONTINUATION_V4_RECORDS_FILENAME: _sha256(records_bytes),
            RAW_RESPONSES_FILENAME: _sha256(archive_raw),
            CAPTURE_LEDGER_FILENAME: _sha256(ledger_bytes),
        },
        "run_timestamp": clock().isoformat(),
        "schema_versions": {
            "universe_screen_record_v4": "0.4.0",
            "universe_screen_continuation_manifest_v4": "0.11.0",
            "universe_screen_continuation_authorization_v4": "0.4.0",
            "universe_screen_selection": "0.1.0",
            "universe_screen_adapter_enablement": "0.1.0",
            "baseline_packet_manifest_v5": "0.5.0",
            "universe_baseline_packet_v2": "0.2.0",
        },
        "limitations": [
            "An empty generateContent body is an attempted external call with "
            "no response. It is counted as an attempt, never archived, and "
            "never hashed; its ledger event carries a null reference.",
            "Reused rows were revalidated by the same strict rules as fresh "
            "rows, but their wire-level evidence lives in their source runs: no "
            "per-attempt telemetry exists for them and none is claimed.",
            "A reused row keeps the raw_response_id it was first written under, "
            "which may name a run earlier than this manifest's immediate "
            "source; row_provenance names the run this record was revalidated "
            "from.",
            "This manifest uses its own filename, so the v0.5-v0.8 loaders "
            "refuse this directory. Promotion to a SCREEN release is a separate "
            "decision with its own loader and tests.",
            "MODEL_EVIDENCE_UNVERIFIED is a visible review state, not a screen "
            "result or exclusion.",
            "PROVIDER_UNRESOLVED means the provider never returned a usable "
            "response after the authorized retries were spent. It is not a "
            "negative result, not an exclusion, and not a model judgement: no "
            "evidence exists for such a row. It is excluded from classifier "
            "call lists and from every valid-status count, and is a named "
            "review population.",
        ],
    }
    _validate(manifest, _load_schema(root, MANIFEST_SCHEMA), "Continuation v4 manifest")
    try:
        write_bytes_once(
            run_dir / CONTINUATION_V4_MANIFEST_FILENAME,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="continuation v4 manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    result.status = "completed"
    result.counts = counts
    result.reconciliation = reconciliation
    result.request_accounting = request_accounting
    result.manifest_path = run_dir / CONTINUATION_V4_MANIFEST_FILENAME
    return result
