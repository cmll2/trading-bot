"""Strategy port (FR-05, FR-06, AD-3).

``on_candle(history) -> TargetPosition``: a fraction of equity in [0, 1], computed from an
immutable view of closed candles only.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal, Protocol

Mode = Literal["backtest", "dry-run", "live"]
MODES: frozenset[Mode] = frozenset({"backtest", "dry-run", "live"})

TargetPosition = Decimal  # in [0, 1]


class Strategy(Protocol):
    id: str
    timeframe: str
    warmup: int
    allowed_modes: frozenset[Mode]

    def on_candle(self, history: object) -> TargetPosition: ...

    def indicators(self, history: object) -> dict[str, float]: ...
