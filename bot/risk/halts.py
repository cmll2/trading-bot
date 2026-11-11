"""Daily-loss and total-drawdown halts (FR-33, AD-11, AD-12). Implemented at M3.

Pure: ``evaluate_halts(ctx, limits) -> list[HaltTrigger]``. Halts never expire on a timer;
only ``bot reset-halt`` clears them.
"""

from __future__ import annotations

from bot.risk.limits import RiskLimits


def evaluate_halts(ctx: object, limits: RiskLimits) -> list[object]:
    """Return the halt triggers breached in ``ctx``. M3."""
    raise NotImplementedError("risk.evaluate_halts is implemented at M3 (FR-33)")
