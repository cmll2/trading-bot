# Build or reuse, and Kraken facts: decision research

Date: 2026-11-11. Inputs: `first_brief.txt` (sections 3, 4, 5, 7, 13). Every claim below has a source URL, read on this date from current official docs (Freqtrade docs/source, Kraken API docs and support, ccxt source). The only Kraken endpoint called was the **public, unauthenticated** `AssetPairs` endpoint. No authenticated call was made and no code was written.

Legend: **COVERED** = works out of the box with config only. **PARTIAL** = some of it is built in, or it can be done in a strategy callback or a small add-on. **NOT COVERED** = you would have to write it, or it conflicts with how Freqtrade works.

Freqtrade version checked: release 2026.10 (30 Oct 2026), develop branch source. <https://github.com/freqtrade/freqtrade/releases>

---

## Part A: Freqtrade coverage matrix

### Section 4: Safety and security rules

| # | Requirement | Status | Note | Source |
|---|---|---|---|---|
| 4.1 | Keys in a secrets file outside the repo, never logged | PARTIAL | Supports a second, private config file (`--config a.json --config private.json`) and `FREQTRADE__EXCHANGE__KEY` env vars. But the docs say "Environment variables detected are logged at startup" (check whether values appear in the log), and that secrets put in `ccxt_config` "may be contained in logs". No documented log redaction. | https://www.freqtrade.io/en/stable/configuration/ |
| 4.2 | IP allow-list reminder at M6 | N/A | This is an operator action on Kraken, not a bot feature. Kraken's `GetApiKeyInfo` returns `ip_allowlist`, so either option can check it (see B3). | https://docs.kraken.com/api-reference/account-data/get-api-key-info.md |
| 4.3 | Protected risk config; the bot cannot edit its own limits | PARTIAL | Freqtrade's REST API/FreqUI can `reload_config` and change runtime state (stopbuy, locks, forceenter/forceexit). The bot has code paths that change trading state, but it does not write the config file. Limits written as custom code would sit in the strategy file, which you control in git. | https://www.freqtrade.io/en/stable/rest-api/ |
| 4.4 | Check key permissions at startup and refuse if withdraw is enabled | NOT COVERED | Startup (`startup()`) runs migrations, precision backfill, stoploss reinit and open-order refresh. There is no permission check. | https://raw.githubusercontent.com/freqtrade/freqtrade/develop/freqtrade/freqtradebot.py |
| 4.5 | Three modes; `live` needs a CLI flag **and** an env var, plus a banner with balance and limits | PARTIAL | Has backtesting, dry-run (`dry_run: true`, the default) and live (`dry_run: false`). A single config flag switches to live. The two-factor gate and the banner would need a wrapper script. | https://www.freqtrade.io/en/stable/configuration/ |
| 4.6 | No real order in development; tests use a fake broker | PARTIAL | Dry-run and backtesting never place orders. Your own add-ons would need their own tests, with mocks via Freqtrade's test fixtures (pytest). | https://www.freqtrade.io/en/stable/configuration/ |
| 4.7 | Lockfile; ask before adding deps beyond the section 6 list | NOT COVERED (conflict) | Freqtrade pins 44 runtime packages, including `ta-lib` (C extension), `scipy`, `fastapi`, `uvicorn`, `python-telegram-bot`, `SQLAlchemy`, `aiohttp`, `cryptography`, `pycoingecko`, `technical`, `ft-pandas-ta`, `rich`, `questionary` and others. It requires Python >= 3.12. Adopting it means approving all of them in one go. | https://raw.githubusercontent.com/freqtrade/freqtrade/develop/requirements.txt , https://github.com/freqtrade/freqtrade |
| 4.8 | Dashboard binds to 127.0.0.1 only | COVERED | "By default, the configuration listens on localhost only". The sample config uses `listen_ip_address: 127.0.0.1`, and all endpoints except `/ping` require auth. (The Docker setup uses 0.0.0.0, so restrict the port mapping.) | https://www.freqtrade.io/en/stable/rest-api/ |

### Section 5: Architecture (same strategy and order logic in all modes)

| # | Requirement | Status | Note | Source |
|---|---|---|---|---|
| 5.0 | Same strategy and order code in backtest, dry-run and live; only the broker and clock change | COVERED | This is Freqtrade's core design. One `IStrategy` class runs in all modes. Backtesting is a separate simulation engine, not the live order path. | https://www.freqtrade.io/en/stable/backtesting/ |

### 5.1 Data

| # | Requirement | Status | Note | Source |
|---|---|---|---|---|
| 5.1a | Download OHLCV via ccxt, paginated, rate-limited, cached as Parquet | PARTIAL | `download-data` supports a `parquet` format (default `feather`). **For Kraken spot, OHLCV history is not available**: `ohlcv_has_history: False`, and `--dl-trades` is mandatory, otherwise "the bot repeatedly downloads the same 720 candles". Trades are converted to candles locally. The docs warn this needs "significantly more RAM" and "takes a long time". Kraken's trade ZIP files can be imported with `convert-trade-data --format-from kraken_csv`. | https://www.freqtrade.io/en/stable/exchanges/ , https://www.freqtrade.io/en/stable/data-download/ , https://raw.githubusercontent.com/freqtrade/freqtrade/develop/freqtrade/exchange/kraken.py |
| 5.1b | Validate: no gaps or duplicates, monotonic, UTC; fail loudly | PARTIAL | Data is UTC and deduplicated on import. Freqtrade's Kraken notes assume "no gaps exist between files" and warn that gaps cause "invalid results". There is no documented fail-loud gap validator. | https://www.freqtrade.io/en/stable/exchanges/ |
| 5.1c | Signals only on closed candles | COVERED | "Only complete/finished candle data is available in the dataframe." | https://www.freqtrade.io/en/stable/strategy-customization/ |

### 5.2 Strategy interface

| # | Requirement | Status | Note | Source |
|---|---|---|---|---|
| 5.2a | `on_candle(history) -> TargetPosition` in [0, 1] | PARTIAL | Freqtrade's model is entry/exit signals on a dataframe, with `custom_stake_amount` for sizing (0/None blocks the entry). There is no "target fraction" abstraction, but long/flat maps onto it cleanly. | https://www.freqtrade.io/en/stable/strategy-callbacks/ |
| 5.2b | Strategy is pure, with no broker, clock or network access | NOT COVERED (by design) | The strategy object gets `self.dp` (live `ticker()`, `orderbook()`) and `self.wallets`. Purity is a coding convention, not something the framework enforces. | https://www.freqtrade.io/en/stable/strategy-customization/ |
| 5.2c | v0 slow trend filter, long/flat, daily | COVERED | Trivial as an `IStrategy` with `timeframe = '1d'`. | https://www.freqtrade.io/en/stable/strategy-customization/ |
| 5.2d | Benchmarks: buy-and-hold of the same pair, and cash | PARTIAL | The backtest report shows "Market change" (average close-to-close change across pairs), which is a rough buy-and-hold. It has no buy-and-hold equity curve with fees and no explicit cash benchmark. | https://www.freqtrade.io/en/stable/backtesting/ |
| 5.2e | Plumbing strategy that cannot run live | NOT COVERED | Any strategy can run in any mode. A guard (for example, refusing in `bot_start` when `dry_run` is false) would need custom code. | https://www.freqtrade.io/en/stable/strategy-callbacks/ |

### 5.3 Backtester

| # | Requirement | Status | Note | Source |
|---|---|---|---|---|
| 5.3a | Event-driven; signal at close of *t*, fill at open of *t+1*, fees and slippage | PARTIAL | Entries at open; "Exit-signal exits happen at open-price of the consecutive candle". Fees are included (exchange default, or `--fee`). **No slippage**: "All orders are filled at the requested price (no slippage)". Also check fee defaults (see B2/B5: ccxt's built-in Kraken defaults are outdated). | https://www.freqtrade.io/en/stable/backtesting/ |
| 5.3b | Enforce minimum size and precision exactly as live; **reject**, never round | PARTIAL / conflict | Limits are respected using *current* limits only ("no information about historic limits"). Live and dry-run **round stake up** to the minimum unless that is more than 30% above the desired stake, and `amount_reserve_percent` (5%) is added. This silent adjustment is what the brief forbids. | https://www.freqtrade.io/en/stable/backtesting/ , https://www.freqtrade.io/en/stable/configuration/ |
| 5.3c | Metrics: return, annualized, max DD, Sharpe, trades, turnover, fees, time in market, vs benchmarks | PARTIAL | Has Sharpe, Sortino, Calmar, max drawdown, SQN, trade count and a p-value. Turnover, total fees, time in market and benchmark comparison would need custom report code from the exported trades. | https://www.freqtrade.io/en/stable/backtesting/ |
| 5.3d | Walk-forward plus a once-only 12-month holdout recorded with date and commit | NOT COVERED | Only `--timerange`. No walk-forward tooling and no holdout ledger. | https://www.freqtrade.io/en/stable/backtesting/ |
| 5.3e | `changes.md`, at most 5 changes, results tied to code, config and data range | NOT COVERED | Process and tooling you would write in either option. | (brief) |
| 5.3f | "Doesn't beat B&H" on line 1; trial counts; bootstrap CI on Sharpe | NOT COVERED | Hyperopt records its epochs, but a bootstrap CI and the first-line verdict are not provided. | https://www.freqtrade.io/en/stable/backtesting/ |
| 5.3g | Look-ahead guard catches a deliberate *t+1* leak | COVERED (stronger than asked) | `lookahead-analysis` re-runs backtests per signal and flags biased entries, exits and indicators (limits: only signals that actually trigger are checked). `recursive-analysis` checks indicator sensitivity to startup candles. It is a CLI tool, not a unit-test guard, so you would still add a pytest that plants a leak and asserts it is flagged. | https://www.freqtrade.io/en/stable/lookahead-analysis/ , https://www.freqtrade.io/en/stable/recursive-analysis/ |

### 5.4 Broker

| # | Requirement | Status | Note | Source |
|---|---|---|---|---|
| 5.4a | Broker interface (balance, ticker, place, cancel, open orders, fills) | COVERED (internal) | Built in via its ccxt `Exchange` class. Not a pluggable interface you own. | https://raw.githubusercontent.com/freqtrade/freqtrade/develop/freqtrade/exchange/exchange.py |
| 5.4b | Paper broker with the same fees, minimums and slippage; virtual balance persisted in SQLite | PARTIAL | Dry-run uses its own DB (`tradesv3.dryrun.sqlite`). The wallet is **recomputed from the DB on every call** (start capital plus closed profit minus open stakes), so it survives restarts. Fills: market orders fill against the order book with up to 5% slippage, and limit orders that cross by more than 1% become market orders. That is a different model from the backtester (no slippage), so the brief's "same slippage model as the backtester" is not met. | https://www.freqtrade.io/en/stable/configuration/ , https://raw.githubusercontent.com/freqtrade/freqtrade/develop/freqtrade/wallets.py |
| 5.4c | Live broker uses client order IDs, so a retry can never duplicate | NOT COVERED | Neither `exchange.py` nor `kraken.py` sets `clientOrderId`, `userref` or `cl_ord_id`. Mitigation: `create_order` has **no retry decorator**, so Freqtrade does not auto-resend. After a timeout, though, an order may exist that Freqtrade does not track until `handle_onexchange_order` adopts it later. | https://raw.githubusercontent.com/freqtrade/freqtrade/develop/freqtrade/exchange/kraken.py , https://raw.githubusercontent.com/freqtrade/freqtrade/develop/freqtrade/exchange/exchange.py |
| 5.4d | Reconcile local and exchange state at startup; **stop on mismatch** | NOT COVERED | `startup_update_open_orders()` re-fetches open orders, but it is skipped in dry-run, logs failures without stopping, and assumes orders older than 5 days were cancelled. Balance mismatches are tolerated within 2% and otherwise logged ("Refusing to adjust..."), not fatal. | https://raw.githubusercontent.com/freqtrade/freqtrade/develop/freqtrade/freqtradebot.py , https://www.freqtrade.io/en/stable/faq/ |

### 5.5 Risk manager

| # | Requirement | Status | Note | Source |
|---|---|---|---|---|
| 5.5a | Max position size as a fraction and as an absolute amount | COVERED | `stake_amount` / `tradable_balance_ratio` / `max_open_trades`, plus `custom_stake_amount` for an absolute cap. | https://www.freqtrade.io/en/stable/configuration/ , https://www.freqtrade.io/en/stable/strategy-callbacks/ |
| 5.5b | Max orders per day | NOT COVERED | "No max entries per day" setting. Could be done in `confirm_trade_entry` with your own counter. | https://www.freqtrade.io/en/stable/configuration/ |
| 5.5c | Max daily loss **and** total drawdown from start; halt until **manual** reset | NOT COVERED (conflict) | The protections (StoplossGuard, MaxDrawdown, LowProfitPairs, CooldownPeriod) are time-boxed locks that **expire automatically** after `stop_duration`. There is no manual-reset mode and no daily-loss protection. MaxDrawdown is drawdown over a lookback window, not from the starting balance. A workaround is a far-future `lock_pair` placed by your code plus a manual unlock, but manual locks do not work in backtesting. | https://www.freqtrade.io/en/stable/plugins/ , https://www.freqtrade.io/en/stable/strategy-customization/ |
| 5.5d | Stale-data check (candle or ticker older than a threshold) | PARTIAL | Not a documented protection. Could be done in `confirm_trade_entry`, which receives `current_time`, comparing it against the dataframe's last candle. | https://www.freqtrade.io/en/stable/strategy-callbacks/ |
| 5.5e | Price sanity (moved more than X since signal) | PARTIAL | `confirm_trade_entry` gets `rate` and can return False. The docs give this exact use ("price is not what we expect"). | https://www.freqtrade.io/en/stable/strategy-callbacks/ |
| 5.5f | Kill switch: a file on disk plus a dashboard button | PARTIAL | The button exists: FreqUI/REST `/stopbuy` ("Stops the trader from opening new trades"), `/pause`, `/stop`. There is no file-based switch; it could be checked in `confirm_trade_entry`. | https://www.freqtrade.io/en/stable/rest-api/ |
| 5.5g | Every rejection stored with its reason | PARTIAL | Locks carry a reason in the DB. Rejections in `confirm_trade_entry` are only logged unless you persist them yourself. | https://www.freqtrade.io/en/stable/plugins/ |

### 5.6 Engine and persistence

| # | Requirement | Status | Note | Source |
|---|---|---|---|---|
| 5.6a | Wake at candle close, then signal, risk, order, record | COVERED | Core loop. | https://www.freqtrade.io/en/stable/strategy-customization/ |
| 5.6b | Crash-safe: everything in SQLite (signals, orders, fills, equity, risk events, heartbeats, errors) | PARTIAL | Trades, orders and locks are in SQLite. Signals, equity snapshots, heartbeats, risk events and errors are not stored there (errors go to logs). | https://www.freqtrade.io/en/stable/configuration/ |
| 5.6c | Journal of every signal with outcome and counterfactual return; weekly review; DECAYING flag | NOT COVERED | Custom. | (brief) |
| 5.6d | Structured file logs with secrets redacted | PARTIAL | `--logfile` is supported, including on Windows. Redaction is not documented (see 4.1). | https://www.freqtrade.io/en/stable/faq/ |

### Section 7: Dashboard (FreqUI)

| # | View | Status | Note | Source |
|---|---|---|---|---|
| 7.0 | Read-only; only action is the kill switch; auto-refresh | NOT COVERED (conflict) | FreqUI is a full control surface (force entry and exit, reload config, delete locks), the opposite of read-only. It is authenticated and bound to localhost. | https://www.freqtrade.io/en/stable/rest-api/ |
| 7.1 | Overview: mode, heartbeat, equity, fees, equity vs B&H and cash | PARTIAL | Shows mode, profit and balance. No B&H or cash overlay. | https://www.freqtrade.io/en/stable/rest-api/ |
| 7.2 | Signals and trades chart with indicator and markers | COVERED | FreqUI charts with `plot_config`. | https://www.freqtrade.io/en/stable/rest-api/ |
| 7.3 | Orders and fills with slippage vs signal price | PARTIAL | Orders and fills, yes. Slippage vs signal price, no. | https://www.freqtrade.io/en/stable/rest-api/ |
| 7.4 | Risk: limit usage, rejection history, kill switch | PARTIAL | Locks list plus stopbuy. No per-limit usage gauges and no rejection history. | https://www.freqtrade.io/en/stable/rest-api/ |
| 7.5 | Dry-run vs backtest per trade | NOT COVERED | This is the brief's main validation tool. Fully custom. | (brief section 13 already anticipates this) |
| 7.6 | Health: errors, latency, rate-limit events, freshness, uptime | PARTIAL | `/health` and the logs endpoint exist. No latency or rate-limit metrics. | https://www.freqtrade.io/en/stable/rest-api/ |
| 7.7 | Ledger with CSV export and a running total of crypto-to-EUR disposals | NOT COVERED | `show-trades --print-json` only. "No CSV option for trades". French disposal tagging is custom. | https://www.freqtrade.io/en/stable/utils/ |

### Cross-cutting items

| Topic | Finding | Source |
|---|---|---|
| Windows | Native install is possible but Freqtrade "**strongly** recommend[s] that Windows users use Docker" (else WSL). Native install may need the Visual C++ build tools. | https://www.freqtrade.io/en/stable/installation/ |
| Licence | GPLv3. Private use with no distribution creates no obligation: "The GPL does not require you to release your modified version, or any part of it." Obligations start only if you convey it (for example, publish or share the bot, including strategy code that imports Freqtrade). | https://raw.githubusercontent.com/freqtrade/freqtrade/develop/LICENSE , https://www.gnu.org/licenses/gpl-faq.html#GPLRequireSourcePostedPublic |
| Kraken in Freqtrade | Spot supported. Stoploss-on-exchange supported. 720-candle limit, so `--dl-trades` (or Kraken trade ZIPs) is mandatory for backtest data. | https://www.freqtrade.io/en/stable/exchanges/ |
| Fee source | Backtests "use the exchange's default fees". For Kraken, ccxt's built-in defaults are 0.26%/0.16% (old schedule), and AssetPairs `fees` arrays are now empty (deprecated 8 Sep 2026). **Always pass `--fee 0.008` / config `fee`**, or results understate costs about 3x. Exactly what Freqtrade falls back to when ccxt's market fee is `None` was not verified. | https://www.freqtrade.io/en/stable/backtesting/ , https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/kraken.py , https://docs.kraken.com/api/docs/rest-api/get-tradable-asset-pairs/ |

### Score (out of 46 rows, excluding N/A)

About 8 COVERED, 24 PARTIAL and 14 NOT COVERED. Most of the NOT COVERED rows are the brief's safety-critical ones: permission check, client order IDs, stop-on-mismatch reconciliation, manual-reset halts, orders/day cap, read-only dashboard, ledger, dependency policy and the dry-run vs backtest view.

### Recommendation: **Option A (custom build)**, borrowing Freqtrade ideas without adopting the code

Reasoning, tailored to this brief:

1. **Auditability is a go-live criterion (section 10: "I have read the code of the broker, risk and engine modules myself").** With Freqtrade, the "engine" is `freqtradebot.py` (about 120 KB), `exchange.py` (about 190 KB), plus wallets, persistence and RPC. Reading that honestly is a far larger job than reading a purpose-built ~1–2k-line engine. You would also not own the order path you are certifying.
2. **The safety rules Freqtrade misses are exactly the hard ones,** and they sit in its core, not at the edges: stop-on-mismatch reconciliation, idempotent client order IDs, manual-reset halts (its protections auto-expire by design), the withdraw-permission refusal, and a read-only dashboard (FreqUI is a control panel). Bolting these on means patching or wrapping core behaviour of a fast-moving upstream (monthly releases). Patches have to be re-audited every upgrade, and an un-upgraded fork drifts.
3. **Behaviour conflicts with the brief rather than gaps:** stake is silently rounded up to the minimum (up to 30%), the backtest has no slippage while dry-run uses an order-book model (so the "same model" consistency test is impossible), and drawdown protection is windowed rather than measured from the start.
4. **Dependency policy:** Freqtrade brings in 44 pinned packages (TA-Lib C extension, FastAPI, Telegram, scipy...) and Python >= 3.12, against a brief that requires asking for each dependency beyond six. On Windows, Freqtrade itself recommends Docker, which is one more layer to trust and operate.
5. **€20 capital and learning goal:** at this size the cost of a bug is small in euros but the point of v1 is to *prove and own the pipeline*. Freqtrade would prove Freqtrade's pipeline. The custom pieces Option B still requires (risk rules, ledger, dry-run vs backtest view, journal, holdout tracking, reports) are already more than half of the brief's work.
6. **What Freqtrade does better, and how to capture it in A:** its order-state handling has been battle-tested on many exchanges, and `lookahead-analysis` is stronger than a single planted-leak test. Mitigations: (a) keep the custom engine very small and single-pair, single-position, with no stoploss orders on the exchange in v1; (b) copy the *idea* of lookahead-analysis (re-run the signal with data truncated at *t* and compare it to the full-data signal) as a test utility, which is simple to do for a pure `on_candle(history)` function; (c) optionally run Freqtrade **once, read-only, in backtest mode in a throwaway venv** as an independent cross-check of the v0 backtest numbers. That needs your dependency approval and is not part of the product.

When B would be the better choice: if you mainly wanted strategies running quickly and accepted Freqtrade's risk model as it is. The brief explicitly does not want that.

---

## Part B: Kraken facts

### B1. Stablecoins tradable from France, and their fee schedule

- **Delisted for EEA clients** (deposit/withdraw only): DAI, PYUSD, UST, EURT, **USDT**, TUSD, USDD, USDS (page updated 29 Oct 2026). https://support.kraken.com/articles/stablecoin-offerings-for-eea-clients
- An April 2026 version of the same page also listed **RLUSD** as delisted. It is absent from the 29 Oct version, and no RLUSD pairs appear in the `country_code=FR` AssetPairs listing. **Treat RLUSD as unavailable.** https://support.kraken.com/gb/articles/stablecoin-offerings-for-eea-clients
- Kraken's global stablecoin list (updated 5 Nov 2026) includes USDC, EURC, EURQ, EURR, USDG, USDe, USDQ, USDR, EUROP and others. https://support.kraken.com/articles/stablecoins-supported-on-kraken
- **Public AssetPairs filtered with `country_code=FR`** (unauthenticated, 2026-11-11) returns, among others: `XBT/EUR`, `ETH/EUR`, **`XBT/USDC`, `ETH/USDC`**, **`XBT/EURC`, `ETH/EURC`**, `SOL/EURC`, `XBT/EUROP`, `XBT/EURCV`, `XBT/USDQ`, `USDC/EUR`, `EURC/EUR`, `EURQ/EUR`, `EUROP/EUR`, `USDG/USDC`. **`EURR` and `USDR` pairs are `post_only`.** No USDT, USDe or RLUSD pairs. https://api.kraken.com/0/public/AssetPairs?country_code=FR , param doc: https://docs.kraken.com/api/docs/rest-api/get-tradable-asset-pairs/ . Caveat: this is the public regional filter. Your account's own eligibility is confirmed only when you log in.
- **Fee schedule:** when the stablecoin is the **quote** (for example BTC/USDC, BTC/EURC), the **standard spot crypto schedule** applies and counts toward 30-day volume. When the stablecoin is the base (USDC/EUR) or both legs are stablecoins, the **stablecoin/FX schedule** applies. https://support.kraken.com/articles/360039299431-how-do-stablecoin-fx-fees-work-
- Stablecoin/FX entry rate: **0.20% maker = taker**. https://www.kraken.com/pro/fees
- **Implication:** a stablecoin route does *not* get cheaper crypto trading. BTC/USDC pays 0.40/0.80% like BTC/EUR, plus a 0.20% conversion each way EUR to USDC to EUR. For the euro-denominated stablecoin option, **BTC/EURC** avoids a USD FX exposure.
- **Brief check:** "USDT is not available to EEA clients" is correct. Also add: RLUSD is unavailable, EURR is post-only, and USDC/EURC/EUROP/EURQ are the realistic choices.

### B2. Kraken Pro spot fees (entry tier)

Tier 1 ($0+ 30-day volume): **0.40% maker / 0.80% taker**. Tier 2 starts at $2.5K: 0.30/0.60. https://www.kraken.com/pro/fees . **The brief's sanity numbers are correct.**

Two related changes affect how the code must read fees:
- AssetPairs `fees` / `fees_maker` are **deprecated as of 8 Sep 2026 and always `[]`**. https://docs.kraken.com/api/docs/rest-api/get-tradable-asset-pairs/
- As a result, ccxt `markets[s]['taker'/'maker']` parse as `None`. ccxt's hard-coded `describe()` defaults are the obsolete 0.26%/0.16%. https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/kraken.py
- **Read fees only via `fetch_trading_fee(symbol)` (TradeVolume)**, and fail closed if that call fails. Do not use the market-level fee fields.

### B3. Can the bot discover its own key's permissions? **Yes. The brief's "if the API allows it" is resolved positively.**

- `POST /0/private/GetApiKeyInfo`: requires **no permission**. It returns `permissions` (array of strings: `query-funds`, `add-funds`, **`withdraw-funds`**, `earn-funds`, `query-open-trades`, `query-closed-trades`, `modify-trades`, `close-trades`, `query-ledger`, `export-data`, `create-ws-token`, **`add-withdraw-address`, `update-withdraw-address`**), `ip_allowlist`, `valid_until`, `nonce_window`, `created_time` and `last_used`. https://docs.kraken.com/api-reference/account-data/get-api-key-info.md
- Note: the schema says snake_case but the doc example uses camelCase. Parse both, and fail closed if the field is missing.
- ccxt exposes it as the implicit method `privatePostGetApiKeyInfo` (present in the kraken `api.private.post` list). There is no unified ccxt method. https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/kraken.py
- **Startup rule:** refuse to start if `withdraw-funds`, `add-withdraw-address` or `update-withdraw-address` is present, or if the call or parse fails. Also, at M6, print `ip_allowlist` (empty means not restricted), which turns the brief's M6 reminder into a check. The call is read-only, but it is authenticated, so it must never run in tests (use the fake broker).
- **Fallback heuristic** (only if GetApiKeyInfo were unavailable): call `WithdrawMethods` with no optional params. It requires both "Funds - Query" **and "Funds - Withdraw"**, takes only a `nonce`, and only lists methods (no side effects documented). Success means withdraw is enabled, so refuse. `EGeneral:Permission denied` means it is disabled. Any other error means refuse (fail closed). https://docs.kraken.com/api/docs/rest-api/get-withdrawal-methods/ . ccxt maps `EGeneral:Permission denied` to `PermissionDenied` and `EAPI:Invalid key` to `AuthenticationError`. https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/kraken.py . `WithdrawInfo` also only returns fee and limit info, but needs `asset`, `key` (a saved withdrawal key name) and `amount`, so it is less convenient. **Never call `Withdraw`.** https://docs.kraken.com/api/docs/rest-api/get-withdrawal-information/
- Required permission names (Kraken UI): Query Funds, Deposit Funds, Withdraw Funds, Query Open/Closed Orders & Trades, Create & Modify Orders, Cancel/Close Orders, Query Ledger Entries, Export Data, Access WebSocket API. Error text: `EGeneral:Permission denied`. https://docs.kraken.com/exchange/guides/rest/api-keys.md
- Brief note: "query and trade permissions only" means the bot needs **Query Funds** (Balance, TradeVolume), **Query Open and Closed Orders & Trades**, **Create & Modify Orders** and **Cancel/Close Orders**. Query Ledger Entries is optional, for ledger cross-checks.

### B4. Client order IDs: `cl_ord_id` vs `userref`

- `cl_ord_id`: a string, either a UUID (with or without dashes) or **free text of up to 18 ASCII characters**. It "uniquely identifies an open order for each client". `userref`: int32, **non-unique**, for grouping. The two are **mutually exclusive** on one order. https://docs.kraken.com/api/docs/rest-api/add-order/ , https://docs.kraken.com/api/docs/guides/spot-clordid/
- **The uniqueness check covers *open* orders only.** The behaviour on a duplicate is not documented. Consequence: if a market order fills instantly and the request then times out, **a blind resend with the same `cl_ord_id` would not be rejected and would create a duplicate.** The brief's assumption that "a retried request can never create a duplicate order" is therefore **not guaranteed by Kraken**. The guarantee has to come from the bot.
  **Proposed rule:** persist the intent with its `cl_ord_id` *before* sending. On timeout or unknown outcome, never resend. Instead query `OpenOrders` and `ClosedOrders` filtered by `cl_ord_id` (both accept a `cl_ord_id` filter). Only if both are definitively empty after a grace period may a new attempt go out, and it gets a **new** id.
  https://docs.kraken.com/api/docs/rest-api/get-closed-orders/ , https://docs.kraken.com/api/docs/rest-api/get-orders-info/ (QueryOrders requires `txid`, so it is not usable for lookup by `cl_ord_id` alone)
- Cancel by `cl_ord_id` is supported. https://docs.kraken.com/api/docs/guides/spot-clordid/
- **ccxt:** `create_order(..., params={'clientOrderId': x})` maps to `cl_ord_id`. `parse_order` fills `clientOrderId` from `cl_ord_id`, falling back to `userref`. https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/kraken.py
- Keep the id at 18 characters or fewer (for example `b` + base32 of a sequence and date), or use a UUID.
- `AddOrder` has `validate=true` (validate only, no matching). That is useful for a manual M6 smoke test, but it is still the live trading endpoint, so **not in tests**. https://docs.kraken.com/api/docs/rest-api/add-order/

### B5. Minimums and fee tier via ccxt

Live public AssetPairs values (2026-11-11):

| Pair | ordermin (base) | costmin (quote) | tick_size | lot_decimals |
|---|---|---|---|---|
| XBT/EUR | **0.00006 BTC** | **0.45 EUR** | 0.1 | 8 |
| ETH/EUR | **0.002 ETH** | 0.45 EUR | 0.01 | 8 |
| XBT/USDC | 0.00006 BTC | 0.5 USDC | 0.01 | 8 |
| USDC/EUR | 5 USDC | 0.45 EUR | 0.0001 | 8 |
| EURC/EUR | 4 EURC | 0.45 EUR | 0.0001 | 8 |

Source: https://api.kraken.com/0/public/AssetPairs?pair=XBTEUR,XBTUSDC,ETHEUR,USDCEUR,EURCEUR . Field meanings: https://docs.kraken.com/api/docs/rest-api/get-tradable-asset-pairs/

- **The brief's minimums are out of date.** "€5 for EUR-quoted orders, 0.0001 BTC, 0.01 ETH" matches Kraken's support article (https://support.kraken.com/articles/360001389303-order-minimums), but the live API now says 0.00006 BTC, 0.002 ETH and a 0.45 EUR cost minimum. The cost-minimum article lists 0.45 EUR / 0.5 USD and the rejection "Cost minimum not met". https://support.kraken.com/articles/12425041458708-cost-minimum-for-trading
- In practice, the binding constraint for BTC/EUR is `ordermin` × price (that is, `ordermin` in EUR at current prices), not €5. The brief's instruction to read the values from metadata is right. Only the reference numbers are stale.
- ccxt mapping: `limits.amount.min` comes from `ordermin`, `limits.cost.min` from `costmin`, and price precision from `pair_decimals` (precisionMode TICK_SIZE). The pre-trade check must enforce **both** amount min and cost min. https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/kraken.py
- Watch `status`: values other than `online` (`post_only`, `limit_only`, `cancel_only`, `reduce_only`) must block or constrain orders. https://docs.kraken.com/api/docs/rest-api/get-tradable-asset-pairs/
- **Fee tier:** `has['fetchTradingFee'] = True`, `has['fetchTradingFees'] = False`. Use `exchange.fetch_trading_fee('BTC/EUR')`, which calls `TradeVolume` with `pair` and `fee-info`. That needs the Query Funds permission, and `fee-info` is a "legacy parameter". Raw response: `fees[pair].fee` (taker %), `fees_maker[pair].fee`, `volume`, `nextfee`, `tiervolume`. https://docs.kraken.com/api/docs/rest-api/get-trade-volume/ , https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/kraken.py
- In backtests, which cannot call an authenticated endpoint, use the configured schedule (0.40/0.80) and cross-check it against `fetch_trading_fee` at dry-run and live startup.

### B6. OHLC history depth (M1: "several years of daily and 4h candles")

- **Confirmed:** `GET /0/public/OHLC` "Returns up to 720 of the most recent entries (older data cannot be retrieved, regardless of the value of `since`)". Intervals: 1, 5, 15, 30, 60, **240**, **1440**, 10080, 21600. https://docs.kraken.com/api/docs/rest-api/get-ohlc-data/
- ccxt hard-codes `fetchOHLCV.limit: 720` for Kraken spot. Pagination cannot go past the window. https://raw.githubusercontent.com/ccxt/ccxt/master/python/ccxt/kraken.py
- Freqtrade's Kraken notes say the same ("only provides 720 historic candles... not for backtesting"). https://www.freqtrade.io/en/stable/exchanges/
- **What 720 candles cover:** 1d is about 23.7 months, and **4h is only 120 days**. **The brief's M1 cannot be met through ccxt `fetch_ohlcv` alone.** It gives under 2 years of daily data and 4 months of 4h data.

Options:

1. **Kraken's official downloadable OHLCVT CSVs (recommended).**
   - What it is: full history from the first trade to 30 Jun 2026, as `Kraken_OHLCVT_Full.zip`, split into 5 parts of about 2 GB each. Quarterly update ZIPs exist for 2026 Q1, Q2 and Q3.
   - Intervals include 240 and 1440. Columns are `timestamp, open, high, low, close, volume, trades`, with **no header row**.
   - **Empty intervals are omitted, not zero-filled.**
   - SHA256 checksums are published for the parts and for the reassembled ZIP. Hosted on `assets.kraken.com`.
   - Source: https://support.kraken.com/articles/360047124832-downloadable-historical-ohlcvt-open-high-low-close-volume-trades-data
2. **Rebuild candles from `GET /0/public/Trades`.** Up to 1000 trades per call, `since` in nanoseconds, paginate via `last`. Kraken suggests 1–2 s between Trades calls (public limits are per IP and per pair). For BTC/EUR over several years this means tens of thousands of calls, many hours to days, and a lot of RAM (Freqtrade warns about the same). Workable as a fallback only. https://docs.kraken.com/api/docs/rest-api/get-recent-trades/ , https://docs.kraken.com/exchange/guides/general/historical-data.md , https://support.kraken.com/articles/206548367
   - Note: Kraken's developer guide says "Kraken does not provide a bulk historical data dump". This contradicts the support article above, which is current and has 2026 files. Trust the support article.
3. Third-party data vendors would add a new dependency or account and a provenance question. Not recommended.

**Recommended M1 approach, using only allowed dependencies (stdlib `zipfile`, `hashlib`, `csv`; `pandas`, `pyarrow`, `ccxt`):**

1. **Download once, by hand.** You download the full archive parts and the 2026 Q3 ZIP from the support page into a data folder outside the repo. The bot should not auto-fetch 10 GB.
2. **Verify.** Check each part against the published SHA256, concatenate the parts with stdlib (binary append), then check the final SHA256.
3. **Extract only what's needed.** Open the ZIP with `zipfile` and stream only the members for the chosen pair at 240 and 1440 minutes; do not unpack the archive. Read them with `pandas.read_csv(header=None, names=[...])`, convert timestamps to UTC (verify that the units are Unix seconds on the first file), and write Parquet.
4. **Top up recent data.** Append the Q3 2026 ZIP rows, then fetch the latest 720 candles via ccxt `fetch_ohlcv`. 120 days of 4h reaches back to mid-July 2026, so it overlaps Q3 and closes the gap to today.
5. **Validate the overlap.** For candles present in both the CSV and the API, OHLCV must match within a tolerance, otherwise fail loudly. This is the provenance check.
6. **Gap policy (required because empty intervals are omitted).** The validator should separate "no-trade interval" from "download gap" (for example, a missing interval inside the CSV range is a no-trade candle, which matters for illiquid early years). Make the policy explicit in config: either forward-fill close with volume 0 and flag it, or start the history at a date after which the pair has no gaps. The brief's "no gaps" rule, applied naively, will fail on legitimate no-trade periods.
7. Ongoing updates in dry-run and live come from ccxt `fetch_ohlcv` (the 720-candle window is ample). Optionally re-import each new quarterly ZIP.

---

## Where the brief's assumptions are wrong or need amending

1. **Section 3, minimum order sizes:** the live API says 0.00006 BTC, 0.002 ETH and a 0.45 EUR cost minimum, not €5 / 0.0001 / 0.01. The "read from metadata" instruction is correct, so keep it and update the reference numbers.
2. **Section 3, fees "read the live rates from the API":** the market metadata no longer carries fees (deprecated 8 Sep 2026), and ccxt's defaults are stale (0.26/0.16). Only `fetch_trading_fee` (TradeVolume) is valid. The 0.40/0.80 sanity figures are correct.
3. **Section 3, stablecoins:** USDT is indeed out. RLUSD is also unavailable, EURR/USDR are post-only, and USDC/EURC/EUROP/EURQ are available. Crypto/stablecoin pairs use the *standard* 0.40/0.80 schedule, and the EUR to stablecoin legs cost 0.20%.
4. **Section 4, permission check "if the API allows it":** it does, via `GetApiKeyInfo`. Make the check mandatory and fail closed, and extend it to the `add-withdraw-address` and `update-withdraw-address` permissions.
5. **Section 5.4, "client order IDs so a retry can never create a duplicate":** Kraken enforces `cl_ord_id` uniqueness only among *open* orders. Idempotency must be implemented as query-before-retry, never as a blind resend.
6. **Section 5.1 / M1, "several years of daily and 4h candles" via ccxt:** this is impossible through OHLC/ccxt (720-candle cap). It needs Kraken's OHLCVT CSV archive (or a trades rebuild), and the validator needs a no-trade-interval policy.
7. **Section 13, "Freqtrade ... ships with ... a look-ahead bias checker" and "custom work limited to the risk rules it lacks, the ledger export and the dry-run-vs-backtest view":** the first part is correct. The custom-work estimate is too small, because client order IDs, reconciliation stop-on-mismatch, manual-reset halts, the permission check, the read-only dashboard, no-rounding minimums and backtester slippage are also missing or conflicting.
