"""The four artifact counts, offline (ADR-035, ADR-036).

- **0** — every pre-authorization refusal; the run root is never created.
- **2** — the zero-admissible-passage non-run, which never consults governance,
  the meter, the provider, the prompt, or the schema pin.
- **7** — a terminal provider failure: five inputs (packet, rendered provider
  contents, prompt, client contract, authorization) plus an errored
  ``extraction_run`` and the provider-error record.
- **9** — an authorized successful run, adding the raw prediction, the envelopes,
  and the prediction manifest. Driven entirely by injected fakes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.manifests import (
    STAGE_OUTPUT_SCHEMA_SHA256 as _STAGE_OUTPUT_SCHEMA_SHA256,
    validate_provider_client_contract,
)
from dynamic_ai_products.extraction.provider_adapter import ProviderResponse
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.run_extraction import (
    CLIENT_CONTRACT_REFERENCE,
    ENVELOPES_REFERENCE,
    NON_RUN_REFERENCE,
    PACKET_REFERENCE,
    PREDICTION_MANIFEST_REFERENCE,
    RAW_REFERENCE,
    run_extraction_stage,
)
from dynamic_ai_products.providers.client_contract import build_client_contract
from dynamic_ai_products.providers.vertex_gemini import (
    RAW_CAPTURE_REPRESENTATION,
    VertexGeminiProvider,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS = REPO_ROOT / "schemas"
COMPANY = "CIK0001404655"
CUTOFF = "2024-12-31"
COVERAGE = {"reference": "coverage/source_family_coverage.json", "sha256": "d" * 64}
SOURCE_MANIFEST = {"reference": "snapshots/manifest.json", "sha256": "e" * 64}
DATES = {"sec-1": "2024-02-14", "sec-late": "2025-06-01"}
PROJECT = "my-research-project"
CAPTURED = b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'


class _Provider:
    """Injected fake. It never builds a client, resolves ADC, or opens a socket."""

    def __init__(self, *, fail=None):
        self._fail = fail
        self.calls = 0
        self.seen_request = None
        self.seen_digest = None
        self.seen_allowlist = None
        self.seen_enablement_allowlist = None

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        self.seen_digest = authorization_sha256
        self.seen_allowlist = endpoint_allowlist
        self.seen_enablement_allowlist = enablement_endpoint_allowlist


    def revoke_run_permission(self) -> None:
        self.revoked = getattr(self, 'revoked', 0) + 1
    def client_contract(self) -> dict:
        return build_client_contract(vertex_project=PROJECT)

    def complete(self, request):
        self.calls += 1
        self.seen_request = request
        if self._fail is not None:
            raise self._fail
        return ProviderResponse(
            raw_bytes=CAPTURED,
            model_provider="google_vertex_ai",
            model_name="gemini-2.5-flash",
            model_parameters={"temperature": 0},
            prompt_model_metadata={
                "model_name": "gemini-2.5-flash",
                "prompt_sha256": request.prompt_sha256,
                "api_version": "v1",
                "raw_capture_representation": RAW_CAPTURE_REPRESENTATION,
            },
        )


class _Refusal(Exception):
    def __init__(self, reason_code, attempt_count):
        super().__init__(reason_code)
        self.reason_code = reason_code
        self.attempt_count = attempt_count


def _passage(passage_id="p-1", text="the product ships an assistant", source_id="sec-1"):
    return {
        "passage_id": passage_id,
        "source_id": source_id,
        "text": text,
        "start_offset": 0,
        "end_offset": len(text),
    }


def write_company_identity(root: Path, **overrides) -> dict[str, str]:
    """Persist an admission artifact and return its pin (ADR-036, E-R).

    Mirrors the approved Pilot Universe Packet's identity fields. The legal name
    is only ever *read* from here; no test may pass one to the builder.
    """
    admission = {
        "company_id": COMPANY,
        "cik": COMPANY[3:].lstrip("0") or "0",
        "legal_name": "HUBSPOT INC",
        "observation_cutoff_date": CUTOFF,
    }
    unknown = sorted(set(overrides) - set(admission))
    assert not unknown, f"unknown admission override(s): {unknown}"
    admission.update(overrides)
    root.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(admission, sort_keys=True, separators=(",", ":")).encode("utf-8")
    (root / "pilot_universe_packet.json").write_bytes(payload)
    return {
        "reference": "pilot_universe_packet.json",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _run(tmp_path: Path, **overrides):
    governance_root = tmp_path / "governance-root"
    kwargs = {
        "run_root": tmp_path / "run",
        "repo_root": REPO_ROOT,
        "stage": "product_extraction",
        "company_id": COMPANY,
        "observation_cutoff_date": CUTOFF,
        "passages": [_passage()],
        "document_publication_dates": dict(DATES),
        "coverage_artifact": dict(COVERAGE),
        "source_snapshot_manifest": dict(SOURCE_MANIFEST),
        "code_commit": "be627003f3246b371c2b3ac13e813ef0bb112582",
        "run_created_at": "2026-07-29T00:00:00Z",
        "extraction_run_id": "ext-0001",
        "prediction_run_id": "pred-0001",
        "schema_root": str(SCHEMAS),
        "provider": _Provider(),
        "governance_artifact_root": governance_root,
        "company_identity_root": tmp_path / "identity",
        "company_identity_pin": write_company_identity(tmp_path / "identity"),
        "live_call_authorization_pin": write_governance_chain(governance_root),
        "budget_meter": FakeMeter(),
    }
    kwargs.update(overrides)
    return run_extraction_stage(**kwargs)


def _files(root: Path) -> set[str]:
    return {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}


# --- 9: the authorized successful run ----------------------------------------


# --- 7: terminal provider failure --------------------------------------------


def test_a_terminal_failure_produces_no_prediction_evidence(tmp_path: Path):
    with pytest.raises(ExtractionError):
        _run(tmp_path, provider=_Provider(fail=_Refusal("adc_expired", 1)))
    published = _files(tmp_path / "run")
    for absent in (RAW_REFERENCE, ENVELOPES_REFERENCE, PREDICTION_MANIFEST_REFERENCE):
        assert absent not in published


# --- 2: the non-run route -----------------------------------------------------


def test_the_non_run_route_publishes_exactly_two_artifacts(tmp_path: Path):
    outcome = _run(
        tmp_path, passages=[_passage("p-1", "late", "sec-late")]
    )
    assert outcome.verdict == "no_run"
    assert _files(outcome.run_root) == {PACKET_REFERENCE, NON_RUN_REFERENCE}


def test_the_non_run_route_consults_no_governance_meter_or_provider(tmp_path: Path):
    """No provider will be called, so requiring any of them would be theatre."""

    class _Exploding:
        def assert_run_permitted(
            self, *, authorization_sha256=None, endpoint_allowlist=None,
            enablement_endpoint_allowlist=None,
        ):
            raise AssertionError("the non-run route must not ask for permission")


        def revoke_run_permission(self) -> None:
            self.revoked = getattr(self, 'revoked', 0) + 1
        def client_contract(self):
            raise AssertionError("the non-run route must not request a contract")

        def complete(self, request):
            raise AssertionError("the non-run route must not call a provider")

    outcome = _run(
        tmp_path,
        passages=[_passage("p-1", "late", "sec-late")],
        provider=_Exploding(),
        governance_artifact_root=None,
        live_call_authorization_pin=None,
        budget_meter=None,
    )
    assert outcome.verdict == "no_run"
    assert len(_files(outcome.run_root)) == 2


# --- 0: pre-authorization refusals -------------------------------------------


def _count_mkdir(monkeypatch, run_root: Path) -> list[int]:
    counter = [0]
    original = Path.mkdir
    prefix = str(run_root)

    def counting(self, *args, **kwargs):
        if str(self) == prefix or str(self).startswith(prefix + "/"):
            counter[0] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", counting)
    return counter


# --- governance chain fixture (ADR-035) --------------------------------------
#
# Built locally in each test module rather than in a shared helper file: the E-L
# increment is scope-locked to a fixed path set, and a new helper module is not
# in it. The duplication is deliberate and small.

GOV_AUTH_REFERENCE = "governance/live_call_authorization.json"
GOV_ENABLEMENT_REFERENCE = "governance/adapter_enablement_record.json"
GOV_QUALIFICATION_REFERENCE = "governance/adapter_qualification_record.json"
STAGE_OUTPUT_SHA = _STAGE_OUTPUT_SCHEMA_SHA256["product_extraction"]
METER_IDENTITY = "e-m-reference-meter"
METER_VERSION = "0.1.0"
ENDPOINT_ALLOWLIST = ["https://us-central1-aiplatform.googleapis.com/v1/projects"]


class FakeMeter:
    """Conforming offline meter. It counts nothing; it only records and refuses.

    E-M supplies the real tokenizer, pricing table, and monotonic clock behind
    this same seam. This stand-in exists so the authorized path is testable
    without either, and it is never used in E-B.
    """

    def __init__(self, *, refuse: str | None = None, identity=METER_IDENTITY,
                 version=METER_VERSION, run_root=None):
        self._refuse = refuse
        self._identity = identity
        self._version = version
        self._run_root = run_root
        self.seen_request = None
        self.seen_max_output_tokens = None
        self.root_existed_at_call = None

    def meter_identity(self):
        return {"meter_identity": self._identity, "meter_version": self._version}

    def assert_within_budget(self, *, request, max_output_tokens, budget):
        self.seen_request = request
        self.seen_max_output_tokens = max_output_tokens
        if self._run_root is not None:
            self.root_existed_at_call = self._run_root.exists()
        if self._refuse:
            raise _MeterRefusal(self._refuse)


class _MeterRefusal(Exception):
    def __init__(self, reason_code):
        super().__init__(reason_code)
        self.reason_code = reason_code


def _client_contract_digest(project="my-research-project"):
    contract = validate_provider_client_contract(
        build_client_contract(vertex_project=project)
    )
    return sha256_bytes(canonical_json_bytes(contract))


def write_governance_chain(root: Path, **overrides):
    """Persist the three-ring chain and return the authorization pin.

    Unknown override keys raise: silently ignoring one would let a test think it
    had weakened a record when it had not, and pass for the wrong reason.
    """
    unknown = sorted(set(overrides) - {"qualification", "enablement", "authorization"})
    if unknown:
        raise AssertionError(f"unknown governance overrides: {unknown}")
    root.mkdir(parents=True, exist_ok=True)
    (root / "governance").mkdir(parents=True, exist_ok=True)

    qualification = {
        "contract": "adapter_qualification_record@0.1.0",
        "schema_version": "0.1.0",
        "qualification_id": "qual-0001",
        "adapter_identity": "dynamic_ai_products.providers.vertex_gemini",
        "adapter_version": "0.1.0",
        "adapter_family": "model_execution",
        # Qualified under the contract this run actually executes, and against
        # the released stage-output schema the run validates against.
        "execution_contract_id": "extraction_provider_client_contract@0.1.0",
        "execution_contract_sha256": _client_contract_digest(),
        "stage_output_contract_id": "product_observation@0.1.0",
        "stage_output_contract_sha256": STAGE_OUTPUT_SHA,
        "qualification_scope": "live_dev",
        "qualification_status": "qualified",
        "qualified_at": "2026-07-01T00:00:00Z",
    }
    qualification.update(overrides.pop("qualification", {}))
    qual_bytes = canonical_json_bytes(qualification)
    (root / GOV_QUALIFICATION_REFERENCE).write_bytes(qual_bytes)

    enablement = {
        "contract": "adapter_enablement_record@0.1.0",
        "schema_version": "0.1.0",
        "enablement_id": "enab-0001",
        "adapter_qualification_record_reference": GOV_QUALIFICATION_REFERENCE,
        "adapter_qualification_record_sha256": sha256_bytes(qual_bytes),
        "prompt_qualification_reference": "governance/prompt_qualification.json",
        "prompt_qualification_sha256": "3" * 64,
        "stage": "product_extraction",
        "stage_output_contract_id": "product_observation@0.1.0",
        "stage_output_contract_sha256": STAGE_OUTPUT_SHA,
        "routing_contract_id": "vertex_gemini_route@0.1.0",
        "routing_contract_sha256": "4" * 64,
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "endpoint_allowlist": list(ENDPOINT_ALLOWLIST),
        "enablement_status": "enabled_live_dev",
        "approver": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
    }
    enablement.update(overrides.pop("enablement", {}))
    enab_bytes = canonical_json_bytes(enablement)
    (root / GOV_ENABLEMENT_REFERENCE).write_bytes(enab_bytes)

    authorization = {
        "contract": "live_call_authorization@0.1.0",
        "schema_version": "0.1.0",
        "authorization_id": "auth-0001",
        "authorized_by": "methodology-owner",
        "effective_at": "2026-07-01T00:00:00Z",
        "expires_at": "2027-07-01T00:00:00Z",
        "deployment_environment_id": "dev-local",
        "rollout_state": "live_dev",
        "adapter_enablement_record_reference": GOV_ENABLEMENT_REFERENCE,
        "adapter_enablement_record_sha256": sha256_bytes(enab_bytes),
        "provider_client_contract_reference": CLIENT_CONTRACT_REFERENCE,
        "provider_client_contract_sha256": _client_contract_digest(),
        "budget_meter_identity": METER_IDENTITY,
        "budget_meter_version": METER_VERSION,
        "stage": "product_extraction",
        "company_id": "CIK0001404655",
        "observation_cutoff_date": "2024-12-31",
        "corpus_scope": "sec_only_partial",
        "budget_max_records": 1,
        "budget_max_requests": 3,
        "budget_max_input_tokens": 100000,
        "budget_max_output_tokens": 8192,
        "budget_max_estimated_cost_micros": 500000,
        "budget_max_wall_clock_seconds": 903,
        "budget_policy_version": "budget_policy_v1",
        "retry_policy_version": "extraction_provider_retry_policy_v1",
        "rate_limit_policy_version": "extraction_provider_rate_limit_policy_v1",
        "endpoint_allowlist": list(ENDPOINT_ALLOWLIST),
        "circuit_breaker_max_consecutive_failures": 1,
        "provider_called": True,
        "harness_run": False,
    }
    authorization.update(overrides.pop("authorization", {}))
    auth_bytes = canonical_json_bytes(authorization)
    (root / GOV_AUTH_REFERENCE).write_bytes(auth_bytes)
    return {"reference": GOV_AUTH_REFERENCE, "sha256": sha256_bytes(auth_bytes)}


# --- the runner binds the authorization allowlist to the connector -------------


# --- no post-handshake refusal leaves a spendable permit (v4.6) ----------------
#
# The permit outlives the client contract, the qualification's execution
# contract, the prompt, the meter, the budget, the run root, and the artifact
# writes. Any of those may refuse, so the orchestrator revokes on every exit.


class _PermitProbe:
    """A conforming provider that reports whether its permit is still live."""

    def __init__(self, *, contract_override=None):
        self._contract_override = contract_override
        self.activated = False
        self.revoked = 0
        self.factory_entries = 0

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:
        self.activated = True

    def revoke_run_permission(self) -> None:
        self.activated = False
        self.revoked += 1

    def client_contract(self) -> dict:
        if self._contract_override is not None:
            return self._contract_override
        return build_client_contract(vertex_project=PROJECT)

    def complete(self, request):
        # Stands in for the factory: reaching here means a permit was spendable.
        self.factory_entries += 1
        if not self.activated:
            raise _Refusal("live_call_not_authorized", 1)
        raise _Refusal("vertex_unavailable", 1)


def _post_handshake_refusal(tmp_path: Path, expected: str, **overrides):
    provider = overrides.pop("provider", None) or _PermitProbe()
    with pytest.raises(ExtractionError) as excinfo:
        _run(tmp_path, provider=provider, **overrides)
    assert excinfo.value.reason_code == expected
    # The handshake succeeded, so the permit existed and must now be gone.
    assert provider.activated is False
    assert provider.revoked >= 1
    assert provider.factory_entries == 0
    return provider


def test_revocation_is_idempotent_and_needs_no_sdk():
    """Clearing a field is the whole operation, so it cannot fail."""
    import sys

    before = {name for name in sys.modules if name.startswith("google")}
    provider = VertexGeminiProvider(
        vertex_project=PROJECT,
        expected_authorization_sha256="a" * 64,
        max_provider_requests=3,
        endpoint_allowlist=tuple(ENDPOINT_ALLOWLIST),
    )
    provider.assert_run_permitted(
        authorization_sha256="a" * 64,
        endpoint_allowlist=tuple(ENDPOINT_ALLOWLIST),
        enablement_endpoint_allowlist=tuple(ENDPOINT_ALLOWLIST),
    )
    for _ in range(3):
        provider.revoke_run_permission()
    with pytest.raises(Exception) as excinfo:
        provider.complete(None)
    assert getattr(excinfo.value, "reason_code", None) == "live_call_not_authorized"
    assert {name for name in sys.modules if name.startswith("google")} == before


class _BadRevoke(_PermitProbe):
    """Non-conforming: revocation is required to be infallible, and this is not."""

    def revoke_run_permission(self) -> None:
        raise RuntimeError("revocation exploded with secret-looking text")


def test_a_standalone_revocation_failure_raises_provider_refused():
    """No original failure in flight, so the revocation failure surfaces."""
    from dynamic_ai_products.extraction.run_extraction import _revoke_run_permission

    with pytest.raises(ExtractionError) as excinfo:
        _revoke_run_permission(_BadRevoke())
    assert excinfo.value.reason_code == "provider_refused"
    assert "revocation exploded" not in str(excinfo.value)


def test_an_in_flight_failure_is_preserved_over_a_revocation_failure():
    """Direct proof of the branch the old sys.exc_info() check could never reach."""
    from dynamic_ai_products.extraction.run_extraction import _revoke_run_permission

    with pytest.raises(ExtractionError) as excinfo:
        try:
            raise ExtractionError("the real reason", reason_code="schema_pin_mismatch")
        finally:
            _revoke_run_permission(_BadRevoke())
    assert excinfo.value.reason_code == "schema_pin_mismatch"


# ---------------------------------------------------------------------------
# Returned-digest integrity on the authorized route (E-L v4.6.2).
#
# The packet and client-contract writes were once bound to their expected digests
# by ``assert``, which ``python -O`` strips: the packet ``assert`` contained the
# write call itself, so under ``-O`` no packet was persisted, and the contract
# ``assert`` was a fail-closed integrity check that simply disappeared. Both are
# now unconditional writes plus ordinary ``if`` comparisons, and both mismatches
# must fail closed *after* a successful handshake without spending the permit.
# ---------------------------------------------------------------------------


def test_the_digest_guard_is_a_plain_function_not_an_assert():
    """Directly exercised, so ``-O`` cannot make it vacuous."""
    from dynamic_ai_products.extraction.run_extraction import _require_written_digest

    _require_written_digest("a" * 64, "a" * 64)  # equal: silent
    with pytest.raises(ExtractionError) as excinfo:
        _require_written_digest("a" * 64, "b" * 64)
    assert excinfo.value.reason_code == "write_error"
    assert "a" * 64 not in str(excinfo.value)
    assert "b" * 64 not in str(excinfo.value)
