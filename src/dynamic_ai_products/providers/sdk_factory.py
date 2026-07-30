"""The single module permitted to import the vendor SDK (ADR-035).

**Lazy by construction.** ``google.genai`` is imported inside the factory body,
so importing this module — or the connector that uses it — pulls in nothing.
E-P shipped zero ``google.*`` imports under ``src/``; E-L raises that to exactly
one, and the boundary guard becomes an exact allowlist naming this file.

The factory is reachable only after the two-key handshake has passed, so an
unauthorized run never touches the SDK, a client, or Application Default
Credentials. ADC itself is resolved by the SDK; no credential material passes
through project code and no environment variable is read here.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from .errors import ProviderError
from .response_capture import CapturingHttpxClient

__all__ = ["build_vertex_client"]


@contextmanager
def build_vertex_client(
    *,
    vertex_project: str,
    vertex_location: str,
    endpoint_allowlist: tuple[str, ...],
    http_options_kwargs: dict[str, Any],
) -> Iterator[tuple[Any, CapturingHttpxClient]]:
    """Yield ``(client, capture)``; close the capture client on the way out.

    The SDK does not close a client it did not create
    (``_api_client.py:2258``), so closing is this factory's obligation and is
    performed in ``finally``.
    """
    # Lazy: the vendor SDK is imported here and nowhere else in ``src/``.
    from google import genai
    from google.genai import types as genai_types

    capture = CapturingHttpxClient(endpoint_allowlist=endpoint_allowlist)
    try:
        options = genai_types.HttpOptions(
            **http_options_kwargs, httpx_client=capture
        )
        client = genai.Client(
            vertexai=True,
            project=vertex_project,
            location=vertex_location,
            http_options=options,
        )
        yield client, capture
    except ProviderError:
        raise
    finally:
        capture.close()
