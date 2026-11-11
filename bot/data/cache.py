"""Local Parquet candle cache (AD-18).

One file per pair and timeframe: ``{var_dir}/data/BTC-EUR/{timeframe}.parquet``. Columns are
exactly ``COLUMNS`` with fixed dtypes (see ``normalize``). Writes are atomic: a temporary
sibling file is written, then moved over the target with ``os.replace``, so a crash never
leaves a half-written cache.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path

import numpy as np
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


DATA_HASH_VERSION = b"bot-candles-v1"


def data_hash(df: pd.DataFrame) -> str:
    """Deterministic sha256 hex of a candle frame's values (NFR-02, AD-21).

    The frame is first normalised to the cache schema, then serialised canonically, column
    by column in ``COLUMNS`` order, each column prefixed by its name and the row count:

    - ``open_at``: int64 milliseconds since the epoch, little-endian;
    - prices and volume: the exact float64 bytes, little-endian;
    - ``trades``: one byte per row (1 = NA, 0 = value) then int64 values with NA as 0;
    - ``source``: per row a length-prefixed utf-8 string, or a ``-1`` length for NA.

    The same values always give the same hex; any value change changes it. The index and
    the Parquet file's metadata are ignored.
    """
    frame = normalize(df)
    n = len(frame)
    h = hashlib.sha256(DATA_HASH_VERSION)

    def _section(name: str, payload: bytes) -> None:
        h.update(name.encode("utf-8"))
        h.update(np.int64(n).astype("<i8").tobytes())
        h.update(np.int64(len(payload)).astype("<i8").tobytes())
        h.update(payload)

    _section("open_at", frame["open_at"].dt.as_unit("ms").astype("int64").to_numpy("<i8").tobytes())
    for col in PRICE_COLUMNS:
        _section(col, frame[col].to_numpy(dtype="<f8").tobytes())
    trades = frame["trades"]
    na = trades.isna().to_numpy(dtype=bool)
    _section(
        "trades",
        na.astype("u1").tobytes() + trades.fillna(0).to_numpy(dtype="<i8").tobytes(),
    )
    parts: list[bytes] = []
    for value in frame["source"].to_numpy(dtype=object):
        if pd.isna(value):
            parts.append(np.int64(-1).astype("<i8").tobytes())
        else:
            raw = str(value).encode("utf-8")
            parts.append(np.int64(len(raw)).astype("<i8").tobytes() + raw)
    _section("source", b"".join(parts))
    return h.hexdigest()
