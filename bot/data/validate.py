"""Candle validation: fail loudly, never repair (AD-18, FR-03).

``validate_frame`` runs ``CHECKS`` in order and raises ``DataValidationError`` at the first
defect, naming it and the offending ``open_at``; it then applies the explicit
``data.no_trade_policy`` and the synthetic-ratio cap. Each check is a plain function
``(df, tf) -> None``. Validation is read-only: it never modifies, drops, reorders or fills
rows.

Kraken's archive omits intervals with no trade. Missing intervals are therefore classified
(``classify_missing``): a hole whose neighbours are both ``archive``/``synthetic`` rows is a
legitimate ``no_trade`` interval; any other hole (inside the API range, touching a ``trades``
row, or between sources) is a ``download`` gap and is never filled. Only writers fill
no-trade holes, through ``apply_no_trade_policy``, before validating; every filled row is
``synthetic``. ``bot data backfill-trades`` fills the empty buckets inside its own window
before merging (``bot.data.trades.fill_interior_buckets``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import numpy as np
import pandas as pd

from bot.config import DataSettings
from bot.data.cache import (
    COLUMNS,
    DTYPES,
    OPEN_AT_DTYPE,
    PRICE_COLUMNS,
    SOURCES,
    interval_ms,
    normalize,
    read_cache,
)

GapKind = Literal["no_trade", "download"]
NO_TRADE_NEIGHBOURS = ("archive", "synthetic")
# ``trades`` rows (M1 story 9) bound synthetic runs like ``archive`` rows: the backfill fills
# its own interior empty buckets. A hole touching a ``trades`` row is still a download gap.
SYNTHETIC_BOUNDARIES = ("archive", "trades")


class DataValidationError(ValueError):
    """A cached or downloaded candle frame is defective. Never repaired."""

    def __init__(self, defect: str, open_at: object = None) -> None:
        self.defect = defect
        self.open_at = open_at
        super().__init__(defect if open_at is None else f"{defect} at {open_at}")


@dataclass(frozen=True)
class ValidationReport:
    tf: str
    rows: int
    first: pd.Timestamp | None
    last: pd.Timestamp | None
    sources: dict[str, int] = field(default_factory=dict)
    synthetic_rows: int = 0
    synthetic_ratio_after_start: float = 0.0  # synthetic / rows from data.history_start on
    synthetic_by_year: dict[int, int] = field(default_factory=dict)  # years with synthetic rows


def read_cache_checked(path: Path) -> pd.DataFrame | None:
    """``read_cache``, with an unreadable file reported as a ``DataValidationError``."""
    try:
        return read_cache(path)
    except (OSError, ValueError) as exc:  # pyarrow errors subclass these
        raise DataValidationError(f"unreadable cache file {path}: {exc}") from exc


def _ms(df: pd.DataFrame) -> pd.Series:
    return df["open_at"].astype("int64")


def _bool(s: pd.Series) -> np.ndarray:
    """Nullable boolean Series -> numpy bool array, NA counted as False."""
    return s.fillna(False).to_numpy(dtype=bool)


def check_columns(df: pd.DataFrame, tf: str) -> None:
    if tuple(df.columns) != COLUMNS:
        raise DataValidationError(f"wrong columns {list(df.columns)}, expected {list(COLUMNS)}")


def check_open_at_utc(df: pd.DataFrame, tf: str) -> None:
    dtype = df["open_at"].dtype
    if not isinstance(dtype, pd.DatetimeTZDtype):
        raise DataValidationError(f"open_at is not timezone-aware UTC (dtype {dtype})")
    if dtype != OPEN_AT_DTYPE:
        raise DataValidationError(f"open_at dtype {dtype}, expected {OPEN_AT_DTYPE}")


def check_dtypes(df: pd.DataFrame, tf: str) -> None:
    for col, expected in DTYPES.items():
        if df[col].dtype != expected:
            raise DataValidationError(
                f"column {col} has dtype {df[col].dtype}, expected {expected}"
            )


def check_no_nulls(df: pd.DataFrame, tf: str) -> None:
    for col in ("open_at", *PRICE_COLUMNS, "source"):
        nulls = df[col].isna()
        if nulls.any():
            idx = nulls.idxmax()
            raise DataValidationError(f"null {col}", df["open_at"].iloc[idx])


def check_sources(df: pd.DataFrame, tf: str) -> None:
    unknown = ~df["source"].isin(SOURCES)
    if unknown.any():
        idx = unknown.idxmax()
        raise DataValidationError(
            f"unknown source {df['source'].iloc[idx]!r}", df["open_at"].iloc[idx]
        )


def check_unique(df: pd.DataFrame, tf: str) -> None:
    dup = df["open_at"].duplicated()
    if dup.any():
        raise DataValidationError("duplicate open_at", df["open_at"].iloc[dup.idxmax()])


def check_increasing(df: pd.DataFrame, tf: str) -> None:
    bad = _ms(df).diff() <= 0
    if bad.any():
        raise DataValidationError(
            "open_at not strictly increasing", df["open_at"].iloc[bad.idxmax()]
        )


def check_aligned(df: pd.DataFrame, tf: str) -> None:
    bad = _ms(df) % interval_ms(tf) != 0
    if bad.any():
        raise DataValidationError(
            f"open_at not aligned to {tf} interval", df["open_at"].iloc[bad.idxmax()]
        )


def check_ohlc(df: pd.DataFrame, tf: str) -> None:
    """Positive finite prices, high/low bracket open and close, volume and trades >= 0."""
    o, h, lo, c = (df[col].to_numpy() for col in ("open", "high", "low", "close"))
    prices = np.stack([o, h, lo, c])
    with np.errstate(invalid="ignore"):
        bad = (
            ~np.isfinite(prices).all(axis=0)
            | (prices <= 0).any(axis=0)
            | (h < lo)
            | (h < np.maximum(o, c))
            | (lo > np.minimum(o, c))
        )
    if bad.any():
        raise DataValidationError("inconsistent OHLC", df["open_at"].iloc[int(bad.argmax())])
    vol = df["volume"].to_numpy()
    bad = ~np.isfinite(vol) | (vol < 0)
    if bad.any():
        raise DataValidationError(
            "non-finite or negative volume", df["open_at"].iloc[int(bad.argmax())]
        )
    bad = _bool(df["trades"] < 0)
    if bad.any():
        raise DataValidationError("negative trades", df["open_at"].iloc[int(bad.argmax())])


def check_synthetic_rows(df: pd.DataFrame, tf: str) -> None:
    """A synthetic row is a flat no-trade candle: O=H=L=C=previous close, volume 0, trades 0,
    and every run of consecutive synthetic rows sits between two ``archive``/``trades`` rows
    (no-trade intervals exist only inside a complete trade record; an API gap is never
    forward-filled)."""
    synth = _bool(df["source"] == "synthetic")
    if not synth.any():
        return
    archive = _bool(df["source"].isin(SYNTHETIC_BOUNDARIES))
    prev_synth = np.concatenate([[False], synth[:-1]])
    next_synth = np.concatenate([synth[1:], [False]])
    prev_archive = np.concatenate([[False], archive[:-1]])
    next_archive = np.concatenate([archive[1:], [False]])
    starts = np.flatnonzero(synth & ~prev_synth)
    ends = np.flatnonzero(synth & ~next_synth)  # ends[k] closes the run opened at starts[k]
    bad_runs = ~prev_archive[starts] | ~next_archive[ends]
    if bad_runs.any():
        raise DataValidationError(
            "synthetic candle outside archive range",
            df["open_at"].iloc[int(starts[int(bad_runs.argmax())])],
        )
    prev_close = df["close"].shift(1).to_numpy()  # NaN for the first row: never equal
    flat = np.ones(len(df), dtype=bool)
    for col in ("open", "high", "low", "close"):
        flat &= df[col].to_numpy() == prev_close
    ok = flat & (df["volume"].to_numpy() == 0) & _bool(df["trades"] == 0)
    bad = synth & ~ok
    if bad.any():
        raise DataValidationError(
            "inconsistent synthetic candle", df["open_at"].iloc[int(bad.argmax())]
        )


def _gaps(df: pd.DataFrame, tf: str) -> list[tuple[int, int, GapKind]]:
    """Holes in a sorted, unique, aligned frame as ``(row_before, missing_count, kind)``."""
    if len(df) < 2:
        return []
    missing = np.diff(_ms(df).to_numpy()) // interval_ms(tf) - 1
    source = df["source"].to_numpy(dtype=object)
    out: list[tuple[int, int, GapKind]] = []
    for i in np.flatnonzero(missing > 0):
        no_trade = source[i] in NO_TRADE_NEIGHBOURS and source[i + 1] in NO_TRADE_NEIGHBOURS
        out.append((int(i), int(missing[i]), "no_trade" if no_trade else "download"))
    return out


def _after_row(df: pd.DataFrame, tf: str, row: int, k: int = 1) -> pd.Timestamp:
    return pd.Timestamp(int(_ms(df).iloc[row]) + k * interval_ms(tf), unit="ms", tz="UTC")


def classify_missing(df: pd.DataFrame, tf: str) -> list[tuple[pd.Timestamp, GapKind]]:
    """Every missing ``open_at`` with its kind: ``no_trade`` when both neighbouring rows are
    ``archive``/``synthetic``, else ``download``. Expects a sorted, unique, aligned frame."""
    return [
        (_after_row(df, tf, row, k), kind)
        for row, count, kind in _gaps(df, tf)
        for k in range(1, count + 1)
    ]


def check_no_missing_interval(df: pd.DataFrame, tf: str) -> None:
    """Any hole is a defect: validation never fills, so a no-trade hole means a writer
    skipped ``apply_no_trade_policy``."""
    gaps = _gaps(df, tf)
    if gaps:
        row, _count, kind = gaps[0]
        defect = "download gap" if kind == "download" else "no-trade gap not filled"
        raise DataValidationError(defect, _after_row(df, tf, row))


CHECKS: list[Callable[[pd.DataFrame, str], None]] = [
    check_columns,
    check_open_at_utc,
    check_dtypes,
    check_no_nulls,
    check_sources,
    check_unique,
    check_increasing,
    check_aligned,
    check_ohlc,
    check_synthetic_rows,
    check_no_missing_interval,
]

# What a writer must know is sound before it can classify and fill holes.
_STRUCTURE_CHECKS = CHECKS[: CHECKS.index(check_aligned) + 1]


def apply_no_trade_policy(df: pd.DataFrame, tf: str, policy: str) -> pd.DataFrame:
    """Writers only: return a new frame, sorted by ``open_at``, with no-trade holes handled
    per ``data.no_trade_policy``. The input is not modified and must already be sorted with
    the exact cache dtypes.

    ``fill_flat`` inserts, for each missing interval between two ``archive``/``synthetic``
    rows, a ``synthetic`` row with O=H=L=C=the close of
    the row before the hole, volume 0, trades 0. ``fail`` raises ``no-trade gap`` at the first
    such interval. Download gaps (API range or between sources) are never filled;
    ``validate_frame`` reports them.
    Structural defects (columns, dtypes, nulls, order, duplicates, alignment) raise
    ``DataValidationError`` here, checked before anything is cast or filled.
    """
    if policy not in ("fill_flat", "fail"):
        raise ValueError(f"unknown no_trade_policy {policy!r}")
    frame = df.reset_index(drop=True)  # positional index only; values and order unchanged
    for check in _STRUCTURE_CHECKS:  # on the input as given: no casting, no sorting
        check(frame, tf)
    gaps = [g for g in _gaps(frame, tf) if g[2] == "no_trade"]
    if not gaps:
        return frame
    if policy == "fail":
        raise DataValidationError("no-trade gap", _after_row(frame, tf, gaps[0][0]))

    rows = np.array([g[0] for g in gaps], dtype="int64")
    counts = np.array([g[1] for g in gaps], dtype="int64")
    steps = np.concatenate([np.arange(1, n + 1, dtype="int64") for n in counts])
    open_ms = np.repeat(_ms(frame).to_numpy()[rows], counts) + steps * interval_ms(tf)
    price = np.repeat(frame["close"].to_numpy()[rows], counts)
    n = len(open_ms)
    filled = normalize(
        pd.DataFrame(
            {
                "open_at": pd.to_datetime(open_ms, unit="ms", utc=True),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": np.zeros(n),
                "trades": np.zeros(n, dtype="int64"),
                "source": ["synthetic"] * n,
            }
        )
    )
    out = pd.concat([frame, filled], ignore_index=True)
    return out.sort_values("open_at", kind="stable").reset_index(drop=True)


def validate_frame(
    df: pd.DataFrame, tf: str, data_settings: DataSettings, now: datetime | None = None
) -> ValidationReport:
    """Run every check, then the no-trade policy and the synthetic-ratio cap. Read-only.

    If ``now`` is given, the last candle must also be closed.
    """
    df = df.reset_index(drop=True)  # a new object: the caller's frame is never changed
    for check in CHECKS:
        check(df, tf)
    if df.empty:
        raise DataValidationError("empty cache")
    first, last = df["open_at"].iloc[0], df["open_at"].iloc[-1]
    if now is not None and int(_ms(df).iloc[-1]) + interval_ms(tf) > now.timestamp() * 1000:
        raise DataValidationError("last candle is not closed", last)

    synth = _bool(df["source"] == "synthetic")
    if data_settings.no_trade_policy == "fail" and synth.any():
        raise DataValidationError(
            "synthetic candle under no_trade_policy=fail", df["open_at"].iloc[int(synth.argmax())]
        )
    after = (df["open_at"] >= pd.Timestamp(data_settings.history_start, tz="UTC")).to_numpy()
    synth_after, rows_after = int((synth & after).sum()), int(after.sum())
    ratio = Decimal(synth_after) / Decimal(rows_after) if rows_after else Decimal(0)
    cap = data_settings.synthetic_cap(tf)
    if ratio > cap:
        raise DataValidationError(
            f"synthetic ratio {float(ratio):.6g} ({synth_after}/{rows_after} rows from "
            f"{data_settings.history_start}) exceeds max_synthetic_ratio "
            f"{cap}"
        )

    years = df.loc[synth, "open_at"].dt.year.value_counts().sort_index()
    counts = df["source"].value_counts()
    return ValidationReport(
        tf=tf,
        rows=len(df),
        first=first,
        last=last,
        sources={s: int(counts.get(s, 0)) for s in SOURCES},
        synthetic_rows=int(synth.sum()),
        synthetic_ratio_after_start=float(ratio),
        synthetic_by_year={int(y): int(n) for y, n in years.items()},
    )


@dataclass(frozen=True)
class GapAudit:
    """No-trade (synthetic) runs of a cache that overlap ``[start, end)`` (M1 story 6).

    ``first``/``last`` give the cached coverage inside the window (None when the cache holds
    no candle there, which means the window cannot be audited, not that it has no gaps).
    Runs are reported with their full extent, even when they cross a window edge.
    """

    tf: str
    start: pd.Timestamp
    end: pd.Timestamp
    rows: int
    first: pd.Timestamp | None
    last: pd.Timestamp | None
    runs: tuple[tuple[pd.Timestamp, pd.Timestamp, int], ...]  # (first open_at, last, length)

    @property
    def synthetic_rows(self) -> int:
        return sum(n for _, _, n in self.runs)


def audit_gaps(df: pd.DataFrame, tf: str, start: pd.Timestamp, end: pd.Timestamp) -> GapAudit:
    """List synthetic runs overlapping ``[start, end)``. Read-only; expects a validated frame."""
    if start >= end:
        raise ValueError(f"audit window start {start} is not before end {end}")
    open_at = df["open_at"].reset_index(drop=True)
    synthetic = _bool(df["source"] == "synthetic")
    runs: list[tuple[pd.Timestamp, pd.Timestamp, int]] = []
    i = 0
    while i < len(df):
        if not synthetic[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(df) and synthetic[j + 1]:
            j += 1
        if open_at.iloc[i] < end and open_at.iloc[j] >= start:
            runs.append((open_at.iloc[i], open_at.iloc[j], j - i + 1))
        i = j + 1
    inside = open_at[(open_at >= start) & (open_at < end)]
    empty = inside.empty
    return GapAudit(
        tf=tf,
        start=start,
        end=end,
        rows=len(inside),
        first=None if empty else inside.iloc[0],
        last=None if empty else inside.iloc[-1],
        runs=tuple(runs),
    )
