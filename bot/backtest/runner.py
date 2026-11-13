"""Backtest runner (FR-12, AD-1): the shared Engine with backtest adapters.

``Engine(PaperBroker, SimClock, ReplayMarketData, Store(":memory:"))``, approval forced to
autonomous. A halt ends the run and the result says so.

Tick schedule (decision 2026-11-13): the SimClock visits each daily close plus
``execution.tick_seconds`` (the order-placement lag of a live tick), and while an intent
is active, every execution-candle (15m) boundary plus the same lag; nothing happens
between those instants in a daily strategy, so skipping them changes no outcome and keeps
a 9-year run fast. A signal on candle t is therefore acted on at t's close + 30 s, and its
first eligible fill candle is the 15m candle starting after that (AD-6).
"""

from __future__ import annotations

import itertools
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from bot.backtest.dataset import Dataset, interval
from bot.backtest.market_rules import load_rules_snapshot
from bot.backtest.provenance import config_hash, limits_hash
from bot.broker.base import FeeRates
from bot.broker.paper import PaperBroker
from bot.clock import SimClock
from bot.config import Settings
from bot.data.market import ReplayMarketData
from bot.engine import Engine, EngineConfig
from bot.store import Store, parse_iso
from bot.strategy.registry import build

Variant = Literal["maker", "taker"]


class InsufficientData(ValueError):
    """The range holds too few candles to warm up and evaluate the strategy."""


@dataclass
class RunResult:
    variant: Variant
    strategy_id: str
    signals: list[dict[str, str | None]]
    fills: list[dict[str, str]]
    equity: list[tuple[datetime, Decimal, Decimal, Decimal]]  # (at, equity, mark, base_qty)
    risk_events: list[dict[str, str | None]]
    halted: bool
    halt_reason: str | None
    initial_quote: Decimal
    rules_snapshot: dict[str, str]
    eval_start: datetime  # first close at which the strategy had its full warm-up
    last_tick: datetime
    orders_submitted: int
    order_outcomes: dict[str, int] = field(default_factory=dict)
    orders: list[dict[str, str | None]] = field(default_factory=list)


def _deterministic_ids(variant: str):  # noqa: ANN202
    counter = itertools.count(1)
    ns = uuid.uuid5(uuid.NAMESPACE_URL, f"trading-bot-backtest-{variant}")
    return lambda: uuid.uuid5(ns, str(next(counter))).hex


def run_backtest(
    settings: Settings,
    dataset: Dataset,
    variant: Variant,
    *,
    stop_after: datetime | None = None,
    strategy_id: str | None = None,
    params: dict[str, int] | None = None,
) -> RunResult:
    """Run the engine over ``dataset``. ``stop_after`` ends the run once the clock passes
    that instant (look-ahead reruns)."""
    sid = strategy_id or settings.strategy.id
    strategy = build(sid, params if params is not None else settings.strategy.params, "backtest")
    tf = strategy.timeframe
    exec_tf = settings.execution.sim_timeframe
    day, step = interval(tf), interval(exec_tf)
    lag = timedelta(seconds=settings.execution.tick_seconds)
    window = timedelta(hours=settings.execution.window_hours)

    daily = dataset.frames[tf]
    if len(daily) < strategy.warmup + 1:
        raise InsufficientData(
            f"need more than {strategy.warmup} {tf} candles for the warm-up, have {len(daily)}"
        )
    eval_start = daily["open_at"].iloc[strategy.warmup - 1].to_pydatetime() + day

    first = dataset.start + day + lag
    clock = SimClock(first)
    frames = {(dataset.pair, t): f for t, f in dataset.frames.items()}
    md = ReplayMarketData.from_frames(frames, clock, settings.data)
    store = Store.open(":memory:")
    snap = load_rules_snapshot(dataset.pair)
    fees = FeeRates(settings.fees.maker, settings.fees.taker, source="config")
    broker = PaperBroker(
        store,
        md,
        clock,
        snap.rules,
        fees,
        slippage_bps=settings.slippage_bps,
        half_spread_bps=settings.execution.sim_half_spread_bps,
        initial_quote=settings.paper.initial_quote,
        exec_timeframe=exec_tf,
        liquidity=variant,
    )
    engine = Engine(
        broker,
        clock,
        md,
        store,
        strategy,
        settings.risk,
        backtest_engine_config(settings, dataset.pair, tf, snap.rules.quote, variant),
        new_cl_ord_id=_deterministic_ids(variant),
    )
    engine.start()

    # Last daily-close tick whose execution window still fits inside the data:
    # close + window <= end  <=>  tick (= close + lag) <= end - window + lag.
    last_signal_tick = dataset.end - window + lag
    hard_end = _floor(last_signal_tick, day) + window + step + lag
    t, last_tick = first, first
    halted = False
    while t <= hard_end and (stop_after is None or t <= stop_after):
        clock.advance_to(t)
        last_tick = t
        if engine.tick().halted:
            halted = True
            break
        if engine.busy:
            t = _floor(t, step) + step + lag
        else:
            t = _floor(t, day) + day + lag
            if t > last_signal_tick:
                break
    engine.stop("halted" if halted else "end of data")
    rules_info = {
        "fetched_at": snap.fetched_at,
        "source": snap.source,
        "amount_min": str(snap.rules.amount_min),
        "cost_min": str(snap.rules.cost_min),
        "tick_size": str(snap.rules.tick_size),
        "amount_step": str(snap.rules.amount_step),
    }
    return _collect(store, variant, sid, halted, eval_start, last_tick, settings, rules_info)


def backtest_engine_config(
    settings: Settings, pair: str, timeframe: str, quote: str, variant: Variant
) -> EngineConfig:
    """The backtest's engine settings: approval forced to autonomous (AD-1)."""
    return EngineConfig(
        mode="backtest",
        pair=pair,
        timeframe=timeframe,
        window=timedelta(hours=settings.execution.window_hours),
        reprice_interval=timedelta(minutes=settings.execution.reprice_interval_minutes),
        completion_window=timedelta(hours=settings.execution.completion_window_hours),
        approval="autonomous",
        slippage_bps=settings.slippage_bps,
        quote_is_fiat=quote in settings.fiat_currencies,
        git_commit="backtest",
        git_dirty=False,
        config_hash=config_hash(settings),
        limits_hash=limits_hash(settings),
        pricing="passive" if variant == "maker" else "aggressive",
    )


def _floor(t: datetime, step: timedelta) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=t.tzinfo)
    return epoch + ((t - epoch) // step) * step


def _collect(
    store: Store,
    variant: Variant,
    sid: str,
    halted: bool,
    eval_start: datetime,
    last_tick: datetime,
    settings: Settings,
    rules_info: dict[str, str],
) -> RunResult:
    signals = [
        dict(r)
        for r in store.all(
            "SELECT candle_open_at, target_fraction, signal_price, outcome, outcome_reason "
            "FROM signals ORDER BY candle_open_at"
        )
    ]
    fills = [
        dict(r)
        for r in store.all(
            "SELECT at, side, qty, price, fee, liquidity, reference_price FROM fills "
            "ORDER BY at, fill_id"
        )
    ]
    equity = [
        (parse_iso(r["at"]), Decimal(r["equity"]), Decimal(r["mark_price"]), Decimal(r["base_qty"]))
        for r in store.all(
            "SELECT at, equity, mark_price, base_qty FROM equity_snapshots "
            "WHERE is_day_open = 1 ORDER BY at"
        )
    ]
    events = [
        dict(r)
        for r in store.all("SELECT at, kind, rule, reason FROM risk_events ORDER BY event_id")
    ]
    halt = store.one("SELECT rule, reason FROM halts ORDER BY halt_id")
    outcomes = {
        r["state"]: int(r["n"])
        for r in store.all("SELECT state, count(*) AS n FROM orders GROUP BY state")
    }
    orders = [
        dict(r)
        for r in store.all(
            "SELECT o.intent_id, o.attempt_no, o.side, o.qty, o.limit_price, o.state, "
            "o.reject_reason, o.created_at, o.filled_qty FROM orders o ORDER BY o.order_id"
        )
    ]
    return RunResult(
        orders=orders,
        variant=variant,
        strategy_id=sid,
        signals=signals,
        fills=fills,
        equity=equity,
        risk_events=events,
        halted=halted,
        halt_reason=None if halt is None else f"{halt['rule']}: {halt['reason']}",
        initial_quote=settings.paper.initial_quote,
        rules_snapshot=rules_info,
        eval_start=eval_start,
        last_tick=last_tick,
        orders_submitted=sum(outcomes.values()),
        order_outcomes=outcomes,
    )
