"""bot.clock adapters used by the data pipeline (AD-2)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from bot.clock import FakeClock, SystemClock

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def test_fake_clock_advance_and_sleep() -> None:
    clock = FakeClock(T0)
    assert clock.now() == T0
    clock.advance(timedelta(minutes=5))
    assert clock.now() == T0 + timedelta(minutes=5)
    clock.sleep_until(T0 + timedelta(minutes=10))
    assert clock.now() == T0 + timedelta(minutes=10)
    clock.sleep_until(T0)  # in the past: time does not go back
    assert clock.now() == T0 + timedelta(minutes=10)
    assert clock.sleep_calls == [T0 + timedelta(minutes=10), T0]


def test_fake_clock_refuses_naive_and_backwards() -> None:
    with pytest.raises(ValueError):
        FakeClock(datetime(2026, 1, 1))  # naive
    with pytest.raises(ValueError):
        FakeClock(T0).advance(timedelta(seconds=-1))


def test_system_clock_is_utc_and_does_not_sleep_for_past_times() -> None:
    clock = SystemClock()
    now = clock.now()
    assert now.tzinfo is not None and now.utcoffset() == timedelta(0)
    clock.sleep_until(now - timedelta(hours=1))  # returns immediately
