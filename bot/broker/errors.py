"""Broker error taxonomy (architecture §1). Every adapter maps its native errors to these."""

from __future__ import annotations


class BrokerError(Exception):
    """Base class of all broker errors."""


class OrderRejected(BrokerError):
    """Definitive rejection: nothing exists on the exchange."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class PostOnlyWouldCross(OrderRejected):
    """Post-only order would have crossed the book; triggers a re-price (AD-5)."""


class OrderOutcomeUnknown(BrokerError):
    """Timeout or network error after send: the order MAY exist (AD-8)."""


class RateLimited(BrokerError):
    def __init__(self, retry_after_s: float) -> None:
        super().__init__(f"rate limited, retry after {retry_after_s}s")
        self.retry_after_s = retry_after_s


class TransientReadError(BrokerError):
    """A read failed; safe to retry."""


class FatalBrokerError(BrokerError):
    """Auth, permission or nonce failure: the engine halts."""
