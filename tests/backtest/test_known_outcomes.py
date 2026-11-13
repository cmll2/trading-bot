"""Known-outcome synthetic backtests through the one command (story 11; FR-58, FR-13).

Each series is run through ``execute`` (the function behind ``bot backtest``: maker and
taker runs, look-ahead guard, metrics, report). Expected trades, fills, fees, ending
equity and the verdict line are derived by hand below from the execution model:

- v0 with SMA(3); signal on day d's close, worked from day d+1 00:00:30;
- ticker = last closed 15m close c; bid = floor_0.1(c x 0.9999), ask = ceil_0.1(c x 1.0001);
- maker buy at the bid, filled on the first eligible 15m candle whose low < bid (wicks
  0.5%, so the first eligible candle trades through), price x 1.0005, fee 0.40%;
- qty = floor_1e-8(cash / (price_limit x 1.004 x 1.0005));
- equity marked at mid = (bid + ask) / 2 of the day's last closed 15m close.
"""

from __future__ import annotations

import math
from datetime import date
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

import pytest

from bot.backtest.command import default_request, execute
from tests.backtest.synth import end_date, make_env

TICK, STEP = Decimal("0.1"), Decimal("0.00000001")
FEE_M, SLIP = Decimal("0.004"), Decimal("1.0005")


def bid(c: float) -> Decimal:
    return (Decimal(repr(c)) * Decimal("0.9999") / TICK).to_integral_value(ROUND_FLOOR) * TICK


def ask(c: float) -> Decimal:
    return (Decimal(repr(c)) * Decimal("1.0001") / TICK).to_integral_value(ROUND_CEILING) * TICK


def mid(c: float) -> Decimal:
    return (bid(c) + ask(c)) / 2


def qty_for(cash: Decimal, limit: Decimal) -> Decimal:
    return (cash / (limit * (1 + FEE_M) * SLIP) / STEP).to_integral_value(ROUND_FLOOR) * STEP


def _run(tmp_path, closes, **kw):  # noqa: ANN001, ANN003, ANN202
    env = make_env(tmp_path, closes, wiggle=0.005, **kw)
    req = default_request(env.settings, "v0_trend", date(2026, 11, 13))
    req = req.__class__(**{**req.__dict__, "end": end_date(env, len(closes))})
    _, md, payload = execute(env.settings, req)
    return payload, md.read_text("utf-8").splitlines()[0]


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-9)  # JSON rounds to 10 decimals


def _bh_final(closes: list[float], first: int, last: int, fee: Decimal, half: Decimal) -> float:
    """Buy-and-hold: all EUR 20 at the first evaluation mark (+ half spread for taker)."""
    m0 = mid(closes[first])
    q = Decimal(20) / (m0 * (1 + half) * SLIP * (1 + fee))
    return float(q * mid(closes[last]))


# Evaluation: warm-up 3 -> first point is day 3 00:00:30 (mark = close of day 2); the last
# daily point is day n-1 00:00:30 (mark = close of day n-2).


def test_rising_series_one_buy_with_hand_computed_fill_fee_and_equity(tmp_path) -> None:
    closes = [40000.0] * 5 + [40000.0 + 400 * i for i in range(1, 26)]
    p, line = _run(tmp_path, closes)
    m = p["results"]["maker"]["strategy"]
    # Signal day 5 (40400 > SMA 40133.3); limit = bid of 40400 = 40395.9.
    limit = bid(40400.0)
    assert limit == Decimal("40395.9")
    q = qty_for(Decimal(20), limit)
    price = limit * SLIP
    fee = q * price * FEE_M
    cash = Decimal(20) - q * price - fee
    final = cash + q * mid(closes[-2])
    assert m["trades"] == 1 and m["round_trips"] == 0
    assert _close(m["total_fees"], float(fee))
    assert _close(m["final_equity"], float(final))
    bh = p["results"]["maker"]["buy_and_hold"]
    assert _close(bh["final_equity"], _bh_final(closes, 2, len(closes) - 2, FEE_M, Decimal(0)))
    # Buy-and-hold entered 3 days earlier at 40,000: the strategy trails it after costs.
    assert line.startswith("VERDICT (SIMULATED): v0_trend does NOT beat buy-and-hold after costs")


def test_falling_series_never_trades_and_beats_buy_and_hold(tmp_path) -> None:
    closes = [40000.0 - 300 * i for i in range(30)]
    p, line = _run(tmp_path, closes)
    for v in ("maker", "taker"):
        s = p["results"][v]["strategy"]
        assert s["trades"] == 0 and s["total_fees"] == 0.0
        assert s["final_equity"] == 20.0 and s["total_return"] == 0.0
        assert p["results"][v]["buy_and_hold"]["total_return"] < 0
    assert line.startswith("VERDICT (SIMULATED): v0_trend beats buy-and-hold after costs")
    assert line.endswith("This is not evidence of future profit.")


def test_flat_series_never_trades_and_buy_and_hold_loses_only_its_costs(tmp_path) -> None:
    closes = [40000.0] * 30
    p, _ = _run(tmp_path, closes)
    s = p["results"]["maker"]["strategy"]
    assert s["trades"] == 0 and s["final_equity"] == 20.0
    bh = p["results"]["maker"]["buy_and_hold"]
    expected = 20 / (1.0005 * 1.004)  # bought and marked at the same 40,000 mid
    assert _close(bh["final_equity"], expected)
    taker = p["results"]["taker"]["buy_and_hold"]
    assert _close(taker["final_equity"], 20 / (1.0001 * 1.0005 * 1.008))


def test_gap_down_round_trip_with_hand_computed_fees(tmp_path) -> None:
    # Long from day 3 (signal day 2: 44000 > SMA 42666.7; days 3-4 keep rising, so v0 stays
    # long); gap down on day 5 to 38000 (< SMA 43000): sell worked on day 6 at the ask of
    # 38000 (38003.8), filled on the first eligible candle whose high > ask.
    closes = [40000.0, 40000.0, 44000.0, 45000.0, 46000.0] + [38000.0] * 25
    p, line = _run(tmp_path, closes)
    m = p["results"]["maker"]["strategy"]
    buy_limit = bid(44000.0)
    q = qty_for(Decimal(20), buy_limit)
    buy_price = buy_limit * SLIP
    sell_price = ask(38000.0) * (2 - SLIP)  # slippage against the seller: x 0.9995
    fees = q * buy_price * FEE_M + q * sell_price * FEE_M
    final = Decimal(20) - q * buy_price + q * sell_price - fees
    assert m["trades"] == 2 and m["round_trips"] == 1
    assert _close(m["total_fees"], float(fees))
    assert _close(m["final_equity"], float(final))
    assert m["time_in_market"] > 0
    assert "VERDICT (SIMULATED): v0_trend" in line


def test_sub_minimum_capital_is_rejected_logged_and_counted_never_rounded(tmp_path) -> None:
    closes = [40000.0] * 5 + [40000.0 + 400 * i for i in range(1, 26)]
    p, line = _run(tmp_path, closes, initial_quote="1")  # EUR 1 < 0.00006 BTC x 40,000
    for v in ("maker", "taker"):
        b = p["results"][v]
        assert b["strategy"]["trades"] == 0
        assert b["signal_outcomes"].get("below_minimum", 0) >= 1
        assert (
            b["risk_events"].get("rejection:minimums", 0) == b["signal_outcomes"]["below_minimum"]
        )
        assert b["orders_submitted"] == 0
    assert line.startswith("VERDICT (SIMULATED): v0_trend does NOT beat buy-and-hold")


@pytest.mark.parametrize("start", [date(2018, 1, 1)])
def test_2018_01_13_anomaly_is_listed_in_the_report(tmp_path, start) -> None:
    """Audit M1 F-3: the report's data-anomaly section lists 2018-01-13 whenever the range
    covers it (signals use closes; fills on that day or the next are flagged)."""
    closes = [14000.0 - 50 * i for i in range(30)]
    env = make_env(tmp_path, closes, start=start, wiggle=0.005)
    req = default_request(env.settings, "v0_trend", date(2026, 11, 13))
    req = req.__class__(**{**req.__dict__, "end": end_date(env, len(closes))})
    _, md, payload = execute(env.settings, req)
    dates = [a["date"] for a in payload["data_anomalies"]]
    assert dates == ["2018-01-13"]
    assert payload["data_anomalies"][0]["flag"] == "no fill"
    assert "2018-01-13" in md.read_text("utf-8").split("## Data anomalies")[1]
