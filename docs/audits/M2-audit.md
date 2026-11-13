# M2 independent audit

- **Scope:** branch `m2-backtest` (HEAD `d438403`) against `main`. 17 commits, `8f212f5` .. `d438403`.
- **Auditor:** a fresh subagent that did not write any of the M2 code. I checked every claim below in this session. I did not take PROGRESS.md, commit messages, story plans or the builder's reports on trust.
- **Date:** 2026-11-13.
- **Method:**
  - Ran the checks and the real backtest myself.
  - Read `git log -p main..m2-backtest` and counted the removed test lines in each commit.
  - Read the code for the dataset loader, replay market data, fill model, paper broker, engine, sizing, metrics, report, holdout and guard.
  - Planted three look-ahead leaks of my own, in memory, against the project's synthetic test environment.
  - Re-ran the real backtest in memory with the €25 absolute cap lifted, to split the gap to buy-and-hold into a cap part and a strategy part.
  - Reconstructed the intraday (15m) equity of the real run to see whether the protected halts would have fired.
  - All scratch scripts and outputs are in the session scratchpad. I modified no project file apart from this report. I ran no holdout mode.

## Overall verdict: PASS with findings (one High)

- **M2 meets its acceptance criterion.** One command (`uv run bot backtest`) writes a SIMULATED report with metrics and both benchmarks at maker and taker rates, and the look-ahead guard test passes. The real run reproduced byte-for-byte, apart from provenance fields.
- **Git history is clean:**
  - No test was deleted, skipped or weakened.
  - The protected-file discipline held.
  - No holdout run exists.
  - No dependency was added.
- **One finding is High (F-1).** The backtest only ticks once a day outside execution windows, so the protected daily-loss halt is effectively never evaluated. In my reconstruction of the real run, a live engine ticking every 30 s would have halted on **2017-07-25**, 5 days into the evaluation, and on 31 days in total. The report presents results for a bot that, as configured, would have stopped trading.
- **Two findings are Medium:**
  - F-2: the guard misses an off-by-one leak in the data adapter. I demonstrated this.
  - F-3: the completion phase gets its own 12-submission budget, which reinterprets a protected limit.
- **The €25 cap explains roughly half of the gap to buy-and-hold at maker fees**, and about a third at taker fees. Without the cap, the strategy still loses to buy-and-hold at both rates.

| # | Item | Rating |
|---|---|---|
| 1 | Checks and real backtest run by the auditor | PASS |
| 2a | Deleted / skipped / weakened tests (incl. the two changed tests) | PASS |
| 2b | Protected files | PASS |
| 2c | Holdout runs on real data | PASS (none) |
| 2d | Dependencies, secrets, large data | PASS |
| 3 | Look-ahead bias (code + guard) | PASS for the current code; guard has blind spots (F-2, F-6) |
| 4 | Costs, minimums, precision, non-fillable synthetic candles, fill realism | PASS |
| 5 | Overfitting / statistics / verdict line | PASS |
| 6 | Benchmark fairness (cap vs strategy) | INCONCLUSIVE until the report carries a diagnostic (F-4) |
| 7a | Separate 12-submission budget for completion | INCONCLUSIVE: operator decision (F-3) |
| 7b | Keep resting order during exchange halts | PASS for the backtest; flag for M3 (F-5) |
| 7c | Pricing from last closed 15m candle / tick cadence | Pricing PASS; tick cadence FAIL (F-1) |
| 8 | M2 acceptance criterion | PASS |

## 1. Checks run by the auditor: PASS

| Command | Result |
|---|---|
| `uv run ruff check .` | `All checks passed!` (exit 0) |
| `uv run ruff format --check .` | `208 files already formatted` (exit 0) |
| `uv run pytest -q` | `781 passed in 32.56s` (exit 0); no skips, xfails or errors |
| `uv lock --check` | `Resolved 65 packages` (exit 0) |
| `uv run bot backtest --results-dir <scratchpad>/bt` | exit 0. Line 1 is the verdict below. |

The verdict line from my run:

```
VERDICT (SIMULATED): v0_trend does NOT beat buy-and-hold after costs (at both maker and taker fees): total return +689.4% vs buy-and-hold +4495.1% at maker fees, +648.9% vs +4476.4% at taker fees (2017-07-20..2025-11-10).
```

Notes on the run:
- **Holdout exclusion checked before running:**
  - `default_request` ends the range at `backtest.holdout_start` (2025-11-11), exclusive.
  - `_check_range` refuses any later end.
  - `load_dataset` raises `HoldoutViolation` itself unless `allow_holdout=True`, and only `--holdout` passes that.
- **Results went to the scratchpad, on purpose.** I used `--results-dir` so that the builder's untracked `results/2026-11-13_v0_trend_d438403cae55.*` would not be overwritten. That overwrite would have flipped `git_dirty` to true, because the untracked files make the tree dirty. No file under `results/` changed.
- **The run reproduces.** My JSON is identical to the builder's `d438403cae55.json` except for `git_commit`/`git_dirty` (`git_dirty: true` in mine, because of the untracked files). The builder's `d438403cae55` and the committed `498d80c6edaa` reports are also identical except for the commit hash.

## 2. Git history

### 2a. Deleted, skipped, xfailed or weakened tests: PASS
- No test file was deleted. No `skip`, `xfail` or `importorskip` was added; all `skip` hits are `# fmt: skip`. No tolerance was loosened.
- Removed test lines per commit:

  | Commit | Removed test lines |
  |---|---|
  | `dacdba0` | 3 |
  | `c6f6093` | 7 |
  | `fa4f3f8` | 5 |
  | `8d7cfa4` | 6 |
  | `498d80c` | 91 |
  | all others | 0 |

  I read every removed line:
  - `c6f6093`: the CLI leak test went from `code in (EXIT_REFUSED, EXIT_LOOKAHEAD)` to `code == EXIT_LOOKAHEAD` plus a stderr assertion. That is **stricter**.
  - `fa4f3f8`: "fee > 0" became an exact fee/slippage check, which is stricter. One sizing case (a half-in top-up) was replaced by an unsellable-partial case of the same strength.
  - `8d7cfa4`: `check_change` gained a strategy argument, and the assertions were kept.
  - `498d80c`: the known-outcome suite was rewritten so that it asserts hand-derived results at **both** rates and the exact verdict line. That is stricter than the `startswith` checks it replaced.
- **`tests/test_cli.py` (backtest stub test): legitimate.** `backtest v0_trend` is now implemented and covered by `tests/backtest/`. `dry-run` (both strategies) and `backtest plumbing` are still asserted to be unimplemented.
- **`tests/test_config.py` ("no fee words"): legitimate.** The ban was narrowed to "no `maker`/`taker` outside `fees:`", in the parsed YAML. A new test pins `fees.maker == 0.0040`, `fees.taker == 0.0080`, `source == published_schedule` and `sma_days == 200`. It still bans hardcoded minimums and tick size.
  - The change follows the coordinator's decision to use published fees instead of `fetch_trading_fee`. That decision supersedes an earlier decision-log entry and deserves explicit operator ratification (F-8). It is not a test weakening.

### 2b. Protected files: PASS
- Only `b140a9b` ("PROTECTED: M2 story 2") touches `bot/risk/` or `tests/risk/`, and it touches nothing else. `bot/risk/limits.py` is unchanged.
- `config.yaml` changed in `dacdba0` and `fa4f3f8`. The `risk:` section is byte-identical to `main` (`git diff main..m2-backtest -- config.yaml` has no hunk below the PROTECTED marker).

### 2c. Holdout runs on real data: PASS (none)
- `results/holdout_runs.jsonl` does not exist, and no commit has ever added or deleted it.
- Both real reports state `holdout runs recorded for this strategy: 0` and `excluded (not loaded, not run)`.
- `git log --all -- results` shows a single commit (`bd1b91a`), and no results file was ever deleted.

### 2d. Dependencies, secrets, large data: PASS
- `pyproject.toml`, `uv.lock` and `tests/conftest.py` are unchanged.
- No secret-like strings appear in the diff, and no `.parquet`, `.zip`, `.csv`, `.db` or `.env` file was added.
- The largest new data file is the committed 832-byte public market snapshot.

## 3. Look-ahead bias: PASS for the current code, with guard gaps (F-2, F-6)

**Code read (no leak found):**
- **Signal at t's close, acted on at t+1.** `ReplayMarketData.closed_candles` returns rows with `open_at + interval <= now`, and `CandleHistory.from_frame` re-checks that exactly in microseconds. The first engine tick after daily candle t is t's close + 30 s, and `_maybe_signal` journals the signal against t.
- **The SMA uses closed candles only.** `close[-sma_days:]` comes from that closed history, which includes t and never the forming t+1.
- **Maker fills.** The order is accepted at 00:00:30. `ceil_to_boundary` makes the first eligible 15m candle the one opening at 00:15, so the 00:00–00:15 candle, which began before the order, is excluded. That is conservative. `_evaluate` only reads closed 15m candles, and fills are stamped at the candle close.
- **Taker variant.** It fills at 00:00:30 at the ask/bid built from the 23:45–00:00 close. That is the t+1 open price in practice, built only from data available at t's close. This is a deviation from AD-5's "t+1 open", but it is causal and documented.
- **No resampling.** 1d and 15m are separate validated files, and their consistency was checked in M1. The ticker is the last closed, non-synthetic 15m close.
- **Holdout rows are filtered out.** They are read for whole-file validation, but `load_dataset` filters them out before any consumer sees them.

**The guard.** It reruns the full pipeline at 12 seeded cutpoints, each with a random walk and its mirror, and compares journaled targets for candles ≤ k. The real run reports `PASSED (12 cutpoints x 2 futures, 13263 candle targets compared)`. The planted test `tests/test_lookahead.py::test_planted_t_plus_1_leak_raises_and_no_report_is_written` passes.

**My own planted leaks** (`plant_leaks.py`, `plant_a_check.py`, synthetic zig-zag env):

| Planted leak | Effect on trades | Guard |
|---|---|---|
| A. `ReplayMarketData.closed_candles` off by one day for 1d (strategy sees the forming candle) | Trades change: the leaky run buys a day early at 100.05 vs the baseline's 101.65 | **NOT CAUGHT** (F-2) |
| B. PaperBroker judges fills with a clock 6 h ahead | Structural; the guard compares targets only and stops before fills on replaced data | **NOT CAUGHT** (F-6, by design) |
| C. Strategy long iff \|next daily move\| > 2% (non-directional) | — | CAUGHT |

Why A escapes: the guard keys its comparison on the candle **label** the adapter reports. With an off-by-one adapter, the leaked decision is labelled k+1, so it falls outside the "≤ k" comparison. The current adapter is correct, so this is a defence-in-depth gap, not a live leak.

## 4. Costs and execution realism: PASS
- **Fees:**
  - Every simulated fill pays a fee. The maker run pays the maker rate (0.40%) and the taker run pays the taker rate (0.80%), and the report shows both (CON-06).
  - Buy-and-hold pays its entry fee, slippage and (in the taker run) the half spread.
  - Both strategy and benchmark are marked at mid with no exit cost, which is symmetric and stated in the caveats.
- **Slippage.** 5 bp is applied against the trader on every fill (`slipped`). For a resting limit, this is a pure cost cushion, which is conservative.
- **Minimums and precision:**
  - PaperBroker rejects an order whose `qty < amount_min`, whose `qty × price < cost_min`, whose price is not a multiple of the tick, or whose qty is not a multiple of the step.
  - Sizing floors qty to the step and returns `NoOrder("below_minimum")` with a risk event. It never rounds up to a minimum.
  - Test: `test_sub_minimum_capital_is_rejected_logged_and_counted_never_rounded`.
  - Caveat, stated in the report: today's minimums are applied to 2017–2025. Kraken's historical BTC minimum, about 0.002 BTC, would have mattered at €20.
- **Synthetic candles never fill.** This is covered by `simulate_maker`, by `test_synthetic_candle_never_fills` and by `test_window_of_synthetic_candles_never_fills_and_ends_not_filled`. The 2018-01-13 anomaly day has 0 fills in both variants.
- **Post-only realism:**
  - A buy fills only on a **strict** trade-through (`low < L`), not on a touch.
  - It fills in full at L, with no queue modelling and no partial fills. That is mildly optimistic but immaterial for a €20–€160 order on BTC/EUR.
  - Adverse selection is modelled naturally, because maker buys fill on dips.
  - The 1 bp simulated half spread is plausible for BTC/EUR today, but optimistic for 2017–2018 (F-9).
- **Side effect of always filling in full:** the AD-28 completion phase never runs in the backtest (it needs a partial fill). The 76 maker fills are all full.

## 5. Overfitting and statistics: PASS
- **Parameters were fixed before evaluation.**
  - `sma_days: 200` entered `config.yaml` in `dacdba0` (17:23). The first real results commit is `bd1b91a` (18:06), and no results file exists in any earlier commit.
  - `changes.md` records the baseline and "No changes yet". The JSON records `configurations_tried: 1`.
  - Caveat: real runs that were not committed cannot be ruled out from git alone. There were at least two real runs (`498d80c`, `d438403`), both of the same configuration and with identical results.
- **Search.** `bot/backtest/search.py` refuses holdout ranges and writes the trial count. It has no CLI entry point and was not used.
- **Bootstrap CI.** It is a circular moving-block bootstrap of daily simple returns (20-day blocks, 2000 resamples, seeded), using 2.5/97.5 percentiles. That method is sound for autocorrelated returns.
  - Strategy (maker): Sharpe 0.89 [0.05, 1.70].
  - Buy-and-hold: Sharpe 1.02 [0.28, 1.75].
  - The intervals overlap heavily, and nothing can be claimed either way.
- **Walk-forward.** These are consecutive 365-day out-of-sample slices of one continuous run, with no refit because there is one configuration. They stop before the holdout (a `HoldoutViolation` guard exists), and their boundaries match the report. Calling them walk-forward is fair only because nothing is fitted; they are sub-period analysis.
- **Verdict line (§5.3).** Line 1 says "does NOT beat buy-and-hold after costs (at both maker and taker fees)" with both totals, and line 3 is the SIMULATED label. The logic is "beats only if better at both rates", which is correct and is tested with exact lines.

## 6. Benchmark fairness, cap vs strategy: INCONCLUSIVE until the report carries a diagnostic (F-4)

I used the project's own pipeline (`load_dataset` → `run_backtest` → `strategy_metrics`/`buy_and_hold_metrics`) on the same pre-holdout range. The second run lifts `max_position_abs_quote` to 1e12 **in memory only**. Script: `cap_diag.py`.

| Maker | Strategy, €25 cap (as built) | Strategy, no abs cap | Buy-and-hold |
|---|---|---|---|
| Total return | +689.4% | **+1756.2%** | +4495.1% |
| Final equity (€) | 157.88 | 371.24 | 919.03 |
| Annualized | +28.2% | +42.1% | +58.5% |
| Max drawdown | 61.0% | 63.0% | 82.5% |
| Sharpe [95% CI] | 0.89 [0.05, 1.70] | 0.94 [0.13, 1.71] | 1.02 [0.28, 1.75] |
| Fills / fees (€) | 76 / 8.11 | 76 / 65.98 | 1 / 0.08 |

| Taker | Strategy, €25 cap | Strategy, no abs cap | Buy-and-hold |
|---|---|---|---|
| Total return | +648.9% | **+1280.2%** | +4476.4% |
| Final equity (€) | 149.79 | 276.05 | 915.29 |
| Fees (€) | 16.97 | 110.84 | 0.16 |

- **Decomposition of the log gap to buy-and-hold:**
  - Maker: the cap accounts for ln(18.56/7.89) = 0.86 of 1.76, about **49%**, and the strategy itself for about **51%**.
  - Taker: the cap accounts for about **34%** and the strategy for about **66%**.
- **The verdict does not change without the cap.** The strategy still does not beat buy-and-hold at either rate, so the cap does not flip the conclusion. Neither run halted.
- **Recommendation:** add a clearly labelled section to every report: "DIAGNOSTIC (not a configuration tried; protected limits unchanged): sizing without the €25 absolute cap". Write it to the JSON under a separate `diagnostics` key.
  - It changes no strategy parameter and must never feed any selection, so it should **not** count toward `configurations_tried`.
  - It must be computed for every report with the same fixed rule, recorded transparently, and never used to pick between variants. If it is ever used to choose something, it becomes a trial and must be counted.
  - The later walk-forward folds (2022–2025) are dominated by the cap: the strategy has about €25 exposed out of €100+ equity, so the diagnostic matters most there.

## 7. Points the builder flagged

### 7a. Separate 12-submission budget for the completion phase: INCONCLUSIVE, operator decision (F-3)
- **What the code does.** `Engine._phase_submissions` passes the count for the current phase only into `RiskContext.intent_submissions`. The protected `check_order` (line 137) compares that value with `max_submissions_per_intent` (12).
- **The effect.** One intent can make up to 24 submissions (12 in the window plus 12 in completion), still under the daily cap of 120.
- **Why it needs ratification.** The protected comment says "submissions (first + re-prices) per order intent". The meaning of a protected limit is being changed by unprotected engine code.
- **Assessment.** The change is safety-neutral (the daily cap still binds, and completion exists to avoid unsellable dust). It has no effect on the backtest, because the fill model never partially fills.
- **Alternatives for the operator:**
  - (a) ratify the per-phase reading, or
  - (b) keep 12 for the whole intent and accept dust when it runs out.

### 7b. Keep the resting order during exchange halts: PASS for the backtest, flag for M3 (F-5)
- **In the backtest this is realistic or conservative.** Synthetic candles never fill. When trading resumes, the stale limit can fill at a worse-than-market price, as a real resting order would.
- **In dry-run and live it carries risk.** The same branch fires when *our own feed* is stale (`now - ticker.ts > 120 s`), not only during an exchange halt. A resting order then keeps working while the bot is blind, for up to the 6 h window, and the price-sanity check no longer applies to it.

### 7c. Pricing from the last closed 15m candle, and tick cadence: pricing PASS, cadence FAIL (F-1)
- **Pricing is strictly causal.** `get_ticker` uses the close of the last closed, non-synthetic 15m candle ± 1 bp, timestamped at that close. Ticker age at each backtest tick is 30 s.
- **The tick cadence breaks the halts.** Outside execution windows the backtest ticks only at 00:00:30. The day-open equity snapshot is written on that same tick, so the daily-loss comparison is equity against itself. The halt can only fire inside a 6 h window after a signal (see F-1).

## 8. M2 acceptance criterion: PASS
"A backtest report with metrics and benchmarks is generated from one command, and the look-ahead guard test passes":
- `uv run bot backtest` exits 0 and writes the JSON and Markdown.
- The report includes every metric in §5.3: total and annualized return, max drawdown, Sharpe with bootstrap CI, trades, turnover, fees, and time in market. Each is shown against buy-and-hold and cash, at both rates, and the verdict comes first.
- The guard test passes in the suite, and the guard passed on the real run.

## Findings by severity

### High
- **F-1: the backtest does not evaluate the protected daily-loss halt intraday.** Outside execution windows it ticks only at 00:00:30, and that tick is also the day-open snapshot. A live engine ticks every 30 s.
  - **Evidence** (`halt_diag.py`): I reconstructed the real maker run's cash and position from its fills and marked equity at every non-synthetic 15m close.
    - Equity fell to ≤ 90% of day-open on **31 days** (48 with no abs cap).
    - The first was **2017-07-25**: €24.03 → €21.47, −10.7%.
    - Others include 2017-12-21 (−20.5%) and 2017-12-22 (−29.1%).
    - Total drawdown never fell to ≤ €15, so that halt is correctly not triggered.
  - **Consequence.** Under the configured protected limits, the bot would have halted (manual reset) 5 days into the evaluation. The backtest ends at a halt, so a faithful backtest would have stopped there.
  - **The report's numbers describe a bot without an effective daily-loss limit.** This also matters for M3/M5 expectations: about 3.7 halts per year at full exposure on BTC.
  - **Fix options:** evaluate halts at every 15m close while a position is held (a cheap extra tick), and report halt events. The operator decides what a backtest does after a halt: end the run, as today, or simulate a reset the next day and count it. The report must state the count either way.

### Medium
- **F-2: the guard misses an off-by-one leak in the data adapter.** I demonstrated this with planted leak A. The guard compares targets by the candle label the adapter reports, so a shifted label hides the leak.
  - **Fix:** compare every signal *evaluated* at or before `cut + lag`, regardless of label, and/or assert in the engine that `candle_open_at + interval <= evaluated_at` for every signal. Add a test that plants the off-by-one.
- **F-3: the per-phase submission count reinterprets the protected `max_submissions_per_intent`** (7a). It needs explicit operator ratification, or a revert to a whole-intent count.
- **F-4: the report has no quantified cap diagnostic.** The caveat is there, but without numbers the reader cannot tell how much of the 689% vs 4495% gap is the cap: about half at maker fees, a third at taker. Add the labelled diagnostic section (§6).

### Low
- **F-5: on own-feed staleness, the resting order is kept** (7b). For M3, cancel on our own staleness (cancels reduce risk and are always allowed). Keep the order only when the exchange status shows a halt, or document why not.
- **F-6: the guard compares targets only.** Engine- or broker-side peeking (planted leak B) is covered only by unit tests: `test_candle_that_began_before_the_order_never_fills_it` and `test_new_order_cannot_fill_on_the_candle_it_was_placed_in`. Consider also asserting prefix invariance of fills and orders before each cutpoint.
- **F-7: duplicate real run left untracked.** `results/2026-11-13_v0_trend_d438403cae55.{json,md}` is a second real run of the same configuration at a docs-only commit. Its content is identical. Commit it or delete it, and mention it in PROGRESS.md so that the run count stays honest.
- **F-8: governance of the fee decision.** Using the published entry tier in config supersedes the 2026-11-11 decision "fees from fetch_trading_fee only" and changed a test. It was decided by the coordinator, so the operator should ratify it at review.

### Info
- **F-9: execution assumptions applied to all history.** The 1 bp half spread and today's minimums are applied to 2017–2025. Spreads and minimums were wider early on, and the €25 cap and minimums interact. This is stated in the caveats.
- **F-10: build pace.** M2 was built in about 1 hour of commit time (17:05–18:06), with review fixes partly in shared commits. The tests are substantive and the history is readable, but the operator's own read of the broker, engine and risk code (GL-05) matters more for that reason.
