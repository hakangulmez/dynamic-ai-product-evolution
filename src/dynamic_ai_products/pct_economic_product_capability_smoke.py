"""Five-firm smoke: saved discovery candidates -> economic products and capabilities."""

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
    _canonical_line,
    _sha256_bytes,
    build_vertex_generator,
    load_smoke_packets,
)
from .pct_economic_pct_smoke import build_economic_pct_plan
from .pct_economic_product_capability import (
    OUTPUT_CONTRACT,
    OUTPUT_SCHEMA,
    validate_economic_product_capability_output,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.freeze import create_run_directory

PROMPT_PATH = "prompts/extraction/pct_item1_economic_product_capability_v1.md"
RUN_KIND = "pct_item1_economic_product_capability_smoke_v1"
RAW_FILENAME = "pct_item1_economic_product_capability_raw_responses.jsonl"
RECORDS_FILENAME = "pct_item1_economic_product_capability_records.jsonl"
MANIFEST_FILENAME = "pct_item1_economic_product_capability_manifest.json"
HTML_FILENAME = "pct_item1_economic_product_capability_human_review.html"


def _html(records: list[dict[str, Any]], run_id: str) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    chunks = [
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">",
        "<title>Economic product and capability review</title>",
        "<style>body{font:15px/1.45 system-ui;margin:2rem;max-width:1200px}"
        "article{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}"
        "code{background:#f2f2f2;padding:.1rem .25rem}</style>",
        f"<h1>Economic product and capability smoke: {esc(run_id)}</h1>",
        "<p>Development-only Item 1 smoke. It settles no task taxonomy, score, tier, transformation depth, or universe membership.</p>",
    ]
    for record in records:
        chunks.append(f"<article><h2>{esc(record['issuer_name'])}</h2>")
        if record["record_kind"] == "review_uncertain":
            chunks.append(
                f"<p><strong>Needs review:</strong> {esc(record['reason'])} — "
                f"{esc(record['detail'])}</p></article>"
            )
            continue
        for product in record["snapshot"]["economic_products"]:
            chunks.append(f"<h3><code>{esc(product['id'])}</code> {esc(product['name'])}</h3><ul>")
            for capability in product["capabilities"]:
                chunks.append(
                    f"<li><code>{esc(capability['id'])}</code> {esc(capability['text'])} — "
                    f"{esc(', '.join(capability['passage_refs']))}</li>"
                )
            chunks.append("</ul>")
        chunks.append("</article>")
    return "\n".join(chunks) + "\n"


def run_economic_product_capability_smoke(
    *,
    plan: list[dict[str, Any]],
    packets_by_key: dict[tuple[str, str], dict[str, Any]],
    discoveries_by_key: dict[tuple[str, str], dict[str, Any]],
    output_root: str | Path,
    run_id: str,
    prompt_sha256: str,
    schema_sha256: str,
    discovery_records_sha256: str,
    generate: Callable[[str], str] | None,
    model: dict[str, Any],
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run product/capability extraction over saved discovery maps."""
    if dry_run:
        return {
            "run_id": run_id,
            "dry_run": True,
            "status": "dry_run",
            "selected_rows": len(plan),
            "model_called_rows": len(plan),
            "run_dir": None,
        }
    if generate is None:
        raise ValueError("A live product/capability smoke requires generate.")
    validator = Draft202012Validator(
        json.loads((Path(__file__).resolve().parents[2] / OUTPUT_SCHEMA).read_text())
    )
    run_dir = create_run_directory(output_root, run_id)
    raw_entries: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for row in plan:
        key = (row["cik"], row["accession"])
        raw = generate(row["rendered_prompt"])
        raw_entries.append({
            "issuer_name": row["issuer_name"],
            "cik": key[0],
            "accession": key[1],
            "raw_response": raw,
            "raw_response_sha256": _sha256_bytes(raw.encode()),
        })
        common = {
            field: row[field]
            for field in ("issuer_name", "cik", "accession", "packet_sha256", "rendered_prompt_sha256")
        }
        try:
            snapshot = validate_economic_product_capability_output(
                raw, packets_by_key[key], discoveries_by_key[key], validator
            )
        except CombinedSnapshotFailure as exc:
            records.append({
                **common,
                "record_kind": "review_uncertain",
                "reason": exc.reason_code,
                "detail": exc.detail,
                "snapshot": None,
            })
        else:
            records.append({
                **common,
                "record_kind": "extracted",
                "reason": None,
                "detail": None,
                "snapshot": snapshot,
            })
    raw_bytes = "".join(_canonical_line(row) + "\n" for row in raw_entries).encode()
    records_bytes = "".join(_canonical_line(row) + "\n" for row in records).encode()
    html_bytes = _html(records, run_id).encode()
    hashes = {
        RAW_FILENAME: _sha256_bytes(raw_bytes),
        RECORDS_FILENAME: _sha256_bytes(records_bytes),
        HTML_FILENAME: _sha256_bytes(html_bytes),
    }
    manifest = {
        "run_kind": RUN_KIND,
        "run_id": run_id,
        "run_timestamp": clock().isoformat(),
        "prompt_template_path": PROMPT_PATH,
        "prompt_template_sha256": prompt_sha256,
        "output_contract": OUTPUT_CONTRACT,
        "output_schema_sha256": schema_sha256,
        "discovery_records_sha256": discovery_records_sha256,
        "model": model,
        "selected_rows": len(plan),
        "model_called_rows": len(plan),
        "counts": {
            "extracted": sum(row["record_kind"] == "extracted" for row in records),
            "review_uncertain": sum(row["record_kind"] == "review_uncertain" for row in records),
        },
        "output_hashes": hashes,
        "limitations": [
            "Development-only five-firm smoke; not a sample or full run.",
            "Discovery remains high-recall candidate input, not a product finding.",
            "The run settles no task taxonomy, score, tier, transformation depth, or universe membership.",
        ],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    try:
        for filename, payload in (
            (RAW_FILENAME, raw_bytes),
            (RECORDS_FILENAME, records_bytes),
            (HTML_FILENAME, html_bytes),
            (MANIFEST_FILENAME, manifest_bytes),
        ):
            write_bytes_once(
                run_dir / filename, payload, what=f"economic product/capability {filename}"
            )
    except WriteOnceError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "run_id": run_id,
        "dry_run": False,
        "status": "completed",
        "run_dir": run_dir,
        "manifest": manifest,
        "records": records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--discovery-run-dir", required=True)
    parser.add_argument("--vertex-project", required=True)
    parser.add_argument("--output-root", default="data/runs/pct-item1-economic-product-capability-smokes")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    prompt = (root / PROMPT_PATH).read_text()
    source = Path(args.discovery_run_dir) / "pct_item1_product_structure_records.jsonl"
    discoveries = {
        (row["cik"], row["accession"]): row["snapshot"]
        for row in (json.loads(line) for line in source.read_text().splitlines())
        if row["record_kind"] == "extracted"
    }
    packets = load_smoke_packets(
        root / "data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819"
        / "universe_baseline_packets.jsonl"
    )
    plan = build_economic_pct_plan(
        prompt_text=prompt, packets_by_key=packets, discoveries_by_key=discoveries
    )
    result = run_economic_product_capability_smoke(
        plan=plan,
        packets_by_key=packets,
        discoveries_by_key=discoveries,
        output_root=root / args.output_root,
        run_id=args.run_id,
        prompt_sha256=_sha256_bytes(prompt.encode()),
        schema_sha256=_sha256_bytes((root / OUTPUT_SCHEMA).read_bytes()),
        discovery_records_sha256=_sha256_bytes(source.read_bytes()),
        generate=(build_vertex_generator(vertex_project=args.vertex_project) if args.live else None),
        model={"provider": "google_vertex_ai", "model_label": "gemini-2.5-flash"},
        clock=lambda: datetime.now().astimezone(),
        dry_run=not args.live,
    )
    summary = {key: result[key] for key in ("run_id", "dry_run", "status", "run_dir")}
    if not result["dry_run"]:
        summary["counts"] = result["manifest"]["counts"]
    print(json.dumps(summary, default=str, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    main()
