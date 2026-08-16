"""DERA FSDS validation tests (ADR-081) — fully offline.

Every run builds its frame from the committed synthetic fixtures into a
temporary directory; nothing reads ``data/runs``, no network exists, and no
model is called. DERA is validation-only: these tests also pin that the
frame inputs are consumed read-only.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.universe.frame import run_frame_builder
from dynamic_ai_products.universe.frame_dera_validation import (
    DeraInputError,
    parse_sub_file,
    run_dera_validation,
)
from dynamic_ai_products.universe.io_utils import read_json, sha256_file

ROOT = Path(__file__).resolve().parents[2]
FRAME_FIXTURE_DIR = ROOT / "evals" / "fixtures" / "edgar_full_index"
DERA_FIXTURE_DIR = ROOT / "evals" / "fixtures" / "dera_fsds"
PROJECT_CONFIG = ROOT / "configs" / "project.yaml"
VALIDATION_SCHEMA_PATH = ROOT / "schemas" / "frame_dera_validation_manifest.schema.json"
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
EXPECTED = read_json(DERA_FIXTURE_DIR / "expected_validation.json")

FIXED_CLOCK = lambda: datetime(2026, 3, 3, 8, 0, 0, tzinfo=timezone.utc)  # noqa: E731

SUB_HEADER = (
    "adsh\tcik\tname\tsic\tcountryba\tstprba\tcityba\tzipba\tbas1\tbas2\tbaph\t"
    "countryma\tstprma\tcityma\tzipma\tmas1\tmas2\tcountryinc\tstprinc\tein\t"
    "former\tchanged\tafs\twksi\tfye\tform\tperiod\tfy\tfp\tfiled\taccepted\t"
    "prevrpt\tdetail\tinstance\tnciks\taciks"
)
_COLS = SUB_HEADER.split("\t")


def _sub_line(adsh, cik, name, form, filed, nciks, aciks):
    values = {c: "" for c in _COLS}
    values.update({"adsh": adsh, "cik": cik, "name": name, "form": form,
                   "filed": filed, "nciks": nciks, "aciks": aciks})
    return "\t".join(values[c] for c in _COLS)


def _sub_text(*rows: str) -> str:
    return SUB_HEADER + "\n" + "\n".join(rows) + "\n"


@pytest.fixture(scope="module")
def fixture_frame(tmp_path_factory: pytest.TempPathFactory):
    """A frame built from the committed fixtures, in a temp dir."""
    out = tmp_path_factory.mktemp("frame")
    result = run_frame_builder(
        repo_root=ROOT,
        project_config_path=PROJECT_CONFIG,
        index_dir=FRAME_FIXTURE_DIR,
        output_dir=out,
        run_id="dera-tests-frame",
        filing_window_start=date(2022, 8, 1),
        filing_window_end=date(2023, 2, 28),
    )
    return result.run_dir / "filer_frame_manifest.json"


def _validate(frame_manifest: Path, dera_dir: Path, out: Path, run_id: str,
              dry_run: bool = False):
    return run_dera_validation(
        repo_root=ROOT,
        frame_manifest_path=frame_manifest,
        dera_dir=dera_dir,
        output_dir=out,
        run_id=run_id,
        clock=FIXED_CLOCK,
        dry_run=dry_run,
    )


@pytest.fixture(scope="module")
def gold_run(fixture_frame, tmp_path_factory: pytest.TempPathFactory):
    return _validate(
        fixture_frame, DERA_FIXTURE_DIR,
        tmp_path_factory.mktemp("val"), "pytest-dera-gold",
    )


def _mutated_bundle(tmp_path: Path, *, extra_rows: tuple = (),
                    replace_rows: dict | None = None) -> Path:
    """Copy the DERA fixture bundle and mutate sub_2022q4.tsv rows."""
    bundle = tmp_path / "dera"
    shutil.copytree(DERA_FIXTURE_DIR, bundle)
    target = bundle / "sub_2022q4.tsv"
    lines = target.read_text(encoding="utf-8").splitlines()
    if replace_rows:
        for index, new in replace_rows.items():
            lines[index] = new
    lines.extend(extra_rows)
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bundle


# --- SUB parser contract ------------------------------------------------------


def test_parser_requires_named_columns_and_ignores_extras() -> None:
    parsed = parse_sub_file(
        _sub_text(_sub_line("0002000001-22-000010", "2000001", "X", "10-K",
                            "20220915", "1", "")),
        source_name="ok.tsv",
    )
    assert len(parsed.rows) == 1 and not parsed.parse_failures
    with pytest.raises(DeraInputError, match="missing required columns"):
        parse_sub_file("adsh\tcik\tform\n", source_name="short.tsv")


def test_parser_records_row_failures_explicitly() -> None:
    short_row = "0002000001-22-000010\t2000001\tonly-three"
    parsed = parse_sub_file(
        _sub_text(short_row), source_name="rows.tsv"
    )
    assert [f.reason_code for f in parsed.parse_failures] == ["wrong_field_count"]


def test_partial_terminal_token_is_valid_and_never_inferred() -> None:
    parsed = parse_sub_file(
        _sub_text(_sub_line("0002000015-22-000003", "2000015", "X", "40-F",
                            "20221115", "3", "PARTIAL")),
        source_name="partial.tsv",
    )
    sub = parsed.rows[0]
    assert sub.registrant_set_partial is True
    assert sub.additional_ciks == []  # nciks=3, but omitted CIKs never inferred
    assert [p[0] for p in sub.registrant_pairs()] == ["0002000015"]


def test_partial_must_be_terminal() -> None:
    parsed = parse_sub_file(
        _sub_text(_sub_line("0002000015-22-000003", "2000015", "X", "40-F",
                            "20221115", "3", "PARTIAL 2000016")),
        source_name="badpartial.tsv",
    )
    assert [f.reason_code for f in parsed.parse_failures] == ["malformed_aciks"]


def test_nciks_must_equal_declared_without_partial() -> None:
    bad = parse_sub_file(
        _sub_text(_sub_line("0002000012-23-000004", "2000012", "X", "10-K",
                            "20230210", "2", "2000013 2000014")),
        source_name="nciks.tsv",
    )
    assert [f.reason_code for f in bad.parse_failures] == ["nciks_inconsistent"]
    ok = parse_sub_file(
        _sub_text(_sub_line("0002000015-22-000003", "2000015", "X", "40-F",
                            "20221115", "7", "2000016 PARTIAL")),
        source_name="partialn.tsv",
    )
    assert ok.rows[0].additional_ciks == ["0002000016"]
    assert ok.rows[0].registrant_set_partial is True


def test_nciks_must_be_a_positive_integer() -> None:
    for value in ("0", "-1"):
        parsed = parse_sub_file(
            _sub_text(_sub_line("0002000001-22-000010", "2000001", "X", "10-K",
                                "20220915", value, "")),
            source_name="zero.tsv",
        )
        assert [f.reason_code for f in parsed.parse_failures] == [
            "invalid_nciks"
        ], value


def test_partial_requires_nciks_above_declared_count() -> None:
    # PARTIAL asserts at least one omitted co-registrant, so nciks equal to
    # the declared count is inconsistent.
    for nciks, aciks in (("1", "PARTIAL"), ("2", "2000016 PARTIAL")):
        parsed = parse_sub_file(
            _sub_text(_sub_line("0002000015-22-000003", "2000015", "X", "40-F",
                                "20221115", nciks, aciks)),
            source_name="partialcard.tsv",
        )
        assert [f.reason_code for f in parsed.parse_failures] == [
            "nciks_inconsistent"
        ], (nciks, aciks)
    ok = parse_sub_file(
        _sub_text(_sub_line("0002000015-22-000003", "2000015", "X", "40-F",
                            "20221115", "2", "PARTIAL")),
        source_name="partialok.tsv",
    )
    assert ok.rows[0].registrant_set_partial is True
    assert ok.rows[0].additional_ciks == []


# --- gold end-to-end ----------------------------------------------------------


def test_gold_counts_and_gate(gold_run) -> None:
    assert gold_run.gate_status == "pass" == EXPECTED["gate_status"]
    assert gold_run.failed_conditions == []
    assert gold_run.counts == EXPECTED["counts"]
    assert all(gold_run.reconciliation.values())


def test_gold_noncoverage_table_total_and_per_form(gold_run) -> None:
    assert gold_run.noncoverage_by_form == EXPECTED["noncoverage_by_form"]
    total = gold_run.noncoverage_by_form["total"]
    assert total["noncoverage_rate"] == pytest.approx(1 / 7, abs=1e-6)
    # Boundary and partial records are excluded from the rate denominator,
    # reported beside it, never folded in.
    assert total["observable_records"] == total["records"] - 2


def test_gold_category_members(gold_run) -> None:
    manifest = read_json(gold_run.manifest_path)
    samples = manifest["samples"]
    def keys(name):
        return [[e["cik"], e["accession_number"]] for e in samples[name]]
    for name, expected in EXPECTED["key_members"].items():
        assert keys(name) == expected, name


def test_manifest_is_schema_valid_with_provenance(gold_run, fixture_frame) -> None:
    manifest = read_json(gold_run.manifest_path)
    Draft202012Validator(read_json(VALIDATION_SCHEMA_PATH)).validate(manifest)
    assert manifest["frame_manifest_sha256"] == sha256_file(fixture_frame)
    assert manifest["observed_through"] == "2022-12-31"
    for entry in manifest["dera_inputs"]:
        assert entry["sha256"] == sha256_file(DERA_FIXTURE_DIR / entry["filename"])
    assert manifest["gate"] == {
        "status": "pass",
        "rule_id": "frame_dera_validation_gate_v1",
        "failed_conditions": [],
    }


def test_dera_is_validation_only_frame_untouched(gold_run, fixture_frame) -> None:
    # The validator consumes the frame read-only: every frame artifact still
    # matches the frame manifest's own output hashes after validation.
    frame_manifest = read_json(fixture_frame)
    frame_dir = fixture_frame.parent
    for name, expected in frame_manifest["output_hashes"].items():
        assert sha256_file(frame_dir / name) == expected


def test_manifest_bytes_deterministic_under_injected_clock(
    fixture_frame, gold_run, tmp_path: Path
) -> None:
    second = _validate(fixture_frame, DERA_FIXTURE_DIR, tmp_path, "pytest-dera-gold")
    assert (
        second.manifest_path.read_bytes() == gold_run.manifest_path.read_bytes()
    )


def test_run_directory_never_reused_and_dry_run_writes_nothing(
    fixture_frame, gold_run, tmp_path: Path
) -> None:
    with pytest.raises(FileExistsError):
        _validate(fixture_frame, DERA_FIXTURE_DIR,
                  gold_run.run_dir.parent, gold_run.run_id)
    out = tmp_path / "dry"
    result = _validate(fixture_frame, DERA_FIXTURE_DIR, out, "dry", dry_run=True)
    assert result.manifest_path is None and not out.exists()


# --- attribution: noncoverage vs right boundary -------------------------------


def test_absence_after_observed_through_is_right_boundary_not_noncoverage(
    gold_run,
) -> None:
    counts = gold_run.counts
    # 0002000001-23-000002 filed 2023-01-25 > observed_through 2022-12-31.
    assert counts["annual_right_boundary_unobserved"] == 1
    # 0002000002-22-000004 filed 2022-08-05 <= observed_through.
    assert counts["annual_noncoverage"] == 1


def test_partial_unresolved_is_nongating_and_outside_rates(gold_run) -> None:
    counts = gold_run.counts
    assert counts["annual_unresolved_partial_registrant_set"] == 1
    assert counts["annual_matched_under_partial"] == 1
    assert gold_run.gate_status == "pass"
    assert gold_run.noncoverage_by_form["40-F"]["noncoverage"] == 0


# --- amendment stratum is report-only -----------------------------------------


def test_amendment_stratum_reconciles_but_never_gates(
    fixture_frame, tmp_path: Path
) -> None:
    # Mutate the amendment row's filed date to a DERA-earlier value (never
    # drift): an amendment identity mismatch appears and reconciles, and the
    # annual gate still passes.
    bundle = _mutated_bundle(
        tmp_path,
        replace_rows={4: _sub_line("0002000001-22-000015", "2000001",
                                   "SYNTHETIC LEDGERWORKS INC", "10-K/A",
                                   "20221119", "1", "")},
    )
    result = _validate(fixture_frame, bundle, tmp_path / "out", "amendment-mismatch")
    assert result.counts["amendment_identity_mismatch"] == 1
    assert result.counts["amendment_matched"] == 0
    assert all(result.reconciliation.values())
    assert result.gate_status == "pass"  # report-only stratum


def _bundle_with_combined_row(tmp_path: Path, combined_row: str) -> Path:
    """Copy the bundle and replace the combined 10-K row in sub_2023q1.tsv."""
    bundle = tmp_path / "dera"
    shutil.copytree(DERA_FIXTURE_DIR, bundle)
    target = bundle / "sub_2023q1.tsv"
    lines = target.read_text(encoding="utf-8").splitlines()
    lines[1] = combined_row
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return bundle


def test_missing_co_registrant_in_complete_dera_set_fails_the_gate(
    fixture_frame, tmp_path: Path
) -> None:
    # (a) A non-PARTIAL DERA registrant set omitting a known FRAME co-filer
    # is a contradiction: the set claims completeness. nciks stays consistent.
    bundle = _bundle_with_combined_row(
        tmp_path,
        _sub_line("0002000012-23-000004", "2000012",
                  "SYNTHETIC COMBINED PARENT CORP", "10-K", "20230210",
                  "2", "2000013"),
    )
    result = _validate(fixture_frame, bundle, tmp_path / "out", "registrant-missing")
    assert result.counts["dera_parse_failures"] == 0
    assert result.counts["annual_frame_filer_not_in_dera_registrants"] == 1
    assert result.gate_status == "fail"
    assert (
        "annual_frame_filer_not_in_dera_registrants > 0"
        in result.failed_conditions
    )


def test_declared_co_registrant_absent_from_frame_fails_the_gate(
    fixture_frame, tmp_path: Path
) -> None:
    # (b) A declared co-registrant the index never listed is a contradiction
    # in the other direction. nciks stays consistent.
    bundle = _bundle_with_combined_row(
        tmp_path,
        _sub_line("0002000012-23-000004", "2000012",
                  "SYNTHETIC COMBINED PARENT CORP", "10-K", "20230210",
                  "4", "2000013 2000014 2000017"),
    )
    result = _validate(fixture_frame, bundle, tmp_path / "out", "registrant-extra")
    assert result.counts["dera_parse_failures"] == 0
    assert result.counts["annual_dera_registrant_not_in_frame"] == 1
    assert result.gate_status == "fail"
    assert "annual_dera_registrant_not_in_frame > 0" in result.failed_conditions


def test_parse_failure_alone_fails_the_gate_with_manifest_written(
    fixture_frame, tmp_path: Path
) -> None:
    # A malformed/inconsistent DERA annual row must not yield a passing
    # validation merely because it was excluded from comparison. nciks BELOW
    # the declared count is genuinely impossible and stays fatal (ADR-085).
    bundle = _mutated_bundle(
        tmp_path,
        extra_rows=(_sub_line("0002000098-22-000001", "2000098",
                              "SYNTHETIC BADCARD CORP", "10-K", "20221001",
                              "1", "2000096 2000095"),),
    )
    result = _validate(fixture_frame, bundle, tmp_path / "out", "parse-failure-gate")
    assert result.counts["dera_parse_failures"] == 1
    assert result.gate_status == "fail"
    assert "dera_parse_failures > 0" in result.failed_conditions
    assert result.manifest_path is not None and result.manifest_path.exists()
    # Every comparison category is otherwise clean; the parse failure alone gates.
    assert result.counts["annual_dera_only_unexplained"] == 0
    assert result.counts["annual_identity_mismatch"] == 0


# --- ADR-085 decision A: truncated registrant sets ----------------------------


def test_truncated_aciks_parses_valid_and_marked() -> None:
    parsed = parse_sub_file(
        _sub_text(_sub_line("0002000012-23-000004", "2000012", "X", "10-K",
                            "20230210", "30", "2000013 2000014")),
        source_name="trunc.tsv",
    )
    assert not parsed.parse_failures
    sub = parsed.rows[0]
    assert sub.registrant_set_truncated is True
    assert sub.registrant_set_partial is False
    assert sub.additional_ciks == ["0002000013", "0002000014"]  # never inferred


def test_truncated_set_is_nongating_like_partial(
    fixture_frame, tmp_path: Path
) -> None:
    # The combined 10-K's DERA set declares one co-registrant with a
    # truncation signature (nciks above declared, no PARTIAL): declared
    # pairs match and are marked; the unlisted FRAME co-filer is unresolved,
    # non-gating — not a registrant contradiction.
    bundle = _bundle_with_combined_row(
        tmp_path,
        _sub_line("0002000012-23-000004", "2000012",
                  "SYNTHETIC COMBINED PARENT CORP", "10-K", "20230210",
                  "9", "2000013"),
    )
    result = _validate(fixture_frame, bundle, tmp_path / "out", "truncated-set")
    assert result.counts["dera_parse_failures"] == 0
    # Two truncated submissions: the committed out-of-scope S-4 fixture row
    # plus this mutated in-scope combined 10-K.
    assert result.counts["dera_registrant_set_truncated_submissions"] == 2
    assert result.counts["annual_matched_under_truncated"] == 2
    assert result.counts["annual_unresolved_partial_registrant_set"] == 2
    assert result.counts["annual_frame_filer_not_in_dera_registrants"] == 0
    assert all(result.reconciliation.values())
    assert result.gate_status == "pass"


# --- ADR-085 decision C: committed adjudications -------------------------------


def test_gold_run_records_adjudication_file_hash(gold_run) -> None:
    manifest = read_json(gold_run.manifest_path)
    entry = manifest["samples"]["adjudications_file"][0]
    assert entry["path"] == "configs/dera_validation_adjudications.json"
    assert entry["sha256"] == sha256_file(
        ROOT / "configs" / "dera_validation_adjudications.json"
    )
    assert entry["records"] == 5
    assert entry["applied"] == 0  # committed records match no synthetic case
    assert manifest["samples"]["adjudications_applied"] == []


def test_committed_adjudications_cover_the_measured_residuals() -> None:
    # Pins the expected real-rerun outcome: the three measured DERA-only
    # orphans and the two drift outliers are all covered, so the rerun's
    # annual_dera_only_unexplained and annual_identity_mismatch must be 0.
    payload = read_json(ROOT / "configs" / "dera_validation_adjudications.json")
    records = payload["records"]
    assert len(records) == 5  # the ADR-085/086 bounded-bridge cap
    keys = {(r["direction"], r["cik"], r["accession_number"]) for r in records}
    assert keys == {
        ("dera_only", "0001108524", "0001108524-21-000014"),   # Salesforce
        ("filed_date", "0001108524", "0001108524-22-000008"),  # Salesforce
        ("filed_date", "0001747079", "0001747079-22-000107"),  # Bally's
        ("dera_only", "0000895051", "0001558370-23-006754"),   # CASI
        ("dera_only", "0000839923", "0001104659-22-116238"),   # Vodafone
    }
    reasons = {r["reason"] for r in records}
    assert reasons == {"replaced_submission", "deleted_submission"}
    for r in records:
        if r["reason"] == "replaced_submission":
            assert isinstance(r["replacement_accession"], str)
        else:
            assert r["replacement_accession"] is None


def test_per_reason_replacement_rules_fail_closed(
    fixture_frame, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dynamic_ai_products.universe.frame_dera_validation as fdv

    base = {
        "cik": "2000099",
        "accession_number": "0002000099-22-000001",
        "direction": "dera_only",
        "backdating_evidence": "x",
        "adr_reference": "ADR-086",
        "evidence_note": "x",
    }
    cases = [
        ({**base, "reason": "replaced_submission",
          "replacement_accession": None}, "non-null replacement"),
        ({**base, "reason": "deleted_submission",
          "replacement_accession": "0002000099-22-000002"},
         "replacement_accession null"),
        ({**base, "reason": "withdrawn_submission",
          "replacement_accession": None}, "admitted reasons"),
    ]
    for record, match in cases:
        bad = tmp_path / "adjudications.json"
        bad.write_text(json.dumps({
            "adjudications_contract": "dera_validation_adjudications@0.1.0",
            "description": "test",
            "records": [record],
        }) + "\n", encoding="utf-8")
        monkeypatch.setattr(fdv, "ADJUDICATIONS_RELATIVE_PATH", bad)
        with pytest.raises(DeraInputError, match=match):
            run_dera_validation(
                repo_root=ROOT,
                frame_manifest_path=fixture_frame,
                dera_dir=DERA_FIXTURE_DIR,
                output_dir=tmp_path / f"out-{match[:8]}",
                run_id=f"bad-{abs(hash(match)) % 10_000}",
            )
        bad.unlink()


def test_synthetic_deleted_submission_applies_nongating(
    fixture_frame, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dynamic_ai_products.universe.frame_dera_validation as fdv

    adjudications = {
        "adjudications_contract": "dera_validation_adjudications@0.1.0",
        "description": "test adjudications",
        "records": [{
            "cik": "2000099",
            "accession_number": "0002000099-22-000001",
            "direction": "dera_only",
            "reason": "deleted_submission",
            "replacement_accession": None,
            "backdating_evidence": "synthetic deletion evidence",
            "adr_reference": "ADR-086",
            "evidence_note": "synthetic deleted-submission event",
        }],
    }
    adj_path = tmp_path / "adjudications.json"
    adj_path.write_text(json.dumps(adjudications) + "\n", encoding="utf-8")
    monkeypatch.setattr(fdv, "ADJUDICATIONS_RELATIVE_PATH", adj_path)

    bundle = _mutated_bundle(
        tmp_path,
        extra_rows=(_sub_line("0002000099-22-000001", "2000099",
                              "SYNTHETIC GHOST FILER CORP", "10-K",
                              "20221001", "1", ""),),
    )
    result = run_dera_validation(
        repo_root=ROOT,
        frame_manifest_path=fixture_frame,
        dera_dir=bundle,
        output_dir=tmp_path / "out",
        run_id="deleted-adjudicated",
        clock=FIXED_CLOCK,
    )
    assert result.counts["annual_dera_only_adjudicated"] == 1
    assert result.counts["annual_dera_only_unexplained"] == 0
    assert result.gate_status == "pass"


def test_adjudicated_dera_only_is_nongating_and_recorded(
    fixture_frame, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dynamic_ai_products.universe.frame_dera_validation as fdv

    adjudications = {
        "adjudications_contract": "dera_validation_adjudications@0.1.0",
        "description": "test adjudications",
        "records": [{
            "cik": "2000099",
            "accession_number": "0002000099-22-000001",
            "direction": "dera_only",
            "reason": "replaced_submission",
            "replacement_accession": "0002000099-22-000002",
            "backdating_evidence": "synthetic evidence",
            "adr_reference": "ADR-085",
            "evidence_note": "synthetic replaced-submission event",
        }],
    }
    adj_path = tmp_path / "adjudications.json"
    adj_path.write_text(json.dumps(adjudications) + "\n", encoding="utf-8")
    # An absolute override path: `root / absolute` resolves to the absolute
    # path, so the fixed-path contract is exercised without a fake repo root.
    monkeypatch.setattr(fdv, "ADJUDICATIONS_RELATIVE_PATH", adj_path)

    bundle = _mutated_bundle(
        tmp_path,
        extra_rows=(_sub_line("0002000099-22-000001", "2000099",
                              "SYNTHETIC GHOST FILER CORP", "10-K",
                              "20221001", "1", ""),),
    )
    result = run_dera_validation(
        repo_root=ROOT,
        frame_manifest_path=fixture_frame,
        dera_dir=bundle,
        output_dir=tmp_path / "out",
        run_id="adjudicated",
        clock=FIXED_CLOCK,
    )
    assert result.counts["annual_dera_only_adjudicated"] == 1
    assert result.counts["annual_dera_only_unexplained"] == 0
    assert result.counts["adjudications_applied"] == 1
    assert all(result.reconciliation.values())
    assert result.gate_status == "pass"
    manifest = read_json(result.manifest_path)
    assert manifest["samples"]["adjudications_applied"][0]["cik"] == "2000099"


def test_malformed_adjudication_file_is_refused(
    fixture_frame, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import dynamic_ai_products.universe.frame_dera_validation as fdv

    bad = tmp_path / "adjudications.json"
    bad.write_text(json.dumps({
        "adjudications_contract": "dera_validation_adjudications@0.1.0",
        "records": [{"cik": "2000099", "direction": "dera_only"}],
    }) + "\n", encoding="utf-8")
    monkeypatch.setattr(fdv, "ADJUDICATIONS_RELATIVE_PATH", bad)
    with pytest.raises(DeraInputError, match="exactly the keys"):
        run_dera_validation(
            repo_root=ROOT,
            frame_manifest_path=fixture_frame,
            dera_dir=DERA_FIXTURE_DIR,
            output_dir=tmp_path / "out",
            run_id="bad-adjudications",
        )


# --- gate failures (annual stratum, fail closed) ------------------------------


def test_unexplained_dera_only_annual_fails_the_gate(
    fixture_frame, tmp_path: Path
) -> None:
    bundle = _mutated_bundle(
        tmp_path,
        extra_rows=(_sub_line("0002000099-22-000001", "2000099",
                              "SYNTHETIC GHOST FILER CORP", "10-K",
                              "20221001", "1", ""),),
    )
    result = _validate(fixture_frame, bundle, tmp_path / "out", "dera-only")
    assert result.gate_status == "fail"
    assert "annual_dera_only_unexplained > 0" in result.failed_conditions
    assert result.counts["annual_dera_only_unexplained"] == 1


def test_form_mismatch_fails_the_gate(fixture_frame, tmp_path: Path) -> None:
    bundle = _mutated_bundle(
        tmp_path,
        replace_rows={1: _sub_line("0002000001-22-000010", "2000001",
                                   "SYNTHETIC LEDGERWORKS INC", "10-KT",
                                   "20220915", "1", "")},
    )
    result = _validate(fixture_frame, bundle, tmp_path / "out", "form-mismatch")
    assert result.gate_status == "fail"
    assert "annual_identity_mismatch > 0" in result.failed_conditions


def test_bounded_dera_later_drift_is_report_only(
    fixture_frame, tmp_path: Path
) -> None:
    # ADR-085 decision B: DERA later by <= 3 days with matching CIK,
    # accession, and form is the report-only filed_date_drift category.
    bundle = _mutated_bundle(
        tmp_path,
        replace_rows={1: _sub_line("0002000001-22-000010", "2000001",
                                   "SYNTHETIC LEDGERWORKS INC", "10-K",
                                   "20220916", "1", "")},
    )
    result = _validate(fixture_frame, bundle, tmp_path / "out", "drift-in-bound")
    assert result.counts["annual_filed_date_drift"] == 1
    assert result.counts["annual_identity_mismatch"] == 0
    assert result.counts["filed_date_drift_bound_days"] == 3
    assert all(result.reconciliation.values())
    assert result.gate_status == "pass"


@pytest.mark.parametrize(
    ("filed", "label"),
    [("20220914", "dera-earlier"), ("20220920", "beyond-bound")],
)
def test_unbounded_or_dera_earlier_drift_fails_the_gate(
    fixture_frame, tmp_path: Path, filed: str, label: str
) -> None:
    # DERA-earlier drift and drift beyond the 3-day bound remain gating
    # identity mismatches (ADR-085 decision B).
    bundle = _mutated_bundle(
        tmp_path,
        replace_rows={1: _sub_line("0002000001-22-000010", "2000001",
                                   "SYNTHETIC LEDGERWORKS INC", "10-K",
                                   filed, "1", "")},
    )
    result = _validate(fixture_frame, bundle, tmp_path / "out", f"drift-{label}")
    assert result.counts["annual_filed_date_drift"] == 0
    assert result.gate_status == "fail"
    assert "annual_identity_mismatch > 0" in result.failed_conditions


def test_zero_matches_with_nonempty_populations_fails_the_gate(
    fixture_frame, tmp_path: Path
) -> None:
    # Shift every annual DERA row's cik to unmatched filers: submissions
    # remain, matches drop to zero -> input-sanity failure.
    bundle = tmp_path / "dera"
    shutil.copytree(DERA_FIXTURE_DIR, bundle)
    for name in ("sub_2022q4.tsv", "sub_2023q1.tsv"):
        target = bundle / name
        text = target.read_text(encoding="utf-8")
        for old, new in (("\t2000001\t", "\t2000081\t"),
                         ("\t2000003\t", "\t2000083\t"),
                         ("\t2000015\t", "\t2000085\t"),
                         ("\t2000012\t", "\t2000082\t"),
                         ("2000013 2000014", "2000093 2000094")):
            text = text.replace(old, new)
        target.write_text(text, encoding="utf-8")
    result = _validate(fixture_frame, bundle, tmp_path / "out", "zero-match")
    assert result.gate_status == "fail"
    assert (
        "zero annual matches with both comparable populations nonempty"
        in result.failed_conditions
    )


def test_tampered_frame_artifact_is_refused_before_comparison(
    fixture_frame, tmp_path: Path
) -> None:
    frame_copy = tmp_path / "frame"
    shutil.copytree(fixture_frame.parent, frame_copy)
    target = frame_copy / "historical_annual_filers.jsonl"
    target.write_bytes(target.read_bytes() + b"\n")
    with pytest.raises(DeraInputError, match="hash mismatch"):
        _validate(frame_copy / "filer_frame_manifest.json", DERA_FIXTURE_DIR,
                  tmp_path / "out", "tampered-frame")


# --- CLI ----------------------------------------------------------------------


def _cli(*extra: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(CLI), *extra], capture_output=True, text=True, cwd=ROOT
    )


def test_cli_dera_validate_happy_path(fixture_frame, tmp_path: Path) -> None:
    completed = _cli(
        "--mode", "dera-validate",
        "--frame-manifest", str(fixture_frame),
        "--dera-dir", str(DERA_FIXTURE_DIR),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-dera",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["gate_status"] == "pass"
    assert payload["counts"] == EXPECTED["counts"]
    assert Path(payload["manifest_path"]).exists()


def test_cli_gate_failure_exits_one(fixture_frame, tmp_path: Path) -> None:
    bundle = _mutated_bundle(
        tmp_path,
        extra_rows=(_sub_line("0002000099-22-000001", "2000099",
                              "SYNTHETIC GHOST FILER CORP", "10-K",
                              "20221001", "1", ""),),
    )
    completed = _cli(
        "--mode", "dera-validate",
        "--frame-manifest", str(fixture_frame),
        "--dera-dir", str(bundle),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-dera-fail",
    )
    assert completed.returncode == 1
    payload = json.loads(completed.stdout)
    assert payload["gate_status"] == "fail"
    assert Path(payload["manifest_path"]).exists()  # manifest still written


def test_cli_dera_mode_rejects_other_mode_flags(fixture_frame, tmp_path: Path) -> None:
    completed = _cli(
        "--mode", "dera-validate",
        "--frame-manifest", str(fixture_frame),
        "--dera-dir", str(DERA_FIXTURE_DIR),
        "--config", str(PROJECT_CONFIG),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-dera-cross",
    )
    assert completed.returncode == 2
    assert "--config" in completed.stderr


def test_cli_other_modes_reject_dera_flags(tmp_path: Path) -> None:
    completed = _cli(
        "--mode", "frame",
        "--config", str(PROJECT_CONFIG),
        "--index-dir", str(FRAME_FIXTURE_DIR),
        "--filing-window-start", "2022-08-01",
        "--filing-window-end", "2023-02-28",
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-frame-dera-cross",
        "--dera-dir", str(DERA_FIXTURE_DIR),
    )
    assert completed.returncode == 2
    assert "--dera-dir" in completed.stderr
