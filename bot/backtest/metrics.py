"""Backtest metrics (FR-14, FR-21, CON-06). Pure functions over daily equity points.

Evaluation window: the day-open equity points from ``eval_start`` (the first close at
which the strategy had its full warm-up) to the last point. Daily returns are simple
returns between consecutive points.

- total return = E_end / E_start - 1; annualized = (1 + total)^(365 / days) - 1
- max drawdown = max_t (1 - E_t / max_{s<=t} E_s)
- Sharpe = mean(daily returns) / std(daily returns, ddof=1) x sqrt(365), risk-free 0
  (crypto trades every day); 0 when the std is 0
- Sharpe CI: moving-block bootstrap (circular blocks of ``block`` days, ``resamples``
  draws, seeded), 2.5% / 97.5% percentiles
- trades = fills; round trips = completed buy-then-sell pairs
- turnover = sum of |fill notional| / mean equity
- time in market = share of daily points holding a non-zero base position
- buy-and-hold benchmark: all equity bought at the first point's mark with slippage and
  the variant's fee, then held and marked at mid (no exit cost, like the strategy)
- cash benchmark: equity constant, 0 return
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime
from decimal import Decimal

import numpy as np

from bot.backtest.runner import RunResult
from bot.store import parse_iso

BPS = Decimal("0.0001")


@dataclass(frozen=True)
class Metrics:
    start: str
    end: str
    days: int
    initial_equity: float
    final_equity: float
    total_return: float
    annualized_return: float
    max_drawdown: float
    sharpe: float
    sharpe_ci_95: tuple[float, float]
    trades: int
    round_trips: int
    turnover: float
    total_fees: float
    time_in_market: float

    def as_dict(self) -> dict[str, object]:
        d = asdict(self)
        d["sharpe_ci_95"] = [round(v, 10) for v in self.sharpe_ci_95]
        return {k: (round(v, 10) if isinstance(v, float) else v) for k, v in d.items()}


def daily_returns(equity: np.ndarray) -> np.ndarray:
    return equity[1:] / equity[:-1] - 1


def sharpe(returns: np.ndarray) -> float:
    if len(returns) < 2:
        return 0.0
    sd = float(np.std(returns, ddof=1))
    if sd == 0 or not math.isfinite(sd):
        return 0.0
    return float(np.mean(returns)) / sd * math.sqrt(365)


def max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    return float(np.max(1 - equity / peak)) if len(equity) else 0.0


def annualized(total: float, days: int) -> float:
    if days <= 0 or total <= -1:
        return -1.0 if total <= -1 else 0.0
    try:
        return (1 + total) ** (365 / days) - 1
    except OverflowError:
        return math.inf


def bootstrap_sharpe_ci(
    returns: np.ndarray, resamples: int, block: int, seed: int
) -> tuple[float, float]:
    """Moving-block (circular) bootstrap 95% CI of the annualized Sharpe ratio."""
    n = len(returns)
    if n < 2:
        return (0.0, 0.0)
    block = max(1, min(block, n))
    rng = np.random.default_rng(seed)
    n_blocks = math.ceil(n / block)
    offsets = np.arange(block)
    stats = np.empty(resamples)
    for i in range(resamples):
        starts = rng.integers(0, n, n_blocks)
        idx = ((starts[:, None] + offsets[None, :]) % n).ravel()[:n]
        stats[i] = sharpe(returns[idx])
    lo, hi = np.percentile(stats, [2.5, 97.5])
    return (float(lo), float(hi))


def _summary(
    dates: list[datetime],
    equity: np.ndarray,
    *,
    trades: int,
    round_trips: int,
    notional: float,
    fees: float,
    in_market: np.ndarray,
    resamples: int,
    block: int,
    seed: int,
) -> Metrics:
    days = (dates[-1] - dates[0]).days
    total = float(equity[-1] / equity[0] - 1)
    rets = daily_returns(equity)
    return Metrics(
        start=dates[0].isoformat(),
        end=dates[-1].isoformat(),
        days=days,
        initial_equity=float(equity[0]),
        final_equity=float(equity[-1]),
        total_return=total,
        annualized_return=annualized(total, days),
        max_drawdown=max_drawdown(equity),
        sharpe=sharpe(rets),
        sharpe_ci_95=bootstrap_sharpe_ci(rets, resamples, block, seed),
        trades=trades,
        round_trips=round_trips,
        turnover=notional / float(np.mean(equity)),
        total_fees=fees,
        time_in_market=float(np.mean(in_market)),
    )


def window(run: RunResult) -> list[tuple[datetime, Decimal, Decimal, Decimal]]:
    pts = [p for p in run.equity if p[0] >= run.eval_start]
    if len(pts) < 2:
        raise ValueError("fewer than two daily points after the warm-up")
    return pts


def strategy_metrics(run: RunResult, resamples: int, block: int, seed: int) -> Metrics:
    pts = window(run)
    t0, t1 = pts[0][0], pts[-1][0]
    # Only fills inside the window whose effect the equity points include.
    fills = [f for f in run.fills if t0 <= parse_iso(str(f["at"])) <= t1]
    amount_min = Decimal(str(run.rules_snapshot.get("amount_min", "0")))
    sides = [f["side"] for f in fills]
    round_trips = sum(
        1 for a, b in zip(sides, sides[1:], strict=False) if (a, b) == ("buy", "sell")
    )
    return _summary(
        [p[0] for p in pts],
        np.array([float(p[1]) for p in pts]),
        trades=len(fills),
        round_trips=round_trips,
        notional=sum(float(Decimal(f["qty"]) * Decimal(f["price"])) for f in fills),
        fees=sum(float(Decimal(f["fee"])) for f in fills),
        # Dust below the exchange minimum is not a position (AD-13).
        in_market=np.array([p[3] > 0 and p[3] >= amount_min for p in pts]),
        resamples=resamples,
        block=block,
        seed=seed,
    )


def buy_and_hold_metrics(
    run: RunResult,
    fee: Decimal,
    slippage_bps: Decimal,
    resamples: int,
    block: int,
    seed: int,
    half_spread_bps: Decimal = Decimal(0),
) -> Metrics:
    """All of the first point's equity buys at that point's mark x (1 + half spread) x
    (1 + slippage), paying ``fee`` (the taker variant passes the half spread, as its
    strategy pays it); the position is then marked at each later point's mark."""
    pts = window(run)
    e0, m0 = pts[0][1], pts[0][2]
    price = m0 * (1 + half_spread_bps * BPS) * (1 + slippage_bps * BPS)
    qty = e0 / (price * (1 + fee))
    fee_paid = qty * price * fee
    equity = np.array([float(e0)] + [float(qty * p[2]) for p in pts[1:]])
    return _summary(
        [p[0] for p in pts],
        equity,
        trades=1,
        round_trips=0,
        notional=float(qty * price),
        fees=float(fee_paid),
        in_market=np.ones(len(pts), dtype=bool),
        resamples=resamples,
        block=block,
        seed=seed,
    )


def cash_metrics(run: RunResult) -> Metrics:
    pts = window(run)
    e0 = float(pts[0][1])
    return _summary(
        [p[0] for p in pts],
        np.full(len(pts), e0),
        trades=0,
        round_trips=0,
        notional=0.0,
        fees=0.0,
        in_market=np.zeros(len(pts), dtype=bool),
        resamples=10,
        block=1,
        seed=0,
    )
