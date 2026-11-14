"""Story M3-2: crash-safe restart mid-order with no duplicates (FR-26, FR-27, FR-39,
FR-59, AD-7, AD-8, AD-27, AD-28). FakeBroker + FakeClock; a "crash" is a BaseException
raised at a chosen line, then a NEW engine is built on the same store (``env.restart``).
"""

from __future__ import annotations

import random
from datetime import timedelta
from decimal import Decimal

import pytest

from bot.broker.errors import TransientReadError
from bot.engine import IllegalTransition
from bot.store import Store, iso
from tests.engine.fake_env import FakeEnv


class Crash(BaseException):
    """The process dies here (never caught by the engine)."""


def _live_exchange_orders(env: FakeEnv) -> list[str]:
    return [o.cl_ord_id for o in env.broker.get_open_orders("BTC/EUR")]


def _assert_no_duplicate(env: FakeEnv) -> None:
    placed = [r.cl_ord_id for r in env.broker.placed]
    assert len(placed) == len(set(placed))
    assert len(_live_exchange_orders(env)) <= 1  # one live order per (single) intent
    for intent in env.intents():
        assert Decimal(intent["filled_qty"]) == env.fills_qty(intent["intent_id"])
    for order in env.orders():
        rows = env.store.all("SELECT qty FROM fills WHERE order_id = ?", (order["order_id"],))
        assert Decimal(order["filled_qty"]) == sum((Decimal(r["qty"]) for r in rows), Decimal(0))


def test_order_row_is_committed_before_the_broker_call(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    seen: list[tuple[str, str]] = []
    real = env.broker.place_order

    def spy(req, decision):  # noqa: ANN001, ANN202
        other = Store.open_readonly(tmp_path / "engine.sqlite")  # a second connection
        row = other.one("SELECT state FROM orders WHERE cl_ord_id = ?", (req.cl_ord_id,))
        other.close()
        seen.append((req.cl_ord_id, row["state"] if row else "MISSING"))
        return real(req, decision)

    env.broker.place_order = spy  # type: ignore[method-assign]
    env.tick()
    assert seen == [("cl0001", "submitting")]


def test_crash_after_insert_before_send_marks_not_found_and_retries_with_new_id(
    tmp_path, monkeypatch
) -> None:
    env = FakeEnv(tmp_path)
    real = env.engine._transition  # noqa: SLF001

    def crash_on_submitting(order_id, to, now, **cols):  # noqa: ANN001, ANN003, ANN202
        if to == "submitting":
            raise Crash
        return real(order_id, to, now, **cols)

    monkeypatch.setattr(env.engine, "_transition", crash_on_submitting)
    with pytest.raises(Crash):
        env.tick()
    assert [o["state"] for o in env.orders()] == ["created"]
    env.restart()
    assert [o["state"] for o in env.orders()] == ["not_found"]
    assert env.broker.submitted == []  # the created order was never sent
    env.tick()
    assert [o["state"] for o in env.orders()] == ["not_found", "open"]
    assert [r.cl_ord_id for r in env.broker.placed] == ["cl0002"]
    _assert_no_duplicate(env)


def test_crash_after_the_exchange_accepted_resolves_to_open_without_resend(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    real = env.broker.place_order

    def accept_then_crash(req, decision):  # noqa: ANN001, ANN202
        real(req, decision)
        raise Crash

    env.broker.place_order = accept_then_crash  # type: ignore[method-assign]
    with pytest.raises(Crash):
        env.tick()
    assert [o["state"] for o in env.orders()] == ["submitting"]
    env.broker.place_order = real  # type: ignore[method-assign]
    env.restart()
    orders = env.orders()
    assert [o["state"] for o in orders] == ["open"]
    assert orders[0]["exchange_order_id"] == "O1"
    for _ in range(5):
        env.tick()
    assert [r.cl_ord_id for r in env.broker.placed] == ["cl0001"]
    _assert_no_duplicate(env)


def test_crash_before_the_request_left_waits_the_grace_then_not_found(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    real = env.broker.place_order

    def crash_before_send(req, decision):  # noqa: ANN001, ANN202
        raise Crash

    env.broker.place_order = crash_before_send  # type: ignore[method-assign]
    with pytest.raises(Crash):
        env.tick()
    env.broker.place_order = real  # type: ignore[method-assign]
    crashed_at = env.clock.now()
    env.restart()
    order = env.orders()[0]
    assert order["state"] == "not_found"
    # looked up every 10 s, open AND closed, until the 60 s grace had passed
    assert env.clock.now() - crashed_at >= timedelta(seconds=60)
    assert env.broker.submitted == []
    env.tick()
    assert [r.cl_ord_id for r in env.broker.placed] == ["cl0002"]
    _assert_no_duplicate(env)


def test_timeout_after_accept_is_never_resent(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.broker.script_place("timeout_after_accept")
    env.tick()
    assert [o["state"] for o in env.orders()] == ["open"]  # found by find_order at once
    for _ in range(4):
        env.tick()
    assert [r.cl_ord_id for r in env.broker.submitted] == ["cl0001"]
    _assert_no_duplicate(env)


def test_unknown_absent_order_frees_the_intent_only_after_the_grace(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    real = env.broker.place_order
    calls = {"n": 0}

    def lost(req, decision):  # noqa: ANN001, ANN202
        calls["n"] += 1
        if calls["n"] == 1:
            from bot.broker.errors import OrderOutcomeUnknown

            raise OrderOutcomeUnknown("timeout before the exchange saw it")
        return real(req, decision)

    env.broker.place_order = lost  # type: ignore[method-assign]
    start = env.clock.now()
    env.tick()
    states = [o["state"] for o in env.orders()]
    assert states[0] == "not_found"
    assert env.clock.now() - start >= timedelta(seconds=60)
    env.tick()
    assert [o["state"] for o in env.orders()] == ["not_found", "open"]
    _assert_no_duplicate(env)


def test_partial_fills_after_restart_are_counted_once(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    cl = env.orders()[0]["cl_ord_id"]
    qty = Decimal(env.orders()[0]["qty"])
    env.broker.fill(cl, qty / 2)
    env.restart()
    env.restart()  # twice: re-polling the same fills never double-counts
    order = env.orders()[0]
    assert order["state"] == "partially_filled"
    assert Decimal(order["filled_qty"]) == qty / 2
    env.broker.fill(cl, qty / 2)
    env.tick()
    assert env.orders()[0]["state"] == "filled"
    assert env.signals()[0]["outcome"] == "filled"
    assert env.store.one("SELECT count(*) FROM fills")[0] == 2
    _assert_no_duplicate(env)


def test_restart_in_cancel_requested_resolves_with_final_fills(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    order = env.orders()[0]
    env.broker.fill(order["cl_ord_id"], Decimal(order["qty"]) / 4)
    env.engine._transition(order["order_id"], "cancel_requested", env.clock.now())  # noqa: SLF001
    env.broker.cancel_order("BTC/EUR", order["cl_ord_id"])  # reached the exchange, then crash
    env.restart()
    order = env.orders()[0]
    assert order["state"] == "cancelled"
    assert Decimal(order["filled_qty"]) == Decimal(order["qty"]) / 4
    _assert_no_duplicate(env)


def test_exchange_side_cancel_is_followed(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.broker.exchange_cancel("cl0001")
    env.tick()
    assert env.orders()[0]["state"] == "cancelled"
    env.tick()  # the intent continues with a new attempt
    assert [o["state"] for o in env.orders()] == ["cancelled", "open"]
    _assert_no_duplicate(env)


def test_pending_signal_without_intent_is_resumed_while_its_window_is_open(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    open_at = "2026-11-13T00:00:00.000Z"
    with env.store.transaction():
        env.store.insert(
            "signals", signal_id=f"test_const|BTC/EUR|1d|{open_at}", run_id=env.engine.run_id,
            strategy_id="test_const", pair="BTC/EUR", timeframe="1d", candle_open_at=open_at,
            evaluated_at=iso(env.clock.now()), target_fraction="1", signal_price="40000",
            indicators_json="{}", outcome="pending",
        )  # fmt: skip
    env.restart()
    # Review fix (stories 5-8): nothing is sent during recover(), before the halts and the
    # startup reconciliation; the first tick re-evaluates the signal and sends the order.
    assert env.broker.submitted == []
    env.tick()
    assert len(env.intents()) == 1
    assert [o["state"] for o in env.orders()] == ["open"]
    assert env.store.one("SELECT count(*) FROM signals")[0] == 1


def test_pending_signal_whose_window_passed_ends_not_filled(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    open_at = "2026-11-12T00:00:00.000Z"  # window ended 2026-11-13 06:00
    with env.store.transaction():
        env.store.insert(
            "signals", signal_id=f"test_const|BTC/EUR|1d|{open_at}", run_id=env.engine.run_id,
            strategy_id="test_const", pair="BTC/EUR", timeframe="1d", candle_open_at=open_at,
            evaluated_at=iso(env.clock.now()), target_fraction="1", signal_price="40000",
            indicators_json="{}", outcome="pending",
        )  # fmt: skip
    env.restart()
    sig = env.signals()[0]
    assert (sig["outcome"], sig["outcome_reason"]) == ("not_filled", "restart_window_passed")
    assert env.intents() == []


def test_rate_limited_read_sleeps_records_and_changes_no_state(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    before = env.orders()
    env.broker.script_read("ok", "rate_limit")  # ticker ok, then get_fills is limited
    env.clock.sleep_calls.clear()
    env.tick()
    assert env.clock.sleep_calls  # slept retry_after_s
    row = env.store.one("SELECT * FROM api_calls WHERE rate_limited = 1")
    assert row is not None and row["endpoint"].startswith("broker.")
    assert [o["state"] for o in env.orders()] == [o["state"] for o in before]


def test_transient_reads_are_retried_three_times_then_skip_the_tick(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    before = env.orders()
    env.broker.script_read("ok", "transient", "transient", "transient", "transient")
    with pytest.raises(TransientReadError):
        env.tick()
    assert env.store.one("SELECT count(*) FROM api_calls WHERE ok = 0")[0] == 4
    assert env.orders() == before
    env.tick()  # recovers on the next tick
    _assert_no_duplicate(env)


def test_illegal_transition_raises(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    with pytest.raises(IllegalTransition):
        env.engine._transition(env.orders()[0]["order_id"], "created", env.clock.now())  # noqa: SLF001


def test_illegal_transition_in_the_loop_halts_fatal_error_and_exits_non_zero(
    tmp_path, monkeypatch
) -> None:
    from bot.clock import FakeClock
    from tests.engine.helpers import T0, dry_run, run

    dry, _ = dry_run(tmp_path, FakeClock(T0 + timedelta(seconds=25)))

    def bad_tick():  # noqa: ANN202
        raise IllegalTransition("order 1: filled -> open")

    monkeypatch.setattr(dry.engine, "tick", bad_tick)
    result = run(dry, ticks=2)
    assert result.exit_code == 1
    assert [r["rule"] for r in dry.store.all("SELECT rule FROM halts")] == ["fatal_error"]
    assert dry.store.one("SELECT stop_reason FROM runs")[0].startswith("fatal")
    assert dry.store.one("SELECT count(*) FROM errors WHERE component = 'fatal'")[0] == 1


def _install_crasher(env: FakeEnv, hit: int) -> None:
    """Raise ``Crash`` at the ``hit``-th order transition or broker submission edge."""
    counter = {"n": 0}
    real_t = env.engine._transition  # noqa: SLF001
    real_p = env.broker.place_order

    def maybe_crash() -> None:
        counter["n"] += 1
        if counter["n"] == hit:
            raise Crash

    def t(order_id, to, now, **cols):  # noqa: ANN001, ANN003, ANN202
        maybe_crash()
        return real_t(order_id, to, now, **cols)

    def p(req, decision):  # noqa: ANN001, ANN202
        maybe_crash()
        ack = real_p(req, decision)
        maybe_crash()
        return ack

    env.engine._transition = t  # type: ignore[method-assign]  # noqa: SLF001
    env.broker.place_order = p  # type: ignore[method-assign]


@pytest.mark.parametrize("seed", range(25))
def test_random_crash_points_never_duplicate_or_lose_fills(tmp_path, seed: int) -> None:
    """Kill the process at a random broker or transition call, restart, repeat; the
    invariants hold every time (story note: auditor's random-kill check, in small)."""
    rng = random.Random(seed)  # noqa: S311 - test randomness
    env = FakeEnv(tmp_path)
    for _ in range(6):
        real_p = env.broker.place_order
        _install_crasher(env, rng.randrange(1, 8))
        try:
            for _ in range(3):
                env.tick(timedelta(minutes=rng.choice([1, 31])))
                live = _live_exchange_orders(env)
                if live and rng.random() < 0.5:
                    o = env.broker.find_order("BTC/EUR", live[0])
                    env.broker.fill(live[0], (o.qty - o.filled_qty) / 2)
        except Crash:
            pass
        env.broker.place_order = real_p  # type: ignore[method-assign]
        env.restart()
        _assert_no_duplicate(env)
