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
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
from typing import Literal

from bot.broker.base import Broker, MarketRules, OrderRequest, Ticker
from bot.broker.errors import (
    OrderOutcomeUnknown,
    OrderRejected,
    PostOnlyWouldCross,
    RateLimited,
    TransientReadError,
)
from bot.config import TIMEFRAME_SECONDS
from bot.data.market import MarketData
from bot.risk.checks import ProposedOrder, RiskContext, RiskDecision, check_order
from bot.risk.halts import HaltContext, evaluate_halts
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


class IllegalTransition(RuntimeError):
    """An order state change not allowed by AD-8."""


class EngineError(RuntimeError):
    """The engine cannot continue safely."""


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
        self._new_id = new_cl_ord_id
        self._interval = timedelta(seconds=TIMEFRAME_SECONDS[config.timeframe])
        self._rules: MarketRules | None = None
        self.run_id: int | None = None

    # --- lifecycle ----------------------------------------------------------------------

    def start(self) -> None:
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
                pid=0,
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
            return TickResult(halted=bool(self._active_halts()), signal_evaluated=False)
        mid = (ticker.bid + ticker.ask) / 2
        first_of_day = self._day_open(now, mid)

        equity = self.store.equity_at(now, mid, self.cfg.pair)
        self._evaluate_halts(now, equity)
        halts = self._active_halts()
        killed = self._kill_switch()
        if halts or killed:
            self._sweep(now, "kill switch" if killed else f"halt: {', '.join(halts)}")
            if not first_of_day:
                self._snapshot(now, mid, False)
            return TickResult(halted=True, signal_evaluated=False)

        self._advance_intent(now, ticker)
        evaluated = self._maybe_signal(now, ticker)
        if not first_of_day:
            self._snapshot(now, mid, False)
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

    def _active_halts(self) -> tuple[str, ...]:
        rows = self.store.all("SELECT rule FROM halts WHERE reset_at IS NULL ORDER BY halt_id")
        return tuple(r["rule"] for r in rows)

    def _sweep(self, now: datetime, why: str) -> None:
        """AD-12: cancel resting orders of the active intent, keep the position."""
        intent = self._active_intent()
        if intent is None:
            return
        self._cancel_live(intent, now)
        self._finish(intent["intent_id"], now, "halted", "halted", why)

    # --- journal helpers ----------------------------------------------------------------

    def _error(self, now: datetime, component: str, exc: Exception) -> None:
        self.store.insert(
            "errors",
            at=iso(now),
            component=component,
            error_type=type(exc).__name__,
            message=str(exc)[:500],
        )

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
        signal_id = f"{self.strategy.id}|{self.cfg.pair}|{self.cfg.timeframe}|{iso(last)}"
        if self.store.one("SELECT 1 FROM signals WHERE signal_id = ?", (signal_id,)):
            return False
        target = self.strategy.on_candle(hist)
        if not isinstance(target, Decimal) or not (0 <= target <= 1):
            raise EngineError(f"strategy returned target {target!r} outside [0, 1]")
        indicators = self.strategy.indicators(hist)
        signal_price = Decimal(repr(float(hist.close[-1])))
        window_end = last + self._interval + self.cfg.window
        mid = (ticker.bid + ticker.ask) / 2
        submit: tuple[int, Decimal, Decimal, str, RiskDecision] | None = None
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
            side, why = self._decide(target, signal_price)
            if self._active_intent() is not None:
                self._set_outcome(signal_id, "no_action", "intent_active")
            elif side is None:
                self._set_outcome(signal_id, "no_action", why)
            elif now >= window_end:
                self._set_outcome(signal_id, "not_filled", "window_passed")
            else:
                price = self._price(side, ticker)
                sized = self._size(side, target, price, now, mid)
                if isinstance(sized, NoOrder):
                    self._set_outcome(signal_id, sized.outcome, sized.reason)
                    if sized.outcome == "below_minimum":
                        self._risk_event(now, "rejection", "minimums", None, sized.reason, {})
                else:
                    cl = self._new_id()
                    proposed = ProposedOrder(0, 1, False, side, sized, price, cl)  # type: ignore[arg-type]
                    decision = check_order(
                        proposed, self._risk_context(now, ticker, signal_price, None), self.limits
                    )
                    if not decision.approved:
                        self._set_outcome(
                            signal_id, "rejected_by_risk", f"{decision.rule}: {decision.reason}"
                        )
                        self._risk_event(
                            now, "rejection", decision.rule or "", None, decision.reason or "", {}
                        )
                    else:
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
                            window_end_at=iso(window_end),
                            created_at=iso(now),
                            updated_at=iso(now),
                        )
                        if approval == "autonomous":
                            submit = (intent_id, sized, price, cl, decision)
        if submit is not None:
            intent_id, qty, price, cl, decision = submit
            result = self._place(self._intent(intent_id), 1, qty, price, cl, decision, now)
            if result == "cross":
                self._resubmit(self._intent(intent_id), now, ticker)  # AD-5 immediate re-price
            elif result == "rejected":
                self._finish(
                    intent_id, now, "cancelled", "rejected_by_risk", "exchange rejected the order"
                )
        return True

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
        """Persist, then send one approved order (AD-7). Returns the order's state."""
        intent_id = intent["intent_id"]
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
        except OrderOutcomeUnknown:
            self._transition(order_id, "unknown", now)
            return "unknown"
        except (RateLimited, TransientReadError) as exc:
            self._transition(order_id, "rejected", now, reject_reason=f"not sent: {exc}")
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
        for f in self.broker.get_fills(self.cfg.pair, since):
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

    def _sync_order(self, order, now: datetime) -> str:  # noqa: ANN001
        """Bring one live order's state in line with the broker (after fills are ingested)."""
        status = self.broker.find_order(self.cfg.pair, order["cl_ord_id"])
        state = order["state"]
        if status is None:
            if state == "unknown":
                self._transition(order["order_id"], "not_found", now)
                return "not_found"
            return state
        stored = Decimal(
            self.store.one(
                "SELECT filled_qty FROM orders WHERE order_id = ?", (order["order_id"],)
            )[0]
        )
        if stored != status.filled_qty:
            return state  # fills not ingested yet (AD-27): no terminal transition
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
        closed = {"closed_at": iso(now)} if new in ("filled", "cancelled", "rejected") else {}
        self._transition(order["order_id"], new, now, **closed)
        return new

    def _cancel_live(self, intent, now: datetime) -> None:  # noqa: ANN001
        """Cancel the intent's live order, then ingest its final fills (AD-27)."""
        order = self._live_order(intent["intent_id"])
        if order is None:
            return
        if order["state"] in ("open", "partially_filled"):
            self._transition(order["order_id"], "cancel_requested", now)
            self.broker.cancel_order(self.cfg.pair, order["cl_ord_id"])
        self._ingest_fills(intent, now)
        order = self.store.one("SELECT * FROM orders WHERE order_id = ?", (order["order_id"],))
        self._sync_order(order, now)

    def _advance_intent(self, now: datetime, ticker: Ticker) -> None:
        """AD-5/AD-28: ingest fills, then re-price, end the window or run the completion
        phase. A new order is placed only once the previous one is confirmed closed and
        its fills are ingested (AD-27)."""
        intent = self._active_intent()
        if intent is None or intent["state"] == "awaiting_approval":
            return
        intent_id = intent["intent_id"]
        self._ingest_fills(intent, now)
        order = self._live_order(intent_id)
        if order is not None:
            self._sync_order(order, now)
        completing = intent["parent_intent_id"] is not None  # a completion intent

        if not completing and self._target_reached(intent_id):
            self._finish(intent_id, now, "done", "filled", None)
            return
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
            # Exchange halted or feed stale (synthetic candles, audit M1 F-2): keep the
            # resting order (it cannot fill on synthetic candles) instead of cancelling and
            # being refused by the stale_ticker rule; the window end still applies.
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
            proposed = ProposedOrder(intent_id, attempt, False, side, sized, price, cl)
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
            child = self.store.insert(
                "intents",
                parent_intent_id=intent["intent_id"],
                pair=self.cfg.pair,
                side="buy",
                reference_price=dec(mid),
                target_qty=dec(target if isinstance(target, Decimal) else Decimal(0)),
                state="working",
                approval_mode=intent["approval_mode"],
                window_end_at=iso(parse_iso(intent["window_end_at"]) + self.cfg.completion_window),
                created_at=iso(now),
                updated_at=iso(now),
            )
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
        since = self.store.one(
            "SELECT at FROM order_events WHERE order_id = ? AND to_state = 'cancel_requested' "
            "ORDER BY event_id DESC",
            (order["order_id"],),
        )[0]
        if now - parse_iso(since) <= self.cfg.fill_settle_timeout:
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
