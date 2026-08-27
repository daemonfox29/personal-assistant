CREATE TABLE assistant_preference_revisions (
    setting_key TEXT NOT NULL CHECK (
        setting_key IN ('communication_style')
    ),
    revision INTEGER NOT NULL CHECK (revision > 0),
    value TEXT NOT NULL CHECK (length(value) <= 2000),
    created_at TEXT NOT NULL,
    PRIMARY KEY (setting_key, revision)
) STRICT;
