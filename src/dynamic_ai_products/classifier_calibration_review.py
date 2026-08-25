"""Put every calibration row in front of a human (ADR-127).

This is the gate between a 40-row calibration and a 4,045-row run, and it is
deliberately the least clever artifact in the pipeline. It reads one completed
calibration run and emits, for **every** selected row, what the classifier
concluded and the evidence it cited, alongside context counts. It nominates the
whole selection, not a subsample: at this size a subsample of a sample would be
a rounding error, and the reason to run 40 rows at all is that 40 rows can be
read.

**It records no score, because it cannot honestly compute one.** There is no
gold set, so nothing here is measured against a truth. Forty rows across nine
strata cannot estimate a rate either — one unusable row in a four-row stratum
is 25%, with an interval spanning most of the unit line. So the contract has no
accuracy, precision, recall, agreement or pass/fail field: not left blank, but
absent, so no later reader can mistake a convenient number for evidence. The
gate is passed by a person recording a decision, under a named protocol, or it
is not passed.

**What it does report** is the material a reader needs: the tier and the rule
that produced it, per stratum; where the axes contradicted the admission the
row entered on; every evidence quote with the passage it cites; and where the
model produced nothing usable, with the reason. Those are questions about the
prompt, the rule config and the contract — the things worth fixing before the
full run, and the things a rate would have hidden.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Callable

from .classifier_calibration_selection import require_calibration_selection
from .lineage_classifier_calibration import (
    CALIBRATION_ROUTE,
    require_classifier_calibration_run,
)
from .lineage_classifier_v2_1 import ClassifierRoute
from .provenance import WriteOnceError, write_bytes_once
from .universe.lineage_screen import (
    ScreenInputError,
    _decode_utf8,
    _load_schema,
    _sha256,
    _validate,
)

__all__ = [
    "REVIEWER_ID",
    "REVIEW_CONTRACT",
    "REVIEW_FILENAME",
    "REVIEW_PROTOCOL_VERSION",
    "build_calibration_review",
]

REVIEW_FILENAME = "universe_classifier_calibration_review.json"
REVIEW_CONTRACT = "universe_classifier_calibration_review@0.1.0"
REVIEW_SCHEMA = "schemas/universe_classifier_calibration_review.schema.json"
REVIEW_KIND = "qualitative_human_reading"

#: The named human gate. Both are consts in the contract: this artifact records
#: who must read and under which protocol, and can name nobody else.
REVIEWER_ID = "hakan_zeki_gulmez"
REVIEW_PROTOCOL_VERSION = "classifier_calibration_review_v1"

GATE_STATE = "pending_human_reading"


def _tally(pairs) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in pairs:
        if key is not None:
            out[key] = out.get(key, 0) + 1
    return out


def build_calibration_review(
    *, repo_root: str | Path, calibration_run_dir: str | Path,
    selection_path: str | Path, selection_sha256: str,
    output_path: str | Path, review_id: str,
    clock: Callable[[], datetime], dry_run: bool = False,
    calibration_route: ClassifierRoute = CALIBRATION_ROUTE,
) -> dict:
    """Derive one review artifact from a completed calibration. No model call.

    ``calibration_route`` names which calibration version this run is. The
    review contract itself is version-neutral — it binds the source manifest
    and prompt digests rather than naming a prompt — so the same builder reads
    a V2.1, V2.2, V2.3 or V2.4 run; only the filenames it opens differ. The
    route is also the whole of the version gate here: it reaches the run only
    through ``require_classifier_calibration_run``, which refuses a manifest
    filename or contract belonging to any other version.
    """
    root = Path(repo_root)
    run_dir = Path(calibration_run_dir)
    manifest_path = require_classifier_calibration_run(run_dir,
                                                       route=calibration_route)
    manifest = json.loads(_decode_utf8(manifest_path.read_bytes(),
                                       calibration_route.manifest_filename))
    selection = require_calibration_selection(selection_path,
                                              expected_sha256=selection_sha256)
    bound = manifest["calibration_selection"]
    if bound["selection_sha256"] != selection_sha256:
        raise ScreenInputError(
            "The calibration run classified a different selection than the one "
            "handed to this review."
        )
    if bound["selection_id"] != selection["selection_id"]:
        raise ScreenInputError("The selection ids disagree.")

    records_name = calibration_route.records_filename
    records_raw = (run_dir / records_name).read_bytes()
    if _sha256(records_raw) != manifest["output_hashes"][records_name]:
        raise ScreenInputError(
            f"The calibration records {records_name} no longer hash to the "
            "manifest entry."
        )
    records = [json.loads(x) for x
               in _decode_utf8(records_raw, records_name).splitlines()
               if x.strip()]
    stratum_by_key = {(r["cik"], r["accession"]): r["stratum"]
                      for r in selection["rows"]}
    if {(r["cik"], r["accession"]) for r in records} != set(stratum_by_key):
        raise ScreenInputError(
            "The calibration classified a different row set than the selection "
            "names; every selected row must be nominated."
        )

    nominated = []
    for record in records:
        key = (record["cik"], record["accession"])
        axes = record["axes"] or {}
        trace = record["tier_rule_trace"] or {}
        fired = next((e["rule_id"] for e in trace.get("entries", [])
                      if e["result"] == "fired"), None)
        admitted = record["admission_provenance"]["admitted_status"]
        contradicts = (record["record_kind"] == "classified"
                       and axes.get("customer_facing_functional_product") is False)
        nominated.append({
            "cik": record["cik"], "accession": record["accession"],
            "company_id": record["company_id"], "stratum": stratum_by_key[key],
            "admission_origin": record["admission_provenance"]["admission_origin"],
            "admitted_status": admitted, "record_kind": record["record_kind"],
            "tier": record["tier"], "fired_rule_id": fired,
            "software_centrality": axes.get("software_centrality"),
            "firm_structure": axes.get("firm_structure"),
            "commercial_materiality": axes.get("commercial_materiality"),
            "customer_market_orientation": axes.get("customer_market_orientation"),
            "contradicts_admission": bool(contradicts),
            "boundary_flags": list(axes.get("boundary_flags") or []),
            "contradictions": list(axes.get("contradictions") or []),
            "evidence": [dict(item) for item in (axes.get("evidence") or [])],
            "packet_sha256": record["packet_sha256"],
            "failure_reason_code": record["failure_reason_code"]})

    tier_by_stratum: dict[str, dict[str, int]] = {}
    for row in nominated:
        if row["tier"]:
            bucket = tier_by_stratum.setdefault(row["stratum"], {})
            bucket[row["tier"]] = bucket.get(row["tier"], 0) + 1
    review = {
        "review_contract": REVIEW_CONTRACT, "review_kind": REVIEW_KIND,
        "review_id": review_id,
        "calibration_run_id": manifest["run_id"],
        "calibration_manifest_sha256": _sha256(manifest_path.read_bytes()),
        "selection_id": selection["selection_id"],
        "selection_sha256": selection_sha256,
        "prompt_template_sha256": manifest["prompt_template_sha256"],
        "tier_rules_version": manifest["tier_rules_version"],
        "tier_rules_sha256": manifest["tier_rules_sha256"],
        "reviewer_id": REVIEWER_ID,
        "review_protocol_version": REVIEW_PROTOCOL_VERSION,
        "gate_state": GATE_STATE,
        "counts": {
            "nominated_rows": len(nominated),
            "selected_rows": len(selection["rows"]),
            "by_record_kind": _tally(r["record_kind"] for r in nominated),
            "by_stratum": _tally(r["stratum"] for r in nominated),
            "by_tier": _tally(r["tier"] for r in nominated),
            "tier_by_stratum": tier_by_stratum,
            "fired_rule_ids": _tally(r["fired_rule_id"] for r in nominated),
            "contradicts_admission_by_origin": _tally(
                r["admission_origin"] for r in nominated
                if r["contradicts_admission"]),
            "unusable_by_reason": _tally(
                r["failure_reason_code"] for r in nominated
                if r["record_kind"] == "model_output_unusable")},
        "nominated_rows": nominated,
        "no_model_call": True, "promotable": False,
        "run_timestamp": clock().isoformat(),
        "limitations": [
            "Every selected row is nominated for reading; this is not a "
            "subsample and carries no sampling of its own.",
            "No accuracy, precision, recall or agreement figure appears here, "
            "and none can: there is no gold set to score against.",
            "The sample is far too small to estimate a rate. Its counts "
            "describe these rows only and may not be extrapolated to the "
            "cohort, nor used to set the full run's bounded-outcome tolerances.",
            "A contradiction of the admission is reported for reading. It is "
            "not an error: the classifier is instructed to judge the complete "
            "Item 1 packet and to contest the admission where the packet "
            "warrants it.",
            "The gate is passed by a recorded human decision under the named "
            "protocol. This artifact records who must read and reports what "
            "they should read; it decides nothing.",
        ],
    }
    if review["counts"]["nominated_rows"] != review["counts"]["selected_rows"]:
        raise ScreenInputError(
            "The review must nominate every selected row; it nominates "
            f"{review['counts']['nominated_rows']} of "
            f"{review['counts']['selected_rows']}."
        )
    _validate(review, _load_schema(root, REVIEW_SCHEMA), "Calibration review")
    if dry_run:
        return review
    payload = (json.dumps(review, indent=2, sort_keys=True) + "\n").encode("utf-8")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        write_bytes_once(target, payload, what="calibration review")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return review
