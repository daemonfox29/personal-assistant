"""Synthetic encrypted-database tests for typed memory repository behavior."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

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
from personal_assistant.memory_repository import (
    LifecycleTransitionError,
    MemoryRepository,
    RecordNotFoundError,
    RepositoryConflictError,
    RepositoryIntegrityError,
    RepositoryOperationError,
)
from personal_assistant.memory_types import (
    ActorType,
    AliasDraft,
    AliasSourceType,
    ConfidenceBasis,
    EntityDraft,
    EntityLinkDraft,
    EntityRelationship,
    EntityStatus,
    EntityType,
    EventPayload,
    FactPayload,
    InsightConfidence,
    InsightPayload,
    LinkSourceType,
    MemoryValidationError,
    MentionPolicy,
    NotePayload,
    PreferencePayload,
    Provenance,
    PurgeReason,
    RecordDraft,
    RecordLinkDraft,
    RecordRelationship,
    RecordStatus,
    Scope,
    ScopeType,
    Sensitivity,
    SourceType,
)
from personal_assistant.migration import MigrationRunner, PackageMigrationSource


SYNTHETIC_KEY = bytes(range(32))
NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


class SyntheticKeyProvider:
    def acquire(self, key_id: str) -> DatabaseKey:
        return DatabaseKey(SYNTHETIC_KEY)


class FailingAuditSink:
    def write(self, event: object) -> None:
        raise AuditWriteError("Audit event could not be recorded.")


class FailingSecondAuditSink:
    def __init__(self) -> None:
        self.calls = 0

    def write(self, event: object) -> None:
        self.calls += 1
        if self.calls == 2:
            raise AuditWriteError("Audit event could not be recorded.")


class MemoryRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = TemporaryDirectory()
        self.path = Path(self._temporary_directory.name) / "memory.db"
        self.audit_sink = InMemoryAuditSink()
        self.database = EncryptedDatabase(
            EncryptedDatabaseSettings(self.path, "synthetic-repository-key"),
            key_provider=SyntheticKeyProvider(),
            audit_sink=self.audit_sink,
        )
        MigrationRunner(
            connection_provider=self.database,
            migration_source=PackageMigrationSource(),
            audit_sink=self.audit_sink,
        ).migrate(uuid4())
        self.repository = MemoryRepository(
            connection_provider=self.database,
            audit_sink=self.audit_sink,
            clock=lambda: NOW,
        )

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    @staticmethod
    def _explicit() -> Provenance:
        return Provenance(
            SourceType.EXPLICIT_USER,
            "synthetic-user-turn",
            ActorType.USER,
        )

    @staticmethod
    def _trusted() -> Provenance:
        return Provenance(
            SourceType.TRUSTED_INTERFACE,
            "synthetic-interface",
            ActorType.USER,
        )

    @staticmethod
    def _model() -> Provenance:
        return Provenance(
            SourceType.MODEL_CANDIDATE,
            "synthetic-model-turn",
            ActorType.MODEL_CANDIDATE,
            "synthetic-model-v1",
        )

    @staticmethod
    def _draft(
        payload: object,
        *,
        status: RecordStatus = RecordStatus.CONFIRMED,
        sensitivity: Sensitivity = Sensitivity.NORMAL,
        mention_policy: MentionPolicy = MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
        scope: Scope = Scope(ScopeType.GLOBAL),
        primary_entity_id=None,  # type: ignore[no-untyped-def]
    ) -> RecordDraft:
        return RecordDraft(
            payload,  # type: ignore[arg-type]
            status,
            sensitivity,
            mention_policy,
            scope,
            primary_entity_id,
        )

    def _fact(self, statement: str = "synthetic statement") -> RecordDraft:
        return self._draft(FactPayload("synthetic subject", statement))

    def test_explicit_record_is_parameterized_encrypted_and_revisioned(self) -> None:
        content = "synthetic'); DROP TABLE records; --"
        record = self.repository.create_record(
            self._fact(content),
            self._explicit(),
            uuid4(),
        )

        inspected = self.repository.inspect_record(record.record_id, uuid4())
        history = self.repository.get_record_history(record.record_id, uuid4())
        self.assertEqual(inspected.revision.payload.statement, content)
        self.assertEqual(inspected.status, RecordStatus.CONFIRMED)
        self.assertEqual(inspected.row_version, 1)
        self.assertEqual(len(history), 1)
        self.assertIsNone(history[0].previous_hash)
        self.assertNotEqual(self.path.read_bytes()[:16], b"SQLite format 3\x00")
        with self.database.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM records").fetchone()[0],
                1,
            )

    def test_success_audit_failure_rolls_back_repository_write(self) -> None:
        repository = MemoryRepository(
            connection_provider=self.database,
            audit_sink=FailingSecondAuditSink(),
            clock=lambda: NOW,
        )
        with self.assertRaises(RepositoryOperationError):
            repository.create_record(self._fact(), self._explicit(), uuid4())

        with self.database.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM records").fetchone()[0],
                0,
            )

    def test_model_output_can_create_only_expiring_candidates(self) -> None:
        candidate = self.repository.create_record(
            self._draft(
                PreferencePayload("synthetic topic", "synthetic preference"),
                status=RecordStatus.CANDIDATE,
            ),
            self._model(),
            uuid4(),
        )
        self.assertEqual(candidate.status, RecordStatus.CANDIDATE)
        self.assertEqual(candidate.candidate_expires_at, NOW + timedelta(days=30))

        confirmed = self.repository.confirm_candidate(
            candidate.record_id,
            candidate.row_version,
            self._explicit(),
            uuid4(),
        )
        self.assertEqual(confirmed.status, RecordStatus.CONFIRMED)
        self.assertIsNone(confirmed.candidate_expires_at)
        self.assertEqual(confirmed.current_revision, 2)
        with self.database.connect(uuid4()) as connection:
            feedback = connection.execute(
                "SELECT feedback_type FROM memory_feedback WHERE record_id = ?",
                (str(candidate.record_id),),
            ).fetchall()
        self.assertEqual(feedback, [("confirm",)])

        with self.assertRaisesRegex(MemoryValidationError, "candidates only"):
            self.repository.create_record(self._fact(), self._model(), uuid4())

    def test_named_scopes_persist_and_match_only_complete_query_phrases(self) -> None:
        first = self.repository.resolve_named_scope(
            ScopeType.PROJECT,
            "Apollo",
            uuid4(),
        )
        repeated = self.repository.resolve_named_scope(
            ScopeType.PROJECT,
            "apollo",
            uuid4(),
        )

        self.assertEqual(first, repeated)
        self.assertEqual(
            self.repository.match_named_scopes(
                "What did we decide for Apollo?",
                uuid4(),
            ),
            (first,),
        )
        self.assertEqual(
            self.repository.match_named_scopes("Apollonia", uuid4()),
            (),
        )
        work = self.repository.resolve_named_scope(
            ScopeType.PLACE,
            "work",
            uuid4(),
        )
        self.assertEqual(
            self.repository.match_named_scopes("How does this work?", uuid4()),
            (),
        )
        self.assertEqual(
            self.repository.match_named_scopes("What do I prefer at work?", uuid4()),
            (work,),
        )

    def test_record_inventory_cursor_pages_without_overlap(self) -> None:
        created = tuple(
            self.repository.create_record(
                self._fact(f"synthetic page statement {index}"),
                self._explicit(),
                uuid4(),
            )
            for index in range(3)
        )

        first = self.repository.list_record_page(uuid4(), limit=2)
        second = self.repository.list_record_page(
            uuid4(),
            limit=2,
            before_updated_at=first.next_updated_at,
            before_record_id=first.next_record_id,
        )

        self.assertEqual(len(first.records), 2)
        self.assertEqual(len(second.records), 1)
        self.assertIsNone(second.next_record_id)
        self.assertEqual(
            {record.record_id for record in first.records + second.records},
            {record.record_id for record in created},
        )

    def test_model_candidate_cannot_revise_confirmed_memory(self) -> None:
        record = self.repository.create_record(
            self._fact(), self._explicit(), uuid4()
        )

        with self.assertRaisesRegex(LifecycleTransitionError, "cannot revise"):
            self.repository.revise_record(
                record.record_id,
                record.row_version,
                FactPayload("synthetic subject", "synthetic model rewrite"),
                self._model(),
                uuid4(),
            )

        self.assertEqual(
            self.repository.inspect_record(record.record_id, uuid4()).row_version,
            1,
        )

    def test_correction_appends_hash_chained_revision_and_rejects_stale_write(self) -> None:
        original = self.repository.create_record(
            self._fact(), self._explicit(), uuid4()
        )
        corrected = self.repository.revise_record(
            original.record_id,
            original.row_version,
            FactPayload("synthetic subject", "corrected synthetic statement"),
            self._explicit(),
            uuid4(),
        )

        history = self.repository.get_record_history(original.record_id, uuid4())
        self.assertEqual(corrected.row_version, 2)
        self.assertEqual(len(history), 2)
        self.assertEqual(history[1].previous_hash, history[0].content_hash)
        self.assertNotEqual(history[1].content_hash, history[0].content_hash)

        with self.assertRaises(RepositoryConflictError):
            self.repository.revise_record(
                original.record_id,
                1,
                FactPayload("synthetic subject", "stale synthetic change"),
                self._explicit(),
                uuid4(),
            )
        self.assertEqual(
            len(self.repository.get_record_history(original.record_id, uuid4())),
            2,
        )
        self.assertEqual(
            [
                event.reason_code
                for event in self.audit_sink.events
                if event.operation is AuditOperation.REPOSITORY_WRITE
                and event.outcome is AuditOutcome.FAILED
            ][-1],
            AuditReasonCode.VERSION_CONFLICT,
        )

    def test_controls_and_lifecycle_changes_are_revisioned(self) -> None:
        record = self.repository.create_record(
            self._fact(), self._explicit(), uuid4()
        )
        controlled = self.repository.update_record_controls(
            record.record_id,
            record.row_version,
            sensitivity=Sensitivity.RESTRICTED,
            mention_policy=MentionPolicy.ONLY_WHEN_DIRECTLY_ASKED,
            scope=Scope(ScopeType.TOPIC, uuid4()),
            provenance=self._trusted(),
            correlation_id=uuid4(),
        )
        archived = self.repository.archive_record(
            record.record_id,
            controlled.row_version,
            self._trusted(),
            uuid4(),
        )
        restored = self.repository.restore_record(
            record.record_id,
            archived.row_version,
            self._explicit(),
            uuid4(),
        )
        deleted = self.repository.delete_record(
            record.record_id,
            restored.row_version,
            self._explicit(),
            uuid4(),
        )

        self.assertEqual(controlled.sensitivity, Sensitivity.RESTRICTED)
        self.assertEqual(archived.status, RecordStatus.ARCHIVED)
        self.assertEqual(restored.status, RecordStatus.CONFIRMED)
        self.assertEqual(deleted.status, RecordStatus.DELETED)
        history = self.repository.get_record_history(record.record_id, uuid4())
        self.assertEqual(len(history), 5)
        self.assertEqual(
            [revision.status for revision in history],
            [
                RecordStatus.CONFIRMED,
                RecordStatus.CONFIRMED,
                RecordStatus.ARCHIVED,
                RecordStatus.CONFIRMED,
                RecordStatus.DELETED,
            ],
        )

        with self.assertRaises(LifecycleTransitionError):
            self.repository.archive_record(
                record.record_id,
                deleted.row_version,
                self._trusted(),
                uuid4(),
            )

    def test_rejected_candidate_is_soft_deleted_and_recoverable(self) -> None:
        candidate = self.repository.create_record(
            self._draft(
                NotePayload("synthetic", "synthetic candidate"),
                status=RecordStatus.CANDIDATE,
            ),
            self._model(),
            uuid4(),
        )
        rejected = self.repository.reject_candidate(
            candidate.record_id,
            candidate.row_version,
            self._explicit(),
            uuid4(),
        )
        restored = self.repository.restore_record(
            candidate.record_id,
            rejected.row_version,
            self._explicit(),
            uuid4(),
        )

        self.assertEqual(rejected.status, RecordStatus.DELETED)
        self.assertEqual(restored.status, RecordStatus.CONFIRMED)
        self.assertEqual(len(self.repository.get_record_history(candidate.record_id, uuid4())), 3)

    def test_candidate_expiry_is_bounded_and_preserves_history(self) -> None:
        candidate = self.repository.create_record(
            self._draft(
                NotePayload("synthetic", "synthetic expiring candidate"),
                status=RecordStatus.CANDIDATE,
            ),
            self._model(),
            uuid4(),
        )
        later_repository = MemoryRepository(
            connection_provider=self.database,
            audit_sink=self.audit_sink,
            clock=lambda: NOW + timedelta(days=31),
        )

        expired = later_repository.expire_candidates(uuid4(), limit=1)
        archived = later_repository.inspect_record(candidate.record_id, uuid4())

        self.assertEqual(expired, (candidate.record_id,))
        self.assertEqual(archived.status, RecordStatus.ARCHIVED)
        self.assertIsNone(archived.candidate_expires_at)
        self.assertEqual(
            len(later_repository.get_record_history(candidate.record_id, uuid4())),
            2,
        )
        self.assertEqual(later_repository.expire_candidates(uuid4(), limit=1), ())
        with self.assertRaises(MemoryValidationError):
            later_repository.expire_candidates(uuid4(), limit=101)

    def test_supersession_is_atomic_and_links_replacement(self) -> None:
        original = self.repository.create_record(
            self._fact(), self._explicit(), uuid4()
        )
        old, replacement, link = self.repository.supersede_record(
            original.record_id,
            original.row_version,
            self._fact("new synthetic state"),
            self._explicit(),
            uuid4(),
        )

        self.assertEqual(old.status, RecordStatus.SUPERSEDED)
        self.assertEqual(replacement.status, RecordStatus.CONFIRMED)
        self.assertEqual(link.source_record_id, old.record_id)
        self.assertEqual(link.target_record_id, replacement.record_id)
        self.assertEqual(link.relationship, RecordRelationship.SUPERSESSION)
        with self.assertRaises(LifecycleTransitionError):
            self.repository.revise_record(
                old.record_id,
                old.row_version,
                FactPayload("synthetic subject", "invalid old edit"),
                self._explicit(),
                uuid4(),
            )

    def test_candidate_correction_is_atomic_and_preserves_both_histories(self) -> None:
        target = self.repository.create_record(
            self._fact("old synthetic state"),
            self._explicit(),
            uuid4(),
        )
        candidate = self.repository.create_record(
            self._draft(
                FactPayload("synthetic subject", "corrected synthetic state"),
                status=RecordStatus.CANDIDATE,
            ),
            self._model(),
            uuid4(),
        )

        consumed, corrected, link = self.repository.reconcile_candidate_as_correction(
            candidate.record_id,
            candidate.row_version,
            target.record_id,
            target.row_version,
            self._trusted(),
            uuid4(),
        )

        self.assertEqual(consumed.status, RecordStatus.SUPERSEDED)
        self.assertEqual(corrected.status, RecordStatus.CONFIRMED)
        self.assertEqual(
            corrected.revision.payload.statement,  # type: ignore[union-attr]
            "corrected synthetic state",
        )
        self.assertEqual(link.relationship, RecordRelationship.EVIDENCE)
        self.assertEqual(
            len(self.repository.get_record_history(target.record_id, uuid4())),
            2,
        )
        self.assertEqual(
            len(self.repository.get_record_history(candidate.record_id, uuid4())),
            2,
        )

    def test_candidate_successor_records_effective_date_without_overwrite(self) -> None:
        target = self.repository.create_record(
            self._fact("prior synthetic state"),
            self._explicit(),
            uuid4(),
        )
        candidate = self.repository.create_record(
            self._draft(
                FactPayload("synthetic subject", "new synthetic state"),
                status=RecordStatus.CANDIDATE,
            ),
            self._model(),
            uuid4(),
        )
        effective_at = NOW + timedelta(days=2)

        ended, successor, link = self.repository.reconcile_candidate_as_successor(
            candidate.record_id,
            candidate.row_version,
            target.record_id,
            target.row_version,
            effective_at,
            self._trusted(),
            uuid4(),
        )

        self.assertEqual(ended.status, RecordStatus.CONFIRMED)
        self.assertEqual(ended.valid_until, effective_at)
        self.assertEqual(successor.status, RecordStatus.CONFIRMED)
        self.assertEqual(successor.valid_from, effective_at)
        self.assertIsNone(successor.candidate_expires_at)
        self.assertEqual(link.relationship, RecordRelationship.SUPERSESSION)

    def test_entities_preserve_ambiguity_and_support_typed_links(self) -> None:
        first = self.repository.create_entity(EntityDraft(EntityType.PET), uuid4())
        second = self.repository.create_entity(EntityDraft(EntityType.PET), uuid4())
        alias_draft = AliasDraft(
            "Synthetic Pet",
            AliasSourceType.EXPLICIT_USER,
            "synthetic-user-turn",
            ConfidenceBasis.EXPLICIT,
        )
        self.repository.add_entity_alias(first.entity_id, alias_draft, uuid4())
        self.repository.add_entity_alias(second.entity_id, alias_draft, uuid4())

        matches = self.repository.find_entities_by_alias(" synthetic   pet ", uuid4())
        self.assertEqual(
            {entity.entity_id for entity in matches},
            {first.entity_id, second.entity_id},
        )
        with self.assertRaises(RepositoryConflictError):
            self.repository.add_entity_alias(first.entity_id, alias_draft, uuid4())

        link = self.repository.create_entity_link(
            EntityLinkDraft(
                first.entity_id,
                second.entity_id,
                EntityRelationship.RELATED,
                LinkSourceType.EXPLICIT_USER,
                "synthetic-user-turn",
            ),
            uuid4(),
        )
        self.assertEqual(link.target_entity_id, second.entity_id)

        associated = self.repository.create_record(
            self._draft(
                FactPayload("synthetic pet", "synthetic species"),
                primary_entity_id=first.entity_id,
            ),
            self._explicit(),
            uuid4(),
        )
        self.assertEqual(associated.primary_entity_id, first.entity_id)

        archived = self.repository.archive_entity(
            first.entity_id,
            first.row_version,
            uuid4(),
        )
        self.assertEqual(archived.status, EntityStatus.ARCHIVED)
        with self.assertRaises(LifecycleTransitionError):
            self.repository.add_entity_alias(first.entity_id, AliasDraft(
                "Another Synthetic Alias",
                AliasSourceType.EXPLICIT_USER,
                "synthetic-user-turn",
                ConfidenceBasis.EXPLICIT,
            ), uuid4())

    def test_insight_requires_three_distinct_evidence_records(self) -> None:
        insight = self.repository.create_record(
            self._draft(
                InsightPayload(
                    "synthetic pattern",
                    InsightConfidence.LOW,
                    "synthetic contradictions considered",
                    NOW,
                    NOW,
                ),
                status=RecordStatus.CANDIDATE,
            ),
            self._model(),
            uuid4(),
        )
        evidence = [
            self.repository.create_record(
                self._draft(EventPayload(f"synthetic event {index}", NOW)),
                self._explicit(),
                uuid4(),
            )
            for index in range(3)
        ]
        for event in evidence[:2]:
            self.repository.create_record_link(
                RecordLinkDraft(
                    insight.record_id,
                    event.record_id,
                    RecordRelationship.EVIDENCE,
                    LinkSourceType.MODEL_CANDIDATE,
                    "synthetic-model-turn",
                ),
                uuid4(),
            )

        with self.assertRaisesRegex(LifecycleTransitionError, "three evidence"):
            self.repository.confirm_candidate(
                insight.record_id,
                insight.row_version,
                self._explicit(),
                uuid4(),
            )

        self.repository.create_record_link(
            RecordLinkDraft(
                insight.record_id,
                evidence[2].record_id,
                RecordRelationship.EVIDENCE,
                LinkSourceType.MODEL_CANDIDATE,
                "synthetic-model-turn",
            ),
            uuid4(),
        )
        confirmed = self.repository.confirm_candidate(
            insight.record_id,
            insight.row_version,
            self._explicit(),
            uuid4(),
        )
        self.assertEqual(confirmed.status, RecordStatus.CONFIRMED)

        with self.assertRaisesRegex(MemoryValidationError, "begin as candidates"):
            self.repository.create_record(
                self._draft(
                    InsightPayload(
                        "another synthetic pattern",
                        InsightConfidence.LOW,
                        "synthetic contradictions considered",
                        NOW,
                        NOW,
                    )
                ),
                self._explicit(),
                uuid4(),
            )

    def test_model_suggested_aliases_and_entity_links_are_quarantined(self) -> None:
        first = self.repository.create_entity(EntityDraft(EntityType.PET), uuid4())
        second = self.repository.create_entity(EntityDraft(EntityType.PET), uuid4())

        with self.assertRaisesRegex(MemoryValidationError, "review workflow"):
            self.repository.add_entity_alias(
                first.entity_id,
                AliasDraft(
                    "Synthetic Model Alias",
                    AliasSourceType.MODEL_CANDIDATE,
                    "synthetic-model-turn",
                    ConfidenceBasis.CANDIDATE,
                ),
                uuid4(),
            )
        with self.assertRaisesRegex(MemoryValidationError, "review workflow"):
            self.repository.create_entity_link(
                EntityLinkDraft(
                    first.entity_id,
                    second.entity_id,
                    EntityRelationship.RELATED,
                    LinkSourceType.MODEL_CANDIDATE,
                    "synthetic-model-turn",
                ),
                uuid4(),
            )

    def test_purge_removes_content_and_permanently_suppresses_the_id(self) -> None:
        record = self.repository.create_record(
            self._fact(), self._explicit(), uuid4()
        )
        self.repository.revise_record(
            record.record_id,
            record.row_version,
            FactPayload("synthetic subject", "synthetic revision"),
            self._explicit(),
            uuid4(),
        )
        entry = self.repository.purge_record(
            record.record_id,
            2,
            PurgeReason.USER_REQUESTED,
            uuid4(),
        )

        self.assertEqual(entry.purged_id, record.record_id)
        self.assertTrue(self.repository.is_purged(record.record_id, uuid4()))
        with self.assertRaises(RecordNotFoundError):
            self.repository.inspect_record(record.record_id, uuid4())
        with self.database.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM record_revisions WHERE record_id = ?",
                    (str(record.record_id),),
                ).fetchone()[0],
                0,
            )

        collision_repository = MemoryRepository(
            connection_provider=self.database,
            audit_sink=self.audit_sink,
            clock=lambda: NOW,
            id_factory=lambda: record.record_id,
        )
        with self.assertRaisesRegex(RepositoryConflictError, "permanently purged"):
            collision_repository.create_record(
                self._fact("synthetic restored content"),
                self._explicit(),
                uuid4(),
            )

    def test_tampered_revision_is_detected_without_exposing_content(self) -> None:
        marker = "synthetic-sensitive-marker"
        record = self.repository.create_record(
            self._fact(marker), self._explicit(), uuid4()
        )
        with self.database.connect(uuid4()) as connection:
            connection.execute(
                "UPDATE record_revisions SET payload_json = ? "
                "WHERE record_id = ? AND revision = 1",
                ('{"schema_version":1}', str(record.record_id)),
            )
            connection.commit()

        with self.assertRaises(RepositoryIntegrityError) as raised:
            self.repository.inspect_record(record.record_id, uuid4())
        self.assertNotIn(marker, str(raised.exception))
        self.assertEqual(
            [
                event.reason_code
                for event in self.audit_sink.events
                if event.operation is AuditOperation.REPOSITORY_READ
                and event.outcome is AuditOutcome.FAILED
            ][-1],
            AuditReasonCode.INTEGRITY_FAILED,
        )

    def test_audit_failure_prevents_repository_mutation(self) -> None:
        failing_repository = MemoryRepository(
            connection_provider=self.database,
            audit_sink=FailingAuditSink(),
            clock=lambda: NOW,
        )

        with self.assertRaises(AuditWriteError):
            failing_repository.create_record(
                self._fact(), self._explicit(), uuid4()
            )

        with self.database.connect(uuid4()) as connection:
            count = connection.execute("SELECT count(*) FROM records").fetchone()[0]
        self.assertEqual(count, 0)

    def test_audit_events_exclude_memory_content_and_database_path(self) -> None:
        marker = "synthetic-private-content"
        record = self.repository.create_record(
            self._fact(marker), self._explicit(), uuid4()
        )
        self.repository.inspect_record(record.record_id, uuid4())

        displayed = repr(
            [
                event
                for event in self.audit_sink.events
                if event.operation
                in {AuditOperation.REPOSITORY_READ, AuditOperation.REPOSITORY_WRITE}
            ]
        )
        self.assertNotIn(marker, displayed)
        self.assertNotIn(self._temporary_directory.name, displayed)
        self.assertIn(str(record.record_id), displayed)


if __name__ == "__main__":
    unittest.main()
