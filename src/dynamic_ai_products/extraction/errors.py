"""Typed failure boundary for the extraction package (ADR-033).

``WriteOnceError`` is an internal transport from the neutral provenance
primitive. It never escapes this package's public API: every entry point
translates it into :class:`ExtractionError`.
"""

from __future__ import annotations

from ..provenance import WriteOnceError

__all__ = ["ExtractionError", "translate_write_once_error"]


class ExtractionError(Exception):
    """Sanitized extraction failure with a stable machine-readable code."""

    def __init__(
        self,
        message: str,
        *,
        reason_code: str,
        stop_reason: str | None = None,
        detail: str | None = None,
    ) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.stop_reason = stop_reason
        self.detail = detail


def translate_write_once_error(error: WriteOnceError) -> ExtractionError:
    """Map the neutral write-once category onto this package's boundary."""
    if error.category == "destination_exists":
        return ExtractionError(
            str(error), reason_code="destination_exists", detail=error.cleanup_detail
        )
    return ExtractionError(
        str(error), reason_code="write_error", detail=error.cleanup_detail
    )
