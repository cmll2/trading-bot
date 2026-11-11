"""SimClock (AD-1, AD-2): the backtest clock only moves forward."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bot.clock import SimClock

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_sim_clock_advance_to_and_sleep_until() -> None:
    clock = SimClock(T0)
    assert clock.now() == T0
    clock.advance_to(T0 + timedelta(minutes=5))
    assert clock.now() == T0 + timedelta(minutes=5)
    clock.advance_to(T0 + timedelta(minutes=5))  # same instant is allowed
    clock.sleep_until(T0 + timedelta(hours=1))
    assert clock.now() == T0 + timedelta(hours=1)
    clock.sleep_until(T0)  # in the past: a no-op, never backwards
    assert clock.now() == T0 + timedelta(hours=1)


def test_sim_clock_refuses_backwards() -> None:
    clock = SimClock(T0 + timedelta(hours=1))
    with pytest.raises(ValueError, match="backwards"):
        clock.advance_to(T0)
    assert clock.now() == T0 + timedelta(hours=1)


def test_sim_clock_refuses_naive_times() -> None:
    with pytest.raises(ValueError):
        SimClock(datetime(2026, 1, 1))
    clock = SimClock(T0)
    with pytest.raises(ValueError):
        clock.advance_to(datetime(2026, 1, 2))
    with pytest.raises(ValueError):
        clock.sleep_until(datetime(2026, 1, 2))
