---
title: 'Refactor sweep'
type: refactor
ticket: '7'
created: '2026-11-12'
status: built
baseline_revision: '75d6e65e73a337fe59937593757795c7c0cba490'
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

**Problem:** Cleanup items the M1 stories noted but left out of scope; nothing may change behaviour, test assertions or protected files.

**Approach:** Apply only the listed items. Sweep scope list (each maps to a recorded finding):
1. Story 5 Implementation Notes / report: `bot/strategy/v0_trend.py` and `bot/strategy/plumbing.py` still type `history` as `object` while the Strategy protocol now uses `CandleHistory` — change the annotations only.
2. Story 6: `bot/data/__init__.py` module docstring lacks the `audit-gaps` command and `bot/candles.py` cross-reference — docstring only.

Out of sweep (would be new behaviour or new stories): 15m gap source (trades rebuild), `load_markets` retry, full-archive import.

</intent-contract>

## Implementation Notes

Oneshot: under 15 lines, annotations and docstrings only.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass, same test count as before (506)

## Review Triage Log

### 2026-11-12 — Review pass
- verdicts: 0 findings — high 0, medium 0, low 0, false 0, maybe-false 0

## Auto Run Result

- Summary: strategy stub annotations now `CandleHistory`; `bot/data/__init__.py` docstring lists `audit-gaps` and the closed-candle view. No behaviour change.
- Verification: full check → 506 passed (unchanged count). Review: 0 findings; follow-up review recommended: false.
