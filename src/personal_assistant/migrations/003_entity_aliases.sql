CREATE TABLE entity_aliases (
    alias_id TEXT PRIMARY KEY CHECK (length(alias_id) = 36),
    entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    normalized_alias TEXT NOT NULL CHECK (length(normalized_alias) BETWEEN 1 AND 512),
    display_alias TEXT NOT NULL CHECK (length(display_alias) BETWEEN 1 AND 512),
    source_type TEXT NOT NULL CHECK (
        source_type IN ('explicit_user', 'trusted_interface', 'deterministic_match', 'model_candidate')
    ),
    source_ref TEXT NOT NULL CHECK (length(source_ref) BETWEEN 1 AND 128),
    confidence_basis TEXT NOT NULL CHECK (
        confidence_basis IN ('explicit', 'exact_match', 'candidate')
    ),
    created_at TEXT NOT NULL,
    UNIQUE (entity_id, normalized_alias)
) STRICT;
