"""Static boundary guards for the offline extraction package (ADR-033, E-A).

E-A carries **no network capability whatsoever**. These tests read the package
source with ``ast`` rather than trusting a docstring, so a future edit that
adds an SDK, a URL, a credential read, a clock, a CLI, or a second evaluation
edge fails here instead of at run time.

Scanning is deliberately AST-based and **prose-excluding**: docstrings and
comments legitimately name the very things the package must not do, and a raw
substring scan would either fail on its own documentation or force the
documentation to be weakened to satisfy the guard.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "src" / "dynamic_ai_products" / "extraction"

# The single permitted extraction -> evaluation edge (ADR-033).
PERMITTED_EVALUATION_EDGE = {"source_snapshot_bridge.py": {"evaluation.source_snapshot"}}
FOREIGN_PACKAGE_TOKENS = ("evaluation", "universe", "ingestion", "collection")

MODULES = sorted(PACKAGE.glob("*.py"))
_SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _tree(module: Path) -> ast.AST:
    return ast.parse(module.read_text(encoding="utf-8"))


def _module_names(tree: ast.AST) -> list[str]:
    """Every imported dotted name; relative imports keep their tail only."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    return names


def _docstring_ids(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _SCOPES):
            continue
        body = getattr(node, "body", [])
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            ids.add(id(body[0].value))
    return ids


def _code_tokens(tree: ast.AST) -> tuple[set[str], list[str]]:
    """Executable identifiers and non-docstring string literals.

    Comments never enter the AST, so they are excluded automatically.
    """
    docstrings = _docstring_ids(tree)
    identifiers: set[str] = set()
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            identifiers.add(node.name)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            literals.append(node.value)
    return identifiers, literals


def test_package_is_enumerable_and_complete():
    assert len(MODULES) == 13
    assert (PACKAGE / "__init__.py") in MODULES


def test_only_one_module_holds_the_evaluation_edge():
    observed: dict[str, set[str]] = {}
    for module in MODULES:
        foreign = {
            name
            for name in _module_names(_tree(module))
            if any(token in name for token in FOREIGN_PACKAGE_TOKENS)
        }
        if foreign:
            observed[module.name] = foreign
    assert observed == PERMITTED_EVALUATION_EDGE


def test_no_reverse_edge_from_any_other_package():
    for package in ("evaluation", "universe", "ingestion", "collection"):
        for module in (ROOT / "src" / "dynamic_ai_products" / package).rglob("*.py"):
            text = module.read_text(encoding="utf-8")
            assert "dynamic_ai_products.extraction" not in text, module
            assert "from ..extraction" not in text, module
            assert "from .extraction" not in text, module


FORBIDDEN_NETWORK_ROOTS = frozenset(
    {
        "socket",
        "ssl",
        "http",
        "httpx",
        "requests",
        "aiohttp",
        "urllib3",
        "websockets",
        "grpc",
        "paramiko",
        "ftplib",
        "smtplib",
        "telnetlib",
        "xmlrpc",
        "asyncio",
        "anthropic",
        "openai",
        "boto3",
    }
)
ALLOWED_URLLIB_MODULE = "urllib.parse"


def _network_violations(tree: ast.AST) -> list[str]:
    """Every imported name that opens, or can reach, a network capability.

    ``urllib`` is allowed **only** as an explicitly scoped ``urllib.parse``
    import. Both ``import urllib`` and ``from urllib import request`` name the
    package itself, which re-exposes every submodule including ``request``, so
    matching on ``urllib.request`` alone leaves the obvious spelling open.
    """
    violations: list[str] = []
    for name in _module_names(tree):
        if not name:
            continue
        root = name.split(".")[0]
        if root == "urllib":
            if name != ALLOWED_URLLIB_MODULE and not name.startswith(
                ALLOWED_URLLIB_MODULE + "."
            ):
                violations.append(name)
        elif root in FORBIDDEN_NETWORK_ROOTS:
            violations.append(name)
    return sorted(violations)


def test_no_network_import_beyond_urllib_parse():
    for module in MODULES:
        assert _network_violations(_tree(module)) == [], module.name


REJECTED_IMPORT_SOURCES = [
    "from urllib import request",
    "from urllib import parse",
    "from urllib import parse, request",
    "import urllib",
    "import urllib as u",
    "import urllib.request",
    "from urllib.request import urlopen",
    "from urllib.error import URLError",
    "import http.client",
    "from http.client import HTTPSConnection",
    "import socket",
    "import requests",
    "import httpx",
    "import anthropic",
    "from openai import OpenAI",
]

ACCEPTED_IMPORT_SOURCES = [
    "import urllib.parse",
    "import urllib.parse as up",
    "from urllib.parse import urlsplit",
    "from urllib.parse import quote as q, urlsplit",
    "import json",
    "from pathlib import Path",
    "from ..provenance import write_bytes_once",
]


@pytest.mark.parametrize("source", REJECTED_IMPORT_SOURCES)
def test_the_guard_rejects_every_network_import_form(source):
    """Synthetic regression: the guard itself is exercised, not just the package.

    The extraction package imports no ``urllib`` module today, so a guard that
    silently stopped catching ``from urllib import request`` would keep passing
    against real source. These cases pin the guard's own behaviour.
    """
    assert _network_violations(ast.parse(source)) != [], source


@pytest.mark.parametrize("source", ACCEPTED_IMPORT_SOURCES)
def test_the_guard_accepts_scoped_urllib_parse_and_ordinary_imports(source):
    assert _network_violations(ast.parse(source)) == [], source


def test_the_rejected_and_accepted_urllib_forms_are_the_documented_boundary():
    assert _network_violations(ast.parse("from urllib import request")) == ["urllib"]
    assert _network_violations(ast.parse("import urllib.request")) == ["urllib.request"]
    assert _network_violations(ast.parse("import urllib.parse")) == []


def test_no_url_literal_reaches_executable_code():
    for module in MODULES:
        _, literals = _code_tokens(_tree(module))
        for literal in literals:
            assert "://" not in literal, f"{module.name}: {literal!r}"


def test_no_credential_or_environment_secret_read():
    forbidden_identifiers = {"environ", "getenv", "putenv", "expandvars"}
    forbidden_fragments = ("api_key", "secret", "bearer", "authorization", "credential")
    for module in MODULES:
        identifiers, literals = _code_tokens(_tree(module))
        assert not (identifiers & forbidden_identifiers), module.name
        for literal in literals:
            lowered = literal.lower()
            for fragment in forbidden_fragments:
                assert fragment not in lowered, f"{module.name}: {literal!r}"


def test_no_clock_and_no_vcs_read():
    """``code_commit`` and ``run_created_at`` are injected, never discovered."""
    forbidden_identifiers = {
        "now",
        "utcnow",
        "today",
        "monotonic",
        "perf_counter",
        "popen",
        "system",
        "run",
        "check_output",
        "Popen",
    }
    for module in MODULES:
        identifiers, _ = _code_tokens(_tree(module))
        assert not (identifiers & forbidden_identifiers), module.name
        for name in _module_names(_tree(module)):
            assert name not in {"time", "subprocess", "shutil"}, module.name


def test_no_cli_entry_point():
    for module in MODULES:
        identifiers, literals = _code_tokens(_tree(module))
        assert "argv" not in identifiers, module.name
        assert "__main__" not in literals, module.name
        for name in _module_names(_tree(module)):
            assert name != "argparse", module.name


def test_no_write_targets_the_repository_data_directory():
    """E-A writes nothing under ``data/``. Every root is caller-supplied."""
    for module in MODULES:
        _, literals = _code_tokens(_tree(module))
        for literal in literals:
            assert literal != "data", module.name
            assert not literal.startswith("data/"), f"{module.name}: {literal!r}"


def test_no_provider_is_constructed_inside_the_package():
    """The provider is injected; E-A builds no client and calls no vendor."""
    text = (PACKAGE / "provider_adapter.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    functions = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert functions == {"require_provider", "complete"}
    assert "Protocol" in text and "runtime_checkable" in text


def test_every_module_declares_a_unique_resolvable_export_list():
    import importlib

    for module in MODULES:
        if module.name == "__init__.py":
            imported = importlib.import_module("dynamic_ai_products.extraction")
        else:
            imported = importlib.import_module(
                f"dynamic_ai_products.extraction.{module.stem}"
            )
        exported = getattr(imported, "__all__", None)
        assert exported, f"{module.name} has no __all__"
        assert len(set(exported)) == len(exported), f"{module.name} __all__ duplicates"
        for name in exported:
            assert hasattr(imported, name), f"{module.name} exports missing {name}"
