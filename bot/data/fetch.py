"""Recent candles from Kraken's public OHLC endpoint through ccxt (FR-01, FR-04, AD-18).

Public and unauthenticated only: the exchange object is built with
``{"enableRateLimit": True}`` and never receives an API key or secret.

Kraken's OHLC endpoint returns at most the last 720 candles of a timeframe, whatever
``since`` asks for; older history comes from the Kraken OHLCVT archive (story 3). We
paginate ourselves (no ccxt ``paginate`` option) and stop when a page brings nothing new.
"""

from __future__ import annotations

import math
from datetime import timedelta
from typing import Any

import ccxt
import pandas as pd

from bot.clock import Clock
from bot.data.cache import interval_ms, normalize

PAGE_LIMIT = 720

RETRYABLE: tuple[type[Exception], ...] = (
    ccxt.RateLimitExceeded,
    ccxt.DDoSProtection,
    ccxt.RequestTimeout,
    ccxt.ExchangeNotAvailable,
)


class FetchError(RuntimeError):
    """Download failed or returned defective data. Nothing is written to the cache."""

    def __init__(self, defect: str, open_at: object = None) -> None:
        self.defect = defect
        self.open_at = open_at
        super().__init__(defect if open_at is None else f"{defect} at {open_at}")


def make_public_exchange() -> ccxt.kraken:
    """Unauthenticated Kraken client for public market data only."""
    return ccxt.kraken({"enableRateLimit": True})


def price_tick(exchange: Any, symbol: str) -> float:
    """The market's price tick from exchange metadata (CON-03: never hardcoded).

    Calls ``exchange.load_markets()`` and reads ``market["precision"]["price"]``, which is a
    tick size only in ccxt's TICK_SIZE precision mode (Kraken's). Anything else, or a tick
    that is not a positive finite number, is refused with ``FetchError``.
    """
    mode = getattr(exchange, "precisionMode", None)
    if mode != ccxt.TICK_SIZE:
        raise FetchError(f"exchange precision mode {mode!r} is not TICK_SIZE; tick unknown")
    try:
        markets = exchange.load_markets()
    except ccxt.BaseError as exc:
        raise FetchError(f"load_markets failed: {type(exc).__name__}: {exc}") from exc
    try:
        tick = markets[symbol]["precision"]["price"]
    except (KeyError, TypeError) as exc:
        raise FetchError(f"no price precision for {symbol} in market metadata") from exc
    if not _is_number(tick) or tick <= 0:
        raise FetchError(f"invalid price tick for {symbol} in market metadata: {tick!r}")
    return float(tick)


def _ts(ms: int | None) -> object:
    return None if ms is None else pd.Timestamp(ms, unit="ms", tz="UTC")


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _parse_row(row: Any, tf: str, step: int) -> tuple[int, tuple[float, ...]]:
    if not isinstance(row, list | tuple) or len(row) != 6:
        raise FetchError(f"malformed {tf} OHLCV row {row!r} (expected 6 fields)")
    ts, *values = row
    if not isinstance(ts, int) or isinstance(ts, bool):
        raise FetchError(f"malformed {tf} OHLCV row {row!r} (timestamp not an integer)")
    if not all(_is_number(v) for v in values):
        raise FetchError(f"non-numeric {tf} OHLCV row {list(row)!r}", _ts(ts))
    if ts % step != 0:
        raise FetchError(f"{tf} candle timestamp not aligned to interval", _ts(ts))
    return ts, tuple(float(v) for v in values)


def _fetch_page(
    exchange: Any,
    symbol: str,
    tf: str,
    cursor: int | None,
    clock: Clock,
    max_retries: int,
    retry_base_seconds: float,
) -> list[Any]:
    """One ``fetch_ohlcv`` call with exponential backoff on retryable errors."""
    attempt = 0
    while True:
        try:
            return exchange.fetch_ohlcv(symbol, tf, since=cursor, limit=PAGE_LIMIT)
        except RETRYABLE as exc:
            if attempt >= max_retries:
                raise FetchError(
                    f"{tf} fetch since {cursor} failed after {max_retries} retries: "
                    f"{type(exc).__name__}: {exc}",
                    _ts(cursor),
                ) from exc
            delay = retry_base_seconds * 2**attempt
            clock.sleep_until(clock.now() + timedelta(seconds=delay))
            attempt += 1
        except ccxt.BaseError as exc:
            raise FetchError(
                f"{tf} fetch since {cursor} failed: {type(exc).__name__}: {exc}", _ts(cursor)
            ) from exc


def fetch_closed_candles(
    exchange: Any,
    symbol: str,
    tf: str,
    since_ms: int | None,
    clock: Clock,
    max_retries: int,
    retry_base_seconds: float,
) -> pd.DataFrame:
    """Fetch closed candles with ``open_at >= since_ms`` (all available if None).

    Returns a normalised cache frame with ``source="api"`` and ``trades=<NA>`` (ccxt's
    unified OHLCV drops Kraken's trade count). Overlapping pages must agree exactly;
    conflicting values raise ``FetchError``. Candles still open at ``clock.now()`` are
    dropped.
    """
    step = interval_ms(tf)
    candles: dict[int, tuple[float, ...]] = {}
    cursor = since_ms
    while True:
        page = _fetch_page(exchange, symbol, tf, cursor, clock, max_retries, retry_base_seconds)
        if not page:
            break
        page_now_ms = clock.now().timestamp() * 1000
        newest: int | None = None
        for raw in page:
            ts, values = _parse_row(raw, tf, step)
            if since_ms is not None and ts < since_ms:
                continue
            if ts + step > page_now_ms:
                continue  # still open: its values change between requests; never compared
            previous = candles.get(ts)
            if previous is not None and previous != values:
                raise FetchError(f"conflicting {tf} values across pages", _ts(ts))
            candles[ts] = values
            if cursor is None or ts >= cursor:
                newest = ts if newest is None else max(newest, ts)
        if newest is None:
            break
        cursor = newest + step

    now_ms = clock.now().timestamp() * 1000
    closed = sorted(ts for ts in candles if ts + step <= now_ms)
    df = pd.DataFrame(
        {
            "open_at": pd.to_datetime(closed, unit="ms", utc=True),
            "open": [candles[t][0] for t in closed],
            "high": [candles[t][1] for t in closed],
            "low": [candles[t][2] for t in closed],
            "close": [candles[t][3] for t in closed],
            "volume": [candles[t][4] for t in closed],
            "trades": pd.array([pd.NA] * len(closed), dtype="Int64"),
            "source": ["api"] * len(closed),
        }
    )
    return normalize(df)
