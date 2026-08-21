"""ADR-115 seven-row diagnostic repair tests — fully offline, fake-client only.

The cohort builders, fake Vertex transport, canary selection and diagnostic
governance helpers are imported from the ADR-112/113/114 suites rather than
duplicated: a repair run's source population *is* a completed diagnostic run,
so the fixture here is the real thing — a 100-row fake-transport diagnostic
run with exactly seven scripted ``quote_resolution_failure`` rejections at
the same ordinals the live v4 canary produced (13, 22, 24, 26, 30, 48, 53).
Nothing is hand-typed: the selection under test is derived from that run's
hash-bound records, exactly as production derivation will be.

No real ``genai.Client`` is built, no credential is resolved, no socket is
opened, and the fresh-subprocess test proves ``google.*`` never loads.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import lineage_screen_diagnostic as ld
from dynamic_ai_products import lineage_screen_diagnostic_repair as lr
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_lineage_screen_diagnostic import (  # noqa: E402
    _bad,
    _canary_setup,
    _diagnostic,
    _v5_evidence_payload,
)
from test_lineage_screen_live import (  # noqa: E402
    PACKET_FIXTURES,
    ROOT,
    _contract_digest,
    _endpoints,
    _FakeFactory,
    _fixture_doc,
    _script_for,
    _v5_run,
)

CLI = ROOT / "pipelines" / "00_build_company_universe.py"

REPAIR_SELECTION_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_diagnostic_repair_selection.schema.json")
    .read_text(encoding="utf-8"))
REPAIR_MANIFEST_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_diagnostic_repair_manifest.schema.json")
    .read_text(encoding="utf-8"))
REPAIR_AUTHORIZATION_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_diagnostic_repair_authorization.schema.json")
    .read_text(encoding="utf-8"))
RECORD_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_diagnostic_record.schema.json")
    .read_text(encoding="utf-8"))

VERTEX_PROJECT = "test-vertex-project"
VERTEX_LOCATION = "us-central1"

#: The same ordinals the live v4 canary rejected; the fixture reproduces
#: them so the derivation under test walks the real shape.
SOURCE_REJECTED_ORDINALS = [13, 22, 24, 26, 30, 48, 53]

FIXED_CLOCK = lambda: datetime(2026, 8, 20, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731


# --- No-SDK guard (module-local baseline; see the diagnostic suite) ---------------

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
    assert not added, f"the repair path imported google modules: {sorted(added)}"


# --- The source diagnostic run: the real population, built once -------------------


@pytest.fixture(scope="module")
def source(tmp_path_factory):
    """A completed 100-row diagnostic run with exactly seven
    quote_resolution_failure rejections at the canonical ordinals."""
    tmp = tmp_path_factory.mktemp("repair-source")
    origin, template = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    docs = [
        (origin, dict(template, cik=f"{9100000000 + index:010d}",
                      accession=f"{9100000000 + index:010d}-22-000001"))
        for index in range(104)
    ]
    docs.append(_fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"))
    cohort = _v5_run(tmp, [docs])
    assert len(cohort.packets) == 104

    selection_path, governance = _canary_setup(cohort, tmp, max_rejected=25)
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    packets_by_cik = {p["cik"]: p for p in cohort.packets}
    script = _script_for(cohort.packets)
    expected = []
    for ordinal in SOURCE_REJECTED_ORDINALS:
        row = selection["rows"][ordinal - 1]
        packet = packets_by_cik[row["cik"]]
        script[row["cik"]]["text"] = _bad(packet, "quote_resolution_failure")
        expected.append({
            "source_row_ordinal": ordinal,
            "cik": row["cik"],
            "accession": row["accession"],
            "packet_sha256": packet["packet_sha256"],
        })
    result, _ = _diagnostic(cohort, tmp, selection_path=selection_path,
                            governance=governance, logical=100, script=script,
                            run_id="source-run")
    assert result.status == "completed", result.receipt
    assert result.validated == 93 and result.rejected == 7
    assert result.rejections_by_reason["quote_resolution_failure"] == 7
    return SimpleNamespace(cohort=cohort, run_dir=result.run_dir,
                           manifest_path=result.manifest_path,
                           expected=expected)


# --- Repair helpers ---------------------------------------------------------------


def _build_selection(source, tmp_path: Path, *, run_id: str = "repair-sel",
                     source_manifest_path=None, cohort=None,
                     dry_run: bool = False):
    return lr.build_repair_selection(
        repo_root=ROOT,
        source_diagnostic_manifest_path=(
            source_manifest_path if source_manifest_path is not None
            else source.manifest_path),
        packet_manifest_path=(cohort or source.cohort).manifest_path,
        output_dir=tmp_path / "repair-selections",
        run_id=run_id,
        clock=FIXED_CLOCK,
        dry_run=dry_run,
    )


def _repair_governance(tmp_path: Path, *, cohort, selection_path: Path,
                       max_rejected: int = 3,
                       mutate_authorization=None, mutate_enablement=None,
                       prompt_sha256: str | None = None):
    """A valid repair enablement + authorization pair; optionally tampered."""
    from dynamic_ai_products.providers.client_contract_v2 import (
        CLIENT_CONTRACT_V2_ID)
    from dynamic_ai_products.providers.retry_policy import (
        RATE_LIMIT_POLICY_VERSION, RETRY_POLICY_VERSION)

    root = tmp_path / "repair-governance"
    root.mkdir(parents=True, exist_ok=True)
    endpoints, digest = _endpoints(), _contract_digest()
    enablement = {
        "enablement_contract": "universe_screen_adapter_enablement@0.1.0",
        "enablement_id": "repair-enablement-fixture",
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
        (ROOT / ld.DIAGNOSTIC_PROMPT_TEMPLATE_RELATIVE_PATH).read_bytes()
    ).hexdigest()
    authorization = {
        "authorization_contract":
            "universe_screen_diagnostic_repair_authorization@0.1.0",
        "authorization_id": "repair-authorization-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": "controlled_pilot",
        "screen_stage": "universe_high_recall_screen",
        "run_kind": "diagnostic_repair_7",
        "diagnostic_only": True,
        "promotable": False,
        "output_contract": "universe_screen_diagnostic_record@0.1.0",
        "packet_manifest_sha256": cohort.manifest_sha256,
        "prompt_template_sha256": (
            prompt_sha256 if prompt_sha256 is not None else template_sha),
        "selection_artifact_sha256": sha256(
            selection_path.read_bytes()).hexdigest(),
        "selection_kind": "repair_7",
        "screen_adapter_enablement_reference": "screen_adapter_enablement.json",
        "screen_adapter_enablement_sha256": sha256(enablement_raw).hexdigest(),
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": digest,
        "vertex_project": VERTEX_PROJECT,
        "vertex_location": VERTEX_LOCATION,
        "model_route": {"provider": "google_vertex_ai",
                        "model_label": "gemini-2.5-flash"},
        "endpoint_allowlist": endpoints,
        "logical_request_cap": 7,
        "provider_attempt_cap": 21,
        "budget_max_external_requests": 28,
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
    (root / "screen_diagnostic_repair_authorization.json").write_bytes(
        authorization_raw)
    return SimpleNamespace(
        root=root,
        reference="screen_diagnostic_repair_authorization.json",
        sha256=sha256(authorization_raw).hexdigest(),
        authorization=authorization)


def _repair(source, tmp_path: Path, *, selection_path, governance,
            script=None, run_id="repair", logical=7, attempts=None,
            dry_run=False, cohort=None):
    cohort = cohort or source.cohort
    factory = _FakeFactory(script if script is not None
                           else _script_for(cohort.packets))
    result = lr.run_lineage_screen_diagnostic_repair(
        repo_root=ROOT,
        packet_manifest_path=cohort.manifest_path,
        selection_artifact_path=selection_path,
        governance_root=governance.root,
        authorization_reference=governance.reference,
        authorization_sha256=governance.sha256,
        output_dir=tmp_path / "repair",
        run_id=run_id,
        logical_request_cap=logical,
        provider_attempt_cap=(21 if attempts is None else attempts),
        clock=FIXED_CLOCK,
        dry_run=dry_run,
        client_factory=factory,
    )
    return result, factory


def _repair_setup(source, tmp_path: Path, **kwargs):
    selection_path = _build_selection(source, tmp_path).manifest_path
    governance = _repair_governance(tmp_path, cohort=source.cohort,
                                    selection_path=selection_path, **kwargs)
    return selection_path, governance


def _records(result) -> list[dict]:
    return [json.loads(line) for line in
            (result.run_dir / lr.REPAIR_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if line.strip()]


def _doctored_source(source, tmp_path: Path, *, mutate_rows=None,
                     mutate_manifest=None) -> Path:
    """Copy the source run and tamper it, repairing the output hashes so the
    tamper is a semantic forgery rather than a trivially detectable one."""
    run_dir = tmp_path / "src-copy"
    shutil.copytree(source.run_dir, run_dir)
    records_path = run_dir / ld.DIAGNOSTIC_RECORDS_FILENAME
    if mutate_rows is not None:
        rows = [json.loads(x) for x in
                records_path.read_text(encoding="utf-8").splitlines()
                if x.strip()]
        rows = mutate_rows(rows)
        records_path.write_text("".join(
            json.dumps(r, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")) + "\n" for r in rows),
            encoding="utf-8")
    manifest_path = run_dir / ld.DIAGNOSTIC_MANIFEST_FILENAME
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["output_hashes"][ld.DIAGNOSTIC_RECORDS_FILENAME] = sha256(
        records_path.read_bytes()).hexdigest()
    if mutate_manifest is not None:
        mutate_manifest(manifest)
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    return manifest_path


def _flip_reason(rows):
    for r in rows:
        if r["record_kind"] == "rejected_output":
            r["rejection_reason_code"] = "adapter_rejection"
            break
    return rows


# --- Selection derivation ----------------------------------------------------------


def test_selection_derives_exactly_the_seven_source_rejections(source, tmp_path):
    result = _build_selection(source, tmp_path)
    assert result.status == "completed"
    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(
        REPAIR_SELECTION_SCHEMA, format_checker=FormatChecker()
    ).iter_errors(payload)) == []
    assert payload["selection_kind"] == "repair_7"
    assert payload["derivation_rule"] == lr.DERIVATION_RULE
    # Exactly the seven source rejections, ascending by source ordinal, with
    # per-row eligibility proof — and nothing hand-typed anywhere.
    assert [r["source_row_ordinal"] for r in payload["rows"]] == \
        SOURCE_REJECTED_ORDINALS
    for row, expected in zip(payload["rows"], source.expected):
        assert row["cik"] == expected["cik"]
        assert row["accession"] == expected["accession"]
        assert row["packet_sha256"] == expected["packet_sha256"]
        assert row["source_record_kind"] == "rejected_output"
        assert row["source_rejection_reason_code"] == "quote_resolution_failure"
    # Source and cohort are bound by bytes, not by trust.
    assert payload["source_diagnostic_manifest_sha256"] == sha256(
        source.manifest_path.read_bytes()).hexdigest()
    assert payload["source_records_jsonl_sha256"] == sha256(
        (source.run_dir / ld.DIAGNOSTIC_RECORDS_FILENAME).read_bytes()
    ).hexdigest()
    assert payload["packet_manifest_sha256"] == source.cohort.manifest_sha256
    assert payload["counts"] == {
        "source_rows_total": 100, "source_rejected_total": 7,
        "source_rejected_quote_resolution": 7, "rows_selected": 7}
    # Write-once and dry-run discipline.
    with pytest.raises(FileExistsError):
        _build_selection(source, tmp_path)
    dry = _build_selection(source, tmp_path, run_id="dry", dry_run=True)
    assert dry.status == "dry_run" and dry.run_dir is None
    assert not (tmp_path / "repair-selections" / "dry").exists()
    _assert_no_google_import()


def test_selection_refuses_receipt_tampered_or_foreign_sources(source, tmp_path):
    # A receipt-bearing source is incomplete and refused.
    receipted = tmp_path / "receipted"
    shutil.copytree(source.run_dir, receipted)
    (receipted / ls.FAILURE_RECEIPT_FILENAME).write_text("{}", encoding="utf-8")
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        _build_selection(source, tmp_path, run_id="a",
                         source_manifest_path=receipted / ld.DIAGNOSTIC_MANIFEST_FILENAME)
    # A byte-flipped records file no longer hashes to its manifest entry.
    flipped = tmp_path / "flipped"
    shutil.copytree(source.run_dir, flipped)
    target = flipped / ld.DIAGNOSTIC_RECORDS_FILENAME
    raw = target.read_bytes()
    target.write_bytes(raw[:-2] + b"X\n")
    with pytest.raises(ls.ScreenInputError, match="hashes to"):
        _build_selection(source, tmp_path, run_id="b",
                         source_manifest_path=flipped / ld.DIAGNOSTIC_MANIFEST_FILENAME)
    # A foreign contract is not a diagnostic run.
    foreign = _doctored_source(source, tmp_path / "f",
                               mutate_manifest=lambda m: m.update(
                                   manifest_contract="something_else@0.1.0"))
    with pytest.raises(ls.ScreenInputError, match="contract"):
        _build_selection(source, tmp_path, run_id="c",
                         source_manifest_path=foreign)
    # Only a diagnostic manifest filename is a source.
    with pytest.raises(ls.ScreenInputError, match="must be a"):
        _build_selection(source, tmp_path, run_id="d",
                         source_manifest_path=source.run_dir
                         / ld.DIAGNOSTIC_RECORDS_FILENAME)
    assert not (tmp_path / "repair-selections").exists()
    _assert_no_google_import()


def test_selection_refuses_wrong_population(source, tmp_path):
    # One rejection flipped to another reason: 6 eligible, not 7 — this is
    # simultaneously the wrong-reason case and the wrong-count case.
    six = _doctored_source(
        source, tmp_path / "six", mutate_rows=_flip_reason,
        mutate_manifest=lambda m: m["counts"]["rejections_by_reason"].update(
            quote_resolution_failure=6, adapter_rejection=1))
    with pytest.raises(ls.ScreenInputError, match="holds 6"):
        _build_selection(source, tmp_path, run_id="a",
                         source_manifest_path=six)

    # A validated row doctored into an eighth rejection: 8 eligible, not 7.
    def add_eighth(rows):
        for r in rows:
            if r["record_kind"] == "validated_screen":
                r.update(record_kind="rejected_output", screen_output=None,
                         rejection_reason_code="quote_resolution_failure",
                         rejection_detail="doctored eighth rejection")
                break
        return rows
    eight = _doctored_source(
        source, tmp_path / "eight", mutate_rows=add_eighth,
        mutate_manifest=lambda m: (
            m["counts"].update(validated=92, rejected=8),
            m["counts"]["rejections_by_reason"].update(
                quote_resolution_failure=8)))
    with pytest.raises(ls.ScreenInputError, match="holds 8"):
        _build_selection(source, tmp_path, run_id="b",
                         source_manifest_path=eight)

    # A duplicated (cik, accession) row is refused on its own: copying one
    # validated row over a validated sibling keeps the kind partition and
    # the dense ordinals intact, so only the duplicate gate can catch it.
    def duplicate(rows):
        rows[14] = dict(rows[15], row_ordinal=15)
        return rows
    dup = _doctored_source(source, tmp_path / "dup", mutate_rows=duplicate)
    with pytest.raises(ls.ScreenInputError, match="duplicate"):
        _build_selection(source, tmp_path, run_id="c",
                         source_manifest_path=dup)

    # A rejected row pointing at a packet the cohort does not hold.
    def orphan(rows):
        for r in rows:
            if r["record_kind"] == "rejected_output":
                r["cik"] = "9999999999"
                r["accession"] = "9999999999-22-000001"
                r["source_id"] = (
                    "sec-primary:9999999999:9999999999-22-000001:x.htm")
                break
        return rows
    missing = _doctored_source(source, tmp_path / "mp", mutate_rows=orphan)
    with pytest.raises(ls.ScreenInputError, match="no packet"):
        _build_selection(source, tmp_path, run_id="d",
                         source_manifest_path=missing)
    _assert_no_google_import()


def test_selection_refuses_a_foreign_cohort(source, tmp_path):
    other = _v5_run(tmp_path, [[
        _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm"),
        _fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"),
        _fixture_doc(PACKET_FIXTURES, "primary_10kt.htm"),
    ]])
    with pytest.raises(ls.ScreenInputError, match="not the cohort"):
        _build_selection(source, tmp_path, run_id="x", cohort=other)
    assert not (tmp_path / "repair-selections").exists()


# --- Preflight refusals ------------------------------------------------------------


def test_repair_preflight_bindings_refuse_before_output(source, tmp_path):
    selection_path, governance = _repair_setup(source, tmp_path)
    # Wrong authorization digest.
    forged = SimpleNamespace(root=governance.root,
                             reference=governance.reference,
                             sha256="0" * 64, authorization=None)
    with pytest.raises(ls.ScreenInputError, match="hashes to"):
        _repair(source, tmp_path, selection_path=selection_path,
                governance=forged)
    # Stale prompt: an authorization minted for the superseded v4 bytes.
    v4_sha = sha256(
        (ROOT / "prompts" / "discovery"
         / "universe_high_recall_screen.v4.md").read_bytes()).hexdigest()
    stale = _repair_governance(tmp_path / "stale", cohort=source.cohort,
                               selection_path=selection_path,
                               prompt_sha256=v4_sha)
    with pytest.raises(ls.ScreenInputError, match="prompt"):
        _repair(source, tmp_path / "stale", selection_path=selection_path,
                governance=stale)
    # A tampered selection no longer matches the authorization's digest.
    doctored = tmp_path / "sel-doctored.json"
    payload = json.loads(selection_path.read_text(encoding="utf-8"))
    payload["selection_id"] = "other"
    doctored.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    with pytest.raises(ls.ScreenInputError, match="not the one"):
        _repair(source, tmp_path, selection_path=doctored,
                governance=governance)
    # Wrong caps are refused: the operator-stated flag first, and a
    # cap-mutated authorization dies against its own schema consts.
    with pytest.raises(ls.ScreenInputError, match="logical_request_cap"):
        _repair(source, tmp_path, selection_path=selection_path,
                governance=governance, logical=6)
    with pytest.raises(ls.ScreenInputError, match="provider_attempt_cap"):
        _repair(source, tmp_path, selection_path=selection_path,
                governance=governance, attempts=20)
    badcaps = _repair_governance(
        tmp_path / "badcaps", cohort=source.cohort,
        selection_path=selection_path,
        mutate_authorization=lambda a: a.update(logical_request_cap=100))
    with pytest.raises(ls.ScreenInputError, match="violates|logical"):
        _repair(source, tmp_path / "badcaps", selection_path=selection_path,
                governance=badcaps, logical=100)
    # A breaker that can never trip is refused by the runner.
    never = _repair_governance(tmp_path / "never", cohort=source.cohort,
                               selection_path=selection_path, max_rejected=7)
    with pytest.raises(ls.ScreenInputError, match="never trip"):
        _repair(source, tmp_path / "never", selection_path=selection_path,
                governance=never)
    assert not (tmp_path / "repair").exists()
    _assert_no_google_import()


def test_a_canary_authorization_cannot_authorize_a_repair_run(source, tmp_path):
    """Third contract, on purpose: the 100-row diagnostic grant is refused."""
    from test_lineage_screen_diagnostic import _diagnostic_governance

    selection_path = _build_selection(source, tmp_path).manifest_path
    canary_gov = _diagnostic_governance(
        tmp_path, cohort=source.cohort,
        selection_path=selection_path, logical=7)
    with pytest.raises(ls.ScreenInputError, match="contract|violates"):
        _repair(source, tmp_path, selection_path=selection_path,
                governance=canary_gov)
    assert not (tmp_path / "repair").exists()
    _assert_no_google_import()


def test_a_canary_selection_is_not_a_repair_selection(source, tmp_path):
    """The 100-row canary selection artifact fails the repair contract."""
    canary_selection, _ = _canary_setup(source.cohort, tmp_path)
    governance = _repair_governance(tmp_path, cohort=source.cohort,
                                    selection_path=canary_selection)
    with pytest.raises(ls.ScreenInputError, match="violates"):
        _repair(source, tmp_path, selection_path=canary_selection,
                governance=governance)
    assert not (tmp_path / "repair").exists()


def test_source_drift_after_selection_minting_is_refused(source, tmp_path):
    """The derivation proof runs twice: a source doctored after the selection
    was minted is caught at preflight even though the selection is intact."""
    drifting = tmp_path / "drifting"
    shutil.copytree(source.run_dir, drifting)
    drifting_manifest = drifting / ld.DIAGNOSTIC_MANIFEST_FILENAME
    selection = _build_selection(
        source, tmp_path, source_manifest_path=drifting_manifest
    ).manifest_path
    governance = _repair_governance(tmp_path, cohort=source.cohort,
                                    selection_path=selection)
    # Now doctor the source under the selection's feet, hashes repaired.
    # The tamper is deliberately derivation-neutral — only a rejection
    # detail changes — so the ONLY thing that can catch it is the byte
    # binding between the minted selection and the source it pinned.
    records_path = drifting / ld.DIAGNOSTIC_RECORDS_FILENAME
    rows = [json.loads(x) for x in
            records_path.read_text(encoding="utf-8").splitlines() if x.strip()]
    for r in rows:
        if r["record_kind"] == "rejected_output":
            r["rejection_detail"] = "post-minting doctored detail"
            break
    records_path.write_text("".join(
        json.dumps(r, sort_keys=True, ensure_ascii=False,
                   separators=(",", ":")) + "\n" for r in rows),
        encoding="utf-8")
    manifest = json.loads(drifting_manifest.read_text(encoding="utf-8"))
    manifest["output_hashes"][ld.DIAGNOSTIC_RECORDS_FILENAME] = sha256(
        records_path.read_bytes()).hexdigest()
    drifting_manifest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    with pytest.raises(ls.ScreenInputError, match="drifted"):
        _repair(source, tmp_path, selection_path=selection,
                governance=governance)
    assert not (tmp_path / "repair").exists()


# --- The repair run ----------------------------------------------------------------


def test_repair_run_happy_path(source, tmp_path):
    selection_path, governance = _repair_setup(source, tmp_path)
    script = _script_for(source.cohort.packets)
    packets_by_cik = {p["cik"]: p for p in source.cohort.packets}
    for row in source.expected:
        script[row["cik"]]["text"] = _v5_evidence_payload(
            packets_by_cik[row["cik"]])
    result, factory = _repair(source, tmp_path, selection_path=selection_path,
                              governance=governance, script=script)
    assert result.status == "completed", result.receipt
    assert result.validated == 7 and result.rejected == 0
    assert factory.count_calls == 7 and factory.generate_calls == 7
    records = _records(result)
    assert len(records) == 7
    # Records reuse the diagnostic record contract, in selection order.
    for record in records:
        assert list(Draft202012Validator(
            RECORD_SCHEMA, format_checker=FormatChecker()
        ).iter_errors(record)) == []
    assert [(r["cik"], r["accession"]) for r in records] == \
        [(e["cik"], e["accession"]) for e in source.expected]
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(
        REPAIR_MANIFEST_SCHEMA, format_checker=FormatChecker()
    ).iter_errors(manifest)) == []
    ra = manifest["request_accounting"]
    assert (ra["logical_request_cap"], ra["provider_attempt_cap"],
            ra["external_request_cap"]) == (7, 21, 28)
    assert ra["external_requests_made"] == 14
    assert manifest["selection"]["source_run_id"] == "source-run"
    assert len(manifest["reconciliation"]) >= 14
    assert all(manifest["reconciliation"].values())
    for filename, recorded in manifest["output_hashes"].items():
        assert sha256((result.run_dir / filename).read_bytes()).hexdigest() \
            == recorded
    # Raw-before-parse and capture accounting: one archive line per row, one
    # count and one generate capture per row, no orphans.
    archive = [json.loads(x) for x in
               (result.run_dir / ls.RAW_RESPONSES_FILENAME)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(archive) == 7
    ledger = [json.loads(x) for x in
              (result.run_dir / ll.CAPTURE_LEDGER_FILENAME)
              .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(ledger) == 14
    for entry in ledger:
        assert sha256((result.run_dir / entry["raw_reference"]).read_bytes()
                      ).hexdigest() == entry["raw_sha256"]
    # Structural non-promotability: every other loader refuses; only the
    # repair loader accepts; and the repair loader refuses everything else.
    assert lr.require_diagnostic_repair_run(result.run_dir)
    with pytest.raises(ls.ScreenInputError, match="no manifest"):
        ls.require_authoritative_screen_run(result.run_dir)
    with pytest.raises(ls.ScreenInputError, match="no manifest"):
        ll.require_promotable_screen_run(result.run_dir)
    with pytest.raises(ls.ScreenInputError, match="no diagnostic manifest"):
        ld.require_diagnostic_run(result.run_dir)
    with pytest.raises(ls.ScreenInputError, match="diagnostic canary"):
        lr.require_diagnostic_repair_run(source.run_dir)
    bare = tmp_path / "bare"
    bare.mkdir()
    with pytest.raises(ls.ScreenInputError, match="no repair manifest"):
        lr.require_diagnostic_repair_run(bare)
    _assert_no_google_import()


def test_repair_run_v5_behaviours_measured_per_row(source, tmp_path):
    """Source injection repairs the copy error; wrong refs and non-verbatim
    quotes remain strict rejections — one validator, per-row measurement."""
    selection_path, governance = _repair_setup(source, tmp_path)
    packets_by_cik = {p["cik"]: p for p in source.cohort.packets}
    script = _script_for(source.cohort.packets)
    rows = source.expected
    # Row 1: model supplies a garbage source_id but a correct ref and quote —
    # the resolver injects the packet-owned source, so this row validates.
    script[rows[0]["cik"]]["text"] = _v5_evidence_payload(
        packets_by_cik[rows[0]["cik"]],
        supplied_source="sec-primary:0000000000:0000000000-00-000000:x.htm")
    # Row 2: an unknown passage reference is never repaired.
    script[rows[1]["cik"]]["text"] = _v5_evidence_payload(
        packets_by_cik[rows[1]["cik"]], ref="P999")
    # Row 3: a non-verbatim quote stays a strict rejection.
    script[rows[2]["cik"]]["text"] = _v5_evidence_payload(
        packets_by_cik[rows[2]["cik"]],
        quote="This sentence is not a verbatim copy of the passage.")
    for row in rows[3:]:
        script[row["cik"]]["text"] = _v5_evidence_payload(
            packets_by_cik[row["cik"]])
    result, _ = _repair(source, tmp_path, selection_path=selection_path,
                        governance=governance, script=script)
    assert result.status == "completed"
    assert result.validated == 5 and result.rejected == 2
    assert result.rejections_by_reason["quote_resolution_failure"] == 2
    records = _records(result)
    by_cik = {r["cik"]: r for r in records}
    injected = by_cik[rows[0]["cik"]]
    assert injected["record_kind"] == "validated_screen"
    assert injected["screen_output"]["positive_evidence"][0]["source_id"] == \
        packets_by_cik[rows[0]["cik"]]["source_id"]
    for bad_cik in (rows[1]["cik"], rows[2]["cik"]):
        rejected = by_cik[bad_cik]
        assert rejected["record_kind"] == "rejected_output"
        assert rejected["rejection_reason_code"] == "quote_resolution_failure"
        assert rejected["screen_output"] is None
        assert rejected["cost_micros"] > 0
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["counts"]["validated"] == 5
    assert manifest["counts"]["rejected"] == 2
    _assert_no_google_import()


def test_breaker_and_envelope_hard_stops(source, tmp_path):
    selection_path, governance = _repair_setup(source, tmp_path,
                                               max_rejected=1)
    packets_by_cik = {p["cik"]: p for p in source.cohort.packets}
    script = _script_for(source.cohort.packets)
    for row in source.expected:
        script[row["cik"]]["text"] = _v5_evidence_payload(
            packets_by_cik[row["cik"]])
    # The first two rows reject: the second trips the max_rejected=1 breaker.
    for row in source.expected[:2]:
        script[row["cik"]]["text"] = _v5_evidence_payload(
            packets_by_cik[row["cik"]], ref="P999")
    result, factory = _repair(source, tmp_path, selection_path=selection_path,
                              governance=governance, script=script)
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "rejected_row_budget_exhausted"
    assert receipt["rejected_rows"] == 2
    assert receipt["stopping_row_index"] == 2
    assert receipt["records_completed_before_failure"] == 1
    assert factory.generate_calls == 2  # no send after the stop
    assert not (result.run_dir / lr.REPAIR_RECORDS_FILENAME).exists()
    assert not (result.run_dir / lr.REPAIR_MANIFEST_FILENAME).exists()
    assert not (result.run_dir / ll.CAPTURE_LEDGER_FILENAME).exists()
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        lr.require_diagnostic_repair_run(result.run_dir)
    # An envelope failure is a hard stop, never a rejection record.
    script2 = _script_for(source.cohort.packets)
    for row in source.expected:
        script2[row["cik"]]["text"] = _v5_evidence_payload(
            packets_by_cik[row["cik"]])
    script2[source.expected[2]["cik"]]["envelope"] = b"this is not json"
    result2, _ = _repair(source, tmp_path, selection_path=selection_path,
                         governance=governance, script=script2,
                         run_id="env-stop")
    assert result2.status == "failed"
    assert result2.receipt["reason_code"] == "provider_error"
    assert result2.receipt["stopping_row_index"] == 3
    assert result2.receipt["records_completed_before_failure"] == 2


def test_determinism_dry_run_and_write_once(source, tmp_path):
    selection_path, governance = _repair_setup(source, tmp_path)
    packets_by_cik = {p["cik"]: p for p in source.cohort.packets}
    script = _script_for(source.cohort.packets)
    for row in source.expected:
        script[row["cik"]]["text"] = _v5_evidence_payload(
            packets_by_cik[row["cik"]])
    dry, factory = _repair(source, tmp_path, selection_path=selection_path,
                           governance=governance, script=script, dry_run=True)
    assert dry.status == "dry_run" and dry.run_dir is None
    assert factory.opens == 0
    assert not (tmp_path / "repair").exists()
    one, _ = _repair(source, tmp_path / "a", selection_path=selection_path,
                     governance=governance, script=script, run_id="same")
    two, _ = _repair(source, tmp_path / "b", selection_path=selection_path,
                     governance=governance, script=script, run_id="same")
    for filename in (lr.REPAIR_RECORDS_FILENAME, ls.RAW_RESPONSES_FILENAME,
                     ll.CAPTURE_LEDGER_FILENAME):
        assert (one.run_dir / filename).read_bytes() == \
            (two.run_dir / filename).read_bytes()
    assert one.manifest_path.read_bytes() == two.manifest_path.read_bytes()
    with pytest.raises(FileExistsError):
        _repair(source, tmp_path / "a", selection_path=selection_path,
                governance=governance, script=script, run_id="same")


# --- Structural guards -------------------------------------------------------------


def test_the_repair_module_reuses_the_validator_and_resolver():
    import ast

    source_text = (ROOT / "src" / "dynamic_ai_products"
                   / "lineage_screen_diagnostic_repair.py").read_text(
        encoding="utf-8")
    tree = ast.parse(source_text)
    imported = {alias.name for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) for alias in node.names}
    assert "_validate_row_output" in imported
    assert "resolve_diagnostic_citation_refs" in imported
    assert "render_diagnostic_prompt_with_citation_refs" in imported
    assert "def _validate_row_output" not in source_text
    assert "def resolve_diagnostic_citation_refs" not in source_text
    assert not set(lr.RECEIPT_REASON_CODES) & set(lr.REJECTION_REASON_CODES)
    assert lr.REPAIR_ROWS == 7


def test_the_repair_authorization_carries_every_diagnostic_binding():
    diagnostic = json.loads(
        (ROOT / "schemas" / "universe_screen_diagnostic_authorization.schema.json")
        .read_text(encoding="utf-8"))
    assert set(diagnostic["properties"]) == \
        set(REPAIR_AUTHORIZATION_SCHEMA["properties"])
    assert set(diagnostic["required"]) == set(REPAIR_AUTHORIZATION_SCHEMA["required"])
    p = REPAIR_AUTHORIZATION_SCHEMA["properties"]
    assert p["authorization_contract"]["const"] == \
        "universe_screen_diagnostic_repair_authorization@0.1.0"
    assert p["run_kind"]["const"] == "diagnostic_repair_7"
    assert p["selection_kind"]["const"] == "repair_7"
    assert p["logical_request_cap"]["const"] == 7
    assert p["provider_attempt_cap"]["const"] == 21
    assert p["budget_max_external_requests"]["const"] == 28
    assert p["max_rejected_rows"]["maximum"] == 7
    assert p["diagnostic_only"]["const"] is True
    assert p["promotable"]["const"] is False
    assert REPAIR_AUTHORIZATION_SCHEMA["additionalProperties"] is False


def test_predecessor_runners_prompts_and_schemas_are_byte_identical():
    """ADR-115 adds a successor and moves nothing it depends on."""
    pins = {
        "src/dynamic_ai_products/lineage_screen_live.py":
            "795dddb081629ddba184f52070011f1c42a61a669698f3643694a7cceb73c2c2",
        "src/dynamic_ai_products/universe/lineage_screen.py":
            "6bc2ae464c8c7d5ae7e16a24940db9e2849e60be692e32be81ce344e9cf8d77c",
        "src/dynamic_ai_products/lineage_screen_diagnostic.py":
            "d4d36da3ac8068f733230958bce819e788f2f255da696d18d86d6339f64d18a6",
        "prompts/discovery/universe_high_recall_screen.md":
            "4ac95a4c4e6ffdfbc55de7aec98fe4d50b89c29fab79e75a10c07cc35d102194",
        "prompts/discovery/universe_high_recall_screen.v2.md":
            "8bf0e3010241efe9aafd7d41af2857764c48ce218a7aa0f009086ec69a5d6694",
        "prompts/discovery/universe_high_recall_screen.v3.md":
            "1d371255d9b650bd5ff6ffd1d58d6a42b649436cfbcaf905bf3e53c5a7a58c78",
        "prompts/discovery/universe_high_recall_screen.v4.md":
            "30ce127d9c89454e222526599465aeb6e8f7bda82ce534fca26309036d7e33b6",
        "prompts/discovery/universe_high_recall_screen.v5.md":
            "fee42d939f9eab590fdcbf055e7b2039e8a33a410dfc12257a47291d7a77d558",
        "schemas/universe_screen_diagnostic_record.schema.json":
            "954ff4feba1a8af20a87099aedb312cbfa769493608835003ce57b309f8c04a8",
        "schemas/universe_screen_diagnostic_manifest.schema.json":
            "213e3a0d2d7794598373438c6c8dfb47e066352cb631f81cdc619df8d50f9f82",
        "schemas/universe_screen_diagnostic_authorization.schema.json":
            "0fc8cb77cac3481fb9bf137bb2474d707cdeebce188ccc66711e9981063dc5eb",
        "schemas/universe_screen_adapter_enablement.schema.json":
            "b7bd256673de311ffb3a49cc492bf5afe17ef4a2970abd175c9b2b7dc59a5058",
        "schemas/universe_screen_selection.schema.json":
            "bb1de6d96eb5382f319c88a7b015df1f20ff9820de7104573394d9415acc00ce",
        "schemas/universe_screen_live_authorization.schema.json":
            "a423eb2ddd2f56f63d74f4751e21d55a5ae8c956640b910221538aabc53493c3",
    }
    for path, expected in pins.items():
        actual = sha256((ROOT / path).read_bytes()).hexdigest()
        assert actual == expected, f"{path} moved: {actual}"


def test_registry_registers_the_three_repair_schemas():
    registry = json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json")
        .read_text(encoding="utf-8"))
    assert registry["manifest_version"] == "0.58.0"
    assert len(registry["schemas"]) == 122
    for key in ("universe_screen_diagnostic_repair_selection",
                "universe_screen_diagnostic_repair_authorization",
                "universe_screen_diagnostic_repair_manifest"):
        assert registry["schemas"][key] == "0.1.0"


def test_fresh_process_preflight_never_imports_google(tmp_path):
    script = (
        "import sys\n"
        "from datetime import datetime, timezone\n"
        "from dynamic_ai_products import lineage_screen_diagnostic_repair as lr\n"
        "from dynamic_ai_products.universe.lineage_screen import ScreenInputError\n"
        "try:\n"
        "    lr.run_lineage_screen_diagnostic_repair(\n"
        f"        repo_root={str(ROOT)!r},\n"
        f"        packet_manifest_path={str(tmp_path / 'none.json')!r},\n"
        f"        selection_artifact_path={str(tmp_path / 'none.json')!r},\n"
        f"        governance_root={str(tmp_path)!r},\n"
        "        authorization_reference='ghost.json',\n"
        "        authorization_sha256='0' * 64,\n"
        f"        output_dir={str(tmp_path / 'out')!r},\n"
        "        run_id='fresh', logical_request_cap=7, provider_attempt_cap=21,\n"
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


# --- CLI ---------------------------------------------------------------------------


def _cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, check=False)


def test_cli_select_repair_rows_end_to_end(source, tmp_path):
    completed = _cli("--mode", "select-screen-repair-rows",
                     "--packet-manifest", str(source.cohort.manifest_path),
                     "--source-diagnostic-manifest", str(source.manifest_path),
                     "--output-dir", str(tmp_path / "out"),
                     "--run-id", "cli-repair-sel")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "completed"
    artifact = json.loads(Path(payload["selection_artifact"])
                          .read_text(encoding="utf-8"))
    assert artifact["selection_kind"] == "repair_7"
    assert len(artifact["rows"]) == 7
    refused = _cli("--mode", "select-screen-repair-rows",
                   "--packet-manifest", str(source.cohort.manifest_path),
                   "--output-dir", str(tmp_path / "o2"), "--run-id", "r")
    assert refused.returncode != 0
    assert "--source-diagnostic-manifest" in refused.stderr
    assert not (tmp_path / "o2").exists()


def test_cli_repair_mode_dry_run_and_refusal(source, tmp_path):
    selection_path, governance = _repair_setup(source, tmp_path)
    base = ["--mode", "screen-universe-lineage-diagnostic-repair",
            "--packet-manifest", str(source.cohort.manifest_path),
            "--selection-artifact", str(selection_path),
            "--governance-root", str(governance.root),
            "--screen-authorization", governance.reference,
            "--logical-request-cap", "7", "--provider-attempt-cap", "21",
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


_OTHER_MODES = [
    "sentinel", "frame", "acquire-index", "dera-validate", "acquire-dera",
    "baseline-carrier", "acquire-docs", "probe-filing-index",
    "build-baseline-packets", "acquire-primary-docs",
    "determine-shell-company", "determine-shell-company-lineage",
    "determine-asset-backed-issuer-lineage",
    "build-baseline-packets-lineage", "build-baseline-packets-lineage-v2",
    "plan-acquisition-queue", "execute-acquisition-queue",
    "aggregate-acquisition-queue", "aggregate-acquisition-lineage",
    "screen-universe-lineage", "screen-universe-lineage-live",
    "screen-universe-lineage-diagnostic",
    "screen-universe-lineage-diagnostic-repair", "select-screen-rows",
]


@pytest.mark.parametrize("mode", _OTHER_MODES)
def test_every_other_mode_refuses_the_source_manifest_flag(tmp_path, mode):
    completed = _cli("--mode", mode,
                     "--source-diagnostic-manifest", "s.json",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr
    assert "--source-diagnostic-manifest" in completed.stderr
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize("flag,value", [
    ("--provider", "mock"), ("--screen-fixture", "f.json"),
    ("--config", "c.yaml"), ("--bundle-dir", "b"),
    ("--selection-seed", "3"), ("--selection-kind", "canary_100"),
])
def test_cli_repair_mode_refuses_irrelevant_flags(tmp_path, flag, value):
    completed = _cli("--mode", "screen-universe-lineage-diagnostic-repair",
                     flag, value,
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert flag in completed.stderr and "does not accept" in completed.stderr
    assert not (tmp_path / "o").exists()
