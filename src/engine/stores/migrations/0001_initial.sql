-- Schema as it existed before migrations were introduced (REFACTOR_SPEC 3.1).
-- IF NOT EXISTS so databases created by the pre-migration code adopt this
-- version without changes. Shared with PostgreSQL: plain types, no SQLite-only
-- syntax.

CREATE TABLE IF NOT EXISTS evidence_records (
    evidence_id   TEXT PRIMARY KEY,
    domain_module TEXT NOT NULL,
    timestamp     TEXT NOT NULL,
    source_type   TEXT NOT NULL,
    source_ref    TEXT NOT NULL DEFAULT '',
    confidence    REAL NOT NULL DEFAULT 1.0,
    assignments   TEXT NOT NULL DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS parameters (
    candidate_id     TEXT NOT NULL,
    domain_module_id TEXT NOT NULL DEFAULT '',
    edge_signature   TEXT NOT NULL DEFAULT '',
    variable_name    TEXT NOT NULL,
    alpha            REAL NOT NULL DEFAULT 1.0,
    counts_json      TEXT NOT NULL DEFAULT '[]',
    parent_ids_json  TEXT NOT NULL DEFAULT '[]',
    updated_at       TEXT NOT NULL,
    PRIMARY KEY (domain_module_id, edge_signature, variable_name)
);

CREATE TABLE IF NOT EXISTS ontology_populations (
    population_id         TEXT PRIMARY KEY,
    domain_module_id      TEXT NOT NULL UNIQUE,
    max_population_size   INT  NOT NULL DEFAULT 10,
    active_candidate_id   TEXT,
    generation            INT  NOT NULL DEFAULT 0,
    paradigm_shift_count  INT  NOT NULL DEFAULT 0,
    updated_at            TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS ontology_candidates (
    candidate_id         TEXT PRIMARY KEY,
    domain_module_id     TEXT NOT NULL,
    generation           INT  NOT NULL DEFAULT 0,
    parent_candidate_id  TEXT,
    log_score            REAL NOT NULL DEFAULT 0.0,
    evidence_count       INT  NOT NULL DEFAULT 0,
    status               TEXT NOT NULL DEFAULT 'ACTIVE',
    introduced_at        TEXT NOT NULL,
    pruned_at            TEXT,
    pruning_reason       TEXT,
    description          TEXT NOT NULL DEFAULT '',
    metadata             TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS candidate_scores (
    score_id          TEXT PRIMARY KEY,
    candidate_id      TEXT NOT NULL,
    ts                TEXT NOT NULL,
    log_likelihood    REAL NOT NULL,
    batch_index       INT  NOT NULL DEFAULT 0,
    context           TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS paradigm_shifts (
    shift_id                TEXT PRIMARY KEY,
    domain_module_id        TEXT NOT NULL,
    generation              INT  NOT NULL,
    shift_ts                TEXT NOT NULL,
    prev_dominant_id        TEXT NOT NULL,
    prev_dominant_name      TEXT NOT NULL DEFAULT '',
    new_dominant_id         TEXT NOT NULL,
    new_dominant_name       TEXT NOT NULL DEFAULT '',
    evidence_count_at_shift INT  NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_paradigm_shifts_domain
    ON paradigm_shifts (domain_module_id, shift_ts ASC);
