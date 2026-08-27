CREATE TABLE conversation_messages (
    message_id TEXT PRIMARY KEY CHECK (length(message_id) = 36),
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id) ON DELETE CASCADE,
    sequence INTEGER NOT NULL CHECK (sequence > 0),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'notice')),
    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 262144),
    created_at TEXT NOT NULL,
    UNIQUE (conversation_id, sequence)
) STRICT;
