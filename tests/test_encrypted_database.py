"""Synthetic-data checks for the fail-closed SQLCipher boundary."""

import os
from pathlib import Path
import sqlite3
import stat
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from personal_assistant.audit import (
    AuditOutcome,
    AuditReasonCode,
    AuditWriteError,
    InMemoryAuditSink,
)
from personal_assistant.encrypted_database import (
    EncryptedDatabase,
    EncryptedDatabaseConfigurationError,
    EncryptedDatabaseOpenError,
    EncryptedDatabaseSettings,
    EncryptedDatabaseUnlockError,
    EncryptedConnectionProvider,
    EncryptionUnavailableError,
)
from personal_assistant.key_provider import DatabaseKey


SYNTHETIC_KEY = bytes(range(32))
OTHER_SYNTHETIC_KEY = bytes(reversed(range(32)))


class SyntheticKeyProvider:
    def __init__(self, key: bytes = SYNTHETIC_KEY) -> None:
        self._key = key
        self.requested_ids: list[str] = []
        self.last_key: DatabaseKey | None = None

    def acquire(self, key_id: str) -> DatabaseKey:
        self.requested_ids.append(key_id)
        self.last_key = DatabaseKey(self._key)
        return self.last_key


class FailingAuditSink:
    def write(self, event: object) -> None:
        raise AuditWriteError("Audit event could not be recorded.")


class EncryptedDatabaseSettingsTests(unittest.TestCase):
    def test_path_key_id_and_timeouts_are_validated(self) -> None:
        absolute_path = Path.cwd() / "memory.db"

        with self.assertRaisesRegex(ValueError, "absolute path"):
            EncryptedDatabaseSettings(Path("memory.db"), "primary")
        with self.assertRaisesRegex(ValueError, "safe label"):
            EncryptedDatabaseSettings(absolute_path, "unsafe key\nname")
        with self.assertRaisesRegex(ValueError, "safe range"):
            EncryptedDatabaseSettings(absolute_path, "primary", timeout_seconds=0)
        with self.assertRaisesRegex(ValueError, "safe range"):
            EncryptedDatabaseSettings(absolute_path, "primary", busy_timeout_ms=True)


class EncryptedDatabaseTests(unittest.TestCase):
    def _database(
        self,
        path: Path,
        *,
        key: bytes = SYNTHETIC_KEY,
        audit_sink: object | None = None,
    ) -> tuple[EncryptedDatabase, SyntheticKeyProvider, InMemoryAuditSink]:
        provider = SyntheticKeyProvider(key)
        sink = InMemoryAuditSink() if audit_sink is None else audit_sink
        database = EncryptedDatabase(
            EncryptedDatabaseSettings(path, "primary-memory-key"),
            key_provider=provider,
            audit_sink=sink,  # type: ignore[arg-type]
        )
        return database, provider, sink  # type: ignore[return-value]

    def test_synthetic_data_is_encrypted_and_reopens_with_same_key(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.db"
            database, provider, audit_sink = self._database(path)

            self.assertIsInstance(database, EncryptedConnectionProvider)

            with database.connect(uuid4()) as connection:
                connection.execute(
                    "CREATE TABLE synthetic_records (value TEXT NOT NULL)"
                )
                connection.execute(
                    "INSERT INTO synthetic_records VALUES (?)",
                    ("synthetic-only",),
                )
                connection.commit()

            self.assertNotEqual(path.read_bytes()[:16], b"SQLite format 3\x00")
            self.assertEqual(provider.requested_ids, ["primary-memory-key"])
            self.assertIsNotNone(provider.last_key)
            self.assertTrue(provider.last_key.is_cleared)
            self.assertEqual(
                [event.outcome for event in audit_sink.events],
                [AuditOutcome.STARTED, AuditOutcome.SUCCEEDED],
            )
            if os.name == "posix":
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

            reopened, _, _ = self._database(path)
            with reopened.connect(uuid4()) as connection:
                value = connection.execute(
                    "SELECT value FROM synthetic_records"
                ).fetchone()[0]
                self.assertEqual(value, "synthetic-only")
                self.assertEqual(
                    connection.execute("PRAGMA cipher_status").fetchone(),
                    ("1",),
                )
                self.assertEqual(
                    connection.execute("PRAGMA foreign_keys").fetchone(),
                    (1,),
                )
                self.assertEqual(
                    connection.execute("PRAGMA trusted_schema").fetchone(),
                    (0,),
                )
                compile_options = {
                    row[0]
                    for row in connection.execute("PRAGMA compile_options").fetchall()
                }
                self.assertIn("ENABLE_FTS5", compile_options)

    def test_wrong_key_is_rejected_with_content_free_audit(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.db"
            database, _, _ = self._database(path)
            with database.connect(uuid4()) as connection:
                connection.execute("CREATE TABLE sample (value INTEGER)")
                connection.commit()

            wrong_database, _, audit_sink = self._database(
                path,
                key=OTHER_SYNTHETIC_KEY,
            )
            with self.assertRaisesRegex(
                EncryptedDatabaseUnlockError,
                "could not be unlocked",
            ):
                with wrong_database.connect(uuid4()):
                    pass

            self.assertEqual(
                [event.reason_code for event in audit_sink.events],
                [AuditReasonCode.NORMAL, AuditReasonCode.DATABASE_UNLOCK_FAILED],
            )
            audit_display = repr(audit_sink.events)
            self.assertNotIn(OTHER_SYNTHETIC_KEY.hex(), audit_display)
            self.assertNotIn(temporary_directory, audit_display)

    def test_standard_sqlite_cannot_read_the_encrypted_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.db"
            database, _, _ = self._database(path)
            with database.connect(uuid4()) as connection:
                connection.execute("CREATE TABLE sample (value INTEGER)")
                connection.commit()

            plaintext_connection = sqlite3.connect(path)
            try:
                with self.assertRaises(sqlite3.DatabaseError):
                    plaintext_connection.execute(
                        "SELECT count(*) FROM sqlite_master"
                    ).fetchone()
            finally:
                plaintext_connection.close()

    def test_plain_sqlite_driver_cannot_satisfy_encryption_requirement(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.db"
            database, _, audit_sink = self._database(path)

            with patch(
                "personal_assistant.encrypted_database.sqlcipher",
                sqlite3,
            ):
                with self.assertRaisesRegex(
                    EncryptionUnavailableError,
                    "did not enable encryption",
                ):
                    with database.connect(uuid4()):
                        pass

            self.assertEqual(
                audit_sink.events[-1].reason_code,
                AuditReasonCode.ENCRYPTION_UNAVAILABLE,
            )

    def test_unsafe_target_is_rejected_before_key_acquisition(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            target = directory / "target.db"
            target.write_bytes(b"unchanged")
            path = directory / "memory.db"
            try:
                path.symlink_to(target)
            except OSError:
                self.skipTest("symbolic links cannot be created")
            database, provider, audit_sink = self._database(path)

            with self.assertRaisesRegex(
                EncryptedDatabaseConfigurationError,
                "file is unsafe",
            ):
                with database.connect(uuid4()):
                    pass

            self.assertEqual(provider.requested_ids, [])
            self.assertEqual(target.read_bytes(), b"unchanged")
            self.assertEqual(
                audit_sink.events[-1].reason_code,
                AuditReasonCode.INVALID_CONFIGURATION,
            )

    def test_audit_failure_prevents_key_access_and_database_open(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.db"
            database, provider, _ = self._database(
                path,
                audit_sink=FailingAuditSink(),
            )

            with self.assertRaises(AuditWriteError):
                with database.connect(UUID(int=1)):
                    pass

            self.assertEqual(provider.requested_ids, [])
            self.assertFalse(path.exists())

    def test_configuration_failure_closes_connection_and_hides_raw_error(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "memory.db"
            database, _, audit_sink = self._database(path)

            with patch.object(
                database,
                "_restrict_file_permissions",
                side_effect=OSError("sensitive raw path"),
            ):
                with self.assertRaises(EncryptedDatabaseOpenError) as raised:
                    with database.connect(uuid4()):
                        pass

            self.assertNotIn("sensitive raw path", str(raised.exception))
            self.assertEqual(
                audit_sink.events[-1].reason_code,
                AuditReasonCode.SAFE_INTERNAL_FAILURE,
            )
