-- Every ingest asks "is this day from this source already stored?"; without an
-- index that is a scan of the domain's whole evidence history.
CREATE INDEX IF NOT EXISTS idx_evidence_domain_timestamp
    ON evidence_records (domain_module, timestamp);
