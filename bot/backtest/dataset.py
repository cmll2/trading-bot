"""Backtest dataset loader: the ONLY way candles enter a backtest (AD-4, NFR-02).

``load_dataset`` reads each needed timeframe from the Parquet cache, validates the whole
file (fail loudly, never repair), slices it to ``[start, end)`` and hashes the slice. The
backtest never sees rows at or after ``end``: by default ``end`` is the holdout start, so
holdout data is not even loaded (FR-15).

``replace_after`` is the look-ahead guard's hook: every row whose ``open_at`` is at or
after that instant is replaced by a seeded random walk, in the frames this function
returns. Because nothing else loads data, a strategy holding a reference to "the loaded
frame" (a closure, a global, a precomputed column) sees the replaced future too, so any
use of it changes past targets and is caught (``bot.backtest.lookahead``).

Validated raw frames are cached per process (keyed by path, size and mtime); every call
returns fresh copies, so no caller can alter another run's data.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from bot.config import TIMEFRAME_SECONDS, Settings
from bot.data.cache import cache_path, data_hash
from bot.data.validate import DataValidationError, read_cache_checked, validate_frame

# Known real-data anomalies reported with every result (audit M1 F-3). Signals use closes,
# so these only matter if a fill is simulated on such a candle; the report lists both.
KNOWN_ANOMALIES: tuple[tuple[str, str], ...] = (
    (
        "2018-01-13",
        "post-outage print: first trade at 20,000 EUR vs ~11,400-11,800 around it sets the "
        "1d/4h open and high (audit M1 F-3)",
    ),
)

_RAW_CACHE: dict[tuple[str, str, int, int], pd.DataFrame] = {}


@dataclass(frozen=True)
class Dataset:
    pair: str
    start: datetime  # inclusive, 00:00 UTC
    end: datetime  # exclusive, 00:00 UTC
    frames: dict[str, pd.DataFrame]  # timeframe -> cache-schema frame within [start, end)
    hashes: dict[str, str]  # timeframe -> data_hash of that frame
    replaced_after: datetime | None = None


def _utc(d: date) -> datetime:
    return datetime(d.year, d.month, d.day, tzinfo=UTC)


def _read_validated(settings: Settings, pair: str, tf: str) -> pd.DataFrame:
    path = cache_path(settings.paths.var_dir, pair, tf)
    if not path.is_file():
        raise DataValidationError(f"no cache for {pair} {tf} ({path})")
    st = path.stat()
    key = (str(Path(path).resolve()), tf, st.st_size, st.st_mtime_ns)
    if key not in _RAW_CACHE:
        frame = read_cache_checked(path)
        if frame is None:
            raise DataValidationError(f"no cache for {pair} {tf} ({path})")
        validate_frame(frame, tf, settings.data)
        _RAW_CACHE.clear()  # keep at most the current files' frames
        _RAW_CACHE[key] = frame
    return _RAW_CACHE[key]


def load_dataset(
    settings: Settings,
    start: date,
    end: date,
    timeframes: tuple[str, ...],
    *,
    replace_after: datetime | None = None,
    seed: int = 0,
) -> Dataset:
    """Validated candles of ``timeframes`` in ``[start, end)`` (dates are 00:00 UTC)."""
    if end <= start:
        raise ValueError(f"empty backtest range {start} .. {end}")
    pair = settings.pairs[0]
    lo, hi = pd.Timestamp(_utc(start)), pd.Timestamp(_utc(end))
    frames: dict[str, pd.DataFrame] = {}
    rng = np.random.default_rng(seed)
    for tf in timeframes:
        raw = _read_validated(settings, pair, tf)
        sliced = raw[(raw["open_at"] >= lo) & (raw["open_at"] < hi)].reset_index(drop=True)
        if sliced.empty:
            raise DataValidationError(f"no {tf} candles in {start} .. {end}")
        if replace_after is not None:
            sliced = _random_walk_after(sliced, tf, replace_after, rng)
        frames[tf] = sliced
    return Dataset(
        pair=pair,
        start=_utc(start),
        end=_utc(end),
        frames=frames,
        hashes={tf: data_hash(f) for tf, f in frames.items()},
        replaced_after=replace_after,
    )


def _random_walk_after(
    frame: pd.DataFrame, tf: str, cut: datetime, rng: np.random.Generator
) -> pd.DataFrame:
    """Replace rows with ``open_at >= cut`` by a seeded random walk from the last close."""
    out = frame.copy()
    mask = (out["open_at"] >= pd.Timestamp(cut)).to_numpy()
    n = int(mask.sum())
    if n == 0:
        return out
    first = int(mask.argmax())
    prev = float(out["close"].iloc[first - 1]) if first > 0 else float(out["open"].iloc[0])
    sigma = 0.03 * np.sqrt(TIMEFRAME_SECONDS[tf] / 86400)
    closes = prev * np.exp(np.cumsum(rng.normal(0.0, sigma, n)))
    opens = np.concatenate([[prev], closes[:-1]])
    wiggle = 1 + np.abs(rng.normal(0.0, sigma / 2, n))
    out.loc[mask, "open"] = opens
    out.loc[mask, "close"] = closes
    out.loc[mask, "high"] = np.maximum(opens, closes) * wiggle
    out.loc[mask, "low"] = np.minimum(opens, closes) / wiggle
    out.loc[mask, "volume"] = 1.0
    out.loc[mask, "source"] = "archive"  # replaced candles are ordinary, fillable candles
    return out


def anomalies_in(dataset: Dataset) -> list[dict[str, str]]:
    """Known anomalies inside the dataset's range (reported even when unused)."""
    out = []
    for day, what in KNOWN_ANOMALIES:
        t = _utc(date.fromisoformat(day))
        if dataset.start <= t < dataset.end:
            out.append({"date": day, "note": what})
    return out


def interval(tf: str) -> timedelta:
    return timedelta(seconds=TIMEFRAME_SECONDS[tf])
