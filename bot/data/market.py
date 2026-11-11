"""MarketData port (architecture paradigm; AD-3, AD-18). Adapters CcxtMarketData and
ReplayMarketData arrive at M1/M2."""

from __future__ import annotations

from typing import Protocol


class MarketData(Protocol):
    """Source of closed candles and tickers. Signatures are fixed at M1."""

    def closed_candles(self, pair: str, timeframe: str) -> object: ...
