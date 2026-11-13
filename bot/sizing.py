"""Order sizing (CON-02, CON-03, AD-13). Pure; recomputed at every submission.

Quantities are floored to the market's amount step (never rounded up). Minimums and
precision come from ``MarketRules`` (exchange metadata), never hardcoded.

- buy qty = floor_step( min(budget, free quote) / ((1 + fee) x (1 + slippage)) / price ),
  budget = min(target x equity, max_position_fraction x equity, max_position_abs_quote)
  - current exposure (position + resting buys, at ``price``);
- sell qty = the full base position, floored to the step (target 0: long-or-flat).

Reject, never round up (FR-13, CON-02): a buy whose qty < amount_min or qty x price <
cost_min, or whose resulting position would not stay sellable after the worst loss the
limits allow (P >= amount_min and P x price x (1 - max_total_drawdown) >= cost_min), is
``NoOrder("below_minimum")``; so is a sell below the minimums. The engine stores the
reason with the signal and writes a ``rejection`` risk event (rule ``minimums``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

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
    if qty < rules.amount_min:
        return NoOrder("below_minimum", f"buy qty {qty} < exchange amount_min {rules.amount_min}")
    if qty * s.price < rules.cost_min:
        return NoOrder(
            "below_minimum", f"buy cost {qty * s.price} < exchange cost_min {rules.cost_min}"
        )
    after = s.position + qty
    if not sellable(after, s.price, rules, limits):
        return NoOrder(
            "below_minimum",
            f"position {after} would not stay sellable after a "
            f"{limits.max_total_drawdown_fraction} loss (threshold "
            f"{sellable_threshold(s.price, rules, limits)})",
        )
    return qty


def sell_qty(position: Decimal, price: Decimal, rules: MarketRules) -> Decimal | NoOrder:
    qty = floor_step(position, rules.amount_step)
    if qty <= 0:
        return NoOrder("no_action", "no base position to sell")
    if qty < rules.amount_min:
        return NoOrder("below_minimum", f"sell qty {qty} < exchange amount_min {rules.amount_min}")
    if qty * price < rules.cost_min:
        return NoOrder(
            "below_minimum", f"sell cost {qty * price} < exchange cost_min {rules.cost_min}"
        )
    return qty


def ceil_step(x: Decimal, step: Decimal) -> Decimal:
    return (x / step).to_integral_value(rounding=ROUND_CEILING) * step


def sellable_threshold(price: Decimal, rules: MarketRules, limits: RiskLimits) -> Decimal:
    """Smallest position that stays sellable after the worst loss the limits allow (AD-13):
    P >= amount_min and P x price x (1 - max_total_drawdown) >= cost_min."""
    worst = price * (1 - limits.max_total_drawdown_fraction)
    return max(rules.amount_min, rules.cost_min / worst)


def sellable(position: Decimal, price: Decimal, rules: MarketRules, limits: RiskLimits) -> bool:
    return position >= sellable_threshold(price, rules, limits)


def completion_qty(
    position: Decimal, price: Decimal, rules: MarketRules, limits: RiskLimits
) -> Decimal | NoOrder:
    """AD-28 completion phase: the smallest buy that makes the position sellable and is
    itself a valid order (>= amount_min, >= cost_min). Rounded UP to the step only to reach
    that threshold; the order still passes every risk check (cash, max position)."""
    gap = sellable_threshold(price, rules, limits) - position
    if gap <= 0:
        return NoOrder("no_action", "position already sellable")
    return ceil_step(max(gap, rules.amount_min, rules.cost_min / price), rules.amount_step)
