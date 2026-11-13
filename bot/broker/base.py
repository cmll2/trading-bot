"""Broker port (FR-23, architecture §1).

Money and quantities are ``Decimal``; datetimes are timezone-aware UTC. ``place_order``
takes the ``RiskDecision`` and every adapter must refuse unless ``decision.approved`` and
``decision.cl_ord_id == req.cl_ord_id`` (AD-10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal, Protocol

from bot.risk.checks import RiskDecision


@dataclass(frozen=True)
class MarketRules:
    """Read from exchange metadata at startup and per intent; never hardcoded (CON-03)."""

    pair: str
    base: str
    quote: str
    amount_min: Decimal
    cost_min: Decimal
    tick_size: Decimal
    amount_step: Decimal
    status: str  # "online", "post_only", "cancel_only", ...


@dataclass(frozen=True)
class FeeRates:
    maker: Decimal
    taker: Decimal
    source: Literal["fetch_trading_fee", "config"]


@dataclass(frozen=True)
class Balance:
    asset: str
    free: Decimal
    locked: Decimal


@dataclass(frozen=True)
class Ticker:
    pair: str
    bid: Decimal
    ask: Decimal
    last: Decimal
    ts: datetime


@dataclass(frozen=True)
class OrderRequest:
    """Always limit + post-only + fee in quote currency (AD-5)."""

    pair: str
    side: Literal["buy", "sell"]
    qty: Decimal
    limit_price: Decimal
    cl_ord_id: str


@dataclass(frozen=True)
class OrderAck:
    cl_ord_id: str
    exchange_order_id: str
    accepted_at: datetime


@dataclass(frozen=True)
class CancelAck:
    cl_ord_id: str
    already_closed: bool


@dataclass(frozen=True)
class OrderStatus:
    cl_ord_id: str
    exchange_order_id: str
    state: Literal["open", "closed", "canceled", "rejected"]
    qty: Decimal
    filled_qty: Decimal
    avg_price: Decimal | None
    updated_at: datetime


@dataclass(frozen=True)
class Fill:
    exchange_trade_id: str
    exchange_order_id: str
    cl_ord_id: str | None
    pair: str
    side: str
    qty: Decimal
    price: Decimal
    fee: Decimal
    fee_ccy: str
    liquidity: Literal["maker", "taker"]
    ts: datetime


@dataclass(frozen=True)
class KeyPermissions:
    applicable: bool
    permissions: frozenset[str]
    ip_allowlist: tuple[str, ...]


class RiskGateViolation(Exception):
    """``place_order`` was called without an approved, matching ``RiskDecision`` (AD-10).

    Not part of the broker error taxonomy on purpose: it is a programming error in the
    caller, never an exchange outcome, and nothing has been sent when it is raised.
    """


def require_approved(req: OrderRequest, decision: RiskDecision | None) -> None:
    """The first call of every adapter's ``place_order`` (AD-10).

    Raises ``RiskGateViolation`` unless ``decision`` is a ``RiskDecision`` that is approved
    and carries the request's ``cl_ord_id``.
    """
    if not isinstance(decision, RiskDecision):
        raise RiskGateViolation(f"order {req.cl_ord_id}: no RiskDecision supplied")
    if not decision.approved:
        raise RiskGateViolation(
            f"order {req.cl_ord_id}: risk decision is a rejection ({decision.rule})"
        )
    if decision.cl_ord_id != req.cl_ord_id:
        raise RiskGateViolation(f"order {req.cl_ord_id}: risk decision is for {decision.cl_ord_id}")


class Broker(Protocol):
    """Implemented by KrakenBroker (M6), PaperBroker (M2) and FakeBroker (tests)."""

    name: str  # "kraken" | "paper" | "fake"

    def load_market(self, pair: str) -> MarketRules: ...
    def get_fee_rates(self, pair: str) -> FeeRates: ...
    def get_balance(self) -> dict[str, Balance]: ...
    def get_ticker(self, pair: str) -> Ticker: ...
    def place_order(self, req: OrderRequest, decision: RiskDecision) -> OrderAck: ...
    def cancel_order(self, pair: str, cl_ord_id: str) -> CancelAck: ...
    def get_open_orders(self, pair: str) -> list[OrderStatus]: ...
    def find_order(self, pair: str, cl_ord_id: str) -> OrderStatus | None: ...  # open AND closed
    def get_fills(self, pair: str, since: datetime) -> list[Fill]: ...
    def check_key_permissions(self) -> KeyPermissions: ...
