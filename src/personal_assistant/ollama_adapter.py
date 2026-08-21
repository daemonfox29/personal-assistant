"""Local Ollama adapter for the shared language-model contract."""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
import json
from typing import Any
from urllib.request import Request, urlopen

from personal_assistant.model import (
    LanguageModel,
    ModelRequest,
    ModelResponse,
)
from personal_assistant.ollama_service import OllamaService, OllamaServiceSettings


JsonSender = Callable[[str, dict[str, object], float], dict[str, Any]]
JsonStreamer = Callable[[str, dict[str, object], float], Iterator[dict[str, Any]]]
ServiceEnsurer = Callable[[], None]


@dataclass(frozen=True)
class OllamaSettings:
    """Resource-conscious settings for the local Ollama connection."""

    base_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen3:14b"
    context_tokens: int = 8192
    keep_alive: str = "5m"
    timeout_seconds: float = 120.0


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

    with urlopen(request, timeout=timeout_seconds) as response:
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

    with urlopen(request, timeout=timeout_seconds) as response:
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

        response = self._send_request(request.prompt)

        return ModelResponse(text=response["response"])

    def stream_generate(self, request: ModelRequest) -> Iterator[str]:
        """Yield response text as Ollama generates it."""

        self._ensure_service()

        for response in self._stream_request(request.prompt):
            text = response.get("response", "")
            if isinstance(text, str) and text:
                yield text

    def warm_up(self) -> None:
        """Load the configured model when the assistant application starts."""

        self._ensure_service()
        self._send_request("")

    def _send_request(self, prompt: str) -> dict[str, Any]:
        return self._send_json(
            f"{self._settings.base_url}/api/generate",
            self._request_payload(prompt, stream=False),
            self._settings.timeout_seconds,
        )

    def _stream_request(self, prompt: str) -> Iterator[dict[str, Any]]:
        return self._stream_json(
            f"{self._settings.base_url}/api/generate",
            self._request_payload(prompt, stream=True),
            self._settings.timeout_seconds,
        )

    def _request_payload(self, prompt: str, *, stream: bool) -> dict[str, object]:
        return {
            "model": self._settings.model_name,
            "prompt": prompt,
            "stream": stream,
            "think": False,
            "keep_alive": self._settings.keep_alive,
            "options": {"num_ctx": self._settings.context_tokens},
        }
