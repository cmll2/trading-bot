"""bot.data.update: incremental update orchestration (FR-02, AD-18)."""

from __future__ import annotations

import shutil
from datetime import timedelta
from pathlib import Path

import ccxt
import pandas as pd
import pytest

from bot.clock import FakeClock
from bot.config import Settings, load_settings
from bot.data.cache import cache_path, read_cache, write_cache
from bot.data.fetch import FetchError
from bot.data.update import update_timeframe
from bot.data.validate import DataValidationError
from tests.conftest import REPO_ROOT
from tests.data.fakes import DAY_MS, START, START_MS, FakeExchange, candles, frame


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", root / "config.yaml")
    return load_settings(root / "config.yaml", root / "none.env", repo_root=root)


def _path(settings: Settings, tf: str = "1d") -> Path:
    return cache_path(settings.paths.var_dir, "BTC/EUR", tf)


def _clock(days: int) -> FakeClock:
    return FakeClock(START + timedelta(days=days, hours=1))


def test_first_run_writes_cache(settings: Settings) -> None:
    ex = FakeExchange([candles(START_MS, 10)])
    out = update_timeframe(settings, ex, _clock(10), "1d")
    assert len(out) == 10
    stored = read_cache(_path(settings))
    assert stored is not None
    pd.testing.assert_frame_equal(stored, out)
    assert ex.calls[0]["since"] is None
    assert ex.calls[0]["symbol"] == "BTC/EUR" and ex.calls[0]["timeframe"] == "1d"


def test_incremental_requests_from_last_plus_interval(settings: Settings) -> None:
    write_cache(_path(settings), frame(5))
    last_ms = START_MS + 4 * DAY_MS
    # Kraken ignores since and returns its whole window, overlapping the cache.
    ex = FakeExchange([candles(START_MS, 8)])
    out = update_timeframe(settings, ex, _clock(8), "1d")
    assert ex.calls[0]["since"] == last_ms + DAY_MS
    assert all(c["since"] is None or c["since"] > last_ms for c in ex.calls)
    assert len(out) == 8 and out["open_at"].is_unique
    pd.testing.assert_frame_equal(out.iloc[:5].reset_index(drop=True), frame(5))


def test_no_new_candles_leaves_file_untouched(settings: Settings) -> None:
    path = _path(settings)
    write_cache(path, frame(5))
    before = path.read_bytes()
    mtime = path.stat().st_mtime_ns
    out = update_timeframe(settings, FakeExchange([]), _clock(5), "1d")
    assert len(out) == 5
    assert path.read_bytes() == before and path.stat().st_mtime_ns == mtime


def test_fetch_failure_writes_nothing_on_first_run(settings: Settings) -> None:
    ex = FakeExchange([ccxt.RateLimitExceeded("x")] * 10)
    with pytest.raises(FetchError):
        update_timeframe(settings, ex, _clock(10), "1d")
    assert not _path(settings).exists()


def test_fetch_failure_leaves_existing_cache_bytes(settings: Settings) -> None:
    path = _path(settings)
    write_cache(path, frame(5))
    before = path.read_bytes()
    bad = candles(START_MS + 5 * DAY_MS, 2)
    bad[1] = [bad[1][0], "x", 1.0, 1.0, 1.0, 1.0]
    with pytest.raises(FetchError):
        update_timeframe(settings, FakeExchange([bad]), _clock(8), "1d")
    assert path.read_bytes() == before


def test_gap_between_cache_and_api_fails_without_writing(settings: Settings) -> None:
    path = _path(settings)
    write_cache(path, frame(5))
    before = path.read_bytes()
    ex = FakeExchange([candles(START_MS + 7 * DAY_MS, 3)])  # days 5 and 6 missing
    with pytest.raises(DataValidationError) as info:
        update_timeframe(settings, ex, _clock(10), "1d")
    assert info.value.defect == "download gap"
    assert info.value.open_at == pd.Timestamp(START_MS + 5 * DAY_MS, unit="ms", tz="UTC")
    assert path.read_bytes() == before


def test_first_run_with_no_closed_candles_writes_nothing(settings: Settings) -> None:
    with pytest.raises(FetchError, match="no closed candles returned for 1d"):
        update_timeframe(settings, FakeExchange([]), _clock(5), "1d")
    assert not _path(settings).exists()


def test_corrupt_cache_is_a_validation_error(settings: Settings) -> None:
    path = _path(settings)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not parquet")
    ex = FakeExchange([candles(START_MS, 5)])
    with pytest.raises(DataValidationError, match="unreadable cache file"):
        update_timeframe(settings, ex, _clock(5), "1d")
    assert ex.calls == [] and path.read_bytes() == b"not parquet"


def test_defective_cache_is_refused_before_fetching(settings: Settings) -> None:
    path = _path(settings)
    df = frame(3)
    df["open_at"] = df["open_at"].dt.tz_localize(None)
    path.parent.mkdir(parents=True)
    df.to_parquet(path, index=False)
    ex = FakeExchange([candles(START_MS, 5)])
    with pytest.raises(DataValidationError):
        update_timeframe(settings, ex, _clock(5), "1d")
    assert ex.calls == []


def test_update_applies_no_trade_policy_before_validating(settings: Settings, monkeypatch) -> None:
    import bot.data.update as update_mod

    calls: list[tuple[str, object]] = []
    real_apply = update_mod.apply_no_trade_policy
    real_validate = update_mod.validate_frame
    real_write = update_mod.write_cache

    def _apply(df: pd.DataFrame, tf: str, policy: str) -> pd.DataFrame:
        assert policy == "fill_flat"
        out = real_apply(df, tf, policy)
        calls.append(("apply", out))
        return out

    def _validate(df: pd.DataFrame, *a: object, **k: object) -> object:
        calls.append(("validate", df))
        return real_validate(df, *a, **k)

    def _write(path: Path, df: pd.DataFrame) -> None:
        calls.append(("write", df))
        real_write(path, df)

    monkeypatch.setattr(update_mod, "apply_no_trade_policy", _apply)
    monkeypatch.setattr(update_mod, "validate_frame", _validate)
    monkeypatch.setattr(update_mod, "write_cache", _write)
    result = update_timeframe(settings, FakeExchange([candles(START_MS, 5)]), _clock(5), "1d")

    assert [name for name, _ in calls] == ["apply", "validate", "write"]
    applied = calls[0][1]
    assert calls[1][1] is applied and calls[2][1] is applied and result is applied


def test_cache_with_unfilled_no_trade_gap_is_refused_before_fetching(settings: Settings) -> None:
    from tests.data.fakes import rows

    path = _path(settings)
    write_cache(path, rows([0, 1, 3], ["archive"] * 3))
    before = path.read_bytes()
    ex = FakeExchange([candles(START_MS + 4 * DAY_MS, 2)])
    with pytest.raises(DataValidationError) as info:
        update_timeframe(settings, ex, _clock(6), "1d")
    assert info.value.defect == "no-trade gap not filled"
    assert ex.calls == [] and path.read_bytes() == before
