"""bot.data.fetch: paginated, retried, closed-only public fetch (FR-01, FR-04, AD-18)."""

from __future__ import annotations

from datetime import timedelta

import ccxt
import pandas as pd
import pytest

from bot.clock import FakeClock
from bot.data.cache import COLUMNS, DTYPES
from bot.data.fetch import (
    PAGE_LIMIT,
    RETRYABLE,
    FetchError,
    fetch_closed_candles,
    make_public_exchange,
    price_tick,
)
from tests.data.fakes import DAY_MS, START, START_MS, TICK, FakeExchange, candle, candles

H4_MS = 4 * 3600 * 1000


def _clock_after(n_days: int, extra: timedelta = timedelta(hours=1)) -> FakeClock:
    return FakeClock(START + timedelta(days=n_days) + extra)


def _fetch(ex: FakeExchange, clock: FakeClock, since: int | None = None, **kw) -> pd.DataFrame:
    tf = kw.pop("tf", "1d")
    args = {"max_retries": 3, "retry_base_seconds": 2.0, **kw}
    return fetch_closed_candles(ex, "BTC/EUR", tf, since, clock, **args)


def test_first_run_two_pages_then_empty() -> None:
    ex = FakeExchange([candles(START_MS, 720), candles(START_MS + 720 * DAY_MS, 720)])
    df = _fetch(ex, _clock_after(1440))
    assert len(df) == 1440
    assert tuple(df.columns) == COLUMNS
    assert {c: df[c].dtype for c in COLUMNS} == DTYPES
    assert df["open_at"].is_monotonic_increasing and df["open_at"].is_unique
    assert (df["source"] == "api").all()
    assert df["trades"].isna().all()
    assert [c["since"] for c in ex.calls] == [
        None,
        START_MS + 720 * DAY_MS,
        START_MS + 1440 * DAY_MS,
    ]
    assert all(c["limit"] == PAGE_LIMIT == 720 for c in ex.calls)
    assert all(c["params"] is None for c in ex.calls)  # no ccxt paginate option


def test_stops_on_non_advancing_page() -> None:
    page = candles(START_MS, 10)
    ex = FakeExchange([page, list(page)])  # Kraken repeats the same window
    df = _fetch(ex, _clock_after(10))
    assert len(df) == 10
    assert len(ex.calls) == 2


@pytest.mark.parametrize("exc_type", RETRYABLE)
def test_retryable_error_backs_off_and_retries(exc_type: type[Exception]) -> None:
    pages = [candles(START_MS, 5)]
    clean = _fetch(FakeExchange(list(pages)), _clock_after(5))
    clock = _clock_after(5)
    t0 = clock.now()
    ex = FakeExchange([exc_type("slow down"), *pages])
    df = _fetch(ex, clock)
    pd.testing.assert_frame_equal(df, clean)
    assert clock.sleep_calls == [t0 + timedelta(seconds=2)]


def test_backoff_is_exponential() -> None:
    clock = _clock_after(5)
    t0 = clock.now()
    ex = FakeExchange([ccxt.RateLimitExceeded("a"), ccxt.RequestTimeout("b"), candles(START_MS, 5)])
    _fetch(ex, clock, retry_base_seconds=1.5)
    assert clock.sleep_calls == [t0 + timedelta(seconds=1.5), t0 + timedelta(seconds=4.5)]


def test_retries_exhausted_raises_naming_tf_and_since() -> None:
    clock = _clock_after(5)
    since = START_MS + 3 * DAY_MS
    ex = FakeExchange([ccxt.DDoSProtection("x")] * 4)
    with pytest.raises(FetchError) as info:
        _fetch(ex, clock, since=since, max_retries=3)
    assert "1d" in info.value.defect and str(since) in info.value.defect
    assert info.value.open_at == pd.Timestamp(since, unit="ms", tz="UTC")
    assert len(ex.calls) == 4 and len(clock.sleep_calls) == 3


def test_zero_retries_fails_immediately() -> None:
    clock = _clock_after(5)
    with pytest.raises(FetchError):
        _fetch(FakeExchange([ccxt.ExchangeNotAvailable("x")]), clock, max_retries=0)
    assert clock.sleep_calls == []


def test_non_retryable_ccxt_error_is_not_retried() -> None:
    clock = _clock_after(5)
    ex = FakeExchange([ccxt.BadSymbol("nope"), candles(START_MS, 5)])
    with pytest.raises(FetchError, match="BadSymbol"):
        _fetch(ex, clock)
    assert len(ex.calls) == 1 and clock.sleep_calls == []


def test_open_candle_is_dropped() -> None:
    # 5 candles; the clock sits inside the 5th, so it is still open.
    df = _fetch(FakeExchange([candles(START_MS, 5)]), _clock_after(4, timedelta(hours=12)))
    assert len(df) == 4
    assert df["open_at"].iloc[-1] == pd.Timestamp(START_MS + 3 * DAY_MS, unit="ms", tz="UTC")


def test_candle_closing_exactly_now_is_kept() -> None:
    df = _fetch(FakeExchange([candles(START_MS, 5)]), _clock_after(5, timedelta(0)))
    assert len(df) == 5


def test_open_candle_changing_between_pages_is_not_a_conflict() -> None:
    # The running candle (day 4) is re-sent with new values after a backoff: not a conflict.
    first = candles(START_MS, 5)
    second = candles(START_MS + 3 * DAY_MS, 2)
    second[1][4] += 7.0  # open candle's close moved
    clock = _clock_after(4, timedelta(hours=12))
    ex = FakeExchange([first, ccxt.RateLimitExceeded("x"), second])
    df = _fetch(ex, clock)
    assert len(df) == 4
    assert df["open_at"].iloc[-1] == pd.Timestamp(START_MS + 3 * DAY_MS, unit="ms", tz="UTC")


def test_identical_page_overlap_is_kept_once() -> None:
    ex = FakeExchange([candles(START_MS, 10), candles(START_MS + 8 * DAY_MS, 5)])
    df = _fetch(ex, _clock_after(13))
    assert len(df) == 13 and df["open_at"].is_unique


def test_conflicting_page_overlap_raises() -> None:
    second = candles(START_MS + 8 * DAY_MS, 5)
    second[0][4] += 1.0  # close differs for a candle already seen
    ex = FakeExchange([candles(START_MS, 10), second])
    with pytest.raises(FetchError, match="conflicting") as info:
        _fetch(ex, _clock_after(13))
    assert info.value.open_at == pd.Timestamp(START_MS + 8 * DAY_MS, unit="ms", tz="UTC")


@pytest.mark.parametrize(
    "row",
    [
        [START_MS, 1.0, 2.0, 0.5, 1.5],  # too short
        [START_MS, 1.0, 2.0, 0.5, 1.5, 3.0, 7],  # too long
        [START_MS, "1.0", 2.0, 0.5, 1.5, 3.0],  # string
        [START_MS, None, 2.0, 0.5, 1.5, 3.0],  # null
        [START_MS, float("nan"), 2.0, 0.5, 1.5, 3.0],  # nan
        [START_MS, True, 2.0, 0.5, 1.5, 3.0],  # bool
        [float(START_MS), 1.0, 2.0, 0.5, 1.5, 3.0],  # float timestamp
        [START_MS + 1000, 1.0, 2.0, 0.5, 1.5, 3.0],  # not aligned to 1d
        "garbage",
    ],
)
def test_malformed_row_raises(row: object) -> None:
    with pytest.raises(FetchError):
        _fetch(FakeExchange([[candle(START_MS - DAY_MS), row]]), _clock_after(5))


def test_misaligned_for_4h_raises_but_aligned_passes() -> None:
    good = candles(START_MS, 6, H4_MS)
    df = _fetch(FakeExchange([good]), _clock_after(2), tf="4h")
    assert len(df) == 6
    bad = [candle(START_MS + 3600 * 1000)]  # 01:00 is not a 4h boundary
    with pytest.raises(FetchError, match="aligned"):
        _fetch(FakeExchange([bad]), _clock_after(2), tf="4h")


def test_rows_before_since_are_ignored() -> None:
    since = START_MS + 5 * DAY_MS
    ex = FakeExchange([candles(START_MS, 10)])  # Kraken returns its window regardless
    df = _fetch(ex, _clock_after(10), since=since)
    assert len(df) == 5
    assert df["open_at"].iloc[0] == pd.Timestamp(since, unit="ms", tz="UTC")
    assert ex.calls[0]["since"] == since


def test_empty_first_page_gives_empty_frame() -> None:
    df = _fetch(FakeExchange([]), _clock_after(5))
    assert df.empty and tuple(df.columns) == COLUMNS


def test_public_exchange_is_unauthenticated() -> None:
    ex = make_public_exchange()
    assert isinstance(ex, ccxt.kraken)
    assert ex.enableRateLimit is True
    assert not ex.apiKey and not ex.secret


# --- price tick (story 4, CON-03) ------------------------------------------------------------


def test_price_tick_from_market_metadata() -> None:
    ex = FakeExchange(markets={"BTC/EUR": {"precision": {"price": 0.5}}})
    assert price_tick(ex, "BTC/EUR") == 0.5
    assert ex.load_markets_calls == 1
    assert price_tick(FakeExchange(), "BTC/EUR") == TICK


def test_real_kraken_client_uses_tick_size_precision_mode() -> None:
    assert make_public_exchange().precisionMode == ccxt.TICK_SIZE  # no network: attribute only


@pytest.mark.parametrize(
    "markets",
    [
        {"BTC/EUR": {"precision": {"price": 0}}},
        {"BTC/EUR": {"precision": {"price": -0.1}}},
        {"BTC/EUR": {"precision": {"price": float("nan")}}},
        {"BTC/EUR": {"precision": {"price": float("inf")}}},
        {"BTC/EUR": {"precision": {"price": None}}},
        {"BTC/EUR": {"precision": {"price": "0.1"}}},
        {"BTC/EUR": {"precision": {"price": True}}},
        {"BTC/EUR": {"precision": {}}},
        {"BTC/EUR": {}},
        {"ETH/EUR": {"precision": {"price": 0.01}}},
    ],
)
def test_bad_or_missing_tick_is_refused(markets: object) -> None:
    with pytest.raises(FetchError, match="tick|precision"):
        price_tick(FakeExchange(markets=markets), "BTC/EUR")


def test_non_tick_size_precision_mode_is_refused() -> None:
    ex = FakeExchange(precisionMode=ccxt.DECIMAL_PLACES)
    with pytest.raises(FetchError, match="not TICK_SIZE"):
        price_tick(ex, "BTC/EUR")
    assert ex.load_markets_calls == 0


def test_load_markets_failure_is_a_fetch_error() -> None:
    with pytest.raises(FetchError, match="load_markets failed: NetworkError"):
        price_tick(FakeExchange(markets=ccxt.NetworkError("down")), "BTC/EUR")
