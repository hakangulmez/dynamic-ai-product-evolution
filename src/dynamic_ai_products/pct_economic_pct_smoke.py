"""Five-firm smoke: discovery candidates -> economic product PCT."""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .classifier_pilot_v1 import render_pilot_prompt
from .pct_combined_snapshot import CombinedSnapshotFailure
from .pct_combined_snapshot_smoke import (
    SMOKE_ROWS,
    _canonical_line,
    _sha256_bytes,
    build_vertex_generator,
    load_smoke_packets,
)
from .pct_economic_pct import OUTPUT_CONTRACT, OUTPUT_SCHEMA, validate_economic_pct_output
from .provenance import WriteOnceError, write_bytes_once
from .universe.freeze import create_run_directory

PROMPT_PATH = "prompts/extraction/pct_item1_economic_pct_v1.md"
RUN_KIND = "pct_item1_economic_pct_smoke_v1"
RAW_FILENAME = "pct_item1_economic_pct_raw_responses.jsonl"
RECORDS_FILENAME = "pct_item1_economic_pct_records.jsonl"
MANIFEST_FILENAME = "pct_item1_economic_pct_manifest.json"
HTML_FILENAME = "pct_item1_economic_pct_human_review.html"


def render_economic_pct_prompt(template: str, packet_prompt: str, discovery: dict[str, Any]) -> str:
    """Append a saved candidate map before the complete Item 1 packet."""
    candidate_map = json.dumps(discovery, ensure_ascii=False, indent=2, sort_keys=True)
    return f"{template}\n\n## Discovery candidate map\n\n```json\n{candidate_map}\n```\n\n{packet_prompt}"


def build_economic_pct_plan(
    *, prompt_text: str, packets_by_key: dict[tuple[str, str], dict[str, Any]],
    discoveries_by_key: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Render each successfully discovered map plus its full packet.

    A readable but invalid discovery response has no trustworthy candidate map,
    so it remains in the preceding discovery review artifact rather than being
    guessed or re-run here.
    """
    plan: list[dict[str, Any]] = []
    for issuer_name, cik, accession in SMOKE_ROWS:
        key = (cik, accession)
        packet = packets_by_key.get(key)
        discovery = discoveries_by_key.get(key)
        if discovery is None:
            continue
        if packet is None:
            raise ValueError(f"Packet is unavailable for {issuer_name} ({key}).")
        rendered = render_economic_pct_prompt(
            prompt_text, render_pilot_prompt("", packet), discovery
        )
        plan.append({
            "issuer_name": issuer_name,
            "cik": cik,
            "accession": accession,
            "packet_sha256": packet["packet_sha256"],
            "rendered_prompt": rendered,
            "rendered_prompt_sha256": _sha256_bytes(rendered.encode()),
        })
    if not plan:
        raise ValueError("The discovery artifact supplies no extracted candidate maps.")
    return plan


def _resolved_text(snapshot: dict[str, Any], packet: dict[str, Any]) -> dict[str, str]:
    refs = {f"P{index:03d}": item["text"] for index, item in enumerate(packet["passages"], 1)}
    wanted: set[str] = set()
    for economic_product in snapshot["economic_products"]:
        wanted.update(economic_product["passage_refs"])
        for capability in economic_product["capabilities"]:
            wanted.update(capability["passage_refs"])
        for task in economic_product["task_families"]:
            wanted.update(task["passage_refs"])
    return {reference: refs[reference] for reference in sorted(wanted)}


def _html(records: list[dict[str, Any]], *, run_id: str) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    chunks = [
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">",
        "<title>Economic PCT smoke review</title>",
        "<style>body{font:15px/1.45 system-ui;margin:2rem;max-width:1200px}"
        "article{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}"
        "code{background:#f2f2f2;padding:.1rem .25rem}pre{white-space:pre-wrap;background:#f6f6f6;padding:.75rem}</style>",
        f"<h1>Economic PCT smoke: {esc(run_id)}</h1>",
        "<p>Development-only: saved discovery candidates are consolidated into economic products and their PCT map. It settles no ontology, score, tier, or universe membership.</p>",
    ]
    for record in records:
        chunks.append(f"<article><h2>{esc(record['issuer_name'])}</h2>")
        if record["record_kind"] == "review_uncertain":
            chunks.append(f"<p><strong>Needs review:</strong> {esc(record['review_reason_code'])}</p><pre>{esc(record['review_detail'])}</pre></article>")
            continue
        for entry in record["snapshot"]["economic_products"]:
            chunks.append(f"<h3><code>{esc(entry['id'])}</code> {esc(entry['name'])}</h3>")
            chunks.append(f"<p>Discovery products: {esc(', '.join(entry['source_product_ids']))}; evidence: {esc(', '.join(entry['passage_refs']))}</p>")
            chunks.append("<h4>Capabilities</h4><ul>")
            for capability in entry["capabilities"]:
                chunks.append(f"<li><code>{esc(capability['id'])}</code> {esc(capability['text'])} — {esc(', '.join(capability['passage_refs']))}</li>")
            chunks.append("</ul><h4>Task families</h4><ul>")
            for task in entry["task_families"]:
                chunks.append(f"<li><code>{esc(task['id'])}</code> {esc(task['text'])} — {esc(task['customer_outcome'])}; {esc(', '.join(task['passage_refs']))}</li>")
            chunks.append("</ul>")
        chunks.append(f"<h3>Not selected discovery products</h3><p>{esc(', '.join(record['snapshot']['not_selected_product_ids'])) or '(none)'}</p>")
        chunks.append("<h3>Resolved evidence</h3>")
        for reference, text in record["resolved_evidence"].items():
            chunks.append(f"<details><summary><code>{esc(reference)}</code></summary><pre>{esc(text)}</pre></details>")
        chunks.append("</article>")
    return "\n".join(chunks) + "\n"


def run_economic_pct_smoke(
    *, plan: list[dict[str, Any]], packets_by_key: dict[tuple[str, str], dict[str, Any]],
    discoveries_by_key: dict[tuple[str, str], dict[str, Any]], output_root: str | Path,
    run_id: str, prompt_sha256: str, schema_sha256: str, discovery_records_sha256: str,
    generate: Callable[[str], str] | None, model: dict[str, Any],
    clock: Callable[[], datetime], dry_run: bool = False,
) -> dict[str, Any]:
    """Run a second model call over a fixed saved discovery map."""
    if not plan or len(plan) > len(SMOKE_ROWS):
        raise ValueError("The economic PCT smoke must use one to five discovery rows.")
    if dry_run:
        return {"run_id": run_id, "dry_run": True, "status": "dry_run", "selected_rows": len(plan), "model_called_rows": len(plan), "run_dir": None}
    if generate is None:
        raise ValueError("A live economic PCT smoke requires generate.")
    validator = Draft202012Validator(json.loads((Path(__file__).resolve().parents[2] / OUTPUT_SCHEMA).read_text()))
    run_dir = create_run_directory(output_root, run_id)
    records: list[dict[str, Any]] = []
    raw_entries: list[dict[str, Any]] = []
    for row in plan:
        key = (row["cik"], row["accession"])
        raw = generate(row["rendered_prompt"])
        raw_entries.append({"issuer_name": row["issuer_name"], "cik": key[0], "accession": key[1], "raw_response": raw, "raw_response_sha256": _sha256_bytes(raw.encode())})
        common = {field: row[field] for field in ("issuer_name", "cik", "accession", "packet_sha256", "rendered_prompt_sha256")}
        try:
            snapshot = validate_economic_pct_output(raw, packets_by_key[key], discoveries_by_key[key], validator)
        except CombinedSnapshotFailure as exc:
            records.append({**common, "record_kind": "review_uncertain", "review_reason_code": exc.reason_code, "review_detail": exc.detail, "snapshot": None, "resolved_evidence": {}})
        else:
            records.append({**common, "record_kind": "extracted", "review_reason_code": None, "review_detail": None, "snapshot": snapshot, "resolved_evidence": _resolved_text(snapshot, packets_by_key[key])})
    raw_bytes = "".join(_canonical_line(row) + "\n" for row in raw_entries).encode()
    records_bytes = "".join(_canonical_line(row) + "\n" for row in records).encode()
    html_bytes = _html(records, run_id=run_id).encode()
    hashes = {RAW_FILENAME: _sha256_bytes(raw_bytes), RECORDS_FILENAME: _sha256_bytes(records_bytes), HTML_FILENAME: _sha256_bytes(html_bytes)}
    manifest = {"run_kind": RUN_KIND, "run_id": run_id, "run_timestamp": clock().isoformat(), "prompt_template_path": PROMPT_PATH, "prompt_template_sha256": prompt_sha256, "output_contract": OUTPUT_CONTRACT, "output_schema_sha256": schema_sha256, "discovery_records_sha256": discovery_records_sha256, "model": model, "selected_rows": len(plan), "model_called_rows": len(plan), "counts": {"extracted": sum(row["record_kind"] == "extracted" for row in records), "review_uncertain": sum(row["record_kind"] == "review_uncertain" for row in records)}, "output_hashes": hashes, "limitations": ["Development-only smoke; not a sample or full run.", "Rows without a validated discovery map remain in the preceding discovery artifact and are not re-run here.", "Discovery is high-recall candidate input, not a product finding.", "The run settles no ontology, score, tier, or universe membership."]}
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    try:
        for filename, payload in ((RAW_FILENAME, raw_bytes), (RECORDS_FILENAME, records_bytes), (HTML_FILENAME, html_bytes), (MANIFEST_FILENAME, manifest_bytes)):
            write_bytes_once(run_dir / filename, payload, what=f"economic PCT {filename}")
    except WriteOnceError as exc:
        raise ValueError(str(exc)) from exc
    return {"run_id": run_id, "dry_run": False, "status": "completed", "run_dir": run_dir, "manifest": manifest, "records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--discovery-run-dir", required=True)
    parser.add_argument("--vertex-project", required=True)
    parser.add_argument("--output-root", default="data/runs/pct-item1-economic-pct-smokes")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    prompt = (root / PROMPT_PATH).read_text()
    discovery_records_path = Path(args.discovery_run_dir) / "pct_item1_product_structure_records.jsonl"
    discoveries = {(row["cik"], row["accession"]): row["snapshot"] for row in (json.loads(line) for line in discovery_records_path.read_text().splitlines()) if row["record_kind"] == "extracted"}
    packets = load_smoke_packets(root / "data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819/universe_baseline_packets.jsonl")
    plan = build_economic_pct_plan(
        prompt_text=prompt, packets_by_key=packets, discoveries_by_key=discoveries
    )
    result = run_economic_pct_smoke(plan=plan, packets_by_key=packets, discoveries_by_key=discoveries, output_root=root / args.output_root, run_id=args.run_id, prompt_sha256=_sha256_bytes(prompt.encode()), schema_sha256=_sha256_bytes((root / OUTPUT_SCHEMA).read_bytes()), discovery_records_sha256=_sha256_bytes(discovery_records_path.read_bytes()), generate=build_vertex_generator(vertex_project=args.vertex_project) if args.live else None, model={"provider": "google_vertex_ai", "model_label": "gemini-2.5-flash"}, clock=lambda: datetime.now().astimezone(), dry_run=not args.live)
    summary = {key: result[key] for key in ("run_id", "dry_run", "status", "run_dir")}
    if not result["dry_run"]:
        summary["counts"] = result["manifest"]["counts"]
    print(json.dumps(summary, default=str, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover - exercised by smoke invocation
    main()
