---
scope: Whole v1 system (brief §5, M0-M6), custom build
purpose: build-substrate
altitude: initiative
updated: 2026-11-11T15:17
---


- (event by coach) Headless run (caller: parent agent, user unavailable). BMad config absent (_bmad/ missing): defaults used; output path set by caller to docs/planning/architecture.md.
- (constraint by coach) Inherited from PROGRESS decisions log: custom build; Python>=3.11 via uv; only brief §6 deps; EUR-quoted pair (market TBD); daily candles; post-only limit re-priced in window then cancel+skip; manual+autonomous approval; risk values; Windows host portable; GL-02 0.5%/fill, 2pp equity; GetApiKeyInfo; fees via fetch_trading_fee; cl_ord_id lookup open+closed; OHLCVT archive + ccxt.
- (version by coach) Verified on PyPI 2026-11-11: ccxt 4.5.92, pandas 3.1.1, pyarrow 26.0.1, pydantic 2.14.3, pyyaml 6.0.3, python-dotenv 1.2.4, pytest 9.2.0, ruff 0.17.4, streamlit 1.67.0, plotly 7.1.0; uv 0.11.3 local; CPython 3.14.3 already installed by uv.
- (decision by coach) Paradigm: hexagonal (ports & adapters) with functional core. Pure: strategy, sizing, risk checks, fill model. Ports: Broker, Clock, MarketData, Store. Prevents mode-specific logic leaking into engine.
- (decision by coach) Backtest runs the same Engine with PaperBroker + SimClock + replay MarketData + in-memory SQLite store. Prevents a second order path in the backtester.
- (decision by coach) Single fill model module shared by backtest and dry-run; both evaluate fills on closed execution candles (finer timeframe) with trade-through rule. Only modelled divergence: synthetic bid/ask half-spread in backtest. Enables exact consistency test.
- (decision by coach) Order lifecycle: intents (one per signal) -> orders (one per submission, own cl_ord_id = uuid4 hex). Re-price = cancel confirmed then new order. Persist before send; never blind resend; on unknown outcome look up in open+closed; NOT_FOUND after grace -> abandoned, retry gets new id.
- (decision by coach) Orders/day limit counts intents, not submissions; re-prices bounded by execution.max_reprices. Prevents re-pricing exhausting 4/day.
- (decision by coach) Kill switch and halts: cancel resting orders, keep position; engine never auto-sells while halted; operator may run CLI flatten (risk-reducing sell, still minimum/price checks).
- (decision by coach) Single writer per table: engine owns trading tables; CLI writes only operator_actions; dashboard opens store read-only (mode=ro) and its only write is the kill-switch file.
- (decision by coach) One store file per (mode, strategy); plumbing dry-run uses its own file. Single-instance lock per store.
- (decision by coach) Plumbing strategy impossible in live: live registry excludes it, Strategy.allowed_modes checked, KrakenBroker requires LiveGate token, live config requires timeframe in {4h,1d}.
- (decision by coach) Look-ahead guard: HistoryView truncated at clock time + future-perturbation check in every backtest (signal at t must not change when candles > t are perturbed).
- (decision by coach) Holdout registry is a committed append-only results/holdout_runs.jsonl; holdout run refused on dirty tree or prior run unless --rerun-holdout --reason.
- (decision by coach) Dust: target 0 sells full base balance; buy refused unless qty remains above amount_min and cost_min after a price drop equal to the drawdown limit. Fees in quote currency (oflag fciq) so base position equals filled qty.
- (decision by coach) Money and quantities stored as decimal TEXT; timestamps ISO-8601 UTC TEXT with Z.
- (decision by coach) Dry-run needs no API key: fees from config schedule; live startup fetches fetch_trading_fee and refuses if different from config. Paper reconciliation compares engine tables vs paper_* tables.
- (decision by coach) Tests: autouse fixture blocks socket connect/getaddrinfo; no public endpoints either; ccxt replaced by fake exchange object.
- (assumption by coach) Bot owns the entire base-asset balance of the traded pair on the account; EUR on account may exceed bot cash (reconcile: base exact, EUR >= bot cash).
- (assumption by coach) Calendar-year disposal total attributed in Europe/Paris time; storage stays UTC.
- (assumption by coach) Archive vs API overlap tolerance: OHLC within 1 tick, volume within 1%.
- (question by coach) Exact EUR market(s) - parallel research.
- (question by coach) OD-14 holdout boundary fixed date vs rolling (design recommends fixed date in config).
- (question by coach) OD-15 DECAYING rule when backtest avg per trade <= 0.
- (question by coach) OD-16 risk limits in config.yaml section vs separate protected file.
- (question by coach) Live banner: print only, or require typed confirmation (conflicts with unattended restart).
- (question by coach) Drawdown halt reset: rebase start equity or not.
- (question by coach) Process supervision on Windows (Task Scheduler restart) and sleep policy.
- (question by coach) Execution window length, re-price interval, max_reprices, execution timeframe values.
- (constraint by coordinator) Pair decided: BTC/EUR (Kraken XBT/EUR), single pair v0, config still a list (docs/research/pair-selection.md).
- (constraint by coordinator) Orders send oflags=post,fciq (sells especially: Kraken default fee on sells is base). Re-read minimums at startup. Sub-minimum partial-fill remainder must be handled (keep repricing / top up to sellable).
- (constraint by progress) Dashboard can only ENGAGE kill switch; disengage and halt reset CLI-only (ux-dashboard spec). Tax-year boundaries Europe/Paris, storage UTC (now adopted, supersedes assumption A-2).
- (event by coordinator) Reviewer gate run: rubric, adversarial, reality lenses as parallel subagents; reviews in scratchpad arch/reviews/.
- (decision by coach) From review: intent state machine with outcome mapping; flatten intents have null signal_id + source_action_id, exempt from orders/day, stale-candle, halt/kill; halt sweep skips flatten.
- (decision by coach) From review: risk check before order row insert; created->not_found at restart; exchange-side cancel edges; next attempt only after ingested fills equal exchange filled qty; unmatched fill halts; fee_ccy != quote halts.
- (decision by coach) From review: schema_meta initial_quote/initial_base immutable; drawdown baseline in append-only equity_baselines; day-open equity defined; equity stored as decimal TEXT; risk_snapshots table for dashboard.
- (decision by coach) From review: buy completion phase - a buy intent whose filled qty is >0 but unsellable continues past window (completion_window) to reach the sellable quantity; sell-side dust merges into next entry and is cleared by the next full-balance sell.
- (decision by coach) From review: look-ahead guard = prefix-invariance (rerun whole backtest from perturbed-future datasets at sampled cutpoints); sizing caps qty by free cash/(1+fee) and risk caps, recomputed each reprice; review job has own lock and owns signal_counterfactuals.
- (assumption by coach) orders/day counts intents (re-prices excluded, bounded by max_reprices) - flagged as open question since PROGRESS value says orders.
- (version by reviewer) Repo M0 scaffold pins Python 3.12 (.python-version, requires-python>=3.12); stack row adopted. ccxt merges postOnly+oflags fciq; cl_ord_id filters verified; post-only cross response unverified -> dual handling + M6 fixture.
- (event by coach) spine finalized (headless; open questions Q-2..Q-11 remain for operator)
