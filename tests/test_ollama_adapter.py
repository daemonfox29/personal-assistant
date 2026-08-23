"""Checks for the local Ollama model adapter."""

import unittest
from unittest.mock import Mock

from personal_assistant.model import (
    MalformedModelResponseError,
    MessageRole,
    ModelMessage,
    ModelRequest,
    ModelStreamChunk,
    ModelNotFoundError,
    ModelUnavailableError,
    response_instruction,
)
from personal_assistant.ollama_adapter import OllamaModel, OllamaSettings
from personal_assistant.ollama_service import OllamaUnavailableError


def chat_request(
    text: str,
    *,
    max_response_tokens: int | None = None,
) -> ModelRequest:
    response_limit = max_response_tokens or 400
    return ModelRequest(
        messages=(
            ModelMessage(MessageRole.SYSTEM, response_instruction(response_limit)),
            ModelMessage(MessageRole.USER, text),
        ),
        max_response_tokens=max_response_tokens,
    )


class OllamaAdapterTests(unittest.TestCase):
    """Verify local-only, resource-conscious Ollama requests."""

    def test_constructing_the_adapter_does_not_contact_ollama(self) -> None:
        sender = Mock()

        OllamaModel(send_json=sender)

        sender.assert_not_called()

    def test_generate_uses_the_expected_local_settings(self) -> None:
        sender = Mock(return_value={"message": {"content": "Local reply"}})
        ensure_service = Mock()
        model = OllamaModel(
            send_json=sender,
            ensure_service=ensure_service,
        )

        response = model.generate(chat_request("Hello"))

        self.assertEqual(response.text, "Local reply")
        ensure_service.assert_called_once_with()
        sender.assert_called_once_with(
            "http://127.0.0.1:11434/api/chat",
            {
                "model": "qwen3:14b",
                "messages": [
                    {
                        "role": "system",
                        "content": response_instruction(400),
                    },
                    {"role": "user", "content": "Hello"},
                ],
                "stream": False,
                "think": False,
                "keep_alive": "5m",
                "options": {"num_ctx": 16384, "num_predict": 400},
            },
            120.0,
        )

    def test_settings_can_be_changed_without_changing_the_adapter(self) -> None:
        sender = Mock(return_value={"message": {"content": "Alternative reply"}})
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

        model.generate(chat_request("Hello", max_response_tokens=200))

        payload = sender.call_args.args[1]
        self.assertEqual(payload["model"], "qwen3:8b")
        self.assertEqual(payload["keep_alive"], "0")
        self.assertEqual(
            payload["options"],
            {"num_ctx": 4096, "num_predict": 200},
        )

    def test_warm_up_loads_the_model_with_the_configured_settings(self) -> None:
        sender = Mock(return_value={"message": {"content": ""}})
        ensure_service = Mock()
        model = OllamaModel(
            send_json=sender,
            ensure_service=ensure_service,
        )

        model.warm_up()

        ensure_service.assert_called_once_with()
        payload = sender.call_args.args[1]
        self.assertEqual(
            payload["messages"],
            [{"role": "user", "content": ""}],
        )
        self.assertEqual(payload["model"], "qwen3:14b")
        self.assertEqual(payload["keep_alive"], "5m")

    def test_stream_generate_yields_each_response_piece(self) -> None:
        stream_json = Mock(
            return_value=iter(
                [
                    {"message": {"content": "Local"}},
                    {"message": {"content": " reply"}},
                    {"done": True},
                ]
            )
        )
        model = OllamaModel(
            stream_json=stream_json,
            ensure_service=Mock(),
        )

        response_chunks = list(model.stream_generate(chat_request("Hello")))

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
            {"num_ctx": 16384, "num_predict": 400},
        )

    def test_explicit_long_request_uses_its_response_cap(self) -> None:
        sender = Mock(return_value={"message": {"content": "A longer reply"}})
        model = OllamaModel(send_json=sender, ensure_service=Mock())

        model.generate(
            chat_request("Explain in detail", max_response_tokens=1200)
        )

        payload = sender.call_args.args[1]
        self.assertEqual(payload["options"]["num_predict"], 1200)
        self.assertEqual(
            payload["messages"][0],
            {"role": "system", "content": response_instruction(1200)},
        )

    def test_non_positive_response_cap_is_rejected(self) -> None:
        model = OllamaModel(send_json=Mock(), ensure_service=Mock())

        with self.assertRaises(ValueError):
            model.generate(chat_request("Hello", max_response_tokens=0))

    def test_shared_response_ceiling_is_applied_to_ollama(self) -> None:
        sender = Mock(return_value={"message": {"content": "Maximum reply"}})
        model = OllamaModel(send_json=sender, ensure_service=Mock())

        model.generate(chat_request("Hello", max_response_tokens=2000))

        payload = sender.call_args.args[1]
        self.assertEqual(payload["options"]["num_predict"], 2000)

    def test_missing_model_error_is_classified_without_exposing_raw_text(self) -> None:
        model = OllamaModel(
            send_json=Mock(return_value={"error": "model qwen-secret not found"}),
            ensure_service=Mock(),
        )

        with self.assertRaises(ModelNotFoundError):
            model.generate(chat_request("Hello"))

    def test_malformed_non_streaming_response_is_rejected(self) -> None:
        model = OllamaModel(
            send_json=Mock(return_value={"message": {"content": 42}}),
            ensure_service=Mock(),
        )

        with self.assertRaises(MalformedModelResponseError):
            model.generate(chat_request("Hello"))

    def test_malformed_streaming_response_is_rejected(self) -> None:
        model = OllamaModel(
            stream_json=Mock(return_value=iter([{"message": "not-an-object"}])),
            ensure_service=Mock(),
        )

        with self.assertRaises(MalformedModelResponseError):
            list(model.stream_generate(chat_request("Hello")))

    def test_unavailable_service_is_translated_to_model_boundary_error(self) -> None:
        ensure_service = Mock(side_effect=OllamaUnavailableError("internal detail"))
        model = OllamaModel(ensure_service=ensure_service)

        with self.assertRaises(ModelUnavailableError):
            model.generate(chat_request("Hello"))
