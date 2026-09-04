"""Fixed five-firm smoke plan for the compact combined Item 1 PCT prompt.

The plan is deliberately small and does not make a universe claim.  It uses
the exact packet renderer already used by the classifier, so every Item 1
block remains visible under its existing P001-style address.
"""

from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import html
import json
from pathlib import Path
from typing import Any, Callable

from jsonschema import Draft202012Validator

from .classifier_pilot_v1 import render_pilot_prompt
from .human_review_overlay import passage_refs
from .pct_combined_snapshot import (
    CombinedSnapshotFailure,
    OUTPUT_CONTRACT_V4,
    OUTPUT_SCHEMA_V4,
    validate_combined_snapshot_output_v4,
)
from .provenance import WriteOnceError, write_bytes_once
from .providers.client_contract import MODEL_NAME, VERTEX_LOCATION
from .providers.sdk_factory import build_smoke_vertex_client
from .providers.vertex_gemini_v2 import build_generation_projection
from .universe.freeze import create_run_directory

SMOKE_PROMPT_PATH = "prompts/extraction/pct_item1_combined_snapshot_v5.md"
SMOKE_RUN_KIND = "pct_item1_combined_snapshot_smoke_v1"
SMOKE_RECORDS_FILENAME = "pct_item1_combined_snapshot_records.jsonl"
SMOKE_RAW_RESPONSES_FILENAME = "pct_item1_combined_snapshot_raw_responses.jsonl"
SMOKE_MANIFEST_FILENAME = "pct_item1_combined_snapshot_manifest.json"
SMOKE_HTML_FILENAME = "pct_item1_combined_snapshot_human_review.html"

# Five known members of the accepted strict-software universe, selected to
# exercise enterprise SaaS, application software, EDA, and a software-plus-
# appliance boundary.  They are a smoke set, not a sample.
SMOKE_ROWS = (
    ("Adobe", "0000796343", "0000796343-22-000032"),
    ("Salesforce", "0001108524", "0001108524-22-000013"),
    ("Autodesk", "0000769397", "0000769397-22-000019"),
    ("Cadence", "0000813672", "0000813672-22-000012"),
    ("F5", "0001048695", "0001048695-22-000033"),
)


class CombinedSnapshotSmokeError(ValueError):
    """The fixed smoke set cannot be rendered against the supplied packets."""


def build_vertex_generator(
    *, vertex_project: str, vertex_location: str = VERTEX_LOCATION,
    client_factory: Callable[..., Any] | None = None,
) -> Callable[[str], str]:
    """Return the one-operation Vertex callable for this bounded smoke only.

    This is intentionally not the production connector: the smoke makes no
    count-token, budget, tier, or eligibility claim.  It does, however, use the
    repository's fixed Gemini 2.5 Flash generation projection and returns the
    literal response text for archiving.  The vendor SDK is imported only when
    the callable is first used, so a dry run cannot resolve credentials or open
    a network client.
    """
    if not isinstance(vertex_project, str) or not vertex_project:
        raise CombinedSnapshotSmokeError("vertex_project must be non-empty.")
    client: Any = None

    def generate(rendered_prompt: str) -> str:
        nonlocal client
        if client is None:
            if client_factory is None:
                client = build_smoke_vertex_client(
                    vertex_project=vertex_project, vertex_location=vertex_location
                )
            else:
                client = client_factory(
                    vertex_project=vertex_project, vertex_location=vertex_location
                )
        response = client.models.generate_content(
            model=MODEL_NAME, contents=rendered_prompt,
            config=build_generation_projection(),
        )
        text = getattr(response, "text", None)
        if not isinstance(text, str) or not text.strip():
            raise CombinedSnapshotSmokeError(
                "Vertex returned no usable text body for the combined snapshot smoke."
            )
        return text

    return generate


def _canonical_line(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_bytes(value: bytes) -> str:
    return sha256(value).hexdigest()


def load_smoke_packets(packets_jsonl: str | Path) -> dict[tuple[str, str], dict[str, Any]]:
    """Load exactly the five fixed smoke packets from the canonical JSONL.

    The function deliberately does not read any classifier output, human label,
    screen verdict, or universe membership decision.  The firm list is a fixed
    prompt smoke set; the packet is the only model input.
    """
    wanted = {(cik, accession) for _name, cik, accession in SMOKE_ROWS}
    found: dict[tuple[str, str], dict[str, Any]] = {}
    with Path(packets_jsonl).open(encoding="utf-8") as handle:
        for line in handle:
            packet = json.loads(line)
            key = (packet.get("cik"), packet.get("accession"))
            if key in wanted:
                found[key] = packet
    missing = wanted - set(found)
    if missing:
        raise CombinedSnapshotSmokeError(
            f"Canonical packet JSONL lacks smoke keys: {sorted(missing)}."
        )
    return found


def build_smoke_plan(
    *, prompt_text: str, packets_by_key: dict[tuple[str, str], dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return rendered, hashable requests for the five fixed smoke firms.

    No passage selection occurs here.  ``render_pilot_prompt`` displays every
    packet block in natural order, so changing a packet's P001 mapping changes
    the rendered bytes and is visible in the returned digest.
    """
    if not isinstance(prompt_text, str) or not prompt_text.strip():
        raise CombinedSnapshotSmokeError("Prompt text must be non-empty.")
    plan: list[dict[str, Any]] = []
    for issuer_name, cik, accession in SMOKE_ROWS:
        packet = packets_by_key.get((cik, accession))
        if packet is None:
            raise CombinedSnapshotSmokeError(
                f"Smoke packet is unavailable for {issuer_name} ({cik}, {accession})."
            )
        rendered = render_pilot_prompt(prompt_text, packet)
        plan.append(
            {
                "issuer_name": issuer_name,
                "cik": cik,
                "accession": accession,
                "packet_sha256": packet["packet_sha256"],
                "passage_count": len(packet["passages"]),
                "rendered_prompt": rendered,
                "rendered_prompt_sha256": sha256(rendered.encode("utf-8")).hexdigest(),
            }
        )
    return plan


def _resolved_evidence(snapshot: dict[str, Any], packet: dict[str, Any]) -> list[dict[str, Any]]:
    """Materialize the model's P001 addresses without asking it for quote text."""
    refs = passage_refs(packet)
    passages = {entry["passage_id"]: entry for entry in packet["passages"]}
    resolved: dict[str, dict[str, Any]] = {}
    for group in ("product_families", "products", "capabilities", "task_families"):
        for entry in snapshot[group]:
            for reference in entry["passage_refs"]:
                passage = passages[refs[reference]]
                resolved.setdefault(reference, {
                    "passage_ref": reference,
                    "passage_id": passage["passage_id"],
                    "source_id": passage["source_id"],
                    "byte_start": passage["byte_start"],
                    "byte_end": passage["byte_end"],
                    "text_sha256": sha256(passage["text"].encode("utf-8")).hexdigest(),
                    "evidence_text": passage["text"],
                })
    return [resolved[key] for key in sorted(resolved)]


def _human_html(records: list[dict[str, Any]], *, run_id: str, prompt_sha256: str) -> str:
    """Render one self-contained, read-only review page from verified records."""
    def esc(value: object) -> str:
        return html.escape(str(value), quote=True)

    chunks = [
        "<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">",
        "<title>PCT combined snapshot smoke review</title>",
        "<style>body{font:15px/1.45 system-ui;margin:2rem;max-width:1100px}"
        "article{border:1px solid #ddd;border-radius:8px;padding:1rem;margin:1rem 0}"
        "pre{white-space:pre-wrap;background:#f6f6f6;padding:.75rem;border-radius:5px}"
        "code{background:#f2f2f2;padding:.1rem .25rem}summary{cursor:pointer}</style>",
        f"<h1>PCT combined snapshot smoke: {esc(run_id)}</h1>",
        "<p>Development-only five-firm prompt smoke. It does not score, tier, "
        "or settle universe membership. Evidence text below is pipeline-derived "
        "from the model-selected P001 addresses.</p>",
        f"<p>Prompt SHA-256: <code>{esc(prompt_sha256)}</code></p>",
    ]
    for record in records:
        chunks.append(
            f"<article><h2>{esc(record['issuer_name'])} "
            f"(<code>{esc(record['cik'])}</code>)</h2>"
        )
        if record["record_kind"] == "review_uncertain":
            chunks.append(
                f"<p><strong>Needs review:</strong> {esc(record['review_reason_code'])}</p>"
                f"<pre>{esc(record['review_detail'])}</pre></article>"
            )
            continue
        snapshot = record["snapshot"]
        for label, heading in (
            ("product_families", "Product families"),
            ("products", "Products"),
            ("capabilities", "Capabilities"),
            ("task_families", "Task families"),
        ):
            chunks.append(f"<h3>{esc(heading)}</h3><ul>")
            for entry in snapshot[label]:
                text = entry.get("name", entry.get("text", ""))
                chunks.append(
                    f"<li><code>{esc(entry['id'])}</code> {esc(text)} "
                    f"— {esc(', '.join(entry['passage_refs']))}</li>"
                )
            chunks.append("</ul>")
        chunks.append("<h3>Resolved evidence blocks</h3>")
        for evidence in record["resolved_evidence"]:
            chunks.append(
                f"<details><summary><code>{esc(evidence['passage_ref'])}</code> "
                f"({esc(evidence['passage_id'])})</summary><pre>"
                f"{esc(evidence['evidence_text'])}</pre></details>"
            )
        chunks.append("</article>")
    return "\n".join(chunks) + "\n"


def run_smoke_plan(
    *, plan: list[dict[str, Any]], packets_by_key: dict[tuple[str, str], dict[str, Any]],
    output_root: str | Path, run_id: str, prompt_sha256: str, schema_sha256: str,
    generate: Callable[[str], str] | None, model: dict[str, Any],
    clock: Callable[[], datetime], dry_run: bool = False,
) -> dict[str, Any]:
    """Run the fixed smoke set through an injected model call and archive it.

    A dry run renders all five exact requests but invokes neither ``generate``
    nor the filesystem writer.  A live call is deliberately all-or-nothing at
    the run level only for provider failures: a readable but invalid model
    response is retained as ``review_uncertain`` so the human review page can
    distinguish a format failure from an absent experiment.
    """
    if len(plan) != len(SMOKE_ROWS):
        raise CombinedSnapshotSmokeError("The smoke plan must contain exactly five rows.")
    if dry_run:
        return {
            "run_id": run_id, "dry_run": True, "status": "dry_run",
            "selected_rows": len(plan), "model_called_rows": len(plan),
            "run_dir": None,
        }
    if generate is None:
        raise CombinedSnapshotSmokeError("A live smoke run requires a model generate callable.")
    run_dir = create_run_directory(output_root, run_id)
    validator = Draft202012Validator(json.loads(
        (Path(__file__).resolve().parents[2] / OUTPUT_SCHEMA_V4).read_text(
            encoding="utf-8"
        )
    ))
    records: list[dict[str, Any]] = []
    raw_entries: list[dict[str, Any]] = []
    for row in plan:
        packet = packets_by_key[(row["cik"], row["accession"])]
        try:
            raw = generate(row["rendered_prompt"])
        except Exception as exc:  # provider failures are not substantive findings
            raise CombinedSnapshotSmokeError(
                f"Provider call stopped at {row['issuer_name']}: {type(exc).__name__}: {exc}"
            ) from exc
        raw_entries.append({
            "issuer_name": row["issuer_name"], "cik": row["cik"],
            "accession": row["accession"], "raw_response": raw,
            "raw_response_sha256": _sha256_bytes(raw.encode("utf-8")),
        })
        common = {
            "issuer_name": row["issuer_name"], "cik": row["cik"],
            "accession": row["accession"], "packet_sha256": row["packet_sha256"],
            "rendered_prompt_sha256": row["rendered_prompt_sha256"],
        }
        try:
            snapshot = validate_combined_snapshot_output_v4(raw, packet, validator)
        except CombinedSnapshotFailure as exc:
            records.append({
                **common, "record_kind": "review_uncertain",
                "review_reason_code": exc.reason_code, "review_detail": exc.detail,
                "snapshot": None, "resolved_evidence": [],
            })
        else:
            records.append({
                **common, "record_kind": "extracted", "review_reason_code": None,
                "review_detail": None, "snapshot": snapshot,
                "resolved_evidence": _resolved_evidence(snapshot, packet),
            })

    raw_bytes = ("".join(_canonical_line(entry) + "\n" for entry in raw_entries)
                 .encode("utf-8"))
    records_bytes = ("".join(_canonical_line(entry) + "\n" for entry in records)
                     .encode("utf-8"))
    html_bytes = _human_html(records, run_id=run_id, prompt_sha256=prompt_sha256).encode("utf-8")
    hashes = {
        SMOKE_RAW_RESPONSES_FILENAME: _sha256_bytes(raw_bytes),
        SMOKE_RECORDS_FILENAME: _sha256_bytes(records_bytes),
        SMOKE_HTML_FILENAME: _sha256_bytes(html_bytes),
    }
    manifest = {
        "run_kind": SMOKE_RUN_KIND, "run_id": run_id,
        "run_timestamp": clock().isoformat(), "prompt_template_path": SMOKE_PROMPT_PATH,
        "prompt_template_sha256": prompt_sha256,
        "output_contract": OUTPUT_CONTRACT_V4,
        "output_schema_sha256": schema_sha256, "model": model,
        "selected_rows": len(plan), "model_called_rows": len(plan),
        "counts": {
            "extracted": sum(r["record_kind"] == "extracted" for r in records),
            "review_uncertain": sum(r["record_kind"] == "review_uncertain" for r in records),
        },
        "rows": [{key: row[key] for key in ("issuer_name", "cik", "accession", "packet_sha256")}
                 for row in plan],
        "output_hashes": hashes,
        "limitations": [
            "Development-only five-firm smoke; it is not a sample or full run.",
            "The run settles no product ontology, score, tier, universe membership, or thesis result.",
            "Model-selected P001 references are validated against the complete packet rendered to the model.",
        ],
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        for filename, payload, what in (
            (SMOKE_RAW_RESPONSES_FILENAME, raw_bytes, "combined snapshot raw responses"),
            (SMOKE_RECORDS_FILENAME, records_bytes, "combined snapshot records"),
            (SMOKE_HTML_FILENAME, html_bytes, "combined snapshot human review"),
            (SMOKE_MANIFEST_FILENAME, manifest_bytes, "combined snapshot manifest"),
        ):
            write_bytes_once(run_dir / filename, payload, what=what)
    except WriteOnceError as exc:
        raise CombinedSnapshotSmokeError(str(exc)) from exc
    return {"run_id": run_id, "dry_run": False, "status": "completed", "run_dir": run_dir,
            "manifest": manifest, "records": records}


def main() -> None:
    """Run the fixed smoke route from the command line.

    ``--live`` is deliberately explicit.  Without it, the command renders the
    five prompts and proves the input plan without resolving credentials,
    constructing a client, or creating a run directory.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--vertex-project", required=True)
    parser.add_argument("--output-root", default="data/runs/pct-item1-combined-snapshot-smokes")
    parser.add_argument("--live", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    prompt = (root / SMOKE_PROMPT_PATH).read_text(encoding="utf-8")
    schema_path = root / OUTPUT_SCHEMA_V4
    packets = load_smoke_packets(
        root / "data/runs/baseline-packets/baseline-packets-domestic-text-lineage-v5-20260819"
        / "universe_baseline_packets.jsonl"
    )
    plan = build_smoke_plan(prompt_text=prompt, packets_by_key=packets)
    result = run_smoke_plan(
        plan=plan, packets_by_key=packets,
        output_root=root / args.output_root, run_id=args.run_id,
        prompt_sha256=_sha256_bytes(prompt.encode("utf-8")),
        schema_sha256=_sha256_bytes(schema_path.read_bytes()),
        generate=(build_vertex_generator(vertex_project=args.vertex_project)
                  if args.live else None),
        model={
            "provider": "google_vertex_ai", "model_label": MODEL_NAME,
            "parameters": build_generation_projection(),
        },
        clock=lambda: datetime.now().astimezone(), dry_run=not args.live,
    )
    summary = {key: result[key] for key in ("run_id", "dry_run", "status", "run_dir")}
    if not result["dry_run"]:
        summary["counts"] = result["manifest"]["counts"]
    print(json.dumps(summary, default=str, sort_keys=True))


if __name__ == "__main__":  # pragma: no cover - CLI is exercised by smoke run
    main()
