"""The canonical routing contract for the two-operation route (ADR-048, G3-3).

``routing_contract_id`` and ``routing_contract_sha256`` have been **required**
fields of ``adapter_enablement_record@0.1.0`` and
``prompt_qualification_record@0.1.0`` since those schemas were released, and
SPEC-027 and SPEC-024 both ask for a "routing contract identity/hash". Nothing
ever produced one. Measured before this module existed: the only check in the
repository compared the prompt qualification's two routing fields with the
enablement's two routing fields -- both caller-supplied -- so a digest of
``"4" * 64`` satisfied the entire suite. This module is the missing producer.

**The digest is derived from what executes, and compared with what governance
declared.** Those are two different origins, which is the whole point. An
earlier shape would have derived the digest from the enablement's own fields
and then compared it with the enablement, which is the tautology ADR-047 closed
for the budget meter. :func:`derive_routing_contract` therefore does not take
``enablement`` at all: the tautology is unrepresentable here rather than merely
avoided.

**What a route is, for the purpose of this digest.** The destination and the
transport rules: the contract identity being executed, the API version, both
operation endpoints, the three endpoint/protocol policies, and the two policy
versions. ``vertex_project``, ``vertex_location`` and ``model_name`` are
deliberately absent -- every one of them is already encoded inside the two
endpoint URLs, and a field that lives in two places can drift in one of them.

**A byte binding, not a grammar binding.** Endpoint URLs enter the projection
exactly as the contract spells them. ``extraction`` may not import
``providers``, so re-implementing ``endpoint_grammar_v2`` here would create the
second grammar owner that module exists to prevent; scheme, host, port, path,
the operation suffixes and the shared model base stay the connector's business.

The consequence is stated exactly rather than overstated: two spellings of one
endpoint produce **two different digests**. That by itself is not a refusal --
an enablement pinned to the respelled contract's own digest matches it and is
accepted, because this module compares digests and has no opinion about which
spelling is canonical. The refusal happens when a *pre-existing* pin was minted
from the other spelling: then the digests differ and the run stops. So this
protects against a route changing underneath a fixed governance pin, and does
not deduplicate two spellings of one destination. That second job belongs to the
connector's grammar, which normalizes before comparing, and is what
``provider_client_contract_sha256`` also leaves to it.

This module owns routing and nothing else. The policy versions travel *inside*
the projection -- the digest covers them -- but they are **validated** by
``manifests.validate_provider_policy_versions``, which owns the pins. One rule,
one owner.
"""

from __future__ import annotations

from typing import Any

from .errors import ExtractionError
from .manifests import validate_v2_contract_execution_fields
from .raw_artifacts import canonical_json_bytes, sha256_bytes

# ``_routing_projection`` is deliberately absent: exporting it would let a caller
# assemble a projection the runner never bound and hash it into something that
# looks like provenance.
__all__ = [
    "ROUTING_CONTRACT_ID",
    "derive_routing_contract",
    "validate_routing_contract",
]

# Code-owned, exactly like the budget meter identity in ADR-047. The enablement
# declares which route it authorized; this says which route this build actually
# is. Both sides of the comparison in :func:`validate_routing_contract` come from
# different places because of this line.
ROUTING_CONTRACT_ID = "vertex_gemini_route@0.2.0"

_ROUTING_CONTRACT_MISMATCH = "routing_contract_mismatch"


def _routing_projection(contract: dict[str, Any]) -> dict[str, Any]:
    """The closed nine-key projection that the digest is taken over.

    ``ROUTING_CONTRACT_ID`` is read here as a module-level name **at call time**,
    not captured in a default argument and not copied into a constant at import.
    That is a requirement, not a style choice: it is what makes the constant's
    participation in the digest observable by a test that patches it.
    """
    return {
        "api_version": contract["api_version"],
        "client_contract_id": contract["contract"],
        "endpoint_match_mode": contract["endpoint_match_mode"],
        "endpoint_query_policy": contract["endpoint_query_policy"],
        "operation_endpoints": dict(contract["operation_endpoints"]),
        "protocol_switch_policy": contract["protocol_switch_policy"],
        "rate_limit_policy_version": contract["rate_limit_policy_version"],
        "retry_policy_version": contract["retry_policy_version"],
        "routing_contract_id": ROUTING_CONTRACT_ID,
    }


def derive_routing_contract(*, client_contract: Any) -> dict[str, str]:
    """Derive this build's routing identity and digest from the executing contract.

    The shape gate runs **here**, not only in the caller. G4 materialization will
    call this function directly to mint the pin an enablement record carries, and
    on that path no runner has checked anything; a producer that trusted its
    caller would happily project a v1 contract.

    Deterministic and pure: no clock, no network, no filesystem, no environment
    and no credential. Two runs of the same build against the same contract
    produce the same digest, which is what lets an enablement pin it at all.
    """
    contract = validate_v2_contract_execution_fields(client_contract)
    return {
        "routing_contract_id": ROUTING_CONTRACT_ID,
        "routing_contract_sha256": sha256_bytes(
            canonical_json_bytes(_routing_projection(contract))
        ),
    }


def validate_routing_contract(
    *, enablement: dict[str, Any], client_contract: Any
) -> None:
    """Bind the enablement's declared route to the route about to be executed.

    This closes the upper half of a chain whose lower half already existed: the
    prompt qualification has always been required to agree with the enablement on
    both routing fields, but the enablement itself agreed with nothing. Now the
    executed contract determines the digest, the enablement must match it, and
    the prompt qualification must match the enablement.

    Identity first, then digest. A run pointed at an entirely different route
    should say so, rather than reporting the digest mismatch that a different
    route would also produce.
    """
    derived = derive_routing_contract(client_contract=client_contract)
    if enablement.get("routing_contract_id") != derived["routing_contract_id"]:
        raise ExtractionError(
            "the enablement authorizes a different route identity than this build "
            "executes",
            reason_code=_ROUTING_CONTRACT_MISMATCH,
        )
    if enablement.get("routing_contract_sha256") != derived["routing_contract_sha256"]:
        raise ExtractionError(
            "the enablement pins a routing digest that does not describe the "
            "contract this run is about to execute",
            reason_code=_ROUTING_CONTRACT_MISMATCH,
        )
