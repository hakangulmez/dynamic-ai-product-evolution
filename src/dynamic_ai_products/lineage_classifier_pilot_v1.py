"""Governed live run of the ten-firm firm-level pilot (ADR-137).

This is the execution path for the pilot, and it is a separate path on purpose.
It shares the generic transport with every other governed run in this repository
— the same connector, the same per-row capture ledger, the same retry and
rate-limit policies, the same cohort budget, the same write-once discipline — and
shares nothing above that line with the V2.x classifier. It imports no V2 route,
no V2 manifest or authorization contract, no axes or record contract of that
ladder, no tier rules and no tier engine. A V2 loader refuses this run's manifest
on its filename before reading its contract, and this module refuses a V2 grant on
its ``authorization_contract`` const.

**The input surface is smaller than V2's, and that is the point.** A V2 run
hydrates the release and the overlay so it can render the earlier verdict to the
model and invite contradiction. The pilot must never render that verdict, so it
never loads it: its inputs are the pinned pilot selection, the cohort manifest it
was drawn from, and the packet cohort. Admission provenance travels on the
selection row, is copied into the stored record for audit, and reaches no prompt,
because :func:`render_pilot_prompt` accepts a template and a packet and has no
parameter it could arrive through.

**A model-response defect costs one row; a provider failure costs the run.** The
two are different kinds of event and the pilot refuses to blur them. Invalid JSON,
a contract violation, a forbidden field and an unresolvable evidence reference are
things this experiment exists to observe, so each becomes a ``review_uncertain``
record with its reason and the run continues through all ten rows. A genuine
provider failure — an exhausted budget, a terminal transport error, a truncated
envelope — is not an observation about a filing at all. It stops the run and
writes a failure receipt naming the row, so no records file and no manifest exist;
turning it into a stored row would let an infrastructure outage read as a
substantive judgement about a firm.

**No tolerance, and nothing to tune.** The four review reasons are non-fatal by
construction rather than by budget, so the grant states no bounded-outcome ceiling
and the authorization schema has no field for one. Ten rows could not calibrate a
tolerance in any case.

**Ten is structural.** The row count is the length of the committed
``PILOT_ROWS`` list, the selection schema bounds its rows to exactly ten, the
grant pins ``logical_row_cap`` as a const, and the derived request caps are
checked against the retry policies rather than accepted from the grant. A run over
any other count is a different experiment and needs a successor contract.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.extraction.provider_adapter import client_contract_digest
from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once
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

from .classifier_candidate_cohort import (
    COHORT_MANIFEST_FILENAME,
    COHORT_RECORDS_FILENAME,
    require_classifier_candidate_cohort,
)
from .classifier_pilot_selection import PILOT_ROW_CAP, require_pilot_selection
from .classifier_pilot_v1 import (
    PILOT_AXES_CONTRACT,
    PILOT_AXES_SCHEMA,
    PILOT_PROMPT_PATH,
    PILOT_RECORD_CONTRACT,
    PILOT_RECORD_SCHEMA,
    PILOT_SELECTION_CONTRACT,
    REVIEW_REASONS,
    build_pilot_record,
    render_pilot_prompt,
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
    _RUN_ID_RE,
    FAILURE_RECEIPT_FILENAME,
    ScreenInputError,
    ScreenProviderTerminalError,
    ScreenRunResult,
    _canonical_line,
    _decode_utf8,
    _load_schema,
    _sha256,
    _validate,
    load_packet_run,
)

__all__ = [
    "PILOT_AUTHORIZATION_CONTRACT",
    "PILOT_AUTHORIZATION_SCHEMA",
    "PILOT_MANIFEST_CONTRACT",
    "PILOT_MANIFEST_FILENAME",
    "PILOT_MANIFEST_SCHEMA",
    "PILOT_RAW_RESPONSES_FILENAME",
    "PILOT_RECORDS_FILENAME",
    "PILOT_RECORD_ORDER",
    "PILOT_RUN_KIND",
    "PILOT_RUN_ROOT_NAME",
    "PilotRunRoute",
    "require_pilot_run",
    "run_lineage_classifier_pilot_v1",
]

PILOT_RUN_KIND = "classifier_pilot_v1"
PILOT_RECORD_ORDER = "pilot_selection_row_order"

#: The pilot's own output names. Nothing here is shared with a V2.x route, so a
#: V2 loader refuses a pilot run on its manifest filename before it reads a
#: contract, and this module's loader refuses a V2 run the same way.
PILOT_RECORDS_FILENAME = "universe_classifier_pilot_v1_records.jsonl"
PILOT_MANIFEST_FILENAME = "universe_classifier_pilot_v1_manifest.json"
PILOT_RAW_RESPONSES_FILENAME = "universe_classifier_pilot_v1_raw_responses.jsonl"

PILOT_MANIFEST_CONTRACT = "universe_classifier_pilot_manifest@0.1.0"
PILOT_MANIFEST_SCHEMA = "schemas/universe_classifier_pilot_manifest.v1.schema.json"
PILOT_AUTHORIZATION_CONTRACT = "universe_classifier_pilot_authorization@0.1.0"
PILOT_AUTHORIZATION_SCHEMA = (
    "schemas/universe_classifier_pilot_authorization.v1.schema.json")

#: The conventional run root for this mode, named so pilot runs never land beside
#: V2.x classifier runs. This module creates nothing: the caller passes the root
#: it wants and the name exists so the CLI and the decision log can agree on one.
PILOT_RUN_ROOT_NAME = "universe-classifier-pilot-v1-runs"


@dataclass(frozen=True)
class PilotRunRoute:
    """Contract-owned names for one isolated pilot execution route."""

    run_kind: str
    records_filename: str
    manifest_filename: str
    raw_responses_filename: str
    manifest_contract: str
    manifest_schema: str
    authorization_contract: str
    authorization_schema: str
    run_root_name: str
    selection_contract: str
    selection_kind: str
    selection_source: str
    load_selection: Callable[[Path, str, Path], dict]
    prompt_path: str
    axes_schema: str
    axes_contract: str
    record_schema: str
    record_contract: str
    judgement_axes: tuple[str, ...]
    build_record: Callable[..., dict]


def _load_v1_selection(path: Path, digest: str, _root: Path) -> dict:
    return require_pilot_selection(path, expected_sha256=digest)


PILOT_V1_ROUTE = PilotRunRoute(
    run_kind=PILOT_RUN_KIND,
    records_filename=PILOT_RECORDS_FILENAME,
    manifest_filename=PILOT_MANIFEST_FILENAME,
    raw_responses_filename=PILOT_RAW_RESPONSES_FILENAME,
    manifest_contract=PILOT_MANIFEST_CONTRACT,
    manifest_schema=PILOT_MANIFEST_SCHEMA,
    authorization_contract=PILOT_AUTHORIZATION_CONTRACT,
    authorization_schema=PILOT_AUTHORIZATION_SCHEMA,
    run_root_name=PILOT_RUN_ROOT_NAME,
    selection_contract=PILOT_SELECTION_CONTRACT,
    selection_kind="classifier_pilot_v1",
    selection_source="calibration",
    load_selection=_load_v1_selection,
    prompt_path=PILOT_PROMPT_PATH,
    axes_schema=PILOT_AXES_SCHEMA,
    axes_contract=PILOT_AXES_CONTRACT,
    record_schema=PILOT_RECORD_SCHEMA,
    record_contract=PILOT_RECORD_CONTRACT,
    judgement_axes=(
        "customer_facing_functional_product",
        "software_centrality",
        "firm_structure",
        "commercial_materiality",
    ),
    build_record=build_pilot_record,
)

RECEIPT_CONTRACT = "universe_screen_failure_receipt@0.1.0"

_DETAIL_LIMIT = 400

#: The four axes the pilot reports distributions over. Written once here so the
#: manifest's tallies and the reconciliation that closes them cannot drift apart.
PILOT_AXES: tuple[str, ...] = (
    "customer_facing_functional_product",
    "software_centrality",
    "firm_structure",
    "commercial_materiality",
)


def _detail(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= _DETAIL_LIMIT else text[:_DETAIL_LIMIT - 1] + "…"


@dataclass
class _PilotPreflight:
    route: PilotRunRoute
    authorization: dict
    enablement: dict
    contract_digest: str
    endpoints: dict
    prompt_text: str
    prompt_sha256: str
    selection: dict
    selection_sha256: str
    selection_path: str
    cohort: dict
    cohort_digests: dict
    coverage_digests: dict | None
    packet_digests: dict
    packets: dict
    model_route: dict
    plan: list[tuple[dict, dict]] = field(default_factory=list)


def _pilot_preflight(
    *, root: Path, governance_root: Path, authorization_reference: str,
    authorization_sha256: str, cohort_manifest_path: Path,
    packet_manifest_path: str | Path, selection_path: str | Path,
    coverage_manifest_path: str | Path | None, route: PilotRunRoute,
    clock: Callable[[], datetime],
) -> _PilotPreflight:
    """Everything provable, proven, before any output or network exists.

    Nothing in this function creates a directory, imports the provider SDK,
    resolves a credential or opens a socket. A grant that does not bind exactly
    these inputs is refused here, where refusing costs nothing.
    """
    authorization, _ = _hydrate_pinned(
        governance_root, authorization_reference, authorization_sha256,
        "classifier pilot authorization")
    if authorization.get("authorization_contract") != route.authorization_contract:
        raise ScreenInputError(
            f"The grant declares "
            f"{authorization.get('authorization_contract')!r}; this route runs "
            f"{route.authorization_contract!r} only.")
    _validate(authorization, _load_schema(root, route.authorization_schema),
              "Classifier pilot authorization")
    enablement, _ = _hydrate_pinned(
        governance_root, authorization["screen_adapter_enablement_reference"],
        authorization["screen_adapter_enablement_sha256"],
        "screen adapter enablement")
    _validate(enablement, _load_schema(root, ENABLEMENT_SCHEMA_RELATIVE_PATH),
              "Screen adapter enablement")
    now = clock()
    for label, artifact in (("authorization", authorization),
                            ("enablement", enablement)):
        if not (_parse_moment(artifact["effective_at"], f"{label} effective_at")
                <= now < _parse_moment(artifact["expires_at"], f"{label} expires_at")):
            raise ScreenInputError(
                f"The {label} is outside its effective window; nothing runs.")

    contract = build_client_contract_v2(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"])
    digest = client_contract_digest(contract)
    model_route = {"provider": contract["model_provider"],
                   "model_label": contract["model_name"]}
    if (authorization["provider_client_contract_reference"] != CLIENT_CONTRACT_V2_ID
            or authorization["provider_client_contract_sha256"] != digest
            or enablement["provider_client_contract_reference"] != CLIENT_CONTRACT_V2_ID
            or enablement["provider_client_contract_sha256"] != digest):
        raise ScreenInputError(
            "Authorization or enablement binds a different provider client "
            "contract.")
    if (authorization["model_route"] != model_route
            or authorization["retry_policy_version"] != RETRY_POLICY_VERSION
            or authorization["rate_limit_policy_version"] != RATE_LIMIT_POLICY_VERSION
            or authorization["screen_generate_retry_policy_version"]
            != SCREEN_GENERATE_RETRY_POLICY_VERSION
            or authorization["screen_count_retry_policy_version"]
            != SCREEN_COUNT_RETRY_POLICY_VERSION
            or authorization["count_attempts_per_row"] != SCREEN_COUNT_MAX_ATTEMPTS_V2
            or authorization["generate_attempts_per_row"]
            != SCREEN_GENERATE_MAX_ATTEMPTS
            or authorization["external_requests_per_row"]
            != SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2
            or authorization["output_contract"] != route.record_contract
            or authorization["output_axes_contract"] != route.axes_contract):
        raise ScreenInputError(
            "Authorization route, policy versions, ceilings or contracts do not "
            "match the committed ones.")
    if authorization["run_kind"] != route.run_kind:
        raise ScreenInputError("The grant names a different run kind.")
    if authorization["promotable"] is not False:
        raise ScreenInputError("A pilot grant may never be promotable.")
    if authorization["covers_full_cohort"] is not False:
        raise ScreenInputError(
            "A pilot grant may never claim full-cohort coverage; ten named "
            "filings are not a universe.")

    endpoints = build_operation_endpoints(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"])
    if set(authorization["endpoint_allowlist"]) != set(endpoints.values()) or \
            set(enablement["endpoint_allowlist"]) != set(endpoints.values()):
        raise ScreenInputError(
            "Authorization/enablement endpoint allowlists are not exactly the "
            "derived operation endpoints.")

    if authorization["prompt_template_path"] != route.prompt_path:
        raise ScreenInputError(
            f"The grant binds prompt {authorization['prompt_template_path']!r}; "
            f"this route runs {route.prompt_path!r} only.")
    prompt_raw = (root / route.prompt_path).read_bytes()
    prompt_sha = _sha256(prompt_raw)
    if prompt_sha != authorization["prompt_template_sha256"]:
        raise ScreenInputError(
            "Authorization does not bind the committed pilot prompt bytes.")

    cohort_path = Path(cohort_manifest_path)
    if cohort_path.name != COHORT_MANIFEST_FILENAME:
        raise ScreenInputError(
            f"The cohort manifest must be {COHORT_MANIFEST_FILENAME}; "
            f"{cohort_path.name} is a different artifact.")
    if not cohort_path.is_file():
        raise ScreenInputError(f"Cohort manifest not found: {cohort_path}")
    cohort_raw = cohort_path.read_bytes()
    if _sha256(cohort_raw) != authorization["cohort_manifest_sha256"]:
        raise ScreenInputError(
            "Authorization binds a different cohort manifest than the one "
            "presented.")
    cohort = json.loads(_decode_utf8(cohort_raw, COHORT_MANIFEST_FILENAME))
    require_classifier_candidate_cohort(cohort_path.parent)
    if cohort["cohort_id"] != authorization["cohort_id"]:
        raise ScreenInputError("Authorization names a different cohort.")
    cohort_records_raw = (cohort_path.parent / COHORT_RECORDS_FILENAME).read_bytes()
    if _sha256(cohort_records_raw) != cohort["output_hashes"][COHORT_RECORDS_FILENAME]:
        raise ScreenInputError(
            f"{COHORT_RECORDS_FILENAME} no longer hashes to the digest its "
            "manifest records; nothing may be read from it.")

    packet_inputs = load_packet_run(root, packet_manifest_path)
    if packet_inputs.manifest_sha256 != authorization["packet_manifest_sha256"]:
        raise ScreenInputError("Authorization binds a different packet cohort.")
    packets = {(p["cik"], p["accession"]): p for p in packet_inputs.packets}

    resolved_selection = Path(selection_path)
    if str(Path(authorization["selection_artifact_path"])) != str(resolved_selection):
        raise ScreenInputError(
            f"The grant names selection "
            f"{authorization['selection_artifact_path']!r}, not "
            f"{str(resolved_selection)!r}.")
    selection = route.load_selection(
        resolved_selection, authorization["selection_artifact_sha256"], root)
    if selection["selection_kind"] != authorization["selection_kind"]:
        raise ScreenInputError("The grant names a different selection kind.")
    selection_cohort_sha = (selection["cohort_manifest_sha256"]
                            if route.selection_source == "calibration"
                            else selection["candidate_cohort_manifest_sha256"])
    selection_cohort_id = (selection["cohort_id"]
                           if route.selection_source == "calibration"
                           else selection["candidate_cohort_id"])
    if selection_cohort_sha != authorization["cohort_manifest_sha256"]:
        raise ScreenInputError(
            "The selection was built from a different cohort than the one this "
            "grant binds.")
    if selection_cohort_id != authorization["cohort_id"]:
        raise ScreenInputError("The selection names a different cohort id.")
    if selection["packet_manifest_sha256"] != authorization["packet_manifest_sha256"]:
        raise ScreenInputError(
            "The selection was built against a different packet cohort than the "
            "one this grant binds.")

    coverage_digests = None
    if route.selection_source == "annual_coverage":
        if coverage_manifest_path is None:
            raise ScreenInputError(
                "The annual-coverage pilot route requires its coverage manifest.")
        from .classifier_annual_coverage_cohort import (
            COVERAGE_MANIFEST_FILENAME,
            COVERAGE_RECORDS_FILENAME,
            require_annual_coverage_cohort,
        )

        coverage_path = Path(coverage_manifest_path)
        if coverage_path.name != COVERAGE_MANIFEST_FILENAME or not coverage_path.is_file():
            raise ScreenInputError("The annual coverage manifest is missing or has the wrong filename.")
        coverage_raw = coverage_path.read_bytes()
        if _sha256(coverage_raw) != authorization["coverage_cohort_manifest_sha256"]:
            raise ScreenInputError("Authorization binds a different annual coverage manifest.")
        require_annual_coverage_cohort(coverage_path.parent)
        coverage = json.loads(_decode_utf8(coverage_raw, COVERAGE_MANIFEST_FILENAME))
        coverage_source = coverage["sources"]["candidate_cohort"]
        if (coverage_source["cohort_id"] != cohort["cohort_id"]
                or coverage_source["manifest_sha256"]
                != authorization["cohort_manifest_sha256"]
                or coverage_source["records_jsonl_sha256"]
                != _sha256(cohort_records_raw)):
            raise ScreenInputError(
                "The annual coverage cohort was built from a different "
                "candidate cohort than this grant binds.")
        if (coverage["coverage_cohort_id"] != authorization["coverage_cohort_id"]
                or selection["coverage_cohort_id"] != authorization["coverage_cohort_id"]
                or selection["coverage_cohort_manifest_sha256"]
                != authorization["coverage_cohort_manifest_sha256"]
                or selection["coverage_cohort_records_sha256"]
                != authorization["coverage_cohort_records_sha256"]):
            raise ScreenInputError("Selection, coverage cohort and authorization disagree.")
        records_raw = (coverage_path.parent / COVERAGE_RECORDS_FILENAME).read_bytes()
        if _sha256(records_raw) != authorization["coverage_cohort_records_sha256"]:
            raise ScreenInputError("Annual coverage records no longer match the grant.")
        coverage_digests = {
            "coverage_cohort_id": coverage["coverage_cohort_id"],
            "manifest_sha256": authorization["coverage_cohort_manifest_sha256"],
            "records_jsonl_sha256": _sha256(records_raw),
        }

    plan: list[tuple[dict, dict]] = []
    for row in selection["rows"]:
        key = (row["cik"], row["accession"])
        packet = packets.get(key)
        if packet is None:
            raise ScreenInputError(
                f"Selected row {key} is absent from the packet cohort.")
        if packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError(
                f"Selected row {key} no longer matches its recorded packet "
                "digest.")
        plan.append((row, packet))
    if len(plan) != PILOT_ROW_CAP:
        raise ScreenInputError(
            f"The pilot plan holds {len(plan)} row(s); this experiment is "
            f"exactly {PILOT_ROW_CAP}.")
    if len({(r["cik"], r["accession"]) for r, _ in plan}) != len(plan):
        raise ScreenInputError("The selection names a filing twice.")

    called = len(plan)
    if authorization["logical_row_cap"] != called:
        raise ScreenInputError(
            f"The grant authorizes {authorization['logical_row_cap']} row(s) "
            f"but this route's scope holds {called}.")
    if authorization["count_attempt_cap"] != screen_count_attempt_cap(called):
        raise ScreenInputError(
            f"count_attempt_cap must be exactly "
            f"{screen_count_attempt_cap(called)}.")
    if authorization["provider_attempt_cap"] != screen_generate_attempt_cap(called):
        raise ScreenInputError(
            f"provider_attempt_cap must be exactly "
            f"{screen_generate_attempt_cap(called)}.")
    if authorization["budget_max_external_requests"] != \
            screen_external_request_cap_v2(called):
        raise ScreenInputError(
            f"budget_max_external_requests must be exactly "
            f"{screen_external_request_cap_v2(called)}.")

    return _PilotPreflight(
        route=route,
        authorization=authorization, enablement=enablement, contract_digest=digest,
        endpoints=endpoints,
        prompt_text=_decode_utf8(prompt_raw, "classifier pilot prompt"),
        prompt_sha256=prompt_sha, selection=selection,
        selection_sha256=authorization["selection_artifact_sha256"],
        selection_path=str(resolved_selection), cohort=cohort,
        cohort_digests={"cohort_id": cohort["cohort_id"],
                        "manifest_sha256": authorization["cohort_manifest_sha256"],
                        "records_jsonl_sha256": _sha256(cohort_records_raw)},
        coverage_digests=coverage_digests,
        packet_digests={"packet_manifest_path": str(Path(packet_manifest_path)),
                        "packet_manifest_sha256": packet_inputs.manifest_sha256,
                        "packets_jsonl_sha256": packet_inputs.packets_jsonl_sha256},
        packets=packets, model_route=model_route, plan=plan)


def run_lineage_classifier_pilot_v1(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    packet_manifest_path: str | Path, selection_path: str | Path,
    governance_root: str | Path, authorization_reference: str,
    authorization_sha256: str, output_dir: str | Path, run_id: str,
    clock: Callable[[], datetime], dry_run: bool = False,
    client_factory: Any = None, sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    """Run the ten-firm firm-level pilot under one governed grant.

    A dry run resolves every one of the ten inputs, renders every prompt, reports
    the derived caps, and stops there: no run directory is created, no provider
    client is constructed, no credential is resolved and nothing is written.
    """
    return _run_lineage_classifier_pilot(
        route=PILOT_V1_ROUTE, repo_root=repo_root,
        cohort_manifest_path=cohort_manifest_path,
        packet_manifest_path=packet_manifest_path, selection_path=selection_path,
        coverage_manifest_path=None, governance_root=governance_root,
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256, output_dir=output_dir,
        run_id=run_id, clock=clock, dry_run=dry_run,
        client_factory=client_factory, sleep=sleep)


def _run_lineage_classifier_pilot(
    *, route: PilotRunRoute, repo_root: str | Path, cohort_manifest_path: str | Path,
    packet_manifest_path: str | Path, selection_path: str | Path,
    coverage_manifest_path: str | Path | None, governance_root: str | Path,
    authorization_reference: str, authorization_sha256: str, output_dir: str | Path,
    run_id: str, clock: Callable[[], datetime], dry_run: bool = False,
    client_factory: Any = None, sleep: Callable[[float], None] | None = None,
) -> ScreenRunResult:
    """Execute one configured pilot route; public wrappers own route identity."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError("Invalid run id.")
    pre = _pilot_preflight(
        root=root, governance_root=Path(governance_root),
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256,
        cohort_manifest_path=Path(cohort_manifest_path),
        packet_manifest_path=packet_manifest_path, selection_path=selection_path,
        coverage_manifest_path=coverage_manifest_path, route=route, clock=clock)
    if dry_run:
        for _row, packet in pre.plan:
            render_pilot_prompt(pre.prompt_text, packet)
        return ScreenRunResult(
            run_id, None, True, "dry_run", len(pre.plan), 0,
            request_accounting={
                "selected_rows": len(pre.selection["rows"]),
                "model_called_rows": len(pre.plan),
                "logical_row_cap": pre.authorization["logical_row_cap"],
                "count_attempt_cap": pre.authorization["count_attempt_cap"],
                "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
                "external_request_cap":
                    pre.authorization["budget_max_external_requests"],
            })
    return _pilot_execute(root=root, pre=pre, output_dir=output_dir, run_id=run_id,
                          authorization_sha256=authorization_sha256, clock=clock,
                          client_factory=client_factory, sleep=sleep)


def _pilot_execute(*, root: Path, pre: _PilotPreflight, output_dir, run_id: str,
                   authorization_sha256: str, clock, client_factory, sleep
                   ) -> ScreenRunResult:
    """The governed loop: ten rows, two record kinds, one archive line per send."""
    connector = VertexGeminiScreenV6(
        vertex_project=pre.authorization["vertex_project"],
        vertex_location=pre.authorization["vertex_location"],
        expected_authorization_sha256=authorization_sha256,
        max_provider_requests=SCREEN_GENERATE_MAX_ATTEMPTS,
        endpoint_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
        client_factory=client_factory, sleep=sleep)
    try:
        connector.assert_run_permitted(
            authorization_sha256=authorization_sha256,
            endpoint_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
            enablement_endpoint_allowlist=tuple(pre.enablement["endpoint_allowlist"]))
    except ProviderError as exc:
        raise ScreenInputError(
            f"Connector handshake refused: {exc.reason_code}.") from exc
    finally:
        connector.revoke_run_permission()

    run_dir = create_run_directory(output_dir, run_id)
    result = ScreenRunResult(run_id, run_dir, False, "failed", len(pre.plan), 0)
    budget = ScreenCohortBudgetV3(
        authorization=pre.authorization, authorization_sha256=authorization_sha256,
        run_id=run_id, clock=clock)
    ledger: list[dict] = []
    adapter = VertexLineageScreenProvider(
        connector=connector, authorization_sha256=authorization_sha256,
        authorization_allowlist=tuple(pre.authorization["endpoint_allowlist"]),
        enablement_allowlist=tuple(pre.enablement["endpoint_allowlist"]),
        run_dir=run_dir, budget=budget,
        packet_sha_by_key={(p["cik"], p["accession"]): p["packet_sha256"]
                           for _, p in pre.plan},
        prompt_template_sha256=pre.prompt_sha256, ledger=ledger)

    archive_path = run_dir / pre.route.raw_responses_filename
    archive = os.fdopen(
        os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), "wb")
    axes_validator = Draft202012Validator(
        _load_schema(root, pre.route.axes_schema), format_checker=FormatChecker())

    records: list[dict] = []
    called_rows = count_attempts = generate_attempts = 0
    rows_count_retried = rows_generate_retried = 0

    def fail(reason: str, detail: str, row: dict) -> ScreenRunResult:
        """Write the receipt for a provider stop and return.

        A provider failure is never stored as a row. The pilot's four review
        reasons all describe a model response the pipeline could read and refuse;
        an exhausted budget or a terminal transport error describes neither the
        filing nor the model, and recording it beside a judgement would let an
        outage read as a finding.
        """
        archive.flush()
        os.fsync(archive.fileno())
        archive.close()
        generates = sum(e["operation_label"] == "generate_content" for e in ledger)
        receipt = {
            "receipt_contract": RECEIPT_CONTRACT, "run_id": run_id,
            "run_kind": pre.route.run_kind, "reason_code": reason,
            "detail": _detail(detail), "stopping_cik": row["cik"],
            "stopping_accession": row["accession"],
            "stopping_row_index": len(records) + 1,
            "stopping_row_completed": False,
            "records_completed_before_failure": len(records),
            "model_called_rows_attempted": called_rows,
            "external_requests_made": len(ledger),
            "count_attempts_made": len(ledger) - generates,
            "provider_attempts_made": generates,
            "authorization_sha256": authorization_sha256,
            "cohort_id": pre.cohort["cohort_id"],
            "selection_id": pre.selection["selection_id"],
            "run_timestamp": clock().isoformat(),
            "retention_note": (
                "Non-authoritative pilot run: no records JSONL, no capture "
                "ledger and no manifest exist here. A provider failure is not a "
                "judgement about any filing and none was recorded. This "
                "directory is immutable; a further attempt requires a new run "
                "id and a new authorization."),
        }
        try:
            write_bytes_once(
                run_dir / FAILURE_RECEIPT_FILENAME,
                (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                what="classifier pilot failure receipt")
        except WriteOnceError as exc:
            raise ScreenInputError(str(exc)) from exc
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        result.receipt = receipt
        return result

    for row, packet in pre.plan:
        rendered = render_pilot_prompt(pre.prompt_text, packet)
        called_rows += 1
        before = len(ledger)
        try:
            raw = adapter.screen(rendered, cik=row["cik"], accession=row["accession"])
        except ScreenProviderTerminalError as exc:
            spent = ledger[before:]
            count_attempts += sum(
                e["operation_label"] == "count_tokens" for e in spent)
            generate_attempts += sum(
                e["operation_label"] == "generate_content" for e in spent)
            return fail("provider_error", str(exc), row)
        spent = ledger[before:]
        row_counts = sum(e["operation_label"] == "count_tokens" for e in spent)
        row_generates = sum(e["operation_label"] == "generate_content" for e in spent)
        count_attempts += row_counts
        generate_attempts += row_generates
        if row_counts > 1:
            rows_count_retried += 1
        if row_generates > 1:
            rows_generate_retried += 1
        if count_attempts > pre.authorization["count_attempt_cap"]:
            return fail("provider_error", "countTokens attempt cap exceeded.", row)
        if generate_attempts > pre.authorization["provider_attempt_cap"]:
            return fail("provider_error", "Provider attempt cap exceeded.", row)
        raw_sha = _sha256(raw.encode("utf-8"))
        response_id = f"{run_id}-{row['cik']}-{row['accession']}"
        archive.write((_canonical_line({
            "raw_response_id": response_id, "cik": row["cik"],
            "accession": row["accession"], "raw_response": raw,
            "raw_response_sha256": raw_sha}) + "\n").encode("utf-8"))
        archive.flush()
        os.fsync(archive.fileno())
        # The stored record carries no archive pointer. The record contract is
        # additionalProperties:false and closed at 0.1.0, and adding a field to
        # a released contract to make a bookkeeping check convenient would be
        # exactly the wrong trade. The archive is bound to the records by
        # position and identity instead, which the reconciliation proves.
        records.append(pre.route.build_record(
            row=row, packet=packet,
            prompt_sha256=_sha256(rendered.encode("utf-8")),
            model_route=dict(adapter.model_route), raw=raw,
            validator=axes_validator))
    archive.flush()
    os.fsync(archive.fileno())
    archive.close()

    validator = Draft202012Validator(
        _load_schema(root, pre.route.record_schema), format_checker=FormatChecker())
    for record in records:
        errors = sorted(validator.iter_errors(record), key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Built pilot record violates {pre.route.record_contract} at "
                f"{errors[0].json_path}: {errors[0].message}")
    return _pilot_settle(
        root=root, pre=pre, run_dir=run_dir, run_id=run_id,
        authorization_sha256=authorization_sha256, clock=clock, records=records,
        ledger=ledger, budget=budget, archive_path=archive_path, result=result,
        counters=(called_rows, count_attempts, generate_attempts,
                  rows_count_retried, rows_generate_retried))


def _tally(rows: list[dict], key: Callable[[dict], object]) -> dict[str, int]:
    """Count by a key, omitting values that did not occur.

    An absent value is absent rather than zero, so a reader cannot mistake a
    category the run never produced for one it produced none of by judgement.
    """
    tally: dict[str, int] = {}
    for row in rows:
        value = key(row)
        if value is None:
            continue
        tally[str(value)] = tally.get(str(value), 0) + 1
    return tally


def _manifest_selection_source(pre: _PilotPreflight) -> dict:
    """Return the route-specific provenance shape the manifest contract names."""
    common = {
        "selection_artifact_path": pre.selection_path,
        "selection_artifact_sha256": pre.selection_sha256,
        "selection_id": pre.selection["selection_id"],
        "selection_kind": pre.selection["selection_kind"],
        "selected_rows": len(pre.selection["rows"]),
    }
    if pre.route.selection_source == "calibration":
        return {
            **common,
            "source_selection_path": pre.selection["source_selection_path"],
            "source_selection_sha256": pre.selection["source_selection_sha256"],
        }
    assert pre.coverage_digests is not None
    return {
        **common,
        "coverage_cohort_id": pre.coverage_digests["coverage_cohort_id"],
        "coverage_cohort_manifest_sha256": pre.coverage_digests["manifest_sha256"],
        "coverage_cohort_records_sha256": pre.coverage_digests["records_jsonl_sha256"],
    }


def _selection_limitation(route: PilotRunRoute) -> str:
    if route.selection_source == "calibration":
        return (
            "The ten are chosen, not sampled, and are a subset of the 40-row "
            "calibration selection. They are a mixed stress set, not an "
            "independent draw, so even their internal proportions carry no "
            "sampling interpretation.")
    return (
        "The ten are chosen, not sampled, from the annual-coverage cohort. "
        "They are a mixed stress set, not an independent draw, so even their "
        "internal proportions carry no sampling interpretation.")


def _pilot_settle(*, root: Path, pre: _PilotPreflight, run_dir: Path, run_id: str,
                  authorization_sha256: str, clock, records: list[dict],
                  ledger: list[dict], budget, archive_path: Path,
                  result: ScreenRunResult, counters) -> ScreenRunResult:
    """Write the ledger, records and manifest once every identity holds."""
    (called_rows, count_attempts, generate_attempts,
     count_retried, generate_retried) = counters
    ledger_bytes = "".join(_canonical_line(e) + "\n" for e in ledger).encode("utf-8")
    records_bytes = "".join(_canonical_line(r) + "\n" for r in records).encode("utf-8")
    try:
        write_bytes_once(run_dir / CAPTURE_LEDGER_FILENAME, ledger_bytes,
                         what="classifier pilot capture ledger")
        write_bytes_once(run_dir / pre.route.records_filename, records_bytes,
                         what="classifier pilot records")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    archive_raw = archive_path.read_bytes()
    archive_entries = [json.loads(line) for line
                       in _decode_utf8(archive_raw,
                                       pre.route.raw_responses_filename).splitlines()
                       if line.strip()]
    classified = [r for r in records if r["record_kind"] == "classified"]
    review = [r for r in records if r["record_kind"] == "review_uncertain"]
    persisted = [e for e in ledger if e["capture_disposition"] == "raw_persisted"]
    capture_ok = all(
        (run_dir / e["raw_reference"]).is_file()
        and _sha256((run_dir / e["raw_reference"]).read_bytes()) == e["raw_sha256"]
        for e in persisted)
    disk_refs = ({str(p.relative_to(run_dir))
                  for p in (run_dir / CAPTURES_DIRNAME).rglob("*") if p.is_file()}
                 if (run_dir / CAPTURES_DIRNAME).exists() else set())

    review_by_reason: dict[str, int] = {}
    for record in review:
        code = record["review_reason_code"]
        review_by_reason[code] = review_by_reason.get(code, 0) + 1
    stratum_by_key = {(r["cik"], r["accession"]): r["pilot_stratum"]
                      for r in pre.selection["rows"]}
    origin_by_key = {(r["cik"], r["accession"]): r["admission_origin"]
                     for r in pre.selection["rows"]}
    evidence_items = sum(len(r["axes"]["evidence"]) for r in classified)

    counts = {
        "selected_rows": len(pre.selection["rows"]),
        "classified": len(classified),
        "review_uncertain": len(review),
        "review_uncertain_by_reason": review_by_reason,
        "by_admission_origin": _tally(
            records, lambda r: origin_by_key[(r["cik"], r["accession"])]),
        "by_pilot_stratum": _tally(
            records, lambda r: stratum_by_key[(r["cik"], r["accession"])]),
        "by_confidence": _tally(classified, lambda r: r["axes"]["confidence"]),
        **{f"by_{axis}": _tally(classified, lambda r, a=axis: r["axes"][a])
           for axis in pre.route.judgement_axes},
        "evidence_items": evidence_items,
        "rows_with_no_evidence": sum(
            not r["axes"]["evidence"] for r in classified),
    }
    request_accounting = {
        "logical_row_cap": pre.authorization["logical_row_cap"],
        "count_attempt_cap": pre.authorization["count_attempt_cap"],
        "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
        "external_request_cap": pre.authorization["budget_max_external_requests"],
        "count_attempts_made": count_attempts,
        "provider_attempts_made": generate_attempts,
        "external_requests_made": len(ledger),
        "rows_count_retried": count_retried,
        "rows_generate_retried": generate_retried,
        "model_called_rows": called_rows,
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
    selected_keys = [(r["cik"], r["accession"]) for r in pre.selection["rows"]]
    reconciliation = {
        "every selected row produced exactly one record": (
            len(records) == len(selected_keys)
            and len({(r["cik"], r["accession"]) for r in records}) == len(records)),
        "records follow the selection's own row order": (
            [(r["cik"], r["accession"]) for r in records] == selected_keys),
        "the run covers exactly the ten named filings": (
            len(records) == PILOT_ROW_CAP),
        "the two record kinds partition the run": (
            len(classified) + len(review) == len(records)),
        "the review breakdown sums to the review population": (
            sum(review_by_reason.values()) == len(review)),
        "every review reason is one of the four non-fatal ones": all(
            r["review_reason_code"] in REVIEW_REASONS for r in review),
        "every review row carries a reason and no axes": all(
            r["review_reason_code"] is not None and r["axes"] is None
            for r in review),
        "every classified row carries axes and no reason": all(
            r["axes"] is not None and r["review_reason_code"] is None
            for r in classified),
        "no record carries a tier of any name": all(
            not ({"tier", "candidate_tier", "tier_rule_trace"} & set(r))
            and not ({"tier", "candidate_tier"} & set(r["axes"] or {}))
            for r in records),
        "every stored evidence field the model never wrote is pipeline-derived":
            all(item["provenance"] == "pipeline_derived"
                for r in classified for item in r["axes"]["evidence"]),
        "every stored evidence block re-derives from its packet": all(
            _evidence_resolves(r, pre.packets) for r in classified),
        "a row citing nothing concluded nothing": all(
            all(r["axes"][axis] == "UNKNOWN" for axis in pre.route.judgement_axes)
            for r in classified if not r["axes"]["evidence"]),
        "the archive holds one line per row": (
            len(archive_entries) == len(records)),
        "every archived response re-hashes": all(
            _sha256(e["raw_response"].encode("utf-8")) == e["raw_response_sha256"]
            for e in archive_entries),
        "the archive and the records name the same filings in the same order": (
            [(r["cik"], r["accession"]) for r in records]
            == [(e["cik"], e["accession"]) for e in archive_entries]),
        "capture files rehash to their ledger lines": capture_ok,
        "no orphan capture file exists": disk_refs == {
            e["raw_reference"] for e in persisted},
        "count and generate sends partition external requests": (
            count_attempts + generate_attempts == len(ledger)),
        "no row exceeded its send ceilings": (
            count_attempts <= pre.authorization["count_attempt_cap"]
            and generate_attempts <= pre.authorization["provider_attempt_cap"]
            and len(ledger) <= pre.authorization["budget_max_external_requests"]),
        "the prompt is the authorized one": (
            pre.prompt_sha256 == pre.authorization["prompt_template_sha256"]),
        "the selection and its sources are the authorized ones": (
            (pre.selection["cohort_manifest_sha256"]
             if pre.route.selection_source == "calibration"
             else pre.selection["candidate_cohort_manifest_sha256"])
            == pre.authorization["cohort_manifest_sha256"]
            and pre.selection["packet_manifest_sha256"]
            == pre.authorization["packet_manifest_sha256"]
            and pre.cohort_digests["manifest_sha256"]
            == pre.authorization["cohort_manifest_sha256"]
            and pre.packet_digests["packet_manifest_sha256"]
            == pre.authorization["packet_manifest_sha256"]
            and (pre.route.selection_source != "annual_coverage" or (
                pre.coverage_digests is not None
                and pre.coverage_digests["manifest_sha256"]
                == pre.authorization["coverage_cohort_manifest_sha256"]
                and pre.coverage_digests["records_jsonl_sha256"]
                == pre.authorization["coverage_cohort_records_sha256"]))),
    }
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            f"Pilot reconciliation failed; no manifest is written. Failed "
            f"identities: {failed}.")

    manifest = {
        "manifest_contract": pre.route.manifest_contract, "run_id": run_id,
        "run_kind": pre.route.run_kind, "run_timestamp": clock().isoformat(),
        "promotable": False, "covers_full_cohort": False,
        "derives_no_tier": True, "settles_no_membership": True,
        "authorization_id": pre.authorization["authorization_id"],
        "authorization_sha256": authorization_sha256,
        "sources": {
            "cohort": dict(pre.cohort_digests),
            **({"coverage": {
                "cohort_id": pre.coverage_digests["coverage_cohort_id"],
                "manifest_sha256": pre.coverage_digests["manifest_sha256"],
                "records_jsonl_sha256": pre.coverage_digests["records_jsonl_sha256"],
            }} if pre.coverage_digests is not None else {}),
            "packet": dict(pre.packet_digests),
            "selection": _manifest_selection_source(pre),
            "sources_unmodified": True},
        "prompt_template_path": pre.route.prompt_path,
        "prompt_template_sha256": pre.prompt_sha256,
        "provider": dict(pre.model_route),
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": pre.contract_digest,
        "screen_adapter_enablement_sha256":
            pre.authorization["screen_adapter_enablement_sha256"],
        "endpoint_allowlist": sorted(pre.endpoints.values()),
        "envelope_text_extraction_rule": ENVELOPE_TEXT_EXTRACTION_RULE,
        "output_contract": pre.route.record_contract,
        "output_axes_contract": pre.route.axes_contract,
        "output_hashes": {
            pre.route.records_filename: _sha256(records_bytes),
            pre.route.raw_responses_filename: _sha256(archive_raw),
            CAPTURE_LEDGER_FILENAME: _sha256(ledger_bytes)},
        "record_order": PILOT_RECORD_ORDER,
        "counts": counts, "request_accounting": request_accounting,
        "reconciliation": reconciliation,
        "schema_versions": {
            "universe_classifier_pilot_axes_record":
                pre.route.axes_contract.rsplit("@", 1)[1],
            "universe_classifier_pilot_record":
                pre.route.record_contract.rsplit("@", 1)[1],
            "universe_classifier_pilot_manifest":
                pre.route.manifest_contract.rsplit("@", 1)[1],
            "universe_classifier_pilot_selection":
                pre.route.selection_contract.rsplit("@", 1)[1],
            "screen_connector": SCREEN_CONNECTOR_V6_ID},
        "limitations": [
            (
                "This run is a pilot over ten named filings. It is structurally "
                "non-promotable, it settles no firm's membership, and nothing "
                "downstream may consume it as a decision."
            ),
            (
                "Ten rows cannot estimate a rate. Every count in this manifest "
                "describes these ten rows and may not be extrapolated to the "
                "candidate cohort or to any other population."
            ),
            _selection_limitation(pre.route),
            (
                "The pilot derives no tier and holds no tier rules. It answers "
                f"{len(pre.route.judgement_axes)} firm-level axes and stops; a tier is a question for a later stage "
                "with more than Item 1 in front of it."
            ),
            (
                "The admission context is carried for audit and reached no prompt. "
                "The model saw Item 1 and nothing else, so these judgements are "
                "neither agreement with nor contradiction of any earlier screen, "
                "overlay decision or classifier run."
            ),
            (
                "A row stored as review_uncertain is a row this pilot concluded "
                "nothing about. Its reason names a defect in one model response, "
                "not a finding about the filing."
            ),
        ],
    }
    _validate(manifest, _load_schema(root, pre.route.manifest_schema),
              "Classifier pilot manifest")
    try:
        write_bytes_once(
            run_dir / pre.route.manifest_filename,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="classifier pilot manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    result.status = "completed"
    result.counts = counts
    result.request_accounting = request_accounting
    result.reconciliation = reconciliation
    result.manifest_path = run_dir / pre.route.manifest_filename
    return result


def _evidence_resolves(record: dict, packets: dict) -> bool:
    """Re-derive one stored row's evidence from its packet alone.

    Packet-only and deterministic: the stored text must be exactly what the
    named block holds, and must hash to the stored digest. No prompt is
    rendered and no reference map is consulted beyond the packet itself, so a
    stored row stays checkable years later without this module's renderer.
    """
    packet = packets.get((record["cik"], record["accession"]))
    if packet is None:
        return False
    bodies = {p["passage_id"]: p for p in packet["passages"]}
    for item in record["axes"]["evidence"]:
        passage = bodies.get(item["passage_id"])
        if passage is None:
            return False
        if (passage["text"] != item["evidence_text"]
                or passage["byte_start"] != item["byte_start"]
                or passage["byte_end"] != item["byte_end"]
                or _sha256(item["evidence_text"].encode("utf-8"))
                != item["text_sha256"]):
            return False
    return True


def require_pilot_run(run_dir: str | Path) -> Path:
    """Refuse any pilot run that is not completed and self-consistent.

    The filename gate is the isolation: a V2.x run holds no
    ``universe_classifier_pilot_v1_manifest.json`` and is refused here before a
    contract is read, exactly as a pilot run is refused by every V2.x loader.
    """
    return _require_pilot_run(run_dir, route=PILOT_V1_ROUTE)


def _require_pilot_run(run_dir: str | Path, *, route: PilotRunRoute) -> Path:
    """Load one completed run for an explicit pilot route only."""
    directory = Path(run_dir)
    if (directory / FAILURE_RECEIPT_FILENAME).exists():
        raise ScreenInputError(
            f"Pilot run {directory} holds a failure receipt; it is "
            "non-authoritative and may not be consumed.")
    manifest_path = directory / route.manifest_filename
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Directory {directory} holds no {route.manifest_filename}; this "
            "loader consumes pilot runs only.")
    manifest = json.loads(_decode_utf8(manifest_path.read_bytes(),
                                       route.manifest_filename))
    if manifest.get("manifest_contract") != route.manifest_contract:
        raise ScreenInputError(
            f"Pilot run {directory} declares "
            f"{manifest.get('manifest_contract')!r}; this loader consumes "
            f"{route.manifest_contract!r} only.")
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file() or _sha256(target.read_bytes()) != recorded:
            raise ScreenInputError(
                f"Pilot run output {filename} is missing or no longer hashes "
                "to its manifest entry.")
    return manifest_path
