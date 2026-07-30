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

MODULES = sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)
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


def _detector_literals(tree: ast.AST) -> set[str]:
    """String constants assigned to a ``_CREDENTIAL_*`` detector constant.

    These literals exist precisely to refuse credential material, so matching
    them would make a module that defends against leaks look like a leak.
    """
    out: set[str] = set()
    for node in ast.walk(tree):
        # Annotated constants are AnnAssign, not Assign; the detector tuples in
        # manifests.py are annotated, so both forms must be recognised.
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names = [node.target.id]
            value = node.value
        else:
            continue
        if value is None or not any(n.startswith("_CREDENTIAL_") for n in names):
            continue
        for child in ast.walk(value):
            if isinstance(child, ast.Constant) and isinstance(child.value, str):
                out.add(child.value)
    return out


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


def test_the_package_stays_flat_so_the_recursive_scan_has_nothing_to_miss():
    """A subpackage would be scanned by rglob, but a flat package is simpler to
    reason about and keeps the module count a meaningful invariant."""
    subdirectories = [
        d for d in PACKAGE.iterdir() if d.is_dir() and d.name != "__pycache__"
    ]
    assert subdirectories == []


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


def test_extraction_never_imports_the_provider_package():
    """The single permitted edge runs providers -> extraction.provider_adapter."""
    for module in MODULES:
        text = module.read_text(encoding="utf-8")
        assert "dynamic_ai_products.providers" not in text, module
        assert "from ..providers" not in text, module


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
    """No environment read, and no embedded credential *value*.

    The literal check matches credential **signatures**, not the word
    "credential": a module whose job is refusing credentials necessarily names
    them in its error prose, and flagging that would punish the defence rather
    than the leak. Detector constants are exempted for the same reason.
    """
    forbidden_identifiers = {"environ", "getenv", "putenv", "expandvars"}
    credential_signatures = ("ya29.", "AIza", "-----BEGIN", "Bearer ")
    for module in MODULES:
        tree = _tree(module)
        identifiers, literals = _code_tokens(tree)
        exempt = _detector_literals(tree)
        assert not (identifiers & forbidden_identifiers), module.name
        for literal in literals:
            if literal in exempt:
                continue
            for signature in credential_signatures:
                assert signature not in literal, f"{module.name}: {literal!r}"


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
    assert functions == {
        "require_provider",
        "require_budget_meter",
        "assert_run_permitted",
        "revoke_run_permission",
        "client_contract",
        "complete",
        # The budget-enforcement seam lives on this same typed surface so that
        # no new extraction module is needed and the 13-module count holds.
        "meter_identity",
        "assert_within_budget",
    }
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


# ---------------------------------------------------------------------------
# Production modules must not rely on ``assert`` (ADR-035, E-L v4.6.2).
#
# ``python -O`` strips every ``assert`` statement from the bytecode. Three had
# reached this package: two of the form
# ``assert write_artifact(root, PACKET_REFERENCE, payload) == packet_sha``, which
# under ``-O`` removed the *write itself* so no packet artifact was persisted at
# all, and one ``assert contract_sha == contract_sha_expected``, which removed a
# fail-closed integrity check. A conditional guarantee is not a guarantee, so the
# rule here is total rather than heuristic: zero ``ast.Assert`` nodes in either
# production package. Tests are free to use ``assert``; only ``src/`` is scanned.
# ---------------------------------------------------------------------------

PROVIDER_PACKAGE = ROOT / "src" / "dynamic_ai_products" / "providers"
PRODUCTION_MODULES = sorted(
    module
    for package in (PACKAGE, PROVIDER_PACKAGE)
    for module in package.rglob("*.py")
    if "__pycache__" not in module.parts
)


def test_the_production_assert_scan_covers_both_packages():
    """A guard that scanned an empty list would pass without proving anything."""
    scanned = {module.parent.name for module in PRODUCTION_MODULES}
    assert scanned == {"extraction", "providers"}
    assert len(PRODUCTION_MODULES) >= 20


@pytest.mark.parametrize("module", PRODUCTION_MODULES, ids=lambda m: m.name)
def test_no_production_module_relies_on_an_assert_statement(module):
    offenders = [
        f"{module.name}:{node.lineno}"
        for node in ast.walk(_tree(module))
        if isinstance(node, ast.Assert)
    ]
    assert not offenders, f"assert is stripped by -O: {offenders}"


def test_the_assert_scan_would_catch_a_reintroduced_call_bearing_assert():
    """The guard is proven against the exact defect it exists to prevent."""
    reintroduced = ast.parse(
        "def run():\n"
        "    assert write_artifact(root, REF, payload) == packet_sha\n"
    )
    found = [n for n in ast.walk(reintroduced) if isinstance(n, ast.Assert)]
    assert len(found) == 1
    # ...and the stripped form really does lose the call.
    calls = [n for n in ast.walk(found[0]) if isinstance(n, ast.Call)]
    assert [c.func.id for c in calls if isinstance(c.func, ast.Name)] == ["write_artifact"]


def test_the_zero_passage_packet_write_executes_under_dash_O():
    """Executed in a child interpreter with -O, where ``__debug__`` is False.

    This is the only way to prove the defect is gone: this process cannot observe
    ``-O`` bytecode, and asserting on source text would prove only that the word
    ``assert`` is absent, not that the write still happens. The child reuses the
    existing non-run helper rather than a new probe module, so the scope stays at
    the authorized path set.
    """
    import json
    import subprocess
    import sys
    import tempfile

    program = """
import json, sys, tempfile
from pathlib import Path
from dynamic_ai_products.extraction.run_extraction import PACKET_REFERENCE
from tests.extraction.test_run_extraction import _non_run

with tempfile.TemporaryDirectory() as work:
    outcome = _non_run(Path(work))
    packet = Path(outcome.run_root) / PACKET_REFERENCE
    print(json.dumps({
        "debug": __debug__,
        "packet_exists": packet.is_file(),
        "packet_bytes": packet.stat().st_size if packet.is_file() else 0,
        "written": sorted(
            str(f.relative_to(outcome.run_root))
            for f in Path(outcome.run_root).rglob("*")
            if f.is_file()
        ),
    }))
"""
    with tempfile.TemporaryDirectory():
        completed = subprocess.run(
            [sys.executable, "-O", "-c", program],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=180,
        )
    assert completed.returncode == 0, completed.stderr[-3000:]
    observed = json.loads(completed.stdout.strip().splitlines()[-1])
    assert observed["debug"] is False, "the child was not running under -O"
    assert observed["packet_exists"] is True, "-O removed the packet write"
    assert observed["packet_bytes"] > 0
    # The non-run route's artifact count is unchanged under -O.
    assert len(observed["written"]) == 2
