"""Sizing, exchange minimums and dust (story 7; FR-13, CON-02, CON-03, AD-13).

Rules: the recorded Kraken public snapshot (amount_min 0.00006 BTC, cost_min 0.45 EUR,
step 1e-8). Limits: the real protected config (100% / EUR 25, drawdown 25%). Fee 0.40%,
slippage 5 bp: one BTC at 40,000 costs 40,000 x 1.004 x 1.0005 = 40,180.08 EUR.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from bot.backtest.dataset import load_dataset
from bot.backtest.market_rules import load_rules_snapshot
from bot.backtest.runner import run_backtest
from bot.config import load_settings
from bot.sizing import (
    NoOrder,
    SizingInput,
    buy_qty,
    completion_qty,
    floor_step,
    sell_qty,
    sellable,
    sellable_threshold,
)
from tests.backtest.synth import end_date, make_env
from tests.conftest import REPO_ROOT

RULES = load_rules_snapshot("BTC/EUR").rules
LIMITS = load_settings(REPO_ROOT / "config.yaml", REPO_ROOT / "no-such.env").risk
FEE, SLIP = Decimal("0.004"), Decimal(5)


def _buy(equity: str, price: str = "40000", free: str | None = None, position: str = "0"):  # noqa: ANN202
    return buy_qty(
        SizingInput(
            target=Decimal(1),
            equity=Decimal(equity),
            free_quote=Decimal(free if free is not None else equity),
            position=Decimal(position),
            resting_buy_qty=Decimal(0),
            price=Decimal(price),
            fee_rate=FEE,
            slippage_bps=SLIP,
        ),
        RULES,
        LIMITS,
    )


# Hand-computed table (AD-13). qty = floor_1e-8(spend / (price x 1.004 x 1.0005)).
# 1. EUR 20 flat:      spend 20 -> 20 / 40180.08 = 0.000497759.. -> 0.00049775
# 2. EUR 100 equity:   cap EUR 25 -> 25 / 40180.08 = 0.000622198.. -> 0.00062219
# 3. EUR 20 after an unsellable partial fill of 0.00005 (the re-price path):
#    budget 20 - 0.00005 x 40000 = 18 -> 18 / 40180.08 = 0.000447983.. -> 0.00044798
# 4. EUR 2 at 40,000:  2 / 40180.08 = 0.0000497.. < amount_min 0.00006 -> below_minimum
# 5. EUR 0.55 at 7000: qty 0.00007821 >= amount_min, cost 0.547 >= 0.45, but after a 25%
#    loss 0.547 x 0.75 = 0.41 < 0.45: unsellable -> below_minimum
TABLE = [
    ("20", "40000", "20", "0", Decimal("0.00049775")),
    ("100", "40000", "100", "0", Decimal("0.00062219")),
    ("20", "40000", "18", "0.00005", Decimal("0.00044798")),
    ("2", "40000", "2", "0", "below_minimum"),
    ("0.55", "7000", "0.55", "0", "below_minimum"),
]


@pytest.mark.parametrize(("equity", "price", "free", "position", "expected"), TABLE)
def test_hand_computed_buy_sizes(equity, price, free, position, expected) -> None:
    got = _buy(equity, price, free, position)
    if isinstance(expected, Decimal):
        assert got == expected
    else:
        assert isinstance(got, NoOrder) and got.outcome == expected and got.reason


def test_buy_never_spends_more_than_free_cash_after_fee_and_slippage() -> None:
    qty = _buy("20")
    assert isinstance(qty, Decimal)
    assert qty * Decimal(40000) * (1 + FEE) * (1 + SLIP / 10000) <= Decimal(20)


def test_below_minimum_is_rejected_never_rounded_up() -> None:
    got = _buy("2")
    assert isinstance(got, NoOrder)
    assert "amount_min" in got.reason
    # Rounding up to the minimum would have been 0.00006 BTC = EUR 2.41 > the EUR 2 held.


def test_sell_sizes_the_full_base_position() -> None:
    assert sell_qty(Decimal("0.00049775"), Decimal(40000), RULES) == Decimal("0.00049775")
    assert sell_qty(Decimal("0.000497759"), Decimal(40000), RULES) == Decimal("0.00049775")


def test_sell_below_minimums_is_rejected() -> None:
    assert sell_qty(Decimal("0.00005"), Decimal(40000), RULES).outcome == "below_minimum"
    got = sell_qty(Decimal("0.0001"), Decimal(4000), RULES)  # EUR 0.40 < cost_min
    assert isinstance(got, NoOrder) and got.outcome == "below_minimum"
    assert sell_qty(Decimal(0), Decimal(40000), RULES).outcome == "no_action"


def test_sellable_threshold() -> None:
    # max(amount_min, cost_min / (price x 0.75)): at 40,000 -> max(0.00006, 0.000015)
    assert sellable_threshold(Decimal(40000), RULES, LIMITS) == Decimal("0.00006")
    # at 5,000 -> 0.45 / 3750 = 0.00012
    assert sellable_threshold(Decimal(5000), RULES, LIMITS) == Decimal("0.00012")
    assert sellable(Decimal("0.00012"), Decimal(5000), RULES, LIMITS)
    assert not sellable(Decimal("0.00011999"), Decimal(5000), RULES, LIMITS)


def test_completion_qty_is_the_smallest_valid_buy_to_the_threshold() -> None:
    assert completion_qty(Decimal("0.00005"), Decimal(40000), RULES, LIMITS) == Decimal("0.00006")
    assert completion_qty(Decimal("0.0001"), Decimal(40000), RULES, LIMITS).outcome == "no_action"


def test_floor_step() -> None:
    assert floor_step(Decimal("0.123456789"), Decimal("0.00000001")) == Decimal("0.12345678")
    assert floor_step(Decimal(-1), Decimal("0.1")) == 0


def test_rules_come_from_the_recorded_public_snapshot() -> None:
    snap = load_rules_snapshot("BTC/EUR")
    assert snap.fetched_at == "2026-11-13"
    assert "load_markets" in snap.source
    assert (RULES.amount_min, RULES.cost_min) == (Decimal("0.00006"), Decimal("0.45"))
    assert (RULES.tick_size, RULES.amount_step) == (Decimal("0.1"), Decimal("0.00000001"))
    with pytest.raises(ValueError):
        load_rules_snapshot("ETH/EUR")


def test_backtest_logs_and_counts_a_below_minimum_signal(tmp_path) -> None:
    # EUR 1 of capital at ~44,000: 1 / 44,000 < amount_min. The signal is journaled as
    # below_minimum with its reason and a rejection risk event; nothing is placed.
    closes = [40000.0, 40000.0, 44000.0, 44000.0, 44000.0]
    env = make_env(tmp_path, closes, sma_days=2, initial_quote="1")
    ds = load_dataset(env.settings, env.start, end_date(env, len(closes)), ("1d", "15m"))
    r = run_backtest(env.settings, ds, "maker")
    sig = next(s for s in r.signals if s["candle_open_at"].startswith("2020-01-03"))
    assert sig["outcome"] == "below_minimum" and "amount_min" in sig["outcome_reason"]
    assert any(e["kind"] == "rejection" and e["rule"] == "minimums" for e in r.risk_events)
    assert r.orders == [] and r.fills == []
    _ = date


def test_backtest_logs_an_unsellable_after_worst_loss_buy_as_below_minimum(tmp_path) -> None:
    # Price ~5,000: 0.55 EUR buys 0.0001095 BTC (>= amount_min, cost 0.547 >= 0.45), but the
    # sellable threshold is 0.45 / (5000 x 0.75) = 0.00012: refused, logged, nothing placed.
    closes = [4500.0, 4500.0, 5000.0, 5000.0, 5000.0]
    env = make_env(tmp_path, closes, sma_days=2, initial_quote="0.55")
    ds = load_dataset(env.settings, env.start, end_date(env, len(closes)), ("1d", "15m"))
    r = run_backtest(env.settings, ds, "maker")
    sig = next(s for s in r.signals if s["candle_open_at"].startswith("2020-01-03"))
    assert sig["outcome"] == "below_minimum" and "sellable" in sig["outcome_reason"]
    assert any(e["kind"] == "rejection" and e["rule"] == "minimums" for e in r.risk_events)
    assert r.orders == []


def test_rules_are_re_read_for_each_intent(tmp_path) -> None:
    from tests.backtest.test_execution import Harness

    h = Harness(tmp_path)
    calls = []
    real = h.broker.load_market
    h.broker.load_market = lambda pair: calls.append(pair) or real(pair)  # type: ignore[method-assign]
    h.tick()
    assert calls == ["BTC/EUR"]  # once for the buy intent created on this tick


def test_partial_sell_leaving_dust_writes_a_dust_event(tmp_path) -> None:
    from datetime import timedelta

    from tests.backtest.test_execution import T15, Harness

    h = Harness(tmp_path)
    h.tick()
    buy = h.broker.placed[0]
    h.broker.fill(buy.cl_ord_id, buy.qty)
    h.tick(T15)  # buy done
    h.tick(timedelta(hours=24) - T15)  # day 4 00:00:30: day-3 close not above SMA -> sell
    sell = h.broker.placed[-1]
    assert sell.side == "sell" and sell.qty == buy.qty
    h.broker.fill(sell.cl_ord_id, sell.qty - Decimal("0.00001"))  # leaves 0.00001 BTC
    h.tick(timedelta(hours=6))  # window end
    events = h.store.all("SELECT kind, rule FROM risk_events")
    assert ("dust", "minimums") in [(e[0], e[1]) for e in events]


def test_below_minimum_remainder_of_a_partial_buy_enters_completion(tmp_path, monkeypatch):
    from datetime import timedelta

    from tests.backtest.test_execution import Harness

    h = Harness(tmp_path)
    h.tick()
    h.broker.fill(h.broker.placed[0].cl_ord_id, Decimal("0.00005"))  # unsellable partial
    # The re-price remainder cannot be sized as a valid order (below the minimums).
    monkeypatch.setattr(
        h.engine, "_size", lambda *a: NoOrder("below_minimum", "remainder below amount_min")
    )
    h.tick(timedelta(minutes=30))
    # AD-13: the remainder goes to AD-28 completion, a new intent linked to its parent.
    child = h.completion()
    assert child is not None and child["parent_intent_id"] == 1
    rows = h.store.all("SELECT kind, rule FROM risk_events")
    assert ("rejection", "minimums") in [(r[0], r[1]) for r in rows]
