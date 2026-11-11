---
type: epic
title: "M3 Paper broker, engine, risk manager: dry-run runs 48 hours unattended and survives a forced restart"
parent: initiative-trading-bot-v1
covers: ["R9", "R10", "R11", "R24", "R25", "R26", "R27", "R29", "R33", "R36", "R37", "R38", "R39", "R40", "R44", "R59", "R60", "R61", "R62", "R63", "R65", "R66", "R70", "R71", "R72"]
sources: []
companions: [docs/planning/architecture.md]
after: ["epic-m2-backtest"]
refined: true
risk: high
---

# M3 Paper broker, engine, risk manager: dry-run runs 48 hours unattended and survives a forced restart

## Description

Brief §9 M3. Wires the M2 engine for dry-run (PaperBroker against live Kraken prices, SystemClock, file store), and adds crash recovery, reconciliation, the kill switch and halts with their engine behaviour (AD-12), operator commands, approval mode, the full journal, health recording, the plumbing strategy and the backtest-vs-paper consistency test.

## Outcome

The operator sees the engine run in dry-run for 48 hours without intervention and resume cleanly after a forced restart (brief §9 M3).

## Requirements

Each line is the parent's line in the PRD's words (refined from the initiative's lines alone; operator unavailable). Stories cite these R ids in `covers` and PRD/AD ids in each criterion.

- R1 (parent R9, FR-09): A plumbing strategy trades on a short timeframe in dry-run, generating enough simulated orders to exercise order handling, restarts and the dashboard. It claims no edge.
- R2 (parent R10, FR-10): The system refuses to run the plumbing strategy in `live` mode. — this epic delivers: registry-level refusal; live-gate refusal is M6.
- R3 (parent R11, FR-11): The same strategy code and the same order logic run in all three modes; only the broker and the clock differ. — this epic delivers: dry-run wiring.
- R4 (parent R24, FR-24): The paper broker simulates fills against live prices using the same fee, minimum-order and slippage model as the backtester. — this epic delivers: paper fills against live prices.
- R5 (parent R25, FR-25): The paper broker's virtual balance persists so that dry-run survives restarts.
- R6 (parent R26, FR-26): The live broker uses client order IDs so that a retried request can never create a duplicate order. — this epic delivers: engine-side duplicate prevention with find_order.
- R7 (parent R27, FR-27): The live broker handles partial fills, rejections, timeouts and rate limits without losing or duplicating state. — this epic delivers: engine handling of partial fills, rejections, timeouts, rate limits via FakeBroker.
- R8 (parent R29, FR-29): At startup, in any mode with a broker, the system reconciles local state (balances, open orders) with the broker's state and stops if they disagree.
- R9 (parent R33, FR-33): Breaching the maximum daily loss or the maximum total drawdown from the starting balance halts trading until the operator resets it manually (reset mechanism: OD-10). — this epic delivers: halt behaviour and manual reset.
- R10 (parent R36, FR-36): The kill switch, triggered by a file on disk or by the dashboard button, stops all new orders immediately (scope for open orders and positions: OD-09).
- R11 (parent R37, FR-37): Every rejection, halt and kill-switch event is stored with its reason.
- R12 (parent R38, FR-38): The engine wakes at candle close, fetches data, computes the signal, runs risk checks, sends orders and records every step.
- R13 (parent R39, FR-39): All state (signals, orders, fills, equity snapshots, risk events, heartbeats, errors) is persisted crash-safely; a restarted process resumes cleanly, including mid-order.
- R14 (parent R40, FR-40): Every signal is journaled with its outcome (filled, not filled, rejected by risk, skipped by the operator); for signals not traded, the journal records what the trade would have returned. — this epic delivers: journal outcomes; counterfactual returns are M4.
- R15 (parent R44, FR-44): The engine supports two approval modes: autonomous trading within limits, and per-order operator approval before sending (choice for first live weeks: OD-05; approval channel: OD-13).
- R16 (parent R59, FR-59): Engine tests use a fake broker and a fake clock and cover restart mid-order, partial fills, duplicate-order prevention, API errors and stale data.
- R17 (parent R60, FR-60): A consistency test shows the backtest and the paper broker produce the same trades on the same recorded data (see BI-05).
- R18 (parent R61, FR-61): Each risk limit has a test that triggers it (GL-03). — this epic delivers: engine level.
- R19 (parent R62, FR-62): Kill-switch tests cover both the file and the dashboard trigger (GL-04). — this epic delivers: file and CLI triggers.
- R20 (parent R63, FR-63): A test proves the plumbing strategy cannot start in `live` mode (FR-10). — this epic delivers: registry level.
- R21 (parent R70, NFR-04): Reliability: dry-run runs 48 hours without intervention and survives a forced restart (M3); four weeks without unhandled errors or reconciliation mismatch (GL-01). — this epic delivers: 48-hour run.
- R22 (parent R71, NFR-05): Observability: heartbeats, errors, API latency, rate-limit events and data freshness are recorded continuously enough to populate FR-55.
- R23 (parent R72, NFR-06): Locality: everything runs on the operator's computer; no cloud services; no network listener beyond `127.0.0.1`. — this epic delivers: no listener.
- R24 (parent R65, FR-65): At the end of each milestone, a reviewer that did not write the code (a fresh session, a separate subagent, or BMAD's review step) runs the tests itself, reads the git history for deleted, skipped or weakened tests and for extra holdout runs, looks for look-ahead bias, missing costs and overfitting, and rates each result PASS, FAIL or INCONCLUSIVE. — this epic delivers: M3 audit.
- R25 (parent R66, FR-66): The operator sees the audit report (FR-65) before reviewing the milestone. — this epic delivers: M3 audit.

## Constraints

- Binding from the initiative: CON-01..CON-11, SAF-01..SAF-15, WR-01..WR-08 and architecture AD-1..AD-30.
- SAF-04: any story touching config.yaml `risk:`, bot/risk/ or tests/risk/ is marked PROTECTED and lands in a dedicated commit touching nothing else, only on the operator's explicit request.
- Brief §9: stop at the end of the milestone, summarize, list known limitations, and wait for the operator's review after the audit story.

## Done when

- `bot dry-run` ran 48 h unattended on this PC with heartbeats every tick, zero unhandled errors and zero reconciliation mismatches, evidence in PROGRESS.md
- A forced kill of the process mid-order followed by restart resumes with no duplicate order and no lost fill (engine test and live dry-run)
- Kill switch (file and CLI) and both halts cancel resting orders, keep the position and are stored with reasons; reset is CLI-only
- Backtest and paper broker produce identical trades on the same recorded candles and bid/ask
- Independent M3 audit report seen by the operator

## Boundaries

- Out: dashboard views (M4), `bot review` and ledger export (M4), KrakenBroker and live gate (M6).
- Touch point: bot/risk/ — kill_switch.py is added here under protection; checks.py/halts.py are owned by epic-m2-backtest.

## References

- parent — docs/stories/initiative-trading-bot-v1/initiative-trading-bot-v1.md, Requirements
- prd — docs/planning/prd.md, Milestones and acceptance criteria (M3)
- brief — first_brief.txt, §9 M3
- architecture — docs/planning/architecture.md, Capability to architecture map
- decisions — PROGRESS.md, Decisions log

## Notes

- Decision: 2026-11-11 — Tracer bullet: story 1 (`bot dry-run` v0 through the shared engine with heartbeats and journal). Next: restart recovery (least certain).
- Decision: 2026-11-11 — The 48-hour run (story 13) is this epic's closing end-to-end check and follows the refactor sweep so it runs on final code.
- Decision: 2026-11-11 (PROGRESS) — Kill switch/halt cancel resting orders and keep the position; `bot flatten` is manual; halt reset does not rebase unless `--rebase-baseline`.
- Decision: 2026-11-11 (PROGRESS) — Approval channel is the CLI (`bot approve` / `bot reject`).
- Assumption: dry-run uses no API key (architecture Q-10); fees come from config in dry-run.
- Waits on epic-m2-backtest because: brief §9 — one milestone at a time; the previous milestone must be accepted after its audit.
