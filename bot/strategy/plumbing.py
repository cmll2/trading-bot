"""Plumbing strategy: short timeframe, NO claimed edge, dry-run only (FR-09, FR-10, AD-30).

It exists to generate enough simulated orders to exercise order handling (placement,
re-pricing, fills, window ends, completion), restarts and the dashboard. Its decisions are
deliberately meaningless: on hourly candles it alternates between holding ``target_pct``
percent of equity and holding nothing, switching every ``flip_hours`` hours of candle open
time. Every output it produces is labelled ``plumbing - no edge`` and SIMULATED.

It must be impossible to run in live: it is absent from ``registry.LIVE_STRATEGIES`` and
``"live"`` is not in its ``allowed_modes`` (checked by the registry and the live gate). It
runs only on its own store, ``var/state/dry-run-plumbing.sqlite``, so its trades never feed
the v0 review (AD-30). Pure: a function of the closed candles only (AD-3).
"""

from __future__ import annotations

from decimal import Decimal

from bot.candles import CandleHistory
from bot.strategy.base import Mode, TargetPosition

LABEL = "plumbing - no edge"
_HOUR_MS = 3_600_000


class Plumbing:
    id = "plumbing"
    timeframe = "1h"
    warmup = 0
    label = LABEL
    allowed_modes: frozenset[Mode] = frozenset({"backtest", "dry-run"})

    def __init__(self, params: dict[str, int] | None = None) -> None:
        params = dict(params or {})
        self.flip_hours = int(params.get("flip_hours", 2))
        self.target_pct = int(params.get("target_pct", 50))
        if self.flip_hours < 1:
            raise ValueError("plumbing flip_hours must be >= 1")
        if not 0 < self.target_pct <= 100:
            raise ValueError("plumbing target_pct must be in (0, 100]")

    def _phase(self, history: CandleHistory) -> int:
        if not len(history):
            return 1
        hour = int(history.open_at[-1]) // _HOUR_MS
        return (hour // self.flip_hours) % 2

    def on_candle(self, history: CandleHistory) -> TargetPosition:
        if self._phase(history) == 0:
            return Decimal(self.target_pct) / 100
        return Decimal(0)

    def indicators(self, history: CandleHistory) -> dict[str, float]:
        return {"phase": float(self._phase(history)), "no_edge": 1.0}
