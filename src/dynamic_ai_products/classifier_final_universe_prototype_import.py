"""Preserve the two historical Item 1 refinement experiments without rerunning them.

The prior strict-CORE and centrality experiments produced useful, complete
JSONL outputs, but their ad-hoc launcher and provider capture logs were not
retained.  This module does *not* reinterpret those outputs as a governed
model run.  It creates a write-once, self-contained import artifact whose
manifest calls that limitation out explicitly.  Downstream deterministic
selection can therefore depend on stable bytes rather than on ``/tmp``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .provenance import WriteOnceError, file_sha256, write_bytes_once
from .universe.freeze import create_run_directory
from .universe.lineage_screen import ScreenInputError

__all__ = [
    "CENTRALITY_METADATA_FILENAME",
    "CENTRALITY_OUTPUTS_FILENAME",
    "CENTRALITY_PROMPT_PATH",
    "IMPORT_CONTRACT",
    "IMPORT_MANIFEST_FILENAME",
    "STRICT_METADATA_FILENAME",
    "STRICT_OUTPUTS_FILENAME",
    "STRICT_PROMPT_PATH",
    "build_final_universe_prototype_import",
    "require_final_universe_prototype_import",
]

IMPORT_CONTRACT = "universe_final_software_prototype_import@0.1.0"
IMPORT_MANIFEST_FILENAME = "universe_final_software_prototype_import_manifest.json"
STRICT_METADATA_FILENAME = "strict_core_refinement_metadata.json"
STRICT_OUTPUTS_FILENAME = "strict_core_refinement_outputs.jsonl"
CENTRALITY_METADATA_FILENAME = "software_centrality_refinement_metadata.json"
CENTRALITY_OUTPUTS_FILENAME = "software_centrality_refinement_outputs.jsonl"
STRICT_PROMPT_PATH = "prompts/discovery/software_universe_strict_core_refinement.v1.md"
CENTRALITY_PROMPT_PATH = "prompts/discovery/software_universe_centrality_refinement.v1.md"


def _load_json(path: Path, *, what: str) -> dict[str, Any]:
    if not path.is_file():
        raise ScreenInputError(f"{what} is missing: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ScreenInputError(f"{what} is not valid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise ScreenInputError(f"{what} must be a JSON object.")
    return value


def _load_jsonl(path: Path, *, what: str) -> tuple[bytes, list[dict[str, Any]]]:
    if not path.is_file():
        raise ScreenInputError(f"{what} is missing: {path}")
    raw = path.read_bytes()
    try:
        rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line]
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ScreenInputError(f"{what} is not valid UTF-8 JSONL: {path}") from exc
    if not rows or not all(isinstance(row, dict) for row in rows):
        raise ScreenInputError(f"{what} must contain one or more JSON objects.")
    return raw, rows


def _sha(raw: bytes) -> str:
    from hashlib import sha256

    return sha256(raw).hexdigest()


def _keys(rows: list[dict[str, Any]], *, what: str) -> list[tuple[str, str]]:
    keys: list[tuple[str, str]] = []
    for row in rows:
        cik, accession = row.get("cik"), row.get("accession")
        if not isinstance(cik, str) or not isinstance(accession, str):
            raise ScreenInputError(f"{what} contains a row without string cik and accession.")
        keys.append((cik, accession))
    if len(keys) != len(set(keys)):
        raise ScreenInputError(f"{what} contains duplicate filing identities.")
    return keys


def _check_output_rows(
    rows: list[dict[str, Any]], *, kind: str, expected_keys: list[tuple[str, str]],
) -> tuple[list[tuple[str, str]], int, int]:
    output_keys = _keys(rows, what=f"{kind} outputs")
    if set(output_keys) != set(expected_keys):
        raise ScreenInputError(
            f"{kind} outputs do not name the same filing identities as the V9 candidates.")
    label = "strict_core" if kind == "strict" else "software_centrality"
    allowed = (
        {"STRICT_CORE", "NOT_STRICT_CORE", "INSUFFICIENT_ITEM1"}
        if kind == "strict"
        else {"CORE", "CO_ESSENTIAL", "ENABLING", "PERIPHERAL", "UNKNOWN"}
    )
    completed = failed = 0
    for row in rows:
        status = row.get("status")
        if status == "failed":
            if not isinstance(row.get("error_type"), str) or not row["error_type"]:
                raise ScreenInputError(f"{kind} failed output has no error_type.")
            if "model_output" in row:
                raise ScreenInputError(f"{kind} failed output must not carry a model output.")
            failed += 1
            continue
        if status != "completed" or not isinstance(row.get("model_output"), dict):
            raise ScreenInputError(f"{kind} outputs must be completed model outputs or typed failures.")
        completed += 1
        output = row["model_output"]
        if output.get(label) not in allowed:
            raise ScreenInputError(f"{kind} output has an invalid {label!r} value.")
        refs = output.get("passage_refs")
        if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
            raise ScreenInputError(f"{kind} output has invalid passage_refs.")
        if len(refs) > 3:
            raise ScreenInputError(f"{kind} output has more than three passage references.")
        if (output[label] in {"INSUFFICIENT_ITEM1", "UNKNOWN"}) != (len(refs) == 0):
            raise ScreenInputError(f"{kind} output violates its empty-reference rule.")
    return output_keys, completed, failed


def _check_metadata(
    metadata: dict[str, Any], *, prompt: bytes, source_candidates_sha256: str,
    row_count: int, kind: str,
) -> None:
    required = {"model", "prompt", "selected_rows", "source_candidates_sha256", "packet_source_sha256"}
    if not required <= metadata.keys():
        raise ScreenInputError(f"{kind} metadata is missing required provenance fields.")
    if metadata["prompt"].encode("utf-8") != prompt:
        raise ScreenInputError(f"{kind} metadata prompt differs from the version-controlled prompt bytes.")
    if metadata["source_candidates_sha256"] != source_candidates_sha256:
        raise ScreenInputError(f"{kind} metadata binds different V9 candidate bytes.")
    if metadata["selected_rows"] != row_count:
        raise ScreenInputError(f"{kind} metadata row count disagrees with imported outputs.")
    if not isinstance(metadata["model"], str) or not metadata["model"].strip():
        raise ScreenInputError(f"{kind} metadata has no model label.")


def _manifest(
    *, import_id: str, clock: Callable[[], datetime], candidates: Path,
    candidate_sha256: str, strict_metadata: dict[str, Any], centrality_metadata: dict[str, Any],
    strict_raw: bytes, centrality_raw: bytes, strict_rows: list[dict[str, Any]],
    centrality_rows: list[dict[str, Any]], strict_metadata_raw: bytes,
    centrality_metadata_raw: bytes, repo_root: Path,
) -> dict[str, Any]:
    strict_core = sum(
        row.get("status") == "completed"
        and row["model_output"]["strict_core"] == "STRICT_CORE"
        for row in strict_rows)
    centrality_core = sum(
        row.get("status") == "completed"
        and row["model_output"]["software_centrality"] == "CORE"
        for row in centrality_rows)
    strict_keys = {
        (row["cik"], row["accession"])
        for row in strict_rows if row.get("status") == "completed"
        and row["model_output"]["strict_core"] == "STRICT_CORE"
    }
    centrality_keys = {
        (row["cik"], row["accession"])
        for row in centrality_rows if row.get("status") == "completed"
        and row["model_output"]["software_centrality"] == "CORE"
    }
    outputs = {
        STRICT_METADATA_FILENAME: _sha(strict_metadata_raw),
        STRICT_OUTPUTS_FILENAME: _sha(strict_raw),
        CENTRALITY_METADATA_FILENAME: _sha(centrality_metadata_raw),
        CENTRALITY_OUTPUTS_FILENAME: _sha(centrality_raw),
    }
    return {
        "import_contract": IMPORT_CONTRACT,
        "import_id": import_id,
        "import_timestamp": clock().isoformat(),
        "import_kind": "historical_external_prototype_snapshot",
        "no_model_call": True,
        "source_candidates": {
            "path": str(candidates), "sha256": candidate_sha256,
            "selected_rows": len(strict_rows),
        },
        "packet_source_sha256": strict_metadata["packet_source_sha256"],
        "experiments": {
            "strict_core": {
                "model_label": strict_metadata["model"],
                "prompt_path": STRICT_PROMPT_PATH,
                "prompt_sha256": _sha((repo_root / STRICT_PROMPT_PATH).read_bytes()),
                "metadata_sha256": outputs[STRICT_METADATA_FILENAME],
                "outputs_sha256": outputs[STRICT_OUTPUTS_FILENAME],
            },
            "software_centrality": {
                "model_label": centrality_metadata["model"],
                "prompt_path": CENTRALITY_PROMPT_PATH,
                "prompt_sha256": _sha((repo_root / CENTRALITY_PROMPT_PATH).read_bytes()),
                "metadata_sha256": outputs[CENTRALITY_METADATA_FILENAME],
                "outputs_sha256": outputs[CENTRALITY_OUTPUTS_FILENAME],
            },
        },
        "output_hashes": outputs,
        "counts": {
            "candidate_rows": len(strict_rows),
            "strict_completed_rows": sum(row.get("status") == "completed" for row in strict_rows),
            "strict_failed_rows": sum(row.get("status") == "failed" for row in strict_rows),
            "centrality_completed_rows": sum(row.get("status") == "completed" for row in centrality_rows),
            "centrality_failed_rows": sum(row.get("status") == "failed" for row in centrality_rows),
            "strict_core_rows": strict_core,
            "centrality_core_rows": centrality_core,
            "intersection_rows": len(strict_keys & centrality_keys),
        },
        "reconciliation": {
            "both experiments name the complete V9 candidate filing set": True,
            "both metadata files bind the same candidate bytes": True,
            "both metadata files bind the same Item 1 packet corpus": True,
            "prompt bytes match the version-controlled prompt files": True,
        },
        "limitations": [
            "This artifact imports historical prototype outputs; importing performs no model call.",
            "The original ad-hoc launcher, provider request captures, retry ledger, and token accounting were not retained.",
            "It supports deterministic downstream reconstruction from frozen imported bytes, not a claim that the historical provider run was governed.",
        ],
    }


def build_final_universe_prototype_import(
    *, repo_root: str | Path, strict_source_dir: str | Path,
    centrality_source_dir: str | Path, candidates_path: str | Path,
    output_root: str | Path, import_id: str, clock: Callable[[], datetime],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Create a self-contained, write-once import of the historical prototype bytes."""
    root = Path(repo_root)
    strict_source, centrality_source, candidates = (
        Path(strict_source_dir), Path(centrality_source_dir), Path(candidates_path))
    candidates_raw, candidate_rows = _load_jsonl(candidates, what="V9 candidate source")
    candidate_sha256 = _sha(candidates_raw)
    candidate_keys = _keys(candidate_rows, what="V9 candidate source")

    strict_metadata_path = strict_source / "metadata.json"
    centrality_metadata_path = centrality_source / "metadata.json"
    strict_metadata_raw = strict_metadata_path.read_bytes() if strict_metadata_path.is_file() else b""
    centrality_metadata_raw = centrality_metadata_path.read_bytes() if centrality_metadata_path.is_file() else b""
    strict_metadata = _load_json(strict_metadata_path, what="strict-core metadata")
    centrality_metadata = _load_json(centrality_metadata_path, what="centrality metadata")
    strict_raw, strict_rows = _load_jsonl(strict_source / "outputs.jsonl", what="strict-core outputs")
    centrality_raw, centrality_rows = _load_jsonl(centrality_source / "outputs.jsonl", what="centrality outputs")
    strict_prompt = (root / STRICT_PROMPT_PATH).read_bytes()
    centrality_prompt = (root / CENTRALITY_PROMPT_PATH).read_bytes()
    if not strict_prompt or not centrality_prompt:
        raise ScreenInputError("A version-controlled refinement prompt is missing or empty.")
    _check_metadata(strict_metadata, prompt=strict_prompt, source_candidates_sha256=candidate_sha256,
                    row_count=len(strict_rows), kind="strict-core")
    _check_metadata(centrality_metadata, prompt=centrality_prompt, source_candidates_sha256=candidate_sha256,
                    row_count=len(centrality_rows), kind="centrality")
    if strict_metadata["packet_source_sha256"] != centrality_metadata["packet_source_sha256"]:
        raise ScreenInputError("The two historical experiments bind different Item 1 packet corpora.")
    strict_keys, _strict_completed, _strict_failed = _check_output_rows(
        strict_rows, kind="strict", expected_keys=candidate_keys)
    centrality_keys, _centrality_completed, _centrality_failed = _check_output_rows(
        centrality_rows, kind="centrality", expected_keys=candidate_keys)
    if set(strict_keys) != set(centrality_keys):
        raise ScreenInputError("The two historical experiments do not name one identical filing set.")
    manifest = _manifest(
        import_id=import_id, clock=clock, candidates=candidates,
        candidate_sha256=candidate_sha256, strict_metadata=strict_metadata,
        centrality_metadata=centrality_metadata, strict_raw=strict_raw,
        centrality_raw=centrality_raw, strict_rows=strict_rows,
        centrality_rows=centrality_rows, strict_metadata_raw=strict_metadata_raw,
        centrality_metadata_raw=centrality_metadata_raw, repo_root=root,
    )
    if dry_run:
        return manifest
    run_dir = create_run_directory(output_root, import_id)
    payloads = {
        STRICT_METADATA_FILENAME: strict_metadata_raw,
        STRICT_OUTPUTS_FILENAME: strict_raw,
        CENTRALITY_METADATA_FILENAME: centrality_metadata_raw,
        CENTRALITY_OUTPUTS_FILENAME: centrality_raw,
        IMPORT_MANIFEST_FILENAME: (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }
    try:
        for filename, raw in payloads.items():
            write_bytes_once(run_dir / filename, raw, what=f"prototype import {filename}")
    except WriteOnceError as exc:
        raise ScreenInputError(str(exc)) from exc
    return manifest


def require_final_universe_prototype_import(
    run_dir: str | Path, *, repo_root: str | Path,
) -> Path:
    """Verify one self-contained historical-prototype import artifact."""
    directory, root = Path(run_dir), Path(repo_root)
    manifest_path = directory / IMPORT_MANIFEST_FILENAME
    manifest = _load_json(manifest_path, what="prototype import manifest")
    if manifest.get("import_contract") != IMPORT_CONTRACT:
        raise ScreenInputError("The artifact declares a different prototype-import contract.")
    if manifest.get("no_model_call") is not True:
        raise ScreenInputError("A historical prototype import must not claim a model call.")
    for filename, digest in manifest.get("output_hashes", {}).items():
        path = directory / filename
        if not path.is_file() or file_sha256(path) != digest:
            raise ScreenInputError("An imported prototype output is missing or does not match its manifest.")
    for key, prompt_path in (("strict_core", STRICT_PROMPT_PATH), ("software_centrality", CENTRALITY_PROMPT_PATH)):
        experiment = manifest.get("experiments", {}).get(key)
        path = root / prompt_path
        if not isinstance(experiment, dict) or not path.is_file() or file_sha256(path) != experiment.get("prompt_sha256"):
            raise ScreenInputError("The imported prototype no longer hashes to its version-controlled prompt.")
    return manifest_path
