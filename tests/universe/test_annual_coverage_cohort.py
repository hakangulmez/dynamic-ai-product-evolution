"""ADR-138 tests: a deterministic filing-year restriction, and what it must not claim.

The rule is small enough to state in one sentence, so most of what is asserted here
is not the arithmetic but the discipline around it: that every source row is kept or
dropped and none vanishes, that a dropped firm keeps its identity and its screen
verdict, that 2021 decides nothing and no year after 2025 does either, that a drifted
input refuses rather than proceeds, and that the artifact never describes itself as a
software universe or as something that ran before the screen.

Everything is fixtures except one test, which reads the committed cohort and FRAME
run to pin the four expected counts and skips when they are absent. No test calls a
model, reaches SEC, or writes outside ``tmp_path``.
"""

from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_annual_coverage_cohort as acc
from dynamic_ai_products import classifier_candidate_cohort as ccc
from dynamic_ai_products.universe.lineage_screen import ScreenInputError

ROOT = Path(__file__).resolve().parents[2]
CLOCK = lambda: __import__("datetime").datetime(  # noqa: E731
    2026, 8, 29, tzinfo=__import__("datetime").timezone.utc)

RECORD_SCHEMA = Draft202012Validator(
    json.loads((ROOT / acc.RECORD_SCHEMA).read_text()), format_checker=FormatChecker())
EXCLUSION_SCHEMA = Draft202012Validator(
    json.loads((ROOT / acc.EXCLUSION_SCHEMA).read_text()),
    format_checker=FormatChecker())
MANIFEST_SCHEMA = Draft202012Validator(
    json.loads((ROOT / acc.COVERAGE_MANIFEST_SCHEMA).read_text()),
    format_checker=FormatChecker())


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


# --- a synthetic cohort and FRAME run ------------------------------------------------


def _candidate_row(index: int, *, origin="model_screen", status="LIKELY_ELIGIBLE"):
    cik = f"{9000000000 + index:010d}"
    return {
        "record_contract": ccc.RECORD_CONTRACT,
        "cik": cik, "accession": f"{cik}-22-000001",
        "company_id": f"CIK{cik}", "form": "10-K",
        "baseline_filing_date": "2022-03-01",
        "source_id": f"sec-primary:{cik}:{cik}-22-000001:doc.htm",
        "packet_sha256": _sha(f"packet-{index}".encode()),
        "admission_origin": origin, "screen_status": status,
        "admission_provenance": {
            "release_id": "synthetic-release", "release_origin": "base_valid",
            "model_screen": {"raw_response_id": f"resp-{cik}",
                             "raw_response_sha256": _sha(f"r{index}".encode())},
            "human_review": None} if origin == "model_screen" else {
            "release_id": "synthetic-release",
            "release_origin": "unresolved_after_repair",
            "model_screen": None,
            "human_review": {"reviewer_id": "reviewer-1", "decision": status}},
    }


def _write_cohort(tmp_path: Path, rows: list[dict], *, name="cohort",
                  mutate_manifest=None):
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)
    records = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                      for r in rows).encode()
    (directory / ccc.COHORT_RECORDS_FILENAME).write_bytes(records)
    manifest = {
        "manifest_contract": ccc.MANIFEST_CONTRACT,
        "cohort_id": "cohort-fixture", "cohort_kind": ccc.COHORT_KIND,
        "counts": {"cohort_rows": len(rows)},
        "output_hashes": {ccc.COHORT_RECORDS_FILENAME: _sha(records)},
    }
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    path = directory / ccc.COHORT_MANIFEST_FILENAME
    path.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return SimpleNamespace(dir=directory, path=path, rows=rows,
                           sha256=_sha(path.read_bytes()))


def _write_frame(tmp_path: Path, years_by_cik: dict[str, list], *, name="frame",
                 fpi_by_cik=None, mutate_manifest=None, drift=None):
    """A FRAME run carrying both annual-filer outputs, hash-bound by its manifest."""
    directory = tmp_path / name
    directory.mkdir(parents=True, exist_ok=True)

    def rows(mapping, form):
        out = []
        for cik, years in sorted(mapping.items()):
            for year in years:
                out.append({"cik": cik, "form": form,
                            "filing_date": f"{year}-03-01",
                            "accession_number": f"{cik}-{str(year)[2:]}-000001"})
        return "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                       for r in out).encode()

    annual = rows(years_by_cik, "10-K")
    fpi = rows(fpi_by_cik or {}, "20-F")
    (directory / "historical_annual_filers.jsonl").write_bytes(annual)
    (directory / "fpi_extension_filers.jsonl").write_bytes(fpi)
    manifest = {
        "run_id": "frame-fixture", "frame_version": "FRAME_v1.1-draft",
        "filing_window_start": "2020-01-01", "filing_window_end": "2026-06-30",
        "output_hashes": {"historical_annual_filers.jsonl": _sha(annual),
                          "fpi_extension_filers.jsonl": _sha(fpi)},
    }
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    path = directory / acc.FRAME_MANIFEST_FILENAME
    path.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    if drift is not None:
        (directory / drift).write_bytes(b'{"cik":"9999999999","form":"10-K",'
                                        b'"filing_date":"2022-03-01"}\n')
    return SimpleNamespace(dir=directory, path=path, sha256=_sha(path.read_bytes()))


def _build(cohort, frame, tmp_path, *, dry_run=False, cohort_sha=None,
           frame_sha=None, cohort_id="coverage-fixture", output_dir=None):
    return acc.build_annual_coverage_cohort(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        cohort_manifest_sha256=cohort_sha or cohort.sha256,
        frame_manifest_path=frame.path,
        frame_manifest_sha256=frame_sha or frame.sha256,
        output_dir=output_dir or (tmp_path / "coverage"),
        coverage_cohort_id=cohort_id, clock=CLOCK, dry_run=dry_run)


ALL = [2021, 2022, 2023, 2024, 2025]


@pytest.fixture
def simple(tmp_path):
    """Six firms spanning every interesting shape the rule can meet."""
    rows = [_candidate_row(i) for i in range(6)]
    ciks = [r["cik"] for r in rows]
    years = {
        ciks[0]: ALL,                       # complete
        ciks[1]: [2022, 2023, 2024, 2025],  # eligible without 2021
        ciks[2]: [2021, 2023, 2024, 2025],  # missing 2022
        ciks[3]: [2021, 2022, 2023, 2024],  # missing 2025
        ciks[4]: [],                        # nothing at all
        ciks[5]: ALL + [2026],              # a later year, which decides nothing
    }
    return SimpleNamespace(
        cohort=_write_cohort(tmp_path, rows), frame=_write_frame(tmp_path, years),
        ciks=ciks, years=years)


# --- the rule itself -----------------------------------------------------------------


def test_the_rule_requires_every_one_of_the_four_years():
    assert acc.REQUIRED_FILING_YEARS == (2022, 2023, 2024, 2025)
    assert acc.OPTIONAL_FILING_YEAR == 2021
    assert acc.LAST_ELIGIBILITY_YEAR == 2025


@pytest.mark.parametrize("missing", [2022, 2023, 2024, 2025])
def test_dropping_any_single_required_year_excludes_the_firm(missing):
    observed = {y for y in ALL if y != missing}
    eligible, gaps, klass = acc.classify_coverage(observed)
    assert eligible is False
    assert gaps == [missing]
    assert klass == "excluded_missing_required_year"


def test_all_four_required_years_present_is_eligible():
    eligible, gaps, klass = acc.classify_coverage({2022, 2023, 2024, 2025})
    assert eligible is True and gaps == []
    assert klass == "2021_missing_2022_2025_present"


def test_2021_is_optional_and_only_changes_the_label():
    with_2021 = acc.classify_coverage(set(ALL))
    without = acc.classify_coverage({2022, 2023, 2024, 2025})
    assert with_2021[0] is without[0] is True
    assert with_2021[1] == without[1] == []
    assert with_2021[2] == "complete_2021_2025"
    assert without[2] == "2021_missing_2022_2025_present"


def test_2021_alone_is_never_enough():
    eligible, gaps, _ = acc.classify_coverage({2021})
    assert eligible is False
    assert gaps == [2022, 2023, 2024, 2025]


@pytest.mark.parametrize("later", [2026, 2027, 2030])
def test_no_year_after_2025_changes_any_verdict(later):
    """The rule's right edge is closed: a later filing neither rescues nor harms."""
    for base in ({2022, 2023, 2024, 2025}, {2021, 2023, 2024, 2025}, set()):
        assert acc.classify_coverage(base) == acc.classify_coverage(base | {later})


def test_a_missing_year_list_is_ascending_and_complete():
    _, gaps, _ = acc.classify_coverage({2023})
    assert gaps == [2022, 2024, 2025]


# --- the built artifact ---------------------------------------------------------------


def test_every_source_row_is_kept_or_dropped_and_none_is_lost(simple, tmp_path):
    built = _build(simple.cohort, simple.frame, tmp_path)
    assert len(built.records) + len(built.exclusions) == len(simple.cohort.rows)
    kept = {(r["cik"], r["accession"]) for r in built.records}
    dropped = {(e["cik"], e["accession"]) for e in built.exclusions}
    assert not (kept & dropped)
    assert kept | dropped == {(r["cik"], r["accession"]) for r in simple.cohort.rows}


def test_the_partition_is_the_one_the_rule_describes(simple, tmp_path):
    built = _build(simple.cohort, simple.frame, tmp_path)
    counts = built.manifest["counts"]
    assert counts["source_cohort_rows"] == 6
    assert counts["included"] == 3          # complete, no-2021, and the 2026 one
    assert counts["excluded"] == 3
    assert counts["complete_2021_2025"] == 2
    assert counts["2021_missing_2022_2025_present"] == 1


def test_every_output_validates_against_its_own_contract(simple, tmp_path):
    built = _build(simple.cohort, simple.frame, tmp_path)
    MANIFEST_SCHEMA.validate(built.manifest)
    for record in built.records:
        RECORD_SCHEMA.validate(record)
    for exclusion in built.exclusions:
        EXCLUSION_SCHEMA.validate(exclusion)


def test_every_exclusion_carries_identity_observed_years_and_missing_years(
        simple, tmp_path):
    built = _build(simple.cohort, simple.frame, tmp_path)
    by_cik = {e["cik"]: e for e in built.exclusions}
    assert set(by_cik) == {simple.ciks[2], simple.ciks[3], simple.ciks[4]}
    for cik, exclusion in by_cik.items():
        assert exclusion["accession"] == f"{cik}-22-000001"
        assert exclusion["company_id"] and exclusion["source_id"]
        assert exclusion["observed_annual_filing_years"] == sorted(simple.years[cik])
        assert exclusion["missing_required_filing_years"]
        assert set(exclusion["missing_required_filing_years"]) <= \
            set(acc.REQUIRED_FILING_YEARS)
    assert by_cik[simple.ciks[2]]["missing_required_filing_years"] == [2022]
    assert by_cik[simple.ciks[3]]["missing_required_filing_years"] == [2025]
    assert by_cik[simple.ciks[4]]["missing_required_filing_years"] == \
        [2022, 2023, 2024, 2025]


def test_no_exclusion_ever_names_2021_as_missing(simple, tmp_path):
    built = _build(simple.cohort, simple.frame, tmp_path)
    for exclusion in built.exclusions:
        assert 2021 not in exclusion["missing_required_filing_years"]


def test_the_screen_verdict_and_review_provenance_are_carried_through(tmp_path):
    """The filter observes filing dates. It has no opinion about admission."""
    rows = [_candidate_row(0, origin="model_screen", status="LIKELY_ELIGIBLE"),
            _candidate_row(1, origin="human_review", status="BOUNDARY_OR_UNCERTAIN"),
            _candidate_row(2, origin="human_review", status="LIKELY_ELIGIBLE")]
    cohort = _write_cohort(tmp_path, rows)
    frame = _write_frame(tmp_path, {rows[0]["cik"]: ALL, rows[1]["cik"]: ALL,
                                    rows[2]["cik"]: [2022]})
    built = _build(cohort, frame, tmp_path)
    stored = {r["cik"]: r for r in built.records + built.exclusions}
    assert len(stored) == 3
    for row in rows:
        out = stored[row["cik"]]
        assert out["admission_origin"] == row["admission_origin"]
        assert out["screen_status"] == row["screen_status"]
        assert out["admission_provenance"] == row["admission_provenance"]


def test_the_included_rows_follow_the_source_cohorts_own_order(tmp_path):
    rows = [_candidate_row(i) for i in range(8)]
    frame = _write_frame(tmp_path, {r["cik"]: ALL for r in rows[::2]})
    built = _build(_write_cohort(tmp_path, rows), frame, tmp_path)
    assert [r["cik"] for r in built.records] == [r["cik"] for r in rows[::2]]


def test_both_annual_forms_count_as_coverage(tmp_path):
    """A firm filing 10-K some years and 20-F others has continuous coverage."""
    row = _candidate_row(0)
    cohort = _write_cohort(tmp_path, [row])
    frame = _write_frame(tmp_path, {row["cik"]: [2022, 2023]},
                         fpi_by_cik={row["cik"]: [2024, 2025]})
    built = _build(cohort, frame, tmp_path)
    assert len(built.records) == 1 and not built.exclusions
    assert built.records[0]["observed_annual_filing_years"] == [2022, 2023, 2024, 2025]


def test_reading_only_the_domestic_file_would_have_dropped_the_fpi_firm(tmp_path):
    """The counterfactual, asserted so the second input is not quietly droppable."""
    row = _candidate_row(0)
    cohort = _write_cohort(tmp_path, [row])
    only_fpi = _write_frame(tmp_path, {}, fpi_by_cik={row["cik"]: ALL}, name="fpi")
    assert len(_build(cohort, only_fpi, tmp_path).records) == 1
    domestic_only = _write_frame(tmp_path, {}, name="domestic")
    assert len(_build(cohort, domestic_only, tmp_path, cohort_id="c2").exclusions) == 1


# --- what the artifact says about itself ---------------------------------------------


def test_the_manifest_refuses_to_be_read_as_a_universe_or_a_classifier_result(
        simple, tmp_path):
    manifest = _build(simple.cohort, simple.frame, tmp_path).manifest
    assert manifest["no_model_call"] is True
    assert manifest["is_software_universe"] is False
    assert manifest["is_classifier_output"] is False
    assert manifest["artifact_role"] == "analysis_eligibility_cohort"


def test_the_manifest_states_that_it_ran_after_the_screen(simple, tmp_path):
    manifest = _build(simple.cohort, simple.frame, tmp_path).manifest
    assert manifest["applied_after_high_recall_screen"] is True
    text = " ".join(manifest["limitations"])
    assert "AFTER the historical high-recall screen" in text
    assert "did not scope the screen" in text
    assert "byte-unchanged" in text


def test_the_manifest_discloses_the_survivor_selection(simple, tmp_path):
    manifest = _build(simple.cohort, simple.frame, tmp_path).manifest
    text = " ".join(manifest["limitations"])
    assert "survivor / continuing-reporter sample" in text
    for word in ("acquired", "taken private", "deregistered", "delisted", "failed"):
        assert word in text, word
    assert "conditional on surviving as a reporting registrant" in text


def test_the_manifest_discloses_the_calendar_filing_year_basis(simple, tmp_path):
    manifest = _build(simple.cohort, simple.frame, tmp_path).manifest
    assert manifest["coverage_rule"]["filing_year_basis"] == \
        "calendar year of the SEC filing date"
    text = " ".join(manifest["limitations"])
    assert "counted by calendar filing year, not fiscal year" in text


def test_the_manifest_never_claims_the_cohort_is_a_software_universe(simple, tmp_path):
    manifest = _build(simple.cohort, simple.frame, tmp_path).manifest
    text = " ".join(manifest["limitations"])
    assert "not a software universe" in text
    assert "not a classifier result" in text
    assert "settles no firm's membership" in text


def test_the_manifest_binds_every_input_by_digest(simple, tmp_path):
    manifest = _build(simple.cohort, simple.frame, tmp_path).manifest
    sources = manifest["sources"]
    assert sources["candidate_cohort"]["manifest_sha256"] == simple.cohort.sha256
    assert sources["frame"]["manifest_sha256"] == simple.frame.sha256
    assert set(sources["frame"]["annual_filer_jsonl_sha256"]) == \
        set(acc.FRAME_ANNUAL_FILENAMES)
    for name, digest in sources["frame"]["annual_filer_jsonl_sha256"].items():
        assert _sha((simple.frame.dir / name).read_bytes()) == digest


def test_every_reconciliation_identity_holds(simple, tmp_path):
    manifest = _build(simple.cohort, simple.frame, tmp_path).manifest
    assert manifest["reconciliation"]
    assert all(manifest["reconciliation"].values()), sorted(
        k for k, v in manifest["reconciliation"].items() if not v)


# --- refusals ------------------------------------------------------------------------


def test_a_wrong_cohort_digest_is_refused(simple, tmp_path):
    with pytest.raises(ScreenInputError, match="was pinned"):
        _build(simple.cohort, simple.frame, tmp_path, cohort_sha="0" * 64)


def test_a_wrong_frame_digest_is_refused(simple, tmp_path):
    with pytest.raises(ScreenInputError, match="was pinned"):
        _build(simple.cohort, simple.frame, tmp_path, frame_sha="0" * 64)


def test_a_drifted_annual_filer_file_is_refused(simple, tmp_path):
    """The manifest still hashes; the file it describes no longer does."""
    (simple.frame.dir / "historical_annual_filers.jsonl").write_bytes(b"")
    with pytest.raises(ScreenInputError, match="no longer hashes"):
        _build(simple.cohort, simple.frame, tmp_path)


def test_a_drifted_cohort_records_file_is_refused(simple, tmp_path):
    (simple.cohort.dir / ccc.COHORT_RECORDS_FILENAME).write_bytes(b"")
    with pytest.raises(ScreenInputError, match="no longer hashes"):
        _build(simple.cohort, simple.frame, tmp_path)


def test_a_frame_manifest_missing_an_annual_output_hash_is_refused(tmp_path):
    row = _candidate_row(0)
    cohort = _write_cohort(tmp_path, [row])
    frame = _write_frame(
        tmp_path, {row["cik"]: ALL},
        mutate_manifest=lambda m: m["output_hashes"].pop("fpi_extension_filers.jsonl"))
    with pytest.raises(ScreenInputError, match="records no output hash"):
        _build(cohort, frame, tmp_path)


def test_a_cohort_whose_count_disagrees_with_its_manifest_is_refused(tmp_path):
    rows = [_candidate_row(i) for i in range(3)]
    cohort = _write_cohort(
        tmp_path, rows, mutate_manifest=lambda m: m["counts"].update(cohort_rows=99))
    frame = _write_frame(tmp_path, {r["cik"]: ALL for r in rows})
    with pytest.raises(ScreenInputError, match="record count disagrees"):
        _build(cohort, frame, tmp_path)


def test_a_foreign_manifest_is_refused_on_its_filename(simple, tmp_path):
    stray = tmp_path / "not_the_cohort.json"
    stray.write_bytes(b"{}\n")
    with pytest.raises(ScreenInputError, match="different artifact"):
        acc.build_annual_coverage_cohort(
            repo_root=ROOT, cohort_manifest_path=stray,
            cohort_manifest_sha256=_sha(stray.read_bytes()),
            frame_manifest_path=simple.frame.path,
            frame_manifest_sha256=simple.frame.sha256,
            output_dir=tmp_path / "out", coverage_cohort_id="x", clock=CLOCK)


def test_a_row_with_an_unusable_filing_date_is_refused(tmp_path):
    row = _candidate_row(0)
    cohort = _write_cohort(tmp_path, [row])
    frame = _write_frame(tmp_path, {row["cik"]: ALL})
    bad = json.dumps({"cik": row["cik"], "form": "10-K", "filing_date": None}) + "\n"
    path = frame.dir / "historical_annual_filers.jsonl"
    path.write_bytes(path.read_bytes() + bad.encode())
    manifest = json.loads(frame.path.read_bytes())
    manifest["output_hashes"]["historical_annual_filers.jsonl"] = \
        _sha(path.read_bytes())
    frame.path.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n")
                           .encode())
    frame.sha256 = _sha(frame.path.read_bytes())
    with pytest.raises(ScreenInputError, match="no usable filing_date"):
        _build(cohort, frame, tmp_path)


# --- write-once, dry run, and source immutability -------------------------------------


def test_a_dry_run_writes_nothing(simple, tmp_path):
    out = tmp_path / "dry"
    built = _build(simple.cohort, simple.frame, tmp_path, dry_run=True, output_dir=out)
    assert built.cohort_dir is None and built.manifest_path is None
    assert built.records and built.exclusions
    assert not out.exists()


def test_a_dry_run_derives_the_same_partition_as_the_write(simple, tmp_path):
    dry = _build(simple.cohort, simple.frame, tmp_path, dry_run=True,
                 output_dir=tmp_path / "dry")
    wet = _build(simple.cohort, simple.frame, tmp_path, output_dir=tmp_path / "wet")
    assert dry.records == wet.records
    assert dry.exclusions == wet.exclusions
    assert dry.manifest["counts"] == wet.manifest["counts"]


def test_the_three_outputs_are_written_once(simple, tmp_path):
    out = tmp_path / "once"
    built = _build(simple.cohort, simple.frame, tmp_path, output_dir=out)
    before = {p.name: p.read_bytes() for p in built.cohort_dir.iterdir()}
    assert set(before) == {acc.COVERAGE_RECORDS_FILENAME,
                           acc.COVERAGE_EXCLUSIONS_FILENAME,
                           acc.COVERAGE_MANIFEST_FILENAME}
    with pytest.raises(ScreenInputError):
        _build(simple.cohort, simple.frame, tmp_path, output_dir=out)
    assert {p.name: p.read_bytes() for p in built.cohort_dir.iterdir()} == before


def test_the_written_outputs_hash_to_their_manifest_entries(simple, tmp_path):
    built = _build(simple.cohort, simple.frame, tmp_path)
    for filename, recorded in built.manifest["output_hashes"].items():
        assert _sha((built.cohort_dir / filename).read_bytes()) == recorded
    assert acc.require_annual_coverage_cohort(built.cohort_dir) == built.manifest_path


def test_the_loader_refuses_a_drifted_output(simple, tmp_path):
    built = _build(simple.cohort, simple.frame, tmp_path)
    (built.cohort_dir / acc.COVERAGE_EXCLUSIONS_FILENAME).write_bytes(b"")
    with pytest.raises(ScreenInputError, match="no longer hashes"):
        acc.require_annual_coverage_cohort(built.cohort_dir)


def test_the_loader_refuses_a_foreign_cohort(tmp_path):
    directory = tmp_path / "foreign"
    directory.mkdir()
    with pytest.raises(ScreenInputError, match="holds no"):
        acc.require_annual_coverage_cohort(directory)


def test_the_source_artifacts_are_byte_unchanged_by_the_build(simple, tmp_path):
    """The screen chain is immutable. This filter reads it and writes elsewhere."""
    before = {p: p.read_bytes()
              for p in list(simple.cohort.dir.iterdir())
              + list(simple.frame.dir.iterdir())}
    built = _build(simple.cohort, simple.frame, tmp_path)
    assert built.cohort_dir is not None
    for path, raw in before.items():
        assert path.read_bytes() == raw, path
    assert built.cohort_dir not in (simple.cohort.dir, simple.frame.dir)


# --- the committed artifacts ----------------------------------------------------------


COMMITTED_COHORT = (
    "data/runs/universe-classifier-candidate-cohorts/"
    "universe-classifier-candidate-cohort-v1-20260824/"
    "universe_classifier_candidate_cohort_manifest.json")
COMMITTED_FRAME = (
    "data/runs/frame-full/frame-live-full-v11-2020q1-2026q2-20260815/"
    "filer_frame_manifest.json")


def test_the_committed_cohort_yields_the_expected_counts(tmp_path):
    """The four numbers this increment was specified against, derived not asserted."""
    cohort_path, frame_path = ROOT / COMMITTED_COHORT, ROOT / COMMITTED_FRAME
    if not cohort_path.is_file() or not frame_path.is_file():
        pytest.skip("the committed cohort or FRAME run is absent from this checkout")
    built = acc.build_annual_coverage_cohort(
        repo_root=ROOT, cohort_manifest_path=cohort_path,
        cohort_manifest_sha256=_sha(cohort_path.read_bytes()),
        frame_manifest_path=frame_path,
        frame_manifest_sha256=_sha(frame_path.read_bytes()),
        output_dir=tmp_path / "must-not-exist",
        coverage_cohort_id="committed-check", clock=CLOCK, dry_run=True)
    counts = built.manifest["counts"]
    assert counts["source_cohort_rows"] == 4045
    assert counts["included"] == 2799
    assert counts["complete_2021_2025"] == 2545
    assert counts["2021_missing_2022_2025_present"] == 254
    assert counts["excluded"] == 1246
    assert counts["included"] + counts["excluded"] == 4045
    assert counts["complete_2021_2025"] + \
        counts["2021_missing_2022_2025_present"] == counts["included"]
    assert not (tmp_path / "must-not-exist").exists()


# --- CLI gating -----------------------------------------------------------------------


def _cli_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "coverage_cli_under_test",
        ROOT / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _cli_module()


def test_the_mode_is_declared(cli):
    action = next(a for a in cli.build_parser()._actions if a.dest == "mode")
    assert "build-annual-coverage-cohort" in action.choices


def test_the_mode_names_every_flag_it_requires(cli):
    args = cli.build_parser().parse_args(
        ["--mode", "build-annual-coverage-cohort", "--output-dir", "/tmp/x",
         "--run-id", "r"])
    message = cli._reject_cross_mode_flags(args)
    for flag in ("--cohort-manifest", "--cohort-manifest-sha256",
                 "--frame-manifest", "--frame-manifest-sha256"):
        assert flag in message, flag


@pytest.mark.parametrize("flag,value", [
    ("--dera-dir", "/x"), ("--bundle-dir", "/x"), ("--config", "/x.yaml"),
    ("--index-dir", "/x"), ("--replay-dir", "/x"), ("--seed", "7"),
    ("--queue-definition", "/x.json"),
])
def test_a_flag_from_another_mode_is_refused(cli, flag, value):
    args = cli.build_parser().parse_args(
        ["--mode", "build-annual-coverage-cohort", "--output-dir", "/tmp/x",
         "--run-id", "r", flag, value])
    message = cli._reject_cross_mode_flags(args)
    assert message and flag in message, message


@pytest.mark.parametrize("mode", [
    "dera-validate", "baseline-carrier", "classify-universe-calibration-v2-9",
    "classify-software-universe-pilot-v1", "select-classifier-pilot-rows",
])
def test_the_frame_digest_flag_belongs_to_this_mode_alone(cli, mode):
    args = cli.build_parser().parse_args(
        ["--mode", mode, "--output-dir", "/tmp/x", "--run-id", "r",
         "--frame-manifest-sha256", "a" * 64])
    message = cli._reject_cross_mode_flags(args)
    assert message and "--frame-manifest-sha256" in message, message
