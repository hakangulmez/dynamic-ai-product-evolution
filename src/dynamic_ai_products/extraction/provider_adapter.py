"""Provider protocol and injection point (ADR-033, E-A).

**E-A carries no network capability whatsoever.** This module declares the
typed surface a provider must satisfy and nothing else: no vendor SDK, no
credential handling, no environment-secret read, no transport construction,
and no call. The concrete connector, model label, parameters, credentials,
and client-contract identity belong to the separately locked E-P increment.

Offline tests satisfy this protocol with an injected fake. The E-P Vertex
connector satisfies it too, but refuses unconditionally in both
``assert_run_permitted`` and ``complete``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, Protocol, runtime_checkable

from .errors import ExtractionError

__all__ = [
    "PROVIDER_PROTOCOL_VERSION",
    "ProviderRequest",
    "ProviderResponse",
    "BudgetMeter",
    "ExtractionProvider",
    "require_budget_meter",
    "require_provider",
]

_SHA256_LOWER_RE = re.compile(r"^[0-9a-f]{64}$")

PROVIDER_PROTOCOL_VERSION = "extraction_provider_protocol_v7"


@dataclass(frozen=True)
class ProviderRequest:
    """One extraction request as seen by a provider.

    ``rendered_contents`` is the **sole** provider-input authority (ADR-036,
    E-R). ``prompt_text`` and ``payload`` are deliberately absent rather than
    merely unused: before E-R the connector sent ``prompt_text`` and the packet
    payload was never transmitted at all, so a live call handed the model a
    template still carrying literal placeholders. Keeping either field would
    leave a second, divergent authority from which a connector could rebuild its
    own representation. With the fields removed, that is structurally impossible.

    ``prompt_sha256`` remains the digest of the **raw frozen template** bytes and
    is provenance only; ``rendered_contents_sha256`` is the digest of what is
    actually sent. The two are different values by construction.
    """

    stage: str
    rendered_contents: str
    rendered_contents_sha256: str
    prompt_sha256: str
    input_packet_sha256: str

    def __post_init__(self) -> None:
        """Bind the digest to the bytes at construction, not by convention.

        Without this a request could carry real contents and a fabricated digest:
        the connector would send the contents anyway, the meter would measure
        them, and every artifact would record a digest that matches nothing. The
        check runs before the request can reach meter admission, ``mkdir``, the
        SDK factory or the provider, so a mismatch costs zero artifacts.

        Neither digest is reported. A hex digest is not secret, but the boundary
        has no channel for unexpected values and gains nothing from one.
        """
        if not isinstance(self.rendered_contents, str) or not self.rendered_contents:
            raise ExtractionError(
                "rendered_contents must be a non-empty string",
                reason_code="provider_protocol_invalid",
            )
        declared = self.rendered_contents_sha256
        if not isinstance(declared, str) or not _SHA256_LOWER_RE.fullmatch(declared):
            raise ExtractionError(
                "rendered_contents_sha256 must be 64 lowercase hex characters",
                reason_code="provider_protocol_invalid",
            )
        try:
            payload = self.rendered_contents.encode("utf-8")
        except UnicodeEncodeError as exc:  # pragma: no cover - str is always encodable
            raise ExtractionError(
                "rendered_contents must be UTF-8 encodable",
                reason_code="provider_protocol_invalid",
            ) from exc
        if sha256(payload).hexdigest() != declared:
            raise ExtractionError(
                "rendered_contents_sha256 does not match the rendered contents",
                reason_code="provider_protocol_invalid",
            )


@dataclass(frozen=True)
class ProviderResponse:
    """A provider's literal output plus the metadata the run manifest records."""

    raw_bytes: bytes
    model_provider: str
    model_name: str
    model_parameters: dict[str, Any]
    prompt_model_metadata: dict[str, Any]


@runtime_checkable
class ExtractionProvider(Protocol):
    """The only provider surface extraction knows about.

    ``assert_run_permitted`` exists so a refused run costs nothing: the
    orchestrator calls it **before** creating a run root, so an unauthorized
    run leaves no directory and no artifact behind. It carries both the verified
    authorization digest and both verified endpoint allowlists, so the authorized
    endpoints are execution-bound rather than merely recorded: a connector
    configured for a broader or different allowlist fails closed even with the
    correct digest.

    The two lists are forwarded rather than compared here on purpose. Endpoint
    normalization is provider-side grammar, and ``extraction`` may not import
    ``providers``; duplicating the grammar would create a second set of rules
    that could drift from the one the capture client actually applies. The
    connector enforces ``enablement ⊇ authorization == connector``.

    ``revoke_run_permission`` exists because a permit granted by
    ``assert_run_permitted`` outlives several later checks — the client contract,
    the qualification's execution contract, the prompt, the meter, the budget,
    the run root, and the artifact writes all come after it. Any of those may
    refuse, and without an explicit revocation the permit would stay live and a
    later ``complete`` could spend it. The orchestrator therefore revokes on
    every exit from the post-handshake region. Revocation must be **idempotent
    and infallible**: it performs no SDK, factory, credential, or network work,
    so a conforming provider has nothing that can fail.

    ``client_contract`` returns a plain mapping. Serialization and write-once
    persistence stay with the orchestrator, so the connector cannot assert a
    digest for bytes it did not have written.
    """

    def assert_run_permitted(
        self,
        *,
        authorization_sha256: str | None = None,
        endpoint_allowlist: tuple[str, ...] | None = None,
        enablement_endpoint_allowlist: tuple[str, ...] | None = None,
    ) -> None:  # pragma: no cover
        ...

    def revoke_run_permission(self) -> None:  # pragma: no cover
        ...

    def client_contract(self) -> dict[str, Any]:  # pragma: no cover
        ...

    def complete(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover
        ...


@runtime_checkable
class BudgetMeter(Protocol):
    """The budget-enforcement seam (SPEC-027 canonical runner).

    ``assert_within_budget`` receives the **exact** :class:`ProviderRequest`
    object that will be handed to the provider, so the prompt text, prompt
    digest, packet payload, and stage it meters are byte-for-byte the ones that
    are sent. Metering a copy would let the two drift.

    ``meter_identity`` returns ``{"meter_identity", "meter_version"}``. The
    runner compares it against the identity the authorization artifact pins.
    That enforces the expected operational identity; it does **not**
    structurally prevent an in-process implementation from imitating those
    values — see ``providers.authorization`` for the same limit stated for the
    connector handshake.
    """

    def meter_identity(self) -> dict[str, str]:  # pragma: no cover
        ...

    def assert_within_budget(
        self,
        *,
        request: ProviderRequest,
        max_output_tokens: int,
        budget: dict[str, Any],
    ) -> None:  # pragma: no cover
        ...


def require_budget_meter(meter: object) -> BudgetMeter:
    """Fail closed unless an injected object satisfies the meter protocol.

    Default-deny: with no meter, ``budget_max_input_tokens`` and
    ``budget_max_estimated_cost_micros`` cannot be checked at all, so the run is
    refused rather than run unmetered.
    """
    if meter is None:
        raise ExtractionError(
            "a budget meter must be injected; input-token and estimated-cost "
            "limits cannot be enforced without one",
            reason_code="budget_meter_unavailable",
        )
    if not isinstance(meter, BudgetMeter):
        raise ExtractionError(
            "injected budget meter does not satisfy the meter protocol",
            reason_code="budget_meter_protocol_invalid",
        )
    return meter


def require_provider(provider: object) -> ExtractionProvider:
    """Fail closed unless an injected object satisfies the protocol."""
    if provider is None:
        raise ExtractionError(
            "an extraction provider must be injected; this package constructs none",
            reason_code="provider_required",
        )
    if not isinstance(provider, ExtractionProvider):
        raise ExtractionError(
            "injected provider does not satisfy the extraction provider protocol",
            reason_code="provider_protocol_invalid",
        )
    return provider
