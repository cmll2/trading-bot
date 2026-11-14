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

import numpy as np

from bot.backtest.dataset import Dataset, interval
from bot.backtest.market_rules import load_rules_snapshot
from bot.backtest.provenance import config_hash, limits_hash
from bot.broker.base import FeeRates
from bot.broker.paper import PaperBroker
from bot.clock import SimClock
from bot.config import Settings
from bot.data.market import ReplayMarketData
from bot.engine import Engine, EngineConfig
from bot.risk.limits import RiskLimits
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
    halt_events: list[dict[str, object]] = field(default_factory=list)


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
    first_tick_at: datetime | None = None,
    strategy_id: str | None = None,
    params: dict[str, int] | None = None,
    limits: RiskLimits | None = None,
    intraday_ticks: Literal["scan", "every_15m"] = "scan",
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
    risk = settings.risk if limits is None else limits  # limits: diagnostic runs only

    first = dataset.start + day + lag
    if first_tick_at is not None:  # holdout run: warm up on history, trade from here
        first = max(first, _floor(first_tick_at, day) + lag)
        eval_start = max(eval_start, _floor(first_tick_at, day))
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
        risk,
        backtest_engine_config(settings, dataset.pair, tf, snap.rules.quote, variant),
        new_cl_ord_id=_deterministic_ids(variant),
    )
    engine.start()

    # Last daily-close tick whose execution window still fits inside the data:
    # close + window <= end  <=>  tick (= close + lag) <= end - window + lag.
    last_signal_tick = dataset.end - window + lag
    completion = timedelta(hours=settings.execution.completion_window_hours)
    hard_end = _floor(last_signal_tick, day) + window + completion + step + lag
    scan = _HaltScan(dataset.frames[exec_tf], step, engine, risk)
    reset_policy = settings.backtest.simulated_halt_reset
    t, last_tick = first, first
    halted = False
    reset_due: datetime | None = None
    while t <= hard_end and (stop_after is None or t <= stop_after):
        clock.advance_to(t)
        last_tick = t
        if reset_due is not None and t >= reset_due:
            engine.reset_halts(t, SIMULATED_RESET_NOTE, rebase_rules=("total_drawdown",))
            reset_due = None
        if engine.tick().halted:
            if reset_policy == "end_run":
                halted = True
                break
            # The operator's manual reset, modelled at the next UTC daily close; no order
            # can be placed until then (the engine keeps rejecting while halted).
            reset_due = _floor(t, day) + day + lag
            t = reset_due
            if t > last_signal_tick and not engine.busy:
                break
            continue
        if engine.busy:
            t = _floor(t, step) + step + lag
        else:
            nxt = _floor(t, day) + day + lag
            # Audit M2 F-1: protected halts are evaluated on equity marked at every 15m close
            # while a position is held: tick at each 15m close where marked equity can reach
            # a halt threshold ("scan"), or at every 15m close ("every_15m", for tests).
            intraday = scan.next_tick(t, nxt, lag, every_15m=intraday_ticks == "every_15m")
            if intraday is not None:
                t = intraday
                continue
            t = nxt
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


SIMULATED_RESET_NOTE = (
    "SIMULATED RESET (backtest): the operator's manual halt reset modelled at the next UTC "
    "daily close"
)


class _HaltScan:
    """Finds the next 15m close at which the held position's marked equity can reach a
    protected halt threshold (daily loss vs day-open equity, total drawdown vs baseline).

    Equity only moves with the mark while a position is held, and the engine marks at the
    mid of the last closed 15m close, so ticking exactly at those candidate closes gives
    the same halts as ticking at every 15m close. The engine itself evaluates the halts
    (``risk.evaluate_halts``); this only chooses when to tick. The candidate test keeps a
    margin above the threshold (spread, tick rounding), so it can only add ticks.
    """

    MARGIN = 0.001

    def __init__(self, frame, step: timedelta, engine: Engine, limits: RiskLimits) -> None:  # noqa: ANN001
        ns = frame["open_at"].dt.tz_convert("UTC").dt.as_unit("ns").astype("int64").to_numpy()
        self._close_ns = ns + int(step.total_seconds()) * 10**9
        self._close = frame["close"].to_numpy(dtype=float)
        self._engine = engine
        self._limits = limits

    def next_tick(
        self, t: datetime, until: datetime, lag: timedelta, every_15m: bool
    ) -> datetime | None:
        store, pair = self._engine.store, self._engine.cfg.pair
        qty = store.position(pair)
        if qty <= 0:
            return None
        lo = int(np.searchsorted(self._close_ns, _ns(t - lag), side="right"))
        hi = int(np.searchsorted(self._close_ns, _ns(until - lag), side="left"))
        if hi <= lo:
            return None
        if every_15m:
            k = lo
        else:
            day_open = store.one(
                "SELECT equity FROM equity_snapshots WHERE is_day_open = 1 "
                "AND substr(at, 1, 10) = ?",
                (t.date().isoformat(),),
            )
            base = store.one("SELECT equity FROM equity_baselines ORDER BY baseline_id DESC")
            if day_open is None or base is None:
                return None
            lim = self._limits
            floor_eq = max(
                (1 - lim.max_daily_loss_fraction) * Decimal(day_open[0]),
                (1 - lim.max_total_drawdown_fraction) * Decimal(base[0]),
            )
            p_star = float((floor_eq - store.cash()) / qty)
            hits = np.flatnonzero(self._close[lo:hi] <= p_star * (1 + self.MARGIN))
            if not len(hits):
                return None
            k = lo + int(hits[0])
        close_at = datetime(1970, 1, 1, tzinfo=t.tzinfo) + timedelta(
            microseconds=int(self._close_ns[k]) // 1000
        )
        return close_at + lag


def _ns(t: datetime) -> int:
    return int((t - datetime(1970, 1, 1, tzinfo=t.tzinfo)).total_seconds() * 10**6) * 1000


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
        fill_settle_timeout=timedelta(seconds=settings.execution.fill_settle_timeout_seconds),
        risk_snapshots=False,  # dashboard data; the backtest report does not use them
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
            "SELECT candle_open_at, evaluated_at, target_fraction, signal_price, outcome, "
            "outcome_reason FROM signals ORDER BY candle_open_at"
        )
    ]
    fills = [
        dict(r)
        for r in store.all(
            "SELECT f.at, f.side, f.qty, f.price, f.fee, f.liquidity, f.reference_price, "
            "o.limit_price FROM fills f JOIN orders o USING (order_id) ORDER BY f.at, f.fill_id"
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
    halt_events = [
        dict(r)
        for r in store.all(
            "SELECT h.rule, h.triggered_at, h.reset_at, h.reason, a.note AS reset_note, "
            "a.rebase_baseline FROM halts h LEFT JOIN operator_actions a "
            "ON a.action_id = h.reset_action_id ORDER BY h.halt_id"
        )
    ]
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
        halt_events=halt_events,
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
