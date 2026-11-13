"""Event-driven backtester, metrics, walk-forward, holdout registry (FR-12 to FR-22). M2.

Modules:
    command       ``bot backtest``: one command from the cache to a SIMULATED results file
    dataset       the only entry point for candles (holdout refused, look-ahead hook)
    runner        the shared Engine with PaperBroker, SimClock, ReplayMarketData (AD-1)
    lookahead     prefix-invariance guard (AD-4)
    metrics       metrics, benchmarks, bootstrap Sharpe CI (FR-14, FR-21)
    report        verdict-first Markdown report and payload blocks (FR-19)
    holdout       holdout registry, walk-forward folds, change limit (FR-15..FR-17)
    search        parameter search with trial count (FR-20); no CLI
    market_rules  recorded public market snapshot (minimums, precision)
    provenance    git commit, dirty flag, config and limits hashes (FR-18)
    results       results file writer
Planned (M3/M4): compare (dry-run vs backtest, AD-20).
"""
