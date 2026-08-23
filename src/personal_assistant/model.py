"""Common contract for replaceable language-model adapters."""

from dataclasses import dataclass
from collections.abc import Iterator
from enum import StrEnum
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


def response_instruction(response_limit: int) -> str:
    """Return the shared system instruction for one response budget."""

    validate_response_token_limit(response_limit)
    return (
        f"Answer the user's request completely within {response_limit} tokens "
        "or fewer. Be concise. If it cannot fit, provide the most useful "
        "complete answer possible and offer to continue."
    )


class MessageRole(StrEnum):
    """Roles that remain structurally separate in a model request."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True)
class ModelMessage:
    """One trusted role-tagged message in a model conversation."""

    role: MessageRole
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.role, MessageRole):
            raise ValueError("A model message must use a recognized role.")


@dataclass(frozen=True)
class ModelRequest:
    """Structured messages sent to a language model."""

    messages: tuple[ModelMessage, ...]
    max_response_tokens: int | None = None

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("A model request must contain at least one message.")
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
