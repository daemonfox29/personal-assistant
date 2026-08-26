"""Synthetic tests for post-response quarantined memory analysis."""

import json
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
)
from personal_assistant.memory_capture import MemoryCaptureCoordinator
from personal_assistant.memory_capture import AutomaticMemorySuggestion
from personal_assistant.memory_repository import MemoryRepository, RetrievalRequest
from personal_assistant.migration import MigrationRunner, PackageMigrationSource
from personal_assistant.model import LanguageModel, ModelResponse
from personal_assistant.memory_types import (
    FactPayload,
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

    def test_model_json_becomes_candidate_never_ordinary_memory(self) -> None:
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

        self.assertEqual(len(result.results), 1)
        self.assertEqual(
            self.repository.retrieve(
                RetrievalRequest("Luna rope toys"), uuid4()
            ).memories,
            (),
        )
        request = model.generate.call_args.args[0]
        self.assertEqual(request.max_response_tokens, 400)
        self.assertIn("untrusted data", request.messages[-1].content)

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
        recalled = self.repository.retrieve(RetrievalRequest("my name"), uuid4())
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

    def test_ambiguous_paraphrase_remains_unconfirmed(self) -> None:
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

        self.assertIsNone(suggestions[0].user_evidence)

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
        user_text = "What do you remember about my dog?"
        model = Mock(spec=LanguageModel)
        model.generate.return_value = ModelResponse(
            json.dumps(
                [
                    {
                        "type": "fact",
                        "subject": "model-authored dog subject",
                        "content": "my dog",
                        "evidence_quote": "my dog",
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

        assert result.results[0].record is not None
        self.assertEqual(result.results[0].record.status, RecordStatus.CANDIDATE)

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

        recalled = self.repository.retrieve(RetrievalRequest("my name"), uuid4())
        self.assertEqual(len(recalled.memories), 1)
        payload = recalled.memories[0].record.revision.payload
        assert isinstance(payload, FactPayload)
        self.assertEqual(payload.statement, user_text)


if __name__ == "__main__":
    unittest.main()
