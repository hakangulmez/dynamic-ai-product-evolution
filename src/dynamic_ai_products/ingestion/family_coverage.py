"""Stage 02 source-family coverage and error artifact (SPEC-004, ADR-031).

The required Pilot 0 family set is exactly the five families declared in the
committed Pilot Universe Packet. ``newsroom`` is recorded as an explicit
optional, out-of-required-set family rather than being silently absent.

``not_attempted`` is a governed coverage state added by ADR-031. It is the
only truthful state for a family that was never queried: ``not_found`` would
claim we looked and ``not_applicable`` would claim the family does not apply.
"""

from __future__ import annotations

from typing import Any, Iterable

from .errors import IngestionError

__all__ = [
    "COVERAGE_CONTRACT",
    "COVERAGE_STATES",
    "OPTIONAL_FAMILIES",
    "REQUIRED_FAMILIES",
    "build_source_family_coverage",
]

COVERAGE_CONTRACT = "source_family_coverage@0.1.0"

# The seven states from docs/architecture/CORPUS_ARCHITECTURE.md plus the
# ADR-031 addition.
COVERAGE_STATES: tuple[str, ...] = (
    "available_and_retrieved",
    "available_but_failed",
    "not_found",
    "not_applicable",
    "temporally_invalid",
    "duplicate",
    "robots_or_access_blocked",
    "not_attempted",
)

# Exactly the families declared by the committed packet.
REQUIRED_FAMILIES: tuple[str, ...] = (
    "sec_edgar",
    "official_ir",
    "product_pages",
    "developer_docs",
    "web_archives",
)

# Present in configs/source_types.yaml and docs/source_playbooks/, but outside
# the packet's declared set. Recorded, never omitted.
OPTIONAL_FAMILIES: tuple[str, ...] = ("newsroom",)


def _require_state(family: str, state: str) -> str:
    if state not in COVERAGE_STATES:
        raise IngestionError(
            f"undeclared coverage state for {family}: {state}",
            reason_code="coverage_state_unknown",
        )
    return state


def build_source_family_coverage(
    *,
    company_id: str,
    observation_cutoff_date: str,
    required_states: dict[str, str],
    optional_states: dict[str, str] | None = None,
    errors: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Build the Stage 02 coverage/error artifact.

    Every required family must carry a declared coverage state; a missing one
    is a fail-closed stop rather than an assumed default.
    """
    missing = sorted(set(REQUIRED_FAMILIES) - set(required_states))
    if missing:
        raise IngestionError(
            f"required source families missing a coverage state: {missing}",
            reason_code="family_coverage_incomplete",
        )
    extra = sorted(set(required_states) - set(REQUIRED_FAMILIES))
    if extra:
        raise IngestionError(
            f"families outside the required set were reported as required: {extra}",
            reason_code="family_coverage_out_of_set",
        )

    optional_states = dict(optional_states or {})
    unknown_optional = sorted(set(optional_states) - set(OPTIONAL_FAMILIES))
    if unknown_optional:
        raise IngestionError(
            f"unknown optional families: {unknown_optional}",
            reason_code="family_coverage_out_of_set",
        )

    required_block = [
        {
            "source_family": family,
            "membership": "required",
            "coverage_state": _require_state(family, required_states[family]),
        }
        for family in sorted(REQUIRED_FAMILIES)
    ]
    optional_block = [
        {
            "source_family": family,
            "membership": "out_of_required_set",
            "coverage_state": _require_state(
                family, optional_states.get(family, "not_attempted")
            ),
        }
        for family in sorted(OPTIONAL_FAMILIES)
    ]

    return {
        "contract": COVERAGE_CONTRACT,
        "schema_version": "0.1.0",
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "required_families": required_block,
        "optional_families": optional_block,
        "errors": [dict(record) for record in errors],
    }
