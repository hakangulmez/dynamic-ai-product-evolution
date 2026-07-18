"""Small IO helpers for the universe sentinel. No network access."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable


def read_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, payload: Any) -> Path:
    target = Path(path)
    target.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    return target


def write_jsonl(path: str | Path, records: Iterable[Any]) -> Path:
    target = Path(path)
    lines = [json.dumps(record, default=str, sort_keys=True) for record in records]
    target.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return target


def read_jsonl(path: str | Path) -> list[Any]:
    text = Path(path).read_text(encoding="utf-8")
    return [json.loads(line) for line in text.splitlines() if line.strip()]


def append_jsonl(path: str | Path, record: Any) -> Path:
    target = Path(path)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str, sort_keys=True) + "\n")
    return target


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: str | Path) -> str:
    return sha256_bytes(Path(path).read_bytes())


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))
