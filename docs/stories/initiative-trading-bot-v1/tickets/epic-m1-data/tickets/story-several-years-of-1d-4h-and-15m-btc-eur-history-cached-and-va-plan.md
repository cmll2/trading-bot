---
title: 'Several years of 1d, 4h and 15m BTC/EUR history cached and validated'
type: feature
ticket: '6'
created: '2026-11-11'
status: blocked
baseline_revision: 'f2d877ac519f1af6c346aeab03fbd15c1f47350e'
route: oneshot
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
blocked_at: "2026-11-11"
blocked_reason: "Operator must download+import the full Kraken OHLCVT archive (~10 GB, docs/data-manifest.md); 15m also lacks 2026-10-01..2026-11-03 until Kraken publishes Q4 2026"
---

<intent-contract>

## Intent

**Problem:** The milestone needs several years of validated 1d, 4h and 15m BTC/EUR candles, with history depth, synthetic ratio and the 2013–2016 daily gap audit recorded in PROGRESS.md; the operator supplies the full archive (hitl), and no backtest may touch the holdout.

**Approach:** Add a read-only `bot data audit-gaps [--timeframe TF] [--start DATE] [--end DATE]` (defaults 1d, 2013-01-01, 2016-12-31) that lists every synthetic (no-trade) run in the window with start, end and length, and states plainly when the cache has no candles in the window (coverage first/last). Then run update → import-archive (Q3 2026 file downloaded per docs/data-manifest.md) → validate → audit-gaps on the real data and record the real output in PROGRESS.md. Where the full archive is required and absent, say so and block on the operator instead of claiming depth.

</intent-contract>

## Implementation Notes

Oneshot: about 60 lines (one pure function in `bot/data/validate.py`, one CLI subcommand, tests). No backtest or parameter search runs in this story (holdout untouched).

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
- `uv run bot data update; uv run bot data import-archive --zip data/raw/kraken_ohlcvt/Kraken_OHLCVT_2026Q3.zip --sha256 96daae63c7b3acb522892e1f602f9c564d1a3fb659089d9b0699282f30d41226; uv run bot data validate; uv run bot data audit-gaps` -- expected: real output recorded verbatim in PROGRESS.md

Files touched: `bot/data/validate.py` (`GapAudit`, `audit_gaps`), `bot/cli.py` (`bot data audit-gaps`), `tests/data/test_audit_gaps.py`. Decision: a window with no cached candles prints `NOT AUDITABLE` (exit 0) so an absent archive is never mistaken for "no gaps".

Real run 2026-11-11 (public endpoint + `Kraken_OHLCVT_2026Q3.zip`): 1d 719 rows 2024-11-22 → 2026-11-10 (92 archive, 627 api); 4h 802 rows 2026-07-01 → 2026-11-11 12:00 (552 archive, 250 api); 15m 720 api rows 2026-11-04 07:45 → 2026-11-11 19:30; overlap 92 (1d) / 552 (4h) rows, 0 ticks; 15m import refused: `download gap at 2026-10-01` (Q3 archive ends 2026-09-30, the 15m API window starts 2026-11-04); 0 synthetic rows; 2013–2016 audit NOT AUDITABLE (full archive not downloaded). "Several years" is not met without the operator-supplied full archive (hitl).

## Review Triage Log

### 2026-11-11 — Review pass
- verdicts: 8 findings — high 0, medium 4, low 4, false 0, maybe-false 0
- findings:
  - `[medium]` `[defer]` real-run results not yet in PROGRESS.md — written in the dedicated PROGRESS.md commit the coordinator requires (separate from code commits).
  - `[medium]` `[defer]` PROGRESS.md does not record the operator block — same PROGRESS.md commit.
  - `[medium]` `[intent_gap]` AC1 "several years" for 1d/4h/15m not met — needs the operator-downloaded full archive (hitl) and, for 15m, a source for 2026-10-01..2026-11-03 (no official file yet); ticket marked blocked.
  - `[medium]` `[patch]` partial window coverage not flagged — `PARTIAL COVERAGE - not examined …` lines; test added.
  - `[low]` `[patch]` runs crossing the window edge were clipped — full extent reported and marked; test updated (own uncommitted test).
  - `[low]` `[patch]` reversed window accepted — refused (exit 2 / ValueError); tests added.
  - `[low]` `[patch]` help text/default and duplicated dedupe for audit-gaps — fixed.
  - `[low]` `[patch]` OSError not caught in audit-gaps — caught as data error.

## Auto Run Result

- Summary: read-only `bot data audit-gaps` (synthetic runs, partial-coverage and NOT AUDITABLE reporting); real data run recorded above.
- Files: `bot/data/validate.py`, `bot/cli.py`, `tests/data/test_audit_gaps.py`.
- Verification: full check → 506 passed; real `bot data validate` exit 0 for 1d/4h/15m; real `bot data audit-gaps` output above.
- Status: blocked — operator must download and import the full Kraken OHLCVT archive (docs/data-manifest.md); 15m additionally has an unfillable official-data gap 2026-10-01..2026-11-03 until Kraken publishes Q4 2026.
