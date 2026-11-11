---
type: initiative
title: "Operator runs an audited, risk-limited Kraken spot bot from data to €20 live"
sources: [docs/planning/prd.md, first_brief.txt, PROGRESS.md]
companions: [docs/planning/architecture.md, docs/planning/ux-dashboard/EXPERIENCE.md, docs/planning/ux-dashboard/DESIGN.md, docs/research/build-vs-reuse-and-kraken.md, docs/research/pair-selection.md, docs/stories/index.md]
after: []
risk: high
---

# Operator runs an audited, risk-limited Kraken spot bot from data to €20 live

## Description

v1 of the custom trading bot (PROGRESS decision: Option A): data, backtest, simulated execution, monitoring, then live execution on about €20 with strict limits, built milestone by milestone M0 to M6 (brief §9). Profit is not the success criterion; correctness, observability and safety are (brief §1). Requirements are lifted one-to-one from the PRD; architecture decisions AD-1..AD-30 bind every epic.

## Outcome

The operator can run the bot live on €20 only after fixed go-live criteria are met, with every milestone accepted on an independent audit (PRD SM-1 to SM-4).

## Requirements

Initiative id R<n> maps to PRD ids as: R1–R66 = FR-01–FR-66, R67–R76 = NFR-01–NFR-10, R77–R82 = GL-01–GL-06.

- R1 (FR-01): The system downloads OHLCV candles for the configured pair and timeframe from Kraken (CON-01), handling pagination and rate limits.
- R2 (FR-02): Downloaded candles are cached locally and reused without re-downloading (brief specifies Parquet).
- R3 (FR-03): Candle data is validated for no gaps, no duplicates, monotonic timestamps and UTC timestamps; any violation is reported and the run fails. Bad data is never silently repaired.
- R4 (FR-04): Signals are computed only on closed candles.
- R5 (FR-05): A strategy receives candle history and returns a target position between 0 and 1.
- R6 (FR-06): A strategy is a pure function of past data with explicit parameters; it has no access to the broker, the clock or the network.
- R7 (FR-07): The v0 strategy is a slow trend filter, long or flat, on one pair (for example: long when price is above a long moving average, flat otherwise, on daily candles). Its parameters are fixed in configuration before any out-of-sample evaluation.
- R8 (FR-08): Every strategy result is reported next to two benchmarks: buy-and-hold of the same pair, and holding cash.
- R9 (FR-09): A plumbing strategy trades on a short timeframe in dry-run, generating enough simulated orders to exercise order handling, restarts and the dashboard. It claims no edge.
- R10 (FR-10): The system refuses to run the plumbing strategy in `live` mode.
- R11 (FR-11): The same strategy code and the same order logic run in all three modes; only the broker and the clock differ.
- R12 (FR-12): The backtest is event-driven, candle by candle: a signal computed on candle *t* close executes at candle *t+1* open, with fees and slippage applied (CON-04).
- R13 (FR-13): The backtest enforces minimum order size and precision exactly as the live broker would; an order below the minimum is rejected and logged, not silently rounded.
- R14 (FR-14): One command produces a backtest report with total return, annualized return, max drawdown, Sharpe, number of trades, turnover, total fees paid and time in market, each compared with the benchmarks, at both maker and taker rates (CON-06).
- R15 (FR-15): Walk-forward evaluation is supported, with a held-out final period (the most recent 12 months) that is never used for tuning.
- R16 (FR-16): The holdout is run once per strategy, at the end, and its result is reported even if it kills the idea. Every holdout run is recorded with its date and git commit, so a second run is visible.
- R17 (FR-17): Strategy changes are made one at a time, at most five per strategy, each logged in `changes.md` with its result and git commit.
- R18 (FR-18): Every result is saved with the code version, configuration and data date range that produced it.
- R19 (FR-19): When a strategy does not beat buy-and-hold after costs, the report says so in its first line.
- R20 (FR-20): Every parameter search writes the number of configurations tried to the results file.
- R21 (FR-21): Reports include a bootstrap confidence interval on the Sharpe ratio.
- R22 (FR-22): A guard in the backtester catches look-ahead; a test that deliberately uses candle *t+1* data at *t* fails because of it.
- R23 (FR-23): A single broker abstraction offers: get balance, get ticker, place order, cancel order, get open orders, get fills. It does not preclude a second exchange later.
- R24 (FR-24): The paper broker simulates fills against live prices using the same fee, minimum-order and slippage model as the backtester.
- R25 (FR-25): The paper broker's virtual balance persists so that dry-run survives restarts.
- R26 (FR-26): The live broker uses client order IDs so that a retried request can never create a duplicate order.
- R27 (FR-27): The live broker handles partial fills, rejections, timeouts and rate limits without losing or duplicating state.
- R28 (FR-28): At startup the system verifies the API key's permissions where the API allows it and refuses to start if withdrawals are enabled (SAF-07; fallback: OD-12).
- R29 (FR-29): At startup, in any mode with a broker, the system reconciles local state (balances, open orders) with the broker's state and stops if they disagree.
- R30 (FR-30): Every order passes pre-trade risk checks before reaching any broker. Limits are read from configuration (protected, SAF-04) and cannot be changed by the running system (SAF-05).
- R31 (FR-31): An order is rejected if it would exceed the maximum position size, as a fraction of equity or as an absolute amount.
- R32 (FR-32): An order is rejected if it would exceed the maximum number of orders per day.
- R33 (FR-33): Breaching the maximum daily loss or the maximum total drawdown from the starting balance halts trading until the operator resets it manually (reset mechanism: OD-10).
- R34 (FR-34): No order is placed if the last candle or ticker is older than a configured threshold.
- R35 (FR-35): An order is rejected if the price moved more than a configured threshold since the signal.
- R36 (FR-36): The kill switch, triggered by a file on disk or by the dashboard button, stops all new orders immediately (scope for open orders and positions: OD-09).
- R37 (FR-37): Every rejection, halt and kill-switch event is stored with its reason.
- R38 (FR-38): The engine wakes at candle close, fetches data, computes the signal, runs risk checks, sends orders and records every step.
- R39 (FR-39): All state (signals, orders, fills, equity snapshots, risk events, heartbeats, errors) is persisted crash-safely; a restarted process resumes cleanly, including mid-order.
- R40 (FR-40): Every signal is journaled with its outcome (filled, not filled, rejected by risk, skipped by the operator); for signals not traded, the journal records what the trade would have returned.
- R41 (FR-41): A weekly review compares realized results with what the backtest expected for the same period and is shown in the dashboard.
- R42 (FR-42): Once there are 20 or more trades, if the average result per trade is below half the backtest's, the strategy is flagged DECAYING (edge case: OD-15).
- R43 (FR-43): Structured logs are written to file with secrets redacted.
- R44 (FR-44): The engine supports two approval modes: autonomous trading within limits, and per-order operator approval before sending (choice for first live weeks: OD-05; approval channel: OD-13).
- R45 (FR-45): In `live` mode, startup requires both the CLI flag and the environment variable and shows the confirmation banner with account balance and active limits (SAF-09).
- R46 (FR-46): Every fill is recorded in the ledger with timestamp, amount, price, fee and quote currency, and the ledger exports to CSV (CON-09).
- R47 (FR-47): Fills that convert crypto to euros are marked, and the running total of crypto-to-euro sales for the calendar year is computed (CON-10).
- R48 (FR-48): The ledger and all FRs work for both EUR-quoted and stablecoin-quoted pairs (CON-11).
- R49 (FR-49): A local web dashboard reads the persisted store, auto-refreshes, binds to `127.0.0.1` only (SAF-15), and can take exactly one action: toggling the kill switch.
- R50 (FR-50): **Overview:** current mode shown prominently (DRY-RUN or LIVE), engine status and last heartbeat, equity, cash, open position, return since start, total fees paid, and an equity curve against buy-and-hold and cash.
- R51 (FR-51): **Signals and trades:** price chart with the strategy's indicator, entry and exit markers, and the current target position.
- R52 (FR-52): **Orders and fills:** table of orders with status; fills with price, fee and slippage versus the signal price; filterable by date.
- R53 (FR-53): **Risk:** each limit with its current usage, history of rejections and halts with reasons, kill switch state and button.
- R54 (FR-54): **Dry-run vs backtest:** for the same period, backtester-predicted equity versus paper-broker-recorded equity, with the difference per trade.
- R55 (FR-55): **Health:** recent errors, API latency, rate-limit events, data freshness, uptime.
- R56 (FR-56): **Ledger:** fills ledger with CSV export, including the calendar-year running total of crypto-to-euro sales.
- R57 (FR-57): Unit tests cover the strategy, sizing, fee and minimum-order logic, and every risk rule.
- R58 (FR-58): Backtester tests run on synthetic price series with known outcomes.
- R59 (FR-59): Engine tests use a fake broker and a fake clock and cover restart mid-order, partial fills, duplicate-order prevention, API errors and stale data.
- R60 (FR-60): A consistency test shows the backtest and the paper broker produce the same trades on the same recorded data (see BI-05).
- R61 (FR-61): Each risk limit has a test that triggers it (GL-03).
- R62 (FR-62): Kill-switch tests cover both the file and the dashboard trigger (GL-04).
- R63 (FR-63): A test proves the plumbing strategy cannot start in `live` mode (FR-10).
- R64 (FR-64): Never delete, skip or weaken a test to make the suite pass. If a test fails, fix the code or report the failure and stop.
- R65 (FR-65): At the end of each milestone, a reviewer that did not write the code (a fresh session, a separate subagent, or BMAD's review step) runs the tests itself, reads the git history for deleted, skipped or weakened tests and for extra holdout runs, looks for look-ahead bias, missing costs and overfitting, and rates each result PASS, FAIL or INCONCLUSIVE.
- R66 (FR-66): The operator sees the audit report (FR-65) before reviewing the milestone.
- R67 (NFR-01): Auditability: modules are small and readable over clever abstractions; the operator must be able to read the broker, risk and engine code in full (GL-05).
- R68 (NFR-02): Reproducibility: the same code version, configuration and data range produce the same backtest result.
- R69 (NFR-03): Time: all timestamps stored and compared in UTC.
- R70 (NFR-04): Reliability: dry-run runs 48 hours without intervention and survives a forced restart (M3); four weeks without unhandled errors or reconciliation mismatch (GL-01).
- R71 (NFR-05): Observability: heartbeats, errors, API latency, rate-limit events and data freshness are recorded continuously enough to populate FR-55.
- R72 (NFR-06): Locality: everything runs on the operator's computer; no cloud services; no network listener beyond `127.0.0.1`.
- R73 (NFR-07): Secret hygiene: no secret appears in logs, error messages, tracebacks, the store, the dashboard or the repository (SAF-01, SAF-02).
- R74 (NFR-08): Cost realism: no simulated fill (backtest or dry-run) omits fees or slippage (CON-04).
- R75 (NFR-09): Simulation labeling: every output derived from simulation (backtest, dry-run, paper fills) is labeled as simulated.
- R76 (NFR-10): Dependency hygiene: dependencies pinned by lockfile; no dependency outside brief §6 without operator approval (SAF-12 to SAF-14).
- R77 (GL-01): Four weeks of dry-run with no unhandled errors and no state mismatch on reconciliation.
- R78 (GL-02): Dry-run fills within a stated tolerance of backtest predictions over the same period. (Tolerance value: OD-08.)
- R79 (GL-03): Every risk limit triggered at least once in tests and seen working.
- R80 (GL-04): Kill switch tested from both the file and the dashboard.
- R81 (GL-05): I have read the code of the broker, risk and engine modules myself.
- R82 (GL-06): Go-live does not depend on the dry-run being profitable. If the strategy shows no edge after costs, that is a valid result and the decision to put €20 on it is mine.

## Constraints

Non-negotiable, verbatim from the PRD (brief §3, §4, §11). Architecture decisions AD-1 to AD-30 (docs/planning/architecture.md) bind all epics.

- (CON-01): **Exchange:** Kraken spot, via the `ccxt` library.
- (CON-02): **Capital:** about €20 live. Position sizing must respect Kraken's minimum order sizes (at the time of writing: €5 for EUR-quoted orders, 0.0001 BTC, 0.01 ETH).
- (CON-03): Read minimums, price precision and fee rates from the exchange's market metadata at startup. Do not hardcode them.
- (CON-04): **Fees:** every backtest and every dry-run fill must include fees taken from the exchange's fee schedule for my tier, plus a configurable slippage assumption.
- (CON-05): For reference, Kraken Pro's entry tier was 0.40% maker / 0.80% taker on spot crypto pairs when this brief was written (November 2026), so a round trip with market orders costs about 1.6% and with resting limit orders about 0.8%. Read the live rates from the API; treat these numbers only as a sanity check.
- (CON-06): Every backtest report must show results at both maker and taker rates.
- (CON-07): **Stablecoin pairs:** USDT is not available to EEA clients on Kraken. If a stablecoin-quoted pair is chosen, confirm which stablecoins are tradable from a French account and which fee schedule applies before building on it.
- (CON-08): **Trade frequency:** low. Fees make frequent trading unviable at this size, so strategies work on 4h or daily candles.
- (CON-09): **Tax bookkeeping (France):** keep a complete ledger of every fill, with timestamps, amounts, prices, fees and the quote currency, exportable to CSV.
- (CON-10): Mark separately the trades that convert crypto to euros, since those are the ones that count toward the annual disposal total.
- (CON-11): The choice between a EUR-quoted pair and a stablecoin-quoted pair is an open decision (section 13); the code must support both.
- (SAF-01): API keys live in a secrets file stored outside the repository folder; the repo holds only its path and a `.env.example` with empty values.
- (SAF-02): Never print, log, commit or ask me to paste a key into the chat, and never open or read the secrets file during development.
- (SAF-03): Kraken lets an API key be restricted to given IP addresses. If the machine running the bot has a stable IP, I will turn this on; remind me at M6.
- (SAF-04): **Protected files:** the risk limits in `config.yaml`, the `risk/` module and its tests may only be changed when I ask for it explicitly in the chat, in a commit that touches nothing else.
- (SAF-05): The running bot has no code path that can edit its own limits.
- (SAF-06): I will create the Kraken API key myself with query and trade permissions only. No withdrawal permission.
- (SAF-07): The bot should check the key's permissions at startup if the API allows it and refuse to start if withdrawals are enabled.
- (SAF-08): Three run modes: `backtest`, `dry-run`, `live`.
- (SAF-09): `live` requires both a CLI flag and an environment variable, and prints a confirmation banner with the account balance and the active limits.
- (SAF-10): During development, never place a real order.
- (SAF-11): Tests use a fake broker. Nothing in the test suite may touch the live trading endpoints.
- (SAF-12): Pin all dependencies with a lockfile.
- (SAF-13): Ask me before adding any dependency beyond those in section 6. (Brief §6 list: Python 3.11 or later, `uv` for environment and lockfile; `ccxt`, `pandas`, `pyarrow`, `pydantic`, `pyyaml`, `python-dotenv`; SQLite through the standard library or SQLAlchemy; `pytest`, `ruff`; Streamlit with Plotly charts for the dashboard, alternative only with a strong reason.)
- (SAF-14): Do not install third-party "trading skills", plugins or packages from unknown sources.
- (SAF-15): The dashboard binds to `127.0.0.1` only.
- (WR-01): Explain design choices briefly before implementing each milestone, and flag anything in this brief that looks wrong or unsafe.
- (WR-02): Prefer small, readable modules to clever abstractions. I need to be able to audit this.
- (WR-03): Never weaken a safety rule from section 4 to make something work. Stop and ask.
- (WR-04): State uncertainty plainly. If Kraken's API behaves differently from what this brief assumes, tell me and propose a change.
- (WR-05): Do not present backtest results as evidence that the strategy will make money.
- (WR-06): Never say that a process is running, a test passed or an order filled without having checked it in this session. Label anything simulated as simulated.
- (WR-07): Keep `PROGRESS.md` up to date with what is done, what is next, and every decision with its reason. Read it first in every new session.
- (WR-08): (from brief §8) Never delete, skip or weaken a test to make the suite pass. If a test fails, fix the code or report the failure and stop.

## Done when

- Every milestone M0 to M5 accepted by the operator with an independent audit report and no unresolved FAIL (SM-1)
- Over the M5 period, dry-run fills within 0.5% per fill and 2 pp equity of backtest predictions (SM-2, GL-02)
- Zero unhandled errors and zero reconciliation mismatches over four weeks of dry-run (SM-3, GL-01)
- Zero real orders placed during development and zero secrets exposed (SM-4)
- M6: go-live decided on GL-01..GL-06 and, if go, the bot runs live on €20 with manual approval

## Boundaries

- Out: LLM in the decision loop, leverage/margin/shorting/derivatives, market making, arbitrage, HFT, prediction markets, multi-exchange, cloud (brief §2).
- Out for v1: more strategies and pairs, notifications, always-on host (brief §12).
- Touch point: Kraken public and private API via ccxt — consumed only; owner: epic-m1-data (public OHLCV), epic-m3-paper-engine-risk (public ticker), epic-m6-live (private).
- Touch point: Windows Task Scheduler on this PC — configured only; owner: epic-m3-paper-engine-risk.
- Tracer path: cached candles (M1) → shared engine backtest (M2) → same engine in dry-run with risk and recovery (M3) → read-only dashboard (M4) → four reviewed weeks (M5) → gated live (M6).

## References

- prd — docs/planning/prd.md, Non-negotiable requirements, Functional requirements, Non-functional requirements, Milestones
- brief — first_brief.txt, §9 Milestones, §10 Go-live criteria, §14 If using BMAD
- decisions — PROGRESS.md, Decisions log (authoritative)
- architecture — docs/planning/architecture.md, §1, §2, AD-1..AD-30, Capability to architecture map
- design — docs/planning/ux-dashboard/EXPERIENCE.md, docs/planning/ux-dashboard/DESIGN.md
- index — docs/stories/index.md

## Notes

- Decision: 2026-11-11 — Epics map one-to-one onto milestones M0–M6 (brief §14 step 4, operator instruction). Each epic ends with an independent audit story (brief §8).
- Decision: 2026-11-11 — Stories touching protected paths (config.yaml `risk:`, bot/risk/, tests/risk/) say so and require a dedicated commit touching nothing else (SAF-04).
- Decision: 2026-11-11 — Slice produced headless; tree validation run inline (no subagent spawned); no git commit made in this run (operator instruction). Operator approval of the slice is pending.
- Assumption: Python 3.12 uv-managed interpreter satisfies brief "Python 3.11 or later".
- Open question: Pure risk checks pulled into M2 (AD-1/AD-10) and KrakenBroker placed in M6 — operator to confirm at the M2 and M6 kickoffs.
- Source conflict: architecture AD-5/Q-8 execution values vs PROGRESS.md (6 h window, 30 min re-price, 12 submissions per intent, 24/day) — PROGRESS wins.
- Source conflict: UX AS-UX-04 (disposal year UTC) vs PROGRESS (Europe/Paris) — PROGRESS wins.
