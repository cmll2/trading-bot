"""Market data: candle download, local Parquet cache, validation (FR-01 to FR-04, AD-18). M1.

Modules:
- cache: schema, path and atomic read/write of var/data/BTC-EUR/{timeframe}.parquet
- fetch: recent closed candles from Kraken's public OHLC endpoint (ccxt, unauthenticated)
- update: incremental cache update (``bot data update``)
- validate: fail loudly, never repair (``bot data validate``)
- archive: Kraken OHLCVT ZIP archive import, checksum first (``bot data import-archive``)
- market: MarketData port
"""
