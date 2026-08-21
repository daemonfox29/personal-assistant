"""Start and check the local Ollama service without loading a model."""

from collections.abc import Callable
from dataclasses import dataclass
import subprocess
import time
from urllib.error import URLError
from urllib.request import Request, urlopen


HealthCheck = Callable[[str, float], bool]
ServiceLauncher = Callable[[], None]
Sleeper = Callable[[float], None]


class OllamaUnavailableError(RuntimeError):
    """Raised when the local Ollama service cannot be started."""


@dataclass(frozen=True)
class OllamaServiceSettings:
    """Settings for checking and starting the local Ollama service."""

    base_url: str = "http://127.0.0.1:11434"
    timeout_seconds: float = 2.0
    startup_attempts: int = 20
    retry_interval_seconds: float = 0.25


def _is_available(base_url: str, timeout_seconds: float) -> bool:
    """Return whether Ollama's local service responds without loading a model."""

    request = Request(f"{base_url}/api/tags", method="GET")

    try:
        with urlopen(request, timeout=timeout_seconds):
            return True
    except URLError:
        return False


def _launch_macos_app() -> None:
    """Launch Ollama in the background on macOS."""

    subprocess.run(["open", "-j", "-a", "Ollama"], check=True)


class OllamaService:
    """Ensure the local service is ready before a model request is sent."""

    def __init__(
        self,
        settings: OllamaServiceSettings = OllamaServiceSettings(),
        *,
        health_check: HealthCheck = _is_available,
        launch_service: ServiceLauncher = _launch_macos_app,
        sleep: Sleeper = time.sleep,
    ) -> None:
        self._settings = settings
        self._health_check = health_check
        self._launch_service = launch_service
        self._sleep = sleep

    def ensure_available(self) -> None:
        """Start Ollama only when needed, then wait until its API responds."""

        if self._is_available():
            return

        self._launch_service()

        for _ in range(self._settings.startup_attempts):
            self._sleep(self._settings.retry_interval_seconds)
            if self._is_available():
                return

        raise OllamaUnavailableError(
            "Ollama did not become available after it was started."
        )

    def _is_available(self) -> bool:
        return self._health_check(
            self._settings.base_url,
            self._settings.timeout_seconds,
        )
