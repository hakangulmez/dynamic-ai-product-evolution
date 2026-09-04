"""Fixed five-firm smoke for the Item 1 product-family/product prompt."""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .pct_combined_snapshot import CombinedSnapshotFailure
from .pct_combined_snapshot_smoke import (
    _canonical_line, _sha256_bytes, build_smoke_plan,
    build_vertex_generator, load_smoke_packets,
)
from .pct_product_structure import (
    OUTPUT_CONTRACT, OUTPUT_SCHEMA, validate_product_structure_output,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.freeze import create_run_directory

SMOKE_PROMPT_PATH = "prompts/extraction/pct_item1_product_structure_v1.md"
RUN_KIND = "pct_item1_product_structure_smoke_v1"
RAW_FILENAME = "pct_item1_product_structure_raw_responses.jsonl"
RECORDS_FILENAME = "pct_item1_product_structure_records.jsonl"
MANIFEST_FILENAME = "pct_item1_product_structure_manifest.json"
HTML_FILENAME = "pct_item1_product_structure_human_review.html"


def _html(records: list[dict[str, Any]], *, run_id: str) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)
    chunks = [
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">",
        "<title>PCT product structure smoke review</title>",
        "<style>body{font:15px/1.45 system-ui;margin:2rem;max-width:1100px}"
        "article{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}"
        "code{background:#f2f2f2;padding:.1rem .25rem}"
        "pre{white-space:pre-wrap;background:#f6f6f6;padding:.75rem}</style>",
        f"<h1>PCT product structure smoke: {esc(run_id)}</h1>",
        "<p>Development-only Item 1 five-firm smoke; it makes no scoring or "
        "universe-membership decision.</p>",
    ]
    for record in records:
        chunks.append(f"<article><h2>{esc(record['issuer_name'])}</h2>")
        if record["record_kind"] == "review_uncertain":
            chunks.append(f"<p><strong>Needs review:</strong> {esc(record['review_reason_code'])}</p><pre>{esc(record['review_detail'])}</pre></article>")
            continue
        for group, heading in (("product_families", "Product families"), ("products", "Products")):
            chunks.append(f"<h3>{heading}</h3><ul>")
            for entry in record["snapshot"][group]:
                parent = entry.get("product_family_id")
                suffix = f" → {parent}" if parent else ""
                chunks.append(f"<li><code>{esc(entry['id'])}</code> {esc(entry['name'])}{esc(suffix)} — {esc(', '.join(entry['passage_refs']))}</li>")
            chunks.append("</ul>")
        chunks.append("</article>")
    return "\n".join(chunks) + "\n"


def run_product_structure_smoke(
    *, plan: list[dict[str, Any]], packets_by_key: dict[tuple[str, str], dict[str, Any]],
    output_root: str | Path, run_id: str, prompt_sha256: str, schema_sha256: str,
    generate: Callable[[str], str] | None, model: dict[str, Any],
    clock: Callable[[], datetime], dry_run: bool = False,
) -> dict[str, Any]:
    """Archive one readable response per fixed row; invalid outputs stay reviewable."""
    if dry_run:
        return {"run_id": run_id, "dry_run": True, "status": "dry_run", "selected_rows": len(plan), "model_called_rows": len(plan), "run_dir": None}
    if generate is None:
        raise ValueError("A live product-structure smoke requires generate.")
    root = Path(__file__).resolve().parents[2]
    validator = Draft202012Validator(json.loads((root / OUTPUT_SCHEMA).read_text()))
    run_dir = create_run_directory(output_root, run_id)
    records: list[dict[str, Any]] = []
    raw_entries: list[dict[str, Any]] = []
    for row in plan:
        packet = packets_by_key[(row["cik"], row["accession"])]
        raw = generate(row["rendered_prompt"])
        raw_entries.append({"issuer_name": row["issuer_name"], "cik": row["cik"], "accession": row["accession"], "raw_response": raw, "raw_response_sha256": _sha256_bytes(raw.encode())})
        common = {key: row[key] for key in ("issuer_name", "cik", "accession", "packet_sha256", "rendered_prompt_sha256")}
        try:
            snapshot = validate_product_structure_output(raw, packet, validator)
        except CombinedSnapshotFailure as exc:
            records.append({**common, "record_kind": "review_uncertain", "review_reason_code": exc.reason_code, "review_detail": exc.detail, "snapshot": None})
        else:
            records.append({**common, "record_kind": "extracted", "review_reason_code": None, "review_detail": None, "snapshot": snapshot})
    raw_bytes = "".join(_canonical_line(row) + "\n" for row in raw_entries).encode()
    records_bytes = "".join(_canonical_line(row) + "\n" for row in records).encode()
    html_bytes = _html(records, run_id=run_id).encode()
    hashes = {RAW_FILENAME: _sha256_bytes(raw_bytes), RECORDS_FILENAME: _sha256_bytes(records_bytes), HTML_FILENAME: _sha256_bytes(html_bytes)}
    manifest = {"run_kind": RUN_KIND, "run_id": run_id, "run_timestamp": clock().isoformat(), "prompt_template_path": SMOKE_PROMPT_PATH, "prompt_template_sha256": prompt_sha256, "output_contract": OUTPUT_CONTRACT, "output_schema_sha256": schema_sha256, "model": model, "selected_rows": len(plan), "model_called_rows": len(plan), "counts": {"extracted": sum(row["record_kind"] == "extracted" for row in records), "review_uncertain": sum(row["record_kind"] == "review_uncertain" for row in records)}, "output_hashes": hashes, "limitations": ["Development-only five-firm smoke; not a sample or full run.", "It settles no product ontology, score, tier, or universe membership.", "Model-selected P001 references are validated against the complete rendered packet."]}
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    try:
        for filename, payload in ((RAW_FILENAME, raw_bytes), (RECORDS_FILENAME, records_bytes), (HTML_FILENAME, html_bytes), (MANIFEST_FILENAME, manifest_bytes)):
            write_bytes_once(run_dir / filename, payload, what=f"product structure {filename}")
    except WriteOnceError as exc:
        raise ValueError(str(exc)) from exc
    return {"run_id": run_id, "dry_run": False, "status": "completed", "run_dir": run_dir, "manifest": manifest, "records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--vertex-project", required=True)
    parser.add_argument("--output-root", default="data/runs/pct-item1-product-structure-smokes")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    prompt = (root / SMOKE_PROMPT_PATH).read_text()
    packets = load_smoke_packets(root / "data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819/universe_baseline_packets.jsonl")
    plan = build_smoke_plan(prompt_text=prompt, packets_by_key=packets)
    result = run_product_structure_smoke(plan=plan, packets_by_key=packets, output_root=root / args.output_root, run_id=args.run_id, prompt_sha256=_sha256_bytes(prompt.encode()), schema_sha256=_sha256_bytes((root / OUTPUT_SCHEMA).read_bytes()), generate=build_vertex_generator(vertex_project=args.vertex_project) if args.live else None, model={"provider": "google_vertex_ai", "model_label": "gemini-2.5-flash"}, clock=lambda: datetime.now().astimezone(), dry_run=not args.live)
    print(json.dumps({key: result[key] for key in ("run_id", "dry_run", "status", "run_dir")}, default=str, sort_keys=True))


if __name__ == "__main__":
    main()
