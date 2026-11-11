"""Candle validation: fail loudly, never repair (AD-18, FR-03).

``validate_frame`` runs ``CHECKS`` in order and raises ``DataValidationError`` at the first
defect, naming it and the offending ``open_at``. Each check is a plain function
``(df, tf) -> None`` so later stories can append checks (OHLC consistency, no-trade policy)
without touching the existing ones.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import pandas as pd

from bot.data.cache import (
    COLUMNS,
    DTYPES,
    OPEN_AT_DTYPE,
    PRICE_COLUMNS,
    SOURCES,
    interval_ms,
    read_cache,
)


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


def read_cache_checked(path: Path) -> pd.DataFrame | None:
    """``read_cache``, with an unreadable file reported as a ``DataValidationError``."""
    try:
        return read_cache(path)
    except (OSError, ValueError) as exc:  # pyarrow errors subclass these
        raise DataValidationError(f"unreadable cache file {path}: {exc}") from exc


def _ms(df: pd.DataFrame) -> pd.Series:
    return df["open_at"].astype("int64")


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


def check_no_missing_interval(df: pd.DataFrame, tf: str) -> None:
    step = interval_ms(tf)
    ms = _ms(df)
    gap = ms.diff() > step
    if gap.any():
        idx = gap.idxmax()
        first_missing = pd.Timestamp(int(ms.iloc[idx - 1]) + step, unit="ms", tz="UTC")
        raise DataValidationError("download gap", first_missing)


CHECKS: list[Callable[[pd.DataFrame, str], None]] = [
    check_columns,
    check_open_at_utc,
    check_dtypes,
    check_no_nulls,
    check_sources,
    check_unique,
    check_increasing,
    check_aligned,
    check_no_missing_interval,
]


def validate_frame(df: pd.DataFrame, tf: str, now: datetime | None = None) -> ValidationReport:
    """Run every check; if ``now`` is given, also require the last candle to be closed."""
    df = df.reset_index(drop=True)
    for check in CHECKS:
        check(df, tf)
    if df.empty:
        raise DataValidationError("empty cache")
    first, last = df["open_at"].iloc[0], df["open_at"].iloc[-1]
    if now is not None and int(_ms(df).iloc[-1]) + interval_ms(tf) > now.timestamp() * 1000:
        raise DataValidationError("last candle is not closed", last)
    counts = df["source"].value_counts()
    sources = {s: int(counts.get(s, 0)) for s in SOURCES}
    return ValidationReport(tf=tf, rows=len(df), first=first, last=last, sources=sources)
