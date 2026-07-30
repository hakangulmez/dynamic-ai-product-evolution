"""Company identity is derived from a SHA-pinned admission artifact (ADR-036).

``extraction_input_packet@0.1.0`` carries ``company_id`` but no name field, so a
prompt needing a legal name could not be rendered from it. ``@0.2.0`` adds the
pinned reference and the name derived from it. The pin is **mandatory**; the
*claim* is forbidden — a caller supplies a reference and a digest, never a name.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.input_packet import (
    PACKET_CONTRACT,
    PACKET_CONTRACT_V2,
    build_extraction_input_packet,
    hydrate_company_identity,
)

ROOT = Path(__file__).resolve().parents[2]
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"


def _passage(passage_id: str, text: str, source_id: str = "sec-1"):
    return {
        "passage_id": passage_id,
        "source_id": source_id,
        "text": text,
        "start_offset": 0,
        "end_offset": len(text),
    }


def _admission(**overrides):
    admission = {
        "company_id": COMPANY,
        "cik": "1404655",
        "legal_name": "HUBSPOT INC",
        "observation_cutoff_date": CUTOFF,
    }
    admission.update(overrides)
    return admission


def _write_admission(root: Path, admission=None, name="admission.json"):
    root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        _admission() if admission is None else admission,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    (root / name).write_bytes(payload)
    return {"reference": name, "sha256": hashlib.sha256(payload).hexdigest()}


def _base(**overrides):
    kwargs = {
        "stage": "product_extraction",
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [_passage("p-1", "the product ships an assistant")],
        "document_publication_dates": {"sec-1": "2024-02-14"},
        "coverage_artifact": {"reference": "c.json", "sha256": "3" * 64},
        "source_snapshot_manifest": {"reference": "m.json", "sha256": "4" * 64},
    }
    kwargs.update(overrides)
    return kwargs


# --- the two versions coexist -------------------------------------------------


def test_a_packet_without_an_identity_pin_stays_at_v0_1(tmp_path: Path):
    """Every pre-E-R caller is unaffected: @0.1.0 is released and unchanged."""
    packet = build_extraction_input_packet(**_base())
    assert packet["contract"] == PACKET_CONTRACT
    assert packet["schema_version"] == "0.1.0"
    for field in ("legal_name", "company_identity_reference", "company_identity_sha256"):
        assert field not in packet


def test_a_packet_with_an_identity_pin_is_v0_2(tmp_path: Path):
    pin = _write_admission(tmp_path / "identity")
    packet = build_extraction_input_packet(
        **_base(),
        company_identity_root=tmp_path / "identity",
        company_identity_pin=pin,
    )
    assert packet["contract"] == PACKET_CONTRACT_V2
    assert packet["schema_version"] == "0.2.0"
    assert packet["legal_name"] == "HUBSPOT INC"
    assert packet["company_identity_reference"] == "admission.json"
    assert packet["company_identity_sha256"] == pin["sha256"]


def test_the_root_is_a_builder_argument_and_never_a_packet_field(tmp_path: Path):
    """The packet records what it was pinned to, not where it was read from."""
    pin = _write_admission(tmp_path / "identity")
    packet = build_extraction_input_packet(
        **_base(),
        company_identity_root=tmp_path / "identity",
        company_identity_pin=pin,
    )
    serialized = json.dumps(packet)
    assert "company_identity_root" not in packet
    assert str(tmp_path) not in serialized


@pytest.mark.parametrize(
    "schema_name,version",
    [
        ("extraction_input_packet.schema.json", "0.1.0"),
        ("extraction_input_packet.v2.schema.json", "0.2.0"),
    ],
)
def test_each_packet_validates_against_its_own_released_schema(
    tmp_path: Path, schema_name, version
):
    schema = json.loads((ROOT / "schemas" / schema_name).read_text(encoding="utf-8"))
    if version == "0.1.0":
        packet = build_extraction_input_packet(**_base())
    else:
        pin = _write_admission(tmp_path / "identity")
        packet = build_extraction_input_packet(
            **_base(),
            company_identity_root=tmp_path / "identity",
            company_identity_pin=pin,
        )
    jsonschema.validate(packet, schema)


def test_neither_schema_accepts_the_other_version(tmp_path: Path):
    v1_schema = json.loads(
        (ROOT / "schemas" / "extraction_input_packet.schema.json").read_text()
    )
    v2_schema = json.loads(
        (ROOT / "schemas" / "extraction_input_packet.v2.schema.json").read_text()
    )
    pin = _write_admission(tmp_path / "identity")
    v1 = build_extraction_input_packet(**_base())
    v2 = build_extraction_input_packet(
        **_base(),
        company_identity_root=tmp_path / "identity",
        company_identity_pin=pin,
    )
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(v1, v2_schema)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(v2, v1_schema)


# --- the claim is forbidden, the pin is required ------------------------------


@pytest.mark.parametrize("field", ["legal_name", "company_identity", "company_name"])
def test_a_caller_supplied_identity_claim_is_refused(tmp_path: Path, field):
    with pytest.raises(ExtractionError) as excinfo:
        build_extraction_input_packet(**_base(), **{field: "HUBSPOT INC"})
    assert excinfo.value.reason_code == "company_identity_pin_forbidden"


def test_a_pin_without_a_root_is_refused(tmp_path: Path):
    pin = _write_admission(tmp_path / "identity")
    with pytest.raises(ExtractionError) as excinfo:
        build_extraction_input_packet(**_base(), company_identity_pin=pin)
    assert excinfo.value.reason_code == "company_identity_root_required"


def test_a_root_without_a_pin_is_refused(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        build_extraction_input_packet(
            **_base(), company_identity_root=tmp_path / "identity"
        )
    assert excinfo.value.reason_code == "company_identity_pin_required"


def test_hydration_refuses_a_missing_root_directly(tmp_path: Path):
    with pytest.raises(ExtractionError) as excinfo:
        hydrate_company_identity(
            None,
            {"reference": "a.json", "sha256": "0" * 64},
            company_id=COMPANY,
            observation_cutoff_date=CUTOFF,
        )
    assert excinfo.value.reason_code == "company_identity_root_required"


# --- the four reconciliation equalities ---------------------------------------


@pytest.mark.parametrize(
    "override",
    [
        {"company_id": "CIK0000320193"},
        {"cik": "320193"},
        {"observation_cutoff_date": "2023-12-31"},
    ],
)
def test_a_mismatching_admission_artifact_is_refused(tmp_path: Path, override):
    pin = _write_admission(tmp_path / "identity", _admission(**override))
    with pytest.raises(ExtractionError) as excinfo:
        build_extraction_input_packet(
            **_base(),
            company_identity_root=tmp_path / "identity",
            company_identity_pin=pin,
        )
    assert excinfo.value.reason_code == "company_identity_mismatch"


def test_a_zero_padded_cik_reconciles_as_one_identity(tmp_path: Path):
    """``1404655`` and ``0001404655`` are the same firm, not two."""
    pin = _write_admission(tmp_path / "identity", _admission(cik="0001404655"))
    packet = build_extraction_input_packet(
        **_base(),
        company_identity_root=tmp_path / "identity",
        company_identity_pin=pin,
    )
    assert packet["legal_name"] == "HUBSPOT INC"


@pytest.mark.parametrize(
    "override,code",
    [
        ({"legal_name": ""}, "company_identity_invalid"),
        ({"legal_name": "   "}, "company_identity_invalid"),
        ({"company_id": "hubspot"}, "company_identity_invalid"),
        ({"cik": "not-a-number"}, "company_identity_invalid"),
        ({"observation_cutoff_date": "31/12/2024"}, "company_identity_invalid"),
    ],
)
def test_a_malformed_admission_artifact_is_refused(tmp_path: Path, override, code):
    pin = _write_admission(tmp_path / "identity", _admission(**override))
    with pytest.raises(ExtractionError) as excinfo:
        build_extraction_input_packet(
            **_base(),
            company_identity_root=tmp_path / "identity",
            company_identity_pin=pin,
        )
    assert excinfo.value.reason_code == code


def test_a_missing_legal_name_field_is_refused(tmp_path: Path):
    admission = _admission()
    del admission["legal_name"]
    pin = _write_admission(tmp_path / "identity", admission)
    with pytest.raises(ExtractionError) as excinfo:
        build_extraction_input_packet(
            **_base(),
            company_identity_root=tmp_path / "identity",
            company_identity_pin=pin,
        )
    assert excinfo.value.reason_code == "company_identity_invalid"


# --- pin integrity ------------------------------------------------------------


def test_a_tampered_admission_artifact_is_refused(tmp_path: Path):
    root = tmp_path / "identity"
    pin = _write_admission(root)
    (root / "admission.json").write_bytes(b'{"legal_name": "SOMEONE ELSE"}')
    with pytest.raises(ExtractionError) as excinfo:
        build_extraction_input_packet(
            **_base(), company_identity_root=root, company_identity_pin=pin
        )
    assert excinfo.value.reason_code == "company_identity_pin_sha_mismatch"


@pytest.mark.parametrize(
    "reference,code",
    [
        ("../escape.json", "company_identity_reference_unsafe"),
        ("/etc/passwd", "company_identity_reference_unsafe"),
        ("", "company_identity_reference_unsafe"),
        # "." resolves to the root itself, which the shared loader rejects on the
        # read/hash path rather than the reference path. Both fail closed; this
        # pins which one, rather than asserting a code it does not produce.
        (".", "company_identity_pin_sha_mismatch"),
    ],
)
def test_an_unsafe_reference_is_refused(tmp_path: Path, reference, code):
    root = tmp_path / "identity"
    _write_admission(root)
    with pytest.raises(ExtractionError) as excinfo:
        build_extraction_input_packet(
            **_base(),
            company_identity_root=root,
            company_identity_pin={"reference": reference, "sha256": "0" * 64},
        )
    assert excinfo.value.reason_code == code


def test_a_symlinked_admission_artifact_is_refused(tmp_path: Path):
    root = tmp_path / "identity"
    root.mkdir(parents=True)
    real = tmp_path / "elsewhere.json"
    payload = json.dumps(_admission(), sort_keys=True, separators=(",", ":")).encode()
    real.write_bytes(payload)
    (root / "link.json").symlink_to(real)
    with pytest.raises(ExtractionError) as excinfo:
        build_extraction_input_packet(
            **_base(),
            company_identity_root=root,
            company_identity_pin={
                "reference": "link.json",
                "sha256": hashlib.sha256(payload).hexdigest(),
            },
        )
    assert excinfo.value.reason_code == "company_identity_reference_unsafe"


def test_the_pilot_admission_artifact_carries_the_fields_this_binding_reads():
    """The shipped Pilot 0 packet is the real source, so pin what it must have."""
    admission = json.loads(
        (ROOT / "data" / "registry" / f"pilot_universe_packet_{COMPANY}.json").read_text(
            encoding="utf-8"
        )
    )
    assert admission["company_id"] == COMPANY
    assert admission["cik"].zfill(10) == COMPANY[3:]
    assert isinstance(admission["legal_name"], str) and admission["legal_name"].strip()
    assert admission["observation_cutoff_date"]


# --- the authoritative publication date (ADR-036, E-R correction) --------------

# The pre-E-R v0.1 bytes for the canonical fixture below, computed from the
# committed implementation at 79b5e2a. E-R must not move this value.
PRE_E_R_V1_PACKET_SHA256 = (
    "f0ca7ce8cb80b5b2b97ccaa6ce11872d1780105560acd7c6d289f8bf1a6bcc96"
)


def _canonical_v1_packet():
    """The fixture the pre-E-R digest above was computed from."""
    return build_extraction_input_packet(
        stage="product_extraction",
        company_id=COMPANY,
        observation_cutoff_date=CUTOFF,
        passages=[_passage("p-1", "the product ships an assistant")],
        document_publication_dates={"sec-1": "2024-02-14", "sec-late": "2025-06-01"},
        coverage_artifact={
            "reference": "coverage/source_family_coverage.json",
            "sha256": "d" * 64,
        },
        source_snapshot_manifest={
            "reference": "snapshots/manifest.json",
            "sha256": "e" * 64,
        },
    )


def test_the_v0_1_packet_bytes_are_unchanged_by_e_r():
    """Regression literal: @0.1.0 is released, so its bytes may not move."""
    from dynamic_ai_products.extraction.input_packet import packet_bytes

    packet = _canonical_v1_packet()
    assert packet["contract"] == PACKET_CONTRACT
    assert (
        hashlib.sha256(packet_bytes(packet)).hexdigest() == PRE_E_R_V1_PACKET_SHA256
    )


def test_the_v0_1_route_adds_no_publication_date():
    """The authoritative copy happens only on the @0.2.0 path."""
    packet = _canonical_v1_packet()
    assert "publication_date" not in packet["passages"][0]


def test_the_v0_2_passages_carry_the_authoritative_publication_date(tmp_path: Path):
    pin = _write_admission(tmp_path / "identity")
    packet = build_extraction_input_packet(
        **_base(),
        company_identity_root=tmp_path / "identity",
        company_identity_pin=pin,
    )
    assert packet["passages"][0]["publication_date"] == "2024-02-14"


def test_a_caller_supplied_passage_date_cannot_override_the_authoritative_one(
    tmp_path: Path,
):
    """document_publication_dates is the authority, not the passage mapping."""
    pin = _write_admission(tmp_path / "identity")
    hostile = _passage("p-1", "the product ships an assistant")
    hostile["publication_date"] = "1999-01-01"
    packet = build_extraction_input_packet(
        **_base(passages=[hostile]),
        company_identity_root=tmp_path / "identity",
        company_identity_pin=pin,
    )
    assert packet["passages"][0]["publication_date"] == "2024-02-14"


def test_the_builder_never_mutates_caller_passages(tmp_path: Path):
    pin = _write_admission(tmp_path / "identity")
    caller = [_passage("p-1", "the product ships an assistant")]
    before = json.dumps(caller, sort_keys=True)
    build_extraction_input_packet(
        **_base(passages=caller),
        company_identity_root=tmp_path / "identity",
        company_identity_pin=pin,
    )
    assert json.dumps(caller, sort_keys=True) == before
    assert "publication_date" not in caller[0]


def test_a_passage_with_no_authoritative_date_never_reaches_the_renderer(
    tmp_path: Path,
):
    """The admissibility filter drops it first, so the packet emits none.

    The builder also refuses a passage whose source has no well-formed date, but
    that guard is defence in depth rather than the active gate: an undatable
    passage cannot satisfy ``publication_date <= observation_cutoff_date`` and is
    already dropped as temporally invalid. What matters is that no passage is ever
    emitted carrying an unusable date, and that the renderer then refuses rather
    than sending an empty passage block.
    """
    from dynamic_ai_products.extraction.contents_renderer import (
        render_provider_contents,
    )

    pin = _write_admission(tmp_path / "identity")
    packet = build_extraction_input_packet(
        **_base(document_publication_dates={"sec-1": "not-a-date"}),
        company_identity_root=tmp_path / "identity",
        company_identity_pin=pin,
    )
    assert packet["passages"] == []
    assert packet["filter_ledger"]["temporal_drop_count"] == 1
    with pytest.raises(ExtractionError) as excinfo:
        render_provider_contents(
            stage="product_extraction",
            prompt_text="{{passages_with_ids}}",
            packet=packet,
        )
    assert excinfo.value.reason_code == "contents_context_invalid"


def test_the_authoritative_date_reaches_the_rendered_contents(tmp_path: Path):
    from dynamic_ai_products.extraction.contents_renderer import (
        render_provider_contents,
    )

    pin = _write_admission(tmp_path / "identity")
    hostile = _passage("p-1", "the product ships an assistant")
    hostile["publication_date"] = "1999-01-01"
    packet = build_extraction_input_packet(
        **_base(passages=[hostile]),
        company_identity_root=tmp_path / "identity",
        company_identity_pin=pin,
    )
    rendered = render_provider_contents(
        stage="product_extraction",
        prompt_text="{{passages_with_ids}}",
        packet=packet,
    )
    assert "[publication_date: 2024-02-14]" in rendered
    assert "1999-01-01" not in rendered
