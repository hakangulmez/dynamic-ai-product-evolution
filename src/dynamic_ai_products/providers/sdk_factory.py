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

__all__ = ["build_smoke_vertex_client", "build_vertex_client"]


def build_smoke_vertex_client(*, vertex_project: str, vertex_location: str) -> Any:
    """Build a development-smoke client through the sole vendor-SDK seam.

    Development smokes archive literal model responses but do not use the
    governed capture transport. Keeping this narrow constructor here preserves
    the repository invariant that no other module under ``src/`` imports the
    vendor SDK directly.
    """
    from google import genai

    return genai.Client(
        vertexai=True, project=vertex_project, location=vertex_location
    )


@contextmanager
def build_vertex_client(
    *,
    vertex_project: str,
    vertex_location: str,
    endpoint_allowlist: tuple[str, ...],
    http_options_kwargs: dict[str, Any],
    operation_endpoints: dict[str, str] | None = None,
) -> Iterator[tuple[Any, CapturingHttpxClient]]:
    """Yield ``(client, capture)``; close the capture client on the way out.

    The SDK does not close a client it did not create
    (``_api_client.py:2258``), so closing is this factory's obligation and is
    performed in ``finally``.

    ADR-043 (E-M) adds ``operation_endpoints``. It is forwarded to the capture
    client and nowhere else: the per-request equality check is transport-side
    grammar, and the SDK builds the request URL itself from base URL, api
    version, project and location, so the two must be compared where the request
    actually is. Left ``None``, the client behaves exactly as E-L shipped it.
    """
    # Lazy: the vendor SDK is imported here and nowhere else in ``src/``.
    from google import genai
    from google.genai import types as genai_types

    capture = CapturingHttpxClient(
        endpoint_allowlist=endpoint_allowlist,
        operation_endpoints=operation_endpoints,
    )
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
