CREATE TABLE entities (
    entity_id TEXT PRIMARY KEY CHECK (length(entity_id) = 36),
    entity_type TEXT NOT NULL CHECK (
        entity_type IN ('person', 'pet', 'place', 'project', 'organization', 'other')
    ),
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('active', 'merged', 'archived', 'deleted')
    ),
    merged_into_entity_id TEXT REFERENCES entities(entity_id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    CHECK (entity_id <> merged_into_entity_id),
    CHECK (
        (status = 'merged' AND merged_into_entity_id IS NOT NULL)
        OR (status <> 'merged' AND merged_into_entity_id IS NULL)
    )
) STRICT;
