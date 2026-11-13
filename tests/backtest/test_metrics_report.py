"""Metrics, benchmarks at maker and taker rates, verdict line and provenance (story 8;
FR-14, FR-18..FR-21, CON-06, NFR-02, NFR-09, AD-21)."""

from __future__ import annotations

import json
import math
import statistics
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np

from bot.backtest.command import default_request, execute
from bot.backtest.metrics import (
    bootstrap_sharpe_ci,
    buy_and_hold_metrics,
    max_drawdown,
    sharpe,
    strategy_metrics,
)
from bot.backtest.report import SIMULATED_LINE, verdict
from bot.backtest.runner import RunResult
from tests.backtest.synth import end_date, make_env

T0 = datetime(2021, 1, 1, 0, 0, 30, tzinfo=UTC)


def _run(equity: list[str], marks: list[str], base: list[str], fills=()) -> RunResult:  # noqa: ANN001
    pts = [
        (T0 + timedelta(days=i), Decimal(e), Decimal(m), Decimal(b))
        for i, (e, m, b) in enumerate(zip(equity, marks, base, strict=True))
    ]
    return RunResult(
        variant="maker", strategy_id="x", signals=[], fills=list(fills), equity=pts,
        risk_events=[], halted=False, halt_reason=None, initial_quote=Decimal(equity[0]),
        rules_snapshot={}, eval_start=T0, last_tick=pts[-1][0], orders_submitted=0,
    )  # fmt: skip


def test_hand_computed_strategy_metrics() -> None:
    fills = [
        {"at": "2021-01-01T06:00:00.000Z", "side": "buy", "qty": "1", "price": "100",
         "fee": "0.4"},
        {"at": "2021-01-03T06:00:00.000Z", "side": "sell", "qty": "1", "price": "99",
         "fee": "0.396"},
    ]  # fmt: skip
    run = _run(
        ["100", "110", "99", "121"], ["100", "110", "99", "121"], ["1", "1", "0", "0"], fills
    )
    m = strategy_metrics(run, resamples=200, block=2, seed=1)
    assert m.total_return == 0.21 or math.isclose(m.total_return, 0.21)
    assert m.days == 3
    assert math.isclose(m.annualized_return, 1.21 ** (365 / 3) - 1)
    assert math.isclose(m.max_drawdown, 1 - 99 / 110)
    rets = [0.1, 99 / 110 - 1, 121 / 99 - 1]
    expected_sharpe = statistics.mean(rets) / statistics.stdev(rets) * math.sqrt(365)
    assert math.isclose(m.sharpe, expected_sharpe)
    assert m.trades == 2 and m.round_trips == 1
    assert math.isclose(m.total_fees, 0.796)
    assert math.isclose(m.turnover, (100 + 99) / statistics.mean([100, 110, 99, 121]))
    assert m.time_in_market == 0.5


def test_buy_and_hold_pays_fee_and_slippage_once() -> None:
    run = _run(["20", "20", "20"], ["100", "110", "120"], ["0", "0", "0"])
    m = buy_and_hold_metrics(run, Decimal("0.004"), Decimal(5), 100, 1, 0)
    qty = 20 / (100 * 1.0005 * 1.004)
    assert math.isclose(m.final_equity, qty * 120)
    assert math.isclose(m.total_return, qty * 120 / 20 - 1)
    assert math.isclose(m.total_fees, qty * 100 * 1.0005 * 0.004)
    assert m.trades == 1 and m.time_in_market == 1.0
    taker = buy_and_hold_metrics(run, Decimal("0.008"), Decimal(5), 100, 1, 0)
    assert taker.total_return < m.total_return  # higher fee, lower return


def test_sharpe_and_drawdown_edge_cases() -> None:
    assert sharpe(np.array([0.01, 0.01, 0.01])) == 0.0  # zero volatility
    assert sharpe(np.array([0.01])) == 0.0
    assert max_drawdown(np.array([1.0, 2.0, 3.0])) == 0.0
    assert math.isclose(max_drawdown(np.array([1.0, 2.0, 1.0, 3.0])), 0.5)


def test_bootstrap_ci_is_seeded_and_brackets_the_estimate() -> None:
    rng = np.random.default_rng(0)
    rets = rng.normal(0.001, 0.02, 500)
    a = bootstrap_sharpe_ci(rets, 500, 20, seed=7)
    b = bootstrap_sharpe_ci(rets, 500, 20, seed=7)
    assert a == b
    assert a[0] < sharpe(rets) < a[1]
    assert bootstrap_sharpe_ci(rets[:1], 100, 20, seed=1) == (0.0, 0.0)


def _block(s: float, b: float) -> dict:
    return {
        "strategy": {"total_return": s, "start": "2021-01-01", "end": "2022-01-01"},
        "buy_and_hold": {"total_return": b},
    }


def test_verdict_says_not_beating_in_its_first_words() -> None:
    v = verdict("v0_trend", _block(0.5, 1.0), _block(0.4, 0.9))
    assert v["beats_buy_and_hold_after_costs"] is False
    assert v["line"].startswith(
        "VERDICT (SIMULATED): v0_trend does NOT beat buy-and-hold after costs"
    )
    mixed = verdict("v0_trend", _block(1.1, 1.0), _block(0.8, 0.9))
    assert mixed["beats_buy_and_hold_after_costs"] is False and "at taker fees" in mixed["line"]
    win = verdict("v0_trend", _block(1.1, 1.0), _block(1.0, 0.9))
    assert win["beats_buy_and_hold_after_costs"] is True
    assert "not evidence of future profit" in win["line"]


# --- end to end through the one command ------------------------------------------------

KEYS = (
    "total_return",
    "annualized_return",
    "max_drawdown",
    "sharpe",
    "sharpe_ci_95",
    "trades",
    "turnover",
    "total_fees",
    "time_in_market",
)
RISE_FALL = [100.0 + 3 * i for i in range(20)] + [157.0 - 4 * i for i in range(20)]


def _execute(env, results_dir=None):  # noqa: ANN001, ANN202
    req = default_request(env.settings, "v0_trend", date(2026, 11, 13))
    fields = {**req.__dict__, "end": end_date(env, len(RISE_FALL))}
    if results_dir is not None:
        fields["results_dir"] = results_dir
    return execute(env.settings, req.__class__(**fields))


def test_report_first_line_is_the_verdict_and_second_the_simulated_label(tmp_path) -> None:
    env = make_env(tmp_path, RISE_FALL, wiggle=0.005)
    json_path, md_path, payload = _execute(env)
    lines = md_path.read_text("utf-8").splitlines()
    assert lines[0] == payload["verdict"]["line"]
    assert lines[0].startswith("VERDICT (SIMULATED): v0_trend ")
    assert lines[2] == SIMULATED_LINE
    assert "## Results at maker fees" in md_path.read_text("utf-8")
    assert "## Results at taker fees" in md_path.read_text("utf-8")


def test_results_json_holds_metrics_benchmarks_and_provenance(tmp_path) -> None:
    env = make_env(tmp_path, RISE_FALL, wiggle=0.005)
    json_path, _, _ = _execute(env)
    p = json.loads(json_path.read_text("utf-8"))
    assert p["label"] == "SIMULATED"
    for variant in ("maker", "taker"):
        for who in ("strategy", "buy_and_hold", "cash"):
            m = p["results"][variant][who]
            for key in KEYS:
                assert key in m, (variant, who, key)
        assert p["results"][variant]["cash"]["total_return"] == 0.0
    assert len(p["code_version"]["git_commit"]) == 40
    assert isinstance(p["code_version"]["git_dirty"], bool)
    assert len(p["config_hash"]) == 64
    assert p["data"]["start"].startswith("2020-01-01")
    assert set(p["data"]["hashes"]) == {"1d", "15m"}
    assert p["change"] == 0 and p["configurations_tried"] == 1
    taker_fees = p["results"]["taker"]["strategy"]["total_fees"]
    maker_fees = p["results"]["maker"]["strategy"]["total_fees"]
    assert taker_fees > maker_fees > 0


def test_same_inputs_give_the_same_file_content(tmp_path) -> None:
    env = make_env(tmp_path / "a", RISE_FALL, wiggle=0.005)
    j1, m1, _ = _execute(env, tmp_path / "r1")
    j2, m2, _ = _execute(env, tmp_path / "r2")
    assert j1.read_bytes() == j2.read_bytes()
    assert m1.read_bytes() == m2.read_bytes()
