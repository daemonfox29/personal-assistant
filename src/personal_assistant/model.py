"""Common contract for replaceable language-model adapters."""

from dataclasses import dataclass
from collections.abc import Iterator, Mapping
from enum import StrEnum
import json
import math
import re
from typing import Protocol, runtime_checkable


MAX_RESPONSE_TOKENS = 2000
MAX_TOOL_ARGUMENT_BYTES = 4_096
MAX_TOOL_SCHEMA_BYTES = 8_192
MAX_MODEL_TOOL_CALLS = 4
_TOOL_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


class ModelError(RuntimeError):
    """A safe, expected failure at the language-model boundary."""


class ModelUnavailableError(ModelError):
    """The configured model service cannot currently be reached."""


class ModelNotFoundError(ModelError):
    """The configured model is not installed or available."""


class MalformedModelResponseError(ModelError):
    """The model service returned data that violates the adapter contract."""


class ModelRequestError(ModelError):
    """The model request failed for another safe-to-report reason."""


def validate_response_token_limit(value: int) -> int:
    """Return a valid response limit or reject values outside the hard ceiling."""

    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("The response token limit must be a whole number.")
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
    TOOL = "tool"


def _normalized_json_value(value: object) -> object:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("Tool data cannot contain NaN or infinity.")
        return value
    if isinstance(value, list):
        return [_normalized_json_value(item) for item in value]
    if isinstance(value, Mapping):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("Tool data field names must be strings.")
            normalized[key] = _normalized_json_value(item)
        return normalized
    raise ValueError("Tool data must contain only JSON-compatible values.")


def _canonical_json_object(value: object, byte_limit: int) -> str:
    normalized = _normalized_json_value(value)
    if not isinstance(normalized, dict):
        raise ValueError("Tool data must be a JSON object.")
    canonical = json.dumps(
        normalized,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    if len(canonical.encode("utf-8")) > byte_limit:
        raise ValueError("Tool data exceeds its size limit.")
    return canonical


@dataclass(frozen=True)
class ModelToolDefinition:
    """One immutable code-owned function schema advertised to a model."""

    name: str
    description: str
    parameters_json: str

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("A tool definition name is invalid.")
        if (
            not isinstance(self.description, str)
            or not self.description
            or len(self.description) > 512
        ):
            raise ValueError("A tool definition description is invalid.")
        if not isinstance(self.parameters_json, str):
            raise ValueError("A tool definition schema is invalid.")
        try:
            parameters = json.loads(self.parameters_json)
        except json.JSONDecodeError as error:
            raise ValueError("A tool definition schema is invalid.") from error
        canonical = _canonical_json_object(parameters, MAX_TOOL_SCHEMA_BYTES)
        object.__setattr__(self, "parameters_json", canonical)

    @classmethod
    def create(
        cls,
        name: str,
        description: str,
        parameters: Mapping[str, object],
    ) -> "ModelToolDefinition":
        return cls(
            name,
            description,
            _canonical_json_object(parameters, MAX_TOOL_SCHEMA_BYTES),
        )

    def parameters(self) -> dict[str, object]:
        return json.loads(self.parameters_json)


@dataclass(frozen=True)
class ModelToolCall:
    """One bounded structured function call proposed by a model."""

    name: str
    arguments_json: str
    index: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or _TOOL_NAME.fullmatch(self.name) is None:
            raise ValueError("A model tool-call name is invalid.")
        if (
            isinstance(self.index, bool)
            or not isinstance(self.index, int)
            or not 0 <= self.index < MAX_MODEL_TOOL_CALLS
        ):
            raise ValueError("A model tool-call index is invalid.")
        if not isinstance(self.arguments_json, str):
            raise ValueError("Model tool-call arguments are invalid.")
        try:
            arguments = json.loads(self.arguments_json)
        except json.JSONDecodeError as error:
            raise ValueError("Model tool-call arguments are invalid.") from error
        canonical = _canonical_json_object(arguments, MAX_TOOL_ARGUMENT_BYTES)
        object.__setattr__(self, "arguments_json", canonical)

    @classmethod
    def create(
        cls,
        name: str,
        arguments: Mapping[str, object],
        *,
        index: int = 0,
    ) -> "ModelToolCall":
        return cls(
            name,
            _canonical_json_object(arguments, MAX_TOOL_ARGUMENT_BYTES),
            index,
        )

    def arguments(self) -> dict[str, object]:
        return json.loads(self.arguments_json)


@dataclass(frozen=True)
class ModelMessage:
    """One structurally role-tagged message in a model conversation."""

    role: MessageRole
    content: str
    tool_calls: tuple[ModelToolCall, ...] = ()
    tool_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.role, MessageRole):
            raise ValueError("A model message must use a recognized role.")
        if not isinstance(self.content, str):
            raise ValueError("A model message must contain text.")
        if not isinstance(self.tool_calls, tuple) or not all(
            isinstance(call, ModelToolCall) for call in self.tool_calls
        ):
            raise ValueError("A model message contains invalid tool calls.")
        if len(self.tool_calls) > MAX_MODEL_TOOL_CALLS:
            raise ValueError("A model message contains too many tool calls.")
        if self.tool_calls and self.role is not MessageRole.ASSISTANT:
            raise ValueError("Only assistant messages may propose tool calls.")
        if self.role is MessageRole.TOOL:
            if (
                not isinstance(self.tool_name, str)
                or _TOOL_NAME.fullmatch(self.tool_name) is None
            ):
                raise ValueError("A tool-result message requires a valid tool name.")
        elif self.tool_name is not None:
            raise ValueError("Only tool-result messages may name a tool.")


@dataclass(frozen=True)
class ModelRequest:
    """Structured messages sent to a language model."""

    messages: tuple[ModelMessage, ...]
    max_response_tokens: int | None = None
    tools: tuple[ModelToolDefinition, ...] = ()

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError("A model request must contain at least one message.")
        if self.max_response_tokens is not None:
            validate_response_token_limit(self.max_response_tokens)
        if not isinstance(self.tools, tuple) or not all(
            isinstance(tool, ModelToolDefinition) for tool in self.tools
        ):
            raise ValueError("A model request contains invalid tool definitions.")
        names = [tool.name for tool in self.tools]
        if len(names) != len(set(names)):
            raise ValueError("A model request contains duplicate tool definitions.")


@dataclass(frozen=True)
class ModelResponse:
    """Text returned by a language model."""

    text: str
    tool_calls: tuple[ModelToolCall, ...] = ()


@dataclass(frozen=True)
class ModelStreamChunk:
    """One piece of a streamed response and optional completion metadata."""

    text: str
    done_reason: str | None = None
    tool_calls: tuple[ModelToolCall, ...] = ()


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
