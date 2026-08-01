"""Offline evidence validation (ADR-042, documentation_evidence_validation@0.1.0).

Every test here is synthetic: fixture bytes built in-test and written only under
``tmp_path``. Nothing reads ``data/raw/**`` -- those objects are gitignored, so a
suite that needed them would pass on one machine and fail on another. The one
committed artifact that *is* tracked, the registry record, is validated against
the committed schema without touching raw evidence.
"""

from __future__ import annotations

import ast
import json
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection import documentation_evidence_validation as ev  # noqa: E402
from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products" / "collection"
SCHEMA_PATH = ROOT / "schemas" / "documentation_evidence_validation.schema.json"
SCHEMA_BYTES = SCHEMA_PATH.read_bytes()
RECORD_PATH = (
    ROOT / "data" / "registry"
    / "documentation_evidence_validation_vertex_ai_gemini_2_5_flash_v1.json"
)

# --- synthetic fixture --------------------------------------------------------

PREFIX = b"<html><body>lead-in bytes that are not part of any selection</body>"
BODY = "the free tier is $0.00 and the maximum quota is 3000 requests per minute".encode()
SUFFIX = b"<!-- trailing bytes -->"
RAW = PREFIX + BODY + SUFFIX
START, STOP = len(PREFIX), len(PREFIX) + len(BODY)


def synthetic_selection(**over) -> dict:
    selection = {
        "evidence_kind": "synthetic_kind",
        "raw_sha256": sha256(RAW).hexdigest(),
        "raw_byte_count": len(RAW),
        "slice_start": START,
        "slice_stop": STOP,
        "slice_sha256": sha256(BODY).hexdigest(),
        "required_literals": ("$0.00", "3000 requests per minute"),
        "forbidden_literals": ("unlimited quota",),
        "claim": "the synthetic passage states a zero price and a 3000 RPM quota",
    }
    selection.update(over)
    return selection


# --- happy path ---------------------------------------------------------------


def test_a_matching_selection_validates():
    finding = ev.validate_selection(synthetic_selection(), RAW)
    assert finding["evidence_kind"] == "synthetic_kind"
    assert finding["slice_byte_count"] == STOP - START
    assert finding["slice_sha256"] == sha256(BODY).hexdigest()
    assert finding["required_literal_count"] == 2
    assert finding["forbidden_literal_count"] == 1
    assert finding["claim_attribution"] == "human_reading_of_the_verified_range"


def test_the_finding_records_the_selection_verbatim():
    """The record carries what was checked, not a summary of it."""
    selection = synthetic_selection()
    finding = ev.validate_selection(selection, RAW)
    assert finding["required_literals"] == list(selection["required_literals"])
    assert finding["forbidden_literals"] == list(selection["forbidden_literals"])
    assert finding["claim"] == selection["claim"]


# --- raw object mismatches ----------------------------------------------------


def test_a_raw_digest_mismatch_is_refused():
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(synthetic_selection(raw_sha256="0" * 64), RAW)
    assert excinfo.value.reason_code == "raw_digest_mismatch"


def test_a_raw_byte_count_mismatch_is_refused():
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(synthetic_selection(raw_byte_count=len(RAW) + 1), RAW)
    assert excinfo.value.reason_code == "raw_byte_count_mismatch"


def test_a_single_flipped_byte_anywhere_is_refused():
    """Byte count survives the edit; the digest does not."""
    tampered = bytearray(RAW)
    tampered[0] ^= 0x01
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(synthetic_selection(), bytes(tampered))
    assert excinfo.value.reason_code == "raw_digest_mismatch"


# --- slice bounds, digest, text ----------------------------------------------


@pytest.mark.parametrize(
    "start,stop",
    [(START, len(RAW) + 1), (len(RAW), len(RAW) + 5), (STOP, START), (START, START)],
    ids=["stop-past-end", "start-past-end", "reversed", "empty"],
)
def test_out_of_range_or_empty_bounds_are_refused(start, stop):
    """Python would clamp an over-long slice; the bounds are checked first."""
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(synthetic_selection(slice_start=start, slice_stop=stop), RAW)
    assert excinfo.value.reason_code == "slice_bounds_invalid"


def test_a_shifted_range_of_the_same_length_is_refused():
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(
            synthetic_selection(slice_start=START - 1, slice_stop=STOP - 1), RAW
        )
    assert excinfo.value.reason_code == "slice_digest_mismatch"


def test_a_slice_digest_mismatch_is_refused():
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(synthetic_selection(slice_sha256="1" * 64), RAW)
    assert excinfo.value.reason_code == "slice_digest_mismatch"


def test_text_tampered_inside_the_range_is_refused():
    """The bytes still decode and still contain the literals -- the digest catches it."""
    tampered = RAW.replace(b"3000 requests", b"9999 requests")
    assert len(tampered) == len(RAW)
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(
            synthetic_selection(raw_sha256=sha256(tampered).hexdigest()), tampered
        )
    assert excinfo.value.reason_code == "slice_digest_mismatch"


@pytest.mark.parametrize("bad", [b"\xff\xfe", b"\x80abc", b"abc\xc3"],
                         ids=["ff-fe", "lone-continuation", "truncated-sequence"])
def test_a_range_that_is_not_strict_utf8_is_refused(bad):
    raw = PREFIX + bad + SUFFIX
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(
            synthetic_selection(
                raw_sha256=sha256(raw).hexdigest(),
                raw_byte_count=len(raw),
                slice_start=len(PREFIX),
                slice_stop=len(PREFIX) + len(bad),
                slice_sha256=sha256(bad).hexdigest(),
            ),
            raw,
        )
    assert excinfo.value.reason_code == "slice_not_utf8"


# --- literal containment ------------------------------------------------------


def test_an_absent_required_literal_is_refused():
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(
            synthetic_selection(required_literals=("$0.00", "not in the passage")), RAW
        )
    assert excinfo.value.reason_code == "required_literal_absent"


def test_a_present_forbidden_literal_is_refused():
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(
            synthetic_selection(forbidden_literals=("3000 requests",)), RAW
        )
    assert excinfo.value.reason_code == "forbidden_literal_present"


@pytest.mark.parametrize(
    "literal",
    ["3000  requests per minute", "3000\trequests per minute",
     "3000 requests per minute ", "  3000 requests per minute",
     "3000 REQUESTS PER MINUTE", "3000 requests\nper minute",
     "maximum  quota"],
    ids=["double-space", "tab", "trailing-space", "double-leading-space",
         "case", "newline", "internal-double-space"],
)
def test_whitespace_or_case_variants_are_not_normalized_into_a_match(literal):
    """No normalization: a literal differing by whitespace or case does not match."""
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(synthetic_selection(required_literals=(literal,)), RAW)
    assert excinfo.value.reason_code == "required_literal_absent"


def test_a_single_leading_space_matches_because_the_source_has_one():
    """Exactness cuts both ways: the guard is containment, not a whitespace rule.

    ``" 3000 requests per minute"`` really does occur -- the passage reads
    "...quota is 3000 requests per minute" -- so it matches, and a test that
    expected a refusal here would have been asserting a falsehood.
    """
    finding = ev.validate_selection(
        synthetic_selection(required_literals=(" 3000 requests per minute",)), RAW
    )
    assert finding["required_literal_count"] == 1


@pytest.mark.parametrize(
    "stored,queried",
    [(b"model&#39;s output", "model's output"), (b"a &amp; b", "a & b"),
     (b"&lt;td&gt;", "<td>"), (b"&nbsp;", " ")],
    ids=["apostrophe", "ampersand", "angle-brackets", "nbsp"],
)
def test_html_entities_are_never_decoded_into_a_match(stored, queried):
    """An entity in the source is not the character it denotes; no decoder runs."""
    raw = PREFIX + stored + SUFFIX
    selection = synthetic_selection(
        raw_sha256=sha256(raw).hexdigest(),
        raw_byte_count=len(raw),
        slice_start=len(PREFIX),
        slice_stop=len(PREFIX) + len(stored),
        slice_sha256=sha256(stored).hexdigest(),
        required_literals=(queried,),
        forbidden_literals=(),
    )
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(selection, raw)
    assert excinfo.value.reason_code == "required_literal_absent"
    # The stored form itself matches exactly, which is the whole point.
    ok = dict(selection)
    ok["required_literals"] = (stored.decode(),)
    assert ev.validate_selection(ok, raw)["required_literal_count"] == 1


# --- malformed selections never leak a builtin exception ----------------------


@pytest.mark.parametrize(
    "selection,label",
    [
        (None, "none"),
        ("not a mapping", "string"),
        (42, "int"),
        ([], "list"),
        ((), "tuple"),
    ],
)
def test_a_selection_that_is_not_a_mapping_is_refused(selection, label):
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(selection, RAW)
    assert excinfo.value.reason_code == "validation_input_invalid", label


@pytest.mark.parametrize(
    "missing",
    ["evidence_kind", "raw_sha256", "raw_byte_count", "slice_start", "slice_stop",
     "slice_sha256", "required_literals", "forbidden_literals", "claim"],
)
def test_a_selection_missing_any_field_is_refused(missing):
    selection = synthetic_selection()
    del selection[missing]
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(selection, RAW)
    assert excinfo.value.reason_code == "validation_input_invalid", missing


@pytest.mark.parametrize(
    "field", ["raw_byte_count", "slice_start", "slice_stop"]
)
def test_a_bool_where_an_integer_belongs_is_refused(field):
    """True == 1 in Python; a bool is not a byte offset."""
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(synthetic_selection(**{field: True}), RAW)
    assert excinfo.value.reason_code == "validation_input_invalid", field


@pytest.mark.parametrize(
    "field,value,label",
    [
        ("evidence_kind", None, "kind-none"),
        ("evidence_kind", "", "kind-empty"),
        ("evidence_kind", 7, "kind-int"),
        ("claim", None, "claim-none"),
        ("claim", "", "claim-empty"),
        ("claim", ["a"], "claim-list"),
        ("raw_sha256", None, "digest-none"),
        ("raw_sha256", "XY" * 32, "digest-non-hex"),
        ("slice_sha256", 12345, "digest-int"),
        ("raw_byte_count", "100", "count-string"),
        ("slice_start", -1, "start-negative"),
        ("slice_start", 1.5, "start-float"),
        ("required_literals", "a bare string", "literals-string"),
        ("required_literals", b"bytes", "literals-bytes"),
        ("required_literals", None, "literals-none"),
        ("forbidden_literals", {"a": 1}, "forbidden-dict"),
        ("required_literals", (None,), "literal-none"),
        ("required_literals", (b"bytes",), "literal-bytes"),
        ("required_literals", ("",), "literal-empty"),
        ("forbidden_literals", (7,), "forbidden-int"),
    ],
)
def test_a_wrongly_typed_field_is_refused(field, value, label):
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(synthetic_selection(**{field: value}), RAW)
    assert excinfo.value.reason_code == "validation_input_invalid", label


@pytest.mark.parametrize("raw", [None, "a string", 42, ["bytes"]])
def test_non_bytes_evidence_is_refused(raw):
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_selection(synthetic_selection(), raw)
    assert excinfo.value.reason_code == "validation_input_invalid"


def test_no_builtin_exception_escapes_for_any_malformed_selection():
    """Every malformed shape becomes a CollectionError, never a KeyError/TypeError."""
    hostile = [
        None, "s", 7, [], (), {}, {"evidence_kind": "k"},
        dict(synthetic_selection(), required_literals=None),
        dict(synthetic_selection(), forbidden_literals="x"),
        dict(synthetic_selection(), slice_start=True),
        dict(synthetic_selection(), claim=None),
        dict(synthetic_selection(), raw_sha256=None),
    ]
    for selection in hostile:
        try:
            ev.validate_selection(selection, RAW)
        except CollectionError as exc:
            assert exc.reason_code == "validation_input_invalid", selection
        except Exception as exc:  # noqa: BLE001 - that is exactly what must not happen
            raise AssertionError(f"{type(exc).__name__} leaked for {selection!r}") from exc


# --- receipt binding ----------------------------------------------------------


def synthetic_receipt(**over) -> bytes:
    receipt = {
        "attempt_id": "docattempt-" + "a" * 32,
        "contract": "documentation_collection_receipt@0.5.0",
        "receipt_schema_sha256": "b" * 64,
        "completion_status": "completed",
        "entries": [
            {
                "evidence_kind": "synthetic_kind",
                "entry_status": "succeeded",
                "content_sha256": sha256(RAW).hexdigest(),
                "byte_count": len(RAW),
                "raw_reference": "synthetic_kind/sha256-x/document.html",
            }
        ],
    }
    receipt.update(over)
    return json.dumps(receipt, sort_keys=True).encode("utf-8")


@pytest.fixture()
def bound(monkeypatch):
    """Point the module's pinned binding at a synthetic receipt."""
    receipt_bytes = synthetic_receipt()
    binding = {
        "attempt_id": "docattempt-" + "a" * 32,
        "receipt_sha256": sha256(receipt_bytes).hexdigest(),
        "receipt_contract": "documentation_collection_receipt@0.5.0",
        "receipt_schema_sha256": "b" * 64,
    }
    monkeypatch.setattr(ev, "ATTEMPT_BINDING", binding)
    return receipt_bytes


def test_a_bound_receipt_and_object_build_a_record(bound):
    record = ev._build_record_noncanonical(
        receipt_bytes=bound,
        raw_objects={"synthetic_kind": RAW},
        selections=(synthetic_selection(),),
        attempt_binding=ev.ATTEMPT_BINDING,
    )
    assert record["contract"] == "documentation_evidence_validation@0.1.0"
    assert record["selection_provenance"] == "human_selected_byte_slice_v1"
    assert record["decode"] == "utf_8_strict"
    assert record["normalization"] == "none"
    assert len(record["findings"]) == 1
    assert record["findings"][0]["raw_reference"] == "synthetic_kind/sha256-x/document.html"


def test_a_receipt_whose_digest_differs_is_refused(bound):
    with pytest.raises(CollectionError) as excinfo:
        ev._build_record_noncanonical(
            receipt_bytes=bound + b" ",
            raw_objects={"synthetic_kind": RAW},
            selections=(synthetic_selection(),),
            attempt_binding=ev.ATTEMPT_BINDING,
        )
    assert excinfo.value.reason_code == "receipt_binding_mismatch"


@pytest.mark.parametrize(
    "field,value",
    [("attempt_id", "docattempt-" + "c" * 32),
     ("contract", "documentation_collection_receipt@0.4.0"),
     ("receipt_schema_sha256", "c" * 64),
     ("completion_status", "stopped")],
)
def test_a_receipt_that_is_not_the_pinned_attempt_is_refused(monkeypatch, field, value):
    receipt_bytes = synthetic_receipt(**{field: value})
    monkeypatch.setattr(ev, "ATTEMPT_BINDING", {
        "attempt_id": "docattempt-" + "a" * 32,
        "receipt_sha256": sha256(receipt_bytes).hexdigest(),
        "receipt_contract": "documentation_collection_receipt@0.5.0",
        "receipt_schema_sha256": "b" * 64,
    })
    with pytest.raises(CollectionError) as excinfo:
        ev._build_record_noncanonical(
            receipt_bytes=receipt_bytes,
            raw_objects={"synthetic_kind": RAW},
            selections=(synthetic_selection(),),
            attempt_binding=ev.ATTEMPT_BINDING,
        )
    assert excinfo.value.reason_code == "receipt_binding_mismatch"


def test_a_receipt_entry_that_did_not_succeed_is_refused(monkeypatch):
    receipt_bytes = synthetic_receipt(entries=[{
        "evidence_kind": "synthetic_kind", "entry_status": "failed",
        "content_sha256": None, "byte_count": None, "raw_reference": None,
    }])
    monkeypatch.setattr(ev, "ATTEMPT_BINDING", {
        "attempt_id": "docattempt-" + "a" * 32,
        "receipt_sha256": sha256(receipt_bytes).hexdigest(),
        "receipt_contract": "documentation_collection_receipt@0.5.0",
        "receipt_schema_sha256": "b" * 64,
    })
    with pytest.raises(CollectionError) as excinfo:
        ev._build_record_noncanonical(
            receipt_bytes=receipt_bytes,
            raw_objects={"synthetic_kind": RAW},
            selections=(synthetic_selection(),),
            attempt_binding=ev.ATTEMPT_BINDING,
        )
    assert excinfo.value.reason_code == "receipt_entry_missing"


def test_an_object_the_receipt_did_not_record_is_refused(bound):
    """The validated bytes must be the ones this attempt actually persisted."""
    other = RAW + b"x"
    with pytest.raises(CollectionError) as excinfo:
        ev._build_record_noncanonical(
            receipt_bytes=bound,
            raw_objects={"synthetic_kind": other},
            selections=(synthetic_selection(
                raw_sha256=sha256(other).hexdigest(), raw_byte_count=len(other)),),
            attempt_binding=ev.ATTEMPT_BINDING,
        )
    assert excinfo.value.reason_code == "receipt_binding_mismatch"


def test_a_missing_raw_object_is_refused(bound):
    with pytest.raises(CollectionError) as excinfo:
        ev._build_record_noncanonical(
            receipt_bytes=bound, raw_objects={}, selections=(synthetic_selection(),),
            attempt_binding=ev.ATTEMPT_BINDING,
        )
    assert excinfo.value.reason_code == "raw_object_missing"


# --- the raw_objects container is validated before any membership test --------


@pytest.mark.parametrize(
    "raw_objects,label",
    [
        (None, "none"),
        ([], "list"),
        ([b"bytes"], "list-of-bytes"),
        ((), "tuple"),
        (("gemini_thinking",), "tuple-of-str"),
        ("abc", "str"),
        ("synthetic_kind", "str-containing-the-kind"),
        (7, "int"),
        (set(), "set"),
        (b"bytes", "bytes"),
    ],
)
def test_a_raw_objects_container_that_is_not_a_mapping_is_refused(
    bound, raw_objects, label
):
    """Measured leaks: ``None`` and ``int`` raised TypeError from the membership
    test, and a ``str`` containing an evidence kind passed it and then raised
    TypeError on subscript. A ``list`` reported ``raw_object_missing``, naming the
    wrong failure entirely.
    """
    with pytest.raises(CollectionError) as excinfo:
        ev._build_record_noncanonical(
            receipt_bytes=bound,
            raw_objects=raw_objects,
            selections=(synthetic_selection(),),
            attempt_binding=ev.ATTEMPT_BINDING,
        )
    assert excinfo.value.reason_code == "validation_input_invalid", label


@pytest.mark.parametrize(
    "value,label",
    [(None, "none"), ("not bytes", "str"), (7, "int"), ([], "list"),
     ({"a": 1}, "dict"), (memoryview(b"x"), "memoryview")],
)
def test_a_raw_object_value_that_is_not_bytes_is_refused(bound, value, label):
    with pytest.raises(CollectionError) as excinfo:
        ev._build_record_noncanonical(
            receipt_bytes=bound,
            raw_objects={"synthetic_kind": value},
            selections=(synthetic_selection(),),
            attempt_binding=ev.ATTEMPT_BINDING,
        )
    assert excinfo.value.reason_code == "validation_input_invalid", label


@pytest.mark.parametrize("key,label", [(7, "int-key"), ("", "empty-key"), (None, "none-key")])
def test_a_raw_objects_key_that_is_not_a_kind_name_is_refused(bound, key, label):
    with pytest.raises(CollectionError) as excinfo:
        ev._build_record_noncanonical(
            receipt_bytes=bound,
            raw_objects={key: RAW},
            selections=(synthetic_selection(),),
            attempt_binding=ev.ATTEMPT_BINDING,
        )
    assert excinfo.value.reason_code == "validation_input_invalid", label


def test_a_bytearray_value_is_accepted(bound):
    """``bytes`` and ``bytearray`` are both real byte containers."""
    record = ev._build_record_noncanonical(
        receipt_bytes=bound,
        raw_objects={"synthetic_kind": bytearray(RAW)},
        selections=(synthetic_selection(),),
        attempt_binding=ev.ATTEMPT_BINDING,
    )
    assert record["findings"][0]["slice_sha256"] == sha256(BODY).hexdigest()


def test_a_missing_evidence_kind_keeps_its_own_distinct_reason(bound):
    """A well-formed mapping that lacks an entry is a different failure.

    ``raw_object_missing`` says the container was fine and the entry was absent;
    ``validation_input_invalid`` says the container itself was unusable. Collapsing
    the two would lose that distinction.
    """
    with pytest.raises(CollectionError) as excinfo:
        ev._build_record_noncanonical(
            receipt_bytes=bound,
            raw_objects={"a_different_kind": RAW},
            selections=(synthetic_selection(),),
            attempt_binding=ev.ATTEMPT_BINDING,
        )
    assert excinfo.value.reason_code == "raw_object_missing"


def test_no_builtin_exception_escapes_for_any_raw_objects_shape(bound):
    hostile = [
        None, [], (), "", "synthetic_kind", 7, 1.5, set(), b"x", object(),
        {"synthetic_kind": None}, {"synthetic_kind": "s"}, {"synthetic_kind": 7},
        {7: RAW}, {"": RAW}, {None: RAW},
    ]
    for raw_objects in hostile:
        try:
            ev._build_record_noncanonical(
                receipt_bytes=bound,
                raw_objects=raw_objects,
                selections=(synthetic_selection(),),
                attempt_binding=ev.ATTEMPT_BINDING,
            )
        except CollectionError as exc:
            assert exc.reason_code in {"validation_input_invalid", "raw_object_missing"}
        except Exception as exc:  # noqa: BLE001 - exactly what must not happen
            raise AssertionError(
                f"{type(exc).__name__} leaked for {raw_objects!r}"
            ) from exc


def test_the_canonical_path_validates_the_container_too(bound):
    """The public entry point shares the guard, not just the private engine."""
    with pytest.raises(CollectionError) as excinfo:
        ev.build_evidence_validation_record(receipt_bytes=bound, raw_objects=None)
    assert excinfo.value.reason_code == "validation_input_invalid"


# --- write-once ---------------------------------------------------------------


def committed_record() -> dict:
    """The tracked canonical record. Reads no gitignored raw object."""
    return json.loads(RECORD_PATH.read_bytes().decode("utf-8"))


def test_the_record_is_written_once_and_never_overwritten(tmp_path: Path):
    record = committed_record()
    target = tmp_path / "record.json"
    digest = ev.publish_evidence_validation_record(target, record)
    assert digest == sha256(target.read_bytes()).hexdigest()
    before = target.read_bytes()
    with pytest.raises(CollectionError) as excinfo:
        ev.publish_evidence_validation_record(target, record)
    assert excinfo.value.reason_code == "destination_exists"
    assert target.read_bytes() == before, "the existing record survives the refusal"


def test_the_serialization_is_canonical_and_deterministic():
    record = committed_record()
    assert ev.validation_record_bytes(record) == ev.validation_record_bytes(record)
    assert ev.validation_record_bytes(record).endswith(b"\n")


# --- the canonical build path takes no caller-supplied selection --------------


def test_the_public_build_path_accepts_no_selection_or_binding():
    """A caller cannot have their own selections wrapped in the locked identity."""
    import inspect

    parameters = inspect.signature(ev.build_evidence_validation_record).parameters
    assert set(parameters) == {"receipt_bytes", "raw_objects"}
    assert "selections" not in parameters
    assert "attempt_binding" not in parameters
    with pytest.raises(TypeError):
        ev.build_evidence_validation_record(
            receipt_bytes=b"{}", raw_objects={}, selections=()
        )


def test_a_record_built_from_foreign_selections_cannot_be_published(tmp_path: Path, bound):
    """The private engine still works; its output is simply not publishable."""
    record = ev._build_record_noncanonical(
        receipt_bytes=bound,
        raw_objects={"synthetic_kind": RAW},
        selections=(synthetic_selection(),),
        attempt_binding=ev.ATTEMPT_BINDING,
    )
    target = tmp_path / "foreign.json"
    with pytest.raises(CollectionError) as excinfo:
        ev.publish_evidence_validation_record(target, record)
    assert excinfo.value.reason_code == "validation_record_not_canonical"
    assert not target.exists(), "no target file is created by a refused publish"


@pytest.mark.parametrize(
    "mutate,label",
    [
        (lambda r: r["attempt_binding"].update(receipt_sha256="0" * 64), "binding"),
        (lambda r: r["findings"][0].update(slice_start=0), "selector"),
        (lambda r: r["findings"][0]["required_literals"].append("extra"), "literal"),
        (lambda r: r["findings"][1].update(claim="a different reading"), "claim"),
        (lambda r: r["pricing_units"].update(input_numerator=4), "pricing"),
        (lambda r: r["findings"][2].update(raw_reference="elsewhere/document.html"),
         "raw-reference"),
        (lambda r: r.update(subject="something_else"), "subject"),
        (lambda r: r.update(normalization="whitespace_collapsed"), "normalization"),
        (lambda r: r["findings"].pop(), "finding-count"),
    ],
)
def test_no_altered_record_can_be_written(tmp_path: Path, mutate, label):
    record = committed_record()
    mutate(record)
    target = tmp_path / f"{label}.json"
    with pytest.raises(CollectionError) as excinfo:
        ev.publish_evidence_validation_record(target, record)
    assert excinfo.value.reason_code == "validation_record_not_canonical", label
    assert not target.exists(), label


def test_the_raw_reference_is_derived_not_accepted():
    for selection in ev.FROZEN_SELECTIONS:
        expected = (
            f"{selection['evidence_kind']}/sha256-{selection['raw_sha256']}/document.html"
        )
        assert ev.canonical_raw_reference(selection) == expected
    record = committed_record()
    for finding, selection in zip(record["findings"], ev.FROZEN_SELECTIONS):
        assert finding["raw_reference"] == ev.canonical_raw_reference(selection)


# --- pricing ------------------------------------------------------------------


def test_the_pricing_units_are_exact_integer_ratios():
    assert ev.PRICING_UNITS["unit"] == "microdollar_per_token"
    assert ev.PRICING_UNITS["microdollar_per_usd"] == 1_000_000
    assert (ev.PRICING_UNITS["input_numerator"], ev.PRICING_UNITS["input_denominator"]) == (3, 10)
    assert (ev.PRICING_UNITS["output_numerator"], ev.PRICING_UNITS["output_denominator"]) == (5, 2)
    assert ev.PRICING_UNITS["prompt_length_tiers"] == 2
    assert ev.PRICING_UNITS["tier_prices_equal"] is True


def test_the_ratios_reproduce_the_quoted_dollar_prices():
    from fractions import Fraction

    usd = ev.PRICING_UNITS["microdollar_per_usd"]
    inp = Fraction(ev.PRICING_UNITS["input_numerator"], ev.PRICING_UNITS["input_denominator"])
    out = Fraction(ev.PRICING_UNITS["output_numerator"], ev.PRICING_UNITS["output_denominator"])
    assert inp * 1_000_000 == Fraction(30, 100) * usd, "$0.30 per 1M tokens"
    assert out * 1_000_000 == Fraction(250, 100) * usd, "$2.50 per 1M tokens"


@pytest.mark.parametrize(
    "inp,out,expected",
    [(0, 0, 0), (1, 1, 4), (10, 10, 28), (1000, 1000, 2800), (1_000_000, 1_000_000, 2_800_000)],
)
def test_the_cost_formula_is_exact(inp, out, expected):
    assert ev.usage_cost_microdollars(input_tokens=inp, output_tokens=out) == expected


@pytest.mark.parametrize("magnitude", [10**18, 10**53, 10**100, 10**400])
def test_the_cost_formula_is_exact_for_very_large_token_counts(magnitude):
    """Integer ceiling division only: no float precision loss, no OverflowError.

    ``ceil(t * 3 / 10)`` would divide in float, which silently loses precision
    above 2**53 and raises OverflowError once the value cannot be converted.
    """
    got = ev.usage_cost_microdollars(input_tokens=magnitude, output_tokens=magnitude)
    expected = -(-magnitude * 3 // 10) + -(-magnitude * 5 // 2)
    assert got == expected
    assert isinstance(got, int)


def test_the_cost_of_a_huge_count_is_not_a_float():
    got = ev.usage_cost_microdollars(input_tokens=10**100, output_tokens=0)
    assert got == (10**100 * 3 + 9) // 10
    assert got * 10 >= 10**100 * 3, "ceiling, never floor"


def test_one_million_of_each_costs_exactly_the_quoted_sum():
    """$0.30 + $2.50 = $2.80 = 2,800,000 microdollar."""
    assert ev.usage_cost_microdollars(
        input_tokens=1_000_000, output_tokens=1_000_000
    ) == 2_800_000


@pytest.mark.parametrize("bad", [-1, 1.5, True, "10", None])
def test_the_cost_formula_refuses_non_counts(bad):
    with pytest.raises(CollectionError) as excinfo:
        ev.usage_cost_microdollars(input_tokens=bad, output_tokens=0)
    assert excinfo.value.reason_code == "validation_input_invalid"


def test_no_float_appears_in_the_declared_pricing_units():
    for key, value in ev.PRICING_UNITS.items():
        assert not isinstance(value, float), key


# --- the committed schema and artifact ---------------------------------------


def test_the_committed_schema_matches_the_locked_definition():
    assert ev.validate_validation_schema_bytes(SCHEMA_BYTES) == sha256(SCHEMA_BYTES).hexdigest()
    Draft202012Validator.check_schema(json.loads(SCHEMA_BYTES.decode("utf-8")))


@pytest.mark.parametrize(
    "path,value",
    [("additionalProperties", 0), ("properties.findings.minItems", 3.0)],
    ids=["addprops-zero", "minitems-float"],
)
def test_the_schema_loader_is_json_type_exact(path, value):
    schema = json.loads(SCHEMA_BYTES.decode("utf-8"))
    node = schema
    parts = path.split(".")
    for key in parts[:-1]:
        node = node[key]
    node[parts[-1]] = value
    with pytest.raises(CollectionError):
        ev.validate_validation_schema_bytes(json.dumps(schema).encode("utf-8"))


def test_the_schema_loader_refuses_a_duplicated_member_name():
    text = SCHEMA_BYTES.decode("utf-8").replace(
        '"type": "object"', '"type": "object", "type": "object"', 1
    )
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_validation_schema_bytes(text.encode("utf-8"))
    assert excinfo.value.reason_code == "validation_schema_invalid"


def test_a_foreign_contract_schema_is_refused():
    v5 = (ROOT / "schemas" / "documentation_collection_receipt.v5.schema.json").read_bytes()
    with pytest.raises(CollectionError) as excinfo:
        ev.validate_validation_schema_bytes(v5)
    assert excinfo.value.reason_code == "validation_schema_contract_mismatch"


def test_the_committed_registry_record_validates_against_the_committed_schema():
    """Tracked artifact, tracked schema -- no gitignored raw object is read."""
    record = json.loads(RECORD_PATH.read_bytes().decode("utf-8"))
    assert not list(Draft202012Validator(
        json.loads(SCHEMA_BYTES.decode("utf-8"))
    ).iter_errors(record))
    assert record["contract"] == "documentation_evidence_validation@0.1.0"
    assert record["attempt_binding"] == ev.ATTEMPT_BINDING
    assert [f["evidence_kind"] for f in record["findings"]] == [
        s["evidence_kind"] for s in ev.FROZEN_SELECTIONS
    ]


# --- the frozen selections, checked without reading raw evidence --------------


def test_every_frozen_selection_is_internally_consistent():
    assert len(ev.FROZEN_SELECTIONS) == 3
    for selection in ev.FROZEN_SELECTIONS:
        assert len(selection["raw_sha256"]) == 64
        assert len(selection["slice_sha256"]) == 64
        assert 0 <= selection["slice_start"] < selection["slice_stop"]
        assert selection["slice_stop"] <= selection["raw_byte_count"]
        assert selection["required_literals"], selection["evidence_kind"]
        for literal in selection["required_literals"] + selection["forbidden_literals"]:
            assert isinstance(literal, str) and literal
        assert selection["claim"].strip()


def test_the_qualifiers_that_must_not_be_dropped_are_bound_as_literals():
    """Two source qualifiers are load-bearing and are pinned so an edit breaks them."""
    by_kind = {s["evidence_kind"]: s for s in ev.FROZEN_SELECTIONS}
    assert "3000 requests per minute" in by_kind["count_tokens"]["required_literals"]
    assert "maximum quota for the" in by_kind["count_tokens"]["required_literals"]
    assert any(
        "reasoning-style text might still be present" in lit
        for lit in by_kind["gemini_thinking"]["required_literals"]
    )


def test_no_claim_overstates_its_evidence():
    """The count_tokens claim must not assert an absence of quota."""
    by_kind = {s["evidence_kind"]: s for s in ev.FROZEN_SELECTIONS}
    claim = by_kind["count_tokens"]["claim"]
    assert "3000" in claim and "rate-limit" in claim
    assert "does not support a claim that no quota applies" in claim


def test_the_prices_are_bound_to_their_own_table_rows():
    """A bare '$0.30 appears somewhere' check would not bind the value to a row."""
    by_kind = {s["evidence_kind"]: s for s in ev.FROZEN_SELECTIONS}
    literals = by_kind["pricing_standard"]["required_literals"]
    assert any(lit.startswith("<td>Input (text, image, video)</td>\n") and "$0.30" in lit
               for lit in literals)
    assert any(lit.startswith("<td>Text output (response and reasoning)</td>\n")
               and "$2.50" in lit for lit in literals)
    thinking = by_kind["gemini_thinking"]["required_literals"]
    assert any("<td>Gemini 2.5 Flash</td>\n<td>1</td>\n<td>24,576</td>" == lit
               for lit in thinking)


# --- structural boundaries ----------------------------------------------------


def test_the_module_imports_no_parser_renderer_network_or_model():
    """The refusal to interpret is structural, not a convention."""
    forbidden = {
        "html", "html.parser", "lxml", "bs4", "beautifulsoup4", "markdownify",
        "httpx", "requests", "urllib", "urllib3", "socket", "http", "ssl",
        "anthropic", "openai", "google", "unicodedata", "codecs", "textwrap",
    }
    tree = ast.parse((SRC / "documentation_evidence_validation.py").read_text(encoding="utf-8"))
    seen: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            seen.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            seen.add(node.module.split(".")[0])
    assert not (seen & forbidden), sorted(seen & forbidden)


def test_the_verification_path_performs_no_normalization():
    """Scoped to the functions that actually inspect evidence.

    A whole-file ban would flag ``declared.strip()`` in the schema loader -- a
    blank-string check on schema metadata that never touches evidence text -- and
    so would punish an unrelated defence rather than catch a real normalizer.
    """
    tree = ast.parse((SRC / "documentation_evidence_validation.py").read_text(encoding="utf-8"))
    verifiers = {"validate_selection", "_require_receipt_binding",
                 "build_evidence_validation_record"}
    checked = set()
    banned = {"lower", "upper", "strip", "casefold", "title", "translate",
              "expandtabs", "unescape", "normalize", "sub", "encode"}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.FunctionDef) and node.name in verifiers):
            continue
        checked.add(node.name)
        for inner in ast.walk(node):
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Attribute):
                assert inner.func.attr not in banned, (node.name, inner.func.attr)
    assert checked == verifiers, sorted(verifiers - checked)


def test_the_module_reads_no_clock_and_no_vcs():
    source = (SRC / "documentation_evidence_validation.py").read_text(encoding="utf-8")
    for marker in ("datetime", "time.time", "utcnow", "subprocess", "rev-parse", "random"):
        assert marker not in source, marker


def test_the_module_declares_no_url_literal():
    source = (SRC / "documentation_evidence_validation.py").read_text(encoding="utf-8")
    assert "http://" not in source
    # The JSON Schema dialect URI is the only https literal permitted here.
    import re as _re

    assert _re.findall(r'"(https?://[^"]*)"', source) == [
        "https://json-schema.org/draft/2020-12/schema"
    ]


def test_the_public_surface_is_exported_and_complete():
    from dynamic_ai_products import collection

    assert "validate_documentation_evidence_selection" in collection.__all__
    assert collection.validate_documentation_evidence_selection is ev.validate_selection
    assert all(hasattr(ev, name) for name in ev.__all__)
