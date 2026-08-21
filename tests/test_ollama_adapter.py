"""Checks for the local Ollama model adapter."""

import unittest
from unittest.mock import Mock

from personal_assistant.model import ModelRequest
from personal_assistant.ollama_adapter import OllamaModel, OllamaSettings


class OllamaAdapterTests(unittest.TestCase):
    """Verify local-only, resource-conscious Ollama requests."""

    def test_constructing_the_adapter_does_not_contact_ollama(self) -> None:
        sender = Mock()

        OllamaModel(send_json=sender)

        sender.assert_not_called()

    def test_generate_uses_the_expected_local_settings(self) -> None:
        sender = Mock(return_value={"response": "Local reply"})
        ensure_service = Mock()
        model = OllamaModel(
            send_json=sender,
            ensure_service=ensure_service,
        )

        response = model.generate(ModelRequest(prompt="Hello"))

        self.assertEqual(response.text, "Local reply")
        ensure_service.assert_called_once_with()
        sender.assert_called_once_with(
            "http://127.0.0.1:11434/api/generate",
            {
                "model": "qwen3:14b",
                "prompt": "Hello",
                "stream": False,
                "think": False,
                "keep_alive": "2m",
                "options": {"num_ctx": 8192},
            },
            120.0,
        )

    def test_settings_can_be_changed_without_changing_the_adapter(self) -> None:
        sender = Mock(return_value={"response": "Alternative reply"})
        settings = OllamaSettings(
            model_name="qwen3:8b",
            context_tokens=4096,
            keep_alive="0",
        )
        model = OllamaModel(
            settings,
            send_json=sender,
            ensure_service=Mock(),
        )

        model.generate(ModelRequest(prompt="Hello"))

        payload = sender.call_args.args[1]
        self.assertEqual(payload["model"], "qwen3:8b")
        self.assertEqual(payload["keep_alive"], "0")
        self.assertEqual(payload["options"], {"num_ctx": 4096})
