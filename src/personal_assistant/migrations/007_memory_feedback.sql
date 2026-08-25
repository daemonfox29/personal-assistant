CREATE TABLE memory_feedback (
    feedback_id TEXT PRIMARY KEY CHECK (length(feedback_id) = 36),
    record_id TEXT NOT NULL REFERENCES records(record_id) ON DELETE CASCADE,
    feedback_type TEXT NOT NULL CHECK (
        feedback_type IN ('confirm', 'reject', 'edit', 'delete', 'relevant', 'irrelevant')
    ),
    memory_kind TEXT NOT NULL CHECK (
        memory_kind IN ('fact', 'preference', 'event', 'note', 'insight', 'policy_preference')
    ),
    scoring_label TEXT CHECK (scoring_label IS NULL OR length(scoring_label) BETWEEN 1 AND 64),
    created_at TEXT NOT NULL
) STRICT;
