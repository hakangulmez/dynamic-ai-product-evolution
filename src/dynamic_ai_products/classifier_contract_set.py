"""Which prompt, axes and record contract one classifier route runs (ADR-128).

Three routes — base, continuation, calibration — now exist at two contract
versions. What separates V2.1 from V2.2 is not logic but a triple: which prompt
bytes the model sees, which axes contract its output is validated against, and
which record contract the stored row declares. Naming that triple once, here,
keeps the preflight, the governed loop and the reconciliation single across six
route/version combinations. A forked runner per version is exactly where two
versions would drift apart while both claiming to be the classifier.

**Why V2.2 exists.** The first calibration stopped after three rows. All three
responses were valid JSON carrying valid axes, and all three were refused on
output size alone: ``evidence`` capped at 6 against a six-value axis vocabulary
that leaves no headroom, and ``quote`` capped at 300 characters against
legitimate contiguous Item 1 spans reaching 972. V2.2 raises those two ceilings
to 12 and 1200 and restates every bound in the prompt's final self-check.

**The economic taxonomy did not change.** Every axis, every enum value and the
tier rules are byte-identical to V2.1. ``taxonomy_version`` moves to
``universe_classifier_axes_v2_2`` because it names the axes *contract* a run was
validated against, which is what a later reader needs in order to interpret a
stored record; it does not denote a change in what the axes mean.

**V2.1 is frozen, not superseded in place.** Its prompt, schemas and contracts
stay byte-identical, so the evidence a V2.1 run archived remains interpretable
under the contract that run actually used.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CONTRACT_SETS",
    "V2_1",
    "V2_2",
    "ClassifierContractSet",
    "contract_set_for",
]


@dataclass(frozen=True)
class ClassifierContractSet:
    """One classifier contract version: prompt, axes, record, taxonomy."""

    version_id: str
    prompt_path: str
    axes_schema: str
    axes_contract: str
    record_contract: str
    record_schema: str
    taxonomy_version: str
    #: Prefix distinguishing this version's output filenames on disk. Empty for
    #: V2.1, whose filenames were established before a second version existed
    #: and must not move.
    output_prefix: str


V2_1 = ClassifierContractSet(
    version_id="v2_1",
    prompt_path="prompts/discovery/universe_full_classification.v2_1.md",
    axes_schema="schemas/universe_classifier_axes_record.schema.json",
    axes_contract="universe_classifier_axes_record@0.1.0",
    record_contract="universe_classifier_record@0.1.0",
    record_schema="schemas/universe_classifier_record.schema.json",
    taxonomy_version="universe_classifier_axes_v2_1",
    output_prefix="",
)

V2_2 = ClassifierContractSet(
    version_id="v2_2",
    prompt_path="prompts/discovery/universe_full_classification.v2_2.md",
    axes_schema="schemas/universe_classifier_axes_record.v2.schema.json",
    axes_contract="universe_classifier_axes_record@0.2.0",
    record_contract="universe_classifier_record@0.2.0",
    record_schema="schemas/universe_classifier_record.v2.schema.json",
    taxonomy_version="universe_classifier_axes_v2_2",
    output_prefix="v2_2_",
)

CONTRACT_SETS: dict[str, ClassifierContractSet] = {
    V2_1.version_id: V2_1,
    V2_2.version_id: V2_2,
}


def contract_set_for(version_id: str) -> ClassifierContractSet:
    """Resolve one contract version by id, refusing anything unknown."""
    try:
        return CONTRACT_SETS[version_id]
    except KeyError:
        raise ValueError(
            f"Unknown classifier contract version {version_id!r}; the known "
            f"versions are {sorted(CONTRACT_SETS)}."
        ) from None
