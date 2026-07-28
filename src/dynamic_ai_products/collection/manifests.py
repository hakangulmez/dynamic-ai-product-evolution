"""Collection run manifests and the receipt (SPEC-004, SPEC-005, ADR-032).

Every manifest records the full run-manifest field set. ``prompt_hash`` and
``model_route`` are asserted null: no prompt and no model participates in
official-source discovery or snapshotting.
"""

from __future__ import annotations

from typing import Any

from .canonical_url import CANONICALIZATION_VERSION
from .domains import OFFICIAL_APEX, SEC_DERIVATION_PINS
from .errors import CollectionError
from .publication import COLLECTION_MANIFEST_CONTRACT, PUBLICATION_MODEL
from .transport import (
    CLIENT_CONTRACT,
    RATE_LIMIT_POLICY_VERSION,
    ROBOTS_POLICY_VERSION,
    client_contract_hash,
)

__all__ = [
    "PILOT_INPUT_PINS",
    "RECEIPT_CONTRACT",
    "build_collection_identity",
    "build_official_web_collection_manifest",
    "build_web_collection_receipt",
    "build_web_discovery_manifest",
]

RECEIPT_CONTRACT = "web_collection_receipt@0.1.0"
DISCOVERY_CONTRACT = "web_discovery_manifest@0.1.0"

# The five Pilot 0 input pins and the parent Increment B manifest pin.
PILOT_INPUT_PINS: dict[str, str] = {
    "packet_sha256": "7abbf6720b78a00130f53055bb5c44f6ed90a2a397ad1675026871569bc381e6",
    "collection_receipt_sha256": (
        "26e91fe2ea5127cb6e5233ba4b2170f42089c4fb07224874c8d617724c71299b"
    ),
    "submissions_sha256": SEC_DERIVATION_PINS["submissions"],
    "filing_index_sha256": SEC_DERIVATION_PINS["filing_index"],
    "primary_document_sha256": SEC_DERIVATION_PINS["primary_document"],
}
PARENT_INGESTION_MANIFEST_SHA256 = (
    "aacc8cdb774f6cb28180d326c798f6b32b55c62a1f5cc7af2168f56c75df6bbb"
)


def _require_injected(code_commit: str, run_created_at: str) -> None:
    for name, value in (("code_commit", code_commit), ("run_created_at", run_created_at)):
        if not isinstance(value, str) or not value.strip():
            raise CollectionError(
                f"{name} must be injected by the caller; this package reads no "
                "clock and no VCS",
                reason_code="run_identity_invalid",
            )


def build_collection_identity(
    *,
    code_commit: str,
    run_created_at: str,
    request_plan_sha256: str,
    parent_ingestion_manifest_sha256: str = PARENT_INGESTION_MANIFEST_SHA256,
    pilot_input_pins: dict[str, str] | None = None,
) -> dict[str, str]:
    """Assemble exactly the fourteen run-identity keys."""
    _require_injected(code_commit, run_created_at)
    pins = dict(pilot_input_pins or PILOT_INPUT_PINS)
    missing = sorted(set(PILOT_INPUT_PINS) - set(pins))
    if missing:
        raise CollectionError(
            f"missing Pilot 0 input pins: {missing}", reason_code="run_identity_invalid"
        )
    return {
        "contract": COLLECTION_MANIFEST_CONTRACT,
        "code_commit": code_commit,
        "run_created_at": run_created_at,
        "parent_ingestion_manifest_sha256": parent_ingestion_manifest_sha256,
        "packet_sha256": pins["packet_sha256"],
        "collection_receipt_sha256": pins["collection_receipt_sha256"],
        "submissions_sha256": pins["submissions_sha256"],
        "filing_index_sha256": pins["filing_index_sha256"],
        "primary_document_sha256": pins["primary_document_sha256"],
        "request_plan_sha256": request_plan_sha256,
        "collection_client_contract_hash": client_contract_hash(),
        "canonicalization_version": CANONICALIZATION_VERSION,
        "robots_policy_version": ROBOTS_POLICY_VERSION,
        "rate_limit_policy_version": RATE_LIMIT_POLICY_VERSION,
    }


def build_web_discovery_manifest(
    *,
    code_commit: str,
    run_created_at: str,
    company_id: str,
    observation_cutoff_date: str,
    candidate_count: int,
    request_plan_sha256: str,
    exclusions: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    _require_injected(code_commit, run_created_at)
    return {
        "contract": DISCOVERY_CONTRACT,
        "schema_version": "0.1.0",
        "spec_version": "SPEC-004",
        "code_commit": code_commit,
        "run_created_at": run_created_at,
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "official_domain_apex": OFFICIAL_APEX,
        "apex_derivation_pins": dict(sorted(SEC_DERIVATION_PINS.items())),
        "canonicalization_version": CANONICALIZATION_VERSION,
        "request_plan_sha256": request_plan_sha256,
        "candidate_count": candidate_count,
        "discovery_mode": "request_plan_only",
        "retry_count": 0,
        "prompt_hash": None,
        "model_route": None,
        "exclusions": list(exclusions or []),
    }


def build_web_collection_receipt(
    *,
    code_commit: str,
    run_created_at: str,
    company_id: str,
    request_plan_sha256: str,
    initial_requests: list[dict[str, Any]],
    robots_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    """The receipt: three request classes accounted separately."""
    _require_injected(code_commit, run_created_at)
    return {
        "contract": RECEIPT_CONTRACT,
        "schema_version": "0.1.0",
        "spec_version": "SPEC-005",
        "code_commit": code_commit,
        "run_created_at": run_created_at,
        "company_id": company_id,
        "request_plan_sha256": request_plan_sha256,
        "collection_client": dict(sorted(CLIENT_CONTRACT.items())),
        "collection_client_contract_hash": client_contract_hash(),
        "initial_requests": list(initial_requests),
        "robots_requests": list(robots_requests),
        "retry_count": sum(int(r.get("retry_count", 0)) for r in initial_requests),
        "prompt_hash": None,
        "model_route": None,
    }


def build_official_web_collection_manifest(
    *,
    run_id: str,
    identity: dict[str, str],
    company_id: str,
    observation_cutoff_date: str,
    artifact_bindings: dict[str, str],
    verdict: str,
) -> dict[str, Any]:
    """The run-root audit artifact binding every collection output."""
    if verdict not in {"official_packet_ready", "no_supported_case"}:
        raise CollectionError(
            f"unknown collection verdict: {verdict}", reason_code="verdict_invalid"
        )
    return {
        "contract": COLLECTION_MANIFEST_CONTRACT,
        "schema_version": "0.1.0",
        "spec_versions": {"stage_02": "SPEC-004", "stage_03": "SPEC-005"},
        "collection_run_id": run_id,
        "code_commit": identity["code_commit"],
        "run_created_at": identity["run_created_at"],
        "company_id": company_id,
        "observation_cutoff_date": observation_cutoff_date,
        "publication_model": PUBLICATION_MODEL,
        "parent_ingestion_manifest_sha256": identity["parent_ingestion_manifest_sha256"],
        "pilot_input_pins": {
            "packet_sha256": identity["packet_sha256"],
            "collection_receipt_sha256": identity["collection_receipt_sha256"],
            "submissions_sha256": identity["submissions_sha256"],
            "filing_index_sha256": identity["filing_index_sha256"],
            "primary_document_sha256": identity["primary_document_sha256"],
        },
        "request_plan_sha256": identity["request_plan_sha256"],
        "collection_client_contract_hash": identity["collection_client_contract_hash"],
        "canonicalization_version": identity["canonicalization_version"],
        "robots_policy_version": identity["robots_policy_version"],
        "rate_limit_policy_version": identity["rate_limit_policy_version"],
        "official_domain_apex": OFFICIAL_APEX,
        "artifact_bindings": dict(sorted(artifact_bindings.items())),
        "retry_count": 0,
        "prompt_hash": None,
        "model_route": None,
        "verdict": verdict,
    }
