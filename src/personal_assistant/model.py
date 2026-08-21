"""Common contract for replaceable language-model adapters."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class ModelRequest:
    """A prompt sent to a language model."""

    prompt: str


@dataclass(frozen=True)
class ModelResponse:
    """Text returned by a language model."""

    text: str


@runtime_checkable
class LanguageModel(Protocol):
    """The behavior required from any language-model adapter."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate a response for a model request."""
