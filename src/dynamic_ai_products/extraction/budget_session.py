"""The canonical budget session for the two-operation route (ADR-047).

Before this module ``BudgetSession`` was a ``Protocol`` and nothing more: the
repository declared a metering seam and shipped no implementation of it, so every
run depended on whatever object a caller injected. G3-0 recorded that as a
blocker, and this is the producer that closes it.

**The identity is owned by code, not by the artifact it is checked against.**
An earlier design had the factory read ``budget_meter_identity`` and
``budget_meter_version`` out of the authorization. That would have made
``validate_budget_meter_identity`` compare the authorization with itself. The
session reports :data:`CANONICAL_BUDGET_METER_IDENTITY` and
:data:`CANONICAL_BUDGET_METER_VERSION` instead, and the authorization is checked
against those; the two sides of the comparison now come from different places.
The factory never receives the authorization mapping at all, which makes the
tautology unrepresentable rather than merely avoided.

**One enforcement owner.** The runner already refuses on
``budget_max_input_tokens`` and ``budget_max_estimated_cost_micros`` before it
calls :meth:`admit`, so those ceilings are not passed in here and this session
does not re-check them. Two copies of a ceiling can disagree; one cannot.

**No clock, no network, no environment.** The package forbids all three, and the
nonce below is derived rather than sampled for the same reason ``code_commit``
and ``run_created_at`` are injected: a value that changes by itself cannot be
reproduced. The consequence is stated plainly rather than hidden --
``budget_max_wall_clock_seconds`` remains a compatibility floor, and nothing here
measures elapsed time.

What this session actually is, stated honestly: a code-owned identity, a cap
bound at construction, a derived nonce, and an ``admit`` that may be spent once.
It is not a budget engine.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .errors import ExtractionError
from .manifests import (
    BUDGET_POLICY_VERSION,
    CANONICAL_BUDGET_METER_IDENTITY,
    CANONICAL_BUDGET_METER_VERSION,
)
from .provider_adapter import BudgetAdmission
from .raw_artifacts import canonical_json_bytes, sha256_bytes

# ``CanonicalBudgetSession`` and ``build_budget_session`` are the public surface.
# The nonce derivation is **not**: it is an implementation detail of the factory,
# and exporting it would invite a caller to mint a nonce the runner never bound.
__all__ = [
    "CanonicalBudgetSession",
    "build_budget_session",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_ADMISSION_INVALID = "budget_admission_invalid"


def _require_hex(value: Any, what: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        raise ExtractionError(
            f"{what} must be 64 lowercase hex characters",
            reason_code="budget_meter_protocol_invalid",
        )
    return value


def _require_text(value: Any, what: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ExtractionError(
            f"{what} must be a non-blank string",
            reason_code="budget_meter_protocol_invalid",
        )
    return value


def _require_cap(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ExtractionError(
            "a generate attempt cap is a positive integer",
            reason_code="budget_insufficient",
        )
    return value


def _derive_session_nonce(
    *, authorization_sha256: str, extraction_run_id: str, generate_attempt_cap: int
) -> str:
    """Derive the session nonce deterministically from what already binds the run.

    Deterministic, not sampled. ``uuid4`` or ``secrets`` would make two otherwise
    identical runs produce different artifacts, which is exactly the ambient
    nondeterminism this package excludes elsewhere by injecting ``code_commit``
    and ``run_created_at``.

    Six inputs, each already fixed before the session exists: the authorization's
    own digest, the run identity, the effective cap, and the three code-owned
    constants. No clock, no VCS, no network, no environment variable, and no
    credential is read to produce it.

    **Collision, stated exactly.** Two sessions collide only when the
    authorization digest and the ``extraction_run_id`` are both equal -- that is,
    when they are two sessions for the same run. Distinct runs carry distinct run
    identities and therefore distinct nonces. A caller that reuses one
    ``extraction_run_id`` for two runs does get one nonce twice; that caller is
    already violating run-identity uniqueness, and the reused run root is refused
    by ``_require_absent_run_root``. This is a bound, not a guarantee of global
    uniqueness, and it is not claimed as one.
    """
    payload = {
        "authorization_sha256": _require_hex(authorization_sha256, "authorization_sha256"),
        "budget_meter_identity": CANONICAL_BUDGET_METER_IDENTITY,
        "budget_meter_version": CANONICAL_BUDGET_METER_VERSION,
        "budget_policy_version": BUDGET_POLICY_VERSION,
        "extraction_run_id": _require_text(extraction_run_id, "extraction_run_id"),
        "generate_attempt_cap": _require_cap(generate_attempt_cap),
    }
    return sha256_bytes(canonical_json_bytes(payload))


@dataclass(frozen=True)
class CanonicalBudgetSession:
    """One run's admission authority. Constructed by the runner, never injected.

    Frozen: the cap and the nonce are decided once, before anything is spent, and
    a session that could be re-pointed mid-run would be a second source of truth
    for the identity the admission carries.
    """

    generate_attempt_cap: int
    session_nonce: str
    _admitted: list[str] = field(default_factory=list, repr=False, compare=False)

    def meter_identity(self) -> dict[str, str]:
        """Exactly two fields, both code-owned.

        The budget policy version is deliberately absent: it is not a property of
        a meter instance, and a third key here would be looked for by a validator
        loop that has no business deriving policy from identity.
        """
        return {
            "meter_identity": CANONICAL_BUDGET_METER_IDENTITY,
            "meter_version": CANONICAL_BUDGET_METER_VERSION,
        }

    def admit(
        self,
        *,
        measured_input_tokens: int,
        reserved_cost_microdollars: int,
        provider_request_digest: str,
    ) -> BudgetAdmission:
        """Mint the run's single admission.

        A second call **refuses**. The route is one countTokens send plus one
        generation admission by construction; a second admission would be a
        second ticket to generate, and the cap that bounds retries lives inside
        the admission rather than in a counter this session could increment.

        ``budget_admission_invalid`` is not a free choice of code: it is one of
        the three the terminal classifier maps onto
        ``pre_generation_invalid``/``budget_termination``. A new code would fall
        through to the provider branch and publish a provider reason for
        something the provider never did.
        """
        if self._admitted:
            raise ExtractionError(
                "this budget session has already admitted the run's single "
                "generation; a second admission is not available",
                reason_code=_ADMISSION_INVALID,
            )
        digest = _require_hex(provider_request_digest, "provider_request_digest")
        self._admitted.append(digest)
        return BudgetAdmission(
            measured_input_tokens=measured_input_tokens,
            reserved_cost_microdollars=reserved_cost_microdollars,
            generate_attempt_cap=self.generate_attempt_cap,
            provider_request_digest=digest,
            session_nonce=self.session_nonce,
        )


def build_budget_session(
    *,
    authorization_sha256: str,
    extraction_run_id: str,
    generate_attempt_cap: int,
) -> CanonicalBudgetSession:
    """Build the run's canonical session from three already-validated values.

    The authorization mapping is **not** a parameter. Everything the session
    needs from it -- the digest that identifies it, and the cap derived from its
    budget by ``resolve_attempt_cap_v2`` -- is passed as a value the caller has
    already checked, so no untrusted field can travel into the identity this
    session reports.
    """
    cap = _require_cap(generate_attempt_cap)
    return CanonicalBudgetSession(
        generate_attempt_cap=cap,
        session_nonce=_derive_session_nonce(
            authorization_sha256=authorization_sha256,
            extraction_run_id=extraction_run_id,
            generate_attempt_cap=cap,
        ),
    )
