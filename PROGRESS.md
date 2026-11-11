# PROGRESS

Read this first in every session. Source of truth for the brief: `first_brief.txt`.

## Status

- **Current phase:** M1 Data (branch `m1-data`).
- **Blocked on:** nothing.

## Done

- 2026-11-11 — Brief read. Launched in parallel: Freqtrade/Kraken research (`docs/research/build-vs-reuse-and-kraken.md`) and PRD (`docs/planning/prd.md`).

- 2026-11-11 — PRD written: `docs/planning/prd.md` (CON/SAF/GL verbatim from brief, FR-01–66, NFR-01–10, OD-01–19). Gaps found: pair needed at M1 not M2; kill switch/halts don't address open orders/positions; withdrawal check unenforceable if API can't report permissions; €20 with €5 min can leave unsellable dust; GL-02 tolerance undefined; Streamlit binds 0.0.0.0 by default (must set `server.address=127.0.0.1`).

- 2026-11-11 — **M0 Scaffold built** (branch `m0-scaffold`, not merged). Package skeleton per brief §5 with stubs citing AD-/FR- IDs; Broker/Clock/Strategy/MarketData ports; frozen pydantic `Settings` from `config.yaml` + `.env` (`.env` = secrets-file path only, refused inside the repo; unknown keys and a live-gate value in `.env` refused; secrets file never opened); protected `risk:` section → frozen `RiskLimits`; `bot backtest|dry-run|live` stubs, live double gate (`--live` + `TRADING_BOT_LIVE=I_ACCEPT_REAL_ORDERS`) and still refusing in M0; plumbing excluded from live; autouse network block in `tests/conftest.py`; ruff TID251 bans wall-clock APIs outside `bot/clock.py`. Check `uv run ruff check . && uv run ruff format --check . && uv run pytest` passed: 93 tests (also via `scripts/check.ps1` and `scripts/check.sh`). No dependency added. Known limits: everything beyond config/CLI gates is a stub; fees not in config (decide at M2); `.streamlit/config.toml` deferred to M4; independent audit not yet run.

- 2026-11-11 — **M0 audited (PASS with findings, `docs/audits/M0-audit.md`) and approved by operator** ("do what you recommend"). Merged to main. Fixed findings F-2..F-7, F-10 (commit 2d49152), F-1 + F-11 in protected commit b415992, F-8/F-9 accepted (hunk review of config.yaml; LiveGate real protection at M6). 127 tests pass.

## Next

1. M1 Data: Kraken OHLCVT archive import + ccxt recent fill, Parquet cache, validation; several years of 1d and 4h BTC/EUR cached and validated. Then independent M1 audit and operator review.

## Decisions log

| Date | Decision | Reason |
|------|----------|--------|
| 2026-11-11 | Follow BMAD full planning track | Brief §14: safety requirements benefit from explicit architecture step |
| 2026-11-11 | Python via `uv` managed interpreter (system has 3.10, brief needs ≥3.11) | Brief §6 |
| 2026-11-11 | **Custom build (Option A)** — user choice | Freqtrade gaps: no client order IDs, reconciliation only logs, timed (not manual-reset) halts, no key-permission check, control-panel UI, silent min-stake round-up; ~300 KB to audit, 44 deps |
| 2026-11-11 | **EUR-quoted pair**; specific market chosen by research on market quality (user: "not only BTC, find the easiest market") — not by backtest returns (avoid selection bias) | User choice; tax simplicity; no 0.20% stablecoin conversion |
| 2026-11-11 | **Daily candles** for v0 | Lowest fee drag; manual approval practical |
| 2026-11-11 | **Post-only limit orders, re-priced within a window, then cancel & skip** (journal: "not filled") | Maker 0.40% vs taker 0.80% |
| 2026-11-11 | **Manual approval per order** as default for first live weeks; engine supports both | User choice |
| 2026-11-11 | **Risk limits:** max position 100% equity & €25 abs; ~~4 orders/day~~ (superseded below); daily loss 10%; total drawdown 25% from start (manual reset); stale: candle > 2 intervals, ticker > 120 s; price sanity 2% | User accepted defaults |
| 2026-11-11 | **Dry-run host: this Windows PC** (keep code portable) | User choice |
| 2026-11-11 | **GL-02 tolerance:** each paper fill within 0.5% of backtest-predicted price; 4-week equity within 2 pp | User accepted defaults |
| 2026-11-11 | Key permissions checked via Kraken `GetApiKeyInfo`; refuse start if withdraw enabled or call fails | Research B3 |
| 2026-11-11 | Fees from `fetch_trading_fee` only (market metadata no longer carries fees; ccxt defaults stale) | Research B2 |
| 2026-11-11 | Before any order retry, look up `cl_ord_id` in open AND closed orders (Kraken dedups only among open) | Research B4 |
| 2026-11-11 | History: Kraken official OHLCVT CSV archive + ccxt for recent gap, overlap check; explicit no-trade-period policy | Research B6: OHLC endpoint limited to 720 candles |

| 2026-11-11 | UX spec: `docs/planning/ux-dashboard/{DESIGN,EXPERIENCE}.md`. Dashboard can only **engage** kill switch (with confirm); disengage + halt reset are CLI-only | Safer narrowing of brief "toggle"; flag to user at M4 review |
| 2026-11-11 | Timestamps stored in UTC; tax-year boundaries for disposal totals computed in Europe/Paris | French tax year is the local calendar year |

| 2026-11-11 | Architecture: `docs/planning/architecture.md` (AD-1..AD-30). Kill switch/halt = cancel resting orders, keep position; `bot flatten` is manual | Never force a sale automatically under a fault condition |
| 2026-11-11 | **"Max 4 orders/day" = 4 new order intents/day; plus a separate hard cap of 24 exchange submissions/day (re-prices count)** — *flag at review: interpretation of a protected limit* | Re-pricing would otherwise make the limit meaningless or block execution; both caps are conservative |
| 2026-11-11 | Execution window 6 h after daily close (00:00 UTC); re-price at most every 30 min, max 12 submissions per intent; then cancel & skip | Fits within 24 submissions/day |
| 2026-11-11 | Holdout = fixed window 2025-11-11 → 2026-11-10 (UTC), frozen in config; never moves | Rolling boundary would leak holdout into tuning over time |
| 2026-11-11 | DECAYING: needs ≥20 trades and backtest avg/trade > 0; if backtest avg ≤ 0 the strategy is shown as "NO EDGE IN BACKTEST" instead | DECAYING rule undefined for non-positive baseline |
| 2026-11-11 | Risk limits stay in `config.yaml` under `risk:` (protected); loaded read-only | Brief §5.5 says config.yaml |
| 2026-11-11 | Halt reset does NOT rebase drawdown baseline unless `--rebase` is passed explicitly (with confirmation) | Conservative default |
| 2026-11-11 | Windows supervision: Task Scheduler (at logon + restart on failure), documented at M3 | Host = this PC |
| 2026-11-11 | **Deviation from AD-10:** the per-intent cap (`max_submissions_per_intent: 12`) lives in `execution:`, not in protected `risk:`. The daily hard cap of 24 exchange submissions stays in `risk:`. Config validation requires per-intent cap ≤ daily cap. architecture.md AD-5/AD-10/AD-28 patched | `risk:` holds exactly the limits the operator adopted; the daily cap is the protective one |
| 2026-11-11 | Execution values from this log (6 h window, 30 min re-price interval, 12 submissions/intent) supersede architecture Q-8 defaults (4 h / 15 min / 8 re-prices); Q-8 patched | This log is authoritative |
| 2026-11-11 | M0 built directly, not through the BMAD `bmad-build-auto` workflow (`_bmad/` runtime was absent at the time) | Coordinator decision; same scope, commits and checks |
| 2026-11-11 | Live gate names per AD-15: `bot live --live` + `TRADING_BOT_LIVE=I_ACCEPT_REAL_ORDERS`, from the shell only (a value in `.env` is refused) | Keep the gate a deliberate per-session act |
| 2026-11-11 | Fee rates are not in `config.yaml` at M0 (Conventions planned `fees.maker/taker` for backtest/dry-run). Decide at M2 whether to add them to config or read them from `fetch_trading_fee` | M0 instruction: no hardcoded minimums or fees |

| 2026-11-11 | **Operator: "don't limit yourself to 4 orders a day, we go when we think there's a good call."** Trade-count caps raised to runaway-bug backstops: 20 intents/day, 120 exchange submissions/day; per-intent cap 12 moved into protected `risk:` (supersedes the AD-10 deviation above); integer limits strict. Protected commit b415992 | Operator's explicit request; caps kept only as protection against a looping bug |
| 2026-11-11 | Operator approved all recommendations at M0 review: dashboard engage-only kill switch, risk checks built in M2 (backtest uses them), KrakenBroker in M6, any unhandled error or code fix during M5 restarts the 4-week clock | "do what you recommend" |

## Brief corrections (from research)

- Kraken minimums are lower than brief states (live: 0.00006 BTC, 0.002 ETH, €0.45 cost min) — always read from metadata.
- Kraken API *can* report key permissions (`GetApiKeyInfo`).

## Pair decision (2026-11-11)

**BTC/EUR (Kraken `XBT/EUR`), single pair for v0.** Selected on ex-ante market quality only (no cross-pair backtests; holdout untouched) — see `docs/research/pair-selection.md`. Runner-ups for later (≥ ~€100 capital, after M6): ETH/EUR, XRP/EUR, SOL/EUR. No basket in v0: thin min-order margin at €20, order-count budget, high correlation with BTC.
Implementation notes: sell orders use `oflags=post,fciq` (fee in quote currency) so the full base balance can be sold; re-read minimums at startup; handle sub-minimum partial-fill remainders; audit 2013–2016 daily gaps at M1.

## Open decisions

- None blocking. (UX: approval channel = CLI prompt by default.)
