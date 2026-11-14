---
title: 'Refactor sweep'
type: refactor
ticket: '12'
created: '2026-11-14'
status: built
baseline_revision: '814da3c'
route: oneshot
route_source: coordinator
risk: low
review: none
review_source: cleanup only; full suite is the check
---

## Sweep scope (listed before the sweep)

Deferred cleanups noticed while building and reviewing stories 1-11:

1. `bot/engine.py`: the same `INSERT INTO halts ... ON CONFLICT DO NOTHING` statement was
   written five times (`_evaluate_halts`, `raise_halt`, `reconcile`, `_ingest_fills`,
   `_settle_overdue`) -> one `_insert_halt` helper returning whether the row is new. Risk
   event writes are untouched (each call site keeps its own semantics: `_evaluate_halts`
   writes a risk event only for a new halt, the others on every call, as before).
2. `bot/runtime.py`: `import json` inside `StoreRecorder.__call__` -> module import; unused
   `DryRun.extra` field removed.

Out of scope: protected paths; anything changing behaviour or a test assertion.

## Verification

No test changed. `uv run ruff check . && uv run ruff format --check . && uv run pytest`:
958 passed.
