"""ADR-127 tests: the gate reports, nominates everything, and scores nothing.

The property under test is mostly an absence. A review that carried an accuracy
figure would be read as evidence, and there is no gold set to produce one from
and far too small a sample to estimate a rate. So the tests check that the
contract has no field a score could live in, that every selected row is
nominated rather than sampled again, and that the named human protocol is on
the artifact.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from dynamic_ai_products import classifier_calibration_review as ccr
from dynamic_ai_products import classifier_calibration_selection as ccs
from dynamic_ai_products import lineage_classifier_calibration as lcal
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_classifier_calibration_selection import (  # noqa: E402
    CLOCK,
    ROOT,
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
    packet_cohort as packet_cohort,  # noqa: F401,PLC0414
    release as release,  # noqa: F401,PLC0414
)
from test_lineage_classifier_calibration import (  # noqa: E402
    _axes_payload,
    _grant,
    _run,
    _script,
    selection as selection,  # noqa: F401,PLC0414
)

REVIEW_SCHEMA = json.loads((ROOT / ccr.REVIEW_SCHEMA).read_text(encoding="utf-8"))

#: No artifact in this pipeline may carry these. A number here would be read as
#: evidence, and none of it could be earned.
FORBIDDEN_FIELDS = ("accuracy", "precision", "recall", "f1", "kappa", "score",
                    "agreement", "pass_fail", "passed", "correct", "error_rate")


@pytest.fixture
def calibrated(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    assert run.result.status == "completed", run.result.receipt
    return run.result


def _build(calibrated, selection, tmp_path, *, review_id="calibration-review-fixture",
           dry_run=False, name="review", sha=None, run_dir=None):
    return ccr.build_calibration_review(
        repo_root=ROOT, calibration_run_dir=run_dir or calibrated.run_dir,
        selection_path=selection.path,
        selection_sha256=sha or selection.sha256,
        output_path=tmp_path / name / ccr.REVIEW_FILENAME,
        review_id=review_id, clock=CLOCK, dry_run=dry_run)


# --- what the gate nominates -------------------------------------------------------


def test_every_selected_row_is_nominated(calibrated, selection, tmp_path):
    from jsonschema import Draft202012Validator, FormatChecker
    review = _build(calibrated, selection, tmp_path)
    Draft202012Validator(REVIEW_SCHEMA,
                         format_checker=FormatChecker()).validate(review)
    assert review["counts"]["nominated_rows"] == len(selection.rows)
    assert review["counts"]["selected_rows"] == len(selection.rows)
    assert len(review["nominated_rows"]) == len(selection.rows)
    assert {(r["cik"], r["accession"]) for r in review["nominated_rows"]} == \
        {(r["cik"], r["accession"]) for r in selection.rows}


def test_each_nomination_carries_what_a_reader_needs(calibrated, selection,
                                                     tmp_path):
    review = _build(calibrated, selection, tmp_path)
    strata = {(r["cik"], r["accession"]): r["stratum"] for r in selection.rows}
    for row in review["nominated_rows"]:
        assert row["stratum"] == strata[(row["cik"], row["accession"])]
        assert row["admission_origin"] in ("model_screen", "human_review")
        assert row["admitted_status"] in ("LIKELY_ELIGIBLE",
                                          "BOUNDARY_OR_UNCERTAIN")
        assert row["packet_sha256"]
        if row["record_kind"] == "classified":
            assert row["tier"] and row["fired_rule_id"]
            assert row["evidence"], "a reader needs the quotes"
            for item in row["evidence"]:
                assert item["passage_ref"].startswith("P")
                assert item["quote"]


def test_the_counts_describe_the_strata_and_the_rules(calibrated, selection,
                                                      tmp_path):
    review = _build(calibrated, selection, tmp_path)
    counts = review["counts"]
    assert sum(counts["by_stratum"].values()) == len(selection.rows)
    assert sum(counts["by_record_kind"].values()) == len(selection.rows)
    assert sum(counts["by_tier"].values()) == counts["by_record_kind"].get(
        "classified", 0)
    assert set(counts["tier_by_stratum"]) <= set(counts["by_stratum"])
    assert sum(counts["fired_rule_ids"].values()) == counts["by_record_kind"].get(
        "classified", 0)


def test_a_contradicted_admission_is_reported_not_flagged_as_an_error(
        cohort, selection, tmp_path):
    """The classifier is told to contest the admission; the gate just says so."""
    row = selection.rows[0]
    packet = cohort.release.packets[(row["cik"], row["accession"])]
    grant = _grant(cohort, selection, tmp_path, name="gov-contradiction")
    run = _run(cohort, selection, grant, tmp_path,
               script=_script(cohort, selection, **{row["cik"]: {
                   "text": _axes_payload(
                       packet, centrality="PERIPHERAL",
                       structure="SOFTWARE_PERIPHERAL", materiality="MINOR",
                       product=False, archetypes=())}}))
    assert run.result.status == "completed"
    review = _build(run.result, selection, tmp_path, name="contradiction")
    nominated = next(r for r in review["nominated_rows"] if r["cik"] == row["cik"])
    assert nominated["contradicts_admission"] is True
    assert nominated["tier"] == "EXCLUDED"
    assert sum(review["counts"]["contradicts_admission_by_origin"].values()) == 1
    joined = " ".join(review["limitations"]).lower()
    assert "not an error" in joined


def test_an_unusable_row_is_nominated_with_its_reason(cohort, selection, tmp_path):
    row = selection.rows[0]
    packet = cohort.release.packets[(row["cik"], row["accession"])]
    grant = _grant(cohort, selection, tmp_path, name="gov-unusable")
    run = _run(cohort, selection, grant, tmp_path,
               script=_script(cohort, selection, **{row["cik"]: {
                   "text": _axes_payload(
                       packet, quote="text that appears in no passage")}}))
    review = _build(run.result, selection, tmp_path, name="unusable")
    nominated = next(r for r in review["nominated_rows"] if r["cik"] == row["cik"])
    assert nominated["record_kind"] == "model_output_unusable"
    assert nominated["failure_reason_code"] == "quote_resolution_failure"
    assert nominated["tier"] is None
    assert review["counts"]["unusable_by_reason"] == {"quote_resolution_failure": 1}
    assert review["counts"]["nominated_rows"] == len(selection.rows)


# --- what the gate refuses to be ---------------------------------------------------


def test_the_contract_has_no_field_a_score_could_live_in():
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "properties":
                    for name in value:
                        assert not any(f in name.lower() for f in FORBIDDEN_FIELDS), \
                            f"the review contract exposes {name!r}"
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)
    walk(REVIEW_SCHEMA)


def test_the_gate_is_pending_and_names_its_human(calibrated, selection, tmp_path):
    review = _build(calibrated, selection, tmp_path)
    assert review["gate_state"] == "pending_human_reading"
    assert review["reviewer_id"] == "hakan_zeki_gulmez"
    assert review["review_protocol_version"] == "classifier_calibration_review_v1"
    assert review["review_kind"] == "qualitative_human_reading"
    assert review["promotable"] is False
    assert review["no_model_call"] is True


def test_the_gate_states_what_it_cannot_support(calibrated, selection, tmp_path):
    review = _build(calibrated, selection, tmp_path)
    joined = " ".join(review["limitations"]).lower()
    assert "no gold set" in joined
    assert "too small to estimate a rate" in joined
    assert "not a subsample" in joined
    assert "bounded-outcome tolerances" in joined
    assert "decides nothing" in joined


def test_the_reporter_carries_no_provider_surface():
    source = (ROOT / "src/dynamic_ai_products/classifier_calibration_review.py"
              ).read_text(encoding="utf-8")
    for forbidden in ("genai", "vertex", "httpx", "requests", "generate_content"):
        assert forbidden not in source, forbidden


# --- binding and refusals ----------------------------------------------------------


def test_the_review_binds_the_run_the_prompt_and_the_rules(calibrated, selection,
                                                           tmp_path):
    review = _build(calibrated, selection, tmp_path)
    manifest = json.loads(calibrated.manifest_path.read_text(encoding="utf-8"))
    assert review["calibration_run_id"] == manifest["run_id"]
    assert review["selection_sha256"] == selection.sha256
    assert review["prompt_template_sha256"] == manifest["prompt_template_sha256"]
    assert review["tier_rules_sha256"] == manifest["tier_rules_sha256"]


def test_a_review_is_written_once(calibrated, selection, tmp_path):
    _build(calibrated, selection, tmp_path, name="once")
    with pytest.raises(ls.ScreenInputError):
        _build(calibrated, selection, tmp_path, name="once")


def test_a_dry_run_writes_nothing(calibrated, selection, tmp_path):
    review = _build(calibrated, selection, tmp_path, dry_run=True, name="dry")
    assert not (tmp_path / "dry").exists()
    assert review["counts"]["nominated_rows"] == len(selection.rows)


def test_a_selection_the_run_did_not_classify_is_refused(calibrated, selection,
                                                         tmp_path):
    with pytest.raises(ls.ScreenInputError, match="was pinned"):
        _build(calibrated, selection, tmp_path, name="wrong", sha="0" * 64)


def test_a_run_without_a_manifest_is_refused(calibrated, selection, tmp_path):
    (calibrated.run_dir / lcal.CALIBRATION_MANIFEST_FILENAME).unlink()
    with pytest.raises(ls.ScreenInputError, match="holds no classifier calibration"):
        _build(calibrated, selection, tmp_path, name="nomanifest")


def test_a_drifted_records_file_is_refused(calibrated, selection, tmp_path):
    records = calibrated.run_dir / lcal.CALIBRATION_RECORDS_FILENAME
    records.write_bytes(records.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError, match="missing or no longer hashes"):
        _build(calibrated, selection, tmp_path, name="drifted")


def test_a_failed_run_is_never_reviewed(calibrated, selection, tmp_path):
    (calibrated.run_dir / ls.FAILURE_RECEIPT_FILENAME).write_bytes(b"{}\n")
    with pytest.raises(ls.ScreenInputError, match="non-authoritative"):
        _build(calibrated, selection, tmp_path, name="failed")


def test_the_selection_filename_is_enforced(calibrated, selection, tmp_path):
    assert ccs.CALIBRATION_SELECTION_FILENAME.endswith(".json")
    foreign = tmp_path / "foreign.json"
    foreign.write_bytes(selection.path.read_bytes())
    with pytest.raises(ls.ScreenInputError, match="different artifact"):
        ccr.build_calibration_review(
            repo_root=ROOT, calibration_run_dir=calibrated.run_dir,
            selection_path=foreign, selection_sha256=selection.sha256,
            output_path=tmp_path / "f" / ccr.REVIEW_FILENAME,
            review_id="f", clock=CLOCK)


# --- dry-run semantics at the CLI boundary -----------------------------------------


def _cli_module():
    """Import the pipeline CLI once, by path, without executing main()."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adr127_review_cli", ROOT / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _invoke(cli, calibrated, selection, out_dir, *, run_id, dry_run):
    argv = ["--mode", "build-classifier-calibration-review",
            "--calibration-run-dir", str(calibrated.run_dir),
            "--calibration-selection", str(selection.path),
            "--calibration-selection-sha256", selection.sha256,
            "--output-dir", str(out_dir), "--run-id", run_id]
    if dry_run:
        argv.append("--dry-run")
    args = cli.build_parser().parse_args(argv)
    assert cli._reject_cross_mode_flags(args) is None
    return cli._main_build_classifier_calibration_review(args)


def test_a_dry_run_reserves_no_review_id(calibrated, selection, tmp_path, capsys):
    """A dry run derives the whole review and leaves the id free.

    The run directory is the write-once reservation, so an invocation that
    writes nothing must not burn an id.
    """
    cli = _cli_module()
    out = tmp_path / "cli-dry"
    assert _invoke(cli, calibrated, selection, out,
                   run_id="dry-review", dry_run=True) == 0
    assert not (out / "dry-review").exists(), "a dry run reserved the run id"
    assert not out.exists(), "a dry run created the output parent"
    reported = json.loads(capsys.readouterr().out)
    assert reported["dry_run"] is True
    assert reported["output_path"] is None
    assert reported["gate_state"] == "pending_human_reading"
    assert reported["reviewer_id"] == "hakan_zeki_gulmez"
    assert reported["review_protocol_version"] == "classifier_calibration_review_v1"
    assert reported["counts"]["nominated_rows"] == len(selection.rows)


def test_a_real_run_creates_exactly_its_write_once_target(calibrated, selection,
                                                          tmp_path, capsys):
    cli = _cli_module()
    out = tmp_path / "cli-real"
    assert _invoke(cli, calibrated, selection, out,
                   run_id="real-review", dry_run=False) == 0
    target = out / "real-review"
    assert target.is_dir()
    assert [p.name for p in target.iterdir()] == [ccr.REVIEW_FILENAME]
    assert [p.name for p in out.iterdir()] == ["real-review"]
    reported = json.loads(capsys.readouterr().out)
    assert reported["dry_run"] is False
    assert reported["output_path"] == str(target / ccr.REVIEW_FILENAME)
    written = json.loads(
        (target / ccr.REVIEW_FILENAME).read_text(encoding="utf-8"))
    assert written["review_id"] == "real-review"
    assert len(written["nominated_rows"]) == len(selection.rows)


def test_a_second_real_run_with_the_same_id_is_refused(calibrated, selection,
                                                       tmp_path, capsys):
    """Write-once is unchanged: the reservation still refuses a second run."""
    from hashlib import sha256
    cli = _cli_module()
    out = tmp_path / "cli-twice"
    assert _invoke(cli, calibrated, selection, out,
                   run_id="same-id", dry_run=False) == 0
    capsys.readouterr()
    written = out / "same-id" / ccr.REVIEW_FILENAME
    before = sha256(written.read_bytes()).hexdigest()
    assert _invoke(cli, calibrated, selection, out,
                   run_id="same-id", dry_run=False) == 2
    captured = capsys.readouterr()
    assert "written once" in captured.err
    assert sha256(written.read_bytes()).hexdigest() == before, \
        "the review was overwritten"


def test_a_dry_run_leaves_the_id_free_for_the_real_run(calibrated, selection,
                                                       tmp_path, capsys):
    cli = _cli_module()
    out = tmp_path / "cli-then-real"
    assert _invoke(cli, calibrated, selection, out,
                   run_id="shared-id", dry_run=True) == 0
    dry = json.loads(capsys.readouterr().out)
    assert _invoke(cli, calibrated, selection, out,
                   run_id="shared-id", dry_run=False) == 0
    real = json.loads(capsys.readouterr().out)
    assert (out / "shared-id" / ccr.REVIEW_FILENAME).is_file()
    assert real["counts"] == dry["counts"]
    assert real["output_path"] == str(out / "shared-id" / ccr.REVIEW_FILENAME)


def test_a_dry_run_against_a_taken_id_still_reports(calibrated, selection,
                                                    tmp_path, capsys):
    cli = _cli_module()
    out = tmp_path / "cli-after"
    assert _invoke(cli, calibrated, selection, out,
                   run_id="taken", dry_run=False) == 0
    capsys.readouterr()
    assert _invoke(cli, calibrated, selection, out,
                   run_id="taken", dry_run=True) == 0
    captured = capsys.readouterr()
    assert "written once" not in captured.err
    reported = json.loads(captured.out)
    assert reported["dry_run"] is True and reported["output_path"] is None
    assert reported["counts"]["nominated_rows"] == len(selection.rows)
