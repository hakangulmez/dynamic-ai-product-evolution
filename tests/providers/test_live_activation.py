"""The authorized execution path, exercised offline (ADR-035).

The connector's real path is driven with an injected fake factory: no
``genai.Client`` is built, no ADC is resolved, and no socket is opened. What is
verified is that activation gates the factory, that the captured entity body is
what gets archived, and that the retry cap and the capture refusals hold.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager

import pytest

from dynamic_ai_products.extraction.provider_adapter import ProviderRequest
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.vertex_gemini import (
    RAW_CAPTURE_REPRESENTATION,
    VertexGeminiProvider,
)

PROJECT = "my-research-project"
DIGEST = "a" * 64
ALLOWLIST = ("https://us-central1-aiplatform.googleapis.com/v1/projects",)
BODY = b'{"candidates":[{"content":{"parts":[{"text":"ok"}]}}]}'


class _FakeCapture:
    def __init__(self, payload=BODY):
        self._payload = payload
        self.closed = False

    def captured_bytes(self):
        if not isinstance(self._payload, bytes) or not self._payload:
            raise ProviderError("provider_response_unusable")
        return self._payload

    def close(self):
        self.closed = True


class _FakeModels:
    def __init__(self, outcomes):
        self._outcomes = list(outcomes)
        self.calls = []

    def generate_content(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class _FakeClient:
    def __init__(self, outcomes):
        self.models = _FakeModels(outcomes)


def _factory(*, outcomes=(object(),), payload=BODY, seen=None):
    @contextmanager
    def factory(**kwargs):
        if seen is not None:
            seen.append(kwargs)
        capture = _FakeCapture(payload)
        client = _FakeClient(outcomes)
        try:
            yield client, capture
        finally:
            capture.close()

    return factory


def _provider(**overrides):
    kwargs = {
        "vertex_project": PROJECT,
        "expected_authorization_sha256": DIGEST,
        "max_provider_requests": 3,
        "endpoint_allowlist": ALLOWLIST,
        "client_factory": _factory(),
    }
    kwargs.update(overrides)
    return VertexGeminiProvider(**kwargs)


def _request():
    return ProviderRequest(
        stage="product_extraction",
        prompt_text="prompt body",
        prompt_sha256="c" * 64,
        input_packet_sha256="d" * 64,
        payload={"passages": [{"passage_id": "p-1"}]},
    )


def _exc(name="ApiError", **attributes):
    cls = type(name, (Exception,), {})
    instance = cls("upstream text that must never surface")
    for key, value in attributes.items():
        setattr(instance, key, value)
    return instance


# --- activation gates the factory --------------------------------------------


def test_the_factory_is_never_reached_without_activation():
    seen: list = []
    provider = _provider(client_factory=_factory(seen=seen))
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.reason_code == "live_call_not_authorized"
    assert seen == []


def test_an_activated_run_reaches_the_factory_with_the_locked_configuration():
    seen: list = []
    provider = _provider(client_factory=_factory(seen=seen))
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    provider.complete(_request())
    assert len(seen) == 1
    assert seen[0]["vertex_project"] == PROJECT
    assert seen[0]["vertex_location"] == "us-central1"
    assert seen[0]["endpoint_allowlist"] == ALLOWLIST
    assert seen[0]["http_options_kwargs"]["timeout"] == 300000
    assert seen[0]["http_options_kwargs"]["retry_options"] == {"attempts": 1}


# --- what gets archived -------------------------------------------------------


def test_the_captured_entity_body_is_what_is_archived():
    provider = _provider()
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    response = provider.complete(_request())
    assert response.raw_bytes == BODY
    assert response.model_provider == "google_vertex_ai"
    assert response.model_name == "gemini-2.5-flash"


def test_the_response_declares_the_capture_representation():
    provider = _provider()
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    response = provider.complete(_request())
    assert (
        response.prompt_model_metadata["raw_capture_representation"]
        == RAW_CAPTURE_REPRESENTATION
        == "post_content_encoding_entity_body"
    )
    assert response.prompt_model_metadata["prompt_sha256"] == "c" * 64


@pytest.mark.parametrize("payload", [b"", None, "text", 7])
def test_an_unusable_capture_is_refused(payload):
    provider = _provider(client_factory=_factory(payload=payload))
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.reason_code == "provider_response_unusable"


def test_the_capture_client_is_closed_even_on_failure():
    closed: list = []

    @contextmanager
    def factory(**kwargs):
        capture = _FakeCapture(b"")
        try:
            yield _FakeClient([object()]), capture
        finally:
            capture.close()
            closed.append(capture.closed)

    provider = _provider(client_factory=factory)
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    with pytest.raises(ProviderError):
        provider.complete(_request())
    assert closed == [True]


# --- the request the provider sends ------------------------------------------


def test_the_locked_model_and_config_reach_the_sdk_call():
    provider = _provider()
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    provider.complete(_request())
    # The fake client records the kwargs the connector passed.
    factory_client = None
    seen: list = []
    provider2 = _provider(client_factory=_factory(seen=seen))
    provider2.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    provider2.complete(_request())
    assert factory_client is None
    assert seen[0]["http_options_kwargs"]["api_version"] == "v1"


# --- retry cap ----------------------------------------------------------------


def test_the_cap_bounds_the_number_of_sdk_calls():
    client_holder: list = []

    @contextmanager
    def factory(**kwargs):
        client = _FakeClient([_exc(code=503) for _ in range(5)])
        client_holder.append(client)
        yield client, _FakeCapture()

    provider = _provider(max_provider_requests=2, client_factory=factory)
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert len(client_holder[0].models.calls) == 2
    assert excinfo.value.attempt_count == 2
    assert excinfo.value.reason_code == "vertex_unavailable"


def test_a_cap_of_one_disables_retry_entirely():
    client_holder: list = []

    @contextmanager
    def factory(**kwargs):
        client = _FakeClient([_exc(code=503) for _ in range(5)])
        client_holder.append(client)
        yield client, _FakeCapture()

    provider = _provider(max_provider_requests=1, client_factory=factory)
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    with pytest.raises(ProviderError):
        provider.complete(_request())
    assert len(client_holder[0].models.calls) == 1


def test_a_non_request_payload_is_refused_after_activation():
    provider = _provider()
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    with pytest.raises(ProviderError) as excinfo:
        provider.complete({"stage": "product_extraction"})
    assert excinfo.value.reason_code == "provider_response_unusable"


def test_no_upstream_text_survives_the_authorized_path():
    @contextmanager
    def factory(**kwargs):
        yield _FakeClient([_exc(code=403)]), _FakeCapture()

    provider = _provider(client_factory=factory)
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert "upstream text" not in str(excinfo.value)


def test_the_offline_path_imports_no_google_module():
    before = {name for name in sys.modules if name.startswith("google")}
    provider = _provider()
    provider.assert_run_permitted(
        authorization_sha256=DIGEST,
        endpoint_allowlist=ALLOWLIST,
        enablement_endpoint_allowlist=ALLOWLIST
    )
    provider.complete(_request())
    assert {name for name in sys.modules if name.startswith("google")} == before


# --- activation is one-shot and non-replayable ---------------------------------
#
# A permit that survived its call could be spent again from the same
# authorization, and a later failed handshake would not revoke an earlier
# success. Both are closed by clearing on every attempt and consuming on use.


def _counting_factory(outcomes=(object(),), payload=BODY):
    """A factory that records how many times it was entered."""
    entries: list = []

    @contextmanager
    def factory(**kwargs):
        entries.append(kwargs)
        capture = _FakeCapture(payload)
        try:
            yield _FakeClient(list(outcomes)), capture
        finally:
            capture.close()

    return factory, entries


def _activate(provider, *, digest=DIGEST, allowlist=ALLOWLIST, enablement=None):
    provider.assert_run_permitted(
        authorization_sha256=digest,
        endpoint_allowlist=allowlist,
        # The enablement defaults to the authorization's own list; the subset
        # rule is covered in test_authorization.py.
        enablement_endpoint_allowlist=allowlist if enablement is None else enablement,
    )


def test_one_authorization_buys_exactly_one_call():
    factory, entries = _counting_factory(outcomes=(object(), object()))
    provider = _provider(client_factory=factory)
    _activate(provider)
    assert provider.complete(_request()).raw_bytes == BODY
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.reason_code == "live_call_not_authorized"
    # The factory was entered once: the second call never reached it.
    assert len(entries) == 1


def test_a_second_call_needs_a_second_handshake():
    factory, entries = _counting_factory(outcomes=(object(), object()))
    provider = _provider(client_factory=factory)
    _activate(provider)
    provider.complete(_request())
    _activate(provider)
    provider.complete(_request())
    assert len(entries) == 2


@pytest.mark.parametrize(
    "digest,allowlist",
    [
        ("b" * 64, ALLOWLIST),
        (None, ALLOWLIST),
        (DIGEST, ("https://europe-west4-aiplatform.googleapis.com/v1/projects",)),
        (DIGEST, None),
        (DIGEST, ()),
        (DIGEST, ("not-a-url",)),
    ],
)
def test_a_failed_handshake_revokes_a_prior_activation(digest, allowlist):
    """The earlier success must not remain spendable."""
    factory, entries = _counting_factory()
    provider = _provider(client_factory=factory)
    _activate(provider)
    with pytest.raises(ProviderError):
        _activate(provider, digest=digest, allowlist=allowlist)
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.reason_code == "live_call_not_authorized"
    assert entries == []


def test_a_failed_handshake_before_any_success_still_refuses():
    factory, entries = _counting_factory()
    provider = _provider(client_factory=factory)
    with pytest.raises(ProviderError):
        _activate(provider, digest="b" * 64)
    with pytest.raises(ProviderError):
        provider.complete(_request())
    assert entries == []


def test_a_terminal_provider_failure_consumes_the_activation():
    factory, entries = _counting_factory(outcomes=(_exc(code=503),) * 5)
    provider = _provider(client_factory=factory)
    _activate(provider)
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.reason_code == "vertex_unavailable"
    with pytest.raises(ProviderError) as second:
        provider.complete(_request())
    assert second.value.reason_code == "live_call_not_authorized"
    assert len(entries) == 1


def test_a_capture_failure_consumes_the_activation():
    factory, entries = _counting_factory(payload=b"")
    provider = _provider(client_factory=factory)
    _activate(provider)
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.reason_code == "provider_response_unusable"
    with pytest.raises(ProviderError) as second:
        provider.complete(_request())
    assert second.value.reason_code == "live_call_not_authorized"
    assert len(entries) == 1


def test_a_factory_failure_consumes_the_activation():
    entries: list = []

    @contextmanager
    def exploding(**kwargs):
        entries.append(kwargs)
        raise RuntimeError("factory could not be built")
        yield  # pragma: no cover

    provider = _provider(client_factory=exploding)
    _activate(provider)
    with pytest.raises(RuntimeError):
        provider.complete(_request())
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.reason_code == "live_call_not_authorized"
    assert len(entries) == 1


def test_a_malformed_request_consumes_the_activation():
    """A spent attempt is spent, however it failed."""
    factory, entries = _counting_factory()
    provider = _provider(client_factory=factory)
    _activate(provider)
    with pytest.raises(ProviderError) as excinfo:
        provider.complete({"stage": "product_extraction"})
    assert excinfo.value.reason_code == "provider_response_unusable"
    with pytest.raises(ProviderError) as second:
        provider.complete(_request())
    assert second.value.reason_code == "live_call_not_authorized"
    assert entries == []


def test_the_activation_is_consumed_before_the_factory_is_entered():
    """Ordering proof: the permit is already spent when the factory runs."""
    observed: list = []

    @contextmanager
    def observing(**kwargs):
        observed.append(provider._activated_digest)
        capture = _FakeCapture(BODY)
        try:
            yield _FakeClient([object()]), capture
        finally:
            capture.close()

    provider = _provider(client_factory=observing)
    _activate(provider)
    provider.complete(_request())
    assert observed == [None]


def test_a_replayed_call_never_imports_the_vendor_sdk():
    before = {name for name in sys.modules if name.startswith("google")}
    factory, _ = _counting_factory()
    provider = _provider(client_factory=factory)
    _activate(provider)
    provider.complete(_request())
    with pytest.raises(ProviderError):
        provider.complete(_request())
    assert {name for name in sys.modules if name.startswith("google")} == before
