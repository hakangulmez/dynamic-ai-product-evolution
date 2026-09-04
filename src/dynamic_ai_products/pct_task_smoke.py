"""A/B smoke for task-only versus task-family-plus-task Item 1 outputs."""

from __future__ import annotations

import argparse
from datetime import datetime
import html
import json
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .classifier_pilot_v1 import render_pilot_prompt
from .human_review_overlay import passage_refs
from .pct_combined_snapshot import CombinedSnapshotFailure
from .pct_combined_snapshot_smoke import (
    SMOKE_ROWS,
    _canonical_line,
    _sha256_bytes,
    build_vertex_generator,
    load_smoke_packets,
)
from .provenance import WriteOnceError, write_bytes_once
from .universe.freeze import create_run_directory

VARIANTS = {
    "flat": {
        "prompt_path": "prompts/extraction/pct_item1_tasks_flat_v2.md",
        "schema_path": "schemas/pct_item1_tasks_flat_output.v2.schema.json",
        "contract": "pct_item1_tasks_flat_output@0.2.0",
    },
    "hierarchy": {
        "prompt_path": "prompts/extraction/pct_item1_tasks_hierarchy_v2.md",
        "schema_path": "schemas/pct_item1_tasks_hierarchy_output.v2.schema.json",
        "contract": "pct_item1_tasks_hierarchy_output@0.2.0",
    },
}
RUN_KIND = "pct_item1_task_ab_smoke_v1"
RAW_FILENAME = "pct_item1_task_ab_raw_responses.jsonl"
RECORDS_FILENAME = "pct_item1_task_ab_records.jsonl"
MANIFEST_FILENAME = "pct_item1_task_ab_manifest.json"
HTML_FILENAME = "pct_item1_task_ab_human_review.html"


def task_candidate_map(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Preserve economic-product/capability candidates while excluding V1 task families."""
    products = []
    for product in snapshot["economic_products"]:
        capabilities = [
            {
                "capability_ref": f"{product['id']}:{capability['id']}",
                "text": capability["text"],
                "passage_refs": capability["passage_refs"],
            }
            for capability in product["capabilities"]
        ]
        products.append({
            key: product[key]
            for key in ("id", "name", "source_product_ids", "passage_refs")
        } | {"capabilities": capabilities})
    return {"economic_products": products}


def _prompt(template: str, packet: dict[str, Any], candidates: dict[str, Any]) -> str:
    return (
        f"{template}\n\n## Economic product and capability candidate map\n\n```json\n"
        f"{json.dumps(candidates, ensure_ascii=False, indent=2, sort_keys=True)}\n```\n\n"
        f"{render_pilot_prompt('', packet)}"
    )


def _validate(
    raw: str, packet: dict[str, Any], candidates: dict[str, Any],
    validator: Draft202012Validator, *, hierarchy: bool,
    allowed_refs: set[str] | None = None,
) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CombinedSnapshotFailure("invalid_model_json", str(exc)) from exc
    errors = sorted(validator.iter_errors(parsed), key=lambda error: error.json_path)
    if errors:
        raise CombinedSnapshotFailure("snapshot_contract_violation", errors[0].message)
    refs = set(passage_refs(packet)) if allowed_refs is None else allowed_refs
    products = {entry["id"] for entry in candidates["economic_products"]}
    capabilities = {
        entry["capability_ref"]: product["id"]
        for product in candidates["economic_products"]
        for entry in product["capabilities"]
    }
    tasks = parsed["tasks"]
    task_ids = [entry["id"] for entry in tasks]
    if len(task_ids) != len(set(task_ids)):
        raise CombinedSnapshotFailure("duplicate_local_id", "Task IDs repeat.")
    seen_products: set[str] = set()
    for task in tasks:
        product_id = task["economic_product_id"]
        if product_id not in products:
            raise CombinedSnapshotFailure("unknown_economic_product_id", f"{task['id']} names {product_id}.")
        if not all(capabilities.get(capability_ref) == product_id for capability_ref in task["capability_refs"]):
            raise CombinedSnapshotFailure("cross_product_capability_reference", f"{task['id']} names a capability from another product.")
        if not all(reference in refs for reference in task["passage_refs"]):
            raise CombinedSnapshotFailure(
                "evidence_reference_unresolvable",
                f"{task['id']} names a reference outside the available task evidence.",
            )
        seen_products.add(product_id)
    if seen_products != products:
        raise CombinedSnapshotFailure("missing_product_task", "Every input economic product needs at least one task.")
    if hierarchy:
        families = parsed["task_families"]
        family_ids = [entry["id"] for entry in families]
        if len(family_ids) != len(set(family_ids)):
            raise CombinedSnapshotFailure("duplicate_local_id", "Task-family IDs repeat.")
        family_task_ids: list[str] = []
        by_task = {entry["id"]: entry for entry in tasks}
        for family in families:
            family_task_ids.extend(family["task_ids"])
            if family["economic_product_id"] not in products:
                raise CombinedSnapshotFailure("unknown_economic_product_id", f"{family['id']} names an unknown product.")
            if not all(reference in refs for reference in family["passage_refs"]):
                raise CombinedSnapshotFailure("evidence_reference_unresolvable", f"{family['id']} names an absent P reference.")
            for task_id in family["task_ids"]:
                task = by_task.get(task_id)
                if task is None or task["economic_product_id"] != family["economic_product_id"]:
                    raise CombinedSnapshotFailure("invalid_task_family_link", f"{family['id']} has an invalid task link.")
        if sorted(family_task_ids) != sorted(task_ids):
            raise CombinedSnapshotFailure("task_family_partition_violation", "Each task must be in exactly one family.")
    return parsed


def _html(records: list[dict[str, Any]], run_id: str) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)
    chunks = ["<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">", "<title>Task granularity A/B</title>", "<style>body{font:15px/1.45 system-ui;margin:2rem;max-width:1200px}article{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}code{background:#f2f2f2;padding:.1rem .25rem}h3{margin-top:1.5rem}</style>", f"<h1>Task granularity A/B smoke: {esc(run_id)}</h1>", "<p>Same economic-product and capability candidates; flat tasks versus task-family-plus-task. Development-only and non-decisional.</p>"]
    for row in records:
        chunks.append(f"<article><h2>{esc(row['issuer_name'])}</h2>")
        for variant in ("flat", "hierarchy"):
            result = row["variants"][variant]
            chunks.append(f"<h3>{esc(variant)}</h3>")
            if result["record_kind"] == "review_uncertain":
                chunks.append(f"<p><strong>Needs review:</strong> {esc(result['reason'])} — {esc(result['detail'])}</p>")
                continue
            snapshot = result["snapshot"]
            if variant == "hierarchy":
                chunks.append("<p>Families: " + esc(", ".join(f"{f['id']}: {f['name']}" for f in snapshot["task_families"])) + "</p>")
            chunks.append("<ul>")
            for task in snapshot["tasks"]:
                chunks.append(f"<li><code>{esc(task['economic_product_id'])}/{esc(task['id'])}</code> {esc(task['text'])} — {esc(', '.join(task['capability_refs']))}; {esc(', '.join(task['passage_refs']))}</li>")
            chunks.append("</ul>")
        chunks.append("</article>")
    return "\n".join(chunks) + "\n"


def run_task_ab_smoke(
    *, candidates_by_key: dict[tuple[str, str], dict[str, Any]], packets_by_key: dict[tuple[str, str], dict[str, Any]],
    prompts: dict[str, str], validators: dict[str, Draft202012Validator], output_root: str | Path,
    run_id: str, candidate_records_sha256: str, generate: Callable[[str], str] | None,
    clock: Callable[[], datetime], dry_run: bool = False,
) -> dict[str, Any]:
    """Run both prompt variants over exactly the same saved input candidate maps."""
    keys = [
        (cik, accession)
        for _name, cik, accession in SMOKE_ROWS
        if (cik, accession) in candidates_by_key
    ]
    if dry_run:
        return {"run_id": run_id, "dry_run": True, "status": "dry_run", "selected_rows": len(keys), "model_called_rows": len(keys) * len(VARIANTS), "run_dir": None}
    if generate is None:
        raise ValueError("A live task A/B smoke requires a generate callable.")
    run_dir = create_run_directory(output_root, run_id)
    records: list[dict[str, Any]] = []
    raw_entries: list[dict[str, Any]] = []
    names = {(cik, accession): name for name, cik, accession in SMOKE_ROWS}
    for key in keys:
        packet, candidates = packets_by_key[key], candidates_by_key[key]
        variants: dict[str, Any] = {}
        for variant, configuration in VARIANTS.items():
            rendered = _prompt(prompts[variant], packet, candidates)
            raw = generate(rendered)
            raw_entries.append({"variant": variant, "cik": key[0], "accession": key[1], "raw_response": raw, "raw_response_sha256": _sha256_bytes(raw.encode())})
            try:
                snapshot = _validate(raw, packet, candidates, validators[variant], hierarchy=variant == "hierarchy")
            except CombinedSnapshotFailure as exc:
                variants[variant] = {"record_kind": "review_uncertain", "reason": exc.reason_code, "detail": exc.detail, "snapshot": None}
            else:
                variants[variant] = {"record_kind": "extracted", "reason": None, "detail": None, "snapshot": snapshot}
        records.append({"issuer_name": names[key], "cik": key[0], "accession": key[1], "packet_sha256": packet["packet_sha256"], "candidate_map": candidates, "variants": variants})
    raw_bytes = "".join(_canonical_line(row) + "\n" for row in raw_entries).encode()
    records_bytes = "".join(_canonical_line(row) + "\n" for row in records).encode()
    html_bytes = _html(records, run_id).encode()
    output_hashes = {RAW_FILENAME: _sha256_bytes(raw_bytes), RECORDS_FILENAME: _sha256_bytes(records_bytes), HTML_FILENAME: _sha256_bytes(html_bytes)}
    manifest = {"run_kind": RUN_KIND, "run_id": run_id, "run_timestamp": clock().isoformat(), "candidate_records_sha256": candidate_records_sha256, "prompt_templates": {name: {"path": cfg["prompt_path"], "sha256": _sha256_bytes(prompts[name].encode())} for name, cfg in VARIANTS.items()}, "output_contracts": {name: cfg["contract"] for name, cfg in VARIANTS.items()}, "selected_rows": len(keys), "model_called_rows": len(raw_entries), "counts": {name: sum(record["variants"][name]["record_kind"] == "extracted" for record in records) for name in VARIANTS}, "output_hashes": output_hashes, "limitations": ["Development-only A/B smoke, not a sample or production run.", "The product/capability candidate maps are fixed across variants; task families from the preceding run are excluded from both model inputs.", "It settles no product ontology, score, tier, transformation depth, or universe membership."]}
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    try:
        for filename, data in ((RAW_FILENAME, raw_bytes), (RECORDS_FILENAME, records_bytes), (HTML_FILENAME, html_bytes), (MANIFEST_FILENAME, manifest_bytes)):
            write_bytes_once(run_dir / filename, data, what=f"task A/B {filename}")
    except WriteOnceError as exc:
        raise ValueError(str(exc)) from exc
    return {"run_id": run_id, "dry_run": False, "status": "completed", "run_dir": run_dir, "manifest": manifest, "records": records}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--economic-run-dir", required=True)
    parser.add_argument("--vertex-project", required=True)
    parser.add_argument("--output-root", default="data/runs/pct-item1-task-ab-smokes")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    prompts = {name: (root / cfg["prompt_path"]).read_text() for name, cfg in VARIANTS.items()}
    validators = {name: Draft202012Validator(json.loads((root / cfg["schema_path"]).read_text())) for name, cfg in VARIANTS.items()}
    source = Path(args.economic_run_dir) / "pct_item1_economic_pct_records.jsonl"
    candidates = {(row["cik"], row["accession"]): task_candidate_map(row["snapshot"]) for row in (json.loads(line) for line in source.read_text().splitlines()) if row["record_kind"] == "extracted"}
    packets = load_smoke_packets(root / "data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819/universe_baseline_packets.jsonl")
    result = run_task_ab_smoke(candidates_by_key=candidates, packets_by_key=packets, prompts=prompts, validators=validators, output_root=root / args.output_root, run_id=args.run_id, candidate_records_sha256=_sha256_bytes(source.read_bytes()), generate=build_vertex_generator(vertex_project=args.vertex_project) if args.live else None, clock=lambda: datetime.now().astimezone(), dry_run=not args.live)
    print(json.dumps({key: result[key] for key in ("run_id", "dry_run", "status", "run_dir")}, default=str, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    main()
