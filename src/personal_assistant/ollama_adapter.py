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
    ModelRequest,
    ModelRequestError,
    ModelResponse,
    ModelStreamChunk,
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
        if not isinstance(message, dict) or not isinstance(
            message.get("content"), str
        ):
            raise MalformedModelResponseError("Malformed local model response.")
        return ModelResponse(text=message["content"])

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
        if not isinstance(message, dict) or not isinstance(
            message.get("content"), str
        ):
            raise MalformedModelResponseError("Malformed streaming response.")
        text = message["content"]
        done_reason = response.get("done_reason")
        if done_reason is not None and not isinstance(done_reason, str):
            raise MalformedModelResponseError("Invalid completion reason.")
        if text or done_reason:
            yield ModelStreamChunk(text=text, done_reason=done_reason)

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
            "messages": [
                {"role": message.role.value, "content": message.content}
                for message in request.messages
            ],
            "stream": stream,
            "think": False,
            "keep_alive": self._settings.keep_alive,
            "options": {
                "num_ctx": self._settings.context_tokens,
                "num_predict": response_limit,
            },
        }
