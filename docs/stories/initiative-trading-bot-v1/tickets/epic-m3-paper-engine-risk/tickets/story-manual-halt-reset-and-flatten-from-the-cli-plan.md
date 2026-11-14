---
title: 'Manual halt reset and flatten from the CLI'
type: feature
ticket: '6'
created: '2026-11-14'
status: built
baseline_revision: '35f411e'
route: full
route_source: coordinator
risk: high
review: quick
review_source: batched review of stories 5-8
---

## Intent

`bot reset-halt <rule|all> --note [--rebase-baseline]` and `bot flatten --note` only insert
`operator_actions`; the engine consumes them (startup for `reset_halt`, AD-8 step 2; every
tick for all kinds). Halts never expire; a reset reuses the backtest's reset path
(`_apply_reset`, shared with `Engine.reset_halts`, one writer of `halts`); the drawdown
baseline moves only with `--rebase-baseline` (CLI asks to type `REBASE`; refused for rules
other than `total_drawdown`/`all`), and the new `equity_baselines` row carries the action id.
Flatten cancels any active intent (`skipped_by_operator`) and opens an `is_flatten` sell of the
full base, reference = mid now, window = execution window; exempt from orders/day,
stale_candle, halt and kill switch, not from stale_ticker, price_sanity or minimums (the
protected `check_order` already encodes this from `ProposedOrder.is_flatten`).

## Built

- bot/engine.py: `_action_reset_halt`, `_action_flatten`, `_apply_reset`; `_resubmit` sizes a
  flatten as the full base and passes `is_flatten` to the risk check; a handler returning
  None leaves the action pending (retried next tick).
- bot/cli.py: typed confirmation for `--rebase-baseline` (alias `--rebase`).

## Verification

`tests/engine/test_reset_and_flatten.py` (16): daily-loss halt stays until reset, no rebase;
total-drawdown rebase appends a baseline with the action id; rebase ignored for daily loss;
inactive rule reset changes nothing; pending reset applied at startup; flatten while halted
AND killed sells the full base; flatten waits for a fresh ticker; flatten cancels the active
intent (`skipped_by_operator`); flatten with no position is a no-op; every CLI command writes
only `operator_actions`; rebase needs the typed confirmation; rebase refused for other rules.
