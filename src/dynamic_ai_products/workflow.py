"""Shared orchestration helpers for the master research notebook.

The notebook is a literate control plane. All production logic remains in
versioned package modules and pipeline entry-point scripts. This module gives
the notebook safe discovery, validation, execution, logging, and reporting
functions without duplicating stage implementations inside notebook cells.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import yaml

ALLOWED_STAGE_STATUS = {"stub", "sentinel", "ready", "frozen"}


@dataclass(frozen=True)
class CommandResult:
    command: list[str]
    returncode: int | None
    stdout: str
    stderr: str
    executed: bool
    blocked_reason: str | None = None
    started_at: str | None = None
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def find_repo_root(start: str | Path | None = None) -> Path:
    """Find the repository root by locating CLAUDE.md and pyproject.toml."""
    current = Path(start or Path.cwd()).resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / "CLAUDE.md").exists() and (candidate / "pyproject.toml").exists():
            return candidate
    raise FileNotFoundError(
        "Could not locate repository root. Open the notebook from inside the repo "
        "or set REPO_ROOT explicitly."
    )


def load_yaml(path: str | Path) -> dict[str, Any]:
    with Path(path).open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise TypeError(f"Expected mapping in {path}")
    return payload


def load_stage_registry(repo_root: str | Path) -> dict[str, Any]:
    return load_yaml(Path(repo_root) / "configs" / "pipeline_stages.yaml")


def load_notebook_config(repo_root: str | Path) -> dict[str, Any]:
    return load_yaml(Path(repo_root) / "configs" / "master_notebook.yaml")


def validate_stage_registry(repo_root: str | Path, registry: dict[str, Any] | None = None) -> list[dict[str, str]]:
    """Return structured findings; an empty list means the registry is valid."""
    root = Path(repo_root)
    registry = registry or load_stage_registry(root)
    findings: list[dict[str, str]] = []
    stages = registry.get("stages")
    if not isinstance(stages, list) or not stages:
        return [{"severity": "error", "code": "missing_stages", "message": "Registry has no stages."}]

    required = {"id", "name", "phase", "script", "spec", "description", "inputs", "outputs", "gate", "status"}
    seen_ids: set[str] = set()
    for index, stage in enumerate(stages):
        if not isinstance(stage, dict):
            findings.append({"severity": "error", "code": "invalid_stage", "message": f"Stage {index} is not a mapping."})
            continue
        missing = sorted(required - set(stage))
        if missing:
            findings.append({"severity": "error", "code": "missing_fields", "message": f"Stage {index} missing: {', '.join(missing)}"})
            continue
        stage_id = str(stage["id"])
        if stage_id in seen_ids:
            findings.append({"severity": "error", "code": "duplicate_stage_id", "message": f"Duplicate stage ID: {stage_id}"})
        seen_ids.add(stage_id)
        if stage["status"] not in ALLOWED_STAGE_STATUS:
            findings.append({"severity": "error", "code": "invalid_status", "message": f"Stage {stage_id} has invalid status {stage['status']}"})
        for key in ("script", "spec"):
            if not (root / stage[key]).exists():
                findings.append({"severity": "error", "code": f"missing_{key}", "message": f"Stage {stage_id}: missing {stage[key]}"})
    return findings


def registry_dataframe(repo_root: str | Path, registry: dict[str, Any] | None = None) -> pd.DataFrame:
    root = Path(repo_root)
    registry = registry or load_stage_registry(root)
    rows: list[dict[str, Any]] = []
    for stage in registry["stages"]:
        rows.append({
            "stage": stage["id"],
            "phase": stage["phase"],
            "name": stage["name"],
            "status": stage["status"],
            "script": stage["script"],
            "spec": stage["spec"],
            "gate": stage["gate"],
        })
    return pd.DataFrame(rows)


def stage_by_id(registry: dict[str, Any], stage_id: str | int) -> dict[str, Any]:
    normalized = f"{int(stage_id):02d}" if str(stage_id).isdigit() else str(stage_id)
    for stage in registry.get("stages", []):
        if str(stage.get("id")) == normalized:
            return stage
    raise KeyError(f"Unknown pipeline stage: {stage_id}")


def environment_report(repo_root: str | Path) -> dict[str, Any]:
    root = Path(repo_root)
    project = load_yaml(root / "configs" / "project.yaml")
    git_commit = "unknown"
    try:
        git_commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=root, check=True,
            capture_output=True, text=True, timeout=15,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return {
        "repo_root": str(root),
        "python": sys.version.split()[0],
        "executable": sys.executable,
        "platform": sys.platform,
        "git_commit": git_commit,
        "project_name": project.get("project_name"),
        "schema_version": project.get("schema_version"),
        "full_run_enabled": bool(project.get("full_run_enabled", False)),
        "observation_window": project.get("observation_window"),
    }


def run_command(
    command: Iterable[str],
    *,
    repo_root: str | Path,
    execute: bool = False,
    log_dir: str | Path | None = None,
    env: dict[str, str] | None = None,
    timeout: int | None = None,
) -> CommandResult:
    command_list = [str(part) for part in command]
    if not execute:
        return CommandResult(command_list, None, "", "", False, "dry_run")

    start = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(
            command_list,
            cwd=Path(repo_root),
            capture_output=True,
            text=True,
            env={**os.environ, **(env or {})},
            timeout=timeout,
            check=False,
        )
        result = CommandResult(
            command=command_list,
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            executed=True,
            started_at=start.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        result = CommandResult(
            command=command_list,
            returncode=1,
            stdout="",
            stderr=str(exc),
            executed=True,
            started_at=start.isoformat(),
            finished_at=datetime.now(timezone.utc).isoformat(),
        )

    if log_dir is not None:
        directory = Path(log_dir)
        directory.mkdir(parents=True, exist_ok=True)
        safe_name = "_".join(Path(part).name.replace(" ", "_") for part in command_list[:3])[:100]
        (directory / f"{safe_name}.json").write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
    return result


def run_stage(
    stage_id: str | int,
    *,
    repo_root: str | Path,
    registry: dict[str, Any] | None = None,
    execute: bool = False,
    allow_stub_execution: bool = False,
    extra_args: Iterable[str] | None = None,
    log_dir: str | Path | None = None,
) -> CommandResult:
    root = Path(repo_root)
    registry = registry or load_stage_registry(root)
    stage = stage_by_id(registry, stage_id)
    command = [sys.executable, stage["script"], *(list(extra_args or []))]

    if stage["status"] == "stub" and execute and not allow_stub_execution:
        return CommandResult(command, None, "", "", False, "stage_is_stub")
    if stage["id"] in {"13", "14"} and execute:
        project = load_yaml(root / "configs" / "project.yaml")
        if not project.get("full_run_enabled", False):
            return CommandResult(command, None, "", "", False, "full_run_disabled")
    return run_command(command, repo_root=root, execute=execute, log_dir=log_dir)


def create_notebook_run_directory(repo_root: str | Path, label: str = "master-notebook") -> Path:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = Path(repo_root) / "data" / "runs" / f"{timestamp}_{label}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory


def write_run_summary(run_dir: str | Path, payload: dict[str, Any]) -> Path:
    path = Path(run_dir) / "notebook_run_summary.json"
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return path


def main() -> None:
    root = find_repo_root()
    findings = validate_stage_registry(root)
    if findings:
        print(json.dumps(findings, indent=2))
        raise SystemExit(1)
    print(registry_dataframe(root).to_string(index=False))


if __name__ == "__main__":
    main()
