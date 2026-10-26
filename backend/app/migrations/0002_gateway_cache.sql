-- Gateway (Portkey) response-cache status per agent run, from x-portkey-cache-status headers.
ALTER TABLE agent_runs ADD COLUMN gateway_cache_hits INTEGER;
ALTER TABLE agent_runs ADD COLUMN gateway_cache_misses INTEGER;
-- Retrieved items withheld from the model because they look like instructions.
ALTER TABLE agent_runs ADD COLUMN quarantined_items INTEGER NOT NULL DEFAULT 0;
