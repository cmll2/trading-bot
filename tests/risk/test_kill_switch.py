"""Kill-switch file module (FR-36, AD-12, GL-04). PROTECTED (SAF-04)."""

from __future__ import annotations

import ast
import inspect
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest

from bot.risk import kill_switch
from bot.risk.kill_switch import engage, kill_switch_engaged, read_kill_switch

AT = datetime(2026, 11, 14, 12, 30, 5, tzinfo=UTC)


def test_absent_file_is_not_engaged(tmp_path: Path) -> None:
    path = tmp_path / "KILL"
    assert kill_switch_engaged(path) is False
    state = read_kill_switch(path)
    assert state.engaged is False and state.source is None and state.at is None


@pytest.mark.parametrize("source", ["cli", "dashboard", "file"])
def test_engage_creates_the_file_with_one_line(tmp_path: Path, source: str) -> None:
    path = tmp_path / "sub" / "KILL"
    state = engage(path, source, AT)
    assert path.read_text(encoding="utf-8") == f"source={source} at=2026-11-14T12:30:05Z\n"
    assert len(path.read_text(encoding="utf-8").splitlines()) == 1
    assert kill_switch_engaged(path) is True
    assert state.engaged and state.source == source and state.at == "2026-11-14T12:30:05Z"


def test_empty_hand_made_file_counts_as_engaged_with_source_file(tmp_path: Path) -> None:
    path = tmp_path / "KILL"
    path.write_bytes(b"")
    assert kill_switch_engaged(path) is True
    state = read_kill_switch(path)
    assert state.engaged and state.source == "file" and state.at is None


@pytest.mark.parametrize("content", ["stop!", "source=hacker at=x", "\n\n", "garbage=1"])
def test_any_hand_made_content_counts_as_engaged_with_source_file(
    tmp_path: Path, content: str
) -> None:
    path = tmp_path / "KILL"
    path.write_text(content, encoding="utf-8")
    state = read_kill_switch(path)
    assert state.engaged and state.source == "file"


def test_engage_never_overwrites_an_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "KILL"
    engage(path, "dashboard", AT)
    state = engage(path, "cli", AT + timedelta(hours=1))
    assert path.read_text(encoding="utf-8") == "source=dashboard at=2026-11-14T12:30:05Z\n"
    assert state.source == "dashboard"


def test_engage_on_a_hand_made_file_keeps_it(tmp_path: Path) -> None:
    path = tmp_path / "KILL"
    path.write_bytes(b"")
    assert engage(path, "cli", AT).source == "file"
    assert path.read_bytes() == b""


def test_engage_refuses_unknown_source_and_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "KILL"
    with pytest.raises(ValueError):
        engage(path, "engine", AT)
    assert not path.exists()


def test_engage_refuses_naive_or_non_utc_time(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        engage(tmp_path / "A", "cli", datetime(2026, 11, 14, 12, 0))  # noqa: DTZ001
    with pytest.raises(ValueError):
        engage(
            tmp_path / "B",
            "cli",
            datetime(2026, 11, 14, 12, 0, tzinfo=timezone(timedelta(hours=1))),
        )
    assert not (tmp_path / "A").exists() and not (tmp_path / "B").exists()


def test_module_offers_no_way_to_delete_the_file() -> None:
    public = {n for n in dir(kill_switch) if not n.startswith("_")}
    assert not {
        n
        for n in public
        if any(w in n.lower() for w in ("off", "delete", "remove", "disengage", "clear", "unlink"))
    }
    tree = ast.parse(inspect.getsource(kill_switch))
    calls = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert not calls & {"unlink", "remove", "rmdir", "rmtree", "replace", "rename", "truncate"}


def test_module_is_pure_of_clock_store_broker_and_network() -> None:
    tree = ast.parse(inspect.getsource(kill_switch))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    forbidden = (
        "bot.clock",
        "bot.store",
        "bot.broker",
        "bot.engine",
        "bot.data",
        "ccxt",
        "socket",
        "time",
    )
    assert not {m for m in imported if m.startswith(forbidden)}
