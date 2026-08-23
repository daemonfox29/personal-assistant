"""Checks for the replaceable language-model contract."""

import unittest

from personal_assistant.model import (
    LanguageModel,
    MAX_RESPONSE_TOKENS,
    ModelRequest,
    ModelResponse,
    ModelStreamChunk,
    StreamingLanguageModel,
)


class EchoModel:
    """A tiny test-only model that returns the prompt unchanged."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(text=request.prompt)


class StreamingEchoModel(EchoModel):
    """A test-only model that can return text gradually."""

    def stream_generate(self, request: ModelRequest):
        yield ModelStreamChunk(text=request.prompt)


class ModelContractTests(unittest.TestCase):
    """Verify that a model adapter can follow the shared contract."""

    def test_model_adapter_matches_the_contract(self) -> None:
        model = EchoModel()

        self.assertIsInstance(model, LanguageModel)

    def test_model_adapter_returns_a_response(self) -> None:
        model = EchoModel()

        response = model.generate(ModelRequest(prompt="Hello"))

        self.assertEqual(response.text, "Hello")

    def test_streaming_model_matches_the_optional_contract(self) -> None:
        model = StreamingEchoModel()

        self.assertIsInstance(model, StreamingLanguageModel)
        self.assertEqual(
            list(model.stream_generate(ModelRequest(prompt="Hello"))),
            [ModelStreamChunk(text="Hello")],
        )

    def test_request_accepts_the_shared_response_ceiling(self) -> None:
        request = ModelRequest(
            prompt="Hello",
            max_response_tokens=MAX_RESPONSE_TOKENS,
        )

        self.assertEqual(request.max_response_tokens, 2000)

    def test_request_rejects_a_limit_above_the_shared_ceiling(self) -> None:
        with self.assertRaises(ValueError):
            ModelRequest(
                prompt="Hello",
                max_response_tokens=MAX_RESPONSE_TOKENS + 1,
            )

    def test_request_rejects_a_non_positive_limit(self) -> None:
        with self.assertRaises(ValueError):
            ModelRequest(prompt="Hello", max_response_tokens=0)
