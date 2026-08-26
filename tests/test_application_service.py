"""Composition tests for the UI-facing application boundary."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from personal_assistant.audit import AuditWriteError
from personal_assistant.application_service import (
    ApplicationLaunchState,
    ApplicationOpenError,
    ApplicationRecoveryRequired,
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
