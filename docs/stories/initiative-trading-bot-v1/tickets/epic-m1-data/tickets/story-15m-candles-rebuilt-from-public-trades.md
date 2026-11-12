---
id: 9
type: story
title: "15m candles rebuilt from public trades between archive end and API window"
parent: epic-m1-data
covers: ["R1", "R2", "R3"]
after: [4, 6]
refined: true
hitl: false
risk: medium
protected: false
---

# 15m candles rebuilt from public trades between archive end and API window

## Description

Coordinator decision 2026-11-12. Kraken's OHLCVT archive ends 2026-09-30 and the public OHLC endpoint returns only the last 720 15m candles (about 7.5 days), leaving 2026-10-01 to about 2026-11-04 without an official 15m source. Rebuild those candles from Kraken's public trades endpoint (research B6, option 2). Generic over timeframe.

## Requirements

1. **Public, paginated, resumable fetch** (FR-01, AD-18, AD-24)
   **Given** a fake ccxt returning pages of trades (with repeated trades across pages) and one RateLimitExceeded
   **When** `bot data backfill-trades --timeframe 15m --start S --end E` runs
   **Then** trades in [S, E) are fetched with `since` pagination and exponential backoff, deduplicated by trade id, checkpointed so an interrupted run resumes without refetching, and a page that brings nothing new fails loudly instead of skipping trades
2. **Archive convention** (AD-18)
   **Given** the fetched trades
   **When** candles are built
   **Then** each bucket is floor(trade time / interval) in UTC; open = first trade, close = last, high/low = max/min, volume = sum of amounts, trades = count; buckets with no trade are omitted and become flagged flat candles through the existing no-trade policy
3. **Overlap-checked merge** (FR-03, AD-18)
   **Given** the existing cache (archive and/or API rows)
   **When** the rebuilt candles are merged
   **Then** overlapping candles pass the existing 1 tick / 1% volume check or nothing is written; the result passes `bot data validate`

## Boundaries

- Public, unauthenticated endpoints only; tests never touch the network; no new dependency.
- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/; existing test assertions.
