"""Story M3-3: reconciliation at startup and hourly halts on mismatch (FR-29, FR-37,
AD-9, AD-29)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from bot.broker.base import Balance, Fill, OrderRequest
from bot.clock import FakeClock
from bot.engine import ReconcileMismatch
from bot.runtime import CHECK_EVERY, EXIT_FATAL, EXIT_OK
from tests.engine.fake_env import FakeEnv
from tests.engine.helpers import T0, dry_run, run
from tests.fakes.broker import approve


def _env_with_open_order(tmp_path) -> FakeEnv:  # noqa: ANN001
    env = FakeEnv(tmp_path)
    env.tick()
    env.sync_balances()
    env.engine.reconcile(env.clock.now())  # consistent: no exception
    return env


def _assert_mismatch(env: FakeEnv, fragment: str) -> None:
    with pytest.raises(ReconcileMismatch, match=fragment):
        env.engine.reconcile(env.clock.now())
    assert "reconcile_mismatch" in env.halts()
    events = env.risk_events("reconcile_mismatch")
    assert events and any(fragment in e["reason"] for e in events)
    # own resting orders cancelled, best effort
    assert env.broker.cancel_calls
    assert env.orders()[0]["state"] == "cancel_requested"


def test_consistent_state_passes(tmp_path) -> None:
    env = _env_with_open_order(tmp_path)
    assert env.halts() == []
    assert env.risk_events("reconcile_mismatch") == []


def test_foreign_open_order_halts(tmp_path) -> None:
    env = _env_with_open_order(tmp_path)
    req = OrderRequest("BTC/EUR", "buy", Decimal("0.0001"), Decimal("39000"), "not-ours")
    env.broker.place_order(req, approve(req))
    _assert_mismatch(env, "unknown to the store")


def test_base_balance_off_by_one_step_halts(tmp_path) -> None:
    env = _env_with_open_order(tmp_path)
    env.broker.balances["BTC"] = Balance("BTC", Decimal("0.00000001"), Decimal(0))
    _assert_mismatch(env, "base balance differs")


def test_quote_balance_below_derived_cash_halts(tmp_path) -> None:
    env = _env_with_open_order(tmp_path)
    env.broker.balances["EUR"] = Balance("EUR", Decimal("19.99"), Decimal(0))
    _assert_mismatch(env, "quote balance below")


def test_quote_balance_above_derived_cash_is_allowed(tmp_path) -> None:
    env = _env_with_open_order(tmp_path)
    env.broker.balances["EUR"] = Balance("EUR", Decimal("25"), Decimal(0))  # A-1
    env.engine.reconcile(env.clock.now())
    assert env.halts() == []


def test_unmatched_fill_halts(tmp_path) -> None:
    env = _env_with_open_order(tmp_path)
    env.broker.inject_fill(
        Fill("T999", "O999", "ghost", "BTC/EUR", "buy", Decimal("0.0001"), Decimal("40000"),
             Decimal("0.016"), "EUR", "maker", env.clock.now())
    )  # fmt: skip
    _assert_mismatch(env, "matches no store fill")


def test_store_order_missing_at_the_broker_halts(tmp_path) -> None:
    env = _env_with_open_order(tmp_path)
    env.broker._orders.clear()  # noqa: SLF001 - the exchange lost the order
    with pytest.raises(ReconcileMismatch, match="not open at the broker"):
        env.engine.reconcile(env.clock.now())
    assert "reconcile_mismatch" in env.halts()


def test_tampered_paper_fill_halts_the_dry_run_at_startup(tmp_path) -> None:
    """Auditor check from the story: edit a paper_fills row and see the halt."""
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, exchange = dry_run(tmp_path, clock)
    exchange.candle_range = 500.0  # wide 15m candles: the resting buy fills
    assert run(dry, ticks=70).exit_code == EXIT_OK  # the 00:15 candle settles at 00:30:10
    assert dry.store.one("SELECT count(*) FROM fills")[0] == 1
    dry.store.execute("UPDATE paper_fills SET qty = qty || '1'")  # the broker's side differs
    dry.store.execute("UPDATE paper_balances SET free = '1' WHERE asset = 'BTC'")
    dry.store.close()
    dry2, _ = dry_run(tmp_path, clock, exchange)
    result = run(dry2, ticks=1)
    assert result.exit_code == EXIT_FATAL
    assert "reconcile mismatch" in result.stop_reason
    halts = dry2.store.all("SELECT rule FROM halts WHERE reset_at IS NULL")
    assert [h["rule"] for h in halts] == ["reconcile_mismatch"]
    assert dry2.store.one("SELECT stop_reason FROM runs ORDER BY run_id DESC")[0].startswith(
        "reconcile mismatch"
    )


def test_reconciliation_runs_hourly_and_after_a_sleep_gap(tmp_path, monkeypatch) -> None:
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, _ = dry_run(tmp_path, clock)
    calls: list[object] = []

    def spy_on(engine):  # noqa: ANN001, ANN202
        real = engine.reconcile

        def spy(now):  # noqa: ANN001, ANN202
            calls.append(now)
            return real(now)

        monkeypatch.setattr(engine, "reconcile", spy)

    spy_on(dry.engine)
    ticks = int(CHECK_EVERY / dry.tick) + 2
    assert run(dry, ticks=ticks).exit_code == EXIT_OK
    assert len(calls) == 2  # startup + one hourly

    # a sleep gap (> 10 min between ticks) re-runs reconciliation at once
    calls.clear()
    from bot import runtime

    real_sleep = runtime._sleep_until  # noqa: SLF001
    state = {"n": 0}

    def sleepy(clk, t, stop):  # noqa: ANN001, ANN202
        state["n"] += 1
        if state["n"] == 3:
            clk.advance(timedelta(minutes=15))  # the PC slept
        return real_sleep(clk, t, stop)

    monkeypatch.setattr(runtime, "_sleep_until", sleepy)
    dry.store.close()
    dry2, _ = dry_run(tmp_path, clock)
    spy_on(dry2.engine)
    assert run(dry2, ticks=5).exit_code == EXIT_OK
    assert len(calls) == 2  # startup + after the gap
