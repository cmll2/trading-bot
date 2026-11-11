"""Test doubles for the data pipeline. No network: the fake replaces the ccxt client."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from bot.data.cache import normalize

DAY_MS = 86_400_000
START = datetime(2024, 1, 1, tzinfo=UTC)
START_MS = int(START.timestamp() * 1000)


def candle(ts: int, base: float = 100.0) -> list[float | int]:
    """A deterministic OHLCV row ``[ts, o, h, l, c, v]`` for ``ts`` (ms)."""
    k = (ts // 60_000) % 1000
    o = base + k
    return [ts, o, o + 2.0, o - 1.0, o + 0.5, 1.25]


def candles(start_ms: int, n: int, step_ms: int = DAY_MS) -> list[list[float | int]]:
    return [candle(start_ms + i * step_ms) for i in range(n)]


@dataclass
class FakeExchange:
    """Scripted ``fetch_ohlcv``: each call pops the next page (a list) or raises the next
    exception. When the script is exhausted it returns an empty page."""

    script: list[Any] = field(default_factory=list)
    calls: list[dict[str, Any]] = field(default_factory=list)

    def fetch_ohlcv(
        self,
        symbol: str,
        timeframe: str = "1m",
        since: int | None = None,
        limit: int | None = None,
        params: dict[str, Any] | None = None,
    ) -> list[list[float | int]]:
        self.calls.append(
            {
                "symbol": symbol,
                "timeframe": timeframe,
                "since": since,
                "limit": limit,
                "params": params,
            }
        )
        if not self.script:
            return []
        item = self.script.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


def ms(ts: pd.Timestamp | datetime) -> int:
    return int(pd.Timestamp(ts).timestamp() * 1000)


def frame(n: int = 3, start_ms: int = START_MS, step: int = DAY_MS) -> pd.DataFrame:
    """A valid normalised cache frame of ``n`` consecutive API candles."""
    rows = [candle(start_ms + i * step) for i in range(n)]
    return normalize(
        pd.DataFrame(
            {
                "open_at": pd.to_datetime([r[0] for r in rows], unit="ms", utc=True),
                "open": [r[1] for r in rows],
                "high": [r[2] for r in rows],
                "low": [r[3] for r in rows],
                "close": [r[4] for r in rows],
                "volume": [r[5] for r in rows],
                "trades": pd.array([pd.NA] * n, dtype="Int64"),
                "source": ["api"] * n,
            }
        )
    )
