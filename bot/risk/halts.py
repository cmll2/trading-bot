"""Daily-loss and total-drawdown halts (FR-33, AD-11, AD-12). PROTECTED (SAF-04).

Pure: ``evaluate_halts(ctx, limits) -> list[HaltTrigger]`` reports the halt rules breached
by the current equity. It keeps no state: persisting a halt (and keeping it until
``bot reset-halt``) is the engine's and store's job; a halt never expires on a timer, so a
later recovery of equity does not clear it (``check_order`` keeps rejecting while the
halt is listed in ``RiskContext.active_halts``).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from bot.risk.limits import RiskLimits


@dataclass(frozen=True)
class HaltContext:
    equity: Decimal  # derived equity marked at the ticker mid
    day_open_equity: Decimal  # first equity snapshot of the UTC day (AD-11)
    baseline_equity: Decimal  # active equity_baselines row (start baseline unless rebased)


@dataclass(frozen=True)
class HaltTrigger:
    rule: str  # "daily_loss" | "total_drawdown"
    reason: str


def evaluate_halts(ctx: HaltContext, limits: RiskLimits) -> list[HaltTrigger]:
    """Return the halt triggers breached in ``ctx`` (equity at or below the threshold)."""
    out: list[HaltTrigger] = []
    daily_floor = (1 - limits.max_daily_loss_fraction) * ctx.day_open_equity
    if ctx.equity <= daily_floor:
        out.append(
            HaltTrigger(
                "daily_loss",
                f"equity {ctx.equity} <= {daily_floor} ({limits.max_daily_loss_fraction} below "
                f"day-open equity {ctx.day_open_equity})",
            )
        )
    dd_floor = (1 - limits.max_total_drawdown_fraction) * ctx.baseline_equity
    if ctx.equity <= dd_floor:
        out.append(
            HaltTrigger(
                "total_drawdown",
                f"equity {ctx.equity} <= {dd_floor} ({limits.max_total_drawdown_fraction} below "
                f"baseline {ctx.baseline_equity})",
            )
        )
    return out
