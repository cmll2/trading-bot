"""Market data: candle download, local Parquet cache, validation (FR-01 to FR-04, AD-18). M1.

Planned modules: archive (Kraken OHLCVT archive import), fetch (ccxt recent candles),
validate (fail loudly, never repair), cache (var/data/BTC-EUR/{timeframe}.parquet),
market (MarketData port).
"""
