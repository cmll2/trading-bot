---
id: 1
type: story
title: "Recent daily candles downloaded, cached and validated end to end"
parent: epic-m1-data
covers: ["R1", "R2"]
after: ["epic-m0-scaffold"]
refined: false
hitl: false
risk: low
protected: false
---

# Recent daily candles downloaded, cached and validated end to end

## Description

Tracer: `bot data update` pulls recent BTC/EUR 1d candles via ccxt with pagination and rate-limit handling into var/data/BTC-EUR/1d.parquet, and `bot data validate` checks them.

## Requirements

Verify: With a fake ccxt in tests the cache file is written with the schema; run once for real by the builder, `bot data validate` exits 0 and prints the range.

1. **Paginated, rate-limited fetch** (FR-01, CON-01, AD-18)
   **Given** a fake ccxt returning 720-candle pages and one RateLimitExceeded
   **When** `bot data update` runs
   **Then** all pages are fetched with `enableRateLimit`, the rate-limit error waits and retries, and no candle is duplicated
2. **Parquet cache reused** (FR-02, AD-18)
   **Given** an existing cache
   **When** the command runs again
   **Then** only candles after the last cached `open_at` are requested; columns are open_at (UTC ms), open, high, low, close, volume, trades, source
3. **Only closed candles stored** (FR-04)
   **Given** the current, still-open candle in the response
   **When** it is cached
   **Then** it is dropped

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/epic-m1-data.md, Requirements R1, R2
- prd — docs/planning/prd.md, CON-01, FR-01, FR-02, FR-04
- architecture — docs/planning/architecture.md, AD-18
- architecture — docs/planning/architecture.md, AD-24
- architecture — docs/planning/architecture.md, Consistency conventions: Time, Pairs

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
