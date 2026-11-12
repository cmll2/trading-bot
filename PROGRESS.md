# PROGRESS

Read this first in every session. Source of truth for the brief: `first_brief.txt`.

## Status

- **Current phase:** M1 Data built (branch `m1-data`); independent M1 audit and operator review pending.
- **Blocked on:** nothing for 1d/4h (full archive imported 2026-11-12). 15m needs two operator decisions (see Next). Story 6 ticket stays `blocked` on 15m only.

## Done

- 2026-11-11 — Brief read. Launched in parallel: Freqtrade/Kraken research (`docs/research/build-vs-reuse-and-kraken.md`) and PRD (`docs/planning/prd.md`).

- 2026-11-11 — PRD written: `docs/planning/prd.md` (CON/SAF/GL verbatim from brief, FR-01–66, NFR-01–10, OD-01–19). Gaps found: pair needed at M1 not M2; kill switch/halts don't address open orders/positions; withdrawal check unenforceable if API can't report permissions; €20 with €5 min can leave unsellable dust; GL-02 tolerance undefined; Streamlit binds 0.0.0.0 by default (must set `server.address=127.0.0.1`).

- 2026-11-11 — **M0 Scaffold built** (branch `m0-scaffold`, not merged). Package skeleton per brief §5 with stubs citing AD-/FR- IDs; Broker/Clock/Strategy/MarketData ports; frozen pydantic `Settings` from `config.yaml` + `.env` (`.env` = secrets-file path only, refused inside the repo; unknown keys and a live-gate value in `.env` refused; secrets file never opened); protected `risk:` section → frozen `RiskLimits`; `bot backtest|dry-run|live` stubs, live double gate (`--live` + `TRADING_BOT_LIVE=I_ACCEPT_REAL_ORDERS`) and still refusing in M0; plumbing excluded from live; autouse network block in `tests/conftest.py`; ruff TID251 bans wall-clock APIs outside `bot/clock.py`. Check `uv run ruff check . && uv run ruff format --check . && uv run pytest` passed: 93 tests (also via `scripts/check.ps1` and `scripts/check.sh`). No dependency added. Known limits: everything beyond config/CLI gates is a stub; fees not in config (decide at M2); `.streamlit/config.toml` deferred to M4; independent audit not yet run.

- 2026-11-11 — **M0 audited (PASS with findings, `docs/audits/M0-audit.md`) and approved by operator** ("do what you recommend"). Merged to main. Fixed findings F-2..F-7, F-10 (commit 2d49152), F-1 + F-11 in protected commit b415992, F-8/F-9 accepted (hunk review of config.yaml; LiveGate real protection at M6). 127 tests pass.

- 2026-11-12 — **M1 Data built** (branch `m1-data`, stories 1–7 via BMAD `bmad-build-auto`: plan → implement subagent → quick review subagent → triage/patch → commit; audit story 8 left to the coordinator). Commands: `bot data update` (public ccxt Kraken `fetch_ohlcv`, own pagination, exponential backoff via Clock, closed candles only, incremental), `bot data import-archive --zip --sha256` (checksum before any ZIP parsing, single file handle, exact `XBTEUR_{1440,240,15}.csv` members, capped streaming read, no extraction), `bot data validate` (schema/UTC/unique/monotonic/aligned/OHLC/no missing interval/synthetic rules/ratio cap; never repairs; prints data hash), `bot data audit-gaps` (read-only no-trade runs, partial coverage, NOT AUDITABLE). Overlap-checked merge (1 tick from market metadata, 1% volume), `SimClock`/`FakeClock`/`SystemClock`, immutable closed-only `CandleHistory` (`bot/candles.py`), `ReplayMarketData`, deterministic data hash. Check: 506 tests pass. No dependency added; no protected file touched.
  - **Archive:** downloaded `Kraken_OHLCVT_2026Q3.zip` (576,348,633 B, SHA-256 `96daae63…1226`, computed, Kraken publishes none for quarterlies) into `data/raw/kraken_ohlcvt/`; manifest `docs/data-manifest.md`. Full archive (5 × 2,097,152,000 B parts) NOT downloaded (>5 GB rule) — operator action.
  - **Real data, 2026-11-11 (public endpoint + Q3 2026 archive), `bot data validate` exit 0 for all three:**
    - 1d: 719 rows, 2024-11-22 → 2026-11-10 (92 archive, 627 api), 0 synthetic, hash `975bb436…`.
    - 4h: 802 rows, 2026-07-01 00:00 → 2026-11-11 12:00 (552 archive, 250 api), 0 synthetic, hash `d62eb114…`.
    - 15m: 720 rows, 2026-11-04 07:45 → 2026-11-11 19:30 (api only), 0 synthetic. Importing Q3 15m is refused: `download gap at 2026-10-01` (Q3 ends 2026-09-30; 15m API window is ~7.5 days).
    - Overlap archive vs API: 92 daily and 552 4h candles compared, max price diff 0 ticks, max volume diff ~4e-14.
    - Synthetic ratio from `history_start` (2017-01-01): 0 on all timeframes.
    - **2013–2016 daily gap audit: NOT AUDITABLE** — no cached candles before 2024-11-22 until the full archive is imported (`bot data audit-gaps`).
  - **M1 "done when" status:** validation, fail-loudly tests, closed-candle view: met. "Several years of 1d and 4h": NOT met (1d ≈ 2 years, 4h ≈ 4 months) until the operator imports the full archive. 15m: validated only for the last week; Oct 2026 has no official source until Kraken publishes Q4 2026.

- 2026-11-12 — **Full Kraken archive imported in place** (split-archive importer, commit ddab312: `--zip` once per part + `--part-sums`; per-part and whole SHA-256 verified in one pass before parsing; no reassembly, disk had 23 GB free). Real results, `bot data validate` exit 0 for all three:
  - 1d: 4,810 rows, 2013-09-10 → 2026-11-10 (4,764 archive, 41 api, 5 synthetic), hash `4eb97931…`. Archive vs API overlap: 678 candles, 0 ticks, max volume diff 0.039%.
  - 4h: 28,859 rows, 2013-09-10 20:00 → 2026-11-11 12:00 (28,430 archive, 250 api, 179 synthetic), hash `34175be1…`. Overlap 552 candles, 0 ticks.
  - 15m: unchanged (720 api rows, last week). Import refused: `download gap at 2026-10-01` (archive ends 2026-09-30; 15m API window starts 2026-11-04). Measured separately (scratch dir): archive-only 15m fails the cap — synthetic ratio 0.163% (558/341,760 from 2017-01-01) > 0.1%.
  - **2013–2016 daily gap audit:** 4 no-trade days, all Sep 2013 (2013-09-12, 09-20, 09-26..27); none in 2014–2016. 4h: 168 no-trade candles, 167 in Sep–Nov 2013, 1 on 2016-01-27.
  - From 2017: 1d one no-trade day (2018-01-12, the Jan 2018 Kraken outage); 4h 11 candles (2018-01-11..13 outage, 2024-04-14, 2025-11-01). Synthetic ratio from 2017-01-01: 1d 0.028%, 4h 0.051% (cap 0.1%).

## Next

1. Independent M1 audit (story 8), then operator review of M1.
2. Operator decisions for 15m (fill-model data, AD-6): (a) source for 2026-10-01..2026-11-03 — wait for Kraken's Q4 2026 file, or a new story to rebuild 15m from the public Trades endpoint; (b) 15m synthetic ratio is 0.163% from 2017 — choose a later 15m start date or a per-timeframe cap (no silent change). Meanwhile keep `bot data update` running at least weekly (15m API window ≈ 7.5 days).
3. M2 (after review): backtests use 1d from `data.history_start`; holdout 2025-11-11 → 2026-11-10 stays untouched until the single holdout run.

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
| 2026-11-11 | M1 built through BMAD `bmad-build-auto` (full route for stories 1–5, oneshot for 6–7), quick review lens per story; follow-up reviews recommended by the workflow for stories 1, 2, 5 were not run (left to the independent audit) | Coordinator instruction; cost |
| 2026-11-11 | Cache stays at `var/data/BTC-EUR/{tf}.parquet` (AD-18); raw downloads under `data/raw/` (both gitignored) | Architecture path; coordinator asked for raw downloads in `data/raw/` |
| 2026-11-11 | Downloaded only `Kraken_OHLCVT_2026Q3.zip` (smallest official file with XBTEUR that overlaps the API window); full archive left to operator | >5 GB with no per-pair file; Q3 makes the real archive-vs-API overlap check possible |
| 2026-11-11 | Quarterly ZIP checksum is trust-on-first-use (computed at download, recorded in `docs/data-manifest.md`); full archive uses Kraken's published SHA-256 | Kraken publishes no checksum for quarterly files |
| 2026-11-11 | API rows carry `trades = <NA>` | ccxt's unified OHLCV drops Kraken's trade count |
| 2026-11-11 | No-trade fill only between two archive rows; every synthetic run must be archive-bounded; merge precedence archive > synthetic > api | A forward-filled API gap must never pass validation |
| 2026-11-11 | Overlap tick read from public market metadata (`load_markets`), only when merging into an existing cache; float epsilon = 1e-6 × tick | CON-03; offline imports report the real error; tolerance must not grow with price |
| 2026-11-11 | `data.history_start: 2017-01-01` provisional (synthetic-ratio cap 0.1% applies from it) | Cannot be measured until the full archive is imported; to be fixed before any backtest |
| 2026-11-12 | **Keep `data.history_start: 2017-01-01`** (provisional until M1 review): measured 1d 0.028% / 4h 0.051% synthetic from it (cap 0.1%), ~8.9 years before the holdout; earlier years have dense 2013 gaps | Measured on the full archive; chosen on data quality only, before any backtest |
| 2026-11-12 | Split archive imported in place (`ConcatReader`), never reassembled | 23 GB free disk; reassembly would need ~9.5 GB more |
| 2026-11-12 | 15m left at the API week; no config change to pass its 0.163% ratio | Changing the cap or start date is an operator decision |
| 2026-11-11 | `bot data audit-gaps` prints NOT AUDITABLE / PARTIAL COVERAGE instead of "no gaps" when the cache does not cover the window | An absent archive must never look like a clean audit |
| 2026-11-11 | Interpretation (flag at review): `validate` exit 0 for 15m covers only the API week; 15m import of Q3 fails loudly on the Oct 2026 download gap, by design | AD-18: download gaps always fail |

## Brief corrections (from research)

- Kraken minimums are lower than brief states (live: 0.00006 BTC, 0.002 ETH, €0.45 cost min) — always read from metadata.
- Kraken API *can* report key permissions (`GetApiKeyInfo`).

## Pair decision (2026-11-11)

**BTC/EUR (Kraken `XBT/EUR`), single pair for v0.** Selected on ex-ante market quality only (no cross-pair backtests; holdout untouched) — see `docs/research/pair-selection.md`. Runner-ups for later (≥ ~€100 capital, after M6): ETH/EUR, XRP/EUR, SOL/EUR. No basket in v0: thin min-order margin at €20, order-count budget, high correlation with BTC.
Implementation notes: sell orders use `oflags=post,fciq` (fee in quote currency) so the full base balance can be sold; re-read minimums at startup; handle sub-minimum partial-fill remainders; audit 2013–2016 daily gaps at M1.

## Open decisions

- None blocking. (UX: approval channel = CLI prompt by default.)
