"""Market data: candle download, local Parquet cache, validation (FR-01 to FR-04, AD-18). M1.

Modules:
- cache: schema, path and atomic read/write of var/data/BTC-EUR/{timeframe}.parquet
- fetch: recent closed candles from Kraken's public OHLC endpoint (ccxt, unauthenticated)
- update: incremental cache update (``bot data update``)
- validate: fail loudly, never repair (``bot data validate``); read-only no-trade run audit
  (``bot data audit-gaps``)
- archive: Kraken OHLCVT ZIP archive import, checksum first (``bot data import-archive``)
- merge: overlap-checked merge of archive, synthetic and API rows (both writers)
- market: MarketData port and ReplayMarketData; strategies read candles only through the
  immutable closed-candle view ``bot.candles.CandleHistory``
"""
