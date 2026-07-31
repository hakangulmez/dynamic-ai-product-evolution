"""The zero-evidence route: publish coverage, call no provider, run no harness."""

from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

sys.path.insert(0, str(Path(__file__).parent))

from dynamic_ai_products.collection.coverage_v2 import (  # noqa: E402
    build_source_family_coverage_v2,
)
from dynamic_ai_products.collection.errors import CollectionError  # noqa: E402
from dynamic_ai_products.collection.manifests import (  # noqa: E402
    build_collection_identity,
    build_official_web_collection_manifest,
)
from dynamic_ai_products.collection.publication import (  # noqa: E402
    derive_collection_run_id,
)
from collection_test_helpers import CODE_COMMIT, COMPANY_ID, CUTOFF, RUN_CREATED_AT  # noqa: E402

PARENT = "aacc8cdb774f6cb28180d326c798f6b32b55c62a1f5cc7af2168f56c75df6bbb"
COLLECTION_DIR = Path("src/dynamic_ai_products/collection")


def _zero_evidence_coverage():
    """Nothing temporally valid was admitted in any required family."""
    return build_source_family_coverage_v2(
        company_id=COMPANY_ID,
        observation_cutoff_date=CUTOFF,
        content_family_states={
            "official_ir": "not_found",
            "product_pages": "temporally_invalid",
            "developer_docs": "robots_or_access_blocked",
        },
        content_family_reasons={
            "official_ir": "no dated document on or before the cutoff",
            "product_pages": "every capture postdates the cutoff",
            "developer_docs": "robots disallow",
        },
        admitted_counts={},
        channel_admitted={"live": 1, "archive": 2},
        channel_temporally_valid={"live": 0, "archive": 0},
        inherited_sec_edgar_state="available_and_retrieved",
        parent_manifest_sha256=PARENT,
        errors=[
            {"content_family": "official_ir", "reason_code": "not_found"},
            {"content_family": "product_pages", "reason_code": "snapshot_after_cutoff"},
            {"content_family": "developer_docs", "reason_code": "robots_or_access_blocked"},
        ],
    )


def test_zero_evidence_coverage_is_still_published_and_valid() -> None:
    artifact = _zero_evidence_coverage()
    schema = json.loads(
        Path("schemas/source_family_coverage.v2.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(artifact)
    assert artifact["errors"], "the error records are the scientific result"


def test_no_required_family_remains_not_attempted() -> None:
    states = {
        e["content_family"]: e["coverage_state"]
        for e in _zero_evidence_coverage()["content_families"]
        if e["membership"] == "required"
    }
    assert states and "not_attempted" not in states.values()


def test_legacy_bridge_is_truthful_when_nothing_is_valid() -> None:
    bridge = _zero_evidence_coverage()["legacy_bridge"]
    assert bridge["coverage_state"] == "available_but_failed"
    assert bridge["temporally_valid_archive_count"] == 0
    assert bridge["reason_code"]


def test_no_supported_case_verdict_is_accepted() -> None:
    identity = build_collection_identity(
        code_commit=CODE_COMMIT,
        run_created_at=RUN_CREATED_AT,
        request_plan_sha256="d" * 64,
    )
    manifest = build_official_web_collection_manifest(
        run_id=derive_collection_run_id(identity),
        identity=identity,
        company_id=COMPANY_ID,
        observation_cutoff_date=CUTOFF,
        artifact_bindings={f"a{i}": f"{i}" * 64 for i in range(6)},
        verdict="no_supported_case",
    )
    assert manifest["verdict"] == "no_supported_case"
    assert manifest["prompt_hash"] is None
    assert manifest["model_route"] is None


def test_extraction_verdicts_are_not_available_here() -> None:
    identity = build_collection_identity(
        code_commit=CODE_COMMIT,
        run_created_at=RUN_CREATED_AT,
        request_plan_sha256="d" * 64,
    )
    with pytest.raises(CollectionError) as excinfo:
        build_official_web_collection_manifest(
            run_id=derive_collection_run_id(identity),
            identity=identity,
            company_id=COMPANY_ID,
            observation_cutoff_date=CUTOFF,
            artifact_bindings={},
            verdict="ready_for_extraction",
        )
    assert excinfo.value.reason_code == "verdict_invalid"


# Narrowly scoped provider/harness surfaces. A bare "completion" substring was
# removed: it flagged ADR-037's locked ``completion_status`` receipt vocabulary
# while proving nothing about model reachability. Concrete call surfaces are
# matched instead, so the guard tightens rather than relaxes.
PROVIDER_HARNESS_MARKERS: tuple[str, ...] = (
    "anthropic",
    "openai",
    "claude",
    "chat.completions",
    "completions.create",
    "messages.create",
    "generate_content",
    "count_tokens(",
    "chat(",
    "run_evaluation",
    "evaluate_case",
    "extract_products",
    "extract_tasks",
)


def test_package_has_no_provider_or_harness_reachability() -> None:
    """Structural, not conventional: nothing here can call a model or the harness."""
    offenders = []
    for path in sorted(COLLECTION_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8").lower()
        for marker in PROVIDER_HARNESS_MARKERS:
            if marker in text:
                offenders.append((path.name, marker))
    assert not offenders, f"no provider or harness reachability: {offenders}"


def test_the_marker_set_rejects_real_model_call_surfaces() -> None:
    """The guard is proven against what it exists to catch."""
    for sample in (
        "client.chat.completions.create(model=...)",
        "openai.completions.create(prompt=...)",
        "anthropic.messages.create(model=...)",
        "client.models.generate_content(contents=...)",
        "from anthropic import Anthropic",
        "run_evaluation(case)",
        "extract_products(packet)",
    ):
        assert any(m in sample.lower() for m in PROVIDER_HARNESS_MARKERS), sample


def test_the_marker_set_allows_the_locked_receipt_vocabulary() -> None:
    """``completion_status``/``completed`` are attempt statuses, not model calls.

    A bare ``completion`` substring marker flagged ADR-037's receipt vocabulary,
    which is a false positive: the guard exists to prove this package cannot
    call a model, and an attempt's terminal status has nothing to do with that.
    """
    for sample in (
        'completion_status = "completed"',
        '"completion_status": {"enum": ["completed", "stopped"]}',
        "if completion_status not in COMPLETION_STATUSES:",
        "COMPLETION_STATUSES = ('completed', 'stopped')",
    ):
        offenders = [m for m in PROVIDER_HARNESS_MARKERS if m in sample.lower()]
        assert not offenders, (sample, offenders)


def test_no_module_defines_a_prompt_constant() -> None:
    for path in sorted(COLLECTION_DIR.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        assert "PROMPT" not in target.id.upper()
