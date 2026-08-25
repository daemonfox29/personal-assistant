"""Checks for friendly command-line startup failures."""

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import personal_assistant.__main__ as main_module
from personal_assistant.config import MemorySettings
from personal_assistant.model import ModelUnavailableError


class MainTests(unittest.TestCase):
    @patch("builtins.print")
    @patch("personal_assistant.__main__.OllamaModel")
    def test_unavailable_ollama_has_a_friendly_startup_message(
        self, model_type: Mock, write_output: Mock
    ) -> None:
        model_type.return_value.warm_up.side_effect = ModelUnavailableError()

        main_module.main()

        write_output.assert_called_with(
            "Ollama is unavailable. Check that it is installed and try again."
        )

    @patch("builtins.print")
    @patch("personal_assistant.__main__.load_settings")
    def test_invalid_configuration_does_not_expose_internal_details(
        self, load_settings: Mock, write_output: Mock
    ) -> None:
        load_settings.side_effect = ValueError("sensitive machine-local value")

        main_module.main()

        write_output.assert_called_with(
            "The assistant configuration is invalid. Check local settings."
        )
        self.assertNotIn(
            "sensitive machine-local value",
            str(write_output.call_args_list),
        )

    @patch("builtins.print")
    def test_new_installation_stays_session_only_without_prompting_for_recovery(
        self,
        write_output: Mock,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            settings = MemorySettings(
                data_directory=Path(temporary_directory) / "private"
            )
            with patch("personal_assistant.__main__.getpass") as get_secret:
                runtime = main_module._open_memory_runtime(settings)

        self.assertIsNone(runtime)
        get_secret.assert_not_called()
        self.assertIn("session-only mode", write_output.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
