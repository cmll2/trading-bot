"""Walking-skeleton backtest (story 4): one command, shared engine, pure v0, risk on every
submission (FR-05..FR-08, FR-11, FR-30, AD-1, AD-3, AD-10)."""

from __future__ import annotations

import ast
import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from bot import cli
from bot import engine as engine_mod
from bot.backtest import runner as runner_mod
from bot.backtest.dataset import load_dataset
from bot.backtest.runner import run_backtest
from bot.candles import CandleHistory
from bot.clock import SimClock
from bot.data.market import ReplayMarketData
from bot.strategy.registry import build
from bot.strategy.v0_trend import V0Trend
from tests.backtest.synth import end_date, make_env
from tests.conftest import REPO_ROOT

# 5 flat days (warm-up, flat), then a steady rise: v0 (SMA 3) goes long and stays long.
RISING = [100.0] * 5 + [100.0 + 5 * i for i in range(1, 26)]
FALLING = [200.0 - 4 * i for i in range(30)]


def _hist(closes: list[float]) -> CandleHistory:
    n = len(closes)
    df = pd.DataFrame(
        {
            "open_at": pd.date_range("2020-01-01", periods=n, freq="1D", tz="UTC").as_unit("ms"),
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "volume": [1.0] * n,
            "source": ["archive"] * n,
        }
    )
    return CandleHistory.from_frame(df, "1d", datetime(2030, 1, 1, tzinfo=UTC))


# --- v0 strategy (pure) ------------------------------------------------------------------


def test_v0_is_flat_until_warm_up_then_follows_the_sma() -> None:
    s = V0Trend({"sma_days": 3})
    assert s.warmup == 3
    assert s.on_candle(_hist([1.0, 2.0])) == Decimal(0)  # not enough candles
    assert s.on_candle(_hist([1.0, 2.0, 3.0])) == Decimal(1)  # 3 > mean(1,2,3)=2
    assert s.on_candle(_hist([3.0, 2.0, 1.0])) == Decimal(0)
    assert s.on_candle(_hist([2.0, 2.0, 2.0])) == Decimal(0)  # equal is not above
    assert s.indicators(_hist([1.0, 2.0, 3.0])) == {"close": 3.0, "sma_3": 2.0}


def test_v0_uses_only_the_candles_it_is_given() -> None:
    # The same closed prefix gives the same target whatever comes after it.
    s = V0Trend({"sma_days": 3})
    full = [1.0, 2.0, 3.0, 0.1, 0.1]
    assert s.on_candle(_hist(full[:3])) == s.on_candle(_hist([1.0, 2.0, 3.0]))


@pytest.mark.parametrize("params", [{}, {"sma_days": 1}, {"sma_days": "200"}, {"x": 3}])
def test_v0_refuses_bad_params(params) -> None:
    with pytest.raises(ValueError):
        V0Trend(params)


def test_registry_builds_v0_from_config_params() -> None:
    s = build("v0_trend", {"sma_days": 200}, "backtest")
    assert isinstance(s, V0Trend) and s.sma_days == 200 and s.warmup == 200


def test_v0_module_imports_nothing_impure() -> None:
    tree = ast.parse((REPO_ROOT / "bot" / "strategy" / "v0_trend.py").read_text("utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
    assert imported <= {"__future__", "collections.abc", "decimal", "numpy", "bot.candles",
                        "bot.strategy.base"}  # fmt: skip


# --- engine wiring -----------------------------------------------------------------------


def test_engine_has_no_mode_branch() -> None:
    """AD-1: ``EngineConfig.mode`` is a label; no comparison may read it."""
    tree = ast.parse((REPO_ROOT / "bot" / "engine.py").read_text("utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Attribute) and sub.attr == "mode":
                    pytest.fail(f"engine.py compares .mode at line {node.lineno}")


def test_backtest_uses_the_shared_engine_and_backtest_adapters(tmp_path, monkeypatch) -> None:
    env = make_env(tmp_path, RISING)
    seen = {}
    real_init = engine_mod.Engine.__init__

    def spy(self, broker, clock, md, store, strategy, limits, config, **kw):  # noqa: ANN001
        seen.update(broker=broker, clock=clock, md=md, store=store, config=config)
        real_init(self, broker, clock, md, store, strategy, limits, config, **kw)

    monkeypatch.setattr(runner_mod.Engine, "__init__", spy)
    ds = load_dataset(env.settings, env.start, end_date(env, len(RISING)), ("1d", "15m"))
    run_backtest(env.settings, ds, "maker")
    assert type(seen["broker"]).__name__ == "PaperBroker"
    assert isinstance(seen["clock"], SimClock)
    assert isinstance(seen["md"], ReplayMarketData)
    assert seen["config"].approval == "autonomous" and seen["config"].mode == "backtest"
    assert runner_mod.Engine is engine_mod.Engine


def test_every_submission_passes_check_order_and_carries_its_decision(tmp_path, monkeypatch):
    env = make_env(tmp_path, RISING + FALLING)
    decisions = []
    real_check = engine_mod.check_order

    def spy_check(p, ctx, limits):  # noqa: ANN001
        d = real_check(p, ctx, limits)
        decisions.append(d)
        return d

    placed = []
    from bot.broker.paper import PaperBroker

    real_place = PaperBroker.place_order

    def spy_place(self, req, decision):  # noqa: ANN001
        placed.append((req.cl_ord_id, decision))
        return real_place(self, req, decision)

    monkeypatch.setattr(engine_mod, "check_order", spy_check)
    monkeypatch.setattr(PaperBroker, "place_order", spy_place)
    ds = load_dataset(env.settings, env.start, end_date(env, 60), ("1d", "15m"))
    result = run_backtest(env.settings, ds, "maker")
    assert len(result.fills) >= 2  # a buy then a sell
    assert placed, "no order was placed"
    for cl, decision in placed:
        assert decision.approved and decision.cl_ord_id == cl
        assert decision in decisions


# --- known trend through the one command -------------------------------------------------


def test_rising_series_buys_once_and_beats_cash(tmp_path) -> None:
    # 0.5% wicks: the passive bid trades through on the first eligible 15m candle.
    env = make_env(tmp_path, RISING, wiggle=0.005)
    ds = load_dataset(env.settings, env.start, end_date(env, len(RISING)), ("1d", "15m"))
    r = run_backtest(env.settings, ds, "maker")
    buys = [f for f in r.fills if f["side"] == "buy"]
    assert len(buys) == 1 and len(r.fills) == 1
    # First close above SMA(3): day index 5 (105 > mean(100,100,105)); executed after its
    # close, i.e. on day index 6.
    assert buys[0]["at"].startswith((env.start + timedelta(days=6)).isoformat())
    assert r.equity[-1][1] > Decimal("20")
    assert not r.halted


def test_falling_series_never_trades(tmp_path) -> None:
    env = make_env(tmp_path, FALLING)
    ds = load_dataset(env.settings, env.start, end_date(env, len(FALLING)), ("1d", "15m"))
    r = run_backtest(env.settings, ds, "maker")
    assert r.fills == []
    assert {s["outcome"] for s in r.signals} == {"no_action"}


def test_cli_backtest_writes_a_simulated_results_file(tmp_path, capsys) -> None:
    env = make_env(tmp_path, RISING)
    end = end_date(env, len(RISING)).isoformat()
    code = cli.main(
        ["backtest", "--config", str(env.config_path), "--env-file", str(env.env_path),
         "--end", end],
        env={},
    )  # fmt: skip
    out = capsys.readouterr().out
    assert code == cli.EXIT_OK, out
    files = sorted(env.results_dir.glob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text("utf-8"))
    assert payload["label"] == "SIMULATED"
    assert "SIMULATED" in out


def test_cli_refuses_a_range_reaching_into_the_holdout(tmp_path, capsys) -> None:
    env = make_env(tmp_path, RISING)
    code = cli.main(
        ["backtest", "--config", str(env.config_path), "--env-file", str(env.env_path),
         "--end", "2025-11-12"],
        env={},
    )  # fmt: skip
    assert code == cli.EXIT_REFUSED
    assert "holdout" in capsys.readouterr().err
    assert not env.results_dir.exists()


def test_replay_market_data_limit_returns_the_newest_closed_candles(tmp_path) -> None:
    env = make_env(tmp_path, RISING)
    ds = load_dataset(env.settings, env.start, end_date(env, 10), ("1d", "15m"))
    clock = SimClock(datetime(2020, 1, 3, 0, 0, 30, tzinfo=UTC))
    md = ReplayMarketData.from_frames(
        {("BTC/EUR", tf): f for tf, f in ds.frames.items()}, clock, env.settings.data
    )
    full = md.closed_candles("BTC/EUR", "15m")
    last5 = md.closed_candles("BTC/EUR", "15m", limit=5)
    assert len(full) == 2 * 96
    assert np.array_equal(last5.open_at, full.open_at[-5:])
    assert len(md.closed_candles("BTC/EUR", "1d")) == 2
    _ = date
