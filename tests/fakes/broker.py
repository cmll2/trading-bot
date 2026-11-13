"""Scriptable FakeBroker for tests (architecture §1, AD-24). Never touches the network.

Script the outcome of the next ``place_order`` calls with ``script_place`` and of the next
read calls with ``script_read``; script fills and exchange-side cancels with ``fill`` and
``exchange_cancel``. Scripted failures raise only the six taxonomy errors of
``bot.broker.errors``. ``place_order`` enforces the risk decision first (AD-10).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Literal

from bot.broker.base import (
    Balance,
    CancelAck,
    FeeRates,
    Fill,
    KeyPermissions,
    MarketRules,
    OrderAck,
    OrderRequest,
    OrderStatus,
    Ticker,
    require_approved,
)
from bot.broker.errors import (
    FatalBrokerError,
    OrderOutcomeUnknown,
    OrderRejected,
    PostOnlyWouldCross,
    RateLimited,
    TransientReadError,
)
from bot.clock import Clock
from bot.risk.checks import RiskDecision

PlaceScript = Literal["accept", "reject", "cross", "timeout_after_accept", "rate_limit", "fatal"]
ReadScript = Literal["ok", "transient", "rate_limit"]


@dataclass
class _Order:
    req: OrderRequest
    exchange_order_id: str
    accepted_at: datetime
    state: Literal["open", "closed", "canceled", "rejected"] = "open"
    filled_qty: Decimal = Decimal(0)
    notional: Decimal = Decimal(0)
    updated_at: datetime | None = None


@dataclass
class FakeBroker:
    clock: Clock
    rules: MarketRules
    fees: FeeRates
    balances: dict[str, Balance] = field(default_factory=dict)
    ticker: Ticker | None = None
    name: str = "fake"

    def __post_init__(self) -> None:
        self._place_script: deque[PlaceScript] = deque()
        self._read_script: deque[ReadScript] = deque()
        self._orders: dict[str, _Order] = {}
        self._fills: list[Fill] = []
        self._seq = 0
        # Every request that passed the risk gate and reached the "exchange", whatever the
        # outcome (accepted, rejected, crossed, rate limited...). ``placed`` = accepted only.
        self.submitted: list[OrderRequest] = []
        self.placed: list[OrderRequest] = []
        self.cancel_calls: list[str] = []

    # --- scripting ----------------------------------------------------------------------

    def script_place(self, *outcomes: PlaceScript) -> None:
        self._place_script.extend(outcomes)

    def script_read(self, *outcomes: ReadScript) -> None:
        self._read_script.extend(outcomes)

    def fill(
        self,
        cl_ord_id: str,
        qty: Decimal,
        price: Decimal | None = None,
        liquidity: Literal["maker", "taker"] = "maker",
    ) -> Fill:
        """Script a (partial) fill of an open order at ``price`` (default: its limit)."""
        order = self._orders[cl_ord_id]
        if qty <= 0:
            raise ValueError("fill quantity must be > 0")
        if order.state != "open":
            raise ValueError(f"order {cl_ord_id} is {order.state}, cannot fill")
        if order.filled_qty + qty > order.req.qty:
            raise ValueError("fill exceeds order quantity")
        px = order.req.limit_price if price is None else price
        rate = self.fees.maker if liquidity == "maker" else self.fees.taker
        self._seq += 1
        f = Fill(
            exchange_trade_id=f"T{self._seq}",
            exchange_order_id=order.exchange_order_id,
            cl_ord_id=cl_ord_id,
            pair=order.req.pair,
            side=order.req.side,
            qty=qty,
            price=px,
            fee=qty * px * rate,
            fee_ccy=self.rules.quote,
            liquidity=liquidity,
            ts=self.clock.now(),
        )
        self._fills.append(f)
        order.filled_qty += qty
        order.notional += qty * px
        order.updated_at = f.ts
        if order.filled_qty == order.req.qty:
            order.state = "closed"
        return f

    def inject_fill(self, fill: Fill) -> None:
        """Make ``get_fills`` return an arbitrary fill: a late fill of a cancelled order, or
        an unknown fill matching no order (AD-9, AD-27 engine tests). Order state untouched."""
        self._fills.append(fill)

    def exchange_cancel(self, cl_ord_id: str) -> None:
        """The exchange cancels an open order on its own (e.g. maintenance)."""
        order = self._orders[cl_ord_id]
        if order.state != "open":
            raise ValueError(f"order {cl_ord_id} is {order.state}, cannot cancel")
        order.state = "canceled"
        order.updated_at = self.clock.now()

    # --- port ---------------------------------------------------------------------------

    def _read(self) -> None:
        outcome = self._read_script.popleft() if self._read_script else "ok"
        if outcome == "transient":
            raise TransientReadError("scripted read failure")
        if outcome == "rate_limit":
            raise RateLimited(1.0)

    def load_market(self, pair: str) -> MarketRules:
        self._read()
        return self.rules

    def get_fee_rates(self, pair: str) -> FeeRates:
        self._read()
        return self.fees

    def get_balance(self) -> dict[str, Balance]:
        self._read()
        return dict(self.balances)

    def get_ticker(self, pair: str) -> Ticker:
        self._read()
        if self.ticker is None:
            raise TransientReadError("no ticker scripted")
        return self.ticker

    def place_order(self, req: OrderRequest, decision: RiskDecision) -> OrderAck:
        require_approved(req, decision)
        self.submitted.append(req)
        outcome = self._place_script.popleft() if self._place_script else "accept"
        if outcome == "reject":
            raise OrderRejected("EOrder:Insufficient funds")
        if outcome == "cross":
            raise PostOnlyWouldCross("EOrder:Post only order")
        if outcome == "rate_limit":
            raise RateLimited(2.0)
        if outcome == "fatal":
            raise FatalBrokerError("EAPI:Invalid key")
        if req.cl_ord_id in self._orders:
            raise OrderRejected(f"duplicate cl_ord_id {req.cl_ord_id}")
        self._seq += 1
        now = self.clock.now()
        order = _Order(req=req, exchange_order_id=f"O{self._seq}", accepted_at=now, updated_at=now)
        self._orders[req.cl_ord_id] = order
        self.placed.append(req)
        if outcome == "timeout_after_accept":
            raise OrderOutcomeUnknown("scripted timeout after the exchange accepted the order")
        return OrderAck(req.cl_ord_id, order.exchange_order_id, now)

    def cancel_order(self, pair: str, cl_ord_id: str) -> CancelAck:
        self.cancel_calls.append(cl_ord_id)
        order = self._orders.get(cl_ord_id)
        if order is None or order.req.pair != pair:
            raise OrderRejected(f"EOrder:Unknown order {cl_ord_id}")
        if order.state != "open":
            return CancelAck(cl_ord_id, already_closed=True)
        order.state = "canceled"
        order.updated_at = self.clock.now()
        return CancelAck(cl_ord_id, already_closed=False)

    def _status(self, o: _Order) -> OrderStatus:
        avg = o.notional / o.filled_qty if o.filled_qty else None
        return OrderStatus(
            cl_ord_id=o.req.cl_ord_id,
            exchange_order_id=o.exchange_order_id,
            state=o.state,
            qty=o.req.qty,
            filled_qty=o.filled_qty,
            avg_price=avg,
            updated_at=o.updated_at or o.accepted_at,
        )

    def get_open_orders(self, pair: str) -> list[OrderStatus]:
        self._read()
        return [
            self._status(o)
            for o in self._orders.values()
            if o.state == "open" and o.req.pair == pair
        ]

    def find_order(self, pair: str, cl_ord_id: str) -> OrderStatus | None:
        self._read()
        o = self._orders.get(cl_ord_id)
        return None if o is None or o.req.pair != pair else self._status(o)

    def get_fills(self, pair: str, since: datetime) -> list[Fill]:
        self._read()
        return [f for f in self._fills if f.pair == pair and f.ts >= since]

    def check_key_permissions(self) -> KeyPermissions:
        self._read()
        return KeyPermissions(applicable=False, permissions=frozenset(), ip_allowlist=())


def approve(req: OrderRequest) -> RiskDecision:
    """An approved decision matching ``req`` (test helper)."""
    return RiskDecision(approved=True, cl_ord_id=req.cl_ord_id)


__all__ = ["FakeBroker", "approve"]
