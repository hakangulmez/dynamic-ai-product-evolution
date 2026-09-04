"""Bounded PCT smoke: consolidate products, extract capabilities, then tasks."""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .classifier_pilot_v1 import render_pilot_prompt
from .pct_capability_extraction import (
    OUTPUT_SCHEMA as CAPABILITY_SCHEMA,
    validate_capability_extraction_output,
)
from .pct_combined_snapshot import CombinedSnapshotFailure
from .pct_combined_snapshot_smoke import (
    SMOKE_ROWS,
    _canonical_line,
    _sha256_bytes,
    build_vertex_generator,
    load_smoke_packets,
)
from .pct_economic_product_consolidation import (
    OUTPUT_SCHEMA as CONSOLIDATION_SCHEMA,
    validate_economic_product_consolidation_output,
)
from .pct_task_smoke import _validate as validate_task_output
from .pct_task_smoke import task_candidate_map
from .pct_two_stage_smoke import project_discovery_for_product_capability, render_task_prompt
from .provenance import WriteOnceError, write_bytes_once
from .universe.freeze import create_run_directory

CONSOLIDATION_PROMPT = "prompts/extraction/pct_item1_economic_product_consolidation_v1.md"
CAPABILITY_PROMPT = "prompts/extraction/pct_item1_capability_extraction_v1.md"
TASK_PROMPT = "prompts/extraction/pct_item1_tasks_flat_v3.md"
TASK_SCHEMA = "schemas/pct_item1_tasks_flat_output.v2.schema.json"
RUN_KIND = "pct_item1_three_stage_smoke_v1"
STAGE1_RAW = "pct_item1_economic_product_consolidation_raw_responses.jsonl"
STAGE1_RECORDS = "pct_item1_economic_product_consolidation_records.jsonl"
STAGE2_RAW = "pct_item1_capability_extraction_raw_responses.jsonl"
STAGE2_RECORDS = "pct_item1_capability_extraction_records.jsonl"
STAGE3_RAW = "pct_item1_customer_tasks_raw_responses.jsonl"
STAGE3_RECORDS = "pct_item1_customer_tasks_records.jsonl"
MANIFEST = "pct_item1_three_stage_manifest.json"
HTML = "pct_item1_three_stage_human_review.html"


def _render_with_item1(template: str, packet: dict[str, Any], heading: str, value: dict[str, Any]) -> str:
    return (
        f"{template}\n\n{render_pilot_prompt('', packet)}\n\n## {heading}\n\n```json\n"
        f"{json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True)}\n```\n"
    )


def build_three_stage_plan(
    *, consolidation_template: str, packets_by_key: dict[tuple[str, str], dict[str, Any]],
    discoveries_by_key: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Render only rows whose fixed upstream discovery map is available."""
    rows = []
    for issuer_name, cik, accession in SMOKE_ROWS:
        key = (cik, accession)
        packet, discovery = packets_by_key.get(key), discoveries_by_key.get(key)
        if packet is None or discovery is None:
            continue
        prompt = _render_with_item1(
            consolidation_template, packet, "Discovery candidate map",
            project_discovery_for_product_capability(discovery),
        )
        rows.append({
            "issuer_name": issuer_name, "cik": cik, "accession": accession,
            "packet_sha256": packet["packet_sha256"], "stage1_prompt": prompt,
            "stage1_prompt_sha256": _sha256_bytes(prompt.encode()),
        })
    if not rows:
        raise ValueError("The supplied discovery artifact has no smoke rows.")
    return rows


def _html(
    stage1: list[dict[str, Any]], stage2: list[dict[str, Any]], stage3: list[dict[str, Any]], run_id: str
) -> str:
    esc = lambda value: html.escape(str(value), quote=True)
    stage2_by_key = {(row["cik"], row["accession"]): row for row in stage2}
    stage3_by_key = {(row["cik"], row["accession"]): row for row in stage3}
    chunks = [
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">",
        "<title>Three-stage Item 1 PCT review</title>",
        "<style>body{font:15px/1.45 system-ui;margin:2rem;max-width:1200px}article{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}code{background:#f2f2f2;padding:.1rem .25rem}</style>",
        f"<h1>Three-stage Item 1 PCT smoke: {esc(run_id)}</h1>",
        "<p>Economic-product boundaries are fixed before capabilities and tasks. This smoke deliberately stops before final task consolidation.</p>",
    ]
    for first in stage1:
        key = (first["cik"], first["accession"])
        chunks.append(f"<article><h2>{esc(first['issuer_name'])}</h2>")
        if first["record_kind"] != "extracted":
            chunks.append(f"<p><strong>Product consolidation needs review:</strong> {esc(first['reason'])} — {esc(first['detail'])}</p></article>")
            continue
        chunks.append("<h3>1. Fixed economic products</h3><ul>")
        for product in first["snapshot"]["economic_products"]:
            chunks.append(f"<li><code>{esc(product['id'])}</code> {esc(product['name'])} — candidates: {esc(', '.join(product['source_product_ids']))}</li>")
        chunks.append("</ul>")
        second = stage2_by_key.get(key)
        if second is None or second["record_kind"] != "extracted":
            chunks.append("<p><strong>Capability extraction unavailable.</strong></p></article>")
            continue
        chunks.append("<h3>2. Capabilities</h3><ul>")
        for product in second["snapshot"]["economic_products"]:
            chunks.append(f"<li><code>{esc(product['id'])}</code>: {esc(', '.join(capability['text'] for capability in product['capabilities']))}</li>")
        chunks.append("</ul><h3>3. Task candidates (before final consolidation)</h3>")
        third = stage3_by_key.get(key)
        if third is None or third["record_kind"] != "extracted":
            chunks.append("<p><strong>Task extraction unavailable.</strong></p>")
        else:
            chunks.append("<ul>")
            for task in third["snapshot"]["tasks"]:
                chunks.append(f"<li><code>{esc(task['economic_product_id'])}/{esc(task['id'])}</code> {esc(task['text'])}</li>")
            chunks.append("</ul>")
        chunks.append("</article>")
    return "\n".join(chunks) + "\n"


def run_three_stage_smoke(
    *, plan: list[dict[str, Any]], packets_by_key: dict[tuple[str, str], dict[str, Any]],
    discoveries_by_key: dict[tuple[str, str], dict[str, Any]], capability_template: str,
    task_template: str, consolidation_validator: Draft202012Validator,
    capability_validator: Draft202012Validator, task_validator: Draft202012Validator,
    output_root: str | Path, run_id: str, consolidation_prompt_sha256: str,
    capability_prompt_sha256: str, task_prompt_sha256: str, discovery_records_sha256: str,
    generate: Callable[[str], str] | None, model: dict[str, Any], clock: Callable[[], datetime],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run later stages only when their fixed upstream map validates."""
    if dry_run:
        return {"run_id": run_id, "dry_run": True, "status": "dry_run", "selected_rows": len(plan), "stage1_model_called_rows": len(plan), "stage2_model_called_rows": len(plan), "stage3_model_called_rows": len(plan), "run_dir": None}
    if generate is None:
        raise ValueError("A live three-stage smoke requires generate.")
    run_dir = create_run_directory(output_root, run_id)
    stage1_raw: list[dict[str, Any]] = []
    stage2_raw: list[dict[str, Any]] = []
    stage3_raw: list[dict[str, Any]] = []
    stage1_records: list[dict[str, Any]] = []
    stage2_records: list[dict[str, Any]] = []
    stage3_records: list[dict[str, Any]] = []
    for row in plan:
        key = (row["cik"], row["accession"])
        common = {field: row[field] for field in ("issuer_name", "cik", "accession", "packet_sha256")}
        raw = generate(row["stage1_prompt"])
        stage1_raw.append({**common, "raw_response": raw, "raw_response_sha256": _sha256_bytes(raw.encode())})
        try:
            products = validate_economic_product_consolidation_output(raw, packets_by_key[key], discoveries_by_key[key], consolidation_validator)
        except CombinedSnapshotFailure as exc:
            stage1_records.append({**common, "rendered_prompt_sha256": row["stage1_prompt_sha256"], "record_kind": "review_uncertain", "reason": exc.reason_code, "detail": exc.detail, "snapshot": None})
            continue
        stage1_records.append({**common, "rendered_prompt_sha256": row["stage1_prompt_sha256"], "record_kind": "extracted", "reason": None, "detail": None, "snapshot": products})
        capability_prompt = _render_with_item1(capability_template, packets_by_key[key], "Fixed economic-product map", {"economic_products": products["economic_products"]})
        raw = generate(capability_prompt)
        stage2_raw.append({**common, "raw_response": raw, "raw_response_sha256": _sha256_bytes(raw.encode())})
        try:
            product_capabilities = validate_capability_extraction_output(raw, packets_by_key[key], products, capability_validator)
        except CombinedSnapshotFailure as exc:
            stage2_records.append({**common, "rendered_prompt_sha256": _sha256_bytes(capability_prompt.encode()), "record_kind": "review_uncertain", "reason": exc.reason_code, "detail": exc.detail, "snapshot": None})
            continue
        stage2_records.append({**common, "rendered_prompt_sha256": _sha256_bytes(capability_prompt.encode()), "record_kind": "extracted", "reason": None, "detail": None, "snapshot": product_capabilities})
        task_prompt = render_task_prompt(task_template, packets_by_key[key], task_candidate_map(product_capabilities))
        raw = generate(task_prompt)
        stage3_raw.append({**common, "raw_response": raw, "raw_response_sha256": _sha256_bytes(raw.encode())})
        try:
            tasks = validate_task_output(raw, packets_by_key[key], task_candidate_map(product_capabilities), task_validator, hierarchy=False)
        except CombinedSnapshotFailure as exc:
            stage3_records.append({**common, "rendered_prompt_sha256": _sha256_bytes(task_prompt.encode()), "record_kind": "review_uncertain", "reason": exc.reason_code, "detail": exc.detail, "snapshot": None})
        else:
            stage3_records.append({**common, "rendered_prompt_sha256": _sha256_bytes(task_prompt.encode()), "record_kind": "extracted", "reason": None, "detail": None, "snapshot": tasks})
    payloads = {
        STAGE1_RAW: "".join(_canonical_line(row) + "\n" for row in stage1_raw).encode(),
        STAGE1_RECORDS: "".join(_canonical_line(row) + "\n" for row in stage1_records).encode(),
        STAGE2_RAW: "".join(_canonical_line(row) + "\n" for row in stage2_raw).encode(),
        STAGE2_RECORDS: "".join(_canonical_line(row) + "\n" for row in stage2_records).encode(),
        STAGE3_RAW: "".join(_canonical_line(row) + "\n" for row in stage3_raw).encode(),
        STAGE3_RECORDS: "".join(_canonical_line(row) + "\n" for row in stage3_records).encode(),
        HTML: _html(stage1_records, stage2_records, stage3_records, run_id).encode(),
    }
    output_hashes = {name: _sha256_bytes(payload) for name, payload in payloads.items()}
    manifest = {
        "run_kind": RUN_KIND, "run_id": run_id, "run_timestamp": clock().isoformat(),
        "economic_product_consolidation_prompt": {"path": CONSOLIDATION_PROMPT, "sha256": consolidation_prompt_sha256},
        "capability_extraction_prompt": {"path": CAPABILITY_PROMPT, "sha256": capability_prompt_sha256},
        "customer_tasks_prompt": {"path": TASK_PROMPT, "sha256": task_prompt_sha256},
        "economic_product_consolidation_schema": CONSOLIDATION_SCHEMA,
        "capability_extraction_schema": CAPABILITY_SCHEMA, "customer_tasks_schema": TASK_SCHEMA,
        "discovery_records_sha256": discovery_records_sha256, "model": model, "selected_rows": len(plan),
        "stage1_model_called_rows": len(stage1_raw), "stage2_model_called_rows": len(stage2_raw), "stage3_model_called_rows": len(stage3_raw),
        "counts": {
            "stage1_extracted": sum(row["record_kind"] == "extracted" for row in stage1_records),
            "stage1_review_uncertain": sum(row["record_kind"] != "extracted" for row in stage1_records),
            "stage2_extracted": sum(row["record_kind"] == "extracted" for row in stage2_records),
            "stage2_review_uncertain": sum(row["record_kind"] != "extracted" for row in stage2_records),
            "stage3_extracted": sum(row["record_kind"] == "extracted" for row in stage3_records),
            "stage3_review_uncertain": sum(row["record_kind"] != "extracted" for row in stage3_records),
        },
        "output_hashes": output_hashes,
        "limitations": ["Development-only four-firm smoke; not a sample or full run.", "Final task consolidation is intentionally not called.", "Each of the first three stages reads full Item 1; the run settles no score, tier, transformation depth, or universe membership."],
    }
    payloads[MANIFEST] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    try:
        for name, payload in payloads.items():
            write_bytes_once(run_dir / name, payload, what=f"three-stage PCT {name}")
    except WriteOnceError as exc:
        raise ValueError(str(exc)) from exc
    return {"run_id": run_id, "dry_run": False, "status": "completed", "run_dir": run_dir, "manifest": manifest, "stage1_records": stage1_records, "stage2_records": stage2_records, "stage3_records": stage3_records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--discovery-run-dir", required=True)
    parser.add_argument("--vertex-project", required=True)
    parser.add_argument("--output-root", default="data/runs/pct-item1-three-stage-smokes")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    templates = {path: (root / path).read_text() for path in (CONSOLIDATION_PROMPT, CAPABILITY_PROMPT, TASK_PROMPT)}
    validators = {
        "consolidation": Draft202012Validator(json.loads((root / CONSOLIDATION_SCHEMA).read_text())),
        "capability": Draft202012Validator(json.loads((root / CAPABILITY_SCHEMA).read_text())),
        "task": Draft202012Validator(json.loads((root / TASK_SCHEMA).read_text())),
    }
    source = Path(args.discovery_run_dir) / "pct_item1_product_structure_records.jsonl"
    discoveries = {(row["cik"], row["accession"]): row["snapshot"] for row in (json.loads(line) for line in source.read_text().splitlines()) if row["record_kind"] == "extracted"}
    packets = load_smoke_packets(root / "data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819/universe_baseline_packets.jsonl")
    plan = build_three_stage_plan(consolidation_template=templates[CONSOLIDATION_PROMPT], packets_by_key=packets, discoveries_by_key=discoveries)
    result = run_three_stage_smoke(
        plan=plan, packets_by_key=packets, discoveries_by_key=discoveries,
        capability_template=templates[CAPABILITY_PROMPT], task_template=templates[TASK_PROMPT],
        consolidation_validator=validators["consolidation"], capability_validator=validators["capability"], task_validator=validators["task"],
        output_root=root / args.output_root, run_id=args.run_id,
        consolidation_prompt_sha256=_sha256_bytes(templates[CONSOLIDATION_PROMPT].encode()),
        capability_prompt_sha256=_sha256_bytes(templates[CAPABILITY_PROMPT].encode()),
        task_prompt_sha256=_sha256_bytes(templates[TASK_PROMPT].encode()), discovery_records_sha256=_sha256_bytes(source.read_bytes()),
        generate=build_vertex_generator(vertex_project=args.vertex_project) if args.live else None,
        model={"provider": "google_vertex_ai", "model_label": "gemini-2.5-flash"}, clock=lambda: datetime.now().astimezone(), dry_run=not args.live,
    )
    print(json.dumps({key: result[key] for key in ("run_id", "dry_run", "status", "run_dir")}, default=str, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    main()
