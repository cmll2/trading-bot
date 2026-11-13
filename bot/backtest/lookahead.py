"""Look-ahead guard by prefix invariance (FR-22, AD-4).

Every backtest re-runs THE WHOLE PIPELINE at ``backtest.lookahead_cutpoints`` seeded
cutpoints k: a fresh dataset load (``bot.backtest.dataset.load_dataset``, looked up at call
time), a fresh strategy from the registry and a fresh engine. Each cutpoint is run twice:
every candle that opens at or after candle k's close is replaced by a seeded random walk
with upward drift, then by its mirror image (negated returns, downward drift), and each
run stops right after candle k has been evaluated. Any decision that depends on the
direction of the future therefore differs from the baseline in at least one of the two.
The target position journaled for every candle up to and including k must equal the
baseline run's; otherwise ``LookAheadError`` is raised and the caller writes no report.

Because candles enter a backtest only through the dataset loader, a strategy that reads
"the loaded frame" through a closure, a module global refreshed on load, or a column
precomputed from it sees the random future in the rerun and its past targets change.

Known limits: the mirror negates only returns (wicks and volume are identical in both
reruns), so a leak that depends only on the SIZE of a future move, its range or its volume
is caught only if the random walk itself changes the decision. A strategy that reads the
Parquet files itself, or caches the baseline's frame in a global it never refreshes, is
not caught by this guard; the import rules (strategy/ may not import data/) and review
cover that.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import date, timedelta

from bot.backtest import dataset as dataset_mod
from bot.backtest.runner import InsufficientData, RunResult, run_backtest
from bot.config import Settings
from bot.store import parse_iso


class LookAheadError(RuntimeError):
    """A past target changed when only the future was replaced: future data leaked."""


@dataclass(frozen=True)
class LookAheadReport:
    cutpoints: tuple[str, ...]  # candle open_at (ISO) of each checked cutpoint
    candles_compared: int
    seed: int


def _targets(run: RunResult) -> dict[str, str]:
    return {str(s["candle_open_at"]): str(s["target_fraction"]) for s in run.signals}


def check_prefix_invariance(
    settings: Settings,
    start: date,
    end: date,
    timeframes: tuple[str, ...],
    baseline: RunResult,
    *,
    strategy_id: str | None = None,
    params: dict[str, int] | None = None,
    n_cutpoints: int | None = None,
    seed: int | None = None,
    allow_holdout: bool = False,
) -> LookAheadReport:
    n = settings.backtest.lookahead_cutpoints if n_cutpoints is None else n_cutpoints
    seed = settings.backtest.lookahead_seed if seed is None else seed
    base = _targets(baseline)
    candles = sorted(base)
    # Cutpoints after the warm-up (where targets can differ at all), excluding the last
    # candle (nothing follows it to replace).
    step = dataset_mod.interval(timeframes[0])  # strategy timeframe comes first
    eligible = [c for c in candles if parse_iso(c) + step >= baseline.eval_start]
    eligible = eligible[:-1]
    if not eligible:
        raise InsufficientData("no candle after the warm-up to cut at: guard cannot run")
    rng = random.Random(seed)  # noqa: S311 - reproducible sampling, not security
    cuts = sorted(rng.sample(eligible, min(n, len(eligible))))
    lag = timedelta(seconds=settings.execution.tick_seconds)
    compared = 0
    for i, k in enumerate(cuts):
        k_open = parse_iso(k)
        cut = k_open + step  # candle k's close
        for mirror in (False, True):
            ds = dataset_mod.load_dataset(
                settings,
                start,
                end,
                timeframes,
                replace_after=cut,
                seed=seed + i + 1,
                mirror=mirror,
                allow_holdout=allow_holdout,
            )
            rerun = run_backtest(
                settings,
                ds,
                "maker",
                stop_after=cut + lag,
                strategy_id=strategy_id,
                params=params,
            )
            got = _targets(rerun)
            for c in candles:
                if parse_iso(c) > k_open:
                    break
                if c not in got:
                    raise LookAheadError(f"rerun at cutpoint {k} did not evaluate candle {c}")
                if got[c] != base[c]:
                    raise LookAheadError(
                        f"look-ahead detected: target for candle {c} was {base[c]} with real "
                        f"future data but {got[c]} when data after {cut.isoformat()} was "
                        f"replaced ({'mirrored ' if mirror else ''}random walk, cutpoint "
                        f"{i + 1}/{len(cuts)})"
                    )
                compared += 0 if mirror else 1  # distinct candles, not reruns
    return LookAheadReport(cutpoints=tuple(cuts), candles_compared=compared, seed=seed)
