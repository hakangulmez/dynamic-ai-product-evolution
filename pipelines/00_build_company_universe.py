"""Stage 00 company-universe entrypoint (local fixtures only).

Governing documents:
- specs/SPEC-001-company-universe.md
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md
- docs/architecture/COMPANY_UNIVERSE_PIPELINE.md
- docs/THESIS_EXECUTION_PLAN.md
- prompts/implementation/phase_0_company_universe.md

Three mutually exclusive modes, selected by ``--mode`` (default ``sentinel``
so every pre-existing invocation is unchanged):

- ``sentinel`` runs the fixture-driven sentinel described in
  `docs/implementation/COMPANY_UNIVERSE_SENTINEL_V0.md`. It performs no
  network access and accepts only the deterministic mock provider.
- ``frame`` runs the FRAME builder (SPEC-001 Stage A; W1) over either a local
  fixture bundle (``--index-dir``) or an acquisition manifest
  (``--acquisition-manifest``), verifying every acquired raw-file hash before
  parsing. No network access.
- ``acquire-index`` acquires a declared master.idx request plan through the
  fixture-replay transport. No live SEC transport exists in this increment;
  live EDGAR collection remains gated behind W0.

Examples:
    python pipelines/00_build_company_universe.py \
        --config configs/universe_sample_rules.yaml \
        --input evals/fixtures/universe_sentinel \
        --output-dir data/runs/universe-sentinel \
        --run-id sentinel-demo --seed 42 --provider mock

    python pipelines/00_build_company_universe.py --mode frame \
        --config configs/project.yaml \
        --index-dir evals/fixtures/edgar_full_index \
        --filing-window-start 2022-08-01 --filing-window-end 2023-02-28 \
        --output-dir data/runs/frame-fixture --run-id frame-demo

    python pipelines/00_build_company_universe.py --mode acquire-index \
        --request-plan evals/fixtures/edgar_index_request_plan/request_plan.json \
        --replay-dir evals/fixtures/edgar_full_index \
        --output-dir data/runs/index-acquisition --run-id acquire-demo
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dynamic_ai_products.universe.frame import (  # noqa: E402
    FrameInputError,
    FrameReconciliationError,
    run_frame_builder,
)
from dynamic_ai_products.universe.frame_acquisition import (  # noqa: E402
    AcquisitionPlanError,
    make_fixture_replay_transport,
    run_index_acquisition,
)
from dynamic_ai_products.universe.freeze import FreezeBlockedError  # noqa: E402
from dynamic_ai_products.universe.runner import (  # noqa: E402
    FixtureError,
    run_universe_sentinel,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="00_build_company_universe",
        description=(
            "Run Stage 00 over local fixtures: the company-universe sentinel "
            "(default), the EDGAR full-index FRAME builder, or the "
            "fixture-replay index acquisition."
        ),
    )
    parser.add_argument(
        "--mode", default="sentinel",
        choices=["sentinel", "frame", "acquire-index"],
        help="Stage 00 sub-pipeline to run (default: sentinel).",
    )
    parser.add_argument(
        "--config", default=None,
        help=(
            "Sentinel mode: the versioned sample-rule config "
            "(configs/universe_sample_rules.yaml). Frame mode: the project "
            "config carrying the universe form scopes (configs/project.yaml). "
            "Not accepted in acquire-index mode."
        ),
    )
    parser.add_argument(
        "--input", default=None,
        help="Sentinel mode only: local fixture bundle directory "
             "(see evals/fixtures/universe_sentinel).",
    )
    parser.add_argument(
        "--output-dir", required=True,
        help="Directory under which the immutable run directory <output-dir>/<run-id> is created.",
    )
    parser.add_argument("--run-id", required=True, help="Unique run identifier; never reused.")
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Sentinel mode only: seed for the reproducible stratified "
             "negative-audit sample (default 42).",
    )
    parser.add_argument(
        "--provider", default=None, choices=["mock"],
        help="Sentinel mode only: only the deterministic 'mock' fixture-replay "
             "provider exists in Phase 0.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Validate inputs and compute results without writing any output files.",
    )
    parser.add_argument(
        "--index-dir", default=None,
        help="Frame mode: directory of master.idx fixture files plus "
             "fixture_manifest.json (see evals/fixtures/edgar_full_index). "
             "Mutually exclusive with --acquisition-manifest.",
    )
    parser.add_argument(
        "--filing-window-start", default=None, metavar="YYYY-MM-DD",
        help="Frame mode only: earliest admitted filing date. No default.",
    )
    parser.add_argument(
        "--filing-window-end", default=None, metavar="YYYY-MM-DD",
        help="Frame mode only: latest admitted filing date. No default.",
    )
    parser.add_argument(
        "--acquisition-manifest", default=None,
        help="Frame mode: path to an edgar_index_acquisition_manifest.json; "
             "raw-file hashes are verified before parsing and the frame "
             "version is the code-owned label. Mutually exclusive with "
             "--index-dir.",
    )
    parser.add_argument(
        "--request-plan", default=None,
        help="Acquire-index mode only: path to the declared master.idx "
             "request plan (see evals/fixtures/edgar_index_request_plan).",
    )
    parser.add_argument(
        "--replay-dir", default=None,
        help="Acquire-index mode only: directory whose local files the "
             "fixture-replay transport serves. No live transport exists.",
    )
    return parser


def _present(pairs: tuple[tuple[str, object], ...]) -> list[str]:
    return [name for name, value in pairs if value is not None]


def _missing(pairs: tuple[tuple[str, object], ...]) -> list[str]:
    return [name for name, value in pairs if value is None]


def _reject_cross_mode_flags(args: argparse.Namespace) -> str | None:
    """Return an error message when a flag from another mode is present."""
    sentinel_flags = (
        ("--input", args.input),
        ("--provider", args.provider),
        ("--seed", args.seed),
    )
    frame_flags = (
        ("--index-dir", args.index_dir),
        ("--filing-window-start", args.filing_window_start),
        ("--filing-window-end", args.filing_window_end),
        ("--acquisition-manifest", args.acquisition_manifest),
    )
    acquire_flags = (
        ("--request-plan", args.request_plan),
        ("--replay-dir", args.replay_dir),
    )

    if args.mode == "frame":
        offending = _present(sentinel_flags + acquire_flags)
        if offending:
            return f"frame mode does not accept: {', '.join(offending)}"
        missing = _missing(
            (
                ("--config", args.config),
                ("--filing-window-start", args.filing_window_start),
                ("--filing-window-end", args.filing_window_end),
            )
        )
        if missing:
            return f"frame mode requires: {', '.join(missing)}"
        if (args.index_dir is None) == (args.acquisition_manifest is None):
            return (
                "frame mode requires exactly one of: --index-dir, "
                "--acquisition-manifest"
            )
        return None

    if args.mode == "acquire-index":
        offending = _present(
            sentinel_flags + frame_flags + (("--config", args.config),)
        )
        if offending:
            return f"acquire-index mode does not accept: {', '.join(offending)}"
        missing = _missing(acquire_flags)
        if missing:
            return f"acquire-index mode requires: {', '.join(missing)}"
        return None

    offending = _present(frame_flags + acquire_flags)
    if offending:
        return f"sentinel mode does not accept: {', '.join(offending)}"
    missing = _missing((("--config", args.config), ("--input", args.input)))
    if missing:
        return f"sentinel mode requires: {', '.join(missing)}"
    return None


def _main_sentinel(args: argparse.Namespace) -> int:
    config_path = Path(args.config)
    input_dir = Path(args.input)
    if not config_path.is_file():
        print(f"ERROR: sample-rule config not found: {config_path}", file=sys.stderr)
        return 2
    if not input_dir.is_dir():
        print(f"ERROR: fixture input directory not found: {input_dir}", file=sys.stderr)
        return 2
    try:
        result = run_universe_sentinel(
            repo_root=REPO_ROOT,
            rules_path=config_path,
            input_dir=input_dir,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            seed=42 if args.seed is None else args.seed,
            provider=args.provider or "mock",
            dry_run=args.dry_run,
        )
    except FixtureError as exc:
        print(f"ERROR: invalid fixture bundle or provider: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except FreezeBlockedError as exc:  # defensive: runner reports, never raises this
        print(f"ERROR: freeze blocked: {exc}", file=sys.stderr)
        return 1

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "counts": result.counts,
        "hard_gate_failures": result.hard_gate_failures,
        "freeze_status": result.freeze_status,
        "freeze_blockers": result.freeze_blockers,
        "universe_version": result.universe_version,
    }
    print(json.dumps(payload, indent=2))
    if result.hard_gate_failures:
        print("ERROR: hard gates failed; see hard_gate_failures above.", file=sys.stderr)
        return 1
    return 0


def _main_frame(args: argparse.Namespace) -> int:
    try:
        window_start = date.fromisoformat(args.filing_window_start)
        window_end = date.fromisoformat(args.filing_window_end)
    except ValueError as exc:
        print(f"ERROR: invalid filing-window date: {exc}", file=sys.stderr)
        return 2
    try:
        result = run_frame_builder(
            repo_root=REPO_ROOT,
            project_config_path=Path(args.config),
            index_dir=Path(args.index_dir) if args.index_dir else None,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            filing_window_start=window_start,
            filing_window_end=window_end,
            dry_run=args.dry_run,
            acquisition_manifest_path=(
                Path(args.acquisition_manifest)
                if args.acquisition_manifest
                else None
            ),
        )
    except FrameInputError as exc:
        print(f"ERROR: invalid frame input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except FrameReconciliationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "frame_version": result.frame_version,
        "counts": result.counts,
        "out_of_scope_form_counts": result.out_of_scope_form_counts,
        "reconciliation": result.reconciliation,
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_acquire(args: argparse.Namespace) -> int:
    request_plan = Path(args.request_plan)
    replay_dir = Path(args.replay_dir)
    if not request_plan.is_file():
        print(f"ERROR: request plan not found: {request_plan}", file=sys.stderr)
        return 2
    if not replay_dir.is_dir():
        print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
        return 2
    try:
        result = run_index_acquisition(
            repo_root=REPO_ROOT,
            request_plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            transport=make_fixture_replay_transport(replay_dir),
            dry_run=args.dry_run,
        )
    except AcquisitionPlanError as exc:
        print(f"ERROR: invalid request plan: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "request_plan_sha256": result.request_plan_sha256,
        "planned_entries": len(result.entries),
        "files_acquired": len(result.receipts),
        "manifest_path": str(result.manifest_path) if result.manifest_path else None,
        "failure_reason_code": (
            result.failure.reason_code if result.failure else None
        ),
        "failure_receipt_path": (
            str(result.failure_receipt_path)
            if result.failure_receipt_path
            else None
        ),
    }
    print(json.dumps(payload, indent=2))
    if result.failure is not None:
        print(
            "ERROR: acquisition failed; see the failure receipt. No "
            "acquisition manifest was written.",
            file=sys.stderr,
        )
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    error = _reject_cross_mode_flags(args)
    if error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 2
    if args.mode == "frame":
        return _main_frame(args)
    if args.mode == "acquire-index":
        return _main_acquire(args)
    return _main_sentinel(args)


if __name__ == "__main__":
    raise SystemExit(main())
