"""The rendered contents are what actually reach the SDK (ADR-036, E-R).

Before E-R the connector called ``generate_content(contents=request.prompt_text)``
and ``request.payload`` was never passed, so the packet's passages never left the
process. These tests capture the real ``contents`` argument handed to a fake SDK
and prove it is byte-identical to ``rendered_contents`` — and that the connector
has no second authority it could rebuild a representation from.
"""

from __future__ import annotations

import ast
import dataclasses
import hashlib
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.provider_adapter import (
    PROVIDER_PROTOCOL_VERSION,
    ProviderRequest,
)
from dynamic_ai_products.providers.errors import ProviderError
from dynamic_ai_products.providers.vertex_gemini import VertexGeminiProvider

ROOT = Path(__file__).resolve().parents[2]
PROJECT = "example-project"
ENDPOINT = "https://us-central1-aiplatform.googleapis.com/v1/projects"
BODY = b'{"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}'

RENDERED = (
    "Firm HUBSPOT INC as of 2024-12-31.\n\n"
    "[ref: P001] [passage_id: p-1] [source_id: sec-a]\nthe product ships an assistant\n"
)


def _request(rendered: str = RENDERED) -> ProviderRequest:
    return ProviderRequest(
        stage="product_extraction",
        rendered_contents=rendered,
        rendered_contents_sha256=hashlib.sha256(rendered.encode("utf-8")).hexdigest(),
        prompt_sha256="a" * 64,
        input_packet_sha256="b" * 64,
    )


class _SeenModels:
    """Records exactly what the SDK surface was called with."""

    def __init__(self, seen: dict) -> None:
        self._seen = seen

    def generate_content(self, *, model, contents, config):
        self._seen["model"] = model
        self._seen["contents"] = contents
        self._seen["config"] = config
        return object()


class _FakeClient:
    def __init__(self, seen: dict) -> None:
        self.models = _SeenModels(seen)


class _FakeCapture:
    def __init__(self, payload: bytes = BODY) -> None:
        self._payload = payload

    def captured_bytes(self) -> bytes:
        return self._payload


def _factory(seen: dict):
    from contextlib import contextmanager

    @contextmanager
    def factory(**kwargs):
        yield _FakeClient(seen), _FakeCapture()

    return factory


def _provider(seen: dict) -> VertexGeminiProvider:
    provider = VertexGeminiProvider(
        vertex_project=PROJECT,
        expected_authorization_sha256="c" * 64,
        max_provider_requests=3,
        endpoint_allowlist=(ENDPOINT,),
        client_factory=_factory(seen),
    )
    provider.assert_run_permitted(
        authorization_sha256="c" * 64,
        endpoint_allowlist=(ENDPOINT,),
        enablement_endpoint_allowlist=(ENDPOINT,),
    )
    return provider


# --- what reaches the SDK -----------------------------------------------------


def test_the_sdk_receives_the_rendered_contents_byte_for_byte():
    seen: dict = {}
    request = _request()
    _provider(seen).complete(request)
    assert seen["contents"] == request.rendered_contents
    assert seen["contents"].encode("utf-8") == RENDERED.encode("utf-8")
    assert (
        hashlib.sha256(seen["contents"].encode("utf-8")).hexdigest()
        == request.rendered_contents_sha256
    )


def test_the_packet_passages_and_identity_actually_leave_the_process():
    """The concrete defect E-R fixes: none of this used to be sent."""
    seen: dict = {}
    _provider(seen).complete(_request())
    for token in ("HUBSPOT INC", "2024-12-31", "p-1", "sec-a", "ships an assistant"):
        assert token in seen["contents"], token


def test_no_literal_placeholder_can_reach_the_sdk():
    seen: dict = {}
    _provider(seen).complete(_request())
    assert "{{" not in seen["contents"]
    assert "}}" not in seen["contents"]


def test_a_different_rendering_reaches_the_sdk_unchanged():
    seen: dict = {}
    other = "Firm OTHER CO as of 2023-12-31.\n\n[ref: P001] [passage_id: q-9] [source_id: sec-z]\nbody\n"
    _provider(seen).complete(_request(other))
    assert seen["contents"] == other


# --- there is no second authority ---------------------------------------------


def test_the_request_carries_no_prompt_text_or_payload_field():
    fields = {field.name for field in dataclasses.fields(ProviderRequest)}
    assert fields == {
        "stage",
        "rendered_contents",
        "rendered_contents_sha256",
        "prompt_sha256",
        "input_packet_sha256",
    }
    assert "prompt_text" not in fields
    assert "payload" not in fields


def test_the_connector_source_never_names_the_removed_fields():
    """Static proof: the connector cannot build a second representation."""
    source = ROOT / "src" / "dynamic_ai_products" / "providers" / "vertex_gemini.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    reads = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "request"
    }
    assert "prompt_text" not in reads
    assert "payload" not in reads
    assert "rendered_contents" in reads


def test_every_provider_module_is_free_of_the_removed_fields():
    package = ROOT / "src" / "dynamic_ai_products" / "providers"
    offenders = []
    for module in sorted(package.rglob("*.py")):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {
                "prompt_text",
                "payload",
            }:
                offenders.append(f"{module.name}:{node.lineno}")
    assert not offenders, offenders


def test_the_protocol_version_records_the_change():
    assert PROVIDER_PROTOCOL_VERSION == "extraction_provider_protocol_v7"


# --- the request is still validated -------------------------------------------


@pytest.mark.parametrize("payload", [None, 7, "text", {"a": 1}])
def test_a_non_request_object_is_refused(payload):
    seen: dict = {}
    with pytest.raises(ProviderError):
        _provider(seen).complete(payload)
    assert "contents" not in seen


def test_an_unactivated_connector_never_reaches_the_sdk():
    seen: dict = {}
    provider = VertexGeminiProvider(
        vertex_project=PROJECT, client_factory=_factory(seen)
    )
    with pytest.raises(ProviderError) as excinfo:
        provider.complete(_request())
    assert excinfo.value.reason_code == "live_call_not_authorized"
    assert seen == {}


# --- the digest is bound to the bytes (ADR-036, E-R correction) ----------------


def test_a_false_digest_cannot_reach_the_sdk():
    """Reproduced defect: real contents plus a fabricated digest used to pass.

    The connector would send the contents anyway, the meter would measure them,
    and every artifact would record a digest matching nothing. Construction now
    refuses, so nothing downstream can be reached at all.
    """
    from dynamic_ai_products.extraction.errors import ExtractionError

    seen: dict = {}
    with pytest.raises(ExtractionError) as excinfo:
        ProviderRequest(
            stage="product_extraction",
            rendered_contents="REAL BYTES",
            rendered_contents_sha256="0" * 64,
            prompt_sha256="a" * 64,
            input_packet_sha256="b" * 64,
        )
    assert excinfo.value.reason_code == "provider_protocol_invalid"
    assert seen == {}
    # Neither digest is echoed through the boundary.
    assert "0" * 64 not in str(excinfo.value)


@pytest.mark.parametrize(
    "digest",
    [
        "0" * 64,                          # right shape, wrong value
        "A" * 64,                          # uppercase hex
        hashlib.sha256(b"other").hexdigest().upper(),
        "abc",                             # too short
        "f" * 65,                          # too long
        "g" * 64,                          # not hex
        None,
        7,
    ],
)
def test_every_malformed_digest_is_refused(digest):
    from dynamic_ai_products.extraction.errors import ExtractionError

    with pytest.raises(ExtractionError) as excinfo:
        ProviderRequest(
            stage="product_extraction",
            rendered_contents=RENDERED,
            rendered_contents_sha256=digest,
            prompt_sha256="a" * 64,
            input_packet_sha256="b" * 64,
        )
    assert excinfo.value.reason_code == "provider_protocol_invalid"


@pytest.mark.parametrize("contents", ["", None, 7])
def test_unusable_contents_are_refused(contents):
    from dynamic_ai_products.extraction.errors import ExtractionError

    with pytest.raises(ExtractionError) as excinfo:
        ProviderRequest(
            stage="product_extraction",
            rendered_contents=contents,
            rendered_contents_sha256="0" * 64,
            prompt_sha256="a" * 64,
            input_packet_sha256="b" * 64,
        )
    assert excinfo.value.reason_code == "provider_protocol_invalid"


def test_a_matching_digest_constructs_normally():
    request = _request()
    assert (
        hashlib.sha256(request.rendered_contents.encode("utf-8")).hexdigest()
        == request.rendered_contents_sha256
    )
