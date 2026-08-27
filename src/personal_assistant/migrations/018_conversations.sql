CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY CHECK (length(conversation_id) = 36),
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 160),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    archived INTEGER NOT NULL DEFAULT 0 CHECK (archived IN (0, 1))
) STRICT;
