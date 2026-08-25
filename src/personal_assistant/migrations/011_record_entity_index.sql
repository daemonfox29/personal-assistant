CREATE INDEX record_entity_index
ON records (primary_entity_id, status, updated_at DESC);
