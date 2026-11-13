"""Backtest dataset loader: the ONLY way candles enter a backtest (AD-4, NFR-02).

``load_dataset`` reads each needed timeframe from the Parquet cache, validates the whole
file (validation needs the whole file: gaps, ratios), slices it to ``[start, end)`` and
hashes the slice. Nothing downstream ever receives a row at or after ``end``. ``end`` may
not pass ``backtest.holdout_start`` unless ``allow_holdout=True``, which only the single,
registered holdout run passes (FR-15, FR-16): the holdout is enforced here, at the one
entry point, not only by the command.

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

_RAW_CACHE: dict[str, tuple[tuple[str, int, int], pd.DataFrame]] = {}


class HoldoutViolation(ValueError):
    """A dataset or search range reaches into the fixed holdout window (FR-15)."""


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
    slot = f"{Path(path).resolve()}|{tf}"
    key = (str(path), st.st_size, st.st_mtime_ns)
    cached = _RAW_CACHE.get(slot)
    if cached is None or cached[0] != key:  # one entry per file; replaced when it changes
        frame = read_cache_checked(path)
        if frame is None:
            raise DataValidationError(f"no cache for {pair} {tf} ({path})")
        validate_frame(frame, tf, settings.data)
        _RAW_CACHE[slot] = (key, frame)
    return _RAW_CACHE[slot][1]


def load_dataset(
    settings: Settings,
    start: date,
    end: date,
    timeframes: tuple[str, ...],
    *,
    replace_after: datetime | None = None,
    seed: int = 0,
    mirror: bool = False,
    allow_holdout: bool = False,
) -> Dataset:
    """Validated candles of ``timeframes`` in ``[start, end)`` (dates are 00:00 UTC)."""
    if end <= start:
        raise ValueError(f"empty backtest range {start} .. {end}")
    if end > settings.backtest.holdout_start and not allow_holdout:
        raise HoldoutViolation(
            f"range end {end} reaches into the holdout starting "
            f"{settings.backtest.holdout_start}; only the registered holdout run may load it"
        )
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
            sliced = _random_walk_after(sliced, tf, replace_after, rng, mirror)
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
    frame: pd.DataFrame, tf: str, cut: datetime, rng: np.random.Generator, mirror: bool = False
) -> pd.DataFrame:
    """Replace rows with ``open_at >= cut`` by a seeded random walk from the last close.

    ``mirror`` negates the walk's returns: the same seed gives a future and its mirror
    image, so a decision that depends on the DIRECTION of the future differs from the
    baseline in at least one of them. Each timeframe gets its own walk (1d is not the
    aggregate of 15m): fine for the guard, whose reruns stop before any fill on replaced
    data; do not use ``replace_after`` for anything that needs consistent futures.
    The walk carries a drift of one sigma per candle (up, or down when mirrored) so the
    replaced future clearly differs in direction from any real one."""
    out = frame.copy()
    mask = (out["open_at"] >= pd.Timestamp(cut)).to_numpy()
    n = int(mask.sum())
    if n == 0:
        return out
    first = int(mask.argmax())
    prev = float(out["close"].iloc[first - 1]) if first > 0 else float(out["open"].iloc[0])
    sigma = 0.03 * np.sqrt(TIMEFRAME_SECONDS[tf] / 86400)
    returns = rng.normal(sigma, sigma, n)
    if mirror:
        returns = -returns
    closes = prev * np.exp(np.cumsum(returns))
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
