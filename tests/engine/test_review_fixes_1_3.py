"""Regression tests for the quick-review findings on M3 stories 1-3 (triage log in the
story 3 plan)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import ccxt

from bot.broker.errors import TransientReadError
from bot.clock import FakeClock
from bot.data.live import CcxtMarketData
from bot.runtime import EXIT_OK, EXIT_REFUSED
from tests.engine.fake_env import FakeEnv
from tests.engine.helpers import T0, dry_run, run
from tests.fakes.ccxt_public import FakePublicKraken

DAY = timedelta(days=1)


def test_forming_candle_is_never_served_as_closed() -> None:
    d = datetime(2026, 11, 13, tzinfo=UTC)
    clock = FakeClock(d + timedelta(hours=10))
    ex = FakePublicKraken(clock)
    md = CcxtMarketData(ex, clock, ("BTC/EUR",))
    assert md.closed_candles("BTC/EUR", "1d").last_open_at == d - DAY
    clock.advance(timedelta(hours=14, seconds=5))  # D+1 00:00:05: D closed, not settled
    assert md.closed_candles("BTC/EUR", "1d").last_open_at == d - DAY
    clock.advance(timedelta(seconds=25))  # D+1 00:00:30
    hist = md.closed_candles("BTC/EUR", "1d")
    assert hist.last_open_at == d
    assert float(hist.close[-1]) == ex.price(d + DAY)  # final close, not the 10:00 value


def test_cancel_lost_in_a_crash_is_re_sent_not_halted(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    order = env.orders()[0]
    env.engine._transition(order["order_id"], "cancel_requested", env.clock.now())  # noqa: SLF001
    env.clock.advance(timedelta(minutes=5))  # crash before the cancel reached the broker
    env.restart()
    for _ in range(3):
        env.tick()
    assert order["cl_ord_id"] in env.broker.cancel_calls
    assert env.orders()[0]["state"] == "cancelled"
    assert env.halts() == []


def test_slow_tick_is_not_mistaken_for_a_future_candle(tmp_path, monkeypatch) -> None:
    env = FakeEnv(tmp_path)
    env.clock.advance(DAY - timedelta(seconds=90))  # 23:59:30 on the next day
    env.refresh_ticker()
    real = env.md.closed_candles
    calls = {"n": 0}

    def slow(pair, tf, limit=None):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            env.clock.advance(timedelta(seconds=60))  # lookups and retries took a minute
        return real(pair, tf, limit)

    monkeypatch.setattr(env.md, "closed_candles", slow)
    env.engine.tick()  # used to raise FutureCandleError (a fatal exit)
    assert len(env.signals()) == 1


def test_reconcile_ingests_unseen_fills_before_comparing(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    order = env.orders()[0]
    qty, price = Decimal(order["qty"]), Decimal(order["limit_price"])
    env.broker.fill(order["cl_ord_id"], qty)  # filled at the broker, not yet ingested
    fee = qty * price * Decimal("0.004")
    env.broker.balances = {
        "EUR": env.broker.balances["EUR"].__class__(
            "EUR", Decimal(20) - qty * price - fee, Decimal(0)
        ),
        "BTC": env.broker.balances["BTC"].__class__("BTC", qty, Decimal(0)),
    }
    env.engine.reconcile(env.clock.now())  # no mismatch
    assert env.halts() == []
    assert env.orders()[0]["state"] == "filled"


def test_network_down_at_startup_refuses_without_a_halt(tmp_path) -> None:
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, ex = dry_run(tmp_path, clock)
    ex.fail("load_markets", ccxt.NetworkError("down"), times=10)
    result = run(dry, ticks=2)
    assert result.exit_code == EXIT_REFUSED
    assert "unreachable" in result.stop_reason
    assert dry.store.one("SELECT count(*) FROM halts")[0] == 0


def test_transient_failure_of_the_hourly_reconcile_is_not_fatal(tmp_path, monkeypatch) -> None:
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, _ = dry_run(tmp_path, clock)
    real = dry.engine.reconcile
    calls = {"n": 0}

    def flaky(now):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 2:
            raise TransientReadError("network blip")
        return real(now)

    monkeypatch.setattr(dry.engine, "reconcile", flaky)
    result = run(dry, ticks=125)
    assert result.exit_code == EXIT_OK
    assert calls["n"] == 3  # startup, failed hourly, retried on the next tick
    assert dry.store.one("SELECT count(*) FROM halts")[0] == 0
    assert dry.store.one("SELECT count(*) FROM errors WHERE component = 'reconcile'")[0] == 1


def test_rate_limited_place_sleeps_and_the_next_tick_retries(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.broker.script_place("rate_limit")
    env.clock.sleep_calls.clear()
    env.tick()
    assert env.orders()[0]["state"] == "rejected"
    assert env.clock.sleep_calls
    env.tick()
    assert [o["state"] for o in env.orders()] == ["rejected", "open"]


def test_the_bid_ask_each_order_was_priced_from_is_recorded(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    row = env.store.one("SELECT detail_json FROM api_calls WHERE endpoint = 'priced_from'")
    detail = json.loads(row[0])
    assert detail["cl_ord_id"] == env.orders()[0]["cl_ord_id"]
    assert Decimal(detail["bid"]) == env.broker.ticker.bid
    assert Decimal(detail["limit"]) == Decimal(env.orders()[0]["limit_price"])
