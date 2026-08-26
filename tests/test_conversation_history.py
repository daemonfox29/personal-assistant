"""Checks for encrypted, bounded, durable conversation transcripts."""

from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from personal_assistant.audit import AuditWriteError, InMemoryAuditSink
from personal_assistant.conversation_history import (
    ConversationHistoryError,
    ConversationHistoryRepository,
    ConversationResponseMessage,
    ConversationRole,
)
from personal_assistant.encrypted_database import (
    EncryptedDatabase,
    EncryptedDatabaseSettings,
)
from personal_assistant.key_provider import DatabaseKey
from personal_assistant.migration import MigrationRunner, PackageMigrationSource


SYNTHETIC_KEY = bytes(range(32))
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class SyntheticKeyProvider:
    def acquire(self, key_id: str) -> DatabaseKey:
        return DatabaseKey(SYNTHETIC_KEY)


class FailingAuditSink:
    def write(self, event: object) -> None:
        raise AuditWriteError("synthetic audit failure")


class ConversationHistoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = TemporaryDirectory()
        self.path = Path(self.temporary.name) / "memory.db"
        self.audit = InMemoryAuditSink()
        self.database = EncryptedDatabase(
            EncryptedDatabaseSettings(self.path, "synthetic-history-key"),
            key_provider=SyntheticKeyProvider(),
            audit_sink=self.audit,
        )
        MigrationRunner(
            connection_provider=self.database,
            migration_source=PackageMigrationSource(),
            audit_sink=self.audit,
        ).migrate(uuid4())
        self.repository = ConversationHistoryRepository(
            self.database,
            self.audit,
            clock=lambda: NOW,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_turn_is_durable_and_reopens_as_model_context(self) -> None:
        conversation_id = self.repository.begin_turn(
            None,
            "Tell me about Luna",
            uuid4(),
        )
        self.repository.finish_turn(
            conversation_id,
            (
                ConversationResponseMessage(
                    ConversationRole.NOTICE,
                    "Synthetic notice",
                ),
                ConversationResponseMessage(
                    ConversationRole.ASSISTANT,
                    "Luna is your pet.",
                ),
            ),
            uuid4(),
        )

        reopened = self.repository.load_conversation(conversation_id, uuid4())

        self.assertEqual(
            [message.role for message in reopened.messages],
            [
                ConversationRole.USER,
                ConversationRole.NOTICE,
                ConversationRole.ASSISTANT,
            ],
        )
        self.assertEqual(reopened.completed_turns()[0].user_text, "Tell me about Luna")
        self.assertEqual(
            self.repository.list_conversations(uuid4())[0].conversation_id,
            conversation_id,
        )
        self.assertNotEqual(self.path.read_bytes()[:16], b"SQLite format 3\x00")

    def test_unanswered_user_message_remains_visible_but_not_model_context(self) -> None:
        conversation_id = self.repository.begin_turn(
            None,
            "A prompt saved before generation",
            uuid4(),
        )

        reopened = self.repository.load_conversation(conversation_id, uuid4())

        self.assertEqual(len(reopened.messages), 1)
        self.assertEqual(reopened.completed_turns(), ())

    def test_delete_cascades_messages(self) -> None:
        conversation_id = self.repository.begin_turn(None, "Delete me", uuid4())

        self.repository.delete_conversation(conversation_id, uuid4())

        self.assertEqual(self.repository.list_conversations(uuid4()), ())
        with self.database.connect(uuid4()) as connection:
            count = connection.execute(
                "SELECT count(*) FROM conversation_messages"
            ).fetchone()[0]
        self.assertEqual(count, 0)

    def test_audit_failure_prevents_a_write(self) -> None:
        repository = ConversationHistoryRepository(
            self.database,
            FailingAuditSink(),
            clock=lambda: NOW,
        )

        with self.assertRaises(ConversationHistoryError):
            repository.begin_turn(None, "Do not persist", uuid4())

        with self.database.connect(uuid4()) as connection:
            count = connection.execute(
                "SELECT count(*) FROM conversations"
            ).fetchone()[0]
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
