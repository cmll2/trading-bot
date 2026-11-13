---
title: 'SQLite store schema v1 with derived position, cash and equity'
type: feature
ticket: '3'
created: '2026-11-13'
status: built
baseline_revision: '284838f'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** `store.py` is a stub; the engine (backtest now, paper/live later) needs the §2 schema with idempotency keys and balances derived from fills, never stored.

**Approach:** `bot/migrations/0001_init.sql` carries the architecture §2 DDL verbatim plus triggers that make `schema_meta` write-once and `equity_baselines`/`order_events`/`fills` append-only; `bot/store.py` opens file or `:memory:` stores with the pragmas, applies/version-checks migrations, exposes small insert/update/query helpers, write-once account init and derived position/cash/equity.

## Boundaries & Constraints

**Always:** Decimal in Python, decimal TEXT in SQL; ISO-8601 `Z` milliseconds timestamps; read-only open never creates a file.

**Never:** store mutable balances; touch protected files.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error Handling |
|---|---|---|---|
| new db | open(":memory:" or file) | all §2 tables, indexes, ledger view; schema_version 1 | none |
| version mismatch | code version differs | open fails | StoreError |
| duplicates | same signal_id / cl_ord_id / (exchange, trade id) / active halt rule / day-open day | refused | sqlite3.IntegrityError |
| write-once | overwrite initial_quote | refused | StoreError / IntegrityError |
| derived | initial 20 EUR, buy then sell fills | cash/position/equity equal hand computation | none |

</intent-contract>

## Code Map

- `bot/migrations/0001_init.sql` -- new; DDL from architecture §2.
- `bot/store.py` -- new implementation (was a stub).
- `tests/test_store.py` -- new.

## Tasks & Acceptance

**Execution:**
- [x] `bot/migrations/0001_init.sql`, `bot/store.py`, `tests/test_store.py`.

**Acceptance Criteria:**
- Given a hand-computed fill sequence, when cash/position/equity are requested, then they match exactly as Decimal.

## Implementation Notes

Implemented in the coordinator's main session. Added triggers beyond the §2 DDL to make write-once/append-only rules database-enforced (AD-26).

## Plan Change Log

## Review Triage Log

### 2026-11-13 — Review pass
- verdicts: 8 findings — high 0, medium 3, low 5, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` only one migration could ever work (schema_version blocked by the write-once trigger) — trigger now exempts `schema_version`; migrations UPDATE it after 0001.
  - `[medium]` `[patch]` failed COMMIT left a dangling transaction; failed ROLLBACK hid the error — COMMIT inside try, rollback on any failure, ROLLBACK errors suppressed; test with a deferred FK violation.
  - `[medium]` `[patch]` version read outside the write transaction; foreign SQLite files migrated in place — version read under BEGIN IMMEDIATE; a non-empty db without schema_meta is refused; test.
  - `[low]` `[patch]` `position(pair)` added initial_base for any pair — refused when it differs from `schema_meta.pair`; test.
  - `[low]` `[patch]` unknown fill side counted as sell — insert trigger + `_side` guard; test.
  - `[low]` `[patch]` WAL result ignored — open refuses a file store that is not in WAL.
  - `[low]` `[patch]` read-only guard could crash/misjudge — removed; `mode=ro` is the enforcement.
  - `[low]` `[patch]` missing tests for delete/order_events triggers and read-write version mismatch — added.

## Auto Run Result

- Summary: schema v1 migration (§2 DDL verbatim + write-once/append-only/side triggers), `Store` with pragmas, version-checked migrations, transactions, write-once account init, derived position/cash/equity.
- Files: `bot/migrations/0001_init.sql`, `bot/store.py`, `tests/test_store.py`.
- Review: 8 patches, 0 deferred, 0 rejected. Follow-up review recommended: true by the formula (3 medium patched) — named risk: the migration/transaction paths are only exercised by unit tests; the M2 audit should re-read `Store.transaction` and `_migrate`.
- Verification: store tests 25 passed; full check run at commit.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
