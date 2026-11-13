-- Schema v2 (audit M2 F-3): the AD-28 completion phase is a NEW order intent linked to
-- its parent (parent_intent_id), with its own signal-free journal row; it counts against
-- max_order_intents_per_day and gets its own max_submissions_per_intent under the normal
-- rules. SQLite cannot alter a CHECK, so intents is rebuilt (store.py runs migrations with
-- foreign keys off and a full foreign_key_check before COMMIT).
CREATE TABLE intents_v2 (
  intent_id INTEGER PRIMARY KEY,
  signal_id TEXT UNIQUE REFERENCES signals,
  source_action_id INTEGER UNIQUE REFERENCES operator_actions,   -- set for flatten
  parent_intent_id INTEGER UNIQUE REFERENCES intents(intent_id), -- set for a completion intent
  is_flatten INTEGER NOT NULL DEFAULT 0,
  pair TEXT NOT NULL, side TEXT NOT NULL CHECK (side IN ('buy','sell')),
  reference_price TEXT NOT NULL,            -- signal close, or mid at creation (flatten, completion)
  target_qty TEXT NOT NULL, filled_qty TEXT NOT NULL DEFAULT '0',   -- filled_qty = sum(fills) (AD-27)
  state TEXT NOT NULL CHECK (state IN ('awaiting_approval','working','completing','done',
          'expired','cancelled','halted')),
  approval_mode TEXT NOT NULL CHECK (approval_mode IN ('manual','autonomous')),
  approval_deadline_at TEXT, window_end_at TEXT NOT NULL, completion_end_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  CHECK ((is_flatten = 0 AND parent_intent_id IS NULL AND signal_id IS NOT NULL
          AND source_action_id IS NULL)
      OR (is_flatten = 0 AND parent_intent_id IS NOT NULL AND signal_id IS NULL
          AND source_action_id IS NULL AND side = 'buy')
      OR (is_flatten = 1 AND parent_intent_id IS NULL AND signal_id IS NULL
          AND source_action_id IS NOT NULL))
);
INSERT INTO intents_v2 (intent_id, signal_id, source_action_id, parent_intent_id, is_flatten,
  pair, side, reference_price, target_qty, filled_qty, state, approval_mode,
  approval_deadline_at, window_end_at, completion_end_at, created_at, updated_at)
  SELECT intent_id, signal_id, source_action_id, NULL, is_flatten, pair, side,
         reference_price, target_qty, filled_qty, state, approval_mode, approval_deadline_at,
         window_end_at, completion_end_at, created_at, updated_at FROM intents;
DROP TABLE intents;
ALTER TABLE intents_v2 RENAME TO intents;
CREATE UNIQUE INDEX one_active_intent_per_pair ON intents(pair)
  WHERE state IN ('awaiting_approval','working','completing');
