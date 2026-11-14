-- Schema v3 (M3): api_calls carries a JSON detail. Dry-run records the bid/ask each order
-- was priced from (AD-6 consistency test input) and the endpoint context of rate limits.
ALTER TABLE api_calls ADD COLUMN detail_json TEXT;
CREATE INDEX api_calls_at ON api_calls(at);
CREATE INDEX heartbeats_at ON heartbeats(at);
