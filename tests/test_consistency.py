"""Story M3-9: the backtest and the paper broker produce the same trades on the same
recorded data (FR-60, AD-6, BI-05; GL-02 depends on it).

Two engines run in lockstep on the SAME inputs (``tests/fixtures/consistency/``: real
Kraken 15m candles and bid/ask quotes derived from them, see ``make_fixture.py``):

- backtest path: the backtest's adapters, as ``bot.backtest.runner.run_backtest`` wires
  them: ``ReplayMarketData`` over the frames, ``PaperBroker`` with the recorded public
  market snapshot, ``SimClock``, an in-memory store;
- paper path: the dry-run wiring itself, ``bot.runtime.build_dry_run``: ``CcxtMarketData``
  and ``LiveFeed`` over a fake public exchange that serves the same candles and quotes,
  ``PaperBroker`` with live rules and ticker, a ``FakeClock``.

Both use the plumbing strategy (many intents) and identical tick times. Fills, prices,
fees, order states and journal outcomes must be identical. A perturbed quote must make
them differ (the test is not vacuous).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import ccxt
import pandas as pd
import pytest

from bot.backtest.market_rules import load_rules_snapshot
from bot.broker.base import FeeRates, Ticker
from bot.broker.paper import PaperBroker
from bot.clock import FakeClock, SimClock
from bot.data.market import ReplayMarketData
from bot.engine import Engine
from bot.runtime import build_dry_run, engine_config
from bot.store import Store
from bot.strategy.registry import build
from tests.engine.helpers import make_settings

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "consistency"
PAIR = "BTC/EUR"
START = datetime(2026, 11, 5, 1, 0, 15, tzinfo=UTC)  # 15 s after an hourly close
END = datetime(2026, 11, 7, 23, 0, 0, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def _frames() -> tuple[pd.DataFrame, pd.DataFrame]:
    raw = pd.read_csv(FIXTURE / "candles_15m.csv")
    raw["open_at"] = pd.to_datetime(raw["open_at"], utc=True).dt.as_unit("ms")
    f15 = raw.assign(trades=pd.array([pd.NA] * len(raw), dtype="Int64"), source="api")
    h = raw.set_index("open_at").resample("1h", label="left", closed="left")
    f1h = pd.DataFrame(
        {"open": h["open"].first(), "high": h["high"].max(), "low": h["low"].min(),
         "close": h["close"].last(), "volume": h["volume"].sum()}
    ).reset_index()  # fmt: skip
    f1h = f1h.assign(trades=pd.array([pd.NA] * len(f1h), dtype="Int64"), source="api")
    return f15, f1h


def _quotes(perturb_at: datetime | None = None) -> Callable[[datetime], tuple[Decimal, Decimal]]:
    q = pd.read_csv(FIXTURE / "quotes.csv")
    times = [datetime.fromisoformat(t.replace("Z", "+00:00")) for t in q["at"]]
    bids = [Decimal(str(b)) for b in q["bid"]]
    asks = [Decimal(str(a)) for a in q["ask"]]
    if perturb_at is not None:
        i = max(k for k, t in enumerate(times) if t <= perturb_at)
        bids[i] -= Decimal(40)
        asks[i] -= Decimal(40)

    def at(t: datetime) -> tuple[Decimal, Decimal]:
        i = max(k for k, s in enumerate(times) if s <= t)
        return bids[i], asks[i]

    return at


class RecordedPublicKraken:
    """Fake public exchange replaying the fixture (closed rows plus the forming one)."""

    precisionMode = ccxt.TICK_SIZE
    rateLimit = 1000

    def __init__(self, clock, frames: dict[str, pd.DataFrame], quotes) -> None:  # noqa: ANN001
        self.clock = clock
        self.frames = frames
        self.quotes = quotes

    def fetch_ohlcv(self, symbol, timeframe, since=None, limit=None):  # noqa: ANN001, ANN201
        now = self.clock.now()
        f = self.frames[timeframe]
        rows = f[f["open_at"] <= pd.Timestamp(now)]
        return [
            [int(r.open_at.value // 1_000_000), r.open, r.high, r.low, r.close, r.volume]
            for r in rows.tail(limit or 720).itertuples()
        ]

    def fetch_ticker(self, symbol: str) -> dict:
        bid, ask = self.quotes(self.clock.now())
        return {"bid": str(bid), "ask": str(ask), "last": None, "timestamp": None}

    def load_markets(self, reload: bool = False) -> dict:
        r = load_rules_snapshot(PAIR).rules
        return {
            PAIR: {
                "base": r.base, "quote": r.quote, "active": True,
                "precision": {"amount": str(r.amount_step), "price": str(r.tick_size)},
                "limits": {"amount": {"min": str(r.amount_min)}, "cost": {"min": str(r.cost_min)}},
                "info": {"status": r.status},
            }
        }  # fmt: skip

    def fetch_time(self) -> int:
        return int((self.clock.now() - _EPOCH).total_seconds() * 1000)


def _backtest_path(settings, f15, f1h, quotes):  # noqa: ANN001, ANN202
    clock = SimClock(START - timedelta(seconds=15))
    data = settings.data.model_copy(update={"timeframes": ("15m", "1h")})
    md = ReplayMarketData.from_frames({(PAIR, "15m"): f15, (PAIR, "1h"): f1h}, clock, data)
    store = Store.open(":memory:")
    snap = load_rules_snapshot(PAIR)

    def ticker(pair: str) -> Ticker:
        bid, ask = quotes(clock.now())
        return Ticker(pair, bid, ask, (bid + ask) / 2, clock.now())

    broker = PaperBroker(
        store, md, clock, snap.rules, FeeRates(settings.fees.maker, settings.fees.taker, "config"),
        slippage_bps=settings.slippage_bps, half_spread_bps=settings.execution.sim_half_spread_bps,
        initial_quote=settings.paper.initial_quote, exec_timeframe="15m", ticker_source=ticker,
    )  # fmt: skip
    p = settings.plumbing
    strategy = build(
        "plumbing", {"flip_hours": p.flip_hours, "target_pct": p.target_pct}, "backtest"
    )
    cfg = engine_config(settings, PAIR, strategy, snap.rules.quote, "backtest", "autonomous")
    engine = Engine(broker, clock, md, store, strategy, settings.risk, cfg)
    engine.start()
    return engine, clock


def _paper_path(settings, f15, f1h, quotes):  # noqa: ANN001, ANN202
    clock = FakeClock(START - timedelta(seconds=15))
    ex = RecordedPublicKraken(clock, {"15m": f15, "1h": f1h}, quotes)
    dry = build_dry_run(settings, "plumbing", ex, clock, approval="autonomous",
                        db_path=Path(":memory:"))  # fmt: skip
    dry.engine.start()
    dry.engine.recover(clock.now())
    return dry.engine, clock


def _drive(a: Engine, ca: SimClock, b: Engine, cb: FakeClock) -> None:
    """Lockstep: every 60 s while an intent is active, else at the next hourly close
    + 15 s (the CcxtMarketData 10 s settle margin is inside those 15 s)."""
    t = START
    while t <= END:
        ca.advance_to(t)
        cb.advance(t - cb.now())
        a.tick()
        b.tick()
        if a.busy or b.busy:
            t += timedelta(minutes=1)
        else:
            t = _EPOCH + ((t - _EPOCH) // timedelta(hours=1) + 1) * timedelta(hours=1)
            t += timedelta(seconds=15)


def _trades(engine: Engine) -> dict[str, list[tuple]]:
    s = engine.store
    return {
        "signals": [tuple(r) for r in s.all(
            "SELECT candle_open_at, target_fraction, signal_price, outcome, outcome_reason "
            "FROM signals ORDER BY candle_open_at")],
        "intents": [tuple(r) for r in s.all(
            "SELECT side, target_qty, filled_qty, state, created_at, window_end_at "
            "FROM intents ORDER BY intent_id")],
        "orders": [tuple(r) for r in s.all(
            "SELECT created_at, attempt_no, side, qty, limit_price, state, filled_qty "
            "FROM orders ORDER BY order_id")],
        "fills": [tuple(r) for r in s.all(
            "SELECT at, side, qty, price, fee, liquidity, slippage_bps FROM fills "
            "ORDER BY fill_id")],
    }  # fmt: skip


@pytest.fixture(scope="module")
def runs(tmp_path_factory):  # noqa: ANN001, ANN201
    tmp = tmp_path_factory.mktemp("consistency")
    settings = make_settings(tmp)
    f15, f1h = _frames()
    quotes = _quotes()
    a, ca = _backtest_path(settings, f15, f1h, quotes)
    b, cb = _paper_path(settings, f15, f1h, quotes)
    _drive(a, ca, b, cb)
    return settings, f15, f1h, _trades(a), _trades(b)


def test_fixture_covers_enough_intents_with_a_reprice_and_a_not_filled(runs) -> None:  # noqa: ANN001
    _, _, _, bt, _ = runs
    assert len(bt["intents"]) >= 10
    assert any(o[1] >= 2 for o in bt["orders"])  # a re-price (attempt 2+)
    assert any(s[3] == "not_filled" for s in bt["signals"])
    assert bt["fills"]  # and real fills


def test_backtest_and_paper_broker_produce_identical_trades(runs) -> None:  # noqa: ANN001
    _, _, _, bt, paper = runs
    for key in ("fills", "orders", "intents", "signals"):
        assert paper[key] == bt[key], key


def test_a_perturbed_recorded_price_breaks_the_equality(runs) -> None:  # noqa: ANN001
    settings, f15, f1h, bt, _ = runs
    first_order_at = datetime.fromisoformat(bt["orders"][0][0].replace("Z", "+00:00"))
    a, ca = _backtest_path(settings, f15, f1h, _quotes())
    b, cb = _paper_path(settings, f15, f1h, _quotes(perturb_at=first_order_at))
    _drive(a, ca, b, cb)
    assert _trades(b)["orders"] != _trades(a)["orders"]
