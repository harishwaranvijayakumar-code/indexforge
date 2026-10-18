"""Integration tests for the crawler's HTTPX network backend."""

from unittest.mock import MagicMock, patch

import pytest

from documents.crawler_network import (
    PublicAddressBackend,
    create_safe_client,
)


class FakeNetworkStream:
    """In-memory HTTP stream that never opens a real socket."""

    def __init__(self):
        self._response = bytearray(
            b"HTTP/1.1 200 OK\r\n"
            b"Content-Type: text/plain\r\n"
            b"Content-Length: 2\r\n"
            b"Connection: close\r\n"
            b"\r\n"
            b"ok"
        )
        self.written = bytearray()
        self.tls_server_hostname = None
        self.ssl_context = None
        self.ssl_object = MagicMock()
        self.ssl_object.getpeercert.return_value = {}
        self.closed = False

    def read(self, max_bytes, timeout=None):
        data = bytes(self._response[:max_bytes])
        del self._response[:max_bytes]
        return data

    def write(self, buffer, timeout=None):
        self.written.extend(buffer)

    def close(self):
        self.closed = True

    def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.ssl_context = ssl_context
        self.tls_server_hostname = server_hostname
        return self

    def get_extra_info(self, info):
        if info == "ssl_object":
            return self.ssl_object
        return None


def test_httpx_request_uses_validated_ip_through_connection_pool():
    """An actual HTTPX request should connect through the safe backend."""
    stream = FakeNetworkStream()

    with create_safe_client() as client:
        backend = client._transport._pool._network_backend
        assert isinstance(backend, PublicAddressBackend)

        with (
            patch(
                "documents.crawler_network._resolve_public_addresses",
                return_value=["93.184.216.34"],
            ) as resolve,
            patch.object(
                backend._backend,
                "connect_tcp",
                return_value=stream,
            ) as connect,
        ):
            response = client.get("http://example.com/")

        assert response.status_code == 200
        assert response.text == "ok"

        resolve.assert_called_once_with("example.com", 80)
        connect.assert_called_once_with(
            "93.184.216.34",
            80,
            timeout=10.0,
            local_address=None,
            socket_options=None,
        )


def test_https_request_preserves_hostname_for_tls():
    """The TCP destination is pinned while TLS receives the original hostname."""
    stream = FakeNetworkStream()

    with create_safe_client() as client:
        backend = client._transport._pool._network_backend

        with (
            patch(
                "documents.crawler_network._resolve_public_addresses",
                return_value=["93.184.216.34"],
            ) as resolve,
            patch.object(
                backend._backend,
                "connect_tcp",
                return_value=stream,
            ) as connect,
        ):
            response = client.get("https://example.com/")

        assert response.status_code == 200
        assert response.text == "ok"
        resolve.assert_called_once_with("example.com", 443)
        connect.assert_called_once_with(
            "93.184.216.34",
            443,
            timeout=10.0,
            local_address=None,
            socket_options=None,
        )
        assert stream.tls_server_hostname == "example.com"
        assert stream.ssl_context is not None
        assert stream.ssl_context.verify_mode == 2
        assert stream.ssl_context.check_hostname is True


def test_non_public_destination_prevents_connection():
    """A rejected DNS result must never reach the TCP connector."""
    with create_safe_client() as client:
        backend = client._transport._pool._network_backend

        with (
            patch(
                "documents.crawler_network._resolve_public_addresses",
                side_effect=ValueError("Non-public network destinations are blocked."),
            ),
            patch.object(
                backend._backend,
                "connect_tcp",
            ) as connect,
        ):
            with pytest.raises(ValueError, match="Non-public"):
                client.get("http://example.com/")

        connect.assert_not_called()


def test_https_client_keeps_tls_verification_enabled():
    with create_safe_client() as client:
        ssl_context = client._transport._pool._ssl_context
        assert ssl_context.verify_mode == 2
        assert ssl_context.check_hostname is True


def test_safe_client_does_not_follow_redirects():
    with create_safe_client() as client:
        assert client.follow_redirects is False
