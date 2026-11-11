---
id: 1
type: story
title: "Skeleton package, pinned lockfile and one check command"
parent: epic-m0-scaffold
covers: ["R1"]
after: []
refined: false
hitl: false
risk: low
protected: false
---

# Skeleton package, pinned lockfile and one check command

## Description

Tracer: the package layout of brief §5 with empty modules, a `uv.lock` pinning only brief §6 dependencies, and one command that runs tests, lint and format check.

## Requirements

Verify: On a clean clone, `uv sync --locked` and the check command both exit 0, and `uv run bot --help` prints the CLI usage.

1. **Pinned dependencies only from brief §6** (SAF-12, SAF-13, SAF-14, NFR-10)
   **Given** pyproject.toml and uv.lock
   **When** the dependency list is inspected
   **Then** every runtime and dev dependency is one of ccxt, pandas, pyarrow, pydantic, pyyaml, python-dotenv, streamlit, plotly, pytest, ruff, and uv.lock pins each exactly
   **And** `uv sync --locked` fails if pyproject and lockfile disagree
2. **Module boundaries exist** (NFR-01)
   **Given** the skeleton
   **When** the tree is listed
   **Then** bot/{config,clock,cli,engine,sizing,store,ledger,logging_setup}.py and bot/{data,strategy,backtest,broker,risk,migrations}/, dashboard/, tests/ exist as in the architecture Structural seed
3. **One CI-style command** (brief §9 M0)
   **Given** an empty skeleton
   **When** the documented check command runs
   **Then** pytest, `ruff check` and `ruff format --check` all run and the command exits 0; any one failing makes it exit non-zero
4. **Gitignore protects runtime state and secrets** (SAF-01, SAF-02)
   **Given** the repo
   **When** `git check-ignore` is run on `.env`, `var/x`, `results/tmp` excluded paths
   **Then** `.env` and `var/` are ignored and `.env.example` is tracked

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m0-scaffold/epic-m0-scaffold.md, Requirements R1
- prd — docs/planning/prd.md, NFR-01, NFR-10, SAF-01, SAF-02, SAF-12, SAF-13, SAF-14
- architecture — docs/planning/architecture.md, Structural seed, Stack

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
