"""Main loop: candle -> signal -> risk -> order (FR-38, FR-39, AD-1, AD-7, AD-8, AD-28). M3.

The only module that composes the ports (Broker, Clock, MarketData, Store) with the pure
core (strategy, risk, sizing). Same code in every mode; only the adapters change (FR-11).
"""

from __future__ import annotations


class Engine:
    """Composes ports and core. M3."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        raise NotImplementedError("Engine is implemented at M3 (FR-38)")
