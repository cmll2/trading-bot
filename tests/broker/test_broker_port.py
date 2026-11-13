"""Broker port shape, the adapter-side risk gate (AD-10) and the scriptable FakeBroker."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from bot.broker import errors
from bot.broker.base import (
    Broker,
    FeeRates,
    Fill,
    MarketRules,
    OrderRequest,
    RiskGateViolation,
    Ticker,
    require_approved,
)
from bot.clock import FakeClock
from bot.risk.checks import RiskDecision
from tests.fakes.broker import FakeBroker, approve

T0 = datetime(2024, 1, 2, 0, 0, 30, tzinfo=UTC)
RULES = MarketRules(
    pair="BTC/EUR",
    base="BTC",
    quote="EUR",
    amount_min=Decimal("0.00006"),
    cost_min=Decimal("0.45"),
    tick_size=Decimal("0.1"),
    amount_step=Decimal("0.00000001"),
    status="online",
)
FEES = FeeRates(maker=Decimal("0.004"), taker=Decimal("0.008"), source="config")
TAXONOMY = (
    errors.OrderRejected,
    errors.PostOnlyWouldCross,
    errors.OrderOutcomeUnknown,
    errors.RateLimited,
    errors.TransientReadError,
    errors.FatalBrokerError,
)


def _broker() -> tuple[FakeBroker, FakeClock]:
    clock = FakeClock(T0)
    return FakeBroker(clock=clock, rules=RULES, fees=FEES), clock


def _req(cl: str = "c1", qty: str = "0.001") -> OrderRequest:
    return OrderRequest("BTC/EUR", "buy", Decimal(qty), Decimal("40000.0"), cl)


def test_port_exposes_exactly_the_architecture_methods() -> None:
    methods = {n for n, v in inspect.getmembers(Broker) if callable(v) and not n.startswith("_")}
    assert methods == {
        "load_market",
        "get_fee_rates",
        "get_balance",
        "get_ticker",
        "place_order",
        "cancel_order",
        "get_open_orders",
        "find_order",
        "get_fills",
        "check_key_permissions",
    }
    assert set(Broker.__annotations__) == {"name"}


def test_fake_broker_satisfies_the_protocol_signatures() -> None:
    for name in (n for n in dir(Broker) if not n.startswith("_")):
        expected = list(inspect.signature(getattr(Broker, name)).parameters)
        actual = list(inspect.signature(getattr(FakeBroker, name)).parameters)
        assert actual == expected, name


@pytest.mark.parametrize(
    "decision",
    [
        None,
        RiskDecision(approved=False, cl_ord_id="c1", rule="max_position", reason="too big"),
        RiskDecision(approved=True, cl_ord_id="other"),
    ],
    ids=["missing", "rejected", "mismatched"],
)
def test_place_order_refuses_without_an_approved_matching_decision(decision) -> None:
    broker, _ = _broker()
    with pytest.raises(RiskGateViolation):
        broker.place_order(_req(), decision)
    assert broker.placed == []
    assert broker.get_open_orders("BTC/EUR") == []


def test_require_approved_accepts_a_matching_approval() -> None:
    require_approved(_req(), RiskDecision(approved=True, cl_ord_id="c1"))


def test_risk_gate_violation_is_not_a_broker_error() -> None:
    # A bypass attempt is a caller bug; the engine must never treat it as an exchange reply.
    assert not issubclass(RiskGateViolation, errors.BrokerError)


def test_accept_and_partial_fill_then_full_fill() -> None:
    broker, clock = _broker()
    req = _req(qty="0.002")
    ack = broker.place_order(req, approve(req))
    assert ack.cl_ord_id == "c1"
    clock.advance(timedelta(minutes=15))
    broker.fill("c1", Decimal("0.0005"))
    status = broker.find_order("BTC/EUR", "c1")
    assert status is not None and status.state == "open"
    assert status.filled_qty == Decimal("0.0005")
    fills = broker.get_fills("BTC/EUR", T0)
    assert len(fills) == 1 and fills[0].fee == Decimal("0.0005") * Decimal("40000.0") * FEES.maker
    assert fills[0].fee_ccy == "EUR"
    broker.fill("c1", Decimal("0.0015"))
    status = broker.find_order("BTC/EUR", "c1")
    assert status is not None and status.state == "closed"
    assert status.avg_price == Decimal("40000.0")
    assert broker.get_open_orders("BTC/EUR") == []


def test_timeout_after_accept_leaves_an_order_that_find_order_sees() -> None:
    broker, _ = _broker()
    broker.script_place("timeout_after_accept")
    req = _req()
    with pytest.raises(errors.OrderOutcomeUnknown) as info:
        broker.place_order(req, approve(req))
    assert isinstance(info.value, TAXONOMY)
    status = broker.find_order("BTC/EUR", "c1")
    assert status is not None and status.state == "open"


@pytest.mark.parametrize(
    ("script", "exc"),
    [
        ("reject", errors.OrderRejected),
        ("cross", errors.PostOnlyWouldCross),
        ("rate_limit", errors.RateLimited),
        ("fatal", errors.FatalBrokerError),
    ],
)
def test_scripted_place_failures_leave_nothing_on_the_exchange(script, exc) -> None:
    broker, _ = _broker()
    broker.script_place(script)
    req = _req()
    with pytest.raises(exc) as info:
        broker.place_order(req, approve(req))
    assert isinstance(info.value, TAXONOMY)
    # PostOnlyWouldCross is an OrderRejected by design (architecture §1): the most
    # specific class is the scripted one.
    assert type(info.value) is exc
    assert broker.find_order("BTC/EUR", "c1") is None
    assert broker.submitted == [req] and broker.placed == []


@pytest.mark.parametrize(
    ("script", "exc"),
    [("transient", errors.TransientReadError), ("rate_limit", errors.RateLimited)],
)
def test_scripted_read_failures(script, exc) -> None:
    broker, _ = _broker()
    broker.ticker = Ticker("BTC/EUR", Decimal(1), Decimal(2), Decimal(1), T0)
    broker.script_read(script)
    with pytest.raises(exc) as info:
        broker.get_ticker("BTC/EUR")
    assert isinstance(info.value, TAXONOMY)
    assert broker.get_ticker("BTC/EUR").ask == Decimal(2)


def test_exchange_side_cancel_and_cancel_of_closed_order() -> None:
    broker, _ = _broker()
    req = _req()
    broker.place_order(req, approve(req))
    broker.exchange_cancel("c1")
    status = broker.find_order("BTC/EUR", "c1")
    assert status is not None and status.state == "canceled"
    assert broker.cancel_order("BTC/EUR", "c1").already_closed is True


def test_duplicate_cl_ord_id_is_rejected() -> None:
    broker, _ = _broker()
    req = _req()
    broker.place_order(req, approve(req))
    with pytest.raises(errors.OrderRejected):
        broker.place_order(req, approve(req))
    assert len(broker.placed) == 1


def test_cancel_with_the_wrong_pair_is_refused() -> None:
    broker, _ = _broker()
    req = _req()
    broker.place_order(req, approve(req))
    with pytest.raises(errors.OrderRejected):
        broker.cancel_order("ETH/EUR", "c1")


def test_exchange_cancel_of_a_filled_order_is_impossible() -> None:
    broker, _ = _broker()
    req = _req()
    broker.place_order(req, approve(req))
    broker.fill("c1", req.qty)
    with pytest.raises(ValueError):
        broker.exchange_cancel("c1")


def test_non_positive_fill_is_refused() -> None:
    broker, _ = _broker()
    req = _req()
    broker.place_order(req, approve(req))
    with pytest.raises(ValueError):
        broker.fill("c1", Decimal(0))


def test_late_and_unknown_fills_can_be_injected() -> None:
    broker, _ = _broker()
    req = _req()
    broker.place_order(req, approve(req))
    broker.cancel_order("BTC/EUR", "c1")
    assert broker.get_fills("BTC/EUR", T0) == []
    unknown = Fill(
        "X1",
        "O99",
        None,
        "BTC/EUR",
        "buy",
        Decimal("0.001"),
        Decimal(1),
        Decimal(0),
        "EUR",
        "maker",
        T0,
    )
    broker.inject_fill(unknown)
    assert broker.get_fills("BTC/EUR", T0) == [unknown]
