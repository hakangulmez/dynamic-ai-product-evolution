"""Dependency-neutral provenance primitives.

This module is a leaf: it imports the standard library only. It must never
import from ``universe`` or ``ingestion``, and it must never raise a
package-specific error type. Consumers translate :class:`WriteOnceError` into
their own public failure boundary (ADR-031).
"""

from __future__ import annotations

import os
from hashlib import sha256
from pathlib import Path
from typing import Literal

__all__ = [
    "WriteOnceError",
    "file_sha256",
    "write_bytes_once",
]

# Stable, closed category vocabulary. Consumers dispatch on these values.
WriteOnceCategory = Literal["destination_exists", "write_verification_failed"]

# Optional diagnostic detail. Deliberately NOT part of the category vocabulary:
# it exists so a consumer can reconstruct step-specific message text.
WriteOnceStep = Literal["create", "write", "reread", "verify"]


class WriteOnceError(Exception):
    """Neutral write-once failure carrying a stable category.

    ``category`` separates a destination-exists refusal from a write or
    verification failure. ``cleanup_detail`` is populated only when the
    post-failure removal of an owned destination itself failed; it never
    replaces or masks the original error, which stays reachable through
    ``__cause__``.
    """

    def __init__(
        self,
        message: str,
        *,
        category: WriteOnceCategory,
        step: WriteOnceStep | None = None,
        cleanup_detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.category = category
        self.step = step
        self.cleanup_detail = cleanup_detail


def file_sha256(path: str | Path) -> str:
    h = sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _remove_owned(target: Path) -> str | None:
    """Remove a destination this call created. Return cleanup detail on failure."""
    try:
        os.unlink(target)
    except FileNotFoundError:
        return None
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def write_bytes_once(path: str | Path, data: bytes, *, what: str) -> str:
    """Write ``data`` to ``path`` exactly once and return its verified SHA-256.

    Refuses any pre-existing path or symlink. Creates the destination with
    ``O_EXCL``, writes, fsyncs, re-reads, and verifies the digest.

    On failure of create, write, fsync, re-read, or verification this closes
    the descriptor and removes **only** the destination it newly created in
    this call. Ownership is proven by a successful ``O_EXCL`` create: if the
    create failed the path pre-existed, nothing was created, and nothing is
    ever removed.
    """
    target = Path(path)
    if target.is_symlink() or target.exists():
        raise WriteOnceError(
            f"{what} already exists; files are write-once",
            category="destination_exists",
        )
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise WriteOnceError(
            f"{what} already exists; files are write-once",
            category="destination_exists",
        ) from exc
    except OSError as exc:
        # Nothing was created; the destination is not owned and is not removed.
        raise WriteOnceError(
            f"failed to create {what}",
            category="write_verification_failed",
            step="create",
        ) from exc

    # From here the destination is owned by this call.
    expected = sha256(data).hexdigest()
    try:
        try:
            handle = os.fdopen(descriptor, "wb")
        except OSError as exc:
            os.close(descriptor)
            raise WriteOnceError(
                f"failed to write {what}",
                category="write_verification_failed",
                step="write",
            ) from exc
        try:
            with handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as exc:
            raise WriteOnceError(
                f"failed to write {what}",
                category="write_verification_failed",
                step="write",
            ) from exc
        try:
            observed = sha256(target.read_bytes()).hexdigest()
        except OSError as exc:
            raise WriteOnceError(
                f"failed to re-read {what} for verification",
                category="write_verification_failed",
                step="reread",
            ) from exc
        if observed != expected:
            raise WriteOnceError(
                f"persisted {what} re-read to a different hash",
                category="write_verification_failed",
                step="verify",
            )
    except WriteOnceError as error:
        detail = _remove_owned(target)
        if detail is not None:
            error.cleanup_detail = detail
        raise
    return observed
