"""Operation-labelled, single-use capture, and the 101 that used to slip through.

Every test here runs over ``httpx.MockTransport``: no socket is opened, no
credential is read, and no vendor client is constructed.

Two properties carry the increment. A retryable attempt's body must survive the
attempt that follows it -- one shared slot would have let the later body take the
earlier one's place with nothing to notice. And a ``101`` must be refused before
``response.content`` is touched: measured in ``httpcore``, the receive loop breaks
on an informational response with status 101, so it reaches this boundary, and the
released guard refused only ``3xx``.
"""

from __future__ import annotations

import httpx
import pytest

from dynamic_ai_products.providers.client_contract_v2 import build_operation_endpoints
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.response_capture import CapturingHttpxClient

ENDPOINTS = build_operation_endpoints(vertex_project="p-example")
COUNT = ENDPOINTS["count_tokens"]
GENERATE = ENDPOINTS["generate_content"]
ALLOWLIST = (COUNT, GENERATE)


def client(handler):
    return CapturingHttpxClient(
        endpoint_allowlist=ALLOWLIST,
        operation_endpoints=dict(ENDPOINTS),
        transport=httpx.MockTransport(handler),
    )


def responder(*outcomes):
    """Reply by call ordinal, never by URL.

    The two operations differ only in their suffix, and both are allowed, so a
    URL-keyed fake could answer the wrong call without either side noticing.
    """
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        status, body = outcomes[state["n"] - 1]
        return httpx.Response(status, content=body)

    return handler


def test_each_operation_keeps_its_own_ordinal_sequence():
    with client(responder((200, b"c"), (200, b"g1"), (200, b"g2"))) as capture:
        with capture.operation("count_tokens"):
            capture.send(httpx.Request("POST", COUNT))
        with capture.operation("generate_content"):
            capture.send(httpx.Request("POST", GENERATE))
            capture.send(httpx.Request("POST", GENERATE))
        assert capture.drain("count_tokens", 1) == b"c"
        assert capture.drain("generate_content", 1) == b"g1"
        assert capture.drain("generate_content", 2) == b"g2"
        assert capture.send_calls == 3


def test_a_retryable_body_is_not_replaced_by_the_attempt_that_follows_it():
    """The single-slot failure, made concrete."""
    with client(responder((503, b"transient"), (200, b"final"))) as capture:
        with capture.operation("generate_content"):
            capture.send(httpx.Request("POST", GENERATE))
            capture.send(httpx.Request("POST", GENERATE))
        assert capture.drain("generate_content", 1) == b"transient"
        assert capture.drain("generate_content", 2) == b"final"


def test_a_drained_slot_is_gone_and_a_filled_one_is_never_overwritten():
    with client(responder((200, b"c"))) as capture:
        with capture.operation("count_tokens"):
            capture.send(httpx.Request("POST", COUNT))
        assert capture.drain("count_tokens", 1) == b"c"
        assert capture.drain("count_tokens", 1) is None


def test_a_101_is_refused_before_the_body_is_read():
    with client(responder((101, b"switched"))) as capture:
        with capture.operation("count_tokens"):
            with pytest.raises(ProviderError):
                capture.send(httpx.Request("POST", COUNT))
        assert capture.drain("count_tokens", 1) is None
        assert capture.send_outcome("count_tokens", 1) == "response_protocol_switch"
        # The request did leave the process, so it is counted.
        assert capture.send_calls == 1


def test_a_redirect_is_still_refused_and_named_separately_from_a_switch():
    with client(responder((302, b"moved"))) as capture:
        with capture.operation("generate_content"):
            with pytest.raises(ProviderError):
                capture.send(httpx.Request("POST", GENERATE))
        assert capture.send_outcome("generate_content", 1) == "response_redirect_refused"
        assert capture.drain("generate_content", 1) is None


@pytest.mark.parametrize(
    "status, outcome", [(200, "response_2xx"), (404, "response_4xx"), (503, "response_5xx")]
)
def test_the_status_class_is_named_at_the_boundary_that_sees_it(status, outcome):
    with client(responder((status, b"body"))) as capture:
        with capture.operation("generate_content"):
            capture.send(httpx.Request("POST", GENERATE))
        assert capture.send_outcome("generate_content", 1) == outcome
        # A 4xx or 5xx body is evidence and is captured; only 1xx and 3xx are not.
        assert capture.drain("generate_content", 1) == b"body"


def test_a_crossed_operation_never_leaves_the_process():
    """Both URLs are on the allowlist, so only the context check can catch this."""
    with client(responder((200, b"never"))) as capture:
        with capture.operation("count_tokens"):
            with pytest.raises(ProviderError):
                capture.send(httpx.Request("POST", GENERATE))
        assert capture.send_calls == 0
        assert capture.send_outcome("count_tokens", 1) == "not_sent_context_url_mismatch"


def test_a_query_string_is_refused_in_v2_mode():
    with client(responder((200, b"never"))) as capture:
        with capture.operation("generate_content"):
            with pytest.raises(ProviderError):
                capture.send(httpx.Request("POST", GENERATE + "?alt=sse"))
        assert capture.send_calls == 0


def test_a_send_outside_an_operation_context_is_refused():
    with client(responder((200, b"never"))) as capture:
        with pytest.raises(ProviderError):
            capture.send(httpx.Request("POST", COUNT))
        assert capture.send_calls == 0


def test_contexts_do_not_nest_and_unknown_labels_are_refused():
    with client(responder((200, b"c"))) as capture:
        with pytest.raises(ProviderError):
            with capture.operation("unknown_operation"):
                pass
        with capture.operation("count_tokens"):
            with pytest.raises(ProviderError):
                with capture.operation("generate_content"):
                    pass


def test_v1_mode_is_untouched_by_the_operation_machinery():
    """Without ``operation_endpoints`` the client behaves exactly as E-L shipped."""
    plain = CapturingHttpxClient(
        endpoint_allowlist=ALLOWLIST, transport=httpx.MockTransport(responder((200, b"body")))
    )
    with plain:
        plain.send(httpx.Request("POST", COUNT))
        assert plain.captured_bytes() == b"body"
        assert plain.operation_endpoints is None


def test_the_capture_module_is_the_only_new_transport_importer():
    from pathlib import Path

    package = Path(__file__).resolve().parents[2] / "src" / "dynamic_ai_products" / "providers"
    importers = [
        path.name
        for path in sorted(package.glob("*.py"))
        if "import httpx" in path.read_text(encoding="utf-8")
    ]
    assert importers == ["response_capture.py"]
