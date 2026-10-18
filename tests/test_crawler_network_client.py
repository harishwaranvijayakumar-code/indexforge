"""Tests for the safe HTTPX client factory."""

import httpx
import pytest

from documents.crawler_network import (
    PublicAddressBackend,
    create_safe_client,
)


def test_safe_client_uses_public_address_backend():
    with create_safe_client() as client:
        assert client.follow_redirects is False
        assert client.trust_env is False
        assert isinstance(
            client._transport._pool._network_backend,
            PublicAddressBackend,
        )


def test_safe_client_verifies_tls():
    with create_safe_client() as client:
        assert client._transport._pool._ssl_context.verify_mode == 2


def test_safe_client_fails_closed_without_pool_backend(monkeypatch):
    original_transport = httpx.HTTPTransport

    class UnsupportedTransport:
        def __init__(self, **kwargs):
            self.closed = False

        def close(self):
            self.closed = True

    monkeypatch.setattr(httpx, "HTTPTransport", UnsupportedTransport)

    with pytest.raises(RuntimeError, match="cannot enforce destination validation"):
        create_safe_client()

    monkeypatch.setattr(httpx, "HTTPTransport", original_transport)
