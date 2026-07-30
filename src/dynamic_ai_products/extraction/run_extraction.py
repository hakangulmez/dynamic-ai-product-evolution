"""Stage-dispatched extraction orchestration (ADR-033, ADR-034, ADR-036).

**Every deterministic input is resolved before anything is created on disk.**
The packet is built in memory; the provider, its client contract, the resolved
prompt, and the stage output-schema pin are all validated while the run root
still does not exist. Only once all of them pass is ``mkdir`` called. A refused
run therefore leaves zero artifacts and there is nothing to roll back — the
guarantee is "never created", not "cleaned up afterwards".

That ordering also stops a wasted provider call: before this, the stage schema
pin was verified *after* ``complete()`` had already run and the raw bytes had
already been written, so a fully deterministic, pre-call-knowable mismatch
could only surface once the call had been paid for.

Four published shapes, each with an exact artifact count:

- **pre-authorization refusal** — 0 artifacts, no run root;
- **non-run** (zero admissible passages) — 2 artifacts, and no governance,
  meter, provider, prompt, or schema preflight is performed at all;
- **terminal provider failure** — 7 artifacts: packet, the rendered provider
  contents, prompt, client contract, the live-call authorization, an errored
  ``extraction_run``, and the provider-error record;
- **authorized successful run** — 9 artifacts: those five inputs — packet,
  rendered provider contents, prompt, client contract, authorization — plus the
  raw prediction, a completed ``extraction_run``, the envelopes, and the
  prediction manifest.

Neither a provider nor a budget meter is constructed here: both must be
injected, and both default to refusing (ADR-035).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from .errors import ExtractionError
from .input_packet import (
    build_extraction_input_packet,
    hydrate_pinned_artifact,
    packet_bytes,
)
from .manifests import (
    PACKET_CONTRACT_REQUIRING_IDENTITY,
    PROVIDER_ERROR_REASONS,
    build_extraction_run,
    build_non_run_record,
    build_provider_error_record,
    record_bytes,
    resolve_attempt_cap,
    resolve_stage_schema_hash,
    validate_authorization_client_contract,
    validate_authorization_scope,
    validate_budget_meter_identity,
    validate_governance_chain,
    validate_governance_semantics,
    validate_provider_client_contract,
    validate_qualification_execution_contract,
)
from .prediction_manifest import build_prediction_artifact_manifest, manifest_bytes
from .contents_renderer import RENDERER_VERSION, render_provider_contents
from .prompts import load_prompt, single_pass_prompt_plan
from .provider_adapter import ProviderRequest, require_budget_meter, require_provider
from .raw_artifacts import (
    build_prediction_envelope,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sha256_bytes,
    write_artifact,
    write_raw_prediction,
)

__all__ = ["ExtractionOutcome", "run_extraction_stage"]

PACKET_REFERENCE = "inputs/extraction_input_packet.json"
PROMPT_REFERENCE = "inputs/resolved_prompt.md"
# ADR-036 (E-R). The exact UTF-8 document the provider received. Persisted
# separately from the frozen prompt so "what was sent" is auditable on its own.
CONTENTS_REFERENCE = "inputs/rendered_provider_contents.md"
CLIENT_CONTRACT_REFERENCE = "inputs/provider_client_contract.json"
AUTHORIZATION_REFERENCE = "inputs/live_call_authorization.json"
NON_RUN_REFERENCE = "manifests/extraction_non_run_record.json"
EXTRACTION_RUN_REFERENCE = "manifests/extraction_run.json"
PROVIDER_ERROR_REFERENCE = "manifests/extraction_provider_error_record.json"
RAW_REFERENCE = "predictions/raw_prediction.json"
ENVELOPES_REFERENCE = "predictions/prediction_envelopes.jsonl"
PREDICTION_MANIFEST_REFERENCE = "predictions/prediction_run_manifest.json"

# Distinguishes "not supplied" from an explicitly supplied ``None``. Both a pin
# and a ``None`` are caller-channel violations, so ``None`` cannot be the
# default sentinel.
_PIN_UNSET = object()


class ExtractionOutcome:
    """Either a published provider run or a published non-run."""

    def __init__(
        self,
        *,
        verdict: str,
        run_root: Path,
        packet: dict[str, Any],
        packet_sha256: str,
        artifacts: dict[str, str],
    ) -> None:
        self.verdict = verdict
        self.run_root = run_root
        self.packet = packet
        self.packet_sha256 = packet_sha256
        self.artifacts = artifacts


def _require_absent_run_root(root: Path) -> None:
    if root.is_symlink() or root.exists():
        raise ExtractionError(
            f"run root already exists; runs are never overwritten: {root}",
            reason_code="run_root_exists",
        )


def _require_written_digest(observed: str, expected: str) -> None:
    """Bind a persisted artifact to the digest the run has already committed to.

    This was once written as ``assert write_artifact(...) == expected``, which
    was a production defect twice over: ``python -O`` strips ``assert``
    statements, so the ``write_artifact`` call itself vanished and no artifact was
    written at all, and the integrity comparison vanished with it. The write is
    therefore performed unconditionally by the caller and only its returned
    digest is passed here.

    Neither digest is reported. A hexadecimal digest is not secret, but the
    boundary has no channel for unexpected bytes and gains nothing from one:
    the artifact and the manifest are both on disk for an operator to compare.
    """
    if observed != expected:
        raise ExtractionError(
            "a persisted artifact does not match the digest the run committed to",
            reason_code="write_error",
        )


def _assert_run_permitted(client: object) -> None:
    """Ask the injected provider whether a run may proceed at all.

    Called before the run root exists. The provider's own exception type is
    never imported: only the duck-typed ``reason_code`` is read, so no upstream
    text can reach the boundary.
    """
    try:
        client.assert_run_permitted()
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        reason = getattr(exc, "reason_code", None)
        raise ExtractionError(
            "the injected provider refused this run",
            reason_code=reason if isinstance(reason, str) and reason else "provider_refused",
        ) from None


def _revoke_run_permission(client: object) -> None:
    """Drop the provider's permit. Safe to call while an exception propagates.

    Revocation is required to be idempotent and infallible, so a conforming
    provider cannot fail here. If a non-conforming one does, the original failure
    must still reach the caller: masking a client-contract mismatch with a
    revocation error would hide the real reason the run stopped.

    Whether an original failure is in flight is captured **before** the call.
    Reading ``sys.exc_info()`` inside the ``except`` block cannot answer the
    question: there it is necessarily the revocation exception itself, so the
    check would always say "something is in flight" and every revocation failure
    would be swallowed, including on the normal-return path.
    """
    original_failure_in_flight = sys.exc_info()[0] is not None
    try:
        client.revoke_run_permission()
    except Exception:  # noqa: BLE001 - the provider seam is total
        if original_failure_in_flight:
            # Preserve the real reason the run stopped.
            return
        # Nothing else was failing, so this is the failure. The provider's own
        # exception text never reaches the boundary.
        raise ExtractionError(
            "the injected provider could not revoke its run permission",
            reason_code="provider_refused",
        ) from None


def _client_contract_of(client: object) -> dict[str, Any]:
    try:
        contract = client.client_contract()
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        reason = getattr(exc, "reason_code", None)
        raise ExtractionError(
            "the injected provider could not supply a client contract",
            reason_code=(
                reason if isinstance(reason, str) and reason else "client_contract_invalid"
            ),
        ) from None
    return validate_provider_client_contract(contract)


def _assert_run_permitted_with(
    client: object,
    digest: str,
    endpoint_allowlist: Any,
    enablement_endpoint_allowlist: Any,
) -> None:
    """Hand the provider our verified digest and both verified allowlists.

    Both lists are forwarded, not compared here: endpoint normalization is
    provider-side grammar and ``extraction`` may not import ``providers``, so
    duplicating it would create a second set of rules that could drift from the
    one the capture client applies. The connector enforces
    ``enablement ⊇ authorization == connector``.
    """
    try:
        client.assert_run_permitted(
            authorization_sha256=digest,
            endpoint_allowlist=tuple(endpoint_allowlist or ()),
            enablement_endpoint_allowlist=tuple(enablement_endpoint_allowlist or ()),
        )
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        reason = getattr(exc, "reason_code", None)
        raise ExtractionError(
            "the injected provider refused this authorized run",
            reason_code=reason if isinstance(reason, str) and reason else "provider_refused",
        ) from None


def _meter_identity_of(meter: object) -> dict[str, Any]:
    try:
        identity = meter.meter_identity()
    except Exception as exc:  # noqa: BLE001 - the meter seam is total
        reason = getattr(exc, "reason_code", None)
        raise ExtractionError(
            "the injected budget meter could not report its identity",
            reason_code=(
                reason if isinstance(reason, str) and reason else "budget_meter_identity_mismatch"
            ),
        ) from None
    return identity


_METER_REASONS = frozenset(
    {
        "budget_input_tokens_exceeded",
        "budget_estimated_cost_exceeded",
        "budget_wall_clock_exceeded",
    }
)


def _assert_within_budget(
    meter: object, *, request: ProviderRequest, max_output_tokens: int, budget: dict[str, Any]
) -> None:
    """Meter the exact request the provider will receive.

    The meter's own exception type is never imported: only the duck-typed
    ``reason_code`` is read, so no upstream text can reach the boundary.
    """
    try:
        meter.assert_within_budget(
            request=request, max_output_tokens=max_output_tokens, budget=budget
        )
    except Exception as exc:  # noqa: BLE001 - the meter seam is total
        reason = getattr(exc, "reason_code", None)
        raise ExtractionError(
            "the injected budget meter refused this run",
            reason_code=(
                reason if isinstance(reason, str) and reason in _METER_REASONS
                else "budget_insufficient"
            ),
        ) from None


def _terminal_failure(exc: BaseException) -> tuple[str, int]:
    """Read the sanitized terminal identity from a provider failure.

    An undeclared or missing reason collapses to ``provider_response_unusable``
    rather than widening the released enum, and never to a message string.
    """
    reason = getattr(exc, "reason_code", None)
    if not isinstance(reason, str) or reason not in PROVIDER_ERROR_REASONS:
        reason = "provider_response_unusable"
    attempts = getattr(exc, "attempt_count", None)
    if not isinstance(attempts, int) or attempts < 1:
        attempts = 1
    return reason, attempts


def run_extraction_stage(
    *,
    run_root: str | Path,
    repo_root: str | Path,
    stage: str,
    company_id: str,
    observation_cutoff_date: str,
    passages: list[dict[str, Any]],
    document_publication_dates: dict[str, str],
    coverage_artifact: dict[str, str],
    source_snapshot_manifest: dict[str, str],
    code_commit: str,
    run_created_at: str,
    extraction_run_id: str,
    prediction_run_id: str,
    schema_root: str = "schemas",
    provider: object = None,
    provider_client_contract: object = _PIN_UNSET,
    governance_artifact_root: str | Path | None = None,
    live_call_authorization_pin: dict[str, str] | None = None,
    budget_meter: object = None,
    artifact_root: str | Path | None = None,
    # ADR-036 (E-R). A builder/runner argument, never a packet field: the packet
    # records the reference and digest, not the root they were read from. There
    # is no cwd search and no environment fallback.
    company_identity_root: str | Path | None = None,
    company_identity_pin: dict[str, str] | None = None,
    snapshot_a_pin: dict[str, str] | None = None,
    snapshot_b_pin: dict[str, str] | None = None,
    product_decision_set_pin: dict[str, str] | None = None,
    capability_decision_set_pin: dict[str, str] | None = None,
) -> ExtractionOutcome:
    """Resolve every deterministic input, then take one of the three routes."""
    # [A] The caller-supplied contract-pin channel is closed. Checked before the
    # route branch, so passing a pin fails identically on either route and the
    # rule has no exception.
    if provider_client_contract is not _PIN_UNSET:
        raise ExtractionError(
            "the provider-client contract is produced by the injected provider "
            "and written here; a caller-supplied pin is not accepted",
            reason_code="contract_pin_forbidden",
        )

    # [B] In memory only. Nothing is persisted yet.
    packet = build_extraction_input_packet(
        stage=stage,
        company_id=company_id,
        observation_cutoff_date=observation_cutoff_date,
        passages=passages,
        document_publication_dates=document_publication_dates,
        coverage_artifact=coverage_artifact,
        source_snapshot_manifest=source_snapshot_manifest,
        artifact_root=artifact_root,
        snapshot_a_pin=snapshot_a_pin,
        snapshot_b_pin=snapshot_b_pin,
        product_decision_set_pin=product_decision_set_pin,
        capability_decision_set_pin=capability_decision_set_pin,
        company_identity_root=company_identity_root,
        company_identity_pin=company_identity_pin,
    )
    root = Path(run_root)
    # Computed once, in memory: the request the meter inspects must carry the
    # same packet digest that is later persisted, and the same bytes object is
    # both hashed here and written at [O].
    packet_payload = packet_bytes(packet)
    packet_sha = sha256_bytes(packet_payload)

    if not packet["passages"]:
        # Non-run route. No provider, prompt, or schema preflight happens here:
        # no provider will be called, so requiring one would be theatre.
        _require_absent_run_root(root)
        root.mkdir(parents=True, exist_ok=False)
        _require_written_digest(
            write_artifact(root, PACKET_REFERENCE, packet_payload), packet_sha
        )
        record = build_non_run_record(
            extraction_run_id=extraction_run_id,
            stage=stage,
            company_id=company_id,
            observation_cutoff_date=observation_cutoff_date,
            code_commit=code_commit,
            run_created_at=run_created_at,
            input_packet_reference=PACKET_REFERENCE,
            input_packet_sha256=packet_sha,
            coverage_artifact_reference=coverage_artifact["reference"],
            coverage_artifact_sha256=coverage_artifact["sha256"],
            reason_code="zero_admissible_passages",
            filter_ledger=packet["filter_ledger"],
        )
        non_run_sha = write_artifact(root, NON_RUN_REFERENCE, record_bytes(record))
        return ExtractionOutcome(
            verdict="no_run",
            run_root=root,
            packet=packet,
            packet_sha256=packet_sha,
            artifacts={
                PACKET_REFERENCE: packet_sha,
                NON_RUN_REFERENCE: non_run_sha,
            },
        )

    # --- pre-run gate: [D] through [N], all side-effect free ------------------
    client = require_provider(provider)                          # [D]

    # [E] The governance chain, read from its own explicitly injected root.
    if live_call_authorization_pin is None or governance_artifact_root is None:
        raise ExtractionError(
            "a live-call authorization pin and an explicit governance artifact "
            "root are both required; there is no ambient, cwd, or environment "
            "fallback for either",
            reason_code="governance_root_required",
        )
    authorization = hydrate_pinned_artifact(
        governance_artifact_root,
        live_call_authorization_pin,
        what="live call authorization",
        unsafe_code="authorization_chain_broken",
        sha_code="authorization_chain_broken",
    )
    enablement_pin = {
        "reference": authorization.get("adapter_enablement_record_reference"),
        "sha256": authorization.get("adapter_enablement_record_sha256"),
    }
    enablement = hydrate_pinned_artifact(
        governance_artifact_root,
        enablement_pin,
        what="adapter enablement record",
        unsafe_code="authorization_chain_broken",
        sha_code="authorization_chain_broken",
    )
    qualification_pin = {
        "reference": enablement.get("adapter_qualification_record_reference"),
        "sha256": enablement.get("adapter_qualification_record_sha256"),
    }
    qualification = hydrate_pinned_artifact(
        governance_artifact_root,
        qualification_pin,
        what="adapter qualification record",
        unsafe_code="authorization_chain_broken",
        sha_code="authorization_chain_broken",
    )
    # The released stage-output schema digest is needed by the governance
    # semantics below. Resolving it here is a pure committed-file read, so the
    # zero-side-effect boundary is unaffected.
    schema_hash = resolve_stage_schema_hash(stage, schema_root)
    authorization = validate_governance_chain(
        authorization=authorization,
        enablement=enablement,
        qualification=qualification,
        authorization_pin=live_call_authorization_pin,
        enablement_pin=enablement_pin,
        qualification_pin=qualification_pin,
    )
    validate_governance_semantics(
        authorization=authorization,
        enablement=enablement,
        qualification=qualification,
        stage=stage,
        run_created_at=run_created_at,
        stage_output_schema_sha256=schema_hash,
    )
    validate_authorization_scope(
        authorization=authorization,
        stage=stage,
        company_id=company_id,
        observation_cutoff_date=observation_cutoff_date,
        corpus_scope=packet["corpus_scope"],
        run_created_at=run_created_at,
    )
    authorization_digest = live_call_authorization_pin["sha256"]
    cap = resolve_attempt_cap(authorization=authorization)

    # [F] The handshake, at the earliest possible point: digest plus the
    # authorization's own endpoint allowlist.
    _assert_run_permitted_with(
        client,
        authorization_digest,
        authorization.get("endpoint_allowlist"),
        enablement.get("endpoint_allowlist"),
    )

    # Everything after the handshake runs inside a revocation guard: the permit
    # outlives the client contract, qualification, prompt, meter, budget, run
    # root, and artifact writes, and any of those may refuse. Revoking on every
    # exit is what stops a refused run from leaving a spendable permit.
    try:
        return _run_authorized_stage(
            client=client,
            authorization=authorization,
            qualification=qualification,
            cap=cap,
            root=root,
            packet=packet,
            packet_payload=packet_payload,
            packet_sha=packet_sha,
            schema_hash=schema_hash,
            repo_root=repo_root,
            stage=stage,
            company_id=company_id,
            code_commit=code_commit,
            run_created_at=run_created_at,
            extraction_run_id=extraction_run_id,
            prediction_run_id=prediction_run_id,
            coverage_artifact=coverage_artifact,
            source_snapshot_manifest=source_snapshot_manifest,
            budget_meter=budget_meter,
        )
    finally:
        _revoke_run_permission(client)


def _run_authorized_stage(
    *,
    client: object,
    authorization: dict[str, Any],
    qualification: dict[str, Any],
    cap: int,
    root: Path,
    packet: dict[str, Any],
    packet_payload: bytes,
    packet_sha: str,
    schema_hash: str,
    repo_root: str | Path,
    stage: str,
    company_id: str,
    code_commit: str,
    run_created_at: str,
    extraction_run_id: str,
    prediction_run_id: str,
    coverage_artifact: dict[str, str],
    source_snapshot_manifest: dict[str, str],
    budget_meter: object,
) -> ExtractionOutcome:
    """The post-handshake region. Its caller guarantees permit revocation."""
    # [G] The declared client contract, and the authorization's byte identity.
    contract = _client_contract_of(client)
    contract_payload = canonical_json_bytes(contract)
    contract_sha_expected = sha256_bytes(contract_payload)
    validate_authorization_client_contract(
        authorization=authorization,
        client_contract_reference=CLIENT_CONTRACT_REFERENCE,
        client_contract_sha256=contract_sha_expected,
    )
    validate_qualification_execution_contract(
        qualification=qualification,
        client_contract=contract,
        client_contract_sha256=contract_sha_expected,
    )
    declared_max_output_tokens = contract["model_parameters"]["max_output_tokens"]

    # [H] Read-only prompt resolution, still in memory. The pass is an explicit
    # decision, not the by-product of indexing: a single-pass run executes the
    # first registered prompt only and records that it did.
    prompt_plan = single_pass_prompt_plan(stage)
    prompt = load_prompt(repo_root, prompt_plan["prompt_id"])
    prompt_payload = prompt["text"].encode("utf-8")

    # [H2] Materialize the contents. The authorized route needs a legal name, so
    # a @0.1.0 packet is refused here rather than sending a literal placeholder.
    if packet["contract"] != PACKET_CONTRACT_REQUIRING_IDENTITY:
        raise ExtractionError(
            "the authorized route requires "
            f"{PACKET_CONTRACT_REQUIRING_IDENTITY}; a packet without a hydrated "
            "company identity cannot render the provider contents",
            reason_code="company_identity_pin_required",
        )
    rendered_contents = render_provider_contents(
        stage=stage, prompt_text=prompt["text"], packet=packet
    )
    contents_payload = rendered_contents.encode("utf-8")
    contents_sha_expected = sha256_bytes(contents_payload)

    # [I] The one canonical request. The meter and the provider see this object,
    # and rendered_contents is its sole provider-input authority.
    provider_request = ProviderRequest(
        stage=stage,
        rendered_contents=rendered_contents,
        rendered_contents_sha256=contents_sha_expected,
        prompt_sha256=prompt["prompt_hash"],
        input_packet_sha256=packet_sha,
    )

    # [J] The budget meter, and the identity the authorization names.
    meter = require_budget_meter(budget_meter)
    validate_budget_meter_identity(
        authorization=authorization, meter_identity=_meter_identity_of(meter)
    )

    # [K]-[L] Arithmetic limits are already enforced by resolve_attempt_cap; the
    # meter owns input tokens, estimated cost, and elapsed wall clock.
    _assert_within_budget(
        meter,
        request=provider_request,
        max_output_tokens=declared_max_output_tokens,
        budget=dict(authorization),
    )

    authorization_payload = canonical_json_bytes(authorization)
    _require_absent_run_root(root)

    # [O] First filesystem effect of this route.
    root.mkdir(parents=True, exist_ok=False)
    _require_written_digest(
        write_artifact(root, PACKET_REFERENCE, packet_payload), packet_sha
    )
    contents_sha = write_artifact(root, CONTENTS_REFERENCE, contents_payload)
    _require_written_digest(contents_sha, contents_sha_expected)
    prompt_sha = write_artifact(root, PROMPT_REFERENCE, prompt_payload)
    contract_sha = write_artifact(root, CLIENT_CONTRACT_REFERENCE, contract_payload)
    _require_written_digest(contract_sha, contract_sha_expected)
    authorization_sha = write_artifact(
        root, AUTHORIZATION_REFERENCE, authorization_payload
    )

    # [P] The provider sees the same request object the meter inspected.
    try:
        response = client.complete(provider_request)
    except Exception as exc:  # noqa: BLE001 - the provider seam is total
        reason, attempts = _terminal_failure(exc)
        if attempts > cap:
            # The provider reported more attempts than the budget authorized.
            # Record the budget violation, not the provider's own reason.
            reason, attempts = "provider_response_unusable", cap
        run_record = build_extraction_run(
            run_id=extraction_run_id,
            stage=stage,
            started_at=run_created_at,
            completed_at=run_created_at,
            status="errored",
            code_commit=code_commit,
            schema_hash=schema_hash,
            prompt_hash=prompt["prompt_hash"],
            source_manifest_hash=source_snapshot_manifest["sha256"],
            error_count=attempts,
        )
        run_sha = write_artifact(root, EXTRACTION_RUN_REFERENCE, record_bytes(run_record))
        error_record = build_provider_error_record(
            extraction_run_id=extraction_run_id,
            stage=stage,
            company_id=company_id,
            code_commit=code_commit,
            input_packet_reference=PACKET_REFERENCE,
            input_packet_sha256=packet_sha,
            resolved_prompt_reference=PROMPT_REFERENCE,
            resolved_prompt_sha256=prompt_sha,
            provider_client_contract_reference=CLIENT_CONTRACT_REFERENCE,
            provider_client_contract_sha256=contract_sha,
            extraction_run_reference=EXTRACTION_RUN_REFERENCE,
            extraction_run_sha256=run_sha,
            reason_code=reason,
            attempt_count=attempts,
        )
        write_artifact(root, PROVIDER_ERROR_REFERENCE, record_bytes(error_record))
        # Evidence first, then a sanitized failure. No raw prediction, envelope,
        # prediction manifest, or harness run exists on this route.
        raise ExtractionError(
            "every provider attempt failed; the terminal cause is recorded in "
            "the provider-error record",
            reason_code=reason,
        ) from None

    raw_sha = write_raw_prediction(root, RAW_REFERENCE, response.raw_bytes)

    run_record = build_extraction_run(
        run_id=extraction_run_id,
        stage=stage,
        started_at=run_created_at,
        completed_at=run_created_at,
        status="completed",
        code_commit=code_commit,
        schema_hash=schema_hash,
        prompt_hash=prompt["prompt_hash"],
        source_manifest_hash=source_snapshot_manifest["sha256"],
        model_provider=response.model_provider,
        model_name=response.model_name,
        model_parameters=response.model_parameters,
    )
    run_sha = write_artifact(root, EXTRACTION_RUN_REFERENCE, record_bytes(run_record))

    envelope = build_prediction_envelope(
        prediction_record_id=f"{prediction_run_id}-0",
        stage=stage,
        source_references=[
            RAW_REFERENCE,
            PROMPT_REFERENCE,
            CLIENT_CONTRACT_REFERENCE,
            AUTHORIZATION_REFERENCE,
        ],
        # ADR-036 (E-R). prompt_model_metadata is an open dict on a released
        # model and the envelope is hash-bound through envelopes_sha256, so the
        # renderer version, the rendered digest and the single-pass record are
        # auditable in the run artifact chain rather than only in an ADR.
        prompt_model_metadata={
            **response.prompt_model_metadata,
            "contents_renderer_version": RENDERER_VERSION,
            "rendered_contents_reference": CONTENTS_REFERENCE,
            "rendered_contents_sha256": contents_sha,
            **prompt_plan,
        },
        input_packet_hash=packet_sha,
        prediction_run_manifest_reference=PREDICTION_MANIFEST_REFERENCE,
        input_packet_reference=PACKET_REFERENCE,
    )
    envelopes_bytes = canonical_jsonl_bytes([envelope])
    envelopes_sha = write_artifact(root, ENVELOPES_REFERENCE, envelopes_bytes)

    manifest = build_prediction_artifact_manifest(
        prediction_run_id=prediction_run_id,
        envelopes_reference=ENVELOPES_REFERENCE,
        envelopes_sha256=envelopes_sha,
        record_count=1,
        source_artifacts={
            "raw_prediction": {"reference": RAW_REFERENCE, "sha256": raw_sha},
            "extraction_input_packet": {"reference": PACKET_REFERENCE, "sha256": packet_sha},
            "rendered_provider_contents": {
                "reference": CONTENTS_REFERENCE,
                "sha256": contents_sha,
            },
            "coverage_artifact": dict(coverage_artifact),
            "resolved_prompt": {"reference": PROMPT_REFERENCE, "sha256": prompt_sha},
            "provider_client_contract": {
                "reference": CLIENT_CONTRACT_REFERENCE,
                "sha256": contract_sha,
            },
            "live_call_authorization": {
                "reference": AUTHORIZATION_REFERENCE,
                "sha256": authorization_sha,
            },
            "extraction_run": {"reference": EXTRACTION_RUN_REFERENCE, "sha256": run_sha},
        },
    )
    manifest_sha = write_artifact(
        root, PREDICTION_MANIFEST_REFERENCE, manifest_bytes(manifest)
    )
    return ExtractionOutcome(
        verdict="provider_run_complete",
        run_root=root,
        packet=packet,
        packet_sha256=packet_sha,
        artifacts={
            PACKET_REFERENCE: packet_sha,
            CONTENTS_REFERENCE: contents_sha,
            PROMPT_REFERENCE: prompt_sha,
            CLIENT_CONTRACT_REFERENCE: contract_sha,
            AUTHORIZATION_REFERENCE: authorization_sha,
            RAW_REFERENCE: raw_sha,
            EXTRACTION_RUN_REFERENCE: run_sha,
            ENVELOPES_REFERENCE: envelopes_sha,
            PREDICTION_MANIFEST_REFERENCE: manifest_sha,
        },
    )
