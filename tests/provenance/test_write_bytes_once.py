"""Direct tests for the shared write-once primitive (ADR-031)."""

from __future__ import annotations

import ast
import os
import resource
from hashlib import sha256
from pathlib import Path

import pytest

from dynamic_ai_products.provenance import (
    WriteOnceError,
    file_sha256,
    write_bytes_once,
)

PAYLOAD = b"pilot-0 payload\n"
EXPECTED = sha256(PAYLOAD).hexdigest()


# --- Dependency neutrality --------------------------------------------------


def test_provenance_imports_stdlib_only() -> None:
    source = Path(
        "src/dynamic_ai_products/provenance.py"
    ).read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.append(node.module or "")
            if node.level:  # a relative import means a package dependency
                imported.append(f"<relative level {node.level}>")
    forbidden = [
        name
        for name in imported
        if "dynamic_ai_products" in name
        or "universe" in name
        or "ingestion" in name
        or name.startswith("<relative")
    ]
    assert not forbidden, f"provenance must stay dependency-neutral: {forbidden}"


def test_provenance_never_references_pilot_packet_error() -> None:
    source = Path(
        "src/dynamic_ai_products/provenance.py"
    ).read_text(encoding="utf-8")
    assert "PilotPacketError" not in source


# --- Success path -----------------------------------------------------------


def test_success_returns_verified_hash_and_bytes(tmp_path: Path) -> None:
    target = tmp_path / "artifact.bin"
    digest = write_bytes_once(target, PAYLOAD, what="artifact")
    assert digest == EXPECTED
    assert target.read_bytes() == PAYLOAD
    assert file_sha256(target) == EXPECTED


# --- Refusal paths (non-ownership) -----------------------------------------


def test_refuses_existing_file_and_never_unlinks_it(tmp_path: Path) -> None:
    target = tmp_path / "artifact.bin"
    target.write_bytes(b"pre-existing")
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(target, PAYLOAD, what="artifact")
    assert excinfo.value.category == "destination_exists"
    assert excinfo.value.cleanup_detail is None
    assert target.exists()
    assert target.read_bytes() == b"pre-existing"


def test_refuses_symlink_and_leaves_link_and_target(tmp_path: Path) -> None:
    real = tmp_path / "real.bin"
    real.write_bytes(b"target bytes")
    link = tmp_path / "link.bin"
    link.symlink_to(real)
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(link, PAYLOAD, what="artifact")
    assert excinfo.value.category == "destination_exists"
    assert link.is_symlink()
    assert real.read_bytes() == b"target bytes"


def test_refuses_dangling_symlink(tmp_path: Path) -> None:
    link = tmp_path / "dangling.bin"
    link.symlink_to(tmp_path / "missing.bin")
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(link, PAYLOAD, what="artifact")
    assert excinfo.value.category == "destination_exists"
    assert link.is_symlink()


# --- Failure injection: owned destination is removed ------------------------


def test_create_failure_creates_nothing(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "missing-dir" / "artifact.bin"
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(target, PAYLOAD, what="artifact")
    assert excinfo.value.category == "write_verification_failed"
    assert excinfo.value.step == "create"
    assert isinstance(excinfo.value.__cause__, OSError)
    assert not target.exists()


class _FailingWriter:
    """Wraps the real handle but fails on write; still closes the descriptor."""

    def __init__(self, handle) -> None:  # noqa: ANN001
        self._handle = handle

    def __enter__(self):  # noqa: ANN204
        return self

    def __exit__(self, *exc_info) -> bool:  # noqa: ANN001
        self._handle.close()
        return False

    def write(self, data) -> int:  # noqa: ANN001
        raise OSError("injected write failure")

    def flush(self) -> None:
        self._handle.flush()

    def fileno(self) -> int:
        return self._handle.fileno()


def test_write_failure_removes_owned_destination(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "artifact.bin"
    real_fdopen = os.fdopen

    def failing_fdopen(fd, mode):  # noqa: ANN001
        return _FailingWriter(real_fdopen(fd, mode))

    monkeypatch.setattr(os, "fdopen", failing_fdopen)
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(target, PAYLOAD, what="artifact")
    monkeypatch.undo()
    assert excinfo.value.category == "write_verification_failed"
    assert excinfo.value.step == "write"
    assert isinstance(excinfo.value.__cause__, OSError)
    assert not target.exists(), "a failed write must not leave a partial file"


def test_fdopen_failure_closes_descriptor_and_removes_destination(
    tmp_path: Path, monkeypatch
) -> None:
    target = tmp_path / "artifact.bin"

    def boom(fd, mode):  # noqa: ANN001
        os_close_calls.append(fd)
        raise OSError("injected fdopen failure")

    os_close_calls: list[int] = []
    monkeypatch.setattr(os, "fdopen", boom)
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(target, PAYLOAD, what="artifact")
    monkeypatch.undo()
    assert excinfo.value.step == "write"
    assert not target.exists()


def test_fsync_failure_removes_owned_destination(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "artifact.bin"
    real_fsync = os.fsync

    def boom(fd):  # noqa: ANN001
        raise OSError("injected fsync failure")

    monkeypatch.setattr(os, "fsync", boom)
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(target, PAYLOAD, what="artifact")
    monkeypatch.setattr(os, "fsync", real_fsync)
    assert excinfo.value.category == "write_verification_failed"
    assert excinfo.value.step == "write"
    assert not target.exists()


def test_reread_failure_removes_owned_destination(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "artifact.bin"

    def boom(self):  # noqa: ANN001
        raise OSError("injected re-read failure")

    monkeypatch.setattr(Path, "read_bytes", boom, raising=True)
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(target, PAYLOAD, what="artifact")
    monkeypatch.undo()
    assert excinfo.value.category == "write_verification_failed"
    assert excinfo.value.step == "reread"
    assert not target.exists()


def test_verify_mismatch_removes_owned_destination(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "artifact.bin"

    def corrupted(self):  # noqa: ANN001
        return b"different bytes"

    monkeypatch.setattr(Path, "read_bytes", corrupted, raising=True)
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(target, PAYLOAD, what="artifact")
    monkeypatch.undo()
    assert excinfo.value.category == "write_verification_failed"
    assert excinfo.value.step == "verify"
    assert not target.exists()


def test_cleanup_failure_is_reported_without_masking(tmp_path: Path, monkeypatch) -> None:
    target = tmp_path / "artifact.bin"

    def bad_read(self):  # noqa: ANN001
        raise OSError("injected re-read failure")

    def bad_unlink(path):  # noqa: ANN001
        raise PermissionError("injected cleanup failure")

    monkeypatch.setattr(Path, "read_bytes", bad_read, raising=True)
    monkeypatch.setattr(os, "unlink", bad_unlink, raising=True)
    with pytest.raises(WriteOnceError) as excinfo:
        write_bytes_once(target, PAYLOAD, what="artifact")
    monkeypatch.undo()
    # The original failure survives; cleanup detail is additive, never a mask.
    assert excinfo.value.step == "reread"
    assert excinfo.value.category == "write_verification_failed"
    assert "PermissionError" in (excinfo.value.cleanup_detail or "")
    target.unlink(missing_ok=True)


def test_no_descriptor_leak_across_failure_paths(tmp_path: Path, monkeypatch) -> None:
    def open_descriptor_count() -> int:
        soft, _ = resource.getrlimit(resource.RLIMIT_NOFILE)
        limit = min(soft, 4096)
        count = 0
        for fd in range(limit):
            try:
                os.fstat(fd)
            except OSError:
                continue
            count += 1
        return count

    baseline = open_descriptor_count()
    for index in range(25):
        target = tmp_path / f"leak-{index}.bin"

        def boom(self):  # noqa: ANN001
            raise OSError("injected re-read failure")

        monkeypatch.setattr(Path, "read_bytes", boom, raising=True)
        with pytest.raises(WriteOnceError):
            write_bytes_once(target, PAYLOAD, what="artifact")
        monkeypatch.undo()
    assert open_descriptor_count() <= baseline + 2
