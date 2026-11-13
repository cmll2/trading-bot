"""``bot backtest``: one command from cached candles to a labelled results file (FR-14).

Default range: ``data.history_start`` (inclusive) to ``backtest.holdout_start``
(exclusive): the holdout is excluded by default and its data is never loaded (FR-15).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

from bot.backtest import dataset as dataset_mod
from bot.backtest.dataset import anomalies_in
from bot.backtest.lookahead import check_prefix_invariance
from bot.backtest.provenance import config_hash, git_commit, git_dirty
from bot.backtest.results import results_stem, write_results
from bot.backtest.runner import InsufficientData, RunResult, run_backtest
from bot.config import Settings
from bot.strategy.registry import build

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_DATA_ERROR = 4


class BacktestRefused(Exception):
    """The requested backtest violates a rule (holdout, change limit, ...)."""


@dataclass(frozen=True)
class BacktestRequest:
    strategy_id: str
    start: date
    end: date  # exclusive
    results_dir: Path
    run_date: date


def default_request(settings: Settings, strategy_id: str | None, run_date: date) -> BacktestRequest:
    return BacktestRequest(
        strategy_id=strategy_id or settings.strategy.id,
        start=settings.data.history_start,
        end=settings.backtest.holdout_start,
        results_dir=settings.backtest.results_dir,
        run_date=run_date,
    )


def _check_range(settings: Settings, req: BacktestRequest) -> None:
    if req.end <= req.start:
        raise BacktestRefused(f"empty range: end {req.end} is not after start {req.start}")
    if req.start < settings.data.history_start:
        raise BacktestRefused(
            f"start {req.start} is before data.history_start {settings.data.history_start}"
        )
    if req.end > settings.backtest.holdout_start:
        raise BacktestRefused(
            f"range end {req.end} reaches into the holdout starting "
            f"{settings.backtest.holdout_start}; the holdout is excluded from backtests"
        )


def _window_return(run: RunResult) -> dict[str, Any]:
    pts = [p for p in run.equity if p[0] >= run.eval_start]
    if len(pts) < 2:
        raise InsufficientData("not enough daily points after the warm-up to evaluate")
    (t0, e0, m0, _), (t1, e1, m1, _) = pts[0], pts[-1]
    return {
        "from": t0.isoformat(),
        "to": t1.isoformat(),
        "strategy_total_return": float(e1 / e0 - 1),
        "buy_and_hold_total_return_gross": float(m1 / m0 - 1),
        "cash_total_return": 0.0,
        "strategy_final_equity": str(e1),
        "trades": len(run.fills),
    }


def execute(settings: Settings, req: BacktestRequest) -> tuple[Path, Path, dict[str, Any]]:
    """Run the backtest and write its results; raises ``BacktestRefused`` on a rule."""
    _check_range(settings, req)
    strategy = build(req.strategy_id, settings.strategy.params, "backtest")
    if not getattr(strategy, "implemented", True):
        raise NotImplementedError(f"strategy {req.strategy_id} is not implemented yet")
    timeframes = (strategy.timeframe, settings.execution.sim_timeframe)
    ds = dataset_mod.load_dataset(settings, req.start, req.end, timeframes)
    maker = run_backtest(settings, ds, "maker", strategy_id=req.strategy_id)
    # AD-4: raises LookAheadError before anything is written.
    guard = check_prefix_invariance(
        settings, req.start, req.end, timeframes, maker, strategy_id=req.strategy_id
    )
    commit = git_commit()
    payload: dict[str, Any] = {
        "label": "SIMULATED",
        "strategy": req.strategy_id,
        "params": dict(settings.strategy.params),
        "code_version": {"git_commit": commit, "git_dirty": git_dirty()},
        "config_hash": config_hash(settings),
        "data": {
            "pair": ds.pair,
            "start": ds.start.isoformat(),
            "end_exclusive": ds.end.isoformat(),
            "hashes": ds.hashes,
        },
        "data_anomalies": anomalies_in(ds),
        "market_rules": maker.rules_snapshot,
        "fees": {
            "maker": str(settings.fees.maker),
            "taker": str(settings.fees.taker),
            "source": settings.fees.source,
        },
        "slippage_bps": str(settings.slippage_bps),
        "configurations_tried": 1,
        "lookahead_guard": {
            "passed": True,
            "cutpoints": list(guard.cutpoints),
            "candles_compared": guard.candles_compared,
            "seed": guard.seed,
        },
        "maker": _window_return(maker),
        "halted": maker.halted,
    }
    s = payload["maker"]
    first = (
        "SIMULATED BACKTEST: "
        f"{req.strategy_id} {s['strategy_total_return']:+.2%} vs buy-and-hold "
        f"{s['buy_and_hold_total_return_gross']:+.2%} (gross) vs cash +0.00%"
    )
    report = first + "\n"
    stem = results_stem(req.run_date, req.strategy_id, commit)
    j, m = write_results(req.results_dir, stem, payload, report)
    return j, m, payload


def print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


__all__ = ["BacktestRefused", "BacktestRequest", "default_request", "execute"]
