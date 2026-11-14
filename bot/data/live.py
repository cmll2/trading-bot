"""Live PUBLIC market data for dry-run (FR-24, AD-1, AD-2, AD-6, NFR-05).

Everything here uses Kraken's public, unauthenticated endpoints through a ccxt client
built by ``bot.data.fetch.make_public_exchange`` (never an API key):

- ``CcxtMarketData``: the ``MarketData`` port over ``fetch_ohlcv``. Closed candles only
  (``CandleHistory`` drops the still-forming one); a frame per (pair, timeframe) is cached
  and refetched only when a newer candle can have closed, so the 30 s engine tick does not
  hammer the API. On a failed refresh the last good frame is served (it goes stale and the
  ``stale_candle`` rule blocks trading); with no frame at all it raises
  ``TransientReadError``.
- ``LiveFeed``: ticker (``fetch_ticker``; Kraken's ticker has no timestamp, so ``ts`` is
  the local receipt time), market rules (``load_markets``: minimums, precision, status,
  never hardcoded, CON-03) and the exchange server time (``fetch_time``, AD-2 skew check).

Every call is recorded through an ``ApiRecorder`` (endpoint, latency, ok, rate-limited,
detail): the store's ``api_calls`` table in dry-run (NFR-05). The ticker detail holds the
bid/ask the engine priced from (AD-6 consistency input). ccxt errors map to the broker
taxonomy: rate limits -> ``RateLimited``, everything else on a read ->
``TransientReadError`` (reads are always safe to retry).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import ccxt
import pandas as pd

from bot.broker.base import MarketRules, Ticker
from bot.broker.errors import RateLimited, TransientReadError
from bot.candles import CandleHistory
from bot.clock import Clock
from bot.config import TIMEFRAME_SECONDS
from bot.data.cache import normalize
from bot.data.fetch import FetchError, _parse_row

ApiRecorder = Callable[[str, int, bool, bool, dict[str, Any] | None], None]
OHLCV_LIMIT = 720  # Kraken's OHLC endpoint returns at most the last 720 candles
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_RATE_LIMIT_ERRORS = (ccxt.RateLimitExceeded, ccxt.DDoSProtection)


def _null_recorder(
    endpoint: str, latency_ms: int, ok: bool, rate_limited: bool, detail: dict[str, Any] | None
) -> None:
    return None


def _dec(x: object, what: str) -> Decimal:
    if x is None or isinstance(x, bool):
        raise TransientReadError(f"missing {what} in exchange response")
    try:
        value = Decimal(str(x))
    except ArithmeticError as exc:
        raise TransientReadError(f"invalid {what} {x!r} in exchange response") from exc
    if not value.is_finite() or value <= 0:
        raise TransientReadError(f"invalid {what} {x!r} in exchange response")
    return value


class _Caller:
    """Times one ccxt call through the clock, records it and maps errors (shared)."""

    def __init__(self, exchange: Any, clock: Clock, recorder: ApiRecorder | None) -> None:
        self.exchange = exchange
        self.clock = clock
        self.recorder = recorder or _null_recorder

    def call(
        self, endpoint: str, fn: Callable[[], Any], detail: Callable[[Any], dict] | None = None
    ) -> Any:
        start = self.clock.now()
        try:
            result = fn()
        except _RATE_LIMIT_ERRORS as exc:
            self._record(endpoint, start, False, True, {"error": type(exc).__name__})
            retry = max(1.0, float(getattr(self.exchange, "rateLimit", 1000) or 1000) / 1000)
            raise RateLimited(retry) from exc
        except ccxt.BaseError as exc:
            self._record(endpoint, start, False, False, {"error": type(exc).__name__})
            raise TransientReadError(f"{endpoint} failed: {type(exc).__name__}: {exc}") from exc
        self._record(endpoint, start, True, False, detail(result) if detail else None)
        return result

    def _record(
        self, endpoint: str, start: datetime, ok: bool, limited: bool, detail: dict | None
    ) -> None:
        latency = int((self.clock.now() - start) / timedelta(milliseconds=1))
        self.recorder(endpoint, max(0, latency), ok, limited, detail)


class CcxtMarketData:
    """``MarketData`` port over Kraken's public OHLC endpoint (dry-run, live)."""

    def __init__(
        self,
        exchange: Any,
        clock: Clock,
        pairs: tuple[str, ...],
        recorder: ApiRecorder | None = None,
        min_refetch: timedelta = timedelta(seconds=20),
    ) -> None:
        self._call = _Caller(exchange, clock, recorder)
        self._clock = clock
        self._pairs = tuple(pairs)
        self._min_refetch = min_refetch
        self._frames: dict[tuple[str, str], pd.DataFrame] = {}
        self._fetched_at: dict[tuple[str, str], datetime] = {}

    def _needs_refresh(self, key: tuple[str, str], now: datetime) -> bool:
        frame = self._frames.get(key)
        last = self._fetched_at.get(key)
        if last is not None and now - last < self._min_refetch:
            return False
        if frame is None or frame.empty:
            return True
        step = timedelta(seconds=TIMEFRAME_SECONDS[key[1]])
        newest = frame["open_at"].iloc[-1].to_pydatetime()
        return newest + 2 * step <= now  # a newer candle has closed since the last fetch

    def _fetch(self, pair: str, tf: str) -> pd.DataFrame:
        step_ms = TIMEFRAME_SECONDS[tf] * 1000
        rows = self._call.call(
            f"fetch_ohlcv:{tf}",
            lambda: self._call.exchange.fetch_ohlcv(pair, tf, limit=OHLCV_LIMIT),
            lambda r: {"rows": len(r)},
        )
        candles: dict[int, tuple[float, ...]] = {}
        try:
            for raw in rows or []:
                ts, values = _parse_row(raw, tf, step_ms)
                if ts in candles and candles[ts] != values:
                    raise FetchError(f"conflicting {tf} values in one response")
                candles[ts] = values
        except FetchError as exc:
            raise TransientReadError(f"defective {tf} OHLCV response: {exc}") from exc
        keys = sorted(candles)
        frame = pd.DataFrame(
            {
                "open_at": pd.to_datetime(keys, unit="ms", utc=True),
                "open": [candles[t][0] for t in keys],
                "high": [candles[t][1] for t in keys],
                "low": [candles[t][2] for t in keys],
                "close": [candles[t][3] for t in keys],
                "volume": [candles[t][4] for t in keys],
                "trades": pd.array([pd.NA] * len(keys), dtype="Int64"),
                "source": ["api"] * len(keys),
            }
        )
        return normalize(frame)

    def closed_candles(self, pair: str, timeframe: str, limit: int | None = None) -> CandleHistory:
        if pair not in self._pairs:
            raise ValueError(f"unknown pair {pair!r}; configured pairs are {list(self._pairs)}")
        if timeframe not in TIMEFRAME_SECONDS:
            raise ValueError(f"unknown timeframe {timeframe!r}")
        key = (pair, timeframe)
        now = self._clock.now()
        if self._needs_refresh(key, now):
            self._fetched_at[key] = now
            try:
                self._frames[key] = self._fetch(pair, timeframe)
            except (TransientReadError, RateLimited):
                if key not in self._frames:
                    raise
                # Serve the last good frame: it goes stale and stale_candle blocks trading.
        frame = self._frames[key]
        hist = CandleHistory.from_frame(frame, timeframe, now)
        if limit is not None and len(hist) > limit:
            # Rows are sorted, so the closed candles are a prefix of the frame.
            closed = frame.iloc[: len(hist)]
            return CandleHistory.from_frame(closed.iloc[len(closed) - limit :], timeframe, now)
        return hist


@dataclass(frozen=True)
class ServerTime:
    local_before: datetime
    local_after: datetime
    server: datetime

    @property
    def skew_seconds(self) -> float:
        """Local clock minus exchange clock, measured at the request midpoint."""
        mid = self.local_before + (self.local_after - self.local_before) / 2
        return (mid - self.server).total_seconds()


class LiveFeed:
    """Public ticker, market rules and server time (dry-run)."""

    def __init__(self, exchange: Any, clock: Clock, recorder: ApiRecorder | None = None) -> None:
        self._call = _Caller(exchange, clock, recorder)
        self._clock = clock

    def ticker(self, pair: str) -> Ticker:
        raw = self._call.call(
            "fetch_ticker",
            lambda: self._call.exchange.fetch_ticker(pair),
            lambda r: {"bid": str(r.get("bid")), "ask": str(r.get("ask")), "pair": pair},
        )
        received = self._clock.now()
        bid = _dec(raw.get("bid"), "bid")
        ask = _dec(raw.get("ask"), "ask")
        if ask <= bid:
            raise TransientReadError(f"crossed or locked book bid {bid} >= ask {ask}")
        last = raw.get("last")
        return Ticker(
            pair=pair,
            bid=bid,
            ask=ask,
            last=_dec(last, "last") if last is not None else (bid + ask) / 2,
            ts=received,
        )

    def market_rules(self, pair: str, reload: bool = True) -> MarketRules:
        markets = self._call.call("load_markets", lambda: self._call.exchange.load_markets(reload))
        try:
            m = markets[pair]
            limits, precision = m["limits"], m["precision"]
            info = m.get("info") or {}
            status = info.get("status") or ("online" if m.get("active") else "offline")
            rules = MarketRules(
                pair=pair,
                base=str(m["base"]),
                quote=str(m["quote"]),
                amount_min=_dec(limits["amount"]["min"], "amount_min"),
                cost_min=_dec(limits["cost"]["min"], "cost_min"),
                tick_size=_dec(precision["price"], "tick_size"),
                amount_step=_dec(precision["amount"], "amount_step"),
                status=str(status),
            )
        except (KeyError, TypeError) as exc:
            raise TransientReadError(f"incomplete market metadata for {pair}: {exc!r}") from exc
        if getattr(self._call.exchange, "precisionMode", ccxt.TICK_SIZE) != ccxt.TICK_SIZE:
            raise TransientReadError("exchange precision mode is not TICK_SIZE; tick unknown")
        return rules

    def server_time(self) -> ServerTime:
        before = self._clock.now()
        ms = self._call.call("fetch_time", lambda: self._call.exchange.fetch_time())
        after = self._clock.now()
        if not isinstance(ms, int | float) or isinstance(ms, bool):
            raise TransientReadError(f"invalid server time {ms!r}")
        return ServerTime(before, after, _EPOCH + timedelta(milliseconds=int(ms)))
