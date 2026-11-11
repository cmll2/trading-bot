"""data_hash: deterministic and value-sensitive (NFR-02, AD-21)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from bot.data.cache import data_hash, read_cache, write_cache
from tests.data.fakes import frame, rows


def test_same_file_loaded_twice_gives_same_hash(tmp_path: Path) -> None:
    path = tmp_path / "1d.parquet"
    write_cache(path, frame(20))
    first, second = read_cache(path), read_cache(path)
    assert first is not None and second is not None
    h = data_hash(first)
    assert len(h) == 64 and int(h, 16) >= 0
    assert data_hash(second) == h
    assert data_hash(frame(20)) == h  # in-memory frame with the same values


def test_rewriting_the_same_values_keeps_the_hash(tmp_path: Path) -> None:
    a, b = tmp_path / "a.parquet", tmp_path / "b.parquet"
    write_cache(a, frame(5))
    write_cache(b, frame(5))
    assert data_hash(read_cache(a)) == data_hash(read_cache(b))  # type: ignore[arg-type]


def test_index_is_ignored() -> None:
    df = frame(5)
    assert data_hash(df.set_axis(range(10, 15))) == data_hash(df)


def test_close_change_changes_hash() -> None:
    df = frame(5)
    changed = df.copy()
    changed.loc[2, "close"] = changed.loc[2, "close"] + 0.1
    assert data_hash(changed) != data_hash(df)


def test_source_change_changes_hash() -> None:
    df = frame(5)
    changed = df.copy()
    changed.loc[3, "source"] = "archive"
    assert data_hash(changed) != data_hash(df)


def test_trades_na_differs_from_zero() -> None:
    df = rows([0, 1], ["archive", "archive"])
    na = df.copy()
    na["trades"] = pd.array([pd.NA, 7], dtype="Int64")
    zero = df.copy()
    zero["trades"] = pd.array([0, 7], dtype="Int64")
    assert data_hash(na) != data_hash(zero)


def test_open_at_and_row_count_change_hash() -> None:
    df = frame(5)
    shifted = df.copy()
    shifted["open_at"] = shifted["open_at"] + pd.Timedelta(days=1)
    assert data_hash(shifted) != data_hash(df)
    assert data_hash(df.iloc[:4]) != data_hash(df)
