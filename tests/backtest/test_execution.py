"""Post-only execution window: fill model, re-pricing, window end, completion phase,
taker variant (story 6; FR-12, FR-24, CON-04, CON-06, AD-5, AD-6, AD-27, AD-28).

Layout: v0 with SMA(2); daily closes 40000, 40000, 44000, ... so the close of day 2 is the
first above its SMA and the buy is worked on day 3 from 00:00:30 (close + 30 s lag). The
first order's bid is 44000 x (1 - 1 bp) floored to the 0.1 tick = 43995.6.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from bot.backtest.dataset import load_dataset
from bot.backtest.market_rules import load_rules_snapshot
from bot.backtest.runner import backtest_engine_config, run_backtest
from bot.broker.base import Balance, FeeRates, Ticker
from bot.broker.fill_model import SimCandle, SimOrder, simulate_maker, simulate_taker
from bot.clock import FakeClock
from bot.data.market import ReplayMarketData
from bot.engine import Engine
from bot.store import Store
from bot.strategy.registry import build
from tests.backtest.synth import end_date, make_env
from tests.fakes.broker import FakeBroker

CLOSES = [40000.0, 40000.0, 44000.0, 44000.0, 44000.0, 44000.0]
D3 = 3 * 96  # first 15m candle of day 3
L1 = Decimal("43995.6")
FLAT = (44000.0, 44000.0, 44000.0, 44000.0)
T15 = timedelta(minutes=15)
UTC0 = datetime(2020, 1, 1, tzinfo=UTC)


def _run(tmp_path, variant="maker", **kw):  # noqa: ANN001, ANN003, ANN202
    env = make_env(tmp_path, CLOSES, sma_days=2, wiggle=kw.pop("wiggle", 0.0), **kw)
    ds = load_dataset(env.settings, env.start, end_date(env, len(CLOSES)), ("1d", "15m"))
    return run_backtest(env.settings, ds, variant), env


def _day3_orders(result):  # noqa: ANN001, ANN202
    return [o for o in result.orders if o["created_at"].startswith("2020-01-04")]


# --- pure fill model ---------------------------------------------------------------------


def _candle(low: str, high: str = "50000", start: str = "00:15", synthetic: bool = False):
    h, m = map(int, start.split(":"))
    return SimCandle(
        UTC0.replace(hour=h, minute=m), T15, Decimal(44000), Decimal(high), Decimal(low),
        Decimal(44000), synthetic,
    )  # fmt: skip


ORDER = SimOrder("buy", Decimal("0.0004"), L1, UTC0.replace(minute=0, second=30))


def test_buy_fills_only_on_strict_trade_through() -> None:
    assert simulate_maker(ORDER, _candle(str(L1)), Decimal("0.004"), Decimal(5)) is None
    fill = simulate_maker(ORDER, _candle("43995.5"), Decimal("0.004"), Decimal(5))
    assert fill is not None
    assert fill.price == L1 * Decimal("1.0005")  # slippage against the buyer
    assert fill.fee == Decimal("0.0004") * fill.price * Decimal("0.004")
    assert fill.liquidity == "maker" and fill.at == UTC0.replace(minute=30)


def test_sell_fills_only_when_high_trades_through() -> None:
    sell = replace(ORDER, side="sell", limit_price=Decimal(44010))
    assert simulate_maker(sell, _candle("1", high="44010"), Decimal("0.004"), Decimal(5)) is None
    fill = simulate_maker(sell, _candle("1", high="44010.1"), Decimal("0.004"), Decimal(5))
    assert fill is not None and fill.price == Decimal(44010) * Decimal("0.9995")


def test_candle_that_began_before_the_order_never_fills_it() -> None:
    assert simulate_maker(ORDER, _candle("1", start="00:00"), Decimal("0.004"), Decimal(5)) is None


def test_synthetic_candle_never_fills() -> None:
    assert simulate_maker(ORDER, _candle("1", synthetic=True), Decimal("0.004"), Decimal(5)) is None


def test_taker_fills_at_once_at_its_limit_with_taker_fee() -> None:
    fill = simulate_taker(ORDER, Decimal("0.008"), Decimal(5))
    assert fill.at == ORDER.accepted_at and fill.liquidity == "taker"
    assert fill.fee == ORDER.qty * fill.price * Decimal("0.008")


# --- engine + paper broker on synthetic 15m candles -----------------------------------


def test_unfilled_window_re_prices_every_30_min_then_ends_not_filled(tmp_path) -> None:
    result, _ = _run(tmp_path)  # flat 44000 candles: the bid never trades through
    orders = _day3_orders(result)
    assert len(orders) == 12  # max_submissions_per_intent, first order included
    assert [o["attempt_no"] for o in orders] == list(range(1, 13))
    assert [o["created_at"][11:19] for o in orders] == [
        f"{h:02d}:{m:02d}:30" for h in range(6) for m in (0, 30)
    ]
    assert {o["state"] for o in orders} == {"cancelled"}
    signal = next(s for s in result.signals if s["candle_open_at"].startswith("2020-01-03"))
    assert signal["outcome"] == "not_filled"
    assert result.fills == []


def test_re_price_then_fill_on_strict_trade_through(tmp_path) -> None:
    # 00:15 low == L1: no fill (not strictly below). 00:45 low 0.1 below the second bid.
    result, _ = _run(
        tmp_path,
        overrides={D3 + 1: (44000.0, 44000.0, float(L1), 44000.0),
                   D3 + 3: (44000.0, 44000.0, 43995.5, 44000.0)},
    )  # fmt: skip
    orders = _day3_orders(result)
    assert [o["state"] for o in orders] == ["cancelled", "filled"]
    assert orders[1]["created_at"].endswith("00:30:30.000Z")
    assert len(result.fills) == 1
    fill = result.fills[0]
    assert fill["at"] == "2020-01-04T01:00:00.000Z"  # close of the 00:45 candle
    assert Decimal(fill["price"]) == L1 * Decimal("1.0005")
    signal = next(s for s in result.signals if s["candle_open_at"].startswith("2020-01-03"))
    assert signal["outcome"] == "filled"


def test_new_order_cannot_fill_on_the_candle_it_was_placed_in(tmp_path) -> None:
    # The 00:30 candle trades through, but the second order was accepted at 00:30:30.
    result, _ = _run(tmp_path, overrides={D3 + 2: (44000.0, 44000.0, 43000.0, 44000.0)})
    assert result.fills == []
    assert len(_day3_orders(result)) == 12


def test_window_of_synthetic_candles_never_fills_and_ends_not_filled(tmp_path) -> None:
    # Exchange halt from 00:15: flat synthetic candles at 43000, below the 43995.6 bid.
    result, _ = _run(
        tmp_path,
        overrides={D3: (44000.0, 44000.0, 43000.0, 43000.0)},
        synthetic_15m=set(range(D3 + 1, D3 + 24)),
        config_edits={"data.max_synthetic_ratio_by_timeframe": {"15m": "0.5"}},
    )
    assert result.fills == []
    signal = next(s for s in result.signals if s["candle_open_at"].startswith("2020-01-03"))
    assert signal["outcome"] == "not_filled"
    # The resting order is kept during the halt (stale ticker: no re-price churn).
    assert len(_day3_orders(result)) == 1


def test_taker_variant_fills_at_the_ask_with_the_taker_fee(tmp_path) -> None:
    result, _ = _run(tmp_path, variant="taker", wiggle=0.001)
    buy = result.fills[0]
    assert buy["liquidity"] == "taker" and buy["at"] == "2020-01-04T00:00:30.000Z"
    ask = Decimal("44004.4")  # 44000 x (1 + 1 bp), ceiled to the tick
    assert Decimal(buy["price"]) == ask * Decimal("1.0005")
    assert Decimal(buy["fee"]) == Decimal(buy["qty"]) * Decimal(buy["price"]) * Decimal("0.008")


# --- engine + FakeBroker: partial fills, completion phase, crosses, rejects -----------


class Harness:
    def __init__(self, tmp_path) -> None:  # noqa: ANN001
        env = make_env(tmp_path, CLOSES, sma_days=2, wiggle=0.0)
        self.settings = env.settings
        ds = load_dataset(env.settings, env.start, end_date(env, len(CLOSES)), ("1d", "15m"))
        self.t0 = datetime(2020, 1, 4, 0, 0, 30, tzinfo=UTC)
        self.clock = FakeClock(self.t0)
        md = ReplayMarketData.from_frames(
            {("BTC/EUR", tf): f for tf, f in ds.frames.items()}, self.clock, env.settings.data
        )
        rules = load_rules_snapshot("BTC/EUR").rules
        fees = FeeRates(Decimal("0.004"), Decimal("0.008"), "config")
        self.broker = FakeBroker(
            clock=self.clock,
            rules=rules,
            fees=fees,
            balances={"EUR": Balance("EUR", Decimal(20), Decimal(0))},
            ticker=Ticker("BTC/EUR", L1, Decimal("44004.4"), Decimal(44000), self.t0),
        )
        self.store = Store.open(":memory:")
        self.engine = Engine(
            self.broker,
            self.clock,
            md,
            self.store,
            build("v0_trend", {"sma_days": 2}, "backtest"),
            env.settings.risk,
            backtest_engine_config(env.settings, "BTC/EUR", "1d", "EUR", "maker"),
        )
        self.engine.start()

    def tick(self, advance: timedelta = timedelta(0)):  # noqa: ANN201
        self.clock.advance(advance)
        self.broker.ticker = replace(self.broker.ticker, ts=self.clock.now())
        return self.engine.tick()

    def outcome(self, day: str = "2020-01-03") -> str:
        return self.store.one(
            "SELECT outcome FROM signals WHERE candle_open_at LIKE ?", (f"{day}%",)
        )[0]

    def intent_state(self) -> str:
        return self.store.one("SELECT state FROM intents ORDER BY intent_id DESC")[0]


def test_unsellable_partial_buy_enters_completion_and_reaches_the_threshold(tmp_path) -> None:
    h = Harness(tmp_path)
    h.tick()
    first = h.broker.placed[0]
    h.broker.fill(first.cl_ord_id, Decimal("0.00005"))  # below amount_min 0.00006
    h.tick(timedelta(hours=6))  # window end
    assert h.intent_state() == "completing"
    h.tick(T15)  # completion order: smallest valid buy reaching the sellable threshold
    completion = h.broker.placed[-1]
    assert completion.qty == Decimal("0.00006")
    h.broker.fill(completion.cl_ord_id, completion.qty)
    h.tick(T15)
    assert h.intent_state() == "done"
    assert h.outcome() == "partially_filled"
    assert h.store.position("BTC/EUR") == Decimal("0.00011")


def test_completion_that_never_reaches_the_threshold_ends_as_dust(tmp_path) -> None:
    h = Harness(tmp_path)
    h.tick()
    h.broker.fill(h.broker.placed[0].cl_ord_id, Decimal("0.00005"))
    h.tick(timedelta(hours=6))
    h.tick(T15)
    h.tick(timedelta(hours=24))  # past completion_end_at, completion order unfilled
    assert h.outcome() == "dust"
    kinds = [r[0] for r in h.store.all("SELECT kind FROM risk_events")]
    assert "dust" in kinds
    assert h.store.one("SELECT count(*) FROM errors WHERE error_type = 'Dust'")[0] == 1


def test_post_only_cross_re_prices_immediately(tmp_path) -> None:
    h = Harness(tmp_path)
    h.broker.script_place("cross")
    h.tick()
    rows = h.store.all("SELECT attempt_no, state, reject_reason FROM orders ORDER BY order_id")
    assert [(r[0], r[1]) for r in rows] == [(1, "rejected"), (2, "open")]
    assert "post_only_cross" in rows[0][2]
    assert len(h.broker.submitted) == 2


def test_exchange_reject_ends_the_intent_with_a_risk_event(tmp_path) -> None:
    h = Harness(tmp_path)
    h.broker.script_place("reject")
    h.tick()
    assert h.intent_state() == "cancelled"
    assert h.outcome() == "rejected_by_risk"
    assert h.store.one("SELECT count(*) FROM risk_events WHERE kind = 'exchange_reject'")[0] == 1


def test_re_price_waits_for_the_cancel_and_fills_before_a_new_order(tmp_path) -> None:
    h = Harness(tmp_path)
    h.tick()
    first = h.broker.placed[0]
    h.broker.fill(first.cl_ord_id, Decimal("0.0001"))  # partial before the re-price
    h.tick(timedelta(minutes=30))
    second = h.broker.placed[-1]
    assert second.cl_ord_id != first.cl_ord_id
    assert first.cl_ord_id in h.broker.cancel_calls
    # The partial fill was ingested before sizing the re-price: the second order only
    # buys the remainder (equity and cash already reflect the first fill).
    assert second.qty < first.qty
    filled = h.store.one("SELECT filled_qty FROM intents")[0]
    assert Decimal(filled) == Decimal("0.0001")


@pytest.mark.parametrize("variant", ["maker", "taker"])
def test_every_simulated_fill_carries_fees_and_slippage(tmp_path, variant) -> None:
    result, _ = _run(tmp_path, variant=variant, wiggle=0.003)
    assert result.fills
    for f in result.fills:
        assert Decimal(f["fee"]) > 0
        assert Decimal(f["price"]) != Decimal(f["reference_price"]) or variant == "maker"
