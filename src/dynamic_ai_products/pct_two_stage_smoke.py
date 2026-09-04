"""Bounded two-stage Item 1 PCT smoke: products/capabilities, then tasks."""

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
from .pct_economic_product_capability import (
    OUTPUT_SCHEMA as PRODUCT_CAPABILITY_SCHEMA,
    validate_economic_product_capability_output,
)
from .pct_task_smoke import _validate as validate_task_output
from .pct_task_smoke import task_candidate_map
from .provenance import WriteOnceError, write_bytes_once
from .universe.freeze import create_run_directory

PRODUCT_CAPABILITY_PROMPT = "prompts/extraction/pct_item1_economic_product_capability_v2.md"
PRODUCT_CAPABILITY_PROMPT_V3 = "prompts/extraction/pct_item1_economic_product_capability_v3.md"
PRODUCT_CAPABILITY_PROMPTS = (
    PRODUCT_CAPABILITY_PROMPT,
    PRODUCT_CAPABILITY_PROMPT_V3,
)
TASK_PROMPT = "prompts/extraction/pct_item1_tasks_flat_v3.md"
TASK_PROMPT_V4 = "prompts/extraction/pct_item1_tasks_flat_v4.md"
TASK_PROMPT_V5 = "prompts/extraction/pct_item1_tasks_flat_v5.md"
TASK_PROMPTS = (TASK_PROMPT, TASK_PROMPT_V4, TASK_PROMPT_V5)
TASK_SCHEMA = "schemas/pct_item1_tasks_flat_output.v2.schema.json"
RUN_KIND = "pct_item1_two_stage_smoke_v1"
STAGE1_RAW = "pct_item1_product_capability_raw_responses.jsonl"
STAGE1_RECORDS = "pct_item1_product_capability_records.jsonl"
STAGE2_RAW = "pct_item1_customer_tasks_raw_responses.jsonl"
STAGE2_RECORDS = "pct_item1_customer_tasks_records.jsonl"
MANIFEST = "pct_item1_two_stage_manifest.json"
HTML = "pct_item1_two_stage_human_review.html"


def render_product_capability_prompt(
    template: str, packet: dict[str, Any], discovery: dict[str, Any]
) -> str:
    """Render Item 1 before a projection that hides family implementation IDs."""
    candidate_map = project_discovery_for_product_capability(discovery)
    return (
        f"{template}\n\n{render_pilot_prompt('', packet)}"
        "\n\n## Discovery candidate map\n\n```json\n"
        f"{json.dumps(candidate_map, ensure_ascii=False, indent=2, sort_keys=True)}\n```\n"
    )


def project_discovery_for_product_capability(discovery: dict[str, Any]) -> dict[str, Any]:
    """Expose family names and their P-product members, never opaque F IDs.

    ``F#`` is a discovery-only implementation key.  Rendering it invites a
    model to copy that key into ``source_product_ids``, whose contract permits
    only candidate product keys.  The projection preserves every model-useful
    relation while making the invalid token unrepresentable in the prompt.
    """
    products = discovery["products"]
    members_by_family: dict[str, list[str]] = {}
    for product in products:
        family_id = product.get("product_family_id")
        if family_id is not None:
            members_by_family.setdefault(family_id, []).append(product["id"])
    families = []
    for family in discovery["product_families"]:
        members = members_by_family.get(family["id"], [])
        if members:
            families.append({
                "name": family["name"],
                "associated_product_ids": members,
                "passage_refs": family["passage_refs"],
            })
    return {
        "product_families": families,
        "products": [{
            key: product[key]
            for key in ("id", "name", "passage_refs", "availability_status")
            if key in product
        } for product in products],
    }


def _task_evidence_refs(candidates: dict[str, Any]) -> set[str]:
    """Return the Item 1 addresses already selected by the upstream map."""
    return {
        ref
        for product in candidates["economic_products"]
        for entry in [product, *product["capabilities"]]
        for ref in entry["passage_refs"]
    }


def _render_task_evidence_bundle(
    packet: dict[str, Any], candidates: dict[str, Any]
) -> str:
    """Render only Item 1 blocks selected as product/capability evidence."""
    displayed = passage_refs(packet)
    by_id = {passage["passage_id"]: passage for passage in packet["passages"]}
    blocks = []
    for ref in sorted(_task_evidence_refs(candidates)):
        passage_id = displayed.get(ref)
        if passage_id is None:
            raise ValueError(f"Selected task evidence names absent passage {ref!r}.")
        blocks.append(f"[{ref}]\n{by_id[passage_id]['text']}")
    return "\n\n".join(blocks)


def render_task_prompt(
    template: str,
    packet: dict[str, Any],
    candidates: dict[str, Any],
    *,
    selected_evidence_only: bool = False,
) -> str:
    """Render a fixed upstream map with full Item 1 or its selected evidence."""
    candidate_map = (
        "\n\n## Fixed economic-product and capability map\n\n```json\n"
        f"{json.dumps(candidates, ensure_ascii=False, indent=2, sort_keys=True)}\n```\n"
    )
    if selected_evidence_only:
        return (
            f"{template}{candidate_map}"
            "\n## Selected Item 1 evidence\n\n"
            f"{_render_task_evidence_bundle(packet, candidates)}\n"
        )
    return (
        f"{template}\n\n{render_pilot_prompt('', packet)}"
        f"{candidate_map}"
    )


def build_two_stage_plan(
    *,
    product_capability_template: str,
    packets_by_key: dict[tuple[str, str], dict[str, Any]],
    discoveries_by_key: dict[tuple[str, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build the fixed five-firm plan from verified packets and discovery maps."""
    rows: list[dict[str, Any]] = []
    for issuer_name, cik, accession in SMOKE_ROWS:
        key = (cik, accession)
        packet = packets_by_key.get(key)
        discovery = discoveries_by_key.get(key)
        if packet is None or discovery is None:
            continue
        rendered = render_product_capability_prompt(product_capability_template, packet, discovery)
        rows.append({
            "issuer_name": issuer_name,
            "cik": cik,
            "accession": accession,
            "packet_sha256": packet["packet_sha256"],
            "stage1_prompt": rendered,
            "stage1_prompt_sha256": _sha256_bytes(rendered.encode()),
        })
    if not rows:
        raise ValueError("The discovery artifact supplies no smoke rows.")
    return rows


def _html(stage1: list[dict[str, Any]], stage2: list[dict[str, Any]], run_id: str) -> str:
    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    stage2_by_key = {(row["cik"], row["accession"]): row for row in stage2}
    chunks = [
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">",
        "<title>Two-stage Item 1 PCT review</title>",
        "<style>body{font:15px/1.45 system-ui;margin:2rem;max-width:1200px}"
        "article{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}"
        "code{background:#f2f2f2;padding:.1rem .25rem}</style>",
        f"<h1>Two-stage Item 1 PCT smoke: {esc(run_id)}</h1>",
        "<p>Stage 1 fixes economic products and capabilities. Stage 2 can only map "
        "those fixed products to customer tasks. Development-only and non-decisional.</p>",
    ]
    for first in stage1:
        key = (first["cik"], first["accession"])
        chunks.append(f"<article><h2>{esc(first['issuer_name'])}</h2>")
        if first["record_kind"] != "extracted":
            chunks.append(
                f"<p><strong>Stage 1 needs review:</strong> {esc(first['reason'])} — "
                f"{esc(first['detail'])}</p></article>"
            )
            continue
        chunks.append("<h3>Stage 1: economic products and capabilities</h3>")
        for product in first["snapshot"]["economic_products"]:
            chunks.append(
                f"<h4><code>{esc(product['id'])}</code> {esc(product['name'])}</h4>"
                f"<p>Source candidates: {esc(', '.join(product['source_product_ids']))}</p><ul>"
            )
            for capability in product["capabilities"]:
                chunks.append(f"<li>{esc(capability['text'])}</li>")
            chunks.append("</ul>")
        second = stage2_by_key.get(key)
        chunks.append("<h3>Stage 2: customer tasks</h3>")
        if second is None:
            chunks.append("<p><strong>Not called:</strong> stage 1 was not available.</p>")
        elif second["record_kind"] != "extracted":
            chunks.append(
                f"<p><strong>Needs review:</strong> {esc(second['reason'])} — "
                f"{esc(second['detail'])}</p>"
            )
        else:
            chunks.append("<ul>")
            for task in second["snapshot"]["tasks"]:
                chunks.append(
                    f"<li><code>{esc(task['economic_product_id'])}/{esc(task['id'])}</code> "
                    f"{esc(task['text'])}</li>"
                )
            chunks.append("</ul>")
        chunks.append("</article>")
    return "\n".join(chunks) + "\n"


def run_two_stage_smoke(
    *,
    plan: list[dict[str, Any]],
    packets_by_key: dict[tuple[str, str], dict[str, Any]],
    discoveries_by_key: dict[tuple[str, str], dict[str, Any]],
    task_template: str,
    product_validator: Draft202012Validator,
    task_validator: Draft202012Validator,
    output_root: str | Path,
    run_id: str,
    product_prompt_path: str = PRODUCT_CAPABILITY_PROMPT,
    product_prompt_sha256: str,
    task_prompt_path: str = TASK_PROMPT,
    task_prompt_sha256: str,
    discovery_records_sha256: str,
    generate: Callable[[str], str] | None,
    model: dict[str, Any],
    clock: Callable[[], datetime],
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run stage 2 only for rows with a validated stage-1 map."""
    if dry_run:
        return {
            "run_id": run_id,
            "dry_run": True,
            "status": "dry_run",
            "selected_rows": len(plan),
            "stage1_model_called_rows": len(plan),
            "stage2_model_called_rows": len(plan),
            "run_dir": None,
        }
    if generate is None:
        raise ValueError("A live two-stage smoke requires generate.")

    run_dir = create_run_directory(output_root, run_id)
    stage1_raw: list[dict[str, Any]] = []
    stage1_records: list[dict[str, Any]] = []
    stage2_raw: list[dict[str, Any]] = []
    stage2_records: list[dict[str, Any]] = []

    for row in plan:
        key = (row["cik"], row["accession"])
        raw = generate(row["stage1_prompt"])
        stage1_raw.append({
            "issuer_name": row["issuer_name"], "cik": key[0], "accession": key[1],
            "raw_response": raw, "raw_response_sha256": _sha256_bytes(raw.encode()),
        })
        common = {
            field: row[field]
            for field in ("issuer_name", "cik", "accession", "packet_sha256")
        } | {"rendered_prompt_sha256": row["stage1_prompt_sha256"]}
        try:
            snapshot = validate_economic_product_capability_output(
                raw, packets_by_key[key], discoveries_by_key[key], product_validator
            )
        except CombinedSnapshotFailure as exc:
            stage1_records.append({
                **common, "record_kind": "review_uncertain", "reason": exc.reason_code,
                "detail": exc.detail, "snapshot": None,
            })
            continue
        first = {**common, "record_kind": "extracted", "reason": None, "detail": None, "snapshot": snapshot}
        stage1_records.append(first)
        candidates = task_candidate_map(snapshot)
        selected_evidence_only = task_prompt_path == TASK_PROMPT_V5
        rendered_task = render_task_prompt(
            task_template,
            packets_by_key[key],
            candidates,
            selected_evidence_only=selected_evidence_only,
        )
        task_raw = generate(rendered_task)
        stage2_raw.append({
            "issuer_name": row["issuer_name"], "cik": key[0], "accession": key[1],
            "raw_response": task_raw, "raw_response_sha256": _sha256_bytes(task_raw.encode()),
        })
        try:
            task_snapshot = validate_task_output(
                task_raw,
                packets_by_key[key],
                candidates,
                task_validator,
                hierarchy=False,
                allowed_refs=(
                    _task_evidence_refs(candidates) if selected_evidence_only else None
                ),
            )
        except CombinedSnapshotFailure as exc:
            stage2_records.append({
                **common, "record_kind": "review_uncertain", "reason": exc.reason_code,
                "detail": exc.detail, "snapshot": None,
            })
        else:
            stage2_records.append({
                **common, "record_kind": "extracted", "reason": None, "detail": None,
                "snapshot": task_snapshot,
            })

    payloads = {
        STAGE1_RAW: "".join(_canonical_line(row) + "\n" for row in stage1_raw).encode(),
        STAGE1_RECORDS: "".join(_canonical_line(row) + "\n" for row in stage1_records).encode(),
        STAGE2_RAW: "".join(_canonical_line(row) + "\n" for row in stage2_raw).encode(),
        STAGE2_RECORDS: "".join(_canonical_line(row) + "\n" for row in stage2_records).encode(),
        HTML: _html(stage1_records, stage2_records, run_id).encode(),
    }
    output_hashes = {name: _sha256_bytes(payload) for name, payload in payloads.items()}
    manifest = {
        "run_kind": RUN_KIND,
        "run_id": run_id,
        "run_timestamp": clock().isoformat(),
        "product_capability_prompt": {"path": product_prompt_path, "sha256": product_prompt_sha256},
        "customer_tasks_prompt": {"path": task_prompt_path, "sha256": task_prompt_sha256},
        "product_capability_schema": PRODUCT_CAPABILITY_SCHEMA,
        "customer_tasks_schema": TASK_SCHEMA,
        "discovery_records_sha256": discovery_records_sha256,
        "model": model,
        "selected_rows": len(plan),
        "stage1_model_called_rows": len(stage1_raw),
        "stage2_model_called_rows": len(stage2_raw),
        "counts": {
            "stage1_extracted": sum(row["record_kind"] == "extracted" for row in stage1_records),
            "stage1_review_uncertain": sum(row["record_kind"] != "extracted" for row in stage1_records),
            "stage2_extracted": sum(row["record_kind"] == "extracted" for row in stage2_records),
            "stage2_review_uncertain": sum(row["record_kind"] != "extracted" for row in stage2_records),
        },
        "output_hashes": output_hashes,
        "limitations": [
            "Development-only five-firm smoke; not a sample or full run.",
            "Stage 2 receives only validated stage-1 maps and cannot revise them.",
            "The run settles no score, tier, transformation depth, or universe membership.",
        ],
    }
    payloads[MANIFEST] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    try:
        for name, payload in payloads.items():
            write_bytes_once(run_dir / name, payload, what=f"two-stage PCT {name}")
    except WriteOnceError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "run_id": run_id, "dry_run": False, "status": "completed", "run_dir": run_dir,
        "manifest": manifest, "stage1_records": stage1_records, "stage2_records": stage2_records,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--discovery-run-dir", required=True)
    parser.add_argument("--vertex-project", required=True)
    parser.add_argument(
        "--product-capability-prompt",
        choices=PRODUCT_CAPABILITY_PROMPTS,
        default=PRODUCT_CAPABILITY_PROMPT,
    )
    parser.add_argument(
        "--task-prompt",
        choices=TASK_PROMPTS,
        default=TASK_PROMPT,
    )
    parser.add_argument("--output-root", default="data/runs/pct-item1-two-stage-smokes")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    product_template = (root / args.product_capability_prompt).read_text()
    task_template = (root / args.task_prompt).read_text()
    discovery_path = Path(args.discovery_run_dir) / "pct_item1_product_structure_records.jsonl"
    discoveries = {
        (row["cik"], row["accession"]): row["snapshot"]
        for row in (json.loads(line) for line in discovery_path.read_text().splitlines())
        if row["record_kind"] == "extracted"
    }
    packets = load_smoke_packets(
        root / "data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819"
        / "universe_baseline_packets.jsonl"
    )
    product_validator = Draft202012Validator(json.loads((root / PRODUCT_CAPABILITY_SCHEMA).read_text()))
    task_validator = Draft202012Validator(json.loads((root / TASK_SCHEMA).read_text()))
    plan = build_two_stage_plan(
        product_capability_template=product_template,
        packets_by_key=packets,
        discoveries_by_key=discoveries,
    )
    result = run_two_stage_smoke(
        plan=plan,
        packets_by_key=packets,
        discoveries_by_key=discoveries,
        task_template=task_template,
        product_validator=product_validator,
        task_validator=task_validator,
        output_root=root / args.output_root,
        run_id=args.run_id,
        product_prompt_path=args.product_capability_prompt,
        product_prompt_sha256=_sha256_bytes(product_template.encode()),
        task_prompt_path=args.task_prompt,
        task_prompt_sha256=_sha256_bytes(task_template.encode()),
        discovery_records_sha256=_sha256_bytes(discovery_path.read_bytes()),
        generate=(build_vertex_generator(vertex_project=args.vertex_project) if args.live else None),
        model={"provider": "google_vertex_ai", "model_label": "gemini-2.5-flash"},
        clock=lambda: datetime.now().astimezone(),
        dry_run=not args.live,
    )
    print(json.dumps({key: result[key] for key in ("run_id", "dry_run", "status", "run_dir")}, default=str, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover
    main()
