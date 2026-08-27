"""Checks for shared, non-secret application settings."""

import unittest

from personal_assistant.config import (
    ChatSettings,
    MemorySettings,
    OllamaSettings,
    SearchSettings,
    load_settings,
)
from personal_assistant.local_http import LocalConnectionError


class AppSettingsTests(unittest.TestCase):
    """Verify defaults and local environment overrides stay predictable."""

    def test_defaults_match_the_initial_local_profile(self) -> None:
        settings = load_settings({})

        self.assertEqual(settings.ollama.model_name, "qwen3:14b")
        self.assertEqual(settings.ollama.context_tokens, 16384)
        self.assertEqual(settings.chat.session_history_tokens, 6000)
        self.assertTrue(settings.memory.enabled)
        self.assertEqual(settings.memory.context_tokens, 2000)
        self.assertEqual(settings.search.base_url, "http://127.0.0.1:8888")

    def test_environment_can_override_machine_local_settings(self) -> None:
        settings = load_settings(
            {
                "PERSONAL_ASSISTANT_MODEL_NAME": "qwen3:8b",
                "PERSONAL_ASSISTANT_CONTEXT_TOKENS": "2048",
                "PERSONAL_ASSISTANT_HISTORY_TOKENS": "1000",
                "PERSONAL_ASSISTANT_LONG_RESPONSE_TOKENS": "900",
                "PERSONAL_ASSISTANT_MAX_RESPONSE_TOKENS": "1000",
            }
        )

        self.assertEqual(settings.ollama.model_name, "qwen3:8b")
        self.assertEqual(settings.ollama.context_tokens, 2048)
        self.assertEqual(settings.chat.session_history_tokens, 1000)
        self.assertEqual(settings.chat.long_response_tokens, 900)

    def test_search_override_must_remain_numeric_loopback(self) -> None:
        settings = load_settings(
            {"PERSONAL_ASSISTANT_SEARXNG_URL": "http://[::1]:9999"}
        )
        self.assertEqual(settings.search.base_url, "http://[::1]:9999")

        for value in (
            "http://localhost:8888",
            "http://192.168.1.2:8888",
            "https://127.0.0.1:8888",
        ):
            with self.subTest(value=value), self.assertRaises(LocalConnectionError):
                SearchSettings(base_url=value)

    def test_memory_paths_and_enablement_are_machine_local(self) -> None:
        settings = load_settings(
            {
                "PERSONAL_ASSISTANT_DATA_DIR": "/tmp/synthetic-assistant-data",
                "PERSONAL_ASSISTANT_BACKUP_DIR": "/tmp/synthetic-backups",
                "PERSONAL_ASSISTANT_MEMORY_ENABLED": "false",
                "PERSONAL_ASSISTANT_AUTOMATIC_MEMORY": "no",
                "PERSONAL_ASSISTANT_MEMORY_TOKENS": "1500",
            }
        )

        self.assertFalse(settings.memory.enabled)
        self.assertFalse(settings.memory.automatic_suggestions)
        self.assertEqual(settings.memory.context_tokens, 1500)
        self.assertEqual(str(settings.memory.backup_directory), "/tmp/synthetic-backups")

    def test_memory_paths_must_be_absolute_and_limits_bounded(self) -> None:
        with self.assertRaises(ValueError):
            load_settings({"PERSONAL_ASSISTANT_DATA_DIR": "relative-data"})
        with self.assertRaises(ValueError):
            load_settings({"PERSONAL_ASSISTANT_MEMORY_ENABLED": "sometimes"})
        with self.assertRaises(ValueError):
            MemorySettings(context_tokens=2501)

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

    def test_remote_ollama_environment_override_is_rejected(self) -> None:
        with self.assertRaises(LocalConnectionError):
            load_settings(
                {"PERSONAL_ASSISTANT_OLLAMA_URL": "http://192.168.1.2:11434"}
            )

    def test_direct_ollama_settings_reject_a_hostname(self) -> None:
        with self.assertRaises(LocalConnectionError):
            OllamaSettings(base_url="http://localhost:11434")

    def test_context_window_accepts_the_full_128k_ceiling(self) -> None:
        settings = load_settings(
            {"PERSONAL_ASSISTANT_CONTEXT_TOKENS": "131072"}
        )

        self.assertEqual(settings.ollama.context_tokens, 131072)

    def test_context_window_rejects_unbounded_resource_values(self) -> None:
        with self.assertRaises(ValueError):
            load_settings({"PERSONAL_ASSISTANT_CONTEXT_TOKENS": "131073"})

    def test_context_window_must_leave_room_for_the_response_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            load_settings({"PERSONAL_ASSISTANT_CONTEXT_TOKENS": "2048"})

    def test_default_response_limit_cannot_exceed_hard_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            OllamaSettings(max_response_tokens=2001)

    def test_chat_ceiling_cannot_exceed_hard_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            ChatSettings(maximum_response_tokens=2001)

    def test_direct_chat_settings_keep_long_limit_below_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            ChatSettings(
                long_response_tokens=1500,
                maximum_response_tokens=1200,
            )

    def test_default_limit_cannot_exceed_configured_chat_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            load_settings(
                {
                    "PERSONAL_ASSISTANT_RESPONSE_TOKENS": "1500",
                    "PERSONAL_ASSISTANT_MAX_RESPONSE_TOKENS": "1200",
                }
            )
