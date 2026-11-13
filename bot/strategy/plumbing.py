"""Plumbing strategy: short timeframe, no claimed edge, dry-run only (FR-09, FR-10, AD-30).

It exists to generate enough simulated orders to exercise order handling, restarts and the
dashboard. It must be impossible to run in live: it is absent from
``registry.LIVE_STRATEGIES`` and ``"live"`` is not in its ``allowed_modes``. Implemented at M3.
"""

from __future__ import annotations

from bot.candles import CandleHistory
from bot.strategy.base import Mode, TargetPosition


class Plumbing:
    id = "plumbing"
    timeframe = "15m"
    warmup = 0
    implemented = False  # M3
    allowed_modes: frozenset[Mode] = frozenset({"backtest", "dry-run"})

    def __init__(self, params: object = None) -> None:
        self.params = params

    def on_candle(self, history: CandleHistory) -> TargetPosition:
        raise NotImplementedError("plumbing is implemented at M3 (FR-09)")

    def indicators(self, history: CandleHistory) -> dict[str, float]:
        raise NotImplementedError("plumbing is implemented at M3 (FR-09)")
