"""A fake PUBLIC ccxt Kraken client for dry-run tests (AD-24: never touches the network).

It serves ``fetch_ohlcv``, ``fetch_ticker``, ``load_markets`` and ``fetch_time`` from a
price function of time, timed by the test clock. Candles are aligned, the newest one is
still forming (as Kraken returns it) and only ``OHLCV_LIMIT`` rows come back. Failures can
be scripted per endpoint with ``fail(endpoint, error, times)``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import ccxt

from bot.clock import Clock
from bot.config import TIMEFRAME_SECONDS

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def rising(start: float = 40000.0, per_day: float = 50.0) -> Callable[[datetime], float]:
    """A steadily rising price (v0 goes long)."""
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    return lambda t: start + per_day * (t - t0).total_seconds() / 86400


class FakePublicKraken:
    precisionMode = ccxt.TICK_SIZE
    rateLimit = 1000

    def __init__(
        self,
        clock: Clock,
        price: Callable[[datetime], float] | None = None,
        *,
        half_spread: float = 0.5,
        candle_range: float = 0.0,
        status: str = "online",
        server_offset: timedelta = timedelta(0),
    ) -> None:
        self.clock = clock
        self.price = price or rising()
        self.half_spread = half_spread
        self.candle_range = candle_range  # high/low distance from the open/close envelope
        self.status = status
        self.server_offset = server_offset
        self.calls: dict[str, int] = defaultdict(int)
        self._fail: dict[str, list[Exception]] = defaultdict(list)
        self.quotes: Callable[[datetime], tuple[float, float]] | None = None
        self.ohlcv_override: dict[str, Callable[[int], tuple[float, ...]]] = {}

    def fail(self, endpoint: str, error: Exception, times: int = 1) -> None:
        self._fail[endpoint].extend([error] * times)

    def _maybe_fail(self, endpoint: str) -> None:
        self.calls[endpoint] += 1
        if self._fail[endpoint]:
            raise self._fail[endpoint].pop(0)

    # --- public endpoints ----------------------------------------------------------------

    def fetch_ohlcv(self, symbol: str, timeframe: str, since=None, limit=None):  # noqa: ANN001, ANN201
        self._maybe_fail("fetch_ohlcv")
        step = TIMEFRAME_SECONDS[timeframe]
        now = self.clock.now()
        n_now = int((now - _EPOCH).total_seconds()) // step  # index of the forming candle
        count = min(limit or 720, 720)
        rows = []
        for i in range(n_now - count + 1, n_now + 1):
            open_ms = i * step * 1000
            if timeframe in self.ohlcv_override:
                o, h, lo, c, v = self.ohlcv_override[timeframe](open_ms)
            else:
                t_open = _EPOCH + timedelta(seconds=i * step)
                o = self.price(t_open)
                c = self.price(min(now, t_open + timedelta(seconds=step)))
                h = max(o, c) + self.candle_range
                lo = min(o, c) - self.candle_range
                v = 1.0
            rows.append([open_ms, o, h, lo, c, v])
        return rows

    def fetch_ticker(self, symbol: str) -> dict:
        self._maybe_fail("fetch_ticker")
        now = self.clock.now()
        if self.quotes is not None:
            bid, ask = self.quotes(now)
        else:
            mid = self.price(now)
            bid, ask = mid - self.half_spread, mid + self.half_spread
        return {
            "symbol": symbol,
            "bid": bid,
            "ask": ask,
            "last": (bid + ask) / 2,
            "timestamp": None,
        }

    def load_markets(self, reload: bool = False) -> dict:
        self._maybe_fail("load_markets")
        return {
            "BTC/EUR": {
                "id": "XXBTZEUR",
                "base": "BTC",
                "quote": "EUR",
                "active": self.status == "online",
                "precision": {"amount": 1e-08, "price": 0.1},
                "limits": {"amount": {"min": 6e-05}, "cost": {"min": 0.45}},
                "info": {"status": self.status},
            }
        }

    def fetch_time(self) -> int:
        self._maybe_fail("fetch_time")
        return int(((self.clock.now() - self.server_offset) - _EPOCH).total_seconds() * 1000)
