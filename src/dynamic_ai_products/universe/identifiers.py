"""CIK, accession, and company identifier normalization.

CIK is the stable firm key (SPEC-001). Ticker is a dated attribute and must
never be used as an identifier.
"""

from __future__ import annotations

import re

#: The only identifier scheme that binds an XBRL context to a CIK. Held here
#: because CIK identity lives in this module and the ingestion package may not
#: name a URL (tests/ingestion/test_ingestion_boundaries.py).
SEC_CIK_IDENTIFIER_SCHEME = "http://www.sec.gov/CIK"

_CIK_RE = re.compile(r"^\d{1,10}$")
_ACCESSION_DIGITS_RE = re.compile(r"^\d{18}$")


class IdentifierError(ValueError):
    """Raised when a CIK or accession number cannot be normalized."""


def normalize_cik(raw: str | int) -> str:
    """Return the canonical zero-padded 10-digit CIK string."""
    text = str(raw).strip().lstrip("0") or "0"
    candidate = str(raw).strip()
    if not _CIK_RE.match(candidate.lstrip("0") or "0") or not candidate.isdigit():
        raise IdentifierError(f"Invalid CIK: {raw!r}")
    if text == "0":
        raise IdentifierError(f"Invalid CIK: {raw!r}")
    return text.zfill(10)


def normalize_accession(raw: str) -> str:
    """Return the canonical dashed accession number NNNNNNNNNN-NN-NNNNNN."""
    digits = re.sub(r"[^0-9]", "", str(raw).strip())
    if not _ACCESSION_DIGITS_RE.match(digits):
        raise IdentifierError(f"Invalid accession number: {raw!r}")
    return f"{digits[:10]}-{digits[10:12]}-{digits[12:]}"


def company_id_for_cik(cik: str | int) -> str:
    """Derive the stable company identifier from a CIK."""
    return f"CIK{normalize_cik(cik)}"
