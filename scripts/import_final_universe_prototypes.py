#!/usr/bin/env python3
"""Write-once importer for the two historical final-universe prototype outputs."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from dynamic_ai_products.classifier_final_universe_prototype_import import (
    build_final_universe_prototype_import,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict-source-dir", type=Path, required=True)
    parser.add_argument("--centrality-source-dir", type=Path, required=True)
    parser.add_argument("--candidates-path", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--import-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    manifest = build_final_universe_prototype_import(
        repo_root=root,
        strict_source_dir=args.strict_source_dir,
        centrality_source_dir=args.centrality_source_dir,
        candidates_path=args.candidates_path,
        output_root=args.output_root,
        import_id=args.import_id,
        clock=lambda: datetime.now(timezone.utc),
        dry_run=args.dry_run,
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
