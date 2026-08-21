"""Checks for shared, non-secret application settings."""

import unittest

from personal_assistant.config import load_settings


class AppSettingsTests(unittest.TestCase):
    """Verify defaults and local environment overrides stay predictable."""

    def test_defaults_match_the_initial_local_profile(self) -> None:
        settings = load_settings({})

        self.assertEqual(settings.ollama.model_name, "qwen3:14b")
        self.assertEqual(settings.ollama.context_tokens, 4096)
        self.assertEqual(settings.chat.session_history_characters, 6000)

    def test_environment_can_override_machine_local_settings(self) -> None:
        settings = load_settings(
            {
                "PERSONAL_ASSISTANT_MODEL_NAME": "qwen3:8b",
                "PERSONAL_ASSISTANT_CONTEXT_TOKENS": "2048",
                "PERSONAL_ASSISTANT_LONG_RESPONSE_TOKENS": "900",
            }
        )

        self.assertEqual(settings.ollama.model_name, "qwen3:8b")
        self.assertEqual(settings.ollama.context_tokens, 2048)
        self.assertEqual(settings.chat.long_response_tokens, 900)

    def test_non_positive_environment_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            load_settings({"PERSONAL_ASSISTANT_CONTEXT_TOKENS": "0"})

    def test_long_response_limit_cannot_exceed_maximum_limit(self) -> None:
        with self.assertRaises(ValueError):
            load_settings(
                {
                    "PERSONAL_ASSISTANT_LONG_RESPONSE_TOKENS": "1201",
                    "PERSONAL_ASSISTANT_MAX_RESPONSE_TOKENS": "1200",
                }
            )
