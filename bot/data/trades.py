"""Candles rebuilt from Kraken's public trades (M1 story 9, FR-01, FR-03, AD-18, AD-24).

Kraken's OHLCVT archive ends before the public OHLC endpoint's window starts (that endpoint
keeps only the last 720 candles), so some ranges have no official candle source. They are
rebuilt from the complete public trade record:

- ``fetch_trades_range`` pages ``fetch_trades`` (public, unauthenticated, no ccxt
  ``paginate``) over ``[start, end)``. ccxt sends ``since`` in whole seconds, so pages
  overlap; trades are deduplicated by Kraken's sequential trade id (ccxt ``id``). The same id
  with different fields, a missing id, or a full page (``PAGE_LIMIT`` trades) that brings no
  new id raises ``FetchError``: trades are never skipped by bumping the cursor. ccxt keeps
  trades with time >= ``since``, so the cursor trade always comes back: a short page with no
  new id (or an empty page) means no trade since the cursor up to now, the end of the data.
  Progress is checkpointed atomically to a Parquet file so an interrupted run resumes from
  its last trade time.
- ``candles_from_trades`` aggregates with the archive's OHLCVT convention: bucket =
  floor(trade time / interval) in UTC; open = first trade, close = last (by time then id),
  high/low = max/min, volume = sum of amounts, trades = count. Buckets without a trade are
  omitted. ``fill_interior_buckets`` then handles the empty buckets strictly between the
  first and last trade bucket per ``data.no_trade_policy`` (flat ``synthetic`` rows, or
  fail); empty buckets at the window edges are never filled, so a hole touching a
  ``trades`` row stays a download gap.
- ``backfill_trades`` merges the rebuilt candles (``source="trades"``) into the cache through
  ``merge_candles`` -> ``apply_no_trade_policy`` -> ``validate_frame`` -> ``write_cache``.
  Any error raises before the candle cache is touched.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import ccxt
import numpy as np
import pandas as pd

from bot.clock import Clock
from bot.config import Settings
from bot.data.cache import cache_path, interval_ms, normalize, pair_dirname, write_cache
from bot.data.fetch import RETRYABLE, FetchError, price_tick
from bot.data.merge import OverlapStats, merge_candles
from bot.data.validate import (
    DataValidationError,
    apply_no_trade_policy,
    read_cache_checked,
    validate_frame,
)

TRADE_COLUMNS = ("ts_ms", "id", "price", "amount")
TRADE_DTYPES: dict[str, str] = {
    "ts_ms": "int64",
    "id": "int64",
    "price": "float64",
    "amount": "float64",
}
CHECKPOINT_EVERY_PAGES = 25
PAGE_LIMIT = 1000  # Kraken's maximum trades per public Trades request


def _ts(ms: int | None) -> object:
    return None if ms is None else pd.Timestamp(ms, unit="ms", tz="UTC")


def _is_number(v: object) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def checkpoint_path(var_dir: Path, pair: str, start: pd.Timestamp, end: pd.Timestamp) -> Path:
    """``{var_dir}/data/{PAIR-DIR}/trades/trades_{S:%Y%m%dT%H%M}_{E:%Y%m%dT%H%M}.parquet``."""
    name = f"trades_{start:%Y%m%dT%H%M}_{end:%Y%m%dT%H%M}.parquet"
    return var_dir / "data" / pair_dirname(pair) / "trades" / name


def _trades_frame(
    ts: list[int], ids: list[int], price: list[float], amount: list[float]
) -> pd.DataFrame:
    df = pd.DataFrame(
        {
            "ts_ms": np.asarray(ts, dtype="int64"),
            "id": np.asarray(ids, dtype="int64"),
            "price": np.asarray(price, dtype="float64"),
            "amount": np.asarray(amount, dtype="float64"),
        }
    )
    return df.sort_values(["ts_ms", "id"], kind="stable").reset_index(drop=True)


def _write_checkpoint(path: Path, df: pd.DataFrame) -> None:
    """Atomic write: temporary sibling then ``os.replace`` (as ``bot.data.cache``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    try:
        df.to_parquet(tmp, index=False)
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _load_checkpoint(path: Path, start_ms: int, end_ms: int) -> pd.DataFrame:
    """Read and validate a checkpoint; anything unexpected raises ``FetchError``."""
    try:
        df = pd.read_parquet(path)
    except (OSError, ValueError) as exc:  # pyarrow errors subclass these
        raise FetchError(f"bad trades checkpoint {path}: unreadable: {exc}") from exc
    if tuple(df.columns) != TRADE_COLUMNS:
        raise FetchError(
            f"bad trades checkpoint {path}: columns {list(df.columns)}, "
            f"expected {list(TRADE_COLUMNS)}"
        )
    for col, dtype in TRADE_DTYPES.items():
        if df[col].dtype != dtype:
            raise FetchError(
                f"bad trades checkpoint {path}: column {col} has dtype {df[col].dtype}, "
                f"expected {dtype}"
            )
    if df["id"].duplicated().any():
        raise FetchError(f"bad trades checkpoint {path}: duplicate trade ids")
    ts = df["ts_ms"].to_numpy()
    if ((ts < start_ms) | (ts >= end_ms)).any():
        raise FetchError(f"bad trades checkpoint {path}: trade time outside the window")
    price, amount = df["price"].to_numpy(), df["amount"].to_numpy()
    with np.errstate(invalid="ignore"):
        bad = ~np.isfinite(price) | ~np.isfinite(amount) | (price <= 0) | (amount <= 0)
    if bad.any():
        raise FetchError(f"bad trades checkpoint {path}: non-positive or non-finite values")
    return df


def _parse_id(raw: object) -> int:
    if isinstance(raw, int) and not isinstance(raw, bool):
        return raw
    if isinstance(raw, str) and raw.isascii() and raw.isdigit():
        return int(raw)
    raise FetchError(f"trade without a valid id: {raw!r}")


def _parse_trade(trade: Any) -> tuple[int, int, float, float]:
    """``(id, ts_ms, price, amount)`` from a ccxt trade dict, or ``FetchError``."""
    if not isinstance(trade, dict):
        raise FetchError(f"malformed trade {trade!r} (expected a dict)")
    tid = _parse_id(trade.get("id"))
    ts = trade.get("timestamp")
    if not isinstance(ts, int) or isinstance(ts, bool):
        raise FetchError(f"trade {tid}: timestamp {ts!r} is not an integer")
    price, amount = trade.get("price"), trade.get("amount")
    if not _is_number(price) or not _is_number(amount) or price <= 0 or amount <= 0:
        raise FetchError(f"trade {tid}: invalid price {price!r} or amount {amount!r}", _ts(ts))
    return tid, ts, float(price), float(amount)


def _fetch_trades_page(
    exchange: Any,
    symbol: str,
    cursor: int,
    clock: Clock,
    max_retries: int,
    retry_base_seconds: float,
    limit: int,
) -> list[Any]:
    """One ``fetch_trades`` call with exponential backoff on retryable errors."""
    attempt = 0
    while True:
        try:
            return exchange.fetch_trades(symbol, since=cursor, limit=limit)
        except RETRYABLE as exc:
            if attempt >= max_retries:
                raise FetchError(
                    f"trades fetch since {cursor} failed after {max_retries} retries: "
                    f"{type(exc).__name__}: {exc}",
                    _ts(cursor),
                ) from exc
            delay = retry_base_seconds * 2**attempt
            clock.sleep_until(clock.now() + timedelta(seconds=delay))
            attempt += 1
        except ccxt.BaseError as exc:
            raise FetchError(
                f"trades fetch since {cursor} failed: {type(exc).__name__}: {exc}", _ts(cursor)
            ) from exc


def fetch_trades_range_with_counts(
    exchange: Any,
    symbol: str,
    start_ms: int,
    end_ms: int,
    clock: Clock,
    max_retries: int,
    retry_base_seconds: float,
    checkpoint_path: Path,
    *,
    checkpoint_every: int = CHECKPOINT_EVERY_PAGES,
    page_limit: int = PAGE_LIMIT,
) -> tuple[pd.DataFrame, int]:
    """``fetch_trades_range``, also returning how many trades came from the checkpoint."""
    if start_ms >= end_ms:
        raise FetchError(f"empty trades window [{_ts(start_ms)}, {_ts(end_ms)})")
    ts: list[int] = []
    ids: list[int] = []
    price: list[float] = []
    amount: list[float] = []
    index: dict[int, int] = {}  # trade id -> position in the lists
    seen: set[int] = set()  # every id seen, also outside the window
    cursor = start_ms
    from_checkpoint = 0
    if checkpoint_path.exists():
        cp = _load_checkpoint(checkpoint_path, start_ms, end_ms)
        ts = cp["ts_ms"].tolist()
        ids = cp["id"].tolist()
        price = cp["price"].tolist()
        amount = cp["amount"].tolist()
        index = {tid: i for i, tid in enumerate(ids)}
        seen = set(ids)
        from_checkpoint = len(ids)
        if ts:
            cursor = max(ts)

    def _save() -> None:
        _write_checkpoint(checkpoint_path, _trades_frame(ts, ids, price, amount))

    pages = 0
    while True:
        page = _fetch_trades_page(
            exchange, symbol, cursor, clock, max_retries, retry_base_seconds, page_limit
        )
        if not page:
            break  # no trade since the cursor up to now
        pages += 1
        new = 0
        reached_end = False
        page_max = cursor
        for raw in page:
            tid, t, p, a = _parse_trade(raw)
            if tid in index:
                i = index[tid]
                if (ts[i], price[i], amount[i]) != (t, p, a):
                    raise FetchError(
                        f"conflicting fields for trade id {tid}: "
                        f"({ts[i]}, {price[i]!r}, {amount[i]!r}) vs ({t}, {p!r}, {a!r})",
                        _ts(t),
                    )
                continue
            if tid not in seen:
                seen.add(tid)
                new += 1
            if t >= end_ms:
                reached_end = True
                continue
            if t < start_ms:
                continue
            index[tid] = len(ids)
            ts.append(t)
            ids.append(tid)
            price.append(p)
            amount.append(a)
            page_max = max(page_max, t)
        if reached_end:
            break
        if new == 0:
            if len(page) < page_limit:
                break  # only the cursor trade(s) again: nothing since, up to now
            raise FetchError(
                f"no progress: a page of {len(page)} trades since {cursor} brought no new id",
                _ts(cursor),
            )
        cursor = page_max
        if pages % checkpoint_every == 0:
            _save()
    _save()
    return _trades_frame(ts, ids, price, amount), from_checkpoint


def fetch_trades_range(
    exchange: Any,
    symbol: str,
    start_ms: int,
    end_ms: int,
    clock: Clock,
    max_retries: int,
    retry_base_seconds: float,
    checkpoint_path: Path,
) -> pd.DataFrame:
    """Every public trade with ``start_ms <= time < end_ms``, sorted by (time, id).

    Columns ``ts_ms`` int64, ``id`` int64, ``price`` float64, ``amount`` float64. Resumes
    from ``checkpoint_path`` if it exists (validated first) and leaves it in place.
    ``end_ms`` must not be in the future: pagination stops at the first trade at or after
    ``end_ms``, at an empty page, or at a short page that brings no new id.
    """
    return fetch_trades_range_with_counts(
        exchange,
        symbol,
        start_ms,
        end_ms,
        clock,
        max_retries,
        retry_base_seconds,
        checkpoint_path,
    )[0]


def candles_from_trades(trades: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Aggregate trades into a normalised cache frame (``source="trades"``, ``trades``
    Int64). Buckets without a trade are omitted."""
    step = interval_ms(tf)
    t = trades.loc[:, list(TRADE_COLUMNS)].sort_values(["ts_ms", "id"], kind="stable")
    t = t.assign(bucket=(t["ts_ms"] // step) * step)
    g = t.groupby("bucket", sort=True)
    out = pd.DataFrame(
        {
            "open": g["price"].first(),
            "high": g["price"].max(),
            "low": g["price"].min(),
            "close": g["price"].last(),
            "volume": g["amount"].sum(),
            "trades": g["id"].count(),
        }
    ).reset_index()
    out["open_at"] = pd.to_datetime(out["bucket"].to_numpy(dtype="int64"), unit="ms", utc=True)
    out["source"] = "trades"
    return normalize(out)


def fill_interior_buckets(candles: pd.DataFrame, tf: str, policy: str) -> pd.DataFrame:
    """Handle empty buckets strictly between the first and last candle of ``candles`` (a
    sorted ``candles_from_trades`` frame): ``fill_flat`` inserts ``synthetic`` rows with
    O=H=L=C=the previous close, volume 0, trades 0; ``fail`` raises ``no-trade gap``."""
    if policy not in ("fill_flat", "fail"):
        raise ValueError(f"unknown no_trade_policy {policy!r}")
    if len(candles) < 2:
        return candles
    step = interval_ms(tf)
    have = candles["open_at"].astype("int64").to_numpy()
    full = np.arange(have[0], have[-1] + step, step, dtype="int64")
    missing = np.setdiff1d(full, have)
    if missing.size == 0:
        return candles
    if policy == "fail":
        raise DataValidationError("no-trade gap", _ts(int(missing[0])))
    prev_close = candles["close"].to_numpy()[np.searchsorted(have, missing) - 1]
    n = missing.size
    filled = normalize(
        pd.DataFrame(
            {
                "open_at": pd.to_datetime(missing, unit="ms", utc=True),
                "open": prev_close,
                "high": prev_close,
                "low": prev_close,
                "close": prev_close,
                "volume": np.zeros(n),
                "trades": np.zeros(n, dtype="int64"),
                "source": ["synthetic"] * n,
            }
        )
    )
    out = pd.concat([candles, filled], ignore_index=True)
    return normalize(out.sort_values("open_at", kind="stable"))


@dataclass(frozen=True)
class BackfillResult:
    frame: pd.DataFrame  # the merged, validated cache as written
    stats: OverlapStats
    trades_new: int  # fetched in this run
    trades_from_checkpoint: int
    candles_built: int  # buckets with at least one trade
    synthetic_filled: int  # interior empty buckets filled flat
    checkpoint: Path


def _utc(value: datetime | pd.Timestamp, name: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None or ts.utcoffset() != timedelta(0):
        raise FetchError(f"{name} {value!r} is not timezone-aware UTC")
    return ts.tz_convert("UTC")


def check_window(
    start: datetime | pd.Timestamp, end: datetime | pd.Timestamp, tf: str, now: datetime
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """``start``/``end`` timezone-aware UTC, aligned to ``tf``, ``start < end <= now``."""
    s, e = _utc(start, "start"), _utc(end, "end")
    step = interval_ms(tf)
    for name, ts in (("start", s), ("end", e)):
        if ts.value % (step * 1_000_000) != 0:
            raise FetchError(f"{name} {ts} is not aligned to the {tf} interval")
    if s >= e:
        raise FetchError(f"start {s} is not before end {e}")
    if e > _utc(now, "now"):
        raise FetchError(f"end {e} is in the future (now {now}): its last candle is not closed")
    return s, e


def backfill_trades(
    settings: Settings,
    exchange: Any,
    clock: Clock,
    tf: str,
    start: datetime | pd.Timestamp,
    end: datetime | pd.Timestamp,
) -> BackfillResult:
    """Rebuild ``tf`` candles over ``[start, end)`` from public trades and merge them into
    ``{var_dir}/data/{pair}/{tf}.parquet``. Nothing is written to the candle cache on error
    (the trades checkpoint is kept, so a rerun resumes)."""
    s, e = check_window(start, end, tf, clock.now())
    pair = settings.pairs[0]
    path = cache_path(settings.paths.var_dir, pair, tf)
    tick = price_tick(exchange, pair)  # refuse a missing/invalid tick before fetching
    cached = read_cache_checked(path)
    if cached is not None:
        validate_frame(cached, tf, settings.data)  # never build on a defective cache

    cp = checkpoint_path(settings.paths.var_dir, pair, s, e)
    trades, from_checkpoint = fetch_trades_range_with_counts(
        exchange,
        pair,
        s.value // 1_000_000,
        e.value // 1_000_000,
        clock,
        settings.data.fetch_max_retries,
        settings.data.fetch_retry_base_seconds,
        cp,
    )
    built = candles_from_trades(trades, tf)
    if built.empty:
        raise FetchError(f"no trades in [{s}, {e})")
    incoming = fill_interior_buckets(built, tf, settings.data.no_trade_policy)

    combined, stats = merge_candles(
        cached,
        incoming,
        tick,
        settings.data.overlap_price_tolerance_ticks,
        settings.data.overlap_volume_tolerance_fraction,
        tf=tf,
    )
    combined = apply_no_trade_policy(combined, tf, settings.data.no_trade_policy)
    validate_frame(combined, tf, settings.data, now=clock.now())
    write_cache(path, combined)
    return BackfillResult(
        frame=combined,
        stats=stats,
        trades_new=len(trades) - from_checkpoint,
        trades_from_checkpoint=from_checkpoint,
        candles_built=len(built),
        synthetic_filled=len(incoming) - len(built),
        checkpoint=cp,
    )
