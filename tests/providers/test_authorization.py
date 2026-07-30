"""Connector half of the two-key handshake (ADR-035).

Neither half alone authorizes a run. These tests pin that the connector refuses
without an expected digest, without a request cap, and on any digest mismatch —
and that the refusal happens before the vendor SDK is touched.

The residual limit is deliberate and recorded: a caller inside this process that
fabricates both the digest and the cap satisfies both halves. That is a
``noncanonical_experiment`` under SPEC-027 and may never enter an evaluation or
production record. What is guaranteed is detectability, not prevention.
"""

from __future__ import annotations

import inspect
import sys

import pytest

from dynamic_ai_products.providers.authorization import (
    require_authorization_digest,
    require_endpoint_allowlist_match,
    require_endpoint_allowlist_subset,
    require_request_cap,
)
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.retry_policy import RETRY_MAX_ATTEMPTS
from dynamic_ai_products.providers.vertex_gemini import VertexGeminiProvider

PROJECT = "my-research-project"
DIGEST = "a" * 64
ALLOWLIST = ("https://us-central1-aiplatform.googleapis.com/v1/projects",)


def _authorized(**overrides):
    kwargs = {
        "vertex_project": PROJECT,
        "expected_authorization_sha256": DIGEST,
        "max_provider_requests": 3,
        "endpoint_allowlist": ALLOWLIST,
    }
    kwargs.update(overrides)
    return VertexGeminiProvider(**kwargs)


# --- digest comparison --------------------------------------------------------


def test_matching_digests_are_accepted():
    assert require_authorization_digest(DIGEST, DIGEST) == DIGEST


@pytest.mark.parametrize(
    "expected,supplied",
    [
        (DIGEST, "b" * 64),
        (DIGEST, None),
        (DIGEST, "short"),
        (DIGEST, "A" * 64),
        (None, DIGEST),
        ("short", DIGEST),
        (7, DIGEST),
        (DIGEST, 7),
    ],
)
def test_any_mismatch_or_malformed_digest_is_refused(expected, supplied):
    with pytest.raises(ProviderError) as excinfo:
        require_authorization_digest(expected, supplied)
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_digest_comparison_is_constant_time():
    """A timing side channel would leak the digest a character at a time."""
    source = inspect.getsource(require_authorization_digest)
    assert "hmac.compare_digest" in source
    assert "==" not in source.split("compare_digest")[1]


# --- the request cap ----------------------------------------------------------


@pytest.mark.parametrize("cap", [1, 2, 3])
def test_a_cap_within_the_policy_is_accepted(cap):
    assert require_request_cap(cap, policy_maximum=RETRY_MAX_ATTEMPTS) == cap


@pytest.mark.parametrize("cap", [None, 0, -1, 4, 99, "3", 1.5, True])
def test_a_missing_or_raising_cap_is_refused(cap):
    """The cap may only lower the policy; it can never buy extra attempts."""
    with pytest.raises(ProviderError) as excinfo:
        require_request_cap(cap, policy_maximum=RETRY_MAX_ATTEMPTS)
    assert excinfo.value.reason_code == "live_call_not_authorized"


# --- the connector's half -----------------------------------------------------


def test_the_default_connector_still_refuses():
    """No expected digest was configured, so E-P's default-deny holds."""
    provider = VertexGeminiProvider(vertex_project=PROJECT)
    with pytest.raises(ProviderError) as excinfo:
        provider.assert_run_permitted(
            authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
        )
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_a_runner_digest_that_does_not_match_is_refused():
    with pytest.raises(ProviderError) as excinfo:
        _authorized().assert_run_permitted(
            authorization_sha256="b" * 64,
            endpoint_allowlist=ALLOWLIST,
            enablement_endpoint_allowlist=ALLOWLIST
        )
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_no_runner_digest_at_all_is_refused():
    with pytest.raises(ProviderError) as excinfo:
        _authorized().assert_run_permitted()
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_a_missing_request_cap_is_refused_even_with_a_matching_digest():
    with pytest.raises(ProviderError) as excinfo:
        _authorized(max_provider_requests=None).assert_run_permitted(
            authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
        )
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_an_empty_configured_allowlist_is_refused():
    with pytest.raises(ProviderError) as excinfo:
        _authorized(endpoint_allowlist=()).assert_run_permitted(
            authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
        )
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_a_matching_digest_and_allowlist_activates_the_connector():
    provider = _authorized()
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )


def test_complete_refuses_until_the_handshake_has_run():
    """Activation is not implied by construction."""
    with pytest.raises(ProviderError) as excinfo:
        _authorized().complete(None)
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_no_refusal_path_imports_the_vendor_sdk():
    before = {name for name in sys.modules if name.startswith("google")}
    provider = _authorized()
    for call in (
        lambda: provider.assert_run_permitted(
            authorization_sha256="b" * 64,
            endpoint_allowlist=ALLOWLIST,
            enablement_endpoint_allowlist=ALLOWLIST
        ),
        lambda: VertexGeminiProvider(vertex_project=PROJECT).complete(None),
    ):
        with pytest.raises(ProviderError):
            call()
    assert {name for name in sys.modules if name.startswith("google")} == before


def test_the_expected_digest_and_cap_are_explicit_constructor_arguments():
    """Neither is derived from a file, an environment variable, or a default."""
    parameters = inspect.signature(VertexGeminiProvider.__init__).parameters
    for name in ("expected_authorization_sha256", "max_provider_requests"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default is None


# --- the third key: the endpoint allowlist is execution-bound ------------------
#
# Validating the allowlist as artifact content is not enough. A connector holding
# the right digest and cap could still carry a broader or different allowlist, and
# every per-request check would then be measured against the wrong set.


BROADER = ALLOWLIST + ("https://us-central1-aiplatform.googleapis.com/v1",)
DIFFERENT = ("https://europe-west4-aiplatform.googleapis.com/v1/projects",)


# A distinct sentinel, so a test can pass an explicit ``None`` enablement list.
_DEFAULT_ENABLEMENT = object()


def _activate(configured, supplied, enablement=_DEFAULT_ENABLEMENT):
    VertexGeminiProvider(
        vertex_project=PROJECT,
        expected_authorization_sha256=DIGEST,
        max_provider_requests=3,
        endpoint_allowlist=configured,
    ).assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=supplied,
        # Defaults to the authorization's own list, so these cases exercise
        # connector-vs-authorization equality; the subset rule has its own tests.
        enablement_endpoint_allowlist=(
            supplied if enablement is _DEFAULT_ENABLEMENT else enablement
        ),
    )


def _refused(configured, supplied, enablement=_DEFAULT_ENABLEMENT):
    with pytest.raises(ProviderError) as excinfo:
        _activate(configured, supplied, enablement)
    assert excinfo.value.reason_code == "live_call_not_authorized"


@pytest.mark.parametrize(
    "supplied",
    [
        ALLOWLIST,
        # The same endpoints, written differently. Comparison is semantic.
        ("https://US-CENTRAL1-AIPLATFORM.googleapis.com/v1/projects",),
        ("https://us-central1-aiplatform.googleapis.com.:443/v1/projects",),
        ("https://us-central1-aiplatform.googleapis.com/v1/./projects",),
        ("https://us-central1-aiplatform.googleapis.com/v1/x/../projects",),
        # Query and fragment take no part in endpoint identity.
        ("https://us-central1-aiplatform.googleapis.com/v1/projects?a=1#f",),
    ],
)
def test_an_equivalent_normalized_allowlist_activates(supplied):
    _activate(ALLOWLIST, supplied)


def test_order_does_not_matter():
    two = ALLOWLIST + DIFFERENT
    _activate(two, tuple(reversed(two)))


def test_a_broader_authorization_allowlist_is_refused():
    """Extra authorized endpoints are not silently accepted."""
    _refused(ALLOWLIST, BROADER)


def test_a_broader_configured_allowlist_is_refused():
    """Nor is a connector that would accept more than was authorized."""
    _refused(BROADER, ALLOWLIST)


def test_a_different_allowlist_is_refused():
    _refused(ALLOWLIST, DIFFERENT)


@pytest.mark.parametrize("supplied", [None, (), []])
def test_a_missing_or_empty_authorization_allowlist_is_refused(supplied):
    _refused(ALLOWLIST, supplied)


@pytest.mark.parametrize(
    "supplied",
    [
        ("http://us-central1-aiplatform.googleapis.com/v1/projects",),
        ("https://user:pass@us-central1-aiplatform.googleapis.com/v1/projects",),
        ("https://us-central1-aiplatform.googleapis.com:8443/v1/projects",),
        ("not-a-url",),
        ("",),
        (7,),
        (None,),
    ],
)
def test_a_malformed_authorization_entry_is_refused(supplied):
    """A malformed entry is an authorization failure, not a response failure."""
    _refused(ALLOWLIST, supplied)


def test_a_duplicate_authorization_entry_is_refused():
    """A duplicate hides how many distinct endpoints were actually authorized."""
    _refused(ALLOWLIST, ALLOWLIST + ALLOWLIST)
    _refused(
        ALLOWLIST,
        ALLOWLIST + ("https://US-CENTRAL1-AIPLATFORM.googleapis.com:443/v1/projects",),
    )


def test_a_duplicate_configured_entry_is_refused():
    _refused(ALLOWLIST + ALLOWLIST, ALLOWLIST)


def test_a_non_sequence_allowlist_is_refused():
    for supplied in ("https://x.example.com/v1", 7, object()):
        _refused(ALLOWLIST, supplied)


def test_the_matcher_returns_the_normalized_set():
    matched = require_endpoint_allowlist_match(ALLOWLIST, ALLOWLIST)
    assert matched == frozenset(
        {("https://us-central1-aiplatform.googleapis.com", "/v1/projects")}
    )


def test_a_mismatched_allowlist_refusal_never_reaches_the_sdk():
    before = {name for name in sys.modules if name.startswith("google")}
    _refused(ALLOWLIST, DIFFERENT)
    assert {name for name in sys.modules if name.startswith("google")} == before


def test_complete_stays_refused_after_an_allowlist_mismatch():
    """A failed handshake must not leave the connector half-activated."""
    provider = VertexGeminiProvider(
        vertex_project=PROJECT,
        expected_authorization_sha256=DIGEST,
        max_provider_requests=3,
        endpoint_allowlist=ALLOWLIST,
    )
    with pytest.raises(ProviderError):
        provider.assert_run_permitted(
            authorization_sha256=DIGEST,
            endpoint_allowlist=DIFFERENT,
            enablement_endpoint_allowlist=DIFFERENT
        )
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(None)
    assert excinfo.value.reason_code == "live_call_not_authorized"


def test_the_allowlist_is_a_keyword_only_protocol_argument():
    parameters = inspect.signature(VertexGeminiProvider.assert_run_permitted).parameters
    assert parameters["endpoint_allowlist"].kind is inspect.Parameter.KEYWORD_ONLY
    assert parameters["endpoint_allowlist"].default is None


# --- enablement ⊇ authorization == connector (ADR-035, v4.5) -------------------
#
# One grammar, three levels. Enforcement lives provider-side because endpoint
# normalization is provider-side grammar and extraction may not import providers;
# a second copy of the rules could drift from the one the capture client applies.


WIDE = ALLOWLIST + ("https://us-central1-aiplatform.googleapis.com/v1/models",)


def test_a_narrower_authorization_within_the_enablement_activates():
    """A run authorization exists so one run can use less than it may."""
    _activate(ALLOWLIST, ALLOWLIST, enablement=WIDE)


def test_an_equal_authorization_and_enablement_activates():
    _activate(ALLOWLIST, ALLOWLIST, enablement=ALLOWLIST)


def test_the_subset_check_is_semantic_not_textual():
    _activate(
        ALLOWLIST,
        ALLOWLIST,
        enablement=("https://US-CENTRAL1-AIPLATFORM.googleapis.com.:443/v1/./projects",),
    )


def test_an_authorization_broader_than_its_enablement_is_refused():
    """Widening is the thing that must be impossible."""
    _refused(WIDE, WIDE, enablement=ALLOWLIST)


def test_a_single_extra_authorized_endpoint_is_refused():
    extra = ALLOWLIST + ("https://europe-west4-aiplatform.googleapis.com/v1/projects",)
    _refused(extra, extra, enablement=ALLOWLIST)


@pytest.mark.parametrize("enablement", [None, (), []])
def test_a_missing_or_empty_enablement_allowlist_is_refused(enablement):
    _refused(ALLOWLIST, ALLOWLIST, enablement=enablement)


@pytest.mark.parametrize(
    "enablement",
    [
        ("not-a-url",),
        ("http://us-central1-aiplatform.googleapis.com/v1/projects",),
        ("https://user:pass@us-central1-aiplatform.googleapis.com/v1/projects",),
        (7,),
        (None,),
        "https://us-central1-aiplatform.googleapis.com/v1/projects",
    ],
)
def test_a_malformed_or_non_sequence_enablement_allowlist_is_refused(enablement):
    _refused(ALLOWLIST, ALLOWLIST, enablement=enablement)


def test_a_duplicate_enablement_entry_is_refused():
    _refused(ALLOWLIST, ALLOWLIST, enablement=ALLOWLIST + ALLOWLIST)


def test_the_subset_helper_returns_the_narrowed_set():
    narrowed = require_endpoint_allowlist_subset(WIDE, ALLOWLIST)
    assert narrowed == frozenset(
        {("https://us-central1-aiplatform.googleapis.com", "/v1/projects")}
    )
    assert narrowed < require_endpoint_allowlist_subset(WIDE, WIDE)


def test_connector_equality_still_holds_under_a_wider_enablement():
    """The enablement may be wider; the connector may not."""
    _refused(WIDE, ALLOWLIST, enablement=WIDE)


def test_a_subset_refusal_never_imports_the_vendor_sdk():
    before = {name for name in sys.modules if name.startswith("google")}
    _refused(WIDE, WIDE, enablement=ALLOWLIST)
    assert {name for name in sys.modules if name.startswith("google")} == before


def test_the_protocol_v5_signature_carries_three_keyword_only_inputs():
    parameters = inspect.signature(VertexGeminiProvider.assert_run_permitted).parameters
    assert [n for n in parameters if n != "self"] == [
        "authorization_sha256",
        "endpoint_allowlist",
        "enablement_endpoint_allowlist",
    ]
    for name in ("authorization_sha256", "endpoint_allowlist", "enablement_endpoint_allowlist"):
        assert parameters[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert parameters[name].default is None


def test_the_protocol_version_and_the_connector_pin_agree_at_v7():
    from dynamic_ai_products.extraction.provider_adapter import PROVIDER_PROTOCOL_VERSION
    from dynamic_ai_products.providers.client_contract import (
        PROVIDER_PROTOCOL_VERSION_PIN,
    )

    assert PROVIDER_PROTOCOL_VERSION == "extraction_provider_protocol_v7"
    assert PROVIDER_PROTOCOL_VERSION_PIN == PROVIDER_PROTOCOL_VERSION
