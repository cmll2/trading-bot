"""Self-test of the autouse network block (AD-24, SAF-10, SAF-11)."""

from __future__ import annotations

import socket
import urllib.request

import pytest

from tests.conftest import NetworkBlocked


def test_create_connection_is_blocked(network_attempts: list[object]) -> None:
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("api.kraken.com", 443), timeout=1)
    assert network_attempts


def test_raw_socket_connect_is_blocked_even_on_loopback() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        with pytest.raises(NetworkBlocked):
            s.connect(("127.0.0.1", 9))
        with pytest.raises(NetworkBlocked):
            s.connect_ex(("127.0.0.1", 9))


def test_dns_resolution_is_blocked() -> None:
    with pytest.raises(NetworkBlocked):
        socket.getaddrinfo("api.kraken.com", 443)


def test_http_client_cannot_reach_kraken(network_attempts: list[object]) -> None:
    with pytest.raises(NetworkBlocked):
        urllib.request.urlopen("https://api.kraken.com/0/public/Time", timeout=1)  # noqa: S310
    assert network_attempts


def test_block_is_active_without_requesting_any_fixture() -> None:
    # No fixture requested here: the block must still apply (autouse).
    with pytest.raises(NetworkBlocked):
        socket.create_connection(("example.com", 80), timeout=1)
