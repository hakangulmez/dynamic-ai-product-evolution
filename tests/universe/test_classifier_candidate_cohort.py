"""ADR-125 tests: admission is derived, and origin never gets flattened.

Every count in these tests is computed from the fixtures rather than written
down. A literal total would encode one particular release and would keep passing
while describing a different cohort.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_candidate_cohort as ccc
from dynamic_ai_products import human_review_overlay as hro
from dynamic_ai_products import lineage_screen_continuation_v5 as lc5
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products import lineage_screen_release as lrel
from dynamic_ai_products import lineage_screen_repair as lr
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import (  # noqa: E402
    CLOCK,
    ROOT,
    _entry,
    _ledger,
    _sha,
    _unresolved_packets,
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
    release as release,  # noqa: F401,PLC0414
)

RECORD_SCHEMA = json.loads((ROOT / ccc.RECORD_SCHEMA).read_text(encoding="utf-8"))
COHORT_SCHEMA = json.loads((ROOT / ccc.MANIFEST_SCHEMA).read_text(encoding="utf-8"))

_GOOGLE_BASELINE: set[str] | None = None


def _google_modules() -> set[str]:
    return {n for n in sys.modules if n == "google" or n.startswith("google.")}


@pytest.fixture(autouse=True)
def _google_module_baseline():
    global _GOOGLE_BASELINE
    if _GOOGLE_BASELINE is None:
        _GOOGLE_BASELINE = _google_modules()
    yield


def _assert_no_google() -> None:
    added = _google_modules() - (_GOOGLE_BASELINE or set())
    assert not added, f"the cohort path imported google: {sorted(added)}"


def _overlay(release, tmp_path, decisions, *, overlay_id="overlay-fixture"):
    packets = _unresolved_packets(release)
    entries = [_entry(release, packet, decision)
               for packet, decision in zip(packets, decisions)]
    ledger = _ledger(tmp_path, entries, name=f"{overlay_id}-ledger.json")
    result = hro.build_human_review_overlay(
        repo_root=ROOT, release_manifest_path=release.path,
        release_manifest_sha256=release.sha256, ledger_path=ledger,
        output_dir=tmp_path / "overlays", overlay_id=overlay_id, clock=CLOCK)
    return SimpleNamespace(dir=result.overlay_dir, path=result.manifest_path,
                           sha256=_sha(result.manifest_path.read_bytes()),
                           counts=result.counts)


def _build(release, overlay, tmp_path, *, cohort_id="cohort-fixture",
           dry_run=False, release_sha=None, overlay_sha=None):
    return ccc.build_classifier_candidate_cohort(
        repo_root=ROOT, release_manifest_path=release.path,
        release_manifest_sha256=release_sha or release.sha256,
        overlay_manifest_path=overlay.path,
        overlay_manifest_sha256=overlay_sha or overlay.sha256,
        output_dir=tmp_path / "cohorts", cohort_id=cohort_id,
        clock=CLOCK, dry_run=dry_run)


def _records(result):
    return [json.loads(x) for x in (result.cohort_dir / ccc.COHORT_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


def _expected(release, decisions):
    """Derive what the cohort should contain, from the fixtures themselves."""
    admitted = set(ccc.ADMITTED_STATUSES)
    model = [r for r in release.rows
             if r["release_origin"] in ccc.MODEL_ORIGINS
             and r["screen_status"] in admitted]
    human = [d for d in decisions if d in admitted]
    return len(model), len(human)


# --- the happy path ----------------------------------------------------------------


def test_the_cohort_admits_both_origins(release, tmp_path):
    decisions = ["LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN"]
    overlay = _overlay(release, tmp_path, decisions)
    result = _build(release, overlay, tmp_path)
    assert result.status == "completed"

    records = _records(result)
    validator = Draft202012Validator(RECORD_SCHEMA, format_checker=FormatChecker())
    for row in records:
        validator.validate(row)
    model_expected, human_expected = _expected(release, decisions)
    c = result.counts
    assert c["model_screen_admitted"] == model_expected
    assert c["human_review_admitted"] == human_expected
    assert c["cohort_rows"] == len(records) == model_expected + human_expected
    assert sum(c["by_screen_status"].values()) == c["cohort_rows"]

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(COHORT_SCHEMA, format_checker=FormatChecker()).validate(
        manifest)
    assert manifest["admission_rule"]["human_ineligible_admitted"] is False
    assert all(manifest["reconciliation"].values())
    assert len(manifest["reconciliation"]) >= 14
    _assert_no_google()


def test_admission_origin_is_preserved_per_row(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    records = _records(_build(release, overlay, tmp_path))
    for row in records:
        provenance = row["admission_provenance"]
        if row["admission_origin"] == "model_screen":
            assert provenance["model_screen"] and provenance["human_review"] is None
            assert provenance["release_origin"] in ccc.MODEL_ORIGINS
        else:
            human = provenance["human_review"]
            assert human and provenance["model_screen"] is None
            assert provenance["release_origin"] == "unresolved_after_repair"
            assert human["evidence_items"] >= 1
            assert human["reviewer_id"] and human["review_protocol_version"]
            assert human["base_failure_reason_code"]
            assert human["repair_failure_reason_code"]
    origins = {r["admission_origin"] for r in records}
    assert origins == {"model_screen", "human_review"}


def test_human_ineligible_rows_stay_in_the_overlay_only(release, tmp_path):
    decisions = ["LIKELY_ELIGIBLE", "LIKELY_INELIGIBLE"]
    overlay = _overlay(release, tmp_path, decisions)
    result = _build(release, overlay, tmp_path)
    records = _records(result)
    ineligible_packet = _unresolved_packets(release)[1]
    assert ineligible_packet["cik"] not in {r["cik"] for r in records}
    assert result.exclusions["human_likely_ineligible"] == 1
    assert result.counts["human_review_admitted"] == 1
    # the decision itself is still on record in the overlay
    decided = [json.loads(x) for x in
               (overlay.dir / hro.OVERLAY_DECISIONS_FILENAME)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert ineligible_packet["cik"] in {d["cik"] for d in decided}


def test_model_ineligible_and_carried_rows_are_excluded(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    result = _build(release, overlay, tmp_path)
    records = _records(result)
    assert not [r for r in records if r["screen_status"] == "LIKELY_INELIGIBLE"]
    release_counts = release.manifest["counts"]
    assert result.exclusions["model_likely_ineligible"] == \
        release_counts["by_screen_status"]["LIKELY_INELIGIBLE"]
    assert result.exclusions["insufficient_evidence"] == \
        release_counts["insufficient_evidence"]
    assert result.exclusions["model_output_truncated"] == \
        release_counts["model_output_truncated"]
    assert result.counts["cohort_rows"] + result.exclusions["excluded_rows_total"] \
        == release_counts["planned_rows"]


def test_the_build_is_deterministic(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    first = _build(release, overlay, tmp_path, cohort_id="cohort-one")
    second = _build(release, overlay, tmp_path, cohort_id="cohort-two")
    a = (first.cohort_dir / ccc.COHORT_RECORDS_FILENAME).read_bytes()
    b = (second.cohort_dir / ccc.COHORT_RECORDS_FILENAME).read_bytes()
    assert _sha(a) == _sha(b)
    assert first.counts == second.counts


# --- refusals ----------------------------------------------------------------------


def test_a_wrong_release_digest_is_refused(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    with pytest.raises(ls.ScreenInputError, match="was pinned"):
        _build(release, overlay, tmp_path, release_sha="0" * 64)


def test_a_wrong_overlay_digest_is_refused(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    with pytest.raises(ls.ScreenInputError, match="was pinned"):
        _build(release, overlay, tmp_path, overlay_sha="0" * 64)


def test_an_overlay_for_another_release_is_refused(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    manifest = json.loads(overlay.path.read_text(encoding="utf-8"))
    manifest["release"]["release_id"] = "some-other-release"
    overlay.path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    with pytest.raises(ls.ScreenInputError, match="reviews release"):
        _build(release, overlay, tmp_path,
               overlay_sha=_sha(overlay.path.read_bytes()))


def test_an_overlay_pinning_other_release_bytes_is_refused(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    manifest = json.loads(overlay.path.read_text(encoding="utf-8"))
    manifest["release"]["manifest_sha256"] = "1" * 64
    overlay.path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    with pytest.raises(ls.ScreenInputError, match="different release manifest digest"):
        _build(release, overlay, tmp_path,
               overlay_sha=_sha(overlay.path.read_bytes()))


def test_an_incomplete_overlay_is_refused(release, tmp_path):
    """A cohort may not be decided by a partial review."""
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    path = overlay.dir / hro.OVERLAY_DECISIONS_FILENAME
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_bytes((lines[0] + "\n").encode())
    manifest = json.loads(overlay.path.read_text(encoding="utf-8"))
    manifest["output_hashes"][hro.OVERLAY_DECISIONS_FILENAME] = _sha(
        path.read_bytes())
    overlay.path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    with pytest.raises(ls.ScreenInputError, match="coverage must be exact"):
        _build(release, overlay, tmp_path,
               overlay_sha=_sha(overlay.path.read_bytes()))


def test_a_drifted_overlay_decisions_file_is_refused(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    path = overlay.dir / hro.OVERLAY_DECISIONS_FILENAME
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError, match="no longer hashes"):
        _build(release, overlay, tmp_path)


def test_a_drifted_release_records_file_is_refused(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    path = release.dir / lrel.RELEASE_RECORDS_FILENAME
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError, match="no longer hashes"):
        _build(release, overlay, tmp_path)


def test_the_sources_are_never_modified(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    def snapshot(directory):
        return {str(p.relative_to(directory)): _sha(p.read_bytes())
                for p in sorted(directory.rglob("*")) if p.is_file()}
    before = (snapshot(release.dir), snapshot(overlay.dir))
    result = _build(release, overlay, tmp_path)
    assert result.status == "completed"
    assert (snapshot(release.dir), snapshot(overlay.dir)) == before
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["sources"]["sources_unmodified"] is True
    assert manifest["sources"]["no_model_call"] is True


def test_dry_run_and_write_once(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    dry = _build(release, overlay, tmp_path, dry_run=True)
    assert dry.status == "dry_run" and dry.cohort_dir is None
    assert not (tmp_path / "cohorts").exists()
    first = _build(release, overlay, tmp_path)
    assert first.status == "completed"
    with pytest.raises(FileExistsError):
        _build(release, overlay, tmp_path)


# --- loaders -----------------------------------------------------------------------


def test_every_other_loader_refuses_the_cohort(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    result = _build(release, overlay, tmp_path)
    for loader in (ls.require_authoritative_screen_run,
                   ll.require_promotable_screen_run,
                   lc5.require_continuation_v5_run, lr.require_repair_run,
                   lrel.require_screen_release,
                   hro.require_human_review_overlay):
        with pytest.raises(ls.ScreenInputError):
            loader(result.cohort_dir)
    assert ccc.require_classifier_candidate_cohort(result.cohort_dir).name == \
        ccc.COHORT_MANIFEST_FILENAME


def test_the_cohort_loader_refuses_its_own_inputs(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    _build(release, overlay, tmp_path)
    for directory in (release.dir, overlay.dir):
        with pytest.raises(ls.ScreenInputError):
            ccc.require_classifier_candidate_cohort(directory)


def test_the_cohort_loader_refuses_a_drifted_output(release, tmp_path):
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    result = _build(release, overlay, tmp_path)
    path = result.cohort_dir / ccc.COHORT_RECORDS_FILENAME
    path.write_bytes(path.read_bytes() + b"\n")
    with pytest.raises(ls.ScreenInputError, match="no longer hashes"):
        ccc.require_classifier_candidate_cohort(result.cohort_dir)


# --- CLI ---------------------------------------------------------------------------


def _cli_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adr125_cli", ROOT / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _overlay_argv(tmp_path):
    return ["--mode", "build-human-review-overlay",
            "--release-manifest", str(tmp_path / "release.json"),
            "--release-manifest-sha256", "0" * 64,
            "--decision-ledger", str(tmp_path / "ledger.json"),
            "--output-dir", str(tmp_path / "out"), "--run-id", "overlay-cli"]


def _cohort_argv(tmp_path):
    return ["--mode", "build-classifier-candidate-cohort",
            "--release-manifest", str(tmp_path / "release.json"),
            "--release-manifest-sha256", "0" * 64,
            "--overlay-manifest", str(tmp_path / "overlay.json"),
            "--overlay-manifest-sha256", "1" * 64,
            "--output-dir", str(tmp_path / "out"), "--run-id", "cohort-cli"]


@pytest.mark.parametrize("argv_builder", [_overlay_argv, _cohort_argv])
def test_both_modes_accept_their_flags(tmp_path, argv_builder):
    cli = _cli_module()
    args = cli.build_parser().parse_args(argv_builder(tmp_path))
    assert cli._reject_cross_mode_flags(args) is None
    _assert_no_google()


@pytest.mark.parametrize("argv_builder", [_overlay_argv, _cohort_argv])
@pytest.mark.parametrize("flag,value", [
    ("--governance-root", "gov"),
    ("--screen-authorization", "auth.json"),
    ("--screen-authorization-sha256", "0" * 64),
    ("--packet-manifest", "packets.json"),
    ("--provider", "mock"),
])
def test_both_modes_reject_governance_and_provider_flags(tmp_path, argv_builder,
                                                         flag, value):
    """A derivation reaches no provider, so it takes no grant."""
    cli = _cli_module()
    args = cli.build_parser().parse_args(argv_builder(tmp_path) + [flag, value])
    verdict = cli._reject_cross_mode_flags(args)
    assert verdict is not None and flag in verdict


@pytest.mark.parametrize("argv_builder,dropped", [
    (_overlay_argv, "--decision-ledger"),
    (_cohort_argv, "--overlay-manifest"),
])
def test_each_mode_requires_its_own_inputs(tmp_path, argv_builder, dropped):
    cli = _cli_module()
    argv = argv_builder(tmp_path)
    index = argv.index(dropped)
    del argv[index:index + 2]
    args = cli.build_parser().parse_args(argv)
    verdict = cli._reject_cross_mode_flags(args)
    assert verdict is not None and dropped in verdict


def test_the_new_flags_belong_to_no_other_mode(tmp_path):
    cli = _cli_module()
    args = cli.build_parser().parse_args([
        "--mode", "build-screen-release",
        "--base-screen-manifest", "b.json",
        "--base-screen-manifest-sha256", "0" * 64,
        "--repair-manifest", "r.json", "--repair-manifest-sha256", "1" * 64,
        "--output-dir", "out", "--run-id", "x",
        "--decision-ledger", "ledger.json",
    ])
    verdict = cli._reject_cross_mode_flags(args)
    assert verdict is not None and "--decision-ledger" in verdict


def test_the_cohort_cli_dry_run_writes_nothing(release, tmp_path):
    cli = _cli_module()
    overlay = _overlay(release, tmp_path, ["LIKELY_ELIGIBLE", "LIKELY_ELIGIBLE"])
    out = tmp_path / "cli-out"
    assert cli.main([
        "--mode", "build-classifier-candidate-cohort",
        "--release-manifest", str(release.path),
        "--release-manifest-sha256", release.sha256,
        "--overlay-manifest", str(overlay.path),
        "--overlay-manifest-sha256", overlay.sha256,
        "--output-dir", str(out), "--run-id", "cohort-cli-dry", "--dry-run",
    ]) == 0
    assert not out.exists(), "a dry run creates no cohort directory"
    _assert_no_google()


def test_no_population_literal_appears_in_the_implementation():
    """A hard-coded total would describe one release and silently outlive it."""
    for module in (ccc, hro):
        text = (ROOT / "src/dynamic_ai_products"
                / f"{module.__name__.rsplit('.', 1)[-1]}.py").read_text(
                    encoding="utf-8")
        for literal in ("4046", "4,046", " 92", "3954", "3,954", "6830", "6,830"):
            assert literal not in text, f"{literal!r} appears in {module.__name__}"
