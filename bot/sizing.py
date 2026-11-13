"""Order sizing (CON-02, CON-03, AD-13). Pure; recomputed at every submission.

Quantities are floored to the market's amount step (never rounded up). Minimums and
precision come from ``MarketRules`` (exchange metadata), never hardcoded.

- buy qty = floor_step( min(budget, free quote) / ((1 + fee) x (1 + slippage)) / price ),
  budget = min(target x equity, max_position_fraction x equity, max_position_abs_quote)
  - current exposure (position + resting buys, at ``price``);
- sell qty = the full base position, floored to the step (target 0: long-or-flat).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_FLOOR, Decimal

from bot.broker.base import MarketRules
from bot.broker.fill_model import BPS
from bot.risk.limits import RiskLimits


@dataclass(frozen=True)
class NoOrder:
    """No order can be sized; ``reason`` is stored with the signal outcome."""

    outcome: str  # signal outcome, e.g. "below_minimum" or "no_action"
    reason: str


def floor_step(x: Decimal, step: Decimal) -> Decimal:
    if x <= 0:
        return Decimal(0)
    return (x / step).to_integral_value(rounding=ROUND_FLOOR) * step


@dataclass(frozen=True)
class SizingInput:
    target: Decimal  # fraction of equity in [0, 1]
    equity: Decimal
    free_quote: Decimal
    position: Decimal
    resting_buy_qty: Decimal
    price: Decimal  # the limit price the order will carry
    fee_rate: Decimal
    slippage_bps: Decimal


def buy_qty(s: SizingInput, rules: MarketRules, limits: RiskLimits) -> Decimal | NoOrder:
    cap = min(
        s.target * s.equity,
        limits.max_position_fraction * s.equity,
        limits.max_position_abs_quote,
    )
    budget = cap - (s.position + s.resting_buy_qty) * s.price
    spend = min(budget, s.free_quote)
    if spend <= 0:
        return NoOrder("no_action", f"no budget (cap {cap}, free quote {s.free_quote})")
    unit = s.price * (1 + s.fee_rate) * (1 + s.slippage_bps * BPS)
    qty = floor_step(spend / unit, rules.amount_step)
    if qty <= 0:
        return NoOrder("below_minimum", f"spend {spend} buys less than one amount step")
    return qty


def sell_qty(position: Decimal, rules: MarketRules) -> Decimal | NoOrder:
    qty = floor_step(position, rules.amount_step)
    if qty <= 0:
        return NoOrder("no_action", "no base position to sell")
    return qty
