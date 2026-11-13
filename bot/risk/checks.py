"""Pre-trade risk checks (FR-30 to FR-36, AD-10, AD-11). PROTECTED (SAF-04).

Pure: ``check_order(proposed, ctx, limits) -> RiskDecision``. No I/O, no clock: the engine
assembles ``RiskContext`` (time included) from the store and passes it in. Every exchange
submission, re-prices and flattens included, passes through it; broker adapters refuse to
send an order unless ``decision.approved`` and ``decision.cl_ord_id == request.cl_ord_id``.

Rules, checked in this order; the first failing rule rejects (AD-11 table):

==================  ===============================================================  =======
rule                rejects when                                                     flatten
==================  ===============================================================  =======
invalid_order       qty or price <= 0, attempt_no < 1, or a flatten that is not a    applies
                    sell (a flatten's exemptions never cover a buy)
kill_switch         the kill-switch file is engaged                                  exempt
halt                any halt is active (daily_loss, total_drawdown, ...)            exempt
market_status       market status is not ``online``                                  applies
minimums            qty < amount_min, or qty x limit_price < cost_min (never        applies
                    rounded up, CON-02)
max_orders_per_day  attempt 1 of a new intent and intents already created on the     exempt
                    UTC day (this one excluded) >= max_order_intents_per_day
max_submissions     submissions already made today >= max_exchange_submissions_     applies
                    per_day, or by this intent >= max_submissions_per_intent
stale_candle        latest closed candle is synthetic, or now - its open_at >        exempt
                    stale_candle_intervals x interval
stale_ticker        now - ticker.ts > stale_ticker_seconds                           applies
price_sanity        abs(mid - reference_price) / reference_price > price_sanity_    applies
                    fraction
max_position        buy only: (position + resting buys + qty) x limit_price >        n/a
                    min(max_position_fraction x equity, max_position_abs_quote)
==================  ===============================================================  =======
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from bot.risk.limits import RiskLimits


@dataclass(frozen=True)
class RiskDecision:
    """Outcome of a pre-trade check for one submission (AD-10)."""

    approved: bool
    cl_ord_id: str
    rule: str | None = None  # rule that rejected, None when approved
    reason: str | None = None


@dataclass(frozen=True)
class ProposedOrder:
    """One exchange submission the engine wants to make (AD-10)."""

    intent_id: int
    attempt_no: int  # 1 for the intent's first submission, then 2, 3, ... for re-prices
    is_flatten: bool
    side: Literal["buy", "sell"]
    qty: Decimal
    limit_price: Decimal
    cl_ord_id: str


@dataclass(frozen=True)
class RiskContext:
    """Everything a check needs, assembled by the engine from the store (AD-10).

    Counts exclude the submission being checked. ``position_qty`` is the derived base
    position; ``resting_buy_qty`` the unfilled quantity of the bot's open buy orders.
    """

    now: datetime
    equity: Decimal
    position_qty: Decimal
    resting_buy_qty: Decimal
    intents_today: int
    submissions_today: int
    intent_submissions: int
    last_candle_open_at: datetime | None
    candle_interval: timedelta
    last_candle_synthetic: bool
    ticker_ts: datetime
    mid: Decimal
    reference_price: Decimal
    active_halts: tuple[str, ...]
    kill_switch_engaged: bool
    market_status: str
    amount_min: Decimal
    cost_min: Decimal


def _reject(p: ProposedOrder, rule: str, reason: str) -> RiskDecision:
    return RiskDecision(approved=False, cl_ord_id=p.cl_ord_id, rule=rule, reason=reason)


def check_order(proposed: ProposedOrder, ctx: RiskContext, limits: RiskLimits) -> RiskDecision:
    """Check one proposed submission against every rule of AD-11 (see module table)."""
    p, flat = proposed, proposed.is_flatten
    if p.qty <= 0 or p.limit_price <= 0:
        return _reject(p, "invalid_order", f"qty {p.qty} and price {p.limit_price} must be > 0")
    if p.attempt_no < 1:
        return _reject(p, "invalid_order", f"attempt_no {p.attempt_no} must be >= 1")
    if flat and p.side != "sell":
        # Flatten is the risk-reducing exit (AD-12, AD-25): its exemptions never cover a buy.
        return _reject(p, "invalid_order", "a flatten order must be a sell")

    if ctx.kill_switch_engaged and not flat:
        return _reject(p, "kill_switch", "kill switch is engaged")
    if ctx.active_halts and not flat:
        return _reject(p, "halt", f"trading halted: {', '.join(ctx.active_halts)}")

    if ctx.market_status != "online":
        return _reject(p, "market_status", f"market status is {ctx.market_status!r}")

    cost = p.qty * p.limit_price
    if p.qty < ctx.amount_min:
        return _reject(p, "minimums", f"qty {p.qty} < exchange amount_min {ctx.amount_min}")
    if cost < ctx.cost_min:
        return _reject(p, "minimums", f"cost {cost} < exchange cost_min {ctx.cost_min}")

    if p.attempt_no == 1 and not flat and ctx.intents_today >= limits.max_order_intents_per_day:
        return _reject(
            p,
            "max_orders_per_day",
            f"{ctx.intents_today} intents already today (limit {limits.max_order_intents_per_day})",
        )
    if ctx.submissions_today >= limits.max_exchange_submissions_per_day:
        return _reject(
            p,
            "max_submissions",
            f"{ctx.submissions_today} submissions already today (limit "
            f"{limits.max_exchange_submissions_per_day})",
        )
    if ctx.intent_submissions >= limits.max_submissions_per_intent:
        return _reject(
            p,
            "max_submissions",
            f"{ctx.intent_submissions} submissions already for intent {p.intent_id} (limit "
            f"{limits.max_submissions_per_intent})",
        )

    if not flat:
        if ctx.last_candle_open_at is None:
            return _reject(p, "stale_candle", "no closed candle")
        if ctx.last_candle_synthetic:
            return _reject(
                p, "stale_candle", f"latest candle {ctx.last_candle_open_at} is synthetic"
            )
        age = ctx.now - ctx.last_candle_open_at
        if age > limits.stale_candle_intervals * ctx.candle_interval:
            return _reject(
                p,
                "stale_candle",
                f"latest candle {ctx.last_candle_open_at} is {age} old (limit "
                f"{limits.stale_candle_intervals} intervals)",
            )

    ticker_age = ctx.now - ctx.ticker_ts
    if ticker_age > timedelta(seconds=limits.stale_ticker_seconds):
        return _reject(
            p,
            "stale_ticker",
            f"ticker is {ticker_age} old (limit {limits.stale_ticker_seconds} s)",
        )

    if ctx.reference_price <= 0:
        return _reject(p, "price_sanity", f"reference price {ctx.reference_price} is not > 0")
    moved = abs(ctx.mid - ctx.reference_price) / ctx.reference_price
    if moved > limits.price_sanity_fraction:
        return _reject(
            p,
            "price_sanity",
            f"mid {ctx.mid} moved {moved:.4%} from reference {ctx.reference_price} (limit "
            f"{limits.price_sanity_fraction:%})",
        )

    if p.side == "buy":
        cap = min(limits.max_position_fraction * ctx.equity, limits.max_position_abs_quote)
        exposure = (ctx.position_qty + ctx.resting_buy_qty + p.qty) * p.limit_price
        if exposure > cap:
            return _reject(
                p,
                "max_position",
                f"exposure {exposure} would exceed cap {cap} (min of "
                f"{limits.max_position_fraction} x equity {ctx.equity} and "
                f"{limits.max_position_abs_quote})",
            )

    return RiskDecision(approved=True, cl_ord_id=p.cl_ord_id)
