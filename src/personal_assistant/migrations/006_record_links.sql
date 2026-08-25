CREATE TABLE record_links (
    link_id TEXT PRIMARY KEY CHECK (length(link_id) = 36),
    source_record_id TEXT NOT NULL REFERENCES records(record_id) ON DELETE CASCADE,
    target_record_id TEXT NOT NULL REFERENCES records(record_id) ON DELETE CASCADE,
    relationship TEXT NOT NULL CHECK (
        relationship IN ('evidence', 'contradiction', 'supersession', 'related')
    ),
    source_type TEXT NOT NULL CHECK (
        source_type IN ('explicit_user', 'trusted_interface', 'deterministic_rule', 'model_candidate')
    ),
    source_ref TEXT NOT NULL CHECK (length(source_ref) BETWEEN 1 AND 128),
    created_at TEXT NOT NULL,
    CHECK (source_record_id <> target_record_id),
    UNIQUE (source_record_id, target_record_id, relationship)
) STRICT;
