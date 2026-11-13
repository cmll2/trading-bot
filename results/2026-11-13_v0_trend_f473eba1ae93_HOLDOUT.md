VERDICT (SIMULATED): v0_trend beats buy-and-hold after costs in this backtest: total return +6.0% vs buy-and-hold -27.2% at maker fees, +6.4% vs -27.5% at taker fees (2025-11-11..2026-11-10). This is not evidence of future profit.

SIMULATED BACKTEST - these are simulated results on historical data; they are not evidence that the strategy will make money.

# Backtest report: v0_trend (change 0)

## Provenance

- Code version: `f473eba1ae93338bf25b510e66542a1b279bcaf6`
- Config hash: `77c5e1f2eb254d480acca501f90786e6a60908dcce5f920869175012a4a18ade`; limits hash: `7193909170f44fc89540856a29e0ef5cc55e8ff8690e573ae30cd9f0c67c583c`
- Parameters: `{'sma_days': 200}`; configurations tried: 1
- Data: BTC/EUR 2025-04-15 to 2026-11-11 (exclusive); hashes 15m `596a819b4a8848b3`, 1d `b3fc1f5ad11bebf4`
- Evaluation window (after a 200-candle warm-up): 2025-11-11 to 2026-11-10
- Holdout 2025-11-11..2026-11-10: THIS IS THE HOLDOUT RUN (recorded in holdout_runs.jsonl); holdout runs recorded for this strategy: 1
- Fees: maker 0.0040, taker 0.0080 (published_schedule); slippage 5 bp
- Exchange rules: public market snapshot fetched 2026-11-13 (amount_min 0.00006 BTC, cost_min 0.45 EUR, tick 0.1)
- Look-ahead guard: PASSED (12 cutpoints x 2 futures, 1363 candle targets compared, seed 20261113)

## Results at maker fees (post-only limit orders, as built)

| Metric | Strategy | Buy-and-hold | Cash |
|---|---|---|---|
| Total return | +5.95% | -27.17% | +0.00% |
| Annualized return | +5.97% | -27.23% | +0.00% |
| Max drawdown | 12.78% | 44.30% | 0.00% |
| Sharpe (daily, ann.) | 0.42 | -0.53 | 0.00 |
| Sharpe 95% CI (bootstrap) | [-1.18, 1.92] | [-2.62, 1.65] | [0.00, 0.00] |
| Trades (fills) | 1 | 1 | 0 |
| Round trips | 0 | 0 | 0 |
| Turnover (x mean equity) | 0.97 | 1.39 | 0.00 |
| Total fees (EUR) | 0.08 | 0.08 | 0.00 |
| Time in market | 22.2% | 100.0% | 0.0% |
| Final equity (EUR) | 21.19 | 14.57 | 20.00 |

- Signal outcomes: {'filled': 1, 'no_action': 364}
- Orders submitted: 2 ({'cancelled': 1, 'filled': 1})
- Risk events: none
- Halted: False

## Results at taker fees (fill at once at ask/bid, CON-06 variant)

| Metric | Strategy | Buy-and-hold | Cash |
|---|---|---|---|
| Total return | +6.44% | -27.46% | +0.00% |
| Annualized return | +6.46% | -27.53% | +0.00% |
| Max drawdown | 12.78% | 44.53% | 0.00% |
| Sharpe (daily, ann.) | 0.44 | -0.53 | 0.00 |
| Sharpe 95% CI (bootstrap) | [-1.17, 1.92] | [-2.62, 1.65] | [0.00, 0.00] |
| Trades (fills) | 1 | 1 | 0 |
| Round trips | 0 | 0 | 0 |
| Turnover (x mean equity) | 0.97 | 1.39 | 0.00 |
| Total fees (EUR) | 0.16 | 0.16 | 0.00 |
| Time in market | 22.2% | 100.0% | 0.0% |
| Final equity (EUR) | 21.29 | 14.51 | 20.00 |

- Signal outcomes: {'filled': 1, 'no_action': 364}
- Orders submitted: 1 ({'filled': 1})
- Risk events: none
- Halted: False

## Protected halts and SIMULATED RESETS

Policy: protected halts are evaluated on equity marked at every 15m close; after a halt the resting orders are cancelled and the position kept, and the operator's manual reset is modelled as a SIMULATED RESET at the next UTC daily close (a total-drawdown reset also rebases the baseline)

- maker: no halt; no halt.
  - Triggered (UTC): none
- taker: no halt; no halt.
  - Triggered (UTC): none

## DIAGNOSTIC (not used for any decision): v0 without the EUR 25 absolute position cap

Same strategy, parameters and data; only the protected absolute cap (max_position_abs_quote) is lifted in a separate in-memory limits object for these diagnostic runs. Protected limits unchanged. Not a configuration tried (configurations_tried stays 1); never used to choose anything.

| Fee rate | Metric | Strategy (no abs cap) | Buy-and-hold |
|---|---|---|---|
| maker | Total return | +5.95% | -27.17% |
| maker | Annualized return | +5.97% | -27.23% |
| maker | Max drawdown | 12.78% | 44.30% |
| maker | Sharpe | 0.42 | -0.53 |
| maker | Total fees (EUR) | 0.08 | 0.08 |
| maker | Final equity (EUR) | 21.19 | 14.57 |
| maker | Halts | none | - |
| taker | Total return | +6.44% | -27.46% |
| taker | Annualized return | +6.46% | -27.53% |
| taker | Max drawdown | 12.78% | 44.53% |
| taker | Sharpe | 0.44 | -0.53 |
| taker | Total fees (EUR) | 0.16 | 0.16 |
| taker | Final equity (EUR) | 21.29 | 14.51 |
| taker | Halts | none | - |

## Data anomalies

- none in range

## Caveats

- Positions are capped by the protected risk limit max_position_abs_quote (EUR 25): once equity grows past it, re-entries invest at most that amount while buy-and-hold keeps its whole initial stake invested (it buys once and holds). The DIAGNOSTIC section shows the same strategy without that cap.
- Exchange minimums and precision come from one public market snapshot and are applied to the whole history; historical minimums differed (Kraken's BTC minimum was about 0.002 BTC in earlier years, which would have mattered at EUR 20), and the simulated half spread is optimistic for 2017-2018, when BTC/EUR spreads were wider.
- Fees are Kraken's published entry tier (maker 0.0040, taker 0.0080), not the account's tier (verified against fetch_trading_fee at live start, M6).
- Execution model: post-only limit at the best bid/ask (last closed 15m close +/- 1 bp), re-priced every 30 min within 6 h after the daily close, plus a 24 h completion phase for an unsellable partial buy; filled only on a strict trade-through of a later closed 15m candle; synthetic (no-trade / exchange-halt) candles never fill. The taker variant fills at once at the ask/bid; its buy-and-hold benchmark pays the same half spread.
- Equity of the strategy and of buy-and-hold is marked at mid, without exit costs.
- Parameters were fixed before any evaluation; configurations tried: 1. THIS IS THE ONE-SHOT HOLDOUT RUN: holdout data was loaded and evaluated.
