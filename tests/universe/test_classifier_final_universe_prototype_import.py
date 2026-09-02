"""Tests for preserving, rather than rerunning, historical refinement outputs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

import pytest

from dynamic_ai_products import classifier_final_universe_prototype_import as prototype
from dynamic_ai_products.universe.lineage_screen import ScreenInputError

ROOT = Path(__file__).resolve().parents[2]
CLOCK = lambda: datetime(2026, 9, 2, tzinfo=timezone.utc)  # noqa: E731


def _sha(raw: bytes) -> str:
    return sha256(raw).hexdigest()


def _write_jsonl(path: Path, rows: list[dict]) -> bytes:
    raw = b"".join((json.dumps(row, sort_keys=True) + "\n").encode() for row in rows)
    path.write_bytes(raw)
    return raw


def _fixture(tmp_path: Path) -> dict[str, Path]:
    candidates = tmp_path / "v9_candidates.jsonl"
    keys = [("0000000001", "0000000001-22-000001"), ("0000000002", "0000000002-22-000002")]
    candidates_raw = _write_jsonl(candidates, [
        {"cik": cik, "accession": accession, "aggregate_role": "software_candidate"}
        for cik, accession in keys
    ])
    strict_dir, centrality_dir = tmp_path / "strict", tmp_path / "centrality"
    strict_dir.mkdir()
    centrality_dir.mkdir()
    strict_prompt = (ROOT / prototype.STRICT_PROMPT_PATH).read_text(encoding="utf-8")
    centrality_prompt = (ROOT / prototype.CENTRALITY_PROMPT_PATH).read_text(encoding="utf-8")
    common = {
        "model": "fixture-model", "selected_rows": len(keys),
        "source_candidates": str(candidates),
        "source_candidates_sha256": _sha(candidates_raw),
        "packet_source_sha256": "a" * 64,
    }
    (strict_dir / "metadata.json").write_text(json.dumps({**common, "prompt": strict_prompt}), encoding="utf-8")
    (centrality_dir / "metadata.json").write_text(json.dumps({**common, "prompt": centrality_prompt}), encoding="utf-8")
    _write_jsonl(strict_dir / "outputs.jsonl", [
        {"cik": keys[0][0], "accession": keys[0][1], "packet_sha256": "b" * 64,
         "status": "completed", "model_output": {"strict_core": "STRICT_CORE", "confidence": "high", "passage_refs": ["P001"]}},
        {"cik": keys[1][0], "accession": keys[1][1], "packet_sha256": "c" * 64,
         "status": "completed", "model_output": {"strict_core": "NOT_STRICT_CORE", "confidence": "medium", "passage_refs": ["P002"]}},
    ])
    _write_jsonl(centrality_dir / "outputs.jsonl", [
        {"cik": keys[0][0], "accession": keys[0][1], "packet_sha256": "b" * 64,
         "status": "completed", "model_output": {"software_centrality": "CORE", "passage_refs": ["P001"]}},
        {"cik": keys[1][0], "accession": keys[1][1], "packet_sha256": "c" * 64,
         "status": "completed", "model_output": {"software_centrality": "ENABLING", "passage_refs": ["P002"]}},
    ])
    return {"strict": strict_dir, "centrality": centrality_dir, "candidates": candidates}


def _build(tmp_path: Path, *, dry_run: bool = True) -> dict:
    fixture = _fixture(tmp_path)
    return prototype.build_final_universe_prototype_import(
        repo_root=ROOT, strict_source_dir=fixture["strict"],
        centrality_source_dir=fixture["centrality"], candidates_path=fixture["candidates"],
        output_root=tmp_path / "imports", import_id="fixture-import", clock=CLOCK,
        dry_run=dry_run,
    )


def test_committed_prompt_bytes_match_the_historical_metadata() -> None:
    expected = {
        prototype.STRICT_PROMPT_PATH: "2f41977e0e9bbab1e36789bb185c171402f12a3e8fadd3fde654a030c2be5fec",
        prototype.CENTRALITY_PROMPT_PATH: "4d19c471624d9be83fe07fa64b59d32908771a214fbf03bc8e66a932c3b35d11",
    }
    for path, digest in expected.items():
        assert _sha((ROOT / path).read_bytes()) == digest


def test_dry_run_validates_complete_snapshot_without_writing(tmp_path: Path) -> None:
    manifest = _build(tmp_path)
    assert manifest["import_contract"] == prototype.IMPORT_CONTRACT
    assert manifest["no_model_call"] is True
    assert manifest["counts"] == {
        "candidate_rows": 2, "strict_completed_rows": 2, "strict_failed_rows": 0,
        "centrality_completed_rows": 2, "centrality_failed_rows": 0,
        "strict_core_rows": 1, "centrality_core_rows": 1, "intersection_rows": 1,
    }
    assert all(manifest["reconciliation"].values())
    assert not (tmp_path / "imports").exists()


def test_wet_import_copies_exact_bytes_and_reloads(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    manifest = prototype.build_final_universe_prototype_import(
        repo_root=ROOT, strict_source_dir=fixture["strict"],
        centrality_source_dir=fixture["centrality"], candidates_path=fixture["candidates"],
        output_root=tmp_path / "imports", import_id="fixture-import", clock=CLOCK,
    )
    run_dir = tmp_path / "imports" / "fixture-import"
    assert prototype.require_final_universe_prototype_import(run_dir, repo_root=ROOT).is_file()
    names = {
        prototype.STRICT_METADATA_FILENAME, prototype.STRICT_OUTPUTS_FILENAME,
        prototype.CENTRALITY_METADATA_FILENAME, prototype.CENTRALITY_OUTPUTS_FILENAME,
        prototype.IMPORT_MANIFEST_FILENAME,
    }
    assert {path.name for path in run_dir.iterdir()} == names
    assert (run_dir / prototype.STRICT_OUTPUTS_FILENAME).read_bytes() == (fixture["strict"] / "outputs.jsonl").read_bytes()
    assert (run_dir / prototype.CENTRALITY_OUTPUTS_FILENAME).read_bytes() == (fixture["centrality"] / "outputs.jsonl").read_bytes()
    assert manifest["output_hashes"][prototype.STRICT_OUTPUTS_FILENAME] == _sha((fixture["strict"] / "outputs.jsonl").read_bytes())


def test_import_refuses_changed_prompt_bytes(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    metadata_path = fixture["strict"] / "metadata.json"
    metadata = json.loads(metadata_path.read_text())
    metadata["prompt"] += "changed"
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ScreenInputError, match="prompt differs"):
        prototype.build_final_universe_prototype_import(
            repo_root=ROOT, strict_source_dir=fixture["strict"],
            centrality_source_dir=fixture["centrality"], candidates_path=fixture["candidates"],
            output_root=tmp_path / "imports", import_id="fixture-import", clock=CLOCK,
        )


def test_import_accepts_different_filing_order_with_the_same_filing_set(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["centrality"] / "outputs.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    _write_jsonl(path, list(reversed(rows)))
    manifest = prototype.build_final_universe_prototype_import(
        repo_root=ROOT, strict_source_dir=fixture["strict"],
        centrality_source_dir=fixture["centrality"], candidates_path=fixture["candidates"],
        output_root=tmp_path / "imports", import_id="fixture-import", clock=CLOCK,
    )
    assert manifest["counts"]["intersection_rows"] == 1


def test_import_refuses_different_packet_corpus(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["centrality"] / "metadata.json"
    metadata = json.loads(path.read_text())
    metadata["packet_source_sha256"] = "d" * 64
    path.write_text(json.dumps(metadata), encoding="utf-8")
    with pytest.raises(ScreenInputError, match="different Item 1 packet corpora"):
        prototype.build_final_universe_prototype_import(
            repo_root=ROOT, strict_source_dir=fixture["strict"],
            centrality_source_dir=fixture["centrality"], candidates_path=fixture["candidates"],
            output_root=tmp_path / "imports", import_id="fixture-import", clock=CLOCK,
        )


def test_import_preserves_a_typed_historical_provider_failure(tmp_path: Path) -> None:
    fixture = _fixture(tmp_path)
    path = fixture["strict"] / "outputs.jsonl"
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    rows[1] = {
        "cik": rows[1]["cik"], "accession": rows[1]["accession"],
        "packet_sha256": rows[1]["packet_sha256"], "status": "failed",
        "error_type": "TransportError", "error": "connection closed",
    }
    _write_jsonl(path, rows)
    manifest = prototype.build_final_universe_prototype_import(
        repo_root=ROOT, strict_source_dir=fixture["strict"],
        centrality_source_dir=fixture["centrality"], candidates_path=fixture["candidates"],
        output_root=tmp_path / "imports", import_id="fixture-import", clock=CLOCK,
    )
    assert manifest["counts"]["strict_failed_rows"] == 1
    assert manifest["counts"]["intersection_rows"] == 1


def test_require_refuses_tampered_output(tmp_path: Path) -> None:
    _build(tmp_path, dry_run=False)
    run_dir = tmp_path / "imports" / "fixture-import"
    (run_dir / prototype.STRICT_OUTPUTS_FILENAME).write_text("tampered\n", encoding="utf-8")
    with pytest.raises(ScreenInputError, match="does not match its manifest"):
        prototype.require_final_universe_prototype_import(run_dir, repo_root=ROOT)
