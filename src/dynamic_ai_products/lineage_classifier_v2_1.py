"""Governed live multi-axis classifier over the candidate cohort (ADR-126).

The cohort admits firms two ways. 3,954 rows carry a validated screen result;
91 rows failed screen validation twice and were admitted by a reviewer through
the complete human-review overlay. Both are legitimate admissions and neither
is evidence: this classifier judges every firm against the complete baseline
Item 1 packet, and the admission context is rendered only so the model can see
what an earlier reader concluded — and contradict it.

**The renderer never invents provenance.** A ``model_screen`` row hydrates the
screen response the cohort record names, by id and digest, from SCREEN_v1's own
archive. A ``human_review`` row hydrates the matching decision from the
hash-bound overlay, because the cohort record carries only reviewer metadata and
an evidence count, not the quote bodies. A missing, duplicate, foreign or
digest-mismatched link on either branch refuses the run before a run directory
exists, before the SDK is imported and before any credential is resolved.

**The model never emits a tier.** It returns axes; a versioned deterministic
engine derives the tier from them and records the full rule trace. The axes
contract has no tier field of any name, so a model that returns one is refused
rather than obeyed, and a prompt revision cannot move tier membership.

**Compactness is a contract term.** The committed ``max_output_tokens`` is
unchanged, so the axes schema bounds every array and string — at most 4
archetypes, 5 dependencies, 6 evidence objects, a 300-character quote, a
200-character claim. A response that overflows those bounds is a validation
failure, not a silent truncation of meaning.

**Bounded outcomes are authorized, never assumed.** Provider-unresolved
(ADR-121) and truncated-output (ADR-122) are carried forward as mechanisms, and
model output that fails validation is a third. All three tolerances are
authorization parameters with no default in this module: each grant states its
own numbers, so no threshold enters the pipeline unexamined.
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
from dynamic_ai_products.classifier_span_index import (
    SpanIndexError,
    SpanSelectionError,
    build_span_index,
    load_span_index_rules,
    render_passage_units,
    resolve_span,
    verify_stored_span,
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
from dynamic_ai_products.provenance import WriteOnceError, write_bytes_once

from .classifier_contract_set import (
    V2_1,
    V2_2,
    V2_3,
    V2_4,
    V2_5,
    V2_6,
    V2_7,
    ClassifierContractSet,
)
from .classifier_tier_engine import derive_tier, load_tier_rules
from .classifier_candidate_cohort import (
    COHORT_MANIFEST_FILENAME,
    COHORT_RECORDS_FILENAME,
    require_classifier_candidate_cohort,
)
from .human_review_overlay import (
    OVERLAY_DECISIONS_FILENAME,
    OVERLAY_MANIFEST_FILENAME,
    passage_refs,
    require_human_review_overlay,
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
from .lineage_screen_release import (
    RELEASE_MANIFEST_FILENAME,
    RELEASE_RECORDS_FILENAME,
    require_screen_release,
)
from .universe.freeze import create_run_directory
from .universe.lineage_screen import (
    FAILURE_RECEIPT_FILENAME,
    ScreenInputError,
    ScreenProviderTerminalError,
    ScreenRunResult,
    _canonical_line,
    _decode_utf8,
    _load_schema,
    _RUN_ID_RE,
    _sha256,
    _validate,
    load_packet_run,
)

__all__ = [
    "CLASSIFIER_MANIFEST_FILENAME",
    "CLASSIFIER_RECORDS_FILENAME",
    "CLASSIFIER_RAW_RESPONSES_FILENAME",
    "load_cohort_inputs",
    "render_classifier_prompt",
    "model_called_provenance",
    "BASE_ROUTE",
    "BASE_ROUTE_V2_2",
    "BASE_ROUTE_V2_3",
    "BASE_ROUTE_V2_4",
    "BASE_ROUTE_V2_5",
    "BASE_ROUTE_V2_6",
    "BASE_ROUTE_V2_7",
    "ClassifierRoute",
    "require_classifier_run",
    "require_completed_run",
    "run_lineage_classifier",
    "validate_axes_output",
]

CLASSIFIER_RECORDS_FILENAME = "universe_classifier_records.jsonl"
CLASSIFIER_MANIFEST_FILENAME = "universe_classifier_manifest.json"
CLASSIFIER_RAW_RESPONSES_FILENAME = "universe_classifier_raw_responses.jsonl"

AUTHORIZATION_CONTRACT = "universe_classifier_authorization@0.1.0"
MANIFEST_CONTRACT = "universe_classifier_manifest@0.1.0"
RECORD_CONTRACT = "universe_classifier_record@0.1.0"
AXES_CONTRACT = "universe_classifier_axes_record@0.1.0"
RUN_KIND = "classifier_v2_1"
RECORD_ORDER = "cohort_row_order"
RECEIPT_CONTRACT = "universe_screen_failure_receipt@0.1.0"

AUTHORIZATION_SCHEMA = "schemas/universe_classifier_authorization.schema.json"
MANIFEST_SCHEMA = "schemas/universe_classifier_manifest.schema.json"
RECORD_SCHEMA = "schemas/universe_classifier_record.schema.json"
AXES_SCHEMA = "schemas/universe_classifier_axes_record.schema.json"

PROMPT_PATH = "prompts/discovery/universe_full_classification.v2_1.md"
TAXONOMY_VERSION = "universe_classifier_axes_v2_1"

@dataclass(frozen=True)
class ClassifierRoute:
    """What one classifier route calls its outputs, and which contract governs.

    Three routes now share this module's preflight, governed loop and
    reconciliation: the base run, its continuation, and the ADR-127 calibration.
    They differ in what they name their outputs and which manifest contract
    describes them, and in nothing else. Making that difference one explicit
    value keeps the reconciliation block single: a copied ``_settle`` is exactly
    where two routes would silently drift apart.
    """

    run_kind: str
    records_filename: str
    manifest_filename: str
    manifest_contract: str
    manifest_schema: str
    record_order: str
    authorization_schema: str
    archive_filename: str
    contracts: ClassifierContractSet


BASE_ROUTE = ClassifierRoute(
    run_kind=RUN_KIND,
    records_filename=CLASSIFIER_RECORDS_FILENAME,
    manifest_filename=CLASSIFIER_MANIFEST_FILENAME,
    manifest_contract=MANIFEST_CONTRACT,
    manifest_schema=MANIFEST_SCHEMA,
    record_order=RECORD_ORDER,
    authorization_schema=AUTHORIZATION_SCHEMA,
    archive_filename=CLASSIFIER_RAW_RESPONSES_FILENAME,
    contracts=V2_1,
)

#: The ADR-128 successor of the base route. Identical logic; wider output
#: bounds, its own contracts, and its own filenames so no loader can confuse
#: the two.
BASE_ROUTE_V2_2 = ClassifierRoute(
    run_kind=RUN_KIND,
    records_filename="universe_classifier_v2_2_records.jsonl",
    manifest_filename="universe_classifier_v2_2_manifest.json",
    manifest_contract="universe_classifier_manifest@0.2.0",
    manifest_schema="schemas/universe_classifier_manifest.v2.schema.json",
    record_order=RECORD_ORDER,
    authorization_schema="schemas/universe_classifier_authorization.v2.schema.json",
    archive_filename="universe_classifier_v2_2_raw_responses.jsonl",
    contracts=V2_2,
)

#: The ADR-129 successor. Same contracts as V2.2 in every respect the schema
#: governs; a different prompt, and therefore its own grant, manifest and
#: filenames.
BASE_ROUTE_V2_3 = ClassifierRoute(
    run_kind=RUN_KIND,
    records_filename="universe_classifier_v2_3_records.jsonl",
    manifest_filename="universe_classifier_v2_3_manifest.json",
    manifest_contract="universe_classifier_manifest@0.3.0",
    manifest_schema="schemas/universe_classifier_manifest.v3.schema.json",
    record_order=RECORD_ORDER,
    authorization_schema="schemas/universe_classifier_authorization.v3.schema.json",
    archive_filename="universe_classifier_v2_3_raw_responses.jsonl",
    contracts=V2_3,
)

#: ADR-130. The V2.4 base route. Its filenames carry the ``v2_4`` prefix and its
#: manifest and authorization contracts are 0.4.0, so a V2.1, V2.2 or V2.3 run
#: is refused here on its manifest filename before its contract is read, and a
#: V2.4 run is refused by each earlier loader the same way. That filename gate
#: matters more than usual for this version: the 0.3.0 axes contract is a
#: widening of 0.2.0, so a V2.3 output would satisfy the V2.4 axes schema and
#: schema validity alone could not tell the two apart.
BASE_ROUTE_V2_4 = ClassifierRoute(
    run_kind=RUN_KIND,
    records_filename="universe_classifier_v2_4_records.jsonl",
    manifest_filename="universe_classifier_v2_4_manifest.json",
    manifest_contract="universe_classifier_manifest@0.4.0",
    manifest_schema="schemas/universe_classifier_manifest.v4.schema.json",
    record_order=RECORD_ORDER,
    authorization_schema="schemas/universe_classifier_authorization.v4.schema.json",
    archive_filename="universe_classifier_v2_4_raw_responses.jsonl",
    contracts=V2_4,
)

#: ADR-132. The V2.5 base route. Its contract set declares ``selected_span``,
#: which is what makes the runner render a span menu and resolve identifiers
#: instead of resolving typed quotes. Unlike the V2.3-to-V2.4 boundary, the
#: contracts alone already reject each other: a V2.4 response carries ``quote``
#: and fails the 0.4.0 axes schema as an unknown property, and a V2.5 response
#: carries ``span_ref`` and fails 0.3.0's the same way. The filenames still gate
#: archives and manifests, which is what keeps a V2.4 archive unreadable here.
BASE_ROUTE_V2_5 = ClassifierRoute(
    run_kind=RUN_KIND,
    records_filename="universe_classifier_v2_5_records.jsonl",
    manifest_filename="universe_classifier_v2_5_manifest.json",
    manifest_contract="universe_classifier_manifest@0.5.0",
    manifest_schema="schemas/universe_classifier_manifest.v5.schema.json",
    record_order=RECORD_ORDER,
    authorization_schema="schemas/universe_classifier_authorization.v5.schema.json",
    archive_filename="universe_classifier_v2_5_raw_responses.jsonl",
    contracts=V2_5,
)

#: ADR-133. The V2.6 base route. Its contract set is V2_5's in everything the
#: model touches; what differs is the manifest and authorization contracts,
#: whose ``request_accounting`` admits a null ``tokens_out_reported`` after a
#: retry. The filenames still separate the two versions' archives and manifests,
#: which is what keeps a V2.5 run unreadable here and a V2.6 run unreadable
#: there.
BASE_ROUTE_V2_6 = ClassifierRoute(
    run_kind=RUN_KIND,
    records_filename="universe_classifier_v2_6_records.jsonl",
    manifest_filename="universe_classifier_v2_6_manifest.json",
    manifest_contract="universe_classifier_manifest@0.6.0",
    manifest_schema="schemas/universe_classifier_manifest.v6.schema.json",
    record_order=RECORD_ORDER,
    authorization_schema="schemas/universe_classifier_authorization.v6.schema.json",
    archive_filename="universe_classifier_v2_6_raw_responses.jsonl",
    contracts=V2_6,
)

#: ADR-134. The V2.7 successor: same route mechanics, same span protocol,
#: a prompt that states the two output rules the V2.6 calibration showed the
#: model breaking. Distinct filenames and a V7 contract keep the two runs
#: structurally unmixable.
BASE_ROUTE_V2_7 = ClassifierRoute(
    run_kind=RUN_KIND,
    records_filename="universe_classifier_v2_7_records.jsonl",
    manifest_filename="universe_classifier_v2_7_manifest.json",
    manifest_contract="universe_classifier_manifest@0.7.0",
    manifest_schema="schemas/universe_classifier_manifest.v7.schema.json",
    record_order=RECORD_ORDER,
    authorization_schema="schemas/universe_classifier_authorization.v7.schema.json",
    archive_filename="universe_classifier_v2_7_raw_responses.jsonl",
    contracts=V2_7,
)

#: The closed provider reasons a bounded provider-unresolved row may carry,
#: identical to ADR-121's set. Never widened here.
PROVIDER_UNRESOLVED_REASONS: tuple[str, ...] = (
    "vertex_quota_exhausted", "vertex_unavailable", "provider_timeout",
    "provider_response_unusable",
)
TRUNCATED_REASON = "max_tokens"
TRUNCATED_FINISH_REASON = "MAX_TOKENS"

#: Placeholders the committed prompt exposes. The prompt is the source of
#: truth: the renderer substitutes, it never re-authors the instructions.
_PLACEHOLDERS = (
    "{{baseline_cutoff}}",
    "{{company_metadata}}",
    "{{model_screen | human_review}}",
    "{{LIKELY_ELIGIBLE | BOUNDARY_OR_UNCERTAIN}}",
    "{{origin_specific_rendered_context}}",
    "{{all_rendered_item_1_passages_with_P_refs}}",
)

_DETAIL_LIMIT = 400


def _detail(text: str) -> str:
    return text if len(text) <= _DETAIL_LIMIT else text[:_DETAIL_LIMIT - 1] + "…"


# --- rendering ----------------------------------------------------------------------


def render_classifier_prompt(template: str, packet: dict, admission: dict,
                             *, span_index=None) -> tuple[str, dict[str, str]]:
    """Render one request: admission context plus the complete Item 1 packet.

    The model sees no path, digest, raw-response id, overlay id, reviewer id or
    repository content — only a natural-language admission summary and the
    displayed passages. Returns the rendered prompt and the ``Pnnn`` mapping the
    response is resolved against.

    ``span_index`` is ADR-132 and is ``None`` for every ``model_quote`` version,
    which renders exactly as it always has — byte for byte, so a V2.1 to V2.4
    prompt digest cannot move. When a ``selected_span`` route supplies an index,
    each passage is rendered as its numbered units instead of as one block. The
    source text still appears exactly once: the markers sit between units the
    segmenter derived from that same text, and the span module refuses any
    segmentation whose units do not rejoin to the normalized passage.
    """
    for token in _PLACEHOLDERS:
        if token not in template:
            raise ScreenInputError(
                f"The classifier prompt is missing placeholder {token!r}; the "
                "committed template and this renderer have diverged."
            )
    refs = passage_refs(packet)
    if span_index is None:
        displayed = "\n\n".join(
            f"[passage_ref={ref} section={passage['section']}]\n{passage['text']}"
            for ref, passage in zip(sorted(refs), packet["passages"]))
    else:
        displayed = "\n\n".join(
            f"[passage_ref={ref} section={passage['section']}]\n"
            f"{render_passage_units(span_index.passages[ref])}"
            for ref, passage in zip(sorted(refs), packet["passages"]))
    metadata = (f"cik: {packet['cik']}\n"
                f"accession: {packet['accession']}\n"
                f"form: {packet['form']}\n"
                f"filing_date: {packet['baseline_filing_date']}")
    lines = []
    if admission["admission_origin"] == "model_screen":
        lines.append("Earlier screen context:")
    else:
        lines.append("Earlier human-review context:")
    for item in admission["context_evidence"]:
        lines.append(f'- {item["passage_ref"]}: "{item["quote"]}"')
    if not admission["context_evidence"]:
        lines.append("- (no displayed evidence was recorded for this admission)")
    rendered = template
    for token, value in zip(_PLACEHOLDERS, (
        packet["baseline_cutoff"], metadata, admission["admission_origin"],
        admission["admitted_status"], "\n".join(lines), displayed,
    )):
        rendered = rendered.replace(token, value)
    return rendered, refs


# --- inputs -------------------------------------------------------------------------


@dataclass
class CohortInputs:
    cohort: dict
    cohort_digests: dict
    rows: list[dict]
    overlay: dict
    overlay_digests: dict
    decisions: dict
    release: dict
    release_digests: dict
    release_rows: dict


def _pin(path: Path, expected: str, *, filename: str, what: str) -> tuple[dict, str]:
    if path.name != filename:
        raise ScreenInputError(
            f"The {what} manifest must be {filename}; {path.name} is a different "
            "artifact."
        )
    if not path.is_file():
        raise ScreenInputError(f"{what} manifest not found: {path}")
    raw = path.read_bytes()
    observed = _sha256(raw)
    if observed != expected:
        raise ScreenInputError(
            f"The {what} manifest hashes to {observed}, but {expected} was "
            "pinned; this is not the artifact that was authorized."
        )
    return json.loads(_decode_utf8(raw, filename)), observed


def _read_pinned(directory: Path, filename: str, recorded: str) -> bytes:
    path = directory / filename
    if not path.is_file():
        raise ScreenInputError(f"Pinned input not found: {path}")
    raw = path.read_bytes()
    if _sha256(raw) != recorded:
        raise ScreenInputError(
            f"{filename} no longer hashes to the digest its manifest records; "
            "nothing may be read from it."
        )
    return raw


def _index(raw: bytes, filename: str, what: str) -> dict[tuple[str, str], dict]:
    index: dict[tuple[str, str], dict] = {}
    for line in _decode_utf8(raw, filename).splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        key = (record["cik"], record["accession"])
        if key in index:
            raise ScreenInputError(
                f"The {what} carries {key} twice; admission provenance would be "
                "ambiguous."
            )
        index[key] = record
    return index


def load_cohort_inputs(
    root: Path, *, cohort_manifest_path: Path, cohort_manifest_sha256: str,
    overlay_manifest_path: Path, overlay_manifest_sha256: str,
    release_manifest_path: Path, release_manifest_sha256: str,
) -> CohortInputs:
    """Hydrate and cross-bind every input before anything is written.

    The three manifests are the whole input surface. Screen evidence is read
    from the release's own records rather than from a source run directory, so
    the classifier depends on the frozen release and not on the mutable runs
    that produced it; the raw-response id and digest the cohort names are still
    matched against the release row, so the admission chain stays intact.
    """
    cohort, cohort_sha = _pin(cohort_manifest_path, cohort_manifest_sha256,
                              filename=COHORT_MANIFEST_FILENAME, what="cohort")
    require_classifier_candidate_cohort(cohort_manifest_path.parent)
    overlay, overlay_sha = _pin(overlay_manifest_path, overlay_manifest_sha256,
                                filename=OVERLAY_MANIFEST_FILENAME, what="overlay")
    require_human_review_overlay(overlay_manifest_path.parent)
    release, release_sha = _pin(release_manifest_path, release_manifest_sha256,
                                filename=RELEASE_MANIFEST_FILENAME, what="release")
    require_screen_release(release_manifest_path.parent)

    if cohort["sources"]["overlay"]["overlay_id"] != overlay["overlay_id"]:
        raise ScreenInputError(
            f"The cohort was built from overlay "
            f"{cohort['sources']['overlay']['overlay_id']!r}, not "
            f"{overlay['overlay_id']!r}."
        )
    if cohort["sources"]["overlay"]["manifest_sha256"] != overlay_sha:
        raise ScreenInputError("The cohort pins a different overlay manifest digest.")
    if cohort["sources"]["release"]["release_id"] != release["release_id"]:
        raise ScreenInputError(
            f"The cohort was built from release "
            f"{cohort['sources']['release']['release_id']!r}, not "
            f"{release['release_id']!r}."
        )
    if cohort["sources"]["release"]["manifest_sha256"] != release_sha:
        raise ScreenInputError("The cohort pins a different release manifest digest.")
    if overlay["release"]["manifest_sha256"] != release_sha:
        raise ScreenInputError("The overlay reviewed a different release.")

    rows_raw = _read_pinned(cohort_manifest_path.parent, COHORT_RECORDS_FILENAME,
                            cohort["output_hashes"][COHORT_RECORDS_FILENAME])
    rows = [json.loads(x) for x
            in _decode_utf8(rows_raw, COHORT_RECORDS_FILENAME).splitlines() if x.strip()]
    if len(rows) != cohort["counts"]["cohort_rows"]:
        raise ScreenInputError("The cohort's record count disagrees with its manifest.")

    decisions_raw = _read_pinned(overlay_manifest_path.parent,
                                 OVERLAY_DECISIONS_FILENAME,
                                 overlay["output_hashes"][OVERLAY_DECISIONS_FILENAME])
    decisions = _index(decisions_raw, OVERLAY_DECISIONS_FILENAME, "overlay")

    release_raw = _read_pinned(release_manifest_path.parent, RELEASE_RECORDS_FILENAME,
                               release["output_hashes"][RELEASE_RECORDS_FILENAME])
    release_rows = _index(release_raw, RELEASE_RECORDS_FILENAME, "release")
    if _sha256(release_raw) != cohort["sources"]["release"]["records_jsonl_sha256"]:
        raise ScreenInputError(
            "The release records the cohort was built from are not these bytes."
        )
    return CohortInputs(
        cohort=cohort,
        cohort_digests={"cohort_id": cohort["cohort_id"], "manifest_sha256": cohort_sha,
                        "records_jsonl_sha256": _sha256(rows_raw)},
        rows=rows, overlay=overlay,
        overlay_digests={"overlay_id": overlay["overlay_id"],
                         "manifest_sha256": overlay_sha,
                         "decisions_jsonl_sha256": _sha256(decisions_raw)},
        decisions=decisions, release=release,
        release_digests={"release_id": release["release_id"],
                         "manifest_sha256": release_sha,
                         "records_jsonl_sha256": _sha256(release_raw)},
        release_rows=release_rows)


#: Which release-provenance branch is authoritative for each model origin.
_PROVENANCE_BRANCH = {"base_valid": "base", "repaired": "repair"}


def _admission_for(row: dict, inputs: CohortInputs, packet: dict) -> dict:
    """Build one row's admission context, refusing any broken link."""
    key = (row["cik"], row["accession"])
    origin = row["admission_origin"]
    provenance = row["admission_provenance"]
    refs = passage_refs(packet)
    by_id = {passage_id: ref for ref, passage_id in refs.items()}
    bodies = {p["passage_id"]: " ".join(p["text"].split()) for p in packet["passages"]}
    if origin == "model_screen":
        named = provenance.get("model_screen")
        if not named:
            raise ScreenInputError(
                f"Row {key} is a model_screen admission carrying no screen "
                "provenance."
            )
        release_row = inputs.release_rows.get(key)
        if release_row is None:
            raise ScreenInputError(
                f"Row {key} is a model_screen admission but the release holds no "
                "row for it."
            )
        branch = _PROVENANCE_BRANCH.get(release_row["release_origin"])
        if branch is None:
            raise ScreenInputError(
                f"Row {key} was admitted as a model screen but its release row "
                f"carries origin {release_row['release_origin']!r}."
            )
        chain_source = release_row["release_provenance"][branch]
        if (chain_source["raw_response_id"] != named["raw_response_id"]
                or chain_source["raw_response_sha256"] != named["raw_response_sha256"]):
            raise ScreenInputError(
                f"Row {key} names screen response {named['raw_response_id']!r}, "
                "which is not the response the release row records."
            )
        if release_row["record_kind"] != "screened_packet":
            raise ScreenInputError(
                f"Row {key} was admitted from a release row of kind "
                f"{release_row['record_kind']!r}, which carries no screen output."
            )
        if release_row["screen_status"] != row["screen_status"]:
            raise ScreenInputError(
                f"Row {key} was admitted as {row['screen_status']!r} but the "
                f"release row screened {release_row['screen_status']!r}."
            )
        context = []
        output = release_row["screen_output"]
        for field in ("positive_evidence", "negative_or_boundary_evidence"):
            for item in output.get(field) or []:
                ref = by_id.get(item["passage_id"])
                if ref is None or " ".join(item["quote"].split()) \
                        not in bodies[item["passage_id"]]:
                    raise ScreenInputError(
                        f"Row {key}'s screen evidence does not resolve in the "
                        "packet passage it cites."
                    )
                context.append({"passage_ref": ref, "quote": item["quote"]})
        chain = {"model_screen": {"release_id": inputs.release["release_id"],
                                  "release_origin": release_row["release_origin"],
                                  "raw_response_id": named["raw_response_id"],
                                  "raw_response_sha256": named["raw_response_sha256"]},
                 "human_review": None}
    elif origin == "human_review":
        named = provenance.get("human_review")
        if not named:
            raise ScreenInputError(
                f"Row {key} is a human_review admission carrying no reviewer "
                "provenance."
            )
        decision = inputs.decisions.get(key)
        if decision is None:
            raise ScreenInputError(
                f"Row {key} is a human_review admission but the hash-bound "
                "overlay holds no decision for it."
            )
        if decision["decision"] != row["screen_status"]:
            raise ScreenInputError(
                f"Row {key} was admitted as {row['screen_status']!r} but the "
                f"overlay decided {decision['decision']!r}."
            )
        if named["overlay_id"] != inputs.overlay["overlay_id"]:
            raise ScreenInputError(
                f"Row {key} names overlay {named['overlay_id']!r}, not "
                f"{inputs.overlay['overlay_id']!r}."
            )
        if len(decision["evidence"]) != named["evidence_items"]:
            raise ScreenInputError(
                f"Row {key} records {named['evidence_items']} evidence item(s) "
                f"but the overlay decision carries {len(decision['evidence'])}."
            )
        context = []
        for item in decision["evidence"]:
            ref, quote = item["passage_ref"], item["quote"]
            passage_id = refs.get(ref)
            if passage_id is None or " ".join(quote.split()) not in bodies[passage_id]:
                raise ScreenInputError(
                    f"Row {key}'s reviewer evidence does not resolve in the "
                    f"packet passage it cites ({ref})."
                )
            context.append({"passage_ref": ref, "quote": quote})
        chain = {"model_screen": None,
                 "human_review": {"overlay_id": named["overlay_id"],
                                  "reviewer_id": named["reviewer_id"],
                                  "review_protocol_version":
                                      named["review_protocol_version"],
                                  "decision_timestamp": named["decision_timestamp"],
                                  "evidence_items": named["evidence_items"]}}
    else:
        raise ScreenInputError(
            f"Row {key} carries admission origin {origin!r}, which this route "
            "does not know how to render."
        )
    return {"cohort_id": inputs.cohort["cohort_id"], "admission_origin": origin,
            "admitted_status": row["screen_status"], "non_authoritative": True,
            "context_evidence": context, **chain}


# --- output validation ---------------------------------------------------------------


class AxesValidationFailure(Exception):
    def __init__(self, reason_code: str, detail: str):
        super().__init__(detail)
        self.reason_code = reason_code
        self.detail = detail


def validate_axes_output(raw: str, packet: dict, validator: Draft202012Validator,
                         axes_contract: str = AXES_CONTRACT) -> dict:
    """Parse and validate one model response against the axes contract.

    Refuses a tier field of any name, enforces the bounded axes schema, and
    resolves every evidence quote verbatim inside the passage it cites.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AxesValidationFailure("invalid_model_json",
                                    f"Model output is not valid JSON: {exc}.") from exc
    if not isinstance(parsed, dict):
        raise AxesValidationFailure(
            "invalid_model_json",
            f"Model output is JSON but not an object: {type(parsed).__name__}.")
    for forbidden in ("tier", "candidate_tier", "tier_rule_trace"):
        if forbidden in parsed:
            raise AxesValidationFailure(
                "model_emitted_tier",
                f"Model output carries {forbidden!r}. The model returns axes "
                "only; a tier is derived deterministically and a model-supplied "
                "tier is never accepted.")
    errors = sorted(validator.iter_errors(parsed), key=lambda e: e.json_path)
    if errors:
        raise AxesValidationFailure(
            "axes_contract_violation",
            f"Model output violates {axes_contract} at "
            f"{errors[0].json_path}: {errors[0].message}")
    refs = passage_refs(packet)
    bodies = {p["passage_id"]: " ".join(p["text"].split()) for p in packet["passages"]}
    for position, item in enumerate(parsed["evidence"], start=1):
        passage_id = refs.get(item["passage_ref"])
        if passage_id is None:
            raise AxesValidationFailure(
                "quote_resolution_failure",
                f"Evidence {position} cites {item['passage_ref']}, which this "
                "packet does not display.")
        if " ".join(item["quote"].split()) not in bodies[passage_id]:
            raise AxesValidationFailure(
                "quote_resolution_failure",
                f"Evidence {position} does not resolve verbatim inside passage "
                f"{item['passage_ref']}.")
    stated = [parsed[f] for f in ("customer_facing_functional_product",
                                 "economically_eligible", "data_eligible")]
    if (parsed["software_centrality"] != "UNKNOWN" or any(v is not None for v in stated)) \
            and not parsed["evidence"]:
        raise AxesValidationFailure(
            "unsupported_conclusion",
            "The output states a non-unknown conclusion but cites no evidence.")
    return parsed


def validate_span_axes_output(raw: str, packet: dict,
                             validator: Draft202012Validator, axes_contract: str,
                             span_index) -> dict:
    """Parse and validate one V2.5 response, then resolve its spans (ADR-132).

    The model returns identifiers; this function turns them into text. Structure
    is the model's responsibility and relevance is the reviewer's: a span that
    parses, names a displayed passage and resolves in range is accepted even if
    a human would judge it unconvincing. That is deliberate. Refusing a
    well-formed but weak selection would be the pipeline scoring evidence, which
    belongs to the review gate and to no layer here.

    Returns the axes with each evidence item extended by the pipeline's own
    ``resolved_quote``, ``span_start``, ``span_end`` and ``span_sha256``. The
    model wrote none of those four.
    """
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AxesValidationFailure("invalid_model_json",
                                    f"Model output is not valid JSON: {exc}.") from exc
    if not isinstance(parsed, dict):
        raise AxesValidationFailure(
            "invalid_model_json",
            f"Model output is JSON but not an object: {type(parsed).__name__}.")
    for forbidden in ("tier", "candidate_tier", "tier_rule_trace"):
        if forbidden in parsed:
            raise AxesValidationFailure(
                "model_emitted_tier",
                f"Model output carries {forbidden!r}. The model returns axes "
                "only; a tier is derived deterministically and a model-supplied "
                "tier is never accepted.")
    errors = sorted(validator.iter_errors(parsed), key=lambda e: e.json_path)
    if errors:
        raise AxesValidationFailure(
            "axes_contract_violation",
            f"Model output violates {axes_contract} at "
            f"{errors[0].json_path}: {errors[0].message}")
    resolved_evidence = []
    for position, item in enumerate(parsed["evidence"], start=1):
        try:
            resolved = resolve_span(item["span_ref"], item["passage_ref"], span_index)
        except SpanSelectionError as exc:
            raise AxesValidationFailure(
                exc.reason_code, f"Evidence {position}: {exc.detail}") from exc
        resolved_evidence.append({
            **item, "resolved_quote": resolved.text,
            "span_start": resolved.start, "span_end": resolved.end,
            "span_sha256": resolved.sha256})
    stated = [parsed[f] for f in ("customer_facing_functional_product",
                                 "economically_eligible", "data_eligible")]
    if (parsed["software_centrality"] != "UNKNOWN" or any(v is not None for v in stated)) \
            and not parsed["evidence"]:
        raise AxesValidationFailure(
            "unsupported_conclusion",
            "The output states a non-unknown conclusion but cites no evidence.")
    return {**parsed, "evidence": resolved_evidence}


def require_completed_run(directory: Path, route: ClassifierRoute, *,
                          what: str) -> dict:
    """Load and verify one completed run of exactly one route.

    Every classifier loader asks the same four questions — is there a failure
    receipt, is this route's manifest present, does it declare this route's
    contract, and does every output still hash to its manifest entry — and
    differs only in which route's names it asks them about. Asking them once,
    against a route, is what keeps a V2.2 or V2.3 run from being read as a V2.1
    one: the manifest filename and the contract id both have to match, so a
    later version's run is refused on its filename before its contract is even
    read.
    """
    if (directory / FAILURE_RECEIPT_FILENAME).exists():
        raise ScreenInputError(
            f"{what} {directory} holds a failure receipt; it is "
            "non-authoritative and may not be consumed."
        )
    manifest_path = directory / route.manifest_filename
    if not manifest_path.is_file():
        raise ScreenInputError(
            f"Directory {directory} holds no {route.manifest_filename}; this "
            f"loader consumes {route.contracts.version_id} runs only."
        )
    manifest = json.loads(_decode_utf8(manifest_path.read_bytes(),
                                       route.manifest_filename))
    if manifest.get("manifest_contract") != route.manifest_contract:
        raise ScreenInputError(
            f"{what} {directory} declares "
            f"{manifest.get('manifest_contract')!r}; this loader consumes "
            f"{route.manifest_contract!r} only."
        )
    for filename, recorded in manifest["output_hashes"].items():
        target = directory / filename
        if not target.is_file() or _sha256(target.read_bytes()) != recorded:
            raise ScreenInputError(
                f"{what} output {filename} is missing or no longer hashes "
                "to its manifest entry."
            )
    return manifest


def require_classifier_run(run_dir: str | Path, *,
                           route: ClassifierRoute | None = None) -> Path:
    """Refuse any classifier run that is not completed and self-consistent.

    ``route`` defaults to the V2.1 base route, so existing callers are
    unchanged; pass a later route to consume that version's run instead.
    """
    directory = Path(run_dir)
    route = route or BASE_ROUTE
    require_completed_run(directory, route, what="Classifier run")
    return directory / route.manifest_filename


# --- preflight and run ----------------------------------------------------------------


@dataclass
class _Preflight:
    authorization: dict
    enablement: dict
    contract_digest: str
    endpoints: dict
    prompt_text: str
    prompt_sha256: str
    tier_rules: Any
    inputs: CohortInputs
    packets: dict
    plan: list[tuple[dict, dict, dict]]
    model_route: dict
    prefix_records: list[dict]
    source: dict | None
    route: ClassifierRoute
    selection: dict | None
    #: ADR-132. The pinned span-index rules for a ``selected_span`` route, and
    #: ``None`` for every ``model_quote`` route, which has no span index.
    span_rules: object | None = None


def _preflight(
    *, root: Path, governance_root: Path, authorization_reference: str,
    authorization_sha256: str, cohort_manifest_path: Path,
    overlay_manifest_path: Path, release_manifest_path: Path,
    packet_manifest_path: str | Path, clock: Callable[[], datetime],
    route: ClassifierRoute = BASE_ROUTE,
    prefix_loader: Callable[[dict, list[dict], dict], tuple[list[dict], dict]]
    | None = None,
    selection_loader: Callable[[dict, list[dict]], tuple[dict, list[dict]]]
    | None = None,
) -> _Preflight:
    """Everything provable, proven, before any output or network exists."""
    authorization, _ = _hydrate_pinned(
        governance_root, authorization_reference, authorization_sha256,
        "classifier authorization")
    _validate(authorization, _load_schema(root, route.authorization_schema),
              "Classifier authorization")
    enablement, _ = _hydrate_pinned(
        governance_root, authorization["screen_adapter_enablement_reference"],
        authorization["screen_adapter_enablement_sha256"], "screen adapter enablement")
    _validate(enablement, _load_schema(root, ENABLEMENT_SCHEMA_RELATIVE_PATH),
              "Screen adapter enablement")
    now = clock()
    for label, artifact in (("authorization", authorization),
                            ("enablement", enablement)):
        if not (_parse_moment(artifact["effective_at"], f"{label} effective_at")
                <= now < _parse_moment(artifact["expires_at"], f"{label} expires_at")):
            raise ScreenInputError(
                f"The {label} is outside its effective window; nothing runs.")
    span_rules = None
    if route.contracts.evidence_protocol == "selected_span":
        try:
            span_rules = load_span_index_rules(root)
        except SpanIndexError as exc:
            raise ScreenInputError(f"Span index unusable: {exc}") from exc
        if authorization.get("span_index_version") != span_rules.version:
            raise ScreenInputError(
                f"The grant authorizes span index "
                f"{authorization.get('span_index_version')!r}, but the committed "
                f"config is {span_rules.version!r}.")
        if authorization.get("span_index_sha256") != span_rules.sha256:
            raise ScreenInputError(
                "The grant pins a different span-index digest than the committed "
                "config hashes to; the menu this run would render is not the one "
                "authorized.")
    # A model_quote route needs no symmetric guard here: every earlier
    # authorization schema is additionalProperties:false, so a grant carrying
    # span_index_version is refused by _validate before this point. Asserting it
    # again would be unreachable code pretending to be a safeguard.

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
            "Authorization or enablement binds a different provider client contract.")
    if (authorization["model_route"] != model_route
            or authorization["retry_policy_version"] != RETRY_POLICY_VERSION
            or authorization["rate_limit_policy_version"] != RATE_LIMIT_POLICY_VERSION
            or authorization["screen_generate_retry_policy_version"]
            != SCREEN_GENERATE_RETRY_POLICY_VERSION
            or authorization["screen_count_retry_policy_version"]
            != SCREEN_COUNT_RETRY_POLICY_VERSION
            or authorization["count_attempts_per_row"] != SCREEN_COUNT_MAX_ATTEMPTS_V2
            or authorization["generate_attempts_per_row"] != SCREEN_GENERATE_MAX_ATTEMPTS
            or authorization["external_requests_per_row"]
            != SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2
            or authorization["output_contract"] != route.contracts.record_contract
            or authorization["taxonomy_version"]
            != route.contracts.taxonomy_version):
        raise ScreenInputError(
            "Authorization route, policy versions, ceilings or contracts do not "
            "match the committed ones.")
    if authorization["promotable"] is not False:
        raise ScreenInputError("A classifier grant may never be promotable.")
    endpoints = build_operation_endpoints(
        vertex_project=authorization["vertex_project"],
        vertex_location=authorization["vertex_location"])
    if set(authorization["endpoint_allowlist"]) != set(endpoints.values()) or \
            set(enablement["endpoint_allowlist"]) != set(endpoints.values()):
        raise ScreenInputError(
            "Authorization/enablement endpoint allowlists are not exactly the "
            "derived operation endpoints.")
    if authorization["prompt_template_path"] != route.contracts.prompt_path:
        raise ScreenInputError(
            f"The grant binds prompt {authorization['prompt_template_path']!r}; "
            f"this route runs {route.contracts.prompt_path!r} only.")
    prompt_raw = (root / route.contracts.prompt_path).read_bytes()
    prompt_sha = _sha256(prompt_raw)
    if prompt_sha != authorization["prompt_template_sha256"]:
        raise ScreenInputError(
            f"Authorization does not bind the committed "
            f"{route.contracts.version_id} classifier prompt bytes.")
    tier_rules = load_tier_rules(root)
    if (authorization["tier_rules_version"] != tier_rules.version
            or authorization["tier_rules_sha256"] != tier_rules.sha256):
        raise ScreenInputError(
            "Authorization does not bind the committed tier-rule config; a tier "
            "derived under other rules would not be reproducible.")
    inputs = load_cohort_inputs(
        root, cohort_manifest_path=cohort_manifest_path,
        cohort_manifest_sha256=authorization["cohort_manifest_sha256"],
        overlay_manifest_path=overlay_manifest_path,
        overlay_manifest_sha256=authorization["overlay_manifest_sha256"],
        release_manifest_path=release_manifest_path,
        release_manifest_sha256=authorization["release_manifest_sha256"])
    if inputs.cohort["cohort_id"] != authorization["cohort_id"]:
        raise ScreenInputError("Authorization names a different cohort.")
    packet_inputs = load_packet_run(root, packet_manifest_path)
    if packet_inputs.manifest_sha256 != authorization["packet_manifest_sha256"]:
        raise ScreenInputError("Authorization binds a different packet cohort.")
    packets = {(p["cik"], p["accession"]): p for p in packet_inputs.packets}

    selection: dict | None = None
    scope: list[dict] = inputs.rows
    if selection_loader is not None:
        # The loader returns cohort records in selection order: the renderer
        # reads a cohort row, and a selection row carries identity only.
        selection, scope = selection_loader(authorization, inputs.rows)

    prefix_records: list[dict] = []
    source: dict | None = None
    if prefix_loader is not None:
        prefix_records, source = prefix_loader(
            authorization, inputs, packets,
            _decode_utf8(prompt_raw, "classifier prompt"), tier_rules, model_route,
            span_rules)

    plan: list[tuple[dict, dict, dict]] = []
    for row in scope[len(prefix_records):]:
        key = (row["cik"], row["accession"])
        packet = packets.get(key)
        if packet is None:
            raise ScreenInputError(
                f"Cohort row {key} is absent from the packet cohort.")
        if packet["packet_sha256"] != row["packet_sha256"]:
            raise ScreenInputError(
                f"Cohort row {key} no longer matches its recorded packet digest.")
        plan.append((row, packet, _admission_for(row, inputs, packet)))
    if not plan:
        raise ScreenInputError(
            "Every cohort row is already covered by the reused prefix; there is "
            "nothing to continue.")
    called = len(plan)
    if source is not None:
        inherited = sum(r["record_kind"] == "model_output_unusable"
                        for r in prefix_records)
        if inherited > authorization["max_model_output_unusable"]:
            raise ScreenInputError(
                f"The reused prefix alone revalidates to {inherited} unusable "
                f"row(s), above the authorized "
                f"{authorization['max_model_output_unusable']}; this run cannot "
                "succeed and is refused before it starts.")
        if authorization["reused_prefix_row_cap"] != len(prefix_records):
            raise ScreenInputError(
                f"The grant authorizes {authorization['reused_prefix_row_cap']} "
                f"reused row(s) but the source prefix rebuilds "
                f"{len(prefix_records)}.")
        if authorization["model_called_row_cap"] != called:
            raise ScreenInputError(
                f"The grant authorizes {authorization['model_called_row_cap']} "
                f"model-called row(s) but {called} remain.")
    # A calibration run is scoped by its selection; every other route covers
    # the whole cohort. Either way the cap is the scope, never a literal.
    if authorization["logical_row_cap"] != len(scope):
        raise ScreenInputError(
            f"The grant authorizes {authorization['logical_row_cap']} row(s) "
            f"but this route's scope holds {len(scope)}.")
    if authorization["count_attempt_cap"] != screen_count_attempt_cap(called):
        raise ScreenInputError(
            f"count_attempt_cap must be exactly {screen_count_attempt_cap(called)}.")
    if authorization["provider_attempt_cap"] != screen_generate_attempt_cap(called):
        raise ScreenInputError(
            f"provider_attempt_cap must be exactly "
            f"{screen_generate_attempt_cap(called)}.")
    if authorization["budget_max_external_requests"] != \
            screen_external_request_cap_v2(called):
        raise ScreenInputError(
            f"budget_max_external_requests must be exactly "
            f"{screen_external_request_cap_v2(called)}.")
    return _Preflight(
        authorization=authorization, enablement=enablement, contract_digest=digest,
        endpoints=endpoints, prompt_text=_decode_utf8(prompt_raw, "classifier prompt"),
        prompt_sha256=prompt_sha, tier_rules=tier_rules, inputs=inputs,
        packets=packets, plan=plan, model_route=model_route, span_rules=span_rules,
        prefix_records=prefix_records, source=source, route=route,
        selection=selection)


def model_called_provenance(run_id: str, raw_response_id: str | None,
                            raw_response_sha256: str | None) -> dict:
    """Output provenance for a row this run actually sent."""
    return {"run_id": run_id, "origin": "model_called",
            "raw_response_id": raw_response_id,
            "raw_response_sha256": raw_response_sha256,
            "source_run_id": None, "source_raw_responses_sha256": None,
            "source_receipt_sha256": None}


def _truncated_envelope(raw: bytes) -> dict | None:
    """A single candidate that stopped at the output ceiling, or None."""
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    if (payload.get("promptFeedback") or {}).get("blockReason"):
        return None
    candidates = payload.get("candidates")
    if not isinstance(candidates, list) or len(candidates) != 1:
        return None
    if candidates[0].get("finishReason") != TRUNCATED_FINISH_REASON:
        return None
    usage = payload.get("usageMetadata") or {}
    return {"reason_code": TRUNCATED_REASON,
            "finish_reason": TRUNCATED_FINISH_REASON,
            "candidate_token_count": usage.get("candidatesTokenCount")}


def _classify_truncated(run_dir: Path, spent: list[dict]) -> dict | None:
    generates = [e for e in spent if e["operation_label"] == "generate_content"]
    if not generates:
        return None
    terminal = generates[-1]
    if terminal["capture_disposition"] != "raw_persisted" or \
            not terminal.get("raw_reference"):
        return None
    target = run_dir / terminal["raw_reference"]
    if not target.is_file():
        return None
    raw = target.read_bytes()
    if _sha256(raw) != terminal["raw_sha256"]:
        return None
    envelope = _truncated_envelope(raw)
    if envelope is None:
        return None
    counts = [e for e in spent if e["operation_label"] == "count_tokens"]
    return {**envelope, "capture_reference": terminal["raw_reference"],
            "capture_sha256": terminal["raw_sha256"],
            "count_attempts": len(counts), "generate_attempts": len(generates)}


def _classify_provider_unresolved(exc: ScreenProviderTerminalError, spent: list[dict]
                                  ) -> tuple[str, dict] | None:
    """Structural, not textual: a ProviderError cause with attempts exhausted."""
    cause = exc.__cause__
    if not isinstance(cause, ProviderError):
        return None
    if cause.reason_code not in PROVIDER_UNRESOLVED_REASONS:
        return None
    counts = [e for e in spent if e["operation_label"] == "count_tokens"]
    generates = [e for e in spent if e["operation_label"] == "generate_content"]
    if generates:
        if len(generates) < SCREEN_GENERATE_MAX_ATTEMPTS:
            return None
    elif len(counts) < SCREEN_COUNT_MAX_ATTEMPTS_V2:
        return None
    return cause.reason_code, {
        "count_attempts": len(counts), "generate_attempts": len(generates),
        "capture_files_persisted": sum(
            1 for e in spent if e["capture_disposition"] == "raw_persisted"),
        "provider_reason_code": cause.reason_code}


def run_lineage_classifier(
    *, repo_root: str | Path, cohort_manifest_path: str | Path,
    overlay_manifest_path: str | Path, release_manifest_path: str | Path,
    packet_manifest_path: str | Path, governance_root: str | Path,
    authorization_reference: str, authorization_sha256: str,
    output_dir: str | Path, run_id: str, clock: Callable[[], datetime],
    dry_run: bool = False, client_factory: Any = None,
    sleep: Callable[[float], None] | None = None,
    route: ClassifierRoute = BASE_ROUTE,
) -> ScreenRunResult:
    """Classify every cohort row under one governed grant."""
    root = Path(repo_root)
    if not _RUN_ID_RE.match(run_id):
        raise ScreenInputError("Invalid run id.")
    pre = _preflight(
        root=root, governance_root=Path(governance_root),
        authorization_reference=authorization_reference,
        authorization_sha256=authorization_sha256,
        cohort_manifest_path=Path(cohort_manifest_path),
        overlay_manifest_path=Path(overlay_manifest_path),
        release_manifest_path=Path(release_manifest_path),
        packet_manifest_path=packet_manifest_path, clock=clock, route=route)
    if dry_run:
        for row, packet, admission in pre.plan:
            render_classifier_prompt(pre.prompt_text, packet, admission)
        return ScreenRunResult(
            run_id, None, True, "dry_run", len(pre.plan), 0,
            request_accounting={
                "cohort_rows": len(pre.inputs.rows),
                "model_called_rows": len(pre.plan),
                "count_attempt_cap": pre.authorization["count_attempt_cap"],
                "provider_attempt_cap": pre.authorization["provider_attempt_cap"],
                "external_request_cap": pre.authorization["budget_max_external_requests"],
            })
    return _execute(root=root, pre=pre, output_dir=output_dir, run_id=run_id,
                    authorization_sha256=authorization_sha256, clock=clock,
                    client_factory=client_factory, sleep=sleep)


def _execute(*, root: Path, pre: _Preflight, output_dir, run_id: str,
             authorization_sha256: str, clock, client_factory, sleep
             ) -> ScreenRunResult:
    """The governed loop, shared by the base route and its continuation."""
    prefix_records = pre.prefix_records
    source = pre.source
    prefix_archive = source["archive_bytes"] if source else b""
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
        raise ScreenInputError(f"Connector handshake refused: {exc.reason_code}.") from exc
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
                           for _, p, _ in pre.plan},
        prompt_template_sha256=pre.prompt_sha256, ledger=ledger)
    adapter._row_ordinal = len(prefix_records)

    archive_path = run_dir / pre.route.archive_filename
    archive = os.fdopen(
        os.open(archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644), "wb")
    if prefix_archive:
        archive.write(prefix_archive)
        archive.flush()
        os.fsync(archive.fileno())
    axes_validator = Draft202012Validator(
        _load_schema(root, pre.route.contracts.axes_schema),
        format_checker=FormatChecker())
    records: list[dict] = list(prefix_records)
    # The prefix's own recomputed failures count against this run's tolerance:
    # they are rows the cohort still has no classification for.
    unusable: dict[str, int] = {}
    for reused in prefix_records:
        if reused["record_kind"] == "model_output_unusable":
            code = reused["failure_reason_code"]
            unusable[code] = unusable.get(code, 0) + 1
    unresolved_rows: list[dict] = []
    truncated_rows: list[dict] = []
    called_rows = count_attempts = generate_attempts = 0
    rows_count_retried = rows_generate_retried = 0

    def base_identity(row: dict, packet: dict, admission: dict, rendered: str) -> dict:
        return {
            "record_contract": pre.route.contracts.record_contract,
            "cik": row["cik"],
            "accession": row["accession"], "company_id": row["company_id"],
            "form": row["form"], "baseline_filing_date": row["baseline_filing_date"],
            "source_id": row["source_id"], "packet_sha256": row["packet_sha256"],
            "prompt_sha256": _sha256(rendered.encode("utf-8")),
            "model_route": dict(adapter.model_route),
            "admission_provenance": {
                "cohort_id": admission["cohort_id"],
                "admission_origin": admission["admission_origin"],
                "admitted_status": admission["admitted_status"],
                "non_authoritative": True,
                "model_screen": admission["model_screen"],
                "human_review": admission["human_review"]},
            "output_provenance": model_called_provenance(run_id, None, None),
            **({"span_index_version": pre.span_rules.version,
                "span_index_sha256": pre.span_rules.sha256}
               if pre.route.contracts.evidence_protocol == "selected_span" else {}),
            "axes": None, "tier": None, "tier_rule_trace": None,
            "failure_reason_code": None, "failure_detail": None,
            "provider_attempt_telemetry": None, "truncation_evidence": None,
        }

    def fail(reason: str, detail: str, row: dict, *,
             stopping_row_completed: bool = False) -> ScreenRunResult:
        """Write the receipt for a stop.

        ``stopping_row_index`` always names the ordinal of the row
        ``stopping_cik``/``stopping_accession`` identifies. That row is not
        always where a continuation resumes: a budget-exhausted stop records
        the offending row before stopping, so the row is complete and a
        continuation resumes after it, while a provider stop never completed
        its row and a continuation resumes at it. The two cases are told apart
        by ``records_completed_before_failure``, and
        ``stopping_row_completed`` states it outright rather than leaving a
        later reader to infer it from an index.
        """
        archive.flush()
        os.fsync(archive.fileno())
        archive.close()
        generates = sum(e["operation_label"] == "generate_content" for e in ledger)
        receipt = {
            "receipt_contract": RECEIPT_CONTRACT, "run_id": run_id,
            "run_kind": pre.authorization["run_kind"], "reason_code": reason,
            "detail": _detail(detail), "stopping_cik": row["cik"],
            "stopping_accession": row["accession"],
            "stopping_row_index": (len(records) if stopping_row_completed
                                   else len(records) + 1),
            "stopping_row_completed": stopping_row_completed,
            "records_completed_before_failure": len(records),
            "reused_prefix_rows": len(prefix_records),
            "model_called_rows_attempted": called_rows,
            "external_requests_made": len(ledger),
            "count_attempts_made": len(ledger) - generates,
            "provider_attempts_made": generates,
            "model_output_unusable_rows": sum(unusable.values()),
            "provider_unresolved_rows": len(unresolved_rows),
            "model_output_truncated_rows": len(truncated_rows),
            "max_model_output_unusable": pre.authorization["max_model_output_unusable"],
            "max_provider_unresolved": pre.authorization["max_provider_unresolved"],
            "max_model_output_truncated":
                pre.authorization["max_model_output_truncated"],
            "authorization_sha256": authorization_sha256,
            "cohort_id": pre.inputs.cohort["cohort_id"],
            "run_timestamp": clock().isoformat(),
            "retention_note": (
                "Non-authoritative classifier run: no records JSONL, no capture "
                "ledger and no manifest exist here. The archived prefix bytes "
                "remain reusable evidence for a governed continuation. This "
                "directory is immutable; a further attempt requires a new run "
                "id and a new authorization."),
        }
        if source is not None:
            receipt.update(source_run_id=source["source_run_id"],
                           source_receipt_sha256=source["source_receipt_sha256"])
        try:
            write_bytes_once(
                run_dir / FAILURE_RECEIPT_FILENAME,
                (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode("utf-8"),
                what="classifier failure receipt")
        except WriteOnceError as exc:
            raise ScreenInputError(str(exc)) from exc
        result.failure_receipt_path = run_dir / FAILURE_RECEIPT_FILENAME
        result.receipt = receipt
        return result

    for row, packet, admission in pre.plan:
        span_index = (build_span_index(packet, pre.span_rules)
                      if pre.span_rules is not None else None)
        rendered, _refs = render_classifier_prompt(pre.prompt_text, packet, admission,
                                                   span_index=span_index)
        called_rows += 1
        before = len(ledger)
        try:
            raw = adapter.screen(rendered, cik=row["cik"], accession=row["accession"])
        except ScreenProviderTerminalError as exc:
            spent = ledger[before:]
            count_attempts += sum(e["operation_label"] == "count_tokens" for e in spent)
            generate_attempts += sum(
                e["operation_label"] == "generate_content" for e in spent)
            truncation = _classify_truncated(run_dir, spent)
            if truncation is not None:
                if len(truncated_rows) + 1 > pre.authorization["max_model_output_truncated"]:
                    return fail("model_output_truncated_budget_exhausted",
                                "The authorized truncated-output tolerance was "
                                "exceeded.", row)
                record = {**base_identity(row, packet, admission, rendered),
                          "record_kind": "model_output_truncated",
                          "failure_reason_code": TRUNCATED_REASON,
                          "failure_detail": _detail(str(exc)),
                          "truncation_evidence": truncation}
                truncated_rows.append(record)
                records.append(record)
                continue
            classified = _classify_provider_unresolved(exc, spent)
            if classified is not None:
                reason, telemetry = classified
                if len(unresolved_rows) + 1 > pre.authorization["max_provider_unresolved"]:
                    return fail("provider_unresolved_budget_exhausted",
                                f"The authorized provider-unresolved tolerance was "
                                f"exceeded ({reason}).", row)
                record = {**base_identity(row, packet, admission, rendered),
                          "record_kind": "provider_unresolved",
                          "failure_reason_code": reason,
                          "failure_detail": _detail(str(exc)),
                          "provider_attempt_telemetry": telemetry}
                unresolved_rows.append(record)
                records.append(record)
                continue
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
        record = {**base_identity(row, packet, admission, rendered),
                  "output_provenance": model_called_provenance(
                      run_id, response_id, raw_sha)}
        try:
            if span_index is not None:
                axes = validate_span_axes_output(
                    raw, packet, axes_validator,
                    pre.route.contracts.axes_contract, span_index)
            else:
                axes = validate_axes_output(raw, packet, axes_validator,
                                            pre.route.contracts.axes_contract)
        except AxesValidationFailure as exc:
            unusable[exc.reason_code] = unusable.get(exc.reason_code, 0) + 1
            record.update(record_kind="model_output_unusable",
                          failure_reason_code=exc.reason_code,
                          failure_detail=_detail(exc.detail))
            if sum(unusable.values()) > pre.authorization["max_model_output_unusable"]:
                records.append(record)
                return fail("model_output_unusable_budget_exhausted",
                            "The authorized unusable-output tolerance was exceeded.",
                            row, stopping_row_completed=True)
        else:
            derivation = derive_tier(axes, pre.tier_rules)
            record.update(record_kind="classified", axes=axes,
                          tier=derivation.tier, tier_rule_trace=derivation.trace)
        records.append(record)
    archive.flush()
    os.fsync(archive.fileno())
    archive.close()

    validator = Draft202012Validator(
        _load_schema(root, pre.route.contracts.record_schema),
        format_checker=FormatChecker())
    for record in records:
        errors = sorted(validator.iter_errors(record), key=lambda e: e.json_path)
        if errors:
            raise ScreenInputError(
                f"Built classifier record violates "
                f"{pre.route.contracts.record_contract} at "
                f"{errors[0].json_path}: {errors[0].message}")
    return _settle(root=root, pre=pre, run_dir=run_dir, run_id=run_id,
                   authorization_sha256=authorization_sha256, clock=clock,
                   records=records, ledger=ledger, budget=budget,
                   archive_path=archive_path, result=result, unusable=unusable,
                   unresolved_rows=unresolved_rows, truncated_rows=truncated_rows,
                   counters=(called_rows, count_attempts, generate_attempts,
                             rows_count_retried, rows_generate_retried))


def _settle(*, root, pre, run_dir, run_id, authorization_sha256, clock, records,
            ledger, budget, archive_path, result, unusable, unresolved_rows,
            truncated_rows, counters) -> ScreenRunResult:
    """Write the ledger, records and manifest once every identity holds."""
    prefix_records = pre.prefix_records
    source = pre.source
    called_rows, count_attempts, generate_attempts, count_retried, generate_retried = counters
    is_continuation = source is not None
    is_calibration = pre.selection is not None
    records_filename = pre.route.records_filename
    manifest_filename = pre.route.manifest_filename
    manifest_contract = pre.route.manifest_contract
    manifest_schema = pre.route.manifest_schema
    ledger_bytes = "".join(_canonical_line(e) + "\n" for e in ledger).encode("utf-8")
    records_bytes = "".join(_canonical_line(r) + "\n" for r in records).encode("utf-8")
    try:
        write_bytes_once(run_dir / CAPTURE_LEDGER_FILENAME, ledger_bytes,
                         what="classifier capture ledger")
        write_bytes_once(run_dir / records_filename, records_bytes,
                         what="classifier records")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc

    archive_raw = archive_path.read_bytes()
    archive_entries = [json.loads(line) for line
                       in _decode_utf8(archive_raw,
                                       pre.route.archive_filename).splitlines()
                       if line.strip()]
    classified = [r for r in records if r["record_kind"] == "classified"]
    answered = [r for r in records if r["output_provenance"]["raw_response_id"]]
    persisted = [e for e in ledger if e["capture_disposition"] == "raw_persisted"]
    capture_ok = all(
        (run_dir / e["raw_reference"]).is_file()
        and _sha256((run_dir / e["raw_reference"]).read_bytes()) == e["raw_sha256"]
        for e in persisted)
    disk_refs = ({str(p.relative_to(run_dir))
                  for p in (run_dir / CAPTURES_DIRNAME).rglob("*") if p.is_file()}
                 if (run_dir / CAPTURES_DIRNAME).exists() else set())
    # Counts come from the records, never from the loop's running tallies: a
    # continuation's reused rows are records this run never sent.
    def _kind(kind: str) -> int:
        return sum(r["record_kind"] == kind for r in records)

    unusable_by_reason: dict[str, int] = {}
    for record in records:
        if record["record_kind"] == "model_output_unusable":
            code = record["failure_reason_code"]
            unusable_by_reason[code] = unusable_by_reason.get(code, 0) + 1
    scope_rows = pre.selection["rows"] if is_calibration else pre.inputs.rows
    counts = {
        "cohort_rows": len(pre.inputs.rows), "classified": len(classified),
        "model_output_unusable": _kind("model_output_unusable"),
        "provider_unresolved": _kind("provider_unresolved"),
        "model_output_truncated": _kind("model_output_truncated"),
        "by_admission_origin": {
            o: sum(r["admission_provenance"]["admission_origin"] == o for r in records)
            for o in ("model_screen", "human_review")},
        "by_tier": {t: sum(r["tier"] == t for r in classified)
                    for t in ("TIER_A", "TIER_B", "TIER_C", "EXCLUDED", "UNCERTAIN")},
        "by_software_centrality": _tally(classified, "software_centrality"),
        "by_firm_structure": _tally(classified, "firm_structure"),
        "by_commercial_materiality": _tally(classified, "commercial_materiality"),
        "by_customer_market_orientation": _tally(classified,
                                                 "customer_market_orientation"),
        "contradiction_rows": sum(bool(r["axes"]["contradictions"]) for r in classified),
        "boundary_flag_rows": sum(bool(r["axes"]["boundary_flags"]) for r in classified),
        "unusable_by_reason": unusable_by_reason,
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
        "reused_prefix_rows": len(prefix_records),
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
    reconciliation = {
        "every row in scope produced exactly one record": (
            len(records) == len(scope_rows)
            and len({(r["cik"], r["accession"]) for r in records}) == len(records)),
        "records follow the scope's own row order": (
            [(r["cik"], r["accession"]) for r in records]
            == [(r["cik"], r["accession"]) for r in scope_rows]),
        "the four record kinds partition the run": (
            len(classified) + counts["model_output_unusable"]
            + counts["provider_unresolved"] + counts["model_output_truncated"]
            == len(records)),
        "every record carries its admission origin and non-authority": all(
            r["admission_provenance"]["admission_origin"]
            in ("model_screen", "human_review")
            and r["admission_provenance"]["non_authoritative"] is True
            for r in records),
        "model-screen rows cite a screen response and no reviewer": all(
            r["admission_provenance"]["model_screen"]
            and r["admission_provenance"]["human_review"] is None
            for r in records
            if r["admission_provenance"]["admission_origin"] == "model_screen"),
        "human-review rows cite a reviewer and no screen response": all(
            r["admission_provenance"]["human_review"]
            and r["admission_provenance"]["model_screen"] is None
            for r in records
            if r["admission_provenance"]["admission_origin"] == "human_review"),
        # A calibration deliberately over-weights the reviewer-admitted rows,
        # so its origin split is the selection's, never the cohort's.
        "the origin split matches the scope's own": (
            counts["by_admission_origin"]["model_screen"]
            == sum(r["admission_origin"] == "model_screen" for r in scope_rows)
            and counts["by_admission_origin"]["human_review"]
            == sum(r["admission_origin"] == "human_review" for r in scope_rows)),
        "no model output supplied a tier": all(
            "tier" not in (r["axes"] or {}) and "candidate_tier" not in (r["axes"] or {})
            for r in records),
        "every classified row carries a derived tier and its trace": all(
            r["tier"] in ("TIER_A", "TIER_B", "TIER_C", "EXCLUDED", "UNCERTAIN")
            and r["tier_rule_trace"]["tier_rules_sha256"] == pre.tier_rules.sha256
            for r in classified),
        "every tier is reproducible from its stored axes": all(
            derive_tier(r["axes"], pre.tier_rules).tier == r["tier"]
            for r in classified),
        "the tier distribution sums to the classified population": (
            sum(counts["by_tier"].values()) == len(classified)),
        "no unclassified row carries axes or a tier": all(
            r["axes"] is None and r["tier"] is None and r["tier_rule_trace"] is None
            for r in records if r["record_kind"] != "classified"),
        "every classified row's evidence resolves in its packet": all(
            _evidence_resolves(
                r, pre.packets,
                selected_span=pre.route.contracts.evidence_protocol
                == "selected_span") for r in classified),
        "bounded outcomes stayed within their authorized tolerances": (
            counts["model_output_unusable"]
            <= pre.authorization["max_model_output_unusable"]
            and counts["provider_unresolved"]
            <= pre.authorization["max_provider_unresolved"]
            and counts["model_output_truncated"]
            <= pre.authorization["max_model_output_truncated"]),
        "the unusable breakdown sums to the unusable population": (
            sum(unusable_by_reason.values()) == counts["model_output_unusable"]),
        "the archive holds one line per answered row": (
            len(archive_entries) == len(answered)),
        "only answered rows carry a response id": all(
            (r["output_provenance"]["raw_response_id"] is not None)
            == (r["record_kind"] in ("classified", "model_output_unusable"))
            for r in records),
        "every archived response re-hashes": all(
            _sha256(e["raw_response"].encode("utf-8")) == e["raw_response_sha256"]
            for e in archive_entries),
        "capture files rehash to their ledger lines": capture_ok,
        "no orphan capture file exists": disk_refs == {
            e["raw_reference"] for e in persisted},
        "count and generate sends partition external requests": (
            count_attempts + generate_attempts == len(ledger)),
        "no row exceeded its send ceilings": (
            count_attempts <= pre.authorization["count_attempt_cap"]
            and generate_attempts <= pre.authorization["provider_attempt_cap"]
            and len(ledger) <= pre.authorization["budget_max_external_requests"]),
        "the prompt and tier rules are the authorized ones": (
            pre.prompt_sha256 == pre.authorization["prompt_template_sha256"]
            and pre.tier_rules.sha256 == pre.authorization["tier_rules_sha256"]),
        "every input source is byte-unchanged": _sources_unchanged(pre),
    }
    if is_calibration:
        selected = {(r["cik"], r["accession"]) for r in pre.selection["rows"]}
        quotas = {s["rule_id"]: s for s in pre.selection["sampling"]["strata"]}
        by_stratum: dict[str, int] = {}
        for row in pre.selection["rows"]:
            by_stratum[row["stratum"]] = by_stratum.get(row["stratum"], 0) + 1
        counts["selected_rows"] = len(scope_rows)
        counts["by_stratum"] = by_stratum
        reconciliation.update({
            "every classified row is a selected row": all(
                (r["cik"], r["accession"]) in selected for r in records),
            "the run covers strictly less than the cohort": (
                len(records) < len(pre.inputs.rows)),
            "each stratum contributed exactly its selected count": all(
                by_stratum.get(rule_id, 0) == stratum["selected"]
                for rule_id, stratum in quotas.items()),
            "the selection's strata rules are the authorized ones": (
                pre.selection["strata_rules_sha256"]
                == pre.authorization["strata_rules_sha256"]
                and pre.selection["sampling"]["seed"]
                == pre.authorization["selection_seed"]),
            "the selection was drawn from this cohort": (
                pre.selection["cohort_manifest_sha256"]
                == pre.authorization["cohort_manifest_sha256"]),
        })
    if is_continuation:
        reconciliation.update({
            "the archive opens with the source archive byte for byte": (
                archive_raw.startswith(source["archive_bytes"])),
                "the reused prefix cost this run no send": all(
                e["row_ordinal"] > len(prefix_records) for e in ledger),
            "every reused row names the source run and nothing else": all(
                r["output_provenance"]["origin"] == "reused_source_prefix"
                and r["output_provenance"]["source_run_id"] == source["source_run_id"]
                and r["output_provenance"]["source_receipt_sha256"]
                == source["source_receipt_sha256"]
                for r in records[:len(prefix_records)]),
            "every called row names no source": all(
                r["output_provenance"]["origin"] == "model_called"
                and r["output_provenance"]["source_run_id"] is None
                for r in records[len(prefix_records):]),
            "reused and called rows partition the cohort": (
                len(prefix_records) + called_rows == len(pre.inputs.rows)),
            "the source run is byte-unchanged": (
                _sha256((Path(source["source_run_path"])
                         / pre.route.archive_filename).read_bytes())
                == source["source_raw_responses_sha256"]),
        })
    if not all(reconciliation.values()):
        failed = sorted(k for k, v in reconciliation.items() if not v)
        raise ScreenInputError(
            f"Classifier reconciliation failed; no manifest is written. Failed "
            f"identities: {failed}.")
    manifest = {
        "manifest_contract": manifest_contract, "run_id": run_id,
        "run_kind": pre.authorization["run_kind"],
        "run_timestamp": clock().isoformat(), "promotable": False,
        "authorization_id": pre.authorization["authorization_id"],
        "authorization_sha256": authorization_sha256,
        "sources": {
            "cohort": pre.inputs.cohort_digests,
            "overlay": pre.inputs.overlay_digests,
            "release": pre.inputs.release_digests,
            "packet": {
                "packet_manifest_path":
                    pre.inputs.overlay["packet_source"]["packet_manifest_path"],
                "packet_manifest_sha256": pre.authorization["packet_manifest_sha256"],
                "packets_jsonl_sha256":
                    pre.inputs.overlay["packet_source"]["packets_jsonl_sha256"]},
            "sources_unmodified": True},
        "prompt_template_path": pre.route.contracts.prompt_path,
        "prompt_template_sha256": pre.prompt_sha256,
        "tier_rules_version": pre.tier_rules.version,
        "tier_rules_sha256": pre.tier_rules.sha256,
        "taxonomy_version": pre.route.contracts.taxonomy_version,
        **({"span_index_version": pre.span_rules.version,
            "span_index_sha256": pre.span_rules.sha256}
           if pre.span_rules is not None else {}),
        "provider": dict(pre.model_route),
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": pre.contract_digest,
        "screen_adapter_enablement_sha256":
            pre.authorization["screen_adapter_enablement_sha256"],
        "endpoint_allowlist": sorted(pre.endpoints.values()),
        "envelope_text_extraction_rule": ENVELOPE_TEXT_EXTRACTION_RULE,
        "output_contract": pre.route.contracts.record_contract,
        "output_hashes": {records_filename: _sha256(records_bytes),
                          pre.route.archive_filename: _sha256(archive_raw),
                          CAPTURE_LEDGER_FILENAME: _sha256(ledger_bytes)},
        "record_order": pre.route.record_order, "counts": counts,
        "request_accounting": request_accounting,
        "bounded_outcomes": {
            "max_provider_unresolved": pre.authorization["max_provider_unresolved"],
            "max_model_output_truncated":
                pre.authorization["max_model_output_truncated"],
            "max_model_output_unusable":
                pre.authorization["max_model_output_unusable"],
            "tier_excludes_market_orientation": True},
        "reconciliation": reconciliation,
        "schema_versions": {
            "universe_classifier_axes_record":
                pre.route.contracts.axes_contract.rsplit("@", 1)[1],
            "universe_classifier_record":
                pre.route.contracts.record_contract.rsplit("@", 1)[1],
            "universe_classifier_manifest":
                pre.route.manifest_contract.rsplit("@", 1)[1],
            "screen_connector": SCREEN_CONNECTOR_V6_ID},
        "limitations": [
            "The admission context is not evidence. Axes were judged against "
            "the complete Item 1 packet, and a prior screen or reviewer "
            "conclusion may be contradicted here.",
            "The model emitted axes only. Every tier was derived by the pinned "
            "deterministic rule config and is replayable from the stored axes.",
            "customer_market_orientation is descriptive metadata and is no "
            "input to the tier function.",
            "This run is an observation, not a frozen universe. It is "
            "structurally non-promotable and carries no adjudication state.",
            "Rows recorded as unusable, provider-unresolved or truncated are "
            "rows about which this run concluded nothing.",
        ],
    }
    if is_calibration:
        manifest["covers_full_cohort"] = False
        manifest["calibration_selection"] = {
            "selection_id": pre.selection["selection_id"],
            "selection_sha256": pre.authorization["selection_artifact_sha256"],
            "strata_rules_version": pre.selection["strata_rules_version"],
            "strata_rules_sha256": pre.selection["strata_rules_sha256"],
            "sampling_algorithm": pre.selection["sampling"]["algorithm"],
            "seed": pre.selection["sampling"]["seed"],
            "selected_rows": len(pre.selection["rows"]),
            "cohort_rows": pre.selection["counts"]["cohort_rows"],
        }
        manifest["limitations"] = manifest["limitations"] + [
            "This is a calibration observation over a stratified sample, not a "
            "universe. It settles no firm's membership and is structurally "
            "non-promotable.",
            "Strata were derived from SCREEN_v1 candidate archetypes, which are "
            "sample design only. They are not truth about a firm and are no "
            "input to the tier engine, which reads the classifier's own axes.",
            "The sample is too small to estimate a rate. Its counts describe "
            "these rows and may not be read as the full cohort's yield, nor "
            "used to set the full run's bounded-outcome tolerances.",
        ]
    if is_continuation:
        manifest["continuation"] = {
            "source_run_id": source["source_run_id"],
            "source_kind": "failed_classifier_run",
            "source_receipt_sha256": source["source_receipt_sha256"],
            "source_raw_responses_sha256": source["source_raw_responses_sha256"],
            "reused_prefix_rows": len(prefix_records),
            "model_called_rows": called_rows,
            "first_model_called_row_ordinal": len(prefix_records) + 1,
            "source_archive_is_byte_identical_prefix": True}
    _validate(manifest, _load_schema(root, manifest_schema), "Classifier manifest")
    try:
        write_bytes_once(
            run_dir / manifest_filename,
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
            what="classifier manifest")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    result.status = "completed"
    result.counts = counts
    result.request_accounting = request_accounting
    result.reconciliation = reconciliation
    result.manifest_path = run_dir / manifest_filename
    return result


def _tally(records: list[dict], field: str) -> dict[str, int]:
    tally: dict[str, int] = {}
    for record in records:
        value = (record["axes"] or {}).get(field)
        if value is not None:
            tally[value] = tally.get(value, 0) + 1
    return tally


def _evidence_resolves(record: dict, packets: dict, *,
                       selected_span: bool = False) -> bool:
    """Re-derive one stored row's evidence from its packet.

    For ``model_quote`` versions this is the original check: the typed quote
    must occur in the passage it cites. For ADR-132's ``selected_span`` it is a
    stronger and cheaper one: the stored text must be exactly what sits at the
    stored offsets, and must hash to the stored digest.

    Neither path loads the span-index config or runs the segmenter. That is the
    property ADR-132 claimed and an earlier revision of this function broke, by
    rebuilding a span index here purely to reach the verifier. The span index is
    needed to *render* the menu and to resolve a model's selection the first
    time; it is not needed, and must not be needed, to check a stored row.
    """
    packet = packets.get((record["cik"], record["accession"]))
    if packet is None:
        return False
    if selected_span:
        return all(verify_stored_span(item, packet)
                   for item in record["axes"]["evidence"])
    refs = passage_refs(packet)
    bodies = {p["passage_id"]: " ".join(p["text"].split()) for p in packet["passages"]}
    for item in record["axes"]["evidence"]:
        passage_id = refs.get(item["passage_ref"])
        if passage_id is None or " ".join(item["quote"].split()) not in bodies[passage_id]:
            return False
    return True


def _sources_unchanged(pre: _Preflight) -> bool:
    return (pre.inputs.cohort_digests["manifest_sha256"]
            == pre.authorization["cohort_manifest_sha256"]
            and pre.inputs.overlay_digests["manifest_sha256"]
            == pre.authorization["overlay_manifest_sha256"]
            and pre.inputs.release_digests["manifest_sha256"]
            == pre.authorization["release_manifest_sha256"])
