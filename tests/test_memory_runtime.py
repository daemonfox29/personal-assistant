"""End-to-end synthetic checks for the unlocked memory runtime."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from personal_assistant.audit import InMemoryAuditSink
from personal_assistant.config import MemorySettings
from personal_assistant.migration import MigrationApplyError
from personal_assistant.memory_runtime import MemoryRuntime
from personal_assistant.memory_capture import AutomaticMemorySuggestion
from personal_assistant.memory_repository import RetrievalRequest
from personal_assistant.memory_types import (
    FactPayload,
    MentionPolicy,
    Scope,
    ScopeType,
    Sensitivity,
)
from personal_assistant.portable_security import PasscodeVerificationError
from personal_assistant.portable_security import (
    PortableSecurityManager,
    PortableSecuritySettings,
)


RECOVERY = "synthetic runtime recovery phrase"
PASSCODE = "synthetic-runtime-passcode"


class MemoryRuntimeTests(unittest.TestCase):
    def test_normal_open_never_creates_a_missing_database(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            data = Path(temporary_directory) / "data"
            audit = InMemoryAuditSink()
            security = PortableSecurityManager(
                PortableSecuritySettings(data / "security.json"),
                audit_sink=audit,
            )
            security.setup(
                RECOVERY,
                RECOVERY,
                PASSCODE,
                PASSCODE,
                uuid4(),
            )
            database = data / "memory.db"

            with self.assertRaises(MigrationApplyError):
                MemoryRuntime.open(
                    MemorySettings(data_directory=data),
                    RECOVERY,
                    audit_sink=audit,
                )

            self.assertFalse(database.exists())

    def test_setup_runtime_remember_restart_recall_backup_and_restore(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            data = root / "data"
            backups = root / "backups"
            backups.mkdir()
            audit = InMemoryAuditSink()
            security = PortableSecurityManager(
                PortableSecuritySettings(data / "security.json"),
                audit_sink=audit,
            )
            security.setup(
                RECOVERY,
                RECOVERY,
                PASSCODE,
                PASSCODE,
                uuid4(),
            )
            settings = MemorySettings(
                data_directory=data,
                backup_directory=backups,
                automatic_suggestions=False,
            )

            first = MemoryRuntime.open(
                settings,
                RECOVERY,
                audit_sink=audit,
                create_database=True,
            )
            outcome = first.remember("Luna likes synthetic rope toys", uuid4())
            snapshot = first.create_daily_backup(uuid4())
            first.close()

            self.assertEqual(outcome, "I saved that as confirmed memory.")
            self.assertIsNotNone(snapshot)
            second = MemoryRuntime.open(settings, RECOVERY, audit_sink=audit)
            context = second.context_provider.context_for(
                "What toys does Luna like?", uuid4()
            )
            self.assertIsNotNone(context)
            assert context is not None
            self.assertIn("synthetic rope toys", context)
            assert snapshot is not None
            second.restore_backup(snapshot.path, PASSCODE, uuid4())
            second.close()

    def test_explicit_sensitive_or_credential_content_is_not_stored(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            data = Path(temporary_directory) / "data"
            audit = InMemoryAuditSink()
            security = PortableSecurityManager(
                PortableSecuritySettings(data / "security.json"),
                audit_sink=audit,
            )
            security.setup(
                RECOVERY,
                RECOVERY,
                PASSCODE,
                PASSCODE,
                uuid4(),
            )
            runtime = MemoryRuntime.open(
                MemorySettings(data_directory=data, automatic_suggestions=False),
                RECOVERY,
                audit_sink=audit,
                create_database=True,
            )

            sensitive = runtime.remember("My childhood trauma detail", uuid4())
            prohibited = runtime.remember("My password is synthetic", uuid4())
            runtime.close()

            self.assertEqual(
                sensitive,
                "That memory needs higher-risk review and was not saved.",
            )
            self.assertEqual(
                prohibited,
                "That information cannot be stored under the memory safety rules.",
            )

    def test_candidate_review_and_sensitive_passcode(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            data = Path(temporary_directory) / "data"
            audit = InMemoryAuditSink()
            security = PortableSecurityManager(
                PortableSecuritySettings(data / "security.json"),
                audit_sink=audit,
            )
            security.setup(
                RECOVERY,
                RECOVERY,
                PASSCODE,
                PASSCODE,
                uuid4(),
            )
            runtime = MemoryRuntime.open(
                MemorySettings(data_directory=data),
                RECOVERY,
                audit_sink=audit,
                create_database=True,
            )
            normal = runtime.capture.suggest_automatically(
                self._suggestion(
                    "Luna normal synthetic preference",
                    Sensitivity.NORMAL,
                    "turn:33333333-3333-3333-3333-333333333333",
                ),
                uuid4(),
            ).record
            sensitive = runtime.capture.suggest_automatically(
                self._suggestion(
                    "Luna health synthetic note",
                    Sensitivity.SENSITIVE,
                    "turn:44444444-4444-4444-4444-444444444444",
                ),
                uuid4(),
            ).record
            assert normal is not None and sensitive is not None

            inbox = runtime.repository.list_candidates(uuid4())
            self.assertEqual({item.record_id for item in inbox}, {
                normal.record_id,
                sensitive.record_id,
            })
            runtime.confirm_candidate(normal.record_id, uuid4())
            with self.assertRaises(PasscodeVerificationError):
                runtime.confirm_candidate(
                    sensitive.record_id,
                    uuid4(),
                    high_risk_passcode="incorrect-passcode",
                )
            runtime.confirm_candidate(
                sensitive.record_id,
                uuid4(),
                high_risk_passcode=PASSCODE,
            )
            recalled = runtime.repository.retrieve(
                RetrievalRequest("Luna normal preference"), uuid4()
            )
            self.assertEqual(
                recalled.receipt.selected_record_ids,
                (normal.record_id,),
            )
            runtime.close()

    @staticmethod
    def _suggestion(
        statement: str,
        sensitivity: Sensitivity,
        source_ref: str,
    ) -> AutomaticMemorySuggestion:
        return AutomaticMemorySuggestion(
            FactPayload(statement, statement),
            sensitivity,
            MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
            Scope(ScopeType.GLOBAL),
            source_ref,
            "synthetic-model-v1",
        )


if __name__ == "__main__":
    unittest.main()
