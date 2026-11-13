"""Synthetic candle caches and settings for backtest tests (never touches real data).

``make_env`` writes a copy of the real config.yaml whose ``var_dir`` and ``results_dir``
point into ``tmp_path``, with chosen ``history_start`` and strategy parameters, and writes
1d and 15m Parquet caches built from one 15m price path, so both timeframes agree.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from bot.config import Settings, load_settings
from bot.data.cache import cache_path, normalize, write_cache
from tests.conftest import REPO_ROOT

BARS_PER_DAY = 96


@dataclass(frozen=True)
class Env:
    settings: Settings
    config_path: Path
    env_path: Path
    results_dir: Path
    start: date


def path_15m(daily_closes: list[float], start_price: float) -> np.ndarray:
    """Linear 15m path: day i moves from the previous close to ``daily_closes[i]``."""
    out, prev = [], start_price
    for close in daily_closes:
        out.extend(np.linspace(prev, close, BARS_PER_DAY + 1)[1:])
        prev = close
    return np.asarray(out, dtype=float)


def frames_from_path(
    start: date,
    closes_15m: np.ndarray,
    start_price: float,
    wiggle: float = 0.001,
    synthetic_15m: set[int] | None = None,
    overrides: dict[int, tuple[float, float, float, float]] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(1d, 15m) cache frames. 15m candle j opens at the previous close and closes at
    ``closes_15m[j]``; high/low widen by ``wiggle``. ``synthetic_15m`` marks 15m rows as
    flat no-trade candles (open=high=low=close=previous close, volume 0)."""
    synthetic_15m = synthetic_15m or set()
    n = len(closes_15m)
    t0 = pd.Timestamp(datetime(start.year, start.month, start.day, tzinfo=UTC))
    open_at = t0 + pd.to_timedelta(np.arange(n) * 15, unit="min")
    opens = np.concatenate([[start_price], closes_15m[:-1]])
    closes = closes_15m.copy()
    highs = np.maximum(opens, closes) * (1 + wiggle)
    lows = np.minimum(opens, closes) * (1 - wiggle)
    vol = np.ones(n)
    source = np.array(["archive"] * n, dtype=object)
    for j, (o, h, lo, c) in (overrides or {}).items():
        opens[j], highs[j], lows[j], closes[j] = o, h, lo, c
    for j in sorted(synthetic_15m):
        prev = closes[j - 1]
        opens[j] = highs[j] = lows[j] = closes[j] = prev
        vol[j] = 0.0
        source[j] = "synthetic"
    f15 = pd.DataFrame(
        {
            "open_at": open_at,
            "open": opens,
            "high": highs,
            "low": lows,
            "close": closes,
            "volume": vol,
            "trades": pd.array([0 if s == "synthetic" else 1 for s in source], "Int64"),
            "source": source,
        }
    )
    g = f15.groupby(f15["open_at"].dt.floor("1D"))
    d = pd.DataFrame(
        {
            "open_at": g["open_at"].first().dt.floor("1D").to_numpy(),
            "open": g["open"].first().to_numpy(),
            "high": g["high"].max().to_numpy(),
            "low": g["low"].min().to_numpy(),
            "close": g["close"].last().to_numpy(),
            "volume": g["volume"].sum().to_numpy(),
            "trades": pd.array([1] * len(g), "Int64"),
            "source": ["archive"] * len(g),
        }
    )
    return normalize(d), normalize(f15)


def make_env(
    tmp_path: Path,
    daily_closes: list[float],
    *,
    start: date = date(2020, 1, 1),
    start_price: float | None = None,
    sma_days: int = 3,
    synthetic_15m: set[int] | None = None,
    overrides: dict[int, tuple[float, float, float, float]] | None = None,
    wiggle: float = 0.001,
    initial_quote: str = "20",
    config_edits: dict[str, object] | None = None,
) -> Env:
    tmp_path.mkdir(parents=True, exist_ok=True)
    data = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    data["paths"]["var_dir"] = str(tmp_path / "var")
    data["backtest"]["results_dir"] = str(tmp_path / "results")
    data["data"]["history_start"] = start.isoformat()
    data["strategy"]["params"] = {"sma_days": sma_days}
    data["paper"]["initial_quote"] = initial_quote
    data["backtest"]["lookahead_cutpoints"] = 3
    data["backtest"]["bootstrap_resamples"] = 200
    for dotted, value in (config_edits or {}).items():
        node = data
        *parents, leaf = dotted.split(".")
        for key in parents:
            node = node[key]
        node[leaf] = value
    config_path = tmp_path / "config.yaml"
    config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    env_path = tmp_path / "none.env"
    settings = load_settings(config_path, env_path)
    sp = start_price if start_price is not None else daily_closes[0]
    d1, d15 = frames_from_path(
        start,
        path_15m(daily_closes, sp),
        sp,
        wiggle=wiggle,
        synthetic_15m=synthetic_15m,
        overrides=overrides,
    )
    write_cache(cache_path(settings.paths.var_dir, "BTC/EUR", "1d"), d1)
    write_cache(cache_path(settings.paths.var_dir, "BTC/EUR", "15m"), d15)
    return Env(settings, config_path, env_path, tmp_path / "results", start)


def end_date(env: Env, n_days: int) -> date:
    return env.start + timedelta(days=n_days)
