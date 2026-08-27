"""Composition tests for the UI-facing application boundary."""

import json
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from uuid import uuid4

from personal_assistant.audit import AuditWriteError
from personal_assistant.application_service import (
    ApplicationLaunchState,
    ApplicationOpenError,
    ApplicationRecoveryRequired,
    ApplicationSettingsError,
    ApplicationSetupError,
    AssistantApplicationFactory,
    MemorySourceUnavailableError,
)
from personal_assistant.config import AppSettings, MemorySettings
from personal_assistant.conversation_history import (
    ConversationResponseMessage,
    ConversationRole,
)
from personal_assistant.memory_types import (
    ActorType,
    FactPayload,
    InsightConfidence,
    InsightPayload,
    MentionPolicy,
    PreferencePayload,
    Provenance,
    RecordDraft,
    RecordStatus,
    Scope,
    ScopeType,
    Sensitivity,
    SourceType,
)
from personal_assistant.model import ModelRequest, ModelResponse
from personal_assistant.runtime_preferences import (
    RuntimePreferences,
    RuntimePreferencesStore,
)


RECOVERY = "synthetic application recovery"
PASSCODE = "synthetic-application-2468"


class SyntheticModel:
    def __init__(self) -> None:
        self.requests: list[ModelRequest] = []

    def warm_up(self) -> None:
        pass

    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse("synthetic response")


class SyntheticObservationModel(SyntheticModel):
    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.messages[0].content.startswith(
            "Identify zero to three durable user-memory suggestions."
        ):
            return ModelResponse(
                json.dumps(
                    [
                        {
                            "type": "observation",
                            "subject": "synthetic interruptions",
                            "content": (
                                "Synthetic interruptions may be draining in "
                                "some recent situations"
                            ),
                            "evidence_quote": "",
                            "sensitivity": "personal",
                            "mention_policy": "ask_before_mentioning",
                        }
                    ]
                )
            )
        return ModelResponse("synthetic response")


class SyntheticRecoveryStore:
    def __init__(self, recovery: str | None = None) -> None:
        self.recovery = recovery
        self.writes: list[str] = []
        self.deletes = 0

    def read_recovery(self) -> str | None:
        return self.recovery

    def write_recovery(self, recovery_passphrase: str) -> None:
        self.recovery = recovery_passphrase
        self.writes.append(recovery_passphrase)

    def delete_recovery(self) -> None:
        self.recovery = None
        self.deletes += 1


class ApplicationServiceTests(unittest.TestCase):
    def test_communication_style_persists_and_applies_as_style_only_data(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            first_model = SyntheticModel()
            style = "Be warm, direct, and use short paragraphs."
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=first_model,
            ):
                service = factory.open(RECOVERY)
                service.save_communication_style(style)
                tuple(service.iter_events("Synthetic first style request"))
                first_system = next(
                    request.messages[0].content
                    for request in first_model.requests
                    if style in request.messages[0].content
                )
                self.assertIn(style, first_system)
                self.assertIn("may adjust only tone", first_system)
                self.assertIn("cannot change safety rules", first_system)
                service.close()

            second_model = SyntheticModel()
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=second_model,
            ):
                reopened = factory.open(RECOVERY)
                self.assertEqual(reopened.communication_style, style)
                tuple(reopened.iter_events("Synthetic reopened style request"))
                self.assertTrue(
                    any(
                        style in request.messages[0].content
                        for request in second_model.requests
                    )
                )
                reopened.close()

    def test_memory_inventory_opens_exact_source_and_reports_deleted_chat(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(RECOVERY)
                tuple(
                    service.iter_events(
                        "My name is Synthetic Source Person."
                    )
                )
                inventory = service.list_memories()
                self.assertEqual(len(inventory), 1)
                self.assertIn("Synthetic Source Person", inventory[0].value)

                source = service.open_memory_source(inventory[0].record_id)
                source_message = next(
                    message
                    for message in source.conversation.messages
                    if message.sequence == source.source_sequence
                )
                self.assertEqual(
                    source_message.content,
                    "My name is Synthetic Source Person.",
                )

                service.delete_conversation(
                    source.conversation.summary.conversation_id
                )
                with self.assertRaisesRegex(
                    MemorySourceUnavailableError,
                    "deleted, the exact message is no longer available",
                ):
                    service.open_memory_source(inventory[0].record_id)
                service.close()

    def test_candidate_review_lists_related_memory_and_applies_correction(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(RECOVERY)
                runtime = service._runtime
                self.assertIsNotNone(runtime)
                target = runtime.repository.create_record(  # type: ignore[union-attr]
                    RecordDraft(
                        PreferencePayload(
                            "synthetic schedule",
                            "I prefer synthetic mornings.",
                        ),
                        RecordStatus.CONFIRMED,
                        Sensitivity.PERSONAL,
                        MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
                        Scope(ScopeType.GLOBAL),
                    ),
                    Provenance(
                        SourceType.TRUSTED_INTERFACE,
                        "synthetic-review-target",
                        ActorType.USER,
                    ),
                    uuid4(),
                )
                candidate = runtime.repository.create_record(  # type: ignore[union-attr]
                    RecordDraft(
                        PreferencePayload(
                            "synthetic schedule",
                            "I may prefer synthetic evenings.",
                        ),
                        RecordStatus.CANDIDATE,
                        Sensitivity.PERSONAL,
                        MentionPolicy.ASK_BEFORE_MENTIONING,
                        Scope(ScopeType.GLOBAL),
                    ),
                    Provenance(
                        SourceType.MODEL_CANDIDATE,
                        "turn:88888888-8888-8888-8888-888888888888",
                        ActorType.MODEL_CANDIDATE,
                        "synthetic-model-v1",
                    ),
                    uuid4(),
                )

                review = service.list_memory_candidates()

                self.assertEqual(len(review), 1)
                self.assertEqual(review[0].record_id, candidate.record_id)
                self.assertEqual(review[0].related_confirmed[0].record_id, target.record_id)
                service.reconcile_memory_candidate(
                    candidate.record_id,
                    candidate.row_version,
                    target.record_id,
                    target.row_version,
                    "I prefer synthetic evenings.",
                    "correct",
                )
                self.assertEqual(service.list_memory_candidates(), ())
                corrected = runtime.repository.inspect_record(  # type: ignore[union-attr]
                    target.record_id,
                    uuid4(),
                )
                consumed = runtime.repository.inspect_record(  # type: ignore[union-attr]
                    candidate.record_id,
                    uuid4(),
                )
                self.assertEqual(
                    corrected.revision.payload.preference,  # type: ignore[union-attr]
                    "I prefer synthetic evenings.",
                )
                self.assertEqual(consumed.status, RecordStatus.SUPERSEDED)
                service.close()

    def test_sensitive_candidate_is_redacted_until_passcode_review(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(RECOVERY)
                runtime = service._runtime
                self.assertIsNotNone(runtime)
                candidate = runtime.repository.create_record(  # type: ignore[union-attr]
                    RecordDraft(
                        FactPayload(
                            "synthetic protected topic",
                            "Synthetic protected candidate content.",
                        ),
                        RecordStatus.CANDIDATE,
                        Sensitivity.SENSITIVE,
                        MentionPolicy.ASK_BEFORE_MENTIONING,
                        Scope(ScopeType.GLOBAL),
                    ),
                    Provenance(
                        SourceType.MODEL_CANDIDATE,
                        "turn:77777777-7777-7777-7777-777777777777",
                        ActorType.MODEL_CANDIDATE,
                        "synthetic-model-v1",
                    ),
                    uuid4(),
                )

                listed = service.list_memory_candidates()[0]

                self.assertTrue(listed.locked)
                self.assertNotIn("protected candidate content", listed.value)
                revealed = service.unlock_memory_candidate(
                    candidate.record_id,
                    PASSCODE,
                )
                self.assertFalse(revealed.locked)
                self.assertIn("protected candidate content", revealed.value)
                service.confirm_memory_candidate(
                    candidate.record_id,
                    candidate.row_version,
                    revealed.value,
                    high_risk_passcode=PASSCODE,
                )
                confirmed = runtime.repository.inspect_record(  # type: ignore[union-attr]
                    candidate.record_id,
                    uuid4(),
                )
                self.assertEqual(confirmed.status, RecordStatus.CONFIRMED)
                service.close()

    def test_legacy_memory_opens_only_one_verbatim_saved_message(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(RECOVERY)
                exact_text = "My synthetic legacy location is Denver."
                history = service._conversation_history
                runtime = service._runtime
                self.assertIsNotNone(history)
                self.assertIsNotNone(runtime)
                reference = history.begin_turn_with_reference(  # type: ignore[union-attr]
                    None,
                    f"Please remember that {exact_text}",
                    uuid4(),
                )
                history.finish_turn(  # type: ignore[union-attr]
                    reference.conversation_id,
                    (
                        ConversationResponseMessage(
                            ConversationRole.ASSISTANT,
                            "Synthetic response",
                        ),
                    ),
                    uuid4(),
                )
                record = runtime.repository.create_record(  # type: ignore[union-attr]
                    RecordDraft(
                        FactPayload("synthetic legacy location", exact_text),
                        RecordStatus.CONFIRMED,
                        Sensitivity.NORMAL,
                        MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
                        Scope(ScopeType.GLOBAL),
                    ),
                    Provenance(
                        SourceType.EXPLICIT_USER,
                        f"turn:{uuid4()}",
                        ActorType.USER,
                    ),
                    uuid4(),
                )

                source = service.open_memory_source(record.record_id)

                self.assertEqual(
                    source.conversation.summary.conversation_id,
                    reference.conversation_id,
                )
                duplicate = history.begin_turn_with_reference(  # type: ignore[union-attr]
                    None,
                    f"A duplicate repeats {exact_text}",
                    uuid4(),
                )
                history.finish_turn(  # type: ignore[union-attr]
                    duplicate.conversation_id,
                    (
                        ConversationResponseMessage(
                            ConversationRole.ASSISTANT,
                            "Synthetic response",
                        ),
                    ),
                    uuid4(),
                )
                with self.assertRaisesRegex(
                    MemorySourceUnavailableError,
                    "multiple saved messages",
                ):
                    service.open_memory_source(record.record_id)
                imported = runtime.repository.create_record(  # type: ignore[union-attr]
                    RecordDraft(
                        FactPayload("synthetic imported location", exact_text),
                        RecordStatus.CONFIRMED,
                        Sensitivity.NORMAL,
                        MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
                        Scope(ScopeType.GLOBAL),
                    ),
                    Provenance(
                        SourceType.TRUSTED_INTERFACE,
                        "settings-import",
                        ActorType.USER,
                    ),
                    uuid4(),
                )
                with self.assertRaisesRegex(
                    MemorySourceUnavailableError,
                    "trusted import or administrative action",
                ):
                    service.open_memory_source(imported.record_id)
                service.close()

    def test_settings_delete_soft_deletes_memory_from_inventory(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(RECOVERY)
                tuple(service.iter_events("My dog is Synthetic Table Scooby."))
                memory = service.list_memories()[0]

                service.delete_memory(memory.record_id)

                self.assertEqual(service.list_memories(), ())
                history = service._runtime.repository.get_record_history(
                    memory.record_id,
                    uuid4(),
                )
                self.assertEqual(history[-1].status.value, "deleted")
                service.close()

    def test_memory_inventory_is_canonical_and_excludes_raw_fact_candidates(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(RECOVERY)
                runtime = service._runtime
                self.assertIsNotNone(runtime)
                confirmed = Provenance(
                    SourceType.TRUSTED_INTERFACE,
                    "synthetic-inventory",
                    ActorType.SYSTEM,
                )
                candidate = Provenance(
                    SourceType.MODEL_CANDIDATE,
                    "turn:99999999-9999-9999-9999-999999999999",
                    ActorType.MODEL_CANDIDATE,
                    "synthetic-model-v1",
                )

                def create(payload, status, provenance):  # type: ignore[no-untyped-def]
                    return runtime.repository.create_record(  # type: ignore[union-attr]
                        RecordDraft(
                            payload,
                            status,
                            Sensitivity.PERSONAL,
                            MentionPolicy.ASK_BEFORE_MENTIONING,
                            Scope(ScopeType.GLOBAL),
                        ),
                        provenance,
                        uuid4(),
                    )

                create(
                    FactPayload(
                        "direct-statement:first",
                        "My name is Synthetic Inventory Person.",
                    ),
                    RecordStatus.CONFIRMED,
                    confirmed,
                )
                create(
                    FactPayload(
                        "direct-statement:duplicate",
                        "my name is synthetic inventory person",
                    ),
                    RecordStatus.CONFIRMED,
                    confirmed,
                )
                create(
                    FactPayload(
                        "direct-statement:question",
                        "have I ever lived in chicago",
                    ),
                    RecordStatus.CONFIRMED,
                    confirmed,
                )
                create(
                    FactPayload(
                        "model-background",
                        "The capital of New Jersey is Trenton.",
                    ),
                    RecordStatus.CANDIDATE,
                    candidate,
                )
                observed_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
                create(
                    InsightPayload(
                        "Synthetic schedule changes may feel draining",
                        InsightConfidence.LOW,
                        "Only one synthetic situation was considered",
                        observed_at,
                        observed_at,
                    ),
                    RecordStatus.CANDIDATE,
                    candidate,
                )

                inventory = service.list_memories()

                self.assertEqual(len(inventory), 2)
                values = tuple(item.value.casefold() for item in inventory)
                self.assertEqual(
                    sum("synthetic inventory person" in value for value in values),
                    1,
                )
                self.assertTrue(
                    any("schedule changes" in value for value in values)
                )
                self.assertFalse(any("chicago" in value for value in values))
                self.assertFalse(any("capital" in value for value in values))
                service.close()

    def test_memory_inventory_rejects_a_malformed_page_cursor(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(RECOVERY)

                with self.assertRaisesRegex(
                    ApplicationOpenError,
                    "could not be listed safely",
                ):
                    service.list_memories_page("not-valid-json")
                service.close()

    def test_tentative_observation_links_to_the_exact_completed_chat_message(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticObservationModel(),
            ):
                service = factory.open(RECOVERY)
                original = "Lately synthetic interruptions have felt draining."
                tuple(service.iter_events(original))
                service.new_conversation()
                tuple(
                    service.iter_events(
                        "How have synthetic interruptions affected me?"
                    )
                )
                observation = next(
                    item
                    for item in service.list_memories()
                    if item.kind == "insight"
                )

                source = service.open_memory_source(observation.record_id)

                self.assertEqual(
                    next(
                        message.content
                        for message in source.conversation.messages
                        if message.sequence == source.source_sequence
                    ),
                    original,
                )
                service.close()
    def test_new_chat_receives_tentative_observation_without_overwriting_fact(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            model = SyntheticObservationModel()
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=model,
            ):
                service = factory.open(RECOVERY)
                tuple(
                    service.iter_events(
                        "I usually do not mind synthetic interruptions."
                    )
                )
                service.new_conversation()
                tuple(
                    service.iter_events(
                        "Lately synthetic interruptions have felt draining."
                    )
                )
                service.new_conversation()
                tuple(
                    service.iter_events(
                        "How have synthetic interruptions been affecting me?"
                    )
                )
                service.close()

            ordinary_requests = [
                request
                for request in model.requests
                if not request.messages[0].content.startswith(
                    "Identify zero to three durable user-memory suggestions."
                )
            ]
            system_context = ordinary_requests[-1].messages[0].content
            self.assertIn('"memories":[', system_context)
            self.assertIn("usually do not mind", system_context)
            self.assertIn('"tentative_observations":[', system_context)
            self.assertIn("may be draining", system_context)
            self.assertIn("may be limited to one situation", system_context)
            self.assertIn("Never silently overwrite", system_context)

    def test_reopened_old_chat_receives_newer_global_memory_as_canonical(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            # This model cannot produce memory-analysis JSON. Clear exact facts
            # must still commit synchronously without depending on model output.
            model = SyntheticModel()
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=model,
            ):
                service = factory.open(RECOVERY)
                tuple(
                    service.iter_events(
                        "My favorite synthetic color is blue."
                    )
                )
                old_chat_id = service.active_conversation_id
                assert old_chat_id is not None
                service.new_conversation()
                tuple(
                    service.iter_events(
                        "My favorite synthetic color is green."
                    )
                )
                service.open_conversation(old_chat_id)
                tuple(
                    service.iter_events(
                        "What is my favorite synthetic color?"
                    )
                )
                service.close()

            ordinary_requests = [
                request
                for request in model.requests
                if not request.messages[0].content.startswith(
                    "Identify zero to three durable user-memory suggestions."
                )
            ]
            reopened_request = ordinary_requests[-1]
            system_context = reopened_request.messages[0].content
            self.assertLess(
                system_context.index("green"),
                system_context.index("blue"),
            )
            self.assertIn(
                "Confirmed memory also overrides conflicting details in earlier "
                "chat turns",
                system_context,
            )
            self.assertEqual(
                reopened_request.messages[1].content,
                "My favorite synthetic color is blue.",
            )

    def test_explicit_recall_search_supplies_prior_chat_to_new_chat(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            model = SyntheticModel()
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=model,
            ):
                service = factory.open(RECOVERY)
                tuple(
                    service.iter_events(
                        "We planned the synthetic cobalt garden launch."
                    )
                )
                service.new_conversation()
                tuple(
                    service.iter_events(
                        "What did we talk about the last time I had this app open?"
                    )
                )
                service.new_conversation()
                tuple(
                    service.iter_events(
                        "Remember when we talked about the cobalt garden? "
                        "Let's continue that here."
                    )
                )
                service.new_conversation()
                tuple(service.iter_events("Continue where we left off."))
                service.new_conversation()
                tuple(
                    service.iter_events(
                        "Have we discussed the cobalt garden before?"
                    )
                )
                service.close()

            ordinary_requests = [
                request
                for request in model.requests
                if not request.messages[0].content.startswith(
                    "Identify zero to three durable user-memory suggestions."
                )
            ]
            system_text = ordinary_requests[1].messages[0].content
            self.assertIn("conversation_matches", system_text)
            self.assertIn(
                "We planned the synthetic cobalt garden launch.",
                system_text,
            )
            self.assertIn("untrusted data", system_text)
            topical_system_text = ordinary_requests[2].messages[0].content
            self.assertIn(
                "We planned the synthetic cobalt garden launch.",
                topical_system_text,
            )
            latest_system_text = ordinary_requests[3].messages[0].content
            self.assertIn(
                "Remember when we talked about the cobalt garden?",
                latest_system_text,
            )
            natural_recall_system_text = ordinary_requests[4].messages[0].content
            self.assertIn(
                "We planned the synthetic cobalt garden launch.",
                natural_recall_system_text,
            )

    def test_ordinary_new_chat_does_not_search_prior_transcripts(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            model = SyntheticModel()
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=model,
            ):
                service = factory.open(RECOVERY)
                tuple(service.iter_events("Synthetic private transcript marker."))
                service.new_conversation()
                tuple(service.iter_events("What should I do today?"))
                service.close()

            ordinary_requests = [
                request
                for request in model.requests
                if not request.messages[0].content.startswith(
                    "Identify zero to three durable user-memory suggestions."
                )
            ]
            self.assertNotIn(
                "Synthetic private transcript marker.",
                ordinary_requests[1].messages[0].content,
            )

    def test_new_chat_receives_confirmed_memory_from_preceding_chat(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            model = SyntheticModel()
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=model,
            ):
                service = factory.open(RECOVERY)
                tuple(service.iter_events("My dog is named Synthetic Scooby."))
                service.new_conversation()
                tuple(service.iter_events("What was the fact I just told you?"))
                service.close()

            ordinary_requests = [
                request
                for request in model.requests
                if not request.messages[0].content.startswith(
                    "Identify zero to three durable user-memory suggestions."
                )
            ]
            second_contents = tuple(
                message.content for message in ordinary_requests[1].messages
            )
            self.assertTrue(
                any(
                    "My dog is named Synthetic Scooby." in content
                    for content in second_contents
                )
            )

    def test_saved_conversation_reopens_and_continues_with_bounded_roles(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            first_model = SyntheticModel()
            second_model = SyntheticModel()
            with patch(
                "personal_assistant.application_service.OllamaModel",
                side_effect=(first_model, second_model),
            ):
                first = factory.open(RECOVERY)
                tuple(first.iter_events("My dog is Scooby"))
                summaries = first.list_conversations()
                first.close()

                second = factory.open(RECOVERY)
                reopened = second.open_conversation(
                    summaries[0].conversation_id
                )
                tuple(second.iter_events("What is my dog's name?"))
                second.close()

            self.assertEqual(reopened.messages[0].content, "My dog is Scooby")
            second_chat_requests = [
                request
                for request in second_model.requests
                if not request.messages[0].content.startswith(
                    "Identify zero to three durable user-memory suggestions."
                )
            ]
            request_contents = [
                message.content for message in second_chat_requests[0].messages
            ]
            self.assertIn("My dog is Scooby", request_contents)
            self.assertIn("synthetic response", request_contents)
            first_chat_requests = [
                request
                for request in first_model.requests
                if not request.messages[0].content.startswith(
                    "Identify zero to three durable user-memory suggestions."
                )
            ]
            self.assertEqual(
                first_chat_requests[0].messages[-1].content,
                "My dog is Scooby",
            )

    def test_private_chat_does_not_create_saved_conversation(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(RECOVERY)
                service.new_conversation(private=True)
                tuple(service.iter_events("Do not save this"))
                conversations = service.list_conversations()
                service.close()

            self.assertEqual(conversations, ())

    def test_runtime_preferences_are_persisted_and_audited(self) -> None:
        with TemporaryDirectory() as directory:
            data_directory = Path(directory) / "private"
            factory = AssistantApplicationFactory(
                AppSettings(memory=MemorySettings(data_directory=data_directory))
            )
            preferences = RuntimePreferences(
                context_tokens=32_768,
                default_response_tokens=800,
                maximum_response_tokens=1_600,
            )

            factory.save_runtime_preferences(preferences)

            self.assertEqual(factory.runtime_preferences, preferences)
            self.assertEqual(
                RuntimePreferencesStore(
                    data_directory / "preferences.json"
                ).load(),
                preferences,
            )
            audit = (data_directory / "audit.jsonl").read_text(encoding="utf-8")
            self.assertIn('"operation":"configuration_update"', audit)
            self.assertIn('"context_tokens":32768', audit)

    def test_audit_failure_rolls_back_runtime_preferences(self) -> None:
        with TemporaryDirectory() as directory:
            data_directory = Path(directory) / "private"
            factory = AssistantApplicationFactory(
                AppSettings(memory=MemorySettings(data_directory=data_directory))
            )

            with patch.object(
                factory,
                "_audit_runtime_preferences",
                side_effect=(None, AuditWriteError("synthetic audit failure")),
            ):
                with self.assertRaises(ApplicationSettingsError):
                    factory.save_runtime_preferences(
                        RuntimePreferences(context_tokens=32_768)
                    )

            self.assertIsNone(
                RuntimePreferencesStore(
                    data_directory / "preferences.json"
                ).load()
            )

    def test_setup_reports_only_whitelisted_actionable_input_errors(self) -> None:
        cases = (
            (
                (RECOVERY, "different recovery", PASSCODE, PASSCODE),
                "The recovery passphrase entries do not match. Re-enter both.",
            ),
            (
                ("too short", "too short", PASSCODE, PASSCODE),
                "The recovery passphrase must contain at least 12 characters.",
            ),
            (
                (RECOVERY, RECOVERY, "short", "short"),
                "The high-risk passcode must contain at least 8 characters.",
            ),
            (
                (RECOVERY, RECOVERY, PASSCODE, "different passcode"),
                "The high-risk passcode entries do not match. Re-enter both.",
            ),
            (
                (RECOVERY, RECOVERY, RECOVERY, RECOVERY),
                (
                    "The recovery passphrase and high-risk passcode must be "
                    "different."
                ),
            ),
        )
        for secrets, expected in cases:
            with self.subTest(expected=expected), TemporaryDirectory() as directory:
                settings = AppSettings(
                    memory=MemorySettings(data_directory=Path(directory) / "private")
                )
                factory = AssistantApplicationFactory(settings)

                with self.assertRaises(ApplicationSetupError) as raised:
                    factory.setup(*secrets)

                self.assertEqual(str(raised.exception), expected)

    def test_failed_setup_removes_new_security_and_database_files(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            data_directory = Path(temporary_directory) / "private"
            settings = AppSettings(
                memory=MemorySettings(data_directory=data_directory)
            )
            factory = AssistantApplicationFactory(settings)

            with patch(
                "personal_assistant.application_service.MemoryRuntime.open",
                side_effect=RuntimeError("synthetic private failure"),
            ):
                with self.assertRaises(ApplicationSetupError) as raised:
                    factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)

            self.assertNotIn("synthetic private failure", str(raised.exception))
            self.assertFalse((data_directory / "security.json").exists())
            self.assertFalse((data_directory / "memory.db").exists())

    def test_failed_unlock_does_not_load_model(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            self.assertEqual(
                factory.launch_state(),
                ApplicationLaunchState.UNLOCK_REQUIRED,
            )

            with patch(
                "personal_assistant.application_service.OllamaModel"
            ) as model_type:
                with self.assertRaises(ApplicationOpenError):
                    factory.open("incorrect synthetic recovery")

            model_type.assert_not_called()

    def test_verified_manual_unlock_enrolls_then_uses_automatic_unlock(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            store = SyntheticRecoveryStore()
            factory = AssistantApplicationFactory(
                settings,
                recovery_store=store,
            )
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            self.assertEqual(
                factory.launch_state(),
                ApplicationLaunchState.AUTOMATIC_UNLOCK,
            )

            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                first = factory.open(RECOVERY)
                first.close()
                second = factory.open()
                second.close()

            self.assertEqual(store.writes, [RECOVERY])
            self.assertEqual(store.recovery, RECOVERY)
            audit_text = (settings.memory.data_directory / "audit.jsonl").read_text(
                encoding="utf-8"
            )
            self.assertIn('"operation":"credential_access"', audit_text)
            self.assertIn("automatic_unlock_write", audit_text)
            self.assertIn("automatic_unlock_read", audit_text)
            self.assertNotIn(RECOVERY, audit_text)

    def test_missing_or_stale_automatic_secret_requires_manual_recovery(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            manual_factory = AssistantApplicationFactory(settings)
            manual_factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)

            for stored_recovery, expected_deletes in (
                (None, 0),
                ("incorrect synthetic recovery", 1),
            ):
                with self.subTest(stored_recovery=stored_recovery):
                    store = SyntheticRecoveryStore(stored_recovery)
                    factory = AssistantApplicationFactory(
                        settings,
                        recovery_store=store,
                    )
                    with patch(
                        "personal_assistant.application_service.OllamaModel"
                    ) as model_type:
                        with self.assertRaises(ApplicationRecoveryRequired):
                            factory.open()

                    self.assertEqual(store.deletes, expected_deletes)
                    model_type.assert_not_called()

    def test_enrollment_audit_failure_removes_automatic_secret(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            store = SyntheticRecoveryStore()
            factory = AssistantApplicationFactory(
                settings,
                recovery_store=store,
            )
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)

            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ), patch.object(
                factory,
                "_audit_credential_access",
                side_effect=(None, AuditWriteError("synthetic audit failure")),
            ):
                with self.assertRaises(ApplicationOpenError):
                    factory.open(RECOVERY)

            self.assertIsNone(store.recovery)
            self.assertEqual(store.deletes, 1)

    def test_missing_database_fails_closed_without_creating_a_replacement(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            database = settings.memory.data_directory / "memory.db"
            database.unlink()

            with patch(
                "personal_assistant.application_service.OllamaModel"
            ) as model_type:
                with self.assertRaises(ApplicationOpenError) as raised:
                    factory.open(RECOVERY)

            self.assertIn("database is missing or unsafe", str(raised.exception))
            self.assertFalse(database.exists())
            model_type.assert_not_called()

    def test_live_backup_configuration_creation_and_audit_view_are_bounded(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            backup_directory = root / "backups"
            backup_directory.mkdir()
            settings = AppSettings(
                memory=MemorySettings(data_directory=root / "private")
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(RECOVERY)
                service.configure_backup_directory(backup_directory)
                factory.save_backup_directory(backup_directory)
                created = service.create_backup()
                overview = service.list_backups()

                self.assertEqual(overview.directory, str(backup_directory))
                self.assertEqual(overview.snapshots[0].snapshot_name, created.snapshot_name)
                self.assertEqual(
                    factory.runtime_preferences.backup_directory,
                    str(backup_directory),
                )
                with self.assertRaisesRegex(ApplicationOpenError, "RESTORE"):
                    service.restore_backup(created.snapshot_name, "restore", PASSCODE)
                with self.assertRaisesRegex(ApplicationOpenError, "unavailable"):
                    service.restore_backup(
                        "memory-20260826T190000Z-" + ("f" * 32) + ".db",
                        "RESTORE",
                        PASSCODE,
                    )

                runtime = service._runtime
                self.assertIsNotNone(runtime)
                runtime.repository.create_record(  # type: ignore[union-attr]
                    RecordDraft(
                        FactPayload(
                            "synthetic post-backup fact",
                            "Synthetic fact created after the selected backup.",
                        ),
                        RecordStatus.CONFIRMED,
                        Sensitivity.NORMAL,
                        MentionPolicy.MAY_MENTION_WHEN_RELEVANT,
                        Scope(ScopeType.GLOBAL),
                    ),
                    Provenance(
                        SourceType.TRUSTED_INTERFACE,
                        "synthetic-post-backup",
                        ActorType.USER,
                    ),
                    uuid4(),
                )
                self.assertTrue(
                    any("created after" in item.value for item in service.list_memories())
                )

                service.restore_backup(created.snapshot_name, "RESTORE", PASSCODE)

                self.assertFalse(
                    any("created after" in item.value for item in service.list_memories())
                )

                audit_page = service.list_audit_events()
                self.assertGreater(len(audit_page.items), 0)
                audit_text = repr(audit_page.items)
                self.assertNotIn(RECOVERY, audit_text)
                self.assertNotIn(str(backup_directory), audit_text)
                with self.assertRaisesRegex(ApplicationOpenError, "cursor"):
                    service.list_audit_events("not-a-cursor")
                service.close()

    def test_session_only_service_exposes_no_authority_objects(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    enabled=False,
                    data_directory=Path(temporary_directory) / "private",
                )
            )
            factory = AssistantApplicationFactory(settings)
            self.assertEqual(factory.launch_state(), ApplicationLaunchState.SESSION_ONLY)
            with patch(
                "personal_assistant.application_service.OllamaModel",
                return_value=SyntheticModel(),
            ):
                service = factory.open(session_only=True)
            try:
                self.assertFalse(service.info.persistent_memory)
                public_names = {name for name in dir(service) if not name.startswith("_")}
                self.assertTrue({"close", "events_for", "info", "iter_events"}.issubset(public_names))
                self.assertTrue(
                    public_names.isdisjoint(
                        {
                            "approval_gate",
                            "audit_sink",
                            "database",
                            "key_provider",
                            "repository",
                        }
                    )
                )
            finally:
                service.close()


if __name__ == "__main__":
    unittest.main()
