-- Persist the whole population so a restart resumes it exactly
-- (REFACTOR_SPEC 3.3, B1). Before this, candidates were written but never
-- read back, edges were not stored at all, and CPTs were keyed by an edge
-- signature that changes whenever an edge is pruned.

-- JSON: the population's candidate ids in order, rng state, batch index,
-- last mutation stats. The id list defines membership: ontology_candidates
-- also holds rows from earlier sessions that are not part of this population.
-- NULL marks a row written by pre-0002 code, which cannot be resumed.
ALTER TABLE ontology_populations ADD COLUMN state TEXT;

-- Keyed by position, not edge_id: nothing guarantees a domain never shares an
-- edge object (and its id) between two seed candidates.
CREATE TABLE IF NOT EXISTS candidate_edges (
    candidate_id           TEXT NOT NULL,
    ordinal                INT  NOT NULL,
    edge_id                TEXT NOT NULL,
    parent_variable_id     TEXT NOT NULL,
    child_variable_id      TEXT NOT NULL,
    dependency_kind        TEXT NOT NULL,
    existence_prior        REAL NOT NULL,
    existence_probability  REAL NOT NULL,
    existence_update_count INT  NOT NULL,
    explore_weight         REAL NOT NULL,
    explanatory_label      TEXT NOT NULL DEFAULT '',
    learnable              INT  NOT NULL,
    enabled                INT  NOT NULL,
    PRIMARY KEY (candidate_id, ordinal)
);

CREATE TABLE IF NOT EXISTS candidate_parameters (
    candidate_id      TEXT NOT NULL,
    variable_name     TEXT NOT NULL,
    domain_module_id  TEXT NOT NULL,
    alpha             REAL NOT NULL,
    counts_json       TEXT NOT NULL,
    parent_names_json TEXT NOT NULL,
    updated_at        TEXT NOT NULL,
    PRIMARY KEY (candidate_id, variable_name)
);
