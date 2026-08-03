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
    BUDGET_POLICY_VERSION,
    PACKET_CONTRACT_REQUIRING_IDENTITY,
    PROVIDER_ERROR_REASONS,
    build_extraction_run,
    build_non_run_record,
    build_provider_error_record,
    record_bytes,
    resolve_attempt_cap,
    resolve_attempt_cap_v2,
    resolve_stage_schema_hash,
    validate_authorization_client_contract,
    validate_authorization_scope,
    validate_budget_meter_identity,
    validate_governance_chain,
    validate_governance_chain_v2,
    validate_governance_semantics,
    validate_provider_client_contract,
    validate_qualification_execution_contract,
)
from .count_reconciliation import (
    parse_input_token_count,
    reconcile_count,
    reconcile_usage,
    reserve_cost_microdollars,
)
from .execution_outcome import (
    COUNT_RAW_REFERENCE,
    EXECUTION_OUTCOME_REFERENCE,
    build_execution_outcome,
    generate_attempt_reference,
    validate_execution_outcome,
)
from .prediction_manifest import (
    build_prediction_artifact_manifest,
    build_prediction_artifact_manifest_v2,
    manifest_bytes,
)
from .budget_session import build_budget_session
from .contents_renderer import RENDERER_VERSION, render_provider_contents
from .prompt_qualification import validate_prompt_qualification
from .prompts import load_prompt, single_pass_prompt_plan
from .provider_adapter import (
    PROVIDER_PROTOCOL_VERSION_V8,
    CaptureRecord,
    CaptureSinkError,
    ProviderRequest,
    provider_request_digest,
    require_budget_meter,
    require_budget_session,
    require_provider,
    require_provider_v8,
)
from .raw_artifacts import (
    build_prediction_envelope,
    canonical_json_bytes,
    canonical_jsonl_bytes,
    sha256_bytes,
    write_artifact,
    write_raw_prediction,
)

__all__ = [
    "COUNT_RAW_REFERENCE",
    "EXECUTION_OUTCOME_REFERENCE",
    "ExtractionOutcome",
    "build_capture_sink",
    "run_extraction_stage",
    "run_extraction_stage_v2",
]

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

# ADR-043 (E-M). The count operation's label is a fixed code-path constant here
# too: the sink routes on it, and a caller-supplied label would let one
# operation's body be filed under the other's name.
COUNT_OPERATION_LABEL = "count_tokens"

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

    # --- [R] ADR-045 (G2b): the v1 provider route is retired ------------------
    #
    # Placed here and nowhere else. Above this line the packet has already been
    # built and the non-run branch has already returned, so the two routes that
    # do not reach a provider keep their exact behaviour: the caller-supplied
    # contract-pin refusal and every packet-build refusal still produce zero
    # artifacts, and a run with no admissible passage still creates its run root
    # and writes exactly the packet and the non-run record. Below this line lie
    # `require_provider`, the governance walk, the permit handshake, the meter,
    # `_require_absent_run_root` and `mkdir` -- none of which now execute.
    #
    # v1 validates the three released rings but has no prompt-qualification
    # binding (ADR-044 placed that on the v2 route) and no countTokens
    # measurement. A route that walks a governance chain and still cannot say
    # which prompt was qualified is not a lesser route; it is a bypass, and it
    # looks legitimate from the outside. A runbook cannot close it, because a
    # runbook is a human document and this is a code path.
    #
    # One ordering consequence is deliberate and recorded: on this branch a run
    # root that already exists now yields `v1_live_route_retired` rather than
    # `run_root_exists`, because `_require_absent_run_root` sits far below, past
    # the provider seam and the permit handshake. The existing root is left
    # exactly as it was found -- this refusal writes nothing and removes nothing.
    raise ExtractionError(
        "the v1 single-operation live route is retired: a provider-backed run "
        "must go through run_extraction_stage_v2, which binds the SPEC-024 "
        "prompt qualification and measures the input before it generates; "
        "there is no v1 bypass",
        reason_code="v1_live_route_retired",
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
    #
    # ADR-047 gave the validator a required `expected_budget_policy_version`
    # parameter. This call is unreachable -- ADR-045 retired the v1 provider route
    # above it -- and passing the constant changes nothing about v1's behaviour.
    # It is passed anyway so that removing the unreachable block later surfaces as
    # a deletion rather than as a TypeError from a call nobody could execute.
    meter = require_budget_meter(budget_meter)
    validate_budget_meter_identity(
        authorization=authorization,
        meter_identity=_meter_identity_of(meter),
        expected_budget_policy_version=BUDGET_POLICY_VERSION,
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


# --- ADR-043 (E-M): two-operation measurement ---------------------------------
#
# The phase order is the whole increment, so it is written once, here:
#
#   F0 static/governance refusal   -- pre-mkdir, zero artifacts, no outcome
#   F1 prepared inputs             -- five write-once artifacts
#   F2 countTokens                 -- the first network call; its body is
#                                     persisted and hash-verified immediately
#   F3 pure derivation             -- parse, then reconcile against the SDK's
#                                     own witness; no network, no clock
#   F4 admission                   -- the budget decides on a MEASURED count
#   F5 generateContent             -- and only now
#
# Nothing derived from a response influences the budget or the next request
# before that response's bytes are durable. What the SDK does internally --
# parsing the body, classifying its own errors -- happens before our persistence
# and is outside this guarantee; the guarantee covers *our* derivations and
# *our* subsequent sends.


def build_capture_sink(root: Path, *, records: list[CaptureRecord] | None = None) -> Any:
    """A runner-owned, write-once persistence callback for one attempt.

    ``records`` is the runner's own ledger. The sink appends every record it
    produces -- including the one describing its own failure -- because the
    connector raises through it and never gets to hand anything back. Without
    this, a persistence failure would take the evidence of the attempts before it
    along with it, and the terminal chain would show a generation route with no
    generation in it.

    Called by the connector after every attempt and **before** the next send.
    That ordering is what makes "a persistence failure permits no further send"
    enforceable at all: a sink that ran after the retry loop would only ever
    report failures the loop had already sent past.

    A zero-length body is never written. ``sha256(b"")`` is a perfectly valid
    digest for content that never existed, and a zero-byte artifact carrying it
    would be indistinguishable from a real one.
    """

    def sink(
        *,
        operation_label: str,
        attempt_ordinal: int,
        raw_bytes: bytes | None,
        send_outcome: str,
        sdk_call_outcome: str,
        provider_reason_code: str | None,
    ) -> CaptureRecord:
        if raw_bytes is None:
            disposition = "no_body_captured"
        elif not raw_bytes:
            disposition = "empty_entity_body_not_persisted"
        else:
            disposition = "raw_persisted"
        if disposition != "raw_persisted":
            record = CaptureRecord(
                operation_label=operation_label,
                attempt_ordinal=attempt_ordinal,
                send_outcome=send_outcome,
                sdk_call_outcome=sdk_call_outcome,
                capture_disposition=disposition,
                provider_reason_code=provider_reason_code,
            )
            if records is not None:
                records.append(record)
            return record
        if operation_label == COUNT_OPERATION_LABEL:
            reference = COUNT_RAW_REFERENCE
        elif sdk_call_outcome == "returned":
            # The one deterministic fact known at sink time is whether this
            # attempt's SDK call returned. With the SDK's own retry disabled a
            # returned call is necessarily the terminal one, so it -- and only
            # it -- owns the raw-prediction path. "Returned" is not the same as
            # "usable": reconciliation may still refuse it later.
            reference = RAW_REFERENCE
        else:
            reference = generate_attempt_reference(attempt_ordinal)
        try:
            digest = write_artifact(root, reference, bytes(raw_bytes))
        except ExtractionError as exc:
            reason = exc.reason_code if exc.reason_code == "destination_exists" else "write_error"
            if records is not None:
                records.append(
                    CaptureRecord(
                        operation_label=operation_label,
                        attempt_ordinal=attempt_ordinal,
                        send_outcome=send_outcome,
                        sdk_call_outcome=sdk_call_outcome,
                        capture_disposition="body_captured_persistence_failed",
                        provider_reason_code=provider_reason_code,
                        persistence_reason_code=reason,
                    )
                )
            raise CaptureSinkError(
                operation_label=operation_label,
                attempt_ordinal=attempt_ordinal,
                persistence_reason_code=reason,
                provider_reason_code=provider_reason_code,
            ) from None
        record = CaptureRecord(
            operation_label=operation_label,
            attempt_ordinal=attempt_ordinal,
            send_outcome=send_outcome,
            sdk_call_outcome=sdk_call_outcome,
            capture_disposition="raw_persisted",
            raw_reference=reference,
            raw_sha256=digest,
            byte_count=len(raw_bytes),
            provider_reason_code=provider_reason_code,
        )
        if records is not None:
            records.append(record)
        return record

    return sink


def _run_two_operation_measurement(
    *,
    root: Path,
    provider: Any,
    session: Any,
    request: ProviderRequest,
    authorization: dict[str, Any],
    max_output_tokens: int,
    request_digest: str,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Walk F2 through F5 and return the facts the outcome record will carry.

    Returns rather than publishes: every route's terminal chain is written by the
    caller, so this function has no way to leave a half-written record behind.

    ``trace`` accumulates what has happened so far -- the phase reached and every
    capture record -- so that when this raises, the caller can still publish a
    truthful terminal chain. Without it a failure would take its own evidence
    with it.

    **Private (ADR-045, G2b).** This walks F2 through F5 with no governance of
    its own: it hydrates nothing, validates no chain, binds no prompt
    qualification and asks for no permit. The ``authorization`` argument is a
    caller-supplied mapping read only for the attempt cap. It was exported, and
    an exported function that sends while validating nothing is a second public
    route around the gate ADR-044 installed, so it is no longer part of
    ``__all__`` and only :func:`_run_two_operation_stage` calls it in production.

    The underscore is a boundary, not an enforcement: nothing stops an
    in-process caller from reaching for it by name. What actually refuses is the
    connector, whose ``count_tokens`` and ``complete_v8`` spend an
    operation-labelled permit that only ``assert_run_permitted`` grants.
    """
    state = trace if trace is not None else {}
    state.setdefault("generate_records", ())
    # ADR-047. The same shape gate the canonical route applies at F0, applied
    # here too: this helper is private but it still accepts a caller-supplied
    # session, and the nonce comparison below is meaningless against an object
    # whose nonce is a method or a non-digest. No exemption for the private seam.
    session = require_budget_session(session)
    cap = resolve_attempt_cap_v2(authorization=authorization)
    state["generate_attempt_cap"] = cap
    # The runner's own ledger of what it persisted, kept where the failure paths
    # can still read it.
    ledger: list[CaptureRecord] = []
    state["sink_records"] = ledger
    sink = build_capture_sink(root, records=ledger)

    # F2 -- the first network call.
    state["phase"] = "count_send"
    count_record, witness = provider.count_tokens(request, sink=sink)
    state["count_record"] = count_record
    state["sdk_witness_total_tokens"] = witness
    if count_record.capture_disposition != "raw_persisted":
        raise ExtractionError(
            "the count response was not persisted, so nothing may be derived from it",
            reason_code="provider_response_unusable",
        )

    # F3 -- pure, and only from bytes that are already on disk and verified.
    state["phase"] = "count_verify"
    persisted = (root / count_record.raw_reference).read_bytes()
    if sha256_bytes(persisted) != count_record.raw_sha256:
        raise ExtractionError(
            "the persisted count response no longer matches its digest",
            reason_code="write_error",
        )
    state["phase"] = "derive"
    parsed = parse_input_token_count(persisted)
    measured = reconcile_count(parsed=parsed, sdk_witness=witness)
    state["measured_input_tokens"] = measured

    # F4 -- the budget decides on the measured count, never on an estimate.
    state["phase"] = "admission"
    reserved = reserve_cost_microdollars(
        measured_input_tokens=measured,
        max_output_tokens=max_output_tokens,
        generate_attempt_cap=cap,
    )
    state["reserved_cost_microdollars"] = reserved
    # Enforced here as well as by the meter. The meter is injected; a fail-closed
    # ceiling cannot depend on an injected object choosing to apply it.
    if measured > authorization["budget_max_input_tokens"]:
        raise ExtractionError(
            "the measured input exceeds the authorized input-token budget",
            reason_code="budget_input_tokens_exceeded",
        )
    if reserved > authorization["budget_max_estimated_cost_micros"]:
        raise ExtractionError(
            "the reserve for the authorized attempt cap exceeds the estimated-cost budget",
            reason_code="budget_estimated_cost_exceeded",
        )
    admission = session.admit(
        measured_input_tokens=measured,
        reserved_cost_microdollars=reserved,
        provider_request_digest=request_digest,
    )
    if admission.generate_attempt_cap > cap:
        raise ExtractionError(
            "the budget session admitted more generation attempts than the "
            "authorization allows",
            reason_code="budget_insufficient",
        )
    if admission.reserved_cost_microdollars != reserved:
        raise ExtractionError(
            "the admission reserves a different amount than the run computed",
            reason_code="budget_estimated_cost_exceeded",
        )
    if admission.provider_request_digest != request_digest:
        raise ExtractionError(
            "the admission was minted for a different provider request",
            reason_code="budget_admission_invalid",
        )
    if admission.session_nonce != session.session_nonce:
        raise ExtractionError(
            "the admission was minted by a different budget session",
            reason_code="budget_admission_invalid",
        )

    # F5 -- and only now.
    state["phase"] = "generate"
    response, generate_records = provider.complete_v8(
        request, admission=admission, sink=sink
    )
    state["generate_records"] = tuple(generate_records)
    state["phase"] = "generated"
    return {
        "generate_attempt_cap": cap,
        "count_record": count_record,
        "measured_input_tokens": measured,
        "sdk_witness_total_tokens": witness,
        "reserved_cost_microdollars": reserved,
        "response": response,
        "generate_records": tuple(generate_records),
    }


def _classify_terminal(exc: BaseException, trace: dict[str, Any]) -> dict[str, Any]:
    """Map a failure and the trace it left behind onto one terminal route.

    The route is never read off a single field. A persistence failure and a
    provider failure can both be true of the same attempt, and the phase the run
    reached is what separates a count-side failure from a generation-side one.
    """
    generate_records = trace.get("generate_records") or ()
    phase = trace.get("phase")
    if isinstance(exc, CaptureSinkError):
        if exc.operation_label == COUNT_OPERATION_LABEL:
            return {
                "route_family": "pre_generation_invalid",
                "terminal_reason": "persistence_failure",
                "loop_termination_cause": "persistence_failure",
                "status": "invalid",
                "error_count": 0,
                "provider_error": None,
            }
        if exc.provider_reason_code is not None:
            # The provider failed too. Its reason is published in the released
            # error record; the persistence reason stays in the outcome.
            return {
                "route_family": "generation_provider_error",
                "terminal_reason": "persistence_failure",
                "loop_termination_cause": "persistence_failure",
                "status": "errored",
                "error_count": exc.attempt_ordinal,
                "provider_error": exc.provider_reason_code,
            }
        return {
            "route_family": "generation_persistence_failed",
            "terminal_reason": "persistence_failure",
            "loop_termination_cause": "persistence_failure",
            "status": "invalid",
            "error_count": max(exc.attempt_ordinal - 1, 0),
            "provider_error": None,
        }
    reason = getattr(exc, "reason_code", None)
    if reason in ("count_parse_failed", "count_reconciliation_mismatch"):
        return {
            "route_family": "pre_generation_invalid",
            "terminal_reason": reason,
            "loop_termination_cause": "retry_not_permitted",
            "status": "invalid",
            "error_count": 0,
            "provider_error": None,
        }
    if reason in _METER_REASONS or reason in (
        "budget_insufficient",
        # An admission that does not match what the run derived is an admission
        # failure, not a provider failure: no send has happened, and attributing
        # it to the provider would put a reason in the released error record for
        # something the provider never did.
        "budget_admission_invalid",
        # Reachable post-F1: the canonical route calls the measurement helper
        # after mkdir, and the helper's own shape gate can raise there. Left in
        # the budget branch rather than the provider one, because a malformed
        # session is not something the provider did.
        "budget_meter_protocol_invalid",
    ):
        return {
            "route_family": "pre_generation_invalid",
            "terminal_reason": "budget_termination",
            "loop_termination_cause": "retry_not_permitted",
            "status": "invalid",
            "error_count": 0,
            "provider_error": None,
        }
    provider_reason = reason if reason in PROVIDER_ERROR_REASONS else "provider_response_unusable"
    if phase == "generate" or generate_records:
        attempts = getattr(exc, "attempt_count", None)
        if not isinstance(attempts, int) or attempts < 1:
            attempts = max(len(generate_records), 1)
        return {
            "route_family": "generation_provider_error",
            "terminal_reason": "provider_call_failed",
            "loop_termination_cause": "non_retryable_provider_failure",
            "status": "errored",
            "error_count": attempts,
            "provider_error": provider_reason,
        }
    return {
        "route_family": "count_provider_error",
        "terminal_reason": "provider_call_failed",
        "loop_termination_cause": "retry_not_permitted",
        "status": "errored",
        "error_count": 1,
        "provider_error": provider_reason,
    }


def _attempt_entry(record: CaptureRecord) -> dict[str, Any]:
    """One capture record as the outcome's schema wants it: absent, not null."""
    entry: dict[str, Any] = {
        "operation_label": record.operation_label,
        "attempt_ordinal": record.attempt_ordinal,
        "send_outcome": record.send_outcome,
        "sdk_call_outcome": record.sdk_call_outcome,
        "capture_disposition": record.capture_disposition,
    }
    if record.capture_disposition == "raw_persisted":
        entry["raw_reference"] = record.raw_reference
        entry["raw_sha256"] = record.raw_sha256
        entry["byte_count"] = record.byte_count
    if record.provider_reason_code is not None:
        entry["provider_reason_code"] = record.provider_reason_code
    if record.persistence_reason_code is not None:
        entry["persistence_reason_code"] = record.persistence_reason_code
    return entry


def _publish_execution_outcome(
    *,
    root: Path,
    schema_root: str,
    route: dict[str, Any],
    trace: dict[str, Any],
    run_root_pins: dict[str, dict[str, str]],
    evidence_binding: dict[str, str],
    provider_error_pin: dict[str, str] | None,
    measurement: dict[str, Any] | None,
) -> str:
    """Build, validate against the committed contract, then write once.

    Validation precedes the write on purpose: a run root must never hold an
    outcome that its own schema rejects, because that record is the classifier
    root on every route that publishes no manifest.
    """
    ledger = trace.get("sink_records") or []
    count_record = trace.get("count_record") or next(
        (r for r in ledger if r.operation_label == COUNT_OPERATION_LABEL), None
    )
    generate_records = trace.get("generate_records") or tuple(
        r for r in ledger if r.operation_label != COUNT_OPERATION_LABEL
    )
    synthesized: tuple[dict[str, Any], ...] = ()
    if not generate_records and route["route_family"] in (
        "generation_provider_error",
        "generation_persistence_failed",
    ):
        # The generation phase failed before its first send produced a record --
        # a factory or credential failure, say. The attempt is still an observed
        # fact and the outcome has to describe it; leaving the list empty would
        # publish a generation route that shows no generation.
        synthesized = (
            {
                "operation_label": "generate_content",
                "attempt_ordinal": 1,
                "send_outcome": "not_sent_client_unavailable",
                "sdk_call_outcome": "not_invoked",
                "capture_disposition": "no_body_captured",
                "provider_reason_code": route["provider_error"] or "provider_response_unusable",
            },
        )
    external_requests = sum(
        0 if record.send_outcome.startswith("not_sent_") else 1
        for record in ((count_record,) if count_record else ()) + tuple(generate_records)
    )
    optional: dict[str, Any] = {}
    if count_record is not None and count_record.capture_disposition == "raw_persisted":
        optional["count_raw_pin"] = {
            "reference": count_record.raw_reference,
            "sha256": count_record.raw_sha256,
        }
    if route["route_family"] in ("completed", "post_generation_invalid") and generate_records:
        terminal = generate_records[-1]
        optional["raw_prediction_pin"] = {
            "reference": terminal.raw_reference,
            "sha256": terminal.raw_sha256,
        }
    if provider_error_pin is not None:
        optional["provider_error_record_pin"] = provider_error_pin
    if measurement is not None:
        optional["measurement_status"] = measurement["measurement_status"]
        if "actual_cost_microdollars" in measurement:
            optional["actual_cost_microdollars"] = measurement["actual_cost_microdollars"]
    for name, key in (
        ("reserved_cost_microdollars", "reserved_cost_microdollars"),
        ("measured_input_tokens", "measured_input_tokens"),
        ("sdk_witness_total_tokens", "sdk_witness_total_tokens"),
    ):
        if trace.get(key) is not None:
            optional[name] = trace[key]
    if trace.get("measured_input_tokens") is not None:
        optional["thinking_budget"] = 0
    record = build_execution_outcome(
        route_family=route["route_family"],
        terminal_reason=route["terminal_reason"],
        loop_termination_cause=route["loop_termination_cause"],
        external_request_count=external_requests,
        error_count=route["error_count"],
        count_operation=_attempt_entry(count_record) if count_record else _ABSENT_COUNT_ATTEMPT,
        generate_attempts=(
            list(synthesized)
            if synthesized
            else [_attempt_entry(record) for record in generate_records]
        ),
        run_root_pins=run_root_pins,
        evidence_binding=evidence_binding,
        **optional,
    )
    validate_execution_outcome(record, schema_root=schema_root)
    return write_artifact(root, EXECUTION_OUTCOME_REFERENCE, record_bytes(record))


# A count operation that never produced a record at all -- the connector refused
# before its first send. The outcome still has to describe it.
_ABSENT_COUNT_ATTEMPT: dict[str, Any] = {
    "operation_label": COUNT_OPERATION_LABEL,
    "attempt_ordinal": 1,
    "send_outcome": "not_sent_client_unavailable",
    "sdk_call_outcome": "not_invoked",
    "capture_disposition": "no_body_captured",
    "provider_reason_code": "provider_response_unusable",
}


def run_extraction_stage_v2(
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
    evidence_binding: dict[str, str],
    schema_root: str = "schemas",
    provider: object = None,
    governance_artifact_root: str | Path | None = None,
    live_call_authorization_pin: dict[str, str] | None = None,
    artifact_root: str | Path | None = None,
    company_identity_root: str | Path | None = None,
    company_identity_pin: dict[str, str] | None = None,
    snapshot_a_pin: dict[str, str] | None = None,
    snapshot_b_pin: dict[str, str] | None = None,
    product_decision_set_pin: dict[str, str] | None = None,
    capability_decision_set_pin: dict[str, str] | None = None,
) -> ExtractionOutcome:
    """The E-M production entry point: one measured, two-operation run.

    The phase order is the increment, and it is visible in the shape of this
    function. F0 resolves every deterministic input and the whole governance
    chain while the run root still does not exist, so a refusal there costs zero
    artifacts. F1 writes the five prepared inputs. F2 makes the first network
    call. F3 derives from bytes that are already on disk and verified. F4 admits
    on the measured number. F5 generates.

    Every route that reaches F1 publishes a terminal chain, and
    ``extraction_execution_outcome@0.1.0`` is always the last record in it --
    validated against its committed contract before it is written, because on
    every route without a manifest it *is* the classifier root.
    """
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
    packet_payload = packet_bytes(packet)
    packet_sha = sha256_bytes(packet_payload)

    if not packet["passages"]:
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
            artifacts={PACKET_REFERENCE: packet_sha, NON_RUN_REFERENCE: non_run_sha},
        )

    # --- F0: nothing exists on disk yet --------------------------------------
    client = require_provider_v8(provider)
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
    # ADR-044. The fourth artifact, hydrated from the same governance root under
    # the same containment and digest discipline as the three rings above. The
    # enablement has always been required to name it; until now nothing opened
    # what it named. The equality checks that bind it to the resolved prompt and
    # the executing client contract need values that do not exist yet, so they
    # run later, in the post-handshake region.
    prompt_qualification_pin = {
        "reference": enablement.get("prompt_qualification_reference"),
        "sha256": enablement.get("prompt_qualification_sha256"),
    }
    prompt_qualification = hydrate_pinned_artifact(
        governance_artifact_root,
        prompt_qualification_pin,
        what="prompt qualification record",
        unsafe_code="authorization_chain_broken",
        sha_code="authorization_chain_broken",
    )
    schema_hash = resolve_stage_schema_hash(stage, schema_root)
    authorization = validate_governance_chain_v2(
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
    # The two-operation budget, refused here rather than after the first send.
    generate_attempt_cap = resolve_attempt_cap_v2(authorization=authorization)

    # --- ADR-047 (G3-2): the canonical session, built here and injected nowhere -
    #
    # The runner constructs its own session from values it has already validated,
    # so there is no public seam through which a different one could arrive. The
    # identity checked below therefore comes from code, not from the artifact it
    # is being checked against.
    #
    # Placed before `_assert_run_permitted_with` on purpose: every refusal on
    # these three lines happens with no permit granted, no run root, no artifact
    # and no provider call, so there is nothing to revoke and nothing to clean up.
    budget_session = build_budget_session(
        authorization_sha256=live_call_authorization_pin["sha256"],
        extraction_run_id=extraction_run_id,
        generate_attempt_cap=generate_attempt_cap,
    )
    require_budget_session(budget_session)
    validate_budget_meter_identity(
        authorization=authorization,
        meter_identity=_meter_identity_of(budget_session),
        expected_budget_policy_version=BUDGET_POLICY_VERSION,
    )
    _assert_run_permitted_with(
        client,
        live_call_authorization_pin["sha256"],
        authorization.get("endpoint_allowlist"),
        enablement.get("endpoint_allowlist"),
    )
    try:
        return _run_two_operation_stage(
            client=client,
            session=budget_session,
            authorization=authorization,
            enablement=enablement,
            qualification=qualification,
            prompt_qualification=prompt_qualification,
            root=root,
            packet=packet,
            packet_payload=packet_payload,
            packet_sha=packet_sha,
            schema_hash=schema_hash,
            schema_root=schema_root,
            repo_root=repo_root,
            stage=stage,
            company_id=company_id,
            code_commit=code_commit,
            run_created_at=run_created_at,
            extraction_run_id=extraction_run_id,
            prediction_run_id=prediction_run_id,
            coverage_artifact=coverage_artifact,
            source_snapshot_manifest=source_snapshot_manifest,
            evidence_binding=evidence_binding,
        )
    finally:
        _revoke_run_permission(client)


def _run_two_operation_stage(
    *,
    client: object,
    session: object,
    authorization: dict[str, Any],
    enablement: dict[str, Any],
    qualification: dict[str, Any],
    prompt_qualification: dict[str, Any],
    root: Path,
    packet: dict[str, Any],
    packet_payload: bytes,
    packet_sha: str,
    schema_hash: str,
    schema_root: str,
    repo_root: str | Path,
    stage: str,
    company_id: str,
    code_commit: str,
    run_created_at: str,
    extraction_run_id: str,
    prediction_run_id: str,
    coverage_artifact: dict[str, str],
    source_snapshot_manifest: dict[str, str],
    evidence_binding: dict[str, str],
) -> ExtractionOutcome:
    """The post-handshake region. Its caller guarantees permit revocation."""
    contract = _client_contract_of_v2(client)
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

    prompt_plan = single_pass_prompt_plan(stage)
    prompt = load_prompt(repo_root, prompt_plan["prompt_id"])
    prompt_payload = prompt["text"].encode("utf-8")
    # ADR-044. Placed here because both operands finally exist: the client
    # contract has been canonicalized, hashed and accepted by the authorization
    # and the adapter qualification just above, and the frozen prompt has just
    # been resolved. Placed *no later* than here because everything after it
    # spends something -- the meter, the run root, the network. A refusal on this
    # line therefore precedes the first filesystem effect and leaves no artifact,
    # and it is raised inside the caller's try/finally, so the run permit is
    # revoked on this route exactly as on every other terminal one.
    validate_prompt_qualification(
        record=prompt_qualification,
        enablement=enablement,
        authorization=authorization,
        qualification=qualification,
        prompt=prompt,
        prompt_plan=prompt_plan,
        stage=stage,
        stage_output_schema_sha256=schema_hash,
        client_contract_sha256=contract_sha_expected,
        code_commit=code_commit,
        run_created_at=run_created_at,
        repo_root=repo_root,
    )
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
    provider_request = ProviderRequest(
        stage=stage,
        rendered_contents=rendered_contents,
        rendered_contents_sha256=contents_sha_expected,
        prompt_sha256=prompt["prompt_hash"],
        input_packet_sha256=packet_sha,
    )
    # Derived only now: the client contract has been canonicalized, hashed, and
    # verified against both the authorization and the qualification above, so the
    # digest binds an identity the governance chain has already accepted.
    request_digest = provider_request_digest(
        provider_request,
        provider_client_contract_sha256=contract_sha_expected,
        protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
    )
    # ADR-047. The meter identity and the budget policy version were checked at
    # F0, before the permit handshake, against a session this runner built
    # itself. Repeating either here would be a second code path for one rule, and
    # the earlier one is strictly better placed: it refuses before a permit
    # exists to revoke.
    authorization_payload = canonical_json_bytes(authorization)
    _require_absent_run_root(root)

    # --- F1: the first filesystem effect -------------------------------------
    root.mkdir(parents=True, exist_ok=False)
    _require_written_digest(
        write_artifact(root, PACKET_REFERENCE, packet_payload), packet_sha
    )
    contents_sha = write_artifact(root, CONTENTS_REFERENCE, contents_payload)
    _require_written_digest(contents_sha, contents_sha_expected)
    prompt_sha = write_artifact(root, PROMPT_REFERENCE, prompt_payload)
    contract_sha = write_artifact(root, CLIENT_CONTRACT_REFERENCE, contract_payload)
    _require_written_digest(contract_sha, contract_sha_expected)
    authorization_sha = write_artifact(root, AUTHORIZATION_REFERENCE, authorization_payload)
    prepared = {
        PACKET_REFERENCE: packet_sha,
        CONTENTS_REFERENCE: contents_sha,
        PROMPT_REFERENCE: prompt_sha,
        CLIENT_CONTRACT_REFERENCE: contract_sha,
        AUTHORIZATION_REFERENCE: authorization_sha,
    }

    def run_root_pins(extraction_run_sha: str) -> dict[str, dict[str, str]]:
        return {
            "packet_pin": {"reference": PACKET_REFERENCE, "sha256": packet_sha},
            "contents_pin": {"reference": CONTENTS_REFERENCE, "sha256": contents_sha},
            "prompt_pin": {"reference": PROMPT_REFERENCE, "sha256": prompt_sha},
            "client_contract_pin": {
                "reference": CLIENT_CONTRACT_REFERENCE,
                "sha256": contract_sha,
            },
            "authorization_pin": {
                "reference": AUTHORIZATION_REFERENCE,
                "sha256": authorization_sha,
            },
            "extraction_run_pin": {
                "reference": EXTRACTION_RUN_REFERENCE,
                "sha256": extraction_run_sha,
            },
        }

    # --- F2 through F5 --------------------------------------------------------
    trace: dict[str, Any] = {"phase": "start", "generate_records": ()}
    try:
        measured = _run_two_operation_measurement(
            root=root,
            provider=client,
            session=session,
            request=provider_request,
            authorization=authorization,
            max_output_tokens=declared_max_output_tokens,
            request_digest=request_digest,
            trace=trace,
        )
    except BaseException as exc:  # noqa: BLE001 - every terminal route publishes
        if not isinstance(exc, Exception):
            raise
        route = _classify_terminal(exc, trace)
        artifacts = dict(prepared)
        run_record = build_extraction_run(
            run_id=extraction_run_id,
            stage=stage,
            started_at=run_created_at,
            completed_at=run_created_at,
            status=route["status"],
            code_commit=code_commit,
            schema_hash=schema_hash,
            prompt_hash=prompt["prompt_hash"],
            source_manifest_hash=source_snapshot_manifest["sha256"],
            error_count=route["error_count"],
        )
        run_sha = write_artifact(root, EXTRACTION_RUN_REFERENCE, record_bytes(run_record))
        artifacts[EXTRACTION_RUN_REFERENCE] = run_sha
        provider_error_pin = None
        if route["provider_error"] is not None:
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
                reason_code=route["provider_error"],
                attempt_count=max(route["error_count"], 1),
            )
            error_sha = write_artifact(
                root, PROVIDER_ERROR_REFERENCE, record_bytes(error_record)
            )
            artifacts[PROVIDER_ERROR_REFERENCE] = error_sha
            provider_error_pin = {
                "reference": PROVIDER_ERROR_REFERENCE,
                "sha256": error_sha,
            }
        outcome_sha = _publish_execution_outcome(
            root=root,
            schema_root=schema_root,
            route=route,
            trace=trace,
            run_root_pins=run_root_pins(run_sha),
            evidence_binding=evidence_binding,
            provider_error_pin=provider_error_pin,
            measurement=None,
        )
        artifacts[EXECUTION_OUTCOME_REFERENCE] = outcome_sha
        for reference in (
            trace.get("count_record").raw_reference if trace.get("count_record") else None,
        ):
            if reference:
                artifacts[reference] = trace["count_record"].raw_sha256
        raise ExtractionError(
            "the two-operation run stopped; the terminal chain records why",
            reason_code=route["terminal_reason"],
            detail=route["route_family"],
        ) from None

    # --- F6: post-generation reconciliation ----------------------------------
    terminal = measured["generate_records"][-1]
    raw_bytes = (root / terminal.raw_reference).read_bytes()
    reconciliation = reconcile_usage(
        raw_bytes=raw_bytes, admitted_input_tokens=measured["measured_input_tokens"]
    )
    certified = reconciliation["measurement_status"] in ("verified", "unknown")
    route = {
        "route_family": "completed" if certified else "post_generation_invalid",
        "terminal_reason": "none" if certified else "reconciliation_invalid",
        "loop_termination_cause": "terminal_response_returned",
        "status": "completed" if certified else "invalid",
        "error_count": max(len(measured["generate_records"]) - 1, 0),
        "provider_error": None,
    }
    artifacts = dict(prepared)
    run_record = build_extraction_run(
        run_id=extraction_run_id,
        stage=stage,
        started_at=run_created_at,
        completed_at=run_created_at,
        status=route["status"],
        code_commit=code_commit,
        schema_hash=schema_hash,
        prompt_hash=prompt["prompt_hash"],
        source_manifest_hash=source_snapshot_manifest["sha256"],
        model_provider=contract["model_provider"],
        model_name=contract["model_name"],
        model_parameters=contract["model_parameters"],
        error_count=route["error_count"],
    )
    run_sha = write_artifact(root, EXTRACTION_RUN_REFERENCE, record_bytes(run_record))
    artifacts[EXTRACTION_RUN_REFERENCE] = run_sha
    outcome_sha = _publish_execution_outcome(
        root=root,
        schema_root=schema_root,
        route=route,
        trace=trace,
        run_root_pins=run_root_pins(run_sha),
        evidence_binding=evidence_binding,
        provider_error_pin=None,
        measurement=reconciliation,
    )
    count_record = trace["count_record"]
    artifacts[count_record.raw_reference] = count_record.raw_sha256
    artifacts[terminal.raw_reference] = terminal.raw_sha256
    artifacts[EXECUTION_OUTCOME_REFERENCE] = outcome_sha
    if not certified:
        # The bytes stay; the certification does not. No envelope, no manifest.
        raise ExtractionError(
            "post-generation reconciliation refused this run",
            reason_code="reconciliation_invalid",
            detail=reconciliation["usage_reason"],
        )

    envelope = build_prediction_envelope(
        prediction_record_id=f"{prediction_run_id}-0",
        stage=stage,
        source_references=[
            terminal.raw_reference,
            PROMPT_REFERENCE,
            CLIENT_CONTRACT_REFERENCE,
            AUTHORIZATION_REFERENCE,
            count_record.raw_reference,
            EXECUTION_OUTCOME_REFERENCE,
        ],
        prompt_model_metadata={
            **measured["response"].prompt_model_metadata,
            "contents_renderer_version": RENDERER_VERSION,
            "rendered_contents_reference": CONTENTS_REFERENCE,
            "rendered_contents_sha256": contents_sha,
            "measurement_status": reconciliation["measurement_status"],
            **prompt_plan,
        },
        input_packet_hash=packet_sha,
        prediction_run_manifest_reference=PREDICTION_MANIFEST_REFERENCE,
        input_packet_reference=PACKET_REFERENCE,
    )
    envelopes_sha = write_artifact(
        root, ENVELOPES_REFERENCE, canonical_jsonl_bytes([envelope])
    )
    artifacts[ENVELOPES_REFERENCE] = envelopes_sha
    manifest = build_prediction_artifact_manifest_v2(
        prediction_run_id=prediction_run_id,
        envelopes_reference=ENVELOPES_REFERENCE,
        envelopes_sha256=envelopes_sha,
        record_count=1,
        source_artifacts={
            "raw_prediction": {
                "reference": terminal.raw_reference,
                "sha256": terminal.raw_sha256,
            },
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
            "count_tokens_raw_response": {
                "reference": count_record.raw_reference,
                "sha256": count_record.raw_sha256,
            },
            "extraction_execution_outcome": {
                "reference": EXECUTION_OUTCOME_REFERENCE,
                "sha256": outcome_sha,
            },
        },
    )
    artifacts[PREDICTION_MANIFEST_REFERENCE] = write_artifact(
        root, PREDICTION_MANIFEST_REFERENCE, manifest_bytes(manifest)
    )
    return ExtractionOutcome(
        verdict="two_operation_run_complete",
        run_root=root,
        packet=packet,
        packet_sha256=packet_sha,
        artifacts=artifacts,
    )


def _client_contract_of_v2(client: object) -> dict[str, Any]:
    """The declared v2 contract, shaped but not validated against @0.1.0.

    The released ``validate_provider_client_contract`` enforces the v1 property
    set exactly; a v2 contract legitimately carries fourteen more fields, so
    running it here would refuse every conforming successor.
    """
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
    if not isinstance(contract, dict):
        raise ExtractionError(
            "the provider client contract must be a mapping",
            reason_code="client_contract_invalid",
        )
    if contract.get("contract") != CLIENT_CONTRACT_V2_CONTRACT:
        raise ExtractionError(
            f"the two-operation route requires {CLIENT_CONTRACT_V2_CONTRACT}",
            reason_code="client_contract_invalid",
        )
    if contract.get("schema_version") != "0.2.0":
        raise ExtractionError(
            "a v2 client contract must declare schema_version 0.2.0",
            reason_code="client_contract_invalid",
        )
    return dict(contract)


CLIENT_CONTRACT_V2_CONTRACT = "extraction_provider_client_contract@0.2.0"
