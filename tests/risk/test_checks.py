"""Every pre-trade rule of AD-11, triggered and passed (FR-30..FR-36, GL-03). PROTECTED.

Limits come from the real config.yaml ``risk:`` section, so these tests exercise the
values the operator adopted (PROGRESS.md decisions log).
"""

from __future__ import annotations

import ast
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from bot.risk.checks import ProposedOrder, RiskContext, RiskDecision, check_order
from bot.risk.limits import RiskLimits

REPO_ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2024, 1, 2, 0, 0, 30, tzinfo=UTC)


def _limits() -> RiskLimits:
    with (REPO_ROOT / "config.yaml").open("r", encoding="utf-8") as fh:
        return RiskLimits.model_validate(yaml.safe_load(fh)["risk"])


LIMITS = _limits()

OK_ORDER = ProposedOrder(
    intent_id=1,
    attempt_no=1,
    is_flatten=False,
    side="buy",
    qty=Decimal("0.0004"),
    limit_price=Decimal("40000"),
    cl_ord_id="c1",
)
OK_CTX = RiskContext(
    now=NOW,
    equity=Decimal("20"),
    position_qty=Decimal(0),
    resting_buy_qty=Decimal(0),
    intents_today=0,
    submissions_today=0,
    intent_submissions=0,
    last_candle_open_at=datetime(2024, 1, 1, tzinfo=UTC),
    candle_interval=timedelta(days=1),
    last_candle_synthetic=False,
    ticker_ts=NOW - timedelta(seconds=30),
    mid=Decimal("40000"),
    reference_price=Decimal("40000"),
    active_halts=(),
    kill_switch_engaged=False,
    market_status="online",
    amount_min=Decimal("0.00006"),
    cost_min=Decimal("0.45"),
)
SELL = replace(OK_ORDER, side="sell")
FLATTEN = replace(OK_ORDER, side="sell", is_flatten=True)


def _check(order: ProposedOrder = OK_ORDER, **ctx: object) -> RiskDecision:
    return check_order(order, replace(OK_CTX, **ctx), LIMITS)


def _rejects(rule: str, decision: RiskDecision) -> None:
    assert decision.approved is False
    assert decision.rule == rule
    assert decision.reason  # FR-37: every rejection carries a stored reason
    assert decision.cl_ord_id == OK_ORDER.cl_ord_id


def test_baseline_order_is_approved() -> None:
    d = _check()
    assert d == RiskDecision(approved=True, cl_ord_id="c1")


# --- max_position (FR-31): 100% of equity AND EUR 25 --------------------------------------


def test_max_position_fraction_of_equity_triggers() -> None:
    # 0.0006 x 40000 = 24 > 100% of equity 20
    _rejects("max_position", _check(replace(OK_ORDER, qty=Decimal("0.0006"))))


def test_max_position_counts_position_and_resting_buys() -> None:
    _rejects(
        "max_position",
        _check(position_qty=Decimal("0.0003"), resting_buy_qty=Decimal("0.0001")),
    )  # (0.0003 + 0.0001 + 0.0004) x 40000 = 32 > 20


def test_max_position_absolute_cap_triggers_when_equity_is_larger() -> None:
    order = replace(OK_ORDER, qty=Decimal("0.00064"))  # 25.6 EUR
    _rejects("max_position", _check(order, equity=Decimal("100")))
    assert _check(replace(OK_ORDER, qty=Decimal("0.000625")), equity=Decimal("100")).approved


def test_max_position_at_exactly_the_cap_passes() -> None:
    assert _check(replace(OK_ORDER, qty=Decimal("0.0005"))).approved  # exactly 20


def test_a_sell_is_never_rejected_by_max_position() -> None:
    assert _check(replace(SELL, qty=Decimal("0.01")), position_qty=Decimal("0.01")).approved


# --- orders per day (FR-32) and submission caps ------------------------------------------


def test_max_orders_per_day_triggers_on_a_new_intent() -> None:
    _rejects("max_orders_per_day", _check(intents_today=LIMITS.max_order_intents_per_day))
    assert _check(intents_today=LIMITS.max_order_intents_per_day - 1).approved


def test_max_orders_per_day_ignores_re_prices_of_an_existing_intent() -> None:
    reprice = replace(OK_ORDER, attempt_no=2)
    assert check_order(
        reprice,
        replace(OK_CTX, intents_today=LIMITS.max_order_intents_per_day, intent_submissions=1),
        LIMITS,
    ).approved


def test_flatten_is_exempt_from_the_intent_count() -> None:
    d = _check(FLATTEN, intents_today=99, position_qty=Decimal("0.0004"))
    assert d.approved


def test_daily_submission_cap_triggers_including_for_flatten() -> None:
    cap = LIMITS.max_exchange_submissions_per_day
    _rejects("max_submissions", _check(submissions_today=cap))
    _rejects("max_submissions", _check(FLATTEN, submissions_today=cap))
    assert _check(submissions_today=cap - 1).approved


def test_per_intent_submission_cap_triggers_including_for_flatten() -> None:
    cap = LIMITS.max_submissions_per_intent
    _rejects(
        "max_submissions", _check(replace(OK_ORDER, attempt_no=cap + 1), intent_submissions=cap)
    )
    _rejects("max_submissions", _check(FLATTEN, intent_submissions=cap))
    assert _check(replace(OK_ORDER, attempt_no=cap), intent_submissions=cap - 1).approved


# --- stale data (FR-34) ----------------------------------------------------------------


def test_stale_candle_older_than_two_intervals_triggers() -> None:
    old = NOW - 2 * timedelta(days=1) - timedelta(seconds=1)
    _rejects("stale_candle", _check(last_candle_open_at=old))
    assert _check(last_candle_open_at=NOW - 2 * timedelta(days=1)).approved


def test_synthetic_latest_candle_triggers_stale_candle() -> None:
    _rejects("stale_candle", _check(last_candle_synthetic=True))


def test_missing_candle_triggers_stale_candle() -> None:
    _rejects("stale_candle", _check(last_candle_open_at=None))


def test_flatten_is_exempt_from_stale_candle() -> None:
    assert _check(FLATTEN, last_candle_synthetic=True, last_candle_open_at=None).approved


def test_stale_ticker_triggers_and_applies_to_flatten() -> None:
    old = NOW - timedelta(seconds=LIMITS.stale_ticker_seconds + 1)
    _rejects("stale_ticker", _check(ticker_ts=old))
    _rejects("stale_ticker", _check(FLATTEN, ticker_ts=old))
    assert _check(ticker_ts=NOW - timedelta(seconds=LIMITS.stale_ticker_seconds)).approved


# --- price sanity (FR-35) --------------------------------------------------------------


def test_price_sanity_triggers_beyond_two_percent_both_directions() -> None:
    _rejects("price_sanity", _check(mid=Decimal("40801")))
    _rejects("price_sanity", _check(mid=Decimal("39199")))
    assert _check(mid=Decimal("40800")).approved  # exactly 2%


def test_price_sanity_applies_to_flatten() -> None:
    _rejects("price_sanity", _check(FLATTEN, mid=Decimal("30000")))


# --- kill switch, halt, market status, minimums (FR-36, AD-13) ------------------------


def test_kill_switch_rejects_non_flatten_and_exempts_flatten() -> None:
    _rejects("kill_switch", _check(kill_switch_engaged=True))
    assert _check(FLATTEN, kill_switch_engaged=True).approved


@pytest.mark.parametrize("halt", ["daily_loss", "total_drawdown", "reconcile_mismatch"])
def test_active_halt_rejects_non_flatten_and_exempts_flatten(halt: str) -> None:
    d = _check(active_halts=(halt,))
    _rejects("halt", d)
    assert halt in (d.reason or "")
    assert _check(FLATTEN, active_halts=(halt,)).approved


@pytest.mark.parametrize("status", ["post_only", "cancel_only", "limit_only", "maintenance"])
def test_market_status_not_online_rejects_even_flatten(status: str) -> None:
    _rejects("market_status", _check(market_status=status))
    _rejects("market_status", _check(FLATTEN, market_status=status))


def test_qty_below_amount_min_is_rejected_never_rounded() -> None:
    d = _check(replace(OK_ORDER, qty=Decimal("0.00005999")))
    _rejects("minimums", d)


def test_cost_below_cost_min_is_rejected() -> None:
    order = replace(OK_ORDER, qty=Decimal("0.0001"), limit_price=Decimal("4000"))  # 0.40 EUR
    _rejects("minimums", _check(order, mid=Decimal("4000"), reference_price=Decimal("4000")))


def test_minimums_at_exactly_the_boundary_pass() -> None:
    assert _check(replace(OK_ORDER, qty=Decimal("0.00006"))).approved  # = amount_min (2.4 EUR)
    order = replace(OK_ORDER, qty=Decimal("0.0001"), limit_price=Decimal("4500"))  # = 0.45 EUR
    assert _check(order, mid=Decimal("4500"), reference_price=Decimal("4500")).approved


def test_flatten_buy_is_invalid_and_gets_no_exemption() -> None:
    _rejects("invalid_order", _check(replace(OK_ORDER, is_flatten=True), kill_switch_engaged=True))


def test_attempt_number_below_one_is_invalid() -> None:
    _rejects("invalid_order", _check(replace(OK_ORDER, attempt_no=0), intents_today=99))


def test_minimums_apply_to_flatten() -> None:
    _rejects("minimums", _check(replace(FLATTEN, qty=Decimal("0.00001"))))


def test_non_positive_qty_or_price_is_rejected() -> None:
    _rejects("invalid_order", _check(replace(OK_ORDER, qty=Decimal(0))))
    _rejects("invalid_order", _check(replace(OK_ORDER, limit_price=Decimal(-1))))


# --- purity (SAF-05, AD-10) ------------------------------------------------------------

_ALLOWED_IMPORTS = {"__future__", "dataclasses", "datetime", "decimal", "typing", "bot.risk.limits"}


@pytest.mark.parametrize("module", ["checks.py", "halts.py"])
def test_checks_and_halts_are_pure(module: str) -> None:
    """Allowlist: only value-type modules may be imported, so no file, network, clock or
    environment access is possible (SAF-05); no call to open/exec/eval/__import__."""
    tree = ast.parse((REPO_ROOT / "bot" / "risk" / module).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            names = []
        for name in names:
            assert name in _ALLOWED_IMPORTS, f"{module} imports {name}"
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") in {
            "open",
            "exec",
            "eval",
            "__import__",
            "getattr",
        }:
            pytest.fail(f"{module} calls {node.func.id}")  # type: ignore[attr-defined]
