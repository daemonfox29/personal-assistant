"""Synthetic checks for bounded, deterministic encrypted-memory retrieval."""

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from personal_assistant.audit import AuditOperation, InMemoryAuditSink
from personal_assistant.encrypted_database import (
    EncryptedDatabase,
    EncryptedDatabaseSettings,
)
from personal_assistant.key_provider import DatabaseKey
from personal_assistant.memory_repository import (
    MAX_RETRIEVAL_RECORDS,
    MAX_RETRIEVAL_TOKENS,
    MemoryRepository,
    RetrievalExclusion,
    RetrievalMode,
    RetrievalRequest,
)
from personal_assistant.memory_types import (
    ActorType,
    EntityDraft,
    EntityType,
    FactPayload,
    InsightConfidence,
    InsightPayload,
    MemoryValidationError,
    MentionPolicy,
    Provenance,
    PurgeReason,
    RecordDraft,
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


class MemoryRetrievalTests(unittest.TestCase):
    def setUp(self) -> None:
        self._temporary_directory = TemporaryDirectory()
        self.audit_sink = InMemoryAuditSink()
        self.database = EncryptedDatabase(
            EncryptedDatabaseSettings(
                Path(self._temporary_directory.name) / "memory.db",
                "synthetic-retrieval-key",
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

    def tearDown(self) -> None:
        self._temporary_directory.cleanup()

    @staticmethod
    def _explicit() -> Provenance:
        return Provenance(
            SourceType.EXPLICIT_USER,
            "synthetic-user-turn",
            ActorType.USER,
        )

    def _create(
        self,
        statement: str,
        *,
        status: RecordStatus = RecordStatus.CONFIRMED,
        sensitivity: Sensitivity = Sensitivity.NORMAL,
        mention_policy: MentionPolicy = MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
        scope: Scope = Scope(ScopeType.GLOBAL),
        primary_entity_id=None,  # type: ignore[no-untyped-def]
        valid_from=None,  # type: ignore[no-untyped-def]
        valid_until=None,  # type: ignore[no-untyped-def]
    ):
        provenance = self._explicit()
        if status is RecordStatus.CANDIDATE:
            provenance = Provenance(
                SourceType.MODEL_CANDIDATE,
                "synthetic-model-turn",
                ActorType.MODEL_CANDIDATE,
                "synthetic-model-v1",
            )
        return self.repository.create_record(
            RecordDraft(
                FactPayload("synthetic subject", statement),
                status,
                sensitivity,
                mention_policy,
                scope,
                primary_entity_id,
                valid_from,
                valid_until,
            ),
            provenance,
            uuid4(),
        )

    def test_only_eligible_confirmed_current_memories_are_returned(self) -> None:
        allowed = self._create("Luna likes synthetic parks")
        self._create("Luna candidate synthetic parks", status=RecordStatus.CANDIDATE)
        self._create(
            "Luna restricted synthetic parks",
            sensitivity=Sensitivity.RESTRICTED,
        )
        self._create(
            "Luna hidden synthetic parks",
            mention_policy=MentionPolicy.NEVER_MENTION,
        )
        self._create(
            "Luna future synthetic parks",
            valid_from=NOW + timedelta(days=1),
        )

        result = self.repository.retrieve(
            RetrievalRequest("Luna synthetic parks"), uuid4()
        )

        self.assertEqual(
            [item.record.record_id for item in result.memories],
            [allowed.record_id],
        )
        self.assertIn("confirmed_only", result.receipt.applied_rules)
        self.assertIn(
            "restricted_requires_separate_authorization",
            result.receipt.applied_rules,
        )

    def test_only_low_risk_insight_candidates_can_be_tentatively_retrieved(
        self,
    ) -> None:
        provenance = Provenance(
            SourceType.MODEL_CANDIDATE,
            "synthetic-model-observation",
            ActorType.MODEL_CANDIDATE,
            "synthetic-model-v1",
        )
        observation = self.repository.create_record(
            RecordDraft(
                InsightPayload(
                    "Synthetic interruptions may be situationally draining",
                    InsightConfidence.LOW,
                    "Only one synthetic event was considered",
                    NOW,
                    NOW,
                ),
                RecordStatus.CANDIDATE,
                Sensitivity.PERSONAL,
                MentionPolicy.ASK_BEFORE_MENTIONING,
                Scope(ScopeType.GLOBAL),
            ),
            provenance,
            uuid4(),
        )
        self._create(
            "Synthetic interruptions are an unconfirmed global fact",
            status=RecordStatus.CANDIDATE,
        )
        self.repository.create_record(
            RecordDraft(
                InsightPayload(
                    "Synthetic interruptions reveal a restricted observation",
                    InsightConfidence.LOW,
                    "Only one synthetic event was considered",
                    NOW,
                    NOW,
                ),
                RecordStatus.CANDIDATE,
                Sensitivity.SENSITIVE,
                MentionPolicy.ONLY_WHEN_DIRECTLY_ASKED,
                Scope(ScopeType.GLOBAL),
            ),
            provenance,
            uuid4(),
        )

        default = self.repository.retrieve(
            RetrievalRequest(
                "Synthetic interruptions",
                mode=RetrievalMode.APPROVED,
            ),
            uuid4(),
        )
        tentative = self.repository.retrieve(
            RetrievalRequest(
                "Synthetic interruptions",
                mode=RetrievalMode.APPROVED,
                include_tentative_observations=True,
            ),
            uuid4(),
        )

        self.assertEqual(default.memories, ())
        self.assertEqual(tentative.receipt.selected_record_ids, (observation.record_id,))
        self.assertIn("tentative_observation", tentative.memories[0].reasons)
        self.assertIn(
            "confirmed_and_labeled_tentative_observations",
            tentative.receipt.applied_rules,
        )

    def test_expired_observation_is_not_tentatively_retrieved(self) -> None:
        provenance = Provenance(
            SourceType.MODEL_CANDIDATE,
            "synthetic-expiring-observation",
            ActorType.MODEL_CANDIDATE,
            "synthetic-model-v1",
        )
        self.repository.create_record(
            RecordDraft(
                InsightPayload(
                    "Synthetic expiring observation",
                    InsightConfidence.LOW,
                    "Only one synthetic event was considered",
                    NOW,
                    NOW,
                ),
                RecordStatus.CANDIDATE,
                Sensitivity.PERSONAL,
                MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
                Scope(ScopeType.GLOBAL),
            ),
            provenance,
            uuid4(),
        )
        later_repository = MemoryRepository(
            connection_provider=self.database,
            audit_sink=self.audit_sink,
            clock=lambda: NOW + timedelta(days=31),
        )

        result = later_repository.retrieve(
            RetrievalRequest(
                "Synthetic expiring observation",
                include_tentative_observations=True,
            ),
            uuid4(),
        )

        self.assertEqual(result.memories, ())

    def test_confirmed_memory_uses_bounded_capacity_before_observation(self) -> None:
        confirmed = self._create("Synthetic capacity topic is a confirmed fact")
        provenance = Provenance(
            SourceType.MODEL_CANDIDATE,
            "synthetic-capacity-observation",
            ActorType.MODEL_CANDIDATE,
            "synthetic-model-v1",
        )
        self.repository.create_record(
            RecordDraft(
                InsightPayload(
                    "Synthetic capacity topic may have a contextual exception",
                    InsightConfidence.LOW,
                    "Only one synthetic event was considered",
                    NOW,
                    NOW,
                ),
                RecordStatus.CANDIDATE,
                Sensitivity.PERSONAL,
                MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
                Scope(ScopeType.GLOBAL),
            ),
            provenance,
            uuid4(),
        )

        result = self.repository.retrieve(
            RetrievalRequest(
                "Synthetic capacity topic",
                max_records=1,
                include_tentative_observations=True,
            ),
            uuid4(),
        )

        self.assertEqual(result.receipt.selected_record_ids, (confirmed.record_id,))

    def test_natural_query_can_recall_partial_lexical_match(self) -> None:
        record = self._create("Luna likes synthetic blue toys")

        result = self.repository.retrieve(
            RetrievalRequest("What toys does Luna like?"), uuid4()
        )

        self.assertEqual(result.receipt.selected_record_ids, (record.record_id,))

    def test_conversational_words_and_extra_descriptor_do_not_hide_subject(self) -> None:
        record = self._create("Scooby enjoys synthetic naps")

        result = self.repository.retrieve(
            RetrievalRequest("What do you know about Scooby my dog?"),
            uuid4(),
        )

        self.assertEqual(result.receipt.selected_record_ids, (record.record_id,))

    def test_direct_mode_allows_only_direct_policy_but_not_restricted_data(self) -> None:
        direct = self._create(
            "Luna direct synthetic detail",
            mention_policy=MentionPolicy.ONLY_WHEN_DIRECTLY_ASKED,
        )
        self._create(
            "Luna direct restricted detail",
            sensitivity=Sensitivity.RESTRICTED,
            mention_policy=MentionPolicy.ONLY_WHEN_DIRECTLY_ASKED,
        )

        ordinary = self.repository.retrieve(
            RetrievalRequest("Luna direct detail"), uuid4()
        )
        requested = self.repository.retrieve(
            RetrievalRequest("Luna direct detail", mode=RetrievalMode.DIRECT),
            uuid4(),
        )

        self.assertEqual(ordinary.memories, ())
        self.assertEqual(
            [item.record.record_id for item in requested.memories],
            [direct.record_id],
        )

    def test_direct_question_can_use_ask_before_memory_without_second_prompt(self) -> None:
        record = self._create(
            "Scooby has a synthetic favorite toy",
            sensitivity=Sensitivity.PERSONAL,
            mention_policy=MentionPolicy.ASK_BEFORE_MENTIONING,
        )

        result = self.repository.retrieve(
            RetrievalRequest(
                "What do you know about Scooby?",
                mode=RetrievalMode.DIRECT,
            ),
            uuid4(),
        )

        self.assertEqual(result.receipt.selected_record_ids, (record.record_id,))

    def test_specific_scope_and_resolved_entity_outrank_global_text(self) -> None:
        topic = Scope(ScopeType.TOPIC, uuid4())
        entity = self.repository.create_entity(EntityDraft(EntityType.PET), uuid4())
        global_record = self._create("Luna synthetic food preference")
        scoped_record = self._create(
            "Luna synthetic food preference",
            scope=topic,
            primary_entity_id=entity.entity_id,
        )

        result = self.repository.retrieve(
            RetrievalRequest(
                "Luna food",
                scopes=(topic,),
                entity_ids=(entity.entity_id,),
            ),
            uuid4(),
        )

        self.assertEqual(result.memories[0].record.record_id, scoped_record.record_id)
        self.assertEqual(result.memories[1].record.record_id, global_record.record_id)
        self.assertIn("resolved_entity_match", result.memories[0].reasons)
        self.assertIn("specific_scope_match", result.memories[0].reasons)

    def test_resolved_entity_can_retrieve_without_raw_query_text(self) -> None:
        entity = self.repository.create_entity(EntityDraft(EntityType.PET), uuid4())
        record = self._create(
            "synthetic veterinary appointment",
            primary_entity_id=entity.entity_id,
        )

        result = self.repository.retrieve(
            RetrievalRequest("", entity_ids=(entity.entity_id,)), uuid4()
        )

        self.assertEqual(result.receipt.selected_record_ids, (record.record_id,))

    def test_retrieval_excludes_question_shaped_legacy_fact_and_duplicates(
        self,
    ) -> None:
        question = self.repository.create_record(
            RecordDraft(
                FactPayload(
                    "direct-statement:synthetic-question",
                    "have I ever lived in chicago",
                ),
                RecordStatus.CONFIRMED,
                Sensitivity.PERSONAL,
                MentionPolicy.ASK_BEFORE_MENTIONING,
                Scope(ScopeType.GLOBAL),
            ),
            self._explicit(),
            uuid4(),
        )
        self._create("Synthetic canonical duplicate fact")
        self._create("synthetic canonical duplicate fact.")

        question_result = self.repository.retrieve(
            RetrievalRequest(
                "Chicago",
                mode=RetrievalMode.DIRECT,
            ),
            uuid4(),
        )
        duplicate_result = self.repository.retrieve(
            RetrievalRequest("synthetic canonical duplicate"),
            uuid4(),
        )

        self.assertNotIn(
            question.record_id,
            question_result.receipt.selected_record_ids,
        )
        self.assertEqual(
            dict(question_result.receipt.exclusion_counts)[
                RetrievalExclusion.UNCONFIRMED
            ],
            1,
        )
        self.assertEqual(len(duplicate_result.memories), 1)
        self.assertEqual(
            dict(duplicate_result.receipt.exclusion_counts)[
                RetrievalExclusion.DUPLICATE_CONTENT
            ],
            1,
        )
        self.assertIn(
            "equivalent_content_deduplicated",
            duplicate_result.receipt.applied_rules,
        )

    def test_record_and_token_limits_are_enforced_independently(self) -> None:
        for index in range(4):
            self._create(f"bounded synthetic retrieval item {index}")

        count_limited = self.repository.retrieve(
            RetrievalRequest("bounded synthetic", max_records=2), uuid4()
        )
        token_limited = self.repository.retrieve(
            RetrievalRequest("bounded synthetic", token_limit=100), uuid4()
        )

        self.assertEqual(len(count_limited.memories), 2)
        self.assertEqual(
            dict(count_limited.receipt.exclusion_counts)[
                RetrievalExclusion.RESULT_LIMIT
            ],
            2,
        )
        self.assertLessEqual(token_limited.receipt.tokens_returned, 100)
        self.assertGreater(
            dict(token_limited.receipt.exclusion_counts)[
                RetrievalExclusion.TOKEN_LIMIT
            ],
            0,
        )

    def test_search_index_tracks_revision_and_permanent_purge(self) -> None:
        record = self._create("obsolete synthetic phrase")
        revised = self.repository.revise_record(
            record.record_id,
            record.row_version,
            FactPayload("synthetic subject", "replacement synthetic phrase"),
            self._explicit(),
            uuid4(),
        )

        self.assertEqual(
            self.repository.retrieve(
                RetrievalRequest("obsolete"), uuid4()
            ).memories,
            (),
        )
        self.assertEqual(
            self.repository.retrieve(
                RetrievalRequest("replacement"), uuid4()
            ).receipt.selected_record_ids,
            (record.record_id,),
        )

        self.repository.purge_record(
            record.record_id,
            revised.row_version,
            PurgeReason.USER_REQUESTED,
            uuid4(),
        )
        self.assertEqual(
            self.repository.retrieve(
                RetrievalRequest("replacement"), uuid4()
            ).memories,
            (),
        )

    def test_query_syntax_is_data_and_receipt_and_audit_are_content_free(self) -> None:
        record = self._create("needle private sentinel synthetic memory")
        query = 'needle" AND private-sentinel --'

        result = self.repository.retrieve(RetrievalRequest(query), uuid4())

        self.assertEqual(result.receipt.selected_record_ids, (record.record_id,))
        retrieval_events = [
            event
            for event in self.audit_sink.events
            if event.operation is AuditOperation.REPOSITORY_READ
            and any(
                item.value == "record_retrieve" for item in event.metadata
            )
        ]
        self.assertEqual(len(retrieval_events), 2)
        self.assertNotIn(
            "private-sentinel",
            repr(retrieval_events) + repr(result.receipt),
        )

    def test_request_limits_and_shapes_fail_before_database_work(self) -> None:
        with self.assertRaises(MemoryValidationError):
            RetrievalRequest("")
        with self.assertRaises(MemoryValidationError):
            RetrievalRequest("why is about me")
        with self.assertRaises(MemoryValidationError):
            RetrievalRequest("synthetic", max_records=MAX_RETRIEVAL_RECORDS + 1)
        with self.assertRaises(MemoryValidationError):
            RetrievalRequest("synthetic", token_limit=MAX_RETRIEVAL_TOKENS + 1)
        with self.assertRaises(MemoryValidationError):
            RetrievalRequest("synthetic", scopes=(Scope(ScopeType.GLOBAL),))


if __name__ == "__main__":
    unittest.main()
