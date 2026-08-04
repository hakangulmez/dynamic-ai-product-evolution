"""The product-candidate availability vocabulary (ADR-052, G6-V).

Two layers guard the same eight tokens and they are tested as two layers: the
JSON schema through ``Draft202012Validator``, the loader through its seven
checks. A test that only exercised one of them would pass while the other
silently drifted, which is the failure this contract exists to prevent.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.availability_vocabulary import (
    AVAILABILITY_PARTITION_FIELDS,
    AVAILABILITY_TAXONOMY_REFERENCE,
    AVAILABILITY_VOCABULARY_CONTRACT,
    AVAILABILITY_VOCABULARY_REFERENCE,
    AVAILABILITY_VOCABULARY_SCHEMA_VERSION,
    AVAILABILITY_VOCABULARY_STAGE,
    CANONICAL_AVAILABILITY_STATUS_VALUES,
    build_availability_vocabulary,
    derive_availability_taxonomy_pin,
    materialize_availability_vocabulary,
    validate_availability_vocabulary,
)
from dynamic_ai_products.extraction.errors import ExtractionError

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas" / "product_candidate_availability_vocabulary.schema.json"

# The human decision this artifact records, exactly as it was locked. "Active"
# is the candidate-admission class of availability-supported, non-roadmap-only
# statuses; it is not automatic human acceptance, not a complete product
# universe, and not a deployed-task finding.
LOCKED_VOCABULARY_VERSION = "product-candidate-availability-v1"
LOCKED_ACTIVE = [
    "broadly_deployed_or_default",
    "general_availability",
    "private_beta",
    "public_beta",
]
LOCKED_ROADMAP = ["announced"]
LOCKED_NON_ACTIVE_KNOWN = ["deprecated", "discontinued"]

DECIDED_BY = "research lead"
DECIDED_AT = "2026-08-04T12:00:00+00:00"


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def document(**over) -> dict:
    """The locked decision, as a complete document, with targeted overrides."""
    payload = {
        "active_status_values": list(LOCKED_ACTIVE),
        "admitted_status_values": list(CANONICAL_AVAILABILITY_STATUS_VALUES),
        "availability_taxonomy_reference": AVAILABILITY_TAXONOMY_REFERENCE,
        "availability_taxonomy_sha256": derive_availability_taxonomy_pin(
            repo_root=ROOT
        )["sha256"],
        "contract": AVAILABILITY_VOCABULARY_CONTRACT,
        "decided_at": DECIDED_AT,
        "decided_by": DECIDED_BY,
        "non_active_known_status_values": list(LOCKED_NON_ACTIVE_KNOWN),
        "roadmap_status_values": list(LOCKED_ROADMAP),
        "schema_version": AVAILABILITY_VOCABULARY_SCHEMA_VERSION,
        "stage": AVAILABILITY_VOCABULARY_STAGE,
        "unknown_status_values": ["unknown"],
        "vocabulary_version": LOCKED_VOCABULARY_VERSION,
    }
    payload.update(over)
    return {key: value for key, value in payload.items() if value is not ...}


def refusal(payload, *, repo_root=ROOT) -> ExtractionError:
    with pytest.raises(ExtractionError) as excinfo:
        validate_availability_vocabulary(payload, repo_root=repo_root)
    return excinfo.value


# --- the taxonomy, measured rather than remembered ---------------------------


def test_the_canonical_eight_are_the_ontology_s_eight():
    """The reviewed constant against the reviewed document, read here.

    The runtime deliberately never parses the ontology (that would be the
    ambient reading the design rejects), so this equality is asserted in the
    test layer instead. If someone edits the ontology's list, this fails and the
    constant has to be revisited on purpose.
    """
    text = (ROOT / AVAILABILITY_TAXONOMY_REFERENCE).read_text(encoding="utf-8")
    section = text.split("## Availability status", 1)[1].split("\n## ", 1)[0]
    listed = tuple(re.findall(r"^- ([a-z][a-z0-9_]*)$", section, flags=re.MULTILINE))
    assert sorted(listed) == list(CANONICAL_AVAILABILITY_STATUS_VALUES)
    assert len(listed) == 8


def test_the_canonical_tuple_is_ascending_unique_and_well_formed():
    values = CANONICAL_AVAILABILITY_STATUS_VALUES
    assert list(values) == sorted(values)
    assert len(set(values)) == len(values) == 8
    for token in values:
        assert re.fullmatch(r"^[a-z][a-z0-9_]*$", token), token


def test_planned_is_absent_from_the_taxonomy_the_constant_and_the_schema():
    """Three independent layers, and the source scan is AST-based on purpose.

    A raw-text scan would match the module docstring's own sentence explaining
    why ``planned`` is excluded, so it would either fail on correct code or be
    weakened until it proved nothing. Only string *constants* are examined:
    prose is free to name the token, executable code is not.
    """
    import ast

    assert "planned" not in CANONICAL_AVAILABILITY_STATUS_VALUES
    assert "planned" not in _schema()["$defs"]["availability_status_token"]["enum"]

    module_path = ROOT / "src/dynamic_ai_products/extraction/availability_vocabulary.py"
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    docstrings = {ast.get_docstring(node) for node in ast.walk(tree)
                  if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef))}
    constants = [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value not in docstrings
    ]
    assert "planned" not in constants
    assert constants, "the scan must actually have inspected string constants"


def test_the_taxonomy_pin_is_the_files_literal_digest():
    pin = derive_availability_taxonomy_pin(repo_root=ROOT)
    raw = (ROOT / AVAILABILITY_TAXONOMY_REFERENCE).read_bytes()
    assert pin == {
        "reference": AVAILABILITY_TAXONOMY_REFERENCE,
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def test_an_unreadable_taxonomy_fails_closed(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        derive_availability_taxonomy_pin(repo_root=tmp_path)
    assert excinfo.value.reason_code == "availability_taxonomy_pin_mismatch"


# --- the schema layer --------------------------------------------------------


def test_the_schema_file_manifest_key_contract_and_version_agree():
    schema = _schema()
    manifest = json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json").read_text(encoding="utf-8")
    )["schemas"]
    key = SCHEMA_PATH.name.removesuffix(".schema.json")
    assert schema["$id"] == SCHEMA_PATH.name
    assert manifest[key] == schema["properties"]["schema_version"]["const"]
    assert schema["properties"]["contract"]["const"] == f"{key}@{manifest[key]}"
    assert schema["properties"]["contract"]["const"] == AVAILABILITY_VOCABULARY_CONTRACT


def test_the_schema_is_meta_valid_and_closed():
    schema = _schema()
    Draft202012Validator.check_schema(schema)
    assert schema["additionalProperties"] is False
    assert sorted(schema["required"]) == sorted(schema["properties"])
    assert len(schema["required"]) == 13


def test_the_schema_pins_the_admitted_list_at_exactly_eight():
    admitted = _schema()["properties"]["admitted_status_values"]
    assert admitted["minItems"] == admitted["maxItems"] == 8
    assert admitted["uniqueItems"] is True


def test_the_schema_enum_and_the_code_constant_do_not_drift():
    enum = _schema()["$defs"]["availability_status_token"]["enum"]
    assert tuple(enum) == CANONICAL_AVAILABILITY_STATUS_VALUES


def test_the_locked_decision_validates_against_the_schema():
    Draft202012Validator(_schema()).validate(document())


@pytest.mark.parametrize("field", ["admitted_status_values", *AVAILABILITY_PARTITION_FIELDS])
def test_the_schema_rejects_an_out_of_taxonomy_token_in_every_list(field):
    payload = document(**{field: ["planned"]})
    assert not Draft202012Validator(_schema()).is_valid(payload)


@pytest.mark.parametrize(
    "payload",
    [
        document(admitted_status_values=list(CANONICAL_AVAILABILITY_STATUS_VALUES)[:7]),
        document(unknown_status_values=["deprecated"]),
        document(unknown_status_values=["unknown", "deprecated"]),
        document(availability_taxonomy_sha256="Z" * 64),
        document(availability_taxonomy_reference="docs/other.md"),
        document(vocabulary_version=""),
        document(injected_field="x"),
        document(contract=...),
    ],
)
def test_the_schema_rejects_these_documents(payload):
    assert not Draft202012Validator(_schema()).is_valid(payload)


# --- the loader layer: L1 through L7 ----------------------------------------


def test_the_locked_decision_passes_the_loader():
    accepted = validate_availability_vocabulary(document(), repo_root=ROOT)
    assert accepted["active_status_values"] == LOCKED_ACTIVE
    assert accepted["roadmap_status_values"] == LOCKED_ROADMAP
    assert accepted["non_active_known_status_values"] == LOCKED_NON_ACTIVE_KNOWN
    assert accepted["unknown_status_values"] == ["unknown"]
    assert accepted["admitted_status_values"] == list(
        CANONICAL_AVAILABILITY_STATUS_VALUES
    )


def test_l1_a_descending_partition_list_is_refused():
    assert refusal(
        document(active_status_values=list(reversed(LOCKED_ACTIVE)))
    ).reason_code == "vocabulary_not_ascending"


def test_l1_a_descending_admitted_list_is_refused():
    assert refusal(
        document(
            admitted_status_values=list(
                reversed(CANONICAL_AVAILABILITY_STATUS_VALUES)
            )
        )
    ).reason_code == "vocabulary_not_ascending"


@pytest.mark.parametrize(
    "admitted",
    [
        list(CANONICAL_AVAILABILITY_STATUS_VALUES)[:7],
        sorted([*CANONICAL_AVAILABILITY_STATUS_VALUES, "beta"]),
        sorted(
            [
                *(v for v in CANONICAL_AVAILABILITY_STATUS_VALUES
                  if v != "broadly_deployed_or_default"),
                "default_or_broadly_deployed",
            ]
        ),
    ],
    ids=["one_short", "one_extra", "respelled_token"],
)
def test_l2_admitted_must_be_the_exact_canonical_set(admitted):
    assert refusal(
        document(admitted_status_values=admitted)
    ).reason_code == "vocabulary_not_canonical_set"


def test_l3_a_partition_that_drops_a_token_is_refused():
    error = refusal(document(non_active_known_status_values=["deprecated"]))
    assert error.reason_code == "vocabulary_partition_incomplete"
    assert "discontinued" in str(error)


def test_l4_a_token_in_two_lists_is_refused_as_an_overlap():
    """Ordering matters here, not just the refusal.

    A duplicated token both overlaps and (because ``admitted`` is fixed at
    eight) leaves the union short somewhere else. Checking completeness first
    would report ``partition_incomplete`` and point the operator at the wrong
    list, so L4 runs before L3 and this test pins that order.
    """
    error = refusal(
        document(
            active_status_values=sorted([*LOCKED_ACTIVE, "announced"]),
            roadmap_status_values=["announced"],
        )
    )
    assert error.reason_code == "vocabulary_partition_overlapping"
    assert "announced" in str(error)


@pytest.mark.parametrize(
    "value",
    [[], ["Private_Beta"], ["private beta"], ["private-beta"], ["private_beta:"],
     [""], ["  "], [12], ["private_beta", "private_beta"]],
    ids=["empty", "uppercase", "inner_space", "hyphen", "colon", "blank",
         "whitespace", "non_string", "duplicate"],
)
def test_l5_list_grammar_is_closed(value):
    assert refusal(
        document(active_status_values=value)
    ).reason_code == "vocabulary_list_invalid"


def test_l5_a_non_list_is_refused():
    assert refusal(
        document(active_status_values="private_beta")
    ).reason_code == "vocabulary_list_invalid"


@pytest.mark.parametrize(
    "payload",
    [
        document(
            unknown_status_values=["deprecated"],
            non_active_known_status_values=["discontinued", "unknown"],
        ),
        document(
            unknown_status_values=["deprecated", "unknown"],
            non_active_known_status_values=["discontinued"],
        ),
    ],
    ids=["unknown_moved_out", "unknown_shares_its_list"],
)
def test_l6_unknown_has_exactly_one_admissible_placement(payload):
    assert refusal(payload).reason_code == "vocabulary_unknown_misplaced"


def test_l6_is_reported_before_the_partition_checks():
    """A moved ``unknown`` is a misplacement, not a partition arithmetic defect.

    The document below is *also* partition-complete and disjoint, so only the
    dedicated L6 check can catch it -- and it must, because reclassifying
    ``unknown`` is precisely what CLAUDE.md rule 7 forbids.
    """
    payload = document(
        unknown_status_values=["deprecated"],
        non_active_known_status_values=["discontinued", "unknown"],
    )
    union = set()
    for field in AVAILABILITY_PARTITION_FIELDS:
        union |= set(payload[field])
    assert union == set(CANONICAL_AVAILABILITY_STATUS_VALUES)
    assert refusal(payload).reason_code == "vocabulary_unknown_misplaced"


@pytest.mark.parametrize(
    "reference",
    [
        "/etc/passwd",
        "../PRODUCT_CAPABILITY_TASK_ONTOLOGY.md",
        "docs\\methodology\\PRODUCT_CAPABILITY_TASK_ONTOLOGY.md",
        "C:/docs/PRODUCT_CAPABILITY_TASK_ONTOLOGY.md",
        "docs/methodology/ABSENT.md",
    ],
    ids=["absolute", "traversal", "backslash", "drive", "missing"],
)
def test_l7_an_unsafe_or_unresolvable_taxonomy_reference_is_refused(reference):
    assert refusal(
        document(availability_taxonomy_reference=reference)
    ).reason_code == "availability_taxonomy_pin_mismatch"


def test_l7_a_stale_taxonomy_digest_invalidates_the_artifact():
    assert refusal(
        document(availability_taxonomy_sha256="0" * 64)
    ).reason_code == "availability_taxonomy_pin_mismatch"


def test_l7_a_different_but_resolvable_document_is_refused():
    """Resolving is not enough; it has to be *the* taxonomy.

    A pin naming some other tracked file with that file's own correct digest
    hydrates successfully, so containment and hashing alone would accept it.
    """
    other = "docs/TEMPORAL_POLICY.md"
    digest = hashlib.sha256((ROOT / other).read_bytes()).hexdigest()
    error = refusal(
        document(
            availability_taxonomy_reference=other,
            availability_taxonomy_sha256=digest,
        )
    )
    assert error.reason_code == "availability_taxonomy_pin_mismatch"


# --- shape ------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        document(injected_field="x"),
        document(contract=...),
        document(decided_by=...),
        document(contract="product_candidate_availability_vocabulary@0.2.0"),
        document(schema_version="0.2.0"),
        document(stage="capability_extraction"),
        document(vocabulary_version=""),
        document(vocabulary_version="   "),
        document(vocabulary_version=7),
        document(decided_by=""),
        document(decided_at="2026-08-04T12:00:00"),
        document(decided_at="not-a-timestamp"),
        document(decided_at=""),
    ],
    ids=["extra_property", "missing_contract", "missing_decided_by",
         "wrong_contract", "wrong_schema_version", "wrong_stage",
         "blank_version", "whitespace_version", "non_string_version",
         "blank_decided_by", "naive_instant", "unparseable_instant",
         "empty_instant"],
)
def test_the_shape_gate_refuses_these(payload):
    assert refusal(payload).reason_code == "vocabulary_input_invalid"


def test_a_non_mapping_is_refused():
    assert refusal(["not", "a", "mapping"]).reason_code == "vocabulary_input_invalid"


def test_validation_returns_a_fresh_outer_mapping():
    payload = document()
    accepted = validate_availability_vocabulary(payload, repo_root=ROOT)
    assert accepted is not payload
    accepted["injected"] = True
    assert "injected" not in payload
    # The list objects are shared, deliberately and visibly: this returns a new
    # outer mapping, not a deep copy, and nothing downstream mutates them.
    assert accepted["active_status_values"] is payload["active_status_values"]


# --- the builder ------------------------------------------------------------


def test_the_builder_produces_the_locked_decision():
    built = build_availability_vocabulary(
        vocabulary_version=LOCKED_VOCABULARY_VERSION,
        active_status_values=LOCKED_ACTIVE,
        roadmap_status_values=LOCKED_ROADMAP,
        non_active_known_status_values=LOCKED_NON_ACTIVE_KNOWN,
        decided_by=DECIDED_BY,
        decided_at=DECIDED_AT,
        repo_root=ROOT,
    )
    assert built == document()
    Draft202012Validator(_schema()).validate(built)


def test_the_builder_owns_admitted_and_unknown_rather_than_accepting_them():
    """Two facts a caller cannot supply, because they are not decisions.

    ``admitted_status_values`` is the taxonomy and ``unknown_status_values`` is
    fixed by L6. Neither is a parameter, so neither can be varied -- the
    constraint is structural, not merely validated.
    """
    import inspect

    parameters = set(inspect.signature(build_availability_vocabulary).parameters)
    assert "admitted_status_values" not in parameters
    assert "unknown_status_values" not in parameters
    assert parameters == {
        "vocabulary_version",
        "active_status_values",
        "roadmap_status_values",
        "non_active_known_status_values",
        "decided_by",
        "decided_at",
        "repo_root",
    }


def test_the_builder_validates_before_returning():
    with pytest.raises(ExtractionError) as excinfo:
        build_availability_vocabulary(
            vocabulary_version=LOCKED_VOCABULARY_VERSION,
            active_status_values=[*LOCKED_ACTIVE, "announced"],
            roadmap_status_values=LOCKED_ROADMAP,
            non_active_known_status_values=LOCKED_NON_ACTIVE_KNOWN,
            decided_by=DECIDED_BY,
            decided_at=DECIDED_AT,
            repo_root=ROOT,
        )
    assert excinfo.value.reason_code == "vocabulary_not_ascending"


def test_the_builder_reads_the_taxonomy_digest_from_disk():
    built = build_availability_vocabulary(
        vocabulary_version=LOCKED_VOCABULARY_VERSION,
        active_status_values=LOCKED_ACTIVE,
        roadmap_status_values=LOCKED_ROADMAP,
        non_active_known_status_values=LOCKED_NON_ACTIVE_KNOWN,
        decided_by=DECIDED_BY,
        decided_at=DECIDED_AT,
        repo_root=ROOT,
    )
    raw = (ROOT / AVAILABILITY_TAXONOMY_REFERENCE).read_bytes()
    assert built["availability_taxonomy_sha256"] == hashlib.sha256(raw).hexdigest()


# --- materialization --------------------------------------------------------


def test_materialization_writes_exactly_one_file_and_returns_its_pin(tmp_path: Path):
    root = tmp_path / "vocab-product-availability-0001"
    root.mkdir()
    pin = materialize_availability_vocabulary(
        document(), attempt_root=root, repo_root=ROOT
    )
    written = sorted(p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file())
    assert written == [AVAILABILITY_VOCABULARY_REFERENCE]
    assert pin["reference"] == AVAILABILITY_VOCABULARY_REFERENCE
    raw = (root / AVAILABILITY_VOCABULARY_REFERENCE).read_bytes()
    assert pin["sha256"] == hashlib.sha256(raw).hexdigest()
    assert json.loads(raw) == document()


def test_the_persisted_bytes_are_canonical_and_re_validate(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    materialize_availability_vocabulary(document(), attempt_root=root, repo_root=ROOT)
    raw = (root / AVAILABILITY_VOCABULARY_REFERENCE).read_bytes()
    reloaded = json.loads(raw)
    assert list(reloaded) == sorted(reloaded)
    validate_availability_vocabulary(reloaded, repo_root=ROOT)


def test_a_second_write_into_the_same_root_is_refused(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    materialize_availability_vocabulary(document(), attempt_root=root, repo_root=ROOT)
    with pytest.raises(ExtractionError) as excinfo:
        materialize_availability_vocabulary(
            document(), attempt_root=root, repo_root=ROOT
        )
    assert excinfo.value.reason_code == "destination_exists"


def test_an_invalid_document_writes_nothing(tmp_path: Path):
    root = tmp_path / "root"
    root.mkdir()
    with pytest.raises(ExtractionError):
        materialize_availability_vocabulary(
            document(unknown_status_values=["deprecated"]),
            attempt_root=root,
            repo_root=ROOT,
        )
    assert list(root.rglob("*")) == []


@pytest.mark.parametrize("kind", ["missing", "file", "symlink", "non_empty"])
def test_the_attempt_root_must_be_a_real_empty_directory(tmp_path: Path, kind):
    root = tmp_path / "root"
    real = tmp_path / "real"
    if kind == "file":
        root.write_text("x")
    elif kind == "symlink":
        real.mkdir()
        root.symlink_to(real, target_is_directory=True)
    elif kind == "non_empty":
        root.mkdir()
        (root / ".gitkeep").write_text("")
    with pytest.raises(ExtractionError) as excinfo:
        materialize_availability_vocabulary(
            document(), attempt_root=root, repo_root=ROOT
        )
    expected = "destination_exists" if kind == "non_empty" else "vocabulary_input_invalid"
    assert excinfo.value.reason_code == expected
    if kind == "symlink":
        # Refused before any write: a symlinked root must not have been followed.
        assert list(real.iterdir()) == []
    if kind == "non_empty":
        assert [p.name for p in root.iterdir()] == [".gitkeep"]


# --- the boundary this contract must not cross ------------------------------


def test_product_extraction_is_not_added_to_the_evaluator_stage_universe():
    """ADR-028's Rule-10 vocabulary and this one are separate contracts.

    The evaluator's governed stage set is a closed four. If ``product_extraction``
    ever appeared in it, this candidate-admission vocabulary and the Rule-10
    evaluator classification would start answering each other's questions.
    """
    from dynamic_ai_products.evaluation.validator_parameters import _STAGE_ORDER

    assert AVAILABILITY_VOCABULARY_STAGE not in _STAGE_ORDER
    assert set(_STAGE_ORDER) == {
        "capability_extraction",
        "task_extraction",
        "universe_screen",
        "universe_classification",
    }


def test_the_vocabulary_does_not_touch_the_released_product_observation_schema():
    """``availability_status`` stays an unconstrained string.

    Admission is governed by this artifact, not by mutating an accepted schema.
    """
    schema = json.loads(
        (ROOT / "schemas" / "product_observation.schema.json").read_text(encoding="utf-8")
    )
    assert schema["properties"]["availability_status"] == {"type": "string"}
