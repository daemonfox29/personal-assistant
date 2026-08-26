"""Checks for bounded, atomic native runtime preferences."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from personal_assistant.config import load_desktop_settings
from personal_assistant.runtime_preferences import (
    RuntimePreferences,
    RuntimePreferencesError,
    RuntimePreferencesStore,
)


class RuntimePreferencesTests(unittest.TestCase):
    def test_round_trip_is_versioned_and_private(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "private" / "preferences.json"
            store = RuntimePreferencesStore(path)
            preferences = RuntimePreferences(
                context_tokens=32_768,
                default_response_tokens=800,
                maximum_response_tokens=1_600,
            )

            store.save(preferences)

            self.assertEqual(store.load(), preferences)
            self.assertEqual(json.loads(path.read_text())["version"], 1)
            if os.name == "posix":
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_desktop_loader_applies_file_then_environment_override(self) -> None:
        with TemporaryDirectory() as directory:
            data_directory = Path(directory) / "private"
            RuntimePreferencesStore(data_directory / "preferences.json").save(
                RuntimePreferences(
                    context_tokens=32_768,
                    default_response_tokens=700,
                    maximum_response_tokens=1_500,
                )
            )
            environment = {
                "PERSONAL_ASSISTANT_DATA_DIR": str(data_directory),
                "PERSONAL_ASSISTANT_RESPONSE_TOKENS": "900",
            }

            settings = load_desktop_settings(environment)

            self.assertEqual(settings.ollama.context_tokens, 32_768)
            self.assertEqual(settings.ollama.max_response_tokens, 900)
            self.assertEqual(settings.chat.maximum_response_tokens, 1_500)

    def test_invalid_or_symlinked_file_fails_closed(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            invalid = root / "preferences.json"
            invalid.write_text("{}", encoding="utf-8")
            with self.assertRaises(RuntimePreferencesError):
                RuntimePreferencesStore(invalid).load()

            target = root / "target.json"
            target.write_text("{}", encoding="utf-8")
            link = root / "linked" / "preferences.json"
            link.parent.mkdir()
            link.symlink_to(target)
            with self.assertRaises(RuntimePreferencesError):
                RuntimePreferencesStore(link).load()

    def test_context_must_leave_room_for_model_input(self) -> None:
        with self.assertRaises(ValueError):
            RuntimePreferences(
                context_tokens=2_048,
                default_response_tokens=2_000,
                maximum_response_tokens=2_000,
            )

        with self.assertRaises(ValueError):
            RuntimePreferences(default_response_tokens=True)

    def test_delete_removes_only_the_expected_regular_file(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "preferences.json"
            store = RuntimePreferencesStore(path)
            store.save(RuntimePreferences())

            store.delete()

            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
