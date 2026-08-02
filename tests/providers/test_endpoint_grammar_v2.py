"""The exact two-operation endpoint grammar.

The released matcher is left in place and keeps its promise that query and
fragment take no part in the decision; every E-L and E-R receipt was produced
under it. These tests cover the successor grammar, and the first two of them are
the reason it exists at all: a prefix entry admits far more than it appears to,
and a stripped query is a query that was never refused.
"""

from __future__ import annotations

import pytest

from dynamic_ai_products.providers.client_contract_v2 import build_operation_endpoints
from dynamic_ai_products.providers.endpoint_grammar_v2 import (
    assert_operation_url,
    normalize_exact_endpoint,
    require_allowlist_equals_operations,
    require_operation_endpoints,
)
from dynamic_ai_products.extraction.provider_adapter import ProviderRequest
from dynamic_ai_products.extraction.raw_artifacts import sha256_bytes
from dynamic_ai_products.providers.authorization import require_endpoint_allowlist_match
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.response_capture import assert_endpoint_allowed
from dynamic_ai_products.providers.vertex_gemini_v2 import VertexGeminiProviderV2

ENDPOINTS = build_operation_endpoints(vertex_project="p-example")


def _grammar_request() -> ProviderRequest:
    contents = "rendered document"
    return ProviderRequest(
        stage="product_extraction",
        rendered_contents=contents,
        rendered_contents_sha256=sha256_bytes(contents.encode("utf-8")),
        prompt_sha256="a" * 64,
        input_packet_sha256="b" * 64,
    )


def _never_sink(**_kwargs):  # pragma: no cover - refused before it is reached
    raise AssertionError("the sink was reached")

COUNT = ENDPOINTS["count_tokens"]
GENERATE = ENDPOINTS["generate_content"]
MODEL_BASE = COUNT[: -len(":countTokens")]


def test_the_released_matcher_admits_far_more_than_a_prefix_looks_like():
    """Measured, and the reason exact equality replaces prefix descent."""
    prefix = ("https://us-central1-aiplatform.googleapis.com/v1/projects",)
    for url in (COUNT, GENERATE, f"{MODEL_BASE}:streamGenerateContent"):
        assert_endpoint_allowed(url, prefix)  # admitted by the released rule


def test_the_released_matcher_ignores_a_query_and_the_successor_does_not():
    assert_endpoint_allowed(GENERATE + "?alt=sse", (GENERATE,))  # admitted
    with pytest.raises(ProviderError):
        assert_operation_url(
            GENERATE + "?alt=sse", operation_label="generate_content", expected=GENERATE
        )


@pytest.mark.parametrize("label, url", [("count_tokens", COUNT), ("generate_content", GENERATE)])
def test_each_operation_admits_exactly_its_own_endpoint(label, url):
    assert_operation_url(url, operation_label=label, expected=url)


def test_the_two_operations_do_not_admit_each_other():
    """Allowlist membership cannot catch this: both are on the allowlist."""
    with pytest.raises(ProviderError):
        assert_operation_url(GENERATE, operation_label="count_tokens", expected=COUNT)
    with pytest.raises(ProviderError):
        assert_operation_url(COUNT, operation_label="generate_content", expected=GENERATE)


@pytest.mark.parametrize(
    "url",
    [
        GENERATE + "?alt=sse",
        GENERATE + "#fragment",
        GENERATE + "?x=1#y",
        GENERATE + "X",
        GENERATE + "/extra",
        GENERATE + "\n",
        GENERATE + " ",
        f"{MODEL_BASE}:streamGenerateContent",
        f"{MODEL_BASE}:predict",
        MODEL_BASE,
        COUNT.replace("https://", "http://"),
        COUNT.replace("https://", "https://user:pass@"),
        COUNT.replace("googleapis.com", "googleapis.com:8443"),
        COUNT.replace("/v1/", "/v1/../v1/"),
        COUNT.replace("/v1/", "/v1//"),
        COUNT.replace("p-example", "other-project"),
        COUNT.replace("us-central1-aiplatform", "europe-west4-aiplatform"),
        "",
        None,
        7,
    ],
)
def test_every_deviation_is_refused(url):
    with pytest.raises(ProviderError):
        assert_operation_url(url, operation_label="count_tokens", expected=COUNT)


def test_one_endpoint_written_two_ways_normalizes_to_one_pair():
    """Measured: ``urlsplit().hostname`` is already lower-cased, and an explicit
    ``:443`` collapses to the implicit port.

    Both are spellings of the same endpoint, so they must normalize together --
    that is precisely what makes the set-equality check on the allowlist mean
    anything. A host that is genuinely different still refuses.
    """
    origin, path = normalize_exact_endpoint(COUNT)
    assert origin.startswith("https://")
    assert path.startswith("/v1/projects/")
    assert normalize_exact_endpoint(COUNT.replace("aiplatform", "AIPLATFORM")) == (origin, path)
    assert normalize_exact_endpoint(
        COUNT.replace("googleapis.com", "googleapis.com:443")
    ) == (origin, path)
    assert normalize_exact_endpoint(
        COUNT.replace("us-central1-aiplatform", "europe-west4-aiplatform")
    ) != (origin, path)


def test_the_named_pair_must_be_two_distinct_operations_on_one_model_base():
    assert set(require_operation_endpoints(ENDPOINTS)) == {"count_tokens", "generate_content"}
    for broken in (
        {"count_tokens": COUNT},
        {"count_tokens": COUNT, "generate_content": GENERATE, "extra": COUNT},
        {"count_tokens": COUNT, "generate_content": COUNT},
        {"count_tokens": GENERATE, "generate_content": GENERATE},
        {
            "count_tokens": COUNT,
            "generate_content": GENERATE.replace("p-example", "other-project"),
        },
        None,
        [],
    ):
        with pytest.raises(ProviderError):
            require_operation_endpoints(broken)


def test_the_allowlist_must_equal_the_named_pair_not_merely_contain_it():
    require_allowlist_equals_operations([COUNT, GENERATE], ENDPOINTS)
    require_allowlist_equals_operations((GENERATE, COUNT), ENDPOINTS)
    for refused in (
        [COUNT],
        [COUNT, GENERATE, f"{MODEL_BASE}:predict"],
        [COUNT, COUNT],
        [COUNT, GENERATE.replace("p-example", "other-project")],
        (),
        None,
    ):
        with pytest.raises(ProviderError):
            require_allowlist_equals_operations(refused, ENDPOINTS)


def test_two_spellings_of_one_endpoint_are_not_two_endpoints():
    """Textual uniqueness would have passed this; normalized comparison does not."""
    with pytest.raises(ProviderError):
        require_allowlist_equals_operations(
            [COUNT, COUNT.replace("googleapis.com", "googleapis.com:443")], ENDPOINTS
        )


def test_the_grammar_module_imports_no_transport():
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "dynamic_ai_products"
        / "providers"
        / "endpoint_grammar_v2.py"
    ).read_text(encoding="utf-8")
    for forbidden in ("import httpx", "from httpx", "import google", "from google"):
        assert forbidden not in source


# --- artifact admission: the permit gate itself ------------------------------
#
# The grammar above is only worth having if something calls it. This section
# drives ``assert_run_permitted`` -- the gate that decides whether the endpoints
# declared by governance are the right ones -- and proves it refuses before any
# client factory or send exists.
#
# The released v1 helpers cannot do this job. They normalize with
# ``normalize_endpoint``, which discards query and fragment before comparing, and
# they read enablement as a superset. For a two-operation run all three lists
# must be the same two exact URLs and nothing else.

THIRD = f"{MODEL_BASE}:streamGenerateContent"
OTHER_MODEL = COUNT.replace("gemini-2.5-flash", "gemini-2.5-pro")
OTHER_LOCATION = COUNT.replace("us-central1", "europe-west4")


class FactoryTripwire:
    """Reaching the factory at all would mean the refusal came too late."""

    def __init__(self):
        self.opened = 0

    def __call__(self, **_kwargs):  # pragma: no cover - reaching it is the bug
        self.opened += 1
        raise AssertionError("the client factory was reached")


def _provider(tripwire, configured=(COUNT, GENERATE)):
    return VertexGeminiProviderV2(
        vertex_project="p-example",
        expected_authorization_sha256="9" * 64,
        max_provider_requests=3,
        endpoint_allowlist=tuple(configured),
        client_factory=tripwire,
    )


def _permit(provider, *, authorization=(COUNT, GENERATE), enablement=(COUNT, GENERATE)):
    provider.assert_run_permitted(
        authorization_sha256="9" * 64,
        endpoint_allowlist=tuple(authorization),
        enablement_endpoint_allowlist=tuple(enablement),
    )


BROKEN_LISTS = {
    "query": (COUNT + "?alt=sse", GENERATE),
    "fragment": (COUNT, GENERATE + "#frag"),
    "third_endpoint": (COUNT, GENERATE, THIRD),
    "duplicate_normalized": (COUNT, COUNT.replace("googleapis.com", "googleapis.com:443")),
    "operation_substituted": (COUNT, COUNT),
    "alternate_model": (OTHER_MODEL, GENERATE),
    "alternate_location": (OTHER_LOCATION, GENERATE),
    "single_entry": (COUNT,),
    "empty": (),
}


@pytest.mark.parametrize("flaw", sorted(BROKEN_LISTS))
@pytest.mark.parametrize("layer", ["configured", "authorization", "enablement"])
def test_a_flawed_list_in_any_layer_refuses_before_the_factory(flaw, layer):
    broken = BROKEN_LISTS[flaw]
    tripwire = FactoryTripwire()
    provider = _provider(tripwire, configured=broken if layer == "configured" else (COUNT, GENERATE))
    kwargs = {}
    if layer == "authorization":
        kwargs["authorization"] = broken
    if layer == "enablement":
        kwargs["enablement"] = broken
    with pytest.raises(ProviderError) as caught:
        _permit(provider, **kwargs)
    assert caught.value.reason_code == "live_call_not_authorized"
    assert tripwire.opened == 0


@pytest.mark.parametrize("flaw", sorted(BROKEN_LISTS))
@pytest.mark.parametrize("layer", ["configured", "authorization", "enablement"])
def test_a_refused_handshake_grants_no_permit_and_no_operation_may_run(flaw, layer):
    """A refusal must leave nothing spendable behind."""
    broken = BROKEN_LISTS[flaw]
    tripwire = FactoryTripwire()
    provider = _provider(tripwire, configured=broken if layer == "configured" else (COUNT, GENERATE))
    kwargs = {}
    if layer == "authorization":
        kwargs["authorization"] = broken
    if layer == "enablement":
        kwargs["enablement"] = broken
    with pytest.raises(ProviderError):
        _permit(provider, **kwargs)
    with pytest.raises(ProviderError) as caught:
        provider.count_tokens(_grammar_request(), sink=_never_sink)
    assert caught.value.reason_code == "live_call_not_authorized"
    assert tripwire.opened == 0


def test_the_query_case_is_exactly_what_the_v1_helpers_would_have_admitted():
    """The regression this closes, shown against the released helpers."""
    with_query = (COUNT + "?alt=sse", GENERATE)
    # The v1 grammar sees no difference: it strips the query before comparing.
    require_endpoint_allowlist_match(with_query, (COUNT, GENERATE))
    # The v2 gate does.
    tripwire = FactoryTripwire()
    provider = _provider(tripwire)
    with pytest.raises(ProviderError):
        _permit(provider, authorization=with_query)
    assert tripwire.opened == 0


def test_a_broader_enablement_is_no_longer_accepted():
    """v1 read enablement as a superset; a two-operation run needs both
    operations and nothing else, from every layer."""
    tripwire = FactoryTripwire()
    provider = _provider(tripwire)
    with pytest.raises(ProviderError):
        _permit(provider, enablement=(COUNT, GENERATE, THIRD))
    assert tripwire.opened == 0


def test_the_exact_two_entry_set_grants_both_permits():
    """Order does not matter; membership and count do."""
    for authorization in ((COUNT, GENERATE), (GENERATE, COUNT)):
        tripwire = FactoryTripwire()
        provider = _provider(tripwire)
        _permit(provider, authorization=authorization, enablement=authorization)
        # Both permits exist: each operation gets past the permit check and is
        # stopped only by the offline factory tripwire.
        with pytest.raises(AssertionError, match="client factory was reached"):
            provider.count_tokens(_grammar_request(), sink=_never_sink)
        assert tripwire.opened == 1


def test_a_second_handshake_attempt_revokes_the_earlier_permits_first():
    tripwire = FactoryTripwire()
    provider = _provider(tripwire)
    _permit(provider)
    with pytest.raises(ProviderError):
        _permit(provider, authorization=(COUNT, GENERATE, THIRD))
    with pytest.raises(ProviderError) as caught:
        provider.count_tokens(_grammar_request(), sink=_never_sink)
    assert caught.value.reason_code == "live_call_not_authorized"
    assert tripwire.opened == 0
