"""The canonical governance materializer (ADR-049, G4-1).

Four governance records have been *validated* by this package since ADR-035 and
*produced* by nobody. Every test wrote them by hand, every fixture invented its
own field order, and no code path could state what a correct chain looks like.
This module is that producer.

**Two roots, never one.** ``governance_artifact_root`` is where the four records
live: it must already exist and be empty when they are written, and it is handed
to :func:`~dynamic_ai_products.extraction.run_extraction.run_extraction_stage_v2`
afterwards so F0 can hydrate them again. ``run_root`` is where a run's own
outputs go and must **not** exist when the run starts. The two can never be the
same path -- one is required to be populated, the other required to be absent --
and this module never names, accepts, or creates a run root.

**A deterministic read-only builder, not a pure one.** Three digests in the
prompt-qualification record cannot be derived: they are the bytes of the frozen
prompt, of SPEC-024, and of the change request. :func:`build_governance_records`
therefore reads three files under ``repo_root``. It writes nothing, opens no
socket, reads no clock, reads no environment, resolves no credential, and does
not import ``providers``.

**The bundle is sealed.** :func:`build_governance_records` returns canonical
*bytes*, not mappings. A caller that mutated a returned dict between building and
writing would change what the validators saw without changing what was written;
storing bytes makes that unrepresentable. The writer writes exactly those bytes,
then re-reads them from disk and validates what it read -- never what it held.

**What this module does not do.** It never produces a real governance chain by
itself: ``vertex_project`` reaches it only inside a client contract its caller
built, and it has no opinion about whether that project is real or synthetic. It
performs no provider call, opens no client, and authorizes no run.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

from .errors import ExtractionError
from .input_packet import hydrate_pinned_artifact
from .manifests import (
    BUDGET_POLICY_VERSION,
    CANONICAL_BUDGET_METER_IDENTITY,
    CANONICAL_BUDGET_METER_VERSION,
    CLIENT_CONTRACT_V2_CONTRACT,
    ENABLEMENT_CONTRACT,
    ENABLEMENT_STATUS_FOR_ROLLOUT,
    GOVERNANCE_SCHEMA_VERSION,
    LIVE_AUTHORIZATION_V2_CONTRACT,
    QUALIFICATION_CONTRACT,
    STAGE_OUTPUT_CONTRACT_ID,
    resolve_attempt_cap_v2,
    resolve_stage_schema_hash,
    validate_authorization_scope,
    validate_budget_meter_identity,
    validate_governance_chain_v2,
    validate_governance_semantics,
    validate_provider_policy_versions,
    validate_v2_contract_execution_fields,
)
from .prompt_qualification import (
    BOOTSTRAP_BASIS,
    BOOTSTRAP_LIFECYCLE_STATE,
    BOOTSTRAP_SCOPE,
    BOOTSTRAP_STATUS,
    DECLARED_NON_CLAIMS,
    GOVERNING_SPEC_REFERENCE,
    KNOWN_LIMITATION_CODES,
    PROMPT_QUALIFICATION_CONTRACT,
    validate_prompt_qualification,
)
from .prompts import load_prompt, single_pass_prompt_plan
from .raw_artifacts import canonical_json_bytes, sha256_bytes, write_artifact
from .routing_contract import derive_routing_contract, validate_routing_contract

__all__ = [
    "GOVERNANCE_REFERENCES",
    "STAGE_CHANGE_REQUEST",
    "GovernanceBuild",
    "GovernanceValidationContext",
    "build_governance_records",
    "change_request_for_stage",
    "materialize_governance_records",
]

# Fixed canonical references. There is deliberately no caller-controlled
# reference parameter: a caller able to choose where a record lands could point
# two chains at one path, and the write-once refusal would then look like a bug
# rather than the collision it is. ``source_snapshot_bridge`` fixes its corpus
# filenames for the same reason.
#
# The production source of truth is this **tuple**, and every internal lookup --
# the embedded pins, ``GovernanceBuild.pin``, the write order, the hydration
# order and the symlink guard -- goes through :func:`_reference`. A public dict
# was tried first and was wrong: it was mutable, and assigning to it changed both
# the pins a build returned *and* the references embedded inside the written
# records, which made "no caller-controlled reference" false in exactly the way
# the sentence denies. A tuple cannot be assigned into.
_CANONICAL_REFERENCES: tuple[tuple[str, str], ...] = (
    ("qualification", "governance/adapter_qualification_record.json"),
    ("prompt_qualification", "governance/prompt_qualification_record.json"),
    ("enablement", "governance/adapter_enablement_record.json"),
    ("authorization", "governance/live_call_authorization.json"),
)

# A read-only view for callers that want to know where the records land. The
# dict it wraps is a throwaway with no other name, so nothing can reach it, and
# rebinding this module attribute cannot affect production either: no internal
# code path reads it.
GOVERNANCE_REFERENCES: Mapping[str, str] = MappingProxyType(dict(_CANONICAL_REFERENCES))


def _reference(name: str) -> str:
    """The canonical relative path of one record. The only production lookup."""
    for candidate, reference in _CANONICAL_REFERENCES:
        if candidate == name:
            return reference
    raise ExtractionError(
        f"unknown governance record: {name!r}", reason_code="governance_input_invalid"
    )

# Leaf to root. A digest cannot be taken of bytes that do not exist yet, so the
# order the records are built in is the reverse of the order they pin each other.
_BUILD_ORDER: tuple[str, ...] = tuple(name for name, _ in _CANONICAL_REFERENCES)

_ROOT_INVALID = "governance_root_invalid"

_BUDGET_FIELDS: tuple[str, ...] = (
    "budget_max_records",
    "budget_max_external_requests",
    "budget_max_input_tokens",
    "budget_max_output_tokens",
    "budget_max_estimated_cost_micros",
    "budget_max_wall_clock_seconds",
)
_IDENTITY_FIELDS: tuple[str, ...] = (
    "authorization_id",
    "enablement_id",
    "qualification_id",
    "prompt_qualification_id",
)
_PEOPLE_FIELDS: tuple[str, ...] = ("authorized_by", "approver", "reviewer")
_WINDOW_FIELDS: tuple[str, ...] = (
    "authorization_effective_at",
    "authorization_expires_at",
    "enablement_effective_at",
    "enablement_expires_at",
)

# The change request the bootstrap prompt qualification cites, per stage. Fixed
# here rather than accepted as a parameter: a caller free to cite any document
# could satisfy the digest check against a file that says nothing about this
# prompt.
#
# ADR-062. This was a single stage-agnostic constant, and the first capability
# chain cited the product prompt's change request. Nothing caught it: the
# reference resolves, the digest matches, and all eight post-write validators
# pass -- the chain is internally consistent and points a reader at a document
# about a different prompt. Fourth instance of one pattern (ADR-053, ADR-058,
# ADR-061): a constant written when only one stage existed, wrong the moment a
# second one did.
#
# Closed and fail-closed. ``task_extraction`` was absent through ADR-068
# because it had no qualified prompt; ADR-069 adds it, on purpose, the moment
# ``task_discovery_schema_v1`` exists to be qualified against.
#
# Known limitation, stated rather than implied: this map records *which change
# request is current*, so it must be updated whenever a stage's prompt is
# superseded -- as CR-0002 -> CR-0003 -> CR-0004 already were, by hand each
# time. Binding the change request to the prompt itself would remove that step,
# and is deliberately not done here: it is a larger contract decision than this
# defect requires.
STAGE_CHANGE_REQUEST: dict[str, str] = {
    "product_extraction": (
        "evals/change_requests/"
        "CR-0004-product-discovery-schema-v4-bootstrap-qualification.md"
    ),
    # ADR-064, then ADR-065. Moved from CR-0005 to CR-0006 to CR-0007 as the
    # capability prompt was superseded twice. This is the maintenance step
    # ADR-062 recorded as its own known limitation: the map states which change
    # request is *current*, so it moves with the prompt, every time.
    "capability_extraction": (
        "evals/change_requests/"
        "CR-0007-capability-discovery-schema-v3-bootstrap-qualification.md"
    ),
    # ADR-069 (E-T1 governance wiring). The task stage's first schema-bound
    # prompt, the same CR-0005 shape one stage on: a prompt whose declared
    # output contract was not the released schema, replaced by one that states
    # it explicitly.
    "task_extraction": (
        "evals/change_requests/"
        "CR-0008-task-discovery-schema-v1-bootstrap-qualification.md"
    ),
    # ADR-073 (CR-0009). The consolidation stage's first schema-bound prompt,
    # the same CR-0005 shape two stages on: a registered prompt with no output
    # contract that no code path could reach.
    "product_consolidation": (
        "evals/change_requests/"
        "CR-0009-product-consolidation-schema-v1-bootstrap-qualification.md"
    ),
}

_STAGE_CHANGE_REQUEST_UNDECLARED = "stage_change_request_undeclared"


def change_request_for_stage(stage: str) -> str:
    """The change request this stage's qualification cites, or a refusal.

    Never falls back. A default is what let a capability chain cite the product
    prompt's change request and pass every validator.
    """
    reference = STAGE_CHANGE_REQUEST.get(stage)
    if reference is None:
        raise ExtractionError(
            f"stage {stage!r} declares no qualifying change request, so a "
            "prompt qualification cannot be minted for it",
            reason_code=_STAGE_CHANGE_REQUEST_UNDECLARED,
        )
    return reference


def _text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(
            f"{what} must be a non-blank string", reason_code="governance_input_invalid"
        )
    return value


def _positive(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExtractionError(
            f"{what} must be a positive integer", reason_code="governance_input_invalid"
        )
    return value


def _require_exact_keys(mapping: Any, expected: tuple[str, ...], what: str) -> dict[str, Any]:
    """Exactly these keys, no more and no fewer.

    A missing key would default to ``None`` somewhere downstream; an extra key
    would be silently dropped and the caller would believe it had configured
    something it had not.
    """
    if not isinstance(mapping, dict):
        raise ExtractionError(
            f"{what} must be a mapping", reason_code="governance_input_invalid"
        )
    observed = set(mapping)
    missing = sorted(set(expected) - observed)
    extra = sorted(observed - set(expected))
    if missing or extra:
        raise ExtractionError(
            f"{what} must carry exactly {sorted(expected)}; missing={missing} extra={extra}",
            reason_code="governance_input_invalid",
        )
    return dict(mapping)


@dataclass(frozen=True)
class GovernanceValidationContext:
    """Everything the eight post-write validators need that is not a record.

    Every field is an immutable value. The three mappings the validators want --
    the client contract, the resolved prompt, the prompt plan -- are held as
    canonical bytes and re-parsed on access, so no caller retains a handle it
    could mutate between building and writing.
    """

    repo_root: str
    stage: str
    company_id: str
    observation_cutoff_date: str
    corpus_scope: str
    code_commit: str
    run_created_at: str
    stage_output_schema_sha256: str
    client_contract_payload: bytes
    client_contract_sha256: str
    prompt_payload: bytes
    prompt_plan_payload: bytes

    def client_contract(self) -> dict[str, Any]:
        return json.loads(self.client_contract_payload.decode("utf-8"))

    def prompt(self) -> dict[str, Any]:
        return json.loads(self.prompt_payload.decode("utf-8"))

    def prompt_plan(self) -> dict[str, Any]:
        return json.loads(self.prompt_plan_payload.decode("utf-8"))


@dataclass(frozen=True)
class GovernanceBuild:
    """The sealed result of a build: four payloads plus the validation context.

    Frozen, and carrying bytes rather than mappings. :meth:`record` re-parses on
    every call, so two callers never share one object and a mutation cannot
    travel from one to the other -- or into what gets written.
    """

    payloads: tuple[tuple[str, bytes], ...]
    context: GovernanceValidationContext

    def _payloads(self) -> dict[str, bytes]:
        return dict(self.payloads)

    def payload(self, name: str) -> bytes:
        try:
            return self._payloads()[name]
        except KeyError:
            raise ExtractionError(
                f"unknown governance record: {name!r}",
                reason_code="governance_input_invalid",
            ) from None

    def digest(self, name: str) -> str:
        return sha256_bytes(self.payload(name))

    def pin(self, name: str) -> dict[str, str]:
        return {"reference": _reference(name), "sha256": self.digest(name)}

    def record(self, name: str) -> dict[str, Any]:
        return json.loads(self.payload(name).decode("utf-8"))


def _qualification_record(
    *,
    qualification_id: str,
    adapter_identity: str,
    adapter_version: str,
    client_contract: dict[str, Any],
    client_contract_sha256: str,
    stage: str,
    stage_output_schema_sha256: str,
    rollout_state: str,
    qualified_at: str,
) -> dict[str, Any]:
    return {
        "contract": QUALIFICATION_CONTRACT,
        "schema_version": GOVERNANCE_SCHEMA_VERSION,
        "qualification_id": qualification_id,
        "adapter_identity": adapter_identity,
        "adapter_version": adapter_version,
        "adapter_family": "model_execution",
        "execution_contract_id": client_contract["contract"],
        "execution_contract_sha256": client_contract_sha256,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[stage],
        "stage_output_contract_sha256": stage_output_schema_sha256,
        "qualification_scope": rollout_state,
        "qualification_status": "qualified",
        "qualified_at": qualified_at,
    }


def _prompt_qualification_record(
    *,
    qualification_id: str,
    prompt: dict[str, Any],
    prompt_plan: dict[str, Any],
    routing: dict[str, str],
    client_contract: dict[str, Any],
    client_contract_sha256: str,
    stage: str,
    stage_output_schema_sha256: str,
    governing_spec_sha256: str,
    change_request_reference: str,
    change_request_sha256: str,
    code_commit: str,
    reviewer: str,
    decided_at: str,
) -> dict[str, Any]:
    return {
        "contract": PROMPT_QUALIFICATION_CONTRACT,
        "schema_version": GOVERNANCE_SCHEMA_VERSION,
        "qualification_id": qualification_id,
        "prompt_id": prompt_plan["prompt_id"],
        "prompt_reference": prompt["reference"],
        "prompt_artifact_sha256": prompt["prompt_hash"],
        "prompt_registry_version": prompt["prompt_registry_version"],
        "prompt_lifecycle_state": BOOTSTRAP_LIFECYCLE_STATE,
        "stage": stage,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[stage],
        "stage_output_contract_sha256": stage_output_schema_sha256,
        "execution_contract_id": client_contract["contract"],
        "execution_contract_sha256": client_contract_sha256,
        "routing_contract_id": routing["routing_contract_id"],
        "routing_contract_sha256": routing["routing_contract_sha256"],
        "governing_spec_reference": GOVERNING_SPEC_REFERENCE,
        "governing_spec_sha256": governing_spec_sha256,
        "change_request_reference": change_request_reference,
        "change_request_sha256": change_request_sha256,
        "qualification_basis": BOOTSTRAP_BASIS,
        "qualification_status": BOOTSTRAP_STATUS,
        "qualification_scope": BOOTSTRAP_SCOPE,
        "declared_non_claims": list(DECLARED_NON_CLAIMS),
        "known_limitation_codes": list(KNOWN_LIMITATION_CODES),
        "supersedes_qualification_id": None,
        "code_commit": code_commit,
        "reviewer": reviewer,
        "decided_at": decided_at,
    }


def _enablement_record(
    *,
    enablement_id: str,
    qualification_pin: dict[str, str],
    prompt_qualification_pin: dict[str, str],
    routing: dict[str, str],
    endpoint_allowlist: list[str],
    stage: str,
    stage_output_schema_sha256: str,
    deployment_environment_id: str,
    rollout_state: str,
    approver: str,
    effective_at: str,
    expires_at: str,
) -> dict[str, Any]:
    return {
        "contract": ENABLEMENT_CONTRACT,
        "schema_version": GOVERNANCE_SCHEMA_VERSION,
        "enablement_id": enablement_id,
        "adapter_qualification_record_reference": qualification_pin["reference"],
        "adapter_qualification_record_sha256": qualification_pin["sha256"],
        "prompt_qualification_reference": prompt_qualification_pin["reference"],
        "prompt_qualification_sha256": prompt_qualification_pin["sha256"],
        "stage": stage,
        "stage_output_contract_id": STAGE_OUTPUT_CONTRACT_ID[stage],
        "stage_output_contract_sha256": stage_output_schema_sha256,
        "routing_contract_id": routing["routing_contract_id"],
        "routing_contract_sha256": routing["routing_contract_sha256"],
        "deployment_environment_id": deployment_environment_id,
        "rollout_state": rollout_state,
        "endpoint_allowlist": list(endpoint_allowlist),
        "enablement_status": ENABLEMENT_STATUS_FOR_ROLLOUT[rollout_state],
        "approver": approver,
        "effective_at": effective_at,
        "expires_at": expires_at,
    }


def _authorization_record(
    *,
    authorization_id: str,
    enablement_pin: dict[str, str],
    client_contract: dict[str, Any],
    client_contract_sha256: str,
    endpoint_allowlist: list[str],
    stage: str,
    company_id: str,
    observation_cutoff_date: str,
    corpus_scope: str,
    budget: dict[str, int],
    circuit_breaker_max_consecutive_failures: int,
    deployment_environment_id: str,
    rollout_state: str,
    authorized_by: str,
    effective_at: str,
    expires_at: str,
) -> dict[str, Any]:
    record = {
        "contract": LIVE_AUTHORIZATION_V2_CONTRACT,
        "schema_version": "0.2.0",
        "authorization_id": authorization_id,
        "authorized_by": authorized_by,
        "effective_at": effective_at,
        "expires_at": expires_at,
        "deployment_environment_id": deployment_environment_id,
        "rollout_state": rollout_state,
        "adapter_enablement_record_reference": enablement_pin["reference"],
        "adapter_enablement_record_sha256": enablement_pin["sha256"],
        # The reference is the run-root path the orchestrator will write the
        # contract to, not a governance-root path: the authorization pins what
        # the run will persist, and that artifact does not exist yet.
        "provider_client_contract_reference": "inputs/provider_client_contract.json",
        "provider_client_contract_sha256": client_contract_sha256,
        # Code-owned, never accepted from a caller. ADR-047: an authorization
        # that declared whatever it was handed would be checked against itself.
        "budget_meter_identity": CANONICAL_BUDGET_METER_IDENTITY,
        "budget_meter_version": CANONICAL_BUDGET_METER_VERSION,
        "budget_policy_version": BUDGET_POLICY_VERSION,
        "retry_policy_version": client_contract["retry_policy_version"],
        "rate_limit_policy_version": client_contract["rate_limit_policy_version"],
        "stage": stage,
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "corpus_scope": corpus_scope,
        "circuit_breaker_max_consecutive_failures": (
            circuit_breaker_max_consecutive_failures
        ),
        "endpoint_allowlist": list(endpoint_allowlist),
        "provider_called": True,
        "harness_run": False,
    }
    record.update(budget)
    return record


def build_governance_records(
    *,
    client_contract: Any,
    repo_root: str | Path,
    stage: str,
    company_id: str,
    observation_cutoff_date: str,
    corpus_scope: str,
    code_commit: str,
    run_created_at: str,
    rollout_state: str,
    deployment_environment_id: str,
    budget: Any,
    circuit_breaker_max_consecutive_failures: Any,
    identities: Any,
    people: Any,
    window: Any,
    qualified_at: str,
    decided_at: str,
    adapter_identity: str,
    adapter_version: str,
    schema_root: str = "schemas",
    **forbidden: Any,
) -> GovernanceBuild:
    """Build the four records and seal them with their validation context.

    Deterministic and read-only. Three files are opened under ``repo_root`` --
    the frozen prompt, SPEC-024, and the change request -- because their digests
    are bytes rather than derivations. Nothing is written, no clock is read, no
    environment is read, no credential is resolved, and ``providers`` is not
    imported: ``vertex_project`` arrives only inside ``client_contract``, which
    the caller built.

    ``**forbidden`` refuses unknown keywords rather than ignoring them. A caller
    that misspelled ``budget`` and had it silently dropped would believe it had
    configured a ceiling it had not.
    """
    if forbidden:
        raise ExtractionError(
            f"unsupported inputs: {sorted(forbidden)}",
            reason_code="governance_input_invalid",
        )
    contract = validate_v2_contract_execution_fields(client_contract)
    if contract["contract"] != CLIENT_CONTRACT_V2_CONTRACT:  # pragma: no cover - gate covers it
        raise ExtractionError(
            "the two-operation route requires the v2 client contract",
            reason_code="client_contract_invalid",
        )
    budget_values = _require_exact_keys(budget, _BUDGET_FIELDS, "budget")
    for field in _BUDGET_FIELDS:
        _positive(budget_values[field], field)
    ids = _require_exact_keys(identities, _IDENTITY_FIELDS, "identities")
    who = _require_exact_keys(people, _PEOPLE_FIELDS, "people")
    when = _require_exact_keys(window, _WINDOW_FIELDS, "window")
    for mapping, label in ((ids, "identities"), (who, "people"), (when, "window")):
        for key, value in mapping.items():
            _text(value, f"{label}.{key}")
    for value, what in (
        (stage, "stage"),
        (company_id, "company_id"),
        (observation_cutoff_date, "observation_cutoff_date"),
        (corpus_scope, "corpus_scope"),
        (code_commit, "code_commit"),
        (run_created_at, "run_created_at"),
        (rollout_state, "rollout_state"),
        (deployment_environment_id, "deployment_environment_id"),
        (qualified_at, "qualified_at"),
        (decided_at, "decided_at"),
        (adapter_identity, "adapter_identity"),
        (adapter_version, "adapter_version"),
    ):
        _text(value, what)
    _positive(circuit_breaker_max_consecutive_failures, "circuit_breaker_max_consecutive_failures")
    if rollout_state not in ENABLEMENT_STATUS_FOR_ROLLOUT:
        raise ExtractionError(
            f"unknown rollout state: {rollout_state!r}",
            reason_code="governance_input_invalid",
        )
    if stage not in STAGE_OUTPUT_CONTRACT_ID:
        raise ExtractionError(
            f"unknown extraction stage: {stage!r}", reason_code="packet_stage_invalid"
        )

    root = Path(repo_root)
    schema_hash = resolve_stage_schema_hash(stage, str(root / schema_root))
    prompt_plan = single_pass_prompt_plan(stage)
    prompt = load_prompt(root, prompt_plan["prompt_id"])
    # The two cited repository documents. Read, not derived: their digests are
    # the bytes on disk, and ``validate_prompt_qualification`` re-reads both.
    governing_spec_sha256 = sha256_bytes((root / GOVERNING_SPEC_REFERENCE).read_bytes())
    change_request_reference = change_request_for_stage(stage)
    change_request_sha256 = sha256_bytes((root / change_request_reference).read_bytes())

    contract_payload = canonical_json_bytes(contract)
    contract_sha256 = sha256_bytes(contract_payload)
    routing = derive_routing_contract(client_contract=contract)
    endpoints = contract["operation_endpoints"]
    # One fixed order. The connector compares the allowlist as a set of
    # normalized pairs, but the authorization is hash-pinned, so a permuted list
    # would be a different artifact for the same route.
    endpoint_allowlist = [endpoints["count_tokens"], endpoints["generate_content"]]

    records: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes] = {}

    def seal(name: str, record: dict[str, Any]) -> None:
        records[name] = record
        payloads[name] = canonical_json_bytes(record)

    def pin(name: str) -> dict[str, str]:
        return {
            "reference": _reference(name),
            "sha256": sha256_bytes(payloads[name]),
        }

    seal(
        "qualification",
        _qualification_record(
            qualification_id=ids["qualification_id"],
            adapter_identity=adapter_identity,
            adapter_version=adapter_version,
            client_contract=contract,
            client_contract_sha256=contract_sha256,
            stage=stage,
            stage_output_schema_sha256=schema_hash,
            rollout_state=rollout_state,
            qualified_at=qualified_at,
        ),
    )
    seal(
        "prompt_qualification",
        _prompt_qualification_record(
            qualification_id=ids["prompt_qualification_id"],
            prompt=prompt,
            prompt_plan=prompt_plan,
            routing=routing,
            client_contract=contract,
            client_contract_sha256=contract_sha256,
            stage=stage,
            stage_output_schema_sha256=schema_hash,
            governing_spec_sha256=governing_spec_sha256,
            change_request_reference=change_request_reference,
            change_request_sha256=change_request_sha256,
            code_commit=code_commit,
            reviewer=who["reviewer"],
            decided_at=decided_at,
        ),
    )
    seal(
        "enablement",
        _enablement_record(
            enablement_id=ids["enablement_id"],
            qualification_pin=pin("qualification"),
            prompt_qualification_pin=pin("prompt_qualification"),
            routing=routing,
            endpoint_allowlist=endpoint_allowlist,
            stage=stage,
            stage_output_schema_sha256=schema_hash,
            deployment_environment_id=deployment_environment_id,
            rollout_state=rollout_state,
            approver=who["approver"],
            effective_at=when["enablement_effective_at"],
            expires_at=when["enablement_expires_at"],
        ),
    )
    seal(
        "authorization",
        _authorization_record(
            authorization_id=ids["authorization_id"],
            enablement_pin=pin("enablement"),
            client_contract=contract,
            client_contract_sha256=contract_sha256,
            endpoint_allowlist=endpoint_allowlist,
            stage=stage,
            company_id=company_id,
            observation_cutoff_date=observation_cutoff_date,
            corpus_scope=corpus_scope,
            budget=budget_values,
            circuit_breaker_max_consecutive_failures=(
                circuit_breaker_max_consecutive_failures
            ),
            deployment_environment_id=deployment_environment_id,
            rollout_state=rollout_state,
            authorized_by=who["authorized_by"],
            effective_at=when["authorization_effective_at"],
            expires_at=when["authorization_expires_at"],
        ),
    )

    context = GovernanceValidationContext(
        repo_root=str(root),
        stage=stage,
        company_id=company_id,
        observation_cutoff_date=observation_cutoff_date,
        corpus_scope=corpus_scope,
        code_commit=code_commit,
        run_created_at=run_created_at,
        stage_output_schema_sha256=schema_hash,
        client_contract_payload=contract_payload,
        client_contract_sha256=contract_sha256,
        prompt_payload=canonical_json_bytes(prompt),
        prompt_plan_payload=canonical_json_bytes(prompt_plan),
    )
    return GovernanceBuild(
        payloads=tuple((name, payloads[name]) for name in _BUILD_ORDER),
        context=context,
    )


def _require_no_symlink_component(attempt_root: Path, reference: str) -> None:
    """Refuse a symlink anywhere between the root and the target.

    ``_safe_target`` does **not** do this. Measured: it checks only whether the
    final target is a symlink and whether the resolved path escapes the root, so
    an intermediate directory symlink that stays inside the root passes both the
    path check and a real read. That is tolerable for a reader whose digests are
    pinned; it is not tolerable for a writer, because the record would land
    somewhere other than where the pin says it is and nothing would show it.

    In practice the emptiness rule fires first for anything that pre-exists, so
    this is defence in depth over the ``mkdir`` that :func:`write_artifact`
    performs afterwards rather than the first line of defence.

    **Declared limit.** This walks downward from the attempt root and does not
    inspect the root's own ancestry. Refusing every symlinked ancestor would
    reject ordinary platform paths -- measured, ``/tmp`` is itself a symlink on
    macOS -- so choosing and creating the attempt root stays the runbook's
    explicit step (G4-0 R7), and that is where ancestry is accounted for.
    """
    current = attempt_root
    for part in Path(reference).parts:
        current = current / part
        if current.is_symlink():
            raise ExtractionError(
                f"governance path component is a symlink: {current}",
                reason_code=_ROOT_INVALID,
            )


def _require_attempt_root(attempt_root: str | Path) -> Path:
    """Accept only an existing, real, non-symlink, completely empty directory.

    Creation is **not** this function's job. G4-0 R7 makes creating the attempt
    root an explicit operator step, so that "who made this root, when, under
    which container" has an answer in the runbook rather than being a side
    effect of the first write.

    Emptiness is total, not "the four targets are absent". A partial root left
    by a failed attempt still lacks some of the four, and writing a second chain
    beside the first one's remains would mix two attempts in one place.
    ``os.listdir`` never returns ``.`` or ``..``, so the test is exact -- and it
    does return dotfiles, which is why a stray ``.gitkeep`` disqualifies a root.
    """
    root = Path(attempt_root)
    if root.is_symlink():
        raise ExtractionError(
            f"governance attempt root must not be a symlink: {root}",
            reason_code=_ROOT_INVALID,
        )
    if not root.exists():
        raise ExtractionError(
            f"governance attempt root does not exist: {root}; creating it is an "
            "explicit runbook step, not a side effect of materialization",
            reason_code=_ROOT_INVALID,
        )
    if not root.is_dir():
        raise ExtractionError(
            f"governance attempt root must be a directory: {root}",
            reason_code=_ROOT_INVALID,
        )
    try:
        entries = os.listdir(root)
    except OSError as exc:
        raise ExtractionError(
            f"governance attempt root is unreadable: {root}", reason_code=_ROOT_INVALID
        ) from exc
    if entries:
        raise ExtractionError(
            f"governance attempt root is not empty: {root}; a retry uses a new "
            "attempt root and never reuses a partial one",
            reason_code="destination_exists",
        )
    for _, reference in _CANONICAL_REFERENCES:
        _require_no_symlink_component(root, reference)
    return root


def materialize_governance_records(
    build: GovernanceBuild, *, attempt_root: str | Path
) -> dict[str, str]:
    """Write the four records, re-read them, validate them, return the run pin.

    The bundle is the only input. There is no second place to pass ``stage`` or
    ``run_created_at`` or a contract, so the value used to build a record and the
    value used to validate it cannot drift apart -- the drift is unrepresentable
    rather than merely discouraged.

    The bytes written are :meth:`GovernanceBuild.payload`, verbatim. The mappings
    validated afterwards are re-hydrated **from disk**, not taken from the
    bundle, so what is checked is what was persisted.

    ``attempt_root`` is a *governance* root and is never a run root. The two are
    opposites by construction: this one must already exist and be empty, and a
    run root must not exist at all when a run starts.

    Returns the in-memory authorization pin. It is not a fifth artifact and is
    not written anywhere; it is the mapping the caller hands to
    ``run_extraction_stage_v2`` alongside the same ``governance_artifact_root``.
    """
    if not isinstance(build, GovernanceBuild):
        raise ExtractionError(
            "materialization consumes a sealed GovernanceBuild",
            reason_code="governance_input_invalid",
        )
    root = _require_attempt_root(attempt_root)

    for name in _BUILD_ORDER:
        reference = _reference(name)
        written = write_artifact(root, reference, build.payload(name))
        if written != build.digest(name):  # pragma: no cover - write_artifact verifies
            raise ExtractionError(
                f"{reference} was not persisted as the bytes that were built",
                reason_code="write_error",
            )

    hydrated = {
        name: hydrate_pinned_artifact(
            root,
            build.pin(name),
            what=f"governance {name}",
            unsafe_code="authorization_chain_broken",
            sha_code="authorization_chain_broken",
        )
        for name in _BUILD_ORDER
    }
    _validate_written_chain(build, hydrated)
    return build.pin("authorization")


def _validate_written_chain(
    build: GovernanceBuild, hydrated: dict[str, dict[str, Any]]
) -> None:
    """Every governance check the v2 route runs at F0 and in its pre-mkdir band.

    Eight calls. ``validate_governance_chain_v2`` deliberately does not see the
    prompt-qualification record -- its signature has no parameter for one -- so
    running it alone would leave P1 through P14 unexercised, which is exactly
    what an earlier revision of this design got wrong.

    The budget meter identity is passed as **code constants**, not from the
    bundle. Letting a caller supply it would restore the tautology ADR-047
    closed: the authorization would be compared with a value its own author
    chose. This proves the authorization declares what this build's session will
    report; it does not exercise the session factory, which needs an
    ``extraction_run_id`` that does not exist until a run starts.
    """
    context = build.context
    authorization = hydrated["authorization"]
    enablement = hydrated["enablement"]
    qualification = hydrated["qualification"]
    client_contract = context.client_contract()

    validate_governance_chain_v2(
        authorization=authorization,
        enablement=enablement,
        qualification=qualification,
        authorization_pin=build.pin("authorization"),
        enablement_pin=build.pin("enablement"),
        qualification_pin=build.pin("qualification"),
    )
    validate_governance_semantics(
        authorization=authorization,
        enablement=enablement,
        qualification=qualification,
        stage=context.stage,
        run_created_at=context.run_created_at,
        stage_output_schema_sha256=context.stage_output_schema_sha256,
    )
    validate_authorization_scope(
        authorization=authorization,
        stage=context.stage,
        company_id=context.company_id,
        observation_cutoff_date=context.observation_cutoff_date,
        corpus_scope=context.corpus_scope,
        run_created_at=context.run_created_at,
    )
    validate_prompt_qualification(
        record=hydrated["prompt_qualification"],
        enablement=enablement,
        authorization=authorization,
        qualification=qualification,
        prompt=context.prompt(),
        prompt_plan=context.prompt_plan(),
        stage=context.stage,
        stage_output_schema_sha256=context.stage_output_schema_sha256,
        client_contract_sha256=context.client_contract_sha256,
        code_commit=context.code_commit,
        run_created_at=context.run_created_at,
        repo_root=context.repo_root,
    )
    validate_provider_policy_versions(
        authorization=authorization, client_contract=client_contract
    )
    validate_routing_contract(enablement=enablement, client_contract=client_contract)
    validate_budget_meter_identity(
        authorization=authorization,
        meter_identity={
            "meter_identity": CANONICAL_BUDGET_METER_IDENTITY,
            "meter_version": CANONICAL_BUDGET_METER_VERSION,
        },
        expected_budget_policy_version=BUDGET_POLICY_VERSION,
    )
    resolve_attempt_cap_v2(authorization=authorization)
