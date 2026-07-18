from datetime import date

from dynamic_ai_products.universe.models import BaselineEvidencePacket, PacketFailure
from dynamic_ai_products.universe.packets import build_packet

from universe_test_helpers import make_filer

CUTOFF = date(2022, 12, 31)


def passage(pid: str, section: str, day: str, text: str) -> dict:
    return {
        "passage_id": pid,
        "source_id": "fixture:src",
        "section": section,
        "publication_date": day,
        "text": text,
    }


def test_valid_packet_reports_missing_sections() -> None:
    packet = build_packet(
        make_filer(),
        [
            passage("p1", "ITEM1_OVERVIEW", "2022-09-15", "We provide software."),
            passage("p2", "PRODUCTS_SERVICES", "2022-09-15", "The product edits documents."),
        ],
        CUTOFF,
    )
    assert isinstance(packet, BaselineEvidencePacket)
    assert "COVER_PAGE" in packet.missing_sections
    assert packet.insufficient_evidence is False


def test_missing_core_sections_flag_insufficient_evidence() -> None:
    packet = build_packet(
        make_filer(),
        [passage("p1", "COVER_PAGE", "2022-09-15", "Annual report.")],
        CUTOFF,
    )
    assert isinstance(packet, BaselineEvidencePacket)
    assert packet.insufficient_evidence is True


def test_post_cutoff_passage_is_rejected_as_temporal_leakage() -> None:
    result = build_packet(
        make_filer(),
        [
            passage("p1", "ITEM1_OVERVIEW", "2022-09-15", "We provide software."),
            passage("p2", "PRODUCTS_SERVICES", "2023-05-01", "Later AI launch."),
        ],
        CUTOFF,
    )
    assert isinstance(result, PacketFailure)
    assert result.reason_code == "TEMPORAL_LEAKAGE"
    assert "2023-05-01" in result.detail


def test_same_day_as_cutoff_is_eligible() -> None:
    result = build_packet(
        make_filer(),
        [passage("p1", "ITEM1_OVERVIEW", "2022-12-31", "We provide software.")],
        CUTOFF,
    )
    assert isinstance(result, BaselineEvidencePacket)


def test_empty_and_invalid_passages_fail_explicitly() -> None:
    empty = build_packet(make_filer(), [], CUTOFF)
    assert isinstance(empty, PacketFailure)
    assert empty.reason_code == "NO_PASSAGES"

    bad_section = build_packet(
        make_filer(),
        [passage("p1", "NOT_A_SECTION", "2022-09-15", "text")],
        CUTOFF,
    )
    assert isinstance(bad_section, PacketFailure)
    assert bad_section.reason_code == "INVALID_PASSAGE"
