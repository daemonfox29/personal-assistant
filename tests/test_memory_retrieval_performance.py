"""Opt-in 100,000-record retrieval benchmark using synthetic encrypted data."""

from datetime import datetime, timezone
from hashlib import sha256
import math
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from time import perf_counter
import unittest
from uuid import UUID, uuid4

from personal_assistant.audit import InMemoryAuditSink
from personal_assistant.encrypted_database import (
    EncryptedDatabase,
    EncryptedDatabaseSettings,
)
from personal_assistant.key_provider import DatabaseKey
from personal_assistant.memory_repository import MemoryRepository, RetrievalRequest
from personal_assistant.memory_types import canonical_json
from personal_assistant.migration import MigrationRunner, PackageMigrationSource


SYNTHETIC_KEY = bytes(range(32))
RECORD_COUNT = 100_000
QUERY_COUNT = 30


class SyntheticKeyProvider:
    def acquire(self, key_id: str) -> DatabaseKey:
        return DatabaseKey(SYNTHETIC_KEY)


@unittest.skipUnless(
    os.environ.get("RUN_MEMORY_PERFORMANCE") == "1",
    "set RUN_MEMORY_PERFORMANCE=1 for the 100,000-record benchmark",
)
class MemoryRetrievalPerformanceTests(unittest.TestCase):
    def test_encrypted_indexed_retrieval_p95_is_below_target(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.db"
            audit_sink = InMemoryAuditSink()
            database = EncryptedDatabase(
                EncryptedDatabaseSettings(path, "synthetic-performance-key"),
                key_provider=SyntheticKeyProvider(),
                audit_sink=audit_sink,
            )
            MigrationRunner(
                connection_provider=database,
                migration_source=PackageMigrationSource(),
                audit_sink=audit_sink,
            ).migrate(uuid4())
            timestamp = datetime(2026, 1, 1, tzinfo=timezone.utc).isoformat()
            with database.connect(uuid4()) as connection:
                connection.execute("BEGIN IMMEDIATE")
                for start in range(0, RECORD_COUNT, 2_000):
                    record_rows = []
                    revision_rows = []
                    search_rows = []
                    for index in range(start, min(start + 2_000, RECORD_COUNT)):
                        record_id = str(UUID(int=index + 1))
                        payload = {
                            "type": "fact",
                            "subject": f"synthetic cohort {index % 1_000}",
                            "statement": f"synthetic benchmark item {index}",
                        }
                        snapshot = canonical_json(
                            {
                                "schema_version": 1,
                                "kind": "fact",
                                "status": "confirmed",
                                "sensitivity": "normal",
                                "mention_policy": "may_mention_when_relevant",
                                "scope_type": "global",
                                "scope_id": None,
                                "primary_entity_id": None,
                                "valid_from": None,
                                "valid_until": None,
                                "candidate_expires_at": None,
                                "payload": payload,
                            }
                        )
                        record_rows.append((record_id, timestamp, timestamp))
                        revision_rows.append(
                            (
                                record_id,
                                snapshot,
                                sha256(snapshot.encode("utf-8")).hexdigest(),
                                timestamp,
                            )
                        )
                        search_rows.append(
                            (
                                record_id,
                                canonical_json(payload),
                                timestamp,
                            )
                        )
                    connection.executemany(
                        "INSERT INTO records (record_id, kind, status, sensitivity, "
                        "mention_policy, scope_type, scope_id, primary_entity_id, "
                        "current_revision, valid_from, valid_until, "
                        "candidate_expires_at, created_at, updated_at, row_version) "
                        "VALUES (?, 'fact', 'confirmed', 'normal', "
                        "'may_mention_when_relevant', 'global', NULL, NULL, 1, "
                        "NULL, NULL, NULL, ?, ?, 1)",
                        record_rows,
                    )
                    connection.executemany(
                        "INSERT INTO record_revisions (record_id, revision, "
                        "payload_version, payload_json, source_type, source_ref, "
                        "reason_code, actor_type, model_version, previous_hash, "
                        "content_hash, created_at) VALUES (?, 1, 1, ?, "
                        "'explicit_user', 'synthetic-performance', 'created', "
                        "'user', NULL, NULL, ?, ?)",
                        revision_rows,
                    )
                    connection.executemany(
                        "INSERT INTO record_search (record_id, content, status, "
                        "sensitivity, mention_policy, scope_type, scope_id, kind, "
                        "valid_from, valid_until, primary_entity_id, updated_at) "
                        "VALUES (?, ?, 'confirmed', 'normal', "
                        "'may_mention_when_relevant', 'global', NULL, 'fact', NULL, "
                        "NULL, NULL, ?)",
                        search_rows,
                    )
                connection.commit()

            repository = MemoryRepository(
                connection_provider=database,
                audit_sink=audit_sink,
                clock=lambda: datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
            request = RetrievalRequest("cohort 999 benchmark")
            repository.retrieve(request, uuid4())
            durations_ms = []
            result = None
            for _ in range(QUERY_COUNT):
                started = perf_counter()
                result = repository.retrieve(request, uuid4())
                durations_ms.append((perf_counter() - started) * 1_000)

            durations_ms.sort()
            p95 = durations_ms[math.ceil(0.95 * len(durations_ms)) - 1]
            median = durations_ms[len(durations_ms) // 2]
            assert result is not None
            print(
                "memory-retrieval-benchmark "
                f"records={RECORD_COUNT} queries={QUERY_COUNT} "
                f"median_ms={median:.2f} p95_ms={p95:.2f} "
                f"examined={result.receipt.records_examined} "
                f"returned={result.receipt.records_returned} "
                f"tokens={result.receipt.tokens_returned} "
                f"database_bytes={path.stat().st_size}"
            )
            self.assertLess(p95, 100.0)
            self.assertLessEqual(result.receipt.records_returned, 12)
            self.assertLessEqual(result.receipt.tokens_returned, 2_500)


if __name__ == "__main__":
    unittest.main()
