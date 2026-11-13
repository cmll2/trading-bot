---
title: 'Walk-forward, holdout registry and change limit'
type: feature
ticket: '9'
created: '2026-11-13'
status: in-review
baseline_revision: '74ac2db'
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

**Problem:** Nothing yet records holdout runs, refuses tuning on the holdout, limits strategy changes, counts trials or reports walk-forward folds (FR-15..FR-17, FR-20).

**Approach:** `bot/backtest/holdout.py`: `check_tuning_range` (also enforced in `load_dataset`), committed registry `results/holdout_runs.jsonl` appended BEFORE the run (date, commit, config hash, data hashes, rerun, reason), refusal on a dirty tree or an existing line unless `--rerun-holdout --reason` (later reports get a banner), `check_change` (N > 5 refused; N ≥ 1 needs `## Change N` in `changes.md`), walk-forward = consecutive `walk_forward_fold_days` out-of-sample folds of the pre-holdout evaluation (1 configuration: nothing to fit). `bot/backtest/search.py` refuses holdout ranges and writes `configurations_tried`. CLI: `--holdout`, `--rerun-holdout`, `--reason`, `--change`. `changes.md` created. Coordinator decision: the real holdout is NOT run in M2; tests use synthetic data, synthetic holdout dates and temp results dirs.

## Boundaries & Constraints

**Always:** default `bot backtest` excludes the holdout; registry is append-only and committed.

**Never:** run the real holdout; touch protected files.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error Handling |
|---|---|---|---|
| tuning on holdout | search / range ending after 2025-11-11 | refused naming the boundary | HoldoutViolation |
| first holdout run | clean tree, no line | line appended before run; `_HOLDOUT` results; evaluation from holdout_start | none |
| second run | existing line, no flag | refused | exit 2 |
| rerun | `--rerun-holdout --reason` | line `rerun: true`; later reports banner | none |
| dirty tree | holdout requested | refused, nothing recorded | exit 2 |
| change | 6, or 1 without entry | refused | exit 2 |
| search | grid of 2 | results file `configurations_tried: 2` | none |

</intent-contract>

## Code Map

- `bot/backtest/holdout.py`, `bot/backtest/search.py` (new); `bot/backtest/command.py`, `bot/backtest/report.py`, `bot/backtest/lookahead.py` (`allow_holdout`), `bot/cli.py` (flags); `changes.md`; `tests/backtest/test_holdout.py`.

## Tasks & Acceptance

**Execution:**
- [x] files above.

**Acceptance Criteria:**
- Given an existing holdout line or a dirty tree, when a holdout run is requested, then it is refused unless `--rerun-holdout --reason` is given (dirty: always refused).

## Implementation Notes

Implemented in the coordinator's main session; committed together with story 8 review fixes (shared files).

## Plan Change Log

## Review Triage Log

## Verification

**Commands:**
- `uv run pytest tests/backtest/test_holdout.py` -- expected: pass
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
