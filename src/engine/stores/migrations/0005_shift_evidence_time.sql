-- When in the evidence's history a shift happened, beside shift_ts (when the
-- server recorded it). They differ by decades after a rebuild. NULL for
-- shifts recorded before this column existed.
ALTER TABLE paradigm_shifts ADD COLUMN evidence_ts TEXT;
