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

import numpy as np
import pandas as pd

from bot.candles import CandleHistory
from bot.clock import Clock
from bot.config import TIMEFRAME_SECONDS, DataSettings
from bot.data.cache import cache_path, data_hash
from bot.data.validate import DataValidationError, read_cache_checked, validate_frame


class MarketData(Protocol):
    """Source of closed candles. Tickers come from the Broker port (``get_ticker``)."""

    def closed_candles(
        self, pair: str, timeframe: str, limit: int | None = None
    ) -> CandleHistory: ...


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
        self._open_ns: dict[tuple[str, str], np.ndarray] = {}
        self._frames_only = False

    @classmethod
    def from_frames(
        cls,
        frames: dict[tuple[str, str], pd.DataFrame],
        clock: Clock,
        data_settings: DataSettings,
    ) -> ReplayMarketData:
        """Serve already loaded and validated frames (backtest dataset, AD-4).

        The frames are the caller's (``bot.backtest.dataset``); they are not re-read from
        disk, so whatever the dataset loader produced is exactly what every consumer sees.
        """
        md = cls(Path("."), sorted({p for p, _ in frames}), clock, data_settings)
        md._frames_only = True  # never fall back to reading the cache from disk
        for key, frame in frames.items():
            md._frames[key] = frame
            md._hashes[key] = data_hash(frame)
        return md

    def _frame(self, pair: str, timeframe: str) -> pd.DataFrame:
        if pair not in self._pairs:
            raise ValueError(f"unknown pair {pair!r}; configured pairs are {list(self._pairs)}")
        if timeframe not in self._data_settings.timeframes:
            raise ValueError(
                f"unknown timeframe {timeframe!r}; configured data.timeframes are "
                f"{list(self._data_settings.timeframes)}"
            )
        key = (pair, timeframe)
        if key not in self._frames and self._frames_only:
            raise ValueError(f"{pair} {timeframe} is not in the loaded dataset")
        if key not in self._frames:
            path = cache_path(self._var_dir, pair, timeframe)
            frame = read_cache_checked(path)
            if frame is None:
                raise DataValidationError(f"no cache for {pair} {timeframe} ({path})")
            validate_frame(frame, timeframe, self._data_settings)
            self._frames[key] = frame
            self._hashes[key] = data_hash(frame)
        return self._frames[key]

    def closed_candles(self, pair: str, timeframe: str, limit: int | None = None) -> CandleHistory:
        """Candles closed at the clock time; with ``limit``, only the newest ``limit``."""
        frame = self._frame(pair, timeframe)
        key = (pair, timeframe)
        if key not in self._open_ns:
            ns = frame["open_at"].dt.tz_convert("UTC").dt.as_unit("ns").astype("int64")
            self._open_ns[key] = ns.to_numpy()
        now = self._clock.now()
        # Rows with open_at + interval <= now; CandleHistory.from_frame re-checks exactly.
        cutoff = pd.Timestamp(now).as_unit("ns").value - TIMEFRAME_SECONDS[timeframe] * 10**9
        stop = int(np.searchsorted(self._open_ns[key], cutoff, side="right"))
        start = 0 if limit is None else max(0, stop - limit)
        return CandleHistory.from_frame(frame.iloc[start:stop], timeframe, now)

    def data_hash(self, pair: str, timeframe: str) -> str:
        """sha256 hex of the whole cached frame served for (pair, timeframe)."""
        self._frame(pair, timeframe)
        return self._hashes[(pair, timeframe)]
