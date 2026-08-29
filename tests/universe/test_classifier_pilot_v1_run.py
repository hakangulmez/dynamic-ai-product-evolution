"""ADR-137 tests: the pilot's governed execution path, entirely offline.

The pilot's *contracts* are pinned by ``test_classifier_pilot_v1.py``. What is
asserted here is the path that runs them: that ten rows in produces ten records
out, that each of the four review reasons degrades one row and never the run,
that a genuine provider failure does the opposite, that a dry run resolves
everything and constructs nothing, and that no loader on either side can read
the other ladder's artifacts.

Everything is fixtures. The cohort, release and overlay are the ADR-127
selection fixtures; the transport is a fake that answers by the CIK the pilot
prompt prints; no test builds a ``genai.Client``, resolves a credential or opens
a socket, and a guard asserts the ``google`` namespace stays unimported.

The ten rows are the fixture cohort's own, substituted for the committed
``PILOT_ROWS`` for the duration of a test. The production ten are real filings
that no synthetic cohort contains, and asserting them is
``test_classifier_pilot_v1.py``'s job against the real artifacts; what this
suite needs is ten rows the machinery can actually be driven over.
"""

from __future__ import annotations

import json
import re
import sys
from contextlib import contextmanager
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_calibration_selection as ccs
from dynamic_ai_products import classifier_pilot_selection as cps
from dynamic_ai_products import classifier_pilot_v1 as pilot
from dynamic_ai_products import lineage_classifier_calibration as lcal
from dynamic_ai_products import lineage_classifier_pilot_v1 as lpilot
from dynamic_ai_products import lineage_classifier_v2_1 as lcl
from dynamic_ai_products.providers import screen_count_retry_policy as cp
from dynamic_ai_products.providers import screen_retry_policy as gp
from dynamic_ai_products.providers.client_contract_v2 import CLIENT_CONTRACT_V2_ID
from dynamic_ai_products.providers.retry_policy import (
    RATE_LIMIT_POLICY_VERSION,
    RETRY_POLICY_VERSION,
)
from dynamic_ai_products.universe.lineage_screen import ScreenInputError

sys.path.insert(0, str(Path(__file__).parent))

from test_classifier_calibration_selection import (  # noqa: E402
    CLOCK,
    ROOT,
    _build as _build_calibration_selection,
    _sha,
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
    packet_cohort as packet_cohort,  # noqa: F401,PLC0414
    release as release,  # noqa: F401,PLC0414
)
from test_lineage_screen_live import (  # noqa: E402
    VERTEX_LOCATION,
    VERTEX_PROJECT,
    _contract_digest,
    _endpoints,
    _envelope,
)
from test_lineage_screen_live_v3 import _EventCapture, _Fake429  # noqa: E402

MANIFEST_SCHEMA = json.loads(
    (ROOT / lpilot.PILOT_MANIFEST_SCHEMA).read_text(encoding="utf-8"))
RECORD_SCHEMA = json.loads(
    (ROOT / pilot.PILOT_RECORD_SCHEMA).read_text(encoding="utf-8"))
SELECTION_SCHEMA = json.loads(
    (ROOT / pilot.PILOT_SELECTION_SCHEMA).read_text(encoding="utf-8"))
AUTHORIZATION_SCHEMA = json.loads(
    (ROOT / lpilot.PILOT_AUTHORIZATION_SCHEMA).read_text(encoding="utf-8"))

#: The pilot prompt prints an uppercase CIK line; the screen prompts print a
#: lowercase one. The fake transport keys on the pilot's.
_CIK_IN_PILOT_PROMPT = re.compile(r"^CIK: (\d{10})$", re.MULTILINE)

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
    assert not added, f"the pilot path imported google: {sorted(added)}"


# --- a fake transport that answers the pilot prompt ---------------------------------


class _PilotModels:
    """Scripted count/generate behaviour keyed by the pilot prompt's CIK line."""

    def __init__(self, capture, script, events):
        self._capture, self._script, self._events = capture, script, events
        self.count_calls = self.generate_calls = 0

    def _entry(self, contents: str) -> dict:
        match = _CIK_IN_PILOT_PROMPT.search(contents)
        assert match, "the rendered pilot prompt carries no CIK line"
        return self._script[match.group(1)]

    def count_tokens(self, *, model, contents, config):
        self.count_calls += 1
        entry = self._entry(contents)
        tokens = entry.get("count_tokens", 120)
        self._capture.record_send(
            "count_tokens", json.dumps({"totalTokens": tokens}).encode(), "ok")
        return SimpleNamespace(total_tokens=tokens)

    def generate_content(self, *, model, contents, config):
        self.generate_calls += 1
        entry = self._entry(contents)
        if entry.get("quota_failures", 0) > 0:
            entry["quota_failures"] -= 1
            self._capture.record_send("generate_content", None,
                                      "no_response_transport_failure")
            raise _Fake429("scripted 429")
        envelope = _envelope(entry["text"],
                             prompt_tokens=entry.get("count_tokens", 120))
        self._capture.record_send("generate_content",
                                  json.dumps(envelope).encode(), "ok")
        return SimpleNamespace()


class _PilotFactory:
    def __init__(self, script, events):
        self.script, self.events = script, events
        self.opens = self.count_calls = self.generate_calls = 0

    def __call__(self, *, vertex_project, vertex_location, endpoint_allowlist,
                 http_options_kwargs, operation_endpoints=None):
        @contextmanager
        def _open():
            self.opens += 1
            capture = _EventCapture(self.events)
            models = _PilotModels(capture, self.script, self.events)
            try:
                yield SimpleNamespace(models=models), capture
            finally:
                self.count_calls += models.count_calls
                self.generate_calls += models.generate_calls
        return _open()


# --- fixtures ------------------------------------------------------------------------


STRATA = ("P1_obvious_software", "P1_obvious_software", "P2_model_screen_likely",
          "P2_model_screen_likely", "P2_model_screen_likely",
          "P3_model_screen_boundary", "P5_economically_ambiguous",
          "P5_economically_ambiguous", "P5_economically_ambiguous",
          "P6_clear_negative")


@pytest.fixture
def source_selection(cohort, tmp_path):
    """The 40-row calibration selection the pilot's ten are a subset of."""
    payload = _build_calibration_selection(cohort, tmp_path, name="source-selection")
    path = tmp_path / "source-selection" / ccs.CALIBRATION_SELECTION_FILENAME
    return SimpleNamespace(path=path, selection=payload,
                           sha256=_sha(path.read_bytes()), rows=payload["rows"])


@pytest.fixture
def pilot_rows(source_selection, monkeypatch):
    """Ten of the fixture cohort's rows, standing in for the committed ten."""
    chosen = source_selection.rows[:10]
    rows = tuple((r["cik"], r["accession"], s) for r, s in zip(chosen, STRATA))
    monkeypatch.setattr(pilot, "PILOT_ROWS", rows)
    return rows


@pytest.fixture
def selection(cohort, source_selection, pilot_rows, tmp_path):
    path = tmp_path / "pilot-selection" / cps.PILOT_SELECTION_FILENAME
    payload = cps.build_pilot_selection_artifact(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        cohort_manifest_sha256=cohort.sha256,
        source_selection_path=source_selection.path,
        source_selection_sha256=source_selection.sha256,
        output_path=path, selection_id="pilot-selection-fixture", clock=CLOCK)
    return SimpleNamespace(path=path, selection=payload,
                           sha256=_sha(path.read_bytes()), rows=payload["rows"])


def _grant(cohort, selection, tmp_path, *, mutate=None, name="pilot-gov"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    endpoints, digest = _endpoints(), _contract_digest()
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
    enablement_raw = (json.dumps(enablement, indent=2, sort_keys=True) + "\n").encode()
    (root / "screen_adapter_enablement.json").write_bytes(enablement_raw)
    rows = len(selection.rows)
    payload = {
        "authorization_contract": lpilot.PILOT_AUTHORIZATION_CONTRACT,
        "authorization_id": "pilot-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": "release_or_research_production",
        "run_kind": lpilot.PILOT_RUN_KIND, "promotable": False,
        "covers_full_cohort": False,
        "output_contract": pilot.PILOT_RECORD_CONTRACT,
        "output_axes_contract": pilot.PILOT_AXES_CONTRACT,
        "cohort_id": "cohort-fixture", "cohort_manifest_sha256": cohort.sha256,
        "packet_manifest_sha256": cohort.packet_manifest_sha256,
        "selection_artifact_path": str(selection.path),
        "selection_artifact_sha256": selection.sha256,
        "selection_kind": "classifier_pilot_v1",
        "prompt_template_path": pilot.PILOT_PROMPT_PATH,
        "prompt_template_sha256":
            sha256((ROOT / pilot.PILOT_PROMPT_PATH).read_bytes()).hexdigest(),
        "screen_adapter_enablement_reference": "screen_adapter_enablement.json",
        "screen_adapter_enablement_sha256": _sha(enablement_raw),
        "provider_client_contract_reference": CLIENT_CONTRACT_V2_ID,
        "provider_client_contract_sha256": digest,
        "vertex_project": VERTEX_PROJECT, "vertex_location": VERTEX_LOCATION,
        "model_route": {"provider": "google_vertex_ai",
                        "model_label": "gemini-2.5-flash"},
        "endpoint_allowlist": endpoints,
        "logical_row_cap": rows, "count_attempt_cap": rows * 3,
        "provider_attempt_cap": rows * 5,
        "budget_max_external_requests": rows * 8,
        "count_attempts_per_row": 3, "generate_attempts_per_row": 5,
        "external_requests_per_row": 8,
        "budget_max_input_tokens": 10_000_000,
        "budget_max_output_tokens": 100_000_000,
        "budget_max_estimated_cost_micros": 1_000_000_000,
        "budget_max_wall_clock_seconds": 86_400,
        "retry_policy_version": RETRY_POLICY_VERSION,
        "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
        "screen_generate_retry_policy_version":
            gp.SCREEN_GENERATE_RETRY_POLICY_VERSION,
        "screen_count_retry_policy_version": cp.SCREEN_COUNT_RETRY_POLICY_VERSION,
    }
    if mutate is not None:
        mutate(payload)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (root / "pilot_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=root, reference="pilot_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def _axes(**over):
    doc = {"customer_facing_functional_product": "YES",
           "software_centrality": "CORE",
           "firm_structure": "SOFTWARE_DOMINANT",
           "commercial_materiality": "DOMINANT",
           "confidence": "high",
           "evidence": [{"axis": "software_centrality", "passage_ref": "P001"}]}
    doc.update(over)
    return doc


def _script(selection, **overrides):
    script = {row["cik"]: {"text": json.dumps(_axes())} for row in selection.rows}
    for cik, extra in overrides.items():
        script[cik] = {**script.get(cik, {}), **extra}
    return script


def _run(cohort, selection, grant, tmp_path, *, script=None, run_id="pilot-run",
         dry_run=False, output_dir=None, selection_path=None):
    events: list = []
    factory = _PilotFactory(
        script if script is not None else _script(selection), events)
    result = lpilot.run_lineage_classifier_pilot_v1(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        packet_manifest_path=cohort.packet_manifest_path,
        selection_path=selection_path or selection.path,
        governance_root=grant.root, authorization_reference=grant.reference,
        authorization_sha256=grant.sha256,
        output_dir=output_dir or (tmp_path / "pilot-out"), run_id=run_id,
        clock=CLOCK, dry_run=dry_run, client_factory=factory,
        sleep=lambda s: events.append(("wait", s)))
    return SimpleNamespace(result=result, factory=factory, events=events)


def _records(result):
    return [json.loads(x) for x in
            (result.run_dir / lpilot.PILOT_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


def _manifest(result):
    return json.loads(result.manifest_path.read_text(encoding="utf-8"))


# --- the ten-row selection and its digest bindings -----------------------------------


def test_the_selection_is_exactly_the_ten_named_rows(selection, pilot_rows):
    Draft202012Validator(SELECTION_SCHEMA, format_checker=FormatChecker()).validate(
        selection.selection)
    assert len(selection.rows) == cps.PILOT_ROW_CAP == 10
    assert [(r["cik"], r["accession"]) for r in selection.rows] == \
        [(cik, acc) for cik, acc, _ in pilot_rows]
    _assert_no_google()


def test_the_selection_binds_its_cohort_source_and_packet_digests(
        selection, cohort, source_selection):
    built = selection.selection
    assert built["cohort_manifest_sha256"] == cohort.sha256
    assert built["source_selection_sha256"] == source_selection.sha256
    assert built["source_selection_path"] == str(source_selection.path)
    assert built["packet_manifest_sha256"] == \
        source_selection.selection["packet_manifest_sha256"]
    assert built["cohort_id"] == source_selection.selection["cohort_id"]


def test_the_builder_accepts_no_row_argument():
    """Which firms the pilot covers is a committed constant, not a parameter."""
    import inspect
    params = set(inspect.signature(cps.build_pilot_selection_artifact).parameters)
    assert not {"rows", "pilot_rows", "ciks", "accessions", "row_count"} & params


def test_a_wrong_cohort_digest_is_refused(cohort, source_selection, pilot_rows,
                                          tmp_path):
    with pytest.raises(ScreenInputError, match="was pinned"):
        cps.build_pilot_selection_artifact(
            repo_root=ROOT, cohort_manifest_path=cohort.path,
            cohort_manifest_sha256="0" * 64,
            source_selection_path=source_selection.path,
            source_selection_sha256=source_selection.sha256,
            output_path=tmp_path / "x" / cps.PILOT_SELECTION_FILENAME,
            selection_id="x", clock=CLOCK)


def test_a_wrong_source_selection_digest_is_refused(cohort, source_selection,
                                                    pilot_rows, tmp_path):
    with pytest.raises(ScreenInputError, match="nothing runs"):
        cps.build_pilot_selection_artifact(
            repo_root=ROOT, cohort_manifest_path=cohort.path,
            cohort_manifest_sha256=cohort.sha256,
            source_selection_path=source_selection.path,
            source_selection_sha256="0" * 64,
            output_path=tmp_path / "x" / cps.PILOT_SELECTION_FILENAME,
            selection_id="x", clock=CLOCK)


def test_a_selection_is_written_once(cohort, source_selection, pilot_rows, tmp_path):
    path = tmp_path / "once" / cps.PILOT_SELECTION_FILENAME
    kwargs = dict(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        cohort_manifest_sha256=cohort.sha256,
        source_selection_path=source_selection.path,
        source_selection_sha256=source_selection.sha256,
        output_path=path, selection_id="once", clock=CLOCK)
    cps.build_pilot_selection_artifact(**kwargs)
    before = path.read_bytes()
    with pytest.raises(ScreenInputError):
        cps.build_pilot_selection_artifact(**kwargs)
    assert path.read_bytes() == before


def test_a_selection_dry_run_writes_nothing(cohort, source_selection, pilot_rows,
                                            tmp_path):
    path = tmp_path / "dry" / cps.PILOT_SELECTION_FILENAME
    built = cps.build_pilot_selection_artifact(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        cohort_manifest_sha256=cohort.sha256,
        source_selection_path=source_selection.path,
        source_selection_sha256=source_selection.sha256,
        output_path=path, selection_id="dry", clock=CLOCK, dry_run=True)
    assert len(built["rows"]) == 10
    assert not path.exists() and not path.parent.exists()


def test_the_pilot_selection_loader_refuses_a_calibration_selection(
        source_selection, selection):
    """Both are selections over the same cohort; the filename gate tells them apart."""
    with pytest.raises(ScreenInputError, match="different artifact"):
        cps.require_pilot_selection(source_selection.path,
                                    expected_sha256=source_selection.sha256)
    assert cps.require_pilot_selection(
        selection.path, expected_sha256=selection.sha256)["selection_kind"] == \
        "classifier_pilot_v1"


def test_the_calibration_loader_refuses_the_pilot_selection(selection):
    with pytest.raises(ScreenInputError, match="different artifact"):
        ccs.require_calibration_selection(selection.path,
                                          expected_sha256=selection.sha256)


# --- the dry run constructs nothing and writes nothing -------------------------------


def test_a_dry_run_resolves_ten_inputs_and_reports_the_derived_caps(
        cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    out = tmp_path / "dry-out"
    run = _run(cohort, selection, grant, tmp_path, dry_run=True, output_dir=out)
    assert run.result.status == "dry_run"
    assert run.result.run_dir is None
    assert run.result.request_accounting == {
        "selected_rows": 10, "model_called_rows": 10, "logical_row_cap": 10,
        "count_attempt_cap": 30, "provider_attempt_cap": 50,
        "external_request_cap": 80}
    _assert_no_google()


def test_a_dry_run_constructs_no_provider_client_and_writes_nothing(
        cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    out = tmp_path / "dry-out"
    run = _run(cohort, selection, grant, tmp_path, dry_run=True, output_dir=out)
    assert run.factory.opens == 0
    assert run.factory.count_calls == run.factory.generate_calls == 0
    assert run.events == []
    assert not out.exists()


def test_a_dry_run_renders_every_one_of_the_ten_prompts(cohort, selection,
                                                        tmp_path, monkeypatch):
    grant = _grant(cohort, selection, tmp_path)
    rendered: list[str] = []
    original = lpilot.render_pilot_prompt

    def spy(template, packet):
        text = original(template, packet)
        rendered.append(text)
        return text

    monkeypatch.setattr(lpilot, "render_pilot_prompt", spy)
    _run(cohort, selection, grant, tmp_path, dry_run=True,
         output_dir=tmp_path / "dry-out")
    assert len(rendered) == 10
    assert len({_CIK_IN_PILOT_PROMPT.search(t).group(1) for t in rendered}) == 10


# --- the happy path ------------------------------------------------------------------


def test_ten_valid_responses_complete_the_run(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()

    records = _records(run.result)
    validator = Draft202012Validator(RECORD_SCHEMA, format_checker=FormatChecker())
    for record in records:
        validator.validate(record)
    assert [(r["cik"], r["accession"]) for r in records] == \
        [(r["cik"], r["accession"]) for r in selection.rows]
    assert all(r["record_kind"] == "classified" for r in records)
    assert run.result.counts["classified"] == 10
    assert run.result.counts["review_uncertain"] == 0
    assert run.result.counts["review_uncertain_by_reason"] == {}


def test_the_manifest_binds_every_input_and_output_digest(cohort, selection,
                                                          source_selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    manifest = _manifest(run.result)
    Draft202012Validator(MANIFEST_SCHEMA, format_checker=FormatChecker()).validate(
        manifest)

    assert manifest["sources"]["cohort"]["manifest_sha256"] == cohort.sha256
    assert manifest["sources"]["packet"]["packet_manifest_sha256"] == \
        cohort.packet_manifest_sha256
    assert manifest["sources"]["selection"]["selection_artifact_sha256"] == \
        selection.sha256
    assert manifest["sources"]["selection"]["source_selection_sha256"] == \
        source_selection.sha256
    assert manifest["prompt_template_sha256"] == \
        sha256((ROOT / pilot.PILOT_PROMPT_PATH).read_bytes()).hexdigest()
    assert manifest["provider_client_contract_sha256"] == _contract_digest()
    assert manifest["provider"] == grant.authorization["model_route"]

    for filename, recorded in manifest["output_hashes"].items():
        assert _sha((run.result.run_dir / filename).read_bytes()) == recorded
    assert set(manifest["output_hashes"]) == {
        lpilot.PILOT_RECORDS_FILENAME, lpilot.PILOT_RAW_RESPONSES_FILENAME,
        "universe_screen_capture_ledger.jsonl"}


def test_the_manifest_states_what_ten_rows_cannot_support(cohort, selection,
                                                          tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    manifest = _manifest(_run(cohort, selection, grant, tmp_path).result)
    assert manifest["promotable"] is False
    assert manifest["covers_full_cohort"] is False
    assert manifest["derives_no_tier"] is True
    assert manifest["settles_no_membership"] is True
    text = " ".join(manifest["limitations"])
    assert "non-promotable" in text
    assert "settles no firm's membership" in text
    assert "may not be extrapolated" in text
    assert "derives no tier" in text


def test_the_manifest_carries_no_tier_and_no_tolerance(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    manifest = _manifest(_run(cohort, selection, grant, tmp_path).result)
    blob = json.dumps(manifest)
    for absent in ("by_tier", "tier_rules_version", "tier_rules_sha256",
                   "tier_rule_trace", "bounded_outcomes",
                   "max_model_output_unusable", "max_provider_unresolved",
                   "taxonomy_version", "span_index_version"):
        assert absent not in blob, absent


def test_the_manifest_reports_the_axis_distributions_it_can_support(
        cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    counts = _manifest(_run(cohort, selection, grant, tmp_path).result)["counts"]
    assert counts["selected_rows"] == 10
    assert counts["by_software_centrality"] == {"CORE": 10}
    assert counts["by_confidence"] == {"high": 10}
    assert sum(counts["by_admission_origin"].values()) == 10
    assert sum(counts["by_pilot_stratum"].values()) == 10
    assert counts["evidence_items"] == 10
    assert counts["rows_with_no_evidence"] == 0


def test_every_reconciliation_identity_holds(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    assert run.result.reconciliation
    assert all(run.result.reconciliation.values()), sorted(
        k for k, v in run.result.reconciliation.items() if not v)


def test_the_run_sends_exactly_one_count_and_one_generate_per_row(
        cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    accounting = run.result.request_accounting
    assert accounting["model_called_rows"] == 10
    assert accounting["count_attempts_made"] == 10
    assert accounting["provider_attempts_made"] == 10
    assert accounting["external_requests_made"] == 20
    assert accounting["rows_count_retried"] == accounting["rows_generate_retried"] == 0


# --- the four review paths each cost one row, never the run --------------------------


REVIEW_CASES = (
    ("invalid_model_json", "{not json"),
    ("model_emitted_forbidden_field", json.dumps(_axes(tier="TIER_A"))),
    ("pilot_axes_contract_violation", json.dumps(_axes(confidence="certain"))),
    ("evidence_reference_unresolvable", json.dumps(_axes(evidence=[
        {"axis": "firm_structure", "passage_ref": "P099"}]))),
)


@pytest.mark.parametrize("reason,payload", REVIEW_CASES)
def test_one_bad_response_degrades_one_row_and_the_run_completes(
        cohort, selection, tmp_path, reason, payload):
    grant = _grant(cohort, selection, tmp_path)
    broken = selection.rows[3]["cik"]
    run = _run(cohort, selection, grant, tmp_path,
               script=_script(selection, **{broken: {"text": payload}}))
    assert run.result.status == "completed", run.result.receipt

    records = _records(run.result)
    assert len(records) == 10
    validator = Draft202012Validator(RECORD_SCHEMA, format_checker=FormatChecker())
    for record in records:
        validator.validate(record)
    bad = next(r for r in records if r["cik"] == broken)
    assert bad["record_kind"] == "review_uncertain"
    assert bad["review_reason_code"] == reason
    assert bad["axes"] is None and bad["review_detail"]
    assert sum(r["record_kind"] == "classified" for r in records) == 9

    manifest = _manifest(run.result)
    assert manifest["counts"]["review_uncertain"] == 1
    assert manifest["counts"]["review_uncertain_by_reason"] == {reason: 1}
    assert manifest["counts"]["classified"] == 9


def test_all_four_review_paths_in_one_run_still_yield_ten_rows(cohort, selection,
                                                               tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    overrides = {selection.rows[i]["cik"]: {"text": payload}
                 for i, (_reason, payload) in enumerate(REVIEW_CASES)}
    run = _run(cohort, selection, grant, tmp_path,
               script=_script(selection, **overrides))
    assert run.result.status == "completed", run.result.receipt
    records = _records(run.result)
    assert len(records) == 10
    assert sum(r["record_kind"] == "review_uncertain" for r in records) == 4
    manifest = _manifest(run.result)
    assert manifest["counts"]["review_uncertain_by_reason"] == {
        reason: 1 for reason, _ in REVIEW_CASES}
    assert sum(manifest["counts"]["review_uncertain_by_reason"].values()) == 4
    assert manifest["counts"]["classified"] == 6
    # and every one of the ten filings is still present exactly once
    assert [(r["cik"], r["accession"]) for r in records] == \
        [(r["cik"], r["accession"]) for r in selection.rows]


def test_no_review_reason_is_outside_the_closed_vocabulary(cohort, selection,
                                                           tmp_path):
    assert {reason for reason, _ in REVIEW_CASES} == set(pilot.REVIEW_REASONS)


# --- a provider failure stops the run and is never stored as a judgement -------------


def test_a_provider_failure_stops_the_run_and_writes_a_receipt(cohort, selection,
                                                               tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    stopping = selection.rows[2]["cik"]
    run = _run(cohort, selection, grant, tmp_path,
               script=_script(selection, **{stopping: {"quota_failures": 99}}))
    assert run.result.status == "failed"
    receipt = run.result.receipt
    assert receipt["reason_code"] == "provider_error"
    assert receipt["stopping_cik"] == stopping
    assert receipt["stopping_row_completed"] is False
    assert receipt["records_completed_before_failure"] == 2
    assert receipt["run_kind"] == lpilot.PILOT_RUN_KIND

    run_dir = run.result.run_dir
    assert not (run_dir / lpilot.PILOT_RECORDS_FILENAME).exists()
    assert not (run_dir / lpilot.PILOT_MANIFEST_FILENAME).exists()
    assert not (run_dir / "universe_screen_capture_ledger.jsonl").exists()


def test_a_provider_failure_is_never_recorded_as_a_review_row(cohort, selection,
                                                              tmp_path):
    """The four review reasons describe a readable model response. An outage is not one."""
    grant = _grant(cohort, selection, tmp_path)
    stopping = selection.rows[2]["cik"]
    run = _run(cohort, selection, grant, tmp_path,
               script=_script(selection, **{stopping: {"quota_failures": 99}}))
    blob = json.dumps(run.result.receipt)
    for reason in pilot.REVIEW_REASONS:
        assert reason not in blob, reason
    assert "review_uncertain" not in blob
    assert "classified" not in blob


def test_a_failed_pilot_run_cannot_be_consumed(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    stopping = selection.rows[2]["cik"]
    run = _run(cohort, selection, grant, tmp_path,
               script=_script(selection, **{stopping: {"quota_failures": 99}}))
    with pytest.raises(ScreenInputError, match="failure receipt"):
        lpilot.require_pilot_run(run.result.run_dir)


# --- prompt isolation ----------------------------------------------------------------


def test_no_rendered_prompt_carries_admission_overlay_or_v2_output(
        cohort, selection, tmp_path, monkeypatch):
    """The model sees Item 1. Everything an earlier reader concluded stays out."""
    grant = _grant(cohort, selection, tmp_path)
    rendered: list[str] = []
    original = lpilot.render_pilot_prompt

    def spy(template, packet):
        text = original(template, packet)
        rendered.append(text)
        return text

    monkeypatch.setattr(lpilot, "render_pilot_prompt", spy)
    run = _run(cohort, selection, grant, tmp_path)
    assert run.result.status == "completed"
    assert len(rendered) == 10
    forbidden = (
        "admission", "admitted_status", "admission_origin", "screen_status",
        "LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN", "model_screen",
        "human_review", "overlay", "reviewer", "decision_ledger",
        "candidate_customer_value_archetypes", "plausible_customer_facing",
        "TIER_A", "TIER_B", "TIER_C", "EXCLUDED", "tier", "non_authoritative",
        "pilot_stratum", "high_recall", "screen_output",
    )
    for text in rendered:
        for token in forbidden:
            assert token not in text, token


def test_the_runner_never_hydrates_a_release_or_an_overlay():
    """The pilot's input surface has no place an earlier verdict could enter."""
    import inspect
    source = inspect.getsource(lpilot)
    for absent in ("require_screen_release", "require_human_review_overlay",
                   "load_cohort_inputs", "_admission_for", "derive_tier",
                   "load_tier_rules", "render_classifier_prompt",
                   "OVERLAY_DECISIONS_FILENAME", "RELEASE_RECORDS_FILENAME"):
        assert absent not in source, absent
    params = set(inspect.signature(
        lpilot.run_lineage_classifier_pilot_v1).parameters)
    assert not {"overlay_manifest_path", "release_manifest_path"} & params


def test_the_prompt_the_model_receives_is_the_one_the_record_hashes(
        cohort, selection, tmp_path, monkeypatch):
    grant = _grant(cohort, selection, tmp_path)
    rendered: list[str] = []
    original = lpilot.render_pilot_prompt
    monkeypatch.setattr(
        lpilot, "render_pilot_prompt",
        lambda t, p: (rendered.append(original(t, p)) or rendered[-1]))
    run = _run(cohort, selection, grant, tmp_path)
    records = _records(run.result)
    assert [r["prompt_sha256"] for r in records] == \
        [sha256(t.encode("utf-8")).hexdigest() for t in rendered]


# --- deterministic whole-block evidence, raw-source offsets --------------------------


def test_stored_evidence_is_the_packets_own_block_bytes_and_offsets(
        cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    packets = {(p["cik"], p["accession"]): p for p in cohort.packets.packets}
    for record in _records(run.result):
        packet = packets[(record["cik"], record["accession"])]
        blocks = {p["passage_id"]: p for p in packet["passages"]}
        assert record["axes"]["evidence"]
        for item in record["axes"]["evidence"]:
            block = blocks[item["passage_id"]]
            assert item["evidence_text"] == block["text"]
            assert item["byte_start"] == block["byte_start"]
            assert item["byte_end"] == block["byte_end"]
            assert item["text_sha256"] == \
                sha256(block["text"].encode("utf-8")).hexdigest()
            assert item["provenance"] == "pipeline_derived"


def test_evidence_resolution_needs_only_the_packet(cohort, selection, tmp_path):
    """A stored row stays checkable without the renderer or any reference map."""
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    packets = {(p["cik"], p["accession"]): p for p in cohort.packets.packets}
    for record in _records(run.result):
        assert lpilot._evidence_resolves(record, packets)
    tampered = dict(_records(run.result)[0])
    tampered["axes"] = {**tampered["axes"], "evidence": [
        {**tampered["axes"]["evidence"][0], "evidence_text": "not the block"}]}
    assert not lpilot._evidence_resolves(tampered, packets)


def test_the_same_selection_yields_the_same_evidence_twice(cohort, selection,
                                                           tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    first = _records(_run(cohort, selection, grant, tmp_path,
                          run_id="pilot-run-a").result)
    second = _records(_run(cohort, selection, grant, tmp_path,
                           run_id="pilot-run-b").result)
    assert [r["axes"] for r in first] == [r["axes"] for r in second]


# --- write-once ----------------------------------------------------------------------


def test_a_run_directory_is_claimed_once(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    out = tmp_path / "once-out"
    first = _run(cohort, selection, grant, tmp_path, output_dir=out)
    assert first.result.status == "completed"
    before = (first.result.run_dir / lpilot.PILOT_RECORDS_FILENAME).read_bytes()
    with pytest.raises(FileExistsError):
        _run(cohort, selection, grant, tmp_path, output_dir=out)
    assert (first.result.run_dir / lpilot.PILOT_RECORDS_FILENAME).read_bytes() == before


def test_the_loader_refuses_a_run_whose_output_drifted(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    assert lpilot.require_pilot_run(run.result.run_dir) == run.result.manifest_path
    (run.result.run_dir / lpilot.PILOT_RECORDS_FILENAME).write_bytes(b"{}\n")
    with pytest.raises(ScreenInputError, match="no longer hashes"):
        lpilot.require_pilot_run(run.result.run_dir)


# --- pilot / V2.x isolation ----------------------------------------------------------


def test_no_pilot_filename_collides_with_any_v2_x_filename():
    v2 = set()
    for route in (lcl.BASE_ROUTE, lcl.BASE_ROUTE_V2_9, lcal.CALIBRATION_ROUTE,
                  lcal.CALIBRATION_ROUTE_V2_8, lcal.CALIBRATION_ROUTE_V2_9):
        v2 |= {route.records_filename, route.manifest_filename,
               route.archive_filename}
    pilot_names = {lpilot.PILOT_RECORDS_FILENAME, lpilot.PILOT_MANIFEST_FILENAME,
                   lpilot.PILOT_RAW_RESPONSES_FILENAME}
    assert not (v2 & pilot_names)


def test_no_pilot_contract_collides_with_any_v2_x_contract():
    v2 = {lcl.MANIFEST_CONTRACT, lcl.AUTHORIZATION_CONTRACT, lcl.RECORD_CONTRACT,
          lcl.AXES_CONTRACT, lcal.CALIBRATION_MANIFEST_CONTRACT,
          ccs.SELECTION_CONTRACT}
    for route in (lcal.CALIBRATION_ROUTE_V2_8, lcal.CALIBRATION_ROUTE_V2_9):
        v2 |= {route.manifest_contract, route.contracts.record_contract,
               route.contracts.axes_contract}
    pilot_contracts = {
        lpilot.PILOT_MANIFEST_CONTRACT, lpilot.PILOT_AUTHORIZATION_CONTRACT,
        pilot.PILOT_RECORD_CONTRACT, pilot.PILOT_AXES_CONTRACT,
        pilot.PILOT_SELECTION_CONTRACT}
    assert not (v2 & pilot_contracts)


def test_a_v2_x_loader_refuses_a_pilot_run(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    for route in (lcl.BASE_ROUTE, lcal.CALIBRATION_ROUTE_V2_9):
        with pytest.raises(ScreenInputError, match="holds no"):
            lcl.require_completed_run(run.result.run_dir, route,
                                      what="Classifier run")


def test_the_pilot_loader_refuses_a_v2_x_run(tmp_path):
    directory = tmp_path / "v2-run"
    directory.mkdir(parents=True)
    (directory / lcal.CALIBRATION_ROUTE_V2_9.manifest_filename).write_bytes(
        b'{"manifest_contract": "universe_classifier_calibration_manifest@0.9.0"}\n')
    with pytest.raises(ScreenInputError, match="holds no"):
        lpilot.require_pilot_run(directory)


def test_the_pilot_refuses_a_v2_x_grant(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path, mutate=lambda p: p.update(
        authorization_contract="universe_classifier_calibration_authorization@0.9.0"))
    with pytest.raises(ScreenInputError, match="this route runs"):
        _run(cohort, selection, grant, tmp_path)


def test_the_pilot_authorization_schema_admits_no_v2_x_field():
    """The absent fields are the design, so their absence is asserted, not assumed."""
    properties = set(AUTHORIZATION_SCHEMA["properties"])
    assert AUTHORIZATION_SCHEMA["additionalProperties"] is False
    for absent in ("tier_rules_version", "tier_rules_sha256", "taxonomy_version",
                   "strata_rules_version", "strata_rules_sha256", "selection_seed",
                   "span_index_version", "span_index_sha256",
                   "overlay_manifest_sha256", "release_manifest_sha256",
                   "max_model_output_unusable", "max_provider_unresolved",
                   "max_model_output_truncated", "reused_prefix_row_cap"):
        assert absent not in properties, absent


@pytest.mark.parametrize("field", ["tier_rules_version", "max_model_output_unusable",
                                   "strata_rules_sha256", "span_index_version"])
def test_a_grant_carrying_a_v2_x_field_is_refused(cohort, selection, tmp_path, field):
    grant = _grant(cohort, selection, tmp_path,
                   mutate=lambda p, f=field: p.update({f: "x"}))
    with pytest.raises(ScreenInputError):
        _run(cohort, selection, grant, tmp_path)


def test_the_pilot_run_kind_is_its_own(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    manifest = _manifest(_run(cohort, selection, grant, tmp_path).result)
    assert manifest["run_kind"] == "classifier_pilot_v1"
    assert manifest["run_kind"] != lcal.CALIBRATION_RUN_KIND
    assert manifest["record_order"] == "pilot_selection_row_order"
    assert manifest["record_order"] != lcal.CALIBRATION_RECORD_ORDER


# --- the grant must bind exactly these inputs ----------------------------------------


@pytest.mark.parametrize("mutation,match", [
    (lambda p: p.update(logical_row_cap=9), "logical_row_cap"),
    (lambda p: p.update(count_attempt_cap=29), "count_attempt_cap"),
    (lambda p: p.update(provider_attempt_cap=49), "provider_attempt_cap"),
    (lambda p: p.update(budget_max_external_requests=79),
     "budget_max_external_requests"),
    (lambda p: p.update(promotable=True), "promotable"),
    (lambda p: p.update(covers_full_cohort=True), "covers_full_cohort"),
    (lambda p: p.update(cohort_manifest_sha256="0" * 64), "cohort manifest"),
    (lambda p: p.update(packet_manifest_sha256="0" * 64), "packet cohort"),
    (lambda p: p.update(selection_artifact_sha256="0" * 64), "nothing runs"),
    (lambda p: p.update(prompt_template_sha256="0" * 64), "prompt bytes"),
    (lambda p: p.update(effective_at="2027-01-01T00:00:00+00:00"),
     "effective window"),
])
def test_a_grant_that_does_not_bind_the_committed_inputs_is_refused(
        cohort, selection, tmp_path, mutation, match):
    grant = _grant(cohort, selection, tmp_path, mutate=mutation)
    with pytest.raises(ScreenInputError, match=match):
        _run(cohort, selection, grant, tmp_path)
    assert not (tmp_path / "pilot-out").exists()


def test_a_grant_naming_another_selection_path_is_refused(cohort, selection,
                                                          tmp_path):
    grant = _grant(cohort, selection, tmp_path,
                   mutate=lambda p: p.update(selection_artifact_path="/elsewhere.json"))
    with pytest.raises(ScreenInputError, match="grant names selection"):
        _run(cohort, selection, grant, tmp_path)


def test_a_refused_grant_creates_no_run_directory(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path,
                   mutate=lambda p: p.update(promotable=True))
    out = tmp_path / "refused-out"
    with pytest.raises(ScreenInputError):
        _run(cohort, selection, grant, tmp_path, output_dir=out)
    assert not out.exists()
    _assert_no_google()


# --- predecessor freeze --------------------------------------------------------------


#: The artifacts this increment must not move. The pilot prompt is deliberately
#: absent: it is the thing under active revision, and a digest pin here would
#: only have to be rebaselined by every wording change while asserting nothing
#: about meaning. Its content is governed by ``test_classifier_pilot_v1.py``,
#: which reads the sentences rather than the bytes.
PREDECESSOR_DIGESTS = {
    "prompts/discovery/universe_full_classification.v2_8.md":
        "56cc14656d26cb59f0ddb6ea5901e62a3f3e37949c49f95fbb06cb7ecd4551ce",
    "prompts/discovery/universe_full_classification.v2_9.md":
        "ab9b4353fd11b1ffe5d226620439c9a927aebc1a979d4f3f7bff5c852e068671",
    "configs/universe_classifier_tier_rules_v2_1.yaml":
        "14326a298236c2431c89aba4d4a5241bc4e6a95e4bc9212df716d5200dedc468",
    "configs/universe_classifier_calibration_strata_v1.yaml":
        "b763dca0816212430bbe844eca0065f2762a18905e3d8a8c6b1ee9dc902353ac",
    "configs/universe_classifier_span_index_v1.yaml":
        "0f98b00f861fbaee710612af3cda681f99c5f642e1e6323f91a1deb9ec219499",
}


@pytest.mark.parametrize("path,digest", sorted(PREDECESSOR_DIGESTS.items()))
def test_the_predecessors_are_byte_unchanged(path, digest):
    """The pilot's execution path is additive. Nothing it runs beside moved."""
    assert _sha((ROOT / path).read_bytes()) == digest, path


def test_the_pilot_contracts_are_byte_unchanged():
    """The three ADR-137 contracts are released; the substrate did not edit them."""
    for relative, digest in (
        (pilot.PILOT_AXES_SCHEMA,
         "81766f63adb27d99193490e3c2cd5063f9ff0124019bc791030858191e8ea870"),
        (pilot.PILOT_RECORD_SCHEMA,
         "fa2c41451f5035b01d6519dfce8cbc541c9ec7818586728dbe87b10c8f986763"),
    ):
        assert _sha((ROOT / relative).read_bytes()) == digest, relative


def test_the_v2_x_routes_still_name_what_they_always_named():
    assert lcal.CALIBRATION_ROUTE_V2_9.records_filename == \
        "universe_classifier_v2_9_calibration_records.jsonl"
    assert lcal.CALIBRATION_ROUTE_V2_9.manifest_contract == \
        "universe_classifier_calibration_manifest@0.9.0"
    assert lcl.BASE_ROUTE.records_filename == "universe_classifier_records.jsonl"
    assert lcl.RECORD_CONTRACT == "universe_classifier_record@0.1.0"


# --- the CLI boundary ----------------------------------------------------------------


def _cli_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "pilot_cli_under_test", ROOT / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def cli():
    return _cli_module()


def test_both_pilot_modes_exist_and_are_distinct_from_the_v2_x_ones(cli):
    action = next(a for a in cli.build_parser()._actions if a.dest == "mode")
    assert "classify-software-universe-pilot-v1" in action.choices
    assert "select-classifier-pilot-rows" in action.choices
    assert "classify-universe-calibration-v2-9" in action.choices
    assert len(action.choices) == len(set(action.choices))


@pytest.mark.parametrize("mode,flag,value", [
    ("classify-universe-calibration-v2-9", "--pilot-selection", "/x.json"),
    ("select-classifier-pilot-rows", "--pilot-selection", "/x.json"),
    ("select-classifier-pilot-rows", "--calibration-run-dir", "/x"),
    ("select-classifier-pilot-rows", "--packet-manifest", "/x.json"),
    ("classify-software-universe-pilot-v1", "--overlay-manifest", "/x.json"),
    ("classify-software-universe-pilot-v1", "--release-manifest", "/x.json"),
    ("classify-software-universe-pilot-v1", "--calibration-selection", "/x.json"),
    ("classify-software-universe-pilot-v1", "--cohort-manifest-sha256", "a" * 64),
])
def test_a_flag_from_another_mode_is_refused(cli, mode, flag, value):
    args = cli.build_parser().parse_args(
        ["--mode", mode, "--output-dir", "/tmp/x", "--run-id", "r", flag, value])
    message = cli._reject_cross_mode_flags(args)
    assert message and flag in message, message


@pytest.mark.parametrize("mode,required", [
    ("select-classifier-pilot-rows",
     ["--cohort-manifest", "--cohort-manifest-sha256", "--calibration-selection",
      "--calibration-selection-sha256"]),
    ("classify-software-universe-pilot-v1",
     ["--cohort-manifest", "--packet-manifest", "--pilot-selection",
      "--governance-root", "--screen-authorization",
      "--screen-authorization-sha256"]),
])
def test_a_pilot_mode_names_every_flag_it_requires(cli, mode, required):
    args = cli.build_parser().parse_args(
        ["--mode", mode, "--output-dir", "/tmp/x", "--run-id", "r"])
    message = cli._reject_cross_mode_flags(args)
    assert message and "requires" in message
    for flag in required:
        assert flag in message, flag


def test_the_live_mode_writes_to_its_own_run_root():
    """Pilot runs never land beside V2.x classifier runs."""
    assert lpilot.PILOT_RUN_ROOT_NAME == "universe-classifier-pilot-v1-runs"
    assert "pilot" in lpilot.PILOT_RUN_ROOT_NAME
    assert lpilot.PILOT_RUN_ROOT_NAME != "universe-classifier-calibration-runs"
