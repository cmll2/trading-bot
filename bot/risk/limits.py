"""Risk limits: a frozen, read-only model of the protected ``risk:`` section of config.yaml.

PROTECTED (SAF-04): change only on the operator's explicit request, in a commit that
touches nothing else. No code path writes these values (SAF-05, AD-10): the model is
frozen, it is built once at startup by ``bot.config`` and is never reloaded.

Semantics of each limit: architecture AD-11. Values: PROGRESS.md decisions log.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator


class RiskLimits(BaseModel):
    """Pre-trade limits (FR-30 to FR-36). Immutable: assignment raises."""

    model_config = ConfigDict(frozen=True, extra="forbid", strict=False)

    # FR-31: max position, as a fraction of equity AND as an absolute quote amount.
    max_position_fraction: Decimal = Field(gt=0, le=1)
    max_position_abs_quote: Decimal = Field(gt=0)
    # FR-32: new order intents per UTC day (attempt_no == 1; flatten exempt).
    max_order_intents_per_day: StrictInt = Field(gt=0)
    # Hard cap on exchange submissions per UTC day, re-prices included.
    max_exchange_submissions_per_day: StrictInt = Field(gt=0)
    # Per-intent cap on submissions (first + re-prices), AD-5/AD-10.
    max_submissions_per_intent: StrictInt = Field(gt=0)
    # FR-33: halts, manual reset only.
    max_daily_loss_fraction: Decimal = Field(gt=0, lt=1)
    max_total_drawdown_fraction: Decimal = Field(gt=0, lt=1)
    # FR-34: stale data.
    stale_candle_intervals: StrictInt = Field(gt=0)
    stale_ticker_seconds: StrictInt = Field(gt=0)
    # FR-35: price moved since the signal.
    price_sanity_fraction: Decimal = Field(gt=0, lt=1)
    # FR-36: kill-switch file; resolved to an absolute path by bot.config at load time.
    kill_switch_path: Path

    @model_validator(mode="after")
    def _per_intent_within_daily(self) -> RiskLimits:
        if self.max_submissions_per_intent > self.max_exchange_submissions_per_day:
            raise ValueError("max_submissions_per_intent exceeds max_exchange_submissions_per_day")
        return self
