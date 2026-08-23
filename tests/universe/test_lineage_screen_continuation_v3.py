"""ADR-120 tests: an empty count body is survivable, and its stop is reusable.

Everything is offline. The transport is a fake that can return an empty body
from either operation on demand, every wait is a recorded call rather than a
sleep, and no test builds a ``genai.Client``, resolves a credential, or opens a
socket. ADR-119's generate behaviour is exercised here too, unchanged.
"""

from __future__ import annotations

import json
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import lineage_screen_continuation_v2 as lc2
from dynamic_ai_products import lineage_screen_continuation_v3 as lc3
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products.providers import screen_count_retry_policy as cp
from dynamic_ai_products.providers import screen_retry_policy as gp
from dynamic_ai_products.providers.client_contract_v2 import CLIENT_CONTRACT_V2_ID
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.vertex_gemini_screen_v5 import (
    EmptyGenerateBody,
    VertexGeminiScreenV5,
    execute_with_empty_body_retry,
)
from dynamic_ai_products.providers.vertex_gemini_screen_v6 import (
    EMPTY_COUNT_BODY_REASON,
    EmptyCountBody,
    VertexGeminiScreenV6,
    execute_with_empty_count_retry,
    is_count_retryable_v6,
)
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_screen_continuation import (  # noqa: E402
    _EventCapture,
    _Fake429,
    _script,
)
from test_lineage_screen_diagnostic import _v5_evidence_payload  # noqa: E402
from test_lineage_screen_live import (  # noqa: E402
    PACKET_FIXTURES,
    ROOT,
    VERTEX_LOCATION,
    VERTEX_PROJECT,
    _contract_digest,
    _endpoints,
    _envelope,
    _fixture_doc,
    _selection,
    _v5_run,
)
from test_lineage_screen_live_v3 import (  # noqa: E402
    _CIK_IN_PROMPT,
    _governance as _v3_governance,
)

CLI = ROOT / "pipelines" / "00_build_company_universe.py"
FIXED_CLOCK = lambda: datetime(2026, 8, 22, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731
PREFIX_ROWS = 4

MANIFEST_V2_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_continuation_manifest.v3.schema.json")
    .read_text(encoding="utf-8"))
MANIFEST_V1_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_continuation_manifest.v2.schema.json")
    .read_text(encoding="utf-8"))
AUTH_V2_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_continuation_authorization.v3.schema.json")
    .read_text(encoding="utf-8"))
AUTH_V1_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_continuation_authorization.v2.schema.json")
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
    assert not added, f"the v2 continuation path imported google: {sorted(added)}"


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    """6 valid packets + 1 packet failure: prefix 4, suffix 2."""
    source, template = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    docs = []
    for index in range(6):
        cik = f"{7200000000 + index:010d}"
        docs.append((source, dict(template, cik=cik, accession=f"{cik}-22-000001")))
    docs.append(_fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"))
    built = _v5_run(tmp_path_factory.mktemp("cont2-cohort"), [docs])
    assert len(built.packets) == 6 and len(built.failures) == 1
    return built


# --- fake transport that can return nothing ----------------------------------------


class _EmptyBodyModels:
    def __init__(self, capture, script, events):
        self._capture, self._script, self._events = capture, script, events
        self.count_calls = self.generate_calls = 0

    def _entry(self, contents):
        match = _CIK_IN_PROMPT.search(contents)
        assert match
        return self._script[match.group(1)]

    def count_tokens(self, *, model, contents, config):
        self.count_calls += 1
        entry = self._entry(contents)
        if entry.get("empty_counts", 0) > 0:
            entry["empty_counts"] -= 1
            # HTTP-successful, and carrying nothing at all.
            self._capture.record_send("count_tokens", b"", "ok")
            return SimpleNamespace()
        if entry.get("count_timeouts", 0) > 0:
            entry["count_timeouts"] -= 1
            self._capture.record_send("count_tokens", None,
                                      "no_response_transport_failure")
            raise TimeoutError("scripted count timeout")
        tokens = entry.get("count_tokens", 120)
        self._capture.record_send(
            "count_tokens", json.dumps({"totalTokens": tokens}).encode(), "ok")
        return SimpleNamespace(total_tokens=tokens)

    def generate_content(self, *, model, contents, config):
        self.generate_calls += 1
        entry = self._entry(contents)
        if entry.get("empty_bodies", 0) > 0:
            entry["empty_bodies"] -= 1
            # HTTP-successful, and carrying nothing at all.
            self._capture.record_send("generate_content", b"", "ok")
            return SimpleNamespace()
        if entry.get("quota_failures", 0) > 0:
            entry["quota_failures"] -= 1
            self._capture.record_send("generate_content", None,
                                      "no_response_transport_failure")
            raise _Fake429("scripted 429")
        if entry.get("malformed", 0) > 0:
            entry["malformed"] -= 1
            self._capture.record_send("generate_content", b"this is not json", "ok")
            return SimpleNamespace()
        if entry.get("blocked", 0) > 0:
            entry["blocked"] -= 1
            body = json.dumps({"promptFeedback": {"blockReason": "SAFETY"},
                               "candidates": []}).encode()
            self._capture.record_send("generate_content", body, "ok")
            return SimpleNamespace()
        envelope = _envelope(entry["text"], prompt_tokens=entry.get("count_tokens", 120))
        self._capture.record_send("generate_content",
                                  json.dumps(envelope).encode(), "ok")
        return SimpleNamespace()


class _EmptyBodyFactory:
    def __init__(self, script, events):
        self.script, self.events = script, events
        self.opens = self.count_calls = self.generate_calls = 0

    def __call__(self, *, vertex_project, vertex_location, endpoint_allowlist,
                 http_options_kwargs, operation_endpoints=None):
        @contextmanager
        def _open():
            self.opens += 1
            capture = _EventCapture(self.events)
            models = _EmptyBodyModels(capture, self.script, self.events)
            try:
                yield SimpleNamespace(models=models), capture
            finally:
                self.count_calls += models.count_calls
                self.generate_calls += models.generate_calls
        return _open()


# --- a synthetic failed continuation source ----------------------------------------


def _archive_line(run_id, packet, payload):
    return json.dumps({
        "raw_response_id": f"{run_id}-{packet['cik']}-{packet['accession']}",
        "cik": packet["cik"], "accession": packet["accession"],
        "raw_response": payload,
        "raw_response_sha256": sha256(payload.encode()).hexdigest(),
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _failed_continuation(tmp_path: Path, cohort, *, prefix_rows=PREFIX_ROWS,
                         run_id="source-continuation", authorization_sha256: str,
                         payloads=None, mutate_receipt=None, mutate_entries=None,
                         stopping_captures=None,
                         reason_code="provider_error",
                         detail="Governed provider failure (provider_response_unusable)."):
    """A run that stopped when countTokens returned with no usable body.

    Its stopping row persists nothing at all: the measurement returned
    nothing, so the generation was never attempted and no capture directory
    was ever created for it.
    """
    directory = tmp_path / "failed" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    packets = cohort.packets[:prefix_rows]
    if payloads is None:
        payloads = [_v5_evidence_payload(p) for p in packets]
    entries = [_archive_line(run_id, p, x) for p, x in zip(packets, payloads)]
    if mutate_entries is not None:
        entries = mutate_entries(entries)
    archive = ("\n".join(entries) + "\n").encode() if entries else b""
    (directory / ls.RAW_RESPONSES_FILENAME).write_bytes(archive)
    stopping = cohort.packets[prefix_rows]
    receipt = {
        "receipt_contract": "universe_screen_failure_receipt@0.1.0",
        "run_id": run_id, "run_kind": "full_cohort_continuation",
        "reason_code": reason_code, "detail": detail,
        "stopping_cik": stopping["cik"], "stopping_accession": stopping["accession"],
        "stopping_row_index": prefix_rows + 1,
        "records_completed_before_failure": prefix_rows,
        "reused_prefix_rows": 0, "model_called_rows_attempted": prefix_rows + 1,
        # one count per attempted row; one generate per COMPLETED row only,
        # because the stopping row never reached the generation
        "count_attempts_made": prefix_rows + 1,
        "provider_attempts_made": prefix_rows,
        "external_requests_made": (prefix_rows + 1) + prefix_rows,
        "empty_generate_body_attempts": 0,
        "empty_count_body_attempts": 1,
        "authorization_sha256": authorization_sha256,
        "source_run_id": "grandparent-run",
        "source_receipt_sha256": "0" * 64,
        "run_timestamp": "2026-08-22T05:00:00+00:00",
        "retention_note": "Non-authoritative failed continuation run.",
    }
    if mutate_receipt is not None:
        mutate_receipt(receipt)
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    (directory / ls.FAILURE_RECEIPT_FILENAME).write_bytes(receipt_bytes)
    # Optional tamper: a stopping-row capture that should not exist.
    if stopping_captures:
        cap = (directory / ll.CAPTURES_DIRNAME
               / f"{receipt['stopping_row_index']:05d}-{receipt['stopping_cik']}"
                 f"-{receipt['stopping_accession']}")
        cap.mkdir(parents=True, exist_ok=True)
        for name, body in stopping_captures.items():
            (cap / name).write_bytes(body)
    return SimpleNamespace(dir=directory, run_id=run_id, receipt=receipt,
                           receipt_sha256=sha256(receipt_bytes).hexdigest(),
                           archive_sha256=sha256(archive).hexdigest(),
                           archive_bytes=archive, prefix_rows=prefix_rows)


def _grant(governance, *, cohort, source, reused, selection_path, breaker=4,
           mutate=None):
    called = len(cohort.packets) - reused
    prompt_sha = sha256(
        (ROOT / "prompts/discovery/universe_high_recall_screen.v5.md").read_bytes()
    ).hexdigest()
    payload = {
        "authorization_contract": "universe_screen_continuation_authorization@0.3.0",
        "authorization_id": "continuation-v2-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": "release_or_research_production",
        "run_kind": "full_cohort_continuation",
        "screen_stage": "universe_high_recall_screen",
        "source_kind": "failed_continuation_empty_count_body",
        "source_run_id": source.run_id, "source_run_path": str(source.dir),
        "source_receipt_sha256": source.receipt_sha256,
        "source_raw_responses_sha256": source.archive_sha256,
        "source_authorization_reference": governance.reference,
        "source_authorization_sha256": governance.sha256,
        "packet_manifest_sha256": cohort.manifest_sha256,
        "prompt_template_sha256": prompt_sha,
        "selection_artifact_sha256": sha256(selection_path.read_bytes()).hexdigest(),
        "selection_kind": "full_cohort",
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
        "logical_row_cap": len(cohort.packets),
        "reused_prefix_row_cap": reused, "model_called_row_cap": called,
        "count_attempt_cap": called * 3, "provider_attempt_cap": called * 5,
        "budget_max_external_requests": called * 8,
        "count_attempts_per_row": 3, "generate_attempts_per_row": 5,
        "external_requests_per_row": 8,
        "max_empty_generate_body_retries_per_row": 5,
        "max_empty_count_body_retries_per_row": 3,
        "budget_max_input_tokens": 10_000_000,
        "budget_max_output_tokens": 100_000_000,
        "budget_max_estimated_cost_micros": 1_000_000_000,
        "budget_max_wall_clock_seconds": 86_400,
        "retry_policy_version": "extraction_provider_retry_policy_v1",
        "rate_limit_policy_version": "extraction_provider_rate_limit_policy_v1",
        "screen_generate_retry_policy_version": gp.SCREEN_GENERATE_RETRY_POLICY_VERSION,
        "screen_count_retry_policy_version": cp.SCREEN_COUNT_RETRY_POLICY_VERSION,
        "max_model_evidence_unverified": breaker,
    }
    if mutate is not None:
        mutate(payload)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (governance.root / "screen_continuation_v3_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=governance.root,
                           reference="screen_continuation_v3_authorization.json",
                           sha256=sha256(raw).hexdigest(), authorization=payload)


def _setup(cohort, tmp_path, *, prefix_rows=PREFIX_ROWS, breaker=4,
           source_kwargs=None, grant_mutate=None):
    selection_path = _selection(cohort, tmp_path, "full_cohort")
    governance = _v3_governance(tmp_path, cohort=cohort,
                                selection_path=selection_path,
                                logical=len(cohort.packets))
    source = _failed_continuation(tmp_path, cohort, prefix_rows=prefix_rows,
                                  authorization_sha256=governance.sha256,
                                  **(source_kwargs or {}))
    grant = _grant(governance, cohort=cohort, source=source, reused=prefix_rows,
                   selection_path=selection_path, breaker=breaker,
                   mutate=grant_mutate)
    return SimpleNamespace(selection=selection_path, governance=governance,
                           source=source, grant=grant)


def _run(cohort, tmp_path, setup, *, script=None, run_id="cont2", dry_run=False):
    waits: list[float] = []
    events: list = []

    def record_wait(seconds):
        waits.append(seconds)
        events.append(("wait", seconds))

    factory = _EmptyBodyFactory(
        script if script is not None else _script(cohort.packets), events)
    result = lc3.run_lineage_screen_continuation_v3(
        repo_root=ROOT, packet_manifest_path=cohort.manifest_path,
        selection_artifact_path=setup.selection,
        governance_root=setup.grant.root,
        authorization_reference=setup.grant.reference,
        authorization_sha256=setup.grant.sha256,
        source_run_dir=setup.source.dir,
        source_receipt_sha256=setup.source.receipt_sha256,
        output_dir=tmp_path / "screen", run_id=run_id, clock=FIXED_CLOCK,
        dry_run=dry_run, client_factory=factory, sleep=record_wait)
    _assert_no_google()
    return SimpleNamespace(result=result, factory=factory, waits=waits, events=events)


def _records(result):
    return [json.loads(x) for x in
            (result.run_dir / lc3.CONTINUATION_V3_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


def _ledger(result):
    return [json.loads(x) for x in
            (result.run_dir / ll.CAPTURE_LEDGER_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


# --- 1. one empty body, then a valid one -------------------------------------------


def test_one_empty_count_then_valid_count_then_generate(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    flaky = cohort.packets[PREFIX_ROWS]["cik"]
    run = _run(cohort, tmp_path, setup,
               script=_script(cohort.packets, **{flaky: {"empty_counts": 1}}))
    result = run.result
    assert result.status == "completed", result.receipt

    assert run.waits == [15.0]                  # the unchanged count schedule
    assert run.factory.count_calls == 2 + 1     # flaky row measured twice
    assert run.factory.generate_calls == 2      # each row generated once

    # The flaky row's stream in full: the empty measurement is followed by a
    # wait and a second measurement, and the generation happens only once the
    # input has actually been measured.
    expected = [("send", "count_tokens"), ("capture", "count_tokens"),
                ("wait", 15.0),
                ("send", "count_tokens"), ("capture", "count_tokens"),
                ("send", "generate_content"), ("capture", "generate_content")]
    assert run.events[:len(expected)] == expected

    ledger = _ledger(result)
    empties = [e for e in ledger
               if e.get("provider_reason_code") == EMPTY_COUNT_BODY_REASON]
    assert len(empties) == 1
    assert empties[0]["capture_disposition"] == "empty_entity_body_not_persisted"
    assert empties[0]["raw_reference"] is None and empties[0]["raw_sha256"] is None
    assert empties[0]["operation_label"] == "count_tokens"

    records = _records(result)
    row = [r for r in records if r["cik"] == flaky]
    assert len(row) == 1 and row[0]["record_kind"] == "screened_packet"
    archive = [json.loads(x) for x in
               (result.run_dir / ls.RAW_RESPONSES_FILENAME)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert sum(1 for e in archive if e["cik"] == flaky) == 1

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(MANIFEST_V2_SCHEMA, format_checker=FormatChecker()).validate(manifest)
    assert manifest["empty_count_body_telemetry"] == {
        "empty_body_attempts": 1, "rows_with_empty_body": 1,
        "rows_recovered_after_empty_body": 1, "max_retries_per_row": 3}
    assert manifest["empty_generate_body_telemetry"]["empty_body_attempts"] == 0
    assert manifest["inherited_source_limitations"]
    assert all(manifest["reconciliation"].values())


def test_three_empty_counts_stop_fail_closed_with_no_generate(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    stuck = cohort.packets[PREFIX_ROWS]["cik"]
    run = _run(cohort, tmp_path, setup,
               script=_script(cohort.packets, **{stuck: {"empty_counts": 99}}))
    result = run.result
    assert result.status == "failed"
    assert run.factory.count_calls == 3
    assert run.factory.generate_calls == 0, "the generation is never invoked"
    assert run.waits == [15.0, 30.0]

    receipt = result.receipt
    assert receipt["reason_code"] == lc3.EMPTY_COUNT_TERMINAL_REASON
    assert "never invoked" in receipt["detail"]
    assert receipt["empty_count_body_attempts"] == 3
    assert receipt["empty_generate_body_attempts"] == 0
    assert receipt["stopping_cik"] == stuck

    archive = (result.run_dir / ls.RAW_RESPONSES_FILENAME).read_text(encoding="utf-8")
    assert stuck not in archive
    assert not (result.run_dir / lc3.CONTINUATION_V3_MANIFEST_FILENAME).exists()
    assert not (result.run_dir / lc3.CONTINUATION_V3_RECORDS_FILENAME).exists()
    assert not (result.run_dir / ll.CAPTURE_LEDGER_FILENAME).exists()
    with pytest.raises(ls.ScreenInputError):
        lc3.require_continuation_v3_run(result.run_dir)


def test_the_empty_count_ceiling_is_the_unchanged_count_schedule():
    waits, calls = [], {"n": 0}

    def always_empty():
        calls["n"] += 1
        raise EmptyCountBody()

    with pytest.raises(ProviderError) as excinfo:
        execute_with_empty_count_retry(always_empty, sleep=waits.append,
                                       max_attempts=99)
    assert excinfo.value.reason_code == "provider_response_unusable"
    assert calls["n"] == cp.SCREEN_COUNT_MAX_ATTEMPTS_V2 == 3
    assert waits == list(map(float, cp.SCREEN_COUNT_RETRY_DELAYS_SECONDS))


def test_adr119_generate_empty_body_behaviour_is_preserved(cohort, tmp_path):
    """The inherited half still works, unchanged."""
    setup = _setup(cohort, tmp_path)
    flaky = cohort.packets[PREFIX_ROWS]["cik"]
    run = _run(cohort, tmp_path, setup,
               script=_script(cohort.packets, **{flaky: {"empty_bodies": 1}}))
    assert run.result.status == "completed", run.result.receipt
    assert run.waits == [15.0]
    assert run.factory.generate_calls == 3 and run.factory.count_calls == 2
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["empty_generate_body_telemetry"]["empty_body_attempts"] == 1
    assert manifest["empty_count_body_telemetry"]["empty_body_attempts"] == 0
    assert VertexGeminiScreenV6.complete_v8 is VertexGeminiScreenV5.complete_v8

    waits, calls = [], {"n": 0}

    def always_empty():
        calls["n"] += 1
        raise EmptyGenerateBody()

    with pytest.raises(ProviderError):
        execute_with_empty_body_retry(always_empty, sleep=waits.append)
    assert calls["n"] == 5 and waits == [15.0, 30.0, 60.0, 120.0]


def test_an_empty_count_never_invokes_generate_on_that_attempt(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    flaky = cohort.packets[PREFIX_ROWS]["cik"]
    run = _run(cohort, tmp_path, setup,
               script=_script(cohort.packets, **{flaky: {"empty_counts": 2}}))
    assert run.result.status == "completed"
    ledger = _ledger(run.result)
    row = [e for e in ledger if e["row_ordinal"] == PREFIX_ROWS + 1]
    assert [e["operation_label"] for e in row] == (
        ["count_tokens"] * 3 + ["generate_content"])
    assert [e["attempt_ordinal"] for e in row] == [1, 2, 3, 1]
    assert run.waits == [15.0, 30.0]


@pytest.mark.parametrize("flavour", ["malformed", "blocked"])
def test_a_content_failure_is_still_terminal_on_its_first_attempt(
        cohort, tmp_path, flavour):
    setup = _setup(cohort, tmp_path / flavour)
    bad = cohort.packets[PREFIX_ROWS]["cik"]
    run = _run(cohort, tmp_path / flavour, setup,
               script=_script(cohort.packets, **{bad: {flavour: 9}}))
    assert run.result.status == "failed"
    assert run.factory.generate_calls == 1, "a returned answer is never retried"
    assert run.waits == []
    assert run.result.receipt["reason_code"] == "provider_error"


def test_the_count_retry_predicate_adds_only_the_empty_count(cohort, tmp_path):
    class Whatever(Exception):
        pass

    from dynamic_ai_products.extraction.provider_adapter import CaptureSinkError
    assert is_count_retryable_v6(EmptyCountBody()) is True
    assert is_count_retryable_v6(Whatever()) is False
    assert is_count_retryable_v6(_Fake429()) is True      # inherited, unchanged
    assert is_count_retryable_v6(CaptureSinkError(
        operation_label="count_tokens", attempt_ordinal=1,
        persistence_reason_code="write_error", provider_reason_code=None)) is False
    assert is_count_retryable_v6(ls.ScreenInputError("governance")) is False
    # an empty generate body is not a count-retry reason
    assert is_count_retryable_v6(EmptyGenerateBody()) is False


def test_a_quote_failure_is_recorded_not_retried(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    bad = cohort.packets[PREFIX_ROWS]["cik"]
    payload = _v5_evidence_payload(cohort.packets[PREFIX_ROWS],
                                   quote="text that appears in no passage")
    run = _run(cohort, tmp_path, setup,
               script=_script(cohort.packets, **{bad: {"text": payload}}))
    assert run.result.status == "completed"
    assert run.factory.generate_calls == 2 and run.waits == []
    unverified = [r for r in _records(run.result)
                  if r["record_kind"] == "model_evidence_unverified"]
    assert len(unverified) == 1
    assert unverified[0]["failure_reason_code"] == "quote_resolution_failure"


# --- 4. safe-source acceptance ------------------------------------------------------


def test_the_empty_body_source_shape_is_accepted(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    prefix = lc3.load_continuation_source_v3(
        setup.source.dir, source_receipt_sha256=setup.source.receipt_sha256)
    assert len(prefix.entries) == PREFIX_ROWS
    assert prefix.archive_sha256 == setup.source.archive_sha256
    assert prefix.receipt["reason_code"] == "provider_error"


def test_the_real_empty_count_source_is_accepted_when_present():
    """The live 4,821-row empty-count source, read only, skipped when absent."""
    directory = (ROOT / "data/runs/universe-screens"
                 / "universe-high-recall-continuation-v2-20260822")
    if not directory.is_dir():
        pytest.skip("the live empty-count source is not present in this checkout")
    receipt_sha = sha256(
        (directory / ls.FAILURE_RECEIPT_FILENAME).read_bytes()).hexdigest()
    prefix = lc3.load_continuation_source_v3(
        directory, source_receipt_sha256=receipt_sha)
    assert len(prefix.entries) == prefix.receipt["records_completed_before_failure"]
    assert prefix.receipt["stopping_row_index"] == len(prefix.entries) + 1
    assert prefix.receipt["empty_generate_body_attempts"] == 0
    # the stopping row persisted nothing, which is what identifies the shape
    cap = (directory / ll.CAPTURES_DIRNAME
           / f"{prefix.receipt['stopping_row_index']:05d}"
             f"-{prefix.receipt['stopping_cik']}"
             f"-{prefix.receipt['stopping_accession']}")
    assert not cap.exists()

    # and the ADR-119 loader still refuses it, which is why this ADR exists:
    # it requires a non-empty countTokens capture for the stopping row.
    with pytest.raises(ls.ScreenInputError) as refusal:
        lc2.load_continuation_source_v2(directory, source_receipt_sha256=receipt_sha)
    assert "countTokens capture" in str(refusal.value)


def _refuses(cohort, tmp_path, match, **setup_kwargs):
    setup = _setup(cohort, tmp_path, **setup_kwargs)
    output_dir = tmp_path / "screen"
    events: list = []
    factory = _EmptyBodyFactory(_script(cohort.packets), events)
    with pytest.raises(ls.ScreenInputError, match=match):
        lc3.run_lineage_screen_continuation_v3(
            repo_root=ROOT, packet_manifest_path=cohort.manifest_path,
            selection_artifact_path=setup.selection,
            governance_root=setup.grant.root,
            authorization_reference=setup.grant.reference,
            authorization_sha256=setup.grant.sha256,
            source_run_dir=setup.source.dir,
            source_receipt_sha256=setup.source.receipt_sha256,
            output_dir=output_dir, run_id="refused", clock=FIXED_CLOCK,
            client_factory=factory,
            sleep=lambda s: pytest.fail("a refused run must never wait"))
    assert not output_dir.exists() or not any(output_dir.iterdir())
    assert factory.opens == 0 and not events
    _assert_no_google()


def test_archive_gap_reorder_and_hash_drift_are_refused(cohort, tmp_path):
    # counters kept internally consistent, so the ORDER check is what fires
    _refuses(cohort, tmp_path / "gap", "maps onto the selection in order",
             source_kwargs={"mutate_entries": lambda e: e[:2] + e[3:],
                            "mutate_receipt": lambda r: r.update(
                                records_completed_before_failure=3,
                                stopping_row_index=4,
                                model_called_rows_attempted=4,
                                count_attempts_made=4, provider_attempts_made=3,
                                external_requests_made=7)})
    _refuses(cohort, tmp_path / "order", "maps onto the selection in order",
             source_kwargs={"mutate_entries": lambda e: [e[1], e[0]] + e[2:]})

    def drift(entries):
        row = json.loads(entries[1])
        row["raw_response"] = row["raw_response"].replace("LIKELY", "UNLIKELY")
        return entries[:1] + [json.dumps(row, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":"))] + entries[2:]
    _refuses(cohort, tmp_path / "drift", "no longer matches its recorded digest",
             source_kwargs={"mutate_entries": drift})


def test_receipt_counter_drift_is_refused(cohort, tmp_path):
    _refuses(cohort, tmp_path / "rows", "does not agree with its own receipt",
             source_kwargs={"mutate_receipt": lambda r: r.update(
                 records_completed_before_failure=r["records_completed_before_failure"] + 1)})
    _refuses(cohort, tmp_path / "ext", "not its count plus",
             source_kwargs={"mutate_receipt": lambda r: r.update(
                 external_requests_made=r["external_requests_made"] + 5)})
    _refuses(cohort, tmp_path / "attempted", "accounting does not close",
             source_kwargs={"mutate_receipt": lambda r: r.update(
                 model_called_rows_attempted=r["model_called_rows_attempted"] + 3)})


def test_any_stopping_row_capture_is_refused(cohort, tmp_path):
    """An empty-count stop persists nothing for its stopping row."""
    _refuses(cohort, tmp_path / "count", "persisted 1 capture file",
             source_kwargs={"stopping_captures": {"count-attempt-01.bin": b'{"totalTokens": 9}'}})
    _refuses(cohort, tmp_path / "gen", "persisted 1 capture file",
             source_kwargs={"stopping_captures": {"generate-attempt-01.bin": b'{"candidates": []}'}})


def test_stopping_row_counter_shape_is_refused_when_wrong(cohort, tmp_path):
    # a generate attempt for the stopping row means it failed elsewhere
    _refuses(cohort, tmp_path / "genattempt", "never reaches the generation",
             source_kwargs={"mutate_receipt": lambda r: r.update(
                 provider_attempts_made=r["provider_attempts_made"] + 1,
                 external_requests_made=r["external_requests_made"] + 1)})
    # more than one count attempt under the legacy shape
    _refuses(cohort, tmp_path / "counts", "this terminal shape spends exactly",
             source_kwargs={"mutate_receipt": lambda r: r.update(
                 count_attempts_made=r["count_attempts_made"] + 2,
                 external_requests_made=r["external_requests_made"] + 2)})


def test_an_empty_generate_body_in_the_source_is_refused(cohort, tmp_path):
    """A run that met both anomalies is a different, untested case."""
    _refuses(cohort, tmp_path, "empty generate bodies",
             source_kwargs={"mutate_receipt": lambda r: r.update(
                 empty_generate_body_attempts=2)})


def test_a_wrong_terminal_code_is_refused(cohort, tmp_path):
    _refuses(cohort, tmp_path / "timeout", "continues an empty-generate-body stop only",
             source_kwargs={"detail": "Governed provider failure (provider_timeout)."})
    _refuses(cohort, tmp_path / "breaker", "continues an empty-generate-body stop only",
             source_kwargs={"reason_code": "model_evidence_budget_exhausted",
                            "detail": "breaker exceeded"})


def test_source_and_grant_bindings_must_agree(cohort, tmp_path):
    _refuses(cohort, tmp_path / "arch", "authorization binds",
             grant_mutate=lambda a: a.update(source_raw_responses_sha256="f" * 64))
    _refuses(cohort, tmp_path / "kind", "violates its contract",
             grant_mutate=lambda a: a.update(source_kind="something_else"))
    # A cap below the schema floor is refused by the contract; one that merely
    # disagrees with the derived suffix is refused by the runner's arithmetic.
    _refuses(cohort, tmp_path / "capfloor", "violates its contract",
             grant_mutate=lambda a: a.update(count_attempt_cap=1))
    _refuses(cohort, tmp_path / "caps", "count_attempt_cap must be exactly",
             grant_mutate=lambda a: a.update(count_attempt_cap=99))


# --- 6-7. cohort closure, isolation and hygiene -------------------------------------


def test_the_full_cohort_closes_without_source_literals(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    run = _run(cohort, tmp_path, setup)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    counts = manifest["counts"]
    assert counts["reused_prefix_rows"] + counts["model_called_rows"] == counts["cohort_rows"]
    assert counts["cohort_rows"] == len(cohort.packets)
    assert len(_records(run.result)) == counts["planned_rows"]
    # the production code carries no literal from any live run
    for path in ("src/dynamic_ai_products/lineage_screen_continuation_v2.py",
                 "src/dynamic_ai_products/providers/vertex_gemini_screen_v5.py",
                 "schemas/universe_screen_continuation_authorization.v3.schema.json",
                 "schemas/universe_screen_continuation_manifest.v3.schema.json"):
        text = (ROOT / path).read_text(encoding="utf-8")
        for literal in ("4297", "2745", "7042", "3939", "3103"):
            assert literal not in text, f"{path} hard-codes {literal}"


def test_manifest_generations_and_grants_mutually_reject(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    run = _run(cohort, tmp_path, setup)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(MANIFEST_V1_SCHEMA).iter_errors(manifest))
    assert list(Draft202012Validator(AUTH_V1_SCHEMA).iter_errors(setup.grant.authorization))
    # the older authoritative loaders refuse this directory outright
    for loader in (ls.require_authoritative_screen_run, ll.require_promotable_screen_run):
        with pytest.raises(ls.ScreenInputError):
            loader(run.result.run_dir)
    lc3.require_continuation_v3_run(run.result.run_dir)


def test_the_source_run_is_never_modified(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    before = {p.name: sha256(p.read_bytes()).hexdigest()
              for p in sorted(setup.source.dir.rglob("*")) if p.is_file()}
    run = _run(cohort, tmp_path, setup)
    assert run.result.status == "completed"
    after = {p.name: sha256(p.read_bytes()).hexdigest()
             for p in sorted(setup.source.dir.rglob("*")) if p.is_file()}
    assert before == after


def test_dry_run_and_write_once(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    dry = _run(cohort, tmp_path, setup, dry_run=True)
    assert dry.result.status == "dry_run" and dry.result.run_dir is None
    assert dry.factory.opens == 0 and not (tmp_path / "screen").exists()
    first = _run(cohort, tmp_path, setup)
    assert first.result.status == "completed"
    with pytest.raises(FileExistsError):
        _run(cohort, tmp_path, setup)


def test_predecessors_are_byte_identical():
    """ADR-119 adds beside; it moves nothing that already shipped."""
    pins = {
        "src/dynamic_ai_products/lineage_screen_live.py":
            "795dddb081629ddba184f52070011f1c42a61a669698f3643694a7cceb73c2c2",
        "src/dynamic_ai_products/lineage_screen_live_v3.py":
            "631c9ee04cca63ffc3a01767e604f6f6ce3ab9ea89cb937117311f519ce49f6a",
        "src/dynamic_ai_products/lineage_screen_continuation.py":
            "0296ce47c7f4af88c425c31915d7c2abfa551f72d239729c985c11ed28aa93d9",
        "src/dynamic_ai_products/providers/retry_policy.py":
            "cb6de1d8c221afe0c90337f165ab74265b303b8eaf2f7a6f1b7bdc43f28dbca8",
        "src/dynamic_ai_products/providers/screen_retry_policy.py":
            "178286d67e80f0d9548e740a2b7f9f846cad2a636a97cb96bab72732db7b9d65",
        "src/dynamic_ai_products/providers/screen_count_retry_policy.py":
            "3a170abe267543b1094cea0cce1b83c490e3f624ec62385b6ef586b392d768f8",
        "src/dynamic_ai_products/providers/vertex_gemini_screen_v3.py":
            "46b0cfdde169180f8073c42330e8e0dfe8366519ea6f257c1943f0228f341c48",
        "src/dynamic_ai_products/providers/vertex_gemini_screen_v4.py":
            "123f2864fe29af0e35f0091ec13d82618d34a8a83846e2720c148d9811d0fa82",
        "prompts/discovery/universe_high_recall_screen.v5.md":
            "fee42d939f9eab590fdcbf055e7b2039e8a33a410dfc12257a47291d7a77d558",
    }
    for path, expected in pins.items():
        actual = sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual == expected, f"{path} moved: {actual}"


def test_the_v3_and_v4_routes_keep_their_policies():
    assert gp.SCREEN_GENERATE_MAX_ATTEMPTS == 5
    assert gp.SCREEN_GENERATE_RETRY_DELAYS_SECONDS == (15, 30, 60, 120)
    assert gp.SCREEN_COUNT_MAX_ATTEMPTS == 1
    assert cp.SCREEN_COUNT_MAX_ATTEMPTS_V2 == 3
    assert cp.SCREEN_COUNT_RETRY_DELAYS_SECONDS == (15, 30)
    # ADR-119 introduced no new schedule and no new budget.
    # ADR-120 introduces no new schedule and no new budget: both anomalies are
    # answered by the ceilings already in force.
    assert lc3.EMPTY_COUNT_TERMINAL_REASON == "empty_count_body_exhausted"
    assert lc3.EMPTY_GENERATE_TERMINAL_REASON == "empty_generate_body_exhausted"
    assert AUTH_V2_SCHEMA["properties"][
        "max_empty_generate_body_retries_per_row"]["const"] == 5
    assert AUTH_V2_SCHEMA["properties"][
        "max_empty_count_body_retries_per_row"]["const"] == 3


def test_registry_registers_the_two_v3_continuation_schemas():
    registry = json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json").read_text(encoding="utf-8"))
    assert registry["manifest_version"] == "0.64.0"
    assert len(registry["schemas"]) == 140
    assert registry["schemas"]["universe_screen_continuation_authorization_v3"] == "0.3.0"
    assert registry["schemas"]["universe_screen_continuation_manifest_v3"] == "0.10.0"
    # predecessors unchanged
    assert registry["schemas"]["universe_screen_continuation_authorization_v2"] == "0.2.0"
    assert registry["schemas"]["universe_screen_continuation_manifest_v2"] == "0.9.0"


def test_fresh_process_never_imports_google(tmp_path):
    script = f"""
import sys
sys.path.insert(0, {str(ROOT / "src")!r})
from dynamic_ai_products import lineage_screen_continuation_v3 as lc3
try:
    lc3.load_continuation_source_v3({str(tmp_path / "missing")!r},
                                    source_receipt_sha256="0" * 64)
except Exception:
    pass
print(sorted(m for m in sys.modules if m == "google" or m.startswith("google.")))
"""
    done = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, check=True)
    assert done.stdout.strip() == "[]", done.stdout


def _cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True)


def test_cli_v3_mode_gating(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    done = _cli("--mode", "screen-universe-lineage-continuation-v3",
                "--packet-manifest", str(cohort.manifest_path),
                "--selection-artifact", str(setup.selection),
                "--governance-root", str(setup.grant.root),
                "--screen-authorization", setup.grant.reference,
                "--screen-authorization-sha256", setup.grant.sha256,
                "--source-run-dir", str(setup.source.dir),
                "--source-receipt-sha256", setup.source.receipt_sha256,
                "--output-dir", str(tmp_path / "cli"), "--run-id", "cli-dry", "--dry-run")
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["status"] == "dry_run"
    assert not (tmp_path / "cli").exists()

    missing = _cli("--mode", "screen-universe-lineage-continuation-v3",
                   "--output-dir", str(tmp_path), "--run-id", "r")
    assert missing.returncode == 2 and "--source-run-dir" in missing.stderr
    for flag in ("--logical-request-cap", "--selection-seed"):
        bad = _cli("--mode", "screen-universe-lineage-continuation-v3",
                   "--output-dir", str(tmp_path), "--run-id", "r", flag, "3")
        assert bad.returncode == 2 and "does not accept" in bad.stderr
