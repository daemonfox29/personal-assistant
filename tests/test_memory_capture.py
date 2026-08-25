"""Synthetic checks for explicit capture and quarantined model suggestions."""

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
from personal_assistant.memory_capture import (
    AutomaticMemorySuggestion,
    CaptureDecision,
    ExplicitMemoryRequest,
    MemoryCaptureCoordinator,
)
from personal_assistant.memory_repository import MemoryRepository, RetrievalRequest
from personal_assistant.memory_types import (
    FactPayload,
    MemoryValidationError,
    MentionPolicy,
    NotePayload,
    PreferencePayload,
    RecordStatus,
    Scope,
    ScopeType,
    Sensitivity,
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


class MemoryCaptureTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = TemporaryDirectory()
        self.audit_sink = InMemoryAuditSink()
        self.database = EncryptedDatabase(
            EncryptedDatabaseSettings(
                Path(self._temporary_directory.name) / "memory.db",
                "synthetic-capture-key",
            ),
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
        self.coordinator = MemoryCaptureCoordinator(
            self.repository,
            self.audit_sink,
        )

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    @staticmethod
    def _explicit(
        payload=None,  # type: ignore[no-untyped-def]
        *,
        sensitivity: Sensitivity = Sensitivity.NORMAL,
        mention_policy: MentionPolicy = MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
        source_ref: str = "synthetic-explicit-turn",
    ) -> ExplicitMemoryRequest:
        return ExplicitMemoryRequest(
            payload or FactPayload("synthetic subject", "synthetic statement"),
            sensitivity,
            mention_policy,
            Scope(ScopeType.GLOBAL),
            source_ref,
        )

    @staticmethod
    def _suggestion(
        payload=None,  # type: ignore[no-untyped-def]
        *,
        sensitivity: Sensitivity = Sensitivity.NORMAL,
        mention_policy: MentionPolicy = MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
        source_ref: str = "synthetic-model-turn",
        model_version: str = "synthetic-model-v1",
    ) -> AutomaticMemorySuggestion:
        return AutomaticMemorySuggestion(
            payload or FactPayload("synthetic subject", "synthetic statement"),
            sensitivity,
            mention_policy,
            Scope(ScopeType.GLOBAL),
            source_ref,
            model_version,
        )

    def test_explicit_instruction_creates_confirmed_revisioned_memory(self) -> None:
        result = self.coordinator.remember_explicitly(self._explicit(), uuid4())

        self.assertEqual(result.decision, CaptureDecision.CREATED_CONFIRMED)
        assert result.record is not None
        self.assertEqual(result.record.status, RecordStatus.CONFIRMED)
        self.assertEqual(result.record.current_revision, 1)
        self.assertEqual(
            result.record.revision.provenance.source_ref,
            "synthetic-explicit-turn",
        )

    def test_exact_confirmed_duplicate_is_reused_without_another_write(self) -> None:
        first = self.coordinator.remember_explicitly(self._explicit(), uuid4())
        second = self.coordinator.remember_explicitly(self._explicit(), uuid4())

        assert first.record is not None
        self.assertEqual(second.decision, CaptureDecision.DUPLICATE)
        self.assertEqual(second.related_record_ids, (first.record.record_id,))
        with self.database.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM records").fetchone()[0],
                1,
            )

    def test_explicit_instruction_confirms_one_matching_candidate(self) -> None:
        candidate = self.coordinator.suggest_automatically(
            self._suggestion(),
            uuid4(),
        )
        assert candidate.record is not None

        result = self.coordinator.remember_explicitly(self._explicit(), uuid4())

        self.assertEqual(
            result.decision,
            CaptureDecision.CONFIRMED_EXISTING_CANDIDATE,
        )
        assert result.record is not None
        self.assertEqual(result.record.record_id, candidate.record.record_id)
        self.assertEqual(result.record.status, RecordStatus.CONFIRMED)
        self.assertEqual(result.record.current_revision, 2)

    def test_changed_value_requires_clarification_instead_of_overwrite(self) -> None:
        first = self.coordinator.remember_explicitly(
            self._explicit(
                PreferencePayload("synthetic beverage", "synthetic tea")
            ),
            uuid4(),
        )
        assert first.record is not None

        result = self.coordinator.remember_explicitly(
            self._explicit(
                PreferencePayload("synthetic beverage", "synthetic coffee")
            ),
            uuid4(),
        )

        self.assertEqual(result.decision, CaptureDecision.CLARIFICATION_REQUIRED)
        self.assertEqual(result.related_record_ids, (first.record.record_id,))
        with self.database.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM records").fetchone()[0],
                1,
            )

    def test_unrelated_global_facts_do_not_trigger_the_neighbor_safety_cap(self) -> None:
        for index in range(70):
            result = self.coordinator.remember_explicitly(
                self._explicit(
                    FactPayload(
                        f"synthetic unrelated subject {index}",
                        f"synthetic unrelated value {index}",
                    ),
                    source_ref=f"synthetic-explicit-{index}",
                ),
                uuid4(),
            )
            self.assertEqual(result.decision, CaptureDecision.CREATED_CONFIRMED)

        final = self.coordinator.remember_explicitly(
            self._explicit(
                FactPayload("synthetic final subject", "synthetic final value"),
                source_ref="synthetic-explicit-final",
            ),
            uuid4(),
        )

        self.assertEqual(final.decision, CaptureDecision.CREATED_CONFIRMED)

    def test_higher_risk_explicit_memory_waits_for_separate_review(self) -> None:
        result = self.coordinator.remember_explicitly(
            self._explicit(sensitivity=Sensitivity.SENSITIVE),
            uuid4(),
        )

        self.assertEqual(
            result.decision,
            CaptureDecision.EXPLICIT_HIGHER_RISK_REVIEW_REQUIRED,
        )
        with self.database.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM records").fetchone()[0],
                0,
            )

    def test_deterministic_policy_can_raise_but_model_cannot_lower_sensitivity(self) -> None:
        explicit = self.coordinator.remember_explicitly(
            self._explicit(
                FactPayload(
                    "synthetic childhood history",
                    "synthetic childhood trauma detail",
                ),
                sensitivity=Sensitivity.NORMAL,
            ),
            uuid4(),
        )
        inferred = self.coordinator.suggest_automatically(
            self._suggestion(
                FactPayload(
                    "synthetic childhood history",
                    "synthetic childhood trauma inference",
                ),
                sensitivity=Sensitivity.NORMAL,
            ),
            uuid4(),
        )

        self.assertEqual(
            explicit.decision,
            CaptureDecision.EXPLICIT_HIGHER_RISK_REVIEW_REQUIRED,
        )
        assert inferred.record is not None
        self.assertEqual(inferred.record.sensitivity, Sensitivity.RESTRICTED)
        self.assertEqual(
            inferred.record.mention_policy,
            MentionPolicy.NEVER_MENTION,
        )

    def test_automatic_suggestion_is_expiring_quarantined_and_conservative(self) -> None:
        result = self.coordinator.suggest_automatically(
            self._suggestion(
                NotePayload("synthetic note", "synthetic inferred detail")
            ),
            uuid4(),
        )

        self.assertEqual(result.decision, CaptureDecision.CREATED_CANDIDATE)
        assert result.record is not None
        self.assertEqual(result.record.status, RecordStatus.CANDIDATE)
        self.assertEqual(result.record.sensitivity, Sensitivity.PERSONAL)
        self.assertEqual(
            result.record.mention_policy,
            MentionPolicy.ASK_BEFORE_MENTIONING,
        )
        self.assertEqual(result.record.candidate_expires_at, NOW + timedelta(days=30))
        self.assertEqual(
            self.repository.retrieve(
                RetrievalRequest("synthetic inferred detail"), uuid4()
            ).memories,
            (),
        )

    def test_restricted_model_suggestion_can_never_be_mentioned_automatically(self) -> None:
        result = self.coordinator.suggest_automatically(
            self._suggestion(
                sensitivity=Sensitivity.RESTRICTED,
                mention_policy=MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
            ),
            uuid4(),
        )

        assert result.record is not None
        self.assertEqual(result.record.sensitivity, Sensitivity.RESTRICTED)
        self.assertEqual(result.record.mention_policy, MentionPolicy.NEVER_MENTION)

    def test_potential_model_conflict_is_quarantined_for_review(self) -> None:
        confirmed = self.coordinator.remember_explicitly(
            self._explicit(
                PreferencePayload("synthetic schedule", "synthetic mornings")
            ),
            uuid4(),
        )
        assert confirmed.record is not None

        result = self.coordinator.suggest_automatically(
            self._suggestion(
                PreferencePayload("synthetic schedule", "synthetic evenings")
            ),
            uuid4(),
        )

        self.assertEqual(
            result.decision,
            CaptureDecision.CREATED_CANDIDATE_REVIEW_REQUIRED,
        )
        assert result.record is not None
        self.assertEqual(result.record.status, RecordStatus.CANDIDATE)
        self.assertEqual(result.related_record_ids, (confirmed.record.record_id,))

    def test_candidate_limit_is_persisted_per_turn_even_across_model_versions(self) -> None:
        for index in range(3):
            result = self.coordinator.suggest_automatically(
                self._suggestion(
                    FactPayload(
                        f"synthetic topic {index}",
                        f"synthetic candidate {index}",
                    )
                ),
                uuid4(),
            )
            self.assertEqual(result.decision, CaptureDecision.CREATED_CANDIDATE)

        limited = self.coordinator.suggest_automatically(
            self._suggestion(
                FactPayload("synthetic fourth topic", "synthetic fourth candidate"),
                model_version="synthetic-model-v2",
            ),
            uuid4(),
        )

        self.assertEqual(limited.decision, CaptureDecision.CANDIDATE_LIMIT_REACHED)
        with self.database.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute(
                    "SELECT count(*) FROM records WHERE status = 'candidate'"
                ).fetchone()[0],
                3,
            )

    def test_post_response_suggestion_batch_is_small_and_cancellable(self) -> None:
        suggestions = tuple(
            self._suggestion(
                FactPayload(
                    f"synthetic batch topic {index}",
                    f"synthetic batch candidate {index}",
                )
            )
            for index in range(3)
        )
        checks = 0

        def cancel_after_first() -> bool:
            nonlocal checks
            checks += 1
            return checks > 1

        result = self.coordinator.process_suggestion_batch(
            suggestions,
            uuid4(),
            is_cancelled=cancel_after_first,
        )

        self.assertTrue(result.cancelled)
        self.assertEqual(len(result.results), 1)
        assert result.results[0].record is not None
        self.assertEqual(result.results[0].record.status, RecordStatus.CANDIDATE)
        with self.assertRaises(MemoryValidationError):
            self.coordinator.process_suggestion_batch(
                suggestions
                + (
                    self._suggestion(
                        FactPayload("synthetic extra", "synthetic extra value")
                    ),
                ),
                uuid4(),
            )

    def test_model_content_and_source_text_never_enter_audit_metadata(self) -> None:
        private_text = "synthetic-private-memory-value"
        result = self.coordinator.suggest_automatically(
            self._suggestion(
                FactPayload("synthetic subject", private_text),
                source_ref="synthetic-private-turn",
            ),
            uuid4(),
        )

        self.assertEqual(result.decision, CaptureDecision.CREATED_CANDIDATE)
        repository_events = [
            event
            for event in self.audit_sink.events
            if event.operation
            in {
                AuditOperation.REPOSITORY_READ,
                AuditOperation.REPOSITORY_WRITE,
                AuditOperation.MEMORY_CAPTURE,
            }
        ]
        self.assertNotIn(private_text, repr(repository_events))
        self.assertNotIn("synthetic-private-turn", repr(repository_events))

    def test_non_write_capture_decisions_are_still_audited(self) -> None:
        self.coordinator.remember_explicitly(self._explicit(), uuid4())
        self.coordinator.remember_explicitly(self._explicit(), uuid4())
        self.coordinator.remember_explicitly(
            self._explicit(sensitivity=Sensitivity.SENSITIVE),
            uuid4(),
        )

        completed = [
            event
            for event in self.audit_sink.events
            if event.operation is AuditOperation.MEMORY_CAPTURE
            and event.outcome is not AuditOutcome.STARTED
        ]
        self.assertEqual(
            [(event.outcome, event.reason_code) for event in completed],
            [
                (AuditOutcome.SUCCEEDED, AuditReasonCode.NORMAL),
                (AuditOutcome.SKIPPED, AuditReasonCode.DUPLICATE),
                (AuditOutcome.DENIED, AuditReasonCode.POLICY_DENIED),
            ],
        )

    def test_invalid_or_credential_related_inputs_fail_before_capture(self) -> None:
        with self.assertRaises(MemoryValidationError):
            FactPayload("synthetic login", "my password is synthetic")
        with self.assertRaises(MemoryValidationError):
            self._suggestion(source_ref="unsafe source with spaces")
        with self.assertRaises(ValueError):
            MemoryCaptureCoordinator(
                self.repository,
                self.audit_sink,
                candidates_per_source=6,
            )

    def test_capture_audit_failure_prevents_database_mutation(self) -> None:
        coordinator = MemoryCaptureCoordinator(
            self.repository,
            FailingAuditSink(),  # type: ignore[arg-type]
        )

        with self.assertRaises(AuditWriteError):
            coordinator.remember_explicitly(self._explicit(), uuid4())

        with self.database.connect(uuid4()) as connection:
            self.assertEqual(
                connection.execute("SELECT count(*) FROM records").fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
