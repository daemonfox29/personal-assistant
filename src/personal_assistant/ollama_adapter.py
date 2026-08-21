"""Local Ollama adapter for the shared language-model contract."""

from collections.abc import Callable
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
ServiceEnsurer = Callable[[], None]


@dataclass(frozen=True)
class OllamaSettings:
    """Resource-conscious settings for the local Ollama connection."""

    base_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen3:14b"
    context_tokens: int = 8192
    keep_alive: str = "2m"
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


class OllamaModel(LanguageModel):
    """Generate text through a locally running Ollama service."""

    def __init__(
        self,
        settings: OllamaSettings = OllamaSettings(),
        *,
        send_json: JsonSender = _send_json,
        ensure_service: ServiceEnsurer | None = None,
    ) -> None:
        self._settings = settings
        self._send_json = send_json
        self._ensure_service = ensure_service or OllamaService(
            OllamaServiceSettings(base_url=settings.base_url)
        ).ensure_available

    def generate(self, request: ModelRequest) -> ModelResponse:
        """Generate one non-streaming response when the user asks for it."""

        self._ensure_service()

        response = self._send_json(
            f"{self._settings.base_url}/api/generate",
            {
                "model": self._settings.model_name,
                "prompt": request.prompt,
                "stream": False,
                "think": False,
                "keep_alive": self._settings.keep_alive,
                "options": {"num_ctx": self._settings.context_tokens},
            },
            self._settings.timeout_seconds,
        )

        return ModelResponse(text=response["response"])
