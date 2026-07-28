"""SEC-derived apex trust boundary and origin admission."""

from __future__ import annotations

from pathlib import Path

import pytest

from dynamic_ai_products.collection.domains import (
    OFFICIAL_APEX,
    SEC_DERIVATION_PINS,
    derive_official_apex,
    host_of,
    is_official_origin,
    require_official_origin,
    split_url,
)
from dynamic_ai_products.collection.errors import CollectionError

RAW = Path("data/raw/sec/CIK0001404655/0000950170-25-018873")
INPUTS = ("submissions", "filing_index", "primary_document")
_FILES = {
    "submissions": "submissions.json",
    "filing_index": "filing-index.json",
    "primary_document": "hubs-20241231.htm",
}


def _real_bytes() -> dict[str, bytes]:
    """The committed SEC bytes, read only. Skips if the raw corpus is absent."""
    if not all((RAW / name).is_file() for name in _FILES.values()):
        pytest.skip("committed Pilot 0 raw SEC corpus not present")
    return {key: (RAW / name).read_bytes() for key, name in _FILES.items()}


def _kwargs(payloads: dict[str, bytes], **overrides):
    kwargs = {
        "submissions_bytes": payloads["submissions"],
        "submissions_sha256": SEC_DERIVATION_PINS["submissions"],
        "filing_index_bytes": payloads["filing_index"],
        "filing_index_sha256": SEC_DERIVATION_PINS["filing_index"],
        "primary_document_bytes": payloads["primary_document"],
        "primary_document_sha256": SEC_DERIVATION_PINS["primary_document"],
    }
    kwargs.update(overrides)
    return kwargs


def test_apex_is_hubspot_com() -> None:
    assert OFFICIAL_APEX == "hubspot.com"


def test_apex_derivation_binds_all_three_raw_inputs() -> None:
    payloads = _real_bytes()
    assert derive_official_apex(**_kwargs(payloads)) == "hubspot.com"


@pytest.mark.parametrize("name", INPUTS)
def test_tampered_raw_input_is_refused(name: str) -> None:
    """Each raw input is independently hash-verified."""
    payloads = _real_bytes()
    payloads[name] = payloads[name] + b"tamper"
    with pytest.raises(CollectionError) as excinfo:
        derive_official_apex(**_kwargs(payloads))
    assert excinfo.value.reason_code == "apex_derivation_failed"
    assert name in str(excinfo.value)


@pytest.mark.parametrize("name", INPUTS)
def test_tampered_pin_is_refused(name: str) -> None:
    """Each supplied pin is independently checked against the bytes."""
    payloads = _real_bytes()
    with pytest.raises(CollectionError) as excinfo:
        derive_official_apex(**_kwargs(payloads, **{f"{name}_sha256": "f" * 64}))
    assert excinfo.value.reason_code == "apex_derivation_failed"
    assert name in str(excinfo.value)


@pytest.mark.parametrize("name", INPUTS)
def test_self_consistent_but_non_pilot_input_is_refused(name: str) -> None:
    """Bytes whose hash matches its own pin but is not the committed pin."""
    from hashlib import sha256

    payloads = _real_bytes()
    forged = b"<html>www.hubspot.com forged</html>"
    payloads[name] = forged
    with pytest.raises(CollectionError) as excinfo:
        derive_official_apex(
            **_kwargs(payloads, **{f"{name}_sha256": sha256(forged).hexdigest()})
        )
    assert excinfo.value.reason_code == "apex_derivation_failed"
    assert "committed Pilot 0 pin" in str(excinfo.value)


@pytest.mark.parametrize("name", INPUTS)
def test_non_bytes_input_is_refused(name: str) -> None:
    payloads = _real_bytes()
    payloads[name] = "not bytes"  # type: ignore[assignment]
    with pytest.raises(CollectionError) as excinfo:
        derive_official_apex(**_kwargs(payloads))
    assert excinfo.value.reason_code == "apex_derivation_failed"


# --- Strict-subdomain admission ----------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://hubspot.com/",
        "https://www.hubspot.com/products",
        "https://ir.hubspot.com/financials",
        "https://developers.hubspot.com/docs/api",
        "https://blog.hubspot.com/marketing",
        "https://deeply.nested.sub.hubspot.com/x",
    ],
)
def test_apex_and_strict_subdomains_are_official(url: str) -> None:
    """Subdomains need not appear literally in the SEC bytes."""
    assert is_official_origin(url)
    assert require_official_origin(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "https://hubspot.com.evil.example/",
        "https://nothubspot.com/",
        "https://xhubspot.com/",
        "https://web.archive.example/web/2025/https://www.hubspot.com/x",
        "https://example.com/hubspot.com",
    ],
)
def test_lookalike_and_third_party_hosts_are_not_official(url: str) -> None:
    assert not is_official_origin(url)
    with pytest.raises(CollectionError) as excinfo:
        require_official_origin(url)
    assert excinfo.value.reason_code == "third_party_domain_excluded"


def test_host_is_lowercased_and_port_stripped() -> None:
    assert host_of("https://WWW.HubSpot.COM:443/x") == "www.hubspot.com"


@pytest.mark.parametrize(
    "url", ["ftp://hubspot.com/x", "file:///etc/passwd", "", "not-a-url"]
)
def test_unsupported_or_malformed_url_is_refused(url: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        host_of(url)
    assert excinfo.value.reason_code == "url_invalid"


def test_derivation_pins_are_the_committed_sec_hashes() -> None:
    assert SEC_DERIVATION_PINS == {
        "submissions": (
            "6d2add25a7753cefa486d224c862f15b7b81a28707562a73848983587fdb8b19"
        ),
        "filing_index": (
            "c6876565db97200958b4b30f2fcfe9da214d86836643f84d30fcb1fd93699880"
        ),
        "primary_document": (
            "36257e638feb2059e3bbc58461938d6ffc11dd280e12d7af0f06c5394bf40b12"
        ),
    }


# --- Sanitized malformed-URL errors ------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "https://user:pass@www.hubspot.com/x",
        "https://user@www.hubspot.com/x",
    ],
)
def test_credentials_are_refused_without_leaking_valueerror(url: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        host_of(url)
    assert excinfo.value.reason_code == "url_invalid"
    assert "credentials" in str(excinfo.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://www.hubspot.com:notaport/x",
        "https://www.hubspot.com:99999999999/x",
        "https://www.hubspot.com:-1/x",
    ],
)
def test_invalid_port_is_refused_without_leaking_valueerror(url: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        host_of(url)
    assert excinfo.value.reason_code == "url_invalid"


def test_split_url_never_raises_valueerror() -> None:
    for url in (
        "https://www.hubspot.com:bad/x",
        "https://u:p@www.hubspot.com/x",
        "://nohost",
        "   ",
    ):
        with pytest.raises(CollectionError):
            split_url(url)
