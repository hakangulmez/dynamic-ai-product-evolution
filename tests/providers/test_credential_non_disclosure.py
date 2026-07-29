"""Credential material never reaches an artifact or a message (ADR-034).

The strongest guarantee here is structural rather than procedural: this package
reads no environment variable at all, so Application Default Credentials are
resolved by the SDK itself and credential material never passes through our
process at any point. There is nothing to redact because nothing is held.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from dynamic_ai_products.extraction.errors import ExtractionError
from dynamic_ai_products.extraction.manifests import validate_provider_client_contract
from dynamic_ai_products.extraction.raw_artifacts import canonical_json_bytes
from dynamic_ai_products.providers.client_contract import build_client_contract
from dynamic_ai_products.providers.errors import PROVIDER_REASON_CODES, ProviderError
from dynamic_ai_products.providers.vertex_gemini import (
    VertexGeminiProvider,
    execute_with_retry,
    translate_provider_exception,
)

SRC = Path(__file__).resolve().parents[2] / "src" / "dynamic_ai_products"
PACKAGE = SRC / "providers"
PROJECT = "my-research-project"

SENTINEL = "ya29.SENTINEL-ACCESS-TOKEN-DO-NOT-LEAK"
SENTINEL_KEY = "AIzaSySENTINELAPIKEY"
SENTINEL_HEADER = "Authorization: Bearer " + SENTINEL


def _leaky(name: str = "ApiError", **attributes):
    cls = type(name, (Exception,), {})
    instance = cls(f"{SENTINEL_HEADER}\n{SENTINEL_KEY}\nbody: {SENTINEL}")
    instance.headers = {"authorization": SENTINEL_HEADER}
    instance.body = SENTINEL
    for key, value in attributes.items():
        setattr(instance, key, value)
    return instance


def _modules() -> list[Path]:
    return sorted(p for p in PACKAGE.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_package_reads_no_environment_variable():
    """Structural: credential material cannot pass through code that never looks."""
    forbidden = {"environ", "getenv", "putenv", "getenvb", "expandvars"}
    for module in _modules():
        tree = ast.parse(module.read_text(encoding="utf-8"))
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        names |= {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
        assert not (names & forbidden), module.name


def test_no_module_reads_a_dotenv_or_credential_file():
    for module in _modules():
        text = module.read_text(encoding="utf-8")
        for needle in (".env", "application_default_credentials.json", ".config/gcloud"):
            assert needle not in text, f"{module.name} mentions {needle}"


def test_no_source_line_contains_a_credential_literal():
    signatures = ("ya29.", "AIza", "-----BEGIN")
    for module in _modules():
        text = module.read_text(encoding="utf-8")
        for signature in signatures:
            assert signature not in text, f"{module.name} carries {signature}"


def test_the_client_contract_bytes_carry_no_sentinel():
    contract = build_client_contract(vertex_project=PROJECT)
    payload = canonical_json_bytes(validate_provider_client_contract(contract))
    for sentinel in (SENTINEL, SENTINEL_KEY, SENTINEL_HEADER):
        assert sentinel.encode("utf-8") not in payload


def test_a_sentinel_bearing_contract_is_refused_not_published():
    contract = build_client_contract(vertex_project=PROJECT)
    contract["client_version"] = SENTINEL
    with pytest.raises(ExtractionError) as excinfo:
        validate_provider_client_contract(contract)
    assert excinfo.value.reason_code == "credential_material_in_artifact"
    # Refused, not rewritten: the caller's object is untouched.
    assert contract["client_version"] == SENTINEL


def test_no_sentinel_survives_error_translation():
    translated = translate_provider_exception(_leaky(code=429))
    rendered = f"{translated} {translated.reason_code} {translated.args}"
    for sentinel in (SENTINEL, SENTINEL_KEY, SENTINEL_HEADER, "Bearer"):
        assert sentinel not in rendered


def test_no_sentinel_survives_retry_exhaustion():
    with pytest.raises(ProviderError) as excinfo:
        execute_with_retry(lambda: (_ for _ in ()).throw(_leaky(code=503)), sleep=lambda _: None)
    rendered = f"{excinfo.value} {excinfo.value.args}"
    for sentinel in (SENTINEL, SENTINEL_KEY, SENTINEL_HEADER):
        assert sentinel not in rendered


def test_the_refusal_path_leaks_nothing_either():
    provider = VertexGeminiProvider(vertex_project=PROJECT)
    for call in (provider.assert_run_permitted, lambda: provider.complete(None)):
        with pytest.raises(ProviderError) as excinfo:
            call()
        rendered = f"{excinfo.value} {excinfo.value.args}"
        for sentinel in (SENTINEL, SENTINEL_KEY, SENTINEL_HEADER):
            assert sentinel not in rendered


def test_every_declared_message_is_a_fixed_sentence():
    """No reason code renders caller or upstream data."""
    for code in PROVIDER_REASON_CODES:
        message = str(ProviderError(code))
        assert message
        for sentinel in (SENTINEL, SENTINEL_KEY, PROJECT):
            assert sentinel not in message


def test_the_project_identifier_is_caller_injected_never_a_repository_literal():
    for module in _modules():
        text = module.read_text(encoding="utf-8")
        assert PROJECT not in text, module.name
