"""The canonical routing contract (ADR-048, G3-3).

Two things are being proved here, and they are different things.

**That the digest describes the route.** The projection is closed and its exact
contents are pinned by an independent re-derivation, so a key that is added,
removed, renamed, or sourced from somewhere else breaks a test rather than
silently changing what an enablement's pin means.

**That the producer is safe to call without a runner.** G4 materialization will
call :func:`derive_routing_contract` directly to mint the pin an enablement
record carries. On that path nothing has validated the contract first, so the
producer's own refusals are the only ones there are. Those refusals are driven
here with real contracts from the provider builders, not with hand-written
stand-ins that could drift from what executes.

Nothing here touches a network, an SDK, ADC, or the filesystem beyond reading
this repository's own source.
"""

from __future__ import annotations

import pytest

from dynamic_ai_products.extraction import routing_contract as routing_contract_module
from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.extraction.routing_contract import (
    ROUTING_CONTRACT_ID,
    derive_routing_contract,
    validate_routing_contract,
)
from dynamic_ai_products.providers.client_contract import build_client_contract
from dynamic_ai_products.providers.client_contract_v2 import build_client_contract_v2

PROJECT = "my-research-project"


def _v2_contract() -> dict:
    return build_client_contract_v2(vertex_project=PROJECT)


def _derived() -> dict:
    return derive_routing_contract(client_contract=_v2_contract())


# --- the public surface ------------------------------------------------------


def test_the_projection_builder_is_not_public():
    """A caller able to assemble its own projection could mint a digest the
    runner never bound, and it would look exactly like provenance."""
    assert routing_contract_module.__all__ == [
        "ROUTING_CONTRACT_ID",
        "derive_routing_contract",
        "validate_routing_contract",
    ]
    assert "_routing_projection" not in routing_contract_module.__all__


def test_the_producer_cannot_be_handed_the_artifact_it_will_be_compared_with():
    """ADR-047's lesson, applied to the route.

    If ``derive_routing_contract`` accepted the enablement, the digest could be
    derived from the very record it is checked against. The parameter does not
    exist, so the tautology is unrepresentable rather than merely avoided.
    """
    import inspect

    parameters = inspect.signature(derive_routing_contract).parameters
    assert set(parameters) == {"client_contract"}
    with pytest.raises(TypeError):
        derive_routing_contract(  # type: ignore[call-arg]
            client_contract=_v2_contract(), enablement={}
        )


# --- what the digest is taken over -------------------------------------------


def test_the_digest_equals_an_independently_assembled_nine_key_projection():
    """The load-bearing test: the projection's exact contents.

    The mapping below is written out here on purpose rather than imported. If a
    key is added, removed, renamed, or starts being read from a different place,
    this equality breaks -- which is the only way a closed projection can be
    kept closed.
    """
    contract = _v2_contract()
    expected_projection = {
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
    assert len(expected_projection) == 9
    expected = sha256_bytes(canonical_json_bytes(expected_projection))
    assert derive_routing_contract(client_contract=contract) == {
        "routing_contract_id": ROUTING_CONTRACT_ID,
        "routing_contract_sha256": expected,
    }


def test_the_digest_is_deterministic_across_calls_and_key_order():
    """No clock, no randomness, and ``sort_keys`` makes spelling order irrelevant."""
    first = _derived()["routing_contract_sha256"]
    second = _derived()["routing_contract_sha256"]
    assert first == second
    shuffled = dict(reversed(list(_v2_contract().items())))
    assert (
        derive_routing_contract(client_contract=shuffled)["routing_contract_sha256"]
        == first
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param("api_version", "v1beta1", id="api_version"),
        pytest.param("endpoint_match_mode", "prefix", id="endpoint_match_mode"),
        pytest.param("endpoint_query_policy", "allow", id="endpoint_query_policy"),
        pytest.param("protocol_switch_policy", "follow", id="protocol_switch_policy"),
        pytest.param(
            "retry_policy_version", "other_retry_v1", id="retry_policy_version"
        ),
        pytest.param(
            "rate_limit_policy_version", "other_rate_v1", id="rate_limit_policy_version"
        ),
    ],
)
def test_every_varyable_projection_field_changes_the_digest(field, value):
    """Six of the nine keys, each varied on its own."""
    baseline = _derived()["routing_contract_sha256"]
    contract = _v2_contract()
    contract[field] = value
    assert derive_routing_contract(client_contract=contract)[
        "routing_contract_sha256"
    ] != baseline


def test_a_different_deployment_changes_the_digest_through_its_endpoints():
    """The seventh key: ``operation_endpoints``.

    Varied the way a real difference would arrive -- a different project -- not
    by editing the mapping by hand. This is also why ``vertex_project`` is not a
    projection key of its own: it is already inside both URLs, and a value that
    lives in two places can drift in one of them.
    """
    baseline = _derived()["routing_contract_sha256"]
    other = derive_routing_contract(
        client_contract=build_client_contract_v2(vertex_project="another-real-project")
    )
    assert other["routing_contract_sha256"] != baseline


def test_the_eighth_key_cannot_be_varied_and_is_covered_by_the_re_derivation():
    """``client_contract_id`` is honestly stated rather than pretend-tested.

    It is pinned by the identity gate, so no accepted contract can carry a
    different value and there is no mutation that exercises it here. Its presence
    in the digest is established by
    ``test_the_digest_equals_an_independently_assembled_nine_key_projection``,
    which would break if the key were dropped. This test records that the
    coverage argument is deliberate.
    """
    contract = _v2_contract()
    contract["contract"] = "extraction_provider_client_contract@0.1.0"
    with pytest.raises(ExtractionError) as caught:
        derive_routing_contract(client_contract=contract)
    assert caught.value.reason_code == "client_contract_invalid"


def test_the_code_owned_route_identity_participates_in_the_digest(monkeypatch):
    """The ninth key, which no contract mutation can reach.

    ``ROUTING_CONTRACT_ID`` is a module constant, so the only controlled way to
    observe its participation is to patch it and re-derive. This works **only**
    because ``_routing_projection`` reads the module-level name at call time; if
    it were ever captured in a default argument or copied at import, this test
    would pass for the wrong reason -- so it also asserts the returned identity
    changed, which a frozen copy could not do.
    """
    baseline = _derived()
    monkeypatch.setattr(
        routing_contract_module, "ROUTING_CONTRACT_ID", "sentinel_route@0.0.0"
    )
    patched = _derived()
    assert patched["routing_contract_id"] == "sentinel_route@0.0.0"
    assert patched["routing_contract_sha256"] != baseline["routing_contract_sha256"]


def test_a_field_outside_the_projection_does_not_change_the_digest():
    """Closed means closed in both directions.

    ``thinking_config`` is a real v2 property and is deliberately not part of the
    route. Its protection is the contract digest the authorization pins.
    """
    contract = _v2_contract()
    baseline = derive_routing_contract(client_contract=contract)[
        "routing_contract_sha256"
    ]
    contract["thinking_config"] = {"thinking_budget": 512}
    assert (
        derive_routing_contract(client_contract=contract)["routing_contract_sha256"]
        == baseline
    )


def _respelled_contract() -> dict:
    """The same destination, spelled with a different host case.

    ``providers.endpoint_grammar_v2`` normalizes host case before comparing and
    would treat this as one endpoint. This module does not, and the two tests
    below state exactly what that does and does not mean.
    """
    respelled = _v2_contract()
    respelled["operation_endpoints"]["count_tokens"] = respelled["operation_endpoints"][
        "count_tokens"
    ].replace("us-central1-aiplatform", "US-CENTRAL1-aiplatform", 1)
    return respelled


def test_two_spellings_of_one_endpoint_produce_two_digests():
    """The declared limit: a byte binding, not a grammar binding.

    ``extraction`` may not import ``providers.endpoint_grammar_v2`` and does not
    re-implement it, so a host-case variant the connector's normalizer would
    collapse is a different digest here. This asserts the digest difference only
    -- what it leads to is the next two tests.
    """
    baseline = _derived()["routing_contract_sha256"]
    assert (
        derive_routing_contract(client_contract=_respelled_contract())[
            "routing_contract_sha256"
        ]
        != baseline
    )


def test_a_respelled_route_pinned_to_its_own_digest_is_accepted():
    """A different digest is not, by itself, a refusal.

    This module compares digests and holds no opinion about which spelling is
    canonical. An enablement minted from the respelled contract matches it and
    the run proceeds. Claiming otherwise would describe a deduplication this
    module does not perform.
    """
    respelled = _respelled_contract()
    validate_routing_contract(
        enablement=dict(derive_routing_contract(client_contract=respelled)),
        client_contract=respelled,
    )


def test_a_respelled_route_under_a_pin_minted_from_the_other_spelling_is_refused():
    """What the binding actually protects against.

    The pin already exists and was minted from the canonical spelling; the run
    now executes the respelled one. The digests differ and the run stops. That is
    the real property: a route may not change underneath a fixed governance pin.
    """
    with pytest.raises(ExtractionError) as caught:
        validate_routing_contract(
            enablement=_enablement(), client_contract=_respelled_contract()
        )
    assert caught.value.reason_code == "routing_contract_mismatch"


# --- the G4 direct-call guarantee --------------------------------------------


@pytest.mark.parametrize(
    ("field", "value"),
    [
        pytest.param(
            "contract", "extraction_provider_client_contract@0.1.0", id="v1-identity"
        ),
        pytest.param("contract", "some_other_contract@9.9.9", id="foreign-identity"),
        pytest.param("schema_version", "0.1.0", id="v1-schema-version"),
        pytest.param("schema_version", "9.9.9", id="foreign-schema-version"),
    ],
)
def test_the_producer_refuses_a_non_v2_surface_on_a_direct_call(field, value):
    """No runner is involved on the G4 path, so the producer checks for itself."""
    contract = _v2_contract()
    contract[field] = value
    with pytest.raises(ExtractionError) as caught:
        derive_routing_contract(client_contract=contract)
    assert caught.value.reason_code == "client_contract_invalid"


def test_a_real_v1_contract_is_refused_rather_than_partially_projected():
    """The concrete accident this guards against.

    A v1 contract has no ``operation_endpoints``, no ``endpoint_match_mode`` and
    no ``protocol_switch_policy``. Projected unchecked it would raise
    ``KeyError`` at best; at worst some future partial mapping would hash
    cleanly into a digest describing a route nobody can execute.
    """
    with pytest.raises(ExtractionError) as caught:
        derive_routing_contract(
            client_contract=build_client_contract(vertex_project=PROJECT)
        )
    assert caught.value.reason_code == "client_contract_invalid"


def test_a_real_v2_contract_from_the_provider_builder_is_accepted():
    """The path G4 will actually take, driven end to end."""
    derived = derive_routing_contract(client_contract=_v2_contract())
    assert derived["routing_contract_id"] == ROUTING_CONTRACT_ID
    assert len(derived["routing_contract_sha256"]) == 64
    assert derived["routing_contract_sha256"] == derived[
        "routing_contract_sha256"
    ].lower()
    assert set(derived["routing_contract_sha256"]) <= set("0123456789abcdef")


# --- the binder --------------------------------------------------------------


def _enablement(**overrides) -> dict:
    base = dict(_derived())
    base.update(overrides)
    return base


def test_an_enablement_that_pins_this_route_is_accepted():
    validate_routing_contract(enablement=_enablement(), client_contract=_v2_contract())


def test_an_enablement_naming_a_different_route_identity_is_refused():
    with pytest.raises(ExtractionError) as caught:
        validate_routing_contract(
            enablement=_enablement(routing_contract_id="vertex_gemini_route@0.1.0"),
            client_contract=_v2_contract(),
        )
    assert caught.value.reason_code == "routing_contract_mismatch"


def test_the_placeholder_digest_that_used_to_satisfy_the_suite_is_now_refused():
    """Before ADR-048 nothing produced this digest, so ``"4" * 64`` passed.

    That is the gap this increment closes, and it is asserted directly so the
    closure cannot regress into a comment.
    """
    with pytest.raises(ExtractionError) as caught:
        validate_routing_contract(
            enablement=_enablement(routing_contract_sha256="4" * 64),
            client_contract=_v2_contract(),
        )
    assert caught.value.reason_code == "routing_contract_mismatch"


def test_an_enablement_pinned_to_a_different_deployment_is_refused():
    """The digest binds a real difference, not just a typo.

    The enablement pins the route of one project; the run executes another.
    Everything else about the two contracts is identical.
    """
    other = derive_routing_contract(
        client_contract=build_client_contract_v2(vertex_project="another-real-project")
    )
    with pytest.raises(ExtractionError) as caught:
        validate_routing_contract(
            enablement=_enablement(
                routing_contract_sha256=other["routing_contract_sha256"]
            ),
            client_contract=_v2_contract(),
        )
    assert caught.value.reason_code == "routing_contract_mismatch"


def test_identity_is_reported_before_digest_when_both_are_wrong():
    """A run pointed at an entirely different route should say so.

    Both fields are wrong here; the identity mismatch is the more specific
    statement and is the one raised.
    """
    with pytest.raises(ExtractionError) as caught:
        validate_routing_contract(
            enablement=_enablement(
                routing_contract_id="vertex_gemini_route@0.1.0",
                routing_contract_sha256="4" * 64,
            ),
            client_contract=_v2_contract(),
        )
    assert caught.value.reason_code == "routing_contract_mismatch"
    assert "route identity" in str(caught.value)


def test_the_binder_refuses_a_non_v2_contract_before_comparing_anything():
    with pytest.raises(ExtractionError) as caught:
        validate_routing_contract(
            enablement=_enablement(),
            client_contract=build_client_contract(vertex_project=PROJECT),
        )
    assert caught.value.reason_code == "client_contract_invalid"
