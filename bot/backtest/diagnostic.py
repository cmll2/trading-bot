"""Report diagnostic: v0 without the EUR 25 absolute position cap (audit M2 F-4).

DIAGNOSTIC ONLY, never used for any decision. Every report re-runs the same strategy, same
parameters and same data with ``max_position_abs_quote`` lifted (the fraction-of-equity
cap stays), so the reader can see how much of the gap to buy-and-hold comes from the
protected cap and how much from the strategy. It is computed with this one fixed rule for
every report, written under a separate ``diagnostics`` key, and does NOT count as a
configuration tried. The protected limits are not changed: this builds a separate,
in-memory ``RiskLimits`` object that only these backtest runs receive; config.yaml, the
loaded ``Settings`` and every dry-run/live path keep the real limits.
"""

from __future__ import annotations

from decimal import Decimal

from bot.risk.limits import RiskLimits

NO_ABS_CAP = Decimal("1E+12")  # effectively unlimited; the fraction cap (100%) still binds

LABEL = "DIAGNOSTIC (not used for any decision): v0 without the EUR 25 absolute position cap"
NOTE = (
    "Same strategy, parameters and data; only the protected absolute cap "
    "(max_position_abs_quote) is lifted in a separate in-memory limits object for these "
    "diagnostic runs. Protected limits unchanged. Not a configuration tried "
    "(configurations_tried stays 1); never used to choose anything."
)


def limits_without_abs_cap(limits: RiskLimits) -> RiskLimits:
    return RiskLimits.model_validate({**limits.model_dump(), "max_position_abs_quote": NO_ABS_CAP})
