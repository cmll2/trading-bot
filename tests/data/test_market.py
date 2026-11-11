"""ReplayMarketData: the MarketData port over the Parquet cache (AD-1, AD-3, AD-18)."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pandas as pd
import pytest

from bot.candles import CandleHistory
from bot.clock import FakeClock, SimClock
from bot.data.cache import cache_path, data_hash, write_cache
from bot.data.market import MarketData, ReplayMarketData
from bot.data.validate import DataValidationError
from tests.data.fakes import DATA, DAY_MS, START, START_MS, frame

PAIR = "BTC/EUR"
N = 10


@pytest.fixture
def var_dir(tmp_path: Path) -> Path:
    write_cache(cache_path(tmp_path, PAIR, "1d"), frame(N))
    return tmp_path


def _close_of(k: int) -> pd.Timestamp:
    """Close instant of the k-th cached 1d candle."""
    return pd.Timestamp(START_MS + (k + 1) * DAY_MS, unit="ms", tz="UTC")


def test_candle_absent_one_second_before_close_and_present_at_close(var_dir: Path) -> None:
    """AC1: through ReplayMarketData, candle 4 is hidden 1 s before its close, shown at it."""
    clock = FakeClock(_close_of(4).to_pydatetime() - timedelta(seconds=1))
    md = ReplayMarketData(var_dir, [PAIR], clock, DATA)
    before = md.closed_candles(PAIR, "1d")
    assert len(before) == 4
    assert before.last_open_at == START + timedelta(days=3)
    clock.advance(timedelta(seconds=1))
    at = md.closed_candles(PAIR, "1d")
    assert len(at) == 5
    assert at.last_open_at == START + timedelta(days=4)


def test_replay_equals_closed_prefix_of_cache(var_dir: Path) -> None:
    clock = SimClock(_close_of(6).to_pydatetime())
    md: MarketData = ReplayMarketData(var_dir, [PAIR], clock, DATA)
    hist = md.closed_candles(PAIR, "1d")
    assert isinstance(hist, CandleHistory)
    expected = frame(N).iloc[:7]
    got = hist.to_frame()
    assert list(got["open_at"]) == list(expected["open_at"])
    for col in ("open", "high", "low", "close", "volume"):
        assert list(got[col]) == list(expected[col])
    assert not got["synthetic"].any()


def test_cache_holding_future_candles_is_served_closed_only(var_dir: Path) -> None:
    """A backtest cache extends past the sim clock: validation must not refuse it, and the
    future rows must stay hidden."""
    clock = SimClock(START)
    md = ReplayMarketData(var_dir, [PAIR], clock, DATA)
    assert len(md.closed_candles(PAIR, "1d")) == 0
    clock.advance_to(_close_of(N - 1).to_pydatetime())
    assert len(md.closed_candles(PAIR, "1d")) == N


def test_file_read_once_per_pair_and_timeframe(var_dir: Path) -> None:
    md = ReplayMarketData(var_dir, [PAIR], SimClock(_close_of(2).to_pydatetime()), DATA)
    md.closed_candles(PAIR, "1d")
    cache_path(var_dir, PAIR, "1d").unlink()
    assert len(md.closed_candles(PAIR, "1d")) == 3


def test_missing_cache_refused(tmp_path: Path) -> None:
    md = ReplayMarketData(tmp_path, [PAIR], FakeClock(START), DATA)
    with pytest.raises(DataValidationError, match="no cache"):
        md.closed_candles(PAIR, "1d")


def test_unknown_pair_or_timeframe_refused(var_dir: Path) -> None:
    md = ReplayMarketData(var_dir, [PAIR], FakeClock(START), DATA)
    with pytest.raises(ValueError, match="unknown pair"):
        md.closed_candles("ETH/EUR", "1d")
    with pytest.raises(ValueError, match="unknown timeframe"):
        md.closed_candles(PAIR, "1h")


def test_bare_string_pairs_refused(var_dir: Path) -> None:
    with pytest.raises(TypeError):
        ReplayMarketData(var_dir, PAIR, FakeClock(START), DATA)


def test_invalid_cache_refused_on_load(tmp_path: Path) -> None:
    bad = frame(5).drop(index=2)  # a download gap inside the API range
    write_cache(cache_path(tmp_path, PAIR, "1d"), bad)
    md = ReplayMarketData(tmp_path, [PAIR], FakeClock(START + timedelta(days=30)), DATA)
    with pytest.raises(DataValidationError, match="download gap"):
        md.closed_candles(PAIR, "1d")


def test_data_hash_is_the_hash_of_the_cached_frame(var_dir: Path) -> None:
    md = ReplayMarketData(var_dir, [PAIR], FakeClock(START), DATA)
    assert md.data_hash(PAIR, "1d") == data_hash(frame(N))
