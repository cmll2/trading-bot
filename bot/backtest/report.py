"""Backtest results payload and Markdown report (FR-14, FR-18..FR-21, CON-06, NFR-09, AD-21).

Line 1 of the report is the verdict against buy-and-hold AFTER COSTS, at both fee rates
(FR-19): the strategy "beats" buy-and-hold only if its total return is higher at the
maker AND at the taker rate. Line 3 labels the whole report SIMULATED and states that a
backtest is not evidence of future profit (WR-05, NFR-09).
"""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from typing import Any

from bot.backtest.metrics import Metrics
from bot.backtest.runner import RunResult

SIMULATED_LINE = (
    "SIMULATED BACKTEST - these are simulated results on historical data; they are not "
    "evidence that the strategy will make money."
)


def variant_block(
    run: RunResult, strategy: Metrics, buy_hold: Metrics, cash: Metrics
) -> dict[str, Any]:
    return {
        "strategy": strategy.as_dict(),
        "buy_and_hold": buy_hold.as_dict(),
        "cash": cash.as_dict(),
        "signal_outcomes": dict(sorted(Counter(str(s["outcome"]) for s in run.signals).items())),
        "order_states": dict(sorted(run.order_outcomes.items())),
        "orders_submitted": run.orders_submitted,
        "risk_events": dict(
            sorted(Counter(f"{e['kind']}:{e['rule']}" for e in run.risk_events).items())
        ),
        "halted": run.halted,
        "halt_reason": run.halt_reason,
    }


def verdict(strategy_id: str, maker: dict[str, Any], taker: dict[str, Any]) -> dict[str, Any]:
    sm, bm = maker["strategy"]["total_return"], maker["buy_and_hold"]["total_return"]
    st, bt = taker["strategy"]["total_return"], taker["buy_and_hold"]["total_return"]
    beats_maker, beats_taker = sm > bm, st > bt
    beats = beats_maker and beats_taker
    span = f"{maker['strategy']['start'][:10]}..{maker['strategy']['end'][:10]}"
    detail = (
        f"total return {sm:+.1%} vs buy-and-hold {bm:+.1%} at maker fees, "
        f"{st:+.1%} vs {bt:+.1%} at taker fees ({span})"
    )
    if beats:
        line = (
            f"VERDICT (SIMULATED): {strategy_id} beats buy-and-hold after costs in this "
            f"backtest: {detail}. This is not evidence of future profit."
        )
    else:
        where = (
            "at both maker and taker fees"
            if not beats_maker and not beats_taker
            else ("at maker fees" if not beats_maker else "at taker fees")
        )
        line = (
            f"VERDICT (SIMULATED): {strategy_id} does NOT beat buy-and-hold after costs "
            f"({where}): {detail}."
        )
    return {
        "beats_buy_and_hold_after_costs": beats,
        "beats_at_maker": beats_maker,
        "beats_at_taker": beats_taker,
        "line": line,
    }


def anomaly_block(anomalies: list[dict[str, str]], runs: dict[str, RunResult]) -> list[dict]:
    """Known data anomalies in range, with any simulated fill on that day or the next
    flagged (F-3): a daily signal reads a candle at its close, so orders driven by the bad
    print fill on the following day."""
    out = []
    for a in anomalies:
        day = date.fromisoformat(a["date"])
        days = (day.isoformat(), (day + timedelta(days=1)).isoformat())
        fills = {v: [f for f in r.fills if str(f["at"])[:10] in days] for v, r in runs.items()}
        out.append(
            {
                **a,
                "fills_on_day": {v: len(fs) for v, fs in fills.items()},
                "flag": "FILL SIMULATED ON THIS DAY" if any(fills.values()) else "no fill",
            }
        )
    return out


def _pct(x: float) -> str:
    return f"{x:+.2%}"


def _row(name: str, key: str, block: dict[str, Any], fmt) -> str:  # noqa: ANN001
    cols = [fmt(block[k][key]) for k in ("strategy", "buy_and_hold", "cash")]
    return f"| {name} | " + " | ".join(cols) + " |"


def _table(block: dict[str, Any]) -> list[str]:
    def ci(v: list[float]) -> str:
        return f"[{v[0]:.2f}, {v[1]:.2f}]"

    return [
        "| Metric | Strategy | Buy-and-hold | Cash |",
        "|---|---|---|---|",
        _row("Total return", "total_return", block, _pct),
        _row("Annualized return", "annualized_return", block, _pct),
        _row("Max drawdown", "max_drawdown", block, lambda v: f"{v:.2%}"),
        _row("Sharpe (daily, ann.)", "sharpe", block, lambda v: f"{v:.2f}"),
        _row("Sharpe 95% CI (bootstrap)", "sharpe_ci_95", block, ci),
        _row("Trades (fills)", "trades", block, str),
        _row("Round trips", "round_trips", block, str),
        _row("Turnover (x mean equity)", "turnover", block, lambda v: f"{v:.2f}"),
        _row("Total fees (EUR)", "total_fees", block, lambda v: f"{v:.2f}"),
        _row("Time in market", "time_in_market", block, lambda v: f"{v:.1%}"),
        _row("Final equity (EUR)", "final_equity", block, lambda v: f"{v:.2f}"),
    ]


def render_markdown(p: dict[str, Any]) -> str:
    lines = [p["verdict"]["line"], "", SIMULATED_LINE, ""]
    if p["holdout"].get("banner"):
        lines += [f"**{p['holdout']['banner']}**", ""]
    lines += [
        f"# Backtest report: {p['strategy']} (change {p['change']})",
        "",
        "## Provenance",
        "",
        f"- Code version: `{p['code_version']['git_commit']}`"
        + (" (DIRTY working tree)" if p["code_version"]["git_dirty"] else ""),
        f"- Config hash: `{p['config_hash']}`; limits hash: `{p['limits_hash']}`",
        f"- Parameters: `{p['params']}`; configurations tried: {p['configurations_tried']}",
        f"- Data: {p['data']['pair']} {p['data']['start'][:10]} to "
        f"{p['data']['end_exclusive'][:10]} (exclusive); hashes "
        + ", ".join(f"{tf} `{h[:16]}`" for tf, h in sorted(p["data"]["hashes"].items())),
        f"- Evaluation window (after a {p['warmup_candles']}-candle warm-up): "
        f"{p['results']['maker']['strategy']['start'][:10]} to "
        f"{p['results']['maker']['strategy']['end'][:10]}",
        f"- Holdout {p['holdout']['start']}..{p['holdout']['end']}: {p['holdout']['status']}"
        f"; holdout runs recorded for this strategy: {p['holdout']['runs_recorded']}",
        f"- Fees: maker {p['fees']['maker']}, taker {p['fees']['taker']} "
        f"({p['fees']['source']}); slippage {p['slippage_bps']} bp",
        f"- Exchange rules: public market snapshot fetched {p['market_rules']['fetched_at']} "
        f"(amount_min {p['market_rules']['amount_min']} BTC, cost_min "
        f"{p['market_rules']['cost_min']} EUR, tick {p['market_rules']['tick_size']})",
        f"- Look-ahead guard: {'PASSED' if p['lookahead_guard']['passed'] else 'FAILED'} "
        f"({len(p['lookahead_guard']['cutpoints'])} cutpoints x 2 futures, "
        f"{p['lookahead_guard']['candles_compared']} candle targets compared, seed "
        f"{p['lookahead_guard']['seed']})",
        "",
    ]
    titles = {
        "maker": "maker fees (post-only limit orders, as built)",
        "taker": "taker fees (fill at once at ask/bid, CON-06 variant)",
    }
    for variant, title in titles.items():
        b = p["results"][variant]
        lines += [f"## Results at {title}", "", *_table(b), ""]
        lines += [
            f"- Signal outcomes: {b['signal_outcomes']}",
            f"- Orders submitted: {b['orders_submitted']} ({b['order_states']})",
            f"- Risk events: {b['risk_events'] or 'none'}",
            f"- Halted: {b['halted']}" + (f" ({b['halt_reason']})" if b["halt_reason"] else ""),
            "",
        ]
    if p.get("walk_forward"):
        lines += ["## Walk-forward folds (out-of-sample, pre-holdout, maker fees)", ""]
        lines += [
            "| Fold | From | To | Strategy | Buy-and-hold | Strategy max DD | Fills |",
            "|---|---|---|---|---|---|---|",
        ]
        for i, f in enumerate(p["walk_forward"], 1):
            lines.append(
                f"| {i} | {f['start'][:10]} | {f['end'][:10]} | {_pct(f['strategy_return'])} "
                f"| {_pct(f['buy_and_hold_return'])} | {f['strategy_max_drawdown']:.2%} "
                f"| {f['fills']} |"
            )
        lines.append("")
    lines += ["## Data anomalies", ""]
    if p["data_anomalies"]:
        for a in p["data_anomalies"]:
            lines.append(f"- {a['date']}: {a['note']} -> {a['flag']} {a['fills_on_day']}")
    else:
        lines.append("- none in range")
    lines += ["", "## Caveats", ""] + [f"- {c}" for c in p["caveats"]] + [""]
    return "\n".join(lines)
