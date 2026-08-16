"""Stage 00 company-universe entrypoint (local fixtures only).

Governing documents:
- specs/SPEC-001-company-universe.md
- docs/methodology/SOFTWARE_FIRM_UNIVERSE.md
- docs/architecture/COMPANY_UNIVERSE_PIPELINE.md
- docs/THESIS_EXECUTION_PLAN.md
- prompts/implementation/phase_0_company_universe.md

Nine mutually exclusive modes, selected by ``--mode`` (default ``sentinel``
so every pre-existing invocation is unchanged):

- ``sentinel`` runs the fixture-driven sentinel described in
  `docs/implementation/COMPANY_UNIVERSE_SENTINEL_V0.md`. It performs no
  network access and accepts only the deterministic mock provider.
- ``frame`` runs the FRAME builder (SPEC-001 Stage A; W1) over either a local
  fixture bundle (``--index-dir``) or an acquisition manifest
  (``--acquisition-manifest``), verifying every acquired raw-file hash before
  parsing. No network access.
- ``acquire-index`` acquires a declared master.idx request plan through the
  fixture-replay transport (default) or, post-W0, the committed ``sec_live``
  transport (``--transport sec-live``), which performs real SEC requests
  under the recorded user-agent, spacing, retry, and timeout contract and
  writes the v0.2 successor manifest.
- ``dera-validate`` validates a completed FRAME run against local DERA FSDS
  SUB files (ADR-081). Independent validation only: DERA never feeds the
  frame. No network access.
- ``acquire-dera`` acquires declared DERA FSDS release ZIP archives
  (ADR-082) through the fixture-replay transport (default) or the committed
  ``sec_live`` transport, preserves raw ZIPs with receipts, extracts exactly
  one ``sub.txt`` member per archive, and writes a bundle that
  ``dera-validate`` consumes unchanged.
- ``acquire-docs`` acquires the baseline annual-report documents of planned
  baseline candidates (ADR-089) through the fixture-replay transport
  (default) or the committed bounded-streaming ``sec_live`` document
  transport, which enforces the plan's ``max_document_bytes`` while
  downloading. ``sec_filename`` is validated provenance; every URL is
  derived in the SEC filing-directory form. Documents only: no packet, no
  screen, no classification.
- ``probe-filing-index`` probes SEC filing-index pages to prove that they
  are a deterministic, type-bearing metadata source for a later two-hop
  packet route (ADR-090). Metadata only: it acquires no primary document,
  builds no packet, and authorizes nothing downstream.
- ``build-baseline-packets`` builds Stage 00C baseline evidence packets from
  a local, hash-verified primary-document bundle (ADR-091). Fixture-first and
  offline: it performs no network access, decides no exclusion, and records
  cover-page evidence and the economic subsections as explicitly missing.
- ``baseline-carrier`` derives the Stage 00B firm-level baseline carrier
  (W2-A, ADR-088) from a completed FRAME run: hash-verified read-only frame
  consumption, per-stratum CIK grouping, baseline-filing selection against
  the W0-frozen cutoff in ``configs/project.yaml``. No exclusions, no DERA,
  no network access.

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
from datetime import date, datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from dynamic_ai_products.universe.frame import (  # noqa: E402
    FrameInputError,
    FrameReconciliationError,
    run_frame_builder,
)
from dynamic_ai_products.sec_index_transport import (  # noqa: E402
    SEC_LIVE_TRANSPORT_IDENTITY,
    make_sec_live_transport,
)
from dynamic_ai_products.universe.frame_acquisition import (  # noqa: E402
    AcquisitionPlanError,
    make_fixture_replay_transport,
    run_index_acquisition,
)
from dynamic_ai_products.universe.dera_acquisition import (  # noqa: E402
    DeraPlanError,
    make_dera_fixture_replay_transport,
    run_dera_acquisition,
)
from dynamic_ai_products.universe.baseline_carrier import (  # noqa: E402
    CarrierInputError,
    CarrierReconciliationError,
    run_baseline_carrier,
)
from dynamic_ai_products.universe.document_acquisition import (  # noqa: E402
    DocumentPlanError,
    load_document_request_plan,
    make_document_fixture_replay_transport,
    run_document_acquisition,
)
from dynamic_ai_products.sec_document_transport import (  # noqa: E402
    SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY,
    make_sec_live_document_transport,
)
from dynamic_ai_products.ingestion.baseline_packet import (  # noqa: E402
    PacketBundleError,
    run_baseline_packet_build,
)
from dynamic_ai_products.universe.filing_index_probe import (  # noqa: E402
    ProbePlanError,
    load_probe_plan,
    make_filing_index_fixture_replay_transport,
    run_filing_index_probe,
)
from dynamic_ai_products.universe.frame_dera_validation import (  # noqa: E402
    DeraInputError,
    run_dera_validation,
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
        choices=["sentinel", "frame", "acquire-index", "dera-validate",
                 "acquire-dera", "baseline-carrier", "acquire-docs",
                 "probe-filing-index", "build-baseline-packets"],
        help="Stage 00 sub-pipeline to run (default: sentinel).",
    )
    parser.add_argument(
        "--config", default=None,
        help=(
            "Sentinel mode: the versioned sample-rule config "
            "(configs/universe_sample_rules.yaml). Frame mode: the project "
            "config carrying the universe form scopes (configs/project.yaml). "
            "Baseline-carrier mode: the project config carrying the "
            "W0-frozen universe.baseline_cutoff (configs/project.yaml). "
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
        help="Acquire-index, acquire-dera, and acquire-docs modes: path to "
             "the declared request plan — master.idx requests "
             "(evals/fixtures/edgar_index_request_plan), DERA FSDS release "
             "archives, or baseline filing documents "
             "(configs/baseline_doc_canary_request_plan.json).",
    )
    parser.add_argument(
        "--replay-dir", default=None,
        help="Acquire-index, acquire-dera, and acquire-docs modes with the "
             "fixture transport: directory whose local files the "
             "fixture-replay transport serves.",
    )
    parser.add_argument(
        "--transport", default=None, choices=["fixture", "sec-live"],
        help="Acquire-index, acquire-dera, and acquire-docs modes: transport "
             "binding (default: fixture). 'sec-live' performs real SEC "
             "requests under the committed sec_live contract and writes the "
             "v0.2 manifest; acquire-docs uses the bounded streaming "
             "document transport, which enforces the plan's "
             "max_document_bytes while downloading.",
    )
    parser.add_argument(
        "--bundle-dir", default=None,
        help="Build-baseline-packets mode only: directory holding "
             "bundle_manifest.json and the local primary documents it "
             "describes (see evals/fixtures/baseline_packets).",
    )
    parser.add_argument(
        "--frame-manifest", default=None,
        help="Dera-validate and baseline-carrier modes: path to a completed "
             "FRAME run's filer_frame_manifest.json.",
    )
    parser.add_argument(
        "--dera-dir", default=None,
        help="Dera-validate mode only: directory of local DERA FSDS SUB "
             "files plus fixture_manifest.json (see evals/fixtures/dera_fsds).",
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
        ("--transport", args.transport),
    )
    dera_flags = (
        ("--frame-manifest", args.frame_manifest),
        ("--dera-dir", args.dera_dir),
    )
    packet_flags = (("--bundle-dir", args.bundle_dir),)

    if args.mode == "dera-validate":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags
            + (("--config", args.config),)
        )
        if offending:
            return f"dera-validate mode does not accept: {', '.join(offending)}"
        missing = _missing(dera_flags)
        if missing:
            return f"dera-validate mode requires: {', '.join(missing)}"
        return None

    if args.mode == "acquire-docs":
        offending = _present(
            sentinel_flags + frame_flags + dera_flags
            + (("--config", args.config),)
        )
        if offending:
            return f"acquire-docs mode does not accept: {', '.join(offending)}"
        if args.request_plan is None:
            return "acquire-docs mode requires: --request-plan"
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "acquire-docs mode with the fixture transport requires: "
                "--replay-dir"
            )
        if transport_choice == "sec-live" and args.replay_dir is not None:
            return (
                "acquire-docs mode with the sec-live transport does not "
                "accept: --replay-dir"
            )
        return None

    if args.mode == "build-baseline-packets":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags + dera_flags
        )
        if offending:
            return (
                "build-baseline-packets mode does not accept: "
                f"{', '.join(offending)}"
            )
        missing = _missing(
            packet_flags + (("--config", args.config),)
        )
        if missing:
            return f"build-baseline-packets mode requires: {', '.join(missing)}"
        return None

    if args.mode == "probe-filing-index":
        offending = _present(
            sentinel_flags + frame_flags + dera_flags + packet_flags
            + (("--config", args.config),)
        )
        if offending:
            return (
                f"probe-filing-index mode does not accept: {', '.join(offending)}"
            )
        if args.request_plan is None:
            return "probe-filing-index mode requires: --request-plan"
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "probe-filing-index mode with the fixture transport requires: "
                "--replay-dir"
            )
        if transport_choice == "sec-live" and args.replay_dir is not None:
            return (
                "probe-filing-index mode with the sec-live transport does not "
                "accept: --replay-dir"
            )
        return None

    if args.mode == "baseline-carrier":
        offending = _present(
            sentinel_flags + frame_flags + acquire_flags
            + (("--dera-dir", args.dera_dir),)
        )
        if offending:
            return (
                f"baseline-carrier mode does not accept: {', '.join(offending)}"
            )
        missing = _missing(
            (
                ("--frame-manifest", args.frame_manifest),
                ("--config", args.config),
            )
        )
        if missing:
            return f"baseline-carrier mode requires: {', '.join(missing)}"
        return None

    if args.mode == "acquire-dera":
        offending = _present(
            sentinel_flags + frame_flags + dera_flags
            + (("--config", args.config),)
        )
        if offending:
            return f"acquire-dera mode does not accept: {', '.join(offending)}"
        if args.request_plan is None:
            return "acquire-dera mode requires: --request-plan"
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "acquire-dera mode with the fixture transport requires: "
                "--replay-dir"
            )
        if transport_choice == "sec-live" and args.replay_dir is not None:
            return (
                "acquire-dera mode with the sec-live transport does not "
                "accept: --replay-dir"
            )
        return None

    if args.mode == "frame":
        offending = _present(sentinel_flags + acquire_flags + dera_flags)
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
            sentinel_flags + frame_flags + dera_flags
            + (("--config", args.config),)
        )
        if offending:
            return f"acquire-index mode does not accept: {', '.join(offending)}"
        if args.request_plan is None:
            return "acquire-index mode requires: --request-plan"
        transport_choice = args.transport or "fixture"
        if transport_choice == "fixture" and args.replay_dir is None:
            return (
                "acquire-index mode with the fixture transport requires: "
                "--replay-dir"
            )
        if transport_choice == "sec-live" and args.replay_dir is not None:
            return (
                "acquire-index mode with the sec-live transport does not "
                "accept: --replay-dir"
            )
        return None

    offending = _present(frame_flags + acquire_flags + dera_flags)
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
    if not request_plan.is_file():
        print(f"ERROR: request plan not found: {request_plan}", file=sys.stderr)
        return 2
    transport_choice = args.transport or "fixture"
    if transport_choice == "sec-live":
        transport = make_sec_live_transport()
        transport_identity = SEC_LIVE_TRANSPORT_IDENTITY
    else:
        replay_dir = Path(args.replay_dir)
        if not replay_dir.is_dir():
            print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
            return 2
        transport = make_fixture_replay_transport(replay_dir)
        transport_identity = None  # fixture-replay identity, v0.1 manifest
    try:
        result = run_index_acquisition(
            repo_root=REPO_ROOT,
            request_plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            transport=transport,
            dry_run=args.dry_run,
            transport_identity=transport_identity,
        )
    except AcquisitionPlanError as exc:
        print(f"ERROR: invalid request plan: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "transport_kind": (
            transport_identity.kind if transport_identity else "fixture_replay"
        ),
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


def _main_acquire_dera(args: argparse.Namespace) -> int:
    request_plan = Path(args.request_plan)
    if not request_plan.is_file():
        print(f"ERROR: request plan not found: {request_plan}", file=sys.stderr)
        return 2
    transport_choice = args.transport or "fixture"
    if transport_choice == "sec-live":
        transport = make_sec_live_transport()
        transport_identity = SEC_LIVE_TRANSPORT_IDENTITY
    else:
        replay_dir = Path(args.replay_dir)
        if not replay_dir.is_dir():
            print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
            return 2
        transport = make_dera_fixture_replay_transport(replay_dir)
        transport_identity = None  # fixture-replay identity, v0.1 manifest
    try:
        result = run_dera_acquisition(
            repo_root=REPO_ROOT,
            request_plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            transport=transport,
            dry_run=args.dry_run,
            transport_identity=transport_identity,
        )
    except DeraPlanError as exc:
        print(f"ERROR: invalid DERA request plan: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "transport_kind": (
            transport_identity.kind if transport_identity else "fixture_replay"
        ),
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "request_plan_sha256": result.request_plan_sha256,
        "planned_releases": len(result.entries),
        "archives_acquired": len(result.receipts),
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
        "bundle_manifest_path": (
            str(result.bundle_manifest_path)
            if result.bundle_manifest_path
            else None
        ),
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
            "ERROR: DERA acquisition failed; see the failure receipt. No "
            "acquisition manifest was written.",
            file=sys.stderr,
        )
        return 1
    return 0


def _main_dera_validate(args: argparse.Namespace) -> int:
    frame_manifest = Path(args.frame_manifest)
    dera_dir = Path(args.dera_dir)
    if not frame_manifest.is_file():
        print(f"ERROR: frame manifest not found: {frame_manifest}", file=sys.stderr)
        return 2
    if not dera_dir.is_dir():
        print(f"ERROR: DERA input directory not found: {dera_dir}", file=sys.stderr)
        return 2
    try:
        result = run_dera_validation(
            repo_root=REPO_ROOT,
            frame_manifest_path=frame_manifest,
            dera_dir=dera_dir,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            dry_run=args.dry_run,
        )
    except DeraInputError as exc:
        print(f"ERROR: invalid DERA validation input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "gate_status": result.gate_status,
        "failed_conditions": result.failed_conditions,
        "counts": result.counts,
        "noncoverage_by_form": result.noncoverage_by_form,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    if result.gate_status == "fail":
        print(
            "ERROR: DERA validation gate failed; see failed_conditions above.",
            file=sys.stderr,
        )
        return 1
    return 0


def _main_build_baseline_packets(args: argparse.Namespace) -> int:
    bundle_dir = Path(args.bundle_dir)
    config_path = Path(args.config)
    if not bundle_dir.is_dir():
        print(f"ERROR: bundle directory not found: {bundle_dir}", file=sys.stderr)
        return 2
    if not config_path.is_file():
        print(f"ERROR: project config not found: {config_path}", file=sys.stderr)
        return 2
    try:
        result = run_baseline_packet_build(
            repo_root=REPO_ROOT,
            bundle_dir=bundle_dir,
            project_config_path=config_path,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            # The ingestion package never reads the clock; the entrypoint owns
            # identity and injects it.
            clock=lambda: datetime.now(timezone.utc),
            dry_run=args.dry_run,
        )
    except PacketBundleError as exc:
        print(f"ERROR: invalid baseline packet input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "bundle_manifest_sha256": result.bundle_manifest_sha256,
        "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
    return 0


def _main_probe_filing_index(args: argparse.Namespace) -> int:
    request_plan = Path(args.request_plan)
    if not request_plan.is_file():
        print(f"ERROR: probe plan not found: {request_plan}", file=sys.stderr)
        return 2
    # The ceiling is plan-owned, so the plan is read before the transport is
    # built; the runner then refuses any transport bound to a different value.
    try:
        _, plan_fields, _ = load_probe_plan(request_plan)
    except ProbePlanError as exc:
        print(f"ERROR: invalid filing index probe plan: {exc}", file=sys.stderr)
        return 2
    max_metadata_bytes = plan_fields["max_metadata_bytes"]
    transport_choice = args.transport or "fixture"
    if transport_choice == "sec-live":
        transport = make_sec_live_document_transport(max_bytes=max_metadata_bytes)
        transport_identity = SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY
    else:
        replay_dir = Path(args.replay_dir)
        if not replay_dir.is_dir():
            print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
            return 2
        transport = make_filing_index_fixture_replay_transport(
            replay_dir, max_bytes=max_metadata_bytes
        )
        transport_identity = None  # fixture-replay identity, v0.1 manifest
    try:
        result = run_filing_index_probe(
            repo_root=REPO_ROOT,
            plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            transport=transport,
            transport_max_bytes=max_metadata_bytes,
            dry_run=args.dry_run,
            transport_identity=transport_identity,
        )
    except ProbePlanError as exc:
        print(f"ERROR: invalid filing index probe input: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "transport_kind": (
            transport_identity.kind if transport_identity else "fixture_replay"
        ),
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "plan_sha256": result.plan_sha256,
        "max_metadata_bytes": max_metadata_bytes,
        "planned_probes": len(result.entries),
        "probes_resolved": len(result.observations),
        "ground_truth_matches": sum(
            1 for o in result.observations if o.ground_truth_match
        ),
        "selected_documents": [o.selected_document for o in result.observations],
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
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
            "ERROR: filing index probe failed; see the failure receipt. No "
            "probe manifest was written.",
            file=sys.stderr,
        )
        return 1
    return 0


def _main_acquire_docs(args: argparse.Namespace) -> int:
    request_plan = Path(args.request_plan)
    if not request_plan.is_file():
        print(f"ERROR: request plan not found: {request_plan}", file=sys.stderr)
        return 2
    # The ceiling is plan-owned, so the plan is read before the transport is
    # built; the runner then refuses any transport bound to a different value.
    try:
        _, plan_fields, _ = load_document_request_plan(request_plan)
    except DocumentPlanError as exc:
        print(f"ERROR: invalid baseline document request plan: {exc}", file=sys.stderr)
        return 2
    max_document_bytes = plan_fields["max_document_bytes"]
    transport_choice = args.transport or "fixture"
    if transport_choice == "sec-live":
        transport = make_sec_live_document_transport(
            max_bytes=max_document_bytes
        )
        transport_identity = SEC_LIVE_DOCUMENT_TRANSPORT_IDENTITY
    else:
        replay_dir = Path(args.replay_dir)
        if not replay_dir.is_dir():
            print(f"ERROR: replay directory not found: {replay_dir}", file=sys.stderr)
            return 2
        transport = make_document_fixture_replay_transport(
            replay_dir, max_bytes=max_document_bytes
        )
        transport_identity = None  # fixture-replay identity, v0.1 manifest
    try:
        result = run_document_acquisition(
            repo_root=REPO_ROOT,
            request_plan_path=request_plan,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            transport=transport,
            transport_max_bytes=max_document_bytes,
            dry_run=args.dry_run,
            transport_identity=transport_identity,
        )
    except DocumentPlanError as exc:
        print(f"ERROR: invalid baseline document request plan: {exc}", file=sys.stderr)
        return 2
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "transport_kind": (
            transport_identity.kind if transport_identity else "fixture_replay"
        ),
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "request_plan_sha256": result.request_plan_sha256,
        "planned_documents": len(result.entries),
        "documents_acquired": len(result.receipts),
        "mapped_carrier_rows": sum(
            len(entry.carrier_rows) for entry in result.entries
        ),
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
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
            "ERROR: baseline document acquisition failed; see the failure "
            "receipt. No acquisition manifest was written.",
            file=sys.stderr,
        )
        return 1
    return 0


def _main_baseline_carrier(args: argparse.Namespace) -> int:
    frame_manifest = Path(args.frame_manifest)
    config_path = Path(args.config)
    if not frame_manifest.is_file():
        print(f"ERROR: frame manifest not found: {frame_manifest}", file=sys.stderr)
        return 2
    if not config_path.is_file():
        print(f"ERROR: project config not found: {config_path}", file=sys.stderr)
        return 2
    try:
        result = run_baseline_carrier(
            repo_root=REPO_ROOT,
            project_config_path=config_path,
            frame_manifest_path=frame_manifest,
            output_dir=Path(args.output_dir),
            run_id=args.run_id,
            dry_run=args.dry_run,
        )
    except CarrierInputError as exc:
        print(f"ERROR: invalid baseline-carrier input: {exc}", file=sys.stderr)
        return 2
    except CarrierReconciliationError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except FileExistsError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    payload = {
        "run_id": result.run_id,
        "dry_run": result.dry_run,
        "run_dir": str(result.run_dir) if result.run_dir else None,
        "counts": result.counts,
        "reconciliation": result.reconciliation,
        "manifest_path": (
            str(result.manifest_path) if result.manifest_path else None
        ),
    }
    print(json.dumps(payload, indent=2))
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
    if args.mode == "acquire-dera":
        return _main_acquire_dera(args)
    if args.mode == "dera-validate":
        return _main_dera_validate(args)
    if args.mode == "baseline-carrier":
        return _main_baseline_carrier(args)
    if args.mode == "acquire-docs":
        return _main_acquire_docs(args)
    if args.mode == "build-baseline-packets":
        return _main_build_baseline_packets(args)
    if args.mode == "probe-filing-index":
        return _main_probe_filing_index(args)
    return _main_sentinel(args)


if __name__ == "__main__":
    raise SystemExit(main())
