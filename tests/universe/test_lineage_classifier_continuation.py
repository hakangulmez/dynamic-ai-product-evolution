"""ADR-126 tests: a failed classifier run's evidence is reused, never trusted.

Every reused row is re-rendered, re-validated and re-tiered here exactly as a
fresh response would be, so a prefix row whose output no longer validates
becomes an unusable row rather than a smuggled-in classification. The source
run stays byte-identical throughout and never becomes authoritative.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import lineage_classifier_continuation as lcc
from dynamic_ai_products import lineage_classifier_v2_1 as lcl
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import CLOCK, ROOT, _sha  # noqa: E402
from test_lineage_classifier_v2_1 import (  # noqa: E402
    _EmptyBodyFactory,
    _axes_payload,
    _grant,
    _script,
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
    packet_cohort as packet_cohort,  # noqa: F401,PLC0414
    release as release,  # noqa: F401,PLC0414
)

#: This suite owns its own provider-import baseline. Borrowing another
#: module's global would leave it unset whenever these tests run first, and the
#: check would then flag every provider module some earlier suite imported.
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
    assert not added, f"the continuation path imported google: {sorted(added)}"


MANIFEST_SCHEMA = json.loads(
    (ROOT / lcc.CONTINUATION_MANIFEST_SCHEMA).read_text(encoding="utf-8"))
RECORD_SCHEMA = json.loads((ROOT / lcl.RECORD_SCHEMA).read_text(encoding="utf-8"))

PREFIX_ROWS = 2
SOURCE_AUTHORIZATION_SHA256 = "a" * 64


def _archive_line(run_id, row, payload):
    return json.dumps({
        "raw_response_id": f"{run_id}-{row['cik']}-{row['accession']}",
        "cik": row["cik"], "accession": row["accession"], "raw_response": payload,
        "raw_response_sha256": _sha(payload.encode()),
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _failed_run(cohort, tmp_path, *, prefix_rows=PREFIX_ROWS,
                run_id="source-classifier-run", payloads=None,
                mutate_receipt=None, mutate_entries=None, extra_files=()):
    """One failed classifier run: a receipt and an archive, and nothing else."""
    directory = tmp_path / "failed" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    rows = cohort.rows[:prefix_rows]
    packets = cohort.release.packets
    if payloads is None:
        payloads = [_axes_payload(packets[(r["cik"], r["accession"])])
                    for r in rows]
    entries = [_archive_line(run_id, r, p) for r, p in zip(rows, payloads)]
    if mutate_entries is not None:
        entries = mutate_entries(entries)
    archive = ("\n".join(entries) + "\n").encode() if entries else b""
    (directory / lcl.CLASSIFIER_RAW_RESPONSES_FILENAME).write_bytes(archive)
    stopping = cohort.rows[prefix_rows]
    receipt = {
        "receipt_contract": "universe_screen_failure_receipt@0.1.0",
        "run_id": run_id, "run_kind": lcl.RUN_KIND,
        "reason_code": "provider_error", "detail": "scripted stop",
        "stopping_cik": stopping["cik"], "stopping_accession": stopping["accession"],
        "stopping_row_index": prefix_rows + 1,
        # A provider stop never completed its row, so the stopping ordinal is
        # the first row this continuation must re-send.
        "stopping_row_completed": False,
        "records_completed_before_failure": prefix_rows,
        "reused_prefix_rows": 0,
        "authorization_sha256": SOURCE_AUTHORIZATION_SHA256,
        "cohort_id": "cohort-fixture",
        "run_timestamp": "2026-08-23T12:00:00+00:00",
    }
    if mutate_receipt is not None:
        mutate_receipt(receipt)
    raw = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    (directory / ls.FAILURE_RECEIPT_FILENAME).write_bytes(raw)
    for filename in extra_files:
        (directory / filename).write_bytes(b"{}\n")
    return SimpleNamespace(dir=directory, run_id=run_id, receipt=receipt,
                           receipt_sha256=_sha(raw), archive_bytes=archive,
                           archive_sha256=_sha(archive), rows=rows)


def _continuation_grant(cohort, source, tmp_path, *, mutate=None,
                        name="classifier-continuation-gov", **kwargs):
    base = _grant(cohort, tmp_path, name=name, **kwargs).authorization
    root = tmp_path / name
    called = len(cohort.rows) - len(source.rows)
    payload = dict(base)
    payload.update({
        "authorization_contract":
            "universe_classifier_continuation_authorization@0.1.0",
        "authorization_id": "classifier-continuation-fixture",
        "run_kind": "classifier_v2_1_continuation",
        "source_kind": lcc.SOURCE_KIND,
        "source_run_id": source.run_id,
        "source_run_path": str(source.dir),
        "source_receipt_sha256": source.receipt_sha256,
        "source_raw_responses_sha256": source.archive_sha256,
        "source_authorization_reference": "classifier_authorization.json",
        "source_authorization_sha256": SOURCE_AUTHORIZATION_SHA256,
        "reused_prefix_row_cap": len(source.rows),
        "model_called_row_cap": called,
        "count_attempt_cap": called * 3,
        "provider_attempt_cap": called * 5,
        "budget_max_external_requests": called * 8,
    })
    if mutate is not None:
        mutate(payload)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (root / "classifier_continuation_authorization.json").write_bytes(raw)
    return SimpleNamespace(
        root=root, reference="classifier_continuation_authorization.json",
        sha256=_sha(raw), authorization=payload)


def _run(cohort, source, grant, tmp_path, *, script=None, run_id="continuation-run",
         dry_run=False, output_dir=None, source_run_dir=None):
    events: list = []
    factory = _EmptyBodyFactory(
        script if script is not None else _script(cohort), events)
    result = lcc.run_lineage_classifier_continuation(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        overlay_manifest_path=cohort.overlay_path,
        release_manifest_path=cohort.release.path,
        packet_manifest_path=cohort.packet_manifest_path,
        governance_root=grant.root, authorization_reference=grant.reference,
        authorization_sha256=grant.sha256,
        source_run_dir=source_run_dir or source.dir,
        output_dir=output_dir or (tmp_path / "continuation-out"), run_id=run_id,
        clock=CLOCK, dry_run=dry_run, client_factory=factory,
        sleep=lambda s: events.append(("wait", s)))
    return SimpleNamespace(result=result, factory=factory, events=events)


def _records(result):
    return [json.loads(x) for x in
            (result.run_dir / lcc.CONTINUATION_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


@pytest.fixture
def source(cohort, tmp_path):
    return _failed_run(cohort, tmp_path)


# --- the happy path ----------------------------------------------------------------


def test_the_prefix_is_reused_and_only_the_rest_is_sent(cohort, source, tmp_path):
    grant = _continuation_grant(cohort, source, tmp_path)
    run = _run(cohort, source, grant, tmp_path)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()

    records = _records(run.result)
    validator = Draft202012Validator(RECORD_SCHEMA, format_checker=FormatChecker())
    for record in records:
        validator.validate(record)
    assert len(records) == len(cohort.rows)
    called = len(cohort.rows) - PREFIX_ROWS
    assert run.factory.generate_calls == run.factory.count_calls == called
    reused = records[:PREFIX_ROWS]
    assert all(r["output_provenance"]["origin"] == "reused_source_prefix"
               for r in reused)
    assert all(r["output_provenance"]["source_run_id"] == source.run_id
               for r in reused)
    assert all(r["output_provenance"]["origin"] == "model_called"
               for r in records[PREFIX_ROWS:])
    assert all(r["record_kind"] == "classified" for r in records)


def test_the_manifest_states_what_was_reused(cohort, source, tmp_path):
    grant = _continuation_grant(cohort, source, tmp_path)
    run = _run(cohort, source, grant, tmp_path)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(MANIFEST_SCHEMA,
                         format_checker=FormatChecker()).validate(manifest)
    continuation = manifest["continuation"]
    assert continuation["source_run_id"] == source.run_id
    assert continuation["source_kind"] == "failed_classifier_run"
    assert continuation["reused_prefix_rows"] == PREFIX_ROWS
    assert continuation["model_called_rows"] == len(cohort.rows) - PREFIX_ROWS
    assert continuation["first_model_called_row_ordinal"] == PREFIX_ROWS + 1
    assert continuation["source_archive_is_byte_identical_prefix"] is True
    assert manifest["promotable"] is False
    assert all(v is True for v in manifest["reconciliation"].values())
    assert lcc.require_classifier_continuation_run(run.result.run_dir) == \
        run.result.manifest_path


def test_the_new_archive_opens_with_the_source_archive(cohort, source, tmp_path):
    grant = _continuation_grant(cohort, source, tmp_path)
    run = _run(cohort, source, grant, tmp_path)
    archive = (run.result.run_dir / lcl.CLASSIFIER_RAW_RESPONSES_FILENAME).read_bytes()
    assert archive.startswith(source.archive_bytes)
    assert len(archive) > len(source.archive_bytes)


def test_the_source_run_is_left_byte_identical(cohort, source, tmp_path):
    before = {p.name: p.read_bytes() for p in source.dir.iterdir()}
    grant = _continuation_grant(cohort, source, tmp_path)
    assert _run(cohort, source, grant, tmp_path).result.status == "completed"
    after = {p.name: p.read_bytes() for p in source.dir.iterdir()}
    assert before == after
    assert not (source.dir / lcc.CONTINUATION_MANIFEST_FILENAME).exists()


def test_a_dry_run_reuses_the_prefix_and_sends_nothing(cohort, source, tmp_path):
    grant = _continuation_grant(cohort, source, tmp_path)
    run = _run(cohort, source, grant, tmp_path, dry_run=True)
    assert run.result.status == "dry_run" and run.result.run_dir is None
    assert run.factory.generate_calls == 0
    assert run.result.request_accounting["reused_prefix_rows"] == PREFIX_ROWS


# --- reuse is recomputed, never copied ---------------------------------------------


def test_a_prefix_row_that_no_longer_validates_becomes_unusable(
        cohort, source, tmp_path):
    packets = cohort.release.packets
    row = cohort.rows[0]
    broken = _axes_payload(packets[(row["cik"], row["accession"])],
                           quote="text that appears in no passage")
    reworked = _failed_run(cohort, tmp_path, run_id="source-with-bad-prefix",
                           payloads=[broken] + [
                               _axes_payload(packets[(r["cik"], r["accession"])])
                               for r in cohort.rows[1:PREFIX_ROWS]])
    grant = _continuation_grant(cohort, reworked, tmp_path, unusable=1,
                                name="gov-bad-prefix")
    run = _run(cohort, reworked, grant, tmp_path)
    assert run.result.status == "completed", run.result.receipt
    record = _records(run.result)[0]
    assert record["record_kind"] == "model_output_unusable"
    assert record["failure_reason_code"] == "quote_resolution_failure"
    assert record["tier"] is None
    assert record["output_provenance"]["origin"] == "reused_source_prefix"


def test_a_reused_row_is_re_tiered_from_its_own_axes(cohort, source, tmp_path):
    packets = cohort.release.packets
    row = cohort.rows[0]
    payloads = [_axes_payload(packets[(row["cik"], row["accession"])],
                              centrality="ENABLING", structure="MIXED_SEPARABLE",
                              materiality="MINOR")] + [
        _axes_payload(packets[(r["cik"], r["accession"])])
        for r in cohort.rows[1:PREFIX_ROWS]]
    reworked = _failed_run(cohort, tmp_path, run_id="source-enabling",
                           payloads=payloads)
    grant = _continuation_grant(cohort, reworked, tmp_path, name="gov-enabling")
    run = _run(cohort, reworked, grant, tmp_path)
    record = _records(run.result)[0]
    assert record["tier"] == "TIER_C"
    assert record["tier_rule_trace"]["tier_rules_version"] == \
        "universe_classifier_tier_rules_v2_1"


def test_a_model_supplied_tier_in_the_prefix_is_still_refused(
        cohort, source, tmp_path):
    packets = cohort.release.packets
    row = cohort.rows[0]
    payloads = [_axes_payload(packets[(row["cik"], row["accession"])],
                              extra={"tier": "TIER_A"})] + [
        _axes_payload(packets[(r["cik"], r["accession"])])
        for r in cohort.rows[1:PREFIX_ROWS]]
    reworked = _failed_run(cohort, tmp_path, run_id="source-tiered",
                           payloads=payloads)
    grant = _continuation_grant(cohort, reworked, tmp_path, unusable=1,
                                name="gov-tiered")
    run = _run(cohort, reworked, grant, tmp_path)
    record = _records(run.result)[0]
    assert record["failure_reason_code"] == "model_emitted_tier"
    assert record["tier"] is None


# --- refusals ----------------------------------------------------------------------


def _refused(cohort, source, grant, tmp_path, match, **kwargs):
    output_dir = tmp_path / "never-created"
    with pytest.raises(ls.ScreenInputError, match=match):
        _run(cohort, source, grant, tmp_path, output_dir=output_dir, **kwargs)
    assert not output_dir.exists(), "a refused continuation created a run directory"
    _assert_no_google()


def test_a_source_that_skipped_a_row_is_refused(cohort, tmp_path):
    """A provider-unresolved or truncated row leaves no archive line."""
    gappy = _failed_run(cohort, tmp_path, run_id="source-with-gap",
                        mutate_receipt=lambda r: r.update(
                            records_completed_before_failure=PREFIX_ROWS + 1,
                            stopping_row_index=PREFIX_ROWS + 2))
    grant = _continuation_grant(cohort, gappy, tmp_path, name="gov-gap")
    _refused(cohort, gappy, grant, tmp_path, "no contiguous reusable prefix")


def test_a_completed_run_is_never_continued(cohort, tmp_path):
    finished = _failed_run(cohort, tmp_path, run_id="source-completed",
                           extra_files=(lcl.CLASSIFIER_MANIFEST_FILENAME,))
    grant = _continuation_grant(cohort, finished, tmp_path, name="gov-completed")
    _refused(cohort, finished, grant, tmp_path, "authoritative on its own")


def test_a_receipt_that_does_not_match_its_pinned_digest_is_refused(
        cohort, source, tmp_path):
    grant = _continuation_grant(
        cohort, source, tmp_path, name="gov-digest",
        mutate=lambda p: p.__setitem__("source_receipt_sha256", "0" * 64))
    _refused(cohort, source, grant, tmp_path, "not the named failure")


def test_a_drifted_source_archive_is_refused(cohort, source, tmp_path):
    grant = _continuation_grant(cohort, source, tmp_path, name="gov-archive")
    archive = source.dir / lcl.CLASSIFIER_RAW_RESPONSES_FILENAME
    archive.write_bytes(archive.read_bytes() + b"\n")
    _refused(cohort, source, grant, tmp_path, "source archive hashes to")


def test_a_source_that_ran_under_another_grant_is_refused(cohort, source, tmp_path):
    grant = _continuation_grant(
        cohort, source, tmp_path, name="gov-foreign-grant",
        mutate=lambda p: p.__setitem__("source_authorization_sha256", "b" * 64))
    _refused(cohort, source, grant, tmp_path, "different grant")


def test_a_source_over_another_cohort_is_refused(cohort, tmp_path):
    foreign = _failed_run(cohort, tmp_path, run_id="source-foreign-cohort",
                          mutate_receipt=lambda r: r.update(
                              cohort_id="another-cohort"))
    grant = _continuation_grant(cohort, foreign, tmp_path, name="gov-foreign-cohort")
    _refused(cohort, foreign, grant, tmp_path, "classified cohort")


def test_a_source_directory_the_grant_does_not_name_is_refused(
        cohort, source, tmp_path):
    other = _failed_run(cohort, tmp_path, run_id="source-elsewhere")
    grant = _continuation_grant(cohort, source, tmp_path, name="gov-elsewhere")
    _refused(cohort, source, grant, tmp_path, "grant names source run",
             source_run_dir=other.dir)


def test_a_reordered_prefix_is_refused(cohort, tmp_path):
    reordered = _failed_run(
        cohort, tmp_path, run_id="source-reordered",
        mutate_entries=lambda entries: list(reversed(entries)))
    grant = _continuation_grant(cohort, reordered, tmp_path, name="gov-reordered")
    _refused(cohort, reordered, grant, tmp_path, "nothing skipped, reordered")


def test_a_duplicated_prefix_row_is_refused(cohort, tmp_path):
    duplicated = _failed_run(
        cohort, tmp_path, run_id="source-duplicated",
        mutate_entries=lambda entries: [entries[0], entries[0]])
    grant = _continuation_grant(cohort, duplicated, tmp_path, name="gov-duplicated")
    _refused(cohort, duplicated, grant, tmp_path, "addresses each row exactly once")


def test_an_archived_response_that_no_longer_hashes_is_refused(cohort, tmp_path):
    def _tamper(entries):
        entry = json.loads(entries[0])
        entry["raw_response"] = entry["raw_response"] + " "
        return [json.dumps(entry, sort_keys=True, separators=(",", ":"))] + entries[1:]

    tampered = _failed_run(cohort, tmp_path, run_id="source-tampered",
                           mutate_entries=_tamper)
    grant = _continuation_grant(cohort, tampered, tmp_path, name="gov-tampered")
    _refused(cohort, tampered, grant, tmp_path, "no longer matches its recorded")


def test_a_stopping_row_that_does_not_follow_the_prefix_is_refused(
        cohort, tmp_path):
    misaligned = _failed_run(
        cohort, tmp_path, run_id="source-misaligned",
        mutate_receipt=lambda r: r.update(stopping_cik="9999999999"))
    grant = _continuation_grant(cohort, misaligned, tmp_path, name="gov-misaligned")
    _refused(cohort, misaligned, grant, tmp_path, "of the scope is")


def test_a_grant_whose_reuse_caps_do_not_match_is_refused(cohort, source, tmp_path):
    grant = _continuation_grant(
        cohort, source, tmp_path, name="gov-caps",
        mutate=lambda p: p.__setitem__("reused_prefix_row_cap", 99))
    _refused(cohort, source, grant, tmp_path, "reused row")


def test_a_grant_whose_called_cap_does_not_match_is_refused(cohort, source, tmp_path):
    grant = _continuation_grant(
        cohort, source, tmp_path, name="gov-called",
        mutate=lambda p: p.__setitem__("model_called_row_cap", 99))
    _refused(cohort, source, grant, tmp_path, "model-called row")


def test_a_source_with_an_empty_archive_is_refused(cohort, tmp_path):
    empty = _failed_run(cohort, tmp_path, run_id="source-empty", prefix_rows=0,
                        mutate_receipt=lambda r: r.update(
                            records_completed_before_failure=0,
                            stopping_row_index=1))
    grant = _continuation_grant(
        cohort, empty, tmp_path, name="gov-empty",
        mutate=lambda p: p.__setitem__("reused_prefix_row_cap", 1))
    with pytest.raises(ls.ScreenInputError, match="fresh run, not a"):
        _run(cohort, empty, grant, tmp_path, output_dir=tmp_path / "never")


def test_the_base_route_refuses_a_continuation_manifest(cohort, source, tmp_path):
    grant = _continuation_grant(cohort, source, tmp_path, name="gov-loader")
    run = _run(cohort, source, grant, tmp_path)
    with pytest.raises(ls.ScreenInputError, match="holds no classifier manifest"):
        lcl.require_classifier_run(run.result.run_dir)


def test_a_prefix_whose_failures_exceed_the_tolerance_is_refused(cohort, tmp_path):
    """A run that cannot succeed is refused before it starts."""
    packets = cohort.release.packets
    payloads = [_axes_payload(packets[(r["cik"], r["accession"])],
                              quote="text that appears in no passage")
                for r in cohort.rows[:PREFIX_ROWS]]
    doomed = _failed_run(cohort, tmp_path, run_id="source-all-unusable",
                         payloads=payloads)
    grant = _continuation_grant(cohort, doomed, tmp_path, unusable=1,
                                name="gov-doomed")
    _refused(cohort, doomed, grant, tmp_path, "reused prefix alone revalidates")


# --- ADR-128: the receipt boundary -------------------------------------------------


def _budget_exhausted_source(cohort, tmp_path, *, run_id, prefix_rows=PREFIX_ROWS):
    """A stop whose offending row WAS recorded before the run stopped.

    The unusable-budget path appends the row and then stops, so the stopping
    row is the last prefix row and a continuation resumes after it — unlike a
    provider stop, which never completed its row.
    """
    stopping = cohort.rows[prefix_rows - 1]
    return _failed_run(
        cohort, tmp_path, run_id=run_id, prefix_rows=prefix_rows,
        mutate_receipt=lambda r: r.update(
            reason_code="model_output_unusable_budget_exhausted",
            detail="The authorized unusable-output tolerance was exceeded.",
            stopping_cik=stopping["cik"],
            stopping_accession=stopping["accession"],
            stopping_row_index=prefix_rows,
            stopping_row_completed=True))


def test_a_budget_exhausted_stop_resumes_after_its_stopping_row(cohort, tmp_path):
    """The regression from the first live calibration.

    The receipt named ordinal N+1 while the identity named row N, so the loader
    refused a prefix that was perfectly reusable.
    """
    source = _budget_exhausted_source(cohort, tmp_path, run_id="source-budget")
    assert source.receipt["stopping_row_index"] == PREFIX_ROWS
    assert source.receipt["records_completed_before_failure"] == PREFIX_ROWS
    grant = _continuation_grant(cohort, source, tmp_path, name="gov-budget")
    run = _run(cohort, source, grant, tmp_path, run_id="budget-continuation")
    assert run.result.status == "completed", run.result.receipt
    records = _records(run.result)
    assert len(records) == len(cohort.rows)
    assert run.factory.generate_calls == len(cohort.rows) - PREFIX_ROWS
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["continuation"]["reused_prefix_rows"] == PREFIX_ROWS
    assert manifest["continuation"]["first_model_called_row_ordinal"] == \
        PREFIX_ROWS + 1


def test_a_provider_stop_resumes_at_its_own_stopping_row(cohort, tmp_path):
    source = _failed_run(cohort, tmp_path, run_id="source-provider")
    assert source.receipt["stopping_row_completed"] is False
    assert source.receipt["stopping_row_index"] == PREFIX_ROWS + 1
    stopping = cohort.rows[PREFIX_ROWS]
    assert (source.receipt["stopping_cik"], source.receipt["stopping_accession"]) \
        == (stopping["cik"], stopping["accession"])
    grant = _continuation_grant(cohort, source, tmp_path, name="gov-provider")
    run = _run(cohort, source, grant, tmp_path, run_id="provider-continuation")
    assert run.result.status == "completed", run.result.receipt
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["continuation"]["first_model_called_row_ordinal"] == \
        PREFIX_ROWS + 1


def test_the_pre_fix_receipt_shape_is_refused(cohort, tmp_path):
    """The exact shape the live run wrote: identity row N, ordinal N+1."""
    stopping = cohort.rows[PREFIX_ROWS - 1]
    broken = _failed_run(
        cohort, tmp_path, run_id="source-offbyone",
        mutate_receipt=lambda r: r.update(
            reason_code="model_output_unusable_budget_exhausted",
            stopping_cik=stopping["cik"],
            stopping_accession=stopping["accession"],
            stopping_row_index=PREFIX_ROWS + 1,
            stopping_row_completed=True))
    grant = _continuation_grant(cohort, broken, tmp_path, name="gov-offbyone")
    _refused(cohort, broken, grant, tmp_path, "the stopping ordinal must be")


def test_a_receipt_without_the_completion_flag_is_refused(cohort, tmp_path):
    """The field is required: its absence is a shape this route never reasoned about."""
    legacy = _failed_run(
        cohort, tmp_path, run_id="source-legacy",
        mutate_receipt=lambda r: r.pop("stopping_row_completed"))
    grant = _continuation_grant(cohort, legacy, tmp_path, name="gov-legacy")
    _refused(cohort, legacy, grant, tmp_path, "missing")


def test_a_stopping_ordinal_outside_the_cohort_is_refused(cohort, tmp_path):
    outside = _failed_run(
        cohort, tmp_path, run_id="source-outside",
        mutate_receipt=lambda r: r.update(stopping_row_index=9_999,
                                          records_completed_before_failure=9_998))
    grant = _continuation_grant(cohort, outside, tmp_path, name="gov-outside")
    _refused(cohort, outside, grant, tmp_path, "completed")
