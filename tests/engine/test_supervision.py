"""Story M3-11: Windows operation - graceful stop, fatal-exit cancel, no listener
(AD-29, NFR-06)."""

from __future__ import annotations

import ast
import signal
from datetime import timedelta
from pathlib import Path

from bot.clock import FakeClock
from bot.runtime import EXIT_FATAL, EXIT_OK, EngineLock, StopFlag, lock_path, run_loop, stop_path
from tests.conftest import REPO_ROOT
from tests.engine.helpers import T0, dry_run


def test_stop_request_mid_tick_finishes_the_tick_commits_and_releases_the_lock(
    tmp_path, monkeypatch
) -> None:
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, _ = dry_run(tmp_path, clock)
    stop = StopFlag(stop_path(dry.db_path))
    real_tick = dry.engine.tick
    calls = {"n": 0}

    def tick_then_signal():  # noqa: ANN202
        calls["n"] += 1
        if calls["n"] == 2:
            stop.set("signal SIGINT")  # CTRL+C arrives as this tick starts running
        return real_tick()  # ... and the tick still runs to completion

    monkeypatch.setattr(dry.engine, "tick", tick_then_signal)
    lock = EngineLock(lock_path(dry.db_path), pid=77)
    result = run_loop(dry, stop, lock=lock, skew=lambda: 0.0)
    assert result.exit_code == EXIT_OK and result.ticks == 2  # the tick in progress finished
    assert not lock_path(dry.db_path).exists()  # lock released
    run = dry.store.one("SELECT stopped_at, stop_reason FROM runs")
    assert run["stopped_at"] is not None and run["stop_reason"] == "graceful stop: signal SIGINT"
    assert dry.store.one("SELECT count(*) FROM orders")[0] == 1  # committed before stopping


def test_stop_file_from_bot_stop_is_honoured(tmp_path) -> None:
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, _ = dry_run(tmp_path, clock)
    stop = StopFlag(stop_path(dry.db_path))

    def sleep_then_request(t):  # noqa: ANN001, ANN202
        FakeClock.sleep_until(clock, t)
        if clock.now() >= T0 + timedelta(minutes=3):
            stop_path(dry.db_path).write_text("stop", encoding="utf-8")

    clock.sleep_until = sleep_then_request  # type: ignore[method-assign]
    result = run_loop(dry, stop, lock=EngineLock(lock_path(dry.db_path), pid=78),
                      skew=lambda: 0.0)  # fmt: skip
    assert result.exit_code == EXIT_OK
    assert "stop file" in result.stop_reason
    assert not lock_path(dry.db_path).exists()


def test_signal_handlers_cover_ctrl_c_and_ctrl_break() -> None:
    stop = StopFlag()
    old = {
        s: signal.getsignal(s) for s in (signal.SIGINT, getattr(signal, "SIGBREAK", signal.SIGINT))
    }
    try:
        stop.install_signal_handlers()
        handler = signal.getsignal(signal.SIGINT)
        handler(signal.SIGINT, None)  # type: ignore[operator]
        assert stop.reason == "signal SIGINT"
        if hasattr(signal, "SIGBREAK"):
            assert signal.getsignal(signal.SIGBREAK) is handler
    finally:
        for s, h in old.items():
            signal.signal(s, h)


def test_fatal_exit_first_cancels_known_resting_orders(tmp_path, monkeypatch) -> None:
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, _ = dry_run(tmp_path, clock)
    real_tick = dry.engine.tick
    calls = {"n": 0}

    def tick_then_die():  # noqa: ANN202
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("unexpected bug")
        return real_tick()

    monkeypatch.setattr(dry.engine, "tick", tick_then_die)
    result = run_loop(dry, StopFlag(), lock=EngineLock(lock_path(dry.db_path), pid=79),
                      skew=lambda: 0.0)  # fmt: skip
    assert result.exit_code == EXIT_FATAL
    states = [r[0] for r in dry.store.all("SELECT state FROM paper_orders")]
    assert states == ["canceled"]  # the resting paper order was cancelled on the way out
    assert dry.store.one("SELECT rule FROM halts")[0] == "fatal_error"
    assert dry.store.one("SELECT stop_reason FROM runs")[0].startswith("fatal: RuntimeError")
    assert not lock_path(dry.db_path).exists()


def test_the_engine_opens_no_listening_socket() -> None:
    """NFR-06: nothing under bot/ binds or listens (only Streamlit, at M4, on 127.0.0.1)."""
    banned_modules = {"http.server", "socketserver", "xmlrpc.server", "asyncio"}
    banned_calls = {"bind", "listen", "serve_forever", "start_server"}
    for path in (REPO_ROOT / "bot").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert not {a.name for a in node.names} & banned_modules, path
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module not in banned_modules, path
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert node.func.attr not in banned_calls, f"{path}: .{node.func.attr}()"


def test_windows_supervision_doc_and_scripts_exist() -> None:
    doc = REPO_ROOT / "docs" / "operations" / "windows-supervision.md"
    text = doc.read_text(encoding="utf-8")
    for needle in ("Task Scheduler", "bot status", "bot stop", "forced restart", "sleep"):
        assert needle in text, needle
    for script in ("register-task.ps1", "start-dry-run.ps1", "stop-dry-run.ps1"):
        assert (REPO_ROOT / "scripts" / script).is_file(), script
    reg = (REPO_ROOT / "scripts" / "register-task.ps1").read_text(encoding="utf-8")
    assert "dry-run" in reg and "--live" not in reg and "plumbing" in reg
    assert (
        Path(REPO_ROOT / "scripts" / "start-dry-run.ps1").read_text(encoding="utf-8").count("var")
        >= 1
    )


def test_loop_ticks_never_land_on_a_candle_boundary() -> None:
    """Review finding (stories 9-11): a window-end tick exactly on a 15m boundary could
    not see the last eligible candle yet (CcxtMarketData settles 10 s) and cancelled the
    order unfilled, unlike the backtest. Ticks are offset past the settle margin."""
    from datetime import UTC, datetime

    from bot.data.live import CLOSE_SETTLE
    from bot.runtime import _next_tick  # noqa: PLC2701

    t = datetime(2026, 11, 14, 0, 0, 0, tzinfo=UTC)
    step = timedelta(seconds=30)
    for _ in range(200):
        t = _next_tick(t, step)
        since_boundary = (t.minute % 15) * 60 + t.second
        assert since_boundary % (15 * 60) >= CLOSE_SETTLE.total_seconds()
        assert t.second in (15, 45)
