"""ADR-123 tests: an unverified row is re-asked, never edited.

Everything is offline. The source screen is a real completed continuation-v5
run built from fixture packets, the transport is the same fake the continuation
suite uses, every wait is a recorded call rather than a sleep, and no test
builds a ``genai.Client``, resolves a credential, or opens a socket.
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import lineage_screen_continuation_v5 as lc5
from dynamic_ai_products import lineage_screen_diagnostic as ld
from dynamic_ai_products import lineage_screen_diagnostic_repair as ldr
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products import lineage_screen_repair as lr
from dynamic_ai_products.providers import screen_count_retry_policy as cp
from dynamic_ai_products.providers import screen_retry_policy as gp
from dynamic_ai_products.providers.client_contract_v2 import CLIENT_CONTRACT_V2_ID
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_screen_continuation import _script  # noqa: E402
from test_lineage_screen_continuation_v5 import (  # noqa: E402
    FIXED_CLOCK,
    PREFIX_ROWS,
    _EmptyBodyFactory,
    _run as _run_source,
    _setup as _setup_source,
)
from test_lineage_screen_diagnostic import _v5_evidence_payload  # noqa: E402
from test_lineage_screen_live import (  # noqa: E402
    ROOT,
    VERTEX_LOCATION,
    VERTEX_PROJECT,
    _contract_digest,
    _endpoints,
)
from test_lineage_screen_live_v3 import _governance as _v3_governance  # noqa: E402

REPAIR_PROMPT = "prompts/discovery/universe_high_recall_screen_repair.v1.md"
SCREEN_PROMPT = "prompts/discovery/universe_high_recall_screen.v5.md"

MANIFEST_SCHEMA = json.loads(
    (ROOT / "schemas/universe_screen_repair_manifest.schema.json")
    .read_text(encoding="utf-8"))
SELECTION_SCHEMA = json.loads(
    (ROOT / "schemas/universe_screen_repair_selection.schema.json")
    .read_text(encoding="utf-8"))
RECORD_V6_SCHEMA = json.loads(
    (ROOT / "schemas/universe_screen_record.v6.schema.json")
    .read_text(encoding="utf-8"))

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
    assert not added, f"the repair path imported google: {sorted(added)}"


def _bad_quote_payload(packet) -> str:
    """A well-formed answer whose quote resolves in no passage."""
    return _v5_evidence_payload(packet, quote="text that appears in no passage")


# --- a real completed continuation-v5 run, used as the repair source ---------------


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    from test_lineage_screen_continuation_v5 import cohort as _cohort
    return _cohort.__wrapped__(tmp_path_factory)


@pytest.fixture
def source(cohort, tmp_path):
    """A completed screen whose evidence failed on three of its rows.

    Two failures are archived prefix rows and one is a live row, so the repair
    population spans both provenances the source can produce.
    """
    packets = cohort.packets[:PREFIX_ROWS]
    payloads = [_v5_evidence_payload(p) for p in packets]
    payloads[1] = _bad_quote_payload(packets[1])
    payloads[3] = _bad_quote_payload(packets[3])
    setup = _setup_source(cohort, tmp_path, source_kwargs={"payloads": payloads})
    live_bad = cohort.packets[PREFIX_ROWS + 1]
    run = _run_source(cohort, tmp_path, setup, script=_script(
        cohort.packets, **{live_bad["cik"]: {"text": _bad_quote_payload(live_bad)}}))
    assert run.result.status == "completed", run.result.receipt
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["model_evidence_unverified"] == 3
    return SimpleNamespace(
        run_dir=run.result.run_dir, manifest_path=run.result.manifest_path,
        manifest=manifest, cohort=cohort, unverified=3)


def _selection(source, tmp_path, *, selection_id="repair-selection-fixture"):
    path = tmp_path / "repair" / lr.REPAIR_SELECTION_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    selection = lr.build_repair_selection(
        repo_root=ROOT, source_manifest_path=source.manifest_path,
        output_path=path, selection_id=selection_id, clock=FIXED_CLOCK)
    return SimpleNamespace(path=path, selection=selection,
                           sha256=sha256(path.read_bytes()).hexdigest())


def _grant(cohort, selection, tmp_path, *, source_run_id, breaker=None, mutate=None):
    # the v3 helper only hashes the artifact it is handed; the repair grant's
    # own selection binding is written below from the repair selection.
    governance = _v3_governance(tmp_path / "repair-gov", cohort=cohort,
                                selection_path=selection.path,
                                logical=len(cohort.packets))
    rows = len(selection.selection["rows"])
    payload = {
        "authorization_contract": lr.AUTHORIZATION_CONTRACT,
        "authorization_id": "repair-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": "release_or_research_production",
        "run_kind": lr.RUN_KIND,
        "screen_stage": "universe_high_recall_screen",
        "promotable": False,
        "output_contract": lr.RECORD_CONTRACT,
        "source_run_id": source_run_id,
        "selection_artifact_sha256": selection.sha256,
        "selection_kind": lr.SELECTION_KIND,
        "packet_manifest_sha256": cohort.manifest_sha256,
        "prompt_template_path": REPAIR_PROMPT,
        "prompt_template_sha256":
            sha256((ROOT / REPAIR_PROMPT).read_bytes()).hexdigest(),
        "screen_adapter_enablement_reference":
            governance.authorization["screen_adapter_enablement_reference"],
        "screen_adapter_enablement_sha256":
            governance.authorization["screen_adapter_enablement_sha256"],
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": _contract_digest(),
        "vertex_project": VERTEX_PROJECT, "vertex_location": VERTEX_LOCATION,
        "model_route": {"provider": "google_vertex_ai",
                        "model_label": "gemini-2.5-flash"},
        "endpoint_allowlist": _endpoints(),
        "logical_row_cap": rows,
        "count_attempt_cap": rows * 3, "provider_attempt_cap": rows * 5,
        "budget_max_external_requests": rows * 8,
        "count_attempts_per_row": 3, "generate_attempts_per_row": 5,
        "external_requests_per_row": 8,
        "max_repair_unverified": rows if breaker is None else breaker,
        "budget_max_input_tokens": 10_000_000,
        "budget_max_output_tokens": 100_000_000,
        "budget_max_estimated_cost_micros": 1_000_000_000,
        "budget_max_wall_clock_seconds": 86_400,
        "retry_policy_version": "extraction_provider_retry_policy_v1",
        "rate_limit_policy_version": "extraction_provider_rate_limit_policy_v1",
        "screen_generate_retry_policy_version": gp.SCREEN_GENERATE_RETRY_POLICY_VERSION,
        "screen_count_retry_policy_version": cp.SCREEN_COUNT_RETRY_POLICY_VERSION,
    }
    if mutate is not None:
        mutate(payload)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (governance.root / "screen_repair_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=governance.root,
                           reference="screen_repair_authorization.json",
                           sha256=sha256(raw).hexdigest(), authorization=payload)


def _run(source, selection, grant, tmp_path, *, script=None,
         run_id="repair-run", dry_run=False):
    events: list = []
    factory = _EmptyBodyFactory(
        script if script is not None else _script(source.cohort.packets), events)
    result = lr.run_lineage_screen_repair(
        repo_root=ROOT, packet_manifest_path=source.cohort.manifest_path,
        selection_artifact_path=selection.path,
        source_manifest_path=source.manifest_path,
        governance_root=grant.root, authorization_reference=grant.reference,
        authorization_sha256=grant.sha256,
        output_dir=tmp_path / "repair-out", run_id=run_id,
        clock=FIXED_CLOCK, dry_run=dry_run, client_factory=factory,
        sleep=lambda s: events.append(("wait", s)))
    return SimpleNamespace(result=result, factory=factory, events=events)


def _records(result):
    return [json.loads(x) for x in
            (result.run_dir / lr.REPAIR_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


# --- Stage 1: the selection ---------------------------------------------------------


def test_selection_is_derived_from_the_source_bytes(source, tmp_path):
    built = _selection(source, tmp_path)
    selection = built.selection
    Draft202012Validator(SELECTION_SCHEMA, format_checker=FormatChecker()).validate(
        selection)
    assert selection["selection_contract"] == lr.SELECTION_CONTRACT
    assert selection["derivation_rule"] == "unverified_rows_ascending_ordinal@1"
    assert selection["counts"]["selected_rows"] == source.unverified
    assert len(selection["rows"]) == source.unverified

    rows = [json.loads(x) for x in
            (source.run_dir / lc5.CONTINUATION_V5_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]
    expected = [(i, r) for i, r in enumerate(rows, 1)
                if r["record_kind"] == "model_evidence_unverified"]
    assert [(r["source_row_ordinal"], r["cik"]) for r in selection["rows"]] == \
        [(i, r["cik"]) for i, r in expected]
    ordinals = [r["source_row_ordinal"] for r in selection["rows"]]
    assert ordinals == sorted(ordinals), "strictly ascending source order"
    assert [r["selection_ordinal"] for r in selection["rows"]] == \
        list(range(1, len(selection["rows"]) + 1))
    # it binds the source by digest, all three files
    assert selection["source_manifest_sha256"] == sha256(
        source.manifest_path.read_bytes()).hexdigest()
    _assert_no_google()


def test_selection_applies_no_status_filter(source, tmp_path):
    """The claimed status inside a rejected payload may not select rows."""
    built = _selection(source, tmp_path)
    archive = {}
    for line in (source.run_dir / ls.RAW_RESPONSES_FILENAME).read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            archive[e["raw_response_id"]] = e["raw_response"]
    claimed = set()
    for row in built.selection["rows"]:
        payload = json.loads(archive[row["source_raw_response_id"]])
        claimed.add(payload.get("screen_status"))
    # every unverified row is present whatever it claimed
    assert built.selection["counts"]["selected_rows"] == source.unverified
    assert claimed, "the fixture payloads do claim statuses"
    assert "screen_status" not in json.dumps(SELECTION_SCHEMA["properties"]["rows"])


def test_selection_is_write_once(source, tmp_path):
    built = _selection(source, tmp_path)
    with pytest.raises(ls.ScreenInputError):
        lr.build_repair_selection(
            repo_root=ROOT, source_manifest_path=source.manifest_path,
            output_path=built.path, selection_id="second", clock=FIXED_CLOCK)


@pytest.mark.parametrize("mutate,match", [
    ("receipt", "failure receipt"),
    ("records", "not consumable"),
    ("archive", "not consumable"),
])
def test_a_tampered_or_failed_source_is_refused(source, tmp_path, mutate, match):
    if mutate == "receipt":
        (source.run_dir / ls.FAILURE_RECEIPT_FILENAME).write_text("{}")
    elif mutate == "records":
        path = source.run_dir / lc5.CONTINUATION_V5_RECORDS_FILENAME
        path.write_bytes(path.read_bytes() + b"\n")
    else:
        path = source.run_dir / ls.RAW_RESPONSES_FILENAME
        path.write_bytes(path.read_bytes().replace(b"LIKELY_ELIGIBLE",
                                                   b"LIKELY_INELIGIBLE", 1))
    with pytest.raises(ls.ScreenInputError, match=match):
        lr.build_repair_selection(
            repo_root=ROOT, source_manifest_path=source.manifest_path,
            output_path=tmp_path / "s.json", selection_id="x", clock=FIXED_CLOCK)


def test_a_foreign_source_manifest_is_refused(source, tmp_path):
    foreign = source.run_dir / ls.SCREEN_MANIFEST_FILENAME
    foreign.write_bytes(source.manifest_path.read_bytes())
    with pytest.raises(ls.ScreenInputError, match="different run kind"):
        lr.build_repair_selection(
            repo_root=ROOT, source_manifest_path=foreign,
            output_path=tmp_path / "s.json", selection_id="x", clock=FIXED_CLOCK)


# --- Stage 2: the repair run --------------------------------------------------------


def test_every_selected_row_is_re_asked_and_recorded(source, tmp_path):
    selection = _selection(source, tmp_path)
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"])
    run = _run(source, selection, grant, tmp_path)
    result = run.result
    assert result.status == "completed", result.receipt

    records = _records(result)
    assert len(records) == source.unverified
    assert run.factory.generate_calls == source.unverified
    assert run.factory.count_calls == source.unverified
    # order follows the selection, not the cohort
    assert [(r["cik"], r["accession"]) for r in records] == \
        [(r["cik"], r["accession"]) for r in selection.selection["rows"]]
    validator = Draft202012Validator(RECORD_V6_SCHEMA, format_checker=FormatChecker())
    for record in records:
        validator.validate(record)
        assert record["record_contract"] == "universe_screen_record@0.6.0"
        assert record["row_provenance"]["origin"] == "model_called"
        assert record["repair_provenance"]["source_record_kind"] == \
            "model_evidence_unverified"
        assert record["repair_provenance"]["source_run_id"] == \
            source.manifest["run_id"]

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(MANIFEST_SCHEMA, format_checker=FormatChecker()).validate(
        manifest)
    assert manifest["promotable"] is False
    assert manifest["counts"]["selected_rows"] == source.unverified
    assert manifest["counts"]["repaired_rows"] == source.unverified
    assert manifest["counts"]["still_unverified_rows"] == 0
    assert all(manifest["reconciliation"].values())
    assert len(manifest["reconciliation"]) >= 18
    _assert_no_google()


def test_a_row_that_fails_again_stays_unverified(source, tmp_path):
    selection = _selection(source, tmp_path)
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"])
    doomed = selection.selection["rows"][0]
    packet = next(p for p in source.cohort.packets
                  if p["cik"] == doomed["cik"])
    run = _run(source, selection, grant, tmp_path, script=_script(
        source.cohort.packets,
        **{doomed["cik"]: {"text": _bad_quote_payload(packet)}}))
    assert run.result.status == "completed", run.result.receipt

    records = _records(run.result)
    failed = [r for r in records if r["cik"] == doomed["cik"]]
    assert len(failed) == 1
    assert failed[0]["record_kind"] == "model_evidence_unverified"
    assert failed[0]["failure_reason_code"] == "quote_resolution_failure"
    assert failed[0]["screen_status"] is None and failed[0]["screen_output"] is None
    # it still names the observation it re-asked
    assert failed[0]["repair_provenance"]["source_raw_response_id"] == \
        doomed["source_raw_response_id"]

    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    counts = manifest["counts"]
    assert counts["still_unverified_rows"] == 1
    assert counts["repaired_rows"] == source.unverified - 1
    assert counts["still_unverified_by_reason"] == {"quote_resolution_failure": 1}
    assert sum(counts["by_screen_status"].values()) == counts["repaired_rows"]
    assert all(manifest["reconciliation"].values())


def test_the_repair_tolerance_is_bounded(source, tmp_path):
    """Above the authorized tolerance the run stops fail-closed."""
    selection = _selection(source, tmp_path)
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"], breaker=1)
    doomed = {}
    for row in selection.selection["rows"][:2]:
        packet = next(p for p in source.cohort.packets if p["cik"] == row["cik"])
        doomed[row["cik"]] = {"text": _bad_quote_payload(packet)}
    run = _run(source, selection, grant, tmp_path,
               script=_script(source.cohort.packets, **doomed))
    assert run.result.status == "failed"
    receipt = run.result.receipt
    assert receipt["reason_code"] == "repair_unverified_budget_exhausted"
    assert receipt["max_repair_unverified"] == 1
    assert not (run.result.run_dir / lr.REPAIR_MANIFEST_FILENAME).exists()
    assert not (run.result.run_dir / lr.REPAIR_RECORDS_FILENAME).exists()


def test_no_earlier_output_reaches_the_prompt(source, tmp_path):
    """The model sees the packet. Nothing about the failed attempt."""
    selection = _selection(source, tmp_path)
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"])
    sent: list[str] = []

    original = ld.render_diagnostic_prompt_with_citation_refs

    def _capture(template, packet):
        rendered, refs = original(template, packet)
        sent.append(rendered)
        return rendered, refs

    lr.render_diagnostic_prompt_with_citation_refs = _capture
    try:
        run = _run(source, selection, grant, tmp_path)
    finally:
        lr.render_diagnostic_prompt_with_citation_refs = original
    assert run.result.status == "completed"
    assert len(sent) == source.unverified

    archive = {}
    for line in (source.run_dir / ls.RAW_RESPONSES_FILENAME).read_text(
            encoding="utf-8").splitlines():
        if line.strip():
            e = json.loads(line)
            archive[e["raw_response_id"]] = e["raw_response"]
    for rendered, row in zip(sent, selection.selection["rows"]):
        earlier = archive[row["source_raw_response_id"]]
        payload = json.loads(earlier)
        assert row["source_raw_response_id"] not in rendered
        assert row["source_failure_reason_code"] not in rendered
        assert "text that appears in no passage" not in rendered
        for field in ("positive_evidence", "negative_or_boundary_evidence"):
            for item in payload.get(field) or []:
                if item.get("quote"):
                    assert item["quote"] not in rendered
        assert "repair" not in rendered.lower()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source"]["earlier_output_withheld_from_prompt"] is True


def test_the_repair_prompt_is_bound_and_the_screen_prompt_is_not_used(source,
                                                                      tmp_path):
    selection = _selection(source, tmp_path)
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"])
    run = _run(source, selection, grant, tmp_path)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    repair_sha = sha256((ROOT / REPAIR_PROMPT).read_bytes()).hexdigest()
    screen_sha = sha256((ROOT / SCREEN_PROMPT).read_bytes()).hexdigest()
    assert manifest["prompt_template_path"] == REPAIR_PROMPT
    assert manifest["prompt_template_sha256"] == repair_sha
    assert manifest["screen_prompt_not_used"] == {"path": SCREEN_PROMPT,
                                                  "sha256": screen_sha}
    assert repair_sha != screen_sha


def test_a_grant_binding_the_screen_prompt_is_refused(source, tmp_path):
    selection = _selection(source, tmp_path)
    grant = _grant(
        source.cohort, selection, tmp_path,
        source_run_id=source.manifest["run_id"],
        mutate=lambda p: p.update(
            prompt_template_sha256=sha256(
                (ROOT / SCREEN_PROMPT).read_bytes()).hexdigest()))
    with pytest.raises(ls.ScreenInputError, match="committed repair prompt bytes"):
        _run(source, selection, grant, tmp_path)


def test_a_doctored_selection_is_refused_even_with_a_matching_digest(source,
                                                                    tmp_path):
    """The runner re-derives the rows from the source's own bytes."""
    selection = _selection(source, tmp_path)
    payload = json.loads(selection.path.read_text(encoding="utf-8"))
    payload["rows"] = payload["rows"][:1]
    payload["counts"]["selected_rows"] = 1
    selection.path.write_bytes(
        (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
    doctored = SimpleNamespace(
        path=selection.path, selection=payload,
        sha256=sha256(selection.path.read_bytes()).hexdigest())
    grant = _grant(source.cohort, doctored, tmp_path,
                   source_run_id=source.manifest["run_id"])
    with pytest.raises(ls.ScreenInputError, match="re-derived from the source"):
        _run(source, doctored, grant, tmp_path)


def test_the_source_run_is_never_modified(source, tmp_path):
    selection = _selection(source, tmp_path)
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"])
    before = {str(p.relative_to(source.run_dir)): sha256(p.read_bytes()).hexdigest()
              for p in sorted(source.run_dir.rglob("*")) if p.is_file()}
    run = _run(source, selection, grant, tmp_path)
    assert run.result.status == "completed"
    after = {str(p.relative_to(source.run_dir)): sha256(p.read_bytes()).hexdigest()
             for p in sorted(source.run_dir.rglob("*")) if p.is_file()}
    assert before == after
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["source"]["source_unmodified"] is True


def test_the_repair_run_is_structurally_non_promotable(source, tmp_path):
    selection = _selection(source, tmp_path)
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"])
    run = _run(source, selection, grant, tmp_path)
    run_dir = run.result.run_dir
    for loader in (ls.require_authoritative_screen_run,
                   ll.require_promotable_screen_run,
                   ld.require_diagnostic_run,
                   ldr.require_diagnostic_repair_run,
                   lc5.require_continuation_v5_run):
        with pytest.raises(ls.ScreenInputError):
            loader(run_dir)
    # its own loader accepts it
    assert lr.require_repair_run(run_dir).name == lr.REPAIR_MANIFEST_FILENAME


def test_a_promotable_grant_or_manifest_is_refused(source, tmp_path):
    selection = _selection(source, tmp_path)
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"],
                   mutate=lambda p: p.update(promotable=True))
    with pytest.raises(ls.ScreenInputError):
        _run(source, selection, grant, tmp_path)


def test_caps_are_derived_from_the_selection(source, tmp_path):
    selection = _selection(source, tmp_path)
    rows = len(selection.selection["rows"])
    for field, wrong in (("count_attempt_cap", rows * 3 + 1),
                         ("provider_attempt_cap", rows * 5 + 1),
                         ("budget_max_external_requests", rows * 8 + 1),
                         ("logical_row_cap", rows + 1)):
        grant = _grant(source.cohort, selection, tmp_path,
                       source_run_id=source.manifest["run_id"],
                       mutate=lambda p, f=field, w=wrong: p.update({f: w}))
        with pytest.raises(ls.ScreenInputError):
            _run(source, selection, grant, tmp_path)


def test_an_unbounded_tolerance_is_refused(source, tmp_path):
    selection = _selection(source, tmp_path)
    rows = len(selection.selection["rows"])
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"],
                   mutate=lambda p: p.update(max_repair_unverified=rows + 1))
    with pytest.raises(ls.ScreenInputError, match="max_repair_unverified"):
        _run(source, selection, grant, tmp_path)


def test_dry_run_and_write_once(source, tmp_path):
    selection = _selection(source, tmp_path)
    grant = _grant(source.cohort, selection, tmp_path,
                   source_run_id=source.manifest["run_id"])
    dry = _run(source, selection, grant, tmp_path, dry_run=True)
    assert dry.result.status == "dry_run" and dry.result.run_dir is None
    assert dry.factory.opens == 0
    first = _run(source, selection, grant, tmp_path)
    assert first.result.status == "completed"
    with pytest.raises(FileExistsError):
        _run(source, selection, grant, tmp_path)


def test_a_foreign_grant_is_refused(source, tmp_path):
    """The continuation grant and the repair grant are mutually exclusive."""
    selection = _selection(source, tmp_path)
    grant = _grant(
        source.cohort, selection, tmp_path,
        source_run_id=source.manifest["run_id"],
        mutate=lambda p: p.update(
            authorization_contract="universe_screen_continuation_authorization@0.5.0"))
    with pytest.raises(ls.ScreenInputError):
        _run(source, selection, grant, tmp_path)


# --- the CLI boundary -------------------------------------------------------------


def _cli_module():
    """Import the pipeline CLI once, by path, without executing main()."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adr123_cli", ROOT / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repair_argv(tmp_path):
    return [
        "--mode", "screen-universe-unverified-repair",
        "--packet-manifest", str(tmp_path / "packets.json"),
        "--selection-artifact", str(tmp_path / "selection.json"),
        "--source-screen-manifest", str(tmp_path / "source.json"),
        "--governance-root", str(tmp_path / "gov"),
        "--screen-authorization", "screen_repair_authorization.json",
        "--screen-authorization-sha256", "0" * 64,
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-gating-fixture",
    ]


def test_the_repair_mode_accepts_its_five_screen_flags(tmp_path):
    """ADR-123 bugfix: the mode was unreachable with the flags it requires.

    The allow-lists governing --packet-manifest and the four
    selection/governance flags did not name this mode, so every invocation was
    rejected before preflight. Nothing downstream runs here: only the argument
    gate is exercised.
    """
    cli = _cli_module()
    args = cli.build_parser().parse_args(_repair_argv(tmp_path))
    assert cli._reject_cross_mode_flags(args) is None
    _assert_no_google()


@pytest.mark.parametrize("flag", [
    "--packet-manifest", "--selection-artifact", "--governance-root",
    "--screen-authorization", "--screen-authorization-sha256",
])
def test_each_required_repair_flag_is_individually_accepted(tmp_path, flag):
    """Each of the five is separately proven, so one allow-list cannot regress."""
    cli = _cli_module()
    argv = _repair_argv(tmp_path)
    args = cli.build_parser().parse_args(argv)
    verdict = cli._reject_cross_mode_flags(args)
    assert verdict is None, verdict
    assert flag not in (verdict or "")


def test_the_repair_mode_still_requires_all_five(tmp_path):
    """Accepting the flags must not make them optional."""
    cli = _cli_module()
    argv = _repair_argv(tmp_path)
    index = argv.index("--governance-root")
    del argv[index:index + 2]
    args = cli.build_parser().parse_args(argv)
    verdict = cli._reject_cross_mode_flags(args)
    assert verdict is not None and "--governance-root" in verdict


def test_the_selection_mode_still_rejects_the_packet_manifest(tmp_path):
    """The builder derives from the source run; it consumes no packet cohort."""
    cli = _cli_module()
    args = cli.build_parser().parse_args([
        "--mode", "select-screen-unverified-repair-rows",
        "--source-screen-manifest", str(tmp_path / "source.json"),
        "--packet-manifest", str(tmp_path / "packets.json"),
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-gating-fixture",
    ])
    verdict = cli._reject_cross_mode_flags(args)
    assert verdict is not None and "--packet-manifest" in verdict


def test_the_repair_cli_reaches_the_runner_without_touching_the_provider(
        tmp_path, monkeypatch):
    """The CLI hands off to the runner and nothing else happens.

    The runner is replaced at the CLI's own seam, so no preflight, no write, no
    SDK import and no Vertex call can occur; what is proven is that the
    arguments now arrive at the boundary they were being rejected before.
    """
    cli = _cli_module()
    for name in ("packets.json", "selection.json", "source.json"):
        (tmp_path / name).write_text("{}")
    (tmp_path / "gov").mkdir()
    seen = {}

    def _stub(**kwargs):
        seen.update(kwargs)
        return SimpleNamespace(
            run_id=kwargs["run_id"], dry_run=False, status="completed",
            run_dir=None, counts={}, request_accounting={}, reconciliation={},
            manifest_path=None, failure_receipt_path=None, receipt=None)

    monkeypatch.setattr(cli, "run_lineage_screen_repair", _stub)
    assert cli.main(_repair_argv(tmp_path)) == 0
    assert seen["run_id"] == "cli-gating-fixture"
    assert seen["authorization_reference"] == "screen_repair_authorization.json"
    assert seen["authorization_sha256"] == "0" * 64
    assert seen["dry_run"] is False
    assert Path(seen["governance_root"]).name == "gov"
    _assert_no_google()


def test_predecessors_are_byte_identical():
    """ADR-123 adds beside; it moves nothing that already shipped."""
    pins = {
        SCREEN_PROMPT:
            "fee42d939f9eab590fdcbf055e7b2039e8a33a410dfc12257a47291d7a77d558",
        "src/dynamic_ai_products/lineage_screen_live.py":
            "795dddb081629ddba184f52070011f1c42a61a669698f3643694a7cceb73c2c2",
        "src/dynamic_ai_products/providers/retry_policy.py":
            "cb6de1d8c221afe0c90337f165ab74265b303b8eaf2f7a6f1b7bdc43f28dbca8",
        "src/dynamic_ai_products/providers/screen_retry_policy.py":
            "178286d67e80f0d9548e740a2b7f9f846cad2a636a97cb96bab72732db7b9d65",
        "src/dynamic_ai_products/providers/screen_count_retry_policy.py":
            "3a170abe267543b1094cea0cce1b83c490e3f624ec62385b6ef586b392d768f8",
    }
    for path, expected in pins.items():
        actual = sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual == expected, f"{path} moved: {actual}"


def test_the_registry_registers_the_repair_contracts():
    registry = json.loads(
        (ROOT / "schemas/schema_version_manifest.json").read_text(encoding="utf-8"))
    assert registry["manifest_version"] == "0.84.0"
    assert len(registry["schemas"]) == 231
    for key, version in (("universe_screen_record_v6", "0.6.0"),
                         ("universe_screen_repair_selection", "0.1.0"),
                         ("universe_screen_repair_authorization", "0.1.0"),
                         ("universe_screen_repair_manifest", "0.1.0")):
        assert registry["schemas"][key] == version


def test_the_validator_is_the_committed_one():
    """A repair row is held to the same strict validator as a screen row."""
    assert lr._validate_row_output is ls._validate_row_output
    assert lr.render_diagnostic_prompt_with_citation_refs is \
        ld.render_diagnostic_prompt_with_citation_refs
    assert lr.resolve_diagnostic_citation_refs is ld.resolve_diagnostic_citation_refs
