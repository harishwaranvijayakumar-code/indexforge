"""Network backend that pins HTTP connections to validated public IPs."""

import ipaddress
import socket
from collections.abc import Iterable

import httpx
from httpcore._backends.base import SOCKET_OPTION, NetworkStream
from httpcore._backends.sync import SyncBackend


def _resolve_public_addresses(host: str, port: int) -> list[str]:
    """Resolve a hostname and reject any non-public destination."""
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("IP-literal destinations are not supported.")

    try:
        results = socket.getaddrinfo(
            host,
            port,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise ValueError("Hostname could not be resolved.") from exc

    addresses = sorted({result[4][0] for result in results})
    if not addresses:
        raise ValueError("Hostname did not resolve to an address.")

    for address in addresses:
        if not ipaddress.ip_address(address).is_global:
            raise ValueError("Non-public network destinations are blocked.")

    return addresses


class PublicAddressBackend:
    """Connect to validated IP addresses without another DNS lookup."""

    def __init__(self) -> None:
        self._backend = SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> NetworkStream:
        addresses = _resolve_public_addresses(host, port)
        last_error: OSError | None = None

        for address in addresses:
            try:
                return self._backend.connect_tcp(
                    address,
                    port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except OSError as exc:
                last_error = exc

        if last_error is not None:
            raise last_error
        raise OSError("No validated public addresses were available.")

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[SOCKET_OPTION] | None = None,
    ) -> NetworkStream:
        raise ValueError("Unix sockets are not supported by the web crawler.")

    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)


def create_safe_client(
    user_agent: str = (
        "IndexForgeBot/0.1 (+https://github.com/harishwaranvijayakumar-code/indexforge)"
    ),
) -> httpx.Client:
    """Create an HTTPX client using the public-address backend."""
    transport = httpx.HTTPTransport(
        verify=True,
        trust_env=False,
        retries=0,
    )

    # HTTPX 0.28.1 stores its connection pool on HTTPTransport.
    # Isolate this private-API dependency here and test it explicitly.
    pool = getattr(transport, "_pool", None)
    if pool is None or not hasattr(pool, "_network_backend"):
        transport.close()
        raise RuntimeError("Unsupported HTTPX transport: cannot enforce destination validation.")

    pool._network_backend = PublicAddressBackend()

    return httpx.Client(
        transport=transport,
        headers={"User-Agent": user_agent},
        timeout=10.0,
        follow_redirects=False,
        trust_env=False,
    )
