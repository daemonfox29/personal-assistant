CREATE TABLE records (
    record_id TEXT PRIMARY KEY CHECK (length(record_id) = 36),
    kind TEXT NOT NULL CHECK (
        kind IN ('fact', 'preference', 'event', 'note', 'insight', 'policy_preference')
    ),
    status TEXT NOT NULL CHECK (
        status IN ('candidate', 'confirmed', 'superseded', 'archived', 'deleted')
    ),
    sensitivity TEXT NOT NULL CHECK (
        sensitivity IN ('normal', 'personal', 'sensitive', 'restricted')
    ),
    mention_policy TEXT NOT NULL CHECK (
        mention_policy IN (
            'may_mention_when_relevant',
            'ask_before_mentioning',
            'only_when_directly_asked',
            'never_mention'
        )
    ),
    scope_type TEXT NOT NULL CHECK (
        scope_type IN ('global', 'conversation_domain', 'topic', 'entity', 'project', 'place')
    ),
    scope_id TEXT,
    primary_entity_id TEXT REFERENCES entities(entity_id) ON DELETE SET NULL,
    current_revision INTEGER NOT NULL CHECK (current_revision > 0),
    valid_from TEXT,
    valid_until TEXT,
    candidate_expires_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    row_version INTEGER NOT NULL DEFAULT 1 CHECK (row_version > 0),
    CHECK (
        (scope_type = 'global' AND scope_id IS NULL)
        OR (scope_type <> 'global' AND scope_id IS NOT NULL)
    ),
    CHECK (
        (status = 'candidate' AND candidate_expires_at IS NOT NULL)
        OR (status <> 'candidate' AND candidate_expires_at IS NULL)
    )
) STRICT;
