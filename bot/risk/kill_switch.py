"""Kill switch file (FR-36, AD-12, GL-04). PROTECTED (SAF-04).

The kill switch is a file on disk at the absolute ``risk.kill_switch_path``. Any file at
that path counts as engaged, whatever its content: a file created by hand (even empty)
reads as ``source=file``.

This module only reads the file and creates it:

- ``kill_switch_engaged(path) -> bool`` and ``read_kill_switch(path)`` only read;
- ``engage(path, source, at)`` only creates it, with one line ``source=<source> at=<UTC>``
  (used by ``bot kill on`` and the dashboard button). If the file already exists it is left
  untouched: the switch is already engaged and its first record is kept.

There is deliberately NO function here that deletes the file. Disengaging is CLI-only
(``bot kill off --note``): it writes an ``operator_actions`` row and the engine, the only
deleter, removes the file when it consumes that action (AD-12).

Pure apart from the file itself: no clock (the caller passes ``at``), no store, no broker.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

SOURCES = frozenset({"cli", "dashboard", "file"})


@dataclass(frozen=True)
class KillSwitchState:
    engaged: bool
    source: str | None  # "cli" | "dashboard" | "file"; None when not engaged
    at: str | None  # the recorded UTC time, as written; None if absent or unparseable


def _utc_text(at: datetime) -> str:
    if at.tzinfo is None or at.utcoffset() != timedelta(0):
        raise ValueError(f"kill switch time must be timezone-aware UTC, got {at!r}")
    return at.strftime("%Y-%m-%dT%H:%M:%SZ")


def read_kill_switch(path: Path) -> KillSwitchState:
    """State of the kill switch at ``path``. Any existing file is engaged; content that is
    empty or not ``source=<cli|dashboard|file> at=<UTC>`` reads as ``source=file``."""
    p = Path(path)
    if not p.exists():
        return KillSwitchState(engaged=False, source=None, at=None)
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        # Unreadable but present (locked, permissions): still engaged.
        return KillSwitchState(engaged=True, source="file", at=None)
    fields: dict[str, str] = {}
    lines = text.strip().splitlines()
    for token in (lines[0] if lines else "").split():
        key, sep, value = token.partition("=")
        if sep:
            fields[key] = value
    source = fields.get("source")
    if source not in SOURCES:
        return KillSwitchState(engaged=True, source="file", at=None)
    return KillSwitchState(engaged=True, source=source, at=fields.get("at"))


def kill_switch_engaged(path: Path) -> bool:
    """True when a file exists at ``path``. Reads only."""
    return Path(path).exists()


def engage(path: Path, source: str, at: datetime) -> KillSwitchState:
    """Create the kill-switch file with one line ``source=<source> at=<UTC>``.

    Creation is exclusive (``O_EXCL``): an existing file is never overwritten or removed,
    and the state already recorded is returned. Parent directories are created.
    """
    if source not in SOURCES:
        raise ValueError(f"kill switch source must be one of {sorted(SOURCES)}, got {source!r}")
    line = f"source={source} at={_utc_text(at)}\n"
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return read_kill_switch(p)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(line)
        fh.flush()
        os.fsync(fh.fileno())
    return read_kill_switch(p)
