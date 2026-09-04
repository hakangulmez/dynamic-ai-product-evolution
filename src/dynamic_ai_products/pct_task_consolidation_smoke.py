"""Bounded final-task consolidation over a completed two-stage PCT smoke."""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .pct_combined_snapshot import CombinedSnapshotFailure
from .pct_combined_snapshot_smoke import _canonical_line, _sha256_bytes, build_vertex_generator
from .pct_task_smoke import task_candidate_map
from .provenance import WriteOnceError, write_bytes_once
from .universe.freeze import create_run_directory

PROMPT = "prompts/extraction/pct_item1_task_consolidation_v1.md"
SCHEMA = "schemas/pct_item1_task_consolidation_output.v1.schema.json"
RUN_KIND = "pct_item1_task_consolidation_smoke_v1"
RAW = "pct_item1_task_consolidation_raw_responses.jsonl"
RECORDS = "pct_item1_task_consolidation_records.jsonl"
MANIFEST = "pct_item1_task_consolidation_manifest.json"
HTML = "pct_item1_task_consolidation_human_review.html"


def consolidation_candidate_map(
    product_snapshot: dict[str, Any], task_snapshot: dict[str, Any]
) -> dict[str, Any]:
    """Supply only fixed upstream maps; no Item 1 text reaches this stage."""
    return {
        **task_candidate_map(product_snapshot),
        "task_candidates": task_snapshot["tasks"],
    }


def render_consolidation_prompt(template: str, candidates: dict[str, Any]) -> str:
    return (
        f"{template}\n\n## Fixed economic-product, capability, and task-candidate maps\n\n"
        "```json\n"
        f"{json.dumps(candidates, ensure_ascii=False, indent=2, sort_keys=True)}\n"
        "```\n"
    )


def validate_consolidation_output(
    raw: str, candidates: dict[str, Any], validator: Draft202012Validator
) -> dict[str, Any]:
    """Validate a complete non-overlapping disposition of fixed task candidates."""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CombinedSnapshotFailure("invalid_model_json", str(exc)) from exc
    errors = sorted(validator.iter_errors(parsed), key=lambda error: error.json_path)
    if errors:
        raise CombinedSnapshotFailure("snapshot_contract_violation", errors[0].message)

    tasks = {task["id"]: task for task in candidates["task_candidates"]}
    products = {product["id"] for product in candidates["economic_products"]}
    final_ids = [task["id"] for task in parsed["final_tasks"]]
    if len(final_ids) != len(set(final_ids)):
        raise CombinedSnapshotFailure("duplicate_local_id", "Final task IDs repeat.")

    assigned: list[str] = []
    stored_final: list[dict[str, Any]] = []
    for final in parsed["final_tasks"]:
        source_ids = final["source_task_ids"]
        source_tasks = [tasks.get(task_id) for task_id in source_ids]
        if any(task is None for task in source_tasks):
            raise CombinedSnapshotFailure("unknown_source_task_id", f"{final['id']} names an absent task.")
        if final["economic_product_id"] not in products:
            raise CombinedSnapshotFailure("unknown_economic_product_id", f"{final['id']} names an absent product.")
        if any(task["economic_product_id"] != final["economic_product_id"] for task in source_tasks):
            raise CombinedSnapshotFailure("cross_product_source_task", f"{final['id']} crosses economic products.")
        allowed_capabilities = {
            capability
            for task in source_tasks
            for capability in task["capability_refs"]
        }
        if not set(final["capability_refs"]).issubset(allowed_capabilities):
            raise CombinedSnapshotFailure("invalid_capability_reference", f"{final['id']} names a capability absent from its sources.")
        assigned.extend(source_ids)
        evidence_refs = list(dict.fromkeys(
            reference for task in source_tasks for reference in task["passage_refs"]
        ))
        stored_final.append({**final, "source_passage_refs": evidence_refs})

    excluded = parsed["excluded_task_candidates"]
    excluded_ids = [entry["task_id"] for entry in excluded]
    unresolved_ids = parsed["unresolved_task_ids"]
    all_dispositions = assigned + excluded_ids + unresolved_ids
    if any(task_id not in tasks for task_id in all_dispositions):
        raise CombinedSnapshotFailure("unknown_source_task_id", "A disposition names an absent task.")
    if len(all_dispositions) != len(set(all_dispositions)) or set(all_dispositions) != set(tasks):
        raise CombinedSnapshotFailure(
            "task_candidate_partition_violation",
            "Every input task must be in exactly one final, excluded, or unresolved disposition.",
        )
    return {**parsed, "final_tasks": stored_final}


def _review_html(records: list[dict[str, Any]], run_id: str) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    chunks = [
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">",
        "<title>Final PCT task consolidation review</title>",
        "<style>body{font:15px/1.45 system-ui;margin:2rem;max-width:1200px}article{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}code{background:#f2f2f2;padding:.1rem .25rem}</style>",
        f"<h1>Final PCT task consolidation: {esc(run_id)}</h1>",
        "<p>Task candidates are fixed upstream material. This stage receives no Item 1 text and derives no new evidence; source passage references are inherited deterministically.</p>",
    ]
    for row in records:
        chunks.append(f"<article><h2>{esc(row['issuer_name'])}</h2>")
        if row["record_kind"] != "extracted":
            chunks.append(f"<p><strong>Needs review:</strong> {esc(row['reason'])} — {esc(row['detail'])}</p></article>")
            continue
        snapshot = row["snapshot"]
        chunks.append("<h3>Final tasks</h3><ul>")
        for task in snapshot["final_tasks"]:
            chunks.append(
                f"<li><code>{esc(task['economic_product_id'])}/{esc(task['id'])}</code> {esc(task['text'])}"
                f"<br>Sources: {esc(', '.join(task['source_task_ids']))}; capabilities: {esc(', '.join(task['capability_refs']))}"
                f"<br>Inherited Item 1 references: {esc(', '.join(task['source_passage_refs']))}</li>"
            )
        chunks.append("</ul><h3>Excluded candidates</h3><ul>")
        for entry in snapshot["excluded_task_candidates"]:
            chunks.append(f"<li><code>{esc(entry['task_id'])}</code> — {esc(entry['reason'])}</li>")
        chunks.append("</ul><h3>Unresolved candidates</h3><p>" + esc(", ".join(snapshot["unresolved_task_ids"]) or "None") + "</p></article>")
    return "\n".join(chunks) + "\n"


def run_task_consolidation_smoke(
    *, source_records: list[dict[str, Any]], template: str, validator: Draft202012Validator,
    output_root: str | Path, run_id: str, source_stage1_sha256: str,
    source_stage2_sha256: str, generate: Callable[[str], str] | None,
    model: dict[str, Any], clock: Callable[[], datetime], dry_run: bool = False,
) -> dict[str, Any]:
    """Consolidate only rows with validated product and task maps."""
    if dry_run:
        return {"run_id": run_id, "dry_run": True, "status": "dry_run", "selected_rows": len(source_records), "model_called_rows": len(source_records), "run_dir": None}
    if generate is None:
        raise ValueError("A live task-consolidation smoke requires generate.")
    run_dir = create_run_directory(output_root, run_id)
    raw_entries: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for source in source_records:
        candidates = consolidation_candidate_map(source["product_snapshot"], source["task_snapshot"])
        rendered = render_consolidation_prompt(template, candidates)
        raw = generate(rendered)
        common = {
            key: source[key] for key in ("issuer_name", "cik", "accession", "packet_sha256")
        } | {"rendered_prompt_sha256": _sha256_bytes(rendered.encode())}
        raw_entries.append({
            "issuer_name": source["issuer_name"], "cik": source["cik"], "accession": source["accession"],
            "raw_response": raw, "raw_response_sha256": _sha256_bytes(raw.encode()),
        })
        try:
            snapshot = validate_consolidation_output(raw, candidates, validator)
        except CombinedSnapshotFailure as exc:
            records.append({**common, "record_kind": "review_uncertain", "reason": exc.reason_code, "detail": exc.detail, "snapshot": None})
        else:
            records.append({**common, "record_kind": "extracted", "reason": None, "detail": None, "snapshot": snapshot})
    payloads = {
        RAW: "".join(_canonical_line(row) + "\n" for row in raw_entries).encode(),
        RECORDS: "".join(_canonical_line(row) + "\n" for row in records).encode(),
        HTML: _review_html(records, run_id).encode(),
    }
    output_hashes = {name: _sha256_bytes(payload) for name, payload in payloads.items()}
    manifest = {
        "run_kind": RUN_KIND, "run_id": run_id, "run_timestamp": clock().isoformat(),
        "task_consolidation_prompt": {"path": PROMPT, "sha256": _sha256_bytes(template.encode())},
        "task_consolidation_schema": SCHEMA, "source_stage1_records_sha256": source_stage1_sha256,
        "source_stage2_records_sha256": source_stage2_sha256, "model": model,
        "selected_rows": len(source_records), "model_called_rows": len(raw_entries),
        "counts": {"extracted": sum(row["record_kind"] == "extracted" for row in records), "review_uncertain": sum(row["record_kind"] != "extracted" for row in records)},
        "output_hashes": output_hashes,
        "limitations": ["Development-only four-firm smoke; not a sample or full run.", "The stage receives fixed upstream maps, not Item 1 text, and settles no score, tier, transformation depth, or universe membership.", "Item 1 references displayed in final records are pipeline-derived from named source task candidates."],
    }
    payloads[MANIFEST] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    try:
        for name, payload in payloads.items():
            write_bytes_once(run_dir / name, payload, what=f"task consolidation {name}")
    except WriteOnceError as exc:
        raise ValueError(str(exc)) from exc
    return {"run_id": run_id, "dry_run": False, "status": "completed", "run_dir": run_dir, "manifest": manifest, "records": records}


def _load_source_rows(run_dir: Path) -> tuple[list[dict[str, Any]], str, str]:
    stage1_path = run_dir / "pct_item1_product_capability_records.jsonl"
    stage2_path = run_dir / "pct_item1_customer_tasks_records.jsonl"
    stage1 = [json.loads(line) for line in stage1_path.read_text().splitlines()]
    stage2 = [json.loads(line) for line in stage2_path.read_text().splitlines()]
    by_key = {(row["cik"], row["accession"]): row for row in stage2 if row["record_kind"] == "extracted"}
    rows = []
    for row in stage1:
        key = (row["cik"], row["accession"])
        task_row = by_key.get(key)
        if row["record_kind"] == "extracted" and task_row is not None:
            rows.append({
                **{key: row[key] for key in ("issuer_name", "cik", "accession", "packet_sha256")},
                "product_snapshot": row["snapshot"], "task_snapshot": task_row["snapshot"],
            })
    return rows, _sha256_bytes(stage1_path.read_bytes()), _sha256_bytes(stage2_path.read_bytes())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--two-stage-run-dir", required=True)
    parser.add_argument("--vertex-project", required=True)
    parser.add_argument("--output-root", default="data/runs/pct-item1-task-consolidation-smokes")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    template = (root / PROMPT).read_text()
    validator = Draft202012Validator(json.loads((root / SCHEMA).read_text()))
    source_rows, stage1_hash, stage2_hash = _load_source_rows(Path(args.two_stage_run_dir))
    result = run_task_consolidation_smoke(
        source_records=source_rows, template=template, validator=validator,
        output_root=root / args.output_root, run_id=args.run_id,
        source_stage1_sha256=stage1_hash, source_stage2_sha256=stage2_hash,
        generate=build_vertex_generator(vertex_project=args.vertex_project) if args.live else None,
        model={"provider": "google_vertex_ai", "model_label": "gemini-2.5-flash"},
        clock=lambda: datetime.now().astimezone(), dry_run=not args.live,
    )
    print(json.dumps({key: result[key] for key in ("run_id", "dry_run", "status", "run_dir")}, default=str, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    main()
