CREATE TABLE deletion_ledger (
    purged_id TEXT PRIMARY KEY CHECK (length(purged_id) = 36),
    purged_at TEXT NOT NULL,
    reason_code TEXT NOT NULL CHECK (length(reason_code) BETWEEN 1 AND 64)
) STRICT;
