"""PCT_Dev30_v0 cohort manifest guard tests -- fully offline.

The manifest at ``evals/registries/pct_dev30_v0_manifest.json`` persists the
30-firm PCT_Dev30_v0 roster, its dev/holdout partition, and its corrected
difficulty ratings, replacing the conversational-only record. Every row's
firm/filing identity is claimed from the legacy THESIS_REPO manifest, not
from this project's Stage 00C acquisition pipeline; no row may carry a
``source_id`` key or any ``sec-primary:``-prefixed value. These tests
validate the committed file only -- nothing here reads the legacy repository,
runs a prompt, calls a model, or scores Dev30.
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = ROOT / "evals" / "registries" / "pct_dev30_v0_manifest.json"
MANIFEST = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))

EXPECTED_HOLDOUT_TICKERS = {"APPF", "PD", "FDS", "YELP", "MQ", "CLVT"}
EXPECTED_VISIBLE_COUNT = 24
EXPECTED_HOLDOUT_COUNT = 6
EXPECTED_TOTAL = 30

EXPECTED_BLOCK_COUNTS = {
    "focused_saas": 2,
    "multi_product_platform": 7,
    "cloud_infra_security": 7,
    "data_analytics": 4,
    "media_education_content": 4,
    "boundary_cases": 6,
}

EXPECTED_DIFFICULTY_COUNTS = {"easy": 1, "medium": 5, "hard": 24}


def _rows():
    return MANIFEST["rows"]


def test_manifest_declares_contract_and_cohort_version():
    assert MANIFEST["cohort_contract"] == "pct_dev30_v0_manifest@0.1.0"
    assert MANIFEST["cohort_version"] == "PCT_Dev30_v0"
    assert MANIFEST["counts"] == {
        "total_rows": EXPECTED_TOTAL,
        "visible": EXPECTED_VISIBLE_COUNT,
        "holdout": EXPECTED_HOLDOUT_COUNT,
    }


def test_exactly_thirty_rows():
    assert len(_rows()) == EXPECTED_TOTAL


def test_no_duplicate_ticker_accession_or_text_path():
    rows = _rows()
    tickers = [r["ticker"] for r in rows]
    accessions = [r["accession"] for r in rows]
    paths = [r["legacy_text_path"] for r in rows]
    assert len(set(tickers)) == EXPECTED_TOTAL, "duplicate ticker in manifest"
    assert len(set(accessions)) == EXPECTED_TOTAL, "duplicate accession in manifest"
    assert len(set(paths)) == EXPECTED_TOTAL, "duplicate legacy_text_path in manifest"


def test_text_path_is_repository_relative_not_absolute():
    for r in _rows():
        assert not r["legacy_text_path"].startswith("/"), r["ticker"]
        assert not r["legacy_text_path"].startswith("~"), r["ticker"]


def test_cik_is_normalized_ten_digit():
    for r in _rows():
        cik = r["cik"]
        assert len(cik) == 10 and cik.isdigit(), (r["ticker"], cik)


def test_accession_matches_sec_dashed_form():
    import re

    pattern = re.compile(r"^\d{10}-\d{2}-\d{6}$")
    for r in _rows():
        assert pattern.match(r["accession"]), (r["ticker"], r["accession"])


def test_form_is_10k_for_every_row():
    for r in _rows():
        assert r["form"] == "10-K", (r["ticker"], r["form"])


def test_legacy_file_sha256_is_well_formed_per_row():
    import re

    pattern = re.compile(r"^[0-9a-f]{64}$")
    for r in _rows():
        assert pattern.match(r["legacy_file_sha256"]), r["ticker"]


def test_dev_holdout_partition_counts_and_exact_membership():
    rows = _rows()
    visible = [r["ticker"] for r in rows if r["dev_holdout_partition"] == "visible"]
    holdout = [r["ticker"] for r in rows if r["dev_holdout_partition"] == "holdout"]
    assert len(visible) == EXPECTED_VISIBLE_COUNT
    assert len(holdout) == EXPECTED_HOLDOUT_COUNT
    assert set(holdout) == EXPECTED_HOLDOUT_TICKERS
    assert set(visible) | set(holdout) == {r["ticker"] for r in rows}
    assert set(visible) & set(holdout) == set()
    for r in rows:
        assert r["dev_holdout_partition"] in ("visible", "holdout"), r["ticker"]


def test_stratification_block_counts_match_recovered_record():
    rows = _rows()
    counts = {}
    for r in rows:
        counts[r["stratification_block"]] = counts.get(r["stratification_block"], 0) + 1
    assert counts == EXPECTED_BLOCK_COUNTS


def test_focused_saas_block_has_no_holdout_member():
    # The confirmation-skim turn deliberately exempted this block from the
    # holdout split -- it has only two members and would otherwise lose all
    # floor-behavior coverage.
    for r in _rows():
        if r["stratification_block"] == "focused_saas":
            assert r["dev_holdout_partition"] == "visible", r["ticker"]


def test_difficulty_rating_counts_match_recovered_record():
    rows = _rows()
    counts = {"easy": 0, "medium": 0, "hard": 0}
    for r in rows:
        assert r["difficulty_rating"] in counts, (r["ticker"], r["difficulty_rating"])
        counts[r["difficulty_rating"]] += 1
    assert counts == EXPECTED_DIFFICULTY_COUNTS


def test_cohort_version_is_uniform_per_row():
    for r in _rows():
        assert r["cohort_version"] == "PCT_Dev30_v0", r["ticker"]


def test_identity_provenance_present_and_disclaims_stage00c():
    for r in _rows():
        note = r["identity_provenance"]
        assert note, r["ticker"]
        assert "not independently verified" in note
        assert "Stage 00C" in note
        assert "sec-primary" in note


def test_no_row_claims_a_stage00c_source_id():
    # The blocking correction from an earlier turn: Dev30 legacy rows must
    # never carry a source_id key or a sec-primary:-prefixed value anywhere.
    for r in _rows():
        assert "source_id" not in r, r["ticker"]
        for value in r.values():
            if isinstance(value, str):
                assert not value.startswith("sec-primary:"), (r["ticker"], value)


def test_legacy_corpus_reference_marks_remote_as_descriptive_only():
    ref = MANIFEST["legacy_corpus_reference"]
    assert ref["manifest_relative_path"] == "data/provenance/final_filing_manifest.csv"
    assert "not a verification basis" in ref["verification_note"]


def test_manifest_top_level_and_nested_key_sets_are_exact():
    # Makes the claimed schema-less additional-properties discipline
    # executable rather than descriptive: no key may be silently added to or
    # dropped from the top level or either nested object without this test
    # failing.
    assert set(MANIFEST.keys()) == {
        "cohort_contract",
        "cohort_version",
        "description",
        "legacy_corpus_reference",
        "counts",
        "rows",
    }
    assert set(MANIFEST["legacy_corpus_reference"].keys()) == {
        "repo_remote",
        "manifest_relative_path",
        "local_head_sha_at_read",
        "file_last_commit_sha",
        "verification_note",
    }
    assert set(MANIFEST["counts"].keys()) == {"total_rows", "visible", "holdout"}


def test_every_row_has_exactly_the_twelve_intended_keys():
    expected_keys = {
        "cohort_version",
        "ticker",
        "cik",
        "accession",
        "filing_date",
        "form",
        "legacy_text_path",
        "legacy_file_sha256",
        "stratification_block",
        "dev_holdout_partition",
        "difficulty_rating",
        "identity_provenance",
    }
    for r in _rows():
        assert set(r.keys()) == expected_keys, r.get("ticker")
