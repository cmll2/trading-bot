---
title: 'Kill switch and halts stop trading: cancel orders, keep position'
type: feature
ticket: '5'
created: '2026-11-14'
status: built
baseline_revision: '5a99592'
route: full
route_source: coordinator
risk: high
review: quick
review_source: batched review of stories 5-8
---

## Intent

AD-12 in the engine: every tick consumes operator actions, then snapshots the kill switch
and evaluates the halts BEFORE any submission; when engaged or halted, new intents and
submissions are blocked, the resting non-flatten order is cancelled in the same tick with
its final fills ingested, the active intent ends `halted` (outcome `halted`), the position
is kept (no automatic sell). The file is re-read just before every `place_order`.
`kill_on`/`kill_off` risk events are written once per observed state change. `bot kill on
--note` creates the file (`risk.kill_switch.engage`, source=cli) and records an action;
`bot kill off --note` only records an action; the engine deletes the file when it consumes it.

## Built

- bot/engine.py: tick order (actions -> stray-order sync -> halts/kill -> sweep -> flatten
  only while stopped -> advance -> signal -> snapshot); `_log_kill_state`;
  `_consume_actions` + `_action_kill_on/_action_kill_off`; `_place` re-reads the kill file
  (returns `blocked`, nothing persisted or sent); `_sync_stray_orders` keeps ingesting the
  final fills of an order whose intent a halt already ended.
- bot/cli.py: `bot kill on|off`, `reset-halt`, `flatten`, `approve`, `reject`, `journal`
  parsers (the last five are consumed by the engine in stories 6-8).
- bot/journal.py: read-only journal view (story 8 uses it).

## Verification

`tests/engine/test_kill_and_halts.py` (10): kill switch from a hand-made file, CLI-source and
dashboard-source files, daily-loss and total-drawdown halts: resting order cancelled in the
same tick, final fills ingested, outcome halted, position unchanged, no new order, risk event
once; halts never expire on a timer; re-read just before place_order blocks the submission;
kill off deletes the file only through the engine; CLI kill on/off.
