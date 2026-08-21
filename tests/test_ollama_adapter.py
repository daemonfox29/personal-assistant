"""Checks for the local Ollama model adapter."""

import unittest
from unittest.mock import Mock

from personal_assistant.model import ModelRequest, ModelStreamChunk
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
                "system": (
                    "Answer the user's request completely within 400 tokens or fewer. "
                    "Be concise. If it cannot fit, provide the most useful complete "
                    "answer possible and offer to continue."
                ),
                "keep_alive": "5m",
                "options": {"num_ctx": 4096, "num_predict": 400},
            },
            120.0,
        )

    def test_settings_can_be_changed_without_changing_the_adapter(self) -> None:
        sender = Mock(return_value={"response": "Alternative reply"})
        settings = OllamaSettings(
            model_name="qwen3:8b",
            context_tokens=4096,
            max_response_tokens=200,
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
        self.assertEqual(
            payload["options"],
            {"num_ctx": 4096, "num_predict": 200},
        )

    def test_warm_up_loads_the_model_with_the_configured_settings(self) -> None:
        sender = Mock(return_value={"response": ""})
        ensure_service = Mock()
        model = OllamaModel(
            send_json=sender,
            ensure_service=ensure_service,
        )

        model.warm_up()

        ensure_service.assert_called_once_with()
        payload = sender.call_args.args[1]
        self.assertEqual(payload["prompt"], "")
        self.assertEqual(payload["model"], "qwen3:14b")
        self.assertEqual(payload["keep_alive"], "5m")

    def test_stream_generate_yields_each_response_piece(self) -> None:
        stream_json = Mock(
            return_value=iter(
                [
                    {"response": "Local"},
                    {"response": " reply"},
                    {"done": True},
                ]
            )
        )
        model = OllamaModel(
            stream_json=stream_json,
            ensure_service=Mock(),
        )

        response_chunks = list(model.stream_generate(ModelRequest(prompt="Hello")))

        self.assertEqual(
            response_chunks,
            [ModelStreamChunk(text="Local"), ModelStreamChunk(text=" reply")],
        )
        payload = stream_json.call_args.args[1]
        self.assertTrue(payload["stream"])
        self.assertFalse(payload["think"])
        self.assertEqual(payload["keep_alive"], "5m")
        self.assertEqual(
            payload["options"],
            {"num_ctx": 4096, "num_predict": 400},
        )

    def test_explicit_long_request_uses_its_response_cap(self) -> None:
        sender = Mock(return_value={"response": "A longer reply"})
        model = OllamaModel(send_json=sender, ensure_service=Mock())

        model.generate(
            ModelRequest(prompt="Explain in detail", max_response_tokens=1200)
        )

        payload = sender.call_args.args[1]
        self.assertEqual(payload["options"]["num_predict"], 1200)
        self.assertEqual(
            payload["system"],
            "Answer the user's request completely within 1200 tokens or fewer. "
            "Be concise. If it cannot fit, provide the most useful complete "
            "answer possible and offer to continue.",
        )

    def test_non_positive_response_cap_is_rejected(self) -> None:
        model = OllamaModel(send_json=Mock(), ensure_service=Mock())

        with self.assertRaises(ValueError):
            model.generate(ModelRequest(prompt="Hello", max_response_tokens=0))
