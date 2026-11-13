"""Protected halts in the backtest (audit M2 F-1): evaluated on equity marked at every 15m
close, resting orders cancelled and position kept, operator reset modelled as a SIMULATED
RESET at the next UTC daily close, and reported."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal

from bot.backtest.command import default_request, execute
from bot.backtest.dataset import load_dataset
from bot.backtest.runner import run_backtest
from tests.backtest.synth import end_date, make_env
from tests.backtest.test_execution import T15, Harness

# v0 SMA(3): long from day 6 (bought on the 00:15 candle). Day 10 (2020-01-11) has an
# intraday crash on the 12:00 candle, recovering on the next one.
CLOSES = [40000.0] * 5 + [40000.0 + 400 * i for i in range(1, 21)]
DAY10 = 10 * 96


def _crash(depth: float) -> dict[int, tuple[float, float, float, float]]:
    j = DAY10 + 48
    p = CLOSES[9] + (CLOSES[10] - CLOSES[9]) * (48 / 96)  # path price around 12:00
    low = p * (1 - depth)
    return {j: (p, p, low, low), j + 1: (low, p * 1.001, low, p * 1.001)}


def _run(tmp_path, depth, **kw):  # noqa: ANN001, ANN003, ANN202
    env = make_env(tmp_path, CLOSES, wiggle=0.005, overrides=_crash(depth), **kw)
    ds = load_dataset(env.settings, env.start, end_date(env, len(CLOSES)), ("1d", "15m"))
    return env, ds


def test_intraday_crash_triggers_a_daily_loss_halt_and_a_simulated_reset(tmp_path) -> None:
    env, ds = _run(tmp_path, 0.15)
    r = run_backtest(env.settings, ds, "maker")
    assert [e["rule"] for e in r.halt_events] == ["daily_loss"]
    e = r.halt_events[0]
    assert e["triggered_at"] == "2020-01-11T12:15:30.000Z"  # 12:00 candle close + 30 s lag
    assert e["reset_at"] == "2020-01-12T00:00:30.000Z"  # next UTC daily close
    assert str(e["reset_note"]).startswith("SIMULATED RESET")
    assert not e["rebase_baseline"]
    # Position kept through the halt: one buy, no sell.
    assert [f["side"] for f in r.fills] == ["buy"]
    assert not r.halted  # the run continued after the simulated reset


def test_deep_crash_triggers_drawdown_too_and_the_reset_rebases_the_baseline(tmp_path) -> None:
    env, ds = _run(tmp_path, 0.30)  # equity <= 75% of the EUR 20 baseline
    r = run_backtest(env.settings, ds, "maker")
    assert sorted(e["rule"] for e in r.halt_events) == ["daily_loss", "total_drawdown"]
    assert all(e["reset_at"] == "2020-01-12T00:00:30.000Z" for e in r.halt_events)
    assert all(e["rebase_baseline"] for e in r.halt_events)  # one reset action, rebased
    # No re-halt after the rebased reset.
    assert len(r.halt_events) == 2


def test_event_scan_finds_the_same_halts_as_ticking_every_15m(tmp_path) -> None:
    env, ds = _run(tmp_path, 0.15)
    scan = run_backtest(env.settings, ds, "maker")
    brute = run_backtest(env.settings, ds, "maker", intraday_ticks="every_15m")
    assert scan.halt_events == brute.halt_events
    assert scan.fills == brute.fills


def test_end_run_policy_stops_at_the_first_halt(tmp_path) -> None:
    env, ds = _run(tmp_path, 0.15, config_edits={"backtest.simulated_halt_reset": "end_run"})
    r = run_backtest(env.settings, ds, "maker")
    assert r.halted and r.halt_events[0]["reset_at"] is None
    assert r.last_tick.isoformat().startswith("2020-01-11T12:15:30")


def test_report_lists_halts_with_dates_and_the_simulated_reset_label(tmp_path) -> None:
    env, _ = _run(tmp_path, 0.15)
    req = default_request(env.settings, "v0_trend", date(2026, 11, 13))
    req = req.__class__(**{**req.__dict__, "end": end_date(env, len(CLOSES))})
    _, md, p = execute(env.settings, req)
    h = p["results"]["maker"]["halts"]
    assert h["count_by_rule"] == {"daily_loss": 1}
    assert h["events"][0]["simulated_reset"] is True
    text = md.read_text("utf-8")
    assert "## Protected halts and SIMULATED RESETS" in text
    assert "2020-01-11 12:15" in text and "SIMULATED RESET" in text


def test_no_trading_while_halted_orders_cancelled_position_kept(tmp_path) -> None:
    h = Harness(tmp_path)
    h.tick()
    buy = h.broker.placed[0]
    h.broker.fill(buy.cl_ord_id, buy.qty)
    h.tick(T15)
    h.tick(timedelta(hours=24) - T15)  # day 4 00:00:30: sell intent working
    sell = h.broker.placed[-1]
    assert sell.side == "sell"
    crash = Decimal("0.8")
    h.broker.ticker = replace(
        h.broker.ticker, bid=h.broker.ticker.bid * crash, ask=h.broker.ticker.ask * crash
    )
    assert h.tick(T15).halted  # equity -20% vs day open: daily-loss halt
    assert sell.cl_ord_id in h.broker.cancel_calls  # resting order cancelled
    assert h.intent_state() == "halted"
    assert h.store.position("BTC/EUR") == buy.qty  # position kept, no forced sale
    placed = len(h.broker.placed)
    for _ in range(4):  # re-price times pass: nothing is placed while halted
        assert h.tick(timedelta(minutes=30)).halted
    assert len(h.broker.placed) == placed
    assert h.engine.reset_halts(h.clock.now(), "test reset", rebase_rules=()) == ["daily_loss"]
    assert h.store.one("SELECT count(*) FROM halts WHERE reset_at IS NULL")[0] == 0
