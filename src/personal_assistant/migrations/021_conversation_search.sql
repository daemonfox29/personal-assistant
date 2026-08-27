CREATE VIRTUAL TABLE conversation_search USING fts5(message_id UNINDEXED, conversation_id UNINDEXED, sequence UNINDEXED, role UNINDEXED, content, created_at UNINDEXED, tokenize = 'unicode61')
