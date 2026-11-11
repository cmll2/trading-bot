"""MarketData port (architecture paradigm; AD-3, AD-18) and its replay adapter.

``closed_candles(pair, timeframe)`` returns a ``CandleHistory`` of the candles closed at the
adapter's clock time; the caller never passes a time, so no caller can ask for the future.

``ReplayMarketData`` serves the local Parquet cache (backtest, AD-1). Each (pair, timeframe)
file is read once, validated with ``validate_frame`` (fail loudly, never repair) and hashed
with ``data_hash`` (NFR-02, AD-21). The cache may hold candles after the clock time: the
closed filter of ``CandleHistory`` hides them. ``CcxtMarketData`` (dry-run, live) arrives
with the engine at M3.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

import pandas as pd

from bot.candles import CandleHistory
from bot.clock import Clock
from bot.config import DataSettings
from bot.data.cache import cache_path, data_hash
from bot.data.validate import DataValidationError, read_cache_checked, validate_frame


class MarketData(Protocol):
    """Source of closed candles. Tickers arrive with the engine at M3."""

    def closed_candles(self, pair: str, timeframe: str) -> CandleHistory: ...


class ReplayMarketData:
    """``MarketData`` over the Parquet cache, timed by ``clock`` (a ``SimClock`` in backtest)."""

    def __init__(
        self,
        var_dir: Path,
        pairs: Iterable[str],
        clock: Clock,
        data_settings: DataSettings,
    ) -> None:
        if isinstance(pairs, str):
            raise TypeError("pairs must be a collection of symbols, not a single string")
        self._var_dir = Path(var_dir)
        self._pairs = tuple(pairs)
        self._clock = clock
        self._data_settings = data_settings
        self._frames: dict[tuple[str, str], pd.DataFrame] = {}
        self._hashes: dict[tuple[str, str], str] = {}

    def _frame(self, pair: str, timeframe: str) -> pd.DataFrame:
        if pair not in self._pairs:
            raise ValueError(f"unknown pair {pair!r}; configured pairs are {list(self._pairs)}")
        if timeframe not in self._data_settings.timeframes:
            raise ValueError(
                f"unknown timeframe {timeframe!r}; configured data.timeframes are "
                f"{list(self._data_settings.timeframes)}"
            )
        key = (pair, timeframe)
        if key not in self._frames:
            path = cache_path(self._var_dir, pair, timeframe)
            frame = read_cache_checked(path)
            if frame is None:
                raise DataValidationError(f"no cache for {pair} {timeframe} ({path})")
            validate_frame(frame, timeframe, self._data_settings)
            self._frames[key] = frame
            self._hashes[key] = data_hash(frame)
        return self._frames[key]

    def closed_candles(self, pair: str, timeframe: str) -> CandleHistory:
        return CandleHistory.from_frame(self._frame(pair, timeframe), timeframe, self._clock.now())

    def data_hash(self, pair: str, timeframe: str) -> str:
        """sha256 hex of the whole cached frame served for (pair, timeframe)."""
        self._frame(pair, timeframe)
        return self._hashes[(pair, timeframe)]
