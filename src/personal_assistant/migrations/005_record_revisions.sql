CREATE TABLE record_revisions (
    record_id TEXT NOT NULL REFERENCES records(record_id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision > 0),
    payload_version INTEGER NOT NULL CHECK (payload_version > 0),
    payload_json TEXT NOT NULL CHECK (json_valid(payload_json)),
    source_type TEXT NOT NULL CHECK (
        source_type IN ('explicit_user', 'trusted_interface', 'model_candidate', 'migration')
    ),
    source_ref TEXT NOT NULL CHECK (length(source_ref) BETWEEN 1 AND 128),
    reason_code TEXT NOT NULL CHECK (length(reason_code) BETWEEN 1 AND 64),
    actor_type TEXT NOT NULL CHECK (
        actor_type IN ('user', 'system', 'model_candidate')
    ),
    model_version TEXT CHECK (model_version IS NULL OR length(model_version) BETWEEN 1 AND 128),
    previous_hash TEXT CHECK (previous_hash IS NULL OR length(previous_hash) = 64),
    content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
    created_at TEXT NOT NULL,
    PRIMARY KEY (record_id, revision),
    CHECK (
        (revision = 1 AND previous_hash IS NULL)
        OR (revision > 1 AND previous_hash IS NOT NULL)
    )
) STRICT;
