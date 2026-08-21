"""Checks for the replaceable language-model contract."""

import unittest

from personal_assistant.model import (
    LanguageModel,
    ModelRequest,
    ModelResponse,
)


class EchoModel:
    """A tiny test-only model that returns the prompt unchanged."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(text=request.prompt)


class ModelContractTests(unittest.TestCase):
    """Verify that a model adapter can follow the shared contract."""

    def test_model_adapter_matches_the_contract(self) -> None:
        model = EchoModel()

        self.assertIsInstance(model, LanguageModel)

    def test_model_adapter_returns_a_response(self) -> None:
        model = EchoModel()

        response = model.generate(ModelRequest(prompt="Hello"))

        self.assertEqual(response.text, "Hello")
