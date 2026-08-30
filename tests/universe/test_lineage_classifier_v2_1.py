"""ADR-126 tests: admission is context, evidence is the packet, tier is derived.

Everything is offline. The cohort is a real ADR-125 cohort built from a real
ADR-124-shaped release and a real hash-bound overlay over genuine fixture
packets, the transport is the same fake the screen suites use, and no test
builds a ``genai.Client``, resolves a credential or opens a socket.

Two properties get the most attention, because the whole design rests on them:
an admission — model or human — can be contradicted by the complete Item 1
packet, and no model output can ever set a tier.
"""

from __future__ import annotations

import json
import sys
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products import classifier_candidate_cohort as ccc
from dynamic_ai_products import human_review_overlay as hro
from dynamic_ai_products import lineage_classifier_v2_1 as lcl
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products import lineage_screen_release as lrel
from dynamic_ai_products.providers import screen_count_retry_policy as cp
from dynamic_ai_products.providers import screen_retry_policy as gp
from dynamic_ai_products.providers.client_contract_v2 import CLIENT_CONTRACT_V2_ID
from dynamic_ai_products.providers.retry_policy import (
    RATE_LIMIT_POLICY_VERSION,
    RETRY_POLICY_VERSION,
)
from dynamic_ai_products.universe import lineage_screen as ls

sys.path.insert(0, str(Path(__file__).parent))

from test_human_review_overlay import (  # noqa: E402
    CLOCK,
    ROOT,
    _entry,
    _ledger,
    _quote,
    _sha,
)
from test_lineage_screen_continuation_v5 import _EmptyBodyFactory  # noqa: E402
from test_lineage_screen_live import (  # noqa: E402
    PACKET_FIXTURES,
    VERTEX_LOCATION,
    VERTEX_PROJECT,
    _contract_digest,
    _endpoints,
    _fixture_doc,
)
from test_lineage_screen_live_v3 import _v5_run  # noqa: E402

RECORD_SCHEMA = json.loads((ROOT / lcl.RECORD_SCHEMA).read_text(encoding="utf-8"))
MANIFEST_SCHEMA = json.loads((ROOT / lcl.MANIFEST_SCHEMA).read_text(encoding="utf-8"))
PROMPT = (ROOT / lcl.PROMPT_PATH).read_text(encoding="utf-8")

#: The release the cohort is derived from. Two rows are admitted by a validated
#: model screen, two by a reviewer, and two are excluded — so every test runs
#: against a cohort whose origins are genuinely mixed.
RELEASE_PLAN = (
    ("base_valid", "LIKELY_ELIGIBLE"),
    ("repaired", "BOUNDARY_OR_UNCERTAIN"),
    ("base_valid", "LIKELY_INELIGIBLE"),
    ("unresolved_after_repair", "LIKELY_ELIGIBLE"),
    ("unresolved_after_repair", "BOUNDARY_OR_UNCERTAIN"),
    ("unresolved_after_repair", "LIKELY_INELIGIBLE"),
)

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
    assert not added, f"the classifier path imported google: {sorted(added)}"


# --- packets, release, overlay, cohort ---------------------------------------------


@pytest.fixture(scope="module")
def packet_cohort(tmp_path_factory):
    """Six real fixture packets, so every quote resolves against real text."""
    source, template = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    docs = []
    for index in range(len(RELEASE_PLAN)):
        cik = f"{8200000000 + index:010d}"
        docs.append((source, dict(template, cik=cik, accession=f"{cik}-22-000001")))
    built = _v5_run(tmp_path_factory.mktemp("adr126-packets"), [docs])
    assert len(built.packets) == len(RELEASE_PLAN)
    return built


def _release_row(packet, origin, status):
    """One release row, with real screen evidence behind the validated ones."""
    raw = json.dumps({"screen_status": status}, sort_keys=True)
    validated = origin in ("base_valid", "repaired")
    base = {"run_id": "synthetic-base-run",
            "raw_response_id": f"base-{packet['cik']}",
            "raw_response_sha256": _sha(raw.encode()),
            "failure_reason_code": None if origin == "base_valid"
            else "quote_resolution_failure",
            "source_row_ordinal": 1}
    repair = {"run_id": "synthetic-repair-run",
              "raw_response_id": f"repair-{packet['cik']}",
              "raw_response_sha256": _sha((raw + "r").encode()),
              "failure_reason_code": None if origin == "repaired"
              else "quote_resolution_failure",
              "source_row_ordinal": None}
    screen_output = None
    if validated:
        screen_output = {
            "screen_status": status,
            "plausible_customer_facing_digital_product": True,
            "candidate_customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
            "positive_evidence": [{
                "passage_id": packet["passages"][0]["passage_id"],
                "quote": _quote(packet), "source_id": packet["source_id"],
                "supported_claim": "The cited passage supports the screen."}],
            "negative_or_boundary_evidence": [], "missing_evidence": [],
            "confidence": "high"}
    return {
        "record_contract": lrel.RECORD_CONTRACT, "release_origin": origin,
        "record_kind": "screened_packet" if validated
        else "model_evidence_unverified",
        "cik": packet["cik"], "company_id": packet["company_id"],
        "accession": packet["accession"], "form": packet["form"],
        "baseline_filing_date": packet["baseline_filing_date"],
        "source_id": packet["source_id"], "packet_sha256": packet["packet_sha256"],
        "prompt_sha256": _sha(b"p"),
        "model_route": {"provider": "google_vertex_ai",
                        "model_label": "gemini-2.5-flash"},
        "screen_status": status if validated else None,
        "screen_output": screen_output,
        "failure_reason_code": None if validated else "quote_resolution_failure",
        "failure_detail": None if validated else "detail",
        "truncation_evidence": None,
        "release_provenance": {
            "base": base,
            "repair": repair if origin in ("repaired", "unresolved_after_repair")
            else None},
    }


@pytest.fixture
def release(packet_cohort, tmp_path):
    packets = packet_cohort.packets
    rows = [_release_row(p, origin, status)
            for p, (origin, status) in zip(packets, RELEASE_PLAN)]
    d = tmp_path / "release" / "synthetic-release"
    d.mkdir(parents=True, exist_ok=True)
    records = "".join(json.dumps(r, sort_keys=True, separators=(",", ":")) + "\n"
                      for r in rows).encode()
    (d / lrel.RELEASE_RECORDS_FILENAME).write_bytes(records)
    base_dir = tmp_path / "base" / "synthetic-base-run"
    base_dir.mkdir(parents=True, exist_ok=True)
    base_manifest = {
        "manifest_contract": "universe_screen_continuation_manifest@0.12.0",
        "run_id": "synthetic-base-run",
        "packet_manifest_path": str(packet_cohort.manifest_path),
        "packet_manifest_sha256": _sha(
            Path(packet_cohort.manifest_path).read_bytes()),
        "packets_jsonl_sha256": ls.load_packet_run(
            ROOT, packet_cohort.manifest_path).packets_jsonl_sha256,
    }
    from dynamic_ai_products import lineage_screen_continuation_v5 as lc5
    base_path = base_dir / lc5.CONTINUATION_V5_MANIFEST_FILENAME
    base_path.write_bytes(
        (json.dumps(base_manifest, indent=2, sort_keys=True) + "\n").encode())
    validated = [r for r in rows if r["screen_status"]]
    manifest = {
        "manifest_contract": lrel.MANIFEST_CONTRACT,
        "release_id": "synthetic-release", "release_kind": "screen_release_v1",
        "counts": {
            "planned_rows": len(rows), "cohort_rows": len(rows),
            "base_valid": sum(r["release_origin"] == "base_valid" for r in rows),
            "repaired": sum(r["release_origin"] == "repaired" for r in rows),
            "unresolved_after_repair": sum(
                r["release_origin"] == "unresolved_after_repair" for r in rows),
            "insufficient_evidence": 0, "model_output_truncated": 0,
            "valid_screened_rows": len(validated),
            "max_unresolved_after_repair": 211,
            "by_screen_status": {
                s: sum(r["screen_status"] == s for r in rows)
                for s in ("LIKELY_ELIGIBLE", "LIKELY_INELIGIBLE",
                          "BOUNDARY_OR_UNCERTAIN")}},
        "sources": {"base": {"run_id": "synthetic-base-run",
                             "manifest_path": str(base_path),
                             "manifest_sha256": _sha(base_path.read_bytes())}},
        "output_hashes": {lrel.RELEASE_RECORDS_FILENAME: _sha(records)},
    }
    path = d / lrel.RELEASE_MANIFEST_FILENAME
    path.write_bytes((json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode())
    return SimpleNamespace(dir=d, path=path, manifest=manifest, rows=rows,
                           sha256=_sha(path.read_bytes()),
                           packets={(p["cik"], p["accession"]): p for p in packets})


@pytest.fixture
def cohort(release, packet_cohort, tmp_path):
    """A real overlay and a real ADR-125 cohort over that release."""
    unresolved = [release.packets[(r["cik"], r["accession"])] for r in release.rows
                  if r["release_origin"] == "unresolved_after_repair"]
    decisions = ["LIKELY_ELIGIBLE", "BOUNDARY_OR_UNCERTAIN", "LIKELY_INELIGIBLE"]
    entries = [_entry(release, packet, decision)
               for packet, decision in zip(unresolved, decisions)]
    overlay = hro.build_human_review_overlay(
        repo_root=ROOT, release_manifest_path=release.path,
        release_manifest_sha256=release.sha256,
        ledger_path=_ledger(tmp_path, entries), output_dir=tmp_path / "overlays",
        overlay_id="overlay-fixture", clock=CLOCK)
    built = ccc.build_classifier_candidate_cohort(
        repo_root=ROOT, release_manifest_path=release.path,
        release_manifest_sha256=release.sha256,
        overlay_manifest_path=overlay.manifest_path,
        overlay_manifest_sha256=_sha(overlay.manifest_path.read_bytes()),
        output_dir=tmp_path / "cohorts", cohort_id="cohort-fixture", clock=CLOCK)
    rows = [json.loads(x) for x in
            (built.cohort_dir / ccc.COHORT_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert built.counts["model_screen_admitted"] == 2
    assert built.counts["human_review_admitted"] == 2
    return SimpleNamespace(
        packets=packet_cohort, release=release, overlay=overlay,
        overlay_path=overlay.manifest_path, path=built.manifest_path,
        sha256=_sha(built.manifest_path.read_bytes()), rows=rows,
        packet_manifest_path=packet_cohort.manifest_path,
        packet_manifest_sha256=packet_cohort.manifest_sha256)


# --- governance --------------------------------------------------------------------


def _grant(cohort, tmp_path, *, mutate=None, unresolved=1, truncated=1, unusable=1,
           name="classifier-gov"):
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
    enablement_raw = (json.dumps(enablement, indent=2, sort_keys=True)
                      + "\n").encode()
    (root / "screen_adapter_enablement.json").write_bytes(enablement_raw)
    rules = __import__(
        "dynamic_ai_products.classifier_tier_engine", fromlist=["load_tier_rules"]
    ).load_tier_rules(ROOT)
    rows = len(cohort.rows)
    payload = {
        "authorization_contract": lcl.AUTHORIZATION_CONTRACT,
        "authorization_id": "classifier-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": "release_or_research_production",
        "run_kind": lcl.RUN_KIND, "promotable": False,
        "output_contract": lcl.RECORD_CONTRACT,
        "cohort_id": "cohort-fixture", "cohort_manifest_sha256": cohort.sha256,
        "overlay_id": cohort.overlay.overlay_id if hasattr(
            cohort.overlay, "overlay_id") else "overlay-fixture",
        "overlay_manifest_sha256": _sha(cohort.overlay_path.read_bytes()),
        "release_id": "synthetic-release",
        "release_manifest_sha256": cohort.release.sha256,
        "packet_manifest_sha256": cohort.packet_manifest_sha256,
        "prompt_template_path": lcl.PROMPT_PATH,
        "prompt_template_sha256":
            sha256((ROOT / lcl.PROMPT_PATH).read_bytes()).hexdigest(),
        "tier_rules_version": rules.version, "tier_rules_sha256": rules.sha256,
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
        "max_provider_unresolved": unresolved,
        "max_model_output_truncated": truncated,
        "max_model_output_unusable": unusable,
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
    (root / "classifier_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=root, reference="classifier_authorization.json",
                           sha256=_sha(raw), authorization=payload)


# --- scripted model output ---------------------------------------------------------


def _safe_quote(packet, ref):
    """A real span, even when the reference is one the packet never displays."""
    ordinal = int(ref[1:]) - 1
    if ordinal >= len(packet["passages"]):
        ordinal = 0
    return packet["passages"][ordinal]["text"][:40]


def _axes_payload(packet, *, centrality="CORE", structure="PURE_PLAY",
                  materiality="DOMINANT", product=True, orientation="B2B",
                  archetypes=("FUNCTIONAL_SOFTWARE",), quote=None, extra=None,
                  ref="P001", evidence=True):
    payload = {
        "customer_value_archetypes": list(archetypes),
        "software_centrality": centrality,
        "complementary_dependencies": ["NONE_OR_STANDARD_COMPUTE"],
        "firm_structure": structure, "commercial_materiality": materiality,
        "customer_facing_functional_product": product,
        "economically_eligible": product, "data_eligible": True,
        "customer_market_orientation": orientation,
        "boundary_flags": [], "contradictions": [],
        "evidence": [{"axis": "centrality", "passage_ref": ref,
                      "quote": _safe_quote(packet, ref) if quote is None
                      else quote,
                      "supported_claim": "The cited passage supports this axis."}]
        if evidence else [],
        "confidence": "high",
    }
    if extra is not None:
        payload.update(extra)
    return json.dumps(payload)


def _script(cohort, **overrides):
    packets = cohort.release.packets
    script = {row["cik"]: {"text": _axes_payload(
        packets[(row["cik"], row["accession"])])} for row in cohort.rows}
    for cik, extra in overrides.items():
        script[cik] = {**script.get(cik, {}), **extra}
    return script


def _run(cohort, grant, tmp_path, *, script=None, run_id="classifier-run",
         dry_run=False, output_dir=None, route=None):
    events: list = []
    factory = _EmptyBodyFactory(
        script if script is not None else _script(cohort), events)
    result = lcl.run_lineage_classifier(
        repo_root=ROOT, cohort_manifest_path=cohort.path,
        overlay_manifest_path=cohort.overlay_path,
        release_manifest_path=cohort.release.path,
        packet_manifest_path=cohort.packet_manifest_path,
        governance_root=grant.root, authorization_reference=grant.reference,
        authorization_sha256=grant.sha256,
        output_dir=output_dir or (tmp_path / "classifier-out"), run_id=run_id,
        clock=CLOCK, dry_run=dry_run, client_factory=factory,
        sleep=lambda s: events.append(("wait", s)),
        **({"route": route} if route is not None else {}))
    return SimpleNamespace(result=result, factory=factory, events=events)


def _records(result):
    return [json.loads(x) for x in
            (result.run_dir / lcl.CLASSIFIER_RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if x.strip()]


def _row_of(cohort, origin, status=None):
    for row in cohort.rows:
        if row["admission_origin"] == origin and (
                status is None or row["screen_status"] == status):
            return row
    raise AssertionError(f"no {origin} row with status {status}")


# --- the happy path ----------------------------------------------------------------


def test_both_origins_are_classified_against_the_complete_packet(cohort, tmp_path):
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()

    records = _records(run.result)
    validator = Draft202012Validator(RECORD_SCHEMA, format_checker=FormatChecker())
    for record in records:
        validator.validate(record)
    assert len(records) == len(cohort.rows)
    assert [(r["cik"], r["accession"]) for r in records] == [
        (r["cik"], r["accession"]) for r in cohort.rows]
    counts = run.result.counts
    assert counts["classified"] == len(records)
    assert counts["by_admission_origin"] == {"model_screen": 2, "human_review": 2}
    assert counts["by_tier"]["TIER_A"] == len(records)
    assert all(v is True for v in run.result.reconciliation.values())


def test_the_manifest_validates_and_pins_every_source(cohort, tmp_path):
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    Draft202012Validator(MANIFEST_SCHEMA,
                         format_checker=FormatChecker()).validate(manifest)
    assert manifest["promotable"] is False
    assert manifest["sources"]["cohort"]["manifest_sha256"] == cohort.sha256
    assert manifest["sources"]["release"]["manifest_sha256"] == cohort.release.sha256
    assert manifest["bounded_outcomes"]["tier_excludes_market_orientation"] is True
    assert manifest["tier_rules_version"] == "universe_classifier_tier_rules_v2_1"
    for filename, recorded in manifest["output_hashes"].items():
        assert _sha((run.result.run_dir / filename).read_bytes()) == recorded
    assert lcl.require_classifier_run(run.result.run_dir) == run.result.manifest_path


def test_every_record_carries_its_admission_and_its_derived_tier(cohort, tmp_path):
    grant = _grant(cohort, tmp_path)
    records = _records(_run(cohort, grant, tmp_path).result)
    from dynamic_ai_products.classifier_tier_engine import (
        derive_tier,
        load_tier_rules,
    )
    rules = load_tier_rules(ROOT)
    for record in records:
        admission = record["admission_provenance"]
        assert admission["non_authoritative"] is True
        if admission["admission_origin"] == "model_screen":
            assert admission["model_screen"]["raw_response_id"]
            assert admission["human_review"] is None
        else:
            assert admission["human_review"]["reviewer_id"]
            assert admission["model_screen"] is None
        assert "tier" not in record["axes"]
        assert derive_tier(record["axes"], rules).tier == record["tier"]
        assert record["tier_rule_trace"]["tier_rules_sha256"] == rules.sha256
        assert record["output_provenance"]["origin"] == "model_called"


def test_the_rendered_admission_context_comes_from_its_own_origin(cohort, tmp_path):
    from dynamic_ai_products.lineage_classifier_v2_1 import (
        _admission_for,
        load_cohort_inputs,
    )
    grant = _grant(cohort, tmp_path)
    inputs = load_cohort_inputs(
        ROOT, cohort_manifest_path=cohort.path, cohort_manifest_sha256=cohort.sha256,
        overlay_manifest_path=cohort.overlay_path,
        overlay_manifest_sha256=grant.authorization["overlay_manifest_sha256"],
        release_manifest_path=cohort.release.path,
        release_manifest_sha256=cohort.release.sha256)
    screened = _row_of(cohort, "model_screen")
    reviewed = _row_of(cohort, "human_review")
    for row, expected in ((screened, "Earlier screen context:"),
                          (reviewed, "Earlier human-review context:")):
        packet = cohort.release.packets[(row["cik"], row["accession"])]
        admission = _admission_for(row, inputs, packet)
        rendered, _refs = lcl.render_classifier_prompt(PROMPT, packet, admission)
        assert expected in rendered
        assert admission["context_evidence"]
        for item in admission["context_evidence"]:
            assert f'- {item["passage_ref"]}: "{item["quote"]}"' in rendered


def test_a_dry_run_renders_every_row_and_sends_nothing(cohort, tmp_path):
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path, dry_run=True)
    assert run.result.status == "dry_run" and run.result.run_dir is None
    assert run.factory.opens == run.factory.generate_calls == 0
    assert run.result.request_accounting["model_called_rows"] == len(cohort.rows)
    _assert_no_google()


# --- an admission is context, not authority ----------------------------------------


def test_a_model_screen_admission_can_be_contradicted(cohort, tmp_path):
    """The screen said eligible; the complete packet says otherwise."""
    row = _row_of(cohort, "model_screen")
    packet = cohort.release.packets[(row["cik"], row["accession"])]
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path, script=_script(cohort, **{
        row["cik"]: {"text": _axes_payload(
            packet, centrality="PERIPHERAL", structure="SOFTWARE_PERIPHERAL",
            materiality="MINOR", product=False, archetypes=(),
            extra={"contradictions": [
                "The admission context overstates the digital product."]})}}))
    assert run.result.status == "completed"
    record = next(r for r in _records(run.result) if r["cik"] == row["cik"])
    assert record["admission_provenance"]["admitted_status"] == row["screen_status"]
    assert record["tier"] == "EXCLUDED"
    assert record["axes"]["contradictions"]


def test_a_human_review_admission_can_be_contradicted(cohort, tmp_path):
    row = _row_of(cohort, "human_review")
    packet = cohort.release.packets[(row["cik"], row["accession"])]
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path, script=_script(cohort, **{
        row["cik"]: {"text": _axes_payload(
            packet, centrality="ENABLING", structure="MIXED_SEPARABLE",
            materiality="MINOR")}}))
    assert run.result.status == "completed"
    record = next(r for r in _records(run.result) if r["cik"] == row["cik"])
    assert record["tier"] == "TIER_C"
    assert record["admission_provenance"]["human_review"]["reviewer_id"]


def test_market_orientation_moves_no_row_between_tiers(cohort, tmp_path):
    tiers = {}
    for index, orientation in enumerate(("B2B", "B2C", "MIXED", "UNKNOWN")):
        grant = _grant(cohort, tmp_path, name=f"gov-{index}")
        packets = cohort.release.packets
        script = {row["cik"]: {"text": _axes_payload(
            packets[(row["cik"], row["accession"])], orientation=orientation)}
            for row in cohort.rows}
        run = _run(cohort, grant, tmp_path, script=script,
                   run_id=f"orientation-run-{index}")
        assert run.result.status == "completed"
        tiers[orientation] = [r["tier"] for r in _records(run.result)]
    assert len(set(map(tuple, tiers.values()))) == 1


# --- a model may not set a tier ----------------------------------------------------


@pytest.mark.parametrize("field", ["tier", "candidate_tier", "tier_rule_trace"])
def test_a_model_supplied_tier_is_refused(cohort, tmp_path, field):
    row = cohort.rows[0]
    packet = cohort.release.packets[(row["cik"], row["accession"])]
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path, script=_script(cohort, **{
        row["cik"]: {"text": _axes_payload(packet, extra={field: "TIER_A"})}}))
    assert run.result.status == "completed"
    record = next(r for r in _records(run.result) if r["cik"] == row["cik"])
    assert record["record_kind"] == "model_output_unusable"
    assert record["failure_reason_code"] == "model_emitted_tier"
    assert record["tier"] is None and record["axes"] is None


# --- outputs that cannot be used ---------------------------------------------------


@pytest.mark.parametrize("payload_kwargs,reason", [
    ({"quote": "text that appears in no passage"}, "quote_resolution_failure"),
    ({"ref": "P999"}, "quote_resolution_failure"),
    ({"archetypes": ("FUNCTIONAL_SOFTWARE", "DATA_ANALYTICS_PRODUCT",
                     "CONTENT_CATALOG", "ECOMMERCE_RETAIL", "OTHER")},
     "axes_contract_violation"),
    ({"centrality": "MOSTLY_CORE"}, "axes_contract_violation"),
    ({"evidence": False}, "unsupported_conclusion"),
])
def test_an_output_that_cannot_be_used_is_recorded_not_repaired(
        cohort, tmp_path, payload_kwargs, reason):
    row = cohort.rows[0]
    packet = cohort.release.packets[(row["cik"], row["accession"])]
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path, script=_script(cohort, **{
        row["cik"]: {"text": _axes_payload(packet, **payload_kwargs)}}))
    assert run.result.status == "completed"
    record = next(r for r in _records(run.result) if r["cik"] == row["cik"])
    assert record["record_kind"] == "model_output_unusable"
    assert record["failure_reason_code"] == reason
    assert record["output_provenance"]["raw_response_id"]


def _widen(packet):
    """Split the fixture packet's single passage into two displayed passages.

    Every committed packet fixture renders one passage, so the case a correct
    quote cited under the wrong reference is unreachable through them. That is
    the failure 119 screen rows produced, so it is exercised here rather than
    left untested.
    """
    text = packet["passages"][0]["text"]
    half = max(len(text) // 2, 40)
    first, second = text[:half], text[half:]
    assert second and second not in first
    return dict(packet, passages=[
        dict(packet["passages"][0], passage_id="synthetic-passage-1", text=first),
        dict(packet["passages"][0], passage_id="synthetic-passage-2", text=second)])


def _axes_validator():
    return Draft202012Validator(
        json.loads((ROOT / lcl.AXES_SCHEMA).read_text(encoding="utf-8")),
        format_checker=FormatChecker())


def test_a_correct_quote_under_the_wrong_reference_is_refused(packet_cohort):
    """The span is genuine; it simply does not live in the passage cited."""
    packet = _widen(packet_cohort.packets[0])
    second = packet["passages"][1]["text"][:40]
    payload = _axes_payload(packet, ref="P001", quote=second)
    with pytest.raises(lcl.AxesValidationFailure) as excinfo:
        lcl.validate_axes_output(payload, packet, _axes_validator())
    assert excinfo.value.reason_code == "quote_resolution_failure"


def test_the_same_quote_resolves_under_its_own_reference(packet_cohort):
    packet = _widen(packet_cohort.packets[0])
    second = packet["passages"][1]["text"][:40]
    axes = lcl.validate_axes_output(
        _axes_payload(packet, ref="P002", quote=second), packet, _axes_validator())
    assert axes["evidence"][0]["passage_ref"] == "P002"


def test_unusable_output_beyond_its_tolerance_stops_the_run(cohort, tmp_path):
    grant = _grant(cohort, tmp_path, unusable=1)
    packets = cohort.release.packets
    script = {row["cik"]: {"text": _axes_payload(
        packets[(row["cik"], row["accession"])],
        quote="text that appears in no passage")} for row in cohort.rows}
    run = _run(cohort, grant, tmp_path, script=script)
    assert run.result.status == "failed"
    receipt = run.result.receipt
    assert receipt["reason_code"] == "model_output_unusable_budget_exhausted"
    assert receipt["max_model_output_unusable"] == 1
    assert not (run.result.run_dir / lcl.CLASSIFIER_MANIFEST_FILENAME).exists()
    assert not (run.result.run_dir / lcl.CLASSIFIER_RECORDS_FILENAME).exists()
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        lcl.require_classifier_run(run.result.run_dir)


# --- bounded provider outcomes -----------------------------------------------------


def test_a_provider_that_never_resolves_is_bounded(cohort, tmp_path):
    row = cohort.rows[0]
    grant = _grant(cohort, tmp_path, unresolved=1)
    run = _run(cohort, grant, tmp_path,
               script=_script(cohort, **{row["cik"]: {"quota_failures": 5}}))
    assert run.result.status == "completed", run.result.receipt
    record = next(r for r in _records(run.result) if r["cik"] == row["cik"])
    assert record["record_kind"] == "provider_unresolved"
    assert record["failure_reason_code"] == "vertex_quota_exhausted"
    assert record["provider_attempt_telemetry"]["generate_attempts"] == 5
    assert record["axes"] is None and record["tier"] is None
    assert run.result.counts["provider_unresolved"] == 1


def test_provider_unresolved_beyond_its_tolerance_stops_the_run(cohort, tmp_path):
    grant = _grant(cohort, tmp_path, unresolved=0)
    run = _run(cohort, grant, tmp_path,
               script=_script(cohort, **{cohort.rows[0]["cik"]:
                                         {"quota_failures": 5}}))
    assert run.result.status == "failed"
    assert run.result.receipt["reason_code"] == "provider_unresolved_budget_exhausted"


def test_a_truncated_output_is_recorded_with_its_evidence(cohort, tmp_path):
    row = cohort.rows[0]
    grant = _grant(cohort, tmp_path, truncated=1)
    run = _run(cohort, grant, tmp_path,
               script=_script(cohort, **{row["cik"]: {"truncated": 1}}))
    assert run.result.status == "completed", run.result.receipt
    record = next(r for r in _records(run.result) if r["cik"] == row["cik"])
    assert record["record_kind"] == "model_output_truncated"
    assert record["failure_reason_code"] == "max_tokens"
    evidence = record["truncation_evidence"]
    assert evidence["finish_reason"] == "MAX_TOKENS"
    assert (run.result.run_dir / evidence["capture_reference"]).is_file()


def test_truncation_beyond_its_tolerance_stops_the_run(cohort, tmp_path):
    grant = _grant(cohort, tmp_path, truncated=0)
    run = _run(cohort, grant, tmp_path,
               script=_script(cohort, **{cohort.rows[0]["cik"]: {"truncated": 1}}))
    assert run.result.status == "failed"
    assert run.result.receipt["reason_code"] == \
        "model_output_truncated_budget_exhausted"


# --- preflight refusals, all before a run directory exists --------------------------


def _refused(cohort, tmp_path, grant, match, **kwargs):
    output_dir = tmp_path / "never-created"
    with pytest.raises(ls.ScreenInputError, match=match):
        _run(cohort, grant, tmp_path, output_dir=output_dir, **kwargs)
    assert not output_dir.exists(), "a refused run created a run directory"
    _assert_no_google()


@pytest.mark.parametrize("field,value,match", [
    ("cohort_manifest_sha256", "0" * 64, "not the artifact that was authorized"),
    ("release_manifest_sha256", "0" * 64, "not the artifact that was authorized"),
    ("overlay_manifest_sha256", "0" * 64, "not the artifact that was authorized"),
    ("packet_manifest_sha256", "0" * 64, "different packet cohort"),
    ("prompt_template_sha256", "0" * 64, "committed v2_1 classifier prompt"),
    ("tier_rules_sha256", "0" * 64, "committed tier-rule config"),
    ("tier_rules_version", "other_rules", "committed tier-rule config"),
    ("taxonomy_version", "other_taxonomy", "policy versions, ceilings or contracts"),
    ("logical_row_cap", 99, r"row\(s\) but this route's scope holds"),
    ("count_attempt_cap", 99, "count_attempt_cap must be exactly"),
    ("provider_attempt_cap", 99, "provider_attempt_cap must be exactly"),
    ("budget_max_external_requests", 99, "budget_max_external_requests must be"),
    ("cohort_id", "other-cohort", "different cohort"),
    # These two are refused by the authorization contract itself, before any
    # runtime comparison: the grant cannot even name another prompt or route.
    ("prompt_template_path", "prompts/discovery/universe_full_classification.md",
     "violates its contract"),
    ("model_route", {"provider": "x", "model_label": "y"},
     "violates its contract"),
])
def test_a_grant_that_does_not_match_the_committed_artifacts_is_refused(
        cohort, tmp_path, field, value, match):
    grant = _grant(cohort, tmp_path,
                   mutate=lambda p: p.__setitem__(field, value))
    _refused(cohort, tmp_path, grant, match)


def test_a_promotable_classifier_grant_is_refused(cohort, tmp_path):
    grant = _grant(cohort, tmp_path,
                   mutate=lambda p: p.__setitem__("promotable", True))
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, grant, tmp_path, output_dir=tmp_path / "never")


def test_an_expired_grant_is_refused(cohort, tmp_path):
    grant = _grant(cohort, tmp_path, mutate=lambda p: p.__setitem__(
        "expires_at", "2026-08-02T00:00:00+00:00"))
    _refused(cohort, tmp_path, grant, "outside its effective window")


def test_a_missing_overlay_decision_is_refused(cohort, tmp_path):
    """A human-review row whose decision the overlay does not hold."""
    grant = _grant(cohort, tmp_path)
    row = _row_of(cohort, "human_review")
    decisions_path = cohort.overlay_path.parent / hro.OVERLAY_DECISIONS_FILENAME
    kept = [line for line in decisions_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and json.loads(line)["cik"] != row["cik"]]
    decisions_path.write_bytes(("\n".join(kept) + "\n").encode())
    _refused(cohort, tmp_path, grant, "no longer hashes")


def test_a_cohort_row_whose_screen_response_is_not_the_release_row_is_refused(
        cohort, tmp_path, monkeypatch):
    grant = _grant(cohort, tmp_path)
    original = lcl._admission_for

    def _tamper(row, inputs, packet):
        if row["admission_origin"] == "model_screen":
            row = dict(row, admission_provenance=dict(
                row["admission_provenance"],
                model_screen={"raw_response_id": "foreign-response",
                              "raw_response_sha256": "0" * 64}))
        return original(row, inputs, packet)

    monkeypatch.setattr(lcl, "_admission_for", _tamper)
    _refused(cohort, tmp_path, grant, "not the response the release row records")


def test_an_unknown_admission_origin_is_refused(cohort, tmp_path, monkeypatch):
    grant = _grant(cohort, tmp_path)
    original = lcl._admission_for
    monkeypatch.setattr(lcl, "_admission_for", lambda row, inputs, packet: original(
        dict(row, admission_origin="assumed"), inputs, packet))
    _refused(cohort, tmp_path, grant, "does not know how to render")


def test_a_drifted_cohort_records_file_is_refused(cohort, tmp_path):
    grant = _grant(cohort, tmp_path)
    records = cohort.path.parent / ccc.COHORT_RECORDS_FILENAME
    records.write_bytes(records.read_bytes() + b"\n")
    _refused(cohort, tmp_path, grant, "no longer hashes")


def test_a_run_id_that_already_exists_is_refused(cohort, tmp_path):
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path)
    assert run.result.status == "completed"
    with pytest.raises(FileExistsError):
        _run(cohort, grant, tmp_path)


# --- what the run spends -----------------------------------------------------------


def test_the_run_stays_inside_every_authorized_ceiling(cohort, tmp_path):
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path)
    accounting = run.result.request_accounting
    assert accounting["model_called_rows"] == len(cohort.rows)
    assert accounting["count_attempts_made"] == len(cohort.rows)
    assert accounting["provider_attempts_made"] == len(cohort.rows)
    assert accounting["external_requests_made"] <= \
        accounting["external_request_cap"]
    ledger = [json.loads(x) for x in
              (run.result.run_dir / ll.CAPTURE_LEDGER_FILENAME)
              .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(ledger) == accounting["external_requests_made"]
    assert {e["operation_label"] for e in ledger} == {"count_tokens",
                                                      "generate_content"}


def test_the_archive_holds_one_line_per_answered_row(cohort, tmp_path):
    grant = _grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path)
    entries = [json.loads(x) for x in
               (run.result.run_dir / lcl.CLASSIFIER_RAW_RESPONSES_FILENAME)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(entries) == len(cohort.rows)
    for entry in entries:
        assert _sha(entry["raw_response"].encode()) == entry["raw_response_sha256"]


# --- the CLI boundary --------------------------------------------------------------


def _cli_module():
    """Import the pipeline CLI once, by path, without executing main()."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "adr126_cli", ROOT / "pipelines" / "00_build_company_universe.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _classifier_argv(tmp_path, *, mode="classify-universe-cohort", extra=()):
    return [
        "--mode", mode,
        "--cohort-manifest", str(tmp_path / "cohort.json"),
        "--overlay-manifest", str(tmp_path / "overlay.json"),
        "--release-manifest", str(tmp_path / "release.json"),
        "--packet-manifest", str(tmp_path / "packets.json"),
        "--governance-root", str(tmp_path / "gov"),
        "--screen-authorization", "classifier_authorization.json",
        "--screen-authorization-sha256", "0" * 64,
        "--output-dir", str(tmp_path / "out"),
        "--run-id", "cli-gating-fixture",
        *extra,
    ]


@pytest.mark.parametrize("mode,extra", [
    ("classify-universe-cohort", ()),
    ("classify-universe-cohort-continuation",
     ("--source-run-dir", "/tmp/source", "--source-receipt-sha256", "0" * 64)),
])
def test_each_classifier_mode_accepts_the_flags_it_requires(tmp_path, mode, extra):
    """ADR-123's lesson: a mode unreachable through its own flags is a defect."""
    cli = _cli_module()
    args = cli.build_parser().parse_args(_classifier_argv(tmp_path, mode=mode,
                                                          extra=extra))
    assert cli._reject_cross_mode_flags(args) is None
    _assert_no_google()


@pytest.mark.parametrize("flag", [
    "--cohort-manifest", "--overlay-manifest", "--release-manifest",
    "--packet-manifest", "--governance-root", "--screen-authorization",
    "--screen-authorization-sha256",
])
def test_the_classifier_mode_still_requires_every_flag(tmp_path, flag):
    cli = _cli_module()
    argv = _classifier_argv(tmp_path)
    index = argv.index(flag)
    del argv[index:index + 2]
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(argv))
    assert verdict and "requires" in verdict and flag in verdict


def test_the_classifier_mode_refuses_a_selection_artifact(tmp_path):
    """A classifier run takes a cohort; a selection artifact is a screen input."""
    cli = _cli_module()
    argv = _classifier_argv(
        tmp_path, extra=("--selection-artifact", str(tmp_path / "selection.json")))
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(argv))
    assert verdict and "--selection-artifact" in verdict


@pytest.mark.parametrize("flag", ["--release-manifest-sha256",
                                  "--overlay-manifest-sha256"])
def test_the_classifier_mode_refuses_a_second_source_of_digest_truth(tmp_path, flag):
    """Digests come from the authorization, never from a flag beside it."""
    cli = _cli_module()
    argv = _classifier_argv(tmp_path, extra=(flag, "0" * 64))
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(argv))
    assert verdict and flag in verdict


def test_the_base_classifier_mode_refuses_a_source_run(tmp_path):
    cli = _cli_module()
    argv = _classifier_argv(tmp_path, extra=("--source-run-dir", "/tmp/source"))
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(argv))
    assert verdict and "--source-run-dir" in verdict


def test_no_other_mode_accepts_the_cohort_flag(tmp_path):
    cli = _cli_module()
    argv = ["--mode", "build-screen-release",
            "--cohort-manifest", str(tmp_path / "cohort.json"),
            "--output-dir", str(tmp_path / "out"), "--run-id", "cli-gating-fixture"]
    verdict = cli._reject_cross_mode_flags(cli.build_parser().parse_args(argv))
    assert verdict and "--cohort-manifest" in verdict


def test_the_cli_declares_both_modes():
    cli = _cli_module()
    parser = cli.build_parser()
    choices = next(a.choices for a in parser._actions if a.dest == "mode")
    assert "classify-universe-cohort" in choices
    assert "classify-universe-cohort-continuation" in choices
    # ADR-127 added three calibration modes; ADR-128 three V2.2 modes;
    # ADR-129 three V2.3 modes and two review modes; ADR-130 four V2.4 modes.
    assert "Sixty-five mutually exclusive modes" in cli.__doc__


# --- ADR-129: the base route at V2.3 ----------------------------------------------


def _v2_3_base_grant(cohort, tmp_path, *, name="base-gov-v2-3"):
    """The V2.1 base grant re-pointed at the V2.3 prompt and 0.2.0 contracts."""
    from dynamic_ai_products.classifier_contract_set import V2_3
    base = _grant(cohort, tmp_path, name=name).authorization
    payload = dict(base)
    payload.update({
        "authorization_contract": "universe_classifier_authorization@0.3.0",
        "output_contract": V2_3.record_contract,
        "taxonomy_version": V2_3.taxonomy_version,
        "prompt_template_path": V2_3.prompt_path,
        "prompt_template_sha256":
            sha256((ROOT / V2_3.prompt_path).read_bytes()).hexdigest(),
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    ((tmp_path / name) / "classifier_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=tmp_path / name,
                           reference="classifier_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def test_the_v2_3_base_route_completes_end_to_end(cohort, tmp_path):
    grant = _v2_3_base_grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path, run_id="base-v2-3",
               route=lcl.BASE_ROUTE_V2_3)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == "universe_classifier_manifest@0.3.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.2.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_2"
    assert manifest["prompt_template_path"].endswith("v2_3.md")
    assert manifest["tier_rules_version"] == "universe_classifier_tier_rules_v2_1"
    records = [json.loads(x) for x in
               (run.result.run_dir / lcl.BASE_ROUTE_V2_3.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(cohort.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.2.0"
               for r in records)


def test_the_v2_1_base_loader_refuses_a_v2_3_run(cohort, tmp_path):
    grant = _v2_3_base_grant(cohort, tmp_path, name="base-gov-iso")
    run = _run(cohort, grant, tmp_path, run_id="base-v2-3-iso",
               route=lcl.BASE_ROUTE_V2_3)
    with pytest.raises(ls.ScreenInputError, match="holds no universe_classifier_manifest.json"):
        lcl.require_classifier_run(run.result.run_dir)


def test_the_v2_3_base_route_refuses_a_v2_1_grant(cohort, tmp_path):
    grant = _grant(cohort, tmp_path, name="base-gov-old")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, grant, tmp_path, run_id="base-cross",
             output_dir=tmp_path / "never", route=lcl.BASE_ROUTE_V2_3)


# --- ADR-130: the base route at V2.4 ----------------------------------------------


def _v2_4_base_grant(cohort, tmp_path, *, name="base-gov-v2-4"):
    """The V2.1 base grant re-pointed at the V2.4 prompt and 0.3.0 contracts."""
    from dynamic_ai_products.classifier_contract_set import V2_4
    base = _grant(cohort, tmp_path, name=name).authorization
    payload = dict(base)
    payload.update({
        "authorization_contract": "universe_classifier_authorization@0.4.0",
        "output_contract": V2_4.record_contract,
        "taxonomy_version": V2_4.taxonomy_version,
        "prompt_template_path": V2_4.prompt_path,
        "prompt_template_sha256":
            sha256((ROOT / V2_4.prompt_path).read_bytes()).hexdigest(),
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    ((tmp_path / name) / "classifier_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=tmp_path / name,
                           reference="classifier_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def test_the_v2_4_base_route_completes_end_to_end(cohort, tmp_path):
    grant = _v2_4_base_grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path, run_id="base-v2-4",
               route=lcl.BASE_ROUTE_V2_4)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == "universe_classifier_manifest@0.4.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.3.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_4"
    assert manifest["prompt_template_path"].endswith("v2_4.md")
    assert manifest["tier_rules_version"] == "universe_classifier_tier_rules_v2_1"
    records = [json.loads(x) for x in
               (run.result.run_dir / lcl.BASE_ROUTE_V2_4.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(cohort.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.3.0"
               for r in records)


def test_the_v2_4_run_hashes_only_its_own_filenames(cohort, tmp_path):
    grant = _v2_4_base_grant(cohort, tmp_path, name="base-gov-v2-4-hash")
    run = _run(cohort, grant, tmp_path, run_id="base-v2-4-hash",
               route=lcl.BASE_ROUTE_V2_4)
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["output_hashes"]) == {
        lcl.BASE_ROUTE_V2_4.records_filename,
        lcl.BASE_ROUTE_V2_4.archive_filename,
        "universe_screen_capture_ledger.jsonl"}
    for filename, digest in manifest["output_hashes"].items():
        assert _sha((run.result.run_dir / filename).read_bytes()) == digest


@pytest.mark.parametrize("route", [
    lcl.BASE_ROUTE, lcl.BASE_ROUTE_V2_2, lcl.BASE_ROUTE_V2_3,
], ids=["v2_1", "v2_2", "v2_3"])
def test_every_earlier_base_loader_refuses_a_v2_4_run(cohort, tmp_path, route):
    grant = _v2_4_base_grant(cohort, tmp_path, name=f"base-gov-iso-{route.contracts.version_id}")
    run = _run(cohort, grant, tmp_path, run_id=f"base-v2-4-iso-{route.contracts.version_id}",
               route=lcl.BASE_ROUTE_V2_4)
    with pytest.raises(ls.ScreenInputError, match="holds no "):
        lcl.require_classifier_run(run.result.run_dir, route=route)


def test_the_v2_4_base_loader_refuses_a_v2_3_run(cohort, tmp_path):
    grant = _v2_3_base_grant(cohort, tmp_path, name="base-gov-v2-3-iso-4")
    run = _run(cohort, grant, tmp_path, run_id="base-v2-3-for-v2-4",
               route=lcl.BASE_ROUTE_V2_3)
    with pytest.raises(ls.ScreenInputError,
                       match="holds no universe_classifier_v2_4_manifest.json"):
        lcl.require_classifier_run(run.result.run_dir, route=lcl.BASE_ROUTE_V2_4)


def test_the_v2_4_base_route_refuses_a_v2_3_grant(cohort, tmp_path):
    grant = _v2_3_base_grant(cohort, tmp_path, name="base-gov-old-v2-3")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, grant, tmp_path, run_id="base-cross-v2-4",
             output_dir=tmp_path / "never-v2-4", route=lcl.BASE_ROUTE_V2_4)


def test_the_v2_3_base_route_refuses_a_v2_4_grant(cohort, tmp_path):
    grant = _v2_4_base_grant(cohort, tmp_path, name="base-gov-new-v2-4")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, grant, tmp_path, run_id="base-cross-v2-3",
             output_dir=tmp_path / "never-v2-3", route=lcl.BASE_ROUTE_V2_3)


def test_the_v2_4_cli_mode_reaches_the_v2_4_route():
    cli = _cli_module()
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "classify-universe-cohort-v2-4":\n'
            "        return _main_classify_universe_cohort("
            "args, route=BASE_ROUTE_V2_4)") in source
    choices = next(a.choices for a in cli.build_parser()._actions
                   if a.dest == "mode")
    assert "classify-universe-cohort-v2-4" in choices


# --- ADR-132: the base route at V2.5 ------------------------------------------------

from dynamic_ai_products import classifier_span_index as _csi  # noqa: E402


def _span_rules():
    return _csi.load_span_index_rules(ROOT)


def _v2_8_axes_payload(packet, rules, *, interpretation="The selected span supports this axis.",
                       omit_interpretation=False, span_ref=None, ref=None, extra=None):
    """A V2.8 response: identifiers plus an optional, unbounded interpretation.

    ``omit_interpretation`` leaves the property out entirely, which the V2.8
    contract permits and the V2.5 one did not.
    """
    index = _csi.build_span_index(packet, rules)
    chosen_ref = ref or sorted(index.passages)[0]
    item = {"axis": "centrality", "passage_ref": chosen_ref,
            "span_ref": span_ref or f"{chosen_ref}:S001"}
    if not omit_interpretation:
        item["span_interpretation"] = interpretation
    payload = {
        "customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "software_centrality": "CORE",
        "complementary_dependencies": ["NONE_OR_STANDARD_COMPUTE"],
        "firm_structure": "PURE_PLAY", "commercial_materiality": "DOMINANT",
        "customer_facing_functional_product": True,
        "economically_eligible": True, "data_eligible": True,
        "customer_market_orientation": "B2B",
        "boundary_flags": [], "contradictions": [],
        "evidence": [item],
        "confidence": "high",
    }
    if extra is not None:
        payload.update(extra)
    return json.dumps(payload)


def _span_axes_payload(packet, rules, *, span_ref=None, ref=None, extra=None,
                       evidence=True):
    """A V2.5 response: identifiers only, no source text anywhere in it."""
    index = _csi.build_span_index(packet, rules)
    chosen_ref = ref or sorted(index.passages)[0]
    payload = {
        "customer_value_archetypes": ["FUNCTIONAL_SOFTWARE"],
        "software_centrality": "CORE",
        "complementary_dependencies": ["NONE_OR_STANDARD_COMPUTE"],
        "firm_structure": "PURE_PLAY", "commercial_materiality": "DOMINANT",
        "customer_facing_functional_product": True,
        "economically_eligible": True, "data_eligible": True,
        "customer_market_orientation": "B2B",
        "boundary_flags": [], "contradictions": [],
        "evidence": [{"axis": "centrality", "passage_ref": chosen_ref,
                      "span_ref": span_ref or f"{chosen_ref}:S001",
                      "supported_claim": "The selected span supports this axis."}]
        if evidence else [],
        "confidence": "high",
    }
    if extra is not None:
        payload.update(extra)
    return json.dumps(payload)


def _span_script(cohort, **overrides):
    rules = _span_rules()
    packets = cohort.release.packets
    script = {row["cik"]: {"text": _span_axes_payload(
        packets[(row["cik"], row["accession"])], rules)} for row in cohort.rows}
    for cik, extra in overrides.items():
        script[cik] = {**script.get(cik, {}), **extra}
    return script


def _v2_5_base_grant(cohort, tmp_path, *, name="base-gov-v2-5"):
    """The V2.4 base grant re-pointed at V2.5 and its pinned span index."""
    from dynamic_ai_products.classifier_contract_set import V2_5
    rules = _span_rules()
    base = _grant(cohort, tmp_path, name=name).authorization
    payload = dict(base)
    payload.update({
        "authorization_contract": "universe_classifier_authorization@0.5.0",
        "output_contract": V2_5.record_contract,
        "taxonomy_version": V2_5.taxonomy_version,
        "prompt_template_path": V2_5.prompt_path,
        "prompt_template_sha256":
            sha256((ROOT / V2_5.prompt_path).read_bytes()).hexdigest(),
        "span_index_version": rules.version,
        "span_index_sha256": rules.sha256,
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    ((tmp_path / name) / "classifier_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=tmp_path / name,
                           reference="classifier_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def test_the_v2_5_base_route_completes_end_to_end(cohort, tmp_path):
    grant = _v2_5_base_grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path, run_id="base-v2-5",
               script=_span_script(cohort), route=lcl.BASE_ROUTE_V2_5)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == "universe_classifier_manifest@0.5.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.4.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_5"
    assert manifest["span_index_version"] == "universe_classifier_span_index_v1"
    assert manifest["span_index_sha256"] == _span_rules().sha256
    records = [json.loads(x) for x in
               (run.result.run_dir / lcl.BASE_ROUTE_V2_5.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(cohort.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.4.0"
               for r in records)


def test_the_stored_v2_5_evidence_round_trips_from_the_packet(cohort, tmp_path):
    """The property that makes a stored row verifiable without the segmenter."""
    grant = _v2_5_base_grant(cohort, tmp_path, name="base-gov-v2-5-rt")
    run = _run(cohort, grant, tmp_path, run_id="base-v2-5-rt",
               script=_span_script(cohort), route=lcl.BASE_ROUTE_V2_5)
    rules = _span_rules()
    records = [json.loads(x) for x in
               (run.result.run_dir / lcl.BASE_ROUTE_V2_5.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    checked = 0
    for record in records:
        if record["record_kind"] != "classified":
            continue
        assert record["span_index_version"] == rules.version
        packet = cohort.release.packets[(record["cik"], record["accession"])]
        index = _csi.build_span_index(packet, rules)
        for item in record["axes"]["evidence"]:
            assert _csi.verify_stored_span(item, packet)
            spans = index.passages[item["passage_ref"]]
            assert spans.normalized[item["span_start"]:item["span_end"]] == \
                item["resolved_quote"]
            assert item["span_sha256"] == sha256(
                item["resolved_quote"].encode("utf-8")).hexdigest()
            assert "quote" not in item
            checked += 1
    assert checked


def test_the_model_never_supplied_the_stored_text(cohort, tmp_path):
    """The archived model bytes carry the identifier and none of the text."""
    grant = _v2_5_base_grant(cohort, tmp_path, name="base-gov-v2-5-arch")
    run = _run(cohort, grant, tmp_path, run_id="base-v2-5-arch",
               script=_span_script(cohort), route=lcl.BASE_ROUTE_V2_5)
    archive = (run.result.run_dir / lcl.BASE_ROUTE_V2_5.archive_filename
               ).read_text(encoding="utf-8")
    for line in archive.splitlines():
        if not line.strip():
            continue
        raw = json.loads(json.loads(line)["raw_response"])
        for item in raw["evidence"]:
            assert set(item) == {"axis", "passage_ref", "span_ref", "supported_claim"}


def test_a_v2_5_grant_naming_a_different_span_index_is_refused(cohort, tmp_path):
    grant = _v2_5_base_grant(cohort, tmp_path, name="base-gov-v2-5-drift")
    payload = dict(grant.authorization, span_index_sha256="0" * 64)
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (grant.root / "classifier_authorization.json").write_bytes(raw)
    drifted = SimpleNamespace(root=grant.root,
                              reference="classifier_authorization.json",
                              sha256=_sha(raw), authorization=payload)
    # span_index_sha256 is a const in the v5 contract, so the grant is refused
    # at schema validation before the runner compares it to the config on disk.
    # The runner's own comparison still matters for the other direction: a config
    # edited after the grant was written.
    with pytest.raises(ls.ScreenInputError, match="span_index_sha256"):
        _run(cohort, drifted, tmp_path, run_id="base-v2-5-drift",
             script=_span_script(cohort), output_dir=tmp_path / "never-drift",
             route=lcl.BASE_ROUTE_V2_5)


def test_a_model_quote_route_refuses_a_grant_naming_a_span_index(cohort, tmp_path):
    """The earlier contracts are additionalProperties:false, so this is structural."""
    grant = _v2_4_base_grant(cohort, tmp_path, name="base-gov-v2-4-span")
    payload = dict(grant.authorization,
                   span_index_version="universe_classifier_span_index_v1")
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    (grant.root / "classifier_authorization.json").write_bytes(raw)
    mixed = SimpleNamespace(root=grant.root,
                            reference="classifier_authorization.json",
                            sha256=_sha(raw), authorization=payload)
    with pytest.raises(ls.ScreenInputError, match="span_index_version"):
        _run(cohort, mixed, tmp_path, run_id="base-v2-4-span",
             output_dir=tmp_path / "never-span", route=lcl.BASE_ROUTE_V2_4)


@pytest.mark.parametrize("route", [
    lcl.BASE_ROUTE, lcl.BASE_ROUTE_V2_2, lcl.BASE_ROUTE_V2_3, lcl.BASE_ROUTE_V2_4,
], ids=["v2_1", "v2_2", "v2_3", "v2_4"])
def test_every_earlier_base_loader_refuses_a_v2_5_run(cohort, tmp_path, route):
    tag = route.contracts.version_id
    grant = _v2_5_base_grant(cohort, tmp_path, name=f"base-gov-v2-5-iso-{tag}")
    run = _run(cohort, grant, tmp_path, run_id=f"base-v2-5-iso-{tag}",
               script=_span_script(cohort), route=lcl.BASE_ROUTE_V2_5)
    with pytest.raises(ls.ScreenInputError, match="holds no "):
        lcl.require_classifier_run(run.result.run_dir, route=route)


def test_the_v2_5_base_loader_refuses_a_v2_4_run(cohort, tmp_path):
    grant = _v2_4_base_grant(cohort, tmp_path, name="base-gov-v2-4-for-v2-5")
    run = _run(cohort, grant, tmp_path, run_id="base-v2-4-for-v2-5",
               route=lcl.BASE_ROUTE_V2_4)
    with pytest.raises(ls.ScreenInputError,
                       match="holds no universe_classifier_v2_5_manifest.json"):
        lcl.require_classifier_run(run.result.run_dir, route=lcl.BASE_ROUTE_V2_5)


def test_the_v2_5_cli_mode_reaches_the_v2_5_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "classify-universe-cohort-v2-5":\n'
            "        return _main_classify_universe_cohort("
            "args, route=BASE_ROUTE_V2_5)") in source
    cli = _cli_module()
    choices = next(a.choices for a in cli.build_parser()._actions if a.dest == "mode")
    assert "classify-universe-cohort-v2-5" in choices
    assert len(choices) == 80


# --- ADR-132 correction: archival verification needs the packet and nothing else ----


def _v2_5_completed(cohort, tmp_path, tag):
    grant = _v2_5_base_grant(cohort, tmp_path, name=f"base-gov-{tag}")
    run = _run(cohort, grant, tmp_path, run_id=f"base-{tag}",
               script=_span_script(cohort), route=lcl.BASE_ROUTE_V2_5)
    assert run.result.status == "completed", run.result.receipt
    records = [json.loads(x) for x in
               (run.result.run_dir / lcl.BASE_ROUTE_V2_5.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    return [r for r in records if r["record_kind"] == "classified"]


def test_v2_5_reconciliation_holds_when_the_segmenter_cannot_run(cohort, tmp_path,
                                                                 monkeypatch):
    """The regression. Reconciliation must not reach ``build_span_index``.

    An earlier revision rebuilt a span index inside ``_evidence_resolves``,
    which made every stored row depend on the segmenter it was supposed to
    outlive. Rigging the segmenter to raise is the only honest way to assert it
    is gone.
    """
    classified = _v2_5_completed(cohort, tmp_path, "recon-segmenter")
    assert classified
    packets = cohort.release.packets

    def _explode(*args, **kwargs):
        raise AssertionError("reconciliation must not build a span index")

    monkeypatch.setattr(lcl, "build_span_index", _explode)
    monkeypatch.setattr(_csi, "build_span_index", _explode)
    monkeypatch.setattr(_csi, "segment_units", _explode)
    for record in classified:
        assert lcl._evidence_resolves(record, packets, selected_span=True)


def test_v2_5_reconciliation_holds_when_the_span_rules_cannot_be_loaded(
        cohort, tmp_path, monkeypatch):
    """A stored row outlives its config: the rules loader is never consulted."""
    classified = _v2_5_completed(cohort, tmp_path, "recon-rules")
    assert classified
    packets = cohort.release.packets

    def _explode(*args, **kwargs):
        raise _csi.SpanIndexError("span index config is unavailable")

    monkeypatch.setattr(lcl, "load_span_index_rules", _explode)
    monkeypatch.setattr(_csi, "load_span_index_rules", _explode)
    for record in classified:
        assert lcl._evidence_resolves(record, packets, selected_span=True)


@pytest.mark.parametrize("field,mutate", [
    ("passage_ref", lambda v: "P999"),
    ("span_start", lambda v: v + 1),
    ("span_end", lambda v: v - 1),
    ("resolved_quote", lambda v: v + " tampered"),
    ("span_sha256", lambda v: "0" * 64),
], ids=["passage_ref", "span_start", "span_end", "resolved_quote", "span_sha256"])
def test_tampering_with_a_stored_v2_5_item_still_fails(cohort, tmp_path, field,
                                                       mutate):
    classified = _v2_5_completed(cohort, tmp_path, f"tamper-{field}")
    record = next(r for r in classified if r["axes"]["evidence"])
    packets = cohort.release.packets
    assert lcl._evidence_resolves(record, packets, selected_span=True)
    tampered = json.loads(json.dumps(record))
    item = tampered["axes"]["evidence"][0]
    item[field] = mutate(item[field])
    assert not lcl._evidence_resolves(tampered, packets, selected_span=True)


def test_v2_5_initial_validation_still_uses_the_span_index(cohort, tmp_path):
    """The index is still required where it belongs: resolving a fresh selection."""
    packet = cohort.release.packets[
        (cohort.rows[0]["cik"], cohort.rows[0]["accession"])]
    rules = _span_rules()
    index = _csi.build_span_index(packet, rules)
    validator = Draft202012Validator(
        json.loads((ROOT / lcl.BASE_ROUTE_V2_5.contracts.axes_schema)
                   .read_text(encoding="utf-8")),
        format_checker=FormatChecker())
    good = json.loads(_span_axes_payload(packet, rules))
    axes = lcl.validate_span_axes_output(
        json.dumps(good), packet, validator,
        lcl.BASE_ROUTE_V2_5.contracts.axes_contract, index)
    assert axes["evidence"][0]["resolved_quote"]

    ref = sorted(index.passages)[0]
    beyond = len(index.passages[ref].units) + 1
    bad = json.loads(_span_axes_payload(packet, rules,
                                        span_ref=f"{ref}:S{beyond:03d}"))
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_span_axes_output(
            json.dumps(bad), packet, validator,
            lcl.BASE_ROUTE_V2_5.contracts.axes_contract, index)
    assert exc.value.reason_code == "span_reference_unresolvable"

    malformed = json.loads(_span_axes_payload(packet, rules))
    malformed["evidence"][0]["span_ref"] = "P001:S1"
    with pytest.raises(lcl.AxesValidationFailure) as exc:
        lcl.validate_span_axes_output(
            json.dumps(malformed), packet, validator,
            lcl.BASE_ROUTE_V2_5.contracts.axes_contract, index)
    assert exc.value.reason_code == "axes_contract_violation"


# --- ADR-133: the base route at V2.6 ------------------------------------------------


def _v2_6_base_grant(cohort, tmp_path, *, name="base-gov-v2-6"):
    from dynamic_ai_products.classifier_contract_set import V2_6
    rules = _span_rules()
    base = _grant(cohort, tmp_path, name=name).authorization
    payload = dict(base)
    payload.update({
        "authorization_contract": "universe_classifier_authorization@0.6.0",
        "output_contract": V2_6.record_contract,
        "taxonomy_version": V2_6.taxonomy_version,
        "prompt_template_path": V2_6.prompt_path,
        "prompt_template_sha256":
            sha256((ROOT / V2_6.prompt_path).read_bytes()).hexdigest(),
        "span_index_version": rules.version,
        "span_index_sha256": rules.sha256,
    })
    raw = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    ((tmp_path / name) / "classifier_authorization.json").write_bytes(raw)
    return SimpleNamespace(root=tmp_path / name,
                           reference="classifier_authorization.json",
                           sha256=_sha(raw), authorization=payload)


def test_the_v2_6_base_route_completes_end_to_end(cohort, tmp_path):
    grant = _v2_6_base_grant(cohort, tmp_path)
    run = _run(cohort, grant, tmp_path, run_id="base-v2-6",
               script=_span_script(cohort), route=lcl.BASE_ROUTE_V2_6)
    assert run.result.status == "completed", run.result.receipt
    _assert_no_google()
    manifest = json.loads(run.result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manifest_contract"] == "universe_classifier_manifest@0.6.0"
    assert manifest["output_contract"] == "universe_classifier_record@0.4.0"
    assert manifest["taxonomy_version"] == "universe_classifier_axes_v2_5"
    assert manifest["span_index_version"] == "universe_classifier_span_index_v1"
    assert isinstance(manifest["request_accounting"]["tokens_out_reported"], int)
    records = [json.loads(x) for x in
               (run.result.run_dir / lcl.BASE_ROUTE_V2_6.records_filename)
               .read_text(encoding="utf-8").splitlines() if x.strip()]
    assert len(records) == len(cohort.rows)
    assert all(r["record_contract"] == "universe_classifier_record@0.4.0"
               for r in records)


def test_a_v2_6_base_run_with_one_retry_reports_null(cohort, tmp_path):
    grant = _v2_6_base_grant(cohort, tmp_path, name="base-gov-v2-6-retry")
    flaky = cohort.rows[0]["cik"]
    run = _run(cohort, grant, tmp_path, run_id="base-v2-6-retry",
               script=_span_script(cohort, **{flaky: {"quota_failures": 1}}),
               route=lcl.BASE_ROUTE_V2_6)
    assert run.result.status == "completed", run.result.receipt
    assert run.result.request_accounting["rows_generate_retried"] == 1
    assert run.result.request_accounting["tokens_out_reported"] is None


def test_the_v2_6_base_run_keeps_the_span_archival_checks(cohort, tmp_path):
    grant = _v2_6_base_grant(cohort, tmp_path, name="base-gov-v2-6-span")
    run = _run(cohort, grant, tmp_path, run_id="base-v2-6-span",
               script=_span_script(cohort), route=lcl.BASE_ROUTE_V2_6)
    records = [json.loads(x) for x in
               (run.result.run_dir / lcl.BASE_ROUTE_V2_6.records_filename)
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


@pytest.mark.parametrize("route", [
    lcl.BASE_ROUTE, lcl.BASE_ROUTE_V2_2, lcl.BASE_ROUTE_V2_3, lcl.BASE_ROUTE_V2_4,
    lcl.BASE_ROUTE_V2_5,
], ids=["v2_1", "v2_2", "v2_3", "v2_4", "v2_5"])
def test_every_earlier_base_loader_refuses_a_v2_6_run(cohort, tmp_path, route):
    tag = route.contracts.version_id
    grant = _v2_6_base_grant(cohort, tmp_path, name=f"base-gov-v2-6-iso-{tag}")
    run = _run(cohort, grant, tmp_path, run_id=f"base-v2-6-iso-{tag}",
               script=_span_script(cohort), route=lcl.BASE_ROUTE_V2_6)
    with pytest.raises(ls.ScreenInputError, match="holds no "):
        lcl.require_classifier_run(run.result.run_dir, route=route)


def test_the_v2_6_base_loader_refuses_a_v2_5_run(cohort, tmp_path):
    grant = _v2_5_base_grant(cohort, tmp_path, name="base-gov-v2-5-for-v2-6")
    run = _run(cohort, grant, tmp_path, run_id="base-v2-5-for-v2-6",
               script=_span_script(cohort), route=lcl.BASE_ROUTE_V2_5)
    with pytest.raises(ls.ScreenInputError,
                       match="holds no universe_classifier_v2_6_manifest.json"):
        lcl.require_classifier_run(run.result.run_dir, route=lcl.BASE_ROUTE_V2_6)


def test_the_v2_6_base_route_refuses_a_v2_5_grant(cohort, tmp_path):
    grant = _v2_5_base_grant(cohort, tmp_path, name="base-gov-v2-5-cross")
    with pytest.raises(ls.ScreenInputError):
        _run(cohort, grant, tmp_path, run_id="base-cross-v2-6",
             script=_span_script(cohort), output_dir=tmp_path / "never-v2-6",
             route=lcl.BASE_ROUTE_V2_6)


def test_the_v2_6_cli_mode_reaches_the_v2_6_route():
    source = (ROOT / "pipelines" / "00_build_company_universe.py").read_text(
        encoding="utf-8")
    assert ('if args.mode == "classify-universe-cohort-v2-6":\n'
            "        return _main_classify_universe_cohort("
            "args, route=BASE_ROUTE_V2_6)") in source
