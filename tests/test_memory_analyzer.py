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


if __name__ == "__main__":
    unittest.main()
