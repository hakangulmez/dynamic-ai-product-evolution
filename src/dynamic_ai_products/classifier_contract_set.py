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

**Why V2.5 exists, and why it is a different kind of successor.** V2.2 through
V2.4 changed how much the model could write or how it was told to write it.
V2.5 changes what it writes at all: the free-text ``quote`` is removed, and the
model instead selects a ``span_ref`` naming sentence units a pinned index
derived from the hash-bound packet, with the pipeline retrieving the text. Three
live calibrations produced ten diagnosed quote failures across five classes --
one dropped invisible U+200B, four small visible copy errors, two splices across
thousands of characters, one correctly copied quote attributed to the wrong
passage, and one quote roughly 45% composed. Four of those five classes are
unreachable when the model never types source characters. The fifth, selecting
the wrong span, survives by design: it yields authentic packet text attached to
a claim, which a human reviewer can adjudicate and which is not fabricated
evidence. ``evidence_protocol`` names which regime a version runs, so the
runner branches on a declared fact rather than on a version-id substring.

**V2.5's rejection is bidirectional and structural**, unlike the 0.2.0-to-0.3.0
widening: a V2.4 response carries ``quote`` and fails the 0.4.0 axes schema as
an unknown property, and a V2.5 response carries ``span_ref`` and fails 0.3.0's
the same way. The route filenames still gate archives and manifests, but here
the contracts alone would already refuse each other.

**Why V2.6 exists, and why it changes nothing the model sees.** The V2.5
calibration sent all forty rows and then could not write its manifest. One row
hit a Vertex quota 429, retried successfully, and ``ScreenBudget`` set
``tokens_out_reported`` to null -- deliberately, because after a retry there is
no verified total -- while ``request_accounting`` admitted integers only. V2.6
widens that one property to integer-or-null in its three manifest contracts and
changes nothing else: the prompt, the span index, the 0.4.0 axes and record
contracts, the taxonomy version, the tier rules and the evidence protocol are
V2.5's own files, reused by reference. Budget enforcement is untouched and
cannot weaken, because nothing reads ``tokens_out_reported``: the ceilings are
enforced against ``tokens_out_accounted``, ``tokens_in_measured`` and
``cost_micros_settled``, and the first of those charges the declared per-call
maximum for exactly the rows whose usage did not verify.

**Successor because a contract moved, not because behaviour did.** V2.6 needs
its own authorization and manifest contracts so a V2.5 grant cannot drive a
V2.6 route and produce a manifest under a different contract, and its own
filenames so no loader can read one version's run as the other's. That is the
same reason V2.3 existed, and the same reason it reused V2.2's schemas.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "CONTRACT_SETS",
    "V2_1",
    "V2_2",
    "V2_3",
    "V2_4",
    "V2_5",
    "V2_6",
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
    #: Which evidence regime this version runs. ``model_quote`` is V2.1 through
    #: V2.4, where the model typed the quote. ``selected_span`` is ADR-132,
    #: where the model selects an identifier and the pipeline retrieves the
    #: text. The runner branches on this rather than on a version id, so a
    #: future version declares its regime instead of being pattern-matched.
    evidence_protocol: str = "model_quote"
    #: The pinned span-index config a ``selected_span`` version renders from.
    #: ``None`` for every ``model_quote`` version, which has no span index.
    span_index_config: str | None = None


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

#: ADR-132. The evidence protocol changes; the economics do not. Every axis,
#: enum value and tier rule is V2_4's, the evidence ceiling stays at 12 objects
#: and ``supported_claim`` at 300 characters. What moves is the evidence item:
#: ``quote`` is gone and ``span_ref`` takes its place, so the axes and record
#: contracts fork to 0.4.0 and ``taxonomy_version`` moves with them. The prompt
#: is a successor because the instruction is now selection rather than copying.
V2_5 = ClassifierContractSet(
    version_id="v2_5",
    prompt_path="prompts/discovery/universe_full_classification.v2_5.md",
    axes_schema="schemas/universe_classifier_axes_record.v4.schema.json",
    axes_contract="universe_classifier_axes_record@0.4.0",
    record_contract="universe_classifier_record@0.4.0",
    record_schema="schemas/universe_classifier_record.v4.schema.json",
    taxonomy_version="universe_classifier_axes_v2_5",
    output_prefix="v2_5_",
    evidence_protocol="selected_span",
    span_index_config="configs/universe_classifier_span_index_v1.yaml",
)

#: ADR-133. A contract-only successor. Every field the model interacts with is
#: V2_5's own: the same prompt file, the same span index, the same 0.4.0 axes
#: and record schema files, the same taxonomy version. ``taxonomy_version``
#: stays ``universe_classifier_axes_v2_5`` because the axes contract genuinely
#: does not change -- the same reasoning that kept V2_3 on the V2.2 taxonomy.
#: What moves lives entirely in the manifest and authorization contracts, which
#: this set does not name; the route does.
V2_6 = ClassifierContractSet(
    version_id="v2_6",
    prompt_path=V2_5.prompt_path,
    axes_schema=V2_5.axes_schema,
    axes_contract=V2_5.axes_contract,
    record_contract=V2_5.record_contract,
    record_schema=V2_5.record_schema,
    taxonomy_version=V2_5.taxonomy_version,
    output_prefix="v2_6_",
    evidence_protocol=V2_5.evidence_protocol,
    span_index_config=V2_5.span_index_config,
)

CONTRACT_SETS: dict[str, ClassifierContractSet] = {
    V2_1.version_id: V2_1,
    V2_2.version_id: V2_2,
    V2_3.version_id: V2_3,
    V2_4.version_id: V2_4,
    V2_5.version_id: V2_5,
    V2_6.version_id: V2_6,
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
