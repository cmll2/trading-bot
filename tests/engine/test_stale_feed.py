"""Audit M2 F-5 (story M3-1 note): a resting order is cancelled when OUR feed is stale or
unavailable, and kept only during an exchange halt (synthetic execution candles)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from bot.broker.base import Ticker
from tests.engine.fake_env import FakeEnv


def _stale_ticker(env: FakeEnv, age_s: int) -> None:
    p = env.price
    env.broker.ticker = Ticker(
        "BTC/EUR", p - 1, p + 1, p, env.clock.now() - timedelta(seconds=age_s)
    )


def test_own_stale_ticker_cancels_the_resting_order(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    assert env.orders()[0]["state"] == "open"
    env.clock.advance(timedelta(seconds=30))
    _stale_ticker(env, 200)
    env.engine.tick()
    assert env.orders()[0]["state"] == "cancelled"
    ev = env.risk_events("stale_data")
    assert ev and ev[0]["rule"] == "stale_ticker" and "F-5" in ev[0]["reason"]
    # no re-price while blind: the stale_ticker rule refuses; a fresh ticker resumes
    env.clock.advance(timedelta(seconds=30))
    _stale_ticker(env, 200)
    env.engine.tick()
    assert len(env.orders()) == 1
    env.tick()
    assert [o["state"] for o in env.orders()] == ["cancelled", "open"]


def test_exchange_halt_keeps_the_resting_order(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.md.synthetic_from = env.clock.now() - timedelta(hours=1)  # no trades: halted
    env.clock.advance(timedelta(seconds=30))
    _stale_ticker(env, 600)
    env.engine.tick()
    assert env.orders()[0]["state"] == "open"
    assert env.risk_events("stale_data") == []


def test_unavailable_ticker_cancels_after_the_stale_threshold(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.broker.ticker = None  # every get_ticker now fails
    env.clock.advance(timedelta(seconds=60))
    env.engine.tick()
    assert env.orders()[0]["state"] == "open"  # not yet stale (60 s < 120 s)
    env.clock.advance(timedelta(seconds=90))
    env.engine.tick()
    assert env.orders()[0]["state"] == "cancelled"
    assert Decimal(env.intents()[0]["filled_qty"]) == 0
    assert env.store.one("SELECT count(*) FROM errors WHERE component = 'ticker'")[0] == 2
