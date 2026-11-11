"""Strategy registry (AD-3, AD-15, AD-30).

Two frozen mappings. ``plumbing`` exists only in ``DRY_RUN_STRATEGIES``; a strategy runs in
live only if it is in ``LIVE_STRATEGIES`` AND declares ``"live"`` in ``allowed_modes``
(FR-10). Both conditions are checked by ``strategy_class_for``.
"""

from __future__ import annotations

from types import MappingProxyType

from bot.strategy.base import Mode
from bot.strategy.plumbing import Plumbing
from bot.strategy.v0_trend import V0Trend


class StrategyNotAllowed(Exception):
    """The strategy is unknown or not allowed in the requested mode."""


LIVE_STRATEGIES = MappingProxyType({"v0_trend": V0Trend})
DRY_RUN_STRATEGIES = MappingProxyType({"v0_trend": V0Trend, "plumbing": Plumbing})
BACKTEST_STRATEGIES = DRY_RUN_STRATEGIES

_BY_MODE = MappingProxyType(
    {"backtest": BACKTEST_STRATEGIES, "dry-run": DRY_RUN_STRATEGIES, "live": LIVE_STRATEGIES}
)


def strategy_class_for(strategy_id: str, mode: Mode) -> type:
    """Return the strategy class for ``mode`` or raise ``StrategyNotAllowed``."""
    registry = _BY_MODE.get(mode)
    if registry is None:
        raise StrategyNotAllowed(f"unknown mode {mode!r}")
    cls = registry.get(strategy_id)
    if cls is None:
        raise StrategyNotAllowed(f"strategy {strategy_id!r} is not allowed in {mode} mode")
    if mode not in cls.allowed_modes:
        raise StrategyNotAllowed(f"strategy {strategy_id!r} does not allow {mode} mode")
    return cls
