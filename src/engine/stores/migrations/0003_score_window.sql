-- The score window (REFACTOR_SPEC D14): log_score and evidence_count with
-- older evidence discounted. Existing rows start from the undiscounted totals,
-- which decay toward the true window as new evidence arrives.
ALTER TABLE ontology_candidates ADD COLUMN window_log_score REAL NOT NULL DEFAULT 0;
ALTER TABLE ontology_candidates ADD COLUMN window_evidence REAL NOT NULL DEFAULT 0;
UPDATE ontology_candidates SET window_log_score = log_score, window_evidence = evidence_count;
