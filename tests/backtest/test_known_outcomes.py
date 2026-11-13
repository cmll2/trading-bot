"""Known-outcome synthetic backtests through the one command (story 11; FR-58, FR-13).

Each series is run through ``execute`` (the function behind ``bot backtest``: maker and
taker runs, look-ahead guard, metrics, report). Expected trades, fees, ending equity,
buy-and-hold equity and the exact verdict line are derived by hand from this model:

- v0 with SMA(3) ("above" is strict); a signal on day d's close is worked from day d+1
  00:00:30; equity starts at EUR 20;
- ticker from the last closed 15m close c: bid = floor_0.1(c x 0.9999),
  ask = ceil_0.1(c x 1.0001), mid = (bid + ask) / 2;
- maker (as built): buy limit at the bid, sell limit at the ask; filled on the first
  eligible 15m candle that trades strictly through (0.5% wicks guarantee it here);
  price x 1.0005 for a buy, x 0.9995 for a sell (slippage 5 bp); fee 0.40%;
- taker (CON-06 variant): buy at the ask, sell at the bid, filled at once; same slippage;
  fee 0.80%;
- qty = floor_1e-8(cash / (limit x (1 + fee) x 1.0005));
- buy-and-hold: EUR 20 at the first evaluation mark (day 3 00:00:30, mark = mid of the
  day-2 close) x (1 + half spread, taker only) x 1.0005 x (1 + fee), marked at mid;
- the last evaluation point is day n-1 00:00:30 (mark = mid of the day n-2 close).
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from bot.backtest.command import default_request, execute
from tests.backtest.synth import end_date, make_env

TICK, STEP = Decimal("0.1"), Decimal("0.00000001")
FEE = {"maker": Decimal("0.004"), "taker": Decimal("0.008")}
HALF = {"maker": Decimal(0), "taker": Decimal("0.0001")}
BUY_SLIP, SELL_SLIP = Decimal("1.0005"), Decimal("0.9995")
START = date(2020, 1, 1)


def bid(c: float) -> Decimal:
    return (Decimal(repr(c)) * Decimal("0.9999") / TICK).to_integral_value(ROUND_FLOOR) * TICK


def ask(c: float) -> Decimal:
    return (Decimal(repr(c)) * Decimal("1.0001") / TICK).to_integral_value(ROUND_CEILING) * TICK


def mid(c: float) -> Decimal:
    return (bid(c) + ask(c)) / 2


def qty_for(cash: Decimal, limit: Decimal, fee: Decimal) -> Decimal:
    return (cash / (limit * (1 + fee) * BUY_SLIP) / STEP).to_integral_value(ROUND_FLOOR) * STEP


def bh_final(closes: list[float], variant: str) -> Decimal:
    m0 = mid(closes[2])
    q = Decimal(20) / (m0 * (1 + HALF[variant]) * BUY_SLIP * (1 + FEE[variant]))
    return q * mid(closes[-2])


def verdict_line(closes: list[float], s: dict[str, Decimal], b: dict[str, Decimal]) -> str:
    """The report's line 1, rebuilt from hand-computed final equities."""
    sm, st = float(s["maker"] / 20 - 1), float(s["taker"] / 20 - 1)
    bm, bt = float(b["maker"] / 20 - 1), float(b["taker"] / 20 - 1)
    span = f"{START + timedelta(days=3)}..{START + timedelta(days=len(closes) - 1)}"
    detail = (
        f"total return {sm:+.1%} vs buy-and-hold {bm:+.1%} at maker fees, "
        f"{st:+.1%} vs {bt:+.1%} at taker fees ({span})"
    )
    if sm > bm and st > bt:
        return (
            f"VERDICT (SIMULATED): v0_trend beats buy-and-hold after costs in this backtest: "
            f"{detail}. This is not evidence of future profit."
        )
    where = (
        "at both maker and taker fees"
        if sm <= bm and st <= bt
        else ("at maker fees" if sm <= bm else "at taker fees")
    )
    return (
        f"VERDICT (SIMULATED): v0_trend does NOT beat buy-and-hold after costs ({where}): {detail}."
    )


def _run(tmp_path, closes, start=START, **kw):  # noqa: ANN001, ANN003, ANN202
    env = make_env(tmp_path, closes, start=start, wiggle=0.005, **kw)
    req = default_request(env.settings, "v0_trend", date(2026, 11, 13))
    req = req.__class__(**{**req.__dict__, "end": end_date(env, len(closes))})
    _, md, payload = execute(env.settings, req)
    text = md.read_text("utf-8")
    return payload, text.splitlines()[0], text


def _close(a: float, b: Decimal | float) -> bool:
    return math.isclose(a, float(b), rel_tol=1e-9, abs_tol=1e-9)  # JSON rounds to 10 dp


def _check(p: dict, variant: str, trades: int, fees: Decimal, final: Decimal) -> None:
    s = p["results"][variant]["strategy"]
    assert s["trades"] == trades, variant
    assert _close(s["total_fees"], fees), variant
    assert _close(s["final_equity"], final), variant


def _bh_ok(p: dict, closes: list[float], variant: str) -> bool:
    return _close(p["results"][variant]["buy_and_hold"]["final_equity"], bh_final(closes, variant))


def test_rising_series_one_buy_hand_computed_at_both_rates(tmp_path) -> None:
    closes = [40000.0] * 5 + [40000.0 + 400 * i for i in range(1, 26)]
    p, line, _ = _run(tmp_path, closes)
    # Signal day 5 (40400 > SMA(40000, 40000, 40400) = 40133.3); v0 stays long after.
    assert bid(40400.0) == Decimal("40395.9") and ask(40400.0) == Decimal("40404.1")
    finals = {}
    for variant, limit in (("maker", bid(40400.0)), ("taker", ask(40400.0))):
        q = qty_for(Decimal(20), limit, FEE[variant])
        price = limit * BUY_SLIP
        fee = q * price * FEE[variant]
        finals[variant] = Decimal(20) - q * price - fee + q * mid(closes[-2])
        _check(p, variant, 1, fee, finals[variant])
        assert _bh_ok(p, closes, variant)
    assert line == verdict_line(closes, finals, {v: bh_final(closes, v) for v in FEE})
    assert "does NOT beat" in line  # buy-and-hold entered 3 days earlier, at 40,000


def test_falling_series_never_trades_and_beats_buy_and_hold(tmp_path) -> None:
    closes = [40000.0 - 300 * i for i in range(30)]
    p, line, _ = _run(tmp_path, closes)
    for variant in FEE:
        _check(p, variant, 0, Decimal(0), Decimal(20))
        assert _bh_ok(p, closes, variant)
    finals = {v: Decimal(20) for v in FEE}
    assert line == verdict_line(closes, finals, {v: bh_final(closes, v) for v in FEE})
    assert line.endswith("This is not evidence of future profit.")


def test_flat_series_never_trades_and_buy_and_hold_loses_only_its_costs(tmp_path) -> None:
    closes = [40000.0] * 30
    p, line, _ = _run(tmp_path, closes)
    for variant in FEE:
        _check(p, variant, 0, Decimal(0), Decimal(20))
    assert _close(p["results"]["maker"]["buy_and_hold"]["final_equity"], 20 / (1.0005 * 1.004))
    taker_bh = 20 / (1.0001 * 1.0005 * 1.008)
    assert _close(p["results"]["taker"]["buy_and_hold"]["final_equity"], taker_bh)
    finals = {v: Decimal(20) for v in FEE}
    assert line == verdict_line(closes, finals, {v: bh_final(closes, v) for v in FEE})


def test_gap_down_round_trip_hand_computed_at_both_rates(tmp_path) -> None:
    # Signal day 2: 44000 > SMA(40000, 40000, 44000) = 41333.3 -> long; days 3-4 keep
    # rising (45000 > 43000, 46000 > 45000); gap down on day 5 to 38000 (< SMA 43000) ->
    # sell worked on day 6 (maker at the ask of 38000 = 38003.8, filled when a candle's
    # high > ask; taker at the bid at once).
    closes = [40000.0, 40000.0, 44000.0, 45000.0, 46000.0] + [38000.0] * 25
    p, line, _ = _run(tmp_path, closes)
    finals = {}
    legs = {"maker": (bid(44000.0), ask(38000.0)), "taker": (ask(44000.0), bid(38000.0))}
    for variant, (buy_limit, sell_limit) in legs.items():
        q = qty_for(Decimal(20), buy_limit, FEE[variant])
        buy_price, sell_price = buy_limit * BUY_SLIP, sell_limit * SELL_SLIP
        fees = q * (buy_price + sell_price) * FEE[variant]
        finals[variant] = Decimal(20) - q * buy_price + q * sell_price - fees
        _check(p, variant, 2, fees, finals[variant])
        assert p["results"][variant]["strategy"]["round_trips"] == 1
    assert line == verdict_line(closes, finals, {v: bh_final(closes, v) for v in FEE})


def test_sub_minimum_capital_is_rejected_logged_and_counted_never_rounded(tmp_path) -> None:
    closes = [40000.0] * 5 + [40000.0 + 400 * i for i in range(1, 26)]
    p, line, text = _run(tmp_path, closes, initial_quote="1")
    # EUR 1 buys ~2.5e-5 BTC < amount_min 0.00006. v0 is long on every evaluated close
    # from day 5 to day 28 (= n - 2): 24 signals, each rejected below_minimum, never rounded.
    for variant in FEE:
        b = p["results"][variant]
        assert b["strategy"]["trades"] == 0 and b["orders_submitted"] == 0
        assert b["signal_outcomes"]["below_minimum"] == 24
        assert b["risk_events"]["rejection:minimums"] == 24
    assert "'rejection:minimums': 24" in text  # the report shows the logged rejections
    assert line.startswith("VERDICT (SIMULATED): v0_trend does NOT beat buy-and-hold")


def test_2018_01_13_anomaly_is_listed_in_the_report(tmp_path) -> None:
    """Audit M1 F-3: the data-anomaly section lists 2018-01-13 whenever the range covers it
    (signals use closes; fills on that day or the next are flagged)."""
    closes = [14000.0 - 50 * i for i in range(30)]
    p, _, text = _run(tmp_path, closes, start=date(2018, 1, 1))
    assert [a["date"] for a in p["data_anomalies"]] == ["2018-01-13"]
    assert p["data_anomalies"][0]["flag"] == "no fill"
    assert "2018-01-13" in text.split("## Data anomalies")[1]
