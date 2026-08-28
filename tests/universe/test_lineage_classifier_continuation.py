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
                mutate_receipt=None, mutate_entries=None, extra_files=(),
                route=None):
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
    archive_name = (route or lcc.CONTINUATION_ROUTE).archive_filename
    (directory / archive_name).write_bytes(archive)
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
                        name="classifier-continuation-gov", route=None, **kwargs):
    """Build a continuation grant for ``route``, defaulting to V2.1.

    A later route differs only in which prompt and contract identities the
    grant declares; every digest, cap and policy version is the same, which is
    the point of a prompt-discipline successor.
    """
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
    if route is not None and route is not lcc.CONTINUATION_ROUTE:
        from hashlib import sha256
        version = {"v2_2": "0.2.0", "v2_3": "0.3.0",
                   "v2_4": "0.4.0",
                   "v2_5": "0.5.0",
                   "v2_6": "0.6.0",
                   "v2_7": "0.7.0",
                   "v2_8": "0.8.0",
                   "v2_9": "0.9.0"}[route.contracts.version_id]
        payload.update({
            "authorization_contract":
                f"universe_classifier_continuation_authorization@{version}",
            "output_contract": route.contracts.record_contract,
            "taxonomy_version": route.contracts.taxonomy_version,
            "prompt_template_path": route.contracts.prompt_path,
            "prompt_template_sha256": sha256(
                (ROOT / route.contracts.prompt_path).read_bytes()).hexdigest(),
        })
        if route.contracts.evidence_protocol == "selected_span":
            from dynamic_ai_products.classifier_span_index import (
                load_span_index_rules)
            rules = load_span_index_rules(ROOT)
            payload.update({"span_index_version": rules.version,
                            "span_index_sha256": rules.sha256})
    if mutate is not None:
        mutate(payload)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (root / "classifier_continuation_authorization.json").write_bytes(raw)
    return SimpleNamespace(
        root=root, reference="classifier_continuation_authorization.json",
        sha256=_sha(raw), authorization=payload)


def _run(cohort, source, grant, tmp_path, *, script=None, run_id="continuation-run",
         dry_run=False, output_dir=None, source_run_dir=None, route=None):
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
        sleep=lambda s: events.append(("wait", s)),
        **({"route": route} if route is not None else {}))
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
    with pytest.raises(ls.ScreenInputError, match="holds no universe_classifier_manifest.json"):
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


# --- ADR-129: the continuation route at V2.3 --------------------------------------


def test_the_v2_3_continuation_route_is_isolated_and_bound():
    """Filenames, contracts and prompt differ; the contract set does not."""
    from dynamic_ai_products.classifier_contract_set import V2_2, V2_3
    v2, v3 = lcc.CONTINUATION_ROUTE_V2_2, lcc.CONTINUATION_ROUTE_V2_3
    assert v3.manifest_contract == "universe_classifier_continuation_manifest@0.3.0"
    assert v3.records_filename == "universe_classifier_v2_3_continuation_records.jsonl"
    assert v3.archive_filename == "universe_classifier_v2_3_raw_responses.jsonl"
    assert v3.run_kind == v2.run_kind
    assert v3.contracts.record_contract == V2_2.record_contract
    assert v3.contracts.taxonomy_version == V2_2.taxonomy_version
    assert v3.contracts.prompt_path == V2_3.prompt_path != V2_2.prompt_path
    for attr in ("records_filename", "manifest_filename", "manifest_contract",
                 "manifest_schema", "authorization_schema", "archive_filename"):
        assert getattr(v3, attr) != getattr(v2, attr), attr


# --- ADR-129: a real V2.3 continuation, end to end --------------------------------


def _records_for(result, route):
    return [json.loads(x) for x in
            (result.run_dir / route.records_filename)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


@pytest.fixture
def v2_3_source(cohort, tmp_path):
    """A synthetic failed V2.3 run: a contiguous prefix under V2.3 filenames.

    Built from fixture packets, never from the real failed calibration archive,
    whose bytes belong to a different contract version and a different cohort
    row set.
    """
    return _failed_run(cohort, tmp_path, run_id="source-v2-3",
                       route=lcc.CONTINUATION_ROUTE_V2_3)


def test_a_v2_3_continuation_completes_end_to_end(cohort, v2_3_source, tmp_path):
    from hashlib import sha256
    from dynamic_ai_products.classifier_contract_set import V2_3
    route = lcc.CONTINUATION_ROUTE_V2_3
    grant = _continuation_grant(cohort, v2_3_source, tmp_path, route=route,
                                name="gov-v2-3-continuation")
    run = _run(cohort, v2_3_source, grant, tmp_path, run_id="continuation-v2-3",
               route=route)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()

    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert run.result.manifest_path.name == route.manifest_filename
    assert manifest["manifest_contract"] == \
        "universe_classifier_continuation_manifest@0.3.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.2.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_2"
    assert manifest["prompt_template_path"] == V2_3.prompt_path
    assert manifest["prompt_template_sha256"] == sha256(
        (ROOT / V2_3.prompt_path).read_bytes()).hexdigest()
    assert manifest["tier_rules_version"] == "universe_classifier_tier_rules_v2_1"

    # the V2.3 filenames, and only those
    present = {p.name for p in run.result.run_dir.iterdir()}
    assert route.records_filename in present
    assert route.manifest_filename in present
    assert route.archive_filename in present
    assert lcc.CONTINUATION_RECORDS_FILENAME not in present
    assert lcc.CONTINUATION_MANIFEST_FILENAME not in present
    assert lcl.CLASSIFIER_RAW_RESPONSES_FILENAME not in present

    # every recorded output still hashes to its manifest entry
    for filename, recorded in manifest["output_hashes"].items():
        target = run.result.run_dir / filename
        assert target.is_file(), filename
        assert _sha(target.read_bytes()) == recorded, filename

    records = _records_for(run.result, route)
    assert len(records) == len(cohort.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.2.0"
               for r in records)
    reused = records[:PREFIX_ROWS]
    assert all(r["output_provenance"]["origin"] == "reused_source_prefix"
               for r in reused)
    assert all(r["output_provenance"]["source_run_id"] == v2_3_source.run_id
               for r in reused)
    assert all(r["output_provenance"]["origin"] == "model_called"
               for r in records[PREFIX_ROWS:])
    assert run.factory.generate_calls == len(cohort.rows) - PREFIX_ROWS
    assert manifest["continuation"]["reused_prefix_rows"] == PREFIX_ROWS
    archive = (run.result.run_dir / route.archive_filename).read_bytes()
    assert archive.startswith(v2_3_source.archive_bytes)


def test_the_v2_3_continuation_loader_accepts_only_its_own_run(
        cohort, v2_3_source, tmp_path):
    route = lcc.CONTINUATION_ROUTE_V2_3
    grant = _continuation_grant(cohort, v2_3_source, tmp_path, route=route,
                                name="gov-v2-3-loader")
    run = _run(cohort, v2_3_source, grant, tmp_path, run_id="continuation-v2-3-iso",
               route=route)
    assert run.result.status == "completed", run.result.receipt
    assert lcc.require_classifier_continuation_run(
        run.result.run_dir, route=route) == run.result.manifest_path
    for other in (lcc.CONTINUATION_ROUTE, lcc.CONTINUATION_ROUTE_V2_2):
        with pytest.raises(ls.ScreenInputError,
                           match=f"holds no {other.manifest_filename}"):
            lcc.require_classifier_continuation_run(run.result.run_dir,
                                                    route=other)
    # the default (V2.1) loader refuses it too, without being told a route
    with pytest.raises(ls.ScreenInputError, match="holds no "):
        lcc.require_classifier_continuation_run(run.result.run_dir)
    with pytest.raises(ls.ScreenInputError):
        lcl.require_classifier_run(run.result.run_dir)


@pytest.mark.parametrize("grant_route", [None, "v2_2"],
                         ids=["v2_1-grant", "v2_2-grant"])
def test_the_v2_3_route_refuses_an_earlier_grant(cohort, v2_3_source, tmp_path,
                                                 grant_route):
    route = {None: None, "v2_2": lcc.CONTINUATION_ROUTE_V2_2}[grant_route]
    grant = _continuation_grant(cohort, v2_3_source, tmp_path, route=route,
                                name=f"gov-old-{grant_route}")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, v2_3_source, grant, tmp_path, run_id="cross-grant",
             output_dir=tmp_path / "never", route=lcc.CONTINUATION_ROUTE_V2_3)


def test_the_v2_3_route_refuses_a_v2_1_source(cohort, tmp_path):
    """A V2.1 source archive is not where the V2.3 route looks for one."""
    v2_1_source = _failed_run(cohort, tmp_path, run_id="source-v2-1-for-v2-3")
    grant = _continuation_grant(cohort, v2_1_source, tmp_path,
                                route=lcc.CONTINUATION_ROUTE_V2_3,
                                name="gov-v2-1-source")
    with pytest.raises(ls.ScreenInputError, match="holds no response archive"):
        _run(cohort, v2_1_source, grant, tmp_path, run_id="cross-source",
             output_dir=tmp_path / "never", route=lcc.CONTINUATION_ROUTE_V2_3)


def test_the_v2_1_route_refuses_a_v2_3_source(cohort, v2_3_source, tmp_path):
    grant = _continuation_grant(cohort, v2_3_source, tmp_path,
                                name="gov-v2-3-source-for-v2-1")
    with pytest.raises(ls.ScreenInputError, match="holds no response archive"):
        _run(cohort, v2_3_source, grant, tmp_path, run_id="cross-source-2",
             output_dir=tmp_path / "never")


def test_the_v2_1_continuation_still_completes_unchanged(cohort, source, tmp_path):
    """The default route is untouched by the route parameter."""
    grant = _continuation_grant(cohort, source, tmp_path, name="gov-v2-1-still")
    run = _run(cohort, source, grant, tmp_path, run_id="continuation-v2-1-still")
    assert run.result.status == "completed", run.result.receipt
    assert run.result.manifest_path.name == lcc.CONTINUATION_MANIFEST_FILENAME
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == lcc.CONTINUATION_MANIFEST_CONTRACT
    assert lcc.require_classifier_continuation_run(run.result.run_dir) == \
        run.result.manifest_path


# --- ADR-129 correction: every version's continuation, end to end -----------------

CONTINUATION_ROUTES = [
    ("v2_1", lcc.CONTINUATION_ROUTE, "universe_classifier_record@0.1.0"),
    ("v2_2", lcc.CONTINUATION_ROUTE_V2_2, "universe_classifier_record@0.2.0"),
    ("v2_3", lcc.CONTINUATION_ROUTE_V2_3, "universe_classifier_record@0.2.0"),
    ("v2_4", lcc.CONTINUATION_ROUTE_V2_4, "universe_classifier_record@0.3.0"),
    ("v2_5", lcc.CONTINUATION_ROUTE_V2_5, "universe_classifier_record@0.4.0"),
    ("v2_6", lcc.CONTINUATION_ROUTE_V2_6, "universe_classifier_record@0.4.0"),
    ("v2_7", lcc.CONTINUATION_ROUTE_V2_7, "universe_classifier_record@0.4.0"),
    ("v2_8", lcc.CONTINUATION_ROUTE_V2_8, "universe_classifier_record@0.5.0"),
    ("v2_9", lcc.CONTINUATION_ROUTE_V2_9, "universe_classifier_record@0.5.0"),
]


def _completed_continuation(cohort, tmp_path, route, tag):
    """One genuine continuation at ``route``: its own prefix, its own grant.

    ADR-132 made the prefix's own shape route-dependent: a ``selected_span``
    route's archive holds span identifiers, and seeding it with V2.4-shaped
    quotes would refuse every reused row before the run started.
    """
    span = route.contracts.evidence_protocol == "selected_span"
    src = _failed_run(cohort, tmp_path, run_id=f"source-{tag}",
                      route=None if route is lcc.CONTINUATION_ROUTE else route,
                      **({"payloads": _v2_5_payloads(cohort, route=route)} if span else {}))
    grant = _continuation_grant(
        cohort, src, tmp_path, name=f"gov-{tag}",
        route=None if route is lcc.CONTINUATION_ROUTE else route)
    run = _run(cohort, src, grant, tmp_path, run_id=f"continuation-{tag}",
               **({"script": _v2_5_script(cohort, route=route)} if span else {}),
               **({} if route is lcc.CONTINUATION_ROUTE else {"route": route}))
    assert run.result.status == "completed", run.result.receipt
    return src, run


@pytest.mark.parametrize("version,route,record_contract", CONTINUATION_ROUTES,
                         ids=[v for v, _, _ in CONTINUATION_ROUTES])
def test_every_version_continuation_completes_end_to_end(
        cohort, tmp_path, version, route, record_contract):
    src, run = _completed_continuation(cohort, tmp_path, route, version)
    _assert_no_google()
    records = _records_for(run.result, route)
    assert len(records) == len(cohort.rows)
    # the defect this test exists for: a reused row must declare the route's
    # own record contract, not the V2.1 module constant
    assert all(r["record_contract"] == record_contract for r in records), version
    reused = records[:PREFIX_ROWS]
    assert all(r["output_provenance"]["origin"] == "reused_source_prefix"
               for r in reused)
    assert all(r["record_contract"] == record_contract for r in reused)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == route.manifest_contract
    assert manifest["output_contract"] == record_contract
    for filename, recorded in manifest["output_hashes"].items():
        target = run.result.run_dir / filename
        assert target.is_file() and _sha(target.read_bytes()) == recorded, filename


@pytest.mark.parametrize("version,route,_c", CONTINUATION_ROUTES,
                         ids=[v for v, _, _ in CONTINUATION_ROUTES])
def test_each_completed_continuation_is_loadable_only_by_its_route(
        cohort, tmp_path, version, route, _c):
    _src, run = _completed_continuation(cohort, tmp_path, route, f"load-{version}")
    kwargs = {} if route is lcc.CONTINUATION_ROUTE else {"route": route}
    assert lcc.require_classifier_continuation_run(
        run.result.run_dir, **kwargs) == run.result.manifest_path
    for _v, other, _oc in CONTINUATION_ROUTES:
        if other is route:
            continue
        with pytest.raises(ls.ScreenInputError,
                           match=f"holds no {other.manifest_filename}"):
            lcc.require_classifier_continuation_run(run.result.run_dir,
                                                    route=other)
    with pytest.raises(ls.ScreenInputError):
        lcl.require_classifier_run(run.result.run_dir)


def test_the_v2_2_route_refuses_a_v2_3_grant_and_source(cohort, tmp_path):
    src = _failed_run(cohort, tmp_path, run_id="source-v2-3-for-v2-2",
                      route=lcc.CONTINUATION_ROUTE_V2_3)
    grant = _continuation_grant(cohort, src, tmp_path, name="gov-v2-3-for-v2-2",
                                route=lcc.CONTINUATION_ROUTE_V2_3)
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, src, grant, tmp_path, run_id="cross-v2-2",
             output_dir=tmp_path / "never", route=lcc.CONTINUATION_ROUTE_V2_2)


def test_the_pre_fix_prefix_contract_is_refused(cohort, tmp_path):
    """The exact shape ADR-128 shipped: a reused row declaring the V2.1 contract.

    Before the correction, ``revalidate_classifier_prefix`` stamped every
    rebuilt row with the module's V2.1 constant, so a V2.2 or V2.3 continuation
    could never satisfy its own record schema. Rebuilding the prefix with the
    V2.1 route while running V2.3 reproduces that shape and must still fail.
    """
    from dynamic_ai_products.classifier_contract_set import V2_2, V2_3
    assert V2_3.record_contract == V2_2.record_contract
    src = _failed_run(cohort, tmp_path, run_id="source-prefix-shape",
                      route=lcc.CONTINUATION_ROUTE_V2_3)
    grant = _continuation_grant(cohort, src, tmp_path, name="gov-prefix-shape",
                                route=lcc.CONTINUATION_ROUTE_V2_3)
    real = lcc.revalidate_classifier_prefix

    def stamped_with_the_old_constant(*args, **kwargs):
        rows = real(*args, **{**kwargs, "route": lcc.CONTINUATION_ROUTE})
        assert all(r["record_contract"] == "universe_classifier_record@0.1.0"
                   for r in rows)
        return rows

    lcc.revalidate_classifier_prefix = stamped_with_the_old_constant
    try:
        with pytest.raises(ls.ScreenInputError,
                           match=r"violates universe_classifier_record@0\.2\.0"):
            _run(cohort, src, grant, tmp_path, run_id="prefix-shape",
                 output_dir=tmp_path / "never-prefix",
                 route=lcc.CONTINUATION_ROUTE_V2_3)
    finally:
        lcc.revalidate_classifier_prefix = real


# --- ADR-130: the continuation route at V2.4 --------------------------------------


@pytest.fixture
def v2_4_source(cohort, tmp_path):
    """A synthetic failed V2.4 run: a contiguous prefix under V2.4 filenames."""
    return _failed_run(cohort, tmp_path, run_id="source-v2-4",
                       route=lcc.CONTINUATION_ROUTE_V2_4)


def test_the_v2_4_continuation_route_is_isolated_and_bound():
    from dynamic_ai_products.classifier_contract_set import V2_3, V2_4
    v3, v4 = lcc.CONTINUATION_ROUTE_V2_3, lcc.CONTINUATION_ROUTE_V2_4
    assert v4.records_filename == "universe_classifier_v2_4_continuation_records.jsonl"
    assert v4.manifest_filename == "universe_classifier_v2_4_continuation_manifest.json"
    assert v4.archive_filename == "universe_classifier_v2_4_raw_responses.jsonl"
    assert v4.manifest_contract == "universe_classifier_continuation_manifest@0.4.0"
    assert v4.run_kind == v3.run_kind
    assert v4.contracts.prompt_path == V2_4.prompt_path != V2_3.prompt_path
    assert v4.contracts.record_contract == "universe_classifier_record@0.3.0"


def test_a_v2_4_continuation_completes_end_to_end(cohort, v2_4_source, tmp_path):
    from hashlib import sha256
    from dynamic_ai_products.classifier_contract_set import V2_4
    route = lcc.CONTINUATION_ROUTE_V2_4
    grant = _continuation_grant(cohort, v2_4_source, tmp_path, route=route,
                                name="gov-v2-4")
    run = _run(cohort, v2_4_source, grant, tmp_path, run_id="continuation-v2-4",
               route=route)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == \
        "universe_classifier_continuation_manifest@0.4.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.3.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_4"
    assert manifest["prompt_template_path"] == V2_4.prompt_path
    assert manifest["prompt_template_sha256"] == sha256(
        (ROOT / V2_4.prompt_path).read_bytes()).hexdigest()

    records = [json.loads(x) for x in
               (run.result.run_dir / route.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(cohort.rows)
    # The reused prefix is what ADR-129's second latent defect broke: every
    # rebuilt row must declare the running route's record contract, not the
    # module's V2.1 constant.
    assert all(r["record_contract"] == "universe_classifier_record@0.3.0"
               for r in records)
    reused = [r for r in records
              if r["output_provenance"].get("source_run_id") == v2_4_source.run_id]
    assert reused, "the continuation reused no prefix row"
    assert all(r["record_contract"] == "universe_classifier_record@0.3.0"
               for r in reused)
    archive = (run.result.run_dir / route.archive_filename).read_bytes()
    assert archive.startswith(v2_4_source.archive_bytes)


def test_the_v2_4_continuation_loader_accepts_only_its_own_run(
        cohort, v2_4_source, tmp_path):
    route = lcc.CONTINUATION_ROUTE_V2_4
    grant = _continuation_grant(cohort, v2_4_source, tmp_path, route=route,
                                name="gov-v2-4-iso")
    run = _run(cohort, v2_4_source, grant, tmp_path, run_id="continuation-v2-4-iso",
               route=route)
    assert lcc.require_classifier_continuation_run(
        run.result.run_dir, route=route) == run.result.manifest_path
    for other in (lcc.CONTINUATION_ROUTE, lcc.CONTINUATION_ROUTE_V2_2,
                  lcc.CONTINUATION_ROUTE_V2_3):
        with pytest.raises(ls.ScreenInputError,
                           match=f"holds no {other.manifest_filename}"):
            lcc.require_classifier_continuation_run(run.result.run_dir, route=other)


@pytest.mark.parametrize("route", [
    lcc.CONTINUATION_ROUTE, lcc.CONTINUATION_ROUTE_V2_2, lcc.CONTINUATION_ROUTE_V2_3,
], ids=["v2_1", "v2_2", "v2_3"])
def test_the_v2_4_route_refuses_every_earlier_grant(cohort, v2_4_source, tmp_path,
                                                    route):
    grant = _continuation_grant(cohort, v2_4_source, tmp_path, route=route,
                                name=f"gov-cross-{route.contracts.version_id}")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, v2_4_source, grant, tmp_path,
             run_id=f"cross-grant-{route.contracts.version_id}",
             output_dir=tmp_path / f"never-{route.contracts.version_id}",
             route=lcc.CONTINUATION_ROUTE_V2_4)


def test_the_v2_4_route_refuses_a_v2_3_source(cohort, tmp_path):
    """The archive filename is the gate, and it has to be, because 0.3.0 is wider.

    A V2.3 prefix would satisfy the V2.4 axes schema on shape alone, so nothing
    downstream could tell the two apart. The source loader is handed this
    route's archive name, so the earlier run's prefix is never found at all.
    """
    src = _failed_run(cohort, tmp_path, run_id="source-v2-3-for-v2-4",
                      route=lcc.CONTINUATION_ROUTE_V2_3)
    grant = _continuation_grant(cohort, src, tmp_path, name="gov-v2-3-src",
                                route=lcc.CONTINUATION_ROUTE_V2_4)
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, src, grant, tmp_path, run_id="cross-source-v2-4",
             output_dir=tmp_path / "never-src", route=lcc.CONTINUATION_ROUTE_V2_4)


def test_the_v2_3_route_refuses_a_v2_4_grant_and_source(cohort, tmp_path):
    src = _failed_run(cohort, tmp_path, run_id="source-v2-4-for-v2-3",
                      route=lcc.CONTINUATION_ROUTE_V2_4)
    grant = _continuation_grant(cohort, src, tmp_path, name="gov-v2-4-for-v2-3",
                                route=lcc.CONTINUATION_ROUTE_V2_4)
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, src, grant, tmp_path, run_id="cross-v2-3-from-v2-4",
             output_dir=tmp_path / "never-back", route=lcc.CONTINUATION_ROUTE_V2_3)


def test_the_v2_4_prefix_rebuild_stamps_the_running_routes_contract(
        cohort, tmp_path):
    """ADR-129's second latent defect, re-armed for the fourth version."""
    src = _failed_run(cohort, tmp_path, run_id="source-prefix-v2-4",
                      route=lcc.CONTINUATION_ROUTE_V2_4)
    grant = _continuation_grant(cohort, src, tmp_path, name="gov-prefix-v2-4",
                                route=lcc.CONTINUATION_ROUTE_V2_4)
    real = lcc.revalidate_classifier_prefix

    def stamped_with_the_old_constant(*args, **kwargs):
        rows = real(*args, **{**kwargs, "route": lcc.CONTINUATION_ROUTE})
        assert all(r["record_contract"] == "universe_classifier_record@0.1.0"
                   for r in rows)
        return rows

    lcc.revalidate_classifier_prefix = stamped_with_the_old_constant
    try:
        with pytest.raises(ls.ScreenInputError,
                           match=r"violates universe_classifier_record@0\.3\.0"):
            _run(cohort, src, grant, tmp_path, run_id="prefix-shape-v2-4",
                 output_dir=tmp_path / "never-prefix-v2-4",
                 route=lcc.CONTINUATION_ROUTE_V2_4)
    finally:
        lcc.revalidate_classifier_prefix = real


def test_the_v2_4_continuation_cli_mode_reaches_its_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "classify-universe-cohort-continuation-v2-4":\n'
            "        return _main_classify_universe_cohort_continuation(\n"
            "            args, route=CONTINUATION_ROUTE_V2_4)") in source


# --- ADR-132: the continuation route at V2.5 ----------------------------------------

from dynamic_ai_products import classifier_span_index as _csi  # noqa: E402


def _payload_builder(route):
    """Pick the response shape this route's contract actually admits.

    A V2.8 evidence item has no ``supported_claim`` and may carry a
    ``span_interpretation``; feeding it a V2.5-shaped payload would refuse every
    row before the continuation began.
    """
    from test_lineage_classifier_v2_1 import _span_axes_payload, _v2_8_axes_payload
    annotated = route is not None and \
        getattr(route.contracts, "annotation_policy", None) == "span_interpretation_v1"
    return _v2_8_axes_payload if annotated else _span_axes_payload


def _v2_5_script(cohort, route=None):
    build = _payload_builder(route)
    rules = _csi.load_span_index_rules(ROOT)
    packets = cohort.release.packets
    return {row["cik"]: {"text": build(
        packets[(row["cik"], row["accession"])], rules)} for row in cohort.rows}


def _v2_5_payloads(cohort, prefix_rows=PREFIX_ROWS, route=None):
    """Archived prefix responses in the span shape: identifiers, never text."""
    build = _payload_builder(route)
    rules = _csi.load_span_index_rules(ROOT)
    packets = cohort.release.packets
    return [build(packets[(r["cik"], r["accession"])], rules)
            for r in cohort.rows[:prefix_rows]]


@pytest.fixture
def v2_5_source(cohort, tmp_path):
    return _failed_run(cohort, tmp_path, run_id="source-v2-5",
                       route=lcc.CONTINUATION_ROUTE_V2_5,
                       payloads=_v2_5_payloads(cohort))


def test_the_v2_5_continuation_route_is_isolated_and_bound():
    from dynamic_ai_products.classifier_contract_set import V2_4, V2_5
    v4, v5 = lcc.CONTINUATION_ROUTE_V2_4, lcc.CONTINUATION_ROUTE_V2_5
    assert v5.records_filename == "universe_classifier_v2_5_continuation_records.jsonl"
    assert v5.archive_filename == "universe_classifier_v2_5_raw_responses.jsonl"
    assert v5.manifest_contract == "universe_classifier_continuation_manifest@0.5.0"
    assert v5.run_kind == v4.run_kind
    assert v5.contracts.prompt_path == V2_5.prompt_path != V2_4.prompt_path
    assert v5.contracts.evidence_protocol == "selected_span"
    assert v4.contracts.evidence_protocol == "model_quote"


def test_a_v2_5_continuation_completes_end_to_end(cohort, v2_5_source, tmp_path):
    route = lcc.CONTINUATION_ROUTE_V2_5
    grant = _continuation_grant(cohort, v2_5_source, tmp_path, route=route,
                                name="gov-v2-5")
    run = _run(cohort, v2_5_source, grant, tmp_path, run_id="continuation-v2-5",
               route=route, script=_v2_5_script(cohort))
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == \
        "universe_classifier_continuation_manifest@0.5.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.4.0"
    assert manifest["span_index_version"] == "universe_classifier_span_index_v1"
    records = [json.loads(x) for x in
               (run.result.run_dir / route.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(cohort.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.4.0"
               for r in records)
    # the reused prefix is rebuilt under the span protocol, not the quote one
    reused = [r for r in records
              if r["output_provenance"].get("source_run_id") == v2_5_source.run_id]
    assert reused
    for record in reused:
        assert record["span_index_version"] == "universe_classifier_span_index_v1"
        if record["record_kind"] == "classified":
            for item in record["axes"]["evidence"]:
                assert "span_ref" in item and "quote" not in item
                assert item["span_sha256"]
    archive = (run.result.run_dir / route.archive_filename).read_bytes()
    assert archive.startswith(v2_5_source.archive_bytes)


def test_the_v2_5_continuation_cannot_read_a_v2_4_archive(cohort, tmp_path):
    """The archive filename refuses it before any parse.

    That ordering is the point: a V2.4 archive holds free-text quotes and no
    span reference, so replaying it under the 0.4.0 contract would refuse every
    row anyway. Refusing on the filename first means an earlier run's evidence
    is never reinterpreted, only declined.
    """
    src = _failed_run(cohort, tmp_path, run_id="source-v2-4-for-v2-5",
                      route=lcc.CONTINUATION_ROUTE_V2_4)
    grant = _continuation_grant(cohort, src, tmp_path, name="gov-v2-4-src",
                                route=lcc.CONTINUATION_ROUTE_V2_5)
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, src, grant, tmp_path, run_id="cross-source-v2-5",
             output_dir=tmp_path / "never-src-v2-5",
             route=lcc.CONTINUATION_ROUTE_V2_5, script=_v2_5_script(cohort))


def test_the_v2_4_route_refuses_a_v2_5_grant_and_source(cohort, tmp_path):
    src = _failed_run(cohort, tmp_path, run_id="source-v2-5-for-v2-4",
                      route=lcc.CONTINUATION_ROUTE_V2_5,
                      payloads=_v2_5_payloads(cohort))
    grant = _continuation_grant(cohort, src, tmp_path, name="gov-v2-5-for-v2-4",
                                route=lcc.CONTINUATION_ROUTE_V2_5)
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, src, grant, tmp_path, run_id="cross-v2-4-from-v2-5",
             output_dir=tmp_path / "never-back-v2-4",
             route=lcc.CONTINUATION_ROUTE_V2_4)


def test_the_v2_5_continuation_loader_accepts_only_its_own_run(cohort, v2_5_source,
                                                               tmp_path):
    route = lcc.CONTINUATION_ROUTE_V2_5
    grant = _continuation_grant(cohort, v2_5_source, tmp_path, route=route,
                                name="gov-v2-5-iso")
    run = _run(cohort, v2_5_source, grant, tmp_path, run_id="continuation-v2-5-iso",
               route=route, script=_v2_5_script(cohort))
    assert lcc.require_classifier_continuation_run(
        run.result.run_dir, route=route) == run.result.manifest_path
    for other in (lcc.CONTINUATION_ROUTE, lcc.CONTINUATION_ROUTE_V2_2,
                  lcc.CONTINUATION_ROUTE_V2_3, lcc.CONTINUATION_ROUTE_V2_4):
        with pytest.raises(ls.ScreenInputError,
                           match=f"holds no {other.manifest_filename}"):
            lcc.require_classifier_continuation_run(run.result.run_dir, route=other)


def test_the_v2_5_continuation_cli_mode_reaches_its_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "classify-universe-cohort-continuation-v2-5":\n'
            "        return _main_classify_universe_cohort_continuation(\n"
            "            args, route=CONTINUATION_ROUTE_V2_5)") in source


# --- ADR-133: the continuation route at V2.6 ----------------------------------------


@pytest.fixture
def v2_6_source(cohort, tmp_path):
    return _failed_run(cohort, tmp_path, run_id="source-v2-6",
                       route=lcc.CONTINUATION_ROUTE_V2_6,
                       payloads=_v2_5_payloads(cohort))


def test_the_v2_6_continuation_route_is_isolated_and_bound():
    from dynamic_ai_products.classifier_contract_set import V2_5, V2_6
    v5, v6 = lcc.CONTINUATION_ROUTE_V2_5, lcc.CONTINUATION_ROUTE_V2_6
    assert v6.records_filename == "universe_classifier_v2_6_continuation_records.jsonl"
    assert v6.archive_filename == "universe_classifier_v2_6_raw_responses.jsonl"
    assert v6.manifest_contract == "universe_classifier_continuation_manifest@0.6.0"
    assert v6.run_kind == v5.run_kind
    # the contract set is V2.5's in everything the model touches
    assert v6.contracts.prompt_path == V2_5.prompt_path == V2_6.prompt_path
    assert v6.contracts.evidence_protocol == "selected_span"
    assert v6.manifest_schema != v5.manifest_schema
    assert v6.authorization_schema != v5.authorization_schema


def test_a_v2_6_continuation_completes_end_to_end(cohort, v2_6_source, tmp_path):
    route = lcc.CONTINUATION_ROUTE_V2_6
    grant = _continuation_grant(cohort, v2_6_source, tmp_path, route=route,
                                name="gov-v2-6")
    run = _run(cohort, v2_6_source, grant, tmp_path, run_id="continuation-v2-6",
               route=route, script=_v2_5_script(cohort))
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == \
        "universe_classifier_continuation_manifest@0.6.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.4.0"
    records = [json.loads(x) for x in
               (run.result.run_dir / route.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(cohort.rows)
    reused = [r for r in records
              if r["output_provenance"].get("source_run_id") == v2_6_source.run_id]
    assert reused
    for record in reused:
        if record["record_kind"] == "classified":
            for item in record["axes"]["evidence"]:
                assert "span_ref" in item and "quote" not in item
    archive = (run.result.run_dir / route.archive_filename).read_bytes()
    assert archive.startswith(v2_6_source.archive_bytes)


def test_a_v2_6_continuation_with_one_retry_reports_null(cohort, v2_6_source,
                                                         tmp_path):
    route = lcc.CONTINUATION_ROUTE_V2_6
    grant = _continuation_grant(cohort, v2_6_source, tmp_path, route=route,
                                name="gov-v2-6-retry")
    flaky = cohort.rows[PREFIX_ROWS]["cik"]
    script = _v2_5_script(cohort)
    script[flaky] = {**script[flaky], "quota_failures": 1}
    run = _run(cohort, v2_6_source, grant, tmp_path,
               run_id="continuation-v2-6-retry", route=route, script=script)
    assert run.result.status == "completed", run.result.receipt
    assert run.result.request_accounting["rows_generate_retried"] == 1
    assert run.result.request_accounting["tokens_out_reported"] is None


def test_the_v2_6_continuation_cannot_read_a_v2_5_archive(cohort, tmp_path):
    src = _failed_run(cohort, tmp_path, run_id="source-v2-5-for-v2-6",
                      route=lcc.CONTINUATION_ROUTE_V2_5,
                      payloads=_v2_5_payloads(cohort))
    grant = _continuation_grant(cohort, src, tmp_path, name="gov-v2-5-src-v2-6",
                                route=lcc.CONTINUATION_ROUTE_V2_6)
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, src, grant, tmp_path, run_id="cross-source-v2-6",
             output_dir=tmp_path / "never-src-v2-6",
             route=lcc.CONTINUATION_ROUTE_V2_6, script=_v2_5_script(cohort))


def test_the_v2_5_route_refuses_a_v2_6_grant_and_source(cohort, tmp_path):
    src = _failed_run(cohort, tmp_path, run_id="source-v2-6-for-v2-5",
                      route=lcc.CONTINUATION_ROUTE_V2_6,
                      payloads=_v2_5_payloads(cohort))
    grant = _continuation_grant(cohort, src, tmp_path, name="gov-v2-6-for-v2-5",
                                route=lcc.CONTINUATION_ROUTE_V2_6)
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, src, grant, tmp_path, run_id="cross-v2-5-from-v2-6",
             output_dir=tmp_path / "never-back-v2-5",
             route=lcc.CONTINUATION_ROUTE_V2_5)


def test_the_v2_6_continuation_cli_mode_reaches_its_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "classify-universe-cohort-continuation-v2-6":\n'
            "        return _main_classify_universe_cohort_continuation(\n"
            "            args, route=CONTINUATION_ROUTE_V2_6)") in source
