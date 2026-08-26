"""ADR-127 tests: the calibration is the classifier, on a sample, and says so.

Everything is offline. The cohort, release and overlay are the ADR-127
selection fixtures; the transport is the fake the screen suites use; no test
builds a ``genai.Client``, resolves a credential or opens a socket.

The properties that matter here are not about classification — ADR-126 already
pins those — but about containment: that a calibration cannot be mistaken for a
full run by any loader, that its grant must state tolerances rather than
inherit them, and that its manifest says out loud what its own numbers cannot
support.
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_calibration_selection as ccs
from dynamic_ai_products import lineage_classifier_calibration as lcal
from dynamic_ai_products import lineage_classifier_v2_1 as lcl
from dynamic_ai_products.providers import screen_count_retry_policy as cp
from dynamic_ai_products.providers import screen_retry_policy as gp
from dynamic_ai_products.providers.client_contract_v2 import CLIENT_CONTRACT_V2_ID
from dynamic_ai_products.providers.retry_policy import (
    RATE_LIMIT_POLICY_VERSION,
    RETRY_POLICY_VERSION,
)
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_classifier_calibration_selection import (  # noqa: E402
    CLOCK,
    ROOT,
    _build as _build_selection,
    _sha,
    cohort as cohort,  # noqa: F401,PLC0414 - re-exported pytest fixture
    packet_cohort as packet_cohort,  # noqa: F401,PLC0414
    release as release,  # noqa: F401,PLC0414
)
from test_lineage_classifier_v2_1 import _axes_payload  # noqa: E402
from test_lineage_screen_continuation_v5 import _EmptyBodyFactory  # noqa: E402
from test_lineage_screen_live import (  # noqa: E402
    VERTEX_LOCATION,
    VERTEX_PROJECT,
    _contract_digest,
    _endpoints,
)

MANIFEST_SCHEMA = json.loads(
    (ROOT / lcal.CALIBRATION_MANIFEST_SCHEMA).read_text(encoding="utf-8"))
RECORD_SCHEMA = json.loads((ROOT / lcl.RECORD_SCHEMA).read_text(encoding="utf-8"))

#: The approved calibration-only tolerances. Named here once so a test can
#: assert they never leak into a full-run default.
CALIBRATION_TOLERANCES = {"max_model_output_unusable": 2,
                          "max_provider_unresolved": 2,
                          "max_model_output_truncated": 2}

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
    assert not added, f"the calibration path imported google: {sorted(added)}"


@pytest.fixture
def selection(cohort, tmp_path):
    payload = _build_selection(cohort, tmp_path, name="calibration-selection")
    path = tmp_path / "calibration-selection" / ccs.CALIBRATION_SELECTION_FILENAME
    return SimpleNamespace(path=path, selection=payload,
                           sha256=_sha(path.read_bytes()),
                           rows=payload["rows"])


def _grant(cohort, selection, tmp_path, *, mutate=None, name="calibration-gov",
           tolerances=None):
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
    from dynamic_ai_products.classifier_tier_engine import load_tier_rules
    tier = load_tier_rules(ROOT)
    strata = ccs.load_strata_rules(ROOT)
    rows = len(selection.rows)
    payload = {
        "authorization_contract":
            "universe_classifier_calibration_authorization@0.1.0",
        "authorization_id": "calibration-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": "release_or_research_production",
        "run_kind": lcal.CALIBRATION_RUN_KIND, "promotable": False,
        "covers_full_cohort": False,
        "output_contract": lcl.RECORD_CONTRACT,
        "cohort_id": "cohort-fixture", "cohort_manifest_sha256": cohort.sha256,
        "overlay_id": "overlay-fixture",
        "overlay_manifest_sha256": cohort.overlay_sha256,
        "release_id": "synthetic-release",
        "release_manifest_sha256": cohort.release.sha256,
        "packet_manifest_sha256": cohort.packet_manifest_sha256,
        "selection_artifact_path": str(selection.path),
        "selection_artifact_sha256": selection.sha256,
        "selection_kind": "classifier_calibration_v1",
        "selection_seed": strata.seed,
        "strata_rules_version": strata.version,
        "strata_rules_sha256": strata.sha256,
        "prompt_template_path": lcl.PROMPT_PATH,
        "prompt_template_sha256":
            sha256((ROOT / lcl.PROMPT_PATH).read_bytes()).hexdigest(),
        "tier_rules_version": tier.version, "tier_rules_sha256": tier.sha256,
        "taxonomy_version": lcl.TAXONOMY_VERSION,
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
        **(tolerances if tolerances is not None else CALIBRATION_TOLERANCES),
    }
    if mutate is not None:
        mutate(payload)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (root / "calibration_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=root, reference="calibration_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def _script(cohort, selection, **overrides):
    packets = cohort.release.packets
    script = {row["cik"]: {"text": _axes_payload(
        packets[(row["cik"], row["accession"])])} for row in selection.rows}
    for cik, extra in overrides.items():
        script[cik] = {**script.get(cik, {}), **extra}
    return script


def _run(cohort, selection, grant, tmp_path, *, script=None, run_id="calibration-run",
         dry_run=False, output_dir=None, selection_path=None, route=None):
    events: list = []
    factory = _EmptyBodyFactory(
        script if script is not None else _script(cohort, selection), events)
    result = lcal.run_lineage_classifier_calibration(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        overlay_manifest_path=cohort.overlay_path,
        release_manifest_path=cohort.release.path,
        packet_manifest_path=cohort.packet_manifest_path,
        selection_path=selection_path or selection.path,
        governance_root=grant.root, authorization_reference=grant.reference,
        authorization_sha256=grant.sha256,
        output_dir=output_dir or (tmp_path / "calibration-out"), run_id=run_id,
        clock=CLOCK, dry_run=dry_run, client_factory=factory,
        sleep=lambda s: events.append(("wait", s)),
        **({"route": route} if route is not None else {}))
    return SimpleNamespace(result=result, factory=factory, events=events)


def _records(result):
    return [json.loads(x) for x in
            (result.run_dir / lcal.CALIBRATION_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


# --- the happy path ----------------------------------------------------------------


def test_the_calibration_classifies_exactly_its_selection(cohort, selection,
                                                          tmp_path):
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
    assert len(records) < len(cohort.rows)
    assert run.result.counts["selected_rows"] == len(selection.rows)
    assert sum(run.result.counts["by_stratum"].values()) == len(records)
    assert all(v is True for v in run.result.reconciliation.values())


def test_the_manifest_binds_the_same_prompt_and_rules_as_the_full_run(
        cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(MANIFEST_SCHEMA,
                         format_checker=FormatChecker()).validate(manifest)
    assert manifest["prompt_template_path"] == lcl.PROMPT_PATH
    assert manifest["prompt_template_sha256"] == \
        sha256((ROOT / lcl.PROMPT_PATH).read_bytes()).hexdigest()
    assert manifest["tier_rules_version"] == "universe_classifier_tier_rules_v2_1"
    assert manifest["sources"]["cohort"]["manifest_sha256"] == cohort.sha256
    assert manifest["calibration_selection"]["seed"] == 20260824
    assert manifest["calibration_selection"]["selection_sha256"] == selection.sha256


def test_a_dry_run_renders_every_selected_row_and_sends_nothing(
        cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path, dry_run=True)
    assert run.result.status == "dry_run" and run.result.run_dir is None
    assert run.factory.opens == run.factory.generate_calls == 0
    assert run.result.request_accounting["selected_rows"] == len(selection.rows)
    assert run.result.request_accounting["cohort_rows"] == len(cohort.rows)


def test_the_run_spends_only_what_the_selection_justifies(cohort, selection,
                                                          tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    accounting = run.result.request_accounting
    assert accounting["model_called_rows"] == len(selection.rows)
    assert accounting["logical_row_cap"] == len(selection.rows)
    assert accounting["count_attempt_cap"] == len(selection.rows) * 3
    assert accounting["provider_attempt_cap"] == len(selection.rows) * 5
    assert accounting["external_request_cap"] == len(selection.rows) * 8
    assert accounting["external_requests_made"] <= accounting["external_request_cap"]


# --- containment: a calibration is not a full run ----------------------------------


def test_a_full_run_loader_refuses_a_calibration(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    with pytest.raises(ls.ScreenInputError, match="holds no universe_classifier_manifest.json"):
        lcl.require_classifier_run(run.result.run_dir)
    assert lcal.require_classifier_calibration_run(run.result.run_dir) == \
        run.result.manifest_path


def test_the_outputs_carry_their_own_names(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    present = {p.name for p in run.result.run_dir.iterdir()}
    assert lcal.CALIBRATION_RECORDS_FILENAME in present
    assert lcal.CALIBRATION_MANIFEST_FILENAME in present
    assert lcl.CLASSIFIER_RECORDS_FILENAME not in present
    assert lcl.CLASSIFIER_MANIFEST_FILENAME not in present


def test_the_manifest_is_non_promotable_and_says_it_covers_no_cohort(
        cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["promotable"] is False
    assert manifest["covers_full_cohort"] is False
    assert manifest["record_order"] == "calibration_selection_row_order"
    assert manifest["run_kind"] == "classifier_calibration_v2_1"
    assert manifest["counts"]["selected_rows"] < manifest["counts"]["cohort_rows"]


def test_the_manifest_refuses_to_let_its_numbers_be_extrapolated(
        cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    joined = " ".join(manifest["limitations"]).lower()
    assert "too small to estimate a rate" in joined
    assert "bounded-outcome tolerances" in joined
    assert "sample design only" in joined
    assert "non-promotable" in joined


def test_a_calibration_loader_refuses_a_full_cohort_claim(cohort, selection,
                                                          tmp_path):
    grant = _grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path)
    manifest_path = run.result.manifest_path
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["covers_full_cohort"] = True
    manifest_path.write_bytes(
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    with pytest.raises(ls.ScreenInputError, match="never a universe"):
        lcal.require_classifier_calibration_run(run.result.run_dir)


def test_a_grant_claiming_cohort_coverage_is_refused(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path, name="gov-covers",
                   mutate=lambda p: p.__setitem__("covers_full_cohort", True))
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, output_dir=tmp_path / "never")


def test_the_base_route_refuses_a_calibration_grant(cohort, selection, tmp_path):
    """The two grants are mutually exclusive contracts, not variants."""
    grant = _grant(cohort, selection, tmp_path, name="gov-cross")
    with pytest.raises(ls.ScreenInputError):
        lcl.run_lineage_classifier(
            repo_root=ROOT, cohort_manifest_path=cohort.path,
            overlay_manifest_path=cohort.overlay_path,
            release_manifest_path=cohort.release.path,
            packet_manifest_path=cohort.packet_manifest_path,
            governance_root=grant.root, authorization_reference=grant.reference,
            authorization_sha256=grant.sha256,
            output_dir=tmp_path / "never", run_id="cross-run", clock=CLOCK,
            dry_run=True)


# --- tolerances are stated, never inherited ----------------------------------------


@pytest.mark.parametrize("field", ["max_model_output_unusable",
                                   "max_provider_unresolved",
                                   "max_model_output_truncated"])
def test_a_grant_without_an_explicit_tolerance_is_refused(cohort, selection,
                                                          tmp_path, field):
    tolerances = dict(CALIBRATION_TOLERANCES)
    del tolerances[field]
    grant = _grant(cohort, selection, tmp_path, name=f"gov-{field}",
                   tolerances=tolerances)
    with pytest.raises(ls.ScreenInputError, match="violates its contract"):
        _run(cohort, selection, grant, tmp_path, output_dir=tmp_path / "never")


def test_the_calibration_tolerances_are_not_a_full_run_default():
    """Nothing in the classifier code carries these numbers as a default."""
    for module in ("lineage_classifier_v2_1.py", "lineage_classifier_calibration.py",
                   "classifier_calibration_selection.py"):
        source = (ROOT / "src/dynamic_ai_products" / module).read_text(
            encoding="utf-8")
        for field in CALIBRATION_TOLERANCES:
            assert f"{field} = " not in source
            assert f'"{field}", 2' not in source
            assert f'{field}={2}' not in source
    schema = json.loads((ROOT / lcl.AUTHORIZATION_SCHEMA).read_text(encoding="utf-8"))
    for field in CALIBRATION_TOLERANCES:
        assert "default" not in schema["properties"][field]


def test_the_calibration_grant_marks_its_tolerances_as_sample_only():
    schema = json.loads(
        (ROOT / lcal.CALIBRATION_AUTHORIZATION_SCHEMA).read_text(encoding="utf-8"))
    for field in CALIBRATION_TOLERANCES:
        described = schema["properties"][field]["description"].lower()
        assert "calibration sample alone" in described
        assert "separate decision" in described
        assert "default" not in schema["properties"][field]


# --- preflight refusals, all before a run directory exists --------------------------


def _refused(cohort, selection, grant, tmp_path, match, **kwargs):
    output_dir = tmp_path / "never-created"
    with pytest.raises(ls.ScreenInputError, match=match):
        _run(cohort, selection, grant, tmp_path, output_dir=output_dir, **kwargs)
    assert not output_dir.exists(), "a refused calibration created a run directory"
    _assert_no_google()


def test_a_selection_the_grant_does_not_name_is_refused(cohort, selection, tmp_path):
    other = _build_selection(cohort, tmp_path, selection_id="other", name="other")
    other_path = tmp_path / "other" / ccs.CALIBRATION_SELECTION_FILENAME
    assert other["selection_id"] == "other"
    grant = _grant(cohort, selection, tmp_path, name="gov-other")
    _refused(cohort, selection, grant, tmp_path, "grant names selection",
             selection_path=other_path)


def test_a_selection_whose_digest_moved_is_refused(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path, name="gov-digest",
                   mutate=lambda p: p.__setitem__("selection_artifact_sha256",
                                                  "0" * 64))
    _refused(cohort, selection, grant, tmp_path, "was pinned")


def test_a_selection_drawn_under_other_strata_rules_is_refused(cohort, selection,
                                                               tmp_path):
    grant = _grant(cohort, selection, tmp_path, name="gov-strata",
                   mutate=lambda p: p.__setitem__("strata_rules_sha256", "0" * 64))
    _refused(cohort, selection, grant, tmp_path, "different strata rules")


def test_a_selection_drawn_under_another_seed_is_refused(cohort, selection,
                                                         tmp_path):
    grant = _grant(cohort, selection, tmp_path, name="gov-seed",
                   mutate=lambda p: p.__setitem__("selection_seed", 1))
    _refused(cohort, selection, grant, tmp_path, "but the grant names")


def test_a_selection_from_another_cohort_is_refused(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path, name="gov-cohort",
                   mutate=lambda p: p.__setitem__("cohort_manifest_sha256",
                                                  "0" * 64))
    _refused(cohort, selection, grant, tmp_path, "was pinned")


def test_a_cap_that_does_not_match_the_selection_is_refused(cohort, selection,
                                                            tmp_path):
    grant = _grant(cohort, selection, tmp_path, name="gov-cap",
                   mutate=lambda p: p.__setitem__("logical_row_cap", 9_999))
    _refused(cohort, selection, grant, tmp_path, r"row\(s\) but this route's scope")


def test_a_grant_for_the_wrong_run_kind_is_refused(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path, name="gov-kind",
                   mutate=lambda p: p.__setitem__("run_kind", "classifier_v2_1"))
    _refused(cohort, selection, grant, tmp_path, "violates its contract")


def test_a_promotable_calibration_grant_is_refused(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path, name="gov-promotable",
                   mutate=lambda p: p.__setitem__("promotable", True))
    _refused(cohort, selection, grant, tmp_path, "violates its contract")


# --- ADR-128: the same route, at the V2.2 contract version -------------------------


def _v2_2_grant(cohort, selection, tmp_path, *, name="calibration-gov-v2-2"):
    """The V2.1 grant, re-pointed at the V2.2 contracts. Same selection."""
    from dynamic_ai_products.classifier_contract_set import V2_2
    base = _grant(cohort, selection, tmp_path, name=name).authorization
    payload = dict(base)
    payload.update({
        "authorization_contract":
            "universe_classifier_calibration_authorization@0.2.0",
        "output_contract": V2_2.record_contract,
        "taxonomy_version": V2_2.taxonomy_version,
        "prompt_template_path": V2_2.prompt_path,
        "prompt_template_sha256":
            sha256((ROOT / V2_2.prompt_path).read_bytes()).hexdigest(),
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    ((tmp_path / name) / "calibration_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=tmp_path / name,
                           reference="calibration_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def test_the_v2_2_route_classifies_the_same_unchanged_selection(cohort, selection,
                                                                tmp_path):
    """The selection is immutable and reusable; only the contract moved."""
    grant = _v2_2_grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path, run_id="calibration-v2-2",
               route=lcal.CALIBRATION_ROUTE_V2_2)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == \
        "universe_classifier_calibration_manifest@0.2.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.2.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_2"
    assert manifest["prompt_template_path"].endswith("v2_2.md")
    assert manifest["calibration_selection"]["selection_sha256"] == selection.sha256
    assert manifest["schema_versions"]["universe_classifier_axes_record"] == "0.2.0"
    assert manifest["schema_versions"]["universe_classifier_record"] == "0.2.0"
    # the tier rules did not move with the contract
    assert manifest["tier_rules_version"] == "universe_classifier_tier_rules_v2_1"
    records = [json.loads(x) for x in
               (run.result.run_dir / lcal.CALIBRATION_ROUTE_V2_2.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(selection.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.2.0"
               for r in records)


def test_the_two_versions_write_different_files(cohort, selection, tmp_path):
    v1 = _run(cohort, selection, _grant(cohort, selection, tmp_path, name="g1"),
              tmp_path, run_id="calib-v1")
    v2 = _run(cohort, selection,
              _v2_2_grant(cohort, selection, tmp_path, name="g2"), tmp_path,
              run_id="calib-v2", route=lcal.CALIBRATION_ROUTE_V2_2)
    assert v1.result.status == v2.result.status == "completed"
    assert {p.name for p in v1.result.run_dir.iterdir()} != \
        {p.name for p in v2.result.run_dir.iterdir()}
    assert (v1.result.run_dir / lcal.CALIBRATION_RECORDS_FILENAME).is_file()
    assert not (v1.result.run_dir /
                lcal.CALIBRATION_ROUTE_V2_2.records_filename).exists()
    assert (v2.result.run_dir /
            lcal.CALIBRATION_ROUTE_V2_2.records_filename).is_file()
    assert not (v2.result.run_dir / lcal.CALIBRATION_RECORDS_FILENAME).exists()


def test_each_version_loader_refuses_the_other(cohort, selection, tmp_path):
    v2 = _run(cohort, selection,
              _v2_2_grant(cohort, selection, tmp_path, name="g3"), tmp_path,
              run_id="calib-iso", route=lcal.CALIBRATION_ROUTE_V2_2)
    with pytest.raises(ls.ScreenInputError,
                       match="holds no universe_classifier_calibration_manifest.json"):
        lcal.require_classifier_calibration_run(v2.result.run_dir)
    with pytest.raises(ls.ScreenInputError, match="holds no universe_classifier_manifest.json"):
        lcl.require_classifier_run(v2.result.run_dir)


def test_a_v2_2_grant_is_refused_by_the_v2_1_route(cohort, selection, tmp_path):
    grant = _v2_2_grant(cohort, selection, tmp_path, name="g4")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id="cross-1",
             output_dir=tmp_path / "never")


def test_a_v2_1_grant_is_refused_by_the_v2_2_route(cohort, selection, tmp_path):
    grant = _grant(cohort, selection, tmp_path, name="g5")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id="cross-2",
             output_dir=tmp_path / "never", route=lcal.CALIBRATION_ROUTE_V2_2)


# --- ADR-129: the same route and the same selection, at V2.3 -----------------------


def _v2_3_grant(cohort, selection, tmp_path, *, name="calibration-gov-v2-3"):
    """The V2.2 grant re-pointed at the V2.3 prompt. Contracts are unchanged."""
    from dynamic_ai_products.classifier_contract_set import V2_3
    base = _grant(cohort, selection, tmp_path, name=name).authorization
    payload = dict(base)
    payload.update({
        "authorization_contract":
            "universe_classifier_calibration_authorization@0.3.0",
        "output_contract": V2_3.record_contract,
        "taxonomy_version": V2_3.taxonomy_version,
        "prompt_template_path": V2_3.prompt_path,
        "prompt_template_sha256":
            sha256((ROOT / V2_3.prompt_path).read_bytes()).hexdigest(),
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    ((tmp_path / name) / "calibration_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=tmp_path / name,
                           reference="calibration_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def test_the_v2_3_route_classifies_the_same_unchanged_selection(cohort, selection,
                                                                tmp_path):
    grant = _v2_3_grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path, run_id="calibration-v2-3",
               route=lcal.CALIBRATION_ROUTE_V2_3)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == \
        "universe_classifier_calibration_manifest@0.3.0"
    # the contract set is V2.2's; only the prompt moved
    assert manifest["output_contract"] == "universe_classifier_record@0.2.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_2"
    assert manifest["prompt_template_path"].endswith("v2_3.md")
    assert manifest["tier_rules_version"] == "universe_classifier_tier_rules_v2_1"
    assert manifest["calibration_selection"]["selection_sha256"] == selection.sha256
    assert manifest["schema_versions"]["universe_classifier_axes_record"] == "0.2.0"
    records = [json.loads(x) for x in
               (run.result.run_dir / lcal.CALIBRATION_ROUTE_V2_3.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(selection.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.2.0"
               for r in records)


def test_the_three_versions_write_three_disjoint_file_sets(cohort, selection,
                                                           tmp_path):
    runs = {
        "v2_1": _run(cohort, selection, _grant(cohort, selection, tmp_path, name="k1"),
                     tmp_path, run_id="calib-k1"),
        "v2_2": _run(cohort, selection,
                     _v2_2_grant(cohort, selection, tmp_path, name="k2"), tmp_path,
                     run_id="calib-k2", route=lcal.CALIBRATION_ROUTE_V2_2),
        "v2_3": _run(cohort, selection,
                     _v2_3_grant(cohort, selection, tmp_path, name="k3"), tmp_path,
                     run_id="calib-k3", route=lcal.CALIBRATION_ROUTE_V2_3),
    }
    names = {}
    for version, run in runs.items():
        assert run.result.status == "completed", (version, run.result.receipt)
        names[version] = {p.name for p in run.result.run_dir.iterdir()}
    assert names["v2_1"] != names["v2_2"] != names["v2_3"] != names["v2_1"]
    # The capture directory and the capture ledger are provider-transport
    # artifacts, named the same in all three manifest contracts. Version
    # identity is carried by the records, manifest and archive names, which
    # must share nothing across versions.
    transport = {"provider_captures", "universe_screen_capture_ledger.jsonl"}
    for a, b in (("v2_1", "v2_2"), ("v2_2", "v2_3"), ("v2_1", "v2_3")):
        shared = (names[a] & names[b]) - transport
        assert not shared, (a, b, shared)
    for version, run in runs.items():
        route = {"v2_1": lcal.CALIBRATION_ROUTE, "v2_2": lcal.CALIBRATION_ROUTE_V2_2,
                 "v2_3": lcal.CALIBRATION_ROUTE_V2_3}[version]
        present = names[version] - transport
        assert present == {route.records_filename, route.manifest_filename,
                           route.archive_filename}, (version, present)


@pytest.mark.parametrize("route,other_grant", [
    (None, "_v2_3_grant"), (None, "_v2_2_grant"),
], ids=["v2_1-route-refuses-v2_3-grant", "v2_1-route-refuses-v2_2-grant"])
def test_the_v2_1_route_refuses_a_later_grant(cohort, selection, tmp_path, route,
                                              other_grant):
    grant = globals()[other_grant](cohort, selection, tmp_path,
                                   name=f"x-{other_grant}")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id="cross-a",
             output_dir=tmp_path / "never")


@pytest.mark.parametrize("grant_maker", ["_grant", "_v2_2_grant"],
                         ids=["v2_1-grant", "v2_2-grant"])
def test_the_v2_3_route_refuses_an_earlier_grant(cohort, selection, tmp_path,
                                                 grant_maker):
    grant = globals()[grant_maker](cohort, selection, tmp_path,
                                   name=f"y-{grant_maker}")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id="cross-b",
             output_dir=tmp_path / "never", route=lcal.CALIBRATION_ROUTE_V2_3)


def test_each_version_loader_refuses_the_other_two(cohort, selection, tmp_path):
    v3 = _run(cohort, selection,
              _v2_3_grant(cohort, selection, tmp_path, name="k4"), tmp_path,
              run_id="calib-iso-3", route=lcal.CALIBRATION_ROUTE_V2_3)
    with pytest.raises(ls.ScreenInputError,
                       match="holds no universe_classifier_calibration_manifest.json"):
        lcal.require_classifier_calibration_run(v3.result.run_dir)
    with pytest.raises(ls.ScreenInputError, match="holds no universe_classifier_manifest.json"):
        lcl.require_classifier_run(v3.result.run_dir)


# --- ADR-130: the same route and the same selection, at V2.4 -----------------------


def _v2_4_grant(cohort, selection, tmp_path, *, name="calibration-gov-v2-4"):
    """The V2.3 grant re-pointed at the V2.4 prompt and the 0.3.0 contracts."""
    from dynamic_ai_products.classifier_contract_set import V2_4
    base = _grant(cohort, selection, tmp_path, name=name).authorization
    payload = dict(base)
    payload.update({
        "authorization_contract":
            "universe_classifier_calibration_authorization@0.4.0",
        "output_contract": V2_4.record_contract,
        "taxonomy_version": V2_4.taxonomy_version,
        "prompt_template_path": V2_4.prompt_path,
        "prompt_template_sha256":
            sha256((ROOT / V2_4.prompt_path).read_bytes()).hexdigest(),
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    ((tmp_path / name) / "calibration_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=tmp_path / name,
                           reference="calibration_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def test_the_v2_4_route_classifies_the_same_unchanged_selection(cohort, selection,
                                                                tmp_path):
    grant = _v2_4_grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path, run_id="calibration-v2-4",
               route=lcal.CALIBRATION_ROUTE_V2_4)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == \
        "universe_classifier_calibration_manifest@0.4.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.3.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_4"
    assert manifest["prompt_template_path"].endswith("v2_4.md")
    assert manifest["tier_rules_version"] == "universe_classifier_tier_rules_v2_1"
    assert manifest["calibration_selection"]["selection_sha256"] == selection.sha256
    assert manifest["promotable"] is False
    assert manifest["covers_full_cohort"] is False
    records = [json.loads(x) for x in
               (run.result.run_dir / lcal.CALIBRATION_ROUTE_V2_4.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(selection.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.3.0"
               for r in records)


def test_the_four_versions_write_four_disjoint_file_sets(cohort, selection,
                                                         tmp_path):
    runs = {
        "v2_1": _run(cohort, selection, _grant(cohort, selection, tmp_path, name="q1"),
                     tmp_path, run_id="calib-q1"),
        "v2_2": _run(cohort, selection,
                     _v2_2_grant(cohort, selection, tmp_path, name="q2"), tmp_path,
                     run_id="calib-q2", route=lcal.CALIBRATION_ROUTE_V2_2),
        "v2_3": _run(cohort, selection,
                     _v2_3_grant(cohort, selection, tmp_path, name="q3"), tmp_path,
                     run_id="calib-q3", route=lcal.CALIBRATION_ROUTE_V2_3),
        "v2_4": _run(cohort, selection,
                     _v2_4_grant(cohort, selection, tmp_path, name="q4"), tmp_path,
                     run_id="calib-q4", route=lcal.CALIBRATION_ROUTE_V2_4),
    }
    names = {}
    for version, run in runs.items():
        assert run.result.status == "completed", (version, run.result.receipt)
        names[version] = {p.name for p in run.result.run_dir.iterdir()}
    transport = {"provider_captures", "universe_screen_capture_ledger.jsonl"}
    versions = list(runs)
    for i, a in enumerate(versions):
        for b in versions[i + 1:]:
            shared = (names[a] & names[b]) - transport
            assert not shared, (a, b, shared)
    routes = {"v2_1": lcal.CALIBRATION_ROUTE, "v2_2": lcal.CALIBRATION_ROUTE_V2_2,
              "v2_3": lcal.CALIBRATION_ROUTE_V2_3, "v2_4": lcal.CALIBRATION_ROUTE_V2_4}
    for version, run in runs.items():
        route = routes[version]
        present = names[version] - transport
        assert present == {route.records_filename, route.manifest_filename,
                           route.archive_filename}, (version, present)


@pytest.mark.parametrize("grant_maker", ["_grant", "_v2_2_grant", "_v2_3_grant"],
                         ids=["v2_1-grant", "v2_2-grant", "v2_3-grant"])
def test_the_v2_4_route_refuses_every_earlier_grant(cohort, selection, tmp_path,
                                                    grant_maker):
    grant = globals()[grant_maker](cohort, selection, tmp_path,
                                   name=f"z-{grant_maker}")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id=f"cross-c-{grant_maker}",
             output_dir=tmp_path / f"never-{grant_maker}",
             route=lcal.CALIBRATION_ROUTE_V2_4)


@pytest.mark.parametrize("tag,route", [
    ("v2_1", None), ("v2_2", lcal.CALIBRATION_ROUTE_V2_2),
    ("v2_3", lcal.CALIBRATION_ROUTE_V2_3),
], ids=["v2_1-route", "v2_2-route", "v2_3-route"])
def test_every_earlier_route_refuses_the_v2_4_grant(cohort, selection, tmp_path,
                                                    tag, route):
    grant = _v2_4_grant(cohort, selection, tmp_path, name=f"w-{tag}")
    kwargs = {} if route is None else {"route": route}
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id=f"cross-d-{tag}",
             output_dir=tmp_path / f"never-earlier-{tag}", **kwargs)


def test_every_calibration_loader_refuses_the_other_three(cohort, selection,
                                                          tmp_path):
    v4 = _run(cohort, selection,
              _v2_4_grant(cohort, selection, tmp_path, name="q5"), tmp_path,
              run_id="calib-iso-4", route=lcal.CALIBRATION_ROUTE_V2_4)
    assert lcal.require_classifier_calibration_run(
        v4.result.run_dir, route=lcal.CALIBRATION_ROUTE_V2_4) == \
        v4.result.manifest_path
    for other in (lcal.CALIBRATION_ROUTE, lcal.CALIBRATION_ROUTE_V2_2,
                  lcal.CALIBRATION_ROUTE_V2_3):
        with pytest.raises(ls.ScreenInputError,
                           match=f"holds no {other.manifest_filename}"):
            lcal.require_classifier_calibration_run(v4.result.run_dir, route=other)
    with pytest.raises(ls.ScreenInputError,
                       match="holds no universe_classifier_v2_4_manifest.json"):
        lcl.require_classifier_run(v4.result.run_dir, route=lcl.BASE_ROUTE_V2_4)


def test_the_v2_4_calibration_cli_mode_reaches_its_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "classify-universe-calibration-v2-4":\n'
            "        return _main_classify_universe_calibration(\n"
            "            args, route=CALIBRATION_ROUTE_V2_4)") in source


# --- ADR-132: the calibration route at V2.5 -----------------------------------------

from dynamic_ai_products import classifier_span_index as _csi  # noqa: E402


def _v2_5_span_script(cohort, selection):
    """A V2.5 script: every row answers with a span identifier, never with text."""
    from test_lineage_classifier_v2_1 import _span_axes_payload
    rules = _csi.load_span_index_rules(ROOT)
    packets = cohort.release.packets
    return {row["cik"]: {"text": _span_axes_payload(
        packets[(row["cik"], row["accession"])], rules)}
        for row in selection.rows}


def _v2_5_grant(cohort, selection, tmp_path, *, name="calibration-gov-v2-5"):
    """The V2.4 calibration grant re-pointed at V2.5 and its pinned span index."""
    from dynamic_ai_products.classifier_contract_set import V2_5
    rules = _csi.load_span_index_rules(ROOT)
    base = _grant(cohort, selection, tmp_path, name=name).authorization
    payload = dict(base)
    payload.update({
        "authorization_contract":
            "universe_classifier_calibration_authorization@0.5.0",
        "output_contract": V2_5.record_contract,
        "taxonomy_version": V2_5.taxonomy_version,
        "prompt_template_path": V2_5.prompt_path,
        "prompt_template_sha256":
            sha256((ROOT / V2_5.prompt_path).read_bytes()).hexdigest(),
        "span_index_version": rules.version,
        "span_index_sha256": rules.sha256,
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    ((tmp_path / name) / "calibration_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=tmp_path / name,
                           reference="calibration_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def test_the_v2_5_route_classifies_the_same_unchanged_selection(cohort, selection,
                                                                tmp_path):
    grant = _v2_5_grant(cohort, selection, tmp_path)
    run = _run(cohort, selection, grant, tmp_path, run_id="calibration-v2-5",
               script=_v2_5_span_script(cohort, selection),
               route=lcal.CALIBRATION_ROUTE_V2_5)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == \
        "universe_classifier_calibration_manifest@0.5.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.4.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_5"
    assert manifest["span_index_version"] == "universe_classifier_span_index_v1"
    assert manifest["promotable"] is False
    assert manifest["covers_full_cohort"] is False
    assert manifest["reconciliation"][
        "every classified row's evidence resolves in its packet"] is True
    records = [json.loads(x) for x in
               (run.result.run_dir / lcal.CALIBRATION_ROUTE_V2_5.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(selection.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.4.0"
               for r in records)


def test_the_five_versions_write_five_disjoint_file_sets(cohort, selection, tmp_path):
    runs = {
        "v2_1": _run(cohort, selection, _grant(cohort, selection, tmp_path, name="p1"),
                     tmp_path, run_id="calib-p1"),
        "v2_2": _run(cohort, selection,
                     _v2_2_grant(cohort, selection, tmp_path, name="p2"), tmp_path,
                     run_id="calib-p2", route=lcal.CALIBRATION_ROUTE_V2_2),
        "v2_3": _run(cohort, selection,
                     _v2_3_grant(cohort, selection, tmp_path, name="p3"), tmp_path,
                     run_id="calib-p3", route=lcal.CALIBRATION_ROUTE_V2_3),
        "v2_4": _run(cohort, selection,
                     _v2_4_grant(cohort, selection, tmp_path, name="p4"), tmp_path,
                     run_id="calib-p4", route=lcal.CALIBRATION_ROUTE_V2_4),
        "v2_5": _run(cohort, selection,
                     _v2_5_grant(cohort, selection, tmp_path, name="p5"), tmp_path,
                     run_id="calib-p5", route=lcal.CALIBRATION_ROUTE_V2_5,
                     script=_v2_5_span_script(cohort, selection)),
    }
    names = {}
    for version, run in runs.items():
        assert run.result.status == "completed", (version, run.result.receipt)
        names[version] = {p.name for p in run.result.run_dir.iterdir()}
    transport = {"provider_captures", "universe_screen_capture_ledger.jsonl"}
    versions = list(runs)
    for i, a in enumerate(versions):
        for b in versions[i + 1:]:
            assert not (names[a] & names[b]) - transport, (a, b)


@pytest.mark.parametrize("grant_maker", ["_grant", "_v2_2_grant", "_v2_3_grant",
                                         "_v2_4_grant"],
                         ids=["v2_1", "v2_2", "v2_3", "v2_4"])
def test_the_v2_5_route_refuses_every_earlier_grant(cohort, selection, tmp_path,
                                                    grant_maker):
    grant = globals()[grant_maker](cohort, selection, tmp_path, name=f"q-{grant_maker}")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id=f"cross-e-{grant_maker}",
             output_dir=tmp_path / f"never-e-{grant_maker}",
             script=_v2_5_span_script(cohort, selection),
             route=lcal.CALIBRATION_ROUTE_V2_5)


@pytest.mark.parametrize("tag,route", [
    ("v2_1", None), ("v2_2", lcal.CALIBRATION_ROUTE_V2_2),
    ("v2_3", lcal.CALIBRATION_ROUTE_V2_3), ("v2_4", lcal.CALIBRATION_ROUTE_V2_4),
], ids=["v2_1", "v2_2", "v2_3", "v2_4"])
def test_every_earlier_route_refuses_the_v2_5_grant(cohort, selection, tmp_path,
                                                    tag, route):
    grant = _v2_5_grant(cohort, selection, tmp_path, name=f"r-{tag}")
    kwargs = {} if route is None else {"route": route}
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id=f"cross-f-{tag}",
             output_dir=tmp_path / f"never-f-{tag}", **kwargs)


def test_every_calibration_loader_refuses_the_other_four(cohort, selection, tmp_path):
    v5 = _run(cohort, selection, _v2_5_grant(cohort, selection, tmp_path, name="p6"),
              tmp_path, run_id="calib-iso-5", route=lcal.CALIBRATION_ROUTE_V2_5,
              script=_v2_5_span_script(cohort, selection))
    assert lcal.require_classifier_calibration_run(
        v5.result.run_dir, route=lcal.CALIBRATION_ROUTE_V2_5) == \
        v5.result.manifest_path
    for other in (lcal.CALIBRATION_ROUTE, lcal.CALIBRATION_ROUTE_V2_2,
                  lcal.CALIBRATION_ROUTE_V2_3, lcal.CALIBRATION_ROUTE_V2_4):
        with pytest.raises(ls.ScreenInputError,
                           match=f"holds no {other.manifest_filename}"):
            lcal.require_classifier_calibration_run(v5.result.run_dir, route=other)


def test_the_v2_5_calibration_cli_mode_reaches_its_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "classify-universe-calibration-v2-5":\n'
            "        return _main_classify_universe_calibration(\n"
            "            args, route=CALIBRATION_ROUTE_V2_5)") in source


# --- ADR-133: the calibration route at V2.6 -----------------------------------------


def _v2_6_grant(cohort, selection, tmp_path, *, name="calibration-gov-v2-6"):
    """The V2.5 calibration grant re-pointed at the 0.6.0 authorization contract.

    Everything the model touches is V2.5's: same prompt, same span index, same
    0.4.0 output contract, same taxonomy. Only the contract id moves.
    """
    from dynamic_ai_products.classifier_contract_set import V2_6
    rules = _csi.load_span_index_rules(ROOT)
    base = _grant(cohort, selection, tmp_path, name=name).authorization
    payload = dict(base)
    payload.update({
        "authorization_contract":
            "universe_classifier_calibration_authorization@0.6.0",
        "output_contract": V2_6.record_contract,
        "taxonomy_version": V2_6.taxonomy_version,
        "prompt_template_path": V2_6.prompt_path,
        "prompt_template_sha256":
            sha256((ROOT / V2_6.prompt_path).read_bytes()).hexdigest(),
        "span_index_version": rules.version,
        "span_index_sha256": rules.sha256,
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    ((tmp_path / name) / "calibration_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=tmp_path / name,
                           reference="calibration_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def _v2_6_script(cohort, selection, **overrides):
    script = _v2_5_span_script(cohort, selection)
    for cik, extra in overrides.items():
        script[cik] = {**script[cik], **extra}
    return script


def _manifest_validator(rel):
    from jsonschema import Draft202012Validator, FormatChecker
    return Draft202012Validator(
        json.loads((ROOT / rel).read_text(encoding="utf-8")),
        format_checker=FormatChecker())


def test_one_quota_retry_completes_under_v2_6_with_a_null_report(cohort, selection,
                                                                 tmp_path):
    """The exact shape that stopped the live V2.5 calibration."""
    grant = _v2_6_grant(cohort, selection, tmp_path)
    flaky = selection.rows[0]["cik"]
    run = _run(cohort, selection, grant, tmp_path, run_id="calibration-v2-6-retry",
               script=_v2_6_script(cohort, selection, **{flaky: {"quota_failures": 1}}),
               route=lcal.CALIBRATION_ROUTE_V2_6)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    accounting = run.result.request_accounting
    assert accounting["rows_generate_retried"] == 1
    assert accounting["provider_attempts_made"] == len(selection.rows) + 1
    assert accounting["tokens_out_reported"] is None
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == \
        "universe_classifier_calibration_manifest@0.6.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.4.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_5"
    assert manifest["span_index_version"] == "universe_classifier_span_index_v1"
    assert manifest["request_accounting"]["tokens_out_reported"] is None
    assert list(_manifest_validator(
        "schemas/universe_classifier_calibration_manifest.v6.schema.json")
        .iter_errors(manifest)) == []


def test_that_same_manifest_is_refused_by_the_v2_5_contract(cohort, selection,
                                                            tmp_path):
    """The live failure, pinned: the fix is a successor, not a relaxation."""
    grant = _v2_6_grant(cohort, selection, tmp_path, name="gov-v2-6-cross")
    flaky = selection.rows[0]["cik"]
    run = _run(cohort, selection, grant, tmp_path, run_id="calibration-v2-6-cross",
               script=_v2_6_script(cohort, selection, **{flaky: {"quota_failures": 1}}),
               route=lcal.CALIBRATION_ROUTE_V2_6)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    errors = list(_manifest_validator(
        "schemas/universe_classifier_calibration_manifest.v5.schema.json")
        .iter_errors(manifest))
    assert any("tokens_out_reported" in "/".join(str(x) for x in e.absolute_path)
               for e in errors)


def test_no_retry_reports_an_integer_under_v2_6(cohort, selection, tmp_path):
    grant = _v2_6_grant(cohort, selection, tmp_path, name="gov-v2-6-clean")
    run = _run(cohort, selection, grant, tmp_path, run_id="calibration-v2-6-clean",
               script=_v2_5_span_script(cohort, selection),
               route=lcal.CALIBRATION_ROUTE_V2_6)
    assert run.result.status == "completed", run.result.receipt
    accounting = run.result.request_accounting
    assert accounting["rows_generate_retried"] == 0
    assert isinstance(accounting["tokens_out_reported"], int)
    assert accounting["rows_usage_verified"] == len(selection.rows)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert list(_manifest_validator(
        "schemas/universe_classifier_calibration_manifest.v6.schema.json")
        .iter_errors(manifest)) == []


def test_conservative_accounting_still_bounds_a_retry_run(cohort, selection,
                                                          tmp_path):
    """A null report must not buy headroom."""
    grant = _v2_6_grant(cohort, selection, tmp_path, name="gov-v2-6-budget")
    flaky = selection.rows[0]["cik"]
    run = _run(cohort, selection, grant, tmp_path, run_id="calibration-v2-6-budget",
               script=_v2_6_script(cohort, selection, **{flaky: {"quota_failures": 1}}),
               route=lcal.CALIBRATION_ROUTE_V2_6)
    assert run.result.status == "completed", run.result.receipt
    a = run.result.request_accounting
    assert a["tokens_out_reported"] is None
    for enforced in ("tokens_in_measured", "cost_micros_settled",
                     "rows_usage_verified", "external_requests_made",
                     "count_attempts_made", "provider_attempts_made"):
        assert isinstance(a[enforced], int), enforced
    assert a["tokens_in_measured"] <= a["budget_max_input_tokens"]
    assert a["cost_micros_settled"] <= a["budget_max_estimated_cost_micros"]
    assert a["external_requests_made"] <= a["external_request_cap"]
    assert a["count_attempts_made"] <= a["count_attempt_cap"]
    assert a["provider_attempts_made"] <= a["provider_attempt_cap"]
    # exactly the retried row failed to verify
    assert a["rows_usage_verified"] == len(selection.rows) - 1


def test_the_v2_6_run_keeps_the_inherited_span_archival_checks(cohort, selection,
                                                               tmp_path):
    """V2.6 changes a manifest property, not the evidence protocol."""
    grant = _v2_6_grant(cohort, selection, tmp_path, name="gov-v2-6-span")
    run = _run(cohort, selection, grant, tmp_path, run_id="calibration-v2-6-span",
               script=_v2_5_span_script(cohort, selection),
               route=lcal.CALIBRATION_ROUTE_V2_6)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["reconciliation"][
        "every classified row's evidence resolves in its packet"] is True
    records = [json.loads(x) for x in
               (run.result.run_dir / lcal.CALIBRATION_ROUTE_V2_6.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    checked = 0
    for record in records:
        if record["record_kind"] != "classified":
            continue
        packet = cohort.release.packets[(record["cik"], record["accession"])]
        for item in record["axes"]["evidence"]:
            assert "span_ref" in item and "quote" not in item
            assert _csi.verify_stored_span(item, packet)
            checked += 1
    assert checked


@pytest.mark.parametrize("grant_maker", ["_grant", "_v2_2_grant", "_v2_3_grant",
                                         "_v2_4_grant", "_v2_5_grant"],
                         ids=["v2_1", "v2_2", "v2_3", "v2_4", "v2_5"])
def test_the_v2_6_route_refuses_every_earlier_grant(cohort, selection, tmp_path,
                                                    grant_maker):
    grant = globals()[grant_maker](cohort, selection, tmp_path, name=f"s-{grant_maker}")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id=f"cross-g-{grant_maker}",
             output_dir=tmp_path / f"never-g-{grant_maker}",
             script=_v2_5_span_script(cohort, selection),
             route=lcal.CALIBRATION_ROUTE_V2_6)


@pytest.mark.parametrize("tag,route", [
    ("v2_1", None), ("v2_2", lcal.CALIBRATION_ROUTE_V2_2),
    ("v2_3", lcal.CALIBRATION_ROUTE_V2_3), ("v2_4", lcal.CALIBRATION_ROUTE_V2_4),
    ("v2_5", lcal.CALIBRATION_ROUTE_V2_5),
], ids=["v2_1", "v2_2", "v2_3", "v2_4", "v2_5"])
def test_every_earlier_route_refuses_the_v2_6_grant(cohort, selection, tmp_path,
                                                    tag, route):
    grant = _v2_6_grant(cohort, selection, tmp_path, name=f"t-{tag}")
    kwargs = {} if route is None else {"route": route}
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, selection, grant, tmp_path, run_id=f"cross-h-{tag}",
             output_dir=tmp_path / f"never-h-{tag}",
             script=_v2_5_span_script(cohort, selection), **kwargs)


def test_every_calibration_loader_refuses_the_other_five(cohort, selection, tmp_path):
    v6 = _run(cohort, selection, _v2_6_grant(cohort, selection, tmp_path, name="s6"),
              tmp_path, run_id="calib-iso-6", route=lcal.CALIBRATION_ROUTE_V2_6,
              script=_v2_5_span_script(cohort, selection))
    assert lcal.require_classifier_calibration_run(
        v6.result.run_dir, route=lcal.CALIBRATION_ROUTE_V2_6) == \
        v6.result.manifest_path
    for other in (lcal.CALIBRATION_ROUTE, lcal.CALIBRATION_ROUTE_V2_2,
                  lcal.CALIBRATION_ROUTE_V2_3, lcal.CALIBRATION_ROUTE_V2_4,
                  lcal.CALIBRATION_ROUTE_V2_5):
        with pytest.raises(ls.ScreenInputError,
                           match=f"holds no {other.manifest_filename}"):
            lcal.require_classifier_calibration_run(v6.result.run_dir, route=other)


def test_the_v2_6_calibration_cli_mode_reaches_its_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "classify-universe-calibration-v2-6":\n'
            "        return _main_classify_universe_calibration(\n"
            "            args, route=CALIBRATION_ROUTE_V2_6)") in source
