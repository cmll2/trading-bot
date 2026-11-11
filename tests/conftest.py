"""Shared test fixtures.

AD-24 / SAF-10 / SAF-11: an autouse fixture blocks ALL network access for every test, so
no test can ever reach Kraken (public or private endpoints). Loopback is blocked too.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


class NetworkBlocked(RuntimeError):
    """Raised on any attempt to open a network connection during tests.

    A RuntimeError (not OSError) so that libraries which catch OSError and retry cannot
    swallow it.
    """


@pytest.fixture(autouse=True)
def _block_network(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[object]]:
    attempts: list[object] = []

    def _refuse(*args: object, **kwargs: object) -> None:
        attempts.append(args[1:] if args else kwargs)
        raise NetworkBlocked(f"network access is blocked in tests: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket.socket, "sendto", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    monkeypatch.setattr(socket, "getaddrinfo", _refuse)
    yield attempts


@pytest.fixture
def network_attempts(_block_network: list[object]) -> list[object]:
    """Connection attempts recorded by the network block in this test."""
    return _block_network
