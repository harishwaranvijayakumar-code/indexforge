"""Tests for the crawler's public-address network backend."""

import socket
from unittest.mock import MagicMock, patch

import pytest

from documents.crawler_network import (
    PublicAddressBackend,
    _resolve_public_addresses,
)


def dns_result(address):
    family = socket.AF_INET6 if ":" in address else socket.AF_INET
    sockaddr = (address, 443, 0, 0) if family == socket.AF_INET6 else (address, 443)
    return (family, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", sockaddr)


def test_resolver_accepts_public_address():
    with patch(
        "documents.crawler_network.socket.getaddrinfo",
        return_value=[dns_result("1.1.1.1")],
    ):
        assert _resolve_public_addresses("example.com", 443) == ["1.1.1.1"]


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
    ],
)
def test_resolver_rejects_non_public_addresses(address):
    with patch(
        "documents.crawler_network.socket.getaddrinfo",
        return_value=[dns_result(address)],
    ):
        with pytest.raises(ValueError, match="Non-public"):
            _resolve_public_addresses("example.com", 443)


def test_resolver_rejects_mixed_public_and_private_results():
    with patch(
        "documents.crawler_network.socket.getaddrinfo",
        return_value=[dns_result("1.1.1.1"), dns_result("10.0.0.1")],
    ):
        with pytest.raises(ValueError, match="Non-public"):
            _resolve_public_addresses("example.com", 443)


def test_resolver_rejects_ip_literal():
    with pytest.raises(ValueError, match="IP-literal"):
        _resolve_public_addresses("1.1.1.1", 443)


def test_resolver_rejects_dns_failure():
    with patch(
        "documents.crawler_network.socket.getaddrinfo",
        side_effect=socket.gaierror("lookup failed"),
    ):
        with pytest.raises(ValueError, match="could not be resolved"):
            _resolve_public_addresses("example.com", 443)


def test_backend_connects_to_validated_ip_not_hostname():
    backend = PublicAddressBackend()
    expected_stream = MagicMock()

    with (
        patch(
            "documents.crawler_network._resolve_public_addresses",
            return_value=["1.1.1.1"],
        ),
        patch.object(
            backend._backend,
            "connect_tcp",
            return_value=expected_stream,
        ) as connect,
    ):
        stream = backend.connect_tcp("example.com", 443, timeout=5.0)

    assert stream is expected_stream
    connect.assert_called_once_with(
        "1.1.1.1",
        443,
        timeout=5.0,
        local_address=None,
        socket_options=None,
    )


def test_backend_rejects_unix_sockets():
    backend = PublicAddressBackend()

    with pytest.raises(ValueError, match="Unix sockets"):
        backend.connect_unix_socket("/tmp/socket")
