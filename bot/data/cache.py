"""Local Parquet candle cache (AD-18).

One file per pair and timeframe: ``{var_dir}/data/BTC-EUR/{timeframe}.parquet``. Columns are
exactly ``COLUMNS`` with fixed dtypes (see ``normalize``). Writes are atomic: a temporary
sibling file is written, then moved over the target with ``os.replace``, so a crash never
leaves a half-written cache.
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from bot.config import TIMEFRAME_SECONDS

COLUMNS = ("open_at", "open", "high", "low", "close", "volume", "trades", "source")
PRICE_COLUMNS = ("open", "high", "low", "close", "volume")
SOURCES = ("archive", "api", "synthetic")

OPEN_AT_DTYPE = pd.DatetimeTZDtype(unit="ms", tz="UTC")
DTYPES: dict[str, object] = {
    "open_at": OPEN_AT_DTYPE,
    **{c: "float64" for c in PRICE_COLUMNS},
    "trades": "Int64",  # nullable: API rows carry <NA> (ccxt drops Kraken's trade count)
    "source": pd.StringDtype(),
}


def interval_ms(tf: str) -> int:
    """Candle interval in milliseconds."""
    return TIMEFRAME_SECONDS[tf] * 1000


def pair_dirname(pair: str) -> str:
    """``BTC/EUR`` -> ``BTC-EUR``."""
    return pair.replace("/", "-")


def cache_path(var_dir: Path, pair: str, tf: str) -> Path:
    return var_dir / "data" / pair_dirname(pair) / f"{tf}.parquet"


def empty_frame() -> pd.DataFrame:
    return normalize(pd.DataFrame({c: [] for c in COLUMNS}))


def normalize(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with exactly ``COLUMNS`` in order and the cache dtypes.

    Raises ``KeyError`` if a column is missing. Naive ``open_at`` is NOT localised: a cast
    of naive datetimes to a UTC dtype raises, so non-UTC data never sneaks in.
    """
    out = df.loc[:, list(COLUMNS)].copy()
    for col, dtype in DTYPES.items():
        out[col] = out[col].astype(dtype)  # type: ignore[call-overload]
    return out.reset_index(drop=True)


def read_cache(path: Path) -> pd.DataFrame | None:
    """Read the cache file as stored (no dtype coercion), or None if it does not exist."""
    if not path.exists():
        return None
    return pd.read_parquet(path)


def write_cache(path: Path, df: pd.DataFrame) -> None:
    """Atomically write ``df`` (normalised) to ``path``."""
    frame = normalize(df)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        frame.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()
