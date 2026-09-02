"""ADR-117 long-429-backoff successor tests — fully offline, fake client only.

The cohort builder, the capture seam and the governance shape are imported
from the ADR-109/112 suites rather than duplicated, so what these tests
exercise is the real adapter, the real sink and the real strict validator with
exactly one thing substituted: the connector that owns the generate retry.

Nothing here waits. The wait chain is proven by injecting a recorder in place
of ``tenacity``'s sleep, so a five-attempt row that would take 225 seconds in
production takes microseconds here. No ``genai.Client`` is built, no
credential is resolved, no socket is opened, and a fresh-subprocess test
proves ``google.*`` never loads on the preflight path.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products import lineage_screen_live_v2 as lv2
from dynamic_ai_products import lineage_screen_live_v3 as lv3
from dynamic_ai_products.providers import retry_policy as generic_policy
from dynamic_ai_products.providers import screen_retry_policy as screen_policy
from dynamic_ai_products.providers.client_contract_v2 import CLIENT_CONTRACT_V2_ID
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.vertex_gemini import execute_with_retry
from dynamic_ai_products.providers.vertex_gemini_screen_v3 import (
    SCREEN_CONNECTOR_ID,
    VertexGeminiScreenV3,
    execute_with_screen_retry,
)
from dynamic_ai_products.providers.vertex_gemini_v2 import VertexGeminiProviderV2
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_screen_diagnostic import _v5_evidence_payload  # noqa: E402
from test_lineage_screen_live import (  # noqa: E402
    PACKET_FIXTURES,
    ROOT,
    SHELL_FIXTURES,
    TEXT_FIXTURES,
    VERTEX_LOCATION,
    VERTEX_PROJECT,
    _contract_digest,
    _endpoints,
    _envelope,
    _FakeCapture,
    _fixture_doc,
    _selection,
    _v5_run,
)

CLI = ROOT / "pipelines" / "00_build_company_universe.py"

MANIFEST_V5_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_manifest.v5.schema.json")
    .read_text(encoding="utf-8"))
MANIFEST_V6_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_manifest.v6.schema.json")
    .read_text(encoding="utf-8"))
MANIFEST_V7_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_manifest.v7.schema.json")
    .read_text(encoding="utf-8"))
AUTHORIZATION_V3_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_live_authorization.v3.schema.json")
    .read_text(encoding="utf-8"))

FIXED_CLOCK = lambda: datetime(2026, 8, 20, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731

_CIK_IN_PROMPT = re.compile(r"^cik: (\d{10})$", re.MULTILINE)

#: The measured production cohort of ADR-116, used only to state the
#: arithmetic this route authorizes. Nothing binds it.
FULL_COHORT_PACKETS = 7042


def _google_modules() -> set[str]:
    return {name for name in sys.modules
            if name == "google" or name.startswith("google.")}


#: Module-local delta baseline: other suites may legitimately have loaded the
#: vendor SDK earlier in a shared process, so the guard is "this path adds
#: nothing", with the absolute proof in the fresh-subprocess test below.
_GOOGLE_BASELINE: set[str] | None = None


@pytest.fixture(autouse=True)
def _google_module_baseline():
    global _GOOGLE_BASELINE
    if _GOOGLE_BASELINE is None:
        _GOOGLE_BASELINE = _google_modules()
    yield


def _assert_no_google_import() -> None:
    added = _google_modules() - (_GOOGLE_BASELINE or set())
    assert not added, f"the v3 screen path imported google modules: {sorted(added)}"


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    """3 valid packets + 2 packet failures — the full-cohort v3 fixture."""
    built = _v5_run(tmp_path_factory.mktemp("v3-cohort"), [
        [
            _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm"),
            _fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"),
            _fixture_doc(SHELL_FIXTURES, "shell_true_ballotbox.html"),
        ],
        [
            _fixture_doc(PACKET_FIXTURES, "primary_10kt.htm"),
            _fixture_doc(TEXT_FIXTURES, "text-10k-item1a.txt"),
            _fixture_doc(SHELL_FIXTURES, "shell_false_booleanfalse.html"),
        ],
    ])
    assert len(built.packets) == 3 and len(built.failures) == 2
    return built


# --- The fake transport: a 429-speaking Vertex ------------------------------------


class _Fake429(Exception):
    """The provider declaring a quota or rate limit — a declared retry trigger."""

    status_code = 429


class _FakeValidationBug(Exception):
    """An undeclared failure. Never a retry trigger under any policy."""


class _EventCapture(_FakeCapture):
    """The ADR-109 capture seam, with each send and each drain timestamped.

    ``drain`` is the sink's own read: logging it is what makes the
    capture-before-next-send ordering observable without touching the
    connector.
    """

    def __init__(self, events: list):
        super().__init__()
        self._events = events

    def record_send(self, label: str, body: bytes | None, outcome: str) -> None:
        self._events.append(("send", label))
        super().record_send(label, body, outcome)

    def drain(self, label: str, ordinal: int):
        self._events.append(("capture", label))
        return super().drain(label, ordinal)


class _ScreenModels:
    """Scripted count/generate behaviour keyed by the prompt's own CIK line."""

    def __init__(self, capture: _EventCapture, script: dict, events: list):
        self._capture = capture
        self._script = script
        self._events = events
        self.count_calls = 0
        self.generate_calls = 0

    def _entry(self, contents: str) -> dict:
        match = _CIK_IN_PROMPT.search(contents)
        assert match, "rendered v5 prompt carries no cik line"
        return self._script[match.group(1)]

    def count_tokens(self, *, model, contents, config):
        self.count_calls += 1
        entry = self._entry(contents)
        tokens = entry.get("count_tokens", 120)
        body = json.dumps({"totalTokens": tokens}).encode("utf-8")
        self._capture.record_send("count_tokens", body, "ok")
        return SimpleNamespace(total_tokens=tokens)

    def generate_content(self, *, model, contents, config):
        self.generate_calls += 1
        entry = self._entry(contents)
        if entry.get("undeclared_failures", 0) > 0:
            entry["undeclared_failures"] -= 1
            self._capture.record_send("generate_content", None,
                                      "no_response_transport_failure")
            raise _FakeValidationBug("scripted undeclared failure")
        if entry.get("quota_failures", 0) > 0:
            entry["quota_failures"] -= 1
            self._capture.record_send("generate_content", None,
                                      "no_response_transport_failure")
            raise _Fake429("scripted 429")
        envelope = _envelope(entry["text"], prompt_tokens=entry.get("count_tokens", 120))
        self._capture.record_send("generate_content",
                                  json.dumps(envelope).encode("utf-8"), "ok")
        return SimpleNamespace()


class _ScreenFactory:
    """Mimics the SDK factory's yield contract; counts every open."""

    def __init__(self, script: dict, events: list):
        self.script = script
        self.events = events
        self.opens = 0
        self.count_calls = 0
        self.generate_calls = 0

    def __call__(self, *, vertex_project, vertex_location, endpoint_allowlist,
                 http_options_kwargs, operation_endpoints=None):
        from contextlib import contextmanager

        @contextmanager
        def _open():
            self.opens += 1
            capture = _EventCapture(self.events)
            models = _ScreenModels(capture, self.script, self.events)
            try:
                yield SimpleNamespace(models=models), capture
            finally:
                self.count_calls += models.count_calls
                self.generate_calls += models.generate_calls

        return _open()


def _script(packets: list[dict], **overrides) -> dict:
    """Every row answers with a valid v5-shaped output unless overridden."""
    script = {p["cik"]: {"text": _v5_evidence_payload(p)} for p in packets}
    for cik, extra in overrides.items():
        script[cik] = {**script.get(cik, {}), **extra}
    return script


# --- Governance ------------------------------------------------------------------


def _governance(tmp_path: Path, *, cohort, selection_path: Path, logical: int,
                mutate=None, prompt_sha256: str | None = None) -> SimpleNamespace:
    """Write a valid enablement + v0.3 authorization pair; optionally tamper."""
    root = tmp_path / "governance"
    root.mkdir(parents=True, exist_ok=True)
    endpoints = _endpoints()
    digest = _contract_digest()
    enablement = {
        "enablement_contract": "universe_screen_adapter_enablement@0.1.0",
        "enablement_id": "screen-enablement-fixture",
        "enabled_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "screen_stage": "universe_high_recall_screen",
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": digest,
        "endpoint_allowlist": endpoints,
    }
    enablement_raw = (json.dumps(enablement, indent=2, sort_keys=True)
                      + "\n").encode("utf-8")
    (root / "screen_adapter_enablement.json").write_bytes(enablement_raw)
    template_sha = sha256((ROOT / lv2.PROMPT_PATH).read_bytes()).hexdigest()
    authorization = {
        "authorization_contract": "universe_screen_live_authorization@0.3.0",
        "authorization_id": "screen-v3-authorization-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": "release_or_research_production",
        "screen_stage": "universe_high_recall_screen",
        "packet_manifest_sha256": cohort.manifest_sha256,
        "prompt_template_sha256": (
            prompt_sha256 if prompt_sha256 is not None else template_sha),
        "selection_artifact_sha256": sha256(selection_path.read_bytes()).hexdigest(),
        "selection_kind": "full_cohort",
        "screen_adapter_enablement_reference": "screen_adapter_enablement.json",
        "screen_adapter_enablement_sha256": sha256(enablement_raw).hexdigest(),
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": digest,
        "vertex_project": VERTEX_PROJECT,
        "vertex_location": VERTEX_LOCATION,
        "model_route": {"provider": "google_vertex_ai",
                        "model_label": "gemini-2.5-flash"},
        "endpoint_allowlist": endpoints,
        "logical_request_cap": logical,
        "provider_attempt_cap": logical * 5,
        "budget_max_external_requests": logical * 6,
        "budget_max_input_tokens": 10_000_000,
        "budget_max_output_tokens": 100_000_000,
        "budget_max_estimated_cost_micros": 1_000_000_000,
        "budget_max_wall_clock_seconds": 86_400,
        "retry_policy_version": generic_policy.RETRY_POLICY_VERSION,
        "rate_limit_policy_version": generic_policy.RATE_LIMIT_POLICY_VERSION,
        "screen_generate_retry_policy_version":
            screen_policy.SCREEN_GENERATE_RETRY_POLICY_VERSION,
        "generate_attempt_cap_per_row": 5,
        "external_requests_per_row": 6,
        "max_model_evidence_unverified": 2,
    }
    if mutate is not None:
        mutate(authorization)
    authorization_raw = (json.dumps(authorization, indent=2, sort_keys=True)
                         + "\n").encode("utf-8")
    (root / "screen_live_authorization_v3.json").write_bytes(authorization_raw)
    return SimpleNamespace(
        root=root,
        reference="screen_live_authorization_v3.json",
        sha256=sha256(authorization_raw).hexdigest(),
        authorization=authorization,
    )


def _setup(cohort, tmp_path: Path, **kwargs):
    selection_path = _selection(cohort, tmp_path, "full_cohort")
    governance = _governance(tmp_path, cohort=cohort, selection_path=selection_path,
                             logical=len(cohort.packets), **kwargs)
    return selection_path, governance


def _run(cohort, tmp_path: Path, *, selection_path, governance, script=None,
         run_id="v3", logical=None, attempts=None, dry_run=False,
         clock=FIXED_CLOCK):
    """Run the v3 route against the fake transport, recording every wait."""
    waits: list[float] = []
    events: list = []

    def record_wait(seconds: float) -> None:
        """One stream for sends, captures and waits, so order is checkable."""
        waits.append(seconds)
        events.append(("wait", seconds))

    logical = len(cohort.packets) if logical is None else logical
    factory = _ScreenFactory(
        script if script is not None else _script(cohort.packets), events)
    result = lv3.run_lineage_screen_live_v3(
        repo_root=ROOT,
        packet_manifest_path=cohort.manifest_path,
        selection_artifact_path=selection_path,
        governance_root=governance.root,
        authorization_reference=governance.reference,
        authorization_sha256=governance.sha256,
        output_dir=tmp_path / "screen",
        run_id=run_id,
        logical_request_cap=logical,
        provider_attempt_cap=(logical * 5 if attempts is None else attempts),
        clock=clock,
        dry_run=dry_run,
        client_factory=factory,
        sleep=record_wait,
    )
    _assert_no_google_import()
    return SimpleNamespace(result=result, factory=factory, waits=waits, events=events)


def _records(result) -> list[dict]:
    return [json.loads(line) for line in
            (result.run_dir / ls.RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if line.strip()]


def _ledger(result) -> list[dict]:
    return [json.loads(line) for line in
            (result.run_dir / ll.CAPTURE_LEDGER_FILENAME)
            .read_text(encoding="utf-8").splitlines() if line.strip()]


def _manifest(result) -> dict:
    return json.loads(result.manifest_path.read_text(encoding="utf-8"))


# --- 1. Four transient 429s, then success ----------------------------------------


def test_four_transient_429s_then_success_spends_five_attempts_and_four_waits(
        cohort, tmp_path):
    selection_path, governance = _setup(cohort, tmp_path)
    retried = cohort.packets[0]["cik"]
    script = _script(cohort.packets, **{retried: {"quota_failures": 4}})
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance, script=script)
    result = run.result
    assert result.status == "completed", result.receipt

    # Five sends for the retried row, one each for the other two.
    assert run.factory.generate_calls == 5 + 1 + 1
    accounting = result.request_accounting
    assert accounting["provider_attempts_made"] == 7
    assert accounting["rows_retried"] == 1
    assert accounting["generate_captures"] == 7
    assert accounting["count_captures"] == 3
    assert accounting["external_requests_made"] == 10  # 3 counts + 7 generates

    # The waits are the policy's, in order, with nothing in between.
    assert run.waits == [15.0, 30.0, 60.0, 120.0]
    assert run.waits == [
        screen_policy.screen_delay_before_attempt(n) for n in range(2, 6)
    ]

    # Four failed attempts persisted no body; the fifth is the terminal one.
    ledger = _ledger(result)
    row_one = [e for e in ledger
               if e["row_ordinal"] == 1 and e["operation_label"] == "generate_content"]
    assert len(row_one) == 5
    assert [e["capture_disposition"] for e in row_one] == (
        ["no_body_captured"] * 4 + ["raw_persisted"])
    assert [e["attempt_ordinal"] for e in row_one] == [1, 2, 3, 4, 5]

    # The row still produced an ordinary accepted record.
    records = _records(result)
    screened = [r for r in records if r["record_kind"] == "screened_packet"]
    assert len(screened) == 3
    assert all(r["screen_status"] in ls.SCREEN_STATUSES for r in screened)
    assert all(result.reconciliation.values())


# --- 2. Persistent 429 ------------------------------------------------------------


def test_persistent_429_stops_after_five_attempts_with_quota_exhausted(
        cohort, tmp_path):
    selection_path, governance = _setup(cohort, tmp_path)
    stuck = cohort.packets[1]["cik"]
    script = _script(cohort.packets, **{stuck: {"quota_failures": 99}})
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance, script=script)
    result = run.result
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "provider_error"
    assert "vertex_quota_exhausted" in receipt["detail"]

    # Exactly five sends on the stuck row: the policy stopped it, not the fake.
    assert run.factory.generate_calls == 1 + 5
    assert receipt["provider_attempts_made"] == 6
    assert receipt["stopping_row_index"] == 2
    assert receipt["records_completed_before_failure"] == 1
    assert receipt["generate_attempt_cap_per_row"] == 5
    # Four waits, not five: the last attempt is not followed by a wait.
    assert run.waits == [15.0, 30.0, 60.0, 120.0]

    # A failed run is non-authoritative and leaves no consumable output.
    assert not (result.run_dir / ls.RECORDS_FILENAME).exists()
    assert not (result.run_dir / ll.CAPTURE_LEDGER_FILENAME).exists()
    assert not (result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        ll.require_promotable_screen_run(result.run_dir)


def test_the_five_attempt_ceiling_is_the_policy_not_the_caller(cohort, tmp_path):
    """A caller cannot buy a sixth attempt, and the reason code survives."""
    waits: list[float] = []
    calls = {"n": 0}

    def always_429():
        calls["n"] += 1
        raise _Fake429("quota")

    with pytest.raises(ProviderError) as excinfo:
        execute_with_screen_retry(always_429, sleep=waits.append, max_attempts=99)
    assert excinfo.value.reason_code == "vertex_quota_exhausted"
    assert calls["n"] == 5 and waits == [15.0, 30.0, 60.0, 120.0]

    # And a lower cap still lowers it.
    waits.clear()
    calls["n"] = 0
    with pytest.raises(ProviderError):
        execute_with_screen_retry(always_429, sleep=waits.append, max_attempts=2)
    assert calls["n"] == 2 and waits == [15.0]


# --- 3. countTokens is never duplicated -------------------------------------------


def test_count_tokens_is_never_duplicated_during_a_generate_retry(cohort, tmp_path):
    selection_path, governance = _setup(cohort, tmp_path)
    retried = cohort.packets[0]["cik"]
    script = _script(cohort.packets, **{retried: {"quota_failures": 4}})
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance, script=script)
    assert run.result.status == "completed"

    # One count send per logical row, whatever the generate attempts cost.
    assert run.factory.count_calls == 3
    ledger = _ledger(run.result)
    counts = [e for e in ledger if e["operation_label"] == "count_tokens"]
    assert len(counts) == 3
    assert [e["attempt_ordinal"] for e in counts] == [1, 1, 1]
    assert {e["row_ordinal"] for e in counts} == {1, 2, 3}

    # The retried row's own event stream carries exactly one count send.
    generate_sends = [e for e in run.events if e == ("send", "generate_content")]
    count_sends = [e for e in run.events if e == ("send", "count_tokens")]
    assert len(generate_sends) == 7 and len(count_sends) == 3
    assert run.result.request_accounting["count_captures"] == 3
    assert screen_policy.SCREEN_COUNT_MAX_ATTEMPTS == 1

    # Structural, not incidental: the screen connector does not override the
    # count operation, whose V2 implementation carries no retry loop at all.
    assert (VertexGeminiScreenV3.count_tokens
            is VertexGeminiProviderV2.count_tokens)


# --- 4. Capture before the next send ----------------------------------------------


def test_every_failed_generate_attempt_is_captured_before_the_next_send(
        cohort, tmp_path):
    selection_path, governance = _setup(cohort, tmp_path)
    retried = cohort.packets[0]["cik"]
    script = _script(cohort.packets, **{retried: {"quota_failures": 4}})
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance, script=script)
    assert run.result.status == "completed"

    # The first row's stream, in full. Every send is drained into the sink
    # before anything else happens, each wait follows its own attempt's
    # capture, and the next send only ever follows a completed wait.
    expected = [("send", "count_tokens"), ("capture", "count_tokens")]
    for delay in (15.0, 30.0, 60.0, 120.0):
        expected += [("send", "generate_content"),
                     ("capture", "generate_content"),
                     ("wait", delay)]
    expected += [("send", "generate_content"), ("capture", "generate_content")]
    assert run.events[:len(expected)] == expected

    # The second row starts only after the first row is fully captured.
    assert run.events[len(expected)] == ("send", "count_tokens")

    # No send is ever unaccompanied: the ledger holds one line per send.
    sends = [e for e in run.events if e[0] == "send"]
    captures = [e for e in run.events if e[0] == "capture"]
    assert len(sends) == len(captures) == len(_ledger(run.result)) == 10


def test_the_sink_holds_every_prior_attempt_before_each_wait():
    """Connector-level proof, with the test owning the sink and the clock."""
    from dynamic_ai_products.extraction.provider_adapter import CaptureRecord

    persisted: list[int] = []
    waits: list[float] = []
    attempts = {"n": 0}

    def sink(*, operation_label, attempt_ordinal, raw_bytes, send_outcome,
             sdk_call_outcome, provider_reason_code):
        persisted.append(attempt_ordinal)
        return CaptureRecord(
            operation_label=operation_label,
            attempt_ordinal=attempt_ordinal,
            send_outcome=send_outcome,
            sdk_call_outcome=sdk_call_outcome,
            capture_disposition="no_body_captured",
            provider_reason_code=provider_reason_code,
        )

    def record_wait(seconds: float) -> None:
        # The wait for attempt k+1 may only happen once attempt k is in the
        # sink: k captures have been taken by the time the k-th wait begins.
        assert len(persisted) == len(waits) + 1, (persisted, waits)
        waits.append(seconds)

    capture = _FakeCapture()

    def attempt():
        attempts["n"] += 1
        ordinal = capture.next_ordinal("generate_content")
        capture.record_send("generate_content", None, "no_response_transport_failure")
        sink(
            operation_label="generate_content",
            attempt_ordinal=ordinal,
            raw_bytes=capture.drain("generate_content", ordinal),
            send_outcome=capture.send_outcome("generate_content", ordinal),
            sdk_call_outcome="raised",
            provider_reason_code="vertex_quota_exhausted",
        )
        raise _Fake429("quota")

    with pytest.raises(ProviderError):
        execute_with_screen_retry(attempt, sleep=record_wait)
    assert attempts["n"] == 5
    assert persisted == [1, 2, 3, 4, 5]
    assert waits == [15.0, 30.0, 60.0, 120.0]


def test_a_persistence_failure_stops_the_loop_instead_of_being_retried():
    """A capture-sink failure is not a transient condition and never retries."""
    from dynamic_ai_products.extraction.provider_adapter import CaptureSinkError

    attempts = {"n": 0}
    waits: list[float] = []

    def attempt():
        attempts["n"] += 1
        raise CaptureSinkError(
            operation_label="generate_content",
            attempt_ordinal=attempts["n"],
            persistence_reason_code="write_error",
            provider_reason_code=None,
        )

    with pytest.raises(CaptureSinkError):
        execute_with_screen_retry(attempt, sleep=waits.append)
    assert attempts["n"] == 1 and waits == []


def test_only_the_declared_transient_conditions_are_retried(cohort, tmp_path):
    """A validation-shaped failure is terminal on its first attempt."""
    selection_path, governance = _setup(cohort, tmp_path)
    broken = cohort.packets[0]["cik"]
    script = _script(cohort.packets, **{broken: {"undeclared_failures": 9}})
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance, script=script)
    assert run.result.status == "failed"
    assert run.factory.generate_calls == 1
    assert run.waits == []
    # The screen policy's trigger set is the committed one, object for object.
    assert (screen_policy.SCREEN_RETRY_TRIGGER_STATUS_CODES
            is generic_policy.RETRY_TRIGGER_STATUS_CODES)
    assert screen_policy.screen_should_retry is generic_policy.should_retry
    assert 429 in screen_policy.SCREEN_RETRY_TRIGGER_STATUS_CODES


# --- 5. The predecessors are untouched --------------------------------------------


def test_predecessor_routes_are_byte_identical():
    pins = {
        # The ADR-109 authoritative route and its schemas.
        "src/dynamic_ai_products/lineage_screen_live.py":
            "795dddb081629ddba184f52070011f1c42a61a669698f3643694a7cceb73c2c2",
        # The ADR-116 authoritative successor this route succeeds.
        "src/dynamic_ai_products/lineage_screen_live_v2.py":
            "bb982df18480e5828c55b4465e1612d8ddcbf295708e99a40cebd175557c89f5",
        # The committed generic transport policy and both shared connectors.
        "src/dynamic_ai_products/providers/retry_policy.py":
            "cb6de1d8c221afe0c90337f165ab74265b303b8eaf2f7a6f1b7bdc43f28dbca8",
        "src/dynamic_ai_products/providers/vertex_gemini.py":
            "000584c77b0dce871d33eea9e24110431a33962149df3b078fa92ce5ae3982ef",
        "src/dynamic_ai_products/providers/vertex_gemini_v2.py":
            "20b02d3875e1d565ec8e5190ed30f95c99d1253ba5c945327677a7afb1ed937a",
        # The prompt all three V5 routes render.
        "prompts/discovery/universe_high_recall_screen.v5.md":
            "fee42d939f9eab590fdcbf055e7b2039e8a33a410dfc12257a47291d7a77d558",
    }
    for path, expected in pins.items():
        actual = sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual == expected, f"{path} moved: {actual}"


def test_the_generic_three_attempt_policy_still_behaves_as_committed():
    assert generic_policy.RETRY_MAX_ATTEMPTS == 3
    assert generic_policy.RETRY_DELAYS_SECONDS == (1, 2)
    assert [generic_policy.delay_before_attempt(n) for n in (1, 2, 3)] == [0.0, 1.0, 2.0]
    with pytest.raises(ValueError):
        generic_policy.delay_before_attempt(4)

    waits: list[float] = []
    calls = {"n": 0}

    def always_429():
        calls["n"] += 1
        raise _Fake429("quota")

    with pytest.raises(ProviderError) as excinfo:
        execute_with_retry(always_429, sleep=waits.append)
    assert excinfo.value.reason_code == "vertex_quota_exhausted"
    assert calls["n"] == 3, "the committed route still stops at three attempts"
    assert waits == [1.0, 2.0], "the committed route still waits 1s then 2s"


def test_the_v2_connector_still_refuses_a_five_attempt_cap():
    """The long backoff is not reachable from the predecessor connector."""
    common = dict(
        vertex_project=VERTEX_PROJECT, vertex_location=VERTEX_LOCATION,
        expected_authorization_sha256="a" * 64,
        endpoint_allowlist=tuple(_endpoints()),
    )
    old = VertexGeminiProviderV2(max_provider_requests=5, **common)
    with pytest.raises(ProviderError) as excinfo:
        old.assert_run_permitted(
            authorization_sha256="a" * 64,
            endpoint_allowlist=tuple(_endpoints()),
            enablement_endpoint_allowlist=tuple(_endpoints()),
        )
    assert excinfo.value.reason_code == "live_call_not_authorized"

    # The screen connector accepts exactly five, and still refuses six.
    new = VertexGeminiScreenV3(max_provider_requests=5, **common)
    new.assert_run_permitted(
        authorization_sha256="a" * 64,
        endpoint_allowlist=tuple(_endpoints()),
        enablement_endpoint_allowlist=tuple(_endpoints()),
    )
    too_many = VertexGeminiScreenV3(max_provider_requests=6, **common)
    with pytest.raises(ProviderError):
        too_many.assert_run_permitted(
            authorization_sha256="a" * 64,
            endpoint_allowlist=tuple(_endpoints()),
            enablement_endpoint_allowlist=tuple(_endpoints()),
        )


def test_a_v3_grant_cannot_run_on_the_v2_route_and_vice_versa(cohort, tmp_path):
    """The two generations' authorization contracts mutually reject."""
    selection_path, governance = _setup(cohort, tmp_path)
    v3_grant = json.loads(
        (governance.root / governance.reference).read_text(encoding="utf-8"))
    v2_schema = json.loads(
        (ROOT / "schemas" / "universe_screen_live_authorization.v2.schema.json")
        .read_text(encoding="utf-8"))
    assert list(Draft202012Validator(v2_schema).iter_errors(v3_grant)), (
        "a long-backoff grant must not validate as a three-attempt grant")

    v2_grant = dict(v3_grant)
    v2_grant["authorization_contract"] = "universe_screen_live_authorization@0.2.0"
    for field in ("screen_generate_retry_policy_version",
                  "generate_attempt_cap_per_row", "external_requests_per_row"):
        v2_grant.pop(field)
    v2_grant["provider_attempt_cap"] = len(cohort.packets) * 3
    v2_grant["budget_max_external_requests"] = len(cohort.packets) * 4
    assert list(Draft202012Validator(AUTHORIZATION_V3_SCHEMA).iter_errors(v2_grant))


# --- 6. A wrong cap or policy fails before anything exists -------------------------


def _refusal(cohort, tmp_path, match, *, attempts=None, **governance_kwargs):
    selection_path, governance = _setup(cohort, tmp_path, **governance_kwargs)
    output_dir = tmp_path / "screen"
    events: list = []
    factory = _ScreenFactory(_script(cohort.packets), events)
    with pytest.raises(ls.ScreenInputError, match=match):
        lv3.run_lineage_screen_live_v3(
            repo_root=ROOT,
            packet_manifest_path=cohort.manifest_path,
            selection_artifact_path=selection_path,
            governance_root=governance.root,
            authorization_reference=governance.reference,
            authorization_sha256=governance.sha256,
            output_dir=output_dir,
            run_id="refused",
            logical_request_cap=len(cohort.packets),
            provider_attempt_cap=(len(cohort.packets) * 5 if attempts is None
                                  else attempts),
            clock=FIXED_CLOCK,
            client_factory=factory,
            sleep=lambda seconds: pytest.fail("a refused run must never wait"),
        )
    # Nothing exists: no run directory, no SDK open, no google import.
    assert not output_dir.exists() or not any(output_dir.iterdir())
    assert factory.opens == 0
    assert not events
    _assert_no_google_import()


def test_a_wrong_cap_or_policy_fails_before_output_sdk_or_network(cohort, tmp_path):
    rows = len(cohort.packets)

    # The operator states the predecessor's three-attempt arithmetic.
    _refusal(cohort, tmp_path / "a", "provider_attempt_cap must be exactly 15",
             attempts=rows * 3)

    # The grant itself states it.
    _refusal(cohort, tmp_path / "b", "provider_attempt_cap must be exactly 15",
             mutate=lambda a: a.update(provider_attempt_cap=rows * 3))

    # The external-request ceiling pays for four sends per row, not six.
    _refusal(cohort, tmp_path / "c", "budget_max_external_requests must be exactly 18",
             mutate=lambda a: a.update(budget_max_external_requests=rows * 4))

    # The grant names another generate policy, or another per-row arithmetic.
    # These three are schema consts, so the contract refuses them before the
    # runner ever compares them — which is the earlier of the two gates.
    _refusal(cohort, tmp_path / "d", "violates its contract",
             mutate=lambda a: a.update(
                 screen_generate_retry_policy_version="extraction_provider_retry_policy_v1"))
    _refusal(cohort, tmp_path / "e", "violates its contract",
             mutate=lambda a: a.update(generate_attempt_cap_per_row=3))
    _refusal(cohort, tmp_path / "f", "violates its contract",
             mutate=lambda a: a.update(external_requests_per_row=4))

    # And the committed transport policy is still bound.
    _refusal(cohort, tmp_path / "g", "policy binding",
             mutate=lambda a: a.update(retry_policy_version="some_other_policy"))


def test_the_runner_repeats_the_policy_binding_the_schema_pins(
        cohort, tmp_path, monkeypatch):
    """Belt and braces, and provably live rather than dead.

    The three policy fields are schema consts, so no grant that validates can
    reach the runner's own comparison. Moving the code's expectation is the
    one way to make schema and runner disagree, and it is exactly the drift
    the second gate exists for: a later schema relaxation must not silently
    become a transport change.
    """
    monkeypatch.setattr(lv3, "SCREEN_GENERATE_MAX_ATTEMPTS", 9)
    _refusal(cohort, tmp_path / "drift",
             "does not name this route's screen generate")


def test_other_bindings_still_refuse_before_anything_exists(cohort, tmp_path):
    _refusal(cohort, tmp_path / "h", "V5 screen prompt bytes",
             prompt_sha256="b" * 64)
    _refusal(cohort, tmp_path / "i", "different provider client contract",
             mutate=lambda a: a.update(provider_client_contract_sha256="c" * 64))
    _refusal(cohort, tmp_path / "j", "effective window",
             mutate=lambda a: a.update(expires_at="2026-08-02T00:00:00+00:00"))
    _refusal(cohort, tmp_path / "k", "endpoint allowlists",
             mutate=lambda a: a.update(
                 endpoint_allowlist=["https://example.invalid/a",
                                     "https://example.invalid/b"]))
    _refusal(cohort, tmp_path / "l", "circuit breaker",
             mutate=lambda a: a.update(max_model_evidence_unverified=999))


# --- The authoritative run itself --------------------------------------------------


def test_v3_run_end_to_end_records_its_policy_and_arithmetic(cohort, tmp_path):
    selection_path, governance = _setup(cohort, tmp_path)
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance)
    result = run.result
    assert result.status == "completed", result.receipt
    assert run.waits == []

    records = _records(result)
    assert len(records) == 5  # 3 screened + 2 insufficient
    assert sum(r["record_kind"] == "screened_packet" for r in records) == 3
    assert sum(r["record_kind"] == "insufficient_evidence" for r in records) == 2
    assert all(r["record_contract"] == "universe_screen_record@0.2.0"
               for r in records)

    manifest = _manifest(result)
    Draft202012Validator(MANIFEST_V7_SCHEMA, format_checker=FormatChecker()).validate(
        manifest)
    assert manifest["manifest_contract"] == "universe_screen_manifest@0.7.0"
    assert manifest["provider"]["connector"] == SCREEN_CONNECTOR_ID
    assert manifest["generate_retry_policy"] == {
        "policy_version": "universe_screen_generate_retry_policy_v1",
        "retry_owner": "tenacity",
        "generate_max_attempts": 5,
        "generate_retry_delays_seconds": [15, 30, 60, 120],
        "jitter": False,
        "count_max_attempts": 1,
        "external_requests_per_row": 6,
    }
    accounting = manifest["request_accounting"]
    assert accounting["logical_request_cap"] == 3
    assert accounting["provider_attempt_cap"] == 15
    assert accounting["external_request_cap"] == 18
    assert accounting["generate_attempt_cap_per_row"] == 5
    assert accounting["external_requests_per_row"] == 6
    assert accounting["provider_attempts_made"] == 3
    assert accounting["external_requests_made"] == 6
    assert accounting["rows_retried"] == 0
    assert all(manifest["reconciliation"].values())

    # The manifest is the run's own bytes, re-derivable from disk.
    assert manifest["output_hashes"][ls.RECORDS_FILENAME] == sha256(
        (result.run_dir / ls.RECORDS_FILENAME).read_bytes()).hexdigest()
    ll.require_promotable_screen_run(result.run_dir)


def test_the_run_arithmetic_scales_to_the_full_cohort():
    """Stated, not pinned: the ceilings are functions of the selection."""
    assert screen_policy.screen_generate_attempt_cap(FULL_COHORT_PACKETS) == 35_210
    assert screen_policy.screen_external_request_cap(FULL_COHORT_PACKETS) == 42_252
    assert FULL_COHORT_PACKETS * 5 == 35_210
    assert FULL_COHORT_PACKETS * 6 == 42_252
    # No production cohort size appears in the shipped code or schemas.
    for path in ("src/dynamic_ai_products/lineage_screen_live_v3.py",
                 "src/dynamic_ai_products/providers/screen_retry_policy.py",
                 "schemas/universe_screen_live_authorization.v3.schema.json",
                 "schemas/universe_screen_manifest.v7.schema.json"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "35210" not in text and "42252" not in text
        assert "7042" not in text


def test_model_evidence_rows_survive_a_retried_row(cohort, tmp_path):
    """The ADR-116 row semantics are unchanged by the longer backoff."""
    selection_path, governance = _setup(cohort, tmp_path)
    retried, unverified = cohort.packets[0]["cik"], cohort.packets[1]["cik"]
    script = _script(cohort.packets, **{
        retried: {"quota_failures": 4},
        unverified: {"text": _v5_evidence_payload(
            cohort.packets[1], quote="text that appears in no passage")},
    })
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance, script=script)
    result = run.result
    assert result.status == "completed", result.receipt
    records = _records(result)
    unverified_rows = [r for r in records
                       if r["record_kind"] == "model_evidence_unverified"]
    assert len(unverified_rows) == 1
    assert unverified_rows[0]["failure_reason_code"] == "quote_resolution_failure"
    assert unverified_rows[0]["screen_status"] is None
    assert unverified_rows[0]["screen_output"] is None
    manifest = _manifest(result)
    assert manifest["counts"]["model_evidence_unverified"] == 1
    assert manifest["counts"]["rejections_by_reason"]["quote_resolution_failure"] == 1


def test_the_model_evidence_breaker_still_stops_the_run(cohort, tmp_path):
    selection_path, governance = _setup(
        cohort, tmp_path, mutate=lambda a: a.update(max_model_evidence_unverified=1))
    script = _script(cohort.packets, **{
        p["cik"]: {"text": _v5_evidence_payload(p, quote="nowhere in any passage")}
        for p in cohort.packets
    })
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance, script=script)
    assert run.result.status == "failed"
    assert run.result.receipt["reason_code"] == "model_evidence_budget_exhausted"
    assert not (run.result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()


def test_manifest_generations_mutually_reject(cohort, tmp_path):
    selection_path, governance = _setup(cohort, tmp_path)
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance)
    manifest = _manifest(run.result)
    for older in (MANIFEST_V5_SCHEMA, MANIFEST_V6_SCHEMA):
        assert list(Draft202012Validator(older).iter_errors(manifest)), (
            "a v0.7 manifest must not validate as an older generation")


def test_dry_run_validates_and_writes_nothing(cohort, tmp_path):
    selection_path, governance = _setup(cohort, tmp_path)
    run = _run(cohort, tmp_path, selection_path=selection_path,
               governance=governance, dry_run=True)
    assert run.result.status == "dry_run" and run.result.run_dir is None
    assert run.result.request_accounting["generate_attempt_cap_per_row"] == 5
    assert run.result.request_accounting["external_requests_per_row"] == 6
    assert run.factory.opens == 0 and run.waits == []
    assert not (tmp_path / "screen").exists()


def test_runs_are_write_once(cohort, tmp_path):
    selection_path, governance = _setup(cohort, tmp_path)
    first = _run(cohort, tmp_path, selection_path=selection_path,
                 governance=governance)
    assert first.result.status == "completed"
    with pytest.raises(FileExistsError):
        _run(cohort, tmp_path, selection_path=selection_path,
             governance=governance)


# --- Repository hygiene -------------------------------------------------------------


def test_registry_registers_the_two_v3_screen_schemas():
    registry = json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json")
        .read_text(encoding="utf-8"))
    # ADR-117 adds the v0.3 authorization and v0.7 manifest (115 -> 117).
    assert registry["manifest_version"] == "0.95.0"
    assert len(registry["schemas"]) == 256
    assert registry["schemas"]["universe_screen_live_authorization_v3"] == "0.3.0"
    assert registry["schemas"]["universe_screen_manifest_v7"] == "0.7.0"
    # Every predecessor entry is unchanged.
    assert registry["schemas"]["universe_screen_live_authorization_v2"] == "0.2.0"
    assert registry["schemas"]["universe_screen_manifest_v6"] == "0.6.0"
    assert registry["schemas"]["universe_screen_record_v2"] == "0.2.0"


def test_fresh_process_preflight_never_imports_google(tmp_path):
    """Absolute proof in a process of its own: refusal touches no vendor SDK."""
    script = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(ROOT / "src")!r})
from dynamic_ai_products import lineage_screen_live_v3 as lv3
from dynamic_ai_products.universe.lineage_screen import ScreenInputError
try:
    lv3.run_lineage_screen_live_v3(
        repo_root={str(ROOT)!r},
        packet_manifest_path={str(tmp_path / "missing.json")!r},
        selection_artifact_path={str(tmp_path / "missing-sel.json")!r},
        governance_root={str(tmp_path)!r},
        authorization_reference="absent.json",
        authorization_sha256="0" * 64,
        output_dir={str(tmp_path / "out")!r},
        run_id="fresh",
        logical_request_cap=1,
        provider_attempt_cap=5,
        clock=lambda: __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc),
    )
except Exception:
    pass
loaded = sorted(m for m in sys.modules if m == "google" or m.startswith("google."))
print(loaded)
"""
    completed = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True)
    assert completed.stdout.strip() == "[]", completed.stdout


# --- CLI ------------------------------------------------------------------------------


def _cli(*args):
    return subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True)


def test_cli_v3_mode_dry_run_and_refusal(cohort, tmp_path):
    selection_path, governance = _setup(cohort, tmp_path)
    completed = _cli(
        "--mode", "screen-universe-lineage-live-v3",
        "--packet-manifest", str(cohort.manifest_path),
        "--selection-artifact", str(selection_path),
        "--governance-root", str(governance.root),
        "--screen-authorization", governance.reference,
        "--screen-authorization-sha256", governance.sha256,
        "--logical-request-cap", str(len(cohort.packets)),
        "--provider-attempt-cap", str(len(cohort.packets) * 5),
        "--output-dir", str(tmp_path / "cli"), "--run-id", "cli-dry", "--dry-run",
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "dry_run"
    assert payload["request_accounting"]["provider_attempt_cap"] == 15
    assert not (tmp_path / "cli").exists()

    refused = _cli(
        "--mode", "screen-universe-lineage-live-v3",
        "--packet-manifest", str(cohort.manifest_path),
        "--selection-artifact", str(selection_path),
        "--governance-root", str(governance.root),
        "--screen-authorization", governance.reference,
        "--screen-authorization-sha256", governance.sha256,
        "--logical-request-cap", str(len(cohort.packets)),
        "--provider-attempt-cap", str(len(cohort.packets) * 3),
        "--output-dir", str(tmp_path / "cli2"), "--run-id", "cli-refused",
    )
    assert refused.returncode == 2
    assert "provider_attempt_cap must be exactly 15" in refused.stderr


def test_cli_v3_mode_requires_all_flags_and_refuses_foreign_ones(tmp_path):
    missing = _cli("--mode", "screen-universe-lineage-live-v3",
                   "--output-dir", str(tmp_path), "--run-id", "r")
    assert missing.returncode == 2
    for flag in ("--packet-manifest", "--selection-artifact", "--governance-root",
                 "--screen-authorization", "--screen-authorization-sha256",
                 "--logical-request-cap", "--provider-attempt-cap"):
        assert flag in missing.stderr

    for flag, value in (("--screen-fixture", "x"), ("--selection-seed", "3"),
                        ("--selection-kind", "canary_100"),
                        ("--source-diagnostic-manifest", "m.json")):
        refused = _cli("--mode", "screen-universe-lineage-live-v3",
                       "--output-dir", str(tmp_path), "--run-id", "r", flag, value)
        assert refused.returncode == 2 and flag in refused.stderr
