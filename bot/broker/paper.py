"""PaperBroker: simulated exchange for backtest (M2) and dry-run (M3) (FR-24, AD-6, AD-26).

Fills go through ``fill_model`` only, against CLOSED execution candles served by the
``MarketData`` port (the Parquet cache in backtest, live candles in dry-run). The virtual
account lives in the ``paper_*`` tables of the store injected by the engine (AD-17: this
module is their only writer), so a dry-run survives restarts.

Exchange-side checks mirror Kraken's: the order must carry an approved matching
``RiskDecision`` (AD-10), the market must be online, quantity and cost must meet the
minimums and both must be exact multiples of the amount step and price tick (never
rounded: an order that is not is rejected), a post-only order that would cross is
refused with ``PostOnlyWouldCross``, and funds must cover the order (fee included).

Ticker (AD-6): bid/ask = close of the last closed, non-synthetic execution candle
-/+ ``half_spread_bps``, rounded outward to the tick; its timestamp is that candle's close,
so during an exchange halt (synthetic candles, audit M1 F-2) the ticker goes stale and the
risk checks refuse to trade. Using the last closed close rather than the open of the
still-forming candle keeps the backtest strictly causal (decision 2026-11-13).

Dry-run (M3): ``ticker_source`` replaces that modelled ticker with the LIVE public bid/ask
(``bot.data.live.LiveFeed.ticker``), and ``rules_source`` re-reads the public market
metadata whenever the engine calls ``load_market`` (AD-13). Fills, fees, minimums,
slippage and the post-only check run through exactly the same code as in the backtest.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal
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
from bot.broker.errors import OrderRejected, PostOnlyWouldCross, TransientReadError
from bot.broker.fill_model import (
    BPS,
    SimCandle,
    SimOrder,
    ceil_to_boundary,
    simulate_maker,
    simulate_taker,
    slipped,
)
from bot.clock import Clock
from bot.config import TIMEFRAME_SECONDS
from bot.data.market import MarketData
from bot.risk.checks import RiskDecision
from bot.store import Store, dec, iso, parse_iso

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_TICKER_LOOKBACK = 400  # execution candles searched for the last non-synthetic close


def round_to_step(x: Decimal, step: Decimal, direction: Literal["down", "up"]) -> Decimal:
    rounding = ROUND_FLOOR if direction == "down" else ROUND_CEILING
    return (x / step).to_integral_value(rounding=rounding) * step


def _d(x: float) -> Decimal:
    return Decimal(repr(float(x)))


class PaperBroker:
    """Broker port over a simulated account. ``liquidity="taker"`` is the CON-06 report
    variant (immediate fill at the order's aggressive limit, taker fee)."""

    name = "paper"

    def __init__(
        self,
        store: Store,
        market_data: MarketData,
        clock: Clock,
        rules: MarketRules,
        fees: FeeRates,
        slippage_bps: Decimal,
        half_spread_bps: Decimal,
        initial_quote: Decimal,
        exec_timeframe: str = "15m",
        liquidity: Literal["maker", "taker"] = "maker",
        ticker_source: Callable[[str], Ticker] | None = None,
        rules_source: Callable[[str], MarketRules] | None = None,
    ) -> None:
        self._store = store
        self._md = market_data
        self._clock = clock
        self._rules = rules
        self._fees = fees
        self._slip = Decimal(slippage_bps)
        self._half_spread = Decimal(half_spread_bps)
        self._tf = exec_timeframe
        self._interval = timedelta(seconds=TIMEFRAME_SECONDS[exec_timeframe])
        self._liquidity = liquidity
        self._ticker_source = ticker_source
        self._rules_source = rules_source
        if store.one("SELECT 1 FROM paper_balances") is None:
            with store.transaction():
                store.insert(
                    "paper_balances", asset=rules.quote, free=dec(initial_quote), locked="0"
                )
                store.insert("paper_balances", asset=rules.base, free="0", locked="0")

    # --- helpers ------------------------------------------------------------------------

    def _bal(self, asset: str) -> tuple[Decimal, Decimal]:
        row = self._store.one("SELECT free, locked FROM paper_balances WHERE asset = ?", (asset,))
        if row is None:
            return Decimal(0), Decimal(0)
        return Decimal(row["free"]), Decimal(row["locked"])

    def _set_bal(self, asset: str, free: Decimal, locked: Decimal) -> None:
        if free < 0 or locked < 0:
            raise RuntimeError(f"paper balance for {asset} would go negative ({free}, {locked})")
        self._store.update("paper_balances", "asset", asset, free=dec(free), locked=dec(locked))

    def _fee_rate(self) -> Decimal:
        return self._fees.maker if self._liquidity == "maker" else self._fees.taker

    def _reserve(self, side: str, qty: Decimal, limit: Decimal) -> Decimal:
        """Funds locked by an order: quote (fee and slippage included) for a buy, base for a
        sell."""
        if side == "sell":
            return qty
        return qty * slipped("buy", limit, self._slip) * (1 + self._fee_rate())

    def _next_id(self, prefix: str, table: str) -> str:
        n = self._store.one(f"SELECT count(*) FROM {table}")[0]  # noqa: S608
        return f"{prefix}{n + 1}"

    # --- port: reads --------------------------------------------------------------------

    def load_market(self, pair: str) -> MarketRules:
        if self._rules_source is not None:
            self._rules = self._rules_source(pair)
        return self._rules

    def get_fee_rates(self, pair: str) -> FeeRates:
        return self._fees

    def get_balance(self) -> dict[str, Balance]:
        self._evaluate()
        rows = self._store.all("SELECT asset, free, locked FROM paper_balances")
        return {
            r["asset"]: Balance(r["asset"], Decimal(r["free"]), Decimal(r["locked"])) for r in rows
        }

    def get_ticker(self, pair: str) -> Ticker:
        if self._ticker_source is not None:
            return self._ticker_source(pair)
        hist = self._md.closed_candles(pair, self._tf, limit=_TICKER_LOOKBACK)
        real = [i for i in range(len(hist)) if not bool(hist.synthetic[i])]
        if not real:
            raise TransientReadError("no non-synthetic execution candle to price from")
        i = real[-1]
        close = _d(hist.close[i])
        tick = self._rules.tick_size
        bid = round_to_step(close * (1 - self._half_spread * BPS), tick, "down")
        ask = round_to_step(close * (1 + self._half_spread * BPS), tick, "up")
        if ask <= bid:
            ask = bid + tick
        ts = _EPOCH + timedelta(milliseconds=int(hist.open_at[i])) + self._interval
        return Ticker(pair=pair, bid=bid, ask=ask, last=close, ts=ts)

    def get_open_orders(self, pair: str) -> list[OrderStatus]:
        self._evaluate()
        rows = self._store.all(
            "SELECT * FROM paper_orders WHERE pair = ? AND state = 'open'", (pair,)
        )
        return [self._status(r) for r in rows]

    def find_order(self, pair: str, cl_ord_id: str) -> OrderStatus | None:
        self._evaluate()
        row = self._store.one(
            "SELECT * FROM paper_orders WHERE pair = ? AND cl_ord_id = ?", (pair, cl_ord_id)
        )
        return None if row is None else self._status(row)

    def get_fills(self, pair: str, since: datetime) -> list[Fill]:
        self._evaluate()
        rows = self._store.all(
            "SELECT f.*, o.cl_ord_id, o.side, o.pair FROM paper_fills f "
            "JOIN paper_orders o USING (exchange_order_id) "
            "WHERE o.pair = ? AND f.at >= ? ORDER BY f.at, f.exchange_trade_id",
            (pair, iso(since)),
        )
        return [
            Fill(
                exchange_trade_id=r["exchange_trade_id"],
                exchange_order_id=r["exchange_order_id"],
                cl_ord_id=r["cl_ord_id"],
                pair=r["pair"],
                side=r["side"],
                qty=Decimal(r["qty"]),
                price=Decimal(r["price"]),
                fee=Decimal(r["fee"]),
                fee_ccy=r["fee_ccy"],
                liquidity=self._liquidity,
                ts=parse_iso(r["at"]),
            )
            for r in rows
        ]

    def check_key_permissions(self) -> KeyPermissions:
        return KeyPermissions(applicable=False, permissions=frozenset(), ip_allowlist=())

    def _status(self, r) -> OrderStatus:  # noqa: ANN001 - sqlite3.Row
        filled = Decimal(r["filled_qty"])
        avg = None
        if filled:
            fills = self._store.all(
                "SELECT qty, price FROM paper_fills WHERE exchange_order_id = ?",
                (r["exchange_order_id"],),
            )
            avg = sum(Decimal(f["qty"]) * Decimal(f["price"]) for f in fills) / filled
        return OrderStatus(
            cl_ord_id=r["cl_ord_id"],
            exchange_order_id=r["exchange_order_id"],
            state=r["state"],
            qty=Decimal(r["qty"]),
            filled_qty=filled,
            avg_price=avg,
            updated_at=parse_iso(r["closed_at"] or r["accepted_at"]),
        )

    # --- port: writes -------------------------------------------------------------------

    def place_order(self, req: OrderRequest, decision: RiskDecision) -> OrderAck:
        require_approved(req, decision)
        r = self._rules
        if req.pair != r.pair:
            raise OrderRejected(f"EQuery:Unknown asset pair {req.pair}")
        if r.status != "online":
            raise OrderRejected(f"EOrder:Market in {r.status} mode")
        if req.qty < r.amount_min:
            raise OrderRejected("EOrder:Order minimum not met")
        if req.qty * req.limit_price < r.cost_min:
            raise OrderRejected("EOrder:Cost minimum not met")
        if req.limit_price % r.tick_size != 0:
            raise OrderRejected("EOrder:Tick size check failed")
        if req.qty % r.amount_step != 0:
            raise OrderRejected("EGeneral:Invalid arguments:volume precision")
        if self._liquidity == "maker":
            ticker = self.get_ticker(req.pair)
            crosses = (
                req.limit_price >= ticker.ask
                if req.side == "buy"
                else req.limit_price <= ticker.bid
            )
            if crosses:
                raise PostOnlyWouldCross("EOrder:Post only order would cross")
        asset = r.quote if req.side == "buy" else r.base
        need = self._reserve(req.side, req.qty, req.limit_price)
        now = self._clock.now()
        with self._store.transaction():
            if self._store.one("SELECT 1 FROM paper_orders WHERE cl_ord_id = ?", (req.cl_ord_id,)):
                raise OrderRejected(f"EOrder:Duplicate client order id {req.cl_ord_id}")
            free, locked = self._bal(asset)
            if free < need:
                raise OrderRejected("EOrder:Insufficient funds")
            self._set_bal(asset, free - need, locked + need)
            oid = self._next_id("P", "paper_orders")
            self._store.insert(
                "paper_orders",
                exchange_order_id=oid,
                cl_ord_id=req.cl_ord_id,
                pair=req.pair,
                side=req.side,
                qty=dec(req.qty),
                limit_price=dec(req.limit_price),
                filled_qty="0",
                state="open",
                accepted_at=iso(now),
            )
            if self._liquidity == "taker":
                order = SimOrder(req.side, req.qty, req.limit_price, now)
                self._apply(oid, order, simulate_taker(order, self._fees.taker, self._slip))
        return OrderAck(req.cl_ord_id, oid, now)

    def cancel_order(self, pair: str, cl_ord_id: str) -> CancelAck:
        self._evaluate()  # fills that happened before the cancel arrives count
        with self._store.transaction():
            row = self._store.one(
                "SELECT * FROM paper_orders WHERE pair = ? AND cl_ord_id = ?", (pair, cl_ord_id)
            )
            if row is None:
                raise OrderRejected(f"EOrder:Unknown order {cl_ord_id}")
            if row["state"] != "open":
                return CancelAck(cl_ord_id, already_closed=True)
            self._release(row)
            self._store.update(
                "paper_orders",
                "exchange_order_id",
                row["exchange_order_id"],
                state="canceled",
                closed_at=iso(self._clock.now()),
            )
        return CancelAck(cl_ord_id, already_closed=False)

    def _release(self, row) -> None:  # noqa: ANN001 - sqlite3.Row
        """Unlock what an open order still holds (its unfilled part)."""
        rest = Decimal(row["qty"]) - Decimal(row["filled_qty"])
        if rest <= 0:
            return
        asset = self._rules.quote if row["side"] == "buy" else self._rules.base
        held = self._reserve(row["side"], rest, Decimal(row["limit_price"]))
        free, locked = self._bal(asset)
        self._set_bal(asset, free + held, locked - held)

    # --- fill evaluation ----------------------------------------------------------------

    def _evaluate(self) -> None:
        """Fill open orders against the closed execution candles available now."""
        if self._liquidity == "taker":
            return
        rows = self._store.all("SELECT * FROM paper_orders WHERE state = 'open'")
        if not rows:
            return
        now = self._clock.now()
        for row in rows:
            accepted = parse_iso(row["accepted_at"])
            first = ceil_to_boundary(accepted, self._interval)
            if first + self._interval > now:
                continue  # no eligible candle has closed yet
            n = math.ceil((now - first) / self._interval) + 2
            hist = self._md.closed_candles(row["pair"], self._tf, limit=n)
            order = SimOrder(
                row["side"], Decimal(row["qty"]), Decimal(row["limit_price"]), accepted
            )
            for i in range(len(hist)):
                candle = SimCandle(
                    open_at=_EPOCH + timedelta(milliseconds=int(hist.open_at[i])),
                    interval=self._interval,
                    open=_d(hist.open[i]),
                    high=_d(hist.high[i]),
                    low=_d(hist.low[i]),
                    close=_d(hist.close[i]),
                    synthetic=bool(hist.synthetic[i]),
                )
                fill = simulate_maker(order, candle, self._fees.maker, self._slip)
                if fill is not None:
                    with self._store.transaction():
                        self._apply(row["exchange_order_id"], order, fill)
                    break

    def _apply(self, oid: str, order: SimOrder, fill) -> None:  # noqa: ANN001 - SimFill
        r = self._rules
        quote_free, quote_locked = self._bal(r.quote)
        base_free, base_locked = self._bal(r.base)
        gross = fill.qty * fill.price
        if order.side == "buy":
            held = self._reserve("buy", fill.qty, order.limit_price)
            self._set_bal(r.quote, quote_free + held - gross - fill.fee, quote_locked - held)
            self._set_bal(r.base, base_free + fill.qty, base_locked)
        else:
            self._set_bal(r.base, base_free, base_locked - fill.qty)
            self._set_bal(r.quote, quote_free + gross - fill.fee, quote_locked)
        self._store.insert(
            "paper_fills",
            exchange_trade_id=self._next_id("PT", "paper_fills"),
            exchange_order_id=oid,
            at=iso(fill.at),
            qty=dec(fill.qty),
            price=dec(fill.price),
            fee=dec(fill.fee),
            fee_ccy=r.quote,
        )
        row = self._store.one(
            "SELECT qty, filled_qty FROM paper_orders WHERE exchange_order_id = ?", (oid,)
        )
        filled = Decimal(row["filled_qty"]) + fill.qty
        state = "closed" if filled >= Decimal(row["qty"]) else "open"
        self._store.update(
            "paper_orders",
            "exchange_order_id",
            oid,
            filled_qty=dec(filled),
            state=state,
            closed_at=iso(fill.at) if state == "closed" else None,
        )
