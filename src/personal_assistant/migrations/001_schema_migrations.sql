CREATE TABLE schema_migrations (
    version INTEGER PRIMARY KEY CHECK (version > 0),
    name TEXT NOT NULL UNIQUE CHECK (length(name) BETWEEN 1 AND 128),
    checksum TEXT NOT NULL CHECK (
        length(checksum) = 64
        AND checksum NOT GLOB '*[^0-9a-f]*'
    ),
    applied_at TEXT NOT NULL,
    compatibility TEXT NOT NULL CHECK (length(compatibility) BETWEEN 1 AND 128)
) STRICT;
