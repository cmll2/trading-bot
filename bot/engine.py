"""Engine: candle -> signal -> sizing -> risk -> order (FR-38, FR-39, AD-1, AD-5, AD-7, AD-28).

The only module that composes the ports (Broker, Clock, MarketData, Store) with the pure
core (strategy, risk, sizing). The same class runs in every mode; only the adapters
change (FR-11). There is no ``if mode`` branch: ``EngineConfig.mode`` is a label, and
``pricing="aggressive"`` exists only for the backtest's CON-06 taker report variant.

One ``tick()``:

1. read the ticker; write the day-open equity snapshot on the first tick of a UTC day;
2. evaluate halts (``risk.evaluate_halts``) and the kill switch BEFORE any submission;
   when halted or killed: cancel the active intent's orders, keep the position, end the
   intent as ``halted`` (AD-12) and return;
3. advance the active intent: ingest fills, re-price, window end (AD-5, AD-28);
4. on a new closed candle of the strategy timeframe: journal the signal and, if the
   target asks for a trade, size it, risk-check it and open an intent (one transaction);
5. snapshot equity.

Every submission passes ``risk.check_order`` and the decision is handed to
``place_order`` (AD-10). Each order row is committed before the broker call (AD-7).
"""

from __future__ import annotations

import json
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from pathlib import Path
from typing import Literal

from bot.broker.base import Broker, MarketRules, OrderRequest, OrderStatus, Ticker
from bot.broker.errors import (
    OrderOutcomeUnknown,
    OrderRejected,
    PostOnlyWouldCross,
    RateLimited,
    TransientReadError,
)
from bot.config import TIMEFRAME_SECONDS
from bot.data.market import MarketData
from bot.logging_setup import redact
from bot.risk.checks import ProposedOrder, RiskContext, RiskDecision, check_order
from bot.risk.halts import HaltContext, evaluate_halts
from bot.risk.kill_switch import read_kill_switch
from bot.risk.limits import RiskLimits
from bot.sizing import (
    NoOrder,
    SizingInput,
    buy_qty,
    completion_qty,
    sell_qty,
    sellable,
)
from bot.store import Store, dec, iso, parse_iso
from bot.strategy.base import Mode, Strategy

log = logging.getLogger("bot.engine")

ACTIVE_INTENT_STATES = ("awaiting_approval", "working", "completing")
LIVE_ORDER_STATES = (
    "created",
    "submitting",
    "open",
    "partially_filled",
    "cancel_requested",
    "unknown",
)

# AD-8 order state machine: any other transition is a bug and raises IllegalTransition.
TRANSITIONS: dict[str, frozenset[str]] = {
    "created": frozenset({"submitting", "not_found"}),
    "submitting": frozenset({"open", "rejected", "unknown"}),
    "unknown": frozenset(
        {"open", "partially_filled", "filled", "cancelled", "rejected", "not_found"}
    ),
    "open": frozenset({"partially_filled", "filled", "cancelled", "cancel_requested"}),
    "partially_filled": frozenset({"partially_filled", "filled", "cancelled", "cancel_requested"}),
    "cancel_requested": frozenset({"cancelled", "filled"}),
}


UNKNOWN_POLL = timedelta(seconds=10)  # AD-8 find_order cadence for an unknown order
RETENTION_DAYS = 30  # api_calls, heartbeats, risk_snapshots (architecture "Deferred")
READ_RETRIES = 3  # AD-8: a failed read is retried at most 3 times, then logged
_UNSET = object()
_PENDING = object()  # an operator action that must wait for a later tick


class IllegalTransition(RuntimeError):
    """An order state change not allowed by AD-8."""


class EngineError(RuntimeError):
    """The engine cannot continue safely."""


class ReconcileMismatch(EngineError):
    """Store and broker disagree (AD-9): halted with ``reconcile_mismatch``; exit non-zero."""


class FutureCandleError(EngineError):
    """The market-data adapter served a candle that is not closed at the evaluation time:
    a look-ahead bug in the adapter (audit M2 F-2). Never trade on it."""


@dataclass(frozen=True)
class EngineConfig:
    mode: Mode  # label only (AD-1)
    pair: str
    timeframe: str  # strategy timeframe
    window: timedelta  # execution window after the signal candle's close (AD-5)
    reprice_interval: timedelta
    completion_window: timedelta
    approval: Literal["manual", "autonomous"]
    slippage_bps: Decimal
    quote_is_fiat: bool
    git_commit: str
    git_dirty: bool
    config_hash: str
    limits_hash: str
    pricing: Literal["passive", "aggressive"] = "passive"
    fill_settle_timeout: timedelta = timedelta(seconds=60)  # AD-27
    unknown_grace: timedelta = timedelta(seconds=60)  # AD-8: unknown -> not_found after this
    exec_timeframe: str = "15m"  # AD-6 execution candles (exchange-halt detection, F-5)
    health_records: bool = True  # risk_snapshots + priced_from rows (the backtest: off)


@dataclass(frozen=True)
class TickResult:
    halted: bool
    signal_evaluated: bool


def _default_cl_ord_id() -> str:
    return uuid.uuid4().hex


class Engine:
    def __init__(
        self,
        broker: Broker,
        clock,  # noqa: ANN001 - Clock port
        market_data: MarketData,
        store: Store,
        strategy: Strategy,
        limits: RiskLimits,
        config: EngineConfig,
        *,
        kill_switch: Callable[[], bool] = lambda: False,
        new_cl_ord_id: Callable[[], str] = _default_cl_ord_id,
        kill_switch_path: Path | None = None,
    ) -> None:
        if strategy.timeframe != config.timeframe:
            raise EngineError("strategy timeframe and engine timeframe differ")
        self.broker = broker
        self.clock = clock
        self.md = market_data
        self.store = store
        self.strategy = strategy
        self.limits = limits
        self.cfg = config
        self._kill_switch = kill_switch
        self._kill_path = kill_switch_path  # the engine is the only deleter (AD-12)
        self._new_id = new_cl_ord_id
        self._interval = timedelta(seconds=TIMEFRAME_SECONDS[config.timeframe])
        self._rules: MarketRules | None = None
        self.run_id: int | None = None
        self._unsettled_since: dict[int, datetime] = {}
        self._cancel_sent_at: dict[int, datetime] = {}
        self._last_ticker_ok: datetime | None = None
        self._priced_ticker: Ticker | None = None

    # --- lifecycle ----------------------------------------------------------------------

    def start(self, pid: int = 0) -> None:
        """Open a run; write the write-once account baseline on first start (AD-26)."""
        now = self.clock.now()
        self._rules = self.broker.load_market(self.cfg.pair)
        fees = self.broker.get_fee_rates(self.cfg.pair)
        self._fees = fees
        with self.store.transaction():
            if self.store.get_meta("initial_quote") is None:
                balances = self.broker.get_balance()
                quote = balances.get(self._rules.quote)
                base = balances.get(self._rules.base)
                initial_quote = quote.free + quote.locked if quote else Decimal(0)
                initial_base = base.free + base.locked if base else Decimal(0)
                self.store.init_account(
                    initial_quote=initial_quote,
                    initial_base=initial_base,
                    at=now,
                    mode=self.cfg.mode,
                    strategy_id=self.strategy.id,
                    exchange=self.broker.name,
                    pair=self.cfg.pair,
                    quote_ccy=self._rules.quote,
                )
            self.run_id = self.store.insert(
                "runs",
                started_at=iso(now),
                mode=self.cfg.mode,
                strategy_id=self.strategy.id,
                git_commit=self.cfg.git_commit,
                git_dirty=int(self.cfg.git_dirty),
                config_hash=self.cfg.config_hash,
                limits_hash=self.cfg.limits_hash,
                pid=pid,
            )

    def stop(self, reason: str) -> None:
        if self.run_id is not None:
            self.store.update(
                "runs",
                "run_id",
                self.run_id,
                stopped_at=iso(self.clock.now()),
                stop_reason=reason,
            )

    @property
    def rules(self) -> MarketRules:
        if self._rules is None:
            raise EngineError("engine not started")
        return self._rules

    @property
    def busy(self) -> bool:
        """True while an intent is active (the backtest then ticks every execution candle)."""
        return self._active_intent() is not None

    # --- tick ---------------------------------------------------------------------------

    def tick(self) -> TickResult:
        if self.run_id is None:
            raise EngineError("call start() before tick()")
        now = self.clock.now()
        try:
            ticker = self.broker.get_ticker(self.cfg.pair)
        except (TransientReadError, RateLimited) as exc:
            self._error(now, "ticker", exc)
            # AD-12 needs no ticker: apply operator actions (a flatten waits for a ticker)
            # and stop on an engaged switch or a recorded halt even while blind.
            self._consume_actions(now, ticker=None)
            halts, killed = self._active_halts(), self._kill_switch()
            self._log_kill_state(now, killed)
            if halts or killed:
                self._sweep(now, "kill switch" if killed else f"halt: {', '.join(halts)}")
            self._own_feed_blind(now)
            return TickResult(halted=bool(halts or killed), signal_evaluated=False)
        self._last_ticker_ok = ticker.ts
        mid = (ticker.bid + ticker.ask) / 2
        first_of_day = self._day_open(now, mid)
        self._consume_actions(now, ticker=ticker)
        self._sync_stray_orders(now)

        # AD-12: kill switch and halts are evaluated BEFORE any submission.
        equity = self.store.equity_at(now, mid, self.cfg.pair)
        self._evaluate_halts(now, equity)
        halts = self._active_halts()
        killed = self._kill_switch()
        self._log_kill_state(now, killed)
        if halts or killed:
            self._sweep(now, "kill switch" if killed else f"halt: {', '.join(halts)}")
            self._advance_flatten(now, ticker)  # the only sell while stopped (AD-25)
            if not first_of_day:
                self._snapshot(now, mid, False)
            self._risk_snapshot(now, ticker)
            return TickResult(halted=True, signal_evaluated=False)

        # A pending signal left by a crash is re-evaluated here, after the halts, the
        # kill switch and the startup reconciliation, never inside recover() (review).
        self._resume_pending_signals(now, ticker)
        if not self._pending_flatten():  # a flatten waiting on a cancel freezes the intent
            self._advance_intent(now, ticker)
        evaluated = self._maybe_signal(now, ticker)
        if not first_of_day:
            self._snapshot(now, mid, False)
        self._risk_snapshot(now, ticker)
        return TickResult(halted=False, signal_evaluated=evaluated)

    # --- equity, halts ------------------------------------------------------------------

    def _day_open(self, now: datetime, mid: Decimal) -> bool:
        day = iso(now)[:10]
        if self.store.one(
            "SELECT 1 FROM equity_snapshots WHERE is_day_open = 1 AND substr(at, 1, 10) = ?",
            (day,),
        ):
            return False
        with self.store.transaction():
            if self.store.one("SELECT 1 FROM equity_baselines") is None:
                self.store.insert(
                    "equity_baselines",
                    at=iso(now),
                    equity=dec(self.store.equity_at(now, mid, self.cfg.pair)),
                    reason="start baseline",
                )
            self._snapshot(now, mid, True)
        return True

    def _snapshot(self, now: datetime, mid: Decimal, day_open: bool) -> None:
        if self.store.get_meta("buy_hold_start_price") is None:
            self.store.set_meta_once("buy_hold_start_price", dec(mid))
        start_px = Decimal(self.store.get_meta("buy_hold_start_price") or mid)
        initial = Decimal(self.store.get_meta("initial_quote") or 0)
        initial += Decimal(self.store.get_meta("initial_base") or 0) * start_px
        cash = self.store.cash(until=now)
        base = self.store.position(self.cfg.pair, until=now)
        self.store.insert(
            "equity_snapshots",
            at=iso(now),
            equity=dec(cash + base * mid),
            cash=dec(cash),
            base_qty=dec(base),
            mark_price=dec(mid),
            buy_hold_equity=dec(initial * mid / start_px),
            is_day_open=int(day_open),
        )

    def _risk_snapshot(self, now: datetime, ticker: Ticker) -> None:
        """Per-tick risk context and limit usage for the dashboard (AD-11, AD-17: the
        dashboard reads this and never recomputes risk). Off in the backtest (speed)."""
        if not self.cfg.health_records:
            return
        intent = self._active_intent()
        reference = Decimal(intent["reference_price"]) if intent else (ticker.bid + ticker.ask) / 2
        ctx = self._risk_context(now, ticker, reference, intent["intent_id"] if intent else None)
        lim = self.limits
        day_open = self._day_open_equity(now)
        baseline = self._baseline()
        cap = min(lim.max_position_fraction * ctx.equity, lim.max_position_abs_quote)
        usage = {
            "orders_today": [ctx.intents_today, lim.max_order_intents_per_day],
            "submissions_today": [ctx.submissions_today, lim.max_exchange_submissions_per_day],
            "intent_submissions": [ctx.intent_submissions, lim.max_submissions_per_intent],
            "position_quote": [str((ctx.position_qty + ctx.resting_buy_qty) * ctx.mid), str(cap)],
            "daily_loss": [str(ctx.equity), str((1 - lim.max_daily_loss_fraction) * day_open)],
            "total_drawdown": [
                str(ctx.equity),
                str((1 - lim.max_total_drawdown_fraction) * baseline),
            ],
            "ticker_age_s": [(now - ctx.ticker_ts).total_seconds(), lim.stale_ticker_seconds],
            "candle_age_s": [
                None
                if ctx.last_candle_open_at is None
                else (now - ctx.last_candle_open_at).total_seconds(),
                lim.stale_candle_intervals * ctx.candle_interval.total_seconds(),
            ],
            "price_vs_reference": [
                str(abs(ctx.mid - reference) / reference),
                str(lim.price_sanity_fraction),
            ],
        }
        context = {
            "equity": str(ctx.equity),
            "day_open_equity": str(day_open),
            "baseline_equity": str(baseline),
            "position_qty": str(ctx.position_qty),
            "resting_buy_qty": str(ctx.resting_buy_qty),
            "mid": str(ctx.mid),
            "reference_price": str(reference),
            "active_halts": list(ctx.active_halts),
            "kill_switch_engaged": ctx.kill_switch_engaged,
            "market_status": ctx.market_status,
            "last_candle_synthetic": ctx.last_candle_synthetic,
            "limits_hash": self.cfg.limits_hash,
        }
        self.store.execute(
            "INSERT OR REPLACE INTO risk_snapshots (at, context_json, usage_json) VALUES (?, ?, ?)",
            (iso(now), json.dumps(context, sort_keys=True), json.dumps(usage, sort_keys=True)),
        )

    def housekeeping(self, now: datetime, backups_dir: Path, keep: int = 30) -> Path:
        """Daily: prune health tables to 30 days and back the store up (architecture §2:
        the store holds the only full copy of the tax ledger), keeping ``keep`` copies."""
        cutoff = iso(now - timedelta(days=RETENTION_DAYS))
        with self.store.transaction():
            for table in ("api_calls", "heartbeats", "risk_snapshots"):
                self.store.execute(f"DELETE FROM {table} WHERE at < ?", (cutoff,))  # noqa: S608
        stem = f"{self.cfg.mode}-{self.strategy.id}"
        target = Path(backups_dir) / f"{stem}-{now.strftime('%Y%m%d')}.sqlite"
        self.store.backup(target)
        copies = sorted(Path(backups_dir).glob(f"{stem}-????????.sqlite"))
        for old in copies[:-keep]:
            old.unlink(missing_ok=True)
        log.info("daily housekeeping: pruned before %s, backup %s", cutoff, target)
        return target

    def _day_open_equity(self, now: datetime) -> Decimal:
        row = self.store.one(
            "SELECT equity FROM equity_snapshots WHERE is_day_open = 1 AND substr(at, 1, 10) = ?",
            (iso(now)[:10],),
        )
        if row is None:
            raise EngineError("no day-open equity")
        return Decimal(row["equity"])

    def _baseline(self) -> Decimal:
        row = self.store.one("SELECT equity FROM equity_baselines ORDER BY baseline_id DESC")
        if row is None:
            raise EngineError("no equity baseline")
        return Decimal(row["equity"])

    def _evaluate_halts(self, now: datetime, equity: Decimal) -> None:
        ctx = HaltContext(equity, self._day_open_equity(now), self._baseline())
        for trigger in evaluate_halts(ctx, self.limits):
            with self.store.transaction():
                cur = self.store.execute(
                    "INSERT INTO halts (rule, triggered_at, reason) VALUES (?, ?, ?) "
                    "ON CONFLICT DO NOTHING",
                    (trigger.rule, iso(now), trigger.reason),
                )
                if cur.rowcount:
                    self._risk_event(now, "halt", trigger.rule, None, trigger.reason, {})

    def reset_halts(self, now: datetime, note: str, rebase_rules: tuple[str, ...]) -> list[str]:
        """Apply a halt reset (AD-12): the operator's ``bot reset-halt`` in dry-run/live
        (M3 consumes it from ``operator_actions``), or the backtest's SIMULATED RESET.

        Writes one consumed ``operator_actions`` row, closes every active halt, writes a
        ``halt_reset`` risk event, and, when an active halt's rule is in ``rebase_rules``,
        appends a new drawdown baseline at the current equity (Q-6 ``--rebase-baseline``).
        Returns the rules reset."""
        rows = self.store.all("SELECT halt_id, rule FROM halts WHERE reset_at IS NULL")
        if not rows:
            return []
        rules = [r["rule"] for r in rows]
        rebase = any(r in rebase_rules for r in rules)
        ticker = self.broker.get_ticker(self.cfg.pair)
        mid = (ticker.bid + ticker.ask) / 2
        with self.store.transaction():
            action = self.store.insert(
                "operator_actions",
                at=iso(now),
                kind="reset_halt",
                target_id=",".join(rules),
                note=note,
                rebase_baseline=int(rebase),
                consumed_at=iso(now),
                result="applied",
            )
            self._apply_reset(now, rows, action, note, rebase, mid)
        return rules

    def _apply_reset(
        self, now: datetime, rows: list, action_id: int, note: str, rebase: bool, mid: Decimal
    ) -> None:
        """Close the given halts with the action that reset them, write ``halt_reset``
        and, when asked, append a new drawdown baseline at the current equity (Q-6). The
        only writer of ``halts`` resets (AD-17); used by the CLI path and the backtest."""
        rules = [r["rule"] for r in rows]
        for r in rows:
            self.store.update(
                "halts", "halt_id", r["halt_id"], reset_at=iso(now), reset_action_id=action_id
            )
        self._risk_event(now, "halt_reset", ",".join(rules), None, note, {"rebase": rebase})
        if rebase:
            self.store.insert(
                "equity_baselines",
                at=iso(now),
                equity=dec(self.store.equity_at(now, mid, self.cfg.pair)),
                reason=note,
                action_id=action_id,
            )

    def _active_halts(self) -> tuple[str, ...]:
        rows = self.store.all("SELECT rule FROM halts WHERE reset_at IS NULL ORDER BY halt_id")
        return tuple(r["rule"] for r in rows)

    def _sweep(self, now: datetime, why: str) -> None:
        """AD-12: cancel the resting order of the active NON-flatten intent, ingest its
        final fills, end the intent ``halted`` (outcome ``halted``) and keep the position:
        no sell is ever placed automatically. A flatten intent is left to run."""
        intent = self._active_intent()
        if intent is None or intent["is_flatten"]:
            return
        self._cancel_live(intent, now)
        self._finish(intent["intent_id"], now, "halted", "halted", why)
        log.warning(
            "intent %s halted (%s): orders cancelled, position kept", intent["intent_id"], why
        )

    def _advance_flatten(self, now: datetime, ticker: Ticker) -> None:
        intent = self._active_intent()
        if intent is not None and intent["is_flatten"]:
            self._advance_intent(now, ticker)

    def _log_kill_state(self, now: datetime, engaged: bool) -> None:
        """Write ``kill_on``/``kill_off`` only when the observed state differs from the
        last one logged (AD-12)."""
        last = self.store.one(
            "SELECT kind FROM risk_events WHERE kind IN ('kill_on', 'kill_off') "
            "ORDER BY event_id DESC"
        )
        last_engaged = last is not None and last["kind"] == "kill_on"
        if engaged == last_engaged:
            return
        if engaged:
            state = read_kill_switch(self._kill_path) if self._kill_path else None
            source = state.source if state else "file"
            self._risk_event(
                now, "kill_on", "kill_switch", None,
                f"kill switch engaged (source={source})", {"path": str(self._kill_path)},
            )  # fmt: skip
            log.error("KILL SWITCH ENGAGED (source=%s): no new orders", source)
        else:
            self._risk_event(now, "kill_off", "kill_switch", None, "kill switch disengaged", {})
            log.warning("kill switch disengaged")

    def _sync_stray_orders(self, now: datetime) -> None:
        """Live orders whose intent is no longer active (a halt ended the intent while a
        cancel was still pending) are re-synced so their final fills are never lost."""
        marks = ",".join("?" for _ in LIVE_ORDER_STATES)
        active = ",".join("?" for _ in ACTIVE_INTENT_STATES)
        rows = self.store.all(
            f"SELECT o.* FROM orders o JOIN intents i USING (intent_id) "  # noqa: S608
            f"WHERE o.state IN ({marks}) AND i.state NOT IN ({active})",
            (*LIVE_ORDER_STATES, *ACTIVE_INTENT_STATES),
        )
        for order in rows:
            intent = self._intent(order["intent_id"])
            self._ingest_fills(intent, now)
            fresh = self.store.one("SELECT * FROM orders WHERE order_id = ?", (order["order_id"],))
            if fresh["state"] in ("open", "partially_filled"):
                self._transition(fresh["order_id"], "cancel_requested", now)
                fresh = self.store.one(
                    "SELECT * FROM orders WHERE order_id = ?", (order["order_id"],)
                )
            if fresh["state"] == "cancel_requested":
                try:
                    self.broker.cancel_order(self.cfg.pair, fresh["cl_ord_id"])
                except (OrderOutcomeUnknown, TransientReadError, RateLimited, OrderRejected) as exc:
                    self.error(now, "cancel", exc)
                self._ingest_fills(intent, now)
            fresh = self.store.one("SELECT * FROM orders WHERE order_id = ?", (order["order_id"],))
            if fresh["state"] == "unknown":
                self._resolve_unknown(fresh)
            else:
                self._sync_order(fresh, now)

    # --- journal helpers ----------------------------------------------------------------

    def _error(self, now: datetime, component: str, exc: BaseException) -> None:
        self.error(now, component, exc)

    def error(
        self, now: datetime, component: str, exc: BaseException, tb: str | None = None
    ) -> None:
        """Record an error, redacted before insert (AD-22)."""
        log.warning("%s error: %s: %s", component, type(exc).__name__, redact(str(exc)))
        self.store.insert(
            "errors",
            at=iso(now),
            component=component,
            error_type=type(exc).__name__,
            message=redact(str(exc))[:500],
            traceback=None if tb is None else redact(tb)[:20000],
        )

    def heartbeat(self, now: datetime, loop_state: str) -> None:
        """One heartbeat row per loop iteration (NFR-05); written by the runtime loop."""
        if self.run_id is None:
            raise EngineError("call start() before heartbeat()")
        self.store.execute(
            "INSERT OR IGNORE INTO heartbeats (run_id, at, loop_state) VALUES (?, ?, ?)",
            (self.run_id, iso(now), loop_state),
        )

    def raise_halt(self, now: datetime, rule: str, reason: str, kind: str = "halt") -> bool:
        """Insert an active halt for ``rule`` (kept until ``bot reset-halt``) and write a
        risk event. Returns True when the halt is new."""
        with self.store.transaction():
            cur = self.store.execute(
                "INSERT INTO halts (rule, triggered_at, reason) VALUES (?, ?, ?) "
                "ON CONFLICT DO NOTHING",
                (rule, iso(now), reason),
            )
            self._risk_event(now, kind, rule, None, reason, {})
        if cur.rowcount:
            log.error("HALT %s: %s", rule, reason)
        return bool(cur.rowcount)

    def fatal(self, now: datetime, reason: str) -> None:
        """Fatal exit path (AD-29): halt with ``fatal_error`` and cancel the bot's known
        resting orders, best effort. The position is kept."""
        self.raise_halt(now, "fatal_error", reason)
        self.cancel_all_resting(now)

    def cancel_all_resting(self, now: datetime) -> None:
        """Best-effort cancel of every resting order the store knows (fatal exits and
        reconciliation mismatches). Errors are recorded, never raised."""
        rows = self.store.all(
            "SELECT * FROM orders "
            "WHERE state IN ('open', 'partially_filled', 'cancel_requested', 'unknown')"
        )
        for order in rows:
            try:
                if order["state"] in ("open", "partially_filled"):
                    self._transition(order["order_id"], "cancel_requested", now)
                # An unknown order may be resting: cancelling by cl_ord_id is safe.
                self.broker.cancel_order(self.cfg.pair, order["cl_ord_id"])
            except Exception as exc:  # noqa: BLE001 - best effort on a fatal path
                self.error(now, "cancel_all_resting", exc)

    def recover(self, now: datetime) -> None:
        """AD-8 startup sequence after any start, crash included (steps 2 to 7; the lock
        is step 1, reconciliation step 8, and the next tick continues or ends each intent,
        step 9).

        - pending ``reset_halt`` operator actions are applied first;
        - ``created`` orders were never sent: ``not_found``;
        - ``submitting`` orders may exist: ``unknown``, then resolved with ``find_order``
          (open AND closed) every 10 s up to ``unknown_grace``; only ``not_found`` frees
          the intent for a new attempt with a new ``cl_ord_id``;
        - every other open-like order is re-synced after its fills are ingested (once
          each, keyed by exchange trade id, AD-27);
        - a ``pending`` signal without an intent is re-evaluated if its window is still
          open, else ends ``not_filled`` / ``restart_window_passed`` (AD-28).
        """
        self._consume_actions(now, kinds=("reset_halt",))
        for order in self.store.all("SELECT * FROM orders WHERE state = 'created'"):
            self._transition(order["order_id"], "not_found", now, closed_at=iso(now))
            log.warning("recover: order %s was never sent: not_found", order["cl_ord_id"])
        for order in self.store.all("SELECT * FROM orders WHERE state = 'submitting'"):
            self._transition(order["order_id"], "unknown", now)
            log.warning("recover: order %s outcome unknown: looking it up", order["cl_ord_id"])
        marks = ",".join("?" for _ in LIVE_ORDER_STATES)
        intents = self.store.all(
            f"SELECT DISTINCT i.* FROM intents i JOIN orders o USING (intent_id) "  # noqa: S608
            f"WHERE o.state IN ({marks})",
            LIVE_ORDER_STATES,
        )
        for intent in intents:
            self._ingest_fills(intent, now)
            order = self._live_order(intent["intent_id"])
            if order is None:
                continue
            if order["state"] == "unknown":
                self._resolve_unknown(order)
            else:
                self._sync_order(order, self.clock.now())
        self._resume_pending_signals(self.clock.now(), None)

    def _resume_pending_signals(self, now: datetime, ticker: Ticker | None) -> None:
        """AD-28: a ``pending`` signal without an intent (a crash between journaling and
        deciding) ends ``not_filled`` / ``restart_window_passed`` if its window passed; with
        a ticker (on a tick, after halts and reconciliation) an open one is re-evaluated
        through the same path as a fresh signal."""
        rows = self.store.all(
            "SELECT s.* FROM signals s LEFT JOIN intents i ON i.signal_id = s.signal_id "
            "WHERE s.outcome = 'pending' AND i.intent_id IS NULL ORDER BY s.candle_open_at"
        )
        for sig in rows:
            open_at = parse_iso(sig["candle_open_at"])
            window_end = open_at + self._interval + self.cfg.window
            if now >= window_end:
                with self.store.transaction():
                    self._set_outcome(sig["signal_id"], "not_filled", "restart_window_passed")
                continue
            if ticker is None:
                continue
            # Network reads before the AD-28 transaction, never inside it.
            self.md.closed_candles(self.cfg.pair, self.cfg.timeframe, limit=1)
            self._rules = self.broker.load_market(self.cfg.pair)
            with self.store.transaction():
                submit = self._decide_and_open(
                    sig["signal_id"],
                    Decimal(sig["target_fraction"]),
                    Decimal(sig["signal_price"]),
                    window_end,
                    now,
                    ticker,
                )
            self._submit_first(submit, now, ticker)

    def _resolve_unknown(self, order) -> str:  # noqa: ANN001 - sqlite3.Row
        """AD-8: look an ``unknown`` order up (open AND closed) every 10 s until it is
        found or ``unknown_grace`` has passed since it became unknown; never resend it."""
        since_row = self.store.one(
            "SELECT at FROM order_events WHERE order_id = ? AND to_state = 'unknown' "
            "ORDER BY event_id DESC",
            (order["order_id"],),
        )
        since = parse_iso(since_row["at"]) if since_row else self.clock.now()
        while True:
            now = self.clock.now()
            status = self._read(
                "find_order", self.broker.find_order, self.cfg.pair, order["cl_ord_id"]
            )
            if status is not None or now - since >= self.cfg.unknown_grace:
                if status is not None:
                    self._ingest_fills(self._intent(order["intent_id"]), now)
                fresh = self.store.one(
                    "SELECT * FROM orders WHERE order_id = ?", (order["order_id"],)
                )
                return self._sync_order(fresh, now, status=status, resolved=True)
            self.clock.sleep_until(min(now + UNKNOWN_POLL, since + self.cfg.unknown_grace))

    def reconcile(self, now: datetime) -> None:
        """AD-9: compare the store with the broker (the ``paper_*`` tables in dry-run) and
        halt on any disagreement.

        - open orders: the broker's open orders on the pair must be the store's open-like
          orders, matched by ``cl_ord_id``; an order the bot did not create is a mismatch,
          and so is a store order the store thinks is resting that the broker does not
          list (``cancel_requested`` and ``unknown`` orders may legitimately be gone);
        - base balance: broker free + locked must EXACTLY equal the derived position;
        - quote balance: broker free + locked must be >= the derived cash (A-1);
        - fills: every broker fill since the account start must match a store fill by
          exchange trade id, and every store fill must exist at the broker.

        On a mismatch: a ``reconcile_mismatch`` risk event with both sides, a
        ``halts(reconcile_mismatch)`` row, both sides logged, the bot's own resting orders
        cancelled (best effort), then ``ReconcileMismatch`` is raised so the process exits
        non-zero (the runtime records ``stop_reason``).

        Before comparing, every live order's fills are ingested and its state synced, so
        the bot's own legitimate fills are never reported; a difference is re-checked once
        after another sync (fills may land between two broker reads) before it counts."""
        self._sync_all_live(now)
        problems, summary = self._reconcile_problems(now)
        if problems:
            self._sync_all_live(self.clock.now())
            problems, summary = self._reconcile_problems(now)
        if not problems:
            log.info("reconciliation OK: %s", summary)
            return
        reason = "; ".join(f"{what} {detail}" for what, detail in problems)
        with self.store.transaction():
            for what, detail in problems:
                self._risk_event(
                    now, "reconcile_mismatch", "reconcile_mismatch", None, what, detail
                )
            self.store.execute(
                "INSERT INTO halts (rule, triggered_at, reason) VALUES (?, ?, ?) "
                "ON CONFLICT DO NOTHING",
                ("reconcile_mismatch", iso(now), reason[:1000]),
            )
        log.error("RECONCILIATION MISMATCH: %s", reason)
        self.cancel_all_resting(now)
        raise ReconcileMismatch(reason)

    def _sync_all_live(self, now: datetime) -> None:
        marks = ",".join("?" for _ in LIVE_ORDER_STATES)
        for order in self.store.all(
            f"SELECT * FROM orders WHERE state IN ({marks})",  # noqa: S608
            LIVE_ORDER_STATES,
        ):
            self._ingest_fills(self._intent(order["intent_id"]), now)
            fresh = self.store.one("SELECT * FROM orders WHERE order_id = ?", (order["order_id"],))
            if fresh["state"] in ("open", "partially_filled", "cancel_requested"):
                self._sync_order(fresh, now)

    def _reconcile_problems(self, now: datetime) -> tuple[list[tuple[str, dict]], str]:
        pair = self.cfg.pair
        problems: list[tuple[str, dict[str, object]]] = []
        exch_open = {
            o.cl_ord_id: o for o in self._read("get_open_orders", self.broker.get_open_orders, pair)
        }
        rows = self.store.all(
            "SELECT cl_ord_id, state FROM orders "
            "WHERE state IN ('open', 'partially_filled', 'cancel_requested', 'unknown')"
        )
        store_open = {r["cl_ord_id"]: r["state"] for r in rows}
        for cl in sorted(set(exch_open) - set(store_open)):
            problems.append(("open order at the broker unknown to the store", {"cl_ord_id": cl}))
        for cl, state in sorted(store_open.items()):
            if state in ("open", "partially_filled") and cl not in exch_open:
                problems.append(
                    (
                        "store order resting but not open at the broker",
                        {"cl_ord_id": cl, "state": state},
                    )
                )
        balances = self._read("get_balance", self.broker.get_balance)
        base_bal = balances.get(self.rules.base)
        quote_bal = balances.get(self.rules.quote)
        base = base_bal.free + base_bal.locked if base_bal else Decimal(0)
        quote = quote_bal.free + quote_bal.locked if quote_bal else Decimal(0)
        derived_base = self.store.position(pair)
        derived_cash = self.store.cash()
        if base != derived_base:
            problems.append(
                ("base balance differs from the derived position",
                 {"broker": str(base), "store": str(derived_base)})
            )  # fmt: skip
        if quote < derived_cash:
            problems.append(
                ("quote balance below the derived cash",
                 {"broker": str(quote), "store": str(derived_cash)})
            )  # fmt: skip
        since = parse_iso(self.store.get_meta("initial_at") or iso(now))
        exch_fills = {
            f.exchange_trade_id: f
            for f in self._read("get_fills", self.broker.get_fills, pair, since)
        }
        store_fills = {
            r["exchange_trade_id"]
            for r in self.store.all(
                "SELECT exchange_trade_id FROM fills WHERE exchange = ?", (self.broker.name,)
            )
        }
        for tid in sorted(set(exch_fills) - store_fills):
            f = exch_fills[tid]
            problems.append(
                ("broker fill matches no store fill",
                 {"trade_id": tid, "cl_ord_id": f.cl_ord_id, "qty": str(f.qty)})
            )  # fmt: skip
        for tid in sorted(store_fills - set(exch_fills)):
            problems.append(("store fill unknown to the broker", {"trade_id": tid}))
        summary = (
            f"{len(exch_open)} open orders, base {base}, quote {quote} >= cash {derived_cash}, "
            f"{len(exch_fills)} fills"
        )
        return problems, summary

    def _consume_actions(
        self, now: datetime, kinds: tuple[str, ...] | None = None, ticker: Ticker | None = None
    ) -> None:
        """Apply pending ``operator_actions`` once each, oldest first (AD-12, AD-16,
        AD-25): the CLI only inserts them, the engine sets ``consumed_at`` and ``result``.

        Each action has an optional ``_prepare_<kind>`` step (broker calls, outside any
        transaction; returning ``_PENDING`` leaves the action for the next tick) and an
        ``_apply_<kind>`` step whose store writes commit in ONE transaction with
        ``consumed_at``, so a crash can never apply a command twice (review finding)."""
        rows = self.store.all(
            "SELECT * FROM operator_actions WHERE consumed_at IS NULL ORDER BY action_id"
        )
        for action in rows:
            if kinds is not None and action["kind"] not in kinds:
                continue
            prepare = getattr(self, f"_prepare_{action['kind']}", None)
            apply = getattr(self, f"_apply_{action['kind']}", None)
            try:
                prepared = prepare(now, action, ticker) if prepare else None
                if prepared is _PENDING:
                    continue
                with self.store.transaction():
                    if apply is None:
                        result = f"ignored: {action['kind']} is not supported"
                    else:
                        result = apply(now, action, prepared)
                    self.store.execute(
                        "UPDATE operator_actions SET consumed_at = ?, result = ? "
                        "WHERE action_id = ? AND consumed_at IS NULL",
                        (iso(now), result, action["action_id"]),
                    )
            except OSError as exc:  # e.g. the kill-switch file is locked on Windows
                self.error(now, f"operator_action_{action['kind']}", exc)
                continue  # rolled back: retried on the next tick
            log.warning(
                "operator action %s %s (%s) consumed: %s",
                action["action_id"], action["kind"], action["note"], result,
            )  # fmt: skip

    def _pending_flatten(self) -> bool:
        return (
            self.store.one(
                "SELECT 1 FROM operator_actions WHERE kind = 'flatten' AND consumed_at IS NULL"
            )
            is not None
        )

    # reset_halt ------------------------------------------------------------------------

    def _halts_for(self, action) -> list:  # noqa: ANN001
        """Active halts the action may reset: matching rule, and triggered no later than
        the action itself (a halt raised after the command was issued is never reset by
        it, review finding)."""
        rule = action["target_id"] or "all"
        rows = self.store.all(
            "SELECT halt_id, rule FROM halts WHERE reset_at IS NULL AND triggered_at <= ?",
            (action["at"],),
        )
        return [r for r in rows if rule == "all" or r["rule"] == rule]

    def _prepare_reset_halt(self, now: datetime, action, ticker: Ticker | None) -> object:  # noqa: ANN001
        rows = self._halts_for(action)
        rebase = bool(action["rebase_baseline"]) and any(
            r["rule"] == "total_drawdown" for r in rows
        )
        if not rebase:
            return None
        if ticker is None:
            try:
                ticker = self._read("get_ticker", self.broker.get_ticker, self.cfg.pair)
            except (TransientReadError, RateLimited) as exc:
                self.error(now, "reset_halt", exc)
                return _PENDING
        return (ticker.bid + ticker.ask) / 2

    def _apply_reset_halt(self, now: datetime, action, mid: object) -> str:  # noqa: ANN001
        """``bot reset-halt <rule|all> --note [--rebase-baseline]`` (AD-12, Q-6): manual
        only; the drawdown baseline moves only with ``--rebase-baseline`` and only when a
        ``total_drawdown`` halt is among those reset (rebase_rules=("total_drawdown",))."""
        rows = self._halts_for(action)
        if not rows:
            return (
                f"no active halt {action['target_id'] or 'all'} (raised before it): nothing reset"
            )
        rebase = isinstance(mid, Decimal) and any(r["rule"] == "total_drawdown" for r in rows)
        self._apply_reset(
            now, rows, action["action_id"], action["note"], rebase, mid if rebase else Decimal(0)
        )
        rules = ",".join(r["rule"] for r in rows)
        return f"reset {rules}" + (" with a new drawdown baseline" if rebase else "")

    # flatten ---------------------------------------------------------------------------

    def _prepare_flatten(self, now: datetime, action, ticker: Ticker | None) -> object:  # noqa: ANN001
        """Broker side of ``bot flatten``: cancel the active intent's live order first."""
        if ticker is None:
            return _PENDING  # applied on a tick, with a fresh ticker
        active = self._active_intent()
        if active is not None and not active["is_flatten"]:
            self._cancel_live(active, now)
            if self._live_order(active["intent_id"]) is not None:
                return _PENDING  # cancel not confirmed yet: retried on the next tick
        return ticker

    def _apply_flatten(self, now: datetime, action, ticker: object) -> str:  # noqa: ANN001
        """``bot flatten --note`` (AD-25): end any active intent (``skipped_by_operator``),
        then open a flatten intent selling the full base, referenced to the mid now. Its
        submissions are exempt from orders/day, stale_candle and halt/kill, never from
        stale_ticker, price_sanity or minimums (protected ``check_order``)."""
        assert isinstance(ticker, Ticker)
        active = self._active_intent()
        if active is not None and active["is_flatten"]:
            return "ignored: a flatten is already active"
        if active is not None:
            why = f"flatten requested (operator action {action['action_id']})"
            self._finish(active["intent_id"], now, "cancelled", "skipped_by_operator", why)
        mid = (ticker.bid + ticker.ask) / 2
        position = self.store.position(self.cfg.pair)
        if not self._sellable_by_minimums(position, mid):
            return f"nothing to flatten: position {position} below the exchange minimums"
        intent_id = self.store.insert(
            "intents",
            source_action_id=action["action_id"],
            is_flatten=1,
            pair=self.cfg.pair,
            side="sell",
            reference_price=dec(mid),
            target_qty=dec(position),
            state="working",
            approval_mode=self.cfg.approval,
            window_end_at=iso(now + self.cfg.window),
            created_at=iso(now),
            updated_at=iso(now),
        )
        log.warning("flatten intent %s: sell %s %s", intent_id, position, self.cfg.pair)
        return f"flatten intent {intent_id} opened: sell {position}"

    # approve / reject ------------------------------------------------------------------

    def _awaiting(self, action):  # noqa: ANN001, ANN202 - sqlite3.Row | None
        try:
            intent_id = int(action["target_id"])
        except (TypeError, ValueError):
            return None
        intent = self._intent(intent_id)
        if intent is None or intent["state"] != "awaiting_approval":
            return None
        return intent

    def _expire_if_due(self, intent, now: datetime) -> bool:  # noqa: ANN001
        """AD-16: past its deadline (the window end) an unapproved intent expires, with
        signal outcome ``skipped_by_operator``."""
        deadline = parse_iso(intent["approval_deadline_at"] or intent["window_end_at"])
        if now < deadline:
            return False
        self._finish(intent["intent_id"], now, "expired", "skipped_by_operator", "approval expired")
        log.warning("intent %s expired without approval", intent["intent_id"])
        return True

    def _apply_approve(self, now: datetime, action, _prepared: object) -> str:  # noqa: ANN001
        """``bot approve <id>``: the approval covers the intent (side, quantity rule,
        window); re-prices inside the band need no new approval, and every submission
        still passes the risk checks (AD-16)."""
        intent = self._awaiting(action)
        if intent is None:
            return f"ignored: intent {action['target_id']} is not awaiting approval"
        if self._expire_if_due(intent, now):
            return "too late: the intent expired"
        self.store.update(
            "intents", "intent_id", intent["intent_id"], state="working", updated_at=iso(now)
        )
        return f"intent {intent['intent_id']} approved"

    def _apply_reject(self, now: datetime, action, _prepared: object) -> str:  # noqa: ANN001
        intent = self._awaiting(action)
        if intent is None:
            return f"ignored: intent {action['target_id']} is not awaiting approval"
        self._finish(
            intent["intent_id"], now, "cancelled", "skipped_by_operator",
            f"rejected by the operator: {action['note']}",
        )  # fmt: skip
        return f"intent {intent['intent_id']} rejected"

    # kill switch -----------------------------------------------------------------------

    def _apply_kill_on(self, now: datetime, action, _prepared: object) -> str:  # noqa: ANN001
        # `bot kill on` creates the file itself (risk.kill_switch.engage); the row is the
        # audit record. The state change is logged from the file by _log_kill_state.
        engaged = self._kill_switch()
        return "kill switch file present" if engaged else "kill switch file absent"

    def _apply_kill_off(self, now: datetime, action, _prepared: object) -> str:  # noqa: ANN001
        """AD-12: disengage is CLI-only and the engine is the only deleter of the file. A
        switch engaged AFTER the ``kill off`` command (dashboard, ``kill on``, by hand) is
        kept: the newer request wins (review finding). An ``OSError`` (file held open on
        Windows) rolls back and the action is retried next tick."""
        if self._kill_path is None:
            return "ignored: no kill switch path configured"
        if not self._kill_path.exists():
            return "kill switch was not engaged"
        state = read_kill_switch(self._kill_path)
        if state.at is not None:
            written = datetime.strptime(state.at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        else:  # a hand-made file: its modification time
            written = datetime.fromtimestamp(self._kill_path.stat().st_mtime, tz=UTC)
        if written > parse_iso(action["at"]):
            return "kept: the kill switch was engaged again after this kill off request"
        self._kill_path.unlink()
        self._log_kill_state(now, self._kill_switch())
        return "kill switch file deleted"

    def _read(self, name: str, fn: Callable, *args: object):  # noqa: ANN202
        """A broker read with AD-8 handling: ``RateLimited`` sleeps ``retry_after_s``,
        ``TransientReadError`` backs off; at most ``READ_RETRIES`` retries, each failure
        recorded in ``api_calls``; no state changes. The last failure propagates (the tick
        is skipped and the error recorded)."""
        attempt = 0
        while True:
            try:
                return fn(*args)
            except RateLimited as exc:
                self._api_failure(name, True)
                if attempt >= READ_RETRIES:
                    raise
                wait = timedelta(seconds=exc.retry_after_s)
            except TransientReadError:
                self._api_failure(name, False)
                if attempt >= READ_RETRIES:
                    raise
                wait = timedelta(seconds=2**attempt)
            attempt += 1
            self.clock.sleep_until(self.clock.now() + wait)

    def _record_pricing(self, now: datetime, cl: str, side: str, price: Decimal) -> None:
        """AD-6: record the bid/ask each order was priced from (``api_calls`` endpoint
        ``priced_from``), the input of the backtest-vs-paper consistency check. Health
        data: off in the backtest (``health_records``)."""
        if not self.cfg.health_records:
            return
        t = self._priced_ticker
        detail = {"cl_ord_id": cl, "side": side, "limit": str(price)}
        if t is not None:
            detail |= {"bid": str(t.bid), "ask": str(t.ask), "ticker_at": iso(t.ts)}
        self.store.insert(
            "api_calls",
            at=iso(now),
            endpoint="priced_from",
            latency_ms=0,
            ok=1,
            rate_limited=0,
            detail_json=json.dumps(detail, sort_keys=True),
        )

    def _api_failure(self, name: str, rate_limited: bool) -> None:
        self.store.insert(
            "api_calls",
            at=iso(self.clock.now()),
            endpoint=f"broker.{name}",
            latency_ms=0,
            ok=0,
            rate_limited=int(rate_limited),
        )

    def _unknown_grace_passed(self, order, now: datetime) -> bool:  # noqa: ANN001
        row = self.store.one(
            "SELECT at FROM order_events WHERE order_id = ? AND to_state = 'unknown' "
            "ORDER BY event_id DESC",
            (order["order_id"],),
        )
        return row is None or now - parse_iso(row["at"]) >= self.cfg.unknown_grace

    def _risk_event(
        self,
        now: datetime,
        kind: str,
        rule: str,
        intent_id: int | None,
        reason: str,
        detail: dict[str, object],
    ) -> None:
        self.store.insert(
            "risk_events",
            at=iso(now),
            kind=kind,
            rule=rule,
            intent_id=intent_id,
            reason=reason,
            detail_json=json.dumps(detail, sort_keys=True, default=str),
        )

    def _set_outcome(self, signal_id: str | None, outcome: str, reason: str | None) -> None:
        if signal_id is not None:
            self.store.update(
                "signals", "signal_id", signal_id, outcome=outcome, outcome_reason=reason
            )

    # --- intents and orders -------------------------------------------------------------

    def _active_intent(self):  # noqa: ANN202 - sqlite3.Row | None
        marks = ",".join("?" for _ in ACTIVE_INTENT_STATES)
        return self.store.one(
            f"SELECT * FROM intents WHERE pair = ? AND state IN ({marks})",  # noqa: S608
            (self.cfg.pair, *ACTIVE_INTENT_STATES),
        )

    def _intent(self, intent_id: int):  # noqa: ANN202
        return self.store.one("SELECT * FROM intents WHERE intent_id = ?", (intent_id,))

    def _live_order(self, intent_id: int):  # noqa: ANN202
        marks = ",".join("?" for _ in LIVE_ORDER_STATES)
        return self.store.one(
            f"SELECT * FROM orders WHERE intent_id = ? AND state IN ({marks})",  # noqa: S608
            (intent_id, *LIVE_ORDER_STATES),
        )

    def _transition(self, order_id: int, to: str, now: datetime, **cols: object) -> None:
        row = self.store.one("SELECT state FROM orders WHERE order_id = ?", (order_id,))
        frm = row["state"]
        if frm == to and to != "partially_filled":
            return
        if to not in TRANSITIONS.get(frm, frozenset()):
            raise IllegalTransition(f"order {order_id}: {frm} -> {to}")
        with self.store.transaction():
            self.store.update("orders", "order_id", order_id, state=to, **cols)
            self.store.insert(
                "order_events",
                order_id=order_id,
                at=iso(now),
                from_state=frm,
                to_state=to,
                detail_json=json.dumps({k: str(v) for k, v in cols.items()}, sort_keys=True),
            )

    def _finish(
        self, intent_id: int, now: datetime, state: str, outcome: str, reason: str | None
    ) -> None:
        intent = self._intent(intent_id)
        with self.store.transaction():
            self.store.update("intents", "intent_id", intent_id, state=state, updated_at=iso(now))
            self._set_outcome(intent["signal_id"], outcome, reason)
            position = self.store.position(self.cfg.pair)
            mark = Decimal(intent["reference_price"])
            if (
                intent["side"] == "sell"
                and position > 0
                and not self._sellable_by_minimums(position, mark)
            ):
                # AD-13 sell-side dust: stays in equity; the next buy adds to it and the
                # next full-balance sell clears it. No top-up buy is made just to sell.
                self._risk_event(
                    now,
                    "dust",
                    "minimums",
                    intent_id,
                    f"base {position} left below the exchange minimums "
                    f"(amount_min {self.rules.amount_min}, cost_min {self.rules.cost_min})",
                    {},
                )

    def _price(self, side: str, ticker: Ticker) -> Decimal:
        """Passive (AD-5): best bid for a buy, best ask for a sell, rounded away from the
        book to the tick. The taker report variant takes the other side (ask for a buy,
        bid for a sell)."""
        self._priced_ticker = ticker
        tick = self.rules.tick_size
        use_ask = (side == "sell") != (self.cfg.pricing == "aggressive")
        if use_ask:
            return (ticker.ask / tick).to_integral_value(rounding=ROUND_CEILING) * tick
        return (ticker.bid / tick).to_integral_value(rounding=ROUND_FLOOR) * tick

    def _fee_rate(self) -> Decimal:
        return self._fees.taker if self.cfg.pricing == "aggressive" else self._fees.maker

    def _resting_buy_qty(self) -> Decimal:
        marks = ",".join("?" for _ in LIVE_ORDER_STATES)
        rows = self.store.all(
            f"SELECT qty, filled_qty FROM orders WHERE side = 'buy' AND state IN ({marks})",  # noqa: S608
            LIVE_ORDER_STATES,
        )
        return sum((Decimal(r["qty"]) - Decimal(r["filled_qty"]) for r in rows), Decimal(0))

    def _size(self, side: str, target: Decimal, price: Decimal, now: datetime, mid: Decimal):  # noqa: ANN202
        position = self.store.position(self.cfg.pair)
        if side == "sell":
            return sell_qty(position, price, self.rules)
        equity = self.store.equity_at(now, mid, self.cfg.pair)
        free_quote = self.store.cash()
        return buy_qty(
            SizingInput(
                target=target,
                equity=equity,
                free_quote=free_quote,
                position=position,
                resting_buy_qty=self._resting_buy_qty(),
                price=price,
                fee_rate=self._fee_rate(),
                slippage_bps=self.cfg.slippage_bps,
            ),
            self.rules,
            self.limits,
        )

    def _risk_context(
        self, now: datetime, ticker: Ticker, reference_price: Decimal, intent_id: int | None
    ) -> RiskContext:
        day = iso(now)[:10]
        hist = self.md.closed_candles(self.cfg.pair, self.cfg.timeframe, limit=1)
        mid = (ticker.bid + ticker.ask) / 2
        intents_today = self.store.one(
            "SELECT count(*) FROM intents "
            "WHERE substr(created_at, 1, 10) = ? AND intent_id IS NOT ?",
            (day, intent_id),
        )[0]
        subs_today = self.store.one(
            "SELECT count(*) FROM orders WHERE substr(created_at, 1, 10) = ?", (day,)
        )[0]
        intent_subs = 0 if intent_id is None else self._submissions(intent_id)
        return RiskContext(
            now=now,
            equity=self.store.equity_at(now, mid, self.cfg.pair),
            position_qty=self.store.position(self.cfg.pair),
            resting_buy_qty=self._resting_buy_qty(),
            intents_today=int(intents_today),
            submissions_today=int(subs_today),
            intent_submissions=int(intent_subs),
            last_candle_open_at=hist.last_open_at,
            candle_interval=self._interval,
            last_candle_synthetic=bool(hist.synthetic[-1]) if len(hist) else False,
            ticker_ts=ticker.ts,
            mid=mid,
            reference_price=reference_price,
            active_halts=self._active_halts(),
            kill_switch_engaged=self._kill_switch(),
            market_status=self.rules.status,
            amount_min=self.rules.amount_min,
            cost_min=self.rules.cost_min,
        )

    # --- signals ------------------------------------------------------------------------

    def _maybe_signal(self, now: datetime, ticker: Ticker) -> bool:
        hist = self.md.closed_candles(self.cfg.pair, self.cfg.timeframe)
        last = hist.last_open_at
        if last is None:
            return False
        # The adapter reads the clock when it is called; a slow tick (lookups, retries)
        # must not look like a future candle, so check against the clock now. The SimClock
        # never moves within a tick, so the backtest guard is unchanged.
        self._check_closed(last, self.clock.now())
        signal_id = f"{self.strategy.id}|{self.cfg.pair}|{self.cfg.timeframe}|{iso(last)}"
        if self.store.one("SELECT 1 FROM signals WHERE signal_id = ?", (signal_id,)):
            return False
        target = self.strategy.on_candle(hist)
        if not isinstance(target, Decimal) or not (0 <= target <= 1):
            raise EngineError(f"strategy returned target {target!r} outside [0, 1]")
        indicators = self.strategy.indicators(hist)
        signal_price = Decimal(repr(float(hist.close[-1])))
        window_end = last + self._interval + self.cfg.window
        if self._active_intent() is None:
            # AD-13: minimums change without notice; re-read them before each decision,
            # outside any transaction (a broker call).
            self._rules = self.broker.load_market(self.cfg.pair)
        with self.store.transaction():
            self.store.insert(
                "signals",
                signal_id=signal_id,
                run_id=self.run_id,
                strategy_id=self.strategy.id,
                pair=self.cfg.pair,
                timeframe=self.cfg.timeframe,
                candle_open_at=iso(last),
                evaluated_at=iso(now),
                target_fraction=dec(target),
                signal_price=dec(signal_price),
                indicators_json=json.dumps(indicators, sort_keys=True),
                outcome="pending",
            )
            submit = self._decide_and_open(signal_id, target, signal_price, window_end, now, ticker)
        self._submit_first(submit, now, ticker)
        return True

    def _decide_and_open(
        self,
        signal_id: str,
        target: Decimal,
        signal_price: Decimal,
        window_end: datetime,
        now: datetime,
        ticker: Ticker,
    ) -> tuple[int, Decimal, Decimal, str, RiskDecision] | None:
        """Decide, size, risk-check and open the intent of a journaled signal (inside the
        caller's transaction, AD-28). Returns the first submission for an autonomous
        intent, to be sent after the commit (AD-7)."""
        mid = (ticker.bid + ticker.ask) / 2
        side, why = self._decide(target, signal_price)
        active = self._active_intent()
        if active is not None:
            reason = "flatten_active" if active["is_flatten"] else "intent_active"
            self._set_outcome(signal_id, "no_action", reason)
            return None
        if side is None:
            self._set_outcome(signal_id, "no_action", why)
            return None
        if now >= window_end:
            self._set_outcome(signal_id, "not_filled", "window_passed")
            return None
        price = self._price(side, ticker)
        sized = self._size(side, target, price, now, mid)
        if isinstance(sized, NoOrder):
            self._set_outcome(signal_id, sized.outcome, sized.reason)
            if sized.outcome == "below_minimum":
                self._risk_event(now, "rejection", "minimums", None, sized.reason, {})
            return None
        cl = self._new_id()
        proposed = ProposedOrder(0, 1, False, side, sized, price, cl)  # type: ignore[arg-type]
        decision = check_order(
            proposed, self._risk_context(now, ticker, signal_price, None), self.limits
        )
        if not decision.approved:
            self._set_outcome(signal_id, "rejected_by_risk", f"{decision.rule}: {decision.reason}")
            self._risk_event(now, "rejection", decision.rule or "", None, decision.reason or "", {})
            return None
        approval = self.cfg.approval  # the backtest wiring forces autonomous
        intent_id = self.store.insert(
            "intents",
            signal_id=signal_id,
            pair=self.cfg.pair,
            side=side,
            reference_price=dec(signal_price),
            target_qty=dec(sized),
            state="working" if approval == "autonomous" else "awaiting_approval",
            approval_mode=approval,
            approval_deadline_at=None if approval == "autonomous" else iso(window_end),
            window_end_at=iso(window_end),
            created_at=iso(now),
            updated_at=iso(now),
        )
        if approval == "autonomous":
            return (intent_id, sized, price, cl, decision)
        self._announce_approval(intent_id, side, sized, price, signal_price, window_end)
        return None

    def _announce_approval(  # noqa: PLR0913
        self,
        intent_id: int,
        side: str,
        qty: Decimal,
        price: Decimal,
        reference: Decimal,
        deadline: datetime,
    ) -> None:
        """AD-16: print and log the order awaiting approval with its allowed price band."""
        band = self.limits.price_sanity_fraction
        lo, hi = reference * (1 - band), reference * (1 + band)
        msg = (
            f"APPROVAL NEEDED (intent {intent_id}): {side} {qty} {self.cfg.pair} post-only "
            f"limit ~{price}; allowed price band {lo:.2f}..{hi:.2f} (+/-{band * 100}% of "
            f"{reference}); expires {iso(deadline)}. Approve: bot approve {intent_id} --note "
            f"... | Reject: bot reject {intent_id} --note ..."
        )
        log.warning(msg)
        print(msg, flush=True)  # noqa: T201 - operator channel (AD-16, OD-13)

    def _submit_first(
        self,
        submit: tuple[int, Decimal, Decimal, str, RiskDecision] | None,
        now: datetime,
        ticker: Ticker,
    ) -> None:
        if submit is None:
            return
        intent_id, qty, price, cl, decision = submit
        result = self._place(self._intent(intent_id), 1, qty, price, cl, decision, now)
        if result == "cross":
            self._resubmit(self._intent(intent_id), now, ticker)  # AD-5 immediate re-price
        elif result == "rejected":
            self._finish(
                intent_id, now, "cancelled", "rejected_by_risk", "exchange rejected the order"
            )

    def _check_closed(self, candle_open_at: datetime, now: datetime) -> None:
        """Every evaluated candle must be closed at evaluation: open_at + interval <= now."""
        if candle_open_at + self._interval > now:
            raise FutureCandleError(
                f"candle {iso(candle_open_at)} ({self.cfg.timeframe}) is not closed at "
                f"{iso(now)}: the market-data adapter leaks the future"
            )

    def _decide(self, target: Decimal, price: Decimal) -> tuple[str | None, str]:
        """Long-or-flat: buy when a target > 0 finds no position; sell the whole position
        when the target is 0. A position the exchange would refuse to sell (below
        amount_min or cost_min) counts as dust, not as held. No partial top-ups (v1)."""
        position = self.store.position(self.cfg.pair)
        held = self._sellable_by_minimums(position, price)
        if target > 0 and not held:
            return "buy", ""
        if target == 0 and held:
            return "sell", ""
        if target == 0 and position > 0:
            return None, f"position {position} below amount_min (dust)"
        return None, "target already met"

    def _place(
        self,
        intent,  # noqa: ANN001 - sqlite3.Row
        attempt_no: int,
        qty: Decimal,
        price: Decimal,
        cl: str,
        decision: RiskDecision,
        now: datetime,
    ) -> str:
        """Persist, then send one approved order (AD-7). Returns the order's state.

        The kill-switch file is re-read just before the order is persisted and sent
        (AD-12): an engaged switch blocks every non-flatten submission ("blocked")."""
        intent_id = intent["intent_id"]
        if not intent["is_flatten"] and self._kill_switch():
            self._log_kill_state(now, True)
            return "blocked"
        with self.store.transaction():
            order_id = self.store.insert(
                "orders",
                intent_id=intent_id,
                attempt_no=attempt_no,
                cl_ord_id=cl,
                side=intent["side"],
                limit_price=dec(price),
                qty=dec(qty),
                state="created",
                created_at=iso(now),
            )
            self.store.insert(
                "order_events",
                order_id=order_id,
                at=iso(now),
                from_state=None,
                to_state="created",
                detail_json="{}",
            )
        self._transition(order_id, "submitting", now, submitted_at=iso(now))
        self._record_pricing(now, cl, intent["side"], price)
        req = OrderRequest(self.cfg.pair, intent["side"], qty, price, cl)
        try:
            ack = self.broker.place_order(req, decision)
        except PostOnlyWouldCross as exc:
            self._transition(order_id, "rejected", now, reject_reason=f"post_only_cross: {exc}")
            return "cross"
        except OrderRejected as exc:
            self._transition(order_id, "rejected", now, reject_reason=str(exc))
            self._risk_event(now, "exchange_reject", "exchange", intent_id, str(exc), {"cl": cl})
            return "rejected"
        except OrderOutcomeUnknown as exc:
            self._transition(order_id, "unknown", now)
            log.warning("place_order outcome unknown for %s: %s", cl, exc)
            order = self.store.one("SELECT * FROM orders WHERE order_id = ?", (order_id,))
            return self._resolve_unknown(order)
        except (RateLimited, TransientReadError) as exc:
            # The exchange refused the request before placing anything (rate limit): the
            # attempt still counts against the submission caps (the conservative side).
            self._transition(order_id, "rejected", now, reject_reason=f"not sent: {exc}")
            if isinstance(exc, RateLimited):
                self._api_failure("place_order", True)
                self.clock.sleep_until(self.clock.now() + timedelta(seconds=exc.retry_after_s))
            return "retry"
        self._transition(
            order_id,
            "open",
            now,
            exchange_order_id=ack.exchange_order_id,
            accepted_at=iso(ack.accepted_at),
        )
        return "open"

    # --- advancing an intent ------------------------------------------------------------

    def _ingest_fills(self, intent, now: datetime) -> None:  # noqa: ANN001
        since = parse_iso(intent["created_at"])
        for f in self._read("get_fills", self.broker.get_fills, self.cfg.pair, since):
            if self.store.one(
                "SELECT 1 FROM fills WHERE exchange = ? AND exchange_trade_id = ?",
                (self.broker.name, f.exchange_trade_id),
            ):
                continue
            order = self.store.one("SELECT * FROM orders WHERE cl_ord_id = ?", (f.cl_ord_id,))
            if order is None:
                with self.store.transaction():
                    self.store.execute(
                        "INSERT INTO halts (rule, triggered_at, reason) VALUES (?, ?, ?) "
                        "ON CONFLICT DO NOTHING",
                        ("reconcile_mismatch", iso(now), f"unknown fill {f.exchange_trade_id}"),
                    )
                    self._risk_event(
                        now,
                        "reconcile_mismatch",
                        "reconcile_mismatch",
                        None,
                        f"fill {f.exchange_trade_id} matches no order",
                        {"cl_ord_id": f.cl_ord_id},
                    )
                continue
            reference = Decimal(order["limit_price"])
            slip = float((f.price - reference) / reference * 10_000)
            with self.store.transaction():
                self.store.insert(
                    "fills",
                    exchange=self.broker.name,
                    exchange_trade_id=f.exchange_trade_id,
                    order_id=order["order_id"],
                    at=iso(f.ts),
                    pair=f.pair,
                    base=self.rules.base,
                    quote_ccy=self.rules.quote,
                    side=f.side,
                    qty=dec(f.qty),
                    price=dec(f.price),
                    fee=dec(f.fee),
                    fee_ccy=f.fee_ccy,
                    liquidity=f.liquidity,
                    reference_price=dec(intent["reference_price"]),
                    slippage_bps=slip,
                    quote_is_fiat=int(self.cfg.quote_is_fiat),
                    simulated=int(self.broker.name != "kraken"),
                )
                filled = Decimal(order["filled_qty"]) + f.qty
                self.store.update("orders", "order_id", order["order_id"], filled_qty=dec(filled))
                total = Decimal(self._intent(order["intent_id"])["filled_qty"]) + f.qty
                self.store.update("intents", "intent_id", order["intent_id"], filled_qty=dec(total))

    def _sync_order(  # noqa: ANN001
        self, order, now: datetime, status: object = _UNSET, resolved: bool = False
    ) -> str:
        """Bring one live order's state in line with the broker (after fills are ingested).

        An ``unknown`` order absent from the broker becomes ``not_found`` only after
        ``unknown_grace`` (AD-8). Fills reported by the broker but not yet ingested block
        any terminal transition (AD-27); if they do not settle within
        ``fill_settle_timeout`` the engine halts with ``reconcile_mismatch``."""
        if status is _UNSET:
            status = self._read(
                "find_order", self.broker.find_order, self.cfg.pair, order["cl_ord_id"]
            )
        state = order["state"]
        if status is None:
            if state == "unknown":
                if not resolved and not self._unknown_grace_passed(order, now):
                    return state
                self._transition(order["order_id"], "not_found", now, closed_at=iso(now))
                log.warning("order %s not found after the grace: not_found", order["cl_ord_id"])
                return "not_found"
            return state
        assert isinstance(status, OrderStatus)
        stored = Decimal(
            self.store.one(
                "SELECT filled_qty FROM orders WHERE order_id = ?", (order["order_id"],)
            )[0]
        )
        if stored > status.filled_qty:
            self.raise_halt(
                now,
                "reconcile_mismatch",
                f"order {order['cl_ord_id']}: ingested fills {stored} exceed the exchange's "
                f"filled quantity {status.filled_qty}",
                kind="reconcile_mismatch",
            )
            return state
        if stored != status.filled_qty:
            first = self._unsettled_since.setdefault(order["order_id"], now)
            if now - first > self.cfg.fill_settle_timeout:
                self.raise_halt(
                    now,
                    "reconcile_mismatch",
                    f"order {order['cl_ord_id']}: fills not settled within the timeout "
                    f"(ingested {stored}, exchange {status.filled_qty})",
                    kind="reconcile_mismatch",
                )
            return state  # fills not ingested yet (AD-27): no terminal transition
        self._unsettled_since.pop(order["order_id"], None)
        if status.state == "open":
            new = "partially_filled" if status.filled_qty > 0 else "open"
            if state == "cancel_requested" or new == state:
                return state
            if state == "partially_filled":  # never back to open
                return state
        else:
            new = {"closed": "filled", "canceled": "cancelled", "rejected": "rejected"}[
                status.state
            ]
            if new == state:
                return state
        cols: dict[str, object] = {}
        if new in ("filled", "cancelled", "rejected"):
            cols["closed_at"] = iso(now)
        if order["exchange_order_id"] is None and status.exchange_order_id:
            cols["exchange_order_id"] = status.exchange_order_id  # found after a restart
        self._transition(order["order_id"], new, now, **cols)
        return new

    def _cancel_live(self, intent, now: datetime) -> None:  # noqa: ANN001
        """Cancel the intent's live order, then ingest its final fills (AD-27). A cancel
        that times out stays ``cancel_requested`` and is re-sent and re-checked on the
        next tick (AD-8); an ``unknown`` order is resolved first, never cancelled blind."""
        order = self._live_order(intent["intent_id"])
        if order is None:
            return
        if order["state"] == "unknown":
            self._resolve_unknown(order)
            order = self._live_order(intent["intent_id"])
            if order is None:
                return
        if order["state"] in ("open", "partially_filled"):
            self._transition(order["order_id"], "cancel_requested", now)
            order = self.store.one("SELECT * FROM orders WHERE order_id = ?", (order["order_id"],))
        if order["state"] == "cancel_requested":
            self._cancel_sent_at.setdefault(order["order_id"], now)
            try:
                self.broker.cancel_order(self.cfg.pair, order["cl_ord_id"])
            except (OrderOutcomeUnknown, TransientReadError, RateLimited, OrderRejected) as exc:
                # Re-checked with find_order (and re-sent) on the next tick.
                self.error(now, "cancel", exc)
        self._ingest_fills(intent, now)
        order = self.store.one("SELECT * FROM orders WHERE order_id = ?", (order["order_id"],))
        self._sync_order(order, now)

    def _advance_intent(self, now: datetime, ticker: Ticker) -> None:
        """AD-5/AD-28: ingest fills, then re-price, end the window or run the completion
        phase. A new order is placed only once the previous one is confirmed closed and
        its fills are ingested (AD-27)."""
        intent = self._active_intent()
        if intent is None:
            return
        if intent["state"] == "awaiting_approval":
            self._expire_if_due(intent, now)
            return
        intent_id = intent["intent_id"]
        self._ingest_fills(intent, now)
        order = self._live_order(intent_id)
        if order is not None:
            self._sync_order(order, now)
        if not intent["is_flatten"] and (self._active_halts() or self._kill_switch()):
            # A halt raised while syncing (reconcile_mismatch) stops the intent now, with
            # the AD-28 outcome `halted`, before any re-price (review finding).
            self._sweep(now, f"halt: {', '.join(self._active_halts()) or 'kill switch'}")
            return
        completing = intent["parent_intent_id"] is not None  # a completion intent

        if not completing and self._target_reached(intent_id):
            self._finish(intent_id, now, "done", "filled", None)
            return
        order = self._live_order(intent_id)
        if order is not None and order["state"] == "cancel_requested":
            self._cancel_live(intent, now)  # re-send a cancel that may not have arrived (AD-8)
            if self._live_order(intent_id) is None:
                intent = self._intent(intent_id)
        if self._settle_overdue(intent_id, now):
            return
        if completing and self._sellable_now(ticker):
            self._cancel_live(intent, now)
            if self._live_order(intent_id) is None:
                self._finish(intent_id, now, "done", "partially_filled", "completion reached")
            return

        end = parse_iso(intent["window_end_at"])
        if now >= end:
            if completing:
                self._end_completion(intent, now, ticker)
            else:
                self._end_window(intent, now, ticker)
            return

        if now - ticker.ts > timedelta(seconds=self.limits.stale_ticker_seconds):
            if not self._exchange_halted():
                # Audit M2 F-5: OUR feed is stale, the exchange is trading. The bot is
                # blind, so the resting order is cancelled (cancels reduce risk and are
                # always allowed); re-pricing waits for a fresh ticker (stale_ticker rule).
                self._cancel_stale(intent, now, "own ticker stale")
                return
            # Exchange halted (synthetic candles, audit M1 F-2): keep the resting order (it
            # cannot fill on synthetic candles) instead of cancelling and being refused by
            # the stale_ticker rule; the window end still applies.
            return
        order = self._live_order(intent_id)
        if order is not None:
            if order["state"] not in ("open", "partially_filled"):
                return  # unknown or cancel pending: resolved on a later tick
            accepted = parse_iso(order["accepted_at"] or order["created_at"])
            if now < accepted + self.cfg.reprice_interval:
                return
            if self._submissions(intent_id) >= self.limits.max_submissions_per_intent:
                return  # no re-price left: the last order rests until the window end
            self._cancel_live(intent, now)
            if self._live_order(intent_id) is not None:
                return  # cancel not confirmed or fills not settled yet (AD-27)
            if not completing and self._target_reached(intent_id):
                self._finish(intent_id, now, "done", "filled", None)
                return
        self._resubmit(self._intent(intent_id), now, ticker)

    def _exchange_halted(self) -> bool:
        """True when the latest closed execution candle is synthetic: a no-trade period,
        which includes exchange trading halts (audit M1 F-2). Live candles from the public
        API are never synthetic, so in dry-run/live a stale ticker means our own feed."""
        try:
            hist = self.md.closed_candles(self.cfg.pair, self.cfg.exec_timeframe, limit=1)
        except (TransientReadError, RateLimited):
            return False
        return bool(len(hist)) and bool(hist.synthetic[-1])

    def _own_feed_blind(self, now: datetime) -> None:
        """The ticker read failed. Once no good ticker has been seen for longer than
        ``stale_ticker_seconds``, cancel the resting order (audit M2 F-5): the bot must not
        keep an order working while it cannot see the market."""
        stale = timedelta(seconds=self.limits.stale_ticker_seconds)
        if self._last_ticker_ok is not None and now - self._last_ticker_ok <= stale:
            return
        intent = self._active_intent()
        if intent is None or self._exchange_halted():
            return
        try:
            self._cancel_stale(intent, now, "ticker unavailable")
        except (TransientReadError, RateLimited, OrderOutcomeUnknown) as exc:
            self.error(now, "cancel_on_blind_feed", exc)

    def _cancel_stale(self, intent, now: datetime, why: str) -> None:  # noqa: ANN001
        order = self._live_order(intent["intent_id"])
        if order is None or order["state"] not in ("open", "partially_filled"):
            return
        self._risk_event(
            now,
            "stale_data",
            "stale_ticker",
            intent["intent_id"],
            f"{why}: resting order {order['cl_ord_id']} cancelled (audit M2 F-5)",
            {},
        )
        log.warning("%s: cancelling resting order %s", why, order["cl_ord_id"])
        self._cancel_live(intent, now)

    def _target_reached(self, intent_id: int) -> bool:
        return (
            self.store.one(
                "SELECT 1 FROM orders WHERE intent_id = ? AND state = 'filled'", (intent_id,)
            )
            is not None
        )

    def _sellable_now(self, ticker: Ticker) -> bool:
        mid = (ticker.bid + ticker.ask) / 2
        return sellable(self.store.position(self.cfg.pair), mid, self.rules, self.limits)

    def _resubmit(self, intent, now: datetime, ticker: Ticker) -> None:  # noqa: ANN001
        """Place the intent's next submission at the current best price (re-price). A
        post-only cross re-prices immediately; the risk caps bound the loop."""
        intent_id = intent["intent_id"]
        side = intent["side"]
        completing = intent["parent_intent_id"] is not None  # a completion intent
        crossed_at: Decimal | None = None
        for _ in range(self.limits.max_submissions_per_intent + 1):
            attempt = (
                1
                + self.store.one("SELECT count(*) FROM orders WHERE intent_id = ?", (intent_id,))[0]
            )
            price = self._price(side, ticker)
            if crossed_at is not None and price == crossed_at:
                return  # the book has not moved since the cross: retry on the next tick
            mid = (ticker.bid + ticker.ask) / 2
            position = self.store.position(self.cfg.pair)
            if completing:
                sized = completion_qty(position, price, self.rules, self.limits)
            elif intent["is_flatten"]:
                sized = self._size("sell", Decimal(0), price, now, mid)  # full base (AD-25)
            else:
                target = Decimal(
                    self.store.one(
                        "SELECT target_fraction FROM signals WHERE signal_id = ?",
                        (intent["signal_id"],),
                    )[0]
                )
                sized = self._size(side, target, price, now, mid)
            filled = Decimal(self._intent(intent_id)["filled_qty"])
            if isinstance(sized, NoOrder):
                if sized.outcome == "below_minimum":
                    self._risk_event(now, "rejection", "minimums", intent_id, sized.reason, {})
                if completing:
                    if self._sellable_now(ticker):
                        self._finish(intent_id, now, "done", "partially_filled", sized.reason)
                    else:
                        self._completion_failed(intent, now, "done", sized.reason)
                    return
                if side == "buy" and filled > 0 and not self._sellable_now(ticker):
                    self._start_completion(intent, now, ticker)  # AD-13: remainder -> AD-28
                    return
                outcome = "partially_filled" if filled > 0 else sized.outcome
                self._finish(intent_id, now, "done", outcome, sized.reason)
                return
            cl = self._new_id()
            proposed = ProposedOrder(
                intent_id, attempt, bool(intent["is_flatten"]), side, sized, price, cl
            )
            ctx = self._risk_context(now, ticker, Decimal(intent["reference_price"]), intent_id)
            decision = check_order(proposed, ctx, self.limits)
            if not decision.approved:
                self._risk_event(
                    now, "rejection", decision.rule or "", intent_id, decision.reason or "", {}
                )
                if completing:  # normal rules: a risk rejection ends the intent
                    self._completion_failed(
                        intent, now, "cancelled", f"{decision.rule}: {decision.reason}"
                    )
                    return
                outcome = "partially_filled" if filled > 0 else "rejected_by_risk"
                self._finish(
                    intent_id, now, "cancelled", outcome, f"{decision.rule}: {decision.reason}"
                )
                return
            result = self._place(intent, attempt, sized, price, cl, decision, now)
            if result == "cross":
                # AD-5: immediate re-price at the CURRENT best price, counted toward caps.
                crossed_at = price
                try:
                    ticker = self.broker.get_ticker(self.cfg.pair)
                except (TransientReadError, RateLimited) as exc:
                    self._error(now, "ticker", exc)
                    return
                continue
            if result == "rejected":
                outcome = "partially_filled" if filled > 0 else "rejected_by_risk"
                self._finish(intent_id, now, "cancelled", outcome, "exchange rejected the order")
            return

    def _start_completion(self, intent, now: datetime, ticker: Ticker) -> None:  # noqa: ANN001
        """AD-28 (as amended after audit M2 F-3): an unsellable partial buy ends its intent
        and opens a NEW completion intent linked by ``parent_intent_id``. The child is an
        ordinary intent: it counts against ``max_order_intents_per_day``, has its own
        ``max_submissions_per_intent`` budget, passes every risk check, and buys only up to
        the sellable threshold until its window (parent window end + completion window)."""
        mid = (ticker.bid + ticker.ask) / 2
        position = self.store.position(self.cfg.pair)
        target = completion_qty(position, self._price("buy", ticker), self.rules, self.limits)
        with self.store.transaction():
            self._finish(
                intent["intent_id"],
                now,
                "done",
                "partially_filled",
                "unsellable remainder: a completion intent (parent_intent_id link) follows",
            )
            manual = intent["approval_mode"] == "manual"
            child_end = parse_iso(intent["window_end_at"]) + self.cfg.completion_window
            child = self.store.insert(
                "intents",
                parent_intent_id=intent["intent_id"],
                pair=self.cfg.pair,
                side="buy",
                reference_price=dec(mid),
                target_qty=dec(target if isinstance(target, Decimal) else Decimal(0)),
                # AD-16: a completion is a NEW intent; in manual mode it needs its own
                # approval (review finding), with its window end as the deadline.
                state="awaiting_approval" if manual else "working",
                approval_mode=intent["approval_mode"],
                approval_deadline_at=iso(child_end) if manual else None,
                window_end_at=iso(child_end),
                created_at=iso(now),
                updated_at=iso(now),
            )
        if manual:
            qty = target if isinstance(target, Decimal) else Decimal(0)
            self._announce_approval(child, "buy", qty, self._price("buy", ticker), mid, child_end)
            return
        self._resubmit(self._intent(child), now, ticker)

    def _journal_signal(self, intent) -> str | None:  # noqa: ANN001
        """The signal an intent reports to: its own, or its parent's for a completion."""
        while intent["signal_id"] is None and intent["parent_intent_id"] is not None:
            intent = self._intent(intent["parent_intent_id"])
        return intent["signal_id"]

    def _completion_failed(self, intent, now: datetime, state: str, why: str) -> None:  # noqa: ANN001
        """A completion intent ends with the position still unsellable: dust (AD-13)."""
        position = self.store.position(self.cfg.pair)
        reason = f"completion ended ({why}) with unsellable position {position}"
        with self.store.transaction():
            self._risk_event(now, "dust", "minimums", intent["intent_id"], reason, {})
            self.store.insert(
                "errors", at=iso(now), component="engine", error_type="Dust", message=reason
            )
            self._finish(intent["intent_id"], now, state, "dust", reason)
            self._set_outcome(self._journal_signal(intent), "dust", reason)

    def _sellable_by_minimums(self, position: Decimal, price: Decimal) -> bool:
        r = self.rules
        return position >= r.amount_min and position * price >= r.cost_min

    def _submissions(self, intent_id: int) -> int:
        """Exchange submissions of this intent (first order + re-prices), AD-5/AD-11."""
        return self.store.one("SELECT count(*) FROM orders WHERE intent_id = ?", (intent_id,))[0]

    def _settle_overdue(self, intent_id: int, now: datetime) -> bool:
        """AD-27: a cancel whose confirmation or fills do not settle within the timeout
        halts with ``reconcile_mismatch`` (the intent then ends as halted)."""
        order = self._live_order(intent_id)
        if order is None or order["state"] != "cancel_requested":
            return False
        # Measured from the first cancel this process sent: a restart re-sends the cancel
        # and restarts the clock instead of halting on a stale event time (review finding).
        since = self._cancel_sent_at.setdefault(order["order_id"], now)
        if now - since <= self.cfg.fill_settle_timeout:
            return False
        reason = f"order {order['cl_ord_id']}: cancel/fills not settled within timeout"
        with self.store.transaction():
            self.store.execute(
                "INSERT INTO halts (rule, triggered_at, reason) VALUES (?, ?, ?) "
                "ON CONFLICT DO NOTHING",
                ("reconcile_mismatch", iso(now), reason),
            )
            self._risk_event(now, "reconcile_mismatch", "reconcile_mismatch", intent_id, reason, {})
        return True

    def _end_window(self, intent, now: datetime, ticker: Ticker) -> None:  # noqa: ANN001
        intent_id = intent["intent_id"]
        self._cancel_live(intent, now)
        if self._live_order(intent_id) is not None:
            return  # cancel not confirmed yet; retried next tick
        if self._target_reached(intent_id):
            self._finish(intent_id, now, "done", "filled", None)
            return
        filled = Decimal(self._intent(intent_id)["filled_qty"])
        if filled == 0:
            self._finish(intent_id, now, "done", "not_filled", "window ended unfilled")
        elif intent["side"] == "buy" and not self._sellable_now(ticker):
            self._start_completion(intent, now, ticker)
        else:
            self._finish(intent_id, now, "done", "partially_filled", "window ended")

    def _end_completion(self, intent, now: datetime, ticker: Ticker) -> None:  # noqa: ANN001
        intent_id = intent["intent_id"]
        self._cancel_live(intent, now)
        if self._live_order(intent_id) is not None:
            return
        if self._sellable_now(ticker):
            self._finish(intent_id, now, "done", "partially_filled", "completion reached")
            return
        self._completion_failed(intent, now, "done", "completion window ended")
