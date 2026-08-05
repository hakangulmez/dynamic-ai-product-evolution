"""The product-candidate availability vocabulary (ADR-052, G6-V).

``availability_status`` is an unconstrained string in
``schemas/product_observation.schema.json``. Measured: ``{"type": "string"}``,
nothing more. So the question "may this status enter a candidate record" has no
answer anywhere in the schema layer, and until this module existed it had no
answer anywhere else either. This artifact is that answer, and it is a
**candidate-admission vocabulary** for the ``product_extraction`` stage -- not
the Rule-10 evaluator classification that ADR-028 governs. The two are separate
contracts with separate consumers; neither is derived from the other, and they
are not required to carry the same tokens. SPEC-023's Rule-10 paragraph records
that boundary in prose so a later reader cannot merge them by accident.

**The taxonomy is pinned, not known.** The contract does not behave as though it
remembers the ontology; it carries where it read it from:
``availability_taxonomy_reference`` plus ``availability_taxonomy_sha256``, bound
to the canonical bytes of ``docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md``
through the same containment-and-digest loader every governance artifact uses.
If the ontology text changes, an existing artifact stops validating and a new one
must be minted. The taxonomy cannot drift underneath a live vocabulary.

**What the pin does not do, stated exactly.** Nothing here parses the ontology.
:data:`CANONICAL_AVAILABILITY_STATUS_VALUES` is code-owned and reviewed, exactly
like the budget meter identity in ADR-047 and ``ROUTING_CONTRACT_ID`` in
ADR-048. The pin proves *which taxonomy text* an artifact was minted against; it
does not prove that the eight tokens below were extracted from that text. That
binding is a review obligation, and claiming otherwise would be the ambient
reading this design rejects. The honest guarantee is narrower than "the code
reads the ontology" and stronger than "somebody checked once": the text cannot
change without invalidating every artifact pinned to it.

**Exact set, not subset.** ``admitted_status_values`` is the canonical eight --
no fewer, no more. Two independent layers enforce it: the schema pins
``minItems == maxItems == 8`` over a closed ``enum``, and :func:`L2
<validate_availability_vocabulary>` compares the tuple. Adding or removing a
token under ``@0.1.0`` is therefore impossible; it requires a contract
successor. ``planned``, which is absent from the ontology and from
``docs/SOURCE_POLICY.md``, cannot enter any list of any artifact.

**The four partition lists carry the only human decision.** Which tokens are
admitted is settled by the taxonomy. What each admitted token *means* for
candidate admission -- active, roadmap, non-active-known, unknown -- is a
methodology judgement, and the artifact records who made it and when.
``unknown_status_values`` is the one exception: it is fixed at exactly
``["unknown"]`` (L6), because CLAUDE.md rule 7 makes insufficient evidence a
result to be carried rather than a category to be reassigned. An ``unknown``
candidate is admitted and its disposition is left to human review.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .errors import ExtractionError
from .input_packet import hydrate_pinned_artifact, hydrate_pinned_bytes
from .manifests import _require_aware_instant, _require_exact_properties
from .raw_artifacts import canonical_json_bytes, sha256_bytes, write_artifact

__all__ = [
    "AVAILABILITY_PARTITION_FIELDS",
    "AVAILABILITY_TAXONOMY_REFERENCE",
    "AVAILABILITY_VOCABULARY_CONTRACT",
    "AVAILABILITY_VOCABULARY_REFERENCE",
    "AVAILABILITY_VOCABULARY_SCHEMA_VERSION",
    "AVAILABILITY_VOCABULARY_STAGE",
    "CANONICAL_AVAILABILITY_STATUS_VALUES",
    "STATUS_LABEL_PATTERN",
    "build_availability_vocabulary",
    "derive_availability_taxonomy_pin",
    "materialize_availability_vocabulary",
    "parse_prompt_status_vocabulary",
    "resolve_status_label",
    "status_label",
    "status_label_table",
    "validate_availability_vocabulary",
    "validate_prompt_vocabulary_binding",
]

AVAILABILITY_VOCABULARY_CONTRACT = "product_candidate_availability_vocabulary@0.1.0"
AVAILABILITY_VOCABULARY_SCHEMA_VERSION = "0.1.0"
AVAILABILITY_VOCABULARY_STAGE = "product_extraction"

# The canonical taxonomy text. Repo-root-relative POSIX, resolved through the
# shared loader, never opened directly.
AVAILABILITY_TAXONOMY_REFERENCE = (
    "docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md"
)

# The artifact's place inside its own attempt root.
AVAILABILITY_VOCABULARY_REFERENCE = (
    "vocabulary/product_candidate_availability_vocabulary.json"
)

# The eight states of ``docs/methodology/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md``,
# ascending. Code-owned and reviewed; see the module docstring for what the
# taxonomy pin does and does not prove about this tuple.
CANONICAL_AVAILABILITY_STATUS_VALUES = (
    "announced",
    "broadly_deployed_or_default",
    "deprecated",
    "discontinued",
    "general_availability",
    "private_beta",
    "public_beta",
    "unknown",
)

# ADR-056. A short label per canonical status, derived from the tuple above.
#
# Measured on ``ext-smoke-0005``: fourteen of fifteen candidates wrote
# ``broadly_deployed_or_default`` correctly and one wrote
# ``broadly_deployed_or_or_default`` -- the syllable ``or`` doubled. That is the
# same fault that corrupted a ``passage_id`` twice before ADR-055: copying a
# long, internally repetitive string. So the model is no longer asked to copy
# this one either.
#
# The ordinal comes from ``CANONICAL_AVAILABILITY_STATUS_VALUES`` itself, not
# from a second list. Inventing an ordering here would be the defect ADR-055
# closed structurally for passages: one rule, one owner.
STATUS_LABEL_PATTERN = re.compile(r"^S(\d+)$")


def status_label(ordinal: int) -> str:
    """The label for a one-based position in the canonical status tuple."""
    return f"S{ordinal}"


def status_label_table() -> tuple[tuple[str, str], ...]:
    """``(label, token)`` for every admitted status, in canonical order.

    The prompt renders this table and the resolver reads it, both from here, so
    a label cannot mean one status in the instruction and another in the code.
    """
    return tuple(
        (status_label(ordinal), token)
        for ordinal, token in enumerate(CANONICAL_AVAILABILITY_STATUS_VALUES, start=1)
    )


def resolve_status_label(label: Any) -> str:
    """Turn ``S2`` into the status it names, or refuse.

    Strict on purpose: a real token is **not** accepted here. Accepting both
    spellings would let a run mix two conventions, and the whole point of the
    label is that the long token is never transcribed. A model that emits the
    token instead has not followed the contract, and that should be loud.
    """
    match = STATUS_LABEL_PATTERN.fullmatch(label) if isinstance(label, str) else None
    if match is None:
        raise ExtractionError(
            f"availability_status must be a status label such as 'S1'; got {label!r}",
            reason_code=_STATUS_LABEL_UNRESOLVABLE,
        )
    ordinal = int(match.group(1))
    if not 1 <= ordinal <= len(CANONICAL_AVAILABILITY_STATUS_VALUES):
        raise ExtractionError(
            f"availability_status cites {label!r}, but only "
            f"{len(CANONICAL_AVAILABILITY_STATUS_VALUES)} statuses exist",
            reason_code=_STATUS_LABEL_UNRESOLVABLE,
        )
    return CANONICAL_AVAILABILITY_STATUS_VALUES[ordinal - 1]


# Ascending, so that iteration order in the partition checks is the order a
# reader sees in the artifact and in every error message.
AVAILABILITY_PARTITION_FIELDS = (
    "active_status_values",
    "non_active_known_status_values",
    "roadmap_status_values",
    "unknown_status_values",
)

_VOCABULARY_PROPERTIES = frozenset(
    {
        "active_status_values",
        "admitted_status_values",
        "availability_taxonomy_reference",
        "availability_taxonomy_sha256",
        "contract",
        "decided_at",
        "decided_by",
        "non_active_known_status_values",
        "roadmap_status_values",
        "schema_version",
        "stage",
        "unknown_status_values",
        "vocabulary_version",
    }
)

_TOKEN_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

_INPUT_INVALID = "vocabulary_input_invalid"
_NOT_ASCENDING = "vocabulary_not_ascending"
_NOT_CANONICAL_SET = "vocabulary_not_canonical_set"
_PARTITION_INCOMPLETE = "vocabulary_partition_incomplete"
_PARTITION_OVERLAPPING = "vocabulary_partition_overlapping"
_LIST_INVALID = "vocabulary_list_invalid"
_UNKNOWN_MISPLACED = "vocabulary_unknown_misplaced"
_TAXONOMY_PIN_MISMATCH = "availability_taxonomy_pin_mismatch"
# ADR-056. Separate from the C5 code for the same reason ADR-055 kept its ref
# code separate: "named a status outside the vocabulary" and "gave something
# that is not a label at all" are different faults with different fixes.
_STATUS_LABEL_UNRESOLVABLE = "candidate_conformance_status_label_unresolvable"

# L6 is a constant, not a parameter: ``unknown`` has exactly one admissible
# placement and no operator may move it.
_UNKNOWN_STATUS_VALUES = ("unknown",)


def _require_token_list(value: Any, *, field: str) -> tuple[str, ...]:
    """L5 for one list: non-empty, well-formed tokens, ascending, duplicate-free.

    Ordering is checked against ``sorted`` rather than pairwise so that a list
    which is unordered *and* duplicated reports one defect, not a sequence of
    them. Uniqueness is checked separately because ``sorted`` equality alone
    would accept ``["a", "a"]``.
    """
    if not isinstance(value, list):
        raise ExtractionError(
            f"{field} must be a list of status tokens", reason_code=_LIST_INVALID
        )
    if not value:
        raise ExtractionError(
            f"{field} must not be empty", reason_code=_LIST_INVALID
        )
    for item in value:
        if not isinstance(item, str) or not _TOKEN_PATTERN.fullmatch(item):
            raise ExtractionError(
                f"{field} carries a token that is not lowercase snake_case: "
                f"{item!r}",
                reason_code=_LIST_INVALID,
            )
    if len(set(value)) != len(value):
        raise ExtractionError(
            f"{field} repeats a status token", reason_code=_LIST_INVALID
        )
    if list(value) != sorted(value):
        raise ExtractionError(
            f"{field} must be ascending", reason_code=_NOT_ASCENDING
        )
    return tuple(value)


def derive_availability_taxonomy_pin(*, repo_root: str | Path) -> dict[str, str]:
    """Read the canonical taxonomy text and return its reference and digest.

    Deterministic apart from the one read it exists to perform: no clock, no
    network, no environment, no credential. The digest is taken over the file's
    literal bytes, so a whitespace-only edit to the ontology invalidates every
    artifact pinned to the previous text -- which is the intent, not a
    side effect.
    """
    target = Path(repo_root) / AVAILABILITY_TAXONOMY_REFERENCE
    try:
        payload = target.read_bytes()
    except OSError as exc:
        raise ExtractionError(
            f"the canonical availability taxonomy is unreadable: {target}",
            reason_code=_TAXONOMY_PIN_MISMATCH,
        ) from exc
    return {
        "reference": AVAILABILITY_TAXONOMY_REFERENCE,
        "sha256": sha256_bytes(payload),
    }


def build_availability_vocabulary(
    *,
    vocabulary_version: str,
    active_status_values: list[str],
    roadmap_status_values: list[str],
    non_active_known_status_values: list[str],
    decided_by: str,
    decided_at: str,
    repo_root: str | Path,
) -> dict[str, Any]:
    """Assemble one vocabulary document and validate it before returning it.

    ``unknown_status_values`` is **not** a parameter. L6 fixes it at exactly
    ``["unknown"]``, and a parameter a caller cannot legally vary is a parameter
    that invites the illusion of choice; leaving it out makes the constraint
    structural instead of merely checked.

    ``admitted_status_values`` is likewise not a parameter: it is the canonical
    eight, and passing it separately would create a second place for the same
    fact to live. What the caller supplies is the partition and the human
    attribution, which is exactly the decision this artifact records.

    The returned document has already passed :func:`validate_availability_vocabulary`,
    so a build that returns at all is a document that a loader will accept.
    """
    document = {
        "active_status_values": list(active_status_values)
        if isinstance(active_status_values, list)
        else active_status_values,
        "admitted_status_values": list(CANONICAL_AVAILABILITY_STATUS_VALUES),
        "availability_taxonomy_reference": AVAILABILITY_TAXONOMY_REFERENCE,
        "availability_taxonomy_sha256": derive_availability_taxonomy_pin(
            repo_root=repo_root
        )["sha256"],
        "contract": AVAILABILITY_VOCABULARY_CONTRACT,
        "decided_at": decided_at,
        "decided_by": decided_by,
        "non_active_known_status_values": list(non_active_known_status_values)
        if isinstance(non_active_known_status_values, list)
        else non_active_known_status_values,
        "roadmap_status_values": list(roadmap_status_values)
        if isinstance(roadmap_status_values, list)
        else roadmap_status_values,
        "schema_version": AVAILABILITY_VOCABULARY_SCHEMA_VERSION,
        "stage": AVAILABILITY_VOCABULARY_STAGE,
        "unknown_status_values": list(_UNKNOWN_STATUS_VALUES),
        "vocabulary_version": vocabulary_version,
    }
    return validate_availability_vocabulary(document, repo_root=repo_root)


def validate_availability_vocabulary(
    document: Any, *, repo_root: str | Path
) -> dict[str, Any]:
    """The seven loader checks the JSON schema cannot express (L1 through L7).

    The schema and this function overlap deliberately on the exact-eight
    constraint: a closed ``enum`` with ``minItems == maxItems == 8`` there, an
    ordered tuple comparison here. Redundancy between two layers that fail for
    different reasons is the point -- an artifact that reached this function
    without schema validation is still refused.

    Returns a fresh outer mapping. The list objects inside it are the caller's
    own; nothing here mutates them, and nothing downstream should.
    """
    payload = _require_exact_properties(
        document,
        _VOCABULARY_PROPERTIES,
        what="availability vocabulary",
        code=_INPUT_INVALID,
    )

    for field, expected in (
        ("contract", AVAILABILITY_VOCABULARY_CONTRACT),
        ("schema_version", AVAILABILITY_VOCABULARY_SCHEMA_VERSION),
        ("stage", AVAILABILITY_VOCABULARY_STAGE),
    ):
        if payload[field] != expected:
            raise ExtractionError(
                f"availability vocabulary {field} must be {expected!r}",
                reason_code=_INPUT_INVALID,
            )

    for field in ("vocabulary_version", "decided_by"):
        value = payload[field]
        if not isinstance(value, str) or not value.strip():
            raise ExtractionError(
                f"availability vocabulary {field} must be a non-blank string",
                reason_code=_INPUT_INVALID,
            )

    # Parsed, not stored: the artifact keeps the operator's own spelling, and a
    # naive instant is refused rather than assumed to be UTC.
    _require_aware_instant(
        payload["decided_at"], field="decided_at", code=_INPUT_INVALID
    )

    # L1 and L5 for the admitted list, then L2 as an ordered tuple comparison.
    admitted = _require_token_list(
        payload["admitted_status_values"], field="admitted_status_values"
    )
    if admitted != CANONICAL_AVAILABILITY_STATUS_VALUES:
        raise ExtractionError(
            "admitted_status_values must be the canonical availability taxonomy "
            "exactly; adding or removing a token requires a contract successor",
            reason_code=_NOT_CANONICAL_SET,
        )

    # L1 and L5 for each partition list.
    partitions = {
        field: _require_token_list(payload[field], field=field)
        for field in AVAILABILITY_PARTITION_FIELDS
    }

    # L6 before L3/L4: a misplaced ``unknown`` has its own reason code, and
    # reporting it as a partition defect would tell the operator less.
    if partitions["unknown_status_values"] != _UNKNOWN_STATUS_VALUES:
        raise ExtractionError(
            "unknown_status_values must be exactly ['unknown']; an unknown "
            "status is carried, never reclassified",
            reason_code=_UNKNOWN_MISPLACED,
        )

    # L4 before L3: an overlap also inflates the union, so checking completeness
    # first would report the wrong defect for a token that appears twice.
    for index, first in enumerate(AVAILABILITY_PARTITION_FIELDS):
        for second in AVAILABILITY_PARTITION_FIELDS[index + 1 :]:
            shared = sorted(set(partitions[first]) & set(partitions[second]))
            if shared:
                raise ExtractionError(
                    f"{first} and {second} both carry {shared}; the four "
                    "partition lists must be pairwise disjoint",
                    reason_code=_PARTITION_OVERLAPPING,
                )

    # L3.
    union = set().union(*(set(values) for values in partitions.values()))
    if union != set(admitted):
        missing = sorted(set(admitted) - union)
        extra = sorted(union - set(admitted))
        raise ExtractionError(
            "the four partition lists must cover admitted_status_values exactly "
            f"(missing={missing}, extra={extra})",
            reason_code=_PARTITION_INCOMPLETE,
        )

    # L7. The shared loader owns the relative-reference rules -- absolute
    # refusal, drive-qualified refusal, upward traversal, symlink, escape --
    # and the digest comparison, so this module adds no second set of them.
    hydrate_pinned_bytes(
        repo_root,
        {
            "reference": payload["availability_taxonomy_reference"],
            "sha256": payload["availability_taxonomy_sha256"],
        },
        what="availability taxonomy",
        unsafe_code=_TAXONOMY_PIN_MISMATCH,
        sha_code=_TAXONOMY_PIN_MISMATCH,
    )
    if payload["availability_taxonomy_reference"] != AVAILABILITY_TAXONOMY_REFERENCE:
        raise ExtractionError(
            "the availability taxonomy pin must reference "
            f"{AVAILABILITY_TAXONOMY_REFERENCE}",
            reason_code=_TAXONOMY_PIN_MISMATCH,
        )

    return payload


def materialize_availability_vocabulary(
    document: dict[str, Any], *, attempt_root: str | Path, repo_root: str | Path
) -> dict[str, str]:
    """Write the vocabulary write-once, re-read it, re-validate it, return its pin.

    The document is validated **before** the write and again **after** it, and
    the second validation runs over bytes hydrated from disk rather than over
    the mapping that was passed in. What is certified is therefore what was
    persisted, not what was intended -- the same discipline
    ``materialize_governance_records`` follows for the governance chain.

    ``attempt_root`` must already exist, be a real directory, and be completely
    empty. Creating it is an explicit operator step so that "who made this root
    and when" has an answer outside the code, and a retry uses a new root
    (``-0002``) rather than writing beside a failed attempt's remains.
    """
    validated = validate_availability_vocabulary(document, repo_root=repo_root)
    root = _require_attempt_root(attempt_root)

    payload = canonical_json_bytes(validated)
    digest = write_artifact(root, AVAILABILITY_VOCABULARY_REFERENCE, payload)

    pin = {"reference": AVAILABILITY_VOCABULARY_REFERENCE, "sha256": digest}
    hydrated = hydrate_pinned_artifact(
        root,
        pin,
        what="availability vocabulary",
        unsafe_code=_INPUT_INVALID,
        sha_code=_INPUT_INVALID,
    )
    validate_availability_vocabulary(hydrated, repo_root=repo_root)
    return pin


# --- the prompt-side copy, and proving it has not drifted (ADR-053, G6-P) ----
#
# The renderer binds exactly ``company_name``, ``cutoff`` and
# ``passages_with_ids`` for ``product_extraction``, and refuses any other
# placeholder with ``contents_placeholder_unbound``. A ``{{allowed_statuses}}``
# marker is therefore not executable without widening the renderer, so the
# successor prompt carries the vocabulary as **literal text**. That creates a
# copy, and a copy can drift; these two functions exist to make the drift
# mechanically detectable rather than a thing a reviewer has to notice.

_PROMPT_BLOCK_FENCE = "```"
_PROMPT_LABEL_RE = re.compile(r"^(?P<label>[a-z][a-z0-9_]*)\s*:\s*(?P<rest>.*)$")

_PROMPT_BLOCK_INVALID = "prompt_vocabulary_block_invalid"
_PROMPT_BINDING_MISMATCH = "prompt_vocabulary_binding_mismatch"

# The order the labels appear in the prompt's canonical block. Deliberately
# **not** ``AVAILABILITY_PARTITION_FIELDS``: that tuple is alphabetical so the
# loader's partition checks iterate deterministically, while this one is the
# reviewed presentation order a reader of the prompt sees -- admitted classes
# from most to least available. Conflating the two would make the parser demand
# an ordering the authored prompt does not use.
_PROMPT_BLOCK_LABEL_ORDER = (
    "active_status_values",
    "roadmap_status_values",
    "non_active_known_status_values",
    "unknown_status_values",
)

# The sub-check identifiers, named explicitly rather than positionally: the
# partition tuple is alphabetical and the B4 labels are not, so pairing them by
# index would be correct today and silently wrong after any reordering.
_B4_CHECK_IDS = {
    "active_status_values": "B4a",
    "roadmap_status_values": "B4b",
    "non_active_known_status_values": "B4c",
    "unknown_status_values": "B4d",
}


def _fenced_blocks(text: str) -> list[list[str]]:
    """Every fenced block's lines, fences excluded. No markdown library."""
    blocks: list[list[str]] = []
    current: list[str] | None = None
    for line in text.splitlines():
        if line.lstrip().startswith(_PROMPT_BLOCK_FENCE):
            if current is None:
                current = []
            else:
                blocks.append(current)
                current = None
            continue
        if current is not None:
            current.append(line)
    # An unterminated fence yields no block rather than a truncated one.
    return blocks


def parse_prompt_status_vocabulary(prompt_text: Any) -> dict[str, list[str]]:
    """Extract the four labelled status lists from a prompt's canonical block.

    Deterministic by construction, which is the whole requirement: the values
    live in exactly one fenced block, each label opens a field at column zero,
    and an indented line with no label continues the field above it. Values
    scattered through prose could not be recovered reliably, so they are not
    permitted to be.

    The labels also appear in the surrounding prose -- the prompt explains what
    ``active_status_values`` means -- so scoping to the fenced block is not a
    convenience. A document-wide scan would read the explanation as data.
    """
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise ExtractionError(
            "prompt text is required to parse the status vocabulary",
            reason_code=_PROMPT_BLOCK_INVALID,
        )

    expected = list(_PROMPT_BLOCK_LABEL_ORDER)
    candidates = [
        block
        for block in _fenced_blocks(prompt_text)
        if all(
            any(_PROMPT_LABEL_RE.match(line) and line.startswith(f"{label}") for line in block)
            for label in expected
        )
    ]
    if len(candidates) != 1:
        raise ExtractionError(
            "the prompt must carry exactly one fenced block holding all four "
            f"status labels; found {len(candidates)}",
            reason_code=_PROMPT_BLOCK_INVALID,
        )

    order: list[str] = []
    raw: dict[str, str] = {}
    current: str | None = None
    for line in candidates[0]:
        if not line.strip():
            continue
        match = _PROMPT_LABEL_RE.match(line)
        if match and not line[0].isspace():
            label = match.group("label")
            if label in raw:
                raise ExtractionError(
                    f"the prompt repeats the status label {label!r}",
                    reason_code=_PROMPT_BLOCK_INVALID,
                )
            order.append(label)
            raw[label] = match.group("rest")
            current = label
            continue
        if current is None:
            raise ExtractionError(
                f"the prompt block opens with an unlabelled line: {line!r}",
                reason_code=_PROMPT_BLOCK_INVALID,
            )
        raw[current] = f"{raw[current]} {line.strip()}"

    if order != expected:
        raise ExtractionError(
            f"the prompt must carry exactly the labels {expected} in that order; "
            f"found {order}",
            reason_code=_PROMPT_BLOCK_INVALID,
        )

    parsed: dict[str, list[str]] = {}
    for label in expected:
        tokens = [token.strip() for token in raw[label].split(",")]
        tokens = [token for token in tokens if token]
        if not tokens:
            raise ExtractionError(
                f"the prompt declares no tokens for {label}",
                reason_code=_PROMPT_BLOCK_INVALID,
            )
        for token in tokens:
            if not _TOKEN_PATTERN.fullmatch(token):
                raise ExtractionError(
                    f"the prompt declares a malformed status token under "
                    f"{label}: {token!r}",
                    reason_code=_PROMPT_BLOCK_INVALID,
                )
        parsed[label] = tokens
    return parsed


def validate_prompt_vocabulary_binding(
    *, prompt_text: str, vocabulary: dict[str, Any]
) -> dict[str, list[str]]:
    """B4a through B4e: four ordered list equalities, then the ordered union.

    **Ordered**, not set equality, and that distinction is the reason this
    function exists. If ``active`` and ``roadmap`` swapped labels, every set
    comparison would still pass and the union would be unchanged -- the model
    would be told that an announcement is shipped and that a shipped product is
    an announcement, and nothing would refuse. Comparing position by position
    makes a label swap fail two of the four checks.

    B4e is not redundant with B4a-d. The four lists could each match the
    artifact's corresponding list while the artifact's own ``admitted`` field
    disagreed with their union; that document is internally inconsistent and the
    loader would refuse it, but this function is also used on documents the
    loader has not seen.

    Pure: no file is opened, no prompt is resolved, and the authority is the
    artifact. The prompt's literal text is what the model is shown; it is never
    what a downstream check trusts.
    """
    parsed = parse_prompt_status_vocabulary(prompt_text)

    for label in AVAILABILITY_PARTITION_FIELDS:
        check = _B4_CHECK_IDS[label]
        expected = vocabulary.get(label)
        if parsed[label] != expected:
            raise ExtractionError(
                f"{check}: the prompt's {label} does not match the vocabulary "
                f"artifact (prompt={parsed[label]}, artifact={expected})",
                reason_code=_PROMPT_BINDING_MISMATCH,
            )

    union = sorted(token for tokens in parsed.values() for token in tokens)
    admitted = vocabulary.get("admitted_status_values")
    if union != admitted:
        raise ExtractionError(
            "B4e: the ordered union of the prompt's four lists does not match "
            f"admitted_status_values (union={union}, artifact={admitted})",
            reason_code=_PROMPT_BINDING_MISMATCH,
        )
    return parsed


def _require_attempt_root(attempt_root: str | Path) -> Path:
    """Accept only an existing, real, non-symlink, completely empty directory.

    ``os.listdir`` returns dotfiles and never returns ``.`` or ``..``, so the
    emptiness test is exact: a stray ``.gitkeep`` disqualifies a root, which is
    correct, because a root someone has already touched is a root whose history
    this code cannot vouch for.
    """
    root = Path(attempt_root)
    if root.is_symlink():
        raise ExtractionError(
            f"vocabulary attempt root must not be a symlink: {root}",
            reason_code=_INPUT_INVALID,
        )
    if not root.exists():
        raise ExtractionError(
            f"vocabulary attempt root does not exist: {root}; creating it is an "
            "explicit operator step, not a side effect of materialization",
            reason_code=_INPUT_INVALID,
        )
    if not root.is_dir():
        raise ExtractionError(
            f"vocabulary attempt root must be a directory: {root}",
            reason_code=_INPUT_INVALID,
        )
    try:
        entries = list(root.iterdir())
    except OSError as exc:
        raise ExtractionError(
            f"vocabulary attempt root is unreadable: {root}",
            reason_code=_INPUT_INVALID,
        ) from exc
    if entries:
        raise ExtractionError(
            f"vocabulary attempt root is not empty: {root}; a retry uses a new "
            "attempt root and never reuses a partial one",
            reason_code="destination_exists",
        )
    return root
