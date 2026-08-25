CREATE INDEX record_retrieval_index
ON records (status, sensitivity, mention_policy, scope_type, scope_id, updated_at DESC);
