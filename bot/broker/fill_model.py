"""Pure fill model shared by the backtest and the paper broker (FR-24, AD-6, CON-04).

One code path decides whether and at what price a simulated order fills, so backtest and
dry-run cannot drift apart (GL-02).

Maker (post-only limit, the v1 execution style):

- Eligible candles: CLOSED execution candles whose ``open_at`` is at or after the order's
  ``accepted_at`` rounded UP to the candle boundary. A candle that began before the order
  existed can never fill it.
- Synthetic candles (no-trade periods, which include Kraken trading halts, audit M1 F-2)
  are never fillable.
- A buy at limit L fills in full at L when the candle's ``low < L`` (strict
  trade-through); a sell fills when ``high > L``.
- The maker fee applies; ``slippage_bps`` moves the fill price against the trader.

Taker (the report's CON-06 variant only; v1 code places no market orders): the order fills
in full immediately at its own limit, which the engine sets at the aggressive side of the
book (ask for a buy, bid for a sell), with the taker fee and the same slippage.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

BPS = Decimal("0.0001")
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True)
class SimCandle:
    open_at: datetime
    interval: timedelta
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    synthetic: bool


@dataclass(frozen=True)
class SimOrder:
    side: Literal["buy", "sell"]
    qty: Decimal
    limit_price: Decimal
    accepted_at: datetime


@dataclass(frozen=True)
class SimFill:
    qty: Decimal
    price: Decimal  # after slippage
    fee: Decimal  # in quote currency
    liquidity: Literal["maker", "taker"]
    at: datetime


def ceil_to_boundary(t: datetime, interval: timedelta) -> datetime:
    """``t`` rounded up to the next multiple of ``interval`` since the epoch (UTC)."""
    step = int(interval.total_seconds() * 1_000_000)
    us = (t - _EPOCH) // timedelta(microseconds=1)
    return _EPOCH + timedelta(microseconds=-(-us // step) * step)


def slipped(side: str, price: Decimal, slippage_bps: Decimal) -> Decimal:
    """Price moved against the trader by ``slippage_bps``."""
    s = slippage_bps * BPS
    return price * (1 + s) if side == "buy" else price * (1 - s)


def eligible(order: SimOrder, candle: SimCandle) -> bool:
    return candle.open_at >= ceil_to_boundary(order.accepted_at, candle.interval)


def simulate_maker(
    order: SimOrder, candle: SimCandle, maker_fee: Decimal, slippage_bps: Decimal
) -> SimFill | None:
    """The fill of a resting post-only limit order on one closed candle, or None."""
    if candle.synthetic or not eligible(order, candle):
        return None
    through = (
        candle.low < order.limit_price if order.side == "buy" else (candle.high > order.limit_price)
    )
    if not through:
        return None
    price = slipped(order.side, order.limit_price, slippage_bps)
    return SimFill(
        qty=order.qty,
        price=price,
        fee=order.qty * price * maker_fee,
        liquidity="maker",
        at=candle.open_at + candle.interval,
    )


def simulate_taker(order: SimOrder, taker_fee: Decimal, slippage_bps: Decimal) -> SimFill:
    """CON-06 report variant: immediate full fill at the order's (aggressive) limit."""
    price = slipped(order.side, order.limit_price, slippage_bps)
    return SimFill(
        qty=order.qty,
        price=price,
        fee=order.qty * price * taker_fee,
        liquidity="taker",
        at=order.accepted_at,
    )
