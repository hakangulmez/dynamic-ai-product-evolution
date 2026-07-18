from __future__ import annotations
from hashlib import sha256
from pathlib import Path


def file_sha256(path: str | Path) -> str:
    h = sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
