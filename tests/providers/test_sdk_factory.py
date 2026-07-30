"""The single vendor-SDK importer, and its laziness (ADR-035).

E-P shipped zero ``google.*`` imports under ``src/``. E-L raises that to exactly
one — this factory — and the boundary guard becomes an exact allowlist naming
this file rather than a count.

Nothing here builds a real client, resolves Application Default Credentials, or
opens a socket. The factory function is inspected, and the SDK types it would
construct are validated for field acceptance only.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from dynamic_ai_products.providers import sdk_factory
from dynamic_ai_products.providers.response_capture import CapturingHttpxClient
from dynamic_ai_products.providers.retry_policy import (
    API_VERSION,
    SDK_RETRY_ATTEMPTS,
    TIMEOUT_DURATION,
)
from dynamic_ai_products.providers.vertex_gemini import build_http_options_kwargs

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "src" / "dynamic_ai_products" / "providers" / "sdk_factory.py"


def test_the_module_level_imports_carry_no_google_name():
    """Importing the factory must not drag the SDK in."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    module_level: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            module_level.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module_level.add(node.module or "")
    assert not any(n == "google" or n.startswith("google.") for n in module_level)


def test_the_google_import_is_inside_the_factory_body():
    source = inspect.getsource(sdk_factory.build_vertex_client)
    assert "from google import genai" in source
    assert "from google.genai import types" in source


def test_importing_the_factory_pulls_in_no_google_module():
    script = (
        "import sys;"
        "import dynamic_ai_products.providers.sdk_factory as m;"
        "print(sorted(n for n in sys.modules if n.startswith('google')))"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        cwd=str(ROOT),
        env={"PYTHONPATH": "src", "PATH": "/usr/bin:/bin"},
        check=True,
    )
    assert result.stdout.strip() == "[]"


def test_the_factory_is_a_context_manager_that_closes_the_capture_client():
    """The SDK does not close a client it did not create, so we must."""
    source = inspect.getsource(sdk_factory.build_vertex_client)
    assert "@contextmanager" in inspect.getsource(sdk_factory).split("def build_vertex_client")[0]
    assert "finally:" in source
    assert "capture.close()" in source


def test_the_factory_passes_the_locked_http_options_and_the_capture_client():
    source = inspect.getsource(sdk_factory.build_vertex_client)
    assert "httpx_client=capture" in source
    assert "vertexai=True" in source
    for name in ("project=vertex_project", "location=vertex_location"):
        assert name in source


def test_the_locked_http_options_are_the_e_p_values():
    options = build_http_options_kwargs()
    assert options["api_version"] == API_VERSION == "v1"
    assert options["timeout"] == TIMEOUT_DURATION == 300000
    assert options["retry_options"] == {"attempts": SDK_RETRY_ATTEMPTS} == {"attempts": 1}


def test_the_capture_client_is_the_transport_the_factory_hands_over():
    assert issubclass(CapturingHttpxClient, __import__("httpx").Client)


def test_the_factory_reads_no_environment_variable():
    """ADC is resolved by the SDK; credential material never passes here."""
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
    names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not (names & {"environ", "getenv", "putenv", "expandvars"})


def test_the_factory_carries_no_endpoint_literal():
    tree = ast.parse(MODULE.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if "://" in node.value:
                assert node.value.split("://", 1)[1] == "", node.value


# --- optional: the installed SDK actually accepts what we would pass ----------


def test_the_installed_sdk_accepts_the_locked_options_and_a_custom_client():
    """Field acceptance only: no client is constructed and no call is made.

    The skip is scoped to this function, not the module: a module-level skip
    would take the AST and lazy-import guards above with it, and those must hold
    whether or not the provider extra is installed.
    """
    import httpx

    genai_types = pytest.importorskip(
        "google.genai.types", reason="the 'provider' extra is not installed"
    )
    capture = CapturingHttpxClient(endpoint_allowlist=("https://example.com/v1",))
    try:
        options = genai_types.HttpOptions(
            **build_http_options_kwargs(), httpx_client=capture
        )
    finally:
        capture.close()
    assert options.timeout == 300000
    assert options.api_version == "v1"
    assert options.retry_options.attempts == 1
    assert isinstance(options.httpx_client, httpx.Client)
