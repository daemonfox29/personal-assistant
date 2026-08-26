"""Composition tests for the UI-facing application boundary."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from personal_assistant.audit import AuditWriteError
from personal_assistant.application_service import (
    ApplicationLaunchState,
    ApplicationOpenError,
    ApplicationRecoveryRequired,
    ApplicationSettingsError,
    ApplicationSetupError,
    AssistantApplicationFactory,
)
from personal_assistant.config import AppSettings, MemorySettings
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


class CrossChatMemoryModel(SyntheticModel):
    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.messages[0].content.startswith(
            "Identify zero to three durable user-memory suggestions."
        ):
            return ModelResponse(
                '[{"type":"fact","subject":"model pet","content":'
                '"The user has a dog called Synthetic Scooby",'
                '"evidence_quote":"","sensitivity":"normal",'
                '"mention_policy":"may_mention_when_relevant"}]'
            )
        return ModelResponse("synthetic response")


class ExactEvidenceMemoryModel(SyntheticModel):
    def generate(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.messages[0].content.startswith(
            "Identify zero to three durable user-memory suggestions."
        ):
            turn = json.loads(request.messages[-1].content.split("\n", 1)[1])
            user_text = turn["user"]
            return ModelResponse(
                json.dumps(
                    [
                        {
                            "type": "fact",
                            "subject": "model-authored synthetic preference",
                            "content": "model-authored synthetic paraphrase",
                            "evidence_quote": user_text,
                            "sensitivity": "normal",
                            "mention_policy": "may_mention_when_relevant",
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
    def test_reopened_old_chat_receives_newer_global_memory_as_canonical(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = AppSettings(
                memory=MemorySettings(
                    data_directory=Path(temporary_directory) / "private"
                )
            )
            factory = AssistantApplicationFactory(settings)
            factory.setup(RECOVERY, RECOVERY, PASSCODE, PASSCODE)
            model = ExactEvidenceMemoryModel()
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
            model = CrossChatMemoryModel()
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
