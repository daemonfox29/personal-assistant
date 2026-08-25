CREATE TABLE entity_links (
    link_id TEXT PRIMARY KEY CHECK (length(link_id) = 36),
    source_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    target_entity_id TEXT NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    relationship TEXT NOT NULL CHECK (
        relationship IN ('related', 'member_of', 'located_at', 'associated_with')
    ),
    source_type TEXT NOT NULL CHECK (
        source_type IN ('explicit_user', 'trusted_interface', 'deterministic_rule', 'model_candidate')
    ),
    source_ref TEXT NOT NULL CHECK (length(source_ref) BETWEEN 1 AND 128),
    created_at TEXT NOT NULL,
    CHECK (source_entity_id <> target_entity_id),
    UNIQUE (source_entity_id, target_entity_id, relationship)
) STRICT;
