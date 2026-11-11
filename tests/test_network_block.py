"""Self-test of the autouse network block (AD-24, SAF-10, SAF-11)."""

from __future__ import annotations

import _socket
import re
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


def test_raw_c_socket_connect_is_blocked() -> None:
    # Audit M0 F-4: the low-level _socket module is blocked too.
    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    try:
        with pytest.raises(NetworkBlocked):
            s.connect(("127.0.0.1", 9))
    finally:
        s.close()


def test_no_test_undoes_the_block_or_spawns_processes() -> None:
    # Audit M0 F-4: ``monkeypatch.undo()`` would lift the block, and a subprocess escapes
    # it entirely. No test file may use either (this file is exempt: it names them).
    # Single exception: local, offline ``git`` calls (e.g. ``git check-ignore``), i.e. a
    # ``subprocess.run(`` whose next line starts the argv with "git".
    from tests.conftest import REPO_ROOT

    pattern = re.compile(r"\.undo\(|\bsubprocess\b|os\.system\(|os\.popen\(|\bPopen\b")
    offenders = []
    for path in (REPO_ROOT / "tests").rglob("*.py"):
        if path.name == "test_network_block.py":
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if not pattern.search(line):
                continue
            if line.strip() == "import subprocess":
                continue  # the import alone does nothing; every call is checked below
            nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
            if "subprocess.run(" in line and nxt.startswith('["git"'):
                continue
            offenders.append(f"{path.relative_to(REPO_ROOT)}:{i + 1}")
    assert offenders == []
