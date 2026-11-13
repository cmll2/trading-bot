-- Schema v1 (architecture §2, verbatim DDL) plus write-once / append-only triggers.
-- Applied by bot/store.py; schema_meta.schema_version must equal store.SCHEMA_VERSION.

CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- write-once keys: schema_version, mode, strategy_id, exchange, pair, quote_ccy,
--   initial_quote, initial_base, initial_at   (set by engine on first start from get_balance(); never updated)

CREATE TABLE runs (
  run_id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, stopped_at TEXT,
  mode TEXT NOT NULL CHECK (mode IN ('backtest','dry-run','live')),
  strategy_id TEXT NOT NULL, git_commit TEXT NOT NULL, git_dirty INTEGER NOT NULL,
  config_hash TEXT NOT NULL, limits_hash TEXT NOT NULL, pid INTEGER NOT NULL, stop_reason TEXT
);

CREATE TABLE heartbeats (
  run_id INTEGER NOT NULL REFERENCES runs, at TEXT NOT NULL, loop_state TEXT NOT NULL,
  PRIMARY KEY (run_id, at)
);

CREATE TABLE signals (                      -- the journal: one row per evaluated closed candle
  signal_id TEXT PRIMARY KEY,               -- '{strategy_id}|{pair}|{timeframe}|{candle_open_at}'
  run_id INTEGER NOT NULL REFERENCES runs,
  strategy_id TEXT NOT NULL, pair TEXT NOT NULL, timeframe TEXT NOT NULL,
  candle_open_at TEXT NOT NULL, evaluated_at TEXT NOT NULL,
  target_fraction TEXT NOT NULL, signal_price TEXT NOT NULL, indicators_json TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK (outcome IN ('pending','no_action','filled','partially_filled',
          'not_filled','rejected_by_risk','skipped_by_operator','below_minimum','halted','dust')),
  outcome_reason TEXT,
  UNIQUE (strategy_id, pair, timeframe, candle_open_at)
);

CREATE TABLE intents (                      -- one order decision; at most one per signal
  intent_id INTEGER PRIMARY KEY,
  signal_id TEXT UNIQUE REFERENCES signals,
  source_action_id INTEGER UNIQUE REFERENCES operator_actions,   -- set for flatten
  is_flatten INTEGER NOT NULL DEFAULT 0,
  pair TEXT NOT NULL, side TEXT NOT NULL CHECK (side IN ('buy','sell')),
  reference_price TEXT NOT NULL,            -- signal close, or mid when flatten created (price-sanity base)
  target_qty TEXT NOT NULL, filled_qty TEXT NOT NULL DEFAULT '0',   -- filled_qty = sum(fills) (AD-27)
  state TEXT NOT NULL CHECK (state IN ('awaiting_approval','working','completing','done',
          'expired','cancelled','halted')),
  approval_mode TEXT NOT NULL CHECK (approval_mode IN ('manual','autonomous')),
  approval_deadline_at TEXT, window_end_at TEXT NOT NULL, completion_end_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK ((is_flatten = 0 AND signal_id IS NOT NULL AND source_action_id IS NULL)
      OR (is_flatten = 1 AND signal_id IS NULL AND source_action_id IS NOT NULL))
);
CREATE UNIQUE INDEX one_active_intent_per_pair ON intents(pair)
  WHERE state IN ('awaiting_approval','working','completing');

CREATE TABLE orders (                       -- one row per submission attempt
  order_id INTEGER PRIMARY KEY,
  intent_id INTEGER NOT NULL REFERENCES intents, attempt_no INTEGER NOT NULL,
  cl_ord_id TEXT NOT NULL UNIQUE,           -- uuid4 hex; inserted only after risk approval, BEFORE send
  exchange_order_id TEXT UNIQUE,
  side TEXT NOT NULL, limit_price TEXT NOT NULL, qty TEXT NOT NULL,
  filled_qty TEXT NOT NULL DEFAULT '0', avg_price TEXT,
  state TEXT NOT NULL CHECK (state IN ('created','submitting','open','partially_filled','filled',
          'cancel_requested','cancelled','rejected','unknown','not_found')),
  reject_reason TEXT,
  created_at TEXT NOT NULL, submitted_at TEXT, accepted_at TEXT, last_checked_at TEXT, closed_at TEXT,
  UNIQUE (intent_id, attempt_no)
);
CREATE UNIQUE INDEX one_live_order_per_intent ON orders(intent_id)
  WHERE state IN ('created','submitting','open','partially_filled','cancel_requested','unknown');

CREATE TABLE order_events (                 -- append-only transition log
  event_id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL REFERENCES orders,
  at TEXT NOT NULL, from_state TEXT, to_state TEXT NOT NULL, detail_json TEXT NOT NULL
);

CREATE TABLE fills (
  fill_id INTEGER PRIMARY KEY,
  exchange TEXT NOT NULL, exchange_trade_id TEXT NOT NULL,
  order_id INTEGER NOT NULL REFERENCES orders,
  at TEXT NOT NULL, pair TEXT NOT NULL, base TEXT NOT NULL, quote_ccy TEXT NOT NULL,
  side TEXT NOT NULL, qty TEXT NOT NULL, price TEXT NOT NULL,
  fee TEXT NOT NULL, fee_ccy TEXT NOT NULL CHECK (fee_ccy = quote_ccy),
  liquidity TEXT NOT NULL CHECK (liquidity IN ('maker','taker')),
  reference_price TEXT NOT NULL, slippage_bps REAL NOT NULL,
  quote_is_fiat INTEGER NOT NULL, simulated INTEGER NOT NULL,
  UNIQUE (exchange, exchange_trade_id)
);

CREATE TABLE equity_snapshots (
  at TEXT PRIMARY KEY, equity TEXT NOT NULL, cash TEXT NOT NULL, base_qty TEXT NOT NULL,
  mark_price TEXT NOT NULL, buy_hold_equity TEXT NOT NULL, is_day_open INTEGER NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX one_day_open_per_day ON equity_snapshots(substr(at,1,10)) WHERE is_day_open = 1;

CREATE TABLE equity_baselines (             -- drawdown baseline; latest row is active; append-only
  baseline_id INTEGER PRIMARY KEY, at TEXT NOT NULL, equity TEXT NOT NULL,
  reason TEXT NOT NULL, action_id INTEGER REFERENCES operator_actions   -- NULL for the first row
);

CREATE TABLE risk_snapshots (               -- per-tick RiskContext + usage, for the dashboard
  at TEXT PRIMARY KEY, context_json TEXT NOT NULL, usage_json TEXT NOT NULL
);

CREATE TABLE risk_events (
  event_id INTEGER PRIMARY KEY, at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('rejection','halt','halt_reset','kill_on','kill_off',
         'reconcile_mismatch','permission_refusal','stale_data','dust','exchange_reject')),
  rule TEXT NOT NULL, intent_id INTEGER REFERENCES intents,
  reason TEXT NOT NULL, detail_json TEXT NOT NULL
);

CREATE TABLE halts (
  halt_id INTEGER PRIMARY KEY,
  rule TEXT NOT NULL,                       -- daily_loss | total_drawdown | reconcile_mismatch | fatal_error
  triggered_at TEXT NOT NULL, reason TEXT NOT NULL,
  reset_at TEXT, reset_action_id INTEGER REFERENCES operator_actions
);
CREATE UNIQUE INDEX one_active_halt_per_rule ON halts(rule) WHERE reset_at IS NULL;
-- insert with ON CONFLICT DO NOTHING; a risk_events row is written every time

CREATE TABLE operator_actions (             -- the ONLY table the CLI writes; engine consumes
  action_id INTEGER PRIMARY KEY, at TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (kind IN ('approve','reject','reset_halt','flatten','kill_on','kill_off')),
  target_id TEXT, note TEXT NOT NULL, rebase_baseline INTEGER NOT NULL DEFAULT 0,
  consumed_at TEXT, result TEXT
);

CREATE TABLE errors (
  error_id INTEGER PRIMARY KEY, at TEXT NOT NULL, component TEXT NOT NULL,
  error_type TEXT NOT NULL, message TEXT NOT NULL, traceback TEXT     -- redacted before insert
);

CREATE TABLE api_calls (                    -- health; pruned to 30 days
  at TEXT NOT NULL, endpoint TEXT NOT NULL, latency_ms INTEGER NOT NULL,
  ok INTEGER NOT NULL, rate_limited INTEGER NOT NULL
);

-- Owned by `bot review` only (AD-20)
CREATE TABLE signal_counterfactuals (
  signal_id TEXT PRIMARY KEY REFERENCES signals, counterfactual_return TEXT NOT NULL,
  computed_at TEXT NOT NULL, data_hash TEXT NOT NULL
);
CREATE TABLE backtest_predictions (
  signal_id TEXT PRIMARY KEY REFERENCES signals, backtest_run_ref TEXT NOT NULL,
  predicted_fill_price TEXT, predicted_fill_at TEXT, predicted_equity TEXT NOT NULL,
  computed_at TEXT NOT NULL, data_hash TEXT NOT NULL
);
CREATE TABLE weekly_reviews (
  week_start TEXT PRIMARY KEY, computed_at TEXT NOT NULL, backtest_run_ref TEXT NOT NULL,
  trades_closed INTEGER NOT NULL, avg_trade_realized TEXT, avg_trade_expected TEXT,
  equity_diff_pp TEXT, max_fill_diff_pct TEXT,
  flag TEXT NOT NULL CHECK (flag IN ('ok','insufficient_trades','decaying','no_edge_baseline')),
  note TEXT
);

-- Owned by broker/paper.py only
CREATE TABLE paper_balances (asset TEXT PRIMARY KEY, free TEXT NOT NULL, locked TEXT NOT NULL);
CREATE TABLE paper_orders (
  exchange_order_id TEXT PRIMARY KEY, cl_ord_id TEXT NOT NULL UNIQUE, pair TEXT NOT NULL, side TEXT NOT NULL,
  qty TEXT NOT NULL, limit_price TEXT NOT NULL, filled_qty TEXT NOT NULL, state TEXT NOT NULL,
  accepted_at TEXT NOT NULL, closed_at TEXT
);
CREATE TABLE paper_fills (
  exchange_trade_id TEXT PRIMARY KEY, exchange_order_id TEXT NOT NULL REFERENCES paper_orders,
  at TEXT NOT NULL, qty TEXT NOT NULL, price TEXT NOT NULL, fee TEXT NOT NULL, fee_ccy TEXT NOT NULL
);

CREATE VIEW ledger AS                       -- tax ledger (CON-09, CON-10): a view, never a copy
  SELECT f.at, f.pair, f.base, f.quote_ccy, f.side, f.qty, f.price,
         f.fee, f.fee_ccy, f.simulated, f.exchange_trade_id,
         (f.side = 'sell' AND f.quote_is_fiat = 1) AS is_crypto_to_fiat_disposal
  FROM fills f ORDER BY f.at;

-- Write-once and append-only guards (AD-26, AD-17): enforced by the database itself.
-- schema_version is the only key a later migration may update.
CREATE TRIGGER schema_meta_write_once BEFORE UPDATE ON schema_meta
WHEN OLD.key <> 'schema_version' OR NEW.key <> 'schema_version'
BEGIN SELECT RAISE(ABORT, 'schema_meta is write-once'); END;
CREATE TRIGGER schema_meta_no_delete BEFORE DELETE ON schema_meta
BEGIN SELECT RAISE(ABORT, 'schema_meta is write-once'); END;
CREATE TRIGGER equity_baselines_append_only_u BEFORE UPDATE ON equity_baselines
BEGIN SELECT RAISE(ABORT, 'equity_baselines is append-only'); END;
CREATE TRIGGER equity_baselines_append_only_d BEFORE DELETE ON equity_baselines
BEGIN SELECT RAISE(ABORT, 'equity_baselines is append-only'); END;
CREATE TRIGGER order_events_append_only_u BEFORE UPDATE ON order_events
BEGIN SELECT RAISE(ABORT, 'order_events is append-only'); END;
CREATE TRIGGER order_events_append_only_d BEFORE DELETE ON order_events
BEGIN SELECT RAISE(ABORT, 'order_events is append-only'); END;
CREATE TRIGGER fills_side_check BEFORE INSERT ON fills
WHEN NEW.side NOT IN ('buy', 'sell')
BEGIN SELECT RAISE(ABORT, 'fills.side must be buy or sell'); END;
CREATE TRIGGER fills_immutable_u BEFORE UPDATE ON fills
BEGIN SELECT RAISE(ABORT, 'fills are immutable'); END;
CREATE TRIGGER fills_immutable_d BEFORE DELETE ON fills
BEGIN SELECT RAISE(ABORT, 'fills are immutable'); END;
