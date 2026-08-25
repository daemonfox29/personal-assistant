"""Composition tests for the UI-facing application boundary."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from personal_assistant.application_service import (
    ApplicationLaunchState,
    ApplicationOpenError,
    ApplicationSetupError,
    AssistantApplicationFactory,
)
from personal_assistant.config import AppSettings, MemorySettings
from personal_assistant.model import ModelRequest, ModelResponse


RECOVERY = "synthetic application recovery"
PASSCODE = "synthetic-application-2468"


class SyntheticModel:
    def warm_up(self) -> None:
        pass

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse("synthetic response")


class ApplicationServiceTests(unittest.TestCase):
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
