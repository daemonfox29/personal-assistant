"""Local Ollama adapter for the shared language-model contract."""

from collections.abc import Callable, Iterator
import json
from typing import Any
from urllib.error import HTTPError
from urllib.request import Request

from personal_assistant.config import OllamaSettings
from personal_assistant.local_http import open_local
from personal_assistant.model import (
    LanguageModel,
    MalformedModelResponseError,
    ModelNotFoundError,
    ModelMessage,
    ModelRequest,
    ModelRequestError,
    ModelResponse,
    ModelStreamChunk,
    ModelToolCall,
    ModelUnavailableError,
    validate_response_token_limit,
)
from personal_assistant.ollama_service import (
    OllamaService,
    OllamaServiceSettings,
    OllamaUnavailableError,
)


JsonSender = Callable[[str, dict[str, object], float], dict[str, Any]]
JsonStreamer = Callable[[str, dict[str, object], float], Iterator[dict[str, Any]]]
ServiceEnsurer = Callable[[], None]


def _send_json(
    url: str,
    payload: dict[str, object],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Send one JSON request to Ollama's local API."""

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with open_local(request, timeout_seconds) as response:
        return json.loads(response.read())


def _stream_json(
    url: str,
    payload: dict[str, object],
    timeout_seconds: float,
) -> Iterator[dict[str, Any]]:
    """Yield Ollama's newline-delimited JSON response as it arrives."""

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    with open_local(request, timeout_seconds) as response:
        for line in response:
            if line.strip():
                yield json.loads(line)


class OllamaModel(LanguageModel):
    """Generate text through a locally running Ollama service."""

    def __init__(
        self,
        settings: OllamaSettings = OllamaSettings(),
        *,
        send_json: JsonSender = _send_json,
        stream_json: JsonStreamer = _stream_json,
        ensure_service: ServiceEnsurer | None = None,
    ) -> None:
        self._settings = settings
        self._send_json = send_json
        self._stream_json = stream_json
        self._ensure_service = ensure_service or OllamaService(
            OllamaServiceSettings(base_url=settings.base_url)
        ).ensure_available

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate one non-streaming response when the user asks for it."""

        self._ensure_available()
        response = self._checked_request(request)
        message = response.get("message")
        if not isinstance(message, dict):
            raise MalformedModelResponseError("Malformed local model response.")
        tool_calls = self._validated_tool_calls(message.get("tool_calls"))
        content = message.get("content", "")
        if content is None and tool_calls:
            content = ""
        if not isinstance(content, str):
            raise MalformedModelResponseError("Malformed local model response.")
        return ModelResponse(text=content, tool_calls=tool_calls)

    def stream_generate(self, request: ModelRequest) -> Iterator[ModelStreamChunk]:
        """Yield response text as Ollama generates it."""

        self._ensure_available()

        try:
            responses = self._stream_request(request)
            for response in responses:
                yield from self._validated_stream_chunk(response)
        except (ModelNotFoundError, MalformedModelResponseError, ModelRequestError):
            raise
        except HTTPError as error:
            if error.code == 404:
                raise ModelNotFoundError(
                    "The configured local model was not found."
                ) from error
            raise ModelRequestError("The local model request failed.") from error
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            raise ModelRequestError("The local model request failed.") from error

    def _validated_stream_chunk(
        self, response: dict[str, Any]
    ) -> Iterator[ModelStreamChunk]:
        if not isinstance(response, dict):
            raise MalformedModelResponseError("Malformed streaming response.")
        self._raise_response_error(response)
        message = response.get("message")
        if response.get("done") is True and message is None:
            return
        if not isinstance(message, dict):
            raise MalformedModelResponseError("Malformed streaming response.")
        tool_calls = self._validated_tool_calls(message.get("tool_calls"))
        text = message.get("content", "")
        if text is None and tool_calls:
            text = ""
        if not isinstance(text, str):
            raise MalformedModelResponseError("Malformed streaming response.")
        done_reason = response.get("done_reason")
        if done_reason is not None and not isinstance(done_reason, str):
            raise MalformedModelResponseError("Invalid completion reason.")
        if text or done_reason or tool_calls:
            yield ModelStreamChunk(
                text=text,
                done_reason=done_reason,
                tool_calls=tool_calls,
            )

    @staticmethod
    def _validated_tool_calls(value: object) -> tuple[ModelToolCall, ...]:
        if value is None:
            return ()
        if not isinstance(value, list) or len(value) > 4:
            raise MalformedModelResponseError("Malformed model tool calls.")
        calls: list[ModelToolCall] = []
        try:
            for position, item in enumerate(value):
                if not isinstance(item, dict):
                    raise ValueError
                function = item.get("function")
                if not isinstance(function, dict):
                    raise ValueError
                name = function.get("name")
                arguments = function.get("arguments")
                index = function.get("index", item.get("index", position))
                if not isinstance(name, str) or not isinstance(arguments, dict):
                    raise ValueError
                calls.append(
                    ModelToolCall.create(name, arguments, index=index)
                )
        except (TypeError, ValueError) as error:
            raise MalformedModelResponseError(
                "Malformed model tool calls."
            ) from error
        return tuple(calls)

    def _ensure_available(self) -> None:
        try:
            self._ensure_service()
        except OllamaUnavailableError as error:
            raise ModelUnavailableError("Ollama is unavailable.") from error

    def _checked_request(self, request: ModelRequest) -> dict[str, Any]:
        try:
            response = self._send_request(request)
        except HTTPError as error:
            if error.code == 404:
                raise ModelNotFoundError(
                    "The configured local model was not found."
                ) from error
            raise ModelRequestError("The local model request failed.") from error
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            raise ModelRequestError("The local model request failed.") from error
        if not isinstance(response, dict):
            raise MalformedModelResponseError("Malformed local model response.")
        self._raise_response_error(response)
        return response

    def _raise_response_error(self, response: dict[str, Any]) -> None:
        error = response.get("error")
        if error is None:
            return
        if isinstance(error, str) and "not found" in error.lower():
            raise ModelNotFoundError("The configured local model was not found.")
        raise ModelRequestError("The local model rejected the request.")

    def warm_up(self) -> None:
        """Preload the configured model without evaluating a chat prompt."""

        self._ensure_available()
        try:
            response = self._send_json(
                f"{self._settings.base_url}/api/chat",
                {
                    "model": self._settings.model_name,
                    "stream": False,
                    "keep_alive": self._settings.keep_alive,
                },
                self._settings.timeout_seconds,
            )
        except HTTPError as error:
            if error.code == 404:
                raise ModelNotFoundError(
                    "The configured local model was not found."
                ) from error
            raise ModelRequestError("The local model preload failed.") from error
        except (OSError, TimeoutError, json.JSONDecodeError) as error:
            raise ModelRequestError("The local model preload failed.") from error
        if not isinstance(response, dict):
            raise MalformedModelResponseError("Malformed model preload response.")
        self._raise_response_error(response)

    def _send_request(self, request: ModelRequest) -> dict[str, Any]:
        return self._send_json(
            f"{self._settings.base_url}/api/chat",
            self._request_payload(request, stream=False),
            self._settings.timeout_seconds,
        )

    def _stream_request(self, request: ModelRequest) -> Iterator[dict[str, Any]]:
        return self._stream_json(
            f"{self._settings.base_url}/api/chat",
            self._request_payload(request, stream=True),
            self._settings.timeout_seconds,
        )

    def _request_payload(
        self,
        request: ModelRequest,
        *,
        stream: bool,
    ) -> dict[str, object]:
        response_limit = (
            request.max_response_tokens
            if request.max_response_tokens is not None
            else self._settings.max_response_tokens
        )
        validate_response_token_limit(response_limit)
        return {
            "model": self._settings.model_name,
            "messages": [self._message_document(message) for message in request.messages],
            "stream": stream,
            "think": False,
            "keep_alive": self._settings.keep_alive,
            "options": {
                "num_ctx": self._settings.context_tokens,
                "num_predict": response_limit,
            },
            **(
                {
                    "tools": [
                        {
                            "type": "function",
                            "function": {
                                "name": tool.name,
                                "description": tool.description,
                                "parameters": tool.parameters(),
                            },
                        }
                        for tool in request.tools
                    ]
                }
                if request.tools
                else {}
            ),
        }

    @staticmethod
    def _message_document(message: ModelMessage) -> dict[str, object]:
        document: dict[str, object] = {
            "role": message.role.value,
            "content": message.content,
        }
        if message.tool_calls:
            document["tool_calls"] = [
                {
                    "type": "function",
                    "function": {
                        "index": call.index,
                        "name": call.name,
                        "arguments": call.arguments(),
                    },
                }
                for call in message.tool_calls
            ]
        if message.tool_name is not None:
            document["tool_name"] = message.tool_name
        return document
