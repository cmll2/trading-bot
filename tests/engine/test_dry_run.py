"""Story M3-1: dry-run engine ticking on live (fake public) prices with heartbeats and the
journal (FR-11, FR-24, FR-25, FR-38, AD-1, AD-2, AD-17, AD-26). All SIMULATED, no network.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from bot import cli
from bot.clock import FakeClock
from bot.engine import Engine
from bot.runtime import EXIT_OK, EXIT_REFUSED, EngineLock, StartRefused
from bot.store import Store
from tests.engine.helpers import T0, dry_run, make_settings, run
from tests.fakes.ccxt_public import FakePublicKraken


def test_dry_run_uses_the_shared_engine_with_dry_run_adapters(tmp_path, monkeypatch) -> None:
    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("dry-run must never load secrets")

    monkeypatch.setattr("bot.config.load_secrets", _boom)
    dry, _ = dry_run(tmp_path, FakeClock(T0))
    assert type(dry.engine) is Engine
    assert dry.engine.broker.name == "paper"
    assert type(dry.engine.md).__name__ == "CcxtMarketData"
    assert dry.db_path.name == "dry-run-v0_trend.sqlite"
    assert dry.engine.cfg.mode == "dry-run"


def test_one_daily_close_journals_a_signal_and_places_a_paper_order(tmp_path) -> None:
    clock = FakeClock(T0 - timedelta(seconds=5))
    dry, exchange = dry_run(tmp_path, clock)
    result = run(dry, ticks=3)
    assert result.exit_code == EXIT_OK
    st = dry.store
    signals = st.all("SELECT * FROM signals")
    assert len(signals) == 1  # the 2026-11-13 daily candle, closed at 00:00 UTC
    assert signals[0]["candle_open_at"] == "2026-11-13T00:00:00.000Z"
    assert Decimal(signals[0]["target_fraction"]) == 1  # rising price: v0 goes long
    intent = st.one("SELECT * FROM intents")
    assert intent["side"] == "buy" and intent["state"] == "working"
    order = st.one("SELECT * FROM orders")
    assert order["state"] == "open"
    paper = st.one("SELECT * FROM paper_orders")
    assert paper["cl_ord_id"] == order["cl_ord_id"] and paper["state"] == "open"
    # priced at the live (fake public) bid, rounded down to the 0.1 tick
    bid = exchange.price(clock.now()) - 0.5
    assert Decimal(order["limit_price"]) <= Decimal(str(bid))
    # heartbeat on every tick, plus the start and stop markers
    beats = st.all("SELECT loop_state FROM heartbeats")
    assert [b["loop_state"] for b in beats].count("tick") == 3
    assert beats[0]["loop_state"] == "starting"  # "stopped" shares the last tick's time here
    run_row = st.one("SELECT * FROM runs")
    assert run_row["pid"] == 4242 and run_row["mode"] == "dry-run"
    assert run_row["stop_reason"].startswith("graceful stop")
    # public calls recorded for health; the ticker detail keeps the bid/ask (AD-6)
    detail = st.one("SELECT detail_json FROM api_calls WHERE endpoint = 'fetch_ticker'")[0]
    assert '"bid"' in detail and '"ask"' in detail


def test_paper_balance_and_account_baseline_survive_a_restart(tmp_path) -> None:
    clock = FakeClock(T0 - timedelta(seconds=5))
    dry, exchange = dry_run(tmp_path, clock)
    run(dry, ticks=2)
    before = {
        r["asset"]: (r["free"], r["locked"]) for r in dry.store.all("SELECT * FROM paper_balances")
    }
    meta = {k: dry.store.get_meta(k) for k in ("initial_quote", "initial_base", "initial_at")}
    dry.store.close()
    dry2, _ = dry_run(tmp_path, clock, exchange)
    assert {
        r["asset"]: (r["free"], r["locked"]) for r in dry2.store.all("SELECT * FROM paper_balances")
    } == before
    assert {k: dry2.store.get_meta(k) for k in meta} == meta
    assert meta["initial_quote"] == "20"
    run(dry2, ticks=2)
    assert dry2.store.one("SELECT count(*) FROM signals")[0] == 1  # never re-journaled
    assert dry2.store.one("SELECT count(*) FROM runs")[0] == 2


def test_second_engine_on_the_same_store_is_refused(tmp_path) -> None:
    dry, _ = dry_run(tmp_path, FakeClock(T0))
    lock_file = dry.db_path.with_name(dry.db_path.name + ".lock")
    holder = EngineLock(lock_file, pid=111, alive=lambda pid: True)
    holder.acquire()
    other = EngineLock(lock_file, pid=222, alive=lambda pid: True)
    with pytest.raises(StartRefused, match="PID 111"):
        other.acquire()
    from bot.runtime import StopFlag, run_loop

    result = run_loop(dry, StopFlag(), max_ticks=1, lock=other, skew=lambda: 0.0)
    assert result.exit_code == EXIT_REFUSED
    assert dry.store.one("SELECT count(*) FROM runs")[0] == 0
    holder.release()
    assert not lock_file.exists()


def test_stale_lock_of_a_dead_process_is_taken_over(tmp_path) -> None:
    lock_file = tmp_path / "x.sqlite.lock"
    lock_file.write_text("999999", encoding="utf-8")
    lock = EngineLock(lock_file, pid=5, alive=lambda pid: False)
    lock.acquire()
    assert lock_file.read_text(encoding="utf-8") == "5"
    lock.release()


@pytest.mark.parametrize("skew", [5.5, -6.0])
def test_clock_skew_beyond_5_s_refuses_the_start(tmp_path, skew: float) -> None:
    dry, _ = dry_run(tmp_path, FakeClock(T0))
    result = run(dry, ticks=1, skew=skew)
    assert result.exit_code == EXIT_REFUSED
    assert "Kraken server time" in result.stop_reason
    assert dry.store.one("SELECT count(*) FROM runs")[0] == 0


def test_skew_is_measured_against_the_public_server_time(tmp_path) -> None:
    clock = FakeClock(T0)
    exchange = FakePublicKraken(clock, server_offset=timedelta(seconds=7))
    dry, _ = dry_run(tmp_path, clock, exchange)
    assert dry.feed.server_time().skew_seconds == pytest.approx(7.0)


def test_cli_dry_run_then_status_shows_a_fresh_heartbeat(tmp_path, monkeypatch, capsys) -> None:
    settings = make_settings(tmp_path)
    clock = FakeClock(T0 - timedelta(seconds=5))
    exchange = FakePublicKraken(clock)
    monkeypatch.setattr(cli, "_exchange_factory", lambda: exchange)
    monkeypatch.setattr(cli, "_clock_factory", lambda: clock)
    monkeypatch.setattr("bot.runtime.measure_skew", lambda feed: 0.0)
    cfg = ["--config", str(tmp_path / "config.yaml"), "--env-file", str(tmp_path / "none.env")]
    code = cli.main(["dry-run", *cfg, "--approval", "autonomous", "--max-ticks", "2"], env={})
    assert code == cli.EXIT_OK
    capsys.readouterr()
    code = cli.main(["status", *cfg], env={})
    out = capsys.readouterr().out
    assert "DRY-RUN (SIMULATED)" in out
    assert "last heartbeat" in out
    assert code == 1  # the run has stopped: not healthy, but the heartbeat is shown
    assert Store.open_readonly(settings.paths.var_dir / "state" / "dry-run-v0_trend.sqlite")


def test_status_reports_healthy_while_heartbeats_are_fresh(tmp_path) -> None:
    from bot import ops

    clock = FakeClock(T0 - timedelta(seconds=5))
    dry, _ = dry_run(tmp_path, clock)
    dry.engine.start(pid=1)
    dry.engine.heartbeat(clock.now(), "tick")
    st = ops.status(dry.db_path, clock.now() + timedelta(seconds=30), 30, tmp_path / "KILL")
    assert st.healthy
    st = ops.status(dry.db_path, clock.now() + timedelta(seconds=200), 30, tmp_path / "KILL")
    assert not st.healthy
