CREATE TABLE named_memory_scopes (
    scope_id TEXT PRIMARY KEY CHECK (length(scope_id) = 36),
    scope_type TEXT NOT NULL CHECK (
        scope_type IN ('topic', 'project', 'place')
    ),
    normalized_label TEXT NOT NULL CHECK (
        length(normalized_label) BETWEEN 1 AND 64
    ),
    display_label TEXT NOT NULL CHECK (
        length(display_label) BETWEEN 1 AND 64
    ),
    created_at TEXT NOT NULL,
    UNIQUE (scope_type, normalized_label)
) STRICT;
