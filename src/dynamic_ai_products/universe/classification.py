"""Stage 00E full multi-axis classification: provider boundary and validation.

The mock provider replays precomputed fixture outputs. Every record is
validated against the canonical JSON schema and against the baseline packet
(evidence quotes must resolve; no post-cutoff evidence). Invalid model output
is stored raw and marked failed — never silently repaired.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Protocol

from jsonschema import Draft202012Validator
from pydantic import ValidationError

from .io_utils import read_json
from .models import (
    BaselineEvidencePacket,
    HighRecallScreenOutput,
    HistoricalAnnualFiler,
    UniverseClassification,
)
from .packets import validate_quotes_resolve

PROMPT_RELATIVE_PATH = Path("prompts/discovery/universe_full_classification.md")
SCHEMA_RELATIVE_PATH = Path("schemas/company_universe_classification.schema.json")


class ClassificationFailure(RuntimeError):
    """Raised when a classification output is missing or invalid."""


class ClassificationProvider(Protocol):
    name: str

    def classify(
        self,
        filer: HistoricalAnnualFiler,
        packet: BaselineEvidencePacket,
        screen: HighRecallScreenOutput,
    ) -> dict: ...


class MockClassificationProvider:
    """Replays precomputed classification outputs keyed by CIK."""

    name = "mock"

    def __init__(self, fixture_path: str | Path):
        self._outputs: dict[str, dict] = read_json(fixture_path)

    def classify(
        self,
        filer: HistoricalAnnualFiler,
        packet: BaselineEvidencePacket,
        screen: HighRecallScreenOutput,
    ) -> dict:
        try:
            return dict(self._outputs[filer.cik])
        except KeyError as exc:
            raise ClassificationFailure(
                f"Mock classification fixture has no output for CIK {filer.cik}."
            ) from exc


def load_schema_validator(repo_root: str | Path) -> Draft202012Validator:
    schema = json.loads(
        (Path(repo_root) / SCHEMA_RELATIVE_PATH).read_text(encoding="utf-8")
    )
    return Draft202012Validator(schema)


def validate_classification(
    raw_output: dict,
    filer: HistoricalAnnualFiler,
    packet: BaselineEvidencePacket,
    schema_validator: Draft202012Validator,
) -> UniverseClassification:
    """Validate one raw classification against schema, packet, and cutoff."""
    errors = sorted(schema_validator.iter_errors(raw_output), key=lambda e: e.json_path)
    if errors:
        details = "; ".join(f"{e.json_path}: {e.message}" for e in errors[:5])
        raise ClassificationFailure(
            f"Classification for CIK {filer.cik} violates the canonical schema: {details}"
        )
    try:
        record = UniverseClassification.model_validate(raw_output)
    except ValidationError as exc:
        raise ClassificationFailure(
            f"Classification for CIK {filer.cik} failed model validation: {exc}"
        ) from exc

    if record.cik != filer.cik:
        raise ClassificationFailure(
            f"Classification CIK {record.cik} does not match candidate {filer.cik}."
        )
    if record.baseline_cutoff != packet.baseline_cutoff:
        raise ClassificationFailure(
            f"Classification cutoff {record.baseline_cutoff} does not match "
            f"packet cutoff {packet.baseline_cutoff}."
        )
    if record.baseline_filing_date > packet.baseline_cutoff:
        raise ClassificationFailure(
            f"Baseline filing date {record.baseline_filing_date} is after the cutoff."
        )
    unresolved = validate_quotes_resolve(packet, [e.quote for e in record.evidence])
    if unresolved:
        raise ClassificationFailure(
            f"Classification for CIK {filer.cik} cites quotes that do not resolve "
            f"to baseline packet passages: {unresolved}"
        )
    non_null_axes = record.software_centrality != "UNKNOWN" or bool(
        set(record.customer_value_archetypes) - {"OTHER"}
    )
    if non_null_axes and not record.evidence:
        raise ClassificationFailure(
            f"Classification for CIK {filer.cik} makes axis claims without evidence."
        )
    return record
