"""Local Ollama adapter for the shared language-model contract."""

from collections.abc import Callable, Iterator
import json
from typing import Any
from urllib.request import Request

from personal_assistant.model import (
    LanguageModel,
    ModelRequest,
    ModelResponse,
    ModelStreamChunk,
    validate_response_token_limit,
)
from personal_assistant.config import OllamaSettings
from personal_assistant.local_http import open_local
from personal_assistant.ollama_service import OllamaService, OllamaServiceSettings


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

        self._ensure_service()

        response = self._send_request(request)

        return ModelResponse(text=response["response"])

    def stream_generate(self, request: ModelRequest) -> Iterator[ModelStreamChunk]:
        """Yield response text as Ollama generates it."""

        self._ensure_service()

        for response in self._stream_request(request):
            text = response.get("response", "")
            done_reason = response.get("done_reason")
            response_text = text if isinstance(text, str) else ""
            completion_reason = (
                done_reason if isinstance(done_reason, str) else None
            )
            if response_text or completion_reason:
                yield ModelStreamChunk(
                    text=response_text,
                    done_reason=completion_reason,
                )

    def warm_up(self) -> None:
        """Load the configured model when the assistant application starts."""

        self._ensure_service()
        self._send_request(ModelRequest(prompt=""))

    def _send_request(self, request: ModelRequest) -> dict[str, Any]:
        return self._send_json(
            f"{self._settings.base_url}/api/generate",
            self._request_payload(request, stream=False),
            self._settings.timeout_seconds,
        )

    def _stream_request(self, request: ModelRequest) -> Iterator[dict[str, Any]]:
        return self._stream_json(
            f"{self._settings.base_url}/api/generate",
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
            "prompt": request.prompt,
            "stream": stream,
            "think": False,
            "system": self._response_instruction(response_limit),
            "keep_alive": self._settings.keep_alive,
            "options": {
                "num_ctx": self._settings.context_tokens,
                "num_predict": response_limit,
            },
        }

    def _response_instruction(self, response_limit: int) -> str:
        return (
            f"Answer the user's request completely within {response_limit} tokens "
            "or fewer. Be concise. If it cannot fit, provide the most useful "
            "complete answer possible and offer to continue."
        )
