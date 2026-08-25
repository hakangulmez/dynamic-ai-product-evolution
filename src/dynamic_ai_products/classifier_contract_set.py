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
under the contract that run actually used. V2.2 is frozen the same way.

**Not every successor is a contract change.** V2.3 shares V2.2's axes and
record contracts exactly, because what failed in the V2.2 calibration was
model discipline rather than a ceiling: excess evidence objects, quotes written
instead of copied, and output field names used as ``evidence.axis`` labels. A
third ceiling increase would have rescued one row of three. So V2.3 moves only
the prompt, and carries new authorization and manifest contracts solely because
the prompt path is pinned as a const in each of them.

**Why V2.4 exists.** The V2.3 calibration stopped after three rows, and every
one of the three carried exactly one schema error: a ``supported_claim`` of
233, 204 and 204 characters against a 200-character cap. Quote lengths (972,
829, 994) and evidence counts (12, 12, 8) were inside the 0.2.0 ceilings, and
all 32 evidence objects carried legal axis labels, so the V2.3 discipline did
take hold where it was aimed. V2.4 therefore moves exactly one bound --
``supported_claim`` to 300 -- and changes the instruction for the two defects a
bound cannot fix: two of the three rows also wrote a quote that did not resolve
verbatim, one splicing two real spans with an ellipsis and one prepending a
subject the passage does not carry. Because the axes contract moves, the record
contract that inlines it moves with it, and ``taxonomy_version`` becomes
``universe_classifier_axes_v2_4``.

**0.3.0 is a widening, so route binding is what separates versions.** Every
valid 0.2.0 axes object is a valid 0.3.0 one. Schema validity therefore cannot
tell a V2.3 output from a V2.4 one, and nothing in this package relies on it:
the separation is the route's output filenames plus the ``prompt_template_path``
and ``output_contract`` consts, both of which reject in either direction.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CONTRACT_SETS",
    "V2_1",
    "V2_2",
    "V2_3",
    "V2_4",
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

#: ADR-129. A prompt-discipline successor, and nothing else: the axes and
#: record contracts, the taxonomy version, the tier rules and the 12/1200
#: ceilings are all V2_2's, byte for byte. The V2.2 calibration stopped with
#: three of four rows rejected, and none of the three was a bound the schema
#: could fix -- the model over-cited, wrote quotes instead of copying them, and
#: put output field names in ``evidence.axis``. Those are instruction failures,
#: so V2.3 changes the instruction and leaves the contract alone. It still
#: needs its own authorization and manifest contracts because
#: ``prompt_template_path`` is a const, and its own output filenames so no
#: loader can read a V2.3 run as a V2.2 one.
V2_3 = ClassifierContractSet(
    version_id="v2_3",
    prompt_path="prompts/discovery/universe_full_classification.v2_3.md",
    axes_schema=V2_2.axes_schema,
    axes_contract=V2_2.axes_contract,
    record_contract=V2_2.record_contract,
    record_schema=V2_2.record_schema,
    taxonomy_version=V2_2.taxonomy_version,
    output_prefix="v2_3_",
)

#: ADR-130. A one-bound successor plus a prompt successor. ``supported_claim``
#: rises from 200 to 300 characters and nothing else about the axes moves:
#: ``evidence`` stays at 12 objects and ``quote`` at 1200 characters, and every
#: enum, pattern and required field is byte-equivalent to V2_2's. Because the
#: axes contract changes, the record contract that inlines it changes too, and
#: ``taxonomy_version`` moves to name the axes contract a stored row was
#: validated against. The prompt additionally forbids any character
#: modification inside a quote and requires a per-axis evidence count; those are
#: instruction rules, not contract bounds, so they leave the schema alone.
V2_4 = ClassifierContractSet(
    version_id="v2_4",
    prompt_path="prompts/discovery/universe_full_classification.v2_4.md",
    axes_schema="schemas/universe_classifier_axes_record.v3.schema.json",
    axes_contract="universe_classifier_axes_record@0.3.0",
    record_contract="universe_classifier_record@0.3.0",
    record_schema="schemas/universe_classifier_record.v3.schema.json",
    taxonomy_version="universe_classifier_axes_v2_4",
    output_prefix="v2_4_",
)

CONTRACT_SETS: dict[str, ClassifierContractSet] = {
    V2_1.version_id: V2_1,
    V2_2.version_id: V2_2,
    V2_3.version_id: V2_3,
    V2_4.version_id: V2_4,
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
