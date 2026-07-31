"""Structural boundaries: one-way imports, no network, no model, no clock."""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402
from dynamic_ai_products.collection.publication import (  # noqa: E402
    canonical_json_bytes as collection_canonical_json,
)
from dynamic_ai_products.collection.publication import stage_artifact  # noqa: E402
from dynamic_ai_products.ingestion.publication import (  # noqa: E402
    canonical_json_bytes as ingestion_canonical_json,
)
from dynamic_ai_products.provenance import WriteOnceError  # noqa: E402

COLLECTION_DIR = Path("src/dynamic_ai_products/collection")
INGESTION_DIR = Path("src/dynamic_ai_products/ingestion")
UNIVERSE_DIR = Path("src/dynamic_ai_products/universe")


def _sources(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.py"))


def _module_names(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
            for alias in node.names:
                if node.level:
                    names.append(alias.name)
    return names


# --- Dependency direction -----------------------------------------------------


def test_collection_never_imports_ingestion() -> None:
    offenders = [
        (p.name, n)
        for p in _sources(COLLECTION_DIR)
        for n in _module_names(p)
        if "ingestion" in n.split(".")
    ]
    assert not offenders, f"collection must not depend on ingestion: {offenders}"


def test_ingestion_never_imports_collection() -> None:
    offenders = [
        (p.name, n)
        for p in _sources(INGESTION_DIR)
        for n in _module_names(p)
        if "collection" in n.split(".")
    ]
    assert not offenders, f"ingestion must not depend on collection: {offenders}"


def test_universe_imports_neither() -> None:
    offenders = [
        (p.name, n)
        for p in _sources(UNIVERSE_DIR)
        for n in _module_names(p)
        if {"collection", "ingestion"} & set(n.split("."))
    ]
    assert not offenders, f"universe must import neither: {offenders}"


def test_collection_depends_only_on_provenance_within_the_package_tree() -> None:
    allowed_relative = {"provenance"}
    for path in _sources(COLLECTION_DIR):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level and node.level > 1:
                assert node.module in allowed_relative, (
                    f"{path.name}: parent-package import of {node.module!r} is not allowed"
                )


def test_canonical_json_matches_the_ingestion_serializer() -> None:
    """The two serializers are pinned together without an import."""
    for payload in (
        {},
        {"b": 1, "a": 2},
        {"nested": {"z": [1, 2, {"k": "v"}]}},
        {"unicode": "café — dash"},
        {"null": None, "bool": True, "num": 1.5},
    ):
        assert collection_canonical_json(payload) == ingestion_canonical_json(payload)


# --- No network ---------------------------------------------------------------


# ADR-037 (E-C-D) introduces exactly one transport module here. The guard moves
# from "no transport at all" to an exact allowlist, recorded as a weakening --
# the same pattern ADR-035 used when the zero-``google.*``-import guard became a
# one-entry allowlist.
HTTPX_ALLOWED_MODULE = "http_adapter.py"


def test_no_network_module_is_imported() -> None:
    forbidden = {"requests", "urllib3", "socket", "http", "ftplib", "ssl"}
    offenders = [
        (p.name, n)
        for p in _sources(COLLECTION_DIR)
        for n in _module_names(p)
        if n.split(".")[0] in forbidden
    ]
    assert not offenders, f"no transport may be imported beyond httpx: {offenders}"


def test_exactly_one_collection_module_imports_httpx() -> None:
    importers = sorted(
        {
            p.name
            for p in _sources(COLLECTION_DIR)
            for n in _module_names(p)
            if n.split(".")[0] == "httpx"
        }
    )
    assert importers == [HTTPX_ALLOWED_MODULE], importers


def test_exactly_two_source_modules_import_httpx_repository_wide() -> None:
    """The recorded weakening: one importer becomes an exact allowlist of two."""
    src = COLLECTION_DIR.parent
    importers = sorted(
        {
            p.name
            for p in sorted(src.rglob("*.py"))
            if "__pycache__" not in p.parts
            for n in _module_names(p)
            if n.split(".")[0] == "httpx"
        }
    )
    assert importers == ["http_adapter.py", "response_capture.py"], importers


def test_only_the_documentation_policy_imports_the_adapter() -> None:
    offenders = [
        (p.name, n)
        for p in _sources(COLLECTION_DIR)
        if p.name not in {"documentation_policy.py", "http_adapter.py"}
        for n in _module_names(p)
        if "http_adapter" in n
    ]
    assert not offenders, offenders


def test_no_public_export_exposes_a_raw_send() -> None:
    from dynamic_ai_products import collection

    assert "http_adapter" not in collection.__all__
    assert "send_once" not in collection.__all__
    assert set(collection.__all__) == {
        "CollectionError",
        "DocumentationCollectionResult",
        "collect_documentation_evidence",
        "translate_write_once_error",
    }


def test_only_urllib_parse_is_used() -> None:
    """URL parsing is fine; urllib.request would be a transport."""
    for path in _sources(COLLECTION_DIR):
        text = path.read_text(encoding="utf-8")
        assert "urllib.request" not in text
        assert "urlopen" not in text


# Modules whose declared policy legitimately holds URL literals. Each is named
# explicitly rather than the guard being relaxed, so a new module cannot acquire
# a live URL silently.
URL_LITERAL_POLICY_MODULES = frozenset(
    {
        "request_plan.py",           # the deterministic robots URL template
        "documentation_policy.py",   # ADR-037: the three frozen evidence pairs
        "documentation_receipt.py",  # ADR-037: the JSON Schema dialect URI only
    }
)


def test_no_live_url_literal_outside_declared_policy() -> None:
    """Only a declared policy module may contain a scheme."""
    for path in _sources(COLLECTION_DIR):
        if path.name in URL_LITERAL_POLICY_MODULES:
            continue
        text = path.read_text(encoding="utf-8")
        assert "http://" not in text, path.name
        assert "https://" not in text, path.name


def test_the_documentation_policy_holds_only_the_frozen_pairs() -> None:
    """Its exemption is bounded: every URL literal is a frozen pair member."""
    import re

    from dynamic_ai_products.collection.documentation_policy import (
        FROZEN_EVIDENCE_ENTRIES,
    )

    source = (COLLECTION_DIR / "documentation_policy.py").read_text(encoding="utf-8")
    # Literals are wrapped across lines, so compare on the joined constants.
    frozen = {e["requested_url"] for e in FROZEN_EVIDENCE_ENTRIES} | {
        e["final_url"] for e in FROZEN_EVIDENCE_ENTRIES
    }
    assert len(frozen) == 6
    for fragment in re.findall(r'"(https?://[^"]*)"', source):
        assert any(url.startswith(fragment) for url in frozen), fragment
    assert "http://" not in source, "no scheme downgrade literal"


def test_the_receipt_module_holds_only_declared_identities() -> None:
    """Bounded too: the dialect URI and the frozen route identities, nothing else.

    The receipt contract pins the frozen routes itself so it stays checkable
    without importing the policy module it validates, which is why its URL
    literals are a superset of the dialect URI alone.
    """
    import re

    from dynamic_ai_products.collection.documentation_receipt import (
        FROZEN_ENTRY_IDENTITIES,
        SCHEMA_DIALECT,
    )

    source = (COLLECTION_DIR / "documentation_receipt.py").read_text(encoding="utf-8")
    allowed = {SCHEMA_DIALECT} | {
        e[field] for e in FROZEN_ENTRY_IDENTITIES for field in ("requested_url", "final_url")
    }
    assert len(allowed) == 7
    for fragment in re.findall(r'"(https?://[^"]*)"', source):
        assert any(url.startswith(fragment) for url in allowed), fragment
    assert "http://" not in source, "no scheme downgrade literal"
    assert SCHEMA_DIALECT == "https://json-schema.org/draft/2020-12/schema"


def test_the_two_frozen_route_declarations_agree() -> None:
    """Duplicated for independence, so drift between them must fail loudly."""
    from dynamic_ai_products.collection.documentation_policy import (
        FROZEN_EVIDENCE_ENTRIES,
    )
    from dynamic_ai_products.collection.documentation_receipt import (
        FROZEN_ENTRY_IDENTITIES,
    )

    assert list(FROZEN_ENTRY_IDENTITIES) == [dict(e) for e in FROZEN_EVIDENCE_ENTRIES]


# --- No model, no harness -----------------------------------------------------


def test_no_provider_prompt_or_harness_import() -> None:
    forbidden = {"anthropic", "openai", "evaluation", "prompts"}
    offenders = [
        (p.name, n)
        for p in _sources(COLLECTION_DIR)
        for n in _module_names(p)
        if set(n.split(".")) & forbidden
    ]
    assert not offenders, f"collection must not reach extraction or harness: {offenders}"


def test_no_cli_entry_point() -> None:
    for path in _sources(COLLECTION_DIR):
        text = path.read_text(encoding="utf-8")
        assert "__main__" not in text
        assert "typer" not in text


# --- No clock, no VCS ---------------------------------------------------------


def test_no_clock_or_vcs_read() -> None:
    offenders = []
    for path in _sources(COLLECTION_DIR):
        text = path.read_text(encoding="utf-8")
        for marker in ("datetime.now", "time.time", "utcnow", "subprocess", "rev-parse"):
            if marker in text:
                offenders.append((path.name, marker))
    assert not offenders, f"identity must be injected, not read: {offenders}"


# --- Error boundary -----------------------------------------------------------


def test_write_once_error_never_escapes(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    stage_artifact(staging, "a/b.json", b"{}\n")
    with pytest.raises(CollectionError) as excinfo:
        stage_artifact(staging, "a/b.json", b"{}\n")
    assert not isinstance(excinfo.value, WriteOnceError)
    assert excinfo.value.reason_code == "destination_exists"
    assert isinstance(excinfo.value.__cause__, WriteOnceError)


# --- Increment C-A writes nothing under data/ ---------------------------------


def test_increment_c_a_creates_no_data_artifact(tmp_path: Path) -> None:
    before = sorted(p.as_posix() for p in Path("data").rglob("*") if p.is_file())
    staging = tmp_path / "staging"
    staging.mkdir()
    stage_artifact(staging, "manifests/x.json", b"{}\n")
    after = sorted(p.as_posix() for p in Path("data").rglob("*") if p.is_file())
    assert before == after, "Increment C-A must not write under data/"
