"""PCT_Dev30_v0 combined-candidate adapter tests (Round 2 contract, plus the
canonical-ledger authority fix).

No real Dev30 firm text, no holdout access, no model call, no prompt. Every
fixture here is synthetic: a fabricated ticker ("ZZZZ") and a fabricated Item
1 span, with a hand-built one-row ledger pointing at that span's real
sha256. The production ``build_persisted_candidates`` API takes no ledger
path at all -- it always resolves and hash-verifies the one canonical,
committed ledger internally. Tests that need a synthetic ledger instead of
the real one monkeypatch the two module-private names
(``_LEDGER_PATH``, ``_CANONICAL_LEDGER_SHA256``) together, which is the only
sanctioned way to redirect this module in a test; production code never
exposes an equivalent public parameter. The exception is a small number of
structural checks against the real, already-committed
``pct_dev30_v0_item1_locator_ledger.json`` -- they only prove an unknown
ticker is refused and that the pinned hash matches the real file; none of
them touches a real firm's evidence.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from dynamic_ai_products.dev30 import combined_candidate_adapter as mod
from dynamic_ai_products.dev30.combined_candidate_adapter import (
    CombinedCandidateAdapterError,
    build_persisted_candidates,
)

ROOT = Path(__file__).resolve().parents[2]

STAGE1_SCHEMA_PATH = ROOT / "schemas" / "pct_dev30_v0_model_output.schema.json"
STAGE2_SCHEMA_PATH = ROOT / "schemas" / "pct_dev30_v0_persisted_candidates.schema.json"
REAL_LEDGER_PATH = ROOT / "evals" / "registries" / "pct_dev30_v0_item1_locator_ledger.json"

STAGE1_SCHEMA = json.loads(STAGE1_SCHEMA_PATH.read_text(encoding="utf-8"))
STAGE2_SCHEMA = json.loads(STAGE2_SCHEMA_PATH.read_text(encoding="utf-8"))

# --- Synthetic fixture: a fabricated Item 1 span and its five evidence
# quotes, none drawn from any real filing. -----------------------------------

TICKER = "ZZZZ"
SPAN_TEXT = (
    "We sell Widget Pro, which includes AI Summaries. Customers can "
    "auto-summarize long documents in seconds. Our internal Data Science "
    "team also uses machine learning to power our AI-driven forecasting "
    "engine.\n"
)
SPAN_HASH = hashlib.sha256(SPAN_TEXT.encode("utf-8")).hexdigest()
LEGACY_SOURCE_ID = f"legacy-item1:dev30-v0:{SPAN_HASH}"

Q_PRODUCT = "Widget Pro"
Q_CAPABILITY = "AI Summaries"
Q_TASK = "auto-summarize long documents in seconds"
Q_EXCLUDED_INTERNAL = "Data Science team also uses machine learning"
Q_EXCLUDED_VAGUE_AI = "AI-driven forecasting engine"


def _span(quote: str) -> dict:
    start = SPAN_TEXT.index(quote)
    return {"char_start": start, "char_end": start + len(quote)}


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
    """The only sanctioned way to redirect the adapter's ledger in a test:
    both module-private names together, matching the schema-tamper pattern.
    ``build_persisted_candidates`` itself takes no ledger parameter."""
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
                "product_name": "Widget Pro", "availability_status": "general_availability",
                "evidence_quote": Q_PRODUCT, "evidence_locator": _span(Q_PRODUCT),
            },
            {
                "local_id": "C1", "kind": "capability", "product_local_id": "P1",
                "capability_text": "AI Summaries", "availability_status": "general_availability",
                "evidence_quote": Q_CAPABILITY, "evidence_locator": _span(Q_CAPABILITY),
            },
            {
                "local_id": "T1", "kind": "task", "product_local_id": "P1",
                "capability_local_ids": ["C1"], "task_text": Q_TASK,
                "customer_need": "save reading time", "availability_status": "general_availability",
                "evidence_quote": Q_TASK, "evidence_locator": _span(Q_TASK),
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
    return build_persisted_candidates(
        ticker=ticker, span_text=span_text, raw_stage1_bytes=_raw(stage1),
        model_output_reference=model_output_reference,
    )


def _refuses(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, reason: str, **kwargs) -> None:
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        _build(tmp_path, monkeypatch, **kwargs)
    assert excinfo.value.reason == reason


# --- Schema files: meta-valid, pinned, self-consistent -----------------------


def test_both_schema_files_are_meta_schema_valid():
    Draft202012Validator.check_schema(STAGE1_SCHEMA)
    Draft202012Validator.check_schema(STAGE2_SCHEMA)


def test_schema_file_hashes_match_the_adapter_pins():
    assert hashlib.sha256(STAGE1_SCHEMA_PATH.read_bytes()).hexdigest() == mod._STAGE1_SCHEMA_SHA256
    assert hashlib.sha256(STAGE2_SCHEMA_PATH.read_bytes()).hexdigest() == mod._STAGE2_SCHEMA_SHA256


def test_canonical_ledger_hash_pin_matches_the_real_committed_file():
    assert hashlib.sha256(REAL_LEDGER_PATH.read_bytes()).hexdigest() == mod._CANONICAL_LEDGER_SHA256
    assert mod._LEDGER_PATH == REAL_LEDGER_PATH


def test_schema_ids_and_contract_consts_match_module_constants():
    assert STAGE1_SCHEMA["$id"] == STAGE1_SCHEMA_PATH.name
    assert STAGE2_SCHEMA["$id"] == STAGE2_SCHEMA_PATH.name
    assert STAGE1_SCHEMA["properties"]["contract"]["const"] == mod.STAGE1_CONTRACT
    assert STAGE2_SCHEMA["properties"]["contract"]["const"] == mod.STAGE2_CONTRACT
    assert STAGE1_SCHEMA["properties"]["schema_version"]["const"] == mod.SCHEMA_VERSION
    assert STAGE2_SCHEMA["properties"]["schema_version"]["const"] == mod.SCHEMA_VERSION
    assert (
        STAGE2_SCHEMA["properties"]["locator_ledger_relative_path"]["const"]
        == mod.LOCATOR_LEDGER_RELATIVE_PATH
    )


def test_stage1_schema_rejects_unknown_top_level_property():
    instance = _valid_stage1()
    instance["unexpected"] = "x"
    assert not Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)


def test_stage1_schema_rejects_capability_missing_product_link():
    instance = _valid_stage1()
    del instance["candidates"][1]["product_local_id"]
    assert not Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)


def test_stage1_schema_rejects_product_branch_carrying_capability_fields():
    instance = _valid_stage1()
    instance["candidates"][0]["capability_text"] = "leaked field"
    assert not Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)


@pytest.mark.parametrize("bad_local_id", ["Q1", "P01", "p1", "P0", "P1a", ""])
def test_stage1_schema_rejects_malformed_product_local_id(bad_local_id):
    instance = _valid_stage1()
    instance["candidates"][0]["local_id"] = bad_local_id
    assert not Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)


def test_stage1_schema_zero_candidates_requires_reason():
    instance = _valid_stage1(candidates=[], zero_candidate_reason=None)
    assert not Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)
    instance["zero_candidate_reason"] = "no_product_capability_or_task_evidence"
    assert Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)


def test_stage1_schema_nonzero_candidates_forbids_reason():
    instance = _valid_stage1(zero_candidate_reason="all_mentions_excluded")
    assert not Draft202012Validator(STAGE1_SCHEMA).is_valid(instance)


def test_stage1_schema_accepts_the_base_fixture():
    assert Draft202012Validator(STAGE1_SCHEMA).is_valid(_valid_stage1())


def test_stage2_schema_rejects_unknown_top_level_property():
    instance = {
        "contract": mod.STAGE2_CONTRACT, "schema_version": "0.1.0", "ticker": "ZZZZ",
        "legacy_source_id": LEGACY_SOURCE_ID, "model_output_reference": "x",
        "model_output_sha256": "0" * 64,
        "locator_ledger_relative_path": mod.LOCATOR_LEDGER_RELATIVE_PATH,
        "locator_ledger_sha256": "0" * 64, "candidates": [], "excluded_mentions": [],
        "zero_candidate_reason": "no_product_capability_or_task_evidence", "extra": 1,
    }
    assert not Draft202012Validator(STAGE2_SCHEMA).is_valid(instance)


# --- Authority: no public ledger parameter, canonical path only -------------


def test_no_public_parameter_permits_a_caller_selected_ledger():
    params = inspect.signature(build_persisted_candidates).parameters
    assert "locator_ledger_path" not in params
    assert set(params) == {"ticker", "span_text", "raw_stage1_bytes", "model_output_reference"}


def test_canonical_ledger_path_is_fixed_from_repo_root():
    assert mod._LEDGER_PATH == mod._REPO_ROOT / mod.LOCATOR_LEDGER_RELATIVE_PATH


def test_canonical_ledger_tamper_refuses_before_ticker_lookup(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    # Simulate a changed canonical-ledger byte AFTER the pin was established:
    # the file on disk now disagrees with the reviewed hash.
    tampered = ledger_path.read_bytes() + b" "
    ledger_path.write_bytes(tampered)
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates(
            ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=_raw(_valid_stage1()),
            model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_LEDGER_FILE_TAMPERED


def test_canonical_ledger_tamper_refuses_even_for_a_ticker_that_would_not_exist(tmp_path, monkeypatch):
    """The tamper check runs before any ticker row is extracted: an unknown
    ticker against a tampered ledger still reports tamper, not
    ledger_row_not_found."""
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    ledger_path.write_bytes(ledger_path.read_bytes() + b" ")
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates(
            ticker="DOES-NOT-EXIST", span_text=SPAN_TEXT, raw_stage1_bytes=_raw(_valid_stage1()),
            model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_LEDGER_FILE_TAMPERED


def test_stage2_ledger_fields_come_from_the_verified_canonical_pin(tmp_path, monkeypatch):
    stage2 = _build(tmp_path, monkeypatch)
    assert stage2["locator_ledger_sha256"] == mod._CANONICAL_LEDGER_SHA256
    assert stage2["locator_ledger_relative_path"] == mod.LOCATOR_LEDGER_RELATIVE_PATH


# --- End-to-end adapter behavior ---------------------------------------------


def test_happy_path_produces_schema_valid_stage2(tmp_path, monkeypatch):
    stage2 = _build(tmp_path, monkeypatch)
    Draft202012Validator(STAGE2_SCHEMA).validate(stage2)
    assert stage2["contract"] == mod.STAGE2_CONTRACT
    assert stage2["schema_version"] == "0.1.0"
    assert stage2["ticker"] == TICKER
    assert stage2["legacy_source_id"] == LEGACY_SOURCE_ID
    assert stage2["locator_ledger_relative_path"] == mod.LOCATOR_LEDGER_RELATIVE_PATH
    assert stage2["zero_candidate_reason"] is None
    assert len(stage2["candidates"]) == 3


def test_candidate_id_matches_manual_recomputation_for_every_row(tmp_path, monkeypatch):
    """Proves the exact hash formula, including that local_id/kind/ordinal
    are NOT re-embedded inside the hashed ``fields`` payload (they each have
    their own dedicated slot or are excluded entirely)."""
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
    first = build_persisted_candidates(
        ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=raw,
        model_output_reference="scratch/fake.json",
    )
    second = build_persisted_candidates(
        ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=raw,
        model_output_reference="scratch/fake.json",
    )
    assert first == second


def test_non_transferability_different_raw_bytes_different_candidate_ids(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    stage1 = _valid_stage1()
    raw_a = json.dumps(stage1).encode("utf-8")
    raw_b = json.dumps(stage1, indent=2).encode("utf-8")  # same content, different bytes
    assert raw_a != raw_b
    result_a = build_persisted_candidates(
        ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=raw_a, model_output_reference="a.json",
    )
    result_b = build_persisted_candidates(
        ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=raw_b, model_output_reference="b.json",
    )
    ids_a = {c["candidate_id"] for c in result_a["candidates"]}
    ids_b = {c["candidate_id"] for c in result_b["candidates"]}
    assert ids_a.isdisjoint(ids_b)
    assert result_a["model_output_sha256"] != result_b["model_output_sha256"]


def test_ordinal_is_original_array_index_not_topological_index(tmp_path, monkeypatch):
    # Declared out of dependency order: capability before its product.
    candidates = [
        {
            "local_id": "C1", "kind": "capability", "product_local_id": "P1",
            "capability_text": "AI Summaries", "availability_status": "general_availability",
            "evidence_quote": Q_CAPABILITY, "evidence_locator": _span(Q_CAPABILITY),
        },
        {
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "Widget Pro", "availability_status": "general_availability",
            "evidence_quote": Q_PRODUCT, "evidence_locator": _span(Q_PRODUCT),
        },
        {
            "local_id": "T1", "kind": "task", "product_local_id": "P1",
            "capability_local_ids": ["C1"], "task_text": Q_TASK,
            "customer_need": "save reading time", "availability_status": "general_availability",
            "evidence_quote": Q_TASK, "evidence_locator": _span(Q_TASK),
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
    for row in stage2["candidates"]:
        assert "product_local_id" not in row
        assert "capability_local_ids" not in row


def test_local_id_retained_as_diagnostic_field(tmp_path, monkeypatch):
    stage2 = _build(tmp_path, monkeypatch)
    assert {row["local_id"] for row in stage2["candidates"]} == {"P1", "C1", "T1"}


def test_every_locator_legacy_source_id_is_the_ledger_value_not_a_model_claim(tmp_path, monkeypatch):
    stage2 = _build(tmp_path, monkeypatch)
    for row in stage2["candidates"]:
        assert row["evidence_locator"]["legacy_source_id"] == LEGACY_SOURCE_ID
    for mention in stage2["excluded_mentions"]:
        assert mention["evidence_locator"]["legacy_source_id"] == LEGACY_SOURCE_ID


def test_provenance_fields_bind_to_the_exact_raw_bytes_and_pinned_ledger(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    stage1 = _valid_stage1()
    raw = _raw(stage1)
    stage2 = build_persisted_candidates(
        ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=raw, model_output_reference="scratch/fake.json",
    )
    assert stage2["model_output_sha256"] == hashlib.sha256(raw).hexdigest()
    assert stage2["locator_ledger_sha256"] == hashlib.sha256(ledger_path.read_bytes()).hexdigest()
    assert stage2["locator_ledger_sha256"] == mod._CANONICAL_LEDGER_SHA256
    assert stage2["model_output_reference"] == "scratch/fake.json"


def test_excluded_mentions_pass_through_with_stamped_locator(tmp_path, monkeypatch):
    excluded = [
        {"reason": "internal_use", "evidence_quote": Q_EXCLUDED_INTERNAL,
         "evidence_locator": _span(Q_EXCLUDED_INTERNAL)},
        {"reason": "vague_ai_marketing", "evidence_quote": Q_EXCLUDED_VAGUE_AI,
         "evidence_locator": _span(Q_EXCLUDED_VAGUE_AI)},
    ]
    stage2 = _build(tmp_path, monkeypatch, stage1=_valid_stage1(excluded_mentions=excluded))
    assert len(stage2["excluded_mentions"]) == 2
    reasons = {m["reason"] for m in stage2["excluded_mentions"]}
    assert reasons == {"internal_use", "vague_ai_marketing"}
    for mention in stage2["excluded_mentions"]:
        assert "candidate_id" not in mention


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
        build_persisted_candidates(
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
        build_persisted_candidates(
            ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=wrapped, model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_NOT_VALID_JSON


def test_refuses_on_top_level_json_array(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates(
            ticker=TICKER, span_text=SPAN_TEXT, raw_stage1_bytes=b"[1, 2, 3]", model_output_reference="x",
        )
    assert excinfo.value.reason == mod.REASON_NOT_VALID_JSON


def test_refuses_on_invalid_utf8_bytes(tmp_path, monkeypatch):
    ledger_path = _write_ledger(tmp_path)
    _patch_canonical_ledger(monkeypatch, ledger_path)
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates(
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
        build_persisted_candidates(
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
    candidates = [
        {
            "local_id": "C1", "kind": "capability", "product_local_id": "P9",
            "capability_text": "AI Summaries", "availability_status": "general_availability",
            "evidence_quote": Q_CAPABILITY, "evidence_locator": _span(Q_CAPABILITY),
        },
    ]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_DANGLING_LOCAL_REFERENCE,
        stage1=_valid_stage1(candidates=candidates, zero_candidate_reason=None),
    )


def test_refuses_on_duplicate_local_id(tmp_path, monkeypatch):
    candidates = [
        {
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "Widget Pro", "availability_status": "general_availability",
            "evidence_quote": Q_PRODUCT, "evidence_locator": _span(Q_PRODUCT),
        },
        {
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "Widget Pro Two", "availability_status": "general_availability",
            "evidence_quote": Q_PRODUCT, "evidence_locator": _span(Q_PRODUCT),
        },
    ]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_DUPLICATE_LOCAL_ID,
        stage1=_valid_stage1(candidates=candidates),
    )


def test_refuses_on_invalid_locator_bounds_reversed(tmp_path, monkeypatch):
    candidates = [
        {
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "Widget Pro", "availability_status": "general_availability",
            "evidence_quote": Q_PRODUCT, "evidence_locator": {"char_start": 18, "char_end": 8},
        },
    ]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_INVALID_LOCATOR_BOUNDS,
        stage1=_valid_stage1(candidates=candidates),
    )


def test_refuses_on_invalid_locator_bounds_out_of_range(tmp_path, monkeypatch):
    candidates = [
        {
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "Widget Pro", "availability_status": "general_availability",
            "evidence_quote": Q_PRODUCT,
            "evidence_locator": {"char_start": 0, "char_end": len(SPAN_TEXT) + 500},
        },
    ]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_INVALID_LOCATOR_BOUNDS,
        stage1=_valid_stage1(candidates=candidates),
    )


def test_refuses_on_evidence_quote_containment_failed_for_a_candidate(tmp_path, monkeypatch):
    candidates = [
        {
            "local_id": "P1", "kind": "product", "product_family": None,
            "product_name": "Widget Pro", "availability_status": "general_availability",
            "evidence_quote": "Something else entirely", "evidence_locator": _span(Q_PRODUCT),
        },
    ]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_EVIDENCE_QUOTE_CONTAINMENT_FAILED,
        stage1=_valid_stage1(candidates=candidates),
    )


def test_refuses_on_evidence_quote_containment_failed_for_an_excluded_mention(tmp_path, monkeypatch):
    excluded = [
        {"reason": "internal_use", "evidence_quote": "Something else entirely",
         "evidence_locator": _span(Q_EXCLUDED_INTERNAL)},
    ]
    _refuses(
        tmp_path, monkeypatch, mod.REASON_EVIDENCE_QUOTE_CONTAINMENT_FAILED,
        stage1=_valid_stage1(excluded_mentions=excluded),
    )


def test_reason_set_is_closed_and_pinned():
    assert mod._REASONS == frozenset(
        {
            "not_valid_json", "schema_invalid", "schema_file_tampered",
            "ledger_file_tampered", "ledger_row_not_found", "span_text_hash_mismatch",
            "legacy_source_id_mismatch", "dangling_local_reference",
            "duplicate_local_id", "invalid_locator_bounds",
            "evidence_quote_containment_failed",
        }
    )
    assert len(mod._REASONS) == 11


def test_error_rejects_an_unrecognized_reason_code():
    with pytest.raises(ValueError):
        CombinedCandidateAdapterError("not_a_real_reason", "message")


def test_locator_ledger_relative_path_points_at_the_real_committed_ledger():
    assert mod.LOCATOR_LEDGER_RELATIVE_PATH == "evals/registries/pct_dev30_v0_item1_locator_ledger.json"
    assert REAL_LEDGER_PATH.exists()


def test_real_committed_ledger_refuses_an_unknown_ticker():
    # No monkeypatch: exercises the real, pinned production ledger directly.
    # Only proves an unknown ticker is refused; no real firm's evidence is used.
    with pytest.raises(CombinedCandidateAdapterError) as excinfo:
        build_persisted_candidates(
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
