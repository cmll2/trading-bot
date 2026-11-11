"""Overlap-checked merge of candle sources (AD-18, assumption A-3). M1 story 4.

History comes from two sources: the Kraken OHLCVT archive and the public API (last 720
candles). Both writers (``bot data update`` and ``bot data import-archive``) combine what is
cached with what they bring through ``merge_candles``:

- rows present in both frames (same ``open_at``) must agree: each of open/high/low/close
  within ``price_tol_ticks`` x the exchange tick (read from market metadata, CON-03), volume
  within ``volume_tol_fraction`` of the larger of the two volumes; ``trades`` is never
  compared (API rows carry none). Any disagreement raises ``MergeError`` and nothing is
  merged: values are never averaged or patched;
- on agreement the row of the higher-precedence source is kept
  (archive > synthetic > api; on a tie the existing row stays), so per-row ``source``
  survives. Agreeing synthetic and api rows carry the same values, and keeping
  ``synthetic`` keeps every synthetic run bounded by archive rows (story 2);
- the result is sorted by ``open_at``, unique and normalized. Holes between the sources are
  not touched here: they stay download gaps (story 2 classification).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import Decimal

import numpy as np
import pandas as pd

from bot.data.cache import empty_frame, normalize
from bot.data.validate import DataValidationError

SOURCE_PRECEDENCE: dict[str, int] = {"archive": 3, "synthetic": 2, "api": 1}
PRICE_FIELDS = ("open", "high", "low", "close")
# Float epsilons: exactly N ticks passes, N ticks + 1 tick fails. The price epsilon is tied
# to the tick (a price-relative one would exceed a tick at very high prices).
_TICK_EPS = 1e-6
_REL_EPS = 1e-9  # volume: relative to the larger volume


class MergeError(DataValidationError):
    """Two sources disagree on an overlapping candle (or the merge inputs are unusable).
    Nothing is written."""

    def __init__(
        self,
        defect: str,
        open_at: object = None,
        tf: str | None = None,
        field: str | None = None,
    ) -> None:
        self.tf = tf
        self.field = field
        super().__init__(defect, open_at)


@dataclass(frozen=True)
class OverlapStats:
    rows_compared: int = 0
    max_price_diff_ticks: float = 0.0
    max_volume_diff_fraction: float = 0.0


def check_tick(tick: object) -> float:
    """A price tick must be a positive finite number (never a bool or a string)."""
    if (
        not isinstance(tick, int | float)
        or isinstance(tick, bool)
        or not math.isfinite(tick)
        or tick <= 0
    ):
        raise MergeError(f"invalid price tick {tick!r}: expected a positive finite number")
    return float(tick)


def _prepare(df: pd.DataFrame | None, role: str, tf: str | None) -> pd.DataFrame:
    if df is None or df.empty:
        return empty_frame()
    try:
        out = normalize(df)
    except (KeyError, ValueError, TypeError) as exc:
        raise MergeError(f"{role} frame unusable for merge: {exc}", tf=tf) from exc
    dup = out["open_at"].duplicated()
    if dup.any():
        raise MergeError(
            f"duplicate open_at in {role} frame",
            out["open_at"].iloc[int(dup.to_numpy().argmax())],
            tf=tf,
        )
    unknown = ~out["source"].isin(list(SOURCE_PRECEDENCE)).to_numpy(dtype=bool)
    if unknown.any():
        i = int(unknown.argmax())
        raise MergeError(
            f"unknown source {out['source'].iloc[i]!r} in {role} frame",
            out["open_at"].iloc[i],
            tf=tf,
        )
    return out.sort_values("open_at", kind="stable").reset_index(drop=True)


def merge_candles(
    existing: pd.DataFrame | None,
    incoming: pd.DataFrame | None,
    tick: float,
    price_tol_ticks: int,
    volume_tol_fraction: Decimal | float,
    *,
    tf: str | None = None,
) -> tuple[pd.DataFrame, OverlapStats]:
    """Union of ``existing`` and ``incoming``; overlapping rows must agree (see module doc).

    Pure: neither input is modified. Raises ``MergeError`` (``tf`` and ``field`` set) naming
    ``open_at``, the field, both values and the tolerance at the first disagreement (in
    ``open_at`` order, fields in the order open, high, low, close, volume).
    """
    tick = check_tick(tick)
    if isinstance(price_tol_ticks, bool) or not isinstance(price_tol_ticks, int):
        raise MergeError(f"invalid price tolerance {price_tol_ticks!r} ticks")
    vol_frac = float(volume_tol_fraction)
    if price_tol_ticks < 0 or not (0 <= vol_frac < 1):
        raise MergeError(
            f"invalid overlap tolerances: {price_tol_ticks} ticks, volume {volume_tol_fraction}"
        )
    old = _prepare(existing, "existing", tf)
    new = _prepare(incoming, "incoming", tf)

    old_ms = old["open_at"].astype("int64").to_numpy()
    new_ms = new["open_at"].astype("int64").to_numpy()
    in_old = np.isin(old_ms, new_ms)
    in_new = np.isin(new_ms, old_ms)
    a = old[in_old].reset_index(drop=True)  # both sorted and unique: rows align
    b = new[in_new].reset_index(drop=True)

    stats = OverlapStats()
    keep_new = np.zeros(len(b), dtype=bool)
    if len(a):
        price_tol = price_tol_ticks * tick
        diffs: dict[str, np.ndarray] = {}
        bad: dict[str, np.ndarray] = {}
        for col in PRICE_FIELDS:
            x, y = a[col].to_numpy(dtype="float64"), b[col].to_numpy(dtype="float64")
            d = np.abs(x - y)
            diffs[col] = d
            bad[col] = ~(d <= price_tol + _TICK_EPS * tick)
        vx, vy = a["volume"].to_numpy(dtype="float64"), b["volume"].to_numpy(dtype="float64")
        vmax = np.maximum(np.abs(vx), np.abs(vy))
        vd = np.abs(vx - vy)
        bad["volume"] = ~(vd <= vol_frac * vmax + _REL_EPS * vmax)
        fields = (*PRICE_FIELDS, "volume")
        any_bad = np.zeros(len(a), dtype=bool)
        for col in fields:
            any_bad |= bad[col]
        if any_bad.any():
            i = int(any_bad.argmax())
            col = next(c for c in fields if bad[c][i])
            x_val, y_val = float(a[col].iloc[i]), float(b[col].iloc[i])
            if col == "volume":
                tol = f"{vol_frac:g} of the larger volume"
            else:
                tol = f"{price_tol_ticks} tick(s) x {tick:g} = {price_tol:g}"
            raise MergeError(
                f"overlap mismatch on {col}: existing {x_val!r} "
                f"({a['source'].iloc[i]}) vs incoming {y_val!r} ({b['source'].iloc[i]}), "
                f"diff {abs(x_val - y_val):.10g} exceeds tolerance {tol}",
                a["open_at"].iloc[i],
                tf=tf,
                field=col,
            )
        with np.errstate(invalid="ignore", divide="ignore"):
            vfrac = np.where(vmax > 0, vd / np.where(vmax > 0, vmax, 1.0), 0.0)
        stats = OverlapStats(
            rows_compared=len(a),
            max_price_diff_ticks=float(max(diffs[c].max() for c in PRICE_FIELDS) / tick),
            max_volume_diff_fraction=float(vfrac.max()),
        )
        old_rank = a["source"].map(SOURCE_PRECEDENCE).to_numpy(dtype="int64")
        new_rank = b["source"].map(SOURCE_PRECEDENCE).to_numpy(dtype="int64")
        keep_new = new_rank > old_rank  # tie: the existing row stays

    keep_old = np.ones(len(old), dtype=bool)
    keep_old[np.flatnonzero(in_old)[keep_new]] = False
    keep_inc = ~in_new
    keep_inc[np.flatnonzero(in_new)[keep_new]] = True
    parts = [df for df in (old[keep_old], new[keep_inc]) if not df.empty]
    if not parts:
        return empty_frame(), stats
    merged = pd.concat(parts, ignore_index=True) if len(parts) > 1 else parts[0]
    merged = merged.sort_values("open_at", kind="stable")
    return normalize(merged), stats
