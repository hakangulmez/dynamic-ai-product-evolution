"""Governed live calibration run over the sampled cohort (ADR-127).

This is the ADR-126 classifier, unchanged in every respect that matters —
identical prompt bytes, identical tier-rule bytes, identical cohort, overlay,
release and packet chain, identical preflight, identical governed loop and
identical reconciliation — run over a seeded stratified sample instead of the
whole cohort. That sameness is the point: what calibration observes is what the
full run would do, and any difference between them would make the exercise
worthless.

**Structurally unconfusable with the full run.** Five separations, none of
which relies on a reader being careful: the grant and manifest are
``promotable: false``; the manifest contract is this route's own, so
``require_classifier_run`` refuses it; the outputs carry their own filenames;
the run lives under its own root; and ``covers_full_cohort`` is a false const
with a row count the preflight proves is strictly below the cohort's.

**Tolerances are stated for this sample and stop there.** The three
bounded-outcome ceilings are authorization parameters with no default, exactly
as in ADR-126. At this sample size they cannot estimate a rate, so the manifest
says in its own limitations that they license no inference about the full run's
tolerance, which remains a separate decision.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from .classifier_calibration_selection import require_calibration_selection
from .classifier_contract_set import V2_1, V2_2, V2_3, V2_4, V2_5
from .lineage_classifier_v2_1 import (
    CLASSIFIER_RAW_RESPONSES_FILENAME,
    ClassifierRoute,
    require_completed_run,
    _execute,
    _preflight,
    render_classifier_prompt,
)
from .universe.lineage_screen import (
    ScreenInputError,
    ScreenRunResult,
    _RUN_ID_RE,
)

__all__ = [
    "CALIBRATION_MANIFEST_CONTRACT",
    "CALIBRATION_MANIFEST_FILENAME",
    "CALIBRATION_RECORDS_FILENAME",
    "CALIBRATION_ROUTE",
    "CALIBRATION_ROUTE_V2_2",
    "CALIBRATION_ROUTE_V2_3",
    "CALIBRATION_ROUTE_V2_4",
    "CALIBRATION_ROUTE_V2_5",
    "require_classifier_calibration_run",
    "run_lineage_classifier_calibration",
]

CALIBRATION_RECORDS_FILENAME = "universe_classifier_calibration_records.jsonl"
CALIBRATION_MANIFEST_FILENAME = "universe_classifier_calibration_manifest.json"
CALIBRATION_MANIFEST_CONTRACT = "universe_classifier_calibration_manifest@0.1.0"
CALIBRATION_MANIFEST_SCHEMA = (
    "schemas/universe_classifier_calibration_manifest.schema.json")
CALIBRATION_AUTHORIZATION_SCHEMA = (
    "schemas/universe_classifier_calibration_authorization.schema.json")
CALIBRATION_RUN_KIND = "classifier_calibration_v2_1"
CALIBRATION_RECORD_ORDER = "calibration_selection_row_order"

#: What this route calls its outputs. Everything else is the base route's.
CALIBRATION_ROUTE = ClassifierRoute(
    run_kind=CALIBRATION_RUN_KIND,
    records_filename=CALIBRATION_RECORDS_FILENAME,
    manifest_filename=CALIBRATION_MANIFEST_FILENAME,
    manifest_contract=CALIBRATION_MANIFEST_CONTRACT,
    manifest_schema=CALIBRATION_MANIFEST_SCHEMA,
    record_order=CALIBRATION_RECORD_ORDER,
    authorization_schema=CALIBRATION_AUTHORIZATION_SCHEMA,
    archive_filename=CLASSIFIER_RAW_RESPONSES_FILENAME,
    contracts=V2_1,
)

#: The ADR-128 successor. The 40-row selection is unchanged and reusable; only
#: the prompt, the axes/record contracts and the output names differ.
CALIBRATION_ROUTE_V2_2 = ClassifierRoute(
    run_kind=CALIBRATION_RUN_KIND,
    records_filename="universe_classifier_v2_2_calibration_records.jsonl",
    manifest_filename="universe_classifier_v2_2_calibration_manifest.json",
    manifest_contract="universe_classifier_calibration_manifest@0.2.0",
    manifest_schema=(
        "schemas/universe_classifier_calibration_manifest.v2.schema.json"),
    record_order=CALIBRATION_RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_calibration_authorization.v2.schema.json"),
    archive_filename="universe_classifier_v2_2_raw_responses.jsonl",
    contracts=V2_2,
)

#: The ADR-129 successor of the calibration route. The 40-row selection is
#: unchanged and reusable across all three versions; only the prompt moved.
CALIBRATION_ROUTE_V2_3 = ClassifierRoute(
    run_kind=CALIBRATION_RUN_KIND,
    records_filename="universe_classifier_v2_3_calibration_records.jsonl",
    manifest_filename="universe_classifier_v2_3_calibration_manifest.json",
    manifest_contract="universe_classifier_calibration_manifest@0.3.0",
    manifest_schema=(
        "schemas/universe_classifier_calibration_manifest.v3.schema.json"),
    record_order=CALIBRATION_RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_calibration_authorization.v3.schema.json"),
    archive_filename="universe_classifier_v2_3_raw_responses.jsonl",
    contracts=V2_3,
)

#: ADR-130. The V2.4 calibration route, forked together with the base and
#: continuation routes so the calibration exercises exactly the prompt and
#: contract set a later full run would use.
CALIBRATION_ROUTE_V2_4 = ClassifierRoute(
    run_kind=CALIBRATION_RUN_KIND,
    records_filename="universe_classifier_v2_4_calibration_records.jsonl",
    manifest_filename="universe_classifier_v2_4_calibration_manifest.json",
    manifest_contract="universe_classifier_calibration_manifest@0.4.0",
    manifest_schema=(
        "schemas/universe_classifier_calibration_manifest.v4.schema.json"),
    record_order=CALIBRATION_RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_calibration_authorization.v4.schema.json"),
    archive_filename="universe_classifier_v2_4_raw_responses.jsonl",
    contracts=V2_4,
)

#: ADR-132. The V2.5 calibration route, forked with base and continuation so the
#: calibration exercises exactly the evidence protocol a later full run would.
#: That property matters more here than at any earlier version: what is being
#: calibrated is no longer a wording change but whether a model can select the
#: right span at all.
CALIBRATION_ROUTE_V2_5 = ClassifierRoute(
    run_kind=CALIBRATION_RUN_KIND,
    records_filename="universe_classifier_v2_5_calibration_records.jsonl",
    manifest_filename="universe_classifier_v2_5_calibration_manifest.json",
    manifest_contract="universe_classifier_calibration_manifest@0.5.0",
    manifest_schema=(
        "schemas/universe_classifier_calibration_manifest.v5.schema.json"),
    record_order=CALIBRATION_RECORD_ORDER,
    authorization_schema=(
        "schemas/universe_classifier_calibration_authorization.v5.schema.json"),
    archive_filename="universe_classifier_v2_5_raw_responses.jsonl",
    contracts=V2_5,
)


def require_classifier_calibration_run(
    run_dir: str | Path, *, route: ClassifierRoute | None = None
) -> Path:
    """Refuse any calibration run that is not completed and self-consistent.

    ``route`` defaults to the V2.1 calibration route, so existing callers are
    unchanged; pass a later route to consume that version's run instead. The
    full-cohort refusal is calibration's own and applies at every version: a
    calibration observes a sample, never a universe.
    """
    directory = Path(run_dir)
    route = route or CALIBRATION_ROUTE
    manifest = require_completed_run(directory, route, what="Calibration run")
    if manifest.get("covers_full_cohort") is not False:
        raise ScreenInputError(
            f"Calibration run {directory} claims full-cohort coverage; a "
            "calibration observes a sample and never a universe."
        )
    return directory / route.manifest_filename

def run_lineage_classifier_calibration(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    overlay_manifest_path: str | Path, release_manifest_path: str | Path,
    packet_manifest_path: str | Path, selection_path: str | Path,
    governance_root: str | Path, authorization_reference: str,
    authorization_sha256: str, output_dir: str | Path, run_id: str,
    clock: Callable[[], datetime], dry_run: bool = False,
    client_factory: Any = None, sleep: Callable[[float], None] | None = None,
    route: ClassifierRoute = CALIBRATION_ROUTE,
) -> ScreenRunResult:
    """Classify one seeded stratified sample under its own governed grant."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError("Invalid run id.")

    def selection_loader(authorization, cohort_rows):
        if str(Path(authorization["selection_artifact_path"])) != \
                str(Path(selection_path)):
            raise ScreenInputError(
                f"The grant names selection "
                f"{authorization['selection_artifact_path']!r}, not "
                f"{str(selection_path)!r}."
            )
        selection = require_calibration_selection(
            selection_path,
            expected_sha256=authorization["selection_artifact_sha256"])
        if selection["selection_kind"] != authorization["selection_kind"]:
            raise ScreenInputError("The grant names a different selection kind.")
        if selection["cohort_manifest_sha256"] != \
                authorization["cohort_manifest_sha256"]:
            raise ScreenInputError(
                "The selection was drawn from a different cohort than the one "
                "this grant binds."
            )
        if selection["cohort_id"] != authorization["cohort_id"]:
            raise ScreenInputError("The selection names a different cohort id.")
        if (selection["strata_rules_version"] != authorization["strata_rules_version"]
                or selection["strata_rules_sha256"]
                != authorization["strata_rules_sha256"]):
            raise ScreenInputError(
                "The selection was drawn under different strata rules than the "
                "grant binds; the sample would not be reproducible."
            )
        if selection["sampling"]["seed"] != authorization["selection_seed"]:
            raise ScreenInputError(
                f"The selection was drawn with seed "
                f"{selection['sampling']['seed']}, but the grant names "
                f"{authorization['selection_seed']}."
            )
        if selection["release_manifest_sha256"] != \
                authorization["release_manifest_sha256"] or \
                selection["overlay_manifest_sha256"] != \
                authorization["overlay_manifest_sha256"]:
            raise ScreenInputError(
                "The selection and the grant do not name the same release and "
                "overlay."
            )
        if authorization["covers_full_cohort"] is not False:
            raise ScreenInputError(
                "A calibration grant may never claim full-cohort coverage."
            )
        if len(selection["rows"]) >= selection["counts"]["cohort_rows"]:
            raise ScreenInputError(
                "The selection is not strictly smaller than its cohort; this is "
                "a full run wearing a calibration label."
            )
        # Map every selected row onto its cohort record, in selection order.
        # The selection names identity; the cohort record carries the admission
        # provenance the renderer needs, and the two must still agree.
        index = {(r["cik"], r["accession"]): r for r in cohort_rows}
        scope: list[dict] = []
        for row in selection["rows"]:
            key = (row["cik"], row["accession"])
            cohort_row = index.get(key)
            if cohort_row is None:
                raise ScreenInputError(
                    f"Selected row {key} is not in the cohort this grant binds.")
            if (cohort_row["screen_status"] != row["screen_status"]
                    or cohort_row["admission_origin"] != row["admission_origin"]
                    or cohort_row["packet_sha256"] != row["packet_sha256"]):
                raise ScreenInputError(
                    f"Selected row {key} no longer matches its cohort record.")
            scope.append(cohort_row)
        if len(scope) >= len(cohort_rows):
            raise ScreenInputError(
                "The scope is not strictly smaller than the cohort; this is a "
                "full run wearing a calibration label.")
        return selection, scope

    pre = _preflight(
        root=root, governance_root=Path(governance_root),
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256,
        cohort_manifest_path=Path(cohort_manifest_path),
        overlay_manifest_path=Path(overlay_manifest_path),
        release_manifest_path=Path(release_manifest_path),
        packet_manifest_path=packet_manifest_path, clock=clock,
        route=route, selection_loader=selection_loader)

    if dry_run:
        for row, packet, admission in pre.plan:
            render_classifier_prompt(pre.prompt_text, packet, admission)
        return ScreenRunResult(
            run_id, None, True, "dry_run", len(pre.plan), 0,
            request_accounting={
                "cohort_rows": len(pre.inputs.rows),
                "selected_rows": len(pre.selection["rows"]),
                "model_called_rows": len(pre.plan),
                "count_attempt_cap": pre.authorization["count_attempt_cap"],
                "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
                "external_request_cap":
                    pre.authorization["budget_max_external_requests"],
            })
    return _execute(root=root, pre=pre, output_dir=output_dir, run_id=run_id,
                    authorization_sha256=authorization_sha256, clock=clock,
                    client_factory=client_factory, sleep=sleep)
