"""canonical_url_v1 and exact-hash duplicate clustering."""

from __future__ import annotations

import pytest

from dynamic_ai_products.collection.canonical_url import (
    CANONICALIZATION_VERSION,
    TRACKING_PARAMETERS,
    canonical_url,
    duplicate_clusters,
)
from dynamic_ai_products.collection.errors import CollectionError


def test_version_is_declared() -> None:
    assert CANONICALIZATION_VERSION == "canonical_url_v1"


def test_scheme_and_host_are_lowercased() -> None:
    assert canonical_url("HTTPS://WWW.HubSpot.COM/Products") == (
        "https://www.hubspot.com/Products"
    )


def test_path_case_is_preserved() -> None:
    assert canonical_url("https://www.hubspot.com/Products/Marketing").endswith(
        "/Products/Marketing"
    )


def test_default_port_is_stripped_and_custom_port_kept() -> None:
    assert canonical_url("https://www.hubspot.com:443/x") == "https://www.hubspot.com/x"
    assert canonical_url("https://www.hubspot.com:8443/x") == (
        "https://www.hubspot.com:8443/x"
    )


def test_fragment_is_dropped() -> None:
    assert canonical_url("https://www.hubspot.com/x#section") == (
        "https://www.hubspot.com/x"
    )


def test_empty_path_becomes_root() -> None:
    assert canonical_url("https://www.hubspot.com") == "https://www.hubspot.com/"


@pytest.mark.parametrize("param", TRACKING_PARAMETERS)
def test_declared_tracking_parameters_are_dropped(param: str) -> None:
    assert canonical_url(f"https://www.hubspot.com/x?{param}=abc") == (
        "https://www.hubspot.com/x"
    )


def test_meaningful_parameters_survive_and_sort() -> None:
    assert canonical_url("https://www.hubspot.com/x?b=2&a=1&utm_source=z") == (
        "https://www.hubspot.com/x?a=1&b=2"
    )


def test_canonicalization_is_idempotent() -> None:
    once = canonical_url("HTTPS://WWW.HubSpot.COM:443/x?utm_source=z&b=2#frag")
    assert canonical_url(once) == once


@pytest.mark.parametrize("url", ["", "   ", "ftp://hubspot.com/x", "https:///nohost"])
def test_malformed_url_is_refused(url: str) -> None:
    with pytest.raises(CollectionError) as excinfo:
        canonical_url(url)
    assert excinfo.value.reason_code == "url_invalid"


# --- Duplicate clustering -----------------------------------------------------


def test_identical_content_hashes_cluster() -> None:
    rows = [
        {"candidate_id": "a", "content_sha256": "a" * 64},
        {"candidate_id": "b", "content_sha256": "a" * 64},
        {"candidate_id": "c", "content_sha256": "b" * 64},
    ]
    clusters = duplicate_clusters(rows)
    assert len(clusters) == 2
    assert len(clusters["a" * 64]) == 2
    assert len(clusters["b" * 64]) == 1


def test_missing_content_hash_is_refused() -> None:
    with pytest.raises(CollectionError) as excinfo:
        duplicate_clusters([{"candidate_id": "a"}])
    assert excinfo.value.reason_code == "content_hash_mismatch"
