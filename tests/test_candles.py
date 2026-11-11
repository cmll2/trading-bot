"""CandleHistory: closed candles only, immutable, neutral imports (FR-04, AD-3)."""

from __future__ import annotations

import ast
import dataclasses
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from bot.candles import CandleHistory
from bot.data.cache import normalize
from tests.conftest import REPO_ROOT

DAY = timedelta(days=1)
JAN1 = datetime(2026, 1, 1, tzinfo=UTC)
LATER = datetime(2026, 1, 10, tzinfo=UTC)


def _frame(
    start: datetime, n: int, step: timedelta, synthetic_at: int | None = None
) -> pd.DataFrame:
    o = np.arange(n, dtype=float) + 100.0
    sources = ["api"] * n
    if synthetic_at is not None:
        sources[synthetic_at] = "synthetic"
    return normalize(
        pd.DataFrame(
            {
                "open_at": pd.to_datetime([start + i * step for i in range(n)], utc=True),
                "open": o,
                "high": o + 2,
                "low": o - 1,
                "close": o + 0.5,
                "volume": [1.0] * n,
                "trades": pd.array([pd.NA] * n, dtype="Int64"),
                "source": sources,
            }
        )
    )


def _ms(t: datetime) -> int:
    return int(t.timestamp() * 1000)


def test_daily_candle_absent_one_second_before_close_present_at_close() -> None:
    df = _frame(datetime(2025, 12, 30, tzinfo=UTC), 4, DAY)  # 12-30 .. 01-02
    before = CandleHistory.from_frame(df, "1d", datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC))
    assert before.last_open_at == datetime(2025, 12, 31, tzinfo=UTC)
    assert len(before) == 2
    at = CandleHistory.from_frame(df, "1d", datetime(2026, 1, 2, tzinfo=UTC))
    assert at.last_open_at == JAN1
    assert len(at) == 3


@pytest.mark.parametrize(
    ("tf", "step"), [("4h", timedelta(hours=4)), ("15m", timedelta(minutes=15))]
)
def test_intraday_boundaries_are_exact(tf: str, step: timedelta) -> None:
    df = _frame(JAN1, 10, step)
    close_of_4 = JAN1 + 5 * step  # candle index 4 closes here
    one_us = timedelta(microseconds=1)
    assert CandleHistory.from_frame(df, tf, close_of_4 - one_us).last_open_at == JAN1 + 3 * step
    at = CandleHistory.from_frame(df, tf, close_of_4)
    assert at.last_open_at == JAN1 + 4 * step
    assert len(at) == 5


def test_daily_boundary_at_microsecond_precision() -> None:
    df = _frame(JAN1, 2, DAY)
    close = JAN1 + DAY
    assert len(CandleHistory.from_frame(df, "1d", close - timedelta(microseconds=1))) == 0
    assert len(CandleHistory.from_frame(df, "1d", close)) == 1


def test_empty_history_before_first_close() -> None:
    hist = CandleHistory.from_frame(_frame(JAN1, 3, DAY), "1d", JAN1 + timedelta(hours=12))
    assert len(hist) == 0 and hist.last_open_at is None
    assert len(hist.to_frame()) == 0


def test_values_and_dtypes_copied() -> None:
    df = _frame(JAN1, 3, DAY, synthetic_at=1)
    hist = CandleHistory.from_frame(df, "1d", LATER)
    assert hist.timeframe == "1d" and hist.as_of == LATER
    assert hist.open_at.dtype == np.int64
    assert list(hist.open_at) == [_ms(JAN1 + i * DAY) for i in range(3)]
    assert list(hist.close) == [100.5, 101.5, 102.5]
    assert list(hist.synthetic) == [False, True, False]
    assert not np.shares_memory(hist.close, df["close"].to_numpy())


def test_mutation_raises_and_source_unchanged() -> None:
    df = _frame(JAN1, 3, DAY)
    before = df.copy()
    hist = CandleHistory.from_frame(df, "1d", LATER)
    for name in ("open_at", "open", "high", "low", "close", "volume", "synthetic"):
        with pytest.raises(ValueError):
            getattr(hist, name)[0] = 1
    with pytest.raises(ValueError):
        hist.close.flags.writeable = True
    with pytest.raises(dataclasses.FrozenInstanceError):
        hist.close = np.zeros(3)  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        hist.as_of = datetime(2030, 1, 1, tzinfo=UTC)  # type: ignore[misc]
    pd.testing.assert_frame_equal(df, before)
    assert list(hist.close) == [100.5, 101.5, 102.5]


def test_to_frame_is_a_fresh_copy() -> None:
    df = _frame(JAN1, 3, DAY)
    hist = CandleHistory.from_frame(df, "1d", LATER)
    out = hist.to_frame()
    assert list(out["open_at"]) == list(df["open_at"])
    out.loc[0, "close"] = -1.0
    assert hist.close[0] == 100.5
    assert hist.to_frame().loc[0, "close"] == 100.5


def test_naive_or_non_utc_as_of_refused() -> None:
    df = _frame(JAN1, 3, DAY)
    with pytest.raises(ValueError):
        CandleHistory.from_frame(df, "1d", datetime(2026, 1, 10))
    paris_winter = timezone(timedelta(hours=1))
    with pytest.raises(ValueError):
        CandleHistory.from_frame(df, "1d", datetime(2026, 1, 10, tzinfo=paris_winter))


def test_unknown_timeframe_refused() -> None:
    with pytest.raises(ValueError):
        CandleHistory.from_frame(_frame(JAN1, 3, DAY), "2d", LATER)


def test_constructor_refuses_writable_or_open_candles() -> None:
    as_of = JAN1 + DAY
    ro = CandleHistory.from_frame(_frame(JAN1, 1, DAY), "1d", as_of)
    fields = {f.name: getattr(ro, f.name) for f in dataclasses.fields(ro)}
    with pytest.raises(ValueError, match="read-only"):
        CandleHistory(**{**fields, "close": np.array([1.0])})
    with pytest.raises(ValueError, match="not closed"):
        CandleHistory(**{**fields, "as_of": as_of - timedelta(seconds=1)})
    writable = np.array([1.0])
    view = writable.view()
    view.flags.writeable = False  # read-only view of memory the caller can still write
    with pytest.raises(ValueError, match="use from_frame"):
        CandleHistory(**{**fields, "close": view})


def test_arrays_are_backed_by_immutable_bytes() -> None:
    hist = CandleHistory.from_frame(_frame(JAN1, 3, DAY), "1d", LATER)
    for name in ("open_at", "open", "high", "low", "close", "volume", "synthetic"):
        arr = getattr(hist, name)
        assert isinstance(arr.base, bytes)
        with pytest.raises(ValueError):
            arr.flags.writeable = True


def test_sub_millisecond_open_at_refused() -> None:
    """An ns-resolution open_at 1 µs off the grid must not be rounded into visibility."""
    df = _frame(JAN1, 3, DAY)
    df["open_at"] = df["open_at"].dt.as_unit("ns")
    df.loc[1, "open_at"] = df.loc[1, "open_at"] + pd.Timedelta(microseconds=1)
    with pytest.raises(ValueError, match="not aligned"):
        CandleHistory.from_frame(df, "1d", LATER)


def test_ns_resolution_aligned_open_at_accepted() -> None:
    df = _frame(JAN1, 3, DAY)
    df["open_at"] = df["open_at"].dt.as_unit("ns")
    hist = CandleHistory.from_frame(df, "1d", JAN1 + 2 * DAY)
    assert hist.last_open_at == JAN1 + DAY


# --- import boundary (architecture dependency rule: strategy/ never imports data/) ---------

FORBIDDEN = (
    "bot.data",
    "bot.broker",
    "bot.engine",
    "bot.store",
    "ccxt",
    "socket",
    "urllib",
    "requests",
)


def _imports(path: Path) -> list[str]:
    names: list[str] = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
            names.extend(f"{node.module}.{a.name}" for a in node.names)
    return names


def _forbidden(name: str) -> bool:
    return any(name == f or name.startswith(f + ".") for f in FORBIDDEN)


@pytest.mark.parametrize(
    "path",
    [REPO_ROOT / "bot" / "candles.py", *sorted((REPO_ROOT / "bot" / "strategy").glob("*.py"))],
    ids=lambda p: p.relative_to(REPO_ROOT).as_posix(),
)
def test_candles_and_strategy_import_nothing_forbidden(path: Path) -> None:
    assert [n for n in _imports(path) if _forbidden(n)] == []


def test_import_boundary_detector_flags_bad_imports(tmp_path: Path) -> None:
    src = tmp_path / "m.py"
    src.write_text(
        "import ccxt\nfrom bot.data.cache import x\nfrom bot import store\nimport bot.candles\n",
        encoding="utf-8",
    )
    assert [n for n in _imports(src) if _forbidden(n)] == [
        "ccxt",
        "bot.data.cache",
        "bot.data.cache.x",
        "bot.store",
    ]
