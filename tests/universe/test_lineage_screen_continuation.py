"""ADR-118 continuation tests — synthetic failed runs, fake clients only.

Every "failed parent" here is built by hand from real packets and real V5
payloads, so the prefix under test has the shape a live failure leaves: a
receipt, a raw archive, and nothing else. No ``genai.Client`` is built, no
credential is resolved, no socket is opened, and no wait is ever slept.

The contract these tests hold the route to is that **reuse is earned**: a
reused row is re-rendered, re-resolved and re-validated by the same code a
fresh row goes through, and anything that cannot be re-proven is refused
before a run directory or a send exists.
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

from dynamic_ai_products import lineage_screen_continuation as lc
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products.providers import screen_count_retry_policy as count_policy
from dynamic_ai_products.providers import retry_policy as generic_policy
from dynamic_ai_products.providers import screen_retry_policy as gen_policy
from dynamic_ai_products.providers.client_contract_v2 import CLIENT_CONTRACT_V2_ID
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.vertex_gemini_screen_v3 import VertexGeminiScreenV3
from dynamic_ai_products.providers.vertex_gemini_screen_v4 import (
    VertexGeminiScreenV4,
    execute_with_count_retry,
)
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_screen_diagnostic import _v5_evidence_payload  # noqa: E402
from test_lineage_screen_live import (  # noqa: E402
    PACKET_FIXTURES,
    ROOT,
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
from test_lineage_screen_live_v3 import (  # noqa: E402
    _CIK_IN_PROMPT,
    _governance as _v3_governance,
)

CLI = ROOT / "pipelines" / "00_build_company_universe.py"
FIXED_CLOCK = lambda: datetime(2026, 8, 21, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731

RECORD_V3_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_record.v3.schema.json")
    .read_text(encoding="utf-8"))
CONTINUATION_MANIFEST_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_continuation_manifest.schema.json")
    .read_text(encoding="utf-8"))
CONTINUATION_AUTH_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_continuation_authorization.schema.json")
    .read_text(encoding="utf-8"))

PREFIX_ROWS = 4


def _google_modules() -> set[str]:
    return {n for n in sys.modules if n == "google" or n.startswith("google.")}


_GOOGLE_BASELINE: set[str] | None = None


@pytest.fixture(autouse=True)
def _google_module_baseline():
    global _GOOGLE_BASELINE
    if _GOOGLE_BASELINE is None:
        _GOOGLE_BASELINE = _google_modules()
    yield


def _assert_no_google_import() -> None:
    added = _google_modules() - (_GOOGLE_BASELINE or set())
    assert not added, f"the continuation path imported google: {sorted(added)}"


@pytest.fixture(scope="module")
def cohort(tmp_path_factory):
    """6 valid packets + 1 packet failure: prefix 4, suffix 2."""
    source, template = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    docs = []
    for index in range(6):
        cik = f"{7100000000 + index:010d}"
        docs.append((source, dict(template, cik=cik, accession=f"{cik}-22-000001")))
    docs.append(_fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"))
    built = _v5_run(tmp_path_factory.mktemp("cont-cohort"), [docs])
    assert len(built.packets) == 6 and len(built.failures) == 1
    return built


# --- the fake transport ------------------------------------------------------------


class _Fake429(Exception):
    status_code = 429


class _FakeReadTimeout(Exception):
    """A transport timeout: the failure that killed the live parent run."""


class _FakeUndeclared(Exception):
    """Outside every declared transient class. Never retried."""


class _EventCapture(_FakeCapture):
    def __init__(self, events: list):
        super().__init__()
        self._events = events

    def record_send(self, label, body, outcome):
        self._events.append(("send", label))
        super().record_send(label, body, outcome)

    def drain(self, label, ordinal):
        self._events.append(("capture", label))
        return super().drain(label, ordinal)


class _ContModels:
    def __init__(self, capture, script, events):
        self._capture, self._script, self._events = capture, script, events
        self.count_calls = self.generate_calls = 0

    def _entry(self, contents):
        match = _CIK_IN_PROMPT.search(contents)
        assert match, "rendered v5 prompt carries no cik line"
        return self._script[match.group(1)]

    def count_tokens(self, *, model, contents, config):
        self.count_calls += 1
        entry = self._entry(contents)
        if entry.get("count_timeouts", 0) > 0:
            entry["count_timeouts"] -= 1
            self._capture.record_send("count_tokens", None,
                                      "no_response_transport_failure")
            raise _FakeReadTimeout("scripted count timeout")
        tokens = entry.get("count_tokens", 120)
        self._capture.record_send(
            "count_tokens", json.dumps({"totalTokens": tokens}).encode(), "ok")
        return SimpleNamespace(total_tokens=tokens)

    def generate_content(self, *, model, contents, config):
        self.generate_calls += 1
        entry = self._entry(contents)
        if entry.get("undeclared_failures", 0) > 0:
            entry["undeclared_failures"] -= 1
            self._capture.record_send("generate_content", None,
                                      "no_response_transport_failure")
            raise _FakeUndeclared("scripted undeclared failure")
        if entry.get("quota_failures", 0) > 0:
            entry["quota_failures"] -= 1
            self._capture.record_send("generate_content", None,
                                      "no_response_transport_failure")
            raise _Fake429("scripted 429")
        envelope = _envelope(entry["text"], prompt_tokens=entry.get("count_tokens", 120))
        self._capture.record_send(
            "generate_content", json.dumps(envelope).encode(), "ok")
        return SimpleNamespace()


class _ContFactory:
    def __init__(self, script, events):
        self.script, self.events = script, events
        self.opens = self.count_calls = self.generate_calls = 0

    def __call__(self, *, vertex_project, vertex_location, endpoint_allowlist,
                 http_options_kwargs, operation_endpoints=None):
        @contextmanager
        def _open():
            self.opens += 1
            capture = _EventCapture(self.events)
            models = _ContModels(capture, self.script, self.events)
            try:
                yield SimpleNamespace(models=models), capture
            finally:
                self.count_calls += models.count_calls
                self.generate_calls += models.generate_calls
        return _open()


def _script(packets, **overrides):
    script = {p["cik"]: {"text": _v5_evidence_payload(p)} for p in packets}
    for cik, extra in overrides.items():
        script[cik] = {**script.get(cik, {}), **extra}
    return script


# --- the synthetic failed parent ---------------------------------------------------


def _archive_line(run_id, packet, payload):
    raw_sha = sha256(payload.encode("utf-8")).hexdigest()
    return json.dumps({
        "raw_response_id": f"{run_id}-{packet['cik']}-{packet['accession']}",
        "cik": packet["cik"],
        "accession": packet["accession"],
        "raw_response": payload,
        "raw_response_sha256": raw_sha,
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def _failed_run(tmp_path: Path, cohort, *, prefix_rows: int = PREFIX_ROWS,
                run_id: str = "parent-run", authorization_sha256: str,
                payloads=None, mutate_receipt=None, mutate_entries=None,
                extra_files=()) -> SimpleNamespace:
    """One failed V3 run: a receipt and a raw archive, and nothing else."""
    directory = tmp_path / "failed" / run_id
    directory.mkdir(parents=True, exist_ok=True)
    packets = cohort.packets[:prefix_rows]
    if payloads is None:
        payloads = [_v5_evidence_payload(p) for p in packets]
    entries = [_archive_line(run_id, p, payload)
               for p, payload in zip(packets, payloads)]
    if mutate_entries is not None:
        entries = mutate_entries(entries)
    archive_bytes = ("\n".join(entries) + "\n").encode("utf-8") if entries else b""
    (directory / ls.RAW_RESPONSES_FILENAME).write_bytes(archive_bytes)
    stopping = cohort.packets[prefix_rows]
    receipt = {
        "receipt_contract": "universe_screen_failure_receipt@0.1.0",
        "run_id": run_id,
        "reason_code": "provider_error",
        "detail": "Governed provider failure (provider_timeout).",
        "stopping_cik": stopping["cik"],
        "stopping_accession": stopping["accession"],
        "stopping_row_index": prefix_rows + 1,
        "records_completed_before_failure": prefix_rows,
        "raw_responses_captured": prefix_rows,
        # one un-retried count per attempted row; one generate per completed row
        "external_requests_made": (prefix_rows + 1) + prefix_rows,
        "provider_attempts_made": prefix_rows,
        "logical_request_cap": len(cohort.packets),
        "provider_attempt_cap": len(cohort.packets) * 5,
        "generate_attempt_cap_per_row": 5,
        "authorization_sha256": authorization_sha256,
        "run_timestamp": "2026-08-21T05:01:22+00:00",
        "retention_note": "Non-authoritative failed V3 live run.",
    }
    if mutate_receipt is not None:
        mutate_receipt(receipt)
    receipt_bytes = (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode()
    (directory / ls.FAILURE_RECEIPT_FILENAME).write_bytes(receipt_bytes)
    for name in extra_files:
        (directory / name).write_text("{}\n", encoding="utf-8")
    return SimpleNamespace(
        dir=directory, run_id=run_id, receipt=receipt,
        receipt_sha256=sha256(receipt_bytes).hexdigest(),
        archive_sha256=sha256(archive_bytes).hexdigest(),
        archive_bytes=archive_bytes, prefix_rows=prefix_rows)


def _continuation_grant(governance, *, cohort, parent, reused: int,
                        selection_path: Path, breaker: int = 4,
                        mutate=None) -> SimpleNamespace:
    """Write the continuation grant beside the parent's, in one root.

    Its bindings are derived from the inputs rather than copied from the
    parent grant, which is what a real continuation authorization does — and
    what lets a parent that ran under different rules be detected at all.
    """
    parent_auth = governance.authorization
    called = len(cohort.packets) - reused
    prompt_sha = sha256(
        (ROOT / "prompts/discovery/universe_high_recall_screen.v5.md").read_bytes()
    ).hexdigest()
    payload = {
        "authorization_contract": "universe_screen_continuation_authorization@0.1.0",
        "authorization_id": "continuation-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": "release_or_research_production",
        "run_kind": "full_cohort_continuation",
        "screen_stage": "universe_high_recall_screen",
        "source_run_id": parent.run_id,
        "source_run_path": str(parent.dir),
        "source_receipt_sha256": parent.receipt_sha256,
        "source_raw_responses_sha256": parent.archive_sha256,
        "source_authorization_reference": governance.reference,
        "source_authorization_sha256": governance.sha256,
        "packet_manifest_sha256": cohort.manifest_sha256,
        "prompt_template_sha256": prompt_sha,
        "selection_artifact_sha256": sha256(
            selection_path.read_bytes()).hexdigest(),
        "selection_kind": "full_cohort",
        "screen_adapter_enablement_reference":
            parent_auth["screen_adapter_enablement_reference"],
        "screen_adapter_enablement_sha256":
            parent_auth["screen_adapter_enablement_sha256"],
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": _contract_digest(),
        "vertex_project": VERTEX_PROJECT,
        "vertex_location": VERTEX_LOCATION,
        "model_route": {"provider": "google_vertex_ai",
                        "model_label": "gemini-2.5-flash"},
        "endpoint_allowlist": _endpoints(),
        "logical_row_cap": len(cohort.packets),
        "reused_prefix_row_cap": reused,
        "model_called_row_cap": called,
        "count_attempt_cap": called * 3,
        "provider_attempt_cap": called * 5,
        "budget_max_external_requests": called * 8,
        "count_attempts_per_row": 3,
        "generate_attempts_per_row": 5,
        "external_requests_per_row": 8,
        "budget_max_input_tokens": 10_000_000,
        "budget_max_output_tokens": 100_000_000,
        "budget_max_estimated_cost_micros": 1_000_000_000,
        "budget_max_wall_clock_seconds": 86_400,
        "retry_policy_version": generic_policy.RETRY_POLICY_VERSION,
        "rate_limit_policy_version": generic_policy.RATE_LIMIT_POLICY_VERSION,
        "screen_generate_retry_policy_version":
            gen_policy.SCREEN_GENERATE_RETRY_POLICY_VERSION,
        "screen_count_retry_policy_version":
            count_policy.SCREEN_COUNT_RETRY_POLICY_VERSION,
        "max_model_evidence_unverified": breaker,
    }
    if mutate is not None:
        mutate(payload)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (governance.root / "screen_continuation_authorization.json").write_bytes(raw)
    return SimpleNamespace(
        root=governance.root, reference="screen_continuation_authorization.json",
        sha256=sha256(raw).hexdigest(), authorization=payload)


def _setup(cohort, tmp_path, *, prefix_rows=PREFIX_ROWS, breaker=4,
           parent_kwargs=None, grant_mutate=None, v3_mutate=None):
    selection_path = _selection(cohort, tmp_path, "full_cohort")
    governance = _v3_governance(tmp_path, cohort=cohort,
                                selection_path=selection_path,
                                logical=len(cohort.packets), mutate=v3_mutate)
    parent = _failed_run(tmp_path, cohort, prefix_rows=prefix_rows,
                         authorization_sha256=governance.sha256,
                         **(parent_kwargs or {}))
    grant = _continuation_grant(governance, cohort=cohort, parent=parent,
                                reused=prefix_rows, breaker=breaker,
                                selection_path=selection_path,
                                mutate=grant_mutate)
    return SimpleNamespace(selection=selection_path, governance=governance,
                           parent=parent, grant=grant)


def _run(cohort, tmp_path, setup, *, script=None, run_id="cont", dry_run=False,
         clock=FIXED_CLOCK):
    waits: list[float] = []
    events: list = []

    def record_wait(seconds):
        waits.append(seconds)
        events.append(("wait", seconds))

    factory = _ContFactory(
        script if script is not None else _script(cohort.packets), events)
    result = lc.run_lineage_screen_continuation(
        repo_root=ROOT,
        packet_manifest_path=cohort.manifest_path,
        selection_artifact_path=setup.selection,
        governance_root=setup.grant.root,
        authorization_reference=setup.grant.reference,
        authorization_sha256=setup.grant.sha256,
        source_run_dir=setup.parent.dir,
        source_receipt_sha256=setup.parent.receipt_sha256,
        output_dir=tmp_path / "screen",
        run_id=run_id, clock=clock, dry_run=dry_run,
        client_factory=factory, sleep=record_wait,
    )
    _assert_no_google_import()
    return SimpleNamespace(result=result, factory=factory, waits=waits, events=events)


def _records(result):
    return [json.loads(x) for x in
            (result.run_dir / ls.RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


def _manifest(result):
    return json.loads(result.manifest_path.read_text(encoding="utf-8"))


# --- the happy path ----------------------------------------------------------------


def test_validated_prefix_plus_called_suffix_makes_one_authoritative_cohort(
        cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    run = _run(cohort, tmp_path, setup)
    result = run.result
    assert result.status == "completed", result.receipt

    records = _records(result)
    assert len(records) == len(cohort.packets) + len(cohort.failures) == 7
    reused = [r for r in records
              if r["row_provenance"]["origin"] == "reused_source_prefix"]
    called = [r for r in records if r["row_provenance"]["origin"] == "model_called"]
    insufficient = [r for r in records
                    if r["row_provenance"]["origin"] == "packet_build_failure"]
    assert (len(reused), len(called), len(insufficient)) == (4, 2, 1)

    # every record validates against the v0.3 contract
    validator = Draft202012Validator(RECORD_V3_SCHEMA, format_checker=FormatChecker())
    for row in records:
        assert not list(validator.iter_errors(row)), row["cik"]

    # reused rows keep their parent binding and their original response id
    for row in reused:
        prov = row["row_provenance"]
        assert prov["source_run_id"] == setup.parent.run_id
        assert prov["source_raw_responses_sha256"] == setup.parent.archive_sha256
        assert prov["source_receipt_sha256"] == setup.parent.receipt_sha256
        assert row["raw_response_id"].startswith(setup.parent.run_id)
    for row in called:
        assert row["row_provenance"]["source_run_id"] is None
        assert row["raw_response_id"].startswith("cont-")

    manifest = _manifest(result)
    Draft202012Validator(CONTINUATION_MANIFEST_SCHEMA,
                         format_checker=FormatChecker()).validate(manifest)
    assert manifest["manifest_contract"] == "universe_screen_manifest@0.8.0"
    assert manifest["run_kind"] == "full_cohort_continuation"
    assert manifest["counts"]["cohort_rows"] == 6
    assert manifest["counts"]["reused_prefix_rows"] == 4
    assert manifest["counts"]["model_called_rows"] == 2
    assert manifest["continuation"]["first_model_called_row_ordinal"] == 5
    assert manifest["continuation"]["source_archive_is_byte_identical_prefix"] is True
    assert manifest["parent_telemetry"]["per_attempt_telemetry_available"] is False
    assert all(manifest["reconciliation"].values())

    # the new archive opens with the parent's bytes, unmodified
    archive = (result.run_dir / ls.RAW_RESPONSES_FILENAME).read_bytes()
    assert archive.startswith(setup.parent.archive_bytes)
    assert len(archive.decode().strip().splitlines()) == 6

    # and the finished run is consumable
    ll.require_promotable_screen_run(result.run_dir)


def test_no_provider_send_happens_for_any_reused_row(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    run = _run(cohort, tmp_path, setup)
    assert run.result.status == "completed"
    # Two suffix rows, one count and one generate each. Nothing more.
    assert run.factory.count_calls == 2
    assert run.factory.generate_calls == 2
    accounting = run.result.request_accounting
    assert accounting["count_attempts_made"] == 2
    assert accounting["provider_attempts_made"] == 2
    assert accounting["external_requests_made"] == 4
    # The prefix CIKs never appear in any send.
    reused_ciks = {p["cik"] for p in cohort.packets[:PREFIX_ROWS]}
    assert not (reused_ciks & set(run.factory.script)) or all(
        run.factory.script[c].get("sent") is None for c in reused_ciks)
    ledger = [json.loads(x) for x in
              (run.result.run_dir / ll.CAPTURE_LEDGER_FILENAME)
              .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(ledger) == 4
    # Ledger ordinals are cohort ordinals: the first sent row is row 5.
    assert {e["row_ordinal"] for e in ledger} == {5, 6}


def test_the_first_called_row_is_exactly_the_parents_stopping_row(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    run = _run(cohort, tmp_path, setup)
    records = _records(run.result)
    called = [r for r in records
              if r["row_provenance"]["origin"] == "model_called"]
    assert (called[0]["cik"], called[0]["accession"]) == (
        setup.parent.receipt["stopping_cik"],
        setup.parent.receipt["stopping_accession"])
    # And it is the cohort's row 5, immediately after the 4-row prefix.
    assert called[0]["cik"] == cohort.packets[PREFIX_ROWS]["cik"]


# --- refusals, all before output or network ----------------------------------------


def _refuses(cohort, tmp_path, match, **setup_kwargs):
    setup = _setup(cohort, tmp_path, **setup_kwargs)
    output_dir = tmp_path / "screen"
    events: list = []
    factory = _ContFactory(_script(cohort.packets), events)
    with pytest.raises(ls.ScreenInputError, match=match):
        lc.run_lineage_screen_continuation(
            repo_root=ROOT, packet_manifest_path=cohort.manifest_path,
            selection_artifact_path=setup.selection,
            governance_root=setup.grant.root,
            authorization_reference=setup.grant.reference,
            authorization_sha256=setup.grant.sha256,
            source_run_dir=setup.parent.dir,
            source_receipt_sha256=setup.parent.receipt_sha256,
            output_dir=output_dir, run_id="refused", clock=FIXED_CLOCK,
            client_factory=factory,
            sleep=lambda s: pytest.fail("a refused run must never wait"),
        )
    assert not output_dir.exists() or not any(output_dir.iterdir())
    assert factory.opens == 0 and not events
    _assert_no_google_import()


def test_a_tampered_source_receipt_is_refused(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    receipt = setup.parent.dir / ls.FAILURE_RECEIPT_FILENAME
    receipt.write_bytes(receipt.read_bytes().replace(b"provider_timeout",
                                                     b"provider_timeouu"))
    with pytest.raises(ls.ScreenInputError, match="hashes to"):
        _run(cohort, tmp_path, setup)


def test_a_wrong_failure_shape_is_refused(cohort, tmp_path):
    """Only the enumerated countTokens-timeout shape may be continued."""
    _refuses(cohort, tmp_path / "a", "continues exactly one shape",
             parent_kwargs={"mutate_receipt": lambda r: r.update(
                 reason_code="model_evidence_budget_exhausted",
                 detail="Declared model-evidence breaker exceeded.")})
    _refuses(cohort, tmp_path / "b", "continues exactly one shape",
             parent_kwargs={"mutate_receipt": lambda r: r.update(
                 detail="Governed provider failure (vertex_quota_exhausted).")})


def test_a_completed_run_is_never_a_continuation_source(cohort, tmp_path):
    for name in (ls.SCREEN_MANIFEST_FILENAME, ls.RECORDS_FILENAME,
                 ll.CAPTURE_LEDGER_FILENAME):
        _refuses(cohort, tmp_path / name, "is never continued",
                 parent_kwargs={"extra_files": (name,)})


def test_archive_and_receipt_disagreement_is_refused(cohort, tmp_path):
    # archive shorter than the receipt claims
    _refuses(cohort, tmp_path / "short", "does not agree with its own receipt",
             parent_kwargs={"mutate_entries": lambda e: e[:-1]})
    # receipt claims a stopping row that is not prefix + 1
    _refuses(cohort, tmp_path / "gap", "contiguous prefix",
             parent_kwargs={"mutate_receipt": lambda r: r.update(
                 stopping_row_index=r["stopping_row_index"] + 2)})
    # the receipt names a stopping row the archive already holds, so the
    # prefix would end after the row that is about to be re-sent
    last_archived = cohort.packets[PREFIX_ROWS - 1]
    _refuses(cohort, tmp_path / "stop", "contains the stopping row",
             parent_kwargs={"mutate_receipt": lambda r: r.update(
                 stopping_cik=last_archived["cik"],
                 stopping_accession=last_archived["accession"])})
    _refuses(cohort, tmp_path / "counts", "countTokens-timeout shape",
             parent_kwargs={"mutate_receipt": lambda r: r.update(
                 external_requests_made=r["external_requests_made"] + 3)})


def test_a_tampered_raw_response_is_refused(cohort, tmp_path):
    def flip(entries):
        row = json.loads(entries[1])
        row["raw_response"] = row["raw_response"].replace("LIKELY", "UNLIKELY")
        return entries[:1] + [json.dumps(row, sort_keys=True, ensure_ascii=False,
                                         separators=(",", ":"))] + entries[2:]
    _refuses(cohort, tmp_path, "no longer matches its recorded digest",
             parent_kwargs={"mutate_entries": flip})


def test_duplicated_reordered_and_foreign_rows_are_refused(cohort, tmp_path):
    # duplicate id
    _refuses(cohort, tmp_path / "dup", "duplicate raw_response_ids",
             parent_kwargs={"mutate_entries": lambda e: e[:2] + [e[0]] + e[3:]})
    # reordered against the selection
    _refuses(cohort, tmp_path / "order", "maps onto the selection in order",
             parent_kwargs={"mutate_entries": lambda e: [e[1], e[0]] + e[2:]})


def test_a_non_prefix_row_cannot_be_reused(cohort, tmp_path):
    """A suffix row spliced into the prefix is refused, not silently accepted."""
    def splice(entries):
        return entries[:2] + entries[3:]
    _refuses(cohort, tmp_path, "maps onto the selection in order",
             parent_kwargs={"mutate_entries": splice,
                            "mutate_receipt": lambda r: r.update(
                                records_completed_before_failure=3,
                                raw_responses_captured=3,
                                stopping_row_index=4,
                                external_requests_made=7,
                                provider_attempts_made=3)})


def test_binding_drift_between_the_parent_and_the_continuation_is_refused(
        cohort, tmp_path):
    for field, value, match in (
        ("packet_manifest_sha256", "a" * 64, "packet cohort"),
        ("prompt_template_sha256", "b" * 64, "V5 screen prompt bytes"),
        ("selection_artifact_sha256", "c" * 64, "Selection and authorization"),
        ("model_route", {"provider": "other", "model_label": "other"},
         "route or policy binding"),
        ("provider_client_contract_sha256", "d" * 64, "client contract"),
        # Both screen policy versions are schema consts, so the contract
        # refuses them before the runner's own comparison is reached.
        ("screen_generate_retry_policy_version", "other_policy", "violates"),
        ("screen_count_retry_policy_version", "other_policy", "violates"),
        ("retry_policy_version", "other_policy", "route or policy binding"),
    ):
        _refuses(cohort, tmp_path / field, match,
                 grant_mutate=lambda a, f=field, v=value: a.update({f: v}))


def test_a_parent_grant_with_different_bindings_is_refused(cohort, tmp_path):
    """The prefix is reusable only if the parent ran under the same rules."""
    _refuses(cohort, tmp_path, "produced under different rules",
             v3_mutate=lambda a: a.update(
                 packet_manifest_sha256="e" * 64))


def test_source_pins_in_the_grant_must_match_the_named_run(cohort, tmp_path):
    _refuses(cohort, tmp_path / "arch", "authorization binds",
             grant_mutate=lambda a: a.update(source_raw_responses_sha256="f" * 64))
    _refuses(cohort, tmp_path / "rid", "the authorization names",
             grant_mutate=lambda a: a.update(source_run_id="not-the-parent"))
    _refuses(cohort, tmp_path / "rcpt", "not the one the authorization binds",
             grant_mutate=lambda a: a.update(source_receipt_sha256="a" * 64))


def test_cap_arithmetic_is_derived_and_refused_on_drift(cohort, tmp_path):
    _refuses(cohort, tmp_path / "rows", "but the inputs derive",
             grant_mutate=lambda a: a.update(reused_prefix_row_cap=3,
                                             model_called_row_cap=3))
    _refuses(cohort, tmp_path / "count", "count_attempt_cap must be exactly",
             grant_mutate=lambda a: a.update(count_attempt_cap=2 * 2))
    _refuses(cohort, tmp_path / "gen", "provider_attempt_cap must be exactly",
             grant_mutate=lambda a: a.update(provider_attempt_cap=2 * 3))
    _refuses(cohort, tmp_path / "ext", "budget_max_external_requests must be exactly",
             grant_mutate=lambda a: a.update(budget_max_external_requests=2 * 6))


# --- reused rows that no longer validate --------------------------------------------


def test_a_reused_row_that_no_longer_validates_becomes_unverified_not_screened(
        cohort, tmp_path):
    """Decision 2: it is recorded with its reason, never relabelled or dropped."""
    payloads = [_v5_evidence_payload(p) for p in cohort.packets[:PREFIX_ROWS]]
    payloads[2] = _v5_evidence_payload(cohort.packets[2],
                                       quote="a quote that is in no passage")
    setup = _setup(cohort, tmp_path, parent_kwargs={"payloads": payloads})
    run = _run(cohort, tmp_path, setup)
    assert run.result.status == "completed", run.result.receipt
    records = _records(run.result)
    unverified = [r for r in records
                  if r["record_kind"] == "model_evidence_unverified"]
    assert len(unverified) == 1
    assert unverified[0]["row_provenance"]["origin"] == "reused_source_prefix"
    assert unverified[0]["failure_reason_code"] == "quote_resolution_failure"
    assert unverified[0]["screen_status"] is None
    assert unverified[0]["screen_output"] is None
    manifest = _manifest(run.result)
    assert manifest["counts"]["reused_model_evidence_unverified"] == 1
    assert manifest["counts"]["model_evidence_unverified"] == 1
    # and it is still counted, never omitted
    assert manifest["reconciliation"][
        "unverified rows are counted, never omitted or relabelled"] is True


def test_a_prefix_that_already_busts_the_breaker_refuses_before_any_network(
        cohort, tmp_path):
    """The one place a reused validation failure stops the run outright."""
    payloads = [
        _v5_evidence_payload(p, quote="nowhere in any passage")
        for p in cohort.packets[:PREFIX_ROWS]
    ]
    _refuses(cohort, tmp_path, "cannot complete and does not start",
             breaker=2, parent_kwargs={"payloads": payloads})


def test_an_invalid_json_prefix_row_is_carried_as_unverified(cohort, tmp_path):
    payloads = [_v5_evidence_payload(p) for p in cohort.packets[:PREFIX_ROWS]]
    payloads[0] = "this is { not json"
    setup = _setup(cohort, tmp_path, parent_kwargs={"payloads": payloads})
    run = _run(cohort, tmp_path, setup)
    assert run.result.status == "completed"
    records = _records(run.result)
    assert records[0]["record_kind"] == "model_evidence_unverified"
    assert records[0]["failure_reason_code"] == "invalid_model_json"


# --- countTokens retry ---------------------------------------------------------------


def test_count_timeout_then_success_spends_three_attempts_and_two_waits(
        cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    slow = cohort.packets[PREFIX_ROWS]["cik"]
    script = _script(cohort.packets, **{slow: {"count_timeouts": 2}})
    run = _run(cohort, tmp_path, setup, script=script)
    assert run.result.status == "completed", run.result.receipt
    assert run.factory.count_calls == 3 + 1
    assert run.waits == [15.0, 30.0]
    accounting = run.result.request_accounting
    assert accounting["count_attempts_made"] == 4
    assert accounting["rows_count_retried"] == 1
    assert accounting["provider_attempts_made"] == 2
    # the generation still happened exactly once for that row, after the count
    row = [e for e in run.events if e[0] in ("send", "wait")][:8]
    assert row[:2] == [("send", "count_tokens"), ("wait", 15.0)]


def test_persistent_count_timeout_stops_with_a_receipt_and_no_generate_send(
        cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    stuck = cohort.packets[PREFIX_ROWS]["cik"]
    script = _script(cohort.packets, **{stuck: {"count_timeouts": 99}})
    run = _run(cohort, tmp_path, setup, script=script)
    result = run.result
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "provider_error"
    assert "provider_timeout" in receipt["detail"]
    assert receipt["run_kind"] == "full_cohort_continuation"
    # three count attempts, two waits, and never a generate send
    assert run.factory.count_calls == 3
    assert run.factory.generate_calls == 0
    assert run.waits == [15.0, 30.0]
    assert receipt["count_attempts_made"] == 3
    assert receipt["provider_attempts_made"] == 0
    assert receipt["reused_prefix_rows"] == PREFIX_ROWS
    assert receipt["stopping_cik"] == stuck
    # nothing consumable exists
    assert not (result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()
    assert not (result.run_dir / ls.RECORDS_FILENAME).exists()
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        ll.require_promotable_screen_run(result.run_dir)


def test_only_declared_transient_conditions_retry_the_count(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    run = _run(cohort, tmp_path, setup,
               script=_script(cohort.packets,
                              **{cohort.packets[PREFIX_ROWS]["cik"]:
                                 {"undeclared_failures": 9}}))
    assert run.result.status == "failed"
    assert run.factory.generate_calls == 1  # one send, no retry
    assert run.waits == []
    assert (count_policy.SCREEN_COUNT_RETRY_TRIGGER_STATUS_CODES
            is generic_policy.RETRY_TRIGGER_STATUS_CODES)
    assert count_policy.screen_count_should_retry is generic_policy.should_retry


def test_the_generate_policy_is_inherited_from_v3_unchanged(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    flaky = cohort.packets[PREFIX_ROWS]["cik"]
    run = _run(cohort, tmp_path, setup,
               script=_script(cohort.packets, **{flaky: {"quota_failures": 4}}))
    assert run.result.status == "completed", run.result.receipt
    assert run.waits == [15.0, 30.0, 60.0, 120.0]
    assert run.result.request_accounting["provider_attempts_made"] == 5 + 1
    assert run.result.request_accounting["rows_generate_retried"] == 1
    assert VertexGeminiScreenV4.complete_v8 is VertexGeminiScreenV3.complete_v8


def test_the_count_retry_is_bounded_and_reason_bearing():
    waits, calls = [], {"n": 0}

    def always():
        calls["n"] += 1
        raise _FakeReadTimeout("t")

    with pytest.raises(ProviderError) as excinfo:
        execute_with_count_retry(always, sleep=waits.append, max_attempts=99)
    assert excinfo.value.reason_code == "provider_timeout"
    assert calls["n"] == 3 and waits == [15.0, 30.0]


# --- immutability, isolation and hygiene ---------------------------------------------


def test_the_parent_failed_run_is_never_modified(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    before = {p.name: sha256(p.read_bytes()).hexdigest()
              for p in sorted(setup.parent.dir.iterdir()) if p.is_file()}
    run = _run(cohort, tmp_path, setup)
    assert run.result.status == "completed"
    after = {p.name: sha256(p.read_bytes()).hexdigest()
             for p in sorted(setup.parent.dir.iterdir()) if p.is_file()}
    assert before == after, "the parent run must be byte-identical afterwards"
    # and it stays non-authoritative forever
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        ls.require_authoritative_screen_run(setup.parent.dir)


def test_the_output_is_not_consumable_until_its_own_manifest_exists(
        cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    stuck = cohort.packets[PREFIX_ROWS]["cik"]
    failed = _run(cohort, tmp_path, setup, run_id="partial",
                  script=_script(cohort.packets, **{stuck: {"count_timeouts": 99}}))
    assert failed.result.status == "failed"
    # the directory holds reused prefix bytes but confers no authority
    archive = (failed.result.run_dir / ls.RAW_RESPONSES_FILENAME).read_bytes()
    assert archive == setup.parent.archive_bytes
    for loader in (ls.require_authoritative_screen_run,
                   ll.require_promotable_screen_run):
        with pytest.raises(ls.ScreenInputError):
            loader(failed.result.run_dir)
    assert "confer no authority" in failed.result.receipt["retention_note"]


def test_runs_are_write_once_and_dry_run_writes_nothing(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    dry = _run(cohort, tmp_path, setup, dry_run=True)
    assert dry.result.status == "dry_run" and dry.result.run_dir is None
    assert dry.factory.opens == 0 and dry.waits == []
    assert not (tmp_path / "screen").exists()
    assert dry.result.request_accounting["reused_prefix_rows"] == PREFIX_ROWS
    first = _run(cohort, tmp_path, setup)
    assert first.result.status == "completed"
    with pytest.raises(FileExistsError):
        _run(cohort, tmp_path, setup)


def test_predecessors_are_byte_identical():
    pins = {
        "src/dynamic_ai_products/lineage_screen_live.py":
            "795dddb081629ddba184f52070011f1c42a61a669698f3643694a7cceb73c2c2",
        "src/dynamic_ai_products/lineage_screen_live_v2.py":
            "bb982df18480e5828c55b4465e1612d8ddcbf295708e99a40cebd175557c89f5",
        "src/dynamic_ai_products/providers/retry_policy.py":
            "cb6de1d8c221afe0c90337f165ab74265b303b8eaf2f7a6f1b7bdc43f28dbca8",
        "src/dynamic_ai_products/providers/vertex_gemini.py":
            "000584c77b0dce871d33eea9e24110431a33962149df3b078fa92ce5ae3982ef",
        "src/dynamic_ai_products/providers/vertex_gemini_v2.py":
            "20b02d3875e1d565ec8e5190ed30f95c99d1253ba5c945327677a7afb1ed937a",
        "prompts/discovery/universe_high_recall_screen.v5.md":
            "fee42d939f9eab590fdcbf055e7b2039e8a33a410dfc12257a47291d7a77d558",
    }
    for path, expected in pins.items():
        actual = sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual == expected, f"{path} moved: {actual}"


def test_the_v3_route_and_its_policy_are_untouched():
    assert gen_policy.SCREEN_GENERATE_MAX_ATTEMPTS == 5
    assert gen_policy.SCREEN_GENERATE_RETRY_DELAYS_SECONDS == (15, 30, 60, 120)
    assert gen_policy.SCREEN_COUNT_MAX_ATTEMPTS == 1, (
        "the V3 route still sends countTokens exactly once")
    assert count_policy.SCREEN_COUNT_MAX_ATTEMPTS_V2 == 3
    assert count_policy.SCREEN_COUNT_RETRY_DELAYS_SECONDS == (15, 30)
    assert count_policy.SCREEN_EXTERNAL_REQUESTS_PER_ROW_V2 == 8
    for path, expected in {
        "src/dynamic_ai_products/lineage_screen_live_v3.py": None,
        "src/dynamic_ai_products/providers/screen_retry_policy.py": None,
        "src/dynamic_ai_products/providers/vertex_gemini_screen_v3.py": None,
    }.items():
        assert (ROOT / path).is_file()


def test_caps_scale_from_the_suffix_and_no_live_count_is_hard_coded():
    assert count_policy.screen_count_attempt_cap(3103) == 9309
    assert count_policy.screen_external_request_cap_v2(3103) == 24824
    assert gen_policy.screen_generate_attempt_cap(3103) == 15515
    for path in ("src/dynamic_ai_products/lineage_screen_continuation.py",
                 "src/dynamic_ai_products/providers/screen_count_retry_policy.py",
                 "src/dynamic_ai_products/providers/vertex_gemini_screen_v4.py",
                 "schemas/universe_screen_continuation_authorization.schema.json",
                 "schemas/universe_screen_continuation_manifest.schema.json"):
        text = (ROOT / path).read_text(encoding="utf-8")
        for literal in ("3939", "3103", "7042", "9309", "24824", "15515"):
            assert literal not in text, f"{path} hard-codes {literal}"


def test_the_continuation_grant_validates_against_its_own_contract(
        cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    validator = Draft202012Validator(CONTINUATION_AUTH_SCHEMA,
                                     format_checker=FormatChecker())
    assert not list(validator.iter_errors(setup.grant.authorization))
    # The per-row multipliers are consts; the row counts never are.
    props = CONTINUATION_AUTH_SCHEMA["properties"]
    assert props["count_attempts_per_row"]["const"] == 3
    assert props["generate_attempts_per_row"]["const"] == 5
    assert props["external_requests_per_row"]["const"] == 8
    for sized in ("logical_row_cap", "reused_prefix_row_cap",
                  "model_called_row_cap", "count_attempt_cap",
                  "provider_attempt_cap", "budget_max_external_requests"):
        assert "const" not in props[sized], f"{sized} must never be pinned"


def test_registry_registers_the_three_continuation_schemas():
    registry = json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json")
        .read_text(encoding="utf-8"))
    assert registry["manifest_version"] == "0.92.0"
    assert len(registry["schemas"]) == 246
    assert registry["schemas"]["universe_screen_record_v3"] == "0.3.0"
    assert registry["schemas"]["universe_screen_continuation_authorization"] == "0.1.0"
    assert registry["schemas"]["universe_screen_continuation_manifest"] == "0.8.0"


def test_fresh_process_preflight_never_imports_google(tmp_path):
    script = f"""
import sys
sys.path.insert(0, {str(ROOT / "src")!r})
from dynamic_ai_products import lineage_screen_continuation as lc
try:
    lc.load_continuation_source({str(tmp_path / "missing")!r},
                                source_receipt_sha256="0" * 64)
except Exception:
    pass
print(sorted(m for m in sys.modules if m == "google" or m.startswith("google.")))
"""
    done = subprocess.run([sys.executable, "-c", script], capture_output=True,
                          text=True, check=True)
    assert done.stdout.strip() == "[]", done.stdout


# --- CLI --------------------------------------------------------------------------


def _cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True)


def test_cli_continuation_dry_run_and_flag_gating(cohort, tmp_path):
    setup = _setup(cohort, tmp_path)
    done = _cli(
        "--mode", "screen-universe-lineage-continuation",
        "--packet-manifest", str(cohort.manifest_path),
        "--selection-artifact", str(setup.selection),
        "--governance-root", str(setup.grant.root),
        "--screen-authorization", setup.grant.reference,
        "--screen-authorization-sha256", setup.grant.sha256,
        "--source-run-dir", str(setup.parent.dir),
        "--source-receipt-sha256", setup.parent.receipt_sha256,
        "--output-dir", str(tmp_path / "cli"), "--run-id", "cli-dry", "--dry-run")
    assert done.returncode == 0, done.stderr
    payload = json.loads(done.stdout)
    assert payload["status"] == "dry_run"
    assert payload["request_accounting"]["reused_prefix_rows"] == PREFIX_ROWS
    assert not (tmp_path / "cli").exists()

    missing = _cli("--mode", "screen-universe-lineage-continuation",
                   "--output-dir", str(tmp_path), "--run-id", "r")
    assert missing.returncode == 2
    for flag in ("--source-run-dir", "--source-receipt-sha256",
                 "--packet-manifest", "--screen-authorization"):
        assert flag in missing.stderr

    # The caps are derived from the two populations, so stating them is
    # refused — by the same shared gate that governs every other mode.
    for flag in ("--logical-request-cap", "--provider-attempt-cap"):
        capped = _cli("--mode", "screen-universe-lineage-continuation",
                      "--output-dir", str(tmp_path), "--run-id", "r", flag, "6")
        assert capped.returncode == 2
        assert "does not accept" in capped.stderr and flag in capped.stderr


def test_cli_other_modes_refuse_the_source_flags(tmp_path):
    for mode in ("screen-universe-lineage-live-v3", "plan-acquisition-queue",
                 "select-screen-rows"):
        done = _cli("--mode", mode, "--source-run-dir", "d",
                    "--output-dir", str(tmp_path), "--run-id", "r")
        assert done.returncode == 2 and "--source-run-dir" in done.stderr
