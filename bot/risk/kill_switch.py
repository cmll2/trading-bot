"""Kill switch file (FR-36, AD-12). Implemented at M3.

``kill_switch_engaged(path)`` only reads. ``engage(path, source)`` only creates the file
(used by the CLI and the dashboard). The engine is the only deleter, on a consumed
``bot kill off`` operator action.
"""

from __future__ import annotations

from pathlib import Path


def kill_switch_engaged(path: Path) -> bool:
    """True when the kill-switch file exists. M3."""
    raise NotImplementedError("risk.kill_switch_engaged is implemented at M3 (FR-36)")


def engage(path: Path, source: str) -> None:
    """Create the kill-switch file with ``source=<source> at=<UTC>``. M3."""
    raise NotImplementedError("risk.kill_switch.engage is implemented at M3 (FR-36)")
