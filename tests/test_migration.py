"""Synthetic checks for exact, transactional encrypted schema migrations."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import UUID, uuid4

from personal_assistant.audit import (
    AuditOperation,
    AuditOutcome,
    AuditReasonCode,
    AuditWriteError,
    InMemoryAuditSink,
)
from personal_assistant.encrypted_database import (
    EncryptedDatabase,
    EncryptedDatabaseSettings,
)
from personal_assistant.key_provider import DatabaseKey
from personal_assistant.migration import (
    Migration,
    MigrationApplyError,
    MigrationHistoryError,
    MigrationRunner,
    MigrationSourceError,
    PackageMigrationSource,
    SCHEMA_COMPATIBILITY,
)


SYNTHETIC_KEY = bytes(range(32))


class SyntheticKeyProvider:
    def acquire(self, key_id: str) -> DatabaseKey:
        return DatabaseKey(SYNTHETIC_KEY)


class StaticMigrationSource:
    def __init__(self, migrations: tuple[Migration, ...]) -> None:
        self._migrations = migrations

    def load(self) -> tuple[Migration, ...]:
        return self._migrations


class FailingAuditSink:
    def write(self, event: object) -> None:
        raise AuditWriteError("Audit event could not be recorded.")


class TrackingConnectionProvider:
    def __init__(self, database: EncryptedDatabase) -> None:
        self._database = database
        self.connect_calls = 0

    def connect(self, correlation_id: UUID):  # type: ignore[no-untyped-def]
        self.connect_calls += 1
        return self._database.connect(correlation_id)


class MigrationTests(unittest.TestCase):
    def _database(self, path: Path) -> EncryptedDatabase:
        return EncryptedDatabase(
            EncryptedDatabaseSettings(path, "synthetic-migration-key"),
            key_provider=SyntheticKeyProvider(),
            audit_sink=InMemoryAuditSink(),
        )

    def _runner(
        self,
        database: EncryptedDatabase,
        *,
        migrations: tuple[Migration, ...] | None = None,
        audit_sink: object | None = None,
    ) -> tuple[MigrationRunner, InMemoryAuditSink]:
        sink = InMemoryAuditSink() if audit_sink is None else audit_sink
        source = (
            PackageMigrationSource()
            if migrations is None
            else StaticMigrationSource(migrations)
        )
        runner = MigrationRunner(
            connection_provider=database,
            migration_source=source,
            audit_sink=sink,  # type: ignore[arg-type]
        )
        return runner, sink  # type: ignore[return-value]

    def test_fresh_encrypted_database_migrates_to_current_schema(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.db"
            database = self._database(path)
            runner, audit_sink = self._runner(database)

            result = runner.migrate(uuid4())

            migrations = PackageMigrationSource().load()
            self.assertEqual(
                result.applied_versions,
                tuple(range(1, len(migrations) + 1)),
            )
            self.assertEqual(result.current_version, len(migrations))
            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
            with database.connect(uuid4()) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
                self.assertTrue(
                    {
                        "schema_migrations",
                        "records",
                        "record_revisions",
                        "entities",
                        "entity_aliases",
                        "entity_links",
                        "record_links",
                        "memory_feedback",
                        "deletion_ledger",
                    }.issubset(tables)
                )
                history = connection.execute(
                    "SELECT version, name, checksum, compatibility "
                    "FROM schema_migrations ORDER BY version"
                ).fetchall()
                self.assertEqual(len(history), len(migrations))
                self.assertTrue(
                    all(row[3] == SCHEMA_COMPATIBILITY for row in history)
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_key_check").fetchall(),
                    [],
                )

            migration_events = [
                event
                for event in audit_sink.events
                if event.operation is AuditOperation.DATABASE_MIGRATE
            ]
            self.assertEqual(
                [event.outcome for event in migration_events],
                [AuditOutcome.STARTED, AuditOutcome.SUCCEEDED],
            )

    def test_rerun_is_idempotent(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = self._database(Path(temporary_directory) / "memory.db")
            runner, _ = self._runner(database)
            first = runner.migrate(uuid4())
            second = runner.migrate(uuid4())

            self.assertGreater(len(first.applied_versions), 0)
            self.assertEqual(second.applied_versions, ())
            self.assertEqual(second.current_version, first.current_version)
            with database.connect(uuid4()) as connection:
                count = connection.execute(
                    "SELECT count(*) FROM schema_migrations"
                ).fetchone()[0]
            self.assertEqual(count, first.current_version)

    def test_new_entity_link_migrations_apply_forward_from_prior_schema(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = self._database(Path(temporary_directory) / "memory.db")
            migrations = PackageMigrationSource().load()
            prior_runner, _ = self._runner(
                database,
                migrations=migrations[:13],
            )
            prior_runner.migrate(uuid4())

            current_runner, _ = self._runner(database)
            result = current_runner.migrate(uuid4())

            self.assertEqual(result.applied_versions, (14, 15))
            with database.connect(uuid4()) as connection:
                tables = {
                    row[0]
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type = 'table'"
                    ).fetchall()
                }
            self.assertIn("records", tables)
            self.assertIn("entity_links", tables)

    def test_missing_duplicate_and_reordered_sources_are_rejected_before_open(self) -> None:
        migrations = PackageMigrationSource().load()
        invalid_sources = (
            migrations[:1] + migrations[2:],
            (migrations[0], migrations[0]),
            (migrations[1], migrations[0]) + migrations[2:],
        )
        with TemporaryDirectory() as temporary_directory:
            for index, invalid in enumerate(invalid_sources):
                database = self._database(
                    Path(temporary_directory) / f"memory-{index}.db"
                )
                provider = TrackingConnectionProvider(database)
                runner = MigrationRunner(
                    connection_provider=provider,
                    migration_source=StaticMigrationSource(invalid),
                    audit_sink=InMemoryAuditSink(),
                )

                with self.assertRaises(MigrationSourceError):
                    runner.migrate(uuid4())

                self.assertEqual(provider.connect_calls, 0)

    def test_migration_object_rejects_a_forged_checksum(self) -> None:
        with self.assertRaisesRegex(MigrationSourceError, "does not match"):
            Migration(
                1,
                "synthetic",
                "CREATE TABLE synthetic (id INTEGER)",
                "0" * 64,
            )

    def test_checksum_modified_migration_is_rejected_without_schema_change(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = self._database(Path(temporary_directory) / "memory.db")
            runner, _ = self._runner(database)
            original_result = runner.migrate(uuid4())
            migrations = PackageMigrationSource().load()
            changed_first = Migration.from_bytes(
                migrations[0].version,
                migrations[0].name,
                (migrations[0].statement + "\n").encode("utf-8"),
            )
            changed = (changed_first,) + migrations[1:]
            changed_runner, audit_sink = self._runner(
                database,
                migrations=changed,
            )

            with self.assertRaisesRegex(MigrationHistoryError, "does not match"):
                changed_runner.migrate(uuid4())

            with database.connect(uuid4()) as connection:
                count = connection.execute(
                    "SELECT count(*) FROM schema_migrations"
                ).fetchone()[0]
            self.assertEqual(count, original_result.current_version)
            self.assertEqual(audit_sink.events[-1].outcome, AuditOutcome.FAILED)
            self.assertEqual(
                audit_sink.events[-1].reason_code,
                AuditReasonCode.MIGRATION_FAILED,
            )

    def test_database_newer_than_source_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = self._database(Path(temporary_directory) / "memory.db")
            runner, _ = self._runner(database)
            runner.migrate(uuid4())
            migrations = PackageMigrationSource().load()
            older_runner, _ = self._runner(
                database,
                migrations=migrations[:-1],
            )

            with self.assertRaisesRegex(MigrationHistoryError, "newer"):
                older_runner.migrate(uuid4())

    def test_gap_in_stored_history_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = self._database(Path(temporary_directory) / "memory.db")
            runner, _ = self._runner(database)
            runner.migrate(uuid4())
            with database.connect(uuid4()) as connection:
                connection.execute("DELETE FROM schema_migrations WHERE version = 5")
                connection.commit()

            with self.assertRaisesRegex(MigrationHistoryError, "does not match"):
                runner.migrate(uuid4())

            with database.connect(uuid4()) as connection:
                versions = [
                    row[0]
                    for row in connection.execute(
                        "SELECT version FROM schema_migrations ORDER BY version"
                    ).fetchall()
                ]
            self.assertNotIn(5, versions)
            self.assertEqual(
                len(versions),
                len(PackageMigrationSource().load()) - 1,
            )

    def test_failing_pending_batch_rolls_back_completely(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = self._database(Path(temporary_directory) / "memory.db")
            first = PackageMigrationSource().load()[0]
            invalid = Migration.from_bytes(
                2,
                "synthetic_failure",
                b"CREATE TABLE synthetic_broken (",
            )
            runner, audit_sink = self._runner(
                database,
                migrations=(first, invalid),
            )

            with self.assertRaisesRegex(MigrationApplyError, "failed safely"):
                runner.migrate(uuid4())

            with database.connect(uuid4()) as connection:
                user_tables = connection.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
            self.assertEqual(user_tables, [])
            self.assertEqual(audit_sink.events[-1].outcome, AuditOutcome.FAILED)

    def test_untracked_existing_schema_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = self._database(Path(temporary_directory) / "memory.db")
            with database.connect(uuid4()) as connection:
                connection.execute("CREATE TABLE synthetic_untracked (id INTEGER)")
                connection.commit()
            runner, _ = self._runner(database)

            with self.assertRaisesRegex(
                MigrationHistoryError,
                "without migration history",
            ):
                runner.migrate(uuid4())

            with database.connect(uuid4()) as connection:
                names = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            self.assertEqual(names, [("synthetic_untracked",)])

    def test_audit_failure_prevents_database_open(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            database = self._database(Path(temporary_directory) / "memory.db")
            provider = TrackingConnectionProvider(database)
            runner = MigrationRunner(
                connection_provider=provider,
                migration_source=PackageMigrationSource(),
                audit_sink=FailingAuditSink(),
            )

            with self.assertRaises(AuditWriteError):
                runner.migrate(uuid4())

            self.assertEqual(provider.connect_calls, 0)

    def test_migration_errors_do_not_expose_sql_or_database_path(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            sensitive_path = Path(temporary_directory) / "private-name.db"
            database = self._database(sensitive_path)
            first = PackageMigrationSource().load()[0]
            secret_marker = "synthetic_secret_marker"
            invalid = Migration.from_bytes(
                2,
                "safe_failure",
                f"CREATE TABLE {secret_marker} (".encode("utf-8"),
            )
            runner, audit_sink = self._runner(
                database,
                migrations=(first, invalid),
            )

            with self.assertRaises(MigrationApplyError) as raised:
                runner.migrate(uuid4())

            displayed = f"{raised.exception!s} {audit_sink.events!r}"
            self.assertNotIn(secret_marker, displayed)
            self.assertNotIn(temporary_directory, displayed)


if __name__ == "__main__":
    unittest.main()
