"""Engine + FakeBroker + FakeClock harness for the M3 engine tests (AD-24, FR-59).

``FakeEnv`` builds the production ``Engine`` on an in-memory (or file) store with the
scriptable ``FakeBroker``, a ``FakeClock`` and a tiny in-memory ``MarketData``. The
strategy is a constant target, so tests control buys and sells directly. ``restart()``
builds a NEW engine on the same store and broker, as a process restart would.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pandas as pd

from bot.broker.base import Balance, FeeRates, MarketRules, Ticker
from bot.candles import CandleHistory
from bot.clock import FakeClock
from bot.config import TIMEFRAME_SECONDS
from bot.engine import Engine, EngineConfig
from bot.risk.kill_switch import kill_switch_engaged
from bot.risk.limits import RiskLimits
from bot.store import Store
from tests.engine.helpers import make_settings
from tests.fakes.broker import FakeBroker

T0 = datetime(2026, 11, 14, 0, 0, 30, tzinfo=UTC)  # 30 s after a daily close
RULES = MarketRules(
    pair="BTC/EUR",
    base="BTC",
    quote="EUR",
    amount_min=Decimal("0.00006"),
    cost_min=Decimal("0.45"),
    tick_size=Decimal("0.1"),
    amount_step=Decimal("0.00000001"),
    status="online",
)
FEES = FeeRates(Decimal("0.004"), Decimal("0.008"), source="config")


class ConstStrategy:
    """Target fixed by the test (``target`` is mutable)."""

    id = "test_const"
    warmup = 0
    allowed_modes = frozenset({"backtest", "dry-run"})

    def __init__(self, target: str = "1", timeframe: str = "1d") -> None:
        self.target = Decimal(target)
        self.timeframe = timeframe

    def on_candle(self, history: CandleHistory) -> Decimal:
        return self.target

    def indicators(self, history: CandleHistory) -> dict[str, float]:
        return {"n": float(len(history))}


class FrameMarketData:
    """Flat closed candles at ``price`` for any timeframe, as of the clock time.
    ``synthetic_from`` marks candles opening at or after that time as synthetic."""

    def __init__(self, clock: FakeClock, price: float = 40000.0) -> None:
        self.clock = clock
        self.price = price
        self.synthetic_from: datetime | None = None

    def closed_candles(self, pair: str, timeframe: str, limit: int | None = None) -> CandleHistory:
        step = TIMEFRAME_SECONDS[timeframe]
        now = self.clock.now()
        epoch = datetime(1970, 1, 1, tzinfo=UTC)
        last = int((now - epoch).total_seconds()) // step - 1  # newest closed index
        n = limit or 5
        idx = list(range(last - n + 1, last + 1))
        opens = [epoch + timedelta(seconds=i * step) for i in idx]
        src = [
            "synthetic" if self.synthetic_from is not None and o >= self.synthetic_from else "api"
            for o in opens
        ]
        frame = pd.DataFrame(
            {
                "open_at": pd.to_datetime(opens, utc=True),
                "open": self.price,
                "high": self.price,
                "low": self.price,
                "close": self.price,
                "volume": 1.0,
                "source": src,
            }
        )
        return CandleHistory.from_frame(frame, timeframe, now)


@dataclass
class FakeEnv:
    tmp_path: Path
    approval: str = "autonomous"
    target: str = "1"
    timeframe: str = "1d"
    price: Decimal = Decimal("40000")
    clock: FakeClock = field(default_factory=lambda: FakeClock(T0))

    def __post_init__(self) -> None:
        self.settings = make_settings(self.tmp_path)
        self.limits: RiskLimits = self.settings.risk
        self.kill_path = self.settings.risk.kill_switch_path
        self.broker = FakeBroker(
            self.clock,
            RULES,
            FEES,
            balances={
                "EUR": Balance("EUR", Decimal("20"), Decimal(0)),
                "BTC": Balance("BTC", Decimal(0), Decimal(0)),
            },
        )
        self.md = FrameMarketData(self.clock, float(self.price))
        self.store = Store.open(self.tmp_path / "engine.sqlite")
        self.strategy = ConstStrategy(self.target, self.timeframe)
        self.ids = iter(f"cl{i:04d}" for i in range(1, 10_000))
        self.engine = self._engine()
        self.refresh_ticker()
        self.engine.start(pid=1)

    def config(self) -> EngineConfig:
        return EngineConfig(
            mode="dry-run",
            pair="BTC/EUR",
            timeframe=self.timeframe,
            window=timedelta(hours=6),
            reprice_interval=timedelta(minutes=30),
            completion_window=timedelta(hours=24),
            approval=self.approval,  # type: ignore[arg-type]
            slippage_bps=Decimal(5),
            quote_is_fiat=True,
            git_commit="test",
            git_dirty=False,
            config_hash="c",
            limits_hash="l",
        )

    def _engine(self) -> Engine:
        return Engine(
            self.broker,
            self.clock,
            self.md,
            self.store,
            self.strategy,
            self.limits,
            self.config(),
            kill_switch=lambda: kill_switch_engaged(self.kill_path),
            kill_switch_path=self.kill_path,
            new_cl_ord_id=lambda: next(self.ids),
        )

    def refresh_ticker(self, bid: Decimal | None = None, ask: Decimal | None = None) -> None:
        bid = bid if bid is not None else self.price - Decimal("0.5")
        ask = ask if ask is not None else self.price + Decimal("0.5")
        self.broker.ticker = Ticker("BTC/EUR", bid, ask, (bid + ask) / 2, self.clock.now())

    def tick(self, advance: timedelta = timedelta(seconds=30)):  # noqa: ANN201
        self.clock.advance(advance)
        self.refresh_ticker()
        return self.engine.tick()

    def restart(self) -> Engine:
        """A new engine on the same store and broker (the process restarted)."""
        self.engine.stop("crash (simulated)")
        self.engine = self._engine()
        self.refresh_ticker()
        self.engine.start(pid=2)
        self.engine.recover(self.clock.now())
        return self.engine

    def sync_balances(self) -> None:
        """Set the fake exchange balances to what the store derives (as a real exchange
        account would show after the fills)."""
        self.broker.balances = {
            "EUR": Balance("EUR", self.store.cash(), Decimal(0)),
            "BTC": Balance("BTC", self.store.position("BTC/EUR"), Decimal(0)),
        }

    # --- queries ----------------------------------------------------------------------

    def orders(self) -> list[dict]:
        return [dict(r) for r in self.store.all("SELECT * FROM orders ORDER BY order_id")]

    def intents(self) -> list[dict]:
        return [dict(r) for r in self.store.all("SELECT * FROM intents ORDER BY intent_id")]

    def signals(self) -> list[dict]:
        return [dict(r) for r in self.store.all("SELECT * FROM signals ORDER BY candle_open_at")]

    def fills_qty(self, intent_id: int) -> Decimal:
        rows = self.store.all(
            "SELECT f.qty FROM fills f JOIN orders o USING (order_id) WHERE o.intent_id = ?",
            (intent_id,),
        )
        return sum((Decimal(r["qty"]) for r in rows), Decimal(0))

    def halts(self) -> list[str]:
        return [r["rule"] for r in self.store.all("SELECT rule FROM halts WHERE reset_at IS NULL")]

    def risk_events(self, kind: str | None = None) -> list[dict]:
        sql = "SELECT * FROM risk_events" + (" WHERE kind = ?" if kind else "")  # noqa: S608
        return [dict(r) for r in self.store.all(sql, (kind,) if kind else ())]
