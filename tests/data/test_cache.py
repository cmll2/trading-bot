"""bot.data.cache: AD-18 schema, path and atomic writes."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from bot.data import cache
from bot.data.cache import (
    COLUMNS,
    DTYPES,
    cache_path,
    empty_frame,
    interval_ms,
    normalize,
    pair_dirname,
    read_cache,
    write_cache,
)
from tests.data.fakes import DAY_MS, START_MS, frame


def test_paths() -> None:
    assert pair_dirname("BTC/EUR") == "BTC-EUR"
    var = Path("/x/var")
    assert cache_path(var, "BTC/EUR", "1d") == var / "data" / "BTC-EUR" / "1d.parquet"


def test_interval_ms() -> None:
    assert interval_ms("1d") == DAY_MS
    assert interval_ms("4h") == 4 * 3600 * 1000
    assert interval_ms("15m") == 15 * 60 * 1000


def test_empty_frame_has_exact_schema() -> None:
    df = empty_frame()
    assert tuple(df.columns) == COLUMNS and df.empty
    assert {c: df[c].dtype for c in COLUMNS} == DTYPES


def test_normalize_sets_exact_dtypes_and_order() -> None:
    out = normalize(frame()[list(reversed(COLUMNS))])
    assert tuple(out.columns) == COLUMNS
    assert str(out["open_at"].dtype) == "datetime64[ms, UTC]"
    assert out["trades"].dtype == "Int64" and out["source"].dtype == "string"
    assert all(out[c].dtype == "float64" for c in ("open", "high", "low", "close", "volume"))
    assert frame()["open_at"].iloc[0] == pd.Timestamp(START_MS, unit="ms", tz="UTC")


def test_normalize_refuses_naive_open_at() -> None:
    df = frame()
    df["open_at"] = df["open_at"].dt.tz_localize(None)
    with pytest.raises((TypeError, ValueError)):
        normalize(df)


def test_normalize_refuses_missing_column() -> None:
    with pytest.raises(KeyError):
        normalize(frame().drop(columns=["volume"]))


def test_read_missing_returns_none(tmp_path: Path) -> None:
    assert read_cache(tmp_path / "nope.parquet") is None


def test_round_trip_keeps_schema(tmp_path: Path) -> None:
    path = tmp_path / "var" / "data" / "BTC-EUR" / "1d.parquet"
    df = frame()
    write_cache(path, df)
    back = read_cache(path)
    assert back is not None
    pd.testing.assert_frame_equal(back, df)
    assert sorted(p.name for p in path.parent.iterdir()) == ["1d.parquet"]  # no temp left


def test_failed_write_leaves_previous_file_intact(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "1d.parquet"
    write_cache(path, frame(2))
    before = path.read_bytes()

    def _broken(self: pd.DataFrame, target: Path, **_k: object) -> None:
        Path(target).write_bytes(b"partial")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_parquet", _broken)
    with pytest.raises(OSError, match="disk full"):
        write_cache(path, frame(5))
    assert path.read_bytes() == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["1d.parquet"]


def test_write_uses_os_replace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[object, object]] = []
    real = cache.os.replace

    def _spy(src: object, dst: object) -> None:
        calls.append((src, dst))
        real(src, dst)

    monkeypatch.setattr(cache.os, "replace", _spy)
    path = tmp_path / "1d.parquet"
    write_cache(path, frame())
    assert calls == [(path.with_name("1d.parquet.tmp"), path)]
