"""The typed failure boundary: WriteOnceError never escapes (ADR-033)."""

from __future__ import annotations

from pathlib import Path

import pytest

from dynamic_ai_products.extraction.errors import (
    ExtractionError,
    translate_write_once_error,
)
from dynamic_ai_products.extraction.raw_artifacts import write_artifact
from dynamic_ai_products.provenance import WriteOnceError


def test_extraction_error_carries_a_stable_machine_readable_code():
    error = ExtractionError("boom", reason_code="write_error", detail="d", stop_reason="s")
    assert error.reason_code == "write_error"
    assert error.detail == "d"
    assert error.stop_reason == "s"
    assert str(error) == "boom"


def test_optional_fields_default_to_none():
    error = ExtractionError("boom", reason_code="pin_invalid")
    assert error.detail is None and error.stop_reason is None


def test_destination_exists_translates_to_its_own_code():
    translated = translate_write_once_error(
        WriteOnceError("exists", category="destination_exists", cleanup_detail="cd")
    )
    assert isinstance(translated, ExtractionError)
    assert translated.reason_code == "destination_exists"
    assert translated.detail == "cd"


@pytest.mark.parametrize("category", ["write_failed", "verification_failed"])
def test_every_other_category_translates_to_write_error(category):
    translated = translate_write_once_error(WriteOnceError("x", category=category))
    assert translated.reason_code == "write_error"


def test_write_once_error_never_escapes_the_package_boundary(tmp_path: Path):
    write_artifact(tmp_path, "a/b.json", b"{}\n")
    # The second write must surface as ExtractionError, not WriteOnceError.
    with pytest.raises(ExtractionError) as excinfo:
        write_artifact(tmp_path, "a/b.json", b"{}\n")
    assert excinfo.value.reason_code == "destination_exists"
    assert not isinstance(excinfo.value, WriteOnceError)


def test_a_pre_existing_artifact_is_never_overwritten(tmp_path: Path):
    write_artifact(tmp_path, "keep.json", b"original\n")
    with pytest.raises(ExtractionError):
        write_artifact(tmp_path, "keep.json", b"replacement\n")
    assert (tmp_path / "keep.json").read_bytes() == b"original\n"
