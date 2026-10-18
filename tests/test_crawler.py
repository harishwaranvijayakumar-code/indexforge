"""Safety tests for the IndexForge web crawler."""

import socket
from unittest.mock import patch

import pytest

from documents.management.commands.crawl_site import (
    normalize_url,
    validate_public_host,
)


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "HTTPS://Example.COM/docs/page#section",
            "https://example.com/docs/page",
        ),
        (
            "http://example.com",
            "http://example.com/",
        ),
        (
            "https://example.com/search?q=python#results",
            "https://example.com/search?q=python",
        ),
    ],
)
def test_normalize_url(url, expected):
    assert normalize_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/file",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://user:password@example.com/",
        "https://example.com:8443/",
    ],
)
def test_normalize_url_rejects_unsupported_urls(url):
    with pytest.raises(ValueError):
        normalize_url(url)


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.8",
        "192.168.1.10",
        "169.254.169.254",
        "::1",
        "fc00::1",
    ],
)
def test_validate_public_host_rejects_non_public_addresses(address):
    result = (
        socket.AF_INET6 if ":" in address else socket.AF_INET,
        socket.SOCK_STREAM,
        6,
        "",
        (address, 443 if ":" in address else 80),
    )

    with patch(
        "documents.management.commands.crawl_site.socket.getaddrinfo",
        return_value=[result],
    ):
        with pytest.raises(ValueError, match="non-public"):
            validate_public_host("https://example.com/")


def test_validate_public_host_accepts_public_address():
    result = (
        socket.AF_INET,
        socket.SOCK_STREAM,
        6,
        "",
        ("1.1.1.1", 443),
    )

    with patch(
        "documents.management.commands.crawl_site.socket.getaddrinfo",
        return_value=[result],
    ):
        validate_public_host("https://example.com/")


def test_validate_public_host_rejects_unresolvable_hostname():
    with patch(
        "documents.management.commands.crawl_site.socket.getaddrinfo",
        side_effect=socket.gaierror("name resolution failed"),
    ):
        with pytest.raises(ValueError, match="could not be resolved"):
            validate_public_host("https://example.com/")
