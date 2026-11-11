"""Clock port (AD-2). The only module allowed to read wall-clock time.

Ruff banned-api (TID251) forbids ``datetime.now``, ``time.time``, ``time.sleep`` etc.
everywhere else. Adapters: SystemClock (M3, with exchange skew check), SimClock (M2),
FakeClock (tests, M3).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime:
        """Current time, timezone-aware UTC."""
        ...

    def sleep_until(self, t: datetime) -> None: ...
