"""Immutable view of closed candles (FR-04, AD-3).

A strategy sees market data only through ``CandleHistory``: a frozen copy of the candles
that are **closed** at ``as_of``, i.e. ``open_at + interval <= as_of``. A candle becomes
visible exactly at its close instant and is invisible one microsecond before.

Every array is a private copy marked read-only, so item assignment raises ``ValueError``
and the source frame is never changed; ``to_frame()`` returns a fresh copy.

This module is neutral ground between data/ and strategy/: it imports nothing from
``bot.data``, ``bot.broker``, ``bot.engine``, ``bot.store`` or any network library
(enforced by ``tests/test_candles.py``), so strategy/ may import it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import numpy as np
import pandas as pd

from bot.config import TIMEFRAME_SECONDS

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_US = timedelta(microseconds=1)
PRICE_FIELDS = ("open", "high", "low", "close", "volume")
_DTYPES: dict[str, type] = {
    "open_at": np.int64,
    **{f: np.float64 for f in PRICE_FIELDS},
    "synthetic": np.bool_,
}


def _require_utc(t: datetime) -> datetime:
    if not isinstance(t, datetime) or t.tzinfo is None or t.utcoffset() != timedelta(0):
        raise ValueError(f"as_of must be a timezone-aware UTC datetime, got {t!r}")
    return t


def _readonly(values: object, dtype: type) -> np.ndarray:
    """A private read-only copy backed by an immutable ``bytes`` buffer: neither the array
    nor its ``base`` can be made writeable again."""
    return np.frombuffer(np.asarray(values, dtype=dtype).tobytes(), dtype=dtype)


def _epoch_us(t: datetime) -> int:
    return (t - _EPOCH) // _US


@dataclass(frozen=True, eq=False)
class CandleHistory:
    """Closed candles of one timeframe as of ``as_of``, oldest first.

    ``open_at`` is int64 milliseconds since the Unix epoch (UTC); ``synthetic`` marks
    flat no-trade candles (AD-18). Build it with ``from_frame``; the constructor only
    accepts arrays that are already read-only and of the right dtype.
    """

    timeframe: str
    as_of: datetime
    open_at: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray
    synthetic: np.ndarray

    def __post_init__(self) -> None:
        if self.timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"unknown timeframe {self.timeframe!r}")
        _require_utc(self.as_of)
        n = len(self.open_at)
        for name, dtype in _DTYPES.items():
            arr = getattr(self, name)
            if not isinstance(arr, np.ndarray) or arr.ndim != 1 or arr.dtype != dtype:
                raise ValueError(f"CandleHistory.{name} must be a 1-D {np.dtype(dtype)} array")
            if arr.flags.writeable or not isinstance(arr.base, bytes):
                raise ValueError(
                    f"CandleHistory.{name} must be read-only and bytes-backed; use from_frame"
                )
            if len(arr) != n:
                raise ValueError(f"CandleHistory.{name} has {len(arr)} rows, expected {n}")
        cutoff_us = _epoch_us(self.as_of)
        if n and (int(self.open_at.max()) * 1000 + self.interval_us > cutoff_us):
            raise ValueError("CandleHistory holds a candle that is not closed at as_of")

    @property
    def interval_us(self) -> int:
        return TIMEFRAME_SECONDS[self.timeframe] * 1_000_000

    @classmethod
    def from_frame(cls, df: pd.DataFrame, timeframe: str, as_of: datetime) -> CandleHistory:
        """Copy the candles of ``df`` closed at ``as_of`` (``open_at + interval <= as_of``).

        ``df`` has the cache columns (``open_at`` timezone-aware, prices, ``source``); it
        is not modified. Row order is kept.
        """
        _require_utc(as_of)
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"unknown timeframe {timeframe!r}")
        open_at = df["open_at"]
        if not isinstance(open_at.dtype, pd.DatetimeTZDtype):
            raise ValueError(f"open_at must be timezone-aware UTC, got dtype {open_at.dtype}")
        # Nanoseconds are lossless for every datetime unit, so a sub-millisecond offset is
        # seen here instead of being rounded away (rounding could reveal a candle early).
        open_ns = open_at.dt.tz_convert("UTC").dt.as_unit("ns").astype("int64").to_numpy()
        interval_us = TIMEFRAME_SECONDS[timeframe] * 1_000_000
        misaligned = open_ns % (interval_us * 1000) != 0
        if misaligned.any():
            bad = open_at.iloc[int(misaligned.argmax())]
            raise ValueError(f"open_at {bad} is not aligned to the {timeframe} interval")
        open_ms = open_ns // 1_000_000
        # Microseconds fit easily in int64 (~1.8e15 today), so the comparison is exact.
        closed = open_ms * 1000 + interval_us <= _epoch_us(as_of)
        synthetic = (df["source"] == "synthetic").fillna(False).to_numpy(dtype=bool)
        return cls(
            timeframe=timeframe,
            as_of=as_of,
            open_at=_readonly(open_ms[closed], np.int64),
            **{
                f: _readonly(df[f].to_numpy(dtype=np.float64)[closed], np.float64)
                for f in PRICE_FIELDS
            },
            synthetic=_readonly(synthetic[closed], np.bool_),
        )

    def __len__(self) -> int:
        return len(self.open_at)

    @property
    def last_open_at(self) -> datetime | None:
        """``open_at`` of the newest closed candle, or None when empty."""
        if not len(self):
            return None
        return _EPOCH + timedelta(milliseconds=int(self.open_at[-1]))

    def to_frame(self) -> pd.DataFrame:
        """A fresh, writable DataFrame copy (``open_at`` as timestamp[ms, UTC])."""
        return pd.DataFrame(
            {
                "open_at": pd.to_datetime(self.open_at.copy(), unit="ms", utc=True).as_unit("ms"),
                **{f: getattr(self, f).copy() for f in PRICE_FIELDS},
                "synthetic": self.synthetic.copy(),
            }
        )
