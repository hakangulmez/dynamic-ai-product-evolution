"""PCT_Dev30_v0 Item 1 locator ledger guard tests.

The ledger at ``evals/registries/pct_dev30_v0_item1_locator_ledger.json``
persists, for all 30 committed PCT_Dev30_v0 rows, the provenance fields the
``dynamic_ai_products.dev30.item1_locator`` module produces. It binds to the
already-committed cohort manifest by that file's own SHA-256, so a changed
cohort cannot silently reuse a stale ledger. No row here carries a Stage 00C
``source_id`` or a ``sec-primary:``-prefixed value.

Most tests here are fully offline (committed JSON only). The final test is
skip-guarded: it re-reads the local legacy THESIS_REPO checkout and
recomputes all 30 rows from raw bytes when that checkout is available,
skipping cleanly when it is not. Nothing here writes a file, runs a prompt,
calls a model, scores Dev30, or makes a network request.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from dynamic_ai_products.dev30.item1_locator import (
    ITEM_ONE_LOCATOR_VERSION,
    locate_item1_span,
)

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "evals" / "registries" / "pct_dev30_v0_manifest.json"
LEDGER_PATH = ROOT / "evals" / "registries" / "pct_dev30_v0_item1_locator_ledger.json"

MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
LEDGER = json.loads(LEDGER_PATH.read_text(encoding="utf-8"))

EXPECTED_TOTAL = 30

LEGACY_CORPUS_ROOT = Path(
    os.environ.get(
        "DEV30_LEGACY_CORPUS_ROOT",
        "/Users/hakanzekigulmez/Documents/thesis_repo_rebuild",
    )
)


def _ledger_rows():
    return LEDGER["rows"]


def _manifest_rows():
    return MANIFEST["rows"]


def test_ledger_declares_contract_and_locator_version():
    assert LEDGER["ledger_contract"] == "pct_dev30_v0_item1_locator_ledger@0.1.0"
    assert LEDGER["item_one_locator_version"] == ITEM_ONE_LOCATOR_VERSION
    assert LEDGER["cohort_version"] == MANIFEST["cohort_version"]
    assert LEDGER["counts"] == {"total_rows": EXPECTED_TOTAL}


def test_ledger_top_level_and_counts_key_sets_are_exact():
    assert set(LEDGER.keys()) == {
        "ledger_contract",
        "item_one_locator_version",
        "cohort_manifest_relative_path",
        "cohort_manifest_sha256",
        "cohort_version",
        "counts",
        "rows",
    }
    assert set(LEDGER["counts"].keys()) == {"total_rows"}


def test_every_ledger_row_has_exactly_the_seven_intended_keys():
    expected_keys = {
        "ticker",
        "legacy_file_sha256",
        "item_one_locator_version",
        "item_one_char_start",
        "item_one_char_end",
        "source_text_hash",
        "legacy_source_id",
    }
    for row in _ledger_rows():
        assert set(row.keys()) == expected_keys, row.get("ticker")


def test_exactly_thirty_ledger_rows_no_duplicates():
    rows = _ledger_rows()
    assert len(rows) == EXPECTED_TOTAL
    tickers = [r["ticker"] for r in rows]
    assert len(set(tickers)) == EXPECTED_TOTAL


def test_source_text_hash_and_legacy_source_id_are_consistent():
    for row in _ledger_rows():
        assert row["legacy_source_id"] == (
            f"legacy-item1:dev30-v0:{row['source_text_hash']}"
        )
        assert len(row["source_text_hash"]) == 64
        assert all(c in "0123456789abcdef" for c in row["source_text_hash"])


def test_item_one_locator_version_is_uniform_and_fixed():
    for row in _ledger_rows():
        assert row["item_one_locator_version"] == "dev30-item1-marker-v1"


def test_no_row_claims_a_stage00c_source_id():
    for row in _ledger_rows():
        assert "source_id" not in row, row["ticker"]
        for value in row.values():
            if isinstance(value, str):
                assert not value.startswith("sec-primary:"), (row["ticker"], value)


def test_char_offsets_are_nonnegative_and_ordered():
    for row in _ledger_rows():
        assert row["item_one_char_start"] >= 0, row["ticker"]
        assert row["item_one_char_end"] > row["item_one_char_start"], row["ticker"]


def test_ledger_binds_to_the_current_cohort_manifest_by_sha256():
    # The binding mechanism: a changed manifest changes this hash, and this
    # test catches the drift immediately rather than letting a stale ledger
    # be silently reused against a different cohort.
    assert LEDGER["cohort_manifest_relative_path"] == (
        "evals/registries/pct_dev30_v0_manifest.json"
    )
    actual_manifest_sha256 = hashlib.sha256(
        MANIFEST_PATH.read_bytes()
    ).hexdigest()
    assert LEDGER["cohort_manifest_sha256"] == actual_manifest_sha256


def test_ledger_tickers_and_legacy_file_sha256_match_the_manifest_one_to_one():
    manifest_by_ticker = {r["ticker"]: r for r in _manifest_rows()}
    ledger_tickers = {r["ticker"] for r in _ledger_rows()}
    assert ledger_tickers == set(manifest_by_ticker.keys())
    for row in _ledger_rows():
        assert row["legacy_file_sha256"] == (
            manifest_by_ticker[row["ticker"]]["legacy_file_sha256"]
        )


@pytest.mark.skipif(
    not LEGACY_CORPUS_ROOT.is_dir(),
    reason="local legacy THESIS_REPO checkout not available",
)
def test_ledger_reproduces_from_the_legacy_checkout_when_available():
    manifest_by_ticker = {r["ticker"]: r for r in _manifest_rows()}
    for row in _ledger_rows():
        manifest_row = manifest_by_ticker[row["ticker"]]
        path = LEGACY_CORPUS_ROOT / manifest_row["legacy_text_path"]
        raw = path.read_bytes()

        assert hashlib.sha256(raw).hexdigest() == row["legacy_file_sha256"], (
            row["ticker"], "legacy file bytes have drifted since the ledger was built"
        )

        located = locate_item1_span(raw)
        assert located.item_one_char_start == row["item_one_char_start"], row["ticker"]
        assert located.item_one_char_end == row["item_one_char_end"], row["ticker"]
        assert located.source_text_hash == row["source_text_hash"], row["ticker"]
        assert located.legacy_source_id == row["legacy_source_id"], row["ticker"]
