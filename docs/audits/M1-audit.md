# M1 independent audit

- **Scope:** branch `m1-data` (HEAD `a5bf56b`) against `main`. 19 commits, `cfb1afc` .. `a5bf56b`.
- **Auditor:** a fresh subagent that did not write any of the M1 code. I checked every claim below in this session. I did not take PROGRESS.md, commit messages or the authors' reports on trust.
- **Date:** 2026-11-12 (the checks ran at about 22:04 UTC)
- **Method:**
  - Ran the checks myself.
  - Read `git log -p main..m1-data` and counted the removed test lines in each commit.
  - Read the data, import, validation, trades and history code.
  - Ran `bot data validate` on the real cache.
  - Re-derived the data checks with my own pandas scripts. They read the Parquet files directly and do not use `bot` code.
  - Compared the cache with Kraken's public, unauthenticated OHLC and Trades endpoints. I used `curl`, and the responses went to the scratchpad.
  - Modified no project file apart from this report. Read no secrets. Deleted nothing (`data/raw/` is intact).

## Overall verdict: PASS, with findings

- M1 meets its acceptance criterion. The cache holds 13 years of validated 1d and 4h BTC/EUR candles, and 15m as well. All of it is internally consistent across timeframes and agrees exactly with Kraken's live public endpoint.
- No test was deleted, skipped or weakened. No protected file was touched. No dependency was added.
- No item is FAIL. Two findings are Medium. One is a governance issue: the 15m cap was loosened by the coordinator and needs operator ratification. The other is a requirement M2 must honour: flat no-trade candles also cover exchange halts.

## 1. Checks run by the auditor: PASS

| Command | Result |
|---|---|
| `uv run ruff check .` | `All checks passed!` (exit 0) |
| `uv run ruff format --check .` | `164 files already formatted` (exit 0) |
| `uv run pytest -q` | `596 passed in 10.14s` (exit 0); no skips, xfails or errors in the output |
| `uv lock --check` | `Resolved 65 packages`, consistent (exit 0) |

## 2. Git history

### 2a. Deleted, skipped, xfailed or weakened tests: PASS
- No test file was deleted. The only pre-existing test file that changed is `tests/test_config.py`, and only by additions. `tests/test_clock.py` is new.
- Removed test lines per commit: only `2d3a0b6` (8), `502e4f1` (16) and `ea0f94d` (5). I read every one:
  - `2d3a0b6`: `validate_frame` gained a `DataSettings` argument. The call sites were updated and the assertions are unchanged.
  - `502e4f1`: `import_archive` gained `tick_provider`. One test changed by design: `test_existing_cache_refused_until_story_4`, where story 3's placeholder refusal ("merge arrives in story 4"), became `test_existing_cache_reimport_merges_identically`. The new test asserts frame equality and a zero-diff overlap line, which is stricter, not looser.
  - `ea0f94d`: the expected `sources` dicts and `SOURCE_PRECEDENCE` gained the new `trades` key. Nothing else changed.
- A grep for added `skip`, `xfail`, `importorskip` or loosened `approx`/`rel=`/`abs=` found none that relaxes a check. The `skip` hits are fixture parameter names and `# fmt: skip`. The `approx` calls compare computed tick ratios such as `approx(1.0)`.
- `tests/conftest.py` (the network block) and `pyproject.toml` are unchanged.

### 2b. Extra holdout runs: PASS (not applicable)
There is no backtest code yet, and `results/` does not exist. The cache contains the holdout window as data, which is expected.

### 2c. Protected files: PASS
- `git diff main..m1-data -- bot/risk tests/risk` is empty.
- Four commits touch `config.yaml` (`ae6cc25`, `2d3a0b6`, `502e4f1`, `a142323`). Reviewed hunk by hunk, every one only adds keys under the new `data:` section, above the `# PROTECTED` marker. The `risk:` section is byte-identical to `main`.

### 2d. Dependencies, committed data, secrets: PASS
- `pyproject.toml` and `uv.lock` are unchanged versus `main`.
- No `*.parquet`, `*.zip`, `*.csv`, `.env` or key file was added. `/data/` and `/var/` are gitignored (`.gitignore` lines 21–22, confirmed with `git check-ignore`).
- No API key or secret appears in the diff. `load_secrets()` still raises `NotImplementedError` and is not called.

## 3. Data correctness on the real cache

### 3a. `bot data validate`: PASS (exit 0 for all three)

| tf | rows | first | last | archive / trades / api / synthetic | synthetic ratio from 2017-01-01 (cap) | hash |
|---|---|---|---|---|---|---|
| 1d | 4,811 | 2013-09-10 | 2026-11-11 | 4,764 / 0 / 42 / 5 | 0.0278% (0.1%) | `d008f171…` |
| 4h | 28,866 | 2013-09-10 20:00 | 2026-11-12 16:00 | 28,430 / 0 / 257 / 179 | 0.0509% (0.1%) | `fc370334…` |
| 15m | 461,849 | 2013-09-10 23:45 | 2026-11-12 21:45 | 448,136 / 3,358 / 760 / 9,595 | 0.162% (0.5%) | `0b813d85…` |

The row counts, ranges and hashes match PROGRESS.md.

### 3b. Independent structural re-check (my own script, pandas only): PASS
For each of 1d, 4h and 15m:
- `open_at` is `datetime64[ms, UTC]`, strictly increasing, with 0 duplicates and 0 misaligned rows.
- **0 missing intervals.** Every hole is filled by a row marked `synthetic`.
- 0 OHLC violations: high ≥ max(open, close), low ≤ min(open, close), high ≥ low, prices > 0 and finite, volume ≥ 0.
- 0 non-synthetic rows with zero volume.
- Every synthetic row is flat at the previous close with volume 0.
- The source ranges are contiguous, and each timeframe has exactly one transition between sources:
  - archive → api at 2026-10-01 for 1d and 4h.
  - archive → trades → api for 15m. The archive ends at 2026-09-30 23:45, the trades rows cover 2026-10-01 00:00 → 2026-11-04 23:45, and the API rows start at 2026-11-05 00:00.
- The last candle is closed relative to the time of the check (22:04 UTC):
  - 1d closes at 11-12 00:00.
  - 4h closes at 20:00.
  - 15m closes at 22:00.
- The largest returns are explained:
  - 2013 thin-market moves, all before `history_start`.
  - 2020-03-12 (−37.6% daily), the real Covid crash.

### 3c. Resampling consistency, 15m → 4h, 15m → 1d, 4h → 1d: PASS
I compared every complete bucket: 28,865 for 4h, and 4,810 for each of the two 1d comparisons.
- **Buckets with no synthetic row: 0 mismatches.** The maximum O/H/L/C difference is 0.000 ticks and the maximum relative volume difference is 5.5e-13. That is 27,034 buckets for 15m → 4h, 4,034 for 15m → 1d and 4,753 for 4h → 1d.
- The trades-rebuilt 15m candles agree exactly with Kraken's own API candles: 209 API 4h candles and 34 API daily candles, at 0.000 ticks. This independently confirms the story 9 rebuild.
- Buckets that contain synthetic rows differ only in open, high or low. That covers 291, 77 and 26 open mismatches across the three comparisons, and every one is a bucket whose first row is synthetic. A flat fill takes the previous close, while the coarse archive candle opens at its first real trade. This is a convention difference, not an error. Close and volume always match.
- Cross-timeframe no-trade consistency holds in both directions:
  - 0 coarse candles are synthetic while the finer timeframe shows volume.
  - 0 coarse candles have trades while every finer row is synthetic.

### 3d. Comparison with Kraken's public OHLC endpoint (fetched 2026-11-12, unauthenticated): PASS
- **1d:** all 720 closed candles (2024-11-22 → 2026-11-11) are in the cache.
  - The 678 archive rows have 0.0 EUR difference on every O/H/L/C. The maximum volume difference is 0.039%, and 1 trade count differs.
  - The 42 API rows are identical.
- **4h:** all 720 closed candles (2026-07-15 20:00 → 2026-11-12 16:00) have 0.0 EUR difference.
- Sampled closes:
  - 2024-11-22: 94,812.3
  - 2025-07-20: 100,834.4
  - 2026-03-17: 64,083.8
  - 2026-11-11: 66,653.6
- Limit: this source is Kraken itself. Kraken is the venue the bot trades on, so that is the right reference, but it is not a third party.

### 3e. Are the synthetic ("no-trade") rows real no-trade periods? PASS, with finding F-2
- From 2017 onwards, 1d has one synthetic day (2018-01-12) and 4h has 11 candles. Most are the January 2018 Kraken outage, plus 2024-04-14 and 2025-11-01.
- 15m has 110 runs. The longest are 151 buckets (the 2018-01-11..13 outage) and 26 buckets (2024-04-14 and 2025-11-01).
- I fetched Kraken's public Trades for three of the longest recent runs. Kraken's own trade record has no BTC/EUR trade in any of them:
  - 2024-01-20 16:00:01 → 21:35:44 (5 h 36 m)
  - 2024-04-14 03:00:15 → 09:52:54 (6 h 53 m)
  - 2025-11-01 15:02:37 → 21:46:15 (6 h 44 m)
- The price is essentially unchanged across each window. These are exchange halts, not missing archive data. The flat fills therefore do not hide download gaps, but they do also stand for "exchange down" (F-2).

## 4. Look-ahead and closed candles: PASS
- `CandleHistory.from_frame` keeps only rows with `open_at + interval <= as_of`. It compares integer microseconds exactly, after converting to nanoseconds so that a sub-millisecond offset cannot round a candle into view early.
- It refuses naive or non-UTC `as_of`, non-tz `open_at` and misaligned rows. `__post_init__` re-checks that no stored candle is unclosed.
- The arrays are read-only and backed by `bytes`. `to_frame()` returns a copy.
- `MarketData.closed_candles(pair, tf)` takes no time argument. `ReplayMarketData` uses the clock, so a caller cannot ask for the future. Future rows in the cache are hidden by the filter.
- `SimClock` refuses to move backwards and refuses naive times.
- `fetch_closed_candles` drops candles with `ts + step > now`, both per page and again at the end.
- `bot data validate` passes `now=clock.now()`, so a stored unclosed last candle fails validation.
- All timestamps are UTC end to end:
  - Archive Unix seconds are range-guarded to [2013, 2100).
  - API timestamps are milliseconds converted with `utc=True`.
  - The trades window bounds must be tz-aware UTC.
- Residual risk: see F-4 (local clock skew).

## 5. Safety

### 5a. Public, unauthenticated endpoints only: PASS
- `make_public_exchange()` is `ccxt.kraken({"enableRateLimit": True})`, with no key.
- The only exchange calls in `bot/` are `load_markets`, `fetch_ohlcv` and `fetch_trades`. There is no `fetch_balance`, no `create_order`, no private call, and no `urlopen`/`requests`/`subprocess`.
- Tests keep the M0 autouse network block. Several tests also assert `network_attempts == []`.

### 5b. Downloaded data treated as untrusted: PASS
- The importer downloads nothing; the operator supplies the files.
- The ZIP is opened from the same handle that was hashed.
- Members are matched by exact basename (`XBTEUR_{1440,240,15}.csv`), and a duplicate basename is refused. Tests cover `AIXBTEUR_240.csv` sitting next to the real member.
- Encrypted members are refused. Members are capped at 512 MiB, both as declared and as actually decompressed.
- The CSV is read with explicit dtypes, `header=None`, ASCII encoding and `compression=None`.
- Nothing is extracted or executed. `test_archive_module_never_extracts` guards this.
- The trades checkpoint is re-validated on load: columns, dtypes, unique ids, window, positive finite values.

### 5c. Checksum first on the multipart path: PASS
- `_open_verified` follows a fixed order:
  1. Parse the SUMS file (strict regex, no path separators, no duplicates).
  2. Check that the part names and their order match exactly. This happens before any part is opened, and the test patches `ConcatReader` to fail if it is.
  3. Hash every part and the whole concatenation in one pass.
  4. Compare against the SUMS file and against the whole-archive SHA-256 supplied on the command line. Only after that is `zipfile.ZipFile` called.
- Tests prove the ZIP is never parsed in each refusal case (the ZIP parser is patched to fail):
  - a corrupt part
  - a wrong whole-archive hash
  - a part replaced together with its listed hash, which the whole hash catches
  - a missing part
  - parts out of order
- Splitting the archive into parts and importing it gives the same result as importing the single file.

### 5d. No secrets read: PASS
See 2d. `load_settings` opens `config.yaml` and `.env`, which holds only the path to the secrets file. It never opens the secrets file itself.

## 6. M1 acceptance: "several years of daily and 4h candles for the chosen pair are cached and validated": PASS
- 1d covers 13.2 years (4,811 rows) and 4h covers 13.2 years (28,866 rows). From `history_start` 2017-01-01 that is about 9.9 years.
- Both pass `bot data validate` (exit 0) and my independent re-derivation.
- The epic's own wider criterion (1d, 4h and 15m covering several years) is also met: 15m covers 13 years (461,849 rows) and validates.

## 7. Decisions logged during M1

| Decision | Rating | Evidence and comment |
|---|---|---|
| `history_start` 2017-01-01 | PASS | Chosen on data quality, before any backtest (there is no backtest code). It excludes the dense 2013 gaps: 1d had 4 synthetic days in 2013, 4h had 167 candles in 2013, and 15m had 8,918 rows in 2013–2015. The config refuses a start on or after the holdout (tests cover this). Still marked provisional until operator review. |
| 15m cap 0.5% (1d/4h stay at 0.1%) | PASS on data, see F-1 on governance | This was raised after the archive-only 15m failed 0.1% (0.163%). The commit `a142323` is isolated, adds tests and removes none. My checks show the extra synthetic rows are genuine Kraken no-trade or halt periods: there is cross-timeframe consistency in both directions (3c), and three long runs were confirmed against Kraken's trade record (3e). The cap does not hide missing data. But it is 3× the observed ratio, and a coordinator set it although PROGRESS.md had earlier said "changing the cap or start date is an operator decision". |
| Trades backfill (2026-10-01 → 2026-11-05) | PASS | 15m rebuilt from trades resamples exactly (0 ticks, volume diff ~1e-13) to 209 Kraken API 4h candles and 34 API daily candles. The source sits in the precedence order archive > trades > synthetic > api. A hole touching a `trades` row is a download gap, and only 2 interior buckets were filled (2026-10-30 02:30–02:45). |

## Findings by severity

No High findings.

### Medium
- **F-1: the 15m synthetic cap was loosened without an operator decision.**
  - The coordinator raised it from 0.1% to 0.5% after the data failed the cap.
  - The data justifies it (section 7), but the 0.5% value leaves about 3× headroom over the measured 0.162%.
  - Earlier in the same log, PROGRESS.md called this an operator decision.
  - Recommendation: the operator ratifies it, or tightens it to about 0.25%, which still passes and keeps the gate meaningful.
- **F-2: "synthetic" also means "exchange halted", not only "flat market".**
  - Confirmed halts include 2018-01-11..13, and periods of 5–7 hours on 2024-01-20, 2024-04-14 and 2025-11-01, all with no Kraken trades.
  - A flat candle at the previous close looks fillable. M2's backtester and fill simulation must treat `synthetic=True` candles as non-fillable, with no fills, no limit-order fills and no execution-window progress. `CandleHistory.synthetic` carries the flag so this is possible.
  - The rationale in the decisions log ("a true flat market state") should mention halts.

### Low
- **F-3: spurious post-outage print on 2018-01-13 (after `history_start`).**
  - The first archive trade after the outage is at 20,000 EUR, while the surrounding prices are about 11,400–11,800. As a result, the 1d and 4h opens and highs for 2018-01-13 are 20,000.
  - This is real Kraken data, not a cache bug. Validation passes it because O ≤ H holds.
  - Any high-based or open-based logic in M2 will see it. Document it, or decide explicitly whether to keep it.
- **F-4: "closed" is judged by the local clock.**
  - The exchange skew check is deferred to M3 (stated in `bot/clock.py`).
  - If the PC clock runs ahead, a run of `bot data update` in the last seconds before a close could store a candle that is still open. `update` resumes at `last + interval`, so that candle would never be re-fetched or corrected.
  - The window is small with NTP. Consider re-fetching the last cached candle under the overlap check.
- **F-5: archive members match by basename under any directory prefix.** A renamed decoy is only refused when it duplicates the real member. The SHA-256 pin makes this practically irrelevant.
- **F-6: the SUMS file is not itself verified against its manifest hash.** The independent whole-archive SHA-256 from the support page closes this (see the tampered-list test), so the impact is nil.

### Info
- PROGRESS.md records that the follow-up reviews the workflow recommended for stories 1, 2 and 5 were not run. This audit read that code directly.
- The 15m API window is about 7.5 days. A lapse in `bot data update` fails loudly as a download gap, and `bot data backfill-trades` can close it.
- `Kraken_OHLCVT_2026Q3.zip` relies on trust on first use: Kraken publishes no checksum for it. The full archive, which supplies almost all of the history, is verified against published hashes.
- `data/raw/` (about 10 GB) and the 10 MB trades checkpoint under `var/` are kept, untracked.
- PROGRESS.md does not yet point to this report. Audit story 8 requires that it does.
