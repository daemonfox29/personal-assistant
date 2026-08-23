"""Common contract for replaceable language-model adapters."""

from dataclasses import dataclass
from collections.abc import Iterator
from typing import Protocol, runtime_checkable


MAX_RESPONSE_TOKENS = 2000


def validate_response_token_limit(value: int) -> int:
    """Return a valid response limit or reject values outside the hard ceiling."""

    if value <= 0:
        raise ValueError("The response token limit must be greater than zero.")
    if value > MAX_RESPONSE_TOKENS:
        raise ValueError(
            f"The response token limit cannot exceed {MAX_RESPONSE_TOKENS}."
        )
    return value


@dataclass(frozen=True)
class ModelRequest:
    """A prompt sent to a language model."""

    prompt: str
    max_response_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.max_response_tokens is not None:
            validate_response_token_limit(self.max_response_tokens)


@dataclass(frozen=True)
class ModelResponse:
    """Text returned by a language model."""

    text: str


@dataclass(frozen=True)
class ModelStreamChunk:
    """One piece of a streamed response and optional completion metadata."""

    text: str
    done_reason: str | None = None


@runtime_checkable
class LanguageModel(Protocol):
    """The behavior required from any language-model adapter."""

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate a response for a model request."""


@runtime_checkable
class StreamingLanguageModel(Protocol):
    """Optional behavior for adapters that can yield a response in pieces."""

    def stream_generate(self, request: ModelRequest) -> Iterator[ModelStreamChunk]:
        """Yield response pieces as they become available."""
