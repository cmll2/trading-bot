---
type: epic
title: "M2 Backtester and v0 strategy: one command produces an honest backtest report"
parent: initiative-trading-bot-v1
covers: ["R5", "R6", "R7", "R8", "R11", "R12", "R13", "R14", "R15", "R16", "R17", "R18", "R19", "R20", "R21", "R22", "R23", "R24", "R30", "R31", "R32", "R33", "R34", "R35", "R57", "R58", "R61", "R65", "R66", "R68", "R74", "R75"]
sources: []
companions: [docs/planning/architecture.md]
after: ["epic-m1-data"]
refined: true
risk: high
---

# M2 Backtester and v0 strategy: one command produces an honest backtest report

## Description

Brief §9 M2. Per AD-1 the backtest is the same engine as dry-run and live with PaperBroker, SimClock, ReplayMarketData and an in-memory store, so this epic builds the broker port, the store schema, the fill model, sizing, the pure risk checks (protected), the engine's execution path and the v0 strategy, then the report, look-ahead guard and holdout discipline.

## Outcome

The operator runs one command and gets a backtest report with metrics and benchmarks at maker and taker rates, and the look-ahead guard test passes (brief §9 M2).

## Requirements

Each line is the parent's line in the PRD's words (refined from the initiative's lines alone; operator unavailable). Stories cite these R ids in `covers` and PRD/AD ids in each criterion.

- R1 (parent R5, FR-05): A strategy receives candle history and returns a target position between 0 and 1.
- R2 (parent R6, FR-06): A strategy is a pure function of past data with explicit parameters; it has no access to the broker, the clock or the network.
- R3 (parent R7, FR-07): The v0 strategy is a slow trend filter, long or flat, on one pair (for example: long when price is above a long moving average, flat otherwise, on daily candles). Its parameters are fixed in configuration before any out-of-sample evaluation.
- R4 (parent R8, FR-08): Every strategy result is reported next to two benchmarks: buy-and-hold of the same pair, and holding cash.
- R5 (parent R11, FR-11): The same strategy code and the same order logic run in all three modes; only the broker and the clock differ. — this epic delivers: backtest wiring of the shared engine.
- R6 (parent R12, FR-12): The backtest is event-driven, candle by candle: a signal computed on candle *t* close executes at candle *t+1* open, with fees and slippage applied (CON-04).
- R7 (parent R13, FR-13): The backtest enforces minimum order size and precision exactly as the live broker would; an order below the minimum is rejected and logged, not silently rounded.
- R8 (parent R14, FR-14): One command produces a backtest report with total return, annualized return, max drawdown, Sharpe, number of trades, turnover, total fees paid and time in market, each compared with the benchmarks, at both maker and taker rates (CON-06).
- R9 (parent R15, FR-15): Walk-forward evaluation is supported, with a held-out final period (the most recent 12 months) that is never used for tuning.
- R10 (parent R16, FR-16): The holdout is run once per strategy, at the end, and its result is reported even if it kills the idea. Every holdout run is recorded with its date and git commit, so a second run is visible.
- R11 (parent R17, FR-17): Strategy changes are made one at a time, at most five per strategy, each logged in `changes.md` with its result and git commit.
- R12 (parent R18, FR-18): Every result is saved with the code version, configuration and data date range that produced it.
- R13 (parent R19, FR-19): When a strategy does not beat buy-and-hold after costs, the report says so in its first line.
- R14 (parent R20, FR-20): Every parameter search writes the number of configurations tried to the results file.
- R15 (parent R21, FR-21): Reports include a bootstrap confidence interval on the Sharpe ratio.
- R16 (parent R22, FR-22): A guard in the backtester catches look-ahead; a test that deliberately uses candle *t+1* data at *t* fails because of it.
- R17 (parent R23, FR-23): A single broker abstraction offers: get balance, get ticker, place order, cancel order, get open orders, get fills. It does not preclude a second exchange later. — this epic delivers: port, domain types, FakeBroker.
- R18 (parent R24, FR-24): The paper broker simulates fills against live prices using the same fee, minimum-order and slippage model as the backtester. — this epic delivers: shared fill model and PaperBroker.
- R19 (parent R30, FR-30): Every order passes pre-trade risk checks before reaching any broker. Limits are read from configuration (protected, SAF-04) and cannot be changed by the running system (SAF-05). — this epic delivers: pure check_order gate on every submission.
- R20 (parent R31, FR-31): An order is rejected if it would exceed the maximum position size, as a fraction of equity or as an absolute amount.
- R21 (parent R32, FR-32): An order is rejected if it would exceed the maximum number of orders per day.
- R22 (parent R33, FR-33): Breaching the maximum daily loss or the maximum total drawdown from the starting balance halts trading until the operator resets it manually (reset mechanism: OD-10). — this epic delivers: halt evaluation; engine halt behaviour is M3.
- R23 (parent R34, FR-34): No order is placed if the last candle or ticker is older than a configured threshold.
- R24 (parent R35, FR-35): An order is rejected if the price moved more than a configured threshold since the signal.
- R25 (parent R57, FR-57): Unit tests cover the strategy, sizing, fee and minimum-order logic, and every risk rule.
- R26 (parent R58, FR-58): Backtester tests run on synthetic price series with known outcomes.
- R27 (parent R61, FR-61): Each risk limit has a test that triggers it (GL-03). — this epic delivers: unit level.
- R28 (parent R68, NFR-02): Reproducibility: the same code version, configuration and data range produce the same backtest result. — this epic delivers: results carry code, config and data hash.
- R29 (parent R74, NFR-08): Cost realism: no simulated fill (backtest or dry-run) omits fees or slippage (CON-04).
- R30 (parent R75, NFR-09): Simulation labeling: every output derived from simulation (backtest, dry-run, paper fills) is labeled as simulated. — this epic delivers: reports labelled SIMULATED.
- R31 (parent R65, FR-65): At the end of each milestone, a reviewer that did not write the code (a fresh session, a separate subagent, or BMAD's review step) runs the tests itself, reads the git history for deleted, skipped or weakened tests and for extra holdout runs, looks for look-ahead bias, missing costs and overfitting, and rates each result PASS, FAIL or INCONCLUSIVE. — this epic delivers: M2 audit.
- R32 (parent R66, FR-66): The operator sees the audit report (FR-65) before reviewing the milestone. — this epic delivers: M2 audit.

## Constraints

- Binding from the initiative: CON-01..CON-11, SAF-01..SAF-15, WR-01..WR-08 and architecture AD-1..AD-30.
- SAF-04: any story touching config.yaml `risk:`, bot/risk/ or tests/risk/ is marked PROTECTED and lands in a dedicated commit touching nothing else, only on the operator's explicit request.
- Brief §9: stop at the end of the milestone, summarize, list known limitations, and wait for the operator's review after the audit story.

## Done when

- `bot backtest --strategy v0_trend` writes results/{date}_{strategy}_{commit}.json and a report whose first line is the verdict against buy-and-hold after costs
- tests/test_lookahead.py passes: a planted t+1 leak raises LookAheadError and no report is written
- Minimums and precision are enforced as live would; sub-minimum orders are rejected and logged, never rounded
- Every risk rule of AD-11 has a unit test that triggers it (protected tests)
- Independent M2 audit report seen by the operator

## Boundaries

- Out: dry-run wiring, restart recovery, reconciliation, kill switch file, operator CLI (M3).
- Out: KrakenBroker (M6). Out: holdout evaluation before the strategy is final (FR-16).

## References

- parent — docs/stories/initiative-trading-bot-v1/initiative-trading-bot-v1.md, Requirements
- prd — docs/planning/prd.md, Milestones and acceptance criteria (M2)
- brief — first_brief.txt, §9 M2
- architecture — docs/planning/architecture.md, Capability to architecture map
- decisions — PROGRESS.md, Decisions log

## Notes

- Decision: 2026-11-11 — Story 1 (broker port) and story 2 (protected risk core) precede the tracer: the tracer needs the port, and protected files cannot share a commit with it (SAF-04). Tracer bullet: story 4.
- Decision: 2026-11-11 — Pure risk checks are built in M2, not M3, because AD-1/AD-10 make every backtest submission pass check_order. Flag to operator at M2 kickoff (brief lists risk manager under M3).
- Decision: 2026-11-11 — The plumbing strategy is built in M3, where it is used (dry-run only).
- Source conflict: AD-5/Q-8 execution values (4 h window, 15 min re-price, max_reprices 8) vs PROGRESS.md (6 h, 30 min, 12 submissions per intent, 24/day). PROGRESS wins.
- Assumption: walk-forward fold sizes and bootstrap method are chosen in story 9 and recorded in PROGRESS.md (architecture Deferred).
- Waits on epic-m1-data because: brief §9 — one milestone at a time; the previous milestone must be accepted after its audit.
