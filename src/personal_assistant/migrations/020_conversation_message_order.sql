CREATE INDEX conversation_message_order ON conversation_messages (
    conversation_id,
    sequence
);
