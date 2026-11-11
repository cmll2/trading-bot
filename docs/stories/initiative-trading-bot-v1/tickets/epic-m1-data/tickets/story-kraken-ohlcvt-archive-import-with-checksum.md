---
id: 3
type: story
title: "Kraken OHLCVT archive import with checksum"
parent: epic-m1-data
covers: ["R1", "R2"]
after: [2]
refined: false
hitl: true
risk: low
protected: false
---

# Kraken OHLCVT archive import with checksum

## Description

`bot data import-archive --zip <path>` verifies the published SHA256 and streams only XBTEUR_1440/240/15 CSVs into the cache with source=archive.

## Requirements

Verify: A test zip with a wrong checksum is refused; a correct fixture zip imports three timeframes; the operator runs it once on the real archive.

1. **Checksum first** (AD-18)
   **Given** a zip whose SHA256 differs from the expected value
   **When** import runs
   **Then** it refuses before reading any row
2. **Only the needed files** (AD-18, Conventions: Pairs)
   **Given** the full archive
   **When** import runs
   **Then** only XBTEUR_{1440,240,15}.csv are streamed, Unix seconds become UTC, and the Kraken name appears nowhere outside the importer

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/epic-m1-data.md, Requirements R1, R2
- prd — docs/planning/prd.md, FR-01, FR-02
- architecture — docs/planning/architecture.md, AD-18
- research — docs/research/build-vs-reuse-and-kraken.md — B6

## Notes

- hitl: the operator downloads the archive by hand to a folder outside the repo and gives its path and published checksum.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
