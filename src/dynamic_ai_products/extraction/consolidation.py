"""Product consolidation: label resolution and universe assembly (ADR-073).

The consolidation stage is the first one whose input is another stage's output
rather than the corpus. What it returns is also different in kind: not candidate
observations, but **decisions about** candidates the discovery stage already
produced.

That difference drives the one design rule this module exists to enforce: the
model never re-emits an observation. A retained product's body is carried
through byte-unchanged from the candidate it came from. Two reasons, both
measured elsewhere in this project rather than assumed here:

- a model cannot reliably copy a long opaque string (ADR-055), and an
  observation is mostly long opaque strings;
- a re-emitted body is a body the model could have altered, silently, in a field
  a human later reads as discovery's finding.

So the model writes ``{"ref": "D3", "action": "retain", ...}`` and this module
assembles the universe from that decision plus the original candidate. The same
discipline ``derive_identity_fields`` applies to identifiers (ADR-054), one
artifact on.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .contents_renderer import (
    CANDIDATE_REF_PATTERN,
    candidate_ref_order,
    canonical_passage_order,
    passage_ref_label,
)
from .errors import ExtractionError
from .raw_artifacts import canonical_json_bytes, write_artifact

__all__ = [
    "CONSOLIDATION_ACTIONS",
    "UNIVERSE_CONTRACT",
    "materialize_consolidated_universe",
    "resolve_candidate_refs",
]

UNIVERSE_CONTRACT = "product_consolidated_universe@0.1.0"

# Closed and exhaustive. ``unresolved`` is a first-class action, not an error
# path: rule 7 says unknown over guess, and a rule the output cannot express is
# a rule the model cannot follow.
CONSOLIDATION_ACTIONS: tuple[str, ...] = (
    "retain",
    "merge_alias",
    "place_family",
    "classify_bundle",
    "exclude",
    "unresolved",
)

# Which link field each action carries, as a closed map rather than a branch --
# the ADR-053/058/061/062/064/071 shape. An action added without an entry here
# fails closed instead of inheriting a neighbour's arm.
_LINK_FIELDS: dict[str, tuple[str, ...]] = {
    "retain": (),
    "merge_alias": ("canonical_ref",),
    "place_family": ("family_ref",),
    "classify_bundle": ("constituent_refs",),
    "exclude": (),
    "unresolved": (),
}

_NOT_DECIDED = "consolidation_candidate_not_decided"
_DECIDED_TWICE = "consolidation_candidate_decided_twice"
_REF_UNRESOLVABLE = "consolidation_ref_unresolvable"
_SELF_LINK = "consolidation_self_link"
_LINK_TARGETS_EXCLUDED = "consolidation_link_targets_excluded"
_QUOTE_UNCONTAINED = "consolidation_evidence_quote_uncontained"


def _link_fields_for(action: str) -> tuple[str, ...]:
    try:
        return _LINK_FIELDS[action]
    except KeyError:
        raise ExtractionError(
            f"no link rule is declared for consolidation action {action!r}",
            reason_code="consolidation_action_rule_missing",
        ) from None


def resolve_candidate_refs(
    decisions: list[Any],
    *,
    packet: dict[str, Any],
) -> list[dict[str, Any]]:
    """Resolve every ``D0N`` label to the candidate it names, or refuse.

    Shares ``candidate_ref_order`` with ``_bind_product_candidates`` so the
    label the model was shown and the label resolved here cannot mean two
    different candidates -- the ``canonical_passage_order`` rule, applied to a
    second family.

    Every check here is about the *candidate set*, which the JSON Schema cannot
    see: exhaustiveness, resolvability, self-links, and links into exclusions.
    Shape is the schema's job and is not repeated.
    """
    ordered = candidate_ref_order(packet)
    by_label = {f"D{ordinal}": entry for ordinal, entry in enumerate(ordered, start=1)}

    if not isinstance(decisions, list):
        raise ExtractionError(
            "consolidation output must be a JSON array",
            reason_code=_REF_UNRESOLVABLE,
        )

    seen: dict[str, int] = {}
    for decision in decisions:
        if not isinstance(decision, dict):
            raise ExtractionError(
                "every consolidation decision must be an object",
                reason_code=_REF_UNRESOLVABLE,
            )
        ref = decision.get("ref")
        if not isinstance(ref, str) or not CANDIDATE_REF_PATTERN.fullmatch(ref):
            raise ExtractionError(
                f"consolidation decision carries an unusable candidate ref: {ref!r}",
                reason_code=_REF_UNRESOLVABLE,
            )
        if ref not in by_label:
            raise ExtractionError(
                f"consolidation decision cites {ref}, which names no candidate "
                f"in this collection",
                reason_code=_REF_UNRESOLVABLE,
            )
        seen[ref] = seen.get(ref, 0) + 1

    # Exhaustive in both directions: one decision per candidate, no more.
    repeated = sorted(ref for ref, count in seen.items() if count > 1)
    if repeated:
        raise ExtractionError(
            f"candidates decided more than once: {repeated}",
            reason_code=_DECIDED_TWICE,
        )
    undecided = sorted(
        (label for label in by_label if label not in seen),
        key=lambda label: int(label[1:]),
    )
    if undecided:
        raise ExtractionError(
            f"candidates with no decision: {undecided}",
            reason_code=_NOT_DECIDED,
        )

    excluded = {
        decision["ref"] for decision in decisions if decision.get("action") == "exclude"
    }

    resolved: list[dict[str, Any]] = []
    for decision in decisions:
        ref = decision["ref"]
        action = decision.get("action")
        if action not in CONSOLIDATION_ACTIONS:
            raise ExtractionError(
                f"unknown consolidation action: {action!r}",
                reason_code="consolidation_action_rule_missing",
            )
        links: dict[str, Any] = {}
        for field in _link_fields_for(action):
            raw = decision.get(field)
            targets = raw if isinstance(raw, list) else [raw]
            resolved_targets: list[dict[str, Any]] = []
            for target in targets:
                if not isinstance(target, str) or target not in by_label:
                    raise ExtractionError(
                        f"{field} on {ref} cites {target!r}, which names no "
                        f"candidate in this collection",
                        reason_code=_REF_UNRESOLVABLE,
                    )
                if target == ref:
                    raise ExtractionError(
                        f"{field} on {ref} points at itself",
                        reason_code=_SELF_LINK,
                    )
                if target in excluded:
                    raise ExtractionError(
                        f"{field} on {ref} points at {target}, which was excluded; "
                        f"a link into an exclusion leaves the universe with a "
                        f"dangling relation",
                        reason_code=_LINK_TARGETS_EXCLUDED,
                    )
                resolved_targets.append(by_label[target])
            links[field] = (
                resolved_targets if isinstance(raw, list) else resolved_targets[0]
            )
        resolved.append(
            {"decision": decision, "candidate": by_label[ref], "links": links}
        )
    return resolved


def _resolve_evidence(
    decision: dict[str, Any], *, packet: dict[str, Any], stage: str
) -> list[dict[str, str]]:
    """Turn ``{"ref": "P3", "quote": ...}`` into a full evidence entry.

    The quote must be contained verbatim in the passage its ``ref`` names --
    ADR-063's C8, applied to a third artifact. A quote assembled from two
    non-adjacent runs reads as one sentence the document never contained.
    """
    ordered = canonical_passage_order(packet)
    by_label = {
        passage_ref_label(ordinal, stage=stage): passage
        for ordinal, passage in enumerate(ordered, start=1)
    }
    out: list[dict[str, str]] = []
    for entry in decision["evidence"]:
        ref = entry.get("ref")
        passage = by_label.get(ref)
        if passage is None:
            raise ExtractionError(
                f"evidence on {decision['ref']} cites {ref!r}, which names no "
                f"passage in this packet",
                reason_code=_REF_UNRESOLVABLE,
            )
        quote = entry.get("quote")
        if not isinstance(quote, str) or quote not in passage["text"]:
            raise ExtractionError(
                f"evidence quote on {decision['ref']} is not contained verbatim "
                f"in passage {ref}",
                reason_code=_QUOTE_UNCONTAINED,
            )
        out.append(
            {
                "source_id": passage["source_id"],
                "passage_id": passage["passage_id"],
                "quote": quote,
            }
        )
    return out


def materialize_consolidated_universe(
    *,
    decisions: list[Any],
    packet: dict[str, Any],
    universe_root: str | Path,
    reference: str,
    candidate_collection_reference: str,
    candidate_collection_sha256: str,
    raw_artifact_reference: str,
    raw_artifact_sha256: str,
    stage: str = "product_consolidation",
) -> dict[str, str]:
    """Assemble and persist the consolidated universe. Write-once.

    Deterministic: nothing here asks the model anything. Each retained
    product's ``observation`` is the candidate's own payload, carried through
    unchanged, and every relation is expressed by ``candidate_id`` rather than
    by label, so the artifact stays readable without the packet that produced
    it.
    """
    resolved = resolve_candidate_refs(decisions, packet=packet)

    retained: list[dict[str, Any]] = []
    aliases: list[dict[str, Any]] = []
    families: list[dict[str, Any]] = []
    bundles: list[dict[str, Any]] = []
    exclusions: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for item in sorted(resolved, key=lambda entry: entry["candidate"]["ordinal"]):
        decision = item["decision"]
        candidate = item["candidate"]
        candidate_id = candidate["candidate_id"]
        evidence = _resolve_evidence(decision, packet=packet, stage=stage)
        reason = decision["reason"]
        action = decision["action"]

        if action == "retain":
            retained.append(
                {
                    "candidate_id": candidate_id,
                    "entity_role": "product",
                    "observation": candidate["payload"],
                    "reason": reason,
                    "evidence": evidence,
                }
            )
        elif action == "classify_bundle":
            retained.append(
                {
                    "candidate_id": candidate_id,
                    "entity_role": decision["bundle_kind"],
                    "observation": candidate["payload"],
                    "reason": reason,
                    "evidence": evidence,
                }
            )
            bundles.append(
                {
                    "candidate_id": candidate_id,
                    "bundle_kind": decision["bundle_kind"],
                    "constituent_candidate_ids": [
                        target["candidate_id"] for target in item["links"]["constituent_refs"]
                    ],
                    "reason": reason,
                    "evidence": evidence,
                }
            )
        elif action == "merge_alias":
            aliases.append(
                {
                    "candidate_id": candidate_id,
                    "canonical_candidate_id": item["links"]["canonical_ref"]["candidate_id"],
                    "reason": reason,
                    "evidence": evidence,
                }
            )
        elif action == "place_family":
            families.append(
                {
                    "candidate_id": candidate_id,
                    "family_candidate_id": item["links"]["family_ref"]["candidate_id"],
                    "reason": reason,
                    "evidence": evidence,
                }
            )
        elif action == "exclude":
            exclusions.append(
                {"candidate_id": candidate_id, "reason": reason, "evidence": evidence}
            )
        else:  # unresolved -- the only remaining member of the closed set
            unresolved.append(
                {
                    "candidate_id": candidate_id,
                    "open_question": decision["open_question"],
                    "reason": reason,
                    "evidence": evidence,
                }
            )

    universe = {
        "contract": UNIVERSE_CONTRACT,
        "schema_version": "0.1.0",
        "company_id": packet["company_id"],
        "observation_cutoff": packet["observation_cutoff_date"],
        "candidate_collection_reference": candidate_collection_reference,
        "candidate_collection_sha256": candidate_collection_sha256,
        "raw_artifact_reference": raw_artifact_reference,
        "raw_artifact_sha256": raw_artifact_sha256,
        "retained": retained,
        "aliases": aliases,
        "families": families,
        "bundles": bundles,
        "exclusions": exclusions,
        "unresolved": unresolved,
        "retained_count": len(retained),
        "excluded_count": len(exclusions),
        "unresolved_count": len(unresolved),
    }
    digest = write_artifact(universe_root, reference, canonical_json_bytes(universe))
    return {"reference": reference, "sha256": digest}


def universe_bytes(universe: dict[str, Any]) -> bytes:
    return canonical_json_bytes(universe)


def load_consolidation_output(raw_text: str) -> list[Any]:
    """Parse the model's array. No repair, no fencing tolerance."""
    try:
        payload = json.loads(raw_text)
    except ValueError as exc:
        raise ExtractionError(
            "consolidation output is not valid JSON",
            reason_code=_REF_UNRESOLVABLE,
        ) from exc
    if not isinstance(payload, list):
        raise ExtractionError(
            "consolidation output must be a JSON array",
            reason_code=_REF_UNRESOLVABLE,
        )
    return payload
