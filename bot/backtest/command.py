"""``bot backtest``: one command from cached candles to a labelled results file (FR-14).

Default range: ``data.history_start`` (inclusive) to ``backtest.holdout_start``
(exclusive): the holdout is excluded by default and its data is never loaded (FR-15).
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from bot.backtest import dataset as dataset_mod
from bot.backtest.dataset import anomalies_in
from bot.backtest.holdout import (
    ChangeRefused,
    HoldoutRefused,
    check_change,
    check_holdout_allowed,
    holdout_runs,
    register_holdout_run,
    walk_forward,
)
from bot.backtest.lookahead import check_prefix_invariance
from bot.backtest.metrics import buy_and_hold_metrics, cash_metrics, strategy_metrics
from bot.backtest.provenance import config_hash, git_commit, git_dirty, limits_hash
from bot.backtest.report import anomaly_block, render_markdown, variant_block, verdict
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
    change: int = 0  # FR-17: 0 = baseline; 1..5 need a changes.md entry
    holdout: bool = False  # FR-16: the single registered holdout run
    rerun_reason: str | None = None  # --rerun-holdout --reason


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


def caveats(settings: Settings) -> list[str]:
    e, r = settings.execution, settings.risk
    return [
        f"Positions are capped by the protected risk limit max_position_abs_quote (EUR "
        f"{r.max_position_abs_quote}): once equity grows past it, re-entries invest at most "
        f"that amount while buy-and-hold keeps its whole initial stake invested (it buys "
        f"once and holds).",
        "Exchange minimums and precision come from one public market snapshot and are "
        "applied to the whole history; historical minimums differed.",
        f"Fees are Kraken's published entry tier (maker {settings.fees.maker}, taker "
        f"{settings.fees.taker}), not the account's tier (verified against fetch_trading_fee "
        f"at live start, M6).",
        f"Execution model: post-only limit at the best bid/ask (last closed {e.sim_timeframe} "
        f"close +/- {e.sim_half_spread_bps} bp), re-priced every {e.reprice_interval_minutes} "
        f"min within {e.window_hours} h after the daily close, plus a {e.completion_window_hours} "
        f"h completion phase for an unsellable partial buy; filled only on a strict "
        f"trade-through of a later closed {e.sim_timeframe} candle; synthetic (no-trade / "
        f"exchange-halt) candles never fill. The taker variant fills at once at the ask/bid; "
        f"its buy-and-hold benchmark pays the same half spread.",
        "Equity of the strategy and of buy-and-hold is marked at mid, without exit costs.",
        "Parameters were fixed before any evaluation; configurations tried: 1. The holdout "
        "window is excluded and its data not loaded.",
    ]


def _metrics(  # noqa: ANN001
    settings: Settings, run: RunResult, fee, half_spread_bps=Decimal(0)
) -> dict[str, Any]:
    b = settings.backtest
    try:
        strat = strategy_metrics(
            run, b.bootstrap_resamples, b.bootstrap_block_days, b.bootstrap_seed
        )
        bh = buy_and_hold_metrics(
            run, fee, settings.slippage_bps, b.bootstrap_resamples, b.bootstrap_block_days,
            b.bootstrap_seed, half_spread_bps,
        )  # fmt: skip
        cash = cash_metrics(run)
    except ValueError as exc:
        raise InsufficientData(str(exc)) from exc
    return variant_block(run, strat, bh, cash)


def execute(settings: Settings, req: BacktestRequest) -> tuple[Path, Path, dict[str, Any]]:
    """Run the backtest (maker and taker variants, look-ahead guard) and write the results
    JSON and Markdown report; raises ``BacktestRefused`` / ``LookAheadError`` /
    ``InsufficientData`` before writing anything."""
    try:
        check_change(req.change)
    except ChangeRefused as exc:
        raise BacktestRefused(str(exc)) from exc
    if not req.holdout:
        _check_range(settings, req)
    try:
        strategy = build(req.strategy_id, settings.strategy.params, "backtest")
    except ValueError as exc:
        raise BacktestRefused(f"invalid strategy parameters: {exc}") from exc
    if not getattr(strategy, "implemented", True):
        raise NotImplementedError(f"strategy {req.strategy_id} is not implemented yet")
    timeframes = (strategy.timeframe, settings.execution.sim_timeframe)
    commit = git_commit()
    start, end = req.start, req.end
    holdout_entry: dict[str, Any] | None = None
    if req.holdout:
        try:
            rerun = check_holdout_allowed(settings, req.strategy_id, git_dirty(), req.rerun_reason)
        except HoldoutRefused as exc:
            raise BacktestRefused(str(exc)) from exc
        hs = settings.backtest.holdout_start
        # Warm-up candles before the holdout are read; evaluation starts at holdout_start.
        start = max(settings.data.history_start, hs - timedelta(days=strategy.warmup + 10))
        end = settings.backtest.holdout_end + timedelta(days=1)
    try:
        ds = dataset_mod.load_dataset(settings, start, end, timeframes, allow_holdout=req.holdout)
    except dataset_mod.HoldoutViolation as exc:
        raise BacktestRefused(str(exc)) from exc
    if req.holdout:
        holdout_entry = {
            "strategy": req.strategy_id,
            "run_date": req.run_date.isoformat(),
            "git_commit": commit,
            "config_hash": config_hash(settings),
            "data_hashes": ds.hashes,
            "holdout": [
                settings.backtest.holdout_start.isoformat(),
                settings.backtest.holdout_end.isoformat(),
            ],
            "rerun": rerun,
            "reason": req.rerun_reason,
        }
        register_holdout_run(settings, holdout_entry)  # before running: a crash still counts
    eval_floor = (
        datetime.combine(settings.backtest.holdout_start, datetime.min.time(), tzinfo=UTC)
        if req.holdout
        else None
    )
    maker = run_backtest(settings, ds, "maker", strategy_id=req.strategy_id)
    if eval_floor is not None:
        maker.eval_start = max(maker.eval_start, eval_floor)
    maker_block = _metrics(settings, maker, settings.fees.maker)
    # AD-4: raises LookAheadError before anything is written.
    guard = check_prefix_invariance(
        settings, start, end, timeframes, maker, strategy_id=req.strategy_id,
        allow_holdout=req.holdout,
    )  # fmt: skip
    # CON-06 report variant: same signals, filled at once at the aggressive side, taker fee.
    taker = run_backtest(settings, ds, "taker", strategy_id=req.strategy_id)
    if eval_floor is not None:
        taker.eval_start = max(taker.eval_start, eval_floor)
    taker_block = _metrics(
        settings, taker, settings.fees.taker, settings.execution.sim_half_spread_bps
    )
    runs = holdout_runs(settings, req.strategy_id)
    reruns = [r for r in runs if r.get("rerun")]
    payload: dict[str, Any] = {
        "label": "SIMULATED",
        "verdict": verdict(req.strategy_id, maker_block, taker_block),
        "strategy": req.strategy_id,
        "params": dict(settings.strategy.params),
        "warmup_candles": strategy.warmup,
        "change": req.change,
        "configurations_tried": 1,
        "code_version": {"git_commit": commit, "git_dirty": git_dirty()},
        "config_hash": config_hash(settings),
        "limits_hash": limits_hash(settings),
        "data": {
            "pair": ds.pair,
            "start": ds.start.isoformat(),
            "end_exclusive": ds.end.isoformat(),
            "hashes": ds.hashes,
        },
        "holdout": {
            "start": settings.backtest.holdout_start.isoformat(),
            "end": settings.backtest.holdout_end.isoformat(),
            "status": (
                "THIS IS THE HOLDOUT RUN (recorded in holdout_runs.jsonl)"
                if req.holdout
                else "excluded (not loaded, not run)"
            ),
            "runs_recorded": len(runs),
            "banner": (
                f"HOLDOUT RE-RUN WARNING: {req.strategy_id} has {len(runs)} holdout runs "
                f"recorded ({len(reruns)} re-run(s), first reason: {reruns[0].get('reason')!r}); "
                "holdout results are no longer a clean out-of-sample test."
                if reruns
                else None
            ),
        },
        "walk_forward": (
            []
            if req.holdout
            else walk_forward(
                maker, settings.backtest.walk_forward_fold_days, settings.backtest.holdout_start
            )
        ),
        "market_rules": maker.rules_snapshot,
        "fees": {
            "maker": str(settings.fees.maker),
            "taker": str(settings.fees.taker),
            "source": settings.fees.source,
        },
        "slippage_bps": str(settings.slippage_bps),
        "execution": {
            "window_hours": settings.execution.window_hours,
            "reprice_interval_minutes": settings.execution.reprice_interval_minutes,
            "sim_timeframe": settings.execution.sim_timeframe,
            "sim_half_spread_bps": str(settings.execution.sim_half_spread_bps),
            "tick_seconds": settings.execution.tick_seconds,
            "completion_window_hours": settings.execution.completion_window_hours,
            "fill_settle_timeout_seconds": settings.execution.fill_settle_timeout_seconds,
        },
        "lookahead_guard": {
            "passed": True,
            "cutpoints": list(guard.cutpoints),
            "candles_compared": guard.candles_compared,
            "seed": guard.seed,
        },
        "results": {"maker": maker_block, "taker": taker_block},
        "data_anomalies": anomaly_block(anomalies_in(ds), {"maker": maker, "taker": taker}),
        "caveats": caveats(settings),
    }
    stem = results_stem(req.run_date, req.strategy_id, commit)
    if req.holdout:
        stem += "_HOLDOUT"
    j, m = write_results(req.results_dir, stem, payload, render_markdown(payload))
    return j, m, payload


def print_err(msg: str) -> None:
    print(msg, file=sys.stderr)


__all__ = ["BacktestRefused", "BacktestRequest", "default_request", "execute"]
