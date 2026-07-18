"""Stage 00D high-recall screen: prompt rendering, provider boundary, validation.

Phase 0 ships only a deterministic mock provider that replays precomputed
fixture outputs. No model API and no network access exist in this module.
The screen result is never final sample membership.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from pydantic import ValidationError

from .io_utils import read_json
from .models import BaselineEvidencePacket, HighRecallScreenOutput, HistoricalAnnualFiler
from .packets import validate_quotes_resolve

PROMPT_RELATIVE_PATH = Path("prompts/discovery/universe_high_recall_screen.md")


class ScreenProviderError(RuntimeError):
    """The provider could not produce a valid output for a candidate."""


class ScreenProvider(Protocol):
    name: str

    def screen(
        self, filer: HistoricalAnnualFiler, packet: BaselineEvidencePacket, prompt: str
    ) -> dict: ...


class MockScreenProvider:
    """Replays precomputed screen outputs keyed by CIK from a fixture file."""

    name = "mock"

    def __init__(self, fixture_path: str | Path):
        self._outputs: dict[str, dict] = read_json(fixture_path)

    def screen(
        self, filer: HistoricalAnnualFiler, packet: BaselineEvidencePacket, prompt: str
    ) -> dict:
        try:
            return dict(self._outputs[filer.cik])
        except KeyError as exc:
            raise ScreenProviderError(
                f"Mock screen fixture has no output for CIK {filer.cik}."
            ) from exc


def render_screen_prompt(
    template_text: str,
    filer: HistoricalAnnualFiler,
    packet: BaselineEvidencePacket,
) -> str:
    """Fill the input template placeholders of the canonical screen prompt."""
    metadata = (
        f"cik: {filer.cik}\n"
        f"name: {filer.canonical_name}\n"
        f"form: {filer.form}\n"
        f"filing_date: {filer.filing_date}\n"
        f"sic: {filer.sic}"
    )
    passages = "\n\n".join(
        f"[source_id={p.source_id} passage_id={p.passage_id} "
        f"section={p.section} date={p.publication_date}]\n{p.text}"
        for p in packet.passages
    )
    rendered = template_text
    replacements = {
        "{{baseline_cutoff}}": str(packet.baseline_cutoff),
        "{{company_metadata}}": metadata,
        "{{passages_with_source_and_passage_ids}}": passages,
    }
    for placeholder, value in replacements.items():
        if placeholder not in rendered:
            raise ValueError(f"Screen prompt template is missing placeholder {placeholder}.")
        rendered = rendered.replace(placeholder, value)
    return rendered


def validate_screen_output(
    raw_output: dict,
    filer: HistoricalAnnualFiler,
    packet: BaselineEvidencePacket,
) -> HighRecallScreenOutput:
    """Validate structure, evidence resolution, and temporal integrity."""
    payload = {"cik": filer.cik, "company_id": filer.company_id, **raw_output}
    try:
        output = HighRecallScreenOutput.model_validate(payload)
    except ValidationError as exc:
        raise ScreenProviderError(f"Invalid screen output for CIK {filer.cik}: {exc}") from exc

    quotes = [item.quote for item in output.positive_evidence + output.negative_or_boundary_evidence]
    unresolved = validate_quotes_resolve(packet, quotes)
    if unresolved:
        raise ScreenProviderError(
            f"Screen output for CIK {filer.cik} contains quotes that do not resolve "
            f"to baseline packet passages: {unresolved}"
        )
    return output
