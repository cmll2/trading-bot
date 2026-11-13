---
id: 1
type: story
title: "Dry-run engine ticking on live prices with heartbeats and journal"
parent: epic-m3-paper-engine-risk
covers: ["R3", "R4", "R5", "R12"]
after: ["epic-m2-backtest"]
refined: false
hitl: false
risk: medium
protected: false
---

# Dry-run engine ticking on live prices with heartbeats and journal

## Description

Tracer: `bot dry-run --strategy v0_trend` runs Engine(PaperBroker, SystemClock, CcxtMarketData, var/state/dry-run-v0_trend.sqlite) with the engine lock, run record, per-tick heartbeat and a journaled signal on each daily close; `bot status` prints state.

## Requirements

Verify: FakeClock/fake-ccxt test drives one daily close to a journaled signal and a paper order; the builder runs `bot dry-run` for 10 minutes and `bot status` shows a fresh heartbeat (labelled simulated).

1. **Shared engine, dry-run adapters** (FR-11, AD-1)
   **Given** the dry-run command
   **When** it starts
   **Then** it builds the M2 Engine with PaperBroker, SystemClock, CcxtMarketData and a file store, no API key and no load_secrets call
2. **Wakes at candle close** (FR-38, FR-04)
   **Given** a daily close at 00:00 UTC
   **When** the next tick runs
   **Then** one signal row is written for that candle, then sizing, risk and an intent in one transaction
3. **Paper balance survives restart** (FR-25, AD-26)
   **Given** a paper account seeded from paper.initial_quote
   **When** the process restarts
   **Then** paper_* balances and schema_meta initial_* are unchanged
4. **One engine per store and clock skew** (AD-17, AD-2)
   **Given** a second engine on the same store, or clock skew > 5 s vs Kraken server time
   **When** it starts
   **Then** it refuses with the reason

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R3, R4, R5, R12
- prd — docs/planning/prd.md, FR-04, FR-11, FR-24, FR-25, FR-38
- architecture — docs/planning/architecture.md, AD-1
- architecture — docs/planning/architecture.md, AD-2
- architecture — docs/planning/architecture.md, AD-17
- architecture — docs/planning/architecture.md, AD-26
- architecture — docs/planning/architecture.md, AD-28

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).

## Added from M2 audit (2026-11-13)

- **Stale OWN feed vs exchange halt (audit M2 F-5).** The M2 engine keeps the resting order (no re-price) whenever `now - ticker.ts > stale_ticker_seconds`. In the backtest that condition only arises from exchange halts (synthetic candles), where keeping the order is realistic. In dry-run/live it also fires when the bot's own feed is stale: the order would keep working while the bot is blind, for up to the 6 h window, outside the price-sanity check. Revisit before the dry-run: cancel resting orders on own-feed staleness (cancels reduce risk and are always allowed), and keep them only when the exchange's market status shows a halt — or document why not. Add an engine test for each case.
- **Halts are evaluated on equity at every tick (audit M2 F-1).** The live tick is 30 s; the backtest now evaluates halts at every 15m close. Expect daily-loss halts roughly 3–4 times a year at full exposure on BTC (31 in the 2017-2025 backtest); the dry-run must show them, and the M5 review should compare halt counts with the backtest's SIMULATED RESET count.
- **`Engine.reset_halts(now, note, rebase_rules)` exists** (M2): the M3 `bot reset-halt` consumer should call it when it consumes a `reset_halt` operator action, instead of writing `halts` itself.
