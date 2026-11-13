---
title: 'Refactor sweep'
type: refactor
ticket: '10'
created: '2026-11-13'
status: built
baseline_revision: '8d7cfa4'
route: oneshot
route_source: auto
risk: low
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

**Problem:** M2 left docstring drift (modules still described as M0/M3 stubs) and dead helpers; nothing may change behaviour, test assertions or protected files.

**Approach:** Apply only this sweep scope list (each item from the M2 story plans/reviews):
1. `bot/backtest/__init__.py` docstring lists "planned" modules — list the real ones (story 4-9 plans).
2. `bot/broker/__init__.py`, `bot/broker/base.py` describe base/paper as M0/M3 — M2 (story 1, 4).
3. `bot/cli.py` docstring says backtest is a stub — document the M2 command (story 4, 5, 9).
4. `bot/data/market.py` docstring says tickers arrive at M3 — from_frames / Broker port (story 5 review).
5. `bot/backtest/command.py` unused `EXIT_*` constants and `print_err` (left from story 4) — removed.

Out of sweep (behaviour): none deferred; every review finding was patched in its story.

</intent-contract>

## Implementation Notes

Oneshot: 22 lines added / 16 removed, docstrings and dead code only.

## Plan Change Log

## Review Triage Log

### 2026-11-13 — Review pass
- verdicts: 2 findings — high 0, medium 0, low 2, false 0, maybe-false 0
- findings:
  - `[low]` `[patch]` cli docstring still called backtest a stub — rewritten as M0 history + M2 state.
  - `[low]` `[patch]` compare module milestone said M3/M4 — M4/M5 (stories 5.7, 6.2-6.4).

## Auto Run Result

- Summary: docstrings and dead helpers only; no behaviour change (781 tests before and after).
- Review: 2 patches. Follow-up review recommended: false.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass, unchanged test count
