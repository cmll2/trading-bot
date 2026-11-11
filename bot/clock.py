"""Clock port (AD-2). The only module allowed to read wall-clock time.

Ruff banned-api (TID251) forbids ``datetime.now``, ``time.time``, ``time.sleep`` etc.
everywhere else. Adapters:

- ``SystemClock``: real UTC wall clock. The exchange skew check of AD-2 (compare with
  Kraken's public server time at startup and hourly, refuse to trade beyond 5 s) is added
  at M3 when the engine first trades; M1 data download does not need it.
- ``FakeClock``: deterministic clock for tests; ``sleep_until`` never blocks.
- ``SimClock``: backtest clock (M2).
"""

from __future__ import annotations

import time
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...

    def sleep_until(self, t: datetime) -> None: ...


def _require_utc(t: datetime) -> datetime:
    if t.tzinfo is None or t.utcoffset() != timedelta(0):
        raise ValueError(f"clock times must be timezone-aware UTC, got {t!r}")
    return t


class SystemClock:
    """Real wall clock, UTC. Skew check against the exchange arrives at M3 (AD-2)."""

    def now(self) -> datetime:
        return datetime.now(UTC)

    def sleep_until(self, t: datetime) -> None:
        delta = (_require_utc(t) - self.now()).total_seconds()
        time.sleep(max(0.0, delta))


class FakeClock:
    """Test clock: time moves only through ``advance`` or ``sleep_until``.

    ``sleep_calls`` records every ``sleep_until`` target, so tests can assert backoff waits.
    """

    def __init__(self, start: datetime) -> None:
        self._now = _require_utc(start)
        self.sleep_calls: list[datetime] = []

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        if delta < timedelta(0):
            raise ValueError("FakeClock cannot move backwards")
        self._now = self._now + delta

    def sleep_until(self, t: datetime) -> None:
        self.sleep_calls.append(_require_utc(t))
        self._now = max(self._now, t)
