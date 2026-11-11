# Pair selection for v0 (Kraken spot, EUR-quoted)

Date: 2026-11-11. Inputs: `first_brief.txt`, `PROGRESS.md`, `docs/research/build-vs-reuse-and-kraken.md`.
Question from the user: "not only BTC — there might be easier markets, search and do the best."

## TL;DR

- **Primary pair for v0: `XBT/EUR` (BTC/EUR).** It is first or tied-first on every ex-ante criterion that matters for a €20, daily, post-only, long-or-flat bot: deepest EUR book on Kraken, a near one-tick spread (median 0.02 bps in book snapshots, 0.32 bps in Kraken's spread feed), the longest EUR history in Kraken's archive (first trade 10 Sep 2013), the lowest volatility of the candidates, the lowest regulatory and delisting risk, and the strongest published evidence for simple moving-average rules.
- **Runner-up: `ETH/EUR`** (97/100 vs 100 for BTC), then **`XRP/EUR`** (78) as "additional pairs later" candidates. `SOL/EUR` (70), `LTC/EUR` (69) and `LINK/EUR` (65) follow: SOL has deep volume but history only from June 2021 and little pair-specific literature; LTC has long history but thin EUR volume and 4+ bps spreads; LINK's book was tight in snapshots but its spread feed median was 5.5 bps.
- **Excluded:** stablecoins (`USDC/EUR`, `EURC/EUR`: no trend by design), `ZEC/EUR` (privacy coin; EU AMLR bars CASPs from these from July 2027, and Kraken already delisted XMR in the EEA), `HYPE/EUR` (listed Jan 2026, less history than the 12-month holdout), and names with less than 3 years of history before the holdout (`SUI`, `PEPE`, `ARB`, `ENA`). `AAVE`, `UNI`, `NEAR`, `AVAX` are eligible but score low (thin EUR volume, 5–8 bps spreads).
- **No basket in v0.** A 2–3 pair split at €20 cuts the headroom over Kraken's order minimums from about 5x to 1.5–2.5x, makes partial-fill dust likely, competes for the 4 orders/day limit, and buys little diversification (correlation with BTC 0.64–0.81 for the majors). Revisit after M6 with more capital.
- **"Easier market" caveat.** No pair can be shown to be "easier to trend-follow" without comparing backtested returns across pairs, which would contaminate the holdout. This selection deliberately does not do that. "Easier" here means: cheapest and most reliable to execute, most data, least listing risk.

## 1. Method and the selection-bias rule

The pair was chosen **only on ex-ante market-quality criteria**. No strategy was backtested on any pair, and no strategy return was computed. Two price-derived numbers were used, both computed only on data **older than 12 months** (before 2025-11-11), so the brief's held-out final 12 months were not looked at for selection:

- annualised volatility of daily log returns (a risk property, used for the drawdown-limit fit), and
- correlation of daily returns with BTC/EUR (used only for the basket question).

Data sources, all **public, unauthenticated** Kraken REST endpoints called on 2026-11-11 between about 15:14 and 15:27 CET (no API key, no secrets file touched):

- `AssetPairs?country_code=FR` (pairs available to a French account, `ordermin`, `costmin`, `lot_decimals`, `status`)
- `Ticker` (24h volume and VWAP, used to rank all 513 FR-available EUR pairs)
- `Depth?count=200` (five snapshots per pair, about 2.5 minutes apart)
- `Spread` (Kraken's recent bid/ask history for each pair, last round)
- `OHLC?interval=1440` (last 720 daily candles: 30-day and 365-day EUR volume, missing days, volatility, correlation)
- `Trades?since=0` (timestamp of the first trade on the pair, which is where Kraken's OHLCVT archive starts)

Scripts and raw JSON are in the session scratchpad, not in the repo. Limits: the spread and depth figures are a ~13-minute window on one weekday afternoon (European hours). They are a sanity check on relative ranking, not a full distribution. Orders of magnitude between pairs are large enough that the ranking would very likely not change with more samples, but M1 can log spread at each daily decision time to confirm it.

Candidates: the 18 non-stablecoin EUR pairs with the highest 24h EUR volume, all `online` for `country_code=FR`.

## 2. Criteria and weights

| # | Criterion | Weight | Why it matters for this bot |
|---|---|---|---|
| C1 | Liquidity: 30d and 365d average EUR volume, depth within 0.5% of mid | 25 | Post-only limit orders fill only if other people trade through your price. More volume means more fills inside the re-pricing window and fewer "not filled" journal entries. |
| C2 | Spread and slippage (bps) | 15 | A tight, tick-constrained spread means the post-only bid sits right at the market; the gap between signal price and fill stays small, which also makes GL-02 (fill within 0.5% of backtest price) easier to meet. |
| C3 | History in Kraken's OHLCVT archive and continuity | 20 | Walk-forward needs several years **before** the 12-month holdout. Kraken's archive only contains intervals with trades, so early illiquid years have gaps. |
| C4 | Regulatory and listing risk (France / MiCA / EEA) | 15 | A delisting forces a sale at a bad moment, breaks the data series and invalidates the dry-run. |
| C5 | Documented evidence for slow trend / moving-average rules | 10 | Ex-ante prior that a v0 trend filter is a sensible thing to test on this asset. Only published work is cited; no own backtest. |
| C6 | Minimum order vs €20 and dust risk | 10 | Must be able to enter and exit in full, including after a partial fill or a 25% drawdown. |
| C7 | Volatility (pre-holdout) | 5 | The total drawdown halt is 25% from start and the daily loss limit 10%. A very volatile pair trips them on noise. |

Each criterion is scored 0–5; weighted score = Σ weight × score / 5 (max 100). Hard exclusions (stablecoin, < 3 years of history before the holdout, known regulatory exit path) are applied before scoring.

## 3. Measured data

| Pair | 24h vol (M€) | 30d avg/day (M€) | 365d avg/day (M€) | Spread median / max (bps, 5 snapshots) | Spread endpoint median / p90 (bps) | Top-of-book min side (€) | Bid depth within 0.5% (€) | Slippage, €20 market sell (bps) | ordermin (base) ≈ € | €20 / ordermin € | First trade on Kraken | Missing days, last 720 | Ann. vol pre-holdout (%) | Corr. w/ BTC pre-holdout |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| XBT/EUR | 35.06 | 31.19 | 34.94 | 0.02 / 0.41 | 0.32 / 1.66 | 1,990 | 6,524,479 | 0.01 | 6e-05 ≈ 3.98 | 5.0x | 2013-09-10 | 0 | 42 | — |
| ETH/EUR | 10.95 | 12.70 | 16.05 | 0.38 / 2.22 | 0.60 / 1.62 | 2,741 | 4,272,197 | 0.19 | 0.002 ≈ 3.69 | 5.4x | 2015-08-07 | 0 | 75 | 0.81 |
| XRP/EUR | 5.70 | 7.48 | 7.26 | 2.31 / 3.15 | 3.26 / 4.20 | 1,639 | 581,528 | 1.15 | 4 ≈ 3.82 | 5.2x | 2017-05-18 | 0 | 92 | 0.71 |
| SOL/EUR | 6.88 | 6.00 | 7.99 | 1.32 / 1.32 | 2.65 / 2.65 | 2,405 | 528,400 | 0.66 | 0.05 ≈ 3.79 | 5.3x | 2021-06-17 | 0 | 87 | 0.79 |
| ZEC/EUR | 6.20 | 4.22 | 2.55 | 5.20 / 6.25 | 5.58 / 7.04 | 15 | 136,197 | 2.89 | 0.004 ≈ 3.54 | 5.6x | 2016-10-28 | 0 | 130 | 0.35 |
| NEAR/EUR | 2.23 | 2.61 | 1.04 | 3.85 / 4.14 | 6.66 / 10.06 | 270 | 95,733 | 2.07 | 1 ≈ 3.38 | 5.9x | 2022-06-16 | 0 | 102 | 0.71 |
| HYPE/EUR | 1.58 | 1.93 | 0.92 | 4.57 / 4.57 | 3.05 / 4.57 | 670 | 123,507 | 2.28 | 0.06 ≈ 3.95 | 5.1x | 2026-01-28 | 0 | n/a | n/a |
| LINK/EUR | 1.21 | 1.63 | 1.01 | 0.65 / 0.80 | 5.48 / 7.31 | 663 | 161,189 | 0.32 | 0.35 ≈ 3.26 | 6.1x | 2019-09-25 | 0 | 102 | 0.71 |
| SUI/EUR | 1.05 | 1.50 | 1.26 | 1.33 / 1.33 | 2.67 / 5.33 | 451 | 89,363 | 0.67 | 5 ≈ 3.75 | 5.3x | 2023-05-03 | 0 | 105 | 0.71 |
| ADA/EUR | 0.56 | 1.47 | 1.72 | 3.26 / 4.26 | 9.33 / 13.35 | 320 | 124,955 | 1.63 | 20 ≈ 3.19 | 6.3x | 2018-09-28 | 0 | 107 | 0.74 |
| PEPE/EUR | 1.63 | 1.01 | 0.36 | 4.48 / 4.48 | 6.70 / 8.97 | 180 | 67,671 | 2.24 | 1.1e+06 ≈ 4.92 | 4.1x | 2023-05-16 | 0 | 115 | 0.72 |
| LTC/EUR | 0.48 | 0.89 | 1.34 | 4.34 / 6.50 | 4.34 / 6.51 | 902 | 154,890 | 2.17 | 0.08 ≈ 3.70 | 5.4x | 2013-09-14 | 0 | 86 | 0.64 |
| UNI/EUR | 0.72 | 0.83 | 0.59 | 6.35 / 11.18 | 7.48 / 11.68 | 559 | 78,490 | 3.18 | 0.7 ≈ 4.09 | 4.9x | 2020-10-15 | 0 | 114 | 0.67 |
| ENA/EUR | 0.63 | 0.80 | 0.26 | 7.26 / 7.27 | 10.88 / 14.53 | 676 | 47,946 | 3.63 | 30 ≈ 4.12 | 4.8x | 2024-05-30 | 0 | 141 | 0.57 |
| AVAX/EUR | 0.77 | 0.77 | 0.47 | 5.20 / 5.21 | 5.20 / 9.09 | 4,756 | 122,051 | 2.60 | 0.5 ≈ 3.85 | 5.2x | 2021-12-21 | 0 | 100 | 0.73 |
| XDG/EUR | 0.80 | 0.68 | 1.18 | 0.11 / 6.39 | 3.16 / 6.83 | 702 | 170,135 | 0.06 | 50 ≈ 3.07 | 6.5x | 2019-12-19 | 0 | 96 | 0.80 |
| AAVE/EUR | 0.56 | 0.58 | 0.42 | 5.40 / 7.19 | 7.20 / 9.01 | 334 | 104,535 | 2.70 | 0.03 ≈ 3.34 | 6.0x | 2020-12-15 | 0 | 103 | 0.68 |
| ARB/EUR | 0.64 | 0.56 | 0.20 | 13.86 / 13.88 | 13.81 / 13.87 | 1,039 | 39,959 | 6.93 | 30 ≈ 4.32 | 4.6x | 2023-03-23 | 0 | 112 | 0.67 |

Column notes:
- *Spread median / max*: from five `Depth` snapshots. *Spread endpoint*: Kraken's `Spread` feed for the same pair (the last 250 quote changes per pair).
- *Top-of-book min side*: € value at the best bid or best ask, whichever is smaller. A €20 post-only order is tiny compared to these.
- *Bid depth within 0.5%*: € of bids within 0.5% of mid (lower bound when 200 levels did not reach 0.5%).
- *Slippage, €20 market sell*: average fill vs mid, i.e. about half the spread. Relevant only for an emergency taker exit.
- *€20 / ordermin €*: how many times the minimum fits in €20. All pairs have `costmin` = €0.45 and `lot_decimals` 5–8, so `ordermin` (fixed in base units) is the binding constraint everywhere.
- *Missing days*: all 18 pairs have zero missing daily candles in the last 720 days. Gaps can still exist in early years of the archive (not measured here: it needs the 10 GB download). The M1 validator must report them.
- *Pre-holdout*: computed only on candles before 2025-11-11.

Market context (Ticker, 24h): EUR pairs available to FR accounts total about €196M; `USDC/EUR` alone is €106M. Among non-stablecoin pairs, BTC/EUR and ETH/EUR together are about 52% of EUR volume. Of 513 FR EUR pairs, 30 are `cancel_only` and 5 `post_only`, i.e. being wound down or restricted, almost all small caps. 18 EUR pairs are listed globally but excluded for FR, including `XMR/EUR`, `USDT/EUR`, `DAI/EUR`, `RLUSD/EUR`.

## 4. Regulatory and listing risk (France / EEA)

- Kraken (Payward Europe Solutions Ltd) holds a MiCA licence from the Central Bank of Ireland since 25 Jun 2025 and is on the AMF's list as authorised to serve France under free provision of services. https://www.amf-france.org/en/warnings/white-lists/casp/payward-europe-solutions-limited-kraken-digital-asset-exchange-kraken , https://www.businesswire.com/news/home/20250625529871/en
- **Privacy coins:** the EU AML Regulation (Regulation (EU) 2024/1624) bars CASPs from handling anonymity-enhancing coins from July 2027 (sources differ between 1 and 10 July 2027; reporting names XMR, ZEC and DASH). Kraken already delisted XMR for EEA clients in Oct 2024 and has delisted XMR/DASH/ZEC in India. **ZEC/EUR is excluded**: a forced exit within the first year of live trading is likely. https://cointelegraph.com/news/eu-crypto-ban-anonymous-privacy-tokens-2027 , https://cointelegraph.com/news/kraken-ends-monero-support-european-economic-area , https://support.kraken.com/ca/sections/delistings
- **Stablecoins:** USDT, DAI, PYUSD and others are already delisted for the EEA (see the build-vs-reuse doc). Not relevant to a EUR-quoted trend pair, but it shows that EEA listing changes do happen at short notice.
- **Small caps:** Kraken publishes monthly "scheduled asset delisting" notices (April–October 2026), and 30 FR EUR pairs are currently `cancel_only`. Delisting risk is concentrated in smaller, newer tokens. https://support.kraken.com/ca/sections/delistings
- **BTC, ETH:** no EEA restriction found. BTC and ETH are the reference assets for MiCA's "other crypto-assets" category and the two assets with the deepest EUR markets on every major EEA venue. Risk rated lowest.
- **SOL, XRP, LINK, ADA, DOGE, LTC:** no EEA restriction found. Rated low but above BTC/ETH (single-issuer or foundation concentration; XRP had a long US securities case, now resolved, but no EEA action).

## 5. Literature on slow trend rules (cited, not re-tested)

- Detzel, Liu, Strauss, Zhou, Zhu (2021), "Learning and predictability via technical analysis: Evidence from bitcoin and stocks with hard-to-value fundamentals", *Financial Management* 50(1), 107–137. Ratios of price to moving averages (5–100 days) forecast daily **Bitcoin** returns in and out of sample; MA strategies improve Sharpe vs buy-and-hold. The working-paper version notes results are gross of costs. https://econpapers.repec.org/RePEc:bla:finmgt:v:50:y:2021:i:1:p:107-137
- Hudson & Urquhart (2021), "Technical trading and cryptocurrencies", *Annals of Operations Research* 297, 191–220. ~15,000 rules on two Bitcoin markets and three other large coins, with data-snooping corrections; predictability in all rule classes. https://centaur.reading.ac.uk/85715
- Deprez & Frömmel (2024), "Are simple technical trading rules profitable in bitcoin markets?", *International Review of Economics & Finance* 93, 858–874. 75,360 rules, transaction costs and data-mining correction; out-of-sample, rules can beat buy-and-hold mainly on a **risk-adjusted** basis. https://ideas.repec.org/a/eee/reveco/v93y2024ipbp858-874.html
- Liu & Tsyvinski (2018/2021), "Risks and Returns of Cryptocurrency", NBER WP 24877 / *Review of Financial Studies*. Time-series momentum at daily and weekly horizons for BTC, XRP and ETH (weaker for ETH). https://www.nber.org/system/files/working_papers/w24877/w24877.pdf
- Moskowitz, Ooi & Pedersen (2012), "Time series momentum", *Journal of Financial Economics* — the general (non-crypto) reference for slow trend filters.

Reading: evidence is densest for **BTC**, then for the other large-cap coins studied (ETH, XRP, LTC). Almost nothing exists for 2023+ listings (SUI, PEPE, HYPE, ENA). Honest caveats: these papers mostly use pre-2022 data, many report gross results, and published effects tend to shrink after publication. This is a prior for "worth testing", not evidence the v0 bot will make money.

## 6. Minimum order, dust and the €20 account

- Current `ordermin` is €3.1–4.9 for every candidate; `costmin` €0.45. With one pair and €20, the position is about **5x** BTC's minimum (0.00006 BTC ≈ €3.98).
- `ordermin` is fixed in **base units**, so its € value moves with price: if BTC doubles, the minimum is ≈ €8 (still 2.5x a €20 position). Kraken says minimums "can change without notice". Read them at startup (already in the brief).
- **Partial-fill dust is the real risk with post-only orders.** If a €20 buy fills €2 and the rest is cancelled at the end of the re-pricing window, the €2 position is **below `ordermin` and cannot be sold**. Mitigations for the architecture: (a) after a partial fill below `ordermin`, either keep re-pricing until filled above the minimum or place a top-up buy so the position is sellable; (b) never cancel an exit while the remaining position is below the minimum without alerting; (c) dust can still be cleared by hand through Kraken's "Buy/Sell Crypto" flow (€1 minimum), outside the bot. https://support.kraken.com/articles/360001389303-order-minimums
- **Fee currency:** Kraken's default is fee in quote currency when buying (`fciq`) but fee in **base** currency when selling (`fcib`). https://docs.kraken.com/api/docs/rest-api/add-order/ . To sell the whole base balance without a remainder or an "insufficient funds" rejection, the KrakenBroker should send `oflags=post,fciq` on sells (verify behaviour in M3 against the fake broker contract and once live with a minimum-size order).
- Lot precision: 8 decimals for BTC/ETH (5 for PEPE, SUI, ARB, ENA). Not a constraint at these sizes.

## 7. Scoring

| Pair | C1 Liquidity (25) | C2 Spread (15) | C3 History (20) | C4 Regulatory (15) | C5 Literature (10) | C6 Min/dust (10) | C7 Volatility (5) | **Score /100** | Note |
|---|---|---|---|---|---|---|---|---|---|
| XBT/EUR | 5 | 5 | 5 | 5 | 5 | 5 | 5 | **100** |  |
| ETH/EUR | 5 | 5 | 5 | 5 | 4 | 5 | 4 | **97** |  |
| XRP/EUR | 4 | 3 | 4 | 4 | 4 | 5 | 3 | **78** |  |
| SOL/EUR | 4 | 3 | 3 | 4 | 2 | 5 | 3 | **70** |  |
| LTC/EUR | 2 | 2 | 5 | 4 | 4 | 5 | 3 | **69** |  |
| LINK/EUR | 3 | 2 | 4 | 4 | 2 | 5 | 2 | **65** |  |
| XDG/EUR | 2 | 3 | 4 | 4 | 2 | 5 | 3 | **64** |  |
| ADA/EUR | 3 | 1 | 4 | 4 | 2 | 5 | 2 | **62** |  |
| AVAX/EUR | 2 | 2 | 3 | 4 | 2 | 5 | 3 | **57** |  |
| AAVE/EUR | 2 | 2 | 3 | 3 | 1 | 5 | 2 | **51** |  |
| UNI/EUR | 2 | 2 | 3 | 3 | 1 | 4 | 2 | **49** |  |
| NEAR/EUR | 3 | 2 | 1 | 3 | 1 | 5 | 2 | **48** |  |
| ZEC/EUR | 4 | 2 | 5 | 0 | 1 | 5 | 1 | **59** | EXCLUDED: privacy coin (AMLR 2027) |
| SUI/EUR | 3 | 3 | 1 | 3 | 1 | 5 | 2 | **51** | EXCLUDED: < 3 y before holdout |
| HYPE/EUR | 3 | 2 | 1 | 3 | 1 | 5 | 1 | **47** | EXCLUDED: < 3 y before holdout |
| PEPE/EUR | 3 | 2 | 1 | 3 | 1 | 3 | 2 | **44** | EXCLUDED: < 3 y before holdout |
| ARB/EUR | 2 | 1 | 1 | 3 | 1 | 4 | 2 | **38** | EXCLUDED: < 3 y before holdout |
| ENA/EUR | 2 | 1 | 1 | 3 | 1 | 4 | 1 | **37** | EXCLUDED: < 3 y before holdout |

Scoring rules used (written before scoring):
- C1: 5 = 30d avg ≥ €10M/day; 4 = ≥ €3M; 3 = ≥ €1M; 2 = ≥ €0.5M; 1 = less.
- C2 (uses the **worse** of the snapshot median and the `Spread`-feed median, to be conservative): 5 = ≤ 1 bps; 4 = ≤ 2; 3 = ≤ 4; 2 = ≤ 8; 1 = more.
- C3: 5 = first EUR trade ≤ 2016; 4 = ≤ 2019; 3 = ≤ 2021; 1 = 2022–2023; excluded if less than 3 years before holdout start (2025-11-11), i.e. listed after 2022-11.
- C4: 5 = BTC/ETH; 4 = large caps without EEA issue; 3 = smaller caps (higher monthly delisting exposure); 0 = known regulatory exit (privacy coins).
- C5: 5 = BTC (multiple peer-reviewed studies specific to it); 4 = ETH/XRP/LTC (in the same studies); 2 = other large caps covered only by cross-sectional studies; 1 = nothing specific.
- C6: 5 = €20 / ordermin € ≥ 5x; 4 = ≥ 4.5x; 3 = less.
- C7: 5 = < 50%; 4 = < 80%; 3 = < 100%; 2 = < 120%; 1 = more; n/a → 1.

## 8. Basket or single pair in v0?

**Single pair.** Reasons:

1. **Minimums.** Equal split of €20: 2 legs = €10 each (BTC: 2.5x its minimum), 3 legs = €6.67 (1.7x; PEPE-type pairs 1.4x). After the 25% drawdown limit, 3 legs are €5 each, about 1.3x the minimum, and a 20% price rise in BTC pushes its € minimum near the leg size. Partial post-only fills would leave unsellable dust often.
2. **Order budget.** The limit is 4 orders/day. Post-only orders that get re-priced (cancel + new order) use several orders per fill. Two legs flipping on the same day can exhaust it, so a second leg would be skipped by the risk manager for reasons unrelated to the strategy.
3. **Little diversification.** Pre-holdout daily correlation with BTC is 0.81 for ETH and about 0.7–0.8 for SOL, XRP, ADA, DOGE, LINK. Most of a crypto basket's risk is still BTC.
4. **Scope.** The brief says v0 is one pair, and every extra pair multiplies data validation, reconciliation and dashboard work before M6.
5. **Selection-bias hygiene.** A basket picked now would invite comparing pairs' backtests. With one pair fixed ex ante, the holdout stays clean.

When to revisit: after M6, if capital is ≥ ~€100 (≥ 5x minimum per leg for 2–3 legs). Add pairs in this order, still chosen ex ante: ETH/EUR, then XRP/EUR, then SOL/EUR. Re-check minimums, status and EEA notices at that time, and run each new pair's holdout once.

## 9. Recommendation

1. **v0 trades `XBT/EUR` only** (ccxt symbol `BTC/EUR`, Kraken key `XXBTZEUR`). Record this in `PROGRESS.md` as a decision made on market-quality criteria, before any backtest.
2. **M1:** extract BTC/EUR 1440- and 240-minute files from the Kraken OHLCVT archive (history from 2013-09-10). Because 2013–2016 EUR trading was thin, the no-trade-day policy will matter for early years; it is reasonable to fix in config, before any backtest, a start date after which the pair has no missing days (to be measured in M1), and to state it in the results file.
3. **Architecture notes from this research:** handle partial-fill dust below `ordermin`; send `fciq` on sells; block orders when `status` ≠ `online`; re-read `ordermin` at startup since its € value moves with price.
4. **Later pairs (not in v0):** ETH/EUR first, then XRP/EUR, then SOL/EUR. Not ZEC (privacy-coin ban), not newly listed tokens.
