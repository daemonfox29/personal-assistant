"""Synthetic tests for post-response quarantined memory analysis."""

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest
from unittest.mock import Mock
from uuid import uuid4

from personal_assistant.audit import AuditOutcome, InMemoryAuditSink
from personal_assistant.encrypted_database import (
    EncryptedDatabase,
    EncryptedDatabaseSettings,
)
from personal_assistant.key_provider import DatabaseKey
from personal_assistant.memory_analyzer import (
    ModelMemorySuggestionAnalyzer,
    PostResponseMemoryWorker,
    has_clear_direct_memory_statement,
)
from personal_assistant.memory_capture import MemoryCaptureCoordinator
from personal_assistant.memory_capture import AutomaticMemorySuggestion
from personal_assistant.memory_repository import (
    MemoryRepository,
    RetrievalMode,
    RetrievalRequest,
)
from personal_assistant.migration import MigrationRunner, PackageMigrationSource
from personal_assistant.model import LanguageModel, ModelResponse
from personal_assistant.memory_types import (
    FactPayload,
    InsightConfidence,
    InsightPayload,
    MentionPolicy,
    RecordStatus,
    Scope,
    ScopeType,
    Sensitivity,
)


SYNTHETIC_KEY = bytes(range(32))


class SyntheticKeyProvider:
    def acquire(self, key_id: str) -> DatabaseKey:
        return DatabaseKey(SYNTHETIC_KEY)


class MemoryAnalyzerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = TemporaryDirectory()
        self.audit = InMemoryAuditSink()
        database = EncryptedDatabase(
            EncryptedDatabaseSettings(
                Path(self.temporary_directory.name) / "memory.db",
                "synthetic-analyzer-key",
            ),
            key_provider=SyntheticKeyProvider(),
            audit_sink=self.audit,
        )
        MigrationRunner(
            connection_provider=database,
            migration_source=PackageMigrationSource(),
            audit_sink=self.audit,
        ).migrate(uuid4())
        self.repository = MemoryRepository(
            connection_provider=database,
            audit_sink=self.audit,
        )
        self.coordinator = MemoryCaptureCoordinator(self.repository, self.audit)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_pre_response_gate_selects_clear_durable_statements_not_questions(self) -> None:
        self.assertTrue(
            has_clear_direct_memory_statement(
                "I have a synthetic gluten sensitivity."
            )
        )
        self.assertTrue(
            has_clear_direct_memory_statement(
                "I am synthetically gluten sensitive."
            )
        )
        self.assertTrue(
            has_clear_direct_memory_statement("Synthetic Scooby is my dog.")
        )
        self.assertTrue(
            has_clear_direct_memory_statement(
                "My vet is Synthetic Veterinary Center."
            )
        )
        self.assertFalse(
            has_clear_direct_memory_statement("Do I have any gut sensitivities?")
        )
        self.assertFalse(
            has_clear_direct_memory_statement("have I ever lived in chicago")
        )
        self.assertFalse(
            has_clear_direct_memory_statement("I was born and raised there!")
        )
        self.assertTrue(
            has_clear_direct_memory_statement("I lived in Chicago from 2021-2023.")
        )
        self.assertFalse(has_clear_direct_memory_statement("I have a question."))

    def test_ungrounded_model_fact_is_discarded_not_stored(self) -> None:
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "fact",
                        "subject": "Luna synthetic toy",
                        "content": "Luna likes synthetic rope toys",
                        "sensitivity": "normal",
                        "mention_policy": "may_mention_when_relevant",
                    }
                ]
            )
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
        )

        suggestions = analyzer.analyze(
            "Luna likes rope toys",
            "That sounds fun.",
            "turn:11111111-1111-1111-1111-111111111111",
            uuid4(),
        )
        result = self.coordinator.process_suggestion_batch(suggestions, uuid4())

        self.assertEqual(suggestions, ())
        self.assertEqual(result.results, ())
        self.assertEqual(
            self.repository.retrieve(
                RetrievalRequest("Luna rope toys"), uuid4()
            ).memories,
            (),
        )
        request = model.generate.call_args.args[0]
        self.assertEqual(request.max_response_tokens, 400)
        self.assertIn("untrusted data", request.messages[-1].content)

    def test_model_observation_is_low_confidence_candidate_even_with_exact_quote(
        self,
    ) -> None:
        observed_at = datetime(2026, 1, 2, tzinfo=timezone.utc)
        user_text = "Synthetic interruptions have been wearing me down lately."
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "observation",
                        "subject": "synthetic interruptions",
                        "content": (
                            "Synthetic interruptions may be wearing the user "
                            "down in the current situation"
                        ),
                        "evidence_quote": user_text,
                        "sensitivity": "normal",
                        "mention_policy": "may_mention_when_relevant",
                    }
                ]
            )
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
            clock=lambda: observed_at,
        )

        suggestions = analyzer.analyze(
            user_text,
            "That sounds draining.",
            "turn:22222222-2222-2222-2222-222222222222",
            uuid4(),
        )
        batch = self.coordinator.process_suggestion_batch(
            suggestions,
            uuid4(),
            direct_user_text=user_text,
        )

        self.assertEqual(len(suggestions), 1)
        self.assertIsNone(suggestions[0].user_evidence)
        self.assertEqual(batch.results[0].record.status, RecordStatus.CANDIDATE)
        payload = batch.results[0].record.revision.payload
        assert isinstance(payload, InsightPayload)
        self.assertEqual(payload.confidence, InsightConfidence.LOW)
        self.assertEqual(payload.range_start, observed_at)
        self.assertIn("current completed turn", payload.contradictions_considered)
        prompt = model.generate.call_args.args[0].messages[0].content
        self.assertIn("situation, time, or context", prompt)
        self.assertIn("do not diagnose", prompt)

    def test_exact_user_quote_can_be_confirmed_without_model_authored_content(self) -> None:
        user_text = "My name is Synthetic Person."
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "fact",
                        "subject": "model-authored subject",
                        "content": "model-authored paraphrase",
                        "evidence_quote": user_text,
                        "sensitivity": "normal",
                        "mention_policy": "may_mention_when_relevant",
                    }
                ]
            )
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
        )

        suggestions = analyzer.analyze(
            user_text,
            "Thanks for telling me.",
            "turn:33333333-3333-3333-3333-333333333333",
            uuid4(),
        )
        result = self.coordinator.process_suggestion_batch(
            suggestions,
            uuid4(),
            direct_user_text=user_text,
        )

        self.assertEqual(result.results[0].record.status, RecordStatus.CONFIRMED)
        recalled = self.repository.retrieve(
            RetrievalRequest("my name", mode=RetrievalMode.APPROVED),
            uuid4(),
        )
        self.assertEqual(len(recalled.memories), 1)
        payload = recalled.memories[0].record.revision.payload
        assert isinstance(payload, FactPayload)
        self.assertEqual(payload.statement, user_text)
        self.assertNotIn("model-authored", payload.statement)

    def test_exact_model_content_selects_complete_user_assertion_not_paraphrase(self) -> None:
        user_text = "Scooby is my dog. He likes synthetic naps."
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "fact",
                        "subject": "model-authored pet subject",
                        "content": "Scooby is my dog",
                        "evidence_quote": "",
                        "sensitivity": "normal",
                        "mention_policy": "may_mention_when_relevant",
                    }
                ]
            )
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
        )

        suggestions = analyzer.analyze(
            user_text,
            "Thanks for telling me.",
            "turn:44444444-4444-4444-4444-444444444444",
            uuid4(),
        )
        result = self.coordinator.process_suggestion_batch(
            suggestions,
            uuid4(),
            direct_user_text=user_text,
        )

        assert result.results[0].record is not None
        self.assertEqual(result.results[0].record.status, RecordStatus.CONFIRMED)
        payload = result.results[0].record.revision.payload
        assert isinstance(payload, FactPayload)
        self.assertEqual(payload.statement, "Scooby is my dog.")

    def test_model_paraphrases_select_exact_location_and_pet_sentences(self) -> None:
        user_text = (
            "I live in Synthetic Denver. My dog is named Synthetic Scooby."
        )
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "fact",
                        "subject": "model-authored residence",
                        "content": "The user resides in Synthetic Denver",
                        "evidence_quote": "",
                        "sensitivity": "personal",
                        "mention_policy": "may_mention_when_relevant",
                    },
                    {
                        "type": "fact",
                        "subject": "model-authored pet",
                        "content": "The user's dog is Synthetic Scooby",
                        "evidence_quote": "",
                        "sensitivity": "normal",
                        "mention_policy": "may_mention_when_relevant",
                    },
                ]
            )
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
        )

        suggestions = analyzer.analyze(
            user_text,
            "Thanks for telling me.",
            "turn:66666666-6666-6666-6666-666666666666",
            uuid4(),
        )

        self.assertEqual(
            tuple(item.user_evidence for item in suggestions),
            (
                "I live in Synthetic Denver.",
                "My dog is named Synthetic Scooby.",
            ),
        )

    def test_ambiguous_paraphrase_is_discarded(self) -> None:
        user_text = "My dog Luna likes naps. My dog Scooby likes walks."
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "fact",
                        "subject": "model-authored dog",
                        "content": "The user's dog likes playing",
                        "evidence_quote": "",
                        "sensitivity": "normal",
                        "mention_policy": "may_mention_when_relevant",
                    }
                ]
            )
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
        )

        suggestions = analyzer.analyze(
            user_text,
            "assistant reply",
            "turn:77777777-7777-7777-7777-777777777777",
            uuid4(),
        )

        self.assertEqual(suggestions, ())

    def test_exact_content_skips_question_and_finds_later_assertion(self) -> None:
        user_text = "Is Scooby my dog? Scooby is my dog."
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "fact",
                        "subject": "model-authored pet subject",
                        "content": "Scooby",
                        "evidence_quote": "Scooby",
                        "sensitivity": "normal",
                        "mention_policy": "may_mention_when_relevant",
                    }
                ]
            )
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
        )

        suggestions = analyzer.analyze(
            user_text,
            "assistant reply",
            "turn:55555555-5555-5555-5555-555555555555",
            uuid4(),
        )

        self.assertEqual(suggestions[0].user_evidence, "Scooby is my dog.")

    def test_question_fragment_cannot_be_promoted_as_direct_evidence(self) -> None:
        user_text = "have I ever lived in chicago"
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "fact",
                        "subject": "model-authored residence subject",
                        "content": user_text,
                        "evidence_quote": user_text,
                        "sensitivity": "normal",
                        "mention_policy": "may_mention_when_relevant",
                    }
                ]
            )
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
        )

        suggestions = analyzer.analyze(
            user_text,
            "I can check.",
            "turn:55555555-5555-5555-5555-555555555555",
            uuid4(),
        )
        result = self.coordinator.process_suggestion_batch(
            suggestions,
            uuid4(),
            direct_user_text=user_text,
        )

        self.assertEqual(suggestions, ())
        self.assertEqual(result.results, ())
        self.assertEqual(self.repository.list_candidates(uuid4()), ())

    def test_uncertain_first_person_statement_cannot_be_auto_confirmed(self) -> None:
        user_text = "I think I have a synthetic gluten sensitivity."
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "fact",
                        "subject": "model-authored sensitivity",
                        "content": "model-authored paraphrase",
                        "evidence_quote": user_text,
                        "sensitivity": "personal",
                        "mention_policy": "ask_before_mentioning",
                    }
                ]
            )
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
        )

        suggestions = analyzer.analyze(
            user_text,
            "assistant reply",
            "turn:99999999-9999-9999-9999-999999999999",
            uuid4(),
        )
        result = self.coordinator.process_suggestion_batch(
            suggestions,
            uuid4(),
            direct_user_text=user_text,
        )

        self.assertEqual(suggestions, ())
        self.assertEqual(result.results, ())
        self.assertEqual(self.repository.list_candidates(uuid4()), ())

    def test_malformed_or_credential_proposal_is_discarded_and_audited(self) -> None:
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            '[{"type":"fact","subject":"password","content":"secret",'
            '"sensitivity":"normal","mention_policy":'
            '"may_mention_when_relevant"}]'
        )
        analyzer = ModelMemorySuggestionAnalyzer(
            model,
            "synthetic-model-v1",
            audit_sink=self.audit,
        )

        suggestions = analyzer.analyze(
            "synthetic user text",
            "synthetic response",
            "turn:22222222-2222-2222-2222-222222222222",
            uuid4(),
        )

        self.assertEqual(suggestions, ())
        self.assertEqual(self.audit.events[-1].outcome, AuditOutcome.FAILED)
        self.assertNotIn("secret", repr(self.audit.events))

    def test_worker_can_cancel_inflight_analysis_before_persistence(self) -> None:
        started = Event()
        release = Event()

        class BlockingAnalyzer:
            def analyze(self, user_text, assistant_text, source_ref, correlation_id):
                started.set()
                release.wait(timeout=1)
                return (
                    AutomaticMemorySuggestion(
                        FactPayload(
                            "synthetic cancelled subject",
                            "synthetic cancelled statement",
                        ),
                        Sensitivity.NORMAL,
                        MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
                        Scope(ScopeType.GLOBAL),
                        source_ref,
                        "synthetic-model-v1",
                    ),
                )

        worker = PostResponseMemoryWorker(
            BlockingAnalyzer(),
            self.coordinator,
            audit_sink=self.audit,
        )
        self.assertTrue(worker.submit("user", "assistant"))
        self.assertTrue(started.wait(timeout=1))
        self.assertTrue(worker.submit("queued user", "queued assistant"))
        self.assertFalse(worker.submit("skipped user", "skipped assistant"))
        self.assertEqual(self.audit.events[-1].outcome, AuditOutcome.SKIPPED)
        closer = Thread(target=worker.close)
        closer.start()
        self.assertTrue(closer.is_alive())
        release.set()
        closer.join(timeout=1)
        self.assertFalse(closer.is_alive())
        self.assertEqual(self.repository.list_candidates(uuid4()), ())
        self.assertFalse(worker.submit("later user", "later assistant"))
        self.assertEqual(self.audit.events[-1].outcome, AuditOutcome.CANCELLED)

    def test_worker_idle_wait_tracks_accepted_turn_to_completion(self) -> None:
        started = Event()
        release = Event()

        class BlockingEmptyAnalyzer:
            def analyze(self, user_text, assistant_text, source_ref, correlation_id):
                started.set()
                release.wait(timeout=1)
                return ()

        worker = PostResponseMemoryWorker(
            BlockingEmptyAnalyzer(),
            self.coordinator,
            audit_sink=self.audit,
        )

        self.assertTrue(worker.submit("user", "assistant"))
        self.assertTrue(started.wait(timeout=1))
        self.assertFalse(worker.wait_until_idle(0))
        release.set()
        self.assertTrue(worker.wait_until_idle(1))
        worker.close()

    def test_clear_capture_does_not_wait_for_background_model_analysis(self) -> None:
        started = Event()
        release = Event()

        class BlockingEmptyAnalyzer:
            @staticmethod
            def analyze(user_text, assistant_text, source_ref, correlation_id):
                started.set()
                release.wait(timeout=1)
                return ()

        worker = PostResponseMemoryWorker(
            BlockingEmptyAnalyzer(),
            self.coordinator,
            audit_sink=self.audit,
        )
        self.assertTrue(worker.submit("background turn", "assistant response"))
        self.assertTrue(started.wait(timeout=1))

        notices = worker.capture_before_response("My name is Synthetic Person.")
        recalled = self.repository.retrieve(
            RetrievalRequest("my name", mode=RetrievalMode.APPROVED),
            uuid4(),
        )
        release.set()
        worker.close()

        assert notices is not None
        self.assertIn("Memory updated:", notices[0])
        self.assertEqual(len(recalled.memories), 1)

    def test_clear_context_phrase_creates_scope_and_retrieves_only_in_context(self) -> None:
        class EmptyAnalyzer:
            @staticmethod
            def analyze(user_text, assistant_text, source_ref, correlation_id):
                return ()

        worker = PostResponseMemoryWorker(
            EmptyAnalyzer(),
            self.coordinator,
            audit_sink=self.audit,
        )

        notices = worker.capture_before_response(
            "At work, I prefer synthetic quiet time."
        )
        outside = self.repository.retrieve(
            RetrievalRequest(
                "synthetic quiet time",
                mode=RetrievalMode.APPROVED,
            ),
            uuid4(),
        )
        scopes = self.repository.match_named_scopes(
            "At work, what do I prefer about synthetic quiet time?",
            uuid4(),
        )
        inside = self.repository.retrieve(
            RetrievalRequest(
                "synthetic quiet time",
                scopes=scopes,
                mode=RetrievalMode.APPROVED,
            ),
            uuid4(),
        )
        worker.close()

        self.assertIsNotNone(notices)
        self.assertEqual(outside.memories, ())
        self.assertEqual(len(scopes), 1)
        self.assertEqual(len(inside.memories), 1)

    def test_ambiguous_context_is_not_silently_saved_as_global(self) -> None:
        class EmptyAnalyzer:
            @staticmethod
            def analyze(user_text, assistant_text, source_ref, correlation_id):
                return ()

        worker = PostResponseMemoryWorker(
            EmptyAnalyzer(),
            self.coordinator,
            audit_sink=self.audit,
        )

        notices = worker.capture_before_response(
            "I prefer synthetic quiet time when I am at work."
        )
        recalled = self.repository.retrieve(
            RetrievalRequest(
                "synthetic quiet time",
                mode=RetrievalMode.APPROVED,
            ),
            uuid4(),
        )
        worker.close()

        self.assertIsNotNone(notices)
        self.assertIn("context-specific", notices[0])
        self.assertEqual(recalled.memories, ())

    def test_worker_promotes_only_exact_direct_user_evidence(self) -> None:
        completed = Event()
        user_text = "My name is Synthetic Worker Person."

        class EvidenceAnalyzer:
            def analyze(self, user_text, assistant_text, source_ref, correlation_id):
                return (
                    AutomaticMemorySuggestion(
                        FactPayload("model subject", "model paraphrase"),
                        Sensitivity.NORMAL,
                        MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
                        Scope(ScopeType.GLOBAL),
                        source_ref,
                        "synthetic-model-v1",
                        user_text,
                    ),
                )

        class SignalingCoordinator(MemoryCaptureCoordinator):
            def process_suggestion_batch(self, *args, **kwargs):
                try:
                    return super().process_suggestion_batch(*args, **kwargs)
                finally:
                    completed.set()

        coordinator = SignalingCoordinator(self.repository, self.audit)
        worker = PostResponseMemoryWorker(
            EvidenceAnalyzer(),
            coordinator,
            audit_sink=self.audit,
        )

        self.assertTrue(worker.submit(user_text, "Synthetic response."))
        self.assertTrue(completed.wait(timeout=1))
        worker.close()

        recalled = self.repository.retrieve(
            RetrievalRequest("my name", mode=RetrievalMode.APPROVED),
            uuid4(),
        )
        self.assertEqual(len(recalled.memories), 1)
        payload = recalled.memories[0].record.revision.payload
        assert isinstance(payload, FactPayload)
        self.assertEqual(payload.statement, user_text)

    def test_clear_statement_is_committed_before_response_with_topic_notice(self) -> None:
        user_text = "I have a synthetic gluten sensitivity."

        class EvidenceAnalyzer:
            calls = 0

            def analyze(self, user_text, assistant_text, source_ref, correlation_id):
                self.calls += 1
                return (
                    AutomaticMemorySuggestion(
                        FactPayload("model subject", "model paraphrase"),
                        Sensitivity.PERSONAL,
                        MentionPolicy.ASK_BEFORE_MENTIONING,
                        Scope(ScopeType.GLOBAL),
                        source_ref,
                        "synthetic-model-v1",
                        user_text,
                    ),
                )

        analyzer = EvidenceAnalyzer()
        worker = PostResponseMemoryWorker(
            analyzer,
            self.coordinator,
            audit_sink=self.audit,
        )

        notices = worker.capture_before_response(user_text)
        recalled = self.repository.retrieve(
            RetrievalRequest(
                "Do I have gut sensitivities?",
                mode=RetrievalMode.DIRECT,
            ),
            uuid4(),
        )
        worker.close()

        self.assertEqual(analyzer.calls, 0)
        self.assertEqual(
            notices,
            ("Memory updated: digestive health and sensitivity or allergy.",),
        )
        self.assertEqual(len(recalled.memories), 1)

    def test_clear_statement_does_not_depend_on_analyzer_output(self) -> None:
        class FailingAnalyzer:
            @staticmethod
            def analyze(user_text, assistant_text, source_ref, correlation_id):
                raise AssertionError("clear exact capture must not call the model")

        worker = PostResponseMemoryWorker(
            FailingAnalyzer(),
            self.coordinator,
            audit_sink=self.audit,
        )

        notices = worker.capture_before_response("My name is Synthetic Person.")
        worker.close()

        assert notices is not None
        self.assertIn("Memory updated: personal fact.", notices[0])
        recalled = self.repository.retrieve(
            RetrievalRequest("my name", mode=RetrievalMode.APPROVED),
            uuid4(),
        )
        self.assertEqual(len(recalled.memories), 1)

    def test_uncertain_statement_gets_immediate_clarification_without_save(self) -> None:
        class FailingAnalyzer:
            @staticmethod
            def analyze(user_text, assistant_text, source_ref, correlation_id):
                raise AssertionError("uncertain text must not call the model")

        worker = PostResponseMemoryWorker(
            FailingAnalyzer(),
            self.coordinator,
            audit_sink=self.audit,
        )

        notices = worker.capture_before_response(
            "I think I have a synthetic gluten sensitivity."
        )
        worker.close()

        assert notices is not None
        self.assertIn("Memory needs clarification:", notices[0])
        self.assertIn("sounded uncertain", notices[0])
        self.assertEqual(
            self.repository.retrieve(
                RetrievalRequest(
                    "Do I have gut sensitivities?",
                    mode=RetrievalMode.DIRECT,
                ),
                uuid4(),
            ).memories,
            (),
        )

    def test_contradictory_clear_statement_asks_before_overwriting(self) -> None:
        class ExactEvidenceAnalyzer:
            @staticmethod
            def analyze(user_text, assistant_text, source_ref, correlation_id):
                return (
                    AutomaticMemorySuggestion(
                        FactPayload("model subject", "model paraphrase"),
                        Sensitivity.PERSONAL,
                        MentionPolicy.ASK_BEFORE_MENTIONING,
                        Scope(ScopeType.GLOBAL),
                        source_ref,
                        "synthetic-model-v1",
                        user_text,
                    ),
                )

        worker = PostResponseMemoryWorker(
            ExactEvidenceAnalyzer(),
            self.coordinator,
            audit_sink=self.audit,
        )
        first = worker.capture_before_response(
            "I have a synthetic gluten sensitivity."
        )

        second = worker.capture_before_response(
            "I do not have a synthetic gluten sensitivity."
        )
        worker.close()

        assert first is not None and second is not None
        self.assertIn("Memory updated:", first[0])
        self.assertIn("Memory needs clarification:", second[0])
        self.assertIn("did not overwrite", second[0])


if __name__ == "__main__":
    unittest.main()
