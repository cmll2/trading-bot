---
title: 'Metrics report at maker and taker rates with verdict line'
type: feature
ticket: '8'
created: '2026-11-13'
status: in-review
baseline_revision: 'fa4f3f8'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** The results file holds only total returns; FR-14/CON-06 require every metric for strategy, buy-and-hold and cash at maker AND taker rates, a verdict first line (FR-19), a bootstrap Sharpe CI (FR-21) and provenance (FR-18, NFR-02), labelled SIMULATED.

**Approach:** `bot/backtest/metrics.py` (pure: total/annualized return, max drawdown, Sharpe ann. √365 rf 0, moving-block bootstrap CI, trades, round trips, turnover, fees, time in market; buy-and-hold with slippage + the variant's fee; cash), `bot/backtest/report.py` (verdict: beats only if higher at both rates; Markdown report with verdict line 1, SIMULATED line 3, provenance, both variant tables, anomalies with fills-on-day flag (audit M1 F-3), caveats), `bot/backtest/command.py` builds the payload (commit, dirty, config & limits hash, data range + hashes, holdout status, rules snapshot, fees, execution, guard, change 0, configurations tried 1). No wall-clock in content: same inputs → identical bytes.

## Boundaries & Constraints

**Always:** verdict line 1 says plainly when the strategy does not beat buy-and-hold after costs; every output labelled SIMULATED; no claim of future profit.

**Never:** load or report holdout data; touch protected files.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error Handling |
|---|---|---|---|
| known series | equity 100,110,99,121 | metrics equal hand computation | none |
| verdict | strategy < B&H at either rate | line 1 "does NOT beat buy-and-hold after costs" (+ which rate) | none |
| provenance | any run | commit (40 hex), dirty flag, config hash, data range + hashes, change, CI | none |
| determinism | same inputs twice | byte-identical JSON and MD | none |

</intent-contract>

## Code Map

- `bot/backtest/metrics.py`, `bot/backtest/report.py` (new), `bot/backtest/command.py` (payload), `tests/backtest/test_metrics_report.py` (new).

## Tasks & Acceptance

**Execution:**
- [x] files above.

**Acceptance Criteria:**
- Given a strategy that does not beat buy-and-hold after costs, when the report is written, then its first line says so.

## Implementation Notes

Implemented in the coordinator's main session. Bootstrap method: circular moving-block bootstrap of daily returns, 20-day blocks, 2000 resamples, seeded (config `backtest.bootstrap_*`), recorded in PROGRESS.

## Plan Change Log

## Review Triage Log

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
