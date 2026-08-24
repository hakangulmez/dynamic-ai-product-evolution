"""ADR-112 diagnostic-canary tests — fully offline, fake-client only.

The cohort, fake Vertex transport, selection and governance helpers are
imported from the ADR-109/110/111 live suite rather than duplicated: this
module tests a *successor* of that route, and sharing the fixtures is what
makes the parity assertions meaningful — the same cohort, the same scripted
responses and the same validator, differing only in per-row policy.

No real ``genai.Client`` is built, no credential is resolved, no socket is
opened, and several tests assert that ``google.*`` never enters
``sys.modules``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import lineage_screen_diagnostic as ld
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_screen_live import (  # noqa: E402
    ARCHETYPES,
    PACKET_FIXTURES,
    ROOT,
    _contract_digest,
    _endpoints,
    _FakeFactory,
    _fixture_doc,
    _model_output,
    _script_for,
    _selection,
    _v5_run,
)

CLI = ROOT / "pipelines" / "00_build_company_universe.py"

RECORD_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_diagnostic_record.schema.json")
    .read_text(encoding="utf-8"))
MANIFEST_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_diagnostic_manifest.schema.json")
    .read_text(encoding="utf-8"))
AUTHORIZATION_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_diagnostic_authorization.schema.json")
    .read_text(encoding="utf-8"))
LIVE_MANIFEST_V4_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_manifest.v4.schema.json")
    .read_text(encoding="utf-8"))

VERTEX_PROJECT = "test-vertex-project"
VERTEX_LOCATION = "us-central1"


# --- No-SDK guard ------------------------------------------------------------------
#
# This module owns its own baseline rather than borrowing the live suite's:
# in a full-suite run tests/providers legitimately loads ``google.*`` before
# tests/universe, and this module sorts before the live one, so a shared
# baseline would be uninitialized here. The guard is a delta — nothing the
# diagnostic path does may ADD a google module — and the absolute proof lives
# in test_fresh_process_preflight_never_imports_google, which checks a
# process of its own.

_GOOGLE_BASELINE: set[str] | None = None


def _google_modules() -> set[str]:
    return {name for name in sys.modules
            if name == "google" or name.startswith("google.")}


@pytest.fixture(autouse=True)
def _google_module_baseline():
    global _GOOGLE_BASELINE
    if _GOOGLE_BASELINE is None:
        _GOOGLE_BASELINE = _google_modules()
    yield


def _assert_no_google_import() -> None:
    added = _google_modules() - (_GOOGLE_BASELINE or set())
    assert not added, f"the diagnostic path imported google modules: {sorted(added)}"


# --- Cohorts ----------------------------------------------------------------------
#
# Built here from the live suite's shared builder rather than imported as
# fixtures, so this module owns its own cohort lifecycle and no fixture name
# is redefined across modules.


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    """104 packets + 1 failure: the canary cohort (100 of 104 are selected)."""
    source, template = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    docs = [
        (source, dict(template, cik=f"{9100000000 + index:010d}",
                      accession=f"{9100000000 + index:010d}-22-000001"))
        for index in range(104)
    ]
    docs.append(_fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"))
    built = _v5_run(tmp_path_factory.mktemp("diag-big"), [docs])
    assert len(built.packets) == 104
    return built


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    """A three-packet cohort, used only for full-cohort refusal coverage."""
    built = _v5_run(tmp_path_factory.mktemp("diag-small"), [[
        _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm"),
        _fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"),
        _fixture_doc(PACKET_FIXTURES, "primary_10kt.htm"),
    ]])
    return built


# --- Diagnostic governance ---------------------------------------------------------


def _diagnostic_governance(tmp_path: Path, *, cohort, selection_path: Path,
                           logical: int, max_rejected: int = 25,
                           mutate_authorization=None, mutate_enablement=None,
                           prompt_sha256: str | None = None):
    """A valid diagnostic enablement + authorization pair; optionally tampered."""
    from types import SimpleNamespace

    from dynamic_ai_products.providers.client_contract_v2 import CLIENT_CONTRACT_V2_ID
    from dynamic_ai_products.providers.retry_policy import (
        RATE_LIMIT_POLICY_VERSION, RETRY_POLICY_VERSION)

    root = tmp_path / "governance"
    root.mkdir(parents=True, exist_ok=True)
    endpoints, digest = _endpoints(), _contract_digest()
    enablement = {
        "enablement_contract": "universe_screen_adapter_enablement@0.1.0",
        "enablement_id": "diagnostic-enablement-fixture",
        "enabled_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "screen_stage": "universe_high_recall_screen",
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": digest,
        "endpoint_allowlist": endpoints,
    }
    if mutate_enablement is not None:
        mutate_enablement(enablement)
    enablement_raw = (json.dumps(enablement, indent=2, sort_keys=True)
                      + "\n").encode("utf-8")
    (root / "screen_adapter_enablement.json").write_bytes(enablement_raw)
    template_sha = sha256(
        (ROOT / ld.DIAGNOSTIC_PROMPT_TEMPLATE_RELATIVE_PATH)
        .read_bytes()).hexdigest()
    authorization = {
        "authorization_contract": "universe_screen_diagnostic_authorization@0.1.0",
        "authorization_id": "diagnostic-authorization-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": "controlled_pilot",
        "screen_stage": "universe_high_recall_screen",
        "run_kind": "diagnostic_canary",
        "diagnostic_only": True,
        "promotable": False,
        "output_contract": "universe_screen_diagnostic_record@0.1.0",
        "packet_manifest_sha256": cohort.manifest_sha256,
        "prompt_template_sha256": (
            prompt_sha256 if prompt_sha256 is not None else template_sha),
        "selection_artifact_sha256": sha256(
            selection_path.read_bytes()).hexdigest(),
        "selection_kind": "canary_100",
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
        "provider_attempt_cap": logical * 3,
        "budget_max_external_requests": logical * 4,
        "budget_max_input_tokens": 10_000_000,
        "budget_max_output_tokens": 100_000_000,
        "budget_max_estimated_cost_micros": 1_000_000_000,
        "budget_max_wall_clock_seconds": 86_400,
        "max_rejected_rows": max_rejected,
        "retry_policy_version": RETRY_POLICY_VERSION,
        "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
    }
    if mutate_authorization is not None:
        mutate_authorization(authorization)
    authorization_raw = (json.dumps(authorization, indent=2, sort_keys=True)
                         + "\n").encode("utf-8")
    (root / "screen_diagnostic_authorization.json").write_bytes(authorization_raw)
    return SimpleNamespace(root=root,
                           reference="screen_diagnostic_authorization.json",
                           sha256=sha256(authorization_raw).hexdigest(),
                           authorization=authorization)


def _diagnostic(cohort, tmp_path: Path, *, selection_path, governance,
                script=None, run_id="diag", logical=None, attempts=None,
                dry_run=False, clock=None):
    from datetime import datetime, timezone

    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if logical is None:
        logical = len(selection["rows"])
    factory = _FakeFactory(script if script is not None
                           else _script_for(cohort.packets))
    result = ld.run_lineage_screen_diagnostic(
        repo_root=ROOT,
        packet_manifest_path=cohort.manifest_path,
        selection_artifact_path=selection_path,
        governance_root=governance.root,
        authorization_reference=governance.reference,
        authorization_sha256=governance.sha256,
        output_dir=tmp_path / "diagnostic",
        run_id=run_id,
        logical_request_cap=logical,
        provider_attempt_cap=(logical * 3 if attempts is None else attempts),
        clock=clock or (lambda: datetime(2026, 8, 20, 9, 0, 0,
                                         tzinfo=timezone.utc)),
        dry_run=dry_run,
        client_factory=factory,
    )
    return result, factory


def _canary_setup(big, tmp_path: Path, **kwargs):
    """The 100-row canary selection over the 104-packet cohort."""
    selection_path = _selection(big, tmp_path, "canary_100", seed=7)
    governance = _diagnostic_governance(tmp_path, cohort=big,
                                        selection_path=selection_path,
                                        logical=100, **kwargs)
    return selection_path, governance


def _records(result) -> list[dict]:
    return [json.loads(line) for line in
            (result.run_dir / ld.DIAGNOSTIC_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if line.strip()]


def _bad(packet, kind: str) -> str:
    """One raw response per model-output failure mode."""
    if kind == "invalid_model_json":
        return "this is { not json"
    payload = json.loads(_model_output(packet, "LIKELY_ELIGIBLE"))
    if kind == "adapter_rejection":
        payload["candidate_customer_value_archetypes"] = ["Productivity/Efficiency"]
    elif kind == "quote_resolution_failure":
        payload["positive_evidence"][0]["quote"] = "text present in no passage"
    return json.dumps(payload)


def _v5_evidence_payload(packet: dict, *, ref: str = "P001",
                         quote: str | None = None,
                         supplied_source: str | None = None) -> str:
    """One v5-shaped response: model emits a passage ref, never source truth."""
    passage = packet["passages"][0]
    evidence = {
        "passage_ref": ref,
        "quote": passage["text"] if quote is None else quote,
        "supported_claim": "The cited passage supports this diagnostic claim.",
    }
    if supplied_source is not None:
        evidence["source_id"] = supplied_source
    return json.dumps({
        "screen_status": "LIKELY_ELIGIBLE",
        "plausible_customer_facing_digital_product": True,
        "candidate_customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "positive_evidence": [evidence],
        "negative_or_boundary_evidence": [],
        "missing_evidence": [],
        "confidence": "high",
    })


def test_v5_renderer_removes_model_facing_source_identity_and_round_trips(big):
    """There is one packet source, so only passage selection reaches model."""
    packet = big.packets[0]
    template = (ROOT / ld.DIAGNOSTIC_PROMPT_TEMPLATE_RELATIVE_PATH).read_text(
        encoding="utf-8")
    rendered, refs = ld.render_diagnostic_prompt_with_citation_refs(template, packet)
    assert "sec-primary:" not in rendered
    assert packet["source_id"] not in rendered
    assert packet["passages"][0]["passage_id"] not in rendered
    assert "[passage_ref=P001 section=" in rendered
    assert refs["P001"] == packet["passages"][0]["passage_id"]

    # A hostile or malformed source field is discarded; packet ownership,
    # not model copying, supplies source identity before strict validation.
    raw = _v5_evidence_payload(
        packet, supplied_source="sec-primary:invented:source"
    )
    normalized = ld.resolve_diagnostic_citation_refs(raw, refs, packet)
    output = ls._validate_row_output(normalized, packet)
    evidence = output.positive_evidence[0]
    assert evidence.source_id == packet["source_id"]
    assert evidence.passage_id == packet["passages"][0]["passage_id"]


@pytest.mark.parametrize("ref,quote", [
    ("P999", None),
    ("P001", "Text present in no passage."),
    ("P001", "The supplied filing says something else."),
])
def test_v5_resolver_never_repairs_unknown_refs_or_nonverbatim_quotes(
        big, ref, quote):
    packet = big.packets[0]
    template = (ROOT / ld.DIAGNOSTIC_PROMPT_TEMPLATE_RELATIVE_PATH).read_text(
        encoding="utf-8")
    _, refs = ld.render_diagnostic_prompt_with_citation_refs(template, packet)
    raw = _v5_evidence_payload(packet, ref=ref, quote=quote)
    with pytest.raises(ls._RowValidationFailure,
                       match="passage_id|quote does not resolve") as exc:
        ls._validate_row_output(
            ld.resolve_diagnostic_citation_refs(raw, refs, packet), packet
        )
    assert exc.value.reason_code == "quote_resolution_failure"


def test_v5_replays_the_seven_measured_failures_without_relaxing_quotes():
    """Read-only regression over the exact seven v4 diagnostic rejections.

    This is intentionally an integration pin rather than a fixture: it proves
    the structural source injection cures the one source-copy error while the
    six wrong-passage/non-verbatim examples remain strict rejections.  A clean
    checkout without the ignored diagnostic artifact skips rather than making
    the unit suite depend on an unavailable research run.
    """
    run_dir = ROOT / "data/runs/universe-screens" / (
        "universe-high-recall-diagnostic-canary-v2-20260820"
    )
    records_path = run_dir / ld.DIAGNOSTIC_RECORDS_FILENAME
    archive_path = run_dir / ls.RAW_RESPONSES_FILENAME
    if not records_path.is_file() or not archive_path.is_file():
        pytest.skip("the pinned v4 diagnostic artifact is unavailable")
    records = [json.loads(line) for line in records_path.read_text(
        encoding="utf-8").splitlines() if line.strip()]
    rejected = [r for r in records if r["record_kind"] == "rejected_output"]
    assert len(rejected) == 7
    archive = {entry["raw_response_id"]: entry["raw_response"] for entry in (
        json.loads(line) for line in archive_path.read_text(
            encoding="utf-8").splitlines() if line.strip()
    )}
    manifest = json.loads((run_dir / ld.DIAGNOSTIC_MANIFEST_FILENAME).read_text(
        encoding="utf-8"))
    inputs = ls.load_packet_run(ROOT, ROOT / manifest["packet_manifest_path"])
    packets = {(p["cik"], p["accession"]): p for p in inputs.packets}
    template = (ROOT / ld.DIAGNOSTIC_PROMPT_TEMPLATE_RELATIVE_PATH).read_text(
        encoding="utf-8")

    repaired, still_rejected = [], []
    for record in rejected:
        packet = packets[(record["cik"], record["accession"])]
        _, refs = ld.render_diagnostic_prompt_with_citation_refs(template, packet)
        normalized = ld.resolve_diagnostic_citation_refs(
            archive[record["raw_response_id"]], refs, packet
        )
        try:
            ls._validate_row_output(normalized, packet)
        except ls._RowValidationFailure as exc:
            assert exc.reason_code == "quote_resolution_failure"
            still_rejected.append(record["row_ordinal"])
        else:
            repaired.append(record["row_ordinal"])
    assert repaired == [22]  # the sole long-source copying error
    assert still_rejected == [13, 24, 26, 30, 48, 53]


# --- The happy path and the partition -------------------------------------------------


def test_full_canary_completes_and_partitions(big, tmp_path):
    selection_path, governance = _canary_setup(big, tmp_path)
    result, factory = _diagnostic(big, tmp_path, selection_path=selection_path,
                                  governance=governance, logical=100)
    assert result.status == "completed", result.receipt
    records = _records(result)
    assert len(records) == 100
    assert result.validated == 100 and result.rejected == 0
    assert factory.count_calls == 100 and factory.generate_calls == 100
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(
        MANIFEST_SCHEMA, format_checker=FormatChecker()
    ).iter_errors(manifest)) == []
    for record in records:
        assert list(Draft202012Validator(
            RECORD_SCHEMA, format_checker=FormatChecker()
        ).iter_errors(record)) == []
    assert manifest["counts"]["validated"] + manifest["counts"]["rejected"] == 100
    assert manifest["request_accounting"]["logical_requests_made"] == 100
    assert manifest["request_accounting"]["external_requests_made"] == 200
    assert len(manifest["reconciliation"]) >= 14
    assert all(manifest["reconciliation"].values())
    for filename, recorded in manifest["output_hashes"].items():
        assert sha256((result.run_dir / filename).read_bytes()).hexdigest() \
            == recorded
    _assert_no_google_import()


@pytest.mark.parametrize("reason", [
    "invalid_model_json", "adapter_rejection", "quote_resolution_failure",
])
def test_each_output_failure_is_recorded_and_the_run_continues(
        big, tmp_path, reason):
    selection_path, governance = _canary_setup(big, tmp_path)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    victim_cik = selection["rows"][10]["cik"]
    victim = next(p for p in big.packets if p["cik"] == victim_cik)
    script = _script_for(big.packets)
    script[victim_cik]["text"] = _bad(victim, reason)
    result, factory = _diagnostic(big, tmp_path, selection_path=selection_path,
                                  governance=governance, logical=100,
                                  script=script)
    assert result.status == "completed"
    assert result.validated == 99 and result.rejected == 1
    assert result.rejections_by_reason[reason] == 1
    records = _records(result)
    assert len(records) == 100  # the run did NOT stop at row 11
    assert factory.generate_calls == 100
    rejected = [r for r in records if r["record_kind"] == "rejected_output"]
    assert len(rejected) == 1
    row = rejected[0]
    assert row["cik"] == victim_cik
    assert row["rejection_reason_code"] == reason
    # No accepted result of any kind, and the contract has no status field.
    assert row["screen_output"] is None
    assert "screen_status" not in row
    assert 0 < len(row["rejection_detail"]) <= ld.REJECTION_DETAIL_MAX
    # Bindings and measurement survive on a rejected row.
    assert row["raw_response_id"] and row["raw_response_sha256"]
    assert row["packet_sha256"] and row["prompt_sha256"]
    assert row["measured_input_tokens"] > 0 and row["cost_micros"] > 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["rejections_by_reason"][reason] == 1
    assert manifest["request_accounting"]["cost_micros_rejected_rows"] == \
        row["cost_micros"]


def test_temporal_violation_is_recorded_and_continues(big, tmp_path):
    """The fourth reason needs a tampered packet date, so it gets its own
    cohort copy; the run must still complete."""
    import shutil

    from dynamic_ai_products.ingestion.baseline_packet import (
        PACKET_MANIFEST_FILENAME, PACKETS_FILENAME)

    run_dir = tmp_path / "cohort"
    shutil.copytree(big.run_dir, run_dir)
    target = run_dir / PACKETS_FILENAME
    rows = [json.loads(x) for x in
            target.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows[3]["baseline_filing_date"] = "2031-01-01"
    target.write_text("".join(
        json.dumps(r, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")) + "\n" for r in rows),
        encoding="utf-8")
    manifest_path = run_dir / PACKET_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_hashes"][PACKETS_FILENAME] = sha256(
        target.read_bytes()).hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    from types import SimpleNamespace
    cohort = SimpleNamespace(
        manifest_path=manifest_path, run_dir=run_dir, packets=rows,
        failures=big.failures,
        manifest_sha256=sha256(manifest_path.read_bytes()).hexdigest())
    selection_path, governance = _canary_setup(cohort, tmp_path)
    result, _ = _diagnostic(cohort, tmp_path, selection_path=selection_path,
                            governance=governance, logical=100)
    assert result.status == "completed"
    assert result.rejections_by_reason["temporal_violation"] >= 1
    assert result.validated + result.rejected == 100


def test_mixed_rejections_reconcile(big, tmp_path):
    selection_path, governance = _canary_setup(big, tmp_path)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    script = _script_for(big.packets)
    plan = {}
    for offset, reason in enumerate(
            ["invalid_model_json", "adapter_rejection",
             "quote_resolution_failure", "adapter_rejection"]):
        cik = selection["rows"][offset * 7]["cik"]
        packet = next(p for p in big.packets if p["cik"] == cik)
        script[cik]["text"] = _bad(packet, reason)
        plan[cik] = reason
    result, _ = _diagnostic(big, tmp_path, selection_path=selection_path,
                            governance=governance, logical=100, script=script)
    assert result.status == "completed"
    assert result.rejected == 4 and result.validated == 96
    assert result.rejections_by_reason == {
        "invalid_model_json": 1, "adapter_rejection": 2,
        "quote_resolution_failure": 1, "temporal_violation": 0}
    records = _records(result)
    by_cik = {r["cik"]: r for r in records}
    for cik, reason in plan.items():
        assert by_cik[cik]["record_kind"] == "rejected_output"
        assert by_cik[cik]["rejection_reason_code"] == reason
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    c = manifest["counts"]
    assert c["validated"] + c["rejected"] == c["rows_selected"] == 100
    assert sum(c["rejections_by_reason"].values()) == c["rejected"]
    assert sum(c["by_screen_status"].values()) == c["validated"]
    assert manifest["request_accounting"]["cost_micros_settled"] == sum(
        r["cost_micros"] for r in records)


def test_record_order_and_ordinals_follow_the_selection(big, tmp_path):
    selection_path, governance = _canary_setup(big, tmp_path)
    result, _ = _diagnostic(big, tmp_path, selection_path=selection_path,
                            governance=governance, logical=100)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    records = _records(result)
    assert [(r["cik"], r["accession"]) for r in records] == \
        [(r["cik"], r["accession"]) for r in selection["rows"]]
    assert [r["row_ordinal"] for r in records] == list(range(1, 101))


# --- The circuit breaker ----------------------------------------------------------------


def test_max_rejected_rows_breaker_hard_stops(big, tmp_path):
    selection_path, governance = _canary_setup(big, tmp_path, max_rejected=3)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    script = _script_for(big.packets)
    for row in selection["rows"][:6]:
        packet = next(p for p in big.packets if p["cik"] == row["cik"])
        script[row["cik"]]["text"] = _bad(packet, "adapter_rejection")
    result, factory = _diagnostic(big, tmp_path, selection_path=selection_path,
                                  governance=governance, logical=100,
                                  script=script)
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "rejected_row_budget_exhausted"
    # Rows 1-3 rejected are tolerated; the 4th trips the breaker.
    assert receipt["rejected_rows"] == 4
    assert receipt["max_rejected_rows"] == 3
    # The triggering row is row 4 itself, not the row after it: unlike a
    # provider or envelope stop, the breaker fires only once the row has
    # been validated, archived and counted, so rows 1-3 are what completed.
    assert receipt["stopping_row_index"] == 4
    assert receipt["records_completed_before_failure"] == 3
    # It was nevertheless measured and archived, which is why the rejected
    # count and the archive both read 4.
    assert receipt["raw_responses_captured"] == 4
    assert factory.generate_calls == 4  # no send after the stop
    assert not (result.run_dir / ld.DIAGNOSTIC_RECORDS_FILENAME).exists()
    assert not (result.run_dir / ld.DIAGNOSTIC_MANIFEST_FILENAME).exists()
    assert not (result.run_dir / ll.CAPTURE_LEDGER_FILENAME).exists()
    # The measurement so far is retained as raw evidence.
    assert len((result.run_dir / ls.RAW_RESPONSES_FILENAME).read_text(
        encoding="utf-8").splitlines()) == 4
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        ld.require_diagnostic_run(result.run_dir)


def test_breaker_must_be_able_to_trip(big, tmp_path):
    selection_path = _selection(big, tmp_path, "canary_100", seed=7)
    governance = _diagnostic_governance(tmp_path, cohort=big,
                                        selection_path=selection_path,
                                        logical=100, max_rejected=101)
    with pytest.raises(ls.ScreenInputError, match="never trip"):
        _diagnostic(big, tmp_path, selection_path=selection_path,
                    governance=governance, logical=100)
    assert not (tmp_path / "diagnostic").exists()


# --- Hard stops stay hard ----------------------------------------------------------------


@pytest.mark.parametrize("name,envelope", [
    ("blocked", {"promptFeedback": {"blockReason": "SAFETY"},
                 "candidates": [{"content": {"parts": [{"text": "x"}]}}]}),
    ("empty_candidates", {"candidates": []}),
    ("two_candidates", {"candidates": [
        {"content": {"parts": [{"text": "a"}]}},
        {"content": {"parts": [{"text": "b"}]}}]}),
    ("part_less", {"candidates": [{"content": {"parts": []}}]}),
    ("malformed", b"this is not json"),
])
def test_envelope_failures_are_hard_stops_not_rejections(
        big, tmp_path, name, envelope):
    """Envelope defects are transport-contract failures, never model-output
    content, so they end the run exactly as on the authoritative path."""
    selection_path, governance = _canary_setup(big, tmp_path)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    cik = selection["rows"][2]["cik"]
    script = _script_for(big.packets)
    script[cik]["envelope"] = envelope
    result, factory = _diagnostic(big, tmp_path, selection_path=selection_path,
                                  governance=governance, logical=100,
                                  script=script, run_id=f"env-{name[:10]}")
    assert result.status == "failed"
    assert result.receipt["reason_code"] == "provider_error"
    assert result.receipt["stopping_row_index"] == 3
    assert result.receipt["records_completed_before_failure"] == 2
    assert factory.generate_calls == 3
    assert not (result.run_dir / ld.DIAGNOSTIC_MANIFEST_FILENAME).exists()
    assert not (result.run_dir / ld.DIAGNOSTIC_RECORDS_FILENAME).exists()


def test_provider_terminal_and_retry_exhaustion_hard_stop(big, tmp_path):
    selection_path, governance = _canary_setup(big, tmp_path)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    for name, mutate in (
        # A provider-side failure the fake transport raises for real: the
        # scripted entry is absent, so the SDK call itself throws and the
        # connector translates it into a provider error.
        ("terminal", lambda s, cik: s.pop(cik)),
        ("exhaustion", lambda s, cik: s[cik].update(transient_failures=3)),
    ):
        script = _script_for(big.packets)
        mutate(script, selection["rows"][1]["cik"])
        result, _ = _diagnostic(big, tmp_path, selection_path=selection_path,
                                governance=governance, logical=100,
                                script=script, run_id=f"hs-{name}")
        assert result.status == "failed", name
        assert result.receipt["reason_code"] == "provider_error", name
        assert result.receipt["stopping_row_index"] == 2, name
        assert not (result.run_dir / ld.DIAGNOSTIC_MANIFEST_FILENAME).exists()


def test_budget_and_cap_failures_hard_stop(big, tmp_path):
    selection_path = _selection(big, tmp_path, "canary_100", seed=7)
    governance = _diagnostic_governance(
        tmp_path, cohort=big, selection_path=selection_path, logical=100,
        mutate_authorization=lambda a: a.update(budget_max_input_tokens=100))
    result, _ = _diagnostic(big, tmp_path, selection_path=selection_path,
                            governance=governance, logical=100)
    assert result.status == "failed"
    assert result.receipt["reason_code"] == "provider_error"
    assert "input-token budget" in result.receipt["detail"]
    # Cap arithmetic is refused before any output exists.
    for kwargs, match in (({"logical": 99}, "logical_request_cap"),
                          ({"attempts": 5}, "provider_attempt_cap")):
        with pytest.raises(ls.ScreenInputError, match=match):
            _diagnostic(big, tmp_path / "capfail", selection_path=selection_path,
                        governance=governance, **kwargs)


def test_governance_failures_refuse_before_output_or_network(big, tmp_path):
    selection_path = _selection(big, tmp_path, "canary_100", seed=7)
    cases = {
        "digest": (dict(), "hashes to", "bad-digest"),
        "prompt": (dict(prompt_sha256="7" * 64), "prompt", None),
        "expiry": (dict(mutate_authorization=lambda a: a.update(
            expires_at="2026-08-02T00:00:00+00:00")), "window", None),
        "contract": (dict(mutate_authorization=lambda a: a.update(
            provider_client_contract_sha256="2" * 64)), "contract", None),
        "endpoints": (dict(mutate_enablement=lambda e: e.update(
            endpoint_allowlist=[e["endpoint_allowlist"][0],
                                "https://example.com/v1/x:predict"])),
            "operation endpoints", None),
    }
    for name, (kwargs, match, forge) in cases.items():
        base = tmp_path / name
        governance = _diagnostic_governance(base, cohort=big,
                                            selection_path=selection_path,
                                            logical=100, **kwargs)
        if forge:
            governance.sha256 = "0" * 64
        with pytest.raises(ls.ScreenInputError, match=match):
            _diagnostic(big, base, selection_path=selection_path,
                        governance=governance, logical=100)
        assert not (base / "diagnostic").exists(), name
    _assert_no_google_import()


def test_a_live_authorization_cannot_authorize_diagnostic_collection(
        big, tmp_path):
    """The whole point of a separate contract: an authorization minted for
    authoritative screening is refused here, and vice versa."""
    from test_lineage_screen_live import _governance as _live_governance

    selection_path = _selection(big, tmp_path, "canary_100", seed=7)
    live_gov = _live_governance(tmp_path / "live", cohort=big,
                                selection_path=selection_path,
                                selection_kind="canary_100", logical=100)
    with pytest.raises(ls.ScreenInputError, match="contract|violates"):
        _diagnostic(big, tmp_path / "live", selection_path=selection_path,
                    governance=live_gov, logical=100)
    assert not (tmp_path / "live" / "diagnostic").exists()

    # And the authoritative runner refuses a diagnostic authorization.
    from test_lineage_screen_live import _live as _live_run

    diag_gov = _diagnostic_governance(tmp_path / "diag", cohort=big,
                                      selection_path=selection_path,
                                      logical=100)
    with pytest.raises(ls.ScreenInputError, match="contract|violates"):
        _live_run(big, tmp_path / "diag", selection_path=selection_path,
                  governance=diag_gov, logical=100)
    _assert_no_google_import()


def test_full_cohort_selection_is_refused(small, tmp_path):
    selection_path = _selection(small, tmp_path, "full_cohort")
    governance = _diagnostic_governance(
        tmp_path, cohort=small, selection_path=selection_path, logical=3,
        max_rejected=1,
        mutate_authorization=lambda a: a.update(selection_kind="full_cohort"))
    # The schema pins selection_kind to canary_100, so this dies at validation.
    with pytest.raises(ls.ScreenInputError, match="canary_100|violates"):
        _diagnostic(small, tmp_path, selection_path=selection_path,
                    governance=governance, logical=3)
    assert not (tmp_path / "diagnostic").exists()


# --- Authority isolation --------------------------------------------------------------------


def test_a_diagnostic_run_is_structurally_non_promotable(big, tmp_path):
    selection_path, governance = _canary_setup(big, tmp_path)
    result, _ = _diagnostic(big, tmp_path, selection_path=selection_path,
                            governance=governance, logical=100)
    assert result.status == "completed"
    # Its own loader accepts it.
    assert ld.require_diagnostic_run(result.run_dir)
    # Every authoritative loader refuses it, without any code change: they
    # look for universe_screen_manifest.json and find none.
    with pytest.raises(ls.ScreenInputError, match="no manifest"):
        ls.require_authoritative_screen_run(result.run_dir)
    with pytest.raises(ls.ScreenInputError, match="no manifest"):
        ll.require_promotable_screen_run(result.run_dir)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["diagnostic_only"] is True
    assert manifest["promotable"] is False
    assert manifest["run_kind"] == "diagnostic_canary"
    assert manifest["selection"]["selection_kind"] == "canary_100"
    # The manifest generations mutually reject.
    assert list(Draft202012Validator(
        LIVE_MANIFEST_V4_SCHEMA, format_checker=FormatChecker()
    ).iter_errors(manifest))
    live_shaped = {"prompt_template_path": manifest["prompt_template_path"]}
    assert list(Draft202012Validator(
        MANIFEST_SCHEMA, format_checker=FormatChecker()
    ).iter_errors(live_shaped))
    # A diagnostic record is not a screen record.
    screen_record_schema = json.loads(
        (ROOT / "schemas" / "universe_screen_record.schema.json")
        .read_text(encoding="utf-8"))
    record = _records(result)[0]
    assert list(Draft202012Validator(
        screen_record_schema, format_checker=FormatChecker()
    ).iter_errors(record))


def test_the_diagnostic_loader_refuses_foreign_and_tampered_runs(
        big, small, tmp_path):
    from test_lineage_screen_live import _full_setup, _live as _live_run

    selection_path, governance = _canary_setup(big, tmp_path)
    result, _ = _diagnostic(big, tmp_path, selection_path=selection_path,
                            governance=governance, logical=100)
    # An authoritative run is refused by the diagnostic loader.
    live_sel, live_gov = _full_setup(small, tmp_path / "auth")
    live = _live_run(small, tmp_path / "auth", selection_path=live_sel,
                     governance=live_gov)[0]
    with pytest.raises(ls.ScreenInputError, match="authoritative"):
        ld.require_diagnostic_run(live.run_dir)
    # A manifest-less directory is refused.
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(ls.ScreenInputError, match="no diagnostic manifest"):
        ld.require_diagnostic_run(bare)
    # Tampered output bytes are refused.
    target = result.run_dir / ld.DIAGNOSTIC_RECORDS_FILENAME
    original = target.read_bytes()
    target.write_bytes(original[:-2] + b"X\n")
    with pytest.raises(ls.ScreenInputError, match="hashes to"):
        ld.require_diagnostic_run(result.run_dir)
    target.write_bytes(original)
    assert ld.require_diagnostic_run(result.run_dir)


# --- Raw/capture integrity, determinism, dry run ----------------------------------------------


def test_raw_and_capture_integrity_including_rejected_rows(big, tmp_path):
    selection_path, governance = _canary_setup(big, tmp_path)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    cik = selection["rows"][5]["cik"]
    packet = next(p for p in big.packets if p["cik"] == cik)
    script = _script_for(big.packets)
    script[cik]["text"] = _bad(packet, "quote_resolution_failure")
    result, _ = _diagnostic(big, tmp_path, selection_path=selection_path,
                            governance=governance, logical=100, script=script)
    assert result.status == "completed"
    archive = {e["raw_response_id"]: e for e in (
        json.loads(x) for x in (result.run_dir / ls.RAW_RESPONSES_FILENAME)
        .read_text(encoding="utf-8").splitlines() if x.strip())}
    assert len(archive) == 100
    records = _records(result)
    for record in records:
        entry = archive[record["raw_response_id"]]
        assert sha256(entry["raw_response"].encode("utf-8")).hexdigest() \
            == entry["raw_response_sha256"] == record["raw_response_sha256"]
    # The rejected row's full invalid payload is in the archive, not the record.
    rejected = next(r for r in records if r["record_kind"] == "rejected_output")
    raw = archive[rejected["raw_response_id"]]["raw_response"]
    assert "text present in no passage" in raw
    assert "text present in no passage" not in json.dumps(rejected)
    ledger = [json.loads(x) for x in
              (result.run_dir / ll.CAPTURE_LEDGER_FILENAME)
              .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(ledger) == 200
    for entry in ledger:
        assert entry["capture_disposition"] == "raw_persisted"
        assert sha256((result.run_dir / entry["raw_reference"]).read_bytes()
                      ).hexdigest() == entry["raw_sha256"]
    on_disk = {str(p.relative_to(result.run_dir)) for p in
               (result.run_dir / ll.CAPTURES_DIRNAME).rglob("*") if p.is_file()}
    assert on_disk == {e["raw_reference"] for e in ledger}


def test_determinism_dry_run_and_write_once(big, tmp_path):
    selection_path, governance = _canary_setup(big, tmp_path)
    dry, factory = _diagnostic(big, tmp_path, selection_path=selection_path,
                               governance=governance, logical=100, dry_run=True)
    assert dry.status == "dry_run" and dry.run_dir is None
    assert factory.opens == 0
    assert not (tmp_path / "diagnostic").exists()

    one, _ = _diagnostic(big, tmp_path / "a", selection_path=selection_path,
                         governance=governance, logical=100, run_id="same")
    two, _ = _diagnostic(big, tmp_path / "b", selection_path=selection_path,
                         governance=governance, logical=100, run_id="same")
    for filename in (ld.DIAGNOSTIC_RECORDS_FILENAME, ls.RAW_RESPONSES_FILENAME,
                     ll.CAPTURE_LEDGER_FILENAME):
        assert (one.run_dir / filename).read_bytes() == \
            (two.run_dir / filename).read_bytes()
    assert one.manifest_path.read_bytes() == two.manifest_path.read_bytes()
    with pytest.raises(FileExistsError):
        _diagnostic(big, tmp_path / "a", selection_path=selection_path,
                    governance=governance, logical=100, run_id="same")


# --- Validator parity ---------------------------------------------------------------------------


def test_validator_parity_same_payload_two_policies(big, tmp_path):
    """The identical payload the authoritative runner hard-stops on becomes a
    recorded rejection here. One validator, two policies."""
    from test_lineage_screen_live import _governance as _live_governance
    from test_lineage_screen_live import _live as _live_run

    selection_path = _selection(big, tmp_path, "canary_100", seed=7)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    cik = selection["rows"][0]["cik"]
    packet = next(p for p in big.packets if p["cik"] == cik)
    script = _script_for(big.packets)
    script[cik]["text"] = _bad(packet, "adapter_rejection")

    live_gov = _live_governance(tmp_path / "auth", cohort=big,
                                selection_path=selection_path,
                                selection_kind="canary_100", logical=100)
    live = _live_run(big, tmp_path / "auth", selection_path=selection_path,
                     governance=live_gov, logical=100, script=script)[0]
    assert live.status == "failed"
    assert live.receipt["reason_code"] == "adapter_rejection"
    assert live.receipt["stopping_row_index"] == 1

    diag_gov = _diagnostic_governance(tmp_path / "diag", cohort=big,
                                      selection_path=selection_path,
                                      logical=100)
    diag, _ = _diagnostic(big, tmp_path / "diag", selection_path=selection_path,
                          governance=diag_gov, logical=100, script=script)
    assert diag.status == "completed"
    assert diag.rejected == 1 and diag.validated == 99
    assert _records(diag)[0]["rejection_reason_code"] == "adapter_rejection"
    # The out-of-vocabulary archetype is still refused by the closed contract.
    assert "Productivity/Efficiency" not in ARCHETYPES


def test_the_diagnostic_module_never_relaxes_the_validator():
    """The rejection vocabulary is exactly the validator's, and the runner
    imports the validator rather than re-implementing it."""
    import ast

    source = (ROOT / "src" / "dynamic_ai_products"
              / "lineage_screen_diagnostic.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert "_validate_row_output" in imported
    assert "def _validate_row_output" not in source
    assert set(ld.REJECTION_REASON_CODES) == {
        "invalid_model_json", "adapter_rejection",
        "quote_resolution_failure", "temporal_violation"}
    # The hard-stop and continue vocabularies are disjoint.
    assert not set(ld.RECEIPT_REASON_CODES) & set(ld.REJECTION_REASON_CODES)


def test_fresh_process_preflight_never_imports_google(tmp_path):
    script = (
        "import sys\n"
        "from datetime import datetime, timezone\n"
        "from dynamic_ai_products import lineage_screen_diagnostic as ld\n"
        "from dynamic_ai_products.universe.lineage_screen import ScreenInputError\n"
        "try:\n"
        "    ld.run_lineage_screen_diagnostic(\n"
        f"        repo_root={str(ROOT)!r},\n"
        f"        packet_manifest_path={str(tmp_path / 'none.json')!r},\n"
        f"        selection_artifact_path={str(tmp_path / 'none.json')!r},\n"
        f"        governance_root={str(tmp_path)!r},\n"
        "        authorization_reference='ghost.json',\n"
        "        authorization_sha256='0' * 64,\n"
        f"        output_dir={str(tmp_path / 'out')!r},\n"
        "        run_id='fresh', logical_request_cap=1, provider_attempt_cap=3,\n"
        "        clock=lambda: datetime.now(timezone.utc))\n"
        "except ScreenInputError:\n"
        "    pass\n"
        "else:\n"
        "    raise AssertionError('the ghost authorization was not refused')\n"
        "assert not any(m == 'google' or m.startswith('google.')\n"
        "               for m in sys.modules), 'google was imported'\n"
        "print('NO-GOOGLE-OK')\n"
    )
    completed = subprocess.run([sys.executable, "-c", script],
                               capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
    assert "NO-GOOGLE-OK" in completed.stdout
    assert not (tmp_path / "out").exists()


# --- CLI ------------------------------------------------------------------------------------------


def _cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, check=False)


def test_cli_diagnostic_mode_requires_all_flags(tmp_path):
    completed = _cli("--mode", "screen-universe-lineage-diagnostic",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    for flag in ("--packet-manifest", "--selection-artifact",
                 "--governance-root", "--screen-authorization",
                 "--screen-authorization-sha256", "--logical-request-cap",
                 "--provider-attempt-cap"):
        assert flag in completed.stderr
    assert not (tmp_path / "o").exists()


def test_cli_diagnostic_dry_run_and_refusal(big, tmp_path):
    selection_path, governance = _canary_setup(big, tmp_path)
    base = ["--mode", "screen-universe-lineage-diagnostic",
            "--packet-manifest", str(big.manifest_path),
            "--selection-artifact", str(selection_path),
            "--governance-root", str(governance.root),
            "--screen-authorization", governance.reference,
            "--logical-request-cap", "100", "--provider-attempt-cap", "300",
            "--output-dir", str(tmp_path / "out")]
    ok = _cli(*base, "--screen-authorization-sha256", governance.sha256,
              "--run-id", "cli-dry", "--dry-run")
    assert ok.returncode == 0, ok.stderr
    assert json.loads(ok.stdout)["status"] == "dry_run"
    assert not (tmp_path / "out").exists()
    bad = _cli(*base, "--screen-authorization-sha256", "0" * 64,
               "--run-id", "cli-bad")
    assert bad.returncode == 2
    assert "hashes to" in bad.stderr
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("flag,value", [
    ("--provider", "mock"), ("--screen-fixture", "f.json"),
    ("--config", "c.yaml"), ("--bundle-dir", "b"),
    ("--selection-seed", "3"), ("--selection-kind", "canary_100"),
])
def test_cli_diagnostic_mode_refuses_irrelevant_flags(tmp_path, flag, value):
    completed = _cli("--mode", "screen-universe-lineage-diagnostic", flag, value,
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert flag in completed.stderr and "does not accept" in completed.stderr
    assert not (tmp_path / "o").exists()


_OTHER_MODES = [
    "sentinel", "frame", "acquire-index", "dera-validate", "acquire-dera",
    "baseline-carrier", "acquire-docs", "probe-filing-index",
    "build-baseline-packets", "acquire-primary-docs",
    "determine-shell-company", "determine-shell-company-lineage",
    "determine-asset-backed-issuer-lineage",
    "build-baseline-packets-lineage", "build-baseline-packets-lineage-v2",
    "plan-acquisition-queue", "execute-acquisition-queue",
    "aggregate-acquisition-queue", "aggregate-acquisition-lineage",
    "screen-universe-lineage", "select-screen-rows",
]


@pytest.mark.parametrize("mode", _OTHER_MODES)
def test_every_other_mode_still_refuses_the_governance_flags(tmp_path, mode):
    completed = _cli("--mode", mode, "--governance-root", "g",
                     "--screen-authorization", "a.json",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr
    assert not (tmp_path / "o").exists()


# --- Predecessor pins and registry -----------------------------------------------------------------


def test_authoritative_predecessors_are_byte_identical():
    """ADR-112 leaves the sentinel screen path that diagnostics depend on unchanged."""
    pins = {
        "src/dynamic_ai_products/universe/lineage_screen.py":
            "6bc2ae464c8c7d5ae7e16a24940db9e2849e60be692e32be81ce344e9cf8d77c",
    }
    for path, expected in pins.items():
        actual = sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual == expected, f"{path} moved: {actual}"


def test_registry_registers_the_three_diagnostic_schemas():
    registry = json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json")
        .read_text(encoding="utf-8"))
    assert registry["manifest_version"] == "0.66.0"
    assert len(registry["schemas"]) == 150
    for key in ("universe_screen_diagnostic_record",
                "universe_screen_diagnostic_manifest",
                "universe_screen_diagnostic_authorization"):
        assert registry["schemas"][key] == "0.1.0"


def test_the_diagnostic_authorization_carries_every_live_binding():
    """A diagnostic authorization binds everything the live one does, so
    nothing is governed less tightly — only differently labelled."""
    live = json.loads((ROOT / "schemas"
                       / "universe_screen_live_authorization.schema.json")
                      .read_text(encoding="utf-8"))
    assert set(live["properties"]) <= set(AUTHORIZATION_SCHEMA["properties"])
    assert set(live["required"]) <= set(AUTHORIZATION_SCHEMA["required"])
    p = AUTHORIZATION_SCHEMA["properties"]
    assert p["authorization_contract"]["const"] == \
        "universe_screen_diagnostic_authorization@0.1.0"
    assert p["run_kind"]["const"] == "diagnostic_canary"
    assert p["diagnostic_only"]["const"] is True
    assert p["promotable"]["const"] is False
    assert p["selection_kind"]["const"] == "canary_100"
    assert "max_rejected_rows" in AUTHORIZATION_SCHEMA["required"]
    assert AUTHORIZATION_SCHEMA["additionalProperties"] is False
