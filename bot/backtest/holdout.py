"""Holdout discipline, walk-forward folds and the change limit (FR-15..FR-17, FR-20, AD-21).

- **Holdout window** ``backtest.holdout_start .. holdout_end`` (fixed, frozen in config):
  never used for tuning. Every tuning or evaluation range must end at or before
  ``holdout_start`` (``check_tuning_range``; ``load_dataset`` enforces the same rule).
- **Holdout registry** ``results/holdout_runs.jsonl`` (committed): one JSON line per
  holdout run, appended BEFORE the run starts (a crashed run still counts), with the run
  date, git commit, config hash and data hashes. A run is refused when the working tree is
  dirty, or when the strategy already has a line, unless ``--rerun-holdout --reason`` is
  given; that line is marked ``"rerun": true`` and every later report carries a banner.
- **Walk-forward**: v0's parameters are fixed (one configuration, nothing to fit), so
  walk-forward reduces to consecutive out-of-sample folds of ``walk_forward_fold_days``
  over the pre-holdout evaluation window, each compared with buy-and-hold over the same
  fold. Folds never reach the holdout.
- **Change limit**: ``bot backtest --change N`` refuses N > 5, and N >= 1 without a
  ``### Change N`` entry under the strategy's own ``## <strategy id>`` section of
  ``changes.md`` (the limit counts per strategy).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from bot.backtest.dataset import HoldoutViolation
from bot.backtest.runner import RunResult
from bot.config import REPO_ROOT, Settings
from bot.store import parse_iso

MAX_CHANGES = 5
CHANGES_PATH = REPO_ROOT / "changes.md"
REGISTRY_NAME = "holdout_runs.jsonl"


class HoldoutRefused(Exception):
    """A holdout run is not allowed (dirty tree, already run, missing reason)."""


class ChangeRefused(Exception):
    """``--change N`` is above the limit or has no changes.md entry."""


def check_tuning_range(settings: Settings, start: date, end: date) -> None:
    """Refuse any tuning / walk-forward range that touches the holdout (end is exclusive)."""
    if end > settings.backtest.holdout_start:
        raise HoldoutViolation(
            f"range {start}..{end} touches the holdout starting "
            f"{settings.backtest.holdout_start}; tuning on it is forbidden (FR-15)"
        )


def registry_path(settings: Settings) -> Path:
    return settings.backtest.results_dir / REGISTRY_NAME


def holdout_runs(settings: Settings, strategy_id: str) -> list[dict[str, Any]]:
    path = registry_path(settings)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entry = json.loads(line)
            if entry.get("strategy") == strategy_id:
                out.append(entry)
    return out


def check_holdout_allowed(
    settings: Settings, strategy_id: str, dirty: bool, rerun_reason: str | None
) -> bool:
    """Return True for a re-run; raise ``HoldoutRefused`` when the run is not allowed."""
    if dirty:
        raise HoldoutRefused("the working tree is dirty: commit first; a holdout run must be "
                             "reproducible from its recorded commit")  # fmt: skip
    previous = holdout_runs(settings, strategy_id)
    if previous and rerun_reason is None:
        raise HoldoutRefused(
            f"{strategy_id} already has {len(previous)} holdout run(s) recorded in "
            f"{REGISTRY_NAME} (first {previous[0]['run_date']} at "
            f"{previous[0]['git_commit'][:12]}); a second run needs --rerun-holdout --reason"
        )
    if rerun_reason is not None and not rerun_reason.strip():
        raise HoldoutRefused("--rerun-holdout needs a non-empty --reason")
    return bool(previous)


def register_holdout_run(settings: Settings, entry: dict[str, Any]) -> None:
    path = registry_path(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, sort_keys=True) + "\n")


def check_change(n: int, strategy_id: str, changes_path: Path = CHANGES_PATH) -> None:
    if n < 0:
        raise ChangeRefused(f"--change must be >= 0, got {n}")
    if n > MAX_CHANGES:
        raise ChangeRefused(f"--change {n} exceeds the limit of {MAX_CHANGES} changes per strategy")
    if n == 0:
        return
    text = changes_path.read_text(encoding="utf-8") if changes_path.exists() else ""
    section = re.search(
        rf"^## {re.escape(strategy_id)}\s*$(.*?)(?=^## |\Z)", text, flags=re.MULTILINE | re.DOTALL
    )
    body = section.group(1) if section else ""
    if not re.search(rf"^### Change {n}\b", body, flags=re.MULTILINE):
        raise ChangeRefused(
            f"changes.md has no '### Change {n}' entry under '## {strategy_id}': log the "
            "change first"
        )


@dataclass(frozen=True)
class Fold:
    start: str
    end: str
    strategy_return: float
    buy_and_hold_return: float
    strategy_max_drawdown: float
    fills: int


def walk_forward(
    run: RunResult,
    fold_days: int,
    holdout_start: date,
    fee: Decimal,
    slippage_bps: Decimal,
) -> list[dict[str, Any]]:
    """Consecutive out-of-sample folds over the evaluation window (none touches the
    holdout); the last, shorter remainder is kept if it spans at least 30 days."""
    pts = [p for p in run.equity if p[0] >= run.eval_start]
    if not pts:
        return []
    limit = pts[0][0].replace(year=holdout_start.year, month=holdout_start.month,
                              day=holdout_start.day, hour=0, minute=0, second=0)  # fmt: skip
    folds: list[dict[str, Any]] = []
    i = 0
    while i < len(pts) - 1:
        start_t = pts[i][0]
        j = i
        while j + 1 < len(pts) and pts[j + 1][0] < start_t + timedelta(days=fold_days):
            j += 1
        if j + 1 < len(pts):
            j += 1  # the fold ends on the first point of the next fold
        seg = pts[i : j + 1]
        if seg[-1][0] > limit:
            raise HoldoutViolation("walk-forward fold reaches into the holdout")
        if (seg[-1][0] - seg[0][0]).days >= 30:
            peak, mdd = float(seg[0][1]), 0.0
            for p in seg:
                peak = max(peak, float(p[1]))
                mdd = max(mdd, 1 - float(p[1]) / peak)
            fills = sum(1 for f in run.fills if seg[0][0] <= parse_iso(str(f["at"])) < seg[-1][0])
            # Buy-and-hold for the fold pays its entry fee and slippage, like the strategy.
            entry = seg[0][2] * (1 + slippage_bps * Decimal("0.0001")) * (1 + fee)
            folds.append(
                asdict(
                    Fold(
                        start=seg[0][0].isoformat(),
                        end=seg[-1][0].isoformat(),
                        strategy_return=float(seg[-1][1] / seg[0][1] - 1),
                        buy_and_hold_return=float(seg[-1][2] / entry - 1),
                        strategy_max_drawdown=mdd,
                        fills=fills,
                    )
                )
            )
        i = j
    return folds
