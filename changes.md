# Strategy change log

Rules (brief §5.3, FR-17, AD-21):

- One change at a time, **at most five changes per strategy**. `bot backtest --change N`
  refuses N > 5 and refuses N >= 1 unless the strategy's `## <strategy id>` section below
  has a `### Change N` entry.
- Each entry records: what changed and why, the git commit, the results file it produced,
  and the result (including when the change made things worse).
- Changes are evaluated on pre-holdout data only. The holdout (2025-11-11 -> 2026-11-10)
  is run once per strategy, at the end, and recorded in `results/holdout_runs.jsonl`.

## v0_trend

Baseline (change 0): long when the last closed daily close > SMA(200) of daily closes,
flat otherwise. Parameters fixed in `config.yaml` on 2026-11-13, before any evaluation.

No changes yet.
