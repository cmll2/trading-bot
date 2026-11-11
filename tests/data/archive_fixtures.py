"""SYNTHETIC Kraken OHLCVT archive fixtures, built in ``tmp_path`` with stdlib ``zipfile``.

None of these rows are real market data. They only mimic the archive format documented in
docs/data-manifest.md: CSV members named ``{PAIR}_{minutes}.csv``, no header, columns
``timestamp, open, high, low, close, volume, trades``, timestamps in Unix seconds, plus a
``MANIFEST.json`` member and decoy members whose names contain ``XBTEUR``.
"""

from __future__ import annotations

import hashlib
import warnings
import zipfile
from pathlib import Path

# 2024-01-01T00:00Z, after data.history_start (2017-01-01).
START_S = 1_704_067_200
# 2015-01-01T00:00Z, before data.history_start: synthetic rows here do not count toward
# max_synthetic_ratio, so a small fixture with a no-trade gap can pass validation.
PRE_HISTORY_START_S = 1_420_070_400

INTERVAL_S = {1440: 86_400, 240: 14_400, 15: 900}


def kraken_csv(
    start_s: int, n: int, step_s: int, skip: tuple[int, ...] = (), base: float = 100.0
) -> str:
    """SYNTHETIC rows ``ts,o,h,l,c,v,trades`` for indexes ``0..n-1`` except ``skip``."""
    lines = []
    for i in range(n):
        if i in skip:
            continue
        o = base + i
        lines.append(f"{start_s + i * step_s},{o},{o + 2.0},{o - 1.0},{o + 0.5},1.25,{10 + i}")
    return "\n".join(lines) + "\n"


def build_zip(path: Path, members: list[tuple[str, str | bytes]]) -> Path:
    """Write a ZIP with these ``(name, content)`` members, in order. Duplicate names are
    allowed (zipfile warns; the warning is silenced here on purpose)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for name, content in members:
                zf.writestr(name, content)
    return path


def standard_members(
    pair: str = "XBTEUR", n: int = 10, start_s: int = START_S
) -> list[tuple[str, str]]:
    """SYNTHETIC ``{pair}_{1440,240,15}.csv`` members, ``n`` consecutive rows each."""
    return [
        (f"{pair}_{m}.csv", kraken_csv(start_s, n, step, base=100.0 + m))
        for m, step in INTERVAL_S.items()
    ]


def decoys() -> list[tuple[str, str]]:
    """SYNTHETIC members a suffix/substring match would wrongly pick up (prices ~ 9000)."""
    return [
        (name, kraken_csv(START_S, 5, 86_400, base=9000.0))
        for name in ("AIXBTEUR_1440.csv", "XBTEURC_1440.csv", "XBTEUROP_1440.csv")
    ] + [("MANIFEST.json", '{"synthetic": true}')]


def standard_zip(tmp_path: Path, n: int = 10) -> Path:
    """SYNTHETIC archive: XBTEUR 1d/4h/15m members, decoys and a MANIFEST.json."""
    return build_zip(tmp_path / "archive" / "synthetic.zip", [*decoys(), *standard_members(n=n)])


def sha256_hex(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
