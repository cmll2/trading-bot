"""Parameter search with trial counting and holdout refusal (FR-15, FR-20, AD-21).

v0 is never tuned (its parameters were fixed before evaluation; configurations tried = 1).
This exists so that any future search is honest by construction: it refuses a range that
touches the holdout and writes the number of configurations tried to its results file, so
results can be judged against the number of trials. There is no CLI entry point for it.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from bot.backtest import dataset as dataset_mod
from bot.backtest.holdout import check_tuning_range
from bot.backtest.metrics import strategy_metrics
from bot.backtest.runner import run_backtest
from bot.config import Settings
from bot.strategy.registry import build


def run_search(
    settings: Settings,
    strategy_id: str,
    grid: list[dict[str, int]],
    start: date,
    end: date,
    results_path: Path,
) -> dict[str, Any]:
    """Backtest every configuration of ``grid`` (maker variant) on ``[start, end)``."""
    check_tuning_range(settings, start, end)
    if not grid:
        raise ValueError("empty parameter grid")
    b = settings.backtest
    timeframes = (
        build(strategy_id, grid[0], "backtest").timeframe,
        settings.execution.sim_timeframe,
    )
    ds = dataset_mod.load_dataset(settings, start, end, timeframes)
    trials = []
    for params in grid:
        run = run_backtest(settings, ds, "maker", strategy_id=strategy_id, params=params)
        m = strategy_metrics(run, b.bootstrap_resamples, b.bootstrap_block_days, b.bootstrap_seed)
        trials.append({"params": params, "maker": m.as_dict()})
    payload = {
        "label": "SIMULATED",
        "kind": "parameter_search",
        "strategy": strategy_id,
        "configurations_tried": len(grid),
        "range": {"start": start.isoformat(), "end_exclusive": end.isoformat()},
        "data_hashes": ds.hashes,
        "trials": trials,
    }
    results_path.parent.mkdir(parents=True, exist_ok=True)
    results_path.write_text(json.dumps(payload, sort_keys=True, indent=2) + "\n", encoding="utf-8")
    return payload
