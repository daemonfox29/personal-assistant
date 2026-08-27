"""Synthetic recovery checks for encrypted backup and restore."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from personal_assistant.audit import (
    AuditOperation,
    AuditOutcome,
    AuditWriteError,
    InMemoryAuditSink,
)
from personal_assistant.authorization import ApprovalAuthority
from personal_assistant.backup import (
    BackupError,
    BackupIntegrityError,
    BackupSettings,
    BackupUnavailableError,
    EncryptedBackupManager,
    RestoreAuthorizationError,
    RestoreError,
)
from personal_assistant.encrypted_database import (
    EncryptedDatabase,
    EncryptedDatabaseSettings,
)
from personal_assistant.key_provider import DatabaseKey
from personal_assistant.migration import MigrationRunner, PackageMigrationSource
from personal_assistant.permissions import ActionKind


SYNTHETIC_KEY = bytes(range(32))


class SyntheticKeyProvider:
    def acquire(self, key_id: str) -> DatabaseKey:
        return DatabaseKey(SYNTHETIC_KEY)


class MutableClock:
    def __init__(self) -> None:
        self.value = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.value


class FailingSnapshotSuccessAuditSink:
    def write(self, event: object) -> None:
        if (
            getattr(event, "operation", None) is AuditOperation.BACKUP_CREATE
            and getattr(event, "outcome", None) is AuditOutcome.SUCCEEDED
        ):
            raise AuditWriteError("Audit event could not be recorded.")


class EncryptedBackupManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.root = Path(self.temporary_directory.name)
        self.live_path = self.root / "memory.db"
        self.destination = self.root / "backups"
        self.destination.mkdir()
        self.audit = InMemoryAuditSink()
        self.keys = SyntheticKeyProvider()
        self.source = PackageMigrationSource()
        self.clock = MutableClock()
        self.live = self._database(self.live_path)
        MigrationRunner(
            connection_provider=self.live,
            migration_source=self.source,
            audit_sink=self.audit,
        ).migrate(uuid4())

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _database(self, path: Path) -> EncryptedDatabase:
        return EncryptedDatabase(
            EncryptedDatabaseSettings(path, "synthetic-backup-key"),
            key_provider=self.keys,
            audit_sink=self.audit,
        )

    def _manager(self, *, retain_count: int = 7) -> EncryptedBackupManager:
        return EncryptedBackupManager(
            BackupSettings(
                self.live_path,
                self.destination,
                retain_count=retain_count,
                max_snapshot_bytes=32 * 1024 * 1024,
                max_total_bytes=64 * 1024 * 1024,
            ),
            live_database=self.live,
            database_factory=self._database,
            migration_source=self.source,
            audit_sink=self.audit,
            clock=self.clock,
        )

    def test_consistent_snapshot_is_encrypted_verified_and_daily_bounded(self) -> None:
        manager = self._manager()
        snapshot = manager.create_daily(uuid4())

        self.assertIsNotNone(snapshot)
        assert snapshot is not None
        self.assertNotEqual(snapshot.path.read_bytes()[:16], b"SQLite format 3\x00")
        self.assertEqual(len(snapshot.ciphertext_sha256), 64)
        metadata_path = snapshot.path.with_name(f"{snapshot.path.name}.meta.json")
        metadata = metadata_path.read_text(encoding="utf-8")
        self.assertIn(snapshot.ciphertext_sha256, metadata)
        self.assertNotIn("synthetic-only", metadata)
        self.assertIsNone(manager.create_daily(uuid4()))
        self.assertEqual(len(tuple(self.destination.glob("memory-*.db"))), 1)

    def test_success_audit_failure_does_not_publish_snapshot(self) -> None:
        manager = EncryptedBackupManager(
            BackupSettings(self.live_path, self.destination),
            live_database=self.live,
            database_factory=self._database,
            migration_source=self.source,
            audit_sink=FailingSnapshotSuccessAuditSink(),
            clock=self.clock,
        )

        with self.assertRaises(BackupError):
            manager.create_snapshot(uuid4())

        self.assertEqual(list(self.destination.iterdir()), [])

    def test_retention_removes_oldest_only_after_new_snapshot_verifies(self) -> None:
        manager = self._manager(retain_count=1)
        first = manager.create_snapshot(uuid4())
        self.clock.value = datetime(2026, 8, 26, 12, 0, tzinfo=timezone.utc)
        second = manager.create_snapshot(uuid4())

        self.assertFalse(first.path.exists())
        self.assertTrue(second.path.exists())
        self.assertEqual(tuple(self.destination.glob("memory-*.db")), (second.path,))

    def test_absent_destination_preserves_live_database(self) -> None:
        manager = self._manager()
        self.destination.rmdir()

        with self.assertRaises(BackupUnavailableError):
            manager.validate_destination()
        with self.assertRaises(BackupUnavailableError):
            manager.create_snapshot(uuid4())

        with self.live.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute("PRAGMA integrity_check").fetchone(), ("ok",)
            )

    def test_interrupted_write_preserves_existing_verified_snapshot(self) -> None:
        manager = self._manager()
        existing = manager.create_snapshot(uuid4())

        def fail_factory(path: Path) -> EncryptedDatabase:
            if path.name.endswith(".partial"):
                raise RuntimeError("synthetic interruption")
            return self._database(path)

        manager._database_factory = fail_factory
        with self.assertRaisesRegex(BackupError, "failed safely"):
            manager.create_snapshot(uuid4())

        self.assertTrue(existing.path.exists())
        self.assertEqual(tuple(self.destination.glob(".*.partial")), ())

    def test_corrupt_snapshot_cannot_produce_restore_plan(self) -> None:
        manager = self._manager()
        snapshot = manager.create_snapshot(uuid4())
        data = bytearray(snapshot.path.read_bytes())
        data[len(data) // 2 : len(data) // 2 + 128] = b"x" * 128
        snapshot.path.write_bytes(data)

        with self.assertRaises(BackupIntegrityError):
            manager.plan_restore(snapshot.path, uuid4())

    def test_snapshot_changed_after_approval_plan_is_rejected(self) -> None:
        manager = self._manager()
        snapshot = manager.create_snapshot(uuid4())
        plan = manager.plan_restore(snapshot.path, uuid4())
        snapshot.path.write_bytes(snapshot.path.read_bytes() + b"changed")
        authority = ApprovalAuthority()
        receipt = authority.issue(
            ActionKind.MEMORY_BACKUP_RESTORE,
            plan.approval_arguments,
        )

        with self.assertRaises(RestoreAuthorizationError):
            manager.restore(
                plan,
                uuid4(),
                approval_receipt=receipt,
                approval_authority=authority,
            )

    def test_missing_or_changed_integrity_metadata_blocks_restore(self) -> None:
        manager = self._manager()
        snapshot = manager.create_snapshot(uuid4())
        metadata = snapshot.path.with_name(f"{snapshot.path.name}.meta.json")
        metadata.write_text("{}", encoding="utf-8")

        with self.assertRaises(BackupIntegrityError):
            manager.plan_restore(snapshot.path, uuid4())

    def test_restore_requires_approval_and_reapplies_deletion_ledger(self) -> None:
        manager = self._manager()
        snapshot = manager.create_snapshot(uuid4())
        purged_id = str(uuid4())
        with self.live.connect(uuid4()) as connection:
            connection.execute(
                "INSERT INTO deletion_ledger (purged_id, purged_at, reason_code) "
                "VALUES (?, ?, ?)",
                (purged_id, "2026-08-25T12:00:00+00:00", "user_requested"),
            )
            connection.commit()

        plan = manager.plan_restore(snapshot.path, uuid4())
        authority = ApprovalAuthority()
        wrong = authority.issue(
            ActionKind.MEMORY_BACKUP_RESTORE,
            {**plan.approval_arguments, "snapshot_name": "different.db"},
        )
        with self.assertRaises(RestoreAuthorizationError):
            manager.restore(
                plan,
                uuid4(),
                approval_receipt=wrong,
                approval_authority=authority,
            )

        receipt = authority.issue(
            ActionKind.MEMORY_BACKUP_RESTORE,
            plan.approval_arguments,
        )
        manager.restore(
            plan,
            uuid4(),
            approval_receipt=receipt,
            approval_authority=authority,
        )
        with self.live.connect(uuid4()) as connection:
            row = connection.execute(
                "SELECT reason_code FROM deletion_ledger WHERE purged_id = ?",
                (purged_id,),
            ).fetchone()
        self.assertEqual(row, ("user_requested",))
        self.assertIn(
            AuditOutcome.SUCCEEDED,
            [event.outcome for event in self.audit.events],
        )

    def test_failed_final_verification_rolls_back_live_database(self) -> None:
        manager = self._manager(retain_count=1)
        snapshot = manager.create_snapshot(uuid4())
        current_id = str(uuid4())
        with self.live.connect(uuid4()) as connection:
            connection.execute(
                "INSERT INTO deletion_ledger (purged_id, purged_at, reason_code) "
                "VALUES (?, ?, ?)",
                (current_id, "2026-08-25T12:00:00+00:00", "user_requested"),
            )
            connection.commit()
        plan = manager.plan_restore(snapshot.path, uuid4())
        authority = ApprovalAuthority()
        receipt = authority.issue(
            ActionKind.MEMORY_BACKUP_RESTORE,
            plan.approval_arguments,
        )
        real_verify = manager._verify_database

        def fail_live_verification(
            provider: object, *args: object, **kwargs: object
        ) -> None:
            if provider is self.live:
                raise BackupIntegrityError("synthetic final verification failure")
            real_verify(provider, *args, **kwargs)  # type: ignore[arg-type]

        with patch.object(
            manager, "_verify_database", side_effect=fail_live_verification
        ):
            with self.assertRaises(RestoreError):
                manager.restore(
                    plan,
                    uuid4(),
                    approval_receipt=receipt,
                    approval_authority=authority,
                )

        with self.live.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT reason_code FROM deletion_ledger WHERE purged_id = ?",
                    (current_id,),
                ).fetchone(),
                ("user_requested",),
            )
        self.assertEqual(tuple(self.root.glob(".*restore*.db")), ())
        self.assertEqual(tuple(self.root.glob(".*rollback*.db")), ())
        self.assertEqual(tuple(self.root.glob(".*failed*.db")), ())


if __name__ == "__main__":
    unittest.main()
