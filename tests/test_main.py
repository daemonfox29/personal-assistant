"""Checks for friendly command-line startup failures."""

import unittest
from unittest.mock import Mock, patch

import personal_assistant.__main__ as main_module
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


if __name__ == "__main__":
    unittest.main()
