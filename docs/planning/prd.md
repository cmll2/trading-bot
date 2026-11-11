---
title: "PRD: small-capital Kraken spot trading bot with dry-run dashboard"
template: prd
version: 1.1.0
status: draft
created: "2026-11-11"
updated: "2026-11-11"
source: first_brief.txt
altitude: initiative
stakes: personal use, real money (about €20 live)
---

# PRD: small-capital Kraken spot trading bot with dry-run dashboard

## Table of Contents

- [Document purpose](#document-purpose): reader, source, conventions, status
- [Vision](#vision): v1 goal, success = correctness, observability, safety
- [Users](#users): single operator
- [Glossary](#glossary): modes, target position, holdout, halt, kill switch, disposal
- [Non-negotiable requirements](#non-negotiable-requirements): CON-01 to CON-11, SAF-01 to SAF-15, GL-01 to GL-06
- [Functional requirements](#functional-requirements): FR-01 to FR-66 (data, strategy, backtest, broker, risk, engine, ledger, dashboard, testing)
- [Non-functional requirements](#non-functional-requirements): NFR-01 to NFR-10
- [Non-goals](#non-goals): no LLM, no leverage, no HFT, no cloud
- [Milestones and acceptance criteria](#milestones-and-acceptance-criteria): M0 to M6
- [Success metrics](#success-metrics): SM-1 to SM-4
- [Working rules for the developer agent](#working-rules-for-the-developer-agent): WR-01 to WR-08
- [Open decisions](#open-decisions): OD-01 to OD-07 (brief §13), OD-08 to OD-19 (raised by this PRD)
- [Brief issues found](#brief-issues-found): BI-01 to BI-10
- [Assumptions](#assumptions): AS-01 to AS-04

## Document purpose

- **Reader:** the operator (owner of the account and the money), the BMAD architect, product owner and developer agents, and the independent milestone auditor.
- **Source:** `first_brief.txt` (project root). Section numbers cited as "brief §N". This PRD does not replace the brief; where they differ, the brief's §3, §4, §9 and §10 wording governs.
- **Conventions:** "I", "me", "my" inside transcribed requirements mean the operator. Non-negotiable requirements (CON, SAF, GL) are transcribed verbatim from the brief, split one sentence group per id; they may not be reworded, softened or dropped by any downstream document. FRs and NFRs state *what*, not *how*: they must hold whether the build is custom or Freqtrade-based (OD-01 is open).
- **Status:** draft. Produced headless; the operator has not reviewed it. Every gap was recorded as an open decision or assumption, not decided.

## Vision

A rules-based spot crypto trading bot that the operator runs on their own computer, observes in dry-run through a local dashboard, and then runs live with about €20 (brief §1).

The purpose of v1 is to prove the pipeline end to end: data, backtest, simulated execution, monitoring, then live execution with strict limits. Profit is not the success criterion for v1. Correctness, observability and safety are.

## Users

One user: the operator, a French tax resident trading on a personal Kraken account, who reads the code of the safety-critical modules (GL-05) and makes every go-live and risk-limit decision. No other users; no multi-user access. User journeys are omitted: this is a single-operator tool and reads as a capability spec.

## Glossary

| Term | Definition |
|---|---|
| Run mode | One of `backtest`, `dry-run`, `live` (SAF-08). Same strategy and order logic in all three; only the broker and the clock change (FR-11). |
| Candle | One OHLCV bar of the configured pair and timeframe, timestamped in UTC. *Closed* once its interval has ended. |
| Strategy | A pure function from candle history to a target position (FR-05, FR-06). |
| Target position | Fraction of equity to hold in the base asset, between 0 and 1. |
| v0 strategy | The slow long-or-flat trend filter used to exercise the pipeline (FR-07). |
| Plumbing strategy | A short-timeframe, dry-run-only strategy that exists to generate orders for testing (FR-09). |
| Benchmarks | Buy-and-hold of the same pair, and holding cash (FR-08). |
| Broker | The abstraction that places and queries orders. *Paper broker* simulates fills (dry-run); *live broker* sends real orders to Kraken; *fake broker* is used by tests. |
| Fill | An executed (possibly partial) order quantity at a price, with its fee. |
| Holdout | The most recent 12 months of data, never used for tuning, evaluated once per strategy (FR-15, FR-16). |
| Risk limit | A configured bound checked before every order (FR-30 to FR-36). Protected (SAF-04). |
| Halt | State entered when the daily-loss or total-drawdown limit is breached; no trading until the operator resets it manually (FR-33). |
| Kill switch | A file on disk and a dashboard button that stop all new orders immediately (FR-36). |
| Reconciliation | Startup comparison of locally persisted state with the broker's state (FR-29). |
| Journal | Per-signal record of outcome and, for untraded signals, the hypothetical return (FR-40). |
| Ledger | Record of every fill for French tax bookkeeping (FR-45 to FR-47). |
| Disposal | A fill converting crypto to euros; counts toward the annual disposal total (CON-10). |
| DECAYING | Flag set on a strategy whose live/dry-run results fall below half the backtest expectation (FR-42). |

## Non-negotiable requirements

Verbatim from the brief. Changing any of these requires the operator's explicit instruction.

### Hard constraints (brief §3)

- **CON-01:** **Exchange:** Kraken spot, via the `ccxt` library.
- **CON-02:** **Capital:** about €20 live. Position sizing must respect Kraken's minimum order sizes (at the time of writing: €5 for EUR-quoted orders, 0.0001 BTC, 0.01 ETH).
- **CON-03:** Read minimums, price precision and fee rates from the exchange's market metadata at startup. Do not hardcode them.
- **CON-04:** **Fees:** every backtest and every dry-run fill must include fees taken from the exchange's fee schedule for my tier, plus a configurable slippage assumption.
- **CON-05:** For reference, Kraken Pro's entry tier was 0.40% maker / 0.80% taker on spot crypto pairs when this brief was written (November 2026), so a round trip with market orders costs about 1.6% and with resting limit orders about 0.8%. Read the live rates from the API; treat these numbers only as a sanity check.
- **CON-06:** Every backtest report must show results at both maker and taker rates.
- **CON-07:** **Stablecoin pairs:** USDT is not available to EEA clients on Kraken. If a stablecoin-quoted pair is chosen, confirm which stablecoins are tradable from a French account and which fee schedule applies before building on it.
- **CON-08:** **Trade frequency:** low. Fees make frequent trading unviable at this size, so strategies work on 4h or daily candles.
- **CON-09:** **Tax bookkeeping (France):** keep a complete ledger of every fill, with timestamps, amounts, prices, fees and the quote currency, exportable to CSV.
- **CON-10:** Mark separately the trades that convert crypto to euros, since those are the ones that count toward the annual disposal total.
- **CON-11:** The choice between a EUR-quoted pair and a stablecoin-quoted pair is an open decision (section 13); the code must support both.

### Safety and security rules (brief §4, non-negotiable)

- **SAF-01:** API keys live in a secrets file stored outside the repository folder; the repo holds only its path and a `.env.example` with empty values.
- **SAF-02:** Never print, log, commit or ask me to paste a key into the chat, and never open or read the secrets file during development.
- **SAF-03:** Kraken lets an API key be restricted to given IP addresses. If the machine running the bot has a stable IP, I will turn this on; remind me at M6.
- **SAF-04:** **Protected files:** the risk limits in `config.yaml`, the `risk/` module and its tests may only be changed when I ask for it explicitly in the chat, in a commit that touches nothing else.
- **SAF-05:** The running bot has no code path that can edit its own limits.
- **SAF-06:** I will create the Kraken API key myself with query and trade permissions only. No withdrawal permission.
- **SAF-07:** The bot should check the key's permissions at startup if the API allows it and refuse to start if withdrawals are enabled.
- **SAF-08:** Three run modes: `backtest`, `dry-run`, `live`.
- **SAF-09:** `live` requires both a CLI flag and an environment variable, and prints a confirmation banner with the account balance and the active limits.
- **SAF-10:** During development, never place a real order.
- **SAF-11:** Tests use a fake broker. Nothing in the test suite may touch the live trading endpoints.
- **SAF-12:** Pin all dependencies with a lockfile.
- **SAF-13:** Ask me before adding any dependency beyond those in section 6. (Brief §6 list: Python 3.11 or later, `uv` for environment and lockfile; `ccxt`, `pandas`, `pyarrow`, `pydantic`, `pyyaml`, `python-dotenv`; SQLite through the standard library or SQLAlchemy; `pytest`, `ruff`; Streamlit with Plotly charts for the dashboard, alternative only with a strong reason.)
- **SAF-14:** Do not install third-party "trading skills", plugins or packages from unknown sources.
- **SAF-15:** The dashboard binds to `127.0.0.1` only.

### Go-live criteria (brief §10, fixed in advance)

- **GL-01:** Four weeks of dry-run with no unhandled errors and no state mismatch on reconciliation.
- **GL-02:** Dry-run fills within a stated tolerance of backtest predictions over the same period. (Tolerance value: OD-08.)
- **GL-03:** Every risk limit triggered at least once in tests and seen working.
- **GL-04:** Kill switch tested from both the file and the dashboard.
- **GL-05:** I have read the code of the broker, risk and engine modules myself.
- **GL-06:** Go-live does not depend on the dry-run being profitable. If the strategy shows no edge after costs, that is a valid result and the decision to put €20 on it is mine.

## Functional requirements

Implementation-neutral. Each FR has one checkable result. Brief section in brackets.

### Data [§5.1]

- **FR-01:** The system downloads OHLCV candles for the configured pair and timeframe from Kraken (CON-01), handling pagination and rate limits.
- **FR-02:** Downloaded candles are cached locally and reused without re-downloading (brief specifies Parquet).
- **FR-03:** Candle data is validated for no gaps, no duplicates, monotonic timestamps and UTC timestamps; any violation is reported and the run fails. Bad data is never silently repaired.
- **FR-04:** Signals are computed only on closed candles.

### Strategy [§5.2, §5]

- **FR-05:** A strategy receives candle history and returns a target position between 0 and 1.
- **FR-06:** A strategy is a pure function of past data with explicit parameters; it has no access to the broker, the clock or the network.
- **FR-07:** The v0 strategy is a slow trend filter, long or flat, on one pair (for example: long when price is above a long moving average, flat otherwise, on daily candles). Its parameters are fixed in configuration before any out-of-sample evaluation.
- **FR-08:** Every strategy result is reported next to two benchmarks: buy-and-hold of the same pair, and holding cash.
- **FR-09:** A plumbing strategy trades on a short timeframe in dry-run, generating enough simulated orders to exercise order handling, restarts and the dashboard. It claims no edge.
- **FR-10:** The system refuses to run the plumbing strategy in `live` mode.
- **FR-11:** The same strategy code and the same order logic run in all three modes; only the broker and the clock differ.

### Backtester [§5.3]

- **FR-12:** The backtest is event-driven, candle by candle: a signal computed on candle *t* close executes at candle *t+1* open, with fees and slippage applied (CON-04).
- **FR-13:** The backtest enforces minimum order size and precision exactly as the live broker would; an order below the minimum is rejected and logged, not silently rounded.
- **FR-14:** One command produces a backtest report with total return, annualized return, max drawdown, Sharpe, number of trades, turnover, total fees paid and time in market, each compared with the benchmarks, at both maker and taker rates (CON-06).
- **FR-15:** Walk-forward evaluation is supported, with a held-out final period (the most recent 12 months) that is never used for tuning.
- **FR-16:** The holdout is run once per strategy, at the end, and its result is reported even if it kills the idea. Every holdout run is recorded with its date and git commit, so a second run is visible.
- **FR-17:** Strategy changes are made one at a time, at most five per strategy, each logged in `changes.md` with its result and git commit.
- **FR-18:** Every result is saved with the code version, configuration and data date range that produced it.
- **FR-19:** When a strategy does not beat buy-and-hold after costs, the report says so in its first line.
- **FR-20:** Every parameter search writes the number of configurations tried to the results file.
- **FR-21:** Reports include a bootstrap confidence interval on the Sharpe ratio.
- **FR-22:** A guard in the backtester catches look-ahead; a test that deliberately uses candle *t+1* data at *t* fails because of it.

### Broker [§5.4]

- **FR-23:** A single broker abstraction offers: get balance, get ticker, place order, cancel order, get open orders, get fills. It does not preclude a second exchange later.
- **FR-24:** The paper broker simulates fills against live prices using the same fee, minimum-order and slippage model as the backtester.
- **FR-25:** The paper broker's virtual balance persists so that dry-run survives restarts.
- **FR-26:** The live broker uses client order IDs so that a retried request can never create a duplicate order.
- **FR-27:** The live broker handles partial fills, rejections, timeouts and rate limits without losing or duplicating state.
- **FR-28:** At startup the system verifies the API key's permissions where the API allows it and refuses to start if withdrawals are enabled (SAF-07; fallback: OD-12).
- **FR-29:** At startup, in any mode with a broker, the system reconciles local state (balances, open orders) with the broker's state and stops if they disagree.

### Risk manager [§5.5]

- **FR-30:** Every order passes pre-trade risk checks before reaching any broker. Limits are read from configuration (protected, SAF-04) and cannot be changed by the running system (SAF-05).
- **FR-31:** An order is rejected if it would exceed the maximum position size, as a fraction of equity or as an absolute amount.
- **FR-32:** An order is rejected if it would exceed the maximum number of orders per day.
- **FR-33:** Breaching the maximum daily loss or the maximum total drawdown from the starting balance halts trading until the operator resets it manually (reset mechanism: OD-10).
- **FR-34:** No order is placed if the last candle or ticker is older than a configured threshold.
- **FR-35:** An order is rejected if the price moved more than a configured threshold since the signal.
- **FR-36:** The kill switch, triggered by a file on disk or by the dashboard button, stops all new orders immediately (scope for open orders and positions: OD-09).
- **FR-37:** Every rejection, halt and kill-switch event is stored with its reason.

### Engine, journal and persistence [§5.6, §13]

- **FR-38:** The engine wakes at candle close, fetches data, computes the signal, runs risk checks, sends orders and records every step.
- **FR-39:** All state (signals, orders, fills, equity snapshots, risk events, heartbeats, errors) is persisted crash-safely; a restarted process resumes cleanly, including mid-order.
- **FR-40:** Every signal is journaled with its outcome (filled, not filled, rejected by risk, skipped by the operator); for signals not traded, the journal records what the trade would have returned.
- **FR-41:** A weekly review compares realized results with what the backtest expected for the same period and is shown in the dashboard.
- **FR-42:** Once there are 20 or more trades, if the average result per trade is below half the backtest's, the strategy is flagged DECAYING (edge case: OD-15).
- **FR-43:** Structured logs are written to file with secrets redacted.
- **FR-44:** The engine supports two approval modes: autonomous trading within limits, and per-order operator approval before sending (choice for first live weeks: OD-05; approval channel: OD-13).
- **FR-45:** In `live` mode, startup requires both the CLI flag and the environment variable and shows the confirmation banner with account balance and active limits (SAF-09).

### Ledger [§3, §7.7]

- **FR-46:** Every fill is recorded in the ledger with timestamp, amount, price, fee and quote currency, and the ledger exports to CSV (CON-09).
- **FR-47:** Fills that convert crypto to euros are marked, and the running total of crypto-to-euro sales for the calendar year is computed (CON-10).
- **FR-48:** The ledger and all FRs work for both EUR-quoted and stablecoin-quoted pairs (CON-11).

### Dashboard [§7]

- **FR-49:** A local web dashboard reads the persisted store, auto-refreshes, binds to `127.0.0.1` only (SAF-15), and can take exactly one action: toggling the kill switch.
- **FR-50:** **Overview:** current mode shown prominently (DRY-RUN or LIVE), engine status and last heartbeat, equity, cash, open position, return since start, total fees paid, and an equity curve against buy-and-hold and cash.
- **FR-51:** **Signals and trades:** price chart with the strategy's indicator, entry and exit markers, and the current target position.
- **FR-52:** **Orders and fills:** table of orders with status; fills with price, fee and slippage versus the signal price; filterable by date.
- **FR-53:** **Risk:** each limit with its current usage, history of rejections and halts with reasons, kill switch state and button.
- **FR-54:** **Dry-run vs backtest:** for the same period, backtester-predicted equity versus paper-broker-recorded equity, with the difference per trade.
- **FR-55:** **Health:** recent errors, API latency, rate-limit events, data freshness, uptime.
- **FR-56:** **Ledger:** fills ledger with CSV export, including the calendar-year running total of crypto-to-euro sales.

### Testing and audit [§8]

- **FR-57:** Unit tests cover the strategy, sizing, fee and minimum-order logic, and every risk rule.
- **FR-58:** Backtester tests run on synthetic price series with known outcomes.
- **FR-59:** Engine tests use a fake broker and a fake clock and cover restart mid-order, partial fills, duplicate-order prevention, API errors and stale data.
- **FR-60:** A consistency test shows the backtest and the paper broker produce the same trades on the same recorded data (see BI-05).
- **FR-61:** Each risk limit has a test that triggers it (GL-03).
- **FR-62:** Kill-switch tests cover both the file and the dashboard trigger (GL-04).
- **FR-63:** A test proves the plumbing strategy cannot start in `live` mode (FR-10).
- **FR-64:** Never delete, skip or weaken a test to make the suite pass. If a test fails, fix the code or report the failure and stop.
- **FR-65:** At the end of each milestone, a reviewer that did not write the code (a fresh session, a separate subagent, or BMAD's review step) runs the tests itself, reads the git history for deleted, skipped or weakened tests and for extra holdout runs, looks for look-ahead bias, missing costs and overfitting, and rates each result PASS, FAIL or INCONCLUSIVE.
- **FR-66:** The operator sees the audit report (FR-65) before reviewing the milestone.

## Non-functional requirements

- **NFR-01 Auditability:** modules are small and readable over clever abstractions; the operator must be able to read the broker, risk and engine code in full (GL-05).
- **NFR-02 Reproducibility:** the same code version, configuration and data range produce the same backtest result.
- **NFR-03 Time:** all timestamps stored and compared in UTC.
- **NFR-04 Reliability:** dry-run runs 48 hours without intervention and survives a forced restart (M3); four weeks without unhandled errors or reconciliation mismatch (GL-01).
- **NFR-05 Observability:** heartbeats, errors, API latency, rate-limit events and data freshness are recorded continuously enough to populate FR-55.
- **NFR-06 Locality:** everything runs on the operator's computer; no cloud services; no network listener beyond `127.0.0.1`.
- **NFR-07 Secret hygiene:** no secret appears in logs, error messages, tracebacks, the store, the dashboard or the repository (SAF-01, SAF-02).
- **NFR-08 Cost realism:** no simulated fill (backtest or dry-run) omits fees or slippage (CON-04).
- **NFR-09 Simulation labeling:** every output derived from simulation (backtest, dry-run, paper fills) is labeled as simulated.
- **NFR-10 Dependency hygiene:** dependencies pinned by lockfile; no dependency outside brief §6 without operator approval (SAF-12 to SAF-14).

## Non-goals

From brief §2 and §12. No level below may add these.

- No LLM in the trading decision loop (a later, measured experiment, brief §12).
- No leverage, margin, futures, shorting or derivatives. Spot, long or flat only.
- No market making, arbitrage or high-frequency logic.
- No prediction markets.
- No multi-exchange support (the broker abstraction must not prevent it later, FR-23).
- No cloud deployment.
- Out of scope for v1, later: additional strategies and pairs, notifications (Telegram or email), running on a small always-on machine.
- Profit is not a v1 success criterion.

## Milestones and acceptance criteria

Verbatim from brief §9. v1 scope is M0 to M6; nothing is cut (a leaner first version was not assessed because the milestones are the operator's).

- **M0 Scaffold:** repo, lockfile, config, `.env.example`, `.gitignore`, CI-style test command. *Done when* tests and lint pass on an empty skeleton.
- **M1 Data:** downloader, cache, validation. *Done when* several years of daily and 4h candles for the chosen pair are cached and validated.
- **M2 Backtester and v0 strategy:** *Done when* a backtest report with metrics and benchmarks is generated from one command, and the look-ahead guard test passes.
- **M3 Paper broker, engine, risk manager:** *Done when* the engine runs in dry-run for 48 hours without intervention and survives a forced restart.
- **M4 Dashboard:** *Done when* all seven views work against the dry-run database.
- **M5 Dry-run period:** at least four weeks, reviewed weekly.
- **M6 Live with €20:** only if the go-live criteria in section 10 are met.

Work one milestone at a time. At the end of each one, stop, summarize what was built, list known limitations, and wait for my review.

Gate before M0: OD-01 (build or reuse) must be decided. Gate before M1: OD-02 (pair) [ASSUMPTION AS-01]. Every milestone ends with the independent audit (FR-65, FR-66).

## Success metrics

- **SM-1:** Every milestone M0 to M5 accepted by the operator with an independent audit report and no unresolved FAIL. Validates FR-57 to FR-66.
- **SM-2:** Over the M5 period, dry-run fills within the GL-02 tolerance of backtest predictions. Validates FR-24, FR-54, FR-60.
- **SM-3:** Zero unhandled errors and zero reconciliation mismatches over four weeks of dry-run. Validates FR-29, FR-39 (GL-01).
- **SM-4:** Zero real orders placed during development and zero secrets exposed. Validates SAF-02, SAF-10, NFR-07.
- **Counter-metrics:** return is explicitly not a target (GL-06); order count is watched against fees so that SM-1 to SM-3 are not met by over-trading the v0 strategy (CON-08).

## Working rules for the developer agent

Verbatim from brief §11, to be added to the developer agent's instructions (brief §14 step 5).

- **WR-01:** Explain design choices briefly before implementing each milestone, and flag anything in this brief that looks wrong or unsafe.
- **WR-02:** Prefer small, readable modules to clever abstractions. I need to be able to audit this.
- **WR-03:** Never weaken a safety rule from section 4 to make something work. Stop and ask.
- **WR-04:** State uncertainty plainly. If Kraken's API behaves differently from what this brief assumes, tell me and propose a change.
- **WR-05:** Do not present backtest results as evidence that the strategy will make money.
- **WR-06:** Never say that a process is running, a test passed or an order filled without having checked it in this session. Label anything simulated as simulated.
- **WR-07:** Keep `PROGRESS.md` up to date with what is done, what is next, and every decision with its reason. Read it first in every new session.
- **WR-08:** (from brief §8) Never delete, skip or weaken a test to make the suite pass. If a test fails, fix the code or report the failure and stop.

## Open decisions

Owner of every item: the operator. None is decided in this PRD.

### From brief §13 ("Ask me these before M2 rather than choosing silently")

| Id | Decision | Options in the brief | Needed by | Blocks |
|---|---|---|---|---|
| **OD-01** | Build or reuse | A: custom build per brief §5 (smaller, fully auditable, more to get wrong in order handling). B: Freqtrade as execution engine, custom work limited to missing risk rules, ledger export, dry-run-vs-backtest view. Before M0, read Freqtrade's current docs, list which requirements of brief §4, §5, §7 it covers and does not, recommend. Do not start the custom build until chosen. | Before M0 | All FRs; architecture |
| **OD-02** | Pair | EUR-quoted (simple, every sale counts toward the annual disposal total) or stablecoin-quoted (crypto-to-crypto; CON-07 check required). | Before M1 (see BI-01) | FR-01, FR-47, M1 |
| **OD-03** | v0 candle timeframe | Daily or 4h. | Before M2 | FR-07, FR-38 |
| **OD-04** | Execution order type | Limit or market orders. | Before M2 | FR-12, FR-24, FR-26, CON-06 interpretation |
| **OD-05** | Approval mode for first live weeks | Autonomous within limits, or per-order approval (engine supports both, FR-44). | Before M6 | M6 |
| **OD-06** | Risk limit values | Max position (fraction, absolute), orders/day, daily loss, total drawdown, stale-data and price-sanity thresholds. | Before M3 | FR-31 to FR-35 |
| **OD-07** | Where the bot runs during the four-week dry-run | Computer must stay on. | Before M5 | M5, SAF-03 |

### Raised by this PRD (gaps in the brief)

| Id | Decision | Why it is needed | Needed by |
|---|---|---|---|
| **OD-08** | GL-02 tolerance value and metric (per-fill price, per-trade return, equity) | GL-02 says "a stated tolerance" but states none; GL criteria are meant to be fixed in advance. | Before M5 starts |
| **OD-09** | Kill-switch scope: only block new orders, or also cancel open orders and/or exit the position | FR-36 says "stops all new orders"; resting limit orders could still fill. | Before M3 |
| **OD-10** | Halt reset mechanism (CLI command, file, other) and whether it may live in the dashboard | Dashboard may only toggle the kill switch; reset must not edit limits (SAF-05). | Before M3 |
| **OD-11** | Whether a halt or kill switch still allows a risk-reducing exit (sell to flat) | "Halts trading" could leave a losing position open indefinitely. | Before M3 |
| **OD-12** | Behavior if Kraken's API cannot report key permissions | SAF-07 applies "if the API allows it"; fallback (refuse, warn, operator attestation) is undefined. | Before M3 |
| **OD-13** | Channel for per-order approval (CLI prompt, file, dashboard) | Dashboard is read-only except the kill switch (FR-49). | Before M6 |
| **OD-14** | Holdout boundary: fixed calendar dates set at M1, or a rolling "most recent 12 months" | A rolling window moves as time passes, and dry-run data later overlaps it. | Before M2 |
| **OD-15** | DECAYING rule when the backtest's average per-trade result is zero or negative | "Below half" is ambiguous for non-positive values. | Before M5 |
| **OD-16** | Location of protected risk limits (section of `config.yaml` vs separate file) and how SAF-04 maps onto Freqtrade if OD-01 = B | SAF-04 names custom-build paths (`config.yaml`, `risk/`). Wording of SAF-04 is not changed here. | With OD-01 |
| **OD-17** | Whether tests may call public (non-trading) Kraken endpoints, e.g. for data download | SAF-11 forbids live trading endpoints only. | Before M1 |
| **OD-18** | Sizing rule when the target position is below the exchange minimum, or a remaining position is below the minimum to sell (dust) | With €20 and a €5 minimum, small targets or post-loss positions may be untradeable (FR-13 rejects, never rounds). | Before M2 |
| **OD-19** | Fee tier and pair fee schedule actually applicable to the account, and whether EUR and crypto pairs differ | CON-04 requires "my tier"; CON-05 numbers are only a sanity check. | Before M2 |

## Brief issues found

- **BI-01:** §13 says to ask the open decisions "before M2", but M1's acceptance criterion requires "the chosen pair", and OD-01 must be settled before M0. Pair must be chosen before M1.
- **BI-02:** SAF-04 names custom-build paths (`config.yaml`, `risk/` module) while OD-01 is open; under Freqtrade these paths may not exist (OD-16).
- **BI-03:** Option B (Freqtrade) adds dependencies far beyond brief §6, which SAF-13 requires the operator to approve; that approval is part of OD-01.
- **BI-04:** The dashboard is "read-only" yet must support the kill-switch button, and possibly halt reset and order approval (OD-10, OD-13). Any write path must be limited and must not touch limits (SAF-05).
- **BI-05:** The consistency test (FR-60) compares backtest and paper broker "on the same recorded data", but the paper broker fills against live prices; a replay input for the paper broker is implied and not stated.
- **BI-06:** Unsafe: the kill switch and halts stop new orders only; open orders and the open position are not addressed (OD-09, OD-11).
- **BI-07:** Unsafe: SAF-07's permission check is conditional; if Kraken cannot report permissions, nothing enforces "no withdrawal permission" in code (OD-12).
- **BI-08:** €20 capital with a €5 minimum order leaves at most about four minimum-size orders; FR-13's "reject, never round" can strand a position below the minimum after a loss (OD-18).
- **BI-09:** GL-02 has no tolerance and M5 ("reviewed weekly") has no pass/fail criterion; both conflict with "fixed in advance" (OD-08).
- **BI-10:** Streamlit, the brief's suggested dashboard stack, listens on all interfaces by default; SAF-15 requires explicit configuration and a test.

## Assumptions

Unconfirmed inferences made headless; each stays until the operator accepts it.

- **AS-01:** The pair (OD-02) must be decided before M1, not M2 (BI-01). Affects M1.
- **AS-02:** "Several years" of candles (M1) means as far back as Kraken's API returns for the pair; Kraken may cap OHLCV history, which the developer must report per WR-04. Affects FR-01, M1.
- **AS-03:** Reconciliation (FR-29) applies to `dry-run` (paper broker state) and `live`, not to `backtest`, which has no broker state. Affects FR-29.
- **AS-04:** Stakes are personal, but real money and safety rules justify exceeding the PRD template's two-page ceiling for solo work; the length comes from the verbatim transcription the operator required.
