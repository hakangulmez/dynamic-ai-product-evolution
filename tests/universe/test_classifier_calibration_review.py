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
    with pytest.raises(ls.ScreenInputError, match="holds no universe_classifier_calibration_manifest.json"):
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


# --- ADR-129 correction: the review reads every calibration version ----------------

from dynamic_ai_products import lineage_classifier_v2_1 as lcl  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_classifier_calibration import (  # noqa: E402
    _v2_2_grant,
    _v2_3_grant,
    _v2_4_grant,
    _v2_5_grant,
    _v2_5_span_script,
)

CALIBRATION_ROUTES = [
    ("v2_1", lcal.CALIBRATION_ROUTE, "_grant"),
    ("v2_2", lcal.CALIBRATION_ROUTE_V2_2, "_v2_2_grant"),
    ("v2_3", lcal.CALIBRATION_ROUTE_V2_3, "_v2_3_grant"),
    ("v2_4", lcal.CALIBRATION_ROUTE_V2_4, "_v2_4_grant"),
    ("v2_5", lcal.CALIBRATION_ROUTE_V2_5, "_v2_5_grant"),
]


def _completed(cohort, selection, tmp_path, route, grant_maker, name):
    from test_lineage_classifier_calibration import _grant, _run
    makers = {"_grant": _grant, "_v2_2_grant": _v2_2_grant,
              "_v2_3_grant": _v2_3_grant, "_v2_4_grant": _v2_4_grant,
              "_v2_5_grant": _v2_5_grant}
    grant = makers[grant_maker](cohort, selection, tmp_path, name=f"g-{name}")
    kwargs = {} if route is lcal.CALIBRATION_ROUTE else {"route": route}
    if route is lcal.CALIBRATION_ROUTE_V2_5:
        kwargs["script"] = _v2_5_span_script(cohort, selection)
    run = _run(cohort, selection, grant, tmp_path, run_id=f"calib-{name}", **kwargs)
    assert run.result.status == "completed", run.result.receipt
    return run.result


@pytest.mark.parametrize("version,route,grant_maker", CALIBRATION_ROUTES,
                         ids=[v for v, _, _ in CALIBRATION_ROUTES])
def test_each_version_is_accepted_only_by_its_matching_loader(
        cohort, selection, tmp_path, version, route, grant_maker):
    result = _completed(cohort, selection, tmp_path, route, grant_maker, version)
    assert lcal.require_classifier_calibration_run(result.run_dir, route=route) == \
        result.run_dir / route.manifest_filename
    for other_version, other_route, _ in CALIBRATION_ROUTES:
        if other_route is route:
            continue
        with pytest.raises(ls.ScreenInputError,
                           match=f"holds no {other_route.manifest_filename}"):
            lcal.require_classifier_calibration_run(result.run_dir,
                                                    route=other_route)
    # and the base/continuation loaders refuse it at every version
    with pytest.raises(ls.ScreenInputError):
        lcl.require_classifier_run(result.run_dir)


def test_the_default_loader_route_is_still_v2_1(cohort, selection, tmp_path):
    """Existing callers pass no route and must keep working unchanged."""
    result = _completed(cohort, selection, tmp_path, lcal.CALIBRATION_ROUTE,
                        "_grant", "default")
    assert lcal.require_classifier_calibration_run(result.run_dir) == \
        result.run_dir / lcal.CALIBRATION_ROUTE.manifest_filename


@pytest.mark.parametrize("version,route,grant_maker", CALIBRATION_ROUTES[1:],
                         ids=["v2_2", "v2_3", "v2_4", "v2_5"])
def test_a_later_version_run_produces_a_valid_review(
        cohort, selection, tmp_path, version, route, grant_maker):
    from jsonschema import Draft202012Validator, FormatChecker
    result = _completed(cohort, selection, tmp_path, route, grant_maker,
                        f"rev-{version}")
    review = ccr.build_calibration_review(
        repo_root=ROOT, calibration_run_dir=result.run_dir,
        selection_path=selection.path, selection_sha256=selection.sha256,
        output_path=tmp_path / f"review-{version}" / ccr.REVIEW_FILENAME,
        review_id=f"review-{version}", clock=CLOCK, calibration_route=route)
    Draft202012Validator(REVIEW_SCHEMA,
                         format_checker=FormatChecker()).validate(review)
    assert review["counts"]["nominated_rows"] == len(selection.rows)
    assert len(review["nominated_rows"]) == len(selection.rows)
    assert review["no_model_call"] is True and review["promotable"] is False
    assert review["gate_state"] == "pending_human_reading"
    assert review["reviewer_id"] == "hakan_zeki_gulmez"
    manifest = json.loads(
        (result.run_dir / route.manifest_filename).read_text(encoding="utf-8"))
    from hashlib import sha256
    assert review["calibration_manifest_sha256"] == sha256(
        (result.run_dir / route.manifest_filename).read_bytes()).hexdigest()
    assert review["prompt_template_sha256"] == manifest["prompt_template_sha256"]
    assert review["calibration_run_id"] == manifest["run_id"]
    assert review["tier_rules_sha256"] == manifest["tier_rules_sha256"]


def test_a_review_built_with_the_wrong_route_is_refused(cohort, selection,
                                                        tmp_path):
    result = _completed(cohort, selection, tmp_path,
                        lcal.CALIBRATION_ROUTE_V2_3, "_v2_3_grant", "wrong")
    with pytest.raises(ls.ScreenInputError, match="holds no "):
        ccr.build_calibration_review(
            repo_root=ROOT, calibration_run_dir=result.run_dir,
            selection_path=selection.path, selection_sha256=selection.sha256,
            output_path=tmp_path / "never" / ccr.REVIEW_FILENAME,
            review_id="wrong", clock=CLOCK,
            calibration_route=lcal.CALIBRATION_ROUTE_V2_2)


def test_the_v2_3_review_verifies_the_route_specific_records_digest(
        cohort, selection, tmp_path):
    result = _completed(cohort, selection, tmp_path,
                        lcal.CALIBRATION_ROUTE_V2_3, "_v2_3_grant", "drift")
    records = result.run_dir / lcal.CALIBRATION_ROUTE_V2_3.records_filename
    assert records.is_file()
    records.write_bytes(records.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError, match="missing or no longer hashes"):
        ccr.build_calibration_review(
            repo_root=ROOT, calibration_run_dir=result.run_dir,
            selection_path=selection.path, selection_sha256=selection.sha256,
            output_path=tmp_path / "never2" / ccr.REVIEW_FILENAME,
            review_id="drift", clock=CLOCK,
            calibration_route=lcal.CALIBRATION_ROUTE_V2_3)


# --- the two new review CLI modes --------------------------------------------------

REVIEW_MODES = ["build-classifier-calibration-review",
                "build-classifier-calibration-review-v2-2",
                "build-classifier-calibration-review-v2-3",
                "build-classifier-calibration-review-v2-4",
                "build-classifier-calibration-review-v2-5"]
REVIEW_REQUIRED_FLAGS = ["--calibration-run-dir", "--calibration-selection",
                         "--calibration-selection-sha256", "--output-dir",
                         "--run-id"]


def _review_argv(mode):
    return ["--mode", mode, "--calibration-run-dir", "run",
            "--calibration-selection", "s.json",
            "--calibration-selection-sha256", "0" * 64,
            "--output-dir", "out", "--run-id", "cli-gating-fixture"]


@pytest.mark.parametrize("mode", REVIEW_MODES)
def test_each_review_mode_accepts_its_complete_argv(mode):
    cli = _cli_module()
    args = cli.build_parser().parse_args(_review_argv(mode))
    assert args.mode == mode
    assert cli._reject_cross_mode_flags(args) is None


@pytest.mark.parametrize("mode", REVIEW_MODES)
@pytest.mark.parametrize("flag", REVIEW_REQUIRED_FLAGS)
def test_each_review_mode_requires_every_declared_flag(mode, flag, capsys):
    cli = _cli_module()
    parser = cli.build_parser()
    enforced_by_argparse = {option for action in parser._actions if action.required
                            for option in action.option_strings}
    trimmed = _review_argv(mode)
    index = trimmed.index(flag)
    del trimmed[index:index + 2]
    if flag in enforced_by_argparse:
        with pytest.raises(SystemExit) as excinfo:
            parser.parse_args(trimmed)
        assert excinfo.value.code == 2
    else:
        verdict = cli._reject_cross_mode_flags(parser.parse_args(trimmed))
        assert verdict and "requires" in verdict and flag in verdict


@pytest.mark.parametrize("mode", REVIEW_MODES)
@pytest.mark.parametrize("flag,value", [
    ("--cohort-manifest", "c.json"), ("--packet-manifest", "p.json"),
    ("--governance-root", "gov"), ("--selection-artifact", "sel.json"),
])
def test_each_review_mode_rejects_an_incompatible_flag(mode, flag, value):
    cli = _cli_module()
    verdict = cli._reject_cross_mode_flags(
        cli.build_parser().parse_args(_review_argv(mode) + [flag, value]))
    assert verdict and flag in verdict


def test_the_cli_declares_all_five_review_modes():
    cli = _cli_module()
    choices = next(a.choices for a in cli.build_parser()._actions
                   if a.dest == "mode")
    for mode in REVIEW_MODES:
        assert mode in choices, mode
    assert len(REVIEW_MODES) == 5
    assert "Fifty-eight mutually exclusive modes" in cli.__doc__


# --- ADR-130: the review route at V2.4 --------------------------------------------


def test_a_v2_4_calibration_produces_a_valid_review(cohort, selection, tmp_path):
    from jsonschema import Draft202012Validator, FormatChecker
    result = _completed(cohort, selection, tmp_path, lcal.CALIBRATION_ROUTE_V2_4,
                        "_v2_4_grant", "rev-v2-4")
    review = ccr.build_calibration_review(
        repo_root=ROOT, calibration_run_dir=result.run_dir,
        selection_path=selection.path, selection_sha256=selection.sha256,
        output_path=tmp_path / "review-v2-4" / "review.json",
        review_id="review-v2-4", clock=CLOCK, dry_run=True,
        calibration_route=lcal.CALIBRATION_ROUTE_V2_4)
    schema = json.loads(
        (ROOT / "schemas/universe_classifier_calibration_review.schema.json")
        .read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(review)
    assert review["review_protocol_version"] == "classifier_calibration_review_v1"
    assert review["gate_state"] == "pending_human_reading"
    assert review["counts"]["nominated_rows"] == len(selection.rows)


def test_the_v2_4_review_route_refuses_every_earlier_run(cohort, selection,
                                                         tmp_path):
    for version, route, grant_maker in CALIBRATION_ROUTES[:-2]:
        result = _completed(cohort, selection, tmp_path, route, grant_maker,
                            f"x4-{version}")
        with pytest.raises(ls.ScreenInputError,
                           match="holds no universe_classifier_v2_4_"
                                 "calibration_manifest.json"):
            ccr.build_calibration_review(
                repo_root=ROOT, calibration_run_dir=result.run_dir,
                selection_path=selection.path, selection_sha256=selection.sha256,
                output_path=tmp_path / f"never-{version}" / "review.json",
                review_id=f"never-{version}", clock=CLOCK, dry_run=True,
                calibration_route=lcal.CALIBRATION_ROUTE_V2_4)


@pytest.mark.parametrize("version,route,grant_maker", CALIBRATION_ROUTES[:-2],
                         ids=["v2_1", "v2_2", "v2_3"])
def test_every_earlier_review_route_refuses_a_v2_4_run(
        cohort, selection, tmp_path, version, route, grant_maker):
    result = _completed(cohort, selection, tmp_path, lcal.CALIBRATION_ROUTE_V2_4,
                        "_v2_4_grant", f"back-{version}")
    with pytest.raises(ls.ScreenInputError,
                       match=f"holds no {route.manifest_filename}"):
        ccr.build_calibration_review(
            repo_root=ROOT, calibration_run_dir=result.run_dir,
            selection_path=selection.path, selection_sha256=selection.sha256,
            output_path=tmp_path / f"never-back-{version}" / "review.json",
            review_id=f"never-back-{version}", clock=CLOCK, dry_run=True,
            calibration_route=route)


def test_the_v2_4_review_verifies_the_route_specific_records_digest(
        cohort, selection, tmp_path):
    result = _completed(cohort, selection, tmp_path, lcal.CALIBRATION_ROUTE_V2_4,
                        "_v2_4_grant", "drift-v2-4")
    records = result.run_dir / lcal.CALIBRATION_ROUTE_V2_4.records_filename
    records.write_bytes(records.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError):
        ccr.build_calibration_review(
            repo_root=ROOT, calibration_run_dir=result.run_dir,
            selection_path=selection.path, selection_sha256=selection.sha256,
            output_path=tmp_path / "never-drift" / "review.json",
            review_id="never-drift", clock=CLOCK, dry_run=True,
            calibration_route=lcal.CALIBRATION_ROUTE_V2_4)


def test_the_v2_4_review_cli_mode_reaches_its_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "build-classifier-calibration-review-v2-4":\n'
            "        return _main_build_classifier_calibration_review(\n"
            "            args, calibration_route=CALIBRATION_ROUTE_V2_4)") in source


def test_the_v2_4_review_dry_run_reserves_no_directory(cohort, selection, tmp_path,
                                                       capsys):
    cli = _cli_module()
    result = _completed(cohort, selection, tmp_path, lcal.CALIBRATION_ROUTE_V2_4,
                        "_v2_4_grant", "dry-v2-4")
    out_dir = tmp_path / "reviews-v2-4"
    argv = ["--mode", "build-classifier-calibration-review-v2-4",
            "--calibration-run-dir", str(result.run_dir),
            "--calibration-selection", str(selection.path),
            "--calibration-selection-sha256", selection.sha256,
            "--output-dir", str(out_dir), "--run-id", "dry-review-v2-4",
            "--dry-run"]
    assert cli.main(argv) == 0
    reported = json.loads(capsys.readouterr().out)
    assert reported["dry_run"] is True
    assert reported["output_path"] is None
    assert not (out_dir / "dry-review-v2-4").exists()


# --- ADR-132: the review route at V2.5 ----------------------------------------------


def test_a_v2_5_calibration_produces_a_valid_review(cohort, selection, tmp_path):
    from jsonschema import Draft202012Validator, FormatChecker
    result = _completed(cohort, selection, tmp_path, lcal.CALIBRATION_ROUTE_V2_5,
                        "_v2_5_grant", "rev-v2-5")
    review = ccr.build_calibration_review(
        repo_root=ROOT, calibration_run_dir=result.run_dir,
        selection_path=selection.path, selection_sha256=selection.sha256,
        output_path=tmp_path / "review-v2-5" / "review.json",
        review_id="review-v2-5", clock=CLOCK, dry_run=True,
        calibration_route=lcal.CALIBRATION_ROUTE_V2_5)
    schema = json.loads(
        (ROOT / "schemas/universe_classifier_calibration_review.schema.json")
        .read_text(encoding="utf-8"))
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(review)
    assert review["gate_state"] == "pending_human_reading"
    assert review["counts"]["nominated_rows"] == len(selection.rows)


def test_the_v2_5_review_shows_the_pipeline_derived_text(cohort, selection, tmp_path):
    """The review contract has no span field, so the resolved text goes in ``quote``.

    That is the projection ADR-132 chose rather than widening a released
    contract. What a reader sees is the packet's own text; where it came from is
    recoverable through the manifest digest the review binds.
    """
    from dynamic_ai_products import classifier_span_index as csi
    result = _completed(cohort, selection, tmp_path, lcal.CALIBRATION_ROUTE_V2_5,
                        "_v2_5_grant", "rev-v2-5-text")
    records = [json.loads(x) for x in
               (result.run_dir / lcal.CALIBRATION_ROUTE_V2_5.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    resolved = {(r["cik"], r["accession"]): r for r in records}
    review = ccr.build_calibration_review(
        repo_root=ROOT, calibration_run_dir=result.run_dir,
        selection_path=selection.path, selection_sha256=selection.sha256,
        output_path=tmp_path / "review-v2-5-text" / "review.json",
        review_id="review-v2-5-text", clock=CLOCK, dry_run=True,
        calibration_route=lcal.CALIBRATION_ROUTE_V2_5)
    checked = 0
    for row in review["nominated_rows"]:
        record = resolved[(row["cik"], row["accession"])]
        if record["record_kind"] != "classified":
            continue
        for shown, stored in zip(row["evidence"], record["axes"]["evidence"]):
            assert set(shown) == {"axis", "passage_ref", "quote", "supported_claim"}
            assert shown["quote"] == stored["resolved_quote"]
            packet = cohort.release.packets[(row["cik"], row["accession"])]
            assert csi.verify_stored_span(stored, packet)
            checked += 1
    assert checked


def test_the_review_contract_cannot_carry_a_span_field_and_was_not_widened():
    """Recorded as a limitation, not worked around.

    ``universe_classifier_calibration_review@0.1.0``'s evidence item is
    ``additionalProperties: false`` over four properties. Carrying ``span_ref``
    or a derived ``span_chars`` into the review needs a contract successor, and
    ADR-132 declined to widen a released contract in passing.
    """
    schema = json.loads(
        (ROOT / "schemas/universe_classifier_calibration_review.schema.json")
        .read_text(encoding="utf-8"))
    item = schema["properties"]["nominated_rows"]["items"]["properties"][
        "evidence"]["items"]
    assert item["additionalProperties"] is False
    assert sorted(item["properties"]) == ["axis", "passage_ref", "quote",
                                          "supported_claim"]
    assert "span_ref" not in item["properties"]
    assert schema["properties"]["review_contract"]["const"] == \
        "universe_classifier_calibration_review@0.1.0"


@pytest.mark.parametrize("version,route,grant_maker", CALIBRATION_ROUTES[:-1],
                         ids=["v2_1", "v2_2", "v2_3", "v2_4"])
def test_every_earlier_review_route_refuses_a_v2_5_run(
        cohort, selection, tmp_path, version, route, grant_maker):
    result = _completed(cohort, selection, tmp_path, lcal.CALIBRATION_ROUTE_V2_5,
                        "_v2_5_grant", f"back5-{version}")
    with pytest.raises(ls.ScreenInputError,
                       match=f"holds no {route.manifest_filename}"):
        ccr.build_calibration_review(
            repo_root=ROOT, calibration_run_dir=result.run_dir,
            selection_path=selection.path, selection_sha256=selection.sha256,
            output_path=tmp_path / f"never-back5-{version}" / "review.json",
            review_id=f"never-back5-{version}", clock=CLOCK, dry_run=True,
            calibration_route=route)


def test_the_v2_5_review_cli_mode_reaches_its_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "build-classifier-calibration-review-v2-5":\n'
            "        return _main_build_classifier_calibration_review(\n"
            "            args, calibration_route=CALIBRATION_ROUTE_V2_5)") in source
