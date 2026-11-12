"""v0 strategy: slow long-or-flat trend filter on daily candles (FR-07). Implemented at M2."""

from __future__ import annotations

from bot.candles import CandleHistory
from bot.strategy.base import Mode, TargetPosition


class V0Trend:
    id = "v0_trend"
    timeframe = "1d"
    warmup = 0  # set at M2 from the fixed parameters
    allowed_modes: frozenset[Mode] = frozenset({"backtest", "dry-run", "live"})

    def on_candle(self, history: CandleHistory) -> TargetPosition:
        raise NotImplementedError("v0_trend is implemented at M2 (FR-07)")

    def indicators(self, history: CandleHistory) -> dict[str, float]:
        raise NotImplementedError("v0_trend is implemented at M2 (FR-07)")
