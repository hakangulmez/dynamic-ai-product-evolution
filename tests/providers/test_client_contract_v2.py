"""The v2 client contract: shape, canonical projection order, and provenance.

The projection test is the one that matters most. An earlier draft of the schema
constrained ``generation_config_projection`` with ``items.enum`` plus
``uniqueItems``, which admits **every permutation** of the six names. A permuted
list serializes to different canonical bytes -- ``sort_keys`` orders mapping keys,
never list elements -- so two semantically identical contracts would have acquired
divergent SHA-256 digests, and an authorization pinning one of them would have
stopped matching the other. ``prefixItems`` with six ``const`` entries, exact
length, and ``items: false`` closes that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.extraction.provider_adapter import (
    PROVIDER_PROTOCOL_VERSION_V8,
    BudgetAdmission,
    ProviderRequest,
    client_contract_digest,
    provider_request_digest,
)
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes, sha256_bytes
from dynamic_ai_products.providers.client_contract import MODEL_PARAMETERS
from dynamic_ai_products.providers.client_contract_v2 import (
    EXTERNAL_REQUEST_MAX,
    GENERATION_CONFIG_PROJECTION,
    PROVIDER_PROTOCOL_VERSION_PIN_V2,
    build_client_contract_v2,
    build_operation_endpoints,
    resolve_effective_generate_cap,
)
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.retry_policy import RETRY_MAX_ATTEMPTS, TIMEOUT_DURATION
from dynamic_ai_products.providers.vertex_gemini_v2 import VertexGeminiProviderV2

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads(
    (ROOT / "schemas" / "extraction_provider_client_contract_v2.schema.json").read_bytes()
)
CANONICAL_ORDER = [
    "temperature",
    "top_p",
    "candidate_count",
    "max_output_tokens",
    "response_mime_type",
    "thinking_config",
]


def contract():
    return build_client_contract_v2(vertex_project="p-example")


def test_the_schema_is_a_valid_draft_2020_12_document():
    Draft202012Validator.check_schema(SCHEMA)


def test_the_builder_output_validates_against_the_committed_schema():
    assert list(Draft202012Validator(SCHEMA).iter_errors(contract())) == []


def test_the_released_v1_schema_is_untouched_by_this_increment():
    """The successor sits beside @0.1.0; it never edits it."""
    released = json.loads(
        (ROOT / "schemas" / "extraction_provider_client_contract.schema.json").read_bytes()
    )
    assert released["properties"]["contract"]["const"] == (
        "extraction_provider_client_contract@0.1.0"
    )
    assert "thinking_config" not in released["properties"]
    assert "thinking_config" not in released["properties"]["model_parameters"]["properties"]


# --- the seven projection cases ----------------------------------------------


def projection_schema():
    return SCHEMA["properties"]["generation_config_projection"]


@pytest.mark.parametrize(
    "value, valid",
    [
        (CANONICAL_ORDER, True),
        # A permutation: the exact hole the prior construction left open.
        (["thinking_config", *CANONICAL_ORDER[:5]], False),
        (CANONICAL_ORDER[:5], False),
        ([*CANONICAL_ORDER, "seed"], False),
        ([*CANONICAL_ORDER[:5], "temperature"], False),
        ([*CANONICAL_ORDER[:5], "tools"], False),
        ([], False),
    ],
)
def test_the_projection_admits_exactly_one_ordering(value, valid):
    errors = list(Draft202012Validator(projection_schema()).iter_errors(value))
    assert (errors == []) is valid


def test_a_permuted_projection_is_rejected_and_would_have_had_a_different_digest():
    """Both halves of the argument, in one test.

    The permutation is refused by the schema, and -- had it not been -- it would
    have produced a different canonical digest for a contract that means exactly
    the same thing. Showing the divergence is what makes the refusal load-bearing
    rather than merely tidy.
    """
    canonical = contract()
    permuted = dict(canonical)
    permuted["generation_config_projection"] = ["thinking_config", *CANONICAL_ORDER[:5]]

    assert list(Draft202012Validator(SCHEMA).iter_errors(permuted)) != []
    assert sha256_bytes(canonical_json_bytes(canonical)) != sha256_bytes(
        canonical_json_bytes(permuted)
    )
    # Same members, same meaning -- only the order differs.
    assert sorted(permuted["generation_config_projection"]) == sorted(CANONICAL_ORDER)


def test_the_builder_emits_the_canonical_order():
    assert list(GENERATION_CONFIG_PROJECTION) == CANONICAL_ORDER
    assert contract()["generation_config_projection"] == CANONICAL_ORDER


# --- constants and their bindings --------------------------------------------


def test_the_protocol_pin_is_re_derived_from_the_adapter():
    assert PROVIDER_PROTOCOL_VERSION_PIN_V2 == PROVIDER_PROTOCOL_VERSION_V8


def test_the_count_timeout_is_bound_to_the_generation_timeout():
    """A declared policy value, not a measurement -- and bound so it cannot drift."""
    built = contract()
    assert built["count_timeout_duration"] == built["timeout_duration"] == TIMEOUT_DURATION
    assert built["count_timeout_unit"] == built["timeout_unit"] == "milliseconds"


def test_structural_maxima_are_declared_and_the_effective_cap_only_narrows_them():
    built = contract()
    assert built["generate_retry_max_attempts"] == RETRY_MAX_ATTEMPTS == 3
    assert built["external_request_max"] == EXTERNAL_REQUEST_MAX == 4
    # The effective cap is derived from the authorization and may only be lower.
    assert resolve_effective_generate_cap(2) == 1
    assert resolve_effective_generate_cap(3) == 2
    assert resolve_effective_generate_cap(4) == 3
    assert resolve_effective_generate_cap(99) == 3
    for refused in (1, 0, -1, True, 2.0, None, "3"):
        with pytest.raises(ProviderError):
            resolve_effective_generate_cap(refused)


def test_model_parameters_stay_closed_and_thinking_lives_beside_them():
    built = contract()
    assert built["model_parameters"] == dict(MODEL_PARAMETERS)
    assert "thinking_config" not in built["model_parameters"]
    assert built["thinking_config"] == {"thinking_budget": 0}
    assert built["thinking_level_used"] is False
    assert built["include_thoughts_used"] is False


def test_the_wire_key_records_what_the_pinned_sdk_actually_sends():
    assert contract()["wire_thinking_budget_key"] == "thinking_budget"


def test_the_two_endpoints_share_one_model_base_and_differ_only_in_the_operation():
    endpoints = build_operation_endpoints(vertex_project="p-example")
    count, generate = endpoints["count_tokens"], endpoints["generate_content"]
    assert count.endswith(":countTokens")
    assert generate.endswith(":generateContent")
    assert count[: -len(":countTokens")] == generate[: -len(":generateContent")]
    for url in (count, generate):
        assert url.startswith("https://")
        assert "?" not in url and "#" not in url and "@" not in url


def test_a_malformed_project_or_model_is_refused():
    for project in ("", "X", "sh", "has space", "UPPER"):
        with pytest.raises(ProviderError):
            build_operation_endpoints(vertex_project=project)
    for model in ("", "a/b", "a:b", "a?b", "a b"):
        with pytest.raises(ProviderError):
            build_operation_endpoints(vertex_project="p-example", model_name=model)


def test_no_endpoint_literal_is_baked_into_the_builder():
    """The origin is composed; no real destination appears in the source."""
    source = (
        ROOT / "src" / "dynamic_ai_products" / "providers" / "client_contract_v2.py"
    ).read_text(encoding="utf-8")
    for line in source.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or '"""' in stripped:
            continue
        assert "://" not in stripped or 'https://"' in stripped


# --- the full provider-request identity ---------------------------------------
#
# ``rendered_contents_sha256`` alone is not an identity. Two runs can send
# byte-identical contents for different stages, under different prompts, from
# different input packets; an admission minted for one of them would have been
# spendable on any of the others, and the budget would have priced a request that
# was never made. Every test below changes exactly one field and expects a
# refusal *before* the factory, the client, the credentials or any send.

CONTENTS = "rendered document"


def _request(*, stage="product_extraction", prompt="a" * 64, packet="b" * 64):
    return ProviderRequest(
        stage=stage,
        rendered_contents=CONTENTS,
        rendered_contents_sha256=sha256_bytes(CONTENTS.encode("utf-8")),
        prompt_sha256=prompt,
        input_packet_sha256=packet,
    )


class _FactoryTripwire:
    """Any use of the client factory is a failure: the refusal must precede it."""

    def __init__(self):
        self.opened = 0

    def __call__(self, **_kwargs):  # pragma: no cover - reaching it is the bug
        self.opened += 1
        raise AssertionError("the factory was reached despite a mismatched admission")


def _connector(tripwire):
    endpoints = build_operation_endpoints(vertex_project="p-example")
    allowlist = (endpoints["count_tokens"], endpoints["generate_content"])
    provider = VertexGeminiProviderV2(
        vertex_project="p-example",
        expected_authorization_sha256="9" * 64,
        max_provider_requests=3,
        endpoint_allowlist=allowlist,
        client_factory=tripwire,
    )
    provider.assert_run_permitted(
        authorization_sha256="9" * 64,
        endpoint_allowlist=allowlist,
        enablement_endpoint_allowlist=allowlist,
    )
    return provider


def _admission(provider, request, *, contract_sha=None, protocol=None):
    digest = provider_request_digest(
        request,
        provider_client_contract_sha256=(
            contract_sha
            if contract_sha is not None
            else client_contract_digest(provider.client_contract())
        ),
        protocol_version=protocol if protocol is not None else PROVIDER_PROTOCOL_VERSION_V8,
    )
    return BudgetAdmission(
        measured_input_tokens=10,
        reserved_cost_microdollars=1,
        generate_attempt_cap=1,
        provider_request_digest=digest,
        session_nonce="nonce",
    )


def _sink(**_kwargs):  # pragma: no cover - never reached in these tests
    raise AssertionError("the sink was reached despite a mismatched admission")


@pytest.mark.parametrize(
    "minted_for, presented_with",
    [
        (dict(stage="product_extraction"), dict(stage="task_extraction")),
        (dict(prompt="a" * 64), dict(prompt="c" * 64)),
        (dict(packet="b" * 64), dict(packet="d" * 64)),
    ],
)
def test_an_admission_minted_for_one_request_is_refused_for_another(
    minted_for, presented_with
):
    """The rendered contents are identical in every one of these pairs."""
    tripwire = _FactoryTripwire()
    provider = _connector(tripwire)
    minted = _request(**minted_for)
    presented = _request(**presented_with)
    assert minted.rendered_contents_sha256 == presented.rendered_contents_sha256
    admission = _admission(provider, minted)
    with pytest.raises(ProviderError) as caught:
        provider.complete_v8(presented, admission=admission, sink=_sink)
    assert caught.value.reason_code == "live_call_not_authorized"
    assert tripwire.opened == 0


def test_a_client_contract_mismatch_refuses_before_the_factory():
    tripwire = _FactoryTripwire()
    provider = _connector(tripwire)
    request = _request()
    admission = _admission(provider, request, contract_sha="e" * 64)
    with pytest.raises(ProviderError) as caught:
        provider.complete_v8(request, admission=admission, sink=_sink)
    assert caught.value.reason_code == "live_call_not_authorized"
    assert tripwire.opened == 0


def test_a_protocol_version_mismatch_refuses_before_the_factory():
    tripwire = _FactoryTripwire()
    provider = _connector(tripwire)
    request = _request()
    admission = _admission(provider, request, protocol="extraction_provider_protocol_v7")
    with pytest.raises(ProviderError) as caught:
        provider.complete_v8(request, admission=admission, sink=_sink)
    assert caught.value.reason_code == "live_call_not_authorized"
    assert tripwire.opened == 0


def test_a_matching_admission_gets_past_the_identity_check():
    """The refusals above are the identity rule, not a blanket refusal.

    A matching admission reaches the factory -- which is where this tripwire
    stops it, offline. Reaching the factory is the whole point.
    """
    tripwire = _FactoryTripwire()
    provider = _connector(tripwire)
    request = _request()
    admission = _admission(provider, request)
    with pytest.raises(AssertionError, match="factory was reached"):
        provider.complete_v8(request, admission=admission, sink=_sink)
    assert tripwire.opened == 1


def test_the_identity_is_never_the_rendered_contents_alone():
    request = _request()
    contract_sha = client_contract_digest(build_client_contract_v2(vertex_project="p-example"))
    digest = provider_request_digest(
        request,
        provider_client_contract_sha256=contract_sha,
        protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
    )
    assert digest != request.rendered_contents_sha256
    assert digest != contract_sha


def test_every_identity_field_changes_the_digest():
    contract_sha = client_contract_digest(build_client_contract_v2(vertex_project="p-example"))
    base = provider_request_digest(
        _request(),
        provider_client_contract_sha256=contract_sha,
        protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
    )
    variants = [
        provider_request_digest(
            _request(stage="task_extraction"),
            provider_client_contract_sha256=contract_sha,
            protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
        ),
        provider_request_digest(
            _request(prompt="c" * 64),
            provider_client_contract_sha256=contract_sha,
            protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
        ),
        provider_request_digest(
            _request(packet="d" * 64),
            provider_client_contract_sha256=contract_sha,
            protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
        ),
        provider_request_digest(
            _request(),
            provider_client_contract_sha256="e" * 64,
            protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
        ),
        provider_request_digest(
            _request(),
            provider_client_contract_sha256=contract_sha,
            protocol_version="extraction_provider_protocol_v7",
        ),
    ]
    assert len(set(variants) | {base}) == 6, "each identity field must move the digest"


def test_no_model_or_config_field_is_restated_beside_the_contract_digest():
    """The client-contract SHA is their single bound identity.

    Changing any model or configuration value changes that digest, and therefore
    the request digest, without any of those values appearing twice.
    """
    contract_sha = client_contract_digest(build_client_contract_v2(vertex_project="p-example"))
    other = build_client_contract_v2(vertex_project="p-example")
    other["model_parameters"] = {**other["model_parameters"], "max_output_tokens": 4096}
    assert client_contract_digest(other) != contract_sha
    request = _request()
    assert provider_request_digest(
        request,
        provider_client_contract_sha256=contract_sha,
        protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
    ) != provider_request_digest(
        request,
        provider_client_contract_sha256=client_contract_digest(other),
        protocol_version=PROVIDER_PROTOCOL_VERSION_V8,
    )


def test_the_admission_is_still_one_shot():
    tripwire = _FactoryTripwire()
    provider = _connector(tripwire)
    request = _request()
    admission = _admission(provider, request)
    assert admission.spent is False
    with pytest.raises(AssertionError, match="factory was reached"):
        provider.complete_v8(request, admission=admission, sink=_sink)
    assert admission.spent is True
    # A second presentation cannot spend it again -- and the permit is gone too.
    with pytest.raises(ProviderError) as caught:
        provider.complete_v8(request, admission=admission, sink=_sink)
    assert caught.value.reason_code == "live_call_not_authorized"
    assert tripwire.opened == 1


def test_the_canonical_serializer_is_the_repository_one():
    """One serialization rule, not two that happen to agree today."""
    payload = {"b": 2, "a": 1, "nested": {"z": 0, "y": [1, 2]}}
    assert client_contract_digest(payload) == sha256_bytes(canonical_json_bytes(payload))
