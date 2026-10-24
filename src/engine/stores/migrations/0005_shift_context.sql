-- What a shift meant, beside when the server recorded it (shift_ts):
-- evidence_ts is when in the evidence's history it happened (they differ by
-- decades after a rebuild), and the programmes say whether the lead passed to
-- another worldview or to a variant of the same one. NULL for shifts
-- recorded before these columns existed.
ALTER TABLE paradigm_shifts ADD COLUMN evidence_ts TEXT;
ALTER TABLE paradigm_shifts ADD COLUMN prev_programme TEXT;
ALTER TABLE paradigm_shifts ADD COLUMN new_programme TEXT;
