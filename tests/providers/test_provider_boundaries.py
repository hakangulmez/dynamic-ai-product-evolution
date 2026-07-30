"""Static boundary guards for the provider package (ADR-034, E-P).

**E-P ships zero ``google.*`` imports under ``src/``.** A connector module that
merely *could* reach the SDK would weaken the guard from an absolute count to
an allowlist, so the SDK factory is deferred to E-L and the count here is zero,
not one.

Scanning is recursive and prose-excluding: a future subpackage cannot hide from
these checks, and docstrings that legitimately name forbidden things do not
trip them.
"""

from __future__ import annotations

import ast
import importlib
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "dynamic_ai_products"
PACKAGE = SRC / "providers"
EXTRACTION = SRC / "extraction"

# The single permitted outbound edge, and the exact names it may carry.
ALLOWED_EXTRACTION_MODULE = "extraction.provider_adapter"
ALLOWED_EXTRACTION_NAMES = frozenset(
    {"ExtractionProvider", "ProviderRequest", "ProviderResponse"}
)

_SCOPES = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)


def _modules(package: Path) -> list[Path]:
    return sorted(p for p in package.rglob("*.py") if "__pycache__" not in p.parts)


MODULES = _modules(PACKAGE)


def _tree(module: Path) -> ast.AST:
    return ast.parse(module.read_text(encoding="utf-8"))


def _imports(tree: ast.AST) -> list[tuple[str, tuple[str, ...]]]:
    """(module, imported names) for every import, relative tails flattened."""
    out: list[tuple[str, tuple[str, ...]]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend((alias.name, ()) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # A relative import already carries its tail in ``node.module``:
            # ``from ..extraction.provider_adapter import X`` gives exactly
            # "extraction.provider_adapter". No prefix is added.
            out.append(
                (node.module or "", tuple(alias.name for alias in node.names))
            )
    return out


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
    docstrings = _docstring_ids(tree)
    identifiers: set[str] = set()
    literals: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            identifiers.add(node.id)
        elif isinstance(node, ast.Attribute):
            identifiers.add(node.attr)
        elif (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in docstrings
        ):
            literals.append(node.value)
    return identifiers, literals


def test_package_is_enumerable():
    assert len(MODULES) == 8
    assert (PACKAGE / "__init__.py") in MODULES


# E-P shipped zero google.* imports under src/. E-L raises that to exactly one:
# the SDK factory. The guard becomes an exact allowlist rather than a count, and
# the entry is named so a second importer cannot appear unnoticed (ADR-035).
GOOGLE_IMPORT_ALLOWLIST = frozenset({"providers/sdk_factory.py"})


def test_only_the_sdk_factory_imports_google():
    offenders: dict[str, list[str]] = {}
    for module in sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts):
        names = [name for name, _ in _imports(_tree(module))]
        google = [n for n in names if n == "google" or n.startswith("google.")]
        if google:
            offenders[str(module.relative_to(SRC))] = google
    assert set(offenders) == GOOGLE_IMPORT_ALLOWLIST


def test_the_sdk_import_is_lazy():
    """Importing the factory module must not pull the SDK in."""
    source = (PACKAGE / "sdk_factory.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_level = {
        name
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for name, _ in _imports(ast.Module(body=[node], type_ignores=[]))
    }
    assert not any(n == "google" or n.startswith("google.") for n in module_level)


def test_providers_outbound_edge_is_exactly_the_provider_adapter_surface():
    observed: dict[str, set[str]] = {}
    for module in MODULES:
        for name, imported in _imports(_tree(module)):
            if not any(
                token in name
                for token in ("extraction", "evaluation", "universe", "ingestion", "collection")
            ):
                continue
            assert name == ALLOWED_EXTRACTION_MODULE, f"{module.name} imports {name}"
            observed.setdefault(module.name, set()).update(imported)
    for module_name, names in observed.items():
        extra = names - ALLOWED_EXTRACTION_NAMES
        assert not extra, f"{module_name} imports disallowed names {sorted(extra)}"


def test_extraction_never_imports_providers():
    for module in sorted(p for p in EXTRACTION.rglob("*.py") if "__pycache__" not in p.parts):
        text = module.read_text(encoding="utf-8")
        assert "dynamic_ai_products.providers" not in text, module
        assert "from ..providers" not in text, module
        assert "from .providers" not in text, module


@pytest.mark.parametrize("package", ["evaluation", "universe", "ingestion", "collection"])
def test_no_other_package_imports_providers_or_extraction(package):
    for module in sorted(p for p in (SRC / package).rglob("*.py") if "__pycache__" not in p.parts):
        text = module.read_text(encoding="utf-8")
        assert "dynamic_ai_products.providers" not in text, module
        assert "dynamic_ai_products.extraction" not in text, module
        assert "from ..providers" not in text, module
        assert "from ..extraction" not in text, module


def test_no_environment_access_anywhere_in_the_package():
    """ADC is resolved by the SDK itself; credential material never passes here."""
    forbidden = {"environ", "getenv", "putenv", "expandvars"}
    for module in MODULES:
        identifiers, _ = _code_tokens(_tree(module))
        assert not (identifiers & forbidden), module.name


def test_no_endpoint_literal_reaches_executable_code():
    """No hardcoded endpoint.

    A bare scheme prefix is not an endpoint: origin normalization legitimately
    builds ``f"https://{host}"``, and rejecting that would punish the code that
    exists to constrain endpoints. What is forbidden is a scheme followed by an
    authority — a real destination baked into the source.
    """
    for module in MODULES:
        _, literals = _code_tokens(_tree(module))
        for literal in literals:
            if "://" not in literal:
                continue
            remainder = literal.split("://", 1)[1]
            assert remainder == "", f"{module.name}: {literal!r}"


def test_no_clock_no_vcs_no_cli():
    forbidden_identifiers = {"now", "utcnow", "today", "monotonic", "perf_counter", "argv"}
    for module in MODULES:
        identifiers, _ = _code_tokens(_tree(module))
        assert not (identifiers & forbidden_identifiers), module.name
        for name, _ in _imports(_tree(module)):
            assert name not in {"time", "subprocess", "argparse", "shutil"}, module.name


# The capture client is an httpx.Client subclass, so exactly one module may
# import httpx. Everything else stays transport-free.
HTTPX_IMPORT_ALLOWLIST = frozenset({"response_capture.py"})


def test_no_network_import_beyond_the_capture_client():
    forbidden = {
        "socket", "ssl", "http", "requests", "aiohttp", "urllib3",
        "websockets", "grpc", "ftplib", "smtplib", "asyncio", "anthropic", "openai",
    }
    httpx_importers: set[str] = set()
    for module in MODULES:
        for name, _ in _imports(_tree(module)):
            root = name.split(".")[0] if name else ""
            assert root not in forbidden, f"{module.name} imports {name}"
            if root == "httpx":
                httpx_importers.add(module.name)
            if root == "urllib":
                assert name == "urllib.parse" or name.startswith("urllib.parse."), name
    assert httpx_importers == HTTPX_IMPORT_ALLOWLIST


def test_capability_probe_rule_is_namespace_safe():
    """A parent ModuleNotFoundError is not evidence that a child is absent.

    ``google`` resolves as a namespace package, so a naive probe of
    ``google.cloud.aiplatform`` raises rather than returning ``None``.
    """
    import importlib.util as util

    def probe(name: str) -> str:
        try:
            spec = util.find_spec(name)
        except ModuleNotFoundError as exc:
            return f"parent_unresolvable:{exc.name}"
        return "absent" if spec is None else "present"

    assert probe("json") == "present"
    assert probe("definitely_not_a_real_module_xyz") == "absent"
    assert probe("json.definitely_not_real") == "absent"
    assert probe("definitely_not_a_real_module_xyz.child").startswith("parent_unresolvable")


def test_every_module_declares_a_unique_resolvable_export_list():
    for module in MODULES:
        suffix = "" if module.name == "__init__.py" else f".{module.stem}"
        imported = importlib.import_module(f"dynamic_ai_products.providers{suffix}")
        exported = getattr(imported, "__all__", None)
        assert exported, f"{module.name} has no __all__"
        assert len(set(exported)) == len(exported), f"{module.name} __all__ duplicates"
        for name in exported:
            assert hasattr(imported, name), f"{module.name} exports missing {name}"


def test_no_behavioural_module_disappears_behind_a_module_level_skip():
    """Coverage can never silently vanish when the provider extra is absent.

    The invariant is about *module-level* skips: those drop an entire file,
    including guards that must hold with or without the SDK. A skip scoped to
    one function drops only that function, which is how the optional
    installed-SDK checks are allowed to exist.
    """
    tests_dir = Path(__file__).resolve().parent
    offenders = []
    for module in sorted(tests_dir.glob("test_*.py")):
        if module.name == "test_real_sdk_compatibility.py":
            continue
        tree = ast.parse(module.read_text(encoding="utf-8"))
        for node in tree.body:
            # Skip function and class bodies: walking into them would find a
            # function-scoped skip, which is exactly what is permitted.
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Attribute) and child.attr in (
                    "importorskip",
                    "skip",
                ):
                    offenders.append(f"{module.name}:{child.attr}")
    assert offenders == []
