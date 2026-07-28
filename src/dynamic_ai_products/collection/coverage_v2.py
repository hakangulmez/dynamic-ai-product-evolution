"""Coverage successor ``source_family_coverage@0.2.0`` (ADR-032).

Content role and access channel are recorded as two independent dimensions.
``web_archives`` is not a content family: it survives only as an explicit
derived bridge for the Pilot Packet's legacy required entry.

The published Increment B coverage artifact is never mutated; this successor is
written only into a new collection run root.
"""

from __future__ import annotations

from typing import Any, Iterable

from .errors import CollectionError
from .request_plan import CONTENT_FAMILIES, REQUIRED_CONTENT_FAMILIES

__all__ = [
    "ACCESS_CHANNELS",
    "COVERAGE_CONTRACT_V2",
    "COVERAGE_STATES",
    "LEGACY_BRIDGE_FAMILY",
    "OPTIONAL_CONTENT_FAMILIES",
    "build_source_family_coverage_v2",
]

COVERAGE_CONTRACT_V2 = "source_family_coverage@0.2.0"
LEGACY_BRIDGE_FAMILY = "web_archives"
OPTIONAL_CONTENT_FAMILIES: tuple[str, ...] = ("newsroom",)
ACCESS_CHANNELS: tuple[str, ...] = ("live", "archive")

# The governed eight (ADR-031 added not_attempted to the CORPUS_ARCHITECTURE
# seven). not_attempted is not a permissible terminal state for a required
# content family once this stage has run.
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
_TERMINAL_STATES = tuple(s for s in COVERAGE_STATES if s != "not_attempted")


def _require_terminal(family: str, state: str) -> str:
    if state not in COVERAGE_STATES:
        raise CollectionError(
            f"undeclared coverage state for {family}: {state}",
            reason_code="coverage_state_unknown",
        )
    if state == "not_attempted":
        raise CollectionError(
            f"required family {family} may not remain not_attempted after a run",
            reason_code="family_coverage_incomplete",
        )
    return state


def build_source_family_coverage_v2(
    *,
    company_id: str,
    observation_cutoff_date: str,
    content_family_states: dict[str, str],
    content_family_reasons: dict[str, str] | None = None,
    admitted_counts: dict[str, int] | None = None,
    channel_admitted: dict[str, int],
    channel_temporally_valid: dict[str, int],
    inherited_sec_edgar_state: str,
    parent_manifest_sha256: str,
    errors: Iterable[dict[str, Any]] = (),
) -> dict[str, Any]:
    """Build the two-dimension coverage artifact plus the legacy bridge."""
    reasons = dict(content_family_reasons or {})
    counts = dict(admitted_counts or {})

    missing = sorted(set(REQUIRED_CONTENT_FAMILIES) - set(content_family_states))
    if missing:
        raise CollectionError(
            f"required content families missing a coverage state: {missing}",
            reason_code="family_coverage_incomplete",
        )
    unknown = sorted(set(content_family_states) - set(CONTENT_FAMILIES))
    if unknown:
        raise CollectionError(
            f"unknown content families reported: {unknown}",
            reason_code="family_coverage_out_of_set",
        )
    for channel in ACCESS_CHANNELS:
        for label, mapping in (
            ("admitted", channel_admitted),
            ("temporally_valid", channel_temporally_valid),
        ):
            if channel not in mapping:
                raise CollectionError(
                    f"access channel {channel} missing a {label} count",
                    reason_code="family_coverage_incomplete",
                )

    content_block = []
    for family in sorted(CONTENT_FAMILIES):
        if family not in content_family_states:
            # Optional families may be absent; record them explicitly.
            content_block.append(
                {
                    "content_family": family,
                    "membership": "optional",
                    "coverage_state": "not_attempted",
                    "reason_code": "out_of_required_set",
                    "admitted_count": 0,
                }
            )
            continue
        required = family in REQUIRED_CONTENT_FAMILIES
        state = content_family_states[family]
        if required:
            _require_terminal(family, state)
        elif state not in COVERAGE_STATES:
            raise CollectionError(
                f"undeclared coverage state for {family}: {state}",
                reason_code="coverage_state_unknown",
            )
        content_block.append(
            {
                "content_family": family,
                "membership": "required" if required else "optional",
                "coverage_state": state,
                "reason_code": reasons.get(family, ""),
                "admitted_count": int(counts.get(family, 0)),
            }
        )

    channel_block = [
        {
            "access_channel": channel,
            "admitted_count": int(channel_admitted[channel]),
            "temporally_valid_count": int(channel_temporally_valid[channel]),
        }
        for channel in sorted(ACCESS_CHANNELS)
    ]

    # Explicit derived bridge for the Pilot Packet's legacy required entry.
    valid_archive = int(channel_temporally_valid["archive"])
    if valid_archive > 0:
        bridge_state = "available_and_retrieved"
        bridge_reason = ""
    else:
        attempted = int(channel_admitted["archive"])
        bridge_state = "available_but_failed" if attempted else "not_found"
        bridge_reason = (
            "archive captures were admitted but none was temporally valid"
            if attempted
            else "no archived capture of an allowed official-origin URL was admitted"
        )
    if bridge_state not in _TERMINAL_STATES:
        raise CollectionError(
            f"legacy bridge produced a non-terminal state: {bridge_state}",
            reason_code="family_coverage_incomplete",
        )

    if inherited_sec_edgar_state not in COVERAGE_STATES:
        raise CollectionError(
            f"undeclared inherited coverage state: {inherited_sec_edgar_state}",
            reason_code="coverage_state_unknown",
        )

    return {
        "contract": COVERAGE_CONTRACT_V2,
        "schema_version": "0.2.0",
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "content_families": content_block,
        "access_channels": channel_block,
        "inherited": [
            {
                "source_family": "sec_edgar",
                "coverage_state": inherited_sec_edgar_state,
                "inherited_from_manifest_sha256": parent_manifest_sha256,
            }
        ],
        "legacy_bridge": {
            "source_family": LEGACY_BRIDGE_FAMILY,
            "membership": "required_legacy",
            "coverage_state": bridge_state,
            "reason_code": bridge_reason,
            "derived_from": "access_channel=archive admitted, temporally_valid",
            "temporally_valid_archive_count": valid_archive,
        },
        "errors": [dict(record) for record in errors],
    }
