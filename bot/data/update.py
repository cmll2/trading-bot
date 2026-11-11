"""Incremental cache update from the public API (FR-02, AD-18).

Reads the cache, fetches only candles after its last ``open_at``, combines both through the
overlap-checked ``merge_candles`` (story 4; the tick comes from exchange metadata), applies
``data.no_trade_policy`` (the writer's job; the validator never fills), validates the
combined frame and writes it atomically. Any error raises before the cache is touched.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from bot.clock import Clock
from bot.config import Settings
from bot.data.cache import cache_path, interval_ms, write_cache
from bot.data.fetch import FetchError, fetch_closed_candles, price_tick
from bot.data.merge import OverlapStats, merge_candles
from bot.data.validate import apply_no_trade_policy, read_cache_checked, validate_frame


def update_timeframe_with_stats(
    settings: Settings, exchange: Any, clock: Clock, tf: str
) -> tuple[pd.DataFrame, OverlapStats]:
    """Bring ``{var_dir}/data/{pair}/{tf}.parquet`` up to the last closed candle; also return
    the overlap statistics of the merge (zero rows compared when nothing overlapped)."""
    pair = settings.pairs[0]
    path = cache_path(settings.paths.var_dir, pair, tf)
    tick = price_tick(exchange, pair)  # refuse a missing/invalid tick before fetching
    cached = read_cache_checked(path)
    since: int | None = None
    if cached is not None:
        validate_frame(cached, tf, settings.data)  # never build on a defective (or empty) cache
        since = int(cached["open_at"].astype("int64").iloc[-1]) + interval_ms(tf)

    fetched = fetch_closed_candles(
        exchange,
        pair,
        tf,
        since,
        clock,
        settings.data.fetch_max_retries,
        settings.data.fetch_retry_base_seconds,
    )
    if fetched.empty:
        if cached is None:
            raise FetchError(f"no closed candles returned for {tf}")
        return cached, OverlapStats()

    combined, stats = merge_candles(
        cached,
        fetched,
        tick,
        settings.data.overlap_price_tolerance_ticks,
        settings.data.overlap_volume_tolerance_fraction,
        tf=tf,
    )
    combined = apply_no_trade_policy(combined, tf, settings.data.no_trade_policy)
    validate_frame(combined, tf, settings.data, now=clock.now())
    write_cache(path, combined)
    return combined, stats


def update_timeframe(settings: Settings, exchange: Any, clock: Clock, tf: str) -> pd.DataFrame:
    """``update_timeframe_with_stats`` without the statistics."""
    return update_timeframe_with_stats(settings, exchange, clock, tf)[0]
