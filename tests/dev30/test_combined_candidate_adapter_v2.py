"""PCT_Dev30_v0 combined-candidate adapter v0.2 successor tests.

No real Dev30 firm text (visible or holdout), no holdout access, no model
call, no prompt. Every fixture here is synthetic: a fabricated ticker
("ZZZZ") and fabricated Item 1 spans built specifically to exercise
ambiguity (a repeated "Widget Pro" mention, plus a more specific "Widget Pro
Lite" mention that occurs exactly once) and overlap-aware duplicate
detection (a literal "aaaaa" span, where ``str.count`` and an overlap-aware
scan disagree). Production ``build_persisted_candidates_v2`` takes no ledger
path at all; tests redirect it only by monkeypatching the two
module-private names together (``_LEDGER_PATH``, ``_CANONICAL_LEDGER_SHA256``),
mirroring v0.1's own sanctioned test pattern.

A separate section proves v0.1's three committed artifacts are unaffected:
this file imports v0.1's module read-only and re-checks its own pinned
hashes and schema behavior directly (a behavior regression check), not by
diffing git history.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.dev30 import combined_candidate_adapter as v1_mod
from dynamic_ai_products.dev30 import combined_candidate_adapter_v2 as mod
from dynamic_ai_products.dev30.combined_candidate_adapter_v2 import (
    CombinedCandidateAdapterError,
    _find_all_occurrences,
    build_persisted_candidates_v2,
)

ROOT = Path(__file__).resolve().parents[2]

STAGE1_SCHEMA_PATH = ROOT / "schemas" / "pct_dev30_v0_model_output_v2.schema.json"
STAGE2_SCHEMA_PATH = ROOT / "schemas" / "pct_dev30_v0_persisted_candidates_v2.schema.json"
REAL_LEDGER_PATH = ROOT / "evals" / "registries" / "pct_dev30_v0_item1_locator_ledger.json"

STAGE1_SCHEMA = json.loads(STAGE1_SCHEMA_PATH.read_text(encoding="utf-8"))
STAGE2_SCHEMA = json.loads(STAGE2_SCHEMA_PATH.read_text(encoding="utf-8"))

# --- Synthetic fixture: a fabricated Item 1 span with a deliberately
# repeated bare mention ("Widget Pro", 3x) and a more specific mention that
# occurs exactly once ("Widget Pro Lite"). No real Dev30 firm text. --------

TICKER = "ZZZZ"
SPAN_TEXT = (
    "We sell Widget Pro, which includes AI Summaries. Customers can "
    "auto-summarize long documents in seconds. Our internal Data Science "
    "team also uses machine learning to power our AI-driven forecasting "
    "engine. Widget Pro also ships Widget Pro Lite for smaller teams.\n"
)
SPAN_HASH = hashlib.sha256(SPAN_TEXT.encode("utf-8")).hexdigest()
LEGACY_SOURCE_ID = f"legacy-item1:dev30-v0:{SPAN_HASH}"

Q_PRODUCT_UNIQUE = "Widget Pro Lite"          # occurs exactly once
Q_PRODUCT_AMBIGUOUS = "Widget Pro"            # occurs three times
Q_CAPABILITY = "AI Summaries"                 # occurs once
Q_TASK = "auto-summarize long documents in seconds"  # occurs once
Q_EXCLUDED_INTERNAL = "Data Science team also uses machine learning"
Q_EXCLUDED_VAGUE_AI = "AI-driven forecasting engine"
Q_NOT_PRESENT = "this exact phrase never appears anywhere in the span"

assert SPAN_TEXT.count(Q_PRODUCT_AMBIGUOUS) == 3
assert SPAN_TEXT.count(Q_PRODUCT_UNIQUE) == 1


def _write_ledger(tmp_path: Path, *, name: str = "synthetic_ledger.json", ticker: str = TICKER,
                   legacy_source_id: str = LEGACY_SOURCE_ID, source_text_hash: str = SPAN_HASH) -> Path:
    ledger = {
        "ledger_contract": "pct_dev30_v0_item1_locator_ledger@0.1.0",
        "item_one_locator_version": "dev30-item1-marker-v1",
        "cohort_manifest_relative_path": "evals/registries/pct_dev30_v0_manifest.json",
        "cohort_manifest_sha256": "0" * 64,
        "cohort_version": "PCT_Dev30_v0_SYNTHETIC_FIXTURE",
        "counts": {"total_rows": 1},
        "rows": [
            {
                "ticker": ticker,
                "legacy_file_sha256": "1" * 64,
                "item_one_locator_version": "dev30-item1-marker-v1",
                "item_one_char_start": 0,
                "item_one_char_end": len(SPAN_TEXT),
                "source_text_hash": source_text_hash,
                "legacy_source_id": legacy_source_id,
            }
        ],
    }
    path = tmp_path / name
    path.write_text(json.dumps(ledger), encoding="utf-8")
    return path


def _patch_canonical_ledger(monkeypatch: pytest.MonkeyPatch, ledger_path: Path) -> None:
    monkeypatch.setattr(mod, "_LEDGER_PATH", ledger_path)
    monkeypatch.setattr(
        mod, "_CANONICAL_LEDGER_SHA256", hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    )


def _valid_stage1(*, candidates: list | None = None, excluded_mentions: list | None = None,
                   zero_candidate_reason=None, legacy_source_id: str = LEGACY_SOURCE_ID) -> dict:
    if candidates is None:
        candidates = [
            {
                "local_id": "P1", "kind": "product", "product_family": None,
                "product_name": "Widget Pro Lite", "availability_status": "general_availability",
                "evidence_quote": Q_PRODUCT_UNIQUE,
            },
            {
                "local_id": "C1", "kind": "capability", "product_local_id": "P1",
                "capability_text": "AI Summaries", "availability_status": "general_availability",
                "evidence_quote": Q_CAPABILITY,
            },
            {
                "local_id": "T1", "kind": "task", "product_local_id": "P1",
                "capability_local_ids": ["C1"], "task_text": Q_TASK,
                "customer_need": "save reading time", "availability_status": "general_availability",
                "evidence_quote": Q_TASK,
            },
        ]
    if excluded_mentions is None:
        excluded_mentions = []
    return {
        "contract": mod.STAGE1_CONTRACT,
        "schema_version": mod.SCHEMA_VERSION,
        "legacy_source_id": legacy_source_id,
        "candidates": candidates,
        "excluded_mentions": excluded_mentions,
        "zero_candidate_reason": zero_candidate_reason,
    }


def _raw(stage1: dict) -> bytes:
    return json.dumps(stage1).encode("utf-8")


def _build(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, stage1: dict | None = None,
           ticker: str = TICKER, span_text: str = SPAN_TEXT,
           model_output_reference: str = "scratch/fake.json", ledger_path: Path | None = None) -> dict:
    if stage1 is None:
        stage1 = _valid_stage1()
    if ledger_path is None:
        ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    return build_persisted_candidates_v2(
        ticker=ticker, span_text=span_text, raw_stage1_bytes=_raw(stage1),
        model_output_reference=model_output_reference,
    )


def _refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str, **kwargs) -> None:
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        _build(tmp_path, monkeypatch, **kwargs)
    assert excinfo.value.reason == reason


# --- Overlap-aware search, unit level -----------------------------------------


def test_find_all_occurrences_detects_overlaps_str_count_would_miss():
    # Non-overlapping str.count undercounts: "aaaaa".count("aaa") == 1.
    assert "aaaaa".count("aaa") == 1
    # Overlap-aware search correctly finds all three start positions.
    assert _find_all_occurrences("aaaaa", "aaa") == [0, 1, 2]


def test_find_all_occurrences_non_overlapping_and_absent_cases():
    assert _find_all_occurrences("abcabc", "abc") == [0, 3]
    assert _find_all_occurrences("abc", "xyz") == []
    assert _find_all_occurrences("hello world", "hello world") == [0]


def test_ambiguous_refusal_driven_by_overlap_not_by_str_count(tmp_path, monkeypatch):
    """A span where str.count would (wrongly) say "unambiguous" but the
    overlap-aware scan correctly refuses."""
    span = "aaaaa\n"
    span_hash = hashlib.sha256(span.encode("utf-8")).hexdigest()
    legacy_source_id = f"legacy-item1:dev30-v0:{span_hash}"
    assert span.count("aaa") == 1  # naive count would look safe
    ledger_path = _write_ledger(
        tmp_path, name="overlap_ledger.json", legacy_source_id=legacy_source_id, source_text_hash=span_hash,
    )
    _patch_canonical_ledger(monkeypatch, ledger_path)
    stage1 = _valid_stage1(
        candidates=[{
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "x", "availability_status": "general_availability",
            "evidence_quote": "aaa",
        }],
        legacy_source_id=legacy_source_id,
    )
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates_v2(
            ticker=TICKER, span_text=span, raw_stage1_bytes=_raw(stage1), model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_EVIDENCE_QUOTE_AMBIGUOUS_IN_SPAN


# --- Schema files: meta-valid, pinned, self-consistent -----------------------


def test_both_v2_schema_files_are_meta_schema_valid():
    Draft202012Validator.check_schema(STAGE1_SCHEMA)
    Draft202012Validator.check_schema(STAGE2_SCHEMA)


def test_v2_schema_file_hashes_match_the_adapter_pins():
    assert hashlib.sha256(STAGE1_SCHEMA_PATH.read_bytes()).hexdigest() == mod._STAGE1_SCHEMA_SHA256
    assert hashlib.sha256(STAGE2_SCHEMA_PATH.read_bytes()).hexdigest() == mod._STAGE2_SCHEMA_SHA256


def test_v2_canonical_ledger_hash_pin_matches_the_real_committed_file():
    assert hashlib.sha256(REAL_LEDGER_PATH.read_bytes()).hexdigest() == mod._CANONICAL_LEDGER_SHA256
    assert mod._LEDGER_PATH == REAL_LEDGER_PATH
    # Same physical ledger as v0.1 -- same pin value.
    assert mod._CANONICAL_LEDGER_SHA256 == v1_mod._CANONICAL_LEDGER_SHA256


def test_v2_schema_ids_and_contract_consts_match_module_constants():
    assert STAGE1_SCHEMA["$id"] == STAGE1_SCHEMA_PATH.name
    assert STAGE2_SCHEMA["$id"] == STAGE2_SCHEMA_PATH.name
    assert STAGE1_SCHEMA["properties"]["contract"]["const"] == mod.STAGE1_CONTRACT
    assert STAGE2_SCHEMA["properties"]["contract"]["const"] == mod.STAGE2_CONTRACT
    assert STAGE1_SCHEMA["properties"]["schema_version"]["const"] == "0.2.0"
    assert STAGE2_SCHEMA["properties"]["schema_version"]["const"] == "0.2.0"
    assert (
        STAGE2_SCHEMA["properties"]["locator_ledger_relative_path"]["const"]
        == mod.LOCATOR_LEDGER_RELATIVE_PATH
        == v1_mod.LOCATOR_LEDGER_RELATIVE_PATH
    )


def test_stage1_v2_schema_admits_no_evidence_locator_field_at_all():
    for def_name in ("product_candidate", "capability_candidate", "task_candidate", "excluded_mention"):
        assert "evidence_locator" not in STAGE1_SCHEMA["$defs"][def_name]["properties"]


def test_stage1_v2_schema_rejects_a_candidate_that_supplies_evidence_locator():
    instance = _valid_stage1()
    instance["candidates"][0]["evidence_locator"] = {"char_start": 0, "char_end": 1}
    assert not Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)


def test_stage1_v2_schema_accepts_a_short_exact_quote_no_minimum_beyond_one_char():
    instance = _valid_stage1(
        candidates=[{
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "x", "availability_status": "general_availability",
            "evidence_quote": "x",
        }],
    )
    assert Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)
    instance["candidates"][0]["evidence_quote"] = ""
    assert not Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)


def test_stage1_v2_schema_accepts_the_base_fixture():
    assert Draft202012Validator(STAGE1_SCHEMA).is_valid(_valid_stage1())


def test_stage2_v2_schema_still_requires_evidence_locator():
    for def_name in ("product_candidate", "capability_candidate", "task_candidate", "excluded_mention"):
        assert "evidence_locator" in STAGE2_SCHEMA["$defs"][def_name]["required"]


def test_stage2_v2_schema_rejects_unknown_top_level_property():
    instance = {
        "contract": mod.STAGE2_CONTRACT, "schema_version": "0.2.0", "ticker": "ZZZZ",
        "legacy_source_id": LEGACY_SOURCE_ID, "model_output_reference": "x",
        "model_output_sha256": "0" * 64,
        "locator_ledger_relative_path": mod.LOCATOR_LEDGER_RELATIVE_PATH,
        "locator_ledger_sha256": "0" * 64, "candidates": [], "excluded_mentions": [],
        "zero_candidate_reason": "no_product_capability_or_task_evidence", "extra": 1,
    }
    assert not Draft202012Validator(STAGE2_SCHEMA).is_valid(instance)


# --- Authority: no public ledger parameter, canonical path only -------------


def test_v2_no_public_parameter_permits_a_caller_selected_ledger():
    params = inspect.signature(build_persisted_candidates_v2).parameters
    assert "locator_ledger_path" not in params
    assert set(params) == {"ticker", "span_text", "raw_stage1_bytes", "model_output_reference"}


def test_v2_canonical_ledger_path_is_fixed_from_repo_root():
    assert mod._LEDGER_PATH == mod._REPO_ROOT / mod.LOCATOR_LEDGER_RELATIVE_PATH


def test_v2_canonical_ledger_tamper_refuses_before_ticker_lookup(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    ledger_path.write_bytes(ledger_path.read_bytes() + b" ")
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates_v2(
            ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=_raw(_valid_stage1()),
            model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_LEDGER_FILE_TAMPERED


# --- End-to-end adapter behavior ---------------------------------------------


def test_happy_path_produces_schema_valid_stage2_with_derived_offsets(tmp_path, monkeypatch):
    stage2 = _build(tmp_path, monkeypatch)
    Draft202012Validator(STAGE2_SCHEMA).validate(stage2)
    by_kind = {row["kind"]: row for row in stage2["candidates"]}
    expected_start = SPAN_TEXT.index(Q_PRODUCT_UNIQUE)
    assert by_kind["product"]["evidence_locator"]["char_start"] == expected_start
    assert by_kind["product"]["evidence_locator"]["char_end"] == expected_start + len(Q_PRODUCT_UNIQUE)
    assert by_kind["product"]["evidence_locator"]["legacy_source_id"] == LEGACY_SOURCE_ID


def test_disambiguation_by_specificity_bare_name_ambiguous_longer_quote_unique(tmp_path, monkeypatch):
    """Direct illustration of the design rationale (ADR-099): the bare name
    "Widget Pro" is ambiguous (3 occurrences); "Widget Pro Lite" is not."""
    bare = dict(_valid_stage1()["candidates"][0])
    bare["evidence_quote"] = Q_PRODUCT_AMBIGUOUS
    _refuses(
        tmp_path, monkeypatch, mod.REASON_EVIDENCE_QUOTE_AMBIGUOUS_IN_SPAN,
        stage1=_valid_stage1(candidates=[bare]),
    )
    # The unique, more specific sibling quote succeeds.
    stage2 = _build(tmp_path, monkeypatch)
    assert stage2["candidates"][0]["evidence_quote"] == Q_PRODUCT_UNIQUE


def test_candidate_id_matches_manual_recomputation_for_every_row(tmp_path, monkeypatch):
    stage2 = _build(tmp_path, monkeypatch)
    model_output_sha256 = stage2["model_output_sha256"]
    for row in stage2["candidates"]:
        fields = {k: v for k, v in row.items() if k not in ("candidate_id", "local_id", "ordinal", "kind")}
        expected = hashlib.sha256(
            model_output_sha256.encode("utf-8") + b"\x00"
            + str(row["ordinal"]).encode("utf-8") + b"\x00"
            + row["kind"].encode("utf-8") + b"\x00"
            + json.dumps(fields, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        ).hexdigest()[:32]
        assert row["candidate_id"] == expected, row["local_id"]


def test_determinism_same_raw_bytes_same_output_twice(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    stage1 = _valid_stage1()
    raw = _raw(stage1)
    first = build_persisted_candidates_v2(
        ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=raw, model_output_reference="scratch/fake.json",
    )
    second = build_persisted_candidates_v2(
        ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=raw, model_output_reference="scratch/fake.json",
    )
    assert first == second


def test_non_transferability_different_raw_bytes_different_candidate_ids(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    stage1 = _valid_stage1()
    raw_a = json.dumps(stage1).encode("utf-8")
    raw_b = json.dumps(stage1, indent=2).encode("utf-8")
    assert raw_a != raw_b
    result_a = build_persisted_candidates_v2(
        ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=raw_a, model_output_reference="a.json",
    )
    result_b = build_persisted_candidates_v2(
        ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=raw_b, model_output_reference="b.json",
    )
    ids_a = {c["candidate_id"] for c in result_a["candidates"]}
    ids_b = {c["candidate_id"] for c in result_b["candidates"]}
    assert ids_a.isdisjoint(ids_b)


def test_ordinal_is_original_array_index_not_topological_index(tmp_path, monkeypatch):
    candidates = [
        {
            "local_id": "C1", "kind": "capability", "product_local_id": "P1",
            "capability_text": "AI Summaries", "availability_status": "general_availability",
            "evidence_quote": Q_CAPABILITY,
        },
        {
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "Widget Pro Lite", "availability_status": "general_availability",
            "evidence_quote": Q_PRODUCT_UNIQUE,
        },
        {
            "local_id": "T1", "kind": "task", "product_local_id": "P1",
            "capability_local_ids": ["C1"], "task_text": Q_TASK,
            "customer_need": "save reading time", "availability_status": "general_availability",
            "evidence_quote": Q_TASK,
        },
    ]
    stage2 = _build(tmp_path, monkeypatch, stage1=_valid_stage1(candidates=candidates))
    ordinal_by_local_id = {row["local_id"]: row["ordinal"] for row in stage2["candidates"]}
    assert ordinal_by_local_id == {"C1": 0, "P1": 1, "T1": 2}


def test_relationship_fields_rewritten_to_persisted_candidate_ids(tmp_path, monkeypatch):
    stage2 = _build(tmp_path, monkeypatch)
    by_kind = {row["kind"]: row for row in stage2["candidates"]}
    product_id = by_kind["product"]["candidate_id"]
    capability_id = by_kind["capability"]["candidate_id"]
    assert by_kind["capability"]["product_candidate_id"] == product_id
    assert by_kind["task"]["product_candidate_id"] == product_id
    assert by_kind["task"]["capability_candidate_ids"] == [capability_id]


def test_excluded_mentions_get_derived_offsets_same_rule_as_candidates(tmp_path, monkeypatch):
    excluded = [
        {"reason": "internal_use", "evidence_quote": Q_EXCLUDED_INTERNAL},
        {"reason": "vague_ai_marketing", "evidence_quote": Q_EXCLUDED_VAGUE_AI},
    ]
    stage2 = _build(tmp_path, monkeypatch, stage1=_valid_stage1(excluded_mentions=excluded))
    assert len(stage2["excluded_mentions"]) == 2
    for mention in stage2["excluded_mentions"]:
        start = SPAN_TEXT.index(mention["evidence_quote"])
        assert mention["evidence_locator"]["char_start"] == start
        assert mention["evidence_locator"]["char_end"] == start + len(mention["evidence_quote"])
        assert mention["evidence_locator"]["legacy_source_id"] == LEGACY_SOURCE_ID


def test_excluded_mention_ambiguous_quote_refuses_same_as_candidate(tmp_path, monkeypatch):
    excluded = [{"reason": "internal_use", "evidence_quote": Q_PRODUCT_AMBIGUOUS}]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_EVIDENCE_QUOTE_AMBIGUOUS_IN_SPAN,
        stage1=_valid_stage1(excluded_mentions=excluded),
    )


def test_zero_candidates_with_reason_is_accepted(tmp_path, monkeypatch):
    stage2 = _build(
        tmp_path, monkeypatch,
        stage1=_valid_stage1(candidates=[], zero_candidate_reason="no_product_capability_or_task_evidence"),
    )
    assert stage2["candidates"] == []
    assert stage2["zero_candidate_reason"] == "no_product_capability_or_task_evidence"


def test_no_row_ever_carries_a_stage00c_source_id(tmp_path, monkeypatch):
    stage2 = _build(tmp_path, monkeypatch)

    def _walk(value):
        if isinstance(value, dict):
            assert "source_id" not in value
            for v in value.values():
                _walk(v)
        elif isinstance(value, list):
            for v in value:
                _walk(v)
        elif isinstance(value, str):
            assert not value.startswith("sec-primary:")

    _walk(stage2)


# --- Refusal reasons: one synthetic case per REASON_* constant --------------


def test_refuses_on_prose_text(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates_v2(
            ticker=TICKER, span_text=SPAN_TEXT,
            raw_stage1_bytes=b"Here is the extraction you asked for: nothing found.",
            model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_NOT_VALID_JSON


def test_refuses_on_code_fenced_json(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    wrapped = b"```json\n" + _raw(_valid_stage1()) + b"\n```"
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates_v2(
            ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=wrapped, model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_NOT_VALID_JSON


def test_refuses_on_top_level_json_array(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates_v2(
            ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=b"[1, 2, 3]", model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_NOT_VALID_JSON


def test_refuses_on_invalid_utf8_bytes(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates_v2(
            ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=b"\xff\xfe\x00{not utf8",
            model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_NOT_VALID_JSON


def test_refuses_on_schema_invalid_missing_required_field(tmp_path, monkeypatch):
    stage1 = _valid_stage1()
    del stage1["candidates"][0]["product_name"]
    _refuses(tmp_path, monkeypatch, mod.REASON_SCHEMA_INVALID, stage1=stage1)


def test_refuses_on_schema_file_tampered(tmp_path, monkeypatch):
    monkeypatch.setattr(mod, "_STAGE1_SCHEMA_SHA256", "0" * 64)
    _refuses(tmp_path, monkeypatch, mod.REASON_SCHEMA_FILE_TAMPERED)


def test_refuses_on_ledger_row_not_found(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path, ticker="OTHER")
    _patch_canonical_ledger(monkeypatch, ledger_path)
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates_v2(
            ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=_raw(_valid_stage1()),
            model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_LEDGER_ROW_NOT_FOUND


def test_refuses_on_span_text_hash_mismatch(tmp_path, monkeypatch):
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        _build(tmp_path, monkeypatch, span_text="an entirely different span, not the ledger-anchored one\n")
    assert excinfo.value.reason == mod.REASON_SPAN_TEXT_HASH_MISMATCH


def test_refuses_on_legacy_source_id_mismatch(tmp_path, monkeypatch):
    wrong = f"legacy-item1:dev30-v0:{'0' * 64}"
    stage1 = _valid_stage1(legacy_source_id=wrong)
    _refuses(tmp_path, monkeypatch, mod.REASON_LEGACY_SOURCE_ID_MISMATCH, stage1=stage1)


def test_refuses_on_dangling_local_reference(tmp_path, monkeypatch):
    candidates = [{
        "local_id": "C1", "kind": "capability", "product_local_id": "P9",
        "capability_text": "AI Summaries", "availability_status": "general_availability",
        "evidence_quote": Q_CAPABILITY,
    }]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_DANGLING_LOCAL_REFERENCE,
        stage1=_valid_stage1(candidates=candidates, zero_candidate_reason=None),
    )


def test_refuses_on_duplicate_local_id(tmp_path, monkeypatch):
    candidates = [
        {
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "Widget Pro Lite", "availability_status": "general_availability",
            "evidence_quote": Q_PRODUCT_UNIQUE,
        },
        {
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "Widget Pro Lite Two", "availability_status": "general_availability",
            "evidence_quote": Q_PRODUCT_UNIQUE,
        },
    ]
    _refuses(tmp_path, monkeypatch, mod.REASON_DUPLICATE_LOCAL_ID, stage1=_valid_stage1(candidates=candidates))


def test_refuses_on_evidence_quote_not_found_in_span_for_a_candidate(tmp_path, monkeypatch):
    candidates = [{
        "local_id": "P1", "kind": "product", "product_family": None,
        "product_name": "Widget Pro Lite", "availability_status": "general_availability",
        "evidence_quote": Q_NOT_PRESENT,
    }]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_EVIDENCE_QUOTE_NOT_FOUND_IN_SPAN,
        stage1=_valid_stage1(candidates=candidates),
    )


def test_refuses_on_evidence_quote_not_found_in_span_for_an_excluded_mention(tmp_path, monkeypatch):
    excluded = [{"reason": "internal_use", "evidence_quote": Q_NOT_PRESENT}]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_EVIDENCE_QUOTE_NOT_FOUND_IN_SPAN,
        stage1=_valid_stage1(excluded_mentions=excluded),
    )


def test_refuses_on_evidence_quote_ambiguous_in_span_for_a_candidate(tmp_path, monkeypatch):
    candidates = [{
        "local_id": "P1", "kind": "product", "product_family": None,
        "product_name": "Widget Pro", "availability_status": "general_availability",
        "evidence_quote": Q_PRODUCT_AMBIGUOUS,
    }]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_EVIDENCE_QUOTE_AMBIGUOUS_IN_SPAN,
        stage1=_valid_stage1(candidates=candidates),
    )


def test_reason_set_is_closed_and_pinned():
    assert mod._REASONS == frozenset(
        {
            "not_valid_json", "schema_invalid", "schema_file_tampered",
            "ledger_file_tampered", "ledger_row_not_found", "span_text_hash_mismatch",
            "legacy_source_id_mismatch", "dangling_local_reference",
            "duplicate_local_id", "evidence_quote_not_found_in_span",
            "evidence_quote_ambiguous_in_span",
        }
    )
    assert len(mod._REASONS) == 11
    # v1's two locator-specific codes have no v2 equivalent by the same name.
    assert "invalid_locator_bounds" not in mod._REASONS
    assert "evidence_quote_containment_failed" not in mod._REASONS


def test_error_rejects_an_unrecognized_reason_code():
    with pytest.raises(ValueError):
        CombinedCandidateAdapterError("not_a_real_reason", "message")


def test_real_committed_ledger_refuses_an_unknown_ticker():
    # No monkeypatch: exercises the real, pinned production ledger directly.
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates_v2(
            ticker="NOTAREALTICKER", span_text=SPAN_TEXT, raw_stage1_bytes=_raw(_valid_stage1()),
            model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_LEDGER_ROW_NOT_FOUND


def test_excluded_mention_reasons_and_zero_candidate_reasons_match_schema_enums():
    stage1_excluded_enum = set(
        STAGE1_SCHEMA["$defs"]["excluded_mention"]["properties"]["reason"]["enum"]
    )
    stage1_zero_enum = set(
        STAGE1_SCHEMA["properties"]["zero_candidate_reason"]["oneOf"][0]["enum"]
    )
    assert stage1_excluded_enum == mod.EXCLUDED_MENTION_REASONS
    assert stage1_zero_enum == mod.ZERO_CANDIDATE_REASONS


# --- v0.1 preservation: behavior regressions, not git-history diffing -------


def test_v01_schema_and_ledger_pins_are_unchanged():
    assert hashlib.sha256(v1_mod._STAGE1_SCHEMA_PATH.read_bytes()).hexdigest() == v1_mod._STAGE1_SCHEMA_SHA256
    assert hashlib.sha256(v1_mod._STAGE2_SCHEMA_PATH.read_bytes()).hexdigest() == v1_mod._STAGE2_SCHEMA_SHA256
    assert hashlib.sha256(v1_mod._LEDGER_PATH.read_bytes()).hexdigest() == v1_mod._CANONICAL_LEDGER_SHA256


def test_v01_reason_set_is_still_its_own_eleven_including_locator_codes():
    assert v1_mod._REASONS == frozenset(
        {
            "not_valid_json", "schema_invalid", "schema_file_tampered",
            "ledger_file_tampered", "ledger_row_not_found", "span_text_hash_mismatch",
            "legacy_source_id_mismatch", "dangling_local_reference",
            "duplicate_local_id", "invalid_locator_bounds",
            "evidence_quote_containment_failed",
        }
    )


def test_v01_public_api_signature_is_unchanged():
    params = inspect.signature(v1_mod.build_persisted_candidates).parameters
    assert set(params) == {"ticker", "span_text", "raw_stage1_bytes", "model_output_reference"}


def test_v01_schema_still_requires_evidence_locator_on_every_branch():
    v1_schema = json.loads(v1_mod._STAGE1_SCHEMA_PATH.read_text(encoding="utf-8"))
    for def_name in ("product_candidate", "capability_candidate", "task_candidate", "excluded_mention"):
        assert "evidence_locator" in v1_schema["$defs"][def_name]["required"]
    instance_without_locator = {
        "local_id": "P1", "kind": "product", "product_family": None,
        "product_name": "Widget Pro", "availability_status": "general_availability",
        "evidence_quote": "Widget Pro",
    }
    branch_schema = v1_schema["$defs"]["product_candidate"]
    assert not Draft202012Validator(branch_schema).is_valid(instance_without_locator)


def test_v01_and_v02_contract_identities_are_distinct():
    assert v1_mod.STAGE1_CONTRACT != mod.STAGE1_CONTRACT
    assert v1_mod.STAGE2_CONTRACT != mod.STAGE2_CONTRACT
    assert v1_mod.STAGE1_CONTRACT.split("@")[0] == mod.STAGE1_CONTRACT.split("@")[0]
    assert v1_mod.STAGE2_CONTRACT.split("@")[0] == mod.STAGE2_CONTRACT.split("@")[0]
    assert v1_mod.STAGE1_CONTRACT.endswith("@0.1.0")
    assert mod.STAGE1_CONTRACT.endswith("@0.2.0")
