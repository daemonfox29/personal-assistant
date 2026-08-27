"""Checks for encrypted, revisioned assistant communication preferences."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from personal_assistant.assistant_preferences import (
    AssistantPreferenceError,
    CommunicationStyle,
    EncryptedAssistantPreferenceStore,
)
from personal_assistant.audit import (
    AuditWriteError,
    InMemoryAuditSink,
)
from personal_assistant.encrypted_database import (
    EncryptedDatabase,
    EncryptedDatabaseSettings,
)
from personal_assistant.key_provider import DatabaseKey
from personal_assistant.migration import MigrationRunner, PackageMigrationSource


SYNTHETIC_KEY = bytes(range(32))


class SyntheticKeyProvider:
    def acquire(self, key_id: str) -> DatabaseKey:
        return DatabaseKey(SYNTHETIC_KEY)


class FailingAuditSink:
    def write(self, event: object) -> None:
        raise AuditWriteError("synthetic audit failure")


class AssistantPreferenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.audit = InMemoryAuditSink()
        self.database = EncryptedDatabase(
            EncryptedDatabaseSettings(
                Path(self.temporary.name) / "memory.db",
                "synthetic-assistant-preferences",
            ),
            key_provider=SyntheticKeyProvider(),
            audit_sink=self.audit,
        )
        MigrationRunner(
            connection_provider=self.database,
            migration_source=PackageMigrationSource(),
            audit_sink=self.audit,
        ).migrate(uuid4())
        self.store = EncryptedAssistantPreferenceStore(
            self.database,
            self.audit,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_style_defaults_empty_then_appends_encrypted_revisions(self) -> None:
        self.assertEqual(
            self.store.load_communication_style(uuid4()),
            CommunicationStyle(),
        )

        self.store.save_communication_style(
            CommunicationStyle("Be warm and concise."),
            uuid4(),
        )
        self.store.save_communication_style(
            CommunicationStyle("Use plain language and short paragraphs."),
            uuid4(),
        )

        self.assertEqual(
            self.store.load_communication_style(uuid4()).text,
            "Use plain language and short paragraphs.",
        )
        self.store.save_communication_style(CommunicationStyle(), uuid4())
        self.assertEqual(
            self.store.load_communication_style(uuid4()),
            CommunicationStyle(),
        )
        with self.database.connect(uuid4()) as connection:
            revisions = connection.execute(
                "SELECT revision FROM assistant_preference_revisions "
                "ORDER BY revision"
            ).fetchall()
        self.assertEqual(revisions, [(1,), (2,), (3,)])
        self.assertNotIn("plain language", repr(self.audit.events))

    def test_invalid_or_credential_style_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CommunicationStyle("x" * 2_001)
        with self.assertRaises(ValueError):
            CommunicationStyle("My password is synthetic-secret")

    def test_audit_failure_prevents_style_write(self) -> None:
        failing = EncryptedAssistantPreferenceStore(
            self.database,
            FailingAuditSink(),  # type: ignore[arg-type]
        )

        with self.assertRaises(AssistantPreferenceError):
            failing.save_communication_style(
                CommunicationStyle("Do not persist this style."),
                uuid4(),
            )

        with self.database.connect(uuid4()) as connection:
            count = connection.execute(
                "SELECT count(*) FROM assistant_preference_revisions"
            ).fetchone()[0]
        self.assertEqual(count, 0)
