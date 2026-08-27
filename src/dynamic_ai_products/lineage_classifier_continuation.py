"""Governed continuation of a failed classifier run (ADR-126).

A classifier run that stops mid-cohort leaves a failure receipt, no manifest,
no records and no capture ledger — and it stays non-authoritative forever. What
it does leave is an archive of the model responses it already paid for. This
successor reuses those bytes and model-calls only the rows that remain.

**Reuse is earned.** Nothing about the parent is trusted. Every archived
response is re-rendered against its own packet, re-validated by the same strict
axes contract a fresh response faces, and re-tiered by the same pinned rule
config. A reused response that no longer validates becomes
``model_output_unusable`` here exactly as it would in a fresh run, and its
recomputed tier is derived, never copied.

**The prefix must be a prefix.** The archive holds one line per row the model
answered, so a row the provider never resolved and a row that stopped at the
output ceiling leave no line. This route therefore requires the archive to map
one-to-one onto the leading cohort rows with nothing skipped: if the parent
carried a bounded-outcome row before it stopped, its archive is not a
contiguous prefix and this route refuses it by name rather than quietly
dropping or re-deciding that row. That case needs a fresh run, not a
continuation.

**Honest telemetry.** The parent left no capture ledger, so no per-attempt
token, cost or wire accounting exists for the reused rows. The manifest records
this run's own sends only and marks the reused rows as such in every record's
output provenance.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator, FormatChecker

from .classifier_contract_set import (
    V2_1, V2_2, V2_3, V2_4, V2_5, V2_6, V2_7)
from .classifier_span_index import build_span_index
from .classifier_tier_engine import derive_tier
from .lineage_classifier_v2_1 import (
    require_completed_run,
    RECORD_ORDER,
    ClassifierRoute,
    CLASSIFIER_MANIFEST_FILENAME,
    CLASSIFIER_RAW_RESPONSES_FILENAME,
    CLASSIFIER_RECORDS_FILENAME,
    AxesValidationFailure,
    _admission_for,
    _detail,
    _execute,
    _preflight,
    render_classifier_prompt,
    validate_axes_output,
    validate_span_axes_output,
)
from .lineage_screen_live import CAPTURE_LEDGER_FILENAME
from .universe.lineage_screen import (
    FAILURE_RECEIPT_FILENAME,
    ScreenInputError,
    ScreenRunResult,
    _RUN_ID_RE,
    _decode_utf8,
    _load_schema,
    _sha256,
)

__all__ = [
    "CONTINUATION_MANIFEST_CONTRACT",
    "CONTINUATION_MANIFEST_FILENAME",
    "CONTINUATION_MANIFEST_SCHEMA",
    "CONTINUATION_RECORDS_FILENAME",
    "CONTINUATION_ROUTE",
    "CONTINUATION_ROUTE_V2_2",
    "CONTINUATION_ROUTE_V2_3",
    "CONTINUATION_ROUTE_V2_4",
    "CONTINUATION_ROUTE_V2_5",
    "CONTINUATION_ROUTE_V2_6",
    "CONTINUATION_ROUTE_V2_7",
    "ClassifierSourcePrefix",
    "load_classifier_continuation_source",
    "require_classifier_continuation_run",
    "run_lineage_classifier_continuation",
]

CONTINUATION_RECORDS_FILENAME = "universe_classifier_continuation_records.jsonl"
CONTINUATION_MANIFEST_FILENAME = "universe_classifier_continuation_manifest.json"
CONTINUATION_MANIFEST_CONTRACT = "universe_classifier_continuation_manifest@0.1.0"
CONTINUATION_MANIFEST_SCHEMA = (
    "schemas/universe_classifier_continuation_manifest.schema.json")
CONTINUATION_AUTHORIZATION_SCHEMA = (
    "schemas/universe_classifier_continuation_authorization.schema.json")

SOURCE_KIND = "failed_classifier_run"
CONTINUATION_RUN_KIND = "classifier_v2_1_continuation"

#: What this route calls its outputs. The governed loop, the reconciliation and
#: the manifest writer are the base route's, unchanged; only these names differ.
CONTINUATION_ROUTE = ClassifierRoute(
    run_kind=CONTINUATION_RUN_KIND,
    records_filename=CONTINUATION_RECORDS_FILENAME,
    manifest_filename=CONTINUATION_MANIFEST_FILENAME,
    manifest_contract=CONTINUATION_MANIFEST_CONTRACT,
    manifest_schema=CONTINUATION_MANIFEST_SCHEMA,
    record_order=RECORD_ORDER,
    authorization_schema=CONTINUATION_AUTHORIZATION_SCHEMA,
    archive_filename=CLASSIFIER_RAW_RESPONSES_FILENAME,
    contracts=V2_1,
)

#: The ADR-128 successor. Same immutable-prefix logic, wider output bounds, its
#: own contracts and filenames.
CONTINUATION_ROUTE_V2_2 = ClassifierRoute(
    run_kind=CONTINUATION_RUN_KIND,
    records_filename="universe_classifier_v2_2_continuation_records.jsonl",
    manifest_filename="universe_classifier_v2_2_continuation_manifest.json",
    manifest_contract="universe_classifier_continuation_manifest@0.2.0",
    manifest_schema=(
        "schemas/universe_classifier_continuation_manifest.v2.schema.json"),
    record_order=RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_continuation_authorization.v2.schema.json"),
    archive_filename="universe_classifier_v2_2_raw_responses.jsonl",
    contracts=V2_2,
)

#: The ADR-129 successor of the continuation route.
CONTINUATION_ROUTE_V2_3 = ClassifierRoute(
    run_kind=CONTINUATION_RUN_KIND,
    records_filename="universe_classifier_v2_3_continuation_records.jsonl",
    manifest_filename="universe_classifier_v2_3_continuation_manifest.json",
    manifest_contract="universe_classifier_continuation_manifest@0.3.0",
    manifest_schema=(
        "schemas/universe_classifier_continuation_manifest.v3.schema.json"),
    record_order=RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_continuation_authorization.v3.schema.json"),
    archive_filename="universe_classifier_v2_3_raw_responses.jsonl",
    contracts=V2_3,
)

#: ADR-130. The V2.4 continuation route. The archive filename is what keeps a
#: V2.3 failed run from being continued as a V2.4 one: the source loader is
#: handed this route's archive name explicitly, so an earlier version's prefix
#: is not found rather than being revalidated under the wider 0.3.0 bound.
CONTINUATION_ROUTE_V2_4 = ClassifierRoute(
    run_kind=CONTINUATION_RUN_KIND,
    records_filename="universe_classifier_v2_4_continuation_records.jsonl",
    manifest_filename="universe_classifier_v2_4_continuation_manifest.json",
    manifest_contract="universe_classifier_continuation_manifest@0.4.0",
    manifest_schema=(
        "schemas/universe_classifier_continuation_manifest.v4.schema.json"),
    record_order=RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_continuation_authorization.v4.schema.json"),
    archive_filename="universe_classifier_v2_4_raw_responses.jsonl",
    contracts=V2_4,
)

#: ADR-132. The V2.5 continuation route. The archive filename is what stops a
#: V2.4 failed run from being continued here, and under ADR-132 that gate does
#: more than separate versions: a V2.4 archive holds free-text quotes and no
#: span reference, so replaying it under the 0.4.0 axes contract would refuse
#: every row. The filename refuses it first, before any parse, which is the
#: honest order -- an earlier run's evidence is not V2.5's to reinterpret.
CONTINUATION_ROUTE_V2_5 = ClassifierRoute(
    run_kind=CONTINUATION_RUN_KIND,
    records_filename="universe_classifier_v2_5_continuation_records.jsonl",
    manifest_filename="universe_classifier_v2_5_continuation_manifest.json",
    manifest_contract="universe_classifier_continuation_manifest@0.5.0",
    manifest_schema=(
        "schemas/universe_classifier_continuation_manifest.v5.schema.json"),
    record_order=RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_continuation_authorization.v5.schema.json"),
    archive_filename="universe_classifier_v2_5_raw_responses.jsonl",
    contracts=V2_5,
)

#: ADR-133. The V2.6 continuation route. The archive filename keeps a V2.5
#: failed run from being continued here, as it does at every version boundary;
#: at this one it also matters that a V2.5 prefix was adjudicated under a
#: manifest contract that could not express what a retried run measured.
CONTINUATION_ROUTE_V2_6 = ClassifierRoute(
    run_kind=CONTINUATION_RUN_KIND,
    records_filename="universe_classifier_v2_6_continuation_records.jsonl",
    manifest_filename="universe_classifier_v2_6_continuation_manifest.json",
    manifest_contract="universe_classifier_continuation_manifest@0.6.0",
    manifest_schema=(
        "schemas/universe_classifier_continuation_manifest.v6.schema.json"),
    record_order=RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_continuation_authorization.v6.schema.json"),
    archive_filename="universe_classifier_v2_6_raw_responses.jsonl",
    contracts=V2_6,
)

#: ADR-134. The V2.7 successor: same route mechanics, same span protocol,
#: a prompt that states the two output rules the V2.6 calibration showed the
#: model breaking. Distinct filenames and a V7 contract keep the two runs
#: structurally unmixable.
CONTINUATION_ROUTE_V2_7 = ClassifierRoute(
    run_kind=CONTINUATION_RUN_KIND,
    records_filename="universe_classifier_v2_7_continuation_records.jsonl",
    manifest_filename="universe_classifier_v2_7_continuation_manifest.json",
    manifest_contract="universe_classifier_continuation_manifest@0.7.0",
    manifest_schema=(
        "schemas/universe_classifier_continuation_manifest.v7.schema.json"),
    record_order=RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_continuation_authorization.v7.schema.json"),
    archive_filename="universe_classifier_v2_7_raw_responses.jsonl",
    contracts=V2_7,
)

#: Receipt fields a continuable classifier failure must carry. A receipt that
#: is missing one is a shape this route has never reasoned about, and it is
#: refused rather than interpreted.
_REQUIRED_RECEIPT_FIELDS = (
    "run_id", "run_kind", "reason_code", "stopping_cik", "stopping_accession",
    "stopping_row_index", "stopping_row_completed",
    "records_completed_before_failure",
    "reused_prefix_rows", "authorization_sha256", "cohort_id",
)


@dataclass
class ClassifierSourcePrefix:
    """One failed classifier run's reusable evidence, all of it hash-bound."""

    run_dir: Path
    run_id: str
    receipt: dict
    receipt_sha256: str
    archive_bytes: bytes
    archive_sha256: str
    entries: list[dict]


def load_classifier_continuation_source(
    source_run_dir: str | Path, *, source_receipt_sha256: str,
    archive_filename: str = CLASSIFIER_RAW_RESPONSES_FILENAME,
) -> ClassifierSourcePrefix:
    """Load and structurally validate one explicitly named failed run.

    There is no discovery here by design: no run-root scan, no glob, no "latest
    failed run". The caller names a directory and pins its receipt by digest.
    """
    directory = Path(source_run_dir)
    if not directory.is_dir():
        raise ScreenInputError(
            f"Continuation source {directory} is not a directory; a source run "
            "is named explicitly and must exist."
        )
    for filename, what in ((CLASSIFIER_MANIFEST_FILENAME, "manifest"),
                           (CONTINUATION_MANIFEST_FILENAME, "continuation manifest"),
                           (CLASSIFIER_RECORDS_FILENAME, "records JSONL"),
                           (CONTINUATION_RECORDS_FILENAME, "continuation records"),
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
            "failed run is continued."
        )
    receipt_raw = receipt_path.read_bytes()
    receipt_sha = _sha256(receipt_raw)
    if receipt_sha != source_receipt_sha256:
        raise ScreenInputError(
            f"The source receipt hashes to {receipt_sha}, but "
            f"{source_receipt_sha256} was pinned; this is not the named failure."
        )
    receipt = json.loads(_decode_utf8(receipt_raw, FAILURE_RECEIPT_FILENAME))
    missing = [f for f in _REQUIRED_RECEIPT_FIELDS if f not in receipt]
    if missing:
        raise ScreenInputError(
            f"The source receipt is missing {missing}; this route continues only "
            "receipts whose shape it has reasoned about."
        )
    archive_path = directory / archive_filename
    if not archive_path.is_file():
        raise ScreenInputError(
            f"Continuation source {directory} holds no response archive; there "
            "is no evidence to reuse."
        )
    archive_bytes = archive_path.read_bytes()
    entries: list[dict] = []
    seen: set[str] = set()
    for line in _decode_utf8(
            archive_bytes, archive_filename).splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        if entry["raw_response_id"] in seen:
            raise ScreenInputError(
                f"The source archive repeats {entry['raw_response_id']!r}; a "
                "reusable prefix addresses each row exactly once."
            )
        seen.add(entry["raw_response_id"])
        if _sha256(entry["raw_response"].encode("utf-8")) != \
                entry["raw_response_sha256"]:
            raise ScreenInputError(
                f"Archived response {entry['raw_response_id']!r} no longer "
                "matches its recorded digest."
            )
        entries.append(entry)
    if not entries:
        raise ScreenInputError(
            f"Continuation source {directory} archived no response; a "
            "continuation with an empty prefix is a fresh run, not a "
            "continuation."
        )
    completed = receipt["records_completed_before_failure"]
    if completed != len(entries):
        raise ScreenInputError(
            f"The source completed {completed} row(s) but archived "
            f"{len(entries)}. A row the model never answered — a "
            "provider-unresolved or truncated row — leaves no archive line, so "
            "this source has no contiguous reusable prefix and needs a fresh "
            "run rather than a continuation."
        )
    # A stop names the row that broke, which is not always where a
    # continuation resumes. A budget-exhausted stop recorded that row before
    # stopping, so it is inside the prefix and the resume point is the row
    # after it; every other stop never completed its row, so the resume point
    # is that row itself. Either way the resume point is completed + 1, and the
    # stopping ordinal must be one of the two rows either side of that seam.
    stopping_completed = bool(receipt.get("stopping_row_completed", False))
    expected_index = completed if stopping_completed else completed + 1
    if receipt["stopping_row_index"] != expected_index:
        raise ScreenInputError(
            f"The source names stopping row {receipt['stopping_row_index']} "
            f"with {completed} completed and stopping_row_completed="
            f"{stopping_completed}; the stopping ordinal must be "
            f"{expected_index}."
        )
    return ClassifierSourcePrefix(
        run_dir=directory, run_id=receipt["run_id"], receipt=receipt,
        receipt_sha256=receipt_sha, archive_bytes=archive_bytes,
        archive_sha256=_sha256(archive_bytes), entries=entries)


def revalidate_classifier_prefix(
    prefix: ClassifierSourcePrefix, *, inputs, packets: dict, prompt_text: str,
    tier_rules, model_route: dict, validator: Draft202012Validator,
    route: ClassifierRoute, span_rules=None,
) -> list[dict]:
    """Rebuild the prefix rows from evidence, recomputing every outcome.

    ``route`` supplies the record contract these rebuilt rows declare. It has
    to: a reused row is a stored record like any other, and a row rebuilt under
    a later route must declare that route's contract or the record schema — in
    which the contract id is a const — refuses it. Hard-coding the V2.1
    contract here made the V2.2 and V2.3 continuations structurally unable to
    complete, which no name-only route test could show.
    """
    rows = inputs.rows
    if len(prefix.entries) > len(rows):
        raise ScreenInputError(
            f"The source prefix holds {len(prefix.entries)} row(s) but the "
            f"cohort covers {len(rows)}; the prefix is not a prefix."
        )
    records: list[dict] = []
    for index, entry in enumerate(prefix.entries):
        row = rows[index]
        if (entry["cik"], entry["accession"]) != (row["cik"], row["accession"]):
            raise ScreenInputError(
                f"Source row {index + 1} is cik={entry['cik']} "
                f"accession={entry['accession']}, but cohort row {index + 1} is "
                f"cik={row['cik']} accession={row['accession']}; a reusable "
                "prefix maps onto the cohort in order, with nothing skipped, "
                "reordered, duplicated or foreign."
            )
        packet = packets.get((row["cik"], row["accession"]))
        if packet is None:
            raise ScreenInputError(
                f"Cohort row {index + 1} is absent from the packet cohort."
            )
        if packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError(
                f"Cohort row {index + 1} no longer matches its recorded packet "
                "digest."
            )
        admission = _admission_for(row, inputs, packet)
        span_index = (build_span_index(packet, span_rules)
                      if span_rules is not None else None)
        rendered, _refs = render_classifier_prompt(prompt_text, packet, admission,
                                                   span_index=span_index)
        record = {
            "record_contract": route.contracts.record_contract,
            "cik": row["cik"],
            "accession": row["accession"], "company_id": row["company_id"],
            "form": row["form"], "baseline_filing_date": row["baseline_filing_date"],
            "source_id": row["source_id"], "packet_sha256": row["packet_sha256"],
            "prompt_sha256": _sha256(rendered.encode("utf-8")),
            "model_route": dict(model_route),
            "admission_provenance": {
                "cohort_id": admission["cohort_id"],
                "admission_origin": admission["admission_origin"],
                "admitted_status": admission["admitted_status"],
                "non_authoritative": True,
                "model_screen": admission["model_screen"],
                "human_review": admission["human_review"]},
            "output_provenance": {
                "run_id": prefix.run_id, "origin": "reused_source_prefix",
                "raw_response_id": entry["raw_response_id"],
                "raw_response_sha256": entry["raw_response_sha256"],
                "source_run_id": prefix.run_id,
                "source_raw_responses_sha256": prefix.archive_sha256,
                "source_receipt_sha256": prefix.receipt_sha256},
            **({"span_index_version": span_rules.version,
                "span_index_sha256": span_rules.sha256}
               if span_rules is not None else {}),
            "axes": None, "tier": None, "tier_rule_trace": None,
            "failure_reason_code": None, "failure_detail": None,
            "provider_attempt_telemetry": None, "truncation_evidence": None,
        }
        try:
            if span_index is not None:
                axes = validate_span_axes_output(
                    entry["raw_response"], packet, validator,
                    route.contracts.axes_contract, span_index)
            else:
                axes = validate_axes_output(entry["raw_response"], packet, validator,
                                            route.contracts.axes_contract)
        except AxesValidationFailure as exc:
            record.update(record_kind="model_output_unusable",
                          failure_reason_code=exc.reason_code,
                          failure_detail=_detail(exc.detail))
        else:
            derivation = derive_tier(axes, tier_rules)
            record.update(record_kind="classified", axes=axes,
                          tier=derivation.tier, tier_rule_trace=derivation.trace)
        records.append(record)
    return records


def require_classifier_continuation_run(
    run_dir: str | Path, *, route: ClassifierRoute | None = None
) -> Path:
    """Refuse any continuation run that is not completed and self-consistent.

    ``route`` defaults to the V2.1 continuation route, so existing callers are
    unchanged; pass a later route to consume that version's run instead.
    """
    directory = Path(run_dir)
    route = route or CONTINUATION_ROUTE
    require_completed_run(directory, route, what="Continuation run")
    return directory / route.manifest_filename

def run_lineage_classifier_continuation(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    overlay_manifest_path: str | Path, release_manifest_path: str | Path,
    packet_manifest_path: str | Path, governance_root: str | Path,
    authorization_reference: str, authorization_sha256: str,
    source_run_dir: str | Path, output_dir: str | Path, run_id: str,
    clock: Callable[[], datetime], dry_run: bool = False,
    client_factory: Any = None, sleep: Callable[[float], None] | None = None,
    route: ClassifierRoute = CONTINUATION_ROUTE,
) -> ScreenRunResult:
    """Continue one named failed classifier run under a fresh grant."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError("Invalid run id.")
    axes_validator = Draft202012Validator(
        _load_schema(root, route.contracts.axes_schema),
        format_checker=FormatChecker())
    holder: dict[str, Any] = {}

    def prefix_loader(authorization, inputs, packets, prompt_text, tier_rules,
                      model_route, span_rules=None):
        if str(Path(authorization["source_run_path"])) != str(Path(source_run_dir)):
            raise ScreenInputError(
                f"The grant names source run {authorization['source_run_path']!r}, "
                f"not {str(source_run_dir)!r}."
            )
        prefix = load_classifier_continuation_source(
            source_run_dir,
            source_receipt_sha256=authorization["source_receipt_sha256"],
            archive_filename=route.archive_filename)
        if prefix.run_id != authorization["source_run_id"]:
            raise ScreenInputError(
                f"The source run is {prefix.run_id!r}, but the grant names "
                f"{authorization['source_run_id']!r}."
            )
        if prefix.archive_sha256 != authorization["source_raw_responses_sha256"]:
            raise ScreenInputError(
                f"The source archive hashes to {prefix.archive_sha256}, but "
                f"{authorization['source_raw_responses_sha256']} was pinned."
            )
        if prefix.receipt["authorization_sha256"] != \
                authorization["source_authorization_sha256"]:
            raise ScreenInputError(
                "The source ran under a different grant than the one this "
                "continuation names; the prefix was produced under rules that "
                "were never checked against these."
            )
        if prefix.receipt["cohort_id"] != authorization["cohort_id"]:
            raise ScreenInputError(
                f"The source classified cohort {prefix.receipt['cohort_id']!r}, "
                f"not {authorization['cohort_id']!r}."
            )
        records = revalidate_classifier_prefix(
            prefix, inputs=inputs, packets=packets, prompt_text=prompt_text,
            tier_rules=tier_rules, model_route=model_route,
            validator=axes_validator, route=route, span_rules=span_rules)
        stopping = (prefix.receipt["stopping_cik"],
                    prefix.receipt["stopping_accession"])
        # The stopping row sits at its own recorded ordinal, which is the last
        # prefix row for a budget stop and the first re-sent row otherwise.
        ordinal = prefix.receipt["stopping_row_index"]
        if not 1 <= ordinal <= len(inputs.rows):
            raise ScreenInputError(
                f"The source names stopping ordinal {ordinal}, outside the "
                f"cohort's {len(inputs.rows)} rows."
            )
        at_ordinal = inputs.rows[ordinal - 1]
        if (at_ordinal["cik"], at_ordinal["accession"]) != stopping:
            raise ScreenInputError(
                f"The source stopped on {stopping}, but row {ordinal} of the "
                f"scope is {(at_ordinal['cik'], at_ordinal['accession'])}."
            )
        holder["prefix"] = prefix
        return records, {
            "source_run_id": prefix.run_id,
            "source_run_path": str(prefix.run_dir),
            "source_receipt_sha256": prefix.receipt_sha256,
            "source_raw_responses_sha256": prefix.archive_sha256,
            "archive_bytes": prefix.archive_bytes,
        }

    pre = _preflight(
        root=root, governance_root=Path(governance_root),
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256,
        cohort_manifest_path=Path(cohort_manifest_path),
        overlay_manifest_path=Path(overlay_manifest_path),
        release_manifest_path=Path(release_manifest_path),
        packet_manifest_path=packet_manifest_path, clock=clock,
        route=route, prefix_loader=prefix_loader)
    if dry_run:
        for row, packet, admission in pre.plan:
            render_classifier_prompt(pre.prompt_text, packet, admission)
        return ScreenRunResult(
            run_id, None, True, "dry_run", len(pre.plan), 0,
            request_accounting={
                "cohort_rows": len(pre.inputs.rows),
                "reused_prefix_rows": len(pre.prefix_records),
                "model_called_rows": len(pre.plan),
                "count_attempt_cap": pre.authorization["count_attempt_cap"],
                "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
                "external_request_cap":
                    pre.authorization["budget_max_external_requests"],
            })
    return _execute(root=root, pre=pre, output_dir=output_dir, run_id=run_id,
                    authorization_sha256=authorization_sha256, clock=clock,
                    client_factory=client_factory, sleep=sleep)
