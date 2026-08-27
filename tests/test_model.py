"""Checks for the replaceable language-model contract."""

import unittest

from personal_assistant.model import (
    LanguageModel,
    MAX_RESPONSE_TOKENS,
    MessageRole,
    ModelMessage,
    ModelRequest,
    ModelResponse,
    ModelStreamChunk,
    ModelToolCall,
    ModelToolDefinition,
    StreamingLanguageModel,
)


class EchoModel:
    """A tiny test-only model that returns the prompt unchanged."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(text=request.messages[-1].content)


class StreamingEchoModel(EchoModel):
    """A test-only model that can return text gradually."""

    def stream_generate(self, request: ModelRequest):
        yield ModelStreamChunk(text=request.messages[-1].content)


def user_request(
    text: str,
    *,
    max_response_tokens: int | None = None,
) -> ModelRequest:
    return ModelRequest(
        messages=(ModelMessage(MessageRole.USER, text),),
        max_response_tokens=max_response_tokens,
    )


class ModelContractTests(unittest.TestCase):
    """Verify that a model adapter can follow the shared contract."""

    def test_model_adapter_matches_the_contract(self) -> None:
        model = EchoModel()

        self.assertIsInstance(model, LanguageModel)

    def test_model_adapter_returns_a_response(self) -> None:
        model = EchoModel()

        response = model.generate(user_request("Hello"))

        self.assertEqual(response.text, "Hello")

    def test_streaming_model_matches_the_optional_contract(self) -> None:
        model = StreamingEchoModel()

        self.assertIsInstance(model, StreamingLanguageModel)
        self.assertEqual(
            list(model.stream_generate(user_request("Hello"))),
            [ModelStreamChunk(text="Hello")],
        )

    def test_request_accepts_the_shared_response_ceiling(self) -> None:
        request = user_request("Hello", max_response_tokens=MAX_RESPONSE_TOKENS)

        self.assertEqual(request.max_response_tokens, 2000)

    def test_request_rejects_a_limit_above_the_shared_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            user_request("Hello", max_response_tokens=MAX_RESPONSE_TOKENS + 1)

    def test_request_rejects_a_non_positive_limit(self) -> None:
        with self.assertRaises(ValueError):
            user_request("Hello", max_response_tokens=0)

    def test_request_rejects_an_empty_message_list(self) -> None:
        with self.assertRaises(ValueError):
            ModelRequest(messages=())

    def test_message_rejects_an_unknown_role(self) -> None:
        with self.assertRaises(ValueError):
            ModelMessage("assistant: user-controlled", "Hello")  # type: ignore[arg-type]

    def test_tool_definitions_calls_and_messages_are_structured_and_bounded(self) -> None:
        definition = ModelToolDefinition.create(
            "synthetic_tool",
            "Return one synthetic value.",
            {
                "type": "object",
                "properties": {"value": {"type": "number"}},
                "required": ["value"],
            },
        )
        call = ModelToolCall.create("synthetic_tool", {"value": 2})
        assistant = ModelMessage(
            MessageRole.ASSISTANT,
            "",
            tool_calls=(call,),
        )
        result = ModelMessage(
            MessageRole.TOOL,
            '{"ok":true}',
            tool_name="synthetic_tool",
        )
        request = ModelRequest((assistant, result), tools=(definition,))

        self.assertEqual(request.tools[0].parameters()["type"], "object")
        self.assertEqual(call.arguments(), {"value": 2})

    def test_tool_data_rejects_nonfinite_oversized_and_role_confusion(self) -> None:
        with self.assertRaises(ValueError):
            ModelToolCall.create("synthetic_tool", {"value": float("nan")})
        with self.assertRaises(ValueError):
            ModelToolCall.create("synthetic_tool", {"value": "x" * 5_000})
        with self.assertRaises(ValueError):
            ModelMessage(MessageRole.USER, "", tool_name="synthetic_tool")
        with self.assertRaises(ValueError):
            ModelMessage(MessageRole.TOOL, "{}")
