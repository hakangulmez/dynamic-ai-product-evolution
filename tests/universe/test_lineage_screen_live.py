"""ADR-109 live-screen successor tests — fully offline, fake-client only.

Every packet cohort here is a **real** v0.5 packet run built by the real
ADR-107 builder over a synthesized lineage, exactly as the ADR-108 suite does
(the synthesis helpers are duplicated per that suite's precedent). The live
path is exercised through an **injected fake client factory** that mimics the
capture-client seam of the real SDK factory: no test builds a real
``genai.Client``, resolves Application Default Credentials, or opens a
socket, and several tests assert that ``google.*`` was never imported.

No production-run hash appears anywhere. The only pinned hashes are the
ADR-108 predecessor pins at the bottom, which freeze the v0.1 screen module,
its two schemas, and its test module byte-identically, so ADR-109 cannot
silently move its predecessor.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from dynamic_ai_products.ingestion.asset_backed_determination import (
    run_asset_backed_determination,
)
from dynamic_ai_products.ingestion.baseline_packet import (
    FAILURES_FILENAME,
    PACKETS_FILENAME,
)
from dynamic_ai_products.ingestion.lineage_packet import (
    run_lineage_packet_build_v2,
)
from dynamic_ai_products.ingestion.shell_company_determination import (
    run_lineage_shell_company_determination,
)
from dynamic_ai_products.providers.client_contract_v2 import (
    CLIENT_CONTRACT_V2_ID,
    build_client_contract_v2,
    build_operation_endpoints,
)
from dynamic_ai_products.providers.retry_policy import (
    RATE_LIMIT_POLICY_VERSION,
    RETRY_POLICY_VERSION,
)
from dynamic_ai_products.extraction.provider_adapter import client_contract_digest
from dynamic_ai_products.universe import lineage_screen as ls
from dynamic_ai_products import lineage_screen_live as ll
from dynamic_ai_products.universe.io_utils import read_json

ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "pipelines" / "00_build_company_universe.py"
CONFIG = ROOT / "configs" / "project.yaml"
PACKET_FIXTURES = ROOT / "evals" / "fixtures" / "baseline_packets"
SHELL_FIXTURES = ROOT / "evals" / "fixtures" / "shell_company"
TEXT_FIXTURES = ROOT / "evals" / "fixtures" / "plain_text_primary"

MANIFEST_V2_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_manifest.v2.schema.json")
    .read_text(encoding="utf-8"))
MANIFEST_V3_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_manifest.v3.schema.json")
    .read_text(encoding="utf-8"))
MANIFEST_V4_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_manifest.v4.schema.json")
    .read_text(encoding="utf-8"))
MANIFEST_V5_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_manifest.v5.schema.json")
    .read_text(encoding="utf-8"))
SELECTION_SCHEMA = json.loads(
    (ROOT / "schemas" / "universe_screen_selection.schema.json")
    .read_text(encoding="utf-8"))

ACQ_MANIFEST_FILENAME = "primary_document_acquisition_manifest.json"
BUNDLE_MANIFEST_FILENAME = "bundle_manifest.json"

FIXED_CLOCK = lambda: datetime(2026, 8, 19, 9, 0, 0, tzinfo=timezone.utc)  # noqa: E731

VERTEX_PROJECT = "test-vertex-project"
VERTEX_LOCATION = "us-central1"

PROVENANCE = {
    "carrier_run_id": "synthetic-fixture-carrier",
    "carrier_manifest_sha256": "0" * 64,
    "freeze_record_sha256": "0" * 64,
}
ROUTE_VALIDATION = {
    "probe_run_id": "synthetic-fixture-probe",
    "probe_manifest_sha256": "0" * 64,
    "covered_accessions": 3,
    "note": "URL-route grammar only; never selection evidence.",
}


def _google_modules() -> set[str]:
    return {name for name in sys.modules
            if name == "google" or name.startswith("google.")}


#: Captured before the first test of THIS module runs. Other suites (the
#: providers suite among them) may legitimately load ``google.*`` earlier in
#: a shared full-suite process, so the guard is a delta, not an absolute:
#: nothing the live screen path does may ADD a google module. The absolute
#: proof lives in test_fresh_process_preflight_never_imports_google, which
#: checks a process of its own.
_GOOGLE_BASELINE: set[str] | None = None


@pytest.fixture(autouse=True)
def _google_module_baseline():
    global _GOOGLE_BASELINE
    if _GOOGLE_BASELINE is None:
        _GOOGLE_BASELINE = _google_modules()
    yield


def _assert_no_google_import() -> None:
    added = _google_modules() - (_GOOGLE_BASELINE or set())
    assert not added, f"the live screen path imported google modules: {sorted(added)}"


# --- Lineage synthesis (mirrors tests/universe/test_lineage_screen.py) ----------


def _synth_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir(parents=True)
    (root / "schemas").symlink_to(ROOT / "schemas")
    return root


def _fixture_doc(source_dir: Path, filename: str, *, cik: str | None = None,
                 accession: str | None = None) -> tuple[Path, dict]:
    manifest = read_json(source_dir / BUNDLE_MANIFEST_FILENAME)
    entry = next(
        dict(d) for d in manifest["documents"] if d["local_filename"] == filename
    )
    if manifest["bundle_contract"].endswith("@0.1.0"):
        entry.update(representation="html", admission=None,
                     document_blocks=None, declared_type=None,
                     declared_filename=None)
    if cik is not None:
        entry["cik"] = cik
    if accession is not None:
        entry["accession"] = accession
    return source_dir / filename, entry


def _write_shard(root: Path, name: str,
                 documents: list[tuple[Path, dict]]) -> Path:
    run_dir = root / "shards" / name
    run_dir.mkdir(parents=True)
    manifest = {
        "bundle_contract": "baseline_primary_document_bundle@0.2.0",
        "description": "Synthesized ADR-109 fixture shard.",
        "provenance": dict(PROVENANCE),
        "route_validation": dict(ROUTE_VALIDATION),
        "documents": [entry for _, entry in documents],
    }
    (run_dir / BUNDLE_MANIFEST_FILENAME).write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    for source, entry in documents:
        target = run_dir / entry["local_filename"]
        if not target.exists():
            shutil.copyfile(source, target)
    (run_dir / ACQ_MANIFEST_FILENAME).write_text(
        json.dumps({"stub_for": name}, indent=2) + "\n", encoding="utf-8")
    return run_dir


def _shard_record(root: Path, index: int, run_dir: Path, rows: int) -> dict:
    return {
        "shard_index": index,
        "run_id": run_dir.name,
        "run_dir": str(run_dir.relative_to(root)),
        "shard_plan_sha256": f"{index:064d}",
        "acquisition_manifest_sha256": sha256(
            (run_dir / ACQ_MANIFEST_FILENAME).read_bytes()).hexdigest(),
        "bundle_manifest_sha256": sha256(
            (run_dir / BUNDLE_MANIFEST_FILENAME).read_bytes()).hexdigest(),
        "accessions": rows,
        "carrier_rows": rows,
        "bundle_entries": rows,
        "total_requests": 2 * rows,
        "retained_bytes_total": 1,
    }


def _write_aggregate(root: Path, shards: list[Path], *, run_ids) -> Path:
    records = [
        _shard_record(root, index, run_dir,
                      len(read_json(run_dir / BUNDLE_MANIFEST_FILENAME)
                          ["documents"]))
        for index, run_dir in enumerate(shards)
    ]
    rows = sum(r["carrier_rows"] for r in records)
    payload = {
        "aggregate_manifest_contract":
            "acquisition_queue_aggregate_manifest@0.2.0",
        "run_id": "synthetic-aggregate",
        "queue_id": "synthetic-queue",
        "queue_definition_sha256": "a" * 64,
        "execution_run_ids": list(run_ids),
        "coverage_complete": True,
        "coverage_statement":
            f"{len(records)} of {len(records)} shard(s) are authoritative.",
        "shards_authoritative": records,
        "shards_not_authoritative": [],
        "superseded_directories": [],
        "counts": {
            "shards_in_queue": len(records),
            "shards_authoritative": len(records),
            "shards_not_authoritative": 0,
            "accessions_covered": rows,
            "carrier_rows_covered": rows,
            "bundle_entries": rows,
            "total_requests": 2 * rows,
            "retained_bytes_total": len(records),
            "superseded_directories": 0,
            "retained_bytes_superseded": 0,
        },
        "run_timestamp": "2026-08-19T09:00:00+00:00",
        "limitations": ["Synthetic fixture aggregate."],
    }
    path = root / "aggregate.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def _v5_run(tmp: Path, shard_docs: list[list[tuple[Path, dict]]]):
    root = _synth_root(tmp)
    run_ids = [f"r{chr(ord('a') + i)}" for i in range(len(shard_docs))]
    shards = [
        _write_shard(root, f"{run_ids[i]}-shard-{i:04d}", docs)
        for i, docs in enumerate(shard_docs)
    ]
    aggregate = _write_aggregate(root, shards, run_ids=run_ids)
    shell_det = run_lineage_shell_company_determination(
        repo_root=root, aggregate_manifest_path=aggregate,
        output_dir=root / "determinations", run_id="shell-det",
        clock=FIXED_CLOCK).manifest_path
    abs_det = run_asset_backed_determination(
        repo_root=root, aggregate_manifest_path=aggregate,
        output_dir=root / "abs-determinations", run_id="abs-det",
        clock=FIXED_CLOCK).manifest_path
    result = run_lineage_packet_build_v2(
        repo_root=root, aggregate_manifest_path=aggregate,
        shell_determination_manifest_path=shell_det,
        asset_backed_determination_manifest_path=abs_det,
        project_config_path=CONFIG, output_dir=tmp / "packets",
        run_id="v5-fixture", item_one_locator="item_one_span_v2",
        clock=FIXED_CLOCK)
    manifest_path = result.manifest_path
    run_dir = manifest_path.parent
    packets = [json.loads(line) for line in
               (run_dir / PACKETS_FILENAME).read_text(encoding="utf-8")
               .splitlines() if line.strip()]
    failures = [json.loads(line) for line in
                (run_dir / FAILURES_FILENAME).read_text(encoding="utf-8")
                .splitlines() if line.strip()]
    return SimpleNamespace(manifest_path=manifest_path, run_dir=run_dir,
                           packets=packets, failures=failures,
                           manifest_sha256=sha256(
                               manifest_path.read_bytes()).hexdigest())


@pytest.fixture(scope="module")
def small(tmp_path_factory):
    """3 packets + 2 failures: the full-cohort live cohort."""
    built = _v5_run(tmp_path_factory.mktemp("live-small"), [
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


@pytest.fixture(scope="module")
def big(tmp_path_factory):
    """104 packets + 1 failure: the canary cohort (selection is 100 of 104)."""
    source, template = _fixture_doc(PACKET_FIXTURES, "primary_10k_ixbrl.htm")
    docs = []
    for index in range(104):
        cik = f"{9100000000 + index:010d}"
        docs.append((source, dict(template, cik=cik,
                                  accession=f"{cik}-22-000001")))
    docs.append(_fixture_doc(PACKET_FIXTURES, "primary_missing_item1.htm"))
    built = _v5_run(tmp_path_factory.mktemp("live-big"), [docs])
    assert len(built.packets) == 104 and len(built.failures) == 1
    return built


# --- Governance fixtures ---------------------------------------------------------


def _endpoints() -> list[str]:
    return sorted(build_operation_endpoints(
        vertex_project=VERTEX_PROJECT, vertex_location=VERTEX_LOCATION
    ).values())


def _contract_digest() -> str:
    return client_contract_digest(build_client_contract_v2(
        vertex_project=VERTEX_PROJECT, vertex_location=VERTEX_LOCATION))


def _governance(tmp_path: Path, *, cohort, selection_path: Path,
                selection_kind: str, logical: int,
                mutate_authorization=None, mutate_enablement=None,
                prompt_sha256: str | None = None) -> SimpleNamespace:
    """Write a valid enablement + authorization pair; optionally tamper one."""
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
    if mutate_enablement is not None:
        mutate_enablement(enablement)
    enablement_raw = (json.dumps(enablement, indent=2, sort_keys=True)
                      + "\n").encode("utf-8")
    (root / "screen_adapter_enablement.json").write_bytes(enablement_raw)
    template_sha = sha256(
        (ROOT / ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH).read_bytes()).hexdigest()
    authorization = {
        "authorization_contract": "universe_screen_live_authorization@0.1.0",
        "authorization_id": "screen-authorization-fixture",
        "authorized_by": "fixture-governance",
        "effective_at": "2026-08-01T00:00:00+00:00",
        "expires_at": "2026-12-31T00:00:00+00:00",
        "deployment_environment_id": "fixture-env",
        "rollout_state": ("controlled_pilot" if selection_kind == "canary_100"
                          else "release_or_research_production"),
        "screen_stage": "universe_high_recall_screen",
        "packet_manifest_sha256": cohort.manifest_sha256,
        "prompt_template_sha256": (
            prompt_sha256 if prompt_sha256 is not None else template_sha),
        "selection_artifact_sha256": sha256(
            selection_path.read_bytes()).hexdigest(),
        "selection_kind": selection_kind,
        "screen_adapter_enablement_reference": "screen_adapter_enablement.json",
        "screen_adapter_enablement_sha256": sha256(
            enablement_raw).hexdigest(),
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
        "retry_policy_version": RETRY_POLICY_VERSION,
        "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
    }
    if mutate_authorization is not None:
        mutate_authorization(authorization)
    authorization_raw = (json.dumps(authorization, indent=2, sort_keys=True)
                         + "\n").encode("utf-8")
    (root / "screen_live_authorization.json").write_bytes(authorization_raw)
    return SimpleNamespace(
        root=root,
        reference="screen_live_authorization.json",
        sha256=sha256(authorization_raw).hexdigest(),
        authorization=authorization,
    )


# --- The fake Vertex transport -----------------------------------------------------


class _FakeHttpError(Exception):
    """A transient transport failure: 503 is a declared retry trigger."""

    status_code = 503


class _FakeCapture:
    def __init__(self):
        self._ordinals: dict[str, int] = {}
        self._slots: dict[tuple[str, int], bytes] = {}
        self._outcomes: dict[tuple[str, int], str] = {}

    @contextmanager
    def operation(self, operation_label: str):
        yield

    def record_send(self, label: str, body: bytes | None, outcome: str) -> None:
        ordinal = self._ordinals.get(label, 0) + 1
        self._ordinals[label] = ordinal
        if body is not None:
            self._slots[(label, ordinal)] = body
        self._outcomes[(label, ordinal)] = outcome

    def next_ordinal(self, label: str) -> int:
        return self._ordinals.get(label, 0) + 1

    def drain(self, label: str, ordinal: int) -> bytes | None:
        return self._slots.pop((label, ordinal), None)

    def send_outcome(self, label: str, ordinal: int) -> str:
        return self._outcomes.get((label, ordinal),
                                  "no_response_transport_failure")


_CIK_IN_PROMPT = re.compile(r"^cik: (\d{10})$", re.MULTILINE)


def _envelope(text: str, *, prompt_tokens: int, output_tokens: int = 7) -> dict:
    return {
        "candidates": [{
            "content": {"parts": [{"text": text}]},
            "finishReason": "STOP",
        }],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": output_tokens,
            "thoughtsTokenCount": 0,
        },
    }


class _FakeModels:
    """Scripted count/generate behavior keyed by the prompt's own CIK line."""

    def __init__(self, capture: _FakeCapture, script: dict):
        self._capture = capture
        self._script = script
        self.count_calls = 0
        self.generate_calls = 0

    def _entry(self, contents: str) -> dict:
        match = _CIK_IN_PROMPT.search(contents)
        assert match, "rendered prompt carries no cik line"
        return self._script[match.group(1)]

    def count_tokens(self, *, model, contents, config):
        self.count_calls += 1
        entry = self._entry(contents)
        tokens = entry.get("count_tokens", 120)
        body = json.dumps(
            entry.get("count_body", {"totalTokens": tokens})
        ).encode("utf-8")
        self._capture.record_send("count_tokens", body, "ok")
        return SimpleNamespace(total_tokens=entry.get("witness", tokens))

    def generate_content(self, *, model, contents, config):
        self.generate_calls += 1
        entry = self._entry(contents)
        remaining = entry.get("transient_failures", 0)
        if remaining > 0:
            entry["transient_failures"] = remaining - 1
            self._capture.record_send("generate_content", None,
                                      "no_response_transport_failure")
            raise _FakeHttpError("scripted transient failure")
        envelope = entry.get("envelope")
        if envelope is None:
            envelope = _envelope(entry["text"],
                                 prompt_tokens=entry.get("count_tokens", 120))
        body = (envelope if isinstance(envelope, bytes)
                else json.dumps(envelope).encode("utf-8"))
        self._capture.record_send("generate_content", body, "ok")
        return SimpleNamespace()


class _FakeFactory:
    """Mimics the SDK factory's yield contract; counts every open."""

    def __init__(self, script: dict):
        self.script = script
        self.opens = 0
        self.count_calls = 0
        self.generate_calls = 0

    @contextmanager
    def __call__(self, *, vertex_project, vertex_location, endpoint_allowlist,
                 http_options_kwargs, operation_endpoints=None):
        self.opens += 1
        capture = _FakeCapture()
        models = _FakeModels(capture, self.script)
        try:
            yield SimpleNamespace(models=models), capture
        finally:
            self.count_calls += models.count_calls
            self.generate_calls += models.generate_calls


def _model_output(packet: dict, status: str = "BOUNDARY_OR_UNCERTAIN") -> str:
    passage = packet["passages"][0]
    evidence = []
    if status == "LIKELY_ELIGIBLE":
        evidence = [{
            "source_id": packet["source_id"],
            "passage_id": passage["passage_id"],
            "quote": passage["text"][:50],
            "supported_claim": "The filing describes an external offering.",
        }]
    return json.dumps({
        "screen_status": status,
        "plausible_customer_facing_digital_product": (
            True if status == "LIKELY_ELIGIBLE" else None),
        "candidate_customer_value_archetypes": [],
        "positive_evidence": evidence,
        "negative_or_boundary_evidence": [],
        "missing_evidence": [],
        "confidence": "medium",
    })


def _script_for(packets: list[dict], statuses: dict[str, str] | None = None,
                **overrides) -> dict:
    statuses = statuses or {}
    script = {
        p["cik"]: {"text": _model_output(
            p, statuses.get(p["cik"], "BOUNDARY_OR_UNCERTAIN"))}
        for p in packets
    }
    for cik, extra in overrides.items():
        script[cik] = {**script.get(cik, {}), **extra}
    return script


# --- Selection helpers --------------------------------------------------------------


def _selection(cohort, tmp_path: Path, kind: str, *, seed: int | None = None,
               run_id: str = "sel", mutate=None) -> Path:
    result = ll.build_screen_selection(
        repo_root=ROOT, packet_manifest_path=cohort.manifest_path,
        selection_kind=kind, seed=seed, output_dir=tmp_path / "selections",
        run_id=run_id, clock=FIXED_CLOCK)
    path = result.manifest_path
    if mutate is not None:
        payload = json.loads(path.read_text(encoding="utf-8"))
        mutate(payload)
        path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
    return path


def _live(cohort, tmp_path: Path, *, selection_path: Path, governance,
          script: dict | None = None, run_id: str = "live", logical=None,
          attempts=None, dry_run: bool = False, clock=FIXED_CLOCK):
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    if logical is None:
        logical = (len(selection["rows"])
                   if selection["selection_kind"] == "canary_100"
                   else len(cohort.packets))
    factory = _FakeFactory(script if script is not None
                           else _script_for(cohort.packets))
    result = ll.run_lineage_screen_live(
        repo_root=ROOT,
        packet_manifest_path=cohort.manifest_path,
        selection_artifact_path=selection_path,
        governance_root=governance.root,
        authorization_reference=governance.reference,
        authorization_sha256=governance.sha256,
        output_dir=tmp_path / "screen",
        run_id=run_id,
        logical_request_cap=logical,
        provider_attempt_cap=(logical * 3 if attempts is None else attempts),
        clock=clock,
        dry_run=dry_run,
        client_factory=factory,
    )
    return result, factory


def _full_setup(small, tmp_path: Path, **kwargs):
    selection_path = _selection(small, tmp_path, "full_cohort")
    governance = _governance(tmp_path, cohort=small,
                             selection_path=selection_path,
                             selection_kind="full_cohort",
                             logical=len(small.packets), **kwargs)
    return selection_path, governance


def _records(result) -> list[dict]:
    return [json.loads(line) for line in
            (result.run_dir / ls.RECORDS_FILENAME)
            .read_text(encoding="utf-8").splitlines() if line.strip()]


def _ledger(result) -> list[dict]:
    return [json.loads(line) for line in
            (result.run_dir / ll.CAPTURE_LEDGER_FILENAME)
            .read_text(encoding="utf-8").splitlines() if line.strip()]


# --- Selection generation -------------------------------------------------------------


def test_allocation_is_exact_and_deterministic():
    sizes = {"a": 5, "b": 3, "c": 2}
    first = ll._allocate_stratum_counts(sizes, 4)
    assert first == ll._allocate_stratum_counts(sizes, 4)
    assert sum(first.values()) == 4
    assert all(first[key] <= sizes[key] for key in sizes)
    assert ll._allocate_stratum_counts({"a": 2}, 2) == {"a": 2}
    with pytest.raises(ls.ScreenInputError, match="smaller"):
        ll._allocate_stratum_counts({"a": 1}, 5)


def test_canary_selection_is_deterministic_and_exactly_100(big, tmp_path):
    one = json.loads(_selection(big, tmp_path, "canary_100", seed=7,
                                run_id="s1").read_text(encoding="utf-8"))
    two = json.loads(_selection(big, tmp_path, "canary_100", seed=7,
                                run_id="s2").read_text(encoding="utf-8"))
    other = json.loads(_selection(big, tmp_path, "canary_100", seed=8,
                                  run_id="s3").read_text(encoding="utf-8"))
    assert one["rows"] == two["rows"]
    assert len(one["rows"]) == 100
    assert one["rows"] != other["rows"]  # 100 of 104: the seed moves rows
    assert one["packet_manifest_sha256"] == big.manifest_sha256
    assert sum(s["selected"] for s in one["sampling"]["strata"]) == 100
    keys = [(r["cik"], r["accession"]) for r in one["rows"]]
    assert len(set(keys)) == 100
    errors = list(Draft202012Validator(
        SELECTION_SCHEMA, format_checker=FormatChecker()).iter_errors(one))
    assert errors == []


def test_canary_selection_refuses_a_small_cohort(small, tmp_path):
    with pytest.raises(ls.ScreenInputError, match="at least 100"):
        ll.build_screen_selection(
            repo_root=ROOT, packet_manifest_path=small.manifest_path,
            selection_kind="canary_100", seed=1,
            output_dir=tmp_path / "selections", run_id="s",
            clock=FIXED_CLOCK)
    assert not (tmp_path / "selections").exists()


def test_full_cohort_selection_enumerates_nothing(small, tmp_path):
    payload = json.loads(_selection(small, tmp_path, "full_cohort")
                         .read_text(encoding="utf-8"))
    assert payload["rows"] == []
    assert payload["sampling"]["algorithm"] == "full_cohort@1"
    assert payload["sampling"]["seed"] is None
    assert payload["counts"]["packets_total"] == 3
    assert list(Draft202012Validator(
        SELECTION_SCHEMA, format_checker=FormatChecker()
    ).iter_errors(payload)) == []


def test_selection_is_write_once_and_dry_run_writes_nothing(small, tmp_path):
    _selection(small, tmp_path, "full_cohort", run_id="once")
    with pytest.raises(FileExistsError):
        _selection(small, tmp_path, "full_cohort", run_id="once")
    result = ll.build_screen_selection(
        repo_root=ROOT, packet_manifest_path=small.manifest_path,
        selection_kind="full_cohort", seed=None,
        output_dir=tmp_path / "dry", run_id="d", clock=FIXED_CLOCK,
        dry_run=True)
    assert result.status == "dry_run"
    assert not (tmp_path / "dry").exists()
    with pytest.raises(ls.ScreenInputError, match="seed"):
        ll.build_screen_selection(
            repo_root=ROOT, packet_manifest_path=small.manifest_path,
            selection_kind="full_cohort", seed=3,
            output_dir=tmp_path / "x", run_id="x", clock=FIXED_CLOCK)


# --- Governance preflight: every refusal before output, SDK, or network ---------------


def _expect_refusal(small, tmp_path, match, **governance_kwargs):
    selection_path = _selection(small, tmp_path, "full_cohort")
    governance = _governance(tmp_path, cohort=small,
                             selection_path=selection_path,
                             selection_kind="full_cohort",
                             logical=len(small.packets), **governance_kwargs)
    with pytest.raises(ls.ScreenInputError, match=match):
        _live(small, tmp_path, selection_path=selection_path,
              governance=governance)
    assert not (tmp_path / "screen").exists()
    _assert_no_google_import()


def test_missing_or_tampered_authorization_is_refused(small, tmp_path):
    selection_path = _selection(small, tmp_path, "full_cohort")
    governance = _governance(tmp_path, cohort=small,
                             selection_path=selection_path,
                             selection_kind="full_cohort", logical=3)
    # Wrong pin digest.
    forged = SimpleNamespace(root=governance.root,
                             reference=governance.reference, sha256="0" * 64,
                             authorization=governance.authorization)
    with pytest.raises(ls.ScreenInputError, match="hashes to"):
        _live(small, tmp_path, selection_path=selection_path,
              governance=forged)
    # Absent artifact.
    ghost = SimpleNamespace(root=governance.root, reference="nope.json",
                            sha256=governance.sha256, authorization=None)
    with pytest.raises(ls.ScreenInputError, match="not found"):
        _live(small, tmp_path, selection_path=selection_path, governance=ghost)
    # Schema-invalid: the prompt hash is a required field ("missing" case).
    def drop_prompt(authorization):
        del authorization["prompt_template_sha256"]
    _expect_refusal(small, tmp_path / "m", "prompt_template_sha256",
                    mutate_authorization=drop_prompt)
    assert not (tmp_path / "screen").exists()
    _assert_no_google_import()


def test_prompt_hash_binding_refuses_malformed_stale_and_mismatched(
        small, tmp_path):
    # Malformed: not 64-hex -> schema refusal.
    def malformed(authorization):
        authorization["prompt_template_sha256"] = "not-a-hash"
    _expect_refusal(small, tmp_path / "a", "prompt_template_sha256",
                    mutate_authorization=malformed)
    # Stale: minted for other template bytes (simulated by hashing altered
    # bytes into the authorization).
    stale = sha256(
        (ROOT / ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH).read_bytes() + b"drift"
    ).hexdigest()
    _expect_refusal(small, tmp_path / "b", "stale or\nmismatched|stale",
                    prompt_sha256=stale)
    # Mismatched: an arbitrary wrong digest.
    _expect_refusal(small, tmp_path / "c", "prompt", prompt_sha256="7" * 64)


def test_enablement_chain_is_refused_when_tampered(small, tmp_path):
    def wrong_sha(authorization):
        authorization["screen_adapter_enablement_sha256"] = "1" * 64
    _expect_refusal(small, tmp_path / "a", "hashes to",
                    mutate_authorization=wrong_sha)

    def widened(enablement):
        enablement["endpoint_allowlist"] = (
            enablement["endpoint_allowlist"]
            + ["https://example.com/v1/other:predict"])
    selection_path = _selection(small, tmp_path / "b", "full_cohort")
    governance = _governance(tmp_path / "b", cohort=small,
                             selection_path=selection_path,
                             selection_kind="full_cohort", logical=3,
                             mutate_enablement=widened)
    # A widened list dies at the enablement's own schema: the allowlist is
    # pinned to exactly two entries before any equality is even compared.
    with pytest.raises(ls.ScreenInputError, match="too long|contract"):
        _live(small, tmp_path / "b", selection_path=selection_path,
              governance=governance)
    assert not (tmp_path / "b" / "screen").exists()

    def swapped(enablement):
        enablement["endpoint_allowlist"] = [
            enablement["endpoint_allowlist"][0],
            "https://example.com/v1/other:predict",
        ]
    selection_path = _selection(small, tmp_path / "c", "full_cohort")
    governance = _governance(tmp_path / "c", cohort=small,
                             selection_path=selection_path,
                             selection_kind="full_cohort", logical=3,
                             mutate_enablement=swapped)
    # A two-entry list carrying a foreign endpoint hydrates and passes the
    # schema; the derivation equality then refuses it.
    with pytest.raises(ls.ScreenInputError, match="operation endpoints"):
        _live(small, tmp_path / "c", selection_path=selection_path,
              governance=governance)
    assert not (tmp_path / "c" / "screen").exists()
    _assert_no_google_import()


def test_contract_route_and_policy_bindings(small, tmp_path):
    def wrong_contract(authorization):
        authorization["provider_client_contract_sha256"] = "2" * 64
    _expect_refusal(small, tmp_path / "a", "different\ncontract|contract",
                    mutate_authorization=wrong_contract)

    def wrong_route(authorization):
        authorization["model_route"] = {"provider": "google_vertex_ai",
                                        "model_label": "gemini-ultra"}
    _expect_refusal(small, tmp_path / "b", "model route",
                    mutate_authorization=wrong_route)

    def wrong_policy(authorization):
        authorization["retry_policy_version"] = "some_other_policy"
    _expect_refusal(small, tmp_path / "c", "policy",
                    mutate_authorization=wrong_policy)


def test_expired_authorization_is_refused(small, tmp_path):
    def expired(authorization):
        authorization["expires_at"] = "2026-08-02T00:00:00+00:00"
    _expect_refusal(small, tmp_path, "window",
                    mutate_authorization=expired)


def test_selection_bindings_are_refused_when_crossed(small, big, tmp_path):
    # A selection generated against a different cohort.
    foreign_selection = _selection(big, tmp_path, "full_cohort",
                                   run_id="foreign")
    governance = _governance(tmp_path, cohort=small,
                             selection_path=foreign_selection,
                             selection_kind="full_cohort", logical=3)
    with pytest.raises(ls.ScreenInputError, match="different packet manifest"):
        _live(small, tmp_path, selection_path=foreign_selection,
              governance=governance)
    # Selection kind disagreement between artifact and authorization.
    selection_path = _selection(small, tmp_path, "full_cohort", run_id="own")
    governance = _governance(tmp_path / "k", cohort=small,
                             selection_path=selection_path,
                             selection_kind="full_cohort", logical=3,
                             mutate_authorization=lambda a: a.update(
                                 selection_kind="canary_100",
                                 rollout_state="controlled_pilot",
                                 logical_request_cap=100,
                                 provider_attempt_cap=300,
                                 budget_max_external_requests=400))
    with pytest.raises(ls.ScreenInputError, match="disagree"):
        _live(small, tmp_path / "k", selection_path=selection_path,
              governance=governance, logical=3)
    # A tampered selection no longer matches the authorization's digest.
    tampered = _selection(small, tmp_path, "full_cohort", run_id="tampered",
                          mutate=lambda p: p.update(selection_id="other"))
    governance = _governance(tmp_path / "t", cohort=small,
                             selection_path=_selection(
                                 small, tmp_path, "full_cohort",
                                 run_id="pinned"),
                             selection_kind="full_cohort", logical=3)
    with pytest.raises(ls.ScreenInputError, match="not the one"):
        _live(small, tmp_path / "t", selection_path=tampered,
              governance=governance)
    assert not (tmp_path / "screen").exists()
    _assert_no_google_import()


def test_selection_row_integrity_on_the_canary(big, tmp_path):
    def forge_foreign(payload):
        payload["rows"][0] = dict(payload["rows"][0], cik="0000000042")

    def forge_sha(payload):
        payload["rows"][0] = dict(payload["rows"][0], packet_sha256="3" * 64)

    def forge_duplicate(payload):
        payload["rows"][1] = dict(payload["rows"][0])

    for name, mutate, match in (
        ("foreign", forge_foreign, "not a valid packet row"),
        ("sha", forge_sha, "drifted row"),
        ("dup", forge_duplicate, "twice"),
    ):
        base = tmp_path / name
        base.mkdir()
        selection_path = _selection(big, base, "canary_100", seed=7,
                                    mutate=mutate)
        governance = _governance(base, cohort=big,
                                 selection_path=selection_path,
                                 selection_kind="canary_100", logical=100)
        with pytest.raises(ls.ScreenInputError, match=match):
            _live(big, base, selection_path=selection_path,
                  governance=governance, logical=100)
        assert not (base / "screen").exists()
    _assert_no_google_import()


def test_caps_are_stated_not_discovered_by_the_live_runner(small, tmp_path):
    selection_path, governance = _full_setup(small, tmp_path)
    with pytest.raises(ls.ScreenInputError, match="logical_request_cap"):
        _live(small, tmp_path, selection_path=selection_path,
              governance=governance, logical=99)
    with pytest.raises(ls.ScreenInputError, match="provider_attempt_cap"):
        _live(small, tmp_path, selection_path=selection_path,
              governance=governance, attempts=5)
    # The authorization side must agree too (full_cohort caps are free-form).
    governance_bad = _governance(
        tmp_path / "bad", cohort=small, selection_path=selection_path,
        selection_kind="full_cohort", logical=5)
    with pytest.raises(ls.ScreenInputError, match="disagree|logical"):
        _live(small, tmp_path / "bad", selection_path=selection_path,
              governance=governance_bad)
    assert not (tmp_path / "screen").exists()
    _assert_no_google_import()


# --- The live happy paths ---------------------------------------------------------------


def test_live_full_cohort_run_end_to_end(small, tmp_path):
    selection_path, governance = _full_setup(small, tmp_path)
    statuses = {small.packets[0]["cik"]: "LIKELY_ELIGIBLE"}
    result, factory = _live(
        small, tmp_path, selection_path=selection_path,
        governance=governance,
        script=_script_for(small.packets, statuses=statuses))
    assert result.status == "completed", result.receipt
    records = _records(result)
    assert len(records) == 5
    screened = [r for r in records if r["record_kind"] == "screened_packet"]
    insufficient = [r for r in records
                    if r["record_kind"] == "insufficient_evidence"]
    assert len(screened) == 3 and len(insufficient) == 2
    assert all(r["model_route"] == {"provider": "google_vertex_ai",
                                    "model_label": "gemini-2.5-flash"}
               for r in screened)
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert list(Draft202012Validator(
        MANIFEST_V5_SCHEMA, format_checker=FormatChecker()
    ).iter_errors(manifest)) == []
    assert manifest["prompt_template_path"] == (
        "prompts/discovery/universe_high_recall_screen.v4.md")
    assert manifest["schema_versions"]["universe_screen_manifest_v5"] == "0.5.0"
    # Three files bound, all re-hashing.
    for filename, recorded in manifest["output_hashes"].items():
        assert sha256((result.run_dir / filename).read_bytes()).hexdigest() \
            == recorded
    ledger = _ledger(result)
    assert len(ledger) == 6  # 3 count + 3 generate
    accounting = result.request_accounting
    assert accounting["logical_requests_made"] == 3
    assert accounting["provider_attempts_made"] == 3
    assert accounting["external_requests_made"] == 6
    assert accounting["count_captures"] == 3
    assert accounting["generate_captures"] == 3
    assert accounting["tokens_in_measured"] == 360
    assert accounting["tokens_out_reported"] == 21
    assert accounting["rows_usage_verified"] == 3
    assert accounting["cost_micros_settled"] > 0
    assert len(result.reconciliation) >= 14
    assert all(result.reconciliation.values())
    # Every capture file re-hashes to its ledger line; no orphan exists.
    for entry in ledger:
        assert entry["capture_disposition"] == "raw_persisted"
        raw = (result.run_dir / entry["raw_reference"]).read_bytes()
        assert sha256(raw).hexdigest() == entry["raw_sha256"]
    # Each archived response equals the text of its terminal envelope.
    archive = {e["raw_response_id"]: e for e in (
        json.loads(line) for line in
        (result.run_dir / ls.RAW_RESPONSES_FILENAME)
        .read_text(encoding="utf-8").splitlines() if line.strip())}
    for entry in ledger:
        if entry["operation_label"] != "generate_content":
            continue
        envelope = json.loads(
            (result.run_dir / entry["raw_reference"]).read_bytes())
        text = envelope["candidates"][0]["content"]["parts"][0]["text"]
        row = [e for e in archive.values()
               if e["raw_response"] == text]
        assert row, "archived text does not match any envelope"
    assert factory.opens == 6  # one client per operation call, two per row
    _assert_no_google_import()


def test_live_canary_run_screens_exactly_the_selection(big, tmp_path):
    selection_path = _selection(big, tmp_path, "canary_100", seed=7)
    governance = _governance(tmp_path, cohort=big,
                             selection_path=selection_path,
                             selection_kind="canary_100", logical=100)
    result, factory = _live(big, tmp_path, selection_path=selection_path,
                            governance=governance, logical=100)
    assert result.status == "completed", result.receipt
    records = _records(result)
    assert len(records) == 100
    assert all(r["record_kind"] == "screened_packet" for r in records)
    assert result.counts["insufficient_evidence"] == 0
    assert result.counts["firm_rollup"]["INSUFFICIENT_EVIDENCE"] == 0
    selection = json.loads(selection_path.read_text(encoding="utf-8"))
    assert ({(r["cik"], r["accession"]) for r in records}
            == {(r["cik"], r["accession"]) for r in selection["rows"]})
    assert factory.count_calls == 100 and factory.generate_calls == 100
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["selection"]["selection_kind"] == "canary_100"
    assert manifest["request_accounting"]["external_request_cap"] == 400
    _assert_no_google_import()


def test_promotion_gate_accepts_only_live_full_cohort(small, big, tmp_path):
    # A live full-cohort run is promotable.
    selection_path, governance = _full_setup(small, tmp_path)
    full, _ = _live(small, tmp_path, selection_path=selection_path,
                    governance=governance)
    assert ll.require_promotable_screen_run(full.run_dir)
    # A canary run is structurally non-promotable.
    canary_selection = _selection(big, tmp_path, "canary_100", seed=7,
                                  run_id="sel-canary")
    canary_governance = _governance(tmp_path / "c", cohort=big,
                                    selection_path=canary_selection,
                                    selection_kind="canary_100", logical=100)
    canary, _ = _live(big, tmp_path / "c", selection_path=canary_selection,
                      governance=canary_governance, logical=100)
    with pytest.raises(ls.ScreenInputError, match="non-promotable"):
        ll.require_promotable_screen_run(canary.run_dir)
    # A mock v0.1 run has no selection block and is refused.
    mock_provider = ls.MockLineageScreenProvider({
        f"{p['cik']}:{p['accession']}": {"raw": _model_output(p)}
        for p in small.packets})
    mock = ls.run_lineage_screen(
        repo_root=ROOT, packet_manifest_path=small.manifest_path,
        provider=mock_provider, output_dir=tmp_path / "mock", run_id="mock",
        logical_request_cap=3, provider_attempt_cap=9, clock=FIXED_CLOCK)
    with pytest.raises(ls.ScreenInputError, match="no selection block"):
        ll.require_promotable_screen_run(mock.run_dir)
    # A tampered capture file is caught by the gate's ledger re-hash.
    ledger = _ledger(full)
    target = full.run_dir / ledger[0]["raw_reference"]
    original = target.read_bytes()
    target.write_bytes(original[:-1] + b"X")
    with pytest.raises(ls.ScreenInputError, match="ledger line"):
        ll.require_promotable_screen_run(full.run_dir)
    target.write_bytes(original)
    # An orphan capture file is caught by the walk.
    orphan = full.run_dir / ll.CAPTURES_DIRNAME / "orphan.bin"
    orphan.write_bytes(b"planted")
    with pytest.raises(ls.ScreenInputError, match="disagree"):
        ll.require_promotable_screen_run(full.run_dir)
    orphan.unlink()
    assert ll.require_promotable_screen_run(full.run_dir)


def test_parity_with_the_mock_predecessor(small, tmp_path):
    statuses = {small.packets[1]["cik"]: "LIKELY_ELIGIBLE"}
    # The mock run replays raw strings; the live fake embeds the same strings
    # in envelopes. Model-derived fields must agree exactly.
    mock_provider = ls.MockLineageScreenProvider({
        f"{p['cik']}:{p['accession']}":
            {"raw": _model_output(p, statuses.get(p["cik"],
                                                  "BOUNDARY_OR_UNCERTAIN"))}
        for p in small.packets})
    mock = ls.run_lineage_screen(
        repo_root=ROOT, packet_manifest_path=small.manifest_path,
        provider=mock_provider, output_dir=tmp_path / "mock", run_id="same",
        logical_request_cap=3, provider_attempt_cap=9, clock=FIXED_CLOCK)
    assert mock.status == "completed"
    selection_path, governance = _full_setup(small, tmp_path)
    live, _ = _live(small, tmp_path, selection_path=selection_path,
                    governance=governance, run_id="same",
                    script=_script_for(small.packets, statuses=statuses))
    mock_by_key = {(r["cik"], r["accession"]): r for r in
                   [json.loads(line) for line in
                    (mock.run_dir / ls.RECORDS_FILENAME)
                    .read_text(encoding="utf-8").splitlines() if line.strip()]}
    for record in _records(live):
        twin = mock_by_key[(record["cik"], record["accession"])]
        for field in ("record_kind", "screen_status", "screen_output",
                      "packet_sha256", "baseline_filing_date",
                      "raw_response_sha256", "failure_reason_code",
                      "failure_detail"):
            assert record[field] == twin[field], field
        if record["record_kind"] == "screened_packet":
            assert record["model_route"] != twin["model_route"]
            # ADR-110: the routes render different templates by design, so
            # the per-record prompt hash differs while every model-derived
            # field above is identical. Both remain 64-hex and bound.
            assert record["prompt_sha256"] != twin["prompt_sha256"]
            assert len(record["prompt_sha256"]) == 64
    _assert_no_google_import()


# --- Retry, exhaustion, envelope failures, budgets ---------------------------------------


def test_retry_arithmetic_and_ledger_truthfulness(small, tmp_path):
    selection_path, governance = _full_setup(small, tmp_path)
    script = _script_for(small.packets)
    script[small.packets[0]["cik"]]["transient_failures"] = 2
    result, _ = _live(small, tmp_path, selection_path=selection_path,
                      governance=governance, script=script)
    assert result.status == "completed", result.receipt
    accounting = result.request_accounting
    assert accounting["provider_attempts_made"] == 5  # 3 + 1 + 1
    assert accounting["rows_retried"] == 1
    assert accounting["generate_captures"] == 5
    assert accounting["count_captures"] == 3
    assert accounting["external_requests_made"] == 8
    ledger = _ledger(result)
    failed = [e for e in ledger
              if e["capture_disposition"] == "no_body_captured"]
    assert len(failed) == 2  # the two transient attempts persisted no body
    assert all(result.reconciliation.values())


def test_transient_exhaustion_is_a_terminal_receipt(small, tmp_path):
    selection_path, governance = _full_setup(small, tmp_path)
    script = _script_for(small.packets)
    script[small.packets[1]["cik"]]["transient_failures"] = 3
    result, _ = _live(small, tmp_path, selection_path=selection_path,
                      governance=governance, script=script)
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "provider_error"
    assert receipt["stopping_row_index"] == 2
    assert receipt["records_completed_before_failure"] == 1
    assert receipt["raw_responses_captured"] == 1
    assert receipt["provider_attempts_made"] == 4  # 1 + the 3 exhausted sends
    assert receipt["external_requests_made"] == 6  # 2 count + 4 generate
    assert not (result.run_dir / ls.RECORDS_FILENAME).exists()
    assert not (result.run_dir / ll.CAPTURE_LEDGER_FILENAME).exists()
    assert not (result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()
    with pytest.raises(ls.ScreenInputError, match="failure receipt"):
        ll.require_promotable_screen_run(result.run_dir)
    # Run-id reuse is refused for failed live directories too.
    with pytest.raises(FileExistsError):
        _live(small, tmp_path, selection_path=selection_path,
              governance=governance, script=_script_for(small.packets))


@pytest.mark.parametrize("name,envelope", [
    ("blocked", {"promptFeedback": {"blockReason": "SAFETY"},
                 "candidates": [{"content": {"parts": [{"text": "x"}]}}]}),
    ("empty_candidates", {"candidates": []}),
    ("two_candidates", {"candidates": [
        {"content": {"parts": [{"text": "a"}]}},
        {"content": {"parts": [{"text": "b"}]}}]}),
    ("part_less", {"candidates": [{"content": {"parts": []}}]}),
    ("non_text_part", {"candidates": [
        {"content": {"parts": [{"inlineData": "zz"}]}}]}),
    ("malformed", b"this is not json"),
    ("truncated", {"candidates": [
        {"content": {"parts": [{"text": "x"}]},
         "finishReason": "MAX_TOKENS"}]}),
    ("empty_text", {"candidates": [
        {"content": {"parts": [{"text": ""}]}, "finishReason": "STOP"}]}),
])
def test_terminal_envelope_failures(small, tmp_path, name, envelope):
    selection_path, governance = _full_setup(small, tmp_path)
    script = _script_for(small.packets)
    script[small.packets[0]["cik"]]["envelope"] = envelope
    result, _ = _live(small, tmp_path, selection_path=selection_path,
                      governance=governance, script=script)
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "provider_error"
    assert receipt["stopping_row_index"] == 1
    assert receipt["records_completed_before_failure"] == 0
    assert receipt["raw_responses_captured"] == 0  # no archive entry exists
    # The wire envelope itself was captured before the stop.
    assert receipt["capture_files_written"] >= 1
    assert not (result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()
    _assert_no_google_import()


def test_screen_validation_failures_flow_from_extracted_text(small, tmp_path):
    # Invalid JSON text: archived first, then refused as invalid_model_json.
    selection_path, governance = _full_setup(small, tmp_path)
    script = _script_for(small.packets)
    script[small.packets[0]["cik"]]["text"] = "this is { not json"
    result, _ = _live(small, tmp_path, selection_path=selection_path,
                      governance=governance, script=script)
    assert result.receipt["reason_code"] == "invalid_model_json"
    assert result.receipt["raw_responses_captured"] == 1  # archived pre-parse
    assert result.receipt["records_completed_before_failure"] == 0
    # A non-resolving quote is a quote_resolution_failure, as in ADR-108.
    script = _script_for(small.packets)
    bad = json.loads(_model_output(small.packets[0], "LIKELY_ELIGIBLE"))
    bad["positive_evidence"][0]["quote"] = "words in no passage anywhere"
    script[small.packets[0]["cik"]]["text"] = json.dumps(bad)
    result, _ = _live(small, tmp_path / "q", selection_path=selection_path,
                      governance=governance, script=script, run_id="q")
    assert result.receipt["reason_code"] == "quote_resolution_failure"


def test_budget_exhaustion_is_terminal(small, tmp_path):
    selection_path = _selection(small, tmp_path, "full_cohort")
    governance = _governance(
        tmp_path, cohort=small, selection_path=selection_path,
        selection_kind="full_cohort", logical=3,
        mutate_authorization=lambda a: a.update(budget_max_input_tokens=100))
    result, _ = _live(small, tmp_path, selection_path=selection_path,
                      governance=governance)
    assert result.status == "failed"
    assert result.receipt["reason_code"] == "provider_error"
    assert "input-token budget" in result.receipt["detail"]
    # The count envelope was captured; no archive entry, no manifest.
    assert result.receipt["raw_responses_captured"] == 0
    assert result.receipt["count_captures"] == 1
    assert not (result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()


def test_output_budget_stops_before_any_post_limit_send(small, tmp_path):
    """The output ceiling is a pre-send refusal: row 1 completes (verified
    usage: 7 output tokens), and row 2 is refused before its handshake,
    countTokens or generateContent — with a ceiling of exactly one route
    maximum, the accounted 7 tokens leave no room for another 16384."""
    selection_path = _selection(small, tmp_path, "full_cohort")
    governance = _governance(
        tmp_path, cohort=small, selection_path=selection_path,
        selection_kind="full_cohort", logical=3,
        mutate_authorization=lambda a: a.update(
            budget_max_output_tokens=16384))
    result, factory = _live(small, tmp_path, selection_path=selection_path,
                            governance=governance)
    assert result.status == "failed"
    receipt = result.receipt
    assert receipt["reason_code"] == "provider_error"
    assert "output-token budget" in receipt["detail"]
    assert receipt["stopping_row_index"] == 2
    assert receipt["stopping_cik"] == small.packets[1]["cik"]
    assert receipt["records_completed_before_failure"] == 1
    assert receipt["raw_responses_captured"] == 1
    # Not one external call exists for the stopping or any later row.
    assert factory.count_calls == 1
    assert factory.generate_calls == 1
    assert receipt["count_captures"] == 1
    assert receipt["generate_captures"] == 1
    assert receipt["external_requests_made"] == 2
    # No records JSONL, capture ledger, or manifest was written.
    assert not (result.run_dir / ls.RECORDS_FILENAME).exists()
    assert not (result.run_dir / ll.CAPTURE_LEDGER_FILENAME).exists()
    assert not (result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists()
    # The completed first row's evidence is retained: its archive line and
    # both of its wire captures.
    archive_lines = (result.run_dir / ls.RAW_RESPONSES_FILENAME).read_text(
        encoding="utf-8").splitlines()
    assert len(archive_lines) == 1
    assert json.loads(archive_lines[0])["cik"] == small.packets[0]["cik"]
    captures = sorted(
        str(p.relative_to(result.run_dir))
        for p in (result.run_dir / ll.CAPTURES_DIRNAME).rglob("*")
        if p.is_file())
    assert len(captures) == 2
    assert all(small.packets[0]["cik"] in name for name in captures)


def test_unverified_output_usage_consumes_the_declared_maximum(small, tmp_path):
    """A completed row whose terminal usage is absent must consume the
    route's declared maximum from future headroom — a ceiling of one route
    maximum less than two rows' worth is then exhausted after one row,
    where verified usage would have left ample room."""
    selection_path = _selection(small, tmp_path, "full_cohort")
    governance = _governance(
        tmp_path, cohort=small, selection_path=selection_path,
        selection_kind="full_cohort", logical=3,
        mutate_authorization=lambda a: a.update(
            budget_max_output_tokens=2 * 16384 - 1))
    script = _script_for(small.packets)
    first = small.packets[0]
    script[first["cik"]]["envelope"] = {
        "candidates": [{
            "content": {"parts": [{"text": script[first["cik"]]["text"]}]},
            "finishReason": "STOP",
        }],
        # No usageMetadata at all: the row completes, but its output cannot
        # be verified, so the full 16384 is accounted.
    }
    result, factory = _live(small, tmp_path, selection_path=selection_path,
                            governance=governance, script=script)
    assert result.status == "failed"
    assert result.receipt["reason_code"] == "provider_error"
    assert "output-token budget" in result.receipt["detail"]
    assert result.receipt["stopping_row_index"] == 2
    assert result.receipt["records_completed_before_failure"] == 1
    assert factory.generate_calls == 1  # no post-limit send of any kind
    # Under the same ceiling, a verified first row passes: 7 + 16384 fits.
    governance_ok = _governance(
        tmp_path / "ok", cohort=small, selection_path=selection_path,
        selection_kind="full_cohort", logical=3,
        mutate_authorization=lambda a: a.update(
            budget_max_output_tokens=2 * 16384 - 1))
    ok, _ = _live(small, tmp_path / "ok", selection_path=selection_path,
                  governance=governance_ok, run_id="verified")
    assert ok.status == "completed"
    assert ok.request_accounting["tokens_out_reported"] == 21


def test_wall_clock_budget_is_enforced_by_the_wrapper():
    moments = [datetime(2026, 8, 19, 9, 0, 0, tzinfo=timezone.utc)]

    def clock():
        moments[0] = moments[0] + timedelta(seconds=40)
        return moments[0]

    budget = ll.ScreenCohortBudget(
        authorization={
            "budget_max_input_tokens": 1000,
            "budget_max_output_tokens": 1000,
            "budget_max_estimated_cost_micros": 10_000_000,
            "budget_max_wall_clock_seconds": 30,
            "budget_max_external_requests": 12,
        },
        authorization_sha256="a" * 64, run_id="wc", clock=clock)
    with pytest.raises(ls.ScreenProviderTerminalError, match="wall-clock"):
        budget.admit(measured_input_tokens=10, request_digest="b" * 64)


def test_count_witness_disagreement_is_terminal(small, tmp_path):
    selection_path, governance = _full_setup(small, tmp_path)
    script = _script_for(small.packets)
    script[small.packets[0]["cik"]]["witness"] = 999
    result, _ = _live(small, tmp_path, selection_path=selection_path,
                      governance=governance, script=script)
    assert result.status == "failed"
    assert "reconciliation" in result.receipt["detail"].lower() \
        or "count" in result.receipt["detail"].lower()
    # A count body with no total is terminal the same closed way.
    script = _script_for(small.packets)
    script[small.packets[0]["cik"]]["count_body"] = {"unrelated": 1}
    result, _ = _live(small, tmp_path / "n", selection_path=selection_path,
                      governance=governance, script=script, run_id="n")
    assert result.status == "failed"


def test_capture_sink_is_write_once(small, tmp_path):
    connector = ll.VertexGeminiProviderV2(
        vertex_project=VERTEX_PROJECT, vertex_location=VERTEX_LOCATION,
        expected_authorization_sha256="a" * 64, max_provider_requests=3,
        endpoint_allowlist=tuple(_endpoints()))
    run_dir = tmp_path / "sinkrun"
    run_dir.mkdir()
    ledger: list[dict] = []
    adapter = ll.VertexLineageScreenProvider(
        connector=connector, authorization_sha256="a" * 64,
        authorization_allowlist=tuple(_endpoints()),
        enablement_allowlist=tuple(_endpoints()), run_dir=run_dir,
        budget=ll.ScreenCohortBudget(
            authorization={
                "budget_max_input_tokens": 1000,
                "budget_max_output_tokens": 1000,
                "budget_max_estimated_cost_micros": 10_000_000,
                "budget_max_wall_clock_seconds": 60,
                "budget_max_external_requests": 12,
            },
            authorization_sha256="a" * 64, run_id="s", clock=FIXED_CLOCK),
        packet_sha_by_key={}, prompt_template_sha256="c" * 64, ledger=ledger)
    sink = adapter._sink_for_row("00001-x-y")
    first = sink(operation_label="count_tokens", attempt_ordinal=1,
                 raw_bytes=b"body", send_outcome="ok",
                 sdk_call_outcome="returned", provider_reason_code=None)
    assert first.capture_disposition == "raw_persisted"
    from dynamic_ai_products.extraction.provider_adapter import CaptureSinkError
    with pytest.raises(CaptureSinkError):
        sink(operation_label="count_tokens", attempt_ordinal=1,
             raw_bytes=b"other", send_outcome="ok",
             sdk_call_outcome="returned", provider_reason_code=None)
    assert ledger[-1]["capture_disposition"] == "body_captured_persistence_failed"


# --- Dry run, determinism, boundaries -------------------------------------------------


def test_dry_run_validates_calls_nothing_writes_nothing(small, tmp_path):
    selection_path, governance = _full_setup(small, tmp_path)
    result, factory = _live(small, tmp_path, selection_path=selection_path,
                            governance=governance, dry_run=True)
    assert result.status == "dry_run"
    assert result.run_dir is None
    assert result.planned_screened == 3
    assert result.planned_insufficient == 2
    assert factory.opens == 0
    assert not (tmp_path / "screen").exists()
    _assert_no_google_import()


def test_live_runs_are_deterministic_and_write_once(small, tmp_path):
    selection_path, governance = _full_setup(small, tmp_path)
    one, _ = _live(small, tmp_path / "one", selection_path=selection_path,
                   governance=governance, run_id="same-id")
    two, _ = _live(small, tmp_path / "two", selection_path=selection_path,
                   governance=governance, run_id="same-id")
    for filename in (ls.RECORDS_FILENAME, ls.RAW_RESPONSES_FILENAME,
                     ll.CAPTURE_LEDGER_FILENAME):
        assert ((one.run_dir / filename).read_bytes()
                == (two.run_dir / filename).read_bytes())
    assert one.manifest_path.read_bytes() == two.manifest_path.read_bytes()
    with pytest.raises(FileExistsError):
        _live(small, tmp_path / "one", selection_path=selection_path,
              governance=governance, run_id="same-id")


def test_fresh_process_preflight_never_imports_google(tmp_path):
    """The absolute no-SDK proof, in a process nothing else has touched:
    importing the live module and driving the preflight to a refusal leaves
    ``google`` entirely absent from ``sys.modules``."""
    script = (
        "import sys\n"
        "from datetime import datetime, timezone\n"
        "from dynamic_ai_products import lineage_screen_live as ll\n"
        "from dynamic_ai_products.universe.lineage_screen import ScreenInputError\n"
        "try:\n"
        "    ll.run_lineage_screen_live(\n"
        f"        repo_root={str(ROOT)!r},\n"
        f"        packet_manifest_path={str(tmp_path / 'none.json')!r},\n"
        f"        selection_artifact_path={str(tmp_path / 'none.json')!r},\n"
        f"        governance_root={str(tmp_path)!r},\n"
        "        authorization_reference='ghost.json',\n"
        "        authorization_sha256='0' * 64,\n"
        f"        output_dir={str(tmp_path / 'out')!r},\n"
        "        run_id='fresh',\n"
        "        logical_request_cap=1,\n"
        "        provider_attempt_cap=3,\n"
        "        clock=lambda: datetime.now(timezone.utc),\n"
        "    )\n"
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


def test_the_live_binding_is_a_top_level_module_and_universe_stays_clean():
    """The committed E-P boundary guards forbid any universe module from
    referencing the provider or extraction stacks, so the live binding lives
    beside provenance.py as a top-level composition module. No universe
    module may gain such an import, and nothing outside sdk_factory may
    import google."""
    import ast

    universe_dir = ROOT / "src" / "dynamic_ai_products" / "universe"
    offenders: dict[str, set[str]] = {}
    for path in sorted(universe_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                parts = name.split(".")
                if "providers" in parts or "extraction" in parts \
                        or parts[0] == "google":
                    offenders.setdefault(path.name, set()).add(name)
    assert offenders == {}, offenders
    live = ROOT / "src" / "dynamic_ai_products" / "lineage_screen_live.py"
    assert live.is_file()
    tree = ast.parse(live.read_text(encoding="utf-8"))
    imported = {
        (node.module or "") for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert any("providers" in name.split(".") for name in imported)
    assert any("extraction" in name.split(".") for name in imported)
    assert not any(name.split(".")[0] == "google" for name in imported)


# --- CLI --------------------------------------------------------------------------------


def _cli(*args):
    return subprocess.run([sys.executable, str(CLI), *args],
                          capture_output=True, text=True, check=False)


def test_cli_select_screen_rows_end_to_end(small, tmp_path):
    completed = _cli("--mode", "select-screen-rows",
                     "--packet-manifest", str(small.manifest_path),
                     "--selection-kind", "full_cohort",
                     "--output-dir", str(tmp_path / "out"),
                     "--run-id", "cli-sel")
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["status"] == "completed"
    artifact = json.loads(Path(payload["selection_artifact"])
                          .read_text(encoding="utf-8"))
    assert artifact["selection_kind"] == "full_cohort"
    # Canary without a seed is refused before anything exists.
    refused = _cli("--mode", "select-screen-rows",
                   "--packet-manifest", str(small.manifest_path),
                   "--selection-kind", "canary_100",
                   "--output-dir", str(tmp_path / "o2"), "--run-id", "r")
    assert refused.returncode != 0
    assert "--selection-seed" in refused.stderr
    assert not (tmp_path / "o2").exists()


def test_cli_live_mode_dry_run_and_preflight_refusal(small, tmp_path):
    selection_path, governance = _full_setup(small, tmp_path)
    completed = _cli("--mode", "screen-universe-lineage-live",
                     "--packet-manifest", str(small.manifest_path),
                     "--selection-artifact", str(selection_path),
                     "--governance-root", str(governance.root),
                     "--screen-authorization", governance.reference,
                     "--screen-authorization-sha256", governance.sha256,
                     "--logical-request-cap", "3",
                     "--provider-attempt-cap", "9",
                     "--output-dir", str(tmp_path / "out"),
                     "--run-id", "cli-dry", "--dry-run")
    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout)["status"] == "dry_run"
    assert not (tmp_path / "out").exists()
    # A wrong authorization digest refuses with no output directory.
    refused = _cli("--mode", "screen-universe-lineage-live",
                   "--packet-manifest", str(small.manifest_path),
                   "--selection-artifact", str(selection_path),
                   "--governance-root", str(governance.root),
                   "--screen-authorization", governance.reference,
                   "--screen-authorization-sha256", "0" * 64,
                   "--logical-request-cap", "3",
                   "--provider-attempt-cap", "9",
                   "--output-dir", str(tmp_path / "out"),
                   "--run-id", "cli-bad")
    assert refused.returncode == 2
    assert "hashes to" in refused.stderr
    assert not (tmp_path / "out").exists()


def test_cli_live_mode_requires_all_flags(tmp_path):
    completed = _cli("--mode", "screen-universe-lineage-live",
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    for flag in ("--packet-manifest", "--selection-artifact",
                 "--governance-root", "--screen-authorization",
                 "--screen-authorization-sha256", "--logical-request-cap",
                 "--provider-attempt-cap"):
        assert flag in completed.stderr
    assert not (tmp_path / "o").exists()


@pytest.mark.parametrize("flag,value", [
    ("--provider", "mock"),
    ("--screen-fixture", "f.json"),
    ("--config", "c.yaml"),
    ("--bundle-dir", "b"),
    ("--selection-seed", "3"),
    ("--selection-kind", "canary_100"),
])
def test_cli_live_mode_accepts_no_mock_or_selection_flags(tmp_path, flag, value):
    completed = _cli("--mode", "screen-universe-lineage-live", flag, value,
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert flag in completed.stderr
    assert "does not accept" in completed.stderr
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
    "screen-universe-lineage",
]


@pytest.mark.parametrize("mode", _OTHER_MODES)
def test_every_other_mode_refuses_the_live_screen_flags(tmp_path, mode):
    completed = _cli("--mode", mode,
                     "--selection-artifact", "s.json",
                     "--governance-root", "g",
                     "--screen-authorization", "a.json",
                     "--screen-authorization-sha256", "0" * 64,
                     "--output-dir", str(tmp_path / "o"), "--run-id", "r")
    assert completed.returncode != 0
    assert "does not accept" in completed.stderr
    for flag in ("--selection-artifact", "--governance-root",
                 "--screen-authorization", "--screen-authorization-sha256"):
        assert flag in completed.stderr
    assert not (tmp_path / "o").exists()


# --- Predecessor byte-identity and registry ---------------------------------------------


# --- ADR-110: the v2 prompt successor and the v0.3 manifest ---------------------------


ARCHETYPES = (
    "FUNCTIONAL_SOFTWARE", "ADAPTIVE_DIGITAL_SERVICE", "DATA_ANALYTICS_PRODUCT",
    "TRANSACTION_INFRASTRUCTURE", "MARKETPLACE_COORDINATION", "CONTENT_CATALOG",
    "ATTENTION_SOCIAL_PLATFORM", "INTERACTIVE_ENTERTAINMENT",
    "HARDWARE_SOFTWARE_SYSTEM", "HUMAN_MANAGED_SERVICE", "ECOMMERCE_RETAIL",
    "PHYSICAL_SERVICE_NETWORK", "OTHER",
)


def test_the_live_route_renders_v3_and_the_mock_route_still_renders_v1():
    assert ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH == (
        "prompts/discovery/universe_high_recall_screen.v4.md")
    assert ls.PROMPT_TEMPLATE_RELATIVE_PATH != (
        ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH)
    assert (ROOT / ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH).is_file()
    # The live module owns its own path and does not import the
    # predecessor's constant (checked structurally, not by substring: the
    # live name legitimately ends with the predecessor's name).
    import ast

    tree = ast.parse((ROOT / "src" / "dynamic_ai_products"
                      / "lineage_screen_live.py").read_text(encoding="utf-8"))
    imported = {
        alias.name for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) for alias in node.names
    }
    assert "PROMPT_TEMPLATE_RELATIVE_PATH" not in imported
    # The renderer and row validator are still reused, never re-implemented.
    assert {"render_lineage_screen_prompt", "_validate_row_output"} <= imported


def test_live_prompt_enumerates_the_closed_vocabulary_and_the_rules():
    text = (ROOT / ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH).read_text(
        encoding="utf-8")
    # Exactly the thirteen taxonomy values, each present as an exact token.
    from dynamic_ai_products.universe.models import Archetype
    from typing import get_args

    assert set(get_args(Archetype)) == set(ARCHETYPES)
    for value in ARCHETYPES:
        assert value in text, value
    # No invented member sneaks into the list block.
    block = text.split("```text", 1)[1].split("```", 1)[0]
    assert [line.strip() for line in block.strip().splitlines()] == list(ARCHETYPES)
    # The three explicit rules the canary proved were missing.
    lowered = text.lower()
    assert "never invent synonyms" in lowered
    assert "return `[]`" in lowered or "return []" in lowered
    assert "productivity/efficiency" in lowered  # named as invalid
    # v1's semantics survive verbatim in the successor.
    v1 = (ROOT / ls.PROMPT_TEMPLATE_RELATIVE_PATH).read_text(encoding="utf-8")
    for sentence in (
        "Use only the supplied baseline-dated SEC evidence.",
        "Use a deliberately high-recall standard.",
        "Every positive claim has a direct quote.",
        "Internal software use alone does not create an eligible product.",
        "BASELINE_SEC_PASSAGES:",
    ):
        assert sentence in v1 and sentence in text, sentence


def test_the_closed_validator_still_rejects_the_measured_canary_label():
    """The fix is the prompt, never a relaxed validator: the exact value the
    first governed canary returned must still be refused."""
    from pydantic import ValidationError

    from dynamic_ai_products.universe.models import HighRecallScreenOutput

    payload = {
        "cik": "0000017843", "company_id": "CIK0000017843",
        "screen_status": "BOUNDARY_OR_UNCERTAIN",
        "plausible_customer_facing_digital_product": True,
        "candidate_customer_value_archetypes": ["Productivity/Efficiency"],
        "positive_evidence": [], "negative_or_boundary_evidence": [],
        "missing_evidence": [], "confidence": "medium",
    }
    with pytest.raises(ValidationError, match="literal_error|Input should be"):
        HighRecallScreenOutput.model_validate(payload)
    # Every closed value validates, and an empty array is always valid.
    for value in ARCHETYPES:
        HighRecallScreenOutput.model_validate(
            dict(payload, candidate_customer_value_archetypes=[value]))
    HighRecallScreenOutput.model_validate(
        dict(payload, candidate_customer_value_archetypes=[]))


@pytest.mark.parametrize("stale_template", [
    "prompts/discovery/universe_high_recall_screen.md",
    "prompts/discovery/universe_high_recall_screen.v2.md",
    "prompts/discovery/universe_high_recall_screen.v3.md",
])
def test_an_authorization_bound_to_a_superseded_prompt_refuses_before_anything(
        small, tmp_path, stale_template):
    """A live authorization minted against any superseded template is stale
    and refuses before output, SDK import, or network (ADR-110/111)."""
    v1_sha = sha256((ROOT / stale_template).read_bytes()).hexdigest()
    selection_path = _selection(small, tmp_path, "full_cohort")
    governance = _governance(tmp_path, cohort=small,
                             selection_path=selection_path,
                             selection_kind="full_cohort", logical=3,
                             prompt_sha256=v1_sha)
    with pytest.raises(ls.ScreenInputError, match="prompt|stale"):
        _live(small, tmp_path, selection_path=selection_path,
              governance=governance)
    assert not (tmp_path / "screen").exists()
    _assert_no_google_import()
    # And the valid v2 binding is exactly the live template's bytes.
    live_sha = sha256(
        (ROOT / ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH).read_bytes()).hexdigest()
    assert live_sha != v1_sha
    ok = _governance(tmp_path / "ok", cohort=small,
                     selection_path=selection_path,
                     selection_kind="full_cohort", logical=3)
    assert ok.authorization["prompt_template_sha256"] == live_sha


def test_manifest_generations_mutually_reject(small, tmp_path):
    """Every generation pins its own prompt path as a const, so a manifest
    written under one is refused by all the others (ADR-109/110/111)."""
    selection_path, governance = _full_setup(small, tmp_path)
    result, _ = _live(small, tmp_path, selection_path=selection_path,
                      governance=governance)
    assert result.status == "completed"
    live = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    v2 = Draft202012Validator(MANIFEST_V2_SCHEMA, format_checker=FormatChecker())
    v3 = Draft202012Validator(MANIFEST_V3_SCHEMA, format_checker=FormatChecker())
    v4 = Draft202012Validator(MANIFEST_V4_SCHEMA, format_checker=FormatChecker())
    v5 = Draft202012Validator(MANIFEST_V5_SCHEMA, format_checker=FormatChecker())
    # The live v0.5 manifest validates only under v0.5.
    assert list(v5.iter_errors(live)) == []
    assert list(v4.iter_errors(live))
    assert list(v3.iter_errors(live))
    assert list(v2.iter_errors(live))

    def reshape(prompt_path, key, version):
        return dict(live, prompt_template_path=prompt_path,
                    schema_versions={
                        **{k: v for k, v in live["schema_versions"].items()
                           if not k.startswith("universe_screen_manifest_v")},
                        key: version})

    as_v3 = reshape("prompts/discovery/universe_high_recall_screen.v2.md",
                    "universe_screen_manifest_v3", "0.3.0")
    assert list(v3.iter_errors(as_v3)) == []
    assert list(v4.iter_errors(as_v3))
    assert list(v5.iter_errors(as_v3))
    assert list(v2.iter_errors(as_v3))

    as_v2 = reshape("prompts/discovery/universe_high_recall_screen.md",
                    "universe_screen_manifest_v2", "0.2.0")
    assert list(v2.iter_errors(as_v2)) == []
    assert list(v3.iter_errors(as_v2))
    assert list(v4.iter_errors(as_v2))
    assert list(v5.iter_errors(as_v2))


def test_live_prompt_renders_through_the_predecessor_renderer(small):
    """The live route reuses the predecessor renderer unchanged: the v2
    template carries the same three placeholders and renders identically
    evidence-minimal metadata."""
    template = (ROOT / ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH).read_text(
        encoding="utf-8")
    packet = small.packets[0]
    rendered = ls.render_lineage_screen_prompt(template, packet)
    assert "{{" not in rendered
    start = rendered.index("COMPANY_METADATA:\n") + len("COMPANY_METADATA:\n")
    end = rendered.index("\n\nBASELINE_SEC_PASSAGES:")
    assert rendered[start:end] == (
        f"cik: {packet['cik']}\n"
        f"accession: {packet['accession']}\n"
        f"form: {packet['form']}\n"
        f"filing_date: {packet['baseline_filing_date']}")
    for value in ARCHETYPES:
        assert value in rendered


def test_short_citation_refs_resolve_before_the_unchanged_strict_validator(small):
    """P001 is model-facing only; accepted records still bind hash ids."""
    packet = small.packets[0]
    template = (ROOT / ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH).read_text(
        encoding="utf-8")
    rendered, refs = ll.render_live_prompt_with_citation_refs(template, packet)
    assert "passage_id=P001" in rendered
    assert packet["passages"][0]["passage_id"] not in rendered
    quote = packet["passages"][0]["text"][:40]
    raw = json.dumps({
        "screen_status": "BOUNDARY_OR_UNCERTAIN",
        "plausible_customer_facing_digital_product": True,
        "candidate_customer_value_archetypes": [],
        "positive_evidence": [{
            "source_id": packet["source_id"], "passage_id": "P001",
            "quote": quote, "supported_claim": "Fixture claim.",
        }],
        "negative_or_boundary_evidence": [], "missing_evidence": [],
        "confidence": "medium",
    })
    resolved = ll.resolve_live_citation_refs(raw, refs)
    output = ls._validate_row_output(resolved, packet)
    assert output.positive_evidence[0].passage_id == packet["passages"][0]["passage_id"]
    unknown = raw.replace("P001", "P999")
    with pytest.raises(ls._RowValidationFailure, match="passage_id"):
        ls._validate_row_output(ll.resolve_live_citation_refs(unknown, refs), packet)


# --- ADR-111: evidence identity and quote binding -------------------------------------


def test_v4_prompt_states_the_short_reference_and_quote_rules():
    text = (ROOT / ll.LIVE_PROMPT_TEMPLATE_RELATIVE_PATH).read_text(
        encoding="utf-8")
    flat = " ".join(text.split())
    lowered = flat.lower()
    assert "short deterministic citation reference" in lowered
    assert "P001" in text and "P017" in text
    assert "never invent, alter, pad, truncate, or substitute a reference" in lowered
    assert "contiguous, verbatim substring" in lowered
    assert "normally no more than 280 characters" in lowered
    assert "correct it or drop that evidence object" in lowered
    assert "do not invent an identifier" in lowered
    assert "an empty evidence array is always better than an unverifiable" \
        in lowered
    # v2's semantics survive verbatim in the successor.
    v2 = (ROOT / "prompts" / "discovery"
          / "universe_high_recall_screen.v2.md").read_text(encoding="utf-8")
    for value in ARCHETYPES:
        assert value in text
    for sentence in (
        "Use only the supplied baseline-dated SEC evidence.",
        "Use a deliberately high-recall standard.",
        "Never invent synonyms, prose labels, descriptive phrases, or new",
        "Every positive claim has a direct quote.",
        "BASELINE_SEC_PASSAGES:",
    ):
        assert sentence in v2 and sentence in text, sentence


def test_the_measured_evidence_defects_are_all_refused(small, tmp_path):
    """The three shapes the second canary produced must each stop the run,
    with the strict validator unchanged: a header-contaminated source_id, a
    passage_id belonging to another passage, and a quote that occurs only
    elsewhere."""
    selection_path, governance = _full_setup(small, tmp_path)
    packet = small.packets[0]
    passage = packet["passages"][0]
    other_packet = small.packets[1]
    other_passage = other_packet["passages"][0]

    def with_evidence(source_id, passage_id, quote):
        payload = json.loads(_model_output(packet, "LIKELY_ELIGIBLE"))
        payload["positive_evidence"] = [{
            "source_id": source_id, "passage_id": passage_id,
            "quote": quote, "supported_claim": "A claim.",
        }]
        return json.dumps(payload)

    cases = {
        # Exactly the row-4 shape: the header's two fields concatenated.
        "header_contaminated_source_id": with_evidence(
            f"{packet['source_id']} passage_id={passage['passage_id']}",
            passage["passage_id"], passage["text"][:60]),
        # An id from a different passage of a different packet.
        "foreign_passage_id": with_evidence(
            packet["source_id"], other_passage["passage_id"],
            passage["text"][:60]),
        # A quote that exists only in another passage's body.
        "quote_from_another_passage": with_evidence(
            packet["source_id"], passage["passage_id"],
            other_passage["text"][:60]),
        # A quote taken from the rendered header rather than the body.
        "quote_from_the_header": with_evidence(
            packet["source_id"], passage["passage_id"],
            f"source_id={packet['source_id']}"),
    }
    for name, raw in cases.items():
        script = _script_for(small.packets)
        script[packet["cik"]]["text"] = raw
        result, factory = _live(small, tmp_path / name,
                                selection_path=selection_path,
                                governance=governance, script=script,
                                run_id=f"ev-{name[:12]}")
        assert result.status == "failed", name
        assert result.receipt["reason_code"] == "quote_resolution_failure", name
        assert result.receipt["stopping_row_index"] == 1, name
        assert result.receipt["records_completed_before_failure"] == 0, name
        # Archived before parsing, and no post-stop send happened.
        assert result.receipt["raw_responses_captured"] == 1, name
        assert factory.generate_calls == 1, name
        assert not (result.run_dir / ls.SCREEN_MANIFEST_FILENAME).exists(), name
    # The well-formed triple still passes, so the guard is not vacuous.
    script = _script_for(small.packets)
    script[packet["cik"]]["text"] = with_evidence(
        packet["source_id"], passage["passage_id"], passage["text"][:60])
    ok, _ = _live(small, tmp_path / "valid", selection_path=selection_path,
                  governance=governance, run_id="ev-valid", script=script)
    assert ok.status == "completed"
    _assert_no_google_import()


def test_adr108_predecessors_are_byte_identical():
    """ADR-109 may not move its predecessor: the v0.1 screen module, its two
    schemas and its test module are frozen at their ADR-108 bytes."""
    pins = {
        "src/dynamic_ai_products/universe/lineage_screen.py":
            "6bc2ae464c8c7d5ae7e16a24940db9e2849e60be692e32be81ce344e9cf8d77c",
        "schemas/universe_screen_record.schema.json":
            "066c49ed118125564fe16cbc57b413d7b96ea3d31bc47cf14a4e3b190693d253",
        "schemas/universe_screen_manifest.schema.json":
            "32e48d9a56bfa12115c3887b0944d0bb156f504c2ef6530401e500faf57e778d",
        # Rebaselined for registry literals three times (ADR-109/110/111),
        # then changed once more by ADR-112, which removed those two absolute
        # assertions permanently and moved registry version/count ownership
        # to the five evaluation guards. Every behavioral ADR-108 assertion,
        # and the mock path it exercises, is unchanged throughout.
        "tests/universe/test_lineage_screen.py":
            "e3f3691a297ce1949a93598569f72f720df4b4e2d793a4d3d02acfa295765671",
        # ADR-110 adds a successor prompt beside it; v1 itself never moves.
        "prompts/discovery/universe_high_recall_screen.md":
            "4ac95a4c4e6ffdfbc55de7aec98fe4d50b89c29fab79e75a10c07cc35d102194",
        "schemas/universe_screen_manifest.v2.schema.json":
            "d9ab3f69c58b29ad5ecbb4fa4c65c369cbf02b024cffa8ffe6b8570a8768bdff",
        # ADR-111 adds v3 beside them; v1, v2 and v0.3 never move.
        "prompts/discovery/universe_high_recall_screen.v2.md":
            "8bf0e3010241efe9aafd7d41af2857764c48ce218a7aa0f009086ec69a5d6694",
        "schemas/universe_screen_manifest.v3.schema.json":
            "72ece2c61b285c89b44c2319cfd6e1767d868ae1839bb22a8a7e8c7b7f2812ec",
    }
    for path, expected in pins.items():
        assert sha256((ROOT / path).read_bytes()).hexdigest() == expected, path


def test_registry_registers_the_four_live_screen_schemas():
    registry = json.loads(
        (ROOT / "schemas" / "schema_version_manifest.json")
        .read_text(encoding="utf-8"))
    # ADR-110 added the v0.3 live manifest successor (103 -> 104);
    # ADR-111 added v0.4 (104 -> 105); ADR-112 adds the three
    # diagnostic-canary contracts (105 -> 108); ADR-113 adds the v0.5
    # live manifest successor (108 -> 109); ADR-115 adds the three
    # diagnostic-repair contracts (109 -> 112). ADR-116 adds the V5
    # authoritative successor's record, authorization and manifest (112 -> 115).
    assert registry["manifest_version"] == "0.89.0"
    assert len(registry["schemas"]) == 242
    assert registry["schemas"]["universe_screen_manifest_v3"] == "0.3.0"
    assert registry["schemas"]["universe_screen_manifest_v4"] == "0.4.0"
    assert registry["schemas"]["universe_screen_manifest_v5"] == "0.5.0"
    assert registry["schemas"]["universe_screen_selection"] == "0.1.0"
    assert registry["schemas"]["universe_screen_adapter_enablement"] == "0.1.0"
    assert registry["schemas"]["universe_screen_live_authorization"] == "0.1.0"
    assert registry["schemas"]["universe_screen_manifest_v2"] == "0.2.0"
    assert registry["schemas"]["universe_screen_record_v2"] == "0.2.0"
    assert registry["schemas"]["universe_screen_live_authorization_v2"] == "0.2.0"
    assert registry["schemas"]["universe_screen_manifest_v6"] == "0.6.0"
