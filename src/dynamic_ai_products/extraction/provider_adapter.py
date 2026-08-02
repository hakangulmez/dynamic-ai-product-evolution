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

import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Protocol, runtime_checkable

from .errors import ExtractionError

__all__ = [
    "PROVIDER_PROTOCOL_VERSION",
    "PROVIDER_PROTOCOL_VERSION_V8",
    "BudgetAdmission",
    "BudgetMeter",
    "BudgetSession",
    "CaptureRecord",
    "CaptureSink",
    "CaptureSinkError",
    "ExtractionProvider",
    "ExtractionProviderV8",
    "ProviderRequest",
    "ProviderResponse",
    "require_budget_meter",
    "client_contract_digest",
    "provider_request_digest",
    "require_provider",
    "require_provider_v8",
]

_SHA256_LOWER_RE = re.compile(r"^[0-9a-f]{64}$")

PROVIDER_PROTOCOL_VERSION = "extraction_provider_protocol_v7"

# ADR-043 (E-M). v8 is declared **alongside** v7 rather than replacing its value.
# ``extraction_provider_client_contract@0.1.0`` is released and its instances are
# hash-pinned by existing governance artifacts; rewriting the shared constant
# would silently change every one of those digests. v7 keeps meaning what it
# meant, and only the v2 contract declares v8.
PROVIDER_PROTOCOL_VERSION_V8 = "extraction_provider_protocol_v8"


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


class CaptureSinkError(Exception):
    """A runner-owned persistence failure, raised inside the provider seam.

    This type exists so that one specific failure cannot be laundered into a
    provider failure. Measured on the released connector: an ``ExtractionError``
    raised from inside the retry wrapper leaves it as
    ``ProviderError('provider_response_unusable', attempt_count=1)`` — the
    original reason survives only in ``__context__``, while the boundary reads
    ``reason_code`` off the raised object. A filesystem failure would therefore
    have been recorded as a provider failure, and ``provider_response_unusable``
    is a **valid** member of the released provider-error enum, so nothing would
    have flagged it.

    It carries the sanitized provider reason alongside its own, because the two
    can be true at once: an attempt may fail on the provider's side *and* then
    fail to persist. Neither masks the other, and no upstream text or response
    byte has a channel into this object — the fields are closed codes and
    integers.
    """

    def __init__(
        self,
        *,
        operation_label: str,
        attempt_ordinal: int,
        persistence_reason_code: str,
        provider_reason_code: str | None = None,
    ) -> None:
        super().__init__("a captured response body could not be persisted")
        self.operation_label = operation_label
        self.attempt_ordinal = attempt_ordinal
        self.persistence_reason_code = persistence_reason_code
        self.provider_reason_code = provider_reason_code


@dataclass(frozen=True)
class CaptureRecord:
    """What the connector returns about one attempt: digests, never bytes.

    The bytes travel connector -> sink in one direction and one hop; the return
    path carries only what a record can hold. ``raw_reference`` and
    ``raw_sha256`` are absent unless the sink actually wrote something, so a
    zero-length body cannot acquire a valid-looking digest.
    """

    operation_label: str
    attempt_ordinal: int
    send_outcome: str
    sdk_call_outcome: str
    capture_disposition: str
    raw_reference: str | None = None
    raw_sha256: str | None = None
    byte_count: int | None = None
    provider_reason_code: str | None = None
    persistence_reason_code: str | None = None


class _OneShot:
    """A single-use gate. Frozen dataclasses cannot flip their own fields."""

    __slots__ = ("_spent",)

    def __init__(self) -> None:
        self._spent = False

    def spend(self) -> None:
        if self._spent:
            raise ExtractionError(
                "a budget admission may be spent exactly once",
                reason_code="budget_admission_invalid",
            )
        self._spent = True

    @property
    def spent(self) -> bool:
        return self._spent


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    """The one canonical serialization: sorted keys, compact, trailing newline.

    Byte-identical to ``raw_artifacts.canonical_json_bytes`` by contract, and a
    test pins the two together. It is spelled out here rather than imported so
    that this shared surface keeps depending on nothing but its own errors.
    """
    return (
        json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
    ).encode("utf-8")


def client_contract_digest(contract: dict[str, Any]) -> str:
    """The digest of a client contract, computed the one canonical way.

    Both sides of the admission need this number and neither may invent its own
    serialization: a runner and a connector that hashed the same mapping
    differently would disagree about identity while both being "correct".
    """
    if not isinstance(contract, dict):
        raise ExtractionError(
            "a client contract must be a mapping", reason_code="client_contract_invalid"
        )
    return sha256(_canonical_bytes(contract)).hexdigest()


def provider_request_digest(
    request: "ProviderRequest",
    *,
    provider_client_contract_sha256: str,
    protocol_version: str,
) -> str:
    """The full identity of one authorized provider request.

    ``rendered_contents_sha256`` alone is **not** an identity. Two runs can send
    byte-identical contents for different stages, under different prompts, from
    different input packets -- an admission minted for one of them would be
    spendable on any of the others, and the budget would have priced a request
    that was never made.

    Six values, and no more. The four request fields say what is being asked; the
    client-contract digest is the single bound identity of the model, its
    parameters, the endpoints, the timeouts and the retry policy, so restating
    any of those individually would be a second, driftable copy; the protocol
    version says which contract the two sides are speaking.
    """
    if not isinstance(request, ProviderRequest):
        raise ExtractionError(
            "a provider request is required to derive its digest",
            reason_code="provider_protocol_invalid",
        )
    if not isinstance(provider_client_contract_sha256, str) or not _SHA256_LOWER_RE.fullmatch(
        provider_client_contract_sha256
    ):
        raise ExtractionError(
            "provider_client_contract_sha256 must be 64 lowercase hex characters",
            reason_code="client_contract_invalid",
        )
    if not isinstance(protocol_version, str) or not protocol_version:
        raise ExtractionError(
            "a protocol version is required to derive a request digest",
            reason_code="provider_protocol_invalid",
        )
    payload = {
        "stage": request.stage,
        "rendered_contents_sha256": request.rendered_contents_sha256,
        "prompt_sha256": request.prompt_sha256,
        "input_packet_sha256": request.input_packet_sha256,
        "provider_client_contract_sha256": provider_client_contract_sha256,
        "provider_protocol_version": protocol_version,
    }
    return sha256(_canonical_bytes(payload)).hexdigest()


@dataclass(frozen=True)
class BudgetAdmission:
    """One measured, single-use permission to make the generation call.

    Bound to the exact request it was issued for and to the session that issued
    it, so an admission cannot be carried across runs or reused for a different
    request. ``provider_request_digest`` is the **full** identity -- stage,
    contents, prompt, packet, client contract and protocol version -- not the
    rendered contents alone, which two different requests can share. ``generate_attempt_cap`` is the run's **effective** cap, derived
    from the authorization; the connector's structural maximum is separate and
    may only be narrowed by it.
    """

    measured_input_tokens: int
    reserved_cost_microdollars: int
    generate_attempt_cap: int
    provider_request_digest: str
    session_nonce: str
    gate: _OneShot = field(default_factory=_OneShot, repr=False, compare=False)

    def spend(self) -> None:
        self.gate.spend()

    @property
    def spent(self) -> bool:
        return self.gate.spent


@runtime_checkable
class CaptureSink(Protocol):
    """The runner's write-once persistence callback, called inside the seam.

    It is invoked after every attempt and **before** the next send, so a
    persistence failure stops the loop while there is still a loop to stop. It
    returns the record the runner will publish; the connector never learns where
    the bytes went beyond the reference in that record.
    """

    def __call__(
        self,
        *,
        operation_label: str,
        attempt_ordinal: int,
        raw_bytes: bytes | None,
        send_outcome: str,
        sdk_call_outcome: str,
        provider_reason_code: str | None,
    ) -> CaptureRecord:  # pragma: no cover
        ...


@runtime_checkable
class BudgetSession(Protocol):
    """The v8 metering seam: admission on a **measured** input count.

    ``BudgetMeter.assert_within_budget`` had no channel for a measured token
    count, so a meter had to estimate the input it was metering. ``admit``
    receives the number the provider itself reported, reconciled against the
    archived bytes.

    It also receives the **reserve** the runner computed from that number:
    ``cap x (ceil(input x 3/10) + ceil(max_output_tokens x 5/2))``. Without it a
    meter would have to re-derive the pricing rule to apply
    ``budget_max_estimated_cost_micros`` at all, and two copies of that rule
    could disagree. The runner enforces the ceiling itself as well -- the meter
    is injected, so a fail-closed gate cannot depend on the meter behaving.
    """

    def meter_identity(self) -> dict[str, str]:  # pragma: no cover
        ...

    def admit(
        self,
        *,
        measured_input_tokens: int,
        reserved_cost_microdollars: int,
        provider_request_digest: str,
    ) -> BudgetAdmission:  # pragma: no cover
        ...


@runtime_checkable
class ExtractionProviderV8(Protocol):
    """The two-operation provider surface (ADR-043).

    ``count_tokens`` returns raw capture records only: it interprets no number.
    Deriving the token count from the archived bytes, and reconciling it against
    the SDK's own witness, belongs to the runner — a connector that returned a
    parsed integer would be the only thing that had seen the bytes.

    ``complete`` requires a verified, single-use admission. One authorization
    buys one generation call, and the admission is spent before any factory,
    SDK, credential or network work begins.
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

    def count_tokens(
        self, request: ProviderRequest, *, sink: CaptureSink
    ) -> tuple[CaptureRecord, int | None]:  # pragma: no cover
        ...

    def complete_v8(
        self, request: ProviderRequest, *, admission: BudgetAdmission, sink: CaptureSink
    ) -> tuple[ProviderResponse, tuple[CaptureRecord, ...]]:  # pragma: no cover
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


def require_provider_v8(provider: object) -> ExtractionProviderV8:
    """Fail closed unless an injected object satisfies the **v8** protocol.

    A separate gate rather than a widened one. ``ExtractionProvider`` requires
    ``complete``; a two-operation connector has ``count_tokens`` and
    ``complete_v8`` instead, so a single protocol that accepted either would let
    a single-operation connector drive a route that must measure before it
    generates -- and the measurement would simply never happen.
    """
    if provider is None:
        raise ExtractionError(
            "an extraction provider must be injected; this package constructs none",
            reason_code="provider_required",
        )
    if not isinstance(provider, ExtractionProviderV8):
        raise ExtractionError(
            "injected provider does not satisfy the two-operation provider protocol",
            reason_code="provider_protocol_invalid",
        )
    return provider


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
