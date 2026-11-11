"""Pre-trade risk checks (FR-30 to FR-35, AD-10, AD-11). Implemented at M3.

Pure: ``check_order(proposed, ctx, limits) -> RiskDecision``. Every exchange submission,
re-prices and flattens included, passes through it; broker adapters refuse to send an
order unless ``decision.approved`` and ``decision.cl_ord_id == request.cl_ord_id``.
"""

from __future__ import annotations

from dataclasses import dataclass

from bot.risk.limits import RiskLimits


@dataclass(frozen=True)
class RiskDecision:
    """Outcome of a pre-trade check for one submission (AD-10)."""

    approved: bool
    cl_ord_id: str
    rule: str | None = None  # rule that rejected, None when approved
    reason: str | None = None


def check_order(proposed: object, ctx: object, limits: RiskLimits) -> RiskDecision:
    """Check one proposed submission against every rule of AD-11. M3."""
    raise NotImplementedError("risk.check_order is implemented at M3 (FR-30..FR-35)")
