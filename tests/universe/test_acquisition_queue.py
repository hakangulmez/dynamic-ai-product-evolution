"""W3 acquisition-queue tests (ADR-095) — fully offline.

Every run plans from a local synthetic carrier and replays local fixture index
pages and primary documents into a temporary directory. Nothing fetches, no
model is called, and no test reads or writes ``data/runs`` except the two
skipif-guarded rederivations, which read the frozen carrier read-only.

These pin the three things the queue is for: deterministic immutable shard
plans, an executor that runs persisted artefacts under an operator-named
allowlist, and an aggregator that admits completed shards only.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.universe.acquisition_queue import (
    ACQUISITION_MANIFEST_FILENAME,
    _bind_shard_manifest,
    AGGREGATE_MANIFEST_FILENAME,
    BUNDLE_MANIFEST_FILENAME,
    EXECUTION_MANIFEST_FILENAME,
    FAILURE_RECEIPT_FILENAME,
    PLAN_MANIFEST_FILENAME,
    AcquisitionQueueError,
    ShardIntegrityError,
    build_shard_plans,
    canonical_plan_bytes,
    load_queue_definition,
    run_queue_aggregator,
    run_queue_executor,
    run_queue_planner,
    select_carrier_accessions,
    manifest_pair_present,
    shard_plan_filename,
)
from dynamic_ai_products.universe.filing_index_probe import (
    make_filing_index_fixture_replay_transport,
)
from dynamic_ai_products.universe.primary_document_acquisition import (
    PLAN_CONTRACT_V2,
    load_request_plan,
    make_primary_document_fixture_replay_transport,
)
from dynamic_ai_products.universe.io_utils import read_json

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "evals" / "fixtures" / "acquisition_queue"
REPLAY = ROOT / "evals" / "fixtures" / "primary_documents"
DEFINITION = FIXTURES / "queue_definition.json"
TIGHT = FIXTURES / "queue_definition_tight_budget.json"
RESTRICTED = FIXTURES / "queue_definition_restricted.json"
CLI = ROOT / "pipelines" / "00_build_company_universe.py"

PLAN_MANIFEST_SCHEMA = ROOT / "schemas" / "acquisition_queue_plan_manifest.schema.json"
EXECUTION_SCHEMA = (
    ROOT / "schemas" / "acquisition_queue_execution_manifest.schema.json"
)
AGGREGATE_SCHEMA = (
    ROOT / "schemas" / "acquisition_queue_aggregate_manifest.schema.json"
)
DEFINITION_SCHEMA = ROOT / "schemas" / "acquisition_queue_definition.schema.json"

METADATA_CEILING = 8388608
DOCUMENT_CEILING = 268435456

CLOCK = lambda: datetime(2026, 8, 17, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731


def _plan(tmp_path: Path, definition: Path = DEFINITION, run_id: str = "qplan"):
    return run_queue_planner(
        repo_root=ROOT, definition_path=definition,
        output_dir=tmp_path / "plans", run_id=run_id, clock=CLOCK,
    )


def _execute(tmp_path: Path, plan_result, *, indices, requests,
             on_failure="stop", definition: Path = DEFINITION,
             run_id: str = "qexec", output_dir=None):
    return run_queue_executor(
        repo_root=ROOT, definition_path=definition,
        plan_dir=plan_result.run_dir, shard_indices=indices,
        expected_request_count=requests, on_shard_failure=on_failure,
        output_dir=output_dir or (tmp_path / "shards"), run_id=run_id,
        clock=CLOCK,
        metadata_transport=make_filing_index_fixture_replay_transport(
            REPLAY, max_bytes=METADATA_CEILING),
        primary_transport=make_primary_document_fixture_replay_transport(
            REPLAY, max_bytes=DOCUMENT_CEILING),
        metadata_transport_max_bytes=METADATA_CEILING,
        primary_transport_max_bytes=DOCUMENT_CEILING,
    )


# --- deterministic sharding --------------------------------------------------


def test_partition_is_exact_and_total(tmp_path):
    definition = load_queue_definition(DEFINITION)
    groups = select_carrier_accessions(
        definition, ROOT / definition.carrier_relative_path)
    shards = build_shard_plans(definition, groups)
    seen = [a for s in shards for a in s.accessions]
    assert sorted(seen) == sorted(groups), "union must equal the queue"
    assert len(seen) == len(set(seen)), "no accession in two shards"
    assert sum(len(s.accessions) for s in shards) == len(groups)


def test_selection_filters_drop_fpi_and_post_baseline_rows():
    definition = load_queue_definition(DEFINITION)
    groups = select_carrier_accessions(
        definition, ROOT / definition.carrier_relative_path)
    assert set(groups) == {
        "0009200001-22-000001", "0009200002-22-000002", "0009200003-22-000003"
    }
    assert "0009200005-22-000005" not in groups, "FPI row must be filtered out"
    for rows in groups.values():
        assert all(r["baseline_status"] == "baseline_candidate" for r in rows)


def test_replanning_is_byte_identical(tmp_path):
    first = _plan(tmp_path, run_id="a")
    second = _plan(tmp_path, run_id="b")
    for x, y in zip(first.shards, second.shards):
        assert canonical_plan_bytes(x.payload) == canonical_plan_bytes(y.payload)
        assert x.plan_sha256 == y.plan_sha256
    a = (first.run_dir / shard_plan_filename(0)).read_bytes()
    b = (second.run_dir / shard_plan_filename(0)).read_bytes()
    assert a == b


def test_a_changed_carrier_changes_every_shard_plan_hash(tmp_path):
    original = read_json(DEFINITION)
    before = [s.plan_sha256 for s in _plan(tmp_path, run_id="before").shards]
    drifted = dict(original)
    drifted["carrier"] = dict(original["carrier"])
    drifted["carrier"]["carrier_manifest_sha256"] = "b" * 64
    path = tmp_path / "drifted.json"
    path.write_text(json.dumps(drifted, indent=2) + "\n")
    after = [s.plan_sha256 for s in _plan(tmp_path, definition=path,
                                          run_id="after").shards]
    assert before != after
    assert not set(before) & set(after)


def test_complete_carrier_groups_never_straddle_a_shard(tmp_path):
    for shard in _plan(tmp_path).shards:
        for document in shard.payload["documents"]:
            rows = document["carrier_rows"]
            assert len(rows) >= 1
            ciks = [r["cik"] for r in rows]
            assert document["directory_cik"] == min(ciks)
    shared = [
        d for s in _plan(tmp_path, run_id="q2").shards
        for d in s.payload["documents"] if len(d["carrier_rows"]) > 1
    ]
    assert len(shared) == 1
    assert {r["cik"] for r in shared[0]["carrier_rows"]} == {
        "0009200003", "0009200004"
    }


def test_requests_are_exactly_two_per_accession(tmp_path):
    result = _plan(tmp_path)
    for shard in result.shards:
        assert shard.planned_requests == 2 * len(shard.accessions)
    assert result.counts["planned_requests"] == 2 * result.counts["unique_accessions"]


def test_every_emitted_plan_loads_through_the_real_loader(tmp_path):
    result = _plan(tmp_path)
    for shard in result.shards:
        planned, fields, sha = load_request_plan(
            result.run_dir / shard_plan_filename(shard.shard_index))
        assert fields["plan_contract"] == PLAN_CONTRACT_V2
        assert fields["max_retained_bytes"] == shard.max_retained_bytes
        assert len(planned) == len(shard.accessions)
        assert sha == shard.plan_sha256


def test_plans_are_written_once_and_hashed_by_the_manifest(tmp_path):
    result = _plan(tmp_path)
    manifest = read_json(result.manifest_path)
    assert not list(
        Draft202012Validator(read_json(PLAN_MANIFEST_SCHEMA)).iter_errors(manifest))
    for shard in result.shards:
        name = shard_plan_filename(shard.shard_index)
        on_disk = (result.run_dir / name).read_bytes()
        assert manifest["output_hashes"][name] == sha256(on_disk).hexdigest()
    assert PLAN_MANIFEST_FILENAME not in manifest["output_hashes"]
    assert manifest["deferred_cohorts"][0]["stratum"] == "fpi_extension"


def test_planner_run_id_is_immutable(tmp_path):
    _plan(tmp_path, run_id="once")
    with pytest.raises(FileExistsError):
        _plan(tmp_path, run_id="once")


# --- the retained-byte budget ------------------------------------------------


def test_budget_refusal_writes_no_authoritative_manifest(tmp_path):
    plan = _plan(tmp_path, definition=TIGHT)
    result = _execute(tmp_path, plan, indices=[0], requests=4, definition=TIGHT)
    execution = result.executions[0]
    assert execution.outcome == "failed"
    run_dir = Path(execution.run_dir)
    assert not (run_dir / BUNDLE_MANIFEST_FILENAME).exists()
    assert not (run_dir / ACQUISITION_MANIFEST_FILENAME).exists()
    receipt = read_json(run_dir / FAILURE_RECEIPT_FILENAME)
    assert receipt["reason_code"] == "shard_retained_byte_budget_exhausted"
    assert execution.failure_reason_code == "shard_retained_byte_budget_exhausted"
    assert execution.receipt_present is True


def test_the_over_budget_document_is_never_written(tmp_path):
    plan = _plan(tmp_path, definition=TIGHT)
    result = _execute(tmp_path, plan, indices=[0], requests=4, definition=TIGHT)
    run_dir = Path(result.executions[0].run_dir)
    receipt = read_json(run_dir / FAILURE_RECEIPT_FILENAME)
    written = sorted(p.name for p in run_dir.glob("primary-*.html"))
    # Retained files persist and are named; the refused one is absent.
    assert written == sorted(receipt["retained_raw_filenames"])
    budget = 400  # the tight definition's per-accession allowance
    assert sum((run_dir / n).stat().st_size for n in written) <= 2 * budget


def test_authoritative_manifests_never_exceed_their_budget(tmp_path):
    plan = _plan(tmp_path)
    result = _execute(tmp_path, plan, indices=[0, 1], requests=6)
    for execution in result.executions:
        manifest = read_json(Path(execution.run_dir) / ACQUISITION_MANIFEST_FILENAME)
        assert manifest["retained_bytes_total"] <= manifest["retained_byte_budget"]
        assert manifest["budget_enforcement"] == {
            "mechanism": "pre_write_retained_byte_check",
            "bounds": "disk",
            "checked_against": "materialised_body_length",
        }


# --- the executor ------------------------------------------------------------


def test_executor_refuses_a_hand_edited_plan(tmp_path):
    plan = _plan(tmp_path)
    target = plan.run_dir / shard_plan_filename(0)
    payload = json.loads(target.read_text())
    payload["description"] = "edited after planning"
    target.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    with pytest.raises(AcquisitionQueueError, match="changed after planning"):
        _execute(tmp_path, plan, indices=[0], requests=4)


def test_executor_refuses_a_plan_tampered_with_a_matching_manifest(tmp_path):
    """Rehashing the tamper into the manifest does not launder it.

    The manifest-hash binding passes here, so the byte-for-byte comparison
    against the plan regenerated from the named definition is what refuses.
    """
    plan = _plan(tmp_path)
    target = plan.run_dir / shard_plan_filename(0)
    payload = json.loads(target.read_text())
    payload["description"] = "edited after planning"
    tampered = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    target.write_bytes(tampered)
    manifest_path = plan.run_dir / PLAN_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text())
    manifest["output_hashes"][shard_plan_filename(0)] = sha256(tampered).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(AcquisitionQueueError, match="byte for byte"):
        _execute(tmp_path, plan, indices=[0], requests=4)


def test_executor_refuses_a_plan_from_another_definition(tmp_path):
    plan = _plan(tmp_path)
    other = _plan(tmp_path, definition=RESTRICTED, run_id="other")
    # Swap a foreign artefact into the plan directory under the right name.
    (plan.run_dir / shard_plan_filename(0)).unlink()
    (plan.run_dir / shard_plan_filename(0)).write_bytes(
        (other.run_dir / shard_plan_filename(0)).read_bytes())
    with pytest.raises(AcquisitionQueueError):
        _execute(tmp_path, plan, indices=[0], requests=4)


def test_executor_refuses_a_missing_plan_artefact(tmp_path):
    plan = _plan(tmp_path)
    (plan.run_dir / shard_plan_filename(0)).unlink()
    with pytest.raises(AcquisitionQueueError, match="persisted plans only"):
        _execute(tmp_path, plan, indices=[0], requests=4)


@pytest.mark.parametrize("indices,message", [
    ([], "explicit shard-index allowlist"),
    ([0, 0], "Duplicate shard indices"),
    ([0, 9], "outside this queue"),
])
def test_executor_refuses_bad_allowlists(tmp_path, indices, message):
    plan = _plan(tmp_path)
    with pytest.raises(AcquisitionQueueError, match=message):
        _execute(tmp_path, plan, indices=indices, requests=4)


def test_executor_refuses_a_wrong_expected_request_count(tmp_path):
    plan = _plan(tmp_path)
    with pytest.raises(AcquisitionQueueError, match="must be stated exactly"):
        _execute(tmp_path, plan, indices=[0, 1], requests=99)


def test_executor_refuses_an_undeclared_stop_policy(tmp_path):
    plan = _plan(tmp_path)
    with pytest.raises(AcquisitionQueueError, match="never defaulted"):
        _execute(tmp_path, plan, indices=[0], requests=4, on_failure="maybe")


def test_executor_creates_one_immutable_run_directory_per_shard(tmp_path):
    plan = _plan(tmp_path)
    result = _execute(tmp_path, plan, indices=[0, 1], requests=6)
    dirs = [Path(e.run_dir) for e in result.executions]
    assert len(dirs) == len(set(dirs)) == 2
    assert [d.name for d in dirs] == ["qexec-shard-0000", "qexec-shard-0001"]


def test_reusing_an_execution_run_id_is_refused(tmp_path):
    """Checked on failed shards, so the authoritative-shard guard cannot mask it.

    That guard deliberately fires first: refusing to redo completed work is
    checked before the filesystem is touched at all.
    """
    plan = _plan(tmp_path, definition=TIGHT)
    first = _execute(tmp_path, plan, indices=[0], requests=4, definition=TIGHT,
                     run_id="reused")
    assert first.executions[0].outcome == "failed"
    with pytest.raises(FileExistsError):
        _execute(tmp_path, plan, indices=[1], requests=2, definition=TIGHT,
                 run_id="reused")


def test_stop_policy_leaves_later_shards_unattempted(tmp_path):
    plan = _plan(tmp_path, definition=TIGHT)
    result = _execute(tmp_path, plan, indices=[0, 1], requests=6,
                      definition=TIGHT, on_failure="stop")
    outcomes = [e.outcome for e in result.executions]
    assert outcomes == ["failed", "not_attempted"]
    assert result.stopped_at_shard_index == 0
    assert result.executions[1].run_dir is None


def test_continue_policy_attempts_every_named_shard(tmp_path):
    plan = _plan(tmp_path, definition=TIGHT)
    result = _execute(tmp_path, plan, indices=[0, 1], requests=6,
                      definition=TIGHT, on_failure="continue")
    assert [e.outcome for e in result.executions] == ["failed", "failed"]
    assert result.stopped_at_shard_index is None
    assert all(e.run_dir is not None for e in result.executions)


def test_executor_refuses_an_already_authoritative_shard(tmp_path):
    plan = _plan(tmp_path)
    _execute(tmp_path, plan, indices=[0], requests=4, run_id="first")
    with pytest.raises(AcquisitionQueueError, match="already has a bound authoritative"):
        _execute(tmp_path, plan, indices=[0], requests=4, run_id="second")


def test_a_prior_corrupt_pair_is_an_integrity_error_not_completed_work(tmp_path):
    """A corrupt pair must not be described as an already-authoritative shard."""
    plan = _plan(tmp_path)
    first = _execute(tmp_path, plan, indices=[0], requests=4, run_id="first")
    path = Path(first.executions[0].run_dir) / ACQUISITION_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    manifest["plan_sha256"] = "f" * 64
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(ShardIntegrityError, match="acquired a different plan") as raised:
        _execute(tmp_path, plan, indices=[0], requests=4, run_id="second")
    assert "already has a bound authoritative" not in str(raised.value)
    assert not (tmp_path / "shards" / "second").exists()


def test_a_bound_shard_with_a_stale_receipt_still_blocks_re_execution(tmp_path):
    plan = _plan(tmp_path)
    first = _execute(tmp_path, plan, indices=[0], requests=4, run_id="first")
    run_dir = Path(first.executions[0].run_dir)
    (run_dir / FAILURE_RECEIPT_FILENAME).write_text(
        json.dumps({"reason_code": "stale_from_an_earlier_attempt"}) + "\n")
    assert manifest_pair_present(run_dir) == (True, True)
    with pytest.raises(AcquisitionQueueError, match="already has a bound authoritative"):
        _execute(tmp_path, plan, indices=[0], requests=4, run_id="second")


def test_executor_cannot_record_an_unbound_child_as_authoritative(tmp_path):
    """A child that completes but does not bind fails the run closed.

    The acquisition runner is stubbed to leave a manifest pair whose content
    belongs to no shard, which is exactly what the executor must never label
    authoritative.
    """
    plan = _plan(tmp_path)

    def forging_runner(*, repo_root, request_plan_path, output_dir, run_id,
                       clock, **kwargs):
        from dynamic_ai_products.universe.freeze import create_run_directory
        run_dir = create_run_directory(output_dir, run_id)
        (run_dir / BUNDLE_MANIFEST_FILENAME).write_text("{}")
        (run_dir / ACQUISITION_MANIFEST_FILENAME).write_text("{}")

        class _Result:
            pass

        result = _Result()
        result.run_dir = run_dir
        return result

    with pytest.raises(ShardIntegrityError):
        run_queue_executor(
            repo_root=ROOT, definition_path=DEFINITION,
            plan_dir=plan.run_dir, shard_indices=[0],
            expected_request_count=4, on_shard_failure="stop",
            output_dir=tmp_path / "shards", run_id="forged",
            acquire=forging_runner, clock=CLOCK,
        )
    execution_manifest = tmp_path / "shards" / "forged" / EXECUTION_MANIFEST_FILENAME
    assert not execution_manifest.exists(), (
        "no execution manifest may label an unbound shard authoritative")


def test_resume_runs_exactly_the_named_non_authoritative_shards(tmp_path):
    plan = _plan(tmp_path)
    first = _execute(tmp_path, plan, indices=[0], requests=4, run_id="first")
    assert first.executions[0].outcome == "authoritative"
    # Shard 1 was never attempted; resume names only it.
    resumed = _execute(tmp_path, plan, indices=[1], requests=2, run_id="resume")
    assert [e.shard_index for e in resumed.executions] == [1]
    assert resumed.executions[0].outcome == "authoritative"


def test_executor_writes_no_aggregate(tmp_path):
    plan = _plan(tmp_path)
    result = _execute(tmp_path, plan, indices=[0, 1], requests=6)
    assert (result.run_dir / EXECUTION_MANIFEST_FILENAME).is_file()
    for directory in (result.run_dir, tmp_path / "shards"):
        assert not (directory / AGGREGATE_MANIFEST_FILENAME).exists()


def test_execution_manifest_validates_and_states_its_boundary(tmp_path):
    plan = _plan(tmp_path)
    result = _execute(tmp_path, plan, indices=[0, 1], requests=6)
    manifest = read_json(result.manifest_path)
    assert not list(
        Draft202012Validator(read_json(EXECUTION_SCHEMA)).iter_errors(manifest))
    assert manifest["authorized_shard_indices"] == [0, 1]
    assert manifest["counts"]["expected_request_count"] == 6
    joined = " ".join(manifest["limitations"])
    assert "confers nothing on any other index" in joined
    assert "aggregation is a separate command" in joined


# --- authority and aggregation ------------------------------------------------


def test_manifest_pair_present_reports_presence_not_authority(tmp_path):
    """Two empty files are a candidate, and explicitly not authority."""
    directory = tmp_path / "shard"
    directory.mkdir()
    assert manifest_pair_present(directory) == (False, False)
    (directory / FAILURE_RECEIPT_FILENAME).write_text("{}")
    assert manifest_pair_present(directory) == (False, True)
    (directory / BUNDLE_MANIFEST_FILENAME).write_text("{}")
    assert manifest_pair_present(directory)[0] is False, "one file is not a pair"
    (directory / ACQUISITION_MANIFEST_FILENAME).write_text("{}")
    # The pair is present; the receipt neither grants nor revokes anything.
    assert manifest_pair_present(directory) == (True, True)
    # And presence alone admits nothing: binding refuses these two files.
    plan = _plan(tmp_path)
    with pytest.raises(ShardIntegrityError):
        _bind_shard_manifest(ROOT, directory, plan.shards[0])


def test_aggregate_admits_only_authoritative_shards(tmp_path):
    plan = _plan(tmp_path)
    _execute(tmp_path, plan, indices=[0, 1], requests=6)
    aggregate = run_queue_aggregator(
        repo_root=ROOT, definition_path=DEFINITION,
        shard_output_dir=tmp_path / "shards", execution_run_id="qexec",
        output_dir=tmp_path / "agg", run_id="qagg", clock=CLOCK)
    manifest = aggregate.manifest
    assert not list(
        Draft202012Validator(read_json(AGGREGATE_SCHEMA)).iter_errors(manifest))
    assert manifest["coverage_complete"] is True
    assert manifest["counts"]["shards_authoritative"] == 2
    assert manifest["counts"]["carrier_rows_covered"] == 4
    assert manifest["shards_not_authoritative"] == []


def test_aggregate_excludes_a_handled_failure_and_reports_partial(tmp_path):
    plan = _plan(tmp_path, definition=TIGHT)
    _execute(tmp_path, plan, indices=[0, 1], requests=6, definition=TIGHT,
             on_failure="continue")
    aggregate = run_queue_aggregator(
        repo_root=ROOT, definition_path=TIGHT,
        shard_output_dir=tmp_path / "shards", execution_run_id="qexec",
        output_dir=tmp_path / "agg", run_id="qagg", clock=CLOCK)
    manifest = aggregate.manifest
    assert manifest["coverage_complete"] is False
    assert "PARTIAL" in manifest["coverage_statement"]
    assert manifest["counts"]["shards_authoritative"] == 0
    reasons = {s["reason"] for s in manifest["shards_not_authoritative"]}
    assert reasons == {"handled_failure"}
    assert all(s["receipt_present"] for s in manifest["shards_not_authoritative"])


def test_aggregate_excludes_a_receiptless_interrupted_shard(tmp_path):
    """A crash may leave no receipt at all; that is still not authority."""
    plan = _plan(tmp_path)
    _execute(tmp_path, plan, indices=[0, 1], requests=6)
    # Simulate an interruption: manifests never written, no receipt.
    interrupted = tmp_path / "shards" / "qexec-shard-0001"
    (interrupted / BUNDLE_MANIFEST_FILENAME).unlink()
    (interrupted / ACQUISITION_MANIFEST_FILENAME).unlink()
    assert not (interrupted / FAILURE_RECEIPT_FILENAME).exists()
    aggregate = run_queue_aggregator(
        repo_root=ROOT, definition_path=DEFINITION,
        shard_output_dir=tmp_path / "shards", execution_run_id="qexec",
        output_dir=tmp_path / "agg", run_id="qagg", clock=CLOCK)
    manifest = aggregate.manifest
    assert manifest["coverage_complete"] is False
    excluded = manifest["shards_not_authoritative"]
    assert len(excluded) == 1
    assert excluded[0]["shard_index"] == 1
    assert excluded[0]["receipt_present"] is False
    assert excluded[0]["reason"] == "interrupted_or_incomplete"
    assert excluded[0]["failure_reason_code"] is None


def test_aggregate_hashes_shard_manifests_and_is_hashed_by_none(tmp_path):
    plan = _plan(tmp_path)
    _execute(tmp_path, plan, indices=[0, 1], requests=6)
    aggregate = run_queue_aggregator(
        repo_root=ROOT, definition_path=DEFINITION,
        shard_output_dir=tmp_path / "shards", execution_run_id="qexec",
        output_dir=tmp_path / "agg", run_id="qagg", clock=CLOCK)
    manifest = aggregate.manifest
    for entry in manifest["shards_authoritative"]:
        run_dir = Path(entry["run_dir"])
        assert entry["acquisition_manifest_sha256"] == sha256(
            (run_dir / ACQUISITION_MANIFEST_FILENAME).read_bytes()).hexdigest()
        assert entry["bundle_manifest_sha256"] == sha256(
            (run_dir / BUNDLE_MANIFEST_FILENAME).read_bytes()).hexdigest()
        shard_manifest = read_json(run_dir / ACQUISITION_MANIFEST_FILENAME)
        assert AGGREGATE_MANIFEST_FILENAME not in shard_manifest["output_hashes"]




# --- persisted plan-manifest authority ----------------------------------------


def _no_execution_run_dir(tmp_path: Path, run_id: str = "qexec") -> bool:
    """Nothing may be created by a preflight refusal."""
    shards = tmp_path / "shards"
    if not shards.is_dir():
        return True
    return not any(c.name.startswith(run_id) for c in shards.iterdir())


def test_executor_refuses_a_directory_with_no_planner_manifest(tmp_path):
    """A byte-identical plan without its planner manifest is not authority."""
    plan = _plan(tmp_path)
    hand_built = tmp_path / "hand-built"
    hand_built.mkdir()
    name = shard_plan_filename(0)
    (hand_built / name).write_bytes((plan.run_dir / name).read_bytes())
    assert (hand_built / name).read_bytes() == (plan.run_dir / name).read_bytes()
    plan.run_dir = hand_built
    with pytest.raises(AcquisitionQueueError, match="not a plan directory"):
        _execute(tmp_path, plan, indices=[0], requests=4)
    assert _no_execution_run_dir(tmp_path)


def test_executor_refuses_a_malformed_plan_manifest(tmp_path):
    plan = _plan(tmp_path)
    (plan.run_dir / PLAN_MANIFEST_FILENAME).write_text("{ not json")
    with pytest.raises(AcquisitionQueueError, match="not valid JSON"):
        _execute(tmp_path, plan, indices=[0], requests=4)
    assert _no_execution_run_dir(tmp_path)


def test_executor_refuses_a_schema_invalid_plan_manifest(tmp_path):
    plan = _plan(tmp_path)
    path = plan.run_dir / PLAN_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    del manifest["output_hashes"]
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(AcquisitionQueueError, match="violates the canonical schema"):
        _execute(tmp_path, plan, indices=[0], requests=4)
    assert _no_execution_run_dir(tmp_path)


def test_executor_refuses_a_plan_manifest_from_another_definition(tmp_path):
    plan = _plan(tmp_path)
    path = plan.run_dir / PLAN_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    manifest["queue_definition_sha256"] = "c" * 64
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(AcquisitionQueueError, match="not the named"):
        _execute(tmp_path, plan, indices=[0], requests=4)
    assert _no_execution_run_dir(tmp_path)


def test_executor_refuses_a_plan_manifest_that_omits_the_shard(tmp_path):
    plan = _plan(tmp_path)
    path = plan.run_dir / PLAN_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    manifest["shards"] = [s for s in manifest["shards"] if s["shard_index"] != 0]
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(AcquisitionQueueError, match="does not enumerate shard 0"):
        _execute(tmp_path, plan, indices=[0], requests=4)
    assert _no_execution_run_dir(tmp_path)


def test_executor_refuses_a_plan_manifest_with_a_wrong_output_hash(tmp_path):
    plan = _plan(tmp_path)
    path = plan.run_dir / PLAN_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    manifest["output_hashes"][shard_plan_filename(0)] = "d" * 64
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(AcquisitionQueueError, match="changed after planning"):
        _execute(tmp_path, plan, indices=[0], requests=4)
    assert _no_execution_run_dir(tmp_path)


def test_executor_refuses_a_plan_manifest_missing_the_output_hash_entry(tmp_path):
    plan = _plan(tmp_path)
    path = plan.run_dir / PLAN_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    del manifest["output_hashes"][shard_plan_filename(0)]
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(AcquisitionQueueError, match="carries no authority"):
        _execute(tmp_path, plan, indices=[0], requests=4)
    assert _no_execution_run_dir(tmp_path)


def test_executor_refuses_a_recorded_plan_hash_that_does_not_regenerate(tmp_path):
    plan = _plan(tmp_path)
    path = plan.run_dir / PLAN_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    for entry in manifest["shards"]:
        if entry["shard_index"] == 0:
            entry["shard_plan_sha256"] = "e" * 64
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(AcquisitionQueueError, match="regenerated from the named"):
        _execute(tmp_path, plan, indices=[0], requests=4)
    assert _no_execution_run_dir(tmp_path)


def test_a_later_shard_preflight_failure_leaves_no_run_directory(tmp_path):
    """Every requested shard is verified before anything is created."""
    plan = _plan(tmp_path)
    (plan.run_dir / shard_plan_filename(1)).unlink()
    with pytest.raises(AcquisitionQueueError):
        _execute(tmp_path, plan, indices=[0, 1], requests=6)
    assert _no_execution_run_dir(tmp_path)
    assert not (tmp_path / "shards" / "qexec-shard-0000").exists()


# --- aggregate admission binds content ----------------------------------------


def _authoritative_shard(tmp_path: Path) -> Path:
    plan = _plan(tmp_path)
    result = _execute(tmp_path, plan, indices=[0, 1], requests=6)
    return Path(result.executions[0].run_dir)


def _aggregate(tmp_path: Path, definition: Path = DEFINITION):
    return run_queue_aggregator(
        repo_root=ROOT, definition_path=definition,
        shard_output_dir=tmp_path / "shards", execution_run_id="qexec",
        output_dir=tmp_path / "agg", run_id="qagg", clock=CLOCK)


def test_aggregate_refuses_a_plan_sha_mismatch(tmp_path):
    """Both filenames present, but the run acquired a different plan."""
    run_dir = _authoritative_shard(tmp_path)
    path = run_dir / ACQUISITION_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    manifest["plan_sha256"] = "f" * 64
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(ShardIntegrityError, match="acquired a different plan"):
        _aggregate(tmp_path)


def test_aggregate_refuses_inconsistent_counts(tmp_path):
    run_dir = _authoritative_shard(tmp_path)
    path = run_dir / ACQUISITION_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    manifest["counts"]["bundle_entries"] += 1
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(ShardIntegrityError, match="counts do not match"):
        _aggregate(tmp_path)


def test_aggregate_refuses_a_bundle_output_hash_mismatch(tmp_path):
    run_dir = _authoritative_shard(tmp_path)
    bundle = run_dir / BUNDLE_MANIFEST_FILENAME
    payload = json.loads(bundle.read_text())
    payload["description"] = "tampered after the run"
    bundle.write_text(json.dumps(payload, indent=2) + "\n")
    with pytest.raises(ShardIntegrityError, match="bundle manifest on disk hashes"):
        _aggregate(tmp_path)


def test_aggregate_refuses_a_budget_overrun_in_the_record(tmp_path):
    run_dir = _authoritative_shard(tmp_path)
    path = run_dir / ACQUISITION_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    manifest["retained_bytes_total"] = manifest["retained_byte_budget"] + 1
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(ShardIntegrityError, match="exceeds the shard budget"):
        _aggregate(tmp_path)


def test_aggregate_refuses_a_malformed_acquisition_manifest(tmp_path):
    run_dir = _authoritative_shard(tmp_path)
    (run_dir / ACQUISITION_MANIFEST_FILENAME).write_text("{ not json")
    with pytest.raises(ShardIntegrityError, match="not valid JSON"):
        _aggregate(tmp_path)


def test_aggregate_refuses_a_malformed_bundle_manifest(tmp_path):
    run_dir = _authoritative_shard(tmp_path)
    (run_dir / BUNDLE_MANIFEST_FILENAME).write_text("{ not json")
    with pytest.raises(ShardIntegrityError, match="not valid JSON"):
        _aggregate(tmp_path)


def test_aggregate_refuses_two_arbitrary_files_named_like_manifests(tmp_path):
    """The exact case the binding exists for."""
    plan = _plan(tmp_path)
    _execute(tmp_path, plan, indices=[0], requests=4)
    forged = tmp_path / "shards" / "qexec-shard-0001"
    forged.mkdir()
    (forged / BUNDLE_MANIFEST_FILENAME).write_text("{}")
    (forged / ACQUISITION_MANIFEST_FILENAME).write_text("{}")
    with pytest.raises(ShardIntegrityError):
        _aggregate(tmp_path)


def test_integrity_failure_is_not_reported_as_ordinary_partial_coverage(tmp_path):
    """Fail closed: a corrupt shard must not be silently downgraded."""
    run_dir = _authoritative_shard(tmp_path)
    path = run_dir / ACQUISITION_MANIFEST_FILENAME
    manifest = json.loads(path.read_text())
    manifest["plan_sha256"] = "f" * 64
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    with pytest.raises(ShardIntegrityError):
        _aggregate(tmp_path)
    assert not (tmp_path / "agg" / "qagg").exists(), "no aggregate is written"
    assert issubclass(ShardIntegrityError, AcquisitionQueueError)


def test_a_valid_shard_with_a_stale_receipt_still_aggregates(tmp_path):
    """Preserved: the receipt is diagnostic, and content binding still holds."""
    run_dir = _authoritative_shard(tmp_path)
    (run_dir / FAILURE_RECEIPT_FILENAME).write_text(
        json.dumps({"reason_code": "stale_from_an_earlier_attempt"}) + "\n")
    assert manifest_pair_present(run_dir) == (True, True)
    manifest = _aggregate(tmp_path).manifest
    assert manifest["coverage_complete"] is True
    assert manifest["counts"]["shards_authoritative"] == 2
    assert manifest["shards_not_authoritative"] == []


# --- ADR-095 wording ----------------------------------------------------------


# --- restricted definitions ---------------------------------------------------


def test_restricted_definition_selects_exactly_its_accessions(tmp_path):
    result = _plan(tmp_path, definition=RESTRICTED)
    selected = [a for s in result.shards for a in s.accessions]
    assert selected == ["0009200002-22-000002", "0009200003-22-000003"]
    assert result.counts["shards"] == 2, "shard_size 1 over two accessions"


def test_restricted_definition_refuses_an_absent_accession(tmp_path):
    payload = read_json(RESTRICTED)
    payload["selection"]["restricted_accessions"] = ["9999999999-99-999999"]
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    with pytest.raises(AcquisitionQueueError, match="absent from the"):
        _plan(tmp_path, definition=path)


# --- definition validation ----------------------------------------------------


def test_committed_definitions_validate_against_the_schema():
    validator = Draft202012Validator(read_json(DEFINITION_SCHEMA))
    for name in ("domestic_primary_document_queue.json",
                 "queue_canary_definition.json"):
        payload = read_json(ROOT / "configs" / name)
        assert not list(validator.iter_errors(payload)), name
        assert load_queue_definition(ROOT / "configs" / name).queue_id


def test_the_fpi_cohort_is_recorded_as_deferred_not_dropped():
    for name in ("domestic_primary_document_queue.json",
                 "queue_canary_definition.json"):
        deferred = read_json(ROOT / "configs" / name)["deferred_cohorts"]
        assert len(deferred) == 1
        assert deferred[0]["stratum"] == "fpi_extension"
        assert deferred[0]["rows"] == 1198
        assert deferred[0]["accessions"] == 1193
        assert "Deferred, not excluded" in deferred[0]["reason"]


def test_the_canary_definition_is_a_cohort_not_two_shards_of_the_full_queue():
    canary = read_json(ROOT / "configs" / "queue_canary_definition.json")
    full = read_json(ROOT / "configs" / "domestic_primary_document_queue.json")
    assert canary["queue_id"] != full["queue_id"]
    assert "restricted_accessions" in canary["selection"]
    assert "restricted_accessions" not in full["selection"]
    assert len(canary["selection"]["restricted_accessions"]) == 6
    assert canary["shard_size"] == 3
    assert "NOT shard 0 and shard 1" in canary["description"]


@pytest.mark.parametrize("mutate,message", [
    (lambda d: d.update(queue_contract="acquisition_queue_definition@9.9.9"),
     "must declare"),
    (lambda d: d["selection"].update(stratum="fpi_extension"), "must be 'domestic'"),
    (lambda d: d["selection"].update(forms=["20-F"]), "duplicate-free subset"),
    (lambda d: d.update(shard_size=0), "positive integer"),
    (lambda d: d.update(per_accession_allowance_bytes=-1), "positive integer"),
    (lambda d: d["carrier"].update(carrier_manifest_sha256="ABC"), "64-hex"),
    (lambda d: d["carrier"].update(relative_path="/etc/passwd"), "repository-relative"),
    (lambda d: d["carrier"].update(relative_path="../escape.jsonl"), "repository-relative"),
    (lambda d: d.update(queue_id="Bad_Id"), "lowercase letters"),
])
def test_queue_definition_refusals(tmp_path, mutate, message):
    payload = read_json(DEFINITION)
    mutate(payload)
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload, indent=2) + "\n")
    with pytest.raises(AcquisitionQueueError, match=message):
        load_queue_definition(path)


# --- boundaries ----------------------------------------------------------------


def test_module_has_no_network_symbol():
    import ast

    path = (
        ROOT / "src" / "dynamic_ai_products" / "universe" / "acquisition_queue.py"
    )
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    roots = {name.split(".")[0] for name in imported}
    assert not roots & {"httpx", "requests", "socket", "urllib", "http"}


def test_planner_writes_no_request_and_says_so(tmp_path):
    manifest = read_json(_plan(tmp_path).manifest_path)
    joined = " ".join(manifest["limitations"])
    assert "makes no request" in joined
    assert "authorizes nothing" in joined
    assert "bound, not a prediction" in joined


# --- the frozen carrier, when it is present -----------------------------------


CARRIER = (
    ROOT / "data" / "runs" / "universe-baseline-carrier"
    / "universe-baseline-carrier-frame-v1-20260816"
    / "universe_baseline_carrier.jsonl"
)


@pytest.mark.skipif(not CARRIER.exists(), reason="local frozen carrier absent")
def test_full_queue_counts_are_derived_from_the_carrier(tmp_path):
    """Read-only: the committed queue must match the carrier exactly."""
    definition = load_queue_definition(
        ROOT / "configs" / "domestic_primary_document_queue.json")
    groups = select_carrier_accessions(definition, CARRIER)
    shards = build_shard_plans(definition, groups)
    assert len(groups) == 8526
    assert sum(len(v) for v in groups.values()) == 8718
    assert len(shards) == 86
    assert sum(s.planned_requests for s in shards) == 17052
    assert sum(len(s.accessions) for s in shards) == 8526
    shared = [a for a, rows in groups.items() if len(rows) > 1]
    assert len(shared) == 134
    assert sum(len(groups[a]) for a in shared) == 326


@pytest.mark.skipif(not CARRIER.exists(), reason="local frozen carrier absent")
def test_canary_definition_rederives_complete_groups(tmp_path):
    """Every selected accession carries its complete carrier group."""
    definition = load_queue_definition(
        ROOT / "configs" / "queue_canary_definition.json")
    groups = select_carrier_accessions(definition, CARRIER)
    assert len(groups) == 6
    # Complete groups: recount each accession against the whole carrier.
    complete: dict[str, set[str]] = {}
    for line in CARRIER.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        accession = row.get("baseline_accession")
        if accession in groups:
            complete.setdefault(accession, set()).add(row["cik"])
    for accession, rows in groups.items():
        assert {r["cik"] for r in rows} == complete[accession], accession

    shards = build_shard_plans(definition, groups)
    assert [s.shard_index for s in shards] == [0, 1]
    assert sum(s.planned_requests for s in shards) == 12
    assert sum(s.carrier_rows for s in shards) == 14
    assert shards[0].accessions == (
        "0001104659-22-024443", "0001437749-22-027522", "0001578443-22-000007")
    assert shards[1].accessions == (
        "0001628280-22-024293", "0001888524-22-003211", "0001888524-22-003213")
    # Coverage the canary exists to exercise.
    forms = {d["form"] for s in shards for d in s.payload["documents"]}
    assert forms == {"10-K", "10-KT"}
    shared = [d for s in shards for d in s.payload["documents"]
              if len(d["carrier_rows"]) > 1]
    assert sorted(len(d["carrier_rows"]) for d in shared) == [3, 7]


# --- CLI -----------------------------------------------------------------------


def _cli(*args):
    import subprocess
    import sys

    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, check=False)


def test_cli_plan_execute_aggregate(tmp_path):
    planned = _cli("--mode", "plan-acquisition-queue",
                   "--queue-definition", str(DEFINITION),
                   "--output-dir", str(tmp_path / "plans"), "--run-id", "p")
    assert planned.returncode == 0, planned.stderr
    plan_dir = json.loads(planned.stdout)["run_dir"]

    executed = _cli("--mode", "execute-acquisition-queue",
                    "--queue-definition", str(DEFINITION),
                    "--plan-dir", plan_dir, "--shard-indices", "0,1",
                    "--expected-request-count", "6",
                    "--on-shard-failure", "stop",
                    "--replay-dir", str(REPLAY),
                    "--shard-output-dir", str(tmp_path / "shards"),
                    "--output-dir", str(tmp_path / "exec"), "--run-id", "e")
    assert executed.returncode == 0, executed.stderr
    assert json.loads(executed.stdout)["counts"]["shards_authoritative"] == 2

    aggregated = _cli("--mode", "aggregate-acquisition-queue",
                      "--queue-definition", str(DEFINITION),
                      "--shard-output-dir", str(tmp_path / "shards"),
                      "--execution-run-id", "e",
                      "--output-dir", str(tmp_path / "agg"), "--run-id", "a")
    assert aggregated.returncode == 0, aggregated.stderr
    assert json.loads(aggregated.stdout)["coverage_complete"] is True


@pytest.mark.parametrize("value", ["all", "0-5", "*", "0,,", "-1"])
def test_cli_refuses_non_enumerated_shard_indices(tmp_path, value):
    completed = _cli("--mode", "execute-acquisition-queue",
                     "--queue-definition", str(DEFINITION),
                     "--plan-dir", str(tmp_path), "--shard-indices", value,
                     "--expected-request-count", "6",
                     "--on-shard-failure", "stop",
                     "--replay-dir", str(REPLAY),
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "--shard-indices" in completed.stderr
    assert "Ranges and 'all' are refused." in completed.stderr or (
        "empty segment" in completed.stderr
    ) or "at least one index" in completed.stderr


def test_cli_execute_requires_every_authorization_flag(tmp_path):
    for missing in ("--shard-indices", "--expected-request-count",
                    "--on-shard-failure", "--plan-dir"):
        argv = ["--mode", "execute-acquisition-queue",
                "--queue-definition", str(DEFINITION),
                "--plan-dir", str(tmp_path), "--shard-indices", "0",
                "--expected-request-count", "4", "--on-shard-failure", "stop",
                "--replay-dir", str(REPLAY),
                "--output-dir", str(tmp_path / "o"), "--run-id", "r"]
        index = argv.index(missing)
        del argv[index:index + 2]
        completed = _cli(*argv)
        assert completed.returncode != 0, missing
        assert "requires" in completed.stderr, missing


def test_cli_execute_refuses_a_hand_supplied_request_plan(tmp_path):
    completed = _cli("--mode", "execute-acquisition-queue",
                     "--queue-definition", str(DEFINITION),
                     "--plan-dir", str(tmp_path), "--shard-indices", "0",
                     "--expected-request-count", "4",
                     "--on-shard-failure", "stop",
                     "--request-plan", str(REPLAY / "request_plan.json"),
                     "--replay-dir", str(REPLAY),
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "never runs a hand-supplied plan" in completed.stderr


def test_cli_rejects_queue_flags_on_other_modes(tmp_path):
    completed = _cli("--mode", "determine-shell-company",
                     "--bundle-dir", str(tmp_path),
                     "--queue-definition", str(DEFINITION),
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr
