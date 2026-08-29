"""The firm-level software-universe pilot: a smaller question, asked separately.

This is not a V2.x successor and shares no contract with that ladder. The V2.x
classifier asks what a firm sells and cites sentence spans for six economic axes;
this asks one firm-level question -- is software economically central -- and cites
whole Item 1 evidence blocks. Keeping it outside the ladder is deliberate: a pilot
that reused V2.x contracts could not be compared against them without arguing about
which change caused which difference.

Three properties are load-bearing and each is enforced here rather than asked for:

**The model never sees the earlier verdict.** ``render_pilot_prompt`` composes the
prompt from Item 1 alone. The selection carries high-recall status, overlay
decisions and admission provenance for audit, and this module never reads them.
Showing the model a prior answer would make the pilot measure agreement.

**The model never writes evidence text.** It returns ``passage_ref`` addresses;
``resolve_evidence_block`` retrieves the exact block text, its offsets and its
digest from the hash-bound packet. There is no quote field to fabricate into.

**An unresolvable reference degrades one row, not the run.** V2.x refuses the row
and can exhaust a tolerance; a pilot exists to find out what happens, so a bad
reference is recorded as ``review_uncertain`` with a reason and the run continues.

The pilot derives no tier. It answers four axes and stops: a tier is a question for
a later stage with more than Item 1 in front of it, and deriving one here would
attach a rule config's authority to a deliberately narrower judgement.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from jsonschema import Draft202012Validator

from .human_review_overlay import passage_refs

__all__ = [
    "PILOT_AXES_CONTRACT",
    "PILOT_AXES_SCHEMA",
    "PILOT_PROMPT_PATH",
    "PILOT_RECORD_CONTRACT",
    "PILOT_RECORD_SCHEMA",
    "PILOT_SELECTION_CONTRACT",
    "PILOT_SELECTION_SCHEMA",
    "PilotAxesFailure",
    "PilotEvidenceBlock",
    "REVIEW_REASONS",
    "build_pilot_record",
    "render_pilot_prompt",
    "resolve_evidence_block",
    "validate_pilot_axes_output",
]

PILOT_PROMPT_PATH = "prompts/discovery/software_universe_classifier_pilot.v1.md"
PILOT_AXES_SCHEMA = "schemas/universe_classifier_pilot_axes_record.v1.schema.json"
PILOT_AXES_CONTRACT = "universe_classifier_pilot_axes_record@0.1.0"
PILOT_RECORD_SCHEMA = "schemas/universe_classifier_pilot_record.v1.schema.json"
PILOT_RECORD_CONTRACT = "universe_classifier_pilot_record@0.1.0"
PILOT_SELECTION_SCHEMA = "schemas/universe_classifier_pilot_selection.v1.schema.json"
PILOT_SELECTION_CONTRACT = "universe_classifier_pilot_selection@0.1.0"

#: The closed set of reasons a pilot row is stored as review_uncertain instead of
#: classified. Every one of them keeps the run going.
REVIEW_REASONS: tuple[str, ...] = (
    "invalid_model_json",
    "pilot_axes_contract_violation",
    "model_emitted_forbidden_field",
    "evidence_reference_unresolvable",
)

#: Fields the model must never emit. ``tier`` and ``candidate_tier`` would claim a
#: derivation that belongs to the rule engine; the rest would claim authorship of
#: text the pipeline retrieves.
FORBIDDEN_MODEL_FIELDS: tuple[str, ...] = (
    "tier", "candidate_tier", "tier_rule_trace", "quote", "evidence_text",
    "resolved_quote", "byte_start", "byte_end", "text_sha256",
    "passage_id", "span_ref",
    "products", "product_list", "capabilities", "tasks",
)


class PilotAxesFailure(Exception):
    """One pilot response could not be used. Never fatal to the run."""

    def __init__(self, reason_code: str, detail: str) -> None:
        super().__init__(detail)
        assert reason_code in REVIEW_REASONS, reason_code
        self.reason_code = reason_code
        self.detail = detail


@dataclass(frozen=True)
class PilotEvidenceBlock:
    """One retrieved Item 1 evidence block. Every field is pipeline-derived.

    ``byte_start`` and ``byte_end`` are the packet's own boundaries into the **raw
    SEC source document**, not offsets into a normalized or re-rendered Item 1.
    They are copied unchanged so a stored row stays checkable against the filing
    itself. ``passage_id`` is the packet's stable identifier for the block, kept
    because ``P001`` is only an ordinal over one packet's blocks.
    """

    passage_id: str
    text: str
    byte_start: int
    byte_end: int
    sha256: str


def render_pilot_prompt(template: str, packet: dict) -> str:
    """Render Item 1 in natural order with its existing P-references.

    No new segmentation is introduced. ``passage_refs`` already assigns P001, P002
    and so on to the packet's heading-derived evidence blocks, and this reuses that
    mapping exactly so a reference means the same thing here as everywhere else.

    The admission context is absent by construction. This function takes a packet
    and nothing else, so there is no argument through which a prior screen result,
    overlay decision or earlier classification could reach the model.
    """
    refs = passage_refs(packet)
    by_id = {p["passage_id"]: p for p in packet["passages"]}
    blocks = []
    for ref in sorted(refs):
        passage = by_id[refs[ref]]
        blocks.append(f"[{ref}]\n{passage['text']}")
    return (f"{template}\n\n## Baseline Item 1\n\n"
            f"CIK: {packet['cik']}\nACCESSION: {packet['accession']}\n"
            f"BASELINE_CUTOFF: {packet['baseline_cutoff']}\n\n" + "\n\n".join(blocks) + "\n")


def resolve_evidence_block(passage_ref: str, packet: dict) -> PilotEvidenceBlock:
    """Retrieve one evidence block from the packet by its reference.

    Deterministic and packet-only: the same reference against the same hash-bound
    packet always yields the same identity, text, offsets and digest. The offsets
    are the packet's own boundaries into the raw SEC source, so a stored row stays
    checkable against the filing without re-rendering anything.
    """
    refs = passage_refs(packet)
    passage_id = refs.get(passage_ref)
    if passage_id is None:
        raise PilotAxesFailure(
            "evidence_reference_unresolvable",
            f"{passage_ref} names no evidence block this packet displays.")
    passage = next((p for p in packet["passages"] if p["passage_id"] == passage_id), None)
    if passage is None:
        raise PilotAxesFailure(
            "evidence_reference_unresolvable",
            f"{passage_ref} maps to {passage_id}, which is absent from the packet.")
    text = passage["text"]
    return PilotEvidenceBlock(
        passage_id=passage_id, text=text,
        byte_start=passage["byte_start"], byte_end=passage["byte_end"],
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest())


def validate_pilot_axes_output(raw: str, packet: dict,
                               validator: Draft202012Validator) -> dict:
    """Parse one pilot response, hold it to its contract, and resolve its blocks.

    Every refusal raises :class:`PilotAxesFailure`, which the caller turns into a
    ``review_uncertain`` row. Nothing here can end a run.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PilotAxesFailure("invalid_model_json",
                               f"Pilot output is not valid JSON: {exc}.") from exc
    if not isinstance(parsed, dict):
        raise PilotAxesFailure(
            "invalid_model_json",
            f"Pilot output is JSON but not an object: {type(parsed).__name__}.")
    for field in FORBIDDEN_MODEL_FIELDS:
        if field in parsed:
            raise PilotAxesFailure(
                "model_emitted_forbidden_field",
                f"Pilot output carries {field!r}. The model returns six axes, a "
                "confidence and evidence-block references; evidence text is "
                "retrieved by the pipeline and no tier is derived here at all.")
    errors = sorted(validator.iter_errors(parsed), key=lambda e: e.json_path)
    if errors:
        raise PilotAxesFailure(
            "pilot_axes_contract_violation",
            f"Pilot output violates {PILOT_AXES_CONTRACT} at "
            f"{errors[0].json_path}: {errors[0].message}")
    resolved = []
    for position, item in enumerate(parsed["evidence"], start=1):
        try:
            block = resolve_evidence_block(item["passage_ref"], packet)
        except PilotAxesFailure as exc:
            raise PilotAxesFailure(exc.reason_code,
                                   f"Evidence {position}: {exc.detail}") from exc
        resolved.append({**item, "passage_id": block.passage_id,
                         "evidence_text": block.text,
                         "byte_start": block.byte_start, "byte_end": block.byte_end,
                         "text_sha256": block.sha256,
                         "provenance": "pipeline_derived"})
    return {**parsed, "evidence": resolved}


def build_pilot_record(*, row: dict, packet: dict, prompt_sha256: str,
                       model_route: dict, raw: str,
                       validator: Draft202012Validator) -> dict:
    """Build one stored pilot row, classified or review_uncertain.

    ``row`` carries admission provenance, and it is copied into the record for
    audit. It is not consulted for any judgement and never reaches the prompt.
    A row is identified by ``(cik, accession)``: one CIK can file more than once,
    and naming a firm by CIK alone would silently merge two filings.

    No tier is derived. The pilot's four axes are the whole of its output.
    """
    base = {
        "record_contract": PILOT_RECORD_CONTRACT,
        "cik": row["cik"], "accession": row["accession"],
        "company_id": row["company_id"], "source_id": row["source_id"],
        "packet_sha256": packet["packet_sha256"],
        "prompt_sha256": prompt_sha256,
        "model_route": dict(model_route),
        "admission_provenance": dict(row.get("admission_provenance") or {}),
    }
    try:
        axes = validate_pilot_axes_output(raw, packet, validator)
    except PilotAxesFailure as exc:
        return {**base, "record_kind": "review_uncertain", "axes": None,
                "review_reason_code": exc.reason_code, "review_detail": exc.detail}
    return {**base, "record_kind": "classified", "axes": axes,
            "review_reason_code": None, "review_detail": None}


#: A deliberate mixed stress set of ten filings, each identified by
#: ``(cik, accession)`` because one issuer can file more than once and a CIK alone
#: would silently merge two filings.
#:
#: The ten are chosen, not sampled, to put the prompt under the kinds of pressure
#: it is most likely to fail on: firms whose software offering is obvious, the
#: services-versus-software boundary, the retail-plus-e-commerce boundary, cases
#: where the only technology in the filing is internal or belongs to a third party,
#: and one clear negative control. A ten-row draw cannot be representative of
#: 4,045, and calling it random would misdescribe it.
#:
#: The immediate purpose is not comparison against any earlier classifier. It is to
#: see whether this prompt produces sensible four-axis firm-level judgements backed
#: by evidence-block references that resolve.
PILOT_ROWS: tuple[tuple[str, str, str], ...] = (
    ("0001838672", "0000950170-22-004082", "P1_obvious_software"),
    ("0001841804", "0000950170-22-001776", "P1_obvious_software"),
    ("0001867072", "0001558370-22-003291", "P2_model_screen_likely"),
    ("0001056285", "0001564590-22-011815", "P2_model_screen_likely"),
    ("0001593936", "0001558370-21-002630", "P2_model_screen_likely"),
    ("0001405528", "0001410578-22-000214", "P3_model_screen_boundary"),
    ("0000082811", "0000082811-22-000069", "P5_economically_ambiguous"),
    ("0001783328", "0000950170-22-003175", "P5_economically_ambiguous"),
    ("0000096021", "0000096021-22-000151", "P5_economically_ambiguous"),
    ("0001623613", "0001623613-20-000011", "P6_clear_negative"),
)


def build_pilot_selection(*, cohort_rows: list[dict], source_selection: dict,
                          source_selection_path: str, source_selection_sha256: str,
                          cohort_manifest_sha256: str, packet_manifest_sha256: str,
                          selection_id: str, run_timestamp: str) -> dict:
    """Assemble the ten-firm pilot selection. Pure; performs no I/O.

    Provenance is copied in so a later audit can ask which admission path produced
    a row. It is copied for the auditor, not for the model: nothing that renders a
    prompt reads these fields.
    """
    by_key = {(r["cik"], r["accession"]): r for r in cohort_rows}
    source_keys = {(r["cik"], r["accession"]) for r in source_selection["rows"]}
    rows = []
    for cik, accession, stratum in PILOT_ROWS:
        key = (cik, accession)
        row = by_key.get(key)
        if row is None:
            raise ValueError(f"{cik}/{accession} is not in the candidate cohort.")
        if key not in source_keys:
            raise ValueError(
                f"{cik}/{accession} is not in the 40-row calibration selection, "
                "which is the pool these ten stress-set filings are drawn from.")
        rows.append({
            "cik": row["cik"], "accession": row["accession"],
            "company_id": row["company_id"], "source_id": row["source_id"],
            "packet_sha256": row["packet_sha256"],
            "pilot_stratum": stratum,
            "admission_origin": row["admission_origin"],
            "screen_status": row["screen_status"],
            "admission_provenance": dict(row["admission_provenance"]),
        })
    strata: dict[str, int] = {}
    origins: dict[str, int] = {}
    statuses: dict[str, int] = {}
    for r in rows:
        strata[r["pilot_stratum"]] = strata.get(r["pilot_stratum"], 0) + 1
        origins[r["admission_origin"]] = origins.get(r["admission_origin"], 0) + 1
        statuses[r["screen_status"]] = statuses.get(r["screen_status"], 0) + 1
    return {
        "selection_contract": PILOT_SELECTION_CONTRACT,
        "selection_id": selection_id,
        "selection_kind": "classifier_pilot_v1",
        "cohort_id": source_selection["cohort_id"],
        "cohort_manifest_sha256": cohort_manifest_sha256,
        "packet_manifest_sha256": packet_manifest_sha256,
        "source_selection_path": source_selection_path,
        "source_selection_sha256": source_selection_sha256,
        "sampling": {"algorithm": "named_pilot_strata@1",
                     "strata": [{"pilot_stratum": k, "selected": v}
                                for k, v in sorted(strata.items())]},
        "rows": rows,
        "counts": {"selected_rows": len(rows), "by_pilot_stratum": strata,
                   "by_admission_origin": origins, "by_screen_status": statuses},
        "no_model_call": True,
        "limitations": [
            "Ten firms cannot estimate a rate. These counts describe these rows only "
            "and may not be extrapolated to the cohort.",
            "The rows are named, not randomly drawn: they are a mixed stress set "
            "spanning obvious software, services/software boundaries, "
            "retail/e-commerce boundaries, internal or third-party technology cases, "
            "and one clear negative control.",
            "This pilot inspects whether the prompt yields sensible four-axis "
            "judgements with resolving evidence references. It is not a comparison "
            "against any earlier classifier and supports no such claim.",
            "The ten are a chosen subset of the 40-row calibration selection and are "
            "not an independent sample of the cohort.",
            "Admission provenance is carried for audit and is never rendered to the "
            "model; the pilot sees Item 1 and nothing else.",
            "This pilot derives no tier and decides no firm's membership; it is not promotable.",
        ],
        "run_timestamp": run_timestamp,
    }
