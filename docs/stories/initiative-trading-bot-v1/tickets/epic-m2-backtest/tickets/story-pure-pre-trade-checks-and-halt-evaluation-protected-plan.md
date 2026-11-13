---
title: 'Pure pre-trade checks and halt evaluation (protected)'
type: feature
ticket: '2'
created: '2026-11-13'
status: built
baseline_revision: '8f212f5'
route: full
route_source: auto
risk: high
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

**Problem:** `check_order` and `evaluate_halts` are M0 stubs; every backtest (and later paper/live) submission must pass a pure pre-trade gate implementing AD-11 exactly.

**Approach:** Implement `ProposedOrder`, `RiskContext`, `check_order` (first failing rule rejects, with rule + reason) and `HaltContext`/`HaltTrigger`/`evaluate_halts` as pure functions; tests in `tests/risk/` trigger and pass every rule with the real config values. Operator explicitly approved building this protected story in M2 (coordinator brief, PROGRESS 2026-11-11 M0 review).

## Boundaries & Constraints

**Always:** SAF-04 dedicated commit touching only `bot/risk/**` and `tests/risk/**`; no limit VALUE changes; no I/O, no clock in checks/halts; Decimal arithmetic; every rejection has a reason (FR-37).

**Never:** change `limits.py`, `kill_switch.py` behaviour or config.yaml; read the kill-switch file here (the engine passes `kill_switch_engaged`).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error Handling |
|---|---|---|---|
| max_position | buy with (pos + resting + qty) x price > min(1.0 x equity, 25) | reject `max_position`; sells never | none |
| orders/day | attempt 1, intents_today >= 20 | reject `max_orders_per_day`; flatten and re-prices exempt | none |
| submissions | today >= 120 or intent >= 12 | reject `max_submissions`, flatten included | none |
| halts | equity <= 90% day-open / <= 75% baseline | `daily_loss` / `total_drawdown` triggers | stateless |
| stale | candle age > 2 intervals or synthetic; ticker > 120 s | `stale_candle` (flatten exempt) / `stale_ticker` (applies) | none |
| price sanity | abs(mid-ref)/ref > 2% | `price_sanity`, flatten included | none |
| kill/halt/status/minimums | engaged / active halt / not online / below min | `kill_switch`,`halt` (flatten exempt); `market_status`,`minimums` (apply) | none |

</intent-contract>

## Code Map

- `bot/risk/checks.py`, `bot/risk/halts.py`, `bot/risk/__init__.py` (docstring) -- implementation.
- `tests/risk/test_checks.py`, `tests/risk/test_halts.py` -- new tests reading real `config.yaml` limits.
- Interpretation recorded: candle age = now − open_at of latest closed candle; stale when > `stale_candle_intervals` × interval (for 1d: a missed daily close makes it stale).

## Tasks & Acceptance

**Execution:**
- [x] `bot/risk/checks.py` -- check_order per AD-11.
- [x] `bot/risk/halts.py` -- evaluate_halts per AD-11.
- [x] `tests/risk/*` -- one trigger + one pass per rule; purity AST test.

**Acceptance Criteria:**
- Given each AD-11 rule, when its threshold is crossed, then check_order/evaluate_halts reports that rule with a reason, and at the boundary it passes.

## Implementation Notes

Implemented in the coordinator's main session. Commit split: protected code+tests in one commit (SAF-04); this plan file in a separate docs commit.

## Plan Change Log

## Review Triage Log

### 2026-11-13 — Review pass
- verdicts: 4 findings — high 0, medium 1, low 3, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` a flatten buy got the kill-switch/halt exemptions — `invalid_order` now rejects any flatten that is not a sell; test added.
  - `[low]` `[patch]` `attempt_no` < 1 skipped the intent cap — rejected as `invalid_order`; test added.
  - `[low]` `[patch]` minimums boundary not tested — exact amount_min and cost_min pass tests added.
  - `[low]` `[patch]` purity test was a denylist — now an import allowlist (dataclasses, datetime, decimal, typing, bot.risk.limits) plus open/exec/eval/__import__/getattr call ban.

## Auto Run Result

- Summary: pure `check_order` (invalid_order, kill_switch, halt, market_status, minimums, max_orders_per_day, max_submissions, stale_candle, stale_ticker, price_sanity, max_position) and `evaluate_halts` (daily_loss, total_drawdown).
- Files: `bot/risk/checks.py`, `bot/risk/halts.py`, `bot/risk/__init__.py`, `tests/risk/test_checks.py`, `tests/risk/test_halts.py` — protected commit b140a9b, touching nothing else; no limit value changed.
- Review: 4 patches, 0 deferred, 0 rejected. Follow-up review recommended: false (one medium patched; covered by a new test).
- Verification: full check → 675 passed.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
