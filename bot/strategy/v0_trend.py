"""v0 strategy: slow long-or-flat trend filter on daily closes (FR-07, AD-3).

Long (target 1) when the last CLOSED daily close is above the simple moving average of the
last ``sma_days`` daily closes (that close included); flat (target 0) otherwise, and flat
until ``sma_days`` closed candles exist. ``sma_days`` is fixed in config.yaml
(``strategy.params``) before any evaluation and never tuned (PROGRESS decisions log,
2026-11-13); the classic slow trend filter of the literature cited in
docs/research/pair-selection.md.

Pure: reads only the ``CandleHistory`` it is given (closed candles only); no broker, clock,
network or global state.
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal

import numpy as np

from bot.candles import CandleHistory
from bot.strategy.base import Mode, TargetPosition


class V0Trend:
    id = "v0_trend"
    timeframe = "1d"
    allowed_modes: frozenset[Mode] = frozenset({"backtest", "dry-run", "live"})

    def __init__(self, params: Mapping[str, int]) -> None:
        if set(params) != {"sma_days"}:
            raise ValueError(f"v0_trend takes exactly one parameter, sma_days; got {dict(params)}")
        sma_days = params["sma_days"]
        if not isinstance(sma_days, int) or isinstance(sma_days, bool) or sma_days < 2:
            raise ValueError(f"sma_days must be an integer >= 2, got {sma_days!r}")
        self.sma_days = sma_days
        self.warmup = sma_days  # closed candles needed before the first non-flat target

    def _sma(self, history: CandleHistory) -> float | None:
        if history.timeframe != self.timeframe:
            raise ValueError(f"v0_trend needs {self.timeframe} candles, got {history.timeframe}")
        if len(history) < self.sma_days:
            return None
        return float(np.mean(history.close[-self.sma_days :]))

    def on_candle(self, history: CandleHistory) -> TargetPosition:
        sma = self._sma(history)
        if sma is None:
            return Decimal(0)
        return Decimal(1) if float(history.close[-1]) > sma else Decimal(0)

    def indicators(self, history: CandleHistory) -> dict[str, float]:
        sma = self._sma(history)
        out = {"close": float(history.close[-1])} if len(history) else {}
        if sma is not None:
            out[f"sma_{self.sma_days}"] = sma
        return out
