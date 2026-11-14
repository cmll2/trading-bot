"""Builds the backtest-vs-paper consistency fixture (story M3-9, AD-6). Run once from the
repo root: ``uv run python tests/fixtures/consistency/make_fixture.py``. Reads the local
cache only (no network).

- ``candles_15m.csv``: REAL Kraken BTC/EUR 15m candles copied from the validated cache
  ``var/data/BTC-EUR/15m.parquet`` for 2026-11-05 00:00 .. 2026-11-08 00:00 UTC.
- ``quotes.csv``: bid/ask every 5 minutes DERIVED from those candles (not recorded live):
  mid moves linearly from the forming candle's open to its close, half spread 1-3 bp
  (deterministic). Same column meaning as the dry-run's ``api_calls`` ``priced_from`` /
  ``fetch_ticker`` detail (bid, ask), so a recorded session can replace it.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
START, END = pd.Timestamp("2026-11-05", tz="UTC"), pd.Timestamp("2026-11-08", tz="UTC")


def main() -> None:
    frame = pd.read_parquet(HERE.parents[2] / "var" / "data" / "BTC-EUR" / "15m.parquet")
    frame = frame[(frame["open_at"] >= START) & (frame["open_at"] < END)]
    assert len(frame) == 288 and (frame["source"] != "synthetic").all()
    out = frame[["open_at", "open", "high", "low", "close", "volume"]].copy()
    out["open_at"] = out["open_at"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out.to_csv(HERE / "candles_15m.csv", index=False)
    rows = []
    for i, c in enumerate(frame.itertuples()):
        for k in range(3):
            frac = k / 3
            mid = c.open + (c.close - c.open) * frac
            half = mid * (1 + (i + k) % 3) / 10_000
            at = c.open_at + pd.Timedelta(minutes=5 * k)
            rows.append(
                (at.strftime("%Y-%m-%dT%H:%M:%SZ"), round(mid - half, 1), round(mid + half, 1))
            )
    pd.DataFrame(rows, columns=["at", "bid", "ask"]).to_csv(HERE / "quotes.csv", index=False)


if __name__ == "__main__":
    main()
